# MDCX 项目长期笔记

## 里番模块 · 自刮削架构与生态调研（2026-08-07 新增，重要）

- **第7模块 anime**：独立 `anime.db`（ANIME_BASE），文件在 `J:\动漫\{1999..2025}\`，两种文件名格式：
  老（2012–2024）`[制作商]标题[DVD番号].mkv`，NFO 已刮好（含 studio/set/premiered/runtime/genre）；新（2025）`[YYMMDD][制作商]标题[人员].cht.mp4` 瘦 NFO。
- **刮削源 = 唯一 getchu.com**：www.getchu.com 按 DVD 番号搜索（`php/search.phtml?genre=all&search_keyword={番号}&gc=gc`，EUC-JP）。
  老数据只读 NFO 不刮；只有无/瘦 NFO 的新增文件且 `online_enrich=True`（module_models 已默认开）才自刮削。
- **自刮削器** `app/scraper/anime_getchu.py`（AnimeGetchuScraper）：
  检索回退（番号→标题+制作商）→ 多候选评分（番号命中100 > 标题重合50 > 制作商20）→ 详情页（年龄墙すすむ）→ xpath 解析
  → dl.getchu.com 桥接补全（见下）→ 落盘 `data/movies/anime/{code}/`（poster.jpg + movie.nfo + extrafanart/01~NN.jpg）。
  公共链路 `scrape_anime_and_apply()` 供扫描器 `_self_scrape` 与手动端点共用；仅填空字段，幂等。
- **方向A双站互补（2026-08-07 已实现）**：www.getchu 详情页含 `dl.getchu.com` 链接时，抓 DL 版页用
  metatube-sdk-go 移植的结构化选择器补全：サークル=制作商 / 配信開始日 / 趣向=类型 / 作品内容=简介 /
  预览图(`td[contains(@style,'background-color: #444444')]//a/@href`) / 封面(`td[@bgcolor='#ffffff']//img`)。
- **手动刮削入口**：前端 AnimeMovies.vue 卡片「刮削」按钮（status=pending 显示）+「批量刮削未刮削」+ 弹窗预览图区；
  后端 `POST /api/v1/anime/movies/{id}/scrape`、`POST /api/v1/anime/movies/scrape-pending`。
- **网络注意**：开发机到 www.getchu.com 直连被墙/封锁（ConnectionReset），**验证必须在服务器 192.168.10.110 侧**；
  dl.getchu.com 开发机可通。请求必须带浏览器指纹（项目 AsyncHttpClient=curl_cffi，裸 requests 会被重置）。
- **生态调研结论**：Emby.JavScraper 无里番源；NASTool 仅 TMDB 不支持成人；MetaTube/AvBase 带 Getchu 但走 dl.getchu
  商品 ID（GETCHU-数字）与 DVD 番号不匹配，只能当第二源兜底；metatube-sdk-go `provider/getchu/getchu.go`
  是 GitHub 活跃维护的成熟 getchu 实现（方向A移植来源）。

## 环境拓扑（重要，排查前必读）

