<template>
  <div class="page gap-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><DataAnalysis /></el-icon>
          JAV 缺口体检与补全
        </h2>
        <span class="page-subtitle">
          查「缺封面 / 缺预览图 / 缺字段」的影片并一键补齐。缺口从磁盘实算，不信数据库标志位。
        </span>
      </div>
      <div class="page-header-right">
        <el-button :loading="auditing" @click="runAudit">
          <el-icon><Refresh /></el-icon>&nbsp;重新体检
        </el-button>
      </div>
    </div>

    <!-- 缺口概览 -->
    <el-row :gutter="12" class="stats-row">
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num">{{ stats.total_movies || 0 }}</span>
            <span class="stat-label">库内影片总数</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="stat-card cover" shadow="hover" @click="filterBy('cover')">
          <div class="stat-inner">
            <span class="stat-num danger">{{ count('cover') }}</span>
            <span class="stat-label">缺封面</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="stat-card preview" shadow="hover" @click="filterBy('preview')">
          <div class="stat-inner">
            <span class="stat-num warning">{{ count('preview') }}</span>
            <span class="stat-label">缺预览图</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="stat-card field" shadow="hover" @click="filterBy('plot')">
          <div class="stat-inner">
            <span class="stat-num info">{{ count('plot') }}</span>
            <span class="stat-label">缺简介</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="stat-card field" shadow="hover" @click="filterBy('studio')">
          <div class="stat-inner">
            <span class="stat-num info">{{ count('studio') }}</span>
            <span class="stat-label">缺片商</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="stat-card field" shadow="hover" @click="filterBy('series')">
          <div class="stat-inner">
            <span class="stat-num info">{{ count('series') }}</span>
            <span class="stat-label">缺系列</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-alert type="info" :closable="false" class="hint-alert">
      <template #title>
        <span class="hint-text">
          标签 / 评分 / 时长<strong>不计入缺口</strong>——实测源站本身就大量缺这些
          （标签缺失率 97%），全量重刮 9000+ 部也补不上，纯浪费请求。
        </span>
      </template>
    </el-alert>

    <!-- 补全策略 -->
    <el-card class="action-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title"><el-icon><Setting /></el-icon>&nbsp;补全策略</span>
        </div>
      </template>

      <el-form :inline="true" label-position="top">
        <el-form-item label="补哪些缺口">
          <el-checkbox-group v-model="reasons">
            <el-checkbox-button value="cover">封面</el-checkbox-button>
            <el-checkbox-button value="preview">预览图</el-checkbox-button>
            <el-checkbox-button value="plot">简介</el-checkbox-button>
            <el-checkbox-button value="studio">片商</el-checkbox-button>
            <el-checkbox-button value="series">系列</el-checkbox-button>
            <el-checkbox-button value="actor">演员</el-checkbox-button>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item label="本次处理数量">
          <el-radio-group v-model="limit">
            <el-radio-button :value="50">前 50</el-radio-button>
            <el-radio-button :value="200">前 200</el-radio-button>
            <el-radio-button :value="1000">前 1000</el-radio-button>
            <el-radio-button :value="5000">全部</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="刮削并发">
          <el-input-number v-model="concurrency" :min="1" :max="10" />
        </el-form-item>

        <el-form-item label="每部间隔（秒）">
          <el-input-number v-model="gapSeconds" :min="0" :max="30" :step="0.5" />
          <span class="form-tip">限流站点建议 ≥1</span>
        </el-form-item>
      </el-form>

      <div class="action-row">
        <el-button type="primary" :loading="starting" :disabled="running" @click="startFill">
          <el-icon><Download /></el-icon>&nbsp;开始补全
        </el-button>
        <el-button :disabled="running" @click="dryRun">
          <el-icon><View /></el-icon>&nbsp;试运行（只看名单）
        </el-button>
        <span v-if="dryRunMsg" class="dry-run-msg">{{ dryRunMsg }}</span>
      </div>

      <div class="source-hint">
        源序：<code>JavDB 官方 API → JavBus → AVMOO → …</code>（主力源，字段最全最快）；
        素人番号自动切换为 <code>javmenu → javmost → JavDB → …</code>（实测 JavBus 对素人命中率 0）。
      </div>
    </el-card>

    <!-- 进度 -->
    <el-card v-if="running || progress.done > 0" class="progress-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title"><el-icon><Loading /></el-icon>&nbsp;补全进度</span>
          <el-tag v-if="running" type="warning" size="small">运行中</el-tag>
          <el-tag v-else type="success" size="small">已结束</el-tag>
        </div>
      </template>

      <el-progress
        :percentage="percent"
        :status="progress.failed > 0 ? 'exception' : undefined"
        :stroke-width="18"
      />

      <el-row :gutter="12" class="progress-stats">
        <el-col :span="4"><div class="ps-item">已处理 <b>{{ progress.done }}</b> / {{ progress.total }}</div></el-col>
        <el-col :span="4"><div class="ps-item ok">成功 <b>{{ progress.fixed }}</b></div></el-col>
        <el-col :span="4"><div class="ps-item warn">无源 <b>{{ progress.no_source }}</b></div></el-col>
        <el-col :span="4"><div class="ps-item err">失败 <b>{{ progress.failed }}</b></div></el-col>
        <el-col :span="8">
          <el-button v-if="!running && progress.done > 0" size="small" @click="runAudit">
            重新体检看效果
          </el-button>
        </el-col>
      </el-row>

      <div v-if="progress.log && progress.log.length" class="progress-log">
        <div v-for="(l, i) in progress.log.slice(-6)" :key="i" class="log-line">{{ l }}</div>
      </div>

      <el-collapse v-if="progress.failed_list && progress.failed_list.length" class="fail-box">
        <el-collapse-item :title="`失败清单（${progress.failed_list.length}）`" name="1">
          <div v-for="(f, i) in progress.failed_list.slice(0, 200)" :key="i" class="fail-line">
            <code>{{ f.code }}</code> — {{ f.reason }}
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 明细 -->
    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><List /></el-icon>&nbsp;缺口明细
            <el-tag v-if="reasonFilter" size="small" closable @close="reasonFilter = ''">
              筛选：{{ reasonLabel(reasonFilter) }}
            </el-tag>
          </span>
          <el-input
            v-model="keyword"
            placeholder="按番号 / 标题搜索"
            clearable
            size="small"
            style="width: 240px"
          />
        </div>
      </template>

      <el-table :data="paged" v-loading="auditing" size="small" stripe height="520">
        <el-table-column prop="code" label="番号" width="140" fixed />
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column label="缺口" width="260">
          <template #default="{ row }">
            <el-tag
              v-for="r in row.reasons"
              :key="r"
              :type="tagType(r)"
              size="small"
              class="reason-tag"
            >{{ reasonLabel(r) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="output_dir" label="目录" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="fillOne(row.code)">补这部</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="empty-text">没有缺口影片 🎉</span>
        </template>
      </el-table>

      <el-pagination
        v-if="filtered.length > pageSize"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="filtered.length"
        layout="total, prev, pager, next"
        class="pager"
      />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getJavGaps, getJavGapFillStatus, fillJavGaps } from '@/api/jav'

const REASONS = {
  cover: '缺封面',
  preview: '缺预览图',
  plot: '缺简介',
  studio: '缺片商',
  series: '缺系列',
  actor: '缺演员',
  no_dir: '目录缺失'
}

const stats = ref({})
const items = ref([])
const auditing = ref(false)
const running = ref(false)
const starting = ref(false)
const progress = ref({ done: 0, total: 0, fixed: 0, no_source: 0, failed: 0, log: [], failed_list: [] })

const reasons = ref(['cover', 'preview'])
const limit = ref(200)
const concurrency = ref(4)
const gapSeconds = ref(0)
const reasonFilter = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = 50
const dryRunMsg = ref('')

let timer = null

const count = (k) => (stats.value.by_reason || {})[k] || 0
const reasonLabel = (k) => REASONS[k] || k
const tagType = (k) =>
  ({ cover: 'danger', preview: 'warning', no_dir: 'danger' })[k] || 'info'

const filtered = computed(() => {
  let list = items.value
  if (reasonFilter.value) {
    list = list.filter((i) => i.reasons.includes(reasonFilter.value))
  }
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(
      (i) =>
        (i.code || '').toLowerCase().includes(kw) ||
        (i.title || '').toLowerCase().includes(kw)
    )
  }
  return list
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize
  return filtered.value.slice(start, start + pageSize)
})

