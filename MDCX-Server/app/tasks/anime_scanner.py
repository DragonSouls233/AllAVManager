"""
日本里番模块扫描器
目录结构：J:\\动漫\\{年}\\...\\*.{mp4,mkv,...}

两种真实文件名格式（已实地核对 2012~2025 全量）：
  1) 老格式（约 2012–2024，已刮削完整）：
       [制作商] 标题 [DVD番号CODE].mkv/.mp4
       例：[BOOTLEG] ネトラレヅマ ～礼子～[无修正] [DBLG-9456].mkv
       → 首括号=制作商，末括号=番号(如 DBLG-9456)，中间=标题
  2) 新格式（2025，未刮削）：
       [YYMMDD][制作商]标题[制作人员].cht.mp4
       例：[251010][Queen Bee]寝取られた爆乳妻たち 後編[ガガーリン吉].cht.mp4
       → 首括号=日期(6位)，次括号=制作商，末括号=人员，无 DVD 番号

设计要点：
- 元数据优先读同名 .nfo（Jellyfin 格式，老年份 NFO 含 studio/set/plot/premiered/runtime/genre）。
- 文件名解析兜底（2025 未刮削 → NFO 很瘦，靠文件名拿制作商/系列/集数）。
- 幂等：以 code 为唯一键，已存在跳过 → 天然「老的只读 NFO」。
- 可选 getchu 在线补（config.online_enrich，默认关），best-effort。
"""
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from app.tasks.base_scanner import BaseScanner, copy_video_assets_to_data_dir
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 视频扩展名
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".wmv", ".ts", ".iso", ".mov", ".flv",
              ".webm", ".m2ts", ".mpg", ".mpeg", ".m4v", ".rmvb"}

# 标题里要剔除的修饰标签（出现在方括号内或作为后缀）
_TITLE_NOISE = re.compile(
    r"\[?(无修正|无码|有码|中文字幕|chs|cht|sc|tc|jap|eng|kor|高清|HD|BD|DVD|1080p|720p|480p|HEVC|x264|x265|H\.264|REMUX|WEBRip|WEB-DL|BluRay|校园|里番|アダルト)\]?",
    re.IGNORECASE,
)

# 篇章指示词 → 集数（无数字时使用）
_PART_MAP = {
    "前編": 1, "前编": 1,
    "中編": 2, "中编": 2,
    "後編": 3, "后编": 3,
    "完結編": 4, "完结编": 4,
    "最終話": 5, "最终话": 5, "最終回": 5, "最终回": 5,
}

# DVD 番号模式（如 DBLG-9456 / ACDDL-1006 / DCLB-9326 / PXY-10063 / GBR-006）
_CODE_PATTERN = re.compile(r"^[A-Za-z]{2,6}-?\d{2,6}$")

# 日期模式（6 位数字 YYMMDD）
_DATE_PATTERN = re.compile(r"^\d{6}$")


