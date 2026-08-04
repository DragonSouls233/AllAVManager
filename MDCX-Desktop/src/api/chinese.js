import { api } from './index'

/** 获取国产演员列表 */
export async function getChineseActors() {
  return api.get('/chinese/actors')
}

/** 从文件夹同步国产演员 */
export async function syncChineseFolderActors() {
  return api.post('/chinese/actors/scan-folders')
}

/** 获取国产影片列表 */
export async function getChineseMovies(params = {}) {
  return api.get('/chinese/movies', { params })
}

/** 获取国产影片详情 */
export async function getChineseMovie(id) {
  return api.get(`/chinese/movies/${id}`)
}

/** 更新国产影片 */
export async function updateChineseMovie(id, data) {
  return api.patch(`/chinese/movies/${id}`, data)
}

/** 刮削国产影片 */
export async function scrapeChineseMovie(id, force = false) {
  return api.post(`/chinese/movies/${id}/scrape`, null, { params: { force }, timeout: 180000 })
}

/** 从 NFO 重载国产影片 */
export async function reloadChineseMovieNfo(id) {
  return api.post(`/chinese/movies/${id}/reload-nfo`)
}

/** 获取国产命名规则 */
export async function getChineseNameRules() {
  return api.get('/chinese/name-rules')
}

/** 更新国产命名规则 */
export async function updateChineseNameRules(data) {
  return api.put('/chinese/name-rules', data)
}

/** 测试去广告效果 */
export async function testChineseNameClean(title) {
  return api.post('/chinese/name-rules/clean', { title })
}

/** 批量去广告重命名 */
export async function batchCleanChineseNames(ids) {
  return api.post('/chinese/name-rules/batch-clean', { ids })
}

/** 获取模块列表 */
export async function getModules() {
  return api.get('/modules')
}

/** 获取模块统计 */
export async function getModuleStats(name) {
  return api.get(`/modules/${name}/stats`)
}

/** 触发模块扫描 */
export async function scanModule(name) {
  return api.post(`/modules/${name}/scan`)
}

// ===== 播放 =====
export async function getChinesePlayInfo(movieId) {
  return api.get(`/chinese/movies/${movieId}/play`)
}
export async function getChinesePlayUrl(movieId, protocol = 'http') {
  return api.get(`/chinese/movies/${movieId}/play/external`, { params: { protocol } })
}

// ===== 详情页相关推荐（通用详情页使用） =====
export async function getRelatedMovies(movieId) {
  return api.get(`/chinese/movies/${movieId}/related`)
}
export async function getMovieActors(movieId) {
  return api.get(`/chinese/movies/${movieId}/actors`)
}
