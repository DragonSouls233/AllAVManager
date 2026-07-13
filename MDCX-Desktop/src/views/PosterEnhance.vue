<template>
  <div class="page poster-enhance-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Picture /></el-icon>
          海报增强
        </h2>
        <span class="page-subtitle">4K/8K 高清海报下载 + 水印标签(马赛克/无码/中字等)</span>
      </div>
    </div>

    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="24" :sm="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num primary">{{ stats.enhancedCount }}</span>
            <span class="stat-label">已增强海报</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num success">{{ stats.labelCount }}</span>
            <span class="stat-label">支持水印类型</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num warning">{{ stats.positionCount }}</span>
            <span class="stat-label">支持水印位置</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 主体内容 Tabs -->
    <el-tabs v-model="activeTab" class="enhance-tabs">
      <!-- 配置标签页 -->
      <el-tab-pane label="配置" name="config">
        <el-row :gutter="16">
          <!-- 水印标签配置 -->
          <el-col :xs="24" :lg="12">
            <el-card shadow="never" class="config-card" v-loading="loadingConfig">
              <template #header>
                <div class="card-header-title">
                  <el-icon><Collection /></el-icon>
                  水印标签配置
                </div>
              </template>
              <div v-if="labelList.length" class="label-grid">
                <el-tag
                  v-for="item in labelList"
                  :key="item.key"
                  :type="item.type"
                  effect="light"
                  round
                  class="label-tag"
                >
                  <strong>{{ item.key }}</strong>
                  <span class="label-desc">{{ item.label }}</span>
                </el-tag>
              </div>
              <el-empty v-else description="暂无标签" :image-size="60" />
            </el-card>
          </el-col>

          <!-- 水印位置配置 -->
          <el-col :xs="24" :lg="12">
            <el-card shadow="never" class="config-card" v-loading="loadingConfig">
              <template #header>
                <div class="card-header-title">
                  <el-icon><Position /></el-icon>
                  水印位置配置
                </div>
              </template>
              <div v-if="positions.length" class="position-grid">
                <div
                  v-for="pos in positions"
                  :key="pos"
                  class="position-cell"
                  :class="{ active: config.watermark_position === pos }"
                  @click="config.watermark_position = pos"
                >
                  <div class="position-box">
                    <span class="position-dot" :class="posClass(pos)"></span>
                  </div>
                  <span class="position-text">{{ pos }}</span>
                </div>
              </div>
              <el-empty v-else description="暂无位置" :image-size="60" />
            </el-card>
          </el-col>

          <!-- Amazon 高清源配置 -->
          <el-col :span="24">
            <el-card shadow="never" class="config-card" v-loading="loadingConfig">
              <template #header>
                <div class="card-header-title">
                  <el-icon><Setting /></el-icon>
                  Amazon 高清源与水印参数
                </div>
              </template>
              <el-form :model="config" label-width="140px" class="config-form">
                <el-form-item label="启用水印">
                  <el-switch v-model="config.enable_watermark" />
                </el-form-item>
                <el-form-item label="水印透明度">
                  <el-slider
                    v-model="config.watermark_opacity"
                    :min="0"
                    :max="1"
                    :step="0.1"
                    show-stops
                    :format-tooltip="v => Math.round(v * 100) + '%'"
                  />
                </el-form-item>
                <el-form-item label="4K 超分辨率">
                  <el-switch v-model="config.enable_4k_upscale" />
                  <span class="form-hint">开启后从 Amazon 源拉取 4K/8K 高清海报</span>
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="saving" @click="saveConfig">
                    <el-icon><Check /></el-icon> 保存配置
                  </el-button>
                  <el-button @click="resetConfig">恢复默认</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- 操作标签页 -->
      <el-tab-pane label="操作" name="operate">
        <el-row :gutter="16">
          <!-- 单影片增强 -->
          <el-col :xs="24" :lg="12">
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <el-icon><Aim /></el-icon>
                  单影片增强
                </div>
              </template>
              <el-form label-position="top">
                <el-form-item label="影片 ID">
                  <el-input
                    v-model="singleId"
                    placeholder="输入单个影片 ID,如 1024"
                    clearable
                    @keyup.enter="handleSingleEnhance"
                  />
                </el-form-item>
                <el-form-item>
                  <el-button
                    type="primary"
                    :loading="singleLoading"
                    :disabled="!singleId.trim()"
                    @click="handleSingleEnhance"
                  >
                    <el-icon><MagicStick /></el-icon> 立即增强
                  </el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>

          <!-- 批量增强 -->
          <el-col :xs="24" :lg="12">
            <el-card shadow="never" class="config-card">
              <template #header>
                <div class="card-header-title">
                  <el-icon><Files /></el-icon>
                  批量增强
                </div>
              </template>
              <el-form label-position="top">
                <el-form-item label="影片 ID 列表(逗号或换行分隔)">
                  <el-input
                    v-model="movieIdsInput"
                    type="textarea"
                    :rows="3"
                    placeholder="如 1024, 2048, 3072"
                  />
                </el-form-item>
                <el-form-item>
                  <el-button
                    type="primary"
                    :loading="batchLoading"
                    :disabled="!movieIdsInput.trim()"
                    @click="handleBatchEnhance"
                  >
                    <el-icon><Files /></el-icon> 批量提交
                  </el-button>
                  <el-button @click="movieIdsInput = ''">清空</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>

          <!-- 预览区:增强前后对比 -->
          <el-col :span="24" v-if="previewResult">
            <el-card shadow="never" class="config-card preview-card">
              <template #header>
                <div class="card-header-title">
                  <el-icon><View /></el-icon>
                  增强前后对比
                  <el-tag size="small" type="success" effect="plain" style="margin-left: 8px">
                    {{ previewResult.status || '成功' }}
                  </el-tag>
                </div>
              </template>
              <div class="preview-grid">
                <div class="preview-item">
                  <div class="preview-label">原图</div>
                  <el-image
                    v-if="previewResult.original_url"
                    :src="previewResult.original_url"
                    fit="cover"
                    class="preview-image"
                    :preview-src-list="[previewResult.original_url]"
                  >
                    <template #error>
                      <div class="image-fallback">无原图</div>
                    </template>
                    <template #placeholder>
                      <div class="image-fallback">加载中…</div>
                    </template>
                  </el-image>
                  <div v-else class="image-fallback">无原图</div>
                </div>
                <div class="preview-item">
                  <div class="preview-label">增强后</div>
                  <el-image
                    v-if="previewResult.poster_url"
                    :src="previewResult.poster_url"
                    fit="cover"
                    class="preview-image"
                    :preview-src-list="[previewResult.poster_url]"
                  >
                    <template #error>
                      <div class="image-fallback">无增强图</div>
                    </template>
                    <template #placeholder>
                      <div class="image-fallback">加载中…</div>
                    </template>
                  </el-image>
                  <div v-else class="image-fallback">无增强图</div>
                </div>
              </div>
              <div v-if="previewResult.message" class="preview-message">
                <el-alert :title="previewResult.message" type="info" :closable="false" />
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Picture, Collection, Position, Setting, Check, Aim, MagicStick, Files, View
} from '@element-plus/icons-vue'
import {
  enhancePoster, batchEnhancePosters,
  getWatermarkLabels, getWatermarkPositions,
  getPosterEnhanceConfig, updatePosterEnhanceConfig
} from '@/api'

