import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useFc2Store = defineStore('fc2', () => {
  const movies = ref([])
  const total = ref(0)
  const loading = ref(false)

  return { movies, total, loading }
})
