# JAV 系列参考项目 · 深度分析与复用评估报告

> 分析对象：`G:\MDCX\.references\JAV系列\`（19 个子目录，含 1 个 `.old` 备份，**18 个有效项目**）
> 对照主体：`G:\MDCX\MDCX-Server`（FastAPI + SQLAlchemy 2.0 + SQLite 七模块独立库）+ `G:\MDCX\MDCX-Desktop`（Vue3）
> 成文时间：2026-08-11　　深度：**代码级**（非 README 级）
> 本报告是对既有 `G:\MDCX\JAV系列_参考学习报告.md`（浅层分类矩阵）的代码级补充与结论收敛。

---

## 〇、结论先行（TL;DR）

三条最值得立刻做的事，按 ROI 排序：

| # | 动作 | 来源 | 解决 MDCX 的什么问题 | 工作量 |
|---|------|------|---------------------|--------|
| **1** | 移植 `jdsignature` 匿名签名，走 JavDB **App JSON API** | `javdb-cli-main`（Go） | JavDB 走 HTML + Cloudflare，`javdb.py` 632 行全在跟盾对抗；App API **免登录、无 CF、返回 JSON** | **0.5 天**（签名算法已在 Python 侧验证 MATCH） |
| **2** | 引入**磁力质量评估 + Tracker 存活探测** | `JavDB_magnet_Spider` + `JHS` + `JAVDB_AutoSpider` | `magnet_extractor.py` 只做"提取"，不做"选优"，用户拿到一堆死种 | 1–2 天 |
| **3** | 补 **per-request 代理池 + 403 封禁轮换** | `JAVDB_AutoSpider`（抄设计） | `proxy_manager.py` 是 Xray 节点管理器，**不是爬虫代理池**，爬虫被封只能整体停摆 | 2–3 天 |

一条重要澄清：**MDCX 已有 `app/services/javdb_api_client.py`（207 行）**，但它用的是 `HMAC-SHA256 + session token` 方案（`JV1.{token[:16]}.{b64(hmac)}.{token[-16:]}`，Base `https://api.javdb.com`，**必须先登录拿 token**）。`javdb-cli` 用的是完全不同的 `md5(ts+prefix)` **匿名**方案（`https://jdforrepam.com`）。两者不冲突，**后者的价值正在于不需要账号**。

---

## 一、项目总览矩阵（18 个）

| # | 项目 | 语言/栈 | 定位 | 数据源 | 对 MDCX 价值 |
|---|------|---------|------|--------|--------------|
| 1 | **javdb-cli-main** | Go | JavDB App API CLI | JavDB App JSON API | ⭐⭐⭐⭐⭐ **最高** |
| 2 | **JavDB_magnet_Spider-main** | Python/FastAPI | 磁力爬取+评分+存活检测 | JavDB HTML | ⭐⭐⭐⭐⭐ |
| 3 | **JAVDB_AutoSpider-main** | Python + Rust core | 自动化订阅下载 | JavDB | ⭐⭐⭐⭐ |
| 4 | **JavLibrarian-main** | Python | 双源合并+改名归档 | JavBus + JavDB | ⭐⭐⭐⭐ |
| 5 | **javbus-api-main** | TypeScript/Node | 自托管 JavBus REST API | JavBus HTML | ⭐⭐⭐⭐ |
| 6 | **AVDB-SERVER-main** | Python/FastAPI + Vue | 完整影片管理服务端 | JavDB | ⭐⭐⭐（局部） |
| 7 | **jvav-master** | Python | 多站点工具库（2119 行） | JavBus/DB/Lib/Sukebei… | ⭐⭐⭐ |
| 8 | **JAV-Scraper-main** | Python/PyQt | 桌面刮削器 | JAVDB→JAV321 降级 | ⭐⭐⭐ |
| 9 | **javdb_tool-main** | Python | NFO 生成+断点续跑 | JavDB (nodriver) | ⭐⭐⭐ |
| 10 | **JHS-main** | Tampermonkey/JS | 浏览器增强脚本 | 多站聚合 | ⭐⭐⭐（算法） |
| 11 | **JavDB-Cover-Bot-main** | Node.js | 封面/标签补全 Bot | JAV321/S1/MOODYZ | ⭐⭐⭐ |
| 12 | **JavBoss-main** | Go + SQLite | 媒体库管理器 | 本地库 | ⭐⭐（演员合并） |
| 13 | **javdb_api-main** | Kotlin/Android | JavDB App 客户端 | JavDB App API | ⭐⭐（佐证） |
| 14 | **JAVDB_AutoSpider_Web-main** | Vue3 + Node/TS | AutoSpider 的 Web 前端 | — | ⭐⭐（UI 参考） |
| 15 | **javdb-magnet-workbench-master** | Tauri + Python sidecar | 磁力→Real-Debrid 直链 | JavDB | ⭐⭐（RD 集成） |
| 16 | **JavdBviewed-main** | TS/Chrome 扩展 | 观看记录+115/Emby 同步 | JavDB | ⭐⭐（115 同步） |
| 17 | **mcp-main** | TypeScript | javinfo.dev 的 MCP Server | javinfo API | ⭐⭐（MCP 范式） |
| 18 | **Harem-Automation-Scraper-main** | Python→Bookmarklet | 论坛磁力批量收割 | 论坛 | ⭐（不相关） |
| — | **sakuramedia-main** | Flutter/Dart | 移动端播放器 App | — | ⭐（技术栈不通） |

