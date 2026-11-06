"""
FC2DB 爬虫（fc2db.net）—— FC2 PPV 影片元数据补充源

🔴 2026-11-06 新增，落地前的实测证据（本机直连，非仅首页 200）：
  GET /work/4573362/    -> 200 / 63KB，h1 = "[FC2-PPV-4573362] <日文标题>"
  GET /work/4974437/    -> 200，交叉验证通过
  GET /work/9999999999/ -> 404（确定性「源不收录」，不熔断）
  字段实测可取：og:image 封面、/work-tags/ 标签、出演女優 演员、
                dl.grid 的 販売日 / 収録時間 / モザイク / 商品ID / 作品販売者。
  ⇒ 番号 → 详情 URL 可直接拼接，无需搜索，不会拖慢源序。

字段位置参考了 ref37-metatube-sdk-go/provider/fc2db/fc2db.go 的页面结构说明；
本文件为独立 Python 实现，未复制任何源码（许可隔离）。

⚠️ 熔断约定：4xx 确定性「源不收录」必须抛 ``ResourceUnavailable`` 并原样放行，
   否则 engine 会把死片记成源失败并触发熔断，导致同模块其它影片一起被短路。

🔴 2026-11-06 真机排障：本源**不能**用 ``AsyncHttpClient``。
   实测同一出口（CF-Ray LAX）下：
     httpx / requests                 -> 200 / 63KB 全文，正常解析
     AsyncHttpClient（curl_cffi 指纹）-> 200 / 3820B 「年齢確認」Cloudflare
                                        Turnstile 页，响应头 x-agegate-pass: 0
   换 UA / Accept-Language / Referer / Cookie 均无效 ⇒ 是 TLS 指纹层面触发的
   年龄门，不是出口 IP 或请求头问题。故本爬虫改用 ``httpx.AsyncClient``，
   并显式走 ``get_effective_proxy_url()`` 保持与服务器内置代理一致。
"""
import logging
import re
from datetime import date
from typing import Optional

import httpx
from parsel import Selector

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.scraper.errors import ResourceUnavailable
from app.services.proxy_manager import get_effective_proxy_url

logger = logging.getLogger(__name__)

#: h1 形如 ``[FC2-PPV-4573362] タイトル...``
_H1_CODE_RE = re.compile(r"\[FC2-PPV-(\d+)\]\s*(.+)", re.S)
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


