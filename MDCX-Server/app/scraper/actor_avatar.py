"""
演员头像刮削器

从 JavBus 和 JavDB 等站点抓取演员头像，下载并保存到本地。
只处理 2 部以上且没有头像的演员。
"""

import asyncio
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from lxml import etree

from app.config.manager import get_config_manager
from app.db.database import Database
from app.db.models import Actor, MovieActor
from app.utils.http_client import AsyncHttpClient

from sqlalchemy import select, func

logger = logging.getLogger(__name__)


def _avatar_backing_path(actor_id: int) -> Path:
    """返回演员头像的 backing 文件路径 (data/avatars/actor_{id}.jpg)。

    computed.data_dir 为相对路径 "data", 需相对 server 启动目录解析为绝对路径。
    """
    try:
        from app.config.manager import get_config_manager
        data_dir = Path(get_config_manager().computed.data_dir)
        if not data_dir.is_absolute():
            data_dir = Path.cwd() / data_dir
        return data_dir / "avatars" / f"actor_{actor_id}.jpg"
    except Exception:
        return Path.cwd() / "data" / "avatars" / f"actor_{actor_id}.jpg"


def actor_needs_avatar(actor: "Actor") -> bool:
    """判断演员是否仍需要(重新)下载头像。

    旧逻辑仅以 avatar_url 是否为空来判定"已有头像"。但若某次刮削只把
    远程 URL 写入 avatar_url 而未真正下载到本地, 该 URL 既不算空(被误判为
    '已有头像'而跳过), 又无法被 /avatar/file 直接服务(404)。

    综合判定"是否已有可用本地头像":
      - 空值                       -> 需要
      - 远程 URL(http/https)       -> 需要(本地无法服务, 需重新落地)
      - 本站服务 URL(/api/v1/...)  -> 校验 backing 文件是否存在
      - 文件系统路径(绝对/相对)   -> 解析后校验文件是否存在
    仅当确无任何可用本地头像时才返回 True, 避免已落地头像被反复重复刮削。
    """
    u = actor.avatar_url
    if not u:
        return True
    u = str(u).strip()

    # 远程 URL: 无法被 /avatar/file 本地服务, 视为需要重新落地为本地文件
    if u.startswith(("http://", "https://")):
        return True

    # 本站内部服务 URL(如 /api/v1/actors/{id}/avatar/file): 背后文件即
    # data/avatars/actor_{id}.jpg, 校验其是否存在即可
    if u.startswith("/"):
        backing = _avatar_backing_path(actor.id)
        return not (backing and backing.exists())

    # 文件系统路径(绝对或相对)。computed.data_dir 为相对 "data",
    # 相对 server 启动目录解析后与 get_actor_avatar_file 行为一致。
    p = Path(u)
    if not p.is_absolute():
        p = Path.cwd() / u
    return not p.exists()


