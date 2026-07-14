<template>
  <div class="download-manager">
    <div class="toolbar">
      <h2>下载管理</h2>
      <div class="stats-row">
        <el-tag type="info">活跃: {{ stats.active_count || 0 }}</el-tag>
        <el-tag type="warning">队列: {{ stats.queue_length || 0 }}</el-tag>
        <el-tag type="success">总数: {{ stats.total_tasks || 0 }}</el-tag>
        <el-tag>最大并发: {{ stats.max_concurrent || 3 }}</el-tag>
        <el-button size="small" @click="loadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <!-- 新建下载 -->
    <el-card class="new-download" style="margin-bottom: 16px">
      <template #header>
        <span>新建下载任务</span>
      </template>
      <el-form :model="newTask" inline>
        <el-form-item label="URL" style="flex: 1">
          <el-input v-model="newTask.url" placeholder="输入视频 URL..." clearable />
        </el-form-item>
        <el-form-item label="引擎">
          <el-select v-model="newTask.engine" style="width: 140px">
            <el-option label="自动选择" value="auto" />
            <el-option v-for="e in engines" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="startNewDownload" :disabled="!newTask.url">
            <el-icon><Download /></el-icon> 开始下载
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 任务列表 -->
    <el-table :data="filteredTasks" v-loading="loading" stripe style="width: 100%">
      <el-table-column prop="task_id" label="ID" width="100" />
      <el-table-column label="URL" min-width="200">
        <template #default="scope">
          <span class="url-cell" :title="scope.row.url">{{ scope.row.url }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="engine" label="引擎" width="100" />
      <el-table-column label="状态" width="120">
        <template #default="scope">
          <el-tag :type="statusTag(scope.row.status)" size="small">
            {{ statusLabel(scope.row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" width="180">
        <template #default="scope">
          <el-progress
            :percentage="scope.row.progress || 0"
            :status="scope.row.status === 'completed' ? 'success' : scope.row.status === 'failed' ? 'exception' : ''"
            :stroke-width="12"
            :text-inside="true"
          />
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170">
        <template #default="scope">
          {{ formatTime(scope.row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="scope">
          <el-button
            v-if="scope.row.status === 'queued' || scope.row.status === 'downloading'"
            size="small"
            type="danger"
            @click="cancelTask(scope.row.task_id)"
          >
            取消
          </el-button>
          <span v-else>-</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空状态 -->
    <el-empty v-if="!loading && filteredTasks.length === 0" description="暂无下载任务" />

    <!-- 排他统计 -->
    <el-card class="cache-stats" v-if="cacheStats.total" style="margin-top: 16px">
      <template #header>
        <span>下载缓存统计</span>
      </template>
      <el-descriptions :column="5" border size="small">
        <el-descriptions-item label="总记录">{{ cacheStats.total }}</el-descriptions-item>
        <el-descriptions-item label="已完成">{{ cacheStats.completed }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ cacheStats.failed }}</el-descriptions-item>
        <el-descriptions-item label="待处理">{{ cacheStats.pending }}</el-descriptions-item>
        <el-descriptions-item label="总字节">{{ formatBytes(cacheStats.total_bytes) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDownloadStore } from '@/stores/download'
import { ElMessage } from 'element-plus'

const store = useDownloadStore()
const loading = ref(false)
const filterStatus = ref('')
const newTask = ref({ url: '', engine: 'auto' })

const engines = computed(() => store.engines)
const filteredTasks = computed(() => {
  let items = store.tasks
  if (filterStatus.value) {
    items = items.filter(t => t.status === filterStatus.value)
  }
  return items
})

function statusTag(status) {
  const map = { queued: 'info', downloading: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { queued: '排队中', downloading: '下载中', completed: '已完成', failed: '失败', cancelled: '已取消', pending: '待处理' }
  return map[status] || status
}

function formatTime(ts) {
  if (!ts) return '-'
  try {
    const d = new Date(ts * 1000)
    return d.toLocaleString('zh-CN')
  } catch {
    return ts
  }
}

function formatBytes(bytes) {
  if (!bytes) return '-'
  if (bytes >= 1024 * 1024 * 1024) return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(2) + ' MB'
  if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB'
  return bytes + ' B'
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([
      store.loadTasks(),
      store.loadEngines(),
      store.loadStats(),
    ])
  } finally {
    loading.value = false
  }
}

async function startNewDownload() {
  if (!newTask.value.url) return
  try {
    const res = await store.submit(
      newTask.value.url,
      '',
      newTask.value.engine,
      {}
    )
    ElMessage.success(`任务已提交: ${res.task_id}`)
    newTask.value.url = ''
  } catch (e) {
    ElMessage.error('提交失败: ' + (e.message || '未知错误'))
  }
}

async function cancelTask(taskId) {
  try {
    await store.cancel(taskId)
    ElMessage.success('已取消')
  } catch (e) {
    ElMessage.error('取消失败')
  }
}

onMounted(() => {
  loadAll()
  store.startPolling(3000)
})

onUnmounted(() => {
  store.stopPolling()
})
</script>

<style scoped>
.download-manager { padding: 20px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.toolbar h2 { margin: 0; }
.stats-row { display: flex; gap: 8px; align-items: center; }
.new-download .el-form { display: flex; gap: 12px; flex-wrap: wrap; }
.url-cell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; max-width: 300px; }
.cache-stats { margin-top: 16px; }
</style>