> 注：`sakuramedia-main` 为 Flutter 移动端，与 MDCX 的 Vue3 Web/Electron 栈不通，仅列入完整性，不展开评估。

---

## 二、逐项目功能概述 + 典型用法（按价值降序）

### 1. javdb-cli-main（Go）— ⭐⭐⭐⭐⭐ 本次最大发现

**核心功能**：绕过 JavDB 网页端 Cloudflare，直连其 **Android App 的 JSON API**。关键在于逆向出了 App 的请求签名头 `jdsignature`。

**关键代码**：`internal/javdb/protocol/signature/sign.go`（逆向自 JavDB.apk v1.9.28）

```go
Prefix = "71cf27bb3c0bcdf207b64abecddc970098c7421ee7203b9cdae54478478a199e" +
         "7d5a6e1a57691123c1a931c057842fb73ba3b3c83bcd69c17ccf174081e3d8aa"
Suffix = "lpw6vgqzsp"
Sign(ts) = fmt.Sprintf("%d.%s.%s", ts, Suffix, md5(ts + Prefix))
```

`internal/javdb/appapi/client.go`：
- Host：`https://jdforrepam.com`（镜像，主推）/ `https://javdb.com`
- UA：`Dart/3.4 (dart:io)`，`app_version: 1.9.28`
- Header：`jdsignature: <Sign(unix_ts)>`
- 端点：`/api/v1/movies/{id}/magnets`、`/api/v1/movies/{id}`、`/api/v1/actors/{id}`、`/api/v1/rankings`、`/api/v1/startup`、`/api/v1/sessions`（登录，可选）

**已在 Python 侧验证复现成功（MATCH）**：

```python
import hashlib, time
PREFIX = ('71cf27bb3c0bcdf207b64abecddc970098c7421ee7203b9cdae54478478a199e'
          '7d5a6e1a57691123c1a931c057842fb73ba3b3c83bcd69c17ccf174081e3d8aa')
SUFFIX = 'lpw6vgqzsp'

def jdsignature(ts: int | None = None) -> str:
    ts = ts or int(time.time())
    return f'{ts}.{SUFFIX}.' + hashlib.md5(f'{ts}{PREFIX}'.encode()).hexdigest()

# ts=1784134914 → 1784134914.lpw6vgqzsp.85b53cc0034eff62f361723615a3b8e3  ✅ 与 Go 输出一致
```

**典型用法**：`javdb-cli movie ABC-123` / `javdb-cli magnets ABC-123`，无需 cookie、无需账号。

**使用场景**：任何需要稳定拿 JavDB 元数据 + 磁力但不想维护 cookie/过 CF 的场景。

**⚠️ 风险**：签名常量绑定 App 版本，JavDB 改版即失效，必须做**降级链**（App API → 现有 HTML 爬虫）。

---

### 2. JavDB_magnet_Spider-main（Python/FastAPI）— ⭐⭐⭐⭐⭐

**核心功能**：JavDB 磁力抓取全流程 —— 登录、爬榜、磁力评分、**Tracker 存活探测**、SSE 实时推送。

**关键代码**：
- `spider_core/services/auth_browser_service.py`：用 `curl_cffi` + `impersonate="chrome"` **直接 TLS 指纹伪装登录**，人工过验证码后复用 cookie（比 MDCX 现在 cloudscraper + undetected-chrome 轻得多）
- `spider_core/services/magnet_scoring.py`：三档**可配权重**评分
- `spider_core/services/magnet_checker.py`：**UDP / HTTP Tracker 主动探测** seeders/leechers，产出 `active` / `weak` / `dead` 三态
- `spider_core/services/ranking_utils.py`：日榜/周榜/月榜解析
- SSE 挂在 `/api/events`

**典型用法**：Web 面板输入番号或选榜单 → 后台任务爬取 → 前端 SSE 看进度 → 拿到按质量排序的磁力列表。

**⚠️ 缺陷**：数据层是裸 `sqlite3`（无 ORM），不可直搬，只取服务层。

---

