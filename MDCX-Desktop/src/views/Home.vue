<template>
  <div class="home">
    <!-- 欢迎横幅 -->
    <el-card class="hero-card" shadow="never">
      <div class="hero">
        <div class="hero-text">
          <h1>欢迎回来，龙魂管理员</h1>
          <p>6 大模块独立管理 · 54+ 爬虫站点 · 各自独有的对比/补丁/播放工具</p>
          <div class="hero-badges">
            <el-tag type="success" effect="dark" size="small" v-if="healthStatus === 'ok'">● 服务器正常</el-tag>
            <el-tag type="warning" effect="dark" size="small" v-else-if="healthStatus === 'warn'">● 服务器降级</el-tag>
            <el-tag type="danger" effect="dark" size="small" v-else>● 未连接</el-tag>
            <el-tag type="info" effect="plain" size="small">{{ crawlerCount }} 爬虫在线</el-tag>
          </div>
        </div>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="$router.push('/jav/movies')">
            <el-icon><VideoCamera /></el-icon> 浏览影片
          </el-button>
          <el-button size="large" @click="$router.push('/cover-wall')">
            <el-icon><Grid /></el-icon> 全局封面墙
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 六模块仪表盘 -->
    <div class="module-grid">
      <div v-for="mod in modules" :key="mod.key" class="module-card" @click="$router.push(mod.moviesRoute)">
        <div class="module-card-header">
          <div class="module-card-title">
            <div class="module-card-icon" :style="{ background: mod.color }">{{ mod.emoji }}</div>
            <span class="module-card-name">{{ mod.label }}</span>
          </div>
          <div class="module-card-status">
            <span v-if="mod.movies > 0" class="maturity">{{ mod.maturity }}</span>
            <span v-else class="maturity muted">等待数据</span>
          </div>
        </div>
        <div class="module-stats">
          <div class="module-stat">
            <div class="module-stat-value">{{ mod.movies }}</div>
            <div class="module-stat-label">影片</div>
          </div>
          <div class="module-stat">
            <div class="module-stat-value">{{ mod.actors }}</div>
            <div class="module-stat-label">演员</div>
          </div>
          <div class="module-stat">
            <div class="module-stat-value">{{ mod.crawlers || mod.crawlerCount || '-' }}</div>
            <div class="module-stat-label">爬虫</div>
          </div>
        </div>
        <div class="module-actions" @click.stop>
          <el-button size="small" text @click="$router.push(mod.moviesRoute)">影片库</el-button>
          <el-button size="small" text @click="$router.push(mod.seriesRoute)" v-if="mod.seriesRoute">系列</el-button>
          <el-button size="small" text @click="$router.push(mod.actorsRoute)">演员库</el-button>
          <el-button size="small" text @click="$router.push(mod.compareRoute)" v-if="mod.compareRoute">本地对比</el-button>
          <el-button size="small" text @click="$router.push(mod.patchRoute)" v-if="mod.patchRoute">补丁</el-button>
        </div>
      </div>
    </div>

    <!-- 继续观看 -->
    <el-card shadow="never" class="section-card" v-if="continueWatching.length">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><VideoPlay /></el-icon> 继续观看
          </span>
          <el-button text @click="$router.push('/jav/movies')">
            更多 <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </template>
      <div class="horizontal-scroll">
        <div v-for="item in continueWatching" :key="item.id" class="scroll-card" @click="$router.push(`/movie/${item.id}`)">
          <div class="scroll-cover">
            <img :src="getMovieCoverUrl(item)" :alt="item.code" @error="handleCoverError">
            <div class="scroll-overlay"><el-icon size="28"><VideoPlay /></el-icon></div>
          </div>
          <div class="scroll-info">
            <span class="scroll-code">{{ item.code }}</span>
            <span class="scroll-title">{{ item.title || '未命名' }}</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 最新添加 + 最近任务 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="16">
        <el-card shadow="never" class="section-card">
          <template #header>
            <div class="card-header">
              <span class="card-title"><el-icon><Clock /></el-icon> 最新添加</span>
              <el-button text @click="$router.push('/jav/movies')">全部 <el-icon><ArrowRight /></el-icon></el-button>
            </div>
          </template>
          <div v-loading="loadingMovies" class="recent-grid">
            <div v-for="item in recentMovies" :key="item.id" class="recent-card" @click="$router.push(`/movie/${item.id}`)">
              <div class="recent-cover">
                <img :src="getMovieCoverUrl(item)" :alt="item.code" @error="handleCoverError">
                <div class="recent-overlay"><el-icon size="28"><VideoPlay /></el-icon></div>
              </div>
              <div class="recent-meta">
                <span class="recent-code">{{ item.code }}</span>
                <span class="recent-date" v-if="item.release_date">{{ item.release_date }}</span>
              </div>
            </div>
            <el-empty v-if="!loadingMovies && !recentMovies.length" description="暂无数据" />
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="8">
        <el-card shadow="never" class="section-card">
          <template #header>
            <div class="card-header">
              <span class="card-title"><el-icon><List /></el-icon> 最近任务</span>
              <el-button text @click="$router.push('/tasks')">全部 <el-icon><ArrowRight /></el-icon></el-button>
            </div>
          </template>
          <div v-loading="loadingTasks" class="task-list">
            <div v-for="task in recentTasks" :key="task.id" class="task-item">
              <div class="task-status">
                <el-tag :type="taskStatusType(task.status)" size="small" effect="dark">{{ taskStatusLabel(task.status) }}</el-tag>
              </div>
              <div class="task-info">
                <div class="task-name">{{ task.name || task.type || '任务' }}</div>
                <div class="task-meta">{{ task.progress }}% · {{ formatTime(task.created_at) }}</div>
              </div>
            </div>
            <el-empty v-if="!loadingTasks && !recentTasks.length" description="暂无任务" :image-size="60" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  VideoCamera, User, PriceTag, Connection, DataAnalysis, Star,
  Clock, ArrowRight, VideoPlay, List, Grid
} from '@element-plus/icons-vue'
import { getMovies, getDashboardStats, getTasks, getCrawlers, getTags, getSystemHealth } from '@/api'
import { defaultCover, getMovieCoverUrl } from '@/utils/media'

