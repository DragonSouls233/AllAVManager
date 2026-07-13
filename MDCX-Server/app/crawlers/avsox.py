"""
AvSox 爬虫
"""

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
class AvSoxCrawler(BaseCrawler):
    """AvSox 爬虫"""
    
    name = "avsox"
    display_name = "AvSox"
    base_url = "https://avsox.click"  # 域名可能变化
    
    priority = CrawlerPriority.NORMAL
    supported_types = ["jav", "jav_uncensored"]
    supported_prefixes = []
    description = "JAV数据库站点"
    language = "zh"
    requires_proxy = True
    
    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """
        刮削指定番号
        
        Args:
            code: 番号
            
        Returns:
            ScrapeResult 刮削结果
        """
        async with AsyncHttpClient() as client:
            try:
                # 先搜索获取详情页URL
                detail_url = await self._search_and_get_detail_url(client, code)
                
                if not detail_url:
                    return None
                
                # 获取详情页
                html_text = await client.get_text(detail_url)
                html = etree.fromstring(html_text, etree.HTMLParser())
                
                # 解析数据
                result = self._parse_detail_page(html, code)
                
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
        async with AsyncHttpClient() as client:
            search_url = f"{self.base_url}/cn/search/{keyword}"
            
            try:
                html_text = await client.get_text(search_url)
                html = etree.fromstring(html_text, etree.HTMLParser())
                
                # 解析搜索结果
                results = []
                items = html.xpath("//div[@class='item']")
                
                for item in items:
                    href = item.xpath("a/@href")
                    title = item.xpath("a/@title")
                    
                    if href and title:
                        results.append(ScrapeResult(
                            code="",  # 需要从详情页提取
                            title=title[0].strip(),
                            source=self.name,
                            confidence=0.8,
                        ))
                
                return results
            
            except Exception:
                return []
    
    async def _search_and_get_detail_url(self, client: AsyncHttpClient, code: str) -> Optional[str]:
        """搜索并获取详情页URL"""
        search_url = f"{self.base_url}/cn/search/{code}"
        
        html_text = await client.get_text(search_url)
        html = etree.fromstring(html_text, etree.HTMLParser())
        
        # 获取搜索结果
        items = html.xpath("//div[@class='item']")
        
        # 精确匹配
        for item in items:
            href = item.xpath("a/@href")
            title = item.xpath("a/@title")
            
            if href and title and code.upper() in title[0].upper():
                return href[0]
        
        # 如果没有精确匹配，取第一个结果
        if items:
            href = items[0].xpath("a/@href")
            if href:
                return href[0]
        
        return None
    
    def _parse_detail_page(self, html: etree._Element, code: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title = self._get_title(html)
            if not title:
                return None
            
            # 封面
            cover_url = self._get_cover(html)
            
            # 发行日期
            release_date = self._get_release_date(html)
            
            # 时长
            duration = self._get_duration(html)
            
            # 制作商
            studio = self._get_studio(html)
            
            # 发行商
            maker = self._get_maker(html)
            
            # 系列
            series = self._get_series(html)
            
            # 标签
            genres = self._get_genres(html)
            
            # 演员
            actors = self._get_actors(html)
            
            # 简介
            plot = None
            
            # 样图
            sample_images = self._get_sample_images(html)
            
            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio=studio,
                maker=maker,
                series=series,
                release_date=release_date,
                duration=duration,
                plot=plot,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                sample_images=sample_images,
            )
        
        except Exception:
            return None
    
    def _get_title(self, html: etree._Element) -> str:
        """获取标题"""
        result = html.xpath('//div[@class="container"]/h3/text()')
        return result[0].strip() if result else ""
    
    def _get_cover(self, html: etree._Element) -> Optional[str]:
        """获取封面URL"""
        result = html.xpath('//a[@class="bigImage"]/@href')
        return result[0] if result else None
    
    def _get_release_date(self, html: etree._Element) -> Optional[date]:
        """获取发行日期"""
        result = html.xpath('//span[@class="header"][contains(text(), "發行日期:")]/../text()')
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
        result = html.xpath('//span[@class="header"][contains(text(), "長度:")]/../text()')
        if not result:
            return None
        
        duration_str = result[0].strip()
        if match := re.search(r"(\d+)", duration_str):
            return int(match.group(1))
        
        return None
    
    def _get_studio(self, html: etree._Element) -> Optional[str]:
        """获取制作商"""
        result = html.xpath('//a[contains(@href, "/studio/")]/text()')
        return result[0].strip() if result else None
    
    def _get_maker(self, html: etree._Element) -> Optional[str]:
        """获取发行商"""
        result = html.xpath('//a[contains(@href, "/label/")]/text()')
        return result[0].strip() if result else None
    
    def _get_series(self, html: etree._Element) -> Optional[str]:
        """获取系列"""
        result = html.xpath('//a[contains(@href, "/series/")]/text()')
        return result[0].strip() if result else None
    
    def _get_genres(self, html: etree._Element) -> list[str]:
        """获取标签"""
        results = html.xpath('//span[@class="genre"]/a/text()')
        return [r.strip() for r in results if r.strip()]
    
    def _get_actors(self, html: etree._Element) -> list[ActorInfo]:
        """获取演员列表"""
        actors = []
        
        names = html.xpath('//div[@id="avatar-waterfall"]/a/span/text()')
        
        for name in names:
            name = name.strip()
            if name:
                actors.append(ActorInfo(name=name))
        
        return actors
    
    def _get_sample_images(self, html: etree._Element) -> list[str]:
        """获取样图列表"""
        results = html.xpath('//div[@id="sample-waterfall"]/a[@class="sample-box"]/@href')
        return [r for r in results if r]