<template>
  <div class="page nfo-refill-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Download /></el-icon>
          补全 NFO 缓存影片
        </h2>
        <span class="page-subtitle">
          对 source=nfo_cache 的影片执行：复制视频目录本地图 → 强制远程刮削 → 下载高清封面 → 写番号预览图 → 补全 NFO
        </span>
      </div>
    </div>

    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num primary">{{ stats.total || 0 }}</span>
            <span class="stat-label">nfo_cache 影片（待补全）</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="action-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title"><el-icon><Setting /></el-icon>&nbsp;补全策略</span>
        </div>
      </template>

      <el-row :gutter="24" align="middle">
        <el-col :xs="24" :sm="8">
          <div class="form-item">
            <span class="label">处理数量</span>
            <el-radio-group v-model="limit" size="default">
              <el-radio-button :value="100">前 100</el-radio-button>
              <el-radio-button :value="500">前 500</el-radio-button>
              <el-radio-button :value="1000">前 1000</el-radio-button>
              <el-radio-button :value="5000">全部</el-radio-button>
            </el-radio-group>
          </div>
        </el-col>

        <el-col :xs="24" :sm="8">
          <div class="form-item">
            <span class="label">步骤选项</span>
            <el-checkbox-group v-model="steps">
              <el-checkbox label="local_first">复制本地图</el-checkbox>
              <el-checkbox label="scrape">远程刮削</el-checkbox>
            </el-checkbox-group>
          </div>
        </el-col>

        <el-col :xs="24" :sm="6">
          <div class="form-item">
            <span class="label">刮削并发</span>
            <el-input-number v-model="concurrency" :min="1" :max="20" size="default" />
          </div>
        </el-col>

        <el-col :xs="24" :sm="6">
          <div class="form-item">
            <span class="label">刮削源（3 重点 + 4 辅助）</span>
            <el-select v-model="sources" multiple collapse-tags collapse-tags-tooltip
                       placeholder="3 重点 + 4 辅助" style="width:100%">
              <el-option label="JavDB API（重点）" value="thejavdb" />
              <el-option label="JavBus（重点）" value="javbus" />
              <el-option label="Avmoo（重点）" value="avmoo" />
              <el-option label="JavBooks（辅助）" value="javbooks" />
              <el-option label="JavDatabase（辅助）" value="javdatabase" />
              <el-option label="AvSox（辅助）" value="avsox" />
              <el-option label="DMM/FANZA（辅助）" value="dmm_web" />
            </el-select>
          </div>
        </el-col>
      </el-row>

      <div class="action-row">
        <el-button type="primary" size="large" :loading="running" @click="startRefill">
          <el-icon><Play /></el-icon>
          启动补全（复制 + 远程刮削）
        </el-button>
        <el-button type="success" size="large" :loading="syncRunning" @click="startLocalSync">
          <el-icon><CopyDocument /></el-icon>
          仅复制本地图（不联网）
        </el-button>
        <el-tag v-if="running" type="info" class="status-tag">
          后台任务进行中……
        </el-tag>
      </div>
    </el-card>

    <el-card v-if="status.running" class="progress-card" shadow="never">
      <template #header>
        <span class="card-title"><el-icon><Loading /></el-icon>&nbsp;实时进度</span>
      </template>
      <el-progress
        :percentage="pct"
        :status="pct >= 100 ? 'success' : undefined"
        :stroke-width="18"
      />
      <div class="progress-detail">
        <span>已处理 <b>{{ status.done || 0 }}</b> / {{ status.total || 0 }}</span>
        <span v-if="status.started_at">
          · 用时 <b>{{ elapsed }}</b>
        </span>
      </div>
      <el-row :gutter="16" class="progress-stats">
        <el-col :xs="6">
          <div class="mini-stat">
            <span class="mini-num success">{{ status.local_only || 0 }}</span>
            <span class="mini-label">本地已足</span>
          </div>
        </el-col>
        <el-col :xs="6">
          <div class="mini-stat">
            <span class="mini-num primary">{{ status.scraped || 0 }}</span>
            <span class="mini-label">远程刮削</span>
          </div>
        </el-col>
        <el-col :xs="6">
          <div class="mini-stat">
            <span class="mini-num warning">{{ status.no_source || 0 }}</span>
            <span class="mini-label">无数据源</span>
          </div>
        </el-col>
        <el-col :xs="6">
          <div class="mini-stat">
            <span class="mini-num danger">{{ status.failed || 0 }}</span>
            <span class="mini-label">失败</span>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card v-if="syncStatus.running" class="progress-card" shadow="never">
      <template #header>
        <span class="card-title"><el-icon><Loading /></el-icon>&nbsp;本地图复制进度</span>
      </template>
      <el-progress
        :percentage="syncPct"
        :status="syncPct >= 100 ? 'success' : undefined"
        :stroke-width="18"
      />
      <div class="progress-detail">
        <span>已处理 <b>{{ syncStatus.done || 0 }}</b> / {{ syncStatus.total || 0 }}</span>
        <span>· 已复制 <b class="success-color">{{ syncStatus.copied || 0 }}</b> 个文件</span>
      </div>
    </el-card>

    <el-card v-if="status.running || (status.failed_list && status.failed_list.length)" class="progress-card" shadow="never">
      <template #header>
        <span class="card-title"><el-icon><Warning /></el-icon>&nbsp;失败清单（{{ (status.failed_list || []).length }} 条）</span>
      </template>
      <div v-if="status.failed_file" class="failed-file">
        已落盘：<code>{{ status.failed_file }}</code>
        <el-button size="small" type="primary" text @click="copyFailedFile">复制路径</el-button>
      </div>
      <el-table :data="status.failed_list || []" size="small" max-height="360" style="width:100%">
        <el-table-column prop="code" label="番号" width="150" />
        <el-table-column prop="reason" label="失败原因" show-overflow-tooltip />
      </el-table>
    </el-card>

    <div class="info-note">
      <el-alert type="info" :closable="false">
        <template #title>说明</template>
        <div>
          <p>· 此页面针对 <b>source=nfo_cache</b> 的影片（从 NFO 文件导入、未经过远程刮削）。</p>
          <p>· "补全"每部影片执行：①复制视频目录本地图 → ②强制远程刮削（拿最新 metadata + 高清封面）→ ③下载封面到数据目录 → ④写番号预览图到视频目录 → ⑤更新 DB 与 NFO。</p>
          <p>· "仅复制本地图"只执行 ①，纯本地操作，秒级完成；适合 H 盘目录已有 {番号}-poster.jpg / fanart.jpg / thumb.jpg 时快速补齐数据目录。</p>
          <p>· 并发越高，服务器与刮削源站点压力越大。网络慢时建议 3-5。</p>
        </div>
      </el-alert>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Download, Setting, VideoPlay, CopyDocument, Loading, Warning } from '@element-plus/icons-vue'
