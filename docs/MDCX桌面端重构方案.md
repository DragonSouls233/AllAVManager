# MDCX 桌面端重构方案：从「Web 管理后台套壳」到「消费型播放器」

> 版本 v1.0 · 2026-09-08
> 适用范围：`G:\MDCX\MDCX-Desktop`（桌面端）与 `G:\MDCX\MDCX-Server\static`（Web 端）

---

## 一、问题定义

### 1.1 现状

桌面端 exe 打开后是一个**完整的 Web 管理后台**：左侧 8 大模块分组、60+ 菜单项，包含扫描控制、刮削管理、补丁刮削、片商合并、番号提取测试、Xray 内置代理、Schema 设置、部署档位、系统日志、用户管理……共 100+ 个功能页面。

它能用，但它不是"桌面软件"，是"浏览器里打开的后台页面被装进了 exe"。

### 1.2 根因（架构层）

两套构建共用同一入口链，导致形态必然相同：

| 构建 | 配置文件 | 产物 | 入口链 |
|------|---------|------|--------|
| 桌面端 | `vite.config.js` | `dist/` + `dist-electron/` → `release/*.exe` | `index.html` → `src/main.js` → `src/App.vue` |
| Web 端 | `vite.config.web.js` | `MDCX-Server/static/` | **完全相同的同一条链** |

两者唯一差别是前者的 vite 配置多挂了 `vite-plugin-electron`。`src/router/index.js` 里那一份 700 行的全量路由表，两个产物共用。

**所以"桌面端只有 5 个页面"这个需求，在现有架构下无法通过改菜单实现——必须在构建期让两条链分叉。**

### 1.3 目标形态

MDCX Player —— 对标 Netflix / Plex / Jellyfin 客户端的**纯消费型前端**：

- 打开就是影片海报墙，不是统计仪表盘
- 导航只有 5 项：**影片库 / 类别 / 系列 / 演员 / 喜好**
- 一个全局模块切换器（JAV有码 / 无码 / FC2 / 国产 / 欧美 / 里番 / PORNHub / 全部）
- 点海报 → 详情面板；点播放 → 全屏播放器
- 所有"管理/运维/刮削"能力**只留在 Web 端**，桌面端一行代码都不打包

---

## 二、架构方案：一套 src，两种 flavor

### 2.1 核心机制

**构建期注入 flavor 常量 → 路由表与布局按 flavor 分叉 → 未命中的代码被 tree-shake 掉。**

```
vite.config.js       define: __APP_FLAVOR__ = 'desktop'
vite.config.web.js   define: __APP_FLAVOR__ = 'web'
                              │
                              ▼
                     src/config/flavor.js
                     export const FLAVOR   = __APP_FLAVOR__
                     export const isDesktop = FLAVOR === 'desktop'
                              │
                              ▼
                     src/router/index.js
                     routes = isDesktop ? routes.desktop : routes.web
```

关键点：`__APP_FLAVOR__` 是编译期字面量，`isDesktop` 在 web 构建中恒为 `false`，Rollup 会把 `routes.desktop` 整个分支（连带 100+ 管理页的 `import()`）**静态消除**。桌面端反之。两个产物各自只包含自己需要的代码。

### 2.2 目录变更

| 路径 | 动作 | 说明 |
|------|------|------|
| `src/config/flavor.js` | **新增** | flavor 常量与判定 |
| `src/router/routes.web.js` | **新增**（迁出） | 现有全部路由，原样搬移，零逻辑改动 |
| `src/router/routes.desktop.js` | **新增** | 桌面端 12 条路由 |
| `src/router/index.js` | **改写** | 只保留 flavor 分发 + 守卫 |
| `src/layouts/AdminLayout.vue` | **新增**（迁出） | 现有 `views/Layout.vue` 原样搬移 |
| `src/layouts/CinemaLayout.vue` | **新增** | 桌面端影院式布局（顶栏 + rail + 主舞台） |
| `src/views/desktop/` | **新增** | 消费端页面：Library / Categories / Series / Actors / Favorites / ActorWorks / MovieDetail / Settings |
| `src/components/cinema/` | **新增** | PosterCard / FilterBar / ModuleSwitcher / RailNav / SkeletonGrid |
| `src/stores/library.js` | **新增** | 当前模块、筛选条件、收藏状态（跨页保持） |
| `src/styles/cinema.css` | **新增** | 影院风设计 token 与组件样式 |

