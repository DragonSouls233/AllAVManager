import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  startDownload, getDownloadStatus, listDownloads,
  cancelDownload, getEngines, getUrlInfo,
  getDownloadCacheStats, getDownloadManagerStats,
} from '@/api/download'

export const useDownloadStore = defineStore('download', () => {
  const tasks = ref([])
  const engines = ref([])
  const stats = ref({})
  const cacheStats = ref({})
  const loading = ref(false)
  const polling = ref(false)
  let pollInterval = null

  async function loadTasks(status = null) {
    loading.value = true
    try {
      const res = await listDownloads(status)
      tasks.value = res.tasks || []
    } finally {
      loading.value = false
    }
  }

  async function loadEngines() {
    const res = await getEngines()
    engines.value = res.engines || []
  }

  async function loadStats() {
    const [s, cs] = await Promise.all([
      getDownloadManagerStats(),
      getDownloadCacheStats(),
    ])
    stats.value = s || {}
    cacheStats.value = cs || {}
  }

  async function submit(url, outputPath = '', engine = 'auto', metadata = {}) {
    const res = await startDownload(url, outputPath, engine, metadata)
    await loadTasks()
    return res
  }

  async function cancel(taskId) {
    await cancelDownload(taskId)
    await loadTasks()
  }

  async function queryInfo(url) {
    return await getUrlInfo(url)
  }

  function startPolling(interval = 3000) {
    if (pollInterval) return
    polling.value = true
    pollInterval = setInterval(() => {
      const active = tasks.value.filter(t => t.status === 'queued' || t.status === 'downloading')
      if (active.length > 0) loadTasks()
    }, interval)
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
    polling.value = false
  }

  return {
    tasks, engines, stats, cacheStats, loading, polling,
    loadTasks, loadEngines, loadStats, submit, cancel, queryInfo,
    startPolling, stopPolling,
  }
})
