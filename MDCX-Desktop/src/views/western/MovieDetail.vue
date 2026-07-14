<template>
  <div class="movie-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回欧美列表
    </el-button>

    <div v-if="movie" class="detail-content">
      <div class="cover-section">
        <img :src="movie.cover_url || defaultCover" :alt="movie.title">
      </div>
      <div class="info-section">
        <h1>{{ movie.title || movie.code }}</h1>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="编号">{{ movie.code }}</el-descriptions-item>
          <el-descriptions-item label="原标题">{{ movie.original_title || '-' }}</el-descriptions-item>
          <el-descriptions-item label="品牌">{{ movie.site || '-' }}</el-descriptions-item>
          <el-descriptions-item label="网络">{{ movie.network || '-' }}</el-descriptions-item>
          <el-descriptions-item label="制作商">{{ movie.studio || '-' }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ movie.source || '-' }}</el-descriptions-item>
          <el-descriptions-item label="发行日期">{{ movie.release_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ movie.duration ? movie.duration + ' 分钟' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ movie.rating ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="播放次数">{{ movie.play_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ formatSize(movie.file_size) }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusMap[movie.status] || movie.status }}</el-descriptions-item>
        </el-descriptions>

        <div class="actors-section" v-if="movie.actors">
          <h3>演员</h3>
          <el-tag v-for="a in parseActors(movie.actors)" :key="a" size="small" type="success">{{ a }}</el-tag>
        </div>

        <div class="tags-section" v-if="movie.tag">
          <h3>标签</h3>
          <el-tag v-for="t in parseCategories(movie.tag)" :key="t" size="small" type="warning">{{ t }}</el-tag>
        </div>

        <div class="desc" v-if="movie.plot">
          <h3>简介</h3>
          <p>{{ movie.plot }}</p>
        </div>

        <div class="file-section" v-if="movie.file_path">
          <h3>文件路径</h3>
          <code>{{ movie.file_path }}</code>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWesternStore } from '@/stores/western'
import defaultCover from '@/assets/default-cover.png'

const route = useRoute()
const router = useRouter()
const store = useWesternStore()
const movie = ref(null)
const loading = ref(true)

const statusMap = { pending: '待刮削', scraped: '已刮削', failed: '失败' }

function parseActors(val) {
  if (!val) return []
  if (Array.isArray(val)) return val
  try { return JSON.parse(val) } catch { return val.split(/[,\n|]/) }
}

function parseCategories(val) {
  if (!val) return []
  try { return JSON.parse(val) } catch { return val.split(/[,\n|]/) }
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes >= 1024 * 1024 * 1024) return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(2) + ' MB'
  if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB'
  return bytes + ' B'
}

function goBack() {
  router.push('/western/movies')
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
.detail-content { display: flex; gap: 24px; }
.cover-section { flex-shrink: 0; width: 350px; }
.cover-section img { width: 100%; border-radius: 8px; }
.info-section { flex: 1; }
.info-section h1 { font-size: 18px; margin-bottom: 16px; }
.actors-section { margin-top: 16px; }
.actors-section h3 { font-size: 14px; margin-bottom: 8px; }
.actors-section .el-tag { margin-right: 6px; margin-bottom: 4px; }
.desc { margin-top: 16px; }
.desc h3 { font-size: 14px; margin-bottom: 8px; }
.desc p { line-height: 1.6; color: #666; font-size: 13px; }
.tags-section { margin-top: 12px; }
.tags-section h3 { font-size: 14px; margin-bottom: 8px; }
.tags-section .el-tag { margin-right: 6px; margin-bottom: 4px; }
.file-section { margin-top: 16px; }
.file-section h3 { font-size: 14px; margin-bottom: 8px; }
.file-section code { background: #f5f7fa; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
</style>
