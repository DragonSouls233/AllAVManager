<template>
  <div class="anime-series-page">
    <div class="page-head">
      <div class="title-row">
        <h2>📺 日本里番 · 系列</h2>
        <el-button text @click="$router.push('/anime')">影片库 →</el-button>
      </div>
      <div class="filters">
        <el-input v-model="q" placeholder="搜索系列名 / 制作商" clearable style="width:280px" @input="onSearch" />
        <el-select v-model="maker" placeholder="制作商" clearable filterable style="width:200px" @change="load">
          <el-option v-for="m in makers" :key="m.name" :label="`${m.name} (${m.movie_count})`" :value="m.name" />
        </el-select>
      </div>
    </div>

    <!-- 系列列表 -->
    <div v-if="!selected" v-loading="loading" class="series-grid">
      <div v-for="s in seriesList" :key="s.id" class="series-card" @click="openSeries(s)">
        <div class="s-cover">
          <img v-if="s.cover" :src="s.cover" :alt="s.name" @error="onCoverError" loading="lazy" />
          <span class="s-count">{{ s.movie_count }} 集</span>
        </div>
        <div class="s-name" :title="s.name">{{ s.name }}</div>
        <div class="s-maker" v-if="s.maker">{{ s.maker }}</div>
      </div>
    </div>

    <el-empty v-if="!selected && !loading && !seriesList.length" description="暂无系列数据，请先扫描 anime 模块" />

    <!-- 系列内集数 -->
    <div v-if="selected" class="episodes-view">
      <div class="ep-head">
        <el-button @click="back">← 返回系列</el-button>
        <div class="ep-title">
          <strong>{{ selected.name }}</strong>
          <span v-if="selected.maker" class="tag maker">{{ selected.maker }}</span>
          <span class="count">· 共 {{ epTotal }} 集</span>
        </div>
      </div>
      <div v-loading="epLoading" class="grid">
        <div v-for="m in episodes" :key="m.id" class="card" @click="openPlayer(m)">
          <div class="poster">
            <img :src="m.cover" :alt="m.title" @error="onCoverError" loading="lazy" />
            <span class="ep-badge">{{ m.episode ? '第' + m.episode + '集' : (m.title || '?') }}</span>
          </div>
          <div class="meta">
            <div class="m-title" :title="m.title">{{ m.title }}</div>
            <div class="m-date" v-if="m.release_date">{{ m.release_date }}</div>
          </div>
        </div>
      </div>
      <el-empty v-if="!epLoading && !episodes.length" description="该系列暂无集数" />
    </div>

    <el-dialog v-model="playerVisible" :title="current?.title" width="80%" top="5vh" @close="closePlayer">
      <div v-if="current" class="player-wrap">
        <video v-if="playerVisible" :src="current.play_url" controls autoplay
               style="width:100%;max-height:70vh;background:#000" @error="onVideoError" />
        <div class="player-meta">
          <span v-if="current.maker" class="tag maker">{{ current.maker }}</span>
          <span v-if="current.series" class="tag series">{{ current.series }}</span>
          <span v-if="current.episode" class="tag">第{{ current.episode }}集</span>
          <span v-if="current.release_date" class="tag">{{ current.release_date }}</span>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAnimeSeries, getAnimeSeriesMovies, getAnimeMakers } from '@/api/anime'

const seriesList = ref([])
const makers = ref([])
const loading = ref(false)
const q = ref('')
const maker = ref('')

const selected = ref(null)
const episodes = ref([])
const epTotal = ref(0)
const epLoading = ref(false)

const playerVisible = ref(false)
const current = ref(null)

let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(), 350)
}

