<template>
  <div class="status-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>系统状态 / 统计中心</h2>
      <p class="subtitle">实时掌握服务器健康、影片/任务/存储分布与刮削活跃度</p>
    </div>

    <!-- 健康探针 -->
    <el-card shadow="never" class="block-card">
      <template #header>
        <div class="block-title">
          <span>服务健康检查</span>
          <el-button text size="small" @click="loadData" :loading="loading">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <el-row :gutter="16">
        <el-col :span="6">
          <div class="health-item">
            <div class="health-dot" :class="dbHealthy ? 'ok' : 'err'"></div>
            <div>
              <div class="health-name">数据库连接</div>
              <div class="health-state" :class="dbHealthy ? 'text-ok' : 'text-err'">
                {{ dbHealthy ? '正常' : '异常' }}
              </div>
            </div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="health-item">
            <div class="health-dot" :class="probe('live')"></div>
            <div>
              <div class="health-name">存活探针 (liveness)</div>
              <div class="health-state" :class="probeClass('live')">{{ probeText('live') }}</div>
            </div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="health-item">
            <div class="health-dot" :class="probe('ready')"></div>
            <div>
              <div class="health-name">就绪探针 (readiness)</div>
              <div class="health-state" :class="probeClass('ready')">{{ probeText('ready') }}</div>
            </div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="health-item">
            <div class="health-dot" :class="probe('health')"></div>
            <div>
              <div class="health-name">基础健康</div>
              <div class="health-state" :class="probeClass('health')">{{ probeText('health') }}</div>
            </div>
          </div>
        </el-col>
      </el-row>
      <el-divider />
      <div class="error-rate">
        <span>近 24 小时任务错误率：</span>
        <el-tag :type="errorRateTag" size="small">{{ errorRateText }}</el-tag>
        <span class="muted">（失败 {{ health.tasks.recent_failed }} 个）</span>
      </div>
    </el-card>

    <!-- 影片统计 -->
    <el-card shadow="never" class="block-card">
      <template #header><span class="block-title">影片概览</span></template>
      <el-row :gutter="16" class="stat-row">
        <el-col :span="6"><div class="mini-stat"><div class="ms-value">{{ dash.movies.total }}</div><div class="ms-label">影片总数</div></div></el-col>
        <el-col :span="6"><div class="mini-stat ok"><div class="ms-value">{{ dash.movies.completed }}</div><div class="ms-label">已完成</div></div></el-col>
        <el-col :span="6"><div class="mini-stat warn"><div class="ms-value">{{ dash.movies.pending }}</div><div class="ms-label">待处理</div></div></el-col>
        <el-col :span="6"><div class="mini-stat err"><div class="ms-value">{{ dash.movies.failed }}</div><div class="ms-label">失败</div></div></el-col>
      </el-row>
      <div class="bar-title">按状态分布</div>
      <div class="bars">
        <div v-for="(count, st) in movieStats.status_distribution" :key="st" class="bar-row">
          <span class="bar-label">{{ st || '未知' }}</span>
          <div class="bar-track">
            <div class="bar-fill" :class="statusColor(st)" :style="{ width: pct(count, maxStatus) }"></div>
          </div>
          <span class="bar-count">{{ count }}</span>
        </div>
      </div>
    </el-card>

    <!-- 任务 & 刮削活跃度 -->
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" class="block-card">
          <template #header><span class="block-title">任务统计</span></template>
          <el-row :gutter="16" class="stat-row">
            <el-col :span="6"><div class="mini-stat"><div class="ms-value">{{ dash.tasks.total }}</div><div class="ms-label">任务总数</div></div></el-col>
            <el-col :span="6"><div class="mini-stat ok"><div class="ms-value">{{ dash.tasks.running }}</div><div class="ms-label">运行中</div></div></el-col>
            <el-col :span="6"><div class="mini-stat warn"><div class="ms-value">{{ dash.tasks.pending }}</div><div class="ms-label">排队</div></div></el-col>
            <el-col :span="6"><div class="mini-stat err"><div class="ms-value">{{ dash.tasks.failed }}</div><div class="ms-label">失败</div></div></el-col>
          </el-row>
          <div class="bar-title">按类型分布</div>
          <div class="bars">
            <div v-for="(count, t) in taskStats.type_distribution" :key="t" class="bar-row">
              <span class="bar-label">{{ t || '未知' }}</span>
              <div class="bar-track">
                <div class="bar-fill" :class="statusColor(t)" :style="{ width: pct(count, maxTaskType) }"></div>
              </div>
              <span class="bar-count">{{ count }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" class="block-card">
          <template #header><span class="block-title">刮削活跃度</span></template>
          <el-row :gutter="16" class="stat-row">
            <el-col :span="12"><div class="mini-stat"><div class="ms-value">{{ dash.activity.today_scraped }}</div><div class="ms-label">今日刮削</div></div></el-col>
            <el-col :span="12"><div class="mini-stat"><div class="ms-value">{{ dash.activity.recent_scraped }}</div><div class="ms-label">近 7 天刮削</div></div></el-col>
          </el-row>
          <div class="bar-title">近 30 天刮削趋势</div>
          <div class="spark">
            <div
              v-for="(p, i) in trendBars"
              :key="i"
              class="spark-bar"
              :style="{ height: p.h + '%' }"
              :title="`${p.date}: ${p.count}`"
            ></div>
            <el-empty v-if="!trendBars.length" description="暂无趋势数据" :image-size="60" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 存储统计 -->
    <el-card shadow="never" class="block-card">
      <template #header><span class="block-title">元数据覆盖度</span></template>
      <el-row :gutter="16" class="stat-row">
        <el-col :span="6"><div class="mini-stat"><div class="ms-value">{{ storage.images.with_cover }}</div><div class="ms-label">有封面</div></div></el-col>
        <el-col :span="6"><div class="mini-stat"><div class="ms-value">{{ storage.images.with_poster }}</div><div class="ms-label">有海报</div></div></el-col>
        <el-col :span="6"><div class="mini-stat"><div class="ms-value">{{ storage.metadata.with_plot }}</div><div class="ms-label">有简介</div></div></el-col>
        <el-col :span="6"><div class="mini-stat"><div class="ms-value">{{ storage.metadata.with_actors }}</div><div class="ms-label">已关联演员</div></div></el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import {
  getDashboardStats, getMovieStats, getTaskStats, getStorageStats,
  getSystemHealth, healthCheck, readinessCheck, livenessCheck
} from '@/api'

const loading = ref(false)
let timer = null

const dash = reactive({
  movies: { total: 0, completed: 0, pending: 0, failed: 0 },
  tasks: { total: 0, running: 0, pending: 0, failed: 0 },
  actors: { total: 0 },
  activity: { recent_scraped: 0, today_scraped: 0 }
})
const movieStats = reactive({ status_distribution: {}, source_distribution: [], scraping_trend: [] })
const taskStats = reactive({ type_distribution: {}, status_distribution: {}, task_trend: [] })
const storage = reactive({ images: { with_cover: 0, with_poster: 0 }, metadata: { with_plot: 0, with_actors: 0 } })
const health = reactive({ database: { healthy: false }, tasks: { error_rate: 0, recent_failed: 0 } })

const probes = reactive({ live: 'unknown', ready: 'unknown', health: 'unknown' })

const dbHealthy = computed(() => health.database.healthy)
const maxStatus = computed(() => Math.max(1, ...Object.values(movieStats.status_distribution)))
const maxTaskType = computed(() => Math.max(1, ...Object.values(taskStats.type_distribution)))
const trendBars = computed(() => {
  const trend = movieStats.scraping_trend || []
  const max = Math.max(1, ...trend.map(t => t.count))
  return trend.map(t => ({ date: t.date, count: t.count, h: Math.round((t.count / max) * 100) }))
})
const errorRateText = computed(() => (health.tasks.error_rate * 100).toFixed(1) + '%')
const errorRateTag = computed(() => {
  const r = health.tasks.error_rate
  if (r === 0) return 'success'
  if (r < 0.1) return 'warning'
  return 'danger'
})

function probe(key) {
  return probes[key] === 'ok' ? 'ok' : probes[key] === 'err' ? 'err' : 'unknown'
}
function probeClass(key) {
  return probes[key] === 'ok' ? 'text-ok' : probes[key] === 'err' ? 'text-err' : 'text-muted'
}
function probeText(key) {
  return probes[key] === 'ok' ? '正常' : probes[key] === 'err' ? '异常' : '未知'
}
function statusColor(st) {
  if (st === 'completed' || st === 'success' || st === 'running') return 'ok'
  if (st === 'pending' || st === 'warning') return 'warn'
  if (st === 'failed' || st === 'error') return 'err'
  return 'neutral'
}
function pct(v, max) {
  return Math.round((v / max) * 100) + '%'
}

async function loadProbes() {
  const checks = [
    ['health', healthCheck()],
    ['ready', readinessCheck()],
    ['live', livenessCheck()]
  ]
  for (const [key, p] of checks) {
    try {
      await p
      probes[key] = 'ok'
    } catch (e) {
      probes[key] = e?.response ? 'err' : 'unknown'
    }
  }
}

async function loadData() {
  loading.value = true
  try {
    const [d, m, t, s, h] = await Promise.all([
      getDashboardStats(),
      getMovieStats(),
      getTaskStats(),
      getStorageStats(),
      getSystemHealth()
    ])
    if (d) {
      Object.assign(dash.movies, d.movies || {})
      Object.assign(dash.tasks, d.tasks || {})
      dash.actors.total = d.actors?.total || 0
      Object.assign(dash.activity, d.activity || {})
    }
    if (m) {
      movieStats.status_distribution = m.status_distribution || {}
      movieStats.source_distribution = m.source_distribution || []
      movieStats.scraping_trend = m.scraping_trend || []
    }
    if (t) {
      taskStats.type_distribution = t.type_distribution || {}
      taskStats.status_distribution = t.status_distribution || {}
      taskStats.task_trend = t.task_trend || []
    }
    if (s) {
      Object.assign(storage.images, s.images || {})
      Object.assign(storage.metadata, s.metadata || {})
    }
    if (h) {
      health.database.healthy = h.database?.healthy || false
      health.tasks.error_rate = h.tasks?.error_rate || 0
      health.tasks.recent_failed = h.tasks?.recent_failed || 0
    }
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  loadProbes()
}

onMounted(() => {
  loadData()
  timer = setInterval(loadData, 30000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.status-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.subtitle {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.block-card {
  margin-bottom: 16px;
}

.block-title {
  font-weight: 600;
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.health-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.health-dot.ok { background: #67c23a; box-shadow: 0 0 8px rgba(103,194,58,.6); }
.health-dot.err { background: #f56c6c; box-shadow: 0 0 8px rgba(245,108,108,.6); }
.health-dot.unknown { background: #c0c4cc; }

.health-name {
  font-size: 13px;
  color: #606266;
}

.health-state {
  font-size: 15px;
  font-weight: 600;
}

.text-ok { color: #67c23a; }
.text-err { color: #f56c6c; }
.text-muted { color: #c0c4cc; }

.error-rate {
  font-size: 13px;
  color: #606266;
}

.muted { color: #909399; }

.stat-row {
  margin-bottom: 8px;
}

.mini-stat {
  text-align: center;
  padding: 14px 0;
  border-radius: 10px;
  background: var(--el-fill-color-light, #f5f7fa);
}

.mini-stat.ok { background: rgba(103,194,58,.1); }
.mini-stat.warn { background: rgba(230,162,60,.12); }
.mini-stat.err { background: rgba(245,108,108,.1); }

.ms-value {
  font-size: 26px;
  font-weight: 700;
  color: #303133;
}

.mini-stat.ok .ms-value { color: #67c23a; }
.mini-stat.warn .ms-value { color: #e6a23c; }
.mini-stat.err .ms-value { color: #f56c6c; }

.ms-label {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}

.bar-title {
  font-size: 13px;
  color: #606266;
  margin: 16px 0 10px;
}

.bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bar-label {
  width: 90px;
  font-size: 12px;
  color: #606266;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bar-track {
  flex: 1;
  height: 14px;
  background: var(--el-fill-color-light, #f0f2f5);
  border-radius: 7px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 7px;
  transition: width .4s;
  background: #409eff;
}

.bar-fill.ok { background: #67c23a; }
.bar-fill.warn { background: #e6a23c; }
.bar-fill.err { background: #f56c6c; }
.bar-fill.neutral { background: #909399; }

.bar-count {
  width: 50px;
  font-size: 12px;
  color: #909399;
  text-align: left;
}

.spark {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 120px;
  padding: 8px 0;
}

.spark-bar {
  flex: 1;
  background: linear-gradient(180deg, #409eff 0%, #6a5acd 100%);
  border-radius: 3px 3px 0 0;
  min-height: 2px;
  transition: height .4s;
}

.spark-bar:hover {
  background: #409eff;
}
</style>
