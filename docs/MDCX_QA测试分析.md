# MDCX 项目原理、功能识别与 QA 测试方向

> 文档用途：项目原理速览 + 全部主要功能清单 + 可提取为自动化 QA 测试的提示词 + QA 测试方向分析
> 适用对象：自动化 QA 测试（Playwright 真实浏览器端到端验证）
> 版本：2026-08-08

---

## 一、项目原理（架构与运作机制）

### 1.1 定位
MDCX 是一套**本地媒体资产管理 + 刮削 + 播放**一体化系统：后端 FastAPI（MDCX-Server）+ 前端 Vue3/Element-Plus/Pinia（MDCX-Desktop）。面向成人影片多片源（JAV 有码/无码、FC2、国产、PornHub、欧美、里番），把散落磁盘的影片扫描入库、补全元数据、整理归档、并提供网页播放与外部客户端（Emby/TVBox/Stash）消费。

### 1.2 数据库架构（核心原理）
**「1 DB = 1 Module」**：6 个内容模块各自独立 SQLite 库，加 1 个系统库。

| 数据库 | 内容 | 关键表 |
|--------|------|--------|
| `system.db` | 跨模块全局数据 | users, user_sessions, settings, cache, tasks, workflows, migrations, scan_records, favorite_groups, favorite_items |
| `jav.db` | JAV 有码 | movies, actors, movie_actors, studios, series, tags, …(20 表) |
| `fc2.db` | FC2 | 同上结构 |
| `uncensored.db` | JAV 无码 | 同上结构 |
| `chinese.db` | 国产 | 同上结构 |
| `pornhub.db` | PornHub | 同上结构 |
| `western.db` | 欧美 | 同上结构 |
| `anime.db` | 里番（第 7 模块，独立 ANIME_BASE） | 独立模型 |

- 模块库内**完全规范化**，多对多关系用关联表（`movie_actors`），不再用逗号分隔字符串。
- `system.db` 与模块库之间**仅用 int ID 关联，无跨库外键**。
- 收藏夹 `favorite_items` 用 `module` 字段区分来源模块。
- 演员关联查询：旧数据 `movies.actor` 是逗号分隔文本，按演员查作品一律走 `actor LIKE '%名字%'`，**不 join 关联表**。
- 演员头像按模块隔离：`DATA/avatars/{module}/actor_{id}.jpg`，6 模块均不读全局目录（避免 id 撞车串图）。

### 1.3 主数据流（核心用户旅程）
```
磁盘扫描(Scanner) → 入库(DB) → 刮削补全(Scraper/Crawler) → 整理归档(Namer/Organizer)
                                                              ↓
                                          NFO/封面/预览落盘 data/movies/{mod}/{code}/
                                                              ↓
                               播放消费：网页播放 / Emby / TVBox / Stash / 外部播放器
```
- **扫描阶段 100% 本地、禁止网络请求**（所有媒体盘为网络盘）。联网刮削仅手动触发。
- **刮削网络请求全部走内置代理 Xray**（SOCKS5:18920 / HTTP:18921，多节点轮换 + 故障切换），`requires_proxy=True` 强制声明。
- **补刮死循环陷阱**：空字段分级 critical(title/release_date) / normal(plot/genre/actor/cover/studio) / optional(其余)；默认 `skip_complete=True` 只放行 critical 缺失，补刮成功须更新 `scraped_at`。绝不可全标 critical（否则 rating/tag 等源不提供字段会无限重扫）。

### 1.4 部署模型（高风险环节）
- 开发机 `G:\MDCX\MDCX-Server`，服务器 `192.168.10.110:8420`，通过 SMB 映射 `L:` = `E:\MDCX-Server` **只读**。
- 向 `L:` 写会 `Permission denied` / `readonly database`，**不是进程占用**，部署须服务器侧手动复制。
- 前端构建统一用 `vite.config.web.js`（输出 `G:\MDCX\MDCX-Server\static`），**绝不用 `npm run build`（那是 electron exe）**。
- 构建前须重命名旧 `static` 防脏目录；部署到服务器须整目录覆盖（不能只覆盖 index.html），否则旧 `index-*.js` 与新主 chunk hash 不匹配→白屏。
- 前端部署后浏览器须 `Ctrl+Shift+R` 硬刷新清缓存。

### 1.5 认证中间件（媒体端点必读）
- `auth_middleware.py` 全局校验 Bearer；浏览器 `<img>/<video>` 不带 Authorization → 直连媒体字节端点**必须白名单放行**，否则 401 裂图/裂视频。
- 已白名单：`/api/v1/actors/.../avatar/file`、`/api/v1/movies/.../{cover,poster,thumb}/file`、模块 `/{mod}/.../cover/file`、`/{mod}/.../avatar/file`、`/{mod}/.../play/file`、HLS、`/api/v1/player/...`、`/api/v1/previews/.../file`。
- 新增媒体端点第一反应加白名单。

