/**
 * MDCX · IA 单一数据源（Phase 1）
 *
 * ⚠️ 本文件**禁止 import 任何 `.vue` 组件**。
 *    它会被 AppSidebar / AppTopbar（面包屑）/ CommandPalette / ToolsHub 四处引用，
 *    一旦引入组件，这 4 个 chunk 的依赖图会被连成一片。
 *
 * 提供四类数据 + 四个纯函数：
 *   NAV         5 个一级组（侧栏 / 面包屑 / 命令面板）
 *   MODULES     7 个内容模块（模块切换器 / 首页 pill / 计数键）
 *   TOOL_GROUPS 6 组 47 个工具（工具中心 Hub / 组页 / 常用工具）
 *   flattenNav / resolveActiveKey / resolveBreadcrumb / findToolByPath
 *
 * 依据 docs/redesign/ARCH-phase1.md §5。
 */

/* ============================================================
 * 7 个内容模块
 * ============================================================ */
export const MODULES = [
  { key: 'jav',        label: 'JAV 有码', emoji: '🎬', movies: '/jav/movies',        actors: '/jav/actors',        flag: 'jav',        toolEnabled: true  },
  { key: 'uncensored', label: 'JAV 无码', emoji: '🔓', movies: '/uncensored/movies', actors: '/uncensored/actors', flag: 'uncensored', toolEnabled: true  },
  { key: 'fc2',        label: 'FC2',      emoji: '📹', movies: '/fc2/movies',        actors: '/fc2/actors',        flag: 'fc2',        toolEnabled: true  },
  { key: 'chinese',    label: '国产',     emoji: '🇨🇳', movies: '/chinese/movies',    actors: '/chinese/actors',    flag: 'chinese',    toolEnabled: true  },
  { key: 'pornhub',    label: 'PORNHub',  emoji: '🌐', movies: '/pornhub/movies',    actors: '/pornhub/actors',    flag: 'pornhub',    toolEnabled: true  },
  { key: 'western',    label: '欧美',     emoji: '🌍', movies: '/western/movies',    actors: '/western/actors',    flag: 'western',    toolEnabled: true  },
  // 里番没有刮削/补丁工具，因此不进工具中心的模块切换器
  { key: 'anime',      label: '里番',     emoji: '📺', movies: '/anime',             actors: null,                 flag: 'anime',      toolEnabled: false },
]

/* ============================================================
 * 5 个一级组
 * ------------------------------------------------------------
 * kind: 'link'（直接跳转）| 'group'（可折叠组）
 * moduleFlag: 为真时，enabled[flag] === false 则整项不渲染
 * legacy: 旧路径，用于 ① 侧栏选中态 ② 面包屑 ③ 「旧入口」提示
 * ============================================================ */
