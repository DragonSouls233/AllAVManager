<template>
  <div class="chinese-movies">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索标题/演员..." clearable style="width: 280px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="success" @click="openScanDialog">
        <el-icon><FolderOpened /></el-icon> 扫描目录
      </el-button>
      <el-tag v-if="store.total">共 {{ store.total }} 部</el-tag>
    </div>

    <div class="movies-grid" v-loading="store.loading">
      <div v-for="m in store.movies" :key="m.id" class="movie-card" @click="goDetail(m.id)">
        <div class="cover">
          <img :src="getCoverSrc(m)" :alt="m.title" @error="onCoverError">
          <div class="cover-badge">{{ m.studio || '国产' }}</div>
        </div>
        <div class="info">
          <div class="title">{{ m.title || m.code }}</div>
          <div class="meta">
            <span class="code">{{ m.code }}</span>
            <el-tag v-if="m.folder_name" size="small" type="warning">{{ m.folder_name }}</el-tag>
          </div>
          <div class="actors" v-if="m.folder_based_actors">
            <el-tag size="mini" v-for="a in parseActors(m.folder_based_actors)" :key="a" type="success">{{ a }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!store.loading && !store.movies.length" description="暂无国产视频，请先扫描目录" />
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

    <el-dialog v-model="scanDialog" title="扫描国产目录" width="400px">
      <p>将从配置的媒体目录中扫描国产视频文件，识别文件夹名作为演员。</p>
      <template #footer>
        <el-button @click="scanDialog = false">取消</el-button>
        <el-button type="primary" :loading="scanning" @click="startScan">开始扫描</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChineseStore } from '@/stores/chinese'
import defaultCover from '@/assets/default-cover.png'
import { getCoverSrc } from '@/utils/media'

const router = useRouter()
const store = useChineseStore()
const keyword = ref('')
const scanDialog = ref(false)
const scanning = ref(false)

function parseActors(val) {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [val] }
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
  router.push(`/chinese/movies/${id}`)
}

function openScanDialog() {
  scanDialog.value = true
}

async function startScan() {
  scanning.value = true
  try {
    await store.syncActors()
    await loadMovies()
  } finally {
    scanning.value = false
    scanDialog.value = false
  }
}

function onCoverError(e) {
  e.target.src = defaultCover
}

onMounted(loadMovies)
</script>

<style scoped>
.chinese-movies { padding: 20px; }
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
.actors { margin-top: 4px; display: flex; gap: 2px; flex-wrap: wrap; }
.pagination { margin-top: 20px; display: flex; justify-content: center; }
</style>
