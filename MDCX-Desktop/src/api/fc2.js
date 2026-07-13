import { api } from './index'

export async function getFc2Actors() {
  return api.get('/fc2/actors')
}

export async function getFc2Actor(id) {
  return api.get(`/fc2/actors/${id}`)
}

export async function getFc2Movies(params = {}) {
  return api.get('/fc2/movies', { params })
}

export async function getFc2Movie(id) {
  return api.get(`/fc2/movies/${id}`)
}