const router = useRouter()
const stats = ref({})
const recentMovies = ref([])
const recentTasks = ref([])
const continueWatching = ref([])
const tagCount = ref(0)
const crawlerCount = ref(0)
const loadingMovies = ref(false)
const loadingTasks = ref(false)
const healthStatus = ref('unknown')

const modules = reactive([
  { key: 'jav', label: 'JAV 有码', emoji: '🎬', color: 'linear-gradient(135deg,#409eff,#66b1ff)',
    moviesRoute: '/jav/movies', actorsRoute: '/jav/actors', compareRoute: '/jav/compare', patchRoute: '/jav/patch',
    movies: 0, actors: 0, crawlers: 0, maturity: '★★★★★' },
  { key: 'uncensored', label: 'JAV 无码', emoji: '🔓', color: 'linear-gradient(135deg,#67c23a,#85ce61)',
    moviesRoute: '/uncensored/movies', actorsRoute: '/uncensored/actors', compareRoute: '/uncensored/compare', patchRoute: '/uncensored/patch',
    movies: 0, actors: 0, crawlers: 0, maturity: '★★★★☆' },
  { key: 'fc2', label: 'FC2', emoji: '📹', color: 'linear-gradient(135deg,#e6a23c,#ebb563)',
    moviesRoute: '/fc2/movies', actorsRoute: '/fc2/actors', compareRoute: '/fc2/compare', patchRoute: '/fc2/patch',
    movies: 0, actors: 0, crawlers: 0, maturity: '★★★★☆' },
  { key: 'chinese', label: '国产', emoji: '🇨🇳', color: 'linear-gradient(135deg,#f56c6c,#f78989)',
    moviesRoute: '/chinese/movies', actorsRoute: '/chinese/actors', compareRoute: null, patchRoute: '/chinese/patch',
    movies: 0, actors: 0, crawlers: 0, maturity: '★★★★★' },
  { key: 'pornhub', label: 'PORNHub', emoji: '🌐', color: 'linear-gradient(135deg,#909399,#b0b3b8)',
    moviesRoute: '/pornhub/movies', actorsRoute: '/pornhub/actors', compareRoute: '/pornhub/compare', patchRoute: '/pornhub/patch',
    movies: 0, actors: 0, crawlers: 0, maturity: '★★★☆☆' },
  { key: 'western', label: '欧美', emoji: '🌍', color: 'linear-gradient(135deg,#b37feb,#d3adf7)',
    moviesRoute: '/western/movies', actorsRoute: '/western/actors', compareRoute: '/western/compare', patchRoute: '/western/patch',
    movies: 0, actors: 0, crawlers: 0, maturity: '★★☆☆☆' },
  { key: 'anime', label: '日本里番', emoji: '📺', color: 'linear-gradient(135deg,#f06ec9,#b37feb)',
    moviesRoute: '/anime', seriesRoute: '/anime/series', actorsRoute: null, compareRoute: null, patchRoute: null,
    movies: 0, actors: 0, crawlers: 0, maturity: '★★★☆☆' },
])

const handleCoverError = (event) => { event.target.src = defaultCover(event.target.alt) }

const loadStats = async () => {
  try {
    const s = await getSystemHealth()
    healthStatus.value = s?.status || 'unknown'
  } catch { healthStatus.value = 'unknown' }
  try {
    const res = await getDashboardStats()
    stats.value = res || {}
    const moduleData = res?.modules || {}
    for (const mod of modules) {
      const data = moduleData[mod.key]
      if (data) {
        mod.movies = data.movies || 0
        mod.actors = data.actors || 0
        mod.crawlers = data.crawlers || 0
      }
    }
    getCrawlers().then(r => {
      const list = r.items || r || []
      crawlerCount.value = list.length
      for (const mod of modules) {
        if (!mod.crawlers && mod.crawlers !== 0) mod.crawlers = list.length
      }
    }).catch(() => {})
  } catch { }
}

