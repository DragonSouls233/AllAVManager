/**
 * 封面自适应填充：解决"封面图看不全"的裁切问题。
 *
 * 问题背景（实测 L:\data\movies\ 3023 张封面）：
 *   - anime 93.1% 是 3:4 竖版（中位 0.707，典型日式 DVD/BD 包装），
 *     塞进原来的 16:9 横向容器会裁掉 60% 画面 → 人物被切头切脚
 *   - jav 66% 竖版 + 33% 横版混排、uncensored 更混杂，
 *     任何单一比例的容器都必然裁切其中一部分
 *
 * 策略：按"裁切率"决定填充方式
 *   - 裁切率 <= 阈值 → 保持 cover（填满容器、无留白，视觉最佳）
 *   - 裁切率 >  阈值 → 切 contain（完整显示），并在容器上铺同图模糊背景，
 *                       让 contain 产生的留白变成有氛围的底色而非突兀空白
 *
 * 容器宽高比由调用方传入（3/4、2/3、16/9 等）。
 */

/** 默认裁切阈值：超过 15% 画面损失就改用 contain */
export const COVER_CROP_THRESHOLD = 0.15

/** cover 模式下会损失多少画面（0~1） */
export function cropRatio(imgAR, containerAR) {
  if (!(imgAR > 0) || !(containerAR > 0)) return 0
  return 1 - Math.min(imgAR, containerAR) / Math.max(imgAR, containerAR)
}

/** 该图是否需要改用 contain（避免裁切） */
export function needsContain(imgAR, containerAR, threshold = COVER_CROP_THRESHOLD) {
  return cropRatio(imgAR, containerAR) > threshold
}

/**
 * 绑定到 `<img @load="...">`。
 *
 * @param {Event|HTMLImageElement} target 事件对象或 img 元素
 * @param {number} containerAR 容器宽高比（宽/高），如 3/4
 * @param {number} [threshold] 可选裁切阈值
 *
 * 只依赖 DOM，不引响应式状态——列表复用/换图时 @load 会再次触发并覆盖上一次结果。
 */
export function fitCover(target, containerAR, threshold = COVER_CROP_THRESHOLD) {
  const img = target && target.target ? target.target : target
  if (!img || img.nodeType !== 1 || !img.naturalWidth || !img.naturalHeight) return

  const box = img.parentElement
  const imgAR = img.naturalWidth / img.naturalHeight
  const needContain = needsContain(imgAR, containerAR, threshold)

  img.classList.toggle('cover-contain', needContain)
  if (box) {
    box.classList.toggle('cover-blur', needContain)
    if (needContain) {
      const src = img.currentSrc || img.getAttribute('src')
      if (src) box.style.backgroundImage = `url("${src}")`
    } else {
      box.style.backgroundImage = ''
    }
  }
  // 便于调试与回归验证
  img.dataset.coverAr = imgAR.toFixed(3)
  img.dataset.coverMode = needContain ? 'contain' : 'cover'
}

/** 常用容器比例常量，避免各页面散落魔法数字 */
export const COVER_AR = {
  poster: 2 / 3, // 全局海报卡 .poster-frame
  seriesAnime: 3 / 4, // 系列卡（与 anime 封面原生比例一致）
  movieCard34: 3 / 4, // 3:4 影片卡
  wide: 16 / 9 // 剧照/横幅
}

function resolveAR(v) {
  return typeof v === 'number' && v > 0 ? v : COVER_AR.poster
}

function bindCoverFit(el, binding) {
  const ar = resolveAR(binding.value)
  // 图片已就绪（含缓存命中）→ 直接判定
  if (el.complete && el.naturalWidth) {
    fitCover(el, ar)
    return
  }
  // 否则挂一次性的 load；先清掉旧监听，避免 updated 反复叠加
  if (el.__coverFitHandler) el.removeEventListener('load', el.__coverFitHandler)
  const handler = () => fitCover(el, ar)
  el.__coverFitHandler = handler
  el.addEventListener('load', handler, { once: true })
}

/**
 * Vue 指令：`<img v-cover-fit="3/4">`（不传则按海报 2:3）
 *
 * 为什么用指令而不是 `@load`：图片命中浏览器缓存时，`load` 事件可能在
 * Vue 挂载监听器之前就已派发（实测 exe 里 48 张缓存封面全部漏判），
 * 指令在 mounted 先查 complete/naturalWidth 即可兜住这种情况。
 */
export const vCoverFit = {
  mounted(el, binding) {
    bindCoverFit(el, binding)
  },
  updated(el, binding) {
    bindCoverFit(el, binding)
  },
  unmounted(el) {
    if (el.__coverFitHandler) el.removeEventListener('load', el.__coverFitHandler)
  }
}
