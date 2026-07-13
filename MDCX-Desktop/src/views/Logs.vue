<template>
  <div class="logs">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-select v-model="filterLevel" placeholder="级别" clearable style="width: 120px">
            <el-option label="DEBUG" value="DEBUG" />
            <el-option label="INFO" value="INFO" />
            <el-option label="WARNING" value="WARNING" />
            <el-option label="ERROR" value="ERROR" />
            <el-option label="CRITICAL" value="CRITICAL" />
          </el-select>
          <el-input v-model="searchKey" placeholder="搜索日志..." clearable style="width: 240px">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
        </div>
        <div class="toolbar-right">
          <el-select v-model="limit" style="width: 110px" @change="loadLogs">
            <el-option :value="100" label="100 条" />
            <el-option :value="500" label="500 条" />
            <el-option :value="1000" label="1000 条" />
          </el-select>
          <el-button @click="loadLogs">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-button @click="clearDisplay">
            <el-icon><Delete /></el-icon> 清空
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="log-card">
      <div class="log-container" ref="logContainer">
        <div
          v-for="(log, idx) in filteredLogs"
          :key="idx"
          :class="['log-line', `log-${(log.level || '').toLowerCase()}`]"
        >
          <span class="log-time">{{ log.timestamp || log.time }}</span>
          <span :class="['log-level', `level-${(log.level || '').toLowerCase()}`]">{{ log.level }}</span>
          <span class="log-logger" v-if="log.logger">{{ log.logger }}</span>
          <span class="log-msg">{{ log.message || log.msg }}</span>
        </div>
        <el-empty v-if="!filteredLogs.length" description="暂无日志" :image-size="80" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Search, Refresh, Delete } from '@element-plus/icons-vue'
import { getLogs } from '@/api'

const logs = ref([])
const filterLevel = ref('')
const searchKey = ref('')
const limit = ref(500)
const autoRefresh = ref(false)
const logContainer = ref(null)
let timer = null

const filteredLogs = computed(() => {
  return logs.value.filter(l => {
    if (filterLevel.value && l.level !== filterLevel.value) return false
    if (searchKey.value) {
      const key = searchKey.value.toLowerCase()
      if (!(l.message || l.msg || '').toLowerCase().includes(key) &&
          !(l.logger || '').toLowerCase().includes(key)) return false
    }
    return true
  })
})

const loadLogs = async () => {
  try {
    const res = await getLogs({ limit: limit.value })
    logs.value = res.items || res || []
    scrollToBottom()
  } catch (e) {
    console.error(e)
  }
}

const scrollToBottom = async () => {
  await nextTick()
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
}

const clearDisplay = () => {
  logs.value = []
}

onMounted(() => {
  loadLogs()
  if (autoRefresh.value) startAutoRefresh()
})

const startAutoRefresh = () => {
  if (timer) clearInterval(timer)
  timer = setInterval(loadLogs, 5000)
}

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

// 监听 autoRefresh 变化
import { watch } from 'vue'
watch(autoRefresh, (val) => {
  if (val) startAutoRefresh()
  else if (timer) { clearInterval(timer); timer = null }
})
</script>

<style scoped>
.logs { display: flex; flex-direction: column; gap: 16px; }
.toolbar-card, .log-card { border-radius: 10px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

.log-container {
  height: 600px;
  overflow-y: auto;
  background: #1a1a2e;
  border-radius: 8px;
  padding: 12px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
}

.log-line {
  display: flex;
  gap: 10px;
  padding: 2px 0;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.05);
}

.log-time { color: #909399; flex-shrink: 0; }
.log-logger { color: #66b1ff; flex-shrink: 0; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.log-msg { color: #dcdfe6; flex: 1; word-break: break-all; }

.log-level {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 3px;
  font-weight: 600;
  font-size: 10px;
}
.level-debug { color: #909399; background: rgba(144, 147, 153, 0.2); }
.level-info { color: #67c23a; background: rgba(103, 194, 58, 0.2); }
.level-warning { color: #e6a23c; background: rgba(230, 162, 60, 0.2); }
.level-error { color: #f56c6c; background: rgba(245, 108, 108, 0.2); }
.level-critical { color: #fff; background: #f56c6c; }

.log-error .log-msg { color: #f78989; }
.log-warning .log-msg { color: #ebb563; }
</style>
