<template>
  <div class="home">
    <!-- 欢迎横幅 -->
    <el-card class="hero-card" shadow="never">
      <div class="hero">
        <div class="hero-text">
          <h1>龙魂视频管理系统</h1>
          <p>多源刮削聚合 · 54+ 站点 · 智能合并 · 完整工作流</p>
        </div>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="$router.push('/movies')">
            <el-icon><VideoCamera /></el-icon>
            番号库
          </el-button>
          <el-button size="large" @click="$router.push('/crawlers')">
            <el-icon><Connection /></el-icon>
            多源管理
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon" style="background: linear-gradient(135deg, #409eff, #66b1ff)">
              <el-icon size="26"><VideoCamera /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.movies?.total || 0 }}</div>
              <div class="stat-label">番号总数</div>
              <div class="stat-sub" v-if="stats.movies?.completed">
                已刮削 {{ stats.movies.completed }}
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon" style="background: linear-gradient(135deg, #67c23a, #85ce61)">
              <el-icon size="26"><User /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.actors?.total || 0 }}</div>
              <div class="stat-label">演员数量</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon" style="background: linear-gradient(135deg, #e6a23c, #ebb563)">
              <el-icon size="26"><PriceTag /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.tags?.total || tagCount }}</div>
              <div class="stat-label">标签数量</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon" style="background: linear-gradient(135deg, #f56c6c, #f78989)">
              <el-icon size="26"><Connection /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.crawlers?.total || crawlerCount }}</div>
              <div class="stat-label">爬虫数量</div>
              <div class="stat-sub" v-if="stats.crawlers?.enabled">
                启用 {{ stats.crawlers.enabled }}
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 多模块统计 -->
    <el-row :gutter="12" class="module-stats-row" v-if="stats.modules && Object.keys(stats.modules).length">
      <el-col :xs="6" :sm="3" v-for="(m, key) in stats.modules" :key="key">
        <div class="module-stat-item" @click="$router.push(moduleStatRoutes[key] || '/')">
          <div class="module-stat-name">{{ moduleStatLabels[key] || key }}</div>
          <div class="module-stat-num">{{ m.movies || 0 }}</div>
          <div class="module-stat-sub">影片 / {{ m.actors || 0 }} 演员</div>
        </div>
      </el-col>
    </el-row>

    <!-- 继续观看（最近播放） -->
    <el-card shadow="never" class="content-card" v-if="continueWatching.length">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><VideoPlay /></el-icon>
            继续观看
          </span>
          <el-button text @click="$router.push('/movies?sort=-last_played_at')">
            查看全部 <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </template>
      <div class="continue-row">
        <div
          v-for="item in continueWatching"
          :key="item.id"
          class="continue-card"
          @click="$router.push(`/movie/${item.id}`)"
        >
          <div class="continue-cover">
            <img :src="getMovieCoverUrl(item)" :alt="item.code" @error="handleCoverError">
            <div class="continue-overlay">
              <el-icon size="28"><VideoPlay /></el-icon>
            </div>
          </div>
          <div class="continue-info">
            <span class="continue-code">{{ item.code }}</span>
            <span class="continue-title">{{ item.title || '未命名' }}</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 中部内容 -->
    <el-row :gutter="16" class="content-row">
      <el-col :xs="24" :lg="16">
        <el-card shadow="never" class="content-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon><Clock /></el-icon>
                最新添加
              </span>
              <el-button text @click="$router.push('/movies')">
                查看全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <div v-loading="loadingMovies" class="recent-grid">
            <div
              v-for="item in recentMovies"
              :key="item.id"
              class="recent-card"
              @click="$router.push(`/movie/${item.id}`)"
            >
              <div class="recent-cover">
                <img :src="getMovieCoverUrl(item)" :alt="item.code" @error="handleCoverError">
                <div class="recent-overlay">
                  <el-icon size="28"><VideoPlay /></el-icon>
                </div>
              </div>
              <div class="recent-meta">
                <span class="recent-code">{{ item.code }}</span>
                <span class="recent-date" v-if="item.release_date">{{ item.release_date }}</span>
                <span class="recent-rating" v-if="item.rating">
                  <span class="stars">★</span>{{ Number(item.rating).toFixed(1) }}
                </span>
              </div>
            </div>
            <el-empty v-if="!loadingMovies && !recentMovies.length" description="暂无数据" />
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="8">
        <el-card shadow="never" class="content-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon><List /></el-icon>
                最近任务
              </span>
              <el-button text @click="$router.push('/tasks')">
                全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <div v-loading="loadingTasks" class="task-list">
            <div v-for="task in recentTasks" :key="task.id" class="task-item">
              <div class="task-status">
                <el-tag :type="taskStatusType(task.status)" size="small" effect="dark">
                  {{ taskStatusLabel(task.status) }}
                </el-tag>
              </div>
              <div class="task-info">
                <div class="task-name">{{ task.name || task.type || '任务' }}</div>
                <div class="task-meta">
                  <span v-if="task.progress !== undefined">{{ task.progress }}%</span>
                  <span v-if="task.created_at">{{ formatTime(task.created_at) }}</span>
                </div>
              </div>
            </div>
            <el-empty v-if="!loadingTasks && !recentTasks.length" description="暂无任务" :image-size="60" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷操作 -->
    <el-card shadow="never" class="quick-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><Operation /></el-icon>
            快捷操作
          </span>
        </div>
      </template>
      <div class="quick-grid">
        <div class="quick-item" @click="$router.push('/movies')">
          <div class="quick-icon" style="background: #409eff">
            <el-icon size="24"><VideoCamera /></el-icon>
          </div>
          <div class="quick-text">番号库</div>
        </div>
        <div class="quick-item" @click="$router.push('/actors')">
          <div class="quick-icon" style="background: #67c23a">
            <el-icon size="24"><User /></el-icon>
          </div>
          <div class="quick-text">演员库</div>
        </div>
        <div class="quick-item" @click="$router.push('/crawlers')">
          <div class="quick-icon" style="background: #e6a23c">
            <el-icon size="24"><Connection /></el-icon>
          </div>
          <div class="quick-text">爬虫管理</div>
        </div>
        <div class="quick-item" @click="$router.push('/compare')">
          <div class="quick-icon" style="background: #f56c6c">
            <el-icon size="24"><DataAnalysis /></el-icon>
          </div>
          <div class="quick-text">本地对比</div>
        </div>
        <div class="quick-item" @click="$router.push('/favorites')">
          <div class="quick-icon" style="background: #f7ba2a">
            <el-icon size="24"><Star /></el-icon>
          </div>
          <div class="quick-text">收藏夹</div>
        </div>
        <div class="quick-item" @click="$router.push('/patch')">
          <div class="quick-icon" style="background: #9c27b0">
            <el-icon size="24"><MagicStick /></el-icon>
          </div>
          <div class="quick-text">补刮管理</div>
        </div>
        <div class="quick-item" @click="$router.push('/tags')">
          <div class="quick-icon" style="background: #00bcd4">
            <el-icon size="24"><PriceTag /></el-icon>
          </div>
          <div class="quick-text">标签管理</div>
        </div>
        <div class="quick-item" @click="$router.push('/tasks')">
          <div class="quick-icon" style="background: #ff5722">
            <el-icon size="24"><List /></el-icon>
          </div>
          <div class="quick-text">任务管理</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  VideoCamera, User, PriceTag, Connection, DataAnalysis, Star,
  CopyDocument, Clock, ArrowRight, VideoPlay, List, Operation, MagicStick
} from '@element-plus/icons-vue'
import { getMovies, getDashboardStats, getTasks, getCrawlers, getTags } from '@/api'
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

