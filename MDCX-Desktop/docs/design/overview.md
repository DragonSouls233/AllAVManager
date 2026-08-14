# MDCX 桌面端 · 播放体验与后端连接 设计交付

## 交付物
1. **高保真可交互原型** — `mdcx-player-redesign.html`
   - 影院暗色播放器：自定义控制栏、进度条 hover 缩略图、画质/倍速/字幕菜单
   - 顶栏后端连接状态胶囊（点击可模拟 在线/弱网/重连 三态）
   - 断点续播条、系列连播列表、底部媒体流状态条
2. **设计系统文档** — `MDCX播放器与后端连接设计系统.md`
   - 设计 Token、组件规格、后端连接状态机、媒体流策略、落地优先级

## 现状关键发现（基于真实代码）
- 播放器 3 套分散实现（`Play.vue` 内联 ~600 行 / `ArtplayerVideo.vue` / `EnhancedArtplayer.vue` 弹幕坏）
- 缩略图进度条用了无效 API `art.template.ingestedThumbnailCues`，悬停预览实际不显示
- 后端连接层完整（health/play/external/hls/模块/mpv/反代/网盘），但前端**无连接状态可视化**
- 有 `recordPlay` 观影记录 API 但播放页未接断点续播

## 设计重点
- 统一播放器实现到 `ArtplayerVideo.vue`，修复缩略图
- 新增 `ConnectionStatus.vue` 连接胶囊（三态 + 弱网自动降码率）
- 接入断点续播 + 系列连播（复用现有端点）
- 落地面向现有 Artplayer 5 + 现有后端端点，不臆改未确认 API
