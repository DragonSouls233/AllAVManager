<template>
  <div class="category-page">
    <!-- 顶部导航 -->
    <div class="top-bar">
      <el-button text @click="goBack">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
      <el-breadcrumb separator="/" class="breadcrumb">
        <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
        <el-breadcrumb-item>{{ moduleLabel }}</el-breadcrumb-item>
        <el-breadcrumb-item v-if="!isListView">分类: {{ currentGenre }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <!-- 模块标题 -->
    <div class="module-header">
      <h2 class="page-title">
        <el-icon><Grid /></el-icon>
        {{ moduleLabel }} · 类别
        <span v-if="categorySummary" class="stat-badge">
          共 {{ categorySummary.total_categories }} 个类别 / 涵盖 {{ categorySummary.total_movies }} 部影片
        </span>
      </h2>
    </div>

    <!-- ========== 列表视图（默认）============ -->
    <template v-if="isListView">
      <!-- 搜索 + 排序 -->
      <el-card shadow="never" class="toolbar-card">
        <div class="toolbar">
          <el-input
            v-model="keyword"
            placeholder="搜索类别，如「巨乳」「人妻」「学生」..."
            clearable
            style="width: 320px"
            @input="onKeywordChange"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-radio-group v-model="sortMode" size="small" @change="applyLocalSort">
            <el-radio-button value="count_desc">按影片数</el-radio-button>
            <el-radio-button value="name_asc">按字母/中文笔画</el-radio-button>
          </el-radio-group>
          <div class="toolbar-right">
            <el-button text :icon="Refresh" @click="loadCategories">刷新</el-button>
          </div>
        </div>
      </el-card>

      <!-- 类别网格：参考 DMMbus 多列文字密集布局 -->
      <el-card v-loading="loading" shadow="never" class="grid-card">
        <div v-if="filteredCategories.length === 0 && !loading" class="empty-state">
          <el-empty :description="categorySummary?.total_categories === 0
            ? `${moduleLabel} 模块暂无类别数据`
            : `没有匹配「${keyword}」的类别`" />
        </div>
        <div v-else class="category-grid">
          <a
            v-for="cat in filteredCategories"
            :key="cat.name"
            class="category-tag"
            @click="enterCategory(cat.name)"
          >
            <span class="cat-name">{{ cat.name }}</span>
            <span class="cat-count">{{ cat.count }}</span>
          </a>
        </div>
      </el-card>
    </template>

    <!-- ========== 类别详情视图：显示该类别的作品 ========== -->
    <template v-else>
      <!-- 类别头部 -->
      <el-card shadow="never" class="category-header-card">
        <div class="category-header">
          <div>
            <span class="selected-genre">{{ currentGenre }}</span>
            <el-tag type="info" effect="plain" size="large" style="margin-left: 12px">
              {{ categoryMoviesTotal }} 部
            </el-tag>
          </div>
          <el-button type="primary" plain @click="goBack">
            <el-icon><Grid /></el-icon> 返回全部类别
          </el-button>
        </div>
      </el-card>

      <!-- 作品网格（复用 MovieCard） -->
      <el-card v-loading="loadingMovies" shadow="never" class="movies-card">
        <div v-if="movies.length === 0 && !loadingMovies" class="empty-state">
          <el-empty :description="`「${currentGenre}」类别暂无作品`" />
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

        <!-- 分页 -->
        <div v-if="categoryMoviesTotal > pageSize" class="pager">
          <el-pagination
            v-model:current-page="page"
            :total="categoryMoviesTotal"
            :page-size="pageSize"
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
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Search, Refresh, Grid } from '@element-plus/icons-vue'
import MovieCard from '@/components/MovieCard.vue'
import { getModuleCategories, getMoviesByCategory } from '@/api'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const uiStore = useUiStore()

// ---------- 模块识别 ----------
// 支持两种进入方式：
// 1. /jav/categories、/uncensored/categories —— 从 path 第二段取模块
// 2. 通用 /movie 或其它 —— 从 query.module 兜底，找不到默认 jav
const KNOWN_MODULES = ['jav', 'uncensored', 'fc2', 'chinese', 'pornhub', 'western', 'anime']
const moduleName = computed(() => {
  const segs = route.path.split('/').filter(Boolean)
  // path 形如 /jav/categories → segs[0]=jav
  if (segs.length && KNOWN_MODULES.includes(segs[0])) return segs[0]
  // 通用路由（如 /movie）→ 从 query 拿
  const m = String(route.query.module || '')
  if (KNOWN_MODULES.includes(m)) return m
  return 'jav'  // 默认 jav
})
const moduleLabel = computed(() => {
  const labels = { jav: 'JAV 有码', uncensored: 'JAV 无码', fc2: 'FC2', chinese: '国产', pornhub: 'PORNHub', western: '欧美', anime: '里番' }
  return labels[moduleName.value] || 'JAV 有码'
})

// ---------- 视图模式 ----------
const isListView = computed(() => !route.query.name)
const currentGenre = computed(() => String(route.query.name || ''))

