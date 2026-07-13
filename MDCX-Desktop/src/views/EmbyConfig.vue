<template>
  <div class="emby-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Connection /></el-icon>
          Emby 协议兼容
        </h2>
        <div class="page-subtitle">让 Infuse / VidHub / SenPlayer / Fileball 等 Emby 客户端直接访问 MDCX 媒体库</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 重载
        </el-button>
        <el-button type="primary" @click="saveAll" :loading="saving">
          <el-icon><Check /></el-icon> 保存配置
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左侧：核心配置 -->
      <el-col :span="16">
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Setting /></el-icon> 协议配置
              <el-switch
                v-model="config.enabled"
                active-text="启用"
                inactive-text="禁用"
                style="margin-left: auto"
              />
            </div>
          </template>

          <el-form :model="config" label-width="120px">
            <el-form-item label="服务器名称">
              <el-input v-model="config.server_name" placeholder="MDCX Media Server" />
              <div class="hint">客户端连接时显示的名称</div>
            </el-form-item>

            <el-form-item label="协议版本">
              <el-input v-model="config.version" placeholder="4.8.10.0" />
              <div class="hint">伪装的 Emby Server 版本号，建议保持默认</div>
            </el-form-item>

            <el-form-item label="API Key">
              <el-input v-model="config.api_key" readonly>
                <template #append>
                  <el-button @click="regenerateKey" :loading="regenerating">
                    <el-icon><RefreshRight /></el-icon> 重新生成
                  </el-button>
                  <el-button @click="copyApiKey">
                    <el-icon><CopyDocument /></el-icon> 复制
                  </el-button>
                </template>
              </el-input>
              <div class="hint">客户端登录时用作凭据（X-Emby-Token header 或 api_key query 参数）</div>
            </el-form-item>

            <el-form-item label="播放协议">
              <el-radio-group v-model="config.play_protocol">
                <el-radio-button label="http">HTTP</el-radio-button>
                <el-radio-button label="https">HTTPS</el-radio-button>
              </el-radio-group>
              <div class="hint">视频流 URL 的协议（HTTPS 需要服务器配置 TLS）</div>
            </el-form-item>

            <el-form-item label="分页大小">
              <el-input-number v-model="config.page_size" :min="10" :max="500" :step="10" />
              <div class="hint">返回给客户端的每页媒体数量</div>
            </el-form-item>

            <el-divider>NSFW 内容控制</el-divider>

            <el-form-item label="隐藏 NSFW">
              <el-switch v-model="config.nsfw_hidden" />
              <div class="hint">开启后，Emby 客户端不会展示含敏感标签的影片</div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 端点测试 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Monitor /></el-icon> 协议自检
            </div>
          </template>
          <div class="test-area">
            <el-button type="primary" @click="runTest" :loading="testing">
              <el-icon><VideoPlay /></el-icon> 测试 /emby/System/Info/Public
            </el-button>
            <el-alert
              v-if="testResult"
              :title="testResult.ok ? '✅ 协议响应正常' : '❌ 协议响应失败'"
              :type="testResult.ok ? 'success' : 'error'"
              :description="testDescription"
              show-icon
              :closable="false"
              style="margin-top: 12px"
            />
          </div>
        </el-card>

        <!-- 元数据推送（v3.1） -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Promotion /></el-icon> 元数据推送闭环
              <el-tag v-if="pushStatus" size="small" :type="pushStatus.connected ? 'success' : 'info'" style="margin-left: auto">
                {{ pushStatus.connected ? `已连接 · ${pushStatus.server_name || ''}` : (pushStatus.enabled ? '未连接' : '未启用') }}
              </el-tag>
            </div>
          </template>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
          >
            <template #title>
              刮削完成后会自动推送元数据到 Emby（在 workflow 中配置）。这里提供手动推送入口：单推、批推、刷新媒体库。
              <strong>注意：</strong>需先在下方"Emby 服务器配置"中填写 URL 与 API Key。
            </template>
          </el-alert>

          <!-- 推送目标 Emby 服务器配置（独立于协议兼容配置） -->
          <el-form :model="pushServerCfg" label-width="120px" style="margin-bottom: 12px">
            <el-form-item label="Emby URL">
              <el-input v-model="pushServerCfg.url" placeholder="http://127.0.0.1:8096" />
              <div class="hint">要推送到的 Emby 服务器地址</div>
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="pushServerCfg.api_key" placeholder="在 Emby 后台 → 高级 → API 密钥中生成" show-password />
              <div class="hint">具有写入权限的 Emby API Key</div>
            </el-form-item>
            <el-form-item>
              <el-button @click="savePushServerCfg" :loading="savingPushCfg">
                <el-icon><Check /></el-icon> 保存推送配置
              </el-button>
              <el-button @click="loadPushStatus" :loading="loadingPushStatus">
                <el-icon><Refresh /></el-icon> 检查连接
              </el-button>
            </el-form-item>
          </el-form>

          <el-divider content-position="left">批量推送</el-divider>

          <el-form :model="batchForm" label-width="120px" inline>
            <el-form-item label="制作商">
              <el-input v-model="batchForm.studio" placeholder="留空则全部" clearable style="width: 200px" />
            </el-form-item>
            <el-form-item label="数量上限">
              <el-input-number v-model="batchForm.limit" :min="1" :max="500" :step="10" />
            </el-form-item>
            <el-form-item label="仅缺海报">
              <el-switch v-model="batchForm.only_missing_poster" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="runBatchPush" :loading="batchPushing">
                <el-icon><Promotion /></el-icon> 开始批量推送
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="batchResult"
            :title="`成功 ${batchResult.success} · 失败 ${batchResult.failed} · 跳过 ${batchResult.skipped} · 共 ${batchResult.total}`"
            :type="batchResult.failed === 0 ? 'success' : 'warning'"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />

          <el-divider content-position="left">媒体库维护</el-divider>

          <div style="display: flex; gap: 12px; flex-wrap: wrap">
            <el-button @click="refreshLibrary" :loading="refreshingLib">
              <el-icon><Refresh /></el-icon> 刷新 Emby 媒体库
            </el-button>
            <el-input
              v-model="searchQuery"
              placeholder="搜索 Emby 项目测试"
              style="width: 240px"
              clearable
              @keyup.enter="searchEmbyItems"
            >
              <template #append>
                <el-button @click="searchEmbyItems" :loading="searching">
                  <el-icon><Search /></el-icon>
                </el-button>
              </template>
            </el-input>
          </div>

          <el-table
            v-if="searchResults.length"
            :data="searchResults"
            size="small"
            border
            style="margin-top: 12px"
          >
            <el-table-column prop="name" label="名称" min-width="200" />
            <el-table-column prop="type" label="类型" width="80" />
            <el-table-column prop="path" label="路径" min-width="200" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>

      <!-- 右侧：客户端接入指南 -->
      <el-col :span="8">
        <el-card shadow="never" class="guide-card">
          <template #header>
            <div class="card-title">
              <el-icon><InfoFilled /></el-icon> 客户端接入指南
            </div>
          </template>

          <div v-if="guide" class="guide-content">
            <div class="guide-block">
              <div class="guide-label">服务器地址</div>
              <el-input :model-value="guide.server_address" readonly size="small">
                <template #append>
                  <el-button @click="copyText(guide.server_address)"><el-icon><CopyDocument /></el-icon></el-button>
                </template>
              </el-input>
            </div>

            <div class="guide-block">
              <div class="guide-label">用户名 / 密码</div>
              <el-input :model-value="`${guide.username} / ${guide.password || '(空)'}`" readonly size="small" />
            </div>

            <div class="guide-block">
              <div class="guide-label">API Key</div>
              <el-input :model-value="guide.api_key" readonly size="small">
                <template #append>
                  <el-button @click="copyText(guide.api_key)"><el-icon><CopyDocument /></el-icon></el-button>
                </template>
              </el-input>
            </div>

            <el-divider>支持的客户端</el-divider>

            <el-collapse v-model="activeClients" accordion>
              <el-collapse-item
                v-for="c in guide.clients"
                :key="c.name"
                :name="c.name"
              >
                <template #title>
                  <div class="client-title">
                    <span class="client-name">{{ c.name }}</span>
                    <el-tag size="small" effect="plain">{{ c.platform }}</el-tag>
                  </div>
                </template>
                <div class="client-detail">
                  <p><strong>配置步骤：</strong>{{ c.setup }}</p>
                  <p class="muted">{{ c.notes }}</p>
                </div>
              </el-collapse-item>
            </el-collapse>

            <el-divider>关键端点</el-divider>
            <el-table :data="guide.endpoints" size="small" border>
              <el-table-column prop="method" label="方法" width="60" />
              <el-table-column prop="path" label="路径" />
              <el-table-column prop="auth" label="认证" width="70" />
              <el-table-column prop="desc" label="说明" />
            </el-table>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Connection, Setting, Refresh, Check, RefreshRight, CopyDocument,
  Monitor, VideoPlay, InfoFilled, Promotion, Search
} from '@element-plus/icons-vue'
import {
  getEmbyConfig, updateEmbyConfig, regenerateEmbyApiKey,
  testEmbyEndpoint, getEmbyClientsGuide,
  getEmbyPushConfig, updateEmbyPushConfig, getEmbyPushStatus,
  batchPushToEmby, refreshEmbyLibrary, searchEmby as searchEmbyApi
} from '@/api'

