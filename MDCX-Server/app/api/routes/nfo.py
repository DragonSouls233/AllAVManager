"""
NFO 导入导出路由

提供 NFO 格式的元数据导入导出功能，兼容 Kodi/Emby/Jellyfin 等媒体中心。
"""

import asyncio
import io
import json
import logging
import shutil
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Body
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xml.dom import minidom

from app.db.database import get_session
from app.db.models import Movie, Actor, MovieActor, Tag, MovieTag

router = APIRouter()
logger = logging.getLogger(__name__)


def _prettify_xml(elem: ET.Element) -> str:
    """格式化 XML 输出,并将 CDATA 占位符替换为真实 CDATA 包裹"""
    rough_string = ET.tostring(elem, encoding="unicode")
    reparsed = minidom.parseString(rough_string)
    # toprettyxml 会自动添加 XML 声明
    pretty = reparsed.toprettyxml(indent="  ", encoding=None)
    # 替换默认声明为指定编码的声明
    pretty = pretty.replace('<?xml version="1.0" ?>', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')

    # 替换 CDATA 占位符为真实 CDATA
    while "__CDATA_START__" in pretty:
        start_idx = pretty.find("__CDATA_START__")
        end_idx = pretty.find("__CDATA_END__", start_idx)
        if end_idx == -1:
            break
        tag_open_end = pretty.rfind(">", 0, start_idx)
        tag_close_start = pretty.find("<", end_idx)
        if tag_open_end == -1 or tag_close_start == -1:
            break
        content = pretty[start_idx + len("__CDATA_START__") : end_idx]
        pretty = (
            pretty[: tag_open_end + 1]
            + f"<![CDATA[{content}]]>"
            + pretty[tag_close_start:]
        )

    return pretty


def _add_cdata_text_element(parent: ET.Element, tag: str, text: Optional[str]) -> ET.Element:
    """添加 CDATA 包裹的文本元素(用于 plot/outline/originalplot 等字段)"""
    elem = ET.SubElement(parent, tag)
    if text:
        elem.text = f"__CDATA_START__{text}__CDATA_END__"
    return elem


def _build_nfo_xml(
    movie: Movie,
    actors: list[dict],
    tags: list[str],
    kodi: bool = False,
) -> ET.Element:
    """
    根据电影数据构建 NFO XML 结构

    Args:
        movie: Movie ORM 对象
        actors: 演员列表 [{"name": ..., "avatar_url": ...}, ...]
        tags: 标签名称列表
        kodi: 是否输出 Kodi 兼容的额外字段（uniqueId/ratings/art/fileinfo 等）

    Returns:
        XML 根元素
    """
    root = ET.Element("movie")

    # === 标题信息(对齐 SSIS-018.nfo) ===
    _add_text_element(root, "title", movie.title or movie.code)
    # originaltitle: 日语原标题(已有 title_jp 字段)
    _add_text_element(root, "originaltitle", movie.title_jp)
    # sorttitle: 优先用日语标题排序
    _add_text_element(root, "sorttitle", movie.title_jp or movie.title or movie.code)
    # id / num: 番号(JavInfo 约定并存)
    _add_text_element(root, "id", movie.code)
    _add_text_element(root, "num", movie.code)

    # === 简介(CDATA 包裹,对齐 SSIS-018.nfo) ===
    if movie.plot:
        _add_cdata_text_element(root, "plot", movie.plot)
        # outline: 短简介
        outline = movie.plot_short or (movie.plot[:145] + "…" if len(movie.plot) > 145 else movie.plot)
        _add_cdata_text_element(root, "outline", outline)

    # originalplot: 日语原简介(关键缺失字段)
    if getattr(movie, "plot_jp", None):
        _add_cdata_text_element(root, "originalplot", movie.plot_jp)

    # tagline: 宣传语
    if movie.release_date:
        _add_cdata_text_element(root, "tagline", f"发行日期 {movie.release_date}")
    elif movie.plot_short:
        _add_cdata_text_element(root, "tagline", movie.plot_short)

    # === 日期(对齐 SSIS-018.nfo: premiered/releasedate/release/year) ===
    if movie.release_date:
        _add_text_element(root, "premiered", movie.release_date)
        _add_text_element(root, "releasedate", movie.release_date)
        _add_text_element(root, "release", movie.release_date)
        year_str = movie.release_date[:4] if len(movie.release_date) >= 4 else None
        _add_text_element(root, "year", year_str)

    # === 时长 ===
    if movie.duration:
        _add_text_element(root, "runtime", str(movie.duration))

    # === 评分(对齐 SSIS-018.nfo: rating/criticrating/votes) ===
    if movie.rating is not None:
        _add_text_element(root, "rating", f"{movie.rating:.1f}")
        # criticrating: 影评人评分(rating × 10)
        _add_text_element(root, "criticrating", str(int(movie.rating * 10)))
    # votes: 评分人数
    if getattr(movie, "votes", None) is not None:
        _add_text_element(root, "votes", str(movie.votes))

    # === 分级(对齐 SSIS-018.nfo: mpaa/customrating/countrycode) ===
    if movie.is_mosaic is not None:
        _add_text_element(root, "mpaa", "JP-18+")
        _add_text_element(root, "customrating", "JP-18+")
    # countrycode: 国家代码
    _add_text_element(root, "countrycode", "JP")

    # === 制作信息(对齐 SSIS-018.nfo: studio/maker/publisher/label) ===
    studio_name = None
    if movie.studio_ref:
        studio_name = movie.studio_ref.name
    _add_text_element(root, "studio", studio_name)
    _add_text_element(root, "maker", movie.maker)
    # publisher: 发行商(关键缺失字段)
    publisher = getattr(movie, "publisher", None) or movie.maker
    _add_text_element(root, "publisher", publisher)
    # label: 厂牌(关键缺失字段)
    label = getattr(movie, "label", None)
    if label:
        _add_text_element(root, "label", label)

    # === 导演(对齐 SSIS-018.nfo) ===
    _add_text_element(root, "director", movie.director)

    # === 系列(set 块,对齐 SSIS-018.nfo) ===
    series_name = None
    if movie.series_ref:
        series_name = movie.series_ref.name
    if series_name:
        set_elem = ET.SubElement(root, "set")
        name_elem = ET.SubElement(set_elem, "name")
        name_elem.text = series_name

    # === 标签(genre + tag,对齐 SSIS-018.nfo) ===
    genre_list = []
    if movie.genre:
        try:
            genre_list = json.loads(movie.genre)
            if not isinstance(genre_list, list):
                genre_list = []
        except (json.JSONDecodeError, TypeError):
            genre_list = [g.strip() for g in movie.genre.split(",") if g.strip()]

    for genre in genre_list:
        _add_text_element(root, "genre", genre)

    # 额外标签 (tag)
    tag_list = []
    if movie.tag:
        try:
            tag_list = json.loads(movie.tag)
            if not isinstance(tag_list, list):
                tag_list = []
        except (json.JSONDecodeError, TypeError):
            tag_list = [t.strip() for t in movie.tag.split(",") if t.strip()]

    # 合并关联标签
    for tag_name in tags:
        if tag_name not in tag_list:
            tag_list.append(tag_name)

    for tag in tag_list:
        _add_text_element(root, "tag", tag)

    # === 演员(对齐 SSIS-018.nfo:含 type 子元素) ===
    for actor_info in actors:
        actor_elem = ET.SubElement(root, "actor")
        _add_text_element(actor_elem, "name", actor_info.get("name"))
        _add_text_element(actor_elem, "role", actor_info.get("role"))
        # type: Actor(对齐 SSIS-018.nfo)
        _add_text_element(actor_elem, "type", "Actor")
        _add_text_element(actor_elem, "thumb", actor_info.get("avatar_url"))

    # === 图片(对齐 SSIS-018.nfo:独立 poster/cover 字段) ===
    if movie.cover_url:
        _add_text_element(root, "cover", movie.cover_url)
        thumb_elem = ET.SubElement(root, "thumb")
        thumb_elem.text = movie.cover_url
        thumb_elem.set("aspect", "poster")
    if movie.poster_url:
        _add_text_element(root, "poster", movie.poster_url)
        thumb_elem2 = ET.SubElement(root, "thumb")
        thumb_elem2.text = movie.poster_url
        thumb_elem2.set("aspect", "poster")

    # 样图(fanart)
    sample_images = []
    if movie.sample_images:
        try:
            sample_images = json.loads(movie.sample_images)
            if not isinstance(sample_images, list):
                sample_images = []
        except (json.JSONDecodeError, TypeError):
            sample_images = []
    for i, img_url in enumerate(sample_images):
        thumb_elem = ET.SubElement(root, "thumb")
        thumb_elem.text = img_url
        thumb_elem.set("aspect", f"fanart{i+1}")

    # === 预告片 ===
    if movie.trailer_url:
        _add_text_element(root, "trailer", movie.trailer_url)

    # === 来源信息(对齐 SSIS-018.nfo:website/javdbid) ===
    if movie.source:
        _add_text_element(root, "source", movie.source)
    # website: 源站链接
    source_url = getattr(movie, "source_url", None)
    if source_url:
        _add_text_element(root, "website", source_url)
    # javdbid: JavDB 视频 ID
    javdb_id = getattr(movie, "javdb_id", None)
    if javdb_id:
        _add_text_element(root, "javdbid", javdb_id)

    # Kodi 兼容额外字段
    if kodi:
        _add_kodi_elements_for_movie(root, movie)

    return root


def _add_kodi_elements_for_movie(root: ET.Element, movie: Movie) -> None:
    """为 Movie ORM 添加 Kodi 兼容的额外字段

    Kodi NFO 规范参考：https://kodi.wiki/view/NFO_files/Movies
    补充 Emby/Jellyfin 基础字段之外的：
    - <uniqueId>：唯一标识（番号 + 来源类型）
    - <ratings>：评分聚合（含 max/votes/default 属性）
    - <userrating>：用户评分
    - <code>：番号（Kodi 专用）
    - <country>：出品国家
    - <aired>：播出日期
    - <tagline>：宣传语
    - <playcount>：播放次数
    - <lastplayed>：最后播放时间
    - <dateadded>：入库时间
    - <art>：艺术图块
    """
    # uniqueId
    unique_id = ET.SubElement(root, "uniqueId")
    unique_id.text = movie.code
    unique_id.set("type", "jav")
    unique_id.set("default", "true")

    # ratings（Kodi 要求嵌套结构）
    if movie.rating is not None:
        ratings_elem = ET.SubElement(root, "ratings")
        rating_elem = ET.SubElement(ratings_elem, "rating")
        rating_elem.set("name", "mdcx")
        rating_elem.set("max", "10")
        rating_elem.set("default", "true")
        value_elem = ET.SubElement(rating_elem, "value")
        value_elem.text = f"{movie.rating:.1f}"
        votes_elem = ET.SubElement(rating_elem, "votes")
        votes_elem.text = "0"

    # userrating（如有 rating 取整作为用户评分，1-10）
    if movie.rating is not None:
        _add_text_element(root, "userrating", str(int(round(movie.rating))))

    # code（Kodi 专用番号字段）
    _add_text_element(root, "code", movie.code)

    # country
    _add_text_element(root, "country", "Japan")

    # aired
    if movie.release_date:
        _add_text_element(root, "aired", movie.release_date)

    # tagline（如有 plot_short）
    if movie.plot_short:
        _add_text_element(root, "tagline", movie.plot_short)

    # playcount
    if movie.play_count:
        _add_text_element(root, "playcount", str(movie.play_count))

    # lastplayed
    if movie.last_played_at:
        _add_text_element(root, "lastplayed", movie.last_played_at.strftime("%Y-%m-%d %H:%M:%S"))

    # dateadded
    if movie.created_at:
        _add_text_element(root, "dateadded", movie.created_at.strftime("%Y-%m-%d %H:%M:%S"))

    # art 块
    art_elem = ET.SubElement(root, "art")
    poster = movie.poster_url or movie.cover_url
    if poster:
        _add_text_element(art_elem, "poster", poster)
        _add_text_element(art_elem, "landscape", poster)
        _add_text_element(art_elem, "banner", poster)
        _add_text_element(art_elem, "clearart", poster)
        _add_text_element(art_elem, "clearlogo", poster)

    sample_images = []
    if movie.sample_images:
        try:
            sample_images = json.loads(movie.sample_images)
            if not isinstance(sample_images, list):
                sample_images = []
        except (json.JSONDecodeError, TypeError):
            sample_images = []
    if sample_images:
        _add_text_element(art_elem, "fanart", sample_images[0])
        if len(sample_images) > 1:
            _add_text_element(art_elem, "thumb", sample_images[1])


def _add_text_element(parent: ET.Element, tag: str, text: Optional[str], **attribs) -> ET.Element:
    """添加文本子元素，仅当 text 非空时添加"""
    elem = ET.SubElement(parent, tag)
    if text:
        elem.text = str(text)
    for key, value in attribs.items():
        elem.set(key, str(value))
    return elem


async def _get_movie_with_relations(session: AsyncSession, movie_id: int) -> Optional[Movie]:
    """获取电影对象（含关联数据），不存在则抛出 404"""
    from sqlalchemy.orm import selectinload
    stmt = select(Movie).where(Movie.id == movie_id).options(
        selectinload(Movie.studio_ref),
        selectinload(Movie.series_ref),
    )
    result = await session.execute(stmt)
    movie = result.scalar_one_or_none()
    if not movie:
        raise HTTPException(status_code=404, detail="电影不存在")
    return movie


async def _get_movie_actors(session: AsyncSession, movie_id: int) -> list[dict]:
    """获取电影的演员信息列表"""
    actor_query = (
        select(Actor.id, Actor.name, Actor.avatar_url, MovieActor.role)
        .join(MovieActor, Actor.id == MovieActor.actor_id)
        .where(MovieActor.movie_id == movie_id)
    )
    result = await session.execute(actor_query)
    actors = []
    for actor_id, name, avatar_url, role in result.fetchall():
        actors.append({
            "name": name,
            "avatar_url": avatar_url,
            "role": role,
        })
    return actors


async def _get_movie_tags(session: AsyncSession, movie_id: int) -> list[str]:
    """获取电影的标签名称列表"""
    tag_query = (
        select(Tag.name)
        .join(MovieTag, Tag.id == MovieTag.tag_id)
        .where(MovieTag.movie_id == movie_id)
    )
    result = await session.execute(tag_query)
    return [row[0] for row in result.fetchall()]


@router.get("/movie/{movie_id}")
async def export_nfo(
    movie_id: int,
    kodi: bool = Query(False, description="输出 Kodi 兼容的额外字段（uniqueId/ratings/art/fileinfo 等）"),
    session: AsyncSession = Depends(get_session),
):
    """导出单个电影的 NFO（返回 XML Response）

    - 默认输出 Emby/Jellyfin 兼容格式
    - `kodi=true` 时追加 Kodi 期望的 uniqueId/ratings/userrating/code/country/aired/
      tagline/playcount/lastplayed/dateadded/art/fileinfo 等字段
    """
    movie = await _get_movie_with_relations(session, movie_id)
    actors = await _get_movie_actors(session, movie_id)
    tags = await _get_movie_tags(session, movie_id)

    root = _build_nfo_xml(movie, actors, tags, kodi=kodi)

    # Kodi 模式下若存在本地文件，附带 fileinfo/streamdetails
    if kodi and movie.file_path:
        streamdetails = await _build_streamdetails_async(movie.file_path)
        if streamdetails is not None:
            fileinfo = ET.SubElement(root, "fileinfo")
            fileinfo.append(streamdetails)

    xml_str = _prettify_xml(root)

    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'inline; filename="{movie.code}.nfo"',
        },
    )


