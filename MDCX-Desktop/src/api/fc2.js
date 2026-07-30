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

export async function updateFc2Movie(id, data) {
  return api.patch(`/fc2/movies/${id}`, data)
}

export async function scrapeFc2Movie(id, force = false) {
  return api.post(`/fc2/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

export async function reloadFc2MovieNfo(id) {
  return api.post(`/fc2/movies/${id}/reload-nfo`)
}
