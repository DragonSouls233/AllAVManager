"""HTTP 响应头工具：处理含非 ASCII 字符的 Content-Disposition。

历史坑：视频/文件原始名常含中文或日文，直接塞进 HTTP 头会因 latin-1
编码限制抛 UnicodeEncodeError -> 接口 500（裂视频/裂图）。统一在此收敛修复，
各模块播放/下载端点共用，避免 7 处重复且易遗漏（anime 已先行修复并验证）。
"""
import os
from urllib.parse import quote


def safe_content_disposition(file_path, disposition_type="inline", fallback_base=None):
    """生成可被 latin-1 编码的 Content-Disposition 头值。

    - filename：ASCII 兜底名（取 fallback_base，否则用 "video"+扩展名），
      供不支持 filename* 的旧浏览器使用，避免 500。
    - filename*：RFC 5987 编码的真实 UTF-8 文件名，现代浏览器优先采用。
    """
    raw_name = os.path.basename(file_path) if file_path else ""
    if fallback_base:
        ascii_name = fallback_base
    else:
        _, ext = os.path.splitext(raw_name)
        ascii_name = f"video{ext}" if ext else "video"
    return (
        f'{disposition_type}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(raw_name)}"
    )
