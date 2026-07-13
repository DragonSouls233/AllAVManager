import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElNotification } from 'element-plus'
import {
  startAvatarScrape,
  getAvatarScrapeStatus,
  cancelAvatarScrape,
  getAvatarLibraryStatus
} from '@/api'

/**
 * 头像刮削全局 Store
 *
 * 负责：
 * - 本地资料库状态探测（O:\MDCX\GitHub-ZIP\P1-High）
 * - 启动 / 轮询 / 取消 后台刮削任务
 * - 通过 ElNotification 向用户推送全局进度通知（不局限于某个弹窗）
 */
export const useAvatarScrapeStore = defineStore('avatarScrape', () => {
  // ============== State ==============
  const jobId = ref(null)
  const active = ref(false)
  const status = ref({})          // 后端 /avatar-scrape/status/{id} 的快照
  const library = ref({})         // 本地资料库状态 { available, path, count }
  const useLocalLibrary = ref(false)
  let pollingTimer = null

  // ============== Getters ==============
  const progressPercent = computed(() => {
    const total = status.value?.total || 0
    const completed = status.value?.completed || 0
    if (!total) return 0
    return Math.min(100, Math.round((completed / total) * 100))
  })

  const isFinished = computed(() =>
    ['completed', 'cancelled', 'failed'].includes(status.value?.status)
  )

  const statusText = computed(() => {
    const s = status.value || {}
    if (s.status === 'running') return `刮削中 ${s.completed || 0}/${s.total || 0}`
    if (s.status === 'completed') return `已完成 ${s.success || 0} 个`
    if (s.status === 'cancelled') return '已取消'
    if (s.status === 'failed') return `失败：${s.error || '未知错误'}`
    if (s.status === 'idle') return '待启动'
    return s.status ? `状态：${s.status}` : '空闲'
  })

  // ============== Actions ==============
  /** 探测本地资料库是否可用 */
  async function initLibrary() {
    try {
      const res = await getAvatarLibraryStatus()
      library.value = res || {}
    } catch (e) {
      library.value = { available: false, path: null, count: null }
    }
  }

  function stopPolling() {
    if (pollingTimer) {
      clearInterval(pollingTimer)
      pollingTimer = null
    }
  }

  async function pollOnce() {
    if (!jobId.value) return
    try {
      const s = await getAvatarScrapeStatus(jobId.value)
      status.value = s || {}
      if (isFinished.value) {
        finish()
      }
    } catch (e) {
      // 404 表示任务已销毁，视为结束
      finish('error')
    }
  }

  function startPolling() {
    stopPolling()
    pollingTimer = setInterval(pollOnce, 2000)
    pollOnce()
  }

  function finish(reason) {
    stopPolling()
    active.value = false
    const s = status.value || {}
    if (reason === 'error' || s.status === 'failed') {
      ElNotification({
        title: '头像刮削失败',
        message: s.error || '任务异常结束',
        type: 'error',
        duration: 6000
      })
    } else if (s.status === 'cancelled') {
      ElNotification({
        title: '已取消头像刮削',
        message: `共处理 ${(s.completed || 0)} 个演员`,
        type: 'warning',
        duration: 4000
      })
    } else {
      ElNotification({
        title: '头像刮削完成',
        message: `成功 ${s.success || 0} · 跳过 ${s.skipped || 0} · 失败 ${s.failed || 0}`,
        type: 'success',
        duration: 5000
      })
    }
    jobId.value = null
  }

  /** 启动一次刮削任务 */
  async function start(opts = {}) {
    if (active.value) {
      ElNotification({
        title: '已有任务进行中',
        message: '请等待当前刮削完成或先取消',
        type: 'warning'
      })
      return false
    }
    const params = {
      minMovies: opts.minMovies ?? 2,
      useLocalLibrary: opts.useLocalLibrary ?? useLocalLibrary.value
    }
    try {
      const res = await startAvatarScrape(params)
      jobId.value = res.job_id
      active.value = true
      status.value = { status: 'running', total: 0, completed: 0 }
      ElNotification({
        title: '头像刮削已启动',
        message: params.useLocalLibrary
          ? '优先使用本地资料库（离线）匹配头像'
          : `只处理 ${params.minMovies} 部以上且无头像的演员`,
        type: 'success',
        duration: 4000
      })
      startPolling()
      return true
    } catch (e) {
      ElNotification({
        title: '启动失败',
        message: e?.response?.data?.detail || e.message || '未知错误',
        type: 'error'
      })
      active.value = false
      return false
    }
  }

  /** 取消当前任务 */
  async function cancel() {
    if (!jobId.value) return
    try {
      await cancelAvatarScrape(jobId.value)
      ElNotification({ title: '正在取消…', type: 'info', duration: 2000 })
    } catch (e) {
      // 忽略取消失败，轮询会在任务消失后自动收尾
    }
  }

  return {
    jobId,
    active,
    status,
    library,
    useLocalLibrary,
    progressPercent,
    isFinished,
    statusText,
    initLibrary,
    start,
    cancel,
    stopPolling
  }
})
