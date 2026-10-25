<template>
  <div class="actor-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回演员列表
    </el-button>

    <!--
      资料区走通用 EntityHero（与 JAV/无码/FC2 等模块同一块卡）。
      原先是「左列头像 + 右列 el-descriptions 边框表」，边框表在暗色下留白很重、
      字段一多就两列挤成一团；换成一行读数 + 右栏资料表后，信息一条没少。
    -->
    <EntityHero
      v-if="actor"
      :name="actor.name"
      kind-label="PORNHUB"
      :avatar="getAvatarSrc(actor)"
      :meta="heroMeta"
      :facts="heroFacts"
      :links="heroLinks"
      :related="costars"
      related-label="同台演员"
      @pick-related="goCostar"
    >
      <template #identity-extra>
        <div class="actor-actions">
          <el-button type="primary" size="small" :loading="scraping" @click="scrapeProfile">
            <el-icon><Refresh /></el-icon> 刮削资料/头像
          </el-button>
          <el-button v-if="actor.photo_url" type="success" size="small" :loading="downloadingAvatar" @click="downloadPhoto">
            <el-icon><Download /></el-icon> 下载头像
          </el-button>
        </div>
        <div v-if="actor.aliases && actor.aliases.length" class="aliases-section">
          <span class="aliases-label">别名</span>
          <el-tag v-for="a in actor.aliases" :key="a" size="small" type="info" style="margin: 2px">{{ a }}</el-tag>
        </div>
      </template>
    </EntityHero>

    <div v-if="actor" class="info-section">
        <div v-if="actor.bio" class="bio-section">
          <h3>Bio</h3>
          <p>{{ actor.bio }}</p>
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
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePornhubStore } from '@/stores/pornhub'
import { ElMessage } from 'element-plus'
import EntityHero from '@/components/base/EntityHero.vue'
import { getAvatarSrc, getCoverSrc, getActorAvatarUrlById } from '@/utils/media'
import { getActorCostars } from '@/api'
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

// ---------- 资料卡（EntityHero）的数据 ----------
const heroMeta = computed(() => {
  const a = actor.value
  if (!a) return []
  const rows = [{ icon: 'film', value: a.movie_count || 0, text: '部作品', strong: true }]
  if (a.total_views) rows.push({ icon: 'star', value: a.total_views, text: '次播放' })
  if (a.nationality) rows.push({ icon: 'user', value: a.nationality })
  if (a.country) rows.push({ icon: 'location', value: a.country })
  return rows
})

const heroFacts = computed(() => {
  const a = actor.value
  if (!a) return []
  const rows = []
  const push = (label, icon, value) => { if (value) rows.push({ label, icon, value: String(value) }) }
  push('国籍', 'user', a.nationality)
  push('国家', 'location', a.country)
  push('出生地', 'location', a.birthplace)
  push('背景', 'id-card', a.background)
  if (a.aliases?.length) rows.push({ label: '别名', icon: 'tags', value: '', tags: a.aliases })
  return rows
})

/** 外链：只放库里存下来的演员主页，不拼站点搜索地址 */
const heroLinks = computed(() => {
  const url = actor.value?.profile_url
  if (!url || !/^https?:\/\//i.test(url)) return []
  return [{ label: 'PORNHUB 主页', url, title: url, icon: 'link' }]
})

// 同台演员：PORNHUB 关联表有 90378 部片的共演关系，这条带基本都能出东西
const costars = ref([])
const loadCostars = async (id) => {
  costars.value = []
  try {
    const res = await getActorCostars(id, { limit: 24, min_movies: 2 }, 'pornhub')
    costars.value = (res.items || []).map(p => ({
      ...p,
      avatar: p.id ? getActorAvatarUrlById(p.id, 'pornhub') : '',
    }))
  } catch { costars.value = [] }
}
function goCostar (p) {
  if (p?.id) router.push(`/pornhub/actors/${p.id}`)
}

async function loadActorData(id) {
  if (!id) return
  loading.value = true
  try {
    actor.value = await store.loadActorDetail(id)
    const res = await getPornhubActorMovies(id)
    movies.value = res?.movies || []
    loadCostars(id)
  } finally {
    loading.value = false
  }
}

onMounted(() => loadActorData(Number(route.params.id)))

// 修复：从演员 A 点进演员 B 时，路由参数变化但组件复用，需重新加载
watch(() => route.params.id, (newId) => loadActorData(Number(newId)))
</script>

<style scoped>
.actor-detail { padding: 20px; }
.actor-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.aliases-section { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 10px; }
.aliases-label { color: var(--text-secondary, #6b7280); font-size: 12px; }
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
