import { createRouter, createWebHashHistory } from 'vue-router'
import { isDesktop } from '@/config/flavor'
// 构建期由 vite alias 物理替换为 routes.web.js 或 routes.desktop.js，
// 未选中的那份不进入依赖图（见 vite.config.js / vite.config.web.js 的 resolve.alias）
import { routes } from '@/router/routes'

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
    return { name: isDesktop ? 'Library' : 'Home' }
  }
})

// 暴露 router 实例给全局，供 axios 401 拦截器使用
window.__router = router

export default router