import { refillNfoCache, getNfoRefillStatus, syncLocalPreviews, getLocalSyncStatus, getJavMovies } from '@/api/jav'
import { ElMessage } from 'element-plus'

const stats = ref({ total: 0, cover_ok: 0, cover_missing: 0, local_missing: 0 })
const limit = ref(500)
const concurrency = ref(5)
const sources = ref(['thejavdb', 'javbus', 'avmoo', 'javbooks', 'javdatabase', 'avsox', 'dmm_web'])
const steps = ref(['local_first', 'scrape'])
const status = ref({ running: false, done: 0, total: 0, scraped: 0, no_source: 0, failed: 0, local_only: 0, started_at: 0, failed_list: [], failed_file: null })
const syncStatus = ref({ running: false, done: 0, total: 0, copied: 0, no_video_dir: 0, failed: 0, started_at: 0 })
const running = ref(false)
const syncRunning = ref(false)
let pollTimer = null
let syncPollTimer = null

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (syncPollTimer) clearInterval(syncPollTimer)
})

const pct = computed(() => {
  const t = status.value.total || 0
  return t > 0 ? Math.round((status.value.done / t) * 100) : 0
})

const syncPct = computed(() => {
  const t = syncStatus.value.total || 0
  return t > 0 ? Math.round((syncStatus.value.done / t) * 100) : 0
})

const elapsed = computed(() => {
  if (!status.value.started_at) return '-'
  const sec = Math.round((Date.now() - status.value.started_at) / 1000)
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
})

async function loadStats() {
  try {
    const res = await getJavMovies({ page: 1, page_size: 1, source: 'nfo_cache' })
    stats.value.total = res.total || 0
  } catch (e) {
    stats.value.total = 0
  }
}

