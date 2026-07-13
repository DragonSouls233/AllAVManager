import { api } from './index'

export async function getFc2Movies(params = {}) {
  return api.get('/fc2/movies', { params })
}
