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

    <!-- 按站点代理覆盖（amane #365，独立段，不改原有代理入口） -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>按站点代理覆盖（amane #365）</span>
          <div>
            <el-switch v-model="siteProxyEnabled" active-text="启用" inline-prompt />
            <el-button size="small" type="primary" @click="saveSiteProxy" :loading="spLoading">保存</el-button>
          </div>
        </div>
      </template>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
        title="为单个站点单独指定代理或强制直连，覆盖全局代理。键可为爬虫名（javdb）或域名（javbus.com），域名取最长匹配；值填 direct 表示强制直连。" />
      <el-table :data="siteProxyRules" size="small" empty-text="暂无规则">
        <el-table-column label="站点/域名" min-width="160">
          <template #default="{ row }"><el-input v-model="row.key" size="small" placeholder="javdb 或 javbus.com" /></template>
        </el-table-column>
        <el-table-column label="代理 / direct" min-width="260">
          <template #default="{ row }"><el-input v-model="row.value" size="small" placeholder="socks5://127.0.0.1:10808 或 direct" /></template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row, $index }">
            <el-button size="small" type="danger" link @click="siteProxyRules.splice($index, 1)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top:8px">
        <el-button size="small" @click="siteProxyRules.push({ key: '', value: '' })">+ 添加规则</el-button>
      </div>
      <el-divider />
      <div class="hint">
        测试：
        <el-input v-model="spTestSite" size="small" style="width:160px" placeholder="站点名" />
        <el-input v-model="spTestUrl" size="small" style="width:240px" placeholder="https://..." />
        <el-button size="small" @click="testSiteProxy">解析</el-button>
      </div>
      <div v-if="spTestResult" class="hint">结果：{{ spTestResult }}</div>
    </el-card>

    <!-- 跨机路径对照表（openaver 0.17.7，独立段） -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>跨机路径对照表（openaver 0.17.7）</span>
          <div>
            <el-switch v-model="pmEnabled" active-text="启用" inline-prompt />
            <el-button size="small" type="primary" @click="savePathMap" :loading="spLoading">保存</el-button>
          </div>
        </div>
      </template>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
        title="片库在另一台机器/NAS 时，把远端路径前缀映射为本机可访问前缀（如 /volume1/av ↔ \\NAS\av）。播放/开文件夹自动套用。" />
      <el-table :data="pathMapRules" size="small" empty-text="暂无规则">
        <el-table-column label="远端前缀" min-width="220">
          <template #default="{ row }"><el-input v-model="row.remote" size="small" placeholder="/volume1/av" /></template>
        </el-table-column>
        <el-table-column label="本机前缀" min-width="220">
          <template #default="{ row }"><el-input v-model="row.local" size="small" placeholder="\\NAS\av" /></template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }"><el-switch v-model="row.enabled" /></template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row, $index }">
            <el-button size="small" type="danger" link @click="pathMapRules.splice($index, 1)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top:8px">
        <el-button size="small" @click="pathMapRules.push({ remote: '', local: '', enabled: true })">+ 添加规则</el-button>
      </div>
      <el-divider />
      <div class="hint">
        测试：<el-input v-model="pmTestPath" size="small" style="width:360px" placeholder="/volume1/av/ABC-123/ABC-123.mp4" />
        <el-button size="small" @click="testPathMap">映射</el-button>
      </div>
      <div v-if="pmTestResult" class="hint">结果：{{ pmTestResult }}</div>
    </el-card>

    <!-- 自定义来源 YAML 规则档（openaver 0.17.7，独立段） -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>自定义来源 YAML 规则档（openaver 0.17.7）</span>
          <div>
            <el-button size="small" @click="validateCustomSource" :loading="csValidating">校验/验收</el-button>
            <el-button size="small" type="primary" @click="saveCustomSource" :loading="csSaving">保存</el-button>
          </div>
        </div>
      </template>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
        title="纯配置新增刮削源（不写代码）。要求 test_cases 至少一例 expect: not_found，且能真正判定为 not_found 才验收通过。" />
      <el-table :data="csList" size="small" empty-text="暂无自定义源（可用「演示」模板参考 data/custom_sources/demo_jav.yaml）">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.valid ? 'success' : 'danger'">{{ row.valid ? '校验通过' : '校验失败' }}</el-tag>
            <span class="hint">用例 {{ row.test_case_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" link @click="editCustomSource(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="deleteCustomSource(row.name)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-divider>编辑区</el-divider>
      <div class="hint">名称：<el-input v-model="csName" size="small" style="width:240px" placeholder="如 my_source" /></div>
      <el-input v-model="csYaml" type="textarea" :rows="14" style="margin-top:8px; font-family:Consolas,Monaco,monospace"
        placeholder="name: my_source&#10;base_url: https://example.com&#10;search:&#10;  url: 'https://example.com/search?q={code}'&#10;  not_found:&#10;    text: ['影片不存在']&#10;  fields:&#10;    title: '.title'&#10;test_cases:&#10;  - code: ABC-123&#10;    expect: found&#10;    html: '<html>...</html>'&#10;  - code: ZZZ-999&#10;    expect: not_found&#10;    html: '<html>影片不存在</html>'" />
      <div v-if="csValidateResult" style="margin-top:8px">
        <el-alert v-if="!csValidateResult.valid" type="error" :closable="false" :title="'校验未通过：' + (csValidateResult.errors || []).join('；')" />
        <el-alert v-else type="success" :closable="false" title="校验通过">
          <template #default>
            <div class="hint" v-for="(t, i) in (csValidateResult.test_results || [])" :key="i">
              [{{ t.code }}] 期望={{ t.expect }} 实测={{ t.got }} {{ t.passed ? '✓' : '✗' }} <span v-if="t.detail">（{{ t.detail }}）</span>
            </div>
          </template>
        </el-alert>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Lightning } from '@element-plus/icons-vue'
import { api } from '@/api'

const API = '/proxy/xray'
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
    const r = await api.get(`${API}/status`)
    state.value = r.data
    subscriptionInput.value = state.value.subscription_url || ''
    const r2 = await api.get(`${API}/nodes`)
    nodes.value = r2.data
  } catch (e) {
    ElMessage.error('加载状态失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

async function doStart () { loading.value = true; try { const r = await api.post(`${API}/start`); state.value = r.data; ElMessage[r.status==='ok'?'success':'error'](r.message||'启动完成') } finally { loading.value = false; loadStatus() } }
async function doStop () { loading.value = true; try { await api.post(`${API}/stop`); ElMessage.success('已停止') } finally { loading.value = false; loadStatus() } }
async function doRestart () { loading.value = true; try { await api.post(`${API}/restart`); ElMessage.success('已重启') } finally { loading.value = false; loadStatus() } }

async function addNode () {
  if (!nodeUrlInput.value.trim()) { ElMessage.warning('请粘贴节点 URL'); return }
  try {
    await api.post(`${API}/nodes`, { url: nodeUrlInput.value.trim() })
    ElMessage.success('添加成功'); nodeUrlInput.value = ''; loadStatus()
  } catch (e) { ElMessage.error('添加失败: ' + (e.response?.data?.detail || e.message)) }
}

async function deleteNode (nodeId) {
  await ElMessageBox.confirm('删除该节点？', '确认', { type: 'warning' })
  await api.delete(`${API}/nodes/${nodeId}`); ElMessage.success('已删除'); loadStatus()
}

async function saveSubscription () {
  await api.post(`${API}/subscription`, { url: subscriptionInput.value || null })
  ElMessage.success('订阅已保存')
}

async function refreshSub () {
  loading.value = true
  try {
    const r = await api.post(`${API}/subscription/refresh`)
    ElMessage[r.status==='ok'?'success':'error'](r.message)
  } finally { loading.value = false; loadStatus() }
}

async function changeMode (mode) {
  await api.post(`${API}/mode`, { mode }); ElMessage.success('模式已切换'); loadStatus()
}

async function speedTest () {
  loading.value = true
  try {
    const r = await api.post(`${API}/speedtest`)
    ElMessage.success(`测速完成 ${r.data.alive}/${r.data.total} 存活`); loadStatus()
  } finally { loading.value = false }
}

onMounted(() => { loadStatus(); loadSiteProxy(); loadPathMap(); loadCustomSources() })

// ===== 按站点代理覆盖（amane #365）=====
const spLoading = ref(false)
const siteProxyEnabled = ref(true)
const siteProxyRules = ref([])
const spTestSite = ref('')
const spTestUrl = ref('')
const spTestResult = ref('')

async function loadSiteProxy () {
  try {
    const r = await api.get('/config/site-proxy')
    siteProxyEnabled.value = r.data.enabled
    siteProxyRules.value = (r.data.items || []).map(i => ({ key: i.key, value: i.value }))
  } catch (e) { /* 非关键 */ }
}
async function saveSiteProxy () {
  spLoading.value = true
  try {
    const sites = {}
    for (const r of siteProxyRules.value) {
      if (r.key && r.key.trim() && r.value && r.value.trim()) sites[r.key.trim()] = r.value.trim()
    }
    await api.put('/config/site-proxy', { enabled: siteProxyEnabled.value, sites })
    ElMessage.success('按站点代理已保存')
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)) }
  finally { spLoading.value = false }
}
async function testSiteProxy () {
  try {
    const r = await api.post('/config/site-proxy/test', { site: spTestSite.value, url: spTestUrl.value })
    spTestResult.value = `命中=${r.data.matched} 实际代理=${r.data.effective_proxy ?? '直连'}（${r.data.mode}）`
  } catch (e) { spTestResult.value = '测试失败: ' + (e.response?.data?.detail || e.message) }
}

// ===== 跨机路径对照表（openaver 0.17.7）=====
const pmEnabled = ref(true)
const pathMapRules = ref([])
const pmTestPath = ref('')
const pmTestResult = ref('')
async function loadPathMap () {
  try {
    const r = await api.get('/config/path-map')
    pmEnabled.value = r.data.enabled
    pathMapRules.value = (r.data.rules || []).map(r2 => ({ remote: r2.remote, local: r2.local, enabled: r2.enabled !== false }))
  } catch (e) { /* 非关键 */ }
}
async function savePathMap () {
  spLoading.value = true
  try {
    const rules = pathMapRules.value
      .filter(r => r.remote && r.local)
      .map(r => ({ remote: r.remote, local: r.local, enabled: r.enabled !== false }))
    await api.put('/config/path-map', { enabled: pmEnabled.value, rules })
    ElMessage.success('路径对照表已保存')
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)) }
  finally { spLoading.value = false }
}
async function testPathMap () {
  try {
    const r = await api.post('/config/path-map/test', { path: pmTestPath.value, direction: 'to_local' })
    pmTestResult.value = r.data.changed ? `→ ${r.data.output}` : '未命中（原样返回）'
  } catch (e) { pmTestResult.value = '测试失败: ' + (e.response?.data?.detail || e.message) }
}

