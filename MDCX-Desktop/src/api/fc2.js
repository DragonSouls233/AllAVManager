import { api } from './index'

export async function getFc2Actors() {
  return api.get('/fc2/actors')
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
