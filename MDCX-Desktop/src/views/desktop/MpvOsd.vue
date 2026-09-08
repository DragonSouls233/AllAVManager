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
        <span v-if="abLoopOn" class="osd-badge ab" title="AB 循环已开启（再按 ] 关闭）">AB 循环</span>
        <span v-if="hwdec && hwdec !== 'no'" class="osd-badge" :title="`硬件解码：${hwdec}`">硬解 {{ hwdec }}</span>
      </div>
      <div class="osd-top-right">
        <button class="osd-icon-btn" title="快捷键 (?): 查看全部" @click="toggleHelp">
          <svg viewBox="0 0 16 16"><path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM8 5.5c-.9 0-1.5.5-1.5 1.2M8 11v-2"/></svg>
        </button>
        <button class="osd-icon-btn" title="全屏 (F)" @click="toggleFullscreen">
          <svg viewBox="0 0 16 16"><path d="M2 6V2h4M14 10v4h-4M14 6V2h-4M2 10v4h4"/></svg>
        </button>
        <button class="osd-icon-btn danger" title="退出播放 (Esc)" @click="exit">
          <svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg>
        </button>
      </div>
    </div>

    <!-- 快捷键帮助浮层 -->
    <div v-if="showHelp" class="osd-help" @click.stop="showHelp = false">
      <div class="osd-help-title">快捷键</div>
      <div class="osd-help-grid">
        <template v-for="k in SHORTCUTS" :key="k.keys">
          <span class="osd-help-keys">{{ k.keys }}</span>
          <span class="osd-help-desc">{{ k.desc }}</span>
        </template>
      </div>
      <div class="osd-help-hint">再次按 ? 或点击空白关闭</div>
    </div>

    <!-- 居中瞬时提示（音量/AB/跳转反馈） -->
    <div v-if="toast" class="osd-toast">{{ toast }}</div>

    <!-- 中间空白：点击切换播放/暂停，鼠标事件默认穿透给 mpv -->
    <div class="osd-center" @click="togglePlay" @dblclick="toggleFullscreen"></div>

    <!-- 底部控制条 -->
    <div class="osd-bottom" @click.stop>
      <button class="osd-play" :title="state.pause ? '播放' : '暂停'" @click="togglePlay">
        <svg v-if="state.pause" viewBox="0 0 16 16"><path d="M4.5 2.5l8 5.5-8 5.5z"/></svg>
        <svg v-else viewBox="0 0 16 16"><rect x="4" y="2.5" width="3" height="11"/><rect x="9" y="2.5" width="3" height="11"/></svg>
      </button>

      <span class="osd-time">{{ fmt(state.timePos) }}</span>

      <!-- 进度条：底层分段着色 + hover 预览，原生 range 负责拖动 -->
      <div
        ref="seekWrap"
        class="osd-seek-wrap"
        @mousemove="onBarMove"
        @mouseleave="hoverPct = -1"
      >
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
        <!-- 轨道底色 -->
        <div class="seek-base" />
        <!-- 章节分段着色 -->
        <div v-if="chapterSegs.length" class="seek-chapters">
          <div
            v-for="(sg, i) in chapterSegs"
            :key="`sg-${i}`"
            class="seek-seg"
            :class="{ alt: i % 2 === 1 }"
            :style="{ left: sg.pct0 + '%', width: sg.pct1 - sg.pct0 + '%' }"
            :title="sg.title"
          />
        </div>
        <!-- 已播进度 -->
        <div class="seek-fill" :style="{ width: playedPct + '%' }" />
        <!-- hover 预览（缩略图 + 时间 + 章节名） -->
        <div
          v-if="hoverPct >= 0 && state.duration > 0"
          class="seek-hover"
          :style="{ left: hoverLeftPx + 'px' }"
        >
          <div v-if="sprite && hoverThumb" class="sh-thumb" :style="thumbBgStyle" />
          <div class="sh-meta">
            <span class="sh-time">{{ fmt(hoverTime) }}</span>
            <span v-if="hoverChapter" class="sh-chapter">{{ hoverChapter }}</span>
          </div>
          <i class="sh-caret" />
        </div>
      </div>

      <span class="osd-time">{{ fmt(state.duration) }}</span>

      <div class="osd-volume">
        <svg v-if="state.mute" class="osd-vol-icon vol-btn" viewBox="0 0 16 16" @click="toggleMute">
          <path d="M3 6h2l3-3v10L5 10H3zM10 6.5l4 3M14 6.5l-4 3" />
        </svg>
        <svg v-else class="osd-vol-icon vol-btn" viewBox="0 0 16 16" @click="toggleMute">
          <path d="M3 6h2l3-3v10L5 10H3z" /><path d="M10.5 5.5a3.5 3.5 0 010 5" />
        </svg>
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
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { getPlayerConfig, getServerUrl } from '@/api'

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2]

