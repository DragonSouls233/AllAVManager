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
            outDir: 'dist-electron'
          }
        }
      }
    ]),
    renderer()
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
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