// ===== 自定义来源 YAML 规则档（openaver 0.17.7）=====
const csList = ref([])
const csName = ref('')
const csYaml = ref('')
const csValidating = ref(false)
const csSaving = ref(false)
const csValidateResult = ref(null)
async function loadCustomSources () {
  try {
    const r = await api.get('/config/custom-sources')
    csList.value = r.data.items || []
  } catch (e) { /* 非关键 */ }
}
function editCustomSource (item) {
  csName.value = item.name
  csYaml.value = item.yaml || ''
  csValidateResult.value = null
}
async function validateCustomSource () {
  if (!csYaml.value.trim()) { ElMessage.warning('请先填写 YAML'); return }
  csValidating.value = true
  try {
    const r = await api.post('/config/custom-sources/validate', { yaml: csYaml.value })
    csValidateResult.value = r.data
    if (r.data.valid && (r.data.test_results || []).every(t => t.passed)) ElMessage.success('校验通过，全部用例验收合格')
    else if (r.data.valid) ElMessage.warning('校验通过，但有用例未通过')
    else ElMessage.error('校验未通过：' + (r.data.errors || []).join('；'))
  } catch (e) { ElMessage.error('校验失败: ' + (e.response?.data?.detail || e.message)) }
  finally { csValidating.value = false }
}
async function saveCustomSource () {
  if (!csName.value.trim()) { ElMessage.warning('请填写名称'); return }
  csSaving.value = true
  try {
    await api.put(`/config/custom-sources/${encodeURIComponent(csName.value.trim())}`, { yaml: csYaml.value })
    ElMessage.success('已保存'); loadCustomSources()
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)) }
  finally { csSaving.value = false }
}
async function deleteCustomSource (name) {
  await ElMessageBox.confirm(`删除自定义源 ${name}？`, '确认', { type: 'warning' })
  await api.delete(`/config/custom-sources/${encodeURIComponent(name)}`)
  ElMessage.success('已删除'); loadCustomSources()
}
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