| 位置 | 含义 | 可写性 |
|------|------|--------|
| `G:\MDCX\MDCX-Server` | **开发机**本地源码（在这里改代码） | 可读写 |
| `G:\MDCX\MDCX-Desktop` | 前端源码（Vue） | 可读写 |
| `L:\` | 网络映射 = `\\192.168.10.110\MDCX-Server` = **服务器上的 `E:\MDCX-Server`** | **只读**（SMB 权限） |
| `L:\data\database\` | 服务器真实数据库目录（system.db / jav.db / fc2.db / ...） | **只读** |
| `L:\data\logs\app.log` | 服务器日志，**每次启动被清空**，崩溃早期的日志抓不到 | 只读 |

关键结论：
- 服务器进程跑在 **192.168.10.110** 上，开发机 `tasklist` / `taskkill` **看不到也杀不掉**它。
  在开发机杀 python 进程是无效操作（那些是本机自己的进程）。
- 向 `L:` 写文件或改数据库会报 `Permission denied` / `attempt to write a readonly database`，
  **这是 SMB 只读共享导致的，不是进程占用**。部署必须由用户在服务器侧手动复制。
- 可以从 `L:` **读**服务器代码和数据库来做诊断（复制到本地再跑测试是可行的）。

## 架构陷阱：两个都会打开 system.db 的类

- `app/db/database.py` → `class Database` / `get_database()`
  **启动流程 (`main.py` → `init_database`) 实际使用的就是它**，服务代码里 `get_database()` 拿到的也是它。
- `app/db/system_db.py` → `class SystemDatabase`
  另一套封装，**启动时并不会被调用**。

历史事故：`scan_records` 加 `removed_files` 列时，迁移只写进了 `SystemDatabase.init()`，
而启动跑的是 `Database.init()`（只有 `create_all`，不改已存在的旧表），
于是"迁移代码明明存在却完全没生效"，直到 INSERT 时才报
`table scan_records has no column named removed_files`。

**现已修复**：迁移逻辑统一收敛到 `app/db/schema_migrations.py`，
`Database.init()` 与 `SystemDatabase._migrate_schema()` 都调用 `apply_required_columns()`。
以后新增历史列**只改 `SYSTEM_REQUIRED_COLUMNS` 一处**，不要在别处再写 ALTER。

另注意 `ScanRecord` 有两处定义：`db/models.py:565`(旧 Base) 与 `db/system_models.py:120`(SystemBase)，
`scan_control.py` 用的是后者。

## 数据模型约定

- `JavMovie.actor` 是**逗号分隔的演员名文本**，扫描器只写这个字段。
- `MovieActor` 关联表存在但**扫描器从不填充**（恒为空）——
  任何按演员查作品的逻辑都必须用 `movie.actor LIKE '%名字%'`，不能 join 关联表。
- 演员头像真相源（2026-08-07 改为按模块隔离）：`DATA/avatars/{module}/actor_{id}.jpg`，
  **module ∈ jav/fc2/uncensored/chinese/western/pornhub**（各模块 actors 表 id 独立自增，必须用子目录隔离，否则串图）。
  旧全局 `DATA/avatars/actor_{id}.jpg` 仅作 **jav 的历史兼容回退**（其余模块禁止回退，否则再次串图）。
  读取端点：`modules.py get_module_actor_avatar_file`（带 module_type 的演员走这）、`actors.py get_actor_avatar_file`（jav，默认 module=jav）、`jav_routes.py`。
  下载/落盘：`modules.py _download_module_actor_avatar(module_name=)`、`actors.py _download_actor_avatar(module=)`、`actors.py upload_actor_avatar`。
  `avatar_url` 字段应存**真实本地绝对路径**，不能存路由字符串
  （详情页会把它当文件路径经 `files/proxy` 加载）。
- **头像跨模块 id 撞车陷阱（重要）**：6 模块 actors 表 id 各自从 1 自增，若头像存成单一全局 `actor_{id}.jpg`，
  jav 的 id=1 小沢菜穂 会被 无码 id=1 ASUKA 等读取到 → 串图。新增头像读写一律带 module 子目录，
  不要回退到全局（jav 除外）。`scraper/actor_avatar.py`、`gfriends_importer.py`、`importer/sync.py` 仍写全局，
  因非 jav 模块已不读全局，故不会串图；jav 经 actors.py/jav_routes 全局回退仍正常。

## 协作约定

- 用户要求：直接修改 G 盘源码并给出部署命令，**不要让用户手动改代码或自己贴代码片段**。
- 服务器部署因共享只读，只能由用户在服务器侧执行复制 + 重启。
- 回复语言：简体中文。

## 认证中间件白名单（重要，媒体端点必读）

- `app/api/auth_middleware.py` 的 `AuthMiddleware` 是全局 ASGI 中间件，对所有 `/api/` 请求校验 Bearer token。
- 浏览器**不会**给 `<img>` / `<video>` 资源请求带 `Authorization` 头。因此任何「经 `<img>`/`<video>` 直连加载的图片/视频字节端点」**必须在 `AuthMiddleware` 白名单放行**，否则一律 401 → 裂图/裂视频。
- 已白名单的：`/api/v1/actors/.../avatar/file`、`/api/v1/movies/.../{cover,poster,thumb}/file`、模块 `/{mod}/.../cover/file` 与 `/{mod}/.../avatar/file`、`/{mod}/.../play/file`、HLS、`/api/v1/player/...` 静态资源、`/api/v1/previews/.../file`。
- **新增媒体文件代理端点时，第一反应就是去 `auth_middleware.py` 加白名单**，别只在路由层考虑鉴权。
- 反面案例：详情页预览图(previews.py)上线后全裂图，根因就是漏了 `/api/v1/previews/.../file` 白名单（见 `2026-08-07.md`）。

## 补丁刮削死循环陷阱（字段重要性分级）

- `_detect_module_missing_for_engine` 对空字段**必须**按重要性分级（critical/normal/optional），绝不能全标 `critical`。
- 不分局：rating=0% 填充、tag=0%、director=0% — 刮削源 (javbus/javdb) 根本不提供这些字段 → 每次检测全量查出 → 刮了白刮 → 下次又全量 → 死循环。
- 正确做法：只有 title/release_date 是 critical；plot/genre/actor/cover/studio 是 normal；其余 optional。
- 默认 `skip_complete=True` 时 Skipper 只放行 critical 缺失项，避免无意义的重新刮削。
- 补刮成功后**必须更新 `scraped_at`**，否则 `skip_recent_days` 机制对成功项无效。
- 见 `2026-08-07.md` 修复详情。

## 用户偏好：本地优先（重要架构取向）

- 用户**明确偏好本地方案**而非远程外链：刮削时把站点 URL 数据下载到 `MOVIES/{模块}/{番号}/`，下载后除非重刮/删除否则不变更。
- 详情页/前端**只读本地文件**，通过后端代理端点（`/previews/…`）暴露本地图，彻底绕过 DMM/javbus 的 Referer 防盗链（直连外链会 403 裂图）。
- 落盘结构：`{data_base}/movies/{module}/{code}/` 下 `poster/fanart/thumb/cover.jpg + movie.nfo + extrafanart/01~NN.jpg`。
- 设计规范（详情页）：左封面右信息 → 下面简介 → 下面预览区，**第一张是封面，后续是预览图**。
- 已落地实现见 `2026-08-07.md`（previews.py 通用路由 + MovieDetail.vue 改读本地接口）。

## 数据中心统一管理约定（扫描时归集资源）

- 用户主张：每个番号视频目录下必有 `视频 + movie.nfo + 2张封面图(poster/fanart)`。为省网络/性能，
  **扫描发现新视频时立即把 NFO + 封面从视频目录复制到数据中心** `data/movies/{module}/{code}/`，
  之后所有读写只针对数据中心目录，视频目录不再作为第一数据源。
- 入口：`app/tasks/base_scanner.py::copy_video_assets_to_data_dir()`；6 个 scanner 在 `session.add(new_movie)` 后
  以 `asyncio.ensure_future(...)` 触发（fire-and-forget，不阻塞扫描事务）。
- NFO 不受图片最小体积阈值限制（文本通常 <1KB），复制时只对图片做 `>=1KB` 校验。
- 资源名归一：`poster/folder.jpg→poster.jpg`、`fanart/background/backdrop.jpg→fanart.jpg`、`cover/landscape.jpg→cover.jpg`、png 同归 jpg。
- 与补刮协同：补刮(`patcher/strategy.py`)只读数据中心 NFO + 仅下载 extrafanart 预览图，不再重复下载封面。

## import 真相源 + 头像端点防护（2026-08-07 新增）

- `get_config_manager` 唯一真相源：**`app/config/manager.py:474`**。
  `app.utils.config_manager` 模块**不存在**——`modules.py:440` / `jav_routes.py:347` 曾引用它，
  ImportError 被 `try/except pass` 吞掉后表现为**功能静默失效**（头像端点永远返回占位图）。
  凡新增代码需拿配置管理器，一律 `from app.config.manager import get_config_manager`。
- 模块演员模型（`db/_module_mixins.py::ActorMixin`）**只有 `avatar_url`，没有 `avatar_path` 列**。
  头像端点写 `_Path(getattr(actor, "avatar_path", "") or "")` 会得到 `Path(".")`（`exists()`=True）
  → `FileResponse(".")` → `RuntimeError: File at path . is not a file` → HTTP 500。
  正确写法：`p = getattr(actor, "avatar_path", "") or ""; if p and _Path(p).is_absolute() and _Path(p).is_file(): FileResponse(p)`。
- 头像约定文件：`{data_dir}/avatars/actor_{id}.jpg`（jav 演员 id 为 jav.db 主键）。
  列表页头像走 `/api/v1/modules/{mod}/actors/{id}/avatar/file`（modules.py，通用 6 模块）；
  详情页头像走 `/api/v1/actors/{id}/avatar/file?module=jav`（actors.py，四级查找：DATA/avatars → avatar_url → gfriends → media_dirs）。
- 排查"列表页全占位图但磁盘有头像文件"类问题，第一反应检查：① 端点内 import 是否指向不存在的模块路径（被 except 吞）；② avatar_path 空值是否触发 FileResponse 500。
