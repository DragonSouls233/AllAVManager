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
