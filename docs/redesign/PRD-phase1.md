# MDCX 界面重构 · Phase 1 PRD（增量）

> 本文只描述**本次变更**。未提及的页面与交互一律保持现状。
> 版本：v1.0 · 类型：增量 PRD · 语言：中文
> 技术栈（不变）：Vue 3 + Vite + Element Plus + Pinia + vue-router（hash history，`base:'./'`）
> 后端：FastAPI，**零改动**，本轮只消费现有接口。

---

## 0. 为什么这轮必须"看得出不一样"

上一轮只做了 **CSS 变量换色**，`AdminLayout.vue` 的深蓝渐变侧栏、`el-menu` 手风琴、`el-footer` 状态栏、`Home.vue` 的 3×3 模块大卡片全部原样保留 → 用户的感受是"配色变了，界面没变"。

本轮改的是**结构**，不是颜色：

| 维度 | 现在 | 本轮之后 |
|---|---|---|
| 一级导航 | 9 个（首员/6 模块/榜单/工具/设置混在一起），`工具与服务` 单组塞 33 项、`系統設置` 单组塞 35 项 | **5 组**：首页 / 媒体库 / 工具中心 / 发现 / 设置 |
| 侧栏视觉 | 深蓝渐变 `#1a1a2e → #16213e`，白色文字 | 浅色（`--sidebar-bg`）+ 1px 右边框，与内容区同基调，靠层级而非颜色分块 |
| 同一功能出现次数 | 刮削 6 次、补全 6 次、对比 5 次、对比演员 2 次（每个模块各挂一份） | 每个功能**菜单中只出现 1 次**，模块用页内「模块切换器」切 |
| 首页 | Hero 渐变条 + 3×3 模块大卡 + 12 个按钮的 `module-actions` | 7 个信息区块，首屏给出「继续观看 / KPI / 快捷操作」，模块矩阵压成 1 行 pill |
| 全局搜索 | `el-dialog` 表单弹窗，必须点开后手输 | `Ctrl/Cmd + K` 命令面板，可搜页面 **和** 番号/演员 |
| 底部状态栏 | 常驻 `el-footer` 24px（服务器/影片/演员/标签/任务/版本/撤销） | **移除**，信息迁到侧栏底部一行 + 顶栏任务胶囊 |
| 顶栏图标 | 7 个平铺图标按钮（搜索/主题/NSFW/更新×2/刷新/退出） | 4 个（搜索/任务/NSFW/主题）+ 用户菜单收纳其余 |

---

## 1. 目标与成功标准

### 产品目标（3 个正交目标，不重叠）

- **G1 减负**：把"每个模块一套工具"的笛卡尔积菜单收敛成"工具做一次、模块做切换"，让导航量级从 130+ 降到 5 组内。
- **G2 可见**：让首页成为"打开就知道该干什么"的工作台，而不是模块入口广告牌。
- **G3 可信**：用统一的外壳、间距、层级、状态反馈，让界面读起来像一款商业 SaaS 产品，而不是内部管理脚本。

### 可验收标准（P0 全中才算本轮通过）

| # | 验收标准 | 判定方式 |
|---|---|---|
| **A1** | 侧栏折叠态可见一级条目 **≤ 5**，全部展开（含媒体库 7 模块）后侧栏总高 ≤ 100vh，**不出现滚动条**（1920×1080 与 1440×900 两档） | 截图对比 + `document.querySelector('.sidebar-menu').scrollHeight <= clientHeight` |
| **A2** | 同一功能在菜单中**只出现 1 次**：全站搜索"刮削"，侧栏/命令面板命中项 ≤ 1 个一级入口 + 1 个工具卡片 | 人工遍历菜单 |
| **A3** | 「继续观看」「4 个 KPI」「6 个快捷操作」在 **1440×900 首屏（不滚动）内全部可见** | 截图 + `window.innerHeight` 断言 |
| **A4** | 亮色模式下，页面内**非中性彩色块 ≤ 3 处**（主按钮、选中态、KPI 数字强调），其余全部走中性灰阶；不再出现深蓝渐变侧栏与 `linear-gradient` Hero | 视觉走查 |
| **A5** | 从任意页面到达任意工具 **≤ 3 次点击**：`Ctrl+K` → 输工具名 → 回车 = 2 步 | 手动计时/点算 |
| **A6** | **0 个旧链接失效**：所有现有路由 path 与 name 原样可访问（见 §4.3 规则 R2） | 遍历 `/src/router/routes.web.js` 现存 100+ path，逐一 `router.resolve` 成功 |
| **A7** | 1280 / 1440 / 1920 三档宽度下，首页与工具中心**无横向滚动**，卡片左边缘对齐同一条网格线（`24px` 倍数） | 三档截图叠加 |

### 明确不做（本轮）

- 媒体库各页（`jav/Movies.vue`、`Actors.vue`、`MovieDetail.vue` 等 40+ 页）的**内部**视觉重做 → 下一阶段。
- 桌面端外壳 `src/views/Layout.vue` 不改结构 → 下一阶段直接复用本轮抽出的 `AppSidebar/AppTopbar`。
- 任何后端接口新增。本轮全部复用现有接口；缺失数据用「空状态 + 引导」处理，不造 mock。

---

## 2. 用户故事

### 首页（仪表盘）

- **US-H1** 作为每天打开系统的管理员，我希望**一进来就看见上次看到一半的片子**，直接点继续，而不是先选模块再翻影片库找进度。
  - 验收：首屏「继续观看」横向卡片 ≥ 3 张时优先于其他区块渲染（骨架屏先出），点击直接进 `/play/:id`。
- **US-H2** 作为要判断"库是否健康"的管理员，我希望首页一眼看到影片/演员/标签总量与最近 24h 新增，以及服务器/存储状态，不用点进 `/stats`。
- **US-H3** 作为刚做完一批刮削的用户，我希望首页能看见最近 8 条任务结果和我积压的"刮削复核"待办数，并且一点就跳过去处理。

### 导航

- **US-N1** 作为被 30+ 个菜单项淹没的用户，我希望侧栏只有 5 个组，展开任一组不超过 10 项，且能记住我上次展开的是哪一组。
- **US-N2** 作为知道自己要找什么的高级用户，我希望 `Ctrl+K` 输入"补丁"能直接跳到补全工具并预选好当前模块，不必先想它挂在哪个模块下。
- **US-N3** 作为需要跨模块对比的用户，我希望在工具页顶部用**一个模块切换器**在 JAV有码/无码/FC2/国产/PORNHub/欧美 之间切换，而不是回侧栏找另一个模块的同一个工具。

### 工具中心

- **US-T1** 作为用户，我希望进「工具中心」看到 6 张分组卡片（刮削与源 / 补全与对比 / 整理与入库 / 去重与健康 / 下载与网盘 / 系统与代理），每张写明组内工具数与最近一次运行时间，一眼知道该进哪个。
- **US-T2** 作为用户，我希望在一个分组页里用左侧工具列表 + 右侧内容区，切工具不跳页、不丢上下文（保持当前模块、当前筛选）。
- **US-T3** 作为用户，我希望原 `/jav/scrape` 这类旧书签仍然能打开，而不是 404。

---

## 3. 需求池

### P0（Must have · 本轮必须交付）

