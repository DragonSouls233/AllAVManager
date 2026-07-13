<template>
  <div class="strm-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Link /></el-icon>
          STRM 文件生成
        </h2>
        <div class="page-subtitle">为 Emby / Jellyfin / Kodi 生成 STRM 流媒体索引 + NFO 元数据</div>
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
      <!-- 左侧：配置 + 操作 -->
      <el-col :span="16">
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><Setting /></el-icon> STRM 配置
              <el-switch
                v-model="config.enabled"
                active-text="启用"
                inactive-text="禁用"
                style="margin-left: auto"
              />
            </div>
          </template>

          <el-form :model="config" label-width="140px">
            <el-form-item label="输出目录">
              <el-input v-model="config.output_dir" placeholder="data/strm" />
              <div class="hint">STRM 与 NFO 文件的根输出目录（相对路径基于服务器工作目录）</div>
            </el-form-item>

            <el-form-item label="URL 模板">
              <el-input v-model="config.url_template" placeholder="http://192.168.1.10:8420/api/v1/movies/{id}/play/external" />
              <div class="hint">
                STRM 文件内容模板，必须包含 <code>{id}</code> 占位符（影片 ID）
              </div>
            </el-form-item>

            <el-form-item label="目录结构模板">
              <el-switch v-model="config.use_directory_template" />
              <div class="hint">启用后按"片商/年份/番号"分级目录组织，否则全部输出到根目录</div>
            </el-form-item>

            <el-form-item label="生成 NFO">
              <el-switch v-model="config.generate_nfo" />
              <div class="hint">同时生成 NFO 元数据文件，让客户端显示完整信息</div>
            </el-form-item>

            <el-form-item label="覆盖已有文件">
              <el-switch v-model="config.overwrite" />
              <div class="hint">关闭时，已存在的 STRM 文件会被跳过</div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 批量操作 -->
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><MagicStick /></el-icon> 批量生成
            </div>
          </template>

          <el-form label-width="140px">
            <el-form-item label="生成范围">
              <el-radio-group v-model="generateMode">
                <el-radio-button label="all">全部影片</el-radio-button>
                <el-radio-button label="ids">指定影片 ID</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item v-if="generateMode === 'ids'" label="影片 ID 列表">
              <el-input
                v-model="movieIdsInput"
                type="textarea"
                :rows="3"
                placeholder="1, 2, 3 或每行一个 ID"
              />
              <div class="hint">逗号、空格或换行分隔</div>
            </el-form-item>

            <el-form-item label="覆盖配置">
              <el-switch v-model="overwriteOverride" />
              <div class="hint">开启后本次生成强制覆盖（忽略全局 overwrite 配置）</div>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                @click="runGenerate"
                :loading="generating"
                :disabled="!config.enabled"
              >
                <el-icon><VideoPlay /></el-icon> 开始生成
              </el-button>
              <el-button
                type="danger"
                plain
                @click="runCleanup"
                :loading="cleaning"
              >
                <el-icon><Delete /></el-icon> 清理 STRM 目录
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="generateResult"
            :title="resultTitle"
            :type="generateResult.failed > 0 ? 'warning' : 'success'"
            :description="resultDescription"
            show-icon
            :closable="false"
            style="margin-top: 12px"
          />

          <div v-if="generateResult?.errors?.length" class="error-list">
            <div class="error-list-title">失败详情（最多显示前 20 条）：</div>
            <el-scrollbar max-height="200px">
              <div v-for="(e, i) in generateResult.errors.slice(0, 20)" :key="i" class="error-item">
                <el-tag size="small" type="danger">{{ e.code || e.movie_id || '?' }}</el-tag>
                <span>{{ e.error }}</span>
              </div>
            </el-scrollbar>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：统计信息 -->
      <el-col :span="8">
        <el-card shadow="never" class="stats-card">
          <template #header>
            <div class="card-title">
              <el-icon><DataAnalysis /></el-icon> 目录统计
            </div>
          </template>

          <div v-if="stats" class="stats-grid">
            <div class="stat-item">
              <div class="stat-value">{{ stats.total_strm }}</div>
              <div class="stat-label">STRM 文件</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">{{ stats.total_nfo }}</div>
              <div class="stat-label">NFO 文件</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">{{ formatSize(stats.total_size_kb) }}</div>
              <div class="stat-label">总大小</div>
            </div>
          </div>

          <el-divider />

          <div class="output-path">
            <div class="output-label">输出目录</div>
            <el-input
              :model-value="stats?.output_dir || config.output_dir"
              readonly
              size="small"
              type="textarea"
              :rows="2"
            />
          </div>

          <div class="tips">
            <div class="tips-title">
              <el-icon><InfoFilled /></el-icon> 使用提示
            </div>
            <ul>
              <li>STRM 文件可被 Emby/Jellyfin/Kodi 扫描为本地视频</li>
              <li>内容为流媒体 URL，由 MDCX 服务器提供视频流</li>
              <li>建议同时启用 NFO 生成，让客户端展示完整元数据</li>
              <li>清理操作会删除输出目录下所有 .strm 和 .nfo 文件</li>
            </ul>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Link, Setting, Refresh, Check, MagicStick, VideoPlay, Delete,
  DataAnalysis, InfoFilled
} from '@element-plus/icons-vue'
import {
  getStrmConfig, updateStrmConfig, generateStrm, cleanupStrm, getStrmStatistics
} from '@/api'

