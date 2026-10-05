<template>
  <div class="jp-page">
    <div class="page-header">
      <div>
        <h2>日本节点代理</h2>
        <p class="sub">DMM / FANZA 对海外 IP 地区封锁，必须经日本出口才能刮到数据</p>
      </div>
      <div class="actions">
        <el-button :loading="loading" @click="loadAll">
          <el-icon><Refresh /></el-icon>刷新状态
        </el-button>
        <el-button type="primary" :loading="refreshing" @click="onRefresh">
          <el-icon><MagicStick /></el-icon>立即更新节点
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!status.in_source_order"
      type="warning"
      show-icon
      :closable="false"
      title="日本节点当前不在刮削源序中"
      description="DMM 源不会参与自动刮削。可检查系统环境变量 MDCX_JP_SOURCE_IN_ORDER 是否被设为 0，或日本出口是否不可用。"
      class="mb"
    />

    <!-- 状态总览 -->
    <el-row :gutter="12" class="mb">
      <el-col :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="stat">
          <div class="stat-label">代理服务</div>
          <el-tag :type="status.service?.running ? 'success' : 'danger'" size="small">
            {{ status.service?.running ? '运行中' : '未运行' }}
          </el-tag>
          <div v-if="status.service?.adopted" class="stat-hint">由上一个进程托管</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="stat">
          <div class="stat-label">出口 IP</div>
          <div class="stat-value">{{ exitIp || '—' }}</div>
          <div class="stat-hint">
            <el-tag v-if="exitCountry" :type="exitCountry === 'JP' ? 'success' : 'warning'" size="small">
              {{ exitCountry }}
            </el-tag>
            <span v-else>未探测</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="stat">
          <div class="stat-label">节点池</div>
          <div class="stat-value">{{ status.nodes?.count || 0 }} <span class="unit">个</span></div>
          <div class="stat-hint">上限 {{ status.max_nodes }} · 活跃 {{ status.service?.active_nodes || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="stat">
          <div class="stat-label">自动刷新</div>
          <div class="stat-value">{{ form.refresh_hours }} <span class="unit">小时</span></div>
          <div class="stat-hint">下次约 {{ nextRefreshHint }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="stat">
          <div class="stat-label">上次更新</div>
          <div class="stat-value small">{{ status.nodes?.updated_at || '从未' }}</div>
          <div class="stat-hint">{{ ageHint }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="stat">
          <div class="stat-label">前置代理</div>
          <div class="stat-value small">{{ status.service?.front || '未记录' }}</div>
          <div class="stat-hint">日本节点需经前置才能连通</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <!-- 左：订阅源与刷新设置 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never" class="mb">
          <template #header>
            <div class="card-head">
              <span>订阅源与更新设置</span>
              <div>
                <el-button size="small" :loading="testing" @click="onTestSub">测试可达性</el-button>
                <el-button size="small" type="primary" :loading="saving" @click="onSave">保存</el-button>
              </div>
            </div>
          </template>

          <el-form label-width="96px" label-position="left">
            <el-form-item label="订阅源">
              <div class="sub-list">
                <div v-for="(u, i) in form.sub_urls" :key="i" class="sub-row">
                  <el-input v-model="form.sub_urls[i]" placeholder="https://.../v2ray-base64-JP.txt" size="small" />
                  <el-button :icon="Delete" size="small" circle @click="form.sub_urls.splice(i, 1)" />
                </div>
                <el-button size="small" text type="primary" @click="form.sub_urls.push('')">
                  <el-icon><Plus /></el-icon>添加订阅源
                </el-button>
              </div>
              <div class="hint">
                GitHub 免费节点仓库会改名 / 删仓 / 改分支，地址失效后在此填入新地址即可，无需改代码。
              </div>
            </el-form-item>

            <el-form-item label="刷新周期">
              <el-input-number v-model="form.refresh_hours" :min="1" :max="168" />
              <span class="unit">小时</span>
              <div class="hint">
                免费节点寿命以小时计（实测同一批 11:30 可用、11:40 已全部失效），过密刷新只是白耗开销。
              </div>
            </el-form-item>

            <el-form-item label="取样数">
              <el-input-number v-model="form.sample" :min="5" :max="200" />
              <span class="unit">个 / 轮</span>
              <div class="hint">每轮从订阅里按 host 分散抽取这么多节点实测，耗时随此值线性增长。</div>
            </el-form-item>
          </el-form>

          <el-divider />

          <div class="svc-actions">
            <el-button size="small" :disabled="status.service?.running" @click="onStart">启动</el-button>
            <el-button size="small" :disabled="!status.service?.running" @click="onStop">停止</el-button>
            <el-button size="small" @click="onRestart">重启</el-button>
            <span v-if="status.service?.last_error" class="err">{{ status.service.last_error }}</span>
          </div>
        </el-card>

        <el-card v-if="logLines.length" shadow="never">
          <template #header><span>更新日志</span></template>
          <pre class="log">{{ logLines.join('\n') }}</pre>
        </el-card>
      </el-col>

      <!-- 右：节点池 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>节点池（{{ nodes.length }}）</span>
              <div>
                <el-button size="small" @click="openAdd">手工添加</el-button>
                <el-button size="small" type="danger" plain :disabled="!nodes.length" @click="onClear">清空</el-button>
              </div>
            </div>
          </template>

          <el-table :data="nodes" size="small" v-loading="loading" empty-text="暂无节点，点击「立即更新节点」自动获取">
            <el-table-column type="index" label="#" width="45" />
            <el-table-column label="名称" min-width="150">
              <template #default="{ row }">{{ row.name || '（未命名）' }}</template>
            </el-table-column>
            <el-table-column label="协议" width="80">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.proto }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="服务器" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ row.host || '—' }}</template>
            </el-table-column>
            <el-table-column label="本地端口" width="95">
              <template #default="{ row }">{{ row.port }}</template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag v-if="!row.enabled" size="small" type="info">未启用</el-tag>
                <el-tag v-else-if="row.alive" size="small" type="success">存活</el-tag>
                <el-tag v-else size="small" type="danger">不可用</el-tag>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="overCount > 0" class="hint warn">
            节点数超过上限 {{ status.max_nodes }}，超出部分不会被启用（每个节点一个独立端口，超出即浪费）。
            「立即更新节点」会自动收敛到上限内。
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="addVisible" title="手工添加节点" width="560px">
      <el-input v-model="newNodeUrl" type="textarea" :rows="4"
                placeholder="粘贴 vmess:// / vless:// / trojan:// / ss:// 完整节点串" />
      <div class="hint">
        手工节点不会自动更新，订阅刷新时会被覆盖。免费节点寿命很短，优先用「立即更新节点」。
      </div>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="onAdd">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus, Refresh, MagicStick } from '@element-plus/icons-vue'
