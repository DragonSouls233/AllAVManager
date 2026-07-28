# MDCX 六大模块全面升级 — 开发计划

版本：v2.0 | 日期：2026-07-28

---

## 一、项目愿景

将 MDCX 从"JAV 有码为主，其他模块为辅"的架构，升级为 **6 个完整独立的内容管理模块**，每个模块拥有各自完整的影片库、演员库、刮削工具、对比查重、NFO 管理、播放等功能。功能归属于模块而非散落在系统工具中。

---

## 二、总体架构

```
MDCX v2.0
├── 🏠 首页                    ← 6 模块概览仪表板
├── 🎬 JAV 有码                ← 完整独立模块
├── 🔓 JAV 无码                ← 完整独立模块
├── 📹 FC2                     ← 完整独立模块
├── 🇨🇳 国产                    ← 完整独立模块（无对比查重）
├── 🌐 PORNHub                 ← 完整独立模块
├── 🌍 欧美                    ← 完整独立模块（新建）
└── ⚙️ 系统                    ← 全局服务（设置/下载器/代理/备份/Bot/插件）
```

### 核心原则

1. **演员和系列每个模块独立** — 各模块有自己的演员表、系列表、制片厂表
2. **功能归属模块** — 刮削/对比/补丁/NFO/播放都在模块内部，不在系统工具中
3. **按模块特性定制** — 国产无标准化番号，所以没有本地对比和对比演员
4. **对比查重** — 适用于 JAV有码/无码/FC2/PORNHub/欧美（国产除外）

---

## 三、各模块功能矩阵

### 3.1 功能对照表

| 功能组 | 具体功能 | JAV有码 | 无码 | FC2 | 国产 | PHub | 欧美 |
|--------|---------|:------:|:----:|:---:|:---:|:----:|:----:|
| **内容管理** | 影片列表+搜索+筛选 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 影片详情 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 演员库（独立） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 系列管理（独立） | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| | 制片厂/工作室 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 收藏/标签 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 字母导航 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| | 封面墙 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **刮削工具** | 多源爬虫管理 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 站点优先级 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 单部/批量刮削 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 补丁刮削 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 文件夹扫描 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 多来源数据精选 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| **对比查重** | 本地 vs 在线对比 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| | 对比演员库 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| | 视频指纹去重 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 三态标记 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **播放工具** | 播放串流 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | 缩略图/GIF/章节 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| | NFO 导出/导入/重载 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |

### 3.2 模块独有功能

| 模块 | 独有功能 |
|------|---------|
| **JAV 有码** | -C/-U 后缀中字识别、番号提取测试、女优合并、自定义封面 |
| **JAV 无码** | 无码平台专有番号识别 |
| **FC2** | FC2-xxx 番号识别、FC2 离线下载 |
| **国产** | **去广告命名规范管理器**、文件夹演员识别、LLM 智能兜底、海角社区 |
| **PORNHub** | **对比查重(PSP引擎)**、flashvars 封面提取、演员资料刮削、**Porn_Fetch下载引擎**、rodrigogs API增强** |
| **欧美** | IAFD 资料、ThePornDB 刮削、品牌管理、1000+站点刮削 |

---

## 四、参考资产总表（扩展版）

### 4.1 本地参考目录核心资产

| 资产 | 路径 | 核心能力 | 复用于 |
|------|------|---------|--------|
| **JavBoss v1.9.0** | `.references\GitHub\JavBoss-main` | 女优合并、片商合并、目录管理NFO导出、JAV详情弹窗+样品图、MPV复用、浏览器播放、FFmpeg检测下载、番号提取测试工具 | JAV有码/无码/FC2 增强 |
| **CommunityScrapers** | `.references\GitHub\CommunityScrapers-master` | AyloAPI(40+品牌)、AlgoliaAPI、VixenNetwork(GraphQL)、IAFD、Pornhub YAML | **欧美模块**、PORNHub |
| **PornSimilarityPlatform(PSP)** | `.references\本地\PornSimilarityPlatform` | PORNHub对比查重(missing_finder)、TitleNormalizer、PornHubUrlDetector、Downloader引擎 | PORNHub对比查重 |
| **stash** | `.references\GitHub\stash-develop` | 完整媒体管理平台架构(Go+GraphQL) | 整体架构参考 |
| **mnamer** | `.references\GitHub\mnamer-main` | 智能文件命名系统 | 命名引擎（已集成） |
| **gfriends** | `.references\GitHub\gfriends` | 2.8K stars，演员头像仓库目录 | 头像匹配（已集成） |
| **ReelSorter** | `.references\本地\ReelSorter` | 视频查重、FFmpeg处理 | 视频指纹去重 |
| **JavSP** | `.references\GitHub\JavSP-master` | 汇总多站点AV元数据刮削 | JAV刮削参考 |
| **videohash** | `.references\GitHub\videohash-main` | 视频感知哈希(pHash)去重 | 视频指纹去重 |
| **xbmc** | `.references\GitHub\xbmc-master` | NFO标准实现 | NFO兼容性参考 |

