import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getWesternMovies, getWesternMovie, getWesternActors, getWesternActor, scanWesternMedia } from '@/api/western'

export const useWesternStore = defineStore('western', () => {
  const movies = ref([])
  const total = ref(0)
  const actors = ref([])
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(24)

  async function loadMovies(params = {}) {
    loading.value = true
    try {
      const res = await getWesternMovies({ skip: (page.value - 1) * pageSize.value, limit: pageSize.value, ...params })
      movies.value = res.items || []
      total.value = res.total || 0
    } finally {
      loading.value = false
    }
  }

  async function loadMovieDetail(id) {
    return await getWesternMovie(id)
  }

  async function loadActors() {
    const res = await getWesternActors()
    actors.value = res || []
    return actors.value
  }

  async function loadActorDetail(id) {
    return await getWesternActor(id)
  }

  async function triggerScan() {
    return await scanWesternMedia()
  }

  return { movies, total, actors, loading, page, pageSize, loadMovies, loadMovieDetail, loadActors, loadActorDetail, triggerScan }
})