const percent = computed(() => {
  const t = progress.value.total || 0
  if (!t) return 0
  return Math.min(100, Math.round((progress.value.done / t) * 100))
})

function filterBy(r) {
  reasonFilter.value = reasonFilter.value === r ? '' : r
  page.value = 1
}

async function runAudit() {
  auditing.value = true
  try {
    const res = await getJavGaps({ limit: 20000 })
    stats.value = res.stats || {}
    items.value = res.items || []
    page.value = 1
    ElMessage.success(
      `体检完成：${stats.value.total_movies || 0} 部中 ${items.value.length} 部有缺口`
    )
  } catch (e) {
    ElMessage.error('体检失败：' + (e?.message || e))
  } finally {
    auditing.value = false
  }
}

async function startFill(dry = false) {
  if (!reasons.value.length) {
    ElMessage.warning('请至少勾选一类缺口')
    return
  }
  if (dry) {
    try {
      const res = await fillJavGaps({
        reasons: reasons.value,
        limit: limit.value,
        dry_run: true
      })
      dryRunMsg.value = `将处理 ${res.total} 部：${(res.codes || []).slice(0, 12).join(', ')}${
        res.total > 12 ? ' …' : ''
      }`
      ElMessage.info('试运行完成，未做任何改动')
    } catch (e) {
      ElMessage.error('试运行失败：' + (e?.message || e))
    }
    return
  }

  starting.value = true
  try {
    const res = await fillJavGaps({
      reasons: reasons.value,
      limit: limit.value,
      concurrency: concurrency.value,
      gap_seconds: gapSeconds.value
    })
    if (res.status === 'busy') {
      ElMessage.warning('已有补全任务在跑')
      return
    }
    running.value = true
    ElMessage.success(`已排队 ${res.queued} 部`)
    startPolling()
  } catch (e) {
    ElMessage.error('启动失败：' + (e?.message || e))
  } finally {
    starting.value = false
  }
}

