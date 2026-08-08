# MDCX 项目长期笔记

## 环境拓扑（排查前必读）
- `G:\MDCX\MDCX-Server` 开发机源码；`G:\MDCX\MDCX-Desktop` 前端源码（均可写）。
- `L:\` = `\\192.168.10.110\MDCX-Server` = 服务器 `E:\MDCX-Server`，**SMB 只读**。向 `L:` 写会 `Permission denied` / `readonly database`，**不是进程占用**，部署须服务器侧手动复制。
- 服务器进程在 `192.168.10.110`，开发机 `tasklist`/`taskkill` 看不到；可从 `L:` **读**代码与库做诊断。
- 后端 FastAPI（`G:\MDCX\MDCX-Server`，服务器 `L:/app`，数据 `L:/data`，静态 `L:/static`）+ Vue3/Element-Plus/Pinia 前端（`G:\MDCX\MDCX-Desktop`）。6 模块独立 DB（`L:/data/database/{module}.db`），演员 id 各自自增。

## 里番模块 anime（2026-08-07）
- 第7模块独立 `anime.db`（ANIME_BASE），文件在 `J:\动漫\{1999..2025}\`。老（2012–2024）`[制作商]标题[DVD番号].mkv` 已刮 NFO；新（2025）`[YYMMDD][制作商]标题[人员].cht.mp4` 瘦 NFO。
- 唯一刮削源 getchu.com（EUC-JP，按 DVD 番号搜索）；老数据只读 NFO，仅新瘦 NFO 且 `online_enrich=True` 才自刮削。
- 自刮削器 `app/scraper/anime_getchu.py`（AnimeGetchuScraper）：番号→标题+制作商回退，多候选评分，年龄墙详情页 xpath，dl.getchu.com 桥接补全；落盘 `data/movies/anime/{code}/`。
- 网络：开发机到 www.getchu 被墙（ConnectionReset），验证须在服务器侧；dl.getchu.com 开发机可通；请求须带浏览器指纹（curl_cffi）。

## 架构陷阱
- 两个都开 system.db 的类：`app/db/database.py::Database`（启动实际用）vs `app/db/system_db.py::SystemDatabase`（启动不调用）。`ScanRecord` 两处定义（`db/models.py:565` 旧 Base / `db/system_models.py:120` SystemBase，`scan_control.py` 用后者）。
- 迁移统一收敛到 `app/db/schema_migrations.py`，只改 `SYSTEM_REQUIRED_COLUMNS` 一处。
- `get_config_manager` 唯一真相源 `app/config/manager.py:474`；不存在 `app.utils.config_manager`（引用会被 except 吞致静默失效）。
- 模块演员模型 `db/_module_mixins.py::ActorMixin` 只有 `avatar_url` 无 `avatar_path`；写头像端点用 `avatar_path` 会 `FileResponse(".")` → 500。正确：`if p and _Path(p).is_absolute() and _Path(p).is_file(): FileResponse(p)`。
- 非 ASCII 文件名端点：`Content-Disposition` 直写中文/日文名会 `UnicodeEncodeError` → 500。统一 `app/utils/http_headers.py::safe_content_disposition()`。已落地 7 个播放端点。

## 数据模型约定
- `JavMovie.actor` 是逗号分隔演员名文本；`MovieActor` 关联表**恒为空**，按演员查作品一律 `movie.actor LIKE '%名字%'`，不 join 关联表。
- **演员头像按模块隔离**：真相源 `DATA/avatars/{module}/actor_{id}.jpg`，module ∈ jav/fc2/uncensored/chinese/western/pornhub。旧全局 `avatars/actor_{id}.jpg` 已弃用（2026-08-08 迁移到 `avatars/jav/`）。**6 模块均不读全局目录**，否则 id 撞车串图。
- 头像端点：列表页 `/api/v1/modules/{mod}/actors/{id}/avatar/file`（modules.py）；详情页 `/api/v1/actors/{id}/avatar/file?module=jav`（actors.py 四级查找：DATA/avatars → avatar_url → gfriends → media_dirs）。`avatar_url` 存真实本地绝对路径，详情页当文件路径经 `files/proxy` 加载。
- 落盘 `movie.nfo + poster/fanart/thumb/cover.jpg` 在 `{data_base}/movies/{module}/{code}/`。扫描即把 NFO+封面复制到数据中心（`base_scanner.copy_video_assets_to_data_dir`，fire-and-forget），之后只读数据中心。

## 认证中间件白名单（媒体端点必读）
- `app/api/auth_middleware.py` 全局校验 Bearer；浏览器 `<img>/<video>` 不带 Authorization → 直连媒体字节端点必须白名单放行，否则 401 裂图/裂视频。
- 已白名单：`/api/v1/actors/.../avatar/file`、`/api/v1/movies/.../{cover,poster,thumb}/file`、模块 `/{mod}/.../cover/file`、`/{mod}/.../avatar/file`、`/{mod}/.../play/file`、HLS、`/api/v1/player/...`、`/api/v1/previews/.../file`。新增媒体端点第一反应加白名单。

## 补丁刮削死循环陷阱（字段重要性分级）
- 空字段必须分级：**critical** = title/release_date；**normal** = plot/genre/actor/cover/studio；**optional** = 其余。绝不能全标 critical（rating/tag/director 源不提供→全量查出→死循环）。
- 默认 `skip_complete=True` 只放行 critical 缺失；补刮成功后必须更新 `scraped_at`。

## 协作约定
- 直接改 G 盘源码并给部署命令，不让用户手改/贴代码。部署因 SMB 只读只能服务器侧复制+重启。回复简体中文。
- 用户偏好本地优先：刮削数据下载到 `MOVIES/{模块}/{番号}/`，前端只读本地文件经后端代理（`/previews/…`）绕过 Referer 防盗链。详情页：左封面右信息→简介→预览区（首张封面，后续预览图）。
- **演员详情页（前端）**：单演员详情统一走通用端点 `commonApi.getActor(id, module)`（`/api/v1/actors/{id}?module={module}`，actors.py 已全模块支持且有 `actor LIKE` 回退）。切勿走各模块专属单 actor 端点（uncensored 等模块根本无该端点→404→全空）。
- **部署务必同步前端构建**：服务器 `L:\static` 须复制开发机 `G:\MDCX\MDCX-Server\static` 最新产物，并硬刷新（Ctrl+Shift+R）清缓存旧 `index.html`，否则"修了还是老样子"。
