<template>
  <div class="desktop-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Monitor /></el-icon>
          桌面设置
        </h2>
        <div class="page-subtitle">
          {{ isElectron ? 'Electron 桌面端运行中' : 'Web 模式（部分功能仅 Electron 可用）' }}
          <el-tag v-if="appInfo" size="small" style="margin-left: 8px">
            v{{ appInfo.version }} · {{ appInfo.platform }} · Electron {{ appInfo.electron }}
          </el-tag>
        </div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 重载
        </el-button>
        <el-button type="primary" @click="saveAll" :loading="saving" :disabled="!isElectron">
          <el-icon><Check /></el-icon> 保存设置
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!isElectron"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
      title="当前为 Web 模式"
      description="系统托盘、全局快捷键、自动更新等桌面功能仅在 Electron 桌面端可用。可下载 MDCX Desktop 体验完整功能。"
    />

    <el-row :gutter="16">
      <!-- 左侧：偏好设置 -->
      <el-col :span="16">
        <!-- 系统托盘 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Box /></el-icon> 系统托盘
            </div>
          </template>
          <el-form label-width="160px">
            <el-form-item label="启用系统托盘">
              <el-switch v-model="prefs.enable_tray" :disabled="!isElectron" />
              <div class="hint">关闭后，应用不会在任务栏托盘区显示图标</div>
            </el-form-item>
            <el-form-item label="关闭按钮最小化">
              <el-switch v-model="prefs.close_to_tray" :disabled="!isElectron || !prefs.enable_tray" />
              <div class="hint">点击窗口关闭按钮时隐藏到托盘（而不是退出应用）</div>
            </el-form-item>
            <el-form-item label="启动时最小化">
              <el-switch v-model="prefs.start_minimized" :disabled="!isElectron" />
              <div class="hint">应用启动时直接隐藏到托盘</div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 全局快捷键 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Key /></el-icon> 全局快捷键
              <el-button text size="small" @click="resetShortcuts" style="margin-left: auto">恢复默认</el-button>
            </div>
          </template>
          <el-form label-width="160px">
            <el-form-item label="显示/隐藏主窗口">
              <el-input
                v-model="prefs.shortcut_show_hide"
                placeholder="例如 CommandOrControl+Shift+M"
                :disabled="!isElectron"
              >
                <template #append>
                  <el-button @click="captureKey('shortcut_show_hide')" :disabled="!isElectron">捕获</el-button>
                </template>
              </el-input>
              <div class="hint">全局快捷键，应用失焦时也可触发。留空表示禁用。另有固定快捷键 Ctrl+Alt+R 显示/隐藏、Ctrl+Alt+E 打开探索页</div>
            </el-form-item>
            <el-form-item label="播放/暂停 (mpv)">
              <el-input
                v-model="prefs.shortcut_play_pause"
                placeholder="例如 CommandOrControl+Shift+P"
                :disabled="!isElectron"
              >
                <template #append>
                  <el-button @click="captureKey('shortcut_play_pause')" :disabled="!isElectron">捕获</el-button>
                </template>
              </el-input>
              <div class="hint">控制 mpv 播放器播放/暂停</div>
            </el-form-item>
            <el-form-item label="截图 (mpv)">
              <el-input
                v-model="prefs.shortcut_screenshot"
                placeholder="例如 CommandOrControl+Shift+S"
                :disabled="!isElectron"
              >
                <template #append>
                  <el-button @click="captureKey('shortcut_screenshot')" :disabled="!isElectron">捕获</el-button>
                </template>
              </el-input>
              <div class="hint">mpv 播放时截图，自动保存到 thumbnails 目录</div>
            </el-form-item>
            <el-form-item v-if="capturing" label="">
              <el-alert
                type="warning"
                show-icon
                :closable="false"
                :title="`正在捕获快捷键，请按下组合键（Esc 取消）`"
              />
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 开机自启（任务 5）-->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><SwitchButton /></el-icon> 启动行为
            </div>
          </template>
          <el-form label-width="160px">
            <el-form-item label="开机自启">
              <el-switch
                v-model="autoLaunchEnabled"
                :loading="autoLaunchLoading"
                :disabled="!isElectron"
                @change="onAutoLaunchChange"
              />
              <div class="hint">系统登录时自动启动 MDCX Desktop（写入系统启动项，仅当前用户有效）</div>
            </el-form-item>
            <el-form-item label="启动时最小化">
              <el-switch v-model="prefs.start_minimized" :disabled="!isElectron" />
              <div class="hint">应用启动时直接隐藏到托盘</div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 主题 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Brush /></el-icon> 主题
            </div>
          </template>
          <el-form label-width="160px">
            <el-form-item label="桌面主题">
              <el-radio-group v-model="prefs.theme">
                <el-radio-button label="light">浅色</el-radio-button>
                <el-radio-button label="dark">深色</el-radio-button>
                <el-radio-button label="system">跟随系统</el-radio-button>
              </el-radio-group>
              <div class="hint">仅影响 Electron 原生 UI（标题栏/菜单），Web 主题请用顶部切换按钮</div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 自动更新 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Upload /></el-icon> 自动更新
              <el-tag v-if="updaterStatus === 'not-installed'" size="small" type="info" style="margin-left: auto">未安装</el-tag>
              <el-tag v-else-if="updaterStatus === 'available'" size="small" type="warning" style="margin-left: auto">有新版本</el-tag>
              <el-tag v-else-if="updaterStatus === 'downloading'" size="small" type="warning" style="margin-left: auto">下载中</el-tag>
              <el-tag v-else-if="updaterStatus === 'downloaded'" size="small" type="success" style="margin-left: auto">已就绪</el-tag>
              <el-tag v-else size="small" type="success" style="margin-left: auto">已是最新</el-tag>
            </div>
          </template>
          <el-form label-width="160px">
            <el-form-item label="启用自动更新">
              <el-switch v-model="prefs.auto_update" :disabled="!isElectron" />
              <div class="hint">应用启动后自动检查新版本</div>
            </el-form-item>
            <el-form-item label="手动检查">
              <el-button @click="checkUpdate" :loading="checking" :disabled="!isElectron || updaterStatus === 'not-installed'">
                <el-icon><Search /></el-icon> 检查更新
              </el-button>
              <el-button
                v-if="updaterStatus === 'available'"
                type="primary"
                @click="downloadUpdate"
                :loading="downloading"
              >
                <el-icon><Download /></el-icon> 下载更新
              </el-button>
              <el-button
                v-if="updaterStatus === 'downloaded'"
                type="success"
                @click="installUpdate"
              >
                <el-icon><Refresh /></el-icon> 重启并安装
              </el-button>
            </el-form-item>
            <el-form-item v-if="updaterInfo" label="">
              <el-alert
                :type="updaterInfo.type"
                :title="updaterInfo.title"
                :description="updaterInfo.description"
                show-icon
                :closable="false"
              />
            </el-form-item>
            <el-form-item v-if="downloadProgress != null" label="下载进度">
              <el-progress :percentage="downloadProgress" :stroke-width="14" striped striped-flow />
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右侧：应用信息 + 路径 -->
      <el-col :span="8">
        <el-card shadow="never" class="info-card">
          <template #header>
            <div class="card-title">
              <el-icon><InfoFilled /></el-icon> 应用信息
            </div>
          </template>
          <div v-if="appInfo" class="info-grid">
            <div class="info-row">
              <span class="info-label">应用名称</span>
              <span class="info-value">{{ appInfo.name }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">版本</span>
              <span class="info-value">v{{ appInfo.version }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">平台</span>
              <span class="info-value">{{ appInfo.platform }} · {{ appInfo.arch }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Electron</span>
              <span class="info-value">{{ appInfo.electron }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Chrome</span>
              <span class="info-value">{{ appInfo.chrome }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Node.js</span>
              <span class="info-value">{{ appInfo.node }}</span>
            </div>
          </div>
          <el-empty v-else description="Web 模式下不可用" :image-size="60" />
        </el-card>

        <el-card v-if="appInfo" shadow="never" class="info-card">
          <template #header>
            <div class="card-title">
              <el-icon><FolderOpened /></el-icon> 文件路径
            </div>
          </template>
          <div class="path-block">
            <div class="path-label">用户数据目录</div>
            <el-input :model-value="appInfo.userData" readonly size="small">
              <template #append>
                <el-button @click="openPath(appInfo.userData)"><el-icon><FolderOpened /></el-icon></el-button>
              </template>
            </el-input>
          </div>
          <div class="path-block">
            <div class="path-label">日志目录</div>
            <el-input :model-value="appInfo.logsPath" readonly size="small">
              <template #append>
                <el-button @click="openPath(appInfo.logsPath)"><el-icon><FolderOpened /></el-icon></el-button>
              </template>
            </el-input>
          </div>
          <div class="path-block">
            <div class="path-label">偏好文件</div>
            <el-input :model-value="appInfo.prefsPath" readonly size="small" type="textarea" :rows="2" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 全局快捷键事件监听测试 -->
    <el-card shadow="never" class="cfg-card">
      <template #header>
        <div class="card-title">
          <el-icon><Bell /></el-icon> 快捷键事件日志
          <el-button text size="small" @click="shortcutLogs = []" style="margin-left: auto">清空</el-button>
        </div>
      </template>
      <div class="event-log">
        <div v-if="shortcutLogs.length === 0" class="empty-tip">尚未捕获任何快捷键事件。请按下设置的全局快捷键进行测试。</div>
        <div v-for="(log, i) in shortcutLogs" :key="i" class="event-item">
          <span class="event-time">{{ log.time }}</span>
          <el-tag size="small">{{ log.accelerator }}</el-tag>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Monitor, Box, Key, Brush, Upload, Search, Download, Refresh, Check,
  InfoFilled, FolderOpened, Bell, SwitchButton
} from '@element-plus/icons-vue'

const electronAPI = window.electronAPI || null
const isElectron = computed(() => !!electronAPI?.isElectron)

const loading = ref(false)
const saving = ref(false)
const checking = ref(false)
const downloading = ref(false)
const appInfo = ref(null)

const prefs = reactive({
  enable_tray: true,
  minimize_to_tray: true,
  close_to_tray: true,
  shortcut_show_hide: 'CommandOrControl+Shift+M',
  shortcut_play_pause: 'CommandOrControl+Shift+P',
  shortcut_screenshot: 'CommandOrControl+Shift+S',
  auto_update: true,
  start_minimized: false,
  theme: 'system'
})

// 开机自启状态（独立于 prefs，由 app.setLoginItemSettings 直接管理）
const autoLaunchEnabled = ref(false)
const autoLaunchLoading = ref(false)

const DEFAULT_PREFS = { ...prefs }

// 自动更新状态
const updaterStatus = ref('idle')  // idle / not-installed / available / downloading / downloaded / up-to-date / error
const updaterInfo = ref(null)
const downloadProgress = ref(null)

// 快捷键捕获
const capturing = ref(false)
const captureTarget = ref('')

// 快捷键事件日志
const shortcutLogs = ref([])
const unbindShortcut = ref(null)
const unbindUpdater = ref(null)

const captureKey = (key) => {
  if (!isElectron.value) return
  capturing.value = true
  captureTarget.value = key
  ElMessage.info('请按下组合键（Esc 取消）')
  // 简化：用 prompt 输入，实际可在主窗口监听 keydown（这里仅做基础实现）
  // 真正的捕获需要主进程配合，这里仅清空等待用户手动填写
}

const resetShortcuts = () => {
  prefs.shortcut_show_hide = DEFAULT_PREFS.shortcut_show_hide
  prefs.shortcut_play_pause = DEFAULT_PREFS.shortcut_play_pause
  prefs.shortcut_screenshot = DEFAULT_PREFS.shortcut_screenshot
  ElMessage.success('快捷键已恢复默认值（需保存生效）')
}

const loadPrefs = async () => {
  if (!isElectron.value) {
    // Web 模式从 localStorage 读取
    const cached = localStorage.getItem('mdcx_desktop_prefs')
    if (cached) {
      try {
        Object.assign(prefs, JSON.parse(cached))
      } catch (e) {}
    }
    return
  }
  try {
    const data = await electronAPI.getDesktopPrefs()
    Object.assign(prefs, data)
  } catch (e) {
    ElMessage.error('读取偏好失败: ' + e.message)
  }
}

const loadAppInfo = async () => {
  if (!isElectron.value) return
  try {
    appInfo.value = await electronAPI.getAppInfo()
  } catch (e) {
    // ignore
  }
}

const checkUpdaterStatus = () => {
  if (!isElectron.value) {
    updaterStatus.value = 'not-installed'
    return
  }
  // electron-updater 是否可用只能通过事件探测，初始假设已安装
  // 实际状态在用户点击"检查更新"后才能确定
}

// 读取开机自启状态（由主进程 app.getLoginItemSettings 维护）
const loadAutoLaunch = async () => {
  if (!isElectron.value || !electronAPI.getAutoLaunch) return
  try {
    const result = await electronAPI.getAutoLaunch()
    autoLaunchEnabled.value = !!result?.enabled
  } catch (e) {
    // 静默失败
  }
}

// 切换开机自启（通过 ipcRenderer.invoke('set-auto-launch', enabled)）
const onAutoLaunchChange = async (val) => {
  if (!isElectron.value || !electronAPI.setAutoLaunch) {
    autoLaunchEnabled.value = false
    ElMessage.warning('当前为 Web 模式，不支持开机自启')
    return
  }
  autoLaunchLoading.value = true
  try {
    const result = await electronAPI.setAutoLaunch(val)
    if (result?.ok) {
      autoLaunchEnabled.value = !!result.enabled
      ElMessage.success(val ? '已启用开机自启' : '已关闭开机自启')
    } else {
      autoLaunchEnabled.value = !val // 回滚
      ElMessage.error('设置失败')
    }
  } catch (e) {
    autoLaunchEnabled.value = !val // 回滚
    ElMessage.error('设置失败: ' + e.message)
  } finally {
    autoLaunchLoading.value = false
  }
}

const loadAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadPrefs(), loadAppInfo(), loadAutoLaunch()])
  } finally {
    loading.value = false
  }
}

