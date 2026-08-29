import { api } from './index'

export async function getPornhubActors() {
  return api.get('/pornhub/actors')
}

export async function getPornhubActor(id) {
  return api.get(`/pornhub/actors/${id}`)
}

export async function getPornhubMovies(params = {}) {
  return api.get('/pornhub/movies', { params })
}

export async function getPornhubMovie(id) {
  return api.get(`/pornhub/movies/${id}`)
}

/** 后台启动 PORNHub 断点续扫（目录级 checkpoint，可反复运行） */
export async function triggerPornhubResumableScan(rescan = false) {
  return api.post('/pornhub/scan', null, { params: { rescan } })
}

export async function updatePornhubMovie(id, data) {
  return api.patch(`/pornhub/movies/${id}`, data)
}

export async function scrapePornhubMovie(id, force = false) {
  return api.post(`/pornhub/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

export async function reloadPornhubMovieNfo(id) {
  return api.post(`/pornhub/movies/${id}/reload-nfo`)
}

// ===== 演员资料/头像刮削 =====

export async function scrapePornhubActorProfile(id) {
  return api.post(`/pornhub/actors/${id}/scrape-profile`)
}

export async function scrapeAllPornhubActorProfilesEnhanced() {
  return api.post('/pornhub/actors/scrape-all-profiles-enhanced')
}

// ===== 对比查重 =====

export async function pornhubCompare(data) {
  return api.post('/pornhub/compare', data)
}

export async function pornhubCompareStatus() {
  return api.get('/pornhub/compare/status')
}

export async function pornhubTestNormalize(title) {
  return api.post('/pornhub/compare/test-normalize', { title })
}

export async function pornhubScanLocal(directory) {
  return api.post('/pornhub/compare/scan-local', { directory })
}

// ===== 播放 =====
export async function getPornhubPlayInfo(movieId) {
  return api.get(`/pornhub/movies/${movieId}/play`)
}
export async function getPornhubPlayUrl(movieId, protocol = 'http') {
  return api.get(`/pornhub/movies/${movieId}/play/external`, { params: { protocol } })
}

// ===== 演员列表增强 =====
export async function getPornhubActorsPage(params = {}) {
  return api.get('/pornhub/actors', { params })
}
export async function getPornhubActorNationalities() {
  return api.get('/pornhub/actors/nationalities')
}
export async function setPornhubActorProfileUrl(id, url) {
  return api.post(`/pornhub/actors/${id}/set-profile-url`, { url })
}
export async function updatePornhubActor(id, data) {
  return api.patch(`/pornhub/actors/${id}`, data)
}
export function pornhubActorAvatarUrl(id) {
  return `/api/pornhub/actors/${id}/avatar/file`
}

// ===== 影片-演员关联 =====
export async function getPornhubMovieActors(movieId) {
  return api.get(`/pornhub/movies/${movieId}/actors`)
}
export async function getPornhubActorMovies(actorId) {
  return api.get(`/pornhub/actors/${actorId}/movies`)
}
export async function syncPornhubMovieActors() {
  return api.post('/pornhub/movies/sync-actors')
}

// ===== 影片批量 =====
export async function batchPornhubRefetchCovers(params = {}) {
  return api.post('/pornhub/movies/batch/refetch-covers', null, { params })
}
export async function batchPornhubGeneratePreviews(params = {}) {
  return api.post('/pornhub/movies/batch/generate-previews', null, { params })
}
export async function batchPornhubDownloadAvatars(params = {}) {
  return api.post('/pornhub/actors/batch/download-avatars', null, { params })
}
export async function generatePornhubPreview(id, cols = 4, rows = 4, thumbW = 320) {
  return api.post(`/pornhub/movies/${id}/generate-cover`, null, {
    params: { cols, rows, thumb_w: thumbW }
  })
}
export async function generatePornhubCoverEnhanced(id, width = 480, quality = 85) {
  return api.post(`/pornhub/movies/generate-cover-enhanced/${id}`, null, {
    params: { width, quality }
  })
}
export async function rescrapePornhubMovie(id) {
  return api.post(`/pornhub/movies/${id}/rescrape`, null, { timeout: 180000 })
}
export function pornhubPreviewUrl(id) {
  return `/api/pornhub/movies/${id}/preview/file`
}

// ===== 外部 L:\data\PORNHUB\models.db =====
export async function pornhubExternalStatus() {
  return api.get('/pornhub/external/status')
}
export async function pornhubExternalSearch(name) {
  return api.get('/pornhub/external/search', { params: { name } })
}
export async function pornhubExternalSeedActor(name) {
  return api.post('/pornhub/external/seed-actor', { name })
}
export async function pornhubExternalSeedAll(limit = 200) {
  return api.post('/pornhub/external/seed-all', null, { params: { limit } })
}
export async function pornhubBackfillUrls() {
  return api.post('/pornhub/actors/backfill-urls')
}
export async function pornhubSeedFromExternal() {
  return api.post('/pornhub/actors/seed-from-external')
}
