import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 专用 Web 构建配置（不含 electron 插件，直接输出到 MDCX-Server/static）
// 使用方式: cd G:\MDCX\MDCX-Desktop ; node node_modules/vite/bin/vite.js build --config vite.config.web.js
//
// 🔴 base 保持 './'（相对路径），不要改成 '/'：
//    本项目路由是 **hash 模式**（src/router/index.js: createWebHashHistory），
//    真实地址形如 http://host/#/jav/browse —— 浏览器加载 index.html 的路径始终是根 '/'，
//    相对 './assets/xxx.js' 正好解析成 '/assets/xxx.js'，是正确的。
//    保持相对还多一层好处：若把 static 挂在子路径下（如 /mdcx/）仍能工作，绝对路径反而 404。
//    ⚠️ 反过来讲：**不要用 http://host/jav/browse 这种无 hash 的地址深链/刷新**——
//    那会让后端把 index.html 吐在 /jav/browse 路径上，相对资源变成 /jav/assets/…
//    → 返回 text/html → 浏览器拒绝执行 module script → 白屏。正确写法是 /#/jav/browse。
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
