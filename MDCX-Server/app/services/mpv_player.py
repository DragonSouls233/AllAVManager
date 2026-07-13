"""
mpv 播放器集成服务

参考 JavBoss 的 mpv player 模块：
- 可配置热键（seek/音量/截图/暂停）
- 播放中截图（自动存到 thumbnails 目录）
- 启动参数：窗口大小、音量、置顶、起始时间
- 跨平台支持

MDCX 是 Electron 桌面端，通过后端 API 启动本地 mpv 进程。
"""
import json
import logging
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.config.manager import get_config_manager
from app.db.database import get_database
from app.db.models import Movie
from sqlalchemy import select

logger = logging.getLogger(__name__)

# 默认热键配置
DEFAULT_HOTKEYS = [
    {"key": "a", "action": "seek", "amount": -1},
    {"key": "z", "action": "seek", "amount": 1},
    {"key": "s", "action": "seek", "amount": -5},
    {"key": "x", "action": "seek", "amount": 5},
    {"key": "d", "action": "seek", "amount": -30},
    {"key": "c", "action": "seek", "amount": 30},
    {"key": "f", "action": "seek", "amount": -300},
    {"key": "v", "action": "seek", "amount": 300},
    {"key": "q", "action": "volume", "amount": -5},
    {"key": "w", "action": "volume", "amount": 5},
    {"key": "e", "action": "screenshot"},
    {"key": "SPACE", "action": "pause"},
    {"key": "ESC", "action": "quit"},
]


def _find_mpv() -> Optional[str]:
    """查找 mpv 可执行文件"""
    mpv = shutil.which("mpv")
    if mpv:
        return mpv

    # Windows 常见安装路径
    if platform.system() == "Windows":
        for p in [
            r"C:\Program Files\mpv\mpv.exe",
            r"C:\Program Files (x86)\mpv\mpv.exe",
            str(Path.home() / "scoop" / "apps" / "mpv" / "current" / "mpv.exe"),
        ]:
            if Path(p).exists():
                return p
    else:
        for p in ["/usr/bin/mpv", "/usr/local/bin/mpv", "/opt/homebrew/bin/mpv"]:
            if Path(p).exists():
                return p

    return None


def _build_input_conf(hotkeys: list[dict]) -> str:
    """生成 mpv input.conf 内容"""
    lines = []
    for hk in hotkeys:
        key = hk["key"]
        action = hk["action"]
        amount = hk.get("amount", 0)

        if action == "seek":
            direction = abs(amount)
            sign = "-" if amount < 0 else ""
            lines.append(f"{key} seek {sign}{direction} exact")
        elif action == "volume":
            direction = abs(amount)
            sign = "-" if amount < 0 else ""
            lines.append(f"{key} add volume {sign}{direction}")
        elif action == "screenshot":
            lines.append(f"{key} screenshot")
        elif action == "pause":
            lines.append(f"{key} cycle pause")
        elif action == "quit":
            lines.append(f"{key} quit")

    return "\n".join(lines) + "\n"


def _get_screenshot_dir(movie_id: int) -> Path:
    """获取影片截图目录"""
    from app.services.thumbnail import _get_thumbnail_dir
    return _get_thumbnail_dir(movie_id)


