import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'
import { resolve } from 'path'

export default defineConfig({
  base: './',
  plugins: [
    vue(),
    electron([
      {
        entry: 'electron/main.js',
        onstart(options) {
          options.startup()
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            rollupOptions: {
              external: ['electron']
            }
          }
        }
      },
      {
        entry: 'electron/preload.js',
        onstart(options) {
          options.reload()
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            rollupOptions: {
              // Electron 33 加载 ESM preload 的要求：文件后缀必须是 .mjs，且窗口必须 sandbox:false
              // （沙箱渲染器的 preload 只支持 CommonJS；本项目 package.json "type":"module"，
              //  插件强制把 preload 输出为 ESM——若叫 .js/.cjs 且保持沙箱，加载会抛
              //  "Cannot use import statement outside a module" → window.electronAPI 永远 undefined）
              output: {
                entryFileNames: 'preload.mjs'
              }
            }
          }
        }
      }
    ]),
    renderer()
  ],
  // 构建期常量：desktop → 消费型播放器形态
  define: {
    __APP_FLAVOR__: JSON.stringify('desktop')
  },
  resolve: {
    // 顺序敏感：具体的路由表别名必须排在 '@' 之前
    alias: [
      { find: '@/router/routes', replacement: resolve(__dirname, 'src/router/routes.desktop.js') },
      { find: '@', replacement: resolve(__dirname, 'src') }
    ]
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8420',
        changeOrigin: true
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        // 代码分割:将第三方依赖拆分为独立 chunk,提升缓存命中率与首屏加载速度
        manualChunks: {
          // Vue 核心生态:vue / vue-router / pinia
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
          // Element Plus UI 库
          'vendor-element': ['element-plus'],
          // 通用工具库:axios / dayjs / @vueuse/core
          'vendor-utils': ['axios', 'dayjs', '@vueuse/core']
        }
      }
    }
  }
})