"""
欧美模块扫描器

参考来源：
- 现有: chinese_scanner.py (扫描器框架)
- P0: mdcx-master/mdcx/crawlers/theporndb.py (站点/品牌识别)
- P0: CommunityScrapers/scrapers/AyloAPI/domains.py (品牌域名映射)

整合说明：
- 扫描框架: 沿用 MDCX BaseScanner
- 文件名识别: 支持品牌前缀匹配（brazzers/bangbros/vixen 等）
- 代理集成: 通过 MDCX 内置代理 (强制)
"""

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.tasks.base_scanner import BaseScanner, copy_video_assets_to_data_dir, iter_media_entries, _file_size
from app.utils.logger import get_logger
from app.utils.nfo_fields import EMPTY_NFO_META, parse_nfo_fields

logger = get_logger(__name__)

# 🔴 已知视频扩展名。绝不能用 Path(name).stem 去扩展名：当文件名本身是
# 「站点.日期.演员」这种无扩展名点分隔命名时，Path 会把最后一个点段当扩展名吃掉
# （如 'pba.16.05.27.jimena.lago' → stem 变成 'pba.16.05.27.jimena'），
# 导致日期前缀识别与演员提取整体错位。故只剥已知视频后缀。
_VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".wmv", ".mov", ".mpg", ".mpeg", ".ts",
    ".flv", ".webm", ".m4v", ".iso", ".rmvb", ".3gp", ".m2ts", ".m2v",
}


def strip_video_ext(name: str) -> str:
    """仅去掉已知的视频扩展名（保留点分隔的命名段）。"""
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base:
        ext = "." + base.rsplit(".", 1)[-1].lower()
        if ext in _VIDEO_EXTS:
            return name[: len(name) - len(ext)]
    return name

# 欧美品牌前缀映射（参考 CommunityScrapers AyloAPI domains.py + vixenNetwork）
# 注意：前缀按匹配优先级排序，长前缀/精确前缀在前，避免短前缀误匹配
WESTERN_SITE_PREFIXES = {
    # ===== Vixen 网络（优先匹配，避免被其他品牌误匹配）=====
    "blackedraw": "Blacked Raw",
    "blacked": "Blacked",
    "tushyraw": "TushyRaw",
    "tushy": "Tushy",
    "vixen": "Vixen",
    "deeper": "Deeper",
    "milfy": "Milfy",
    "wifey": "Wifey",
    "slayed": "Slayed",
    # ===== Aylo 品牌 =====
    "brazzers": "Brazzers",
    "brzzrs": "Brazzers",
    "bangbros": "BangBros",
    "bbros": "BangBros",
    "bb.": "BangBros",  # bb.date.scene 格式
    "realitykings": "Reality Kings",
    "rk": "Reality Kings",
    "mofos": "Mofos",
    "digitalplayground": "Digital Playground",
    "twistys": "Twistys",
    "babes": "Babes",
    # ===== Naughty America（放在 PublicAgent 后面，避免 na 误匹配 publicagent）=====
    "naughtyamerica": "Naughty America",
    "tonightsgirlfriend": "Naughty America",
    "myfriendshotmom": "Naughty America",
    "mysistershotfriend": "Naughty America",
    "thundercock": "Naughty America",
    "mylf": "MYLF",
    # ===== 其他独立品牌 =====
    "publicagent": "PublicAgent",
    "pba.": "PublicAgent",  # PublicAgent 的简写/旧格式
    "hegre": "Hegre",
    "hegreart": "Hegre",
    # ===== Algolia 品牌 =====
    "evilangel": "Evil Angel",
    "adulttime": "Adult Time",
    "puretaboo": "Pure Taboo",
    # ===== TeamSkeet =====
    "teamskeet": "TeamSkeet",
    "brattysis": "BrattySis",
    # ===== 其他 =====
    "playboy": "Playboy",
    "penthouse": "Penthouse",
    "wicked": "Wicked",
    "sexart": "SexArt",
    "stripshow": "StripShow",
    "eroticax": "EroticaX",
    "girlsway": "Girlsway",
    "girlfriendsfilms": "GirlfriendsFilms",
    "realityjunkies": "RealityJunkies",
    "wankz": "Wankz",
    "pornfidelity": "PornFidelity",
    "teenmegaworld": "TeenMegaWorld",
}