### 3. JAVDB_AutoSpider-main（Python + Rust core）— ⭐⭐⭐⭐

**核心功能**：订阅式自动化下载。演员/系列订阅 → 定时爬新作 → 分类磁力 → 推送下载器 → 洗版检测。

**关键代码**：
- `javdb/parsing/magnet_categorize.py`：磁力**四分类** `subtitle`（字幕）/ `hacked_subtitle`（破解带字幕）/ `hacked_no_subtitle` / `no_subtitle`，**纯 Python 实现，无 Rust 依赖，可直接抄**
- `javdb/services/dedup_query.py`：**洗版检测** —— 同分类下出现更大体积版本则触发重下
- `javdb/storage/`：**pending 影子表**模式，爬取结果先入暂存表，校验通过再提交主表（防脏数据污染）
- `javdb/proxy/pool.py` + `ban_manager.py`：代理池 + 403 封禁轮换 —— **强依赖 Rust core，缺失时直接 raise**，只能抄设计（`ProxyInfo` 结构、403/CF 触发条件、冷却时长）
- `javdb/auth/login.py`：AI 打码
- `javdb/parsing/fallback/`：BeautifulSoup 兜底解析

**典型用法**：配置演员订阅 → 守护进程定时跑 → 自动入库并推 qBittorrent/Aria2。

---

### 4. JavLibrarian-main（Python）— ⭐⭐⭐⭐

**核心功能**：双源元数据合并 + 文件改名归档 + 可回滚。

**关键代码**：
- `merge_sources()`：**以 JavBus 为骨架，字段级优先级合并** JavDB 数据（不是整体覆盖，而是逐字段判空补齐）
- `_same_code()`：**番号反向校验** —— 抓回的数据必须能反解出同一番号，否则丢弃。这是**防串号的关键防线，MDCX 目前完全没有**
- `Fetcher.bucket_of()`：按 **(主机 + 请求类型)** 分桶限流，比全局限流精细
- `RenameLog`：改名映射日志，支持**回滚**

**典型用法**：指向媒体目录 → 扫描 → 双源刮削 → 生成新名 → 应用（可 undo）。

---

### 5. javbus-api-main（TypeScript）— ⭐⭐⭐⭐

**核心功能**：把 JavBus 网页实时转成 REST JSON 服务（无数据库，纯转换层）。

**关键代码**：`api/javbus-parser.ts`（419 行）
- `getMovieDetail(id)` / `getMoviesByPage()` / `getMoviesByKeywordAndPage()` / `getMovieMagnets()` / `getStarInfo()`
- `textInfoFinder` / `linkInfoFinder` / `multipleInfoFinder` 三个**通用字段提取器**，覆盖 JavBus 详情页所有字段形态
- `convertMagnetsHTML()`：解析磁力表格，含 **tag 锚点**（高清/字幕）
- 磁力自带 `sort` 逻辑
- 端点：`/api/movies`、`/api/movies/search`、`/api/movies/{id}`、`/api/magnets/{id}`、`/api/stars/{id}`
- 支持 Docker / Vercel / PM2 部署，带 Token 鉴权

**与 MDCX 对比**：MDCX 的 `app/crawlers/javbus.py` 只有 **359 行**，字段覆盖（series/director/genres/sample_images 都有）大体齐，但**磁力表格解析与 tag 提取缺失**，可对照 `convertMagnetsHTML` 补齐。

**典型用法**：`docker run` 起服务 → `GET /api/magnets/ABP-123?gid=xxx&uc=0`。

---

### 6. AVDB-SERVER-main（Python/FastAPI + Vue）— ⭐⭐⭐（仅局部）

**核心功能**：完整的影片管理服务端，与 MDCX 定位高度重叠，但架构上是**单库 + 子进程爬虫**，与 MDCX 七模块独立 DB 冲突。

**唯一值得抄的**：`backend/services/browser_pool.py` —— **浏览器实例池化 + stealth 注入 + Turnstile 自动过**，是本批 18 个项目里 CF 对抗做得最完整的一份。

**次要**：`new_works_monitor.py` 的**三级新作判定**（首次见/已知未下载/已下载）。

**⚠️ 排雷（避免误抄）**：
- README 宣称的 **FTS5 全文搜索是虚标** —— 代码里实际只有 `LIKE` 降级实现
- `flaresolverr.py` 是**死代码**，没有任何调用点
- `scraper_lock.py` 不是真队列，只是个互斥锁
- `scheduler.py` 只是 APScheduler 的薄封装，无价值（MDCX 已装 APScheduler 3.11.2）

---

### 7. jvav-master（Python）— ⭐⭐⭐

**核心功能**：多站点统一工具库，`jvav/utils.py` 单文件 **2119 行**，为 JavBus / JavDB / JavLib / Sukebei / DMM 各实现一个 `Util` 类。

