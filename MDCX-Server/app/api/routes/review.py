"""人工复核队列 /review

把刮削质量做成可运营的抓手：扫描 → 列出可疑条目 → 人工核查 → 忽略 / 导出。
"""
from __future__ import annotations

import csv
import io
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import review_audit as ra

router = APIRouter()

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _resolve(modules: str) -> list[str]:
    available = ra.available_modules()
    if modules == "all":
        return available
    wanted = [m.strip() for m in modules.split(",") if m.strip()]
    bad = [m for m in wanted if m not in ra.MODULE_MODELS]
    if bad:
        raise HTTPException(400, f"未知模块: {bad}，有效值: {list(ra.MODULE_MODELS)} 或 all")
    return [m for m in wanted if m in available]


def _all_issues(module_names: list[str]) -> list[dict]:
    """汇总各模块缓存中的问题条目"""
    out: list[dict] = []
    for m in module_names:
        stat = ra.get_cached(m)
        if stat:
            out.extend(stat.get("issues") or [])
    return out


@router.get("/rules", summary="复核规则清单")
async def list_rules():
    """返回全部判定规则：编码、中文名、严重度、说明"""
    return {
        "rules": [
            {"code": c, "label": lb, "severity": sv, "desc": ds}
            for c, lb, sv, ds in ra.RULES
        ],
        "severities": ["high", "medium", "low"],
    }


@router.post("/scan", summary="扫描刮削质量")
async def scan_review(
    module: str = Query("all", description="模块名 / 逗号分隔 / all"),
    force: bool = Query(False, description="忽略缓存强制重扫"),
):
    """逐模块扫描并缓存结果。大库（PORNHUB 9 万+）需数秒，前端应先调它再取列表。"""
    modules = _resolve(module)
    if not modules:
        return {"modules": [], "total_issues": 0, "by_type": {}}

    await ra.scan(modules, force=force)

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    summaries = []
    total = 0
    for m in modules:
        stat = ra.get_cached(m)
        if not stat:
            continue
        issues = stat.get("issues") or []
        total += len(issues)
        summaries.append({
            "module": m,
            "label": stat.get("label"),
            "scanned": stat.get("scanned"),
            "issues": len(issues),
            "cached_age": stat.get("cached_age"),
        })
        for it in issues:
            for t in it["types"]:
                by_type[t] = by_type.get(t, 0) + 1
            by_severity[it["severity"]] = by_severity.get(it["severity"], 0) + 1

    return {
        "modules": summaries,
        "total_issues": total,
        "by_type": by_type,
        "by_severity": by_severity,
    }


@router.get("/stats", summary="复核统计（读缓存）")
async def review_stats(module: str = Query("all")):
    """读已有扫描缓存；未扫过返回空计数，前端据此提示「先扫描」"""
    modules = _resolve(module)
    issues = _all_issues(modules)
    ignored = ra.load_ignored()

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_module: dict[str, dict] = {}
    for it in issues:
        for t in it["types"]:
            by_type[t] = by_type.get(t, 0) + 1
        by_severity[it["severity"]] = by_severity.get(it["severity"], 0) + 1
        m = it["module"]
        entry = by_module.setdefault(m, {"label": it["module_label"], "total": 0})
        entry["total"] += 1

    open_issues = [i for i in issues if f"{i['module']}:{i['id']}" not in ignored]

    return {
        "scanned_modules": modules,
        "cached_modules": sorted({m for m in modules if ra.get_cached(m)}),
        "total_issues": len(issues),
        "open_issues": len(open_issues),
        "ignored_count": len(issues) - len(open_issues),
        "by_type": by_type,
        "by_severity": by_severity,
        "by_module": by_module,
    }


