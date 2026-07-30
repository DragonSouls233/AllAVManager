import { api } from './index'

export async function getUncensoredActors() {
  return api.get('/uncensored/actors')
}

export async function getUncensoredActor(id) {
  return api.get(`/uncensored/actors/${id}`)
}

export async function getUncensoredMovies(params = {}) {
  return api.get('/uncensored/movies', { params })
}

export async function getUncensoredMovie(id) {
  return api.get(`/uncensored/movies/${id}`)
}

export async function updateUncensoredMovie(id, data) {
  return api.patch(`/uncensored/movies/${id}`, data)
}

export async function scrapeUncensoredMovie(id, force = false) {
  return api.post(`/uncensored/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

export async function reloadUncensoredMovieNfo(id) {
  return api.post(`/uncensored/movies/${id}/reload-nfo`)
}

// ===== 播放 =====
export async function getUncensoredPlayInfo(movieId) {
  return api.get(`/uncensored/movies/${movieId}/play`)
}
export async function getUncensoredPlayUrl(movieId, protocol = 'http') {
  return api.get(`/uncensored/movies/${movieId}/play/external`, { params: { protocol } })
}
