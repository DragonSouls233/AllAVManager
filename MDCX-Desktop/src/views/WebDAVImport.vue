<template>
  <div class="webdav-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Download /></el-icon>
          WebDAV 导入
        </h2>
        <div class="page-subtitle">从远程 WebDAV 服务器扫描并导入影片 · 支持复制/移动/链接三种模式</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadConfig">
          <el-icon><Refresh /></el-icon> 重载配置
        </el-button>
      </div>
    </div>

    <!-- 步骤条 -->
    <el-card shadow="never" class="step-card">
      <el-steps :active="activeStep" finish-status="success" align-center>
        <el-step title="配置连接" description="WebDAV 服务器地址和认证" />
        <el-step title="扫描目录" description="递归扫描影片文件" />
        <el-step title="选择影片" description="筛选要导入的影片" />
        <el-step title="执行导入" description="写入数据库" />
      </el-steps>
    </el-card>

    <!-- WebDAV 服务端配置（暴露本地媒体库） -->
    <el-card shadow="never" class="server-card">
      <template #header>
        <div class="card-title">
          <el-icon><Upload /></el-icon> WebDAV 服务端（暴露本地媒体库）
          <el-tag v-if="serverForm.enabled" type="success" size="small" style="margin-left: 8px">已启用</el-tag>
          <el-tag v-else type="info" size="small" style="margin-left: 8px">未启用</el-tag>
        </div>
      </template>
      <el-form :model="serverForm" label-width="140px" style="max-width: 640px">
        <el-form-item label="启用服务端">
          <el-switch v-model="serverForm.enabled" />
          <span class="form-tip">开启后可通过 WebDAV 客户端（Windows 资源管理器/macOS Finder/VLC）访问媒体库</span>
        </el-form-item>
        <el-form-item label="挂载路径">
          <el-input v-model="serverForm.mount_path" placeholder="/webdav" style="width: 220px" />
          <span class="form-tip">WebDAV 客户端访问的 URL 路径，如 http://ip:8420/webdav/</span>
        </el-form-item>
        <el-form-item label="访问用户名">
          <el-input v-model="serverForm.username" placeholder="（可选，留空则不验证）" />
        </el-form-item>
        <el-form-item label="访问密码">
          <el-input v-model="serverForm.password" type="password" show-password placeholder="（可选）" />
        </el-form-item>
        <el-form-item label="虚拟目录布局">
          <el-radio-group v-model="serverForm.virtual_layout">
            <el-radio value="flat">扁平（所有影片在同一层）</el-radio>
            <el-radio value="by_code">按番号首字母</el-radio>
            <el-radio value="by_actor">按演员</el-radio>
            <el-radio value="by_studio">按厂商</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveServerConfig" :loading="savingServer">
            保存服务端配置
          </el-button>
          <span class="form-tip">保存后需重启后端才能生效</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 步骤 1: 配置连接 -->
    <el-card v-if="activeStep === 0" shadow="never" class="config-card">
      <template #header>
        <div class="card-title"><el-icon><Connection /></el-icon> WebDAV 服务器配置</div>
      </template>
      <el-form :model="connForm" label-width="160px" style="max-width: 700px">
        <el-form-item label="服务器地址">
          <el-input v-model="connForm.url" placeholder="https://webdav.example.com" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="connForm.username" placeholder="（可选）" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="connForm.password" type="password" show-password placeholder="（可选）" />
        </el-form-item>
        <el-form-item label="基础路径">
          <el-input v-model="connForm.base_path" placeholder="/" />
        </el-form-item>
        <el-form-item label="扫描深度">
          <el-input-number v-model="connForm.max_depth" :min="1" :max="10" />
          <span class="form-tip">递归扫描的最大目录深度</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="testConnection" :loading="testing">
            <el-icon><Connection /></el-icon> 测试连接
          </el-button>
          <el-button v-if="connectionOk" type="success" @click="goToScan">
            下一步：扫描 <el-icon><ArrowRight /></el-icon>
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 步骤 2: 扫描 -->
    <el-card v-if="activeStep === 1" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Search /></el-icon> 扫描 WebDAV 目录
          <span v-if="scanResult.total > 0" class="scan-summary">
            共 {{ scanResult.total }} 部 · 识别 {{ scanResult.parsed }} · 未识别 {{ scanResult.unparsed }}
          </span>
        </div>
      </template>

      <div v-if="!scanResult.total" class="scan-empty">
        <el-empty description="尚未扫描" />
        <el-button type="primary" size="large" @click="startScan" :loading="scanning">
          <el-icon><Search /></el-icon> 开始扫描
        </el-button>
        <p class="scan-tip">扫描过程将通过 WebSocket 实时推送日志到"实时日志流"页面</p>
      </div>

      <div v-else>
        <div class="scan-actions">
          <el-button @click="activeStep = 0">重新配置</el-button>
          <el-button @click="startScan" :loading="scanning">
            <el-icon><Refresh /></el-icon> 重新扫描
          </el-button>
          <el-button type="primary" @click="goToSelect">
            下一步：选择影片 <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 步骤 3: 选择影片 -->
    <el-card v-if="activeStep === 2" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Files /></el-icon> 选择要导入的影片
          <div class="header-actions">
            <el-input v-model="filterKeyword" placeholder="搜索文件名/番号" clearable size="small" style="width: 220px" />
            <el-checkbox v-model="onlyParsed">仅显示已识别</el-checkbox>
            <el-button size="small" @click="selectAll">全选</el-button>
            <el-button size="small" @click="selectNone">清空</el-button>
          </div>
        </div>
      </template>

      <el-table :data="filteredScanItems" max-height="500" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column label="文件名" min-width="280" prop="name" show-overflow-tooltip />
        <el-table-column label="番号" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.number" type="success" size="small">{{ row.number }}</el-tag>
            <el-tag v-else type="danger" size="small">未识别</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="修改时间" width="180" prop="modified" />
        <el-table-column label="路径" min-width="200" prop="path" show-overflow-tooltip />
      </el-table>

      <div class="select-actions">
        <span>已选 {{ selectedItems.length }} / 共 {{ scanResult.total }} 部</span>
        <el-button type="primary" :disabled="!selectedItems.length" @click="goToImport">
          下一步：执行导入 <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </el-card>

    <!-- 步骤 4: 导入 -->
    <el-card v-if="activeStep === 3" shadow="never">
      <template #header>
        <div class="card-title"><el-icon><Upload /></el-icon> 执行导入</div>
      </template>

      <el-form label-width="160px" style="max-width: 700px">
        <el-form-item label="导入影片数">
          <el-tag type="success" size="large">{{ selectedItems.length }} 部</el-tag>
        </el-form-item>
        <el-form-item label="导入模式">
          <el-radio-group v-model="importForm.link_mode">
            <el-radio value="link">链接（仅记录远程路径）</el-radio>
            <el-radio value="copy">复制（下载到本地）</el-radio>
            <el-radio value="move">移动（下载并删除远程）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="importForm.link_mode !== 'link'" label="本地保存目录">
          <el-input v-model="importForm.local_dir" placeholder="O:\Downloads" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" @click="executeImport" :loading="importing">
            <el-icon><Upload /></el-icon> 开始导入
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="importResult" class="import-result">
        <el-alert
          :type="importResult.failed > 0 ? 'warning' : 'success'"
          :title="`导入完成 · 成功 ${importResult.success} / 跳过 ${importResult.skipped} / 失败 ${importResult.failed}`"
          :closable="false"
          show-icon
        />
        <el-button type="primary" @click="$router.push('/movies')" style="margin-top: 16px">
          前往番号库查看
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Download, Refresh, Connection, ArrowRight, Search, Files, Upload
} from '@element-plus/icons-vue'
import {
  getWebDAVConfig, updateWebDAVConfig, testWebDAV, scanWebDAV, importFromWebDAV
} from '@/api'

