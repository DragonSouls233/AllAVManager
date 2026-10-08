"""出站 HTTP 录制 / 离线回放（P1-1，来源 ref114-amane observability 设计）

## 解决什么
站点改版后，要复现「某天刮削某番号为啥失败 / 解析出啥」，以往只能现场再抓一次——
而此时站点可能已经改版、或当天返回的就是脏数据。录制回放把**每一次出站 HTTP 响应正文**
连同请求一起落盘，之后可完全离线、确定性地重放整条刮削链路，用于：
- 调试爬虫解析（站点改版前录一份，改版后离线比对差异）
- 复现偶发失败（限流页 / soft404 / 编码错乱），不依赖当时网络
- 给同事 / CI 一份可重放的"现场"，不用真连外网

## 设计（对齐 ref114）
- 落盘布局：`<rec_dir>/http/index.jsonl`（每行一条交换）+ `<rec_dir>/http/bodies/{seq}.*`。
- WebClient 透明接入：通过 http_client 模块的 ContextVar 开关，录制**只在显式开启时**
  发生，生产路径默认零开销（不创建文件、不读响应体）。
- 脱敏：索引不收录 `Cookie` / `Authorization` / `Proxy-Authorization`，响应正文照存
  （正文本就无密钥；若含登录态 cookie 那是站点行为，不在索引里暴露即可）。
- 回放：`ReplayWebClient` 是 `AsyncHttpClient` 的 duck-typed 替代品，按
  `method + 归一化URL` 匹配；返回 `RecordedResponse`（兼容
  `AsyncHttpClient.resp_to_text` / `resp_to_html` 用到的 `.content/.text/.encoding/.url/.status_code/.headers/.json()`）。

## 三不（实测踩坑的预防）
1. **绝不在生产默认开启**：录制开关只由 `MDCX_HTTP_RECORD_DIR` 环境变量或程序化
   `set_active_http_recorder` 触发；两者皆空则 `_record_exchange_if_active` 直接 return。
2. **绝不为录制读取/复制大响应体而拖慢主流程**：录制在线程外尽力执行，异常一律吞掉，
   一次记录失败绝不能变成一次刮削失败。
3. **回放 URL 必须归一化**：同一请求带不同签名 / 时间戳参数时也要命中同一录制，否则
   离线重放会 404。归一化规则见 `_normalize_url`（去噪 query key、排序、小写 host）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# 录制索引里**不收录**的请求/响应头（与 ref114 一致：避免把登录态 cookie / token 写进磁盘）
_SENSITIVE_HEADERS = {
    "cookie",
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
}

# 归一化时忽略的"噪声 query 参数"：签名、时间戳、随机数、追踪 id 等，
# 这些每次请求都不同，但对应的响应正文通常相同，忽略它们才能让回放稳定命中。
_NOISE_QUERY_KEYS = {
    "signature", "sig", "sign", "_", "t", "ts", "timestamp", "nonce", "rand",
    "rnd", "cb", "_dc", "v", "ver", "utm_source", "utm_medium", "utm_campaign",
    "ref", "referer", "spm", "csrf", "csrf_token", "token", "_t",
}


def _sanitize_headers(headers: Optional[dict]) -> dict:
    """剔除敏感头，其余保留（大小写不敏感匹配键名）。"""
    if not headers:
        return {}
    out: dict[str, str] = {}
    for k, v in headers.items():
        if str(k).lower() in _SENSITIVE_HEADERS:
            continue
        out[str(k)] = str(v)
    return out


def _normalize_url(url: str, params: Optional[dict] = None) -> str:
    """归一化 URL 用于回放匹配。

    - 合并显式 ``params`` 到 query（爬虫常把分页/搜索参数放 kwargs['params']）
    - 小写 scheme/host
    - 丢弃噪声 query key
    - query 参数按 key 排序，保证 `?a=1&b=2` 与 `?b=2&a=1` 等价
    - 去掉默认 80/443 端口、去掉 fragment
    """
    if params:
        # params 可能是 dict 或 list[(k,v)]
        try:
            extra = urlencode(params, doseq=True)
            sep = "&" if "?" in url else "?"
            url = url + sep + extra
        except Exception:
            pass
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
        if port in (80, 443, None):
            port = None
        q = parse_qsl(parts.query, keep_blank_values=True)
        q = [(k, v) for k, v in q if k.lower() not in _NOISE_QUERY_KEYS]
        q.sort(key=lambda kv: kv[0])
        query = urlencode(q)
        path = parts.path or "/"
        norm = urlunsplit((parts.scheme.lower(), f"{host}:{port}" if port else host, path, query, ""))
        return norm
    except Exception:
        return url


def _ext_for_content_type(content_type: str, status: int) -> str:
    """根据 Content-Type / 状态码挑 body 文件扩展名。"""
    ct = (content_type or "").lower()
    if status == 204 or status == 304:
        return "empty"
    if "json" in ct:
        return "json"
    if "html" in ct:
        return "html"
    if "xml" in ct:
        return "xml"
    if "javascript" in ct or "ecmascript" in ct:
        return "js"
    if "text/plain" in ct:
        return "txt"
    if ct.startswith("image/"):
        return "img"
    return "bin"


def _infer_encoding(headers: dict, content: bytes) -> Optional[str]:
    """从 Content-Type charset / BOM 推断解码用编码。"""
    ct = (headers or {}).get("Content-Type", "") or ""
    # charset=...
    for tok in ct.split(";"):
        tok = tok.strip()
        if tok.lower().startswith("charset="):
            cs = tok.split("=", 1)[1].strip().strip('"').strip("'")
            if cs:
                return cs
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if content.startswith(b"\xff\xfe") or content.startswith(b"\xfe\xff"):
        return "utf-16"
    return None


# ---------------------------------------------------------------------------
# 录制端：HttpRecorder
# ---------------------------------------------------------------------------

class HttpRecorder:
    """把出站 HTTP 交换落盘到 ``<root>/http/``。

    用法::

        rec = HttpRecorder()
        rec.begin("/tmp/rec/job1")          # 创建 http/ 与 bodies/
        set_active_http_recorder(rec)       # 之后 AsyncHttpClient 自动落盘
        ... 跑刮削 ...
        reset_active_http_recorder(token)
        rec.close()                          # 写 summary
    """

    def __init__(self) -> None:
        self._root: Optional[str] = None
        self._http_dir: Optional[str] = None
        self._bodies_dir: Optional[str] = None
        self._seq = 0
        self._lock = threading.Lock()
        self._index_fp: Optional[Any] = None
        self._requests = 0
        self._bytes = 0
        self._started_at: float = 0.0
        self._finished_at: float = 0.0

    @property
    def active(self) -> bool:
        return self._root is not None

    @property
    def root(self) -> Optional[str]:
        return self._root

    def begin(self, root_dir: str) -> None:
        """创建录制目录并打开索引文件。重复 begin 会重置。"""
        import time

        os.makedirs(root_dir, exist_ok=True)
        http_dir = os.path.join(root_dir, "http")
        bodies_dir = os.path.join(http_dir, "bodies")
        os.makedirs(bodies_dir, exist_ok=True)
        self._root = root_dir
        self._http_dir = http_dir
        self._bodies_dir = bodies_dir
        self._seq = 0
        self._requests = 0
        self._bytes = 0
        self._started_at = time.time()
        self._finished_at = 0.0
        # 截断（新任务不沿用上次残留索引，对齐 ref114 "begin 删除残留 summary"）
        idx_path = os.path.join(http_dir, "index.jsonl")
        self._index_fp = open(idx_path, "w", encoding="utf-8")
        # 启动时先写一条会话头（便于排障：录制何时、哪个目录）
        logger.info("HTTP 录制已开启 → %s", root_dir)

    def close(self) -> None:
        """关闭索引文件并写 summary.json。"""
        import time

        if self._index_fp is not None:
            try:
                self._index_fp.close()
            except Exception:
                pass
            self._index_fp = None
        if self._http_dir:
            self._finished_at = time.time()
            summary = {
                "requests": self._requests,
                "bytes": self._bytes,
                "duration_s": round(self._finished_at - self._started_at, 3),
                "started_at": self._started_at,
                "finished_at": self._finished_at,
            }
            try:
                with open(os.path.join(self._http_dir, "summary.json"), "w", encoding="utf-8") as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.debug("写录制 summary 失败（非致命）: %s", e)

    def record_exchange(
        self,
        method: str,
        url: str,
        request_headers: Optional[dict],
        params: Optional[Any],
        response: Any,
        *,
        error: Optional[str] = None,
    ) -> None:
        """记录一次 HTTP 交换。

        ``response`` 是 curl_cffi / httpx 的 Response 样对象
        （需有 ``.status_code`` ``.headers`` ``.content`` ``.url``）。
        任何异常都吞掉——录制失败绝不能影响主流程。
        """
        if not self.active or self._index_fp is None:
            return
        try:
            status = int(getattr(response, "status_code", 0) or 0)
            raw_headers = dict(getattr(response, "headers", {}) or {})
            content = bytes(getattr(response, "content", b"") or b"")
            resp_url = str(getattr(response, "url", url) or url)
            content_type = raw_headers.get("Content-Type") or raw_headers.get("content-type") or ""

            self._seq += 1
            seq = self._seq
            ext = _ext_for_content_type(content_type, status)
            body_file = f"bodies/{seq}.{ext}"
            body_path = os.path.join(self._bodies_dir, f"{seq}.{ext}")  # type: ignore[arg-type]

            # 写 body（空响应跳过，少占 IO）
            if content:
                with open(body_path, "wb") as bf:
                    bf.write(content)

            entry = {
                "seq": seq,
                "method": method.upper(),
                "url": url,
                "normalized_url": _normalize_url(url, params),
                "request_headers": _sanitize_headers(request_headers),
                "params": _safe_params(params),
                "status": status,
                "response_headers": _sanitize_headers(raw_headers),
                "content_type": content_type,
                "body_file": body_file if content else None,
                "body_bytes": len(content),
                "response_url": resp_url,
                "error": error,
            }
            line = json.dumps(entry, ensure_ascii=False, default=str)
            self._index_fp.write(line + "\n")  # type: ignore[union-attr]
            self._index_fp.flush()
            self._requests += 1
            self._bytes += len(content)
        except Exception as e:  # 录制失败绝不抛给主流程
            logger.debug("HTTP 录制失败（已忽略）: %s", e)

    # 便捷：记录一次失败（未拿到响应，如连接错误）
    def record_failure(
        self, method: str, url: str,
        request_headers: Optional[dict], params: Optional[Any],
        error: str,
    ) -> None:
        if not self.active or self._index_fp is None:
            return
        try:
            self._seq += 1
            seq = self._seq
            entry = {
                "seq": seq,
                "method": method.upper(),
                "url": url,
                "normalized_url": _normalize_url(url, params),
                "request_headers": _sanitize_headers(request_headers),
                "params": _safe_params(params),
                "status": None,
                "response_headers": {},
                "content_type": "",
                "body_file": None,
                "body_bytes": 0,
                "response_url": None,
                "error": error[:500],
            }
            self._index_fp.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            self._index_fp.flush()
            self._requests += 1
        except Exception:
            logger.debug("HTTP 录制失败（已忽略）")


def _safe_params(params: Any) -> Any:
    """params 可能是 dict / list / 其他，保证可 json 序列化。"""
    if params is None:
        return None
    if isinstance(params, dict):
        return {str(k): str(v) for k, v in params.items()}
    if isinstance(params, (list, tuple)):
        return [list(p) if isinstance(p, (list, tuple)) else p for p in params]
    return str(params)


# ---------------------------------------------------------------------------
# 回放端：RecordedResponse + ReplayWebClient
# ---------------------------------------------------------------------------

class RecordedResponse:
    """curl_cffi Response 的 duck-typed 替代品，供 ``resp_to_text`` / ``resp_to_html`` 使用。"""

    def __init__(
        self,
        method: str,
        url: str,
        status: int,
        headers: dict,
        content: bytes,
    ) -> None:
        self.method = method
        self.url = url
        self.status_code = status
        self.headers = _CaseInsensitiveDict(headers)
        self._content = content
        self.encoding = _infer_encoding(headers, content)

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        enc = self.encoding or "utf-8"
        try:
            return self._content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            return self._content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        import json as _json

        return _json.loads(self.text)


class _CaseInsensitiveDict(dict):
    """简易大小写不敏感 dict（兼容 curl_cffi response.headers 取值习惯）。"""

    def __init__(self, data: Optional[dict] = None) -> None:
        super().__init__()
        if data:
            for k, v in data.items():
                self[str(k)] = str(v)

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(str(key))

    def __contains__(self, key: object) -> bool:
        return super().__contains__(str(key))

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(str(key), default)


class ReplayWebClient:
    """离线回放客户端，接口对齐 ``AsyncHttpClient`` 的子集。

    命中规则：``method + 归一化URL`` 精确匹配；同一 (method, url) 有多条录制时，
    优先取最近的、其次取 2xx 的。未命中抛 ``FileNotFoundError``（让调用方走本地无源分支）。

    ⚠️ 这是**只读**客户端：不联网、不写库、不重试。仅用于离线复现解析逻辑。
    """

    def __init__(self, rec_dir: str) -> None:
        self._rec_dir = rec_dir
        self._http_dir = os.path.join(rec_dir, "http")
        self._index = self._load_index()
        self._by_key: dict[str, list[dict]] = {}
        for e in self._index:
            key = f"{e.get('method','GET')}|{e.get('normalized_url') or _normalize_url(e.get('url',''))}"
            self._by_key.setdefault(key, []).append(e)
        logger.info(
            "离线回放客户端就绪：%s 共 %s 条录制", rec_dir, len(self._index)
        )

    @property
    def entry_count(self) -> int:
        return len(self._index)

    def _load_index(self) -> list[dict]:
        idx_path = os.path.join(self._http_dir, "index.jsonl")
        if not os.path.exists(idx_path):
            raise FileNotFoundError(f"找不到录制索引：{idx_path}")
        out: list[dict] = []
        with open(idx_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    def _match(self, method: str, url: str, params: Optional[Any]) -> dict:
        norm = _normalize_url(url, params)
        key = f"{method.upper()}|{norm}"
        cands = self._by_key.get(key)
        if not cands:
            # 退一步：忽略 params 再试（有时爬虫把查询放 url 里、有时放 params）
            key2 = f"{method.upper()}|{_normalize_url(url)}"
            cands = self._by_key.get(key2)
        if not cands:
            raise FileNotFoundError(
                f"回放未命中：[{method}] {url}\n归一化：{norm}\n"
                f"（录制目录 {self._rec_dir} 含 {len(self._index)} 条交换）"
            )
        # 优先 2xx，其次最接近请求顺序（取最后一条，覆盖旧的脏数据）
        ok = [c for c in cands if isinstance(c.get("status"), int) and 200 <= c["status"] < 300]
        pick = ok[-1] if ok else cands[-1]
        return pick

    def _read_body(self, entry: dict) -> bytes:
        bf = entry.get("body_file")
        if not bf:
            return b""
        path = os.path.join(self._http_dir, bf)
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return b""

    def _response(self, entry: dict) -> RecordedResponse:
        content = self._read_body(entry)
        return RecordedResponse(
            method=entry.get("method", "GET"),
            url=entry.get("response_url") or entry.get("url", ""),
            status=int(entry.get("status") or 0),
            headers=entry.get("response_headers") or {},
            content=content,
        )

    # ── 对齐 AsyncHttpClient 的公开接口 ──────────────────────────────────
    async def init_session(self) -> None:
        return None

    async def close_session(self) -> None:
        return None

    async def get(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[str] = None,
        **kwargs,
    ) -> RecordedResponse:
        entry = self._match("GET", url, kwargs.get("params"))
        return self._response(entry)

    async def post(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[str] = None,
        **kwargs,
    ) -> RecordedResponse:
        entry = self._match("POST", url, kwargs.get("params"))
        return self._response(entry)

    async def get_text(
        self, url: str, headers: Optional[dict] = None,
        cookies: Optional[dict] = None, encoding: Optional[str] = None, **kwargs,
    ) -> str:
        resp = await self.get(url, headers=headers, cookies=cookies, **kwargs)
        if encoding:
            return resp.content.decode(encoding, errors="replace")
        return resp.text

    async def get_bytes(
        self, url: str, headers: Optional[dict] = None,
        cookies: Optional[dict] = None, **kwargs,
    ) -> bytes:
        resp = await self.get(url, headers=headers, cookies=cookies, **kwargs)
        return resp.content

    async def get_json(
        self, url: str, headers: Optional[dict] = None,
        cookies: Optional[dict] = None, **kwargs,
    ) -> Any:
        resp = await self.get(url, headers=headers, cookies=cookies, **kwargs)
        return resp.json()

    async def post_json(
        self, url: str, data: Optional[Any] = None, json: Optional[Any] = None,
        headers: Optional[dict] = None, cookies: Optional[dict] = None,
        purpose: Optional[str] = None, **kwargs,
    ) -> Any:
        resp = await self.post(url, data=data, json=json, headers=headers, cookies=cookies, **kwargs)
        return resp.json()

    async def get_html(
        self, url: str, encoding: Optional[str] = None,
        headers: Optional[dict] = None, cookies: Optional[dict] = None, **kwargs,
    ) -> Any:
        """返回 lxml HTML 文档（对齐 AsyncHttpClient.get_html）。"""
        from lxml import html as lxml_html

        text = await self.get_text(url, headers=headers, cookies=cookies, encoding=encoding, **kwargs)
        if not text:
            return lxml_html.fromstring("<html></html>")
        doc = lxml_html.fromstring(text)
        try:
            doc.make_links_absolute(str(self._match("GET", url, kwargs.get("params")).get("response_url") or url),
                                    resolve_base_href=True)
        except Exception:
            pass
        return doc


# ---------------------------------------------------------------------------
# 透明接入：ContextVar 开关（由 http_client 调用）
# ---------------------------------------------------------------------------

def _make_cv():
    import contextvars

    return contextvars.ContextVar("mdcx_http_recorder", default=None)


_cv = _make_cv()

# 模块级全局 recorder：用于「录制整个进程的所有出站 HTTP」（如 MDCX_HTTP_RECORD_DIR
# 环境变量模式）。ContextVar 只在设置它的那个 async 任务上下文内可见——
# 而 `AsyncHttpClient` 是进程级单例、被所有任务共享，若在首个任务的 ContextVar 里
# 开启录制，后续任务读不到 → 只有首个任务会被录。因此"录制一切"模式必须落到全局，
# 对所有任务生效。ContextVar 仍保留给「单任务录制到独立目录」的场景（优先级更高）。
_global_recorder: Optional[HttpRecorder] = None


def set_active_http_recorder(rec: HttpRecorder):
    """开启（context-local）录制，返回 token 供 reset。单任务独立目录时用。"""
    return _cv.set(rec)


def set_global_http_recorder(rec: HttpRecorder) -> None:
    """开启（进程级）录制，对所有任务生效。环境变量 / 调试"录制一切"时用。"""
    global _global_recorder
    _global_recorder = rec


def reset_active_http_recorder(token) -> None:
    _cv.reset(token)


def reset_global_http_recorder() -> None:
    global _global_recorder
    _global_recorder = None


def get_active_http_recorder() -> Optional[HttpRecorder]:
    """取当前生效的 recorder：context-local 优先，否则取进程级全局。"""
    cv = _cv.get(None)
    if cv is not None:
        return cv
    return _global_recorder


def auto_begin_from_env() -> Optional[HttpRecorder]:
    """若设置了 ``MDCX_HTTP_RECORD_DIR`` 环境变量，自动开启进程级录制。

    仅开发/调试用，生产环境不要设置此变量。返回已开启的 recorder 或 None。
    用进程级（而非 context-local）开启：HTTP 客户端是单例、被所有任务共享，
    context-local 只会影响首个触发初始化的任务，后续任务录不到。
    """
    d = os.environ.get("MDCX_HTTP_RECORD_DIR")
    if not d:
        return None
    rec = HttpRecorder()
    rec.begin(d)
    set_global_http_recorder(rec)
    return rec


__all__ = [
    "HttpRecorder",
    "RecordedResponse",
    "ReplayWebClient",
    "set_active_http_recorder",
    "set_global_http_recorder",
    "reset_active_http_recorder",
    "reset_global_http_recorder",
    "get_active_http_recorder",
    "auto_begin_from_env",
]
