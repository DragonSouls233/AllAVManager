"""
Webhook 输出管理器

提供多渠道 Webhook 配置 CRUD、事件订阅、并发发送、历史记录。
作为现有 app/utils/webhook.py 的增强版，新增：
- Bark 支持
- 多 Webhook 配置持久化
- 事件订阅路由
- 发送历史记录

事件类型：
- scrape.complete      刮削完成
- scrape.batch_done    批量刮削完成
- import.complete      导入完成
- system.error         系统错误
- player.play          播放
- custom               自定义

配置文件：data/webhooks.json
历史文件：data/webhook_history.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# ===== 枚举 =====

class WebhookChannel(str, Enum):
    """Webhook 渠道"""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    BARK = "bark"
    WECHAT = "wechat"        # 企业微信
    CUSTOM = "custom"


class EventLevel(str, Enum):
    """事件级别"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


# 默认支持的事件类型
SUPPORTED_EVENTS = [
    "scrape.complete",
    "scrape.batch_done",
    "import.complete",
    "system.error",
    "player.play",
    "custom",
]


# ===== 数据模型 =====

@dataclass
class WebhookConfig:
    """单个 Webhook 配置"""
    id: str                                      # 唯一 ID
    name: str                                    # 显示名称
    channel: WebhookChannel                      # 渠道
    url: str = ""                                # Webhook URL（custom/wechat/discord 必填）
    token: str = ""                              # Telegram Bot Token / Bark 设备 Key
    chat_id: str = ""                            # Telegram Chat ID
    bark_server: str = ""                        # Bark 自建服务器（默认 https://api.day.app）
    enabled: bool = True
    events: list[str] = field(default_factory=lambda: ["custom"])  # 订阅的事件
    timeout: int = 30
    extra: dict = field(default_factory=dict)    # 额外参数（颜色、头像等）

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "channel": self.channel.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WebhookConfig":
        # 兼容 channel 字符串
        channel = data.get("channel", "custom")
        if isinstance(channel, str):
            try:
                channel = WebhookChannel(channel)
            except ValueError:
                channel = WebhookChannel.CUSTOM
        return cls(
            id=data.get("id") or str(uuid.uuid4())[:8],
            name=data.get("name", ""),
            channel=channel,
            url=data.get("url", ""),
            token=data.get("token", ""),
            chat_id=data.get("chat_id", ""),
            bark_server=data.get("bark_server", "https://api.day.app"),
            enabled=data.get("enabled", True),
            events=data.get("events", ["custom"]),
            timeout=data.get("timeout", 30),
            extra=data.get("extra", {}),
        )


@dataclass
class NotificationEvent:
    """通知事件"""
    event: str                              # 事件类型
    title: str
    message: str
    level: EventLevel = EventLevel.INFO
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SendRecord:
    """发送历史记录"""
    id: str
    webhook_id: str
    webhook_name: str
    channel: str
    event: str
    title: str
    success: bool
    error: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# ===== Webhook 管理器 =====