**值得取的**：
- `MagnetUtil.get_nice_magnets()`：**降级语义设计得好** —— 按条件筛选，若筛完为空则**返回原列表而非空列表**，避免"过滤过头导致零结果"
- `requests_cache` 本地磁盘缓存，重复请求零成本

**⚠️ 缺陷**：2119 行单文件、无类型标注、同步阻塞 requests，整体不可搬，只取思路。

---

### 8. JAV-Scraper-main（Python/PyQt）— ⭐⭐⭐

**核心功能**：桌面刮削器。

**值得取的**：
- `lib/code_extractor.py::extract_code()`：**四步番号清洗正则**（① 去水印/发布组后缀 → ② FC2 专用 → ③ T28/特殊厂牌 → ④ 标准 `[A-Z]+-\d+`）。MDCX 的 `app/scraper/number.py` 有 976 行、正则更多，但**清洗顺序不如它清晰**，可对照补强边界 case
- `gui/scrape_worker.py`：JAVDB → JAV321 **源降级链**

---

### 9. javdb_tool-main（Python）— ⭐⭐⭐

**核心功能**：批量生成 NFO，强调**不中断、不损坏**。

**值得取的（工程质量类，含金量高）**：
- `_atomic_json_write()`：`mkstemp` + `fsync` + `os.replace` **三步原子写**，断电不产生半截文件
- NFO 写入同样原子化，且**写前自动备份**
- `.javdb_progress.json` / `.javdb_state.json` 双文件**断点续跑**
- 客户端用 `nodriver`（比 undetected-chromedriver 更新、更难被识别）

---

### 10. JHS-main（Tampermonkey/JS）— ⭐⭐⭐

**核心功能**：浏览器端多站增强脚本。

**值得取的**：`src/plugins/external-search/magnet-hub.js::calcMagnetScore()` —— **五维加权磁力评分**，是本批里最完整的一套：

| 维度 | 权重 |
|------|------|
| seeders（做种数） | 35 |
| resolution（分辨率） | 25 |
| subtitle（字幕） | 20 |
| freshness（新鲜度） | 15 |
| completeness（完整度惩罚项） | −15 |

---

### 11. JavDB-Cover-Bot-main（Node.js）— ⭐⭐⭐

**核心功能**：封面与标签补全机器人。

**值得取的**：
- `src/jav321.js`：**S1 / MOODYZ / Aircontrol 官网标签解析** —— 直取厂商官网标签，质量高于聚合站
- `isJavdbCover()`：识别并**屏蔽带水印的 JavDB 封面**
- **封面回退链**：官网 → JAV321 → JavBus → JavDB
- FC2 番号规范化正则

**与 MDCX 关联**：MDCX 有 `cover_refill.py` / `poster_enhancer.py`，可把回退链和水印判定接进去。

---

### 12. JavBoss-main（Go + SQLite）— ⭐⭐

**核心功能**：媒体库管理器。

**值得取的**：`internal/db/jav.go::MergeJavIdols()`（L3552）+ `jav_idol_alias` 表设计。

**⚠️ 局限**：它是**纯手动合并 + 硬删源记录**，没有自动相似度判定。**MDCX 的 `actor_merge_service.py`（235 行，含 `search_similar_actors` 相似度）实际上比它更强**，只需借鉴其 `alias` 表结构来持久化别名。

---

### 13. javdb_api-main（Kotlin/Android）— ⭐⭐

**核心功能**：JavDB 第三方 Android 客户端。

**结论**：`BASE_URL = https://api.btyjscl.com`，`jdsignature` 头**在代码里是空常量**，只实现了 `/api/v1/startup`。**仅能佐证"App API 确实存在"，无法交叉验证 `jdforrepam.com` 域名与 md5 签名算法**。价值到此为止。

---

### 14. JAVDB_AutoSpider_Web-main（Vue3 + Node/TS）— ⭐⭐

AutoSpider 的 Web 前端：Vue3 + TS + i18n + Pinia + 主题系统，服务端在 `server/`（routes/services/middleware/contract 分层，带契约测试）。

**值得取的**：订阅管理、任务进度、磁力分类展示的 **UI/交互范式**，MDCX-Desktop 同为 Vue3，可直接看组件结构。

---

### 15. javdb-magnet-workbench-master（Tauri + Python sidecar）— ⭐⭐

磁力 → **Real-Debrid 直链**工作台（Windows 桌面版，portable）。核心是 `realdebrid.py` + `javdb_scraper.py`，Tauri 前端 + PyInstaller 打包的 sidecar.exe 通过 HTTP 通信。

