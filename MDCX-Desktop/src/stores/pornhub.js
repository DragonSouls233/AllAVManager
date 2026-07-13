import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePornhubStore = defineStore('pornhub', () => {
  const movies = ref([])
  const total = ref(0)
  const loading = ref(false)

  return { movies, total, loading }
})
