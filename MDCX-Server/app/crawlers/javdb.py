"""
JavDB 爬虫
"""

import re
import logging
from datetime import date
from typing import Optional
from urllib.parse import urljoin

from parsel import Selector

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
class JavDBCrawler(BaseCrawler):
    """JavDB 爬虫"""
    
    name = "javdb"
    display_name = "JavDB"
    base_url = "https://javdb.com"
    
    priority = CrawlerPriority.VERY_HIGH
    supported_types = ["jav", "jav_uncensored", "fc2"]
    supported_prefixes = []
    description = "JAV数据库站点，支持多语言"
    language = "zh"
    requires_proxy = True  # 通常需要代理
    
    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """
        刮削指定番号

        Args:
            code: 番号
            ctx: 单次刮削共享上下文（可选，复用 HTTP session / cookies）

        Returns:
            ScrapeResult 刮削结果
        """
        # 只走 JavDB App API 匿名通道（免登录、不绑定 IP、绕 CF）。
        # 不再降级 HTML+cookie 链：javdb.com 直连被 Cloudflare 403 拦截，
        # cookie 链实测全部 403 + 3 次重试 + httpx 降级，只会空转浪费时间。
        return await self._scrape_via_app_api(code, zone=self._infer_zone(code))

    async def scrape_url(self, url: str, code: str, ctx=None) -> Optional[ScrapeResult]:
        """直接抓取指定 JavDB 详情页 URL 刮削（不搜索，避免同番号匹配到错误条目）

        Args:
            url: JavDB 详情页完整链接（如 https://javdb.com/v/xxxx）
            code: 番号（详情页解析结果以调用方传入为准，用于写库）
            ctx: 单次刮削共享上下文（可选）

        Returns:
            ScrapeResult 刮削结果
        """
        detail_text = await self._fetch_with_cloudscraper(url, ctx=ctx)
        if not detail_text:
            return None

        if self._is_cf_blocked(detail_text) or "driver-verify" in detail_text.lower():
            logger.debug(f"JavDB 详情页 {url}: 验证拦截，刮削失败")
            return None

        html = Selector(detail_text)
        result = self._parse_detail_page(html, code, url)
        if result:
            self.mark_success()
        else:
            self.mark_error()
        return result

    async def _scrape_via_app_api(self, code: str, zone: Optional[str] = None) -> Optional[ScrapeResult]:
        """通过 JavDB 匿名 App JSON API 刮削（免登录、绕过 Cloudflare）。

        zone 可选：按分区过滤搜索结果（censored/uncensored/western/fc2），
        缩小范围提高精确命中率；无法确定时传 None 全分区搜索。
        返回元数据 + 磁力列表（javdb.py 原本不抓磁力，这里一并补上）。
        """
        try:
            from app.services.javdb_app_client import JavDBAppClient
            client = JavDBAppClient()
            try:
                mv = await client.search_movie(code, zone=zone)
                if not mv:
                    logger.debug(f"JavDB App API {code}: 未找到")
                    self.mark_error()
                    return None
                # 反向校验：App API 返回的 number 若与目标番号强不等价，判定为抓错片，拒绝入库防串号。
                if mv.number:
                    from app.utils.code_verify import reverse_code_check
                    is_match, norm_e, norm_g = reverse_code_check(code, mv.number)
                    if not is_match:
                        logger.warning(
                            f"JavDB App API 番号反向校验失败，拒绝入库: 期望={norm_e} 实际={norm_g} title={mv.title[:30]!r}"
                        )
                        self.mark_error()
                        return None
                # 取磁力（App API 特有，HTML 链路拿不到）
                magnets = await client.get_magnets(mv.id)
                # v4 详情补全：搜索接口字段极少（无 studio/series/actors/tags/plot），
                # 2026-08-18 新增调 /api/v4/movies/{id} 补全，解决"NFO 系列只有小部分有"。
                fields = await client.build_scrape_fields(mv, magnets)
                fields["code"] = fields.get("code") or code
                fields["title"] = fields.get("title") or code
                fields["release_date"] = self._parse_date(fields.get("release_date") or "")
                fields["confidence"] = 0.9
                result = ScrapeResult(source=self.name, **fields)
                self.mark_success()
                return result
            finally:
                await client.close()
        except Exception as e:
            logger.debug(f"JavDB App API 兜底失败 {code}: {e}")
            self.mark_error()
            return None

    @staticmethod
    def _infer_zone(code: str) -> Optional[str]:
        """按番号格式推断 JavDB 分区；无法确定返回 None（全分区搜索 + 精确匹配 + 反向校验防串号）。"""
        c = (code or "").upper().replace(" ", "")
        if c.startswith("FC2"):
            return "fc2"
        return None

    @staticmethod
    def _parse_date(s: str) -> Optional[date]:
        """解析 JavDB App API 的 release_date（'2021-05-09' 或 '05/09/2021'）。"""
        from datetime import datetime
        if not s:
            return None
        s = s.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    async def _fetch_with_cloudscraper(self, url: str, ctx=None) -> Optional[str]:
        """访问 JavDB 抓取 HTML（异步主路径 + 快速 CF 放弃 + 重兜底限时下线程）

        Args:
            url: 目标 URL
            ctx: 单次刮削共享上下文（可选，复用 HTTP session / cookies）
        """
        import asyncio

        cookie_headers = None
        if ctx:
            cookie_str = ctx.get_cookies("javdb.com")
            if cookie_str:
                cookie_headers = {"cookie": cookie_str, "User-Agent": "Mozilla/5.0"}
        if not cookie_headers:
            from app.utils.cookie_manager import get_cookie_headers
            cookie_headers = get_cookie_headers("javdb")

        # 1) 主路径：异步 AsyncHttpClient（curl_cffi 指纹 + 代理），最快
        html = await self._fetch_async(url, ctx, cookie_headers)
        if html and not self._is_cf_blocked(html):
            return html
        # Cloudflare 挑战页：本环境 cloudscraper/Chrome/stealth 均无法稳定解开 javdb 的盾，
        # 且会空转 30~100s。确认 CF 后直接放弃，避免级联耗时与误启 Chrome 进程。
        if html and self._is_cf_blocked(html):
            logger.debug(f"JavDB 命中 Cloudflare 挑战页，提前放弃: {url}")
            return None

        # 2) 主路径硬失败（非 CF 阻挡，例如连接错误/403）→ 级联兜底
        # 2a) stealth_fetch（真正的 CF 解法，线程池执行，限时 35s）
        try:
            from app.utils.stealth_fetcher import stealth_fetch, is_available
            if is_available():
                sf = await asyncio.wait_for(stealth_fetch(url), timeout=35)
                if sf and "JavDB" in sf.get("html", ""):
                    return sf["html"]
        except Exception as e:
            logger.debug(f"JavDB stealth_fetch 失败 {url}: {e}")

        # 2b) cloudscraper 兜底（同步 requests 客户端）—— 放入线程池并加超时，避免阻塞事件循环
        try:
            import cloudscraper
        except ImportError:
            cloudscraper = None

        if cloudscraper is not None:
            try:
                if not hasattr(self, "_cloudscraper"):
                    self._cloudscraper = cloudscraper.create_scraper()
                    try:
                        from app.services.proxy_manager import get_effective_proxy_url
                        proxy_url = get_effective_proxy_url()
                        if proxy_url:
                            self._cloudscraper.proxies = {"http": proxy_url, "https": proxy_url}
                            logger.debug(f"JavDB cloudscraper 代理: {proxy_url}")
                    except Exception:
                        pass

                # 带上 over18=1 年龄 cookie（get_cookie_headers 对 javdb 始终返回），
                # 避免 cloudscraper 回退时撞年龄墙。
                _cookie_str = ""
                if cookie_headers and cookie_headers.get("cookie"):
                    _cookie_str = cookie_headers["cookie"]
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._cloudscraper.get, url, timeout=20,
                        cookies=_cookie_str or None,
                    ),
                    timeout=25,
                )
                if response.status_code == 200:
                    if self._is_cf_blocked(response.text):
                        logger.debug(f"JavDB cloudscraper 命中 CF，放弃(不启 chrome): {url}")
                        return None
                    return response.text
                logger.debug(f"JavDB {url} HTTP {response.status_code}")
            except Exception as e:
                logger.debug(f"JavDB cloudscraper 请求失败 {url}: {e}")

        # 2c) undetected-chromedriver 兜底（重，必须放入线程池并加超时，避免卡死事件循环）
        try:
            h = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_with_undetected_chrome, url),
                timeout=60,
            )
            if h:
                return h
        except Exception as e:
            logger.debug(f"JavDB undetected-chromedriver 兜底失败 {url}: {e}")
        return None

    async def _fetch_async(self, url: str, ctx, headers) -> Optional[str]:
        """异步主路径：通过 AsyncHttpClient（curl_cffi，自动代理+指纹）获取 HTML，异常返回 None"""
        try:
            if ctx and ctx.http_client is not None:
                return await ctx.http_client.get_text(url, headers=headers)
            async with AsyncHttpClient() as client:
                return await client.get_text(url, headers=headers)
        except Exception as e:
            logger.debug(f"JavDB AsyncHttpClient 请求失败 {url}: {e}")
            return None

    def _fetch_with_undetected_chrome(self, url: str) -> Optional[str]:
        """v3.1: 使用 undetected-chromedriver 作为最终兜底（同步方法，由调用方 asyncio.to_thread 调度）

        undetected-chromedriver 启动真实 Chrome 浏览器，能绕过最严格的 Cloudflare 检测，
        但资源占用高（每次启动一个 Chrome 进程），仅在 cloudscraper 失败时使用。
        本方法为同步实现（内部全为阻塞调用），必须由 to_thread 在独立线程执行，
        否则会阻塞整个事件循环。
        """
        try:
            import undetected_chromedriver as uc
        except ImportError:
            logger.debug("undetected-chromedriver 未安装，跳过降级方案")
            return None

        driver = None
        try:
            from app.config.manager import get_config
            options = uc.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--lang=zh-CN")

            # 代理配置
            try:
                from app.services.proxy_manager import get_effective_proxy_url
                proxy_url = get_effective_proxy_url()
                if proxy_url:
                    options.add_argument(f"--proxy-server={proxy_url}")
                    logger.debug(f"JavDB undetected-chromedriver 代理: {proxy_url}")
            except Exception:
                pass

            driver = uc.Chrome(options=options, version_main=None)
            driver.set_page_load_timeout(30)

            # 注入 Cookie（如果配置了）
            from app.utils.cookie_manager import get_cookie_headers
            cookie_headers = get_cookie_headers("javdb")
            if cookie_headers and "cookie" in cookie_headers:
                # 先访问域名以设置 Cookie
                driver.get("https://javdb.com")
                import time
                time.sleep(2)
                for cookie_pair in cookie_headers["cookie"].split(";"):
                    if "=" in cookie_pair:
                        name, value = cookie_pair.strip().split("=", 1)
                        try:
                            driver.add_cookie({"name": name, "value": value, "domain": ".javdb.com"})
                        except Exception:
                            pass

            driver.get(url)
            import time
            time.sleep(3)  # 等待 Cloudflare 5 秒盾跳转
            html = driver.page_source
            if html and "JavDB" in html:
                logger.debug(f"JavDB undetected-chromedriver 成功: {url}")
                return html
            logger.debug(f"JavDB undetected-chromedriver 未获取到有效内容: {url}")
            return None
        except Exception as e:
            logger.debug(f"JavDB undetected-chromedriver 失败 {url}: {e}")
            return None
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    @staticmethod
    def _is_cf_blocked(html_text: str) -> bool:
        """判断返回的 HTML 是否为 Cloudflare 挑战/拦截页

        fix23c: 之前 /cdn-cgi/challenge-platform 误判登录页为 CF 挑战页。
        改为只看 CF 挑战页独有的 <title> + 短 body 组合。
        """
        if not html_text:
            return True
        low = html_text.lower()
        # CF 挑战页的 <title> 是固定的 "Just a moment..." / "Attention Required!"
        if "<title>just a moment" in low or "<title>attention required" in low:
            return True
        # CF 拦截页通常很短（< 5KB）+ 含 ray-id
        if "ray-id" in low and len(html_text) < 5000:
            return True
        # JavDB 自有验证页
        if "driver-verify" in low and len(html_text) < 10000:
            return True
        return False

    @staticmethod
    def _is_login_redirect(html_text: str) -> bool:
        """判断是否被重定向到登录页（Cookie 失效）

        fix23c: JavDB Cookie 失效时会 302 重定向到 /login?return_to_url=...
        页面 title 是 "登入 | JavDB" / "Login | JavDB"
        """
        if not html_text:
            return False
        low = html_text.lower()
        # 登录页特征
        if "<title>登入" in low or "<title>login" in low:
            return True
        if "return_to_url" in low and "javdb.com/login" in low:
            return True
        return False

    def _extract_detail_url(self, html_text: str, code: str) -> Optional[str]:
        """从搜索结果 HTML 中提取详情页 URL"""
        html = Selector(html_text)
        # 注意：javdb 搜索卡片 class 实际为 "box ..."（含额外 class），
        # 必须用 contains() 兼容，精确 @class='box' 会匹配不到导致刮削失败。
        items = html.xpath("//a[contains(@class,'box')]")
        if not items:
            return None

        # 精确匹配
        for item in items:
            href = item.xpath("@href").get()
            title = item.xpath("div[@class='video-title']/strong/text()").get()
            if href and title and code.upper() in title.upper():
                return urljoin(self.base_url, href) + "?locale=zh"

        # 取第一个结果
        href = items[0].xpath("@href").get()
        if href:
            return urljoin(self.base_url, href) + "?locale=zh"
        return None
    
    async def search(self, keyword: str) -> list[ScrapeResult]:
        """
        搜索番号
        """
        html_text = await self._fetch_with_cloudscraper(
            f"{self.base_url}/search?q={keyword}&locale=zh"
        )
        if not html_text:
            return []

        html = Selector(html_text)
        items = html.xpath("//a[contains(@class,'box')]")
        results = []

        for item in items:
            href = item.xpath("@href").get()
            title = item.xpath("div[@class='video-title']/strong/text()").get()
            code_text = item.xpath("div[@class='video-title']/span/text()").get()
            if href and title:
                results.append(ScrapeResult(
                    code=code_text or "",
                    title=title.strip(),
                    source=self.name,
                    confidence=0.8,
                ))
        return results
    
    def _parse_detail_page(
        self,
        html: Selector,
        code: str,
        detail_url: str,
    ) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title = self._get_title(html)
            if not title:
                return None
            
            # 原始标题
            original_title = self._get_original_title(html)
            
            # 封面
            cover_url = self._get_cover(html)
            
            # 海报
            poster_url = self._get_poster(html)
            
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
            
            # 所有演员（含男演员）
            all_actors = self._get_all_actors(html)
            
            # 导演
            directors = self._get_directors(html)
            
            # 简介
            plot = None
            
            # 评分
            rating = self._get_rating(html)
            
            # 想看人数
            wanted = self._get_wanted(html)
            
            # 样图
            sample_images = self._get_sample_images(html)
            
            # 预告片
            trailer_url = self._get_trailer(html)
            
            # 有码/无码判断 - 参考 mdcx javdb_new.py post_process
            is_uncensored = any(kw in title for kw in ["無碼", "無修正", "Uncensored"])
            is_mosaic = not is_uncensored
            
            return ScrapeResult(
                code=code,
                title=title,
                original_title=original_title,
                source=self.name,
                studio=studio,
                maker=maker,
                series=series,
                release_date=release_date,
                duration=duration,
                plot=plot,
                genres=genres,
                actors=actors,
                all_actors=all_actors,
                directors=directors,
                cover_url=cover_url,
                poster_url=poster_url,
                trailer_url=trailer_url,
                sample_images=sample_images,
                extrafanart=sample_images,
                rating=rating,
                wanted=wanted,
                is_uncensored=is_uncensored,
                is_mosaic=is_mosaic,
            )
        
        except Exception:
            return None
    
    def _get_title(self, html: Selector) -> str:
        """获取标题"""
        result = html.xpath('string(//h2[@class="title is-4"]/strong[@class="current-title"])').get()
        return result.strip() if result else ""

    def _get_original_title(self, html: Selector) -> Optional[str]:
        """获取原始标题（日文/英文）- 参考 mdcx javdb_new.py originaltitle"""
        result = html.xpath('string(//h2[@class="title is-4"]/span[@class="origin-title"])').get()
        return result.strip() if result else None
    
    def _get_cover(self, html: Selector) -> Optional[str]:
        """获取封面URL"""
        result = html.xpath("//img[@class='video-cover']/@src").get()
        return result if result else None
    
    def _get_poster(self, html: Selector) -> Optional[str]:
        """获取海报URL"""
        # JavDB 通常封面和海报是同一个
        return self._get_cover(html)
    
    def _get_release_date(self, html: Selector) -> Optional[date]:
        """获取发行日期"""
        result = html.xpath('//strong[contains(text(),"日期:")]/../span/text()').get()
        if not result:
            result = html.xpath('//strong[contains(text(),"Released Date:")]/../span/text()').get()
        
        if not result:
            return None
        
        date_str = result.strip()
        date_str = date_str.replace("/", "-").replace(".", "-")
        
        if match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str):
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
        
        return None
    
    def _get_duration(self, html: Selector) -> Optional[int]:
        """获取时长（分钟）"""
        result = html.xpath('//strong[contains(text(),"時長")]/../span/text()').get()
        if not result:
            result = html.xpath('//strong[contains(text(),"Duration:")]/../span/text()').get()
        
        if not result:
            return None
        
        duration_str = result.strip()
        duration_str = duration_str.replace(" 分鍾", "").replace(" minute(s)", "")
        
        if match := re.search(r"(\d+)", duration_str):
            return int(match.group(1))
        
        return None
    
    def _get_studio(self, html: Selector) -> Optional[str]:
        """获取制作商"""
        result = html.xpath('//strong[contains(text(),"片商:")]/../span/a/text()').get()
        if not result:
            result = html.xpath('//strong[contains(text(),"Maker:")]/../span/a/text()').get()
        return result.strip() if result else None
    
    def _get_maker(self, html: Selector) -> Optional[str]:
        """获取发行商"""
        result = html.xpath('//strong[contains(text(),"發行:")]/../span/a/text()').get()
        if not result:
            result = html.xpath('//strong[contains(text(),"Publisher:")]/../span/a/text()').get()
        return result.strip() if result else None
    
    def _get_series(self, html: Selector) -> Optional[str]:
        """获取系列"""
        result = html.xpath('//strong[contains(text(),"系列:")]/../span/a/text()').get()
        if not result:
            result = html.xpath('//strong[contains(text(),"Series:")]/../span/a/text()').get()
        return result.strip() if result else None
    
    def _get_genres(self, html: Selector) -> list[str]:
        """获取标签"""
        results = html.xpath('//strong[contains(text(),"類別:")]/../span/a/text()').getall()
        if not results:
            results = html.xpath('//strong[contains(text(),"Tags:")]/../span/a/text()').getall()
        
        # 清理标签
        genres = []
        for r in results:
            r = r.replace("\xa0", "").replace("'", "").replace(" ", "").strip()
            if r:
                genres.append(r)
        
        return list(dict.fromkeys(genres))  # 去重保持顺序
    
    def _get_actors(self, html: Selector) -> list[ActorInfo]:
        """获取演员列表（女演员）"""
        actors = []
        
        # 女演员
        names = html.xpath("//strong[contains(@class, 'female')]/preceding-sibling::a/text()").getall()
        
        for name in names:
            name = name.strip()
            if name:
                actors.append(ActorInfo(name=name))
        
        return actors

    def _get_all_actors(self, html: Selector) -> list[str]:
        """获取所有演员（含男演员）- 参考 mdcx javdb_new.py all_actors

        注意：不能使用 CSS `:has()` 伪类（lxml/parsel 仅支持 XPath 1.0，
        `:has()` 会抛 ValueError 导致整个详情解析被 except 吞掉、刮削返回 None）。
        女/男演员均通过 ``strong.female/male`` 符号的 preceding-sibling 链接提取，
        覆盖 javdb 全部演员展示形式。
        """
        all_names: list[str] = []
        # 女演员
        female_names = html.xpath("//strong[contains(@class, 'female')]/preceding-sibling::a/text()").getall()
        # 男演员
        male_names = html.xpath("//strong[contains(@class, 'male')]/preceding-sibling::a/text()").getall()
        # 通用演员链接（无性别标记时回退：演員面板下的 a 文本）
        generic_names = html.xpath(
            "//strong[contains(text(),'演員') or contains(text(),'演员')]/../span//a/text()"
        ).getall()

        seen: set[str] = set()
        for name in female_names + male_names + generic_names:
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                all_names.append(name)

        return all_names

    def _get_directors(self, html: Selector) -> list[str]:
        """获取导演列表 - 参考 mdcx javdb_new.py directors"""
        results = html.xpath('//strong[contains(text(),"導演:")]/../span/a/text()').getall()
        if not results:
            results = html.xpath('//strong[contains(text(),"Director:")]/../span/a/text()').getall()
        return [r.strip() for r in results if r.strip()]
    
    def _get_rating(self, html: Selector) -> Optional[float]:
        """获取评分 - 参考 mdcx javdb_new.py score"""
        result = html.xpath("//span[@class='score-stars']/../text()").get()
        if not result:
            result = html.xpath("//span[@class='value']/text()").get()
        if not result:
            return None
        
        rating_str = result.strip()
        if match := re.search(r"(\d+\.?\d*)", rating_str):
            return float(match.group(1))
        
        return None
    
    def _get_sample_images(self, html: Selector) -> list[str]:
        """获取样图列表"""
        results = html.xpath("//div[@class='tile-images preview-images']/a[@class='tile-item']/@href").getall()
        return [r for r in results if r]
    
    def _get_trailer(self, html: Selector) -> Optional[str]:
        """获取预告片URL"""
        result = html.xpath("//video[@id='preview-video']/source/@src").get()
        if result and result.startswith("//"):
            result = "https:" + result
        return result if result else None

    def _get_wanted(self, html: Selector) -> Optional[str]:
        """获取想看人数 - 参考 mdcx javdb_new.py wanted"""
        html_text = html.get()
        if match := re.search(r"(\d+)(人想看| want to watch it)", html_text):
            return match.group(1)
        return None