def _clean_title(s: str) -> str:
    """去掉标题里的方括号标签与修饰词，得到干净标题。"""
    # 去掉所有 [xxx]
    s = re.sub(r"\[[^\]]*\]", " ", s)
    # 去掉常见修饰词（含可能残留的中括号）
    s = _TITLE_NOISE.sub(" ", s)
    # 去掉 .cht 等字幕后缀（已在 stem 处理，双保险）
    s = re.sub(r"\.(cht|chs|sc|tc|jap|eng|kor)$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" -_　")
    return s


def _file_size(path: Path) -> int:
    """网络盘上一次 stat 取大小（容错），避免 exists()+stat() 两次 IO"""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def parse_anime_filename(filename: str) -> dict:
    """解析里番文件名 → {fmt, date, maker, code, staff, title}

    fmt: 'dated' (2025 新格式) | 'coded' (老格式，含 DVD 番号) | 'plain'
    """
    stem = Path(filename).stem
    # 去掉 .cht 之类的字幕标签后缀
    m = re.match(r"^(.*?)\.([A-Za-z]{2,4})$", stem)
    if m and m.group(2).lower() in {"cht", "chs", "sc", "tc", "jap", "eng", "kor"}:
        stem = m.group(1)

    brackets = re.findall(r"\[([^\]]+)\]", stem)

    fmt = "plain"
    date = None
    maker = None
    code = None
    staff = None

    if brackets:
        first = brackets[0]
        if _DATE_PATTERN.fullmatch(first):
            # 新格式：首括号=日期
            fmt = "dated"
            date = _parse_yymmdd(first)
            if len(brackets) > 1:
                maker = brackets[1]
            if len(brackets) > 2:
                staff = brackets[-1]
        else:
            # 老格式：首括号=制作商；末括号若像番号则取为 code
            maker = first
            if len(brackets) > 1:
                last = brackets[-1]
                if _CODE_PATTERN.fullmatch(last):
                    code = last
                    fmt = "coded"
                else:
                    staff = last

    # 标题 = 去掉所有方括号后的剩余文本，再清洗
    title = _clean_title(stem)
    return {"fmt": fmt, "date": date, "maker": maker, "code": code,
            "staff": staff, "title": title}


def _parse_yymmdd(s: str) -> str | None:
    try:
        yy = int(s[:2]); mm = int(s[2:4]); dd = int(s[4:6])
    except ValueError:
        return None
    year = 1900 + yy if yy >= 90 else 2000 + yy
    if 1 <= mm <= 12 and 1 <= dd <= 31:
        return f"{year}-{mm:02d}-{dd:02d}"
    return None


def parse_series_episode(title: str) -> tuple[str, int | None]:
    """从标题解析系列名与集数。返回 (series_name, episode)"""
    ep: int | None = None
    t = title

    # 第N話 / 第N话
    m = re.search(r"第\s*(\d+)\s*話", t) or re.search(r"第\s*(\d+)\s*话", t)
    if m:
        ep = int(m.group(1)); t = re.sub(r"第\s*\d+\s*話", "", t)
        t = re.sub(r"第\s*\d+\s*话", "", t)
    else:
        # 第N巻 / 第N卷
        m = re.search(r"第\s*(\d+)\s*[巻卷]", t)
        if m:
            ep = int(m.group(1)); t = re.sub(r"第\s*\d+\s*[巻卷]", "", t)
        else:
            # File.NN / file.NN（如 File.02）
            m = re.search(r"[Ff]ile\.(\d+)", t)
            if m:
                ep = int(m.group(1)); t = re.sub(r"[Ff]ile\.\d+", "", t)
            else:
                # #N
                m = re.search(r"#\s*(\d+)", t)
                if m:
                    ep = int(m.group(1)); t = re.sub(r"#\s*\d+", "", t)
                else:
                    # 前編/中編/後編 等篇章指示词
                    for k, v in _PART_MAP.items():
                        if k in t:
                            ep = v; t = t.replace(k, ""); break

    series = _clean_title(t)
    if not series:
        series = title  # 兜底：整标题当系列名
    return series, ep


def parse_nfo(nfo_path: Path) -> dict:
    """解析 Jellyfin/Kodi NFO → 富字段字典。任何异常返回空字典。"""
    out: dict = {}
    try:
        text = nfo_path.read_text(encoding="utf-8", errors="ignore")
        root = ET.fromstring(text)
    except Exception as e:
        logger.debug(f"[anime] NFO 解析失败 {nfo_path.name}: {e}")
        return out

    def txt(tag: str) -> str | None:
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    # 制作商（studio 字段常含 JP 全名，如 ミルキーズピクチャーズ/BOOTLEG）
    studio = txt("studio")
    if studio:
        out["studio"] = studio

    # 系列（<set><name>）
    set_el = root.find("set")
    if set_el is not None:
        name_el = set_el.find("name")
        if name_el is not None and name_el.text and name_el.text.strip():
            out["set_name"] = name_el.text.strip()

    # 简介
    plot = txt("plot")
    if plot:
        out["plot"] = plot

    # 发行日期
    premiered = txt("premiered") or txt("releasedate")
    if premiered:
        out["premiered"] = premiered[:10]

    # 年份
    year = txt("year")
    if year and year.isdigit():
        out["year"] = int(year)

    # 时长（分钟）
    runtime = txt("runtime")
    if runtime and runtime.isdigit():
        out["runtime"] = int(runtime)

    # 类型
    genres = [g.text.strip() for g in root.findall("genre") if g.text and g.text.strip()]
    if genres:
        out["genres"] = genres

    # 标题（优先 originaltitle，更干净）
    ot = txt("originaltitle")
    if ot:
        out["title"] = _clean_title(ot)
    else:
        ti = txt("title")
        if ti:
            out["title"] = _clean_title(ti)

    # 评分
    rating = txt("rating")
    if rating:
        try:
            out["rating"] = float(rating)
        except ValueError:
            pass

    return out


def generate_anime_code(parsed: dict, stem: str) -> str:
    """生成稳定唯一 code：优先用 DVD 番号，否则用文件名哈希。"""
    if parsed.get("code"):
        return "ANI-" + parsed["code"]
    return "ANI-" + hashlib.sha256(stem.encode("utf-8")).hexdigest()[:12].upper()


def _find_poster(video_path: Path) -> Path | None:
    """查找同目录海报：{stem}-poster.* / {stem}-fanart.* / {stem}.{jpg,png}。

    2026-08-08: 网络盘下逐 exists 探测最多 16 次 stat，改为一次 listdir 取目录列表内存匹配。
    """
    stem = video_path.stem
    parent = video_path.parent
    try:
        entries = set(os.listdir(parent))
    except OSError:
        return None
    for suffix in ("-poster", "-fanart", "-cover", ""):
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if stem + suffix + ext in entries:
                return parent / (stem + suffix + ext)
    return None


def _find_nfo(video_path: Path) -> Path | None:
    """找同目录 NFO（一次 listdir 替代多次 stat）"""
    stem = video_path.stem
    parent = video_path.parent
    try:
        entries = set(os.listdir(parent))
    except OSError:
        return None
    for cand in (stem + ".nfo", stem + ".cht.nfo"):
        if cand in entries:
            return parent / cand
    return None


class AnimeScanner(BaseScanner):
    """日本里番扫描器"""

    def __init__(self, media_dirs: list[str], config: dict | None = None):
        super().__init__("anime", media_dirs)
        self.video_extensions = VIDEO_EXTS
        self.config = config or {}
        # 扫描只做本地入库：从 NFO/文件名解析元数据写库，绝不发起网络请求。
        # 网络刮削（getchu）仅由用户显式触发的「指定目录刮削 / 单部刮削 / 批量刮削pending」执行，
        # 详见 app/services/anime_scrape_service.py 与 app/api/routes/anime_routes.py。

    async def scan(self) -> dict:
        results = {"total": 0, "scanned": 0, "movies_added": 0,
                   "series": set(), "makers": set(), "errors": []}
        for media_dir in self.media_dirs:
            try:
                dir_result = await self._scan_directory(Path(media_dir))
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["movies_added"] += dir_result.get("movies_added", 0)
                results["series"].update(dir_result["series"])
                results["makers"].update(dir_result["makers"])
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"[anime] 扫描目录失败 {media_dir}: {e}")

        results["series"] = sorted(results["series"])
        results["makers"] = sorted(results["makers"])
        return results

    async def _scan_directory(self, media_dir: Path) -> dict:
        result = {"total": 0, "scanned": 0, "movies_added": 0, "series": set(), "makers": set()}

        from app.db.module_db import ModuleDatabase
        from app.db.anime_models import AnimeMovie, AnimeSeries, AnimeStudio
        from sqlalchemy import select

        db = ModuleDatabase.get_instance("anime")
        session = await db.get_session()
        # 2026-08-08: studio/series 查询缓存——11.7 万文件目录下逐文件 DB 查询是超时主因之一
        _studio_cache: dict[str, int] = {}
        _series_cache: dict[str, int] = {}
        try:
            existing_codes: set[str] = set(
                (await session.execute(select(AnimeMovie.code))).scalars().all()
            )
            existing_series: set[str] = set(
                (await session.execute(select(AnimeSeries.name))).scalars().all()
            )

            walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
            batch_counter = 0  # 2026-08-08: 增量提交——每批 100 部 commit，超时也不丢已扫描部分
            for root, dirs, files in walk_entries:
                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue
                    file_path = Path(root) / file_name
                    result["total"] += 1

                    parsed = parse_anime_filename(file_name)
                    code = generate_anime_code(parsed, file_path.stem)
                    if code in existing_codes:
                        continue  # 已存在 → 跳过（老的只读）
                    existing_codes.add(code)

                    # NFO 富字段（老年份已刮削）
                    nfo_path = _find_nfo(file_path)
                    nfo = parse_nfo(nfo_path) if nfo_path else {}

                    # 系列：优先 NFO <set>，否则文件名派生
                    series_name, episode = parse_series_episode(parsed["title"])
                    if nfo.get("set_name"):
                        series_name = nfo["set_name"]

                    # 制作商：文件名品牌 → maker；NFO studio → studio（更全的 JP 名）
                    maker = parsed["maker"]
                    studio = nfo.get("studio") or maker

                    # 标题：NFO 优先，否则文件名清洗
                    title = nfo.get("title") or parsed["title"] or file_path.stem

                    release_date = nfo.get("premiered") or parsed["date"]

                    # 制作商 → Studio 记录（缓存避免逐文件查询）
                    studio_id = None
                    if maker:
                        result["makers"].add(maker)
                        if maker in _studio_cache:
                            studio_id = _studio_cache[maker]
                        else:
                            studio_row = (await session.execute(
                                select(AnimeStudio).where(AnimeStudio.name == maker)
                            )).scalar_one_or_none()
                            if not studio_row:
                                studio_row = AnimeStudio(name=maker, movie_count=0)
                                session.add(studio_row)
                                await session.flush()
                            _studio_cache[maker] = studio_row.id
                            studio_id = studio_row.id

                    # 系列 → Series 记录（缓存避免逐文件查询）
                    series_id = None
                    if series_name:
                        result["series"].add(series_name)
                        if series_name not in existing_series:
                            srow = AnimeSeries(name=series_name, movie_count=0)
                            if studio_id:
                                srow.studio_id = studio_id
                            session.add(srow)
                            await session.flush()
                            existing_series.add(series_name)
                            _series_cache[series_name] = srow.id
                            series_id = srow.id
                        elif series_name in _series_cache:
                            series_id = _series_cache[series_name]
                        else:
                            srow = (await session.execute(
                                select(AnimeSeries).where(AnimeSeries.name == series_name)
                            )).scalar_one_or_none()
                            series_id = srow.id if srow else None
                            if series_id:
                                _series_cache[series_name] = series_id

                    genres_json = json.dumps(nfo.get("genres", []), ensure_ascii=False) if nfo.get("genres") else None

                    new_movie = AnimeMovie(
                        code=code,
                        title=title,
                        original_title=nfo.get("title"),
                        release_date=release_date,
                        duration=nfo.get("runtime"),
                        rating=nfo.get("rating"),
                        plot=nfo.get("plot"),
                        genre=genres_json,
                        director=parsed["staff"],
                        maker=maker,
                        studio=studio,
                        studio_id=studio_id,
                        series=series_name,
                        series_id=series_id,
                        episode=episode,
                        file_path=str(file_path),
                        # 网络盘上一次 stat 即可（exists()+stat() 两次 IO 翻倍耗时）
                        file_size=_file_size(file_path),
                        source="nfo" if nfo else "filename",
                        status="completed" if nfo else "pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1

                    # 复制 NFO + 视频目录资源到数据中心（限并发，防大目录下请求风暴拖垮扫描）
                    asyncio.ensure_future(
                        self._copy_limited(
                            copy_video_assets_to_data_dir(str(file_path), code, "anime")
                        )
                    )
                    # 复制海报（同目录 -poster/-fanart）
                    asyncio.ensure_future(self._copy_limited(self._copy_poster(str(file_path), code)))

                    # 增量提交：每 100 部 commit 一次——即使后续超时，已扫描部分也已入库，
                    # 下次扫描通过 existing_codes 跳过（幂等续扫）
                    batch_counter += 1
                    if batch_counter % 100 == 0:
                        await session.commit()
                        logger.info(f"[anime] 增量提交: 已入库 {result['movies_added']} 部")

            await session.commit()
        finally:
            await session.close()

        return result

    # 2026-08-08: copy 任务并发限制——无限制 ensure_future 会淹没事件循环拖垮扫描主流程（600s 超时根因）
    _COPY_SEM: Optional[asyncio.Semaphore] = None

    async def _copy_limited(self, coro):
        """并发受限地执行复制任务"""
        if AnimeScanner._COPY_SEM is None:
            AnimeScanner._COPY_SEM = asyncio.Semaphore(5)
        try:
            async with AnimeScanner._COPY_SEM:
                await asyncio.wait_for(coro, timeout=60)
        except Exception:
            pass  # 复制失败不影响扫描主流程

    async def _copy_poster(self, video_path: str, code: str) -> None:
        try:
            poster = _find_poster(Path(video_path))
            if not poster:
                return
            from app.config.manager import get_config_manager
            data_dir = get_config_manager().computed.data_dir
            target_dir = Path(data_dir) / "movies" / "anime" / code
            target_dir.mkdir(parents=True, exist_ok=True)
            dst = target_dir / "poster.jpg"
            if dst.exists():
                return
            import shutil
            shutil.copy2(poster, dst)
            logger.info(f"[anime] 复制海报: {poster.name} → {dst}")
        except Exception as e:
            logger.debug(f"[anime] 海报复制失败（忽略）: {e}")
