<template>
  <div class="pan115-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Cloudy /></el-icon>
          115 网盘离线下载
        </h2>
        <div class="page-subtitle">
          磁力链 / HTTP 离线下载 · 文件浏览 · 自动入库
        </div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll">
          <el-icon><Refresh /></el-icon> 重载
        </el-button>
      </div>
    </div>

    <!-- Cookie 失效重新登录横幅 -->
    <el-alert
      v-if="needRelogin"
      type="warning"
      :closable="false"
      show-icon
      class="relogin-banner"
      title="115 网盘 Cookie 已失效，请重新登录"
    >
      <template #default>
        <span>点击下方按钮将自动打开浏览器窗口供您登录 115 网盘。</span>
        <el-button
          size="small"
          type="warning"
          @click="startBrowserLogin"
          :loading="browserStarting"
          style="margin-left: 8px"
        >
          <el-icon><Monitor /></el-icon> 浏览器重新登录
        </el-button>
      </template>
    </el-alert>

    <!-- 配置卡片 -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-title">
          <el-icon><Setting /></el-icon> 账号配置
          <el-tag v-if="form.enabled" type="success" size="small" style="margin-left: 8px">已启用</el-tag>
          <el-tag v-else type="info" size="small" style="margin-left: 8px">未启用</el-tag>
        </div>
      </template>
      <el-form :model="form" label-width="160px" style="max-width: 720px">
        <el-form-item label="启用 115 网盘">
          <el-switch v-model="form.enabled" />
          <span class="form-tip">开启后将自动验证凭据并对接 115 网盘 Web API</span>
        </el-form-item>
        <el-form-item label="Cookie">
          <el-input
            v-model="form.cookies"
            type="textarea"
            :rows="3"
            placeholder="从浏览器抓取的 Cookie 字符串，如 UID=xxx; CID=xxx; SEID=xxx"
          />
          <span class="form-tip">优先使用 Cookie 认证（推荐，从浏览器开发者工具复制）</span>
        </el-form-item>
        <el-form-item label="Access Token">
          <el-input v-model="form.token" show-password placeholder="可选，留空则使用 Cookie 认证" />
          <span class="form-tip">部分接口支持 Token 认证（可与 Cookie 二选一）</span>
        </el-form-item>
        <el-form-item label="目标文件夹 ID">
          <el-input v-model="form.target_folder_id" placeholder="留空则使用根目录（0）" />
          <span class="form-tip">离线下载文件保存到的文件夹 CID</span>
        </el-form-item>
        <el-form-item label="自动入库">
          <el-switch v-model="form.auto_link_to_library" />
          <span class="form-tip">离线下载完成后自动将视频文件入库到本地媒体库</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="loadConfig">重置</el-button>
          <el-button type="success" @click="doLogin" :loading="loggingIn">
            <el-icon><Key /></el-icon> 立即登录
          </el-button>
          <el-button type="warning" @click="startBrowserLogin" :loading="browserStarting">
            <el-icon><Monitor /></el-icon> 浏览器登录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 状态卡片 -->
    <el-card shadow="never" class="status-card">
      <template #header>
        <div class="card-title">
          <el-icon><Connection /></el-icon> 连接状态
        </div>
      </template>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="服务状态">
          <el-tag v-if="status.started" type="success" size="small">已启动</el-tag>
          <el-tag v-else type="info" size="small">未启动</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="登录状态">
          <el-tag v-if="status.logged_in" type="success" size="small">已登录</el-tag>
          <el-tag v-else type="warning" size="small">未登录</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="凭据配置">
          <el-tag v-if="status.has_credentials" type="success" size="small">已配置</el-tag>
          <el-tag v-else type="danger" size="small">未配置</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="启用状态">
          <el-tag v-if="status.enabled" type="success" size="small">已启用</el-tag>
          <el-tag v-else type="info" size="small">未启用</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="目标文件夹 ID">{{ status.target_folder_id || '0' }}</el-descriptions-item>
        <el-descriptions-item label="自动入库">
          <el-tag v-if="status.auto_link_to_library" type="success" size="small">开启</el-tag>
          <el-tag v-else type="info" size="small">关闭</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 离线下载任务 -->
    <el-card shadow="never" class="tasks-card">
      <template #header>
        <div class="card-title">
          <el-icon><Download /></el-icon> 离线下载任务
          <div class="header-actions">
            <el-button size="small" @click="loadTasks" :loading="loadingTasks">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
            <el-button size="small" type="primary" @click="addTaskDialogVisible = true">
              <el-icon><Plus /></el-icon> 添加任务
            </el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loadingTasks" :data="tasks" max-height="400" empty-text="暂无离线下载任务">
        <el-table-column label="文件名" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.file_name || row.info_hash || '-' }}</template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.type || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ row.size_text || formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status_text || '未知' }}</el-tag>
            <span v-if="row.status === 1" style="margin-left: 4px; font-size: 12px">{{ row.percent }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="添加时间" width="180" prop="added_time" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              size="small"
              type="danger"
              text
              @click="cancelTask(row)"
              :loading="cancellingHash === row.info_hash"
            >
              <el-icon><Delete /></el-icon> 取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 文件浏览 -->
    <el-card shadow="never" class="browser-card">
      <template #header>
        <div class="card-title">
          <el-icon><FolderOpened /></el-icon> 文件浏览
          <div class="header-actions">
            <el-breadcrumb separator="/">
              <el-breadcrumb-item
                v-for="(seg, idx) in breadcrumb"
                :key="idx"
                @click="navigateTo(seg.cid)"
              >
                <span class="breadcrumb-link">{{ seg.name }}</span>
              </el-breadcrumb-item>
            </el-breadcrumb>
            <el-button size="small" @click="goUp" :disabled="currentCid === '0'">
              <el-icon><Top /></el-icon> 上级
            </el-button>
            <el-button size="small" @click="loadFiles(currentCid)" :loading="listing">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
            <el-button size="small" type="primary" @click="scanDialogVisible = true">
              <el-icon><Search /></el-icon> 扫描文件
            </el-button>
          </div>
        </div>
      </template>

      <el-input v-model="currentCid" placeholder="0" style="margin-bottom: 12px" @keyup.enter="loadFiles(currentCid)">
        <template #prepend>文件夹 CID</template>
        <template #append>
          <el-button @click="loadFiles(currentCid)" :loading="listing">前往</el-button>
        </template>
      </el-input>

      <el-table v-loading="listing" :data="files" max-height="500" @row-dblclick="onRowDblClick" empty-text="暂无文件">
        <el-table-column label="名称" min-width="280">
          <template #default="{ row }">
            <el-icon v-if="row.is_dir" style="color: var(--el-color-primary)"><Folder /></el-icon>
            <el-icon v-else style="color: var(--el-color-success)"><Document /></el-icon>
            <span style="margin-left: 6px">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_dir" size="small">目录</el-tag>
            <el-tag v-else size="small" type="info">{{ row.ext || '文件' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ row.is_dir ? '-' : (row.size_text || formatSize(row.size)) }}</template>
        </el-table-column>
        <el-table-column label="修改时间" width="180" prop="modified" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button v-if="row.is_dir" size="small" text @click.stop="enterDir(row)">
              进入
            </el-button>
            <el-button v-else size="small" text @click.stop="copyFid(row)">
              复制 ID
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 添加任务对话框 -->
    <el-dialog v-model="addTaskDialogVisible" title="添加离线下载任务" width="540px">
      <el-form label-width="120px">
        <el-form-item label="链接">
          <el-input
            v-model="addTaskForm.magnet_url"
            type="textarea"
            :rows="4"
            placeholder="磁力链接 magnet:?xt=... / HTTP(s) 链接 / ed2k 链接"
          />
        </el-form-item>
        <el-form-item label="保存目录 CID">
          <el-input v-model="addTaskForm.target_cid" placeholder="留空则使用配置中的目标文件夹" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="doAddTask" :loading="addingTask">
            <el-icon><Download /></el-icon> 添加任务
          </el-button>
        </el-form-item>
      </el-form>
    </el-dialog>

    <!-- 扫描对话框 -->
    <el-dialog v-model="scanDialogVisible" title="扫描 115 网盘文件" width="540px">
      <el-form label-width="120px">
        <el-form-item label="起始文件夹 CID">
          <el-input v-model="scanForm.folder_id" placeholder="留空则从根目录开始" />
        </el-form-item>
        <el-form-item label="递归扫描">
          <el-switch v-model="scanForm.recursive" />
        </el-form-item>
        <el-form-item label="最大深度">
          <el-input-number v-model="scanForm.max_depth" :min="1" :max="20" :disabled="!scanForm.recursive" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="doScan" :loading="scanning">
            <el-icon><Search /></el-icon> 开始扫描
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="scanResult" class="scan-result">
        <el-alert
          :type="scanResult.failed ? 'warning' : 'success'"
          :title="`扫描完成：共找到 ${scanResult.total} 个文件`"
          :closable="false"
          show-icon
        />
        <el-table :data="scanResult.files?.slice(0, 50)" max-height="320" style="margin-top: 12px" size="small">
          <el-table-column label="文件名" prop="name" min-width="240" show-overflow-tooltip />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ row.size_text || formatSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="CID" prop="cid" width="120" show-overflow-tooltip />
        </el-table>
        <p v-if="scanResult.total > 50" class="more-tip">仅显示前 50 条，共 {{ scanResult.total }} 条</p>
      </div>
    </el-dialog>

    <!-- 浏览器登录对话框 -->
    <el-dialog
      v-model="browserLoginVisible"
      title="浏览器登录 115 网盘"
      width="480px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="browserLoginDone"
    >
      <div class="browser-login-body">
        <el-steps :active="browserStep" align-center finish-status="success" style="margin-bottom: 16px">
          <el-step title="启动" />
          <el-step title="等待登录" />
          <el-step title="保存Cookie" />
          <el-step title="校验" />
        </el-steps>
        <div v-if="browserLoginDone" class="browser-login-result">
          <el-icon :class="browserLoginSuccess ? 'ok' : 'fail'">
            <CircleCheck v-if="browserLoginSuccess" />
            <CircleClose v-else />
          </el-icon>
          <p>{{ browserLoginMessage }}</p>
        </div>
        <div v-else class="browser-login-status">
          <el-icon class="is-loading" style="font-size: 28px; color: var(--el-color-primary)"><Loading /></el-icon>
          <p>{{ browserStatusText || '正在启动浏览器...' }}</p>
          <p class="tip">请在弹出的浏览器窗口中完成 115 网盘登录，登录后会自动保存 Cookie 并校验。</p>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Cloudy, Refresh, Setting, Key, Connection, FolderOpened,
  Top, Search, Folder, Document, Download, Plus, Delete,
  CircleCheck, CircleClose, Loading, Monitor
} from '@element-plus/icons-vue'
import {
  getPan115Config, updatePan115Config, loginPan115, getPan115Status,
  listPan115OfflineTasks, addPan115OfflineTask, cancelPan115OfflineTask,
  listPan115Files, scanPan115, loginPan115Browser, getPan115BrowserStatus
} from '@/api'