const moduleStatLabels = { chinese: '国产', uncensored: '无码', fc2: 'FC2', pornhub: 'PORNHub' }
const moduleStatRoutes = { chinese: '/chinese', uncensored: '/uncensored', fc2: '/fc2', pornhub: '/pornhub' }

const handleCoverError = (event) => {
  event.target.src = defaultCover(event.target.alt)
}

const loadStats = async () => {
  try {
    const res = await getDashboardStats()
    stats.value = res || {}
    if (!res.tags) {
      getTags({ page: 1, page_size: 1 }).then(r => {
        tagCount.value = r.total || 0
      }).catch(() => {})
    }
    if (!res.crawlers) {
      getCrawlers().then(r => {
        const list = r.items || r || []
        crawlerCount.value = list.length
      }).catch(() => {})
    }
  } catch (e) {
    console.error('加载统计失败:', e)
  }
}

const loadRecentMovies = async () => {
  loadingMovies.value = true
  try {
    const res = await getMovies({ page: 1, page_size: 12 })
    recentMovies.value = res.items || []
  } catch (e) {
    console.error(e)
  } finally {
    loadingMovies.value = false
  }
}

const loadContinueWatching = async () => {
  try {
    const res = await getMovies({ page: 1, page_size: 6, sort: '-last_played_at' })
    continueWatching.value = (res.items || []).filter(m => m.last_played_at)
  } catch (e) {
    console.error(e)
  }
}

