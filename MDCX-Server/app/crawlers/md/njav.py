"""
NJAV 爬虫 - 从 JavSP 移植

原始文件: javsp/web/njav.py
站点: https://njav.tv/ja

JavSP 原版不足之处已补全:
- 预览图列表解析(JavSP 原版始终为 None)
- 预告片视频 URL 解析
- 标签/系列/导演字段补全
"""

import logging
import re
import time
from typing import Optional

from lxml import etree

from app.crawlers.base import CrawlerPriority, ScrapeResult
from app.crawlers.legacy_adapter import LegacyCrawlerAdapter
from app.crawlers.md.compat import LogBuffer, manager
from app.crawlers.provider import register_crawler

logger = logging.getLogger(__name__)

BASE_URL = "https://njav.tv/ja"


def _get_first(lst) -> Optional[str]:
    """安全取列表首元素(JavSP get_list_first 等价)"""
    if lst and len(lst) > 0:
        return lst[0]
    return None


def _strftime_to_minutes(s: str) -> Optional[int]:
    """将 HH:MM:SS 或 MM:SS 时长转为分钟数(移植自 JavSP lib.py:27)

    Args:
        s: HH:MM:SS / MM:SS / 纯数字字符串

    Returns:
        取整后的分钟数,失败返回 None
    """
    if not s:
        return None
    s = s.strip()
    try:
        items = [int(x) for x in s.split(":")]
    except ValueError:
        # 包含非数字字符,提取首个数字作为分钟
        m = re.search(r"\d+", s)
        return int(m.group()) if m else None

    if len(items) == 1:
        # 纯数字(分钟)
        return items[0]
    if len(items) == 2:
        # MM:SS
        return items[0] + round(items[1] / 60)
    if len(items) == 3:
        # HH:MM:SS
        return items[0] * 60 + items[1] + round(items[2] / 60)
    return None


# ===== JavSP 原始解析函数 =====


def get_real_url(html, dvdid: str) -> str:
    """从搜索结果页解析详情页 URL

    Args:
        html: lxml etree HTML
        dvdid: 番号(大写)

    Returns:
        详情页 URL,未找到返回空字符串
    """
    items = html.xpath("//div[@class='box-item']/div[@class='detail']/a")
    for item in items:
        titles = item.xpath("text()")
        search_title = titles[0] if titles else ""
        if not search_title:
            continue
        if dvdid in search_title:
            href = item.xpath("@href")
            return _get_first(href) or ""
        # FC2 番号特殊匹配:FC2-123456 → 检查 "FC2" + "123456"
        if dvdid.startswith("FC2-"):
            fc2id = dvdid.replace("FC2-", "")
            if "FC2" in search_title and fc2id in search_title:
                href = item.xpath("@href")
                return _get_first(href) or ""
    return ""


def get_title(html) -> str:
    """从详情页提取标题(JavSP 原始 XPath)"""
    result = html.xpath(
        "//div[@class='d-flex justify-content-between align-items-start']/div/h1/text()"
    )
    return result[0].strip() if result else ""


def get_cover(html) -> str:
    """从详情页提取封面(data-poster 属性)"""
    result = html.xpath("//div[@id='player']/@data-poster")
    return _get_first(result) or ""


def get_plot(html) -> str:
    """从详情页提取简介"""
    parts = html.xpath("//div[@class='description']/p/text()")
    return " ".join(p.strip() for p in parts if p.strip())


def get_magnets(html) -> list[str]:
    """从详情页提取磁力链接列表"""
    return html.xpath("//div[@class='magnet']/a/@href")


def get_preview_pics(html) -> list[str]:
    """从详情页提取预览图列表(补全 JavSP 原版未实现的部分)

    NJAV 详情页结构:
    - div#preview-images / div.preview-image > img[data-src]
    - 或 ol.carousel > li > img[src]
    """
    pics = html.xpath("//div[contains(@class,'preview')]//img/@data-src")
    if not pics:
        pics = html.xpath("//div[contains(@class,'preview')]//img/@src")
    if not pics:
        pics = html.xpath("//ol[contains(@class,'carousel')]//img/@src")
    if not pics:
        # 兜底:扫描 #player 后的截图列表
        pics = html.xpath("//div[@id='player']/following-sibling::div//img/@src")
    # 去重并保留顺序
    seen = set()
    result = []
    for p in pics:
        if p and p not in seen and "data:image" not in p:
            seen.add(p)
            result.append(p)
    return result