# 品牌网络映射
SITE_NETWORK_MAP = {
    # Vixen 网络
    "Vixen": "Vixen Network",
    "Blacked": "Vixen Network",
    "Blacked Raw": "Vixen Network",
    "Tushy": "Vixen Network",
    "TushyRaw": "Vixen Network",
    "Deeper": "Vixen Network",
    "Milfy": "Vixen Network",
    "Wifey": "Vixen Network",
    "Slayed": "Vixen Network",
    # Aylo 网络
    "Brazzers": "Aylo",
    "BangBros": "Aylo",
    "Reality Kings": "Aylo",
    "Mofos": "Aylo",
    "Digital Playground": "Aylo",
    "Twistys": "Aylo",
    "Babes": "Aylo",
    # NA 网络
    "Naughty America": "Naughty America",
    "MYLF": "Naughty America",
    # Algolia 网络
    "Evil Angel": "Algolia",
    "Adult Time": "Algolia",
    "Pure Taboo": "Algolia",
    # 独立品牌（无网络归属）
    "Hegre": "Independent",
    "PublicAgent": "Independent",
    "TeamSkeet": "TeamSkeet",
    "BrattySis": "TeamSkeet",
    "Playboy": "Playboy",
    "Penthouse": "Penthouse",
}


def extract_site_from_filename(filename: str) -> tuple[str | None, str | None]:
    """从文件名或文件夹名提取站点和品牌网络

    支持格式:
    - brazzers_12345.mp4
    - BangBros - Scene 1.mp4
    - vixen-2023-01-15.mp4
    - [PublicAgent] video.mp4   （文件夹名）
    - Hegre.xxx.mp4
    """
    name_lower = filename.lower()

    for prefix, site_name in WESTERN_SITE_PREFIXES.items():
        if prefix in name_lower:
            network = SITE_NETWORK_MAP.get(site_name)
            return site_name, network

    return None, None


def generate_western_code(file_path: Path, site: str | None) -> str:
    """为欧美视频生成唯一编码"""
    site_part = site or "unknown"
    hash_part = hashlib.sha256(str(file_path).encode()).hexdigest()[:8]
    return f"WE-{site_part}-{hash_part}"


# ---------------------------------------------------------------------------
# 欧美文件名演员识别
# ---------------------------------------------------------------------------
# 🔴 2026-10-05：欧美样本的演员名几乎都直接写在文件名里，但旧扫描器只从 NFO 读
# `actor`，而 G:\TEST\欧美 这类样本没有每片 NFO（只有一个根目录 movie.nfo 且
# 不含 actor），导致库里 8 部片只有 1 部有演员。国产专用的
# `extract_actor_from_folder` 不能用：它把 "Anna Ralphs" 拆成两个 token、且
# **拒绝全小写名**（blaire.ivory / jimena.lago 直接返回 []）、还会把 XXX 当
# 成人名一部分。所以这里写一份欧美专用的文件名解析器。
#
# 两种主流命名：
#   1) Hegre 风："Anna Ralphs - [Hegre.com] - [2023] - Cum Inside Me - 4K"
#      → 演员在第一个 " - " 之前。
#   2) 站点.日期.演员.场景 风："Blacked.19.10.12.Lana.Sharapova.4k-C" /
#      "bb.16.07.13.blaire.ivory" / "pba.16.05.27.jimena.lago" /
#      "PublicAgent.16.05.27.Jimena.Lago.XXX.1080p.MP4-KTR[rarbg]"
#      → 先剥掉 站点.YYYY.MM.DD. 前缀，再取首个质量/清晰度标记之前的名字 token，
#       "And"/"&" 视作多演员分隔。
# 实测 8/8 通过（见 scripts/_verify_western_filename_actor.py）。

