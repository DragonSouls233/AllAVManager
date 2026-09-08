<template>
  <div
    class="osd-root"
    :class="{ 'is-hidden': !visible }"
    @mousemove="onActivity"
    @mouseleave="onLeave"
  >
    <!-- 顶部：标题 + 窗口控制 -->
    <div class="osd-top">
      <div class="osd-top-left">
        <span v-if="title" class="osd-title">{{ title }}</span>
        <span v-if="hwdec && hwdec !== 'no'" class="osd-badge" :title="`硬件解码：${hwdec}`">硬解 {{ hwdec }}</span>
      </div>
      <div class="osd-top-right">
        <button class="osd-icon-btn" title="全屏 (F)" @click="toggleFullscreen">
          <svg viewBox="0 0 16 16"><path d="M2 6V2h4M14 10v4h-4M14 6V2h-4M2 10v4h4"/></svg>
        </button>
        <button class="osd-icon-btn danger" title="退出播放 (Esc)" @click="exit">
          <svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg>
        </button>
      </div>
    </div>

    <!-- 中间空白：点击切换播放/暂停，鼠标事件默认穿透给 mpv -->
    <div class="osd-center" @click="togglePlay" @dblclick="toggleFullscreen"></div>

    <!-- 底部控制条 -->
    <div class="osd-bottom" @click.stop>
      <button class="osd-play" :title="state.pause ? '播放' : '暂停'" @click="togglePlay">
        <svg v-if="state.pause" viewBox="0 0 16 16"><path d="M4.5 2.5l8 5.5-8 5.5z"/></svg>
        <svg v-else viewBox="0 0 16 16"><rect x="4" y="2.5" width="3" height="11"/><rect x="9" y="2.5" width="3" height="11"/></svg>
      </button>

      <span class="osd-time">{{ fmt(state.timePos) }}</span>

      <input
        class="osd-seek"
        type="range"
        min="0"
        :max="Math.max(state.duration || 0, 1)"
        step="0.5"
        :value="state.timePos"
        @input="onSeekInput"
        @change="onSeekCommit"
      />

      <span class="osd-time">{{ fmt(state.duration) }}</span>

      <div class="osd-volume">
        <svg class="osd-vol-icon" viewBox="0 0 16 16"><path d="M3 6h2l3-3v10L5 10H3z"/><path d="M10.5 5.5a3.5 3.5 0 010 5"/></svg>
        <input
          class="osd-vol"
          type="range"
          min="0"
          max="100"
          :value="state.mute ? 0 : state.volume"
          @input="onVolume"
        />
      </div>

      <select class="osd-speed" :value="state.speed" @change="onSpeed">
        <option v-for="s in SPEEDS" :key="s" :value="s">{{ s }}×</option>
      </select>
    </div>

    <div v-if="!state.running && !state.error" class="osd-center-msg">正在启动 mpv…</div>
    <div v-if="state.error" class="osd-center-msg error">{{ state.error }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2]

const state = ref({
  running: false,
  pause: true,
  timePos: 0,
  duration: 0,
  volume: 100,
  mute: false,
  speed: 1,
  hwdec: '',
  error: ''
})

const visible = ref(true)
const title = ref('')
const hwdec = ref('')

let hideTimer = null
let unbindState = null
let seeking = false

function fmt(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m)
  return h > 0
    ? `${h}:${mm}:${String(ss).padStart(2, '0')}`
    : `${mm}:${String(ss).padStart(2, '0')}`
}

const api = () => (typeof window !== 'undefined' && window.electronAPI) || null

/** 鼠标活动 → 显示 OSD 并收回鼠标事件；静止 2.5s → 隐藏并把事件还给 mpv */
function onActivity() {
  if (!visible.value) {
    visible.value = true
    api()?.mpvOsdInteractive?.(true)
  }
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = setTimeout(hide, 2500)
}

function onLeave() {
  hide()
}

function hide() {
  if (seeking) return
  visible.value = false
  api()?.mpvOsdInteractive?.(false)
}

function togglePlay() {
  api()?.mpvSetProp?.('pause', !state.value.pause)
  onActivity()
}

function onSeekInput(e) {
  seeking = true
  state.value.timePos = Number(e.target.value)
  onActivity()
}

function onSeekCommit(e) {
  seeking = false
  api()?.mpvCommand?.(['seek', Number(e.target.value), 'absolute'])
  onActivity()
}

