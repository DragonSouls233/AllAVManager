"""
HTTP 客户端工具类
基于 curl_cffi 实现，支持浏览器指纹模拟

v3.1 增强：
- 集成 browser_fingerprint 指纹池（6 个预定义指纹）
- 按 host + 用途选择指纹（document/api/asset/download）
- 同一 host 在会话内复用同一指纹（减少漂移）
- Amazon.co.jp 自动切换日语 Accept-Language
- 本地地址与 CF bypass URL 跳过指纹注入
"""

import asyncio
import logging
import os
import random
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

from curl_cffi import AsyncSession
from curl_cffi.requests import Response

from app.config.manager import get_config
from app.utils.browser_fingerprint import (
    BrowserFingerprint,
    RequestPurpose,
    build_fingerprint_headers,
    infer_request_purpose,
    merge_headers,
    select_fingerprint,
    should_apply_fingerprint,
)

logger = logging.getLogger(__name__)

# 确定性失败状态码：源站/CDN 明确拒绝或不可达（Cloudflare 521-524、内容级
# 403/404/405/410/451）。重试无意义，命中即跳过重试与 httpx 降级，立即失败，
# 避免每张图浪费 3 次重试（每次约 20s）+ 降级 httpx 的双倍时间。
# 2026-09-29 补入 401：theporndb / missav_api 未配 Token 时源站恒返 401，
# 此前不在集合内导致每个番号都要跑满 3 次重试 + httpx 降级（约 20s/番号），
# 占批量刮削总耗时的绝大部分。
_NO_RETRY_STATUS = {401, 403, 404, 405, 410, 451, 521, 522, 523, 524}

# 会话级默认指纹（最现代的 Chrome 136 Windows）
# 每个请求可通过 impersonate 参数覆盖
_SESSION_DEFAULT_IMPERSONATE = "chrome136"

# 兼容旧代码：保留 BROWSER_IMPERSONATES 列表
BROWSER_IMPERSONATES = [
    "chrome120", "chrome123", "chrome124", "chrome131", "chrome136",
    "firefox133", "firefox135",
    "edge99", "edge101",
    "safari15_3", "safari15_5", "safari17_0", "safari18_0",
]


# ── curl_cffi 原生层降级（进程级共享）──────────────────────────────────────
# ⚠️ 必须背景（2026-10-02 事故，根因已由 faulthandler 锁定）：
#   curl_cffi 0.11.4 的 C 扩展在 socket 事件回调里访问已失效 handle →
#   `curl_cffi/aio.py:209 socket_action ← _asyncio_selector.py:250 _handle_event`
#   恶性时直接 access violation（0xC0000005）整进程崩溃；
#   良性时抛 `TypeError: initializer for ctype 'void *' must be a cdata pointer,
#   not NoneType`，把整部片子（元数据+图片）打成 FAILED（实测持续出现 319 部）。
#
# 旧实现把 `_curl_failed` 放在**实例**上，而刮削每部片子都会新建一个
# AsyncHttpClient → 探测到的降级状态无法跨实例共享，每片重踩一次。
# 实测后果：「curl_cffi 不可用」日志 count=0（从未触发），只有
# 「降级 httpx 再试」355 次 —— 说明整批片子一直在反复踩同一个坑。
#
# 现改为**进程级**：原生库一旦损坏就是全局损坏，全进程统一切换 httpx。
# 另注：升级 curl_cffi 0.16.3 后该缺陷应已消除，此处作为兜底防线保留。
_CURL_DISABLED: bool = False
_CURL_DISABLED_REASON: str = ""
_CURL_DISABLED_LOCK = threading.Lock()

