<template>
  <div class="network-diag-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Connection /></el-icon>
          网络诊断中心
        </h2>
        <div class="page-subtitle">站点连通性 / 代理可用性 / Cookie 有效性 一键诊断</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadConfig" :loading="loadingConfig">
          <el-icon><Refresh /></el-icon> 重载配置
        </el-button>
        <el-button type="primary" @click="runFullDiag" :loading="running">
          <el-icon><Cpu /></el-icon> 运行完整诊断
        </el-button>
      </div>
    </div>

    <!-- 概览卡片 -->
    <el-row :gutter="16" class="summary-row">
      <el-col :span="6">
        <el-card shadow="never" class="summary-card ok">
          <div class="summary-num">{{ report.summary.ok || 0 }}</div>
          <div class="summary-label">OK · 正常</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="summary-card warning">
          <div class="summary-num">{{ report.summary.warning || 0 }}</div>
          <div class="summary-label">WARNING · 警告</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="summary-card failed">
          <div class="summary-num">{{ report.summary.failed || 0 }}</div>
          <div class="summary-label">FAILED · 失败</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="summary-card skipped">
          <div class="summary-num">{{ report.summary.skipped || 0 }}</div>
          <div class="summary-label">SKIPPED · 跳过</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <!-- 左侧：站点列表与诊断 -->
      <el-col :span="16">
        <el-card shadow="never" class="diag-card">
          <template #header>
            <div class="card-title">
              <el-icon><Histogram /></el-icon> 诊断项
              <span v-if="report.total_duration_ms" class="diag-time">
                总耗时 {{ report.total_duration_ms }}ms
              </span>
            </div>
          </template>

          <el-table :data="report.items" stripe style="width: 100%" empty-text="尚未运行诊断">
            <el-table-column label="诊断项" min-width="180">
              <template #default="{ row }">
                <div class="diag-name">
                  <el-icon :class="statusClass(row.status)">
                    <SuccessFilled v-if="row.status === 'OK'" />
                    <WarningFilled v-else-if="row.status === 'WARNING'" />
                    <CircleCloseFilled v-else-if="row.status === 'FAILED'" />
                    <RemoveFilled v-else />
                  </el-icon>
                  <span>{{ row.name }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" effect="dark" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="100">
              <template #default="{ row }">
                <span class="diag-duration">{{ row.duration_ms }}ms</span>
              </template>
            </el-table-column>
            <el-table-column label="详情" min-width="280">
              <template #default="{ row }">
                <div class="diag-message">{{ row.message }}</div>
                <div v-if="row.details && Object.keys(row.details).length" class="diag-details">
                  <el-tag
                    v-for="(v, k) in row.details"
                    :key="k"
                    size="small"
                    type="info"
                    class="detail-tag"
                  >{{ k }}: {{ v }}</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  link
                  type="primary"
                  @click="recheck(row)"
                  :loading="rechecking === row.name"
                >重检</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 单项检查 -->
        <el-card shadow="never" class="single-card">
          <template #header>
            <div class="card-title"><el-icon><Aim /></el-icon> 单项快速检查</div>
          </template>
          <el-form inline>
            <el-form-item label="检查类型">
              <el-radio-group v-model="singleForm.check_type">
                <el-radio-button value="site">站点连通</el-radio-button>
                <el-radio-button value="proxy">代理可用</el-radio-button>
                <el-radio-button value="cookie">Cookie</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="singleForm.check_type !== 'proxy'" label="站点">
              <el-select v-model="singleForm.site" placeholder="选择站点" style="width: 180px">
                <el-option
                  v-for="site in siteList"
                  :key="site.name"
                  :label="site.name"
                  :value="site.name"
                >
                  <span>{{ site.name }}</span>
                  <span class="opt-url">{{ site.url }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="超时">
              <el-input-number v-model="singleForm.timeout" :min="3" :max="60" size="small" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="runSingle" :loading="singleLoading">
                <el-icon><VideoPlay /></el-icon> 执行检查
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="singleResult"
            :title="`${singleResult.name} · ${singleResult.status} · ${singleResult.duration_ms}ms`"
            :type="alertType(singleResult.status)"
            :description="singleResult.message"
            show-icon
            :closable="false"
            style="margin-top: 12px"
          />
        </el-card>
      </el-col>

      <!-- 右侧：配置 -->
      <el-col :span="8">
        <el-card shadow="never" class="config-card">
          <template #header>
            <div class="card-title"><el-icon><Setting /></el-icon> 诊断配置</div>
          </template>
          <el-form :model="configForm" label-width="100px">
            <el-form-item label="超时(秒)">
              <el-input-number v-model="configForm.timeout" :min="3" :max="60" />
            </el-form-item>
            <el-form-item label="目标站点">
              <el-checkbox-group v-model="configForm.target_sites">
                <el-checkbox
                  v-for="site in siteList"
                  :key="site.name"
                  :value="site.name"
                  class="site-checkbox"
                >
                  {{ site.name }}
                </el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveConfig" :loading="savingConfig">
                <el-icon><Check /></el-icon> 保存配置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 代理状态 -->
        <el-card shadow="never" class="proxy-card">
          <template #header>
            <div class="card-title"><el-icon><Promotion /></el-icon> 代理状态</div>
          </template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="启用状态">
              <el-tag :type="proxyInfo.enabled ? 'success' : 'info'" size="small">
                {{ proxyInfo.enabled ? '已启用' : '未启用' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="协议">{{ proxyInfo.protocol || '-' }}</el-descriptions-item>
            <el-descriptions-item label="地址">{{ proxyInfo.address || '-' }}:{{ proxyInfo.port || '-' }}</el-descriptions-item>
            <el-descriptions-item label="完整 URL">
              <code class="proxy-url">{{ proxyInfo.enabled ? proxyInfo.proxy_url : '（未启用）' }}</code>
            </el-descriptions-item>
          </el-descriptions>
          <el-button
            type="primary"
            plain
            style="margin-top: 12px; width: 100%"
            @click="quickCheckProxy"
            :loading="proxyChecking"
          >
            <el-icon><Promotion /></el-icon> 快速检查代理
          </el-button>
        </el-card>

        <!-- 站点参考表 -->
        <el-card shadow="never" class="sites-ref-card">
          <template #header>
            <div class="card-title"><el-icon><Link /></el-icon> 支持诊断的站点</div>
          </template>
          <div class="sites-list">
            <div v-for="site in siteList" :key="site.name" class="site-row">
              <span class="site-name">{{ site.name }}</span>
              <a :href="site.url" target="_blank" class="site-url" :title="site.url">{{ site.url }}</a>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Connection, Refresh, Cpu, Setting, Check, Promotion, Link,
  Histogram, Aim, VideoPlay,
  SuccessFilled, WarningFilled, CircleCloseFilled, RemoveFilled,
} from '@element-plus/icons-vue'
import {
  getDiagSites, runDiagnosis, singleCheck,
  getDiagConfig, updateDiagConfig,
} from '@/api'

// 站点列表
const siteList = ref([])
const loadingConfig = ref(false)
const running = ref(false)
const savingConfig = ref(false)
const singleLoading = ref(false)
const proxyChecking = ref(false)
const rechecking = ref('')

// 诊断报告
const report = reactive({
  started_at: '',
  finished_at: '',
  total_duration_ms: 0,
  summary: { total: 0, ok: 0, warning: 0, failed: 0, skipped: 0 },
  items: [],
})

// 配置表单
const configForm = reactive({
  timeout: 10,
  target_sites: [],
})

// 代理信息（从 localStorage 或后端读取）
const proxyInfo = reactive({
  enabled: false,
  protocol: 'http',
  address: '',
  port: '',
  proxy_url: '',
})

// 单项检查表单
const singleForm = reactive({
  check_type: 'site',
  site: 'javdb',
  timeout: 10,
})

const singleResult = ref(null)

// 加载站点列表
const loadSites = async () => {
  try {
    const data = await getDiagSites()
    siteList.value = data.all_sites || []
    if (!singleForm.site && data.target_sites?.length) {
      singleForm.site = data.target_sites[0]
    }
  } catch (e) {
    // 错误已由拦截器处理
  }
}

// 加载配置
const loadConfig = async () => {
  loadingConfig.value = true
  try {
    const [cfg] = await Promise.all([getDiagConfig(), getDiagSites()])
    configForm.timeout = cfg.timeout || 10
    configForm.target_sites = cfg.target_sites || []
    siteList.value = cfg.all_sites || siteList.value
    // 同步代理信息从 localStorage
    const proxyStr = localStorage.getItem('mdcx_proxy')
    if (proxyStr) {
      try {
        Object.assign(proxyInfo, JSON.parse(proxyStr))
      } catch {}
    }
    ElMessage.success('配置已加载')
  } catch (e) {
    // ignore
  } finally {
    loadingConfig.value = false
  }
}

// 保存配置
const saveConfig = async () => {
  if (configForm.target_sites.length === 0) {
    ElMessage.warning('请至少选择一个目标站点')
    return
  }
  savingConfig.value = true
  try {
    await updateDiagConfig({
      timeout: configForm.timeout,
      target_sites: configForm.target_sites,
    })
    ElMessage.success('配置已保存')
  } catch (e) {
    // ignore
  } finally {
    savingConfig.value = false
  }
}

// 运行完整诊断
const runFullDiag = async () => {
  running.value = true
  report.items = []
  report.summary = { total: 0, ok: 0, warning: 0, failed: 0, skipped: 0 }
  try {
    const data = await runDiagnosis()
    Object.assign(report, data)
    const s = data.summary || {}
    ElMessage.success(`诊断完成 · OK:${s.ok || 0} WARN:${s.warning || 0} FAIL:${s.failed || 0}`)
  } catch (e) {
    // ignore
  } finally {
    running.value = false
  }
}

// 单项检查
const runSingle = async () => {
  if (singleForm.check_type !== 'proxy' && !singleForm.site) {
    ElMessage.warning('请选择站点')
    return
  }
  singleLoading.value = true
  singleResult.value = null
  try {
    const data = await singleCheck({
      check_type: singleForm.check_type,
      site: singleForm.check_type === 'proxy' ? null : singleForm.site,
      timeout: singleForm.timeout,
    })
    singleResult.value = data
  } catch (e) {
    // ignore
  } finally {
    singleLoading.value = false
  }
}

// 重检某项
const recheck = async (row) => {
  rechecking.value = row.name
  try {
    let checkType = 'site'
    let site = null
    if (row.name === 'proxy') {
      checkType = 'proxy'
    } else if (row.name.startsWith('cookie:')) {
      checkType = 'cookie'
      site = row.name.replace('cookie:', '')
    } else if (row.name.startsWith('site:')) {
      checkType = 'site'
      site = row.name.replace('site:', '')
    }
    const data = await singleCheck({
      check_type: checkType,
      site,
      timeout: configForm.timeout,
    })
    // 替换该行
    const idx = report.items.findIndex(it => it.name === row.name)
    if (idx >= 0) {
      report.items[idx] = data
      // 重新计算汇总
      recomputeSummary()
    }
    ElMessage.success(`${row.name} 已重检：${data.status}`)
  } catch (e) {
    // ignore
  } finally {
    rechecking.value = ''
  }
}

const recomputeSummary = () => {
  const s = { total: report.items.length, ok: 0, warning: 0, failed: 0, skipped: 0 }
  for (const it of report.items) {
    if (it.status === 'OK') s.ok++
    else if (it.status === 'WARNING') s.warning++
    else if (it.status === 'FAILED') s.failed++
    else if (it.status === 'SKIPPED') s.skipped++
  }
  report.summary = s
}

// 快速检查代理
const quickCheckProxy = async () => {
  proxyChecking.value = true
  singleResult.value = null
  try {
    const data = await singleCheck({
      check_type: 'proxy',
      timeout: configForm.timeout,
    })
    singleResult.value = data
  } catch (e) {
    // ignore
  } finally {
    proxyChecking.value = false
  }
}

// 工具函数
const statusClass = (s) => ({
  'status-ok': s === 'OK',
  'status-warning': s === 'WARNING',
  'status-failed': s === 'FAILED',
  'status-skipped': s === 'SKIPPED' || s === 'CANCELLED',
})

const statusTagType = (s) => {
  const m = { OK: 'success', WARNING: 'warning', FAILED: 'danger', SKIPPED: 'info', CANCELLED: 'info' }
  return m[s] || 'info'
}

const alertType = (s) => {
  const m = { OK: 'success', WARNING: 'warning', FAILED: 'error', SKIPPED: 'info', CANCELLED: 'info' }
  return m[s] || 'info'
}

onMounted(() => {
  loadSites()
  loadConfig()
})
</script>

<style scoped>
.network-diag-page {
  padding: 4px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.page-title {
  margin: 0 0 4px 0;
  font-size: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-subtitle {
  font-size: 12px;
  color: #909399;
}

.page-header-actions {
  display: flex;
  gap: 8px;
}

.summary-row {
  margin-bottom: 16px;
}

.summary-card {
  text-align: center;
  padding: 8px 0;
  border-left: 4px solid #909399;
}

.summary-card.ok { border-left-color: #67c23a; }
.summary-card.warning { border-left-color: #e6a23c; }
.summary-card.failed { border-left-color: #f56c6c; }
.summary-card.skipped { border-left-color: #909399; }

.summary-num {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.2;
}

.summary-card.ok .summary-num { color: #67c23a; }
.summary-card.warning .summary-num { color: #e6a23c; }
.summary-card.failed .summary-num { color: #f56c6c; }
.summary-card.skipped .summary-num { color: #909399; }

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.diag-card,
.single-card,
.config-card,
.proxy-card,
.sites-ref-card {
  margin-bottom: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.diag-time {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}

.diag-name {
  display: flex;
  align-items: center;
  gap: 6px;
}

.diag-name .el-icon {
  font-size: 16px;
}

.status-ok { color: #67c23a; }
.status-warning { color: #e6a23c; }
.status-failed { color: #f56c6c; }
.status-skipped { color: #909399; }

.diag-duration {
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: #909399;
}

.diag-message {
  font-size: 13px;
  color: #303133;
}

.diag-details {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.detail-tag {
  font-size: 11px;
}

.opt-url {
  color: #909399;
  font-size: 11px;
  margin-left: 8px;
}

.site-checkbox {
  display: block;
  margin-bottom: 4px;
}

.proxy-url {
  font-family: 'Consolas', monospace;
  font-size: 11px;
  background: #f4f4f5;
  padding: 2px 6px;
  border-radius: 3px;
  word-break: break-all;
}

.sites-list {
  max-height: 320px;
  overflow-y: auto;
}

.site-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
  font-size: 12px;
}

.site-row:last-child {
  border-bottom: none;
}

.site-name {
  color: #409eff;
  font-weight: 600;
}

.site-url {
  color: #909399;
  text-decoration: none;
}

.site-url:hover {
  color: #409eff;
  text-decoration: underline;
}

:deep(.dark) .summary-card {
  background: #2c2c2c;
}

:deep(.dark) .diag-message {
  color: #e0e0e0;
}

:deep(.dark) .proxy-url {
  background: #3a3a3a;
  color: #d0d0d0;
}

:deep(.dark) .site-row {
  border-bottom-color: #3a3a3a;
}
</style>
