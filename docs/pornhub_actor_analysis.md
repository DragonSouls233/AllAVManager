# PORNHUB 模块 · 演员读取与显示分析

> 分析范围：演员「如何进入数据库」与「扫描后如何展示」两条链路，含后端代码定位与前端渲染路径。
> 涉及文件：后端 `app/tasks/pornhub_scanner.py`、`app/api/routes/pornhub_routes.py`、`app/db/pornhub_models.py`、`app/scraper/pornhub_actor_scraper.py`、`app/api/routes/modules.py`；前端 `src/views/pornhub/Actors.vue`、`ActorDetail.vue`、`src/stores/pornhub.js`、`src/api/pornhub.js`、`src/utils/media.js`。

---

## 一、演员的「读取」方式（两条入口）

### 入口 A：扫描进入（主入口，source="scan"）
- 触发：`PornhubScanner.scan()` → `_scan_directory()`，目录结构约定 `G:\TEST\pornhub\[Channel] ActorName\videofile.mp4`。
- 解析：`extract_actor_and_nationality(folder_name)` 用正则从**文件夹名**提取演员名与国籍：
  - 去开头 `[Channel]` 标记；
  - 末尾 `[US]`/`(US)` 等 → 国籍（映射中英文，如 `US→美国`）；
  - 纯国籍目录（如 `M:\美国\`）→ 不当作演员；
  - 分类黑名单（`素人`/`Amateur`/`VIP`/`HD` 等）→ 跳过。
- 落库：每个根目录解析出 `actor_name` 后，若 `PornhubActor.name` 不存在则 `add(PornhubActor(name, nationality, source="scan", movie_count=1))`；已存在则 `movie_count += 1`。
- 收尾：`_update_actor_counts()` 用 `PornhubMovie.actor LIKE "%name%"` **重算**每个演员的 `movie_count`。

### 入口 B：影片刮削（source="scraper"）
- 触发：`scrape_pornhub_movie` / `scrape_all_pending_pornhub`。
- 解析：`scrape_result.actors`（刮削器返回的演员列表），**逐个**新建 `PornhubActor(name=ai.name, source="scraper", movie_count=1)`，并对已存在者 `movie_count += 1`。
- 同时把 `movie.actor = ",".join(actor_names)`（逗号分隔字符串）。

> 两条入口的 `source` 字段不同：扫描建的是 `scan`，刮削建的是 `scraper`；前端 `Actors.vue` 对 `source==="scraper"` 显示「来自爬虫」标签。

---

## 二、扫描后的「显示」方式

### 后端 API
- `GET /api/v1/pornhub/actors`：`select(PornhubActor).order_by(movie_count.desc())`，返回 `{id,name,nationality,avatar_url,movie_count,source,module_type:"pornhub"}`（**按作品数倒序**，作品多的演员排前面）。
- `GET /api/v1/pornhub/actors/{id}`：返回单演员详情（含 alias、created_at 等）。

### 前端渲染
- `stores/pornhub.js → loadActors()` 调 `getPornhubActors()` 拿全量列表 → `actors.value`。
- `Actors.vue`：卡片网格，每个卡片显示头像（`getAvatarSrc`）、`name`、`movie_count 部作品`、以及 `source==="scraper"` 时的标签。点击进入 `ActorDetail.vue`。
- `ActorDetail.vue`：左边头像+名字+作品数，右边「作品列表」用 `getCoverSrc(m)` 拉封面。
  - 注意：详情页 `onMounted` 调的是 `loadActors()`（拉全量）再 `.find(id)`，而非 `store.loadActorDetail(id)`（虽已实现但组件未用）——数据量小时无碍，量大时低效。

---

## 三、头像解析链路（关键，见结构图⑤）
前端 `getAvatarSrc(actor)`：演员带 `id + module_type="pornhub"` → 统一走
`GET /api/v1/modules/pornhub/actors/{id}/avatar/file`（`modules.py::get_module_actor_avatar_file`）。该端点解析顺序：
1. **优先** `DATA/avatars/pornhub/actor_{id}.jpg`（通用模块头像刮削 `_download_module_actor_avatar` 写入的文件，按 id 命名）；
2. **回退** `actor.avatar_url`：仅当它是**绝对本地路径**时直接读（pornhub 自带 `download_actor_avatar` 把头像下到 `DATA/avatars/pornhub/{safe_name}.jpg` 并把该绝对路径存进 `avatar_url`，故此兜底能命中）；
3. 都没有 → 返回 SVG 占位图（默认蓝底首字母头像）。

---

## 四、发现的问题 / 风险

| # | 问题 | 影响 |
|---|------|------|
| 1 | **双头像体系并存、命名不一致** | pornhub 自带 profile scraper 写 `DATA/avatars/pornhub/{name}.jpg`（按名），通用模块头像刮削写 `actor_{id}.jpg`（按 id）；前者只能靠 `avatar_url` 兜底读取，两套文件互不相干，易混淆、难清理。 |
| 2 | **前端无"刮削资料/头像"入口** | `Actors.vue`/`ActorDetail.vue` 只展示，不调用 `scrape_pornhub_actor_profile` 或通用头像刮削。扫描进来的演员默认无头像（占位图），除非在别处手动触发头像刮削。 |
| 3 | **演员命名口径不一致（多演员）** | 扫描按文件夹整段存（如 `"Anna + Sunny"`），影片刮削按 `scrape_result.actors` 逐个建表（`"Anna"`、`"Sunny"`）。同一批作品在两张表里名字不同，`movie_count` 的 `LIKE` 计数可能重复/遗漏，且两者不会合并。 |
| 4 | **movie_count 计数口径冲突** | 影片刮削每成功一次 `+1`（重刮会累加）；扫描 `_update_actor_counts` 用 `LIKE` 重算。两口径不一致，重刮后数字漂移。 |
| 5 | **详情页低效加载** | `ActorDetail.vue` 拉全量 actors 再 `.find`，应改用已有的 `loadActorDetail(id)`。 |

---

## 五、建议（按需取用）
- 统一头像命名：让 pornhub profile scraper 也走 `_download_module_actor_avatar`（写 `actor_{id}.jpg`），废弃按名的 `{name}.jpg` 文件，消除双体系。
- 前端 `ActorDetail.vue` 改用 `loadActorDetail(id)`；可选在 `Actors.vue` 加"批量刮削头像"按钮接通用端点。
- 多演员归一：扫描时对 `+`/`&` 拆分的文件夹名，逐个建独立 actor（与刮削口径对齐），避免 `"Anna + Sunny"` 与 `"Anna"` 分裂。
- `movie_count` 统一由扫描的 `LIKE` 重算口径维护，刮削路径不再 `+1`（或刮削也用重算）。

> 注：以上为**只读分析**，未改动任何代码。修复类 bug 见 `pornhub_fix_overview.md`（上一轮已落地 6 个写入/刮削 bug）。
