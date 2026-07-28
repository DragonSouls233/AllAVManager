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
