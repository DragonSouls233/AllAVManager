"""Gfriends 头像库批量导入服务

Gfriends 是 GitHub 上的演员头像集合仓库：
https://github.com/gfriends/gfriends

仓库根目录的 Filetree.json 列出了所有头像文件的路径，
按演员名分目录存储，文件名即演员名（日文/英文）。

本服务实现：
1. 拉取 Filetree.json 索引
2. 与本地 Actor 表匹配（按 name / name_jp）
3. 批量下载头像到 data/avatars/actor_{id}.jpg
4. 自动调用人脸裁剪（复用现有 FaceCropper）
5. 更新 Actor.avatar_url

参考 Gfriends 项目本身、以及 metatube / mdc-ng 的头像管理思路。
"""

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
from sqlalchemy import select, or_

from app.config.manager import get_config, get_config_manager
from app.db.database import get_database
from app.db.models import Actor
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Gfriends 仓库常量
GFRIENDS_REPO = "gfriends/gfriends"
GFRIENDS_BRANCH = "master"
FILETREE_URL = f"https://raw.githubusercontent.com/{GFRIENDS_REPO}/{GFRIENDS_BRANCH}/Filetree.json"
RAW_BASE = f"https://raw.githubusercontent.com/{GFRIENDS_REPO}/{GFRIENDS_BRANCH}/"

# 下载限流
MAX_CONCURRENT_DOWNLOADS = 5  # 并发下载数
DOWNLOAD_TIMEOUT = 30  # 单个头像下载超时


# ===== 本地资料库（离线 Gfriends 副本）支持 =====
# 当无法访问 GitHub（国内网络 / 代理缺失）时，可直接使用本地已下载的 Gfriends 资料库。
# 目录结构：<LIB>/Content/{制片厂}/{演员名}.jpg
_LOCAL_INDEX: dict = {}
_LOCAL_INDEX_LOADED = False
_LOCAL_LIB_PATH: Optional[Path] = None


def detect_local_library() -> Optional[Path]:
    """探测本地 Gfriends 头像库根目录（需含 Content/ 子目录）"""
    candidates: list = []
    # 1) 优先:环境变量(运行时最高优先级)
    env = os.environ.get("MDCX_AVATAR_LIBRARY")
    if env:
        candidates.append(Path(env))
    # 2) 配置文件中显式指定的路径(用户在前端填写)
    try:
        cfg = get_config_manager().computed.config.gfriends
        if cfg.local_library_path:
            candidates.append(Path(cfg.local_library_path))
            # 兼容:用户填的是 gfriends-master 根目录,自动加 Content
            p = Path(cfg.local_library_path)
            if not p.name.lower().startswith("content") and (p / "Content").exists():
                candidates.append(p / "Content")
            elif p.exists() and p.is_dir():
                candidates.append(p)
    except Exception:
        pass
    # 3) 已知默认位置（NAS 映射盘 / 本地副本）
    candidates.append(Path(r"O:/MDCX/GitHub-ZIP/P1-High/gfriends-master/gfriends-master"))
    candidates.append(Path(r"/o/MDCX/GitHub-ZIP/P1-High/gfriends-master/gfriends-master"))
    candidates.append(Path(r"G:/MDCX/GitHub-ZIP/P1-High/gfriends-master/gfriends-master"))
    candidates.append(Path(r"/g/MDCX/GitHub-ZIP/P1-High/gfriends-master/gfriends-master"))
    try:
        candidates.append(Path(get_config_manager().computed.data_dir) / "gfriends-library" / "Content")
    except Exception:
        pass
    for c in candidates:
        try:
            if c.exists() and c.is_dir():
                # 优先返回根目录(让上层决定是否找 Content/)
                # 但若本身就是 Content 目录,也接受
                return c
        except Exception:
            continue
    return None


