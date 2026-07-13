import { api } from './index'

/** 获取 FC2 影片列表 */
export async function getFc2Movies(params = {}) {
  return api.get('/fc2/movies', { params })
}

/** 获取 FC2 影片详情 */
export async function getFc2Movie(id) {
  return api.get(`/fc2/movies/${id}`)
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