const activeStep = ref(0)
const testing = ref(false)
const scanning = ref(false)
const importing = ref(false)
const connectionOk = ref(false)
const savingServer = ref(false)

const connForm = reactive({
  url: '',
  username: '',
  password: '',
  base_path: '/',
  max_depth: 5,
})

// WebDAV 服务端配置（暴露本地媒体库给外部客户端）
const serverForm = reactive({
  enabled: false,
  mount_path: '/webdav',
  username: '',
  password: '',
  virtual_layout: 'by_code',
})

const scanResult = ref({ total: 0, parsed: 0, unparsed: 0, items: [] })
const selectedItems = ref([])
const filterKeyword = ref('')
const onlyParsed = ref(false)

const importForm = reactive({
  link_mode: 'link',
  local_dir: '',
})

const importResult = ref(null)

const filteredScanItems = computed(() => {
  let items = scanResult.value.items
  if (onlyParsed.value) items = items.filter(i => i.number)
  if (filterKeyword.value) {
    const kw = filterKeyword.value.toLowerCase()
    items = items.filter(i =>
      i.name?.toLowerCase().includes(kw) || i.number?.toLowerCase().includes(kw)
    )
  }
  return items
})

const loadConfig = async () => {
  try {
    const res = await getWebDAVConfig()
    if (res.client) {
      connForm.url = res.client.url || ''
      connForm.username = res.client.username || ''
      connForm.base_path = res.client.base_path || '/'
      importForm.link_mode = res.client.link_mode || 'link'
    }
    if (res.server) {
      serverForm.enabled = !!res.server.enabled
      serverForm.mount_path = res.server.mount_path || '/webdav'
      serverForm.username = res.server.username || ''
      serverForm.password = ''  // 不回显密码
      serverForm.virtual_layout = res.server.virtual_layout || 'by_code'
    }
  } catch (e) {
    console.error(e)
  }
}