**值得取的**：① Real-Debrid 集成（若你用 RD）；② **pending 待处理清单**模式 —— RD 还在处理的 torrent 不阻塞主流程，可稍后重试；③ Tauri + Python sidecar 的进程间协议设计（`spikes/python_sidecar_protocol`）。

---

### 16. JavdBviewed-main（TypeScript / Chrome 扩展）— ⭐⭐

观看记录管理扩展，monorepo（`apps/extension` + `packages/sync-client` + `packages/sync-protocol`）。带 **115 网盘 / Emby / Jellyfin** 的 API 参考实现（`reference/` 下有 emby-api-4.9.5.0、jellyfin-api-12.0.0、openai-115）。Playwright 扩展 E2E 测试配置齐全。

**与 MDCX 关联**：MDCX 已有 `pan_115.py`、`view_status.py`、`viewing_report.py`，可对照其 `reference/openai-115` 校验 115 接口用法。

---

### 17. mcp-main（TypeScript）— ⭐⭐

`javinfo.dev` 的 MCP Server（stdio），暴露 5 个 tool：`javinfo-search` / `javinfo-movie` / `javinfo-random` / `javinfo-open` / `javinfo-serve`。多 provider 路由：`fanza`/`dmm`（元数据）、`javdb`（磁力）、`missav`（m3u8）、`javdatabase`（简介+样图）。

**与 MDCX 关联**：MDCX 已有 `app/services/mcp_service.py`，可对照其 **tool 粒度划分与 provider 路由**设计（"先 search 拿 code，再 movie 取详情"的两段式很值得学）。

---

### 18. Harem-Automation-Scraper-main（Python → Bookmarklet）— ⭐

三个文件的小工具：Python 脚本生成一段 JS 书签，在论坛页面并发抓取所有资源帖、提取磁力/电驴/网盘链接、大屏画廊选择、一键导出 txt。

**结论**：面向论坛而非 JAV 数据库站，与 MDCX 业务不相关。仅"生成 bookmarklet"的分发方式有点意思。

---

## 三、MDCX-Server 现状盘点（对照基线）

评估前先把家底摸清，避免"推荐已经有的东西"。以下均为**实际读码 / grep 计数**结果，非推测。

### 3.1 已有且够用（不需要引入外部方案）

| 能力 | 位置 | 现状 |
|------|------|------|
| 爬虫矩阵 | `app/crawlers/` | javbus / javdb / avmoo / avsox / dmm / javdatabase / fc2 全家桶（fc2 有 5 个变体）/ pornhub / uncensored / western，共 20+ 文件 |
| 番号识别 | `app/scraper/number.py` | 976 行多正则 |
| 演员合并 | `app/services/actor_merge_service.py`（235 行）+ `app/utils/actor_alias.py` | 含 `search_similar_actors` 相似度判定，**强于 JavBoss** |
| 定时任务 | APScheduler 3.11.2（11 处引用） | 已装已用 |
| TLS 指纹 | curl_cffi 0.11.4（**46 处引用**） | 已装已用 |
| SSE 实时推送 | 257 处引用 | 已成体系 |
| 订阅体系 | `actor_subscription.py` / `subscription_downloader.py`（168 处引用） | 已有 |
| 下载器 | aria2 / transmission / qb（`downloader_registry.py` 等 8 个文件） | 齐全 |
| JavDB App API | `app/services/javdb_api_client.py`（207 行） | **HMAC-SHA256 + token 方案，需登录** |

### 3.2 缺口（本次评估的靶心）

| 缺口 | 证据 | 影响 |
|------|------|------|
| **磁力质量评估缺失** | `magnet_extractor.py`（227 行）只有 4 种 fallback **提取**逻辑（直接查找/文本匹配/class 选择器/正则），`grep score\|seed` **零命中** | 用户拿到一堆无人做种的死链 |
| **爬虫代理池 / 封禁轮换缺失** | `proxy_manager.py`（440 行）是 **Xray 节点订阅 + 本地 socks5 出口管理器**（`_build_config`/`start`/`_health_loop`/`get_current_socks5_url`），**不是 per-request 代理轮换池**；无 403 计数、无节点冷却、无按站点封禁 | 单点被封 → 整体停摆 |
| **番号反向校验缺失** | 全局 grep 无相关实现 | 抓错片却入库，串号污染 |
| **JavDB 仍走 HTML 硬刚 CF** | `app/crawlers/javdb.py` 632 行，cloudscraper + undetected-chromedriver + Cloudflare 检测分支 | 维护成本高、成功率不稳定 |
| **FTS5 全文搜索未落地** | 全项目仅 1 处"提及" | 大库搜索慢 |
| **JavBus 磁力表格解析缺失** | `javbus.py` 359 行，`grep magnet` 无命中 | JavBus 这一路拿不到磁力 |

---

## 四、复用评估清单（核心交付物）

