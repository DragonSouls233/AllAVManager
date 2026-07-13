import { api } from './index'

export async function getModules() {
  return api.get('/modules')
}

export async function getModuleStats(name) {
  return api.get(`/modules/${name}/stats`)
}

export async function scanModule(name) {
  return api.post(`/modules/${name}/scan`)
}

/** 获取 modules 配置 */
export async function getModulesConfig() {
  return api.get('/modules/config')
}

/** 更新 modules 配置 */
export async function updateModulesConfig(updates) {
  return api.put('/modules/config', updates)
}

/** 切换模块启用状态 */
export async function toggleModuleEnabled(name, enabled) {
  return api.patch(`/modules/${name}/toggle`, null, { params: { enabled } })
}