**`src/views/*.vue` 全部不动**——Web 端继续用它们，桌面端复用其中可复用的（Play.vue、MovieDetail.vue、Login.vue）。

### 2.3 Web 端零影响保证

- `routes.web.js` 内容 = 现有路由表逐字复制（仅把 `views/Layout.vue` 改为 `layouts/AdminLayout.vue`）
- `AdminLayout.vue` = 现有 `Layout.vue` 逐字复制
- Web 构建产物应与管理端现状逐字节等价（除 chunk hash）

---

## 三、桌面端信息架构

### 3.1 布局骨架

```
┌──────────────────────────────────────────────────────────────┐
│ TitleBar  品牌 │ 模块切换器 ▾ │  全局搜索  │ NSFW ☾ ⚙ ─ □ ✕  │ 56px
├──────┬───────────────────────────────────────────────────────┤
│ 🎬   │  筛选条：排序 │ 年份 │ 评分 │ 片商 │ 标签        [网格]│
│ 影片库│                                                        │
│ 🏷   │  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐          │
│ 类别 │  │海报│ │海报│ │海报│ │海报│ │海报│ │海报│   2:3     │
│ 📚   │  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘          │
│ 系列 │  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐          │
│ 👤   │  │海报│ │海报│ │海报│ │海报│ │海报│ │海报│          │
│ 演员 │  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘          │
│ ★    │                    ↓ 滚动到底自动加载                  │
│ 喜好 │                                                        │
└──────┴───────────────────────────────────────────────────────┘
  72px              主舞台（暗色，径向光晕 + 噪点纹理）
```

### 3.2 路由表（desktop）

| 路由 | 组件 | 说明 |
|------|------|------|
| `/` | redirect → `/library` | |
| `/library` | `desktop/Library.vue` | 影片库（海报墙 + 筛选 + 无限滚动） |
| `/categories` | `desktop/Categories.vue` | 类别（卡片云，带影片数） |
| `/library?genre=xxx` | `desktop/Library.vue` | 类别 → 影片库（带筛选） |
| `/series` | `desktop/Series.vue` | 系列卡片墙，展开看该系列影片 |
| `/actors` | `desktop/Actors.vue` | 演员头像墙 + 首字母导航 |
| `/actors/:id` | `desktop/ActorWorks.vue` | 演员作品墙 |
| `/favorites` | `desktop/Favorites.vue` | 喜好（Tab：影片 / 演员 / 系列） |
| `/movie/:module/:id` | `desktop/MovieDetail.vue` | 详情面板（复用 MovieDetail 数据层） |
| `/play/:id` | `views/Play.vue`（**复用**） | 全屏播放器 |
| `/settings` | `desktop/Settings.vue` | 极简设置 |
| `/login` | `views/Login.vue`（**复用**） | 登录（桌面端自动填充凭证） |

**12 条路由 vs 现有 100+ 条。**

### 3.3 数据流（全部走现有 API，后端零改动）

| 页面 | 接口 | 来源 |
|------|------|------|
| 模块切换器 | `getModules()` | `api/modules.js` |
| 影片库 | `getUnifiedMovies(params)` | `api/modules.js` → `/modules/unified/movies` |
| 类别 | `getModuleCategories(module, {limit})` / `getMoviesByCategory()` | `api/index.js` |
| 系列 | `getModuleSeries(module, params)` / `getModuleSeriesMovies()` | `api/index.js` |
| 演员 | `getActors({module, ...})` | `api/index.js:255` |
| 喜好 | `getFavoriteGroups()` / `getFavoriteItems()` | `api/index.js:399` |
| 里番系列/喜好 | `getAnimeSeries()` / `getAnimeFavoriteSeries()` | `api/anime.js` |
| 全局搜索 | `unifiedSearch(keyword)` | `api/modules.js` |
| 封面 | `getCoverSrc()` — 已修 Electron origin 问题 | `utils/media.js` |

