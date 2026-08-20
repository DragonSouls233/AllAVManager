"""
NFO 文件生成器

生成 Emby/Jellyfin/Kodi 兼容的 NFO 文件。
字段对齐 JavInfo 真实样例(SSIS-018.nfo),覆盖 40+ 字段。
plot/outline/originalplot 使用 CDATA 包裹,避免特殊字符破坏 XML。
"""

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List
from xml.dom import minidom

from app.crawlers.base import ActorInfo, ScrapeResult

logger = logging.getLogger(__name__)

# 需要 CDATA 包裹的字段(文本类,可能含 & < > 等特殊字符)
_CDATA_FIELDS = {"plot", "outline", "originalplot", "tagline"}


def _g(result, name: str, default=None):
    """统一从 result 取字段，兼容 dataclass / SimpleNamespace / dict / None。

    2026-08-18: strategy.py 传进来的 nfo_data 是 SimpleNamespace，NFO 内部原本
    大量直访 result.xxx 在字段缺失时会 AttributeError。统一用 _g 兜底 None。
    """
    if result is None:
        return default
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


class NFOGenerator:
    """
    NFO 文件生成器

    生成 Emby/Jellyfin/Kodi 兼容的 NFO 文件。
    当 kodi_compatible=True 时，额外输出 Kodi 期望的字段：
    - <uniqueId> / <ratings> / <userrating> / <top250>
    - <country> / <credits> / <code> / <aired>
    - <tagline> / <playcount> / <lastplayed> / <dateadded>
    - <art> 块（poster/fanart/thumb/landscape/banner/clearart/clearlogo）
    - <fileinfo><streamdetails> 块（如可获取文件流信息）
    """

    def __init__(self, output_dir: str):
        """
        初始化 NFO 生成器

        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)

    def generate(
        self,
        result: ScrapeResult,
        movie_dir: Optional[str] = None,
        filename: str = "movie.nfo",
        kodi_compatible: bool = False,
    ) -> Optional[str]:
        """
        生成 NFO 文件

        Args:
            result: 刮削结果
            movie_dir: 电影目录（默认使用 output_dir）
            filename: 文件名
            kodi_compatible: 是否输出 Kodi 兼容的额外字段（uniqueId/ratings/art/fileinfo 等）

        Returns:
            生成的文件路径
        """
        if movie_dir:
            save_dir = Path(movie_dir)
        else:
            save_dir = self.output_dir

        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / filename

        try:
            # 构建 XML
            root = self._build_xml(result, kodi_compatible=kodi_compatible)

            # 格式化输出
            xml_str = self._prettify(root)

            # 写入文件
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(xml_str)

            logger.info(f"NFO已生成: {save_path}")
            return str(save_path)

        except Exception as e:
            logger.error(f"生成NFO失败: {e}")
            return None

    def build_xml_string(self, result: ScrapeResult, kodi_compatible: bool = True) -> str:
        """从 ScrapeResult 直接构建 NFO XML 字符串(不写文件).

        用于 PATCH /movies/{id} 时回写 movie.nfo —— 调用方传入 movie_dir 自行落盘,
        或直接用 save_to_path(movie_dir) 落地。
        """
        root = self._build_xml(result, kodi_compatible=kodi_compatible)
        return self._prettify(root)

    def save_to_path(self, xml_str: str, save_path) -> str:
        """把 XML 字符串写到文件路径."""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(xml_str)
        logger.info(f"NFO已生成: {save_path}")
        return str(save_path)

    def generate_from_movie(
        self,
        movie,
        movie_dir: Optional[str] = None,
        filename: str = "movie.nfo",
        kodi_compatible: bool = True,
        actor_names: Optional[List[str]] = None,
    ) -> Optional[str]:
        """从 Movie ORM 写 NFO.

        适用场景: 用户在网页编辑表单改完字段, PATCH 端点调用此方法把最新 DB 字段回写到 movie.nfo,
        与 Emby/Jellyfin/Kodi 保持一致。

        Args:
            movie: SQLAlchemy Movie ORM
            movie_dir: 落盘目录; 默认用 movie.output_dir(若存在)或 movie.file_path 父目录
            filename: 文件名(默认 movie.nfo)
            kodi_compatible: 是否包含 Kodi 增强字段
            actor_names: 演员名列表(由调用方提供,因为 ORM 关系可能未预加载)

        Returns:
            落盘文件路径,失败返回 None
        """
        try:
            from app.crawlers.base import ActorInfo

            # 解析 release_date
            release_date = None
            rd = getattr(movie, "release_date", None)
            if rd:
                if isinstance(rd, str):
                    # 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' → date
                    try:
                        release_date = datetime.strptime(rd[:10], "%Y-%m-%d").date()
                    except Exception:
                        release_date = None
                elif isinstance(rd, date):
                    release_date = rd

            # 解析 genre / tag (DB 里是 JSON 字符串)
            genres = self._parse_json_field(getattr(movie, "genre", None))
            tags = self._parse_json_field(getattr(movie, "tag", None))

            # 解析 sample_images
            sample_images = self._parse_json_field(getattr(movie, "sample_images", None))

            # actors 转 ActorInfo
            actors_objs = []
            for n in (actor_names or []):
                if not n: continue
                actors_objs.append(ActorInfo(name=str(n)))

            # 解析 directors (DB 是逗号字符串)
            director_field = getattr(movie, "director", None) or ""
            directors = [d.strip() for d in str(director_field).split(",") if d.strip()]

            # 构造 ScrapeResult (注意: ScrapeResult 字段是 dataclass, 必填 code/title/source)
            # 2026-08-18: 字符串列优先，relationship 仅兜底。
            # async 环境访问未预加载的 lazy relationship（studio_ref/series_ref）
            # 会抛 MissingGreenlet（greenlet_spawn has not been called），
            # 因此包 try/except，优先读同步可靠的字符串列 studio/series。
            studio = getattr(movie, "studio", None) or None
            if not studio:
                try:
                    studio = getattr(movie.studio_ref, "name", None)
                except Exception:
                    studio = None
            series = getattr(movie, "series", None) or None
            if not series:
                try:
                    series = getattr(movie.series_ref, "name", None)
                except Exception:
                    series = None
            result = ScrapeResult(
                code=getattr(movie, "code", "") or "",
                title=getattr(movie, "title", "") or getattr(movie, "code", "") or "",
                source=getattr(movie, "source", None) or "manual",
                original_title=getattr(movie, "original_title", None) or getattr(movie, "title_jp", None),
                studio=studio,
                maker=getattr(movie, "maker", None),
                series=series,
                release_date=release_date,
                duration=getattr(movie, "duration", None),
                plot=getattr(movie, "plot", None),
                # plot_short 不在 ScrapeResult 字段, 留给 NFO 输出逻辑用 getattr
                genres=genres,
                tags=tags,
                actors=actors_objs,
                all_actors=[a.name for a in actors_objs],
                directors=directors,
                is_mosaic=getattr(movie, "is_mosaic", None),
                is_uncensored=getattr(movie, "is_uncensored", None),
                is_chinese=getattr(movie, "is_chinese", None),
                cover_url=getattr(movie, "cover_url", None),
                poster_url=getattr(movie, "poster_url", None),
                trailer_url=getattr(movie, "trailer_url", None),
                sample_images=sample_images if isinstance(sample_images, list) else [],
                extrafanart=[],
                rating=getattr(movie, "rating", None),
            )
            # plot_short 用 setattr 注入(NFO 生成器内部用 getattr 读)
            try:
                setattr(result, "plot_short", getattr(movie, "plot_short", None))
            except Exception:
                pass

            # 决定 movie_dir: 优先 output_dir(用户配置的标准输出位置), fallback file_path.parent
            if not movie_dir:
                movie_dir = getattr(movie, "output_dir", None) or None
                if not movie_dir and getattr(movie, "file_path", None):
                    movie_dir = str(Path(movie.file_path).parent)
            if not movie_dir:
                logger.warning(f"generate_from_movie: 无法决定 movie_dir (movie id={getattr(movie, 'id', '?')})")
                return None

            return self.generate(
                result=result,
                movie_dir=movie_dir,
                filename=filename,
                kodi_compatible=kodi_compatible,
            )
        except Exception as e:
            logger.error(f"从影片生成NFO失败: {e}")
            return None

    @staticmethod
    def _normalize_date(value):
        """把 release_date / last_played_at 统一成 date/datetime。

        scraped_data 里的日期字段可能是字符串(如 NFO 缓存的 .isoformat(),
        或 scraper 直接塞的 str),而 NFO 生成器内部用 .strftime()。这里做容错转换,
        避免 'str' object has no attribute 'strftime'。
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            # 完整字符串优先(可能含时间), 再退化为前 19 / 10 位; datetime 格式优先于纯日期
            candidates = [s, s[:19], s[:10]]
            fmts = [
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d",
                "%Y/%m/%d",
            ]
            for c in candidates:
                for fmt in fmts:
                    try:
                        return datetime.strptime(c, fmt)
                    except Exception:
                        continue
            return None
        return None

    @staticmethod
    def _parse_json_field(v) -> list:
        """Movie ORM 上 genre/tag/sample_images 是 JSON 字符串."""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                import json
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
            # 退化: 逗号分隔
            return [s.strip() for s in v.split(",") if s.strip()]
        return []

    def _build_xml(self, result: ScrapeResult, kodi_compatible: bool = False) -> ET.Element:
        """构建 XML 结构

        字段对齐 JavInfo 真实样例(SSIS-018.nfo),覆盖 40+ 字段。
        """
        root = ET.Element("movie")

        # 兼容 release_date / last_played_at 可能为字符串的情况：
        # - scraper 的 ScrapeResult.release_date 实际常是 str（dataclass 不强制类型）
        # - NFO 缓存命中时 strategy.py 用 .isoformat() 存成字符串
        # _build_xml 内部对这两个字段调 .strftime(), 这里统一转换为 date/datetime,
        # 避免 'str' object has no attribute 'strftime'。
        release_date = self._normalize_date(_g(result, "release_date"))
        last_played = self._normalize_date(_g(result, "last_played_at"))

        # === 标题信息 ===
        self._add_element(root, "title", _g(result, "title"))
        # originaltitle: 日语原标题(修复:原来错误地设为 title)
        original_title = _g(result, "original_title") or _g(result, "title")
        self._add_element(root, "originaltitle", original_title)
        # sorttitle: 优先用日语标题排序,与 JavInfo 一致
        self._add_element(root, "sorttitle", original_title)
        # id: 番号
        self._add_element(root, "id", _g(result, "code"))
        # num: 番号(JavInfo 约定字段,与 id 并存)
        self._add_element(root, "num", _g(result, "code"))

        # === 简介(CDATA 包裹) ===
        if _g(result, "plot"):
            self._add_cdata_element(root, "plot", _g(result, "plot"))
            # outline: 短简介(若 plot_short 存在则用,否则用 plot)
            plot_short = _g(result, "plot_short") or _g(result, "plot")
            self._add_cdata_element(root, "outline", plot_short)

        # originalplot: 日语原简介(关键缺失字段)
        original_plot = _g(result, "original_plot") or _g(result, "plot_jp")
        if original_plot:
            self._add_cdata_element(root, "originalplot", original_plot)

        # tagline: 宣传语(用发行日期或 plot_short)
        if release_date:
            self._add_cdata_element(root, "tagline", f"发行日期 {release_date.strftime('%Y-%m-%d')}")
        elif _g(result, "plot_short"):
            self._add_cdata_element(root, "tagline", _g(result, "plot_short"))

        # === 日期 ===
        if release_date:
            date_str = release_date.strftime("%Y-%m-%d")
            self._add_element(root, "premiered", date_str)
            self._add_element(root, "releasedate", date_str)
            self._add_element(root, "release", date_str)
            self._add_element(root, "year", str(release_date.year))

        # === 时长 ===
        if _g(result, "duration"):
            self._add_element(root, "runtime", str(_g(result, "duration")))

        # === 评分(对齐 SSIS-018.nfo) ===
        rating = _g(result, "rating")
        if rating is not None:
            self._add_element(root, "rating", f"{rating:.1f}")
            # criticrating: 影评人评分(rating × 10)
            self._add_element(root, "criticrating", str(int(rating * 10)))
        # votes: 评分人数
        votes = _g(result, "votes")
        if votes is not None:
            self._add_element(root, "votes", str(votes))

        # === 分级 ===
        # mpaa: JavInfo 用 "JP-18+" 格式,非中文"有码/无码"
        is_mosaic = _g(result, "is_mosaic")
        if is_mosaic is True:
            self._add_element(root, "mpaa", "JP-18+")
            self._add_element(root, "customrating", "JP-18+")
        elif is_mosaic is False:
            self._add_element(root, "mpaa", "JP-18+")  # 无码也是 18+
            self._add_element(root, "customrating", "JP-18+")
        # countrycode: 国家代码
        self._add_element(root, "countrycode", "JP")

        # === 制作信息 ===
        if _g(result, "studio"):
            self._add_element(root, "studio", _g(result, "studio"))
        if _g(result, "maker"):
            self._add_element(root, "maker", _g(result, "maker"))
        # publisher: 发行商(关键缺失字段)
        publisher = _g(result, "publisher") or _g(result, "maker")
        if publisher:
            self._add_element(root, "publisher", publisher)
        # label: 厂牌(关键缺失字段)
        label = _g(result, "label") or _g(result, "series")
        if label:
            self._add_element(root, "label", label)

        # === 导演(关键缺失字段) ===
        for director in _g(result, "directors", []) or []:
            self._add_element(root, "director", director)

        # === 系列 ===
        if _g(result, "series"):
            set_elem = ET.SubElement(root, "set")
            name_elem = ET.SubElement(set_elem, "name")
            name_elem.text = _g(result, "series")

        # === 标签 ===
        # 优先级标签（内容类型，如"女仆/护士/人妻"）前置，媒体库展示首要类型
        # （移植 ref42-Kesuy-mdcx mdcx/core/tag_priority.py；资源缺失时原序输出）
        from app.utils.tag_priority import prioritize_nfo_tags

        genres = list(_g(result, "genres", []) or [])
        genres = prioritize_nfo_tags(genres)
        for genre in genres:
            self._add_element(root, "genre", genre)
            self._add_element(root, "tag", genre)
        # 额外标签
        for tag in prioritize_nfo_tags(list(_g(result, "tags", []) or [])):
            if tag not in genres:
                self._add_element(root, "tag", tag)

        # === 演员(对齐 SSIS-018.nfo:含 type 子元素) ===
        for actor in _g(result, "actors", []) or []:
            self._add_actor(root, actor)
        # 男演员(导演/演员)
        all_actors = _g(result, "all_actors", []) or []
        actors = _g(result, "actors", []) or []
        for actor_name in all_actors:
            if not any(a.name == actor_name for a in actors):
                actor_elem = ET.SubElement(root, "actor")
                name_elem = ET.SubElement(actor_elem, "name")
                name_elem.text = actor_name
                type_elem = ET.SubElement(actor_elem, "type")
                type_elem.text = "Actor"

        # === 图片(对齐 SSIS-018.nfo:独立 poster/cover 字段) ===
        if _g(result, "cover_url"):
            self._add_element(root, "cover", _g(result, "cover_url"))
            thumb_elem = ET.SubElement(root, "thumb")
            thumb_elem.text = _g(result, "cover_url")
            thumb_elem.set("aspect", "poster")
        if _g(result, "poster_url"):
            self._add_element(root, "poster", _g(result, "poster_url"))
            thumb_elem2 = ET.SubElement(root, "thumb")
            thumb_elem2.text = _g(result, "poster_url")
            thumb_elem2.set("aspect", "poster")
        for i, sample_url in enumerate(_g(result, "sample_images", []) or []):
            thumb_elem = ET.SubElement(root, "thumb")
            thumb_elem.text = sample_url
            thumb_elem.set("aspect", f"fanart{i+1}")

        # === 预告片 ===
        if _g(result, "trailer_url"):
            self._add_element(root, "trailer", _g(result, "trailer_url"))

        # === 来源信息(对齐 SSIS-018.nfo:website/javdbid) ===
        self._add_element(root, "source", _g(result, "source"))
        # website: 源站链接
        source_url = _g(result, "source_url") or _g(result, "website")
        if source_url:
            self._add_element(root, "website", source_url)
        # javdbid: JavDB 视频 ID(关键缺失字段)
        javdb_id = _g(result, "javdb_id")
        if not javdb_id:  # A1 匿名兜底把它放 raw_data 里
            raw_data = self._coerce_raw_data(result)
            javdb_id = raw_data.get("javdb_id")
        if javdb_id:
            self._add_element(root, "javdbid", javdb_id)

        # === 磁力链接（来自 raw_data["magnets"]，通常由 JavDB 匿名 App API 兜底拉取） ===
        self._add_magnets(root, result)

        # === Kodi 兼容额外字段 ===
        if kodi_compatible:
            self._add_kodi_extras(root, result)

        return root

    def _coerce_raw_data(self, result) -> dict:
        """统一从 result 拿到 raw_data dict。

        result 可能是 ScrapeResult(dataclass) / SimpleNamespace / 字典，
        这里用 hasattr + dict 分支判断兜底所有可能形态，避免 'X has no attribute raw_data'。
        """
        if result is None:
            return {}
        if isinstance(result, dict):
            return result.get("raw_data") or {}
        raw = getattr(result, "raw_data", None)
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if hasattr(raw, "to_dict"):
            try:
                d = raw.to_dict()
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}
        if hasattr(raw, "__dict__"):
            return dict(raw.__dict__) or {}
        return {}

    def _add_magnets(self, root: ET.Element, result: ScrapeResult) -> None:
        """把 raw_data['magnets'] 写入 <magnet> 标签。

        JavDB 匿名 App API 兜底（app.crawlers.javdb._scrape_via_app_api）会往
        raw_data['magnets'] 写入磁力列表，每个元素形如：
            {"name", "hash", "size", "cnsub", "hd", "magnet_uri"}
        这里兼容两种数据源：带 magnet_uri 的 App API 磁力，以及 MagnetInfo.to_dict()。
        """
        raw = self._coerce_raw_data(result)
        magnets = raw.get("magnets") or []
        if not magnets:
            return
        for m in magnets:
            if not isinstance(m, dict):
                continue
            uri = m.get("magnet_uri") or m.get("link") or m.get("url")
            if not uri:
                h = m.get("hash")
                if h:
                    uri = f"magnet:?xt=urn:btih:{h}"
            if not uri:
                continue
            magnet_elem = ET.SubElement(root, "magnet")
            magnet_elem.text = uri
            magnet_elem.set("name", str(m.get("name") or ""))
            if m.get("size"):
                magnet_elem.set("size", str(m.get("size")))
            if m.get("cnsub"):
                magnet_elem.set("cnsub", "true")
            if m.get("hd"):
                magnet_elem.set("hd", "true")

    def _add_kodi_extras(self, root: ET.Element, result: ScrapeResult) -> None:
        """添加 Kodi 兼容的额外字段

        release_date 可能为字符串(同 _build_xml 的容错说明), 这里统一归一化。
        """
        release_date = self._normalize_date(_g(result, "release_date"))

        # Kodi NFO 规范参考：https://kodi.wiki/view/NFO_files/Movies
        # 主要补充以下字段（与 Emby/Jellyfin 共有部分会去重）：
        # - <uniqueId>：唯一标识（番号 + 来源）
        # - <ratings>：评分聚合（含 max/votes/default 属性）
        # - <userrating>：用户评分（1-10）
        # - <country>：出品国家（默认 Japan）
        # - <code>：番号（Kodi 专用字段）
        # - <aired>：播出日期（Kodi 使用此字段而非 premiered）
        # - <tagline>：副标题/宣传语
        # - <dateadded>：入库时间（ISO 8601）
        # - <playcount>：播放次数
        # - <lastplayed>：最后播放时间
        # - <art>：艺术图块（poster/fanart/thumb/landscape/banner/clearart/clearlogo）
        # - <fileinfo><streamdetails>：视频/音频/字幕流信息（如可获取）
        # uniqueId：番号作为唯一标识
        unique_id = ET.SubElement(root, "uniqueId")
        unique_id.text = _g(result, "code")
        unique_id.set("type", "jav")
        unique_id.set("default", "true")

        # ratings 评分聚合（Kodi 要求嵌套结构）
        rating = _g(result, "rating")
        if rating:
            ratings_elem = ET.SubElement(root, "ratings")
            rating_elem = ET.SubElement(ratings_elem, "rating")
            rating_elem.set("name", "mdcx")
            rating_elem.set("max", "10")
            rating_elem.set("default", "true")
            value_elem = ET.SubElement(rating_elem, "value")
            value_elem.text = f"{rating:.1f}"
            votes_elem = ET.SubElement(rating_elem, "votes")
            votes_elem.text = "0"

        # 番号（Kodi 专用 code 字段，与 <id> 并列）
        self._add_element(root, "code", _g(result, "code"))

        # 国家（日本 AV 默认 Japan）
        self._add_element(root, "country", "Japan")

        # aired（Kodi 使用此字段识别播出日期）
        if release_date:
            self._add_element(root, "aired", release_date.strftime("%Y-%m-%d"))

        # tagline（如有 plot_short 则用之，否则省略）
        plot_short = _g(result, "plot_short")
        if plot_short:
            self._add_element(root, "tagline", plot_short)

        # dateadded（入库时间，ISO 8601）
        self._add_element(root, "dateadded", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # playcount / lastplayed（ScrapeResult 可选携带，来自观影历史 PlayHistory）
        play_count = _g(result, "play_count")
        if play_count:
            self._add_element(root, "playcount", str(play_count))

        last_played = self._normalize_date(_g(result, "last_played_at"))
        if last_played:
            self._add_element(root, "lastplayed", last_played.strftime("%Y-%m-%d %H:%M:%S"))

        # art 块（Kodi 期望独立 <art> 块，与 <thumb> 并列）
        art_elem = ET.SubElement(root, "art")
        poster_url = _g(result, "poster_url") or _g(result, "cover_url")
        if poster_url:
            self._add_element(art_elem, "poster", poster_url)
        sample_images = _g(result, "sample_images", []) or []
        if sample_images:
            self._add_element(art_elem, "fanart", sample_images[0])
            if len(sample_images) > 1:
                self._add_element(art_elem, "thumb", sample_images[1])
        cover_url = _g(result, "cover_url")
        if cover_url:
            self._add_element(art_elem, "landscape", cover_url)
            self._add_element(art_elem, "banner", cover_url)
            self._add_element(art_elem, "clearart", cover_url)
            self._add_element(art_elem, "clearlogo", cover_url)

        # fileinfo/streamdetails（通过 ffprobe 解析视频流信息,ffprobe 不可用时跳过）
        file_path = _g(result, "file_path")
        if file_path:
            streamdetails = self._build_streamdetails(file_path)
            if streamdetails is not None:
                fileinfo = ET.SubElement(root, "fileinfo")
                fileinfo.append(streamdetails)

    def _add_element(
        self,
        parent: ET.Element,
        tag: str,
        text: Optional[str] = None,
        **attribs,
    ) -> ET.Element:
        """添加 XML 元素"""
        elem = ET.SubElement(parent, tag)

        if text:
            elem.text = text

        for key, value in attribs.items():
            elem.set(key, str(value))

        return elem

    def _add_cdata_element(
        self,
        parent: ET.Element,
        tag: str,
        text: Optional[str] = None,
    ) -> ET.Element:
        """添加 CDATA 包裹的 XML 元素

        用于 plot/outline/originalplot 等可能含 & < > 特殊字符的字段。
        由于 stdlib ET 不直接支持 CDATA 创建,通过预处理方式实现:
        先用占位文本创建元素,在 _prettify 阶段替换为 CDATA。
        """
        elem = ET.SubElement(parent, tag)
        if text:
            # 用占位符包裹,后续 _prettify 时替换
            elem.text = f"__CDATA_START__{text}__CDATA_END__"
        return elem

    def _add_actor(self, parent: ET.Element, actor: ActorInfo) -> None:
        """添加演员元素(对齐 SSIS-018.nfo:含 type 子元素)"""
        actor_elem = ET.SubElement(parent, "actor")

        name_elem = ET.SubElement(actor_elem, "name")
        name_elem.text = actor.name

        # type: Actor(对齐 SSIS-018.nfo)
        type_elem = ET.SubElement(actor_elem, "type")
        type_elem.text = "Actor"

        jp_name = getattr(actor, "japanese_name", None)
        if jp_name:
            jp_name_elem = ET.SubElement(actor_elem, "alt_name")
            jp_name_elem.text = jp_name

        avatar = getattr(actor, "avatar_url", None)
        if avatar:
            thumb_elem = ET.SubElement(actor_elem, "thumb")
            thumb_elem.text = avatar

    def _build_streamdetails(self, file_path: str) -> Optional[ET.Element]:
        """通过 ffprobe 解析视频流信息，构建 <streamdetails> 元素

        Args:
            file_path: 视频文件绝对路径

        Returns:
            streamdetails Element，或 None（ffprobe 不可用/解析失败）
        """
        import json
        import subprocess

        from app.utils.bin_tools import get_tool_path

        ffprobe = get_tool_path("ffprobe")
        if not os.path.isfile(ffprobe):
            return None

        try:
            cmd = [
                ffprobe, "-v", "quiet", "-print_format", "json",
                "-show_streams", "-show_format", file_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                                 encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                return None
            data = json.loads(proc.stdout)
        except Exception as e:
            logger.debug(f"ffprobe 解析失败 {file_path}: {e}")
            return None

        streamdetails = ET.Element("streamdetails")

        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video":
                video_elem = ET.SubElement(streamdetails, "video")
                self._add_element(video_elem, "codec", stream.get("codec_name"))
                if stream.get("width") and stream.get("height"):
                    self._add_element(video_elem, "width", str(stream["width"]))
                    self._add_element(video_elem, "height", str(stream["height"]))
                    # 计算宽高比
                    try:
                        aspect = round(stream["width"] / stream["height"], 2)
                        self._add_element(video_elem, "aspect", f"{aspect:.2f}")
                    except (ZeroDivisionError, TypeError):
                        pass
                if stream.get("duration"):
                    try:
                        dur = float(stream["duration"])
                        self._add_element(video_elem, "durationinseconds", str(int(dur)))
                    except (TypeError, ValueError):
                        pass
            elif codec_type == "audio":
                audio_elem = ET.SubElement(streamdetails, "audio")
                self._add_element(audio_elem, "codec", stream.get("codec_name"))
                if stream.get("channels"):
                    self._add_element(audio_elem, "channels", str(stream["channels"]))
                lang = stream.get("language") or stream.get("tags", {}).get("language")
                if lang:
                    self._add_element(audio_elem, "language", lang)
            elif codec_type == "subtitle":
                sub_elem = ET.SubElement(streamdetails, "subtitle")
                lang = stream.get("language") or stream.get("tags", {}).get("language")
                if lang:
                    self._add_element(sub_elem, "language", lang)

        # 时长（从 format 段获取，更准确）
        fmt = data.get("format", {})
        if fmt.get("duration"):
            try:
                dur = float(fmt["duration"])
                # 找到 video 元素并写入 duration（分钟）
                video_elem = streamdetails.find("video")
                if video_elem is not None and video_elem.find("duration") is None:
                    self._add_element(video_elem, "duration", str(int(dur // 60)))
            except (TypeError, ValueError):
                pass

        return streamdetails

    def _prettify(self, elem: ET.Element) -> str:
        """格式化 XML 输出,并将 CDATA 占位符替换为真实 CDATA 包裹"""
        rough_string = ET.tostring(elem, encoding="unicode")
        reparsed = minidom.parseString(rough_string)
        pretty = reparsed.toprettyxml(indent="  ", encoding=None)

        # 替换 CDATA 占位符为真实 CDATA
        # 占位符格式: __CDATA_START__内容__CDATA_END__
        # 替换为: <![CDATA[内容]]>
        while "__CDATA_START__" in pretty:
            start_idx = pretty.find("__CDATA_START__")
            end_idx = pretty.find("__CDATA_END__", start_idx)
            if end_idx == -1:
                break
            # 找到占位符所在文本节点的开始/结束标签
            # 向前查找 > (开标签结束)
            tag_open_end = pretty.rfind(">", 0, start_idx)
            # 向后查找 < (闭标签开始)
            tag_close_start = pretty.find("<", end_idx)
            if tag_open_end == -1 or tag_close_start == -1:
                break
            # 提取内容
            content = pretty[start_idx + len("__CDATA_START__") : end_idx]
            # 替换整个文本节点为 CDATA
            pretty = (
                pretty[: tag_open_end + 1]
                + f"<![CDATA[{content}]]>"
                + pretty[tag_close_start:]
            )

        return pretty


class ActorNFOGenerator:
    """
    演员 NFO 文件生成器
    """
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
    
    def generate(
        self,
        actor: ActorInfo,
        actor_dir: Optional[str] = None,
    ) -> Optional[str]:
        """
        生成演员 NFO 文件
        
        Args:
            actor: 演员信息
            actor_dir: 演员目录
            
        Returns:
            生成的文件路径
        """
        if actor_dir:
            save_dir = Path(actor_dir)
        else:
            safe_name = self._sanitize_filename(actor.name)
            save_dir = self.output_dir / safe_name
        
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / "actor.nfo"
        
        try:
            root = ET.Element("actor")
            
            self._add_element(root, "name", actor.name)
            
            jp_name2 = getattr(actor, "japanese_name", None)
            if jp_name2:
                self._add_element(root, "alt_name", jp_name2)
            
            avatar2 = getattr(actor, "avatar_url", None)
            if avatar2:
                self._add_element(root, "thumb", avatar2)
            
            # 写入文件
            xml_str = self._prettify(root)
            
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(xml_str)
            
            return str(save_path)
        
        except Exception as e:
            logger.error(f"生成演员NFO失败: {e}")
            return None
    
    def _add_element(self, parent: ET.Element, tag: str, text: Optional[str]) -> ET.Element:
        elem = ET.SubElement(parent, tag)
        if text:
            elem.text = text
        return elem
    
    def _prettify(self, elem: ET.Element) -> str:
        rough_string = ET.tostring(elem, encoding="unicode")
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ", encoding=None)
    
    def _sanitize_filename(self, name: str) -> str:
        illegal_chars = '<>:"/\\|?*'
        for char in illegal_chars:
            name = name.replace(char, "")
        return name.strip()


def generate_nfo(
    result: ScrapeResult,
    movie_dir: str,
    filename: str = "movie.nfo",
    kodi_compatible: bool = False,
) -> Optional[str]:
    """
    生成 NFO 文件的便捷函数

    Args:
        result: 刮削结果
        movie_dir: 电影目录
        filename: 文件名
        kodi_compatible: 是否输出 Kodi 兼容的额外字段

    Returns:
        生成的文件路径
    """
    generator = NFOGenerator(movie_dir)
    return generator.generate(result, movie_dir, filename, kodi_compatible=kodi_compatible)
