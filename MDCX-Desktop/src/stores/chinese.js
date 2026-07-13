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

  async function loadActors() {
    const res = await getChineseActors()
    actors.value = res || []
    return actors.value
  }

  async function syncActors() {
    const res = await syncChineseFolderActors()
    await loadActors()
    return res
  }

  return { movies, total, actors, loading, page, pageSize, loadMovies, loadMovieDetail, loadActors, syncActors }
})
