import { api } from './index'

const API = '/uncensored'

// Movies
// 🔴 2026-10-20：默认 page_size 必须是 24 吗？—— 不是。这里的默认值会被
//   Object.assign 覆盖 params，所以只要调用方显式传了 page_size 就没问题；
//   但此前 store 传的是 page/page_size、后端只认 skip/limit，才导致分页失效。
//   现在后端两套命名都支持，保持 page/page_size 即可。
export function getMovies(params = {}) {
  const p = Object.assign({ page: 1, page_size: 24 }, params)
  return api.get(`${API}/movies`, { params: p })
}

export function getMovie(id) {
  return api.get(`${API}/movies/${id}`)
}

// 🔴 2026-10-20 修复影片详情页「影片数据加载失败」：
//   views/MovieDetail.vue 按模块动态加载 api/{module}.js，并统一按「模块前缀」命名取函数
//   （getUncensoredMovie / updateUncensoredMovie / scrapeUncensoredMovie /
//     reloadUncensoredMovieNfo）—— 见 MovieDetail.vue::loadApi()。
//   但本文件原本只有无前缀的通用名（getMovie / updateMovie / scrapeMovie /
//     reloadMovieNfo）⇒ loadApi 拿到的全是 undefined ⇒ api.get() 抛 TypeError
//   ⇒ catch 里 movie=null ⇒ 页面显示「影片数据加载失败 / 服务器繁忙或请求超时」。
//   （jav/fc2/western/pornhub/chinese 五个模块都有带前缀的函数，只有无码这组缺失。）
//
//   这里补齐**别名**而不是去改 MovieDetail.vue：别名是纯新增、不影响既有调用方
//   （无码库/演员库页面仍在用 getMovie/updateMovie 等通用名）。
//
//   注意 scrape 的参数语义差异：
//   - 本文件原有 scrapeMovie(code) 收的是「番号」，打 POST /uncensored/scrape/movie；
//   - 详情页统一调 api.scrape(movieId, force) 传的是「影片 id」，
//     所以别名要打按 id 的 POST /uncensored/movies/{id}/scrape（后端已存在该端点）。
export async function getUncensoredMovie(id) {
  return api.get(`${API}/movies/${id}`)
}

export async function updateUncensoredMovie(id, data) {
  return api.put(`${API}/movies/${id}`, data)
}

export async function scrapeUncensoredMovie(id, force = false) {
  return api.post(`${API}/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

export async function reloadUncensoredMovieNfo(id) {
  return api.post(`${API}/movies/${id}/reload-nfo`)
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
  // 后端该端点内部会同步调 engine.scrape_number（要联网抓资源），
  // 可能耗时几十秒 ⇒ 给足超时，避免前端先超时报"失败"。
  return api.post(`${API}/movies/${movieId}/refresh-images`, null, { timeout: 180000 })
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

export function downloadActorAvatar(id) {
  return api.post(`${API}/actors/${id}/avatar`)
}

// ===== 演员头像文件代理 =====
export function getActorAvatarFileUrl(id) {
  return `/api/v1${API}/actors/${id}/avatar/file`
}

// ===== 批量同步演员头像 =====
export function syncActorAvatars() {
  return api.post(`${API}/actors/sync-avatars`)
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
  return api.post(`${API}/crawlers/${id}/priority`, { priority })
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
