<template>
  <div class="tool-loading" role="status" aria-busy="true" aria-live="polite">
    <span class="sr-only">工具页加载中</span>
    <div class="tl-bar tl-bar--sm" />
    <div class="tl-block" />
  </div>
</template>

<script setup>
/**
 * ToolLoading —— 工具页异步加载占位
 *
 * 为什么单独一个文件：`defineAsyncComponent` 配 `suspensible: false` 时，
 * Suspense 的 fallback 不会触发（异步组件不再向上冒泡 suspension），
 * 必须由异步组件自己提供 `loadingComponent` 才有可见占位。
 * 纯静态骨架，无 props、无依赖，保证被打进工具中心那一个 chunk。
 */
</script>

<style scoped>
.tool-loading {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 0;
}

.tl-bar {
  height: 16px;
  border-radius: var(--radius-ctl, 8px);
  background: var(--hover-layer, rgba(15, 18, 26, 0.04));
  animation: tl-pulse 1.2s var(--ease-out-nav, ease-out) infinite;
}

.tl-bar--sm {
  width: 180px;
}

.tl-block {
  height: 240px;
  border-radius: var(--radius-card, 10px);
  background: var(--hover-layer, rgba(15, 18, 26, 0.04));
  animation: tl-pulse 1.2s var(--ease-out-nav, ease-out) infinite;
}

@keyframes tl-pulse {
  0%,
  100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