class ActorAvatarScraper:
    """演员头像刮削器"""

    # JavBus 基础 URL（支持多个域名）
    JAVBUS_DOMAINS = [
        "https://www.javbus.com",
        "https://javbus.pw",
        "https://javbus.org",
        "https://javbus.io",
        "https://javbus.net",
    ]

    # JavDB 基础 URL
    JAVDB_DOMAINS = [
        "https://javdb.com",
        "https://javdb.io",
    ]

    def __init__(self, db: Database, min_movies: int = 2, use_local_library: bool = False):
        self.db = db
        self.min_movies = min_movies
        self.use_local_library = use_local_library
        self._progress = {
            "total": 0,
            "completed": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "current_actor": None,
            "status": "idle",
        }
        self._cloudscraper = None

    def get_progress(self) -> dict:
        return dict(self._progress)

    async def scrape_all(self) -> dict:
        """
        批量刮削所有符合条件的演员头像（2部以上且无头像）

        Returns:
            进度摘要
        """
        self._progress["status"] = "running"

        # 1. 查询符合条件的演员
        actors = await self._find_actors_without_avatar()
        self._progress["total"] = len(actors)

        if not actors:
            self._progress["status"] = "completed"
            logger.info("没有需要补充头像的演员")
            return self.get_progress()

        logger.info(f"找到 {len(actors)} 个需要补充头像的演员（>={self.min_movies}部且无头像）")

        # 2. 逐个刮削（限速，避免被封）
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
                logger.error(f"刮削演员 {actor.name} 头像失败: {e}")
                self._progress["failed"] += 1

            self._progress["completed"] += 1

            # 限速：每个演员间隔 1 秒
            await asyncio.sleep(1.0)

        self._progress["status"] = "completed"
        self._progress["current_actor"] = None
        logger.info(
            f"头像刮削完成: 成功={self._progress['success']}, "
            f"失败={self._progress['failed']}, 总计={self._progress['total']}"
        )
        return self.get_progress()

    async def _find_actors_without_avatar(self) -> list[Actor]:
        """查找 >= min_movies 部、名字有效、且无有效本地头像的演员"""
        async with self.db.session() as session:
            # 子查询：每个演员的作品数
            movie_count_subq = (
                select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("mc"))
                .group_by(MovieActor.actor_id)
                .subquery()
            )

            # 查询：>= min_movies 部 + 名字有效(排除佚名/空名)
            # 注: 不再用 avatar_url 是否为空来过滤 —— 远程 URL / 失效路径
            # 也属于"无有效本地头像", 需在 Python 层用 actor_needs_avatar 二次筛选
            query = (
                select(Actor)
                .outerjoin(movie_count_subq, Actor.id == movie_count_subq.c.actor_id)
                .where(
                    # 2部以上
                    func.coalesce(movie_count_subq.c.mc, 0) >= self.min_movies,
                    # 排除佚名
                    Actor.name != "佚名",
                    Actor.name.isnot(None),
                    Actor.name != "",
                )
                .order_by(func.coalesce(movie_count_subq.c.mc, 0).desc())
            )

            result = await session.execute(query)
            actors = list(result.scalars().all())

        # 仅保留"无有效本地头像"的演员(空值 / 远程URL / 本地文件缺失)
        return [a for a in actors if actor_needs_avatar(a)]

    async def _scrape_one(self, actor: Actor) -> bool:
        """刮削单个演员的头像"""
        # 0. 优先使用本地资料库（离线 Gfriends 副本）
        if self.use_local_library:
            try:
                from app.services.gfriends_importer import find_local_avatar
                # 本地资料库扫描(51172 个文件)为同步 IO, 若直接在当前协程
                # 执行会阻塞整个事件循环(服务器在扫描期间无法响应任何请求)。
                # 用 to_thread 卸载到线程池, 保持事件循环空闲并能被 /status 轮询。
                local_path = await asyncio.to_thread(find_local_avatar, actor.name, actor.name_jp)
                if local_path:
                    ok = await self._import_local_avatar(actor, local_path)
                    if ok:
                        return True
                    # 复制失败则继续走在线抓取
            except Exception as e:
                logger.debug(f"本地资料库匹配失败 {actor.name}: {e}")

        # 1. 首先尝试从 JavDB 搜索（更稳定）
        avatar_url = await self._search_javdb_avatar(actor.name, actor.name_jp)

        if not avatar_url:
            # 备用：尝试从 JavBus 搜索
            logger.debug(f"JavDB 未找到，尝试 JavBus: {actor.name}")
            avatar_url = await self._search_javbus_avatar(actor.name, actor.name_jp)

        if not avatar_url:
            logger.debug(f"未找到演员 {actor.name} 的头像")
            return False

        # 2. 下载头像（带人脸裁剪）
        local_path = await self._download_avatar(actor.id, avatar_url, actor_name=actor.name)

        if not local_path:
            return False

        # 3. 更新数据库
        async with self.db.session() as session:
            db_actor = await session.get(Actor, actor.id)
            if db_actor:
                db_actor.avatar_url = str(local_path)
                await session.commit()

        logger.info(f"演员 {actor.name} 头像已更新: {local_path}")
        return True

    async def _search_javdb_avatar(
        self, name: str, name_jp: Optional[str] = None
    ) -> Optional[str]:
        """从 JavDB 搜索演员头像 URL"""
        from urllib.parse import quote

        search_name = name_jp or name

        try:
            search_names = [search_name]
            if name_jp and name != name_jp:
                search_names.append(name)
            if name and name not in search_names:
                search_names.append(name)

            seen = set()
            search_names = [n for n in search_names if n and n not in seen and not seen.add(n)]

            for domain in self.JAVDB_DOMAINS:
                logger.debug(f"尝试 JavDB 域名: {domain}")

                for current_name in search_names:
                    encoded_name = quote(current_name)
                    search_url = f"{domain}/search?q={encoded_name}&f=actor"

                    logger.info(f"JavDB 搜索演员 {current_name}: {search_url}")

                    try:
                        async with AsyncHttpClient() as client:
                            html_text = await client.get_text(search_url)

                        if not html_text:
                            logger.debug(f"JavDB 搜索 {current_name} 结果为空")
                            continue

                        if "JavDB" not in html_text:
                            logger.debug(f"JavDB 页面内容异常")
                            continue

                        html = etree.fromstring(html_text, etree.HTMLParser())

                        actor_items = html.xpath('//div[@id="actors"]//div[@class="box actor-box"]')
                        if not actor_items:
                            actor_items = html.xpath('//div[@class="actors"]//div[contains(@class, "actor-box")]')

                        if not actor_items:
                            logger.debug(f"JavDB 搜索 {current_name} 未找到匹配的演员")
                            continue

                        logger.info(f"JavDB 搜索 {current_name} 找到 {len(actor_items)} 个演员")

                        for item in actor_items[:5]:
                            name_elements = item.xpath('.//strong/text()')
                            if not name_elements:
                                name_elements = item.xpath('.//img/@alt')

                            sname = name_elements[0].strip() if name_elements else ""
                            imgs = item.xpath('.//img[@class="avatar"]/@src')
                            if not imgs:
                                imgs = item.xpath('.//img/@src')
                            img_src = imgs[0] if imgs else ""

                            logger.debug(f"JavDB 候选: {sname} -> {img_src}")

                            if not sname or not img_src:
                                continue

                            if (sname == name or
                                sname == name_jp or
                                (name and sname.startswith(name[:2])) or
                                (name_jp and sname.startswith(name_jp[:2])) or
                                (name and name.startswith(sname[:2]))):
                                if img_src.startswith("//"):
                                    target_avatar = "https:" + img_src
                                elif img_src.startswith("/"):
                                    target_avatar = domain + img_src
                                else:
                                    target_avatar = img_src
                                logger.info(f"JavDB 找到匹配演员 {sname}: {target_avatar}")
                                return target_avatar

                        if actor_items:
                            first_item = actor_items[0]
                            imgs = first_item.xpath('.//img[@class="avatar"]/@src')
                            if not imgs:
                                imgs = first_item.xpath('.//img/@src')
                            if imgs:
                                img_src = imgs[0]
                                if img_src.startswith("//"):
                                    target_avatar = "https:" + img_src
                                elif img_src.startswith("/"):
                                    target_avatar = domain + img_src
                                else:
                                    target_avatar = img_src
                                logger.info(f"JavDB 取第一个候选结果: {target_avatar}")
                                return target_avatar
                    except Exception as e:
                        logger.debug(f"JavDB 请求失败 {search_url}: {e}")
                        continue

            return None

        except Exception as e:
            logger.error(f"JavDB 搜索演员 {name} 失败: {e}")
            return None

    async def _search_javbus_avatar(
        self, name: str, name_jp: Optional[str] = None
    ) -> Optional[str]:
        """从 JavBus 搜索演员头像 URL"""
        from urllib.parse import quote

        search_name = name_jp or name

        try:
            search_names = [search_name]
            if name_jp and name != name_jp:
                search_names.append(name)
            if name and name not in search_names:
                search_names.append(name)

            seen = set()
            search_names = [n for n in search_names if n and n not in seen and not seen.add(n)]

            for domain in self.JAVBUS_DOMAINS:
                logger.debug(f"尝试 JavBus 域名: {domain}")

                for current_name in search_names:
                    encoded_name = quote(current_name)

                    search_paths = [
                        f"{domain}/search?q={encoded_name}",
                        f"{domain}/search/{encoded_name}",
                    ]

                    for search_url in search_paths:
                        logger.info(f"JavBus 搜索演员 {current_name}: {search_url}")

                        try:
                            # 尝试使用 cloudscraper 绕过 Cloudflare
                            html_text = await self._fetch_with_cloudscraper(search_url)

                            if not html_text:
                                # 备用方案：使用常规 HTTP 客户端
                                async with AsyncHttpClient() as client:
                                    html_text = await client.get_text(search_url)

                        except Exception as e:
                            logger.debug(f"JavBus 搜索 {search_url} 失败: {e}")
                            continue

                        if not html_text:
                            logger.debug(f"JavBus 搜索 {current_name} 结果为空")
                            continue

                        # 检查是否是 Cloudflare 挑战页面
                        if "cloudflare" in html_text.lower() or "cf-browser-verification" in html_text.lower():
                            logger.debug(f"JavBus 遇到 Cloudflare 挑战，尝试下一个域名")
                            break

                        # 检查是否是 driver-verify 页面
                        if "driver-verify" in html_text.lower():
                            logger.debug(f"JavBus 遇到 driver 验证，尝试下一个域名")
                            break

                        html = etree.fromstring(html_text, etree.HTMLParser())

                        star_items = html.xpath('//a[contains(@class, "avatar-box")]')
                        if not star_items:
                            star_items = html.xpath('//div[@class="item"]//a[.//img]')
                        if not star_items:
                            star_items = html.xpath('//div[contains(@class, "movie-item")]//a')

                        if not star_items:
                            logger.debug(f"JavBus 搜索 {current_name} 未找到匹配的演员")
                            continue

                        logger.info(f"JavBus 搜索 {current_name} 找到 {len(star_items)} 个演员")

                        for item in star_items:
                            name_spans = item.xpath('.//span[@class="star-name"]/text()')
                            if not name_spans:
                                name_spans = item.xpath('.//div[@class="photo-info"]//span/text()')
                            if not name_spans:
                                name_spans = item.xpath('.//img/@alt')
                            sname = name_spans[0].strip() if name_spans else ""

                            imgs = item.xpath('.//img/@src')
                            img_src = imgs[0] if imgs else ""

                            logger.debug(f"JavBus 候选: {sname} -> {img_src}")

                            if not sname or not img_src:
                                continue

                            if (sname == name or
                                sname == name_jp or
                                (name and sname.startswith(name[:2])) or
                                (name_jp and sname.startswith(name_jp[:2])) or
                                (name and name.startswith(sname[:2]))):
                                if img_src.startswith("//"):
                                    target_avatar = "https:" + img_src
                                elif img_src.startswith("/"):
                                    target_avatar = domain + img_src
                                else:
                                    target_avatar = img_src
                                logger.info(f"JavBus 找到匹配演员 {sname}: {target_avatar}")
                                return target_avatar

                        if star_items:
                            first_item = star_items[0]
                            imgs = first_item.xpath('.//img/@src')
                            if imgs:
                                img_src = imgs[0]
                                if img_src.startswith("//"):
                                    target_avatar = "https:" + img_src
                                elif img_src.startswith("/"):
                                    target_avatar = domain + img_src
                                else:
                                    target_avatar = img_src
                                logger.info(f"JavBus 取第一个候选结果: {target_avatar}")
                                return target_avatar

                logger.debug(f"演员 {name}({name_jp}) 在所有 JavBus 域名上都未找到头像")
                return None

        except Exception as e:
            logger.error(f"JavBus 搜索演员 {name} 失败: {e}")
            return None

    async def _fetch_with_cloudscraper(self, url: str) -> Optional[str]:
        """使用 cloudscraper 绕过 Cloudflare 反爬"""
        try:
            import cloudscraper

            # 获取代理配置
            from app.config.manager import get_config
            from app.services.proxy_manager import get_effective_proxy_url
            proxy_url = get_effective_proxy_url()
            logger.debug(f"使用代理: {proxy_url}")

            if not self._cloudscraper:
                # 创建带代理的 cloudscraper
                self._cloudscraper = cloudscraper.create_scraper()
                if proxy_url:
                    # 设置代理
                    self._cloudscraper.proxies = {
                        "http": proxy_url,
                        "https": proxy_url,
                    }

            response = self._cloudscraper.get(url)
            if response.status_code == 200:
                return response.text
            return None
        except ImportError:
            logger.debug("cloudscraper 未安装")
            return None
        except Exception as e:
            logger.debug(f"cloudscraper 请求失败: {e}")
            return None

    async def _download_avatar(
        self, actor_id: int, url: str, actor_name: str = ""
    ) -> Optional[Path]:
        """下载头像到本地（可选人脸裁剪）"""
        from app.config.manager import get_config_manager

        manager = get_config_manager()
        avatar_dir = manager.computed.data_dir / "avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)

        raw_path = avatar_dir / f"actor_{actor_id}_raw.jpg"
        output_path = avatar_dir / f"actor_{actor_id}.jpg"

        async with AsyncHttpClient() as client:
            try:
                # 提取域名用于 Referer
                match = re.match(r'https?://([^/]+)', url)
                referer_domain = f"https://{match.group(1)}" if match else "https://www.javbus.com"

                headers = {
                    "Referer": f"{referer_domain}/",
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
                logger.info(f"下载头像 {actor_id} ({actor_name}): {url}")
                content = await client.get_bytes(url, headers=headers)
                if content and len(content) > 500:
                    # 保存原始图片
                    with open(raw_path, "wb") as f:
                        f.write(content)
                    logger.debug(f"原始头像已保存: {raw_path} ({len(content)} bytes)")

                    # 尝试人脸裁剪
                    cropped = False
                    try:
                        from app.utils.face_crop import FaceCropper, AVATAR_SIZE
                        cropper = FaceCropper()
                        result = cropper.crop_face(
                            str(raw_path), str(output_path), target_size=AVATAR_SIZE
                        )
                        if result:
                            logger.info(f"人脸裁剪完成: {output_path}")
                            cropped = True
                            # 裁剪成功后清理原图
                            if raw_path.exists():
                                raw_path.unlink()
                    except Exception as e:
                        logger.debug(f"人脸裁剪失败，使用原图: {e}")

                    if not cropped:
                        # 不使用裁剪，直接使用原图作为头像
                        raw_path.rename(output_path)
                        logger.info(f"头像下载成功（无裁剪）: {output_path} ({len(content)} bytes)")

                    return output_path.resolve()
                else:
                    logger.warning(f"头像太小或为占位图: {url} ({len(content) if content else 0} bytes)")
                    return None
            except Exception as e:
                logger.error(f"下载头像失败 {url}: {e}")
                return None

    async def _import_local_avatar(self, actor: Actor, src_path: Path) -> bool:
        """将本地资料库的头像文件复制到演员头像目录（DATA/avatars/actor_{id}.jpg）"""
        try:
            avatar_dir = (get_config_manager().computed.data_dir / "avatars").resolve()
            avatar_dir.mkdir(parents=True, exist_ok=True)
            output_path = avatar_dir / f"actor_{actor.id}.jpg"
            shutil.copy2(src_path, output_path)

            async with self.db.session() as session:
                db_actor = await session.get(Actor, actor.id)
                if db_actor:
                    # 存绝对路径, 避免相对 "data/avatars/..." 依赖 server 启动目录,
                    # 也确保 actor_needs_avatar 的 is_absolute() 分支能正确判定"已有头像"
                    db_actor.avatar_url = str(output_path.resolve())
                    await session.commit()

            logger.info(f"演员 {actor.name} 头像已从本地资料库导入: {output_path}")
            return True
        except Exception as e:
            logger.error(f"导入本地头像失败 {actor.name}: {e}")
            return False

    def cancel(self):
        """取消刮削"""
        self._progress["status"] = "cancelled"


# ===== 全局任务管理 =====

_active_avatar_jobs: dict[str, dict] = {}


async def run_avatar_scrape_job(job_id: str, db: Database, min_movies: int = 2, use_local_library: bool = False):
    """运行头像刮削后台任务"""
    scraper = ActorAvatarScraper(db=db, min_movies=min_movies, use_local_library=use_local_library)
    _active_avatar_jobs[job_id] = {
        "scraper": scraper,
        "started_at": datetime.now(),
    }

    try:
        result = await scraper.scrape_all()
        _active_avatar_jobs[job_id]["result"] = result
        _active_avatar_jobs[job_id]["finished_at"] = datetime.now()
    except Exception as e:
        logger.error(f"头像刮削任务 {job_id} 失败: {e}")
        _active_avatar_jobs[job_id]["error"] = str(e)
        _active_avatar_jobs[job_id]["finished_at"] = datetime.now()


def get_avatar_job_status(job_id: str) -> Optional[dict]:
    """获取头像刮削任务状态"""
    job = _active_avatar_jobs.get(job_id)
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


def cancel_avatar_job(job_id: str) -> bool:
    """取消头像刮削任务"""
    job = _active_avatar_jobs.get(job_id)
    if not job:
        return False
    scraper = job.get("scraper")
    if scraper:
        scraper.cancel()
    return True
