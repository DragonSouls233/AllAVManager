import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { useThemeStore } from './theme'
import defaultTheme from '../themes/default.json'
import midnightTheme from '../themes/midnight.json'
import sunsetTheme from '../themes/sunset.json'
import forestTheme from '../themes/forest.json'
import roseTheme from '../themes/rose.json'
import cinemaTheme from '@/themes/cinema.json'
import { getThemesConfig, updateThemesConfig } from '../api'

// localStorage 持久化键
const THEME_NAME_KEY = 'mdcx_theme_name'
const CUSTOM_THEMES_KEY = 'mdcx_custom_themes'

// 预设主题列表（内置）
const PRESET_THEMES = [
  defaultTheme,
  midnightTheme,
  sunsetTheme,
  forestTheme,
  roseTheme,
  cinemaTheme,
]

// ============== 颜色工具函数 ==============

/**
 * hex 转 rgb 对象
 */
function hexToRgb(hex) {
  if (!hex || typeof hex !== 'string') return { r: 64, g: 158, b: 255 }
  const cleaned = hex.replace('#', '').trim()
  if (cleaned.length !== 6) return { r: 64, g: 158, b: 255 }
  const r = parseInt(cleaned.substring(0, 2), 16)
  const g = parseInt(cleaned.substring(2, 4), 16)
  const b = parseInt(cleaned.substring(4, 6), 16)
  if ([r, g, b].some((n) => Number.isNaN(n))) return { r: 64, g: 158, b: 255 }
  return { r, g, b }
}

/**
 * rgb 转 hex 字符串
 */