# 判定「致命 curl_cffi C 层错误」的特征串。命中即说明原生扩展已不可用，
# 继续用下去只会重复失败（甚至段错误），应立即全局降级。
#
# ⚠️ 措辞必须精确：**不能**用 "libcurl" / "curl" 这类宽泛串 —— 普通超时错误的
# 提示里就带 `See https://curl.se/libcurl/c/libcurl-errors.html`（实测），
# 一旦误判就会把「网络超时」当成「原生库损坏」→ 全进程错误降级、白丢指纹。
# 因此只匹配 cffi/原生层特有的措辞。
_CURL_FATAL_MARKERS = (
    "initializer for ctype",       # cffi: initializer for ctype 'void *' must be a cdata pointer
    "must be a cdata pointer",
    "cdata pointer",
    "ffi.error",                   # cffi 层错误
    "access violation",            # 原生层内存访问违规
    "0xC0000005",
)


def is_fatal_curl_error(exc: BaseException) -> bool:
    """判断异常是否属于「curl_cffi 原生扩展已不可用」的致命错误。

    只在能明确归因于原生层时才返回 True，避免把普通业务异常
    （如 4xx/5xx、超时、DNS 失败）误判为需要全局降级。
    供本模块以外的直连调用点（如 crawlers/md/src/fc2ppvdb.py）复用。
    """
    if isinstance(exc, BaseException) and type(exc).__name__.startswith("Curl"):
        return True
    msg = str(exc)
    return any(m in msg for m in _CURL_FATAL_MARKERS)


def mark_curl_unavailable(reason: str = "") -> None:
    """把 curl_cffi 标记为**进程级**不可用，后续所有请求一律降级 httpx。

    幂等：首次置位时打一条 error 日志，之后静默（避免刷屏）。
    """
    global _CURL_DISABLED, _CURL_DISABLED_REASON
    with _CURL_DISABLED_LOCK:
        if _CURL_DISABLED:
            return
        _CURL_DISABLED = True
        _CURL_DISABLED_REASON = str(reason)[:300]
    logger.error(
        f"[curl_cffi] 原生扩展已被标记为进程级不可用，全部请求降级 httpx。原因: "
        f"{_CURL_DISABLED_REASON}"
    )


def is_curl_disabled() -> bool:
    """curl_cffi 是否已在进程级被禁用（供其它直连调用点查询）。"""
    return _CURL_DISABLED


def curl_disabled_reason() -> str:
    """返回进程级禁用的原因（未禁用时为空串），用于诊断。"""
    return _CURL_DISABLED_REASON


def reset_curl_state() -> None:
    """清除进程级降级标记。仅供测试/诊断热切换使用，生产路径不要调用。"""
    global _CURL_DISABLED, _CURL_DISABLED_REASON
    with _CURL_DISABLED_LOCK:
        _CURL_DISABLED = False
        _CURL_DISABLED_REASON = ""



# ── 站点级速率限制（进程级共享）────────────────────────────────────────────
# ⚠️ 必修背景（2026-09-30）：原实现的域名限速状态挂在实例上（self._domain_limiters），
# 而刮削时**每个番号都会新建一个 AsyncHttpClient** → 各实例状态互不可见，
# 并发下等于完全没有域名限速。实测后果：并发 24 打 javbus → HTTP 429 限流 3226 次。
# 修复：状态提到模块级，所有实例共享同一份「该域名上次请求时刻」。
_GLOBAL_LAST_REQUEST: float = 0.0
_GLOBAL_REQUEST_LOCK = asyncio.Lock()
_GLOBAL_DOMAIN_LAST: dict = {}
_GLOBAL_DOMAIN_LOCK = asyncio.Lock()

# 未单独配置的域名使用的 QPS 上限
DEFAULT_DOMAIN_QPS = 20.0

# 站点级 QPS 覆盖表（req/s）—— 对并发/频率敏感的站点单独降速
SITE_QPS_OVERRIDES: dict = {
    "www.javbus.com": 3.0,      # javbus 对并发敏感，20 req/s 实测触发 429 限流
    "javbus.com": 3.0,
    "jdforrepam.com": 8.0,      # JavDB 官方 App API 镜像
    "javdb.com": 8.0,
    "api.thejavdb.net": 8.0,    # 第三方开放 API（thejavdb / dmm_api 共用）
}