const activeTab = ref('config')
const loadingConfig = ref(false)
const saving = ref(false)
const singleLoading = ref(false)
const batchLoading = ref(false)

const singleId = ref('')
const movieIdsInput = ref('')
const labels = ref({})
const positions = ref([])
const previewResult = ref(null)

const defaultConfig = {
  enable_watermark: true,
  watermark_position: 'bottom-right',
  watermark_opacity: 0.7,
  enable_4k_upscale: false
}
const config = ref({ ...defaultConfig })

// 标签按 key 着色
const LABEL_TYPES = ['primary', 'success', 'warning', 'danger', 'info']
const labelList = computed(() =>
  Object.entries(labels.value).map(([key, label], idx) => ({
    key, label,
    type: LABEL_TYPES[idx % LABEL_TYPES.length]
  }))
)

const stats = computed(() => ({
  enhancedCount: previewResult.value ? 1 : 0,
  labelCount: labelList.value.length,
  positionCount: positions.value.length
}))

function posClass(pos) {
  // dot 位置(top-left / bottom-right ...)
  return pos.replace(/[^a-z-]/g, '')
}

async function loadConfig() {
  loadingConfig.value = true
  try {
    const [labelsRes, positionsRes, configRes] = await Promise.all([
      getWatermarkLabels(),
      getWatermarkPositions(),
      getPosterEnhanceConfig()
    ])
    labels.value = labelsRes.labels || labelsRes || {}
    positions.value = positionsRes.positions || positionsRes || []
    if (configRes) Object.assign(config.value, configRes)
  } catch (e) {
    console.error(e)
  } finally {
    loadingConfig.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    await updatePosterEnhanceConfig(config.value)
    ElMessage.success('配置已保存')
  } catch (e) {
    console.error(e)
  } finally {
    saving.value = false
  }
}

