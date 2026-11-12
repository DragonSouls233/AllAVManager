# JAV 有码 / 无码 · 字幕下载增量接入方案

- 文档版本：v1.0（设计稿，未落地）
- 编写日期：2026-11-12
- 适用模块：`jav`（有码，含 `/jav/ltx` 复用页）、`uncensored`（无码）
- 状态：**仅设计与文档**。本次不修改任何代码/配置，不部署、不重启、不 git commit。
- 交付对象：可直接照做的后端 + 前端工程师

---

## 0. 可行性结论与代码核实记录

### 0.1 已由需求方实测确认（本方案直接采信，不再重复调研）

| 项 | 结论 |
|---|---|
| 参考项目 | `huangmoling/subtitle-matcher`：Go 独立 EXE、无 HTTP API，**只能移植逻辑**，不能调用 |
| subtitlecat | 搜索 `GET https://www.subtitlecat.com/index.php?search={code}` → 200 / 4 条；详情 `subs/{id}/{slug}.html` → 200 / 117KB，按 `Chinese (Simplified)` / `Chinese (Traditional)` 分块，块内 `href="/subs/{id}/{slug}-zh-CN.srt"`；下载 200 / 57,749 B / 4,375 行 / 标准 SRT；详情页 1~8s，**需要 Referer** |
| 爱译网 aiyi1 | 搜索 `GET https://www.aiyi1.com/?s={code}` → 200 / 29KB；列表页纯文本字段 `字幕语种：` / `字幕格式：` / `下载字幕 \| 15KB` / `文件名：` / `匹配视频：`，标题在 `<h2><a href="https://www.aiyi1.com/{id}.html">`；文章页 `class="main-content"` 内 `下载字幕` 链接指向 CDN（`https://a.hinimg.com/aiyi-files/...-zh-CN.srt`）；下载 200 / 62,432 B / 4,400 行 / 标准 SRT |
| javzimu | 免费额度约 2 次后强制 `turnstile_required`，纯 HTTP 不可用 → **不进主链路**，文档仅记为「未来可选」 |
| 实测环境 | 代理 `127.0.0.1:10808`、UA=Chrome/122、`Accept-Language: zh-CN` |

### 0.2 对 MDCX 现有资产的核实（含两处需要纠正的前提）

| 资产 | 核实结果 |
|---|---|
| 番号归一 | ✅ `app/scraper/number.py:1464 extract_number()` 返回 `NumberResult`（`number` 已剥离 `-C/-U/-UC/-CD1/-LTX` 后缀，`formatted` 为爬虫格式）。**本方案一律复用它，不自写番号正则** |
| 扫描器落库口径 | ✅ `app/tasks/jav_scanner.py` 用 `extract_number()` 得番号后写入 `code`；`is_chinese = flags["is_chinese"] or has_external_subtitle(...)`（`jav_scanner.py:590`）⇒ **同目录出现 .srt 后，下一次扫描会自动把 `is_chinese` 置 True** |
| 外挂字幕识别 | ✅ `app/tasks/base_scanner.py:225 dir_subtitle_stems()`、`:239 has_external_subtitle()`、`:270 find_external_subtitle()`（单部影片用，会真列一次目录） |
| 字幕字段 | ✅ `app/db/jav_models.py:32 is_chinese`、`:48 has_subtitle`（`index=True`，`server_default="0"`）。⚠️ `app/db/uncensored_models.py:24 UncensoredMovie` **只有 `is_chinese`，没有 `has_subtitle`** |
| `code` 约束 | ✅ `app/db/_module_mixins.py:27` `code` 单列 `unique=True`。**本方案不改它，也不新增任何与番号有关的列** |
| 代理 | ✅ `app/services/proxy_manager.py:532 get_effective_proxy_url(site="", url="")`，内置 xray 端口优先，支持站点/域名覆盖（`app/services/site_proxy.py:183 resolve()`）。⚠️ 全仓 `app/` 下目前**没有任何 `trust_env=False`**，本方案按要求显式设置 |
| 原子写 | ✅ `app/utils/atomic_write.py:35 _atomic_write()`：同目录 `mkstemp` → `write` → `fsync` → `os.replace`。**正是 SMB 网络盘需要的语义**，直接复用 |
| 后台任务 + 进度 | ✅ `app/services/media_repair.py:595 RepairJob` / `:629 _JOBS`（dataclass + `OrderedDict` + 淘汰）、`app/api/routes/jav_routes.py` 的 `_local_sync_state` 模块级 dict 轮询两种范式都在用 |
| 模块化路由范式 | ✅ `app/api/routes/previews.py:43/69/77/147`：独立 `APIRouter`，路径 `/{module}/{movie_id}`，用 `_normalize_module()` 校验、`_load_movie_brief()` 跨模块取 `code/file_path`。**本方案的 API 采用同一范式** |
| 编码嗅探 | ✅ `app/services/subtitle_matcher.py:189 detect_subtitle_encoding()`：UTF-8 BOM → UTF-16 BOM → 严格 UTF-8 → charset_normalizer + 常见中文字打分（已修 Big5/GBK 互判 bug）。直接复用，不重写 |
| 增量加列迁移 | ✅ `app/db/module_db.py:137 ModuleDatabase._migrate_schema()`：模块库初始化时按模型元数据遍历，对缺失列执行 `ALTER TABLE ADD COLUMN`（幂等）。另有旧 `app/db/migrations.py` 手写 DDL（system.db 用）。**结论：模型加列即可自动迁移，无需手写脚本** |
| `.strm` | ✅ `app/services/strm.py` 生成 `X.strm`；`Path("X.strm").stem == "X"` ⇒ 同目录写 `X.srt` 可被 Emby/Jellyfin 识别（但网络盘可能只读，见风险 R5） |

### 0.3 两处需要纠正的前提（重要，影响端点挂载）

1. **不存在「`jav_routes.list_movies` 被遮蔽」**。
   - `app/api/__init__.py:17` 把 `movies.router` 挂在 `/movies`，其列表是 `@router.get("")`（`movies.py:194`）→ 实际路径 `/api/v1/movies?module=jav`；
   - `jav_routes.router` 自带 `prefix="/jav"`（`jav_routes.py:27`）→ 列表是 `/api/v1/jav/movies`（`jav_routes.py:782`）；
   - 前端 `src/stores/jav.js:40` 明确调用 `getJavMovies()` → `src/api/jav.js` 的 `/jav/movies`。
   - 两者路径不重叠，各自都活着（`/api/v1/movies` 被 TVBox / 通用库页使用）。**但两条链路各有一套筛选参数，口径不同**，所以新功能不要挂到任一「列表」处理器上。
2. **播放器里已有一套「在线字幕」能力，勿混淆**：`app/services/subtitle_online.py`（仅 subtitlecat、**不走代理**、输出 WebVTT）+ `app/api/routes/player.py:391` 的 `/player/{movie_id}/subtitles/online/{search|files|load}`，前端在 `src/views/Play.vue` 用。它是「播放时临时挂字幕」，**不落盘**，与本需求正交。

> 由此定下的关键决策：**新功能独立成 router + 独立页面入口**，不改 `subtitle_online.py` / `subtitle_matcher.py` / `player.py`，不改任何既有列表接口。

---

## 1. 需求确认清单

| # | 需求 | 确认结论 | 备注 |
|---|---|---|---|
| R1 | 字幕来源 | subtitlecat + 爱译网（aiyi1）**两站并发搜索**，合并候选后选优 | 并发用 `asyncio.gather`，任一源失败不影响另一源 |
| R2 | 选优规则 | **简体优先**（zh-CN > zh-TW）；**同语言取文件最大**；下载失败按候选顺序**自动回退** | 大小未知时用一次 HEAD 探测补全（见 §3.5） |
| R3 | 使用范围 | **单条下载** + **批量补全** | 批量必须有并发上限与进度查询 |
| R4 | 落盘位置 | **与视频同目录**，文件名 `<视频名>.srt`（`Path(file_path).stem + ".srt"`） | Emby/Jellyfin/Plex 原生识别 |
| R5 | 落盘编码 | UTF-8（无 BOM），LF 换行，标准 SRT 时间轴 | 覆盖 UTF-16/BOM、全角冒号、`->`、4 位毫秒等异常 |
| R6 | 与现有扫描联动 | 写完即被 `has_external_subtitle()` 识别 → `has_subtitle`/`is_chinese` 置真 | 无需新增字段，无需新扫描器 |
| R7 | 已存在处理 | **默认跳过**；`overwrite=true` 时覆盖同名 `.srt` | 复用 `find_external_subtitle()` 口径，避免与库内徽标矛盾 |
| R8 | 对外请求约束 | 一律 `get_effective_proxy_url()` + `trust_env=False` + 分级限速 + 明确 UA/Referer | 见 §3.4 |
| R9 | 数据源范围 | **不新增数据源**；javzimu 不进主链路 | 仅留扩展点 |
| R10 | 用户可见文案 | 全量简体中文（含失败原因） | 见 §4.5 文案表 |
| R11 | 前端入口 | 仅在 **JAV 有码 / JAV 无码** 页面内**新增独立按钮**；不改/不替换既有入口；不塞全局侧栏 | 列表页 + 详情页各一处 |
| R12 | 不可改项 | `code` 单列 UNIQUE、现有扫描/播放器/列表接口 | 本次零改动 |

