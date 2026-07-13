"""WebDAV 客户端服务

用于从远程 WebDAV 服务器扫描影片文件并导入到本地数据库。
支持三种导入模式：copy（下载）、move（移动）、link（仅记录路径）。

参考 JavdBviewed 的 WebDAV 云端同步方案。
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import quote, urljoin

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.database import get_session_factory
from app.db.models import Movie
from app.services.websocket import emit_log, emit_progress

logger = logging.getLogger(__name__)

# 影片文件扩展名
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".m4v", ".ts", ".webm"}

# 番号识别正则
NUMBER_PATTERNS = [
    re.compile(r"([A-Za-z]{2,6})-?(\d{2,5})", re.IGNORECASE),
    re.compile(r"(FC2[-_]?PPV[-_]?\d{4,8})", re.IGNORECASE),
    re.compile(r"(\d{6}[-_]\d{2,4})", re.IGNORECASE),
]


class WebDAVClient:
    """WebDAV 客户端"""

    def __init__(
        self,
        url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30,
    ):
        self.base_url = url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            auth = None
            if self.username and self.password:
                auth = httpx.BasicAuth(self.username, self.password)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                auth=auth,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def test_connection(self) -> tuple[bool, str]:
        """测试连接"""
        try:
            client = await self._get_client()
            resp = await client.request("OPTIONS", "/")
            if resp.status_code in (200, 207, 204):
                return True, f"连接成功（HTTP {resp.status_code}）"
            return False, f"HTTP {resp.status_code}: {resp.reason_phrase}"
        except Exception as e:
            return False, f"连接失败: {e}"

    async def list_dir(self, path: str = "/") -> list[dict]:
        """列出目录内容（PROPFIND）

        返回每个条目：name, path, is_dir, size, content_type, modified
        """
        client = await self._get_client()
        headers = {
            "Depth": "1",
            "Content-Type": "application/xml; charset=utf-8",
        }
        body = """<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:displayname/>
    <D:resourcetype/>
    <D:getcontentlength/>
    <D:getcontenttype/>
    <D:getlastmodified/>
  </D:prop>