function resetConfig() {
  Object.assign(config.value, defaultConfig)
  ElMessage.info('已恢复默认配置(需点击保存生效)')
}

async function handleSingleEnhance() {
  const id = parseInt(singleId.value.trim())
  if (!id) { ElMessage.warning('请输入有效的影片 ID'); return }
  singleLoading.value = true
  try {
    const res = await enhancePoster({ movie_id: id })
    previewResult.value = res
    ElMessage.success('增强完成')
  } catch (e) {
    console.error(e)
  } finally {
    singleLoading.value = false
  }
}

async function handleBatchEnhance() {
  const ids = movieIdsInput.value
    .split(/[,\n]/)
    .map(s => parseInt(s.trim()))
    .filter(n => !Number.isNaN(n))
  if (!ids.length) { ElMessage.warning('请输入有效的影片 ID'); return }
  batchLoading.value = true
  try {
    const res = await batchEnhancePosters(ids)
    const r = res.results || res
    ElMessage.success(`完成:成功 ${r.success ?? 0},失败 ${r.failed ?? 0},跳过 ${r.skipped ?? 0}`)
    // 后端 /batch-enhance 仅返回统计结果，不返回预览图，故不再设置 previewResult
  } catch (e) {
    console.error(e)
  } finally {
    batchLoading.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.poster-enhance-page {
  gap: var(--gap-md);
}

.enhance-tabs {
  margin-top: var(--space-2);
}

.config-card {
  border-radius: var(--radius-lg) !important;
  border: 1px solid var(--border-color) !important;
  box-shadow: var(--shadow-sm) !important;
  margin-bottom: var(--gap-md);
  height: 100%;
}

.card-header-title {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-weight: 600;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.label-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.label-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
}

.label-tag .label-desc {
  font-weight: 400;
  opacity: 0.85;
}

.position-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--gap-sm);
}

.position-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-sm);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  background: var(--bg-card);
}

.position-cell:hover {
  border-color: var(--primary-light);
  transform: translateY(-2px);
}

.position-cell.active {
  border-color: var(--primary-color);
  background: var(--brand-gradient-soft);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}

.position-box {
  width: 56px;
  height: 40px;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  position: relative;
  background: var(--bg-page);
}

.position-dot {
  position: absolute;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-placeholder);
}

.position-dot.top-left { top: 4px; left: 4px; }
.position-dot.top-right { top: 4px; right: 4px; }
.position-dot.bottom-left { bottom: 4px; left: 4px; }
.position-dot.bottom-right { bottom: 4px; right: 4px; }
.position-dot.center {
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
}
.position-cell.active .position-dot {
  background: var(--primary-color);
}

.position-text {
  font-size: var(--font-size-xs);
  color: var(--text-regular);
}

.config-form .form-hint {
  margin-left: var(--gap-sm);
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.preview-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap-md);
}

.preview-item {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.preview-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  font-weight: 600;
}

.preview-image {
  width: 100%;
  aspect-ratio: 2 / 3;
  border-radius: var(--radius-md);
  background: var(--bg-page);
  overflow: hidden;
}

.image-fallback {
  width: 100%;
  aspect-ratio: 2 / 3;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-page);
  color: var(--text-placeholder);
  font-size: var(--font-size-sm);
  border-radius: var(--radius-md);
}

.preview-message {
  margin-top: var(--gap-md);
}

@media (max-width: 640px) {
  .preview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
