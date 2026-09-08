<template>
  <section>
    <!-- 类别墙视图 -->
    <template v-if="!activeGenre">
      <div class="cinema-page-head">
        <h1 class="cinema-page-title">类别</h1>
        <span class="cinema-page-count">
          {{ lib.currentLabel }} · {{ summary ? `${summary.total_categories} 个类别 / ${summary.total_movies} 部影片` : '' }}
        </span>
      </div>

      <div class="cinema-filters">
        <el-input
          v-model="q"
          placeholder="搜索类别，如 巨乳 / 人妻 / 学生…"
          clearable
          size="small"
          style="width: 260px"
          @input="onSearch"
        />
        <el-select v-model="sortBy" size="small" style="width: 140px" @change="applyLocalSort">
          <el-option label="按影片数 ↓" value="count" />
          <el-option label="按名称" value="name" />
        </el-select>
      </div>

      <div v-if="error" class="cinema-empty">
        <div class="cinema-empty-icon">⚠️</div>
        <div class="cinema-empty-text">{{ error }}</div>
        <el-button size="small" style="margin-top: 12px" @click="load">重试</el-button>
      </div>

      <div v-else-if="loading" class="genre-skeletons">
        <div v-for="n in 24" :key="n" class="genre-skeleton" />
      </div>

      <div v-else-if="!genres.length" class="cinema-empty">
        <div class="cinema-empty-icon">🏷️</div>
        <div class="cinema-empty-text">
          {{ q
            ? `没有匹配「${q}」的类别`
            : (isAnime ? `${lib.currentLabel} 类别浏览需服务端部署新版 anime 接口（当前旧版暂不支持）` : `${lib.currentLabel} 暂无类别数据`) }}
        </div>
      </div>

      <div v-else class="genre-wall">
        <button
          v-for="g in genres"
          :key="g.name"
          class="genre-chip"
          type="button"
          :title="`${g.count} 部`"
          @click="enterGenre(g.name)"
        >
          <span class="genre-name">{{ g.name }}</span>
          <span class="genre-count">{{ fmtCount(g.count) }}</span>
        </button>
      </div>
    </template>

    <!-- 类别影片视图 -->
    <template v-else>
      <div class="cinema-page-head">
        <h1 class="cinema-page-title">
          <el-button text size="small" @click="backToGenres">← 全部类别</el-button>
          <span class="inline-title">{{ activeGenre }}</span>
          <span class="cinema-page-count">{{ movieTotal }} 部</span>
        </h1>
      </div>

      <div v-if="moviesError" class="cinema-empty">
        <div class="cinema-empty-icon">⚠️</div>
        <div class="cinema-empty-text">{{ moviesError }}</div>
        <el-button size="small" style="margin-top: 12px" @click="loadMovies(true)">重试</el-button>
      </div>
      <div v-else-if="!movieLoading && !movies.length" class="cinema-empty">
        <div class="cinema-empty-icon">🎬</div>
        <div class="cinema-empty-text">「{{ activeGenre }}」暂无影片</div>
      </div>
      <div v-else class="cinema-grid">
        <template v-if="movieLoading && !movies.length">
          <div v-for="n in 18" :key="`sk-${n}`" class="poster-skeleton" />
        </template>
        <PosterCard
          v-for="m in movies"
          :key="`${lib.currentModule}-${m.id}`"
          :movie="m"
          @open="openDetail"
          @play="playMovie"
        />
      </div>

      <div class="load-bar">
        <el-button v-if="hasMore" :loading="movieLoading" size="small" text @click="loadMovies()">
          加载更多（{{ movies.length }}/{{ movieTotal }}）
        </el-button>
        <span v-else-if="movieTotal > 0" class="load-end">已到底部</span>
      </div>
    </template>
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import PosterCard from '@/components/cinema/PosterCard.vue'
import { useLibraryStore } from '@/stores/library'
import { getModuleCategories, getMoviesByCategory } from '@/api'
import { getAnimeMovies, getAnimeCategories } from '@/api/anime'
import { decorateMovies, fmtCount, enrichStatus } from '@/utils/browse'

const PAGE = 48
const router = useRouter()
const lib = useLibraryStore()

const genres = ref([])
const summary = ref(null)
const loading = ref(false)
const error = ref('')
const q = ref('')
const sortBy = ref('count')
let rawGenres = []

const activeGenre = ref('')
const movies = ref([])
const movieTotal = ref(0)
const movieLoading = ref(false)
const moviesError = ref('')
const hasMore = ref(false)
let movieSeq = 0

