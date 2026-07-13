<template>
  <div class="log-stream-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Monitor /></el-icon>
          实时日志流
        </h2>
        <div class="page-subtitle">WebSocket 推送 · 刮削进度可视化</div>
      </div>
      <div class="page-header-actions">
        <el-tag :type="connected ? 'success' : 'danger'" effect="dark" size="default">
          <el-icon><Connection /></el-icon>
          {{ connected ? '已连接' : '已断开' }}
        </el-tag>
        <el-button @click="reconnect" :loading="reconnecting">
          <el-icon><Refresh /></el-icon> 重连
        </el-button>
        <el-button :type="autoScroll ? 'primary' : 'default'" @click="autoScroll = !autoScroll">
          <el-icon><Bottom /></el-icon> {{ autoScroll ? '自动滚动' : '已暂停' }}
        </el-button>
        <el-button @click="clearLogs">
          <el-icon><Delete /></el-icon> 清空
        </el-button>
        <el-button @click="exportLogs">
          <el-icon><Download /></el-icon> 导出
        </el-button>
      </div>
    </div>

    <!-- 筛选 -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索日志..." clearable size="small" style="width: 220px" />
        <el-select v-model="levelFilter" placeholder="全部级别" clearable size="small" style="width: 120px">
          <el-option label="INFO" value="INFO" />
          <el-option label="SUCCESS" value="SUCCESS" />
          <el-option label="WARNING" value="WARNING" />
          <el-option label="ERROR" value="ERROR" />
          <el-option label="DEBUG" value="DEBUG" />
        </el-select>
        <el-select v-model="taskFilter" placeholder="全部任务" clearable size="small" style="width: 180px">
          <el-option v-for="t in taskList" :key="t" :label="t" :value="t" />
        </el-select>
        <span class="filter-tip">共 {{ filteredLogs.length }} 条 / 总计 {{ logs.length }} 条</span>
      </div>
    </el-card>

    <!-- 任务进度面板 -->
    <el-card shadow="never" v-if="Object.keys(progressMap).length" class="progress-card">
      <template #header>
        <div class="card-title">
          <el-icon><Loading /></el-icon>
          进行中任务 ({{ Object.keys(progressMap).length }})
        </div>
      </template>
      <div class="progress-list">
        <div v-for="(p, id) in progressMap" :key="id" class="progress-item">
          <div class="progress-header">
            <span class="task-name">{{ p.task_name }}</span>
            <el-tag :type="getProgressStatusType(p.status)" size="small">{{ getProgressStatusText(p.status) }}</el-tag>
            <span class="task-count">{{ p.current }} / {{ p.total }}</span>
          </div>
          <el-progress
            :percentage="p.percent"
            :status="getProgressStatus(p.status)"
            :stroke-width="14"
            :text-inside="true"
          />
        </div>
      </div>
    </el-card>

    <!-- 日志流 -->
    <el-card shadow="never" class="logs-card">
      <div class="logs-stream" ref="logsContainer">
        <div
          v-for="(log, idx) in filteredLogs"
          :key="idx"
          class="log-line"
          :class="'level-' + log.level.toLowerCase()"
        >
          <span class="log-time">{{ formatTime(log.timestamp) }}</span>
          <span class="log-level" :class="'level-' + log.level.toLowerCase()">{{ log.level }}</span>
          <span class="log-task" v-if="log.task_id">[{{ log.task_id }}]</span>
          <span class="log-module" v-if="log.module">{{ log.module }}</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
        <el-empty v-if="!filteredLogs.length" description="暂无日志" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Monitor, Connection, Refresh, Bottom, Delete, Download, Loading
} from '@element-plus/icons-vue'
import { getServerBaseUrl } from '@/utils/media'

const MAX_LOGS = 1000 // 最多保留 1000 条日志

const connected = ref(false)
const reconnecting = ref(false)
const autoScroll = ref(true)
const logs = ref([])
const logsContainer = ref(null)
const progressMap = ref({})
const keyword = ref('')
const levelFilter = ref('')
const taskFilter = ref('')

let ws = null
let reconnectTimer = null

const taskList = computed(() => {
  const set = new Set()
  logs.value.forEach(l => { if (l.task_id) set.add(l.task_id) })
  return Array.from(set)
})

const filteredLogs = computed(() => {
  return logs.value.filter(l => {
    if (levelFilter.value && l.level !== levelFilter.value) return false
    if (taskFilter.value && l.task_id !== taskFilter.value) return false
    if (keyword.value) {
      const kw = keyword.value.toLowerCase()
      if (!(l.message?.toLowerCase().includes(kw) || l.module?.toLowerCase().includes(kw))) return false
    }
    return true
  })
})