---

## 四、设计系统（影院风）

### 4.1 色彩 token

在现有 `html.dark` 基础上扩展（`src/styles/cinema.css`）：

```css
--cinema-0:  #0B0E14;   /* 舞台底 — 深蓝黑，非纯黑 */
--cinema-1:  #13161D;   /* 卡片 */
--cinema-2:  #1A1E27;   /* 抬升层（顶栏/弹层） */
--cinema-3:  #252A36;   /* hover */
--cinema-line: #2A2F3A; /* 描边 */
--brand:     #00A3FF;   /* 电光蓝 — 品牌与选中态 */
--accent:    #FFB020;   /* 琥珀金 — CTA 与评分/收藏 */
--text-1: #E8ECF4;  --text-2: #A7B0C0;  --text-3: #6B7484;
```

### 4.2 关键规则

- **背景纵深**：`--cinema-0` 打底 + 顶部径向光晕（`radial-gradient` 品牌色 8% 透明）+ 2% 噪点纹理。绝不用平铺纯色。
- **海报**：2:3 固定比例，圆角 10px，hover `translateY(-6px) scale(1.03)` + 品牌色外发光 + 200ms 缓动；尊重 `prefers-reduced-motion`。
- **字号**：片名 15px/600，元信息 12px/`--text-2`；正文不小于 13px。
- **加载态**：骨架网格（`SkeletonGrid`），不是转圈。
- **错误态**：保留全部筛选条件，只高亮提示 + 重试按钮，**绝不清空用户输入**。
- **触摸/点击目标**：≥44×44px。
- **对比度**：正文 ≥4.5:1，UI 元素 ≥3:1。

### 4.3 记忆点

**海报墙的"沉浸模式"**：鼠标静止 2.5s 后，非焦点海报降到 40% 不透明度、顶栏与 rail 自动淡出，画面只剩海报——把桌面端和网页端一眼区分开。

---

## 五、分阶段实施

| 阶段 | 内容 | 产出验证 |
|------|------|---------|
| **P0** | flavor 机制 + 路由分表 + layouts 拆分 + CinemaLayout 骨架 + 5 个占位页 | 打包 exe，打开只有 5 项导航；Web 端产物无变化 |
| **P1** | 影片库（PosterCard / FilterBar / 无限滚动 / 骨架屏） | 海报墙可用，滚动流畅 |
| **P2** | 类别页 + 系列页（含系列展开） | 类别/系列可点进影片库 |
| **P3** | 演员墙 + 喜好页（三 Tab） | 演员可点进作品墙；喜好可增删 |
| **P4** | 详情面板 + 播放器接入 + 极简设置 | 海报→详情→播放全链路通 |
| **P5** | 原生能力：托盘菜单、全局快捷键(Ctrl+F/空格)、全屏切换、窗口位置记忆、图标 | 打包收尾 |

---

## 六、风险与对策

| 风险 | 对策 |
|------|------|
| 改动破坏 Web 端 | P0 阶段路由/布局是**纯搬移**，改完立即跑 web 构建比对；Web 端页面文件一个都不动 |
| `views/Layout.vue` 被别处引用 | 全局 grep 确认引用点；`routes.web.js` 改为 `layouts/AdminLayout.vue` |
| 桌面端 mdcx:// 协议跳转到已删除路由 | 路由守卫加 fallback：桌面端未注册路径 → `/library` |
| Play.vue 2168 行可能与影院布局冲突 | P4 阶段做适配层，不改动原文件；桌面端用 `?cinema=1` 走全屏样式 |
| 自定义图标缺失 | P5 补 `build.win.icon`（当前是 Electron 默认图标） |

---

## 七、待确认决策

1. **登录**：桌面端是否需要登录页？（建议：保留但自动填充凭证静默登录，本机可信）
2. **模块范围**：模块切换器是否包含全部 7 个模块，还是只留你实际在用的？
3. **沉浸模式**：是否需要第五节 4.3 的自动淡出效果？
