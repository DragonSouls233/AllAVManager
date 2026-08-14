# MDCX 桌面端 · 播放体验与后端连接 设计系统 (Cinema v1)

> 适用范围：MDCX-Desktop（Electron + Vue3 + Element-Plus + Pinia，构建产物由后端 `static/` 托管）
> 目标：把"更好的视频播放"和"和后端链接"做成一套统一、可落地的设计系统。
> 配套高保真原型：`mdcx-player-redesign.html`（可交互预览）

---

## 1. 设计目标与原则

| 目标 | 说明 |
|---|---|
| **影院级沉浸** | 播放器默认暗色、16:9、控制栏自动隐显，把注意力留给画面 |
| **连接可感** | 后端连接状态、画质/码率、缓冲必须"看得见"，断了用户不慌 |
| **连贯观看** | 断点续播 + 系列连播，一次点开看到底 |
| **一处实现** | 播放器核心逻辑只写一遍（收敛 `Play.vue` 内联代码到 `ArtplayerVideo.vue`） |
| **无障碍** | 控件可键盘操作、对比度达标、字幕/画质切换有明确状态 |

---

## 2. 设计 Token（沿用现有蓝系，新增影院暗色）

```css
:root{
  /* 色彩：沿用 Element/Artplayer 蓝，叠加影院黑 */
  --bg-0:#0b0c0f;  --bg-1:#141519;  --bg-2:#1c1e24;  --bg-3:#262932;
  --line:#2c2f38;
  --txt-1:#eef1f6; --txt-2:#aeb4c2; --txt-3:#717886;
  --brand:#3b8cff; --brand-2:#2396ef;   /* 与现有 Artplayer theme 一致 */
  --ok:#2ecc71; --warn:#f5a623; --bad:#ef4d56;
  /* 间距：4 基准 */
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px;
  /* 圆角 */
  --r-lg:16px; --r-md:12px; --r-sm:8px;
  --shadow:0 10px 40px rgba(0,0,0,.55);
}
```

> 适配现有 `getServerBaseUrl()` 同源托管：播放器/媒体走 `window.location.origin`，API 走 `localStorage.serverUrl`（跨域后端）。设计上媒体与 API 分离，不混用。

---

## 3. 组件库规格

### 3.1 播放器控制栏（`ArtplayerVideo.vue` 统一承载）
- 布局：进度条（含 hover 缩略图预览）+ 一行按钮（播放/暂停、时间、画质、倍速、字幕、音量、画中画、设置、全屏）。
- 控制栏 `opacity:0` 默认隐藏，`.player:hover` 或 `.playing` 时淡入。
- **缩略图进度条修复方向**：现行代码 `art.template.ingestedThumbnailCues = cues` 是无效 API（Artplayer 5 无此字段，悬停预览实际不显示）。落地时应改为 Artplayer 官方缩略图方案（`thumbnail` option 或 `<track kind="thumbnail">` VTT），并先在开发机核对 Artplayer 5 当前 API 再改。
- 画质/倍速/字幕做成**下拉菜单**（非平铺按钮），减少控制栏拥挤。

### 3.2 后端连接状态胶囊（新增 `ConnectionStatus.vue`，置于顶栏右侧）
| 状态 | 颜色 | 文案 | 行为 |
|---|---|---|---|
| `online` | 绿 | 后端已连接 · 12ms · HLS·自适应 | 正常 |
| `weak` | 黄 | 弱网 · 已降码率 · 320ms | 自动降画质，提示一次 |
| `reconnect` | 红(脉冲) | 连接中断 · 自动重连中 (2/5) | 自动重试 + 断点续播保留 |

- 数据来源：复用现有 `checkServerConnection()`（`/api/v1/health`）；弱网判定 = 播放请求耗时 > 阈值；重连 = 监听 axios 响应拦截器 `error`（非 401）。
- 点击胶囊可手动触发一次探活（便于排查）。

