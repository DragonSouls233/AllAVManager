<template>
  <div class="module-movies">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索标题/番号..." clearable style="width: 280px" @keyup.enter="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="store.statusFilter" placeholder="刮削状态" style="width: 130px" @change="onFilterChange">
        <el-option label="全部" value="" />
        <el-option label="待刮削" value="pending" />
        <el-option label="已刮削" value="scraped" />
      </el-select>
      <el-select v-model="store.pageSize" style="width: 80px" @change="onPageSizeChange">
        <el-option :value="12" label="12" />
        <el-option :value="24" label="24" />
        <el-option :value="48" label="48" />
        <el-option :value="96" label="96" />
        <el-option :value="192" label="192" />
      </el-select>
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
      <el-tag v-if="store.total">{{ store.total }} 部</el-tag>
    </div>

    <div class="movies-grid" v-loading="store.loading">
      <div v-for="m in store.movies" :key="m.id" class="movie-card" @click="goDetail(m.id)">
        <div class="cover">
          <img :src="getCoverSrc(m)" :alt="m.title" @error="onCoverError">
          <div class="cover-badge">{{ m.source_platform || 'JAV' }}</div>
          <div class="cover-badges">
            <el-tag v-if="m.is_chinese" size="small" type="danger" effect="dark">中文</el-tag>
            <el-tag v-if="m.is_uncensored" size="small" type="warning" effect="dark">无码</el-tag>
          </div>
          <div class="cover-status">
            <el-tag v-if="m.status === 'scraped'" size="small" type="success">已刮削</el-tag>
            <el-tag v-else size="small" type="warning">待刮削</el-tag>
          </div>
        </div>
        <div class="info">
          <div class="title" :title="m.title">{{ m.title || m.code }}</div>
          <div class="meta">
            <span class="code">{{ m.code }}</span>
            <span v-if="m.studio" class="studio">{{ m.studio }}</span>
          </div>
          <div class="tags">
            <el-tag v-if="m.series" size="small" type="info">{{ m.series }}</el-tag>
            <el-tag v-if="m.release_date" size="small">{{ String(m.release_date).slice(0, 10) }}</el-tag>
          </div>
          <div class="actors" v-if="m.actor">
            <el-tag v-for="a in m.actor.split(',').slice(0, 4)" :key="a" size="small" type="success" class="actor-tag">{{ a.trim() }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!store.loading && !store.movies.length" description="暂无JAV影片" />
    </div>

    <div class="pagination" v-if="store.total > 0">
      <el-pagination
        v-model:current-page="store.page"
        v-model:page-size="store.pageSize"
        :page-sizes="[12, 24, 48, 96, 192]"
        :total="store.total"
        layout="total, sizes, prev, pager, next"
        @current-change="loadMovies"
        @size-change="onPageSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useJavStore } from '@/stores/jav'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getCoverSrc } from '@/utils/media'

const router = useRouter()
const store = useJavStore()
const keyword = ref('')
const scanning = ref(false)

function search() {
  store.page = 1
  loadMovies()
}

function onFilterChange() {
  store.page = 1
  loadMovies()
}

function onPageSizeChange() {
  store.page = 1
  loadMovies()
}

function resetFilters() {
  keyword.value = ''
  store.statusFilter = ''
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
      `确认要对 ${store.pendingCount} 部 JAV 影片启动批量刮削吗？`,
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
    await ElMessageBox.confirm('确认要导入 NFO 文件吗？', '导入 NFO', { confirmButtonText: '开始导入', cancelButtonText: '取消', type: 'info' })
    const res = await store.triggerImportNfo()
    ElMessage.success(res.message || 'NFO 导入已启动')
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('启动失败: ' + (e.message || '未知错误'))
    }
  }
}

function onCoverError(e) {
  e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 150"><rect fill="%23333" width="100" height="150"/><text x="50" y="80" text-anchor="middle" fill="%23666" font-size="12">无封面</text></svg>'
}

onMounted(() => loadMovies())
</script>

<style scoped>
.movies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}

.movie-card {
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  transition: transform .2s, box-shadow .2s;
}

.movie-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}

.cover {
  aspect-ratio: 2/3;
  position: relative;
  background: #f0f0f0;
  overflow: hidden;
}

.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-badge {
  position: absolute;
  top: 4px;
  left: 4px;
  background: rgba(0,0,0,0.5);
  color: #fff;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
}

.cover-badges {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 3px;
}

.cover-status {
  position: absolute;
  bottom: 4px;
  right: 4px;
}

.info {
  padding: 10px 12px;
}

.title {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.code {
  font-size: 12px;
  font-family: monospace;
  color: #409eff;
  font-weight: 600;
}

.studio {
  font-size: 11px;
  color: #909399;
}

.tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.actors {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}

.actor-tag {
  font-size: 11px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}
</style>