@register_crawler
class FC2DBCrawler(BaseCrawler):
    """FC2DB：按番号直查 FC2 PPV 元数据。"""

    name = "fc2db"
    display_name = "FC2DB"
    base_url = "https://fc2db.net"

    # 作为补充源排在现有 FC2 源之后，不抢主力
    priority = CrawlerPriority.LOW
    supported_types = ["fc2"]
    supported_prefixes = ["FC2"]
    description = "FC2DB（FC2 PPV 元数据：标题 / 封面 / 标签 / 演员 / 发售日 / 卖家）"
    language = "ja"
    requires_proxy = False

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """按番号直查；不使用 ctx.http_client（原因见文件头实测说明）。"""
        number_id = self._extract_number_id(code)
        if not number_id:
            # 不是 FC2 番号：不发请求，也不当失败（与 provider 的 prefix 路由配合）
            return None

        url = f"{self.base_url}/work/{number_id}/"
        try:
            proxy = get_effective_proxy_url(site=self.name, url=self.base_url)
            kwargs = {"proxy": proxy} if proxy else {}
            async with httpx.AsyncClient(
                timeout=20, verify=False, follow_redirects=True, **kwargs
            ) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": _BROWSER_UA,
                        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    },
                )

            # 🔴 确定性「源不收录」：必须与「源坏了」分开，不能返回 None
            if resp.status_code in (404, 410):
                raise ResourceUnavailable(
                    f"HTTP {resp.status_code}",
                    kind="gone" if resp.status_code == 410 else "not_found",
                )
            if resp.status_code >= 400:
                logger.warning("FC2DB HTTP %s [%s]", resp.status_code, number_id)
                self.mark_error()
                return None
            if "年齢確認" in resp.text:
                logger.warning(
                    "FC2DB 命中 Cloudflare 年龄验证页 [%s] x-agegate-pass=%s",
                    number_id, resp.headers.get("x-agegate-pass"),
                )
                self.mark_error()
                return None

            result = self._parse_detail(resp.text, code, number_id, url)
            if result:
                self.mark_success()
            else:
                self.mark_error()
            return result

        except ResourceUnavailable:
            # 🔴 必须放行为第一个 except：死片信号原样交给 engine 区分处理
            raise
        except Exception as e:
            logger.warning(
                "FC2DB 请求失败 [%s]: %s: %s", number_id, type(e).__name__, e
            )
            self.mark_error()
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """不实现搜索。

        站内搜索页返回的是「最新/相关条目」而非精确命中（实测
        ``/search/?q=4573362`` 的 h1 是另一部片），而 ``/work/<id>/``
        可直接由番号拼出，精确且省一次请求。
        """
        return []

    @staticmethod
    def _extract_number_id(code: str) -> Optional[str]:
        """FC2-4573362 / FC2-PPV-4573362 / 4573362 -> ``4573362``。"""
        s = (code or "").upper().strip()
        for prefix in ("FC2-PPV-", "FC2PPV-", "FC2-", "FC2"):
            s = s.replace(prefix, "")
        s = re.sub(r"\D", "", s)
        return s if 5 <= len(s) <= 12 else None

    def _parse_detail(
        self, html_text: str, code: str, number_id: str, url: str
    ) -> Optional[ScrapeResult]:
        """解析详情页；解析不出结构时不猜、返回 None。"""
        x = Selector(html_text)
        h1 = " ".join((x.xpath("string(//h1)").get() or "").split())
        m = _H1_CODE_RE.search(h1)
        if not m:
            # 200 但没有带番号的 h1：页面结构变动或软 404，不构造空壳结果
            return None
        if m.group(1) != number_id:
            # 页面番号与请求不符，宁可不返回，避免张冠李戴
            logger.info("FC2DB 番号不符: 请求 %s / 页面 %s", number_id, m.group(1))
            return None
        title = m.group(2).strip()
        if not title:
            return None

        cover = x.xpath('//meta[@property="og:image"]/@content').get()
        cover = cover.strip() if cover else None

        genres = [
            t.strip()
            for t in x.xpath("//a[contains(@href,'/work-tags/')]//text()").getall()
            if t.strip()
        ]
        # 去重保序（页面里同一标签可能在正文与侧栏各出现一次）
        genres = list(dict.fromkeys(genres))

        # 演员名过闸门：源站的「出演女優」偶尔混入外貌描述而非姓名
        try:
            from app.scraper.module_actor_sync import is_plausible_actor_name
        except ImportError:  # pragma: no cover - 闸门模块缺失时退化为不过滤
            is_plausible_actor_name = lambda _n: True  # noqa: E731
        actors: list[ActorInfo] = []
        seen: set[str] = set()
        for raw in x.xpath(
            "//span[contains(text(),'出演女優')]/following-sibling::a//text()"
        ).getall():
            name = (raw or "").strip()
            if not name or name in seen or not is_plausible_actor_name(name):
                continue
            seen.add(name)
            actors.append(ActorInfo(name=name))

        # dl.grid：販売日 / 収録時間 / モザイク / 商品ID / 作品販売者
        meta: dict[str, str] = {}
        for dl in x.xpath("//dl[contains(@class,'grid')]"):
            for dt in dl.xpath(".//dt"):
                label = " ".join((dt.xpath("string(.)").get() or "").split())
                dds = dt.xpath("following-sibling::dd[1]")
                if label and dds:
                    meta[label] = " ".join((dds[0].xpath("string(.)").get() or "").split())

        def _value(prefix: str) -> Optional[str]:
            return next((v for k, v in meta.items() if k.startswith(prefix)), None)

        release: Optional[date] = None
        raw_date = _value("販売日")
        if raw_date:
            try:
                release = date.fromisoformat(raw_date[:10])
            except ValueError:
                pass

        maker = _value("作品販売者")
        if maker and maker in ("-", "－"):
            maker = None

        mosaic = _value("モザイク")
        is_uncensored = (mosaic == "なし") if mosaic else None

        # 🔴 不填 duration：参考库 fc2db.go 明确注释「时长由播放端 ffprobe
        #   实际文件得出，元数据里不再填」；本项目的时长同理以本地文件为准。
        return ScrapeResult(
            code=code,
            title=title,
            original_title=title,
            source=self.name,
            source_url=url,
            cover_url=cover,
            genres=genres,
            actors=actors,
            all_actors=[a.name for a in actors],
            maker=maker,
            studio=maker,
            release_date=release,
            is_uncensored=is_uncensored,
            is_mosaic=(not is_uncensored) if is_uncensored is not None else None,
            raw_data={"fc2db_id": number_id, "meta": meta},
        )