const SHORTCUTS = [
  { keys: 'Esc', desc: '退出播放' },
  { keys: 'Space', desc: '播放 / 暂停' },
  { keys: 'F', desc: '全屏切换' },
  { keys: '← / →', desc: '后退 / 快进 5 秒' },
  { keys: '↑ / ↓', desc: '音量 +5 / -5' },
  { keys: 'M', desc: '静音切换' },
  { keys: '[', desc: '设 A 点（AB 循环起点）' },
  { keys: ']', desc: '设 B 点开启循环 / 再按关闭' },
  { keys: '0-9', desc: '跳转到 0%–90%' },
  { keys: '?', desc: '显示 / 隐藏本帮助' }
]

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
const showHelp = ref(false)
const toast = ref('')
const abA = ref(null) // AB 循环 A 点（秒）
const abLoopOn = ref(false)

// ===== 章节分段 / 缩略图进度条（OSD 独立窗口经 mpv-context 获取影片身份）=====
const chapters = ref([])
const sprite = ref(null) // { sprite_url, vtt_url, count, interval, duration, thumb_width, thumb_height, cols }
const hoverPct = ref(-1) // 鼠标悬停在进度条 0~100，-1=不在
const hoverTime = ref(0)
const seekWrap = ref(null)
let movieCtx = null // { module, id }

/** 章节区间：转成 0~100 的分段（首章起点当 0，末章终点当 100） */
const chapterSegs = computed(() => {
  const dur = state.value.duration || 0
  if (!dur || !chapters.value.length) return []
  const segs = []
  const items = chapters.value
    .filter((c) => Number.isFinite(Number(c.start)))
    .sort((a, b) => Number(a.start) - Number(b.start))
  for (let i = 0; i < items.length; i++) {
    const s0 = i === 0 ? 0 : Number(items[i].start)
    const eRaw = Number(items[i].end) || (i + 1 < items.length ? Number(items[i + 1].start) : dur)
    const s1 = i === items.length - 1 ? Math.max(s0, Math.min(eRaw, dur)) : Math.min(eRaw, Number(items[i + 1].start), dur)
    if (s1 <= s0) continue
    segs.push({
      pct0: (s0 / dur) * 100,
      pct1: (s1 / dur) * 100,
      title: items[i].title || ''
    })
  }
  return segs
})

/** 已播进度（0~100） */
const playedPct = computed(() => {
  const dur = state.value.duration || 0
  if (!dur) return 0
  return Math.min(100, Math.max(0, ((state.value.timePos || 0) / dur) * 100))
})

/** hover 时刻对应的章节标题（供预览浮层展示） */
const hoverChapter = computed(() => {
  if (hoverPct.value < 0 || !chapters.value.length) return ''
  const items = chapters.value.filter((c) => Number.isFinite(Number(c.start)))
  let name = ''
  for (const c of items) {
    if (hoverTime.value >= Number(c.start) - 0.001) name = c.title || ''
  }
  return name
})

/** 是否可用 sprite 预览 */
const spriteReady = computed(() => {
  const s = sprite.value
  return !!(s && s.sprite_url && s.count > 0 && s.cols > 0 && s.interval > 0)
})

/** 悬停框偏移（居中于光标，夹在进度条宽度内） */
const hoverLeftPx = computed(() => {
  const w = seekWrap.value ? seekWrap.value.clientWidth : 400
  const ratio = Math.min(100, Math.max(0, hoverPct.value)) / 100
  const x = ratio * w
  // 浮层（缩略图 160 + 边距）居中于光标，避免溢出两端
  return Math.min(Math.max(x, 100), w - 100)
})

const hoverThumb = computed(() => {
  const s = sprite.value
  if (!spriteReady.value) return null
  const t = Math.min(Math.max(hoverTime.value, 0), state.value.duration || 0)
  const idx = Math.min(s.count - 1, Math.floor(t / s.interval))
  return { idx, col: idx % s.cols, row: Math.floor(idx / s.cols) }
})

