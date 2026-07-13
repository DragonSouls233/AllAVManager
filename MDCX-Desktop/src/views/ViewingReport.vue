<template>
  <div class="viewing-report-page">
    <!-- 顶部 -->
    <el-card shadow="never" class="header-card">
      <div class="header">
        <h2 class="page-title">
          <el-icon><DataAnalysis /></el-icon>
          AI 观影报告
        </h2>
        <div class="period-selector">
          <el-radio-group v-model="period" @change="loadReport">
            <el-radio-button :value="7">近7天</el-radio-button>
            <el-radio-button :value="30">近30天</el-radio-button>
            <el-radio-button :value="90">近90天</el-radio-button>
            <el-radio-button :value="365">近1年</el-radio-button>
          </el-radio-group>
          <el-button :loading="loading" @click="loadReport">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <div v-loading="loading">
      <!-- 概要卡片 -->
      <div class="summary-grid" v-if="report">
        <div class="summary-card">
          <div class="summary-icon" style="background: rgba(64, 158, 255, 0.15); color: #409eff">
            <el-icon size="24"><VideoPlay /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ report.summary.play_count }}</div>
            <div class="summary-label">播放次数</div>
          </div>
        </div>
        <div class="summary-card">
          <div class="summary-icon" style="background: rgba(103, 194, 58, 0.15); color: #67c23a">
            <el-icon size="24"><Clock /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ report.summary.total_duration_human }}</div>
            <div class="summary-label">总观看时长</div>
          </div>
        </div>
        <div class="summary-card">
          <div class="summary-icon" style="background: rgba(230, 162, 60, 0.15); color: #e6a23c">
            <el-icon size="24"><Film /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ report.summary.unique_movies }}</div>
            <div class="summary-label">观看影片数</div>
          </div>
        </div>
        <div class="summary-card">
          <div class="summary-icon" style="background: rgba(245, 108, 108, 0.15); color: #f56c6c">
            <el-icon size="24"><CircleCheck /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ (report.summary.completion_rate * 100).toFixed(0) }}%</div>
            <div class="summary-label">完播率（{{ report.summary.completed_count }} 次）</div>
          </div>
        </div>
        <div class="summary-card">
          <div class="summary-icon" style="background: rgba(144, 147, 153, 0.15); color: #909399">
            <el-icon size="24"><TrendCharts /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ (report.summary.avg_progress * 100).toFixed(0) }}%</div>
            <div class="summary-label">平均观看进度</div>
          </div>
        </div>
      </div>

      <!-- AI 洞察 -->
      <el-card shadow="never" class="insights-card" v-if="report && report.insights">
        <template #header>
          <span class="card-title">
            <el-icon><MagicStick /></el-icon>
            AI 洞察分析
          </span>
        </template>
        <div class="insights-list">
          <div v-for="(insight, i) in report.insights" :key="i" class="insight-item">
            <el-icon class="insight-bullet"><Star /></el-icon>
            <span>{{ insight }}</span>
          </div>
          <el-empty v-if="!report.insights.length" :image-size="60" description="暂无洞察数据" />
        </div>
      </el-card>

      <!-- Top 排行 -->
      <div class="rank-grid" v-if="report">
        <el-card shadow="never" class="rank-card">
          <template #header>
            <span class="card-title"><el-icon><User /></el-icon> 热门演员 Top 10</span>
          </template>
          <div class="rank-list">
            <div v-for="(item, i) in report.top_actors" :key="i" class="rank-item">
              <span class="rank-no">{{ i + 1 }}</span>
              <span class="rank-name">{{ item.name }}</span>
              <div class="rank-bar-wrap">
                <div class="rank-bar" :style="{ width: barWidth(item.play_count, report.top_actors[0]?.play_count) }"></div>
              </div>
              <span class="rank-count">{{ item.play_count }} 次</span>
            </div>
            <el-empty v-if="!report.top_actors.length" :image-size="50" description="暂无数据" />
          </div>
        </el-card>

        <el-card shadow="never" class="rank-card">
          <template #header>
            <span class="card-title"><el-icon><PriceTag /></el-icon> 热门标签 Top 15</span>
          </template>
          <div class="rank-list">
            <div v-for="(item, i) in report.top_tags" :key="i" class="rank-item">
              <span class="rank-no">{{ i + 1 }}</span>
              <el-tag
                size="small"
                effect="plain"
                :class="item.is_user ? 'tag-user' : 'tag-crawler'"
              >{{ item.name }}</el-tag>
              <div class="rank-bar-wrap">
                <div
                  class="rank-bar"
                  :class="item.is_user ? 'bar-user' : 'bar-crawler'"
                  :style="{ width: barWidth(item.play_count, report.top_tags[0]?.play_count) }"
                ></div>
              </div>
              <span class="rank-count">{{ item.play_count }} 次</span>
            </div>
            <el-empty v-if="!report.top_tags.length" :image-size="50" description="暂无数据" />
          </div>
        </el-card>

        <el-card shadow="never" class="rank-card">
          <template #header>
            <span class="card-title"><el-icon><Collection /></el-icon> 热门系列 Top 10</span>
          </template>
          <div class="rank-list">
            <div v-for="(item, i) in report.top_series" :key="i" class="rank-item">
              <span class="rank-no">{{ i + 1 }}</span>
              <span class="rank-name">{{ item.name }}</span>
              <div class="rank-bar-wrap">
                <div class="rank-bar bar-series" :style="{ width: barWidth(item.play_count, report.top_series[0]?.play_count) }"></div>
              </div>
              <span class="rank-count">{{ item.play_count }} 次</span>
            </div>
            <el-empty v-if="!report.top_series.length" :image-size="50" description="暂无数据" />
          </div>
        </el-card>

        <el-card shadow="never" class="rank-card">
          <template #header>
            <span class="card-title"><el-icon><OfficeBuilding /></el-icon> 热门厂商 Top 10</span>
          </template>
          <div class="rank-list">
            <div v-for="(item, i) in report.top_studios" :key="i" class="rank-item">
              <span class="rank-no">{{ i + 1 }}</span>
              <span class="rank-name">{{ item.name }}</span>
              <div class="rank-bar-wrap">
                <div class="rank-bar bar-studio" :style="{ width: barWidth(item.play_count, report.top_studios[0]?.play_count) }"></div>
              </div>
              <span class="rank-count">{{ item.play_count }} 次</span>
            </div>
            <el-empty v-if="!report.top_studios.length" :image-size="50" description="暂无数据" />
          </div>
        </el-card>
      </div>

      <!-- 时间分布 -->
      <div class="dist-grid" v-if="report">
        <el-card shadow="never" class="dist-card">
          <template #header>
            <span class="card-title"><el-icon><Clock /></el-icon> 每小时观看分布</span>
          </template>
          <div class="hour-chart">
            <div
              v-for="(cnt, hour) in report.time_distribution.by_hour"
              :key="hour"
              class="hour-bar-wrap"
            >
              <div class="hour-bar" :style="{ height: barHeight(cnt, maxHourCount) }"></div>
              <span class="hour-label">{{ hour }}</span>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="dist-card">
          <template #header>
            <span class="card-title"><el-icon><Calendar /></el-icon> 每周观看分布</span>
          </template>
          <div class="weekday-chart">
            <div
              v-for="(cnt, wd) in report.time_distribution.by_weekday"
              :key="wd"
              class="weekday-bar-wrap"
            >
              <div class="weekday-bar" :style="{ height: barHeight(cnt, maxWeekdayCount) }"></div>
              <span class="weekday-label">{{ weekdayName(wd) }}</span>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 每日趋势 -->
      <el-card shadow="never" class="trend-card" v-if="report">
        <template #header>
          <span class="card-title"><el-icon><TrendCharts /></el-icon> 每日观看趋势</span>
        </template>
        <div class="trend-chart" v-if="report.daily_trend.length">
          <div class="trend-area">
            <svg :viewBox="`0 0 ${report.daily_trend.length * 8 + 40} 100`" preserveAspectRatio="none" class="trend-svg">
              <polyline
                :points="trendPoints"
                fill="none"
                stroke="#409eff"
                stroke-width="1.5"
              />
              <polygon
                :points="trendPoints + `, ${report.daily_trend.length * 8 + 40},100 0,100`"
                fill="url(#trendGradient)"
                opacity="0.3"
              />
              <defs>
                <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#409eff" />
                  <stop offset="100%" stop-color="#409eff" stop-opacity="0" />
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div class="trend-labels">
            <span>{{ report.daily_trend[0]?.date }}</span>
            <span>{{ report.daily_trend[report.daily_trend.length - 1]?.date }}</span>
          </div>
        </div>
        <el-empty v-else :image-size="60" description="暂无趋势数据" />
      </el-card>

      <!-- 评分分布 -->
      <el-card shadow="never" class="rating-card" v-if="report">
        <template #header>
          <span class="card-title"><el-icon><Star /></el-icon> 观看影片评分分布</span>
        </template>
        <div class="rating-chart" v-if="report.rating_distribution.length">
          <div
            v-for="r in report.rating_distribution"
            :key="r.rating"
            class="rating-bar-wrap"
          >
            <span class="rating-label">{{ r.rating.toFixed(1) }}</span>
            <div class="rating-bar-bg">
              <div class="rating-bar" :style="{ width: barWidth(r.count, maxRatingCount) }"></div>
            </div>
            <span class="rating-count">{{ r.count }}</span>
          </div>
        </div>
        <el-empty v-else :image-size="60" description="暂无评分数据" />
      </el-card>

      <!-- 最近观看历史 -->
      <el-card shadow="never" class="history-card">
        <template #header>
          <span class="card-title"><el-icon><Clock /></el-icon> 最近观看历史</span>
        </template>
        <el-table :data="history" stripe size="small" v-loading="historyLoading">
          <el-table-column prop="movie_code" label="番号" width="140" />
          <el-table-column prop="movie_title" label="标题" show-overflow-tooltip />
          <el-table-column label="进度" width="100">
            <template #default="{ row }">
              <el-progress :percentage="Math.round((row.progress || 0) * 100)" :stroke-width="6" />
            </template>
          </el-table-column>
          <el-table-column label="时长" width="90">
            <template #default="{ row }">
              {{ formatDuration(row.duration_watched) }}
            </template>
          </el-table-column>
          <el-table-column label="完播" width="60">
            <template #default="{ row }">
              <el-icon v-if="row.completed" color="#67c23a"><CircleCheck /></el-icon>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="160">
            <template #default="{ row }">
              {{ formatTime(row.played_at) }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis, Refresh, VideoPlay, Clock, Film, CircleCheck, TrendCharts,
  MagicStick, Star, User, PriceTag, Collection, OfficeBuilding, Calendar
} from '@element-plus/icons-vue'
import { getViewingReport, getViewingHistory } from '@/api'

