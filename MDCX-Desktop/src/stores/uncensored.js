import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getUncensoredMovies, getUncensoredMovie, getUncensoredActors, getUncensoredActor } from '@/api/uncensored'
import { scanModule } from '@/api/modules'

export const useUncensoredStore = defineStore('uncensored', () => {
  const movies = ref([])
  const total = ref(0)
  const actors = ref([])
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(24)

  async function loadMovies(params = {}) {
    loading.value = true
    try {
      const res = await getUncensoredMovies({ skip: (page.value - 1) * pageSize.value, limit: pageSize.value, ...params })
      movies.value = res.items || []
      total.value = res.total || 0
    } finally {
      loading.value = false
    }
  }

  async function loadMovieDetail(id) {
    return await getUncensoredMovie(id)
  }

  async function loadActors() {
    const res = await getUncensoredActors()
    actors.value = res || []
    return actors.value
  }

  async function loadActorDetail(id) {
    return await getUncensoredActor(id)
  }

  async function triggerScan() {
    return await scanModule('uncensored')
  }

  return { movies, total, actors, loading, page, pageSize, loadMovies, loadMovieDetail, loadActors, loadActorDetail, triggerScan }
})
