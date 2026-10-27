<template>
  <div class="stats-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <h2 class="page-title">
          <el-icon><DataAnalysis /></el-icon>
          统计总览
        </h2>
        <el-button :loading="loading" @click="loadAll">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </el-card>

    <div v-loading="loading">
      <!-- 顶部指标卡 -->
      <el-row :gutter="12" class="metric-row">
        <el-col :span="4" v-for="m in metricCards" :key="m.label">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-value">{{ m.value }}</div>
            <div class="metric-label">{{ m.label }}</div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="12">
        <!-- 模块分布 -->
        <el-col :span="12">
          <el-card shadow="never" class="block-card">
            <div class="block-title">模块分布（影片 / 演员）</div>
            <div v-for="mod in moduleRows" :key="mod.key" class="bar-row">
              <div class="bar-label">{{ mod.label }}</div>
              <div class="bar-track">
                <div class="bar-fill movies" :style="{ width: mod.mPct + '%' }"></div>
              </div>
              <div class="bar-num">{{ mod.movies }}</div>
              <div class="bar-track actors">
                <div class="bar-fill actors" :style="{ width: mod.aPct + '%' }"></div>
              </div>
              <div class="bar-num actors">{{ mod.actors }}</div>
            </div>
            <el-empty v-if="!moduleRows.length" description="暂无模块数据" />
          </el-card>
        </el-col>

        <!-- 刮削状态分布 -->
        <el-col :span="12">
          <el-card shadow="never" class="block-card">
            <div class="block-title">刮削状态分布</div>
            <div v-for="s in statusRows" :key="s.key" class="bar-row">
              <div class="bar-label">{{ s.label }}</div>
              <div class="bar-track">
                <div class="bar-fill" :class="s.cls" :style="{ width: s.pct + '%' }"></div>
              </div>
              <div class="bar-num">{{ s.value }}</div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="12">
        <!-- 来源 Top10 -->
        <el-col :span="12">
          <el-card shadow="never" class="block-card">
            <div class="block-title">来源 Top 10</div>
            <div v-for="src in sourceRows" :key="src.source" class="bar-row">
              <div class="bar-label" :title="src.source">{{ src.source || '未知' }}</div>
              <div class="bar-track">
                <div class="bar-fill src" :style="{ width: src.pct + '%' }"></div>
              </div>
              <div class="bar-num">{{ src.count }}</div>
            </div>
            <el-empty v-if="!sourceRows.length" description="暂无来源数据" />
          </el-card>
        </el-col>

        <!-- 媒体覆盖 -->
        <el-col :span="12">
          <el-card shadow="never" class="block-card">
            <div class="block-title">元数据覆盖（基于 {{ totalMovies }} 部影片）</div>
            <div v-for="c in coverageRows" :key="c.label" class="bar-row">
              <div class="bar-label">{{ c.label }}</div>
              <div class="bar-track">
                <div class="bar-fill cover" :style="{ width: c.pct + '%' }"></div>
              </div>
              <div class="bar-num">{{ c.count }}（{{ c.pct }}%）</div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 刮削趋势 -->
      <el-card shadow="never" class="block-card">
        <div class="block-title">刮削趋势（近 {{ trendDays }} 天）</div>
        <div v-if="trendPoints.length" class="trend-wrap">
          <svg :viewBox="'0 0 ' + trendW + ' ' + trendH" class="trend-svg" preserveAspectRatio="none">
            <polygon :points="trendArea" class="trend-area" />
            <polyline :points="trendLine" class="trend-line" />
          </svg>
          <div class="trend-axis">
            <span>{{ trendPoints[0]?.date }}</span>
            <span>{{ trendPoints[trendPoints.length - 1]?.date }}</span>
          </div>
          <div class="trend-peak">峰值 {{ trendMax }} 部/天</div>
        </div>
        <el-empty v-else description="近阶段无刮削记录" />
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getDashboardStats, getMovieStats, getStorageStats, getTaskStats } from '@/api'

const loading = ref(true)
const dash = ref({})
const movieStats = ref({})
const storage = ref({})
const taskStats = ref({})

const MODULE_LABELS = {
  jav: 'JAV 有码', fc2: 'FC2', uncensored: 'JAV 无码', chinese: '国产',
  western: '欧美', pornhub: 'PORNHUB', anime: '里番',
}
const trendDays = 30
const trendW = 800
const trendH = 180

async function loadAll() {
  loading.value = true
  try {
    const [d, m, s] = await Promise.all([
      getDashboardStats(), getMovieStats({ days: trendDays }), getStorageStats(),
    ])
    dash.value = d || {}
    movieStats.value = m || {}
    storage.value = s || {}
  } catch (e) {
    // 单个接口失败不阻塞整页
  } finally {
    loading.value = false
  }
}
onMounted(loadAll)

const totalMovies = computed(() => (dash.value.movies?.total) || 0)

