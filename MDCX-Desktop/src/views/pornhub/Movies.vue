<template>
  <div class="module-movies">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索标题/viewkey..." clearable style="width: 280px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="success" @click="startScan" :loading="scanning">
        <el-icon><FolderOpened /></el-icon> 扫描目录
      </el-button>
      <el-tag v-if="store.total">共 {{ store.total }} 部</el-tag>
    </div>

    <div class="movies-grid" v-loading="store.loading">
      <div v-for="m in store.movies" :key="m.id" class="movie-card" @click="goDetail(m.id)">
        <div class="cover">
          <img :src="getCoverSrc(m)" :alt="m.title" @error="onCoverError">
          <div class="cover-badge">{{ m.uploader || 'PH' }}</div>
        </div>
        <div class="info">
          <div class="title">{{ m.title || m.code }}</div>
          <div class="meta">
            <span class="code">{{ m.code }}</span>
            <span v-if="m.source_views" class="views">{{ formatNumber(m.source_views) }} 次播放</span>
          </div>
          <div class="categories" v-if="m.categories">
            <el-tag size="mini" v-for="c in parseCategories(m.categories)" :key="c" type="info">{{ c }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!store.loading && !store.movies.length" description="暂无 PORNHub 影片，请先扫描目录" />
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePornhubStore } from '@/stores/pornhub'
import { ElMessage } from 'element-plus'
import defaultCover from '@/assets/default-cover.png'
import { getCoverSrc } from '@/utils/media'

const router = useRouter()
const store = usePornhubStore()
const keyword = ref('')
const scanning = ref(false)

function parseCategories(val) {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [val] }
}

function formatNumber(n) {
  if (!n) return '0'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

function search() {
  store.page = 1
  loadMovies()
}

function resetFilters() {
  keyword.value = ''
  store.page = 1
  loadMovies()
}

async function loadMovies() {
  await store.loadMovies({ keyword: keyword.value || undefined })
}

function goDetail(id) {
  router.push(`/pornhub/movies/${id}`)
}

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
.info { padding: 8px; }
.title { font-size: 13px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { display: flex; gap: 4px; align-items: center; margin-top: 4px; }
.code { font-size: 11px; color: #999; }
.views { font-size: 10px; color: #409eff; }
.categories { margin-top: 4px; display: flex; gap: 2px; flex-wrap: wrap; }
.pagination { margin-top: 20px; display: flex; justify-content: center; }
</style>
