import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const VIEW_MODE_KEY = 'mdcx_view_mode'
const IMAGE_MODE_KEY = 'mdcx_image_mode'
const POSTER_MODE_KEY = 'mdcx_poster_mode'

/**
 * 视图模式：
 * - compact: 紧凑模式（小卡片，仅显示封面+番号+标题，更多列）
 * - standard: 标准模式（默认，封面+完整信息）
 * - detail: 详细模式（横向卡片，封面+完整信息+简介）
 */
const VIEW_MODES = ['compact', 'standard', 'detail']

/**
 * 图片模式：
 * - poster: 封面图（cover_url，2:3 竖版海报）
 * - thumbnail: 缩略图（thumb_url，视频帧截图）
 */
const IMAGE_MODES = ['poster', 'thumbnail']

/**
 * 海报模式（B2 海报马赛克纯净模式）：
 * - full: 完整显示海报
 * - mosaic: 马赛克模糊（blur + 像素化）
 * - number_only: 纯净模式，隐藏海报仅显示番号
 */
const POSTER_MODES = ['full', 'mosaic', 'number_only']

export const useUiStore = defineStore('ui', () => {
  // 视图模式
  const viewMode = ref(localStorage.getItem(VIEW_MODE_KEY) || 'standard')
  // 图片模式
  const imageMode = ref(localStorage.getItem(IMAGE_MODE_KEY) || 'poster')
  // 海报模式（B2 纯净模式）
  const posterMode = ref(localStorage.getItem(POSTER_MODE_KEY) || 'full')

  const viewModeLabel = computed(() => {
    const labels = {
      compact: '紧凑',
      standard: '标准',
      detail: '详细',
    }
    return labels[viewMode.value] || '标准'
  })

  const imageModeLabel = computed(() => {
    const labels = {
      poster: '封面',
      thumbnail: '缩略图',
    }
    return labels[imageMode.value] || '封面'
  })

  const posterModeLabel = computed(() => {
    const labels = {
      full: '完整',
      mosaic: '马赛克',
      number_only: '仅番号',
    }
    return labels[posterMode.value] || '完整'
  })

  function setViewMode(mode) {
    if (!VIEW_MODES.includes(mode)) return
    viewMode.value = mode
    localStorage.setItem(VIEW_MODE_KEY, mode)
  }

  function setImageMode(mode) {
    if (!IMAGE_MODES.includes(mode)) return
    imageMode.value = mode
    localStorage.setItem(IMAGE_MODE_KEY, mode)
  }

  function setPosterMode(mode) {
    if (!POSTER_MODES.includes(mode)) return
    posterMode.value = mode
    localStorage.setItem(POSTER_MODE_KEY, mode)
  }

  function toggleViewMode() {
    const idx = VIEW_MODES.indexOf(viewMode.value)
    const next = VIEW_MODES[(idx + 1) % VIEW_MODES.length]
    setViewMode(next)
  }

  function toggleImageMode() {
    const idx = IMAGE_MODES.indexOf(imageMode.value)
    const next = IMAGE_MODES[(idx + 1) % IMAGE_MODES.length]
    setImageMode(next)
  }

  function togglePosterMode() {
    const idx = POSTER_MODES.indexOf(posterMode.value)
    const next = POSTER_MODES[(idx + 1) % POSTER_MODES.length]
    setPosterMode(next)
  }

  return {
    viewMode,
    imageMode,
    posterMode,
    viewModeLabel,
    imageModeLabel,
    posterModeLabel,
    setViewMode,
    setImageMode,
    setPosterMode,
    toggleViewMode,
    toggleImageMode,
    togglePosterMode,
    VIEW_MODES,
    IMAGE_MODES,
    POSTER_MODES,
  }
})
