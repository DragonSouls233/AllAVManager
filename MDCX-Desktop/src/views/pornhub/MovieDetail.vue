<template>
  <div class="movie-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回 PORNHub 列表
    </el-button>

    <div v-if="movie" class="detail-content">
      <div class="cover-section">
        <img :src="movie.cover_url || defaultCover" :alt="movie.title">
      </div>
      <div class="info-section">
        <h1>{{ movie.title || movie.code }}</h1>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="番号">{{ movie.code }}</el-descriptions-item>
          <el-descriptions-item label="上传者">{{ movie.uploader || '-' }}</el-descriptions-item>
          <el-descriptions-item label="演员">{{ movie.actor || '-' }}</el-descriptions-item>
          <el-descriptions-item label="制作商">{{ movie.studio || '-' }}</el-descriptions-item>
          <el-descriptions-item label="播放量">{{ formatNumber(movie.source_views) }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ movie.source_score ?? movie.rating ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ movie.duration ? movie.duration + '分钟' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusMap[movie.status] || movie.status }}</el-descriptions-item>
          <el-descriptions-item label="发布日期">{{ movie.release_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="下载量">{{ formatNumber(movie.source_downloads) }}</el-descriptions-item>
        </el-descriptions>

        <div class="categories-section" v-if="movie.categories">
          <h3>分类</h3>
          <el-tag v-for="c in parseCategories(movie.categories)" :key="c" size="small" type="info">{{ c }}</el-tag>
        </div>

        <div class="desc" v-if="movie.plot">
          <h3>简介</h3>
          <p>{{ movie.plot }}</p>
        </div>
        <div class="tags-section" v-if="movie.tags">
          <h3>标签</h3>
          <el-tag v-for="t in parseCategories(movie.tags)" :key="t" size="small" type="warning">{{ t }}</el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePornhubStore } from '@/stores/pornhub'
import defaultCover from '@/assets/default-cover.png'

const route = useRoute()
const router = useRouter()
const store = usePornhubStore()
const movie = ref(null)
const loading = ref(true)

const statusMap = { pending: '待刮削', scraped: '已刮削', failed: '失败' }

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

function goBack() {
  router.push('/pornhub')
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
.categories-section { margin-top: 16px; }
.categories-section h3 { font-size: 14px; margin-bottom: 8px; }
.categories-section .el-tag { margin-right: 6px; margin-bottom: 4px; }
.desc { margin-top: 16px; }
.desc h3 { font-size: 14px; margin-bottom: 8px; }
.desc p { line-height: 1.6; color: #666; font-size: 13px; }
.tags-section { margin-top: 12px; }
.tags-section h3 { font-size: 14px; margin-bottom: 8px; }
.tags-section .el-tag { margin-right: 6px; margin-bottom: 4px; }
</style>