export const NAV = [
  { key: 'home', label: '首页', icon: 'HomeFilled', kind: 'link', to: '/' },

  /* ---------- 媒体库：只放「看与管理内容」 ---------- */
  {
    key: 'library', label: '媒体库', icon: 'VideoCamera', kind: 'group', defaultOpen: false,
    children: [
      { key: 'jav',        label: 'JAV 有码', emoji: '🎬', to: '/jav/movies',        countKey: 'movies', moduleFlag: 'jav',        legacy: ['/jav', '/jav/browse', '/jav/categories', '/jav/series', '/jav/actors', '/jav/studios', '/jav/studio-merge', '/jav/actor-merge'] },
      { key: 'uncensored', label: 'JAV 无码', emoji: '🔓', to: '/uncensored/movies', countKey: 'movies', moduleFlag: 'uncensored', legacy: ['/uncensored/categories', '/uncensored/series', '/uncensored/actors'] },
      { key: 'fc2',        label: 'FC2',      emoji: '📹', to: '/fc2/movies',        countKey: 'movies', moduleFlag: 'fc2',        legacy: ['/fc2', '/fc2/series', '/fc2/actors'] },
      { key: 'chinese',    label: '国产',     emoji: '🇨🇳', to: '/chinese/movies',    countKey: 'movies', moduleFlag: 'chinese',    legacy: ['/chinese', '/chinese/actors'] },
      { key: 'pornhub',    label: 'PORNHub',  emoji: '🌐', to: '/pornhub/movies',    countKey: 'movies', moduleFlag: 'pornhub',    legacy: ['/pornhub', '/pornhub/actors', '/pornhub/nationalities'] },
      { key: 'western',    label: '欧美',     emoji: '🌍', to: '/western/movies',    countKey: 'movies', moduleFlag: 'western',    legacy: ['/western', '/western/actors', '/western/config'] },
      { key: 'anime',      label: '里番',     emoji: '📺', to: '/anime',             countKey: 'movies', moduleFlag: 'anime',      legacy: ['/anime/series', '/anime/favorites'] },
      { divider: true },
      { key: 'favorites',  label: '收藏夹',   icon: 'Star',      to: '/favorites' },
      { key: 'cover-wall', label: '封面墙',   icon: 'Grid',      to: '/cover-wall' },
      { key: 'playlists',  label: '播放列表', icon: 'VideoPlay', to: '/playlists' },
      { key: 'queues',     label: '观影队列', icon: 'List',      to: '/queues' },
      { key: 'actress',    label: '女优收藏', icon: 'Avatar',    to: '/actress-collection' },
    ],
  },

  /* ---------- 工具中心：主语是「一次批量动作」 ---------- */
  {
    key: 'tools', label: '工具中心', icon: 'Tools', kind: 'group', defaultOpen: false, to: '/tools',
    children: [
      // 侧栏直达 ToolsHub：否则用户只能从首页 Hero 按钮或面包屑进入
      { key: 'tools', label: '工具总览', icon: 'Grid', to: '/tools', desc: '6 组 47 个工具的总入口' },
      { divider: true },
      {
        key: 'scrape', label: '刮削与源', icon: 'Connection', to: '/tools/scrape',
        desc: '刮削、站点优先级、Cookie、刮削复核',
        legacy: ['/crawlers', '/jav/scrape', '/uncensored/scrape', '/fc2/scrape', '/chinese/scrape', '/pornhub/scrape', '/western/scrape'],
      },
      {
        key: 'fix', label: '补全与对比', icon: 'MagicStick', to: '/tools/fix',
        desc: '补丁、本地对比、NFO、多来源精选',
        legacy: ['/patch', '/jav/patch', '/uncensored/patch', '/fc2/patch', '/chinese/patch', '/pornhub/patch', '/western/patch',
                 '/compare', '/jav/compare', '/uncensored/compare', '/fc2/compare', '/pornhub/compare', '/western/compare',
                 '/compare-actors', '/jav/compare-actors', '/uncensored/compare-actors'],
      },
      { key: 'organize', label: '整理与入库', icon: 'FolderOpened', to: '/tools/organize', desc: '导入、整理、未识别、命名、扫描' },
      { key: 'health',   label: '去重与健康', icon: 'FirstAidKit',  to: '/tools/health',   desc: '重复番号、指纹、媒体健康、垃圾文件' },
      { key: 'download', label: '下载与网盘', icon: 'Download',     to: '/tools/download', desc: '下载器、115、CloudDrive2、WebDAV、STRM' },
      { key: 'system',   label: '系统与代理', icon: 'Monitor',      to: '/tools/system',   desc: '网络诊断、Xray、任务、日志、备份' },
    ],
  },

  /* ---------- 发现：只读、只出结论 ---------- */
  {
    key: 'discover', label: '发现', icon: 'DataAnalysis', kind: 'group', defaultOpen: false,
    children: [
      { key: 'top250',  label: '榜单 TOP250', icon: 'Trophy',     to: '/jav/top250' },
      { key: 'rec',     label: '智能推荐',    icon: 'Promotion',  to: '/recommendations' },
      { key: 'stats',   label: '统计总览',    icon: 'Histogram',  to: '/stats' },
      { key: 'report',  label: '观影报告',    icon: 'DataLine',   to: '/viewing-report' },
      { key: 'taste',   label: '口味画像',    icon: 'IceCream',   to: '/taste' },
      { key: 'graph',   label: '影片图谱',    icon: 'Share',      to: '/movie-graph' },
      { key: 'immerse', label: '沉浸浏览',    icon: 'FullScreen', to: '/immerse' },
    ],
  },

  /* ---------- 设置：配置型、低频（15 项，组内滚动） ---------- */
  {
    key: 'settings', label: '设置', icon: 'Setting', kind: 'group', defaultOpen: false,
    children: [
      { key: 'settings',  label: '系统设置',      icon: 'Setting',       to: '/settings' },
      { key: 'scan',      label: '扫描控制',      icon: 'Search',        to: '/scan-control' },
      { key: 'modules',   label: '模块管理',      icon: 'Grid',          to: '/modules' },
      { key: 'themes',    label: '主题外观',      icon: 'MagicStick',    to: '/themes' },
      { key: 'users',     label: '用户与权限',    icon: 'UserFilled',    to: '/users' },
      { key: 'plugins',   label: '插件系统',      icon: 'Box',           to: '/plugins' },
      { key: 'metatube',  label: 'Metatube 插件', icon: 'Connection',    to: '/metatube-plugin' },
      { key: 'emby',      label: 'Emby 兼容',     icon: 'Connection',    to: '/emby-config' },
      { key: 'tvbox',     label: 'TVBox',         icon: 'VideoCamera',   to: '/tvbox' },
      { key: 'mpv',       label: 'mpv 设置',      icon: 'Monitor',       to: '/mpv-settings' },
      { key: 'desktop',   label: '桌面设置',      icon: 'Platform',      to: '/desktop-settings' },
      { key: 'schema',    label: 'Schema 设置',   icon: 'Grid',          to: '/schema-settings' },
      { key: 'deploy',    label: '部署档位',      icon: 'Upload',        to: '/deploy' },
      { key: 'telegram',  label: 'Telegram Bot',  icon: 'ChatLineRound', to: '/telegram-bot' },
      { key: 'readonly',  label: '唯读来源',      icon: 'FolderOpened',  to: '/read-only' },
    ],
  },
]