const metricCards = computed(() => {
  const d = dash.value
  return [
    { label: '影片总数', value: totalMovies.value },
    { label: '演员总数', value: d.actors?.total || 0 },
    { label: '已刮削', value: d.movies?.completed || 0 },
    { label: '待刮削', value: d.movies?.pending || 0 },
    { label: '刮削失败', value: d.movies?.failed || 0 },
    { label: '任务总数', value: d.tasks?.total || 0 },
  ]
})

const moduleRows = computed(() => {
  const mods = dash.value.modules || {}
  const arr = Object.entries(mods).map(([key, v]) => ({
    key, label: MODULE_LABELS[key] || key, movies: v.movies || 0, actors: v.actors || 0,
  }))
  const maxM = Math.max(1, ...arr.map(a => a.movies))
  const maxA = Math.max(1, ...arr.map(a => a.actors))
  arr.forEach(a => {
    a.mPct = Math.round((a.movies / maxM) * 100)
    a.aPct = Math.round((a.actors / maxA) * 100)
  })
  return arr.sort((x, y) => y.movies - x.movies)
})

const statusRows = computed(() => {
  const m = dash.value.movies || {}
  const max = Math.max(1, m.completed || 0, m.pending || 0, m.failed || 0)
  return [
    { key: 'completed', label: '已完成', value: m.completed || 0, cls: 'movies', pct: Math.round(((m.completed || 0) / max) * 100) },
    { key: 'pending', label: '待刮削', value: m.pending || 0, cls: 'src', pct: Math.round(((m.pending || 0) / max) * 100) },
    { key: 'failed', label: '失败', value: m.failed || 0, cls: 'flag', pct: Math.round(((m.failed || 0) / max) * 100) },
  ]
})

const sourceRows = computed(() => {
  const list = movieStats.value.source_distribution || []
  const max = Math.max(1, ...list.map(s => s.count))
  return list.map(s => ({ ...s, pct: Math.round((s.count / max) * 100) }))
})

const coverageRows = computed(() => {
  const total = totalMovies.value || 1
  const s = storage.value || {}
  const items = [
    { label: '有封面图', count: s.images?.with_cover || 0 },
    { label: '有海报', count: s.images?.with_poster || 0 },
    { label: '有简介', count: s.metadata?.with_plot || 0 },
    { label: '有演员', count: s.metadata?.with_actors || 0 },
  ]
  return items.map(c => ({ ...c, pct: Math.round((c.count / total) * 100) }))
})

const trendPoints = computed(() => movieStats.value.scraping_trend || [])
const trendMax = computed(() => Math.max(1, ...trendPoints.value.map(p => p.count)))
const trendLine = computed(() => {
  const pts = trendPoints.value
  if (!pts.length) return ''
  const stepX = trendW / Math.max(1, pts.length - 1)
  return pts.map((p, i) => `${(i * stepX).toFixed(1)},${(trendH - (p.count / trendMax.value) * (trendH - 10) - 5).toFixed(1)}`).join(' ')
})
const trendArea = computed(() => {
  if (!trendLine.value) return ''
  return `0,${trendH} ${trendLine.value} ${trendW},${trendH}`
})
</script>

<style scoped>
.stats-page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; }
.page-title { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 18px; }
.metric-row { margin-bottom: 12px; }
.metric-card { text-align: center; }
.metric-value { font-size: 26px; font-weight: 700; }
.metric-label { font-size: 12px; opacity: 0.7; margin-top: 4px; }
.block-card { margin-bottom: 12px; }
.block-title { font-weight: 600; margin-bottom: 12px; font-size: 14px; }
.bar-row { display: grid; grid-template-columns: 110px 1fr 70px; gap: 8px; align-items: center; margin-bottom: 8px; }
.bar-label { font-size: 12px; opacity: 0.85; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { height: 14px; background: rgba(125,125,125,0.18); border-radius: 7px; overflow: hidden; }
.bar-track.actors { margin-top: 3px; }
.bar-fill { height: 100%; border-radius: 7px; min-width: 2px; transition: width .4s; }
.bar-fill.movies { background: linear-gradient(90deg,#409eff,#79bbff); }
.bar-fill.actors { background: linear-gradient(90deg,#a855f7,#c084fc); }
.bar-fill.src { background: linear-gradient(90deg,#10b981,#34d399); }
.bar-fill.cover { background: linear-gradient(90deg,#f59e0b,#fbbf24); }
.bar-fill.flag { background: linear-gradient(90deg,#ef4444,#f87171); }
.bar-num { font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; }
.bar-num.actors { color: #c084fc; }
.trend-wrap { position: relative; }
.trend-svg { width: 100%; height: 180px; display: block; }
.trend-area { fill: rgba(64,158,255,0.18); }
.trend-line { fill: none; stroke: #409eff; stroke-width: 2; }
.trend-axis { display: flex; justify-content: space-between; font-size: 11px; opacity: 0.6; margin-top: 4px; }
.trend-peak { position: absolute; top: 0; right: 0; font-size: 12px; color: #409eff; }
</style>
