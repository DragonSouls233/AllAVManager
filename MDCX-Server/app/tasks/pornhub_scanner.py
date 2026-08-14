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

import asyncio
import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner, copy_video_assets_to_data_dir, iter_media_entries, _file_size
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 常见国籍标记（扩展版）
_NATIONALITY_PATTERNS: dict[str, str] = {
    # 英文代码 → 中文
    "US": "美国", "USA": "美国",
    "UK": "英国", "GB": "英国",
    "JP": "日本", "KR": "韩国",
    "TW": "台湾", "CN": "中国",
    "HK": "香港", "MO": "澳门",
    "FR": "法国", "DE": "德国",
    "IT": "意大利", "ES": "西班牙",
    "CA": "加拿大", "AU": "澳大利亚",
    "BR": "巴西", "RU": "俄罗斯",
    "NL": "荷兰", "SE": "瑞典",
    "CH": "瑞士", "TH": "泰国",
    "VN": "越南", "PH": "菲律宾",
    "IN": "印度", "AR": "阿根廷",
    "MX": "墨西哥", "CO": "哥伦比亚",
    "EE": "爱沙尼亚", "EU": "欧洲",
    "PT": "葡萄牙", "GR": "希腊",
    "PL": "波兰", "CZ": "捷克",
    "HU": "匈牙利", "RO": "罗马尼亚",
    "UA": "乌克兰", "BY": "白俄罗斯",
    "TR": "土耳其", "IL": "以色列",
    "SA": "沙特", "AE": "阿联酋",
    "EG": "埃及", "ZA": "南非",
    "NG": "尼日利亚", "KE": "肯尼亚",
    "ID": "印尼", "MY": "马来西亚",
    "SG": "新加坡", "NZ": "新西兰",
    "DK": "丹麦", "NO": "挪威",
    "FI": "芬兰", "BE": "比利时",
    "AT": "奥地利", "SK": "斯洛伐克",
    "SI": "斯洛文尼亚", "HR": "克罗地亚",
    "RS": "塞尔维亚", "BG": "保加利亚",
    "LT": "立陶宛", "LV": "拉脱维亚",
    "CL": "智利", "PE": "秘鲁",
    "CU": "古巴", "DO": "多米尼加",
    "PR": "波多黎各",
    # 中文名（支持上级目录直接用中文名）
    "美国": "美国", "英国": "英国", "日本": "日本",
    "韩国": "韩国", "台湾": "台湾", "中国": "中国",
    "香港": "香港", "澳门": "澳门",
    "法国": "法国", "德国": "德国",
    "意大利": "意大利", "西班牙": "西班牙",
    "加拿大": "加拿大", "澳大利亚": "澳大利亚",
    "巴西": "巴西", "俄罗斯": "俄罗斯",
    "荷兰": "荷兰", "瑞典": "瑞典", "瑞士": "瑞士",
    "泰国": "泰国", "越南": "越南",
    "菲律宾": "菲律宾", "印度": "印度",
    "阿根廷": "阿根廷", "墨西哥": "墨西哥",
    "哥伦比亚": "哥伦比亚", "爱沙尼亚": "爱沙尼亚",
    "欧洲": "欧洲",
    "葡萄牙": "葡萄牙", "希腊": "希腊",
    "波兰": "波兰", "捷克": "捷克",
    "匈牙利": "匈牙利", "罗马尼亚": "罗马尼亚",
    "乌克兰": "乌克兰", "白俄罗斯": "白俄罗斯",
    "土耳其": "土耳其", "以色列": "以色列",
    "印尼": "印尼", "马来西亚": "马来西亚",
    "新加坡": "新加坡", "新西兰": "新西兰",
    "丹麦": "丹麦", "挪威": "挪威",
    "芬兰": "芬兰", "比利时": "比利时",
    "奥地利": "奥地利",
    "智利": "智利", "秘鲁": "秘鲁",
    "古巴": "古巴",
    "南非": "南非", "尼日利亚": "尼日利亚",
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
      - 美国                              →  (None, "美国")    ← 纯国籍目录
      - 俄罗斯                            →  (None, "俄罗斯")  ← 纯国籍目录
      - 素人                              →  ("素人", None)    ← 特殊分类(保留原名)

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

    # 4. 如果清洗后的文件夹名直接匹配国籍字典中的中文国籍名，
    #    说明这是一个纯国籍目录（如 M:\美国\），不应作为演员名
    if name in _NATIONALITY_PATTERNS:
        return None, name

    # 5. 过滤非演员的分类目录（如"素人"等分类标签，不是具体演员名）
    _CATEGORY_BLACKLIST = {
        "素人", "Amateur", "VIP", "Premium",
        "Uncensored", "1080p", "4K", "HD", "精选", "合集",
    }
    if name in _CATEGORY_BLACKLIST:
        return None, nationality

    return name, nationality


def _split_actor_names(name: str) -> list[str]:
    """把 'Anna + Sunny' / 'A & B' / 'A, B' 拆成独立演员名。

    与影片刮削逐个建表（scrape_result.actors）的口径对齐，
    避免扫描建出 'Anna + Sunny' 整段、刮削建出 'Anna'/'Sunny' 分裂导致的
    movie_count 计数与展示不一致。movie.actor 仍保留原整段字符串用于 LIKE 计数。
    """
    parts = re.split(r"\s*[+&,/]\s*", name)
    return [p.strip() for p in parts if p.strip()]


class PornhubScanner(BaseScanner):
    """PORNHub 模块扫描器"""

    def __init__(self, media_dirs: list[str]):
        super().__init__("pornhub", media_dirs)

    async def scan(self) -> dict:
        """扫描 PORNHub 媒体目录并落库"""
        results = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "actors_found": {}, "errors": []}

        logger.info(f"[pornhub] 扫描启动: media_dirs={[str(d) for d in self.media_dirs]}")
        for media_dir in self.media_dirs:
            try:
                logger.info(f"[pornhub] 开始扫描目录: {media_dir}")
                dir_result = await self._scan_directory(Path(media_dir))
                logger.info(
                    f"[pornhub] 目录扫描完成: {media_dir} 共发现 {dir_result['total']} 个文件，"
                    f"新增 {dir_result.get('movies_added', 0)}"
                )
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
        logger.info(
            f"[pornhub] 扫描完成: 共发现 {results['total']} 个文件，新增 {results['movies_added']}，"
            f"错误 {len(results['errors'])} 个"
        )
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

            # 性能修复：一次性载入已存在番号，避免每文件一次 SELECT 的 N+1 查询
            existing_codes: set[str] = set(
                (await session.execute(select(PornhubMovie.code))).scalars().all()
            )

            walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
            for root, dirs, files in walk_entries:
                # 提取当前目录的演员名和国籍（跳过根目录）
                # 传入 root 路径而非文件路径，_get_actor_from_path 内部使用 parent 提取目录
                root_path = Path(root)
                actor_name, nationality = self._get_actor_from_path(root_path / "dummy.mp4", media_dir)

                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    code = extract_pornhub_code(file_name)
                    if not code:
                        # 文件名不含 PornHub viewkey 时，回退用「相对路径」作为 code。
                        # 不能只用文件名 stem：M:/N:/O: 各目录普遍存在同名文件
                        # （video.mp4 / 01.mp4 / clip 01.mp4），若按 stem 做 code，
                        # 跨目录同名文件会被 existing_codes 内存判重成批丢弃，
                        # 这正是 PORNHUB 库几乎无数据的原因之一。
                        # viewkey 仅刮削阶段使用；无 viewkey 的影片刮削时会优雅跳过。
                        try:
                            rel = file_path.relative_to(media_dir)
                        except ValueError:
                            rel = Path(file_path.name)
                        code = re.sub(
                            r"[^\w\-]", "_", rel.with_suffix("").as_posix()
                        )
                    result["matched"] += 1

                    # 检查是否已存在（内存判重，避免 N+1 查询）
                    if code in existing_codes:
                        continue
                    existing_codes.add(code)

                    # 写入新影片记录
                    new_movie = PornhubMovie(
                        code=code,
                        title=Path(file_name).stem,
                        actor=actor_name,
                        file_path=str(file_path),
                        file_size=_file_size(file_path),
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1

                    # 增量提交：整盘首扫影片量可达数万，若只在全部扫完后一次 commit，
                    # 扫描超时/中断时已 add 未 commit 的数据会整体丢失（PORNHUB 一直
                    # 空库的另一个原因）。每 200 条落地一次，中断也能保住已扫盘符的数据。
                    if result["scanned"] % 200 == 0:
                        await session.commit()
                        logger.info(f"[pornhub] 增量提交: 已入库 {result['movies_added']} 部")

                    if code:
                        # 并发受限（防整盘扫描时无限制 ensure_future 风暴拖死事件循环）
                        asyncio.ensure_future(
                            self._copy_limited(
                                copy_video_assets_to_data_dir(str(file_path), code, "pornhub")
                            )
                        )

                    if actor_name:
                        # 多演员文件夹名（Anna + Sunny）按 + / & / , 拆分，逐个建表，
                        # 与影片刮削口径对齐，避免 "Anna + Sunny" 与 "Anna" 分裂
                        for single_name in _split_actor_names(actor_name):
                            result["actors"].setdefault(single_name, nationality)

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
                    existing_actor.movie_count += 1
                else:
                    existing_actor.movie_count += 1

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
          M:\\爱沙尼亚\\[Channel] Diana Rider\\videofile.mp4  ← 上级目录为国籍
          M:\\美国\\videofile.mp4  ← 纯国籍目录，无演员

        优先使用离文件最近的目录名作为演员候选。
        如果最内层目录是纯国籍名，则向上回溯一级寻找演员名。
        """
        try:
            rel_path = Path(file_path).relative_to(media_dir)
        except ValueError:
            return None, None

        # 取文件所在目录（跳过文件本身）
        parent_dir = rel_path.parent

        if parent_dir == Path("."):
            return None, None

        # 从最内层目录开始检查
        parts = list(parent_dir.parents) if parent_dir != Path(".") else []
        # parts[0] = 祖父目录, parts[-1] = 最顶层
        # 我们要检查：最内层目录 -> 其父目录 -> 再上一级
        inner_name = parent_dir.name if parent_dir != Path(".") else None
        if not inner_name:
            return None, None

        # 第1步：检查最内层目录
        actor_name, nationality = extract_actor_and_nationality(inner_name)

        # 如果最内层是纯国籍目录（如"美国"、"俄罗斯"），
        # 说明这个目录本身只是国籍分类，不包含演员信息
        if not actor_name and nationality:
            # 向上检查是否有演员目录
            if parent_dir.parent != Path("."):
                upper_name = parent_dir.parent.name
                upper_actor, upper_nationality = extract_actor_and_nationality(upper_name)
                # 如果上级目录提取到了演员名，使用上级的
                if upper_actor:
                    return upper_actor, nationality
            return None, nationality

        # 第2步：检查上级目录名补充国籍
        # M:\\爱沙尼亚\\[Channel] Diana Rider\\video.mp4
        # → 内层: actor_name="Diana Rider", nationality=None
        # → 祖父目录: "爱沙尼亚" → nationality="爱沙尼亚"
        if not nationality and parent_dir.parent != Path("."):
            grandparent_name = parent_dir.parent.name
            if grandparent_name in _NATIONALITY_PATTERNS:
                nationality = _NATIONALITY_PATTERNS[grandparent_name]

        return actor_name, nationality
