# JAV 有码 · 系列功能 + 类别封面 bug 修复

## 一、JAV 有码「系列」聚合功能

### 背景（数据库现状，读生产库 jav.db 确认）
- `series` 表 **0 行**；`movies.series_id` 全部为 NULL（印证 `movies.py:277` 注释）。
- `movies.series` 文本字段 **2329 部有值**，按文本聚合 **影片数 > 2 的系列共 173 个**（如「【初撮り】ネットでAV応募→AV体験撮影」76 部、「じんかくそうさ洗脳催●」39 部）。
- 结论：JAV 系列必须按 `movies.series` 文本字段聚合，不能依赖 series 表 / series_id FK。

### 新增后端 `app/api/routes/jav_series.py`（注册于 `/jav/series`）
- `GET /api/v1/jav/series`
  - 按 `movies.series` 文本 `GROUP BY` + `HAVING COUNT(*) >= min_count`（默认 2，即聚合 2 部及以上）聚合。
  - 返回 `total` / `total_movies`（全部系列涵盖影片总数）/ `items(name, movie_count)`。
  - 支持 `search`（系列名模糊）/ `min_count` / `page` / `page_size`，按影片数倒序。
- `GET /api/v1/jav/series/{series_name}/movies`
  - 某系列全部作品（按上映日期倒序分页），每项注入 `module_type="jav"`（封面端点拼接关键）。
  - 含 URL 编码双保险解码。
  - SQLite 兼容排序：`release_date.isnot(None).desc()`（不用 `nullslast()`）。

### 前端
- `src/api/index.js`：新增 `getJavSeries` / `getJavSeriesMovies`。
- `src/views/jav/Series.vue`：系列卡片网格 → 点进作品网格（复用 `MovieCard`，后端已带 `module_type` 故封面正常），含搜索、分页、返回。
- `src/router/index.js`：新增 `jav/series` 路由。
- `src/views/Layout.vue`：JAV 有码菜单新增「系列」入口（`Collection` 图标）。

## 二、类别页封面不显示（BUG 修复）

### 根因
通用 `/movies` 端点的 `MovieResponse` 缺 `module_type` 字段。类别详情走 `getMoviesByCategory` → 通用 `/movies`，返回的作品无 `module_type`，前端 `getMovieCoverUrl` 无法拼出模块专属封面端点 `/api/v1/jav/movies/{id}/cover/file`，回退到通用 `/movies/{id}/cover/file`（jav.db 查不到）→ 裂图。主库走 `getJavMovies`（本就带 `module_type`）故正常。

### 修复（`app/api/routes/movies.py`）
- `MovieResponse` 增加 `module_type: Optional[str] = None` 字段。
- 在 4 处构建（`list_movies` / `update_movie` / `reload_movie_from_nfo` / `get_movie`）注入 `module_type=module`。
- 顺带修复：所有经通用 `/movies` 端点访问的模块（uncensored/fc2/chinese/pornhub/western/anime）类别封面一并恢复正常。

## 三、验证
- 后端 `py_compile` 通过；`app.api` 包导入成功；`/jav/series` 与 `/jav/series/{series_name}/movies` 路由已注册。
- 对生产库副本执行与端点完全一致的聚合 SQL → 173 个系列、计数正确（数据层面确凿）。
- 前端 `vite build --config vite.config.web.js` 干净构建通过（`static` 单一批次：1 主包 + Layout + 各模块分块，含 `Series-X0XVjP6_.js`），`jav/series` 已进入包体。
- 说明：本地直接 HTTP 冒烟被认证中间件拦截（401，前端登录后带 token 即正常，非代码缺陷）；模块 DB 需 app 启动初始化，故未做无认证的端到端 HTTP 测试。生产环境需部署后由浏览器硬刷新做最终 QA。

## 四、部署清单（SMB 只读，服务器侧手动操作）
**后端**（拷到 `E:\MDCX-Server\app\...` 对应位置）：
- `app/api/routes/jav_series.py`（新增）
- `app/api/routes/movies.py`
- `app/api/__init__.py`

**前端**：把开发机 `G:\MDCX\MDCX-Server\static` 整目录覆盖 `L:\static`（`E:\MDCX-Server\static`），删净旧 static 再覆盖。

**重启**：重启服务器 `run.py`（8420）；浏览器 **Ctrl+Shift+R** 硬刷新清缓存。

**验收**：左侧 JAV 有码 → 系列 → 看到 173 个系列；点进任一系列看到作品且封面正常；类别页点类别进入后番号封面显示正常。
