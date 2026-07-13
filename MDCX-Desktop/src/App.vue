<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { onMounted } from 'vue'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { setServerUrl, checkServerConnection } from '@/api'

onMounted(async () => {
  const api = (typeof window !== 'undefined' && window.electronAPI) || null
  if (!api || !api.isElectron) return

  const saved = localStorage.getItem('serverUrl')
  if (saved) return

  try {
    const result = await api.detectBackend()
    if (result && result.ok) {
      setServerUrl(result.url)
      console.log(`[AutoDetect] backend found at ${result.url}, connected`)
    }
  } catch (e) {
    console.warn('[AutoDetect] backend detection failed:', e)
  }
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
</style>