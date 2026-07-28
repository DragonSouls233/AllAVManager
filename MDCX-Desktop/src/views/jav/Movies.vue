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
      <el-button type="warning" @click="startScrapeAll" :loading="store.scraping" :disabled="store.pendingCount === 0">
        <el-icon><Monitor /></el-icon> 批量刮削
        <el-tag v-if="store.pendingCount" size="small" type="danger" style="margin-left:4px">{{ store.pendingCount }}</el-tag>
      </el-button>
      <el-button type="info" @click="startImportNfo" :loading="store.scraping">
        <el-icon><Document /></el-icon> 导入 NFO
      </el-button>
      <el-tag v-if="store.total">共 {{ store.total }} 部</el-tag>
    </div>

    <div class="movies-grid" v-loading="store.loading">
      <div v-for="m in store.movies" :key="m.id" class="movie-card" @click="goDetail(m.id)">
        <div class="cover">
          <img :src="getCoverSrc(m)" :alt="m.title" @error="onCoverError">
          <div class="cover-badge">{{ m.source_platform || 'JAV' }}</div>
          <div class="cover-status" v-if="m.status === 'scraped'">
            <el-tag size="small" type="success">已刮削</el-tag>
          </div>
          <div class="cover-status" v-else>
            <el-tag size="small" type="warning">待刮削</el-tag>
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
      <el-empty v-if="!store.loading && !store.movies.length" description="暂无JAV影片，请先扫描目录" />
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
import { useJavStore } from '@/stores/jav'
import { ElMessage, ElMessageBox } from 'element-plus'
import defaultCover from '@/assets/default-cover.png'
import { getCoverSrc } from '@/utils/media'

const router = useRouter()
const store = useJavStore()
const keyword = ref('')
const scanning = ref(false)

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
  router.push(`/jav/movies/${id}`)
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

async function startScrapeAll() {
  if (store.pendingCount === 0) {
    ElMessage.info('没有待刮削的影片')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认要对 ${store.pendingCount} 部 JAV 影片启动批量刮削吗？\n刮削过程将在后台进行，可能需要较长时间。`,
      '批量刮削',
      { confirmButtonText: '开始刮削', cancelButtonText: '取消', type: 'warning' }
    )
    const res = await store.triggerScrapeAll()
    ElMessage.success(res.message || '批量刮削已启动')
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('启动失败: ' + (e.message || '未知错误'))
    }
  }
}

async function startImportNfo() {
  try {
    await ElMessageBox.confirm(
      '将从 JAV 媒体目录扫描所有 .nfo 文件并导入元数据。\n已有元数据的影片不会被覆盖。\n确认继续？',
      '导入 NFO',
      { confirmButtonText: '开始导入', cancelButtonText: '取消', type: 'info' }
    )
    const res = await store.triggerImportNfo()
    ElMessage.success(res.message || 'NFO 导入已启动')
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('导入失败: ' + (e.message || '未知错误'))
    }
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
.cover-status { position: absolute; bottom: 6px; left: 6px; }
.cover-status .el-tag { font-size: 10px; padding: 0 4px; height: 18px; line-height: 18px; }
.info { padding: 8px; }
.title { font-size: 13px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { display: flex; gap: 4px; align-items: center; margin-top: 4px; }
.code { font-size: 11px; color: #999; }
.actors { margin-top: 4px; display: flex; gap: 2px; flex-wrap: wrap; }
.pagination { margin-top: 20px; display: flex; justify-content: center; }
</style>
