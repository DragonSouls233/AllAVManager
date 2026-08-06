import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    meta: { public: true },
    component: () => import('@/views/Login.vue')
  },
  {
    path: '/',
    component: () => import('@/views/Layout.vue'),
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
        name: 'UncensoredScrape',
        component: () => import('@/views/Crawlers.vue')
      },
      {
        path: 'uncensored/compare',
        name: 'UncensoredCompare',
        component: () => import('@/views/Compare.vue')
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
        path: 'jav/actor-merge',
        name: 'JavActorMerge',
        component: () => import('@/views/jav/ActorMerge.vue')
      },
      {
        path: 'jav/code-test',
        name: 'JavCodeTest',
        component: () => import('@/views/jav/CodeTest.vue')
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
        path: 'pornhub/actors/:id',
        name: 'PornhubActorDetail',
        component: () => import('@/views/ActorDetail.vue')
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

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach((to, from) => {
  const token = localStorage.getItem('token')
  // 无 token 访问受保护页面 → 跳转登录
  if (!to.meta.public && !token) {
    return { name: 'Login' }
  }
  // 已在登录页且无 token → 阻止一切离开登录页的导航
  if (from.name === 'Login' && !token && to.name !== 'Login') {
    return false
  }
  if (to.name === 'Login' && token) {
    return { name: 'Home' }
  }
})

// 暴露 router 实例给全局，供 axios 401 拦截器使用
window.__router = router

export default router