async function load() {
  loading.value = true
  try {
    const res = await getAnimeSeries({
      limit: 300,
      q: q.value || undefined,
      maker: maker.value || undefined,
    })
    // 后端 /series 暂不支持 q/maker 过滤，前端兜底
    let items = res.items || []
    if (q.value) {
      const k = q.value.toLowerCase()
      items = items.filter(s => (s.name || '').toLowerCase().includes(k) || (s.maker || '').toLowerCase().includes(k))
    }
    if (maker.value) items = items.filter(s => s.maker === maker.value)
    // 为系列卡片找一张封面（取该系列首部作品的封面）
    await Promise.all(items.map(async (s) => {
      try {
        const r = await getAnimeSeriesMovies(s.id)
        const first = (r.items || [])[0]
        s.cover = first ? first.cover : null
      } catch { s.cover = null }
    }))
    seriesList.value = items
  } finally {
    loading.value = false
  }
}

async function openSeries(s) {
  selected.value = s
  epLoading.value = true
  try {
    const res = await getAnimeSeriesMovies(s.id)
    episodes.value = res.items || []
    epTotal.value = res.total || episodes.value.length
  } finally {
    epLoading.value = false
  }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function back() { selected.value = null; episodes.value = [] }

async function loadFilters() {
  try { const mk = await getAnimeMakers(); makers.value = mk.items || [] } catch {}
}

function onCoverError(e) {
  e.target.style.visibility = 'hidden'
}
function onVideoError() {
  ElMessage?.error?.('视频加载失败，请确认服务器已挂载该目录')
}
function openPlayer(m) { current.value = m; playerVisible.value = true }
function closePlayer() { current.value = null }

onMounted(() => { loadFilters(); load() })
</script>

<style scoped>
.anime-series-page { padding: 20px 24px; }
.page-head { margin-bottom: 18px; }
.title-row { display: flex; align-items: center; justify-content: space-between; }
.title-row h2 { margin: 0; font-size: 22px; }
.filters { display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
.series-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 18px; }
.series-card { cursor: pointer; border-radius: 12px; overflow: hidden; background: var(--el-bg-color-overlay,#fff); transition: transform .2s, box-shadow .2s; }
.series-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,.18); }
.s-cover { position: relative; aspect-ratio: 16/10; background: #2a2a35; display:flex; align-items:center; justify-content:center; }
.s-cover img { max-width:100%; max-height:100%; object-fit: cover; }
.s-count { position:absolute; bottom:8px; right:8px; background: rgba(0,0,0,.6); color:#fff; font-size:12px; padding:2px 8px; border-radius:10px; }
.s-name { padding: 8px 10px 2px; font-size: 14px; font-weight: 600; line-height:1.4; max-height:2.8em; overflow:hidden; }
.s-maker { padding: 0 10px 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.episodes-view { margin-top: 8px; }
.ep-head { display:flex; align-items:center; gap:16px; margin-bottom:16px; }
.ep-title { font-size: 18px; display:flex; align-items:center; gap:10px; }
.ep-title .count { color: var(--el-text-color-secondary); font-weight: normal; font-size:14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 16px; }
.card { cursor: pointer; border-radius: 12px; overflow: hidden; background: var(--el-bg-color-overlay,#fff); transition: transform .2s, box-shadow .2s; }
.card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,.18); }
.poster { position: relative; aspect-ratio: 3/4; background: #2a2a35; }
.poster img { width:100%; height:100%; object-fit: cover; }
.ep-badge { position:absolute; top:8px; right:8px; background:#b37feb; color:#fff; font-size:12px; padding:2px 8px; border-radius:10px; max-width:90%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.meta { padding: 8px 10px; }
.m-title { font-size: 13px; line-height:1.4; max-height:2.8em; overflow:hidden; }
.m-date { margin-top:4px; font-size:12px; color: var(--el-text-color-secondary); }
.tag { font-size:11px; padding:1px 7px; border-radius:8px; background: rgba(0,0,0,.06); }
.tag.maker { background: rgba(240,110,201,.15); color:#d24bb0; }
.tag.series { background: rgba(179,127,235,.15); color:#8a4fd0; }
.player-wrap { display:flex; flex-direction:column; gap:12px; }
.player-meta { display:flex; flex-wrap:wrap; gap:8px; }
</style>
