<template>
  <div class="movie-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回无码列表
    </el-button>

    <div v-if="movie" class="detail-content">
      <div class="cover-section">
        <img :src="movie.cover_url || defaultCover" :alt="movie.title">
      </div>
      <div class="info-section">
        <h1>{{ movie.title || movie.code }}</h1>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="番号">{{ movie.code }}</el-descriptions-item>
          <el-descriptions-item label="来源平台">{{ movie.source_platform || '-' }}</el-descriptions-item>
          <el-descriptions-item label="演员">{{ movie.actor || '-' }}</el-descriptions-item>
          <el-descriptions-item label="制作商">{{ movie.studio || '-' }}</el-descriptions-item>
          <el-descriptions-item label="系列">{{ movie.series || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ movie.duration ? movie.duration + '分钟' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ movie.rating ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusMap[movie.status] || movie.status }}</el-descriptions-item>
          <el-descriptions-item label="发布日期">{{ movie.release_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ movie.source || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="desc" v-if="movie.plot">
          <h3>简介</h3>
          <p>{{ movie.plot }}</p>
        </div>
        <div class="tags-section" v-if="movie.tag || movie.genre">
          <el-tag v-if="movie.tag" type="warning">{{ movie.tag }}</el-tag>
          <el-tag v-if="movie.genre" type="info">{{ movie.genre }}</el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUncensoredStore } from '@/stores/uncensored'
import defaultCover from '@/assets/default-cover.png'

const route = useRoute()
const router = useRouter()
const store = useUncensoredStore()
const movie = ref(null)
const loading = ref(true)

const statusMap = { pending: '待刮削', scraped: '已刮削', failed: '失败' }

function goBack() {
  router.push('/uncensored')
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
.desc { margin-top: 16px; }
.desc h3 { font-size: 14px; margin-bottom: 8px; }
.desc p { line-height: 1.6; color: #666; font-size: 13px; }
.tags-section { margin-top: 12px; display: flex; gap: 6px; flex-wrap: wrap; }
</style>
