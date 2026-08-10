<template>
  <div class="jav-series-page">
    <!-- 顶部导航 -->
    <div class="top-bar">
      <el-button text @click="goBack">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
      <el-breadcrumb separator="/" class="breadcrumb">
        <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
        <el-breadcrumb-item>JAV 有码</el-breadcrumb-item>
        <el-breadcrumb-item v-if="!selected">系列</el-breadcrumb-item>
        <el-breadcrumb-item v-else>{{ selected.name }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <!-- 列表视图 -->
    <template v-if="!selected">
      <div class="module-header">
        <h2 class="page-title">
          <el-icon><Collection /></el-icon>
          JAV 有码 · 系列
          <span v-if="summary" class="stat-badge">
            共 {{ summary.total }} 个系列（{{ summary.totalMovies }} 部影片）
          </span>
        </h2>
      </div>

      <el-card shadow="never" class="toolbar-card">
        <div class="toolbar">
          <el-input
            v-model="keyword"
            placeholder="搜索系列名，如「初撮り」「マジ軟派」..."
            clearable
            style="width: 320px"
            @input="onSearch"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-radio-group v-model="sortMode" size="small" @change="applyLocalSort">
            <el-radio-button value="count_desc">按影片数</el-radio-button>
            <el-radio-button value="name_asc">按名称</el-radio-button>
          </el-radio-group>
          <el-button text :icon="Refresh" @click="load">刷新</el-button>
        </div>
      </el-card>

      <el-card v-loading="loading" shadow="never" class="grid-card">
        <div v-if="seriesList.length === 0 && !loading" class="empty-state">
          <el-empty description="暂无系列数据，请先刮削 JAV 有码影片" />
        </div>
        <div v-else class="series-grid">
          <div
            v-for="s in seriesList"
            :key="s.name"
            class="series-card"
            @click="openSeries(s)"
          >
            <div class="s-cover">
              <span class="s-count">{{ s.movie_count }} 部</span>
            </div>
            <div class="s-name" :title="s.name">{{ s.name }}</div>
          </div>
        </div>

        <div v-if="totalPages > 1" class="pager">
          <el-pagination
            v-model:current-page="page"
            :total="total"
            :page-size="pageSize"
            :pager-count="5"
            background
            layout="prev, pager, next, jumper, total"
            @current-change="load"
          />
        </div>
      </el-card>
    </template>

    <!-- 系列详情视图：作品网格 -->
    <template v-else>
      <el-card shadow="never" class="category-header-card">
        <div class="category-header">
          <div>
            <span class="selected-genre">{{ selected.name }}</span>
            <el-tag type="info" effect="plain" size="large" style="margin-left: 12px">
              {{ movieTotal }} 部
            </el-tag>
          </div>
          <el-button type="primary" plain @click="back">
            <el-icon><Collection /></el-icon> 返回全部系列
          </el-button>
        </div>
      </el-card>

      <el-card v-loading="loadingMovies" shadow="never" class="movies-card">
        <div v-if="movies.length === 0 && !loadingMovies" class="empty-state">
          <el-empty :description="`「${selected.name}」系列暂无作品`" />
        </div>
        <div v-else class="movies-grid">
          <MovieCard
            v-for="m in movies"
            :key="m.id"
            :movie="m"
            :view-mode="viewMode"
            :image-mode="imageMode"
            @click="goDetail"
          />
        </div>

        <div v-if="movieTotal > moviePageSize" class="pager">
          <el-pagination
            v-model:current-page="moviePage"
            :total="movieTotal"
            :page-size="moviePageSize"
            :pager-count="5"
            background
            layout="prev, pager, next, jumper, total"
            @current-change="loadMovies"
          />
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Search, Refresh, Collection } from '@element-plus/icons-vue'
import MovieCard from '@/components/MovieCard.vue'
import { getJavSeries, getJavSeriesMovies } from '@/api'

const router = useRouter()

