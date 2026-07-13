# MDCX 项目命名规则与规范

> **版本:** v1.0  
> **日期:** 2026-07-13  
> **用途:** 统一 MDCX 全项目的命名风格，避免前后端、数据库、配置文件、路由之间的命名混乱

---

## 一、总体原则

| 原则 | 说明 |
|------|------|
| **一致性** | 同一范畴内的命名风格必须完全统一，不混用 |
| **可读性** | 命名优先表达"是什么"而非"怎样实现" |
| **短小精悍** | 在清晰的前提下尽量简短 |
| **中英分离** | 代码中全部使用英文，仅在用户可见的 UI 界面使用中文 |
| **禁止拼音** | 不使用拼音缩写（如 `jsz`、`xj`），用英文全拼或缩写 |
| **现有优先** | 已有文件/类/路由的命名风格不可随意更改，新代码遵循已有风格 |

---

## 二、项目级命名规范

### 2.1 项目名称

| 层级 | 命名 | 风格 | 示例 |
|------|------|------|------|
| 显示名称 | `MDCX` | 全大写缩写 | MDCX |
| npm package | `mdcx-server` / `mdcx-desktop` | `kebab-case` | `mdcx-desktop` |
| Docker 镜像 | `mdcx/server` / `mdcx/desktop` | `kebab-case` | `mdcx/server:latest` |
| 数据库文件 | `scraper.db` / `chinese.db` | 小写 `.db` | `chinese.db` |
| 配置文件 | `config.yaml` | 小写 `.yaml` | `config.yaml` |
| GitHub 仓库 | `MDCX` | 全大写缩写 | MDCX |

### 2.2 目录命名

```
MDCX/                          # 项目根目录，全大写缩写
├── MDCX-Server/               # 后端目录，PascalCase（已存在，不动）
├── MDCX-Desktop/              # 前端目录，PascalCase（已存在，不动）
├── docs/                      # 文档，全小写
├── .references/               # 参考项目，小写+下划线
├── scripts/                   # 构建/工具脚本
└── data/                      # 运行时数据
```

**规则：**
- 已有目录名不可改（`MDCX-Server`、`MDCX-Desktop` 保持原名）
- 新目录使用 `snake_case`
- 文档目录用单数 `docs/` 而非 `documentation/` 或 `doc/`

---

## 三、Python 后端命名规范（MDCX-Server）

### 3.1 文件/模块命名

| 类型 | 风格 | 示例 |
|------|------|------|
| 路由文件 | `snake_case` | `movies.py`, `file_organize.py`, `emby_push.py` |
| 数据模型 | `snake_case` | `models.py`, `chinese_models.py` |
| 配置 | `snake_case` | `models.py`, `manager.py` |
| 爬虫 | `snake_case` | `javbus.py`, `fc2ppvdb.py`, `theporndb_movies.py` |
| 服务 | `snake_case` | `watcher.py`, `fingerprint.py` |
| 任务 | `snake_case` | `scanner.py`, `organizer.py`, `scheduler.py` |
| 工具 | `snake_case` | `logger.py`, `http_client.py`, `i18n.py` |
| 刮削模块 | `snake_case` | `engine.py`, `merger.py`, `number.py` |

#### 3.1.1 新模块文件命名规则（5 模块扩展）

```
# 国产模块文件命名
chinese_models.py     # 数据模型
chinese_routes.py     # API 路由
chinese_scanner.py    # 扫描器
chinese_scraper.py    # 刮削器
folder_actor.py       # 文件夹演员识别（国产独有）

# 无码模块
uncensored_models.py
uncensored_routes.py
uncensored_scanner.py

# FC2 模块
fc2_models.py
fc2_routes.py
fc2_scanner.py

# PORNHub 模块
pornhub_models.py
pornhub_routes.py
pornhub_scanner.py
pornhub_scraper.py    # PORNHub 爬虫

# 模块通用
module_db.py          # 模块数据库管理器
module_models.py      # 模块配置模型
```

### 3.2 类/模型命名

