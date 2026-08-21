"""
FC2 爬虫
"""

import json
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
from app.utils.http_client import AsyncHttpClient


@register_crawler
class FC2Crawler(BaseCrawler):
    """FC2 爬虫"""
    
    name = "fc2"
    display_name = "FC2"
    base_url = "https://adult.contents.fc2.com"
    
    priority = CrawlerPriority.HIGH
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-"]
    description = "FC2 PPV 内容站点"
    language = "ja"
    requires_proxy = False
    
    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """
        刮削指定番号
        
        Args:
            code: 番号（如 FC2-123456）
            
        Returns:
            ScrapeResult 刮削结果
        """
        # 提取纯数字ID
        number_id = self._extract_number_id(code)
        if not number_id:
            return None
        
        async with AsyncHttpClient() as client:
            try:
                detail_url = f"{self.base_url}/article/{number_id}/"
                
                html_text = await client.get_text(detail_url)
                html = etree.fromstring(html_text, etree.HTMLParser())
                
                # 检查是否找到页面
                if self._is_not_found(html):
                    return None
                
                # 解析详情页
                result = await self._parse_detail_page(html, code, number_id, client, detail_url)
                
                if result:
                    self.mark_success()
                else:
                    self.mark_error()
                
                return result
            
            except Exception as e:
                self.mark_error()
                raise e
    
    async def search(self, keyword: str) -> list[ScrapeResult]:
        """
        搜索番号
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            搜索结果列表
        """
        # FC2 搜索功能暂不实现
        return []
    
    def _extract_number_id(self, code: str) -> Optional[str]:
        """从番号提取纯数字ID"""
        code = code.upper()
        code = code.replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
        
        if code.isdigit():
            return code
        
        return None
    
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
        client: AsyncHttpClient,
        detail_url: str = "",
    ) -> Optional[ScrapeResult]:
        """解析详情页 - 参考 mdcx fc2.py"""
        try:
            # 标题
            title = self._get_title(html)
            if not title:
                return None
            
            # 封面和样图
            cover_url, sample_images = self._get_cover_and_samples(html)
            
            # 简介
            plot = self._get_plot(html)
            
            # 标签
            genres = self._get_genres(html)
            
            # 发行日期
            release_date = self._get_release_date(html)
            
            # 时长
            duration = self._get_duration(html)
            
            # 演员
            actors = self._get_actors(html)
            
            # 评分（从JSON-LD提取）
            rating = self._get_rating(html)
            
            # 预告片（通过API获取）
            trailer_url = await self._get_trailer(client, number_id)
            
            # 卖家作为厂商 - 参考 mdcx fc2.py
            studio = self._get_studio(html)
            
            # 有码/无码判断 - 参考 mdcx fc2.py getMosaic
            is_uncensored = self._get_is_uncensored(html, genres, title)
            is_mosaic = not is_uncensored if is_uncensored is not None else None
            
            # 过滤标签中的"無修正"
            genres = [g for g in genres if g != "無修正"]
            
            # 小图
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
            )
        
        except Exception:
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
    
    async def _get_trailer(self, client: AsyncHttpClient, number_id: str) -> Optional[str]:
        """通过API获取预告片"""
        try:
            api_url = f"{self.base_url}/api/v2/videos/{number_id}/sample"
            response_text = await client.get_text(api_url)

            data = json.loads(response_text)
            path = data.get("path")
            if path:
                if path.startswith("http"):
                    return path
                elif path.startswith("/"):
                    return self.base_url + path
                return self.base_url + "/" + path
            return None

        except Exception:
            return None

    def _get_studio(self, html: etree._Element) -> Optional[str]:
        """获取卖家作为厂商 - 参考 mdcx fc2.py getStudio"""
        result = html.xpath('//div[@class="items_article_headerInfo"]/ul/li[last()]/a/text()')
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