### 🟢 A 级：直接复用（代码可近乎照搬，ROI 最高）

#### A1. `jdsignature` 匿名签名 → JavDB App API 通道

- **来源**：`javdb-cli-main/internal/javdb/protocol/signature/sign.go` + `appapi/client.go`
- **适用性**：★★★★★ —— 算法已在 Python 侧验证 MATCH，零移植风险
- **对接方式**：
  1. 在 `app/services/javdb_api_client.py` **新增** `AnonymousJavDBClient`，与现有 HMAC 客户端**并存**（不要替换，token 方案能拿到个人收藏/观看记录，匿名方案拿不到）
  2. 复用现有 `curl_cffi`（已装 0.11.4）发请求，header 加 `jdsignature`
  3. Host 走 `jdforrepam.com`，UA 固定 `Dart/3.4 (dart:io)`，带 `app_version=1.9.28`
  4. 在 `app/crawlers/javdb.py` 顶部加**优先级路由**：App API 成功 → 直接返回；失败/签名过期 → 落回现有 632 行 HTML 路径
  5. 把 `PREFIX`/`SUFFIX`/`app_version` 抽进配置（`get_config_manager`，唯一真相源 `app/config/manager.py:474`），JavDB 改版时改配置不改码
- **落地建议**：**先做这个**。0.5 天，收益立竿见影
- **风险**：签名绑定 App 版本 → 必须保留 HTML 降级链，且加成功率埋点（`app/services/metrics.py`）

#### A2. 磁力五维评分算法

- **来源**：`JHS-main/src/plugins/external-search/magnet-hub.js::calcMagnetScore`（权重表）+ `JavDB_magnet_Spider/spider_core/services/magnet_scoring.py`（可配置三档结构）
- **对接方式**：新建 `app/services/magnet_scorer.py`，输入 `MagnetInfo`（`magnet_extractor.py` 已有 dataclass），输出 `score` + `tier`。权重放配置，供用户调
- **注意**：`MagnetInfo` 现有字段不含 seeders，需先做 A3 才能填满五维；未做 A3 前先用 resolution/subtitle/size 三维

#### A3. Tracker 存活探测（seeders/leechers）

- **来源**：`JavDB_magnet_Spider/spider_core/services/magnet_checker.py`
- **对接方式**：新增 `app/services/magnet_checker.py`，UDP + HTTP 双协议 tracker scrape，异步并发（asyncio），结果三态 `active` / `weak` / `dead` 写回磁力记录
- **落地建议**：与 A2 打包成一个"磁力质量"特性，1–2 天

#### A4. 磁力四分类

- **来源**：`JAVDB_AutoSpider-main/javdb/parsing/magnet_categorize.py`（**纯 Python，无 Rust 依赖，可直接复制**）
- **分类**：`subtitle` / `hacked_subtitle` / `hacked_no_subtitle` / `no_subtitle`
- **对接方式**：直接放进 `app/services/magnet_scorer.py` 作为前置分类步骤

#### A5. 原子写 + 断点续跑

- **来源**：`javdb_tool-main/javdb_core.py::_atomic_json_write` + `.javdb_progress.json` 模式
- **适用性**：★★★★★ —— **MDCX 所有媒体盘都是 SMB 网络盘（H:/I:/J:/K:/Y:/Z:/G:/L:），断连概率远高于本地盘，非原子写就是在赌**
- **对接方式**：抽 `app/utils/atomic_io.py`（`mkstemp` + `fsync` + `os.replace`），改造所有 NFO / JSON 落盘点（`nfo_scraper.py`、`base_scanner.copy_video_assets_to_data_dir` 等）
- **落地建议**：**优先级仅次于 A1**，属于"防数据损坏"的基础设施

#### A6. 番号反向校验

- **来源**：`JavLibrarian-main/javlibrarian.py::_same_code`
- **对接方式**：在 `app/scraper/number.py` 加 `verify_code_match(query_code, scraped_title, scraped_code)`，所有 crawler 的 `parse` 出口统一过一遍，不匹配则丢弃并记 warning
- **落地建议**：**几十行代码，但能杜绝串号入库**，性价比极高

---

### 🟡 B 级：参考设计（抄思路不抄码）

#### B1. 爬虫代理池 + 403 封禁轮换

- **来源**：`JAVDB_AutoSpider-main/javdb/proxy/{pool.py, ban_manager.py}`
- **⚠️ 不可直搬**：强依赖 Rust core，缺失时直接 `raise`
- **可抄的设计**：`ProxyInfo` 数据结构、403/CF 挑战的触发条件判定、封禁冷却时长策略、按 (代理 × 站点) 二维记账
- **对接方式**：新建 `app/services/crawler_proxy_pool.py`，与现有 `proxy_manager.py`（Xray 出口）**分层**：Xray 管"我从哪出网"，新池管"这次请求用哪个出口 + 被封了怎么换"
- **工作量**：2–3 天

