<template>
  <section>
    <!-- 内嵌系列影片视图 -->
    <template v-if="activeSeries">
      <div class="cinema-page-head">
        <h1 class="cinema-page-title">
          <el-button text size="small" @click="activeSeries = null">← 返回喜好</el-button>
          <span class="inline-title">{{ activeSeries.name }}</span>
          <span class="cinema-page-count">{{ seriesMoviesTotal }} 集</span>
        </h1>
      </div>
      <div v-if="seriesMoviesError" class="cinema-empty">
        <div class="cinema-empty-icon">⚠️</div>
        <div class="cinema-empty-text">{{ seriesMoviesError }}</div>
        <el-button size="small" style="margin-top: 12px" @click="loadSeriesMovies(activeSeries)">重试</el-button>
      </div>
      <div v-else-if="!seriesMoviesLoading && !seriesMovies.length" class="cinema-empty">
        <div class="cinema-empty-icon">🎬</div>
        <div class="cinema-empty-text">该系列暂无影片</div>
      </div>
      <div v-else class="cinema-grid">
        <template v-if="seriesMoviesLoading && !seriesMovies.length">
          <div v-for="n in 18" :key="`sk-${n}`" class="poster-skeleton" />
        </template>
        <PosterCard
          v-for="m in seriesMovies"
          :key="`fav-s-${m.id}`"
          :movie="m"
          @open="openMovie('anime', m)"
          @play="playMovie('anime', m)"
        />
      </div>
    </template>

    <!-- 喜好总览 -->
    <template v-else>
      <div class="cinema-page-head">
        <h1 class="cinema-page-title">喜好</h1>
        <span class="cinema-page-count">
          里番系列 {{ animeTotal }} · {{ movieGroups.length ? `影片收藏 ${movieGroupCount}` : '' }}
        </span>
      </div>

      <h2 class="block-title">
        ★ 里番系列
        <el-button text size="small" style="margin-left: 10px" @click="goSeries">
          去「系列」页收藏 →
        </el-button>
      </h2>

      <div class="cinema-filters">
        <el-input
          v-model="q"
          placeholder="搜索喜好的系列名"
          clearable
          size="small"
          style="width: 240px"
          @input="onSearch"
        />
        <el-select v-model="sortBy" size="small" style="width: 150px" @change="reloadAnime">
          <el-option label="最近收藏" value="fav_time" />
          <el-option label="按作品数" value="count" />
          <el-option label="按名称" value="name" />
          <el-option label="按最新更新" value="recent" />
        </el-select>
      </div>

      <div v-if="animeError" class="cinema-empty">
        <div class="cinema-empty-icon">⚠️</div>
        <div class="cinema-empty-text">{{ animeError }}</div>
        <el-button size="small" style="margin-top: 12px" @click="loadAnime(true)">重试</el-button>
      </div>

      <div v-else-if="!animeLoading && !animeList.length" class="cinema-empty">
        <div class="cinema-empty-icon">★</div>
        <div class="cinema-empty-text">还没有喜好的里番系列 — 在「系列」页（里番模块）点卡片左上角 ☆ 即可加入</div>
      </div>

      <div v-else v-loading="animeLoading" class="anime-fav-wall">
        <article
          v-for="s in animeList"
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
            <button class="asc-fav on" type="button" title="移出喜好" @click.stop="removeFav(s)">★</button>
          </div>
          <div class="asc-name" :title="s.name">{{ s.name }}</div>
          <div v-if="s.maker" class="asc-maker">{{ s.maker }}</div>
          <div v-if="s.latest_date" class="asc-latest">最新 {{ s.latest_date }}</div>
          <div v-if="s.favorited_at" class="asc-added">收藏于 {{ (s.favorited_at || '').slice(0, 10) }}</div>
        </article>
      </div>

      <div v-if="animeTotal > animePageSize" class="load-bar">
        <el-pagination
          v-model:current-page="animePage"
          :total="animeTotal"
          :page-size="animePageSize"
          :pager-count="5"
          background
          small
          layout="prev, pager, next, total"
          @current-change="loadAnime()"
        />
      </div>

      <!-- 通用影片收藏（用户自定义收藏夹分组） -->
      <template v-if="movieGroups.length">
        <h2 class="block-title">🎬 影片收藏夹</h2>
        <div v-for="g in movieGroups" :key="g.id" class="fav-group">
          <div class="fav-group-head">
            <span class="fav-group-name">{{ g.name }}</span>
            <span class="fav-group-count">{{ g.item_count }} 部</span>
          </div>
          <div v-if="g.loading" class="fav-group-empty">加载中…</div>
          <div v-else-if="!g.items.length" class="fav-group-empty">暂无条目</div>
          <div v-else class="fav-group-items">
            <div v-for="it in g.items" :key="it.id" class="fav-item" :title="it.entity_name || ''">
              <div class="fav-item-cover">
                <img v-if="itemCover(it)" :src="itemCover(it)" alt="" loading="lazy" @error="onImgErr" />
                <span v-else class="fav-item-fallback">🎬</span>
                <button class="fav-item-del" type="button" title="移出收藏" @click.stop="removeGroupItem(g, it)">✕</button>
              </div>
              <div class="fav-item-meta">
                <span class="fav-item-name">{{ it.entity_name || it.module || '影片' }}</span>
                <span class="fav-item-mod">{{ moduleLabel(it.module) }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PosterCard from '@/components/cinema/PosterCard.vue'
import { useLibraryStore } from '@/stores/library'
import { MODULES } from '@/stores/library'
import { getAnimeFavoriteSeries, removeAnimeFavoriteSeries, getAnimeSeriesMovies } from '@/api/anime'
import { getFavoriteGroups, getFavoriteItems, removeFavoriteItem } from '@/api'
import { decorateMovies, normMedia, enrichStatus } from '@/utils/browse'

const router = useRouter()
const lib = useLibraryStore()

// ===== 里番系列收藏 =====
const animeList = ref([])
const animeTotal = ref(0)
const animePage = ref(1)
const animePageSize = ref(48)
const animeLoading = ref(false)
const animeError = ref('')
const q = ref('')
const sortBy = ref('fav_time')
let searchTimer = null

// ===== 内嵌系列影片 =====
const activeSeries = ref(null)
const seriesMovies = ref([])
const seriesMoviesTotal = ref(0)
const seriesMoviesLoading = ref(false)
const seriesMoviesError = ref('')

// ===== 通用影片收藏 =====
const movieGroups = ref([])

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { animePage.value = 1; loadAnime() }, 350)
}
function reloadAnime() { animePage.value = 1; loadAnime() }

