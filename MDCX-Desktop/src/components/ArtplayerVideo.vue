<template>
  <div class="artplayer-video">
    <div ref="artplayerRef" class="artplayer-box"></div>
    <div v-if="!url" class="no-url">
      <el-empty description="未提供视频地址" :image-size="60" />
    </div>
  </div>
</template>

<script setup>
/**
 * Artplayer + Hls.js 可复用视频播放器组件
 *
 * v3.1 新增：
 * - 封装 Artplayer 5 + Hls.js 6 逻辑
 * - 自动检测 HLS（.m3u8 或 /hls/ 路径）
 * - 支持章节列表、外挂字幕、缩略图进度条
 * - 暴露 art 实例供父组件调用（seek/screenshot/currentTime）
 *
 * 用法：
 *   <ArtplayerVideo :url="videoUrl" :chapters="chapters" @ready="onReady" />
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElEmpty } from 'element-plus'
import Artplayer from 'artplayer'
import Hls from 'hls.js'

const props = defineProps({
  url: { type: String, default: '' },
  // 章节列表 [{ start: number, title: string }]
  chapters: { type: Array, default: () => [] },
  // 外挂字幕 URL
  subtitleUrl: { type: String, default: '' },
  subtitleType: { type: String, default: 'vtt' }, // vtt | srt
  // 缩略图进度条 VTT URL
  spriteVttUrl: { type: String, default: '' },
  // 主题色
  theme: { type: String, default: '#2396ef' },
  // 自动播放
  autoplay: { type: Boolean, default: false },
  // 默认音量 0-1
  volume: { type: Number, default: 0.7 },
  // 音轨列表 v3.5：[{ index, label, language, default }]
  audioTracks: { type: Array, default: () => [] },
  // HLS 自适应画质列表 v3.5：[{ bandwidth, width, height, label }]
  // 空数组表示单码率或直接播放
  qualities: { type: Array, default: () => [] },
})

const emit = defineEmits(['ready', 'timeupdate', 'screenshot', 'chapter-mark'])

const artplayerRef = ref(null)
let art = null
let hls = null

const formatTime = (sec) => {
  if (sec == null || isNaN(sec)) return '--:--'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// v3.5: 构建播放器设置菜单（章节/音轨/画质）
const buildSettings = () => {
  const items = []

  // 章节跳转
  if (props.chapters.length) {
    items.push({
      html: '章节',
      tooltip: '跳转章节',
      selector: props.chapters.map((c) => ({
        html: `${formatTime(c.start)} - ${c.title || '未命名'}`,
        time: c.start,
      })),
      onSelect(item) {
        art.currentTime = item.time
        return item.html
      },
    })
  }

  // 音轨切换
  if (props.audioTracks.length > 1) {
    items.push({
      html: '音轨',
      tooltip: '切换音轨',
      selector: props.audioTracks.map((t) => ({
        html: t.label || `音轨 ${t.index + 1}`,
        value: t.index,
        default: !!t.default,
      })),
      onSelect(item) {
        switchAudioTrack(item.value)
        return item.html
      },
    })
  }

  // 画质切换（HLS自适应码率）
  if (props.qualities.length) {
    items.push({
      html: '画质',
      tooltip: '自适应码率',
      selector: [
        { html: '自动', value: -1, default: true },
        ...props.qualities.map((q, i) => ({
          html: q.label || `${q.height}p`,
          value: i,
        })),
      ],
      onSelect(item) {
        switchQuality(item.value)
        return item.html
      },
    })
  }

  return items
}

// v3.5: 切换音轨
const switchAudioTrack = (trackIndex) => {
  if (!art) return
  const video = art.video
  if (hls) {
    // HLS 模式：通过 hls.js 切换
    try {
      hls.audioTrack = trackIndex
    } catch (e) {
      console.warn('音轨切换失败:', e)
    }
  } else if (video && video.audioTracks && video.audioTracks.length) {
    // 直接播放模式：通过 HTMLAudioTrack API 切换（Chrome/Edge 支持）
    for (let i = 0; i < video.audioTracks.length; i++) {
      video.audioTracks[i].enabled = i === trackIndex
    }
  } else {
    console.warn('当前浏览器或播放模式不支持音轨切换，建议使用 HLS 模式')
  }
}

// v3.5: 切换画质（HLS自适应码率）
const switchQuality = (levelIndex) => {
  if (!hls) {
    console.warn('画质切换仅支持 HLS 自适应码率模式')
    return
  }
  // hls.js: currentLevel = -1 表示自动（根据网络情况切换）
  // currentLevel = N 表示强制使用第 N 个画质
  hls.currentLevel = levelIndex
}

const initArtplayer = (videoUrl) => {
  if (!videoUrl) return
  if (art) {
    art.destroy(false)
    art = null
  }
  if (hls) {
    hls.destroy()
    hls = null
  }

  const isHls = videoUrl.includes('/hls/') || videoUrl.endsWith('.m3u8') || videoUrl.includes('.m3u8?')

  art = new Artplayer({
    container: artplayerRef.value,
    url: videoUrl,
    type: isHls ? 'm3u8' : 'video',
    customType: {
      m3u8: (video, url) => {
        if (Hls.isSupported()) {
          if (hls) hls.destroy()
          hls = new Hls({ enableWorker: true, lowLatencyMode: false })
          hls.loadSource(url)
          hls.attachMedia(video)
          hls.on(Hls.Events.ERROR, (event, data) => {
            if (data.fatal) {
              console.warn('HLS fatal error:', data.type, data.details)
            }
          })
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
          // Safari 原生支持 HLS
          video.src = url
        }
      }
    },
    volume: props.volume,
    autoplay: props.autoplay,
    autoSize: false,
    autoMini: false,
    screenshot: true,
    setting: true,
    loop: false,
    flip: true,
    playbackRate: true,
    aspectRatio: true,
    fullscreen: true,
    fullscreenWeb: true,
    subtitleOffset: true,
    miniProgressBar: true,
    mutex: true,
    backdrop: true,
    playsInline: true,
    autoPlayback: true,
    airplay: true,
    theme: props.theme,
    lang: 'zh-cn',
    moreVideoAttr: {
      crossOrigin: 'anonymous',
      preload: 'auto',
    },
    settings: buildSettings(),
    contextmenu: [
      {
        html: '标记此刻为章节',
        click() {
          emit('chapter-mark', art.currentTime)
        },
      },
      {
        html: '截图',
        click() {
          art.screenshot()
        },
      },
    ],
    controls: [
      {
        name: 'mark-chapter',
        position: 'right',
        html: '<i class="art-icon">📍</i>',
        tooltip: '标记此刻',
        click() {
          emit('chapter-mark', art.currentTime)
        },
      },
    ],
  })

  // 加载外挂字幕
  if (props.subtitleUrl) {
    art.subtitle = {
      url: props.subtitleUrl,
      type: props.subtitleType,
      encoding: 'utf-8',
      style: { color: '#fff' },
    }
  }

  // 加载缩略图进度条 VTT
  if (props.spriteVttUrl) {
    loadThumbnailVtt(props.spriteVttUrl)
  }

  art.on('ready', () => {
    emit('ready', art)
  })

  art.on('video:timeupdate', () => {
    emit('timeupdate', art.currentTime)
  })

  art.on('video:screenshot', ({ dataURL }) => {
    emit('screenshot', dataURL)
  })
}

const loadThumbnailVtt = (vttUrl) => {
  if (!art) return
  fetch(vttUrl)
    .then((r) => r.text())
    .then((vtt) => {
      const cues = parseVtt(vtt)
      if (art.template) {
        art.template.ingestedThumbnailCues = cues
      }
    })
    .catch(() => {})
}

const parseVtt = (vtt) => {
  const cues = []
  const lines = vtt.split('\n')
  let current = null
  for (const line of lines) {
    const m = line.match(/(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})/)
    if (m) {
      current = { start: parseTimestamp(m[1]), end: parseTimestamp(m[2]) }
    } else if (current && line.includes('#xywh=')) {
      const xywh = line.match(/#xywh=(\d+),(\d+),(\d+),(\d+)/)
      if (xywh) {
        current.x = parseInt(xywh[1])
        current.y = parseInt(xywh[2])
        current.w = parseInt(xywh[3])
        current.h = parseInt(xywh[4])
        cues.push(current)
      }
    }
  }
  return cues
}

const parseTimestamp = (ts) => {
  const [h, m, s] = ts.split(':')
  return parseFloat(h) * 3600 + parseFloat(m) * 60 + parseFloat(s)
}

// 暴露 art 实例方法给父组件
defineExpose({
  art: () => art,
  seek: (t) => {
    if (art) art.currentTime = t
  },
  toggle: () => {
    if (art) art.toggle()
  },
  screenshot: () => {
    if (art) art.screenshot()
  },
  getCurrentTime: () => (art ? art.currentTime : 0),
  // v3.5: 音轨/画质切换
  switchAudioTrack,
  switchQuality,
  getHls: () => hls,
  destroy: () => {
    if (art) art.destroy(false)
    if (hls) hls.destroy()
    art = null
    hls = null
  },
})

// 监听 URL 变化重新初始化
watch(
  () => props.url,
  async (newUrl) => {
    if (newUrl) {
      await nextTick()
      initArtplayer(newUrl)
    }
  }
)

// v3.5: 监听音轨/画质列表变化，更新设置菜单
watch(
  [() => props.audioTracks, () => props.qualities],
  () => {
    if (art) {
      art.setting.show = false
      // 重建 settings 需要重新初始化（Artplayer 限制）
      // 这里通过更新 art.setting 配置实现
      const newSettings = buildSettings()
      // Artplayer 5 支持 art.setting.update（如果可用）
      if (typeof art.setting.update === 'function') {
        art.setting.update(newSettings)
      }
    }
  },
  { deep: true }
)

onMounted(async () => {
  if (props.url) {
    await nextTick()
    initArtplayer(props.url)
  }
})

onUnmounted(() => {
  if (art) art.destroy(false)
  if (hls) hls.destroy()
})
</script>

<style scoped>
.artplayer-video {
  width: 100%;
  position: relative;
}

.artplayer-box {
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 70vh;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.no-url {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #000;
  border-radius: 8px;
}
</style>
