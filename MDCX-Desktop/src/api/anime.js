import { api } from './index'

export async function getAnimeMovies(params = {}) {
  return api.get('/anime/movies', { params })
}

export async function getAnimeMovie(id) {
  return api.get(`/anime/movies/${id}`)
}

export async function getAnimeSeries(params = {}) {
  return api.get('/anime/series', { params })
}

export async function getAnimeSeriesMovies(seriesId) {
  return api.get(`/anime/series/${seriesId}/movies`)
}

export async function getAnimeMakers(params = {}) {
  return api.get('/anime/makers', { params })
}

export async function scrapeAnimeMovie(movieId) {
  return api.post(`/anime/movies/${movieId}/scrape`)
}

export async function scrapeAnimePending(limit = 20) {
  return api.post('/anime/movies/scrape-pending', null, { params: { limit } })
}

export async function scrapeAnimeDir(directory, onlyMissing = true) {
  return api.post('/anime/scrape-dir', null, { params: { directory, only_missing: onlyMissing } })
}

export async function getAnimeDirScrapeStatus(jobId) {
  return api.get(`/anime/scrape-dir/${jobId}/status`)
}

export async function getAnimeMoviePreviews(movieId) {
  return api.get(`/previews/anime/${movieId}`)
}