</D:propfind>"""
        # 路径编码
        encoded_path = quote(str(PurePosixPath(path)), safe="/")
        if not encoded_path.startswith("/"):
            encoded_path = "/" + encoded_path

        resp = await client.request(
            "PROPFIND", encoded_path, headers=headers, content=body
        )

        if resp.status_code not in (200, 207):
            raise RuntimeError(f"PROPFIND 失败: HTTP {resp.status_code}")

        return self._parse_propfind(resp.text, base_path=path)

    def _parse_propfind(self, xml_text: str, base_path: str) -> list[dict]:
        """解析 PROPFIND 响应"""
        import xml.etree.ElementTree as ET

        items = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"XML 解析失败: {e}")
            return items

        # 命名空间
        ns = {"D": "DAV:"}

        for resp_elem in root.findall("D:response", ns):
            href_elem = resp_elem.find("D:href", ns)
            if href_elem is None or not href_elem.text:
                continue

            href = href_elem.text.strip()
            # 跳过自身
            if quote(str(PurePosixPath(base_path)), safe="/").rstrip("/") in href.rstrip("/"):
                continue

            propstat = resp_elem.find("D:propstat", ns)
            if propstat is None:
                continue

            prop = propstat.find("D:prop", ns)
            if prop is None:
                continue

            # 资源类型
            resourcetype = prop.find("D:resourcetype", ns)
            is_dir = resourcetype is not None and resourcetype.find("D:collection", ns) is not None

            # 文件名
            displayname_elem = prop.find("D:displayname", ns)
            if displayname_elem is not None and displayname_elem.text:
                name = displayname_elem.text
            else:
                name = PurePosixPath(href).name or href

            # 大小
            size = 0
            content_length = prop.find("D:getcontentlength", ns)
            if content_length is not None and content_length.text:
                try:
                    size = int(content_length.text)
                except ValueError:
                    pass

            # 内容类型
            content_type = ""
            ct_elem = prop.find("D:getcontenttype", ns)
            if ct_elem is not None and ct_elem.text:
                content_type = ct_elem.text

            # 修改时间
            modified = ""
            modified_elem = prop.find("D:getlastmodified", ns)
            if modified_elem is not None and modified_elem.text:
                modified = modified_elem.text

            items.append({
                "name": name,
                "path": href,
                "is_dir": is_dir,
                "size": size,
                "content_type": content_type,
                "modified": modified,
            })

        return items

    async def download_file(self, remote_path: str, local_path: str) -> bool:
        """下载文件到本地"""
        client = await self._get_client()
        encoded = quote(str(PurePosixPath(remote_path)), safe="/")
        if not encoded.startswith("/"):
            encoded = "/" + encoded

        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            async with client.stream("GET", encoded) as resp:
                if resp.status_code != 200:
                    return False
                with open(local_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"下载失败 {remote_path}: {e}")
            return False


def extract_number_from_filename(filename: str) -> Optional[str]:
    """从文件名提取番号"""
    # 移除扩展名
    name = os.path.splitext(filename)[0]

    # 尝试每个正则
    for pattern in NUMBER_PATTERNS:
        match = pattern.search(name)
        if match:
            number = match.group(0).upper()
            # 标准化：XXX-123
            if number.startswith("FC2"):
                return f"FC2-PPV-{match.group(0).split('PPV')[-1].lstrip('-_').split('-')[0]}"
            # 标准格式
            parts = re.match(r"([A-Za-z]+)[-_]?(\d+)", number)
            if parts:
                return f"{parts.group(1).upper()}-{parts.group(2)}"
            return number
    return None


async def scan_webdav_for_movies(
    client: WebDAVClient,
    base_path: str = "/",
    max_depth: int = 5,
    task_id: str = "webdav-scan",
) -> list[dict]:
    """递归扫描 WebDAV 目录，返回所有影片文件

    每个影片：{path, name, size, modified, number, parsed}
    """
    found = []
    visited = set()

    async def _scan(path: str, depth: int):
        if depth > max_depth:
            return
        # 防止循环
        norm = path.rstrip("/") or "/"
        if norm in visited:
            return
        visited.add(norm)

        try:
            entries = await client.list_dir(path)
        except Exception as e:
            await emit_log("ERROR", f"扫描目录失败 {path}: {e}", task_id=task_id, module="webdav")
            return

        for entry in entries:
            if entry["is_dir"]:
                await _scan(entry["path"], depth + 1)
            else:
                ext = os.path.splitext(entry["name"])[1].lower()
                if ext not in VIDEO_EXTENSIONS:
                    continue

                number = extract_number_from_filename(entry["name"])
                found.append({
                    "path": entry["path"],
                    "name": entry["name"],
                    "size": entry["size"],
                    "modified": entry["modified"],
                    "number": number,
                    "parsed": number is not None,
                })
                await emit_log(
                    "DEBUG",
                    f"发现影片: {entry['name']} → 番号: {number or '未识别'}",
                    task_id=task_id,
                    module="webdav",
                )

    await _scan(base_path, 0)
    return found


async def import_webdav_movies(
    client: WebDAVClient,
    movies: list[dict],
    link_mode: str = "link",
    local_dir: Optional[str] = None,
    task_id: str = "webdav-import",
) -> dict:
    """导入 WebDAV 影片到数据库

    link_mode:
        - link: 仅记录远程路径到 movie.file_path
        - copy: 下载到 local_dir
        - move: 下载后删除远程（慎用）
    """
    session_factory = get_session_factory()
    success = 0
    skipped = 0
    failed = 0

    total = len(movies)
    await emit_progress(task_id, "WebDAV 导入", 0, total, status="running")

    async with session_factory() as session:
        for idx, item in enumerate(movies, 1):
            number = item.get("number")
            if not number:
                await emit_log(
                    "WARNING",
                    f"跳过无法识别番号的文件: {item['name']}",
                    task_id=task_id,
                    module="webdav",
                )
                skipped += 1
                continue

            # 检查是否已存在
            existing = await session.execute(
                select(Movie).where(Movie.code == number)
            )
            existing_movie = existing.scalar_one_or_none()

            if existing_movie:
                # 更新 file_path（如果原为空）
                if not existing_movie.file_path:
                    existing_movie.file_path = item["path"]
                    await session.commit()
                await emit_log(
                    "DEBUG",
                    f"番号已存在: {number}",
                    task_id=task_id,
                    module="webdav",
                )
                skipped += 1
            else:
                try:
                    # 处理本地文件
                    file_path = item["path"]
                    if link_mode in ("copy", "move") and local_dir:
                        local_filename = f"{number}{os.path.splitext(item['name'])[1]}"
                        local_path = os.path.join(local_dir, local_filename)
                        ok = await client.download_file(item["path"], local_path)
                        if ok:
                            file_path = local_path
                            if link_mode == "move":
                                # 删除远程文件（DELETE 请求）
                                # 慎用，默认不启用
                                pass

                    # 创建影片记录
                    movie = Movie(
                        code=number,
                        title=item["name"],  # 临时用文件名作为标题
                        file_path=file_path,
                        file_size=item.get("size") or 0,
                        status="pending",  # 待刮削
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    session.add(movie)
                    await session.commit()

                    success += 1
                    await emit_log(
                        "SUCCESS",
                        f"导入成功: {number} ({item['name']})",
                        task_id=task_id,
                        module="webdav",
                    )
                except Exception as e:
                    failed += 1
                    await emit_log(
                        "ERROR",
                        f"导入失败 {number}: {e}",
                        task_id=task_id,
                        module="webdav",
                    )

            await emit_progress(task_id, "WebDAV 导入", idx, total, status="running")

    await emit_progress(
        task_id, "WebDAV 导入", total, total,
        status="success" if failed == 0 else "failed",
        message=f"成功 {success} / 跳过 {skipped} / 失败 {failed}",
    )

    return {
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "total": total,
    }