/* ============================================================
 * 6 组 47 个工具（`tool` 即 TOOL_COMPONENTS 的键）
 * 重复归位原则：一个组件在工具中心只出现 1 次。
 * ============================================================ */
export const TOOL_GROUPS = [
  {
    key: 'scrape', label: '刮削与源', icon: 'Connection', to: '/tools/scrape',
    desc: '刮削、站点优先级、Cookie、刮削复核',
    tools: [
      { key: 'crawlers',       label: '刮削管理',        tool: 'crawlers',        moduleAware: true, legacy: ['/crawlers', '/jav/scrape', '/uncensored/scrape', '/fc2/scrape', '/chinese/scrape', '/pornhub/scrape', '/western/scrape'] },
      { key: 'site-priority',  label: '站点优先级',      tool: 'sitePriority',    legacy: ['/site-priority'] },
      { key: 'site-registry',  label: '站点注册表',      tool: 'siteRegistry',    legacy: ['/sites'] },
      { key: 'cookie-manager', label: 'Cookie 管理器',   tool: 'cookieManager',   legacy: ['/cookie-manager'] },
      { key: 'cookiecloud',    label: 'CookieCloud 同步', tool: 'cookieCloud',    legacy: ['/cookiecloud'] },
      { key: 'review',         label: '刮削复核',        tool: 'review',          legacy: ['/review'] },
      { key: 'gfriends',       label: '头像库（Gfriends）', tool: 'gfriends',     legacy: ['/gfriends'] },
    ],
  },
  {
    key: 'fix', label: '补全与对比', icon: 'MagicStick', to: '/tools/fix',
    desc: '补丁、本地对比、NFO、多来源精选',
    tools: [
      { key: 'patch',          label: '补丁刮削',       tool: 'patch',          moduleAware: true, legacy: ['/patch', '/jav/patch', '/uncensored/patch', '/fc2/patch', '/chinese/patch', '/pornhub/patch', '/western/patch'] },
      { key: 'compare',        label: '本地对比',       tool: 'compare',        legacy: ['/compare', '/jav/compare', '/uncensored/compare', '/fc2/compare', '/pornhub/compare', '/western/compare'] },
      { key: 'compare-actors', label: '对比演员',       tool: 'compareActors',  moduleAware: true, legacy: ['/compare-actors', '/jav/compare-actors', '/uncensored/compare-actors'] },
      { key: 'nfo-scrape',     label: 'NFO 免改名刮削', tool: 'nfoScrape',      legacy: ['/nfo-scrape'] },
      { key: 'source-merge',   label: '多来源数据精选', tool: 'sourceMerge',    legacy: ['/source-merge'] },
      { key: 'gap-fill',       label: '缺口体检与补全', tool: 'gapFill',        onlyModule: 'jav', legacy: ['/jav/gap-fill'] },
    ],
  },
  {
    key: 'organize', label: '整理与入库', icon: 'FolderOpened', to: '/tools/organize',
    desc: '导入、整理、未识别、命名、扫描',
    tools: [
      { key: 'import',             label: '批量导入',       tool: 'import',            legacy: ['/import'] },
      { key: 'file-organize',      label: '文件整理',       tool: 'fileOrganize',      legacy: ['/file-organize'] },
      { key: 'auto-organize',      label: '自动整理',       tool: 'autoOrganize',      legacy: ['/auto-organize'] },
      { key: 'unrecognized-files', label: '未识别文件',     tool: 'unrecognizedFiles', legacy: ['/unrecognized-files'] },
      { key: 'refresh-folders',    label: '文件夹刷新',     tool: 'refreshFolders',    legacy: ['/refresh-folders'] },
      { key: 'folder-check',       label: '文件夹归属',     tool: 'folderCheck',       legacy: ['/jav/folder-check'] },
      { key: 'naming-template',    label: '命名模板',       tool: 'namingTemplate',    legacy: ['/naming-template'] },
      { key: 'chinese-name-rules', label: '命名规范（国产）', tool: 'chineseNameRules', legacy: ['/chinese/name-rules'] },
      { key: 'tiers',              label: '分级治理',       tool: 'tiers',             legacy: ['/tiers'] },
      { key: 'workflows',          label: '工作流',         tool: 'workflows',         legacy: ['/workflows'] },
    ],
  },
  {
    key: 'health', label: '去重与健康', icon: 'FirstAidKit', to: '/tools/health',
    desc: '重复番号、指纹、媒体健康、垃圾文件',
    tools: [
      { key: 'duplicates',     label: '重复番号扫描', tool: 'duplicates',    legacy: ['/duplicates'] },
      { key: 'fingerprint',    label: '指纹去重',     tool: 'fingerprint',   legacy: ['/fingerprint'] },
      { key: 'media-health',   label: '媒体健康扫描', tool: 'mediaHealth',   legacy: ['/media-health'] },
      { key: 'junk-files',     label: '垃圾文件检测', tool: 'junkFiles',     legacy: ['/junk-files'] },
      { key: 'view-status',    label: '三态标记',     tool: 'viewStatus',    legacy: ['/view-status'] },
      { key: 'face-crop',      label: '人脸裁剪',     tool: 'faceCrop',      legacy: ['/face-crop'],     section: '图像质量' },
      { key: 'poster-enhance', label: '海报增强',     tool: 'posterEnhance', legacy: ['/poster-enhance'], section: '图像质量' },
    ],
  },
  {
    key: 'download', label: '下载与网盘', icon: 'Download', to: '/tools/download',
    desc: '下载器、115、CloudDrive2、WebDAV、STRM',
    tools: [
      { key: 'downloaders',      label: '下载器统一管理', tool: 'downloaders',     legacy: ['/downloaders'] },
      { key: 'download-manager', label: '下载任务',       tool: 'downloadManager', legacy: ['/download'] },
      { key: 'pan-115',          label: '115 网盘',       tool: 'pan115',          legacy: ['/pan-115'] },
      { key: 'cloud-drive2',     label: 'CloudDrive2',    tool: 'cloudDrive2',     legacy: ['/cloud-drive2'] },
      { key: 'webdav-import',    label: 'WebDAV 导入',    tool: 'webdavImport',    legacy: ['/webdav-import'] },
      { key: 'strm',             label: 'STRM 生成',      tool: 'strm',            legacy: ['/strm'] },
      { key: 'quality-goals',    label: '高清版目标',     tool: 'qualityGoals',    legacy: ['/quality-goals'] },
      { key: 'wants',            label: '想要清单',       tool: 'wants',           legacy: ['/wants'] },
    ],
  },
  {
    key: 'system', label: '系统与代理', icon: 'Monitor', to: '/tools/system',
    desc: '网络诊断、Xray、任务、日志、备份',
    tools: [
      { key: 'network-diag',  label: '网络诊断',      tool: 'networkDiag',  legacy: ['/network-diag'] },
      { key: 'proxy-xray',    label: '内置 Xray 代理', tool: 'proxyXray',   legacy: ['/proxy-xray'] },
      { key: 'jp-proxy',      label: '日本节点代理',  tool: 'jpProxy',      legacy: ['/proxy/jp'] },
      { key: 'system-status', label: '系统状态',      tool: 'systemStatus', legacy: ['/system-status'] },
      { key: 'tasks',         label: '任务管理',      tool: 'tasks',        legacy: ['/tasks'] },
      { key: 'logs',          label: '系统日志',      tool: 'logs',         legacy: ['/logs'] },
      { key: 'log-stream',    label: '实时日志流',    tool: 'logStream',    legacy: ['/log-stream'] },
      { key: 'webhooks',      label: 'Webhook 通知',  tool: 'webhooks',     legacy: ['/webhooks'] },
      { key: 'backup',        label: '自动备份',      tool: 'backup',       legacy: ['/backup'] },
    ],
  },
]

