"""
NFO 解析器

解析已有的 NFO 文件，提取元数据信息
支持格式：
- Emby/Kodi 格式 (movie.nfo XML)
- Kodev 格式 (JSON)
"""

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class ImportedMovie:
    """导入的电影数据"""
    # 基本信息
    code: Optional[str] = None           # 番号
    title: Optional[str] = None          # 标题
    original_title: Optional[str] = None # 原标题
    
    # 元数据
    plot: Optional[str] = None           # 简介
    release_date: Optional[date] = None  # 发行日期
    year: Optional[int] = None           # 年份
    duration: Optional[int] = None       # 时长（分钟）
    
    # 制作信息
    studio: Optional[str] = None         # 制作商
    maker: Optional[str] = None          # 发行商
    series: Optional[str] = None         # 系列
    director: Optional[str] = None       # 导演
    
    # 内容
    genres: list[str] = field(default_factory=list)  # 标签
    actors: list[str] = field(default_factory=list)  # 演员名列表
    
    # 图片路径（本地文件）
    poster_path: Optional[str] = None    # 封面路径
    fanart_path: Optional[str] = None    # 背景图路径
    thumb_path: Optional[str] = None     # 缩略图路径
    
    # 来源信息
    nfo_path: Optional[str] = None       # NFO文件路径
    source: Optional[str] = None         # 数据来源（站点）

    # 版本标记（从文件名/目录名后缀识别，如 SONE-228-C / IPTD-499-Leak）
    is_chinese: Optional[bool] = None    # 中文字幕/中文配音版（后缀 -C/-CH/-CN/-中字）
    is_uncensored: Optional[bool] = None # 无码版（后缀 -U/-UC/-无码/-Uncensored）
    is_leak: Optional[bool] = None       # 流出/破解版（后缀 -Leak/-流出/-破解）
    code_suffix: Optional[str] = None    # 原始后缀（如 C/Leak/U），用于追溯

    # 元信息
    imported_at: Optional[datetime] = None  # 导入时间
    confidence: float = 1.0                 # 数据置信度
    
    def is_valid(self) -> bool:
        """检查数据是否有效"""
        return bool(self.code or self.title)


