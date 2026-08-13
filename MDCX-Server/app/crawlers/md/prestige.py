"""
Prestige 爬虫 - 从 MDCX 迁移

原始文件: prestige.py
"""

import logging
import re
import time
import traceback
from typing import Optional

from lxml import etree

from app.crawlers.base import CrawlerPriority, ScrapeResult
from app.crawlers.legacy_adapter import LegacyCrawlerAdapter
from app.crawlers.md.compat import LogBuffer, manager
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


def _coerce_json(obj):
    """将 get_json 可能返回的字符串 / 已解析对象规整为 dict；失败返回 None。

    CompatAsyncClient.get_json 在 JSON 解析失败时会回退返回原始文本(str)，
    直接传给期望 dict 的解析函数会触发 `string indices must be integers` 崩溃。
    这里统一兜底：str -> json.loads -> dict；其余返回 None 以走"解析失败"分支。
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            import json as _json
            parsed = _json.loads(obj)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


# ===== MDCX 原始解析函数 =====

def get_actor(page_data):
    actor_new_list = []
    for each in page_data["actress"]:
        actor_new_list.append(each["name"].replace(" ", ""))
    return ",".join(actor_new_list)

def get_actor_photo(actor):
    actor = actor.split(",")
    data = {}
    for i in actor:
        actor_photo = {i: ""}
        data.update(actor_photo)
    return data

def get_extrafanart(page_data):
    result = []
    for each in page_data["media"]:
        result.append("https://www.prestige-av.com/api/media/" + each["path"])
    return result

def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release

def get_tag(page_data):
    new_list = []
    for each in page_data["genre"]:
        new_list.append(each["name"])
    return ",".join(new_list)

def get_real_url(html_search, number):
    result = html_search["hits"]["hits"]
    for each in result:
        productUuid = each["_source"]["productUuid"]
        deliveryItemId = each["_source"]["deliveryItemId"]
        if deliveryItemId.endswith(number.upper()):
            return "https://www.prestige-av.com/api/product/" + productUuid
    return ""

async def main(
    number,
    appoint_url="",
    **kwargs,
):
    start_time = time.time()
    website_name = "prestige"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url.replace("goods", "api/product")
    image_cut = "right"
    image_download = True
    search_url = ""
    mosaic = ""
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 prestige")
    debug_info = ""
    poster = ""

    # search_url = https://www.prestige-av.com/api/search?isEnabledQuery=true&searchText=abw-130&isEnableAggregation=false&release=false&reservation=false&soldOut=false&from=0&aggregationTermsSize=0&size=20
    # real_url = https://www.prestige-av.com/api/product/2e4a2de8-7275-4803-bb07-7585fd4f2ff3

    try:  # 捕获主动抛出的异常
        if not real_url:
            # 通过搜索获取real_url
            search_url = f"https://www.prestige-av.com/api/search?isEnabledQuery=true&searchText={number}&isEnableAggregation=false&release=false&reservation=false&soldOut=false&from=0&aggregationTermsSize=0&size=20"
            debug_info = f"搜索地址: {search_url} "
            LogBuffer.info().write(web_info + debug_info)

            # ========================================================================搜索番号
            _search_headers = {
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.prestige-av.com/",
                "Origin": "https://www.prestige-av.com",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            }
            raw_search, error = await manager.computed.async_client.get_json(search_url, headers=_search_headers)
            html_search = _coerce_json(raw_search)
            if html_search is None:
                # get_json 已在 error 中带回真实根因(HTTP状态/超时/反爬HTML),
                # 直接暴露,不再误报"响应非合法 JSON"。
                debug_info = f"搜索结果解析失败: {error or '响应为空或非JSON'}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

            real_url = get_real_url(html_search, number)
            if not real_url:
                debug_info = "搜索结果: 未匹配到番号！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

        if real_url:
            # 'https://www.prestige-av.com/goods/2e4a2de8-7275-4803-bb07-7585fd4f2ff3'
            # 'https://www.prestige-av.com/api/product/2e4a2de8-7275-4803-bb07-7585fd4f2ff3'
            debug_info = f"番号地址: {real_url.replace('api/product', 'goods')} "
            LogBuffer.info().write(web_info + debug_info)
            _detail_headers = {
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.prestige-av.com/",
                "Origin": "https://www.prestige-av.com",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            }
            raw_detail, error = await manager.computed.async_client.get_json(real_url, headers=_detail_headers)
            page_data = _coerce_json(raw_detail)
            if page_data is None:
                debug_info = f"详情解析失败: {error or '响应为空或非JSON'}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

            title = page_data["title"].replace("【配信専用】", "")
            if not title:
                debug_info = "数据获取失败: 未获取到 title！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            outline = page_data["body"]
            actor = get_actor(page_data)
            actor_photo = get_actor_photo(actor)
            # https://www.prestige-av.com/api/media/goods/prestige/abw/130/pf_abw-130.jpg
            try:
                poster = "https://www.prestige-av.com/api/media/" + page_data["thumbnail"]["path"]
                if "noimage" in poster:
                    poster = ""
            except Exception:
                poster = ""
            try:
                cover_url = "https://www.prestige-av.com/api/media/" + page_data["packageImage"]["path"]
            except Exception:
                cover_url = ""
            try:
                release = page_data["sku"][0]["salesStartAt"][:10]
            except Exception:
                release = ""
            year = get_year(release)
            runtime = str(page_data["playTime"])
            score = ""
            try:
                series = page_data["series"]["name"]
            except Exception:
                series = ""
            tag = get_tag(page_data)
            try:
                director = page_data["directors"][0]["name"]
            except Exception:
                director = ""
            try:
                studio = page_data["maker"]["name"]
            except Exception:
                studio = ""
            try:
                publisher = page_data["label"]["name"]
            except Exception:
                publisher = ""
            extrafanart = get_extrafanart(page_data)
            try:
                trailer = "https://www.prestige-av.com/api/media/" + page_data["movie"]["path"]
            except Exception:
                trailer = ""
            mosaic = "有码"
            try:
                dic = {
                    "number": number,
                    "title": title,
                    "originaltitle": title,
                    "actor": actor,
                    "outline": outline,
                    "originalplot": outline,
                    "tag": tag,
                    "release": release,
                    "year": year,
                    "runtime": runtime,
                    "score": score,
                    "series": series,
                    "director": director,
                    "studio": studio,
                    "publisher": publisher,
                    "source": "prestige",
                    "actor_photo": actor_photo,
                    "thumb": cover_url,
                    "poster": poster,
                    "extrafanart": extrafanart,
                    "trailer": trailer,
                    "image_download": image_download,
                    "image_cut": image_cut,
                    "mosaic": mosaic,
                    "website": real_url.replace("api/product", "goods"),
                    "wanted": "",
                }
                debug_info = "数据获取成功！"
                LogBuffer.info().write(web_info + debug_info)

            except Exception as e:
                debug_info = f"数据生成出错: {str(e)}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
    except Exception as e:
        # 403/反爬/超时属于预期内失败：只记一行警告，不打完整堆栈刷屏
        logger.warning(f"[prestige] {number} 刮削失败: {e}")
        LogBuffer.error().write(str(e))
        dic = {
            "title": "",
            "thumb": "",
            "website": "",
        }
    dic = {
        "official": {"zh_cn": dic, "zh_tw": dic, "jp": dic},
        website_name: {"zh_cn": dic, "zh_tw": dic, "jp": dic},
    }
    LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
    return dic

if __name__ == "__main__":
    # yapf: disable
    # print(main('abw-130'))
    print(main('FCP-150'))  # print(main('fakwm-064', appoint_url='https://www.prestige-av.com/goods/dcb86b74-195b-46c4-8ced-71f5f3ce5c3c?skuId=ABW-344'))  # 有导演  # print(main('ABW-343'))  # 无图

# ===== 爬虫类 =====

@register_crawler
class PrestigeCrawler(LegacyCrawlerAdapter):
    """Prestige 爬虫"""

    name = "prestige"
    display_name = "Prestige"
    base_url = "https://prestige.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ['jav']
    supported_prefixes = ['PRESTIGE']
    description = "Prestige 厂牌"
    language = "ja"
    _main_func = staticmethod(main)

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索"""
        return []
