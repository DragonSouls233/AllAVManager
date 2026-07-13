<template>
  <el-dialog
    v-model="visible"
    :title="title || '封面预览'"
    width="80%"
    top="5vh"
    class="cover-preview-dialog"
    :before-close="handleClose"
    append-to-body
    destroy-on-close
  >
    <div class="preview-container" ref="containerRef">
      <!-- 工具栏 -->
      <div class="preview-toolbar">
        <el-button-group>
          <el-button size="small" @click="zoomOut" :disabled="scale <= 0.5">
            <el-icon><ZoomOut /></el-icon>
          </el-button>
          <el-button size="small" disabled>{{ Math.round(scale * 100) }}%</el-button>
          <el-button size="small" @click="zoomIn" :disabled="scale >= 5">
            <el-icon><ZoomIn /></el-icon>
          </el-button>
        </el-button-group>
        <el-button size="small" @click="resetZoom">
          <el-icon><RefreshRight /></el-icon> 重置
        </el-button>
        <el-button size="small" @click="fitToScreen">
          <el-icon><FullScreen /></el-icon> 适应屏幕
        </el-button>
        <el-button size="small" @click="downloadImage" v-if="src">
          <el-icon><Download /></el-icon> 下载
        </el-button>
      </div>

      <!-- 图片容器（支持滚轮缩放 + 拖动） -->
      <div
        class="image-wrapper"
        ref="wrapperRef"
        @wheel.prevent="onWheel"
        @mousedown="onMouseDown"
        @mousemove="onMouseMove"
        @mouseup="onMouseUp"
        @mouseleave="onMouseUp"
      >
        <img
          v-if="src"
          :src="src"
          :alt="title"
          class="preview-image"
          :style="imageStyle"
          @load="onImageLoad"
          @error="onImageError"
          draggable="false"
        />
        <div v-if="loading" class="loading-placeholder">
          <el-icon class="is-loading" :size="40"><Loading /></el-icon>
          <span>加载中...</span>
        </div>
        <div v-if="error" class="error-placeholder">
          <el-icon :size="40"><PictureFilled /></el-icon>
          <span>图片加载失败</span>
        </div>
      </div>

      <!-- 缩放滑块 -->
      <div class="zoom-slider">
        <el-slider
          v-model="scalePercent"
          :min="50"
          :max="500"
          :step="10"
          :show-tooltip="true"
          :format-tooltip="(val) => `${val}%`"
          @input="onSliderChange"
        />
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import {
  ZoomIn, ZoomOut, RefreshRight, FullScreen, Download, Loading, PictureFilled
} from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  src: { type: String, default: '' },
  title: { type: String, default: '' },
  initialScale: { type: Number, default: 1 }, // 初始缩放倍率
})

const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

// 缩放状态
const scale = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const loading = ref(false)
const error = ref(false)
const wrapperRef = ref(null)
const containerRef = ref(null)
const naturalSize = ref({ width: 0, height: 0 })

// 拖动状态
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0, offsetX: 0, offsetY: 0 })

const scalePercent = computed({
  get: () => Math.round(scale.value * 100),
  set: (val) => { scale.value = val / 100 }
})

const imageStyle = computed(() => ({
  transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
  cursor: isDragging.value ? 'grabbing' : 'grab',
}))

// ============== 缩放控制 ==============
const zoomIn = () => {
  scale.value = Math.min(5, scale.value + 0.2)
}

const zoomOut = () => {
  scale.value = Math.max(0.5, scale.value - 0.2)
}

const resetZoom = () => {
  scale.value = props.initialScale
  offsetX.value = 0
  offsetY.value = 0
}

const fitToScreen = () => {
  if (!naturalSize.value.width || !wrapperRef.value) return
  const wrapperRect = wrapperRef.value.getBoundingClientRect()
  const fitScale = Math.min(
    (wrapperRect.width - 40) / naturalSize.value.width,
    (wrapperRect.height - 40) / naturalSize.value.height,
    1
  )
  scale.value = Math.max(0.5, fitScale)
  offsetX.value = 0
  offsetY.value = 0
}

const onSliderChange = () => {
  // scalePercent 的 setter 已处理
}

// ============== 滚轮缩放 ==============
const onWheel = (e) => {
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  const newScale = Math.max(0.5, Math.min(5, scale.value + delta))
  scale.value = newScale
}

// ============== 拖动 ==============
const onMouseDown = (e) => {
  if (e.button !== 0) return // 仅左键
  isDragging.value = true
  dragStart.value = {
    x: e.clientX,
    y: e.clientY,
    offsetX: offsetX.value,
    offsetY: offsetY.value,
  }
}

const onMouseMove = (e) => {
  if (!isDragging.value) return
  offsetX.value = dragStart.value.offsetX + (e.clientX - dragStart.value.x)
  offsetY.value = dragStart.value.offsetY + (e.clientY - dragStart.value.y)
}

const onMouseUp = () => {
  isDragging.value = false
}

// ============== 图片加载 ==============
const onImageLoad = (e) => {
  loading.value = false
  error.value = false
  naturalSize.value = {
    width: e.target.naturalWidth,
    height: e.target.naturalHeight,
  }
  // 首次加载时适应屏幕
  nextTick(() => {
    if (props.initialScale === 1) {
      fitToScreen()
    } else {
      scale.value = props.initialScale
    }
  })
}

const onImageError = () => {
  loading.value = false
  error.value = true
}

// ============== 下载 ==============
const downloadImage = async () => {
  if (!props.src) return
  try {
    const response = await fetch(props.src)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = (props.title || 'cover') + '.jpg'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e) {
    // 兜底：直接打开
    window.open(props.src, '_blank')
  }
}

// ============== 关闭 ==============
const handleClose = () => {
  resetZoom()
  visible.value = false
}

// 监听 src 变化重置状态
watch(() => props.src, (newSrc) => {
  if (newSrc) {
    loading.value = true
    error.value = false
    scale.value = props.initialScale
    offsetX.value = 0
    offsetY.value = 0
  }
})

// 监听 dialog 打开重置
watch(visible, (val) => {
  if (val) {
    resetZoom()
  }
})
</script>

<style scoped>
.preview-container {
  display: flex;
  flex-direction: column;
  height: 80vh;
}

.preview-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 8px;
}

.image-wrapper {
  flex: 1;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-page, #1a1a2e);
  border-radius: 6px;
  position: relative;
  user-select: none;
}

.preview-image {
  max-width: 100%;
  max-height: 100%;
  transition: transform 0.05s ease-out;
  will-change: transform;
  pointer-events: none;
}

.loading-placeholder,
.error-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-secondary);
}

.zoom-slider {
  padding: 8px 16px 0;
  border-top: 1px solid var(--border-color);
  margin-top: 8px;
}

.zoom-slider :deep(.el-slider) {
  --el-slider-height: 4px;
  --el-slider-button-size: 16px;
}
</style>

<style>
/* 全局样式（dialog 非 scoped） */
.cover-preview-dialog .el-dialog__body {
  padding: 12px 20px;
}
</style>