### 4.2 JavBoss v1.9.0 可复用功能

| 功能 | 参考代码 | 行数 | MDCX 实现方式 |
|------|---------|------|-------------|
| **女优合并(演员别名)** | `internal/db/jav.go MergeJavIdols` | ~90行 | 新增 API + 迁移 |
| **片商合并(名称/别名)** | v1.9.0 最新特性 | ~80行 | 新增 API |
| **目录管理(NFO导出/封面导出/整理)** | `internal/server/directory_api.go` + 前端 | ~200行 | 复用已有NFO+新增批量 |
| **JAV详情弹窗+样品图** | 前端JAV详情弹窗 | — | 前端组件复用 |
| **浏览器播放器FFmpeg检测** | 配置API+前端设置 | ~100行 | 新增 FFmpeg API |
| **番号提取测试工具** | v1.8.0 | ~50行 | 返回多匹配结果 |

### 4.3 EchterAlsFake 系列API（PORNHub/欧美）

| 项目 | 本地路径 | 核心能力 | 复用于 |
|------|---------|---------|--------|
| **Porn_Fetch** | `Porn_Fetch-master` | PySide6桌面应用，**完整的PORNHub下载管理**：flashvars提取、多线程下载、搜索/浏览/演员 | PORNHub模块下载增强 |
| **eaf_base_api** | `eaf_base_api-master` | Python基础库：异步HTTP、代理、CF绕过(cloudscraper/curl_cffi)、DTO模式 | 可直接复用为基础库 |
| **unofficial-api-for-pornhub** | 待下载 | PORNHub 非官方API（Python） | PORNHub爬虫替代API |
| **unofficial-api-for-porntrex** | 待下载 | PornTrex 非官方API（Python） | 欧美新增站点 |
| **unofficial-api-for-xvideos** | 待下载 | XVideos 非官方API（Python） | 欧美新增站点 |
| **unofficial-api-for-porngo** | 待下载 | PORNGO 非官方API（Python） | 欧美新增站点 |
| **Pornhub-Video-Downloader-Plugin-v3** | 待下载 | 浏览器扩展插件，flashvars提取、m3u8解析 | PORNHub下载参考 |

### 4.4 PORNHub 相关项目

| 项目 | 本地路径 | 核心能力 | 复用于 |
|------|---------|---------|--------|
| **rodrigogs/pornhub** | `pornhub-main` | **Node.js PORNHub API库**（推荐/最热/搜索/详情/批量） | PORNHub API参考（TypeScript→Python翻译） |
| **pornhub_archiver** | `pornhub_archiver-main` | Docker化的PORNHub频道存档工具，yt-dlp下载、DB驱动 | PORNHub下载方案参考 |
| **pornSpider** | `pornSpider-main` | Python下载器，cloudscraper绕过CF，搜索/分类浏览 | PORNHub爬虫参考 |
| **PornHubDL** | `PornHubDL-main` | Chrome扩展，flashvars注入 | PORNHub flashvars提取（已部分使用） |
| **phdownloader** | `phdownloader-master` | Python下载器 | PORNHub下载参考 |
| **FapNation** | `FapNation-main` | HTML/JS前端 | 前端UI参考 |

### 4.5 JAVdb / JAVbus 系列API