_WESTERN_QUALITY = {
    "4k", "1080p", "720p", "480p", "2160p", "1440p", "xxx", "mp4", "mkv", "ktr",
    "rarbg", "uncen", "uncut", "h264", "x264", "x265", "web", "webrip", "web-dl",
    "bluray", "brrip", "hd", "full", "scene", "c", "u", "leak", "samples", "fhd",
    "uhd", "hevc", "10bit", "yify", "ettv", "avi", "wmv", "mov",
}
_WESTERN_CONJ = {"and", "&", "with", "feat", "featuring"}


def _clean_western_token(token: str) -> str:
    """去掉尾部的 -C/-U/-UC/-4K 等字幕/清晰度标记（如 Orchid-C → Orchid）。"""
    return re.sub(r"-(C|U|UC|4K|4k|LEAK|Leak)$", "", token, flags=re.I)


def _is_western_quality(token: str) -> bool:
    t = token.lower().replace("-", "")
    if t in _WESTERN_QUALITY:
        return True
    if re.match(r"^\d{3,4}p", t.lower()):
        return True
    if t.startswith("4k") or t.startswith("uhd"):
        return True
    return False


def _titlecase_western(token: str) -> str:
    if not token:
        return token
    if token.isupper():
        return token.title()
    return token[:1].upper() + token[1:].lower()


def _split_on_conj(tokens: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    cur: list[str] = []
    for t in tokens:
        if t.lower() in _WESTERN_CONJ:
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        groups.append(cur)
    return groups


def extract_actors_from_western_filename(filename: str) -> list[str]:
    """从欧美视频文件名识别演员名列表。无结果返回 []。"""
    stem = strip_video_ext(filename)

    # ① Hegre 风：演员在第一个 " - " 或 "[" 之前，且形如 "Anna Ralphs"
    head = re.split(r"\s-\s|\[", stem)[0].strip()
    if re.match(r"^[A-Z][a-z]+(\s[A-Z][a-z]+)+", head):
        groups = _split_on_conj(head.split())
        out = [" ".join(_titlecase_western(x) for x in g) for g in groups]
        out = [o for o in out if o]
        if out:
            return out

    # ② 站点.日期.演员.场景 风：先剥 站点.YYYY.MM.DD. 前缀
    rest = stem
    m = re.match(r"^[A-Za-z]+(?:\.[A-Za-z]+)?\.\d{2}\.\d{2}\.\d{2}\.", stem)
    if m:
        rest = stem[m.end():]
    else:
        m = re.match(r"^[A-Za-z]+(?:\.[A-Za-z]+)?\.\d{6}\.", stem)
        if m:
            rest = stem[m.end():]

    tokens = [_clean_western_token(t) for t in re.split(r"[._\-–\s]+", rest) if t]
    # 截断到第一个质量/清晰度标记
    cut = len(tokens)
    for i, t in enumerate(tokens):
        if _is_western_quality(t):
            cut = i
            break
    tokens = tokens[:cut]

    out: list[str] = []
    for g in _split_on_conj(tokens):
        name = " ".join(_titlecase_western(x) for x in g)
        if name and not all(_is_western_quality(x) for x in g):
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# 更智能的欧美文件名结构化识别
# ---------------------------------------------------------------------------
# 🔴 2026-10-05：G:\TEST\欧美 实测发现，目录级共享 movie.nfo 会把 8 部片全部
# 套成同一个错误标题（"Anna L and Danny Happy Ending Massage"）+ 同一错误日期
# （2023-12-19）。而文件名本身就携带了**正确**的标题与日期：
#   - Hegre 风：'Anna Ralphs - [Hegre.com] - [2023] - Cum Inside Me - 4K'
#   - 站点.日期.演员：'Blacked.19.10.12.Lana.Sharapova.4k-C'
#   - 站点.日期.演员.XXX.画质.组：'PublicAgent.16.05.27.Jimena.Lago.XXX.1080p.MP4-KTR[rarbg]'
#   - BangBros 简写：'bb.16.07.13.blaire.ivory.mp4'
# 每种下载组的命名约定都不一样 ⇒ 必须做结构化解析：站点/网络/日期/标题/演员/
# 画质/发布组 各归各位，且**文件名能识别出的字段优先于共享 movie.nfo**。

_BRACKET_RE = re.compile(r"^\[.*\]$")
_YEAR_ONLY_RE = re.compile(r"\[(\d{4})\]")
_DATE_DOT4_RE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")
# 站点.YY.MM.DD. 形态（BB/Blacked/PublicAgent 等）。允许前面是点分隔符，
# 仅保证后面不是 ".数字"（避免误吃 19.10.123 这种）。
_DATE_DOT2_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})(?!\.\d)")


