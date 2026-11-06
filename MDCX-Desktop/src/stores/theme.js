import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const THEME_KEY = 'mdcx_theme'
const SYSTEM_THEME_QUERY = '(prefers-color-scheme: dark)'
const VALID_PREFERENCES = ['light', 'dark', 'system']

/**
 * 读取主题偏好。
 *
 * 兼容旧版本：localStorage 里原本就存 'light' / 'dark'，直接沿用；
 * 无记录时 Electron 桌面端默认影院暗色、Web 端默认亮色（保持历史行为）。
 * ⚠️ 这里的默认值判定必须与 index.html 首屏内联脚本保持一致，否则深色用户
 *    冷启动会先闪一帧白底。
 */
function readPreference() {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (VALID_PREFERENCES.includes(saved)) return saved
    const isElectron = typeof window !== 'undefined' &&
      !!(window.electronAPI && window.electronAPI.isElectron)
    return isElectron ? 'dark' : 'light'
  } catch (e) {
    return 'light'
  }
}

function systemPrefersDarkNow() {
  try {
    return typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia(SYSTEM_THEME_QUERY).matches
  } catch (e) {
    return false
  }
}

/**
 * 主题 Store
 *
 * 🔴 2026-11-06：由布尔二态升级为 light | dark | system 三态（参考 JavBoss
 *    web/src/app/theme/preferences.js），并配合 index.html 的首屏同步预写消除
 *    深色用户冷启动闪白。对外仍保留 isDark / mode / toggleDark / setDark 等
 *    原有 API，AppTopbar 的主题按钮与 stores/themes.js 的 watch 均无需改动。
 */
export const useThemeStore = defineStore('theme', () => {
  // ============== State ==============
  /** @type {'light'|'dark'|'system'} 用户偏好，持久化到 localStorage */
  const preference = ref(readPreference())
  /** 系统当前是否深色，仅 preference === 'system' 时参与计算 */
  const systemDark = ref(systemPrefersDarkNow())

  // ============== Getters ==============
  /** 实际是否深色（兼容既有 UI：仍是布尔） */
  const isDark = computed(() => preference.value === 'dark' ||
    (preference.value === 'system' && systemDark.value))
  /** 实际生效模式：'dark' | 'light' */
  const mode = computed(() => (isDark.value ? 'dark' : 'light'))

  // ============== 内部：系统主题 / 跨标签监听 ==============
  let mql = null
  let listenersBound = false

  function onSystemChange(e) {
    systemDark.value = !!e.matches
    applyTheme()
  }

  function onStorage(e) {
    if (e.key && e.key !== THEME_KEY) return
    preference.value = readPreference()
    applyTheme()
  }

  // ============== Actions ==============
  /**
   * 应用当前主题到 document.documentElement。
   * 与 index.html 首屏脚本写同样的三处：dark class / colorScheme / theme-color。
   */
  function applyTheme() {
    const root = document.documentElement
    const dark = isDark.value
    root.classList.toggle('dark', dark)
    root.style.colorScheme = dark ? 'dark' : 'light'
    root.dataset.themePreference = preference.value
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', dark ? '#141414' : '#ffffff')
  }

  function persist(next) {
    preference.value = next
    try {
      localStorage.setItem(THEME_KEY, next)
    } catch (e) {
      /* localStorage 被禁用时仅内存生效 */
    }
    applyTheme()
  }

  /**
   * 切换主题（保留原「一键亮/暗」入口语义）：
   * 基于当前**实际生效**的模式取反，system 态下手动切换会落回显式 light/dark。
   */
  function toggleDark() {
    persist(isDark.value ? 'light' : 'dark')
  }

  /** 设置为指定明暗（兼容旧调用） */
  function setDark(dark) {
    persist(dark ? 'dark' : 'light')
  }

  /** 设置三态偏好，供将来需要「跟随系统」选项的界面调用 */
  function setPreference(next) {
    if (!VALID_PREFERENCES.includes(next)) return
    persist(next)
  }

  /**
   * 初始化（应用启动时调用一次）：应用主题 + 注册监听。
   * 监听只绑一次，避免 HMR 重复注册。
   */
  function initTheme() {
    applyTheme()
    if (listenersBound) return
    listenersBound = true
    try {
      if (typeof window.matchMedia === 'function') {
        mql = window.matchMedia(SYSTEM_THEME_QUERY)
        if (mql.addEventListener) mql.addEventListener('change', onSystemChange)
        else if (mql.addListener) mql.addListener(onSystemChange)
      }
      window.addEventListener('storage', onStorage)
    } catch (e) {
      /* 极简/受限浏览器环境下降级为不跟随系统 */
    }
  }

  return {
    // state
    isDark,
    preference,
    // getters
    mode,
    // actions
    toggleDark,
    setDark,
    setPreference,
    initTheme,
    applyTheme
  }
})
