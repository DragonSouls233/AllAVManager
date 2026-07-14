"""
通用多域名切换器 (DomainSwitcher)

参考来源:
- P1: PornSimilarityPlatform/modules/madouqu/core/crawler.py (MadouquCrawler.find_working_url)
- P1: PSP 麻豆 5 个备用域名的循环测试逻辑

整合说明:
- 业务逻辑: 100% 复用 P1 麻豆的 find_working_url / test_url
- HTTP 客户端: 切换为 MDCX AsyncHttpClient + 强制内置代理
- 持久化: 缓存当前可用域名到本地文件 (data/domain_cache.json)
- 异步化: 全部 async/await

使用方式:
  switcher = DomainSwitcher(["https://a.com", "https://b.com"], name="madouqu")
  await switcher.test_all()           # 测试所有域名
  url = await switcher.get_working()   # 获取可用域名
  await switcher.test_and_cache()     # 测试并缓存
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.services.proxy_manager import get_proxy
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

CACHE_FILE = Path(__file__).parent.parent / "data" / "domain_cache.json"


@dataclass
class DomainStatus:
    """域名状态"""
    url: str
    available: bool = False
    last_check: float = 0.0
    response_time: float = 0.0
    status_code: int = 0
    error: Optional[str] = None


@dataclass
class DomainSwitcherConfig:
    """域名切换器配置"""
    timeout: int = 10
    max_retries: int = 2
    retry_delay: float = 1.0
    use_proxy: bool = True
    cache_ttl: int = 3600  # 缓存有效期（秒）


class DomainSwitcher:
    """通用多域名切换器

    对一组候选域名进行健康检查 + 持久化缓存 + 异步切换。
    适用场景：麻豆、海角、PORNHub 等存在多镜像的站点。

    流程:
      1. 启动时从磁盘缓存读取上次可用域名
      2. 命中缓存且未过期 → 直接使用
      3. 未命中 / 已过期 → 依次测试所有域名
      4. 第一个可用域名被选中，更新缓存
      5. 全部失败 → 返回 None

    所有测试请求通过 MDCX 内置代理。
    """

    def __init__(
        self,
        candidate_urls: list[str],
        name: str = "default",
        config: Optional[DomainSwitcherConfig] = None,
    ):
        self.name = name
        self.candidate_urls = [u.rstrip("/") for u in candidate_urls]
        self.config = config or DomainSwitcherConfig()
        self._status_map: dict[str, DomainStatus] = {}
        self._current: Optional[str] = None
        self._load_cache()

    def _load_cache(self) -> None:
        """从磁盘加载缓存"""
        if not CACHE_FILE.exists():
            return
        try:
            with CACHE_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            entry = data.get(self.name)
            if entry:
                ts = entry.get("timestamp", 0)
                if time.time() - ts < self.config.cache_ttl:
                    self._current = entry.get("url")
                    logger.debug(f"[{self.name}] 从缓存加载可用域名: {self._current}")
        except Exception as e:
            logger.debug(f"[{self.name}] 缓存加载失败: {e}")

    def _save_cache(self) -> None:
        """保存当前可用域名到磁盘"""
        if not self._current:
            return
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if CACHE_FILE.exists():
                try:
                    with CACHE_FILE.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data[self.name] = {"url": self._current, "timestamp": time.time()}
            with CACHE_FILE.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[{self.name}] 缓存保存失败: {e}")

    async def test_url(self, url: str) -> DomainStatus:
        """测试单个 URL 可用性"""
        status = DomainStatus(url=url)
        proxy = get_proxy() if self.config.use_proxy else None

        async with AsyncHttpClient(proxy=proxy, timeout=self.config.timeout) as client:
            start = time.time()
            try:
                resp = await client.get(url, allow_redirects=True)
                if resp is not None:
                    status.status_code = getattr(resp, "status_code", 0)
                    status.available = 200 <= status.status_code < 400
                else:
                    status.available = False
            except Exception as e:
                status.error = str(e)[:120]
                status.available = False
            status.response_time = time.time() - start
        status.last_check = time.time()
        return status

    async def test_all(self) -> list[DomainStatus]:
        """测试所有候选域名（并发）"""
        tasks = [self.test_url(u) for u in self.candidate_urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for s in results:
            self._status_map[s.url] = s
        return results

    async def get_working(self) -> Optional[str]:
        """获取可用域名（按候选顺序）"""
        # 优先使用缓存
        if self._current and self._current in self.candidate_urls:
            return self._current

        # 重新测试
        statuses = await self.test_all()
        for s in statuses:
            if s.available:
                self._current = s.url
                self._save_cache()
                logger.info(f"[{self.name}] 找到可用域名: {s.url} (响应: {s.response_time:.2f}s)")
                return s.url
        logger.error(f"[{self.name}] 所有域名都不可用: {[s.url for s in statuses]}")
        return None

    async def test_and_cache(self) -> Optional[str]:
        """测试并缓存（get_working 的语义化别名）"""
        return await self.get_working()

    @property
    def current(self) -> Optional[str]:
        return self._current

    def get_status_report(self) -> dict:
        """获取测试报告"""
        return {
            "name": self.name,
            "current": self._current,
            "candidates": [
                {
                    "url": s.url,
                    "available": s.available,
                    "response_time": round(s.response_time, 3),
                    "status_code": s.status_code,
                    "error": s.error,
                }
                for s in self._status_map.values()
            ],
        }


# 便捷工厂
def make_madouqu_switcher() -> DomainSwitcher:
    """麻豆专用切换器（5 个备用域名）"""
    return DomainSwitcher(
        name="madouqu",
        candidate_urls=[
            "https://madouqu.sbs",
            "https://madouqu.club",
            "https://madouqu.cc",
            "https://madouqu.net",
            "https://madouqu.org",
        ],
    )


def make_haijiao_switcher() -> DomainSwitcher:
    """海角专用切换器"""
    return DomainSwitcher(
        name="haijiao",
        candidate_urls=[
            "https://haijiao.com",
            "https://www.haijiao.com",
        ],
    )


def make_javdb_switcher() -> DomainSwitcher:
    """JAVDB 专用切换器（多镜像）"""
    return DomainSwitcher(
        name="javdb",
        candidate_urls=[
            "https://javdb.com",
            "https://javdb36.com",
            "https://javdb.org",
        ],
    )