const connect = () => {
  if (ws && ws.readyState === WebSocket.OPEN) return

  const baseUrl = getServerBaseUrl()
  const wsUrl = baseUrl.replace(/^http/, 'ws') + '/ws/logs'

  try {
    ws = new WebSocket(wsUrl)
  } catch (e) {
    console.error('WebSocket 创建失败:', e)
    scheduleReconnect()
    return
  }

  ws.onopen = () => {
    connected.value = true
    reconnecting.value = false
    ElMessage.success('WebSocket 已连接')
  }

  ws.onmessage = (event) => {
    if (event.data === 'pong') return
    try {
      const msg = JSON.parse(event.data)
      handleMessage(msg)
    } catch (e) {
      console.error('解析消息失败:', e)
    }
  }

  ws.onerror = (e) => {
    console.error('WebSocket 错误:', e)
  }

  ws.onclose = () => {
    connected.value = false
    if (!reconnecting.value) {
      scheduleReconnect()
    }
  }
}

const scheduleReconnect = () => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnecting.value = true
  reconnectTimer = setTimeout(() => {
    connect()
  }, 3000)
}

const reconnect = () => {
  if (ws) {
    ws.close()
    ws = null
  }
  reconnecting.value = true
  connect()
}

const handleMessage = (msg) => {
  if (msg.type === 'connected') {
    // 连接成功欢迎消息
    return
  }

  if (msg.type === 'log') {
    logs.value.push(msg)
    if (logs.value.length > MAX_LOGS) {
      logs.value = logs.value.slice(-MAX_LOGS)
    }
    if (autoScroll.value) {
      nextTick(() => {
        if (logsContainer.value) {
          logsContainer.value.scrollTop = logsContainer.value.scrollHeight
        }
      })
    }
  } else if (msg.type === 'progress') {
    // 更新进度
    progressMap.value[msg.task_id] = msg
    // 完成的任务 3 秒后移除
    if (['success', 'failed', 'cancelled'].includes(msg.status)) {
      setTimeout(() => {
        delete progressMap.value[msg.task_id]
      }, 3000)
    }
  }
}

// 心跳
let pingTimer = null
const startPing = () => {
  pingTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send('ping')
    }
  }, 30000)
}

const clearLogs = () => {
  logs.value = []
}

const exportLogs = () => {
  const text = filteredLogs.value.map(l =>
    `[${l.timestamp}] [${l.level}]${l.task_id ? ` [${l.task_id}]` : ''}${l.module ? ` [${l.module}]` : ''} ${l.message}`
  ).join('\n')
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `mdcx-logs-${Date.now()}.log`
  a.click()
  URL.revokeObjectURL(url)
}

const formatTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

const getProgressStatus = (status) => {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'exception'
  return undefined
}

const getProgressStatusType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'info'
  return 'primary'
}

const getProgressStatusText = (status) => {
  const map = { running: '运行中', success: '已完成', failed: '失败', cancelled: '已取消' }
  return map[status] || status
}

onMounted(() => {
  connect()
  startPing()
})

onBeforeUnmount(() => {
  if (ws) ws.close()
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (pingTimer) clearInterval(pingTimer)
})
</script>

<style scoped>
.log-stream-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.page-header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
}

.page-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
}

.page-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.filter-card {
  border-radius: 8px !important;
}

.filter-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.filter-tip {
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: auto;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

/* 进度面板 */
.progress-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.progress-item {
  padding: 8px 0;
}

.progress-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.task-name {
  font-weight: 600;
  color: var(--text-primary);
}

.task-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-secondary);
}

/* 日志流 */
.logs-card {
  border-radius: 8px !important;
  overflow: hidden;
}

.logs-stream {
  max-height: 60vh;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.7;
  padding: 12px;
  background: #1a1a2e;
  color: #e0e0e0;
  border-radius: 6px;
}

.log-line {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.log-line:hover {
  background: rgba(255, 255, 255, 0.04);
}

.log-time {
  color: #888;
  flex-shrink: 0;
  width: 110px;
}

.log-level {
  flex-shrink: 0;
  width: 70px;
  font-weight: 700;
  text-align: center;
  padding: 0 4px;
  border-radius: 3px;
}

.level-info {
  color: #409eff;
}

.level-info .log-level {
  background: rgba(64, 158, 255, 0.2);
  color: #66b1ff;
}

.level-success {
  color: #67c23a;
}

.level-success .log-level {
  background: rgba(103, 194, 58, 0.2);
  color: #85ce61;
}

.level-warning {
  color: #e6a23c;
}

.level-warning .log-level {
  background: rgba(230, 162, 60, 0.2);
  color: #ebb563;
}

.level-error {
  color: #f56c6c;
}

.level-error .log-level {
  background: rgba(245, 108, 108, 0.2);
  color: #f78989;
}

.level-debug {
  color: #909399;
}

.level-debug .log-level {
  background: rgba(144, 147, 153, 0.2);
  color: #a6a9ad;
}

.log-task {
  color: #ffd700;
  flex-shrink: 0;
}

.log-module {
  color: #a0a0ff;
  flex-shrink: 0;
}

.log-message {
  flex: 1;
  word-break: break-all;
}

/* 滚动条 */
.logs-stream::-webkit-scrollbar {
  width: 8px;
}

.logs-stream::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.2);
}

.logs-stream::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}

.logs-stream::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}
</style>
