"""
FastAPI 应用入口
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response

from app.config.manager import get_config, get_config_manager, CONFIG_FILE
from app.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 自动整理定时任务调度器（在 lifespan 中初始化，关闭时停止）
_auto_organize_scheduler = None

# 配置监视：记录上一次生效的媒体目录与 config.yaml 修改时间
_last_applied_media_dirs: list[str] = []
_config_mtime: float | None = None


async def _watch_config_and_rescan(poll_interval: int = 5) -> None:
    """监视 config.yaml：一旦 media_dirs 变化（GUI 工具保存），自动重新扫描导入。

    这样在 GUI 工具里绑定/修改媒体目录后无需重启服务端即可生效。
    """
    global _last_applied_media_dirs, _config_mtime
    from app.api.routes.import_ import auto_scan_media_dirs

    # 初始化已生效的媒体目录
    try:
        _last_applied_media_dirs = list(get_config().scraper.media_dirs or [])
    except Exception:
        _last_applied_media_dirs = []

    if CONFIG_FILE.exists():
        try:
            _config_mtime = CONFIG_FILE.stat().st_mtime
        except OSError:
            _config_mtime = None

    logger.info(f"配置监视器已启动，监视文件: {CONFIG_FILE}")

    while True:
        await asyncio.sleep(poll_interval)
        try:
            if not CONFIG_FILE.exists():
                continue
            mtime = CONFIG_FILE.stat().st_mtime
            if _config_mtime is not None and mtime == _config_mtime:
                continue  # 无变化

            _config_mtime = mtime
            # 重新从磁盘加载配置（含 media_dirs 最新值）
            get_config_manager().load()
            new_dirs = list(get_config().scraper.media_dirs or [])

            if new_dirs == _last_applied_media_dirs:
                logger.info("config.yaml 变化，但 media_dirs 未变动，忽略")
                continue

            added = [d for d in new_dirs if d not in _last_applied_media_dirs]
            removed = [d for d in _last_applied_media_dirs if d not in new_dirs]
            _last_applied_media_dirs = new_dirs
            logger.info(
                f"检测到 media_dirs 变更（新增 {len(added)} / 移除 {len(removed)}），"
                f"自动重新扫描导入"
            )

            # 更新目录监听器
            try:
                from app.services.watcher import get_directory_watcher
                get_directory_watcher().start(new_dirs)
            except Exception as e:
                logger.warning(f"更新目录监听器失败: {e}")

            # 触发自动递归扫描导入
            if new_dirs:
                asyncio.create_task(
                    auto_scan_media_dirs(new_dirs, recursive=True, conflict_strategy="skip")
                )
        except Exception as e:
            logger.error(f"配置监视器异常: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 全局声明必须在函数开头(在 startup/shutdown 中都会用到)
    global _auto_organize_scheduler

    # 启动时
    config = get_config()
    manager = get_config_manager()

    # 设置日志
    log_file = None
    if config.log.file_enabled:
        log_file = manager.computed.logs_dir / "app.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

    setup_logging(
        level=config.log.level,
        log_format=config.log.format,
        log_file=log_file,
        console=config.log.console_enabled,
    )

    logger.info(f"启动 {config.app_name}")
    logger.info(f"监听 {config.server.host}:{config.server.port}")
    logger.info(f"配置文件: {CONFIG_FILE}  (存在={CONFIG_FILE.exists()})")
    logger.info(f"已加载媒体目录 media_dirs: {config.scraper.media_dirs or []}")

    # 初始化数据库
    from app.db.database import init_database
    await init_database()
    logger.info("数据库初始化完成")

    # 执行数据库迁移
    try:
        from app.db.migrations import run_migrations
        applied = await run_migrations()
        if applied:
            logger.info(f"数据库迁移完成: {', '.join(applied)}")
        else:
            logger.info("数据库已是最新版本")
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")

    # 启动定时任务调度器
    try:
        from app.tasks.scheduled import get_scheduled_task_manager
        scheduler = get_scheduled_task_manager()
        scheduler.start()
        logger.info("定时任务调度器已启动")
    except Exception as e:
        logger.warning(f"定时任务调度器启动失败: {e}")

    # 启动目录实时监听
    media_dirs = config.scraper.media_dirs or []
    try:
        from app.services.watcher import get_directory_watcher
        watcher = get_directory_watcher()
        watcher.start(media_dirs)
    except Exception as e:
        logger.warning(f"目录监听启动失败: {e}")

    # 启动后自动递归扫描已绑定的媒体目录（导入番号/演员，无需手动触发）
    if media_dirs:
        try:
            from app.api.routes.import_ import auto_scan_media_dirs
            asyncio.create_task(
                auto_scan_media_dirs(media_dirs, recursive=True, conflict_strategy="skip")
            )
            logger.info(f"已对 {len(media_dirs)} 个媒体目录发起自动递归扫描导入")
        except Exception as e:
            logger.warning(f"自动扫描媒体目录失败: {e}")

    # 启动后一次性回填历史影片封面（修复旧导入中 cover_url 为空导致的封面缺失）
    # 放在后台任务，不阻塞启动；限量避免一次性处理过多
    try:
        async def _startup_backfill():
            try:
                from app.db.database import get_db
                from app.api.routes.movies import run_cover_backfill
                db = get_db()
                async with db.session() as s:
                    result = await run_cover_backfill(s, limit=5000)
                    logger.info(f"启动封面回填完成：扫描 {result['scanned']} 部，更新 {result['updated']} 部封面")
            except Exception as e:
                logger.warning(f"启动封面回填失败（可稍后手动调用 /api/v1/movies/backfill-covers）: {e}")
        asyncio.create_task(_startup_backfill())
    except Exception as e:
        logger.warning(f"安排启动封面回填失败: {e}")

    # 初始化插件系统 + 注册爬虫插件
    try:
        from app.services.plugin_manager import get_plugin_manager
        from app.services.plugin_loader_crawler import init_crawler_plugins
        pm = get_plugin_manager()
        crawler_count = init_crawler_plugins()
        total = len(pm.list_plugins())
        logger.info(f"插件系统初始化完成：共 {total} 个插件，已注册 {crawler_count} 个爬虫插件")
    except Exception as e:
        logger.warning(f"插件系统初始化失败: {e}")

    # 启动 CookieCloud 自动同步
    try:
        from app.services.cookiecloud import cookiecloud_service
        if config.cookiecloud.enabled:
            await cookiecloud_service.start_auto_sync()
            logger.info("CookieCloud 自动同步已启动")
        else:
            logger.info("CookieCloud 未启用，跳过自动同步")
    except Exception as e:
        logger.warning(f"CookieCloud 自动同步启动失败: {e}")

    # 启动 CloudDrive2 客户端
    try:
        from app.services.cloud_drive2 import cloud_drive2_client
        await cloud_drive2_client.start()
        if config.cloud_drive2.enabled:
            logger.info(f"CloudDrive2 客户端已启动: {config.cloud_drive2.url}")
    except Exception as e:
        logger.warning(f"CloudDrive2 客户端启动失败: {e}")

    # 启动 115 网盘客户端
    try:
        from app.services.pan_115 import pan_115_client
        await pan_115_client.start()
        if config.pan_115.enabled:
            logger.info(f"115 网盘客户端已启动")
    except Exception as e:
        logger.warning(f"115 网盘客户端启动失败: {e}")

    # 启动下载器管理器（§7.11 统一对接 qBittorrent / Transmission / Aria2）
    try:
        from app.services.downloader_manager import downloader_manager
        await downloader_manager.start_all()
        if downloader_manager.list_available():
            logger.info(f"下载器管理器已启动，激活下载器: {config.downloader.active or '(未设置)'}")
        else:
            logger.info("下载器管理器未启用（无已启用的下载器配置）")
    except Exception as e:
        logger.warning(f"下载器管理器启动失败: {e}")

    # 启动自动备份服务（Phase 6 生产级部署）
    try:
        from app.services.backup import backup_service
        backup_service.start_scheduled()
        if config.backup.enabled:
            logger.info(f"自动备份已启动: {config.backup.interval} @ {config.backup.schedule_time}")
        else:
            logger.info("自动备份未启用（可在配置中开启 backup.enabled）")
    except Exception as e:
        logger.warning(f"自动备份启动失败: {e}")

    # 启动订阅自动下载服务（v4.1 A1：演员/系列订阅自动搜索下载）
    try:
        from app.services.subscription_downloader import subscription_downloader_service
        await subscription_downloader_service.start()
        if subscription_downloader_service.is_running:
            logger.info("订阅自动下载服务已启动")
        else:
            logger.info("订阅自动下载服务未启用（可在配置中开启 subscription_downloader.enabled）")
    except Exception as e:
        logger.warning(f"订阅自动下载服务启动失败: {e}")

    # 启动自动整理定时任务（v4.1 B1：每小时检查一次已观看视频并按规则移动）
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from app.db.database import get_session_context
        from app.services.file_organize import auto_organize_watched

        _auto_organize_scheduler = AsyncIOScheduler()

        async def _auto_organize_job():
            """定时执行自动整理检查"""
            try:
                async with get_session_context() as session:
                    summary = await auto_organize_watched(session)
                    if summary.get("processed"):
                        logger.info(
                            f"自动整理定时任务完成：处理 {summary['processed']} 部，"
                            f"移动 {summary['moved']}，复制 {summary['copied']}"
                        )
            except Exception as exc:
                logger.error(f"自动整理定时任务异常: {exc}")

        _auto_organize_scheduler.add_job(
            _auto_organize_job,
            trigger=IntervalTrigger(hours=1),
            id="auto_organize_watched",
            replace_existing=True,
        )
        _auto_organize_scheduler.start()
        logger.info("自动整理定时任务已启动（每小时检查一次）")
    except Exception as e:
        logger.warning(f"自动整理定时任务启动失败: {e}")

    # 启动配置监视器：GUI 工具修改 media_dirs 后自动重新扫描（无需重启服务端）
    try:
        asyncio.create_task(_watch_config_and_rescan(poll_interval=5))
    except Exception as e:
        logger.warning(f"配置监视器启动失败: {e}")

    # 启动内置 Xray 代理管理器（v6：如果有节点则自动拉起 xray）
    try:
        from app.services.proxy_manager import get_proxy_manager
        _proxy_mgr = get_proxy_manager()
        # 若节点池非空，异步拉起 xray（不阻塞启动流程）
        if _proxy_mgr.list_nodes():
            asyncio.create_task(_proxy_mgr.start())
            logger.info("内置 Xray 代理: 已计划启动 (节点数=%d)", len(_proxy_mgr.list_nodes()))
        else:
            logger.info("内置 Xray 代理: 节点池为空，跳过启动")
    except Exception as e:
        logger.warning(f"内置 Xray 代理启动失败: {e}")

    yield

    # 关闭时(每个服务使用 asyncio.wait_for 设置超时,避免单个服务卡死阻塞整个关闭)
    # 默认关闭超时:5 秒(网络客户端)/ 10 秒(数据库)
    SHUTDOWN_TIMEOUT_NETWORK = 5.0
    SHUTDOWN_TIMEOUT_DB = 10.0

    async def _safe_close(name: str, coro, timeout: float):
        """安全关闭协程,带超时和异常捕获

        用 asyncio.wait_for 包裹协程,超时后强制取消并跳过,
        避免单个服务卡死阻塞整个应用关闭流程。
        """
        try:
            await asyncio.wait_for(coro, timeout=timeout)
            logger.info(f"{name}已停止")
        except asyncio.TimeoutError:
            logger.warning(f"{name}关闭超时({timeout}s),已强制跳过")
        except Exception as e:
            logger.warning(f"{name}关闭失败: {e}")

    # === 同步关闭的服务(无网络 IO,直接调用) ===
    # 目录监听
    try:
        from app.services.watcher import get_directory_watcher
        get_directory_watcher().stop()
        logger.info("目录监听已停止")
    except Exception as e:
        logger.warning(f"目录监听停止失败: {e}")

    # 内置 Xray 代理
    try:
        from app.services.proxy_manager import get_proxy_manager
        await _safe_close("内置Xray代理", get_proxy_manager().stop(), timeout=5.0)
    except Exception as e:
        logger.warning(f"内置Xray代理停止失败: {e}")

    # 自动备份服务(纯线程)
    try:
        from app.services.backup import backup_service
        backup_service.stop_scheduled()
        logger.info("自动备份已停止")
    except Exception as e:
        logger.warning(f"自动备份停止失败: {e}")

    # 自动整理定时任务(AsyncIOScheduler.shutdown 是同步方法)
    try:
        if _auto_organize_scheduler is not None:
            _auto_organize_scheduler.shutdown(wait=False)
            _auto_organize_scheduler = None
            logger.info("自动整理定时任务已停止")
    except Exception as e:
        logger.warning(f"自动整理定时任务停止失败: {e}")

    # 定时任务调度器
    try:
        from app.tasks.scheduled import get_scheduled_task_manager
        scheduler = get_scheduled_task_manager()
        scheduler.stop()
        logger.info("定时任务调度器已停止")
    except Exception as e:
        logger.warning(f"定时任务调度器停止失败: {e}")

    # === 异步关闭的服务(有网络 IO,用 asyncio.wait_for 包裹超时) ===
    # CookieCloud 自动同步
    try:
        from app.services.cookiecloud import cookiecloud_service
        await _safe_close(
            "CookieCloud 自动同步",
            cookiecloud_service.stop_auto_sync(),
            SHUTDOWN_TIMEOUT_NETWORK,
        )
    except Exception as e:
        logger.warning(f"CookieCloud 停止失败: {e}")

    # CloudDrive2 客户端
    try:
        from app.services.cloud_drive2 import cloud_drive2_client
        await _safe_close(
            "CloudDrive2 客户端",
            cloud_drive2_client.close(),
            SHUTDOWN_TIMEOUT_NETWORK,
        )
    except Exception as e:
        logger.warning(f"CloudDrive2 客户端关闭失败: {e}")

    # 115 网盘客户端
    try:
        from app.services.pan_115 import pan_115_client
        await _safe_close(
            "115 网盘客户端",
            pan_115_client.close(),
            SHUTDOWN_TIMEOUT_NETWORK,
        )
    except Exception as e:
        logger.warning(f"115 网盘客户端关闭失败: {e}")

    # 下载器管理器
    try:
        from app.services.downloader_manager import downloader_manager
        await _safe_close(
            "下载器管理器",
            downloader_manager.close_all(),
            SHUTDOWN_TIMEOUT_NETWORK,
        )
    except Exception as e:
        logger.warning(f"下载器管理器关闭失败: {e}")

    # 订阅自动下载服务
    try:
        from app.services.subscription_downloader import subscription_downloader_service
        await _safe_close(
            "订阅自动下载服务",
            subscription_downloader_service.stop(),
            SHUTDOWN_TIMEOUT_NETWORK,
        )
    except Exception as e:
        logger.warning(f"订阅自动下载服务停止失败: {e}")

    # HTTP 客户端
    try:
        from app.utils.http_client import close_http_client
        await _safe_close(
            "HTTP 客户端",
            close_http_client(),
            SHUTDOWN_TIMEOUT_NETWORK,
        )
    except Exception as e:
        logger.warning(f"HTTP 客户端关闭失败: {e}")

    # 数据库连接(最后关闭,给较长时间)
    try:
        from app.db.database import get_database
        await _safe_close(
            "数据库连接",
            get_database().close(),
            SHUTDOWN_TIMEOUT_DB,
        )
    except Exception as e:
        logger.warning(f"数据库关闭失败: {e}")

    logger.info("应用关闭")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    config = get_config()

    app = FastAPI(
        title=config.app_name,
        description="龙魂视频管理系统 - 视频元数据刮削与管理平台",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    logger.info("="*50)
    logger.info("create_app() 开始创建应用")
    
    # 测试路由 - 第一个就注册，绝对能访问到
    @app.get("/test", include_in_schema=False)
    async def test_page():
        logger.info("访问 /test 路由")
        return {"message": "测试成功！", "status": "ok"}
    
    logger.info("✅ 测试路由 /test 已注册")

    # CORS 中间件统一在 AuthMiddleware 之后注册（即最外层），
    # 否则 OPTIONS 预检请求会被 AuthMiddleware 拦截返回 401，
    # 导致浏览器跨域（如网页版以 127.0.0.1 访问、SPA 调 localhost:8420）全部失败。
    # 详见文件末尾 app.add_middleware(AuthMiddleware) 之后的注册。

    # GZip 压缩中间件（压缩响应体，大幅减少传输大小）
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Prometheus 指标采集中间件（自动统计 HTTP 请求计数/延迟）
    try:
        from app.services.metrics import MetricsMiddleware
        app.add_middleware(MetricsMiddleware)
        logger.info("✅ Prometheus 指标中间件已注册")
    except Exception as e:
        logger.warning(f"指标中间件注册失败: {e}")

    
    # 根路径与 /login 直接返回 SPA（index.html），由前端路由接管登录态
    logger.info("准备注册根路径和登录路由")
    @app.get("/", include_in_schema=False)
    async def root_page():
        logger.info("访问根路径 /")
        if static_dir:
            return FileResponse(str(static_dir / "index.html"), headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h1>前端资源未找到</h1>")

    @app.get("/login", include_in_schema=False)
    async def login_page():
        logger.info("访问登录页 /login")
        if static_dir:
            return FileResponse(str(static_dir / "index.html"), headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h1>前端资源未找到</h1>")

    logger.info("✅ 根路径和登录路由已注册（已指向 SPA）")

    # 先查找 static_dir（调试路由需要用到）
    static_dir = None
    
    # 策略1：环境变量（最可靠，由 mdcx_server.py 启动时设置）
    env_static = os.getenv("MDCX_STATIC_DIR")
    if env_static:
        candidate = Path(env_static)
        if candidate.exists() and (candidate / "index.html").exists():
            static_dir = candidate
            logger.info(f"静态目录(env): {static_dir}")
    
    # 策略2：PyInstaller 打包后 sys._MEIPASS 目录
    if not static_dir:
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidate = Path(meipass) / "static"
            if candidate.exists() and (candidate / "index.html").exists():
                static_dir = candidate
                logger.info(f"静态目录(meipass): {static_dir}")
    
    # 策略3：当前工作目录
    if not static_dir:
        candidate = Path.cwd() / "static"
        if candidate.exists() and (candidate / "index.html").exists():
            static_dir = candidate
            logger.info(f"静态目录(cwd): {static_dir}")
    
    # 策略4：项目根目录
    if not static_dir:
        candidate = PROJECT_ROOT / "static"
        if candidate.exists() and (candidate / "index.html").exists():
            static_dir = candidate
            logger.info(f"静态目录(project): {static_dir}")
    
    # 策略5：打包后 exe 相关路径暴力搜索
    if not static_dir and getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        for sub in [
            "static",
            "../static",
            "_internal/static",
            "../../static",
        ]:
            candidate = (exe_dir / sub).resolve()
            if candidate.exists() and (candidate / "index.html").exists():
                static_dir = candidate
                logger.info(f"静态目录(exe): {static_dir}")
                break
    
    # 策略6：通过 MDCX_EXE_DIR 环境变量（由 mdcx_server.py 最新版设置）
    if not static_dir:
        exe_dir_str = os.getenv("MDCX_EXE_DIR")
        if exe_dir_str:
            exe_dir = Path(exe_dir_str)
            for sub in ["static", "../static", "_internal/static"]:
                candidate = (exe_dir / sub).resolve()
                if candidate.exists() and (candidate / "index.html").exists():
                    static_dir = candidate
                    logger.info(f"静态目录(MDCX_EXE_DIR): {static_dir}")
                    break

    # 调试端点（不认证，用于调试）- 必须在 SPA 路由之前注册！
    @app.get("/api/debug/paths")
    async def debug_paths():
        """调试：查看所有路径"""
        env_static = os.getenv("MDCX_STATIC_DIR")
        paths = {
            "PROJECT_ROOT": str(PROJECT_ROOT),
            "__file__": __file__,
            "cwd": str(Path.cwd()),
            "sys._MEIPASS": str(getattr(sys, '_MEIPASS', '')),
            "MDCX_STATIC_DIR env": env_static or "(not set)",
            "static_mounted": str(static_dir) if static_dir else None,
        }
        # 添加静态文件候选路径检查
        candidates = [
            ("_MEIPASS/static", Path(getattr(sys, '_MEIPASS', '')) / "static" if getattr(sys, '_MEIPASS', None) else None),
            ("MDCX_STATIC_DIR", Path(env_static) if env_static else None),
            ("CWD/static", Path.cwd() / "static"),
            ("PROJECT_ROOT/static", PROJECT_ROOT / "static"),
        ]
        for label, c in candidates:
            if c:
                paths[f"candidate_{label}"] = {
                    "path": str(c),
                    "exists": c.exists(),
                    "has_index": (c / "index.html").exists() if c.exists() else False
                }
            else:
                paths[f"candidate_{label}"] = None
        return paths
    
    logger.info("✅ 调试路由 /api/debug/paths 已注册")

    # 注册 API 路由（延迟导入，避免模块级导入影响启动速度）
    from app.api import api_router
    app.include_router(api_router, prefix="/api/v1")

    # 注册 WebSocket 路由（不走 /api/v1 前缀，便于前端直连）
    from app.services.websocket import router as ws_router_mod
    app.include_router(ws_router_mod)
    logger.info("✅ WebSocket 路由 /ws/logs 已注册")

    # 注册 Emby 协议兼容路由（不走 /api/v1 前缀，挂载在 /emby 路径下）
    from app.api.routes.emby_compat import router as emby_router_mod
    app.include_router(emby_router_mod, prefix="/emby")
    logger.info("✅ Emby 协议兼容路由 /emby/* 已注册")

    # 注册 TVBox 开放接口路由（不走 /api/v1 前缀，挂载在 /tvbox 路径下）
    from app.api.routes.tvbox import router as tvbox_router_mod
    app.include_router(tvbox_router_mod, prefix="/tvbox")
    logger.info("✅ TVBox 开放接口路由 /tvbox/* 已注册")

    # 注册 MacCMS v10 采集接口路由（不走 /api/v1 前缀，挂载在 /maccms 路径下）
    from app.api.routes.maccms import router as maccms_router_mod
    app.include_router(maccms_router_mod, prefix="/maccms")
    logger.info("✅ MacCMS 采集接口路由 /maccms/* 已注册")

    # 注册 WebDAV 服务端路由（不走 /api/v1 前缀，挂载路径可配置，默认 /webdav）
    # 注意：必须在 SPA 回退路由之前注册，否则会被 /{full_path:path} 拦截
    try:
        webdav_cfg = config.webdav_server
        if webdav_cfg.enabled:
            from app.services.webdav_server import router as webdav_router_mod
            mount_path = webdav_cfg.mount_path.rstrip("/") or "/webdav"
            app.include_router(webdav_router_mod, prefix=mount_path)
            logger.info(f"✅ WebDAV 服务端路由 {mount_path}/* 已注册（布局: {webdav_cfg.virtual_layout}）")
        else:
            logger.info("ℹ️ WebDAV 服务端未启用（可在配置中开启 webdav_server.enabled）")
    except Exception as e:
        logger.warning(f"WebDAV 服务端路由注册失败: {e}")

    # 注册 Metatube 兼容路由（不走 /api/v1 前缀，挂载到 /metatube 根路径，供 Jellyfin 调用）
    # 注意：必须在 SPA 回退路由之前注册
    try:
        from app.api.routes.metatube import router as metatube_router_mod
        mt_cfg = config.metatube
        mt_path = mt_cfg.base_path.rstrip("/") or "/metatube"
        app.include_router(metatube_router_mod, prefix=mt_path)
        if mt_cfg.enabled:
            logger.info(f"✅ Metatube 兼容路由 {mt_path}/* 已注册（插件名: {mt_cfg.plugin_name}）")
        else:
            logger.info(f"ℹ️ Metatube 兼容路由 {mt_path}/* 已注册但未启用")
    except Exception as e:
        logger.warning(f"Metatube 兼容路由注册失败: {e}")

    # 注册 Prometheus 指标端点（不走 /api/v1 前缀，无认证，供 Prometheus 直连抓取）
    # 注意：必须在 SPA 回退路由之前注册
    @app.get("/metrics", include_in_schema=False)
    async def standalone_metrics():
        from app.services.metrics import generate_metrics_text, get_content_type, collect_db_metrics
        await collect_db_metrics()
        text = generate_metrics_text()
        return Response(content=text, media_type=get_content_type())
    logger.info("✅ Prometheus 指标端点 /metrics 已注册")
    
    # 记录最终结果
    if static_dir:
        logger.info(f"前端资源目录: {static_dir}")
    else:
        logger.error(f"静态文件目录在所有策略中均未找到！")
        logger.error(f"  sys._MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")
        logger.error(f"  PROJECT_ROOT: {PROJECT_ROOT}")
        logger.error(f"  CWD: {Path.cwd()}")
        logger.error(f"  MDCX_STATIC_DIR: {os.getenv('MDCX_STATIC_DIR', 'N/A')}")
        logger.error(f"  sys.executable: {sys.executable if getattr(sys, 'frozen', False) else 'N/A'}")
    
    if static_dir:
        assets_dir = static_dir / "assets"
        
        # 直接路由提供静态资源（避免 app.mount 在打包环境中的兼容问题）
        @app.get("/assets/{file_path:path}", include_in_schema=False)
        async def serve_assets(file_path: str):
            target = (assets_dir / file_path).resolve()
            # 安全检查：防止目录穿越
            if str(target).startswith(str(assets_dir.resolve())) and target.exists() and target.is_file():
                # 带 hash 的静态资源可以长期缓存
                headers = {"Cache-Control": "public, max-age=31536000, immutable"}
                return FileResponse(str(target), headers=headers)
            return Response(status_code=404)
        
        # favicon
        @app.get("/favicon.svg", include_in_schema=False)
        async def serve_favicon():
            favicon = static_dir / "favicon.svg"
            if favicon.exists():
                return FileResponse(str(favicon))
            return Response(status_code=404)
        
        @app.get("/favicon.ico", include_in_schema=False)
        async def serve_favicon_ico():
            favicon = static_dir / "favicon.ico"
            if favicon.exists():
                return FileResponse(str(favicon))
            return Response(status_code=404)
        
        # SPA 路由：所有非 API 请求返回 index.html
        @app.api_route("/{full_path:path}", methods=["GET"], include_in_schema=False)
        async def serve_spa(full_path: str):
            # 排除 api 和 assets 路径
            if full_path.startswith("api/") or full_path.startswith("assets/"):
                return {"detail": "Not Found"}
            # 静态资源直接返回文件（不经过 SPA）
            target = (static_dir / full_path).resolve()
            if target.exists() and target.is_file() and str(target).startswith(str(static_dir.resolve())):
                return FileResponse(str(target))
            # index.html 不缓存，确保用户总能拿到最新版本
            return FileResponse(str(static_dir / "index.html"), headers={"Cache-Control": "no-cache"})
        

        logger.info(f"前端静态资源目录: {static_dir}")
    else:
        logger.error(f"静态文件目录未找到！")
        logger.error(f"  PROJECT_ROOT: {PROJECT_ROOT}")
        logger.error(f"  CWD: {Path.cwd()}")
        logger.error(f"  MDCX_STATIC_DIR env: {os.getenv('MDCX_STATIC_DIR')}")

    # 调试端点已在前面注册（避免被 SPA 路由拦截）

    # 打印所有已注册的路由（调试用）
    logger.info("="*50)
    logger.info("所有已注册的路由：")
    for route in app.routes:
        methods = getattr(route, "methods", None) or {"WS"}
        logger.info(f"  - {route.name}: {route.path} ({methods})")
    logger.info("="*50)
    
    logger.info("✅ 应用创建完成！")

    # 认证中间件（保护所有 API）- ASGI 方式（兼容 app.mount）
    from app.api.auth_middleware import AuthMiddleware
    app.add_middleware(AuthMiddleware)

    # CORS 中间件（最外层）：必须放在 AuthMiddleware 之后，
    # 这样浏览器发出的 OPTIONS 预检请求会先被 CORS 处理并返回 200，
    # 不会被 AuthMiddleware 拦截成 401，跨域访问网页版才不会报 CORS 错误。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn

    config = get_config()
    uvicorn.run(
        "app.main:app",
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers,
        reload=config.server.debug,
    )