class WebhookManager:
    """
    Webhook 管理器

    - 多 Webhook CRUD（持久化到 data/webhooks.json）
    - 事件路由（按订阅事件触发）
    - 并发发送（asyncio.gather）
    - 发送历史记录（最近 200 条）
    """

    MAX_HISTORY = 200

    def __init__(self, data_dir: Path):
        """
        Args:
            data_dir: 数据目录，用于存放 webhooks.json 和 webhook_history.json
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._config_file = self.data_dir / "webhooks.json"
        self._history_file = self.data_dir / "webhook_history.json"

        self._webhooks: dict[str, WebhookConfig] = {}
        self._history: list[SendRecord] = []
        self._load()

    # ===== 持久化 =====

    def _load(self) -> None:
        """加载配置和历史"""
        if self._config_file.exists():
            try:
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                for item in data.get("webhooks", []):
                    cfg = WebhookConfig.from_dict(item)
                    self._webhooks[cfg.id] = cfg
            except Exception as e:
                logger.error(f"加载 webhook 配置失败: {e}")

        if self._history_file.exists():
            try:
                data = json.loads(self._history_file.read_text(encoding="utf-8"))
                for item in data.get("records", []):
                    self._history.append(SendRecord(
                        id=item.get("id", ""),
                        webhook_id=item.get("webhook_id", ""),
                        webhook_name=item.get("webhook_name", ""),
                        channel=item.get("channel", ""),
                        event=item.get("event", ""),
                        title=item.get("title", ""),
                        success=item.get("success", False),
                        error=item.get("error", ""),
                        timestamp=item.get("timestamp", 0),
                    ))
            except Exception as e:
                logger.error(f"加载 webhook 历史失败: {e}")

    def _save_config(self) -> None:
        try:
            self._config_file.write_text(
                json.dumps(
                    {"webhooks": [w.to_dict() for w in self._webhooks.values()]},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"保存 webhook 配置失败: {e}")

    def _save_history(self) -> None:
        try:
            self._history_file.write_text(
                json.dumps(
                    {"records": [r.to_dict() for r in self._history]},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"保存 webhook 历史失败: {e}")

    # ===== CRUD =====

    def list_webhooks(self) -> list[WebhookConfig]:
        return list(self._webhooks.values())

    def get_webhook(self, webhook_id: str) -> Optional[WebhookConfig]:
        return self._webhooks.get(webhook_id)

    def add_webhook(self, config: WebhookConfig) -> WebhookConfig:
        if not config.id:
            config.id = str(uuid.uuid4())[:8]
        self._webhooks[config.id] = config
        self._save_config()
        return config

    def update_webhook(self, webhook_id: str, data: dict) -> Optional[WebhookConfig]:
        cfg = self._webhooks.get(webhook_id)
        if cfg is None:
            return None
        # 更新字段
        for key in ("name", "url", "token", "chat_id", "bark_server",
                    "enabled", "events", "timeout", "extra"):
            if key in data:
                setattr(cfg, key, data[key])
        if "channel" in data:
            try:
                cfg.channel = WebhookChannel(data["channel"])
            except ValueError:
                pass
        self._save_config()
        return cfg

    def delete_webhook(self, webhook_id: str) -> bool:
        if webhook_id not in self._webhooks:
            return False
        del self._webhooks[webhook_id]
        self._save_config()
        return True

    # ===== 发送 =====

    async def send_to_webhook(
        self, webhook_id: str, event: NotificationEvent
    ) -> tuple[bool, str]:
        """发送到指定 Webhook"""
        cfg = self._webhooks.get(webhook_id)
        if cfg is None:
            return False, "webhook 不存在"
        if not cfg.enabled:
            return False, "webhook 已禁用"
        success, err = await self._dispatch(cfg, event)
        self._record(cfg, event, success, err)
        return success, err

    async def broadcast(self, event: NotificationEvent) -> int:
        """
        广播事件到所有订阅了该事件且已启用的 Webhook

        Returns:
            成功发送的数量
        """
        targets = [
            cfg for cfg in self._webhooks.values()
            if cfg.enabled and event.event in cfg.events
        ]
        if not targets:
            return 0

        tasks = [self._dispatch(cfg, event) for cfg in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        for cfg, result in zip(targets, results):
            if isinstance(result, Exception):
                self._record(cfg, event, False, str(result))
            else:
                success, err = result
                self._record(cfg, event, success, err)
                if success:
                    success_count += 1
        return success_count

    async def _dispatch(
        self, cfg: WebhookConfig, event: NotificationEvent
    ) -> tuple[bool, str]:
        """根据渠道分发"""
        try:
            if cfg.channel == WebhookChannel.TELEGRAM:
                return await self._send_telegram(cfg, event)
            if cfg.channel == WebhookChannel.DISCORD:
                return await self._send_discord(cfg, event)
            if cfg.channel == WebhookChannel.BARK:
                return await self._send_bark(cfg, event)
            if cfg.channel == WebhookChannel.WECHAT:
                return await self._send_wechat(cfg, event)
            return await self._send_custom(cfg, event)
        except Exception as e:
            return False, str(e)

    # ===== 各渠道发送实现 =====

    async def _send_telegram(
        self, cfg: WebhookConfig, event: NotificationEvent
    ) -> tuple[bool, str]:
        if not cfg.token or not cfg.chat_id:
            return False, "缺少 token 或 chat_id"
        emoji = self._level_emoji(event.level)
        text = f"{emoji} *{event.title}*\n\n{event.message}"
        url = f"https://api.telegram.org/bot{cfg.token}/sendMessage"
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(url, json={
                "chat_id": cfg.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
            resp.raise_for_status()
        return True, ""

    async def _send_discord(
        self, cfg: WebhookConfig, event: NotificationEvent
    ) -> tuple[bool, str]:
        if not cfg.url:
            return False, "缺少 webhook url"
        color = self._level_color(event.level)
        embed = {
            "title": event.title,
            "description": event.message,
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event.timestamp)),
        }
        # 附加数据
        if event.data:
            embed["fields"] = [
                {"name": k, "value": str(v)[:1024], "inline": True}
                for k, v in list(event.data.items())[:10]
            ]
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(cfg.url, json={"embeds": [embed]})
            resp.raise_for_status()
        return True, ""

    async def _send_bark(
        self, cfg: WebhookConfig, event: NotificationEvent
    ) -> tuple[bool, str]:
        """
        Bark 推送（iOS 通知）
        URL 格式：https://api.day.app/{key}/{title}/{body}
        或 POST JSON：https://api.day.app/{key} {body}
        """
        if not cfg.token:
            return False, "缺少 bark 设备 key"
        server = (cfg.bark_server or "https://api.day.app").rstrip("/")
        url = f"{server}/{cfg.token}"
        payload = {
            "title": event.title,
            "body": event.message,
            "level": "active",  # timeSensitive / active / passive
            "group": "MDCX",
        }
        # 级别映射
        level_map = {
            EventLevel.INFO: "active",
            EventLevel.SUCCESS: "active",
            EventLevel.WARNING: "timeSensitive",
            EventLevel.ERROR: "timeSensitive",
        }
        payload["level"] = level_map.get(event.level, "active")

        # 自定义图标/声音（在 extra 中）
        if "icon" in cfg.extra:
            payload["icon"] = cfg.extra["icon"]
        if "sound" in cfg.extra:
            payload["sound"] = cfg.extra["sound"]
        if "url" in cfg.extra:
            payload["url"] = cfg.extra["url"]

        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                return False, data.get("message", "Bark 返回错误")
        return True, ""

    async def _send_wechat(
        self, cfg: WebhookConfig, event: NotificationEvent
    ) -> tuple[bool, str]:
        if not cfg.url:
            return False, "缺少企业微信 webhook url"
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### {event.title}\n\n{event.message}"
            },
        }
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(cfg.url, json=data)
            resp.raise_for_status()
        return True, ""

    async def _send_custom(
        self, cfg: WebhookConfig, event: NotificationEvent
    ) -> tuple[bool, str]:
        if not cfg.url:
            return False, "缺少 webhook url"
        payload = {
            "event": event.event,
            "title": event.title,
            "message": event.message,
            "level": event.level.value,
            "timestamp": event.timestamp,
            "data": event.data,
        }
        headers = {"Content-Type": "application/json"}
        # 自定义签名头（在 extra 中）
        for k, v in cfg.extra.items():
            if k.startswith("X-"):
                headers[k] = str(v)
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(cfg.url, json=payload, headers=headers)
            resp.raise_for_status()
        return True, ""

    # ===== 辅助 =====

    def _level_emoji(self, level: EventLevel) -> str:
        return {
            EventLevel.INFO: "ℹ️",
            EventLevel.SUCCESS: "✅",
            EventLevel.WARNING: "⚠️",
            EventLevel.ERROR: "❌",
        }.get(level, "📢")

    def _level_color(self, level: EventLevel) -> int:
        return {
            EventLevel.INFO: 0x3498db,
            EventLevel.SUCCESS: 0x2ecc71,
            EventLevel.WARNING: 0xf39c12,
            EventLevel.ERROR: 0xe74c3c,
        }.get(level, 0x95a5a6)

    def _record(
        self,
        cfg: WebhookConfig,
        event: NotificationEvent,
        success: bool,
        error: str,
    ) -> None:
        record = SendRecord(
            id=str(uuid.uuid4())[:8],
            webhook_id=cfg.id,
            webhook_name=cfg.name,
            channel=cfg.channel.value,
            event=event.event,
            title=event.title,
            success=success,
            error=error,
        )
        self._history.append(record)
        # 限制历史长度
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]
        self._save_history()

    # ===== 历史 =====

    def list_history(
        self, webhook_id: Optional[str] = None, limit: int = 50
    ) -> list[SendRecord]:
        records = self._history
        if webhook_id:
            records = [r for r in records if r.webhook_id == webhook_id]
        # 倒序，最新的在前
        return list(reversed(records[-limit:]))

    def clear_history(self) -> int:
        count = len(self._history)
        self._history.clear()
        self._save_history()
        return count

    # ===== 测试发送 =====

    async def test_webhook(self, webhook_id: str) -> tuple[bool, str]:
        """发送一条测试通知"""
        cfg = self._webhooks.get(webhook_id)
        if cfg is None:
            return False, "webhook 不存在"
        event = NotificationEvent(
            event="custom",
            title=f"MDCX 测试通知",
            message=f"这是来自 MDCX 的测试通知，渠道：{cfg.channel.value}，名称：{cfg.name}",
            level=EventLevel.INFO,
        )
        return await self.send_to_webhook(webhook_id, event)


# ===== 全局单例 =====

_manager: Optional[WebhookManager] = None


def get_webhook_manager() -> WebhookManager:
    """获取全局 WebhookManager 单例"""
    global _manager
    if _manager is None:
        from app.config.manager import DATA_DIR
        _manager = WebhookManager(Path(DATA_DIR))
    return _manager


# ===== 便捷函数（供业务代码调用） =====

async def notify_event(
    event: str,
    title: str,
    message: str,
    level: str = "info",
    data: Optional[dict] = None,
) -> int:
    """
    触发事件通知（广播到所有订阅该事件且已启用的 Webhook）

    Args:
        event: 事件类型（如 scrape.complete）
        title: 标题
        message: 消息内容
        level: 级别（info/success/warning/error）
        data: 附加数据

    Returns:
        成功发送的 Webhook 数量
    """
    try:
        level_enum = EventLevel(level)
    except ValueError:
        level_enum = EventLevel.INFO

    evt = NotificationEvent(
        event=event,
        title=title,
        message=message,
        level=level_enum,
        data=data or {},
    )
    return await get_webhook_manager().broadcast(evt)