/* ============================================================
 * 不在菜单里的旧页面标题
 * ------------------------------------------------------------
 * 这些页面**保持原路由可访问、不进侧栏**（ARCH-phase1 §5.3 末注），
 * 只在面包屑兜底时用一次，避免顶栏出现 `/movies` 这种裸路径。
 * ============================================================ */
export const EXTRA_TITLES = {
  '/movies': '影片库',
  '/movie': '影片详情',
  '/play': '播放',
  '/actors': '演员库',
  '/tags': '标签管理',
  '/files': '文件管理',
  '/studios': '制片厂',
  '/subscriptions': '演员订阅',
  '/series-subscriptions': '系列订阅',
  '/jav/code-test': '番号提取测试',
  '/jav/leaderboard': 'AV 联盟榜单',
  '/jav/wikipedia': '维基女优',
  '/jav/play': '播放工具',
  '/onboarding': '新手引导',
  '/login': '登录',
}

/* ============================================================
 * 查询函数（纯函数，无副作用）
 * ============================================================ */

/**
 * 把 NAV 拍平成「可跳转叶子项」列表，供命令面板搜索 / 常用工具渲染。
 * @param {Array} [nav] 默认取 NAV
 * @returns {Array<{key:string,label:string,to:string,group:string,groupLabel:string,icon:string,desc:string,legacy:Array<string>}>}
 */