// ---------- 类别列表 ----------
const allCategories = ref([])        // 原始：按 count desc 排序
const categorySummary = ref(null)
const keyword = ref('')
const sortMode = ref('count_desc')
const loading = ref(false)

const filteredCategories = computed(() => {
  let list = allCategories.value
  if (keyword.value.trim()) {
    const q = keyword.value.toLowerCase().trim()
    list = list.filter(c => c.name.toLowerCase().includes(q))
  }
  if (sortMode.value === 'name_asc') {
    // 中文按 localeCompare 自然序（含中文笔画）；英文按字母
    return [...list].sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'))
  }
  return list  // 默认 count desc
})

const loadCategories = async () => {
  loading.value = true
  try {
    const res = await getModuleCategories(moduleName.value, { limit: 1000 })
    allCategories.value = res.items || []
    categorySummary.value = {
      total_categories: res.total_categories,
      total_movies: res.total_movies,
    }
  } catch (e) {
    console.error(e)
    ElMessage.error('加载类别失败：' + (e?.response?.data?.detail || e.message))
    allCategories.value = []
    categorySummary.value = null
  } finally {
    loading.value = false
  }
}

const onKeywordChange = () => { /* filteredCategories 自动响应 */ }
const applyLocalSort = () => { /* filteredCategories 自动响应 */ }

// 进入某个类别 → 切到详情视图（保留 module 等已有 query）
const enterCategory = (name) => {
  router.push({ path: route.path, query: { ...route.query, name } })
}

// 返回全部类别视图
const goBack = () => {
  if (isListView.value) {
    router.push({ path: `/${moduleName.value}/movies` })
  } else {
    // 从类别详情返回类别列表，保留 module
    router.push({ path: route.path, query: { module: moduleName.value } })
  }
}

// ---------- 类别作品 ----------
const movies = ref([])
const loadingMovies = ref(false)
const categoryMoviesTotal = ref(0)
const page = ref(1)
const pageSize = ref(24)
const viewMode = computed(() => uiStore.viewMode)
const imageMode = computed(() => uiStore.imageMode)

const loadMovies = async () => {
  if (!currentGenre.value) return
  loadingMovies.value = true
  try {
    const res = await getMoviesByCategory(moduleName.value, currentGenre.value, {
      page: page.value,
      page_size: pageSize.value,
    })
    movies.value = res.items || []
    categoryMoviesTotal.value = res.total || 0
  } catch (e) {
    console.error(e)
    ElMessage.error('加载作品失败：' + (e?.response?.data?.detail || e.message))
    movies.value = []
    categoryMoviesTotal.value = 0
  } finally {
    loadingMovies.value = false
  }
}

// 详情跳转（统一走通用路由 /movie/:id）
const goDetail = (id) => router.push(`/movie/${id}`)

// ---------- 监听 ----------
// 切换 query.name 时重新加载
watch(() => route.query.name, (newName) => {
  if (newName) {
    page.value = 1
    loadMovies()
  }
})
// 切换 module 时重新加载
watch(moduleName, () => {
  if (isListView.value) loadCategories()
  else loadMovies()
})

onMounted(() => {
  if (isListView.value) loadCategories()
  else loadMovies()
})
</script>

<style scoped>
.category-page { max-width: 1600px; margin: 0 auto; padding: 16px 24px 32px; }

.top-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}
.breadcrumb { font-size: 13px; }

.module-header { margin-bottom: 16px; }
.page-title {
  font-size: 22px;
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.stat-badge {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
  margin-left: 12px;
}

.toolbar-card { margin-bottom: 16px; }
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar-right { margin-left: auto; }

.grid-card { min-height: 400px; }

.category-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px 12px;
  padding: 8px 4px;
}
@media (max-width: 1280px) { .category-grid { grid-template-columns: repeat(5, 1fr); } }
@media (max-width: 960px)  { .category-grid { grid-template-columns: repeat(4, 1fr); } }
@media (max-width: 720px)  { .category-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 480px)  { .category-grid { grid-template-columns: repeat(2, 1fr); } }

.category-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 4px;
  background: #fafafa;
  border: 1px solid #ebeef5;
  color: #303133;
  cursor: pointer;
  transition: all 0.12s ease;
  text-decoration: none;
  user-select: none;
}
.category-tag:hover {
  background: #fef0f0;
  border-color: #f56c6c;
  color: #f56c6c;
}
.category-tag:hover .cat-count { color: #f56c6c; }
.cat-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70%;
}
.cat-count {
  font-size: 11px;
  color: #909399;
  background: #fff;
  padding: 1px 6px;
  border-radius: 10px;
  min-width: 26px;
  text-align: center;
}

.empty-state { padding: 60px 0; }

.category-header-card { margin-bottom: 16px; }
.category-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.selected-genre {
  font-size: 24px;
  font-weight: 700;
  background: linear-gradient(135deg, #f56c6c, #f89898);
  color: #fff;
  padding: 6px 16px;
  border-radius: 4px;
  display: inline-block;
  letter-spacing: 1px;
}

.movies-card { margin-bottom: 16px; }
.movies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
  padding: 8px 0;
}
.pager {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}
</style>
