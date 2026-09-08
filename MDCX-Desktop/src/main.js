import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import { useThemeStore } from './stores/theme'
import { isDesktop } from './config/flavor'
import { bootstrapDesktop } from './utils/bootstrap'
import './styles/index.css'
import './styles/element-overrides.css'

// 桌面端（消费型播放器）：强制影院暗色 + 载入影院风设计系统
// isDesktop 是编译期字面量，Web 构建中此分支被静态消除
if (isDesktop) {
  document.documentElement.classList.add('dark')
  import('./styles/cinema.css')
}

const app = createApp(App)

// Pinia store
const pinia = createPinia()
app.use(pinia)

// 初始化主题（必须在 pinia 安装后、app.mount 前）
useThemeStore().initTheme()

app.use(ElementPlus)

// Register all icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 桌面端：先探测后端 + 尝试可信 IP 免登录，再安装路由并挂载。
//
// 顺序至关重要：vue-router 在 app.use(router) 时就会**同步**发起首次导航，
// 若此时 token 还没写进 localStorage，守卫会直接把用户弹到登录页，
// 之后没有任何二次导航 —— 表现就是「打开 exe 停在登录页，什么都拿不到」。
bootstrapDesktop()
  .catch((e) => console.warn('[bootstrap] failed:', e))
  .finally(() => {
    app.use(router)
    app.mount('#app')
  })