function onVolume(e) {
  const v = Number(e.target.value)
  api()?.mpvSetProp?.('volume', v)
  api()?.mpvSetProp?.('mute', v === 0)
  onActivity()
}

function onSpeed(e) {
  api()?.mpvSetProp?.('speed', Number(e.target.value))
  onActivity()
}

function toggleFullscreen() {
  api()?.mpvToggleFullscreen?.()
}

function exit() {
  api()?.mpvExit?.()
}

function onKey(e) {
  if (e.key === 'Escape') exit()
  else if (e.key === ' ') { e.preventDefault(); togglePlay() }
  else if (e.key === 'f' || e.key === 'F') toggleFullscreen()
  else if (e.key === 'ArrowLeft') api()?.mpvCommand?.(['seek', -5, 'relative'])
  else if (e.key === 'ArrowRight') api()?.mpvCommand?.(['seek', 5, 'relative'])
  onActivity()
}

onMounted(async () => {
  const a = api()
  unbindState = a?.onMpvState?.((s) => {
    state.value = { ...state.value, ...s }
    if (s.hwdec) hwdec.value = s.hwdec
    if (s.path) {
      const name = String(s.path).split(/[\\/]/).pop() || ''
      title.value = name.replace(/\.[^.]+$/, '')
    }
  })
  // 首次进入先拉一次状态，避免等 mpv 推第一个事件
  try {
    const s = await a?.mpvState?.()
    if (s) state.value = { ...state.value, ...s }
  } catch {
    /* 忽略 */
  }
  window.addEventListener('keydown', onKey)
  onActivity()
})

onBeforeUnmount(() => {
  if (hideTimer) clearTimeout(hideTimer)
  if (unbindState) unbindState()
  window.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
/* OSD 运行在独立透明窗口里，背景必须全透明 */
:global(html),
:global(body),
:global(#app) {
  background: transparent !important;
}

.osd-root {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
  opacity: 1;
  transition: opacity 0.18s;
  user-select: none;
}

.osd-root.is-hidden {
  opacity: 0;
}

.osd-root.is-hidden .osd-top,
.osd-root.is-hidden .osd-bottom {
  pointer-events: none;
}

.osd-top,
.osd-bottom {
  pointer-events: auto;
}

.osd-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: linear-gradient(180deg, rgba(0, 0, 0, 0.6), transparent);
}

.osd-top-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.osd-title {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
  max-width: 60vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.osd-badge {
  font-size: 11px;
  color: #7ee0b8;
  border: 1px solid rgba(126, 224, 184, 0.35);
  background: rgba(126, 224, 184, 0.12);
  padding: 1px 7px;
  border-radius: 999px;
  white-space: nowrap;
}

.osd-top-right {
  display: flex;
  gap: 6px;
}

.osd-icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  border: none;
  background: rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.osd-icon-btn svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: rgba(255, 255, 255, 0.85);
  stroke-width: 1.4;
  stroke-linecap: round;
}

.osd-icon-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.osd-icon-btn.danger:hover {
  background: #e81123;
}

.osd-center {
  flex: 1;
  pointer-events: auto;
  cursor: default;
}

.osd-center-msg {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  font-size: 13px;
  color: rgba(255, 255, 255, 0.65);
  background: rgba(0, 0, 0, 0.55);
  padding: 8px 16px;
  border-radius: 8px;
}

.osd-center-msg.error {
  color: #ff9b9b;
}

.osd-bottom {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px 14px;
  background: linear-gradient(0deg, rgba(0, 0, 0, 0.72), transparent);
}

.osd-play {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.14);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}

.osd-play svg {
  width: 14px;
  height: 14px;
  fill: #fff;
  stroke: none;
}

.osd-play:hover {
  background: rgba(255, 255, 255, 0.26);
}

.osd-time {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.75);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  min-width: 42px;
}

.osd-seek {
  flex: 1;
  min-width: 120px;
}

.osd-volume {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.osd-vol-icon {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: rgba(255, 255, 255, 0.8);
  stroke-width: 1.2;
  stroke-linecap: round;
}

.osd-vol {
  width: 78px;
}

.osd-speed {
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.12);
  border: none;
  color: #fff;
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 5px;
  cursor: pointer;
}

.osd-speed option {
  background: #1b1f27;
}

input[type='range'] {
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.25);
  outline: none;
  cursor: pointer;
}

input[type='range']::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  cursor: pointer;
}
</style>
