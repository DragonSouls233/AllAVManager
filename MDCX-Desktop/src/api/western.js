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