| 类型 | 风格 | 示例 |
|------|------|------|
| Pydantic 配置模型 | `PascalCase` | `ServerConfig`, `DatabaseConfig`, `ScraperConfig` |
| SQLAlchemy ORM | `PascalCase` | `Movie`, `Actor`, `MovieActor`, `Studio` |
| 响应 DTO | `PascalCase` | `MovieResponse`, `ActorBrief`, `TagBrief` |
| 服务类 | `PascalCase` | `ConfigManager`, `BaseCrawler` |
| 爬虫类 | `PascalCase` | `JavBusCrawler`, `FC2PpvDbCrawler` |
| 私有类 | `_PascalCase` | `_SimpleCache` |

#### 3.2.1 新类命名（5 模块扩展）

```
# 国产模块
ChineseMovie           # 国产影片模型
ChineseActor           # 国产演员模型
FolderActorExtractor   # 文件夹演员提取器
ChineseScanner         # 国产扫描器
ChineseRoutes          # 国产 API 路由

# 模块配置
ChineseModuleConfig    # 国产模块配置（含 actor_from_folder）
UncensoredModuleConfig # 无码模块配置
FC2ModuleConfig        # FC2 模块配置
PornhubModuleConfig    # PORNHub 模块配置
ModuleDatabaseConfig   # 模块数据库配置

# 服务
LLMScraper             # LLM 刮削引擎
DedupEngine            # 三层去重引擎
YamlPluginLoader       # YAML 刮削插件加载器
NamingEngine           # 命名引擎
Watermark              # 水印工具
ImageCropper           # 封面裁剪工具
WorkflowPipeline       # 自动化工作流管道
ScraperMonitor         # 爬虫健康监控
```

### 3.3 函数/方法命名

| 类型 | 风格 | 示例 |
|------|------|------|
| 公共函数 | `snake_case` | `list_movies()`, `get_movie()`, `delete_movie()` |
| 私有方法 | `_snake_case` | `_merge_field()`, `_parse_sample_images()` |
| 异步函数 | `async def snake_case` | `async def scrape_movie()` |
| 模型验证器 | `snake_case` | `@field_validator("xxx")` |
| 属性 | `snake_case` | `movie.title`, `actor.name` |

#### 3.3.1 国产模块专用函数命名

```
# 文件夹演员识别
extract_actor_from_folder()    # 从文件夹名提取演员名
sync_folder_actors()            # 同步文件夹演员到数据库
count_movies_in_folder()        # 统计文件夹内影片数
clean_actor_name()              # 清洗演员名（去噪/标准化）

# 扫描流程
scan_chinese_media_dir()        # 扫描国产媒体目录
scan_with_folder_actor()        # 扫描并识别文件夹演员
merge_folder_actor_to_movie()   # 合并文件夹演员到影片记录

# 配置
get_chinese_module_config()     # 获取国产模块配置
update_actor_blacklist()        # 更新演员黑名单
set_actor_folder_depth()        # 设置文件夹深度
```

### 3.4 变量命名

| 类型 | 风格 | 示例 |
|------|------|------|
| 局部变量 | `snake_case` | `movie_count`, `file_path`, `total_pages` |
| 常量 | `SCREAMING_SNAKE_CASE` | `MAX_RETRY_COUNT = 3` |
| 类属性 | `snake_case` | `self.media_dirs`, `self.concurrent_limit` |
| 私有属性 | `_snake_case` | `self._cache`, `self._ref_count` |
| 布尔变量 | `is_xxx` / `has_xxx` | `is_uncensored`, `has_cover` |

### 3.5 路由命名

```
统一前缀: /api/v1

# 现有路由（不动）
/api/v1/movies          # 影片 CRUD
/api/v1/actors          # 演员
/api/v1/studios         # 工作室
/api/v1/series          # 系列
/api/v1/tags            # 标签
/api/v1/stats           # 统计

# 新模块路由
/api/v1/modules         # 模块管理（启用/禁用/配置）

/api/v1/chinese         # 国产模块
/api/v1/chinese/movies  # 国产影片
/api/v1/chinese/actors  # 国产演员
/api/v1/chinese/folders # 国产文件夹演员同步

/api/v1/uncensored      # 无码模块
/api/v1/uncensored/movies
/api/v1/uncensored/actors

/api/v1/fc2             # FC2 模块
/api/v1/fc2/movies
/api/v1/fc2/actors

/api/v1/pornhub         # PORNHub 模块
/api/v1/pornhub/movies
/api/v1/pornhub/actors
```

