import AdminLayout from '@/layouts/AdminLayout.vue'

// ============================================================
// Web 端（管理后台）全量路由
// 由 src/router/index.js 原样迁出，逻辑零改动。
// 桌面端构建时整份被 tree-shake 消除。
// ============================================================
export const routes = [
  {
    path: '/login',
    name: 'Login',
    meta: { public: true },
    component: () => import('@/views/Login.vue')
  },
  {
    path: '/',
    component: AdminLayout,
    children: [
      {
        path: '',
        name: 'Home',
        component: () => import('@/views/Home.vue')
      },
      {
        path: 'movies',
        name: 'Movies',
        component: () => import('@/views/Movies.vue')
      },
      {
        path: 'actors',
        name: 'Actors',
        component: () => import('@/views/Actors.vue')
      },
      {
        path: 'actors/:id',
        name: 'ActorDetail',
        component: () => import('@/views/ActorDetail.vue')
      },
      {
        path: 'play/:id',
        name: 'Play',
        component: () => import('@/views/Play.vue')
      },
      {
        path: 'movie/:id',
        name: 'MovieDetail',
        component: () => import('@/views/MovieDetail.vue')
      },
      {
        path: 'anime',
        name: 'AnimeMovies',
        component: () => import('@/views/AnimeMovies.vue')
      },
      {
        path: 'anime/series',
        name: 'AnimeSeries',
        component: () => import('@/views/AnimeSeries.vue')
      },
      {
        path: 'anime/favorites',
        name: 'AnimeFavorites',
        component: () => import('@/views/AnimeFavorites.vue'),
        meta: { title: '里番 · 我的喜好' }
      },
      {
        path: 'crawlers',
        name: 'Crawlers',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'compare',
        name: 'Compare',
        component: () => import('@/views/Compare.vue')
      },
      {
        path: 'compare-actors',
        name: 'CompareActors',
        component: () => import('@/views/CompareActors.vue')
      },
      {
        path: 'jav/actor-merge',
        name: 'ActorMerge',
        component: () => import('@/views/ActorMerge.vue')
      },
      {
        path: 'favorites',
        name: 'Favorites',
        component: () => import('@/views/Favorites.vue')
      },
      {
        path: 'fingerprint',
        name: 'Fingerprint',
        component: () => import('@/views/Fingerprint.vue')
      },
      {
        path: 'duplicates',
        name: 'Duplicates',
        component: () => import('@/views/Duplicates.vue'),
        meta: { title: '重复番号扫描' }
      },
      {
        path: 'media-health',
        name: 'MediaHealth',
        component: () => import('@/views/MediaHealth.vue'),
        meta: { title: '媒体健康扫描' }
      },
      {
        // 🔴 以下 7 条在拆分 routes.web/desktop 时漏迁：页面文件一直在 src/views 下，
        // 但没有任何路由引用 → 构建产物里没有对应 chunk，页面等于不存在。
        // 路径/name 一律沿用拆分前 src/router/index.js 的原始定义，恢复原访问地址。
        path: 'unrecognized-files',
        name: 'UnrecognizedFiles',
        component: () => import('@/views/UnrecognizedFiles.vue'),
        meta: { title: '未识别文件' }
      },
      {
        path: 'file-organize',
        name: 'FileOrganize',
        component: () => import('@/views/FileOrganize.vue'),
        meta: { title: '文件整理' }
      },
      {
        path: 'auto-organize',
        name: 'AutoOrganize',
        component: () => import('@/views/AutoOrganize.vue'),
        meta: { title: '自动整理' }
      },
      {
        path: 'refresh-folders',
        name: 'RefreshFolders',
        component: () => import('@/views/RefreshFolders.vue'),
        meta: { title: '刷新目录' }
      },
      {
        path: 'webdav-import',
        name: 'WebDAVImport',
        component: () => import('@/views/WebDAVImport.vue'),
        meta: { title: 'WebDAV 导入' }
      },
      {
        path: 'cloud-drive2',
        name: 'CloudDrive2',
        component: () => import('@/views/CloudDrive2.vue'),
        meta: { title: 'CloudDrive2 网盘' }
      },
      {
        path: 'pan-115',
        name: 'Pan115',
        component: () => import('@/views/Pan115.vue'),
        meta: { title: '115 网盘' }
      },
      {
        path: 'wants',
        name: 'Wants',
        component: () => import('@/views/Wants.vue'),
        meta: { title: '想要清单' }
      },
      {
        path: 'playlists',
        name: 'Playlists',
        component: () => import('@/views/Playlists.vue'),
        meta: { title: '播放列表' }
      },
      {
        path: 'patch',
        name: 'Patch',
        component: () => import('@/views/Patch.vue')
      },
      {
        path: 'import',
        name: 'Import',
        component: () => import('@/views/Import.vue')
      },
      {
        path: 'tags',
        name: 'Tags',
        component: () => import('@/views/Tags.vue')
      },
      {
        path: 'tiers',
        name: 'Tiers',
        component: () => import('@/views/Tiers.vue')
      },
      {
        path: 'log-stream',
        name: 'LogStream',
        component: () => import('@/views/LogStream.vue')
      },
      {
        path: 'network-diag',
        name: 'NetworkDiag',
        component: () => import('@/views/NetworkDiag.vue')
      },
      {
        path: 'proxy-xray',
        name: 'ProxyXray',
        component: () => import('@/views/ProxyXray.vue')
      },
      {
        path: 'face-crop',
        name: 'FaceCrop',
        component: () => import('@/views/FaceCrop.vue')
      },
      {
        path: 'site-priority',
        name: 'SitePriority',
        component: () => import('@/views/SitePriority.vue')
      },
      {
        path: 'naming-template',
        name: 'NamingTemplate',
        component: () => import('@/views/NamingTemplate.vue')
      },
      {
        path: 'emby-config',
        name: 'EmbyConfig',
        component: () => import('@/views/EmbyConfig.vue')
      },
      {
        path: 'strm',
        name: 'Strm',
        component: () => import('@/views/Strm.vue')
      },
      {
        path: 'desktop-settings',
        name: 'DesktopSettings',
        component: () => import('@/views/DesktopSettings.vue')
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('@/views/Tasks.vue')
      },
      {
        path: 'proxy/jp',
        name: 'JpProxy',
        component: () => import('@/views/proxy/JpProxy.vue'),
        meta: { title: '日本节点代理' }
      },
      {
        path: 'plugins',
        name: 'Plugins',
        component: () => import('@/views/Plugins.vue')
      },
      {
        path: 'webhooks',
        name: 'Webhooks',
        component: () => import('@/views/Webhooks.vue')
      },
      {
        path: 'subscriptions',
        name: 'Subscriptions',
        component: () => import('@/views/Subscriptions.vue')
      },
      {
        path: 'viewing-report',
        name: 'ViewingReport',
        component: () => import('@/views/ViewingReport.vue')
      },
      // 🔴 2026-10-26：Peach 风四大跨模块功能（观影队列 / 刮削复核 / 高清版目标 / 口味画像）。
      //    均为跨模块工具，挂在「工具与服务」分组，不归属任何单一模块。
      {
        path: 'queues',
        name: 'Queues',
        component: () => import('@/views/Queue.vue'),
        meta: { title: '观影队列' }
      },
      {
        path: 'review',
        name: 'Review',
        component: () => import('@/views/Review.vue'),
        meta: { title: '刮削复核' }
      },
      {
        path: 'quality-goals',
        name: 'QualityGoals',
        component: () => import('@/views/QualityGoals.vue'),
        meta: { title: '高清版目标' }
      },
      {
        path: 'taste',
        name: 'Taste',
        component: () => import('@/views/Taste.vue'),
        meta: { title: '口味画像' }
      },
      // 🔴 2026-10-27：Peach 统计总览（消费 /stats/* 现有接口）
      {
        path: 'stats',
        name: 'Stats',
        component: () => import('@/views/Stats.vue'),
        meta: { title: '统计总览' }
      },
      // 🔴 2026-10-27：Peach 沉浸浏览（全屏逐片，纯前端）
      {
        path: 'immerse',
        name: 'Immerse',
        component: () => import('@/views/Immerse.vue'),
        meta: { title: '沉浸浏览' }
      },
      // 🔴 2026-10-27：Peach 垃圾文件检测（样本片/预告/广告/系统垃圾）
      {
        path: 'junk-files',
        name: 'JunkFiles',
        component: () => import('@/views/JunkFiles.vue'),
        meta: { title: '垃圾文件检测' }
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/Users.vue')
      },
      {
        path: 'telegram-bot',
        name: 'TelegramBot',
        component: () => import('@/views/TelegramBot.vue')
      },
      {
        path: 'view-status',
        name: 'ViewStatus',
        component: () => import('@/views/ViewStatus.vue')
      },
      {
        path: 'cookiecloud',
        name: 'CookieCloud',
        component: () => import('@/views/CookieCloud.vue')
      },
      {
        path: 'cookie-manager',
        name: 'CookieManager',
        component: () => import('@/views/CookieManager.vue'),
        meta: { title: 'Cookie 管理器' }
      },
      {
        path: 'gfriends',
        name: 'Gfriends',
        component: () => import('@/views/Gfriends.vue')
      },
      {
        path: 'metatube-plugin',
        name: 'MetatubePlugin',
        component: () => import('@/views/MetatubePlugin.vue')
      },
      {
        path: 'tvbox',
        name: 'Tvbox',
        component: () => import('@/views/Tvbox.vue')
      },
      {
        path: 'downloaders',
        name: 'Downloaders',
        component: () => import('@/views/Downloaders.vue')
      },
      {
        path: 'cover-wall',
        name: 'CoverWall',
        component: () => import('@/views/CoverWall.vue'),
        meta: { title: '封面墙' }
      },
      {
        path: 'actress-collection',
        name: 'ActressCollection',
        component: () => import('@/views/ActressCollection.vue'),
        meta: { title: '女优收藏' }
      },
      {
        path: 'read-only',
        name: 'ReadOnly',
        component: () => import('@/views/ReadOnlyManager.vue'),
        meta: { title: '唯读来源' }
      },
      {
        path: 'themes',
        name: 'Themes',
        component: () => import('@/views/Themes.vue')
      },
      {
        path: 'schema-settings',
        name: 'SchemaSettings',
        component: () => import('@/views/SchemaSettings.vue')
      },
      {
        path: 'deploy',
        name: 'Deploy',
        component: () => import('@/views/Deploy.vue')
      },
      {
        path: 'backup',
        name: 'Backup',
        component: () => import('@/views/Backup.vue')
      },
      {
        path: 'logs',
        name: 'Logs',
        component: () => import('@/views/Logs.vue')
      },
      {
        path: 'mpv-settings',
        name: 'MpvSettings',
        component: () => import('@/views/MpvSettings.vue')
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/Settings.vue')
      },
      {
        path: 'poster-enhance',
        name: 'PosterEnhance',
        component: () => import('@/views/PosterEnhance.vue')
      },
      {
        path: 'series-subscriptions',
        name: 'SeriesSubscriptions',
        component: () => import('@/views/SeriesSubscriptions.vue')
      },
      {
        path: 'movie-graph',
        name: 'MovieGraph',
        component: () => import('@/views/MovieGraph.vue')
      },
      {
        path: 'recommendations',
        name: 'Recommendations',
        component: () => import('@/views/Recommendations.vue')
      },
      {
        path: 'nfo-scrape',
        name: 'NfoScrape',
        component: () => import('@/views/NfoScrape.vue')
      },
      {
        path: 'workflows',
        name: 'Workflows',
        component: () => import('@/views/Workflows.vue')
      },
      {
        path: 'studios',
        name: 'Studios',
        component: () => import('@/views/Studios.vue')
      },
      {
        path: 'files',
        name: 'Files',
        component: () => import('@/views/Files.vue')
      },
      {
        path: 'scan-control',
        name: 'ScanControl',
        component: () => import('@/views/ScanControl.vue'),
        meta: { title: '扫描控制', icon: 'Search' }
      },
      {
        path: 'system-status',
        name: 'SystemStatus',
        component: () => import('@/views/SystemStatus.vue')
      },
      {
        path: 'source-merge',
        name: 'SourceMerge',
        component: () => import('@/views/SourceMerge.vue')
      },
      {
        path: 'chinese',
        name: 'Chinese',
        component: () => import('@/views/chinese/Movies.vue')
      },
      {
        path: 'chinese/movies',
        name: 'ChineseMovies',
        component: () => import('@/views/chinese/Movies.vue')
      },
      {
        path: 'chinese/movies/:id',
        name: 'ChineseMovieDetail',
        component: () => import('@/views/MovieDetail.vue')
      },
      {
        path: 'chinese/actors',
        name: 'ChineseActors',
        component: () => import('@/views/chinese/Actors.vue')
      },
      {
        path: 'chinese/actors/:id',
        name: 'ChineseActorDetail',
        component: () => import('@/views/ActorDetail.vue')
      },
      {
        path: 'chinese/name-rules',
        name: 'ChineseNameRules',
        component: () => import('@/views/chinese/NameRules.vue')
      },
      {
        path: 'chinese/scrape',
        name: 'ChineseScrape',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'chinese/patch',
        name: 'ChinesePatch',
        component: () => import('@/views/chinese/Patch.vue')
      },
      {
        path: 'fc2',
        name: 'Fc2',
        component: () => import('@/views/fc2/Movies.vue')
      },
      {
        path: 'fc2/movies',
        name: 'Fc2Movies',
        component: () => import('@/views/fc2/Movies.vue')
      },
      {
        path: 'fc2/movies/:id',
        name: 'Fc2MovieDetail',
        component: () => import('@/views/MovieDetail.vue')
      },
      {
        path: 'fc2/actors',
        name: 'Fc2Actors',
        component: () => import('@/views/fc2/Actors.vue')
      },
      {
        path: 'fc2/actors/:id',
        name: 'Fc2ActorDetail',
        component: () => import('@/views/ActorDetail.vue')
      },
      {
        path: 'fc2/scrape',
        name: 'Fc2Scrape',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'fc2/compare',
        name: 'Fc2Compare',
        component: () => import('@/views/Compare.vue')
      },
      {
        path: 'fc2/patch',
        name: 'Fc2Patch',
        component: () => import('@/views/Patch.vue')
      },
      {
        path: 'uncensored/scrape',
        name: 'UncensoredScrape',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'uncensored/categories',
        name: 'UncensoredCategories',
        component: () => import('@/views/Category.vue'),
        meta: { title: 'JAV 无码 · 类别' }
      },
      {
        path: 'uncensored/movies',
        name: 'UncensoredMovies',
        component: () => import('@/views/uncensored/Movies.vue')
      },
      {
        path: 'uncensored/movies/:id',
        name: 'UncensoredMovieDetail',
        component: () => import('@/views/MovieDetail.vue')
      },
      {
        path: 'uncensored/actors',
        name: 'UncensoredActors',
        component: () => import('@/views/uncensored/Actors.vue')
      },
      {
        path: 'uncensored/actors/:id',
        name: 'UncensoredActorDetail',
        component: () => import('@/views/ActorDetail.vue')
      },
      {
        path: 'uncensored',
        redirect: { name: 'UncensoredScrape' }
      },
      {
        path: 'uncensored/compare',
        name: 'UncensoredCompare',
        component: () => import('@/views/Compare.vue')
      },
      {
        path: 'uncensored/compare-actors',
        name: 'UncensoredCompareActors',
        component: () => import('@/views/CompareActors.vue')
      },
      {
        path: 'uncensored/patch',
        name: 'UncensoredPatch',
        component: () => import('@/views/Patch.vue')
      },
      {
        path: 'jav',
        name: 'Jav',
        component: () => import('@/views/jav/Movies.vue')
      },
      {
        path: 'jav/movies',
        name: 'JavMovies',
        component: () => import('@/views/jav/Movies.vue')
      },
      {
        path: 'jav/movies/:id',
        name: 'JavMovieDetail',
        component: () => import('@/views/MovieDetail.vue')
      },
      {
        // 2026-10-26：新增 Peach 风浏览页（海报墙 + 悬停预览 + 点击即播），
        // 与 jav/movies 管理视图并存，只做「看」、不挂写操作。
        path: 'jav/browse',
        name: 'JavBrowse',
        component: () => import('@/views/jav/Browse.vue')
      },
      {
        path: 'jav/actors',
        name: 'JavActors',
        component: () => import('@/views/jav/Actors.vue')
      },
      {
        path: 'jav/actors/:id',
        name: 'JavActorDetail',
        component: () => import('@/views/ActorDetail.vue')
      },
      {
        path: 'jav/folder-check',
        name: 'JavFolderCheck',
        component: () => import('@/views/jav/FolderCheck.vue'),
        meta: { title: 'JAV 有码 · 文件夹归属' }
      },
      {
        path: 'jav/studios',
        name: 'JavStudios',
        component: () => import('@/views/Studios.vue')
      },
      {
        path: 'jav/studio-merge',
        name: 'JavStudioMerge',
        component: () => import('@/views/StudioMerge.vue')
      },
      {
        path: 'jav/scrape',
        name: 'JavScrape',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'jav/compare',
        name: 'JavCompare',
        component: () => import('@/views/Compare.vue')
      },
      {
        path: 'jav/compare-actors',
        name: 'JavCompareActors',
        component: () => import('@/views/CompareActors.vue')
      },
      {
        path: 'jav/patch',
        name: 'JavPatch',
        component: () => import('@/views/Patch.vue')
      },
      {
        path: 'jav/play',
        name: 'JavPlay',
        component: () => import('@/views/MpvSettings.vue')
      },
      {
        path: 'jav/code-test',
        name: 'JavCodeTest',
        component: () => import('@/views/jav/CodeTest.vue')
      },
      {
        path: 'jav/gap-fill',
        name: 'JavGapFill',
        component: () => import('@/views/jav/GapFill.vue'),
        meta: { title: 'JAV 有码 · 缺口体检与补全' }
      },
      {
        path: 'jav/leaderboard',
        name: 'JavLeaderboard',
        component: () => import('@/views/jav/Leaderboard.vue'),
        meta: { title: 'JAV 有码 · AV联盟榜单' }
      },
      {
        // 🔴 2026-10-20：TOP250 已是跨 4 模块（JAV有码/无码/欧美/FC2）的收录体检，
        //    菜单归属移到独立「榜单」分组（见 AdminLayout.vue），但**路由路径刻意不变**，
        //    以免旧书签/外部链接 404。
        path: 'jav/top250',
        name: 'JavTop250',
        component: () => import('@/views/jav/Top250.vue'),
        meta: { title: '榜单 · TOP 250 收录体检' }
      },
      {
        path: 'jav/wikipedia',
        name: 'JavWikipediaActresses',
        component: () => import('@/views/jav/WikipediaActresses.vue'),
        meta: { title: 'JAV 有码 · 维基女优' }
      },
      {
        path: 'jav/categories',
        name: 'JavCategories',
        component: () => import('@/views/Category.vue'),
        meta: { title: 'JAV 有码 · 类别' }
      },
      {
        path: 'jav/series',
        name: 'JavSeries',
        component: () => import('@/views/jav/Series.vue'),
        props: { module: 'jav' },
        meta: { title: 'JAV 有码 · 系列' }
      },
      {
        path: 'fc2/series',
        name: 'Fc2Series',
        component: () => import('@/views/jav/Series.vue'),
        props: { module: 'fc2' },
        meta: { title: 'FC2 · 系列' }
      },
      {
        path: 'uncensored/series',
        name: 'UncensoredSeries',
        component: () => import('@/views/jav/Series.vue'),
        props: { module: 'uncensored' },
        meta: { title: 'JAV 无码 · 系列' }
      },
      {
        path: 'western/series',
        name: 'WesternSeries',
        component: () => import('@/views/jav/Series.vue'),
        props: { module: 'western' },
        meta: { title: '欧美 · 系列' }
      },
      {
        path: 'pornhub',
        name: 'Pornhub',
        component: () => import('@/views/pornhub/Movies.vue')
      },
      {
        path: 'pornhub/movies',
        name: 'PornhubMovies',
        component: () => import('@/views/pornhub/Movies.vue')
      },
      {
        path: 'pornhub/movies/:id',
        name: 'PornhubMovieDetail',
        component: () => import('@/views/MovieDetail.vue')
      },
      {
        path: 'pornhub/actors',
        name: 'PornhubActors',
        component: () => import('@/views/pornhub/Actors.vue')
      },
      {
        path: 'pornhub/nationalities',
        name: 'PornhubNationalities',
        component: () => import('@/views/pornhub/Nationalities.vue'),
        meta: { title: 'PORNHUB · 国籍' }
      },
      {
        path: 'pornhub/actors/:id',
        name: 'PornhubActorDetail',
        // 🔴 必须用 pornhub 专属详情页：通用 ActorDetail.vue 在 onMounted 里会调
        // getActorTags(id)（不带 module=pornhub）→ GET /actors/{id}/tags 落到 JAV 库
        // → 404 "演员不存在"。专属页只用 /pornhub/actors/{id} 与 /pornhub/actors/{id}/movies，
        // 不会跨模块误查，也符合"PORNHUB 工具只放 PORNHUB 模块"的约定。
        component: () => import('@/views/pornhub/ActorDetail.vue')
      },
      {
        path: 'pornhub/scrape',
        name: 'PornhubScrape',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'pornhub/compare',
        name: 'PornhubCompare',
        component: () => import('@/views/Compare.vue')
      },
      {
        path: 'pornhub/patch',
        name: 'PornhubPatch',
        component: () => import('@/views/Patch.vue')
      },
      {
        path: 'western',
        name: 'Western',
        component: () => import('@/views/western/Movies.vue')
      },
      {
        path: 'western/movies',
        name: 'WesternMovies',
        component: () => import('@/views/western/Movies.vue')
      },
      {
        path: 'western/movies/:id',
        name: 'WesternMovieDetail',
        component: () => import('@/views/MovieDetail.vue')
      },
      {
        path: 'western/actors',
        name: 'WesternActors',
        component: () => import('@/views/western/Actors.vue')
      },
      {
        path: 'western/actors/:id',
        name: 'WesternActorDetail',
        component: () => import('@/views/ActorDetail.vue')
      },
      {
        path: 'western/scrape',
        name: 'WesternScrape',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'western/compare',
        name: 'WesternCompare',
        component: () => import('@/views/Compare.vue')
      },
      {
        path: 'western/patch',
        name: 'WesternPatch',
        component: () => import('@/views/Patch.vue')
      },
      {
        path: 'western/config',
        name: 'WesternConfig',
        component: () => import('@/views/western/Config.vue')
      },
      {
        path: 'download',
        name: 'DownloadManager',
        component: () => import('@/views/download/DownloadManager.vue')
      },
      {
        path: 'sites',
        name: 'SiteRegistry',
        component: () => import('@/views/sites/SiteRegistry.vue')
      },
      {
        path: 'modules',
        name: 'Modules',
        component: () => import('@/views/modules/ModuleManager.vue')
      },
      {
        path: 'onboarding',
        name: 'Onboarding',
        meta: { public: true },
        component: () => import('@/views/Onboarding.vue')
      }
    ]
  }
]

// 兼容旧引用名
export const webRoutes = routes