async function loadAnime() {
  animeLoading.value = true
  animeError.value = ''
  try {
    const res = await getAnimeFavoriteSeries({
      q: q.value || undefined,
      sort: sortBy.value,
      skip: (animePage.value - 1) * animePageSize.value,
      limit: animePageSize.value
    })
    animeList.value = (res?.items || []).map((s) => ({ ...s, coverUrl: normMedia(s.cover) }))
    animeTotal.value = res?.total || 0
  } catch (e) {
    animeError.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载喜好失败'
  } finally {
    animeLoading.value = false
  }
}

async function removeFav(s) {
  try {
    await removeAnimeFavoriteSeries(s.id)
    ElMessage.success(`已移出喜好：${s.name}`)
    animeList.value = animeList.value.filter((x) => x.id !== s.id)
    animeTotal.value = Math.max(0, animeTotal.value - 1)
  } catch (e) {
    ElMessage.error('操作失败：' + (e?.message || e))
  }
}

async function enterSeries(s) {
  activeSeries.value = s
  seriesMovies.value = []
  seriesMoviesTotal.value = 0
  seriesMoviesError.value = ''
  seriesMoviesLoading.value = false
  await loadSeriesMovies(s)
}

async function loadSeriesMovies(s) {
  seriesMoviesLoading.value = true
  seriesMoviesError.value = ''
  try {
    const res = await getAnimeSeriesMovies(s.id)
    seriesMovies.value = decorateMovies(res?.items || [], 'anime')
    seriesMoviesTotal.value = res?.total ?? seriesMovies.value.length
    enrichStatus(seriesMovies.value, 'anime')
  } catch (e) {
    seriesMoviesError.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载系列影片失败'
  } finally {
    seriesMoviesLoading.value = false
  }
}

// ===== 通用收藏夹（影片分组）=====
async function loadMovieGroups() {
  try {
    const groups = await getFavoriteGroups('movie')
    if (!Array.isArray(groups) || !groups.length) return
    movieGroups.value = await Promise.all(
      groups.map(async (g) => {
        let items = []
        try {
          const r = await getFavoriteItems(g.id)
          items = Array.isArray(r) ? r : (r?.items || [])
        } catch { items = [] }
        return { ...g, items, loading: false }
      })
    )
  } catch { movieGroups.value = [] }
}

