"""
JAV 有码模块扫描器

功能：
- 从文件名提取标准 JAV 番号（使用 number.py extract_number 支持 -C/-UC 后缀）
- 从目录名提取演员（使用 folder_actor.py）
- 写入 jav.db
"""

import asyncio
import os
import re
from pathlib import Path

from app.scraper.folder_actor import extract_actor_from_folder
from app.tasks.base_scanner import BaseScanner, copy_video_assets_to_data_dir, iter_media_entries, _file_size, detect_version_flags, find_local_cover
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 🔴 2026-10-05 修复（实测 jav.db 有 256 条 pending 的 output_dir 全空，
#    但磁盘上 movie.nfo 266/266、poster.jpg 257/266 全部存在）：
#    扫描器原先只在「新番号」时插 pending 行，且**无条件** status="pending"，
#    对已存在的 pending 行也从不回填 ⇒
#    ① 明明磁盘上已有刮削好的 NFO/海报，却被标成待刮削；
#    ② 批量刮削每次都把它们重新选中、反复重刮，却永不退出 pending 池
#       （"缺口 289 刮了三次还是 289"）。
#    现在改为：**同目录已有 NFO ⇒ 第一时间导入 NFO 富字段并直接标 scraped**；
#    对已存在的 pending 行同样就地回填（不新增行、不动已刮好的真实值）。
# ══════════════════════════════════════════════════════════════════════


def _find_local_nfo(code: str, dir_path: Path) -> Path | None:
    """找该番号在源目录（或已复制到数据中心）的 movie.nfo。"""
    from app.config.manager import DATA_DIR

    candidates = [
        dir_path / "movie.nfo",
        Path(DATA_DIR) / "movies" / "jav" / code / "movie.nfo",
    ]
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _nfo_updates(meta: dict, code: str, data_dir_movie: Path | None) -> dict:
    """由 NFO 解析结果构造可直接 setattr 到 JavMovie 的字段字典。

    口径与 anime_scanner 一致；只产出「NFO 里确实有值」的键，
    调用方负责只填空位（不覆盖已有真实值）。
    """
    import json as _json

    genres = meta.get("genre") or []
    tags = meta.get("tag") or []
    upd: dict = {}
    if meta.get("title"):
        upd["title"] = meta["title"]
    if meta.get("original_title"):
        upd["original_title"] = meta["original_title"]
    if meta.get("plot"):
        upd["plot"] = meta["plot"]
    if meta.get("plot_short"):
        upd["plot_short"] = meta["plot_short"]
    if meta.get("release_date"):
        upd["release_date"] = meta["release_date"]
    if meta.get("duration"):
        upd["duration"] = meta["duration"]
    if meta.get("rating") is not None:
        upd["rating"] = meta["rating"]
    if genres:
        upd["genre"] = ",".join(genres)
    if tags:
        upd["tag"] = _json.dumps(tags, ensure_ascii=False)
    actors = meta.get("actors") or []
    if actors:
        upd["actor"] = ",".join(actors)
    if meta.get("studio"):
        upd["studio"] = meta["studio"]
    if meta.get("series"):
        upd["series"] = meta["series"]
    if data_dir_movie is not None:
        upd["output_dir"] = str(data_dir_movie)
        poster = data_dir_movie / "poster.jpg"
        if poster.is_file():
            upd["cover_url"] = str(poster)
    upd["source"] = "nfo"
    return upd


def _apply_nfo_to_movie(movie, meta: dict, code: str, data_dir_movie: Path | None) -> bool:
    """把 NFO 字段写进 movie：只填「当前为空 / 仍是占位」的列，绝不覆盖真实值。

    返回 True 表示该影片已被认定为「刮削完成」（存在有效 NFO）。
    """
    if not meta or not meta.get("title"):
        return False
    upd = _nfo_updates(meta, code, data_dir_movie)
    cur_actor = (getattr(movie, "actor", None) or "").strip()
    changed = False
    for key, value in upd.items():
        if not hasattr(movie, key):
            continue
        old = getattr(movie, key)
        # 占位标题（= 文件名/番号）视为空，可被 NFO 覆盖
        if key == "title" and old:
            if not _is_placeholder_title(old, code):
                continue
        elif key == "actor":
            if cur_actor and cur_actor.upper() != code.upper():
                continue
        elif old not in (None, "", 0):
            continue
        setattr(movie, key, value)
        changed = True
    return True


