import { api } from './index'

export async function getFc2Actors(params = {}) {
  return api.get('/fc2/actors', { params })
}

export async function getFc2Actor(id) {
  return api.get(`/fc2/actors/${id}`)
}

export async function getFc2Movies(params = {}) {
  return api.get('/fc2/movies', { params })
}

export async function getFc2Movie(id) {
  return api.get(`/fc2/movies/${id}`)
}

export async function updateFc2Movie(id, data) {
  return api.patch(`/fc2/movies/${id}`, data)
}

export async function scrapeFc2Movie(id, force = false) {
  return api.post(`/fc2/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

export async function reloadFc2MovieNfo(id) {
  return api.post(`/fc2/movies/${id}/reload-nfo`)
}

// ===== 播放 =====
export async function getFc2PlayInfo(movieId) {
  return api.get(`/fc2/movies/${movieId}/play`)
}
export async function getFc2PlayUrl(movieId, protocol = 'http') {
  return api.get(`/fc2/movies/${movieId}/play/external`, { params: { protocol } })
}

// ===== 详情页相关推荐（通用详情页使用） =====
export async function getRelatedMovies(movieId) {
  return api.get(`/fc2/movies/${movieId}/related`)
}
export async function getMovieActors(movieId) {
  return api.get(`/fc2/movies/${movieId}/actors`)
}

// ===== 预览图 =====
export async function getFc2Previews(movieId, refresh = false) {
  return api.get(`/fc2/movies/${movieId}/previews`, { params: refresh ? { refresh: true } : undefined })
}

// ===== 封面裁剪 =====
export async function fc2FaceCrop(movieId, data = {}) {
  return api.post(`/fc2/movies/${movieId}/face-crop`, data, { timeout: 120000 })
}

// ===== 演员资料补全 =====
export async function fc2ScrapeActor(movieId) {
  return api.post(`/fc2/movies/${movieId}/scrape-actor`)
}

// ===== 封面文件代理 =====
export function getFc2CoverUrl(movieId) {
  return `/api/v1/fc2/movies/${movieId}/cover/file`
}

// ===== 视频文件代理 =====
export function getFc2PlayFileUrl(movieId) {
  return `/api/v1/fc2/movies/${movieId}/play/file`
}

// ===== 扫描 =====
export async function triggerFc2Scan() {
  return api.post('/fc2/scan')
}

// ===== 批量刮削 =====
export async function scrapeAllPendingFc2() {
  return api.post('/fc2/movies/scrape-all-pending')
}

// ===== 演员相关 =====
export async function getFc2ActorMovies(actorId) {
  return api.get(`/fc2/actors/${actorId}/movies`)
}

// ===== 演员头像文件代理 =====
export function getFc2ActorAvatarUrl(actorId) {
  return `/api/v1/fc2/actors/${actorId}/avatar/file`
}

// ===== 批量同步演员头像 =====
export async function syncFc2ActorAvatars() {
  return api.post('/fc2/actors/sync-avatars')
}