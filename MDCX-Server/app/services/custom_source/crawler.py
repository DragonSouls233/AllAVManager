"""自定义来源的可运行爬虫核心。

``scrape_with_spec`` 是纯函数式的抓取入口，``http_get`` 可注入（测试时喂 fixture），
因此整条链路可以完全离线验收。生产环境由 ``CustomYamlCrawler`` 包装，复用项目
自身的 ``AsyncHttpClient``（带 TLS 指纹 / 代理 / 限流）。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from app.services.custom_source.parser import (
    extract_fields,
    is_not_found,
    normalize_url,
)
from app.services.custom_source.schema import CustomSourceSpec

# http_get: async (url, *, method, headers, encoding) -> (status_code, html_text)
HttpGet = Callable[..., Awaitable[tuple[int, str]]]


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """合并搜索结果与详情结果；列表字段取并集去重。"""
    out = dict(base)
    for k, v in over.items():
        if k in out and isinstance(out[k], list) and isinstance(v, list):
            seen = list(out[k])
            for x in v:
                if x not in seen:
                    seen.append(x)
            out[k] = seen
        else:
            out[k] = v
    return out


async def scrape_with_spec(
    spec: CustomSourceSpec,
    code: str,
    http_get: HttpGet,
    *,
    encoding: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """按规则档抓取一个番号。

    Args:
        spec: 已解析的规则档。
        code: 番号。
        http_get: 注入的 HTTP 获取函数（async）。
        encoding: 覆盖编码（默认取 spec.encoding）。

    Returns:
        命中 → 字段 dict（含 code）；未命中（not_found）→ None。
        若连标题都抽不到，也视为未命中返回 None。
    """
    enc = encoding or spec.encoding
    headers = dict(spec.search.get("headers") or {})

    # 1) 搜索页
    if spec.has_search:
        url = spec.search["url"].replace("{code}", code)
        status, html = await http_get(
            url, method=str(spec.search.get("method", "GET")).upper(),
            headers=headers, encoding=enc,
        )
        if is_not_found(html, spec.search.get("not_found") or {}, status_code=status):
            return None
        soup = _parse_for_extract(html, enc)
        from app.services.custom_source.parser import extract_fields

        fields = extract_fields(soup, spec.search.get("fields") or {})
        detail_link = (
            fields.pop("detail_url", None)
            or fields.pop("url", None)
        )
        if not fields.get("title"):
            # 搜索页抽不到标题，尝试详情页
            if not (spec.has_detail or detail_link):
                return None
        result = {"code": code, **fields}
    else:
        result = {"code": code}
        detail_link = None

    # 2) 详情页（补充字段）
    detail_url = None
    if spec.has_detail:
        detail_url = spec.detail["url"].replace("{code}", code)
    if not detail_url and detail_link:
        detail_url = normalize_url(str(detail_link), spec.base_url)
    if detail_url:
        dstatus, dhtml = await http_get(
            detail_url, method=str(spec.detail.get("method", "GET")).upper(),
            headers=headers, encoding=enc,
        )
        if not is_not_found(dhtml, spec.detail.get("not_found") or {}, status_code=dstatus):
            dsoup = _parse_for_extract(dhtml, enc)
            from app.services.custom_source.parser import extract_fields

            dfields = extract_fields(dsoup, spec.detail.get("fields") or {})
            result = _merge(result, dfields)

    if not result.get("title"):
        return None
    # 统一封面键名
    if "cover" in result and "cover_url" not in result:
        result["cover_url"] = result.pop("cover")
    return result


def _parse_for_extract(html: str, encoding: str):
    from app.services.custom_source.parser import parse_html

    return parse_html(html, encoding)


class CustomYamlCrawler:
    """把规则档包装成爬虫（供 scrape 引擎按需调用）。

    不自动进入 canon 源序——是否启用由用户在配置里决定是否加入编排。
    这样保证「纯配置」不会悄悄改变既有刮削行为。
    """

    def __init__(self, spec: CustomSourceSpec):
        self.spec = spec
        self.name = spec.name
        self.display_name = spec.display_name
        self.base_url = spec.base_url

    @property
    def enabled(self) -> bool:
        return self.spec.enabled

    async def scrape(self, code: str, ctx=None) -> Optional[dict[str, Any]]:
        from app.utils.http_client import AsyncHttpClient

        client = None
        if ctx is not None and getattr(ctx, "http_client", None) is not None:
            client = ctx.http_client
        else:
            client = AsyncHttpClient()

        async def _http_get(url, *, method="GET", headers=None, encoding="utf-8"):
            resp = await client.get(url, headers=headers)
            return resp.status_code, (resp.text or "")

        try:
            return await scrape_with_spec(self.spec, code, _http_get, encoding=self.spec.encoding)
        finally:
            if client is not None and not (ctx is not None and getattr(ctx, "http_client", None) is not None):
                try:
                    await client.close()
                except Exception:  # noqa: BLE001
                    pass


__all__ = ["scrape_with_spec", "CustomYamlCrawler"]
