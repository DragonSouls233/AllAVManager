<template>
  <div class="movie-detail" v-loading="loading">
    <div class="detail-header">
      <el-button text @click="goBack">
        <el-icon><ArrowLeft /></el-icon> 返回JAV列表
      </el-button>
      <div class="header-actions">
        <el-button type="primary" @click="play" :disabled="!canPlay">
          <el-icon><VideoPlay /></el-icon> 播放
        </el-button>
        <el-tag v-if="movie && !canPlay" type="danger" size="small">视频文件不存在</el-tag>
      </div>
    </div>

    <div v-if="movie" class="detail-content">
      <div class="cover-section">
        <img :src="coverSrc" :alt="movie.title" @error="onCoverError">
      </div>
      <div class="info-section">
        <h1>{{ movie.title || movie.code }}</h1>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="番号">{{ movie.code }}</el-descriptions-item>
          <el-descriptions-item label="来源平台">{{ movie.source_platform || movie.source || '-' }}</el-descriptions-item>
          <el-descriptions-item label="演员">{{ movie.actor || '-' }}</el-descriptions-item>
          <el-descriptions-item label="制作商">{{ movie.studio || '-' }}</el-descriptions-item>
          <el-descriptions-item label="系列">{{ movie.series || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ movie.duration ? movie.duration + '分钟' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ movie.rating ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusMap[movie.status] || movie.status }}</el-descriptions-item>
          <el-descriptions-item label="发布日期">{{ movie.release_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="文件路径">{{ movie.file_path || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="desc" v-if="movie.plot">
          <h3>简介</h3>
          <p>{{ movie.plot }}</p>
        </div>
        <div class="tags-section" v-if="movie.tag || movie.genre">
          <el-tag v-if="movie.tag" type="warning">{{ movie.tag }}</el-tag>
          <el-tag v-if="movie.genre" type="info">{{ movie.genre }}</el-tag>
        </div>

        <!-- 操作工具栏 -->
        <div class="action-bar">
          <el-button size="small" type="warning" :loading="scraping" @click="startScrape">
            <el-icon><Refresh /></el-icon> 刮削补充
          </el-button>
          <el-button size="small" type="info" @click="startNfoReload">
            <el-icon><Document /></el-icon> 从 NFO 重新导入
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useJavStore } from '@/stores/jav'
import { scrapeJavMovie, importJavNfo } from '@/api/jav'
import { getCoverSrc } from '@/utils/media'
import { ElMessage } from 'element-plus'
import { VideoPlay, Refresh, Document } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const store = useJavStore()
const movie = ref(null)
const loading = ref(true)
const scraping = ref(false)

const statusMap = { pending: '待刮削', scraped: '已刮削', failed: '失败' }

const coverSrc = computed(() => getCoverSrc(movie.value))

const canPlay = computed(() => {
  return movie.value && movie.value.file_path
})

function goBack() {
  router.push('/jav')
}

function play() {
  if (!canPlay.value) {
    ElMessage.warning('该影片没有关联视频文件')
    return
  }
  router.push({ path: `/play/${route.params.id}`, query: { module: 'jav' } })
}

function onCoverError(e) {
  e.target.src = `data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='450' viewBox='0 0 320 450'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop stop-color='%23111827'/%3E%3Cstop offset='1' stop-color='%23374151'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='320' height='450' fill='url(%23g)'/%3E%3C/svg%3E`
}

async function startScrape() {
  const id = route.params.id
  scraping.value = true
  try {
    const res = await scrapeJavMovie(id)
    ElMessage.success(res.message || '刮削完成')
    movie.value = await store.loadMovieDetail(id)
  } catch (e) {
    ElMessage.error('刮削失败: ' + (e.message || '未知错误'))
  } finally {
    scraping.value = false
  }
}

async function startNfoReload() {
  ElMessage.info('NFO 重新导入功能正在启动...')
  try {
    const res = await importJavNfo()
    ElMessage.success(res.message || 'NFO 导入已启动')
  } catch (e) {
    ElMessage.error('NFO 导入失败: ' + (e.message || '未知错误'))
  }
}

onMounted(async () => {
  try {
    movie.value = await store.loadMovieDetail(route.params.id)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.movie-detail { padding: 20px; }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.detail-content { display: flex; gap: 24px; }
.cover-section { flex-shrink: 0; width: 350px; }
.cover-section img { width: 100%; border-radius: 8px; }
.info-section { flex: 1; }
.info-section h1 { font-size: 18px; margin-bottom: 16px; }
.desc { margin-top: 16px; }
.desc h3 { font-size: 14px; margin-bottom: 8px; }
.desc p { line-height: 1.6; color: #666; font-size: 13px; }
.tags-section { margin-top: 12px; display: flex; gap: 6px; flex-wrap: wrap; }
.action-bar { margin-top: 20px; display: flex; gap: 8px; }
</style>
