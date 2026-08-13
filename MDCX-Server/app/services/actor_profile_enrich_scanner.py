"""
演员资料自动补全扫描器（对标 JavBoss ScanIdolProfiles）

背景：
- MDCX 的 Actor 模型已含完整资料字段（height/bust/waist/hip/cup/birth_date/intro/
  birthplace/alias/source_url...），且已有 ActorProfileScraper（DMM/JavWiki/AVOpen/
  AVWikiDB/Wikidata/Wikipedia/Gfriends）与 ModuleActorProfileScraper（uncensored=HEYZO、
  western=ThePornDB、fc2/pornhub=JavDB），以及手动端点 /actors/{id}/scrape-profile 与
  /actors/scrape-profiles/batch。
- 但缺少「自动化后台扫描器」：周期性找出资料缺失的演员并自动补全。本模块补齐该能力。

策略：
- 周期性扫描各模块中资料缺失的演员（height/bust/waist/hip/cup/birth_date 全空视为缺失）。
- 按模块选择合适来源补全：
  - jav / chinese / anime：统一 ActorProfileScraper（多源）
  - uncensored：ModuleActorProfileScraper -> HEYZO
  - fc2 / pornhub：ModuleActorProfileScraper -> JavDB
  - western：ModuleActorProfileScraper -> ThePornDB
- 字段级 merge：仅补充当前为空的字段，绝不覆盖已有值（与 JavBoss mergeActressInfo 一致）。
- 别名合并：补全得到的别名追加到 actor.alias（逗号分隔去重）。
- 后台 asyncio 循环，默认 24h 一轮（可在 config 覆盖），亦可手动触发。
"""
import asyncio
import json
import logging
import random
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.utils.module_helper import get_module_model, get_module_session

logger = logging.getLogger(__name__)

# 参与扫描的模块
MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub", "anime"]

# 用于判断「资料缺失」的核心字段：全部为空才视为需要补全
_MISSING_CORE_FIELDS = ["height", "bust", "waist", "hip", "cup", "birth_date"]

# 补全时会写入的字段（仅当 actor 当前为空才写入）
_PROFILE_FIELDS = [
    "name_jp", "alias", "birth_date", "age", "height", "bust",
    "waist", "hip", "cup", "birthplace", "hobby", "intro",
    "avatar_url", "source", "source_url", "zodiac", "debut_year", "social_links",
]

# 每轮每个模块最多处理的数量（分批续扫，避免单次过长）
BATCH_LIMIT = 200

# 每个演员之间的礼貌延迟（秒），避免对来源站造成压力
REQUEST_DELAY = 0.6

# 后台扫描状态
_scanner_task: Optional[asyncio.Task] = None
_scanner_running = False
_scanning = False
_last_run_at: Optional[str] = None
_last_stats: dict = {}


def _interval_seconds() -> int:
    """扫描间隔（秒），默认 24h，可由 config 覆盖。"""
    try:
        from app.config.manager import get_config_manager
        cfg = get_config_manager().config
        h = getattr(cfg, "actor_profile_enrich_interval_hours", None)
        if not h:
            h = getattr(cfg, "actor_enrich_interval_hours", None)
        if h:
            return max(3600, int(h) * 3600)
    except Exception:
        pass
    return 24 * 3600


def _is_enabled() -> bool:
    try:
        from app.config.manager import get_config_manager
        cfg = get_config_manager().config
        v = getattr(cfg, "actor_profile_enrich_enabled", None)
        if v is not None:
            return bool(v)
    except Exception:
        pass
    return True


def _merge_alias(canonical_alias: Optional[str], canonical_name: str,
                 source_aliases: list[str]) -> str:
    """合并别名（逗号分隔去重，排除 canonical 自身名称）。"""
    seen = set()
    out = []
    for item in [canonical_alias, canonical_name, *source_aliases]:
        if not item:
            continue
        for part in item.split(","):
            a = part.strip()
            if not a:
                continue
            key = a.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(a)
    return ",".join(out)


async def _scrape(module: str, name: str, name_jp: Optional[str]) -> Optional[dict]:
    """按模块选择来源刮削演员资料，返回字段字典（含 None）。"""
    lookup = name_jp or name

    # 模块专属来源（uncensored/fc2/pornhub/western）
    if module in ("fc2", "pornhub", "uncensored", "western"):
        try:
            from app.scraper.module_actor_profile import ModuleActorProfileScraper
            prof = await ModuleActorProfileScraper(module).get_profile(lookup)
            if prof and getattr(prof, "name", None):
                return asdict(prof)
        except Exception as e:
            logger.debug(f"[{module}] 模块专属来源获取失败 {lookup}: {e}")

    # 统一多源（jav/chinese/anime 以及上述模块的兜底）
    try:
        from app.scraper.actor_profile_scrapers import get_actor_profile_scraper
        prof = await get_actor_profile_scraper().get_profile(name, name_jp)
        if prof and getattr(prof, "name", None):
            return asdict(prof)
    except Exception as e:
        logger.debug(f"[{module}] 统一来源获取失败 {lookup}: {e}")

    return None


