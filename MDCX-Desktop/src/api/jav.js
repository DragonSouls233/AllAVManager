import { api } from './index'

export async function getJavActors() {
  return api.get('/jav/actors')
}

export async function getJavActor(id) {
  return api.get(`/jav/actors/${id}`)
}

export async function getJavMovies(params = {}) {
  return api.get('/jav/movies', { params })
}

export async function getJavMovie(id) {
  return api.get(`/jav/movies/${id}`)
}

export async function scrapeJavMovie(id) {
  return api.post(`/jav/movies/${id}/scrape`)
}

export async function scrapeAllPendingJav() {
  return api.post('/jav/movies/scrape-all-pending')
}

export async function importJavNfo(params = {}) {
  return api.post('/jav/movies/import-nfo', null, { params })
}
