import axios from 'axios'
import { ElMessage } from 'element-plus'

const STORAGE_KEY = 'serverUrl'

function getBaseURL() {
  const url = localStorage.getItem(STORAGE_KEY)
  return url ? `${url.replace(/\/$/, '')}/api/v1` : '/api/v1'
}

const api = axios.create({
  baseURL: getBaseURL(),
  timeout: 30000
})

export function setServerUrl(url) {
  if (!url) {
    localStorage.removeItem(STORAGE_KEY)
  } else {
    localStorage.setItem(STORAGE_KEY, url.replace(/\/$/, ''))
  }
  api.defaults.baseURL = getBaseURL()
}

export function getServerUrl() {
  return localStorage.getItem(STORAGE_KEY) || ''
}

export async function checkServerConnection(url) {
  const base = url ? url.replace(/\/$/, '') : (localStorage.getItem(STORAGE_KEY) || window.location.origin)
  const testUrl = `${base}/api/v1/health/version`
  try {
    const res = await axios.get(testUrl, { timeout: 5000 })
    if (res.status === 200 && res.data) {
      return { ok: true, url: base, version: res.data.version || 'unknown' }
    }
    return { ok: false, error: 'Invalid response' }
  } catch (e) {
    return { ok: false, error: e.message || 'Connection failed' }
  }
}

// 请求拦截器 - 添加 token
api.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// 响应拦截器
api.interceptors.response.use(
  response => response.data,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      if (!location.hash.includes('/login')) {
        ElMessage.error('登录已失效，请重新登录')
        location.hash = '#/login'
      }
      return Promise.reject(error)
    }
    const msg = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export default api
export { api }

// ============================================
// Auth 认证
// ============================================
export const login = (data) => api.post('/auth/login', data)
export const getMe = () => api.get('/auth/me')
export const checkAuth = () => api.post('/auth/check')
export const getTrustedIPs = () => api.get('/auth/trusted-ip')
export const updateTrustedIPs = (data) => api.put('/auth/trusted-ip', data)

// ============================================
// System 版本/补丁信息
// ============================================
export const getVersion = () => api.get('/health/version')

// ============================================
// Movies 媒体管理
// ============================================
export const getMovies = (params) => api.get('/movies', { params })
export const getMovie = (id) => api.get(`/movies/${id}`)
export const updateMovie = (id, data) => api.patch(`/movies/${id}`, data)
export const deleteMovie = (id) => api.delete(`/movies/${id}`)
export const reloadMovieNfo = (id) => api.post(`/movies/${id}/reload-nfo`)
export const batchDeleteMovies = (ids) => api.post('/movies/batch-delete', { ids })
export const scrapeMovie = (id, force = false) => api.post(`/movies/${id}/scrape?force=${force}`, null, { timeout: 180000 })
export const scrapeByCode = (code, sources = null) =>
  api.post('/movies/scrape-by-code', { code, sources }, { timeout: 180000 })
export const playMovie = (id) => api.get(`/movies/${id}/play`)
export const getMoviePlayUrl = (id, protocol = 'http') => api.get(`/movies/${id}/play/external`, { params: { protocol } })
export const getMovieCodecInfo = (id) => api.get(`/movies/${id}/codec-info`)
export const getRelatedMovies = (id) => api.get(`/movies/${id}/related`)
export const scanMovies = (directory) => api.get('/movies/scan', { params: { directory } })
export const scanAndLink = (directories, dry_run = false) => api.post('/movies/scan-and-link', { directories, dry_run })
export const autoLinkFiles = () => api.post('/movies/auto-link-files')
export const refreshFolders = (directories, dryRun = false, clearMissing = true) =>
  api.post('/movies/refresh-folders', { directories, dry_run: dryRun, clear_missing: clearMissing })

// 番号首字母分组导航
export const getAlphabet = (status) => api.get('/movies/alphabet', { params: { status } })

// ============================================
// Translate 翻译
// ============================================
export const translateText = (data) => api.post('/translate', data)
export const translateBatch = (data) => api.post('/translate/batch', data)
export const translateMovie = (data) => api.post('/translate/movie', data)
export const getTranslateConfig = () => api.get('/translate/config')

// ============================================
// Tiers 分级管理（参考 JATLAS）
// ============================================
export const getTierConfig = () => api.get('/tiers/config')
export const updateTierConfig = (data) => api.put('/tiers/config', data)
export const getTierDashboard = () => api.get('/tiers/dashboard')
export const getTierRisk = (params) => api.get('/tiers/risk', { params })
export const getActorTier = (actorId) => api.get(`/tiers/actors/${actorId}`)
export const setActorTier = (actorId, data) => api.put(`/tiers/actors/${actorId}`, data)
export const batchSetTier = (data) => api.post('/tiers/batch', data)
export const removeActorTier = (actorId) => api.delete(`/tiers/actors/${actorId}`)
export const getChangeLogs = (params) => api.get('/tiers/logs', { params })
export const clearChangeLogs = (beforeDays) => api.delete('/tiers/logs', { params: { before_days: beforeDays } })

// ============================================
// WebDAV
// ============================================
export const testWebDAV = (data) => api.post('/webdav/test', data)
export const scanWebDAV = (data) => api.post('/webdav/scan', data)
export const importFromWebDAV = (data) => api.post('/webdav/import', data)
export const getWebDAVConfig = () => api.get('/webdav/config')
export const updateWebDAVConfig = (data) => api.put('/webdav/config', data)
export const listWebDAVServerFiles = (params) => api.get('/webdav/server/files', { params })

// ============================================
// 网络诊断
// ============================================
export const getDiagSites = () => api.get('/network-diag/sites')
export const runDiagnosis = () => api.post('/network-diag/run')
export const singleCheck = (data) => api.post('/network-diag/check', data)
export const getDiagConfig = () => api.get('/network-diag/config')
export const updateDiagConfig = (params) => api.put('/network-diag/config', null, { params })

