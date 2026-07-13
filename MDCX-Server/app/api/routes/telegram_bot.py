"""Telegram Bot 路由"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.telegram_bot import get_telegram_bot_service

router = APIRouter()


class UpdateConfigRequest(BaseModel):
    bot_token: str | None = None
    allowed_chat_ids: list[int] | None = None
    allowed_usernames: list[str] | None = None
    enabled: bool | None = None
    mode: str | None = None         # polling / webhook
    webhook_url: str | None = None
    webhook_secret: str | None = None
    language: str | None = None
    enable_inline_search: bool | None = None
    notification_events: list[str] | None = None


class SendMessageRequest(BaseModel):
    chat_id: int | str
    text: str
    parse_mode: str = "Markdown"


@router.get("/config")
async def get_config():
    """获取 Bot 配置（token 已脱敏）"""
    service = get_telegram_bot_service()
    return service.get_config()


@router.put("/config")
async def update_config(body: UpdateConfigRequest):
    """更新 Bot 配置（不会自动启动，需调用 /start）"""
    service = get_telegram_bot_service()
    data = body.model_dump(exclude_none=True)
    # webhook_secret 为空字符串表示用户想清除
    if "webhook_secret" in data and not data["webhook_secret"]:
        data["webhook_secret"] = ""
    cfg = service.update_config(data)
    return cfg


@router.get("/status")
async def status():
    """获取 Bot 运行状态"""
    service = get_telegram_bot_service()
    return service.get_status()


@router.post("/start")
async def start_bot():
    """启动 Bot"""
    service = get_telegram_bot_service()
    ok = await service.start()
    if not ok:
        raise HTTPException(400, "启动失败，请检查 bot_token 和 enabled 配置")
    return {"ok": True, "status": service.get_status()}


@router.post("/stop")
async def stop_bot():
    """停止 Bot"""
    service = get_telegram_bot_service()
    await service.stop()
    return {"ok": True, "status": service.get_status()}


@router.post("/restart")
async def restart_bot():
    """重启 Bot"""
    service = get_telegram_bot_service()
    ok = await service.restart()
    return {"ok": ok, "status": service.get_status()}


@router.post("/send")
async def send_message(body: SendMessageRequest):
    """主动发送消息到指定 chat_id"""
    service = get_telegram_bot_service()
    try:
        result = await service.send_message(body.chat_id, body.text, body.parse_mode)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(500, str(e))


class BroadcastRequest(BaseModel):
    text: str
    parse_mode: str = "Markdown"


@router.post("/broadcast")
async def broadcast(body: BroadcastRequest):
    """广播到所有 allowed_chat_ids"""
    service = get_telegram_bot_service()
    count = await service.broadcast(body.text, body.parse_mode)
    return {"sent": count}


@router.post("/delete-webhook")
async def delete_webhook():
    """删除 Webhook（切换到 polling 时使用）"""
    service = get_telegram_bot_service()
    await service.delete_webhook()
    return {"ok": True}


# ===== Webhook 接收 update（webhook 模式） =====

@router.post("/webhook")
async def webhook_update(request: Request):
    """接收 Telegram 推送的 update（webhook 模式）"""
    service = get_telegram_bot_service()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(400, "无效的 JSON")
    result = await service.handle_webhook_update(update, secret=secret)
    if not result.get("ok"):
        raise HTTPException(403, result.get("error", "forbidden"))
    return {"ok": True}


# ===== 测试 getMe =====

@router.get("/me")
async def get_me():
    """测试 bot token 是否有效，返回 bot 信息"""
    service = get_telegram_bot_service()
    try:
        return await service._api_call("getMe")
    except Exception as e:
        raise HTTPException(400, str(e))
