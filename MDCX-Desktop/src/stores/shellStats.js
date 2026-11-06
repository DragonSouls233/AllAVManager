/**
 * MDCX · 外壳数据单例（Phase 1）
 *
 * 目的：把「健康 / 全库统计 / 任务统计 / 版本 / 模块开关」收成**全站唯一**数据源。
 * 改造前：AdminLayout 每 30s 拉一次全库聚合，Home.vue 挂载时再拉一次
 *         → 打开首页瞬间 2 次 `getDashboardStats()`（顺序遍历 7 个模块库）。
 * 改造后：外壳与首页全部读本 store，请求数 = 1 份。
 *
 * 纪律（写进 Shared Knowledge，任何人不得违反）：
 *   1. `startPolling()` **只允许** `AdminLayout.onMounted` 调用，子组件永不调；
 *   2. `refresh()` 幂等：进行中则复用同一个 Promise；
 *   3. 子组件禁止自己调 getDashboardStats / getSystemHealth / getTaskStats / getModulesConfig。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getSystemHealth, getDashboardStats, getTaskStats, getVersion } from '@/api'
import { getModulesConfig } from '@/api/modules'
import { MODULES } from '@/config/nav'

/** 健康等级派生：`/stats/health` 没有 status 字段（修正 F4 / 坑 16） */
const HEALTH_TEXT = {
  ok: '服务器正常',
  warn: '服务器降级',
  error: '服务器异常',
  unknown: '未连接',
}

