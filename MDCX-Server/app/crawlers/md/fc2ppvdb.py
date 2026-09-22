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

def get_video_time(data):  # 获取视频时长（上游统一为分钟，与库内其它模块一致）
    duration = str(data.get("article", {}).get("duration", "")).strip()
    if not duration:
        return ""
    temp_list = duration.split(":")
    if len(temp_list) == 3:
        hours, minutes, seconds = temp_list
        try:
            total_minutes = int(hours) * 60 + int(minutes)
            if total_minutes == 0 and int(seconds) > 0:
                return "1"
            return str(total_minutes)
        except ValueError:
            return duration
    if len(temp_list) <= 2 and temp_list[0].isdigit():
        return str(int(temp_list[0]))
    return duration

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
            # 1) 先访问详情页，让站点接受配置中的独立 cookie
            url_article = f"{base_url}/articles/{number}"
            response_article = await session.get(url_article, proxy=proxy)
            if response_article.status != 200:
                raise Exception(f"详情页请求失败: {response_article.status}")
            # 详情页跳转到登录页，说明 cookie 未生效/已过期
            if "/login" in str(response_article.url):
                response_article.close()
                raise Exception("详情页跳转到登录页，fc2ppvdb Cookie 可能无效或已过期")
            response_article.close()

            # 2) 再访问 XHR 接口获取 JSON 数据（带 XHR 头，模拟页面内请求）
            xhr_url = f"{base_url}/articles/article-info?videoid={number}"
            xhr_headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": url_article,
                "X-Requested-With": "XMLHttpRequest",
            }
            response_xhr = await session.get(xhr_url, proxy=proxy, headers=xhr_headers)
            if response_xhr.status != 200:
                raise Exception(f"XHR 请求失败: {response_xhr.status}")
            try:
                html_info = await response_xhr.json()
            except Exception as e:
                text = await response_xhr.text()
                text_preview = " ".join(text.strip().split())[:120]
                # 接口返回登录页/HTML 而非 JSON，通常是 cookie 失效
                if "login" in text.lower() or text.lstrip().startswith("<!DOCTYPE html"):
                    raise Exception(f"XHR 返回登录页/HTML（cookie 可能失效）：{text_preview}")
                raise Exception(f"XHR 返回内容不是有效 JSON: {e}；响应摘要={text_preview}")
            response_xhr.close()

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