**路由命名规则：**
- 路径全小写，多词用 `snake_case`
- 资源名用复数（`/movies` 而非 `/movie`）
- 路由文件后缀统一为 `_routes.py`
- 每个模块的路由函数命名：`list_{resource}()`, `get_{resource}()`, `create_{resource}()`, `update_{resource}()`, `delete_{resource}()`

### 3.6 数据库命名

#### 3.6.1 数据库文件

```
data/database/
├── scraper.db              # JAV 有码（已有，不动）
├── uncensored.db           # JAV 无码
├── fc2.db                  # FC2
├── chinese.db              # 国产
├── pornhub.db              # PORNHub
└── shared.db               # 共享数据（用户/配置缓存）
```

#### 3.6.2 表名

| 规则 | 示例 |
|------|------|
| 全小写复数 `snake_case` | `movies`, `actors`, `studios` |
| 多对多关联表 | `movie_actors`, `movie_tags` |
| 国产模块特殊表 | `chinese_movies`, `chinese_actors`, `folder_actors` |

#### 3.6.3 列名

| 规则 | 示例 |
|------|------|
| 主键 | `id` |
| 外键 | `xxx_id` |
| 字符串 | `snake_case` |
| 布尔 | `is_xxx` |
| 时间 | `xxx_at` |
| 计数 | `xxx_count` |

**各模块列名差异：**

```sql
-- 通用字段（所有模块一致）
id              INTEGER PRIMARY KEY
code            TEXT UNIQUE
title           TEXT
cover_url       TEXT
file_path       TEXT
file_size       INTEGER
play_count      INTEGER DEFAULT 0
created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME

-- JAV 有码专用（已有，不动）
studio_id       INTEGER REFERENCES studios(id)
series_id       INTEGER REFERENCES series(id)
is_uncensored   BOOLEAN
is_mosaic       BOOLEAN

-- 国产模块专用
folder_name     TEXT            -- 所在文件夹名
folder_based_actors TEXT        -- 文件夹演员 JSON 数组
extracted_actor TEXT            -- 文件名提取的演员
studio          TEXT            -- 制作商（非外键，纯文本）

-- FC2 专用
is_mosaic       BOOLEAN        -- FC2 混合有码/无码
seller_id       TEXT            -- 卖家 ID

-- PORNHub 专用
source_views    INTEGER         -- 播放量
source_score    REAL            -- 评分
uploader        TEXT            -- 上传者
source_id       TEXT            -- 源站视频 ID
```

### 3.7 配置键命名（YAML）

```
小写 + 冒号分层（YAML 嵌套结构）

示例:
server:
  host: "0.0.0.0"
  port: 8420

modules:
  chinese:
    enabled: true
    media_dirs:
      - "E:/Media/Chinese"
    actor_from_folder:
      enabled: true
      folder_depth: 1
      blacklist:
        - "新建文件夹"
        - "合集"
```

**规则：**
- 一级键 = 服务/模块名（单数）
- 多词用 `snake_case`
- 布尔值用 `enabled` 而非 `enable` 或 `is_enabled`
- 列表用 `- ` 缩进

---

## 四、前端命名规范（MDCX-Desktop）

### 4.1 Vue 文件命名

| 类型 | 风格 | 示例 |
|------|------|------|
| 视图页面 | `PascalCase.vue` | `Movies.vue`, `MovieDetail.vue` |
| 通用组件 | `PascalCase.vue` | `MovieCard.vue`, `LazyImage.vue` |
| 基础组件 | `Base` + `PascalCase.vue` | `BaseButton.vue`, `BaseModal.vue` |
| 布局组件 | `Layout` + `PascalCase.vue` | `Layout.vue`, `ModuleLayout.vue` |

#### 4.1.1 新模块前端文件