| ID | 需求 | 影响文件 |
|---|---|---|
| P0-1 | 新增 IA 单一配置源 `src/config/nav.js`：5 组、组内项、图标、`enabled` 依赖模块开关、`order`。侧栏、命令面板、面包屑、工具中心卡片**全部**从它派生 | 新建 `src/config/nav.js` |
| P0-2 | 侧栏重写：浅色底、5 组可折叠（`localStorage` 记忆）、折叠态 64px 只显图标、底部一行状态 | 新建 `src/layouts/AppSidebar.vue`，`AdminLayout.vue` 改为引用 |
| P0-3 | 顶栏重写：64px，面包屑 + `Ctrl+K` 搜索入口 + 任务胶囊 + NSFW + 主题 + 用户菜单；删除刷新/退出/更新独立按钮 | 新建 `src/layouts/AppTopbar.vue` |
| P0-4 | 移除 `el-footer` 状态栏，信息迁至侧栏底部（服务器点 + 影片数）与顶栏任务胶囊 | `AdminLayout.vue` |
| P0-5 | 命令面板 `CommandPalette.vue`：`Ctrl/Cmd+K` 唤起；结果 = 页面（来自 `nav.js`）+ 内容（复用 `unifiedSearch`）；↑↓ 选择、回车跳转 | 新建 `src/components/shell/CommandPalette.vue` |
| P0-6 | 首页仪表盘重写为 7 区块（见 §6） | 重写 `src/views/Home.vue`，新建 `src/components/dashboard/*` |
| P0-7 | 工具中心 Hub + 6 个分组页（见 §7），页内「工具切换器 + 模块切换器」 | 新建 `src/views/tools/*`（7 文件） |
| P0-8 | `/uncensored` 当前 redirect 到 `UncensoredScrape`（进无码模块先看到刮削页），改为 redirect 到 `/uncensored/movies` | `routes.web.js:573-576` |
| P0-9 | 设计 token 补齐（见 §8）：侧栏/顶栏/内容宽/卡片圆角/hover 层/焦点环/动效曲线 | 新建 `src/styles/tokens.redesign.css`，`main.js` 引入 |
| P0-10 | 旧路由 100% 保留可访问，仅从菜单移除（规则 R2） | `routes.web.js`（只增不删） |

### P1（Should have · 本轮尽量，可延一版）

| ID | 需求 |
|---|---|
| P1-1 | 6 条 `*/scrape`、6 条 `*/patch`、5 条 `*/compare`、2 条 `*/compare-actors` 改为 `redirect` 到 `/tools/*?module=x`；需先给 3 处 module 解析加 `route.query.module` 兜底（`Crawlers.vue:217`、`Patch.vue:276`、`CompareActors.vue:449`） |
| P1-2 | 媒体库模块内页 Tab（`ModuleTabs.vue`：影片 / 浏览 / 演员 / 系列 / 类别 / 制片厂），替代侧栏二级 |
| P1-3 | KPI 卡显示 7 日增量（需 `GET /stats/movies?range=7d` 是否已支持待确认，见 §9-Q2） |
| P1-4 | 命令面板记录最近 5 条访问，空关键词时展示 |
| P1-5 | 工具卡片显示"最近运行时间/上次结果"，数据来自 `getTasks` 本地匹配（不新增接口） |
| P1-6 | 桌面端 `Layout.vue` 复用 `AppSidebar/AppTopbar` |

### P2（Nice to have）

| ID | 需求 |
|---|---|
| P2-1 | 侧栏宽度拖拽（200–280px）并持久化 |
| P2-2 | 首页区块可拖拽排序 / 可隐藏，存 `localStorage` |
| P2-3 | 顶栏「快捷创建 `+`」下拉（导入 / 扫描模块 / 新建播放列表） |
| P2-4 | 深色模式下的"影院风"开关（保留现有 `--bg-0/-1/-2` 蓝黑体系） |

---

## 4. 信息架构（IA）

### 4.1 站点地图

```
MDCX
├── 首页 /                                    ← 仪表盘（重写）
│
├── 媒体库                                     ← 只做"看与管理内容"，不放工具
│   ├── JAV 有码        /jav/movies            （+ 页内 Tab：浏览/演员/系列/类别/制片厂）
│   ├── JAV 无码        /uncensored/movies
│   ├── FC2             /fc2/movies
│   ├── 国产            /chinese/movies
│   ├── PORNHub         /pornhub/movies
│   ├── 欧美            /western/movies
│   ├── 里番            /anime
│   ├── 收藏夹          /favorites
│   ├── 封面墙          /cover-wall
│   ├── 播放列表        /playlists
│   ├── 观影队列        /queues
│   └── 女优收藏        /actress-collection
│
├── 工具中心 /tools                            ← Hub（新增）
│   ├── 刮削与源        /tools/scrape
│   ├── 补全与对比      /tools/fix
│   ├── 整理与入库      /tools/organize
│   ├── 去重与健康      /tools/health
│   ├── 下载与网盘      /tools/download
│   └── 系统与代理      /tools/system
│
├── 发现                                       ← 消费型/洞察型，只读为主
│   ├── 榜单 TOP250     /jav/top250            （path 不变）
│   ├── 智能推荐        /recommendations       （path 不变）
│   ├── 统计总览        /stats
│   ├── 观影报告        /viewing-report
│   ├── 口味画像        /taste
│   ├── 影片图谱        /movie-graph
│   └── 沉浸浏览        /immerse
│
└── 设置                                       ← 配置型，低频
    ├── 系统设置 / 扫描控制 / 模块管理 / 主题外观
    ├── 用户与权限 / 插件与集成 / Cookie 与站点
    ├── 代理与网络 / Emby / TVBox / STRM / mpv
    └── 日志 / 备份 / 部署档位 / Schema / 桌面设置
```

**分组判定法则**（架构师遇到新页面按此归位，不再靠感觉）：

| 组 | 判据 |
|---|---|
| 媒体库 | 页面的主语是"一部片/一个演员/一个列表" |
| 工具中心 | 页面的主语是"一次批量动作"（扫描、刮、补、比、去重、导、下） |
| 发现 | 页面只读、只出结论（榜单、画像、报告、图谱） |
| 设置 | 页面改变系统行为且低频（开关、密钥、路径、外观） |

### 4.2 新旧路径映射表

**规则（架构师必须遵守）**

- **R1 新增**：所有新入口只使用 `/tools/*` 与 `/discover/*` 之外的**现有 path**（发现组不新建 path）；`/tools`、`/tools/scrape`、`/tools/fix`、`/tools/organize`、`/tools/health`、`/tools/download`、`/tools/system` 为 8 条新增 path。
- **R2 保留（P0）**：`routes.web.js` 中现有 **每一条** path 与 name **一行都不删、不改**，只从侧栏菜单移除。目的：0 个 404、0 个失效书签、组件被两处挂载不增加维护成本。
- **R3 收敛（P1）**：仅对下表"R3"行做 `redirect`，且必须先完成 3 处 module 兜底改造。

