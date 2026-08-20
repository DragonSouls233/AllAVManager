"""网络诊断服务

参考 Hazard804-mdcx 的 network_check.py：
- 状态枚举：OK / WARNING / FAILED / SKIPPED / CANCELLED
- 诊断项：站点连通性、代理可用性、Cookie 有效性、CF Bypass
"""

import asyncio
import enum
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config.manager import get_config
from app.crawlers import get_crawler  # 已有的爬虫注册中心
from app.services.websocket import emit_log

logger = logging.getLogger(__name__)


# 站点级详情页探针路径（比首页更能反映真实可用性，参考 Kesuy-mdcx network_check.py）
SPECIAL_CHECK_PATHS = {
    "javdb": "/v/D16Q5?locale=zh",
    "javbus": "/FSDSS-660",
    "javlibrary": "/cn/?v=javme2j2tu",
    "kin8": "/moviepages/3681/index.html",
}

# Cloudflare 挑战页特征 marker（参考 Kesuy-mdcx network_check.py）
CF_CHALLENGE_MARKERS = (
    "challenge",
    "ray id",
    "ray-id",
    "cf-browser-verification",
    "just a moment",
    "cf-chl",
    "cdn-cgi/challenge-platform",
    "attention required",
    "enable javascript and cookies",
    "checking your browser before accessing",
)


class DiagStatus(str, enum.Enum):
    OK = "OK"
    WARNING = "WARNING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


@dataclass
class DiagResult:
    """单项诊断结果"""
    name: str
    status: DiagStatus
    message: str = ""
    duration_ms: int = 0
    details: dict = field(default_factory=dict)


@dataclass
class DiagReport:
    """完整诊断报告"""
    started_at: str = ""
    finished_at: str = ""
    total_duration_ms: int = 0
    summary: dict = field(default_factory=dict)
    items: list[DiagResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_duration_ms": self.total_duration_ms,
            "summary": self.summary,
            "items": [
                {
                    "name": it.name,
                    "status": it.status.value,
                    "message": it.message,
                    "duration_ms": it.duration_ms,
                    "details": it.details,
                }
                for it in self.items
            ],
        }


# 站点 URL 映射
SITE_URLS = {
    "javdb": "https://javdb.com",
    "javbus": "https://www.javbus.com",
    "dmm": "https://www.dmm.co.jp",
    "fc2ppvdb": "https://fc2cmadb.com",
    "missav": "https://missav.ws",
    "avsox": "https://avsox.click",
    "mgstage": "https://www.mgstage.com",
    "fantastica": "https://fantastica-vr.com",
}


async def check_site_connectivity(
    site_name: str,
    timeout: int = 10,
    proxy_url: Optional[str] = None,
) -> DiagResult:
    """检查单个站点连通性"""
    url = SITE_URLS.get(site_name, "")
    if not url:
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.SKIPPED,
            message=f"未知站点: {site_name}",
        )

    # 优先用详情页探针路径（比首页更能反映真实可用性）
    probe_path = SPECIAL_CHECK_PATHS.get(site_name, "")
    if probe_path:
        url = url.rstrip("/") + probe_path

    start = time.time()
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            proxy=proxy_url,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            duration = int((time.time() - start) * 1000)
            text = resp.text or ""

            if resp.status_code == 200:
                return _classify_ok_response(
                    site_name, text, duration, url, resp.status_code,
                )
            elif resp.status_code in (403, 503):
                # 可能是 CF 拦截或站点级封禁
                has_cf = "cloudflare" in text.lower() or "cf-ray" in resp.headers
                return DiagResult(
                    name=f"site:{site_name}",
                    status=DiagStatus.WARNING if has_cf else DiagStatus.FAILED,
                    message=f"HTTP {resp.status_code}{' (Cloudflare 拦截)' if has_cf else ''}",
                    duration_ms=duration,
                    details={"url": url, "status": resp.status_code, "cloudflare": has_cf},
                )
            else:
                return DiagResult(
                    name=f"site:{site_name}",
                    status=DiagStatus.WARNING,
                    message=f"HTTP {resp.status_code}",
                    duration_ms=duration,
                    details={"url": url, "status": resp.status_code},
                )
    except httpx.TimeoutException:
        duration = int((time.time() - start) * 1000)
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.FAILED,
            message="连接超时，请检查网络或代理节点",
            duration_ms=duration,
        )
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.FAILED,
            message=_classify_error_message(e),
            duration_ms=duration,
        )