import {
  getJpStatus, getJpNodes, getJpConfig, saveJpConfig, testJpSubscription,
  refreshJpNodes, addJpNode, clearJpNodes, startJpProxy, stopJpProxy, restartJpProxy
} from '@/api/proxyJp'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const refreshing = ref(false)
const adding = ref(false)

const status = ref({})
const nodes = ref([])
const logLines = ref([])
const form = ref({ sub_urls: [], refresh_hours: 8, sample: 40 })
const addVisible = ref(false)
const newNodeUrl = ref('')

const exitIp = computed(() => status.value.exit_ip?.ip || '')
const exitCountry = computed(() => status.value.exit_ip?.country || '')
const overCount = computed(() => Math.max(0, nodes.value.length - (status.value.max_nodes || 4)))

const nextRefreshHint = computed(() => {
  const h = Number(form.value.refresh_hours) || 0
  return h >= 24 ? `${Math.round(h / 24)} 天后` : `${h} 小时后`
})

// 节点寿命以小时计，池子显示「已存活 X 小时」比显示时间戳更能说明新鲜度
const ageHint = computed(() => {
  const t = status.value.nodes?.updated_at
  if (!t) return ''
  const then = new Date(String(t).replace(/-/g, '/')).getTime()
  if (!then) return ''
  const h = (Date.now() - then) / 3600000
  if (h < 0) return ''
  if (h < 1) return `${Math.round(h * 60)} 分钟前`
  if (h < 48) return `${h.toFixed(1)} 小时前`
  return `${(h / 24).toFixed(1)} 天前`
})

async function loadStatus() {
  const r = await getJpStatus(true)
  // 🔴 不要写 r.data：api/index.js 的响应拦截器已 `response => response.data`，
  // 这里的 r **就是** 后端返回体。再取 .data 会变成 undefined，
  // 表现为「订阅源空白 / 节点池 0 个」但接口 200 正常（2026-10-05 实测踩到）。
  status.value = r || {}
}

