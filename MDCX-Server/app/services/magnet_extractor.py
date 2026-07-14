"""
通用磁力链接提取器 (MagnetExtractor)

参考来源:
- P1: PornSimilarityPlatform/modules/madouqu/core/crawler.py (4 种磁力提取方式)
- P1: PSP madouqu get_detail() 的 4 种 fallback 模式

整合说明:
- 提取方式: 100% 复用 P1 麻豆的 4 种 fallback (直接查找/文本匹配/class 选择器/正则)
- HTTP: 走 MDCX 内置代理
- 数据模型: 适配 MDCX MagnetInfo dataclass

提取流程（按优先级）:
  1. <a href="magnet:..."> 直接查找
  2. <a> 包含"磁力/magnet/bt/下载"文本
  3. class 选择器 (.magnet-link, .bt-link, .download-link)
  4. 全文本正则匹配 magnet:\\?xt=urn:btih:[a-zA-Z0-9]+

每条 magnet 链接会解析:
  - xt (urn:btih:xxxx) → 磁力哈希
  - dn (display name) → 文件名
  - tr (tracker) → tracker 列表
  - 其他参数 (xl / kt / xs)
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup
from lxml import html as lxml_html

from app.utils.logger import get_logger

logger = get_logger(__name__)


# 磁力链接正则
MAGNET_PATTERN = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^\"\s<>]*", re.IGNORECASE)
BTIH_PATTERN = re.compile(r"urn:btih:([a-zA-Z0-9]+)", re.IGNORECASE)

# 4 种 fallback 选择器
LINK_TEXT_PATTERN = re.compile(r"(磁力|magnet|bt|下载)", re.IGNORECASE)
CLASS_SELECTORS = [
    ".magnet-link",
    ".bt-link",
    ".download-link",
    'a[class*="magnet"]',
    'a[class*="bt"]',
]


@dataclass
class MagnetInfo:
    """磁力链接信息"""
    link: str
    hash: str = ""           # 40 位 btih
    name: str = ""           # dn 参数
    trackers: list[str] = field(default_factory=list)
    file_size: str = ""      # xl 参数（人类可读）
    keywords: list[str] = field(default_factory=list)  # kt
    source_url: str = ""

    def to_dict(self) -> dict:
        return {
            "link": self.link,
            "hash": self.hash,
            "name": self.name,
            "trackers": self.trackers,
            "file_size": self.file_size,
            "keywords": self.keywords,
            "source_url": self.source_url,
        }


class MagnetExtractor:
    """通用磁力链接提取器

    支持从 HTML 文本提取磁力链接，按 4 种方式优先级 fallback。
    去重：相同 btih 只保留首次出现。
    """

    def __init__(self, source_url: str = ""):
        self.source_url = source_url

    @staticmethod
    def parse_magnet(magnet: str) -> MagnetInfo:
        """解析磁力链接参数

        格式示例:
          magnet:?xt=urn:btih:xxxx&dn=文件名&tr=tracker1&tr=tracker2&xl=size&kt=keyword1
        """
        info = MagnetInfo(link=magnet)
        if not magnet.startswith("magnet:"):
            return info

        try:
            # 提取 btih
            m = BTIH_PATTERN.search(magnet)
            if m:
                info.hash = m.group(1).lower()

            # 解析 query string
            query = magnet[len("magnet:"):]
            if "?" in query:
                query = query.split("?", 1)[1]
            params = parse_qs(query, keep_blank_values=True)

            info.name = unquote(params.get("dn", [""])[0]) if params.get("dn") else ""
            info.trackers = [unquote(t) for t in params.get("tr", []) if t]
            info.file_size = unquote(params.get("xl", [""])[0]) if params.get("xl") else ""
            info.keywords = [unquote(k) for k in params.get("kt", []) if k]
        except Exception as e:
            logger.debug(f"磁力解析失败: {magnet[:80]}: {e}")
        return info

    def extract_from_html(self, html_text: str, source_url: str = "") -> list[MagnetInfo]:
        """从 HTML 文本中提取磁力链接（4 种方式）"""
        if source_url:
            self.source_url = source_url
        if not html_text:
            return []

        results: list[MagnetInfo] = []
        seen_hashes: set[str] = set()

        try:
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception as e:
            logger.debug(f"BeautifulSoup 解析失败: {e}")
            soup = None

        # 方式 1: <a href="magnet:..."> 直接查找
        if soup:
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if href.startswith("magnet:"):
                    info = self.parse_magnet(href)
                    info.source_url = self.source_url
                    if info.hash and info.hash not in seen_hashes:
                        results.append(info)
                        seen_hashes.add(info.hash)

        # 方式 2: 包含磁力/magnet/bt/下载 文本的链接
        if soup:
            for a in soup.find_all("a", string=LINK_TEXT_PATTERN):
                href = a.get("href", "")
                if href.startswith("magnet:"):
                    info = self.parse_magnet(href)
                    info.source_url = self.source_url
                    if info.hash and info.hash not in seen_hashes:
                        results.append(info)
                        seen_hashes.add(info.hash)

        # 方式 3: class 选择器
        if soup:
            for selector in CLASS_SELECTORS:
                for a in soup.select(selector):
                    href = a.get("href", "")
                    if href.startswith("magnet:"):
                        info = self.parse_magnet(href)
                        info.source_url = self.source_url
                        if info.hash and info.hash not in seen_hashes:
                            results.append(info)
                            seen_hashes.add(info.hash)

        # 方式 4: 全文本正则匹配
        text = soup.get_text() if soup else html_text
        for match in MAGNET_PATTERN.finditer(text):
            href = match.group()
            info = self.parse_magnet(href)
            info.source_url = self.source_url
            if info.hash and info.hash not in seen_hashes:
                results.append(info)
                seen_hashes.add(info.hash)

        logger.debug(f"从页面提取到 {len(results)} 条磁力链接")
        return results

    def extract_from_lxml(self, html_text: str, source_url: str = "") -> list[MagnetInfo]:
        """从 lxml tree 提取（更快，仅方式 1+4）"""
        if source_url:
            self.source_url = source_url
        if not html_text:
            return []

        results: list[MagnetInfo] = []
        seen_hashes: set[str] = set()

        try:
            tree = lxml_html.fromstring(html_text)
        except Exception:
            return results

        # 方式 1: a[href^="magnet:"]
        for a in tree.xpath('//a[starts-with(@href, "magnet:")]/@href'):
            info = self.parse_magnet(a)
            info.source_url = self.source_url
            if info.hash and info.hash not in seen_hashes:
                results.append(info)
                seen_hashes.add(info.hash)

        # 方式 4: 全文本正则
        text = tree.text_content() if hasattr(tree, "text_content") else ""
        for match in MAGNET_PATTERN.finditer(text):
            href = match.group()
            info = self.parse_magnet(href)
            info.source_url = self.source_url
            if info.hash and info.hash not in seen_hashes:
                results.append(info)
                seen_hashes.add(info.hash)

        return results


# 便捷函数
def extract_magnets_from_html(html_text: str, source_url: str = "") -> list[MagnetInfo]:
    """便捷函数：从 HTML 提取磁力链接"""
    extractor = MagnetExtractor(source_url=source_url)
    return extractor.extract_from_html(html_text)


def extract_magnets_from_lxml(html_text: str, source_url: str = "") -> list[MagnetInfo]:
    """便捷函数：从 lxml 提取磁力链接（更快）"""
    extractor = MagnetExtractor(source_url=source_url)
    return extractor.extract_from_lxml(html_text)
