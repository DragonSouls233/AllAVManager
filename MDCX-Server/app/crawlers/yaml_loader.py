"""YAML 声明式刮削插件系统

参考 yamdc (YAML Plugin Bundle) + stash (Scraper Plugin) 的设计：
- YAML 配置文件定义刮削规则（搜索/详情/字段提取）
- 支持 CSS Selector / XPath / JSONPath 三种提取模式
- 支持单步（one-step）和两步（two-step）刮削流程
- 链式执行多 scraper，结果合并

添加新站点只需新建 YAML 文件，无需写 Python 代码。
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from app.crawlers.base import BaseCrawler, ScrapeResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class YAMLScraperPlugin:
    """单个 YAML 刮削插件"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.display_name = config.get("display_name", name)
        self.base_url = config.get("base_url", "")
        self.scrape_type = config.get("type", "one-step")  # one-step / two-step
        self.supported_types = config.get("supported_types", [])
        self.priority = config.get("priority", 50)

        search_cfg = config.get("search", {})
        detail_cfg = config.get("detail", {})

        self.search_url = search_cfg.get("url", "")
        self.search_method = search_cfg.get("method", "GET")
        self.search_headers = search_cfg.get("headers", {})
        self.search_result_selector = search_cfg.get("result_selector", "")
        self.search_code_selector = search_cfg.get("code_selector", "")

        self.detail_url = detail_cfg.get("url", "")
        self.detail_method = detail_cfg.get("method", "GET")
        self.detail_headers = detail_cfg.get("headers", {})
        self.fields = detail_cfg.get("fields", {})

        self._validated = False

    def validate(self) -> bool:
        """验证配置完整性"""
        if not self.name:
            logger.error(f"YAML 插件缺少 name: {self.config}")
            return False
        if self.scrape_type == "one-step" and not self.detail_url and not self.search_url:
            logger.error(f"YAML 插件 [{self.name}] 缺少 url 配置")
            return False
        if not self.fields:
            logger.error(f"YAML 插件 [{self.name}] 缺少 fields 配置")
            return False
        self._validated = True
        return True

    def _render_url(self, template: str, variables: dict) -> str:
        """渲染 URL 模板（替换 {variable} 占位符）"""
        def replacer(match):
            key = match.group(1)
            return str(variables.get(key, match.group(0)))
        return re.sub(r"\{(\w+)\}", replacer, template)

    async def search(self, keyword: str) -> list[dict]:
        """搜索

        返回候选列表：[{"code": "...", "url": "...", "title": "..."}]
        """
        if not self.search_url:
            return [{"code": keyword, "url": self._render_url(self.detail_url, {"code": keyword}), "title": keyword}]

        url = self._render_url(self.search_url, {"keyword": keyword})
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.request(self.search_method, url, headers=self.search_headers)
                resp.raise_for_status()

            return self._parse_search_results(resp.text)

        except Exception as e:
            logger.warning(f"YAML 插件 [{self.name}] 搜索失败 [{keyword}]: {e}")
            return [{"code": keyword, "url": self._render_url(self.detail_url, {"code": keyword}), "title": keyword}]

    def _parse_search_results(self, html: str) -> list[dict]:
        """解析搜索结果 HTML"""
        try:
            from parsel import Selector
            sel = Selector(text=html)
            results = []

            items = sel.css(self.search_result_selector) if self.search_result_selector else []
            for item in items:
                code = ""
                if self.search_code_selector:
                    code = item.css(self.search_code_selector).get("") or ""

                url = item.css("::attr(href)").get("") or ""
                title = item.css("::text").get("") or ""

                results.append({
                    "code": code.strip(),
                    "url": url.strip(),
                    "title": title.strip(),
                })

            return results if results else []

        except ImportError:
            logger.warning("缺少 parsel 库，无法解析搜索 HTML")
            return []
        except Exception as e:
            logger.debug(f"搜索 HTML 解析失败: {e}")
            return []

    async def scrape(self, url: str) -> Optional[ScrapeResult]:
        """刮削详情页"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.request(self.detail_method, url, headers=self.detail_headers)
                resp.raise_for_status()

            return self._parse_detail(resp.text, url)

        except Exception as e:
            logger.warning(f"YAML 插件 [{self.name}] 刮削失败 [{url}]: {e}")
            return None

    def _parse_detail(self, html: str, source_url: str) -> Optional[ScrapeResult]:
        """解析详情页 HTML / JSON"""
        content_type = self.config.get("detail", {}).get("format", "html")

        if content_type == "json":
            return self._parse_json_detail(html, source_url)
        return self._parse_html_detail(html, source_url)

    def _parse_html_detail(self, html: str, source_url: str) -> Optional[ScrapeResult]:
        """解析 HTML 详情页"""
        try:
            from parsel import Selector
        except ImportError:
            logger.warning("缺少 parsel 库")
            return None

        sel = Selector(text=html)
        data = {}

        for field_name, field_cfg in self.fields.items():
            selector = field_cfg.get("selector", "")
            attr = field_cfg.get("attribute", "text")
            multiple = field_cfg.get("multiple", False)
            transform = field_cfg.get("transform", "")

            try:
                if multiple:
                    if attr == "text":
                        values = sel.css(selector).getall()
                    else:
                        values = sel.css(f"{selector}::attr({attr})").getall()
                    values = [v.strip() for v in values if v and v.strip()]
                    data[field_name] = values
                else:
                    if attr == "text":
                        value = sel.css(selector).get("") or ""
                    else:
                        value = sel.css(f"{selector}::attr({attr})").get("") or ""
                    data[field_name] = value.strip()
            except Exception:
                data[field_name] = "" if not multiple else []

        return self._build_result(data, source_url)

    def _parse_json_detail(self, text: str, source_url: str) -> Optional[ScrapeResult]:
        """解析 JSON 响应"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"YAML 插件 [{self.name}] JSON 解析失败")
            return None

        result_data = {}
        for field_name, field_cfg in self.fields.items():
            path = field_cfg.get("jsonpath", "")
            multiple = field_cfg.get("multiple", False)

            try:
                value = self._resolve_jsonpath(data, path)
                if multiple:
                    result_data[field_name] = value if isinstance(value, list) else [value] if value else []
                else:
                    result_data[field_name] = str(value) if value is not None else ""
            except Exception:
                result_data[field_name] = "" if not multiple else []

        return self._build_result(result_data, source_url)

    def _resolve_jsonpath(self, data: Any, path: str) -> Any:
        """简单的 JSON 路径解析（支持点号分隔）"""
        if not path:
            return data
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx] if idx < len(current) else None
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def _build_result(self, data: dict, source_url: str) -> Optional[ScrapeResult]:
        """构建 ScrapeResult"""
        code = data.get("code", "") or data.get("number", "")
        title = data.get("title", "") or data.get("name", "")
        if not title:
            logger.warning(f"YAML 插件 [{self.name}] 未提取到标题")
            return None

        from app.crawlers.base import ScrapeResult, ActorInfo

        actors_list = data.get("actors", []) or data.get("actress", []) or data.get("performers", [])
        if isinstance(actors_list, str):
            actors_list = [actors_list]

        return ScrapeResult(
            code=code,
            title=title,
            original_title=data.get("original_title", ""),
            studio=data.get("studio", ""),
            maker=data.get("maker", ""),
            series=data.get("series", ""),
            release_date=str(data.get("release_date", "")),
            duration=data.get("duration"),
            plot=data.get("plot", "") or data.get("description", ""),
            cover_url=data.get("cover", "") or data.get("cover_url", ""),
            poster_url=data.get("poster", "") or data.get("poster_url", ""),
            rating=data.get("rating"),
            source=self.name,
            source_url=source_url,
            genres=data.get("genres", []) or data.get("tags", []),
            actors=[ActorInfo(name=a) if isinstance(a, str) else ActorInfo(name=a.get("name", "")) for a in actors_list] if actors_list else [],
            is_uncensored=data.get("is_uncensored", False),
            is_chinese=data.get("is_chinese", False),
            is_mosaic=data.get("is_mosaic", True),
            sample_images=data.get("sample_images", []) or data.get("screenshots", []),
            trailer_url=data.get("trailer_url", ""),
        )


