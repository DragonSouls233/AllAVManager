import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getChineseMovies, getChineseMovie, getChineseActors, syncChineseFolderActors } from '@/api/chinese'

export const useChineseStore = defineStore('chinese', () => {
  const movies = ref([])
  const total = ref(0)
  const actors = ref([])
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(24)
  // 🔴 2026-10-13 演员分页（服务端）。后端 /actors 已支持 skip/limit，
  // 不再全表捞出后在前端切片。
  const actorPage = ref(1)
  const actorPageSize = ref(24)
  const actorTotal = ref(0)

  async function loadMovies(params = {}) {
    loading.value = true
    try {
      const res = await getChineseMovies({ page: page.value, page_size: pageSize.value, ...params })
      movies.value = res.items || []
      total.value = res.total || 0
    } finally {
      loading.value = false
    }
  }

  async function loadMovieDetail(id) {
    return await getChineseMovie(id)
  }

  async function loadActors(params = {}) {
    // 服务端分页：skip/limit 下推 SQL，count 也下推（不再全表捞）
    const q = {
      skip: (actorPage.value - 1) * actorPageSize.value,
      limit: actorPageSize.value,
      ...params,
    }
    const res = await getChineseActors(q)
    // 兼容信封（现行）与历史裸数组
    if (Array.isArray(res)) {
      actors.value = res
      actorTotal.value = res.length
    } else {
      actors.value = res?.items || []
      actorTotal.value = res?.total || 0
    }
    // 返回数组：ActorDetail.vue 等调用方要 .find(a => a.id === id)
    return actors.value
  }

  async function syncActors() {
    const res = await syncChineseFolderActors()
    await loadActors()
    return res
  }

  return { movies, total, actors, loading, page, pageSize,
           actorPage, actorPageSize, actorTotal, loadMovies, loadMovieDetail, loadActors, syncActors }
})