const loading = ref(false)
const historyLoading = ref(false)
const period = ref(30)
const report = ref(null)
const history = ref([])

const maxHourCount = computed(() => {
  if (!report.value) return 1
  return Math.max(1, ...Object.values(report.value.time_distribution.by_hour))
})

const maxWeekdayCount = computed(() => {
  if (!report.value) return 1
  return Math.max(1, ...Object.values(report.value.time_distribution.by_weekday))
})

const maxRatingCount = computed(() => {
  if (!report.value?.rating_distribution?.length) return 1
  return Math.max(1, ...report.value.rating_distribution.map(r => r.count))
})

const trendPoints = computed(() => {
  if (!report.value?.daily_trend?.length) return ''
  const data = report.value.daily_trend
  const max = Math.max(1, ...data.map(d => d.play_count))
  return data.map((d, i) => {
    const x = i * 8 + 4
    const y = 100 - (d.play_count / max) * 90 - 5
    return `${x},${y}`
  }).join(' ')
})

const barWidth = (val, max) => {
  if (!max) return '0%'
  return `${Math.max(2, (val / max) * 100)}%`
}

const barHeight = (val, max) => {
  if (!max) return '0%'
  return `${Math.max(2, (val / max) * 100)}%`
}

const weekdayName = (wd) => {
  const names = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']
  return names[parseInt(wd)] || wd
}