const saveServerConfig = async () => {
  savingServer.value = true
  try {
    await updateWebDAVConfig({
      server_enabled: serverForm.enabled,
      server_mount_path: serverForm.mount_path,
      server_username: serverForm.username || null,
      server_password: serverForm.password || null,
      server_virtual_layout: serverForm.virtual_layout,
    })
    ElMessage.success('WebDAV 服务端配置已保存，重启后端后生效')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingServer.value = false
  }
}

const testConnection = async () => {
  if (!connForm.url) {
    ElMessage.warning('请输入 WebDAV 服务器地址')
    return
  }
  testing.value = true
  try {
    const res = await testWebDAV({
      url: connForm.url,
      username: connForm.username || undefined,
      password: connForm.password || undefined,
    })
    if (res.connected) {
      connectionOk.value = true
      ElMessage.success(res.message)
    } else {
      connectionOk.value = false
      ElMessage.error(res.message)
    }
  } catch (e) {
    connectionOk.value = false
    ElMessage.error('连接测试失败')
  } finally {
    testing.value = false
  }
}

const goToScan = () => {
  activeStep.value = 1
  startScan()
}

const startScan = async () => {
  scanning.value = true
  try {
    const res = await scanWebDAV({
      url: connForm.url,
      username: connForm.username || undefined,
      password: connForm.password || undefined,
      base_path: connForm.base_path,
      max_depth: connForm.max_depth,
    })
    scanResult.value = res
    ElMessage.success(`扫描完成，发现 ${res.total} 部影片`)
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    scanning.value = false
  }
}

const goToSelect = () => { activeStep.value = 2 }

const onSelectionChange = (items) => { selectedItems.value = items }
const selectAll = () => { /* el-table 内置处理 */ }
const selectNone = () => { /* el-table 内置处理 */ }

const goToImport = () => { activeStep.value = 3 }

const executeImport = async () => {
  if (!selectedItems.value.length) {
    ElMessage.warning('未选择任何影片')
    return
  }
  importing.value = true
  try {
    const res = await importFromWebDAV({
      movies: selectedItems.value,
      link_mode: importForm.link_mode,
      local_dir: importForm.local_dir || undefined,
    })
    importResult.value = res
    ElMessage.success(`导入完成：成功 ${res.success} 部`)
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    importing.value = false
  }
}

const formatSize = (bytes) => {
  if (!bytes) return '0'
  const mb = bytes / 1024 / 1024
  if (mb < 1024) return `${mb.toFixed(1)} MB`
  return `${(mb / 1024).toFixed(2)} GB`
}

onMounted(() => loadConfig())
</script>

<style scoped>
.webdav-page {
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

.scan-summary {
  margin-left: 12px;
  font-size: 13px;
  font-weight: normal;
  color: var(--text-secondary);
}

.header-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  align-items: center;
}

.form-tip {
  margin-left: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}

.scan-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 40px 0;
}

.scan-tip {
  font-size: 13px;
  color: var(--text-secondary);
}

.scan-actions, .select-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 16px;
  justify-content: center;
}

.import-result {
  margin-top: 20px;
}
</style>
