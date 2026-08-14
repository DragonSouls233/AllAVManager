<template>
  <div class="module-movies">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索标题/番号..." clearable style="width: 280px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="success" @click="startScan" :loading="scanning">
        <el-icon><FolderOpened /></el-icon> 扫描目录
      </el-button>
      <el-tag v-if="store.total">共 {{ store.total }} 部</el-tag>
      <!-- 详情页跳转筛选状态 -->
      <el-tag v-if="route.query.series" type="success" closable @close="clearRouteFilter('series')">系列：{{ route.query.series }}</el-tag>
      <el-tag v-if="route.query.maker" type="warning" closable @close="clearRouteFilter('maker')">片商：{{ route.query.maker }}</el-tag>
      <el-tag v-if="route.query.genre" type="danger" closable @close="clearRouteFilter('genre')">类别：{{ route.query.genre }}</el-tag>
      <el-tag v-if="route.query.code_prefix" type="info" closable @close="clearRouteFilter('code_prefix')">番号：{{ route.query.code_prefix }}</el-tag>
    </div>

    <div class="movies-grid" v-loading="store.loading">
      <div v-for="m in store.movies" :key="m.id" class="movie-card" @click="goDetail(m.id)">
        <div class="cover">
          <img :src="getCoverSrc(m)" :alt="m.title" @error="onCoverError">
          <div class="cover-badge">{{ m.source_platform || '无码' }}</div>
          <div class="cover-badges">
            <el-tag v-for="b in getMovieVersionBadges(m)" :key="b.text" size="small" :type="versionBadgeType(b.type)" effect="dark">{{ b.text }}</el-tag>
          </div>
        </div>
        <div class="info">
          <div class="title">{{ m.title || m.code }}</div>
          <div class="meta">
            <span class="code">{{ m.code }}</span>
            <el-tag v-if="m.series" size="small" type="info">{{ m.series }}</el-tag>
          </div>
          <div class="actors" v-if="m.actor">
            <el-tag size="mini" type="success">{{ m.actor }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!store.loading && !store.movies.length" description="暂无无码影片，请先扫描目录" />
    </div>

    <div class="pagination" v-if="store.total > 0">
      <el-pagination
        v-model:current-page="store.page"
        :page-size="store.pageSize"
        :total="store.total"
        layout="total, prev, pager, next"
        @current-change="loadMovies"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUncensoredStore } from '@/stores/uncensored'
import { ElMessage } from 'element-plus'
import defaultCover from '@/assets/default-cover.png'
import { getCoverSrc, getMovieVersionBadges, versionBadgeType } from '@/utils/media'

const router = useRouter()
const route = useRoute()
const store = useUncensoredStore()
const keyword = ref('')
const scanning = ref(false)

// 2026-08-08: 详情页跳转筛选（系列/片商/类别/番号前缀）
function routeFilterParams() {
  const q = route.query
  const p = {}
  if (q.series) p.series = String(q.series)
  if (q.maker) p.maker = String(q.maker)
  if (q.genre) p.genre = String(q.genre)
  if (q.code_prefix) p.code_prefix = String(q.code_prefix)
  return p
}

function clearRouteFilter(key) {
  const q = { ...route.query }
  delete q[key]
  router.replace({ path: route.path, query: q })
}

function search() {
  store.page = 1
  loadMovies()
}

function resetFilters() {
  keyword.value = ''
  store.page = 1
  router.replace({ path: route.path, query: {} })
  loadMovies()
}

async function loadMovies() {
  await store.loadMovies({ keyword: keyword.value || undefined, ...routeFilterParams() })
}

function goDetail(id) {
  router.push(`/uncensored/movies/${id}`)
}

// 路由 query 变化时重新加载
watch(() => route.query, () => { store.page = 1; loadMovies() }, { deep: true })

async function startScan() {
  scanning.value = true
  try {
    await store.triggerScan()
    await loadMovies()
    ElMessage.success('扫描完成')
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.message || '未知错误'))
  } finally {
    scanning.value = false
  }
}

function onCoverError(e) {
  e.target.src = defaultCover
}

onMounted(loadMovies)
</script>

<style scoped>
.module-movies { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
.movies-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.movie-card { cursor: pointer; border: 1px solid #ebeef5; border-radius: 8px; overflow: hidden; transition: all 0.2s; }
.movie-card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.1); }
.cover { position: relative; aspect-ratio: 3/4; overflow: hidden; }
.cover img { width: 100%; height: 100%; object-fit: cover; }
.cover-badge { position: absolute; top: 6px; left: 6px; background: rgba(0,0,0,0.6); color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.cover-badges { position: absolute; top: 6px; right: 6px; display: flex; flex-direction: column; gap: 4px; align-items: flex-end; }
.info { padding: 8px; }
.title { font-size: 13px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { display: flex; gap: 4px; align-items: center; margin-top: 4px; }
.code { font-size: 11px; color: #999; }
.actors { margin-top: 4px; display: flex; gap: 2px; flex-wrap: wrap; }
.pagination { margin-top: 20px; display: flex; justify-content: center; }
</style>
