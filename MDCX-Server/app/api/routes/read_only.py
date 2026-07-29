"""唯读来源 + .strm 生成 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.read_only_service import ReadOnlyService

router = APIRouter()


@router.get("/scan")
async def api_read_only_scan(
    root_path: str = Query(..., description="视频文件根目录"),
    recursive: bool = Query(True, description="是否递归扫描子目录"),
    generate_strm: bool = Query(True, description="是否生成 .strm"),
    generate_nfo: bool = Query(True, description="是否生成 .nfo"),
):
    """扫描目录，生成唯读引用（.strm + .nfo + JSON 索引）。

    与普通刮削的区别：
    - 不写 NFO 到原目录
    - 不修改文件属性
    - 只生成外部引用文件
    """
    import os
    if not os.path.isdir(root_path):
        raise HTTPException(status_code=404, detail=f"目录不存在: {root_path}")

    service = ReadOnlyService()
    result = await service.full_process(
        root_path, generate_strm_flag=generate_strm, generate_nfo_flag=generate_nfo,
    )
    return result


@router.get("/index")
async def api_read_only_index():
    """获取唯读来源索引 JSON。"""
    import json
    import os
    index_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "read_only", "index.json",
    )
    if not os.path.isfile(index_path):
        return {"movies": [], "count": 0}
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)