const formatDuration = (sec) => {
  if (!sec) return '-'
  const m = Math.floor(sec / 60)
  const h = Math.floor(m / 60)
  return h > 0 ? `${h}h${m % 60}m` : `${m}m`
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const loadReport = async () => {
  loading.value = true
  try {
    report.value = await getViewingReport({ days: period.value })
  } catch (e) {
    ElMessage.error('加载报告失败')
    console.error(e)
  } finally {
    loading.value = false
  }
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const res = await getViewingHistory({ limit: 30 })
    history.value = res.items || []
  } catch (e) {
    console.error(e)
  } finally {
    historyLoading.value = false
  }
}

onMounted(() => {
  loadReport()
  loadHistory()
})
</script>

<style scoped>
.viewing-report-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header-card {
  border-radius: 8px !important;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.period-selector {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 概要卡片 */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 8px;
}

.summary-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.summary-content {
  min-width: 0;
}

.summary-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.summary-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* AI 洞察 */
.insights-card {
  border-radius: 8px !important;
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.05), rgba(144, 147, 153, 0.05));
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.insights-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.insight-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-regular);
}

.insight-bullet {
  color: #e6a23c;
  margin-top: 3px;
  flex-shrink: 0;
}

/* Top 排行 */
.rank-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 12px;
}