---

## 2. 总体方案

### 2.1 新增 / 修改文件清单

**新增（后端，6 个）**

| 相对路径 | 职责 | 预估行数 |
|---|---|---|
| `app/services/subtitle_fetcher.py` | 编排层：单条拉取、候选选优、失败回退、落盘、登记、批量任务注册表 | ~450 |
| `app/services/subtitle_sources/__init__.py` | 适配器注册表 `SOURCES`、公共导出 | ~30 |
| `app/services/subtitle_sources/base.py` | `SubtitleCandidate` / `SubtitleSource` 协议 / `RateGate` / `http_client()` / SRT 规范化 / 选优 / 登记读写 | ~320 |
| `app/services/subtitle_sources/subtitlecat.py` | subtitlecat 适配器（搜索页 + 详情页 + 下载链接解析） | ~180 |
| `app/services/subtitle_sources/aiyi1.py` | 爱译网适配器（列表页 + 文章页 + CDN 链接解析） | ~170 |
| `app/api/routes/subtitle_routes.py` | 4 个端点（状态 / 单条 / 批量启动 / 批量进度+取消） | ~200 |

**新增（前端，2 个）**

| 相对路径 | 职责 |
|---|---|
| `MDCX-Desktop/src/api/subtitle.js` | 4 个 API 封装（含长超时） |
| `MDCX-Desktop/src/components/SubtitleBatchDialog.vue` | 批量弹窗（筛选、并发、进度、结果、失败原因），被两个列表页复用 |

**修改（4 个）**

| 相对路径 | 改动 | 说明 |
|---|---|---|
| `app/api/__init__.py` | 1 行 `include_router` + import | 挂 `/subtitles` 前缀 |
| `MDCX-Desktop/src/views/jav/Movies.vue` | 工具条**新增** 1 个按钮 + 引入弹窗组件 | 不动既有 8 个按钮 |
| `MDCX-Desktop/src/views/uncensored/Movies.vue` | 同上 | 不动既有按钮 |
| `MDCX-Desktop/src/views/MovieDetail.vue` | `actions-bar` 内**新增** 1 个按钮 | `moduleType ∈ {jav, uncensored}` 时显示 |

**明确不改**

`app/db/jav_models.py`、`app/db/uncensored_models.py`、`app/db/_module_mixins.py`、`app/services/subtitle_online.py`、`app/services/subtitle_matcher.py`、`app/api/routes/player.py`、`app/api/routes/jav_routes.py`、`app/api/routes/uncensored_routes.py`、`app/api/routes/movies.py`、任何配置文件。

**测试脚本（仓库既有风格：脚本式、带日期）**

`tests/test_subtitle_download_2026-11-12.py`（离线夹具 + 可选 `--live` 真实联网）

### 2.2 API 挂载位置（决策）

新建独立 router：`app/api/routes/subtitle_routes.py`，`prefix="/subtitles"`，路径带 `{module}` 段（与 `previews.py` 一致）：

```
/api/v1/subtitles/{module}/{movie_id}/status
/api/v1/subtitles/{module}/{movie_id}/download
/api/v1/subtitles/{module}/batch
/api/v1/subtitles/{module}/batch/{job_id}
/api/v1/subtitles/{module}/batch/{job_id}/cancel
```

**理由**：① 一份实现同时服务 `jav` / `uncensored`（两个模块库的 `movie_id` 会撞号，必须显式带 `module`）；② 不碰 `jav_routes` / `uncensored_routes` 里现有的 `/{movie_id}` 通配，杜绝路由顺序踩踏；③ 与 `previews.py` 的既有范式一致，评审成本最低。

**前端如何定位详情页模块**：`MovieDetail.vue:320` 已有 `MODULE_MAP` + `route.path.split('/')[1]` 得到 `moduleType`，直接透传给新 API 即可，无需新增路由逻辑。

### 2.3 调用时序（单条）

```
前端(详情页)              路由层                     编排层                       适配器/网络
    │  POST /subtitles/jav/12/download
    │────────────────────>│
    │                     │ 读 JavMovie(file_path, code)
    │                     │ ① 已有字幕? ──yes──> 200 {status:"skipped"}
    │                     │ ② extract_number(code) 兜底
    │                     │ ③ 建 45s 预算
    │                     │──fetch_for_movie()──>│
    │                     │                      │ gather(2 个任务)
    │                     │                      │──search("SSIS-001")──> subtitlecat ┐ (700ms/20s/2)
    │                     │                      │──search("SSIS-001")──> aiyi1      ┘ (1000ms/15s/1)
    │                     │                      │ 合并去重 → 番号校验 → (可选)HEAD 补大小
    │                     │                      │ 排序取候选 → 依次 download()
    │                     │                      │   subtitlecat 需 Referer=详情页
    │                     │                      │   aiyi1 需 Referer=文章页
    │                     │                      │ normalize_srt() → UTF-8 无 BOM
    │                     │                      │ atomic_write_bytes(同目录 X.srt)
    │                     │                      │ 写 download_registry.json
    │                     │                      │ UPDATE 该行 is_chinese/has_subtitle
    │<──200 {status,source,language,path,bytes,lines,elapsed_ms,attempts}──│
```

### 2.4 调用时序（批量）

```
前端(列表页)              路由层                     编排层（job 注册表）
    │ POST /subtitles/jav/batch {only_missing:true,limit:200,concurrency:2}
    │───────────────────>│ 查库取 movie_id 列表
    │                    │ 建 BatchJob -> asyncio.create_task(_run_batch)
    │<──{job_id,total}───│
    │ GET .../batch/{id} （每 2s 轮询；页面卸载即停）
    │───────────────────>│ job.to_dict() -> {status,done,total,items[]}
```

`_run_batch` 内部语义 = `asyncio.Semaphore(concurrency)` 包裹 N 次 `fetch_for_movie()`；**全部限速闸门是进程级共享的**，所以并发提高只减少排队等待，不会突破站点限速。

---

## 3. 后端服务设计

### 3.1 数据结构（`subtitle_sources/base.py`）

```python
from dataclasses import dataclass, field
from typing import Protocol, Literal

LangCode = Literal["zh-CN", "zh-TW"]

LANG_RANK = {"zh-CN": 2, "zh-TW": 1}      # 简体优先
LANG_LABEL = {"zh-CN": "简体中文", "zh-TW": "繁体中文"}
SOURCE_LABEL = {"subtitlecat": "SubtitleCat", "aiyi1": "爱译网"}
SOURCE_PRIORITY = {"subtitlecat": 0, "aiyi1": 1}   # 同分时的稳定次序


@dataclass(frozen=True, slots=True)
class SubtitleCandidate:
    """一个「可下载的单个语种字幕文件」——不是「一个搜索结果」。"""
    source: str                 # "subtitlecat" | "aiyi1"
    language: str               # "zh-CN" | "zh-TW"
    title: str                  # 搜索命中的标题原文（用于番号校验 + 前端展示）
    detail_url: str             # 详情/文章页（同时作为 Referer）
    download_url: str           # .srt 直链（subtitlecat 站内 / aiyi1 CDN）
    referer: str                # 下载时必须带的 Referer
    size_declared: int | None = None   # 列表页声明大小（aiyi1 有；subtitlecat 常为 None）
    file_name: str = ""                # 源站文件名，仅用于日志

    @property
    def sort_key(self) -> tuple:
        return (
            -LANG_RANK.get(self.language, 0),
            -(self.size_declared or 0),
            SOURCE_PRIORITY.get(self.source, 9),
            self.title,
        )


class SubtitleSource(Protocol):
    name: str

    async def search(self, code: str, *, budget: "Budget") -> list[SubtitleCandidate]: ...
    async def probe_size(self, cand: SubtitleCandidate) -> int | None: ...
    async def download(self, cand: SubtitleCandidate) -> bytes: ...


@dataclass
class Budget:
    """单部影片的时间预算（monotonic 截止时刻）。"""
    deadline: float
    def left(self) -> float: ...              # max(0, deadline - monotonic())
    def expired(self) -> bool: ...
    def clamp(self, seconds: float) -> float: # min(seconds, left())
```

**适配器接口形态说明**

- `search()` 只返回**已经确认语种**的候选（subtitlecat 从 `-zh-CN.srt` / `-zh-TW.srt` 反推语种；aiyi1 从 `字幕语种：` 字段映射）。解析不到语种的候选直接丢弃，`language` 不允许为空。
- `probe_size()` 只允许发 **HEAD**（subtitlecat 站内）；aiyi1 直接返回 `size_declared`，不发请求。
- `download()` 只负责取字节，**不做格式转换**（转换在编排层统一做，便于两源一致）。

### 3.2 适配器：subtitlecat（`subtitle_sources/subtitlecat.py`）