| 旧路径 | 旧 name | 现状 | 新归属 | 处理 |
|---|---|---|---|---|
| `/` | Home | 首页 | 首页 | 组件重写，path 不变 |
| `/crawlers` | Crawlers | 独立刮削汇总 | 工具中心 › 刮削与源 | R2 保留（菜单移除） |
| `/jav/scrape` | JavScrape | Crawlers 第 1 份 | 同上 | R2；R3 `→ /tools/scrape?module=jav` |
| `/uncensored/scrape` | UncensoredScrape | Crawlers 第 2 份 | 同上 | R2；R3 `?module=uncensored` |
| `/fc2/scrape` | Fc2Scrape | Crawlers 第 3 份 | 同上 | R2；R3 |
| `/chinese/scrape` | ChineseScrape | Crawlers 第 4 份 | 同上 | R2；R3 |
| `/pornhub/scrape` | PornhubScrape | Crawlers 第 5 份 | 同上 | R2；R3 |
| `/western/scrape` | WesternScrape | Crawlers 第 6 份 | 同上 | R2；R3 |
| `/patch` | Patch | 独立补全 | 工具中心 › 补全与对比 | R2 保留 |
| `/jav/patch` `/uncensored/patch` `/fc2/patch` `/chinese/patch` `/pornhub/patch` `/western/patch` | *Patch | Patch 6 份 | 同上 | R2；R3 `→ /tools/fix?tool=patch&module=x` |
| `/compare` | Compare | 独立对比 | 同上 | R2 保留 |
| `/jav/compare` `/uncensored/compare` `/fc2/compare` `/pornhub/compare` `/western/compare` | *Compare | Compare 5 份 | 同上 | R2；R3 `?tool=compare` |
| `/compare-actors` `/jav/compare-actors` `/uncensored/compare-actors` | *CompareActors | 3 份 | 同上 | R2；R3 `?tool=compare-actors` |
| `/nfo-scrape` `/source-merge` `/jav/gap-fill` `/review` | — | 补全类散点 | 补全与对比 | R2 保留 |
| `/import` `/file-organize` `/auto-organize` `/unrecognized-files` `/refresh-folders` `/jav/folder-check` `/naming-template` `/chinese/name-rules` `/scan-control` `/tiers` | — | 入库类散点 | 整理与入库 | R2 保留 |
| `/duplicates` `/fingerprint` `/media-health` `/junk-files` `/view-status` `/face-crop` `/poster-enhance` | — | 健康类散点 | 去重与健康 | R2 保留 |
| `/downloaders` `/download` `/pan-115` `/cloud-drive2` `/webdav-import` `/strm` `/quality-goals` `/wants` | — | 下载类散点 | 下载与网盘 | R2 保留 |
| `/network-diag` `/proxy-xray` `/proxy/jp` `/system-status` `/tasks` `/workflows` `/logs` `/log-stream` `/webhooks` `/backup` | — | 系统类散点 | 系统与代理 | R2 保留 |
| `/site-priority` `/sites` `/cookie-manager` `/cookiecloud` `/gfriends` `/metatube-plugin` | — | 源与凭据 | 刮削与源 / 设置 | R2 保留 |
| `/avatars`… 无 | — | — | — | — |
| `/jav/top250` | JavTop250 | 榜单 | 发现 | path **刻意不变**（防旧链 404） |
| `/recommendations` `/stats` `/viewing-report` `/taste` `/movie-graph` `/immerse` | — | 洞察类 | 发现 | R2 保留 |
| `/queues` | Queues | 观影队列 | 媒体库（跨模块） | R2 保留 |
| `/actress-collection` `/favorites` `/cover-wall` `/playlists` `/tags` `/studios` | — | 跨模块内容 | 媒体库 | R2 保留 |
| `/settings` `/modules` `/themes` `/users` `/plugins` `/tvbox` `/emby-config` `/mpv-settings` `/desktop-settings` `/schema-settings` `/deploy` `/read-only` `/telegram-bot` | — | 配置 | 设置 | R2 保留 |
| `/jav` `/fc2` `/chinese` `/pornhub` `/western` | * | 模块落地页→ Movies | 媒体库 | 保留 |
| `/uncensored` | — | **redirect 到 UncensoredScrape（异常）** | 媒体库 › 无码影片库 | **P0-8 改为 redirect `/uncensored/movies`** |
| `/jav/play` | JavPlay | 指向 `MpvSettings.vue` | 设置 › mpv | 保留 R2 |
| `/play/:id` `/movie/:id` `/jav/movies/:id` 等 7 条详情 | — | 详情 | 媒体库 | 保留，**不加入菜单** |

**新增路由清单（8 条，全部挂在 `AdminLayout` 下）**

```js
{ path: 'tools',            name: 'ToolsHub',       component: () => import('@/views/tools/ToolsHub.vue') },
{ path: 'tools/scrape',     name: 'ToolsScrape',    component: () => import('@/views/tools/ToolsScrape.vue') },
{ path: 'tools/fix',        name: 'ToolsFix',       component: () => import('@/views/tools/ToolsFix.vue') },
{ path: 'tools/organize',   name: 'ToolsOrganize',  component: () => import('@/views/tools/ToolsOrganize.vue') },
{ path: 'tools/health',     name: 'ToolsHealth',    component: () => import('@/views/tools/ToolsHealth.vue') },
{ path: 'tools/download',   name: 'ToolsDownload',  component: () => import('@/views/tools/ToolsDownload.vue') },
{ path: 'tools/system',     name: 'ToolsSystem',    component: () => import('@/views/tools/ToolsSystem.vue') },
```

> 全部新增 name 以 `Tools` 开头，避免与现有 100+ name 冲突。新增前先跑 `node -e "…"` 或人工核验 name 唯一性。

### 4.3 `src/config/nav.js` 数据结构（架构师照抄）

```js
export const NAV = [
  { key: 'home', label: '首页', icon: 'HomeFilled', to: '/' },
  {
    key: 'library', label: '媒体库', icon: 'VideoCamera', defaultOpen: false,
    children: [
      { key: 'jav',        label: 'JAV 有码', emoji: '🎬', to: '/jav/movies',        countKey: 'jav.movies',        moduleFlag: 'jav' },
      { key: 'uncensored', label: 'JAV 无码', emoji: '🔓', to: '/uncensored/movies', countKey: 'uncensored.movies', moduleFlag: 'uncensored' },
      { key: 'fc2',        label: 'FC2',      emoji: '📹', to: '/fc2/movies',        countKey: 'fc2.movies',        moduleFlag: 'fc2' },
      { key: 'chinese',    label: '国产',      emoji: '🇨🇳', to: '/chinese/movies',    countKey: 'chinese.movies',    moduleFlag: 'chinese' },
      { key: 'pornhub',    label: 'PORNHub',  emoji: '🌐', to: '/pornhub/movies',    countKey: 'pornhub.movies',    moduleFlag: 'pornhub' },
      { key: 'western',    label: '欧美',      emoji: '🌍', to: '/western/movies',    countKey: 'western.movies',    moduleFlag: 'western' },
      { key: 'anime',      label: '里番',      emoji: '📺', to: '/anime',             countKey: 'anime.movies',      moduleFlag: 'anime' },
      { divider: true },
      { key: 'favorites',  label: '收藏夹', icon: 'Star',      to: '/favorites' },
      { key: 'coverwall',  label: '封面墙', icon: 'Grid',      to: '/cover-wall' },
      { key: 'playlists',  label: '播放列表', icon: 'VideoPlay', to: '/playlists' },
      { key: 'queues',     label: '观影队列', icon: 'List',      to: '/queues' },
      { key: 'actress',    label: '女优收藏', icon: 'Avatar',    to: '/actress-collection' },
    ],
  },
  {
    key: 'tools', label: '工具中心', icon: 'Tools', to: '/tools', defaultOpen: false,
    children: [
      { key: 'scrape',   label: '刮削与源',   icon: 'Connection',    to: '/tools/scrape',   desc: '刮削、站点优先级、Cookie、刮削复核' },
      { key: 'fix',      label: '补全与对比', icon: 'MagicStick',    to: '/tools/fix',      desc: '补丁、本地对比、NFO、多来源精选' },
      { key: 'organize', label: '整理与入库', icon: 'FolderOpened',  to: '/tools/organize', desc: '导入、整理、未识别、命名、扫描' },
      { key: 'health',   label: '去重与健康', icon: 'FirstAidKit',   to: '/tools/health',   desc: '重复番号、指纹、媒体健康、垃圾文件' },
      { key: 'download', label: '下载与网盘', icon: 'Download',      to: '/tools/download', desc: '下载器、115、CloudDrive2、WebDAV、STRM' },
      { key: 'system',   label: '系统与代理', icon: 'Monitor',       to: '/tools/system',   desc: '网络诊断、Xray、任务、日志、备份' },
    ],
  },
  { key: 'discover', label: '发现', icon: 'DataAnalysis', defaultOpen: false, children: [ /* top250 / recommendations / stats / viewing-report / taste / movie-graph / immerse */ ] },
  { key: 'settings', label: '设置', icon: 'Setting',      defaultOpen: false, children: [ /* §4.1 设置组 */ ] },
]
```

