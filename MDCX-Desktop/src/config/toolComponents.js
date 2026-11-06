/**
 * MDCX · 工具组件映射表（Phase 1）
 *
 * ⚠️ 全仓库**唯一**允许 import 工具页 `.vue` 的文件。
 *    47 个工具全部走 `defineAsyncComponent`，组内切换时按需加载，
 *    避免 `/tools/organize` 一次把 10 个重页面拉进同一个 chunk。
 *
 * `tool` 键来自 `src/config/nav.js` 的 `TOOL_GROUPS[].tools[].tool`。
 */
import { defineAsyncComponent } from 'vue'
import ToolLoading from '@/components/shell/ToolLoading.vue'

/**
 * 统一的懒加载包装：120ms 内不闪骨架（本地磁盘读取通常 <120ms）、
 * 30s 超时兜底。`suspensible: false` 让异步组件自己控制占位，
 * 不与路由级 Suspense（本项目没有）发生耦合。
 * @param {() => Promise<any>} loader
 */
const lazy = (loader) =>
  defineAsyncComponent({
    loader,
    loadingComponent: ToolLoading,
    delay: 120,
    timeout: 30000,
    suspensible: false,
  })

export const TOOL_COMPONENTS = {
  /* ---------- 刮削与源（7） ---------- */
  crawlers: lazy(() => import('@/views/Crawlers.vue')),
  sitePriority: lazy(() => import('@/views/SitePriority.vue')),
  siteRegistry: lazy(() => import('@/views/sites/SiteRegistry.vue')),
  cookieManager: lazy(() => import('@/views/CookieManager.vue')),
  cookieCloud: lazy(() => import('@/views/CookieCloud.vue')),
  review: lazy(() => import('@/views/Review.vue')),
  gfriends: lazy(() => import('@/views/Gfriends.vue')),

  /* ---------- 补全与对比（6） ---------- */
  patch: lazy(() => import('@/views/Patch.vue')),
  compare: lazy(() => import('@/views/Compare.vue')),
  compareActors: lazy(() => import('@/views/CompareActors.vue')),
  nfoScrape: lazy(() => import('@/views/NfoScrape.vue')),
  sourceMerge: lazy(() => import('@/views/SourceMerge.vue')),
  gapFill: lazy(() => import('@/views/jav/GapFill.vue')),

  /* ---------- 整理与入库（10） ---------- */
  import: lazy(() => import('@/views/Import.vue')),
  fileOrganize: lazy(() => import('@/views/FileOrganize.vue')),
  autoOrganize: lazy(() => import('@/views/AutoOrganize.vue')),
  unrecognizedFiles: lazy(() => import('@/views/UnrecognizedFiles.vue')),
  refreshFolders: lazy(() => import('@/views/RefreshFolders.vue')),
  folderCheck: lazy(() => import('@/views/jav/FolderCheck.vue')),
  namingTemplate: lazy(() => import('@/views/NamingTemplate.vue')),
  chineseNameRules: lazy(() => import('@/views/chinese/NameRules.vue')),
  tiers: lazy(() => import('@/views/Tiers.vue')),
  workflows: lazy(() => import('@/views/Workflows.vue')),

  /* ---------- 去重与健康（7） ---------- */
  duplicates: lazy(() => import('@/views/Duplicates.vue')),
  fingerprint: lazy(() => import('@/views/Fingerprint.vue')),
  mediaHealth: lazy(() => import('@/views/MediaHealth.vue')),
  junkFiles: lazy(() => import('@/views/JunkFiles.vue')),
  viewStatus: lazy(() => import('@/views/ViewStatus.vue')),
  faceCrop: lazy(() => import('@/views/FaceCrop.vue')),
  posterEnhance: lazy(() => import('@/views/PosterEnhance.vue')),

  /* ---------- 下载与网盘（8） ---------- */
  downloaders: lazy(() => import('@/views/Downloaders.vue')),
  downloadManager: lazy(() => import('@/views/download/DownloadManager.vue')),
  pan115: lazy(() => import('@/views/Pan115.vue')),
  cloudDrive2: lazy(() => import('@/views/CloudDrive2.vue')),
  webdavImport: lazy(() => import('@/views/WebDAVImport.vue')),
  strm: lazy(() => import('@/views/Strm.vue')),
  qualityGoals: lazy(() => import('@/views/QualityGoals.vue')),
  wants: lazy(() => import('@/views/Wants.vue')),

  /* ---------- 系统与代理（9） ---------- */
  networkDiag: lazy(() => import('@/views/NetworkDiag.vue')),
  proxyXray: lazy(() => import('@/views/ProxyXray.vue')),
  jpProxy: lazy(() => import('@/views/proxy/JpProxy.vue')),
  systemStatus: lazy(() => import('@/views/SystemStatus.vue')),
  tasks: lazy(() => import('@/views/Tasks.vue')),
  logs: lazy(() => import('@/views/Logs.vue')),
  logStream: lazy(() => import('@/views/LogStream.vue')),
  webhooks: lazy(() => import('@/views/Webhooks.vue')),
  backup: lazy(() => import('@/views/Backup.vue')),
}

/**
 * 取工具组件。键不存在时返回 `null`（调用方负责渲染"工具缺失"提示，
 * 而不是抛错白屏）。
 * @param {string} toolKey
 * @returns {import('vue').Component | null}
 */
export function getComponent(toolKey) {
  if (!toolKey) return null
  return TOOL_COMPONENTS[toolKey] || null
}

export default TOOL_COMPONENTS
