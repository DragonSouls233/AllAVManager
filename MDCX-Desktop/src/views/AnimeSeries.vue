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
          <!-- 列表外直接播放整系列 -->
          <button class="s-play" :title="`播放整系列《${s.name}》`" :disabled="playLoadingId === s.id"
                  @click.stop="playSeriesFromList(s)">
            <span v-if="playLoadingId === s.id" class="spinner" />
            <span v-else>▶</span>
          </button>
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
          <span class="count">· 共 {{ selected.movie_count }} 集</span>
        </div>
        <el-button type="primary" plain :disabled="!displayEpisodes.length"
                   @click="playSeriesInView" title="按当前筛选连播整系列">
          ▶ 播放整系列
        </el-button>
      </div>

      <!-- 年份时间线筛选：按系列各集 release_date 的年份统计 -->
      <div v-if="yearBuckets.length" class="timeline">
        <span class="tl-label">时间线：</span>
        <button class="tl-chip" :class="{ active: yearFilter === null }" @click="yearFilter = null">
          全部 ({{ episodes.length }})
        </button>
        <button v-for="b in yearBuckets" :key="b.year" class="tl-chip"
                :class="{ active: yearFilter === b.year }" @click="yearFilter = b.year">
          {{ b.year }} ({{ b.count }})
        </button>
      </div>

      <div v-loading="epLoading" class="grid">
        <div v-for="m in displayEpisodes" :key="m.id" class="card" @click="openPlayer(m)">
          <div class="poster">
            <img :src="m.cover" :alt="m.title" @error="onCoverError" loading="lazy" />
            <span class="ep-badge">{{ m.episode ? '第' + m.episode + '集' : (m.title || '?') }}</span>
          </div>
          <div class="meta">
            <div class="m-title" :title="m.title">{{ m.title }}</div>
            <div class="m-date" v-if="m.release_date">{{ m.release_date }}</div>
            <div class="m-year" v-if="yearOf(m)">{{ yearOf(m) }}</div>
          </div>
        </div>
      </div>
      <el-empty v-if="!epLoading && !displayEpisodes.length" description="该筛选条件下暂无集数" />
    </div>

    <!-- 播放列表连播弹窗 -->
    <el-dialog v-model="playerVisible" :title="(current?.series || '') + ' · 连播'" width="92%" top="3vh" @close="closePlayer">
      <div v-if="current" class="player-wrap">
        <div class="player-main">
          <video :key="current.id" :src="current.play_url" controls autoplay
                 style="width:100%;max-height:62vh;background:#000"
                 @error="onVideoError" @ended="onEnded" />
          <div class="player-bar">
            <el-button :disabled="playIndex === 0" @click="prev">⏮ 上一集</el-button>
            <span class="pos">{{ playIndex + 1 }} / {{ playlist.length }}</span>
            <el-button :disabled="playIndex >= playlist.length - 1" @click="next">下一集 ⏭</el-button>
            <span class="now" v-if="current.episode">第 {{ current.episode }} 集</span>
            <span class="now" v-else-if="current.title">{{ current.title }}</span>
          </div>
          <div class="player-meta">
            <span v-if="current.maker" class="tag maker">{{ current.maker }}</span>
            <span v-if="current.series" class="tag series">{{ current.series }}</span>
            <span v-if="current.episode" class="tag">第{{ current.episode }}集</span>
            <span v-if="current.release_date" class="tag">{{ current.release_date }}</span>
          </div>
        </div>
        <div class="player-list">
          <div class="pl-head">播放列表 ({{ playlist.length }})</div>
          <div v-for="(m, i) in playlist" :key="m.id"
               :class="['pl-item', { active: i === playIndex, watched: m._played }]"
               @click="jumpTo(i)">
            <span class="pl-idx">{{ i + 1 }}</span>
            <img v-if="m.cover" :src="m.cover" class="pl-cover" @error="onCoverError" />
            <span class="pl-title">{{ m.title || m.code }}</span>
            <span class="pl-ep" v-if="m.episode">第{{ m.episode }}集</span>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
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