@dataclass
class WesternFileMeta:
    """从文件名解析出的欧美视频结构化信息。"""
    site: str | None = None
    network: str | None = None
    date: str | None = None            # YYYY-MM-DD（能解析到日）；仅年份时为 YYYY-01-01
    date_is_full: bool = False
    title: str | None = None           # 可识别的作品标题（Hegre 风等）
    actors: list[str] = field(default_factory=list)
    quality: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)   # 发布组 rarbg/KTR 等
    search_query: str | None = None


def _normalize_yy(yy: str) -> str:
    y = int(yy)
    if y >= 100:
        return str(y)
    return f"20{y:02d}" if y < 70 else f"19{y:02d}"


def _parse_filename_date(stem: str) -> tuple[str | None, bool]:
    """返回 (date_str, is_full)。仅年份 → (YYYY-01-01, False)。"""
    m = _DATE_DOT4_RE.search(stem)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", True
    m = _DATE_DOT2_RE.search(stem)
    if m:
        return f"{_normalize_yy(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", True
    m = _YEAR_ONLY_RE.search(stem)
    if m:
        return f"{m.group(1)}-01-01", False
    return None, False


def _extract_hegre_title(stem: str) -> str | None:
    """Hegre 风：'Actor - [Site] - [Year] - Title - Quality' 取中间的作品标题。"""
    if " - " not in stem:
        return None
    segments = [s.strip() for s in stem.split(" - ")]
    if not re.match(r"^[A-Z][a-z]+(\s[A-Z][a-z]+)+", segments[0]):
        return None
    candidates: list[str] = []
    for seg in segments[1:]:
        if _BRACKET_RE.match(seg):
            continue
        if _is_western_quality(seg):
            continue
        candidates.append(seg)
    if not candidates:
        return None
    # Hegre 命名里演员只在首段，后续非括号、非画质段即作品标题；
    # 取最长一段作为标题（"Cum Inside Me" 这类全大写开头多词串不再被误判为演员名）。
    return max(candidates, key=len)


