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
} from '@/api/pornhub'
import { scanModule } from '@/api/modules'

export const usePornhubStore = defineStore('pornhub', () => {
  // 影片
  const movies = ref([])
  const total = ref(0)
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(24)
  const sortBy = ref('created_at')
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
  async function loadMovies(extra = {}) {
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
      const res = await getPornhubMovies(params)
      movies.value = res.items || []
      total.value = res.total || 0
    } finally {
      loading.value = false
    }
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
    const res = await getPornhubActorsPage({
      skip: (actorPage.value - 1) * actorPageSize.value,
      limit: actorPageSize.value,
      search: actorSearch.value,
      nationality: actorNationality.value,
      profile_status: actorProfileStatus.value,
      sort_by: actorSortBy.value,
      sort_dir: actorSortDir.value,
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

  return {
    // state
    movies, total, loading, page, pageSize, sortBy, sortDir, filters,
    actors, actorTotal, actorPage, actorPageSize, actorSearch,
    actorNationality, actorProfileStatus, actorSortBy, actorSortDir,
    nationalities, externalStatus, currentMovie, currentActor,
    // 影片 actions
    loadMovies, loadMovieDetail, scrapeMovie, rescrapeMovie, updateMovie,
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
  }
})