export const useShellStatsStore = defineStore('shellStats', () => {
  // ---------- 原始数据 ----------
  /** @type {import('vue').Ref<'ok'|'warn'|'error'|'unknown'>} */
  const health = ref('unknown')
  /**
   * `/stats/health` 的**原始 payload**。
   * `health` 只存派生出的等级（字符串），凡是要读原始字段的（如
   * `tasks.recent_failed`）都必须从这里取，否则子组件会自己再打一次接口。
   */
  const healthRaw = ref(null)
  /** @type {import('vue').Ref<Object|null>} /stats/dashboard 原样 */
  const dashboard = ref(null)
  /** @type {import('vue').Ref<Object|null>} /stats/tasks 原样 */
  const taskStats = ref(null)
  const version = ref('0.1.0')
  const versionInfo = ref({ version: '0.01', patches: [], build_date: '', patch_level: '' })
  /** @type {import('vue').Ref<Object>} { jav: true, ... } */
  const enabled = ref({})
  const loading = ref(false)
  /** 最近一次刷新是否整体失败（供页面显示「重试」） */
  const lastError = ref('')

  // ---------- 派生：全库统计 ----------
  const moviesTotal = computed(() => {
    const v = dashboard.value?.movies?.total
    return typeof v === 'number' ? v : 0
  })
  const actorsTotal = computed(() => {
    const v = dashboard.value?.actors?.total
    return typeof v === 'number' ? v : 0
  })
  const pendingTotal = computed(() => {
    const v = dashboard.value?.movies?.pending
    return typeof v === 'number' ? v : 0
  })
  const failedTotal = computed(() => {
    const v = dashboard.value?.movies?.failed
    return typeof v === 'number' ? v : 0
  })
  const completedTotal = computed(() => {
    const v = dashboard.value?.movies?.completed
    return typeof v === 'number' ? v : 0
  })

  /** { jav: 1284, uncensored: 320, ... } */
  const moduleMovies = computed(() => {
    const out = {}
    const mods = dashboard.value?.modules || {}
    for (const m of MODULES) {
      const d = mods[m.key]
      if (typeof d === 'number') out[m.key] = d
      else if (d && typeof d.movies === 'number') out[m.key] = d.movies
      else out[m.key] = 0
    }
    return out
  })

  /** { jav: 120, ... } 演员数（dashboard 有就取，没有就是 0） */
  const moduleActors = computed(() => {
    const out = {}
    const mods = dashboard.value?.modules || {}
    for (const m of MODULES) {
      const d = mods[m.key]
      out[m.key] = d && typeof d.actors === 'number' ? d.actors : 0
    }
    return out
  })

  // ---------- 派生：任务 ----------
  const distribution = computed(() => taskStats.value?.status_distribution || {})
  const runningTasks = computed(() => distribution.value.running || 0)
  const taskDone = computed(() => distribution.value.success || 0)
  const taskTotal = computed(() =>
    Object.values(distribution.value).reduce((a, b) => a + (typeof b === 'number' ? b : 0), 0),
  )
  const taskPercent = computed(() =>
    taskTotal.value > 0 ? Math.round((taskDone.value / taskTotal.value) * 100) : 0,
  )

  const healthText = computed(() => HEALTH_TEXT[health.value] || HEALTH_TEXT.unknown)

  /** 最近失败任务数（`/stats/health` 的 `tasks.recent_failed`）。
   *  供首页「系统」卡使用 —— 避免子组件为了一个字段重复请求同一个接口。 */
  const recentFailedTasks = computed(() => {
    const n = healthRaw.value?.tasks?.recent_failed
    return typeof n === 'number' ? n : 0
  })

  /** 模块是否启用（未加载完配置时一律视为启用，避免侧栏闪空） */
  function isModuleEnabled(flag) {
    if (!flag) return true
    return enabled.value[flag] !== false
  }

  // ---------- refresh（幂等） ----------
  /** @type {Promise<any>|null} */
  let inFlight = null

  async function refresh() {
    if (inFlight) return inFlight
    loading.value = true

    const run = (async () => {
      const [h, d, t, v] = await Promise.allSettled([
        getSystemHealth(),
        getDashboardStats(),
        getTaskStats(),
        getVersion(),
      ])

      // 健康：/stats/health 没有 status 字段，按 database.healthy + tasks.error_rate 派生
      if (h.status === 'fulfilled') {
        const payload = h.value || {}
        healthRaw.value = payload
        if (payload?.database?.healthy === false) health.value = 'error'
        else if ((payload?.tasks?.error_rate ?? 0) > 0.2) health.value = 'warn'
        else health.value = 'ok'
      } else {
        // 沿用 AdminLayout.vue 旧判定：有 response = 服务端报了错，无 response = 连不上
        healthRaw.value = null
        health.value = h.reason?.response ? 'error' : 'unknown'
      }

      if (d.status === 'fulfilled') dashboard.value = d.value || null
      if (t.status === 'fulfilled') taskStats.value = t.value || null
      if (v.status === 'fulfilled' && v.value) {
        versionInfo.value = v.value
        version.value = v.value.version || version.value
      }

      const failures = [h, d, t, v].filter((r) => r.status === 'rejected').length
      lastError.value = failures >= 2 ? '统计数据加载失败' : ''
    })().catch((e) => {
      // allSettled 不会 reject；这里只兜底 Promise 链自身的异常
      lastError.value = String(e?.message || e)
    })

    inFlight = run
    try {
      await run
    } finally {
      inFlight = null
      loading.value = false
    }
    return run
  }

  // ---------- 模块开关 ----------
  async function loadModulesEnabled() {
    try {
      const config = await getModulesConfig()
      const next = {}
      if (config && typeof config === 'object') {
        for (const [name, cfg] of Object.entries(config)) {
          if (cfg && typeof cfg.enabled === 'boolean') next[name] = cfg.enabled
          else if (typeof cfg === 'boolean') next[name] = cfg
        }
      }
      enabled.value = next
    } catch {
      // 静默失败：保持「全部启用」，侧栏不因此变空
    }
  }

  // ---------- 轮询（幂等） ----------
  /** @type {number|null} */
  let timer = null

  /**
   * 启动 30s 轮询。已启动则直接返回（幂等）。
   * ⚠️ 只允许 AdminLayout.onMounted 调用。
   * @param {number} [ms]
   */
  function startPolling(ms = 30000) {
    if (timer) return
    refresh().catch(() => {})
    timer = window.setInterval(() => {
      refresh().catch(() => {})
    }, ms)
  }

  function stopPolling() {
    if (timer) {
      window.clearInterval(timer)
      timer = null
    }
  }

  return {
    // 原始
    health,
    healthRaw,
    dashboard,
    taskStats,
    version,
    versionInfo,
    enabled,
    loading,
    lastError,
    // 派生
    moviesTotal,
    actorsTotal,
    pendingTotal,
    failedTotal,
    completedTotal,
    moduleMovies,
    moduleActors,
    distribution,
    runningTasks,
    taskDone,
    taskTotal,
    taskPercent,
    healthText,
    recentFailedTasks,
    // 方法
    isModuleEnabled,
    refresh,
    loadModulesEnabled,
    startPolling,
    stopPolling,
  }
})
