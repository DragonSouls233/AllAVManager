// ============================================================
// 应用形态（flavor）：构建期常量，决定 UI 形态
//   desktop → 消费型播放器（影片库 / 类别 / 系列 / 演员 / 喜好）
//   web     → 管理后台（全量运维功能）
//
// __APP_FLAVOR__ 由以下配置注入（编译期字面量，未命中分支被静态消除）：
//   vite.config.js      → 'desktop'
//   vite.config.web.js  → 'web'
//
// 注意：路由表本身不走运行时分支，而是由 vite alias 在构建期
// 物理替换 `@/router/routes`（见两份 vite 配置的 resolve.alias），
// 未选中的路由文件不进入依赖图 —— 保证桌面端不打包任何管理端页面。
// ============================================================

/* global __APP_FLAVOR__ */
export const FLAVOR = typeof __APP_FLAVOR__ !== 'undefined' ? __APP_FLAVOR__ : 'web'

/** 桌面端（消费型播放器） */
export const isDesktop = FLAVOR === 'desktop'

/** Web 端（管理后台） */
export const isWeb = FLAVOR === 'web'

/** 应用显示名 */
export const APP_TITLE = isDesktop ? 'MDCX Player' : '龙魂 视频管理系统'

/** 应用副标题（侧栏/顶栏用） */
export const APP_SUBTITLE = isDesktop ? '影音库' : '视频管理系统'

export default { FLAVOR, isDesktop, isWeb, APP_TITLE, APP_SUBTITLE }
