import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getPornhubMovies, getPornhubMovie } from '@/api/pornhub'
import { scanModule } from '@/api/modules'

export const usePornhubStore = defineStore('pornhub', () => {
  const movies = ref([])
  const total = ref(0)
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(24)

  async function loadMovies(params = {}) {
    loading.value = true
    try {
      const res = await getPornhubMovies({ skip: (page.value - 1) * pageSize.value, limit: pageSize.value, ...params })
      movies.value = res.items || []
      total.value = res.total || 0
    } finally {
      loading.value = false
    }
  }

  async function loadMovieDetail(id) {
    return await getPornhubMovie(id)
  }

  async function triggerScan() {
    return await scanModule('pornhub')
  }

  return { movies, total, loading, page, pageSize, loadMovies, loadMovieDetail, triggerScan }
})
