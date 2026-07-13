<template>
  <div class="cd2-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Cloudy /></el-icon>
          CloudDrive2 网盘集成
        </h2>
        <div class="page-subtitle">
          聚合 115 / 阿里云盘 / 百度网盘等云盘 · 浏览云端文件并流式播放
        </div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll">
          <el-icon><Refresh /></el-icon> 重载
        </el-button>
      </div>
    </div>

    <!-- 配置卡片 -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-title">
          <el-icon><Setting /></el-icon> 服务器配置
          <el-tag v-if="form.enabled" type="success" size="small" style="margin-left: 8px">已启用</el-tag>
          <el-tag v-else type="info" size="small" style="margin-left: 8px">未启用</el-tag>
        </div>
      </template>
      <el-form :model="form" label-width="160px" style="max-width: 720px">
        <el-form-item label="启用 CloudDrive2">
          <el-switch v-model="form.enabled" />
          <span class="form-tip">开启后将自动登录并对接 CloudDrive2 服务</span>
        </el-form-item>
        <el-form-item label="服务器地址">
          <el-input v-model="form.url" placeholder="http://localhost:19798" />
          <span class="form-tip">CloudDrive2 默认端口 19798</span>
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="CloudDrive2 账号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="CloudDrive2 密码" />
        </el-form-item>
        <el-form-item label="基础路径">
          <el-input v-model="form.base_path" placeholder="/" />
          <span class="form-tip">浏览文件时的起始路径</span>
        </el-form-item>
        <el-form-item label="视频扩展名">
          <el-select
            v-model="form.video_extensions"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入视频扩展名"
            style="width: 100%"
          >
            <el-option
              v-for="ext in defaultVideoExts"
              :key="ext"
              :label="ext"
              :value="ext"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="连接超时 (秒)">
          <el-input-number v-model="form.timeout" :min="5" :max="120" :step="5" />
        </el-form-item>
        <el-form-item label="本地流式代理端口">
          <el-input-number v-model="form.proxy_port" :min="0" :max="65535" />
          <span class="form-tip">0=不启用本地代理（直接使用 CloudDrive2 的 Redirect URL）</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="loadConfig">重置</el-button>
          <el-button type="success" @click="doLogin" :loading="loggingIn">
            <el-icon><Key /></el-icon> 立即登录
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
        <el-descriptions-item label="服务器地址">{{ status.url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="基础路径">{{ status.base_path || '/' }}</el-descriptions-item>
        <el-descriptions-item label="启用状态">
          <el-tag v-if="status.enabled" type="success" size="small">已启用</el-tag>
          <el-tag v-else type="info" size="small">未启用</el-tag>
        </el-descriptions-item>
      </el-descriptions>
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
                @click="navigateTo(seg.path)"
              >
                <span class="breadcrumb-link">{{ seg.name }}</span>
              </el-breadcrumb-item>
            </el-breadcrumb>
            <el-button size="small" @click="goUp" :disabled="currentPath === '/' || currentPath === form.base_path">
              <el-icon><Top /></el-icon> 上级
            </el-button>
            <el-button size="small" @click="loadList(currentPath)" :loading="listing">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
            <el-button size="small" type="primary" @click="scanDialogVisible = true">
              <el-icon><Search /></el-icon> 扫描视频
            </el-button>
          </div>
        </div>
      </template>

      <el-input
        v-model="currentPath"
        placeholder="/"
        style="margin-bottom: 12px"
        @keyup.enter="loadList(currentPath)"
      >
        <template #prepend>路径</template>
        <template #append>
          <el-button @click="loadList(currentPath)" :loading="listing">前往</el-button>
        </template>
      </el-input>

      <el-table
        v-loading="listing"
        :data="fileList"
        max-height="500"
        @row-dblclick="onRowDblClick"
      >
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
            <el-tag v-else size="small" type="info">{{ row.file_extension || '文件' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="120">
          <template #default="{ row }">
            {{ row.is_dir ? '-' : formatSize(row.size) }}
          </template>
        </el-table-column>
        <el-table-column label="修改时间" width="180" prop="modified_at" />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button
              v-if="!row.is_dir && isVideo(row.name)"
              size="small"
              type="primary"
              text
              @click.stop="playVideo(row)"
            >
              <el-icon><VideoPlay /></el-icon> 播放
            </el-button>
            <el-button
              v-if="!row.is_dir"
              size="small"
              text
              @click.stop="copyStreamUrl(row)"
            >
              复制 URL
            </el-button>
            <el-button
              v-if="row.is_dir"
              size="small"
              text
              @click.stop="enterDir(row)"
            >
              进入
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 扫描对话框 -->
    <el-dialog v-model="scanDialogVisible" title="扫描云端视频文件" width="540px">
      <el-form label-width="120px">
        <el-form-item label="起始路径">
          <el-input v-model="scanForm.path" placeholder="/" />
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
          :title="`扫描完成：共找到 ${scanResult.total} 个视频文件`"
          :closable="false"
          show-icon
        />
        <el-table :data="scanResult.items?.slice(0, 50)" max-height="320" style="margin-top: 12px" size="small">
          <el-table-column label="文件名" prop="name" min-width="240" show-overflow-tooltip />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ formatSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="路径" prop="path" min-width="200" show-overflow-tooltip />
        </el-table>
        <p v-if="scanResult.total > 50" class="more-tip">仅显示前 50 条，共 {{ scanResult.total }} 条</p>
      </div>
    </el-dialog>

    <!-- 播放对话框 -->
    <el-dialog v-model="playDialogVisible" :title="`播放: ${playingFile?.name || ''}`" width="820px" @closed="onPlayDialogClosed">
      <div v-if="playingUrl" class="player-box">
        <ArtplayerVideo
          v-if="playDialogVisible && playingUrl"
          ref="artplayerComp"
          :url="playingUrl"
          :autoplay="true"
          theme="#409eff"
          @screenshot="onScreenshot"
        />
        <el-input v-model="playingUrl" readonly style="margin-top: 12px">
          <template #prepend>流式 URL</template>
          <template #append>
            <el-button @click="copyText(playingUrl)">复制</el-button>
          </template>
        </el-input>
      </div>
      <el-empty v-else description="无法获取流式 URL" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Cloudy, Refresh, Setting, Key, Connection, FolderOpened,
  Top, Search, Folder, Document, VideoPlay
} from '@element-plus/icons-vue'
import ArtplayerVideo from '@/components/ArtplayerVideo.vue'
import {
  getCloudDrive2Config, updateCloudDrive2Config, loginCloudDrive2,
  getCloudDrive2Status, listCloudDrive2Dir, scanCloudDrive2, getCloudDrive2StreamUrl
} from '@/api'

const defaultVideoExts = [
  '.mp4', '.mkv', '.avi', '.wmv', '.flv', '.mov', '.m4v',
  '.rm', '.rmvb', '.mpg', '.mpeg', '.ts', '.m2ts', '.webm'
]

const form = reactive({
  enabled: false,
  url: 'http://localhost:19798',
  username: '',
  password: '',
  base_path: '/',
  video_extensions: [...defaultVideoExts],
  proxy_port: 0,
  timeout: 30,
})

const status = ref({
  enabled: false,
  url: '',
  started: false,
  logged_in: false,
  has_credentials: false,
  base_path: '/',
})

const currentPath = ref('/')
const fileList = ref([])
const listing = ref(false)
const saving = ref(false)
const loggingIn = ref(false)

const scanDialogVisible = ref(false)
const scanning = ref(false)
const scanForm = reactive({
  path: '/',
  recursive: true,
  max_depth: 5,
})
const scanResult = ref(null)

const playDialogVisible = ref(false)
const playingFile = ref(null)
const playingUrl = ref('')
const artplayerComp = ref(null)

// 播放对话框关闭时销毁播放器释放资源
const onPlayDialogClosed = () => {
  if (artplayerComp.value) {
    artplayerComp.value.destroy()
  }
  playingUrl.value = ''
}

// Artplayer 截图回调
const onScreenshot = (dataURL) => {
  // 将截图下载到本地
  const link = document.createElement('a')
  link.href = dataURL
  link.download = `${playingFile.value?.name || 'screenshot'}-${Date.now()}.png`
  link.click()
  ElMessage.success('截图已保存')
}

const breadcrumb = computed(() => {
  const path = currentPath.value || '/'
  const segs = path.split('/').filter(Boolean)
  const result = [{ name: '根目录', path: '/' }]
  let cur = ''
  for (const s of segs) {
    cur = cur + '/' + s
    result.push({ name: s, path: cur })
  }
  return result
})

const isVideo = (name) => {
  if (!name) return false
  const dot = name.lastIndexOf('.')
  if (dot < 0) return false
  const ext = name.slice(dot).toLowerCase()
  return (form.video_extensions || []).some(e => e.toLowerCase() === ext)
}

const formatSize = (bytes) => {
  if (!bytes) return '0'
  const mb = bytes / 1024 / 1024
  if (mb < 1024) return `${mb.toFixed(1)} MB`
  return `${(mb / 1024).toFixed(2)} GB`
}

const loadConfig = async () => {
  try {
    const res = await getCloudDrive2Config()
    form.enabled = !!res.enabled
    form.url = res.url || 'http://localhost:19798'
    form.username = res.username || ''
    form.password = ''  // 不回显
    form.base_path = res.base_path || '/'
    form.video_extensions = res.video_extensions?.length ? res.video_extensions : [...defaultVideoExts]
    form.proxy_port = res.proxy_port || 0
    form.timeout = res.timeout || 30
  } catch (e) {
    console.error(e)
  }
}

const loadStatus = async () => {
  try {
    status.value = await getCloudDrive2Status()
  } catch (e) {
    console.error(e)
  }
}

const loadList = async (path) => {
  listing.value = true
  try {
    const res = await listCloudDrive2Dir(path || '/')
    fileList.value = res.items || []
    currentPath.value = res.path || path
  } catch (e) {
    ElMessage.error('列目录失败: ' + (e.response?.data?.detail || e.message))
    fileList.value = []
  } finally {
    listing.value = false
  }
}

const loadAll = async () => {
  await Promise.all([loadConfig(), loadStatus()])
  if (status.value.started || status.value.enabled) {
    await loadList(form.base_path || '/')
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await updateCloudDrive2Config({
      enabled: form.enabled,
      url: form.url,
      username: form.username,
      password: form.password || undefined,
      base_path: form.base_path,
      video_extensions: form.video_extensions,
      proxy_port: form.proxy_port,
      timeout: form.timeout,
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
    // 先保存配置（包含密码），再登录
    if (form.password) {
      await updateCloudDrive2Config({
        username: form.username,
        password: form.password,
        url: form.url,
      })
    }
    await loginCloudDrive2({})
    ElMessage.success('登录成功')
    await loadStatus()
  } catch (e) {
    ElMessage.error('登录失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loggingIn.value = false
  }
}

const enterDir = (row) => {
  loadList(row.full_path)
}

const onRowDblClick = (row) => {
  if (row.is_dir) enterDir(row)
  else if (isVideo(row.name)) playVideo(row)
}

const goUp = () => {
  const path = currentPath.value || '/'
  if (path === '/' || path === form.base_path) return
  const idx = path.lastIndexOf('/')
  const parent = idx <= 0 ? '/' : path.slice(0, idx)
  loadList(parent)
}

const navigateTo = (path) => {
  loadList(path)
}

const playVideo = async (row) => {
  try {
    const res = await getCloudDrive2StreamUrl(row.full_path)
    playingFile.value = row
    playingUrl.value = res.stream_url
    playDialogVisible.value = true
  } catch (e) {
    ElMessage.error('获取流式 URL 失败: ' + (e.response?.data?.detail || e.message))
  }
}

const copyStreamUrl = async (row) => {
  try {
    const res = await getCloudDrive2StreamUrl(row.full_path)
    await copyText(res.stream_url)
    ElMessage.success('已复制流式 URL')
  } catch (e) {
    ElMessage.error('复制失败')
  }
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 退化方案
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

const doScan = async () => {
  scanning.value = true
  scanResult.value = null
  try {
    const res = await scanCloudDrive2({
      path: scanForm.path,
      recursive: scanForm.recursive,
      max_depth: scanForm.max_depth,
    })
    scanResult.value = res
    ElMessage.success(`扫描完成，共 ${res.total} 个视频文件`)
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    scanning.value = false
  }
}

onMounted(() => loadAll())
</script>

<style scoped>
.cd2-page {
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

.player-box {
  display: flex;
  flex-direction: column;
}
</style>