`moduleFlag` 为真的项在 `getModulesConfig()` 返回 `enabled=false` 时**整项隐藏**（沿用现有 `moduleEnabled` 逻辑，不新增接口）。

---

## 5. 外壳规格

### 5.1 结构

```
┌───────────────────────────────────────────────────────────────┐
│ AppTopbar  64px                                               │
├──────────┬────────────────────────────────────────────────────┤
│ AppSidebar│  <router-view />                                   │
│ 240 / 64 │  content: max-width 1440px, padding 24px           │
│          │                                                    │
├──────────┴────────────────────────────────────────────────────┤
（无 status bar）
```

- 根容器：`height: calc(100vh - var(--titlebar-h, 0px))`（沿用，Electron 标题栏兼容）。
- **移除** `AdminLayout.vue:750-790` 的 `el-footer.status-bar`；`loadHealthAndStats()` 保留（数据给侧栏底部与顶栏胶囊用），30s 轮询不变。
- 外壳拆成 `AppSidebar.vue` + `AppTopbar.vue`，`AdminLayout.vue` 只保留 `<AppSidebar/> <el-container><AppTopbar/><el-main/></el-container>` + 现有全部对话框（更新/更新日志/头像刮削浮层/全局搜索→改为命令面板）。**Electron 事件监听、NSFW 逻辑、主题、auth、undo、avatarStore 全部原样搬移，不改逻辑。**

### 5.2 侧栏 `AppSidebar.vue`

| 项 | 规格 |
|---|---|
| 宽度 | 展开 `240px`（`--sidebar-w`），折叠 `64px`（`--sidebar-w-collapsed`），`transition: width 220ms var(--ease-out)` |
| 底色 | 亮：`--sidebar-bg: #FBFBFC`；暗：`#0F1115`。右边框 `1px solid var(--border-color)`。**不使用渐变** |
| Logo 区 | 高 56px，32×32 圆角 8px 的 `--accent` 方块 + 「MDCX」16px/600 + 副标题 11px `--text-secondary`；折叠态只留图标 |
| 一级项 | 高 36px，圆角 `--radius-md`(8px)，左内边距 12px，图标 16px + 文字 14px/500；`margin: 2px 8px` |
| 折叠/展开 | 一级组点击标题区域切换，箭头 180° 旋转；状态存 `localStorage['mdcx_nav_open']`（JSON 数组 of key）。**默认全部关闭**（保证首屏 5 行） |
| 二级项 | 高 32px，左缩进 32px（折叠态下以 hover 弹出气泡呈现二级，避免 64px 挤爆） |
| 计数徽标 | 媒体库 7 项右侧显示影片数（12px，`--text-secondary`，`tabular-nums`），数据来自 `getDashboardStats().modules[key].movies`（沿用 `Home.vue:194-204` 的取数逻辑） |
| 选中态 | 背景 `color-mix(in srgb, var(--accent) 10%, transparent)`，文字 `--accent`，字重 600，**左侧 2px 竖条**（`::before`，圆角 2px）。不再用 `inset 3px 0 0` 满高阴影 |
| hover | 背景 `var(--hover-layer)`（亮 `rgba(15,18,26,.04)` / 暗 `rgba(255,255,255,.06)`），`transition 120ms` |
| 分组标题 | 11px / 600 / `letter-spacing: .06em` / `--text-secondary` / 大写化（中文不加 letter-spacing，改为 12px/500） |
| 底部 | 一行 12px：`● 服务器正常 · 1,234 影片 · v{{version}}`，`●` 为 6px 状态点（ok `--success` / warn `--warning` / error `--danger`），点击打开更新日志 |
| 滚动 | `.sidebar-menu { overflow-y: auto; }`，滚动条 6px 半透明；**P0 验收要求 1080p 下不出现** |
| 无障碍 | 保留 `role="navigation" aria-label="主导航"`、`aria-expanded`、`skip-link` |

**媒体库组内不出现工具项**（刮削/补全/对比全部进工具中心），这是本次"减负"的核心。

### 5.3 顶栏 `AppTopbar.vue`

高 `64px`，`background: var(--bg-card)`，`border-bottom: 1px solid var(--border-color)`，**无 box-shadow**（SaaS 风靠边框不靠阴影）。

| 区域 | 内容 | 规格 |
|---|---|---|
| 左 1 | 折叠按钮 | 32×32 icon button，`aria-label` 保留 |
| 左 2 | 面包屑 | `首页 / 媒体库 / JAV 有码`，来源 = `nav.js` + 当前 path 最长匹配；最后一级 14px/600 `--text-primary`，其余 14px/400 `--text-secondary`，分隔符 `/` 用 `--text-placeholder`。**不再用 `pageTitle` 硬编码字典（`AdminLayout.vue:1424-1544` 的 120 行 switch 表）** |
| 左 3（可选） | 模块上下文 pill | 当前处于某模块时显示 `🎬 JAV 有码` 小 pill，点击弹模块切换菜单 |
| 中 | 搜索 | 宽 `min(420px, 32vw)`、高 34px，圆角 8px，背景 `var(--bg-page)`，占位「搜索番号、演员、页面…」，右侧 `⌘K` 徽标（12px）。点击或 `Ctrl/Cmd+K` 打开命令面板 |
| 右 | 任务胶囊 | 有 running 任务时显示 `⟳ 任务 3/8` + 32px 宽度内嵌进度条，点击进 `/tasks`；无任务时隐藏 |
| 右 | NSFW | 保留现有 popover 全功能（6 个开关 + 滑杆），图标按钮，开启时右上角 6px 红点 |
| 右 | 主题 | Sun/Moon 切换，保留 `themeStore.toggleDark()` |
| 右 | 用户菜单 | 头像 28px + 用户名（≥1280px 才显示用户名）。`el-dropdown` 项：更新日志 / 检查更新（仅 Electron）/ 刷新页面 / 退出登录。**删除顶栏原有的"刷新""退出""更新""安装"4 个独立图标按钮** |
| — | 移除 | `el-divider` 竖线、`update-badge` 独立徽标（合并进用户菜单红点） |

