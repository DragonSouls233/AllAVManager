"""Wikipedia / Wikidata 演员资料刮削器

通过 Wikidata SPARQL 查询和 Wikipedia API 获取演员的权威资料：
- 中文名 / 日文名 / 英文名 / 别名
- 出生日期 / 出生地
- 简介（Wikipedia 摘要）
- 头像（Wikidata P18 图片属性）

数据流：
1. Wikidata SPARQL 查询：按演员名匹配 QID（实体 ID）
2. Wikidata REST API：获取 P18（图片）、P19（出生地）、P569（出生日期）等属性
3. Wikipedia API：获取简介摘要

参考 Hazard804-mdcx 的 Wikipedia 演员资料集成思路。
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from app.config.manager import get_config
from app.utils.logger import get_logger
from app.utils.http_client import get_http_client

from app.scraper.actor_profile_scrapers import BaseActorProfileScraper, ActorProfile

logger = get_logger(__name__)

# Wikidata SPARQL 端点
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
# Wikidata REST API（获取实体详情）
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# Wikipedia API（获取摘要）
WIKIPEDIA_API = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIPEDIA_SEARCH = "https://{lang}.wikipedia.org/w/api.php"

# User-Agent（Wikidata/Wikipedia 要求标识）
USER_AGENT = "MDCX/3.0 (https://github.com/mdcx)"


class WikidataScraper(BaseActorProfileScraper):
    """Wikidata 演员资料刮削器

    通过 Wikidata SPARQL 查询匹配演员实体，再获取详细属性。
    Wikidata 提供结构化的多语言数据，包括：
    - P1477: 出生名
    - P1449: 别名
    - P569: 出生日期
    - P19: 出生地
    - P18: 图片
    - P856: 官方网站
    """

    name = "wikidata"
    display_name = "Wikidata"
    base_url = "https://www.wikidata.org"

    def __init__(self):
        self._http = None

    async def _get_client(self):
        if self._http is None:
            self._http = get_http_client()
        return self._http

    async def search(self, name: str) -> Optional[str]:
        """搜索演员，返回 Wikidata QID（如 Q123456）

        使用 SPARQL 查询：按 label 或 alias 匹配，限定职业为演员（Q10648343）
        """
        client = await self._get_client()

        # SPARQL 查询：搜索 label 或 alias 匹配的演员实体
        # 优先日文标签（AV 女优在日文维基更常见）
        sparql_query = f"""
