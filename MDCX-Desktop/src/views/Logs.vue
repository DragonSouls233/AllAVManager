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
/* 分区之间距统一 20px（v6 口径 20–24px） */
.logs { display: flex; flex-direction: column; gap: 20px; }

/* ⚠️ 卡片质感（radius / border / shadow）由 src/styles/commercial.css 的 `.el-card`
   以 `!important` 统一提供。原来这里写 `.toolbar-card, .log-card { border-radius: 10px }`
   —— 无 !important，永远被全局覆盖，属**无效声明**，故移除。 */

.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

/* ⚠️ 日志面板是「终端表面」：**整块调色板固定，不参与主题换肤**。
   覆盖范围 = 深底 #1a1a2e、正文 #dcdfe6、时间戳/调试灰 #909399、红底对比字 #fff、
   两条白色 alpha 分隔线，以及下方 .level-* 的级别色**及其底纹**。
   若把 #1a1a2e / #dcdfe6 换成 --bg-card / --text-primary，亮色主题下会变成
   「浅底深字」的普通卡片，终端语义就没了；#909399 还会变成深灰压深底、不可读。
   级别色为什么不走 token，见 .log-level 上方那段。
   **lead 已批准**：整个终端调色板（深底 #1a1a2e / 正文 #dcdfe6 / 时间戳 #909399 /
   级别色）刻意不跟随主题，属「数据语义 + 终端表面」例外；--text-* / --hairline 不套用。
   改动前请先想清楚这条边界。 */
.log-container {
  height: 600px;
  overflow-y: auto;
  background: #1a1a2e;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-card, 10px);
  padding: 12px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  font-variant-numeric: tabular-nums;
}

.log-line {
  display: flex;
  gap: 10px;
  padding: 2px 0;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.05);
}

.log-time { color: #909399; flex-shrink: 0; font-variant-numeric: tabular-nums; }
/* --accent-soft = 主色向白偏移 72%，正是深底上需要的浅一档强调色（明暗主题都成立） */
.log-logger { color: var(--accent-soft, #7c8af0); flex-shrink: 0; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.log-msg { color: #dcdfe6; flex: 1; word-break: break-all; }

.log-level {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 3px;
  font-weight: 600;
  font-size: 10px;
  letter-spacing: 0.02em;
}
/* ⚠️ 级别色是**日志数据的严重性编码**（红=错误、橙=警告），属**固定调色板，换主题不跟随**。
   与上面 .log-container 的深底/浅字同属「终端表面」，整块面板刻意不参与主题换肤。
   为什么前景不能用 var(--danger-color) 这类状态 token：themes.js:164-166 会按主题注入
   success/warning/danger，用户导入自定义主题后「错误」可能不再是红色 → 日志语义丢失。
   **底纹同理，一并不跟主题**：若前景固定 hex、底纹却用会随主题变的 --success-color，
   会出现「文字固定红、底纹换主题变另一种红」的割裂，所以底纹保持 raw rgba。
   结论：这几行是**有意保留字面量**，前景与底纹都不要"顺手 token 化"。 */
.level-debug { color: #909399; background: rgba(144, 147, 153, 0.2); }
.level-info { color: #67c23a; background: rgba(103, 194, 58, 0.2); }
.level-warning { color: #e6a23c; background: rgba(230, 162, 60, 0.2); }
.level-error { color: #f56c6c; background: rgba(245, 108, 108, 0.2); }
.level-critical { color: #fff; background: #f56c6c; }

/* 错误/警告行整体提亮一档，保证深底上的可读性（同样属固定调色板） */
.log-error .log-msg { color: #f78989; }
.log-warning .log-msg { color: #ebb563; }
</style>
