<template>
  <section class="ra" aria-label="最近活动">
    <div class="ra-head">
      <h2 class="ra-title">最近活动</h2>
      <router-link class="ra-more" to="/tools/system?tool=tasks">全部任务 →</router-link>
    </div>

    <div class="ra-body">
      <!-- 骨架 -->
      <div v-if="loading" class="ra-skeleton" aria-hidden="true">
        <div v-for="i in 5" :key="i" class="ra-sk-row" />
      </div>

      <!-- 错误：区块内文案 + 重试（不弹 ElMessage） -->
      <div v-else-if="error" class="ra-error">
        <span>{{ error }}</span>
        <button type="button" class="ra-retry" @click="load">重试</button>
      </div>

      <!-- 空 -->
      <EmptyState
        v-else-if="!tasks.length"
        type="no-data"
        inline
        title="还没有任务记录"
        description="从批量导入开始，任务会在这里出现"
      >
        <el-button size="small" @click="$router.push('/import')">批量导入</el-button>
      </EmptyState>

      <!-- 列表 -->
      <ul v-else class="ra-list">
        <li v-for="task in tasks" :key="task.id" class="ra-item">
          <span class="ra-dot" :class="`is-${tone(task.status)}`" aria-hidden="true" />
          <span class="ra-name" :title="task.name || task.type">{{ task.name || task.type || '任务' }}</span>
          <span class="ra-status">{{ statusLabel(task.status) }}</span>
          <span class="ra-time">{{ formatTime(task.created_at) }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup>
/**
 * RecentActivity —— 首页区块 6 · 最近 8 条任务
 *
 * 唯一一处首页自有请求（`getTasks({page:1,page_size:8})`）。
 * 错误处理按 Shared Knowledge 第 9 条：区块级内联文案 + 「重试」，不弹 ElMessage。
 */
import { onMounted, ref } from 'vue'
import { getTasks } from '@/api'
import EmptyState from '@/components/EmptyState.vue'

const tasks = ref([])
const loading = ref(true)
const error = ref('')

const STATUS_LABEL = {
  pending: '等待',
  running: '运行中',
  success: '成功',
  failed: '失败',
  cancelled: '已取消',
}

const STATUS_TONE = {
  pending: 'idle',
  running: 'run',
  success: 'ok',
  failed: 'err',
  cancelled: 'idle',
}

const statusLabel = (s) => STATUS_LABEL[s] || s || '未知'
const tone = (s) => STATUS_TONE[s] || 'idle'

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return String(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await getTasks({ page: 1, page_size: 8 })
    tasks.value = Array.isArray(res?.items) ? res.items : []
  } catch (e) {
    tasks.value = []
    error.value = '任务列表加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ra {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
  min-width: 0;
}

.ra-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.ra-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.ra-more {
  font-size: 12px;
  color: var(--text-secondary);
  text-decoration: none;
  white-space: nowrap;
}

.ra-more:hover {
  color: var(--accent);
}

.ra-body {
  min-height: 160px;
}

.ra-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.ra-item {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  border-bottom: 1px solid var(--border-light);
  font-size: 13px;
}

.ra-item:last-child {
  border-bottom: 0;
}

.ra-dot {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--text-placeholder);
}

.ra-dot.is-ok { background: var(--success-color); }
.ra-dot.is-err { background: var(--danger-color); }
.ra-dot.is-run { background: var(--accent); }
.ra-dot.is-idle { background: var(--text-placeholder); }

.ra-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-regular);
}

.ra-status {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.ra-time {
  flex-shrink: 0;
  width: 74px;
  text-align: right;
  font-size: 11px;
  color: var(--text-placeholder);
  font-variant-numeric: tabular-nums;
}

.ra-error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 40px 0;
  justify-content: center;
  font-size: 13px;
  color: var(--text-secondary);
}

.ra-retry {
  border: 0;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  color: var(--accent);
  cursor: pointer;
  padding: 0;
}

.ra-retry:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: 4px;
}

.ra-skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 8px;
}

.ra-sk-row {
  height: 22px;
  border-radius: 4px;
  background: var(--hover-layer);
  animation: ra-pulse 1.2s var(--ease-out-nav, ease-out) infinite;
}

@keyframes ra-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
