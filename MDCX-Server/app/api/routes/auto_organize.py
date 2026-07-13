"""
自动整理规则 API 路由（v4.1 B1）

提供 AutoOrganizeRule 的 CRUD 端点与手动触发检查：

- GET    /auto-organize/rules          — 列出所有规则
- POST   /auto-organize/rules          — 创建规则
- PUT    /auto-organize/rules/{rule_id} — 更新规则
- DELETE /auto-organize/rules/{rule_id} — 删除规则
- POST   /auto-organize/check          — 手动触发一次自动整理检查
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import AutoOrganizeRule
from app.services.file_organize import auto_organize_watched

router = APIRouter()


# ============================================
# 请求/响应模型
# ============================================

class RuleCreate(BaseModel):
    """创建自动整理规则请求"""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    condition_field: str = Field(..., max_length=50, description="条件字段（如 play_count / view_status / maker 等）")
    condition_op: str = Field(..., max_length=20, description="条件操作符（eq/ne/contains/gt/lt/ge/le/regex/in）")
    condition_value: str = Field(..., max_length=500, description="条件值")
    action: str = Field("move", max_length=50, description="动作（move/copy/hardlink/symlink）")
    target_path: str | None = Field(None, max_length=1000, description="目标路径")
    enabled: bool = Field(True, description="是否启用")


class RuleUpdate(BaseModel):
    """更新自动整理规则请求（所有字段可选）"""
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    condition_field: str | None = Field(None, max_length=50)
    condition_op: str | None = Field(None, max_length=20)
    condition_value: str | None = Field(None, max_length=500)
    action: str | None = Field(None, max_length=50)
    target_path: str | None = Field(None, max_length=1000)
    enabled: bool | None = Field(None)


class RuleResponse(BaseModel):
    """规则响应"""
    id: int
    name: str
    condition_field: str
    condition_op: str
    condition_value: str
    action: str
    target_path: str | None = None
    enabled: bool
    created_at: str | None = None


def _to_response(rule: AutoOrganizeRule) -> dict:
    """把 ORM 对象转为响应 dict"""
    return {
        "id": rule.id,
        "name": rule.name,
        "condition_field": rule.condition_field,
        "condition_op": rule.condition_op,
        "condition_value": rule.condition_value,
        "action": rule.action,
        "target_path": rule.target_path,
        "enabled": rule.enabled,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


# ============================================
# 路由
# ============================================

@router.get("/rules", summary="列出所有自动整理规则")
async def list_rules(session: AsyncSession = Depends(get_session)):
    """列出所有自动整理规则"""
    stmt = select(AutoOrganizeRule).order_by(AutoOrganizeRule.id.asc())
    rules = (await session.execute(stmt)).scalars().all()
    return {"total": len(rules), "items": [_to_response(r) for r in rules]}


@router.post("/rules", summary="创建自动整理规则")
async def create_rule(body: RuleCreate, session: AsyncSession = Depends(get_session)):
    """创建一条自动整理规则"""
    rule = AutoOrganizeRule(
        name=body.name,
        condition_field=body.condition_field,
        condition_op=body.condition_op,
        condition_value=body.condition_value,
        action=body.action,
        target_path=body.target_path,
        enabled=body.enabled,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _to_response(rule)


@router.put("/rules/{rule_id}", summary="更新自动整理规则")
async def update_rule(
    rule_id: int,
    body: RuleUpdate,
    session: AsyncSession = Depends(get_session),
):
    """更新一条自动整理规则（仅更新传入的字段）"""
    rule = await session.get(AutoOrganizeRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)

    await session.commit()
    await session.refresh(rule)
    return _to_response(rule)


@router.delete("/rules/{rule_id}", summary="删除自动整理规则")
async def delete_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    """删除一条自动整理规则"""
    rule = await session.get(AutoOrganizeRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")

    await session.delete(rule)
    await session.commit()
    return {"ok": True, "deleted_id": rule_id}


@router.post("/check", summary="手动触发一次自动整理检查")
async def check_now(session: AsyncSession = Depends(get_session)):
    """手动触发一次自动整理检查

    遍历所有启用的规则，将命中的影片按规则动作整理到目标路径。
    """
    try:
        result = await auto_organize_watched(session)
        result["triggered_at"] = datetime.now().isoformat()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自动整理检查失败: {e}")
