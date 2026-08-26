"""
FC2 PPV 爬虫

使用多级反爬策略（cf_bypass）：
1. curl_cffi Chrome 120 指纹模拟
2. Cloudflare Worker 代理转发
3. FlareSolverr 真实浏览器渲染
4. httpx 直连缓存兜底

全流程刮削：标题、封面、样图、简介、标签、发行日期、时长、演员、评分、预告片、卖家（厂商）、有无码
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from lxml import etree

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    CrawlerStatus,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.cf_bypass import get_cf_bypass
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


@register_crawler
class FC2Crawler(BaseCrawler):
    """FC2 PPV 官方站点爬虫"""

    name = "fc2"
    display_name = "FC2 PPV"
    base_url = "https://adult.contents.fc2.com"

    priority = CrawlerPriority.HIGH
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-"]
    description = "FC2 PPV 内容站点（含多级反爬）"
    language = "ja"
    requires_proxy = False

    def _extract_number_id(self, code: str) -> Optional[str]:
        """从番号中提取纯数字 ID（如 FC2-123456 → 123456）"""
        if not code:
            return None
        code = code.strip()
        m = re.search(r'(\d{5,7})', code)
        return m.group(1) if m else None

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """
        刮削指定番号，使用 cf_bypass 全流程反爬

        Args:
            code: 番号（如 FC2-123456 / 123456）
        """
        number_id = self._extract_number_id(code)
        if not number_id:
            return None

        detail_url = f"{self.base_url}/article/{number_id}/"

        html_text = None
        # 优先使用 cf_bypass 绕过 Cloudflare
        try:
            bypass_result = await get_cf_bypass().fetch(detail_url, timeout=45, max_retries=3)
            if bypass_result.success and bypass_result.html:
                html_text = bypass_result.html
                logger.info(f"FC2 cf_bypass 获取成功 [{code}], 策略={bypass_result.strategy}")
            else:
                logger.warning(f"FC2 cf_bypass 失败 [{code}]: {bypass_result.error}，降级到 httpx")
        except Exception as e:
            logger.warning(f"FC2 cf_bypass 异常 [{code}]: {e}，降级到 httpx")

        # 降级：直接使用 AsyncHttpClient
        if not html_text:
            async with AsyncHttpClient() as client:
                try:
                    html_text = await client.get_text(detail_url)
                except Exception as e:
                    self.mark_error()
                    logger.error(f"FC2 页面获取失败 [{code}]: {e}")
                    return None

        try:
            html = etree.fromstring(html_text.encode("utf-8"), etree.HTMLParser())
        except Exception:
            self.mark_error()
            return None

        if self._is_not_found(html):
            logger.info(f"FC2 未找到内容 [{code}]")
            return None

        result = await self._parse_detail_page(html, code, number_id, detail_url)

        if result:
            self.mark_success()
        else:
            self.mark_error()

        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """
        通过 FC2 站内搜索或番号精确查找
        
        支持：
        - 纯数字番号：直接跳转到详情页
        - 关键词：使用站内 /search/ 接口
        """
        results = []

        # 尝试提取番号
        number_id = self._extract_number_id(keyword)
        if number_id:
            result = await self.scrape(keyword)
            if result:
                results.append(result)
            return results

        # 关键词搜索（使用站内搜索页面）
        search_url = f"{self.base_url}/search/?keyword={keyword}"
        try:
            bypass_result = await get_cf_bypass().fetch(search_url, timeout=30, max_retries=2)
            if not bypass_result.success or not bypass_result.html:
                return results

            html = etree.fromstring(bypass_result.html.encode("utf-8"), etree.HTMLParser())
            # 提取搜索结果链接
            search_items = html.xpath('//a[contains(@href, "/article/")]/@href')
            for href in search_items[:20]:
                match = re.search(r"/article/(\d+)/", href)
                if match:
                    num = match.group(1)
                    full_code = f"FC2-{num}"
                    result = await self.scrape(full_code)
                    if result:
                        results.append(result)
        except Exception as e:
            logger.warning(f"FC2 搜索失败 [{keyword}]: {e}")

        return results
    
    def _is_not_found(self, html: etree._Element) -> bool:
        """检查是否为未找到页面"""
        # FC2 未找到页面特征
        title = html.xpath("//title/text()")
        if title and "not found" in title[0].lower():
            return True
        
        return False
    
    async def _parse_detail_page(
        self,
        html: etree._Element,
        code: str,
        number_id: str,
        detail_url: str = "",
    ) -> Optional[ScrapeResult]:
        """解析详情页 - 参考 mdcx fc2.py"""
        try:
            title = self._get_title(html)
            if not title:
                return None

            cover_url, sample_images = self._get_cover_and_samples(html)
            plot = self._get_plot(html)
            genres = self._get_genres(html)
            release_date = self._get_release_date(html)
            duration = self._get_duration(html)
            actors = self._get_actors(html)
            rating = self._get_rating(html)
            trailer_url = await self._get_trailer(number_id)
            studio = self._get_studio(html)
            seller = self._get_seller(html)
            is_uncensored = self._get_is_uncensored(html, genres, title)
            is_mosaic = not is_uncensored if is_uncensored is not None else None
            genres = [g for g in genres if g != "無修正"]
            poster_url = self._get_poster(html)

            return ScrapeResult(
                code=code,
                title=title,
                original_title=title,
                source=self.name,
                source_url=detail_url,
                studio=studio,
                maker=studio,
                series="FC2系列",
                release_date=release_date,
                duration=duration,
                plot=plot,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                poster_url=poster_url,
                trailer_url=trailer_url,
                sample_images=sample_images,
                extrafanart=sample_images,
                rating=rating,
                is_uncensored=is_uncensored,
                is_mosaic=is_mosaic,
                raw_data={"seller": seller},
            )

        except Exception as e:
            logger.error(f"FC2 详情页解析失败 [{code}]: {e}")
            return None
    
    def _get_title(self, html: etree._Element) -> str:
        """获取标题"""
        result = html.xpath('//div[@data-section="userInfo"]//h3/span/../text()')
        if result:
            return result[0].strip()
        
        # 备用选择器
        result = html.xpath("//h3/text()")
        return result[0].strip() if result else ""
    
    def _get_cover_and_samples(self, html: etree._Element) -> tuple[Optional[str], list[str]]:
        """获取封面和样图"""
        # 封面
        cover_result = html.xpath('//ul[@class="items_article_SampleImagesArea"]/li/a/@href')
        
        if cover_result:
            # 第一个通常是封面
            cover_url = cover_result[0]
            if cover_url.startswith("//"):
                cover_url = "https:" + cover_url
            elif cover_url.startswith("/"):
                cover_url = self.base_url + cover_url
            sample_images = []
            for url in cover_result[1:]:
                if url:
                    if url.startswith("//"):
                        url = "https:" + url
                    elif url.startswith("/"):
                        url = self.base_url + url
                    sample_images.append(url)
            return cover_url, sample_images
        
        return None, []
    
    def _get_plot(self, html: etree._Element) -> Optional[str]:
        """获取简介"""
        results = html.xpath('//section[contains(@class, "items_article_Contents")]//text()')
        if results:
            plot = " ".join([r.strip() for r in results if r.strip()])
            return plot if plot else None
        
        return None
    
    def _get_genres(self, html: etree._Element) -> list[str]:
        """获取标签"""
        results = html.xpath('//a[@class="tag tagTag"]/text()')
        return [r.strip() for r in results if r.strip()]
    
    def _get_release_date(self, html: etree._Element) -> Optional[date]:
        """获取发行日期"""
        result = html.xpath('//span[contains(text(), "販売日")]/../text()')
        if not result:
            return None
        
        date_str = result[0].strip()
        date_str = date_str.replace("/", "-").replace(".", "-")
        
        if match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str):
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
        
        return None
    
    def _get_duration(self, html: etree._Element) -> Optional[int]:
        """获取时长"""
        result = html.xpath('//span[contains(text(), "動画時間")]/../text()')
        if not result:
            return None
        
        duration_str = result[0].strip()
        
        # 格式: HH:MM:SS 或 MM:SS
        if ":" in duration_str:
            parts = duration_str.split(":")
            if len(parts) >= 2:
                try:
                    minutes = int(parts[0]) * 60 + int(parts[1]) if len(parts) >= 3 else int(parts[0])
                    return minutes
                except ValueError:
                    pass
        
        # 格式: XX分
        if match := re.search(r"(\d+)", duration_str):
            return int(match.group(1))
        
        return None
    
    def _get_actors(self, html: etree._Element) -> list[ActorInfo]:
        """获取演员列表"""
        actors = []
        
        # FC2 通常不显示演员名，或显示为 "個人撮影"
        results = html.xpath('//a[@class="tag tagActor"]/text()')
        
        for name in results:
            name = name.strip()
            if name:
                actors.append(ActorInfo(name=name))
        
        return actors
    
    def _get_rating(self, html: etree._Element) -> Optional[float]:
        """从JSON-LD获取评分"""
        result = html.xpath('//script[@type="application/ld+json"]/text()')
        if not result:
            return None
        
        try:
            data = json.loads(result[0])
            if "aggregateRating" in data:
                rating_value = data["aggregateRating"].get("ratingValue")
                if rating_value:
                    return float(rating_value)
        except (json.JSONDecodeError, ValueError):
            pass
        
        return None
    
    async def _get_trailer(self, number_id: str) -> Optional[str]:
        """通过 FC2 sample API 获取预告片，使用 cf_bypass 反爬"""
        api_url = f"{self.base_url}/api/v2/videos/{number_id}/sample"
        try:
            bypass_result = await get_cf_bypass().fetch(api_url, timeout=30, max_retries=2)
            if bypass_result.success and bypass_result.html:
                response_text = bypass_result.html
            else:
                logger.warning(f"FC2 预告片 API cf_bypass 失败 [{number_id}]")
                return None

            data = json.loads(response_text)
            path = data.get("path")
            if path:
                if path.startswith("http"):
                    return path
                elif path.startswith("/"):
                    return self.base_url + path
                return self.base_url + "/" + path
            return None

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"FC2 预告片获取失败 [{number_id}]: {e}")
            return None

    def _get_studio(self, html: etree._Element) -> Optional[str]:
        """获取卖家作为厂商 - 参考 mdcx fc2.py getStudio"""
        result = html.xpath('//div[@class="items_article_headerInfo"]/ul/li[last()]/a/text()')
        if result:
            return result[0].strip()
        return None

    def _get_seller(self, html: etree._Element) -> Optional[str]:
        """获取卖家信息"""
        result = html.xpath('//div[@class="items_article_headerInfo"]/ul/li[last()]/a/text()')
        if result:
            return result[0].strip()
        result = html.xpath('//span[contains(@class, "seller")]/text()')
        if result:
            return result[0].strip()
        return None

    def _get_is_uncensored(self, html: etree._Element, genres: list[str], title: str) -> Optional[bool]:
        """
        FC2 PPV 内容绝大多数为无码(無修正)。
        默认标记为无码，仅当页面明确出现"有码"标记时才反向标记。
        """
        tag_str = ",".join(genres)
        # 显式有码标记
        mosaic_keywords = ["有码", "修正", "モザイク"]
        for kw in mosaic_keywords:
            if kw in tag_str or kw in title:
                return False
        # FC2 默认无码
        return True

    def _get_poster(self, html: etree._Element) -> Optional[str]:
        """获取小图 - 参考 mdcx fc2.py getCoverSmall"""
        result = html.xpath('//div[@class="items_article_MainitemThumb"]/span/img/@src')
        if result:
            url = result[0]
            if url.startswith("//"):
                url = "https:" + url
            return url
        return None