class YAMLLoader:
    """YAML 刮削插件加载器

    扫描指定目录加载所有 *.yaml 刮削配置。
    """

    def __init__(self, scan_dirs: Optional[list[str]] = None):
        self._plugins: dict[str, YAMLScraperPlugin] = {}
        self._scan_dirs = scan_dirs or []

    def add_scan_dir(self, directory: str) -> None:
        if directory not in self._scan_dirs:
            self._scan_dirs.append(directory)

    def load_all(self) -> int:
        """加载所有 YAML 插件"""
        total = 0
        for scan_dir in self._scan_dirs:
            count = self._load_from_dir(scan_dir)
            total += count
            logger.info(f"YAML 加载器: 从 {scan_dir} 加载了 {count} 个插件")
        return total

    def _load_from_dir(self, directory: str) -> int:
        """从单个目录加载"""
        path = Path(directory)
        if not path.is_dir():
            logger.warning(f"YAML 扫描目录不存在: {directory}")
            return 0

        count = 0
        for yaml_file in path.glob("*.yaml"):
            name = yaml_file.stem
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)

                if not config or not isinstance(config, dict):
                    logger.warning(f"YAML 文件格式无效: {yaml_file}")
                    continue

                plugin = YAMLScraperPlugin(name, config)
                if plugin.validate():
                    self._plugins[name] = plugin
                    count += 1
                else:
                    logger.warning(f"YAML 插件验证失败: {yaml_file}")

            except yaml.YAMLError as e:
                logger.warning(f"YAML 解析失败 [{yaml_file}]: {e}")
            except Exception as e:
                logger.warning(f"YAML 加载失败 [{yaml_file}]: {e}")

        return count

    def get_plugin(self, name: str) -> Optional[YAMLScraperPlugin]:
        return self._plugins.get(name)

    def get_all_plugins(self) -> dict[str, YAMLScraperPlugin]:
        return dict(self._plugins)

    def get_plugins_by_type(self, module_type: str) -> list[YAMLScraperPlugin]:
        return [p for p in self._plugins.values() if module_type in p.supported_types]

    def reload(self) -> int:
        """重新加载所有插件"""
        self._plugins.clear()
        return self.load_all()


