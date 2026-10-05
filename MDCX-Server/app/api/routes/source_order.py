# -*- coding: utf-8 -*-
"""刮削源序查询 API（只读）

前缀: /api/v1/source-order

为什么需要这个端点
------------------
`canon.source_order_for()` 是源序的**唯一真相源**，但它此前只被后端内部消费，
前端拿不到 —— 于是各个页面各自硬编码了一份源名列表（补刮页、导入页、
NFO 缓存重建页各一份），彼此不一致且都会随源序调整而腐化：

  - 补刮页 Patch.vue 的 SOURCE_POOL 引用的是 engine 的 PRIMARY/FALLBACK 池，
    **漏 `dmm_web`**（用户已把 DMM 定为主力源）
  - 导入页 Import.vue 顺序与 canon 相反，且含**已废弃的 `dmm`**
  - NFO 缓存重建页整体颠倒，主力前 4 个源一个都没列

有了本端点，前端改为「拉真实序渲染 UI + 不传 sources 让后端裁决」，
硬编码列表从此不需要维护。

GET /api/v1/source-order
    → { order, mainstream, amateur, aux, jp, jp_available, labels }
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter()

#: 源名 → 展示名。⚠️ 命名陷阱：`thejavdb` **不是** JavDB 官方 API（那是 `javdb`），
#: 它是第三方开放站 api.thejavdb.net；`dmm_web` 才是 FANZA/DMM 官方 GraphQL。
#: 这个混淆历史上导致过「主力源首位该放谁」的误判，UI 上必须写清楚。
SOURCE_LABELS: dict[str, str] = {
    "javdb": "JavDB（官方 App API）",
    "javmenu": "JavMenu（素人最佳）",
    "javmost": "JavMost",
    "javbus": "JavBus（有码大厂专精）",
    "dmm_web": "DMM / FANZA 官方（需日本出口）",
    "thejavdb": "TheJavDB（第三方 API）",
    "avmoo": "AVMOO",
    "javplace": "JavPlace（命中即字段全）",
    "javdb_new": "JavDB 新版（App 通道兜底）",
    "javdatabase": "JavDatabase（有码专精）",
    "freejavbt": "FreeJavBT",
}

# 🔴 自检：labels 必须覆盖 canon 序的每一个源，否则前端下拉会退化成裸源名
#    （如 "javplace" 这种用户看不懂的内部标识）。新增 canon 源时若忘了加标签，
#    这个断言会在 import 时立刻炸，而不是等到界面上才发现。
def _assert_labels_complete() -> None:
    from app.scraper.canon import AUX_SOURCE_ORDER, JP_SOURCE_ORDER, \
        AMATEUR_SOURCE_ORDER, MAINSTREAM_SOURCE_ORDER
    need = set(AMATEUR_SOURCE_ORDER) | set(MAINSTREAM_SOURCE_ORDER) \
        | set(AUX_SOURCE_ORDER) | set(JP_SOURCE_ORDER)
    missing = sorted(need - set(SOURCE_LABELS))
    if missing:
        raise RuntimeError(
            "source_order.SOURCE_LABELS 缺少展示名: %s —— 前端源下拉会显示内部标识"
            % missing)


_assert_labels_complete()


@router.get("")
async def get_source_order(
    code: str = Query("ABC-123", description="示例番号；决定走素人还是有码源序"),
):
    """返回 canon 的真实源序，供前端渲染源选择 UI 与说明文案。

    完整路径 = 前缀 ``/api/v1/source-order`` + 本路由的 ""（空），
    不能写成 "/source-order" —— 那会拼成 /api/v1/source-order/source-order（404）。

    前端**不应**再硬编码源名列表：源序随实测结论调整（2026-10-05 就把 DMM
    提到 thejavdb 之前、把 thejavdb 降为辅助源），硬编码必然漂移。
    """
    from app.scraper.canon import (
        AUX_SOURCE_ORDER,
        AMATEUR_SOURCE_ORDER,
        MAINSTREAM_SOURCE_ORDER,
        is_amateur_code,
        jp_fallback_order,
        jp_sources_available,
        source_order_for,
    )

    order = list(source_order_for(code))
    return {
        # 指定番号的实际尝试序（已含日本源与辅助源）
        "order": order,
        "mainstream": list(MAINSTREAM_SOURCE_ORDER),
        "amateur": list(AMATEUR_SOURCE_ORDER),
        "aux": list(AUX_SOURCE_ORDER),
        "jp": list(jp_fallback_order()),
        # 🔴 日本出口不可用时 dmm_web 会**静默**从 order 里消失（canon 的既定
        # 降级行为：宁可少一个源也不要整条链路因节点起不来而失败）。
        # 前端必须能区分「没配 DMM」和「DMM 此刻不可用」，否则界面会误导用户。
        "jp_available": jp_sources_available(),
        "is_amateur": is_amateur_code(code),
        "labels": SOURCE_LABELS,
    }