export function flattenNav(nav = NAV) {
  const out = []
  for (const item of nav) {
    if (!item || item.divider) continue
    if (item.kind === 'group') {
      for (const child of item.children || []) {
        if (!child || child.divider) continue
        out.push({
          key: child.key,
          label: child.label,
          to: child.to,
          group: item.key,
          groupLabel: item.label,
          icon: child.icon || item.icon,
          desc: child.desc || '',
          legacy: child.legacy || [],
        })
      }
    } else {
      out.push({
        key: item.key,
        label: item.label,
        to: item.to,
        group: '',
        groupLabel: '',
        icon: item.icon,
        desc: item.desc || '',
        legacy: item.legacy || [],
      })
    }
  }
  return out
}

/** 在某个一级组内按 key 找二级项 */
function findChildByKey(group, key) {
  if (!group || !group.children) return null
  return group.children.find((c) => c && !c.divider && c.key === key) || null
}

/**
 * 当前路径命中的 nav 二级项 key（含 legacy 旧路径）。
 * 命中不到时返回空字符串。
 * @param {string} path  route.path
 * @param {Object} [query] route.query（工具中心用它细化，只影响面包屑）
 * @returns {string}
 */
export function resolveActiveKey(path, query = {}) {
  if (!path || path === '/') return 'home'

  const clean = path.split('?')[0].replace(/\/+$/, '') || '/'

  // 1) 工具中心组页：/tools/{groupKey}
  if (clean === '/tools') return 'tools'
  if (clean.startsWith('/tools/')) {
    const seg = clean.slice('/tools/'.length).split('/')[0]
    const groupItem = NAV.find((n) => n.key === 'tools')
    if (groupItem && findChildByKey(groupItem, seg)) return seg
    return 'tools'
  }

  // 2) 精确匹配 to
  for (const item of NAV) {
    if (item.kind !== 'group') {
      if (item.to === clean) return item.key
      continue
    }
    for (const child of item.children || []) {
      if (!child || child.divider) continue
      if (child.to === clean) return child.key
    }
  }

  // 3) legacy 旧路径
  for (const item of NAV) {
    if (item.kind !== 'group') continue
    for (const child of item.children || []) {
      if (!child || child.divider) continue
      if (Array.isArray(child.legacy) && child.legacy.includes(clean)) return child.key
    }
  }

  // 4) 模块兜底：/jav/movies/123 之类的详情页归到模块本身
  const seg1 = clean.split('/')[1]
  if (seg1) {
    const library = NAV.find((n) => n.key === 'library')
    if (library && findChildByKey(library, seg1)) return seg1
  }

  return ''
}