### 3.3 断点续播条（新增，置于播放器下方）
- 加载影片时调 `getViewingHistory` 取 `position`；有进度则显示"从第 mm:ss 继续（已看 NN%）"。
- 播放中每 10s 调一次 `recordPlay({movie_id, position, duration})`（端点已存在 `/viewing/play`）。
- 点"继续观看"→ `art.currentTime = position`。

### 3.4 系列连播列表（右侧栏，复用现有 JAV 系列端点）
- 数据：复用 `/jav/series/{name}/movies` + `module` 参数（已支持 jav/fc2/uncensored/western）。
- 当前话高亮、已看打勾、点击切换并自动加载下一部播放 URL（`getModulePlayUrl` / HLS）。

### 3.5 续播/连播之外的细节
- 信息卡片（番号、标题、评分、标签 chip、演员 chip 可点进详情）——沿用 `Play.vue` 现有结构，仅视觉统一到 Token。
- 快捷键帮助（`?` 唤起）：空格播放、←→ 快进退、F 全屏、M 静音、↑↓ 音量。

---

## 4. 后端连接架构与媒体流策略

```
┌──────────────┐   同源托管    ┌──────────────────────────────┐
│  MDCX-Desktop │ ───────────▶ │  FastAPI (static/ + /api/v1) │
│  (Electron)   │  origin=后端  │                              │
└──────────────┘              │  媒体端点(已白名单放行):      │
      │  axios                 │   /movies/{id}/play/external  │
      │ baseURL=/api/v1        │   /movies/{id}/hls/master.m3u8│
      │ (serverUrl 可跨域)     │   /modules/{m}/movies/{id}/play│
      └──────────────────────▶ │   /proxy-play/{id} (302反代)  │
                                │   /files/proxy?path= (本地文件)│
                                └──────────────────────────────┘
```

**媒体流优先级（设计建议）**
1. 本地直连/同域：`/movies/{id}/play/external?protocol=http` 返回 `play_url` → 直接喂 Artplayer。
2. 大文件/远程：走 HLS `/hls/master.m3u8` → 自适应码率（已有 `getHlsQualities`）。
3. 网盘源：CloudDrive2 / pan115 走各自 `stream-url` 端点。
4. 防盗链/跨域：一律经后端代理（`/files/proxy`、`/previews/...`），前端不直连外链。

**错误与重连 UX**
- 401 → 现有逻辑跳登录（保留）。
- 网络错误/超时 → 连接胶囊转 `reconnect`，自动重试播放请求（指数退避，最多 5 次），期间显示缓冲占位；续播位置不丢。
- 媒体 404/解码失败 → 提示"该源不可用"，并提供"外部播放 / mpv 播放"回退（现有按钮保留）。

---

## 5. 落地优先级（按现状缺口排序）

| # | 任务 | 现状缺口 | 工作量 |
|---|---|---|---|
| 1 | 统一播放器：把 `Play.vue` 内联 Artplayer 收敛进 `ArtplayerVideo.vue` | 三处重复、维护成本高 | 中 |
| 2 | 修复缩略图进度条（替换无效 `ingestedThumbnailCues`） | 悬停预览不显示 | 小 |
| 3 | 新增 `ConnectionStatus.vue` 连接状态胶囊 | 前端无连接可视化 | 小 |
| 4 | 接入断点续播（`recordPlay`/`getViewingHistory`） | API 已有未接 | 小 |
| 5 | 系列连播列表（复用系列端点） | 播放页无连播 | 中 |
| 6 | `EnhancedArtplayer.vue` 弹幕：引入真实 danmaku 插件或下线 | plugins 空数组，弹幕坏 | 小 |
| 7 | 快捷键帮助面板 + 控制栏菜单化 | 体验细节 | 小 |

> 设计原则（遵循项目规范）：修改前先读对应源码与 Artplayer 5 文档，不在未确认 API 时臆改；改动后需 Playwright 真实浏览器 QA 验证播放/续播/连播/弱网提示。

---

