# PORNHUB 演员读取/显示 · 本轮修复清单

> 上一轮分析（`pornhub_actor_analysis.md`）定位 5 个问题，本轮按推荐优先级（1 头像统一 + 3 多演员归一 + 4 movie_count）落地，并补齐 2（前端缺刮削入口）与 5（详情页低效加载）。
> 改动文件：后端 `app/api/routes/pornhub_routes.py`、`app/tasks/pornhub_scanner.py`；前端 `src/api/pornhub.js`、`src/views/pornhub/ActorDetail.vue`、`src/views/pornhub/Actors.vue`。

## 修复明细

### ① 头像统一落盘为 `actor_{id}.jpg`（核心显示修复）
- **根因**：5 个 profile 刮削路径都只把**远程 URL** 写进 `actor.avatar_url`；而模块头像端点 `get_module_actor_avatar_file` 对远程 URL 不服务（仅服务本地文件），导致刮削后头像仍显示占位图。pornhub 自带 scraper 虽下载到 `avatars/pornhub/{name}.jpg`，但端点优先读 `actor_{id}.jpg`，命名不一致 → 兜底也常不命中。
- **修复**：新增模块级辅助 `_store_pornhub_actor_avatar(actor, url, name)`，下载头像到本地后**复制到 `DATA/avatars/pornhub/actor_{id}.jpg`**（端点优先读取的约定命名），并把 `actor.avatar_url` 指向该本地文件（双保险）。应用到全部 5 个路径：
  - `scrape_pornhub_actor_profile`（单刮）
  - `scrape_all_pornhub_actor_profiles`（批量非增强）
  - `scrape_actor_profile_enhanced`（增强单刮）
  - `scrape_all_actor_profiles_enhanced`（增强批量，含去重判定同步支持 `actor_{id}.jpg`）
  - `run_pornhub_full_workflow`（完整工作流）
- **效果**：刮削成功后头像真正显示，且与通用模块头像刮削（`actor_{id}.jpg`）命名体系统一。

### ② movie_count 计数口径统一
- 单部刮削：`db_actor.movie_count += 1` → 改为 `_recount_actor_movie_count(session, name)`（按 `movie.actor LIKE "%name%"` 重算），避免重复刮削同一影片时累加。
- 批量刮削：原逻辑对**已存在**演员根本不更新计数（漏算），现同样改为重算；新演员仍 `movie_count=1`。
- 新增辅助 `_recount_actor_movie_count`，与扫描 `_update_actor_counts` 口径一致。

### ③ 多演员按名拆分归一
- 新增 `_split_actor_names(name)`：把 `"Anna + Sunny"` / `"A & B"` / `"A, B"` 按 `+ & , /` 拆成独立演员名。
- 扫描 `_scan_directory` 中，对解析出的文件夹名**逐个建表**（如 `Anna`、`Sunny`），与影片刮削逐个建表口径对齐；`movie.actor` 仍保留原整段字符串用于 `LIKE` 计数。
- **效果**：消除「扫描建出 `Anna + Sunny` 整段、刮削建出 `Anna`/`Sunny`」导致的分裂与计数/展示不一致。

### ④ 前端补齐刮削入口（让头像真正可触发）
- `src/api/pornhub.js` 新增 `scrapePornhubActorProfile(id)`、`scrapeAllPornhubActorProfilesEnhanced()`。
- `ActorDetail.vue`：新增「刮削资料/头像」按钮（触发后重载详情）。
- `Actors.vue`：新增「批量增强刮削」按钮，可一次性补齐全部演员资料/头像。

### ⑤ 详情页高效加载
- `ActorDetail.vue` `onMounted` 由 `loadActors().find(id)` 改为 `store.loadActorDetail(id)`，直接取单演员详情，去掉拉全量再查找。

## 验证
- 后端 `pornhub_routes.py`、`pornhub_scanner.py` 均通过 `py_compile`。
- 静态确认：无残留 `movie_count += 1`；无「只写远程 avatar_url」的赋值；`_store_pornhub_actor_avatar` 覆盖全部 5 个路径；scanner `re` 已导入。

## 部署提示
- 后端 2 个文件需覆盖到服务器 `192.168.10.110` 对应源码并重启（SMB 只读，需服务器侧操作）。
- 前端 3 个文件改动后**必须重新构建**并复制产物到 `L:\static`，浏览器硬刷新（Ctrl+Shift+R）清缓存。