const thumbBgStyle = computed(() => {
  const s = sprite.value
  const ht = hoverThumb.value
  if (!s || !ht) return {}
  const rows = Math.ceil(s.count / s.cols)
  const url = /^https?:\/\//i.test(s.sprite_url)
    ? s.sprite_url
    : `${getServerUrl() || ''}${s.sprite_url}`
  return {
    width: s.thumb_width + 'px',
    height: s.thumb_height + 'px',
    backgroundImage: `url("${url}")`,
    backgroundSize: `${s.cols * s.thumb_width}px ${rows * s.thumb_height}px`,
    backgroundPosition: `-${ht.col * s.thumb_width}px -${ht.row * s.thumb_height}px`
  }
})

/** 鼠标悬停：换算百分比与对应时间 */
function onBarMove(e) {
  const el = seekWrap.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (rect.width <= 0) return
  const pct = ((e.clientX - rect.left) / rect.width) * 100
  hoverPct.value = Math.min(100, Math.max(0, pct))
  hoverTime.value = (state.value.duration || 0) * (hoverPct.value / 100)
  onActivity()
}

/** 从主进程拿 module/id → 拉章节 + 缩略图元数据 */
async function loadMovieMeta() {
  try {
    const a = api()
    const ctx = await a?.mpvContext?.()
    if (!ctx || !ctx.module || !ctx.id) return
    movieCtx = { module: ctx.module, id: ctx.id }
    const cfg = await getPlayerConfig(ctx.id, ctx.module)
    if (!cfg) return
    if (Array.isArray(cfg.chapters)) chapters.value = cfg.chapters
    if (cfg.thumbnail_sprite) sprite.value = cfg.thumbnail_sprite
  } catch (e) {
    /* 无章节/缩略图时静默降级为普通进度条 */
  }
}

let hideTimer = null
let toastTimer = null
let unbindState = null
let seeking = false

function flashToast(text) {
  toast.value = text
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 1600)
}

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

function toggleMute() {
  api()?.mpvSetProp?.('mute', !state.value.mute)
  flashToast(state.value.mute ? '已取消静音' : '已静音')
  onActivity()
}

function toggleHelp() {
  showHelp.value = !showHelp.value
  if (showHelp.value) {
    // 帮助打开时保持 OSD 不自动隐藏
    if (hideTimer) clearTimeout(hideTimer)
  } else {
    onActivity()
  }
}

function setAbA() {
  const t = state.value.timePos || 0
  abA.value = t
  flashToast(`A 点已设：${fmt(t)}（再按 ] 设 B 开启循环）`)
  api()?.mpvCommand?.(['ab-loop-a'])
  onActivity()
}

function setAbB() {
  if (abLoopOn.value) {
    // 再按 ] → 关闭循环
    api()?.mpvSetProp?.('ab-loop-a', 'no')
    api()?.mpvSetProp?.('ab-loop-b', 'no')
    abLoopOn.value = false
    abA.value = null
    flashToast('AB 循环已关闭')
  } else if (abA.value !== null) {
    api()?.mpvCommand?.(['ab-loop-b'])
    abLoopOn.value = true
    flashToast(`B 点已设，AB 循环开启（再按 ] 关闭）`)
  } else {
    flashToast('请先按 [ 设 A 点')
  }
  onActivity()
}

function seekPercent(pct) {
  const d = state.value.duration || 0
  if (!d) return
  const target = (d * pct) / 100
  api()?.mpvCommand?.(['seek', target, 'absolute'])
  flashToast(`跳转 ${pct}%`)
  onActivity()
}

function onKey(e) {
  const k = e.key
  if (showHelp.value) {
    if (k === 'Escape' || k === '?' || k === '/') { toggleHelp(); return }
  }
  if (k === 'Escape') exit()
  else if (k === ' ') { e.preventDefault(); togglePlay() }
  else if (k === 'f' || k === 'F') toggleFullscreen()
  else if (k === 'm' || k === 'M') toggleMute()
  else if (k === '?') toggleHelp()
  else if (k === 'ArrowLeft') { api()?.mpvCommand?.(['seek', -5, 'relative']); flashToast('−5 秒') }
  else if (k === 'ArrowRight') { api()?.mpvCommand?.(['seek', 5, 'relative']); flashToast('+5 秒') }
  else if (k === 'ArrowUp') { const v = Math.min(130, (state.value.volume || 0) + 5); api()?.mpvSetProp?.('volume', v); api()?.mpvSetProp?.('mute', false); flashToast(`音量 ${v}%`) }
  else if (k === 'ArrowDown') { const v = Math.max(0, (state.value.volume || 0) - 5); api()?.mpvSetProp?.('volume', v); api()?.mpvSetProp?.('mute', v === 0); flashToast(`音量 ${v}%`) }
  else if (k === '[') setAbA()
  else if (k === ']') setAbB()
  else if (/^[0-9]$/.test(k)) seekPercent(Number(k) * 10)
  else return // 未消费的键不触发 OSD 活跃（避免方向键滚动等）
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
  loadMovieMeta()
  onActivity()
})

