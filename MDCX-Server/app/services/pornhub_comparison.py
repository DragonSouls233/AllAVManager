"""
PORNHub 本地 vs 在线对比查重服务

基于 PornSimilarityPlatform (PSP) 的 MissingFinder 核心逻辑适配到 MDCX 体系。
核心工作流：
1. 用户提供 PORNHub 演员URL → 爬虫获取在线视频列表
2. 扫描本地目录获取视频文件
3. 标题归一化 + 相似度匹配 → 输出缺失/已匹配列表
"""
import re
import os
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class TitleNormalizer:
    """标题归一化器（适配自 PSP TitleNormalizer）"""

    RESOLUTION_PATTERNS = [
        r'\b(4K|2160p|1080p|720p|480p|360p|240p)\b',
        r'\b(HD|FHD|UHD|SD)\b',
        r'\b(HDR|HDR10|DolbyVision)\b',
        r'\b(60fps|30fps)\b',
    ]

    CODEC_PATTERNS = [
        r'\b(H\.?264|H\.?265|HEVC|AVC|VP9|AV1)\b',
        r'\b(x264|x265|xvid|divx)\b',
    ]

    SITE_PATTERNS = [
        r'\b(PornHub|Porn|PH|XVideos|XV|XHamster|XH|Porn91|91Porn)\b',
        r'\[(PornHub|Porn|PH|XVideos|XV|XHamster|XH)\]',
    ]

    FULLWIDTH_MAP = {
        '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
        '５': '5', '６': '6', '７': '7', '８': '8', '９': '9',
        'Ａ': 'A', 'Ｂ': 'B', 'Ｃ': 'C', 'Ｄ': 'D', 'Ｅ': 'E',
        'Ｆ': 'F', 'Ｇ': 'G', 'Ｈ': 'H', 'Ｉ': 'I', 'Ｊ': 'J',
        'Ｋ': 'K', 'Ｌ': 'L', 'Ｍ': 'M', 'Ｎ': 'N', 'Ｏ': 'O',
        'Ｐ': 'P', 'Ｑ': 'Q', 'Ｒ': 'R', 'Ｓ': 'S', 'Ｔ': 'T',
        'Ｕ': 'U', 'Ｖ': 'V', 'Ｗ': 'W', 'Ｘ': 'X', 'Ｙ': 'Y', 'Ｚ': 'Z',
        'ａ': 'a', 'ｂ': 'b', 'ｃ': 'c', 'ｄ': 'd', 'ｅ': 'e',
        'ｆ': 'f', 'ｇ': 'g', 'ｈ': 'h', 'ｉ': 'i', 'ｊ': 'j',
        'ｋ': 'k', 'ｌ': 'l', 'ｍ': 'm', 'ｎ': 'n', 'ｏ': 'o',
        'ｐ': 'p', 'ｑ': 'q', 'ｒ': 'r', 'ｓ': 's', 'ｔ': 't',
        'ｕ': 'u', 'ｖ': 'v', 'ｗ': 'w', 'ｘ': 'x', 'ｙ': 'y', 'ｚ': 'z',
        '　': ' ', '＿': '_', '－': '-',
    }

    DASH_PATTERNS = [
        (r'[\u2013\u2014\u2015\u2212]', '-'),
        (r'—', '-'),
        (r'–', '-'),
    ]

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.case_sensitive = self.config.get("case_sensitive", False)
        self.strip_punctuation = self.config.get("strip_punctuation", True)
        self.strip_resolution = self.config.get("strip_resolution", True)
        self.strip_site_tags = self.config.get("strip_site_tags", True)

    def normalize(self, title: str) -> str:
        if not title:
            return ""
        result = title.strip()
        result = self._fullwidth_to_halfwidth(result)
        for pattern, replacement in self.DASH_PATTERNS:
            result = re.sub(pattern, replacement, result)
        result = re.sub(r'[/\\]', '_', result)
        if self.strip_resolution:
            for pattern in self.RESOLUTION_PATTERNS:
                result = re.sub(pattern, "", result, flags=re.IGNORECASE)
            for pattern in self.CODEC_PATTERNS:
                result = re.sub(pattern, "", result, flags=re.IGNORECASE)
        if self.strip_site_tags:
            for pattern in self.SITE_PATTERNS:
                result = re.sub(pattern, "", result, flags=re.IGNORECASE)
        result = re.sub(r'\[[^\]]*\]', "", result)
        result = re.sub(r'\([^)]*(p|P|HD|FHD|4K)[^)]*\)', "", result)
        result = re.sub(r'\s+', " ", result).strip()
        if not self.case_sensitive:
            result = result.lower()
        if self.strip_punctuation:
            result = re.sub(r'[\W_]+', "", result, flags=re.UNICODE)
        return result

    def _fullwidth_to_halfwidth(self, text: str) -> str:
        result = []
        for char in text:
            if char in self.FULLWIDTH_MAP:
                result.append(self.FULLWIDTH_MAP[char])
            else:
                result.append(char)
        return "".join(result)

    def are_similar(self, title1: str, title2: str, threshold: float = 0.85) -> bool:
        norm1 = self.normalize(title1)
        norm2 = self.normalize(title2)
        if norm1 == norm2:
            return True
        if norm1 in norm2 or norm2 in norm1:
            return True
        if len(norm1) > 0 and len(norm2) > 0:
            set1 = set(norm1)
            set2 = set(norm2)
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            if union > 0:
                return (intersection / union) >= threshold
        return False


