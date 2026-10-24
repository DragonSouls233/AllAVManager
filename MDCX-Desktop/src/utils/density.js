/* 卡片密度：一个 CSS 变量 `--tile` 控制整个网格的列宽。
 *
 * 思路取自 peach 的 appearance/density.ts —— 密度不写在组件里，写在 <html> 的变量上，
 * 所有网格读同一个变量，切密度不用改任何组件。
 *
 * 与 peach 的差别：它只有两档且按 2 倍设计（模块 168 → 大图 336），因为它的卡片是按模块单位
 * 拼接的。MDCX 的封面是固定 3:4，不需要对齐模块，所以给三档更实用，并且**默认就是现状的 200px**，
 * 不切换时视觉零变化。
 *
 * 存 localStorage 自己的键，不进主题 JSON：密度是「怎么看」的问题，不是「什么颜色」的问题。 */

const DENSITY_KEY = 'mdcx_density'

/** 三档列宽。medium 是历史上各页面普遍在用的 200px，作为默认值保持现状。 */
export const DENSITY_TILES = {
  compact: '150px',
  medium: '200px',
  big: '300px',
}

/** 工具栏那颗切换按钮按这个顺序轮转。 */
export const DENSITY_ORDER = ['compact', 'medium', 'big']

export const DENSITY_LABELS = {
  compact: '小图',
  medium: '中图',
  big: '大图',
}

/** 读已保存的密度；存的值认不出来时按中图算（和以前一样）。 */
export function currentDensity() {
  const saved = localStorage.getItem(DENSITY_KEY)
  return DENSITY_ORDER.includes(saved) ? saved : 'medium'
}

/** 把密度写到 <html> 上。首屏调用一次，切换时再调用一次。 */
export function applyDensity(density = currentDensity()) {
  const next = DENSITY_ORDER.includes(density) ? density : 'medium'
  document.documentElement.style.setProperty('--tile', DENSITY_TILES[next])
  document.documentElement.dataset.density = next
  return next
}

/** 换下一档并落盘。返回新密度，方便调用方同步按钮状态。 */
export function cycleDensity() {
  const idx = DENSITY_ORDER.indexOf(currentDensity())
  const next = DENSITY_ORDER[(idx + 1) % DENSITY_ORDER.length]
  localStorage.setItem(DENSITY_KEY, next)
  return applyDensity(next)
}

/** 显式设一档。 */
export function setDensity(density) {
  localStorage.setItem(DENSITY_KEY, density)
  return applyDensity(density)
}
