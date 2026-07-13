<template>
  <div
    class="skeleton"
    :class="{ 'skeleton-animated': animated }"
    :style="skeletonStyle"
    role="status"
    aria-busy="true"
    aria-live="polite"
  >
    <span class="sr-only">加载中</span>
  </div>
</template>

<script setup>
/**
 * Skeleton 骨架屏
 * - 占位元素,在内容加载前显示
 * - 支持 shimmer 渐变动画
 * - 可配置宽度/高度/圆角/是否动画
 */
import { computed } from 'vue'

const props = defineProps({
  // 宽度(数字按 px,字符串直接用,如 '100%'/'12rem')
  width: { type: [Number, String], default: '100%' },
  // 高度(同上)
  height: { type: [Number, String], default: 16 },
  // 圆角(数字按 px,字符串直接用)
  rounded: { type: [Number, String], default: 4 },
  // 是否启用 shimmer 动画
  animated: { type: Boolean, default: true }
})

const toSize = (v) => (typeof v === 'number' ? v + 'px' : v)

const skeletonStyle = computed(() => ({
  width: toSize(props.width),
  height: toSize(props.height),
  borderRadius: toSize(props.rounded)
}))
</script>

<style scoped>
.skeleton {
  display: inline-block;
  background: var(--skeleton-bg, rgba(0, 0, 0, 0.08));
  vertical-align: middle;
  overflow: hidden;
  position: relative;
}

html.dark .skeleton {
  background: var(--skeleton-bg, rgba(255, 255, 255, 0.08));
}

/* shimmer 渐变动画:在骨架上扫过的高光 */
.skeleton-animated::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.35) 50%,
    transparent 100%
  );
  animation: skeleton-shimmer 1.4s infinite;
}

html.dark .skeleton-animated::after {
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.06) 50%,
    transparent 100%
  );
}

@keyframes skeleton-shimmer {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}

/* 屏幕阅读器视觉隐藏 */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* 减弱动效:关闭 shimmer */
@media (prefers-reduced-motion: reduce) {
  .skeleton-animated::after {
    animation: none;
  }
}
</style>
