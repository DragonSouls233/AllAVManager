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