### 1.6 开发约束（来自开发规则）
- 代码引用优先级：P0 GitHub 成熟方案 > P2 自研已验证 > P1 本地原型 > 自研。
- 分层：`api/routes`（HTTP 映射）→ `services`（业务）→ `db`（ORM）→ `tasks`（异步/扫描）→ `crawlers`（站点适配器）→ `utils`/`config`。
- 所有可选依赖 `try/except ImportError` 兜底降级。

---

## 二、全部主要功能清单（按功能域）

> 共识别 **17 个后端功能域 / 123 个前端路由（106 个 vue 文件）**。

| # | 功能域 | 用户价值 | 代表端点 / 页面 |
|---|--------|----------|------------------|
| 1 | 扫描/入库 | 把磁盘影片批量识别入库，支持增量/断点 | `POST /scan/trigger`、`POST /modules/{mod}/scan`、`/scan-control` |
| 2 | 刮削/元数据补全 | 补齐标题/封面/演员/简介，多源择优，生成 NFO | `POST /patch/run`、`POST /nfo-scrape/scan-dir`、`/patch`、`/jav/scrape` |
| 3 | 影片库管理（分模块） | jav/fc2/uncensored/chinese/pornhub/western/anime 各自独立库 + 跨模块统一检索 | `GET /movies`、`GET /modules/unified/search`、`*/movies`、`MovieDetail.vue` |
| 4 | 演员管理 | 别名合并、头像补全、按演员追新、分级 | `POST /actors/merge`、`POST /actors/avatar-scrape/start`、`/actors`、`ActorMerge.vue` |
| 5 | 播放/预览/代理播放 | 网页直接播放本地/网盘影片，雪碧图/章节/多音轨 | `GET /movies/{id}/play`、`/hls/master.m3u8`、`/player/{id}/thumbnail-sprite`、`/play/:id` |
| 6 | 文件整理/重命名 | 按模板批量改名归档、规则化自动整理、未识别文件补救 | `POST /file-organize/execute`、`POST /mnamer/rename`、`/naming-template` |
| 7 | 下载 | 统一 qb/tr/aria2 + 网盘离线，下载后接入刮削链路 | `POST /download/start`、`POST /pan-115/offline-tasks`、`/download`、`/downloaders` |
| 8 | 收藏/标签/系列/厂商 | 收藏夹、多维标签、系列/片商自动同步去重合并 | `POST /favorites/groups`、`POST /studios/merge`、`/favorites`、`/tags` |
| 9 | 重复检测/去重 | 番号级 + 内容指纹级双重查重 | `GET /duplicates/scan`、`POST /fingerprint/scan`、`/duplicates`、`/fingerprint` |
| 10 | 备份/唯读来源 | DB/配置快照可回滚；只读挂载源可索引不写入 | `POST /backup/create`、`GET /read-only/scan`、`/backup`、`/read-only` |
| 11 | 用户/认证/权限 | 多用户会话、内网可信 IP 免登录 | `POST /auth/login`、`GET/PUT /auth/trusted-ip`、`/users` |
| 12 | 爬虫源/站点/Cookie | 可视化管理数十刮削源启停/优先级/登录态 | `POST /crawlers/ping`、`PUT /site-priority/order`、`/crawlers`、`/cookiecloud` |
| 13 | 设置/配置 | 前端设置页由后端 Schema 自动生成，可校验/重置 | `GET /schema`、`GET/PATCH /config`、`/settings`、`/schema-settings` |
| 14 | 插件/工作流/MCP | 扫描→刮削→整理→推送编排为工作流定时执行；MCP 让 AI 调用 | `POST /workflows/run/{id}`、`GET /mcp/mcp/capabilities`、`/workflows`、`/plugins` |
| 15 | 外部集成 | 被 Emby/TVBox/Stash/WebDAV 等既有客户端直接消费 | `GET /emby/Videos/{id}/stream`、`GET /tvbox/config.json`、`/emby-config`、`/strm` |
| 16 | 监控/日志/统计 | 一屏掌握库存/存储/任务/网络健康，观影行为回溯 | `GET /health`、`GET /logs/stream`、`/system-status`、`/network-diag` |
| 17 | 图像增强/智能 | 人脸裁封面、水印角标增强、有码/无码判定、智能推荐 | `POST /face-crop/batch-crop`、`POST /poster-enhance/enhance`、`/recommendations` |

