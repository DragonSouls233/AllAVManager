<template>
  <div class="anime-fav-page">
    <div class="page-head">
      <div class="title-row">
        <h2>★ 我的喜好 · 里番系列</h2>
        <div class="head-actions">
          <el-button text @click="$router.push('/anime/series')">全部系列 →</el-button>
          <el-button text @click="$router.push('/anime')">影片库 →</el-button>
        </div>
      </div>
      <div class="filters">
        <el-input v-model="q" placeholder="搜索系列名 / 影片名" clearable style="width:280px" @input="onSearch" />
        <el-select v-model="sort" style="width:160px" @change="reload">
          <el-option label="最近收藏" value="fav_time" />
          <el-option label="按集数排序" value="count" />
          <el-option label="按名称排序" value="name" />
          <el-option label="按最新更新" value="recent" />
        </el-select>
        <span class="total-hint">共 {{ total }} 个喜好系列 · 点 ▶ 直接连播，点卡片看集数</span>
      </div>
    </div>

    <div v-loading="loading" class="series-grid">
      <div v-for="s in list" :key="s.id" class="series-card" @click="openSeries(s)">
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
          <button class="s-fav on" title="取消喜好" @click.stop="removeFav(s)">★</button>
          <!-- 直接播放整系列，不用先跳到系列页 -->
          <button class="s-play" :title="`播放整系列《${s.name}》`" :disabled="playLoadingId === s.id"
                  @click.stop="playSeries(s)">
            <span v-if="playLoadingId === s.id" class="spinner" />
            <span v-else>▶</span>
          </button>
        </div>
        <div class="s-name" :title="s.name">{{ s.name }}</div>
        <div class="s-maker" v-if="s.maker">{{ s.maker }}</div>
        <div class="s-latest" v-if="s.latest_date">最新 {{ s.latest_date }}</div>
        <div class="s-added" v-if="s.favorited_at">收藏于 {{ shortDate(s.favorited_at) }}</div>
      </div>
    </div>

    <el-empty v-if="!loading && !list.length"
              description="还没有喜好系列 — 到「里番 · 系列」页点击卡片左上角的 ☆ 即可加入" />

    <div v-if="total > pageSize" class="pager">
      <el-pagination
        v-model:current-page="page"
        :total="total" :page-size="pageSize" :pager-count="7" background
        layout="prev, pager, next, jumper, total" @current-change="load" />
    </div>

    <!-- 连播弹窗（与系列页共用同一组件） -->
    <SeriesPlayerDialog
      v-model="playerVisible"
      v-model:playIndex="playIndex"
      :playlist="playlist"
      :series-name="playingName"
      @video-error="onVideoError" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAnimeFavoriteSeries, removeAnimeFavoriteSeries, getAnimeSeriesMovies } from '@/api/anime'
import SeriesPlayerDialog from '@/components/SeriesPlayerDialog.vue'
import { vCoverFit, COVER_AR } from '@/utils/coverFit'

const router = useRouter()

const list = ref([])
const loading = ref(false)
const q = ref('')
const sort = ref('fav_time')
const page = ref(1)
const pageSize = ref(48)
const total = ref(0)

// 连播播放（喜好页内直接播放整系列，无需跳到系列页）
const playlist = ref([])
const playIndex = ref(0)
const playerVisible = ref(false)
const playLoadingId = ref(null)
const playingName = ref('')

let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => reload(), 350)
}
function reload() { page.value = 1; load() }

async function load() {
  loading.value = true
  try {
    const res = await getAnimeFavoriteSeries({
      q: q.value || undefined,
      sort: sort.value,
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    list.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage?.error?.('加载喜好失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function openSeries(s) {
  // 跳到系列页并自动展开该系列（集数列表 + 连播播放器都在那边）
  router.push({ path: '/anime/series', query: { open: s.id } })
}

// 直接连播整系列：拉该系列集数后立刻开播
async function playSeries(s) {
  if (playLoadingId.value) return
  playLoadingId.value = s.id
  try {
    const res = await getAnimeSeriesMovies(s.id)
    const items = res.items || []
    if (!items.length) {
      ElMessage?.warning?.(`《${s.name}》暂无可播放的集数`)
      return
    }
    playingName.value = s.name
    playlist.value = items.slice()
    playIndex.value = 0
    playerVisible.value = true
  } catch (e) {
    ElMessage?.error?.('加载系列失败：' + (e?.message || e))
  } finally {
    playLoadingId.value = null
  }
}
function onVideoError() {
  ElMessage?.error?.('视频加载失败，请确认服务器已挂载该目录')
}

async function removeFav(s) {
  try {
    await ElMessageBox.confirm(`确定把《${s.name}》移出喜好？`, '取消喜好', {
      type: 'warning', confirmButtonText: '移出', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await removeAnimeFavoriteSeries(s.id)
    ElMessage?.success?.(`已移出喜好：${s.name}`)
    load()
  } catch (e) {
    ElMessage?.error?.('操作失败：' + (e?.message || e))
  }
}

function shortDate(v) {
  return (v || '').slice(0, 10)
}
function onCoverError(e) {
  e.target.style.visibility = 'hidden'
}

onMounted(load)
</script>

<style scoped>
.anime-fav-page { padding: 20px 24px; }
.page-head { margin-bottom: 18px; }
.title-row { display: flex; align-items: center; justify-content: space-between; }
.head-actions { display: flex; align-items: center; gap: 4px; }
.title-row h2 { margin: 0; font-size: 22px; }
.filters { display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; align-items: center; }
.total-hint { font-size: 13px; color: var(--el-text-color-secondary); }
.series-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 18px; }
.series-card { cursor: pointer; border-radius: 12px; overflow: hidden; background: var(--el-bg-color-overlay,#fff); transition: transform .2s, box-shadow .2s; }
.series-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,.18); }
.s-cover { position: relative; /* 3:4 = 里番封面原生比例，16:10 会裁掉大半画面 */ aspect-ratio: 3/4; background: #2a2a35; display:flex; align-items:center; justify-content:center; overflow: hidden; }
.s-cover img { width:100%; height:100%; object-fit: cover; }
.s-count { position:absolute; bottom:8px; right:8px; background: rgba(0,0,0,.6); color:#fff; font-size:12px; padding:2px 8px; border-radius:10px; }
.s-fav {
  position: absolute; top: 8px; left: 8px; width: 30px; height: 30px; border-radius: 50%;
  border: none; background: rgba(0,0,0,.5); color:#fff; font-size:16px; line-height:30px;
  cursor: pointer; display:flex; align-items:center; justify-content:center; transition: background .2s, transform .2s;
}
.s-fav.on { background: rgba(240,180,41,.92); }
.s-fav:hover { transform: scale(1.1); }
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
.s-maker { padding: 0 10px 4px; font-size: 12px; color: var(--el-text-color-secondary); }
.s-latest { padding: 0 10px 2px; font-size: 11px; color:#b37feb; }
.s-added { padding: 0 10px 10px; font-size: 11px; color: var(--el-text-color-secondary); }
.pager { display: flex; justify-content: center; margin-top: 22px; }
</style>
