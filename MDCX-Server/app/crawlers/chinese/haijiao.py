"""
海角社区 (haijiao.com) 爬虫 — 国产原创平台。

海角是中国最大的国产原创视频平台之一，拥有大量独家演员和内容。
从主页URL提取用户发布的全部视频标题列表。

参考：海角标题提取器 v7.0 (特殊项目/提取)
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@register_crawler
class HaijiaoCrawler(BaseCrawler):
    """海角社区国产原创爬虫。"""

    name = "haijiao"
    display_name = "海角社区"
    base_url = "https://haijiao.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["chinese"]
    description = "海角社区国产原创内容"
    language = "zh"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    async def fetch_user_videos(self, user_url: str,
                                max_pages: int = 20,
                                skip_existing: bool = True,
                                data_dir: str | None = None) -> dict:
        """获取海角用户的所有视频标题。

        Args:
            user_url: 用户主页URL (https://haijiao.com/homepage/{id})
            max_pages: 最大页数
            skip_existing: 跳过已缓存
            data_dir: 数据目录

        Returns:
            {"user_id": str, "titles": list, "success": bool, "cached": bool}
        """
        user_id = self._extract_user_id(user_url)
        if not user_id:
            return {"user_id": "", "titles": [], "success": False, "error": "无法提取用户ID"}

        # 缓存检查
        cache_path = ""
        if data_dir and skip_existing:
            cache_path = os.path.join(data_dir, f"user_{user_id}.json")
            if os.path.isfile(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    if cached.get("titles"):
                        return {"user_id": user_id, "titles": cached["titles"],
                                "success": True, "cached": True}
                except Exception:
                    pass

        # 爬取
        all_titles: list[str] = []
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            for page in range(1, max_pages + 1):
                page_url = f"{user_url}?page={page}"
                try:
                    html = await client.get_text(page_url, headers={"User-Agent": _USER_AGENT})
                    if not html:
                        break

                    titles = self._extract_titles(html)
                    if not titles:
                        break

                    all_titles.extend(titles)
                    time.sleep(0.5)

                except Exception as e:
                    logger.debug("haijiao page %d failed: %s", page, e)
                    break

        # 去重
        seen = set()
        unique_titles = []
        for t in all_titles:
            if t and t not in seen:
                seen.add(t)
                unique_titles.append(t)

        # 缓存
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            cache_path = os.path.join(data_dir, f"user_{user_id}.json")
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"user_id": user_id, "titles": unique_titles,
                               "count": len(unique_titles),
                               "updated": datetime.now().isoformat()},
                              f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        return {"user_id": user_id, "titles": unique_titles,
                "success": True, "cached": False}

    def _extract_user_id(self, url: str) -> Optional[str]:
        m = re.search(r"homepage/(\d+)", url)
        return m.group(1) if m else None

    def _extract_titles(self, html: str) -> list[str]:
        titles: list[str] = []

        # 模式1: 标题链接
        for m in re.finditer(r'<a[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL):
            t = m.group(1).strip()
            if t and len(t) > 2:
                titles.append(t)

        # 模式2: h2/h3 标题
        if not titles:
            for m in re.finditer(r'<h[23][^>]*>(.*?)</h[23]>', html):
                t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if t and len(t) > 2:
                    titles.append(t)

        # 模式3: video-card 类
        if not titles:
            for m in re.finditer(r'class="[^"]*video-card[^"]*"[^>]*>.*?<h[^>]*>(.*?)</h', html, re.DOTALL):
                t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if t and len(t) > 2:
                    titles.append(t)

        return titles


# ---------------------------------------------------------------------------
# 国产视频对比器 — 从海角提取器移植
# ---------------------------------------------------------------------------


class ChineseVideoComparer:
    """国产视频对比器 — 对比标题列表与本地视频目录。

    功能：
    1. 加载标题列表（从TXT或提取结果）
    2. 扫描本地视频目录
    3. 模糊匹配（阈值可调）
    4. 检测重复视频
    5. 导出报告
    """

    def __init__(self, match_threshold: float = 0.90):
        super().__init__()
        self.match_threshold = match_threshold

    def load_titles(self, path: str) -> list[str]:
        """从TXT文件加载标题。"""
        titles = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    titles.append(line)
        return titles

    def scan_videos(self, directory: str) -> list[dict]:
        """扫描本地视频目录。"""
        video_exts = {".mp4", ".mkv", ".avi", ".wmv", ".m4v", ".mov", ".webm", ".ts", ".flv"}
        videos = []
        for f in Path(directory).rglob("*"):
            if f.suffix.lower() in video_exts and f.is_file():
                norm = re.sub(r'[^\u4e00-\u9fff\w]', '', f.stem).lower()
                videos.append({
                    "path": str(f),
                    "filename": f.name,
                    "stem": f.stem,
                    "normalized": norm,
                })
        return videos

    def _normalize(self, text: str) -> str:
        """归一化文本用于模糊匹配。"""
        return re.sub(r'[^\u4e00-\u9fff\w\s]', '', text).lower().strip()

    def compare(self, titles: list[str], directory: str) -> dict:
        """对比标题列表与视频目录。"""
        videos = self.scan_videos(directory)
        norm_videos = {v["normalized"]: v for v in videos}

        matched: list[dict] = []
        missing: list[dict] = []
        matched_set = set()

        for title in titles:
            norm_title = self._normalize(title)
            if not norm_title:
                continue

            # 精确匹配
            if norm_title in norm_videos:
                matched.append({
                    "title": title,
                    "video": norm_videos[norm_title]["filename"],
                    "path": norm_videos[norm_title]["path"],
                    "score": 1.0,
                    "type": "exact",
                })
                matched_set.add(norm_videos[norm_title]["path"])
                continue

            # 模糊匹配
            best_score = 0.0
            best_video = None
            for vn, v in norm_videos.items():
                # Jaccard 相似度（中文分词字符级）
                chars_title = set(norm_title)
                chars_video = set(vn)
                if not chars_title or not chars_video:
                    continue
                intersection = chars_title & chars_video
                union = chars_title | chars_video
                score = len(intersection) / len(union) if union else 0
                if score > best_score:
                    best_score = score
                    best_video = v

            if best_score >= self.match_threshold and best_video:
                matched.append({
                    "title": title,
                    "video": best_video["filename"],
                    "path": best_video["path"],
                    "score": round(best_score, 4),
                    "type": "fuzzy",
                })
                matched_set.add(best_video["path"])
            else:
                missing.append({
                    "title": title,
                    "normalized": norm_title,
                    "best_score": round(best_score, 4) if best_score else 0,
                    "best_candidate": best_video["filename"] if best_video else "",
                    "best_candidate_score": round(best_score, 4) if best_score else 0,
                })

        extra = [v for v in videos if v["path"] not in matched_set]

        return {
            "total_titles": len(titles),
            "total_videos": len(videos),
            "matched": matched,
            "matched_count": len(matched),
            "missing": missing,
            "missing_count": len(missing),
            "extra": extra,
            "extra_count": len(extra),
        }

    def export_report(self, result: dict, output_path: str, fmt: str = "txt"):
        """导出对比报告。"""
        if fmt == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"对比报告\n")
                f.write(f"总计: 标题 {result['total_titles']}, 视频 {result['total_videos']}\n")
                f.write(f"匹配: {result['matched_count']}, 缺失: {result['missing_count']}, 额外: {result['extra_count']}\n\n")
                for m in result["matched"]:
                    f.write(f"[MATCHED] {m['title']} → {m['video']} ({m['score']:.2f})\n")
                for m in result["missing"]:
                    f.write(f"[MISSING] {m['title']} (最佳候选: {m.get('best_candidate', '无')})\n")
        return output_path