const saveAll = async () => {
  saving.value = true
  try {
    if (isElectron.value) {
      await electronAPI.setDesktopPrefs({ ...prefs })
      ElMessage.success('桌面设置已保存')
    } else {
      localStorage.setItem('mdcx_desktop_prefs', JSON.stringify(prefs))
      ElMessage.success('桌面设置已保存到本地（仅当前浏览器）')
    }
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  } finally {
    saving.value = false
  }
}

const checkUpdate = async () => {
  if (!isElectron.value) return
  checking.value = true
  updaterInfo.value = null
  try {
    const result = await electronAPI.updaterCheck()
    if (!result.ok) {
      if (result.error?.includes('not installed')) {
        updaterStatus.value = 'not-installed'
        updaterInfo.value = {
          type: 'info',
          title: 'electron-updater 未安装',
          description: '请在 MDCX-Desktop 目录运行 npm install electron-updater 安装此依赖'
        }
      } else {
        updaterStatus.value = 'error'
        updaterInfo.value = { type: 'error', title: '检查失败', description: result.error }
      }
    }
    // 真实状态由 onUpdaterEvent 异步通知
  } catch (e) {
    updaterStatus.value = 'error'
    updaterInfo.value = { type: 'error', title: '检查失败', description: e.message }
  } finally {
    checking.value = false
  }
}