def get_trailer_url(html) -> str:
    """从详情页提取预告片 URL(补全 JavSP 原版未实现的部分)"""
    # 优先:video 标签的 src
    result = html.xpath("//video[@id='player']//source/@src")
    if result:
        return result[0]
    # 兜底:data-preview-video 属性
    result = html.xpath("//div[@id='player']/@data-preview-video")
    return result[0] if result else ""


def get_detail_fields(html) -> dict:
    """从详情页 detail-item 块提取结构化字段

    JavSP 原始字段:
    - タグ / ジャンル → genre(标签)
    - レーベル → genre(JavSP 把 label 也归入 genre,这里保持一致)
    - 女優 → actress
    - シリーズ → serial(系列)
    - メーカー → producer(制作商)
    - コード → real_id(实际番号)
    - 公開日 → publish_date(发行日期)
    - 再生時間 → duration_str(时长)

    Returns:
        dict with keys: genre, actress, serial, producer, real_id,
        publish_date, duration_str
    """
    genre: list[str] = []
    actress: list[str] = []
    serial = None
    producer = None
    real_id = None
    publish_date = None
    duration_str = None

    for item in html.xpath("//div[@class='detail-item']/div"):
        titles = item.xpath("span/text()")
        if not titles:
            continue
        item_title = titles[0]
        # 第二个 span 内的文本/链接
        spans = item.xpath("span")
        second = spans[1] if len(spans) >= 2 else None

        if "タグ:" in item_title or "ジャンル:" in item_title or "レーベル:" in item_title:
            if second is not None:
                genre += second.xpath("a/text()")
        elif "女優:" in item_title:
            if second is not None:
                actress = second.xpath("a/text()")
        elif "シリーズ:" in item_title:
            if second is not None:
                serial = _get_first(second.xpath("a/text()"))
        elif "メーカー:" in item_title:
            if second is not None:
                producer = _get_first(second.xpath("a/text()"))
        elif "コード:" in item_title:
            if second is not None:
                real_id = _get_first(second.xpath("text()"))
        elif "公開日:" in item_title:
            if second is not None:
                publish_date = _get_first(second.xpath("text()"))
        elif "再生時間:" in item_title:
            if second is not None:
                duration_str = _get_first(second.xpath("text()"))

    return {
        "genre": genre,
        "actress": actress,
        "serial": serial,
        "producer": producer,
        "real_id": real_id,
        "publish_date": publish_date,
        "duration_str": duration_str,
    }


def get_actor_photo(actor_names: list[str]) -> dict:
    """构造演员头像字典(占位,与 MDCX 字段格式保持一致)"""
    return {name: "" for name in actor_names if name}


def get_mosaic(title: str, magnets: list[str]) -> str:
    """判断是否有码

    JavSP 原始逻辑:magnet 链接或标题中出现 'uncensored' 即视为无码
    """
    uncensored_arr = magnets + [title]
    for s in uncensored_arr:
        if s and "uncensored" in s.lower():
            return "无码"
    return "有码"


def clean_title(title: str, real_id: Optional[str], dvdid: str) -> str:
    """清除标题里的番号字符(JavSP 原始逻辑)"""
    keywords = [real_id, " "]
    if dvdid.startswith("FC2"):
        keywords += ["FC2", "PPV", "-", dvdid.split("-")[-1]]
    for kw in keywords:
        if kw:
            title = re.sub(re.escape(kw), "", title, flags=re.IGNORECASE)
    return title.strip()


# ===== MDCX 风格 main 函数 =====


