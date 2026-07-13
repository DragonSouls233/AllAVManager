"""
Getchu DL 爬虫 - 从 MDCX 迁移

原始文件: getchu_dl.py
站点: https://dl.getchu.com
"""

import logging
import re
import time
import unicodedata
import urllib.parse
from typing import Optional

from lxml import etree

from app.crawlers.base import CrawlerPriority, ScrapeResult
from app.crawlers.legacy_adapter import LegacyCrawlerAdapter
from app.crawlers.md.compat import LogBuffer, manager
from app.crawlers.provider import register_crawler

logger = logging.getLogger(__name__)


# ===== MDCX 原始解析函数 =====

def get_title(html):
    result = html.xpath('//meta[@property="og:title"]/@content')
    return result[0].strip() if result else ""


def get_studio(html):
    return html.xpath("string(//td[text()='サークル']/following-sibling::td)")


def get_release(html):
    result = html.xpath("//td[contains(text(),'配信開始日')]/following-sibling::td/text()")
    return result[0].replace("/", "-") if result and re.search(r"\d+", result[0]) else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_director(html):
    return html.xpath('string(//td[text()="作者"]/following-sibling::td)').strip()


def get_runtime(html):
    result = html.xpath("//td[contains(text(),'画像数&ページ数')]/following-sibling::td/text()")
    if result:
        result = re.findall(r"\d*", result[0])
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath('//td[text()="趣向"]/following-sibling::td/a/text()')
    return ",".join(result) if result else ""


def get_cover(html):
    result = html.xpath('//meta[@property="og:image"]/@content')
    return result[0] if result else ""


def get_outline(html):
    return html.xpath('string(//td[text()="作品内容"]/following-sibling::td)').strip()


def get_extrafanart(html):
    result_list = html.xpath("//a[contains(@href,'/data/item_img/') and @class='highslide']/@href")
    result = []
    for each in result_list:
        result.append(f"https://dl.getchu.com{each}")
    return result


@register_crawler
class GetchuDlCrawler(LegacyCrawlerAdapter):
    """Getchu DL 爬虫"""

    name = "getchu_dl"
    display_name = "Getchu DL"
    base_url = "https://dl.getchu.com"
    priority = CrawlerPriority.NORMAL
    supported_types = ["jav"]
    supported_prefixes = ["DLID", "ITEM", "GETCHU"]
    description = "Getchu DL 数字下载版"
    language = "ja"
    requires_proxy = False

    def __init__(self):
        super().__init__()
        self._main_func = self._dl_main

    async def _dl_main(self, number, appoint_url="", **kwargs):
        """MDCX 原始 main 函数"""
        start_time = time.time()
        website_name = "getchu_dl"
        LogBuffer.req().write(f"-> {website_name}")
        real_url = appoint_url
        cover_url = ""
        image_cut = ""
        image_download = True
        url_search = ""
        web_info = "\n       "
        LogBuffer.info().write(" \n    🌐 dl_getchu")
        debug_info = ""
        cookies = {"adult_check_flag": "1"}

        if not real_url and ("DLID" in number.upper() or "ITEM" in number.upper() or "GETCHU" in number.upper()):
            id = re.findall(r"\d+", number)[0]
            real_url = f"https://dl.getchu.com/i/item{id}"

        try:
            if not real_url:
                keyword = unicodedata.normalize("NFC", number.replace("●", " "))
                keyword2 = urllib.parse.quote_plus(keyword, encoding="EUC-JP")
                url_search = f"https://dl.getchu.com/search/search_list.php?dojin=1&search_category_id=&search_keyword={keyword2}&btnWordSearch=%B8%A1%BA%F7&action=search&set_category_flag=1"
                debug_info = f"搜索地址: {url_search} "
                LogBuffer.info().write(web_info + debug_info)

                html_search, error = await manager.computed.async_client.get_text(
                    url_search, cookies=cookies, encoding="euc-jp"
                )
                if html_search is None:
                    debug_info = f"网络请求错误: {error} "
                    LogBuffer.info().write(web_info + debug_info)
                    raise Exception(debug_info)
                html = etree.fromstring(html_search, etree.HTMLParser())
                res_list = html.xpath("//table/tr/td[@valign='top' and not (@align)]/div/a")
                for each in res_list:
                    temp_url = each.get("href")
                    temp_title = each.xpath("string(.)")
                    if temp_url and "/item" in temp_url and temp_title and temp_title.startswith(number):
                        real_url = temp_url
                        break
                else:
                    debug_info = "搜索结果: 未匹配到番号！"
                    LogBuffer.info().write(web_info + debug_info)
                    raise Exception(debug_info)

            if real_url:
                debug_info = f"番号地址: {real_url} "
                LogBuffer.info().write(web_info + debug_info)

                html_content, error = await manager.computed.async_client.get_text(
                    real_url, cookies=cookies, encoding="euc-jp"
                )
                if html_content is None:
                    debug_info = f"网络请求错误: {error} "
                    LogBuffer.info().write(web_info + debug_info)
                    raise Exception(debug_info)
                html_info = etree.fromstring(html_content, etree.HTMLParser())
                number = "DLID-" + re.findall(r"\d+", real_url)[0]
                title = get_title(html_info)
                if not title:
                    debug_info = "数据获取失败: 未获取到title！"
                    LogBuffer.info().write(web_info + debug_info)
                    raise Exception(debug_info)
                outline = get_outline(html_info)
                actor = ""
                actor_photo = {"": ""}
                cover_url = get_cover(html_info)
                tag = get_tag(html_info)
                studio = get_studio(html_info)
                release = get_release(html_info)
                year = get_year(release)
                runtime = get_runtime(html_info)
                score = ""
                series = ""
                director = get_director(html_info)
                publisher = ""
                extrafanart = get_extrafanart(html_info)
                mosaic = "同人"
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
                        "source": "dl_getchu",
                        "actor_photo": actor_photo,
                        "thumb": cover_url,
                        "poster": cover_url,
                        "extrafanart": extrafanart,
                        "trailer": "",
                        "image_download": image_download,
                        "image_cut": image_cut,
                        "mosaic": mosaic,
                        "website": real_url,
                        "wanted": "",
                    }
                    debug_info = "数据获取成功！"
                    LogBuffer.info().write(web_info + debug_info)

                except Exception as e:
                    debug_info = f"数据生成出错: {str(e)}"
                    LogBuffer.info().write(web_info + debug_info)
                    raise Exception(debug_info)
        except Exception as e:
            LogBuffer.error().write(str(e))
            dic = {"title": "", "thumb": "", "website": ""}
        dic = {website_name: {"zh_cn": dic, "zh_tw": dic, "jp": dic}}
        LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
        return dic


async def main(
    number: str,
    appoint_url: str = "",
    **kwargs,
) -> Optional[dict]:
    """
    MDCX main 接口（供 getchu.py 回退调用）。

    处理 DLID/ITEM/GETCHU 类数字下载版番号，委托给 GetchuDlCrawler 的
    _dl_main 实现，返回 MDCX 字典格式。失败时返回 None。
    """
    try:
        crawler = GetchuDlCrawler()
        return await crawler._dl_main(number, appoint_url=appoint_url, **kwargs)
    except Exception as e:
        logger.error(f"GetchuDl main fallback error for {number}: {e}")
        return None

