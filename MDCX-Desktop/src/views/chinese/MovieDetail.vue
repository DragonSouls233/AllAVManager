<template>
  <div class="movie-detail" v-loading="loading">
    <div class="detail-header">
      <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon> 返回国产列表</el-button>
      <div class="header-actions">
        <el-button type="primary" @click="play" :disabled="!canPlay">
          <el-icon><VideoPlay /></el-icon> 播放
        </el-button>
        <el-tag v-if="movie && !canPlay" type="danger" size="small">视频文件不存在</el-tag>
      </div>
    </div>
    <div v-if="movie" class="detail-content">
      <div class="cover-section"><img :src="coverSrc" :alt="movie.title" @error="onCoverError"></div>
      <div class="info-section">
        <h1>{{ movie.title || movie.code }}</h1>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="番号">{{ movie.code }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ movie.source || '-' }}</el-descriptions-item>
          <el-descriptions-item label="演员">{{ movie.actor || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ movie.duration ? movie.duration + '分钟' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ movie.rating ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ movie.status }}</el-descriptions-item>
          <el-descriptions-item label="文件路径" :span="2">{{ movie.file_path || '-' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="movie.plot" class="desc"><h3>简介</h3><p>{{ movie.plot }}</p></div>
        <div v-if="movie.genre" class="tags-section"><el-tag type="info">{{ movie.genre }}</el-tag></div>
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
import { getChineseMovie, scrapeChineseMovie, reloadChineseMovieNfo } from '@/api/chinese'
import { getCoverSrc } from '@/utils/media'
import { ElMessage } from 'element-plus'
import { VideoPlay, Refresh, Document } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const movie = ref(null)
const loading = ref(true)
const scraping = ref(false)
const coverSrc = computed(() => getCoverSrc(movie.value))
const canPlay = computed(() => movie.value && movie.value.file_path)

function goBack() { router.push('/chinese') }
function play() {
  if (!canPlay.value) { ElMessage.warning('该影片没有关联视频文件'); return }
  router.push({ path: `/play/${route.params.id}`, query: { module: 'chinese' } })
}
function onCoverError(e) {
  e.target.src = 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="320" height="450"%3E%3Crect width="320" height="450" fill="%23111827"/%3E%3C/svg%3E'
}
async function startScrape() {
  scraping.value = true
  try {
    const res = await scrapeChineseMovie(route.params.id)
    ElMessage.success(res.message || '刮削完成')
    movie.value = await getChineseMovie(route.params.id)
  } catch (e) { ElMessage.error('刮削失败: ' + (e.message || '未知错误'))
  } finally { scraping.value = false }
}
async function startNfoReload() {
  try {
    const res = await reloadChineseMovieNfo(route.params.id)
    ElMessage.success(res.message || 'NFO 重载完成')
  } catch (e) { ElMessage.error('NFO 重载失败: ' + (e.message || '未知错误')) }
}
onMounted(async () => {
  try { movie.value = await getChineseMovie(route.params.id) }
  finally { loading.value = false }
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
