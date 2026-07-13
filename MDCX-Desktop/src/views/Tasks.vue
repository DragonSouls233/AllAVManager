<template>
  <div class="tasks">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-select v-model="filterStatus" placeholder="状态筛选" clearable style="width: 140px">
            <el-option label="等待中" value="pending" />
            <el-option label="运行中" value="running" />
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
            <el-option label="已取消" value="cancelled" />
          </el-select>
          <el-select v-model="filterType" placeholder="任务类型" clearable style="width: 160px">
            <el-option label="刮削" value="scrape" />
            <el-option label="补刮" value="patch" />
            <el-option label="导入" value="import" />
            <el-option label="缩略图" value="thumbnail" />
            <el-option label="指纹" value="fingerprint" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button type="warning" plain @click="cleanupAction" :loading="cleaning">
            <el-icon><Delete /></el-icon> 清理已完成
          </el-button>
          <el-button @click="loadTasks">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="filteredTasks" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.type || '任务' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="任务名称" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small" effect="dark">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress
              v-if="row.status === 'running'"
              :percentage="row.progress || 0"
              :status="row.progress === 100 ? 'success' : ''"
            />
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'failed'"
              size="small"
              type="primary"
              plain
              @click="retryAction(row)"
            >
              重试
            </el-button>
            <el-button
              v-if="['pending', 'running'].includes(row.status)"
              size="small"
              type="danger"
              plain
              @click="cancelAction(row)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination" v-if="total > 0">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadTasks"
        />
      </div>
    </el-card>

    <!-- 定时任务 -->
    <el-card shadow="never" class="scheduled-card">
      <template #header>
        <div class="card-title">
          <el-icon><AlarmClock /></el-icon> 定时任务
          <el-button size="small" type="primary" plain @click="showCreateScheduled" style="margin-left: auto">
            <el-icon><Plus /></el-icon> 新建
          </el-button>
        </div>
      </template>
      <el-table :data="scheduledJobs" v-loading="loadingScheduled" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="cron" label="Cron 表达式" width="160" />
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column prop="next_run" label="下次执行" width="180">
          <template #default="{ row }">
            {{ formatTime(row.next_run) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="deleteScheduledAction(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建定时任务对话框 -->
    <el-dialog v-model="createDialog.visible" title="新建定时任务" width="500px">
      <el-form label-width="120px" :model="createDialog.form">
        <el-form-item label="名称">
          <el-input v-model="createDialog.form.name" placeholder="任务名称" />
        </el-form-item>
        <el-form-item label="Cron 表达式">
          <el-input v-model="createDialog.form.cron" placeholder="0 2 * * * (每天2点)" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="createDialog.form.type" style="width: 100%">
            <el-option label="刮削" value="scrape" />
            <el-option label="补刮" value="patch" />
            <el-option label="扫描关联" value="scan_link" />
          </el-select>
        </el-form-item>
        <el-form-item label="参数(JSON)">
          <el-input v-model="createDialog.form.params" type="textarea" :rows="4" placeholder='{"directories":["/path"]}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="createScheduledAction" :loading="createDialog.loading">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, Plus, AlarmClock } from '@element-plus/icons-vue'
import {
  getTasks, retryTask, cancelTask, cleanupTasks,
  getScheduledJobs, createScheduledJob, deleteScheduledJob
} from '@/api'

const loading = ref(false)
const loadingScheduled = ref(false)
const cleaning = ref(false)
const tasks = ref([])
const scheduledJobs = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filterStatus = ref('')
const filterType = ref('')

const filteredTasks = computed(() => {
  return tasks.value.filter(t => {
    if (filterStatus.value && t.status !== filterStatus.value) return false
    if (filterType.value && t.type !== filterType.value) return false
    return true
  })
})

const statusType = (s) => ({
  pending: 'info', running: 'warning', success: 'success',
  failed: 'danger', cancelled: 'info'
}[s] || 'info')

const statusLabel = (s) => ({
  pending: '等待中', running: '运行中', success: '成功',
  failed: '失败', cancelled: '已取消'
}[s] || s || '未知')

const formatTime = (t) => {
  if (!t) return '-'
  const d = new Date(t)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const loadTasks = async () => {
  loading.value = true
  try {
    const res = await getTasks({ page: page.value, page_size: pageSize.value })
    tasks.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const loadScheduled = async () => {
  loadingScheduled.value = true
  try {
    const res = await getScheduledJobs()
    scheduledJobs.value = res.items || res || []
  } catch (e) {
    console.error(e)
  } finally {
    loadingScheduled.value = false
  }
}

const retryAction = async (row) => {
  try {
    await retryTask(row.id)
    ElMessage.success('已重试')
    loadTasks()
  } catch (e) { console.error(e) }
}

const cancelAction = async (row) => {
  try {
    await cancelTask(row.id)
    ElMessage.success('已取消')
    loadTasks()
  } catch (e) { console.error(e) }
}

const cleanupAction = async () => {
  cleaning.value = true
  try {
    await cleanupTasks()
    ElMessage.success('已清理')
    loadTasks()
  } catch (e) { console.error(e) }
  finally { cleaning.value = false }
}

const createDialog = ref({
  visible: false,
  loading: false,
  form: { name: '', cron: '0 2 * * *', type: 'scrape', params: '{}' }
})

const showCreateScheduled = () => {
  createDialog.value = {
    visible: true, loading: false,
    form: { name: '', cron: '0 2 * * *', type: 'scrape', params: '{}' }
  }
}

const createScheduledAction = async () => {
  createDialog.value.loading = true
  try {
    let params = {}
    try { params = JSON.parse(createDialog.value.form.params || '{}') } catch {}
    await createScheduledJob({
      name: createDialog.value.form.name,
      cron: createDialog.value.form.cron,
      type: createDialog.value.form.type,
      params
    })
    ElMessage.success('创建成功')
    createDialog.value.visible = false
    loadScheduled()
  } catch (e) { console.error(e) }
  finally { createDialog.value.loading = false }
}

const deleteScheduledAction = (row) => {
  ElMessageBox.confirm(`确认删除定时任务「${row.name}」？`, '提示', { type: 'warning' })
    .then(async () => {
      try {
        await deleteScheduledJob(row.id)
        ElMessage.success('已删除')
        loadScheduled()
      } catch (e) { console.error(e) }
    }).catch(() => {})
}

onMounted(() => {
  loadTasks()
  loadScheduled()
})
</script>

<style scoped>
.tasks { display: flex; flex-direction: column; gap: 16px; }
.toolbar-card, .table-card, .scheduled-card { border-radius: 10px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; color: #303133; }
.text-muted { color: #c0c4cc; }
.pagination { margin-top: 16px; display: flex; justify-content: center; }
</style>
