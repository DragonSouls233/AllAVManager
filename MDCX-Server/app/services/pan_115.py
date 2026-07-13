"""115 网盘离线下载客户端服务（§7.6）

对接 115 网盘 Web API（基于 p115client / alist 社区文档与抓包验证），支持：
- Cookie 认证登录（UID/CID/SEID/KID 四元组）
- 离线下载任务管理（添加磁力链 / HTTP / ed2k 链接、查询、取消）
- 文件列表浏览（按文件夹 cid 导航）
- 文件下载直链获取（pickcode → 下载 URL）
- 文件 SHA1 校验
- 离线下载完成后可选自动入库到本地媒体库

实现要点（基于 webapi.115.com 真实端点）：
1. 认证：通过浏览器抓取的 Cookie 字符串进行鉴权（UID/CID/SEID/KID）
2. 列目录：GET /files（按 cid 分页，show_dir=1 包含子目录）
3. 离线下载：GET /offline/list（任务列表）/ POST /offline/add（添加任务）
4. 取消任务：POST /offline/del（按 info_hash 删除/取消）
5. 下载直链：GET /files/download?pickcode=xxx（返回 oss 直链，含过期时间）
6. SHA1 校验：GET /files/sha1?file_id=xxx（返回文件 SHA1）

注意：115 接口返回统一格式 {"state": true/false, ...}，state 为 false 时附带 error 字段。
"""

import asyncio
import logging
import re
import time
from typing import Optional

import httpx

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 115 网盘 Web API 基础地址（web 接口，社区广泛使用）
API_BASE = "https://webapi.115.com"
# 备用地址（部分 app 接口走此域名）
API_BASE_APP = "https://proapi.115.com"
# 默认根目录 cid
ROOT_CID = "0"
# 请求超时（秒）
DEFAULT_TIMEOUT = 30
# 浏览器 UA（与项目指纹池一致的现代 Chrome）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
# Cookie 字段提取正则（UID / CID / SEID / KID）
_COOKIE_RE_UID = re.compile(r"UID(?:=|:)([^;,\s]+)", re.IGNORECASE)
_COOKIE_RE_CID = re.compile(r"CID(?:=|:)([^;,\s]+)", re.IGNORECASE)


def _format_size(size: int) -> str:
    """格式化文件大小"""
    if size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    fsize = float(size)
    idx = 0
    while fsize >= 1024 and idx < len(units) - 1:
        fsize /= 1024
        idx += 1
    return f"{fsize:.2f} {units[idx]}"


def _parse_cookies(cookies: str) -> dict[str, str]:
    """从 Cookie 字符串中解析出键值对"""
    result: dict[str, str] = {}
    if not cookies:
        return result
    for part in cookies.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