def _is_placeholder_title(title: str | None, code: str) -> bool:
    """占位标题判定：空 / 与番号相同 / 本质只是番号 token（扫描器塞的文件名）。"""
    if not title:
        return True
    t = str(title).strip()
    if not t or t.upper() == code.upper():
        return True
    residue = _CODE_TOKEN_RE.sub(" ", t)
    residue = re.sub(r"[\s\[\]\(\){}<>_\-.,!~+#@$%^&*|\\:;'\"/]+", " ", residue)
    words = [w for w in residue.split() if any(ch.isalpha() for ch in w)]
    if not words:
        return True
    return sum(len(w) for w in words) <= 2


_CODE_TOKEN_RE = re.compile(
    r"[A-Za-z]{2,10}[-_]?\d{2,6}(?:[-_]?[A-Za-z]{1,4})?|FC2[-_]?(?:PPV[-_]?)?\d{5,7}",
    re.IGNORECASE,
)

# JAV 工作室黑名单（不识别为演员的文件夹名）
STUDIO_BLACKLIST = {
    "R18", "premium", "SOD", "IDEAPOCKET", "MOODYZ", "S1", "S1NO1",
    "MADONNA", "KA", "kawaii", "kirakira", "wanz", "MGS", "DMM",
    "FC2", "HEYZO", "CARIB", "1PONDO", "MKD", "JAV", "高清", "HD",
    "有码", "无码", "国产", "欧美", "合集", "精选", "新建文件夹",
    "unknown", "Unknow", "Other", "others",
}

# JAV 工作室自动识别（用于填充 studio 字段）
STUDIO_MAP = {
    "S1": "S1 NO.1 STYLE",
    "IDEAPOCKET": "IDEAPOCKET",
    "MOODYZ": "MOODYZ",
    "MADONNA": "MADONNA",
    "PREMIUM": "PREMIUM",
    "KAWAII": "kawaii*",
    "KIRAKIRA": "kira☆kira",
    "WANZ": "WANZ FACTORY",
    "SOD": "SOD",
    "R18": "R18",
    "PREMIUM": "PREMIUM",
}


def is_valid_jav_code(code: str) -> bool:
    """判断是否为标准 JAV 番号"""
    if not code:
        return False
    # 标准 JAV: 字母-数字，如 ABC-123
    jav_pattern = re.compile(r'^[A-Za-z]{2,10}-\d{2,5}$', re.IGNORECASE)
    return bool(jav_pattern.match(code))