const isAnime = computed(() => lib.currentModule === 'anime')
const moduleLabel = computed(() => lib.currentLabel)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = lib.currentModule === 'anime'
      ? await getAnimeCategories({ limit: 2000 })
      : await getModuleCategories(lib.currentModule, { limit: 2000 })
    summary.value = res || null
    const items = (res?.items || res?.categories || []).map((g) => ({
      name: g.name || g.genre,
      count: g.count ?? g.movie_count ?? 0
    }))
    rawGenres = items
    applyLocalSort()
  } catch (e) {
    // 服务端未部署 anime 类别端点（老版 anime_routes.py）时返回 404「未知模块」——
    // 降级为友好空态提示，而不是报错。部署新版后端后自动恢复可用。
    const animeUnsupported = lib.currentModule === 'anime'
      && (e?.response?.status === 404 || /未知模块|not found/i.test(String(e?.response?.data?.detail || e?.message)))
    error.value = animeUnsupported
      ? ''
      : (e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载类别失败，请检查服务器连接')
    if (animeUnsupported) {
      summary.value = { total_categories: 0, total_movies: 0, items: [] }
      rawGenres = []
      applyLocalSort()
    }
  } finally {
    loading.value = false
  }
}

function onSearch() {
  const kw = q.value.trim().toLowerCase()
  if (!kw) {
    genres.value = rawGenres.slice()
    return
  }
  genres.value = rawGenres.filter((g) => g.name.toLowerCase().includes(kw))
}

function applyLocalSort() {
  let list = rawGenres.slice()
  if (sortBy.value === 'name') list.sort((a, b) => a.name.localeCompare(b.name, 'zh'))
  else list.sort((a, b) => b.count - a.count)
  if (q.value.trim()) {
    const kw = q.value.trim().toLowerCase()
    list = list.filter((g) => g.name.toLowerCase().includes(kw))
  }
  genres.value = list
}

function enterGenre(name) {
  activeGenre.value = name
  resetMovies()
  loadMovies(true)
}
function backToGenres() {
  activeGenre.value = ''
  resetMovies()
}

function resetMovies() {
  movieSeq++
  movies.value = []
  movieTotal.value = 0
  hasMore.value = false
  moviesError.value = ''
}

async function loadMovies(fresh = false) {
  if (fresh) resetMovies()
  if (movieLoading.value || !activeGenre.value) return
  if (!fresh && !hasMore.value) return
  const seq = ++movieSeq
  movieLoading.value = true
  moviesError.value = ''
  try {
    const mod = lib.currentModule
    const skip = movies.value.length
    const res = mod === 'anime'
      ? await getAnimeMovies({ genre: activeGenre.value, sort: 'recent', skip, limit: PAGE })
      : await getMoviesByCategory(mod, activeGenre.value, {
          page: Math.floor(skip / PAGE) + 1,
          page_size: PAGE
        })
    if (seq !== movieSeq) return
    const list = decorateMovies(res?.items || [], mod)
    movies.value = fresh ? list : movies.value.concat(list)
    movieTotal.value = res?.total ?? movies.value.length
    hasMore.value = movies.value.length < movieTotal.value
    enrichStatus(list, mod)
  } catch (e) {
    if (seq !== movieSeq) return
    moviesError.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载影片失败'
  } finally {
    if (seq === movieSeq) movieLoading.value = false
  }
}

function openDetail(movie) {
  router.push(`/movie/${lib.currentModule}/${movie.id}`)
}
function playMovie(movie) {
  router.push(`/mpv/${lib.currentModule}/${movie.id}`)
}

watch(() => lib.currentModule, () => {
  if (activeGenre.value) backToGenres()
  load()
})

onMounted(load)

// keep-alive：返回时刷新类别影片角标（限最近 600）
onActivated(() => {
  if (movies.value.length) enrichStatus(movies.value, lib.currentModule, 600)
})
</script>

<style scoped>
.genre-wall {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.genre-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 14px;
  border: 1px solid var(--cinema-line);
  border-radius: 999px;
  background: var(--cinema-1);
  color: var(--text-1);
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s, background 0.15s;
  font-size: 13px;
}
.genre-chip:hover {
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  transform: translateY(-1px);
}
.genre-count {
  font-size: 11px;
  color: var(--text-3);
  background: var(--cinema-0);
  border-radius: 999px;
  padding: 1px 8px;
}
.inline-title {
  font-size: 20px;
  color: var(--brand);
}
.genre-skeletons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.genre-skeleton {
  width: 110px;
  height: 34px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--cinema-1) 25%, var(--cinema-2) 50%, var(--cinema-1) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}
.load-bar {
  display: flex;
  justify-content: center;
  padding: 16px 0 8px;
}
.load-end {
  font-size: 12px;
  color: var(--text-3);
}
@keyframes shimmer {
  to { background-position: -200% 0; }
}
</style>