@router.get("/issues", summary="列出待复核条目")
async def list_issues(
    module: str = Query("all"),
    type: str | None = Query(None, description="规则编码，见 /review/rules"),
    severity: str | None = Query(None, description="high / medium / low"),
    include_ignored: bool = Query(False, description="是否含已忽略条目"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """分页返回待复核条目，默认按严重度（高→低）排序"""
    if type and type not in ra.RULE_CODES:
        raise HTTPException(400, f"未知规则: {type}，有效值: {ra.RULE_CODES}")
    if severity and severity not in _SEVERITY_ORDER:
        raise HTTPException(400, f"无效严重度: {severity}，有效值: high/medium/low")

    modules = _resolve(module)
    issues = _all_issues(modules)
    ignored = ra.load_ignored()

    if type:
        issues = [i for i in issues if type in i["types"]]
    if severity:
        issues = [i for i in issues if i["severity"] == severity]

    for i in issues:
        k = f"{i['module']}:{i['id']}"
        i["ignored"] = k in ignored
        i["ignore_reason"] = ignored.get(k, {}).get("reason", "")

    if not include_ignored:
        issues = [i for i in issues if not i["ignored"]]

    issues.sort(key=lambda i: (_SEVERITY_ORDER[i["severity"]], i["module"], i["id"]))

    return {
        "total": len(issues),
        "items": issues[offset: offset + limit],
    }


class IgnoreRequest(BaseModel):
    module: str
    movie_id: int
    reason: str = Field("", max_length=200)


class IgnoreBatchRequest(BaseModel):
    items: list[IgnoreRequest] = Field(..., min_length=1, max_length=1000)


@router.post("/ignore", summary="忽略条目")
async def ignore_issue(body: IgnoreRequest):
    """把某条目加入忽略名单（只影响复核视图，不改动影片数据）"""
    if body.module not in ra.MODULE_MODELS:
        raise HTTPException(400, f"未知模块: {body.module}")
    ra.add_ignored(body.module, body.movie_id, body.reason)
    return {"module": body.module, "movie_id": body.movie_id, "ignored": True}


@router.post("/ignore/batch", summary="批量忽略")
async def ignore_issues_batch(body: IgnoreBatchRequest):
    data = ra.load_ignored()
    for it in body.items:
        data[ra._key(it.module, it.movie_id)] = {"reason": it.reason, "at": time.time()}
    ra.save_ignored(data)
    return {"ignored": len(body.items)}


@router.post("/unignore", summary="取消忽略")
async def unignore_issue(body: IgnoreRequest):
    ra.remove_ignored(body.module, body.movie_id)
    return {"module": body.module, "movie_id": body.movie_id, "ignored": False}


@router.post("/ignore/clear", summary="清空忽略名单")
async def clear_ignore_list():
    before = len(ra.load_ignored())
    ra.clear_ignored()
    return {"cleared": before}


@router.get("/export", summary="导出待复核清单 CSV")
async def export_review_csv(
    module: str = Query("all"),
    type: str | None = Query(None),
    include_ignored: bool = Query(False),
    limit: int = Query(20000, ge=1, le=50000),
):
    """导出复核结果 CSV（UTF-8 BOM；单元格做了公式注入转义）"""
    modules = _resolve(module)
    issues = _all_issues(modules)
    ignored = ra.load_ignored()

    if type:
        issues = [i for i in issues if type in i["types"]]
    for i in issues:
        i["ignored"] = f"{i['module']}:{i['id']}" in ignored
    if not include_ignored:
        issues = [i for i in issues if not i["ignored"]]
    issues.sort(key=lambda i: (_SEVERITY_ORDER[i["severity"]], i["module"], i["id"]))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["模块", "番号", "标题", "问题类型", "严重度", "演员", "厂商",
                "状态", "文件路径", "更新时间"])
    sev_label = {"high": "高", "medium": "中", "low": "低"}
    for i in issues[:limit]:
        w.writerow([
            ra.iv(i["module_label"]), ra.iv(i["code"]), ra.iv(i["title"]),
            ra.iv("/".join(i["type_labels"])), sev_label.get(i["severity"], i["severity"]),
            ra.iv(i["actor"]), ra.iv(i["studio"]), ra.iv(i["status"]),
            ra.iv(i["file_path"]), ra.iv(i["updated_at"]),
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="review-issues.csv"'},
    )