```python
class SubtitleCatSource:
    name = "subtitlecat"
    SITE = "https://www.subtitlecat.com"

    async def search(self, code: str, *, budget: Budget) -> list[SubtitleCandidate]:
        # 1) GET /index.php?search={code}  （限速闸门：间隔 700ms / 读超时 20s / 重试 2 次）
        # 2) bs4 解析：结果表内的 <a href="/subs/{id}/{slug}.html">，
        #    标题文本必须通过 _title_matches_code() 校验（见 §3.6）
        # 3) 逐条 GET 详情页（串行！每条都过闸门；预算不足立即返回已得结果）
        #    - 按块定位 "Chinese (Simplified)" / "Chinese (Traditional)"
        #    - 块内正则取 href="/subs/{id}/{slug}-zh-CN.srt" | -zh-TW.srt
        # 4) 详情页异常（超时/结构变化）→ 跳过该条，不中断整体
```

**关键实现约束**

| 约束 | 值 |
|---|---|
| 搜索结果上限 | 取前 **4** 条详情页（实测约 4 条；多取只增耗时，不增命中率） |
| 详情页超时 | `timeout=Timeout(connect=8, read=20)`；实测 1~8s |
| 详情页 Referer | 搜索结果页 `https://www.subtitlecat.com/index.php?search={code}` |
| 下载 Referer | 该候选的 `detail_url`（必须带，否则可能 403） |
| 链接合法性 | 只接受 `https://www.subtitlecat.com/subs/{digits}/{slug}.srt`（host/scheme/path 白名单校验，防 SSRF/跳转注入） |
| Cloudflare 判据 | 响应 403/503 或正文含 `Just a moment` / `cf-chl` → 抛 `SourceBlocked`，归因 `blocked` |

### 3.3 适配器：爱译网（`subtitle_sources/aiyi1.py`）

```python
class Aiyi1Source:
    name = "aiyi1"
    SITE = "https://www.aiyi1.com"

    async def search(self, code: str, *, budget: Budget) -> list[SubtitleCandidate]:
        # 1) GET /?s={code}  （闸门：间隔 1000ms / 读超时 15s / 重试 1 次）
        # 2) bs4：标题链接 <h2><a href="https://www.aiyi1.com/{id}.html">
        #    块内纯文本字段正则：
        #      语种  r"字幕语种[：:]\s*(简体|繁体|英文|[^\s<]+)"
        #      格式  r"字幕格式[：:]\s*([A-Za-z0-9]+)"
        #      大小  r"下载字幕\s*[|｜]\s*([\d.]+\s*[KMG]B)"   → 换算为字节
        #      文件  r"文件名[：:]\s*([^\n<]+)"
        # 3) 标题校验同 §3.6
        # 4) 逐条 GET 文章页（串行、过闸门、受预算约束）
        #    - bs4 取 .main-content 内 a:contains("下载字幕") 的 href（可能是相对/协议相对）
        #    - 只接受 https + host ∈ {a.hinimg.com, *.aiyi1.com}
        #    - 下载 Referer = 文章页 URL
```

**语种映射**：`简体 → zh-CN`、`繁体 → zh-TW`；其它语种（英文/日文）**不产生候选**（本需求只要中文）。

**格式过滤**：`字幕格式` 非 `SRT`（如 ASS/SSA）时仍可生成候选（下载后统一规范化为 SRT），但排序时排在 SRT 之后 —— 通过 `size_declared` 之外的隐含规则实现：在 `search()` 内把非 SRT 候选的 `SOURCE_PRIORITY` 等效降级（实现上给候选加 `fmt` 字段并进 `sort_key`，`fmt_rank = {"srt": 0, "ass": 1, "ssa": 1}`）。

> 说明：上述为「可选强化」。若团队希望严格对齐「只接受 SRT」，则直接丢弃非 SRT 候选，实现更简单，验收不受影响。

### 3.4 网络层：代理 / UA / 限速 / 超时 / 重试

```python
# subtitle_sources/base.py

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def http_client(url: str, *, timeout: httpx.Timeout, site_key: str = "") -> httpx.AsyncClient:
    """唯一出网入口：代理只来自 get_effective_proxy_url()，且 trust_env=False。"""
    from app.services.proxy_manager import get_effective_proxy_url
    return httpx.AsyncClient(
        proxy=get_effective_proxy_url(site=site_key, url=url),   # None → 直连
        trust_env=False,          # 忽略 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY，避免双重代理
        timeout=timeout,
        follow_redirects=True,
        headers=BASE_HEADERS,
    )
```

**限速闸门（进程级共享，跨请求/跨批量任务有效）**

```python
@dataclass(frozen=True)
class RatePolicy:
    min_interval: float    # 两次请求最小间隔（秒）——唯一硬约束
    read_timeout: float    # 单次读超时（秒）
    retries: int           # 额外重试次数（429 走指数退避，仍受此上限约束）
    window: float = 0.0    # 可选滑动窗口（0 = 不启用，默认关闭）
    max_in_window: int = 0

POLICIES: dict[str, RatePolicy] = {
    # 站点            间隔   读超时 重试
    "subtitlecat":   RatePolicy(0.70, 20.0, 2),
    "aiyi1":         RatePolicy(1.00, 15.0, 1),
    "subtitle_cdn":  RatePolicy(0.20, 60.0, 2),   # 字幕文件（含 subtitlecat /subs/ 与 a.hinimg.com）
}

class RateGate:
    """按 min_interval 串行放行。asyncio.Lock 保护，跨任务共享。"""
    async def acquire(self, budget: Budget | None = None) -> float:
        ...  # 预算不足以等到下一个放行点时抛 BudgetExceeded，而不是干等
```

> 🔴 **三元组的含义是「请求间隔 / 读超时 / 重试次数」，不是「间隔 / 窗口 / 次数」。**
> 字幕 CDN 的实际口径是**间隔 200ms**；若误读成「2 次 / 60s」，批量吞吐会慢近百倍（详见附录 C）。

- 闸门按**域名**取键：`subtitlecat.com` → `subtitlecat`；`aiyi1.com` → `aiyi1`；`a.hinimg.com` 与 `subtitlecat.com/subs/*.srt` → `subtitle_cdn`。
- 闸门实现在**同一个事件循环**内共享（`_GATES: dict[str, RateGate]` 惰性创建），批量任务与单条请求共用，天然不会被并发打穿。
- ⚠️ **吞吐量预期**：`subtitle_cdn` 只约束**间隔 200ms**（不是「2 次 / 60s」）。单部影片的主要耗时来自 `subtitlecat` 的 0.7s 间隔 + 详情页串行抓取（实测单部约 17~22s），CDN 200ms 几乎不构成瓶颈。若仍嫌慢，只改 `POLICIES` 一个常量，**不改任何调用点**。

**超时与重试**

| 场景 | connect | read | 总预算 |
|---|---|---|---|
| 搜索页（两站） | 8s | 15s | `min(20s, budget.left())` |
| subtitlecat 详情页 | 8s | 20s | 同上（串行累计受 45s 卡口） |
| 字幕文件下载 | 8s | 30s | `min(30s, budget.left())` |
| 单部影片整体 | — | — | **45s**（`asyncio.timeout`） |

- 重试：仅对 `httpx.ConnectError / ReadTimeout / 5xx` 重试 **1 次**（共 2 次尝试），退避 `0.8s`；`403/404/解析失败` **不重试**（重试只会加速封禁）。
- 任何一次重试前都要重新过闸门。

**大小上限**：单文件 `MAX_BYTES = 4 MiB`（流式读取，超限即 abort），与 `subtitle_online.py:21` 保持一致。

### 3.5 候选合并、选优与回退

```python
def merge_and_rank(cands: list[SubtitleCandidate]) -> list[SubtitleCandidate]:
    """去重（download_url 归一后相同视为同一份）+ 排序。"""
    # 排序键：语言(简>繁) > size_declared 降序 > 源优先级 > 标题
    return sorted(dedup(cands), key=lambda c: c.sort_key)
```

**选优/回退流程（编排层，`fetch_for_movie` 内）**

```
1. 两站并发 search（gather(return_exceptions=True)），各自受预算约束
2. 合并去重 → _title_matches_code() 过滤（§3.6）
3. 空 → 归因 site_empty，结束
4. 语言分层：取「最高语言层」（有 zh-CN 就丢掉 zh-TW）
5. 该层内若存在 size 未知的候选，且层内候选数 > 1：
     对每个未知项调 source.probe_size()（最多 3 个，受预算与 CDN 闸门约束）
     探测失败/超预算 → 视为 None（排序时按 0 处理，不阻塞）
6. 重新排序，得到候选队列
7. for cand in queue[:3]:            # 最多尝试 3 个
       通过闸门 → download() → normalize_srt() → 写盘
       成功 → 返回 downloaded
       失败 → attempts.append({...}) 继续下一个
8. 全部失败 → 归因 download_failed（若全是超时则 timeout）
```

**为什么「同语言取最大」要探测**：subtitlecat 详情页不给文件大小（实测 117KB HTML 内无 size），而 aiyi1 列表页给 `下载字幕 | 15KB`。若不探测，`size` 两侧不可比，「取最大」会退化成「aiyi1 必胜」。用一次 HEAD 补全（`Content-Length`）即可让规则真正生效，代价可控（≤3 次请求，且命中 CDN 闸门）。

