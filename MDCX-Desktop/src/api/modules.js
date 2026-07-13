import { api } from './index'

export async function getModules() { return api.get('/modules') }
export async function getModuleStats(name) { return api.get(`/modules/${name}/stats`) }
export async function scanModule(name) { return api.post(`/modules/${name}/scan`) }
export async function getModulesConfig() { return api.get('/modules/config') }
export async function updateModulesConfig(updates) { return api.put('/modules/config', updates) }
export async function toggleModuleEnabled(name, enabled) { return api.patch(`/modules/${name}/toggle`, null, { params: { enabled } }) }

/** 跨模块聚合影片列表 */
export async function getUnifiedMovies(params = {}) { return api.get('/modules/unified/movies', { params }) }

/** 跨模块全局搜索 */
export async function unifiedSearch(keyword, params = {}) { return api.get('/modules/unified/search', { params: { keyword, ...params } }) }
