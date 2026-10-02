"""
补刮管理路由

API 端点：
- GET  /api/v1/patch/detect   - 检测缺失字段/图片
- POST /api/v1/patch/run      - 执行补刮
- GET  /api/v1/patch/status   - 补刮状态/进度
- GET  /api/v1/patch/report   - 补刮报告
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
# Movie/PatchRecord now per-module
from app.utils.module_helper import get_module_model, get_module_session
from app.patcher.detector import MissingDetector, MissingInfo
from app.patcher.engine import PatchWorkflow, PatchOptions, PatchJobResult, PatchMode
from app.patcher.strategy import PatchType, PatchResult
from app.patcher.reporter import PatchReporter, PatchReport

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Request Models =====

class DetectRequest(BaseModel):
    """检测请求"""
    movie_ids: Optional[list[int]] = Field(default=None, description="电影 ID 列表")
    codes: Optional[list[str]] = Field(default=None, description="番号列表")
    status: Optional[str] = Field(default=None, description="按状态过滤")
    check_critical_only: bool = Field(default=False, description="仅检查关键字段")


class PatchRunRequest(BaseModel):
    """补刮执行请求"""
    mode: str = Field(default="all", description="补刮模式: all/directory/selected")
    patch_type: str = Field(default="smart", description="补刮类型: smart/images_only/metadata_only/full/custom")

    # 选定补刮
    movie_ids: Optional[list[int]] = Field(default=None, description="电影 ID 列表")
    codes: Optional[list[str]] = Field(default=None, description="番号列表")

    # 目录级补刮
    directories: Optional[list[str]] = Field(default=None, description="目录列表")

    # 刮削来源站点（如 ['javbus','javdb']）；不传则自动选择
    sources: Optional[list[str]] = Field(default=None, description="指定刮削来源站点")

    # 跳过选项
    skip_recent_days: int = Field(default=7, description="跳过最近 N 天内刮削的")
    skip_verified: bool = Field(default=True, description="跳过已审核的")
    skip_complete: bool = Field(default=True, description="跳过字段完整的")

    # 自定义字段/图片（仅 custom 类型）
    custom_fields: Optional[list[str]] = Field(default=None, description="自定义字段列表")
    custom_images: Optional[list[str]] = Field(default=None, description="自定义图片列表")
    
    # 模块
    module: Optional[str] = Field(default=None, description="模块名（jav/fc2/...），不传=中心数据库")
    
    # 报告选项
    generate_report: bool = Field(default=True, description="生成报告")
    report_format: str = Field(default="json", description="报告格式: json/markdown/both")


# ===== Response Models =====

class MissingFieldResponse(BaseModel):
    """缺失字段响应"""
    field: str
    current_value: Optional[str] = None
    importance: str


class MissingImageResponse(BaseModel):
    """缺失图片响应"""
    image_type: str
    expected_path: Optional[str] = None
    exists: bool
    importance: str


class MissingInfoResponse(BaseModel):
    """缺失信息响应"""
    movie_id: int
    movie_code: str
    missing_fields: list[MissingFieldResponse]
    missing_images: list[MissingImageResponse]
    nfo_exists: bool
    nfo_path: Optional[str] = None
    actor_images_missing: list[str]
    total_missing: int
    critical_missing: int
    output_dir: Optional[str] = None


class DetectResponse(BaseModel):
    """检测响应"""
    total: int
    items: list[MissingInfoResponse]


class PatchResultResponse(BaseModel):
    """补刮结果响应"""
    movie_id: int
    movie_code: str
    patch_type: str
    status: str
    patched_fields: list[str] = []
    patched_images: list[str] = []
    failed_fields: list[str] = []
    failed_images: list[str] = []
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


class PatchJobResponse(BaseModel):
    """补刮任务响应"""
    job_id: str
    mode: str
    status: str = "running"
    progress: float = 0.0
    started_at: str
    finished_at: Optional[str] = None
    duration_seconds: float = 0.0
    total_detected: int = 0
    total_skipped: int = 0
    total_to_patch: int = 0
    total_patched: int = 0
    total_success: int = 0
    total_partial: int = 0
    total_failed: int = 0
    current_code: Optional[str] = None
    error_message: Optional[str] = None


class PatchReportResponse(BaseModel):
    """补刮报告响应"""
    report_id: str
    started_at: str
    finished_at: Optional[str] = None
    duration_seconds: float = 0.0
    total_movies: int = 0
    total_missing_detected: int = 0
    total_patched: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    success_rate: float = 0.0
    field_stats: dict
    image_stats: dict


# ===== Background Job Storage =====

# 存储正在运行的补刮任务（实时状态）
_active_jobs: dict[str, dict] = {}

# ── 任务状态持久化（2026-10-01 加）───────────────────────────────────────────
# 历史缺陷：_active_jobs 是**纯内存态**，而 _save_patch_records() 只在**整个任务收尾时**
# 才落库 ⇒ 进程被原生崩溃打死（实测 Windows 0xC0000005 / APPCRASH，故障模块 ntdll.dll）后：
#   · GET /patch/history 变空、patch_records 0 行
#   · 没有任何续跑/恢复机制
#   · 用户看到的就是「刮削走一半不动了 / 任务凭空消失」，而服务本身是健康的
#   （守护进程 5s 后就把 run.py 拉起来了）。
# 这里把任务状态**增量写盘**（原子替换），启动时再把上次遗留的 running 标为 interrupted，
# 保证「崩了也看得见、说得清」，不再静默消失。
_JOB_STATE_FILE: Optional[Path] = None
_JOB_STATE_LOCK = threading.Lock()
_last_persist_ts = 0.0
_PERSIST_MIN_INTERVAL = 3.0   # 秒；进度回调很频繁，节流避免每片都写盘
_MAX_JOBS_KEPT = 50


def _job_state_path() -> Path:
    """任务状态文件路径：<data_dir>/state/patch_jobs.json"""
    global _JOB_STATE_FILE
    if _JOB_STATE_FILE is None:
        try:
            from app.config.manager import get_config_manager
            base = Path(get_config_manager().computed.data_dir)
        except Exception:
            # app/api/routes/patch.py -> parents[3] == 服务端根目录
            base = Path(__file__).resolve().parents[3] / "data"
        _JOB_STATE_FILE = base / "state" / "patch_jobs.json"
    return _JOB_STATE_FILE


def _job_public(job_id: str, st: dict) -> dict:
    """把内部任务态转成「可 JSON 序列化 + 前端友好」的扁平结构

    刻意**剔除 result**（PatchJobResult 不可序列化）。
    同时给出前端补刮历史表格直接消费的别名字段（started_at/total/success/failed/status）。
    """
    started = st.get("started_at")
    finished = st.get("finished_at")
    return {
        "id": job_id,
        "job_id": job_id,
        "module": st.get("module") or "jav",
        "mode": st.get("mode"),
        "status": st.get("status"),
        "progress": st.get("progress", 0.0),
        "started_at": started.isoformat() if hasattr(started, "isoformat") else started,
        "finished_at": finished.isoformat() if hasattr(finished, "isoformat") else finished,
        "total_detected": st.get("total_detected", 0),
        "total_skipped": st.get("total_skipped", 0),
        "total_to_patch": st.get("total_to_patch", 0),
        "total_patched": st.get("total_patched", 0),
        "total": st.get("total_to_patch", 0),
        "total_success": st.get("total_success", 0),
        "success": st.get("total_success", 0),
        "total_partial": st.get("total_partial", 0),
        "total_failed": st.get("total_failed", 0),
        "failed": st.get("total_failed", 0),
        "current_code": st.get("current_code"),
        "error_message": st.get("error_message"),
    }


def _persist_jobs(force: bool = False) -> None:
    """把 _active_jobs 落盘（节流 + 原子替换）

    原子性：先写 .tmp 再 os.replace —— 即使在写盘途中被打死，也不会留下半个 JSON
    把状态文件本身弄坏（下次启动读不出来就等于又丢一次）。
    """
    global _last_persist_ts
    now = time.monotonic()
    if not force and now - _last_persist_ts < _PERSIST_MIN_INTERVAL:
        return
    _last_persist_ts = now
    try:
        path = _job_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        items = [_job_public(jid, st) for jid, st in _active_jobs.items()]
        items.sort(key=lambda x: x.get("started_at") or "", reverse=True)
        items = items[:_MAX_JOBS_KEPT]
        payload = {
            "version": 1,
            "saved_at": datetime.now().isoformat(),
            "jobs": items,
        }
        tmp = path.with_name(path.name + ".tmp")
        with _JOB_STATE_LOCK:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
    except Exception as e:
        logger.warning(f"补刮任务状态持久化失败: {e}")


def _load_persisted_jobs() -> list[dict]:
    try:
        path = _job_state_path()
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        return jobs if isinstance(jobs, list) else []
    except Exception as e:
        logger.warning(f"读取补刮任务状态失败: {e}")
        return []


def _restore_jobs_at_startup() -> None:
    """启动时恢复任务可见性：把上次进程遗留的 running 任务标记为 interrupted。

    原生崩溃（0xC0000005）不会给 Python 任何清理机会，所以状态文件里**必然**留着
    status=running 的僵尸任务 —— 这里正是它的兜底出口。
    """
    jobs = _load_persisted_jobs()
    if not jobs:
        return
    now = datetime.now()
    interrupted = 0
    for j in jobs:
        if not isinstance(j, dict):
            continue
        st = dict(j)
        jid = st.get("job_id") or st.get("id")
        if not jid:
            continue
        if st.get("status") == "running":
            st["status"] = "interrupted"
            st["finished_at"] = now.isoformat()
            st["error_message"] = (
                "任务被中断（服务进程崩溃或重启）；已完成的部分已逐片入库，"
                "未完成的可重新发起补刮，已完成的会被自动跳过"
            )
            interrupted += 1
        # 字符串时间 → datetime，供 /status 的 duration 计算
        for k in ("started_at", "finished_at"):
            v = st.get(k)
            if isinstance(v, str) and v:
                try:
                    st[k] = datetime.fromisoformat(v)
                except Exception:
                    st[k] = None
        _active_jobs[str(jid)] = st
    if interrupted:
        logger.warning(
            f"检测到 {interrupted} 个补刮任务在上次进程退出时处于运行中，已标记为 interrupted"
        )
    _persist_jobs(force=True)


try:
    _restore_jobs_at_startup()
except Exception as _e:      # 绝不因为状态恢复失败而阻断路由注册
    logger.warning(f"补刮任务状态恢复失败（忽略）: {_e}")


async def _find_movie_ids_in_directories(
    directories: list[str], session: AsyncSession
) -> list[int]:
    """根据目录列表查找匹配的电影 ID（output_dir 或 file_path 含该目录）"""
    from sqlalchemy import text

    ids: set[int] = set()
    for d in directories:
        d = d.rstrip("/\\")
        if not d:
            continue
        result = await session.execute(
            text(
                "SELECT id FROM movies "
                "WHERE output_dir LIKE :p1 OR file_path LIKE :p1"
            ),
            {"p1": f"%{d}%"},
        )
        for row in result.fetchall():
            ids.add(row[0])
    return list(ids)


# ===== API Endpoints =====

@router.get("/detect", response_model=DetectResponse)
async def detect_missing(
    movie_id: Optional[int] = Query(None, description="电影 ID"),
    code: Optional[str] = Query(None, description="番号"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    directories: Optional[list[str]] = Query(None, description="按目录范围检测（匹配 output_dir/file_path）"),
    fields: Optional[list[str]] = Query(None, description="仅报告指定字段类型的缺失（如 title,cover,actors）"),
    check_critical_only: bool = Query(False, description="仅检查关键字段"),
    module: Optional[str] = Query(None, description="模块名（jav/fc2/uncensored/chinese/western/pornhub），不传=遍历所有模块库聚合检测"),
    session: AsyncSession = Depends(get_session),
):
    """
    检测缺失字段/图片

    - 不传参数：检测所有电影
    - 传 movie_id：检测指定电影
    - 传 code：检测指定番号
    - 传 status：按状态过滤
    - 传 directories：仅检测该目录范围内的电影（支持演员文件夹定向补刮）
    - 传 fields：仅报告指定字段类型的缺失
    - 传 module：指定模块数据库（jav/fc2/...）；不传则遍历所有模块库聚合检测（已废弃的中心数据库 scraper.db 不再使用）
    """
    # 未传 module 时遍历所有模块库聚合检测（不再依赖已废弃的中心数据库 scraper.db）
    ALL_MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub"]

    async def _detect_across_modules(method: str, **kwargs) -> list:
        infos: list = []
        for m in ALL_MODULES:
            try:
                det = MissingDetector(check_critical_only=check_critical_only, module_name=m)
                infos.extend(await getattr(det, method)(**kwargs))
            except Exception as e:
                logger.warning(f"补刮检测模块 {m} 失败: {e}")
        return infos

    detector = MissingDetector(check_critical_only=check_critical_only, module_name=module)

    missing_infos = []

    if movie_id:
        info = await detector.detect_movie(movie_id)
        if info:
            missing_infos = [info]
    elif code:
        info = await detector.detect_by_code(code)
        if info:
            missing_infos = [info]
    elif status:
        # 按状态过滤：指定模块查该模块，未指定则跨所有模块
        if module:
            missing_infos = await detector.detect_batch(status=status)
        else:
            missing_infos = await _detect_across_modules("detect_batch", status=status)
    elif directories:
        if module:
            # 传了 module 时不支持按目录过滤，直接全量检测
            missing_infos = await detector.detect_all()
        else:
            # 未传 module：逐模块按目录找 id 后聚合检测
            mod_ids: list[int] = []
            for m in ALL_MODULES:
                try:
                    det = MissingDetector(check_critical_only=check_critical_only, module_name=m)
                    async with det._get_session() as s:
                        ids = await _find_movie_ids_in_directories(directories, s)
                        mod_ids.extend(ids)
                except Exception as e:
                    logger.warning(f"补刮目录扫描模块 {m} 失败: {e}")
            if mod_ids:
                missing_infos = await _detect_across_modules("detect_batch", movie_ids=mod_ids)
    else:
        # 全量检测：指定模块查该模块，未指定则跨所有模块
        if module:
            missing_infos = await detector.detect_all()
        else:
            missing_infos = await _detect_across_modules("detect_all")

    # 按指定字段类型过滤报告（不影响实际补刮，仅让检测结果与勾选一致）
    if fields:
        # 支持 genre/genres 别名映射
        field_aliases = {"genres": "genre"}
        wanted = set(field_aliases.get(f, f) for f in fields)
        for info in missing_infos:
            info.missing_fields = [f for f in info.missing_fields if f.field_type.value in wanted]
            info.missing_images = [i for i in info.missing_images if i.image_type.value in wanted]

    # 转换响应
    items = []
    for info in missing_infos:
        items.append(MissingInfoResponse(
            movie_id=info.movie_id,
            movie_code=info.movie_code,
            missing_fields=[
                MissingFieldResponse(
                    field=f.field_type.value,
                    current_value=str(f.current_value) if f.current_value is not None else None,
                    importance=f.importance,
                )
                for f in info.missing_fields
            ],
            missing_images=[
                MissingImageResponse(
                    image_type=i.image_type.value,
                    expected_path=i.expected_path,
                    exists=i.exists,
                    importance=i.importance,
                )
                for i in info.missing_images
            ],
            nfo_exists=info.nfo_exists,
            nfo_path=info.nfo_path,
            actor_images_missing=info.actor_images_missing,
            total_missing=info.total_missing_count(),
            critical_missing=info.critical_missing_count(),
            output_dir=info.output_dir,
        ))
    
    return DetectResponse(total=len(items), items=items)


@router.post("/run", response_model=PatchJobResponse)
async def run_patch(
    request: PatchRunRequest,
    background_tasks: BackgroundTasks,
):
    """
    执行补刮
    
    - mode: all（全库）, directory（目录级）, selected（选定）
    - patch_type: smart（智能）, images_only（仅图片）, metadata_only（仅元数据）, full（完整）
    """
    # 转换模式
    try:
        mode = PatchMode(request.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")
    
    try:
        patch_type = PatchType(request.patch_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid patch_type: {request.patch_type}")
    
    # 创建选项
    options = PatchOptions(
        mode=mode,
        patch_type=patch_type,
        movie_ids=request.movie_ids or [],
        codes=request.codes or [],
        directories=request.directories or [],
        sources=request.sources,
        skip_recent_days=request.skip_recent_days,
        skip_verified=request.skip_verified,
        skip_complete=request.skip_complete,
        generate_report=request.generate_report,
        report_format=request.report_format,
        module=request.module,
    )
    
    # 创建初始状态
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    started_at = datetime.now()

    _active_jobs[job_id] = {
        "job_id": job_id,
        "mode": mode.value,
        "module": request.module or "jav",
        "status": "running",
        "progress": 0.0,
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": 0.0,
        "total_detected": 0,
        "total_skipped": 0,
        "total_to_patch": 0,
        "total_patched": 0,
        "total_success": 0,
        "total_partial": 0,
        "total_failed": 0,
        "current_code": None,
        "error_message": None,
        "result": None,
    }
    _persist_jobs(force=True)   # 立刻落盘：即使随后裸崩，也能在历史里看到"这个任务存在过"

    # 后台执行
    background_tasks.add_task(_run_patch_background, job_id, options)

    return PatchJobResponse(
        job_id=job_id,
        mode=mode.value,
        status="running",
        progress=0.0,
        started_at=started_at.isoformat(),
    )


@router.get("/status/{job_id}", response_model=PatchJobResponse)
async def get_patch_status(job_id: str):
    """
    获取补刮任务状态/进度
    
    - job_id: 任务 ID（由 /run 返回）
    """
    if job_id not in _active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    st = _active_jobs[job_id]
    finished_at = st.get("finished_at")
    started_at = st.get("started_at")
    duration = ((finished_at or datetime.now()) - started_at).total_seconds() if started_at else 0.0

    return PatchJobResponse(
        job_id=st["job_id"],
        mode=st.get("mode", ""),
        status=st.get("status", "running"),
        progress=st.get("progress", 0.0),
        started_at=started_at.isoformat() if started_at else "",
        finished_at=finished_at.isoformat() if finished_at else None,
        duration_seconds=duration,
        total_detected=st.get("total_detected", 0),
        total_skipped=st.get("total_skipped", 0),
        total_to_patch=st.get("total_to_patch", 0),
        total_patched=st.get("total_patched", 0),
        total_success=st.get("total_success", 0),
        total_partial=st.get("total_partial", 0),
        total_failed=st.get("total_failed", 0),
        current_code=st.get("current_code"),
        error_message=st.get("error_message"),
    )


@router.get("/report/{job_id}", response_model=PatchReportResponse)
async def get_patch_report(job_id: str):
    """
    获取补刮报告
    
    - job_id: 任务 ID
    """
    if job_id not in _active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = _active_jobs[job_id].get("result")
    
    if not result or not result.report:
        raise HTTPException(status_code=404, detail="Report not generated")
    
    report = result.report
    
    return PatchReportResponse(
        report_id=report.report_id,
        started_at=report.started_at.isoformat(),
        finished_at=report.finished_at.isoformat() if report.finished_at else None,
        duration_seconds=report.duration_seconds(),
        total_movies=report.total_movies,
        total_missing_detected=report.total_missing_detected,
        total_patched=report.total_patched,
        total_failed=report.total_failed,
        total_skipped=report.total_skipped,
        success_rate=report.success_rate(),
        field_stats={k: v.to_dict() for k, v in report.field_stats.items()},
        image_stats={k: v.to_dict() for k, v in report.image_stats.items()},
    )


@router.get("/history")
async def get_patch_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    module: str = Query("jav", description="模块名（jav/fc2/uncensored/chinese/western/pornhub），不传默认 jav"),
    include_records: bool = Query(False, description="同时附带逐片 patch_records 明细（旧行为）"),
):
    """
    获取补刮历史（**任务级**）

    2026-10-01 改：此前这里查的是逐片 ``patch_records``，而 ``patch_records`` 只在任务
    **收尾时**才写入 ⇒ 任务被崩溃/重启打断时它恒为空，"上次跑到哪"永远看不到
    （实测 0xC0000005 崩溃后 ``total=0``）。
    现在改为返回**持久化的任务记录**（``<data_dir>/state/patch_jobs.json``）：
      · 能显示被中断的任务（``status=interrupted``）及其进度（如 3721/9380）
      · 字段与前端补刮历史表格对齐（id/started_at/total/success/failed/status）
    """
    jobs = [
        j for j in (_job_public(jid, st) for jid, st in _active_jobs.items())
        if (j.get("module") or "jav") == module
    ]
    jobs.sort(key=lambda x: x.get("started_at") or "", reverse=True)

    start = (page - 1) * page_size
    resp = {
        "total": len(jobs),
        "items": jobs[start:start + page_size],
        "module": module,
    }

    # 兼容出口：仍可取逐片明细（默认关闭）
    if include_records:
        PatchRecord = get_module_model(module, "patch_record")
        session = await get_module_session(module)
        try:
            query = (
                select(PatchRecord)
                .order_by(PatchRecord.patched_at.desc())
                .limit(page_size)
            )
            result = await session.execute(query)
            resp["records"] = [
                {
                    "id": r.id,
                    "movie_id": r.movie_id,
                    "patch_type": r.patch_type,
                    "status": r.status,
                    "patched_at": r.patched_at.isoformat() if r.patched_at else None,
                }
                for r in result.scalars().all()
            ]
        finally:
            await session.close()

    return resp


# ===== Background Task =====

async def _run_patch_background(job_id: str, options: PatchOptions):
    """后台执行补刮任务（实时更新 _active_jobs）"""
    workflow = PatchWorkflow()
    logger.info(f"后台补刮任务已启动: {job_id}")

    def _on_progress(status_dict: dict):
        if job_id not in _active_jobs:
            return
        _active_jobs[job_id].update(status_dict)
        # 增量落盘（内部按 _PERSIST_MIN_INTERVAL 节流，不会每片都写盘）
        _persist_jobs()

    try:
        result = await workflow.run(options, progress_callback=_on_progress)
        # 完成：更新最终状态
        if job_id in _active_jobs:
            _active_jobs[job_id].update({
                "status": "success" if not result.error_message else "failed",
                "progress": 100.0,
                "finished_at": result.finished_at or datetime.now(),
                "total_detected": result.total_detected,
                "total_skipped": result.total_skipped,
                "total_to_patch": result.total_to_patch,
                "total_patched": result.total_patched,
                "total_success": result.total_success,
                "total_partial": result.total_partial,
                "total_failed": result.total_failed,
                "error_message": result.error_message,
                "result": result,
            })
            _persist_jobs(force=True)   # 终态立即落盘

        logger.info(
            f"后台补刮任务完成: {job_id} | "
            f"检测 {result.total_detected}, 跳过 {result.total_skipped}, "
            f"补刮 {result.total_patched} "
            f"(成功 {result.total_success}, 部分 {result.total_partial}, "
            f"失败 {result.total_failed})"
        )

        # 保存到数据库（按当前补刮模块落库；未指定模块默认 jav）
        await _save_patch_records(result, module=options.module or "jav")

    except Exception as e:
        logger.error(f"后台补刮任务 {job_id} 异常崩溃: {e}", exc_info=True)
        if job_id in _active_jobs:
            _active_jobs[job_id].update({
                "status": "failed",
                "finished_at": datetime.now(),
                "error_message": str(e),
            })
            _persist_jobs(force=True)


async def _save_patch_records(result: PatchJobResult, module: str = "jav"):
    """保存补刮记录到指定模块的数据库（patch_records 为每模块独立表）"""
    from app.db.module_db import ModuleDatabase

    PatchRecord = get_module_model(module, "patch_record")
    mod_db = ModuleDatabase.get_instance(module)
    session = await mod_db.get_session()
    try:
        for pr in result.results:
            record = PatchRecord(
                movie_id=pr.movie_id,
                missing_fields=str(pr.patched_fields + pr.failed_fields),
                missing_images=str(pr.patched_images + pr.failed_images),
                patch_type=pr.patch_type.value,
                status=pr.status.value,
                result=str(pr.to_dict()),
                patched_at=pr.finished_at or datetime.now(),
            )
            session.add(record)

        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()