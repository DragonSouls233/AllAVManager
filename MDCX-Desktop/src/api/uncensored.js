import { api } from './index'

const API = '/uncensored'

// Movies
export function getMovies(params = {}) {
  const p = Object.assign({ page: 1, page_size: 24 }, params)
  return api.get(`${API}/movies`, { params: p })
}

export function getMovie(id) {
  return api.get(`${API}/movies/${id}`)
}

export function addMovie(data) {
  return api.post(`${API}/movies`, data)
}

export function updateMovie(id, data) {
  return api.put(`${API}/movies/${id}`, data)
}

export function deleteMovie(id) {
  return api.delete(`${API}/movies/${id}`)
}

export function scrapeMovie(code) {
  return api.post(`${API}/scrape/movie`, { code })
}

export function reloadMovieNfo(movieId) {
  return api.post(`${API}/movies/${movieId}/reload-nfo`)
}

export function refreshMovieImages(movieId) {
  return api.post(`${API}/movies/${movieId}/refresh-images`)
}

export function generatePoster(movieId, data) {
  return api.post(`${API}/movies/${movieId}/poster`, data)
}

export function importNfo(data) {
  return api.post(`${API}/movies/import-nfo`, data)
}

export function getRelatedMovies(movieId, params = {}) {
  const p = Object.assign({ page: 1, page_size: 12 }, params)
  return api.get(`${API}/movies/${movieId}/related`, { params: p })
}

// Actors
export function getActors(params = {}) {
  const p = Object.assign({ page: 1, page_size: 30 }, params)
  return api.get(`${API}/actors`, { params: p })
}

export function getActor(id) {
  return api.get(`${API}/actors/${id}`)
}

export function getActorMovies(id, params = {}) {
  const p = Object.assign({ page: 1, page_size: 24 }, params)
  return api.get(`${API}/actors/${id}/movies`, { params: p })
}

export function searchActors(keyword) {
  return api.get(`${API}/actors/search`, { params: { keyword } })
}

export function addActor(data) {
  return api.post(`${API}/actors`, data)
}

export function updateActor(id, data) {
  return api.put(`${API}/actors/${id}`, data)
}

export function deleteActor(id) {
  return api.delete(`${API}/actors/${id}`)
}

export function uploadActorAvatar(id, formData) {
  return api.post(`${API}/actors/${id}/avatar`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// Studios
export function getStudios(params = {}) {
  return api.get(`${API}/studios`, { params })
}

export function getStudio(id) {
  return api.get(`${API}/studios/${id}`)
}

export function getStudioMovies(id, params = {}) {
  const p = Object.assign({ page: 1, page_size: 24 }, params)
  return api.get(`${API}/studios/${id}/movies`, { params: p })
}

export function addStudio(data) {
  return api.post(`${API}/studios`, data)
}

export function updateStudio(id, data) {
  return api.put(`${API}/studios/${id}`, data)
}

export function deleteStudio(id) {
  return api.delete(`${API}/studios/${id}`)
}

// Genres
export function getGenres(params = {}) {
  return api.get(`${API}/genres`, { params })
}

export function getGenreMovies(id, params = {}) {
  const p = Object.assign({ page: 1, page_size: 24 }, params)
  return api.get(`${API}/genres/${id}/movies`, { params: p })
}

// Scraping
export function startScraping(data) {
  return api.post(`${API}/scrape`, data)
}

export function getScrapingStatus() {
  return api.get(`${API}/scraping/status`)
}

export function getPendingScrapeCodes() {
  return api.get(`${API}/scraping/pending`)
}

export function scrapeByCode(code) {
  return api.post(`${API}/scrape/movie`, { code })
}

export function searchMovie(code) {
  return api.get(`${API}/search/movie`, { params: { code } })
}

export function scrapeBatch(data) {
  return api.post(`${API}/scrape/batch`, data)
}

export function getSpecialScrape() {
  return api.get(`${API}/scrape/special`)
}

export function executeSpecialScrape(data) {
  return api.post(`${API}/scrape/special`, data)
}

export function testCode(data) {
  return api.post(`${API}/test/code`, data)
}

export function checkFolder(folderPath) {
  return api.post(`${API}/folders/check`, { folder_path: folderPath })
}

export function getMediaInfo(movieId) {
  return api.get(`${API}/movies/${movieId}/media`)
}

export function refillMedia(movieId, data) {
  return api.post(`${API}/movies/${movieId}/media/refill`, data)
}

export function getCrawlers() {
  return api.get('/crawlers')
}

export function getCrawlersStats() {
  return api.get(`${API}/crawlers/stats`)
}

export function setCrawlerEnabled(id, enabled) {
  return api.put(`${API}/crawlers/${id}/enabled`, { enabled })
}

export function setCrawlerPriority(id, priority) {
  return api.put(`${API}/crawlers/${id}/priority`, { priority })
}

export function getCrawlerLogs(params = {}) {
  return api.get(`${API}/crawlers/logs`, { params })
}

export function getCrawlerSettings() {
  return api.get(`${API}/crawlers/settings`)
}

export function updateCrawlerSettings(data) {
  return api.put(`${API}/crawlers/settings`, data)
}

export function getDirectoryMovies(data) {
  return api.post(`${API}/movies/scan`, data)
}

export function refreshCoverImages(data) {
  return api.post(`${API}/covers/refresh`, data)
}

export function detectCoverProblems(params = {}) {
  return api.get(`${API}/covers/problems`, { params })
}

export function getStats() {
  return api.get(`${API}/stats`)
}

export function getTags(params = {}) {
  return api.get(`${API}/tags`, { params })
}

export function getFavoriteMovies(params = {}) {
  const p = Object.assign({ page: 1, page_size: 24 }, params)
  return api.get(`${API}/favorites`, { params: p })
}

export function toggleFavorite(movieId) {
  return api.post(`${API}/favorites/${movieId}`)
}

export function getSubscriptions(params = {}) {
  return api.get(`${API}/subscriptions`, { params })
}

// Playback
export function getUncensoredPlayInfo(movieId) {
  return api.get(`${API}/play/${movieId}/info`)
}

export function getUncensoredPlayUrl(movieId) {
  return api.get(`${API}/play/${movieId}/url`)
}
