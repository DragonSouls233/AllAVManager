"""Jinja2 沙箱命名模板引擎

参考 Hazard804-mdcx 的命名模板设计：
- 使用 jinja2.sandbox.SandboxedEnvironment 防止任意代码执行
- StrictUndefined 强制要求所有变量都已提供，避免静默错误
- 文件名/目录名非法字符清理
- 长度限制（防止超出文件系统路径长度）

支持变量：
    code, title, original_title, title_jp,
    actor（第一位演员）, actors（所有演员列表）,
    studio, series, director, maker,
    release_date, release_year, release_month,
    rating, genre, tags, source,
    is_uncensored, is_chinese, is_mosaic
"""

import re
from datetime import datetime
from typing import Any, Optional

from jinja2.sandbox import SandboxedEnvironment
from jinja2 import StrictUndefined, TemplateError

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Windows / macOS / Linux 文件名非法字符
ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')
# 目录名非法字符（保留路径分隔符由调用方处理）
ILLEGAL_DIRNAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _make_env() -> SandboxedEnvironment:
    """创建沙箱环境（每次调用生成新环境，避免状态污染）"""
    env = SandboxedEnvironment(
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # 注册安全的全局过滤器
    env.filters["safe_name"] = sanitize_filename
    env.filters["lower"] = lambda s: str(s).lower() if s else ""
    env.filters["upper"] = lambda s: str(s).upper() if s else ""
    env.filters["truncate_str"] = lambda s, n=80: str(s)[:n] if s else ""
    return env


def sanitize_filename(name: str, replace_to_underscore: bool = True) -> str:
    """清理文件名中的非法字符"""
    if not name:
        return ""
    s = str(name).strip()
    replacement = "_" if replace_to_underscore else ""
    s = ILLEGAL_FILENAME_CHARS.sub(replacement, s)
    # 折叠连续下划线/空格
    s = re.sub(r"[_\s]+", " ", s).strip()
    # 去除首尾的点（Windows 不允许）
    s = s.strip(". ")
    return s


def sanitize_dirname(name: str, replace_to_underscore: bool = True) -> str:
    """清理目录名中的非法字符（保留 / 作为分隔符）"""
    if not name:
        return ""
    s = str(name)
    replacement = "_" if replace_to_underscore else ""
    # 仅清理每段内的非法字符，保留路径分隔符
    parts = s.split("/")
    cleaned = [sanitize_filename(p, replace_to_underscore) for p in parts]
    return "/".join(p for p in cleaned if p)


# 注意：必须在 sanitize_filename 定义后才能初始化 _env
_env = _make_env()


def truncate_safe(s: str, max_length: int) -> str:
    """安全截断字符串到指定长度"""
    if not s:
        return ""
    return s[:max_length].rstrip(". ")


def _extract_year(date_str: Optional[str]) -> str:
    """从日期字符串中提取年份"""
    if not date_str:
        return ""
    # 尝试多种日期格式
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y")
        except ValueError:
            continue
    # 兜底：取前 4 位数字
    m = re.match(r"^(\d{4})", date_str.strip())
    return m.group(1) if m else ""


def _extract_month(date_str: Optional[str]) -> str:
    """从日期字符串中提取月份"""
    if not date_str:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%m")
        except ValueError:
            continue
    return ""


def build_template_context(movie_dict: dict, actors: Optional[list[str]] = None) -> dict:
    """根据影片字典构建模板上下文

    Args:
        movie_dict: 影片数据（通常为 Movie 模型序列化或 dict）
        actors: 演员名列表（可选，若提供则覆盖 movie_dict.actors）

    Returns:
        模板渲染上下文 dict
    """
    # 安全提取字段，缺失返回空字符串（避免 StrictUndefined 报错）
    def g(key, default=""):
        v = movie_dict.get(key, default)
        return v if v is not None else default

    release_date = g("release_date")
    actor_list = actors or (
        movie_dict.get("actors") or
        ([movie_dict["actor"]] if movie_dict.get("actor") else [])
    )
    first_actor = actor_list[0] if actor_list else ""

    # 解析 genre / tags（可能是 JSON 字符串或列表）
    def to_list(v):
        if not v:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                import json
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else [v]
            except Exception:
                return [v]
        return []

    genres = to_list(g("genre"))
    tag_list = to_list(g("tag") or g("tags"))

    return {
        "code": g("code"),
        "title": g("title"),
        "original_title": g("original_title"),
        "title_jp": g("title_jp"),
        "actor": first_actor,
        "actors": actor_list,
        "studio": g("studio") or g("maker"),
        "maker": g("maker"),
        "series": g("series"),
        "director": g("director"),
        "release_date": release_date,
        "release_year": _extract_year(release_date),
        "release_month": _extract_month(release_date),
        "rating": g("rating"),
        "genre": genres,
        "tags": tag_list,
        "source": g("source"),
        "is_uncensored": g("is_uncensored", False),
        "is_chinese": g("is_chinese", False),
        "is_mosaic": g("is_mosaic", False),
    }


def render_template(template_str: str, context: dict) -> str:
    """渲染模板字符串

    Args:
        template_str: Jinja2 模板字符串
        context: 模板上下文（由 build_template_context 构建）

    Returns:
        渲染后的字符串（未做长度限制/字符清理，由调用方决定）
    """
    try:
        tmpl = _env.from_string(template_str)
        return tmpl.render(**context)
    except TemplateError as e:
        logger.warning(f"模板渲染失败: {e} · 模板: {template_str!r}")
        # 兜底：返回原始模板字符串
        return template_str


def render_filename(
    template_str: str,
    movie_dict: dict,
    actors: Optional[list[str]] = None,
    extension: str = "",
) -> str:
    """渲染文件名（清理非法字符 + 截断长度）

    Args:
        template_str: 文件名模板
        movie_dict: 影片数据
        actors: 演员名列表
        extension: 文件扩展名（不含点，如 "mp4"）

    Returns:
        安全的文件名字符串
    """
    cfg = get_config().naming
    context = build_template_context(movie_dict, actors)
    raw = render_template(template_str, context)
    name = sanitize_filename(raw, cfg.replace_invalid_to_underscore)
    name = truncate_safe(name, cfg.max_length)
    if extension:
        ext = extension.lstrip(".")
        return f"{name}.{ext}"
    return name


def render_dirpath(
    template_str: str,
    movie_dict: dict,
    actors: Optional[list[str]] = None,
) -> str:
    """渲染目录路径（保留路径分隔符）

    返回相对路径（如 "studio/2024/ABC-123"），不含首尾分隔符。
    """
    cfg = get_config().naming
    context = build_template_context(movie_dict, actors)
    raw = render_template(template_str, context)
    path = sanitize_dirname(raw, cfg.replace_invalid_to_underscore)
    # 清理空段和首尾斜杠
    parts = [p for p in path.split("/") if p]
    return "/".join(parts)


def preview_template(
    template_str: str,
    sample_data: Optional[dict] = None,
) -> dict:
    """预览模板渲染效果

    Args:
        template_str: 模板字符串
        sample_data: 自定义样例数据，None 时使用内置示例

    Returns:
        { "ok": bool, "result": str, "error": str }
    """
    if sample_data is None:
        sample_data = {
            "code": "ABC-123",
            "title": "示例标题",
            "original_title": "サンプルタイトル",
            "title_jp": "サンプルタイトル",
            "actor": "示例演员",
            "actors": ["示例演员", "副演员"],
            "studio": "示例工作室",
            "maker": "示例厂商",
            "series": "示例系列",
            "director": "示例导演",
            "release_date": "2024-05-01",
            "rating": 8.5,
            "genre": ["剧情", "恋爱"],
            "tags": ["高画质", "推荐"],
            "source": "javdb",
            "is_uncensored": False,
            "is_chinese": False,
            "is_mosaic": True,
        }
    try:
        # 渲染时不做长度限制和字符清理，便于看出原始效果
        context = build_template_context(sample_data)
        result = render_template(template_str, context)
        return {"ok": True, "result": result, "error": ""}
    except Exception as e:
        return {"ok": False, "result": "", "error": f"{type(e).__name__}: {e}"}


def validate_template(template_str: str) -> tuple[bool, str]:
    """验证模板语法是否正确

    Returns:
        (is_valid, error_message)
    """
    try:
        _env.parse(template_str)
        return True, ""
    except TemplateError as e:
        return False, f"{type(e).__name__}: {e}"


def get_default_templates() -> dict:
    """获取默认模板示例"""
    return {
        "file": "[{{ code }}] {{ title }}",
        "file_with_actor": "[{{ code }}] {{ actor }} - {{ title }}",
        "file_uncensored_flag": "{% if is_uncensored %}[无码]{% endif %}[{{ code }}] {{ title }}",
        "dir_by_studio_year": "{{ studio }}/{{ release_year }}/{{ code }}",
        "dir_by_actor": "{{ actor }}/{{ code }}",
        "dir_by_year_month": "{{ release_year }}-{{ release_month }}/{{ code }}",
        "dir_by_studio": "{{ studio }}/{{ code }}",
        "poster": "{{ code }}-poster",
        "thumb": "{{ code }}-thumb",
        "complex": "[{{ code }}][{{ studio }}][{{ release_year }}] {{ title }}",
    }


def get_available_variables() -> list[dict]:
    """获取所有可用模板变量（供前端文档展示）"""
    return [
        {"name": "code", "type": "string", "desc": "番号（如 ABC-123）"},
        {"name": "title", "type": "string", "desc": "标题（本地化后）"},
        {"name": "original_title", "type": "string", "desc": "原始标题"},
        {"name": "title_jp", "type": "string", "desc": "日文标题"},
        {"name": "actor", "type": "string", "desc": "第一位演员名"},
        {"name": "actors", "type": "list", "desc": "所有演员名列表"},
        {"name": "studio", "type": "string", "desc": "厂商/工作室（fallback 到 maker）"},
        {"name": "maker", "type": "string", "desc": "制造商"},
        {"name": "series", "type": "string", "desc": "系列名"},
        {"name": "director", "type": "string", "desc": "导演"},
        {"name": "release_date", "type": "string", "desc": "发布日期（原始字符串）"},
        {"name": "release_year", "type": "string", "desc": "发布年份（4 位）"},
        {"name": "release_month", "type": "string", "desc": "发布月份（2 位）"},
        {"name": "rating", "type": "float", "desc": "评分（0-10）"},
        {"name": "genre", "type": "list", "desc": "类型列表"},
        {"name": "tags", "type": "list", "desc": "标签列表"},
        {"name": "source", "type": "string", "desc": "数据源（javdb/javbus/...）"},
        {"name": "is_uncensored", "type": "bool", "desc": "是否无码"},
        {"name": "is_chinese", "type": "bool", "desc": "是否中文字幕"},
        {"name": "is_mosaic", "type": "bool", "desc": "是否有码"},
    ]


def get_available_filters() -> list[dict]:
    """获取可用过滤器"""
    return [
        {"name": "safe_name", "desc": "清理文件名非法字符"},
        {"name": "lower", "desc": "转小写"},
        {"name": "upper", "desc": "转大写"},
        {"name": "truncate_str(n)", "desc": "截断到 n 个字符"},
    ]