### 5.4 命令面板 `CommandPalette.vue`（P0）

- 触发：`Ctrl/Cmd + K` 全局监听（`AdminLayout` 挂一次 `keydown`，`e.preventDefault()`）；顶栏搜索框点击；`/` 键（输入框外时）。
- 形态：居中浮层，宽 `560px`，`max-height: 60vh`，圆角 `--radius-lg`，`--shadow-xl`，背景 `--bg-card`，遮罩 `rgba(15,18,26,.45)` + `backdrop-filter: blur(2px)`。
- 结果分两组：
  1. **页面**（最多 6 条）：从 `nav.js` 扁平化后按 label 模糊匹配，命中显示 `组 / 页名` + `↵`。
  2. **内容**（最多 8 条）：沿用 `unifiedSearch(keyword)`（≥2 字才请求，350ms 防抖），命中显示模块 tag + 标题 + 番号，跳转规则沿用 `AdminLayout.vue:1007-1010` 的 `/{module}/movies/{id}`。
- 交互：↑↓ 移动（`aria-activedescendant`）、Enter 执行、Esc 关闭、结果项 hover 背景 `--hover-layer`、选中项左侧 2px `--accent` 竖条。
- 状态：无关键词 → 显示「最近访问 5 条」+「常用工具 6 条」（工具中心 6 组）；无结果 → `EmptyState type="no-results"`；请求失败 → 静默失败，只显示页面组。
- 可访问性：`role="dialog" aria-modal="true"`，焦点锁在输入框，关闭后焦点回到触发元素。

---

## 6. 首页仪表盘规格（`src/views/Home.vue` 重写）

**布局**：CSS Grid 12 列，`gap: 16px`，内容区 `max-width: 1440px`。区块顺序即 DOM 顺序（可访问性 + 首屏优先级）。

| 序 | 区块 | 栅格 | 数据来源（**全部现有接口**） | 空态 | 加载态 | 错误态 |
|---|---|---|---|---|---|---|
| 1 | **Hero 欢迎区** `dashboard/HeroBanner.vue` | 12 | `authStore.username`（已存在）；`getSystemHealth()` | — | 静态文字先渲染，状态点用 8px 灰点 | 状态点变 `--danger` + 「未连接」 |
| 2 | **继续观看** `dashboard/ContinueWatching.vue` | 12 | `getMovies({page:1,page_size:6,sort:'-last_played_at'})`（沿用 `Home.vue:225`）；或 `getViewingResume()`（`api/index.js:119`，二选一，优先后者） | 隐藏整块（不占位） | 6 个 140×210 骨架卡 | 隐藏整块，不报错 |
| 3 | **库概览 KPI** `dashboard/KpiRow.vue` | 12 → 4×3 | `getDashboardStats()` → 影片/演员/标签/系列总数；7 日增量见 §9-Q2 | 数字显示 `0` + 「去导入」链接 | 4 个 88px 高骨架块 | 数字显示 `—`，卡片加 12px 「加载失败」灰字 |
| 4 | **模块矩阵** `dashboard/ModulePills.vue` | 12（一行） | `getDashboardStats().modules[key]`（复用 `Home.vue:194-204`）+ `getCrawlers()` 取爬虫数 | 库为 0 的模块显示 `等待数据` 灰字 | 7 个 44px 高骨架 pill | 只显示模块名，不显示数字 |
| 5 | **快捷操作** `dashboard/QuickActions.vue` | 7 → 6+6 | 纯静态配置（`nav.js` 中 tools 组 6 项 + 常用 6 项：导入/扫描/刮削复核/网络诊断/任务/统计） | — | 无（静态） | — |
| 6 | **最近活动** `dashboard/RecentActivity.vue` | 5 | `getTasks({page:1,page_size:8})`；右侧待办数来自 `getQueueStats()` 与 `/review` 列表条数（P1） | `EmptyState type="no-data"` 高 160px，文案「还没有任务，试试批量导入」+ 按钮 | 4 行 × 40px 骨架行 | 区块内 error 文案 + 「重试」文字按钮 |
| 7 | **推荐** `dashboard/RecommendStrip.vue` | 5 | `getRecommendations(12)`（`api/index.js:1069`） | 隐藏整块 | 6 张骨架卡 | 隐藏整块 |
| 8 | **系统状态** `dashboard/SystemStatusCard.vue` | 2（与 7 同排右侧）或并入 6 | `getSystemHealth()` + `getStorageStats()`（`api/index.js:570/569`） | 显示「未连接」+ 「去设置」 | 3 行骨架 | 显示 `—` + 重试 |

> 区块 6/7/8 同处第二屏。首屏（1440×900，`innerHeight ≈ 900 - 64 topbar = 836`）可见：Hero（约 120）+ 继续观看（约 300）+ KPI（约 120）+ ModulePills（约 60）= 600px，**满足 A3**。

**Hero 区规格（必须去掉渐变）**

```
┌───────────────────────────────────────────────────────────┐
│  晚上好，龙魂管理员                        ● 服务器正常    │
│  库内 1,284 部影片 · 312 位演员 · 上次同步 2 小时前        │
│                                                           │
│  [ + 导入文件 ]  [ 扫描目录 ]  [ 全局搜索 ⌘K ]            │
└───────────────────────────────────────────────────────────┘
```
- 无卡片背景、无边框、无渐变，直接坐在 `--bg-page` 上，靠 24px 留白与上下区块分开。
- 主标题 30px/600（`--font-size-4xl`）/ `letter-spacing: -0.02em`；副行 14px/400 `--text-secondary`。
- 按钮组：1 个 `type="primary"`（沿用 `--accent`）+ 2 个 `plain`（边框 1px `--border-color`，透明底）。
- 时段问候：6–12 上午好 / 12–18 下午好 / 18–24 晚上好 / 0–6 夜深了。

**KPI 卡规格**（`dashboard/KpiRow.vue`）

```
┌──────────────────────┐
│ 影片总数        ↗    │   ← 标签 13px/500 --text-secondary
│ 1,284                │   ← 30px/600 tabular-nums letter-spacing -.02em
│ 近 7 日 +36          │   ← 12px，正 --success / 负 --danger / 0 --text-placeholder
└──────────────────────┘
```
卡片：`background: var(--bg-card)`、`border: 1px solid var(--border-color)`、`border-radius: 10px`、`padding: 16px`、**无阴影**；hover 时边框变 `color-mix(accent 30%, border-color)`，不用位移、不用阴影。

**明确删除的旧结构**

- 删除 `Home.vue:28-62` 的 `.module-grid` 3×3 大卡片（信息已由侧栏计数 + ModulePills 承载，重复）。
- 删除每张模块卡里的 5 个 `el-button text`（`module-actions`）—— 共 30+ 个按钮，是"模块塞太满"的直接来源。
- 删除 `hero-card` 的 `linear-gradient(135deg,#1a1a2e,…)` 深蓝条形卡。

---

## 7. 工具中心规格

### 7.1 Hub `src/views/tools/ToolsHub.vue`