const loadRecentTasks = async () => {
  loadingTasks.value = true
  try {
    const res = await getTasks({ page: 1, page_size: 8 })
    recentTasks.value = res.items || []
  } catch (e) {
    console.error(e)
  } finally {
    loadingTasks.value = false
  }
}

const taskStatusType = (s) => ({
  pending: 'info',
  running: 'warning',
  success: 'success',
  failed: 'danger',
  cancelled: 'info'
}[s] || 'info')

const taskStatusLabel = (s) => ({
  pending: '等待',
  running: '运行',
  success: '成功',
  failed: '失败',
  cancelled: '取消'
}[s] || s || '未知')

const formatTime = (t) => {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(() => {
  loadStats()
  loadRecentMovies()
  loadContinueWatching()
  loadRecentTasks()
})
</script>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hero-card {
  border-radius: 12px;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
  color: #fff;
  border: none;
}

.hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 8px;
  flex-wrap: wrap;
  gap: 20px;
}

.hero-text h1 {
  margin: 0 0 8px;
  font-size: 24px;
  color: #fff;
}

.hero-text p {
  margin: 0;
  color: #a5d6ff;
  font-size: 14px;
}

.hero-actions {
  display: flex;
  gap: 10px;
}

.stats-row {
  margin-bottom: 0;
}

.stat-card {
  border-radius: 10px;
  border: none;
}

.stat-inner {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-info {
  min-width: 0;
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--el-text-color-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.stat-sub {
  font-size: 12px;
  color: var(--el-text-color-disabled);
  margin-top: 1px;
}

.content-card {
  border-radius: 10px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 15px;
}

/* 继续观看 */
.continue-row {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
  scrollbar-width: thin;
}

.continue-card {
  flex: 0 0 140px;
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  transition: transform .2s, box-shadow .2s;
  background: var(--el-bg-color-page);
}

.continue-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 16px rgba(0,0,0,.15);
}

.continue-cover {
  position: relative;
  aspect-ratio: 2/3;
  overflow: hidden;
  background: var(--el-fill-color);
}

.continue-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.continue-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,.4);
  opacity: 0;
  transition: opacity .25s;
  color: #fff;
}

.continue-card:hover .continue-overlay {
  opacity: 1;
}

.continue-info {
  padding: 6px 8px;
}

.continue-code {
  font-size: 12px;
  font-weight: 700;
  color: var(--el-color-primary);
  display: block;
}

.continue-title {
  font-size: 11px;
  color: var(--el-text-color-regular);
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 2px;
}

/* 最新添加网格 */
.recent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 10px;
}

.recent-card {
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  transition: transform .2s, box-shadow .2s;
  background: var(--el-bg-color-page);
}

.recent-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 16px rgba(0,0,0,.12);
}

.recent-cover {
  position: relative;
  aspect-ratio: 2/3;
  overflow: hidden;
  background: var(--el-fill-color);
}

.recent-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.recent-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,.35);
  opacity: 0;
  transition: opacity .25s;
  color: #fff;
}

.recent-card:hover .recent-overlay {
  opacity: 1;
}

.recent-meta {
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.recent-code {
  font-size: 12px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.recent-date {
  font-size: 11px;
  color: var(--el-text-color-disabled);
}

.recent-rating {
  font-size: 11px;
  color: #e6a23c;
}

.stars {
  letter-spacing: 1px;
}

/* 中部区域 */
.content-row {
  margin-bottom: 0;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.task-item:last-child {
  border-bottom: none;
}

.task-status {
  flex-shrink: 0;
  padding-top: 2px;
}

.task-info {
  flex: 1;
  min-width: 0;
}

.task-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-meta {
  font-size: 11px;
  color: var(--el-text-color-disabled);
  margin-top: 2px;
  display: flex;
  gap: 8px;
}

/* 快捷操作 */
.quick-card {
  border-radius: 10px;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 12px;
}

.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 14px 8px;
  cursor: pointer;
  border-radius: 10px;
  transition: background .2s, transform .2s;
}

.quick-item:hover {
  background: var(--el-fill-color-light);
  transform: translateY(-2px);
}

.quick-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.quick-text {
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-regular);
}

/* ===== 多模块统计 ===== */
.module-stats-row {
  margin: 0;
}
.module-stat-item {
  text-align: center;
  padding: 12px 8px;
  cursor: pointer;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  transition: all 0.2s;
  background: var(--el-bg-color);
}
.module-stat-item:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  transform: translateY(-1px);
}
.module-stat-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.module-stat-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--el-color-primary);
}
.module-stat-sub {
  font-size: 11px;
  color: var(--el-text-color-disabled);
  margin-top: 2px;
}
</style>