async def main(number, appoint_url="", **kwargs):
    """NJAV 爬虫主入口

    Args:
        number: 番号(如 ABC-123, FC2-123456)
        appoint_url: 指定详情页 URL(可选,绕过搜索)

    Returns:
        MDCX 风格 dict: {"njav": {"zh_cn": {...}, "zh_tw": {...}, "jp": {...}}}
    """
    start_time = time.time()
    website_name = "njav"
    LogBuffer.req().write(f"-> {website_name}")
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 njav")
    debug_info = ""

    # 标准化番号(大写)
    dvdid = (number or "").upper()

    try:
        real_url = appoint_url or ""

        # 1. 若无指定 URL,先搜索详情页
        if not real_url:
            search_url = f"{BASE_URL}/search?keyword={dvdid}"
            debug_info = f"搜索页地址: {search_url} "
            LogBuffer.info().write(web_info + debug_info)

            search_html_text, error = await manager.computed.async_client.get_text(search_url)
            if search_html_text is None:
                debug_info = f"搜索页请求错误: {error}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

            search_html = etree.fromstring(search_html_text, etree.HTMLParser())
            real_url = get_real_url(search_html, dvdid)

            if not real_url:
                debug_info = f"搜索页未匹配到番号: {dvdid}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

        # 2. 抓取详情页
        debug_info = f"番号地址: {real_url} "
        LogBuffer.info().write(web_info + debug_info)

        detail_html_text, error = await manager.computed.async_client.get_text(real_url)
        if detail_html_text is None:
            debug_info = f"详情页请求错误: {error}"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        html = etree.fromstring(detail_html_text, etree.HTMLParser())

        # 容器(JavSP 原始 XPath)
        containers = html.xpath("//div[@class='container']/div/div[@class='col']")
        if not containers:
            debug_info = "详情页结构异常: 未找到 .col 容器"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        # 3. 解析各字段
        title = get_title(html)
        if not title:
            debug_info = "数据获取失败: 标题为空"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        cover_url = get_cover(html)
        plot = get_plot(html)
        magnets = get_magnets(html)
        preview_pics = get_preview_pics(html)
        trailer_url = get_trailer_url(html)
        fields = get_detail_fields(html)

        real_id = fields["real_id"] or dvdid
        # 清除标题里的番号字符
        title = clean_title(title, fields["real_id"], dvdid)

        actress = fields["actress"]
        actor_str = ",".join(actress) if actress else ""
        actor_photo = get_actor_photo(actress)

        genre = fields["genre"] or []
        tag = ",".join(genre)

        # 时长:HH:MM:SS → 分钟
        runtime = ""
        if fields["duration_str"]:
            minutes = _strftime_to_minutes(fields["duration_str"])
            if minutes is not None:
                runtime = str(minutes)

        # 发行日期:YYYY-MM-DD 提取
        release = ""
        if fields["publish_date"]:
            m = re.search(r"\d{4}-\d{1,2}-\d{1,2}", fields["publish_date"])
            if m:
                release = m.group()

        year = release[:4] if release else ""

        # FC2 封面特殊处理:封面 220x220 比例异常,使用第一张预览图代替
        if dvdid.startswith("FC2") and preview_pics:
            cover_url = preview_pics[0]

        mosaic = get_mosaic(title, magnets)

        try:
            dic = {
                "number": real_id,
                "title": title,
                "originaltitle": title,
                "actor": actor_str,
                "outline": plot,
                "originalplot": plot,
                "tag": tag,
                "release": release,
                "year": year,
                "runtime": runtime,
                "score": "",
                "series": fields["serial"] or "",
                "director": "",
                "studio": fields["producer"] or "",
                "publisher": fields["producer"] or "",
                "source": "njav",
                "actor_photo": actor_photo,
                "thumb": cover_url,
                "poster": "",
                "extrafanart": preview_pics,
                "trailer": trailer_url,
                "image_download": False,
                "image_cut": "right",
                "mosaic": mosaic,
                "website": real_url,
                "wanted": "",
                # NJAV 特有:磁力链接
                "magnet": magnets,
            }
            debug_info = "数据获取成功！"
            LogBuffer.info().write(web_info + debug_info)

        except Exception as e:
            debug_info = f"数据生成出错: {str(e)}"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

    except Exception as e:
        LogBuffer.error().write(str(e))
        dic = {
            "title": "",
            "thumb": "",
            "website": "",
        }

    result = {website_name: {"zh_cn": dic, "zh_tw": dic, "jp": dic}}
    LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
    return result


if __name__ == "__main__":
    import asyncio

    async def _test():
        # 测试样例
        r = await main("SSIS-001")
        print(r)

    asyncio.run(_test())


# ===== 爬虫类 =====


@register_crawler
class NjavCrawler(LegacyCrawlerAdapter):
    """NJAV 爬虫

    站点: https://njav.tv/ja
    支持: 标准 JAV 番号 + FC2 番号
    特点: 包含磁力链接字段,适合作为元数据补充源
    """

    name = "njav"
    display_name = "NJAV"
    base_url = BASE_URL

    priority = CrawlerPriority.LOW
    supported_types = ["jav", "fc2"]
    supported_prefixes = []
    description = "NJAV 日文站,含磁力链接"
    language = "ja"

    _main_func = staticmethod(main)

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号"""
        try:
            raw_result = await self._main_func(number=code)
            if not raw_result:
                return None
            return self._parse_result(raw_result, code)
        except Exception as e:
            logger.error(f"{self.name} scrape error for {code}: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索(NJAV 不支持站内搜索 API,返回空)"""
        return []