- 页面骨架统一用现有 `components/base/PageShell.vue`（`title="工具中心"`, `description="按动作分组，模块在页内切换"`）。
- 6 张大卡，`grid-template-columns: repeat(auto-fill, minmax(280px,1fr))`，`gap: 16px`。
- 卡片内容：图标 20px（`--accent`，仅图标着色）+ 组名 15px/600 + 一句话说明 13px `--text-secondary` + 底部 `4 个工具` / `最近运行 2 小时前`（12px）+ 右上角 `→`。
- 卡片交互：hover 边框加深 + `→` 右移 2px（`transform: translateX(2px)`, 150ms）；整卡可点。
- 6 张卡由 `nav.js` 的 `tools.children` 直接渲染（单一数据源）。

### 7.2 分组页通用布局（`ToolPageShell.vue`）

```
┌────────────────────────────────────────────────────────────────┐
│ 补全与对比                            当前模块 [JAV 有码 ▾]     │  ← 页头，右侧模块切换器
├──────────────────┬─────────────────────────────────────────────┤
│ 工具列表          │  工具内容（动态组件）                        │
│ ● 补丁刮削        │                                             │
│   本地对比        │  <component :is="activeTool.component"       │
│   对比演员        │             :module="currentModule" />       │
│   NFO 免改名刮削  │                                             │
│   多来源数据精选  │                                             │
│   缺口体检        │                                             │
└──────────────────┴─────────────────────────────────────────────┘
  宽 200px，左侧固定      flex:1，min-width:0
```

- **左栏（工具切换器）**：200px，`border-right: 1px solid var(--border-color)`；项高 36px，选中态同侧栏规则（`--accent` 10% 底 + 2px 竖条）；切换只改 `?tool=` query，**不整页跳转**（`router.replace`），保留滚动与筛选。
- **右上「模块切换器」**：`el-select`（宽 160px，高 32px），选项来自 `nav.js` 中 `moduleFlag` 为真且 `enabled` 的模块；切换写 `?module=`，并**持久化到 `localStorage['mdcx_tool_module']`**，下次进任意工具组沿用。
- **URL 即状态**：`/tools/fix?tool=patch&module=jav`。刷新、分享、书签均可复原。
- **模块不适用时**：该工具若没有当前模块的实现（如「缺口体检」仅 JAV 有码），模块切换器仍显示但工具卡片内显示 `EmptyState`「该工具仅适用于 JAV 有码」+「切换到 JAV 有码」按钮。
- 页面级懒加载：`defineAsyncComponent` + `Suspense` 兜底骨架，切工具不白屏。

### 7.3 六组工具清单（含复用来源，架构师按此建组件）

> 「复用」列 = **直接 `import` 现有 `.vue`，不复制、不改内部实现**。本轮只改外层容器。

#### 组 1 刮削与源 `/tools/scrape`

| 工具 | 复用组件 | 现路由 | 是否吃 `module` |
|---|---|---|---|
| 刮削管理 | `@/views/Crawlers.vue` | `/jav/scrape` 等 6 条 | **是**（已支持 6 模块，`Crawlers.vue:216-220` 靠 path 判定，需加 query 兜底） |
| 站点优先级 | `@/views/SitePriority.vue` | `/site-priority` | 否 |
| 站点注册表 | `@/views/sites/SiteRegistry.vue` | `/sites` | 否 |
| Cookie 管理器 | `@/views/CookieManager.vue` | `/cookie-manager` | 否 |
| CookieCloud 同步 | `@/views/CookieCloud.vue` | `/cookiecloud` | 否 |
| 刮削复核 | `@/views/Review.vue` | `/review` | 否 |
| 头像库（Gfriends） | `@/views/Gfriends.vue` | `/gfriends` | 否 |

#### 组 2 补全与对比 `/tools/fix`

| 工具 | 复用组件 | 现路由 | module |
|---|---|---|---|
| 补丁刮削 | `@/views/Patch.vue` | `/patch`、`*/patch` ×6 | **是** |
| 本地对比 | `@/views/Compare.vue` | `/compare`、`*/compare` ×5 | 否（组件内自带选择器） |
| 对比演员 | `@/views/CompareActors.vue` | `/compare-actors`、×2 | **是** |
| NFO 免改名刮削 | `@/views/NfoScrape.vue` | `/nfo-scrape` | 否 |
| 多来源数据精选 | `@/views/SourceMerge.vue` | `/source-merge` | 否 |
| 缺口体检与补全 | `@/views/jav/GapFill.vue` | `/jav/gap-fill` | 仅 jav |

#### 组 3 整理与入库 `/tools/organize`

| 工具 | 复用组件 | 现路由 |
|---|---|---|
| 批量导入 | `@/views/Import.vue` | `/import` |
| 文件整理 | `@/views/FileOrganize.vue` | `/file-organize` |
| 自动整理 | `@/views/AutoOrganize.vue` | `/auto-organize` |
| 未识别文件 | `@/views/UnrecognizedFiles.vue` | `/unrecognized-files` |
| 文件夹刷新 | `@/views/RefreshFolders.vue` | `/refresh-folders` |
| 文件夹归属 | `@/views/jav/FolderCheck.vue` | `/jav/folder-check` |
| 命名模板 | `@/views/NamingTemplate.vue` | `/naming-template` |
| 命名规范（国产） | `@/views/chinese/NameRules.vue` | `/chinese/name-rules` |
| 扫描控制 | `@/views/ScanControl.vue` | `/scan-control` |
| 分级治理 | `@/views/Tiers.vue` | `/tiers` |
| 工作流 | `@/views/Workflows.vue` | `/workflows` |

#### 组 4 去重与健康 `/tools/health`

| 工具 | 复用组件 | 现路由 |
|---|---|---|
| 重复番号扫描 | `@/views/Duplicates.vue` | `/duplicates` |
| 指纹去重 | `@/views/Fingerprint.vue` | `/fingerprint` |
| 媒体健康扫描 | `@/views/MediaHealth.vue` | `/media-health` |
| 垃圾文件检测 | `@/views/JunkFiles.vue` | `/junk-files` |
| 三态标记 | `@/views/ViewStatus.vue` | `/view-status` |
| 人脸裁剪 | `@/views/FaceCrop.vue` | `/face-crop` |
| 海报增强 | `@/views/PosterEnhance.vue` | `/poster-enhance` |

> 最后两项（人脸裁剪 / 海报增强）属"图像质量"，放进本组 `子标题「图像质量」`，不改组名。

#### 组 5 下载与网盘 `/tools/download`

| 工具 | 复用组件 | 现路由 |
|---|---|---|
| 下载器统一管理 | `@/views/Downloaders.vue` | `/downloaders` |
| 下载任务 | `@/views/download/DownloadManager.vue` | `/download` |
| 115 网盘 | `@/views/Pan115.vue` | `/pan-115` |
| CloudDrive2 | `@/views/CloudDrive2.vue` | `/cloud-drive2` |
| WebDAV 导入 | `@/views/WebDAVImport.vue` | `/webdav-import` |
| STRM 生成 | `@/views/Strm.vue` | `/strm` |
| 高清版目标 | `@/views/QualityGoals.vue` | `/quality-goals` |
| 想要清单 | `@/views/Wants.vue` | `/wants` |

#### 组 6 系统与代理 `/tools/system`

