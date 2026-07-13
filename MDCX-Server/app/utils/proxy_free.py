"""免代理地址发现与代理切换策略(借鉴 JavSP javsp/web/proxyfree.py)

JavSP 面对的问题:目标站点(JavBus/JavDB/JavLibrary/Avsox)在中国大陆被 GFW 屏蔽,
但站点官方会通过"防屏蔽地址"机制发布临时镜像域名。本模块通过爬取各站点官方提供的
"通告入口"动态发现可用镜像域名。

移植改进(相对 JavSP):
1. 改为异步(MDCX-Server 基于 asyncio)
2. 用注册表模式替代 JavSP 的 dir(sys.modules[__name__]) 反射
3. 加 TTL 缓存(默认 1 小时),避免高频请求被封
4. 失败记录日志(JavSP 吞掉异常返回空字符串,难以排查)
5. 保留 JavSP 的 4 个站点发现器:avsox/javbus/javlib/javdb

典型用法:
    from app.utils.proxy_free import get_proxy_free_url
    url = await get_proxy_free_url('javbus')
    # 或带预配置:
    url = await get_proxy_free_url('javbus', prefer_url='https://www.seedmm.help')
"""

import asyncio
import logging
import re
import time
from typing import Callable, Optional

from curl_cffi import AsyncSession

logger = logging.getLogger(__name__)

# ============================================
# 注册表与缓存
# ============================================

# 站点发现函数注册表(替代 JavSP 的 dir() 反射)
_DISCOVERERS: dict[str, Callable] = {}

# 缓存:(site_name) -> (url, expire_at)
# 借鉴 JavSP 的设计:每次调用都重新发现太慢,加 1 小时 TTL 缓存
_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 3600  # 1 小时
_CACHE_LOCK = asyncio.Lock()


