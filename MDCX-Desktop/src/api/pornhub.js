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
