import { defineStore } from 'pinia'
import * as api from '@/api/uncensored'

export const useUncensoredStore = defineStore('uncensored', {
  state: () => ({
    movies: [],
    movieDetail: null,
    actors: [],
    actorDetail: null,
    studios: [],
    genres: [],
    crawlers: [],
    favorites: [],
    stats: null,
    total: 0,
    page: 1,
    pageSize: 24,
    loading: false,
    searchKeyword: '',
    sortField: 'created_at',
    sortOrder: 'desc',
    statusFilter: '',
    scraping: false,
    scrapingProgress: 0,
    scrapingMessage: '',
    pendingCount: 0,
    selectedMovies: [],
    specialScrapeData: null
  }),

  getters: {
    hasFavorites: (state) => state.favorites.length > 0,
    isScraping: (state) => state.scraping
  },

  actions: {
    setSort({ field, order }) {
      this.sortField = field
      this.sortOrder = order
    },

    async loadMovies() {
      this.loading = true
      try {
        const params = {
          page: this.page,
          page_size: this.pageSize,
          sort: this.sortField,
          order: this.sortOrder
        }
        if (this.searchKeyword) params.search = this.searchKeyword
        if (this.statusFilter) params.status = this.statusFilter
        const res = await api.getMovies(params)
        this.movies = res.items || res.data || []
        this.total = res.total || 0
        return res
      } catch (e) {
        console.error('Load movies failed:', e)
        this.movies = []
        this.total = 0
        throw e
      } finally {
        this.loading = false
      }
    },

    async loadActors() {
      this.loading = true
      try {
        const params = { page: this.page, page_size: this.pageSize }
        if (this.searchKeyword) params.search = this.searchKeyword
        if (this.sortField) params.sort = this.sortField
        if (this.sortOrder) params.order = this.sortOrder
        const res = await api.getActors(params)
        this.actors = res.items || res.data || []
        this.total = res.total || 0
        return res
      } catch (e) {
        console.error('Load actors failed:', e)
        this.actors = []
        this.total = 0
        throw e
      } finally {
        this.loading = false
      }
    },

    async loadStudios() {
      const res = await api.getStudios()
      this.studios = res.items || res.data || []
      return res
    },

    async loadGenres() {
      const res = await api.getGenres()
      this.genres = res.items || res.data || []
      return res
    },

    async loadStats() {
      try {
        const res = await api.getStats()
        this.stats = res
      } catch (e) {
        console.error('Load stats failed:', e)
      }
    },

    async loadCrawlers() {
      try {
        const res = await api.getCrawlers()
        this.crawlers = res.items || res.data || res || []
        return this.crawlers
      } catch (e) {
        console.error('Load crawlers failed:', e)
        return []
      }
    },

    async loadFavorites() {
      try {
        const res = await api.getFavoriteMovies({ page: this.page, page_size: this.pageSize })
        this.favorites = res.items || res.data || []
        this.total = res.total || 0
      } catch (e) {
        console.error('Load favorites failed:', e)
      }
    },

    async scrapeMovie(code) {
      return await api.scrapeMovie(code)
    },

    async scrapeBatch(movieIds) {
      this.scraping = true
      this.scrapingProgress = 0
      this.scrapingMessage = 'Starting batch scrape...'
      try {
        return await api.scrapeBatch({ movie_ids: movieIds })
      } finally {
        this.scraping = false
      }
    },

    async triggerScrapeAll() {
      this.scraping = true
      this.scrapingMessage = 'Scraping all movies...'
      try {
        return await api.startScraping({ mode: 'all' })
      } finally {
        this.scraping = false
      }
    },

    async refreshCover() {
      try {
        return await api.refreshCoverImages({})
      } catch (e) {
        console.error('Refresh cover failed:', e)
        throw e
      }
    },

    async refillImages(movieId) {
      this.loading = true
      try {
        return await api.refillMedia(movieId, {})
      } finally {
        this.loading = false
      }
    },

    async reloadNfo(movieId) {
      try {
        return await api.reloadMovieNfo(movieId)
      } catch (e) {
        console.error('Reload NFO failed:', e)
        throw e
      }
    },

    async generatePoster(movieId, data) {
      return await api.generatePoster(movieId, data)
    },

    async triggerImportNfo(data) {
      return await api.importNfo(data)
    },

    async testCode(data) {
      return await api.testCode(data)
    },

    async checkFolder(folderPath) {
      return await api.checkFolder(folderPath)
    },

    async getPendingCount() {
      try {
        const res = await api.getPendingScrapeCodes()
        this.pendingCount = res.total || res.count || 0
        return this.pendingCount
      } catch (e) {
        this.pendingCount = 0
        return 0
      }
    },

    async loadSpecialScrape() {
      try {
        const res = await api.getSpecialScrape()
        this.specialScrapeData = res
      } catch (e) {
        console.error('Load special scrape failed:', e)
      }
    },

    async executeSpecialScrape(data) {
      return await api.executeSpecialScrape(data)
    },

    async toggleFavorite(movieId) {
      await api.toggleFavorite(movieId)
      if (this.favorites.some(f => f.id === movieId || f.movie_id === movieId)) {
        this.favorites = this.favorites.filter(f => f.id !== movieId && f.movie_id !== movieId)
      } else {
        await this.loadFavorites()
      }
    }
  }
})