### 3.6 番号匹配守卫（防误匹配，硬性）

```python
def normalize_code(raw: str) -> str:
    """唯一口径：复用 extract_number，禁止自写正则。"""
    from app.scraper.number import extract_number
    r = extract_number((raw or "").strip())
    return (r.number or "").strip().upper()

def _title_matches_code(title: str, code: str) -> bool:
    """标题归一化后必须包含目标番号（且数字边界精确）。

    1) 优先：extract_number(title).number == code  → 命中
    2) 兜底：标题里出现 `(?<![A-Z0-9])CODE(?![0-9])`（`_`→`-` 后比较）
       —— 为覆盖「标题里只有一个长标题、番号嵌在中间」的情况
    """
```

- 目标番号来源优先级：`movie.code` → 失败则 `extract_number_from_path(movie.file_path)`（`number.py:2220`）。
- 两处都取不到 → 归因 `no_number`，不发任何网络请求。
- 该守卫同时用于：① subtitlecat 搜索结果过滤（已有等价物 `subtitle_online.py:137 _matches`，逻辑一致但**不复用其代码**）；② aiyi1 列表标题过滤。

> 为什么不复用 `subtitle_online._extract_code`：它是独立的正则（`subtitle_online.py:123`），与本仓 `extract_number` 口径不同（例如 `259LUXU-1004`、`-CD1`、`-LTX` 处理不一致）。本方案统一走 `extract_number`，避免「下载器认得出、库里认不出」的双口径。

### 3.7 时间轴规范化（`normalize_srt`）

```python
def normalize_srt(raw: bytes) -> tuple[str, dict]:
    """字节 → 标准 SRT 文本（UTF-8、LF、块号 1..N）。

    Returns:
        (text, meta)  meta = {
            "source_encoding": "gbk" | "utf-16" | "utf-8-sig" | ...,
            "lines": 4375,          # 非空行数（用于前端展示/质检参考）
            "blocks": 1120,         # 有效字幕块数
            "fixes": ["fullwidth_colon", "arrow", "zero_width", "ms4",
                      "dup_minute", "reindex", "bom"],   # 实际生效的修复项
            "dropped": 2,           # 被丢弃的空块/无时间轴块
        }
    """
```

**处理规则（按顺序执行，每条都要有单元测试）**

| # | 规则 | 实现要点 |
|---|---|---|
| N1 | 解码 | `subtitle_matcher.detect_subtitle_encoding(raw)`（`subtitle_matcher.py:189`）→ `raw.decode(enc, errors="replace")` |
| N2 | BOM / 换行 | 去 `\ufeff`；`\r\n`、`\r` → `\n` |
| N3 | 零宽字符 | 删除 `\u200b \u200c \u2060 \ufeff`，**保留 `\u200d`（ZWJ，泰/表情合成会用到，误删会改字）** |
| N4 | 全角→半角 | 时间轴上：`：`→`:`、`．`/`。`→`.`、全角数字 ０-９ → 0-9（**只处理时间轴行**，正文里的中文标点保持原样） |
| N5 | 箭头 | `->`、`-->`、`—>`、`–>`、`＞` → `-->`；两段间多余空格归一 |
| N6 | 分钟重复 | 形如 `00:01:02:03,000`（4 段）→ 取 `HH:MM:SS,mmm`；形如 `00:00:01:00:00,200`（小时+分钟重复）→ 取末尾 3 段 |
| N7 | 4 位毫秒 | `,1234` → `,123`（截断，不四舍五入，避免累计漂移） |
| N8 | 时间合法性 | `end <= start` 时 `end = start + 1.0s`；单块超过 60s 不改（真实长镜头字幕存在） |
| N9 | 块重建 | 丢弃无时间轴的块、空文本块；块号强制重排 1..N；块间单空行；文件末尾单个 `\n` |
| N10 | 输出 | **UTF-8 无 BOM**（Emby/Jellyfin/Plex 均可识别；BOM 在某些老播放器上会显示为乱码字符） |

**不做的事（明确边界）**：不做机器翻译、不做简繁转换、不做时间轴对齐（字幕与视频版本不匹配属于内容问题，见风险 R7）。

### 3.8 写盘

```python
def srt_target_path(video_path: str | Path) -> Path:
    """<视频名>.srt —— 与视频严格同目录。"""
    p = Path(video_path)
    return p.with_name(p.stem + ".srt")

async def write_subtitle(video_path: str, text: str) -> Path:
    """原子写：同目录 .tmp → fsync → os.replace（SMB 安全）。"""
    from app.utils.atomic_write import atomic_write_bytes
    target = srt_target_path(video_path)
    await asyncio.to_thread(atomic_write_bytes, target, text.encode("utf-8"))
    return target
```

| 规则 | 行为 |
|---|---|
| 已存在判断 | `find_external_subtitle(video_path, code)`（`base_scanner.py:270`）为真 → `skipped/already_exists`；`overwrite=true` 时只跳过该判断 |
| 目录不存在 | `write_failed`，文案「视频目录不存在或已离线」 |
| 权限/断连（`PermissionError`/`OSError`） | `write_failed`，文案「写入视频目录失败（可能是网络盘只读或磁盘已满）」；**不留下半截文件**（原子写保证） |
| `.strm` 占位 | `Path("X.strm").stem == "X"` → 写 `X.srt`，与 Emby 约定一致 |
| 多分卷（`-CD1`/`-CD2`） | 各分卷各自写自己的同名 `.srt`（不跨分卷复制），见风险 R7 |
| 编码 | UTF-8 无 BOM，LF |

### 3.9 落盘登记（解决「来源/时间/可重试」，**避免加列**）

`data/subtitles/download_registry.json`（路径用 `get_config_manager().computed.data_dir`，与 `subtitle_quality` 同思路）：

```json
{
  "version": 1,
  "items": {
    "Y:\\jav\\SSIS-001\\SSIS-001-C.mp4": {
      "code": "SSIS-001",
      "path": "Y:\\jav\\SSIS-001\\SSIS-001-C.srt",
      "source": "subtitlecat",
      "source_label": "SubtitleCat",
      "language": "zh-CN",
      "bytes": 57749,
      "lines": 4375,
      "status": "downloaded",
      "reason": null,
      "at": "2026-11-12T21:03:11+08:00"
    }
  }
}
```

- 写入用 `atomic_write_json`（`app/utils/atomic_write.py:68`）+ 进程内 `asyncio.Lock`；读取失败/损坏 → 返回空登记（不让页面崩）。
- 上限 5000 条，超出按 `at` 淘汰最旧（FIFO），与 `media_repair._evict_jobs()` 同思路。
- 该文件**只用于展示与排查**，不参与「是否已有字幕」的判定（判定永远以磁盘为准，避免登记与磁盘不一致）。

### 3.10 编排层接口（`app/services/subtitle_fetcher.py`）

```python
# ---------- 归因枚举（对外即 reason 字段，前端按此映射中文） ----------
class FailReason(str, Enum):
    NO_NUMBER = "no_number"                 # 无法识别番号
    NO_FILE_PATH = "no_file_path"           # 影片没有本地文件路径
    ALREADY_EXISTS = "already_exists"       # 已有字幕，跳过
    SITE_EMPTY = "site_empty"               # 两个站点都没有结果
    BLOCKED = "blocked"                     # 站点拦截/Cloudflare/结构变化
    TIMEOUT = "timeout"                     # 超出时间预算
    DOWNLOAD_FAILED = "download_failed"     # 文件下载/校验失败
    WRITE_FAILED = "write_failed"           # 写视频目录失败
    CANCELLED = "cancelled"                 # 批量任务被取消


@dataclass
class FetchResult:
    ok: bool
    status: str                       # downloaded | skipped | failed
    movie_id: int | None
    code: str
    reason: FailReason | None
    message: str                      # 简体中文，可直接回显
    source: str | None = None
    source_label: str | None = None
    language: str | None = None
    language_label: str | None = None
    path: str | None = None
    bytes: int = 0
    lines: int = 0
    elapsed_ms: int = 0
    candidates_total: int = 0
    attempts: list[dict] = field(default_factory=list)   # [{source,language,ok,reason,message,elapsed_ms}]

    def to_dict(self) -> dict: ...


async def fetch_for_movie(
    module: str,
    movie_id: int,
    *,
    overwrite: bool = False,
    file_path: str | None = None,     # 批量路径已查好则传入，省一次 DB 查询
    code: str | None = None,
    budget_s: float = 45.0,
) -> FetchResult: ...


async def fetch_for_code(
    code: str,
    *,
    file_path: str,
    overwrite: bool = False,
    budget_s: float = 45.0,
) -> FetchResult:
    """跳过 DB 的纯能力入口（给脚本/测试用，也是单条端点的实现内核）。"""


# ---------- 批量（进程内任务注册表，仿 media_repair） ----------
@dataclass
class BatchJob:
    id: str
    module: str
    total: int
    concurrency: int
    status: str = "queued"          # queued | running | done | cancelled | failed
    done: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    current: dict | None = None
    items: list[dict] = field(default_factory=list)   # 最多保留 500 条明细
    started_at: float = ...
    finished_at: float | None = None
    cancel_requested: bool = False
    def to_dict(self) -> dict: ...


async def start_batch(
    module: str,
    *,
    movie_ids: list[int] | None = None,
    only_missing: bool = True,
    keyword: str | None = None,
    code_prefix: str | None = None,
    limit: int = 200,
    concurrency: int = 2,
    overwrite: bool = False,
) -> dict: ...      # {"job_id": "...", "total": N, "message": "..."}

def get_batch(job_id: str) -> dict | None: ...
def list_batches(module: str, limit: int = 5) -> list[dict]: ...
def cancel_batch(job_id: str) -> dict: ...
```

