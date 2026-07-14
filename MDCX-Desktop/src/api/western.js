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
