<template>
  <div class="deploy-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>部署档位管理</h2>
      <p class="subtitle">四档渐进式部署方案 · 从单机到 Kubernetes 集群，按需选择</p>
    </div>

    <!-- 当前运行档位卡片 -->
    <el-card class="current-tier-card" shadow="hover" v-loading="loading.current">
      <div class="current-tier-content">
        <div class="current-tier-icon" :style="{ background: tierColor(currentTier?.tier_id) }">
          <el-icon size="32"><Cpu /></el-icon>
        </div>
        <div class="current-tier-info">
          <div class="tier-badge" :style="{ background: tierColor(currentTier?.tier_id) }">
            {{ currentTier?.name || '检测中' }}
          </div>
          <h3>{{ currentTier?.tagline || '正在检测当前部署环境...' }}</h3>
          <p class="description">{{ currentTier?.description }}</p>
          <div class="tech-stack" v-if="currentTier">
            <el-tag size="small" type="info">{{ currentTier.runtime }}</el-tag>
            <el-tag size="small" type="success">{{ currentTier.database }}</el-tag>
            <el-tag size="small" type="warning" v-if="currentTier.cache !== '无'">{{ currentTier.cache }}</el-tag>
            <el-tag size="small" type="danger" v-if="currentTier.tls_termination">TLS</el-tag>
          </div>
        </div>
        <div class="current-tier-actions">
          <el-button type="primary" @click="loadRuntimeInfo" :loading="loading.runtime">
            <el-icon><Refresh /></el-icon>
            刷新环境信息
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 运行时环境信息（折叠面板） -->
    <el-collapse v-if="runtimeInfo" v-model="runtimeCollapse" class="runtime-collapse">
      <el-collapse-item title="运行时环境详情（诊断信息）" name="runtime">
        <div class="runtime-grid">
          <div class="runtime-item">
            <span class="label">检测档位</span>
            <el-tag :type="runtimeInfo.detected_tier === runtimeInfo.explicit_tier || !runtimeInfo.explicit_tier ? 'success' : 'warning'">
              {{ runtimeInfo.detected_tier }}
            </el-tag>
          </div>
          <div class="runtime-item">
            <span class="label">显式指定</span>
            <span>{{ runtimeInfo.explicit_tier || '(未指定，自动检测)' }}</span>
          </div>
          <div class="runtime-item">
            <span class="label">Docker 容器</span>
            <el-tag :type="runtimeInfo.environment.is_docker ? 'success' : 'info'" size="small">
              {{ runtimeInfo.environment.is_docker ? '是' : '否' }}
            </el-tag>
          </div>
          <div class="runtime-item">
            <span class="label">Kubernetes</span>
            <el-tag :type="runtimeInfo.environment.is_kubernetes ? 'success' : 'info'" size="small">
              {{ runtimeInfo.environment.is_kubernetes ? '是' : '否' }}
            </el-tag>
          </div>
          <div class="runtime-item">
            <span class="label">Docker Compose</span>
            <el-tag :type="runtimeInfo.environment.is_docker_compose ? 'success' : 'info'" size="small">
              {{ runtimeInfo.environment.is_docker_compose ? '是' : '否' }}
            </el-tag>
          </div>
          <div class="runtime-item">
            <span class="label">Python</span>
            <span>{{ runtimeInfo.runtime.python_version }}</span>
          </div>
          <div class="runtime-item">
            <span class="label">平台</span>
            <span>{{ runtimeInfo.runtime.platform }}</span>
          </div>
          <div class="runtime-item">
            <span class="label">主机名</span>
            <span>{{ runtimeInfo.runtime.hostname }}</span>
          </div>
        </div>
        <div class="env-vars-list" v-if="Object.keys(runtimeInfo.mdcx_env_vars).length">
          <div class="env-vars-title">MDCX 环境变量：</div>
          <el-table :data="envVarsTable" size="small" border>
            <el-table-column prop="name" label="变量名" width="220" />
            <el-table-column prop="value" label="值" />
          </el-table>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- 四档对比 -->
    <div class="section-title">
      <h3>四档部署方案对比</h3>
      <p>根据使用场景和性能需求选择合适的部署档位</p>
    </div>

    <div class="tiers-grid" v-loading="loading.tiers">
      <el-card
        v-for="tier in tiers"
        :key="tier.tier_id"
        class="tier-card"
        :class="{ active: tier.is_current }"
        shadow="hover"
        @click="selectTier(tier.tier_id)"
      >
        <div class="tier-card-header" :style="{ background: tierColor(tier.tier_id) }">
          <el-icon size="24"><component :is="tierIcon(tier.tier_id)" /></el-icon>
          <span class="tier-name">{{ tier.name }}</span>
          <el-tag v-if="tier.is_current" type="success" effect="dark" size="small">当前</el-tag>
        </div>
        <div class="tier-card-body">
          <p class="tagline">{{ tier.tagline }}</p>
          <div class="tier-meta">
            <div class="meta-row">
              <span class="meta-label">数据库</span>
              <span class="meta-value">{{ tier.database }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">缓存</span>
              <span class="meta-value">{{ tier.cache }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">代理</span>
              <span class="meta-value">{{ tier.reverse_proxy }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">扩展</span>
              <span class="meta-value">{{ tier.scalability }}</span>
            </div>
          </div>
          <div class="tier-features">
            <div class="feature-tags">
              <el-tag size="small" :type="tier.high_availability ? 'success' : 'info'">
                {{ tier.high_availability ? '高可用' : '单点' }}
              </el-tag>
              <el-tag size="small" :type="tier.auto_scaling ? 'success' : 'info'">
                {{ tier.auto_scaling ? '自动扩缩' : '固定副本' }}
              </el-tag>
              <el-tag size="small" :type="tier.tls_termination ? 'success' : 'info'">
                {{ tier.tls_termination ? 'TLS' : '无 TLS' }}
              </el-tag>
            </div>
          </div>
          <div class="tier-resources">
            <div class="resource-row">
              <span class="resource-label">最低</span>
              <span class="resource-value">{{ formatResources(tier.min_resources) }}</span>
            </div>
            <div class="resource-row">
              <span class="resource-label">推荐</span>
              <span class="resource-value">{{ formatResources(tier.recommended_resources) }}</span>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 选中档位详情 -->
    <el-dialog
      v-model="detailVisible"
      :title="`${selectedTierDetail?.name || ''} - 部署详情`"
      width="80%"
      top="5vh"
      class="tier-detail-dialog"
    >
      <div v-loading="loading.detail">
        <el-tabs v-model="detailTab" v-if="selectedTierDetail">
          <!-- 概览 -->
          <el-tab-pane label="概览" name="overview">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="档位 ID">{{ selectedTierDetail.tier_id }}</el-descriptions-item>
              <el-descriptions-item label="名称">{{ selectedTierDetail.name }}</el-descriptions-item>
              <el-descriptions-item label="标语">{{ selectedTierDetail.tagline }}</el-descriptions-item>
              <el-descriptions-item label="运行时">{{ selectedTierDetail.runtime }}</el-descriptions-item>
              <el-descriptions-item label="数据库">{{ selectedTierDetail.database }}</el-descriptions-item>
              <el-descriptions-item label="缓存">{{ selectedTierDetail.cache }}</el-descriptions-item>
              <el-descriptions-item label="反向代理">{{ selectedTierDetail.reverse_proxy }}</el-descriptions-item>
              <el-descriptions-item label="编排工具">{{ selectedTierDetail.orchestration }}</el-descriptions-item>
              <el-descriptions-item label="扩展能力">{{ selectedTierDetail.scalability }}</el-descriptions-item>
              <el-descriptions-item label="高可用">
                <el-tag :type="selectedTierDetail.high_availability ? 'success' : 'info'" size="small">
                  {{ selectedTierDetail.high_availability ? '支持' : '不支持' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="自动扩缩">
                <el-tag :type="selectedTierDetail.auto_scaling ? 'success' : 'info'" size="small">
                  {{ selectedTierDetail.auto_scaling ? '支持' : '不支持' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="TLS 终止">
                <el-tag :type="selectedTierDetail.tls_termination ? 'success' : 'info'" size="small">
                  {{ selectedTierDetail.tls_termination ? '支持' : '不支持' }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>

            <el-divider content-position="left">描述</el-divider>
            <p class="detail-description">{{ selectedTierDetail.description }}</p>

            <el-divider content-position="left">适用场景</el-divider>
            <div class="use-cases">
              <el-tag v-for="uc in selectedTierDetail.use_cases" :key="uc" class="use-case-tag">
                {{ uc }}
              </el-tag>
            </div>

            <el-divider content-position="left">资源要求</el-divider>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-card shadow="never">
                  <template #header>最低配置</template>
                  <div v-for="(v, k) in selectedTierDetail.min_resources" :key="k" class="resource-line">
                    <span class="resource-key">{{ resourceLabel(k) }}</span>
                    <span class="resource-val">{{ v }}</span>
                  </div>
                </el-card>
              </el-col>
              <el-col :span="12">
                <el-card shadow="never">
                  <template #header>推荐配置</template>
                  <div v-for="(v, k) in selectedTierDetail.recommended_resources" :key="k" class="resource-line">
                    <span class="resource-key">{{ resourceLabel(k) }}</span>
                    <span class="resource-val">{{ v }}</span>
                  </div>
                </el-card>
              </el-col>
            </el-row>
          </el-tab-pane>

          <!-- 特性与限制 -->
          <el-tab-pane label="特性与限制" name="features">
            <el-row :gutter="20">
              <el-col :span="14">
                <el-card shadow="never">
                  <template #header>
                    <span style="color: var(--el-color-success)">✓ 支持的特性</span>
                  </template>
                  <ul class="feature-list">
                    <li v-for="f in selectedTierDetail.features" :key="f" class="feature-item positive">
                      <el-icon><CircleCheck /></el-icon>
                      <span>{{ f }}</span>
                    </li>
                  </ul>
                </el-card>
              </el-col>
              <el-col :span="10">
                <el-card shadow="never">
                  <template #header>
                    <span style="color: var(--el-color-warning)">⚠ 已知限制</span>
                  </template>
                  <ul class="feature-list">
                    <li v-for="l in selectedTierDetail.limitations" :key="l" class="feature-item negative">
                      <el-icon><WarningFilled /></el-icon>
                      <span>{{ l }}</span>
                    </li>
                  </ul>
                </el-card>
              </el-col>
            </el-row>
          </el-tab-pane>

          <!-- 部署指南 -->
          <el-tab-pane label="部署指南" name="guide">
            <div v-loading="loading.guide">
              <div v-if="guide">
                <el-divider content-position="left">部署步骤</el-divider>
                <ol class="steps-list">
                  <li v-for="step in guide.steps" :key="step">{{ step }}</li>
                </ol>

                <el-divider content-position="left">部署命令</el-divider>
                <div class="command-block">
                  <div class="command-header">
                    <span>命令行</span>
                    <el-button text size="small" @click="copyCommands(guide.commands)">
                      <el-icon><CopyDocument /></el-icon> 复制
                    </el-button>
                  </div>
                  <pre class="command-pre"><code v-for="(cmd, i) in guide.commands" :key="i">{{ cmd }}{{ '\n' }}</code></pre>
                </div>

                <el-divider content-position="left">注意事项</el-divider>
                <ul class="notes-list">
                  <li v-for="note in guide.notes" :key="note">
                    <el-icon><InfoFilled /></el-icon>
                    <span>{{ note }}</span>
                  </li>
                </ul>

                <el-alert
                  :title="`部署命令: ${guide.deploy_command}`"
                  type="info"
                  :closable="false"
                  class="deploy-cmd-alert"
                />
              </div>
            </div>
          </el-tab-pane>

          <!-- 部署文件 -->
          <el-tab-pane label="部署文件" name="files">
            <div v-loading="loading.files">
              <el-table :data="tierFiles" border v-if="tierFiles.length">
                <el-table-column prop="path" label="文件路径" min-width="280" />
                <el-table-column prop="description" label="说明" min-width="200" />
                <el-table-column prop="required" label="必需" width="80" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.required ? 'danger' : 'info'" size="small">
                      {{ row.required ? '必需' : '可选' }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="暂无文件清单" />
            </div>
          </el-tab-pane>

          <!-- 环境变量 -->
          <el-tab-pane label="环境变量" name="env-vars">
            <div v-loading="loading.envVars">
              <el-table :data="tierEnvVars" border v-if="tierEnvVars.length">
                <el-table-column prop="name" label="变量名" min-width="200" />
                <el-table-column prop="description" label="说明" min-width="180" />
                <el-table-column prop="default" label="默认值" min-width="120" />
                <el-table-column prop="required" label="必需" width="80" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.required ? 'danger' : 'info'" size="small">
                      {{ row.required ? '必需' : '可选' }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="暂无环境变量" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Cpu, Refresh, CircleCheck, WarningFilled, CopyDocument, InfoFilled,
  Monitor, Connection, Box, Coordinate
} from '@element-plus/icons-vue'
import {
  getDeployTiers, getCurrentDeployTier, getDeployTierDetail,
  getDeployTierFiles, getDeployTierEnvVars, getDeployRuntimeInfo, getDeployGuide
} from '@/api'

// ========== 数据 ==========
const currentTier = ref(null)
const tiers = ref([])
const runtimeInfo = ref(null)
const runtimeCollapse = ref([])

const detailVisible = ref(false)
const detailTab = ref('overview')
const selectedTierDetail = ref(null)
const guide = ref(null)
const tierFiles = ref([])
const tierEnvVars = ref([])

const loading = reactive({
  current: false,
  tiers: false,
  runtime: false,
  detail: false,
  guide: false,
  files: false,
  envVars: false
})

// ========== 计算属性 ==========
const envVarsTable = computed(() => {
  if (!runtimeInfo.value?.mdcx_env_vars) return []
  return Object.entries(runtimeInfo.value.mdcx_env_vars).map(([name, value]) => ({ name, value }))
})

// ========== 方法 ==========
function tierColor(tierId) {
  const colors = {
    lite: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
    standard: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    advanced: 'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
    enterprise: 'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)'
  }
  return colors[tierId] || colors.lite
}

function tierIcon(tierId) {
  const icons = {
    lite: Monitor,
    standard: Box,
    advanced: Connection,
    enterprise: Coordinate
  }
  return icons[tierId] || Monitor
}

function formatResources(resources) {
  if (!resources) return '-'
  return Object.entries(resources).map(([k, v]) => `${resourceLabel(k)}: ${v}`).join(' · ')
}

function resourceLabel(key) {
  const labels = {
    cpu: 'CPU',
    memory: '内存',
    disk: '磁盘',
    nodes: '节点数'
  }
  return labels[key] || key
}

async function loadCurrent() {
  loading.current = true
  try {
    currentTier.value = await getCurrentDeployTier()
  } catch (e) {
    // 静默失败
  } finally {
    loading.current = false
  }
}

async function loadTiers() {
  loading.tiers = true
  try {
    const data = await getDeployTiers()
    tiers.value = data.tiers
  } catch (e) {
    // 静默失败
  } finally {
    loading.tiers = false
  }
}

async function loadRuntimeInfo() {
  loading.runtime = true
  try {
    runtimeInfo.value = await getDeployRuntimeInfo()
    runtimeCollapse.value = ['runtime']
    ElMessage.success('运行时环境已刷新')
  } catch (e) {
    // 错误已由拦截器提示
  } finally {
    loading.runtime = false
  }
}

async function selectTier(tierId) {
  detailVisible.value = true
  detailTab.value = 'overview'
  selectedTierDetail.value = null
  guide.value = null
  tierFiles.value = []
  tierEnvVars.value = []

  // 并行加载详情
  loading.detail = true
  try {
    selectedTierDetail.value = await getDeployTierDetail(tierId)
  } catch (e) {
    // 静默
  } finally {
    loading.detail = false
  }

  // 预加载指南
  loadGuide(tierId)
  loadFiles(tierId)
  loadEnvVars(tierId)
}

async function loadGuide(tierId) {
  loading.guide = true
  try {
    guide.value = await getDeployGuide(tierId)
  } catch (e) {
    // 静默
  } finally {
    loading.guide = false
  }
}

async function loadFiles(tierId) {
  loading.files = true
  try {
    const data = await getDeployTierFiles(tierId)
    tierFiles.value = data.files
  } catch (e) {
    // 静默
  } finally {
    loading.files = false
  }
}

async function loadEnvVars(tierId) {
  loading.envVars = true
  try {
    const data = await getDeployTierEnvVars(tierId)
    tierEnvVars.value = data.env_vars
  } catch (e) {
    // 静默
  } finally {
    loading.envVars = false
  }
}

async function copyCommands(commands) {
  try {
    await navigator.clipboard.writeText(commands.join('\n'))
    ElMessage.success('命令已复制到剪贴板')
  } catch (e) {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

// ========== 初始化 ==========
onMounted(() => {
  loadCurrent()
  loadTiers()
})
</script>

<style scoped>
.deploy-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
}
.page-header h2 {
  margin: 0 0 8px 0;
  font-size: 24px;
}
.page-header .subtitle {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

/* 当前档位卡片 */
.current-tier-card {
  margin-bottom: 20px;
  border: none;
  background: var(--el-bg-color);
}
.current-tier-content {
  display: flex;
  align-items: center;
  gap: 24px;
}
.current-tier-icon {
  width: 80px;
  height: 80px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}
.current-tier-info {
  flex: 1;
  min-width: 0;
}
.current-tier-info .tier-badge {
  display: inline-block;
  padding: 2px 12px;
  border-radius: 12px;
  color: white;
  font-size: 12px;
  margin-bottom: 8px;
}
.current-tier-info h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
}
.current-tier-info .description {
  margin: 0 0 12px 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}
.tech-stack {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.current-tier-actions {
  flex-shrink: 0;
}

/* 运行时折叠面板 */
.runtime-collapse {
  margin-bottom: 24px;
}
.runtime-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
.runtime-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.runtime-item .label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  min-width: 80px;
}
.env-vars-title {
  margin-bottom: 8px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}

/* 区块标题 */
.section-title {
  margin-bottom: 16px;
}
.section-title h3 {
  margin: 0 0 4px 0;
  font-size: 18px;
}
.section-title p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

/* 四档网格 */
.tiers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.tier-card {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  border: 2px solid transparent;
}
.tier-card:hover {
  transform: translateY(-4px);
}
.tier-card.active {
  border-color: var(--el-color-success);
}
.tier-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  color: white;
  border-radius: 4px 4px 0 0;
  margin: -20px -20px 16px -20px;
}
.tier-card-header .tier-name {
  font-size: 16px;
  font-weight: 600;
  flex: 1;
}
.tier-card-body {
  padding: 0;
}
.tier-card-body .tagline {
  margin: 0 0 12px 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.tier-meta {
  margin-bottom: 12px;
}
.meta-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.meta-row:last-child {
  border-bottom: none;
}
.meta-label {
  color: var(--el-text-color-secondary);
}
.meta-value {
  font-weight: 500;
  text-align: right;
}
.feature-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.tier-resources {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 8px 12px;
}
.resource-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 2px 0;
}
.resource-label {
  color: var(--el-text-color-secondary);
}

/* 详情对话框 */
.tier-detail-dialog :deep(.el-dialog__body) {
  max-height: 75vh;
  overflow-y: auto;
}
.detail-description {
  margin: 0;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.use-cases {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.use-case-tag {
  margin: 0;
}
.resource-line {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.resource-line:last-child {
  border-bottom: none;
}
.resource-key {
  color: var(--el-text-color-secondary);
}
.resource-val {
  font-weight: 500;
}

/* 特性列表 */
.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
  font-size: 13px;
  line-height: 1.5;
}
.feature-item:last-child {
  border-bottom: none;
}
.feature-item.positive .el-icon {
  color: var(--el-color-success);
  flex-shrink: 0;
  margin-top: 2px;
}
.feature-item.negative .el-icon {
  color: var(--el-color-warning);
  flex-shrink: 0;
  margin-top: 2px;
}

/* 命令块 */
.command-block {
  background: var(--el-fill-color-darker);
  border-radius: 6px;
  overflow: hidden;
  margin: 8px 0;
}
.command-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--el-fill-color-dark);
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.command-pre {
  margin: 0;
  padding: 12px 16px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  overflow-x: auto;
  color: var(--el-color-success);
}
.command-pre code {
  display: block;
  white-space: pre;
}

/* 步骤与注意事项 */
.steps-list {
  margin: 0;
  padding-left: 20px;
  line-height: 2;
}
.notes-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.notes-list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
  line-height: 1.6;
}
.notes-list .el-icon {
  color: var(--el-color-info);
  flex-shrink: 0;
  margin-top: 3px;
}
.deploy-cmd-alert {
  margin-top: 16px;
}
.deploy-cmd-alert :deep(.el-alert__title) {
  font-family: 'Consolas', monospace;
}

/* 暗黑模式适配 */
:deep(.dark) .command-block,
:deep(.dark) .command-pre {
  background: #1a1a1a;
}
:deep(.dark) .command-pre {
  color: #67c23a;
}
</style>