```
src/views/chinese/
├── Movies.vue             # 国产影片列表（含文件夹演员标识）
├── Actors.vue             # 国产演员管理（文件夹演员+手动）
├── ActorDetail.vue        # 演员详情（含文件夹影片统计）
├── MovieDetail.vue        # 影片详情（标注"来自文件夹"）

src/views/uncensored/
├── Movies.vue
├── Actors.vue
├── MovieDetail.vue

src/views/fc2/
├── Movies.vue
├── Actors.vue
├── MovieDetail.vue

src/views/pornhub/
├── Movies.vue
├── Actors.vue
├── MovieDetail.vue

src/views/modules/
├── ModuleManager.vue      # 模块管理页面
├── ModuleConfig.vue       # 模块配置页面

src/components/chinese/
├── FolderActorSync.vue    # 文件夹演员同步组件
├── ActorFromFolder.vue    # 来自文件夹的演员标签组件
├── ActorFolderTree.vue    # 文件夹演员目录树组件
```

### 4.2 组件命名

| 类型 | 风格 | 示例 |
|------|------|------|
| 单文件组件 | `PascalCase` | `<MovieCard />`, `<BaseModal />` |
| 具名插槽 | `snake_case` | `<slot name="actor_info" />` |
| props | `camelCase` | `:mediaDir`, `:actorName` |
| emit 事件 | `kebab-case` | `@folder-sync`, `@actor-selected` |

### 4.3 前端路由命名

```javascript
// path = kebab-case, name = PascalCase

// 现有路由（不动）
{ path: '/movies',       name: 'Movies' }
{ path: '/movie/:id',    name: 'MovieDetail' }
{ path: '/actors',       name: 'Actors' }
{ path: '/actors/:id',   name: 'ActorDetail' }

// 新模块路由
{ path: '/module/chinese',       name: 'ChineseMovies' }
{ path: '/module/chinese/:id',   name: 'ChineseMovieDetail' }
{ path: '/module/chinese/actors', name: 'ChineseActors' }
{ path: '/module/uncensored',    name: 'UncensoredMovies' }
{ path: '/module/fc2',           name: 'FC2Movies' }
{ path: '/module/pornhub',       name: 'PornhubMovies' }
{ path: '/modules',              name: 'ModuleManager' }
{ path: '/modules/:name/config', name: 'ModuleConfig' }
```

### 4.4 Store 命名

```javascript
// 文件名 = camelCase, store名 = useXxxStore

// 现有（不动）
auth.js       → useAuthStore
movies.js     → useMoviesStore
theme.js      → useThemeStore
ui.js         → useUiStore

// 新模块
chinese.js    → useChineseStore
uncensored.js → useUncensoredStore
fc2.js        → useFc2Store
pornhub.js    → usePornhubStore
modules.js    → useModulesStore
```

### 4.5 API 模块命名

```javascript
// src/api/ 下每个模块一个文件
api/index.js              // 统一导出
api/movies.js             // JAV 有码（包装现有）
api/chinese.js            // 国产 API
api/uncensored.js         // 无码 API
api/fc2.js                // FC2 API
api/pornhub.js            // PORNHub API
api/modules.js            // 模块管理 API

// 函数命名 = camelCase
export async function getChineseMovies(params) {}
export async function syncFolderActors() {}
export async function getFolderActorTree() {}
```

---

## 五、数据库命名完整规范

### 5.1 数据库文件命名规则

```
{module_name}.db

module_name:
  scraper     → scraper.db       # JAV 有码（保持原名）
  uncensored  → uncensored.db     # JAV 无码
  fc2         → fc2.db            # FC2
  chinese     → chinese.db        # 国产
  pornhub     → pornhub.db        # PORNHub
  shared      → shared.db         # 共享库
```

### 5.2 表名规范

```
# 通用规则
全小写 + 下划线 + 复数

movies          # 影片
actors          # 演员
studios         # 工作室
series          # 系列
tags            # 标签
genres          # 分类/风格
favorites       # 收藏

# 关联表
movie_actors    # 影片-演员多对多
movie_tags      # 影片-标签多对多
actor_tags      # 演员-标签

# 国产模块专属
folder_actors   # 文件夹演员
```

### 5.3 列名规范速查表

