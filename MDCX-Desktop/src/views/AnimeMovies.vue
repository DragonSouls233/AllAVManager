<template>
  <div class="anime-page">
    <div class="page-head">
      <div class="title-row">
        <h2>📺 日本里番</h2>
        <el-button text @click="$router.push('/anime/series')">查看系列 →</el-button>
      </div>
      <div class="filters">
        <el-input v-model="q" placeholder="搜索标题 / 制作商 / 系列" clearable style="width:260px" @input="onSearch" />
        <el-select v-model="maker" placeholder="制作商" clearable filterable style="width:180px" @change="load">
          <el-option v-for="m in makers" :key="m.name" :label="`${m.name} (${m.movie_count})`" :value="m.name" />
        </el-select>
        <el-select v-model="series" placeholder="系列" clearable filterable style="width:220px" @change="load">
          <el-option v-for="s in seriesList" :key="s.id" :label="`${s.name} (${s.movie_count})`" :value="s.name" />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <el-button type="warning" plain :loading="batchScraping" @click="scrapeAll">批量刮削未刮削</el-button>
      </div>
    </div>

    <div v-loading="loading" class="grid">
      <div v-for="m in movies" :key="m.id" class="card" @click="openPlayer(m)">
        <div class="poster">
          <img :src="m.cover" :alt="m.title" @error="onCoverError" loading="lazy" />
          <span v-if="m.episode" class="ep-badge">第{{ m.episode }}集</span>
          <span v-if="m.status === 'pending'" class="pend-badge">未刮削</span>
          <button v-if="m.status === 'pending'" class="scrape-btn" title="手动刮削 (getchu)"
                  :disabled="scrapingId === m.id" @click.stop="scrapeOne(m)">
            {{ scrapingId === m.id ? '刮削中…' : '刮削' }}
          </button>
        </div>
        <div class="meta">
          <div class="m-title" :title="m.title">{{ m.title }}</div>
          <div class="m-sub">
            <span v-if="m.maker" class="tag maker">{{ m.maker }}</span>
            <span v-if="m.series" class="tag series">{{ m.series }}</span>
          </div>
          <div class="m-date" v-if="m.release_date">{{ m.release_date }}</div>
        </div>
      </div>
    </div>

    <el-empty v-if="!loading && !movies.length" description="暂无作品，请先在服务器配置 anime 模块媒体目录并扫描" />

    <el-pagination
      v-if="total > pageSize"
      layout="prev, pager, next"
      :total="total" :page-size="pageSize" :current-page="page"
      @current-change="onPage"
      style="justify-content:center;margin-top:16px"
    />

    <el-dialog v-model="playerVisible" :title="current?.title" width="80%" top="5vh" @close="closePlayer">
      <div v-if="current" class="player-wrap">
        <video v-if="playerVisible" :src="current.play_url" controls autoplay
               style="width:100%;max-height:70vh;background:#000" @error="onVideoError" />
        <div class="player-meta">
          <span v-if="current.maker" class="tag maker">{{ current.maker }}</span>
          <span v-if="current.series" class="tag series">{{ current.series }}</span>
          <span v-if="current.episode" class="tag">第{{ current.episode }}集</span>
          <span v-if="current.release_date" class="tag">{{ current.release_date }}</span>
          <span v-if="current.status === 'pending'" class="tag pend">未刮削</span>
        </div>
        <div v-if="previews.length" class="preview-sec">
          <div class="preview-title">预览图（{{ previews.length }}）</div>
          <div class="preview-grid">
            <img v-for="(p, i) in previews" :key="i" :src="p" loading="lazy"
                 @error="e => e.target.style.display = 'none'" />
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAnimeMovies, getAnimeMakers, getAnimeSeries, scrapeAnimeMovie, scrapeAnimePending, getAnimeMoviePreviews } from '@/api/anime'

const movies = ref([])
const total = ref(0)
const loading = ref(false)
const q = ref('')
const maker = ref('')
const series = ref('')
const makers = ref([])
const seriesList = ref([])
const page = ref(1)
const pageSize = ref(48)

const playerVisible = ref(false)
const current = ref(null)
const previews = ref([])
const scrapingId = ref(null)
const batchScraping = ref(false)

let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 350)
}