const loadRecentMovies = async () => {
  loadingMovies.value = true
  try {
    const res = await getMovies({ page: 1, page_size: 12 })
    recentMovies.value = res.items || []
  } catch { } finally { loadingMovies.value = false }
}

const loadContinueWatching = async () => {
  try {
    const res = await getMovies({ page: 1, page_size: 6, sort: '-last_played_at' })
    continueWatching.value = (res.items || []).filter(m => m.last_played_at)
  } catch { }
}

const loadRecentTasks = async () => {
  loadingTasks.value = true
  try {
    const res = await getTasks({ page: 1, page_size: 8 })
    recentTasks.value = res.items || []
  } catch { } finally { loadingTasks.value = false }
}

const taskStatusType = (s) => ({ pending: 'info', running: 'warning', success: 'success', failed: 'danger', cancelled: 'info' }[s] || 'info')
const taskStatusLabel = (s) => ({ pending: '等待', running: '运行', success: '成功', failed: '失败', cancelled: '取消' }[s] || s || '未知')
const formatTime = (t) => { if (!t) return ''; const d = new Date(t); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` }

onMounted(() => { loadStats(); loadRecentMovies(); loadContinueWatching(); loadRecentTasks() })
</script>

<style scoped>
.home { display: flex; flex-direction: column; gap: 16px; }
.hero-card { border-radius: 12px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%); color: #fff; border: none; }
.hero { display: flex; justify-content: space-between; align-items: center; padding: 16px 8px; flex-wrap: wrap; gap: 20px; }
.hero-text h1 { margin: 0 0 8px; font-size: 24px; color: #fff; }
.hero-text p { margin: 0 0 12px; color: #a5d6ff; font-size: 14px; }
.hero-badges { display: flex; gap: 6px; }
.hero-actions { display: flex; gap: 10px; }

/* 模块卡片网格 */
.module-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.module-card { background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); border-radius: 12px; padding: 16px; cursor: pointer; transition: all .2s; }
.module-card:hover { border-color: var(--el-color-primary); box-shadow: 0 4px 16px rgba(0,0,0,.08); transform: translateY(-2px); }
.module-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.module-card-title { display: flex; align-items: center; gap: 8px; }
.module-card-icon { width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.module-card-name { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
.module-card-status { font-size: 11px; }
.maturity { color: #e6a23c; }
.muted { color: var(--el-text-color-disabled); }
.module-stats { display: flex; gap: 16px; margin-bottom: 12px; }
.module-stat { flex: 1; }
.module-stat-value { font-size: 20px; font-weight: 700; color: var(--el-text-color-primary); }
.module-stat-label { font-size: 11px; color: var(--el-text-color-secondary); }
.module-actions { display: flex; gap: 4px; flex-wrap: wrap; padding-top: 8px; border-top: 1px solid var(--el-border-color-lighter); }

/* 继续观看 */
.horizontal-scroll { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: thin; }
.scroll-card { flex: 0 0 140px; cursor: pointer; border-radius: 8px; overflow: hidden; transition: transform .2s; background: var(--el-bg-color-page); }
.scroll-card:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0,0,0,.15); }
.scroll-cover { position: relative; aspect-ratio: 2/3; overflow: hidden; background: var(--el-fill-color); }
.scroll-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.scroll-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.4); opacity: 0; transition: opacity .25s; color: #fff; }
.scroll-card:hover .scroll-overlay { opacity: 1; }
.scroll-info { padding: 6px 8px; }
.scroll-code { font-size: 12px; font-weight: 700; color: var(--el-color-primary); display: block; }
.scroll-title { font-size: 11px; color: var(--el-text-color-regular); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px; }

/* 最新添加 */
.recent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; }
.recent-card { cursor: pointer; border-radius: 8px; overflow: hidden; transition: transform .2s; background: var(--el-bg-color-page); }
.recent-card:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0,0,0,.12); }
.recent-cover { position: relative; aspect-ratio: 2/3; overflow: hidden; background: var(--el-fill-color); }
.recent-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.recent-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.35); opacity: 0; transition: opacity .25s; color: #fff; }
.recent-card:hover .recent-overlay { opacity: 1; }
.recent-meta { padding: 6px 8px; display: flex; flex-direction: column; gap: 1px; }
.recent-code { font-size: 12px; font-weight: 700; color: var(--el-color-primary); }
.recent-date { font-size: 11px; color: var(--el-text-color-disabled); }

/* 通用 */
.section-card { border-radius: 10px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }

/* 任务 */
.task-list { display: flex; flex-direction: column; gap: 8px; }
.task-item { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.task-item:last-child { border-bottom: none; }
.task-status { flex-shrink: 0; }
.task-info { flex: 1; min-width: 0; }
.task-name { font-size: 13px; font-weight: 500; color: var(--el-text-color-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { font-size: 11px; color: var(--el-text-color-disabled); margin-top: 2px; }

@media (max-width: 800px) { .module-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 500px) { .module-grid { grid-template-columns: 1fr; } }
</style>
