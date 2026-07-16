export const getServerBaseUrl = () => {
  // 媒体资源(封面/头像/文件代理)始终由托管当前页面的同一后端提供，
  // 因此固定使用页面真实来源(window.location.origin)，
  // 不受 localStorage 中 serverUrl 旧配置影响——
  // 否则一旦 serverUrl 被填成内网/旧地址，浏览器会从连不通的 host 取图→全部裂图。
  // API 请求仍由 src/api/index.js 单独读取 serverUrl 以支持跨域后端。
  return window.location.origin || ''
}

export const defaultAvatar = (name = '') => {
  const text = encodeURIComponent((name || '?').slice(0, 1).toUpperCase())
  return `data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Crect width='120' height='120' rx='60' fill='%23409eff'/%3E%3Ctext x='60' y='70' text-anchor='middle' font-size='48' font-family='Arial' fill='white'%3E${text}%3C/text%3E%3C/svg%3E`
}

export const defaultCover = (code = '') => {
  const text = encodeURIComponent(code || 'MDCX')
  return `data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='450' viewBox='0 0 320 450'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop stop-color='%23111827'/%3E%3Cstop offset='1' stop-color='%23374151'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='320' height='450' fill='url(%23g)'/%3E%3Ctext x='160' y='215' text-anchor='middle' font-size='28' font-family='Arial' font-weight='700' fill='%23ffffff'%3EMDCX%3C/text%3E%3Ctext x='160' y='255' text-anchor='middle' font-size='18' font-family='Arial' fill='%239ca3af'%3E${text}%3C/text%3E%3C/svg%3E`
}

export const getActorAvatarUrl = (actor) => {
  if (!actor?.id) {
    return defaultAvatar(actor?.name)
  }
  return `${getServerBaseUrl()}/api/v1/actors/${actor.id}/avatar/file`
}

/**
 * 按 actor_id 获取头像 URL(用于表格行中只有 actor_id 的场景)
 * @param {number|string} actorId - 演员 ID
 * @param {string} [version] - 缓存版本参数(可选,避免浏览器缓存)
 */
export const getActorAvatarUrlById = (actorId, version) => {
  if (!actorId) return defaultAvatar()
  const v = version ? `?t=${encodeURIComponent(version)}` : ''
  return `${getServerBaseUrl()}/api/v1/actors/${actorId}/avatar/file${v}`
}

/**
 * 获取文件代理 URL(用于在 <img>/<video> 标签中通过后端代理访问本地文件)
 * @param {string} path - 本地文件绝对路径
 */
export const getFileProxyUrl = (path) => {
  if (!path) return ''
  return `${getServerBaseUrl()}/api/v1/files/proxy?path=${encodeURIComponent(path)}`
}

/**
 * 获取模块影片封面 URL
 * 处理三种情况：
 *  1. cover_url 是 HTTP URL → 直接使用
 *  2. cover_url 是本地路径 → 通过文件代理
 *  3. cover_url 为空 → 返回占位图
 */
export const getCoverSrc = (movie) => {
  if (movie?.cover_url) {
    if (/^https?:\/\//i.test(movie.cover_url)) {
      return movie.cover_url
    }
    return getFileProxyUrl(movie.cover_url)
  }
  return defaultCover(movie?.code || movie?.title)
}

/**
 * 获取模块演员头像 URL
 * 处理三种情况：
 *  1. avatar_url 是 HTTP URL → 直接使用
 *  2. avatar_url 是本地路径 → 通过文件代理
 *  3. avatar_url 为空 → 返回占位图
 */
export const getAvatarSrc = (actor) => {
  if (actor?.avatar_url) {
    if (/^https?:\/\//i.test(actor.avatar_url)) {
      return actor.avatar_url
    }
    return getFileProxyUrl(actor.avatar_url)
  }
  return defaultAvatar(actor?.name)
}

/**
 * 获取字幕文件 URL(用于 <track> 标签加载 VTT/SRT)
 * @param {number|string} movieId - 影片 ID
 * @param {string} [subPath] - 字幕文件子路径(可选)
 */
export const getSubtitleFileUrl = (movieId, subPath) => {
  const base = `${getServerBaseUrl()}/api/v1/player/${movieId}/subtitles/file`
  return subPath ? `${base}?path=${encodeURIComponent(subPath)}` : base
}

/**
 * 获取影片封面 URL。
 * 关键修复：
 *  1. 始终用 window.location.origin（页面真实来源），不再依赖 localStorage 中可能被配错的 serverUrl，
 *     否则封面会请求到一个浏览器连不通的 host → 全部裂图。
 *  2. 不再拼接 ?t=Windows路径 参数——该参数含反斜杠+中文，经反向代理/隧道时易被错误转发导致 404。
 *     后端本身能凭 DB 中的 cover_url 直接解析封面（已验证不带 t 也返回 200 真实 JPEG）。
 *  只要 movie.id 存在就请求 /cover/file；仅当 id 缺失才返回占位图。
 */
export const getMovieCoverUrl = (movie) => {
  if (!movie?.id) {
    return defaultCover(movie?.code)
  }
  return `${getServerBaseUrl()}/api/v1/movies/${movie.id}/cover/file`
}

export const getMoviePosterUrl = (movie) => {
  if (!movie?.id) {
    return defaultCover(movie?.code)
  }
  return `${getServerBaseUrl()}/api/v1/movies/${movie.id}/poster/file`
}

export const getMovieThumbUrl = (movie) => {
  if (!movie?.id) {
    return defaultCover(movie?.code)
  }
  return `${getServerBaseUrl()}/api/v1/movies/${movie.id}/thumb/file`
}

/**
 * 根据图片模式获取影片主图 URL
 * @param {Object} movie - 影片对象
 * @param {string} imageMode - 'poster' | 'thumbnail'
 */
export const getMovieImageUrl = (movie, imageMode = 'poster') => {
  if (imageMode === 'thumbnail') {
    return getMovieThumbUrl(movie)
  }
  return getMovieCoverUrl(movie)
}