def site_qps(domain: str) -> float:
    """取域名的 QPS 上限（逐级回溯匹配子域，如 a.b.javbus.com → b.javbus.com）"""
    if not domain:
        return DEFAULT_DOMAIN_QPS
    d = (domain or "").lower().strip(".")
    if d in SITE_QPS_OVERRIDES:
        return SITE_QPS_OVERRIDES[d]
    parts = d.split(".")
    for i in range(1, len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in SITE_QPS_OVERRIDES:
            return SITE_QPS_OVERRIDES[cand]
    return DEFAULT_DOMAIN_QPS


class AsyncHttpClient:
    """
    异步 HTTP 客户端
    
    基于 curl_cffi 实现，支持：
    - 浏览器指纹模拟（绕过 Cloudflare）
    - 自动重试
    - 请求限流
    - 代理支持
    """
    
    def __init__(
        self,
        proxy: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        rate_limit: float = 20.0,  # 请求/秒
    ):
        # 如果没有传入代理，则从配置中读取
        if proxy is None:
            # 统一走项目唯一定义源：优先内置 xray 实际端口，回退旧版 config.proxy
            from app.services.proxy_manager import get_effective_proxy_url
            proxy = get_effective_proxy_url()

        self.proxy = proxy
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limit = rate_limit

        self._session: Optional[AsyncSession] = None
        self._httpx_client: Optional[httpx.AsyncClient] = None  # httpx 持久客户端（复用连接）
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()
        # 域名级速率限制（来自 Hazard804 MDCX）
        self._domain_limiters: dict[str, float] = {}
        self._domain_lock = asyncio.Lock()
        # 上一次使用的指纹 ID（用于排除连续重复）
        self._last_fingerprint_id: str = ""
        # ⚠️ 注意：curl_cffi 是否可用**不是实例状态**，而是进程级状态
        # （见模块顶部 `_CURL_DISABLED`）。本类通过只读属性 `_curl_failed`
        # 暴露它，读写都落到全局，跨实例共享。此处不再持有实例副本。

        # === 全局并发 Semaphore（防 hang 死）===
        # 2026-09-03 事故：6:48 站群瞬时断流 → 数千个下载请求同时跑 3×30s 重试 →
        # 累积死等协程占满 asyncio 信号量 → 事件循环锁死 → uvicorn handler 拿不到
        # 调度 → 客户端全 504/超时。修复：所有 get/post 必须先 acquire Semaphore，
        # 限制同时在途请求数。即使下游全挂，最多 N 个协程挂在 socket 上等超时，
        # 不会耗光 asyncio 默认 1024 协程槽位。
        # 拆分：document/api 走 _api_sem（限 16）；download 走 _download_sem（限 8）。
        # 两路独立，单一图片洪水不会挤垮 API 刮削。
        self._api_sem: asyncio.Semaphore = asyncio.Semaphore(16)
        self._download_sem: asyncio.Semaphore = asyncio.Semaphore(8)

    # ── curl_cffi 可用性（进程级，跨实例共享）─────────────────────────────
    # 保留 `self._curl_failed` 这个旧名字，让既有读写点无需改动即可
    # 升级为「进程级」语义：读 → 查全局；写 True → 全局置位。
    @property
    def _curl_failed(self) -> bool:  # type: ignore[override]
        return _CURL_DISABLED

    @_curl_failed.setter
    def _curl_failed(self, value: bool) -> None:  # type: ignore[override]
        if value:
            mark_curl_unavailable("实例在使用 curl_cffi 时探测到致命原生错误")
        # 写 False 视为 no-op：降级是不可逆的进程级决策，
        # 不允许某个实例把它"复位"回去，否则又会踩同一个坑。

    async def __aenter__(self) -> "AsyncHttpClient":
        """上下文管理器入口"""
        await self.init_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器退出"""
        await self.close_session()

    async def init_session(self) -> None:
        """初始化会话（使用 Chrome 136 作为默认 TLS 指纹）"""
        if self._session is None and not self._curl_failed:
            # 允许通过环境变量强制禁用 curl_cffi（本环境 Python3.14 + 预编译 native
            # 库损坏时会报 "initializer for ctype 'void *' must be a cdata pointer"）。
            if os.environ.get("MDCX_DISABLE_CURL_CFFI", "").lower() in ("1", "true", "yes"):
                self._curl_failed = True
                logger.warning("curl_cffi 已通过 MDCX_DISABLE_CURL_CFFI 强制禁用，将使用 httpx 降级")
                return
            try:
                self._session = AsyncSession(
                    max_clients=300,
                    verify=False,
                    max_redirects=20,
                    timeout=self.timeout,
                    impersonate=_SESSION_DEFAULT_IMPERSONATE,
                    proxy=self.proxy,
                )
            except Exception as e:
                self._curl_failed = True
                logger.warning(
                    f"curl_cffi 会话初始化失败（{e}），进程内后续请求将降级到 httpx"
                )

    def _select_fingerprint_for_request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[dict] = None,
        json_data: object = None,
        stream: bool = False,
        purpose: Optional[RequestPurpose] = None,
    ) -> Optional[BrowserFingerprint]:
        """为单次请求选择浏览器指纹。

        Returns:
            BrowserFingerprint 实例，若应跳过指纹注入则返回 None
        """
        if not should_apply_fingerprint(url):
            return None

        # 推断用途（若调用方未指定）
        if purpose is None:
            purpose = infer_request_purpose(
                url,
                method=method,
                headers=headers,
                stream=stream,
                json_data=json_data,
            )

        host = ""
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            pass

        fp = select_fingerprint(
            host,
            purpose=purpose,
            exclude_fingerprint_id=self._last_fingerprint_id,
        )
        self._last_fingerprint_id = fp.fingerprint_id
        return fp

    def _build_request_headers(
        self,
        url: str,
        fingerprint: Optional[BrowserFingerprint],
        explicit_headers: Optional[dict],
        purpose: RequestPurpose = "document",
    ) -> dict:
        """合并指纹 headers 与显式 headers（显式优先）"""
        if fingerprint is None:
            # 跳过指纹注入，使用最小默认 headers
            fp_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            }
        else:
            fp_headers = build_fingerprint_headers(url, fingerprint=fingerprint, purpose=purpose)
        return merge_headers(fp_headers, None, explicit_headers)
    
    async def close_session(self) -> None:
        """关闭所有会话"""
        if self._session:
            await self._session.close()
            self._session = None
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None

    async def _httpx_request(
        self,
        method: str,
        url: str,
        headers: Optional[dict],
        cookies: Optional[dict],
        kwargs: dict,
    ):
        """curl_cffi 不可用时的降级实现（使用 httpx 持久连接池）。

        返回 httpx.Response，接口与 curl_cffi Response 兼容。
        使用持久客户端复用 TCP 连接，避免每次创建/销毁的开销（尤其在高并发补刮时）。
        """
        import httpx

        if self._httpx_client is None:
            limits = httpx.Limits(max_connections=300, max_keepalive_connections=100)
            transport = httpx.AsyncHTTPTransport(
                limits=limits,
                retries=1,  # httpx 内置重试（仅安全幂等方法）
            )
            self._httpx_client = httpx.AsyncClient(
                proxy=self.proxy or None,
                timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=10.0),
                verify=False,
                follow_redirects=True,
                limits=limits,
                transport=transport,
            )

        params = kwargs.get("params")
        data = kwargs.get("data")
        json_body = kwargs.get("json")

        try:
            if method == "POST":
                resp = await self._httpx_client.post(
                    url, headers=headers, cookies=cookies or {},
                    data=data, json=json_body, params=params,
                )
            else:
                resp = await self._httpx_client.get(
                    url, headers=headers, cookies=cookies or {}, params=params,
                )
            await resp.aread()
            return resp
        except Exception as e:
            # 连接池可能因代理断开等原因损坏 / 半开连接，重建客户端再试一次
            logger.warning(
                f"httpx {method} {url} 失败，重建连接池重试: {type(e).__name__}: {e}"
            )
            try:
                await self._httpx_client.aclose()
            except Exception:
                pass
            self._httpx_client = httpx.AsyncClient(
                proxy=self.proxy or None,
                timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=10.0),
                verify=False,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=300, max_keepalive_connections=100),
            )
            if method == "POST":
                resp = await self._httpx_client.post(
                    url, headers=headers, cookies=cookies or {},
                    data=data, json=json_body, params=params,
                )
            else:
                resp = await self._httpx_client.get(
                    url, headers=headers, cookies=cookies or {}, params=params,
                )
            await resp.aread()
            return resp
    
    async def _wait_for_rate_limit(self, url: str = "") -> None:
        """等待以遵守速率限制（全局 + 域名级，状态均为【进程级共享】）

        ⚠️ 域名限速状态必须全局共享：刮削每个番号都新建一个 AsyncHttpClient，
        若状态挂在实例上，并发时各实例互不可见 → 等于不限速
        （历史 bug → javbus 429 限流 3226 次）。站点级 QPS 见 SITE_QPS_OVERRIDES。
        """
        global _GLOBAL_LAST_REQUEST
        if self.rate_limit <= 0:
            return

        # 全局速率限制（进程级）
        async with _GLOBAL_REQUEST_LOCK:
            now = time.monotonic()
            interval = 1.0 / self.rate_limit
            wait_time = interval - (now - _GLOBAL_LAST_REQUEST)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            _GLOBAL_LAST_REQUEST = time.monotonic()

        # 域名级速率限制（进程级共享 + 站点级 QPS 覆盖）
        if url:
            domain = urlparse(url).hostname or ""
            if domain:
                qps = site_qps(domain)
                interval = (1.0 / qps) if qps > 0 else 0.0
                async with _GLOBAL_DOMAIN_LOCK:
                    last = _GLOBAL_DOMAIN_LAST.get(domain, 0.0)
                    now = time.monotonic()
                    wait = interval - (now - last)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    _GLOBAL_DOMAIN_LAST[domain] = time.monotonic()
    
    async def get(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[RequestPurpose] = None,
        **kwargs,
    ) -> Response:
        """
        GET 请求

        Args:
            url: 请求URL
            headers: 请求头（与指纹 headers 合并，显式优先）
            cookies: Cookies
            purpose: 请求用途（document/api/asset/download），None 则自动推断
            **kwargs: 其他参数

        Returns:
            Response 响应对象

        Raises:
            Exception: 当响应状态码为 4xx 或 5xx 时抛出异常
        """
        # 2026-09-03 防 hang 死：按 purpose 选 Semaphore。
        # 9/3 06:48 站群断流时数千图片下载同时挂起，吃光 asyncio 协程槽位。
        # 限 8 个 download + 16 个 document/api 同时在途，剩余排队等 acquire。
        is_download = purpose == "download"
        sem = self._download_sem if is_download else self._api_sem
        async with sem:
            return await self._get_impl(url, headers, cookies, purpose, **kwargs)

    async def _get_impl(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[RequestPurpose] = None,
        **kwargs,
    ) -> Response:
        await self.init_session()
        await self._wait_for_rate_limit(url)

        # 选择指纹并构建 headers
        fingerprint = self._select_fingerprint_for_request(
            url, method="GET", headers=headers, purpose=purpose
        )
        req_purpose: RequestPurpose = purpose or (
            fingerprint and infer_request_purpose(url, method="GET", headers=headers) or "document"
        )
        req_headers = self._build_request_headers(url, fingerprint, headers, req_purpose)

        # 重试逻辑
        no_retry_status: Optional[int] = None
        if not self._curl_failed and self._session is not None:
            for attempt in range(self.max_retries):
                try:
                    # 传入 per-request impersonate 覆盖会话默认值
                    request_kwargs = dict(kwargs)
                    if fingerprint is not None and "impersonate" not in request_kwargs:
                        request_kwargs["impersonate"] = fingerprint.impersonate

                    response = await self._session.get(  # type: ignore
                        url,
                        headers=req_headers,
                        cookies=cookies,
                        **request_kwargs,
                    )
                    # 关键修复：在受保护块内【立即读取响应体】。
                    # curl_cffi 在 Python3.14 + 预编译 native 库损坏时，C 层错误
                    # "initializer for ctype 'void *' must be a cdata pointer" 发生在
                    # 读取响应体（response.content/.text）时，而该步骤在 get_text/
                    # get_html 内、已离开本 try —— 导致降级逻辑永不触发、
                    # _curl_failed 永远不置位，批量刮削整批失败。提前读体能确保该
                    # 错误被本 try 捕获并切到 httpx 降级。
                    _ = response.content
                    # 检查响应状态码
                    if response.status_code and response.status_code in _NO_RETRY_STATUS:
                        # 确定性失败：跳过剩余重试与 httpx 降级，直接失败
                        no_retry_status = response.status_code
                        logger.warning(
                            f"GET {url} 确定性失败 HTTP {no_retry_status}，跳过重试"
                        )
                        break
                    if response.status_code and 400 <= response.status_code < 600:
                        raise Exception(f"HTTP {response.status_code}")
                    return response

                except Exception as e:
                    # 记录每次失败（超时/连接失败/5xx），否则“刮削失败但不知为何”
                    logger.warning(
                        f"GET 失败 ({attempt + 1}/{self.max_retries}) {url}: "
                        f"{type(e).__name__}: {e}"
                    )
                    # 致命的 curl_cffi C 层错误（native 库损坏 / handle 失效）：
                    # 直接全局禁用 curl_cffi，进程内后续请求全部走 httpx 降级。
                    if is_fatal_curl_error(e):
                        self._curl_failed = True  # → 进程级置位
                        logger.warning(
                            f"curl_cffi 不可用（{e}），进程内全部请求将降级到 httpx"
                        )
                        break
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))

        # 确定性失败：直接抛给调用方，不再降级 httpx（降级结果相同，纯浪费时间）
        if no_retry_status is not None:
            raise Exception(f"HTTP {no_retry_status}")

        # curl_cffi 不可用或本次失败 → 降级到 httpx（接口兼容 Response）
        if self.max_retries > 0:
            logger.warning(f"GET {url} 重试 {self.max_retries} 次均失败，降级 httpx 再试")
        return await self._httpx_request("GET", url, req_headers, cookies, dict(kwargs))
    
    async def get_text(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        encoding: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        GET 请求并返回文本
        
        Args:
            url: 请求URL
            headers: 请求头
            cookies: Cookies
            encoding: 编码（默认自动检测）
            **kwargs: 其他参数
            
        Returns:
            响应文本
        """
        response = await self.get(url, headers, cookies, **kwargs)
        
        if encoding:
            return response.content.decode(encoding)
        
        return response.text

    async def get_bytes(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        **kwargs,
    ) -> bytes:
        """
        GET 请求并返回原始字节

        Args:
            url: 请求URL
            headers: 请求头
            cookies: Cookies
            **kwargs: 其他参数

        Returns:
            响应字节
        """
        response = await self.get(url, headers, cookies, **kwargs)
        return response.content

    async def get_json(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        """
        GET 请求并返回 JSON

        Returns:
            响应 JSON 字典
        """
        response = await self.get(url, headers, cookies, **kwargs)
        try:
            return response.json()
        except Exception:
            import json as _json
            return _json.loads(response.text)

    async def post(
        self,
        url: str,
        data: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[RequestPurpose] = None,
        **kwargs,
    ) -> Response:
        """
        POST 请求

        Args:
            url: 请求URL
            data: 表单数据
            json: JSON数据
            headers: 请求头（与指纹 headers 合并，显式优先）
            cookies: Cookies
            purpose: 请求用途，默认推断为 api（POST 多为 API 调用）
            **kwargs: 其他参数

        Returns:
            Response 响应对象
        """
        # 2026-09-03 防 hang 死：POST 默认走 API 限流。
        is_download = purpose == "download"
        sem = self._download_sem if is_download else self._api_sem
        async with sem:
            return await self._post_impl(
                url, data, json, headers, cookies, purpose, **kwargs
            )

    async def post_json(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[RequestPurpose] = None,
        **kwargs,
    ) -> dict:
        """POST 请求并返回 JSON（与 get_json 对称）。

        2026-09-29 新增：app/crawlers/missav_api.py 与 app/crawlers/md/hdouban.py
        调用了 ``client.post_json(...)``，但本类此前只有 ``post()``，导致这两处
        每次调用都抛 ``AttributeError: 'AsyncHttpClient' object has no attribute
        'post_json'`` —— 爬虫 100% 失败且被 try/except 静默吞掉，日志里只显示
        "request failed"，看不到真实原因。补齐该方法即可修复。

        Returns:
            响应 JSON 字典
        """
        response = await self.post(url, data, json, headers, cookies, purpose, **kwargs)
        try:
            return response.json()
        except Exception:
            import json as _json

            return _json.loads(response.text)

    async def _post_impl(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[RequestPurpose] = None,
        **kwargs,
    ) -> Response:
        await self.init_session()
        await self._wait_for_rate_limit(url)

        # 选择指纹并构建 headers（POST 默认推断为 api 用途）
        inferred_purpose: RequestPurpose = purpose or "api"
        fingerprint = self._select_fingerprint_for_request(
            url, method="POST", headers=headers, json_data=json, purpose=inferred_purpose
        )
        req_headers = self._build_request_headers(url, fingerprint, headers, inferred_purpose)

        no_retry_status: Optional[int] = None
        if not self._curl_failed and self._session is not None:
            for attempt in range(self.max_retries):
                try:
                    request_kwargs = dict(kwargs)
                    if fingerprint is not None and "impersonate" not in request_kwargs:
                        request_kwargs["impersonate"] = fingerprint.impersonate

                    response = await self._session.post(  # type: ignore
                        url,
                        data=data,
                        json=json,
                        headers=req_headers,
                        cookies=cookies,
                        **request_kwargs,
                    )
                    # 与 get() 同理：在受保护块内提前读取响应体，确保 curl_cffi
                    # C 层错误能被捕获并降级到 httpx。
                    _ = response.content
                    # 2026-09-29 补：与 get() 对齐。此前 POST 完全不检查状态码，
                    # 401/403/404 这类确定性失败也会跑满 3 次重试 + httpx 降级。
                    if response.status_code and response.status_code in _NO_RETRY_STATUS:
                        no_retry_status = response.status_code
                        logger.warning(
                            f"POST {url} 确定性失败 HTTP {no_retry_status}，跳过重试"
                        )
                        break
                    return response

                except Exception as e:
                    # 记录每次失败，便于定位批量刮削整批失败的原因
                    logger.warning(
                        f"POST 失败 ({attempt + 1}/{self.max_retries}) {url}: "
                        f"{type(e).__name__}: {e}"
                    )
                    # 致命的 curl_cffi C 层错误：全局禁用 curl_cffi，降级 httpx
                    if is_fatal_curl_error(e):
                        self._curl_failed = True  # → 进程级置位
                        logger.warning(
                            f"curl_cffi 不可用（{e}），进程内全部请求将降级到 httpx"
                        )
                        break
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))

        # 确定性失败：直接抛给调用方，不再降级 httpx（降级结果相同，纯浪费时间）
        if no_retry_status is not None:
            raise Exception(f"HTTP {no_retry_status}")

        # curl_cffi 不可用或本次失败 → 降级到 httpx
        if self.max_retries > 0:
            logger.warning(f"POST {url} 重试 {self.max_retries} 次均失败，降级 httpx 再试")
        return await self._httpx_request(
            "POST", url, req_headers, cookies,
            {"data": data, "json": json, **kwargs},
        )

    # ============================================
    # HTML 解析辅助方法(移植自 JavSP web/base.py)
    # 集中处理编码检测与链接绝对化,减少爬虫重复代码
    # ============================================

    @staticmethod
    def resp_to_text(response: Response, encoding: Optional[str] = None) -> str:
        """从 Response 提取文本,支持 apparent_encoding 回退

        移植自 JavSP get_resp_text

        curl_cffi 的 response.text 在日文/中文站点可能编码错误,
        此方法提供 apparent_encoding 自动检测作为兜底。

        Args:
            response: curl_cffi Response 对象
            encoding: 强制指定编码(优先级最高)

        Returns:
            解码后的文本
        """
        if encoding:
            try:
                return response.content.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                pass

        # 优先用 response 自带的 encoding
        if response.encoding:
            try:
                return response.content.decode(response.encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                pass

        # 兜底:apparent_encoding 自动检测
        try:
            from charset_normalizer import from_bytes
            result = from_bytes(response.content).best()
            if result:
                return str(result)
        except ImportError:
            pass

        # 最终兜底:UTF-8 + replace
        return response.content.decode("utf-8", errors="replace")

    @staticmethod
    def resp_to_html(
        response: Response,
        encoding: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """Response → lxml HTML 文档,链接绝对化

        移植自 JavSP resp2html

        Args:
            response: curl_cffi Response 对象
            encoding: 强制指定编码
            base_url: 基础 URL(默认用 response.url)

        Returns:
            lxml.html.HtmlElement
        """
        from lxml import html as lxml_html

        text = AsyncHttpClient.resp_to_text(response, encoding)
        if not text:
            from lxml.html import HtmlElement
            return lxml_html.fromstring("<html></html>")

        # 解析为 HTML 文档
        doc = lxml_html.fromstring(text)

        # 链接绝对化(用 response.url 或显式 base_url)
        if base_url:
            url = base_url
        elif response.url:
            url = str(response.url)
        else:
            url = None
        if url:
            try:
                doc.make_links_absolute(url, resolve_base_href=True)
            except Exception:
                pass

        return doc

    async def get_html(
        self,
        url: str,
        encoding: Optional[str] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        **kwargs,
    ):
        """GET 请求并返回 lxml HTML 文档

        移植自 JavSP get_html

        集中处理编码检测与链接绝对化,减少爬虫重复代码。

        Args:
            url: 请求 URL
            encoding: 强制指定编码(如 'utf-8', 'shift_jis')
            headers: 请求头
            cookies: Cookies
            **kwargs: 其他参数

        Returns:
            lxml.html.HtmlElement
        """
        response = await self.get(url, headers, cookies, **kwargs)
        return AsyncHttpClient.resp_to_html(response, encoding, base_url=url)


# 全局客户端实例（懒加载）
_client: Optional[AsyncHttpClient] = None


async def get_http_client() -> AsyncHttpClient:
    """获取全局 HTTP 客户端实例"""
    global _client

    if _client is None:
        config = get_config()
        # 统一走项目唯一定义源：优先内置 xray 实际端口，回退旧版 config.proxy
        from app.services.proxy_manager import get_effective_proxy_url
        proxy = get_effective_proxy_url()
        _client = AsyncHttpClient(
            proxy=proxy,
            timeout=config.scraper.timeout,
            max_retries=config.scraper.retry_count,
        )
        await _client.init_session()
    
    return _client


async def close_http_client() -> None:
    """关闭全局 HTTP 客户端"""
    global _client
    
    if _client:
        await _client.close_session()
        _client = None
