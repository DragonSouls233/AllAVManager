<template>
  <div
    ref="containerRef"
    class="virtual-scroll"
    :style="containerStyle"
    @scroll.passive="onScroll"
  >
    <!-- 占位元素:撑出总高度,使滚动条与列表内容真实长度一致 -->
    <div class="virtual-scroll-spacer" :style="spacerStyle">
      <!-- 可视区域 viewport:绝对定位并 translateY 偏移到首个可见行位置 -->
      <div class="virtual-scroll-viewport" :class="gridClass" :style="viewportStyle">
        <template v-for="item in visibleItems" :key="getKey(item)">
          <slot :item="item" :index="getItemIndex(item)" />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * VirtualScroll 虚拟滚动列表
 * - 仅渲染可视区域内的项目 + 上下缓冲区（各 bufferRows 行）
 * - 支持网格布局：通过 minItemWidth + gap 自动计算列数
 * - 使用 IntersectionObserver 检测容器是否进入视口(离屏不重算)
 * - 使用 ResizeObserver 监听容器宽度变化(响应式列数)
 * - 滚动事件经 requestAnimationFrame 节流,确保 60fps
 */
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'

const props = defineProps({
  // 数据数组
  items: { type: Array, required: true },
  // 单个项目高度(网格场景下为单行高度)
  itemHeight: { type: Number, required: true },
  // 容器高度(数字按 px,字符串直接用)
  height: { type: [Number, String], default: 600 },
  // 唯一键字段名
  keyField: { type: String, default: 'id' },
  // 应用到 viewport 上的 CSS 类(用于复用外部 grid 样式)
  gridClass: { type: String, default: '' },
  // 网格场景下单个项目最小宽度,用于自动计算列数
  minItemWidth: { type: Number, default: 220 },
  // 网格行/列间距
  gap: { type: Number, default: 16 },
  // 上下缓冲行数(各 bufferRows 行)
  bufferRows: { type: Number, default: 5 }
})

const emit = defineEmits(['scroll'])

const containerRef = ref(null)
const scrollTop = ref(0)
const containerWidth = ref(0)
const containerHeight = ref(0)
const isVisible = ref(true)

// 列数:基于容器实际宽度计算
const columns = computed(() => {
  if (containerWidth.value === 0) return 1
  return Math.max(1, Math.floor((containerWidth.value + props.gap) / (props.minItemWidth + props.gap)))
})

// 总行数
const totalRows = computed(() => Math.ceil(props.items.length / columns.value))

// 行高(含间距)
const rowStride = computed(() => props.itemHeight + props.gap)

// 占位总高度(让滚动条正确反映数据总量)
const totalHeight = computed(() => {
  if (props.items.length === 0) return 0
  return totalRows.value * props.itemHeight + (totalRows.value - 1) * props.gap
})

// 可见起止行(含缓冲)
const visibleStartRow = computed(() =>
  Math.max(0, Math.floor(scrollTop.value / rowStride.value) - props.bufferRows)
)
const visibleEndRow = computed(() => {
  const endRow = Math.ceil((scrollTop.value + containerHeight.value) / rowStride.value) + props.bufferRows
  return Math.min(totalRows.value, endRow)
})

// 可见项目切片
const visibleItems = computed(() => {
  if (props.items.length === 0) return []
  const startIdx = visibleStartRow.value * columns.value
  const endIdx = visibleEndRow.value * columns.value
  return props.items.slice(startIdx, endIdx)
})

// viewport 偏移(对齐到可见起始行)
const offsetY = computed(() => visibleStartRow.value * rowStride.value)

const containerStyle = computed(() => ({
  height: typeof props.height === 'number' ? props.height + 'px' : props.height,
  overflowY: 'auto',
  overflowX: 'hidden',
  position: 'relative',
  contain: 'layout'
}))

const spacerStyle = computed(() => ({
  height: totalHeight.value + 'px',
  position: 'relative'
}))

const viewportStyle = computed(() => ({
  position: 'absolute',
  top: '0',
  left: '0',
  right: '0',
  transform: `translateY(${offsetY.value}px)`,
  willChange: 'transform'
}))

// 获取项目唯一 key
const getKey = (item) => {
  if (item == null) return undefined
  if (typeof item !== 'object') return item
  return item[props.keyField] ?? JSON.stringify(item)
}

const getItemIndex = (item) => props.items.indexOf(item)

// 滚动事件处理:rAF 节流
let rafId = null
const onScroll = (e) => {
  if (rafId != null) return
  rafId = requestAnimationFrame(() => {
    rafId = null
    if (!containerRef.value) return
    scrollTop.value = containerRef.value.scrollTop
    emit('scroll', {
      scrollTop: scrollTop.value,
      scrollLeft: containerRef.value.scrollLeft || 0,
      total: props.items.length,
      visibleCount: visibleItems.value.length,
      event: e
    })
  })
}

// 容器尺寸观察(响应式列数)
let resizeObserver = null
const setupResizeObserver = () => {
  if (!containerRef.value || typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(entries => {
    for (const entry of entries) {
      const { width, height } = entry.contentRect
      containerWidth.value = width
      containerHeight.value = height
    }
  })
  resizeObserver.observe(containerRef.value)
}

// 可见性观察(离屏不重算,节省 CPU)
let intersectionObserver = null
const setupIntersectionObserver = () => {
  if (!containerRef.value || typeof IntersectionObserver === 'undefined') return
  intersectionObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      isVisible.value = entry.isIntersecting
    }
  }, { threshold: 0 })
  intersectionObserver.observe(containerRef.value)
}

// 项目数变化时校正 scrollTop
watch(() => props.items.length, () => {
  nextTick(() => {
    if (!containerRef.value) return
    if (containerRef.value.scrollTop > totalHeight.value) {
      containerRef.value.scrollTop = 0
      scrollTop.value = 0
    }
  })
})

onMounted(() => {
  if (containerRef.value) {
    containerWidth.value = containerRef.value.clientWidth
    containerHeight.value = containerRef.value.clientHeight
  }
  setupResizeObserver()
  setupIntersectionObserver()
})

onBeforeUnmount(() => {
  if (rafId != null) cancelAnimationFrame(rafId)
  if (resizeObserver) resizeObserver.disconnect()
  if (intersectionObserver) intersectionObserver.disconnect()
})

// 暴露命令式 API
defineExpose({
  scrollToIndex: (index) => {
    if (!containerRef.value) return
    const row = Math.floor(index / columns.value)
    containerRef.value.scrollTop = row * rowStride.value
  },
  scrollToTop: () => {
    if (containerRef.value) containerRef.value.scrollTop = 0
  },
  getVisibleCount: () => visibleItems.value.length,
  isIntersecting: () => isVisible.value
})
</script>

<style scoped>
.virtual-scroll {
  /* 继承父级宽度,自身仅控制纵向滚动 */
  width: 100%;
}

.virtual-scroll-spacer {
  width: 100%;
}

.virtual-scroll-viewport {
  /* 默认是块级容器,具体网格布局由 gridClass 注入 */
  display: block;
}
</style>