class NFOParser:
    """
    NFO 解析器
    
    解析 Emby/Kodi 格式的 NFO 文件
    """
    
    def parse(self, nfo_path: Union[str, Path]) -> Optional[ImportedMovie]:
        """
        解析 NFO 文件

        Args:
            nfo_path: NFO 文件路径

        Returns:
            ImportedMovie 导入的电影数据
        """
        nfo_path = Path(nfo_path)

        if not nfo_path.exists():
            logger.warning(f"NFO file not found: {nfo_path}")
            return None

        # 判断文件格式
        # 使用 utf-8-sig 自动处理 BOM 头（MDCX 生成的 NFO 文件通常有 UTF-8 BOM）
        content = nfo_path.read_text(encoding="utf-8-sig", errors="ignore")

        if content.strip().startswith("{"):
            # JSON 格式 (Kodev)
            movie = self._parse_json(content, nfo_path)
        elif content.strip().startswith("<"):
            # XML 格式 (Emby/Kodi)
            movie = self._parse_xml(content, nfo_path)
        else:
            # 尝试去掉不可见字符后再判断
            cleaned = content.strip().lstrip("\ufeff\ufeff\u200b\u200c\u200d")
            if cleaned.startswith("{"):
                movie = self._parse_json(content, nfo_path)
            elif cleaned.startswith("<"):
                movie = self._parse_xml(content, nfo_path)
            else:
                logger.warning(f"Unknown NFO format: {nfo_path}")
                return None

        if movie is not None:
            # 叠加从文件名/目录名识别的版本后缀（-C/-Leak/-U 等）
            self._detect_version_suffix(movie, nfo_path)
        return movie

    def parse_to_dict(self, nfo_path: Union[str, Path]) -> Optional[dict]:
        """解析 NFO 为 update_movie body 兼容的 dict.

        字段命名对齐 ``PATCH /api/v1/movies/{id}`` 接受的 body:
        - title / original_title / plot / plot_short / release_date / duration
        - studio (按名) / series (按名) / director / maker
        - genre (list) / tag (list) / actors (list of name)
        - rating / is_chinese / is_uncensored / is_leak
        - code (若 NFO 中存在且与 DB 不同, 也带回, 由端点决定是否覆盖)

        找不到 / 解析失败返回 None.
        """
        m = self.parse(nfo_path)
        if m is None:
            return None
        out: dict = {}
        if m.code:
            out["code"] = m.code
        if m.title is not None:
            out["title"] = m.title
        if m.original_title is not None:
            out["original_title"] = m.original_title
        if m.plot is not None:
            out["plot"] = m.plot
        if m.release_date is not None:
            out["release_date"] = m.release_date.strftime("%Y-%m-%d") if hasattr(m.release_date, "strftime") else str(m.release_date)
        if m.duration is not None:
            out["duration"] = m.duration
        if m.studio:
            out["studio"] = m.studio
        if m.series:
            out["series"] = m.series
        if m.director:
            out["director"] = m.director
        if m.maker:
            out["maker"] = m.maker
        if m.genres:
            out["genre"] = list(m.genres)
        if m.actors:
            out["actors"] = list(m.actors)
        if m.is_chinese is not None:
            out["is_chinese"] = bool(m.is_chinese)
        if m.is_uncensored is not None:
            out["is_uncensored"] = bool(m.is_uncensored)
        if m.is_leak is not None:
            out["is_leak"] = bool(m.is_leak)
        return out

    def _detect_version_suffix(self, movie: ImportedMovie, nfo_path: Path) -> None:
        """
        从 NFO 文件名、所在目录名识别版本后缀。

        JAV 影片常见的版本后缀约定：
        - -C / -CH / -CN / -中字   → 中文字幕/中文配音版
        - -U / -UC / -无码 / -Uncensored → 无码版
        - -Leak / -流出 / -破解    → 流出/破解版
        - -4K / -HD                → 画质版本（仅记录，不影响字段）

        示例：
            SONE-228-C.nfo        → code=SONE-228, is_chinese=True, suffix=C
            IPTD-499-Leak.nfo     → code=IPTD-499, is_leak=True, suffix=Leak
            RBD-257-C.nfo         → code=RBD-257, is_chinese=True, suffix=C

        同时叠加 NFO 内 <genre> 中包含「中文字幕/中文/無碼/无码」关键字，
        以及 <mpaa> 字段的「有码/无码」标记，作为冗余判定。
        """
        import re as _re

        # 拼接 NFO 文件名 + 父目录名 + NFO <num> 字段（原始），用于后缀识别
        nfo_stem = nfo_path.stem  # 如 "IPTD-499-Leak"
        dir_name = nfo_path.parent.name  # 如 "[2009-10-01][IPTD-499]芸能人の..."
        candidates = [nfo_stem, dir_name]

        # 基础番号（去掉可能的后缀），用于在候选字符串里定位真正的"后缀"
        base_code = movie.code or ""

        # 在每个候选字符串里，找形如 <base_code>-<SUFFIX> 的后缀片段
        # 后缀允许的字符：字母/数字/中文，长度 1-12
        suffix_patterns = []
        if base_code:
            code_escaped = _re.escape(base_code)
            # 匹配 番号-后缀 中的"后缀"部分，后缀可含字母/数字/中文
            suffix_patterns.append(_re.compile(rf"{code_escaped}[-_]([A-Za-z0-9\u4e00-\u9fff]{{1,12}})"))

        # 兜底：直接从 NFO 文件名提取（NFO 文件名往往是番号+后缀，如 IPTD-499-Leak.nfo）
        # 注意：suffix_patterns 只能装 re.Pattern 对象（可调用 .search），
        # 不能装 re.match() 的返回值（re.Match 对象，没有 .search 方法）
        nfo_name_pattern = _re.compile(r"[A-Za-z]{2,6}[-_]\d{2,5}[-_]([A-Za-z0-9\u4e00-\u9fff]{1,12})")
        suffix_patterns.append(nfo_name_pattern)

        detected_suffix = None
        for cand in candidates:
            for pat in suffix_patterns:
                m = pat.search(cand)
                if m:
                    detected_suffix = m.group(1).strip()
                    break
            if detected_suffix:
                break

        # 关键字集合（小写匹配）
        def _match_any(text: str, keywords) -> bool:
            t = text.lower()
            return any(k in t for k in keywords)

        # 判定中文字幕版
        if detected_suffix and _match_any(detected_suffix, ["c", "ch", "cn", "中字", "中文"]):
            movie.is_chinese = True
            movie.code_suffix = detected_suffix
        # 判定无码版
        if detected_suffix and _match_any(detected_suffix, ["u", "uc", "uncensored", "无码", "無碼", "unc"]):
            movie.is_uncensored = True
            movie.code_suffix = detected_suffix
        # 判定流出/破解版
        if detected_suffix and _match_any(detected_suffix, ["leak", "流出", "破解", "rip"]):
            movie.is_leak = True
            movie.code_suffix = detected_suffix

        # NFO 内 genre 关键字叠加判定（冗余信号）
        genre_text = " ".join(movie.genres) if movie.genres else ""
        if genre_text:
            if _match_any(genre_text, ["中文字幕", "中文", "中字"]):
                movie.is_chinese = True
            if _match_any(genre_text, ["无码", "無碼", "uncensored"]):
                movie.is_uncensored = True
            if _match_any(genre_text, ["流出", "破解", "leak"]):
                movie.is_leak = True
    
    def _parse_xml(self, content: str, nfo_path: Path) -> Optional[ImportedMovie]:
        """解析 XML 格式 NFO"""
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # XML 解析失败，尝试容错处理（修复未转义的 & 字符等）
            try:
                fixed_content = self._fix_xml_content(content)
                root = ET.fromstring(fixed_content)
            except ET.ParseError as e:
                logger.error(f"XML parse error (even after fix): {nfo_path} - {e}")
                return None
        
        # 检查根元素
        # 支持 movie, episodedetails, tvshow, season 等 Emby/Kodi 格式
        if root.tag not in ("movie", "episodedetails", "tvshow", "season"):
            logger.warning(f"Unknown root element: {root.tag}")
            return None
        
        movie = ImportedMovie()
        movie.nfo_path = str(nfo_path)
        movie.imported_at = datetime.now()
        
        # 解析字段（番号统一标准化为大写）
        raw_code = self._get_text(root, "id") or self._get_text(root, "num")
        movie.code = self._normalize_code(raw_code)
        movie.title = self._get_text(root, "title")
        movie.original_title = self._get_text(root, "originaltitle")
        movie.plot = self._get_text(root, "plot") or self._get_text(root, "outline")
        
        # 如果没有番号，尝试从标题中提取
        if not movie.code and movie.title:
            movie.code = self._extract_code_from_title(movie.title)
        
        # 如果标题包含日期前缀（如 "2024-02-13IPZZ-218..."），清理标题
        if movie.title and movie.code:
            movie.title = self._clean_title(movie.title, movie.code)
        
        # 发行日期
        release_str = self._get_text(root, "releasedate") or self._get_text(root, "premiered")
        if release_str:
            movie.release_date = self._parse_date(release_str)
        
        # 年份
        year_str = self._get_text(root, "year")
        if year_str:
            movie.year = int(year_str)
        
        # 时长
        runtime_str = self._get_text(root, "runtime")
        if runtime_str:
            import re
            match = re.search(r'(\d+)', runtime_str)
            if match:
                movie.duration = int(match.group(1))
        
        # 制作商
        movie.studio = self._get_text(root, "studio")
        movie.maker = self._get_text(root, "maker")
        movie.series = self._get_text(root, "set")
        movie.director = self._get_text(root, "director")
        
        # 标签（去重，保持顺序）
        raw_genres = self._get_texts(root, "genre") + self._get_texts(root, "tag")
        seen = set()
        movie.genres = [g for g in raw_genres if g not in seen and not seen.add(g)]
        
        # 演员
        for actor_elem in root.findall("actor"):
            actor_name = self._get_text(actor_elem, "name")
            if actor_name:
                movie.actors.append(actor_name)
        
        # 来源
        movie.source = self._get_text(root, "source")
        
        return movie
    
    def _parse_json(self, content: str, nfo_path: Path) -> Optional[ImportedMovie]:
        """解析 JSON 格式 NFO (Kodev)"""
        try:
            data = json.loads(content)
            
            movie = ImportedMovie()
            movie.nfo_path = str(nfo_path)
            movie.imported_at = datetime.now()
            
            # 映射字段（番号统一标准化为大写）
            movie.code = self._normalize_code(data.get("code") or data.get("id"))
            movie.title = data.get("title") or data.get("name")
            movie.original_title = data.get("originaltitle")
            movie.plot = data.get("plot") or data.get("description")
            
            # 发行日期
            release_str = data.get("release_date") or data.get("releasedate")
            if release_str:
                movie.release_date = self._parse_date(release_str)
            
            # 年份
            if data.get("year"):
                movie.year = int(data["year"])
            
            # 时长
            if data.get("duration") or data.get("runtime"):
                movie.duration = int(data.get("duration") or data.get("runtime"))
            
            # 制作商
            movie.studio = data.get("studio")
            movie.maker = data.get("maker") or data.get("publisher")
            movie.series = data.get("series") or data.get("set")
            movie.director = data.get("director")
            
            # 标签
            genres = data.get("genres") or data.get("tags") or []
            if isinstance(genres, list):
                movie.genres = genres
            elif isinstance(genres, str):
                movie.genres = [g.strip() for g in genres.split(",")]
            
            # 演员
            actors = data.get("actors") or []
            if isinstance(actors, list):
                movie.actors = [a.get("name") if isinstance(a, dict) else a for a in actors]
            elif isinstance(actors, str):
                movie.actors = [a.strip() for a in actors.split(",")]
            
            # 来源
            movie.source = data.get("source")
            
            return movie
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {nfo_path} - {e}")
            return None
    
    def _get_text(self, elem: ET.Element, tag: str) -> Optional[str]:
        """获取单个文本值"""
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None
    
    def _fix_xml_content(self, content: str) -> str:
        """
        修复 XML 内容中的常见错误
        
        常见问题：
        - & 未转义为 &amp;（标题中含有 & 字符）
        - < > 未转义
        - 不完整的标签
        """
        import re
        
        # 方法：用正则逐个处理标签之间的文本内容，转义特殊字符
        # 只处理标签之间的文本，不处理标签本身
        
        def fix_text_between_tags(match):
            text = match.group(1)
            # 转义文本中的特殊 XML 字符（但保留已有的实体引用）
            # 先还原已有的实体引用，再统一转义
            text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'")
            # 重新转义
            text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            return f'>{text}<'
        
        # 匹配 >文本< 之间的内容（标签间的文本）
        fixed = re.sub(r'>([^<]+)<', fix_text_between_tags, content)
        
        return fixed
    
    def _extract_code_from_title(self, title: str) -> Optional[str]:
        """
        从标题中提取番号
        
        支持格式：
        - "2024-02-13IPZZ-218FIRST IMPRESSION..." → IPZZ-218
        - "ABC-123 标题" → ABC-123
        - "[2024-02-13][IPZZ-218]标题" → IPZZ-218
        """
        import re
        
        # 去掉日期前缀
        cleaned = re.sub(r'^\d{4}[-/]\d{2}[-/]\d{2}', '', title)
        
        # 匹配常见番号格式
        patterns = [
            r'([A-Z]{2,6}[-_]\d{2,5})',          # IPZZ-218, ABC-123
            r'([A-Z]{2,6}\d{2,5})',               # IPZZ218 (无分隔符)
            r'(FC2[-_]?PPV[-_]\d+)',               # FC2-PPV-123456
            r'(FC2[-_]\d+)',                        # FC2-123456
            r'(\d{6}[-_]\d{2,3})',                 # 111122-01 (加勒比)
            r'(HEYZO[-_]\d+)',                      # HEYZO-1234
            r'([A-Z]+[-_]\d+)',                     # 通用格式
        ]
        
        for pattern in patterns:
            match = re.search(pattern, cleaned, re.IGNORECASE)
            if match:
                code = match.group(1).upper()
                # 标准化分隔符
                code = code.replace('_', '-')
                return code
        
        return None
    
    def _normalize_code(self, code: Optional[str]) -> Optional[str]:
        """
        标准化番号格式（统一大写和分隔符）
        
        - 转换为大写
        - _ 替换为 -
        - 去除前后空白
        """
        if not code:
            return None
        return code.strip().upper().replace('_', '-')
    
    def _clean_title(self, title: str, code: str) -> str:
        """
        清理标题，去掉日期前缀和番号
        
        "2024-02-13IPZZ-218FIRST IMPRESSION 167 美神 RARA" → "FIRST IMPRESSION 167 美神 RARA"
        "IPZZ-827-美貌・色気..." → "美貌・色気..."
        "[2019-01-24]  [SDNM181]标题" → "标题"
        """
        import re
        
        cleaned = title
        # 去掉 [YYYY-MM-DD] 格式的日期前缀
        cleaned = re.sub(r'^\[?\d{4}[-/]\d{2}[-/]\d{2}\]?\s*', '', cleaned)
        # 去掉 [番号] 格式
        code_escaped = re.escape(code)
        cleaned = re.sub(rf'\[?{code_escaped}\]?\s*', '', cleaned)
        # 去掉番号（含后面的分隔符 - 或空格）
        cleaned = re.sub(rf'^{code_escaped}[\s\-_]*', '', cleaned)
        # 去掉开头多余的空格和标点
        cleaned = re.sub(r'^[\s\-_\[\]]+', '', cleaned)
        # 如果清理后为空，保留原标题
        if not cleaned.strip():
            return title
        
        return cleaned.strip()
    
    def _get_texts(self, elem: ET.Element, tag: str) -> list[str]:
        """获取多个文本值"""
        results = []
        for child in elem.findall(tag):
            if child.text:
                results.append(child.text.strip())
        return results
    
    def _parse_date(self, date_str: str) -> Optional[date]:
        """解析日期字符串"""
        import re
        
        date_str = date_str.strip()
        date_str = date_str.replace("/", "-").replace(".", "-")
        
        # 尝试多种格式
        patterns = [
            r"(\d{4})-(\d{1,2})-(\d{1,2})",  # YYYY-MM-DD
            r"(\d{4})-(\d{2})-(\d{2})",      # YYYY-MM-DD
            r"(\d{2})-(\d{2})-(\d{4})",      # DD-MM-YYYY
        ]
        
        for pattern in patterns:
            if match := re.search(pattern, date_str):
                try:
                    parts = match.groups()
                    if len(parts[0]) == 4:  # YYYY-MM-DD
                        return date(int(parts[0]), int(parts[1]), int(parts[2]))
                    else:  # DD-MM-YYYY
                        return date(int(parts[2]), int(parts[1]), int(parts[0]))
                except ValueError:
                    continue
        
        return None


def parse_nfo_file(nfo_path: Union[str, Path]) -> Optional[ImportedMovie]:
    """
    解析 NFO 文件的便捷函数
    
    Args:
        nfo_path: NFO 文件路径
        
    Returns:
        ImportedMovie 导入的电影数据
    """
    parser = NFOParser()
    return parser.parse(nfo_path)