def _classify_ok_response(
    site_name: str,
    text: str,
    duration: int,
    url: str,
    status_code: int,
) -> DiagResult:
    """HTTP 200 时的站点级语义判定（参考 Kesuy-mdcx network_check.py）。

    识别 CF 挑战页、JavDB IP 封禁 / 地域限制 / Cookie 有效性、
    JavBus Cookie 提示、DMM 地域限制、MGStage 空页面。
    """
    # 1. Cloudflare 挑战页（多 marker 识别）
    if _is_cloudflare_challenge(text):
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.WARNING,
            message="HTTP 200 但被 Cloudflare 挑战页拦截",
            duration_ms=duration,
            details={"url": url, "status": status_code, "cloudflare_challenge": True},
        )

    # 2. 站点级语义判定
    cfg = get_config().crawler

    if site_name == "javdb":
        if "The owner of this website has banned your access based on your browser's behaving" in text:
            ip_match = re.findall(r"(\d+\.\d+\.\d+\.\d+)", text)
            ip_text = f"{ip_match[0]} " if ip_match else ""
            return DiagResult(
                name=f"site:{site_name}",
                status=DiagStatus.FAILED,
                message=f"当前 IP {ip_text}被 JavDB 封禁",
                duration_ms=duration,
                details={"url": url, "status": status_code, "ip_banned": True},
            )
        if "Due to copyright restrictions" in text or "Access denied" in text:
            return DiagResult(
                name=f"site:{site_name}",
                status=DiagStatus.FAILED,
                message="当前 IP 被 JavDB 限制，请使用非日本节点",
                duration_ms=duration,
                details={"url": url, "status": status_code},
            )
        if "/logout" in text:
            return DiagResult(
                name=f"site:{site_name}",
                status=DiagStatus.OK,
                message=f"HTTP 200 · 响应时间 {duration}ms · Cookie 有效",
                duration_ms=duration,
                details={"url": url, "status": status_code, "cookie_valid": True},
            )
        if getattr(cfg, "javdb_cookie", ""):
            return DiagResult(
                name=f"site:{site_name}",
                status=DiagStatus.WARNING,
                message="站点可访问，但 JavDB Cookie 可能无效",
                duration_ms=duration,
                details={"url": url, "status": status_code},
            )
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.OK,
            message=f"HTTP 200 · 响应时间 {duration}ms",
            duration_ms=duration,
            details={"url": url, "status": status_code},
        )

    if site_name == "javbus":
        has_cookie = bool(getattr(cfg, "javbus_cookie", ""))
        if "lostpasswd" in text and has_cookie:
            return DiagResult(
                name=f"site:{site_name}",
                status=DiagStatus.WARNING,
                message="站点可访问，但 JavBus Cookie 可能无效",
                duration_ms=duration,
                details={"url": url, "status": status_code},
            )
        if "lostpasswd" in text:
            return DiagResult(
                name=f"site:{site_name}",
                status=DiagStatus.WARNING,
                message="当前节点可能需要 JavBus Cookie",
                duration_ms=duration,
                details={"url": url, "status": status_code},
            )
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.OK,
            message=f"HTTP 200 · 响应时间 {duration}ms",
            duration_ms=duration,
            details={"url": url, "status": status_code},
        )

    if site_name == "dmm" and "このページはお住まいの地域からご利用になれません" in text:
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.FAILED,
            message="DMM 地域限制，请使用日本节点",
            duration_ms=duration,
            details={"url": url, "status": status_code, "region_blocked": True},
        )

    if site_name == "mgstage" and not text.strip():
        return DiagResult(
            name=f"site:{site_name}",
            status=DiagStatus.FAILED,
            message="MGStage 返回空页面，通常是地域限制，请使用日本节点",
            duration_ms=duration,
            details={"url": url, "status": status_code},
        )

    # 3. 默认：HTTP 200 正常
    return DiagResult(
        name=f"site:{site_name}",
        status=DiagStatus.OK,
        message=f"HTTP 200 · 响应时间 {duration}ms",
        duration_ms=duration,
        details={"url": url, "status": status_code},
    )


