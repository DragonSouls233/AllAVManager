"""
JavBus 爬虫
"""

import re
import logging
from datetime import date
from typing import Optional
from urllib.parse import urljoin

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

logger = logging.getLogger(__name__)


@register_crawler
class JavBusCrawler(BaseCrawler):
    """JavBus 爬虫"""
    
    name = "javbus"
    display_name = "JavBus"
    base_url = "https://www.javbus.com"
    
    priority = CrawlerPriority.HIGHEST
    supported_types = ["jav", "jav_uncensored"]
    supported_prefixes = []  # 支持所有标准JAV番号
    description = "JAV数据库站点，覆盖最全"
    language = "zh"
    requires_proxy = False
    
    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """
        刮削指定番号

        Args:
            code: 番号
            ctx: 单次刮削共享上下文（可选，复用 HTTP session / cookies）

        Returns:
            ScrapeResult 刮削结果
        """
        # 优先使用共享上下文的 client（复用 TLS + 指纹 + 速率限制）
        # 否则自建 AsyncHttpClient（向后兼容）
        if ctx and ctx.http_client is not None:
            return await self._scrape_with_client(code, ctx.http_client, ctx)

        async with AsyncHttpClient() as client:
            return await self._scrape_with_client(code, client, ctx)

    async def _scrape_with_client(
        self,
        code: str,
        client: AsyncHttpClient,
        ctx=None,
    ) -> Optional[ScrapeResult]:
        """实际刮削逻辑（接受共享 client）"""
        # 构建详情页URL
        detail_url = f"{self.base_url}/{code}"

        # 优先从 ctx 获取 cookies（运行时 CookieCloud 同步的）
        # 否则回退到配置文件读取
        headers = None
        if ctx:
            headers = ctx.get_headers("javbus.com")
        if not headers or not headers.get("cookie"):
            from app.utils.cookie_manager import get_cookie_headers
            headers = get_cookie_headers("javbus")

        try:
            html_text = await client.get_text(detail_url, headers=headers)

            # 检查是否遇到driver验证或Cloudflare拦截
            if "driver-verify" in html_text.lower() or "cloudflare" in html_text.lower():
                logger.debug(f"JavBus {code}: 遇到验证拦截，跳过")
                self.mark_error()
                return None

            html = etree.fromstring(html_text, etree.HTMLParser())

            # 检查是否找到页面
            if self._is_not_found(html):
                return None

            # 解析数据
            result = self._parse_detail_page(html, code)

            if result:
                self.mark_success()
            else:
                self.mark_error()

            return result

        except Exception as e:
            self.mark_error()
            logger.debug(f"JavBus {code} 刮削失败: {e}")
            return None
    
    async def search(self, keyword: str) -> list[ScrapeResult]:
        """
        搜索番号

        Args:
            keyword: 搜索关键词

        Returns:
            搜索结果列表
        """
        # JavBus 搜索功能暂不实现
        return []


    def _is_not_found(self, html: etree._Element) -> bool:
        """检查是否为404页面"""
        title = html.xpath("//title/text()")
        if title and "404" in title[0]:
            return True
        
        # 检查是否有错误提示
        error_msg = html.xpath("//div[@class='error']")
        return len(error_msg) > 0
    
    def _parse_detail_page(self, html: etree._Element, code: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title = self._get_title(html)
            if not title:
                return None
            
            # 封面
            cover_url = self._get_cover(html)
            
            # 海报（小图）
            poster_url = self._get_poster(cover_url) if cover_url else None

            # javbus 返回相对路径（/pics/cover/*），补全为绝对 URL 才能下载
            if cover_url and cover_url.startswith("/"):
                cover_url = self.base_url.rstrip("/") + cover_url
            if poster_url and poster_url.startswith("/"):
                poster_url = self.base_url.rstrip("/") + poster_url
            
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
            
            # 导演
            director = self._get_director(html)
            
            # 标签
            genres = self._get_genres(html)
            
            # 演员
            actors = self._get_actors(html)
            
            # 所有演员名（含男演员）
            all_actor_names = [a.name for a in actors]
            
            # 有码/无码判断
            is_uncensored = self._get_is_uncensored(html)
            is_mosaic = not is_uncensored if is_uncensored is not None else None
            
            # 简介（JavBus通常没有简介）
            plot = None
            
            # 评分（JavBus没有评分）
            rating = None
            
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
                all_actors=all_actor_names,
                directors=[director] if director else [],
                cover_url=cover_url,
                poster_url=poster_url,
                sample_images=sample_images,
                extrafanart=sample_images,
                rating=rating,
                is_uncensored=is_uncensored,
                is_mosaic=is_mosaic,
                raw_data={
                    "director": director,
                },
            )
        
        except Exception:
            return None
    
    def _get_title(self, html: etree._Element) -> str:
        """获取标题"""
        result = html.xpath("//h3/text()")
        return result[0].strip() if result else ""
    
    def _get_cover(self, html: etree._Element) -> Optional[str]:
        """获取封面URL"""
        result = html.xpath('//a[@class="bigImage"]/@href')
        return result[0] if result else None
    
    def _get_poster(self, cover_url: str) -> Optional[str]:
        """获取海报URL（小图）"""
        if "/pics/cover/" in cover_url:
            return cover_url.replace("/cover/", "/thumb/").replace("_b.jpg", ".jpg")
        if "/imgs/cover/" in cover_url:
            return cover_url.replace("/cover/", "/thumbs/").replace("_b.jpg", ".jpg")
        return None
    
    def _get_release_date(self, html: etree._Element) -> Optional[date]:
        """获取发行日期"""
        result = html.xpath('//span[@class="header"][contains(text(), "發行日期:")]/../text()')
        if not result:
            return None
        
        date_str = result[0].strip()
        date_str = date_str.replace("/", "-").replace(".", "-")
        
        # 解析日期
        if match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str):
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
        
        return None
    
    def _get_duration(self, html: etree._Element) -> Optional[int]:
        """获取时长（分钟）"""
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
    
    def _get_director(self, html: etree._Element) -> Optional[str]:
        """获取导演"""
        result = html.xpath('//a[contains(@href, "/director/")]/text()')
        return result[0].strip() if result else None
    
    def _get_genres(self, html: etree._Element) -> list[str]:
        """获取标签"""
        results = html.xpath('//span[@class="genre"]/label/a[contains(@href, "/genre/")]/text()')
        return [r.strip() for r in results if r.strip()]
    
    def _get_actors(self, html: etree._Element) -> list[ActorInfo]:
        """获取演员列表（含头像URL）"""
        actors = []

        # 演员名和头像来自同一个 img 元素，确保一一对应
        names = html.xpath('//div[@class="star-name"]/../a/img/@title')
        photos = html.xpath('//div[@class="star-name"]/../a/img/@src')

        if len(names) == len(photos):
            for i, name in enumerate(names):
                name = name.strip()
                if not name:
                    continue
                photo = photos[i]
                if "http" not in photo:
                    photo = self.base_url + photo
                actors.append(ActorInfo(name=name, avatar_url=photo))
        else:
            # 数量不匹配时回退到只取名字
            names = html.xpath('//div[@class="star-name"]/a/text()')
            for name in names:
                name = name.strip()
                if not name:
                    continue
                actors.append(ActorInfo(name=name))

        return actors
    
    def _get_sample_images(self, html: etree._Element) -> list[str]:
        """获取样图列表，补全为完整 URL"""
        results = html.xpath('//div[@id="sample-waterfall"]/a[@class="sample-box"]/@href')
        base = self.base_url.rstrip("/")
        full_urls = []
        for r in results:
            if not r:
                continue
            if r.startswith("//"):
                full_urls.append(f"https:{r}")
            elif r.startswith("/"):
                full_urls.append(f"{base}{r}")
            elif r.startswith("http"):
                full_urls.append(r)
            else:
                full_urls.append(f"{base}/{r}")
        return full_urls

    def _get_is_uncensored(self, html: etree._Element) -> Optional[bool]:
        """判断是否有码/无码 - 参考 mdcx getMosaic"""
        # 检查导航栏 active 标签是否包含无码标识
        active_tab = html.xpath('//li[@class="active"]/a/text()')
        if active_tab:
            tab_text = str(active_tab)
            if "有碼" in tab_text or "有码" in tab_text:
                return False
            if "無碼" in tab_text or "无码" in tab_text or "uncensored" in tab_text.lower():
                return True

        # 检查导航栏 active 标签的 href
        active_href = html.xpath('//li[@class="active"]/a/@href')
        if active_href:
            href_text = str(active_href)
            if "/uncensored" in href_text:
                return True

        return None