#### B2. 浏览器池化 + Turnstile 自动过

- **来源**：`AVDB-SERVER-main/backend/services/browser_pool.py`
- **对接方式**：作为 A1 的**兜底层**。若 A1（App API）稳定，此项可降级为低优先级
- **注意**：只抄 `browser_pool.py`，**该项目其余部分（FTS5 虚标、flaresolverr 死代码、单库架构）勿碰**

#### B3. 双源字段级合并

- **来源**：`JavLibrarian-main::merge_sources`（JavBus 为骨架，字段级判空补齐）
- **对接方式**：MDCX 已有 `aggregate_searcher.py` / `uncensored_aggregate.py` / `western_aggregate.py`，可对照升级为**字段级优先级表**（而非整体覆盖）

#### B4. 封面回退链 + 水印屏蔽

- **来源**：`JavDB-Cover-Bot-main/src/jav321.js`
- **对接方式**：接入 `app/services/cover_refill.py` / `poster_enhancer.py`，回退链 官网(S1/MOODYZ/Aircontrol) → JAV321 → JavBus → JavDB，并加 `isJavdbCover` 水印判定

#### B5. JavBus 磁力表格解析

- **来源**：`javbus-api-main/api/javbus-parser.ts::convertMagnetsHTML`
- **对接方式**：MDCX `app/crawlers/javbus.py` 补 `_get_magnets()`，含 tag 锚点（高清/字幕）提取。同时可对照 `textInfoFinder`/`linkInfoFinder`/`multipleInfoFinder` 三个通用提取器**简化现有 xpath 散装写法**

#### B6. 洗版检测 + pending 影子表

- **来源**：`JAVDB_AutoSpider-main/javdb/services/dedup_query.py` + `javdb/storage/`
- **对接方式**：MDCX 已有 `dedup.py` / `duplicate_scanner.py` / `video_dedup.py`，可补"同分类更大体积 → 触发重下"规则；影子表模式适合接进现有扫描器，防脏数据直接污染 7 个模块主库

#### B7. 番号清洗正则边界补强

- **来源**：`JAV-Scraper-main/lib/code_extractor.py::extract_code` 四步顺序
- **对接方式**：`app/scraper/number.py` 已有 976 行，**不重写**，只把它的四步顺序当 checklist 补边界 case（水印后缀、T28、特殊厂牌）

#### B8. 降级语义 + 请求缓存

- **来源**：`jvav-master`：`get_nice_magnets` 筛完为空则返回原列表；`requests_cache` 磁盘缓存
- **对接方式**：MDCX 有 `smart_cache.py`，可对照加"过滤器零结果自动放宽"的通用装饰器

#### B9. 分桶限流

- **来源**：`JavLibrarian-main::Fetcher.bucket_of`（按 主机+请求类型 分桶）
- **对接方式**：现有限流若是全局的，可升级为二维桶，避免"详情页拖慢列表页"

#### B10. MCP tool 粒度与两段式检索

- **来源**：`mcp-main`（search → movie 两段式，provider 路由）
- **对接方式**：对照优化 `app/services/mcp_service.py` 的 tool 划分

---

### 🔴 C 级：不推荐 / 排雷

| 项目/模块 | 原因 |
|-----------|------|
| `AVDB-SERVER-main` 整体架构 | 单库 + 子进程爬虫，与 MDCX **七模块独立 DB** 根本冲突 |
| `AVDB-SERVER-main` 的 FTS5 | **README 虚标**，代码只有 LIKE 降级，别照着抄 |
| `AVDB-SERVER-main/flaresolverr.py` | **死代码**，无调用点 |
| `AVDB-SERVER-main/scheduler.py` | APScheduler 薄封装，MDCX 已有 3.11.2 |
| `JAVDB_AutoSpider` 代理池实现 | Rust 强耦合，缺失即 raise，**只能抄设计** |
| `JavBoss-main::MergeJavIdols` | 纯手动合并 + 硬删源，**弱于 MDCX 现有 `actor_merge_service.py`** |
| `javdb_api-main`（Kotlin） | `jdsignature` 为空常量，仅 1 个端点，无交叉验证价值 |
| `JavDB_magnet_Spider` 数据层 | 裸 sqlite3，与 SQLAlchemy 2.0 不兼容，只取服务层 |
| `sakuramedia-main` | Flutter 移动端，栈不通 |
| `Harem-Automation-Scraper-main` | 论坛场景，业务不相关 |
| `jvav-master` 整体 | 2119 行单文件、无类型标注、同步阻塞，只取思路 |

---

