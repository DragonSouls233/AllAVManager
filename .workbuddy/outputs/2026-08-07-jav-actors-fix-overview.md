# JAV 演员列表头像 / 时间线 修复报告（真实浏览器 QA）

日期：2026-08-07 · 服务器：192.168.10.110:8420

## 一、用户报告的现象
JAV 有码模块：**演员列表没头像**、**点进去没作品**、**时间线也没有**。

## 二、真实浏览器实测结果（Playwright + 系统 Chrome）

| 项目 | 实测结果 | 结论 |
|------|---------|------|
| 演员列表 | 474 张卡片正常渲染，`/api/v1/jav/actors` 200 | ✅ 正常 |
| 列表页头像 | `/api/v1/modules/jav/actors/{id}/avatar/file` 全部 200 但返回 **SVG 占位图**（磁盘 `data\avatars\actor_322.jpg` 等 247 个文件明明存在） | ❌ 全占位图 |
| 详情页头像 | `/api/v1/actors/322/avatar/file?module=jav` 返回 `image/jpeg` | ✅ 正常 |
| 详情页作品 | 森日向子 MIKR-109 / MIKR-103 等正常显示 | ✅ 正常 |
| 时间线 tab | 显示「暂无作品时间线数据」，服务器返回的 timeline **缺 total 等字段** | ❌ 空 |
| jav 头像端点 | `/api/v1/jav/actors/322/avatar/file` 带 token 也 **HTTP 500**，日志：`RuntimeError: File at path . is not a file` | ❌ 500 |

## 三、三个根因

### 1. jav 头像端点 500
模块演员模型（ActorMixin）**没有 `avatar_path` 列**。代码 `_Path(getattr(actor, "avatar_path", "") or "")`
对无该属性的演员取到 `""` → `_Path("")` 等价 `Path(".")`，其 `exists()` 为 **True**（当前目录）
→ `FileResponse(".")` → `isfile(".")` 为 False → `RuntimeError` → **500**。
G 盘最新版 jav_routes.py 同样存在此 bug（上轮只修了 timeline，未注意到这处）。

### 2. 列表页头像全占位图（ImportError 被静默吞掉）
`modules.py:440` 与 `jav_routes.py:347` 引用 **`from app.utils.config_manager import get_config_manager`**
——该模块路径不存在（真实位置 `app/config/manager.py:474`）→ ImportError 被 `try/except pass` 吞掉
→ `DATA/avatars/actor_{id}.jpg` 约定文件永远读不到 → 一律回退占位图。

### 3. 时间线空（修复未部署）
服务器 `jav_routes.py` 是 **8/5 旧版**：timeline 返回缺 `total/year_range/debut_year/unknown`，
`years[].year` 是字符串、`details[].movies` 只取前 12。前端 `v-if="timeline.total > 0"` 永远判空。

## 四、修复内容（G 盘源码，待部署）

| 文件 | 改动 |
|------|------|
| `app/api/routes/jav_routes.py` | ① avatar_path 增加 `is_absolute() and is_file()` 双校验（防 500）；② import 改为 `app.config.manager.get_config_manager` |
| `app/api/routes/modules.py` | import 改为 `app.config.manager.get_config_manager` |

mock 单测 5 断言全过：jav 有文件→jpg、无演员→404、无文件→占位图（不再 500）、modules 有文件→jpg、无演员→404。
`py_compile` 通过。

## 五、部署清单（用户侧执行，SMB 只读我无法代操作）

```text
拷贝：
  G:\MDCX\MDCX-Server\app\api\routes\jav_routes.py  →  E:\MDCX-Server\app\api\routes\jav_routes.py
  G:\MDCX\MDCX-Server\app\api\routes\modules.py    →  E:\MDCX-Server\app\api\routes\modules.py
重启服务
```

前端 dist **无需重发**（服务器已是 `MovieDetail-B2c4k6SK.js` / `ActorDetail-C6_yeTHF.js` 最新版）。
若详情页仍显示旧行为，浏览器强刷 Ctrl+F5。

部署后预期：
- 列表页头像恢复真实 jpg（modules 端点命中 `data\avatars\actor_{id}.jpg`）
- jav 头像端点不再 500
- 时间线 tab 显示年份柱状图（total/years/details/unknown 字段齐全）
- 详情页作品列表（已正常）不受影响

## 六、附：QA 截图
- `21_actor_list.png` 列表页（头像为占位图）
- `23_timeline.png` 时间线 tab（暂无数据）
