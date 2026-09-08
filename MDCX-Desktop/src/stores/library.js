import { defineStore } from 'pinia'
import { getModules } from '@/api/modules'

/** 模块定义：桌面端模块切换器与影片库共用 */
export const MODULES = [
  { key: 'jav', label: 'JAV 有码', emoji: '🎬' },
  { key: 'uncensored', label: 'JAV 无码', emoji: '🔓' },
  { key: 'fc2', label: 'FC2', emoji: '📹' },
  { key: 'chinese', label: '国产', emoji: '🇨🇳' },
  { key: 'western', label: '欧美', emoji: '🌍' },
  { key: 'pornhub', label: 'PORNHub', emoji: '🌐' },
  { key: 'anime', label: '里番', emoji: '🎭' }
]

const STORAGE_KEY = 'mdcx_desktop_module'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    /** 当前模块 key，'' 表示全部模块 */
    currentModule: localStorage.getItem(STORAGE_KEY) || 'jav',
    /** 后端返回的模块启用状态 */
    enabledModules: {},
    /** 全局搜索关键词（顶栏输入，影片库消费） */
    keyword: '',
    /** 进入影片库时携带的维度筛选（类别/系列/演员 → Library） */
    filter: {
      genre: '',
      series: '',
      actor: '',
      sort: '-release_date'
    }
  }),

  getters: {
    /** 可供切换的模块（后端未禁用即显示） */
    availableModules(state) {
      return MODULES.filter(m => state.enabledModules[m.key] !== false)
    },
    currentLabel(state) {
      if (!state.currentModule) return '全部'
      return (MODULES.find(m => m.key === state.currentModule) || {}).label || state.currentModule
    },
    hasFilter(state) {
      return !!(state.filter.genre || state.filter.series || state.filter.actor)
    }
  },

  actions: {
    setModule(key) {
      this.currentModule = key || ''
      localStorage.setItem(STORAGE_KEY, this.currentModule)
      // 切换模块时清空维度筛选，避免跨模块串味
      this.clearFilter()
    },

    /** 从类别/系列/演员页跳入影片库 */
    applyFilter(patch) {
      Object.assign(this.filter, patch)
    },

    clearFilter() {
      this.filter = { genre: '', series: '', actor: '', sort: this.filter.sort }
    },

    setKeyword(kw) {
      this.keyword = kw || ''
    },

    async loadModules() {
      try {
        const data = await getModules()
        const list = Array.isArray(data) ? data : (data?.modules || data?.items || [])
        const map = {}
        for (const m of list) {
          const key = m.name || m.module_name || m.key
          if (key) map[key] = m.enabled !== false
        }
        if (Object.keys(map).length) this.enabledModules = map
      } catch {
        // 后端不可用时保持全部可用（乐观显示）
      }
    }
  }
})