onBeforeUnmount(() => {
  if (hideTimer) clearTimeout(hideTimer)
  if (toastTimer) clearTimeout(toastTimer)
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

.osd-badge.ab {
  color: #ffd479;
  border-color: rgba(255, 212, 121, 0.4);
  background: rgba(255, 212, 121, 0.12);
}

/* ===== 快捷键帮助浮层 ===== */
.osd-help {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: min(420px, 84vw);
  background: rgba(10, 13, 19, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 12px;
  padding: 16px 20px;
  backdrop-filter: blur(10px);
  z-index: 20;
  pointer-events: auto;
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.6);
}

.osd-help-title {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  margin-bottom: 12px;
}

.osd-help-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 7px 16px;
}

.osd-help-keys {
  font-family: Consolas, Menlo, monospace;
  font-size: 11.5px;
  color: #ffd479;
  background: rgba(255, 212, 121, 0.1);
  padding: 1px 8px;
  border-radius: 4px;
  text-align: center;
  white-space: nowrap;
}

.osd-help-desc {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.82);
}

.osd-help-hint {
  margin-top: 12px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  text-align: center;
}

/* ===== 居中瞬时提示 ===== */
.osd-toast {
  position: absolute;
  left: 50%;
  bottom: 26%;
  transform: translateX(-50%);
  font-size: 13px;
  color: #fff;
  background: rgba(0, 0, 0, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.16);
  padding: 7px 18px;
  border-radius: 999px;
  pointer-events: none;
  z-index: 15;
  white-space: nowrap;
  animation: osd-toast-in 0.18s var(--ease, ease);
}

@keyframes osd-toast-in {
  from { opacity: 0; transform: translateX(-50%) translateY(6px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}

.vol-btn {
  cursor: pointer;
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

/* ===== 进度条自定义轨道（range 透明化，视觉由自定义层绘制）===== */
.osd-seek-wrap {
  position: relative;
  flex: 1;
  min-width: 120px;
  height: 26px;
  display: flex;
  align-items: center;
  cursor: pointer;
  z-index: 4;
}

.osd-seek-wrap .osd-seek {
  position: relative;
  z-index: 6;
  width: 100%;
  background: transparent !important;
  margin: 0;
}

/* range 原生轨道隐藏，只用它的 thumb 拖动 */
.osd-seek-wrap input[type='range'] {
  background: transparent;
}

.osd-seek-wrap input[type='range']::-webkit-slider-runnable-track {
  background: transparent;
  height: 4px;
}

.seek-base,
.seek-chapters,
.seek-fill {
  position: absolute;
  left: 0;
  right: 0;
  height: 4px;
  border-radius: 2px;
  pointer-events: none;
}

.seek-base {
  background: rgba(255, 255, 255, 0.22);
  z-index: 1;
}

/* 章节分段着色 */
.seek-chapters {
  overflow: hidden;
  z-index: 2;
}

.seek-seg {
  position: absolute;
  top: 0;
  height: 100%;
  background: rgba(255, 255, 255, 0.06);
  border-right: 1px solid rgba(255, 255, 255, 0.3);
}

.seek-seg.alt {
  background: rgba(0, 163, 255, 0.16);
}

/* 已播进度 */
.seek-fill {
  background: linear-gradient(90deg, #00a3ff, #4dc9ff);
  z-index: 3;
}

/* ===== hover 缩略图预览 ===== */
.seek-hover {
  position: absolute;
  bottom: 32px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  background: rgba(8, 11, 16, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 8px;
  padding: 6px;
  pointer-events: none;
  z-index: 30;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.6);
}

.sh-thumb {
  background-repeat: no-repeat;
  background-color: #000;
  border-radius: 4px;
  max-width: 280px;
  max-height: 200px;
}

.sh-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.92);
  white-space: nowrap;
}

.sh-chapter {
  color: #7ee0b8;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sh-caret {
  position: absolute;
  bottom: -7px;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 0;
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-top: 7px solid rgba(255, 255, 255, 0.45);
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
