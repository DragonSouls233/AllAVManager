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
