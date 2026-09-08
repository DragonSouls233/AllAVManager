<template>
  <section>
    <!-- 系列列表视图 -->
    <template v-if="!activeSeries">
      <div class="cinema-page-head">
        <h1 class="cinema-page-title">系列</h1>
        <span class="cinema-page-count">
          {{ lib.currentLabel }} · {{ total }} 个系列
        </span>
      </div>

      <div class="cinema-filters">
        <el-input
          v-model="q"
          placeholder="搜索系列名"
          clearable
          size="small"
          style="width: 240px"
          @input="onSearch"
        />
        <template v-if="isAnime">
          <el-select v-model="sortBy" size="small" style="width: 150px" @change="reload">
            <el-option label="按作品数" value="count" />
            <el-option label="按名称" value="name" />
            <el-option label="按最新更新" value="recent" />
            <el-option label="按收藏时间" value="fav_time" />
          </el-select>
          <el-button
            size="small"
            :type="onlyFav ? 'warning' : 'default'"
            :plain="!onlyFav"
            @click="onlyFav = !onlyFav; reload()"
          >
            ★ 只看喜好
          </el-button>
        </template>
      </div>

      <div v-if="error" class="cinema-empty">
        <div class="cinema-empty-icon">⚠️</div>
        <div class="cinema-empty-text">{{ error }}</div>
        <el-button size="small" style="margin-top: 12px" @click="load">重试</el-button>
      </div>

      <div v-else-if="isUnsupported" class="cinema-empty">
        <div class="cinema-empty-icon">📚</div>
        <div class="cinema-empty-text">{{ lib.currentLabel }} 模块暂无系列数据</div>
      </div>

      <div v-else-if="!loading && !series.length" class="cinema-empty">
        <div class="cinema-empty-icon">📚</div>
        <div class="cinema-empty-text">{{ q ? `没有匹配「${q}」的系列` : `${lib.currentLabel} 暂无系列数据` }}</div>
      </div>

      <!-- anime 系列横卡墙 -->
      <div v-else-if="isAnime" v-loading="loading" class="anime-series-wall">
        <article
          v-for="s in series"
          :key="s.id"
          class="anime-s-card"
          tabindex="0"
          @click="enterSeries(s)"
          @keyup.enter="enterSeries(s)"
        >
          <div class="asc-cover">
            <img v-if="s.coverUrl" :src="s.coverUrl" :alt="s.name" loading="lazy" @error="onImgErr" />
            <div v-else class="asc-fallback">📚</div>
            <span class="asc-count">{{ s.movie_count }} 集</span>
            <button
              class="asc-fav"
              :class="{ on: s.favorited }"
              type="button"
              :title="s.favorited ? '移出喜好' : '加入喜好'"
              @click.stop="toggleFav(s)"
            >★</button>
          </div>
          <div class="asc-name" :title="s.name">{{ s.name }}</div>
          <div v-if="s.maker" class="asc-maker">{{ s.maker }}</div>
          <div v-if="s.latest_date" class="asc-latest">最新 {{ s.latest_date }}</div>
        </article>
      </div>

      <!-- 其他模块：系列名列表 -->
      <div v-else v-loading="loading" class="series-name-list">
        <button
          v-for="s in series"
          :key="s.name"
          class="series-name-row"
          type="button"
          @click="enterSeries(s)"
        >
          <span class="sn-name" :title="s.name">{{ s.name }}</span>
          <span class="sn-count">{{ s.movie_count }} 部</span>
          <span class="sn-arrow">›</span>
        </button>
      </div>

      <div v-if="total > pageSize && !activeSeries" class="load-bar">
        <el-pagination
          v-model:current-page="page"
          :total="total"
          :page-size="pageSize"
          :pager-count="5"
          background
          small
          layout="prev, pager, next, total"
          @current-change="load"
        />
      </div>
    </template>

    <!-- 系列影片视图 -->
    <template v-else>
      <div class="cinema-page-head">
        <h1 class="cinema-page-title">
          <el-button text size="small" @click="backToList">← 全部系列</el-button>
          <span class="inline-title">{{ activeSeries.name }}</span>
          <span class="cinema-page-count">{{ movieTotal }} 集</span>
          <button
            v-if="isAnime"
            class="head-fav"
            :class="{ on: activeSeries.favorited }"
            type="button"
            @click="toggleFav(activeSeries)"
          >★ {{ activeSeries.favorited ? '已喜好' : '加入喜好' }}</button>
        </h1>
      </div>

      <div v-if="moviesError" class="cinema-empty">
        <div class="cinema-empty-icon">⚠️</div>
        <div class="cinema-empty-text">{{ moviesError }}</div>
        <el-button size="small" style="margin-top: 12px" @click="loadMovies(true)">重试</el-button>
      </div>
      <div v-else-if="!movieLoading && !movies.length" class="cinema-empty">
        <div class="cinema-empty-icon">🎬</div>
        <div class="cinema-empty-text">该系列暂无影片</div>
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
import { ElMessage } from 'element-plus'
import PosterCard from '@/components/cinema/PosterCard.vue'
import { useLibraryStore } from '@/stores/library'
import { getAnimeSeries, getAnimeSeriesMovies, toggleAnimeFavoriteSeries } from '@/api/anime'
import { getModuleSeries, getModuleSeriesMovies } from '@/api'
import { decorateMovies, normMedia, enrichStatus } from '@/utils/browse'

