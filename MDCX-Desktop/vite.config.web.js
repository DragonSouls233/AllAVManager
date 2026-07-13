import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 专用 Web 构建配置（不含 electron 插件，直接输出到 MDCX-Server/static）
// 使用方式: cd G:\MDCX\MDCX-Desktop ; node node_modules/vite/bin/vite.js build --config vite.config.web.js
export default defineConfig({
  base: './',
  root: '.',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  // 禁用 public 目录扫描（favicon.svg 会手动保留）
  publicDir: false,
  build: {
    outDir: '../MDCX-Server/static',
    emptyOutDir: true,
    rollupOptions: {
      input: 'index.html'
    }
  }
})
