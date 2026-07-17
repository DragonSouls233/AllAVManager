# 开发日志

## 2026-07-17 封面路径修复 + 运行时盘符自动检测

### 问题背景

服务端存储的封面图片和演员头像路径在数据库中的 `cover_url` / `output_dir` / `avatar_url` 字段指向了旧的路径（如 `C:\output\`、不同盘符的本地路径、HTTP URL），而实际文件位于服务端统一的 `data/` 目录下（`data/movies/{module}/{code}/cover.jpg`、`data/avatars/actor_{id}.jpg`）。

开发环境（G:\）和服务器环境（L:\ 或 E:\）盘符不一致，需要一套运行时可自动识别的路径机制。

### 改动清单

#### 1. 新增文件：`app/utils/media_helpers.py`

新建媒体工具函数共享模块，将 `movies.py` 中的下列私有函数提取为公共函数：

- `collect_media_dirs(cfg)` — 替代原有的 `_collect_media_dirs`，收集所有媒体目录（scraper + 各模块）
- `scan_media_dirs_for_cover(media_dirs, code, max_depth=3)` — 限深度搜索封面，替代原有的 `rglob(*)` 全盘扫描
- `scan_media_dirs_for_avatar(media_dirs, name, name_jp)` — 在媒体目录中搜索演员头像
- `search_video_in_media_dirs(media_dirs, code_lower)` — 限深度搜索视频文件，替代原有的 `rglob(*)` 全盘扫描

内部辅助函数：
- `_walk_depth_limited(base, max_depth)` — 限制深度的目录遍历生成器
- `_find_code_subdir_depth_limited(base, code_lower, max_depth)` — 限制深度的子目录搜索
- `_find_image_in_dir(directory)` — 在目录中搜索标准封面图片

#### 2. 修改文件：`app/api/routes/movies.py`

- **`_resolve_cover_path` 增强**：
  - step 2 新增：当 `movie.output_dir` 不存在时，回退到 `config.scraper.output_dir` 按 module/code 构造封面路径寻找
  - step 2 新增：当 `movie.output_dir` 为空时，直接尝试 config 输出目录
- 新增辅助函数：
  - `_search_cover_in_output_dir()` — 在 output_dir 中搜索标准图片
  - `_search_cover_in_config_output_dir()` — 根据 config 输出目录按 module/code 构造封面路径
- 将 `_SOURCE_MODULE_MAP` / `_source_to_module` 提前到文件顶部，消除重复定义
- 删除原有的 `_collect_media_dirs` 和 `_search_video_in_media_dirs` 函数定义
- 导入共享模块中的 `collect_media_dirs`、`search_video_in_media_dirs`、`VIDEO_EXTENSIONS`

#### 3. 修改文件：`app/api/routes/actors.py`

- `get_actor_avatar_file` 的 step 4 改用 `scan_media_dirs_for_avatar` 和 `collect_media_dirs`，消除跨模块导入风险（不再从 `movies.py` 导入私有函数）

#### 4. 修改文件：`app/config/manager.py`

**运行时盘符自动检测机制**（增强 `_resolve_data_dir`）：

优先级：
1. 环境变量 `MDCX_DATA_DIR` / `SCRAPER_DATA_DIR`（可绝对或相对项目根）
2. 项目根下的 `data/` 目录（`PROJECT_ROOT / data`）
3. 如果项目根下的 `data/` 不存在，遍历所有有效盘符（A-Z）查找 `\<盘符>:\MDCX-Server\data`
   - 找到后同步更新 `PROJECT_ROOT` 全局变量至对应盘符
4. 全部未命中 → 抛出 `FileNotFoundError`，记录所有已扫描盘符信息到日志

### 性能优化

- 所有目录搜索均使用深度受限遍历（`_walk_depth_limited` / `_find_code_subdir_depth_limited`），避免 `rglob(*)` 全盘扫描导致的长时间阻塞
- 封面搜索默认最大深度为 3 层，视频文件搜索默认最大深度为 4 层

### 跨环境兼容说明

| 环境 | 盘符 | `PROJECT_ROOT` | `DATA_DIR` | 封面查找路径 |
|------|------|----------------|------------|-------------|
| 开发机 | G:\ | G:\MDCX\MDCX-Server | G:\MDCX\MDCX-Server\data | G:\ 数据目录为空 → 回退至 media_dirs 搜索 |
| 服务器 | L:\ | L:\MDCX-Server | L:\MDCX-Server\data | L:\data\movies\{module}\{code}\cover.jpg 命中 |
| 服务器 | E:\ | E:\MDCX-Server | E:\MDCX-Server\data | E:\data\movies\{module}\{code}\cover.jpg 命中 |

### 需测试的场景

- [ ] 开发机 G:\ 后端启动后 API 正常响应
- [ ] 服务端 L:\ 封面图片正常显示（`_search_cover_in_config_output_dir` 命中）
- [ ] 服务端 L:\ 演员头像正常显示（`_get_avatar_path` 命中 `L:\data\avatars\actor_{id}.jpg`）
- [ ] 盘符遍历兜底机制：删除 PROJECT_ROOT 下 data/ 后启动，自动找到 L:\ 或 E:\ 上的 data 目录
- [ ] 环境变量覆盖：设置 `MDCX_DATA_DIR` 后，优先使用环境变量指定的路径