async function load() {
  loading.value = true
  try {
    const res = await getAnimeMovies({
      q: q.value || undefined,
      maker: maker.value || undefined,
      series: series.value || undefined,
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    movies.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function onPage(p) { page.value = p; load() }

async function loadFilters() {
  try {
    const [mk, se] = await Promise.all([getAnimeMakers(), getAnimeSeries()])
    makers.value = mk.items || []
    seriesList.value = se.items || []
  } catch {}
}

function onCoverError(e) {
  e.target.src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="280"><rect fill="%232a2a35" width="200" height="280"/></svg>'
}
function onVideoError() {
  // 视频可能需鉴权或路径不可达，给出提示
  ElMessage?.error?.('视频加载失败，请确认服务器已挂载该目录且 anime 模块已扫描')
}

function openPlayer(m) {
  current.value = m
  previews.value = []
  playerVisible.value = true
  loadPreviews(m.id)
}
function closePlayer() {
  current.value = null
  previews.value = []
}

async function loadPreviews(id) {
  try {
    const res = await getAnimeMoviePreviews(id)
    if (res && res.source === 'local' && Array.isArray(res.images)) {
      previews.value = res.images
    }
  } catch {}
}

async function scrapeOne(m) {
  scrapingId.value = m.id
  try {
    const res = await scrapeAnimeMovie(m.id)
    if (res?.status === 'success') {
      ElMessage.success(res.message || '刮削完成')
      await load()
    } else {
      ElMessage.warning(res?.message || `刮削失败：${m.code}`)
    }
  } catch (e) {
    ElMessage.error(`刮削请求失败：${e?.message || e}`)
  } finally {
    scrapingId.value = null
  }
}

async function scrapeAll() {
  try {
    await ElMessageBox.confirm('将对所有「未刮削」(status=pending) 的里番逐部调用 getchu 刮削（限流并发，耗时视数量而定），继续？', '批量刮削', { type: 'warning' })
  } catch {
    return
  }
  batchScraping.value = true
  try {
    const res = await scrapeAnimePending(20)
    ElMessage.success(`批量刮削完成：成功 ${res?.ok ?? 0}，失败 ${res?.failed ?? 0}`)
    await load()
  } catch (e) {
    ElMessage.error(`批量刮削失败：${e?.message || e}`)
  } finally {
    batchScraping.value = false
  }
}

onMounted(() => { loadFilters(); load() })
</script>

<style scoped>
.anime-page { padding: 20px 24px; }
.page-head { margin-bottom: 18px; }
.title-row { display: flex; align-items: center; justify-content: space-between; }
.title-row h2 { margin: 0; font-size: 22px; }
.filters { display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 16px; }
.card { cursor: pointer; border-radius: 12px; overflow: hidden; background: var(--el-bg-color-overlay, #fff); transition: transform .2s, box-shadow .2s; }
.card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,.18); }
.poster { position: relative; aspect-ratio: 3/4; background: #2a2a35; }
.poster img { width: 100%; height: 100%; object-fit: cover; }
.ep-badge { position: absolute; top: 8px; right: 8px; background: #f06ec9; color: #fff; font-size: 12px; padding: 2px 8px; border-radius: 10px; }
.pend-badge { position: absolute; top: 8px; left: 8px; background: #e6a23c; color: #fff; font-size: 12px; padding: 2px 8px; border-radius: 10px; }
.scrape-btn { position: absolute; bottom: 8px; left: 8px; right: 8px; padding: 6px 0; border: none; border-radius: 8px;
  background: rgba(230,162,60,.92); color: #fff; font-size: 13px; cursor: pointer; transition: background .2s, transform .2s; }
.scrape-btn:hover:not(:disabled) { background: #d48806; transform: translateY(-1px); }
.scrape-btn:disabled { opacity: .6; cursor: not-allowed; }
.meta { padding: 8px 10px; }
.m-title { font-size: 13px; line-height: 1.4; max-height: 2.8em; overflow: hidden; }
.m-sub { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.m-date { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); }
.tag { font-size: 11px; padding: 1px 7px; border-radius: 8px; background: rgba(0,0,0,.06); }
.tag.maker { background: rgba(240,110,201,.15); color: #d24bb0; }
.tag.series { background: rgba(179,127,235,.15); color: #8a4fd0; }
.player-wrap { display: flex; flex-direction: column; gap: 12px; }
.player-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.tag.pend { background: rgba(230,162,60,.18); color: #d48806; }
.preview-sec { margin-top: 4px; }
.preview-title { font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.preview-grid img { width: 100%; aspect-ratio: 3/4; object-fit: cover; border-radius: 8px; background: #2a2a35; }
</style>