**批量选片 SQL（两模块通用，禁止跨模块混查）**

```python
# only_missing=True 时：仅取「本地尚无外挂字幕」的影片
stmt = select(Movie.id, Movie.code, Movie.file_path).where(Movie.file_path.isnot(None))
if only_missing:
    stmt = stmt.where(or_(Movie.has_subtitle.is_(None), Movie.has_subtitle == 0))  # 仅 jav 有该列
if keyword:     stmt = stmt.where(or_(Movie.title.like(f"%{keyword}%"), Movie.code.like(f"%{keyword}%")))
if code_prefix: stmt = stmt.where(Movie.code.startswith(code_prefix))
stmt = stmt.order_by(Movie.id.desc()).limit(min(limit, 500))
```

⚠️ **`only_missing` 的跨模块差异**：`uncensored` 库没有 `has_subtitle` 列，所以：
- 方案 A（推荐，零迁移）：`only_missing` 对 uncensored 退化为「按目录实时过滤」——取 `file_path` 后调用 `find_external_subtitle()`（每部一次 `iterdir`，200 部≈毫秒级~秒级，可接受）；
- 方案 B（若后续要给无码也加「有字幕」筛选）：把 `has_subtitle` 列加到 `UncensoredMovie`，`module_db._migrate_schema()` 会自动 `ALTER TABLE ADD COLUMN`，无需手写迁移。**本期不做**，见 §5。

**并发与取消**

- `concurrency` 取值 `1..4`，默认 2；用 `asyncio.Semaphore` 控制，**同时只允许一个批量任务在跑**（第二个请求直接复用/拒绝，避免重复打站）。
- `cancel_batch` 置 `cancel_requested=True`，worker 在每个影片开始前检查；正在跑的单个 `fetch_for_movie` 最多再耗 45s 收尾，状态置 `cancelled`。
- 任务历史最多保留 20 个（`_evict()`），重启即丢（进度不持久化，见风险 R10）。

---

## 4. API 设计

统一前缀 `/api/v1/subtitles`，全部返回 JSON，`module ∈ {jav, uncensored}`（其余 404，文案「不支持的模块」）。

### 4.1 查询状态

```
GET /api/v1/subtitles/{module}/{movie_id}/status
```

```json
{
  "module": "jav",
  "movie_id": 12,
  "code": "SSIS-001",
  "file_path": "Y:\\jav\\SSIS-001\\SSIS-001-C.mp4",
  "has_subtitle": true,
  "target_path": "Y:\\jav\\SSIS-001\\SSIS-001-C.srt",
  "target_exists": true,
  "registry": {
    "source": "subtitlecat", "source_label": "SubtitleCat",
    "language": "zh-CN", "language_label": "简体中文",
    "bytes": 57749, "at": "2026-11-12T21:03:11+08:00"
  }
}
```

（`registry` 可为 `null`；`target_exists=false` 且 `has_subtitle=true` 说明字幕是 `ABC-123.chs.srt` 之类别的命名，前端仍显示「已有字幕」）

### 4.2 单条下载

```
POST /api/v1/subtitles/{module}/{movie_id}/download
Content-Type: application/json

{ "overwrite": false }
```

成功（200）：

```json
{
  "ok": true,
  "status": "downloaded",
  "movie_id": 12,
  "code": "SSIS-001",
  "source": "subtitlecat",
  "source_label": "SubtitleCat",
  "language": "zh-CN",
  "language_label": "简体中文",
  "bytes": 57749,
  "lines": 4375,
  "path": "Y:\\jav\\SSIS-001\\SSIS-001-C.srt",
  "elapsed_ms": 3120,
  "candidates_total": 3,
  "reason": null,
  "message": "已下载简体中文字幕并保存到视频同目录",
  "attempts": [
    {"source": "aiyi1", "language": "zh-CN", "ok": false, "reason": "download_failed",
     "message": "下载超时，已切换下一个候选", "elapsed_ms": 1520},
    {"source": "subtitlecat", "language": "zh-CN", "ok": true, "reason": null,
     "message": "", "elapsed_ms": 1600}
  ]
}
```

已存在（200，**不是错误**）：

```json
{ "ok": true, "status": "skipped", "reason": "already_exists",
  "message": "该影片已有字幕，已跳过",
  "path": "Y:\\jav\\SSIS-001\\SSIS-001-C.srt", "elapsed_ms": 3 }
```

失败（HTTP **200** + `ok:false`，避免前端 axios 抛错吞掉原因；只有「影片不存在」用 404、「模块不支持」用 404）：

```json
{ "ok": false, "status": "failed", "reason": "site_empty",
  "message": "两个站点都没有搜到该番号的字幕，可稍后重试或手动上传",
  "code": "SSIS-001", "elapsed_ms": 6210, "attempts": [] }
```

### 4.3 批量启动

```
POST /api/v1/subtitles/{module}/batch
```

```json
{
  "movie_ids": null,
  "only_missing": true,
  "keyword": null,
  "code_prefix": null,
  "limit": 200,
  "concurrency": 2,
  "overwrite": false
}
```

返回：

```json
{ "job_id": "sb1a2b3c4d001", "module": "jav", "total": 137,
  "concurrency": 2,
  "message": "已启动字幕补全，共 137 部（并发 2，预计较慢，请勿重复点击）" }
```

若已有同模块任务在跑：`409` + `{"detail": "字幕补全任务正在运行，请等待完成或先取消"}`。

### 4.4 批量进度 / 取消

```
GET  /api/v1/subtitles/{module}/batch/{job_id}
POST /api/v1/subtitles/{module}/batch/{job_id}/cancel
GET  /api/v1/subtitles/{module}/batch/latest          # 页面刷新后恢复进度（可选但建议）
```

```json
{
  "job_id": "sb1a2b3c4d001",
  "module": "jav",
  "status": "running",
  "total": 137, "done": 42, "ok": 31, "skipped": 8, "failed": 3,
  "concurrency": 2,
  "started_at": 1762950000.0, "finished_at": null,
  "eta_seconds": 1800,
  "current": { "movie_id": 88, "code": "ABP-123", "stage": "下载字幕中" },
  "items": [
    { "movie_id": 90, "code": "SSIS-001", "status": "downloaded", "reason": null,
      "message": "已下载简体中文字幕", "source": "subtitlecat", "elapsed_ms": 3120 },
    { "movie_id": 89, "code": "ABC-999", "status": "failed", "reason": "site_empty",
      "message": "两个站点都没有搜到该番号的字幕", "source": null, "elapsed_ms": 4100 }
  ]
}
```

`status ∈ queued | running | done | cancelled | failed`；`items` 只保留最近 500 条（前端表格 + 「只看失败」筛选够用）。

### 4.5 失败原因 → 中文文案（前端唯一映射源）

| reason | 中文提示 | 建议操作 |
|---|---|---|
| `already_exists` | 该影片已有字幕，已跳过 | 需要更新请用「覆盖」 |
| `no_number` | 无法从片名识别番号，无法搜索 | 手动核对片名 |
| `no_file_path` | 该影片没有本地文件路径，无法写入字幕 | 先补文件路径 |
| `site_empty` | 两个站点都没有搜到该番号的字幕 | 稍后重试 / 手动上传 |
| `blocked` | 站点暂时拒绝访问（可能触发风控），请稍后重试 | 检查代理 |
| `timeout` | 搜索或下载超时，请稍后重试 | 重试 |
| `download_failed` | 字幕文件下载失败，已尝试全部候选 | 重试 |
| `write_failed` | 写入视频目录失败（网络盘只读/磁盘已满） | 检查盘符权限 |
| `cancelled` | 已取消 | — |

前端不得直接展示 `reason` 原文；`message` 已由后端给出中文，可作为兜底。

---

## 5. 数据字段评估：**不加列足够**

### 5.1 为什么够

| 需求 | 现有能力 | 结论 |
|---|---|---|
| 「这部有没有字幕」 | `jav` 有 `has_subtitle`；两模块都有 `is_chinese`；扫描器已实现自愈（`jav_scanner.py:367-375`、`:694-735`） | 不加列 |
| 「字幕是不是中文」 | `jav_scanner.py:590` `is_chinese = flags[...] or has_sub`：**同目录出现任何外挂字幕即视为中文证据** | 不加列 |
| 「筛选/徽章」 | `jav_routes.py:849`、`movies.py:353` 已有 `has_subtitle=1` 筛选；前端 `jav/Movies.vue:68` 已有「有字幕」tab | 不加列 |
| 「来源/时间/失败原因」 | **不属于影片实体属性**，属于一次下载动作 | 存 `data/subtitles/download_registry.json` |
| 「可重试」 | 失败即无产物，重试就是再调一次接口 | 不需要字段 |