def _is_cloudflare_challenge(text: str) -> bool:
    """识别 Cloudflare 挑战页（多 marker 特征，参考 Kesuy-mdcx）。"""
    lowered = (text or "").lower()
    return "cloudflare" in lowered and any(
        marker in lowered for marker in CF_CHALLENGE_MARKERS
    )


def _classify_error_message(e: Exception) -> str:
    """将连接异常归类为可读提示（参考 Kesuy-mdcx _message_for_error）。"""
    lowered = str(e).lower()
    if "proxy" in lowered or "socks" in lowered or "tunnel" in lowered:
        return "代理连接失败，请检查代理地址或代理软件"
    if "timeout" in lowered or "timed out" in lowered:
        return "连接超时，请检查网络或代理节点"
    if "dns" in lowered or "resolve" in lowered or "getaddrinfo" in lowered:
        return "DNS 解析失败"
    return f"连接失败: {type(e).__name__}: {e}"


async def check_proxy(
    proxy_url: Optional[str] = None,
    timeout: int = 10,
) -> DiagResult:
    """检查代理可用性"""
    from app.services.proxy_manager import get_effective_proxy_url
    # 统一走项目唯一定义源：内置 xray 实际端口 或 旧版 config.proxy
    effective = proxy_url or get_effective_proxy_url()
    if not effective:
        return DiagResult(
            name="proxy",
            status=DiagStatus.SKIPPED,
            message="代理未启用",
        )

    actual_proxy = effective
    if not actual_proxy:
        return DiagResult(
            name="proxy",
            status=DiagStatus.WARNING,
            message="代理已启用但地址为空",
        )

    start = time.time()
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            proxy=actual_proxy,
        ) as client:
            # 通过 ipinfo.io 检查代理出口 IP
            resp = await client.get("https://ipinfo.io/json")
            duration = int((time.time() - start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                return DiagResult(
                    name="proxy",
                    status=DiagStatus.OK,
                    message=f"代理可用 · 出口 IP: {data.get('ip', '?')} · 地区: {data.get('country', '?')}",
                    duration_ms=duration,
                    details={
                        "proxy": actual_proxy,
                        "exit_ip": data.get("ip"),
                        "country": data.get("country"),
                        "city": data.get("city"),
                    },
                )
            else:
                return DiagResult(
                    name="proxy",
                    status=DiagStatus.FAILED,
                    message=f"代理请求失败: HTTP {resp.status_code}",
                    duration_ms=duration,
                )
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return DiagResult(
            name="proxy",
            status=DiagStatus.FAILED,
            message=f"代理连接失败: {e}",
            duration_ms=duration,
        )


async def check_cookie(
    site_name: str,
    cookie: Optional[str] = None,
    timeout: int = 10,
) -> DiagResult:
    """检查 Cookie 有效性"""
    cfg = get_config().crawler
    actual_cookie = cookie or {
        "javdb": cfg.javdb_cookie,
        "javbus": cfg.javbus_cookie,
        "fc2ppvdb": cfg.fc2ppvdb_cookie,
    }.get(site_name)

    if not actual_cookie:
        return DiagResult(
            name=f"cookie:{site_name}",
            status=DiagStatus.SKIPPED,
            message=f"{site_name} 未配置 Cookie",
        )

    url = SITE_URLS.get(site_name)
    if not url:
        return DiagResult(
            name=f"cookie:{site_name}",
            status=DiagStatus.SKIPPED,
            message="未知站点",
        )

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Cookie": actual_cookie,
                },
            )
            duration = int((time.time() - start) * 1000)

            # 简单判断：登录页通常会有特定标识
            text = resp.text.lower()
            if resp.status_code == 200:
                # JavDB 登录后会有用户菜单
                if site_name == "javdb" and "logout" in text:
                    return DiagResult(
                        name=f"cookie:{site_name}",
                        status=DiagStatus.OK,
                        message="Cookie 有效（已登录）",
                        duration_ms=duration,
                    )
                if site_name == "javbus" and "logout" in text:
                    return DiagResult(
                        name=f"cookie:{site_name}",
                        status=DiagStatus.OK,
                        message="Cookie 有效（已登录）",
                        duration_ms=duration,
                    )
                return DiagResult(
                    name=f"cookie:{site_name}",
                    status=DiagStatus.WARNING,
                    message="Cookie 已配置但无法确认登录状态",
                    duration_ms=duration,
                )
            else:
                return DiagResult(
                    name=f"cookie:{site_name}",
                    status=DiagStatus.FAILED,
                    message=f"HTTP {resp.status_code}",
                    duration_ms=duration,
                )
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return DiagResult(
            name=f"cookie:{site_name}",
            status=DiagStatus.FAILED,
            message=f"检查失败: {e}",
            duration_ms=duration,
        )


