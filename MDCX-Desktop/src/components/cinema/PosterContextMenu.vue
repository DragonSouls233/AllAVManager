<template>
  <teleport to="body">
    <div v-if="state.visible" class="pcm-backdrop" @contextmenu.prevent="hide" @click="hide" @mousedown="hide" />
    <div
      v-if="state.visible"
      class="poster-context-menu"
      :style="posStyle"
      @click.stop
      @contextmenu.prevent.stop
    >
      <div class="pcm-title" v-if="movie">{{ movie.code || movie.title || '影片' }}</div>
      <button class="pcm-item" type="button" @click="playMpv">
        <span class="pcm-ico">▶</span> 原生播放器播放
      </button>
      <button class="pcm-item" type="button" @click="playExternal">
        <span class="pcm-ico">↗</span> 外部播放器打开
      </button>
      <div class="pcm-sep" />
      <button class="pcm-item" type="button" @click="mark('wanted')">
        <span class="pcm-ico">★</span> 标记为想看
      </button>
      <button class="pcm-item" type="button" @click="mark('watched')">
        <span class="pcm-ico">✓</span> 标记为已看
      </button>
      <button class="pcm-item" type="button" @click="mark('')">
        <span class="pcm-ico">✕</span> 清除标记
      </button>
    </div>
  </teleport>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { posterMenuState as state, hidePosterMenu, moduleOf } from '@/utils/posterMenu'
import { setMovieViewStatus, getMoviePlayUrl } from '@/api/index'
import { notifyViewStatusChanged } from '@/utils/browse'

const router = useRouter()
const movie = computed(() => state.movie)
const mod = computed(() => moduleOf(state.movie, state.module))

// 视口内夹紧，避免贴边溢出
const posStyle = computed(() => {
  const w = typeof window !== 'undefined' ? window.innerWidth : 1920
  const h = typeof window !== 'undefined' ? window.innerHeight : 1080
  const left = Math.min(state.x, w - 200)
  const top = Math.min(state.y, h - 230)
  return { left: `${Math.max(4, left)}px`, top: `${Math.max(4, top)}px` }
})

function hide() {
  hidePosterMenu()
}

function onKey(e) {
  if (e.key === 'Escape' && state.visible) hide()
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

function playMpv() {
  if (!movie.value) return
  router.push(`/mpv/${mod.value}/${movie.value.id}`)
  hide()
}

async function playExternal() {
  if (!movie.value) return
  try {
    const res = await getMoviePlayUrl(movie.value.id)
    const url = res?.data?.url || res?.url || res?.data?.play_url || (typeof res === 'string' ? res : '')
    if (!url) {
      ElMessage.warning('未获取到外部播放地址')
      return
    }
    if (window.electronAPI && typeof window.electronAPI.openExternal === 'function') {
      window.electronAPI.openExternal(url)
    } else {
      window.open(url, '_blank')
    }
  } catch (e) {
    ElMessage.error('外部播放失败，请确认服务端已启用外部播放')
  } finally {
    hide()
  }
}

async function mark(status) {
  if (!movie.value) return
  const m = movie.value
  const module = mod.value
  try {
    await setMovieViewStatus(m.id, status, module)
  } catch (e) {
    ElMessage.error('标记失败，请检查服务端 /view-status 接口')
  }
  // 就地更新角标：菜单持有的 movie 即网格 items 中的同一引用，修改后响应式刷新
  m._view_status = status || ''
  if (!status) {
    m._progress = 0
    m._position = 0
  }
  notifyViewStatusChanged(module, m.id, status)
  hide()
}
</script>

<style scoped>
.pcm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9998;
}
.poster-context-menu {
  position: fixed;
  z-index: 9999;
  min-width: 184px;
  padding: 6px;
  border-radius: 10px;
  background: rgba(20, 24, 32, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(10px);
  color: #e8edf5;
  font-size: 13px;
  user-select: none;
}
.pcm-title {
  padding: 4px 10px 8px;
  font-size: 12px;
  color: var(--text-3, #9aa4b2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pcm-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: transparent;
  color: inherit;
  text-align: left;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
}
.pcm-item:hover {
  background: rgba(0, 163, 255, 0.18);
}
.pcm-ico {
  width: 16px;
  text-align: center;
  opacity: 0.85;
}
.pcm-sep {
  height: 1px;
  margin: 4px 6px;
  background: rgba(255, 255, 255, 0.08);
}
</style>