// ============================================
// 人脸裁剪
// ============================================
export const getFaceCropConfig = () => api.get('/face-crop/config')
export const updateFaceCropConfig = (data) => api.put('/face-crop/config', data)
export const initializeFaceCropper = () => api.post('/face-crop/initialize')
export const cropPoster = (data) => api.post('/face-crop/crop', data)
export const batchCrop = (data) => api.post('/face-crop/batch-crop', data)
export const getCropperStatus = () => api.get('/face-crop/status')

// ============================================
// 命名模板（Jinja2 沙箱）
// ============================================
export const getNamingConfig = () => api.get('/naming/config')
export const updateNamingConfig = (data) => api.put('/naming/config', data)
export const previewNamingTemplate = (data) => api.post('/naming/preview', data)
export const validateNamingTemplate = (data) => api.post('/naming/validate', data)
export const renderNamingForMovie = (data) => api.post('/naming/render', data)
export const getDefaultTemplates = () => api.get('/naming/defaults')
export const getTemplateVariables = () => api.get('/naming/variables')

// ============================================
// 站点优先级可视化
// ============================================
export const getSitePriorityVisualization = () => api.get('/site-priority/visualization')
export const pingAllSitesForVisualization = () => api.post('/site-priority/visualization/ping-all')
export const updateSitePriorityOrder = (order) => api.put('/site-priority/order', { order })
export const toggleSiteEnabled = (name, enabled) => api.post(`/site-priority/${name}/toggle`, null, { params: { enabled } })

// ============================================
// Emby 协议兼容
// ============================================
export const getEmbyConfig = () => api.get('/emby-config/config')
export const updateEmbyConfig = (data) => api.put('/emby-config/config', data)
export const regenerateEmbyApiKey = () => api.post('/emby-config/regenerate-key')
export const testEmbyEndpoint = () => api.post('/emby-config/test')
export const getEmbyClientsGuide = () => api.get('/emby-config/clients-guide')

// ============================================
// Emby 元数据推送（v3.1）
// ============================================
export const getEmbyPushConfig = () => api.get('/emby-push/config')
export const updateEmbyPushConfig = (data) => api.put('/emby-push/config', data)
export const getEmbyPushStatus = () => api.get('/emby-push/status')
export const pushMovieToEmby = (movieId) => api.post(`/emby-push/movie/${movieId}`)
export const batchPushToEmby = (data) => api.post('/emby-push/batch', data)
export const refreshEmbyMovie = (movieId) => api.post(`/emby-push/refresh/${movieId}`)
export const pushActorToEmby = (actorId, data) => api.post(`/emby-push/actor/${actorId}`, data)
export const searchEmby = (q, limit = 20) => api.get('/emby-push/search', { params: { q, limit } })
export const refreshEmbyLibrary = () => api.post('/emby-push/refresh-library')

// ============================================
// STRM 文件生成
// ============================================
export const getStrmConfig = () => api.get('/strm/config')
export const updateStrmConfig = (data) => api.put('/strm/config', data)
export const generateStrm = (data) => api.post('/strm/generate', data)
export const cleanupStrm = () => api.post('/strm/cleanup')
export const getStrmStatistics = () => api.get('/strm/statistics')

// ============================================
// NSFW 模式
// ============================================
export const getNsfwConfig = () => api.get('/nsfw/config')
export const updateNsfwConfig = (data) => api.put('/nsfw/config', data)
export const toggleNsfwMode = () => api.post('/nsfw/toggle')

// ============================================
// 马赛克识别
// ============================================
export const getMosaicConfig = () => api.get('/mosaic/config')
export const updateMosaicConfig = (data) => api.put('/mosaic/config', data)
export const identifyMosaic = (data) => api.post('/mosaic/identify', data)
export const identifyMosaicBatch = (data) => api.post('/mosaic/identify-batch', data)
export const getUncensoredPatterns = () => api.get('/mosaic/uncensored-patterns')

// ============================================
// Thumbnails 缩略图
// ============================================
export const getMovieThumbnails = (movieId) => api.get(`/movies/${movieId}/thumbnails`)
export const generateMovieThumbnails = (movieId, force = false) => api.post(`/movies/${movieId}/thumbnails/generate`, null, { params: { force } })