// 年份时间线筛选
const yearFilter = ref(null)

// 播放列表连播
const playlist = ref([])
const playIndex = ref(0)
const playerVisible = ref(false)
const playLoadingId = ref(null)
const current = computed(() => playlist.value[playIndex.value] || null)

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
  yearFilter.value = null
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

function back() { selected.value = null; episodes.value = []; yearFilter.value = null }

async function loadFilters() {
  try { const mk = await getAnimeMakers(); makers.value = mk.items || [] } catch {}
}

function onCoverError(e) {
  e.target.style.visibility = 'hidden'
}
function onVideoError() {
  ElMessage?.error?.('视频加载失败，请确认服务器已挂载该目录')
}

// ===== 年份时间线 =====
function yearOf(m) {
  const y = (m.release_date || '').slice(0, 4)
  return /^\d{4}$/.test(y) ? y : ''
}
const yearBuckets = computed(() => {
  const map = {}
  for (const m of episodes.value) {
    const y = yearOf(m)
    if (y) map[y] = (map[y] || 0) + 1
  }
  return Object.keys(map).sort((a, b) => b - a).map(y => ({ year: y, count: map[y] }))
})
const displayEpisodes = computed(() => {
  if (yearFilter.value === null) return episodes.value
  return episodes.value.filter(m => yearOf(m) === String(yearFilter.value))
})

