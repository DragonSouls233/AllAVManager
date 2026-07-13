"""
API 路由
"""

from app.api.routes import auth, health, config, files, movies, tasks, patch, actors, crawlers, stats, import_, logs, compare

__all__ = ["auth", "health", "config", "files", "movies", "tasks", "patch", "actors", "crawlers", "stats", "import_", "logs", "compare"]