| 数据类型 | 命名模式 | 示例 |
|----------|----------|------|
| 主键 | `id` | `id` |
| 外键 | `{table}_id` | `studio_id`, `series_id` |
| 字符串/文本 | 业务意义 | `title`, `code`, `plot` |
| 数字 | 业务意义 | `duration`, `rating`, `play_count` |
| 布尔 | `is_{adj}` / `has_{noun}` | `is_uncensored`, `is_chinese`, `has_cover` |
| 日期 | `{event}_date` | `release_date`, `created_at` |
| 时间戳 | `{event}_at` | `created_at`, `updated_at`, `scraped_at` |
| JSON | `{描述}_json` | `sample_images`, `folder_based_actors` |
| 计数 | `{noun}_count` | `play_count`, `movie_count` |

---

## 六、项目文件路径规范

### 6.1 后端代码路径

```
MDCX-Server/app/
├── api/routes/           # API 路由
│   ├── movies.py         # JAV 有码（不动）
│   ├── chinese_routes.py # 国产模块
│   ├── uncensored_routes.py
│   ├── fc2_routes.py
│   ├── pornhub_routes.py
│   └── modules.py        # 模块管理
│
├── crawlers/             # 爬虫
│   ├── javbus.py         # 现有
│   ├── javdb.py          # 现有
│   ├── md/               # 第三方/扩展爬虫
│   │   ├── guochan.py    # 国产标签列表
│   │   ├── madouqu.py    # 麻豆趣
│   │   └── fc2ppvdb.py   # FC2
│   └── pornhub.py        # PORNHub 爬虫（新建）
│
├── db/
│   ├── models.py         # JAV 有码模型（不动）
│   ├── chinese_models.py # 国产模型
│   ├── uncensored_models.py
│   ├── fc2_models.py
│   ├── pornhub_models.py
│   └── module_db.py      # 模块数据库管理器
│
├── scraper/
│   ├── number.py         # 番号识别（不动）
│   ├── engine.py         # 刮削引擎（不动）
│   ├── merger.py         # 多源合并（不动）
│   ├── folder_actor.py   # 文件夹演员识别（国产专用）
│   └── llm_scraper.py    # LLM 刮削引擎
│
├── services/
│   ├── dedup.py          # 三层去重引擎
│   ├── naming_engine.py  # 命名引擎（VaultX 风格）
│   ├── watermark.py      # 水印工具
│   ├── workflow.py       # 自动化工作流
│   └── scraper_monitor.py # 爬虫健康监控
│
├── tasks/
│   ├── scanner.py        # JAV 扫描器（不动）
│   ├── chinese_scanner.py # 国产扫描器
│   ├── uncensored_scanner.py
│   ├── fc2_scanner.py
│   └── pornhub_scanner.py
│
└── config/
    ├── models.py         # 主配置模型
    └── module_models.py  # 模块配置模型
```

### 6.2 前端代码路径

```
MDCX-Desktop/src/
├── views/
│   ├── Movies.vue            # JAV 有码（不动）
│   ├── Actors.vue            # JAV 有码（不动）
│   ├── chinese/              # 国产模块页面
│   │   ├── Movies.vue
│   │   ├── Actors.vue
│   │   ├── ActorDetail.vue
│   │   └── MovieDetail.vue
│   ├── uncensored/
│   ├── fc2/
│   └── pornhub/
│
├── components/
│   ├── MovieCard.vue         # 通用（不动）
│   ├── chinese/              # 国产专用组件
│   │   ├── FolderActorSync.vue
│   │   └── ActorFromFolder.vue
│   └── module/               # 模块通用组件
│       ├── ModuleTab.vue
│       └── ModuleConfig.vue
│
├── api/
│   ├── index.js              # 统一导出
│   ├── movies.js             # JAV 有码 API
│   ├── chinese.js            # 国产 API
│   ├── uncensored.js
│   ├── fc2.js
│   ├── pornhub.js
│   └── modules.js            # 模块管理 API
│
├── stores/
│   ├── movies.js             # JAV 有码（不动）
│   ├── chinese.js            # 国产 Store
│   ├── uncensored.js
│   ├── fc2.js
│   ├── pornhub.js
│   └── modules.js            # 模块管理 Store
│
└── router/
    └── index.js              # 路由配置（追加新模块路由）
```

---

## 七、Git 提交规范

### 7.1 提交信息格式

```
<type>(<scope>): <subject>

<body>
```

### 7.2 Type 类型