async function fillOne(code) {
  try {
    await fillJavGaps({ codes: [code], reasons: reasons.value, limit: 1 })
    ElMessage.success(`已排队：${code}`)
    running.value = true
    startPolling()
  } catch (e) {
    ElMessage.error('启动失败：' + (e?.message || e))
  }
}

function startPolling() {
  stopPolling()
  timer = setInterval(async () => {
    try {
      const s = await getJavGapFillStatus()
      progress.value = s || {}
      if (!s?.running) {
        stopPolling()
        running.value = false
        ElMessage.success('补全任务结束')
      }
    } catch {
      stopPolling()
      running.value = false
    }
  }, 2000)
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  runAudit()
  // 刷新页面时若后端仍在跑，恢复轮询
  getJavGapFillStatus()
    .then((s) => {
      if (s?.running) {
        running.value = true
        progress.value = s
        startPolling()
      }
    })
    .catch(() => {})
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.gap-page { padding: 16px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.page-subtitle { display: block; margin-top: 6px; color: #6b7280; font-size: 13px; }

.stats-row { margin-bottom: 12px; }
.stat-card { cursor: default; transition: transform .15s; }
.stat-card.cover, .stat-card.preview, .stat-card.field { cursor: pointer; }
.stat-card:hover { transform: translateY(-2px); }
.stat-inner { display: flex; flex-direction: column; align-items: center; padding: 6px 0; }
.stat-num { font-size: 26px; font-weight: 700; line-height: 1.2; }
.stat-num.danger { color: #e5484d; }
.stat-num.warning { color: #f5a524; }
.stat-num.info { color: #3b82f6; }
.stat-label { margin-top: 4px; font-size: 12px; color: #6b7280; }

.hint-alert { margin-bottom: 12px; }
.hint-text { font-size: 13px; }

.action-card, .progress-card, .table-card { margin-bottom: 12px; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-title { font-weight: 600; display: flex; align-items: center; }

.form-item { display: flex; flex-direction: column; gap: 6px; }
.label { font-size: 13px; color: #374151; font-weight: 500; }
.form-tip { margin-left: 8px; font-size: 12px; color: #9ca3af; }

.action-row { display: flex; align-items: center; gap: 12px; margin-top: 4px; }
.dry-run-msg { font-size: 12px; color: #6b7280; }

.source-hint { margin-top: 10px; font-size: 12px; color: #6b7280; line-height: 1.7; }
.source-hint code { background: #f3f4f6; padding: 1px 5px; border-radius: 3px; }

.progress-stats { margin-top: 12px; }
.ps-item { font-size: 13px; color: #374151; }
.ps-item b { font-size: 16px; }
.ps-item.ok b { color: #16a34a; }
.ps-item.warn b { color: #f5a524; }
.ps-item.err b { color: #e5484d; }

.progress-log { margin-top: 10px; font-size: 12px; color: #6b7280; line-height: 1.8; }
.log-line { font-family: ui-monospace, Menlo, Consolas, monospace; }

.fail-box { margin-top: 10px; }
.fail-line { font-size: 12px; padding: 2px 0; color: #4b5563; }
.fail-line code { background: #f3f4f6; padding: 1px 4px; border-radius: 3px; margin-right: 6px; }

.reason-tag { margin-right: 4px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.empty-text { color: #9ca3af; }
</style>
