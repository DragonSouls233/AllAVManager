import { api } from './index'

export async function getJavActors(params = {}) {
  return api.get('/jav/actors', { params })
}

export async function getJavActor(id) {
  return api.get(`/jav/actors/${id}`)
}

export async function getJavMovies(params = {}) {
  return api.get('/jav/movies', { params })
}

export async function getJavMovie(id) {
  return api.get(`/jav/movies/${id}`)
}

export async function scrapeJavMovie(id, force = false) {
  return api.post(`/jav/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

// 特殊刮削：按番号 + 指定 JAVDB/JAVBUS 链接强制重刮（先清理旧数据再重新刮削）
export async function forceScrapeJavMovie(data = {}) {
  return api.post('/jav/movies/force-scrape', data, { timeout: 180000 })
}

export async function updateJavMovie(id, data) {
  return api.patch(`/jav/movies/${id}`, data)
}

export async function reloadJavMovieNfo(id) {
  return api.post(`/jav/movies/${id}/reload-nfo`)
}

export async function scrapeAllPendingJav() {
  return api.post('/jav/movies/scrape-all-pending')
}

// 缺图电影批量补刮（完整重刮 + 兑底，后台执行）
export async function scrapeMediaRefill(data = {}) {
  return api.post('/movies/scrape-media-refill', data)
}

// 单部影片重新下载图片（封面/背景图/缩略图），后台异步执行
export async function refillMovieImages(movieId, force = false) {
  return api.post(`/movies/${movieId}/refill-images`, null, { params: { force } })
}

// 单部影片从视频截取一帧生成 poster.jpg
export async function generateMoviePoster(movieId, overwrite = false) {
  return api.post(`/movies/${movieId}/generate-poster`, null, { params: { overwrite } })
}

export async function importJavNfo(params = {}) {
  return api.post('/jav/movies/import-nfo', null, { params })
}

// ===== 演员合并 =====

export async function mergeJavActors(data) {
  return api.post('/jav/actors/merge', data)
}

export async function searchSimilarActors(name) {
  return api.get('/jav/actors/similar', { params: { name } })
}

export async function getMergeCandidates(actorId) {
  return api.get(`/jav/actors/${actorId}/merge-candidates`)
}

// ===== 播放 =====

export async function getJavPlayInfo(movieId) {
  return api.get(`/jav/movies/${movieId}/play`)
}

export async function getJavPlayUrl(movieId, protocol = 'http') {
  return api.get(`/jav/movies/${movieId}/play/external`, { params: { protocol } })
}

export async function getRelatedMovies(movieId) {
  return api.get(`/jav/movies/${movieId}/related`)
}

export async function getMovieActors(movieId) {
  return api.get(`/jav/movies/${movieId}/actors`)
}

// ===== 演员作品/时间线/标签/头像 =====

export async function getJavActorMovies(id, params = {}) {
  return api.get(`/jav/actors/${id}/movies`, { params })
}

export async function getJavActorTimeline(id) {
  return api.get(`/jav/actors/${id}/timeline`)
}

export async function getJavActorTags(id) {
  return api.get(`/jav/actors/${id}/tags`)
}

export async function uploadJavActorAvatar(id, file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/jav/actors/${id}/avatar`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export async function getJavActorAvatarUrl(id) {
  return api.get(`/jav/actors/${id}/avatar/file`)
}

// ===== 番号提取测试 =====

export async function testCodeExtract(filename) {
  return api.post('/jav/code-extract-test', { filename })
}

// ===== 文件夹归属检测 / 回填 =====

export async function getJavFolderCheck(params = {}) {
  return api.get('/jav/folder-check', { params })
}

export async function fillJavFolderCheck(data = {}) {
  return api.post('/jav/folder-check/fill', data)
}

// ===== 缺口体检 + 一键补全 =====
// 2026-10-06：原「封面问题修复」「补全 NFO 缓存」两个页面已删除，能力并入此处。
//   · 封面损坏检测 → gaps 体检现在会验图片能否解码，不再只看文件在不在
//   · 离线拷本地图   → fillJavGaps 的 local_first（默认开）
// 因此 /jav/covers/* 与 /jav/scrape/refill-nfo-cache 的前端封装已移除，
// 后端端点保留（供脚本/历史链接使用）。

// 缺口体检（只读）：返回各类缺口数量 + 明细
export async function getJavGaps(params = {}) {
  return api.get('/jav/gaps/audit', { params, timeout: 300000 })
}

// 一键补全（后台执行）
export async function fillJavGaps(data = {}) {
  return api.post('/jav/gaps/fill', data, { timeout: 60000 })
}

// 补全进度
export async function getJavGapFillStatus() {
  return api.get('/jav/gaps/fill/status')
}

// 中止批量补全：当前这部跑完即停，不再启动下一部
export async function cancelJavGapFill() {
  return api.post('/jav/gaps/fill/cancel')
}

// 刮削源序（后端 canon 是唯一真相源，前端不再硬编码源名列表）
// 🔴 不要写 r.data：api/index.js 拦截器已 `response => response.data`，
//    返回值就是后端返回体，再取 .data 会变 undefined。
export async function getSourceOrder(code = 'ABC-123') {
  return api.get('/source-order', { params: { code } })
}