async def play_video(
    movie_id: int,
    start_time: float = 0,
    volume: int = 70,
    window_width: Optional[int] = None,
    window_height: Optional[int] = None,
    on_top: bool = True,
    hotkeys: Optional[list[dict]] = None,
) -> dict:
    """
    启动 mpv 播放视频

    参数:
        movie_id: 影片 ID
        start_time: 起始时间（秒）
        volume: 音量 (0-100)
        window_width: 窗口宽度
        window_height: 窗口高度
        on_top: 窗口置顶
        hotkeys: 热键配置（None 则用默认）

    返回:
        {"status": "ok", "pid": ...} 或 {"status": "error", "message": ...}
    """
    mpv_path = _find_mpv()
    if not mpv_path:
        return {"status": "error", "message": "未找到 mpv 可执行文件，请安装 mpv"}

    # 异步获取影片文件路径
    movie = await _get_movie(movie_id)

    if not movie or not movie.file_path:
        return {"status": "error", "message": "影片不存在或没有关联文件"}

    file_path = Path(movie.file_path)
    if not file_path.exists():
        return {"status": "error", "message": f"视频文件不存在: {file_path}"}

    # 生成 input.conf
    hk_config = hotkeys or DEFAULT_HOTKEYS
    input_conf = _build_input_conf(hk_config)

    # 写入临时 input.conf
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False, encoding="utf-8") as f:
        f.write(input_conf)
        input_conf_path = f.name

    # 截图目录
    screenshot_dir = _get_screenshot_dir(movie_id)

    # 构建 mpv 启动参数
    cmd = [mpv_path]

    # 输入配置
    cmd.extend([f"--input-conf={input_conf_path}"])

    # 起始时间
    if start_time > 0:
        cmd.append(f"--start={start_time}")

    # 音量
    cmd.append(f"--volume={volume}")

    # 窗口置顶
    if on_top:
        cmd.append("--ontop")

    # 窗口大小
    if window_width and window_height:
        cmd.append(f"--autofit={window_width}x{window_height}")

    # 截图设置
    screenshot_template = str(screenshot_dir / "mpv_%wH-%wM-%wS")
    cmd.extend([
        f"--screenshot-template={screenshot_template}",
        "--screenshot-format=jpg",
        "--screenshot-quality=90",
    ])

    # OSD 热键提示
    osd_msg = "播放中 | a/z:±1s s/x:±5s d/c:±30s e:截图 空格:暂停 ESC:退出"
    cmd.append(f"--osd-playing-msg={osd_msg}")

    # 视频文件
    cmd.append("--")
    cmd.append(str(file_path))

    try:
        # 启动进程（非阻塞）
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"mpv 已启动，PID={process.pid}，影片={movie.code}")

        return {
            "status": "ok",
            "pid": process.pid,
            "mpv_path": mpv_path,
            "file_path": str(file_path),
        }
    except Exception as e:
        logger.error(f"启动 mpv 失败: {e}")
        return {"status": "error", "message": str(e)}


async def _get_movie(movie_id: int) -> Optional[Movie]:
    """从数据库获取影片"""
    db = get_database()
    async with db.session() as session:
        return await session.get(Movie, movie_id)


async def get_mpv_config() -> dict:
    """获取 mpv 配置（热键、音量等）"""
    from app.db.models import Setting

    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            select(Setting).where(Setting.key.in_([
                "player_hotkeys",
                "player_volume",
                "player_ontop",
                "player_window_width",
                "player_window_height",
            ]))
        )
        rows = result.scalars().all()
        config = {r.key: r.value for r in rows}

    hotkeys = DEFAULT_HOTKEYS
    if "player_hotkeys" in config:
        try:
            hotkeys = json.loads(config["player_hotkeys"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "hotkeys": hotkeys,
        "volume": int(config.get("player_volume", 70)),
        "on_top": config.get("player_ontop", "true") == "true",
        "window_width": int(config["player_window_width"]) if "player_window_width" in config else None,
        "window_height": int(config["player_window_height"]) if "player_window_height" in config else None,
    }


async def save_mpv_config(
    hotkeys: Optional[list[dict]] = None,
    volume: Optional[int] = None,
    on_top: Optional[bool] = None,
    window_width: Optional[int] = None,
    window_height: Optional[int] = None,
) -> dict:
    """保存 mpv 配置到数据库"""
    from app.db.models import Setting

    updates = {}
    if hotkeys is not None:
        updates["player_hotkeys"] = json.dumps(hotkeys, ensure_ascii=False)
    if volume is not None:
        updates["player_volume"] = str(volume)
    if on_top is not None:
        updates["player_ontop"] = "true" if on_top else "false"
    if window_width is not None:
        updates["player_window_width"] = str(window_width)
    if window_height is not None:
        updates["player_window_height"] = str(window_height)

    if not updates:
        return {"status": "ok", "message": "无更新"}

    db = get_database()
    async with db.session() as session:
        for key, value in updates.items():
            existing = await session.scalar(
                select(Setting).where(Setting.key == key)
            )
            if existing:
                existing.value = value
            else:
                session.add(Setting(key=key, value=value))
        await session.commit()

    logger.info(f"mpv 配置已保存: {list(updates.keys())}")
    return {"status": "ok", "updated": list(updates.keys())}
