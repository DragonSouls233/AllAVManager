"""
PORNHub 扫描器
目录结构: G:\\TEST\\pornhub\\[Channel] ActorName\\videofile.mp4
从目录名提取演员，支持服务器上带国籍的目录名

支持的目录名格式:
  - Anna Cherry7
  - [ChannelName] Anna Cherry7
  - Anna Cherry7 [US]
  - [ChannelName] Anna Cherry7 [US]
  - Anna Cherry7 (US)
"""

import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 常见国籍标记
_NATIONALITY_PATTERNS = {
    "US": "美国", "USA": "美国", "美国": "美国",
    "UK": "英国", "GB": "英国", "英国": "英国",
    "JP": "日本", "日本": "日本",
    "KR": "韩国", "韩国": "韩国",
    "TW": "台湾", "台湾": "台湾",
    "CN": "中国", "中国": "中国",
    "HK": "香港", "香港": "香港",
    "FR": "法国", "法国": "法国",
    "DE": "德国", "德国": "德国",
    "IT": "意大利", "意大利": "意大利",
    "ES": "西班牙", "西班牙": "西班牙",
    "CA": "加拿大", "加拿大": "加拿大",
    "AU": "澳大利亚", "澳大利亚": "澳大利亚",
    "BR": "巴西", "巴西": "巴西",
    "RU": "俄罗斯", "俄罗斯": "俄罗斯",
    "NL": "荷兰", "荷兰": "荷兰",
    "SE": "瑞典", "瑞典": "瑞典",
    "CH": "瑞士", "瑞士": "瑞士",
    "TH": "泰国", "泰国": "泰国",
    "VN": "越南", "越南": "越南",
    "PH": "菲律宾", "菲律宾": "菲律宾",
    "IN": "印度", "印度": "印度",
    "AR": "阿根廷", "阿根廷": "阿根廷",
    "MX": "墨西哥", "墨西哥": "墨西哥",
    "CO": "哥伦比亚", "哥伦比亚": "哥伦比亚",
    "EU": "欧洲", "欧洲": "欧洲",
}


def extract_pornhub_code(filename: str) -> str | None:
    """从文件名提取 PORNHub viewkey

    PornHub viewkey 格式为 13 位字母数字，字符范围涵盖 a-z0-9。
    真实 PH viewkey 必定包含 g-z 范围的字母（不限于 a-f），以此区分纯 MD5/哈希值。

    支持格式:
      - phXXXXXXXXXXXXX  (带 ph 前缀，13位，必含 g-z 字母)
      - XXXXXXXXXXXXX    (不带 ph 前缀，13位，必含 g-z 字母)
    """
    stem = Path(filename).stem

    def _is_valid_viewkey(s: str) -> bool:
        """验证是否为真实 PH viewkey: 13位，必含 g-z 范围字母"""
        if len(s) != 13:
            return False
        has_gz_letter = any(c >= 'g' and c <= 'z' for c in s)
        return has_gz_letter

    # 优先匹配带 ph 前缀的 viewkey（ph + 13位字母数字）
    pattern = r'\bph([a-z0-9]{13})\b'
    match = re.search(pattern, stem, re.IGNORECASE)
    if match:
        code = match.group(1).lower()
        if _is_valid_viewkey(code):
            return "ph" + code
    # 回退匹配纯 13 位字母数字（不含ph前缀）
    pattern2 = r'\b([a-z0-9]{13})\b'
    match2 = re.search(pattern2, stem, re.IGNORECASE)
    if match2:
        code = match2.group(1).lower()
        if _is_valid_viewkey(code):
            return code
    return None


def extract_actor_and_nationality(folder_name: str) -> tuple[str | None, str | None]:
    """从文件夹名提取演员名和国籍

    支持的格式:
      - [ChannelName] Anna Cherry7 [US]  →  ("Anna Cherry7", "美国")
      - Anna Cherry7 [US]                →  ("Anna Cherry7", "美国")
      - [Channel] Anna Cherry7           →  ("Anna Cherry7", None)
      - Anna Cherry7                     →  ("Anna Cherry7", None)
      - Anna Cherry7 (US)                →  ("Anna Cherry7", "美国")
      - Anna+Sunny [US]                  →  ("Anna+Sunny", "美国")
      - Anna Cherry7 + Sunny Leone [UK]  →  ("Anna Cherry7 + Sunny Leone", "英国")

    Returns:
        (actor_name, nationality) 元组
    """
    name = folder_name.strip()
    if not name:
        return None, None

    # 1. 去掉开头的 [ChannelName] / [Chan] 等标记
    name = re.sub(r'^\[.*?\]\s*', '', name).strip()

    # 2. 尝试从末尾提取国籍 [XX] 或 (XX)
    nationality = None

    # 匹配末尾 [US] [UK] [JP] 等
    m = re.search(r'\s*\[([A-Za-z]{2,4}(?:[,/\s][A-Za-z]{2,4})*)\]\s*$', name)
    if m:
        code = m.group(1).strip().upper()
        nationality = _NATIONALITY_PATTERNS.get(code, code)
        name = name[:m.start()].strip()

    # 匹配末尾 (US) (UK) 等
    if not nationality:
        m = re.search(r'\s*\(([A-Za-z]{2,4})\)\s*$', name)
        if m:
            code = m.group(1).strip().upper()
            nationality = _NATIONALITY_PATTERNS.get(code, code)
            name = name[:m.start()].strip()

    # 3. 检查是否还包含多个演员（用 + 或 & 分割）
    # 保留原始格式，在写入 DB 时按逗号分隔

    if not name:
        return None, None

    return name, nationality


