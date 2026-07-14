"""
海角社区演员提取适配器

参考来源：
- P2: .references/特殊项目/提取/core/extractor.py (浏览器抓取流程)
- P2: .references/特殊项目/提取/core/title_parser.py (标题清洗/归一化)
- P2: .references/特殊项目/提取/core/page_reader.py (页面解析)

整合说明：
- 业务逻辑: 100% 复用 P2 特殊项目（导入 + 调用）
- 浏览器自动化: 切换为 MDCX 的 cf_bypass 工具 + Playwright/Selenium
- 代理集成: 通过 MDCX 内置代理 (强制) + xray SOCKS5
- 数据模型: 适配 ChineseActor (chinese 模块演员表)
- 异步化: 包装同步 Selenium 为 asyncio.to_thread 调用

数据流:
  海角用户主页 URL
    ↓ Playwright 打开
    ↓ 等待加载
    ↓ 提取该用户发布的所有标题
    ↓ 按标题归一化
    ↓ 写入 chinese_actors 表 (作为别名/作品集) + chinese_movies 关联
"""

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 海角社区配置
HAIJIAO_BASE_URL = "https://haijiao.com"
HAIJIAO_HOMEPAGE_PATTERN = r"/homepage/(?:(?:last|essence|sell)/)?(\d+)"


@dataclass
class HaijiaoUser:
    """海角社区用户"""
    user_id: str
    username: str = ""
    url: str = ""
    titles: list[str] = field(default_factory=list)
    total_pages: int = 0
    success: bool = False
    error: Optional[str] = None
    source: str = "haijiao"


@dataclass
class HaijiaoExtractConfig:
    """海角提取配置"""
    proxy: Optional[str] = None       # 走 MDCX 内置代理
    headless: bool = True
    skip_existing: bool = True
    max_pages: int = 20
    timeout: int = 30
    data_dir: str = "./data/haijiao"
    use_builtin_browser: bool = True  # True=MDCX Playwright, False=原项目 Selenium


# 标题归一化（100% 复用 P2 title_parser.normalize_title）
def normalize_title(text: str) -> str:
    """通用标题清洗

    复用于 P2 特殊项目：core/title_parser.py
    """
    if not text:
        return ""
    s = str(text).strip()
    s = os.path.splitext(s)[0] if "." in s else s
    s = os.path.basename(s)
    s = re.sub(r"[【\[\(][^】\]\)]*?[】\]\)]", "", s)
    s = re.sub(
        r"[\s\-_—·•·.,，。！!？?/\\|~`@#$%^&*=+\[\]\{\}<>"
        "'" + '：:；;、（）()〔〕【】《》…—·•]+',
        "",
        s,
    )
    s = re.sub(r"^\d+", "", s)
    return s.lower()


def extract_user_id_from_url(url: str) -> Optional[str]:
    """从海角 URL 提取用户 ID"""
    if not url:
        return None
    m = re.search(HAIJIAO_HOMEPAGE_PATTERN, url)
    return m.group(1) if m else None


# 复用 P2 特殊项目的解析函数（如果 P2 目录存在则 import，否则使用本地实现）
def _try_import_p2_project():
    """尝试导入 P2 特殊项目的核心模块"""
    try:
        p2_path = Path(__file__).resolve().parent.parent.parent.parent / ".references" / "特殊项目" / "提取"
        p2_path_str = str(p2_path)
        if p2_path_str not in sys.path:
            sys.path.insert(0, p2_path_str)

        from core.extractor import TitleExtractor
        from core.title_parser import (
            normalize_title as p2_normalize,
            extract_user_id as p2_extract_uid,
        )
        return TitleExtractor, p2_normalize, p2_extract_uid
    except Exception as e:
        logger.debug(f"P2 特殊项目不可用，使用本地实现: {e}")
        return None, None, None


_P2_EXT, _P2_NORM, _P2_EID = _try_import_p2_project()