async def run_full_diagnosis(task_id: str = "network-diag") -> DiagReport:
    """运行完整网络诊断"""
    from datetime import datetime

    report = DiagReport()
    report.started_at = datetime.now().isoformat()

    start = time.time()
    cfg = get_config()
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()

    await emit_log("INFO", "开始网络诊断...", task_id=task_id, module="network-diag")

    # 1. 代理检查
    await emit_log("DEBUG", "检查代理...", task_id=task_id, module="network-diag")
    proxy_result = await check_proxy(proxy_url=proxy_url, timeout=cfg.network_diag.timeout)
    report.items.append(proxy_result)
    await emit_log(
        "SUCCESS" if proxy_result.status == DiagStatus.OK else "WARNING" if proxy_result.status == DiagStatus.SKIPPED else "ERROR",
        f"代理检查: {proxy_result.message}",
        task_id=task_id,
        module="network-diag",
    )

    # 2. 各站点连通性
    for site in cfg.network_diag.target_sites:
        await emit_log("DEBUG", f"检查站点 {site}...", task_id=task_id, module="network-diag")
        site_result = await check_site_connectivity(
            site, timeout=cfg.network_diag.timeout, proxy_url=proxy_url,
        )
        report.items.append(site_result)
        level = "SUCCESS" if site_result.status == DiagStatus.OK else "WARNING" if site_result.status == DiagStatus.WARNING else "ERROR"
        await emit_log(
            level,
            f"站点 {site}: {site_result.message}",
            task_id=task_id,
            module="network-diag",
        )

    # 3. Cookie 检查
    cookie_sites = ["javdb", "javbus", "fc2ppvdb"]
    for site in cookie_sites:
        cookie_result = await check_cookie(site, timeout=cfg.network_diag.timeout)
        report.items.append(cookie_result)

    # 汇总
    report.total_duration_ms = int((time.time() - start) * 1000)
    report.finished_at = datetime.now().isoformat()
    report.summary = {
        "total": len(report.items),
        "ok": sum(1 for r in report.items if r.status == DiagStatus.OK),
        "warning": sum(1 for r in report.items if r.status == DiagStatus.WARNING),
        "failed": sum(1 for r in report.items if r.status == DiagStatus.FAILED),
        "skipped": sum(1 for r in report.items if r.status == DiagStatus.SKIPPED),
    }

    await emit_log(
        "INFO",
        f"诊断完成 · 耗时 {report.total_duration_ms}ms · OK:{report.summary['ok']} WARN:{report.summary['warning']} FAIL:{report.summary['failed']}",
        task_id=task_id,
        module="network-diag",
    )

    return report
