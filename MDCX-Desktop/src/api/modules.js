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
