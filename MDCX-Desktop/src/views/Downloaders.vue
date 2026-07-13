<template>
  <div class="dl-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Download /></el-icon>
          下载器统一管理
        </h2>
        <div class="page-subtitle">
          统一对接 qBittorrent / Transmission / Aria2 · 添加磁力链 / HTTP 种子
        </div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 重载
        </el-button>
      </div>
    </div>

    <!-- 配置卡片 -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-title">
          <el-icon><Setting /></el-icon> 下载器配置
          <el-tag v-if="form.active" type="success" size="small" style="margin-left: 8px">
            当前激活: {{ activeLabel }}
          </el-tag>
          <el-tag v-else type="warning" size="small" style="margin-left: 8px">未设置激活下载器</el-tag>
        </div>
      </template>

      <el-form :model="form" label-width="160px" style="max-width: 720px">
        <el-form-item label="激活下载器">
          <el-select v-model="form.active" placeholder="选择激活的下载器" style="width: 100%">
            <el-option label="qBittorrent" value="qbittorrent" :disabled="!form.qbittorrent.enabled" />
            <el-option label="Transmission" value="transmission" :disabled="!form.transmission.enabled" />
            <el-option label="Aria2" value="aria2" :disabled="!form.aria2.enabled" />
          </el-select>
          <span class="form-tip">只能选择已启用的下载器</span>
        </el-form-item>

        <!-- 下载器子配置切换 -->
        <el-tabs v-model="activeTab" type="border-card" class="sub-tabs">
          <!-- qBittorrent -->
          <el-tab-pane label="qBittorrent" name="qbittorrent">
            <el-form :model="form.qbittorrent" label-width="140px">
              <el-form-item label="启用">
                <el-switch v-model="form.qbittorrent.enabled" />
              </el-form-item>
              <el-form-item label="主机地址">
                <el-input v-model="form.qbittorrent.host" placeholder="127.0.0.1" />
              </el-form-item>
              <el-form-item label="端口">
                <el-input-number v-model="form.qbittorrent.port" :min="1" :max="65535" />
              </el-form-item>
              <el-form-item label="用户名">
                <el-input v-model="form.qbittorrent.username" placeholder="admin" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input
                  v-model="form.qbittorrent.password"
                  type="password"
                  show-password
                  placeholder="留空不修改"
                />
              </el-form-item>
              <el-form-item label="校验 SSL">
                <el-switch v-model="form.qbittorrent.verify_ssl" />
              </el-form-item>
              <el-form-item label="默认下载目录">
                <el-input v-model="form.qbittorrent.download_dir" placeholder="留空使用 qBittorrent 默认路径" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="testConn('qbittorrent')" :loading="testing === 'qbittorrent'">
                  <el-icon><Connection /></el-icon> 测试连接
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <!-- Transmission -->
          <el-tab-pane label="Transmission" name="transmission">
            <el-form :model="form.transmission" label-width="140px">
              <el-form-item label="启用">
                <el-switch v-model="form.transmission.enabled" />
              </el-form-item>
              <el-form-item label="主机地址">
                <el-input v-model="form.transmission.host" placeholder="127.0.0.1" />
              </el-form-item>
              <el-form-item label="端口">
                <el-input-number v-model="form.transmission.port" :min="1" :max="65535" />
              </el-form-item>
              <el-form-item label="用户名">
                <el-input v-model="form.transmission.username" placeholder="（可空）" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input
                  v-model="form.transmission.password"
                  type="password"
                  show-password
                  placeholder="留空不修改"
                />
              </el-form-item>
              <el-form-item label="使用 HTTPS">
                <el-switch v-model="form.transmission.use_ssl" />
              </el-form-item>
              <el-form-item label="RPC 路径">
                <el-input v-model="form.transmission.rpc_path" placeholder="/transmission/rpc" />
              </el-form-item>
              <el-form-item label="默认下载目录">
                <el-input v-model="form.transmission.download_dir" placeholder="留空使用 Transmission 默认路径" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="testConn('transmission')" :loading="testing === 'transmission'">
                  <el-icon><Connection /></el-icon> 测试连接
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <!-- Aria2 -->
          <el-tab-pane label="Aria2" name="aria2">
            <el-form :model="form.aria2" label-width="140px">
              <el-form-item label="启用">
                <el-switch v-model="form.aria2.enabled" />
              </el-form-item>
              <el-form-item label="RPC URL">
                <el-input v-model="form.aria2.rpc_url" placeholder="http://localhost:6800/jsonrpc" />
              </el-form-item>
              <el-form-item label="RPC Secret">
                <el-input
                  v-model="form.aria2.secret"
                  type="password"
                  show-password
                  placeholder="留空不修改"
                />
              </el-form-item>
              <el-form-item label="默认下载目录">
                <el-input v-model="form.aria2.download_dir" placeholder="留空使用 aria2 默认路径" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="testConn('aria2')" :loading="testing === 'aria2'">
                  <el-icon><Connection /></el-icon> 测试连接
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
        </el-tabs>

        <el-form-item style="margin-top: 16px">
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="loadConfig">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 状态卡片 -->
    <el-card shadow="never" class="status-card">
      <template #header>
        <div class="card-title">
          <el-icon><Connection /></el-icon> 连接状态
          <el-button
            size="small"
            style="margin-left: auto"
            @click="loadStatus"
            :loading="statusLoading"
          >
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <el-descriptions :column="3" border v-if="status">
        <el-descriptions-item label="下载器类型">
          <el-tag size="small">{{ status.type || '-' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="连接状态">
          <el-tag v-if="status.connected" type="success" size="small">已连接</el-tag>
          <el-tag v-else type="danger" size="small">未连接</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="登录状态">
          <el-tag v-if="status.logged_in" type="success" size="small">已登录</el-tag>
          <el-tag v-else type="warning" size="small">未登录</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="版本">{{ status.version || '-' }}</el-descriptions-item>
        <el-descriptions-item label="下载速度">{{ formatSpeed(status.download_speed) }}</el-descriptions-item>
        <el-descriptions-item label="上传速度">{{ formatSpeed(status.upload_speed) }}</el-descriptions-item>
        <el-descriptions-item label="服务器地址">
          {{ status.host ? `${status.host}:${status.port}` : (status.rpc_url || '-') }}
        </el-descriptions-item>
        <el-descriptions-item label="激活任务数">{{ status.active_tasks ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="启用状态">
          <el-tag v-if="status.enabled" type="success" size="small">已启用</el-tag>
          <el-tag v-else type="info" size="small">未启用</el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="无状态数据（请先配置并激活下载器）" />
    </el-card>

    <!-- 任务列表 -->
    <el-card shadow="never" class="tasks-card">
      <template #header>
        <div class="card-title">
          <el-icon><List /></el-icon> 任务列表
          <div class="header-actions">
            <el-select v-model="taskFilter" placeholder="全部" size="small" style="width: 140px" clearable>
              <el-option label="全部" value="" />
              <el-option label="等待中" value="pending" />
              <el-option label="下载中" value="downloading" />
              <el-option label="做种中" value="seeding" />
              <el-option label="已完成" value="completed" />
              <el-option label="已暂停" value="paused" />
              <el-option label="错误" value="error" />
            </el-select>
            <el-button size="small" @click="loadTasks" :loading="tasksLoading">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
            <el-button size="small" type="primary" @click="addDialogVisible = true">
              <el-icon><Plus /></el-icon> 添加任务
            </el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="tasksLoading" :data="tasks" max-height="500" empty-text="暂无任务">
        <el-table-column label="名称" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.name || row.id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress :percentage="row.progress || 0" :status="progressStatus(row.status)" :stroke-width="14" />
          </template>
        </el-table-column>
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="下载速度" width="110">
          <template #default="{ row }">{{ formatSpeed(row.download_speed) }}</template>
        </el-table-column>
        <el-table-column label="上传速度" width="110">
          <template #default="{ row }">{{ formatSpeed(row.upload_speed) }}</template>
        </el-table-column>
        <el-table-column label="剩余时间" width="100">
          <template #default="{ row }">{{ formatEta(row.eta) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'downloading' || row.status === 'seeding' || row.status === 'pending'"
              size="small"
              text
              type="warning"
              @click="onPause(row)"
            >
              暂停
            </el-button>
            <el-button
              v-if="row.status === 'paused'"
              size="small"
              text
              type="success"
              @click="onResume(row)"
            >
              恢复
            </el-button>
            <el-button size="small" text type="danger" @click="onCancel(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 添加任务对话框 -->
    <el-dialog v-model="addDialogVisible" title="添加下载任务" width="540px">
      <el-form :model="addForm" label-width="120px">
        <el-form-item label="链接">
          <el-input
            v-model="addForm.url"
            type="textarea"
            :rows="4"
            placeholder="磁力链接（magnet:?xt=...）或 HTTP/HTTPS 种子 URL"
          />
        </el-form-item>
        <el-form-item label="下载目录">
          <el-input v-model="addForm.download_dir" placeholder="留空使用默认下载目录" />
        </el-form-item>
        <el-form-item label="任务名称">
          <el-input v-model="addForm.name" placeholder="（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="onAddTask" :loading="adding">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Download, Refresh, Setting, Connection, List, Plus
} from '@element-plus/icons-vue'
import {
  getDownloaderConfig, updateDownloaderConfig,
  getDownloaderStatus, listDownloaderTasks,
  addDownloaderTask, cancelDownloaderTask,
  pauseDownloaderTask, resumeDownloaderTask,
  testDownloaderConnection
} from '@/api'

const loading = ref(false)
const saving = ref(false)
const testing = ref('')
const statusLoading = ref(false)
const tasksLoading = ref(false)
const adding = ref(false)

const activeTab = ref('qbittorrent')
const taskFilter = ref('')
const addDialogVisible = ref(false)

const form = reactive({
  active: '',
  qbittorrent: {
    enabled: false,
    host: '127.0.0.1',
    port: 8080,
    username: 'admin',
    password: '',
    verify_ssl: true,
    download_dir: ''
  },
  transmission: {
    enabled: false,
    host: '127.0.0.1',
    port: 9091,
    username: '',
    password: '',
    use_ssl: false,
    rpc_path: '/transmission/rpc',
    download_dir: ''
  },
  aria2: {
    enabled: false,
    rpc_url: 'http://localhost:6800/jsonrpc',
    secret: '',
    download_dir: ''
  }
})

const addForm = reactive({
  url: '',
  download_dir: '',
  name: ''
})

const status = ref(null)
const tasks = ref([])

const activeLabel = computed(() => {
  const m = { qbittorrent: 'qBittorrent', transmission: 'Transmission', aria2: 'Aria2' }
  return m[form.active] || form.active
})

// ============== 工具函数 ==============
const formatSize = (bytes) => {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Number(bytes)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(2)} ${units[i]}`
}

const formatSpeed = (bytesPerSec) => {
  if (!bytesPerSec || bytesPerSec <= 0) return '0 B/s'
  return formatSize(bytesPerSec) + '/s'
}

const formatEta = (eta) => {
  if (eta === undefined || eta === null || eta < 0) return '-'
  if (eta === 0) return '已完成'
  const s = Math.floor(eta)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

const statusLabel = (s) => {
  const m = {
    pending: '等待中',
    downloading: '下载中',
    seeding: '做种中',
    completed: '已完成',
    paused: '已暂停',
    error: '错误',
    unknown: '未知'
  }
  return m[s] || s || '-'
}

const statusTagType = (s) => {
  const m = {
    pending: 'info',
    downloading: '',
    seeding: 'success',
    completed: 'success',
    paused: 'warning',
    error: 'danger',
    unknown: 'info'
  }
  return m[s] || 'info'
}

const progressStatus = (s) => {
  if (s === 'completed') return 'success'
  if (s === 'error') return 'exception'
  return undefined
}

// ============== 加载 ==============
const loadConfig = async () => {
  try {
    const res = await getDownloaderConfig()
    form.active = res.active || ''
    form.qbittorrent = {
      enabled: res.qbittorrent?.enabled ?? false,
      host: res.qbittorrent?.host ?? '127.0.0.1',
      port: res.qbittorrent?.port ?? 8080,
      username: res.qbittorrent?.username ?? 'admin',
      password: '', // 不回显
      verify_ssl: res.qbittorrent?.verify_ssl ?? true,
      download_dir: res.qbittorrent?.download_dir || ''
    }
    form.transmission = {
      enabled: res.transmission?.enabled ?? false,
      host: res.transmission?.host ?? '127.0.0.1',
      port: res.transmission?.port ?? 9091,
      username: res.transmission?.username ?? '',
      password: '',
      use_ssl: res.transmission?.use_ssl ?? false,
      rpc_path: res.transmission?.rpc_path ?? '/transmission/rpc',
      download_dir: res.transmission?.download_dir || ''
    }
    form.aria2 = {
      enabled: res.aria2?.enabled ?? false,
      rpc_url: res.aria2?.rpc_url ?? 'http://localhost:6800/jsonrpc',
      secret: '',
      download_dir: res.aria2?.download_dir || ''
    }
    // 自动切换到激活的 tab
    if (form.active) activeTab.value = form.active
  } catch (e) {
    console.error('加载配置失败', e)
  }
}

const loadStatus = async () => {
  statusLoading.value = true
  try {
    status.value = await getDownloaderStatus()
  } catch (e) {
    // 静默：未配置激活下载器会返回 400
    status.value = null
  } finally {
    statusLoading.value = false
  }
}

const loadTasks = async () => {
  tasksLoading.value = true
  try {
    tasks.value = await listDownloaderTasks(taskFilter.value || undefined)
  } catch (e) {
    tasks.value = []
  } finally {
    tasksLoading.value = false
  }
}

const loadAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadConfig(), loadStatus(), loadTasks()])
  } finally {
    loading.value = false
  }
}

// ============== 操作 ==============
const saveConfig = async () => {
  // 校验：active 必须为已启用的下载器
  if (form.active) {
    const sub = form[form.active]
    if (!sub || !sub.enabled) {
      ElMessage.warning('激活的下载器必须先启用')
      return
    }
  }
  saving.value = true
  try {
    await updateDownloaderConfig({
      active: form.active,
      qbittorrent: { ...form.qbittorrent },
      transmission: { ...form.transmission },
      aria2: { ...form.aria2 }
    })
    ElMessage.success('配置已保存')
    await Promise.all([loadStatus(), loadTasks()])
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

const testConn = async (type) => {
  testing.value = type
  try {
    // 先保存配置（含明文密码），再测试
    await updateDownloaderConfig({
      active: form.active,
      qbittorrent: { ...form.qbittorrent },
      transmission: { ...form.transmission },
      aria2: { ...form.aria2 }
    })
    const res = await testDownloaderConnection(type)
    if (res.ok) {
      ElMessage.success(`连接成功：${res.status?.version || '未知版本'}`)
    } else {
      ElMessage.error(`连接失败：${res.msg || '请检查配置'}`)
    }
  } catch (e) {
    ElMessage.error('测试失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    testing.value = ''
  }
}

const onAddTask = async () => {
  if (!addForm.url) {
    ElMessage.warning('请输入链接')
    return
  }
  adding.value = true
  try {
    await addDownloaderTask({
      url: addForm.url,
      download_dir: addForm.download_dir || undefined,
      name: addForm.name || undefined
    })
    ElMessage.success('任务已添加')
    addDialogVisible.value = false
    addForm.url = ''
    addForm.download_dir = ''
    addForm.name = ''
    await loadTasks()
  } catch (e) {
    ElMessage.error('添加失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    adding.value = false
  }
}

const onPause = async (row) => {
  try {
    await pauseDownloaderTask(row.id)
    ElMessage.success('已暂停')
    await loadTasks()
  } catch (e) {
    ElMessage.error('暂停失败: ' + (e.response?.data?.detail || e.message))
  }
}

const onResume = async (row) => {
  try {
    await resumeDownloaderTask(row.id)
    ElMessage.success('已恢复')
    await loadTasks()
  } catch (e) {
    ElMessage.error('恢复失败: ' + (e.response?.data?.detail || e.message))
  }
}

const onCancel = async (row) => {
  try {
    await ElMessageBox.confirm(`确定取消任务 "${row.name || row.id}" 吗？`, '确认', {
      type: 'warning'
    })
    await cancelDownloaderTask(row.id)
    ElMessage.success('任务已取消')
    await loadTasks()
  } catch (e) {
    if (e === 'cancel') return
    ElMessage.error('取消失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => loadAll())
</script>

<style scoped>
.dl-page {
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
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.form-tip {
  margin-left: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}

.sub-tabs {
  margin-top: 8px;
}

.header-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