## 6. 验收标准
- 播放器在暗色影院风格下 16:9 沉浸式呈现，控制栏 hover/播放时淡入。
- 缩略图进度条 hover 可见；画质/倍速/字幕菜单可切换并实时反映到状态条。
- 顶栏连接胶囊能正确反映 在线/弱网/重连 三态，弱网自动降码率并提示一次。
- 打开有观看记录的影片显示续播条，点"继续"跳到记录位置。
- 系列影片可一键连播，当前话高亮。

---

## 7. 落地进度（2026-08-13）

### 第一轮（已交付）
- ✅ **#2 缩略图修复**：`Play.vue` 与 `ArtplayerVideo.vue` 改用官方 `thumbnails` API，替换无效 `ingestedThumbnailCues`。
- ✅ **#3 连接胶囊**：新增 `ConnectionStatus.vue`（online/weak/reconnect 三态 + 指数退避重连 + 延迟测量）。
- ✅ **#4 断点续播**：`Play.vue` 接入 `getViewingHistory`/`recordPlay`，续播条 + 每 10s 上报。

### 第二轮（本次交付）
- ✅ **#1 统一播放器收口**：删除 `Play.vue` 内联 `initArtplayer`/`buildArtSettings`/`buildThumbnails`/`switchAudioTrack`/`switchQuality`，改用 `<ArtplayerVideo>` 统一基座。Play 专属逻辑（生成 GIF 右键菜单、续播上报、mpv/截图/字幕）通过 `@ready`/`@chapter-mark`/`@error`/`@ended` 事件与 `extraContextmenu` prop 保留。`Play.vue` 现在只有 **1 处** Artplayer 实例化（`ArtplayerVideo.vue` 内部），消除重复。
- ✅ **#5 系列连播**：`Play.vue` 新增 `loadSeriesPlaylist`（模块场景调 `getModuleSeriesMovies`）、`series-bar` UI（横向小卡、当前高亮、已看置灰）、`@ended` 自动跳下一集（`router.push` 触发现有 `route` watch 重载，无需额外状态管理）。`autoNext` 开关保证首次进入不自动播、连播时自动续看。
- ⏭️ **#6 弹幕**：**用户明确不需要**。原 `EnhancedArtplayer.vue` 弹幕插件数组为空、调用 `art.plugins.danmaku` 必崩，但**无任何引用（死代码）**，不影响线上，保持下线不动。

### 第三轮（本次交付）
- ✅ **#7 快捷键帮助面板**：
  - 新增 `ShortcutHelp.vue`（暗色模态，`v-model` 控制；全局 `?` 唤起、`Esc` 关闭；列出已核实快捷键 + "播放器聚焦时生效"脚注；`<kbd>` 键帽样式）。
  - `Play.vue` 引入组件，conn-bar 下渲染；`info-actions` 加"⌨ 快捷键"发现按钮（`showShortcutHelp = true`）。
  - **核实并修正了原 §3.5 的不准确处**：Artplayer 5.4.0 默认**只**绑定 `Space / ←→ / ↑↓ / Esc`（基于 `e.code`、仅播放器聚焦生效），**并不**绑定 `F`/`M`。为让帮助面板所言非虚，本项目在 `Play.vue` 全局 `keydown` 显式接入 **`F` 切换全屏**（`art.fullscreen = !art.fullscreen`）与 **`M` 切换静音**（`art.muted = !art.muted`），并带输入框/修饰键守卫。`?` 帮助键同为全局。
  - 帮助面板所列全部为真实可用键，无虚列。

### 验证
- `vite build --config vite.config.web.js`（managed Node 22.22.2）编译通过；`static` 为干净单一批次。
- 本地 Playwright 冒烟：app 挂载、**0 uncaught / 0 fatal**（唯一 404 为本地静态服务缺资源，非回归）。
- 本地 Playwright 冒烟：app 挂载、0 uncaught error、0 fatal（唯一 404 为静态服务资源缺失，非回归）。
- 部署后真实 QA：`scripts/qa_player_connection.mjs`（已增强连播检查项）覆盖连接胶囊/缩略图/续播/连播。