async def enrich_actor(module: str, actor, session) -> dict:
    """补全单个演员资料（字段级 merge），返回 {updated, fields}。"""
    prof = await _scrape(module, actor.name, getattr(actor, "name_jp", None))
    if not prof:
        return {"updated": False, "fields": {}}

    updates: dict = {}
    for field in _PROFILE_FIELDS:
        if not hasattr(actor, field):
            continue
        cur = getattr(actor, field, None)
        new = prof.get(field)
        if (cur is None or cur == "") and new not in (None, ""):
            updates[field] = new

    # 别名合并
    new_alias = prof.get("alias")
    if new_alias:
        merged = _merge_alias(getattr(actor, "alias", None), actor.name, [new_alias])
        if merged and merged != (getattr(actor, "alias", None) or ""):
            updates["alias"] = merged

    # 自动标签（v3.5）：AV联盟 タグ / Wiki 受賞歴 -> actor_tags（is_user=False）
    new_tags: list[str] = []
    scraped_tags = prof.get("tags")
    if scraped_tags:
        try:
            from app.utils.actor_tag_sync import sync_auto_actor_tags
            ActorTag = get_module_model(module, "actor_tag")
            new_tags = await sync_auto_actor_tags(session, ActorTag, actor.id, scraped_tags)
        except Exception as e:
            logger.debug(f"[{module}] 演员 {actor.name} 自动标签写入失败(忽略): {e}")

    if updates or new_tags:
        for f, v in updates.items():
            # social_links 列是 JSON 字符串（Text），字典需序列化后再写入
            if f == "social_links" and isinstance(v, dict):
                v = json.dumps(v, ensure_ascii=False)
            setattr(actor, f, v)
        await session.commit()
        if new_tags:
            updates["tags"] = new_tags
        logger.info(f"[{module}] 演员 {actor.name} 补全 {len(updates)} 个字段: {list(updates.keys())}")

    return {"updated": bool(updates or new_tags), "fields": updates}


async def _list_missing_actors(session, ActorModel) -> list:
    from sqlalchemy import and_
    conds = [getattr(ActorModel, f).is_(None) for f in _MISSING_CORE_FIELDS]
    stmt = select(ActorModel).where(and_(*conds)).limit(BATCH_LIMIT)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def run_once(module: Optional[str] = None) -> dict:
    """执行一轮补全扫描。"""
    global _scanning, _last_run_at, _last_stats
    if _scanning:
        return {"status": "skipped", "reason": "already running"}
    _scanning = True
    try:
        modules = [module] if module else MODULES
        total_candidates = 0
        total_updated = 0
        per_module = {}

        for mod in modules:
            try:
                ActorModel = get_module_model(mod, "actor")
            except Exception as e:
                logger.debug(f"[{mod}] 无 actor 模型，跳过: {e}")
                continue

            try:
                session = await get_module_session(mod)
            except Exception as e:
                logger.warning(f"[{mod}] 获取会话失败，跳过: {e}")
                continue

            try:
                candidates = await _list_missing_actors(session, ActorModel)
                random.shuffle(candidates)
                updated = 0
                for actor in candidates:
                    try:
                        res = await enrich_actor(mod, actor, session)
                        if res["updated"]:
                            updated += 1
                    except Exception as e:
                        logger.debug(f"[{mod}] 演员 {getattr(actor, 'name', '?')} 补全失败: {e}")
                    await asyncio.sleep(REQUEST_DELAY)
                total_candidates += len(candidates)
                total_updated += updated
                per_module[mod] = {"candidates": len(candidates), "updated": updated}
            finally:
                # 会话由模块 DB 统一管理，这里不主动 close（与 tags.py / actor_merge_service.py 一致）
                pass

        _last_run_at = datetime.now().isoformat(timespec="seconds")
        _last_stats = {
            "candidates": total_candidates,
            "updated": total_updated,
            "per_module": per_module,
        }
        logger.info(f"演员资料补全扫描完成: 候选 {total_candidates}, 更新 {total_updated}")
        return {"status": "ok", "candidates": total_candidates, "updated": total_updated,
                "per_module": per_module}
    finally:
        _scanning = False


async def _scanner_loop(interval_seconds: int):
    global _scanner_running
    _scanner_running = True
    logger.info(f"演员资料自动补全扫描器启动，间隔 {interval_seconds}s")
    try:
        while True:
            if _is_enabled():
                try:
                    await run_once()
                except Exception as e:
                    logger.error(f"演员资料补全扫描异常: {e}")
            else:
                logger.debug("演员资料补全扫描器已禁用（config.actor_profile_enrich_enabled=false）")
            await asyncio.sleep(interval_seconds)
    finally:
        _scanner_running = False


def ensure_scanner_started() -> None:
    """确保后台扫描任务已启动（幂等）。在请求处理期间调用最稳妥（此时事件循环已运行）。"""
    global _scanner_task
    if _scanner_task is not None and not _scanner_task.done():
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            return
        _scanner_task = loop.create_task(_scanner_loop(_interval_seconds()))
        logger.info("演员资料自动补全扫描器任务已创建")
    except Exception as e:
        logger.debug(f"扫描器任务延迟启动（将在下次请求时启动）: {e}")


def get_status() -> dict:
    return {
        "running": _scanner_running,
        "scanning": _scanning,
        "enabled": _is_enabled(),
        "interval_seconds": _interval_seconds(),
        "last_run_at": _last_run_at,
        "last_stats": _last_stats,
    }