def set_local_library_path(path_str: str) -> None:
    """运行时切换本地资料库路径(用于前端配置热更新)

    清空已构建的索引,下次 build_local_index 会重新扫描新路径。
    """
    global _LOCAL_INDEX, _LOCAL_INDEX_LOADED, _LOCAL_LIB_PATH
    _LOCAL_INDEX = {}
    _LOCAL_INDEX_LOADED = False
    _LOCAL_LIB_PATH = None
    logger.info(f"本地资料库路径已切换: {path_str or '(空,回退到自动探测)'}")


def _normalize_name(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "").replace("　", "")


def build_local_index() -> dict:
    """构建 演员名 → 本地文件路径 索引（带缓存，仅全量扫描一次）"""
    global _LOCAL_INDEX, _LOCAL_INDEX_LOADED, _LOCAL_LIB_PATH
    if _LOCAL_INDEX_LOADED:
        return _LOCAL_INDEX
    _LOCAL_LIB_PATH = detect_local_library()
    _LOCAL_INDEX = {}
    if _LOCAL_LIB_PATH:
        try:
            # 智能判断:根目录还是 Content 子目录
            # 用户通常填写 gfriends-master 根目录,内部有 Content/
            scan_dir = _LOCAL_LIB_PATH
            if _LOCAL_LIB_PATH.name.lower() != "content" and (_LOCAL_LIB_PATH / "Content").exists():
                scan_dir = _LOCAL_LIB_PATH / "Content"

            for studio_dir in scan_dir.iterdir():
                if not studio_dir.is_dir():
                    continue
                for f in studio_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                        key = _normalize_name(f.stem)
                        if key and key not in _LOCAL_INDEX:
                            _LOCAL_INDEX[key] = f
        except Exception as e:
            logger.warning(f"扫描本地资料库失败: {e}")
    _LOCAL_INDEX_LOADED = True
    logger.info(f"本地资料库索引构建完成: {len(_LOCAL_INDEX)} 张（路径: {_LOCAL_LIB_PATH}）")
    return _LOCAL_INDEX


def get_local_library_status() -> dict:
    """返回本地资料库状态（不强制全量扫描，仅在已构建时给出数量）"""
    global _LOCAL_LIB_PATH
    if not _LOCAL_LIB_PATH:
        _LOCAL_LIB_PATH = detect_local_library()
    return {
        "available": bool(_LOCAL_LIB_PATH),
        "path": str(_LOCAL_LIB_PATH) if _LOCAL_LIB_PATH else None,
        "count": len(_LOCAL_INDEX) if _LOCAL_INDEX_LOADED else None,
    }


def find_local_avatar(name: str, name_jp: Optional[str] = None) -> Optional[Path]:
    """在本地资料库中按演员名查找头像文件"""
    idx = build_local_index()
    if not idx:
        return None
    for n in (name, name_jp):
        if not n:
            continue
        p = idx.get(_normalize_name(n))
        if p and p.exists():
            return p
    return None


def copy_local_avatar(actor_id: int, src_path: Path, avatars_dir: Path) -> Path:
    """将本地头像文件复制到 DATA/avatars/actor_{id}.jpg"""
    target = avatars_dir / f"actor_{actor_id}.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, target)
    return target