SELECT ?item ?itemLabel ?itemDescription WHERE {{
  {{
    SELECT ?item WHERE {{
      ?item rdfs:label "{name}"@ja.
      ?item wdt:P106 wd:Q10648343.
    }}
  }} UNION {{
    SELECT ?item WHERE {{
      ?item rdfs:label "{name}"@zh.
      ?item wdt:P106 wd:Q10648343.
    }}
  }} UNION {{
    SELECT ?item WHERE {{
      ?item rdfs:label "{name}"@en.
      ?item wdt:P106 wd:Q10648343.
    }}
  }} UNION {{
    SELECT ?item WHERE {{
      ?item altLabel "{name}".
      ?item wdt:P106 wd:Q10648343.
    }}
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,zh,en". }}
}}
LIMIT 5
""".strip()

        try:
            params = {
                "query": sparql_query,
                "format": "json",
            }
            # SPARQL 查询用 GET，参数在 URL 中
            url = f"{WIKIDATA_SPARQL}?query={quote(sparql_query)}&format=json"
            headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

            data = await client.get_json(url, headers=headers)
            bindings = data.get("results", {}).get("bindings", [])
            if not bindings:
                logger.debug(f"Wikidata 未找到匹配: {name}")
                return None

            # 取第一个结果的 QID
            item_uri = bindings[0].get("item", {}).get("value", "")
            # URI 格式：http://www.wikidata.org/entity/Q123456
            match = re.search(r"Q\d+$", item_uri)
            if match:
                qid = match.group(0)
                logger.info(f"Wikidata 匹配: {name} → {qid}")
                return qid
            return None

        except Exception as e:
            logger.debug(f"Wikidata 搜索失败 {name}: {e}")
            return None

    async def scrape_profile(self, qid: str) -> Optional[ActorProfile]:
        """抓取 Wikidata 实体详情

        通过 wbgetentities API 获取属性，包括：
        - labels（多语言名称）
        - aliases（别名）
        - claims（P569 出生日期、P19 出生地、P18 图片等）
        """
        client = await self._get_client()

        try:
            url = f"{WIKIDATA_API}?action=wbgetentities&ids={qid}&format=json&languages=zh|ja|en&props=labels|aliases|claims|descriptions"
            headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

            data = await client.get_json(url, headers=headers)
            entities = data.get("entities", {})
            entity = entities.get(qid)
            if not entity:
                return None

            # 提取多语言名称
            labels = entity.get("labels", {})
            name_jp = labels.get("ja", {}).get("value")
            name_zh = labels.get("zh", {}).get("value")
            name_en = labels.get("en", {}).get("value")
            name = name_zh or name_jp or name_en or ""

            # 提取别名（多语言）
            aliases = entity.get("aliases", {})
            alias_list = []
            for lang in ("ja", "zh", "en"):
                for alias in aliases.get(lang, []):
                    val = alias.get("value")
                    if val and val not in alias_list and val != name:
                        alias_list.append(val)
            alias_str = ", ".join(alias_list[:5]) if alias_list else None

            # 提取属性（claims）
            claims = entity.get("claims", {})

            # P569: 出生日期
            birth_date = self._extract_date_claim(claims, "P569")

            # P19: 出生地（取地名）
            birthplace = await self._extract_entity_label(claims, "P19", client)

            # P18: 图片
            avatar_url = None
            if "P18" in claims:
                p18 = claims["P18"][0]
                img_filename = p18.get("mainsnak", {}).get("datavalue", {}).get("value")
                if img_filename:
                    # Wikimedia 图片 URL 需要特殊计算（md5 前缀）
                    avatar_url = self._build_commons_url(img_filename)

            # 获取简介（从 Wikipedia）
            intro = None
            if name:
                intro = await self._fetch_wikipedia_summary(name, name_jp, client)

            # 社交账号（v3.4 新增，从 Wikidata claims 提取）
            social_links = self._extract_social_links(claims)

            profile = ActorProfile(
                name=name,
                name_jp=name_jp,
                name_en=name_en,
                alias=alias_str,
                avatar_url=avatar_url,
                birth_date=birth_date,
                birthplace=birthplace,
                intro=intro,
                social_links=social_links,
                source="wikidata",
                source_url=f"https://www.wikidata.org/wiki/{qid}",
            )
            logger.info(f"Wikidata 抓取完成: {name} ({qid})")
            return profile

        except Exception as e:
            logger.error(f"Wikidata 详情抓取失败 {qid}: {e}")
            return None

    def _extract_date_claim(self, claims: dict, prop: str) -> Optional[str]:
        """从 claims 中提取日期值（格式化为 YYYY-MM-DD）"""
        if prop not in claims:
            return None
        try:
            claim = claims[prop][0]
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            time_str = value.get("time", "")
            # Wikidata 时间格式：+2000-01-01T00:00:00Z
            match = re.match(r"\+[+-]?(\d{4}-\d{2}-\d{2})", time_str)
            if match:
                return match.group(1)
            # 仅年份
            match = re.match(r"\+[+-]?(\d{4})", time_str)
            if match:
                return match.group(1)
        except Exception:
            pass
        return None

    async def _extract_entity_label(self, claims: dict, prop: str, client) -> Optional[str]:
        """从 claims 中提取实体引用的标签（如出生地地名）"""
        if prop not in claims:
            return None
        try:
            claim = claims[prop][0]
            qid = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            if not qid:
                return None
            # 查询该实体的标签
            url = f"{WIKIDATA_API}?action=wbgetentities&ids={qid}&format=json&languages=zh|ja|en&props=labels"
            headers = {"User-Agent": USER_AGENT}
            data = await client.get_json(url, headers=headers)
            entity = data.get("entities", {}).get(qid, {})
            labels = entity.get("labels", {})
            return labels.get("zh", {}).get("value") or labels.get("ja", {}).get("value") or labels.get("en", {}).get("value")
        except Exception:
            return None

    def _build_commons_url(self, filename: str) -> str:
        """构造 Wikimedia Commons 图片 URL

        格式：https://commons.wikimedia.org/wiki/Special:FilePath/<filename>
        """
        # 去掉前导 "File:"
        if filename.startswith("File:"):
            filename = filename[5:]
        encoded = quote(filename)
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}"

    def _extract_social_links(self, claims: dict) -> Optional[dict]:
        """从 Wikidata claims 提取社交账号链接（v3.4 新增）

        支持的 Wikidata 属性：
        - P2002: Twitter 用户名
        - P2003: Instagram 用户名
        - P2013: Facebook 用户名
        - P2397: YouTube 频道 ID
        - P4264: LinkedIn 公司名
        - P856: 官方网站
        """
        social = {}
        # 属性 -> (平台名, URL 模板)
        prop_map = {
            "P2002": ("twitter", "https://twitter.com/{}"),
            "P2003": ("instagram", "https://www.instagram.com/{}"),
            "P2013": ("facebook", "https://www.facebook.com/{}"),
            "P2397": ("youtube", "https://www.youtube.com/channel/{}"),
            "P4264": ("linkedin", "https://www.linkedin.com/company/{}"),
        }
        for prop, (platform, url_template) in prop_map.items():
            if prop in claims:
                try:
                    value = claims[prop][0].get("mainsnak", {}).get("datavalue", {}).get("value")
                    if value:
                        social[platform] = url_template.format(value)
                except (IndexError, KeyError, TypeError):
                    pass
        # P856: 官方网站（直接是 URL）
        if "P856" in claims:
            try:
                official = claims["P856"][0].get("mainsnak", {}).get("datavalue", {}).get("value")
                if official:
                    social["official"] = official
            except (IndexError, KeyError, TypeError):
                pass
        return social if social else None

    async def _fetch_wikipedia_summary(
        self, name: str, name_jp: Optional[str], client
    ) -> Optional[str]:
        """从 Wikipedia 获取演员简介摘要

        优先日文维基（AV 女优资料更全），回退中文和英文
        """
        # 按优先级尝试不同语言
        for lang, query_name in [("ja", name_jp), ("zh", name), ("en", name)]:
            if not query_name:
                continue
            try:
                # 先搜索精确匹配的页面标题
                search_url = f"{WIKIPEDIA_SEARCH.format(lang=lang)}?action=query&list=search&srsearch={quote(query_name)}&srlimit=1&format=json"
                headers = {"User-Agent": USER_AGENT}
                search_data = await client.get_json(search_url, headers=headers)
                search_results = search_data.get("query", {}).get("search", [])
                if not search_results:
                    continue
                title = search_results[0].get("title")
                if not title:
                    continue

                # 获取摘要
                summary_url = WIKIPEDIA_API.format(lang=lang, title=quote(title))
                summary_data = await client.get_json(summary_url, headers=headers)
                extract = summary_data.get("extract")
                if extract:
                    # 截断到 500 字符
                    return extract[:500] + ("..." if len(extract) > 500 else "")
            except Exception as e:
                logger.debug(f"Wikipedia {lang} 摘要获取失败 {query_name}: {e}")
                continue
        return None


class WikipediaScraper(BaseActorProfileScraper):
    """Wikipedia 演员资料刮削器

    仅使用 Wikipedia API（不依赖 Wikidata SPARQL），
    适合 Wikidata 查询失败时的轻量级兜底。
    """

    name = "wikipedia"
    display_name = "Wikipedia"
    base_url = "https://wikipedia.org"

    def __init__(self):
        self._http = None

    async def _get_client(self):
        if self._http is None:
            self._http = get_http_client()
        return self._http

    async def search(self, name: str) -> Optional[str]:
        """搜索演员，返回 Wikipedia 页面标题"""
        client = await self._get_client()
        headers = {"User-Agent": USER_AGENT}

        # 优先日文维基
        for lang in ("ja", "zh", "en"):
            try:
                url = f"{WIKIPEDIA_SEARCH.format(lang=lang)}?action=query&list=search&srsearch={quote(name)}&srlimit=1&format=json"
                data = await client.get_json(url, headers=headers)
                results = data.get("query", {}).get("search", [])
                if results:
                    title = results[0].get("title")
                    if title:
                        return f"{lang}:{title}"
            except Exception:
                continue
        return None

    async def scrape_profile(self, search_key: str) -> Optional[ActorProfile]:
        """抓取 Wikipedia 页面摘要"""
        if not search_key or ":" not in search_key:
            return None

        lang, title = search_key.split(":", 1)
        client = await self._get_client()
        headers = {"User-Agent": USER_AGENT}

        try:
            # 获取摘要
            summary_url = WIKIPEDIA_API.format(lang=lang, title=quote(title))
            data = await client.get_json(summary_url, headers=headers)

            extract = data.get("extract")
            if not extract:
                return None

            # 尝试从原始数据提取更多信息
            name = data.get("title") or title
            description = data.get("description") or ""

            # 尝试提取出生日期（从描述或摘要）
            birth_date = self._extract_date_from_text(extract + " " + description)

            # 头像（thumbnail）
            avatar_url = data.get("thumbnail", {}).get("source")

            profile = ActorProfile(
                name=name,
                intro=extract[:500] + ("..." if len(extract) > 500 else ""),
                avatar_url=avatar_url,
                birth_date=birth_date,
                source="wikipedia",
                source_url=data.get("content_urls", {}).get("desktop", {}).get("page"),
            )
            logger.info(f"Wikipedia 抓取完成: {name}")
            return profile

        except Exception as e:
            logger.error(f"Wikipedia 详情抓取失败 {search_key}: {e}")
            return None

    def _extract_date_from_text(self, text: str) -> Optional[str]:
        """从文本中提取日期（简化版）"""
        # 匹配 YYYY年MM月DD日 格式
        match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if match:
            y, m, d = match.groups()
            return f"{y}-{int(m):02d}-{int(d):02d}"
        # 匹配 YYYY-MM-DD 格式
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if match:
            return match.group(0)
        # 仅年份
        match = re.search(r"(\d{4})年", text)
        if match:
            return match.group(1)
        return None


__all__ = ["WikidataScraper", "WikipediaScraper"]
