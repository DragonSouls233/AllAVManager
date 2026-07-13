<template>
  <div class="chinese-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回国产列表
    </el-button>

    <div v-if="movie" class="detail-content">
      <div class="cover-section">
        <img :src="movie.cover_url || defaultCover" :alt="movie.title">
      </div>
      <div class="info-section">
        <h1>{{ movie.title || movie.code }}</h1>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="番号">{{ movie.code }}</el-descriptions-item>
          <el-descriptions-item label="文件夹">{{ movie.folder_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="制作商">{{ movie.studio || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ movie.duration ? movie.duration + '分钟' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ movie.rating ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusMap[movie.status] || movie.status }}</el-descriptions-item>
        </el-descriptions>

        <div class="actors-section" v-if="folderActors.length">
          <h3>演员（来自文件夹）</h3>
          <el-tag v-for="a in folderActors" :key="a" type="success" size="large">{{ a }}</el-tag>
        </div>

        <div class="desc" v-if="movie.plot">
          <h3>简介</h3>
          <p>{{ movie.plot }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChineseStore } from '@/stores/chinese'
import defaultCover from '@/assets/default-cover.png'

const route = useRoute()
const router = useRouter()
const store = useChineseStore()
const movie = ref(null)
const loading = ref(true)

const statusMap = { pending: '待刮削', scraped: '已刮削', failed: '失败' }

const folderActors = computed(() => {
  if (!movie.value?.folder_based_actors) return []
  try { return JSON.parse(movie.value.folder_based_actors) }
  catch { return [movie.value.folder_based_actors] }
})

function goBack() {
  router.push('/chinese')
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
.chinese-detail { padding: 20px; }
.detail-content { display: flex; gap: 24px; }
.cover-section { flex-shrink: 0; width: 350px; }
.cover-section img { width: 100%; border-radius: 8px; }
.info-section { flex: 1; }
.info-section h1 { font-size: 18px; margin-bottom: 16px; }
.actors-section { margin-top: 16px; }
.actors-section h3 { margin-bottom: 8px; font-size: 14px; }
.actors-section .el-tag { margin-right: 6px; }
.desc { margin-top: 16px; }
.desc h3 { font-size: 14px; margin-bottom: 8px; }
.desc p { line-height: 1.6; color: #666; font-size: 13px; }
</style>