def parse_western_filename(filename: str) -> WesternFileMeta:
    """从欧美视频文件名智能识别：站点/网络/日期/标题/演员/画质/发布组/搜索词。"""
    # 用 strip_video_ext 而非 Path().stem：站点.日期.演员 这类命名里末段不是扩展名，
    # Path.stem 会把 "pba.16.05.27.jimena.lago" 误当扩展名吃掉成 "pba.16.05.27.jimena"。
    stem = strip_video_ext(filename)
    site, network = extract_site_from_filename(stem)
    actors = extract_actors_from_western_filename(stem)

    date, date_is_full = _parse_filename_date(stem)
    title = _extract_hegre_title(stem)

    # 画质 + 发布组
    quality: list[str] = []
    groups: list[str] = []
    for m in re.finditer(r"\[([^\]]*)\]", stem):
        groups.append(m.group(1))
    for tok in re.split(r"[._\-–\s]+", stem):
        if _is_western_quality(tok) and tok.lower() not in [g.lower() for g in groups]:
            quality.append(tok)
    for tok in re.split(r"[.\-]+", stem):
        if tok.upper() in {"KTR", "RARBG", "YIFY", "ETTV", "WIKI", "GAZ"}:
            groups.append(tok.upper())

    # 搜索词：优先作品标题，其次演员名（IAFD 不索引演员名，但 Aylo 按演员搜有效）
    if title:
        search_query = title
    elif actors:
        search_query = " ".join(actors)
    else:
        search_query = None

    return WesternFileMeta(
        site=site, network=network, date=date, date_is_full=date_is_full,
        title=title, actors=actors, quality=quality, groups=groups,
        search_query=search_query,
    )


