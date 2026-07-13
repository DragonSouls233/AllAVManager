<template>
  <div class="face-crop-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Avatar /></el-icon>
          AI 人脸裁剪
        </h2>
        <div class="page-subtitle">基于 YuNet ONNX 智能识别面部，自动裁剪海报/封面，避免人脸被切</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button type="primary" @click="initCropper" :loading="initializing">
          <el-icon><Cpu /></el-icon> 初始化裁剪器
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左侧：状态 + 裁剪操作 -->
      <el-col :span="14">
        <!-- 状态卡片 -->
        <el-card shadow="never" class="status-card">
          <template #header>
            <div class="card-title"><el-icon><InfoFilled /></el-icon> 裁剪器状态</div>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="初始化状态">
              <el-tag :type="status.initialized ? 'success' : 'info'" effect="dark" size="small">
                {{ status.initialized ? '已就绪' : '未初始化' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="检测引擎">
              <el-tag v-if="status.backend === 'yunet'" type="success" size="small">YuNet ONNX</el-tag>
              <el-tag v-else-if="status.backend === 'opencv'" type="warning" size="small">OpenCV Cascade</el-tag>
              <el-tag v-else type="info" size="small">未加载</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="功能开关">
              <el-tag :type="config.enabled ? 'success' : 'info'" size="small">
                {{ config.enabled ? '已启用' : '已禁用' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="模型文件">
              <el-tag :type="config.model_exists ? 'success' : 'danger'" size="small">
                {{ config.model_exists ? '已存在' : '未下载' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <el-alert
            v-if="!status.initialized"
            type="warning"
            :closable="false"
            show-icon
            title="裁剪器尚未初始化"
            description="点击右上角“初始化裁剪器”按钮下载/加载 YuNet 模型；如失败将自动回退到 OpenCV Cascade。"
            style="margin-top: 12px"
          />
          <el-alert
            v-else-if="status.backend === 'opencv'"
            type="info"
            :closable="false"
            show-icon
            title="当前使用 OpenCV Cascade 兜底引擎"
            description="YuNet 模型加载失败，已回退到 OpenCV。检测精度较低，建议检查 onnxruntime 安装。"
            style="margin-top: 12px"
          />
        </el-card>

        <!-- 单部裁剪 -->
        <el-card shadow="never" class="op-card">
          <template #header>
            <div class="card-title"><el-icon><Aim /></el-icon> 单部影片裁剪</div>
          </template>
          <el-form :model="singleForm" label-width="100px" inline>
            <el-form-item label="影片 ID">
              <el-input-number v-model="singleForm.movie_id" :min="1" controls-position="right" />
            </el-form-item>
            <el-form-item label="目标">
              <el-select v-model="singleForm.target" style="width: 140px" placeholder="默认用配置">
                <el-option label="默认（按配置）" :value="null" />
                <el-option label="海报 (2:3)" value="poster" />
                <el-option label="封面 (4:3)" value="cover" />
                <el-option label="两者" value="both" />
              </el-select>
            </el-form-item>
            <el-form-item label="源图 URL">
              <el-input
                v-model="singleForm.source_url"
                placeholder="留空则使用影片当前 cover_url"
                style="width: 280px"
              />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                @click="cropSingle"
                :loading="cropping"
                :disabled="!status.initialized && !config.enabled"
              >
                <el-icon><Scissor /></el-icon> 执行裁剪
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="singleResult"
            :type="singleResult.status === 'ok' ? 'success' : 'error'"
            :title="singleResult.status === 'ok' ? `裁剪成功 · 影片 ${singleResult.movie_id}` : '裁剪失败'"
            :description="singleResult.poster_path || singleResult.detail || ''"
            show-icon
            :closable="false"
            style="margin-top: 12px"
          />
        </el-card>

        <!-- 批量裁剪 -->
        <el-card shadow="never" class="op-card">
          <template #header>
            <div class="card-title">
              <el-icon><Histogram /></el-icon> 批量裁剪
              <span class="batch-hint">输入影片 ID 列表（逗号或空格分隔）</span>
            </div>
          </template>
          <el-form label-width="100px">
            <el-form-item label="影片 ID">
              <el-input
                v-model="batchInput"
                type="textarea"
                :rows="3"
                placeholder="例如: 1, 2, 3, 5, 8"
              />
            </el-form-item>
            <el-form-item label="目标">
              <el-radio-group v-model="batchForm.target">
                <el-radio-button :value="null">默认</el-radio-button>
                <el-radio-button value="poster">海报</el-radio-button>
                <el-radio-button value="cover">封面</el-radio-button>
                <el-radio-button value="both">两者</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                @click="cropBatch"
                :loading="batching"
                :disabled="!status.initialized && !config.enabled"
              >
                <el-icon><Histogram /></el-icon> 开始批量裁剪
              </el-button>
              <span class="batch-tip">进度将通过 WebSocket 推送到"实时日志流"页面</span>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="batchResult"
            :type="batchResult.failed === 0 ? 'success' : 'warning'"
            :closable="false"
            show-icon
            :title="`批量完成 · 成功 ${batchResult.success} / 失败 ${batchResult.failed} / 跳过 ${batchResult.skipped} / 总计 ${batchResult.total}`"
            style="margin-top: 12px"
          />
        </el-card>
      </el-col>

      <!-- 右侧：配置 -->
      <el-col :span="10">
        <el-card shadow="never" class="config-card">
          <template #header>
            <div class="card-title">
              <el-icon><Setting /></el-icon> 裁剪配置
              <el-button
                size="small"
                type="primary"
                link
                style="margin-left: auto"
                @click="saveConfig"
                :loading="saving"
              >保存配置</el-button>
            </div>
          </template>

          <el-form :model="config" label-width="120px">
            <el-form-item label="启用">
              <el-switch v-model="config.enabled" />
              <span class="form-tip">关闭后，刮削流程不会自动触发裁剪</span>
            </el-form-item>
            <el-form-item label="裁剪目标">
              <el-radio-group v-model="config.target">
                <el-radio-button value="poster">海报 2:3</el-radio-button>
                <el-radio-button value="cover">封面 4:3</el-radio-button>
                <el-radio-button value="both">两者</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="最小人脸尺寸">
              <el-input-number v-model="config.min_face_size" :min="20" :max="500" />
              <span class="form-tip">px</span>
            </el-form-item>
            <el-form-item label="输出质量">
              <el-slider v-model="config.output_quality" :min="50" :max="100" show-input style="max-width: 320px" />
            </el-form-item>
            <el-form-item label="人脸边距比例">
              <el-slider v-model="config.margin_ratio" :min="0" :max="1" :step="0.05" show-input style="max-width: 320px" />
            </el-form-item>
            <el-form-item label="模型路径">
              <el-input
                v-model="config.model_path"
                placeholder="留空使用默认缓存路径 data/models/face_detection_yunet_fp32.onnx"
              />
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 引擎说明 -->
        <el-card shadow="never" class="info-card">
          <template #header>
            <div class="card-title"><el-icon><InfoFilled /></el-icon> 引擎说明</div>
          </template>
          <ul class="info-list">
            <li>
              <strong>YuNet ONNX（推荐）</strong>
              <p>高精度人脸检测，支持小脸/侧脸。首次使用会自动从 HuggingFace 下载 ~5MB 模型文件。</p>
            </li>
            <li>
              <strong>OpenCV Cascade（兜底）</strong>
              <p>无需下载模型，但精度较低，对小脸/侧脸识别效果差。仅当 onnxruntime 不可用时使用。</p>
            </li>
            <li>
              <strong>旋转回退检测</strong>
              <p>对每张图依次尝试 0°/90°/180°/270° 四个方向，取检测到人脸数最多的方向。</p>
            </li>
            <li>
              <strong>智能构图</strong>
              <p>按目标比例（2:3 或 4:3）裁剪，并将人脸置于画面上 1/3 处，符合海报美学。</p>
            </li>
          </ul>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Avatar, Refresh, Cpu, InfoFilled, Aim, Scissor, Histogram, Setting,
} from '@element-plus/icons-vue'
import {
  getFaceCropConfig, updateFaceCropConfig, initializeFaceCropper,
  cropPoster, batchCrop, getCropperStatus,
} from '@/api'

const loading = ref(false)
const initializing = ref(false)
const cropping = ref(false)
const batching = ref(false)
const saving = ref(false)

const status = reactive({
  initialized: false,
  backend: null,
})

const config = reactive({
  enabled: false,
  model_path: '',
  model_exists: false,
  target: 'poster',
  min_face_size: 80,
  output_quality: 95,
  margin_ratio: 0.4,
})

const singleForm = reactive({
  movie_id: 1,
  source_url: '',
  target: null,
})

const singleResult = ref(null)

const batchInput = ref('')
const batchForm = reactive({ target: null })
const batchResult = ref(null)

const loadAll = async () => {
  loading.value = true
  try {
    const [cfg, st] = await Promise.all([getFaceCropConfig(), getCropperStatus()])
    Object.assign(config, cfg)
    Object.assign(status, st)
  } catch (e) {
    // ignore
  } finally {
    loading.value = false
  }
}

const initCropper = async () => {
  initializing.value = true
  try {
    await initializeFaceCropper()
    ElMessage.success('裁剪器初始化成功')
    await loadAll()
  } catch (e) {
    // ignore
  } finally {
    initializing.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await updateFaceCropConfig({
      enabled: config.enabled,
      model_path: config.model_path || null,
      target: config.target,
      min_face_size: config.min_face_size,
      output_quality: config.output_quality,
      margin_ratio: config.margin_ratio,
    })
    ElMessage.success('配置已保存')
  } catch (e) {
    // ignore
  } finally {
    saving.value = false
  }
}

const cropSingle = async () => {
  cropping.value = true
  singleResult.value = null
  try {
    const data = await cropPoster({
      movie_id: singleForm.movie_id,
      source_url: singleForm.source_url || null,
      target: singleForm.target,
    })
    singleResult.value = { status: 'ok', ...data }
    ElMessage.success('裁剪成功')
  } catch (e) {
    singleResult.value = { status: 'error', detail: e.response?.data?.detail || e.message }
  } finally {
    cropping.value = false
  }
}

const cropBatch = async () => {
  const ids = batchInput.value
    .split(/[,\s]+/)
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n) && n > 0)

  if (ids.length === 0) {
    ElMessage.warning('请输入有效的影片 ID')
    return
  }

  batching.value = true
  batchResult.value = null
  try {
    const data = await batchCrop({
      movie_ids: ids,
      target: batchForm.target,
    })
    batchResult.value = data
    ElMessage.success(`批量完成：成功 ${data.success} / 失败 ${data.failed}`)
  } catch (e) {
    // ignore
  } finally {
    batching.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.face-crop-page {
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

.status-card,
.op-card,
.config-card,
.info-card {
  margin-bottom: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.batch-hint {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}

.form-tip {
  font-size: 11px;
  color: #909399;
  margin-left: 8px;
}

.batch-tip {
  font-size: 11px;
  color: #909399;
  margin-left: 8px;
}

.info-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.info-list li {
  padding: 8px 0;
  border-bottom: 1px dashed #ebeef5;
}

.info-list li:last-child {
  border-bottom: none;
}

.info-list strong {
  color: #409eff;
  display: block;
  margin-bottom: 4px;
}

.info-list p {
  margin: 0;
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
}

:deep(.dark) .info-list li {
  border-bottom-color: #3a3a3a;
}

:deep(.dark) .info-list p {
  color: #b0b0b0;
}
</style>
