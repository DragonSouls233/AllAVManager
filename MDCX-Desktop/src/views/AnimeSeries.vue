<template>
  <div class="anime-series-page">
    <div class="page-head">
      <div class="title-row">
        <h2>📺 日本里番 · 系列</h2>
        <div class="head-actions">
          <el-button text @click="$router.push('/anime/favorites')">★ 我的喜好 →</el-button>
          <el-button text @click="$router.push('/anime')">影片库 →</el-button>
        </div>
      </div>
      <div class="filters">
        <el-input v-model="q" placeholder="搜索系列名 / 制作商 / 影片名" clearable style="width:280px" @input="onSearch" />
        <el-select v-model="maker" placeholder="制作商" clearable filterable style="width:200px" @change="reload">
          <el-option v-for="m in makers" :key="m.name" :label="`${m.name} (${m.movie_count})`" :value="m.name" />
        </el-select>
        <el-select v-model="sort" style="width:150px" @change="reload">
          <el-option label="按集数排序" value="count" />
          <el-option label="按名称排序" value="name" />
          <el-option label="按最新更新" value="recent" />
        </el-select>
        <el-switch v-model="onlyFav" active-text="仅看喜好" @change="reload" />
        <span class="total-hint">共 {{ total }} 个系列</span>
      </div>
    </div>

    <!-- 系列列表 -->
    <div v-if="!selected" v-loading="loading" class="series-grid">
      <div v-for="s in seriesList" :key="s.id" class="series-card" @click="openSeries(s)">
        <div class="s-cover">
          <img
            v-if="s.cover"
            :src="s.cover"
            :alt="s.name"
            v-cover-fit="COVER_AR.seriesAnime"
            @error="onCoverError"
            loading="lazy"
          />
          <span class="s-count">{{ s.movie_count }} 集</span>
          <!-- 喜好标记：加入「我的喜好」页 -->
          <button class="s-fav" :class="{ on: s.favorited }"
                  :title="s.favorited ? '取消喜好' : '标记為我的喜好'"
                  @click.stop="toggleFav(s)">
            {{ s.favorited ? '★' : '☆' }}
          </button>
          <!-- 列表外直接播放整系列 -->
          <button class="s-play" :title="`播放整系列《${s.name}》`" :disabled="playLoadingId === s.id"
                  @click.stop="playSeriesFromList(s)">
            <span v-if="playLoadingId === s.id" class="spinner" />
            <span v-else>▶</span>
          </button>
        </div>
        <div class="s-name" :title="s.name">{{ s.name }}</div>
        <div class="s-maker" v-if="s.maker">{{ s.maker }}</div>
        <div class="s-latest" v-if="s.latest_date">最新 {{ s.latest_date }}</div>
      </div>
    </div>

    <div v-if="!selected && total > pageSize" class="pager">
      <el-pagination
        v-model:current-page="page"
        :total="total" :page-size="pageSize" :pager-count="7" background
        layout="prev, pager, next, jumper, total" @current-change="load" />
    </div>

    <el-empty v-if="!selected && !loading && !seriesList.length"
              :description="q ? `没有匹配「${q}」的系列（支持系列名 / 制作商 / 影片名）` : '暂无系列数据，请先扫描 anime 模块'" />

    <!-- 系列内集数 -->
    <div v-if="selected" class="episodes-view">
      <div class="ep-head">
        <el-button @click="back">← 返回系列</el-button>
        <div class="ep-title">
          <strong>{{ selected.name }}</strong>
          <span v-if="selected.maker" class="tag maker">{{ selected.maker }}</span>
          <span class="count">· 共 {{ selected.movie_count }} 集</span>
        </div>
        <el-button :type="selected?.favorited ? 'warning' : 'default'" plain
                   @click="toggleFav(selected)">
          {{ selected?.favorited ? '★ 已加入喜好' : '☆ 加入喜好' }}
        </el-button>
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

    <!-- 播放列表连播弹窗（与「我的喜好」页共用同一组件） -->
    <SeriesPlayerDialog
      v-model="playerVisible"
      v-model:playIndex="playIndex"
      :playlist="playlist"
      :series-name="current?.series || selected?.name || ''"
      @video-error="onVideoError" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getAnimeSeries, getAnimeSeriesMovies, getAnimeMakers, toggleAnimeFavoriteSeries } from '@/api/anime'
import SeriesPlayerDialog from '@/components/SeriesPlayerDialog.vue'
import { vCoverFit, COVER_AR } from '@/utils/coverFit'

const route = useRoute()
const router = useRouter()

const seriesList = ref([])
const makers = ref([])
const loading = ref(false)
const q = ref('')
const maker = ref('')
const sort = ref('count')
const onlyFav = ref(false)

// 分页：全库 1400+ 系列，必须服务端分页，否则一次只能拿到前 N 个
const page = ref(1)
const pageSize = ref(48)
const total = ref(0)

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
  searchTimer = setTimeout(() => reload(), 350)
}

// 条件变化：回到第一页
function reload() {
  page.value = 1
  load()
}

async function load() {
  loading.value = true
  try {
    // 搜索 / 制作商 / 喜好 过滤与分页全部下沉到后端，前端不再全量拉取
    const res = await getAnimeSeries({
      q: q.value || undefined,
      maker: maker.value || undefined,
      sort: sort.value,
      favorite: onlyFav.value || undefined,
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    seriesList.value = (res.items || []).map(s => ({ ...s, favorited: !!s.favorited }))
    total.value = res.total || 0
  } catch (e) {
    ElMessage?.error?.('加载系列失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

// 喜好标记（★/☆），与「我的喜好」页共用同一份数据
async function toggleFav(s) {
  const next = !s.favorited
  s.favorited = next  // 乐观更新，失败回滚
  try {
    const res = await toggleAnimeFavoriteSeries(s.id)
    s.favorited = !!res.favorited
    ElMessage?.success?.(s.favorited ? `已加入喜好：${s.name}` : `已移出喜好：${s.name}`)
  } catch (e) {
    s.favorited = !next
    ElMessage?.error?.('操作失败：' + (e?.message || e))
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

function back() {
  selected.value = null
  episodes.value = []
  yearFilter.value = null
  // 清掉 ?open= 直达参数，避免返回列表后再次自动展开
  if (route.query.open) router.replace({ path: '/anime/series' })
}

async function loadFilters() {
  try { const mk = await getAnimeMakers(); makers.value = mk.items || [] } catch {}
}

function onCoverError(e) {
  e.target.style.visibility = 'hidden'
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
    playSeries(items)
  } catch (e) {
    ElMessage?.error?.('加载系列失败：' + (e?.message || e))
  } finally {
    playLoadingId.value = null
  }
}
// 用给定片单打开连播弹窗（从第 1 集开始）
function playSeries(items) {
  playlist.value = items.slice()
  playIndex.value = 0
  playerVisible.value = true
}
function onVideoError() {
  ElMessage?.error?.('视频加载失败，请确认服务器已挂载该目录')
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
.s-cover { position: relative; /* 3:4 = 里番封面原生比例（实测 93% 落此区间），16:10 会裁掉大半画面 */ aspect-ratio: 3/4; background: #2a2a35; display:flex; align-items:center; justify-content:center; overflow: hidden; }
.s-cover img { width:100%; height:100%; object-fit: cover; }
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
/* 连播弹窗样式已抽到 @/components/SeriesPlayerDialog.vue（系列页与喜好页共用） */
</style>