**额外收益（写盘后立即同步库）**——单条/批量成功后顺手 `UPDATE`，让页面无需等下次扫描：

```python
# jav
UPDATE movies SET has_subtitle = 1, is_chinese = 1 WHERE id = :mid
# uncensored（该库无 has_subtitle）
UPDATE movies SET is_chinese = 1 WHERE id = :mid
```

只置真、不置假（与扫描器「只加不减」口径一致），不引新列、不影响 `code` UNIQUE。

### 5.2 若将来确需加列（备选，本期不做）

| 字段 | 类型 | 用途 |
|---|---|---|
| `subtitle_source` | `String(20)` | 「字幕来自哪个站」的库内筛选 |
| `subtitle_fetched_at` | `DateTime` | 统计/「N 天前下载」 |
| `subtitle_lang` | `String(10)` | 简/繁筛选 |

**迁移方式（已核实，无需手写脚本）**：在 `JavMovie` / `UncensoredMovie` 上 `mapped_column(...)` 加列即可 —— 服务启动时 `ModuleDatabase.init()` → `_migrate_schema()`（`app/db/module_db.py:137-187`）会遍历模型元数据，对缺失列执行 `ALTER TABLE "movies" ADD COLUMN "subtitle_source" VARCHAR(20) DEFAULT NULL`，幂等、单列出错不影响其它列。约束：新列必须**可空或有默认值**（该函数的 SQLite 限制处理已覆盖）。

> 结论：**本期零迁移**。前端「来源」信息从 §4.1 的 `registry` 字段读，够用。

---

## 6. 前端设计

### 6.1 入口位置（严格按要求）

| 页面 | 文件 | 位置 | 形态 |
|---|---|---|---|
| JAV 有码 列表 | `src/views/jav/Movies.vue` | `.toolbar` 内，`导入 NFO` 按钮**之后**追加 | `<el-button type="primary" plain>` + `<el-icon><Download/></el-icon>` 文案「下载字幕」 |
| JAV 无码 列表 | `src/views/uncensored/Movies.vue` | `.toolbar` 内，`扫描目录` 之后追加 | 同上 |
| JAV 有码 / 无码 详情 | `src/views/MovieDetail.vue` | `.actions-bar` 内，`视频截图生成海报` 之后追加 | `<el-button>` 文案「下载字幕」，`moduleType ∈ {jav, uncensored}` 才渲染 |
| JAV · LTX 库（`/jav/ltx`） | 复用 `jav/Movies.vue` | 同上（组件复用，自动获得） | 无需额外改动 |

**硬性约束**：不改、不替换任何现有按钮；不加到全局侧栏/工具栏；不新增路由（弹窗形态）。

### 6.2 复用组件 `SubtitleBatchDialog.vue`

```vue
<SubtitleBatchDialog v-model="subtitleDlgVisible" module="jav" />
<SubtitleBatchDialog v-model="subtitleDlgVisible" module="uncensored" />
```

Props：`modelValue: Boolean`、`module: 'jav' | 'uncensored'`、可选 `presetKeyword`（用列表当前搜索词预填）。

界面结构：

```
┌ 批量下载字幕 ────────────────────────────────┐
│ 范围： ○ 仅缺字幕（推荐）   ○ 全部（含已有，覆盖）│
│ 数量上限：[200]  并发：[2 ▾]  （提示：站点限速，建议 1~2）│
│ 关键词过滤：[__________]（可选，预填列表当前搜索）      │
│ ⚠ 字幕来自第三方站点，仅供个人备份使用；下载速度受站点限速影响，请勿重复点击。│
│                                    [取消] [开始下载] │
│ ── 运行中 ───────────────────────────────── │
│ 进度 42/137  ██████░░░░░░ 31 成功 · 8 跳过 · 3 失败    │
│ 当前：ABP-123 下载字幕中…        [取消任务]            │
│ ── 结果（可折叠，默认只看失败）────────────────│
│ 番号     状态    来源       耗时    说明                │
│ ABC-999  失败    -          4.1s    两个站点都没有搜到…  │
└────────────────────────────────────────────┘
```

行为：

- 点击「开始下载」→ `POST .../batch` → 保存 `job_id` → `setInterval` 每 **2000ms** 轮询 `GET .../batch/{job_id}`。
- 轮询到 `status ∈ done|cancelled|failed` → 停止定时器；`ElMessage.success('字幕补全完成：成功 31，跳过 8，失败 3')`；触发列表 `loadMovies()`（或 `store.invalidateMovies()`）以刷新「有字幕」徽章。
- 弹窗 `@close`、组件 `onBeforeUnmount`、路由离开 → **必须 `clearInterval`**（对齐 `jav/Movies.vue` 现有 `startStatsPoll` / `onBeforeUnmount` 习惯）。
- 刷新页面后：`GET .../batch/latest`，若 `running` 则自动恢复弹窗与进度（可选，建议做，成本低）。
- 全程简体中文；`el-alert` 提示「第三方字幕，仅供个人备份」合规声明。

### 6.3 单条按钮交互（详情页）

```js
// MovieDetail.vue script setup 内新增（不动既有逻辑）
const subtitleLoading = ref(false)
async function downloadSubtitle () {
  subtitleLoading.value = true
  try {
    const res = await downloadMovieSubtitle(moduleType.value, movieId.value, { overwrite: false })
    const map = { downloaded: 'success', skipped: 'info', failed: 'error' }
    ElMessage[map[res.status] || 'info'](res.message || '已处理')
    if (res.status === 'downloaded') await load()   // 刷新「有字幕/中文」徽章
  } catch (e) {
    ElMessage.error('字幕下载失败：' + (e?.response?.data?.detail || e.message))
  } finally {
    subtitleLoading.value = false
  }
}
```

- 按钮上 `:loading="subtitleLoading"`，`title` 提示「从 SubtitleCat / 爱译网抓取中文字幕并保存到视频同目录（同名 .srt）」。
- 失败时把 `attempts` 折叠展示在 `ElMessageBox` 里（可选），便于排查「哪个站失败了」。

### 6.4 API 封装 `src/api/subtitle.js`

```js
import { api } from './index'

export function getSubtitleStatus (module, movieId) {
  return api.get(`/subtitles/${module}/${movieId}/status`)
}
// 单条：整链路 45s 预算 + 两站搜索，默认 60s 超时不够稳，放宽到 90s
export function downloadMovieSubtitle (module, movieId, data = {}) {
  return api.post(`/subtitles/${module}/${movieId}/download`, data, { timeout: 90000 })
}
export function startSubtitleBatch (module, data = {}) {
  return api.post(`/subtitles/${module}/batch`, data, { timeout: 30000 })
}
export function getSubtitleBatch (module, jobId) {
  return api.get(`/subtitles/${module}/batch/${jobId}`)
}
export function cancelSubtitleBatch (module, jobId) {
  return api.post(`/subtitles/${module}/batch/${jobId}/cancel`)
}
export function getLatestSubtitleBatch (module) {
  return api.get(`/subtitles/${module}/batch/latest`)
}
```

---

## 7. 任务分解（有序、含依赖、含改动文件与验收点）

> 顺序即依赖顺序。T1–T6 为后端串行，T7 起可并行（前端可先用 mock）。

| # | 任务 | 依赖 | 改动文件 | 验收点 |
|---|---|---|---|---|
| **T1** | 基础设施：`SubtitleCandidate`、`RateGate`、`http_client()`、`Budget`、`normalize_srt()`、选优 `merge_and_rank()`、登记读写 | — | `app/services/subtitle_sources/base.py`（新） | ① 单测：`normalize_srt()` 覆盖 N1–N10 全部规则（含 UTF-16 样本、全角冒号样本、4 位毫秒样本、`->` 样本），输出 UTF-8 无 BOM；② `RateGate` 单测：并发 acquire 时相邻两次放行间隔 ≥ `min_interval`（实测 708/710/713/713/714ms）；③ `merge_and_rank()` 简>繁、同语言大者优先 |
| **T2** | subtitlecat 适配器 | T1 | `app/services/subtitle_sources/subtitlecat.py`、`__init__.py` | 真实搜 `SSIS-001` 得 ≥1 条 `zh-CN` 候选；详情页解析出 `-zh-CN.srt` 直链；`_title_matches_code` 拒绝无关结果；403 归因 `blocked` |
| **T3** | 爱译网适配器 | T1 | `app/services/subtitle_sources/aiyi1.py` | 真实搜 `SSIS-001` 得候选，`字幕语种`→`zh-CN`、`下载字幕 \| NKB`→字节数；文章页取到 CDN 直链；下载 200 且 >10KB |
| **T4** | 编排：两站并发、番号守卫、选优、探测 size、失败回退、45s 预算 | T2、T3 | `app/services/subtitle_fetcher.py`（新） | ① 模拟「首个候选下载失败」→ 自动换候选并成功；② 两站都超时 → `reason=timeout`；③ 两站空 → `site_empty`；④ 单次调用总耗时 ≤ 45s（打表） |
| **T5** | 落盘 + 登记 + 库内同步 | T4 | `subtitle_fetcher.py` | ① 写成 `<视频名>.srt`；② 第二次调用返回 `skipped/already_exists`；③ 目录只读时返回 `write_failed` 且不留 `.tmp`；④ `data/subtitles/download_registry.json` 有记录 |
| **T6** | API：status / download / batch / progress / cancel | T5 | `app/api/routes/subtitle_routes.py`（新）、`app/api/__init__.py`（1 行） | ① `GET /api/v1/openapi.json` 能看到 5 个端点；② 单条返回结构与 §4.2 一致；③ 重复启动批量返回 409；④ 取消后 `status=cancelled` |
| **T7** | 前端 API + 批量弹窗组件 | T6（可先用 mock） | `src/api/subtitle.js`、`src/components/SubtitleBatchDialog.vue`（均新） | ① 启动→轮询→完成全流程通；② 关闭弹窗/离开页面无残留定时器（DevTools 校验）；③ 失败列表中文可读 |
| **T8** | 三个页面加入口 | T7 | `jav/Movies.vue`、`uncensored/Movies.vue`、`MovieDetail.vue` | ① 三个入口可见且既有按钮零变化；② `/jav/ltx` 自动获得入口；③ 详情页非 jav/uncensored 模块不显示按钮 |
| **T9** | 联调 + 真实用例 + 回归 | T8 | `tests/test_subtitle_download_2026-11-12.py`（新） | 见 §8 全部条目；`/api/v1/player/*`、`/jav/movies`、`/uncensored/movies` 响应无变化 |
| **T10** | 文档更新 | T9 | `docs/subtitle/DESIGN.md` 追加「实现偏差记录」小节 | 与实现一致；风险清单逐条有结论 |