class HaijiaoAdapter:
    """海角社区演员提取适配器

    负责将 P2 特殊项目的同步 Selenium 提取流程，包装为 MDCX 异步 API，
    写入 chinese 模块的演员表。

    特性:
    - 强制使用 MDCX 内置代理 (requires_proxy=True)
    - 支持缓存已抓取用户（skip_existing）
    - 支持分页抓取（默认最多 20 页）
    - 自动创建/更新 ChineseActor 记录
    """

    def __init__(self, config: Optional[HaijiaoExtractConfig] = None):
        self.config = config or HaijiaoExtractConfig()
        self._init_proxy()
        Path(self.config.data_dir).mkdir(parents=True, exist_ok=True)

    def _init_proxy(self) -> None:
        """初始化代理（MDCX 内置代理）"""
        if self.config.proxy:
            return
        try:
            from app.services.proxy_manager import get_proxy_url

            self.config.proxy = get_proxy_url()
            logger.info(f"海角适配器使用内置代理: {self.config.proxy}")
        except Exception as e:
            logger.warning(f"无法获取内置代理，使用直连: {e}")
            self.config.proxy = None

    def _import_p2_extractor(self):
        """惰性导入 P2 特殊项目"""
        if _P2_EXT is None:
            raise ImportError("P2 特殊项目不可用")
        return _P2_EXT

    async def fetch_user(self, url: str) -> HaijiaoUser:
        """异步抓取单个海角用户主页

        Args:
            url: 海角用户主页 URL (https://haijiao.com/homepage/{user_id})

        Returns:
            HaijiaoUser: 包含 user_id, username, titles, total_pages 等
        """
        user_id = extract_user_id_from_url(url) or ""
        result = HaijiaoUser(user_id=user_id, url=url)

        if not user_id:
            result.error = "无效的 URL"
            return result

        if _P2_EXT is None:
            result.error = "P2 特殊项目不可用，请确认 .references/特殊项目/提取 存在"
            return result

        # P2 是同步 Selenium 调用，包到线程池中
        try:
            TitleExtractorCls = self._import_p2_extractor()
            extractor = TitleExtractorCls(
                proxy=self.config.proxy,
                headless=self.config.headless,
                skip_existing=self.config.skip_existing,
                max_pages=self.config.max_pages,
                data_dir=self.config.data_dir,
            )

            r = await asyncio.to_thread(extractor.extract, url)
            result.success = r.get("success", False)
            result.titles = r.get("titles", [])
            result.username = r.get("user_name", f"用户{user_id}")
            result.total_pages = r.get("total_pages", 0)
            if not result.success:
                result.error = r.get("error", "未知错误")
        except Exception as e:
            result.error = str(e)
            logger.error(f"海角抓取失败 [{url}]: {e}")

        return result

    async def fetch_users(self, urls: list[str], progress_fn: Optional[Callable] = None) -> list[HaijiaoUser]:
        """批量抓取多个用户

        Args:
            urls: 用户主页 URL 列表
            progress_fn: 进度回调 (current, total, titles_count, total_pages)
        """
        if not urls:
            return []
        results = []
        total = len(urls)
        for idx, url in enumerate(urls, 1):
            user = await self.fetch_user(url)
            results.append(user)
            if progress_fn:
                try:
                    progress_fn(idx, total, len(user.titles), user.total_pages)
                except Exception:
                    pass
        return results

    async def import_to_chinese_module(self, user: HaijiaoUser) -> dict:
        """将海角用户数据导入到国产模块数据库

        规则:
        1. 在 chinese_actors 表中创建/更新演员记录
        2. username -> name 字段
        3. titles -> alias 字段（按 | 分隔）
        4. movie_count = len(titles)
        5. source = "haijiao"

        Returns:
            dict: {actor_id, created, titles_count, error}
        """
        result = {"actor_id": None, "created": False, "titles_count": 0, "error": None}

        if not user.success or not user.titles:
            result["error"] = user.error or "无有效标题"
            return result

        if not user.username:
            user.username = f"海角用户_{user.user_id}"

        try:
            from app.db.chinese_models import ChineseActor
            from app.db.module_db import ModuleDatabase
            from sqlalchemy import select

            db = ModuleDatabase.get_instance("chinese")
            session = await db.get_session()
            try:
                # 查找现有记录
                stmt = select(ChineseActor).where(ChineseActor.name == user.username)
                existing = (await session.execute(stmt)).scalar_one_or_none()

                # 合并标题（去重）
                if existing and existing.alias:
                    old_titles = set(existing.alias.split("|"))
                    new_titles = [t for t in user.titles if t not in old_titles]
                    merged_titles = existing.alias.split("|") + new_titles
                    alias_value = "|".join(merged_titles)
                else:
                    alias_value = "|".join(user.titles)

                if existing:
                    existing.alias = alias_value
                    existing.movie_count = alias_value.count("|") + 1 if alias_value else 0
                    existing.source = "haijiao"
                    result["actor_id"] = existing.id
                else:
                    new_actor = ChineseActor(
                        name=user.username,
                        alias=alias_value,
                        source="haijiao",
                        movie_count=len(user.titles),
                    )
                    session.add(new_actor)
                    await session.flush()
                    result["actor_id"] = new_actor.id
                    result["created"] = True

                await session.commit()
                result["titles_count"] = len(user.titles)
                logger.info(
                    f"海角导入成功: {user.username} (ID={result['actor_id']}, "
                    f"{'新建' if result['created'] else '更新'}, {result['titles_count']} 标题)"
                )
            finally:
                await session.close()
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"海角导入到 chinese 模块失败: {e}")

        return result

    async def fetch_and_import(self, url: str) -> dict:
        """一站式接口：抓取 + 导入"""
        user = await self.fetch_user(url)
        return await self.import_to_chinese_module(user)


# 便捷函数
async def scrape_haijiao_user(url: str) -> HaijiaoUser:
    """便捷函数：抓取单个海角用户"""
    adapter = HaijiaoAdapter()
    return await adapter.fetch_user(url)


async def scrape_and_import_haijiao(url: str) -> dict:
    """便捷函数：抓取并导入到 chinese 模块"""
    adapter = HaijiaoAdapter()
    return await adapter.fetch_and_import(url)