def register(site_name: str) -> Callable:
    """装饰器:注册站点发现函数到 _DISCOVERERS 注册表

    替代 JavSP 的 dir(sys.modules[__name__]) 反射查找,可读性更好。

    用法:
        @register('javbus')
        async def _get_javbus_urls() -> list[str]:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        _DISCOVERERS[site_name.lower()] = fn
        return fn
    return decorator


# ============================================
# 连通性测试(无代理直连)
# ============================================

async def is_connectable(url: str, timeout: float = 5.0) -> bool:
    """异步连通性测试(无代理直连)

    借鉴 JavSP javsp/web/base.py:201-208 的 is_connectable 函数。
    关键:测试直连可用性,必须绕过全局代理配置,否则测出"代理通"误判为"直连通"。

    Args:
        url: 待测试的 URL
        timeout: 超时时间(秒),默认 5 秒

    Returns:
        True 如果 URL 可连通(不抛异常),False 否则
    """
    try:
        # 关键:proxy=None 强制无代理直连,绕过全局代理配置
        async with AsyncSession() as session:
            await session.get(url, timeout=timeout, proxy=None)
        return True
    except Exception as e:
        logger.debug(f"Not connectable: {url}: {e}")
        return False


# ============================================
# 核心调度函数
# ============================================

async def get_proxy_free_url(site_name: str, prefer_url: Optional[str] = None) -> str:
    """获取指定站点的免代理地址

    借鉴 JavSP javsp/web/proxyfree.py:8-30 的 get_proxy_free_url 函数。

    调度逻辑:
    1. 优先使用用户预配置(prefer_url),若能连通则直接返回
    2. 查 TTL 缓存,命中且未过期则返回缓存值
    3. 调用对应站点的发现函数(_get_{site}_urls)获取候选 URL 列表
    4. 逐个测试候选 URL 的连通性,返回第一个可连通的
    5. 失败返回空字符串(JavSP 行为兼容)

    Args:
        site_name: 站点名称(如 'javbus'、'javdb'、'javlib'、'avsox')
        prefer_url: 优先测试的用户预配置 URL(可选)

    Returns:
        可连通的免代理 URL,失败返回空字符串
    """
    # 1. 优先使用用户预配置
    if prefer_url and await is_connectable(prefer_url):
        logger.debug(f"使用预配置 URL: {prefer_url}")
        return prefer_url

    # 2. 查缓存
    async with _CACHE_LOCK:
        cached = _CACHE.get(site_name)
        if cached and cached[1] > time.time():
            logger.debug(f"使用缓存 URL for {site_name}: {cached[0]}")
            return cached[0]

    # 3. 查找发现函数
    discoverer = _DISCOVERERS.get(site_name.lower())
    if not discoverer:
        logger.warning(f"未注册站点 {site_name} 的发现函数")
        return ''

    # 4. 调用发现函数获取候选 URL
    try:
        urls = await discoverer()
    except Exception as e:
        logger.warning(f"发现 {site_name} 免代理地址失败: {e}")
        return ''

    # 5. 逐个测试连通性
    for url in urls:
        if await is_connectable(url):
            # 写入缓存
            async with _CACHE_LOCK:
                _CACHE[site_name] = (url, time.time() + _CACHE_TTL)
            logger.info(f"发现 {site_name} 免代理地址: {url}")
            return url

    logger.warning(f"所有 {site_name} 候选 URL 均不可连通: {urls}")
    return ''


def clear_cache(site_name: Optional[str] = None) -> None:
    """清除缓存

    Args:
        site_name: 指定站点名清除缓存,None 清除所有缓存
    """
    if site_name:
        _CACHE.pop(site_name, None)
    else:
        _CACHE.clear()


def get_supported_sites() -> list[str]:
    """获取已注册的站点列表"""
    return sorted(_DISCOVERERS.keys())


# ============================================
# 站点发现函数(借鉴 JavSP 的 _get_{site}_urls)
# ============================================

@register('avsox')
async def _get_avsox_urls() -> list[str]:
    """获取 Avsox 的免代理地址

    借鉴 JavSP javsp/web/proxyfree.py:40-43。
    通告入口:https://tellme.pw/avsox
    解析方式:XPath //h4/strong/a/@href 提取所有镜像链接
    """
    # 用 curl_cffi 无代理直连(通告入口站本身不被墙)
    async with AsyncSession() as session:
        resp = await session.get('https://tellme.pw/avsox', timeout=10, proxy=None)
        if resp.status_code != 200:
            logger.warning(f"tellme.pw/avsox 返回 {resp.status_code}")
            return []
        html_text = resp.text

    # 用正则提取 href(避免引入 lxml 依赖)
    # JavSP 用 html.xpath('//h4/strong/a/@href'),这里用正则替代
    urls = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>', html_text)
    # 过滤出 http(s) URL
    urls = [u for u in urls if u.startswith('http')]
    logger.debug(f"Avsox 候选 URL: {urls}")
    return urls


@register('javbus')
async def _get_javbus_urls() -> list[str]:
    """获取 JavBus 的免代理地址

    借鉴 JavSP javsp/web/proxyfree.py:46-50。
    通告入口:https://www.javbus.one/
    解析方式:正则匹配文本中"防屏蔽地址："后跟的域名
    """
    async with AsyncSession() as session:
        resp = await session.get('https://www.javbus.one/', timeout=10, proxy=None)
        if resp.status_code != 200:
            logger.warning(f"javbus.one 返回 {resp.status_code}")
            return []
        text = resp.text

    # JavSP 正则:r'防屏蔽地址：(https://(?:[\d\w][-\d\w]{1,61}[\d\w]\.){1,2}[a-z]{2,})'
    matches = re.findall(
        r'防屏蔽地址[：:](https://(?:[\d\w][-\d\w]{1,61}[\d\w]\.){1,2}[a-z]{2,})',
        text,
        re.I | re.A,
    )
    logger.debug(f"JavBus 候选 URL: {matches}")
    return matches


@register('javlib')
async def _get_javlib_urls() -> list[str]:
    """获取 JavLibrary 的免代理地址

    借鉴 JavSP javsp/web/proxyfree.py:53-59。
    通告入口:https://github.com/javlibcom
    解析方式:提取 GitHub Profile Bio 文本中的域名
    """
    async with AsyncSession() as session:
        resp = await session.get('https://github.com/javlibcom', timeout=10, proxy=None)
        if resp.status_code != 200:
            logger.warning(f"github.com/javlibcom 返回 {resp.status_code}")
            return []
        html_text = resp.text

    # JavSP 用 XPath 提取 bio 文本,这里用正则替代
    # bio 通常在 <div class="p-note user-profile-bio ...">...</div>
    bio_match = re.search(
        r'<div[^>]*class="[^"]*user-profile-bio[^"]*"[^>]*>(.*?)</div>',
        html_text,
        re.DOTALL,
    )
    if not bio_match:
        logger.debug("未找到 JavLib GitHub bio")
        return []
    bio_text = re.sub(r'<[^>]+>', '', bio_match.group(1)).strip()

    # JavSP:re.search(r'[\w\.]+', text, re.A) 提取域名
    match = re.search(r'[\w\.]+', bio_text, re.A)
    if match:
        domain = f'https://www.{match.group(0)}.com'
        logger.debug(f"JavLib 候选 URL: [{domain}]")
        return [domain]
    return []


@register('javdb')
async def _get_javdb_urls() -> list[str]:
    """获取 JavDB 的免代理地址

    借鉴 JavSP javsp/web/proxyfree.py:62-70。
    通告入口:https://jav524.app
    解析方式:遍历 <script src> 链接,找到 /js/index 资源后
              正则匹配 $officialUrl = "https://..."
    """
    async with AsyncSession() as session:
        resp = await session.get('https://jav524.app', timeout=10, proxy=None)
        if resp.status_code != 200:
            logger.warning(f"jav524.app 返回 {resp.status_code}")
            return []
        html_text = resp.text

    # 提取所有 <script src="..."> 链接
    js_links = re.findall(r'<script[^>]+src="([^"]+)"', html_text)

    # 遍历查找 /js/index 资源
    for link in js_links:
        if '/js/index' not in link:
            continue
        # 补全为绝对 URL
        if link.startswith('//'):
            link = 'https:' + link
        elif link.startswith('/'):
            link = 'https://jav524.app' + link

        try:
            async with AsyncSession() as js_session:
                js_resp = await js_session.get(link, timeout=10, proxy=None)
                if js_resp.status_code != 200:
                    continue
                js_text = js_resp.text

            # JavSP 正则:r'\$officialUrl\s*=\s*"(https://...)"'
            match = re.search(
                r'\$officialUrl\s*=\s*"(https://(?:[\d\w][-\d\w]{1,61}[\d\w]\.){1,2}[a-z]{2,})"',
                js_text,
                flags=re.I | re.A,
            )
            if match:
                url = match.group(1)
                logger.debug(f"JavDB 候选 URL: [{url}]")
                return [url]
        except Exception as e:
            logger.debug(f"解析 JavDB JS 失败: {link}: {e}")
            continue

    return []


# ============================================
# 代理/直连 fallback 策略(借鉴 JavSP javlib.py 模式 C)
# ============================================

async def discover_with_fallback(
    site_name: str,
    permanent_url: str,
    use_proxy: bool = True,
) -> str:
    """代理/直连 fallback 策略(借鉴 JavSP javlib.py:21-44 模式 C)

    JavSP javlib 的最复杂策略:
    1. 动态发现镜像 URL
    2. 候选 URL 列表 = [配置镜像, 动态镜像, 永久域名](去重)
    3. 双层循环:外层 [直连, 代理],内层遍历候选 URL
    4. 直连时不尝试 permanent_url(因为直连一定不通)
    5. 注释:"使用代理容易触发 IUAM 保护,先尝试不使用代理访问"

    Args:
        site_name: 站点名(如 'javlib')
        permanent_url: 永久域名(如 'https://www.javlibrary.com')
        use_proxy: 是否在直连失败后尝试代理(默认 True)

    Returns:
        可连通的 URL,失败返回空字符串
    """
    from app.config.manager import get_config

    # 1. 收集候选 URL
    candidates: list[str] = []

    # 1a. 用户配置的镜像(从 config.proxy.proxy_free_urls 读取,如有)
    try:
        config = get_config()
        # 检查 ProxyConfig 是否有 proxy_free_urls 字段(未来扩展)
        configured = getattr(config.proxy, 'proxy_free_urls', None)
        if configured and site_name in configured:
            candidates.append(configured[site_name])
    except Exception:
        pass

    # 1b. 动态发现的镜像
    discovered = await get_proxy_free_url(site_name)
    if discovered:
        candidates.append(discovered)

    # 1c. 永久域名(代理模式才尝试,直连一定不通)
    if permanent_url:
        candidates.append(permanent_url)

    # 去重(保持顺序)
    seen = set()
    unique_candidates = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique_candidates.append(url)

    if not unique_candidates:
        return ''

    # 2. 双层循环:外层 [直连, 代理]
    # 直连在前(避免触发 IUAM),代理在后(兜底)
    proxy_modes = [False]  # 先直连
    if use_proxy:
        try:
            from app.services.proxy_manager import get_effective_proxy_url
            if get_effective_proxy_url():
                proxy_modes.append(True)  # 再代理
        except Exception:
            pass

    for use_proxy_mode in proxy_modes:
        for url in unique_candidates:
            # 直连模式跳过永久域名(一定不通)
            if not use_proxy_mode and url == permanent_url:
                continue
            try:
                async with AsyncSession() as session:
                    kwargs = {'timeout': 5, 'proxy': None}
                    if use_proxy_mode:
                        try:
                            from app.services.proxy_manager import get_effective_proxy_url
                            kwargs['proxy'] = get_effective_proxy_url()
                        except Exception:
                            pass
                    await session.get(url, **kwargs)
                logger.info(f"发现可用 URL for {site_name}: {url}(proxy={use_proxy_mode})")
                return url
            except Exception:
                continue

    logger.warning(f"所有 {site_name} 候选 URL 均不可连通: {unique_candidates}")
    return ''
