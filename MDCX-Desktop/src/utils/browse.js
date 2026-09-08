// ============================================================
// 桌面端浏览页（类别/系列/演员/喜好）共享工具
// ============================================================
import { getServerUrl } from '@/api/index'
import { getServerBaseUrl, getCoverSrc } from './media'

/** 当前后端根地址（无尾斜杠） */
export function backendOrigin() {
  return getServerUrl() || getServerBaseUrl()
}

/**
 * 规整后端返回的媒体 URL（封面/头像/系列横图）。
 * 兼容三种形态：
 *  1. http(s):// 完整地址 → 原样（web 同源直连；桌面 file:// 下仍可直连绝对 http）
 *  2. 本地文件绝对路径（C:\... / \\server\...）→ 走后端 files/proxy 代理
 *  3. 站点相对路径（/api/v1/... 或裸相对）→ 补上后端 host
 */
export function normMedia(src) {
  if (!src) return ''
  if (/^https?:\/\//i.test(src)) return src
  if (/^[a-zA-Z]:[\\/]/.test(src) || /^\\\\/.test(src)) {
    return `${getServerBaseUrl()}/api/v1/files/proxy?path=${encodeURIComponent(src)}`
  }
  const base = backendOrigin()
  return src.startsWith('/') ? `${base}${src}` : `${base}/${src}`
}

/**
 * 给后端返回的影片项补上 module 标记 + 封面字段归一。
 * 桌面各模块影片 id 各自自增，封面/详情/播放一律按 {module}/movies/{id} 路由；
 * PosterCard 依赖 movie.module_type 拼封面端点，缺失会导致裂图或占位。
 * 另外里番端点把封面放在 `cover`（站内相对 URL），PosterCard 只认 cover_url，
 * 这里统一映射，保证各来源影片都能出图。
 */
export function decorateMovies(items, module) {
  if (!Array.isArray(items)) return items
  return items.map((m) => {
    const out = { ...m }
    if (!out.module_type) out.module_type = module
    if (!out.cover_url && out.cover) out.cover_url = normMedia(out.cover)
    return out
  })
}

/** 系列/类别/演员 计数缩写：1234 → 1.2k */
export function fmtCount(n) {
  const v = Number(n) || 0
  if (v >= 10000) return `${(v / 10000).toFixed(1)}w`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

/** 取系列封面：cover 字段可直接用则用，否则回退该系列首部影片封面 */
export function seriesCover(s, module) {
  const c = normMedia(s?.cover || s?.cover_url || '')
  if (c) return c
  const first = s?.movies?.[0] || s?.latest_movie
  if (first) {
    const m = decorateMovies([first], module)[0]
    return getCoverSrc(m)
  }
  return ''
}
