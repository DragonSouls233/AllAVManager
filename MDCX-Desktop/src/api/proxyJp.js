import { api } from './index'

// 日本节点（DMM/FANZA 出口）管理。
// 注意：refresh 可能会逐个起临时 xray 实测几十个节点，耗时可达数十秒，
// 所以必须放大超时，否则前端会先超时断开（后端仍在跑，白白浪费一次探测）。
const LONG_TIMEOUT = 300000

export async function getJpStatus(checkExit = true) {
  return api.get('/proxy/jp/status', { params: { check_exit: checkExit } })
}

export async function getJpNodes() {
  return api.get('/proxy/jp/nodes')
}

export async function getJpConfig() {
  return api.get('/proxy/jp/config')
}

export async function saveJpConfig(payload) {
  return api.put('/proxy/jp/config', payload)
}

// 测试订阅源：只拉取不解节点编码，3 秒内出结果。
// 换地址后先测这个再刷新 —— 刷新要逐个实测，地址写错时纯属浪费时间。
export async function testJpSubscription(subUrls = null) {
  return api.post('/proxy/jp/test', { sub_urls: subUrls }, { timeout: 120000 })
}

export async function refreshJpNodes(payload = {}) {
  return api.post('/proxy/jp/refresh', payload, { timeout: LONG_TIMEOUT })
}

export async function addJpNode(url) {
  return api.post('/proxy/jp/nodes', { url })
}

export async function clearJpNodes() {
  return api.delete('/proxy/jp/nodes')
}

export async function startJpProxy() {
  return api.post('/proxy/jp/start', null, { timeout: 60000 })
}

export async function stopJpProxy() {
  return api.post('/proxy/jp/stop', null, { timeout: 60000 })
}

export async function restartJpProxy() {
  return api.post('/proxy/jp/restart', null, { timeout: 60000 })
}
