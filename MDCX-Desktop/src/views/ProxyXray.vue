<template>
  <div class="proxy-xray-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Lightning /></el-icon>
          内置 Xray 代理
        </h2>
        <div class="page-subtitle">粘贴订阅或节点链接，服务端自动走代理刮削海外站</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadStatus" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新状态
        </el-button>
      </div>
    </div>

    <el-card shadow="never" class="status-card">
      <div class="status-row">
        <div class="status-item">
          <div class="status-label">状态</div>
          <el-tag :type="state.running ? 'success' : 'info'" size="large">
            {{ state.running ? '● 运行中' : '○ 未启动' }}
          </el-tag>
        </div>
        <div class="status-item">
          <div class="status-label">SOCKS5</div>
          <div class="status-value mono">127.0.0.1:{{ state.socks_port }}</div>
        </div>
        <div class="status-item">
          <div class="status-label">HTTP</div>
          <div class="status-value mono">127.0.0.1:{{ state.http_port }}</div>
        </div>
        <div class="status-item">
          <div class="status-label">节点数</div>
          <div class="status-value">{{ nodes.length }}</div>
        </div>
        <div class="status-item">
          <div class="status-label">分流模式</div>
          <el-radio-group v-model="state.mode" @change="changeMode" size="small">
            <el-radio-button label="domain">按域名</el-radio-button>
            <el-radio-button label="global">全局</el-radio-button>
            <el-radio-button label="direct">直连</el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <div class="status-actions">
        <el-button type="success" @click="doStart" :disabled="state.running || nodes.length===0">启动</el-button>
        <el-button type="danger" @click="doStop" :disabled="!state.running">停止</el-button>
        <el-button type="warning" @click="doRestart" :disabled="!state.running">重启</el-button>
      </div>
      <el-alert v-if="state.last_error" type="error" :closable="false" show-icon style="margin-top:12px">
        {{ state.last_error }}
      </el-alert>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>订阅链接</span>
          <div>
            <el-button size="small" @click="saveSubscription">保存</el-button>
            <el-button size="small" type="primary" @click="refreshSub" :loading="loading">立即刷新</el-button>
          </div>
        </div>
      </template>
      <el-input v-model="subscriptionInput" placeholder="https://sub.example.com/link/xxxxxxx" clearable />
      <div class="hint">订阅返回 base64 编码的 vmess/vless/ss/trojan 节点列表。保存后可点"立即刷新"抓取。</div>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>手动添加节点</span>
          <el-button size="small" type="primary" @click="addNode">添加</el-button>
        </div>
      </template>
      <el-input v-model="nodeUrlInput" placeholder="vmess:// / vless:// / ss:// / trojan:// 单个节点 URL" clearable />
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>节点池 ({{ nodes.length }})</span>
          <el-button size="small" @click="speedTest" :loading="loading" :disabled="nodes.length===0">TCP 测速</el-button>
        </div>
      </template>
      <el-table :data="nodes" size="small" empty-text="暂无节点，请添加订阅或手动粘贴 URL">
        <el-table-column prop="name" label="别名" min-width="180" show-overflow-tooltip />
        <el-table-column prop="protocol" label="协议" width="100">
          <template #default="{ row }"><el-tag size="small">{{ row.protocol }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="address" label="地址" min-width="180" show-overflow-tooltip />
        <el-table-column prop="port" label="端口" width="80" />
        <el-table-column label="延迟" width="100">
          <template #default="{ row }">
            <span v-if="row.latency_ms === null || row.latency_ms === undefined" style="color:#909399">-</span>
            <span v-else-if="row.latency_ms < 200" style="color:#67c23a">{{ row.latency_ms }}ms</span>
            <span v-else-if="row.latency_ms < 500" style="color:#e6a23c">{{ row.latency_ms }}ms</span>
            <span v-else style="color:#f56c6c">{{ row.latency_ms }}ms</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="danger" link @click="deleteNode(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Lightning } from '@element-plus/icons-vue'
