<template>
  <section class="pills" aria-label="模块入口">
    <router-link
      v-for="pill in pills"
      :key="pill.key"
      :to="pill.to"
      class="pill"
      :class="{ 'is-empty': pill.count === 0 }"
    >
      <span class="pill-emoji" aria-hidden="true">{{ pill.emoji }}</span>
      <span class="pill-label">{{ pill.label }}</span>
      <span v-if="pill.count > 0" class="pill-count">{{ pill.countLabel }}</span>
      <span v-else class="pill-count is-muted">等待数据</span>
    </router-link>
  </section>
</template>

<script setup>
/**
 * ModulePills —— 首页区块 4 · 7 个模块 pill（一行）
 *
 * 计数读 `shellStats.moduleMovies`（来自 `/stats/dashboard` 的 `modules[key].movies`），0 请求。
 * 停用的模块不渲染（与侧栏一致）。
 */
import { computed } from 'vue'
import { MODULES } from '@/config/nav'
import { useShellStatsStore } from '@/stores/shellStats'

const shell = useShellStatsStore()

function fmt(n) {
  const v = Number(n) || 0
  if (v >= 10000) return `${(v / 10000).toFixed(1)}w`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

const pills = computed(() =>
  MODULES.filter((m) => shell.enabled[m.flag] !== false).map((m) => {
    const count = shell.moduleMovies[m.key] || 0
    return {
      key: m.key,
      label: m.label,
      emoji: m.emoji,
      to: m.movies,
      count,
      countLabel: fmt(count),
    }
  }),
)
</script>

<style scoped>
.pills {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: 10px;
  background: var(--bg-card);
  box-shadow: var(--shadow-kpi);
  font-size: 13px;
  color: var(--text-regular);
  text-decoration: none;
  transition:
    border-color var(--dur-fast, 120ms),
    box-shadow var(--dur-fast, 120ms),
    color var(--dur-fast, 120ms);
}

.pill:hover {
  border-color: var(--card-border-hover);
  box-shadow: var(--shadow-card);
  color: var(--text-primary);
}

.pill:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.pill.is-empty {
  color: var(--text-secondary);
}

.pill-emoji {
  font-size: 13px;
  line-height: 1;
}

.pill-label {
  white-space: nowrap;
}

.pill-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  padding: 1px 7px;
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}

.pill-count.is-muted {
  font-weight: 400;
  color: var(--text-placeholder);
  background: var(--hover-layer);
}
</style>
