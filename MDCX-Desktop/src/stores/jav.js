import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { getJavMovies, getJavMovie, getJavActors, getJavActor, scrapeJavMovie, scrapeAllPendingJav, importJavNfo, scrapeMediaRefill } from '@/api/jav'
import { scanModule } from '@/api/modules'
import { queryClient, queryKeys, invalidateByPrefix } from '@/query'

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

  // 取数走 Query 缓存（决策见 src/query/client.js）：在途去重 + 统一失效入口。
  // 竞态靠 loadSeq（fetchQuery 无 observer，不随组件卸载自动取消）。
  let loadSeq = 0

  async function loadMovies(params = {}) {
    const seq = ++loadSeq
    loading.value = true
    try {
      const query = {
        skip: (page.value - 1) * pageSize.value,
        limit: pageSize.value,
        status: statusFilter.value || undefined,
        ...params,
      }
      const res = await queryClient.fetchQuery({
        queryKey: queryKeys.jav.movies(query),
        queryFn: ({ signal }) => getJavMovies(query, { signal }),
      })
      // 期间又触发了新的取数 ⇒ 本次结果已过时，不回写（否则翻页会跳回上一页）
      if (seq !== loadSeq) return
      movies.value = res.items || []
      total.value = res.total || 0
      pendingCount.value = res.pending_count || 0
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  /** 只刷「待刮削」角标，不动当前页列表（limit=1 的最小请求）。取不到返回 null。 */
  async function refreshStats() {
    try {
      const res = await queryClient.fetchQuery({
        queryKey: queryKeys.jav.stats,
        queryFn: ({ signal }) => getJavMovies({ limit: 1 }, { signal }),
      })
      pendingCount.value = res.pending_count || 0
      return pendingCount.value
    } catch {
      return null
    }
  }

  /** 让所有影片列表查询过期。后台任务改了库之后调用。 */
  function invalidateMovies() {
    return invalidateByPrefix(queryKeys.jav.moviesRoot)
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
    refreshStats, invalidateMovies,
    triggerScan, triggerScrapeAll, triggerImportNfo, triggerMediaRefill,
  }
})
