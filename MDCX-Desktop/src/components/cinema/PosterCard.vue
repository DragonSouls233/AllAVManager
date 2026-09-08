<template>
  <article
    class="poster-card"
    tabindex="0"
    role="link"
    :aria-label="`${movie.code || ''} ${title}`"
    @click="$emit('open', movie)"
    @keyup.enter="$emit('open', movie)"
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

const props = defineProps({
  movie: { type: Object, required: true }
})

defineEmits(['open', 'play'])

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
</style>
