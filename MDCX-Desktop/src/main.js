import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import { useThemeStore } from './stores/theme'
import './styles/index.css'
import './styles/element-overrides.css'

const app = createApp(App)

// Pinia store
const pinia = createPinia()
app.use(pinia)

// 初始化主题（必须在 pinia 安装后、app.mount 前）
useThemeStore().initTheme()

// Element Plus
app.use(ElementPlus)

// Register all icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(router)

app.mount('#app')