| Type | 用途 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(chinese): add folder actor extraction` |
| `fix` | 修复 | `fix(scanner): fix folder depth detection` |
| `refactor` | 重构 | `refactor(models): move chinese models to separate file` |
| `docs` | 文档 | `docs: add naming convention spec` |
| `style` | 格式 | `style: fix indentation` |
| `perf` | 性能 | `perf(scanner): optimize parallel directory scanning` |

### 7.3 Scope 范围

| Scope | 对应模块 |
|-------|----------|
| `chinese` | 国产模块相关 |
| `fc2` | FC2 模块相关 |
| `uncensored` | 无码模块相关 |
| `pornhub` | PORNHub 模块相关 |
| `jav` | JAV 有码（现有的） |
| `scanner` | 扫描器相关 |
| `scraper` | 刮削器相关 |
| `models` | 数据模型相关 |
| `api` | API 路由相关 |
| `ui` | 前端 UI 相关 |
| `config` | 配置相关 |
| `docs` | 文档相关 |

---

## 八、命名检查清单

在提交代码前，用此清单检查命名是否符合规范：

### 后端检查

- [ ] 新 Python 文件名是否是 `snake_case`？
- [ ] 新类名是否是 `PascalCase`？
- [ ] 新函数名是否是 `snake_case`？
- [ ] 私有方法是否以 `_` 开头？
- [ ] 常量是否使用 `SCREAMING_SNAKE_CASE`？
- [ ] 布尔变量是否以 `is_` / `has_` 开头？
- [ ] 路由路径是否全小写 `kebab-case`？
- [ ] 路由函数名是否 `snake_case`？
- [ ] DB 表名是否小写复数 `snake_case`？
- [ ] DB 列名是否 `snake_case`？

### 前端检查

- [ ] Vue 文件是否是 `PascalCase.vue`？
- [ ] Store 文件名是否是 `camelCase.js`？
- [ ] Store 函数名是否 `useXxxStore`？
- [ ] API 函数是否 `camelCase`？
- [ ] 组件名是否 `PascalCase`？
- [ ] 路由 path 是否 `kebab-case`？
- [ ] 路由 name 是否 `PascalCase`？

### 国产模块专用检查

- [ ] 文件夹演员相关命名包含 `folder_actor`？
- [ ] 国产模块配置键包含 `actor_from_folder`？
- [ ] API 路由以 `/api/v1/chinese/` 开头？
- [ ] 前端口径以 `chinese/` 开头？
- [ ] Store 名为 `useChineseStore`？

---

## 九、快速参考速查表

```
              Python           Vue/JS           DB/Config
─────── ────────────────── ──────────────── ─────────────────
文件      snake_case.py     PascalCase.vue     snake_case
                               camelCase.js
类/组件   PascalCase         PascalCase        snake_case (表)
函数      snake_case         camelCase         snake_case (列)
私有      _snake_case        _camelCase        —
常量      SCREAMING_SNAKE    SCREAMING_SNAKE   —
配置       YAML snake_case    —                snake_case
路由      /api/v1/snake      /kebab-case       —
布尔      is_xxx/has_xxx     isXxx/hasXxx      is_xxx
存储      useXxxStore (Pinia) —                —
```

---

## 十、附录：常见命名错误对照

| ❌ 错误 | ✅ 正确 | 说明 |
|---------|---------|------|
| `chinese_movie_api.py` | `chinese_routes.py` | 路由文件统一 `_routes` 后缀 |
| `ChineseScanner.py` | `chinese_scanner.py` | Python 文件不首字母大写 |
| `chineseMovies` | `chinese_movies` | Python 变量用 snake_case |
| `ChineseMovie` (数据库模型) | `ChineseMovie` ✅ | 类名 PascalCase 正确 |
| `/api/v1/chinese/movie` | `/api/v1/chinese/movies` | 路径资源名用复数 |
| `is_Chinese` | `is_chinese` | 布尔变量统一小写 |
| `folderActorSync` | `folder_actor_sync` | Python 函数用 snake_case |
| `jsz` | `chinese` | 不用拼音缩写 |
| `actor_from_folder_enabled` | `actor_from_folder.enabled` | YAML 用嵌套结构 |
