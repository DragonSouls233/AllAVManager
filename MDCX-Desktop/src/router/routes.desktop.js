// ============================================================
// 桌面端（消费型播放器）路由表
// 只有 5 个消费入口 + 详情 / 播放 / 设置 / 登录
// 所有管理运维页面（扫描 / 刮削 / 合并 / 日志 / 用户 …）一概不注册，
// 因此也不会被打进 exe。
// ============================================================
import CinemaLayout from '@/layouts/CinemaLayout.vue'

export const routes = [
  {
    path: '/login',
    name: 'Login',
    meta: { public: true },
    component: () => import('@/views/Login.vue')
  },
  {
    path: '/',
    component: CinemaLayout,
    redirect: '/library',
    children: [
      {
        path: 'library',
        name: 'Library',
        component: () => import('@/views/desktop/Library.vue'),
        meta: { title: '影片库', icon: 'Film' }
      },
      {
        path: 'categories',
        name: 'Categories',
        component: () => import('@/views/desktop/Categories.vue'),
        meta: { title: '类别', icon: 'PriceTag' }
      },
      {
        path: 'series',
        name: 'Series',
        component: () => import('@/views/desktop/Series.vue'),
        meta: { title: '系列', icon: 'Collection' }
      },
      {
        path: 'actors',
        name: 'Actors',
        component: () => import('@/views/desktop/Actors.vue'),
        meta: { title: '演员', icon: 'User' }
      },
      {
        path: 'actors/:id',
        name: 'ActorWorks',
        component: () => import('@/views/desktop/ActorWorks.vue'),
        meta: { title: '演员作品' }
      },
      {
        path: 'favorites',
        name: 'Favorites',
        component: () => import('@/views/desktop/Favorites.vue'),
        meta: { title: '喜好', icon: 'Star' }
      },
      {
        path: 'movie/:module/:id',
        name: 'MovieDetail',
        component: () => import('@/views/desktop/MovieDetail.vue'),
        meta: { title: '详情' }
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/desktop/Settings.vue'),
        meta: { title: '设置' }
      }
    ]
  },
  {
    // 播放器独占全屏，不套 CinemaLayout
    path: '/play/:id',
    name: 'Play',
    component: () => import('@/views/Play.vue')
  },
  {
    // 桌面端原生 mpv 播放器宿主：整页黑屏，mpv 经 --wid 嵌入并覆盖客户区
    path: '/mpv/:module/:id',
    name: 'MpvPlay',
    component: () => import('@/views/desktop/MpvStage.vue'),
    meta: { public: true }
  },
  {
    // 透明 OSD 浮层（独立置顶窗口），不套任何布局
    path: '/mpv-osd',
    name: 'MpvOsd',
    component: () => import('@/views/desktop/MpvOsd.vue'),
    meta: { public: true }
  },
  {
    // 桌面端未注册的路径一律回落到影片库
    // （兼容 mdcx:// 协议跳转、旧版收藏的 hash 路由）
    path: '/:pathMatch(.*)*',
    redirect: '/library'
  }
]