@router.get("/movie/{movie_id}/file")
async def download_nfo(
    movie_id: int,
    kodi: bool = Query(False, description="输出 Kodi 兼容的额外字段"),
    session: AsyncSession = Depends(get_session),
):
    """下载 NFO 文件

    - 默认输出 Emby/Jellyfin 兼容格式
    - `kodi=true` 时追加 Kodi 期望的额外字段
    """
    movie = await _get_movie_with_relations(session, movie_id)
    actors = await _get_movie_actors(session, movie_id)
    tags = await _get_movie_tags(session, movie_id)

    root = _build_nfo_xml(movie, actors, tags, kodi=kodi)

    if kodi and movie.file_path:
        streamdetails = await _build_streamdetails_async(movie.file_path)
        if streamdetails is not None:
            fileinfo = ET.SubElement(root, "fileinfo")
            fileinfo.append(streamdetails)

    xml_str = _prettify_xml(root)

    filename = f"{movie.code}.nfo"
    return Response(
        content=xml_str.encode("utf-8"),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/import")
async def import_nfo(
    xml_content: Optional[str] = Body(None, description="NFO XML 字符串"),
    file: Optional[UploadFile] = File(None, description="NFO 文件上传"),
    session: AsyncSession = Depends(get_session),
):
    """
    导入 NFO（接收 XML 字符串或文件上传，解析并更新/创建电影）

    优先使用文件上传，其次使用 XML 字符串。
    通过 <id> (番号) 匹配已有电影，更新缺失字段。
    """
    # 获取 XML 内容
    content = None
    if file:
        content = (await file.read()).decode("utf-8-sig", errors="ignore")
    elif xml_content:
        content = xml_content

    if not content:
        raise HTTPException(status_code=400, detail="请提供 NFO XML 内容或上传文件")

    # 解析 XML
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"XML 解析失败: {e}")

    if root.tag not in ("movie", "episodedetails", "tvshow"):
        raise HTTPException(status_code=400, detail=f"不支持的根元素: {root.tag}，期望 movie/episodedetails/tvshow")

    # 提取字段
    # 优先 <id>，Kodi 兼容字段 <code> 和 <uniqueId> 作为兜底
    code = _get_element_text(root, "id")
    if not code:
        code = _get_element_text(root, "code")
    if not code:
        unique_id_elem = root.find("uniqueId")
        if unique_id_elem is not None and unique_id_elem.text:
            code = unique_id_elem.text.strip()
    if not code:
        # 尝试从标题提取番号
        title = _get_element_text(root, "title")
        if title:
            from app.scraper.number import extract_number
            number_result = extract_number(title)
            if number_result and number_result.number:
                code = number_result.number.upper()

    if not code:
        raise HTTPException(status_code=400, detail="NFO 中未找到番号 (<id>/<code>/<uniqueId> 标签)，且无法从标题提取")

    code = code.strip().upper()

    # 查找已有电影
    result = await session.execute(select(Movie).where(Movie.code == code))
    movie = result.scalar_one_or_none()

    updated_fields = []
    created = False

    if movie is None:
        # 创建新电影
        movie = Movie(code=code, status="pending")
        session.add(movie)
        created = True
        updated_fields.append("code")

    # 更新缺失字段
    def _update_field(field_name: str, xml_tag: str):
        if getattr(movie, field_name) is None:
            value = _get_element_text(root, xml_tag)
            if value:
                setattr(movie, field_name, value)
                updated_fields.append(field_name)

    _update_field("title", "title")
    _update_field("title_jp", "originaltitle")
    _update_field("plot", "plot")
    _update_field("studio", "studio")
    _update_field("maker", "maker")
    _update_field("director", "director")
    _update_field("release_date", "premiered")
    # Kodi 兼容：<aired> 作为 <premiered> 的兜底
    if movie.release_date is None:
        _update_field("release_date", "aired")

    # 年份
    if movie.release_date is None:
        year_str = _get_element_text(root, "year")
        if year_str:
            movie.release_date = f"{year_str}-01-01"
            updated_fields.append("release_date")

    # 时长
    if movie.duration is None:
        runtime_str = _get_element_text(root, "runtime")
        if runtime_str:
            import re
            match = re.search(r'(\d+)', runtime_str)
            if match:
                movie.duration = int(match.group(1))
                updated_fields.append("duration")

    # 评分
    if movie.rating is None:
        rating_str = _get_element_text(root, "rating")
        # Kodi 兼容：<ratings><rating><value>8.5</value></rating></ratings>
        if not rating_str:
            ratings_elem = root.find("ratings")
            if ratings_elem is not None:
                rating_inner = ratings_elem.find("rating")
                if rating_inner is not None:
                    value_elem = rating_inner.find("value")
                    if value_elem is not None and value_elem.text:
                        rating_str = value_elem.text.strip()
        if rating_str:
            try:
                movie.rating = float(rating_str)
                updated_fields.append("rating")
            except ValueError:
                pass

    # 有码/无码
    if movie.is_mosaic is None:
        mpaa = _get_element_text(root, "mpaa")
        if mpaa:
            movie.is_mosaic = "有码" in mpaa
            updated_fields.append("is_mosaic")

    # 标签 (genre)
    if movie.genre is None:
        genres = _get_element_texts(root, "genre")
        if genres:
            movie.genre = json.dumps(genres, ensure_ascii=False)
            updated_fields.append("genre")

    # 额外标签 (tag)
    if movie.tag is None:
        tags = _get_element_texts(root, "tag")
        if tags:
            movie.tag = json.dumps(tags, ensure_ascii=False)
            updated_fields.append("tag")

    # 封面
    if movie.cover_url is None:
        for thumb_elem in root.findall("thumb"):
            aspect = thumb_elem.get("aspect", "")
            if aspect == "poster" and thumb_elem.text:
                movie.cover_url = thumb_elem.text.strip()
                updated_fields.append("cover_url")
                break
        # 如果没有 poster aspect 的 thumb，取第一个 thumb
        if movie.cover_url is None:
            first_thumb = root.find("thumb")
            if first_thumb is not None and first_thumb.text:
                movie.cover_url = first_thumb.text.strip()
                updated_fields.append("cover_url")

    # 演员
    actor_names = []
    for actor_elem in root.findall("actor"):
        actor_name = _get_element_text(actor_elem, "name")
        if actor_name:
            actor_names.append(actor_name)

    if actor_names:
        # 查找或创建演员，关联到电影
        for actor_name in actor_names:
            # 查找已有演员
            actor_result = await session.execute(
                select(Actor).where(Actor.name == actor_name)
            )
            actor = actor_result.scalar_one_or_none()

            if actor is None:
                # 尝试从 NFO 获取头像
                avatar_url = None
                for actor_elem in root.findall("actor"):
                    name_elem = actor_elem.find("name")
                    if name_elem is not None and name_elem.text and name_elem.text.strip() == actor_name:
                        thumb_elem = actor_elem.find("thumb")
                        if thumb_elem is not None and thumb_elem.text:
                            avatar_url = thumb_elem.text.strip()
                        break

                actor = Actor(name=actor_name, avatar_url=avatar_url)
                session.add(actor)
                await session.flush()  # 获取 actor.id

            # 检查是否已关联
            link_result = await session.execute(
                select(MovieActor).where(
                    MovieActor.movie_id == movie.id,
                    MovieActor.actor_id == actor.id,
                )
            )
            if link_result.scalar_one_or_none() is None:
                session.add(MovieActor(movie_id=movie.id, actor_id=actor.id))
                updated_fields.append(f"actor:{actor_name}")

    await session.commit()
    await session.refresh(movie)

    return {
        "status": "ok",
        "created": created,
        "movie_id": movie.id,
        "code": movie.code,
        "updated_fields": updated_fields,
    }


