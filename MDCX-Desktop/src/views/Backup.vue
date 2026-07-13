<template>
  <div class="backup-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>自动备份管理</h2>
      <p class="subtitle">定期备份数据库与配置文件 · 保留策略自动清理 · 一键恢复</p>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ stats.total_backups || 0 }}</div>
          <div class="stat-label">备份总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ stats.total_size_str || '0 B' }}</div>
          <div class="stat-label">备份总大小</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value" :class="{ 'text-success': stats.auto_backup_enabled }">
            {{ stats.auto_backup_enabled ? '已启用' : '未启用' }}
          </div>
          <div class="stat-label">自动备份</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ formatTime(stats.last_backup) }}</div>
          <div class="stat-label">最近备份</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 操作栏 -->
    <div class="action-bar">
      <el-button type="primary" @click="handleCreateBackup" :loading="creating">
        <el-icon><Plus /></el-icon>
        立即备份
      </el-button>
      <el-button @click="loadData" :loading="loading">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
      <el-button @click="configDialogVisible = true">
        <el-icon><Setting /></el-icon>
        备份配置
      </el-button>
    </div>

    <!-- 备份列表 -->
    <el-card shadow="never" class="backup-list-card">
      <template #header>
        <span>备份列表</span>
      </template>
      <el-table :data="backups" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="名称" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="大小" width="120">
          <template #default="{ row }">
            {{ row.size_str }}
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_compressed ? 'success' : 'info'">
              {{ row.is_compressed ? '压缩' : '目录' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="handleRestore(row)">
              恢复
            </el-button>
            <el-button size="small" type="info" link @click="handleDownload(row)">
              下载
            </el-button>
            <el-button size="small" type="danger" link @click="handleDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无备份记录" />
        </template>
      </el-table>
    </el-card>

    <!-- 备份配置对话框 -->
    <el-dialog v-model="configDialogVisible" title="备份配置" width="500px">
      <el-form :model="configForm" label-width="120px">
        <el-form-item label="启用自动备份">
          <el-switch v-model="configForm.enabled" />
        </el-form-item>
        <el-form-item label="备份频率">
          <el-select v-model="configForm.interval" style="width: 100%">
            <el-option label="每小时" value="hourly" />
            <el-option label="每天" value="daily" />
            <el-option label="每周" value="weekly" />
          </el-select>
        </el-form-item>
        <el-form-item label="执行时间">
          <el-time-picker v-model="scheduleTimeObj" format="HH:mm" value-format="HH:mm" placeholder="选择时间" style="width: 100%" />
        </el-form-item>
        <el-form-item label="执行日期" v-if="configForm.interval === 'weekly'">
          <el-select v-model="configForm.schedule_day" style="width: 100%">
            <el-option label="周日" :value="0" />
            <el-option label="周一" :value="1" />
            <el-option label="周二" :value="2" />
            <el-option label="周三" :value="3" />
            <el-option label="周四" :value="4" />
            <el-option label="周五" :value="5" />
            <el-option label="周六" :value="6" />
          </el-select>
        </el-form-item>
        <el-form-item label="最大保留数">
          <el-input-number v-model="configForm.max_backups" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="备份内容">
          <el-checkbox v-model="configForm.backup_database">数据库</el-checkbox>
          <el-checkbox v-model="configForm.backup_config">配置文件</el-checkbox>
          <el-checkbox v-model="configForm.backup_logs">日志文件</el-checkbox>
        </el-form-item>
        <el-form-item label="压缩备份">
          <el-switch v-model="configForm.compress" />
        </el-form-item>
        <el-form-item label="自定义目录">
          <el-input v-model="configForm.backup_dir" placeholder="留空使用默认 data/backups" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveConfig" :loading="savingConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- 创建备份对话框 -->
    <el-dialog v-model="createDialogVisible" title="创建备份" width="400px">
      <el-form>
        <el-form-item label="备份备注">
          <el-input v-model="createNote" placeholder="可选，如：升级前备份" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmCreateBackup" :loading="creating">
          确认备份
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Setting } from '@element-plus/icons-vue'
import {
  listBackups, getBackupStats, createBackup,
  restoreBackup, deleteBackup, getBackupConfig, updateBackupConfig,
  downloadBackup
} from '@/api'

const loading = ref(false)
const creating = ref(false)
const savingConfig = ref(false)
const configDialogVisible = ref(false)
const createDialogVisible = ref(false)
const createNote = ref('')

const backups = ref([])
const stats = ref({})
const configForm = reactive({
  enabled: false,
  interval: 'daily',
  schedule_time: '03:00',
  schedule_day: 0,
  max_backups: 7,
  backup_database: true,
  backup_config: true,
  backup_logs: false,
  compress: true,
  backup_dir: '',
})

// 时间选择器需要 Date 对象
const scheduleTimeObj = computed({
  get: () => configForm.schedule_time ? new Date(`2000-01-01T${configForm.schedule_time}:00`) : null,
  set: (val) => {
    if (val) {
      const d = new Date(val)
      configForm.schedule_time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    }
  }
})

async function loadData() {
  loading.value = true
  try {
    const [listRes, statsRes] = await Promise.all([
      listBackups(),
      getBackupStats()
    ])
    backups.value = listRes.data.backups || []
    stats.value = statsRes.data
  } catch (e) {
    ElMessage.error('加载数据失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function loadConfig() {
  try {
    const res = await getBackupConfig()
    Object.assign(configForm, res.data)
  } catch (e) {
    // 静默
  }
}

function handleCreateBackup() {
  createNote.value = ''
  createDialogVisible.value = true
}

async function confirmCreateBackup() {
  creating.value = true
  try {
    const res = await createBackup(createNote.value)
    ElMessage.success(`备份成功: ${res.data.backup.name}`)
    createDialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('备份失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

async function handleRestore(row) {
  try {
    await ElMessageBox.confirm(
      `确定从备份 "${row.name}" 恢复吗？当前数据库和配置将被替换（恢复前会自动创建 .prerestore 备份）。`,
      '恢复确认',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )
    const res = await restoreBackup(row.name)
    ElMessage.success(`恢复完成: ${res.data.result.restored.join(', ')}`)
    if (res.data.result.errors?.length) {
      ElMessage.warning(`部分错误: ${res.data.result.errors.join('; ')}`)
    }
    loadData()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('恢复失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除备份 "${row.name}" 吗？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await deleteBackup(row.name)
    ElMessage.success('已删除')
    loadData()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

async function handleDownload(row) {
  try {
    // 使用 @/api 封装(自动携带 token,返回 blob)
    const blob = await downloadBackup(row.name)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = row.name
    link.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('下载失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function saveConfig() {
  savingConfig.value = true
  try {
    await updateBackupConfig(configForm)
    ElMessage.success('配置已保存')
    configDialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingConfig.value = false
  }
}

function formatDateTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatTime(iso) {
  if (!iso) return '从未'
  const d = new Date(iso)
  const now = new Date()
  const diff = now - d
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return `${Math.floor(diff / 86400000)} 天前`
}

onMounted(() => {
  loadData()
  loadConfig()
})
</script>

<style scoped>
.backup-page {
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

.stat-value.text-success {
  color: #67c23a;
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

.backup-list-card {
  margin-bottom: 20px;
}
</style>