## 五、推荐落地路线

### 第一阶段（约 1 周）：止血 + 高 ROI

```
[A1] jdsignature 匿名 App API 通道        0.5 天  ← 立刻做
[A5] 原子写 atomic_io                     0.5 天  ← SMB 网络盘刚需
[A6] 番号反向校验 verify_code_match       0.5 天  ← 防串号
[A4] 磁力四分类 magnet_categorize         0.5 天
[A2+A3] 磁力评分 + Tracker 存活探测       2 天
```

**产出**：JavDB 通道稳定化 + 数据不再损坏/串号 + 磁力从"一堆链接"变成"按质量排序、标注存活状态"。

### 第二阶段（约 1 周）：抗封 + 补源

```
[B1] 爬虫代理池 + 403 封禁轮换            2-3 天
[B5] JavBus 磁力表格解析                  0.5 天
[B4] 封面回退链 + 水印屏蔽                1 天
[B3] 双源字段级合并升级                   1 天
```

### 第三阶段（按需）

```
[B2] 浏览器池化 + Turnstile（若 A1 失效再上）
[B6] 洗版检测 + pending 影子表
[B7~B10] 各类边角优化
```

---

## 六、关键风险与注意事项

1. **A1 的签名常量会过期**。JavDB App 一升级，`PREFIX`/`SUFFIX` 大概率变。**必须**：① 抽到配置；② 保留 HTML 降级链；③ 加成功率监控（`metrics.py`），连续失败自动切降级。
2. **不要替换现有 `javdb_api_client.py`**。HMAC+token 方案能访问需登录的接口（收藏、观看记录），匿名方案访问不到。两者是互补关系。
3. **A5 原子写要覆盖全部落盘点**，包括 NFO、封面、progress json。SMB 盘 `os.replace` 语义与本地盘有差异，需在 L: 盘实测一遍。
4. **B1 代理池要与 `proxy_manager.py` 明确分层**，不要混在一起改，否则会把 Xray 出口管理搞坏。
5. **本报告的复用建议全部需要真实联调验证**。按项目既有规范，任何"修好了"必须经 Playwright 真实浏览器 QA 后才能声明。
6. **jdforrepam.com 域名未经交叉验证**（Kotlin 项目用的是 `api.btyjscl.com` 且签名为空）。首次接入前建议先手工 curl 一次确认可达。

---

## 附录：文件路径速查

| 要抄的东西 | 源文件绝对路径 |
|-----------|---------------|
| jdsignature 算法 | `G:\MDCX\.references\JAV系列\javdb-cli-main\internal\javdb\protocol\signature\sign.go` |
| App API 客户端 | `G:\MDCX\.references\JAV系列\javdb-cli-main\internal\javdb\appapi\client.go` |
| 磁力评分 | `G:\MDCX\.references\JAV系列\JavDB_magnet_Spider-main\spider_core\services\magnet_scoring.py` |
| Tracker 探测 | `G:\MDCX\.references\JAV系列\JavDB_magnet_Spider-main\spider_core\services\magnet_checker.py` |
| curl_cffi 直登 | `G:\MDCX\.references\JAV系列\JavDB_magnet_Spider-main\spider_core\services\auth_browser_service.py` |
| 磁力四分类 | `G:\MDCX\.references\JAV系列\JAVDB_AutoSpider-main\javdb\parsing\magnet_categorize.py` |
| 代理池设计 | `G:\MDCX\.references\JAV系列\JAVDB_AutoSpider-main\javdb\proxy\` |
| 洗版检测 | `G:\MDCX\.references\JAV系列\JAVDB_AutoSpider-main\javdb\services\dedup_query.py` |
| 原子写 | `G:\MDCX\.references\JAV系列\javdb_tool-main\javdb_core.py` |
| 双源合并/反向校验 | `G:\MDCX\.references\JAV系列\JavLibrarian-main\javlibrarian.py` |
| JavBus 解析器 | `G:\MDCX\.references\JAV系列\javbus-api-main\api\javbus-parser.ts` |
| 浏览器池 | `G:\MDCX\.references\JAV系列\AVDB-SERVER-main\backend\services\browser_pool.py` |
| 五维评分 | `G:\MDCX\.references\JAV系列\JHS-main\src\plugins\external-search\magnet-hub.js` |
| 封面回退链 | `G:\MDCX\.references\JAV系列\JavDB-Cover-Bot-main\src\jav321.js` |
| 番号清洗 | `G:\MDCX\.references\JAV系列\JAV-Scraper-main\lib\code_extractor.py` |
| 演员别名表 | `G:\MDCX\.references\JAV系列\JavBoss-main\internal\db\jav.go`（L3552） |

---

*报告完 · 代码级调研，结论均基于实际读码，非 README 转述。*
