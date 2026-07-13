<template>
  <div class="tvbox-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Connection /></el-icon>
          TVBox / MacCMS 开放接口
        </h2>
        <div class="page-subtitle">让 TVBox、MacCMS 客户端及影视 App 直接接入 MDCX 媒体库</div>
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
      <!-- 左侧：配置 -->
      <el-col :span="16">
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Setting /></el-icon> 接口配置
              <el-switch
                v-model="config.enabled"
                active-text="启用"
                inactive-text="禁用"
                style="margin-left: auto"
              />
            </div>
          </template>

          <el-form :model="config" label-width="120px">
            <el-form-item label="站点名称">
              <el-input v-model="config.site_name" placeholder="MDCX 媒体库" />
              <div class="hint">客户端中显示的站点名称</div>
            </el-form-item>

            <el-form-item label="播放源标识">
              <el-input v-model="config.play_from" placeholder="MDCX" />
              <div class="hint">vod_play_from 字段值（播放源名称，建议保持默认）</div>
            </el-form-item>

            <el-form-item label="访问令牌">
              <el-input v-model="config.token" placeholder="留空则不鉴权（公开访问）">
                <template #append>
                  <el-button @click="regenerateToken" :loading="regenerating">
                    <el-icon><RefreshRight /></el-icon> 生成
                  </el-button>
                  <el-button @click="copyToken">
                    <el-icon><CopyDocument /></el-icon> 复制
                  </el-button>
                </template>
              </el-input>
              <div class="hint">所有 TVBox/MacCMS 端点通过 ?token=xxx 校验。留空则开放访问（仅在内网或受信环境使用）</div>
            </el-form-item>

            <el-form-item label="分页大小">
              <el-input-number v-model="config.page_size" :min="1" :max="100" :step="5" />
              <div class="hint">列表接口（ac=list / category.html）的每页条目数</div>
            </el-form-item>

            <el-divider>NSFW 内容控制</el-divider>

            <el-form-item label="隐藏 NSFW">
              <el-switch v-model="config.nsfw_hidden" />
              <div class="hint">开启后仅展示已收藏的影片（避免敏感内容暴露给客户端）</div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 接口自检 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Monitor /></el-icon> 接口自检
            </div>
          </template>
          <div class="test-area">
            <el-button type="primary" @click="runTest" :loading="testing">
              <el-icon><VideoPlay /></el-icon> 测试 /tvbox/home.html
            </el-button>
            <el-alert
              v-if="testResult"
              :title="testResult.ok ? '✅ 接口响应正常' : '❌ 接口响应失败'"
              :type="testResult.ok ? 'success' : 'error'"
              :description="testDescription"
              show-icon
              :closable="false"
              style="margin-top: 12px"
            />
          </div>
        </el-card>

        <!-- 端点说明表格 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><List /></el-icon> 端点说明
            </div>
          </template>
          <el-table
            :data="guide?.endpoints || []"
            size="small"
            border
            stripe
          >
            <el-table-column prop="method" label="方法" width="70" />
            <el-table-column prop="path" label="路径" min-width="280" show-overflow-tooltip />
            <el-table-column prop="auth" label="鉴权" width="80" />
            <el-table-column prop="desc" label="说明" min-width="160" />
          </el-table>
        </el-card>
      </el-col>

      <!-- 右侧：接入指南 -->
      <el-col :span="8">
        <el-card shadow="never" class="guide-card">
          <template #header>
            <div class="card-title">
              <el-icon><InfoFilled /></el-icon> 接入指南
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
              <div class="guide-label">访问令牌</div>
              <el-input :model-value="guide.token || '(未设置，公开访问)'" readonly size="small">
                <template #append>
                  <el-button @click="copyText(guide.token)"><el-icon><CopyDocument /></el-icon></el-button>
                </template>
              </el-input>
            </div>

            <el-divider>TVBox 接入</el-divider>

            <div class="guide-block">
              <div class="guide-label">配置文件 URL</div>
              <el-input :model-value="guide.tvbox.config_url" readonly size="small">
                <template #append>
                  <el-button @click="copyText(guide.tvbox.config_url)"><el-icon><CopyDocument /></el-icon></el-button>
                </template>
              </el-input>
            </div>

            <div class="guide-block">
              <div class="guide-label">首页 URL</div>
              <el-input :model-value="guide.tvbox.home_url" readonly size="small">
                <template #append>
                  <el-button @click="copyText(guide.tvbox.home_url)"><el-icon><CopyDocument /></el-icon></el-button>
                </template>
              </el-input>
            </div>

            <el-divider>MacCMS 采集</el-divider>

            <div class="guide-block">
              <div class="guide-label">采集 API</div>
              <el-input :model-value="guide.maccms.api_url" readonly size="small">
                <template #append>
                  <el-button @click="copyText(guide.maccms.api_url)"><el-icon><CopyDocument /></el-icon></el-button>
                </template>
              </el-input>
            </div>

            <div class="guide-block">
              <div class="guide-label">列表接口</div>
              <el-input :model-value="guide.maccms.list_url" readonly size="small">
                <template #append>
                  <el-button @click="copyText(guide.maccms.list_url)"><el-icon><CopyDocument /></el-icon></el-button>
                </template>
              </el-input>
            </div>

            <el-divider>使用说明</el-divider>

            <div class="usage-steps">
              <ol>
                <li>启用 TVBox/MacCMS 开放接口</li>
                <li>设置访问令牌（推荐）或留空（仅内网）</li>
                <li>将上方 TVBox 配置文件 URL 复制到 TVBox 客户端的"配置地址"中</li>
                <li>或将 MacCMS 采集 API 复制到影视 App 的采集源配置中</li>
                <li>客户端会自动加载分类、列表、详情、播放地址</li>
              </ol>
            </div>
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
  Monitor, VideoPlay, InfoFilled, List
} from '@element-plus/icons-vue'
import {
  getTvboxConfig, updateTvboxConfig, regenerateTvboxToken,
  testTvboxEndpoint, getTvboxClientsGuide
} from '@/api'