async function startRefill() {
  if (running.value) return
  const body = {
    limit: limit.value,
    concurrency: concurrency.value,
    local_first: steps.value.includes('local_first'),
    scrape: steps.value.includes('scrape'),
    sources: sources.value,
  }
  try {
    await refillNfoCache(body)
    running.value = true
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = setInterval(pollRefillStatus, 2500)
    pollRefillStatus()
  } catch (e) {
    console.error(e)
  }
}

async function pollRefillStatus() {
  try {
    const res = await getNfoRefillStatus()
    status.value = res
    running.value = !!res.running
    if (res.running) {
      // 后端任务在跑：确保轮询恢复（切页回来 onMounted 首次拉取时也能续上）
      if (!pollTimer) {
        pollTimer = setInterval(pollRefillStatus, 2500)
      }
    } else {
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
      loadStats()
    }
  } catch (e) {
    console.error(e)
  }
}

async function pollSyncStatus() {
  try {
    const res = await getLocalSyncStatus()
    syncStatus.value = res
    syncRunning.value = !!res.running
    if (res.running) {
      if (!syncPollTimer) {
        syncPollTimer = setInterval(pollSyncStatus, 2500)
      }
    } else {
      if (syncPollTimer) {
        clearInterval(syncPollTimer)
        syncPollTimer = null
      }
      loadStats()
    }
  } catch (e) {
    console.error(e)
  }
}

onMounted(() => {
  // 页面挂载即恢复实时状态：后端任务若在跑，自动恢复轮询并显示实时进度，
  // 不再依赖"必须在本页点击启动"才展示
  pollRefillStatus()
  pollSyncStatus()
  loadStats()
})

loadStats()

function copyFailedFile() {
  if (!status.value.failed_file) return
  navigator.clipboard.writeText(status.value.failed_file).then(() => {
    ElMessage.success('失败清单路径已复制')
  }).catch(() => {
    ElMessage.error('复制失败，请手动复制上方路径')
  })
}

async function startLocalSync() {
  if (syncRunning.value) return
  try {
    await syncLocalPreviews({ limit: limit.value })
    syncRunning.value = true
    if (syncPollTimer) clearInterval(syncPollTimer)
    syncPollTimer = setInterval(pollSyncStatus, 2500)
    pollSyncStatus()
  } catch (e) {
    console.error(e)
  }
}
</script>

<style scoped>
.page { padding: 16px 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { font-size: 22px; margin: 0; display: flex; align-items: center; gap: 8px; }
.page-subtitle { font-size: 13px; color: #666; margin-top: 4px; display: block; }
.stats-row { margin-bottom: 16px; }
.stat-card { text-align: center; }
.stat-inner { padding: 8px 0; }
.stat-num { font-size: 28px; font-weight: bold; margin-right: 10px; }
.stat-num.primary { color: #409eff; }
.stat-num.warning { color: #e6a23c; }
.stat-num.danger { color: #f56c6c; }
.stat-num.info { color: #909399; }
.stat-label { font-size: 12px; color: #666; }
.action-card { margin-bottom: 16px; }
.card-title { font-weight: bold; font-size: 15px; display: flex; align-items: center; }
.form-item { margin-bottom: 12px; }
.form-item .label { display: block; font-size: 13px; color: #666; margin-bottom: 6px; }
.action-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding-top: 12px; }
.status-tag { font-size: 12px; }
.progress-card { margin-bottom: 16px; }
.progress-detail { font-size: 13px; color: #666; margin-top: 8px; display: flex; gap: 12px; }
.progress-stats { margin-top: 12px; }
.mini-stat { text-align: center; padding: 8px 0; }
.mini-num { font-size: 20px; font-weight: bold; display: block; }
.mini-label { font-size: 12px; color: #666; display: block; margin-top: 4px; }
.mini-num.success { color: #67c23a; }
.mini-num.primary { color: #409eff; }
.mini-num.warning { color: #e6a23c; }
.mini-num.danger { color: #f56c6c; }
.success-color { color: #67c23a; }
.failed-file {
  font-size: 13px;
  color: #666;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.failed-file code {
  background: #f4f4f5;
  padding: 2px 6px;
  border-radius: 4px;
  word-break: break-all;
}
.info-note { margin-top: 12px; }
.info-note .el-alert { font-size: 13px; line-height: 1.7; }
</style>