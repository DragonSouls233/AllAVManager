"""唯读来源 + .strm 文件生成服务。

对已存在的视频文件不写 NFO、不修改文件属性。
只生成 .strm 串流文件供 Emby/Jellyfin 扫描。
数据存在独立的 read_only 数据库。

参考：OpenAver 的唯读来源模式。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".wmv", ".m4v", ".mov", ".webm", ".ts", ".flv"}
_STRM_EXTS = {".strm"}


@dataclass
class ReadOnlyMovie:
    """唯读来源影片记录。"""
    id: str = ""
    code: str = ""
    title: str = ""
    file_path: str = ""
    strm_path: str = ""
    original_name: str = ""
    module: str = ""
    studio: str = ""
    actors: list[str] = field(default_factory=list)
    file_size: int = 0
    duration: int = 0


class ReadOnlyService:
    """唯读来源管理服务。

    工作流：
    1. scan_directories() — 扫描目录，发现视频文件
    2. generate_strm() — 为每个视频生成 .strm 文件（指向原始路径）
    3. generate_nfo() — 可选：为媒体中心生成 NFO（不影响原文件）
    4. export_json() — 导出索引为 JSON（供外部使用）
    """

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "read_only",
        )
        os.makedirs(self.data_dir, exist_ok=True)

    def scan(self, root_path: str, recursive: bool = True) -> list[ReadOnlyMovie]:
        """扫描目录下的所有视频文件。"""
        movies: list[ReadOnlyMovie] = []
        root = Path(root_path)
        if not root.is_dir():
            return movies

        pattern = "**/*" if recursive else "*"
        for p in root.glob(pattern):
            if p.suffix.lower() in _VIDEO_EXTS and p.is_file():
                movies.append(ReadOnlyMovie(
                    id=p.stem,
                    file_path=str(p.resolve()),
                    original_name=p.name,
                    title=p.stem,
                    file_size=p.stat().st_size,
                    module=self._guess_module(p),
                ))
        return movies

    def _guess_module(self, path: Path) -> str:
        """从文件路径猜测模块。"""
        p = str(path).lower()
        if any(kw in p for kw in ("chinese", "国产", "madou", "麻豆")):
            return "chinese"
        if any(kw in p for kw in ("fc2", "FC2")):
            return "fc2"
        if any(kw in p for kw in ("uncensored", "无码", "heyzo", "1pondo")):
            return "uncensored"
        if any(kw in p for kw in ("pornhub", "ph_")):
            return "pornhub"
        if any(kw in p for kw in ("western", "欧美", "brazzers", "vixen", "blacked")):
            return "western"
        return "jav"

    def generate_strm(self, movie: ReadOnlyMovie,
                      strm_root: str | None = None) -> str:
        """为视频生成 .strm 文件。

        .strm 文件内容为视频的绝对路径。
        Emby/Jellyfin 扫描 .strm 时会读取内容并播放。
        """
        output_root = strm_root or os.path.join(self.data_dir, "strm")
        module_dir = os.path.join(output_root, movie.module)
        os.makedirs(module_dir, exist_ok=True)

        strm_name = movie.original_name.rsplit(".", 1)[0] + ".strm"
        strm_path = os.path.join(module_dir, strm_name)

        with open(strm_path, "w", encoding="utf-8") as f:
            f.write(movie.file_path)

        movie.strm_path = strm_path
        return strm_path

    def generate_nfo(self, movie: ReadOnlyMovie,
                     nfo_root: str | None = None) -> str:
        """为媒体中心生成 .nfo 元数据（不影响原文件）。"""
        output_root = nfo_root or os.path.join(self.data_dir, "nfo")
        module_dir = os.path.join(output_root, movie.module)
        os.makedirs(module_dir, exist_ok=True)

        nfo_name = movie.original_name.rsplit(".", 1)[0] + ".nfo"
        nfo_path = os.path.join(module_dir, nfo_name)

        with open(nfo_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write("<movie>\n")
            f.write(f"  <title>{movie.title}</title>\n")
            f.write(f"  <code>{movie.code or movie.title}</code>\n")
            f.write(f"  <studio>{movie.studio or ''}</studio>\n")
            if movie.actors:
                for a in movie.actors:
                    f.write(f"  <actor><name>{a}</name></actor>\n")
            f.write(f"  <source>read_only</source>\n")
            f.write("</movie>\n")

        return nfo_path

    def export_json(self, movies: list[ReadOnlyMovie],
                    output_path: str | None = None) -> str:
        """导出索引为 JSON。"""
        path = output_path or os.path.join(self.data_dir, "index.json")
        data = []
        for m in movies:
            data.append({
                "id": m.id,
                "code": m.code,
                "title": m.title,
                "file_path": m.file_path,
                "strm_path": m.strm_path,
                "module": m.module,
                "studio": m.studio,
                "actors": m.actors,
                "file_size": m.file_size,
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"movies": data, "count": len(data)}, f, ensure_ascii=False, indent=2)
        return path

    async def full_process(self, root_path: str,
                           strm_root: str | None = None,
                           nfo_root: str | None = None,
                           generate_strm_flag: bool = True,
                           generate_nfo_flag: bool = True) -> dict:
        """完整处理流程：扫描 → 生成 .strm → 生成 .nfo → 导出 JSON。"""
        movies = self.scan(root_path)

        strm_count = 0
        nfo_count = 0
        for m in movies:
            if generate_strm_flag:
                self.generate_strm(m, strm_root)
                strm_count += 1
            if generate_nfo_flag:
                self.generate_nfo(m, nfo_root)
                nfo_count += 1

        json_path = self.export_json(movies)

        return {
            "root": root_path,
            "videos_found": len(movies),
            "strm_generated": strm_count,
            "nfo_generated": nfo_count,
            "json_index": json_path,
            "data_dir": self.data_dir,
        }