const loading = ref(false)
const saving = ref(false)
const generating = ref(false)
const cleaning = ref(false)

const config = ref({
  enabled: false,
  output_dir: 'data/strm',
  use_directory_template: true,
  url_template: 'http://localhost:8420/api/v1/movies/{id}/play/external',
  generate_nfo: true,
  overwrite: false
})

const stats = ref(null)
const generateMode = ref('all')
const movieIdsInput = ref('')
const overwriteOverride = ref(false)
const generateResult = ref(null)

const resultTitle = computed(() => {
  if (!generateResult.value) return ''
  const r = generateResult.value
  return `✅ 成功 ${r.success} · ⏭ 跳过 ${r.skipped} · ❌ 失败 ${r.failed} · 共 ${r.total}`
})

const resultDescription = computed(() => {
  if (!generateResult.value) return ''
  const r = generateResult.value
  return `总计 ${r.total} 部影片 · 成功生成 ${r.success} 个 STRM 文件`
})

const formatSize = (kb) => {
  if (!kb || kb <= 0) return '0 B'
  if (kb < 1024) return `${kb} KB`
  if (kb < 1024 * 1024) return `${(kb / 1024).toFixed(2)} MB`
  return `${(kb / 1024 / 1024).toFixed(2)} GB`
}

const parseMovieIds = () => {
  if (!movieIdsInput.value.trim()) return []
  return movieIdsInput.value
    .split(/[\s,，;；\n\r]+/)
    .map(s => s.trim())
    .filter(Boolean)
    .map(s => parseInt(s, 10))
    .filter(n => !isNaN(n) && n > 0)
}

const loadConfig = async () => {
  loading.value = true
  try {
    const data = await getStrmConfig()
    config.value = {
      enabled: data.enabled,
      output_dir: data.output_dir,
      use_directory_template: data.use_directory_template,
      url_template: data.url_template,
      generate_nfo: data.generate_nfo,
      overwrite: data.overwrite
    }
    if (data.statistics) stats.value = data.statistics
  } catch (e) {
    // ignore
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    stats.value = await getStrmStatistics()
  } catch (e) {
    // ignore
  }
}

const loadAll = async () => {
  await Promise.all([loadConfig(), loadStats()])
}

const saveAll = async () => {
  saving.value = true
  try {
    await updateStrmConfig({
      enabled: config.value.enabled,
      output_dir: config.value.output_dir,
      use_directory_template: config.value.use_directory_template,
      url_template: config.value.url_template,
      generate_nfo: config.value.generate_nfo,
      overwrite: config.value.overwrite
    })
    ElMessage.success('STRM 配置已保存')
  } catch (e) {
    // ignore
  } finally {
    saving.value = false
  }
}

const runGenerate = async () => {
  if (!config.value.enabled) {
    ElMessage.warning('请先启用 STRM 生成')
    return
  }

  const payload = {
    overwrite: overwriteOverride.value
  }

  if (generateMode.value === 'ids') {
    const ids = parseMovieIds()
    if (ids.length === 0) {
      ElMessage.warning('请输入有效的影片 ID')
      return
    }
    payload.movie_ids = ids
  } else {
    payload.movie_ids = null
  }

  generating.value = true
  generateResult.value = null
  try {
    const result = await generateStrm(payload)
    generateResult.value = result
    ElMessage.success(`生成完成：成功 ${result.success} / 失败 ${result.failed}`)
    await loadStats()
  } catch (e) {
    // ignore
  } finally {
    generating.value = false
  }
}

const runCleanup = async () => {
  try {
    await ElMessageBox.confirm(
      '此操作将删除 STRM 输出目录下所有 .strm 和 .nfo 文件，是否继续？',
      '确认清理',
      { type: 'warning', confirmButtonText: '清理', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  cleaning.value = true
  try {
    const result = await cleanupStrm()
    ElMessage.success(`已删除 ${result.deleted_strm} 个 STRM + ${result.deleted_nfo} 个 NFO 文件`)
    await loadStats()
  } catch (e) {
    // ignore
  } finally {
    cleaning.value = false
  }
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.strm-page {
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
.stats-card {
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
  line-height: 1.5;
}

.hint code {
  background: #f5f7fa;
  padding: 1px 4px;
  border-radius: 3px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: #e96900;
}

.error-list {
  margin-top: 12px;
  padding: 10px 12px;
  background: #fef0f0;
  border-radius: 4px;
}

.error-list-title {
  font-size: 13px;
  color: #f56c6c;
  margin-bottom: 6px;
  font-weight: 600;
}

.error-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  color: #606266;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.stat-item {
  text-align: center;
  padding: 16px 8px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #409eff;
  line-height: 1.2;
}

.stat-label {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}

.output-path {
  margin-bottom: 16px;
}

.output-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.tips {
  padding: 12px;
  background: #ecf5ff;
  border-radius: 6px;
  border-left: 3px solid #409eff;
}

.tips-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
  font-size: 13px;
}

.tips ul {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: #606266;
  line-height: 1.7;
}

.tips li {
  list-style: disc;
}
</style>