**建议工作量拆分**：T1–T3 是「能拿到字节」，T4–T5 是「能正确落盘」，T6–T8 是「能点」，T9 是「敢上线」。

---

## 8. 验收标准

### 8.1 功能验收（必须全部通过）

1. **真实单条下载**：对库内 `SSIS-001`（`file_path` 真实存在）点「下载字幕」→ 返回 `status=downloaded`，`source` 为 subtitlecat 或 aiyi1，`language=zh-CN`，并在**视频同目录**生成 `SSIS-001*.srt`；用文本编辑器打开为**简体中文、时间轴正常**；文件头 3 字节不是 `EF BB BF`。
2. **落盘命名**：视频为 `Y:\jav\SSIS-001\SSIS-001-C.mp4` → 字幕必须是 `Y:\jav\SSIS-001\SSIS-001-C.srt`（`stem + .srt`，不是 `SSIS-001.srt`）。
3. **已有字幕跳过**：再点一次 → `status=skipped`、`reason=already_exists`、文案「该影片已有字幕，已跳过」，且**文件 mtime 不变**。
4. **站点无结果**：用一个不存在的番号（如 `ZZZZ-999`）→ `ok=false`、`reason=site_empty`、中文提示「两个站点都没有搜到该番号的字幕」，**耗时 ≤ 45s**，前端不弹空白错误框。
5. **无番号**：`code=""` 且文件名不含番号 → `reason=no_number`，**零网络请求**（抓包/日志确认）。
6. **失败回退**：人为让首候选返回 404（或临时改 URL）→ 日志出现 2 条 `attempts`，最终成功；把两站全部置为不可达 → `reason` 为 `timeout` 或 `download_failed`，不抛 500。
7. **批量并发与进度**：50 部影片启动批量（并发 2）→ 首 3s 内能拿到 `job_id`；轮询 `done/total` 单调递增；完成后 `ok+skipped+failed == total`；期间 `GET /health` 与 `/jav/movies` 响应 < 1s（不阻塞事件循环）。
8. **批量取消**：运行中点取消 → 10s 内 `status=cancelled`，且不再发起新的出网请求（日志验证）。
9. **代理与限速**：断开代理后单条请求 → `blocked`/`timeout`，**不出现长时间挂起**；开启代理后连续 10 部 → 服务端日志中 subtitlecat 相邻请求间隔 ≥ 700ms、aiyi1 ≥ 1000ms、字幕 CDN ≥ 200ms；站点无 403/429/验证码（`turnstile`）出现。
10. **不破坏既有功能**：`/api/v1/player/{id}/subtitles*`（本地/在线/VTT）、`/jav/movies`、`/uncensored/movies`、扫描器 `has_subtitle/is_chinese` 逻辑、`code` UNIQUE 均无回归。
11. **前端三入口**：`/jav/movies`、`/jav/ltx`、`/uncensored/movies` 各有独立「下载字幕」按钮；JAV/无码详情页各有单条按钮；其它模块详情页（fc2/chinese 等）**不出现**该按钮。
12. **零配置改动**：`git diff` 只含 §2.1 列出的文件；无 `config.yaml`/`*.json` 配置项新增；无新依赖（`httpx[socks]`/`bs4`/`lxml` 均已有）。

### 8.2 非功能验收

| 项 | 标准 |
|---|---|
| 事件循环阻塞 | 所有磁盘写/目录遍历走 `asyncio.to_thread`；批量 50 部期间 `/health` 无 >1s 抖动 |
| 内存 | 单文件 ≤ 4 MiB；`BatchJob.items` ≤ 500 条；任务历史 ≤ 20 个 |
| 幂等 | 同一影片并发两次单条请求 → 一次 `downloaded`、一次 `skipped`，不产生两个文件 |
| 可观测 | 每条失败日志含 `module/code/reason/elapsed_ms/source`；不带用户隐私路径进 INFO 级以外的堆栈 |

---

## 9. 风险与边界

| # | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| **R1** | **Cloudflare / 风控变化**（subtitlecat 加挑战、aiyi1 加验证码） | 全量失败，`reason=blocked` | ① 检测 `cf-chl`/`turnstile`/403/503 即快速失败（不重试、不放大流量）；② 文案明确「站点暂时拒绝访问」；③ 保留 `site_proxy` 覆盖能力（`get_effective_proxy_url(site=..., url=...)`，用户可给这两站配独立出口）→ **零代码改动即可换 IP** |
| **R2** | **站点改版**（HTML 结构/字段名变化） | 解析返回空 → `site_empty`，静默退化 | ① 解析器对「字段缺失」逐条容错，不因一个字段失败整页；② 每次搜索记录 `candidates_total` 与命中字段，便于 5 分钟定位；③ 单测用离线 HTML 夹具锁定结构，改版时改夹具即可 |
| **R3** | **限速被封** | 站点 403/429、IP 进黑名单 | ① 沿用参考项目口径：subtitlecat 0.7s / aiyi1 1.0s / CDN 0.2s **请求间隔**；② 闸门进程级共享，**并发提高不会突破限速**；③ 批量同模块同时只允许 1 个任务、并发默认 3；④ 403 立即失败（不重试）；⑤ 429 指数退避 1s→2s→4s（上限 30s，重试次数仍受 2 次上限约束）；⑥ **任务级源熔断**：同一任务内某源连续 5 次 blocked 后不再请求它（新任务重新探测） |
| **R4** | **批量吞吐受站点间隔约束**（单部约 17~22s，瓶颈是 subtitlecat 0.7s 间隔 + 详情页串行） | 200 部约 1 小时（并发 3 时更短） | ① 弹窗明确提示「站点限速，请勿重复点击」；② 支持取消；③ `POLICIES` 单点可调；④ 二次补全天然幂等（已下载的会被跳过）；⑤ 源级熔断避免对已封禁的源空转 |
| **R5** | **网络盘写权限 / 断连**（SMB 只读、盘符离线） | `write_failed`，任务大面积为失败 | ① 原子写保证不留半个文件；② 单部失败不影响批次；③ 文案指明「检查盘符权限/网络盘是否在线」；④ 建议上线前对目标盘做一次 `os.access` 试写检查（可放在批量启动前的预检，返回「3 个目录不可写」） |
| **R6** | **`.strm` 占位文件能否同目录写 .srt** | 若 strm 所在目录为只读（常见于「唯读来源」模式），写不进去 | ① 语义上正确（`X.strm` → `X.srt`，Emby 认）；② 实际取决于目录权限 → 归入 `write_failed` 并给明确文案；③ **不在本次做「写到 data 目录再软链」的兜底**（会引入新复杂度与跨盘问题），仅在文档标注 |
| **R7** | **字幕与视频版本不匹配**（不同片源/剪辑/分卷导致时间轴错位） | 字幕能显示但不同步 | ① 本设计只保证「文件存在且格式标准」，不做对齐；② 多分卷（`-CD1/-CD2`）各自写自身同名文件，不跨卷复制（避免整片字幕套到单卷上）；③ 已有 `subtitle_quality.check_subtitle_file()` 可做时长比对，**建议后续在单条成功后异步跑一次质检**（本期不做，避免范围膨胀） |
| **R8** | **版权与合规** | 第三方字幕版权归字幕组/译者 | ① 弹窗与文档明确「字幕来自第三方公开站点，仅供个人备份与学习，请勿传播/商用」；② 不内置镜像、不缓存到公共目录、不做分发接口；③ 遵守站点 robots 与限速，不并发轰炸 |
| **R9** | **解析逻辑重复**（新适配器 vs `subtitle_online.py`） | 两套 subtitlecat 解析，未来改版要改两处 | ① 本期**不动** `subtitle_online.py`（播放器在跑，改它风险 > 收益）；② 在 `subtitle_online.py` 头部注释标注「搜索/下载链路已由 `subtitle_fetcher` 取代，播放器在线字幕待统一」；③ 后续单独任务把 `subtitle_online.search/files/load` 改为委托 `subtitle_fetcher` 的底层方法 |
| **R10** | **批量进度不持久化** | 服务重启后进度丢失，前端轮询 404 | ① `latest` 返回 404 时前端提示「任务已结束或服务已重启」；② 前端停止轮询；③ 磁盘上的 .srt 与登记文件不受影响，重跑即幂等 |
| **R11** | **javzimu 不可用** | 少一个源 | 不进主链路；`SOURCES` 注册表留扩展点，未来接 `turnstile` 需要浏览器内核（`playwright` 已在依赖里），另立任务 |
| **R12** | **番号写法差异导致漏搜**（`SSIS-001` vs `SSIS001`、`259LUXU-1004`） | 搜不到 | ① 搜索词统一用 `extract_number(code).number`；② 对 subtitlecat 额外用「去连字符」变体再搜一次**仅在首选为空时**（1 次额外请求，走闸门）—— 可选优化，默认关闭以控流量 |

