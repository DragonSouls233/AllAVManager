<template>
  <router-link :to="group.to" class="tool-card">
    <span class="tc-head">
      <span class="tc-icon" aria-hidden="true">
        <el-icon :size="18"><component :is="group.icon" /></el-icon>
      </span>
      <span class="tc-count">{{ toolCount }} 个工具</span>
    </span>
    <span class="tc-title">{{ group.label }}</span>
    <span class="tc-desc">{{ group.desc }}</span>
    <span v-if="lastRunAt" class="tc-foot">上次使用 {{ lastRunAt }}</span>
    <span v-else class="tc-foot is-muted">尚未使用</span>
  </router-link>
</template>

<script setup>
/**
 * ToolCard —— 工具中心首页的 6 张大卡
 *
 * 完全由 `TOOL_GROUPS` 驱动（禁止硬编码组名/工具数）。
 * `lastRunAt` 本轮传 `null`（P1-5 再补真实「上次使用时间」）。
 */
defineProps({
  group: { type: Object, required: true },
  toolCount: { type: Number, default: 0 },
  lastRunAt: { type: String, default: '' },
})
</script>

<style scoped>
.tool-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card);
  box-shadow: var(--shadow-kpi);
  text-decoration: none;
  min-width: 0;
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    border-color 0.18s ease;
}

.tool-card:hover {
  border-color: var(--card-border-hover);
  transform: translateY(-3px);
  box-shadow: var(--shadow-card);
}

.tool-card:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.tc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.tc-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--accent) 85%, #fff),
    var(--accent)
  );
  color: #fff;
  box-shadow: 0 2px 8px -3px color-mix(in srgb, var(--accent) 65%, transparent);
}

.tc-count {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--hover-layer);
  font-size: 11px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.tc-title {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.tc-desc {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  min-height: 38px;
}

.tc-foot {
  font-size: 11px;
  color: var(--text-secondary);
}

.tc-foot.is-muted {
  color: var(--text-placeholder);
}
</style>
