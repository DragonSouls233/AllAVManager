"""
NFO 免改名半自动刮削服务（C9）

读取已存在的 .nfo 文件，提取元数据后导入到数据库，不会重命名或移动视频文件。
支持 Emby / Jellyfin / Kodi 三种 NFO 格式的字段差异。

核心函数：
- parse_nfo(nfo_path): 解析单个 NFO XML 文件，返回统一结构的 dict
- scan_directory(dir_path): 递归扫描目录中所有 .nfo 文件
- import_to_db(nfo_data, session): 将 NFO 数据导入 Movie/Actor/Tag 表（不重复创建）
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import xml.etree.ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Actor, Movie, MovieActor, MovieTag, Tag

logger = logging.getLogger(__name__)


# 三种 NFO 格式的字段名差异（实际取值时按顺序兜底）：
# - Emby/Jellyfin：<id>、<premiered>、<studio>、<maker>、<thumb aspect="poster">
# - Kodi：<uniqueId>、<aired>、<studio>、<maker>、<art><poster>...
# 三者都使用 <title>、<originaltitle>、<plot>、<outline>、<runtime>、<genre>、<tag>、<set>、<actor>

# 番号字段候选（按优先级）
_CODE_FIELDS = ("id", "code", "num")
# 发行日期候选
_DATE_FIELDS = ("premiered", "releasedate", "aired")
# 标题字段候选
_TITLE_FIELDS = ("title", "sorttitle")


def _get_text(root: ET.Element, tag: str) -> Optional[str]:
    """获取 XML 元素中指定标签的文本（去空白）"""
    child = root.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _get_texts(root: ET.Element, tag: str) -> list[str]:
    """获取所有同名子元素的文本（去空白、去重、保持顺序）"""
    seen: set[str] = set()
    results: list[str] = []
    for child in root.findall(tag):
        if child.text:
            value = child.text.strip()
            if value and value not in seen:
                seen.add(value)
                results.append(value)
    return results


def _get_first_text(root: ET.Element, tags: tuple[str, ...]) -> Optional[str]:
    """按字段优先级取首个非空值"""
    for tag in tags:
        value = _get_text(root, tag)
        if value:
            return value
    return None


def _normalize_code(code: Optional[str]) -> Optional[str]:
    """标准化番号：去空白、转大写、统一分隔符"""
    if not code:
        return None
    code = code.strip().upper().replace("_", "-")
    # 去掉多余空白
    code = re.sub(r"\s+", "", code)
    return code or None


def _extract_code_from_title(title: str) -> Optional[str]:
    """从标题中提取番号（兜底策略）"""
    if not title:
        return None
    cleaned = re.sub(r"^\d{4}[-/]\d{2}[-/]\d{2}", "", title)
    patterns = [
        r"([A-Z]{2,6}[-_]?\d{2,5})",
        r"(FC2[-_]?PPV[-_]?\d+)",
        r"(HEYZO[-_]?\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return _normalize_code(match.group(1))
    return None


def _parse_date(date_str: Optional[str]) -> Optional[str]:
    """解析日期字符串，统一输出 YYYY-MM-DD 格式"""
    if not date_str:
        return None
    date_str = date_str.strip().replace("/", "-").replace(".", "-")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if match:
        y, m, d = match.groups()
        try:
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except ValueError:
            return None
    # 仅有年份
    match = re.search(r"^(\d{4})$", date_str)
    if match:
        return f"{match.group(1)}-01-01"
    return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    """从字符串中提取整数"""
    if not value:
        return None
    match = re.search(r"(\d+)", value)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _parse_float(value: Optional[str]) -> Optional[float]:
    """从字符串中提取浮点数"""
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _detect_nfo_format(root: ET.Element) -> str:
    """检测 NFO 格式：emby / jellyfin / kodi

    判定逻辑：
    - 含 <uniqueId> 或 <ratings> 或 <art> 块 → kodi
    - 否则默认 emby/jellyfin（两者字段几乎一致，无法细分）
    """
    if root.find("uniqueId") is not None:
        return "kodi"
    if root.find("ratings") is not None:
        return "kodi"
    art = root.find("art")
    if art is not None and len(list(art)) > 0:
        return "kodi"
    # 默认 emby/jellyfin（两者字段几乎一致）
    return "emby"


def _extract_actors(root: ET.Element) -> list[dict]:
    """提取演员列表（含头像）"""
    actors: list[dict] = []
    seen: set[str] = set()
    for actor_elem in root.findall("actor"):
        name = _get_text(actor_elem, "name")
        if not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        avatar_url = _get_text(actor_elem, "thumb")
        role = _get_text(actor_elem, "role")
        actors.append({
            "name": name,
            "avatar_url": avatar_url,
            "role": role,
        })
    return actors


def _extract_thumbs(root: ET.Element, nfo_dir: Path) -> dict:
    """提取封面/海报/缩略图路径

    Emby/Jellyfin：使用 <thumb aspect="..."> 标签
    Kodi：使用 <art><poster>/<fanart>/<banner>...</art>，或也用 <thumb>

    优先返回本地路径（如果文件存在），否则返回 URL。
    """
    thumbs: dict = {
        "cover_url": None,
        "poster_url": None,
        "thumb_url": None,
        "fanart_url": None,
    }

    # 1. Emby/Jellyfin 风格：<thumb aspect="...">
    for thumb_elem in root.findall("thumb"):
        if not thumb_elem.text:
            continue
        url = thumb_elem.text.strip()
        aspect = thumb_elem.get("aspect", "") or thumb_elem.get("type", "")
        if aspect == "poster" and not thumbs["poster_url"]:
            thumbs["poster_url"] = url
        elif aspect == "fanart" and not thumbs["fanart_url"]:
            thumbs["fanart_url"] = url
        elif aspect == "thumb" and not thumbs["thumb_url"]:
            thumbs["thumb_url"] = url
        elif aspect in ("landscape", "banner", "clearart") and not thumbs["cover_url"]:
            thumbs["cover_url"] = url

    # 2. Kodi 风格：<art><poster>/<fanart>/...
    art_elem = root.find("art")
    if art_elem is not None:
        if not thumbs["poster_url"]:
            thumbs["poster_url"] = _get_text(art_elem, "poster")
        if not thumbs["fanart_url"]:
            thumbs["fanart_url"] = _get_text(art_elem, "fanart")
        if not thumbs["thumb_url"]:
            thumbs["thumb_url"] = _get_text(art_elem, "thumb")
        if not thumbs["cover_url"]:
            thumbs["cover_url"] = _get_text(art_elem, "landscape") or _get_text(art_elem, "banner")

    # 3. 兜底：取第一个 <thumb>
    if not thumbs["poster_url"]:
        first_thumb = root.find("thumb")
        if first_thumb is not None and first_thumb.text:
            thumbs["poster_url"] = first_thumb.text.strip()

    # 4. 检测 NFO 同目录下的同名图片文件（Emby/Kodi 约定）
    # 例如 movie.nfo 旁的 movie-poster.jpg / movie-fanart.jpg
    if nfo_dir.exists():
        nfo_stem = nfo_dir.stem  # 通常为 "movie" 或番号
        local_candidates = {
            "poster_url": [
                nfo_dir / f"{nfo_stem}-poster.jpg",
                nfo_dir / f"{nfo_stem}-poster.png",
                nfo_dir / "poster.jpg",
                nfo_dir / "poster.png",
            ],
            "fanart_url": [
                nfo_dir / f"{nfo_stem}-fanart.jpg",
                nfo_dir / f"{nfo_stem}-fanart.png",
                nfo_dir / "fanart.jpg",
                nfo_dir / "fanart.png",
            ],
            "cover_url": [
                nfo_dir / "landscape.jpg",
                nfo_dir / "landscape.png",
            ],
        }
        for key, candidates in local_candidates.items():
            if not thumbs.get(key):
                for cand in candidates:
                    if cand.exists():
                        thumbs[key] = str(cand)
                        break

    return thumbs


def parse_nfo(nfo_path: str) -> dict:
    """解析单个 NFO XML 文件，返回统一结构的 dict

    支持 Emby / Jellyfin / Kodi 三种 NFO 格式。

    Args:
        nfo_path: NFO 文件绝对路径

    Returns:
        包含以下字段的 dict：
        - code: 番号（标准化大写）
        - title: 标题
        - original_title: 原始标题
        - plot: 简介
        - plot_short: 短简介
        - studio: 制作商
        - maker: 发行商
        - director: 导演
        - series: 系列
        - release_date: 发行日期 YYYY-MM-DD
        - year: 年份
        - duration: 时长（分钟）
        - rating: 评分 0-10
        - is_mosaic: 是否有码
        - genres: 标签列表
        - tags: 额外标签列表
        - actors: 演员列表 [{name, avatar_url, role}]
        - cover_url / poster_url / thumb_url / fanart_url: 图片路径或URL
        - source: 数据来源
        - nfo_path: NFO 文件路径
        - nfo_format: NFO 格式（emby/jellyfin/kodi）

    Raises:
        FileNotFoundError: NFO 文件不存在
        ET.ParseError: XML 解析失败
    """
    nfo_path_obj = Path(nfo_path)
    if not nfo_path_obj.exists():
        raise FileNotFoundError(f"NFO 文件不存在: {nfo_path}")

    content = nfo_path_obj.read_text(encoding="utf-8-sig", errors="ignore")
    root = ET.fromstring(content)

    # 兼容多种根元素（movie/episodedetails/tvshow/season）
    if root.tag not in ("movie", "episodedetails", "tvshow", "season"):
        raise ValueError(f"不支持的 NFO 根元素: {root.tag}")

    nfo_format = _detect_nfo_format(root)
    nfo_dir = nfo_path_obj.parent

    # 番号：优先 <id>，Kodi 兼容 <code>/<uniqueId>，再兜底从标题提取
    code = _get_first_text(root, _CODE_FIELDS)
    if not code:
        # Kodi uniqueId 通常带 type 属性，取 default="true" 的优先
        unique_id_elem = None
        for uid in root.findall("uniqueId"):
            if uid.get("default", "false").lower() == "true":
                unique_id_elem = uid
                break
        if unique_id_elem is None:
            unique_id_elem = root.find("uniqueId")
        if unique_id_elem is not None and unique_id_elem.text:
            code = unique_id_elem.text.strip()
    code = _normalize_code(code)

    title = _get_first_text(root, _TITLE_FIELDS)
    if not code and title:
        code = _extract_code_from_title(title)

    original_title = _get_text(root, "originaltitle")
    plot = _get_text(root, "plot") or _get_text(root, "outline")
    plot_short = _get_text(root, "outline")

    # 简介（如果只有 plot，截断作为 plot_short）
    if plot and not plot_short:
        plot_short = (plot[:145] + "…") if len(plot) > 145 else plot

    studio = _get_text(root, "studio")
    maker = _get_text(root, "maker")
    director = _get_text(root, "director")
    series = _get_text(root, "set")

    release_str = _get_first_text(root, _DATE_FIELDS)
    release_date = _parse_date(release_str)
    year = _parse_int(_get_text(root, "year"))
    # 若无 year 但有 release_date，则从日期提取
    if not year and release_date:
        year = int(release_date[:4])

    runtime_str = _get_text(root, "runtime")
    duration = _parse_int(runtime_str)

    # 评分：Emby 直接 <rating>，Kodi 用 <ratings><rating><value>
    rating_str = _get_text(root, "rating")
    if not rating_str:
        ratings_elem = root.find("ratings")
        if ratings_elem is not None:
            rating_inner = ratings_elem.find("rating")
            if rating_inner is not None:
                value_elem = rating_inner.find("value")
                if value_elem is not None and value_elem.text:
                    rating_str = value_elem.text.strip()
    rating = _parse_float(rating_str)

    # 有码/无码：<mpaa>"有码" → True，"无码" → False
    is_mosaic: Optional[bool] = None
    mpaa = _get_text(root, "mpaa")
    if mpaa:
        if "无码" in mpaa:
            is_mosaic = False
        elif "有码" in mpaa:
            is_mosaic = True

    genres = _get_texts(root, "genre")
    tags = _get_texts(root, "tag")

    actors = _extract_actors(root)
    thumbs = _extract_thumbs(root, nfo_dir)

    source = _get_text(root, "source")

    return {
        "code": code,
        "title": title,
        "original_title": original_title,
        "title_jp": original_title,
        "plot": plot,
        "plot_short": plot_short,
        "studio": studio,
        "maker": maker,
        "director": director,
        "series": series,
        "release_date": release_date,
        "year": year,
        "duration": duration,
        "rating": rating,
        "is_mosaic": is_mosaic,
        "genres": genres,
        "tags": tags,
        "actors": actors,
        "cover_url": thumbs["cover_url"],
        "poster_url": thumbs["poster_url"],
        "thumb_url": thumbs["thumb_url"],
        "fanart_url": thumbs["fanart_url"],
        "source": source or "nfo",
        "nfo_path": str(nfo_path_obj),
        "nfo_format": nfo_format,
    }


def scan_directory(dir_path: str, recursive: bool = True) -> list[dict]:
    """扫描目录中的所有 .nfo 文件并解析

    Args:
        dir_path: 目录路径
        recursive: 是否递归扫描子目录

    Returns:
        解析结果列表（每个元素为 parse_nfo 的返回 dict）
        解析失败的文件会跳过并记录 warning 日志。
    """
    dir_path_obj = Path(dir_path)
    if not dir_path_obj.exists():
        raise FileNotFoundError(f"目录不存在: {dir_path}")
    if not dir_path_obj.is_dir():
        raise NotADirectoryError(f"路径不是目录: {dir_path}")

    if recursive:
        nfo_files = list(dir_path_obj.rglob("*.nfo"))
    else:
        nfo_files = list(dir_path_obj.glob("*.nfo"))

    results: list[dict] = []
    for nfo_file in nfo_files:
        try:
            data = parse_nfo(str(nfo_file))
            results.append(data)
        except (ET.ParseError, ValueError) as e:
            logger.warning(f"解析 NFO 失败 {nfo_file}: {e}")
        except Exception as e:
            logger.error(f"处理 NFO 文件异常 {nfo_file}: {e}", exc_info=True)

    return results


async def import_to_db(nfo_data: dict, session: AsyncSession) -> dict:
    """将解析后的 NFO 数据导入数据库

    - 若影片已存在（按番号匹配），仅补全缺失字段
    - 若不存在则创建
    - 演员/标签按名称去重，不重复创建关联

    Args:
        nfo_data: parse_nfo 的返回 dict
        session: 异步数据库会话

    Returns:
        dict:
        - movie_id: 影片 ID
        - code: 番号
        - created: 是否新建
        - updated_fields: 更新的字段名列表
    """
    code = nfo_data.get("code")
    if not code:
        raise ValueError("NFO 数据缺少番号 code，无法导入")

    # 查找已有影片
    result = await session.execute(select(Movie).where(Movie.code == code))
    movie = result.scalar_one_or_none()

    created = False
    updated_fields: list[str] = []

    if movie is None:
        movie = Movie(code=code, status="pending")
        session.add(movie)
        created = True
        updated_fields.append("code")

    # 缺失字段补全
    def _fill(field_name: str, value):
        if getattr(movie, field_name) is None and value is not None:
            setattr(movie, field_name, value)
            updated_fields.append(field_name)

    _fill("title", nfo_data.get("title"))
    _fill("title_jp", nfo_data.get("title_jp") or nfo_data.get("original_title"))
    _fill("plot", nfo_data.get("plot"))
    _fill("plot_short", nfo_data.get("plot_short"))
    _fill("maker", nfo_data.get("maker"))
    _fill("director", nfo_data.get("director"))
    _fill("release_date", nfo_data.get("release_date"))
    _fill("duration", nfo_data.get("duration"))
    _fill("rating", nfo_data.get("rating"))
    _fill("is_mosaic", nfo_data.get("is_mosaic"))
    _fill("cover_url", nfo_data.get("cover_url"))
    _fill("poster_url", nfo_data.get("poster_url"))
    _fill("thumb_url", nfo_data.get("thumb_url"))
    _fill("source", nfo_data.get("source"))

    # studio 字段（Movie 模型为 studio_id 外键，但原始字段 movie.studio 已废弃；
    # 这里若需要可创建 Studio 记录，否则将名称写入 maker 字段作兜底）
    # 注意：Movie 模型没有 studio 字符串字段，跳过以避免 AttributeError
    # 若有需要可在此扩展创建 Studio 记录

    # 标签 genre（JSON 数组）
    genres = nfo_data.get("genres") or []
    if genres and movie.genre is None:
        movie.genre = json.dumps(genres, ensure_ascii=False)
        updated_fields.append("genre")

    # 额外标签 tag（JSON 数组）
    nfo_tags = nfo_data.get("tags") or []
    if nfo_tags and movie.tag is None:
        movie.tag = json.dumps(nfo_tags, ensure_ascii=False)
        updated_fields.append("tag")

    # 系列字段（Movie 模型无 series 字符串字段，仅 series_id 外键，跳过）
    # 若有需要可在此扩展创建 Series 记录

    await session.flush()  # 获取 movie.id（新建时）

    # 演员：按名称查找或创建，关联到影片（去重）
    for actor_info in nfo_data.get("actors") or []:
        actor_name = actor_info.get("name")
        if not actor_name:
            continue

        # 查找已有演员
        actor_result = await session.execute(
            select(Actor).where(Actor.name == actor_name)
        )
        actor = actor_result.scalar_one_or_none()

        if actor is None:
            actor = Actor(
                name=actor_name,
                avatar_url=actor_info.get("avatar_url"),
            )
            session.add(actor)
            await session.flush()  # 获取 actor.id
            updated_fields.append(f"actor:{actor_name}")
        else:
            # 演员已存在，补回头像
            if actor.avatar_url is None and actor_info.get("avatar_url"):
                actor.avatar_url = actor_info.get("avatar_url")

        # 检查是否已关联
        link_result = await session.execute(
            select(MovieActor).where(
                MovieActor.movie_id == movie.id,
                MovieActor.actor_id == actor.id,
            )
        )
        if link_result.scalar_one_or_none() is None:
            session.add(MovieActor(
                movie_id=movie.id,
                actor_id=actor.id,
                role=actor_info.get("role"),
            ))
            if f"actor:{actor_name}" not in updated_fields:
                updated_fields.append(f"actor:{actor_name}")

    # 标签：合并 genres + tags，按名称查找或创建
    all_tag_names: list[str] = []
    seen_tags: set[str] = set()
    for name in (genres + nfo_tags):
        if name and name not in seen_tags:
            seen_tags.add(name)
            all_tag_names.append(name)

    for tag_name in all_tag_names:
        tag_result = await session.execute(select(Tag).where(Tag.name == tag_name))
        tag = tag_result.scalar_one_or_none()
        if tag is None:
            tag = Tag(name=tag_name, is_user=False)
            session.add(tag)
            await session.flush()

        # 检查关联
        link_result = await session.execute(
            select(MovieTag).where(
                MovieTag.movie_id == movie.id,
                MovieTag.tag_id == tag.id,
            )
        )
        if link_result.scalar_one_or_none() is None:
            session.add(MovieTag(movie_id=movie.id, tag_id=tag.id))
            updated_fields.append(f"tag:{tag_name}")

    await session.commit()
    await session.refresh(movie)

    return {
        "movie_id": movie.id,
        "code": movie.code,
        "created": created,
        "updated_fields": updated_fields,
    }
