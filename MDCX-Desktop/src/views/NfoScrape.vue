<template>
  <div class="nfo-scrape">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-info">
        <h2>
          <el-icon><Document /></el-icon>
          NFO 免改名半自动刮削
        </h2>
        <p class="subtitle">
          读取已存在的 .nfo 文件（Emby / Jellyfin / Kodi 格式），提取元数据并导入数据库，不重命名视频文件。
        </p>
      </div>
    </div>

    <!-- 步骤 1: 目录选择与扫描 -->
    <el-card class="step-card">
      <template #header>
        <div class="card-header">
          <span class="step-num">1</span>
          <span>选择目录并扫描</span>
        </div>
      </template>

      <el-form label-position="top">
        <el-form-item label="NFO 所在目录">
          <div class="dir-input-row">
            <el-input
              v-model="form.dirPath"
              placeholder="例如 O:\Movies 或 O:\Series\Library"
              clearable
              @keyup.enter="onScan"
            />
            <el-button type="primary" @click="onScan" :loading="scanning">
              <el-icon><Search /></el-icon>
              开始扫描
            </el-button>
          </div>
        </el-form-item>

        <el-form-item>
          <el-checkbox v-model="form.recursive">递归扫描子目录</el-checkbox>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 步骤 2: 扫描结果预览 -->
    <el-card class="step-card" v-if="scanResults.length">
      <template #header>
        <div class="card-header">
          <span class="step-num">2</span>
          <span>扫描结果预览（共 {{ scanResults.length }} 个 NFO 文件）</span>
          <div class="header-actions">
            <el-button size="small" @click="onRescan" :loading="scanning">
              <el-icon><Refresh /></el-icon> 重新扫描
            </el-button>
            <el-button size="small" type="success" @click="onImportAll" :loading="importingAll">
              <el-icon><Upload /></el-icon> 全部导入
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="scanResults" border stripe size="small" max-height="500">
        <el-table-column label="#" type="index" width="50" />
        <el-table-column label="番号" prop="code" width="140">
          <template #default="{ row }">
            <el-tag size="small">{{ row.code || '(无番号)' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" prop="title" min-width="220" show-overflow-tooltip />
        <el-table-column label="NFO 格式" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="formatTagType(row.format)" effect="plain">
              {{ row.format || '未知' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="演员" min-width="180">
          <template #default="{ row }">
            <span v-if="row.actors && row.actors.length">
              {{ row.actors.slice(0, 3).map(a => a.name).join(' / ')
              }}{{ row.actors.length > 3 ? ` 等 ${row.actors.length} 人` : '' }}
            </span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="发行日期" prop="release_date" width="120">
          <template #default="{ row }">{{ row.release_date || '-' }}</template>
        </el-table-column>
        <el-table-column label="NFO 文件路径" prop="nfo_path" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button text size="small" @click="onPreview(row)">
              <el-icon><View /></el-icon> 预览
            </el-button>
            <el-button
              text
              size="small"
              type="success"
              @click="onImportOne(row)"
              :loading="row._importing"
            >
              <el-icon><Upload /></el-icon> 导入
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 空状态 -->
    <el-card class="step-card" v-else-if="scanned && !scanResults.length">
      <el-empty description="未在所选目录中找到 .nfo 文件">
        <el-button type="primary" @click="onRescan">重新扫描</el-button>
      </el-empty>
    </el-card>

    <!-- 预览对话框 -->
    <el-dialog v-model="previewVisible" title="NFO 详情预览" width="720px" top="6vh">
      <div v-if="previewData" class="preview-content">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="番号">{{ previewData.code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="NFO 格式">
            <el-tag size="small" :type="formatTagType(previewData.format)" effect="plain">
              {{ previewData.format || '未知' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="标题" :span="2">{{ previewData.title || '(未命名)' }}</el-descriptions-item>
          <el-descriptions-item label="原标题" :span="2" v-if="previewData.original_title">
            {{ previewData.original_title }}
          </el-descriptions-item>
          <el-descriptions-item label="发行日期">{{ previewData.release_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="评分" v-if="previewData.rating != null">
            {{ previewData.rating }} / 10
          </el-descriptions-item>
          <el-descriptions-item label="制作商" v-if="previewData.studio">{{ previewData.studio }}</el-descriptions-item>
          <el-descriptions-item label="系列" v-if="previewData.series">{{ previewData.series }}</el-descriptions-item>
          <el-descriptions-item label="NFO 路径" :span="2">{{ previewData.nfo_path }}</el-descriptions-item>
          <el-descriptions-item label="视频文件" :span="2" v-if="previewData.video_path">
            {{ previewData.video_path }}
          </el-descriptions-item>
          <el-descriptions-item label="剧情" :span="2" v-if="previewData.plot">
            <div class="plot-text">{{ previewData.plot }}</div>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 演员 -->
        <div v-if="previewData.actors && previewData.actors.length" class="preview-section">
          <h4>演员（{{ previewData.actors.length }} 人）</h4>
          <div class="actor-list">
            <el-tag
              v-for="(a, idx) in previewData.actors"
              :key="idx"
              size="small"
              effect="plain"
              class="actor-tag"
            >
              {{ a.name }}<span v-if="a.role" class="muted"> ({{ a.role }})</span>
            </el-tag>
          </div>
        </div>

        <!-- 标签 -->
        <div v-if="previewData.tags && previewData.tags.length" class="preview-section">
          <h4>标签（{{ previewData.tags.length }} 个）</h4>
          <div class="tag-list">
            <el-tag v-for="(t, idx) in previewData.tags" :key="idx" size="small" class="tag-item">
              {{ t }}
            </el-tag>
          </div>
        </div>

        <!-- 封面/海报 -->
        <div v-if="hasImages(previewData)" class="preview-section">
          <h4>图片资源</h4>
          <div class="image-grid">
            <div v-if="previewData.cover_url" class="image-item">
              <img :src="resolveImageUrl(previewData.cover_url)" alt="封面" @error="onImgError" />
              <div class="image-label">封面</div>
            </div>
            <div v-if="previewData.poster_url" class="image-item">
              <img :src="resolveImageUrl(previewData.poster_url)" alt="海报" @error="onImgError" />
              <div class="image-label">海报</div>
            </div>
            <div v-if="previewData.thumb_url" class="image-item">
              <img :src="resolveImageUrl(previewData.thumb_url)" alt="缩略图" @error="onImgError" />
              <div class="image-label">缩略图</div>
            </div>
            <div v-if="previewData.fanart_url" class="image-item">
              <img :src="resolveImageUrl(previewData.fanart_url)" alt="背景图" @error="onImgError" />
              <div class="image-label">背景图</div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
        <el-button
          type="success"
          @click="onImportFromPreview"
          :loading="importingFromPreview"
        >
          <el-icon><Upload /></el-icon> 导入此 NFO
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入结果汇总 -->
    <el-dialog v-model="summaryVisible" title="导入结果汇总" width="540px">
      <div v-if="importSummary" class="summary-content">
        <el-result
          :icon="importSummary.failed === 0 ? 'success' : 'warning'"
          :title="`成功 ${importSummary.success} / 失败 ${importSummary.failed} / 跳过 ${importSummary.skipped}`"
        />
        <el-divider />
        <div v-if="importSummary.errors && importSummary.errors.length" class="error-list">
          <h4>失败详情</h4>
          <ul>
            <li v-for="(err, idx) in importSummary.errors" :key="idx" class="error-item">
              <span class="error-path">{{ err.path || err.code || '?' }}</span>
              <span class="error-msg">{{ err.error }}</span>
            </li>
          </ul>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="summaryVisible = false">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Document, Search, Refresh, Upload, View
} from '@element-plus/icons-vue'
import { scanNfoDirectory, scrapeNfoFile, previewNfo } from '@/api'
import { getServerBaseUrl, getFileProxyUrl } from '@/utils/media'

// 表单状态
const form = reactive({
  dirPath: '',
  recursive: true,
})

// 扫描状态
const scanning = ref(false)
const scanned = ref(false)
const scanResults = ref([])

// 预览状态
const previewVisible = ref(false)
const previewData = ref(null)
const importingFromPreview = ref(false)

// 导入状态
const importingAll = ref(false)
const summaryVisible = ref(false)
const importSummary = ref(null)

// 扫描目录
const onScan = async () => {
  if (!form.dirPath.trim()) {
    ElMessage.warning('请输入或粘贴 NFO 所在目录路径')
    return
  }
  scanning.value = true
  scanned.value = false
  try {
    const data = await scanNfoDirectory({
      dir_path: form.dirPath.trim(),
      recursive: form.recursive,
    })
    scanResults.value = (data?.items || []).map(it => ({ ...it, _importing: false }))
    scanned.value = true
    ElMessage.success(`扫描完成，共发现 ${scanResults.value.length} 个 NFO 文件`)
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '扫描失败'
    ElMessage.error(`扫描失败: ${msg}`)
  } finally {
    scanning.value = false
  }
}

// 重新扫描
const onRescan = () => onScan()

// 单个预览
const onPreview = async (row) => {
  previewData.value = null
  previewVisible.value = true
  try {
    const data = await previewNfo(row.nfo_path)
    previewData.value = data
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '预览失败'
    ElMessage.error(`预览失败: ${msg}`)
    previewVisible.value = false
  }
}

// 单个导入
const onImportOne = async (row) => {
  row._importing = true
  try {
    const data = await scrapeNfoFile({ nfo_path: row.nfo_path })
    ElMessage.success(`已导入: ${data?.code || row.code || row.nfo_path}`)
    row._imported = true
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '导入失败'
    ElMessage.error(`导入失败: ${msg}`)
  } finally {
    row._importing = false
  }
}

// 全部导入
const onImportAll = async () => {
  if (!scanResults.value.length) return
  try {
    await ElMessageBox.confirm(
      `即将导入 ${scanResults.value.length} 个 NFO 文件的元数据，是否继续？`,
      '确认全部导入',
      { confirmButtonText: '全部导入', cancelButtonText: '取消', type: 'info' }
    )
  } catch {
    return
  }

  importingAll.value = true
  const summary = { success: 0, failed: 0, skipped: 0, errors: [] }

  for (const row of scanResults.value) {
    row._importing = true
    try {
      await scrapeNfoFile({ nfo_path: row.nfo_path })
      summary.success++
      row._imported = true
    } catch (e) {
      summary.failed++
      const msg = e?.response?.data?.detail || e?.message || '未知错误'
      summary.errors.push({ path: row.nfo_path, code: row.code, error: msg })
    } finally {
      row._importing = false
    }
  }

  importSummary.value = summary
  summaryVisible.value = true
  importingAll.value = false
}

// 从预览对话框导入
const onImportFromPreview = async () => {
  if (!previewData.value) return
  importingFromPreview.value = true
  try {
    const data = await scrapeNfoFile({ nfo_path: previewData.value.nfo_path })
    ElMessage.success(`已导入: ${data?.code || previewData.value.code || 'NFO'}`)
    previewVisible.value = false
    // 同步刷新列表中的标记
    const idx = scanResults.value.findIndex(r => r.nfo_path === previewData.value.nfo_path)
    if (idx >= 0) scanResults.value[idx]._imported = true
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '导入失败'
    ElMessage.error(`导入失败: ${msg}`)
  } finally {
    importingFromPreview.value = false
  }
}

// 工具方法
const formatTagType = (format) => {
  if (format === 'emby') return 'primary'
  if (format === 'jellyfin') return 'success'
  if (format === 'kodi') return 'warning'
  return 'info'
}

const hasImages = (data) => {
  return !!(data && (data.cover_url || data.poster_url || data.thumb_url || data.fanart_url))
}

// 解析图片 URL：本地相对路径补全为服务端绝对地址
const resolveImageUrl = (url) => {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  // 本地路径通过 files/proxy 透传
  return getFileProxyUrl(url)
}

const onImgError = (e) => {
  // 图片加载失败时隐藏
  if (e?.target) e.target.style.display = 'none'
}
</script>

<style scoped>
.nfo-scrape {
  padding: 4px 0 20px;
}

.page-header {
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0 0 6px;
  font-size: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.subtitle {
  margin: 0;
  color: var(--text-secondary, #606266);
  font-size: 13px;
  line-height: 1.5;
}

.step-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.step-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--el-color-primary, #409eff);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.header-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.dir-input-row {
  display: flex;
  gap: 8px;
}

.muted {
  color: var(--text-placeholder, #c0c4cc);
}

/* 预览对话框 */
.preview-content {
  max-height: 65vh;
  overflow-y: auto;
}

.preview-section {
  margin-top: 16px;
}

.preview-section h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--text-primary, #303133);
}

.plot-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary, #606266);
}

.actor-list,
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

.image-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.image-item img {
  width: 100%;
  max-height: 200px;
  object-fit: contain;
  border-radius: 6px;
  background: var(--bg-page, #f5f7fa);
}

.image-label {
  font-size: 12px;
  color: var(--text-secondary, #606266);
}

/* 导入汇总 */
.summary-content .error-list {
  max-height: 240px;
  overflow-y: auto;
}

.error-list h4 {
  margin: 8px 0;
  font-size: 13px;
  color: var(--el-color-danger, #f56c6c);
}

.error-list ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.error-item {
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--border-light, #ebeef5);
}

.error-path {
  display: block;
  color: var(--text-primary, #303133);
  word-break: break-all;
}

.error-msg {
  display: block;
  color: var(--el-color-danger, #f56c6c);
  margin-top: 2px;
}
</style>