class JavScanner(BaseScanner):
    """JAV 有码模块扫描器"""

    def __init__(self, media_dirs: list[str], config: dict | None = None):
        super().__init__("jav", media_dirs)
        self.config = config or {}
        self.actor_blacklist = set(self.config.get("blacklist", [])) | STUDIO_BLACKLIST
        self.folder_depth = self.config.get("folder_depth", 2)

    async def scan(self) -> dict:
        """扫描有码媒体目录并落库"""
        results = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "actors": set(), "errors": []}

        logger.info(f"[jav] 扫描启动: media_dirs={[str(d) for d in self.media_dirs]}")
        for media_dir in self.media_dirs:
            try:
                logger.info(f"[jav] 开始扫描目录: {media_dir}")
                dir_result = await self._scan_directory(media_dir)
                logger.info(
                    f"[jav] 目录扫描完成: {media_dir} 共发现 {dir_result['total']} 个文件，"
                    f"新增 {dir_result.get('movies_added', 0)}"
                )
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["matched"] += dir_result["matched"]
                results["movies_added"] += dir_result.get("movies_added", 0)
                if dir_result.get("actors"):
                    results["actors"].update(dir_result["actors"])
            except Exception as e:
                # 2026-08-18: 完整性冲突类(UNIQUE 重复)经内层回滚已能跳过,这里降级
                # 为 warning,避免每次跨盘重名扫描刷 4 条 ERROR 干扰日志。其他错误
                # 仍保留 ERROR 级别。
                msg = f"扫描目录失败 {media_dir}: {e}"
                if "UNIQUE constraint failed" in str(e):
                    logger.warning(msg + " (重复番号已跳过)")
                else:
                    logger.error(msg)
                results["errors"].append(f"{media_dir}: {e}")

        # 同步演员表
        if results["actors"]:
            await self._sync_actors(list(results["actors"]))
            await self._update_actor_counts()

        results["actors"] = list(results["actors"])
        logger.info(
            f"[jav] 扫描完成: 共发现 {results['total']} 个文件，新增 {results['movies_added']}，"
            f"错误 {len(results['errors'])} 个"
        )
        return results

    async def _scan_directory(self, media_dir: Path) -> dict:
        """扫描单个媒体目录并写入数据库"""
        result = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "actors": set()}
        media_dir = Path(media_dir)

        from app.db.module_db import ModuleDatabase
        from app.db.jav_models import JavMovie
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        db = ModuleDatabase.get_instance("jav")
        session = await db.get_session()
        try:
            # 性能修复：一次性载入已存在番号，避免"每个视频文件一次 SELECT"的 N+1 查询。
            # 旧写法在 8000+ 文件的库上要跑 8000 次 await 查询，
            # 极易触发 scan_control 的 600s 超时 → 扫描失败 → 新增文件永远扫不进来。
            existing_codes: set[str] = set(
                (await session.execute(select(JavMovie.code))).scalars().all()
            )
            # 🔴 2026-10-05：同时载入 status='pending' 的行，用于「已刮好但没登记」
            # 的就地回填（避免这些行永远停在 pending 被反复重刮）。
            pending_rows = (
                await session.execute(
                    select(JavMovie).where(JavMovie.status == "pending")
                )
            ).scalars().all()
            pending_by_code: dict[str, object] = {m.code: m for m in pending_rows if m.code}
            walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
            pending_movies: list[JavMovie] = []
            for root, dirs, files in walk_entries:
                # 收集当前目录的演员信息
                dir_path = Path(root)

                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = dir_path / file_name
                    result["total"] += 1

                    # 使用统一番号提取（从 number.py 或内置逻辑）
                    code = self._extract_code(file_name, dir_path)
                    if not code:
                        continue
                    result["matched"] += 1

                    # 🔴 2026-10-05：已存在且仍是 pending ⇒ 若磁盘上已有 NFO，
                    # 说明它早就刮好了，只是没写回库。**就地回填并转 scraped**，
                    # 绝不能 continue 跳过 —— 那正是"缺口永不消失"的根因。
                    if code in existing_codes:
                        known = pending_by_code.get(code)
                        if known is not None:
                            nfo_path = _find_local_nfo(code, dir_path)
                            if nfo_path is None:
                                continue
                            try:
                                from app.utils.nfo_fields import parse_nfo_fields

                                meta = parse_nfo_fields(nfo_path)
                            except Exception as e:
                                logger.debug(
                                    "[jav] 回填 NFO 失败 %s: %s", code, e
                                )
                                continue
                            from app.config.manager import DATA_DIR

                            data_movie = Path(DATA_DIR) / "movies" / "jav" / code
                            if _apply_nfo_to_movie(known, meta, code, data_movie):
                                known.status = "scraped"
                                result["movies_backfilled"] = (
                                    result.get("movies_backfilled", 0) + 1
                                )
                                logger.info(
                                    "[jav] 回填已刮削影片（磁盘已有 NFO）: %s", code
                                )
                        continue
                    existing_codes.add(code)

                    # 提取演员（素人目录中的文件不走文件夹名提取）
                    is_amateur = False
                    try:
                        from app.config.manager import get_config
                        cfg = get_config()
                        amateur_dirs = getattr(cfg.modules.jav, "amateur_media_dirs", None) or []
                        fp = file_path.resolve()
                        for d in amateur_dirs:
                            base = Path(d).resolve()
                            if base in fp.parents or fp == base:
                                is_amateur = True
                                break
                    except Exception:
                        pass

                    folder_actors = [] if is_amateur else self._get_folder_actors(file_path, media_dir)
                    actor_str = ",".join(folder_actors) if folder_actors else None
                    if folder_actors:
                        result["actors"].update(folder_actors)

                    # 检测版本标记（-C 中文 / -U 无码 / -UC 无码中文 / -Leak 破解 / -4K）
                    flags = detect_version_flags(file_name)
                    is_chinese = flags["is_chinese"]
                    is_uncensored = flags["is_uncensored"]

                    # 提取工作室
                    studio = self._detect_studio(code, dir_path, media_dir)

                    # 从同目录查找本地封面图片
                    # 兼容通用名（poster.jpg）与番号命名（{code}-poster.jpg）两类
                    cover_url = None
                    try:
                        cover_url = find_local_cover(file_path, code)
                    except Exception:
                        pass
                    if not cover_url:
                        dir_path_obj = file_path.parent
                        for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg"]:
                            img_path = dir_path_obj / img_name
                            if img_path.exists():
                                cover_url = str(img_path)
                                break

                    # 🔴 2026-10-05：同目录已有 NFO ⇒ 该片其实早已刮好，
                    # 必须第一时间导入 NFO 富字段并直接标 scraped，
                    # 不能无条件塞进 pending 池（否则批量刮削会无限重刮它）。
                    nfo_meta = None
                    nfo_path = _find_local_nfo(code, file_path.parent)
                    if nfo_path is not None:
                        try:
                            from app.utils.nfo_fields import parse_nfo_fields

                            nfo_meta = parse_nfo_fields(nfo_path)
                        except Exception as e:
                            logger.debug("[jav] 解析 NFO 失败 %s: %s", code, e)

                    has_nfo = bool(nfo_meta and nfo_meta.get("title"))

                    # 写入新影片记录
                    new_movie = JavMovie(
                        code=code,
                        title=Path(file_name).stem,
                        file_path=str(file_path),
                        file_size=_file_size(file_path),
                        actor=actor_str,
                        studio=studio,
                        cover_url=cover_url,
                        is_chinese=is_chinese,
                        is_uncensored=is_uncensored,
                        is_mosaic=not is_uncensored,
                        is_leak=flags["is_leak"],
                        is_4k=flags["is_4k"],
                        source="nfo" if has_nfo else "folder",
                        status="scraped" if has_nfo else "pending",
                    )
                    if has_nfo:
                        from app.config.manager import DATA_DIR

                        _apply_nfo_to_movie(
                            new_movie,
                            nfo_meta,
                            code,
                            Path(DATA_DIR) / "movies" / "jav" / code,
                        )
                    session.add(new_movie)
                    pending_movies.append(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1

                    # 将视频目录的 NFO + 封面复制到数据中心目录
                    # 并发受限（防整盘扫描时无限制 ensure_future 风暴拖死事件循环）
                    if code:
                        asyncio.ensure_future(
                            self._copy_limited(
                                copy_video_assets_to_data_dir(str(file_path), code, "jav")
                            )
                        )

            try:
                await session.commit()
            except IntegrityError:
                # 并发扫描（自动扫描 + 手动触发 + 目录监听可能同时跑）时，各 session
                # 各自查 existing_codes 看不到对方已插入的番号，commit 会撞 UNIQUE。
                # 回滚后逐条重插，冲突的跳过，避免整个目录扫描失败丢数据。
                logger.warning(
                    f"[jav] 目录 {media_dir} 批量提交撞 UNIQUE 冲突，回滚后逐条重插跳过重复番号"
                )
                await session.rollback()
                skipped_dup = 0
                for m in pending_movies:
                    session.add(m)
                    try:
                        await session.flush()
                    except IntegrityError:
                        await session.rollback()
                        skipped_dup += 1
                await session.commit()
                result["movies_added"] -= skipped_dup
                if skipped_dup:
                    logger.warning(
                        f"[jav] 目录 {media_dir} 跳过 {skipped_dup} 个重复番号（并发扫描冲突）"
                    )
        finally:
            await session.close()

        return result

    def _extract_code(self, file_name: str, file_dir: Path) -> str | None:
        r"""从文件名提取标准 JAV 番号

        🔴 2026-10-05：旧实现只用**自带的简易正则** ``[A-Za-z]{2,6}-\d{2,5}``，
        该正则要求番号**以字母开头**，于是素人厂牌番号的前导数字被整段丢掉：
          300MIUM-1437.mp4 -> MIUM-1437   （真实番号 300MIUM-1437）
          200GANA-3426.mp4 -> GANA-3426
          259LUXU-1602.mp4 -> LUXU-1602
        结果这些片以错误番号入库、按错误番号搜源站，实测会刮到**完全无关的另一部片**
        （服务器实证：`LUXU-1602` 刮出「かれん&さや」，而 `259LUXU-1602` 才是真片）。

        现在改为**优先走全仓统一的 `app.scraper.number.extract_number`**
        （它已支持素人番号、FC2 紧凑写法、方括号 token 等，且 2026-10-05 修好了
        素人番号丢前导数字的问题），失败才回退旧的简易正则。
        """
        stem = Path(file_name).stem

        # ① 统一番号提取（唯一真相源），文件名优先
        try:
            from app.scraper.number import extract_number
            result = extract_number(file_name)
            if result.number and result.number.strip():
                return result.number.strip()
        except Exception as exc:  # noqa: BLE001 - 提取失败则回退旧逻辑
            logger.debug("统一番号提取失败，回退旧正则 [%s]: %s", file_name, exc)

        # ② 回退：旧简易正则（字母开头）
        patterns = [
            r'([A-Za-z]{2,10}-\d{2,5})(?:[-_.\s]?[CUc]?[UCuc]?)?$',
            r'\[([A-Za-z]{2,10}-\d{2,5})\]',
        ]

        for pattern in patterns:
            match = re.search(pattern, stem)
            if match:
                code = match.group(1).upper()
                # 清理残留的尾部分隔符
                code = code.rstrip('-_. ')
                return code

        # 如果文件名无匹配，尝试父目录名
        parent_name = file_dir.name
        for pattern in patterns:
            match = re.search(pattern, parent_name)
            if match:
                code = match.group(1).upper()
                code = code.rstrip('-_. ')
                return code

        return None

    def _detect_studio(self, code: str, file_dir: Path, media_dir: Path) -> str | None:
        """尝试检测工作室"""
        # 从目录名检测
        try:
            rel = file_dir.relative_to(media_dir)
            parts = list(rel.parents) if rel != Path('.') else []
            # 从最外层目录开始匹配
            for p in reversed(parts):
                name = str(p).upper()
                for key in STUDIO_MAP:
                    if key in name:
                        return STUDIO_MAP[key]
        except ValueError:
            pass
        return None

    def _get_folder_actors(self, file_path: Path, media_dir: Path) -> list[str]:
        """从目录路径提取演员"""
        try:
            rel_path = file_path.relative_to(media_dir)
        except ValueError:
            return []

        parts = list(rel_path.parents)[::-1]
        all_actors = []
        seen = set()

        # 检查最近2层目录
        check_folders = []
        for i in range(min(self.folder_depth, len(parts))):
            f = parts[-(i + 1)]
            if f is not None:
                check_folders.append(f)

        for folder in check_folders:
            name = folder.name if hasattr(folder, "name") else str(folder)
            # 跳过日期前缀目录，如 [2020-02-06]...
            if re.match(r'^\[\d{4}-\d{2}-\d{2}\]', name):
                continue
            # 跳过已识别为工作室的目录
            if name.upper() in STUDIO_BLACKLIST:
                continue

            actors = extract_actor_from_folder(
                name,
                blacklist=self.actor_blacklist,
            )
            for actor in actors:
                if actor not in seen:
                    all_actors.append(actor)
                    seen.add(actor)

        return all_actors

    async def _sync_actors(self, actor_names: list[str]):
        """同步演员表"""
        from app.db.module_db import ModuleDatabase
        from app.db.jav_models import JavActor
        from sqlalchemy import select

        # 防污染（2026-08-26）：拒绝长度 ≤2 的短名
        # "AI"/"あさみ"/"しずく" 等短名被当作演员后，在 LIKE 查询中会误匹配大量无关影片。
        actor_names = [n for n in actor_names if len(n) >= 3]

        db = ModuleDatabase.get_instance("jav")
        session = await db.get_session()
        try:
            for name in actor_names:
                existing = await session.execute(select(JavActor).where(JavActor.name == name))
                if not existing.scalar_one_or_none():
                    session.add(JavActor(name=name, source="folder"))
            await session.commit()
        finally:
            await session.close()

    async def _update_actor_counts(self):
        """更新演员表的 movie_count

        2026-10-04：原实现对每个演员跑一次
        ``WHERE actor LIKE '%name%'``，有两个实测问题：

        1. SQLite ``LIKE`` **默认大小写不敏感** ⇒ ``Ruth lee`` 与 ``Ruth Lee``
           各虚增一次（pornhub 库 id=12/201 即是这么来的，且两者都在
           ``movie_actors`` 里 0 行，movie_count 是纯假数据）。
        2. 子串匹配无法区分 ``Anna Cherry`` 与 ``Anna Cherry7``。

        改为走基类的关联表回填 + 精确计数。
        """
        await self._sync_actor_links()
