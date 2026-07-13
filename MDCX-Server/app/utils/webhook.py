"""
Webhook 通知

支持：
- Telegram
- Discord
- 企业微信
- 自定义 Webhook
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class WebhookType(str, Enum):
    """Webhook 类型"""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    WECHAT = "wechat"
    CUSTOM = "custom"


@dataclass
class WebhookConfig:
    """Webhook 配置"""
    type: WebhookType
    url: str                    # Webhook URL
    token: Optional[str] = None # Telegram Bot Token
    chat_id: Optional[str] = None  # Telegram Chat ID
    enabled: bool = True
    timeout: int = 30


@dataclass
class Notification:
    """通知消息"""
    title: str
    message: str
    level: str = "info"  # info/warning/error/success
    data: Optional[dict] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class WebhookNotifier:
    """
    Webhook 通知器
    
    支持多种通知渠道
    """
    
    def __init__(self, config: WebhookConfig):
        """
        初始化
        
        Args:
            config: Webhook 配置
        """
        self.config = config
        self.type = config.type
    
    async def send(self, notification: Notification) -> bool:
        """
        发送通知
        
        Args:
            notification: 通知消息
            
        Returns:
            是否成功
        """
        if not self.config.enabled:
            return False
        
        try:
            if self.type == WebhookType.TELEGRAM:
                return await self._send_telegram(notification)
            elif self.type == WebhookType.DISCORD:
                return await self._send_discord(notification)
            elif self.type == WebhookType.WECHAT:
                return await self._send_wechat(notification)
            elif self.type == WebhookType.CUSTOM:
                return await self._send_custom(notification)
            else:
                logger.warning(f"Unknown webhook type: {self.type}")
                return False
        
        except Exception as e:
            logger.error(f"Webhook send error: {e}")
            return False
    
    async def _send_telegram(self, notification: Notification) -> bool:
        """发送到 Telegram"""
        if not self.config.token or not self.config.chat_id:
            logger.warning("Telegram token or chat_id not configured")
            return False
        
        # 构建消息
        emoji = self._get_emoji(notification.level)
        text = f"{emoji} *{notification.title}*\n\n{notification.message}"
        
        # 发送请求
        url = f"https://api.telegram.org/bot{self.config.token}/sendMessage"
        
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": self.config.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            response.raise_for_status()
            logger.info(f"Sent Telegram notification: {notification.title}")
            return True
    
    async def _send_discord(self, notification: Notification) -> bool:
        """发送到 Discord"""
        # 构建嵌入消息
        color = self._get_color(notification.level)
        
        embed = {
            "title": notification.title,
            "description": notification.message,
            "color": color,
            "timestamp": notification.timestamp.isoformat(),
        }
        
        # 发送请求
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                self.config.url,
                json={"embeds": [embed]},
            )
            response.raise_for_status()
            logger.info(f"Sent Discord notification: {notification.title}")
            return True
    
    async def _send_wechat(self, notification: Notification) -> bool:
        """发送到企业微信"""
        # 构建消息
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"# {notification.title}\n\n{notification.message}"
            }
        }
        
        # 发送请求
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                self.config.url,
                json=data,
            )
            response.raise_for_status()
            logger.info(f"Sent WeChat notification: {notification.title}")
            return True
    
    async def _send_custom(self, notification: Notification) -> bool:
        """发送到自定义 Webhook"""
        data = {
            "title": notification.title,
            "message": notification.message,
            "level": notification.level,
            "timestamp": notification.timestamp.isoformat(),
            "data": notification.data,
        }
        
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                self.config.url,
                json=data,
            )
            response.raise_for_status()
            logger.info(f"Sent custom webhook: {notification.title}")
            return True
    
    def _get_emoji(self, level: str) -> str:
        """获取表情符号"""
        emojis = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        return emojis.get(level, "📢")
    
    def _get_color(self, level: str) -> int:
        """获取颜色（Discord）"""
        colors = {
            "info": 0x3498db,      # 蓝色
            "warning": 0xf39c12,   # 橙色
            "error": 0xe74c3c,     # 红色
            "success": 0x2ecc71,   # 绿色
        }
        return colors.get(level, 0x95a5a6)


class NotificationService:
    """
    通知服务
    
    管理多个 Webhook，统一发送通知
    """
    
    def __init__(self):
        self.notifiers: list[WebhookNotifier] = []
    
    def add_notifier(self, config: WebhookConfig):
        """添加通知器"""
        self.notifiers.append(WebhookNotifier(config))
    
    async def notify(self, notification: Notification):
        """
        发送通知到所有渠道
        
        Args:
            notification: 通知消息
        """
        for notifier in self.notifiers:
            try:
                await notifier.send(notification)
            except Exception as e:
                logger.error(f"Notifier error: {e}")
    
    async def notify_scrape_complete(
        self,
        code: str,
        title: str,
        success: bool,
        message: str = "",
    ):
        """刮削完成通知"""
        notification = Notification(
            title=f"刮削{'成功' if success else '失败'}: {code}",
            message=f"标题: {title}\n{message}",
            level="success" if success else "error",
        )
        await self.notify(notification)
    
    async def notify_batch_complete(
        self,
        total: int,
        success: int,
        failed: int,
    ):
        """批量刮削完成通知"""
        notification = Notification(
            title="批量刮削完成",
            message=f"总数: {total}\n成功: {success}\n失败: {failed}",
            level="success" if failed == 0 else "warning",
        )
        await self.notify(notification)


# 全局通知服务实例
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """获取通知服务实例"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


async def send_notification(
    title: str,
    message: str,
    level: str = "info",
):
    """发送通知的便捷函数"""
    service = get_notification_service()
    notification = Notification(
        title=title,
        message=message,
        level=level,
    )
    await service.notify(notification)