@router.post("/batch-export")
async def batch_export_nfo(
    movie_ids: list[int] = Body(..., description="电影 ID 列表"),
    kodi: bool = Query(False, description="输出 Kodi 兼容的额外字段"),
    session: AsyncSession = Depends(get_session),
):
    """批量导出 NFO（接收 movie_ids 列表，返回 zip 文件）

    - 默认输出 Emby/Jellyfin 兼容格式
    - `kodi=true` 时追加 Kodi 期望的额外字段（含 fileinfo/streamdetails）
    """
    if not movie_ids:
        raise HTTPException(status_code=400, detail="请提供电影 ID 列表")

    if len(movie_ids) > 100:
        raise HTTPException(status_code=400, detail="单次最多导出 100 部电影")

    # 查询所有电影
    result = await session.execute(
        select(Movie).where(Movie.id.in_(movie_ids))
    )
    movies = result.scalars().all()

    if not movies:
        raise HTTPException(status_code=404, detail="未找到指定电影")

    # 构建 zip 文件
    zip_buffer = io.BytesIO()
    exported = []
    skipped = []

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for movie in movies:
            try:
                actors = await _get_movie_actors(session, movie.id)
                tags = await _get_movie_tags(session, movie.id)

                root = _build_nfo_xml(movie, actors, tags, kodi=kodi)

                if kodi and movie.file_path:
                    streamdetails = await _build_streamdetails_async(movie.file_path)
                    if streamdetails is not None:
                        fileinfo = ET.SubElement(root, "fileinfo")
                        fileinfo.append(streamdetails)

                xml_str = _prettify_xml(root)

                filename = f"{movie.code}.nfo"
                zf.writestr(filename, xml_str.encode("utf-8"))
                exported.append({"id": movie.id, "code": movie.code, "filename": filename})
            except Exception as e:
                logger.error(f"导出 NFO 失败 (movie_id={movie.id}): {e}")
                skipped.append({"id": movie.id, "code": movie.code, "error": str(e)})

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=nfo_export.zip",
            "X-Exported-Count": str(len(exported)),
            "X-Skipped-Count": str(len(skipped)),
        },
    )


