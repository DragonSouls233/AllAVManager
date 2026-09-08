<template>
  <article
    class="poster-card"
    tabindex="0"
    role="link"
    :data-cover="cover"
    :aria-label="`${movie.code || ''} ${title}`"
    @click="$emit('open', movie)"
    @keyup.enter="$emit('open', movie)"
    @mouseenter="onHover"
    @contextmenu.prevent="onContextMenu"
  >
    <div class="poster-frame">
      <img
        v-if="cover && !failed"
        :src="cover"
        :alt="title"
        loading="lazy"
        decoding="async"
        @error="failed = true"
      />
      <div v-else class="poster-fallback">
        <el-icon><Picture /></el-icon>
      </div>
      <span v-if="movie.code" class="poster-code">{{ movie.code }}</span>
      <!-- 三态角标 + 续播进度条（数据来自 enrichStatus 批量查询） -->
      <span v-if="badge" class="poster-badge" :class="`pb-${badge.key}`">{{ badge.label }}</span>
      <div v-if="progressPct > 0" class="poster-progress" :title="progressTip">
        <i :style="{ width: progressPct + '%' }" />
      </div>
      <!-- 桌面端悬停播放按钮：直连原生 mpv -->
      <button
        v-if="isDesktop"
        class="poster-play"
        type="button"
        title="用原生播放器播放"
        @click.stop="$emit('play', movie)"
      >
        <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
      </button>
    </div>
    <div class="poster-meta">
      <div class="poster-title">{{ title }}</div>
      <div class="poster-sub">{{ sub }}</div>
    </div>
  </article>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Picture } from '@element-plus/icons-vue'
import { getCoverSrc } from '@/utils/media'
import { isDesktop } from '@/config/flavor'
import { useLibraryStore } from '@/stores/library'
import { showPosterMenu } from '@/utils/posterMenu'
import { preloadNeighbors } from '@/utils/preload'

const props = defineProps({
  movie: { type: Object, required: true }
})

const emit = defineEmits(['open', 'play'])
const lib = useLibraryStore()

// 所属模块：优先影片自带，否则取当前浏览模块
const moduleName = computed(
  () => props.movie.module_name || props.movie.module_type || lib.currentModule || ''
)

function onContextMenu(e) {
  if (!isDesktop) return // 仅桌面端启用右键菜单
  showPosterMenu(e, props.movie, moduleName.value)
}

function onHover(e) {
  preloadNeighbors(e.currentTarget, 4)
}

const failed = ref(false)
const cover = computed(() => getCoverSrc(props.movie) || '')
const title = computed(() => props.movie.title || props.movie.code || '未命名')
const sub = computed(() => {
  const parts = []
  if (props.movie.release_date) parts.push(String(props.movie.release_date).slice(0, 10))
  else if (props.movie.created_at) parts.push(String(props.movie.created_at).slice(0, 10))
  if (props.movie.rating) parts.push(`★ ${props.movie.rating}`)
  if (props.movie.studio) parts.push(props.movie.studio)
  return parts.join(' · ')
})

// ---- 三态角标 ----
const viewStatus = computed(() => props.movie._view_status || props.movie.view_status || '')
const BADGES = {
  wanted: { label: '想看', key: 'wanted' },
  watched: { label: '已看', key: 'watched' }
}
const badge = computed(() => BADGES[viewStatus.value] || null)
// ---- 续播进度条（browsed 但未看完时有进度；wanted/watched 用角标表达）----
const progressPct = computed(() => {
  if (viewStatus.value === 'wanted' || viewStatus.value === 'watched') return 0
  const p = Number(props.movie._progress ?? 0)
  if (!(p > 0) || p >= 0.98) return 0
  return Math.min(100, Math.round(p * 100))
})
const progressTip = computed(() => {
  const pos = Number(props.movie._position || 0)
  if (pos > 0) {
    const mm = Math.floor(pos / 60)
    const ss = pos % 60
    return `看到 ${mm}:${String(ss).padStart(2, '0')}`
  }
  return ''
})
</script>

<style scoped>
.poster-frame {
  position: relative;
}

/* 桌面端悬停播放：中央圆形按钮，hover 海报时浮现 */
.poster-play {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%) scale(0.85);
  width: 52px;
  height: 52px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 163, 255, 0.92);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.16s, transform 0.16s, background 0.16s;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
  z-index: 2;
}

.poster-play svg {
  width: 26px;
  height: 26px;
  fill: #fff;
  margin-left: 3px; /* 视觉居中三角形 */
}

.poster-card:hover .poster-play {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1);
}

.poster-play:hover {
  background: #00a3ff;
}

.poster-play:active {
  transform: translate(-50%, -50%) scale(0.94);
}

/* 三态角标（右上角） */
.poster-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 3;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.5;
  color: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(4px);
  pointer-events: none;
}
.pb-wanted { background: linear-gradient(135deg, #ffb020, #f5811a); }
.pb-watched { background: linear-gradient(135deg, #2fcf8a, #17a36b); }

/* 续播进度条（底部，越过后番号小角） */
.poster-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 4px;
  background: rgba(11, 14, 20, 0.62);
  z-index: 3;
}
.poster-progress i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #00a3ff, #4dc9ff);
  border-radius: 0 2px 2px 0;
}
</style>
