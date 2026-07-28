import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getJavMovies, getJavMovie, getJavActors, getJavActor, scrapeJavMovie, scrapeAllPendingJav, importJavNfo } from '@/api/jav'
import { scanModule } from '@/api/modules'

export const useJavStore = defineStore('jav', () => {
  const movies = ref([])
  const total = ref(0)
  const actors = ref([])
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(24)
  const pendingCount = ref(0)
  const scraping = ref(false)
  const scrapingStatus = ref('')

  async function loadMovies(params = {}) {
    loading.value = true
    try {
      const res = await getJavMovies({ skip: (page.value - 1) * pageSize.value, limit: pageSize.value, ...params })
      movies.value = res.items || []
      total.value = res.total || 0
      pendingCount.value = res.pending_count || 0
    } finally {
      loading.value = false
    }
  }

  async function loadMovieDetail(id) {
    return await getJavMovie(id)
  }

  async function loadActors() {
    const res = await getJavActors()
    actors.value = res || []
    return actors.value
  }

  async function loadActorDetail(id) {
    return await getJavActor(id)
  }

  async function triggerScan() {
    return await scanModule('jav')
  }

  async function triggerScrapeAll() {
    scraping.value = true
    scrapingStatus.value = '正在启动批量刮削...'
    try {
      const res = await scrapeAllPendingJav()
      scrapingStatus.value = res.message || '批量刮削已启动'
      return res
    } finally {
      scraping.value = false
    }
  }

  async function triggerImportNfo(params = {}) {
    scraping.value = true
    scrapingStatus.value = '正在启动 NFO 导入...'
    try {
      const res = await importJavNfo(params)
      scrapingStatus.value = res.message || 'NFO 导入已启动'
      return res
    } finally {
      scraping.value = false
    }
  }

  return {
    movies, total, actors, loading, page, pageSize, pendingCount,
    scraping, scrapingStatus,
    loadMovies, loadMovieDetail, loadActors, loadActorDetail,
    triggerScan, triggerScrapeAll, triggerImportNfo,
  }
})
