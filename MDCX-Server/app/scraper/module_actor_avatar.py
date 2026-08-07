"""
模块演员头像刮削器

支持 uncensored, fc2, chinese, western, pornhub 模块的演员头像刮削

头像统一落盘到 DATA/avatars/{module}/actor_{id}.jpg，与 movies/{module} 的
目录结构保持一致，避免各模块 actors 表 id 独立自增导致的跨模块串图问题。
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.manager import get_config, get_config_manager
from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)

_active_module_avatar_jobs: dict = {}

_module_avatar_config = {
    "uncensored": {
        "domains": ["https://www.heyzo.com", "https://javdb.com"],
        "search_paths": [
            ("heyzo", lambda name: f"https://www.heyzo.com/search/{name.replace(' ', '%20')}"),
            ("javdb", lambda name: f"https://javdb.com/search?q={name.replace(' ', '%20')}&f=actor"),
        ],
    },
    "fc2": {
        "domains": ["https://javdb.com", "https://fc2club.com"],
        "search_paths": [
            ("javdb", lambda name: f"https://javdb.com/search?q={name.replace(' ', '%20')}&f=actor"),
            ("fc2club", lambda name: f"https://fc2club.com/search?q={name.replace(' ', '%20')}"),
        ],
    },
    "chinese": {
        "domains": ["https://javdb.com"],
        "search_paths": [
            ("javdb", lambda name: f"https://javdb.com/search?q={name.replace(' ', '%20')}&f=actor"),
        ],
    },
    "western": {
        "domains": ["https://javdb.com", "https://naughtyamerica.com"],
        "search_paths": [
            ("javdb", lambda name: f"https://javdb.com/search?q={name.replace(' ', '%20')}&f=actor"),
        ],
    },
    "pornhub": {
        "domains": ["https://javdb.com"],
        "search_paths": [
            ("javdb", lambda name: f"https://javdb.com/search?q={name.replace(' ', '%20')}&f=actor"),
        ],
    },
}


class ModuleActorAvatarScraper:
    """模块演员头像刮削器"""

    def __init__(self, module_name: str, min_movies: int = 1):
        self.module_name = module_name
        self.min_movies = min_movies
        self.db = ModuleDatabase.get_instance(module_name)
        self.config = _module_avatar_config.get(module_name, {})

        self._progress = {
            "total": 0,
            "completed": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "current_actor": None,
            "status": "idle",
        }

        config = get_config()
        self._proxy = None
        proxy_config = config.proxy
        if proxy_config and proxy_config.get("enabled"):
            self._proxy = proxy_config.get("http")

        # 按模块隔离: DATA/avatars/{module_name}/actor_{id}.jpg
        # 与 movies/{module} 目录结构一致，避免跨模块 id 串图
        data_dir = Path(get_config_manager().computed.data_dir)
        self._avatar_dir = (data_dir / "avatars" / module_name).resolve()
        self._avatar_dir.mkdir(parents=True, exist_ok=True)

    def get_progress(self) -> dict:
        return self._progress.copy()

    def cancel(self):
        self._progress["status"] = "cancelled"

    async def scrape_all(self) -> dict:
        """批量刮削所有符合条件的演员头像"""
        self._progress["status"] = "running"

        actors = await self._find_actors_without_avatar()
        self._progress["total"] = len(actors)

        if not actors:
            self._progress["status"] = "completed"
            logger.info(f"[{self.module_name}] 没有需要补充头像的演员")
            return self.get_progress()

        logger.info(f"[{self.module_name}] 找到 {len(actors)} 个需要补充头像的演员")

        for actor in actors:
            if self._progress["status"] == "cancelled":
                break

            self._progress["current_actor"] = actor.name
            try:
                success = await self._scrape_one(actor)
                if success:
                    self._progress["success"] += 1
                else:
                    self._progress["failed"] += 1
            except Exception as e:
                logger.error(f"[{self.module_name}] 刮削演员 {actor.name} 头像失败: {e}")
                self._progress["failed"] += 1

            self._progress["completed"] += 1
            await asyncio.sleep(1.0)

        self._progress["status"] = "completed"
        self._progress["current_actor"] = None

        return self.get_progress()

    async def _find_actors_without_avatar(self) -> list:
        """查找需要头像的演员"""
        import importlib

        model_map = {
            "chinese": ("app.db.chinese_models", "ChineseActor"),
            "uncensored": ("app.db.uncensored_models", "UncensoredActor"),
            "fc2": ("app.db.fc2_models", "Fc2Actor"),
            "pornhub": ("app.db.pornhub_models", "PornhubActor"),
            "western": ("app.db.western_models", "WesternActor"),
        }

        if self.module_name not in model_map:
            return []

        model_path, actor_class = model_map[self.module_name]

        try:
            mod = importlib.import_module(model_path)
            actor_model = getattr(mod, actor_class)
        except (ImportError, AttributeError):
            logger.warning(f"[{self.module_name}] 无法导入 Actor 模型")
            return []

        session = await self.db.get_session()
        try:
            from sqlalchemy import select

            stmt = select(actor_model).where(
                actor_model.movie_count >= self.min_movies,
                actor_model.avatar_url.is_(None) | (actor_model.avatar_url == "")
            ).order_by(actor_model.movie_count.desc())

            result = await session.execute(stmt)
            actors = result.scalars().all()
            return list(actors)
        finally:
            await session.close()

    async def _scrape_one(self, actor) -> bool:
        """刮削单个演员的头像"""
        avatar_url = await self._search_avatar(actor.name)

        if not avatar_url:
            logger.debug(f"[{self.module_name}] 未找到演员 {actor.name} 的头像")
            return False

        local_path = await self._download_avatar(actor.id, avatar_url, actor.name)

        if not local_path:
            return False

        session = await self.db.get_session()
        try:
            import importlib

            model_map = {
                "chinese": ("app.db.chinese_models", "ChineseActor"),
                "uncensored": ("app.db.uncensored_models", "UncensoredActor"),
                "fc2": ("app.db.fc2_models", "Fc2Actor"),
                "pornhub": ("app.db.pornhub_models", "PornhubActor"),
                "western": ("app.db.western_models", "WesternActor"),
            }

            model_path, actor_class = model_map[self.module_name]
            mod = importlib.import_module(model_path)
            actor_model = getattr(mod, actor_class)

            from sqlalchemy import select
            stmt = select(actor_model).where(actor_model.id == actor.id)
            result = await session.execute(stmt)
            db_actor = result.scalar_one_or_none()

            if db_actor:
                db_actor.avatar_url = str(local_path)
                await session.commit()
                logger.info(f"[{self.module_name}] 演员 {actor.name} 头像已更新: {local_path}")
                return True
        except Exception as e:
            logger.error(f"[{self.module_name}] 更新演员头像失败: {e}")
        finally:
            await session.close()

        return False

    async def _search_avatar(self, name: str) -> Optional[str]:
        """搜索演员头像 URL"""
        from urllib.parse import quote
        from app.utils.http_client import AsyncHttpClient

        search_paths = self.config.get("search_paths", [])

        for site_name, search_func in search_paths:
            try:
                search_url = search_func(name)
                logger.info(f"[{self.module_name}] 搜索 {site_name}: {search_url}")

                async with AsyncHttpClient() as client:
                    html = await client.get_text(search_url, timeout=15)

                if not html:
                    continue

                avatar_url = self._extract_avatar_from_html(html, site_name)
                if avatar_url:
                    return avatar_url

            except Exception as e:
                logger.debug(f"[{self.module_name}] 搜索 {site_name} 失败: {e}")
                continue

        return None

    def _extract_avatar_from_html(self, html: str, site: str) -> Optional[str]:
        """从 HTML 中提取头像 URL"""
        import re

        if site == "javdb":
            match = re.search(r'<img[^>]+src="([^"]*actor[^"]*\.(?:jpg|png|jpeg))"', html, re.I)
            if match:
                return match.group(1)

            img_matches = re.findall(r'<img[^>]+src="([^"]+)"[^>]*class="[^"]*actor[^"]*"', html, re.I)
            for img in img_matches[:3]:
                if any(ext in img.lower() for ext in ['.jpg', '.png', '.jpeg']):
                    return img

        elif site == "heyzo":
            match = re.search(r'<img[^>]+src="([^"]*actress[^"]*\.(?:jpg|png|jpeg))"', html, re.I)
            if match:
                return match.group(1)

        return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=5))
    async def _download_avatar(self, actor_id: int, url: str, actor_name: str) -> Optional[Path]:
        """下载头像到 DATA/avatars/{module}/actor_{id}.jpg"""
        from app.utils.http_client import AsyncHttpClient

        ext = "jpg" if ".jpg" in url.lower() else "png"
        filename = f"actor_{actor_id}.{ext}"
        local_path = self._avatar_dir / filename

        try:
            async with AsyncHttpClient() as client:
                content = await client.get_bytes(url, timeout=30)

            local_path.write_bytes(content)
            return local_path
        except Exception as e:
            logger.error(f"[{self.module_name}] 下载头像失败: {e}")
            return None


async def run_module_avatar_scrape_job(job_id: str, module_name: str, min_movies: int = 1):
    """运行模块头像刮削后台任务"""
    scraper = ModuleActorAvatarScraper(module_name=module_name, min_movies=min_movies)
    _active_module_avatar_jobs[job_id] = {
        "scraper": scraper,
        "started_at": datetime.now(),
    }

    try:
        result = await scraper.scrape_all()
        _active_module_avatar_jobs[job_id]["result"] = result
        _active_module_avatar_jobs[job_id]["finished_at"] = datetime.now()
    except Exception as e:
        logger.error(f"模块头像刮削任务 {job_id} 失败: {e}")
        _active_module_avatar_jobs[job_id]["error"] = str(e)
        _active_module_avatar_jobs[job_id]["finished_at"] = datetime.now()


def get_module_avatar_job_status(job_id: str) -> Optional[dict]:
    """获取模块头像刮削任务状态"""
    job = _active_module_avatar_jobs.get(job_id)
    if not job:
        return None

    scraper = job.get("scraper")
    progress = scraper.get_progress() if scraper else {}

    return {
        "job_id": job_id,
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
        **progress,
    }


def cancel_module_avatar_job(job_id: str) -> bool:
    """取消模块头像刮削任务"""
    job = _active_module_avatar_jobs.get(job_id)
    if not job:
        return False

    scraper = job.get("scraper")
    if scraper:
        scraper.cancel()
    return True