### 2.1 模块级 vs 通用页
- **多路由复用同一组件**：`MovieDetail.vue`（所有影片详情）、`ActorDetail.vue`（所有演员详情）、`Crawlers.vue`（所有刮削）、`Compare.vue`、`Patch.vue`、`CompareActors.vue`、`Studios.vue`、`MpvSettings.vue`。
- **各模块独立文件**：`jav/chinese/fc2/uncensored/western/pornhub` 各自的 `Movies.vue`、`Actors.vue`。
- **`modules/` 是单一通用页** `ModuleManager.vue`。

### 2.2 已发现的冗余/风险 UI（QA 需重点验证）
1. `/uncensored` 与 `/uncensored/scrape` 路由完全重复（同组件同名）→ 冗余。
2. 下载双页：`/download`（DownloadManager）与 `/downloaders` 并存。
3. **孤立未注册视图**（路由表无入口，疑似废弃或待接入）：`AutoOrganize.vue`、`FileOrganize.vue`、`RefreshFolders.vue`、`UnrecognizedFiles.vue`、`WebDAVImport.vue`、`CloudDrive2.vue`、`Pan115.vue`、`chinese/Scrape.vue`、`pornhub/Compare.vue`。
4. 部分已注册路由（Tiers、SitePriority、NamingTemplate、CookieCloud、NfoScrape、SourceMerge）**未出现在侧边栏菜单**，仅可直链/详情进入。

---

## 三、QA 测试方向分析（按风险优先级）

> 原则：以「真实联调 + Playwright 真实浏览器 QA」为准，所有改动须端到端验证后才能声明修复。

| 优先级 | 测试方向 | 高风险根因 | 验证手段 |
|--------|----------|------------|----------|
| **P0** | **主链路 E2E**（扫描→刮削→播放） | 任一环断裂用户不可用 | Playwright 走完整流程，断言列表/封面/播放 |
| **P0** | **媒体字节端点**（封面/头像/预览/播放） | auth 白名单遗漏→401 裂图裂视频；非 ASCII 文件名→UnicodeEncodeError 500；模块隔离串图 | 直接请求字节端点 + 浏览器 `<img>/<video>` 渲染断言 |
| **P0** | **前端构建/部署完整性** | 脏 static 目录 / 旧 chunk 残留 / 路由菜单前缀不一致→白屏 | 构建后 grep 主 chunk 含目标路由；硬刷新验证无白屏 |
| **P1** | **模块隔离完整性** | 跨库串数据、头像 id 撞车串图、actor LIKE 误匹配 | 各模块独立断言数据不泄漏 |
| **P1** | **补刮死循环防护** | optional 字段误标 critical→无限重扫 | 构造缺 optional 字段影片，断言补刮收敛并写 scraped_at |
| **P1** | **演员管理**（合并/对比/头像刮削/详情通用端点） | 走模块专属单 actor 端点→404 全空；合并后关联丢失 | 断言合并结果与详情页走 `commonApi.getActor` |
| **P2** | **设置 Schema 动态页** | 配置写错/校验失败静默 | 改配置→保存→重启生效→读回断言 |
| **P2** | **外部集成协议**（Emby/TVBox/Stash/WebDAV） | 协议字段不兼容客户端报错 | 用对应客户端/工具拉取断言 |
| **P2** | **下载/网盘** | 下载器账号/代理/离线任务失败 | 构造任务断言状态流转 |
| **P3** | **冗余/孤立 UI** | 重复路由、孤立页面入口缺失 | 断言已注册页可达、孤立页不影响其他功能 |

---

## 四、可提取的自动化 QA 测试提示词

> 以下为**自然语言测试指令**，可直接提取喂给自动化 QA 智能体（建议配合 Playwright 真实浏览器）。
> 每条即一个独立可执行测试意图。按功能域分组，便于拆分到不同测试套件。

### A. 主链路 E2E（P0）
1. 打开首页，登录系统后进入 JAV 模块影片库页面，断言影片列表正常渲染且总数与 `jav.db` 的 `movies` 表一致。
2. 触发一次 JAV 模块扫描（ScanControl 页面），断言扫描任务进入 running 状态并返回 records，扫描后新增影片出现在列表。
3. 对一部缺失封面/演员的影片执行补刮（Patch 页面），断言补刮任务完成后该影片 `scraped_at` 被更新且封面图在详情页正常加载（非灰色占位）。
4. 在影片详情页点击播放，断言网页播放器加载视频并显示（HLS master.m3u8 可解析、进度条雪碧图与章节可用）。
5. 将一部影片加入收藏夹，刷新后断言收藏状态持久化（跨刷新保留），且 `favorite_items` 表写入 `module='jav'`。

