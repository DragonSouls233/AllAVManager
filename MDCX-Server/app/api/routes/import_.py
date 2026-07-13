"""
导入管理路由

API 端点：
- GET  /api/v1/import/scan    - 扫描目录，检测已有刮削
- POST /api/v1/import/run     - 执行导入
- GET  /api/v1/import/status  - 导入状态/进度
- GET  /api/v1/import/report  - 导入报告
- POST /api/v1/import/cleanup - 清理数据库中已删除的文件记录
- POST /api/v1/import/resync  - 重新同步：检测目录变化并更新数据库
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import ImportRecord, Movie, Actor
from app.importer.sync import ImportSync, ImportResult, ImportReport

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Request Models =====

class ImportScanRequest(BaseModel):
    """扫描请求 - 兼容前端多目录+扩展名过滤"""
    directory: Optional[str] = Field(None, description="扫描目录（单目录，兼容旧版）")
    directories: Optional[list[str]] = Field(None, description="扫描目录列表（多目录，前端格式）")
    recursive: bool = Field(default=True, description="是否递归扫描")
    extensions: Optional[list[str]] = Field(None, description="文件扩展名过滤（如 ['mp4','mkv']），不过滤则留空")


class ImportRunRequest(BaseModel):
    """导入执行请求 - 兼容前端字段"""
    directories: list[str] = Field(..., description="要导入的目录列表")
    conflict_strategy: str = Field(default="skip", description="冲突策略: skip/overwrite/merge")
    skip_hours: int = Field(default=72, description="冷却期（小时），冷却期内已导入的目录直接跳过")
    # 前端传来的额外字段（兼容接收，暂不影响核心逻辑）
    scrape: Optional[bool] = Field(None, description="导入后是否刮削（预留）")
    sources: Optional[list[str]] = Field(None, description="刮削来源（预留）")
    skip_existing: Optional[bool] = Field(None, description="跳过已存在（映射到 conflict_strategy）")


# ===== Response Models =====

class ScannedDirectory(BaseModel):
    """扫描到的目录"""
    path: str
    has_nfo: bool
    has_images: bool
    has_video: bool = False
    detected_number: Optional[str] = None
    video_files: list[str] = []


class ImportScanResponse(BaseModel):
    """扫描响应"""
    total: int
    directories: list[ScannedDirectory]


class ImportResultResponse(BaseModel):
    """导入结果响应"""
    directory: str
    number: Optional[str] = None
    status: str
    message: str
    movie_id: Optional[int] = None
    imported_at: Optional[str] = None


class ImportStatusResponse(BaseModel):
    """导入状态响应"""
    job_id: str
    status: str  # pending/running/completed/failed
    total: int
    processed: int
    success: int
    skipped: int
    failed: int
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None


class ImportReportResponse(BaseModel):
    """导入报告响应"""
    total: int
    success: int
    skipped: int
    failed: int
    duration_seconds: float
    results: list[ImportResultResponse]


# ===== Background Job Storage =====

_active_import_jobs: dict[str, dict] = {}
_MAX_COMPLETED_JOBS = 20  # 最多保留 20 个已完成任务，防止内存泄漏


def _cleanup_old_jobs():
    """清理已完成的旧任务，防止内存泄漏"""
    completed = [
        (jid, job) for jid, job in _active_import_jobs.items()
        if job.get("status") in ("completed", "failed")
    ]
    if len(completed) > _MAX_COMPLETED_JOBS:
        # 按完成时间排序，删除最旧的
        completed.sort(key=lambda x: x[1].get("finished_at") or datetime.min)
        for jid, _ in completed[:len(completed) - _MAX_COMPLETED_JOBS]:
            del _active_import_jobs[jid]


# ===== API Endpoints =====

# ===== 可复用扫描工具（/scan 端点与启动时自动扫描共用）=====
from pathlib import Path

VIDEO_EXTENSIONS_DEFAULT = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
    ".iso", ".rmvb", ".rm", ".mpg", ".mpeg", ".m4v", ".3gp", ".webm",
    ".vob", ".ogv", ".divx", ".asf", ".tp", ".mts",
}
SKIP_DIRS = {
    "System Volume Information", "$RECYCLE.BIN", "$Recycle.Bin",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "Recovery", "Intel", "PerfLogs", "pagefile.sys", "hiberfil.sys",
    ".git", ".svn", ".hg", "node_modules", "__pycache__",
    "AppData", "Application Data",
}


def _should_skip_dir(path: Path) -> bool:
    name = path.name
    if name in SKIP_DIRS:
        return True
    if name.startswith('.') and name != '.':
        return True
    if name.startswith('$'):
        return True
    return False


def _safe_iterdir(path: Path):
    try:
        return list(path.iterdir())
    except (PermissionError, OSError):
        return []


def _scan_one_root(root_dir: str, recursive: bool, video_ext: set) -> dict:
    """对单个根目录递归扫描，返回 {dir_path: ScannedDirectory}"""
    from app.importer.nfo_parser import NFOParser
    from app.importer.number_matcher import NumberMatcher

    nfo_parser = NFOParser()
    number_matcher = NumberMatcher()
    directory = Path(root_dir)

    if not directory.exists():
        logger.warning(f"扫描目录不存在，跳过: {root_dir}")
        return {}
    if not directory.is_dir():
        logger.warning(f"路径不是目录，跳过: {root_dir}")
        return {}

    logger.info(f"开始扫描目录: {root_dir} (recursive={recursive})")

    dir_nfo_map: dict = {}
    dir_video_map: dict = {}

    if recursive:
        queue = [directory]
        while queue:
            current = queue.pop(0)
            for item in _safe_iterdir(current):
                if item.is_dir():
                    if not _should_skip_dir(item):
                        queue.append(item)
                elif item.is_file():
                    suf = item.suffix.lower()
                    if suf == '.nfo':
                        dir_nfo_map.setdefault(str(item.parent), []).append(item)
                    elif suf in video_ext:
                        dir_video_map.setdefault(str(item.parent), []).append(item)
    else:
        for item in _safe_iterdir(directory):
            if item.is_file():
                suf = item.suffix.lower()
                if suf == '.nfo':
                    dir_nfo_map.setdefault(str(item.parent), []).append(item)
                elif suf in video_ext:
                    dir_video_map.setdefault(str(item.parent), []).append(item)

    scanned: dict = {}
    all_subdirs = set(dir_nfo_map.keys()) | set(dir_video_map.keys())

    for dir_path_str in all_subdirs:
        dir_path = Path(dir_path_str)
        nfo_files = dir_nfo_map.get(dir_path_str, [])
        video_files = dir_video_map.get(dir_path_str, [])

        detected_number = None
        if nfo_files:
            for nfo_file in nfo_files:
                try:
                    nfo_data = nfo_parser.parse(nfo_file)
                    if nfo_data and nfo_data.code:
                        detected_number = nfo_data.code
                        break
                    elif nfo_data:
                        number, _ = number_matcher.match(nfo_data, dir_path_str)
                        if number:
                            detected_number = number
                            break
                except Exception as e:
                    logger.warning(f"解析 NFO 文件 {nfo_file} 失败: {e}")
                    continue
        if not detected_number and video_files:
            try:
                number_result = number_matcher.match(
                    video_file=str(video_files[0]),
                    directory=dir_path_str,
                )
                if number_result[0]:
                    detected_number = number_result[0]
            except Exception:
                pass
        has_images = False
        _IMG_KEYWORDS = ('poster', 'fanart', 'thumb', 'cover', 'folder', 'backdrop')
        try:
            for item in dir_path.iterdir():
                if item.is_file() and item.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                    stem = item.stem.lower()
                    if stem in _IMG_KEYWORDS or any(
                        stem == k or stem.endswith('-' + k) or stem.endswith('_' + k)
                        for k in _IMG_KEYWORDS
                    ):
                        has_images = True
                        break
        except (PermissionError, OSError):
            pass
        scanned[dir_path_str] = ScannedDirectory(
            path=dir_path_str,
            has_nfo=bool(nfo_files),
            has_images=has_images,
            has_video=bool(video_files),
            detected_number=detected_number,
            video_files=[str(f) for f in video_files],
        )

    logger.info(f"目录 {root_dir} 扫描完成，发现 {len(scanned)} 个待处理目录")
    return scanned


async def collect_import_targets(
    scan_dirs: list[str],
    recursive: bool = True,
    extensions: list[str] | None = None,
) -> list:
    """扫描多个根目录，返回待导入的 ScannedDirectory 列表（已跳过冷却期内已导入的目录）

    重要：递归遍历文件系统 + 解析 NFO 是纯同步重 I/O，若直接跑在事件循环上会长时间
    阻塞 uvicorn，导致扫描期间 Web 界面完全无法访问。因此每个根目录的扫描都放到线程池
    执行（asyncio.to_thread）并并发 gather，事件循环全程空闲，Web 保持可访问。
    """
    import asyncio
    video_ext = VIDEO_EXTENSIONS_DEFAULT
    if extensions:
        video_ext = video_ext & {
            e.lower().strip() if e.startswith('.') else f'.{e.lower().strip()}'
            for e in extensions if e.strip()
        }
    # 每个根目录的递归扫描放到独立线程并发执行，避免阻塞事件循环
    scan_tasks = [
        asyncio.to_thread(_scan_one_root, root, recursive, video_ext)
        for root in scan_dirs
    ]
    scanned_results = await asyncio.gather(*scan_tasks)

    all_scanned: dict = {}
    for scanned in scanned_results:
        all_scanned.update(scanned)

    recently_imported = await _load_recently_imported(72)
    for d in list(all_scanned.keys()):
        if d in recently_imported:
            del all_scanned[d]

    logger.info(f"全部扫描完成，共发现 {len(all_scanned)} 个待处理目录")
    return list(all_scanned.values())


async def auto_scan_media_dirs(
    directories: list[str],
    recursive: bool = True,
    conflict_strategy: str = "skip",
) -> str | None:
    """启动时对媒体目录自动递归扫描并导入（无需手动触发）"""
    import asyncio

    targets = await collect_import_targets(directories, recursive, None)
    if not targets:
        logger.info("自动扫描：未发现需要导入的目录（可能已导入或在冷却期内）")
        return None

    dirs_to_import = [s.path for s in targets]
    job_id = "auto_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    _active_import_jobs[job_id] = {
        "status": "pending",
        "total": len(dirs_to_import),
        "processed": 0,
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "started_at": datetime.now(),
        "finished_at": None,
        "error_message": None,
        "results": [],
        "auto": True,
    }
    asyncio.create_task(
        _run_import_background(job_id, dirs_to_import, conflict_strategy, 72)
    )
    logger.info(f"自动扫描导入任务已创建: job_id={job_id}, 目录数={len(dirs_to_import)}")
    return job_id


@router.post("/scan", response_model=ImportScanResponse)
async def scan_directory(
    request: ImportScanRequest,
    background_tasks: BackgroundTasks,
):
    """
    扫描目录，检测已有刮削内容和视频文件

    支持两种调用方式：
    - 旧版: { directory: "D:/Videos", recursive: true }
    - 新版(前端): { directories: ["D:/Videos","E:/Movies"], recursive: true, extensions: ["mp4","mkv"] }

    增量扫描：冷却期内已成功导入的子目录会被跳过，不重复扫描。
    扫描完成后自动在后台启动导入任务。
    """
    # ---- 统一目录列表：兼容单 directory 和多 directories ----
    scan_dirs: list[str] = []
    if request.directories:
        scan_dirs = [d.strip() for d in request.directories if d.strip()]
    elif request.directory:
        scan_dirs = [request.directory.strip()]

    if not scan_dirs:
        raise HTTPException(status_code=400, detail="请提供至少一个目录路径（directory 或 directories）")

    ext_filter = [e for e in (request.extensions or []) if e.strip()]

    try:
        targets = await collect_import_targets(scan_dirs, request.recursive, ext_filter)
    except Exception as e:
        logger.error(f"扫描目录失败: {e}")
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")

    # 扫描完成后自动在后台启动导入
    dirs_to_import = [s.path for s in targets]
    if dirs_to_import:
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        _active_import_jobs[job_id] = {
            "status": "pending",
            "total": len(dirs_to_import),
            "processed": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "started_at": datetime.now(),
            "finished_at": None,
            "error_message": None,
            "results": [],
        }
        background_tasks.add_task(
            _run_import_background,
            job_id,
            dirs_to_import,
            "skip",
            72,
        )
        logger.info(f"自动导入任务已创建: job_id={job_id}, 目录数={len(dirs_to_import)}")

    return ImportScanResponse(
        total=len(targets),
        directories=targets,
    )


@router.post("/run")
async def run_import(
    request: ImportRunRequest,
    background_tasks: BackgroundTasks,
):
    """
    执行导入

    - directories: 要导入的目录列表
    - conflict_strategy: 冲突处理策略（skip/overwrite/merge）
    - skip_hours: 冷却期小时数

    兼容前端字段：
    - skip_existing: true → 映射为 conflict_strategy="skip"
    - scrape / sources: 预留字段，暂不影响核心导入流程
    """
    # 前端 skip_existing 映射到 conflict_strategy
    if request.skip_existing is True and request.conflict_strategy == "skip":
        pass  # 已是默认值
    elif request.skip_existing is False and request.conflict_strategy == "skip":
        request.conflict_strategy = "overwrite"

    # 验证冲突策略
    if request.conflict_strategy not in ["skip", "overwrite", "merge"]:
        raise HTTPException(
            status_code=400,
            detail=f"无效的冲突策略: {request.conflict_strategy}"
        )
    
    # 创建任务
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    _active_import_jobs[job_id] = {
        "status": "pending",
        "total": len(request.directories),
        "processed": 0,
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "started_at": datetime.now(),
        "finished_at": None,
        "error_message": None,
        "results": [],
    }
    
    # 后台执行导入
    background_tasks.add_task(
        _run_import_background,
        job_id,
        request.directories,
        request.conflict_strategy,
        request.skip_hours,
    )
    
    return {
        "job_id": job_id,
        "status": "pending",
        "total": len(request.directories),
    }


@router.get("/status/{job_id}", response_model=ImportStatusResponse)
async def get_import_status(job_id: str):
    """
    获取导入状态/进度
    
    - job_id: 任务 ID（由 /run 返回）
    """
    if job_id not in _active_import_jobs:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    job = _active_import_jobs[job_id]
    
    return ImportStatusResponse(
        job_id=job_id,
        status=job["status"],
        total=job["total"],
        processed=job["processed"],
        success=job["success"],
        skipped=job["skipped"],
        failed=job["failed"],
        started_at=job["started_at"].isoformat() if job["started_at"] else None,
        finished_at=job["finished_at"].isoformat() if job["finished_at"] else None,
        error_message=job["error_message"],
    )


@router.get("/report/{job_id}", response_model=ImportReportResponse)
async def get_import_report(job_id: str):
    """
    获取导入报告
    
    - job_id: 任务 ID
    """
    if job_id not in _active_import_jobs:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    job = _active_import_jobs[job_id]
    
    # 计算耗时
    duration = 0.0
    if job["started_at"] and job["finished_at"]:
        duration = (job["finished_at"] - job["started_at"]).total_seconds()
    
    return ImportReportResponse(
        total=job["total"],
        success=job["success"],
        skipped=job["skipped"],
        failed=job["failed"],
        duration_seconds=duration,
        results=[
            ImportResultResponse(
                directory=r.get("directory", ""),
                number=r.get("number"),
                status=r.get("status", "pending"),
                message=r.get("message", ""),
                movie_id=r.get("movie_id"),
                imported_at=r.get("imported_at"),
            )
            for r in job["results"]
        ],
    )


@router.get("/history")
async def get_import_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """
    获取导入历史记录
    
    从数据库 import_records 表查询
    """
    query = select(ImportRecord).order_by(ImportRecord.imported_at.desc())
    
    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)
    
    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    records = result.scalars().all()
    
    return {
        "total": total or 0,
        "items": [
            {
                "id": r.id,
                "file_path": r.file_path,
                "movie_code": r.movie_code,
                "movie_id": r.movie_id,
                "source_type": r.source_type,
                "status": r.status,
                "conflict": r.conflict,
                "imported_at": r.imported_at.isoformat() if r.imported_at else None,
            }
            for r in records
        ],
    }


@router.delete("/history/{record_id}")
async def delete_import_record(
    record_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    删除导入记录
    
    - record_id: 记录 ID
    """
    record = await session.get(ImportRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    
    await session.delete(record)
    await session.commit()
    
    return {"status": "ok"}


# ===== Background Task =====

async def _run_import_background(
    job_id: str,
    directories: list[str],
    conflict_strategy: str,
    skip_hours: int = 72,
):
    """
    后台执行导入任务

    优化策略：
    1. 批量事务提交（减少 SQLite 锁竞争）
    2. 限速扫描（每条间隔 50ms，避免 I/O 压力过大）
    3. 增量扫描（跳过冷却期内已成功导入的目录，默认 72 小时/3 天）
    4. 单条错误不影响整体流程
    """
    import asyncio
    import_sync = ImportSync(conflict_strategy=conflict_strategy)

    job = _active_import_jobs[job_id]
    job["status"] = "running"

    # ===== 增量扫描：加载冷却期内已成功导入的目录 =====
    recently_imported = await _load_recently_imported(skip_hours)

    # 批量保存导入记录，减少事务次数
    pending_records: list[ImportRecord] = []
    BATCH_SIZE = 200  # 每 200 条批量写入一次
    IMPORT_DELAY = 0.01  # 每条导入间隔 10ms

    skipped_count = 0

    async def _flush_records():
        """批量写入待保存的导入记录"""
        if not pending_records:
            return
        from app.db.database import get_db
        db = get_db()
        try:
            async with db.session() as session:
                session.add_all(pending_records)
                await session.commit()
            pending_records.clear()
        except Exception as e:
            logger.warning(f"批量保存导入记录失败: {e}")
            for record in list(pending_records):
                try:
                    async with db.session() as session:
                        session.add(record)
                        await session.commit()
                except Exception:
                    pass
            pending_records.clear()

    try:
        for i, directory in enumerate(directories):
            try:
                # ===== 增量扫描：跳过冷却期内已导入的目录 =====
                if directory in recently_imported:
                    skipped_count += 1
                    job["processed"] += 1
                    job["skipped"] += 1
                    job["results"].append({
                        "directory": directory,
                        "status": "skipped",
                        "message": f"冷却期内（{skip_hours}小时）已导入，跳过扫描",
                    })
                    pending_records.append(ImportRecord(
                        file_path=directory,
                        source_type="nfo",
                        status="skipped",
                        imported_at=datetime.now(),
                    ))
                    if len(pending_records) >= BATCH_SIZE:
                        await _flush_records()
                    continue

                result = await import_sync.import_directory(directory)

                job["processed"] += 1
                job["results"].append({
                    "directory": result.directory,
                    "number": result.number,
                    "status": result.status,
                    "message": result.message,
                    "movie_id": result.movie_id,
                    "imported_at": result.imported_at.isoformat() if result.imported_at else None,
                })

                if result.status == "success":
                    job["success"] += 1
                elif result.status == "skipped":
                    job["skipped"] += 1
                else:
                    job["failed"] += 1

                # 收集导入记录（不立即写入）
                pending_records.append(ImportRecord(
                    file_path=result.directory,
                    movie_code=result.number,
                    movie_id=result.movie_id,
                    source_type="nfo",
                    status=result.status,
                    imported_at=result.imported_at or datetime.now(),
                ))

                # 每 BATCH_SIZE 条批量写入一次
                if len(pending_records) >= BATCH_SIZE:
                    await _flush_records()

                # ===== 限速：每条导入后短暂休息 =====
                await asyncio.sleep(IMPORT_DELAY)

            except Exception as e:
                # 单条错误不影响整体流程
                logger.error(f"Import error for {directory}: {e}")
                job["processed"] += 1
                job["failed"] += 1
                job["results"].append({
                    "directory": directory,
                    "status": "failed",
                    "message": str(e)[:200],  # 截断过长错误信息
                })

        # 写入剩余记录
        await _flush_records()

        job["status"] = "completed"
        job["finished_at"] = datetime.now()
        _cleanup_old_jobs()
        if skipped_count > 0:
            logger.info(f"导入完成：跳过冷却期内 {skipped_count} 个目录，实际处理 {job['processed'] - skipped_count} 个")

    except Exception as e:
        logger.error(f"Import job {job_id} failed: {e}")
        job["status"] = "failed"
        job["error_message"] = str(e)
        job["finished_at"] = datetime.now()


async def _load_recently_imported(hours: int = 72) -> set[str]:
    """
    加载冷却期内已成功导入的目录路径集合

    用于增量扫描：如果目录在冷却期内已成功导入，直接跳过，不再扫描。
    默认 72 小时（3 天）。
    """
    from app.db.database import get_db
    from datetime import timedelta

    db = get_db()
    cutoff = datetime.now() - timedelta(hours=hours)

    try:
        async with db.session() as session:
            result = await session.execute(
                select(ImportRecord.file_path).where(
                    ImportRecord.status.in_(["success", "skipped"]),
                    ImportRecord.imported_at.isnot(None),
                    ImportRecord.imported_at >= cutoff,
                )
            )
            paths = {row[0] for row in result.fetchall()}
            if paths:
                logger.info(f"增量扫描：冷却期 {hours} 小时内，跳过 {len(paths)} 个已导入目录")
            return paths
    except Exception as e:
        logger.warning(f"加载最近导入记录失败: {e}")
        return set()


async def _save_import_record(result: ImportResult):
    """保存导入记录到数据库（带重试机制处理 SQLite 锁）"""
    from app.db.database import get_db

    db = get_db()

    # 最多重试 5 次，指数退避
    max_retries = 5
    for attempt in range(max_retries):
        try:
            async with db.session() as session:
                record = ImportRecord(
                    file_path=result.directory,
                    movie_code=result.number,
                    movie_id=result.movie_id,
                    source_type="nfo",
                    status=result.status,
                    imported_at=result.imported_at or datetime.now(),
                )
                session.add(record)
                await session.commit()
                return
        except Exception as e:
            # 数据库锁定时重试
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                import asyncio
                wait_time = 0.1 * (2 ** attempt)  # 0.1s, 0.2s, 0.4s, 0.8s
                await asyncio.sleep(wait_time)
                continue
            # 其他错误只记录日志，不影响导入流程
            if attempt == max_retries - 1:
                logger.warning(f"Save import record failed after {max_retries} tries: {e}")
            else:
                logger.debug(f"Save import record attempt {attempt + 1} failed: {e}")


# ===== 清理 & 重新同步端点 =====

class CleanupRequest(BaseModel):
    """清理请求"""
    dry_run: bool = Field(default=False, description="仅预览，不实际删除数据")
    delete_missing_movies: bool = Field(default=False, description="删除文件已不存在的影片记录")
    clear_missing_file_path: bool = Field(default=True, description="清除已不存在的 file_path（设为 NULL）")
    clear_missing_cover_url: bool = Field(default=True, description="清除已不存在的 cover_url（设为 NULL）")
    limit: int = Field(default=10000, ge=1, le=50000, description="最多检查多少条记录")


class CleanupResult(BaseModel):
    """清理结果"""
    dry_run: bool
    total_checked: int
    missing_file_path: int = 0
    missing_cover_url: int = 0
    missing_video_files: int = 0  # file_path 指向的文件不存在
    missing_cover_files: int = 0  # cover_url 指向的文件不存在
    deleted_movies: int = 0
    cleared_file_paths: int = 0
    cleared_cover_urls: int = 0
    errors: list[str] = []


@router.post("/cleanup", response_model=CleanupResult)
async def cleanup_missing_files(
    req: CleanupRequest,
    session: AsyncSession = Depends(get_session),
):
    """检测并清理数据库中引用已不存在文件的记录。

    场景：
    - 用户删除了视频文件/封面图片，但数据库中仍有记录
    - 目录被移动或重命名，导致 file_path/cover_url 失效

    处理策略：
    - clear_missing_file_path=True: 将失效的 file_path 设为 NULL（保留影片记录）
    - clear_missing_cover_url=True: 将失效的 cover_url 设为 NULL（保留影片记录）
    - delete_missing_movies=True: 当 file_path 和 cover_url 都已失效时，删除整条影片记录
    - dry_run=True: 仅统计，不修改数据库
    """
    from pathlib import Path

    result = CleanupResult(dry_run=req.dry_run)

    rows = await session.execute(
        select(Movie).where(
            or_(
                Movie.file_path.isnot(None),
                Movie.cover_url.isnot(None),
            )
        ).limit(req.limit)
    )
    movies = rows.scalars().all()
    result.total_checked = len(movies)

    to_delete = []
    to_update_file_path = []
    to_update_cover_url = []

    for m in movies:
        file_path_exists = False
        cover_url_exists = False

        if m.file_path:
            fp = Path(m.file_path)
            if fp.exists() and fp.is_file():
                file_path_exists = True
            else:
                result.missing_video_files += 1

        if m.cover_url:
            cp = Path(m.cover_url)
            if cp.exists() and cp.is_file():
                cover_url_exists = True
            else:
                result.missing_cover_files += 1

        if not file_path_exists and not cover_url_exists:
            if req.delete_missing_movies:
                to_delete.append(m)
                result.deleted_movies += 1
        else:
            if not file_path_exists and req.clear_missing_file_path and m.file_path:
                to_update_file_path.append(m)
                result.cleared_file_paths += 1
            if not cover_url_exists and req.clear_missing_cover_url and m.cover_url:
                to_update_cover_url.append(m)
                result.cleared_cover_urls += 1

    if not req.dry_run:
        try:
            for m in to_delete:
                await session.delete(m)
            for m in to_update_file_path:
                m.file_path = None
                m.file_size = None
            for m in to_update_cover_url:
                m.cover_url = None
            await session.commit()
        except Exception as e:
            result.errors.append(str(e))
            await session.rollback()

    return result


class ResyncRequest(BaseModel):
    """重新同步请求"""
    directories: list[str] = Field(..., description="要扫描的根目录列表")
    update_file_paths: bool = Field(default=True, description="更新已变更的文件路径")
    update_actor_names: bool = Field(default=True, description="检测目录名变化并更新演员名")
    detect_deleted: bool = Field(default=False, description="同时检测并清理已删除的记录")
    dry_run: bool = Field(default=False, description="仅预览，不实际修改数据库")
    limit: int = Field(default=5000, ge=1, le=50000, description="最多处理多少条记录")


class ResyncResult(BaseModel):
    """重新同步结果"""
    dry_run: bool
    scanned_movies: int = 0
    updated_file_paths: int = 0
    updated_actor_names: int = 0
    detected_deleted: int = 0
    deleted_records: int = 0
    details: list[str] = []


@router.post("/resync", response_model=ResyncResult)
async def resync_database(
    req: ResyncRequest,
    session: AsyncSession = Depends(get_session),
):
    """重新同步数据库：检测文件系统变化并更新数据库。

    功能：
    1. 目录重命名检测：如果目录路径变了但番号一样，更新 file_path/cover_url
    2. 演员目录名变更检测：如果演员目录改名了，更新 Actor.name
    3. 删除检测：如果 req.detect_deleted=True，同时清理已删除的记录
    """
    from pathlib import Path

    result = ResyncResult(dry_run=req.dry_run)

    VIDEO_EXTENSIONS_FOR_SYNC = {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
        ".rmvb", ".rm", ".mpg", ".mpeg", ".m4v", ".3gp", ".webm",
    }

    rows = await session.execute(
        select(Movie).where(
            or_(Movie.code.isnot(None), Movie.file_path.isnot(None), Movie.cover_url.isnot(None))
        ).limit(req.limit)
    )
    movies = list(rows.scalars().all())
    result.scanned_movies = len(movies)

    movie_by_code = {}
    for m in movies:
        if m.code:
            code_upper = m.code.strip().upper()
            if code_upper not in movie_by_code:
                movie_by_code[code_upper] = []
            movie_by_code[code_upper].append(m)

    for root_dir_str in req.directories:
        root_dir = Path(root_dir_str)
        if not root_dir.exists():
            result.details.append(f"目录不存在，跳过: {root_dir_str}")
            continue

        try:
            for entry in root_dir.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name.startswith('.') or entry.name.startswith('$'):
                    continue
                dir_name = entry.name
                code_match = _extract_code_from_dirname(dir_name)
                if not code_match:
                    continue

                matched_movies = movie_by_code.get(code_match.upper(), [])
                if not matched_movies:
                    continue

                for video_file in entry.iterdir():
                    if video_file.is_file() and video_file.suffix.lower() in VIDEO_EXTENSIONS_FOR_SYNC:
                        video_path = str(video_file)
                        for m in matched_movies:
                            if m.file_path != video_path:
                                result.details.append(
                                    f"更新 file_path: {m.code} -> {video_path}"
                                )
                                if not req.dry_run:
                                    m.file_path = video_path
                                    m.file_size = video_file.stat().st_size
                                result.updated_file_paths += 1
                        break

                for img_file in entry.iterdir():
                    if img_file.is_file() and img_file.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                        if img_file.stem.lower() in ("cover", "poster", "folder", "fanart"):
                            cover_path = str(img_file)
                            for m in matched_movies:
                                if m.cover_url != cover_path:
                                    result.details.append(
                                        f"更新 cover_url: {m.code} -> {cover_path}"
                                    )
                                    if not req.dry_run:
                                        m.cover_url = cover_path
                            break
        except PermissionError:
            result.details.append(f"无权限访问目录: {entry}")

    if req.update_actor_names:
        rows_actors = await session.execute(
            select(Actor).limit(req.limit)
        )
        actors = list(rows_actors.scalars().all())
        actor_by_name = {a.name: a for a in actors if a.name}
        actor_by_name_jp = {a.name_jp: a for a in actors if a.name_jp}

        for root_dir_str in req.directories:
            root_dir = Path(root_dir_str)
            if not root_dir.exists():
                continue
            try:
                for entry in root_dir.iterdir():
                    if not entry.is_dir():
                        continue
                    dir_name = entry.name
                    actor = actor_by_name.get(dir_name) or actor_by_name_jp.get(dir_name)
                    if not actor or actor.name == dir_name:
                        continue
                    old_name = actor.name
                    result.details.append(
                        f"更新演员名: {old_name} -> {dir_name}"
                    )
                    if not req.dry_run:
                        if actor.name:
                            actor.name = dir_name
                        result.updated_actor_names += 1
            except PermissionError:
                pass

    if req.detect_deleted:
        cleanup_req = CleanupRequest(
            dry_run=req.dry_run,
            clear_missing_file_path=True,
            clear_missing_cover_url=True,
            delete_missing_movies=False,
            limit=req.limit,
        )
        cleanup_result = await cleanup_missing_files(cleanup_req, session)
        result.detected_deleted = cleanup_result.missing_video_files + cleanup_result.missing_cover_files
        result.deleted_records = cleanup_result.deleted_movies

    if not req.dry_run:
        try:
            await session.commit()
        except Exception as e:
            result.details.append(f"提交失败: {e}")
            await session.rollback()

    return result


def _extract_code_from_dirname(dirname: str) -> Optional[str]:
    """从目录名提取番号"""
    import re
    dirname_upper = dirname.strip().upper()
    patterns = [
        re.compile(r"^([A-Z]{2,6}[-_]?\d{2,5})"),
        re.compile(r"^([A-Z]{2,6}[-_]\d{2,5})"),
        re.compile(r"^(\d{6,7}[-_]?\d{2,3})"),  # FC2 格式
        re.compile(r"^([A-Z]{1,4}[-_]\d{2,5})"),  # 短前缀
    ]
    for pat in patterns:
        m = pat.match(dirname_upper)
        if m:
            return m.group(1).replace("_", "-")
    return None