const loading = ref(false)
const saving = ref(false)
const regenerating = ref(false)
const testing = ref(false)
const testResult = ref(null)
const guide = ref(null)
const activeClients = ref('')

// ===== 推送闭环状态（v3.1） =====
const pushServerCfg = ref({ url: '', api_key: '', enabled: false })
const pushStatus = ref(null)
const savingPushCfg = ref(false)
const loadingPushStatus = ref(false)
const batchForm = ref({ studio: '', limit: 50, only_missing_poster: false })
const batchResult = ref(null)
const batchPushing = ref(false)
const refreshingLib = ref(false)
const searchQuery = ref('')
const searchResults = ref([])
const searching = ref(false)

const config = ref({
  enabled: false,
  api_key: '',
  server_name: 'MDCX Media Server',
  version: '4.8.10.0',
  play_protocol: 'http',
  nsfw_hidden: false,
  page_size: 100
})

const testDescription = computed(() => {
  if (!testResult.value) return ''
  if (testResult.value.ok) {
    return `HTTP ${testResult.value.status_code} · ServerName: ${testResult.value.server_name || '-'} · Version: ${testResult.value.version || '-'}`
  }
  return testResult.value.error || `HTTP ${testResult.value.status_code || '?'}`
})

const loadConfig = async () => {
  loading.value = true
  try {
    const data = await getEmbyConfig()
    config.value = { ...config.value, ...data }
  } catch (e) {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

const loadGuide = async () => {
  try {
    guide.value = await getEmbyClientsGuide()
    if (guide.value?.clients?.length) {
      activeClients.value = guide.value.clients[0].name
    }
  } catch (e) {
    // 忽略
  }
}

const loadAll = async () => {
  await Promise.all([loadConfig(), loadGuide()])
}

const saveAll = async () => {
  saving.value = true
  try {
    await updateEmbyConfig({
      enabled: config.value.enabled,
      api_key: config.value.api_key,
      server_name: config.value.server_name,
      version: config.value.version,
      play_protocol: config.value.play_protocol,
      nsfw_hidden: config.value.nsfw_hidden,
      page_size: config.value.page_size
    })
    ElMessage.success('Emby 兼容配置已保存')
  } catch (e) {
    // ignore
  } finally {
    saving.value = false
  }
}

const regenerateKey = async () => {
  regenerating.value = true
  try {
    const data = await regenerateEmbyApiKey()
    config.value.api_key = data.api_key
    ElMessage.success('API Key 已重新生成')
    await loadGuide()
  } catch (e) {
    // ignore
  } finally {
    regenerating.value = false
  }
}

const copyApiKey = () => copyText(config.value.api_key)

const copyText = async (text) => {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch (e) {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}

const runTest = async () => {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testEmbyEndpoint()
  } catch (e) {
    testResult.value = { ok: false, error: e.message || '请求失败' }
  } finally {
    testing.value = false
  }
}

// ===== 推送闭环方法（v3.1） =====
const loadPushServerCfg = async () => {
  try {
    const data = await getEmbyPushConfig()
    pushServerCfg.value = {
      url: data.url || '',
      api_key: data.api_key || '',
      enabled: !!data.enabled
    }
  } catch (e) {
    // 忽略
  }
}

const loadPushStatus = async () => {
  loadingPushStatus.value = true
  try {
    pushStatus.value = await getEmbyPushStatus()
  } catch (e) {
    pushStatus.value = { enabled: false, connected: false, message: e.message || '请求失败' }
  } finally {
    loadingPushStatus.value = false
  }
}

const savePushServerCfg = async () => {
  savingPushCfg.value = true
  try {
    await updateEmbyPushConfig({
      url: pushServerCfg.value.url,
      api_key: pushServerCfg.value.api_key,
      enabled: pushServerCfg.value.enabled || !!(pushServerCfg.value.url && pushServerCfg.value.api_key)
    })
    ElMessage.success('推送配置已保存')
    await loadPushStatus()
  } catch (e) {
    // ignore
  } finally {
    savingPushCfg.value = false
  }
}

const runBatchPush = async () => {
  batchPushing.value = true
  batchResult.value = null
  try {
    batchResult.value = await batchPushToEmby({
      limit: batchForm.value.limit,
      only_missing_poster: batchForm.value.only_missing_poster,
      studio: batchForm.value.studio || null
    })
    ElMessage.success(`批量推送完成：成功 ${batchResult.value.success} / ${batchResult.value.total}`)
  } catch (e) {
    ElMessage.error('批量推送失败：' + (e.message || '未知错误'))
  } finally {
    batchPushing.value = false
  }
}

const refreshLibrary = async () => {
  refreshingLib.value = true
  try {
    const res = await refreshEmbyLibrary()
    ElMessage.success(`已刷新 ${res.refreshed_views || 0} / ${res.total_views || 0} 个媒体库`)
  } catch (e) {
    ElMessage.error('刷新媒体库失败：' + (e.message || '未知错误'))
  } finally {
    refreshingLib.value = false
  }
}

const searchEmbyItems = async () => {
  if (!searchQuery.value.trim()) return
  searching.value = true
  try {
    const res = await searchEmbyApi(searchQuery.value.trim(), 20)
    searchResults.value = res.items || []
    if (!searchResults.value.length) ElMessage.info('未找到匹配项目')
  } catch (e) {
    ElMessage.error('搜索失败：' + (e.message || '未知错误'))
  } finally {
    searching.value = false
  }
}

onMounted(() => {
  loadAll()
  loadPushServerCfg()
  loadPushStatus()
})
</script>

<style scoped>
.emby-page {
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
.guide-card {
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
  line-height: 1.4;
}

.test-area {
  padding: 8px 0;
}

.guide-content {
  font-size: 14px;
}

.guide-block {
  margin-bottom: 12px;
}

.guide-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.client-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.client-name {
  font-weight: 600;
}

.client-detail p {
  margin: 6px 0;
  line-height: 1.5;
  font-size: 13px;
}

.client-detail .muted {
  color: #909399;
}

:deep(.el-collapse-item__header) {
  padding: 0 12px;
}

:deep(.el-collapse-item__content) {
  padding: 8px 12px 16px;
}
</style>
