import { api } from './index'

export async function startDownload(url, outputPath = '', engine = 'auto', metadata = {}) {
  return api.post('/download/start', { url, output_path: outputPath, engine, metadata })
}

export async function getDownloadStatus(taskId) {
  return api.get(`/download/status/${taskId}`)
}

export async function listDownloads(status = null) {
  const params = {}
  if (status) params.status = status
  return api.get('/download/list', { params })
}

export async function cancelDownload(taskId) {
  return api.post(`/download/cancel/${taskId}`)
}

export async function getEngines() {
  return api.get('/download/engines')
}

export async function getUrlInfo(url) {
  return api.get('/download/info', { params: { url } })
}

export async function getDownloadCacheStats() {
  return api.get('/download/cache/stats')
}

export async function getDownloadManagerStats() {
  return api.get('/download/stats')
}
