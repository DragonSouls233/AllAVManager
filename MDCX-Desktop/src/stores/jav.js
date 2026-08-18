import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { getJavMovies, getJavMovie, getJavActors, getJavActor, scrapeJavMovie, scrapeAllPendingJav, importJavNfo, scrapeMediaRefill } from '@/api/jav'
import { scanModule } from '@/api/modules'

const PAGE_SIZE_KEY = 'mdcx_jav_page_size'

export const useJavStore = defineStore('jav', () => {
  const movies = ref([])
  const total = ref(0)
  const actors = ref([])
  const loading = ref(false)
  const page = ref(1)
  // 每页数量持久化：刷新/重进页面后保留用户选择（如 192/240/288）
  const savedPageSize = Number(localStorage.getItem(PAGE_SIZE_KEY))
  const pageSize = ref(Number.isInteger(savedPageSize) && savedPageSize >= 12 ? savedPageSize : 24)
  watch(pageSize, (v) => localStorage.setItem(PAGE_SIZE_KEY, String(v)))
  const statusFilter = ref('')
  const pendingCount = ref(0)
  const scraping = ref(false)
  const scrapingStatus = ref('')

  async function loadMovies(params = {}) {
    loading.value = true
    try {
      const res = await getJavMovies({
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
      status: statusFilter.value || undefined,
      ...params
    })
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

  async function loadActors(params = {}) {
    const res = await getJavActors(params)
    actors.value = res.items || []
    total.value = res.total || 0
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

  async function triggerMediaRefill(limit = 50) {
    scraping.value = true
    scrapingStatus.value = '正在启动缺图补刮...'
    try {
      const res = await scrapeMediaRefill({ module: 'jav', limit })
      scrapingStatus.value = res.message || '缺图补刮已启动'
      return res
    } finally {
      scraping.value = false
    }
  }

  return {
    movies, total, actors, loading, page, pageSize, statusFilter, pendingCount,
    scraping, scrapingStatus,
    loadMovies, loadMovieDetail, loadActors, loadActorDetail,
    triggerScan, triggerScrapeAll, triggerImportNfo, triggerMediaRefill,
  }
})
