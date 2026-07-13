import { api } from './index'

export async function getPornhubMovies(params = {}) {
  return api.get('/pornhub/movies', { params })
}