const form = reactive({
  enabled: false,
  cookies: '',
  token: '',
  auto_link_to_library: false,
  target_folder_id: '',
})

const status = ref({
  enabled: false,
  started: false,
  logged_in: false,
  has_credentials: false,
  auto_link_to_library: false,
  target_folder_id: '0',
  last_login_at: 0,
})

// 离线任务
const tasks = ref([])
const loadingTasks = ref(false)
const cancellingHash = ref('')
const addTaskDialogVisible = ref(false)
const addTaskForm = reactive({ magnet_url: '', target_cid: '' })
const addingTask = ref(false)

// 文件浏览
const currentCid = ref('0')
const folderStack = ref(['0'])  // 用于上级导航
const files = ref([])
const listing = ref(false)

// 扫描
const scanDialogVisible = ref(false)
const scanning = ref(false)
const scanForm = reactive({ folder_id: '', recursive: true, max_depth: 5 })
const scanResult = ref(null)

const saving = ref(false)
const loggingIn = ref(false)

// Cookie 失效重新登录
const needRelogin = ref(false)
const browserLoginVisible = ref(false)
const browserStarting = ref(false)
const browserLoginDone = ref(false)
const browserLoginSuccess = ref(false)
const browserLoginMessage = ref('')
const browserStatusText = ref('')
const browserStep = ref(0)

