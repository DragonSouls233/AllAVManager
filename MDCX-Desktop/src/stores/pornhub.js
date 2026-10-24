import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getPornhubMovies,
  getPornhubMovie,
  getPornhubActors,
  getPornhubActor,
  getPornhubActorsPage,
  getPornhubActorNationalities,
  triggerPornhubResumableScan,
  scrapePornhubMovie,
  scrapePornhubActorProfile,
  scrapeAllPornhubActorProfilesEnhanced,
  updatePornhubMovie,
  updatePornhubActor,
  setPornhubActorProfileUrl,
  rescrapePornhubMovie,
  generatePornhubCoverEnhanced,
  generatePornhubPreview,
  batchPornhubRefetchCovers,
  batchPornhubGeneratePreviews,
  batchPornhubDownloadAvatars,
  pornhubExternalStatus,
  pornhubExternalSearch,
  pornhubExternalSeedActor,
  pornhubExternalSeedAll,
  pornhubBackfillUrls,
  pornhubSeedFromExternal,
  scrapeAllPendingPornhub,
} from '@/api/pornhub'
import { scanModule } from '@/api/modules'
import { queryClient, queryKeys, invalidateByPrefix } from '@/query'

export const usePornhubStore = defineStore('pornhub', () => {
  // 影片
  const movies = ref([])
  const total = ref(0)
  // 待刮削数量（批量刮削按钮的角标）
  const pendingCount = ref(0)
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(24)
  const sortBy = ref('scraped_at')
  const sortDir = ref('desc')
  const filters = ref({
    status: '',
    search: '',
    actor: '',
    has_cover: null,
    has_file: null,
    series: '',
    maker: '',
    genre: '',
    code_prefix: '',
  })

  // 演员
  const actors = ref([])
  const actorTotal = ref(0)
  const actorPage = ref(1)
  const actorPageSize = ref(24)
  const actorSearch = ref('')
  const actorNationality = ref('')
  const actorProfileStatus = ref('')
  const actorSortBy = ref('movie_count')
  const actorSortDir = ref('desc')
  const nationalities = ref([])
  const externalStatus = ref(null)

  // 当前详情
  const currentMovie = ref(null)
  const currentActor = ref(null)

  // ========== 影片 ==========
  // 取数走 Query 缓存（决策见 src/query/client.js）：
  //  · 同一组参数的在途请求会被合并，快速翻页不会打出一串重复请求；
  //  · 竞态保护靠下面的 loadSeq —— `fetchQuery` 没有 observer，不会随组件卸载自动取消，
  //    所以「迟到的响应不许回写」必须自己判；signal 已铺好，供将来改用 useQuery 或手动 cancelQueries；
  //  · 后台任务（刮削/扫描/补封面）启动后调 invalidateMovies()。
  let loadSeq = 0

  async function loadMovies(extra = {}) {
    const seq = ++loadSeq
    loading.value = true
    try {
      const params = {
        skip: (page.value - 1) * pageSize.value,
        limit: pageSize.value,
        sort_by: sortBy.value,
        sort_dir: sortDir.value,
        ...filters.value,
        ...extra,
      }
      // 清空空值
      Object.keys(params).forEach(k => {
        if (params[k] === '' || params[k] === null || params[k] === undefined) delete params[k]
      })
      const res = await queryClient.fetchQuery({
        queryKey: queryKeys.pornhub.movies(params),
        queryFn: ({ signal }) => getPornhubMovies(params, { signal }),
      })
      // 期间用户又触发了新的取数 ⇒ 这次结果已经过时，不许写回（否则翻页会跳回上一页）
      if (seq !== loadSeq) return
      movies.value = res.items || []
      total.value = res.total || 0
      pendingCount.value = res.pending_count || 0
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  /** 只刷「待刮削」角标，不动当前页列表。
   *
   * 批量刮削/扫描是后台任务，pending_count 会一直下降；用 limit=1 的最小请求去取，
   * 代价远小于重取整页（PORNHUB 列表带封面字段，一页 24 条很重）。
   * 返回当前数量，取不到返回 null（让轮询继续但不中断）。 */
  async function refreshStats() {
    try {
      const res = await queryClient.fetchQuery({
        queryKey: queryKeys.pornhub.stats,
        queryFn: ({ signal }) => getPornhubMovies({ limit: 1 }, { signal }),
      })
      pendingCount.value = res.pending_count || 0
      return pendingCount.value
    } catch {
      return null
    }
  }

  /** 让所有影片列表查询过期。后台任务改了库之后调用，下一次取数才拿新数据。 */
  function invalidateMovies() {
    return invalidateByPrefix(queryKeys.pornhub.moviesRoot)
  }

  async function loadMovieDetail(id) {
    const m = await getPornhubMovie(id)
    currentMovie.value = m
    return m
  }

  async function scrapeMovie(id) {
    return await scrapePornhubMovie(id, false)
  }

  async function rescrapeMovie(id) {
    return await rescrapePornhubMovie(id)
  }

  async function updateMovie(id, data) {
    return await updatePornhubMovie(id, data)
  }

  // ========== 演员 ==========
  async function loadActors() {
    const params = {
      skip: (actorPage.value - 1) * actorPageSize.value,
      limit: actorPageSize.value,
      search: actorSearch.value,
      nationality: actorNationality.value,
      profile_status: actorProfileStatus.value,
      sort_by: actorSortBy.value,
      sort_dir: actorSortDir.value,
    }
    const res = await queryClient.fetchQuery({
      queryKey: queryKeys.pornhub.actors(params),
      queryFn: ({ signal }) => getPornhubActorsPage(params, { signal }),
    })
    actors.value = res.items || []
    actorTotal.value = res.total || 0
    return actors.value
  }

  async function loadNationalities() {
    nationalities.value = await getPornhubActorNationalities()
    return nationalities.value
  }

  async function loadActorDetail(id) {
    const a = await getPornhubActor(id)
    currentActor.value = a
    return a
  }

  async function scrapeActor(id) {
    return await scrapePornhubActorProfile(id)
  }

  async function scrapeAllActors() {
    return await scrapeAllPornhubActorProfilesEnhanced()
  }

  async function updateActor(id, data) {
    return await updatePornhubActor(id, data)
  }

  async function setActorProfileUrl(id, url) {
    return await setPornhubActorProfileUrl(id, url)
  }

  // ========== 批量任务 ==========
  async function batchRefetchCovers(params = {}) {
    return await batchPornhubRefetchCovers(params)
  }
  async function batchGeneratePreviews(params = {}) {
    return await batchPornhubGeneratePreviews(params)
  }
  async function batchDownloadAvatars(params = {}) {
    return await batchPornhubDownloadAvatars(params)
  }
  async function generatePreview(id, cols, rows, thumbW) {
    return await generatePornhubPreview(id, cols, rows, thumbW)
  }
  async function generateCover(id) {
    return await generatePornhubCoverEnhanced(id)
  }

  // ========== 外部种子（L:\data\PORNHUB） ==========
  async function loadExternalStatus() {
    externalStatus.value = await pornhubExternalStatus()
    return externalStatus.value
  }
  async function externalSearch(name) {
    return await pornhubExternalSearch(name)
  }
  async function externalSeedActor(name) {
    return await pornhubExternalSeedActor(name)
  }
  async function externalSeedAll(limit = 200) {
    return await pornhubExternalSeedAll(limit)
  }
  async function backfillUrls() {
    return await pornhubBackfillUrls()
  }
  async function seedFromExternal() {
    return await pornhubSeedFromExternal()
  }

  // ========== 扫描 ==========
  async function triggerScan() {
    return await scanModule('pornhub')
  }
  async function triggerResumableScan(rescan = false) {
    return await triggerPornhubResumableScan(rescan)
  }

  async function triggerScrapeAll() {
    // 🔴 2026-10-13：PORNHUB 详情页 1.5MB/次且限流严于 JSON 端点，
    // 后端 scrape_module_pending 是**串行**的。86350 部 × 约 10s/部 ≈ 10 天，
    // 所以这里明确告知用户预期耗时，避免以为又卡住了。
    const res = await scrapeAllPendingPornhub()
    return res
  }
  return {
    // state
    movies, total, loading, page, pageSize, sortBy, sortDir, filters,
    actors, actorTotal, actorPage, actorPageSize, actorSearch,
    actorNationality, actorProfileStatus, actorSortBy, actorSortDir,
    nationalities, externalStatus, currentMovie, currentActor,
    // 影片 actions
    loadMovies, loadMovieDetail, scrapeMovie, rescrapeMovie, updateMovie,
    refreshStats, invalidateMovies,
    // 演员 actions
    loadActors, loadNationalities, loadActorDetail,
    scrapeActor, scrapeAllActors, updateActor, setActorProfileUrl,
    // 批量
    batchRefetchCovers, batchGeneratePreviews, batchDownloadAvatars,
    generatePreview, generateCover,
    // 外部
    loadExternalStatus, externalSearch, externalSeedActor, externalSeedAll,
    backfillUrls, seedFromExternal,
    // 扫描
    triggerScan, triggerResumableScan,
    // 批量刮削
    triggerScrapeAll, pendingCount,
  }
})