async function loadNodes() {
  const r = await getJpNodes()
  nodes.value = r?.nodes || []
}

async function loadConfig() {
  const d = await getJpConfig() || {}
  form.value = {
    sub_urls: Array.isArray(d.sub_urls) ? [...d.sub_urls] : [],
    refresh_hours: d.refresh_hours || 8,
    sample: d.sample || 40
  }
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadStatus(), loadNodes(), loadConfig()])
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function onSave() {
  const subs = form.value.sub_urls.map((s) => String(s).trim()).filter(Boolean)
  if (!subs.length) {
    ElMessage.warning('至少保留一个订阅源')
    return
  }
  saving.value = true
  try {
    await saveJpConfig({
      sub_urls: subs,
      refresh_hours: form.value.refresh_hours,
      sample: form.value.sample
    })
    ElMessage.success('已保存')
    await Promise.all([loadConfig(), loadStatus()])
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function onTestSub() {
  const subs = form.value.sub_urls.map((s) => String(s).trim()).filter(Boolean)
  if (!subs.length) {
    ElMessage.warning('请先填写订阅源')
    return
  }
  testing.value = true
  try {
    const r = await testJpSubscription(subs)
    const d = r || {}
    if (d.ok) {
      ElMessage.success(`可用：解析到 ${d.total} 个节点，来自 ${d.host_count} 台服务器`)
    } else {
      ElMessage.error('订阅源不可用：' + ((d.errors || []).join('; ') || '未解析到节点'))
    }
  } catch (e) {
    ElMessage.error('测试失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    testing.value = false
  }
}

async function onRefresh() {
  refreshing.value = true
  logLines.value = []
  try {
    const r = await refreshJpNodes({ sample: form.value.sample })
    const d = r || {}
    logLines.value = d.log || []
    if (d.ok) {
      ElMessage.success(`已更新 ${d.kept} 个节点（订阅 ${d.total} / 取样 ${d.sampled}）`)
    } else {
      ElMessage.warning('本轮没有可用节点，已保留原节点池')
    }
    await Promise.all([loadStatus(), loadNodes()])
  } catch (e) {
    ElMessage.error('更新失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    refreshing.value = false
  }
}

async function onStart() {
  try {
    await startJpProxy()
    ElMessage.success('已启动')
  } catch (e) {
    ElMessage.error('启动失败: ' + (e.response?.data?.detail || e.message))
  }
  await loadStatus()
}

async function onStop() {
  await stopJpProxy()
  ElMessage.info('已停止')
  await loadStatus()
}

async function onRestart() {
  try {
    await restartJpProxy()
    ElMessage.success('已重启')
  } catch (e) {
    ElMessage.error('重启失败: ' + (e.response?.data?.detail || e.message))
  }
  await loadStatus()
}

function openAdd() {
  newNodeUrl.value = ''
  addVisible.value = true
}

async function onAdd() {
  const u = newNodeUrl.value.trim()
  if (!u) return
  adding.value = true
  try {
    await addJpNode(u)
    ElMessage.success('已添加')
    addVisible.value = false
    await loadNodes()
  } catch (e) {
    ElMessage.error('添加失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    adding.value = false
  }
}

async function onClear() {
  try {
    await ElMessageBox.confirm(
      '清空后日本出口将不可用，DMM 刮削会失败。确定继续？', '清空节点池',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await clearJpNodes()
    ElMessage.success('已清空')
    await loadNodes()
  } catch (e) {
    ElMessage.error('清空失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.jp-page {
  padding: 16px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}
.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.sub {
  margin: 0;
  color: #909399;
  font-size: 13px;
}
.mb {
  margin-bottom: 12px;
}
.stat {
  text-align: left;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.stat-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  word-break: break-all;
}
.stat-value.small {
  font-size: 13px;
  font-weight: 500;
}
.unit {
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}
.stat-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: center;
  gap: 4px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sub-list {
  width: 100%;
}
.sub-row {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}
.hint {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
.hint.warn {
  color: #e6a23c;
  margin-top: 10px;
}
.svc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.err {
  color: #f56c6c;
  font-size: 12px;
}
.log {
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.7;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  color: #606266;
  font-family: Consolas, Monaco, monospace;
}
</style>