async def _build_streamdetails_async(file_path: str) -> Optional[ET.Element]:
    """异步调用 ffprobe 解析视频流信息，构建 <streamdetails> 元素

    Args:
        file_path: 视频文件绝对路径

    Returns:
        streamdetails Element，或 None（ffprobe 不可用/解析失败/文件不存在）
    """
    import os

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    if not file_path or not os.path.exists(file_path):
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode != 0:
            return None
        data = json.loads(stdout.decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.debug(f"ffprobe 异步解析失败 {file_path}: {e}")
        return None

    streamdetails = ET.Element("streamdetails")

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            video_elem = ET.SubElement(streamdetails, "video")
            _add_text_element(video_elem, "codec", stream.get("codec_name"))
            if stream.get("width") and stream.get("height"):
                _add_text_element(video_elem, "width", str(stream["width"]))
                _add_text_element(video_elem, "height", str(stream["height"]))
                try:
                    aspect = round(stream["width"] / stream["height"], 2)
                    _add_text_element(video_elem, "aspect", f"{aspect:.2f}")
                except (ZeroDivisionError, TypeError):
                    pass
            if stream.get("duration"):
                try:
                    dur = float(stream["duration"])
                    _add_text_element(video_elem, "durationinseconds", str(int(dur)))
                except (TypeError, ValueError):
                    pass
        elif codec_type == "audio":
            audio_elem = ET.SubElement(streamdetails, "audio")
            _add_text_element(audio_elem, "codec", stream.get("codec_name"))
            if stream.get("channels"):
                _add_text_element(audio_elem, "channels", str(stream["channels"]))
            lang = stream.get("language") or stream.get("tags", {}).get("language")
            if lang:
                _add_text_element(audio_elem, "language", lang)
        elif codec_type == "subtitle":
            sub_elem = ET.SubElement(streamdetails, "subtitle")
            lang = stream.get("language") or stream.get("tags", {}).get("language")
            if lang:
                _add_text_element(sub_elem, "language", lang)

    # 时长（从 format 段获取）
    fmt = data.get("format", {})
    if fmt.get("duration"):
        try:
            dur = float(fmt["duration"])
            video_elem = streamdetails.find("video")
            if video_elem is not None and video_elem.find("duration") is None:
                _add_text_element(video_elem, "duration", str(int(dur // 60)))
        except (TypeError, ValueError):
            pass

    # 若无任何子元素，返回 None
    if len(list(streamdetails)) == 0:
        return None
    return streamdetails


def _get_element_text(elem: ET.Element, tag: str) -> Optional[str]:
    """获取 XML 元素的文本内容"""
    child = elem.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _get_element_texts(elem: ET.Element, tag: str) -> list[str]:
    """获取 XML 元素的所有同名子元素文本"""
    results = []
    for child in elem.findall(tag):
        if child.text:
            results.append(child.text.strip())
    return results