### B. 媒体字节端点（P0，重点防裂图/裂视频）
6. 直接 GET 影片封面端点 `/api/v1/jav/movies/{id}/cover/file`，断言返回 200 且 Content-Type 为 image/*（带 Authorization 也放行）。
7. 在浏览器中渲染 `<img src="/api/v1/jav/actors/{id}/avatar/file">`，断言图片成功加载不裂图（验证 auth 白名单）。
8. 用含中文/日文文件名的影片封面端点测试，断言不返回 500（验证非 ASCII 文件名 Content-Disposition 修复）。
9. 构造一个存在于 jav 但头像路径指向其他模块 id 的演员，断言头像端点返回本模块正确头像、不发生跨模块串图。
10. 请求预览图端点 `/api/v1/previews/{module}/{id}/file` 与播放字节端点 `/api/v1/{mod}/.../play/file`，断言均 200 可直接播放（不带 token 的媒体标签也可加载）。

### C. 前端构建/部署完整性（P0）
11. 用 `vite.config.web.js` 重新构建前端，断言 `static` 目录仅含单一批次主 chunk + Layout chunk（无多个 `index-*.js` 残留）。
12. 部署到服务器后硬刷新页面，断言首页不白屏且点击菜单 `JAV / 演员合并` 能进入 `jav/actor-merge` 路由（验证菜单 path 与路由表前缀一致）。
13. 构建产物 grep 校验：主 chunk 与 `Layout-*.js` 同时包含目标路由路径，旧路径不再匹配。

### D. 模块隔离（P1）
14. 在 jav 库新增/修改一条影片，断言 fc2/uncensored/chinese 等模块库数据不受影响、列表不串。
15. 断言演员头像严格按 `avatars/{module}/actor_{id}.jpg` 隔离，jav 演员详情不加载其他模块头像。
16. 按演员名在 jav 模块查作品，断言结果来自 `movies.actor LIKE '%名%'` 且仅本模块匹配，不跨模块。

### E. 补刮死循环防护（P1）
17. 构造一部仅缺 optional 字段（如 rating/tag）但 critical 字段齐全的影片，执行自动补刮，断言任务在首轮后收敛停止（不无限重扫）且 `scraped_at` 被更新。
18. 构造一部缺 title 的影片，断言补刮优先补齐 critical 字段后停止，不卡在 optional 字段。

### F. 演员管理（P1）
19. 在演员合并页选择两个同人演员执行合并，断言合并后原演员作品聚合到目标演员，且详情页走通用端点 `commonApi.getActor(id, module)` 而非模块专属单 actor 端点。
20. 对一批头像为空的演员执行头像批量刮削，断言任务完成且 `avatar_url` 指向本地 `/api/v1/actors/{id}/avatar/file`。
21. 打开任意演员详情页，断言作品列表与时间线正常加载（演员详情页统一走 `actors.py` 通用端点，不出现 404 全空）。

### G. 设置与配置（P2）
22. 在设置页修改一项配置并保存，断言 `config.yaml` 持久化、重启服务后该配置仍生效。
23. 触发一次 Schema 校验（非法值），断言返回校验错误且不写入损坏配置。

### H. 外部集成（P2）
24. 访问 `/tvbox/config.json` 与 `/emby/Videos/{id}/stream`，断言返回合法协议响应（TVBox 可解析、Emby 流可播放）。
25. 对 Stash/MacCMS 兼容端点发请求，断言返回符合各自协议结构的数据。

### I. 下载与网盘（P2）
26. 添加一个 qBittorrent/Aria2 下载任务，断言任务进入列表且状态在 downloading→completed 间正确流转。
27. 触发一次 115 网盘离线任务，断言离线任务创建并返回任务 id。

### J. 冗余/孤立 UI（P3）
28. 遍历所有侧边栏菜单项，断言每个都能打开对应页面无 404/白屏。
29. 访问 `/uncensored` 与 `/uncensored/scrape`，断言两者渲染一致（冗余路由但不应报错）。
30. 确认孤立视图（AutoOrganize/FileOrganize/UnrecognizedFiles 等）即便无菜单入口，也不影响其他已注册页面功能。

---

## 五、已知待验证项（QA 必覆盖）
- `favorite_items.module` 列迁移：部分环境待执行 `migrate_db.py`，收藏跨模块可能失败 → 测试前确认迁移已跑。
- 爬虫 403：刮削依赖 CookieCloud/手动 Cookie，未配置时刮削失败属预期 → QA 区分「功能缺陷」与「配置缺失」。
- 演员关联表 `movie_actors` 在全模块为空，关联查询必须走 `actor LIKE`；任何走 join 关联表的查询会返回空。
- 服务器 SMB 只读：任何需要写 `L:` 的操作须服务器侧执行，自动化测试若直接写 `L:` 会 Permission denied（非缺陷）。

---

*生成说明：本文档基于代码静态分析（后端 92 路由文件、前端 123 路由、DB 架构文档、开发规则、数据流向文档）整理，用于指导自动化 QA 测试套件设计与提示词提取。*
