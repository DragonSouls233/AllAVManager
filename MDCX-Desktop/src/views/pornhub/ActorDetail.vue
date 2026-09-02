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
          <el-statistic title="作品数" :value="actor.movie_count || 0" />
          <el-statistic v-if="actor.total_views" title="总播放" :value="actor.total_views" />
        </div>
        <el-button type="primary" size="small" :loading="scraping" @click="scrapeProfile" style="margin-top: 12px">
          <el-icon><Refresh /></el-icon> 刮削资料/头像
        </el-button>
        <el-button v-if="actor.photo_url" type="success" size="small" :loading="downloadingAvatar" @click="downloadPhoto" style="margin-top: 6px">
          <el-icon><Download /></el-icon> 下载头像
        </el-button>

        <div v-if="actor.profile_url" class="profile-link">
          <a :href="actor.profile_url" target="_blank" rel="noopener">{{ actor.profile_url }}</a>
        </div>
      </div>
      <div class="info-section">
        <div v-if="actor.bio" class="bio-section">
          <h3>Bio</h3>
          <p>{{ actor.bio }}</p>
        </div>

        <div v-if="actor.background || actor.birthplace || actor.country || actor.nationality" class="profile-fields">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item v-if="actor.country" label="Country">{{ actor.country }}</el-descriptions-item>
            <el-descriptions-item v-if="actor.nationality" label="Nationality">{{ actor.nationality }}</el-descriptions-item>
            <el-descriptions-item v-if="actor.birthplace" label="Birth Place">{{ actor.birthplace }}</el-descriptions-item>
            <el-descriptions-item v-if="actor.background" label="Background">{{ actor.background }}</el-descriptions-item>
            <el-descriptions-item v-if="actor.photo_url" label="Photo URL" :span="2">
              <el-text style="word-break: break-all; font-size: 11px">{{ actor.photo_url }}</el-text>
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <div v-if="actor.aliases && actor.aliases.length" class="aliases-section">
          <h4>Aliases</h4>
          <el-tag v-for="a in actor.aliases" :key="a" size="small" type="info" style="margin: 2px">{{ a }}</el-tag>
        </div>

        <div class="movies-section" style="margin-top: 20px">
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePornhubStore } from '@/stores/pornhub'
import { ElMessage } from 'element-plus'
import { getAvatarSrc, getCoverSrc } from '@/utils/media'
import {
  scrapePornhubActorProfile,
  getPornhubActorMovies,
  pornhubVideoDownload,
} from '@/api/pornhub'

const route = useRoute()
const router = useRouter()
const store = usePornhubStore()
const actor = ref(null)
const movies = ref([])
const loading = ref(true)
const scraping = ref(false)
const downloadingAvatar = ref(false)

function goBack() { router.push('/pornhub/actors') }
function goMovieDetail(id) { router.push(`/pornhub/movies/${id}`) }

function handleAvatarError(e) {
  e.target.src = 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="150" height="150"%3E%3Crect width="150" height="150" fill="%23111827"/%3E%3Ctext x="75" y="81" text-anchor="middle" font-size="50" fill="%23666"%3E%3F%3C/text%3E%3C/svg%3E'
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

async function downloadPhoto() {
  if (!actor.value?.photo_url) return
  downloadingAvatar.value = true
  try {
    const url = actor.value.photo_url
    const res = await fetch(url, { mode: 'cors' })
    const blob = await res.blob()
    const ext = url.split('.').pop()?.split('?')[0] || 'jpg'
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${actor.value.name}_${actor.value.id}.${ext}`
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('头像下载完成')
  } catch (e) {
    ElMessage.error('头像下载失败: ' + (e.message || '未知错误'))
  } finally {
    downloadingAvatar.value = false
  }
}

onMounted(async () => {
  try {
    const id = Number(route.params.id)
    actor.value = await store.loadActorDetail(id)
    const res = await getPornhubActorMovies(id)
    movies.value = res?.movies || []
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.actor-detail { padding: 20px; }
.detail-content { display: flex; gap: 24px; }
.avatar-section { flex-shrink: 0; width: 240px; text-align: center; }
.avatar-section img { width: 150px; height: 150px; border-radius: 50%; object-fit: cover; margin-bottom: 12px; }
.avatar-section h2 { font-size: 18px; margin-bottom: 8px; }
.stats { font-size: 13px; color: #999; display: flex; flex-direction: column; gap: 8px; align-items: center; margin-bottom: 12px; }
.profile-link { font-size: 11px; color: #409eff; word-break: break-all; margin-top: 8px; }
.profile-link a { text-decoration: none; overflow: hidden; text-overflow: ellipsis; }
.profile-fields { margin-top: 16px; }
.info-section { flex: 1; }
.bio-section { margin-bottom: 16px; }
.bio-section h3 { font-size: 14px; margin-bottom: 8px; }
.bio-section p { line-height: 1.6; color: #666; font-size: 13px; }
.aliases-section { margin-top: 12px; }
.aliases-section h4 { font-size: 13px; margin-bottom: 6px; color: #666; }
.movies-section h3 { font-size: 16px; margin-bottom: 12px; }
.movies-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.movie-card { cursor: pointer; border: 1px solid #eee; border-radius: 6px; overflow: hidden; }
.movie-card img { width: 100%; aspect-ratio: 3/4; object-fit: cover; }
.movie-title { padding: 6px; font-size: 12px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
