<template>
  <!-- 折叠态：只留一个状态点，点击仍能打开更新日志 -->
  <button
    v-if="collapsed"
    type="button"
    class="sidebar-status sidebar-status--mini"
    :title="tip"
    :aria-label="tip"
    @click="$emit('open-changelog')"
  >
    <span class="status-dot" :class="`is-${health}`" />
  </button>

  <button
    v-else
    type="button"
    class="sidebar-status"
    :title="`${healthText}${version ? ` · v${version}` : ''}（点击查看更新日志）`"
    @click="$emit('open-changelog')"
  >
    <span class="status-dot" :class="`is-${health}`" />
    <span class="status-text">{{ healthText }}</span>
    <span class="status-sep">·</span>
    <span class="status-num">{{ moviesLabel }}</span>
    <span class="status-version">{{ version ? `v${version}` : '' }}</span>
  </button>
</template>

<script setup>
/**
 * SidebarStatus —— 侧栏底部一行状态
 *
 * 取代原 `el-footer.status-bar`（P0-4 状态栏移除）的左半部分：
 * 服务器健康 + 影片总数 + 版本。数据全部来自 shellStats（0 请求）。
 */
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useShellStatsStore } from '@/stores/shellStats'

defineProps({
  collapsed: { type: Boolean, default: false },
})

defineEmits(['open-changelog'])

const shell = useShellStatsStore()
const { health, healthText, moviesTotal, version } = storeToRefs(shell)

const moviesLabel = computed(() => {
  const n = moviesTotal.value || 0
  if (n >= 10000) return `${(n / 10000).toFixed(1)}w 影片`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k 影片`
  return `${n} 影片`
})

const tip = computed(() => `${healthText.value} · ${moviesLabel.value}`)
</script>

<style scoped>
.sidebar-status {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  height: 40px;
  padding: 0 14px;
  border: 0;
  border-top: 1px solid var(--border-light);
  background: transparent;
  font-family: inherit;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  box-sizing: border-box;
  transition: background-color var(--dur-fast, 120ms);
}

.sidebar-status:hover {
  background: var(--hover-layer);
}

.sidebar-status:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.sidebar-status--mini {
  justify-content: center;
  padding: 0;
}

.status-dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-placeholder);
}

.status-dot.is-ok { background: var(--success-color); }
.status-dot.is-warn { background: var(--warning-color); }
.status-dot.is-error { background: var(--danger-color); }
.status-dot.is-unknown { background: var(--text-placeholder); }

.status-text {
  flex-shrink: 0;
  color: var(--text-regular);
}

.status-sep {
  color: var(--text-placeholder);
}

.status-num {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.status-version {
  flex-shrink: 0;
  color: var(--text-placeholder);
  font-variant-numeric: tabular-nums;
}
</style>
