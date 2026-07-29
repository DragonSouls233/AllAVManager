"""
国产模块爬虫
"""
from app.crawlers.chinese import madou
from app.crawlers.chinese import aggregate
import importlib
_91porn = importlib.import_module("app.crawlers.chinese.91porn")
_haijiao = importlib.import_module("app.crawlers.chinese.haijiao")

__all__ = ["madou", "aggregate", "91porn", "haijiao"]