import axios from 'axios'

const API = '/api/v1/proxy/xray'
const loading = ref(false)
const state = ref({
  running: false, pid: null, socks_port: 10809, http_port: 10808,
  current_node_id: null, mode: 'domain', subscription_url: null,
  last_error: null, nodes_count: 0
})
const nodes = ref([])
const subscriptionInput = ref('')
const nodeUrlInput = ref('')

async function loadStatus () {
  loading.value = true
  try {
    const r = await axios.get(`${API}/status`)
    state.value = r.data.data
    subscriptionInput.value = state.value.subscription_url || ''
    const r2 = await axios.get(`${API}/nodes`)
    nodes.value = r2.data.data
  } catch (e) {
    ElMessage.error('加载状态失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

async function doStart () { loading.value = true; try { const r = await axios.post(`${API}/start`); state.value = r.data.data; ElMessage[r.data.status==='ok'?'success':'error'](r.data.message||'启动完成') } finally { loading.value = false; loadStatus() } }
async function doStop () { loading.value = true; try { await axios.post(`${API}/stop`); ElMessage.success('已停止') } finally { loading.value = false; loadStatus() } }
async function doRestart () { loading.value = true; try { await axios.post(`${API}/restart`); ElMessage.success('已重启') } finally { loading.value = false; loadStatus() } }

async function addNode () {
  if (!nodeUrlInput.value.trim()) { ElMessage.warning('请粘贴节点 URL'); return }
  try {
    await axios.post(`${API}/nodes`, { url: nodeUrlInput.value.trim() })
    ElMessage.success('添加成功'); nodeUrlInput.value = ''; loadStatus()
  } catch (e) { ElMessage.error('添加失败: ' + (e.response?.data?.detail || e.message)) }
}

async function deleteNode (nodeId) {
  await ElMessageBox.confirm('删除该节点？', '确认', { type: 'warning' })
  await axios.delete(`${API}/nodes/${nodeId}`); ElMessage.success('已删除'); loadStatus()
}

async function saveSubscription () {
  await axios.post(`${API}/subscription`, { url: subscriptionInput.value || null })
  ElMessage.success('订阅已保存')
}

async function refreshSub () {
  loading.value = true
  try {
    const r = await axios.post(`${API}/subscription/refresh`)
    ElMessage[r.data.status==='ok'?'success':'error'](r.data.message)
  } finally { loading.value = false; loadStatus() }
}

async function changeMode (mode) {
  await axios.post(`${API}/mode`, { mode }); ElMessage.success('模式已切换'); loadStatus()
}

async function speedTest () {
  loading.value = true
  try {
    const r = await axios.post(`${API}/speedtest`)
    ElMessage.success(`测速完成 ${r.data.data.alive}/${r.data.data.total} 存活`); loadStatus()
  } finally { loading.value = false }
}

onMounted(loadStatus)
</script>

<style scoped>
.proxy-xray-page { padding: 20px; }
.page-header { display: flex; justify-content: space-between; margin-bottom: 20px; }
.page-title { font-size: 20px; font-weight: 600; display: flex; align-items: center; gap: 8px; margin: 0; }
.page-subtitle { color: var(--el-text-color-secondary); font-size: 13px; margin-top: 4px; }
.status-card { margin-bottom: 16px; }
.status-row { display: flex; gap: 32px; flex-wrap: wrap; align-items: center; }
.status-item { display: flex; flex-direction: column; gap: 4px; }
.status-label { font-size: 12px; color: var(--el-text-color-secondary); }
.status-value { font-size: 16px; font-weight: 500; }
.status-value.mono { font-family: 'JetBrains Mono', Consolas, monospace; }
.status-actions { margin-top: 16px; display: flex; gap: 8px; }
.section-card { margin-bottom: 16px; }
.section-header { display: flex; justify-content: space-between; align-items: center; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 8px; }
</style>