| 工具 | 复用组件 | 现路由 |
|---|---|---|
| 网络诊断 | `@/views/NetworkDiag.vue` | `/network-diag` |
| 内置 Xray 代理 | `@/views/ProxyXray.vue` | `/proxy-xray` |
| 日本节点代理 | `@/views/proxy/JpProxy.vue` | `/proxy/jp` |
| 系统状态 | `@/views/SystemStatus.vue` | `/system-status` |
| 任务管理 | `@/views/Tasks.vue` | `/tasks` |
| 系统日志 | `@/views/Logs.vue` | `/logs` |
| 实时日志流 | `@/views/LogStream.vue` | `/log-stream` |
| Webhook 通知 | `@/views/Webhooks.vue` | `/webhooks` |
| 自动备份 | `@/views/Backup.vue` | `/backup` |

> `Workflows.vue` 同时被组 3 与组 6 引用 → **只允许在组 3 出现一次**，组 6 不放，避免制造新的重复。原则：一个组件在工具中心只允许出现在一个组。

### 7.4 工具中心必须解决的 3 个技术点（给架构师）

1. **module 判定改造（3 处，各 1–2 行）**
   `Crawlers.vue:216-220`、`Patch.vue:276`、`CompareActors.vue:449` 现为：
   ```js
   const seg = route.path.split('/')
   return MODULE_MAP[seg[1]] ? seg[1] : null
   ```
   改为：
   ```js
   const moduleKey = computed(() => {
     const q = route.query.module
     if (q && MODULE_MAP[q]) return q
     const seg = route.path.split('/')
     return MODULE_MAP[seg[1]] ? seg[1] : null
   })
   ```
   这样旧 path 与新 query 两种入口都能正确识别模块，且不影响旧行为。
2. **`keep-alive` 冲突**：`AdminLayout.vue:742` 现有 `<keep-alive :max="20" :exclude="excludeCache">` 以 `$route.name` 为 key。工具组内切工具若都走同一 name（`ToolsFix`），动态组件状态会被缓存复用。**方案**：工具组页内用 `<component :is>` 加载子组件，子组件**不**包 `keep-alive`；若某工具需要保状态（如 `Crawlers` 的筛选），由工具自身用 `sessionStorage` 恢复。
3. **代码分割**：6 个工具组页各自 `() => import()`，组内工具再用 `defineAsyncComponent(() => import('@/views/xxx.vue'))`。避免 `/tools/scrape` 一次拉进 7 个重页面（`Crawlers.vue` 已 1000+ 行）。

---

## 8. SaaS 设计规范（基于现有 token 增量）

> 现有 `src/styles/index.css` 已有 `--space-1..20`、`--font-size-xs..5xl`、`--radius-sm..full`、`--shadow-xs..xl`、`--accent`。**不新建体系，只补缺项 + 明确用法。** 新文件：`src/styles/tokens.redesign.css`，在 `main.js` 中于 `index.css` **之后**引入（覆盖优先级）。

### 8.1 间距刻度（沿用现有，锁定用法）

| Token | 值 | 唯一允许用途 |
|---|---|---|
| `--space-1` | 4px | 图标与文字间距、tag 内边距 |
| `--space-2` | 8px | 紧密元素、按钮组 gap |
| `--space-3` | 12px | 卡片内行间距、表单项间距 |
| `--space-4` | 16px | **卡片内边距、区块内 gap（默认值）** |
| `--space-5` | 20px | 卡片与卡片间距（大屏） |
| `--space-6` | 24px | **内容区左右内边距、区块与区块间距** |
| `--space-8` | 32px | 页面上下留白（≥1440px 时） |
| `--space-12` | 48px | Hero 区上下留白 |

**硬约束**：任何 `margin/padding/gap` 只能取上表值（或 `0`、`auto`、`100%`）。禁止 `13px`、`18px`、`22px` 这类现值散数（当前代码里大量存在）。

### 8.2 字号层级

| 层级 | Token | 值 | 字重 | 行高 | 用途 |
|---|---|---|---|---|---|
| Display | `--font-size-4xl` | 30px | 600 | 1.2 | 首页 Hero 标题 |
| Page Title | `--font-size-3xl` | 24px | 600 | 1.25 | 页面 H1（`PageShell` 标题） |
| Section | `--font-size-lg` | 16px | 600 | 1.4 | 区块标题、卡片标题 |
| Body | `--font-size-base` | 14px | 400 | 1.6 | 正文、表格单元格、菜单 |
| Body Strong | 14px | 500/600 | 1.6 | 强调、选中态 |
| Caption | `--font-size-sm` | 13px | 400 | 1.5 | 说明文字、卡片描述 |
| Meta | `--font-size-xs` | 12px | 400/500 | 1.4 | 时间戳、计数、badge |

- **数字一律 `font-variant-numeric: tabular-nums`**（KPI、计数、进度、番号）。
- **标题 `letter-spacing: -0.01em` ~ `-0.02em`**（≥24px 才用 `-0.02em`），中文正文 `letter-spacing: normal`。
- 全局 `font-family` 不变（沿用现有）。

### 8.3 圆角

| Token | 值 | 用途 |
|---|---|---|
| `--radius-sm` | 4px | tag、badge、小徽标 |
| `--radius-md` | 8px | **按钮、输入框、菜单项、pill**（默认值） |
| `--radius-card` | **10px（新增）** | **所有内容卡片、KPI 卡、工具卡** |
| `--radius-lg` | 12px | 弹层、命令面板、dialog |
| `--radius-xl` | 16px | 大容器（少用） |
| `--radius-full` | 9999px | 头像、状态点 |

> 新增 `--radius-card: 10px` 的动机：8px 对大卡片太锐、12px 又偏圆，10px 是 Linear/Vercel 的常用档。

### 8.4 阴影（只有两档 + 一个浮层档）

| 场景 | 值 |
|---|---|
| 卡片静态 | **无阴影**，只用 `1px solid var(--border-color)` |
| 卡片 hover | **无阴影、无位移**，只改边框色 `color-mix(in srgb, var(--accent) 28%, var(--border-color))` |
| 下拉/弹层/dialog | `--shadow-lg`（`0 8px 24px rgba(0,0,0,.12)`；暗色 `.5`） |
| 命令面板 | `--shadow-xl`（`0 20px 25px -5px rgb(0 0 0 / .12)`） |
| 禁止 | 所有 `hover: translateY(-2px/-3px)`（现 `Home.vue` 与 30+ 页面在用）、`box-shadow: 0 6px 20px` 悬停浮起 |

### 8.5 交互态

```css
--hover-layer:   rgba(15, 18, 26, 0.04);      /* 亮 */
--hover-layer:   rgba(255, 255, 255, 0.06);   /* 暗 */
--active-layer:  rgba(15, 18, 26, 0.07);
--focus-ring:    0 0 0 2px var(--bg-card), 0 0 0 4px color-mix(in srgb, var(--accent) 45%, transparent);
--ease-out:      cubic-bezier(0.16, 1, 0.3, 1);
--dur-fast:      120ms;   /* hover / 图标变色 */
--dur-base:      200ms;   /* 展开折叠 / 页面切换 */
```

- 所有可点元素必须有可见 hover（背景层）与 `:focus-visible`（`--focus-ring`）。**不允许 `outline: none` 裸写**。
- 过渡只允许 `background-color / border-color / color / opacity / transform`，禁止 `transition: all`（现有代码大量使用）。