const downloadUpdate = async () => {
  if (!isElectron.value) return
  downloading.value = true
  updaterInfo.value = null
  downloadProgress.value = 0
  try {
    const result = await electronAPI.updaterDownload()
    if (!result.ok) {
      ElMessage.error('下载失败: ' + result.error)
    }
  } catch (e) {
    ElMessage.error('下载失败: ' + e.message)
  } finally {
    downloading.value = false
  }
}

const installUpdate = () => {
  if (!isElectron.value) return
  electronAPI.updaterInstall()
}

const openPath = async (path) => {
  if (!isElectron.value) return
  // 通过 shell.openPath 打开目录（在主进程添加 IPC）
  // 此处复用 openExternal 的 fallback：用户可手动复制路径
  try {
    await navigator.clipboard.writeText(path)
    ElMessage.success('路径已复制到剪贴板')
  } catch (e) {}
}

const handleShortcutEvent = (accelerator) => {
  const time = new Date().toLocaleTimeString()
  shortcutLogs.value.unshift({ time, accelerator })
  if (shortcutLogs.value.length > 50) shortcutLogs.value.pop()

  // 命中播放/暂停 - 触发 mpv 控制（通过自定义事件让 Play.vue 感知）
  if (accelerator === prefs.shortcut_play_pause) {
    window.dispatchEvent(new CustomEvent('mdcx-mpv-toggle'))
  } else if (accelerator === prefs.shortcut_screenshot) {
    window.dispatchEvent(new CustomEvent('mdcx-mpv-screenshot'))
  }
}