function rgbToHex(r, g, b) {
  const toHex = (n) =>
    Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

/**
 * 颜色变亮（amount: 0~1）
 */
function lighten(hex, amount) {
  const { r, g, b } = hexToRgb(hex)
  return rgbToHex(
    r + (255 - r) * amount,
    g + (255 - g) * amount,
    b + (255 - b) * amount
  )
}

/**
 * 颜色变暗（amount: 0~1）
 */
function darken(hex, amount) {
  const { r, g, b } = hexToRgb(hex)
  return rgbToHex(r * (1 - amount), g * (1 - amount), b * (1 - amount))
}

/**
 * hex 转 rgba 字符串
 */
function rgba(hex, alpha) {
  const { r, g, b } = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// ============== localStorage 工具 ==============

function loadCustomThemes() {
  try {
    const raw = localStorage.getItem(CUSTOM_THEMES_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch (e) {
    return []
  }
}

function saveCustomThemes(themes) {
  try {
    localStorage.setItem(CUSTOM_THEMES_KEY, JSON.stringify(themes))
  } catch (e) {
    // 忽略存储失败
  }
}

function loadThemeName() {
  return localStorage.getItem(THEME_NAME_KEY) || 'default'
}

/**
 * 皮肤主题 Store（§7.8 皮肤插件机制）
 *
 * 与 theme.js 的协调关系：
 * - theme.js 管理「明暗模式」（light/dark），通过 html.dark class 切换
 * - themes.js（本 store）管理「颜色皮肤」（accent 主题色 + 圆角 + 字号）
 * - accent 颜色（primary/success/...）在明暗模式下保持一致
 * - 中性色（background/surface/text/border）仅在浅色模式下覆盖；
 *   暗黑模式下移除覆盖，让 styles/index.css 的 html.dark 规则生效
 */
export const useThemesStore = defineStore('themes', () => {
  // ============== State ==============
  const presetThemes = ref(PRESET_THEMES)
  const customThemes = ref(loadCustomThemes())
  // 当前已保存的主题名
  const activeThemeName = ref(loadThemeName())
  // 预览中的主题名（未确认保存）；为 null 表示与 active 一致
  const previewingName = ref(null)

  // ============== Getters ==============
  const allThemes = computed(() => [
    ...presetThemes.value,
    ...customThemes.value,
  ])

  const currentTheme = computed(() => {
    const name = previewingName.value || activeThemeName.value
    return (
      allThemes.value.find((t) => t.name === name) || presetThemes.value[0]
    )
  })

  const isPreviewing = computed(
    () =>
      previewingName.value !== null &&
      previewingName.value !== activeThemeName.value
  )

  const isCustom = computed(() => {
    const name = previewingName.value || activeThemeName.value
    return customThemes.value.some((t) => t.name === name)
  })

  // ============== 主题应用核心 ==============

  /**
   * 将主题应用到 document.documentElement 的 CSS 变量
   * @param {Object} theme 主题对象
   */
  function applyThemeToDOM(theme) {
    if (!theme || !theme.colors) return
    const root = document.documentElement
    const colors = theme.colors

    // 1. accent 颜色（明暗模式通用，始终应用）
    root.style.setProperty('--primary-color', colors.primary)
    root.style.setProperty('--primary-light', lighten(colors.primary, 0.2))
    root.style.setProperty('--primary-dark', darken(colors.primary, 0.2))
    root.style.setProperty('--success-color', colors.success)
    root.style.setProperty('--warning-color', colors.warning)
    root.style.setProperty('--danger-color', colors.danger)
    root.style.setProperty('--info-color', colors.info)
    // 品牌渐变（从主色派生）
    root.style.setProperty(
      '--brand-gradient',
      `linear-gradient(135deg, ${colors.primary} 0%, ${darken(colors.primary, 0.25)} 100%)`
    )
    root.style.setProperty(
      '--brand-gradient-soft',
      `linear-gradient(135deg, ${rgba(colors.primary, 0.1)} 0%, ${rgba(darken(colors.primary, 0.25), 0.1)} 100%)`
    )
    // 链接色
    root.style.setProperty('--link-color', colors.link || colors.primary)

    // 2. 中性色 —— 与 theme.js 的明暗模式协调
    //    浅色模式：覆盖背景/表面/文字/边框
    //    暗黑模式：移除覆盖，让 styles/index.css 的 html.dark 规则生效
    const themeStore = useThemeStore()
    const neutralProps = [
      '--bg-page',
      '--bg-card',
      '--text-primary',
      '--text-regular',
      '--text-secondary',
      '--text-placeholder',
      '--border-color',
      '--border-light',
    ]

    if (themeStore.isDark) {
      // 暗黑模式：移除中性色内联覆盖，交给 index.css 的 html.dark 规则
      neutralProps.forEach((p) => root.style.removeProperty(p))
    } else {
      // 浅色模式：应用主题中性色
      root.style.setProperty('--bg-page', colors.background)
      root.style.setProperty('--bg-card', colors.surface)
      root.style.setProperty('--text-primary', colors.text)
      root.style.setProperty('--text-regular', colors.text)
      // 次级文字 = 主文字稍亮
      root.style.setProperty('--text-secondary', lighten(colors.text, 0.3))
      root.style.setProperty('--text-placeholder', lighten(colors.text, 0.5))
      root.style.setProperty('--border-color', colors.border)
      // 边框浅色 = 边框色稍亮
      root.style.setProperty('--border-light', lighten(colors.border, 0.5))
    }

    // 3. 圆角（从 radius 派生 sm/md/lg/xl）
    const r = Number(theme.radius) || 8
    root.style.setProperty('--radius-sm', `${Math.round(r * 0.5)}px`)
    root.style.setProperty('--radius-md', `${r}px`)
    root.style.setProperty('--radius-lg', `${Math.round(r * 1.5)}px`)
    root.style.setProperty('--radius-xl', `${Math.round(r * 2)}px`)

    // 4. 字号
    const fs = Number(theme.font_size) || 14
    root.style.fontSize = `${fs}px`
  }

  /**
   * 应用当前主题（active 或 preview）
   */
  function applyCurrent() {
    applyThemeToDOM(currentTheme.value)
  }

  // ============== Actions ==============

  /**
   * 初始化主题（应用启动时调用）
   * 会从后端拉取配置（如果可用），否则使用 localStorage
   */
  async function loadThemes() {
    // 先用 localStorage 中的主题立即应用，避免闪烁
    applyCurrent()

    // 监听 theme.js 的 isDark 变化，暗黑模式切换时重新应用中性色策略
    // （只在首次初始化时注册一次 watch）
    const themeStore = useThemeStore()
    watch(
      () => themeStore.isDark,
      () => applyCurrent()
    )

    // 尝试从后端同步配置（失败则静默使用本地配置）
    try {
      const res = await getThemesConfig()
      if (res && res.active_theme) {
        activeThemeName.value = res.active_theme
        localStorage.setItem(THEME_NAME_KEY, res.active_theme)
      }
      if (res && res.custom_themes && Array.isArray(res.custom_themes)) {
        // 后端自定义主题覆盖本地（后端为准）
        customThemes.value = res.custom_themes
        saveCustomThemes(customThemes.value)
      }
      applyCurrent()
    } catch (e) {
      // 后端不可用时使用本地配置，不报错
    }
  }

  /**
   * 设置（保存并应用）主题
   * @param {string} name 主题名
   */
  async function setTheme(name) {
    const theme = allThemes.value.find((t) => t.name === name)
    if (!theme) {
      ElMessage.error(`主题「${name}」不存在`)
      return
    }
    activeThemeName.value = name
    previewingName.value = null
    localStorage.setItem(THEME_NAME_KEY, name)
    applyThemeToDOM(theme)

    // 同步到后端（失败不阻塞）
    try {
      await updateThemesConfig({
        active_theme: name,
        custom_themes: customThemes.value,
      })
    } catch (e) {
      // 后端同步失败，本地仍生效
    }
  }

  /**
   * 预览主题（仅应用，不保存）
   * @param {string} name 主题名
   */
  function previewTheme(name) {
    const theme = allThemes.value.find((t) => t.name === name)
    if (!theme) return
    previewingName.value = name
    applyThemeToDOM(theme)
  }

  /**
   * 取消预览，回到已保存的主题
   */
  function resetTheme() {
    previewingName.value = null
    const theme = allThemes.value.find(
      (t) => t.name === activeThemeName.value
    )
    if (theme) applyThemeToDOM(theme)
  }

  /**
   * 导出主题为 JSON 对象
   * @param {string} name 主题名（默认当前主题）
   * @returns {Object|null} 主题 JSON
   */
  function exportTheme(name) {
    const target = name || previewingName.value || activeThemeName.value
    const theme = allThemes.value.find((t) => t.name === target)
    if (!theme) return null
    // 深拷贝，避免外部修改影响内部状态
    return JSON.parse(JSON.stringify(theme))
  }

  /**
   * 从 JSON 对象导入主题（添加到自定义主题）
   * @param {Object} data 主题 JSON
   * @param {boolean} apply 是否立即应用
   * @returns {boolean} 是否导入成功
   */
  function importTheme(data, apply = false) {
    if (!data || !data.name || !data.colors) {
      ElMessage.error('主题格式无效：缺少 name 或 colors 字段')
      return false
    }
    // 校验必需颜色字段
    const required = [
      'primary',
      'success',
      'warning',
      'danger',
      'info',
      'background',
      'surface',
      'text',
      'border',
    ]
    for (const key of required) {
      if (!data.colors[key]) {
        ElMessage.error(`主题格式无效：缺少 colors.${key}`)
        return false
      }
    }
    // 名称冲突检查
    const exists = allThemes.value.some((t) => t.name === data.name)
    if (exists) {
      // 覆盖同名的自定义主题
      customThemes.value = customThemes.value.filter((t) => t.name !== data.name)
    }
    // 补充可选字段
    const theme = {
      display_name: data.name,
      description: data.description || '导入的自定义主题',
      radius: data.radius || 8,
      font_size: data.font_size || 14,
      ...data,
    }
    if (!theme.colors.link) theme.colors.link = theme.colors.primary
    customThemes.value.push(theme)
    saveCustomThemes(customThemes.value)
    // 同步到后端（不阻塞）
    updateThemesConfig({
      active_theme: activeThemeName.value,
      custom_themes: customThemes.value,
    }).catch(() => {})
    if (apply) {
      setTheme(theme.name)
    } else {
      ElMessage.success(`主题「${theme.display_name || theme.name}」已导入`)
    }
    return true
  }

  /**
   * 创建自定义主题
   * @param {Object} data 主题定义
   * @returns {string|null} 新主题名
   */
  function createCustomTheme(data) {
    if (!data.name) {
      ElMessage.error('主题名不能为空')
      return null
    }
    if (!data.colors || !data.colors.primary) {
      ElMessage.error('主题必须包含 primary 颜色')
      return null
    }
    // 预设主题名冲突
    if (presetThemes.value.some((t) => t.name === data.name)) {
      ElMessage.error(`主题名「${data.name}」与预设主题冲突`)
      return null
    }
    // 覆盖同名自定义主题
    customThemes.value = customThemes.value.filter((t) => t.name !== data.name)
    const theme = {
      display_name: data.name,
      description: data.description || '用户自定义主题',
      radius: data.radius || 8,
      font_size: data.font_size || 14,
      colors: {
        primary: data.colors.primary,
        success: data.colors.success || '#67c23a',
        warning: data.colors.warning || '#e6a23c',
        danger: data.colors.danger || '#f56c6c',
        info: data.colors.info || '#909399',
        background: data.colors.background || '#f0f2f5',
        surface: data.colors.surface || '#ffffff',
        text: data.colors.text || '#303133',
        border: data.colors.border || '#ebeef5',
        link: data.colors.link || data.colors.primary,
      },
      ...data,
    }
    customThemes.value.push(theme)
    saveCustomThemes(customThemes.value)
    // 同步到后端
    updateThemesConfig({
      active_theme: activeThemeName.value,
      custom_themes: customThemes.value,
    }).catch(() => {})
    ElMessage.success(`自定义主题「${theme.display_name}」已创建`)
    return theme.name
  }

  /**
   * 删除自定义主题
   * @param {string} name 主题名
   */
  function deleteCustomTheme(name) {
    const idx = customThemes.value.findIndex((t) => t.name === name)
    if (idx === -1) {
      ElMessage.error(`自定义主题「${name}」不存在`)
      return
    }
    customThemes.value.splice(idx, 1)
    saveCustomThemes(customThemes.value)
    // 同步到后端
    updateThemesConfig({
      active_theme: activeThemeName.value,
      custom_themes: customThemes.value,
    }).catch(() => {})
    // 若删除的是当前主题，回退到 default
    if (activeThemeName.value === name) {
      setTheme('default')
    }
    if (previewingName.value === name) {
      resetTheme()
    }
    ElMessage.success(`主题「${name}」已删除`)
  }

  /**
   * 根据名称获取主题对象
   */
  function getThemeByName(name) {
    return allThemes.value.find((t) => t.name === name) || null
  }

  return {
    // state
    presetThemes,
    customThemes,
    activeThemeName,
    previewingName,
    // getters
    allThemes,
    currentTheme,
    isPreviewing,
    isCustom,
    // actions
    loadThemes,
    setTheme,
    previewTheme,
    resetTheme,
    exportTheme,
    importTheme,
    createCustomTheme,
    deleteCustomTheme,
    getThemeByName,
    applyThemeToDOM,
    applyCurrent,
    // 工具函数（供视图层使用）
    lighten,
    darken,
    rgba,
  }
})
