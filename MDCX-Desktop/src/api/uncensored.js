import { api } from './index'

export async function getUncensoredActors() {
  return api.get('/uncensored/actors')
}

export async function getUncensoredMovies(params = {}) {
  return api.get('/uncensored/movies', { params })
}