# 全局单例
_loader_instance: Optional[YAMLLoader] = None


def get_yaml_loader() -> YAMLLoader:
    """获取全局 YAML 加载器"""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = YAMLLoader()
        # 默认扫描目录
        cfg = None
        try:
            from app.config.manager import get_config
            cfg = get_config()
        except Exception:
            pass
        if cfg and hasattr(cfg, "scrapers") and hasattr(cfg.scrapers, "yaml_dir"):
            _loader_instance.add_scan_dir(cfg.scrapers.yaml_dir)
        else:
            _loader_instance.add_scan_dir(os.path.join(os.path.dirname(__file__), "yaml_configs"))
    return _loader_instance


async def scrape_with_yaml(code: str, module_type: str = "jav") -> Optional[ScrapeResult]:
    """便捷函数：使用 YAML 插件刮削"""
    loader = get_yaml_loader()
    plugins = loader.get_plugins_by_type(module_type)
    if not plugins:
        return None

    # 按优先级排序
    plugins.sort(key=lambda p: p.priority, reverse=True)

    result = None
    for plugin in plugins:
        candidates = await plugin.search(code)
        if not candidates:
            continue

        for candidate in candidates:
            url = candidate.get("url", "")
            if not url:
                continue
            r = await plugin.scrape(url)
            if r:
                if result is None:
                    result = r
                else:
                    # 合并：用高优先级插件的字段填充低优先级插件的空字段
                    for field in ["title", "cover_url", "plot", "studio", "series", "release_date"]:
                        if not getattr(result, field) and getattr(r, field):
                            setattr(result, field, getattr(r, field))
                break

    return result


__all__ = [
    "YAMLScraperPlugin",
    "YAMLLoader",
    "get_yaml_loader",
    "scrape_with_yaml",
]