| 项目 | 本地路径 | 核心能力 | 复用于 |
|------|---------|---------|--------|
| **javdb-cli** | `javdb-cli-main` | **Go语言 JavDB App JSON API客户端**（搜索/详情/磁力/排行/TOP250/收藏） | JAV模块 JavDB 数据源增强 |
| **javdb-python** | `javdb-python-main` | JAVDatabase 搜索+NFO/JSON输出 | JAV模块 NFO 输出参考 |
| **javbus-api** | `javbus-api-main` | TypeScript JavBus REST API | JAV模块 JavBus 数据源增强 |
| **javapi** | `javapi-master` | **Go JAV聚合搜索API**（JavDB元数据+8个视频站嵌入链接） | JAV模块 多源聚合 |
| **dock-javbus** | `dock-javbus-main` | Docker化JavBus | 部署参考 |
| **javspider_stack** | `javspider_stack-main` | FastAPI+SQLAlchemy JavBus管理器，WebSocket实时进度 | 架构参考 |
| **javdb_api** (caojiying002) | 待下载 | JavDB API Python封装 | JAV模块 |
| **javdb-api-scraper** | 待下载 | JavDB API刮削器 | JAV模块 |

### 4.6 MDCX 变体项目

| 项目 | 本地路径 | 核心能力 | 可复用功能 |
|------|---------|---------|-----------|
| **mdcx-diy** | `mdcx-diy-main` | MDCX PyQt6桌面版变体，包含LLM客户端+图片处理+无码番号识别增强 | **无码番号识别**(number.py strip_escape_strings+normalize_uncensored)、LLM客户端设计 |
| **mdcx_sqlite** | `mdcx_sqlite-main` | MDCX SQLite数据库工具 | 数据库管理参考 |
| **mdcx (Kesuy)** | 待检查 | MDCX 另一个Fork | 需检查差异 |

### 4.7 其他辅助项目

| 项目 | 本地路径 | 核心能力 | 复用于 |
|------|---------|---------|--------|
| **mp-relay** | `mp-relay-main` | **磁力→下载→刮削→入库全管道**，集成MDCX+qBittorrent+MoviePilot+Jellyfin，Web UI监听:5000 | 系统工具增强（统一输入/演员发现/封面补填） |
| **OpenAver** | `OpenAver-main` | 桌面GUI JAV管理器，8爬虫+Metatube联盟30+提供商，AI API操作 | JAV刮削架构、女优跨语言别名、封面墙UI |
| **Javdex** | `Javdex-main` | Electron桌面媒体库，插件驱动刮削系统，MCP+Agent支持 | **前端UI架构参考**、插件系统设计 |
| **avbook** | `avbook-master` | PHP Laravel JAV网站 | 部署参考 |
| **JAV-Manager** | `JAV-Manager-main` | JAV管理 | 功能参考 |
| **JATLAS** | `JATLAS-main` | Emby数据库工具(TS) | 数据库工具参考 |
| **jav (hyperq)** | `jav-master` | Rust TUI JAV浏览器 | Rust实现参考 |
| **javm** | `javm-main` | JAV管理 | 功能参考 |
| **Aver-Metatube** | `OpenAver-main`参考 | 30+刮削器联盟 | 刮削架构参考 |

---

## 五、国产去广告命名规范管理器（完整方案）

### 5.1 问题
国产视频文件名含大量广告/平台标记，如 `!DVDEmpire`、`.9Porn.asia`、`PsychoPorn.com`、`CHT!BT`

### 5.2 功能设计

```
国产模块
└── 🛠️ 命名规范管理
    ├── 📋 内置广告词列表（不可编辑，可启用/禁用）
    ├── ➕ 手动添加广告词
    ├── 🔄 一键去广告重命名
    ├── 📁 命名规范模板配置
    └── 📊 自动记录日志（新广告词 -> 用户确认 -> 加入规则）
```

### 5.3 数据模型

```json
{
  "version": 2,
  "builtin_enabled": true,
  "auto_record": true,
  "naming_template": "{code}.{actor}.{title}",
  "ad_rules": {
    "builtin": ["!DVDEmpire", "CHT!BT", "!9Porn", "PsychoPorn.com", ...],
    "user_defined": ["麻豆传媒映画", "天美传媒", ...]
  },
  "auto_recorded": [
    {"pattern": "9Porn.asia", "first_seen": "2026-07-28", "file": "xxx.mp4"}
  ]
}
```

### 5.4 实现文件

| 文件 | 说明 |
|------|------|
| `app/services/chinese_rename_service.py`（新建） | 命名规范管理器核心服务 |
| `app/api/routes/chinese_routes.py`（新增路由） | 命名规范管理API |

---