class GfriendsImporter:
    """Gfriends 头像库批量导入器"""

    def __init__(self):
        self._index: Optional[dict] = None
        self._index_loaded = False
        # 任务状态（job_id → status）
        self._jobs: dict[str, dict] = {}

    async def _load_index(self) -> dict:
        """加载 Gfriends Filetree.json 索引"""
        if self._index_loaded and self._index:
            return self._index

        proxy = None
        try:
            from app.services.proxy_manager import get_effective_proxy_url
            proxy = get_effective_proxy_url()
        except Exception:
            pass

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(FILETREE_URL, proxy=proxy) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"拉取 Filetree.json 失败: HTTP {resp.status}")
                # GitHub raw 返回的 Content-Type 是 text/plain 而非 application/json,
                # aiohttp 默认会校验 MIME 类型并抛 ContentTypeError。
                # content_type=None 跳过该校验（响应体本身是合法 JSON）。
                self._index = await resp.json(content_type=None)

        self._index_loaded = True
        logger.info(f"Gfriends 索引加载完成: {len(self._index)} 个目录")
        return self._index

    def _find_avatar_url(self, actor_name: str, index: dict) -> Optional[str]:
        """在 Filetree 索引中查找演员的头像 URL

        Filetree.json 格式：
        {
          "Content": {
            "ActorName1.jpg": "Content/ActorName1.jpg",
            "ActorName2.jpg": "Content/ActorName2.jpg"
          },
          ...
        }

        匹配策略：
        1. 精确匹配文件名（含 .jpg 后缀）
        2. 模糊匹配（去除空格、大小写不敏感）
        """
        if not actor_name:
            return None

        target = actor_name.strip()
        target_lower = target.lower().replace(" ", "")

        # 遍历所有目录
        for dir_name, files in index.items():
            if not isinstance(files, dict):
                continue
            for filename, path in files.items():
                # 精确匹配
                if filename == f"{target}.jpg" or filename == target:
                    return RAW_BASE + path if not path.startswith("http") else path
                # 模糊匹配
                normalized = filename.replace(".jpg", "").lower().replace(" ", "")
                if normalized == target_lower:
                    return RAW_BASE + path if not path.startswith("http") else path

        return None

    async def _download_one(
        self,
        session: aiohttp.ClientSession,
        actor: Actor,
        avatar_url: str,
        avatars_dir: Path,
        semaphore: asyncio.Semaphore,
    ) -> bool:
        """下载单个演员的头像"""
        async with semaphore:
            try:
                async with session.get(avatar_url) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.read()

                # 保存到 data/avatars/actor_{id}.jpg
                target_path = avatars_dir / f"actor_{actor.id}.jpg"
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "wb") as f:
                    f.write(data)

                # 调用人脸裁剪（可选，失败不阻塞）
                try:
                    from app.utils.face_crop import FaceCropper
                    cropper = FaceCropper()
                    cropper.crop_and_save(str(target_path), str(target_path))
                except Exception as e:
                    logger.debug(f"人脸裁剪跳过（不阻塞）: actor_{actor.id}: {e}")

                return True
            except Exception as e:
                logger.debug(f"下载头像失败 {actor.name}: {e}")
                return False

    async def run_import(
        self,
        job_id: str,
        overwrite: bool = False,
        min_movies: int = 0,
        use_local: bool = False,
    ) -> dict:
        """执行批量导入

        Args:
            job_id: 任务 ID
            overwrite: 是否覆盖已有头像
            min_movies: 仅导入出演影片数 >= min_movies 的演员（0=全部）
            use_local: 强制使用本地资料库(覆盖配置中的 mode)

        Returns:
            {"total": N, "matched": M, "downloaded": D, "skipped": S, "failed": F}
        """
        # 2026-07-08 修复 2: 决定使用本地还是在线模式
        # 优先级:use_local 参数 > gfriends config.mode > 默认 online
        try:
            gcfg = get_config_manager().computed.config.gfriends
        except Exception:
            gcfg = None
        if gcfg and gcfg.prefer_local and gcfg.local_library_path and not use_local:
            # 配置启用"优先本地"且填了路径,且本次未显式指定 use_local=False
            use_local = True
        if not use_local and gcfg and gcfg.mode == "local":
            use_local = True
        # 若 use_local=True 但配置没填路径,尝试自动探测
        if use_local and not _LOCAL_INDEX_LOADED:
            build_local_index()
        self._jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "progress": {"total": 0, "matched": 0, "downloaded": 0, "skipped": 0, "failed": 0},
        }

        try:
            # 1. 加载索引
            index = await self._load_index()

            # 2. 查询本地演员
            db = get_database()
            async with db.session() as session:
                query = select(Actor)
                if not overwrite:
                    query = query.where(Actor.avatar_url.is_(None))
                if min_movies > 0:
                    # 子查询：出演影片数 >= min_movies
                    from app.db.models import MovieActor
                    from sqlalchemy import func
                    subq = (
                        select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("cnt"))
                        .group_by(MovieActor.actor_id)
                        .having(func.count(MovieActor.movie_id) >= min_movies)
                        .subquery()
                    )
                    query = query.join(subq, Actor.id == subq.c.actor_id)

                result = await session.execute(query.order_by(Actor.name))
                actors = result.scalars().all()

                progress = self._jobs[job_id]["progress"]
                progress["total"] = len(actors)
                logger.info(f"Gfriends 批量导入: 共 {len(actors)} 个演员待处理")

                # 3. 匹配 + 下载
                avatars_dir = Path(get_config_manager().computed.data_dir) / "avatars"
                avatars_dir.mkdir(parents=True, exist_ok=True)

                proxy = None
                try:
                    from app.services.proxy_manager import get_effective_proxy_url
                    proxy = get_effective_proxy_url()
                except Exception:
                    pass

                timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

                online_matched = []   # (actor, url) 需要在线下载
                local_matched = []    # actor 已复制到本地，待更新数据库
                async with aiohttp.ClientSession(timeout=timeout) as http_session:
                    for actor in actors:
                        if use_local:
                            # 本地资料库模式：直接复制本地头像文件，不访问 GitHub
                            local_path = find_local_avatar(actor.name, actor.name_jp)
                            if not local_path:
                                progress["skipped"] += 1
                                continue
                            copy_local_avatar(actor.id, local_path, avatars_dir)
                            progress["matched"] += 1
                            local_matched.append(actor)
                            continue

                        # 在线模式：先用 name 匹配，再用 name_jp 匹配
                        avatar_url = self._find_avatar_url(actor.name, index)
                        if not avatar_url and actor.name_jp:
                            avatar_url = self._find_avatar_url(actor.name_jp, index)

                        if not avatar_url:
                            progress["skipped"] += 1
                            continue

                        progress["matched"] += 1
                        online_matched.append((actor, avatar_url))

                    # 批量并发下载（仅在线模式）
                    if online_matched:
                        tasks = [
                            self._download_one(http_session, actor, url, avatars_dir, semaphore)
                            for actor, url in online_matched
                        ]
                        results = await asyncio.gather(*tasks, return_exceptions=True)

                        for (actor, url), success in zip(online_matched, results):
                            if success is True:
                                actor.avatar_url = f"/api/v1/actors/{actor.id}/avatar/file"
                                progress["downloaded"] += 1
                            else:
                                progress["failed"] += 1

                    # 本地模式已复制的文件：直接标记为已下载并更新数据库
                    for actor in local_matched:
                        actor.avatar_url = f"/api/v1/actors/{actor.id}/avatar/file"
                        progress["downloaded"] += 1

                    await session.commit()

                self._jobs[job_id]["status"] = "completed"
                self._jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                logger.info(
                    f"Gfriends 批量导入完成: 总 {progress['total']}, 匹配 {progress['matched']}, "
                    f"下载 {progress['downloaded']}, 跳过 {progress['skipped']}, 失败 {progress['failed']}"
                )
                return progress

        except Exception as e:
            self._jobs[job_id]["status"] = "failed"
            self._jobs[job_id]["error"] = str(e)
            logger.error(f"Gfriends 批量导入失败: {e}")
            raise

    def get_job_status(self, job_id: str) -> dict:
        """获取任务状态"""
        return self._jobs.get(job_id, {"status": "unknown"})

    def list_jobs(self) -> list[dict]:
        """列出所有任务"""
        return [{"job_id": k, **v} for k, v in self._jobs.items()]


# 全局单例
gfriends_importer = GfriendsImporter()


__all__ = ["gfriends_importer", "GfriendsImporter"]