const PAGE = 48
const router = useRouter()
const lib = useLibraryStore()

const ANIME = 'anime'
const TEXT_SERIES_MODULES = ['jav', 'fc2', 'uncensored', 'western']

const series = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(PAGE)
const loading = ref(false)
const error = ref('')
const q = ref('')
const sortBy = ref('count')
const onlyFav = ref(false)
let searchTimer = null

const activeSeries = ref(null)
const movies = ref([])
const movieTotal = ref(0)
const movieLoading = ref(false)
const moviesError = ref('')
const hasMore = ref(false)
let movieSeq = 0

const isAnime = computed(() => lib.currentModule === ANIME)
const isUnsupported = computed(() => !isAnime.value && !TEXT_SERIES_MODULES.includes(lib.currentModule))

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => reload(), 350)
}
function reload() { page.value = 1; load() }

async function load() {
  if (isUnsupported.value) return
  loading.value = true
  error.value = ''
  try {
    if (isAnime.value) {
      const res = await getAnimeSeries({
        q: q.value || undefined,
        sort: sortBy.value,
        favorite: onlyFav.value || undefined,
        skip: (page.value - 1) * pageSize.value,
        limit: pageSize.value
      })
      series.value = (res?.items || []).map((s) => ({
        ...s,
        coverUrl: normMedia(s.cover || s.cover_url)
      }))
      total.value = res?.total || 0
    } else {
      const res = await getModuleSeries(lib.currentModule, {
        search: q.value || undefined,
        page: page.value,
        page_size: Math.min(pageSize.value, 200)
      })
      series.value = (res?.items || []).map((s) => ({ name: s.name, movie_count: s.movie_count }))
      total.value = res?.total || 0
    }
  } catch (e) {
    error.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载系列失败，请检查服务器连接'
  } finally {
    loading.value = false
  }
}

async function enterSeries(s) {
  activeSeries.value = s
  movies.value = []
  movieTotal.value = 0
  movieLoading.value = false
  moviesError.value = ''
  hasMore.value = false
  await loadMovies(true)
}

function backToList() {
  activeSeries.value = null
  movies.value = []
}

async function loadMovies(fresh = false) {
  if (!activeSeries.value) return
  if (fresh) { movieSeq++; movies.value = []; movieTotal.value = 0; hasMore.value = false; moviesError.value = '' }
  if (movieLoading.value) return
  if (!fresh && !hasMore.value) return
  const seq = ++movieSeq
  movieLoading.value = true
  moviesError.value = ''
  try {
    const mod = lib.currentModule
    let res
    if (isAnime.value) {
      res = await getAnimeSeriesMovies(activeSeries.value.id)
      if (seq !== movieSeq) return
      const list = decorateMovies(res?.items || [], 'anime')
      movies.value = list
      movieTotal.value = res?.total ?? list.length
      hasMore.value = false // anime 系列一次全量返回
      enrichStatus(list, 'anime')
    } else {
      const skip = movies.value.length
      res = await getModuleSeriesMovies(mod, activeSeries.value.name, {
        page: Math.floor(skip / PAGE) + 1,
        page_size: PAGE
      })
      if (seq !== movieSeq) return
      const list = decorateMovies(res?.items || [], mod)
      movies.value = fresh ? list : movies.value.concat(list)
      movieTotal.value = res?.total ?? movies.value.length
      hasMore.value = movies.value.length < movieTotal.value
      enrichStatus(list, mod)
    }
  } catch (e) {
    if (seq !== movieSeq) return
    moviesError.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载集数失败'
  } finally {
    if (seq === movieSeq) movieLoading.value = false
  }
}

