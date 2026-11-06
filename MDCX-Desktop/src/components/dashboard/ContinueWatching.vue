<template>
  <!-- 空 → 整块不渲染（不占位，符合 PRD 表格） -->
  <section v-if="loading || items.length" class="cw" aria-label="继续观看">
    <div class="cw-head">
      <h2 class="cw-title">继续观看</h2>
      <router-link class="cw-more" to="/playlists">播放列表 →</router-link>
    </div>

    <div class="cw-rail" role="list">
      <!-- 骨架 -->
      <template v-if="loading">
        <div v-for="i in 6" :key="`sk-${i}`" class="cw-card cw-card--skeleton" aria-hidden="true">
          <div class="cw-cover cw-shimmer" />
          <div class="cw-bar" />
        </div>
      </template>

      <button
        v-for="item in (loading ? [] : items)"
        :key="`${item.module_type}-${item.id}`"
        type="button"
        class="cw-card"
        role="listitem"
        :aria-label="`继续播放 ${item.code || item.title || '影片'}`"
        @click="open(item)"
      >
        <span class="cw-cover">
          <img
            :src="coverOf(item)"
            :alt="item.code || item.title || '封面'"
            loading="lazy"
            @error="onCoverError($event, item)"
          />
          <span class="cw-play" aria-hidden="true">
            <el-icon :size="22"><VideoPlay /></el-icon>
          </span>
          <span class="cw-progress" aria-hidden="true">
            <span class="cw-progress-fill" :style="{ width: `${pct(item.progress)}%` }" />
          </span>
        </span>
        <span class="cw-meta">
          <span class="cw-code">{{ item.code || '—' }}</span>
          <span class="cw-name">{{ item.title || '未命名' }}</span>
        </span>
      </button>
    </div>
  </section>
</template>

<script setup>
/**
 * ContinueWatching —— 首页区块 2 · 跨模块续播
 *
 * 两个必须踩对的坑（ARCH-phase1 §9.3 / §11-14/15）：
 * ① `/viewing/resume` **按模块**，没有 `all`；跨模块必须并发（每模块 limit 3），
 *    用 `Promise.allSettled` 合并，任一模块失败不影响其它；
 * ② 返回字段是 `movie_id` / `module`，不是 `id` / `module_type`。
 *    归一化时必须补 `{ id: movie_id, module_type: module }`，
 *    否则 `getMovieCoverUrl()` 会拼成 JAV 的封面地址 → 无码/FC2 全部 404。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { VideoPlay } from '@element-plus/icons-vue'
import { getViewingResume } from '@/api'
import { defaultCover, getMovieCoverUrl } from '@/utils/media'
import { MODULES } from '@/config/nav'
import { useShellStatsStore } from '@/stores/shellStats'

const MODULE_ORDER = MODULES.map((m) => m.key)
const PER_MODULE = 3
const MAX_ITEMS = 6

const router = useRouter()
const shell = useShellStatsStore()

const items = ref([])
const loading = ref(true)

/** progress 可能是 0..1 也可能是 0..100，两种都吃 */
function pct(p) {
  const v = Number(p) || 0
  const asPct = v <= 1 ? v * 100 : v
  return Math.max(0, Math.min(100, asPct))
}

function coverOf(item) {
  if (item.cover_url) return item.cover_url
  return getMovieCoverUrl(item)
}

function onCoverError(event, item) {
  const target = event && event.target
  if (!target) return
  target.src = defaultCover(item.code || '')
}

async function load() {
  loading.value = true
  try {
    const mods = MODULE_ORDER.filter((m) => shell.enabled[m] !== false)
    if (mods.length === 0) {
      items.value = []
      return
    }
    const results = await Promise.allSettled(
      mods.map((m) => getViewingResume({ module: m, limit: PER_MODULE })),
    )
    const merged = results
      .flatMap((r) => (r.status === 'fulfilled' ? (r.value?.items || []) : []))
      .map((it) => ({
        // ⚠️ resume 返回 movie_id（不是 id）
        id: it.movie_id,
        // ⚠️ 必须补 module_type，否则封面函数拼错模块 → 404
        module_type: it.module,
        code: it.code,
        title: it.title,
        cover_url: it.cover_url,
        progress: it.progress,
        played_at: it.played_at,
      }))
      .filter((it) => it.id != null)
      .sort((a, b) => new Date(b.played_at || 0) - new Date(a.played_at || 0))
      .slice(0, MAX_ITEMS)
    items.value = merged
  } catch (e) {
    // 全灭 → 整块隐藏，不显示错误（符合 PRD §9.2 表格）
    items.value = []
  } finally {
    loading.value = false
  }
}

function open(item) {
  router.push(`/play/${item.id}?module=${item.module_type}`).catch(() => {})
}

onMounted(load)
</script>

<style scoped>
.cw {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cw-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.cw-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.cw-more {
  font-size: 12px;
  color: var(--text-secondary);
  text-decoration: none;
}

.cw-more:hover {
  color: var(--accent);
}

.cw-rail {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
  scrollbar-width: thin;
}

.cw-card {
  display: flex;
  flex-direction: column;
  flex: 0 0 140px;
  width: 140px;
  padding: 0;
  border: 0;
  background: transparent;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.cw-card:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: var(--radius-card, 10px);
}

.cw-cover {
  position: relative;
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

.cw-card:hover .cw-cover {
  border-color: var(--card-border-hover);
}

.cw-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.cw-play {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: rgba(15, 18, 26, 0.32);
  opacity: 0;
  transition: opacity var(--dur-fast, 120ms);
}

.cw-card:hover .cw-play,
.cw-card:focus-visible .cw-play {
  opacity: 1;
}

.cw-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: rgba(255, 255, 255, 0.28);
}

.cw-progress-fill {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width var(--dur-base, 200ms) var(--ease-out-nav, ease-out);
}

.cw-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 6px 2px 0;
  min-width: 0;
}

.cw-code {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cw-name {
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 骨架 */
.cw-card--skeleton .cw-cover {
  border-color: transparent;
}

.cw-shimmer {
  background: var(--hover-layer);
  animation: cw-pulse 1.2s var(--ease-out-nav, ease-out) infinite;
}

.cw-bar {
  height: 10px;
  margin: 8px 2px 0;
  border-radius: 4px;
  background: var(--hover-layer);
}

@keyframes cw-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