### 8.6 布局与容器

```css
--sidebar-w: 240px;
--sidebar-w-collapsed: 64px;
--topbar-h: 64px;
--content-max: 1440px;
--content-pad: 24px;      /* < 1440px */
--content-pad-lg: 32px;   /* ≥ 1600px */
```

- 内容区：`padding: var(--content-pad)`，`max-width: var(--content-max)`，`margin: 0 auto`。
- 网格：卡片网格统一 `gap: 16px`，`minmax(280px, 1fr)`（工具卡）/ `minmax(130px,1fr)`（海报）/ `repeat(4,1fr)`（KPI，`<1280px` 降 2 列，`<768px` 1 列）。
- 断点：沿用现有 `800px` / `1280px`，新增 `1600px`（只加内边距，不改列数）。

### 8.7 表格密度

| Token | 值 |
|---|---|
| 行高（默认） | 48px |
| 行高（紧凑，`density="compact"`） | 40px |
| 单元格内边距 | `12px 16px` |
| 表头 | 背景 `var(--bg-page)`，13px/500 `--text-secondary`，`position: sticky; top: 0` |
| 分隔线 | 仅横向 `1px solid var(--border-light)`，**无竖线、无斑马纹** |
| hover 行 | `var(--hover-layer)` |
| 数字列 | 右对齐 + `tabular-nums` |

> 现状问题：`index.css` 已有 `el-table` 覆盖，但 30+ 页面各自 `:deep(.el-table)` 再覆盖。本轮**不改**各页面内部表格，只保证工具组页外层容器不与之冲突。

### 8.8 空 / 加载 / 错误

统一使用已存在的 `components/EmptyState.vue`、`components/base/SkeletonGrid.vue`、`components/Skeleton.vue`：

| 态 | 规格 |
|---|---|
| 空状态 | 图标 48px（`--text-placeholder`）、标题 15px/500 `--text-primary`、描述 13px `--text-secondary`、**最多 1 个主操作按钮**、`padding: 48px 24px`、整体居中 |
| 骨架屏 | shimmer 宽 1.4s 线性循环，底色 `var(--bg-page)`，高光 `color-mix(in srgb, var(--bg-card) 70%, transparent)`；**形状必须与真实内容同尺寸**（卡片骨架 = 卡片真实宽高），禁止用 `v-loading` 盖一层白色遮罩（现状 `Home.vue:100` 即此写法） |
| 错误 | 区块内联展示：`WarningFilled` 16px `--danger` + 13px 文案 + 「重试」文字按钮；**不使用 ElMessage 弹窗报错**（页面级错误不走 toast） |
| 加载最短时长 | 骨架屏至少展示 200ms，避免闪跳 |

### 8.9 色彩使用纪律

- `--accent (#5468d4)` 只允许出现在：主按钮、选中态（菜单/tab/pill）、KPI 数字、焦点环、链接文字。
- **不允许**：渐变背景（`--brand-gradient` 仅保留给 logo 方块）、彩色模块大色块（现 `Home.vue:163-184` 的 7 个 `linear-gradient` 全部移除）。
- 状态色沿用：`--success #67c23a` / `--warning #e6a23c` / `--danger #f56c6c`，只用于状态点、tag、错误文案。
- 模块识别不用颜色，用 **emoji + 文字**（现方案已如此，保留）。

---

## 9. 待确认问题（5 条）

| # | 问题 | 影响 | 默认方案（若无回复则按此执行） |
|---|---|---|---|
| **Q1** | 侧栏是否接受**浅色**（`#FBFBFC` + 右边框）替代现在的深蓝渐变？这是"感觉不一样"的最大杠杆，但会失去"深色影院感" | §5.2 全部 | 接受浅色；深色模式保留蓝黑体系，影院感交给深色主题承载 |
| **Q2** | 后端 `GET /stats/movies` 是否支持 `range=7d` 或返回 `created_last_7d` 字段？（KPI 卡"近 7 日 +36"依赖它） | §6 区块 3 | **不支持**：不请求新接口，KPI 第二行改为「占总库 12%」等现有字段派生；或直接不显示第二行 |
| **Q3** | `/tools/*` 6 个分组页里，旧路由（`/jav/scrape` 等）走 **R2 保留（推荐，0 风险）** 还是 **P1 的 redirect 收敛**？ | §4.2 | 本轮只做 R2；R3 留到下阶段随 module 兜底改造一起做 |
| **Q4** | 底部状态栏移除后，「可撤销 N 步」入口是否需要保留？现只在 status bar 出现 | §5.1 | 移到顶栏用户菜单旁、仅在 `undoStore.canUndo` 时出现的 24px 小 Chip；否则彻底删除 |
| **Q5** | 首页「最近活动」是否要把「刮削复核待办数」`/review` 的条数拉进来？（需 `getTasks` 之外再请求一次列表接口） | §6 区块 6 | 本轮**不做**，只显示任务列表；下阶段随 P1-5 一起做 |

---

## 10. 交付物清单（给架构师的落地顺序）

| 步 | 产出 | 依赖 |
|---|---|---|
| 1 | `src/config/nav.js` | 无 |
| 2 | `src/styles/tokens.redesign.css` + `main.js` 引入 | 无 |
| 3 | `src/components/shell/NavGroup.vue`（侧栏一级/二级项，含折叠动画） | 1,2 |
| 4 | `src/layouts/AppSidebar.vue` | 1–3 |
| 5 | `src/layouts/AppTopbar.vue`（含用户菜单、任务胶囊） | 1,2 |
| 6 | `src/components/shell/CommandPalette.vue` | 1,2 |
| 7 | `AdminLayout.vue` 重写外壳部分（保留全部逻辑与对话框，删 status bar） | 4–6 |
| 8 | `src/components/dashboard/*` 8 个组件 + `Home.vue` 重写 | 2 |
| 9 | `src/components/shell/ToolPageShell.vue` + `ToolCard.vue` | 2 |
| 10 | `src/views/tools/ToolsHub.vue` + 6 组页 | 9 |
| 11 | `routes.web.js` 追加 7 条新路由 + `/uncensored` redirect 修正 | 10 |
| 12 | `Crawlers.vue` / `Patch.vue` / `CompareActors.vue` 各加 `route.query.module` 兜底（P1 前置，2 行） | 10 |

**验收自测清单**

- [ ] A1 1080p / 900p 两档侧栏无滚动条
- [ ] A2 菜单中"刮削""补全""对比"各只出现 1 次（侧栏，不含工具卡片）
- [ ] A3 1440×900 首屏见 Hero + 继续观看 + KPI + ModulePills
- [ ] A4 亮色页面无渐变块、无非中性彩色底
- [ ] A5 `Ctrl+K` → 输"补丁" → 回车 到 `/tools/fix?tool=patch`
- [ ] A6 遍历 `routes.web.js`，全部 path `router.resolve().matched.length > 0`
- [ ] A7 1280/1440/1920 三档无横向滚动
- [ ] 旧路由 `/jav/scrape`、`/compare-actors`、`/jav/top250` 直接访问不 404、不白屏
- [ ] 暗色模式全量截图复查（尤其新增卡片边框、hover 层）
- [ ] Electron 端（若构建）启动无 `status-bar` 布局塌陷、`titlebar-h` 变量仍生效