async function toggleFav(s) {
  try {
    await toggleAnimeFavoriteSeries(s.id)
    s.favorited = !s.favorited
    ElMessage.success(s.favorited ? `已加入喜好：${s.name}` : `已移出喜好：${s.name}`)
    if (onlyFav.value && activeSeries.value === s) {
      // 只看喜好模式下从列表移除
      series.value = series.value.filter((x) => x.id !== s.id)
    }
    if (activeSeries.value && activeSeries.value.id === s.id) {
      activeSeries.value.favorited = s.favorited
    }
  } catch (e) {
    ElMessage.error('操作失败：' + (e?.message || e))
  }
}

function openDetail(movie) {
  const mod = movie.module_type || lib.currentModule
  router.push(`/movie/${mod}/${movie.id}`)
}
function playMovie(movie) {
  const mod = movie.module_type || lib.currentModule
  router.push(`/mpv/${mod}/${movie.id}`)
}
function onImgErr(e) {
  e.target.style.visibility = 'hidden'
}

watch(() => lib.currentModule, () => {
  activeSeries.value = null
  movies.value = []
  q.value = ''
  reload()
})

onMounted(load)

// keep-alive：从详情/mpv 返回时刷新已加载集数角标（限最近 600）
onActivated(() => {
  if (movies.value.length && activeSeries.value) {
    enrichStatus(movies.value, isAnime.value ? 'anime' : lib.currentModule, 600)
  }
})
</script>

<style scoped>
.inline-title { font-size: 20px; color: var(--brand); }
.head-fav {
  margin-left: 12px;
  padding: 3px 12px;
  border-radius: 999px;
  border: 1px solid var(--cinema-line);
  background: var(--cinema-1);
  color: var(--text-2);
  cursor: pointer;
  font-size: 12px;
  vertical-align: middle;
}
.head-fav.on { color: #f0b429; border-color: #f0b429; background: color-mix(in srgb, #f0b429 15%, transparent); }

.anime-series-wall {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}
.anime-s-card {
  border-radius: 12px;
  overflow: hidden;
  background: var(--cinema-1);
  border: 1px solid var(--cinema-line);
  cursor: pointer;
  transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
}
.anime-s-card:hover {
  transform: translateY(-3px);
  border-color: var(--brand);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.35);
}
.asc-cover {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--cinema-2);
  display: flex;
  align-items: center;
  justify-content: center;
}
.asc-cover img { width: 100%; height: 100%; object-fit: cover; }
.asc-fallback { font-size: 40px; opacity: 0.4; }
.asc-count {
  position: absolute;
  bottom: 8px; right: 8px;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  font-size: 12px;
  padding: 1px 9px;
  border-radius: 999px;
}
.asc-fav {
  position: absolute;
  top: 8px; left: 8px;
  width: 30px; height: 30px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s, transform 0.15s;
}
.asc-fav.on { background: rgba(240, 180, 41, 0.92); }
.asc-fav:hover { transform: scale(1.12); }
.asc-name {
  padding: 9px 10px 2px;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asc-maker { padding: 0 10px; font-size: 12px; color: var(--text-3); }
.asc-latest { padding: 0 10px 10px; font-size: 11px; color: var(--brand-dim); }

.series-name-list { display: flex; flex-direction: column; gap: 6px; }
.series-name-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border: 1px solid var(--cinema-line);
  border-radius: 10px;
  background: var(--cinema-1);
  color: var(--text-1);
  cursor: pointer;
  font-size: 14px;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}
.series-name-row:hover { border-color: var(--brand); background: color-mix(in srgb, var(--brand) 8%, transparent); }
.sn-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sn-count { font-size: 12px; color: var(--text-3); flex-shrink: 0; }
.sn-arrow { color: var(--text-3); font-size: 18px; line-height: 1; flex-shrink: 0; }

.load-bar { display: flex; justify-content: center; padding: 16px 0 8px; }
.load-end { font-size: 12px; color: var(--text-3); }
</style>