// ============================================
// Actors 演员管理
// ============================================
export const getActors = (params) => api.get('/actors', { params })
export const getActor = (id) => api.get(`/actors/${id}`)
export const getActorMovies = (id, params) => api.get(`/actors/${id}/movies`, { params })
export const getActorTimeline = (id) => api.get(`/actors/${id}/timeline`)
export const updateActor = (id, data) => api.patch(`/actors/${id}`, data)
export const getActorStats = () => api.get('/actors/stats/overview')
export const scrapeActorProfile = (id) => api.post(`/actors/${id}/scrape-profile`, null, { timeout: 120000 })
export const scrapeActorProfiles = (data) => api.post('/actors/scrape-profiles/batch', data, { timeout: 300000 })
// 演员标签管理（v3.4 新增）
export const getActorTags = (id) => api.get(`/actors/${id}/tags`)
export const addActorTag = (id, data) => api.post(`/actors/${id}/tags`, data)
export const deleteActorTag = (id, tagId) => api.delete(`/actors/${id}/tags/${tagId}`)
export const getPopularActorTags = (params) => api.get('/actors/tags/popular', { params })
export const uploadActorAvatar = (id, file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/actors/${id}/avatar`, formData, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const deleteActorAvatar = (id) => api.delete(`/actors/${id}/avatar`)

// ============================================
// Tags 标签管理
// ============================================
export const getTags = (params) => api.get('/tags', { params })
export const getTagStats = () => api.get('/tags/stats')
export const createTag = (data) => api.post('/tags', data)
export const batchCreateTags = (tags) => api.post('/tags/batch', { tags })
export const batchTagMovies = (data) => api.post('/tags/batch-tag-movies', data)
export const removeTagFromMovies = (data) => api.post('/tags/remove-tag-movies', data)
export const replaceTagsForMovies = (data) => api.post('/tags/replace-tags-movies', data)
export const batchDeleteTags = (ids) => api.post('/tags/batch-delete-tags', { ids })
export const syncTagsFromMovies = () => api.post('/tags/sync-from-movies')
export const updateTag = (id, data) => api.patch(`/tags/${id}`, data)
export const deleteTag = (id) => api.delete(`/tags/${id}`)

// ============================================
// Studios 厂商管理
// ============================================
export const getStudios = (params) => api.get('/studios', { params })
export const getStudio = (id) => api.get(`/studios/${id}`)
export const createStudio = (data) => api.post('/studios', data)
export const syncStudiosFromMovies = () => api.post('/studios/sync-from-movies')
export const updateStudio = (id, data) => api.patch(`/studios/${id}`, data)
export const deleteStudio = (id) => api.delete(`/studios/${id}`)

// ============================================
// Series 系列管理
// ============================================
export const getSeries = (params) => api.get('/series', { params })
export const getSeriesDetail = (id) => api.get(`/series/${id}`)
export const createSeries = (data) => api.post('/series', data)
export const syncSeriesFromMovies = () => api.post('/series/sync-from-movies')
export const updateSeries = (id, data) => api.patch(`/series/${id}`, data)
export const deleteSeries = (id) => api.delete(`/series/${id}`)

// ============================================
// Crawlers 爬虫管理（多源刮削）
// ============================================
export const getCrawlers = () => api.get('/crawlers')
export const getCrawlerInfo = (name) => api.get(`/crawlers/${name}`)
export const enableCrawler = (name) => api.post(`/crawlers/${name}/enable`)
export const disableCrawler = (name) => api.post(`/crawlers/${name}/disable`)
export const testCrawler = (name, number) => api.post(`/crawlers/${name}/test`, null, { params: { test_code: number } })
export const pingCrawler = (name) => api.post(`/crawlers/${name}/ping`)
export const pingCrawlers = () => api.post('/crawlers/ping')
export const setCrawlerPriority = (priorities) => api.post('/crawlers/priority', { priorities })
export const getCrawlerStats = () => api.get('/crawlers/stats')

// ============================================
// Compare 本地在线对比
// ============================================
export const scanLocal = (directories = []) => api.post('/compare/scan-local', { directories })
export const compareOnline = (data) => api.post('/compare/online', data)
export const localDatabaseSummary = () => api.post('/compare/database')
export const compareSearchDirectories = (actorName, maxDepth = 4) =>
  api.post('/compare/search-directories', { actor_name: actorName, max_depth: maxDepth })
export const compareOnlineByActor = (actorId, data = {}) => api.post('/compare/online-by-actor', { actor_id: actorId, ...data })
export const getCompareActors = (params) => api.get('/compare/actors', { params })
export const getActorCompareUrl = (actorId) => api.get(`/compare/actors/${actorId}/url`)
export const saveActorCompareUrl = (actorId, data) => api.put(`/compare/actors/${actorId}/url`, data)
export const scanAllCompareActors = (minMovies = 10) => api.post('/compare/actors/scan', null, { params: { min_movies: minMovies } })
export const detectActorLocalDir = (actorId) => api.post(`/compare/actors/${actorId}/detect-dir`)
export const browseDir = (path) => api.post('/compare/browse-dir', { path })

// ============================================
// Favorites 收藏夹
// ============================================
export const getFavoriteGroups = (entityType) => api.get('/favorites/groups', { params: { entity_type: entityType } })
export const createFavoriteGroup = (name, entityType) => api.post('/favorites/groups', { name, entity_type: entityType })
export const updateFavoriteGroup = (id, data) => api.patch(`/favorites/groups/${id}`, data)
export const deleteFavoriteGroup = (id) => api.delete(`/favorites/groups/${id}`)
export const getFavoriteItems = (groupId) => api.get(`/favorites/groups/${groupId}/items`)
export const addFavoriteItem = (groupId, entityId) => api.post(`/favorites/groups/${groupId}/items`, { entity_id: entityId })
export const removeFavoriteItem = (groupId, entityId) => api.delete(`/favorites/groups/${groupId}/items/${entityId}`)
export const updateFavoriteItemOrder = (groupId, itemIds) => api.put(`/favorites/groups/${groupId}/item-order`, { item_ids: itemIds })
export const checkFavorite = (entityType, entityId) => api.get('/favorites/check', { params: { entity_type: entityType, entity_id: entityId } })

// ============================================
// Fingerprint 视频指纹
// ============================================
export const computeFingerprint = (movieId) => api.post(`/fingerprint/compute/${movieId}`)
export const scanFingerprints = (limit = 50) => api.post('/fingerprint/scan', null, { params: { limit } })
export const findDuplicates = (threshold = 5) => api.get('/fingerprint/duplicates', { params: { threshold } })
export const fingerprintStatus = () => api.get('/fingerprint/status')

// ============================================
// Proxy 内置代理（Western 模块用）
// ============================================
export const getProxyStatus = () => api.get('/proxy/xray/status')

// ============================================
// mpv Player 播放器
// ============================================
export const playWithMpv = (movieId, options = {}) => api.post(`/mpv/play/${movieId}`, options)
export const getMpvConfig = () => api.get('/mpv/config')
export const saveMpvConfig = (config) => api.put('/mpv/config', config)
export const getDefaultHotkeys = () => api.get('/mpv/hotkeys')

// ============================================
// Tasks 任务管理
// ============================================
export const getTasks = (params) => api.get('/tasks', { params })
export const createTask = (data) => api.post('/tasks', data)
export const retryTask = (id) => api.post(`/tasks/${id}/retry`)
export const cancelTask = (id) => api.delete(`/tasks/${id}`)
export const cleanupTasks = () => api.post('/tasks/cleanup')
export const getScheduledJobs = () => api.get('/tasks/scheduled')
export const createScheduledJob = (data) => api.post('/tasks/scheduled', data)
export const deleteScheduledJob = (jobId) => api.delete(`/tasks/scheduled/${jobId}`)

// ============================================
// Patch 补刮管理
// ============================================
export const detectMissing = (params) => api.get('/patch/detect', { params, timeout: 120000 })
export const runPatch = (data) => api.post('/patch/run', data)
export const getPatchStatus = (jobId) => api.get(`/patch/status/${jobId}`)
export const getPatchReport = (jobId) => api.get(`/patch/report/${jobId}`)
export const getPatchHistory = () => api.get('/patch/history')

// ============================================
// Import 导入管理
// ============================================
export const scanImportDirectory = (data) => api.post('/import/scan', data)
export const runImport = (data) => api.post('/import/run', data)
export const getImportStatus = (jobId) => api.get(`/import/status/${jobId}`)
export const getImportReport = (jobId) => api.get(`/import/report/${jobId}`)
export const getImportHistory = () => api.get('/import/history')
export const deleteImportRecord = (recordId) => api.delete(`/import/history/${recordId}`)

// ============================================
// NFO 导入导出
// ============================================
export const exportNfo = (movieId) => api.get(`/nfo/movie/${movieId}`)
export const downloadNfo = (movieId) => api.get(`/nfo/movie/${movieId}/file`, { responseType: 'blob' })
export const importNfo = (data) => api.post('/nfo/import', data)
export const batchExportNfo = (movieIds) => api.post('/nfo/batch-export', { movie_ids: movieIds }, { responseType: 'blob' })

// ============================================
// Workflows 工作流
// ============================================
export const getWorkflows = () => api.get('/workflows')
export const getWorkflow = (id) => api.get(`/workflows/${id}`)
export const createWorkflow = (data) => api.post('/workflows', data)
export const updateWorkflow = (id, data) => api.put(`/workflows/${id}`, data)
export const deleteWorkflow = (id) => api.delete(`/workflows/${id}`)
export const scanWorkflowDirectory = (data) => api.post('/workflows/scan-directory', data)
export const runWorkflow = (id) => api.post(`/workflows/run/${id}`)

// ============================================
// Logs 日志
// ============================================
export const getLogs = (params) => api.get('/logs', { params })

// ============================================
// Config 配置管理
// ============================================
export const getConfig = () => api.get('/config')
export const updateConfig = (data) => api.patch('/config', data)  // 修复：使用 PATCH 而非 POST
export const resetConfig = () => api.post('/config/reset')
export const testProxy = (data) => api.post('/config/test-proxy', data)
export const checkJavdbCookie = (cookie) => api.post('/config/check-javdb-cookie', { cookie })
export const checkJavbusCookie = (cookie) => api.post('/config/check-javbus-cookie', { cookie })
export const startCookieLogin = (site) => api.post(`/config/cookie-login/${site}`)
export const getCookieLoginPollStatus = (site) => api.get(`/config/cookie-login/${site}/status`)
export const stealthFetch = (data) => api.post('/config/stealth-fetch', data)

// ============================================
// Stats 统计（修复：使用具体端点而非根路径）
// ============================================
export const getDashboardStats = () => api.get('/stats/dashboard')
export const getMovieStats = () => api.get('/stats/movies')
export const getTaskStats = () => api.get('/stats/tasks')
export const getStorageStats = () => api.get('/stats/storage')
export const getSystemHealth = () => api.get('/stats/health')

// 兼容旧代码：getStats 映射到 dashboard
export const getStats = () => api.get('/stats/dashboard')

// ============================================
// Files 文件浏览
// ============================================
export const getFileRoots = () => api.get('/files/roots')
export const browseDirectory = (path, showFiles = false) => api.get('/files/browse', { params: { path, show_files: showFiles } })

// ============================================
// Health 健康检查
// ============================================
export const healthCheck = () => api.get('/health')
export const readinessCheck = () => api.get('/health/ready')
export const livenessCheck = () => api.get('/health/live')

// ============================================
// Player 播放器（缩略图进度条、GIF、章节、字幕）
// ============================================
// 一次性获取影片所有播放器元数据
export const getPlayerConfig = (movieId) => api.get(`/player/${movieId}/config`)

// 缩略图进度条
export const getThumbnailSprite = (movieId) => api.get(`/player/${movieId}/thumbnail-sprite`)
export const generateThumbnailSprite = (movieId, params = {}) =>
  api.post(`/player/${movieId}/thumbnail-sprite/generate`, null, { params })

// GIF 动图
export const listGifs = (movieId) => api.get(`/player/${movieId}/gifs`)
export const generateGif = (movieId, data) => api.post(`/player/${movieId}/gifs/generate`, data)
export const deleteGif = (movieId, filename) => api.delete(`/player/${movieId}/gifs/${filename}`)

// 章节标记
export const listChapters = (movieId) => api.get(`/player/${movieId}/chapters`)
export const addChapter = (movieId, data) => api.post(`/player/${movieId}/chapters`, data)
export const updateChapter = (movieId, chapterId, data) =>
  api.put(`/player/${movieId}/chapters/${chapterId}`, data)
export const deleteChapter = (movieId, chapterId) =>
  api.delete(`/player/${movieId}/chapters/${chapterId}`)
export const autoDetectChapters = (movieId, params = {}) =>
  api.post(`/player/${movieId}/chapters/auto-detect`, null, { params })
export const generateChapterThumbnails = (movieId) =>
  api.post(`/player/${movieId}/chapters/generate-thumbnails`)

// 字幕
export const listSubtitles = (movieId) => api.get(`/player/${movieId}/subtitles`)

// 音轨切换（v3.5 新增）
export const listAudioTracks = (movieId) => api.get(`/player/${movieId}/audio-tracks`)
export const switchAudioTrack = (movieId, trackIndex) =>
  api.post(`/player/${movieId}/audio-tracks/${trackIndex}/switch`)

// HLS 自适应码率（v3.5 新增）
export const getHlsQualities = (movieId) => api.get(`/movies/${movieId}/hls/qualities`)

// ============================================
// Plugins 插件系统
// ============================================
export const listPlugins = (pluginType) =>
  api.get('/plugins/list', { params: { plugin_type: pluginType } })
export const getPluginDetail = (pluginType, name) =>
  api.get(`/plugins/${pluginType}/${name}`)
export const enablePlugin = (pluginType, name) =>
  api.post(`/plugins/${pluginType}/${name}/enable`)
export const disablePlugin = (pluginType, name) =>
  api.post(`/plugins/${pluginType}/${name}/disable`)
export const reloadPlugin = (pluginType, name) =>
  api.post(`/plugins/${pluginType}/${name}/reload`)
export const reloadAllPlugins = () => api.post('/plugins/reload-all')
export const updatePluginConfig = (pluginType, name, config) =>
  api.put(`/plugins/${pluginType}/${name}/config`, { config })
export const createPluginTemplate = (data) => api.post('/plugins/create-template', data)
export const deletePlugin = (pluginType, name) =>
  api.delete(`/plugins/${pluginType}/${name}`)
export const listTranslatorPlugins = () => api.get('/plugins/translators')
export const listOrganizerPlugins = () => api.get('/plugins/organizers')

// ============================================
// Webhooks 通知输出
// ============================================
export const listWebhooks = () => api.get('/plugins/webhooks')
export const createWebhook = (data) => api.post('/plugins/webhooks', data)
export const updateWebhook = (id, data) => api.put(`/plugins/webhooks/${id}`, data)
export const deleteWebhook = (id) => api.delete(`/plugins/webhooks/${id}`)
export const testWebhook = (id) => api.post(`/plugins/webhooks/${id}/test`)
export const broadcastWebhook = (data) => api.post('/plugins/webhooks/broadcast', data)
export const getWebhookHistory = (params) =>
  api.get('/plugins/webhooks/history', { params })
export const clearWebhookHistory = () => api.delete('/plugins/webhooks/history')

// ============================================
// Subscriptions 演员订阅
// ============================================
export const listSubscriptions = (params) =>
  api.get('/subscriptions', { params })
export const subscribeActor = (data) => api.post('/subscriptions', data)
export const unsubscribeActor = (actorId, params) =>
  api.delete(`/subscriptions/${actorId}`, { params })
export const checkActorNewMovies = (actorId) =>
  api.get(`/subscriptions/check/${actorId}`)
export const checkAllSubscriptions = () => api.post('/subscriptions/check-all')
export const listSubscriptionNewMovies = (params) =>
  api.get('/subscriptions/new-movies', { params })

// ============================================
// Viewing 观影历史 + AI 报告
// ============================================
export const recordPlay = (data) => api.post('/viewing/play', data)
export const getViewingHistory = (params) =>
  api.get('/viewing/history', { params })
export const getViewingReport = (params) =>
  api.get('/viewing/report', { params })

// ============================================
// Users 多用户管理
// ============================================
export const listUsers = () => api.get('/users')
export const getUser = (id) => api.get(`/users/${id}`)
export const createUser = (data) => api.post('/users', data)
export const updateUser = (id, data) => api.put(`/users/${id}`, data)
export const deleteUser = (id) => api.delete(`/users/${id}`)
export const userLogin = (data) => api.post('/users/login', data)
export const verifyToken = (token) => api.post('/users/verify', { token })
export const userLogout = (token) => api.post('/users/logout', { token })
export const listUserSessions = (userId) => api.get(`/users/${userId}/sessions`)
export const revokeUserSession = (userId, sessionId) =>
  api.delete(`/users/${userId}/sessions/${sessionId}`)
export const revokeAllUserSessions = (userId) =>
  api.post(`/users/${userId}/revoke-all-sessions`)
export const ensureDefaultAdmin = () => api.post('/users/ensure-default-admin')

// ============================================
// Telegram Bot
// ============================================
export const getTelegramBotConfig = () => api.get('/telegram-bot/config')
export const updateTelegramBotConfig = (data) => api.put('/telegram-bot/config', data)
export const getTelegramBotStatus = () => api.get('/telegram-bot/status')
export const startTelegramBot = () => api.post('/telegram-bot/start')
export const stopTelegramBot = () => api.post('/telegram-bot/stop')
export const restartTelegramBot = () => api.post('/telegram-bot/restart')
export const sendTelegramMessage = (data) => api.post('/telegram-bot/send', data)
export const broadcastTelegram = (data) => api.post('/telegram-bot/broadcast', data)
export const deleteTelegramWebhook = () => api.post('/telegram-bot/delete-webhook')
export const testTelegramToken = () => api.get('/telegram-bot/me')

// ============================================
// 三态视频标记（v3.0）
// ============================================
export const getViewStatusStats = () => api.get('/view-status/stats')
export const getMovieViewStatus = (movieId) => api.get(`/view-status/${movieId}`)
export const setMovieViewStatus = (movieId, status) => api.put(`/view-status/${movieId}`, { status })
export const batchSetViewStatus = (movieIds, status) => api.post('/view-status/batch', { movie_ids: movieIds, status })
export const listMoviesByViewStatus = (status, limit = 100, offset = 0) =>
  api.get('/view-status/', { params: { status, limit, offset } })

// ============================================
// 文件整理（v3.0：5 种整理模式）
// ============================================
export const getOrganizeModes = () => api.get('/file-organize/modes')
export const previewOrganize = (data) => api.post('/file-organize/preview', data)
export const executeOrganize = (data) => api.post('/file-organize/execute', data)
export const listOrganizeJobs = (params) => api.get('/file-organize/jobs', { params })
export const getOrganizeJobStats = () => api.get('/file-organize/stats')

// ============== CookieCloud 同步 ==============
export const getCookieCloudConfig = () => api.get('/cookiecloud/config')
export const updateCookieCloudConfig = (data) => api.put('/cookiecloud/config', data)
export const syncCookieCloudNow = () => api.post('/cookiecloud/sync')
export const getCookieCloudStatus = () => api.get('/cookiecloud/status')

// ============== Cookie 管理 ==============
export const cookieStatus = () => api.get('/config/cookie/status')
export const cookieLogin = (site) => api.post(`/config/cookie/${site}/login`)
export const cookieLoginStatus = (site) => api.get(`/config/cookie/${site}/status`)
export const cookieValidate = (site) => api.post(`/config/cookie/${site}/validate`)
export const cookieSet = (site, data) => api.put(`/config/cookie/${site}`, data)

// ============== Gfriends 头像库 ==============
export const importGfriends = (data) => api.post('/gfriends/import', data)
export const getGfriendsJobStatus = (jobId) => api.get(`/gfriends/jobs/${jobId}`)
export const listGfriendsJobs = () => api.get('/gfriends/jobs')
export const getGfriendsLibrary = () => api.get('/gfriends/library')
export const previewGfriendsMatches = (useLocal = false) =>
  api.get('/gfriends/preview', { params: { use_local: useLocal } })
// 2026-07-08 修复 2:本地资料库配置
export const getGfriendsConfig = () => api.get('/gfriends/config')
export const updateGfriendsConfig = (data) => api.post('/gfriends/config', data)
export const testGfriendsLocalLibrary = () => api.post('/gfriends/config/test-local')

// ============== 未识别文件处理 ==============
export const scanUnrecognized = (data) => api.post('/unrecognized/scan', data)
export const manualLinkFile = (data) => api.post('/unrecognized/manual-link', data)
export const manualSetNumber = (data) => api.post('/unrecognized/manual-set-number', data)
export const renameUnrecognizedFile = (data) => api.post('/unrecognized/rename', data)
export const deleteUnrecognizedFile = (data) => api.post('/unrecognized/delete', data)

// ============== CloudDrive2 网盘 ==============
export const getCloudDrive2Config = () => api.get('/cloud-drive2/config')
export const updateCloudDrive2Config = (data) => api.put('/cloud-drive2/config', data)
export const loginCloudDrive2 = (data) => api.post('/cloud-drive2/login', data || {})
export const getCloudDrive2Status = () => api.get('/cloud-drive2/status')
export const listCloudDrive2Dir = (path) => api.get('/cloud-drive2/list', { params: { path } })
export const getCloudDrive2FileInfo = (path) => api.get('/cloud-drive2/file-info', { params: { path } })
export const scanCloudDrive2 = (params) => api.get('/cloud-drive2/scan', { params })
export const getCloudDrive2StreamUrl = (path) => api.get('/cloud-drive2/stream-url', { params: { path } })

// ============== 115 网盘离线下载 ==============
// 注意:后端实际端点为 /offline-tasks(连字符),旧封装错误地用了 /offline/tasks
export const getPan115Config = () => api.get('/pan-115/config')
export const updatePan115Config = (data) => api.put('/pan-115/config', data)
export const getPan115Status = () => api.get('/pan-115/status')
// 手动登录(可选传 cookies/token 覆盖配置)
export const loginPan115 = (data = {}) => api.post('/pan-115/login', data || {})
// 浏览器登录(后端启动真实 Playwright 浏览器,用于 Cookie 失效时重新登录)
export const loginPan115Browser = () => api.post('/config/cookie-login/pan115')
// 浏览器登录状态轮询(后端返回 starting/opening/waiting/saving/completed/failed)
export const getPan115BrowserStatus = () => api.get('/config/cookie-login/pan115/status')
// 列出离线下载任务(后端端点为 /offline-tasks)
export const listPan115OfflineTasks = (page = 1, page_size = 30) =>
  api.get('/pan-115/offline-tasks', { params: { page, page_size } })
// 添加离线下载任务(磁力链/HTTP/ed2k)
export const addPan115OfflineTask = (magnet_url, target_cid = undefined) =>
  api.post('/pan-115/offline-tasks', { magnet_url, target_cid })
// 取消(删除)离线下载任务 - 后端用 DELETE /offline-tasks/{task_id}
export const cancelPan115OfflineTask = (task_id) => api.delete(`/pan-115/offline-tasks/${task_id}`)
// 兼容别名:旧名 deletePan115OfflineTask
export const deletePan115OfflineTask = (task_id) => api.delete(`/pan-115/offline-tasks/${task_id}`)
// 文件浏览(按 folder_id 导航,后端参数名为 folder_id 而非 cid)
export const listPan115Files = (folder_id, limit = 100, offset = 0) =>
  api.get('/pan-115/files', { params: { folder_id, limit, offset } })
// 扫描文件夹(参数对齐后端 ScanRequest: folder_id / recursive / max_depth)
export const scanPan115 = (data) => api.post('/pan-115/scan', data)
export const scanPan115Videos = (folder_id, recursive = true, max_depth = 5) =>
  api.post('/pan-115/scan', { folder_id, recursive, max_depth })
// 搜索文件
export const searchPan115Files = (keyword, folder_id = undefined) =>
  api.get('/pan-115/files/search', { params: { keyword, folder_id } })
// 获取文件下载直链(按 pickcode)
export const getPan115DownloadUrl = (pickcode) => api.get(`/pan-115/files/${pickcode}/download-url`)
// 获取文件 SHA1
export const getPan115FileSha1 = (file_id) => api.get(`/pan-115/files/${file_id}/sha1`)
// 移动文件
export const movePan115Files = (file_ids, target_cid) =>
  api.post('/pan-115/files/move', { file_ids, target_cid })
// 获取当前登录用户信息
export const getPan115UserInfo = () => api.get('/pan-115/user-info')

// ============== Metatube 插件 ==============
export const getMetatubeConfig = () => api.get('/metatube-config/config')
export const updateMetatubeConfig = (data) => api.put('/metatube-config/config', data)

// ============== 多来源数据精选 ==============
export const getSourceMergeFields = (movieId) => api.get(`/source-merge/${movieId}/fields`)
export const previewSourceScrape = (movieId, source) => api.post(`/source-merge/${movieId}/preview`, { source })
export const applySourceMerge = (movieId, fields) => api.post(`/source-merge/${movieId}/apply`, { fields })
export const getSourceMergeMeta = () => api.get('/source-merge/fields-meta')

// ============== 演员头像刮削（§头像补充） ==============
// 本地头像资料库状态（探测 O:\MDCX\GitHub-ZIP\P1-High\gfriends-master）
export const getAvatarLibraryStatus = () => api.get('/actors/avatar-scrape/library')
// 启动后台刮削，支持本地资料库优先模式
export const startAvatarScrape = (opts = {}) => {
  const { minMovies = 2, useLocalLibrary = false } = opts
  return api.post('/actors/avatar-scrape/start', null, {
    params: { min_movies: minMovies, use_local_library: useLocalLibrary }
  })
}
export const getAvatarScrapeStatus = (jobId) =>
  api.get(`/actors/avatar-scrape/status/${jobId}`)
export const cancelAvatarScrape = (jobId) =>
  api.post(`/actors/avatar-scrape/cancel/${jobId}`)
export const previewAvatarScrape = (opts = {}) => {
  const { minMovies = 2, useLocalLibrary = false } = opts
  return api.get('/actors/avatar-scrape/preview', {
    params: { min_movies: minMovies, use_local_library: useLocalLibrary }
  })
}

// ============== TVBox / MacCMS 开放接口（§7.10） ==============
export const getTvboxConfig = () => api.get('/tvbox-config/config')
export const updateTvboxConfig = (data) => api.put('/tvbox-config/config', data)
export const regenerateTvboxToken = () => api.post('/tvbox-config/regenerate-token')
export const testTvboxEndpoint = () => api.post('/tvbox-config/test')
export const getTvboxClientsGuide = () => api.get('/tvbox-config/clients-guide')

// ============== 下载器统一管理（§7.11） ==============
// 对接 qBittorrent / Transmission / Aria2，统一 RESTful API
export const getDownloaderConfig = () => api.get('/downloaders/config')
export const updateDownloaderConfig = (data) => api.put('/downloaders/config', data)
export const getDownloaderStatus = () => api.get('/downloaders/status')
export const listDownloaderTasks = (status) =>
  api.get('/downloaders/tasks', { params: { status } })
export const addDownloaderTask = (data) => api.post('/downloaders/tasks', data)
export const cancelDownloaderTask = (taskId) => api.delete(`/downloaders/tasks/${taskId}`)
export const pauseDownloaderTask = (taskId) => api.post(`/downloaders/tasks/${taskId}/pause`)
export const resumeDownloaderTask = (taskId) => api.post(`/downloaders/tasks/${taskId}/resume`)
export const testDownloaderConnection = (type) => api.post('/downloaders/test', { type })

// ============================================
// Themes 皮肤插件（§7.8 主题插件化）
// ============================================
export const getThemesConfig = () => api.get('/themes/config')
export const updateThemesConfig = (data) => api.put('/themes/config', data)
export const getPresetThemes = () => api.get('/themes/presets')
export const saveCustomTheme = (data) => api.post('/themes/custom', data)
export const deleteCustomTheme = (name) => api.delete(`/themes/custom/${name}`)

// ============================================
// Schema 驱动设置页（§7.9 Schema 驱动设置页）
// 根据 Pydantic 模型自动生成的 JSON Schema 渲染表单
// 路由前缀：/schema
// ============================================
// 获取所有配置段的 schema（按分组组织）
export const getConfigSchema = () => api.get('/schema')
// 获取指定配置段的 schema
export const getConfigSectionSchema = (section) => api.get(`/schema/${section}`)
// 获取所有配置段的当前值
export const getConfigValues = () => api.get('/schema/values')
// 获取指定配置段的当前值
export const getConfigSectionValues = (section) => api.get(`/schema/values/${section}`)
// 更新指定配置段的值（带 Pydantic 校验）
export const updateConfigSectionValues = (section, values) =>
  api.put(`/schema/values/${section}`, values)
// 校验配置值（不保存）
export const validateConfig = (section, values) =>
  api.post('/schema/validate', { section, values })

// ============================================
// 部署档位管理（§7.12 四档渐进式部署）
// 路由前缀：/deploy
// ============================================
// 获取四档部署对比表
export const getDeployTiers = () => api.get('/deploy/tiers')
// 获取当前运行档位信息
export const getCurrentDeployTier = () => api.get('/deploy/current')
// 获取指定档位详情
export const getDeployTierDetail = (tierId) => api.get(`/deploy/tiers/${tierId}`)
// 获取指定档位部署文件清单
export const getDeployTierFiles = (tierId) => api.get(`/deploy/tiers/${tierId}/files`)
// 获取指定档位环境变量
export const getDeployTierEnvVars = (tierId) => api.get(`/deploy/tiers/${tierId}/env-vars`)
// 获取运行时环境信息（容器/K8s/Python 检测）
export const getDeployRuntimeInfo = () => api.get('/deploy/runtime-info')
// 获取部署指南（可指定目标档位，auto=自动推荐）
export const getDeployGuide = (tier = 'auto') => api.get('/deploy/guide', { params: { tier } })

// ============================================
// 自动备份管理 API
// 路由前缀：/backup
// ============================================
// 立即创建备份
export const createBackup = (note = '') => api.post('/backup/create', { note })
// 列出所有备份
export const listBackups = () => api.get('/backup/list')
// 获取备份统计
export const getBackupStats = () => api.get('/backup/stats')
// 从备份恢复
export const restoreBackup = (name) => api.post(`/backup/${name}/restore`)
// 删除备份
export const deleteBackup = (name) => api.delete(`/backup/${name}`)
// 获取备份配置
export const getBackupConfig = () => api.get('/backup/config')
// 更新备份配置
export const updateBackupConfig = (config) => api.put('/backup/config', config)
// 下载备份文件(返回 blob,需携带 token)
// 注意:此端点返回二进制,不能用默认的 axios 拦截器(会解析成 json)
// 用法: const blob = await downloadBackup(name)
//       const url = URL.createObjectURL(blob); link.href = url; link.click();
export const downloadBackup = (name) =>
  api.get(`/backup/download/${name}`, { responseType: 'blob' })

// ============================================
// 302 反代播放(§11 A3)
// ============================================
export const proxyPlay = (movieId) => api.get(`/proxy-play/${movieId}`)
export const proxyPlayInfo = (movieId) => api.get(`/proxy-play/${movieId}/info`)

// ============================================
// 海报增强(§11 A4)
// ============================================
export const enhancePoster = (data) => api.post('/poster-enhance/enhance', data)
export const batchEnhancePosters = (movieIds) => api.post('/poster-enhance/batch-enhance', { movie_ids: movieIds })
export const getWatermarkLabels = () => api.get('/poster-enhance/labels')
export const getWatermarkPositions = () => api.get('/poster-enhance/positions')
export const getPosterEnhanceConfig = () => api.get('/poster-enhance/config')
export const updatePosterEnhanceConfig = (data) => api.put('/poster-enhance/config', data)

// ============================================
// 系列订阅(§11 A2)
// ============================================
export const getSeriesSubscriptions = (params) => api.get('/series-subscriptions', { params })
export const subscribeSeries = (data) => api.post('/series-subscriptions', data)
export const unsubscribeSeries = (seriesId) => api.delete(`/series-subscriptions/${seriesId}`)
export const checkSeriesSubscriptions = () => api.post('/series-subscriptions/check')
export const getSeriesSubscriptionNewMovies = (params) => api.get('/series-subscriptions/new-movies', { params })

// ============================================
// 订阅自动下载(§11 A1)
// ============================================
export const getSubscriptionDownloaderStatus = () => api.get('/subscription-downloader/status')
export const checkSubscriptionDownloads = () => api.post('/subscription-downloader/check')
export const manualDownload = (data) => api.post('/subscription-downloader/download', data)

// ============================================
// 影片图谱(§11 A5)
// ============================================
export const getMovieGraph = (movieId, depth = 1) => api.get(`/movie-graph/${movieId}/graph`, { params: { depth } })
export const getMovieRecommendations = (movieId, limit = 10) => api.get(`/movie-graph/${movieId}/recommendations`, { params: { limit } })
export const saveMovieRelation = (data) => api.post('/movie-graph/relation', data)

// ============================================
// AI 智能推荐(§11 A6)
// ============================================
export const getRecommendations = (limit = 20) => api.get('/recommendations', { params: { limit } })
export const refreshRecommendations = () => api.post('/recommendations/refresh')
export const dismissRecommendation = (movieId) => api.post(`/recommendations/${movieId}/dismiss`)

// ============================================
// NFO 免改名半自动刮削 (v4.1 C9)
// 路由前缀：/nfo-scrape
// ============================================
// 扫描目录中的所有 .nfo 文件
export const scanNfoDirectory = (data) => api.post('/nfo-scrape/scan-dir', data)
// 导入单个 NFO 文件元数据到数据库
export const scrapeNfoFile = (data) => api.post('/nfo-scrape/scrape-file', data)
// 预览 NFO 解析结果（不写入数据库）
export const previewNfo = (filePath) => api.get(`/nfo-scrape/preview/${encodeURIComponent(filePath)}`)

// ============================================
// fanart.tv 集成 (v4.1 C1)
// 路由前缀：/fanart
// ============================================
// 按 TMDB ID 搜索 fanart.tv 资源
export const searchFanarts = (tmdbId) => api.get(`/fanart/search/${tmdbId}`)
// 获取影片已关联的 fanart 资源
export const getMovieFanarts = (movieId) => api.get(`/fanart/movie/${movieId}`)
// 下载并应用 fanart 背景图到影片
export const downloadMovieFanart = (movieId) => api.post(`/fanart/download/${movieId}`)
// 更新影片的 TMDB ID
export const updateMovieTmdbId = (movieId, tmdbId) => api.put(`/fanart/movie/${movieId}/tmdb-id`, { tmdb_id: tmdbId })
// 获取 fanart 配置
export const getFanartConfig = () => api.get('/fanart/config')

// ============================================
// 自动整理规则（AutoOrganize）
// 路由前缀：/auto-organize
// ============================================
// 列出所有自动整理规则
export const getAutoOrganizeRules = () => api.get('/auto-organize/rules')
// 创建自动整理规则
export const createAutoOrganizeRule = (data) => api.post('/auto-organize/rules', data)
// 更新自动整理规则
export const updateAutoOrganizeRule = (id, data) => api.put(`/auto-organize/rules/${id}`, data)
// 删除自动整理规则
export const deleteAutoOrganizeRule = (id) => api.delete(`/auto-organize/rules/${id}`)
// 手动触发整理检查
export const triggerAutoOrganizeCheck = () => api.post('/auto-organize/check')

// ============================================
// mnamer 智能重命名(§B1/B2/B4)
// 路由前缀:/mnamer
// ============================================
// 健康检查(mnamer 是否可用 + 版本)
export const getMnamerHealth = () => api.get('/mnamer/health')
// 获取候选列表(预览,不执行重命名)
export const getMnamerCandidates = (data) => api.post('/mnamer/candidates', data)
// 预览目标路径(不执行重命名)
export const previewMnamerTarget = (data) => api.post('/mnamer/target', data)
// 执行重命名
export const executeMnamerRename = (data) => api.post('/mnamer/rename', data)
// 获取 mnamer 配置(API Key 掩码)
export const getMnamerConfig = () => api.get('/mnamer/config')
// 更新 mnamer 配置
export const updateMnamerConfig = (data) => api.put('/mnamer/config', data)
