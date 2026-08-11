<template>
  <div class="actor-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回演员列表
    </el-button>

    <div v-if="actor" class="detail-content">
      <div class="avatar-section">
        <img :src="getAvatarSrc(actor)" alt="" @error="handleAvatarError">
        <h2>{{ actor.name }}</h2>
        <div class="stats">
          <span>{{ actor.movie_count }} 部作品</span>
          <el-tag v-if="actor.source === 'scraper'" type="success" size="small">来自爬虫</el-tag>
        </div>
        <el-button type="primary" size="small" :loading="scraping" @click="scrapeProfile" style="margin-top: 12px">
          刮削资料/头像
        </el-button>
      </div>
      <div class="movies-section">
        <h3>作品列表</h3>
        <div class="movies-grid" v-if="movies.length">
          <div v-for="m in movies" :key="m.id" class="movie-card" @click="goMovieDetail(m.id)">
            <img :src="getCoverSrc(m)" alt="">
            <div class="movie-title">{{ m.title || m.code }}</div>
          </div>
        </div>
        <el-empty v-else description="暂无作品" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePornhubStore } from '@/stores/pornhub'
import { ElMessage } from 'element-plus'
import defaultAvatar from '@/assets/default-avatar.png'
import defaultCover from '@/assets/default-cover.png'
import { getAvatarSrc, getCoverSrc } from '@/utils/media'
import { scrapePornhubActorProfile } from '@/api/pornhub'

const route = useRoute()
const router = useRouter()
const store = usePornhubStore()
const actor = ref(null)
const movies = ref([])
const loading = ref(true)
const scraping = ref(false)

function goBack() { router.push('/pornhub/actors') }
function goMovieDetail(id) { router.push(`/pornhub/movies/${id}`) }

function handleAvatarError(e) {
  e.target.src = defaultAvatar(e.target.alt || '?')
}

async function scrapeProfile() {
  if (!actor.value?.id) return
  scraping.value = true
  try {
    await scrapePornhubActorProfile(actor.value.id)
    ElMessage.success('已触发演员资料/头像刮削（后台进行，稍后刷新可见）')
    actor.value = await store.loadActorDetail(Number(route.params.id))
  } catch (e) {
    ElMessage.error('刮削触发失败')
  } finally {
    scraping.value = false
  }
}

onMounted(async () => {
  try {
    actor.value = await store.loadActorDetail(Number(route.params.id))
    // 只拉取当前演员的作品（按 movie.actor LIKE 过滤），并取足量条数避免分页截断
    await store.loadMovies({ actor: actor.value.name, limit: 1000 })
    movies.value = store.movies
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.actor-detail { padding: 20px; }
.detail-content { display: flex; gap: 24px; }
.avatar-section { flex-shrink: 0; width: 200px; text-align: center; }
.avatar-section img { width: 150px; height: 150px; border-radius: 50%; object-fit: cover; margin-bottom: 12px; }
.avatar-section h2 { font-size: 18px; margin-bottom: 8px; }
.stats { font-size: 13px; color: #999; display: flex; gap: 8px; justify-content: center; }
.movies-section { flex: 1; }
.movies-section h3 { font-size: 16px; margin-bottom: 12px; }
.movies-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.movie-card { cursor: pointer; border: 1px solid #eee; border-radius: 6px; overflow: hidden; }
.movie-card img { width: 100%; aspect-ratio: 3/4; object-fit: cover; }
.movie-title { padding: 6px; font-size: 12px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