## 六、PORNHub 对比查重（基于您开发的 PSP）

### 6.1 核心复用

| PSP 文件 | 功能 | 适配方式 |
|----------|------|---------|
| `modules/core/comparator/missing_finder.py` | PORNHub 在线vs本地对比 | 直接适配为 MDCX 服务 |
| `modules/core/local_scanner/title_normalizer.py` | 标题归一化 | 复用 |
| `modules/porn/core/utils/pornhub_url_detector.py` | URL类型识别 | 复用 |
| `modules/core/local_scanner/scanner.py` | 本地视频文件扫描 | 复用扫描逻辑 |

### 6.2 实现文件

| 文件 | 说明 |
|------|------|
| `app/services/pornhub_comparison.py`（新建） | PORNHub对比查重服务 |
| `app/api/routes/pornhub_routes.py`（新增API） | 对比查重API端点 |

---

## 七、欧美模块完整方案

### 7.1 爬虫来源

| 爬虫 | CommunityScrapers文件 | 覆盖品牌 |
|------|---------------------|---------|
| AyloAPI | `scrapers/AyloAPI/scrape.py` (1021行) | Brazzers/BangBros/Mofos/RealityKings/NaughtyAmerica/DigitalPlayground/Twistys 等 40+ |
| AlgoliaAPI | `scrapers/AlgoliaAPI/AlgoliaAPI.py` (961行) | EvilAngel/AdultTime/JulesJordan/TeamSkeet/Gamma/Wicked 等 |
| VixenNetwork GraphQL | `scrapers/vixenNetwork/vixenNetwork.py` (577行) | Vixen/Blacked/BlackedRaw/Tushy/Deeper/Milfy/Wifey/Slayed |
| IAFD | `scrapers/IAFD/IAFD.py` (475行) | 欧美演员数据库（出生日期/三围/种族/纹身等） |
| ThePornDB | 现有 `app/crawlers/md/theporndb.py` | 通用元数据API |

### 7.2 品牌网络体系

```
欧美品牌管理
├── 品牌网络 Aylo (40+)
│   ├── Brazzers
│   ├── BangBros
│   ├── Mofos
│   ├── RealityKings
│   └── ...更多
├── 品牌网络 Algolia (20+)
│   ├── EvilAngel
│   ├── AdultTime
│   ├── JulesJordan
│   ├── TeamSkeet
│   └── ...更多
├── 品牌网络 Vixen (9)
│   ├── Vixen
│   ├── Blacked
│   ├── Tushy
│   └── ...更多
└── 独立品牌管理器
    └── 用户可添加自定义品牌
```

### 7.3 实现文件

| 文件 | 说明 |
|------|------|
| `app/crawlers/western/aylo_api.py`（新建） | Aylo品牌站群API爬虫 |
| `app/crawlers/western/algolia_api.py`（新建） | Algolia品牌站群API爬虫 |
| `app/crawlers/western/vixen_network.py`（新建） | Vixen网络GraphQL爬虫 |
| `app/crawlers/western/iafd.py`（新建） | IAFD演员数据库爬虫 |
| `app/db/western_models.py`（增强） | 新增品牌管理模型 |
| `app/api/routes/western_routes.py`（增强） | 完整的欧美模块API |

---

## 八、实施路线与里程碑

### Phase 1：首页重构 + 导航新设计（目标：3天）
- [ ] 重写 Home.vue — 6 模块仪表板
- [ ] 重写 Layout.vue — 新导航栏设计
- [ ] 更新 router/index.js — 6 模块独立路由
- [ ] 侧边栏：模块名 → 内部子导航

### Phase 2：国产去广告命名规范管理器（目标：2天）
- [ ] 新建 `chinese_rename_service.py`
- [ ] 内置广告词规则库
- [ ] 自动学习+用户确认机制
- [ ] 前端命名规范管理页面

### Phase 3：PORNHub 对比查重（目标：2天）
- [ ] 新建 `pornhub_comparison.py`（基于PSP missing_finder）
- [ ] PSP title_normalizer 适配
- [ ] 前端对比查重页面

### Phase 4：JAV 无码/FC2 功能补齐（目标：2天）
- [ ] API路由规范化
- [ ] 前端页面规范化为统一组件

### Phase 5：JAV 有码增强（目标：2天）
- [ ] 演员别名合并API（参考JavBoss v1.9.0）
- [ ] 番号提取测试工具
- [ ] 片商合并API

