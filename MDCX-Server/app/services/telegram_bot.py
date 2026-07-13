"""
Telegram Bot 服务

提供：
- Bot 配置持久化（token、允许的 chat_ids、命令权限）
- 主动通知发送（与 WebhookManager 互补）
- 命令处理框架（/start /help /status /search /subscribe 等）
- 长轮询（getUpdates）作为可选运行模式
- Webhook 模式设置（setWebhook）

设计要点：
- 独立模块，不依赖现有 app/utils/webhook.py
- 配置存储在 data/telegram_bot.json
- 不强制启用，默认关闭
- 不阻塞主线程，长轮询使用 asyncio.create_task
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any

import httpx

logger = logging.getLogger(__name__)


# ===== 配置 =====

@dataclass
class TelegramBotConfig:
    """Telegram Bot 配置"""
    bot_token: str = ""                                # Bot Token
    allowed_chat_ids: list[int] = field(default_factory=list)  # 允许的 Chat ID
    allowed_usernames: list[str] = field(default_factory=list) # 允许的 @username
    enabled: bool = False                              # 是否启用
    mode: str = "polling"                              # polling / webhook
    webhook_url: str = ""                              # webhook 模式 URL
    webhook_secret: str = ""                           # webhook 密钥
    command_prefix: str = "/"                          # 命令前缀
    language: str = "zh"                               # 语言
    enable_inline_search: bool = True                  # 启用内联搜索
    notification_events: list[str] = field(default_factory=lambda: [
        "scrape.complete",
        "scrape.batch_done",
        "system.error",
    ])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TelegramBotConfig":
        return cls(
            bot_token=data.get("bot_token", ""),
            allowed_chat_ids=data.get("allowed_chat_ids", []),
            allowed_usernames=data.get("allowed_usernames", []),
            enabled=data.get("enabled", False),
            mode=data.get("mode", "polling"),
            webhook_url=data.get("webhook_url", ""),
            webhook_secret=data.get("webhook_secret", ""),
            command_prefix=data.get("command_prefix", "/"),
            language=data.get("language", "zh"),
            enable_inline_search=data.get("enable_inline_search", True),
            notification_events=data.get("notification_events", [
                "scrape.complete", "scrape.batch_done", "system.error",
            ]),
        )


# ===== 命令处理器 =====

CommandHandler = Callable[[dict], Awaitable[dict]]


class TelegramBotService:
    """
    Telegram Bot 服务

    使用：
        service = get_telegram_bot_service()
        await service.start()              # 启动长轮询
        await service.send_message(chat_id, "hello")
        await service.stop()
    """

    API_BASE = "https://api.telegram.org"

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()
        self._client: Optional[httpx.AsyncClient] = None
        self._polling_task: Optional[asyncio.Task] = None
        self._polling_offset = 0
        self._running = False
        # 命令注册表
        self._commands: dict[str, tuple[str, CommandHandler]] = {}
        # 注册内置命令
        self._register_builtin_commands()

    # ===== 配置 =====

    def _load_config(self) -> TelegramBotConfig:
        if not self.config_path.exists():
            return TelegramBotConfig()
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return TelegramBotConfig.from_dict(data)
        except Exception as e:
            logger.error(f"加载 Telegram Bot 配置失败: {e}")
            return TelegramBotConfig()

    def _save_config(self) -> None:
        try:
            self.config_path.write_text(
                json.dumps(self.config.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"保存 Telegram Bot 配置失败: {e}")

    def update_config(self, data: dict) -> TelegramBotConfig:
        """更新配置（重启后生效）"""
        self.config = TelegramBotConfig.from_dict({**self.config.to_dict(), **data})
        self._save_config()
        return self.config

    def get_config(self) -> dict:
        # 不返回完整 token（防止泄露），返回 mask 后的版本
        cfg = self.config.to_dict()
        if cfg["bot_token"]:
            token = cfg["bot_token"]
            cfg["bot_token_masked"] = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
        else:
            cfg["bot_token_masked"] = ""
        # 不暴露 webhook_secret
        cfg["webhook_secret"] = "***" if cfg["webhook_secret"] else ""
        return cfg

    # ===== HTTP =====

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def _api_call(self, method: str, **params) -> dict:
        """调用 Telegram Bot API"""
        if not self.config.bot_token:
            raise RuntimeError("Bot token 未配置")
        url = f"{self.API_BASE}/bot{self.config.bot_token}/{method}"
        client = self._get_client()
        resp = await client.post(url, json=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API 错误: {data.get('description')}")
        return data.get("result", {})

    # ===== 鉴权 =====

    def _is_authorized(self, update: dict) -> bool:
        """检查 update 是否来自授权用户"""
        if not self.config.allowed_chat_ids and not self.config.allowed_usernames:
            # 未配置白名单时，允许所有（开发模式）
            return True
        msg = update.get("message") or update.get("callback_query", {}).get("message") or {}
        chat = msg.get("chat", {})
        user = msg.get("from", {})
        if chat.get("id") in self.config.allowed_chat_ids:
            return True
        if user.get("username") in self.config.allowed_usernames:
            return True
        return False

    # ===== 消息发送 =====

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Optional[dict] = None,
        disable_web_page_preview: bool = True,
    ) -> dict:
        """发送消息"""
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            params["reply_markup"] = reply_markup
        return await self._api_call("sendMessage", **params)

    async def send_photo(
        self,
        chat_id: int | str,
        photo: str,
        caption: str = "",
        parse_mode: str = "Markdown",
    ) -> dict:
        """发送图片"""
        return await self._api_call(
            "sendPhoto",
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
        )

    async def broadcast(self, text: str, parse_mode: str = "Markdown") -> int:
        """广播到所有允许的 chat_id"""
        success = 0
        for chat_id in self.config.allowed_chat_ids:
            try:
                await self.send_message(chat_id, text, parse_mode=parse_mode)
                success += 1
            except Exception as e:
                logger.error(f"广播到 {chat_id} 失败: {e}")
        return success

    # ===== 命令注册 =====

    def register_command(self, name: str, description: str, handler: CommandHandler) -> None:
        """注册命令"""
        self._commands[name] = (description, handler)

    def _register_builtin_commands(self) -> None:
        """注册内置命令"""
        self.register_command("start", "启动 Bot", self._cmd_start)
        self.register_command("help", "显示帮助", self._cmd_help)
        self.register_command("status", "查看系统状态", self._cmd_status)
        self.register_command("ping", "测试连通性", self._cmd_ping)
        self.register_command("subscribe", "订阅演员 (格式: /subscribe 演员名)", self._cmd_subscribe)
        self.register_command("subscriptions", "查看订阅列表", self._cmd_list_subscriptions)
        self.register_command("search", "搜索影片 (格式: /search 番号)", self._cmd_search)
        self.register_command("report", "查看观影报告", self._cmd_report)

    async def _cmd_start(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        return await self.send_message(
            chat_id,
            "👋 欢迎使用 MDCX Bot！\n\n"
            "可用命令：\n"
            "/help - 显示帮助\n"
            "/status - 系统状态\n"
            "/search <番号> - 搜索影片\n"
            "/subscribe <演员名> - 订阅演员\n"
            "/subscriptions - 查看订阅\n"
            "/report - 观影报告\n"
        )

    async def _cmd_help(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        lines = ["📖 命令列表：\n"]
        for name, (desc, _) in self._commands.items():
            lines.append(f"/{name} - {desc}")
        return await self.send_message(chat_id, "\n".join(lines))

    async def _cmd_status(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        try:
            from app.db.database import async_session_factory
            from sqlalchemy import select, func
            from app.db.models import Movie, Actor
            async with async_session_factory() as session:
                movie_count = (await session.execute(select(func.count(Movie.id)))).scalar_one()
                actor_count = (await session.execute(select(func.count(Actor.id)))).scalar_one()
            return await self.send_message(
                chat_id,
                f"📊 *系统状态*\n\n"
                f"影片数: {movie_count}\n"
                f"演员数: {actor_count}\n"
                f"Bot 状态: {'运行中' if self._running else '已停止'}\n",
            )
        except Exception as e:
            return await self.send_message(chat_id, f"❌ 获取状态失败: {e}")

    async def _cmd_ping(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        return await self.send_message(chat_id, f"🏓 Pong！时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    async def _cmd_subscribe(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return await self.send_message(chat_id, "⚠️ 用法: /subscribe 演员名")
        actor_name = parts[1].strip()
        try:
            from app.db.database import async_session_factory
            from sqlalchemy import select
            from app.db.models import Actor
            from app.services.actor_subscription import subscribe, list_subscriptions
            async with async_session_factory() as session:
                stmt = select(Actor).where(Actor.name == actor_name).limit(1)
                actor = (await session.execute(stmt)).scalar_one_or_none()
                if actor is None:
                    return await self.send_message(chat_id, f"❌ 未找到演员: {actor_name}")
                await subscribe(user_id=None, actor_id=actor.id, notify_new_movie=True, session=session)
            return await self.send_message(
                chat_id, f"✅ 已订阅演员: *{actor_name}*\n新片发布时会自动通知。"
            )
        except Exception as e:
            return await self.send_message(chat_id, f"❌ 订阅失败: {e}")

    async def _cmd_list_subscriptions(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        try:
            from app.db.database import async_session_factory
            from app.services.actor_subscription import list_subscriptions
            async with async_session_factory() as session:
                subs = await list_subscriptions(user_id=None, session=session)
            if not subs:
                return await self.send_message(chat_id, "📭 暂无订阅")
            lines = ["📋 订阅列表：\n"]
            for s in subs[:20]:
                new_mark = f" (+{s['new_movie_count']} 新)" if s["new_movie_count"] > 0 else ""
                lines.append(f"• {s['actor_name']} ({s['current_movie_count']} 部){new_mark}")
            return await self.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            return await self.send_message(chat_id, f"❌ 查询失败: {e}")

    async def _cmd_search(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return await self.send_message(chat_id, "⚠️ 用法: /search 番号")
        code = parts[1].strip()
        try:
            from app.db.database import async_session_factory
            from sqlalchemy import select, or_
            from app.db.models import Movie
            async with async_session_factory() as session:
                stmt = select(Movie).where(
                    or_(Movie.code == code, Movie.code.contains(code))
                ).limit(5)
                movies = (await session.execute(stmt)).scalars().all()
            if not movies:
                return await self.send_message(chat_id, f"🔍 未找到影片: {code}")
            lines = ["🔍 搜索结果：\n"]
            for m in movies:
                title = (m.title or "未命名")[:50]
                lines.append(f"• `{m.code}` - {title}")
                if m.release_date:
                    lines.append(f"  发布: {m.release_date}")
                if m.rating:
                    lines.append(f"  评分: ⭐ {m.rating}/10")
            return await self.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            return await self.send_message(chat_id, f"❌ 搜索失败: {e}")

    async def _cmd_report(self, update: dict) -> dict:
        chat_id = update["message"]["chat"]["id"]
        try:
            from app.db.database import async_session_factory
            from app.services.viewing_report import generate_report
            async with async_session_factory() as session:
                report = await generate_report(user_id=None, session=session, days=30)
            summary = report["summary"]
            lines = [
                f"📈 *最近 {report['period_days']} 天观影报告*\n",
                f"播放次数: {summary['play_count']}",
                f"观看时长: {summary['total_duration_human']}",
                f"独立影片: {summary['unique_movies']}",
                f"完成率: {summary['completion_rate']*100:.0f}%",
                "",
                "💡 洞察：",
            ]
            for insight in report["insights"][:5]:
                lines.append(f"• {insight}")
            return await self.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            return await self.send_message(chat_id, f"❌ 报告生成失败: {e}")

    # ===== 命令分发 =====

    async def _handle_update(self, update: dict) -> None:
        """处理单个 update"""
        if not self._is_authorized(update):
            logger.warning(f"未授权的 update: {update.get('update_id')}")
            return

        msg = update.get("message")
        if not msg:
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith(self.config.command_prefix):
            return

        # 解析命令
        parts = text[1:].split(maxsplit=1)
        cmd_name = parts[0].lower()
        if cmd_name not in self._commands:
            await self.send_message(msg["chat"]["id"], f"❓ 未知命令: /{cmd_name}\n输入 /help 查看可用命令")
            return

        try:
            _, handler = self._commands[cmd_name]
            await handler(update)
        except Exception as e:
            logger.error(f"命令 /{cmd_name} 处理失败: {e}")
            try:
                await self.send_message(msg["chat"]["id"], f"❌ 命令执行失败: {e}")
            except Exception:
                pass

    # ===== 长轮询 =====

    async def _polling_loop(self) -> None:
        """长轮询主循环"""
        logger.info("Telegram Bot 长轮询已启动")
        self._running = True
        client = self._get_client()
        while self._running:
            try:
                url = f"{self.API_BASE}/bot{self.config.bot_token}/getUpdates"
                params = {"timeout": 30, "offset": self._polling_offset}
                resp = await client.post(url, json=params, timeout=35)
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"getUpdates 错误: {data.get('description')}")
                    await asyncio.sleep(5)
                    continue
                updates = data.get("result", [])
                for update in updates:
                    self._polling_offset = update["update_id"] + 1
                    try:
                        await self._handle_update(update)
                    except Exception as e:
                        logger.error(f"处理 update 失败: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"轮询异常: {e}")
                await asyncio.sleep(5)
        logger.info("Telegram Bot 长轮询已停止")

    # ===== 启动 / 停止 =====

    async def start(self) -> bool:
        """启动 Bot"""
        if not self.config.enabled:
            return False
        if not self.config.bot_token:
            return False
        if self._polling_task is not None and not self._polling_task.done():
            return True
        # 测试 token 有效性
        try:
            me = await self._api_call("getMe")
            logger.info(f"Telegram Bot 已启动: @{me.get('username')}")
            # 设置命令列表
            await self._set_my_commands()
        except Exception as e:
            logger.error(f"启动 Bot 失败（token 无效？）: {e}")
            return False
        if self.config.mode == "polling":
            self._polling_task = asyncio.create_task(self._polling_loop())
        elif self.config.mode == "webhook":
            await self._set_webhook()
        return True

    async def stop(self) -> None:
        """停止 Bot"""
        self._running = False
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def restart(self) -> bool:
        """重启 Bot（配置更新后调用）"""
        await self.stop()
        return await self.start()

    async def _set_my_commands(self) -> None:
        """设置 Bot 命令列表"""
        try:
            commands = [
                {"command": name, "description": desc}
                for name, (desc, _) in self._commands.items()
            ]
            await self._api_call("setMyCommands", commands=commands)
        except Exception as e:
            logger.warning(f"设置命令列表失败: {e}")

    async def _set_webhook(self) -> None:
        """设置 Webhook"""
        if not self.config.webhook_url:
            return
        try:
            await self._api_call(
                "setWebhook",
                url=self.config.webhook_url,
                secret_token=self.config.webhook_secret,
            )
            logger.info(f"Webhook 已设置: {self.config.webhook_url}")
        except Exception as e:
            logger.error(f"设置 Webhook 失败: {e}")

    async def delete_webhook(self) -> None:
        """删除 Webhook（切换到 polling 模式时调用）"""
        try:
            await self._api_call("deleteWebhook")
        except Exception as e:
            logger.error(f"删除 Webhook 失败: {e}")

    # ===== 状态 =====

    def get_status(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "running": self._running,
            "mode": self.config.mode,
            "authorized_count": len(self.config.allowed_chat_ids),
            "commands": [name for name in self._commands],
        }

    # ===== 接收 Webhook update（webhook 模式） =====

    async def handle_webhook_update(self, update: dict, secret: str = "") -> dict:
        """处理通过 webhook 接收的 update"""
        if self.config.webhook_secret and secret != self.config.webhook_secret:
            return {"ok": False, "error": "invalid secret"}
        try:
            await self._handle_update(update)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ===== 全局单例 =====

_service: Optional[TelegramBotService] = None


def get_telegram_bot_service() -> TelegramBotService:
    """获取全局 TelegramBotService 单例"""
    global _service
    if _service is None:
        from app.config.manager import DATA_DIR
        config_path = Path(DATA_DIR) / "telegram_bot.json"
        _service = TelegramBotService(config_path)
    return _service


# ===== 便捷函数 =====

async def notify_telegram(title: str, message: str, level: str = "info") -> int:
    """通过 Telegram Bot 发送通知（广播到所有允许的 chat_id）"""
    service = get_telegram_bot_service()
    if not service.config.enabled:
        return 0
    emoji = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
    }.get(level, "📢")
    text = f"{emoji} *{title}*\n\n{message}"
    return await service.broadcast(text)
