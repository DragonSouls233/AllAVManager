"""
FC2PPVDB 爬虫 - 从 MDCX 迁移

原始文件: fc2ppvdb.py
"""

import logging
import re
import time
from http.cookies import SimpleCookie
from typing import Optional

import aiohttp
from lxml import etree

from app.crawlers.base import CrawlerPriority, ScrapeResult
from app.crawlers.legacy_adapter import LegacyCrawlerAdapter
from app.crawlers.md.compat import LogBuffer, manager
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

# ===== MDCX 原始解析函数 =====

def get_title(data):  # 获取标题
    return data.get("article", {}).get("title", "")

def get_cover(data, number):  # 获取封面URL
    image_url = data.get("article", {}).get("image_url", "")
    if image_url and "no-image" not in image_url:
        return image_url
    return ""

def get_release_date(data):  # 获取发行日期
    return data.get("article", {}).get("release_date", "")

def get_actors(data):  # 获取演员
    actresses = data.get("article", {}).get("actresses", [])
    return ",".join([actress.get("name", "") for actress in actresses]) if actresses else ""

def get_tags(data):  # 获取标签
    tags = data.get("article", {}).get("tags", [])
    return ",".join([tag.get("name", "") for tag in tags]) if tags else ""

def get_studio(data):  # 获取厂家
    writer = data.get("article", {}).get("writer", {})
    return writer.get("name", "")

def get_video_type(data):  # 获取视频类型
    censored = data.get("article", {}).get("censored")
    if censored == "無":
        return "無碼"
    elif censored == "有":
        return "有碼"
    else:
        return ""

def get_video_url(data):  # 获取视频URL
    # video_id = data.get("article", {}).get("video_id")
    # if video_id:
    #     return f"https://example.com/videos/{video_id}.mp4"
    return ""

