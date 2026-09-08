import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 专用 Web 构建配置（不含 electron 插件，直接输出到 MDCX-Server/static）
// 使用方式: cd G:\MDCX\MDCX-Desktop ; node node_modules/vite/bin/vite.js build --config vite.config.web.js
export default defineConfig({
  base: './',
  root: '.',
  plugins: [vue()],
  // 构建期常量：web → 管理后台形态
  define: {
    __APP_FLAVOR__: JSON.stringify('web')
  },
  resolve: {
    // 顺序敏感：具体的路由表别名必须排在 '@' 之前
    alias: [
      { find: '@/router/routes', replacement: resolve(__dirname, 'src/router/routes.web.js') },
      { find: '@', replacement: resolve(__dirname, 'src') }
    ]
  },
  // 启用 public 目录，使 favicon.svg 随 Web 构建自动输出到 static/（修复 /favicon.svg 404）
  publicDir: 'public',
  build: {
    outDir: '../MDCX-Server/static',
    emptyOutDir: false,
    rollupOptions: {
      input: 'index.html'
    }
  }
})
