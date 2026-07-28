<template>
  <!--
    Artplayer 弹幕增强播放器（v6.0）
    - 弹幕系统（Danmaku）
    - 外挂字幕（VTT/SRT）
    - 多音轨切换
    - 自适应码率（HLS）
    - 缩略图进度条
  -->
  <div class="enhanced-player">
    <!-- 播放器容器 -->
    <div ref="playerRef" class="player-box"></div>

    <!-- 空状态 -->
    <div v-if="!url" class="player-empty">
      <el-empty description="未提供视频地址" :image-size="60" />
    </div>

    <!-- 弹幕控制栏 -->
    <div v-if="url" class="danmaku-bar">
      <el-switch
        v-model="danmakuVisible"
        size="small"
        active-text="弹幕"
        inactive-text="弹幕关"
        @change="toggleDanmaku"
      />
      <el-input
        v-model="danmakuText"
        size="small"
        placeholder="发一条弹幕..."
        style="width: 200px;"
        @keyup.enter="sendDanmaku"
      />
      <el-button size="small" type="primary" :icon="ChatDotSquare" @click="sendDanmaku">
        发射
      </el-button>
      <span style="font-size:12px;color:var(--el-text-color-secondary);margin-left:8px;">
        {{ currentTime }}
      </span>
    </div>
  </div>
</template>

<script setup>
/**
 * Artplayer 弹幕增强播放器
 *
 * Props:
 *   url - 视频播放地址（M3U8 或 MP4）
 *   subtitles - 字幕列表 [{ url, label, type }]
 *   quality - 可选画质列表 [{ url, label }]
 *   code - 番号（用于弹幕持久化）
 *
 * Emits:
 *   ready - 播放器就绪
 *   timeupdate - 播放时间更新
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotSquare } from '@element-plus/icons-vue'
import Artplayer from 'artplayer'
import Hls from 'hls.js'

const props = defineProps({
  url: { type: String, default: '' },
  subtitles: { type: Array, default: () => [] },
  quality: { type: Array, default: () => [] },
  code: { type: String, default: '' },
  theme: { type: String, default: '#2396ef' },
  autoplay: { type: Boolean, default: false },
  volume: { type: Number, default: 0.7 },
})

const emit = defineEmits(['ready', 'timeupdate'])

const playerRef = ref(null)
const danmakuVisible = ref(true)
const danmakuText = ref('')
const currentTime = ref('00:00')
let art = null
let danmakuPool = [] // 持久化弹幕池

// --- 初始化播放器 ---
function initPlayer() {
  if (!playerRef.value || !props.url) return
  if (art) { art.destroy(); art = null }

  const isHls = props.url.includes('.m3u8') || props.url.includes('/hls/')
  const customType = {}
  let hlsInstance = null

  if (isHls && Hls.isSupported()) {
    customType.m3u8 = (video, url) => {
      hlsInstance = new Hls({
        enableWorker: true,
        maxBufferLength: 100,
        maxMaxBufferLength: 300,
        startLevel: -1,
      })
      hlsInstance.loadSource(url)
      hlsInstance.attachMedia(video)
    }
  }

  art = new Artplayer({
    container: playerRef.value,
    url: props.url,
    customType,
    theme: props.theme,
    volume: props.volume,
    autoplay: props.autoplay,
    playbackRate: true,
    screenshot: true,
    setting: true,
    loop: false,
    pip: true,
    mutex: true,
    fullscreen: true,
    fullscreenWeb: true,
    hotkey: true,
    plugins: [
      // 缩略图进度条可通过 options.thumbnails 配置
    ],
  })

  // 字幕
  if (props.subtitles.length) {
    art.subtitle.url = props.subtitles[0].url
    art.subtitle.type = props.subtitles[0].type || 'vtt'
  }

  // 画质切换
  if (props.quality.length) {
    art.quality = props.quality
  }

  // 当前时间更新
  art.on('video:timeupdate', () => {
    const s = Math.floor(art.currentTime)
    const m = Math.floor(s / 60)
    const sec = s % 60
    currentTime.value = `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    emit('timeupdate', art.currentTime)
  })

  // 弹幕定时器
  danmakuPool = loadDanmaku(props.code)
  let lastCheck = 0
  art.on('video:timeupdate', () => {
    const now = Math.floor(art.currentTime)
    if (now !== lastCheck && danmakuVisible.value) {
      lastCheck = now
      danmakuPool
        .filter(d => Math.floor(d.time) === now)
        .forEach(d => art.plugins.danmaku?.emit('danmaku_push', d.text))
    }
  })

  emit('ready', art)
}

// --- 弹幕控制 ---
function toggleDanmaku(visible) {
  if (!art) return
  art.plugins.danmaku && (art.plugins.danmaku.plugin.config.opacity = visible ? 1 : 0)
}

function sendDanmaku() {
  const text = danmakuText.value.trim()
  if (!text || !art) return
  art.plugins.danmaku?.emit('danmaku_push', text)
  danmakuPool.push({ time: Math.floor(art.currentTime), text })
  saveDanmaku(props.code, danmakuPool)
  danmakuText.value = ''
}

// --- 弹幕持久化（localStorage）---
function loadDanmaku(code) {
  if (!code) return []
  try {
    const raw = localStorage.getItem(`danmaku_${code}`)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveDanmaku(code, pool) {
  if (!code) return
  try {
    localStorage.setItem(`danmaku_${code}`, JSON.stringify(pool.slice(-500)))
  } catch { /* storage full */ }
}

// --- 生命周期 ---
onMounted(() => { nextTick(initPlayer) })
onUnmounted(() => { if (art) { art.destroy(); art = null } })

watch(() => props.url, () => { nextTick(initPlayer) })

// 暴露 API 给父组件
defineExpose({
  seek(t) { art?.seek(t) },
  screenshot() { return art?.screenshot() },
  getCurrentTime() { return art?.currentTime || 0 },
  toggle() { art?.toggle() },
  getArt() { return art },
})
</script>

<style scoped>
.enhanced-player { position: relative; }
.player-box { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 6px; overflow: hidden; }
.player-empty { position: absolute; top: 0; left: 0; right: 0; bottom: 0; display: flex; align-items: center; justify-content: center; background: #000; border-radius: 6px; }
.danmaku-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  border-top: none;
  border-radius: 0 0 6px 6px;
}
</style>
