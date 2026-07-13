<template>
  <div class="actor-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回演员列表
    </el-button>

    <div v-if="actor" class="detail-content">
      <div class="avatar-section">
        <img :src="actor.avatar_url || defaultAvatar" alt="">
        <h2>{{ actor.name }}</h2>
        <div class="stats">
          <span>{{ actor.movie_count }} 部作品</span>
          <el-tag v-if="actor.source === 'scraper'" type="success" size="small">来自爬虫</el-tag>
        </div>
      </div>
      <div class="movies-section">
        <h3>作品列表</h3>
        <div class="movies-grid" v-if="movies.length">
          <div v-for="m in movies" :key="m.id" class="movie-card" @click="goMovieDetail(m.id)">
            <img :src="m.cover_url || defaultCover" alt="">
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
import { useUncensoredStore } from '@/stores/uncensored'
import defaultAvatar from '@/assets/default-avatar.png'
import defaultCover from '@/assets/default-cover.png'

const route = useRoute()
const router = useRouter()
const store = useUncensoredStore()
const actor = ref(null)
const movies = ref([])
const loading = ref(true)

function goBack() { router.push('/uncensored/actors') }
function goMovieDetail(id) { router.push(`/uncensored/movies/${id}`) }

onMounted(async () => {
  try {
    const actors = await store.loadActors()
    actor.value = actors.find(a => a.id === Number(route.params.id))
    await store.loadMovies()
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