// ===== 播放列表连播 =====
function openPlayer(m) {
  // 单集点击：以"当前筛选结果"为播放列表，从点击项开始连播
  playlist.value = displayEpisodes.value.slice()
  const idx = playlist.value.findIndex(x => x.id === m.id)
  playIndex.value = idx >= 0 ? idx : 0
  playerVisible.value = true
}
function playSeriesInView() {
  if (!displayEpisodes.value.length) return
  playlist.value = displayEpisodes.value.slice()
  playIndex.value = 0
  playerVisible.value = true
}
async function playSeriesFromList(s) {
  if (playLoadingId.value) return
  playLoadingId.value = s.id
  try {
    const res = await getAnimeSeriesMovies(s.id)
    const items = res.items || []
    if (!items.length) {
      ElMessage?.warning?.(`《${s.name}》暂无可播放的集数`)
      return
    }
    selected.value = s
    episodes.value = items
    epTotal.value = res.total || items.length
    playlist.value = items.slice()
    playIndex.value = 0
    playerVisible.value = true
  } catch (e) {
    ElMessage?.error?.('加载系列失败：' + (e?.message || e))
  } finally {
    playLoadingId.value = null
  }
}
function next() {
  if (playIndex.value < playlist.value.length - 1) {
    markPlayed(playIndex.value)
    playIndex.value += 1
  }
}
function prev() {
  if (playIndex.value > 0) playIndex.value -= 1
}
function jumpTo(i) {
  if (i >= 0 && i < playlist.value.length) playIndex.value = i
}
function onEnded() {
  markPlayed(playIndex.value)
  if (playIndex.value < playlist.value.length - 1) {
    playIndex.value += 1   // 自动连播下一集
  } else {
    ElMessage?.success?.('本系列播放完毕')
  }
}
function markPlayed(i) {
  const m = playlist.value[i]
  if (m) m._played = true
}
function closePlayer() {
  playerVisible.value = false
}

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
.s-play {
  position: absolute; bottom:8px; left:8px; width:38px; height:38px; border-radius:50%;
  border: none; background: rgba(0,0,0,.55); color:#fff; font-size:16px; line-height:38px; text-align:center;
  cursor: pointer; display:flex; align-items:center; justify-content:center; transition: background .2s, transform .2s;
}
.s-play:hover { background:#b37feb; transform: scale(1.08); }
.s-play:disabled { opacity:.7; cursor:default; }
.spinner { width:16px; height:16px; border:2px solid rgba(255,255,255,.4); border-top-color:#fff; border-radius:50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.s-name { padding: 8px 10px 2px; font-size: 14px; font-weight: 600; line-height:1.4; max-height:2.8em; overflow:hidden; }
.s-maker { padding: 0 10px 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.episodes-view { margin-top: 8px; }
.ep-head { display:flex; align-items:center; gap:16px; margin-bottom:16px; flex-wrap: wrap; }
.ep-title { font-size: 18px; display:flex; align-items:center; gap:10px; }
.ep-title .count { color: var(--el-text-color-secondary); font-weight: normal; font-size:14px; }
.timeline { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
.tl-label { font-size:13px; color: var(--el-text-color-secondary); }
.tl-chip {
  border:1px solid var(--el-border-color, #dcdfe6); background: var(--el-bg-color-overlay,#fff);
  color: var(--el-text-color-regular); border-radius:16px; padding:4px 12px; font-size:13px; cursor:pointer; transition: all .15s;
}
.tl-chip:hover { border-color:#b37feb; color:#8a4fd0; }
.tl-chip.active { background:#b37feb; border-color:#b37feb; color:#fff; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 16px; }
.card { cursor: pointer; border-radius: 12px; overflow: hidden; background: var(--el-bg-color-overlay,#fff); transition: transform .2s, box-shadow .2s; }
.card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,.18); }
.poster { position: relative; aspect-ratio: 3/4; background: #2a2a35; }
.poster img { width:100%; height:100%; object-fit: cover; }
.ep-badge { position:absolute; top:8px; right:8px; background:#b37feb; color:#fff; font-size:12px; padding:2px 8px; border-radius:10px; max-width:90%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.meta { padding: 8px 10px; }
.m-title { font-size: 13px; line-height:1.4; max-height:2.8em; overflow:hidden; }
.m-date { margin-top:4px; font-size:12px; color: var(--el-text-color-secondary); }
.m-year { font-size:11px; color:#b37feb; }
.tag { font-size:11px; padding:1px 7px; border-radius:8px; background: rgba(0,0,0,.06); }
.tag.maker { background: rgba(240,110,201,.15); color:#d24bb0; }
.tag.series { background: rgba(179,127,235,.15); color:#8a4fd0; }
/* 连播弹窗 */
.player-wrap { display:flex; gap:16px; align-items:flex-start; }
.player-main { flex: 1 1 auto; min-width:0; }
.player-bar { display:flex; align-items:center; gap:12px; margin-top:10px; flex-wrap:wrap; }
.player-bar .pos { font-size:14px; color: var(--el-text-color-secondary); min-width:48px; text-align:center; }
.player-bar .now { font-size:13px; color: var(--el-text-color-secondary); margin-left:auto; }
.player-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.player-list { flex: 0 0 280px; max-height:62vh; overflow-y:auto; border-left:1px solid var(--el-border-color,#ebeef5); padding-left:14px; }
.pl-head { font-size:13px; font-weight:600; margin-bottom:8px; color: var(--el-text-color-secondary); }
.pl-item { display:flex; align-items:center; gap:8px; padding:6px 6px; border-radius:8px; cursor:pointer; }
.pl-item:hover { background: rgba(0,0,0,.05); }
.pl-item.active { background: rgba(179,127,235,.18); }
.pl-idx { font-size:12px; color: var(--el-text-color-secondary); width:20px; text-align:right; flex:0 0 auto; }
.pl-cover { width:34px; height:46px; object-fit:cover; border-radius:4px; background:#2a2a35; flex:0 0 auto; }
.pl-title { font-size:13px; line-height:1.3; overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.pl-ep { font-size:11px; color:#b37feb; flex:0 0 auto; }
.pl-item.watched .pl-title { color: var(--el-text-color-secondary); text-decoration: line-through; }
@media (max-width: 860px) {
  .player-wrap { flex-direction: column; }
  .player-list { flex: 1 1 auto; max-height:40vh; border-left:none; border-top:1px solid var(--el-border-color,#ebeef5); padding-left:0; padding-top:12px; width:100%; }
}
</style>
