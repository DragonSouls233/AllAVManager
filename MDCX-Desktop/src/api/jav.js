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

export async function updateJavMovie(id, data) {
  return api.patch(`/jav/movies/${id}`, data)
}

export async function reloadJavMovieNfo(id) {
  return api.post(`/jav/movies/${id}/reload-nfo`)
}

export async function scrapeAllPendingJav() {
  return api.post('/jav/movies/scrape-all-pending')
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