.rank-card {
  border-radius: 8px !important;
}

.rank-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rank-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.rank-no {
  width: 20px;
  text-align: center;
  font-weight: 700;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.rank-name {
  min-width: 80px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex-shrink: 0;
}

.rank-bar-wrap {
  flex: 1;
  height: 8px;
  background: var(--bg-card);
  border-radius: 4px;
  overflow: hidden;
  min-width: 50px;
}

.rank-bar {
  height: 100%;
  background: var(--primary-color);
  border-radius: 4px;
  transition: width 0.3s;
}

.bar-user { background: #10b981 !important; }
.bar-crawler { background: #f97316 !important; }
.bar-series { background: #8b5cf6 !important; }
.bar-studio { background: #06b6d4 !important; }

.rank-count {
  font-size: 11px;
  color: var(--text-secondary);
  min-width: 50px;
  text-align: right;
  flex-shrink: 0;
}

:deep(.tag-user) {
  --el-tag-bg-color: rgba(16, 185, 129, 0.12);
  --el-tag-border-color: rgba(16, 185, 129, 0.4);
  --el-tag-text-color: #10b981;
}

:deep(.tag-crawler) {
  --el-tag-bg-color: rgba(249, 115, 22, 0.12);
  --el-tag-border-color: rgba(249, 115, 22, 0.4);
  --el-tag-text-color: #f97316;
}

/* 时间分布 */
.dist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 12px;
}

.dist-card {
  border-radius: 8px !important;
}

.hour-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 120px;
  padding: 8px 0;
}

.hour-bar-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  min-width: 0;
}

.hour-bar {
  width: 70%;
  background: linear-gradient(180deg, #409eff, #79bbff);
  border-radius: 2px 2px 0 0;
  min-height: 2px;
  transition: height 0.3s;
}

.hour-label {
  font-size: 9px;
  color: var(--text-placeholder);
  margin-top: 4px;
}

.weekday-chart {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  height: 120px;
  padding: 8px 0;
}

.weekday-bar-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
}

.weekday-bar {
  width: 60%;
  background: linear-gradient(180deg, #67c23a, #95d475);
  border-radius: 4px 4px 0 0;
  min-height: 2px;
  transition: height 0.3s;
}

.weekday-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* 趋势 */
.trend-card {
  border-radius: 8px !important;
}

.trend-chart {
  width: 100%;
}

.trend-area {
  width: 100%;
  height: 160px;
}

.trend-svg {
  width: 100%;
  height: 100%;
}

.trend-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* 评分分布 */
.rating-card {
  border-radius: 8px !important;
}

.rating-chart {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rating-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rating-label {
  width: 32px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
}

.rating-bar-bg {
  flex: 1;
  height: 16px;
  background: var(--bg-card);
  border-radius: 4px;
  overflow: hidden;
}

.rating-bar {
  height: 100%;
  background: linear-gradient(90deg, #f7ba2a, #ffd75e);
  border-radius: 4px;
  transition: width 0.3s;
}

.rating-count {
  width: 40px;
  font-size: 11px;
  color: var(--text-secondary);
  text-align: right;
}

/* 历史 */
.history-card {
  border-radius: 8px !important;
}
</style>
