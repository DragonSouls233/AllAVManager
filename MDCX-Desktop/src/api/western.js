import { api } from './index'

export async function getWesternMovies(params = {}) {
  return api.get('/western/movies', { params })
}

export async function getWesternMovie(id) {
  return api.get(`/western/movies/${id}`)
}

export async function getWesternActors() {
  return api.get('/western/actors')
}

export async function getWesternActor(id) {
  return api.get(`/western/actors/${id}`)
}

export async function scanWesternMedia() {
  return api.post('/western/scan')
}

export async function updateWesternMovie(id, data) {
  return api.patch(`/western/movies/${id}`, data)
}

export async function scrapeWesternMovie(id, force = false) {
  return api.post(`/western/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

export async function reloadWesternMovieNfo(id) {
  return api.post(`/western/movies/${id}/reload-nfo`)
}

// ===== 播放 =====
export async function getWesternPlayInfo(movieId) {
  return api.get(`/western/movies/${movieId}/play`)
}
export async function getWesternPlayUrl(movieId, protocol = 'http') {
  return api.get(`/western/movies/${movieId}/play/external`, { params: { protocol } })
}

// ===== 影片详情 =====
export async function getWesternMovieActors(movieId) {
  return api.get(`/western/movies/${movieId}/actors`)
}

export async function getWesternRelatedMovies(movieId) {
  return api.get(`/western/movies/${movieId}/related`)
}

// ===== 演员相关 =====
export async function getWesternActorMovies(actorId) {
  return api.get(`/western/actors/${actorId}/movies`)
}

export async function scrapeWesternActor(id) {
  return api.post(`/western/actors/${id}/scrape`, null, { timeout: 60000 })
}

export async function updateWesternActor(id, data) {
  return api.put(`/western/actors/${id}`, data)
}

export async function scrapeActorBatch() {
  return api.post('/western/actors/scrape-batch')
}

// ===== 封面文件代理 =====
export function getWesternCoverUrl(movieId) {
  return `/api/v1/western/movies/${movieId}/cover/file`
}

// ===== 演员头像文件代理 =====
export function getWesternActorAvatarUrl(actorId) {
  return `/api/v1/western/actors/${actorId}/avatar/file`
}

// ===== 批量同步演员头像 =====
export async function syncWesternActorAvatars() {
  return api.post('/western/actors/sync-avatars')
}

// ===== 批量刮削 =====
export async function scrapeAllPendingWestern() {
  return api.post('/western/movies/scrape-all-pending')
}

// ===== 播放文件代理 =====
export function getWesternPlayFileUrl(movieId) {
  return `/api/v1/western/movies/${movieId}/play/file`
}

// ===== NFO =====
export async function getWesternNfoTemplates() {
  return api.get('/western/nfo-templates')
}

export async function updateWesternNfoTemplate(template, data) {
  return api.put(`/western/nfo-templates/${template}`, data)
}

export async function exportWesternNfo(movieId) {
  return api.post(`/western/movies/${movieId}/export-nfo`)
}