### Phase 6：欧美模块完整实现（目标：5天）
- [ ] AyloAPI爬虫适配
- [ ] AlgoliaAPI爬虫适配
- [ ] VixenNetwork爬虫适配
- [ ] IAFD爬虫适配
- [ ] 欧美品牌管理体系
- [ ] 完整前端页面

### Phase 7：功能迁移 + 清理（目标：2天）
- [ ] 系统工具中的本地对比 → 移动到各模块
- [ ] 系统工具中的对比演员 → 移动到各模块
- [ ] 系统工具中的补丁刮削 → 移动到各模块
- [ ] 系统工具中的NFO管理 → 移动到各模块
- [ ] 演员订阅/系列订阅 → 保留在系统层
- [ ] 统一前端组件抽取（ModuleMovies/ModuleMovieDetail/ModuleActors/ModuleActorDetail）

---

## 九、文件变更总清单

### 后端新建文件

| 文件 | 优先级 | Phase | 参考来源 |
|------|--------|-------|---------|
| `app/services/chinese_rename_service.py` | P0 | Phase 2 | 自研 |
| `app/services/pornhub_comparison.py` | P0 | Phase 3 | PSP missing_finder |
| `app/services/pornhub_download.py` | P2 | Phase 5 | Porn_Fetch / rodrigogs pornhub |
| `app/crawlers/western/aylo_api.py` | P0 | Phase 6 | CommunityScrapers AyloAPI |
| `app/crawlers/western/algolia_api.py` | P1 | Phase 6 | CommunityScrapers AlgoliaAPI |
| `app/crawlers/western/vixen_network.py` | P1 | Phase 6 | CommunityScrapers VixenNetwork |
| `app/crawlers/western/iafd.py` | P1 | Phase 6 | CommunityScrapers IAFD |
| `app/crawlers/western/porntrex.py` | P2 | Phase 6 | EchterAlsFake unofficial-api-for-porntrex |
| `app/crawlers/western/xvideos.py` | P2 | Phase 6 | EchterAlsFake unofficial-api-for-xvideos |

### 后端修改文件

| 文件 | 修改内容 | Phase |
|------|---------|-------|
| `app/api/routes/chinese_routes.py` | 新增命名规范管理API | Phase 2 |
| `app/api/routes/pornhub_routes.py` | 新增对比查重API | Phase 3 |
| `app/api/routes/uncensored_routes.py` | API规范化 | Phase 4 |
| `app/api/routes/fc2_routes.py` | API规范化 | Phase 4 |
| `app/db/western_models.py` | 新增品牌管理模型 | Phase 6 |
| `app/api/routes/western_routes.py` | 完整API实现 | Phase 6 |

### 前端新建/修改文件

| 文件 | 说明 | Phase |
|------|------|-------|
| `src/views/Home.vue` | 重写首页 | Phase 1 |
| `src/views/Layout.vue` | 重写布局 | Phase 1 |
| `src/router/index.js` | 6模块路由 | Phase 1 |
| `src/views/chinese/NameRules.vue` | 命名规范管理页 | Phase 2 |
| `src/views/pornhub/Compare.vue` | 对比查重页 | Phase 3 |
| `src/views/western/` | 欧美完整前端 | Phase 6 |
| `src/components/ModuleMovies.vue` | 通用影片列表组件 | Phase 7 |
| `src/components/ModuleMovieDetail.vue` | 通用影片详情组件 | Phase 7 |
| `src/components/ModuleActors.vue` | 通用演员列表组件 | Phase 7 |
| `src/components/ModuleActorDetail.vue` | 通用演员详情组件 | Phase 7 |

---

## 十、技术风险与缓解

| 风险 | 缓解 |
|------|------|
| CommunityScrapers 使用 stashapp 特定py_common类型系统 | 提取核心爬虫逻辑，适配 MDCX 类型系统 |
| 欧美站点反爬升级频繁 | 内置Xray代理 + 多爬虫冗余 |
| 国产广告词模式多样 | 内置规则 + 自动学习 + 用户确认 |
| PORNHub CF保护 | PSP已有curl-cffi impersonate方案 |
| 数据库迁移（演员合并） | 先备份再执行迁移脚本 |

---

*本计划将根据开发过程中的实际情况持续更新。*
