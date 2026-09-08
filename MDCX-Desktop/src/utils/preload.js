/**
 * 海报悬停预加载。
 * 在网格中悬停某张卡片时，预热其后若干张卡片的封面（这些卡片可能还在懒加载或尚未进入视口），
 * 让横向/纵向滚动与翻页更跟手。卡片根元素需带 data-cover 属性（PosterCard 已设置）。
 */

export function preloadImage(src) {
  if (!src || typeof window === 'undefined') return
  const img = new Image()
  img.decoding = 'async'
  img.src = src
}

/**
 * 预热 el 之后 count 个兄弟海报的封面。
 * el 应为 .poster-card 根节点，其父节点为网格容器，子节点即各海报卡片。
 */
export function preloadNeighbors(el, count = 4) {
  if (!el || !el.parentElement) return
  const parent = el.parentElement
  const siblings = parent.children
  const idx = Array.prototype.indexOf.call(siblings, el)
  if (idx < 0) return
  for (let i = idx + 1; i <= idx + count && i < siblings.length; i++) {
    const cover = siblings[i] && siblings[i].getAttribute && siblings[i].getAttribute('data-cover')
    if (cover) preloadImage(cover)
  }
}
