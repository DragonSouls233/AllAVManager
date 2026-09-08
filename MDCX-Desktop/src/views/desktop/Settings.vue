<template>
  <section>
    <div class="cinema-page-head">
      <h1 class="cinema-page-title">设置</h1>
    </div>
    <div class="cinema-settings">
      <div class="set-row">
        <div>
          <div class="set-label">服务器地址</div>
          <div class="set-desc">桌面端通过此地址读取数据与封面</div>
        </div>
        <el-input v-model="serverUrl" size="small" style="width: 260px" placeholder="http://192.168.10.110:8420" />
      </div>
      <div class="set-row">
        <div>
          <div class="set-label">NSFW 显示</div>
          <div class="set-desc">关闭后隐藏封面与敏感内容</div>
        </div>
        <el-switch v-model="nsfw" @change="applyNsfw" />
      </div>
      <div class="set-row">
        <div>
          <div class="set-label">关闭时最小化到托盘</div>
          <div class="set-desc">关闭后程序继续在后台运行；关闭此项则点 ✕ 直接退出</div>
        </div>
        <el-switch v-model="closeToTray" @change="onCloseToTray" />
      </div>
      <div class="set-row">
        <div>
          <div class="set-label">开机自启</div>
          <div class="set-desc">系统启动时自动运行 MDCX Player</div>
        </div>
        <el-switch v-model="autoLaunch" @change="onAutoLaunch" />
      </div>
      <div class="set-actions">
        <el-button size="small" type="primary" @click="save">保存服务器地址</el-button>
        <el-button size="small" @click="logout">退出登录</el-button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { setServerUrl } from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const serverUrl = ref(localStorage.getItem('serverUrl') || '')
const nsfw = ref(localStorage.getItem('mdcx_nsfw') !== '0')
const autoLaunch = ref(localStorage.getItem('mdcx_auto_launch') === '1')
const closeToTray = ref(true)

function applyNsfw() {
  const root = document.documentElement
  root.setAttribute('data-nsfw', nsfw.value ? 'off' : 'on')
  root.setAttribute('data-nsfw-hide-cover', nsfw.value ? '0' : '1')
  localStorage.setItem('mdcx_nsfw', nsfw.value ? '1' : '0')
}

function onAutoLaunch(val) {
  localStorage.setItem('mdcx_auto_launch', val ? '1' : '0')
  const api = window.electronAPI
  if (api && api.setAutoLaunch) api.setAutoLaunch(val).catch(() => {})
}

async function onCloseToTray(val) {
  const api = window.electronAPI
  if (api?.setDesktopPrefs) {
    try {
      await api.setDesktopPrefs({ close_to_tray: !!val })
      ElMessage.success(val ? '已开启：关闭窗口后最小化到托盘' : '已关闭：点 ✕ 将直接退出程序')
    } catch {
      ElMessage.warning('设置未生效')
    }
  }
}

function save() {
  const url = serverUrl.value.trim().replace(/\/+$/, '')
  if (!url) return
  setServerUrl(url)
  localStorage.setItem('serverUrl', url)
  ElMessage.success('已保存，正在重新加载…')
  setTimeout(() => window.location.reload(), 600)
}

function logout() {
  localStorage.removeItem('token')
  authStore.logout?.()
  router.push('/login')
}

onMounted(() => {
  const api = window.electronAPI
  if (api && api.getAutoLaunch) {
    api.getAutoLaunch().then(v => { autoLaunch.value = !!v }).catch(() => {})
  }
  if (api?.getDesktopPrefs) {
    api.getDesktopPrefs().then(p => {
      if (p && typeof p.close_to_tray === 'boolean') closeToTray.value = p.close_to_tray
    }).catch(() => {})
  }
})
</script>

<style scoped>
.cinema-settings {
  max-width: 620px;
  background: var(--cinema-1);
  border: 1px solid var(--cinema-line);
  border-radius: 12px;
  padding: 6px 18px 18px;
}
.set-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 0;
  border-bottom: 1px solid var(--cinema-line);
}
.set-label { font-size: 13.5px; color: var(--text-1); font-weight: 500; }
.set-desc { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
.set-actions { display: flex; gap: 10px; padding-top: 16px; }
</style>
