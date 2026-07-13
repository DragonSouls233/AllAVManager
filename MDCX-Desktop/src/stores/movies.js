import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMovies } from '@/api'

/**
 * 影片列表 Store（v3.4 新增）
 *
 * 统一管理影片列表的查询状态、筛选条件、分页、排序，
 * 供 Movies.vue 及其他需要影片列表的页面复用。
 */
export const useMoviesStore = defineStore('movies', () => {
  // ===== 列表数据 =====
  const movies = ref([])
  const total = ref(0)
  const loading = ref(false)

  // ===== 分页 =====
  const page = ref(1)
  const pageSize = ref(24)
  const hasMore = computed(() => movies.value.length < total.value)

  // ===== 搜索 =====
  const keyword = ref('')

  // ===== 排序 =====
  // '' | 'rating' | 'release_date' | 'play_count' | 'random'
  const sortBy = ref('')
  const isRandom = ref(false)
  const randomSeed = ref(null)

  // ===== 筛选条件 =====
  const selectedLetter = ref('')
  const selectedTags = ref([])
  const tagMode = ref('OR') // 'AND' | 'OR'
  const minRating = ref(null)
  const maxRating = ref(null)
  const onlyFavorite = ref(false)

  // ===== 计算属性 =====
  const hasAdvancedFilters = computed(() => {
    return !!(
      selectedTags.value.length ||
      minRating.value !== null ||
      maxRating.value !== null ||
      onlyFavorite.value ||
      selectedLetter.value
    )
  })

  const hasActiveFilters = computed(() => {
    return !!keyword.value || hasAdvancedFilters.value
  })

  // ===== 构建查询参数 =====
  const buildParams = (overrides = {}) => {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      ...overrides,
    }
    if (keyword.value) params.keyword = keyword.value
    if (sortBy.value && !isRandom.value) params.sort_by = sortBy.value
    if (isRandom.value) {
      params.sort_by = 'random'
      if (randomSeed.value) params.seed = randomSeed.value
    }
    if (selectedLetter.value) params.letter = selectedLetter.value
    if (selectedTags.value.length) {
      params.tags = selectedTags.value.join(',')
      params.tag_mode = tagMode.value
    }
    if (minRating.value !== null) params.min_rating = minRating.value
    if (maxRating.value !== null) params.max_rating = maxRating.value
    if (onlyFavorite.value) params.only_favorite = true
    return params
  }

  // ===== Actions =====

  /** 加载第一页（重置列表） */
  const fetchFirstPage = async () => {
    page.value = 1
    loading.value = true
    try {
      const res = await getMovies(buildParams())
      movies.value = res.items || []
      total.value = res.total || 0
    } finally {
      loading.value = false
    }
  }

  /** 加载下一页（无限滚动追加） */
  const fetchNextPage = async () => {
    if (!hasMore.value || loading.value) return
    page.value += 1
    loading.value = true
    try {
      const res = await getMovies(buildParams())
      movies.value.push(...(res.items || []))
      total.value = res.total || total.value
    } finally {
      loading.value = false
    }
  }

  /** 重置所有筛选与分页 */
  const resetFilters = () => {
    keyword.value = ''
    selectedLetter.value = ''
    selectedTags.value = []
    minRating.value = null
    maxRating.value = null
    onlyFavorite.value = false
    isRandom.value = false
    randomSeed.value = null
    sortBy.value = ''
  }

  /** 切换随机排序（生成新种子） */
  const shuffleRandom = () => {
    isRandom.value = true
    sortBy.value = ''
    randomSeed.value = Date.now()
  }

  return {
    // 状态
    movies,
    total,
    loading,
    page,
    pageSize,
    keyword,
    sortBy,
    isRandom,
    randomSeed,
    selectedLetter,
    selectedTags,
    tagMode,
    minRating,
    maxRating,
    onlyFavorite,
    // 计算属性
    hasMore,
    hasAdvancedFilters,
    hasActiveFilters,
    // actions
    buildParams,
    fetchFirstPage,
    fetchNextPage,
    resetFilters,
    shuffleRandom,
  }
})