/**
 * 旧路径 → { groupKey, toolKey, tool, group }。用于面包屑与「你正在旧入口」提示。
 * @param {string} path
 * @returns {{groupKey:string,toolKey:string,tool:Object,group:Object}|null}
 */
export function findToolByPath(path) {
  if (!path) return null
  const clean = path.split('?')[0].replace(/\/+$/, '') || '/'
  for (const group of TOOL_GROUPS) {
    for (const tool of group.tools) {
      if (Array.isArray(tool.legacy) && tool.legacy.includes(clean)) {
        return { groupKey: group.key, toolKey: tool.key, tool, group }
      }
    }
  }
  return null
}

/**
 * 面包屑：「首页 / 工具中心 / 补全与对比 / 补丁刮削」。
 * 最后一项不带 `to`（当前页不可点自己）。
 * @param {string} path
 * @param {Object} [query]
 * @returns {Array<{label:string,to?:string}>}
 */
export function resolveBreadcrumb(path, query = {}) {
  const trail = [{ label: '首页', to: '/' }]
  if (!path || path === '' || path === '/') return trail

  const clean = path.split('?')[0].replace(/\/+$/, '') || '/'

  if (clean === '/tools') {
    trail.push({ label: '工具中心' })
    return trail
  }

  const key = resolveActiveKey(clean, query)
  let groupItem = null
  let child = null
  for (const item of NAV) {
    if (item.kind !== 'group') continue
    const c = findChildByKey(item, key)
    if (c) { groupItem = item; child = c; break }
  }

  if (!groupItem || !child) {
    // 完全兜底：先查「不在菜单里的旧页面」标题，再退化成第一段路径
    const segs = clean.split('/').filter(Boolean)
    const fallback =
      EXTRA_TITLES[clean] ||
      (segs.length > 1 ? EXTRA_TITLES[`/${segs[0]}`] : '') ||
      segs[0] ||
      '首页'
    trail.push({ label: fallback })
    return trail
  }

  const firstChildTo = ((groupItem.children || []).find((c) => c && !c.divider) || {}).to
  trail.push({ label: groupItem.label, to: groupItem.to || firstChildTo })
  trail.push({ label: child.label, to: child.to })

  // 工具中心：再细化到具体工具
  if (groupItem.key === 'tools') {
    const group = TOOL_GROUPS.find((g) => g.key === child.key)
    let tool = null
    const qTool = typeof query.tool === 'string' ? query.tool : ''
    if (group && qTool) {
      tool = group.tools.find((t) => t.key === qTool || t.tool === qTool) || null
    }
    if (!tool) {
      const hit = findToolByPath(clean)
      if (hit && hit.groupKey === child.key) tool = hit.tool
    }
    if (tool) trail.push({ label: tool.label })
  }

  // 最后一项不可点
  const last = trail[trail.length - 1]
  if (last && last.to) delete last.to

  return trail
}

export default { NAV, MODULES, TOOL_GROUPS, EXTRA_TITLES, flattenNav, resolveActiveKey, resolveBreadcrumb, findToolByPath }