const breadcrumb = computed(() => {
  const result = [{ name: '根目录', cid: '0' }]
  for (let i = 1; i < folderStack.value.length; i++) {
    const cid = folderStack.value[i]
    result.push({ name: cid, cid })
  }
  return result
})

const formatSize = (bytes) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let fsize = parseFloat(bytes)
  let idx = 0
  while (fsize >= 1024 && idx < units.length - 1) {
    fsize /= 1024
    idx++
  }
  return `${fsize.toFixed(2)} ${units[idx]}`
}

const statusTagType = (status) => {
  const map = { 0: 'info', 1: 'warning', 2: 'success', '-1': 'danger' }
  return map[String(status)] || 'info'
}

const loadConfig = async () => {
  try {
    const res = await getPan115Config()
    form.enabled = !!res.enabled
    form.cookies = ''  // 不回显敏感字段
    form.token = ''
    form.auto_link_to_library = !!res.auto_link_to_library
    form.target_folder_id = res.target_folder_id || ''
  } catch (e) {
    console.error(e)
  }
}

const loadStatus = async () => {
  try {
    const s = await getPan115Status()
    status.value = s
    needRelogin.value = !!s.need_relogin
  } catch (e) {
    console.error(e)
  }
}

const loadTasks = async () => {
  loadingTasks.value = true
  try {
    const res = await listPan115OfflineTasks()
    tasks.value = res.tasks || []
  } catch (e) {
    handleAuthError(e, '获取离线任务失败')
    tasks.value = []
  } finally {
    loadingTasks.value = false
  }
}

