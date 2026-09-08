<template>
  <div class="mpv-stage">
    <div v-if="error" class="mpv-stage-error">
      <div class="mpv-stage-title">无法启动原生播放器</div>
      <div class="mpv-stage-desc">{{ error }}</div>
      <div class="mpv-stage-actions">
        <button class="mpv-btn" @click="retry">重试</button>
        <button class="mpv-btn ghost" @click="fallback">改用网页播放器</button>
      </div>
    </div>
    <div v-else class="mpv-stage-hint">正在启动 mpv…</div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getServerUrl } from '@/api'

const route = useRoute()
const router = useRouter()

const error = ref('')
let unbindExit = null

async function launch() {
  error.value = ''
  const api = window.electronAPI
  if (!api?.mpvStart) {
    error.value = '当前不在桌面端（mpv 仅在 MDCX 桌面客户端内可用）'
    return
  }

  const module = route.params.module || 'jav'
  const id = route.params.id
  const base = getServerUrl()
  if (!base) {
    error.value = '未配置服务器地址'
    return
  }

  // 直连后端 Range 流：mpv 自己发 Range 请求，不需要 ffmpeg 转码/切片
  const url = `${base}/api/v1/${module}/movies/${id}/play/file`
  const start = Number(route.query.start || 0)

  const result = await api.mpvStart({ url, start })
  if (result && result.ok === false) {
    error.value = result.error || '启动失败'
  }
}

function retry() {
  launch()
}

function fallback() {
  router.replace(`/play/${route.params.id}`)
}

onMounted(() => {
  launch()
  unbindExit = window.electronAPI?.onMpvExit?.(() => {
    router.replace('/library')
  })
})

onBeforeUnmount(() => {
  if (unbindExit) unbindExit()
})
</script>

<style scoped>
/* 这个页面只是 mpv 的嵌入宿主：mpv 画面会完全覆盖客户区，
   所以这里保持纯黑，任何 UI 都看不见（控制条在 OSD overlay 窗口里） */
.mpv-stage {
  height: calc(100vh - var(--titlebar-h, 0px));
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.45);
  font-size: 13px;
}

.mpv-stage-error {
  max-width: 520px;
  text-align: center;
}

.mpv-stage-title {
  font-size: 15px;
  color: #ff8b8b;
  margin-bottom: 8px;
}

.mpv-stage-desc {
  font-size: 12.5px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.6);
}

.mpv-stage-actions {
  margin-top: 16px;
  display: flex;
  gap: 10px;
  justify-content: center;
}

.mpv-btn {
  border: 1px solid rgba(255, 255, 255, 0.22);
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
}

.mpv-btn.ghost {
  background: transparent;
}
</style>
