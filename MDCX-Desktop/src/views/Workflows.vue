<template>
  <div class="workflows-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>工作流管理</h2>
      <p class="subtitle">编排自动化任务流水线 · 一键运行 · 扫描目录自动关联影片</p>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ total || 0 }}</div>
          <div class="stat-label">工作流总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value text-success">{{ enabledCount }}</div>
          <div class="stat-label">已启用</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value text-muted">{{ disabledCount }}</div>
          <div class="stat-label">已停用</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ scheduledCount }}</div>
          <div class="stat-label">已配置计划</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 操作栏 -->
    <div class="action-bar">
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>
        新建工作流
      </el-button>
      <el-button @click="openScan">
        <el-icon><FolderOpened /></el-icon>
        扫描目录
      </el-button>
      <el-button @click="loadData" :loading="loading">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <!-- 工作流列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="workflows" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="ID" prop="id" width="70" />
        <el-table-column label="名称" prop="name" min-width="160" show-overflow-tooltip />
        <el-table-column label="描述" prop="description" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="muted">{{ row.description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="计划" prop="schedule" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.schedule" size="small" type="warning">{{ row.schedule }}</el-tag>
            <span v-else class="muted">未配置</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="(v) => toggleEnabled(row, v)"
              :loading="row._toggling"
            />
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" link @click="runNow(row)" :loading="row._running">
              <el-icon><VideoPlay /></el-icon> 运行
            </el-button>
            <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无工作流，点击「新建工作流」开始编排" />
        </template>
      </el-table>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑工作流' : '新建工作流'" width="520px">
      <el-form :model="form" label-width="90px" ref="formRef">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如：每日新片入库" maxlength="60" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="可选，描述该工作流的用途" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="计划(Cron)">
          <el-input v-model="form.schedule" placeholder="可选，例如 0 3 * * * （每天 3 点）" />
          <div class="field-hint">留空表示不自动调度，仅可手动运行</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 扫描目录对话框 -->
    <el-dialog v-model="scanVisible" title="扫描目录并自动关联影片" width="640px">
      <el-alert type="info" :closable="false" show-icon class="scan-tip">
        <template #title>根据文件名中的番号，自动在库中匹配影片并写入文件路径</template>
      </el-alert>
      <el-form label-width="90px" class="scan-form">
        <el-form-item label="目录列表">
          <el-input
            v-model="scanDirsText"
            type="textarea"
            :rows="4"
            placeholder="每行一个绝对路径，留空则使用配置中的媒体目录&#10;例如：&#10;D:\Movies&#10;E:\JAV"
          />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="scanDryRun">仅预览（不实际写入，只返回匹配结果）</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scanVisible = false">关闭</el-button>
        <el-button type="primary" @click="runScan" :loading="scanning">开始扫描</el-button>
      </template>

      <el-divider v-if="scanResult">扫描结果</el-divider>
      <div v-if="scanResult" class="scan-result">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="发现文件">{{ scanResult.total_files_found }}</el-descriptions-item>
          <el-descriptions-item label="未关联影片">{{ scanResult.movies_without_path }}</el-descriptions-item>
          <el-descriptions-item label="成功关联">{{ scanResult.linked_count }}</el-descriptions-item>
          <el-descriptions-item label="未匹配">{{ scanResult.not_found_count }}</el-descriptions-item>
          <el-descriptions-item label="模式">
            {{ scanResult.dry_run ? '预览' : '已写入' }}
          </el-descriptions-item>
        </el-descriptions>
        <el-table v-if="scanResult.linked && scanResult.linked.length" :data="scanResult.linked" size="small" max-height="240" class="scan-linked">
          <el-table-column label="番号" prop="code" width="120" />
          <el-table-column label="标题" prop="title" min-width="160" show-overflow-tooltip />
          <el-table-column label="路径" prop="path" min-width="220" show-overflow-tooltip />
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, FolderOpened, VideoPlay } from '@element-plus/icons-vue'
import {
  getWorkflows, createWorkflow, updateWorkflow, deleteWorkflow,
  runWorkflow, scanWorkflowDirectory
} from '@/api'

const loading = ref(false)
const saving = ref(false)
const scanning = ref(false)

const workflows = ref([])
const total = ref(0)

const enabledCount = computed(() => workflows.value.filter(w => w.enabled).length)
const disabledCount = computed(() => workflows.value.filter(w => !w.enabled).length)
const scheduledCount = computed(() => workflows.value.filter(w => w.schedule).length)

// 新建/编辑
const dialogVisible = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const form = reactive({
  name: '',
  description: '',
  enabled: true,
  schedule: ''
})

// 扫描
const scanVisible = ref(false)
const scanDirsText = ref('')
const scanDryRun = ref(true)
const scanResult = ref(null)

async function loadData() {
  loading.value = true
  try {
    const res = await getWorkflows()
    workflows.value = Array.isArray(res) ? res : []
    total.value = workflows.value.length
  } catch (e) {
    // 错误提示由拦截器统一处理
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', description: '', enabled: true, schedule: '' })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    description: row.description || '',
    enabled: row.enabled,
    schedule: row.schedule || ''
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写工作流名称')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description || null,
      enabled: form.enabled,
      schedule: form.schedule || null
    }
    if (editingId.value) {
      await updateWorkflow(editingId.value, payload)
      ElMessage.success('已更新')
    } else {
      await createWorkflow(payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    loadData()
  } catch (e) {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row, val) {
  row._toggling = true
  try {
    await updateWorkflow(row.id, {
      name: row.name,
      description: row.description || null,
      enabled: val,
      schedule: row.schedule || null
    })
    row.enabled = val
    ElMessage.success(val ? '已启用' : '已停用')
  } catch (e) {
    // 拦截器已提示
  } finally {
    row._toggling = false
  }
}

async function runNow(row) {
  row._running = true
  try {
    const res = await runWorkflow(row.id)
    ElMessage.success(res.message || `工作流 ${row.name} 已触发`)
  } catch (e) {
    // 拦截器已提示
  } finally {
    row._running = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除工作流「${row.name}」吗？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await deleteWorkflow(row.id)
    ElMessage.success('已删除')
    loadData()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

function openScan() {
  scanResult.value = null
  scanDirsText.value = ''
  scanDryRun.value = true
  scanVisible.value = true
}

async function runScan() {
  scanning.value = true
  scanResult.value = null
  try {
    const directories = scanDirsText.value
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)
    const res = await scanWorkflowDirectory({
      directories: directories.length ? directories : null,
      dry_run: scanDryRun.value
    })
    scanResult.value = res
    ElMessage.success(
      scanDryRun.value
        ? `预览完成：匹配到 ${res.linked_count} 个影片`
        : `关联完成：写入 ${res.linked_count} 个影片路径`
    )
  } catch (e) {
    // 拦截器已提示
  } finally {
    scanning.value = false
  }
}

function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.workflows-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.subtitle {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  text-align: center;
  padding: 10px 0;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.text-success {
  color: #67c23a;
}

.text-muted {
  color: #909399;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.action-bar {
  margin-bottom: 16px;
  display: flex;
  gap: 8px;
}

.list-card {
  margin-bottom: 20px;
}

.muted {
  color: #c0c4cc;
}

.field-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.scan-tip {
  margin-bottom: 16px;
}

.scan-form {
  margin-top: 8px;
}

.scan-result {
  margin-top: 8px;
}

.scan-linked {
  margin-top: 12px;
}
</style>