class LocalMediaScanner:
    """本地视频文件扫描器"""

    VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"}

    def __init__(self, media_dirs: list = None):
        self.media_dirs = media_dirs or []

    def scan_directory(self, directory: str) -> List[Dict[str, Any]]:
        videos = []
        if not directory or not os.path.exists(directory):
            return videos
        path = Path(directory)
        for f in path.rglob("*"):
            if f.suffix.lower() in self.VIDEO_EXTENSIONS and f.is_file():
                title = f.stem
                videos.append({
                    "file_path": str(f),
                    "file_name": f.name,
                    "title": title,
                    "normalized_title": TitleNormalizer().normalize(title),
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1) if f.stat().st_size > 0 else 0,
                })
        return videos

    def scan_directories(self) -> List[Dict[str, Any]]:
        all_videos = []
        for d in self.media_dirs:
            all_videos.extend(self.scan_directory(d))
        return all_videos


class PornhubComparator:
    """
    PORNHub 在线 vs 本地对比查重服务

    核心流程（适配自 PSP MissingFinder）：
    1. 爬虫获取在线视频列表（基于 actress URL）
    2. 扫描本地目录获取视频文件
    3. 标题归一化 + 相似度匹配
    4. 输出缺失/已匹配列表
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.normalizer = TitleNormalizer(config)

    async def compare(
        self,
        actress_url: str,
        local_directory: str = None,
        similarity_threshold: float = 0.85,
        max_pages: int = 100,
    ) -> Dict[str, Any]:
        result = {
            "actress_url": actress_url,
            "online_count": 0,
            "local_count": 0,
            "matched_count": 0,
            "missing_count": 0,
            "missing_videos": [],
            "local_videos": [],
            "online_videos": [],
        }

        try:
            # 1. 获取在线视频列表（通过 PORNHub 爬虫）
            online_videos = await self._fetch_online_videos(actress_url, max_pages)
            result["online_videos"] = online_videos
            result["online_count"] = len(online_videos)

            # 2. 扫描本地目录
            local_videos = []
            if local_directory:
                scanner = LocalMediaScanner()
                local_videos = scanner.scan_directory(local_directory)
            result["local_videos"] = local_videos
            result["local_count"] = len(local_videos)

            # 3. 构建本地标题集合
            local_normalized = {}
            for v in local_videos:
                norm = v.get("normalized_title", "")
                if norm:
                    local_normalized[norm] = v

            # 4. 对比找出缺失
            missing = []
            matched = 0
            for ov in online_videos:
                online_title = ov.get("title", "")
                online_norm = self.normalizer.normalize(online_title)

                if online_norm in local_normalized:
                    matched += 1
                    continue

                is_matched = False
                for local_norm, lv in local_normalized.items():
                    if self.normalizer.are_similar(online_title, lv.get("title", ""), similarity_threshold):
                        is_matched = True
                        matched += 1
                        break

                if not is_matched:
                    missing.append(ov)

            result["missing_videos"] = missing
            result["missing_count"] = len(missing)
            result["matched_count"] = matched

        except Exception as e:
            logger.error(f"PORNHub 对比查重失败: {e}", exc_info=True)

        return result

    async def _fetch_online_videos(self, actress_url: str, max_pages: int) -> List[Dict[str, Any]]:
        """通过 PORNHub 爬虫获取演员的在线视频列表"""
        try:
            from app.crawlers.pornhub import PornhubCrawler
            crawler = PornhubCrawler()
            # 使用爬虫的搜索/浏览功能获取视频列表
            videos = await crawler.fetch_actress_videos(actress_url, max_pages=max_pages)
            return videos
        except ImportError:
            logger.warning("PornhubCrawler 未找到，尝试备用方案")
            return await self._fetch_online_videos_fallback(actress_url, max_pages)

    async def _fetch_online_videos_fallback(self, actress_url: str, max_pages: int) -> List[Dict[str, Any]]:
        """备用方案：通过 httpx 直接抓取 PORNHub 页面"""
        import httpx
        from bs4 import BeautifulSoup

        videos = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }

        for page in range(1, min(max_pages + 1, 10)):
            url = f"{actress_url}?page={page}" if "?" not in actress_url else f"{actress_url}&page={page}"
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        break
                    soup = BeautifulSoup(resp.text, "html.parser")
                    video_cards = soup.select(".video-wrapper .video-card") or soup.select(".vid-item")

                    if not video_cards:
                        break

                    for card in video_cards:
                        title_el = card.select_one(".title a") or card.select_one("a[title]")
                        url_el = card.select_one("a[href*='viewkey']")
                        duration_el = card.select_one(".duration") or card.select_one(".time")

                        title = ""
                        if title_el:
                            title = title_el.get("title", "") or title_el.get_text(strip=True)
                        video_url = ""
                        if url_el:
                            href = url_el.get("href", "")
                            video_url = f"https://www.pornhub.com{href}" if href.startswith("/") else href
                        duration = duration_el.get_text(strip=True) if duration_el else ""

                        if title:
                            videos.append({
                                "title": title,
                                "url": video_url,
                                "duration": duration,
                                "source": "pornhub_fallback",
                            })

                    if not video_cards:
                        break
            except Exception as e:
                logger.warning(f"抓取第 {page} 页失败: {e}")
                break

        return videos
