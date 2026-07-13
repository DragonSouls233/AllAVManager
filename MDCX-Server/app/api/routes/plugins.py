"""插件系统路由

提供插件管理、配置、热重载能力，以及 Webhook 输出管理。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from app.services.plugin_manager import (
    PluginManager, PluginType, PluginStatus,
    get_plugin_manager,
)
from app.services.plugin_loader_crawler import (
    register_crawler_plugins, unregister_all_crawler_plugins,
    unregister_crawler_plugin,
)
from app.services.plugin_loader_translate import list_translator_plugins
from app.services.plugin_loader_organizer import list_organizer_plugins
from app.services.webhook_manager import (
    WebhookManager, WebhookConfig, WebhookChannel, EventLevel,
    SUPPORTED_EVENTS,
    get_webhook_manager, notify_event,
)

router = APIRouter()


# ===== 通用响应 =====

def _entry_to_dict(entry) -> dict:
    return {
        "name": entry.meta.name,
        "plugin_type": entry.meta.plugin_type.value,
        "display_name": entry.meta.display_name,
        "version": entry.meta.version,
        "author": entry.meta.author,
        "description": entry.meta.description,
        "homepage": entry.meta.homepage,
        "requires": entry.meta.requires,
        "status": entry.status.value,
        "enabled": entry.status == PluginStatus.ENABLED,
        "error": entry.error,
        "loaded_at": entry.loaded_at,
        "file_path": entry.file_path,
    }


# ===== 插件管理 =====

@router.get("/list")
async def list_plugins(plugin_type: Optional[str] = None):
    """列出所有插件"""
    manager = get_plugin_manager()
    if plugin_type:
        try:
            pt = PluginType(plugin_type)
        except ValueError:
            raise HTTPException(400, f"无效的插件类型: {plugin_type}")
        entries = manager.list_plugins(pt)
    else:
        entries = manager.list_plugins()
    return {"items": [_entry_to_dict(e) for e in entries]}


@router.get("/{plugin_type}/{name}")
async def get_plugin_detail(plugin_type: str, name: str):
    """获取插件详情（含配置 + schema）"""
    try:
        pt = PluginType(plugin_type)
    except ValueError:
        raise HTTPException(400, "无效的插件类型")
    manager = get_plugin_manager()
    entry = manager.get_plugin(pt, name)
    if entry is None:
        raise HTTPException(404, "插件不存在")
    return {
        "info": _entry_to_dict(entry),
        "config": manager.get_plugin_config(pt, name),
        "config_schema": manager.get_config_schema(pt, name),
        "source_code": _read_source_code(entry.file_path),
    }


def _read_source_code(file_path: str) -> str:
    """读取插件源码（限制 50KB）"""
    try:
        from pathlib import Path
        p = Path(file_path)
        if not p.exists():
            return ""
        size = p.stat().st_size
        if size > 50 * 1024:
            return f"# 文件过大（{size} 字节），不显示"
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"# 读取失败: {e}"


@router.post("/{plugin_type}/{name}/enable")
async def enable_plugin(plugin_type: str, name: str):
    """启用插件"""
    try:
        pt = PluginType(plugin_type)
    except ValueError:
        raise HTTPException(400, "无效的插件类型")
    manager = get_plugin_manager()
    try:
        manager.enable(pt, name)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    # 爬虫插件需要重新注册到 Provider
    if pt == PluginType.CRAWLER:
        unregister_all_crawler_plugins()
        register_crawler_plugins()
    return {"ok": True}


@router.post("/{plugin_type}/{name}/disable")
async def disable_plugin(plugin_type: str, name: str):
    """禁用插件"""
    try:
        pt = PluginType(plugin_type)
    except ValueError:
        raise HTTPException(400, "无效的插件类型")
    manager = get_plugin_manager()
    try:
        manager.disable(pt, name)
    except KeyError as e:
        raise HTTPException(404, str(e))
    if pt == PluginType.CRAWLER:
        unregister_crawler_plugin(name)
    return {"ok": True}


@router.post("/{plugin_type}/{name}/reload")
async def reload_plugin(plugin_type: str, name: str):
    """重载插件"""
    try:
        pt = PluginType(plugin_type)
    except ValueError:
        raise HTTPException(400, "无效的插件类型")
    manager = get_plugin_manager()
    try:
        entry = manager.reload(pt, name)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    if pt == PluginType.CRAWLER:
        unregister_all_crawler_plugins()
        register_crawler_plugins()
    return {"info": _entry_to_dict(entry)}


@router.post("/reload-all")
async def reload_all_plugins():
    """重新扫描并加载所有插件"""
    manager = get_plugin_manager()
    # 先卸载所有爬虫插件
    unregister_all_crawler_plugins()
    # 重新扫描加载
    count = manager.discover_all()
    # 重新注册爬虫插件
    crawler_count = register_crawler_plugins()
    return {
        "loaded": count,
        "crawler_registered": crawler_count,
        "items": [_entry_to_dict(e) for e in manager.list_plugins()],
    }


class ConfigUpdate(BaseModel):
    config: dict


@router.put("/{plugin_type}/{name}/config")
async def update_plugin_config(plugin_type: str, name: str, body: ConfigUpdate):
    """更新插件配置"""
    try:
        pt = PluginType(plugin_type)
    except ValueError:
        raise HTTPException(400, "无效的插件类型")
    manager = get_plugin_manager()
    try:
        manager.update_plugin_config(pt, name, body.config)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


# ===== 模板创建 =====

class CreateTemplateRequest(BaseModel):
    plugin_type: str       # crawler / translator / organizer / notifier
    name: str
    force: bool = False


@router.post("/create-template")
async def create_template(body: CreateTemplateRequest):
    """创建示例插件文件"""
    try:
        pt = PluginType(body.plugin_type)
    except ValueError:
        raise HTTPException(400, "无效的插件类型")
    manager = get_plugin_manager()
    try:
        path = manager.create_template(pt, body.name, force=body.force)
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    # 立即加载
    try:
        manager._load_file(path, pt)
    except Exception as e:
        # 加载失败也返回路径，用户可编辑后重载
        return {"file_path": str(path), "loaded": False, "error": str(e)}
    return {"file_path": str(path), "loaded": True}


@router.delete("/{plugin_type}/{name}")
async def delete_plugin(plugin_type: str, name: str):
    """删除插件文件"""
    try:
        pt = PluginType(plugin_type)
    except ValueError:
        raise HTTPException(400, "无效的插件类型")
    manager = get_plugin_manager()
    if pt == PluginType.CRAWLER:
        unregister_crawler_plugin(name)
    try:
        manager.delete_plugin_file(pt, name)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True}


# ===== 类型快捷查询 =====

@router.get("/translators")
async def list_translators():
    """列出翻译插件"""
    return {"items": list_translator_plugins()}


@router.get("/organizers")
async def list_organizers():
    """列出整理插件"""
    return {"items": list_organizer_plugins()}


# ===== Webhook 管理 =====

class WebhookCreate(BaseModel):
    name: str
    channel: str            # telegram / discord / bark / wechat / custom
    url: str = ""
    token: str = ""
    chat_id: str = ""
    bark_server: str = "https://api.day.app"
    enabled: bool = True
    events: list[str] = ["custom"]
    timeout: int = 30
    extra: dict = {}


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    url: Optional[str] = None
    token: Optional[str] = None
    chat_id: Optional[str] = None
    bark_server: Optional[str] = None
    enabled: Optional[bool] = None
    events: Optional[list[str]] = None
    timeout: Optional[int] = None
    extra: Optional[dict] = None


class TestSendRequest(BaseModel):
    title: str = "MDCX 测试通知"
    message: str = "测试消息内容"
    level: str = "info"
    event: str = "custom"


@router.get("/webhooks")
async def list_webhooks():
    """列出所有 Webhook"""
    manager = get_webhook_manager()
    return {
        "items": [w.to_dict() for w in manager.list_webhooks()],
        "supported_channels": [c.value for c in WebhookChannel],
        "supported_events": SUPPORTED_EVENTS,
        "supported_levels": [l.value for l in EventLevel],
    }


@router.post("/webhooks")
async def create_webhook(body: WebhookCreate):
    """创建 Webhook"""
    manager = get_webhook_manager()
    cfg = WebhookConfig(
        id="",
        name=body.name,
        channel=WebhookChannel(body.channel) if body.channel in [c.value for c in WebhookChannel] else WebhookChannel.CUSTOM,
        url=body.url,
        token=body.token,
        chat_id=body.chat_id,
        bark_server=body.bark_server,
        enabled=body.enabled,
        events=body.events,
        timeout=body.timeout,
        extra=body.extra,
    )
    cfg = manager.add_webhook(cfg)
    return cfg.to_dict()


@router.put("/webhooks/{webhook_id}")
async def update_webhook(webhook_id: str, body: WebhookUpdate):
    """更新 Webhook"""
    manager = get_webhook_manager()
    data = body.model_dump(exclude_none=True)
    cfg = manager.update_webhook(webhook_id, data)
    if cfg is None:
        raise HTTPException(404, "Webhook 不存在")
    return cfg.to_dict()


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str):
    """删除 Webhook"""
    manager = get_webhook_manager()
    if not manager.delete_webhook(webhook_id):
        raise HTTPException(404, "Webhook 不存在")
    return {"ok": True}


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str):
    """测试 Webhook（发送测试通知）"""
    manager = get_webhook_manager()
    try:
        success, msg = await manager.test_webhook(webhook_id)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"success": success, "message": msg}


class BroadcastRequest(BaseModel):
    event: str
    title: str
    message: str
    level: str = "info"
    data: Optional[dict] = None


@router.post("/webhooks/broadcast")
async def broadcast_event(body: BroadcastRequest):
    """广播事件到所有订阅的 Webhook"""
    count = await notify_event(
        event=body.event,
        title=body.title,
        message=body.message,
        level=body.level,
        data=body.data,
    )
    return {"sent": count}


@router.get("/webhooks/history")
async def webhook_history(webhook_id: Optional[str] = None, limit: int = 50):
    """获取 Webhook 发送历史"""
    manager = get_webhook_manager()
    records = manager.list_history(webhook_id=webhook_id, limit=limit)
    return {"items": [r.to_dict() for r in records]}


@router.delete("/webhooks/history")
async def clear_webhook_history():
    """清空 Webhook 历史"""
    manager = get_webhook_manager()
    count = manager.clear_history()
    return {"cleared": count}