const loading = ref(false)
const saving = ref(false)
const regenerating = ref(false)
const testing = ref(false)
const testResult = ref(null)
const guide = ref(null)

const config = ref({
  enabled: false,
  token: '',
  page_size: 20,
  nsfw_hidden: true,
  site_name: 'MDCX 媒体库',
  play_from: 'MDCX'
})

const testDescription = computed(() => {
  if (!testResult.value) return ''
  if (testResult.value.ok) {
    return `HTTP ${testResult.value.status_code} · 返回 ${testResult.value.class_count || 0} 个分类`
  }
  return testResult.value.error || `HTTP ${testResult.value.status_code || '?'}`
})

const loadConfig = async () => {
  loading.value = true
  try {
    const data = await getTvboxConfig()
    config.value = { ...config.value, ...data }
  } catch (e) {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

const loadGuide = async () => {
  try {
    guide.value = await getTvboxClientsGuide()
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
    await updateTvboxConfig({
      enabled: config.value.enabled,
      token: config.value.token,
      page_size: config.value.page_size,
      nsfw_hidden: config.value.nsfw_hidden,
      site_name: config.value.site_name,
      play_from: config.value.play_from
    })
    ElMessage.success('TVBox/MacCMS 配置已保存')
    await loadGuide()
  } catch (e) {
    // ignore
  } finally {
    saving.value = false
  }
}

const regenerateToken = async () => {
  regenerating.value = true
  try {
    const data = await regenerateTvboxToken()
    config.value.token = data.token
    ElMessage.success('访问令牌已重新生成')
    await loadGuide()
  } catch (e) {
    // ignore
  } finally {
    regenerating.value = false
  }
}

const copyToken = () => copyText(config.value.token)

const copyText = async (text) => {
  if (!text) {
    ElMessage.warning('内容为空，无法复制')
    return
  }
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
    testResult.value = await testTvboxEndpoint()
  } catch (e) {
    testResult.value = { ok: false, error: e.message || '请求失败' }
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.tvbox-page {
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

.usage-steps {
  font-size: 13px;
  color: #606266;
  line-height: 1.8;
}

.usage-steps ol {
  padding-left: 20px;
  margin: 0;
}

.usage-steps li {
  margin-bottom: 4px;
}
</style>
