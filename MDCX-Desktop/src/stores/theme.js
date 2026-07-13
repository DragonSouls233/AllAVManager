import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const THEME_KEY = 'mdcx_theme'

/**
 * 主题 Store
 * 统一管理亮色/暗黑模式，持久化到 localStorage
 */
export const useThemeStore = defineStore('theme', () => {
  // ============== State ==============
  const isDark = ref(localStorage.getItem(THEME_KEY) === 'dark')

  // ============== Getters ==============
  const mode = computed(() => (isDark.value ? 'dark' : 'light'))

  // ============== Actions ==============
  /**
   * 应用当前主题到 document.documentElement
   * 通过 class="dark" 切换（element-plus dark css 变量）
   */
  function applyTheme() {
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  /**
   * 切换主题
   */
  function toggleDark() {
    isDark.value = !isDark.value
    localStorage.setItem(THEME_KEY, isDark.value ? 'dark' : 'light')
    applyTheme()
  }

  /**
   * 设置为指定主题
   */
  function setDark(dark) {
    isDark.value = !!dark
    localStorage.setItem(THEME_KEY, isDark.value ? 'dark' : 'light')
    applyTheme()
  }

  /**
   * 初始化（应用启动时调用一次）
   */
  function initTheme() {
    applyTheme()
  }

  return {
    // state
    isDark,
    // getters
    mode,
    // actions
    toggleDark,
    setDark,
    initTheme,
    applyTheme
  }
})