---

## 10. 未来可选（不在本期）

1. **javzimu**：需浏览器内核过 `turnstile`，成本高、稳定性差；等主链路稳定后单独评估。
2. **质检联动**：下载成功后调 `subtitle_quality.check_subtitle_file(record=True)`，把「字幕时长 vs 视频时长」写入既有质检登记，前端在详情页显示「字幕同步性：良好/偏移」。
3. **播放器在线字幕统一**：`subtitle_online.py` 改为委托 `subtitle_fetcher` 的解析层，顺带让播放器也走代理（当前播放器在线搜索**不走代理**，境外网络下会失败）。
4. **无码库加 `has_subtitle` 列**：让无码列表也支持「有字幕」筛选（`module_db._migrate_schema()` 自动迁移，零脚本）。
5. **手动上传本地字幕**：详情页支持选本地文件 → 规范化为 `<视频名>.srt`（同一落盘/登记路径，复用度高）。

---

## 附录 A：关键常量集中表（唯一调整点）

```python
# subtitle_sources/base.py 顶部，全部集中于此，禁止散落在适配器里
UA_VER               = "Chrome/122.0.0.0"
MAX_BYTES            = 4 * 1024 * 1024          # 单文件上限
POLICIES             = {"subtitlecat": (0.70, 20.0, 2),    # (间隔s, 读超时s, 重试次数)
                        "aiyi1":       (1.00, 15.0, 1),
                        "subtitle_cdn":(0.20, 60.0, 2)}     # 间隔 200ms，不是 2 次/60s
TIMEOUT_SEARCH       = dict(connect=8.0, read=15.0)
TIMEOUT_DETAIL       = dict(connect=8.0, read=20.0)
TIMEOUT_DOWNLOAD     = dict(connect=8.0, read=30.0)
RETRY_TIMES          = 1                        # 额外重试次数
RETRY_BACKOFF        = 0.8
VIDEO_BUDGET_S       = 45.0                     # 单部影片总预算
MAX_CANDIDATES_TRY   = 3                        # 最多尝试几个候选
SEARCH_RESULTS_LIMIT = 4                        # subtitlecat 详情页最多抓 4 条
BATCH_CONCURRENCY    = (1, 4, 3)                # (min, max, default)
BATCH_LIMIT_MAX      = 500                      # 服务层上限；scope=all 路由层再收紧到 200
JOB_HISTORY          = 20
JOB_ITEMS_KEEP       = 500
REGISTRY_KEEP        = 5000
```

## 附录 B：离线 HTML 夹具建议（`tests/fixtures/subtitle/`）

| 文件 | 用途 |
|---|---|
| `subtitlecat_search.html` | 搜索页（4 条结果，含 1 条无关标题用于验证守卫） |
| `subtitlecat_detail.html` | 详情页（简/繁两块，各 1 个 `.srt` 链接） |
| `aiyi1_search.html` | 列表页（简体 15KB / 繁体 62KB 两条，字段行完整） |
| `aiyi1_article.html` | 文章页（`.main-content` 内 CDN 直链） |
| `sample_gbk.srt` / `sample_utf16.srt` / `sample_weird_time.srt` | 规范化用例（GBK、UTF-16 BOM、全角冒号 + `->` + 4 位毫秒 + 分钟重复） |

---

## 附录 C：实现偏差记录（T10 填写）

### C.1 已落地但与设计稿不同的地方（均已验证）

| 设计条目 | 实际实现 | 偏差原因 | 影响 |
|---|---|---|---|
| §3.4 限速「subtitle_cdn 2 次 / 60s」 | **间隔 200ms**（`subtitle_cdn = (0.20, 60.0, 2)` 中的 60.0 是**读超时**、2 是**重试次数**） | 原三元组被误读成「间隔/窗口/次数」。参考项目口径是「间隔 / 超时 / 重试」，按窗口限流会让批量慢近百倍 | 批量吞吐恢复；实测单部 17~22s，CDN 200ms 不构成瓶颈 |
| §3.4 限速闸门「min_interval + 滑动窗口双约束」 | 只保留 `min_interval` 硬约束；`window/max_in_window` 字段保留但默认 0（关闭） | 同上，窗口约束本身是误读的产物 | 并发提高仍不突破间隔（实测 6 并发 acquire 间隔 201/202/203/204/201ms） |
| §4.3 批量并发默认 2 | **默认 3**（范围 1~4） | 单部主要耗时是站点间隔而非带宽，3 并发在闸门约束下不会加速封禁 | 吞吐提升，闸门仍是唯一限速源 |
| §4.3 批量 `limit` 默认 200 / 上限 500 | 路由层改为 **`movie_ids` 或 `scope=all + confirm + limit`**；`scope=all` 时 limit 上限 **200**；服务层 `BATCH_LIMIT_MAX` 仍为 500（供 `movie_ids` 指定列表用） | 空参数默认全库会「点一下就把全库跑起来」，风险不可接受 | 空 body / 空数组一律 400；全库必须三要素齐全 |
| §2.3 最多尝试 3 个候选（按 rank 截断） | `_trial_queue()`：先各源取头名，再按 rank 补满 3 个 | 纯 rank 截断会让「排名靠后的源」永远轮不到，该源整体挂掉时无候选可回退 | 跨源回退实测可用（subtitlecat 全失败 → aiyi1 成功，58,050 B） |
| §3.6 时间轴「含箭头即块起始」 | **两侧时间戳都能解析才算块起始**；正文里的 `-->` / `->` / `→` 原样保留 | 原实现在正文含箭头时会把整块连同后续正文行一起吞掉（QA P1-1） | 块数与正文一条不丢（三条样本 + 真实 SSIS-001 1339 块回归） |
| §9 R3「403/429 立即熔断（仅本次调用）」 | 403 立即失败；**429 指数退避 1s→2s→4s（≤30s）**；**任务级源熔断**：连续 5 次 blocked 后本任务跳过该源 | 单次调用内熔断对批量无意义，下一部仍会打同一个已封禁的源 | 8 部压测：第 6 部起该源 0 请求，任务正常收尾，`sources.*.circuit_open=true` |
| 单条请求无 per-movie 锁 | 未加锁（依赖原子写保证文件不损坏） | 不扩大范围；并发同一影片属低频操作 | 极端并发下可能两次都 `downloaded`（幂等性由原子写与二次覆盖兜底）——**本期不修** |
| §4.3 无码 `only_missing` | 无码表没有 `has_subtitle` 列 ⇒ 逐部 `find_external_subtitle()`（一次 listdir） | 不改表结构是硬约束 | 无码批量选片多一次目录 IO；**性能未优化，本期不修** |
| 爱译网「字幕格式」字段 | 非 SRT（ASS/SSA）候选**直接丢弃**，不做转换 | 规范化只输出 SRT，写出非 SRT 内容会污染播放器 | 命中率略降；宁缺勿错 |
| §5 批量进度持久化 | 仍为内存态，服务重启后 `latest` 返回 404 | 本期不做落盘 | 前端提示「任务已结束或服务已重启」并停止轮询——**本期不修** |

### C.2 明确记录但本期不修

| 项 | 现状 | 为什么不修 |
|---|---|---|
| per-movie 并发锁 | 同一影片并发两次请求可能都走完下载 | 低频场景；原子写已保证不出半截文件 |
| 无码 `only_missing` 的 listdir 性能 | 每部一次目录遍历（网络盘有开销） | 需改表结构或加索引，超出本期范围 |
| 源站广告块 / 未闭合标签过滤 | 字幕正文可能带站点广告行、HTML 片段原样保留 | 属内容清洗范畴，易误删台词，需单独评估 |
| 批量进度不持久化 | 重启后进度丢失 | 落盘会引入状态恢复与并发一致性问题 |
