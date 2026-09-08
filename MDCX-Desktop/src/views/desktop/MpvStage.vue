<template>
  <div class="mpv-stage">
    <div v-if="error" class="mpv-stage-error">
      <div class="mpv-stage-title">无法启动原生播放器</div>
      <div class="mpv-stage-desc">{{ error }}</div>
      <div class="mpv-stage-actions">
        <button class="mpv-btn" @click="launch">重试</button>
        <button class="mpv-btn ghost" @click="fallback">改用网页播放器</button>
      </div>
    </div>
    <div v-else class="mpv-stage-hint">
      {{ launching ? '正在启动 mpv…' : '播放结束，正在返回…' }}
      <span v-if="resumeSec > 0" class="mpv-stage-resume">检测到上次观看至 {{ fmtPos(resumeSec) }}，已续播</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getServerUrl } from '@/api'
import { getViewingHistory, recordPlay } from '@/api'

const route = useRoute()
const router = useRouter()

const error = ref('')
const launching = ref(true)
const resumeSec = ref(0)

const module = String(route.params.module || 'jav')
const id = Number(route.params.id)

let unbindExit = null
let unbindState = null
let reportTimer = null

// 最近一次 mpv 状态快照（由 onMpvState 推送刷新）
let lastState = { timePos: 0, duration: 0, pause: true, loaded: false, running: false }
// 最近上报时间（节流：>=10s 才真正 POST）
let lastReportAt = 0
// 已上报过"播放完成"，避免退出时重复
let completedReported = false

function fmtPos(sec) {
  const p = Math.round(Number(sec) || 0)
  const h = Math.floor(p / 3600)
  const m = Math.floor((p % 3600) / 60)
  const s = p % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

/** 查询该片最近一次未看完进度（续播点） */
async function fetchResumePosition() {
  try {
    const res = await getViewingHistory({ movie_id: id, module, limit: 5 })
    const items = res?.items || []
    // 取最近一条 未完成 且已开播(>3%) 未近结尾(<97%) 的记录
    const r = items.find((x) => !x.completed && (x.progress || 0) > 0.03 && (x.progress || 0) < 0.97)
    if (!r) return 0
    const pos = r.duration_watched || 0
    return Math.max(0, Math.floor(pos))
  } catch {
    return 0
  }
}

/** 上报观看进度（position=秒） */
async function report(completed = false) {
  const st = lastState
  if (!st.duration || st.duration <= 0) return
  const pos = Math.min(Math.max(0, st.timePos || 0), st.duration)
  const progress = pos / st.duration
  try {
    await recordPlay({
      movie_id: id,
      module,
      position: Math.floor(pos),
      duration: Math.floor(st.duration),
      progress: Number(progress.toFixed(4)),
      completed: completed || progress >= 0.97
    })
    completedReported = completedReported || completed || progress >= 0.97
    lastReportAt = Date.now()
  } catch {
    /* 上报失败不影响播放 */
  }
}

async function launch() {
  error.value = ''
  launching.value = true
  const api = window.electronAPI
  if (!api?.mpvStart) {
    error.value = '当前不在桌面端（mpv 仅在 MDCX 桌面客户端内可用）'
    launching.value = false
    return
  }

  const base = getServerUrl()
  if (!base) {
    error.value = '未配置服务器地址'
    launching.value = false
    return
  }

  // 直连后端 Range 流：mpv 自己发 Range 请求，不需要 ffmpeg 转码/切片
  const url = `${base}/api/v1/${module}/movies/${id}/play/file`

  // 续播策略：
  //  - 显式带 start（0=从头 / n=指定秒）→ 尊重调用方
  //  - 未带 start（海报 ▶ 直达）→ 自动查历史，有进度则续播
  let start = 0
  const qs = route.query.start
  if (qs !== undefined && qs !== null && qs !== '') {
    start = Math.max(0, Math.floor(Number(qs) || 0))
  } else {
    start = await fetchResumePosition()
  }
  resumeSec.value = start

  const result = await api.mpvStart({ url, start, module, id })
  if (result && result.ok === false) {
    error.value = result.error || '启动失败'
    launching.value = false
  }
}

function fallback() {
  router.replace(`/play/${route.params.id}`)
}

function onStateChange(st) {
  if (!st) return
  lastState = st
  // 播放自然结束（end-file / 到达片尾）→ 上报完成
  if (!st.loaded && st.duration > 0 && (st.timePos || 0) / st.duration >= 0.95 && !completedReported) {
    report(true)
  }
}

onMounted(() => {
  launch()
  unbindExit = window.electronAPI?.onMpvExit?.(() => {
    // 退出即上报一次最终进度（可能在暂停态）
    report(false)
    router.replace('/library')
  })
  unbindState = window.electronAPI?.onMpvState?.((st) => onStateChange(st))
  // 节流心跳：播放中每 15s 落一次进度
  reportTimer = setInterval(() => {
    const st = lastState
    if (!st.running || !st.loaded) return
    if (!st.pause && Date.now() - lastReportAt >= 10000) {
      report(false)
    }
  }, 15000)
})

onBeforeUnmount(() => {
  if (unbindExit) unbindExit()
  if (unbindState) unbindState()
  if (reportTimer) clearInterval(reportTimer)
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

.mpv-stage-resume {
  display: block;
  margin-top: 6px;
  color: rgba(0, 163, 255, 0.8);
  font-size: 12px;
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
