<template>
  <section v-if="loading || items.length" class="rec" aria-label="为你推荐">
    <div class="rec-head">
      <h2 class="rec-title">为你推荐</h2>
      <router-link class="rec-more" to="/recommendations">更多 →</router-link>
    </div>

    <div class="rec-grid">
      <template v-if="loading">
        <div v-for="i in 3" :key="`sk-${i}`" class="rec-card" aria-hidden="true">
          <div class="rec-cover rec-shimmer" />
        </div>
      </template>

      <router-link
        v-for="item in (loading ? [] : items)"
        :key="`${item.module_type || item.module || ''}-${item.id}`"
        :to="linkOf(item)"
        class="rec-card"
      >
        <span class="rec-cover">
          <img :src="coverOf(item)" :alt="item.code || '封面'" loading="lazy" @error="onCoverError($event, item)" />
        </span>
        <span class="rec-code">{{ item.code || '—' }}</span>
      </router-link>
    </div>
  </section>
</template>

<script setup>
/**
 * RecommendStrip —— 首页区块 8 · 推荐 3 张
 *
 * 相对 PRD 的 1 处调整（ARCH-phase1 §9.1 ②）：4/12 宽度下放 6 张会挤成缩略图，
 * 改为 3 张（`minmax(110px, 1fr)`）。空 → 整块隐藏。
 */
import { onMounted, ref } from 'vue'
import { getRecommendations } from '@/api'
import { defaultCover, getMovieCoverUrl } from '@/utils/media'

const items = ref([])
const loading = ref(true)

function coverOf(item) {
  if (item.cover_url) return item.cover_url
  // 推荐接口自带 module_type 时直接用；缺省按 jav 处理
  return getMovieCoverUrl({ ...item, module_type: item.module_type || item.module || 'jav' })
}

function onCoverError(event, item) {
  const target = event && event.target
  if (!target) return
  target.src = defaultCover(item.code || '')
}

function linkOf(item) {
  const mod = item.module_type || item.module || 'jav'
  return `/${mod}/movies/${item.id}`
}

onMounted(async () => {
  try {
    const res = await getRecommendations(12)
    const list = Array.isArray(res?.items) ? res.items : []
    items.value = list.slice(0, 3)
  } catch (e) {
    items.value = []
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.rec {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
  min-width: 0;
}

.rec-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.rec-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.rec-more {
  font-size: 12px;
  color: var(--text-secondary);
  text-decoration: none;
  white-space: nowrap;
}

.rec-more:hover {
  color: var(--accent);
}

.rec-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.rec-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-decoration: none;
  min-width: 0;
}

.rec-card:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: var(--radius-card, 10px);
}

.rec-cover {
  display: block;
  width: 100%;
  aspect-ratio: 2 / 3;
  border-radius: var(--radius-card, 10px);
  overflow: hidden;
  background: var(--bg-page);
  border: 1px solid var(--border-color);
  transition: border-color var(--dur-fast, 120ms);
  box-sizing: border-box;
}

.rec-card:hover .rec-cover {
  border-color: var(--card-border-hover);
}

.rec-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.rec-code {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rec-shimmer {
  border-color: transparent;
  background: var(--hover-layer);
  animation: rec-pulse 1.2s var(--ease-out-nav, ease-out) infinite;
}

@keyframes rec-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