class Pan115Client:
    """115 网盘客户端

    通过 Cookie 与 115 网盘 Web API 交互。
    生命周期由 app.main lifespan 管理。
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._started: bool = False
        self._logged_in: bool = False
        self._last_login_at: float = 0.0
        # 缓存的用户 ID（部分接口需要 uid 参数）
        self._user_id: Optional[str] = None
        # 缓存的用户信息
        self._user_info: Optional[dict] = None
        # Cookie 是否失效、需要重新登录（由登录/接口鉴权失败置位）
        self._need_relogin: bool = False

    def _build_headers(self) -> dict[str, str]:
        """构建请求头（含 Cookie 鉴权）"""
        cfg = get_config().pan_115
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
        }
        if cfg.cookies:
            headers["Cookie"] = cfg.cookies
        if cfg.token:
            headers["Authorization"] = f"Bearer {cfg.token}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 httpx 客户端（懒加载，附加 Cookie / Token 头）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=API_BASE,
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                follow_redirects=True,
                headers=self._build_headers(),
            )
        return self._client

    async def start(self) -> None:
        """启动客户端（在 lifespan 中调用）"""
        cfg = get_config().pan_115
        if not cfg.enabled:
            logger.info("115 网盘离线下载未启用，跳过启动")
            return

        try:
            await self.login()
            self._started = True
            logger.info("115 网盘客户端已就绪")
        except Exception as e:
            logger.warning(f"115 网盘登录验证失败（仍可手动重试）: {e}")
            # 即使登录失败也标记为已启动，允许后续手动登录
            self._started = True

    async def close(self) -> None:
        """关闭客户端（在 lifespan 中调用）"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        self._started = False
        self._logged_in = False
        self._user_id = None
        self._user_info = None
        self._need_relogin = False
        logger.info("115 网盘客户端已关闭")

    async def reset(self) -> None:
        """重置客户端（凭据更新后调用，强制重建连接）"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._logged_in = False
        self._user_id = None
        self._user_info = None
        self._need_relogin = False

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def need_relogin(self) -> bool:
        return self._need_relogin

    def mark_need_relogin(self) -> None:
        """标记 Cookie 已失效，需要重新登录（供路由/前端检测）"""
        self._need_relogin = True

    def _maybe_auth_error(self, data: dict) -> bool:
        """检测 115 返回的 state=false 是否为鉴权失效；是则标记 need_relogin。

        Returns:
            True 判定为鉴权失效
        """
        errcode = data.get("errcode")
        err = str(data.get("error") or data.get("message") or "").lower()
        auth_markers = [
            "登录", "未登录", "过期", "expired", "token", "cookie",
            "401", "请先登录", "权限", "invalid", "重新登录",
        ]
        if errcode in (401, 403, 10001, -10001) or any(m in err for m in auth_markers):
            self._need_relogin = True
            return True
        return False

    def _assert_state(self, data: dict, action: str = "操作") -> None:
        """断言 115 返回 state 为真；为假时标记鉴权失效并抛出 RuntimeError。"""
        if not data.get("state", False):
            self._maybe_auth_error(data)
            err = data.get("error") or data.get("message") or f"{action}失败"
            raise RuntimeError(err)

    # ============================================
    # 登录与用户信息
    # ============================================

    async def login(self) -> bool:
        """登录 115 网盘（验证 Cookie / Token 是否有效）

        通过调用用户基本信息接口验证凭据有效性。
        若凭据无效则抛出 RuntimeError。

        Returns:
            True 登录成功，False 未配置凭据
        """
        cfg = get_config().pan_115
        if not cfg.cookies and not cfg.token:
            logger.debug("115 网盘未配置 Cookie / Token，跳过登录")
            return False

        client = await self._get_client()
        try:
            resp = await client.get("/user/user_info")
            resp.raise_for_status()
            data = resp.json()
            # 115 接口统一返回 {"state": true, "data": {...}} 或 {"state": false, "error": "..."}
            if not data.get("state", False):
                err = data.get("error") or data.get("message") or "未知错误"
                logger.warning(f"115 网盘登录验证失败: {err}")
                self._logged_in = False
                self._maybe_auth_error(data)
                return False

            user_data = data.get("data", {}) or {}
            self._logged_in = True
            self._need_relogin = False
            self._last_login_at = time.time()
            self._user_id = str(user_data.get("user_id", "") or user_data.get("uid", "") or "")
            self._user_info = {
                "user_id": self._user_id,
                "username": user_data.get("username", "") or user_data.get("name", ""),
                "space_used": int(user_data.get("space_used", 0) or 0),
                "space_total": int(user_data.get("space_total", 0) or 0),
                "vip_type": user_data.get("vip_type", 0),
            }
            logger.info(
                f"115 网盘登录验证成功 (uid={self._user_id}, "
                f"username={self._user_info['username']})"
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                f"115 网盘登录验证失败 HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            )
            self._logged_in = False
            raise RuntimeError(f"登录验证失败: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"115 网盘登录验证异常: {e}")
            self._logged_in = False
            raise

    async def get_user_info(self) -> dict:
        """获取用户基本信息（空间使用、VIP 状态等）"""
        if not self._logged_in:
            await self.login()
        return self._user_info or {}

    async def get_status(self) -> dict:
        """获取 115 网盘连接状态"""
        cfg = get_config().pan_115
        status = {
            "enabled": cfg.enabled,
            "started": self._started,
            "logged_in": self._logged_in,
            "need_relogin": self._need_relogin,
            "has_credentials": bool(cfg.cookies or cfg.token),
            "auto_link_to_library": cfg.auto_link_to_library,
            "target_folder_id": cfg.target_folder_id or ROOT_CID,
            "last_login_at": self._last_login_at,
        }
        if self._user_info:
            status["user_info"] = self._user_info
        return status

    # ============================================
    # 离线下载任务管理
    # ============================================

    async def add_offline_task(self, magnet_url: str, target_cid: Optional[str] = None) -> dict:
        """添加离线下载任务

        Args:
            magnet_url: 磁力链接 / HTTP / ed2k 链接
            target_cid: 保存目录 CID（None 则使用配置中的 target_folder_id 或根目录）

        Returns:
            {
                "success": bool,
                "info_hash": str,
                "message": str,
                "target_cid": str,
            }
        """
        cfg = get_config().pan_115
        cid = target_cid or cfg.target_folder_id or ROOT_CID

        client = await self._get_client()
        try:
            resp = await client.post(
                "/offline/add",
                data={
                    "url": magnet_url,
                    "cid": cid,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            success = bool(data.get("state", False))
            if not success:
                self._maybe_auth_error(data)
            # 115 返回样例 {"state": true, "data": {"info_hash": "...", "file_name": "..."}}
            # 失败时返回 {"state": false, "errcode": <int>, "error": "<msg>"}
            info_hash = ""
            if success:
                d = data.get("data", {}) or {}
                info_hash = d.get("info_hash", "") or d.get("hash", "")
            message = (
                data.get("error")
                or data.get("message")
                or ("添加成功" if success else "添加失败")
            )
            return {
                "success": success,
                "info_hash": info_hash,
                "message": message,
                "target_cid": cid,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"115 添加离线下载任务失败 HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            )
            raise RuntimeError(f"添加离线下载任务失败: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"115 添加离线下载任务异常: {e}")
            raise RuntimeError(f"添加离线下载任务异常: {e}")

    async def list_offline_tasks(self, page: int = 1, page_size: int = 30) -> dict:
        """列出离线下载任务

        Args:
            page: 页码（从 1 开始）
            page_size: 每页数量

        Returns:
            {
                "tasks": [...],
                "total": int,
                "page": int,
                "page_size": int,
            }
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                "/offline/list",
                params={
                    "page": page,
                    # 115 web 接口每页固定 30 条，忽略 page_size 仅做标记
                    "uid": self._user_id or "",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._assert_state(data, "列离线任务")

            d = data.get("data", {}) or {}
            tasks_raw = d.get("tasks", []) or d.get("list", []) or []
            total = int(d.get("total", len(tasks_raw)) or len(tasks_raw))

            tasks = []
            for item in tasks_raw:
                status = int(item.get("status", 0))
                # 115 离线任务状态映射
                # 0=等待/排队 1=下载中 2=已完成 -1=失败/异常
                status_text_map = {0: "等待中", 1: "下载中", 2: "已完成", -1: "失败"}
                # percent：115 返回 0-100 整数
                percent = float(item.get("percent", item.get("progress", 0.0)) or 0.0)
                if percent <= 1.0 and status == 2:
                    percent = 100.0
                file_size = int(item.get("file_size", item.get("size", 0)) or 0)
                tasks.append({
                    "info_hash": item.get("info_hash", item.get("hash", "")),
                    "file_name": item.get("file_name", item.get("name", "")),
                    "file_size": file_size,
                    "size_text": _format_size(file_size),
                    "status": status,
                    "status_text": status_text_map.get(status, "未知"),
                    "percent": percent,
                    "added_time": item.get("add_time", item.get("added_time", "")),
                    "finished_time": item.get("finish_time", item.get("finished_time", "")),
                    "type": item.get("type", ""),
                    "url": item.get("url", item.get("magnet", "")),
                    "save_path": item.get("save_pathname", ""),
                })

            return {
                "tasks": tasks,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"115 列离线任务失败 HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            )
            raise RuntimeError(f"列离线任务失败: HTTP {e.response.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"115 列离线任务异常: {e}")
            raise RuntimeError(f"列离线任务异常: {e}")

    async def cancel_task(self, task_id: str) -> dict:
        """取消（删除）离线下载任务

        Args:
            task_id: 任务 info_hash 或 file_id

        Returns:
            {"success": bool, "message": str}
        """
        client = await self._get_client()
        try:
            resp = await client.post(
                "/offline/del",
                data={
                    "hash": task_id,
                    # del_source=0 保留已下载文件，1 连同文件一起删除
                    "del_source": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            success = bool(data.get("state", False))
            if not success:
                self._maybe_auth_error(data)
            message = (
                data.get("error")
                or data.get("message")
                or ("取消成功" if success else "取消失败")
            )
            return {"success": success, "message": message}
        except httpx.HTTPStatusError as e:
            logger.error(
                f"115 取消离线任务失败 HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            )
            raise RuntimeError(f"取消离线任务失败: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"115 取消离线任务异常: {e}")
            raise RuntimeError(f"取消离线任务异常: {e}")

    # ============================================
    # 文件浏览
    # ============================================

    async def list_files(
        self, folder_id: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> dict:
        """列出指定文件夹下的文件

        Args:
            folder_id: 文件夹 CID（None 则使用根目录）
            limit: 返回数量
            offset: 偏移量

        Returns:
            {
                "cid": str,
                "files": [...],
                "total": int,
                "offset": int,
                "limit": int,
            }
        """
        cid = folder_id or ROOT_CID
        client = await self._get_client()
        try:
            resp = await client.get(
                "/files",
                params={
                    "aid": 1,
                    "cid": cid,
                    "o": "user_update_time",  # 按更新时间排序
                    "asc": 0,  # 降序
                    "show_dir": 1,  # 包含子目录
                    "limit": limit,
                    "offset": offset,
                    "type": 0,  # 0=全部 1=文件 2=文件夹（部分接口）
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if "state" in data and not data.get("state", False):
                self._maybe_auth_error(data)
                err = data.get("error") or "列目录失败"
                raise RuntimeError(f"115 列目录失败: {err}")

            # 115 返回样例：
            # {"state": true, "data": [{"fid": "...", "n": "file.mp4", "s": 1234, ...}], "count": 1, ...}
            files_raw = data.get("data", []) or []
            total = int(data.get("count", len(files_raw)) or len(files_raw))

            files = []
            for item in files_raw:
                cid_val = str(item.get("cid", "0"))
                fid_val = str(item.get("fid", "") or item.get("id", "") or "")
                # 115 中目录有 cid 无 fid，文件有 fid
                is_dir = bool(item.get("pid") is not None and not fid_val) or bool(
                    item.get("fc", 0)
                )
                # fc 字段：文件夹子项数（>=0 表示是文件夹）
                if "fc" in item:
                    is_dir = True
                file_size = int(item.get("s", item.get("size", 0)) or 0)
                files.append({
                    "cid": cid_val,
                    "fid": fid_val,
                    "name": item.get("n", item.get("name", "")),
                    "size": file_size,
                    "size_text": _format_size(file_size),
                    "modified": item.get("t", item.get("modified", "")),
                    "ext": item.get("ico", item.get("ext", item.get("pc", ""))),
                    "is_dir": is_dir,
                    # pickcode 用于获取下载直链
                    "pickcode": item.get("pc", item.get("pickcode", "")),
                    "sha1": item.get("sha", item.get("sha1", "")),
                })

            return {
                "cid": cid,
                "files": files,
                "total": total,
                "offset": offset,
                "limit": limit,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"115 列目录失败 HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            )
            raise RuntimeError(f"列目录失败: HTTP {e.response.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"115 列目录异常: {e}")
            raise RuntimeError(f"列目录异常: {e}")

    async def search_files(self, keyword: str, folder_id: Optional[str] = None) -> list[dict]:
        """在指定文件夹下搜索文件（含子目录）

        Args:
            keyword: 搜索关键词
            folder_id: 起始文件夹 CID（None 则使用根目录）

        Returns:
            文件列表（格式同 list_files 中的元素）
        """
        cid = folder_id or ROOT_CID
        client = await self._get_client()
        try:
            resp = await client.get(
                "/files/search",
                params={
                    "aid": 1,
                    "cid": cid,
                    "search_value": keyword,
                    "type": 0,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("state", False):
                self._maybe_auth_error(data)
                return []
            files_raw = data.get("data", []) or []
            results = []
            for item in files_raw:
                cid_val = str(item.get("cid", "0"))
                fid_val = str(item.get("fid", ""))
                is_dir = "fc" in item
                file_size = int(item.get("s", 0) or 0)
                results.append({
                    "cid": cid_val,
                    "fid": fid_val,
                    "name": item.get("n", ""),
                    "size": file_size,
                    "size_text": _format_size(file_size),
                    "modified": item.get("t", ""),
                    "ext": item.get("ico", ""),
                    "is_dir": is_dir,
                    "pickcode": item.get("pc", ""),
                    "sha1": item.get("sha", ""),
                })
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"115 搜索文件失败 HTTP {e.response.status_code}")
            raise RuntimeError(f"搜索文件失败: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"115 搜索文件异常: {e}")
            raise RuntimeError(f"搜索文件异常: {e}")

    async def scan_folder(
        self, folder_id: Optional[str] = None, recursive: bool = True, max_depth: int = 5
    ) -> list[dict]:
        """扫描文件夹下的所有文件（可选递归）

        Args:
            folder_id: 起始文件夹 CID
            recursive: 是否递归扫描子目录
            max_depth: 最大递归深度

        Returns:
            文件列表
        """
        start_cid = folder_id or ROOT_CID
        results: list[dict] = []
        seen: set[str] = set()

        async def _scan(current_cid: str, depth: int) -> None:
            if depth > max_depth or current_cid in seen:
                return
            seen.add(current_cid)
            try:
                offset = 0
                while True:
                    listing = await self.list_files(current_cid, limit=100, offset=offset)
                    files = listing.get("files", [])
                    if not files:
                        break
                    for f in files:
                        if f["is_dir"]:
                            if recursive:
                                await _scan(f["cid"], depth + 1)
                        else:
                            results.append({**f, "parent_cid": current_cid, "depth": depth})
                    if len(files) < 100:
                        break
                    offset += 100
            except Exception as e:
                logger.warning(f"扫描目录 {current_cid} 失败: {e}")

        await _scan(start_cid, 0)
        logger.info(f"115 网盘扫描 {start_cid} 完成: 找到 {len(results)} 个文件")
        return results

    # ============================================
    # 文件下载与校验
    # ============================================

    async def get_download_url(self, pickcode: str) -> dict:
        """获取文件下载直链

        115 的下载直链通过 pickcode 获取，返回一个带过期时间的 OSS URL。
        客户端可直接用此 URL 下载文件，或交给 ffmpeg / mpv 流式播放。

        Args:
            pickcode: 文件的 pickcode（list_files 返回的 pickcode 字段）

        Returns:
            {
                "url": str,
                "file_name": str,
                "file_size": int,
                "expires": str,
            }
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                "/files/download",
                params={
                    "pickcode": pickcode,
                    "t": int(time.time()),  # 防缓存
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._assert_state(data, "获取下载链接")

            d = data.get("data", {}) or {}
            url = d.get("file_url") or d.get("url") or ""
            if not url:
                raise RuntimeError("115 返回的下载链接为空")

            return {
                "url": url,
                "file_name": d.get("file_name", ""),
                "file_size": int(d.get("file_size", 0) or 0),
                "expires": d.get("expires", ""),
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"115 获取下载链接失败 HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            )
            raise RuntimeError(f"获取下载链接失败: HTTP {e.response.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"115 获取下载链接异常: {e}")
            raise RuntimeError(f"获取下载链接异常: {e}")

    async def get_file_sha1(self, file_id: str) -> dict:
        """获取文件 SHA1 校验值

        用于校验下载文件完整性，避免离线下载后文件损坏。

        Args:
            file_id: 文件 fid

        Returns:
            {"sha1": str, "file_id": str}
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                "/files/sha1",
                params={
                    "file_id": file_id,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._assert_state(data, "获取 SHA1")
            d = data.get("data", {}) or {}
            return {
                "sha1": d.get("sha1", d.get("sha", "")),
                "file_id": file_id,
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"115 获取 SHA1 失败 HTTP {e.response.status_code}")
            raise RuntimeError(f"获取 SHA1 失败: HTTP {e.response.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"115 获取 SHA1 异常: {e}")
            raise RuntimeError(f"获取 SHA1 异常: {e}")

    async def move_file(self, file_ids: list[str], target_cid: str) -> dict:
        """移动文件到指定目录

        用于离线下载完成后将文件移动到目标分类目录。

        Args:
            file_ids: 文件 fid 列表
            target_cid: 目标文件夹 CID

        Returns:
            {"success": bool, "message": str}
        """
        client = await self._get_client()
        try:
            resp = await client.post(
                "/files/move",
                data={
                    "pid": target_cid,
                    "fid": ",".join(file_ids),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            success = bool(data.get("state", False))
            if not success:
                self._maybe_auth_error(data)
            message = data.get("error") or ("移动成功" if success else "移动失败")
            return {"success": success, "message": message}
        except httpx.HTTPStatusError as e:
            logger.error(f"115 移动文件失败 HTTP {e.response.status_code}")
            raise RuntimeError(f"移动文件失败: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"115 移动文件异常: {e}")
            raise RuntimeError(f"移动文件异常: {e}")


# 全局单例
pan_115_client = Pan115Client()

__all__ = ["pan_115_client", "Pan115Client"]