const movieGroupCount = computed(() => {
  let n = 0
  for (const g of movieGroups.value) n += g.items.length
  return n
})

async function removeGroupItem(g, it) {
  try {
    await removeFavoriteItem(g.id, it.entity_id)
    g.items = g.items.filter((x) => x.id !== it.id)
    ElMessage.success('已移出收藏')
  } catch (e) {
    ElMessage.error('操作失败：' + (e?.message || e))
  }
}

function itemCover(it) {
  return normMedia(it.entity_cover)
}

function moduleLabel(m) {
  const found = MODULES.find((x) => x.key === m)
  return found ? found.label : (m || '')
}

function goSeries() {
  lib.setModule('anime')
  router.push('/series')
}

function openMovie(module, m) {
  router.push(`/movie/${module}/${m.id}`)
}
function playMovie(module, m) {
  router.push(`/mpv/${module}/${m.id}`)
}
function onImgErr(e) {
  e.target.style.visibility = 'hidden'
}

onMounted(() => {
  loadAnime()
  loadMovieGroups()
})

// keep-alive：返回时刷新内嵌系列集数角标（anime）
onActivated(() => {
  if (seriesMovies.value.length && activeSeries.value) {
    enrichStatus(seriesMovies.value, 'anime', 600)
  }
})
</script>

<style scoped>
.block-title {
  display: flex;
  align-items: center;
  font-size: 16px;
  font-weight: 600;
  margin: 8px 0 14px;
  color: var(--text-1);
}
.block-title + .cinema-filters { margin-top: -6px; }
.inline-title { font-size: 20px; color: var(--brand); }

.anime-fav-wall {
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
.asc-cover { position: relative; aspect-ratio: 16 / 9; background: var(--cinema-2); display: flex; align-items: center; justify-content: center; }
.asc-cover img { width: 100%; height: 100%; object-fit: cover; }
.asc-fallback { font-size: 40px; opacity: 0.4; }
.asc-count { position: absolute; bottom: 8px; right: 8px; background: rgba(0,0,0,.65); color: #fff; font-size: 12px; padding: 1px 9px; border-radius: 999px; }
.asc-fav {
  position: absolute; top: 8px; left: 8px; width: 30px; height: 30px; border-radius: 50%;
  border: none; background: rgba(0,0,0,.5); color: #fff; font-size: 15px;
  display: flex; align-items: center; justify-content: center; cursor: pointer; transition: transform .15s;
}
.asc-fav.on { background: rgba(240,180,41,.92); }
.asc-fav:hover { transform: scale(1.12); }
.asc-name { padding: 9px 10px 2px; font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asc-maker { padding: 0 10px; font-size: 12px; color: var(--text-3); }
.asc-latest { padding: 0 10px 2px; font-size: 11px; color: var(--brand-dim); }
.asc-added { padding: 0 10px 10px; font-size: 11px; color: var(--text-3); }

.fav-group { margin-bottom: 18px; }
.fav-group-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.fav-group-name { font-size: 14px; font-weight: 600; color: var(--text-1); }
.fav-group-count { font-size: 12px; color: var(--text-3); }
.fav-group-empty { font-size: 12px; color: var(--text-3); padding: 8px 0; }
.fav-group-items { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
.fav-item { border-radius: 10px; overflow: hidden; background: var(--cinema-1); border: 1px solid var(--cinema-line); }
.fav-item-cover { position: relative; aspect-ratio: 3 / 4; background: var(--cinema-2); display: flex; align-items: center; justify-content: center; }
.fav-item-cover img { width: 100%; height: 100%; object-fit: cover; }
.fav-item-fallback { font-size: 28px; opacity: .4; }
.fav-item-del {
  position: absolute; top: 6px; right: 6px; width: 24px; height: 24px; border-radius: 50%;
  border: none; background: rgba(0,0,0,.55); color: #fff; font-size: 11px;
  cursor: pointer; display: flex; align-items: center; justify-content: center; opacity: 0; transition: opacity .15s, transform .15s;
}
.fav-item:hover .fav-item-del { opacity: 1; }
.fav-item-del:hover { transform: scale(1.1); background: #e05252; }
.fav-item-meta { display: flex; flex-direction: column; gap: 2px; padding: 7px 9px; }
.fav-item-name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-1); }
.fav-item-mod { font-size: 10px; color: var(--text-3); }

.load-bar { display: flex; justify-content: center; padding: 16px 0 8px; }
</style>