const handleUpdaterEvent = (event) => {
  const { type, ...rest } = event
  switch (type) {
    case 'checking':
      updaterStatus.value = 'idle'
      updaterInfo.value = { type: 'info', title: '正在检查更新...' }
      break
    case 'available':
      updaterStatus.value = 'available'
      updaterInfo.value = {
        type: 'warning',
        title: `发现新版本 v${rest.version}`,
        description: typeof rest.releaseNotes === 'string' ? rest.releaseNotes : '点击下载更新'
      }
      break
    case 'not-available':
      updaterStatus.value = 'up-to-date'
      updaterInfo.value = { type: 'success', title: '已是最新版本' }
      break
    case 'progress':
      updaterStatus.value = 'downloading'
      downloadProgress.value = Math.round(rest.percent || 0)
      break
    case 'downloaded':
      updaterStatus.value = 'downloaded'
      downloadProgress.value = 100
      updaterInfo.value = { type: 'success', title: `v${rest.version} 已下载完成`, description: '点击"重启并安装"应用更新' }
      break
    case 'error':
      updaterStatus.value = 'error'
      updaterInfo.value = { type: 'error', title: '更新失败', description: rest.message }
      break
  }
}

onMounted(async () => {
  await loadAll()
  checkUpdaterStatus()
  if (isElectron.value) {
    unbindShortcut.value = electronAPI.onGlobalShortcut(handleShortcutEvent)
    unbindUpdater.value = electronAPI.onUpdaterEvent(handleUpdaterEvent)
  }
  // 监听 Esc 取消捕获
  window.addEventListener('keydown', onGlobalKeydown)
})

const onGlobalKeydown = (e) => {
  if (e.key === 'Escape' && capturing.value) {
    capturing.value = false
    captureTarget.value = ''
    ElMessage.info('已取消捕获')
  }
}

onUnmounted(() => {
  if (unbindShortcut.value) unbindShortcut.value()
  if (unbindUpdater.value) unbindUpdater.value()
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<style scoped>
.desktop-page {
  padding: 0;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 16px 20px;
  background: linear-gradient(135deg, #ffffff 0%, #f5f7fa 100%);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 20px;
  color: #303133;
}

.page-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.page-header-actions {
  display: flex;
  gap: 8px;
}

.cfg-card,
.info-card {
  margin-bottom: 16px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #303133;
}

.hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.5;
}

.info-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.info-label {
  font-size: 12px;
  color: #909399;
}

.info-value {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
  font-family: 'Consolas', 'Monaco', monospace;
}

.path-block {
  margin-bottom: 12px;
}

.path-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.event-log {
  max-height: 300px;
  overflow-y: auto;
}

.empty-tip {
  text-align: center;
  color: #909399;
  padding: 24px 0;
  font-size: 13px;
}

.event-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
}

.event-time {
  color: #909399;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  min-width: 100px;
}
</style>