class WesternScanner(BaseScanner):
    """欧美模块扫描器"""

    def __init__(self, media_dirs: list[str], config: dict | None = None):
        super().__init__("western", media_dirs)
        self.config = config or {}

    async def scan(self) -> dict:
        """扫描欧美媒体目录并落库"""
        results = {"total": 0, "scanned": 0, "movies_added": 0, "sites": set(), "errors": []}

        logger.info(f"[western] 扫描启动: media_dirs={[str(d) for d in self.media_dirs]}")
        for media_dir in self.media_dirs:
            try:
                logger.info(f"[western] 开始扫描目录: {media_dir}")
                dir_result = await self._scan_directory(media_dir)
                logger.info(
                    f"[western] 目录扫描完成: {media_dir} 共发现 {dir_result['total']} 个文件，"
                    f"新增 {dir_result.get('movies_added', 0)}"
                )
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["movies_added"] += dir_result.get("movies_added", 0)
                results["sites"].update(dir_result.get("sites", set()))
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"扫描目录失败 {media_dir}: {e}")

        # 🔴 演员关联回填：把刚提交的 movies.actor 文本列回填成 actors 表 +
        # movie_actors 关联（基类方法，读取库里 actor 列，创建演员记录 + 重建
        # 关联 + 重算 movie_count）。此前 western 扫描器从不调这一步，导致库里
        # 演员表/关联表常年为空，"按演员查片"只能靠文本 LIKE 兜底。
        try:
            await self._sync_actor_links()
        except Exception as e:
            logger.warning(f"[western] 演员关联回填失败（不影响扫描）: {e}")

        results["sites"] = list(results["sites"])
        logger.info(
            f"[western] 扫描完成: 共发现 {results['total']} 个文件，新增 {results['movies_added']}，"
            f"错误 {len(results['errors'])} 个"
        )
        return results

    async def _scan_directory(self, media_dir) -> dict:
        """扫描单个媒体目录并写入数据库"""
        result = {"total": 0, "scanned": 0, "movies_added": 0, "sites": set()}
        media_dir = Path(media_dir)

        from app.db.module_db import ModuleDatabase
        db = ModuleDatabase.get_instance("western")
        session = await db.get_session()
        try:
            from app.db.western_models import WesternMovie
            from sqlalchemy import select

            # 性能修复：一次性载入已存在番号，避免每文件一次 SELECT 的 N+1 查询
            existing_codes: set[str] = set(
                (await session.execute(select(WesternMovie.code))).scalars().all()
            )

            walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
            for root, dirs, files in walk_entries:
                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    # 🔴 智能识别：从文件名解析站点/日期/标题/演员/画质（覆盖多种命名约定）
                    meta = parse_western_filename(file_name)
                    site, network = meta.site, meta.network
                    if site:
                        result["sites"].add(site)

                    # 生成编码
                    code = generate_western_code(file_path, site)

                    # 检查是否已存在（内存判重，避免 N+1 查询）
                    if code in existing_codes:
                        continue
                    existing_codes.add(code)

                    # 🔴 NFO 富字段入库（此前 title 写死 Path(file_name).stem，
                    #    把 NFO 里已有的 premiered/runtime/tag/actor 全丢了）。
                    #    实测 G:\TEST\欧美 样本 NFO 带 premiered+year+runtime+38 个
                    #    tag+2 个 actor，而库里 8 条只有 1 条有 duration。
                    #    解析器为全仓唯一实现 app/utils/nfo_fields.py。
                    nfo_meta: dict = {
                        k: ([] if isinstance(v, list) else v)
                        for k, v in EMPTY_NFO_META.items()
                    }
                    # 追踪 NFO 来源：'{stem}.nfo' 是专为当前片生成的，优先级最高；
                    # 目录级 'movie.nfo' 可能是多片共享的（如 G:\TEST\欧美 根目录
                    # 那个只描述其中一部的 movie.nfo），不可盲信。
                    nfo_source = None
                    for nfo_candidate in (file_path.parent / f"{file_path.stem}.nfo",
                                          file_path.parent / "movie.nfo"):
                        if nfo_candidate.exists():
                            nfo_meta = parse_nfo_fields(nfo_candidate)
                            nfo_source = "stem" if nfo_candidate.name.startswith(file_path.stem) else "movie"
                            break

                    # 🔴 演员识别：文件名优先（实测 8/8 通过），NFO 兜底
                    nfo_actors = list(nfo_meta.get("actors") or [])
                    if meta.actors:
                        actor_names = meta.actors
                    elif nfo_actors:
                        actor_names = nfo_actors
                    else:
                        actor_names = []
                    actor_str = ",".join(actor_names) if actor_names else None

                    # 🔴 标题：文件名可识别标题（Hegre 风）优先于共享 movie.nfo，
                    #    否则 NFO 优先，再回退文件名。避免根目录共享 movie.nfo 把
                    #    8 部片全套成同一个错误标题（实测：全变成 "Anna L and Danny..."）。
                    title = meta.title or nfo_meta.get("title") or Path(file_name).stem

                    # 🔴 日期：文件名解析到「日」的优先（更精确），否则 NFO，
                    #    否则仅年份兜底（Hegre [2023] 形态）。
                    if meta.date_is_full:
                        release_date = meta.date
                    elif nfo_meta.get("release_date"):
                        release_date = nfo_meta.get("release_date")
                    else:
                        release_date = meta.date

                    # 写入新影片记录
                    new_movie = WesternMovie(
                        code=code,
                        title=title,
                        original_title=nfo_meta.get("original_title"),
                        site=site,
                        network=network,
                        release_date=release_date,
                        duration=nfo_meta.get("duration"),
                        rating=nfo_meta.get("rating"),
                        plot=nfo_meta.get("plot"),
                        plot_short=nfo_meta.get("plot_short"),
                        actor=actor_str,
                        studio=nfo_meta.get("studio"),
                        series=nfo_meta.get("series"),
                        # genre/tag 存 JSON 字符串（与 workflow.py::persist 同口径，
                        # API 侧 movies.py::_apply_nfo 两种格式都兼容）
                        genre=json.dumps(nfo_meta["genre"], ensure_ascii=False) if nfo_meta.get("genre") else None,
                        tag=json.dumps(nfo_meta["tag"], ensure_ascii=False) if nfo_meta.get("tag") else None,
                        file_path=str(file_path),
                        file_size=_file_size(file_path),
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1
                    if code:
                        # 并发受限（防整盘扫描时无限制 ensure_future 风暴拖死事件循环）
                        asyncio.ensure_future(
                            self._copy_limited(
                                copy_video_assets_to_data_dir(str(file_path), code, "western")
                            )
                        )

            await session.commit()
        finally:
            await session.close()

        return result