const keyword = ref('')
const sortMode = ref('count_desc')
const page = ref(1)
const pageSize = ref(60)
const total = ref(0)
const seriesList = ref([])
const loading = ref(false)
const summary = ref(null)

// 详情视图
const selected = ref(null)
const movies = ref([])
const movieTotal = ref(0)
const moviePage = ref(1)
const moviePageSize = ref(24)
const loadingMovies = ref(false)
const viewMode = ref('standard')
const imageMode = ref('poster')

const totalPages = computed(() => Math.ceil(total.value / pageSize.value))

let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 350)
}

function applyLocalSort() {
  // 后端已按 count desc / name asc 排序；前端仅在已有结果上快速重排
  const list = seriesList.value.slice()
  if (sortMode.value === 'name_asc') {
    list.sort((a, b) => a.name.localeCompare(b.name, 'ja'))
  } else {
    list.sort((a, b) => b.movie_count - a.movie_count || a.name.localeCompare(b.name, 'ja'))
  }
  seriesList.value = list
}

async function load() {
  loading.value = true
  try {
    const res = await getJavSeries({
      min_count: 2,
      page: page.value,
      page_size: pageSize.value,
      search: keyword.value || undefined,
    })
    const items = res.items || []
    seriesList.value = items
    total.value = res.total || items.length
    summary.value = {
      total: res.total || items.length,
      totalMovies: res.total_movies || 0,
    }
    applyLocalSort()
  } catch (e) {
    ElMessage.error('加载系列失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function openSeries(s) {
  selected.value = s
  moviePage.value = 1
  window.scrollTo({ top: 0, behavior: 'smooth' })
  await loadMovies()
}

async function loadMovies() {
  if (!selected.value) return
  loadingMovies.value = true
  try {
    const res = await getJavSeriesMovies(selected.value.name, {
      page: moviePage.value,
      page_size: moviePageSize.value,
    })
    movies.value = res.items || []
    movieTotal.value = res.total || movies.value.length
  } catch (e) {
    ElMessage.error('加载作品失败：' + (e?.message || e))
  } finally {
    loadingMovies.value = false
  }
}

function back() {
  selected.value = null
  movies.value = []
  movieTotal.value = 0
}

function goDetail(id) {
  router.push(`/movie/${id}`)
}

function goBack() {
  if (selected.value) {
    back()
  } else {
    router.push('/jav/movies')
  }
}

onMounted(() => load())
</script>

<style scoped>
.jav-series-page { padding: 20px 24px; }
.top-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.breadcrumb { font-size: 13px; }
.module-header { margin-bottom: 16px; }
.page-title { margin: 0; font-size: 22px; display: flex; align-items: center; gap: 8px; }
.stat-badge {
  font-size: 13px; font-weight: normal; color: var(--el-text-color-secondary);
  background: var(--el-bg-color-overlay); padding: 2px 10px; border-radius: 12px;
}
.toolbar-card { margin-bottom: 16px; }
.toolbar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.toolbar-right { margin-left: auto; }
.grid-card { min-height: 200px; }
.series-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
.series-card {
  cursor: pointer; border-radius: 12px; overflow: hidden;
  background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color-light);
  transition: transform .2s, box-shadow .2s;
}
.series-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,.18); }
.s-cover {
  position: relative; aspect-ratio: 16/9;
  background: linear-gradient(135deg, #3a2b5e 0%, #1a1a2e 100%);
  display: flex; align-items: center; justify-content: center;
}
.s-count {
  background: rgba(0,0,0,.55); color: #fff; font-size: 13px;
  padding: 3px 10px; border-radius: 12px;
}
.s-name { padding: 10px 12px; font-size: 14px; font-weight: 600; line-height: 1.4; min-height: 2.8em; }
.category-header-card { margin-bottom: 16px; }
.category-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.selected-genre { font-size: 18px; font-weight: 700; }
.movies-card { min-height: 200px; }
.movies-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px; }
.pager { display: flex; justify-content: center; margin-top: 18px; }
.empty-state { padding: 40px 0; }
</style>