const loadFiles = async (cid) => {
  listing.value = true
  try {
    const target = cid || '0'
    const res = await listPan115Files(target)
    files.value = res.files || []
    currentCid.value = res.cid || target
  } catch (e) {
    handleAuthError(e, '列目录失败')
    files.value = []
  } finally {
    listing.value = false
  }
}

const loadAll = async () => {
  await Promise.all([loadConfig(), loadStatus()])
  if (status.value.started || status.value.enabled) {
    await Promise.all([loadTasks(), loadFiles('0')])
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await updatePan115Config({
      enabled: form.enabled,
      cookies: form.cookies || undefined,
      token: form.token || undefined,
      auto_link_to_library: form.auto_link_to_library,
      target_folder_id: form.target_folder_id || undefined,
    })
    ElMessage.success('配置已保存，重启后端后完全生效')
    await loadStatus()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

const doLogin = async () => {
  loggingIn.value = true
  try {
    // 先保存配置（包含凭据），再登录
    if (form.cookies || form.token) {
      await updatePan115Config({
        cookies: form.cookies || undefined,
        token: form.token || undefined,
      })
    }
    await loginPan115({})
    ElMessage.success('登录成功')
    needRelogin.value = false
    await loadStatus()
  } catch (e) {
    ElMessage.error('登录失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loggingIn.value = false
  }
}

// ============== 浏览器登录（Cookie 失效时重新登录） ==============
let browserPollTimer = null

const statusToStep = (st) => {
  switch (st) {
    case 'starting':
    case 'opening':
      return 1
    case 'waiting':
      return 2
    case 'saving':
      return 3
    case 'completed':
    case 'failed':
      return 4
    default:
      return 0
  }
}

const startBrowserLogin = async () => {
  if (browserLoginVisible.value && !browserLoginDone.value) return
  browserLoginVisible.value = true
  browserLoginDone.value = false
  browserLoginSuccess.value = false
  browserLoginMessage.value = ''
  browserStep.value = 0
  browserStarting.value = true
  try {
    const res = await loginPan115Browser()
    browserStarting.value = false
    browserStatusText.value = res.message || '浏览器启动中...'
    startBrowserPolling()
  } catch (e) {
    browserStarting.value = false
    browserLoginDone.value = true
    browserLoginSuccess.value = false
    browserLoginMessage.value = '启动失败: ' + (e.response?.data?.detail || e.message)
    stopBrowserPolling()
  }
}

const startBrowserPolling = () => {
  stopBrowserPolling()
  browserPollTimer = setInterval(async () => {
    try {
      const res = await getPan115BrowserStatus()
      const st = res.status
      browserStep.value = statusToStep(st)
      browserStatusText.value = res.message || ''
      if (st === 'completed') {
        browserStep.value = 4
        await finalizeBrowserLogin(true)
      } else if (st === 'failed') {
        await finalizeBrowserLogin(false)
      }
    } catch (e) {
      // 轮询失败忽略，继续
    }
  }, 1500)
}

const stopBrowserPolling = () => {
  if (browserPollTimer) {
    clearInterval(browserPollTimer)
    browserPollTimer = null
  }
}

const finalizeBrowserLogin = async (success) => {
  stopBrowserPolling()
  browserLoginDone.value = true
  browserLoginSuccess.value = success
  if (success) {
    try {
      await loginPan115({})  // 用已保存的 Cookie 自动校验
      needRelogin.value = false
      browserLoginMessage.value = 'Cookie 已保存并校验成功，115 网盘登录有效。'
      await loadStatus()
      ElMessage.success('115 网盘登录成功')
    } catch (e) {
      browserLoginSuccess.value = false
      browserLoginMessage.value = 'Cookie 已保存，但校验失败: ' + (e.response?.data?.detail || e.message)
    }
  } else {
    browserLoginMessage.value = '登录未完成或获取 Cookie 失败，请重试。'
  }
}

// 统一处理 115 接口鉴权失效：标记需重新登录并自动弹窗
const handleAuthError = (e, fallbackMsg = '操作失败') => {
  const msg = (e.response?.data?.detail || e.message || fallbackMsg).toString()
  const isAuth = /未登录|401|请先登录|重新登录|失效|权限|token|cookie/i.test(msg)
  if (isAuth && !needRelogin.value) {
    needRelogin.value = true
    if (!browserLoginVisible.value) {
      startBrowserLogin()
    }
  }
  ElMessage.error((fallbackMsg ? fallbackMsg + ': ' : '') + msg)
}

const doAddTask = async () => {
  if (!addTaskForm.magnet_url) {
    ElMessage.warning('请输入链接')
    return
  }
  addingTask.value = true
  try {
    const res = await addPan115OfflineTask(addTaskForm.magnet_url, addTaskForm.target_cid || undefined)
    ElMessage.success(res.message || '任务已添加')
    addTaskForm.magnet_url = ''
    addTaskForm.target_cid = ''
    addTaskDialogVisible.value = false
    await loadTasks()
  } catch (e) {
    handleAuthError(e, '添加任务失败')
  } finally {
    addingTask.value = false
  }
}

const cancelTask = async (row) => {
  try {
    await ElMessageBox.confirm(`确定取消任务 "${row.file_name || row.info_hash}" 吗？`, '确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  cancellingHash.value = row.info_hash
  try {
    const res = await cancelPan115OfflineTask(row.info_hash)
    ElMessage.success(res.message || '任务已取消')
    await loadTasks()
  } catch (e) {
    handleAuthError(e, '取消任务失败')
  } finally {
    cancellingHash.value = ''
  }
}

const enterDir = (row) => {
  folderStack.value.push(row.cid)
  loadFiles(row.cid)
}

const onRowDblClick = (row) => {
  if (row.is_dir) enterDir(row)
}

const goUp = () => {
  if (folderStack.value.length <= 1) return
  folderStack.value.pop()
  const parent = folderStack.value[folderStack.value.length - 1]
  loadFiles(parent)
}

const navigateTo = (cid) => {
  // 截断到指定层级
  const idx = folderStack.value.indexOf(cid)
  if (idx >= 0) {
    folderStack.value = folderStack.value.slice(0, idx + 1)
  }
  loadFiles(cid)
}

const copyFid = async (row) => {
  try {
    await navigator.clipboard.writeText(row.fid || row.cid || '')
    ElMessage.success('已复制文件 ID')
  } catch {
    ElMessage.warning('复制失败')
  }
}

const doScan = async () => {
  scanning.value = true
  scanResult.value = null
  try {
    const res = await scanPan115({
      folder_id: scanForm.folder_id || undefined,
      recursive: scanForm.recursive,
      max_depth: scanForm.max_depth,
    })
    scanResult.value = res
    ElMessage.success(`扫描完成，共 ${res.total} 个文件`)
  } catch (e) {
    handleAuthError(e, '扫描失败')
  } finally {
    scanning.value = false
  }
}

onMounted(() => loadAll())
onUnmounted(() => stopBrowserPolling())
</script>

<style scoped>
.pan115-page {
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

.header-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  align-items: center;
}

.breadcrumb-link {
  cursor: pointer;
  color: var(--el-color-primary);
}

.breadcrumb-link:hover {
  text-decoration: underline;
}

.scan-result {
  margin-top: 16px;
}

.more-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
}

.relogin-banner {
  margin-bottom: 16px;
}

.browser-login-body {
  text-align: center;
}

.browser-login-status .tip {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 8px;
}

.browser-login-result .ok {
  font-size: 48px;
  color: var(--el-color-success);
}

.browser-login-result .fail {
  font-size: 48px;
  color: var(--el-color-danger);
}

.browser-login-result p {
  margin-top: 8px;
}
</style>