class PornhubScanner(BaseScanner):
    """PORNHub 模块扫描器"""

    def __init__(self, media_dirs: list[str]):
        super().__init__("pornhub", media_dirs)

    async def scan(self) -> dict:
        """扫描 PORNHub 媒体目录并落库"""
        results = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "actors_found": {}, "errors": []}

        for media_dir in self.media_dirs:
            try:
                dir_result = await self._scan_directory(Path(media_dir))
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["matched"] += dir_result["matched"]
                results["movies_added"] += dir_result.get("movies_added", 0)
                results["actors_found"].update(dir_result.get("actors", {}))
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"扫描目录失败 {media_dir}: {e}")

        # 更新演员表的 movie_count
        if results["actors_found"]:
            await self._update_actor_counts()

        results["actors_found"] = list(results["actors_found"].keys())
        return results

    async def _scan_directory(self, media_dir: Path) -> dict:
        """扫描单个媒体目录并写入数据库"""
        result = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "actors": {}}
        media_dir = Path(media_dir)

        from app.db.module_db import ModuleDatabase
        db = ModuleDatabase.get_instance("pornhub")
        session = await db.get_session()
        try:
            from app.db.pornhub_models import PornhubMovie, PornhubActor
            from sqlalchemy import select

            for root, dirs, files in os.walk(media_dir):
                # 提取当前目录的演员名和国籍（跳过根目录）
                actor_name, nationality = self._get_actor_from_path(root, media_dir)

                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    code = extract_pornhub_code(file_name)
                    if not code:
                        continue
                    result["matched"] += 1

                    # 检查是否已存在
                    existing = await session.execute(select(PornhubMovie).where(PornhubMovie.code == code))
                    if existing.scalar_one_or_none():
                        continue

                    # 写入新影片记录
                    new_movie = PornhubMovie(
                        code=code,
                        title=Path(file_name).stem,
                        actor=actor_name,
                        file_path=str(file_path),
                        file_size=file_path.stat().st_size if file_path.exists() else 0,
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1

                    if actor_name:
                        result["actors"][actor_name] = nationality

            # 同步演员表：新演员写入（正确记录每个演员的国籍）
            for actor_name, actor_nationality in result["actors"].items():
                ext_actor = await session.execute(
                    select(PornhubActor).where(PornhubActor.name == actor_name)
                )
                existing_actor = ext_actor.scalar_one_or_none()
                if not existing_actor:
                    session.add(PornhubActor(
                        name=actor_name,
                        nationality=actor_nationality,
                        source="folder",
                        movie_count=1,
                    ))
                elif actor_nationality and not existing_actor.nationality:
                    existing_actor.nationality = actor_nationality

            await session.commit()
        finally:
            await session.close()

        return result

    async def _update_actor_counts(self):
        """更新演员表的 movie_count"""
        from app.db.module_db import ModuleDatabase
        from app.db.pornhub_models import PornhubActor, PornhubMovie
        from sqlalchemy import select, func

        db = ModuleDatabase.get_instance("pornhub")
        session = await db.get_session()
        try:
            actors = await session.execute(select(PornhubActor))
            for actor_row in actors.scalars().all():
                actor_name = actor_row.name
                count = await session.scalar(
                    select(func.count()).select_from(PornhubMovie).where(
                        PornhubMovie.actor.like(f"%{actor_name}%")
                    )
                ) or 0
                actor_row.movie_count = count
            await session.commit()
        finally:
            await session.close()

    def _get_actor_from_path(self, file_path: Path, media_dir: Path) -> tuple[str | None, str | None]:
        """从文件路径中提取演员名和国籍

        目录结构:
          G:\\TEST\\pornhub\\[Channel] Anna Cherry7\\videofile.mp4
          G:\\TEST\\pornhub\\Anna Cherry7 [US]\\videofile.mp4
          G:\\TEST\\pornhub\\XXX\\Anna Cherry7\\videofile.mp4

        优先使用离文件最近的目录名。
        """
        try:
            rel_path = file_path.relative_to(media_dir)
        except ValueError:
            return None, None

        # 取文件所在目录的父目录名（跳过文件本身）
        parent_dir = rel_path.parent

        if parent_dir == Path("."):
            return None, None

        # 取最内层目录名
        folder_name = parent_dir.name if parent_dir != Path(".") else None
        if not folder_name:
            return None, None

        return extract_actor_and_nationality(folder_name)
