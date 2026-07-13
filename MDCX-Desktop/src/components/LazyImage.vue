<template>
  <div
    ref="wrapperRef"
    class="lazy-image"
    :class="{ 'lazy-image-loaded': loaded, 'lazy-image-error': error }"
    :style="wrapperStyle"
  >
    <!-- 骨架屏占位(加载前或加载失败时显示) -->
    <Skeleton
      v-if="!loaded"
      :width="'100%'"
      :height="'100%'"
      :rounded="0"
      :animated="!error"
      class="lazy-image-skeleton"
    />

    <!-- 实际图片:进入视口后才挂载 src,避免提前下载 -->
    <img
      v-if="shouldLoad && !error"
      :src="currentSrc"
      :alt="alt"
      :style="imgStyle"
      class="lazy-image-img"
      decoding="async"
      @load="onLoad"
      @error="onError"
    />

    <!-- 错误占位图标(placeholder 也加载失败时显示) -->
    <div v-if="error" class="lazy-image-error-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor">
        <path d="M21 5v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1zM8.5 13.5l-3.5 4.5h14l-4.5-6-3.5 4.5-2.5-3z"/>
      </svg>
    </div>
  </div>
</template>

<script setup>
/**
 * LazyImage 图片懒加载组件
 * - 使用 IntersectionObserver 监听图片是否进入视口
 * - 进入视口后才挂载 src,避免提前下载
 * - 加载前显示 Skeleton 骨架屏(shimmer 动画)
 * - 加载完成后淡入显示
 * - 出错时尝试加载 placeholder,placeholder 也失败则显示错误占位图标
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import Skeleton from './Skeleton.vue'

const props = defineProps({
  // 图片地址
  src: { type: String, default: '' },
  // 替代文本
  alt: { type: String, default: '' },
  // 容器宽度
  width: { type: [Number, String], default: '100%' },
  // 容器高度
  height: { type: [Number, String], default: '100%' },
  // 占位图:加载错误时备用
  placeholder: { type: String, default: '' },
  // 触发距离:提前多少像素开始加载(rootMargin)
  rootMargin: { type: String, default: '200px 0px' },
  // 立即模式:跳过 IntersectionObserver,适用于已由父组件(如VirtualScroll)控制可见性的场景
  immediate: { type: Boolean, default: false }
})

const emit = defineEmits(['load', 'error'])

const wrapperRef = ref(null)
const inView = ref(false)
const loaded = ref(false)
const error = ref(false)
// 当前实际使用的 src:出错后会切换到 placeholder
const currentSrc = ref(props.src)

// 是否应该开始加载图片: immediate 模式或在视口内
const shouldLoad = computed(() => props.immediate || inView.value)

const toSize = (v) => (typeof v === 'number' ? v + 'px' : v)

const wrapperStyle = computed(() => ({
  width: toSize(props.width),
  height: toSize(props.height)
}))

const imgStyle = computed(() => ({
  opacity: loaded.value ? 1 : 0,
  transition: 'opacity 0.3s ease'
}))

// IntersectionObserver 监听进入视口
let ioObserver = null
const setupObserver = () => {
  // immediate 模式或不支持 IO 时直接加载
  if (props.immediate || !wrapperRef.value || typeof IntersectionObserver === 'undefined') {
    inView.value = true
    return
  }
  ioObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          inView.value = true
          // 进入视口后即可断开观察,无需继续监听
          if (ioObserver) {
            ioObserver.disconnect()
            ioObserver = null
          }
        }
      }
    },
    { rootMargin: props.rootMargin, threshold: 0.01 }
  )
  ioObserver.observe(wrapperRef.value)
}

const onLoad = (e) => {
  loaded.value = true
  error.value = false
  emit('load', e)
}

const onError = (e) => {
  // 出错后若有 placeholder 且尚未尝试过,切换到 placeholder 再加载一次
  if (props.placeholder && currentSrc.value !== props.placeholder) {
    currentSrc.value = props.placeholder
    return
  }
  // 没有回退或 placeholder 也失败:显示错误占位图标
  error.value = true
  loaded.value = false
  emit('error', e)
}

// src 变化时重置状态(并切换 currentSrc)
watch(
  () => props.src,
  (newSrc) => {
    currentSrc.value = newSrc
    loaded.value = false
    error.value = false
  }
)

onMounted(() => {
  setupObserver()
})

onBeforeUnmount(() => {
  if (ioObserver) {
    ioObserver.disconnect()
    ioObserver = null
  }
})
</script>

<style scoped>
.lazy-image {
  position: relative;
  overflow: hidden;
  display: inline-block;
  background: transparent;
}

.lazy-image-img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.lazy-image-skeleton {
  position: absolute;
  inset: 0;
}

.lazy-image-error-icon {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder, #c0c4cc);
  background: var(--bg-page, #f0f2f5);
}

html.dark .lazy-image-error-icon {
  background: var(--bg-page, #141414);
  color: var(--text-placeholder, #8D9095);
}
</style>
