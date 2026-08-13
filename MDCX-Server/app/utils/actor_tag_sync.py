"""
演员自动标签同步工具（v3.5）

将刮削器提取到的荣誉/风格标签（AV联盟 タグ、Wiki 受賞歴 等）写入 actor_tags 表，
统一以 is_user=False 区分手动标签（手动标签 API 写入 is_user=True）。

供以下调用方复用：
- actors.py 批量刮削 /scrape-profiles/batch
- modules.py 单/批量模块演员刮削
- actor_profile_enrich_scanner.py 后台自动补全扫描器
"""
import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)

# 自动标签统一底色（暗金色，示意"荣誉/排行"），与手动标签默认无色区分
AUTO_TAG_COLOR = "#B8860B"


async def sync_auto_actor_tags(session, ActorTag, actor_id: int, tags) -> list[str]:
    """将刮削标签写入 actor_tags（去重、is_user=False），返回新写入的标签名列表。

    仅 flush（使新增对象获得 id），不 commit，由调用方在事务块内统一 commit。
    调用方应自行 try/except 包裹（并发场景下唯一约束冲突时忽略即可）。
    """
    if not tags:
        return []

    inserted: list[str] = []
    for raw in tags:
        if raw is None:
            continue
        name = str(raw).strip()
        if not name or len(name) > 50:
            continue

        existing = await session.execute(
            select(ActorTag).where(ActorTag.actor_id == actor_id, ActorTag.name == name)
        )
        if existing.scalars().first():
            continue

        tag = ActorTag(
            actor_id=actor_id,
            name=name,
            color=AUTO_TAG_COLOR,
            is_user=False,
        )
        session.add(tag)
        inserted.append(name)

    if inserted:
        await session.flush()
        logger.info(f"演员 {actor_id} 写入 {len(inserted)} 个自动标签: {inserted}")
    return inserted