def extract_inertia_props(html_text: Optional[str]) -> Optional[dict]:
    """从 Inertia.js 页面 HTML 中提取 JSON props。

    🔴 2026-10-04：fc2cmadb.com 改版为 Inertia.js，数据内嵌在
    ``<script type="application/json">{...}</script>``（Inertia v2）或
    ``<div id="app" data-page="{...}">``（v1 早期）里。
    兼容两种形态；解析失败返回 None（由调用方给出可诊断的错误信息）。
    """
    if not html_text:
        return None
    import html as _html
    import json as _json

    # 形态 1：data-page="..."（属性值里的 HTML 实体已转义）
    for m in re.finditer(r'data-page="([^"]+)"', html_text, re.DOTALL):
        try:
            obj = _json.loads(_html.unescape(m.group(1)))
        except (_json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            props = obj.get("props")
            if isinstance(props, dict):
                return props
            return obj

    # 形态 2：<script type="application/json">…</script>（Inertia v2）
    for m in re.finditer(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
        html_text, re.DOTALL,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            obj = _json.loads(_html.unescape(raw))
        except (_json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            props = obj.get("props")
            if isinstance(props, dict):
                return props
            return obj
    return None


def get_video_time(data):  # 获取视频时长（上游统一为分钟，与库内其它模块一致）
    """时长（分钟）—— 统一走 ``parse_runtime_minutes``（duration 唯一真相源）。

    🔴 旧实现手写 ``int(h)*60 + int(m)`` 会把 ``01:52:37`` 算成 **112**
    （正确 113），且不认 ``113分`` / ``1時間52分`` 这类写法。
    """
    from app.utils.nfo_runtime import parse_runtime_minutes

    duration = str(data.get("article", {}).get("duration", "")).strip()
    if not duration:
        return ""
    minutes = parse_runtime_minutes(duration)
    return str(minutes) if minutes is not None else ""

def cookie_str_to_dict(cookie_str: str) -> dict:  # cookie 转为字典（用 SimpleCookie 解析，兼容带引号/特殊字符的 value）
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_str)
    except Exception:
        return {}
    return {key: morsel.value for key, morsel in cookie.items()}

async def main(
    number,
    appoint_url="",
    **kwargs,
):
    """
    主函数，获取FC2视频信息
    :param number: 番号
    :param appoint_url: 指定的URL
    :param language: 语言
    :return: JSON格式的影片信息
    """
    start_time = time.time()
    website_name = "fc2ppvdb"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url
    number = number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
    dic = {}
    web_info = "\n       "

    try:
        debug_info = f"番号地址: {real_url}"
        LogBuffer.info().write(web_info + debug_info)
        # ========================================================================番号详情页
        # 使用独立的 fc2ppvdb cookie
        from app.utils.cookie_manager import get_cookie
        cookie_str = get_cookie("fc2ppvdb") or ""
        cookies = cookie_str_to_dict(cookie_str)
        base_url = "https://fc2cmadb.com"
        proxies = {"http": manager.config.proxy, "https": manager.config.proxy} if manager.config.use_proxy else None
        proxy = proxies["http"] if proxies else None
        # aiohttp 新版 API：ClientSession + request 级 proxy（旧版 AsyncSession/proxies 已移除）
        # 同一 session 的 cookie jar 会在两次请求间保持，先访问详情页可让站点接受独立 cookie（warmup）
        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 1) 访问详情页，让站点接受配置中的独立 cookie
            url_article = f"{base_url}/articles/{number}"
            response_article = await session.get(url_article, proxy=proxy)
            if response_article.status != 200:
                raise Exception(f"详情页请求失败: {response_article.status}")
            # 详情页跳转到登录页，说明 cookie 未生效/已过期
            if "/login" in str(response_article.url):
                response_article.close()
                raise Exception("详情页跳转到登录页，fc2ppvdb Cookie 可能无效或已过期")
            article_html = await response_article.text()
            response_article.close()

            # 2) 🔴 2026-10-04 真实抓取核实：fc2cmadb.com 已改版为 **Inertia.js**。
            #    旧 XHR 接口 `/articles/article-info?videoid=<id>` **已废弃** ——
            #    现在返回站点首页 HTML（实测 Accept: application/json 也一样），
            #    ⇒ `response_xhr.json()` 必抛异常 ⇒ **该源 100% 失效**
            #    （表现为「fc2ppvdb NONE」，且被误判成「cookie 失效」）。
            #    新数据内嵌在详情页的
            #    `<script type="application/json">{...}</script>`（Inertia v2 props）
            #    里，直接从详情页 HTML 提取。
            html_info = extract_inertia_props(article_html)
            if not html_info or not html_info.get("article"):
                preview = " ".join((article_html or "").strip().split())[:120]
                raise Exception(
                    "未从详情页 Inertia props 提取到数据"
                    f"（站点结构可能再变，len={len(article_html or '')}）：{preview}"
                )

        title = get_title(html_info)
        if not title:
            debug_info = "数据获取失败: 未获取到title！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        cover_url = get_cover(html_info, number)
        if "http" not in cover_url:
            debug_info = "数据获取失败: 未获取到cover！"
            LogBuffer.info().write(web_info + debug_info)
        release_date = get_release_date(html_info)
        year = release_date[:4] if release_date else ""
        actor = get_actors(html_info)
        tag = get_tags(html_info)
        studio = get_studio(html_info)  # 使用卖家作为厂商
        video_type = get_video_type(html_info)
        video_url = get_video_url(html_info)
        video_time = get_video_time(html_info)
        tag = tag.replace("無修正,", "").replace("無修正", "").strip(",")
        if "fc2_seller" in manager.config.fields_rule:
            actor = studio

        try:
            dic = {
                "number": "FC2-" + str(number),
                "title": title,
                "originaltitle": title,
                "outline": "",
                "actor": actor,
                "originalplot": "",
                "tag": tag,
                "release": release_date,
                "year": year,
                "runtime": video_time,
                "score": "",
                "series": "FC2系列",
                "director": "",
                "studio": studio,
                "publisher": studio,
                "source": "fc2",
                "website": real_url,
                "actor_photo": {actor: ""},
                "thumb": cover_url,
                "poster": cover_url,
                "extrafanart": [],
                "trailer": video_url,
                "image_download": False,
                "image_cut": "center",
                "mosaic": "无码" if video_type == "無碼" else "有码",
                "wanted": "",
            }
            debug_info = "数据获取成功！"
            LogBuffer.info().write(web_info + debug_info)
        except Exception as e:
            debug_info = f"数据生成出错: {str(e)}"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

    except Exception as e:
        # print(traceback.format_exc())
        LogBuffer.error().write(str(e))
        dic = {
            "title": "",
            "thumb": "",
            "website": "",
        }
    dic = {website_name: {"zh_cn": dic, "zh_tw": dic, "jp": dic}}
    LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
    return dic

if __name__ == "__main__":
    print(main("FC2-3259498"))

# ===== 爬虫类 =====

@register_crawler
class FC2PPVDBCrawler(LegacyCrawlerAdapter):
    """FC2PPVDB 爬虫"""

    name = "fc2ppvdb"
    display_name = "FC2PPVDB"
    base_url = "https://fc2cmadb.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ['fc2']
    supported_prefixes = ['FC2']
    description = "FC2PPVDB"
    language = "en"
    _main_func = staticmethod(main)

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索"""
        return []
