<template>
  <section>
    <div class="cinema-page-head actor-head">
      <div>
        <div class="head-line">
          <el-button text size="small" @click="goBack">← 演员</el-button>
        </div>
        <h1 class="cinema-page-title" style="display: flex; align-items: center; gap: 12px">
          <img v-if="actorId" class="head-avatar" :src="headAvatar" alt="" @error="headAvatarErr" />
          <span>{{ actorName || '演员作品' }}</span>
          <span class="cinema-page-count">{{ total }} 部作品</span>
        </h1>
      </div>
    </div>

    <div v-if="error" class="cinema-empty">
      <div class="cinema-empty-icon">⚠️</div>
      <div class="cinema-empty-text">{{ error }}</div>
      <el-button size="small" style="margin-top: 12px" @click="reload">重试</el-button>
    </div>

    <div v-else-if="!loading && !movies.length" class="cinema-empty">
      <div class="cinema-empty-icon">🎬</div>
      <div class="cinema-empty-text">没有匹配的作品</div>
    </div>

    <div v-else class="cinema-grid">
      <template v-if="loading && !movies.length">
        <div v-for="n in 18" :key="`sk-${n}`" class="poster-skeleton" />
      </template>
      <PosterCard
        v-for="m in movies"
        :key="`${module}-${m.id}`"
        :movie="m"
        @open="openDetail"
        @play="playMovie"
      />
    </div>

    <div class="load-bar">
      <el-button v-if="hasMore" :loading="loading" size="small" text @click="loadMore">
        加载更多（{{ movies.length }}/{{ total }}）
      </el-button>
      <span v-else-if="total > 0" class="load-end">已到底部</span>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PosterCard from '@/components/cinema/PosterCard.vue'
import { useLibraryStore } from '@/stores/library'
import { getActor, getActorMovies } from '@/api'
import { getActorAvatarUrlById, defaultAvatar } from '@/utils/media'
import { decorateMovies } from '@/utils/browse'

const PAGE = 60
const route = useRoute()
const router = useRouter()
const lib = useLibraryStore()

const actorId = computed(() => Number(route.params.id))
const module = computed(() => String(route.query.module || lib.currentModule || 'jav'))

const movies = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const hasMore = ref(false)
const actorName = ref('')
const headAvatar = ref('')
let seq = 0

async function loadActorInfo() {
  try {
    const a = await getActor(actorId.value, module.value)
    actorName.value = a?.name || a?.canonical_name || ''
    headAvatar.value = a?.id ? getActorAvatarUrlById(a.id, module.value) : ''
  } catch { /* 头像/名字失败不阻塞作品列表 */ }
}

async function loadMore() {
  if (loading.value || !hasMore.value) return
  await load()
}

async function load() {
  const s = ++seq
  loading.value = true
  error.value = ''
  try {
    const res = await getActorMovies(
      actorId.value,
      {
        page: Math.floor(movies.value.length / PAGE) + 1,
        page_size: PAGE
      },
      module.value
    )
    if (s !== seq) return
    const list = decorateMovies(res?.items || [], module.value)
    movies.value = movies.value.concat(list)
    total.value = res?.total ?? movies.value.length
    hasMore.value = movies.value.length < total.value
    if (!actorName.value) actorName.value = res?.actor_name || ''
  } catch (e) {
    if (s !== seq) return
    error.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载作品失败，请检查服务器连接'
  } finally {
    if (s === seq) loading.value = false
  }
}

function reload() {
  movies.value = []
  total.value = 0
  hasMore.value = false
  error.value = ''
  load()
}

function headAvatarErr(e) {
  e.target.src = defaultAvatar(actorName.value)
}
function goBack() {
  router.push('/actors')
}
function openDetail(movie) {
  router.push(`/movie/${module.value}/${movie.id}`)
}
function playMovie(movie) {
  router.push(`/mpv/${module.value}/${movie.id}`)
}

onMounted(() => {
  loadActorInfo()
  load()
})
</script>

<style scoped>
.head-line { margin-bottom: 4px; }
.head-avatar {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--cinema-line);
  background: var(--cinema-2);
}
.load-bar { display: flex; justify-content: center; padding: 18px 0 8px; }
.load-end { font-size: 12px; color: var(--text-3); }
</style>
