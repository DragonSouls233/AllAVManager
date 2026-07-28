import { api } from './index'

export async function getJavActors() {
  return api.get('/jav/actors')
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

export async function scrapeJavMovie(id) {
  return api.post(`/jav/movies/${id}/scrape`)
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

// ===== 番号提取测试 =====

export async function testCodeExtract(filename) {
  return api.post('/jav/code-extract-test', { filename })
}
