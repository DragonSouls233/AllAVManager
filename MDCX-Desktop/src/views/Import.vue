<template>
  <div class="import-page">
    <el-tabs v-model="activeTab" class="import-tabs">
      <!-- ============================================ -->
      <!-- Tab 1: 普通导入(原有三步向导) -->
      <!-- ============================================ -->
      <el-tab-pane label="普通导入" name="import">
    <el-card shadow="never" class="step-card">
      <el-steps :active="currentStep" finish-status="success" align-center>
        <el-step title="扫描目录" description="扫描待导入文件" />
        <el-step title="执行导入" description="匹配入库" />
        <el-step title="导入报告" description="结果统计" />
      </el-steps>
    </el-card>

    <!-- 步骤 1: 扫描 -->
    <el-card v-if="currentStep === 0" shadow="never" class="content-card">
      <template #header>
        <div class="card-title"><el-icon><FolderOpened /></el-icon> 扫描目录</div>
      </template>
      <el-form label-width="160px" :model="scanForm">
        <el-form-item label="目录路径">
          <el-input
            v-model="scanForm.directory"
            type="textarea"
            :rows="3"
            placeholder="每行一个目录路径，例如：&#10;D:\Videos\New&#10;E:\Downloads"
          />
        </el-form-item>
        <el-form-item label="递归扫描">
          <el-switch v-model="scanForm.recursive" />
        </el-form-item>
        <el-form-item label="文件扩展名">
          <el-input v-model="scanForm.extensions" placeholder="mp4,mkv,avi,wmv,flv,mov" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runScan" :loading="scanning">
            <el-icon><Search /></el-icon> 开始扫描
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="scanResult" class="scan-result">
        <el-divider />
        <h4>扫描结果</h4>
        <el-row :gutter="16">
          <el-col :span="8">
            <div class="result-stat">
              <div class="result-num">{{ scanResult.total || 0 }}</div>
              <div class="result-label">总文件数</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="result-stat">
              <div class="result-num success">{{ scanMatched }}</div>
              <div class="result-label">已识别番号</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="result-stat">
              <div class="result-num warning">{{ scanUnmatched }}</div>
              <div class="result-label">未识别</div>
            </div>
          </el-col>
        </el-row>
        <el-button type="primary" @click="goToImport" style="margin-top: 16px">
          下一步：执行导入 <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </el-card>

    <!-- 步骤 2: 导入 -->
    <el-card v-if="currentStep === 1" shadow="never" class="content-card">
      <template #header>
        <div class="card-title"><el-icon><Upload /></el-icon> 执行导入</div>
      </template>
      <el-form label-width="160px" :model="importForm">
        <el-form-item label="立即刮削">
          <el-switch v-model="importForm.scrape" />
          <span class="form-tip">导入后立即触发刮削</span>
        </el-form-item>
        <el-form-item label="刮削来源">
          <el-checkbox-group v-model="importForm.sources" :disabled="!importForm.scrape">
            <el-checkbox value="javbus">JavBus</el-checkbox>
            <el-checkbox value="javdb">JavDB</el-checkbox>
            <el-checkbox value="avmoo">Avmoo</el-checkbox>
            <el-checkbox value="dmm">DMM</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="跳过已存在">
          <el-switch v-model="importForm.skip_existing" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runImportAction" :loading="importing">
            <el-icon><Upload /></el-icon> 开始导入
          </el-button>
          <el-button @click="currentStep = 0">上一步</el-button>
        </el-form-item>
      </el-form>

      <div v-if="currentJob" class="job-progress">
        <el-divider />
        <h4>导入进度</h4>
        <el-progress :percentage="jobProgress" :status="jobStatus" />
        <div class="job-info">
          <span>状态：{{ currentJob.status }}</span>
          <span v-if="currentJob.success">已导入 {{ currentJob.success }}</span>
          <span v-if="currentJob.skipped">已跳过 {{ currentJob.skipped }}</span>
          <span v-if="currentJob.failed">失败 {{ currentJob.failed }}</span>
        </div>
      </div>
    </el-card>

    <!-- 步骤 3: 报告 -->
    <el-card v-if="currentStep === 2" shadow="never" class="content-card">
      <template #header>
        <div class="card-title"><el-icon><Document /></el-icon> 导入报告</div>
      </template>
      <div v-if="report" class="report">
        <el-row :gutter="16">
          <el-col :span="6">
            <div class="result-stat">
              <div class="result-num">{{ report.total || 0 }}</div>
              <div class="result-label">总数</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="result-stat">
              <div class="result-num success">{{ report.imported || 0 }}</div>
              <div class="result-label">导入成功</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="result-stat">
              <div class="result-num info">{{ report.skipped || 0 }}</div>
              <div class="result-label">已跳过</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="result-stat">
              <div class="result-num danger">{{ report.failed || 0 }}</div>
              <div class="result-label">导入失败</div>
            </div>
          </el-col>
        </el-row>
        <el-divider />
        <h4>历史记录</h4>
        <el-table :data="history" v-loading="loadingHistory" stripe size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="started_at" label="开始时间" width="160" />
          <el-table-column prop="total" label="总数" width="80" />
          <el-table-column prop="imported" label="成功" width="80" />
          <el-table-column prop="failed" label="失败" width="80" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'warning'" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button size="small" type="danger" plain @click="deleteRecord(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-button type="primary" @click="restart" style="margin-top: 16px">重新开始</el-button>
    </el-card>
      </el-tab-pane>

      <!-- ============================================ -->
      <!-- Tab 2: 智能重命名(mnamer) -->
      <!-- ============================================ -->
      <el-tab-pane label="智能重命名" name="mnamer">
        <el-card shadow="never" class="content-card">
          <template #header>
            <div class="card-title">
              <el-icon><MagicStick /></el-icon> mnamer 智能重命名
              <el-tag v-if="mnamerHealth.available" type="success" size="small" style="margin-left: 8px">
                v{{ mnamerHealth.version }}
              </el-tag>
              <el-tag v-else type="danger" size="small" style="margin-left: 8px">不可用</el-tag>
            </div>
          </template>

          <el-form label-width="120px" :model="mnamerForm">
            <el-form-item label="文件路径">
              <el-input
                v-model="mnamerForm.filePath"
                placeholder="输入视频文件完整路径，例如：D:\Videos\The.Matrix.1999.1080p.mkv"
                clearable
              />
            </el-form-item>
            <el-form-item label="候选数量">
              <el-input-number v-model="mnamerForm.hits" :min="1" :max="20" />
              <span class="form-tip">留空则用配置默认值</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="queryCandidates" :loading="mnamerLoading">
                <el-icon><Search /></el-icon> 查询候选
              </el-button>
              <el-button @click="loadMnamerConfig">配置</el-button>
            </el-form-item>
          </el-form>

          <!-- guessit 解析结果 -->
          <div v-if="mnamerResult?.parsed && Object.keys(mnamerResult.parsed).length" class="parsed-section">
            <el-divider />
            <h4>本地解析（guessit）</h4>
            <el-descriptions :column="3" border size="small">
              <el-descriptions-item
                v-for="(val, key) in mnamerResult.parsed"
                :key="key"
                :label="String(key)"
              >
                {{ val }}
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <!-- 候选列表 -->
          <div v-if="mnamerResult?.candidates?.length" class="candidates-section">
            <el-divider />
            <h4>远端候选（共 {{ mnamerResult.count }} 个）</h4>
            <el-row :gutter="12">
              <el-col
                v-for="(cand, idx) in mnamerResult.candidates"
                :key="idx"
                :span="12"
                style="margin-bottom: 12px"
              >
                <el-card
                  shadow="hover"
                  :class="['candidate-card', { selected: mnamerForm.selectedIndex === idx }]"
                  @click="selectCandidate(idx)"
                >
                  <div class="candidate-header">
                    <el-tag :type="mnamerForm.selectedIndex === idx ? 'primary' : 'info'" size="small">
                      #{{ idx }}
                    </el-tag>
                    <span class="candidate-name">{{ cand.display || cand.name || '未知' }}</span>
                  </div>
                  <div class="candidate-meta">
                    <span v-if="cand.year">🎬 {{ cand.year }}</span>
                    <span v-if="cand.id_imdb">⭐ IMDB: {{ cand.id_imdb }}</span>
                    <span v-if="cand.id_tmdb">🎬 TMDB: {{ cand.id_tmdb }}</span>
                  </div>
                </el-card>
              </el-col>
            </el-row>
          </div>

          <!-- 错误提示 -->
          <el-alert
            v-if="mnamerResult?.error"
            :title="mnamerResult.error"
            type="warning"
            show-icon
            :closable="false"
            style="margin-top: 12px"
          />

          <!-- 预览目标路径 -->
          <div v-if="mnamerTarget" class="target-section">
            <el-divider />
            <h4>目标路径预览</h4>
            <el-alert
              :title="mnamerTarget.target_path"
              type="info"
              show-icon
              :closable="false"
            />
          </div>

          <!-- 执行重命名 -->
          <div v-if="mnamerForm.selectedIndex !== null" style="margin-top: 16px">
            <el-button
              type="warning"
              @click="previewTarget"
              :loading="previewLoading"
              :disabled="!mnamerResult?.candidates?.length"
            >
              预览目标路径
            </el-button>
            <el-button
              type="danger"
              @click="confirmRename"
              :loading="renameLoading"
              :disabled="!mnamerResult?.candidates?.length"
            >
              <el-icon><Check /></el-icon> 执行重命名
            </el-button>
          </div>

          <!-- 重命名结果 -->
          <el-alert
            v-if="renameResult"
            :title="`重命名成功：${renameResult.original_path} → ${renameResult.final_path}`"
            type="success"
            show-icon
            :closable="false"
            style="margin-top: 12px"
          />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- mnamer 配置对话框 -->
    <el-dialog
      v-model="mnamerConfigVisible"
      title="mnamer 智能重命名配置"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form
        v-loading="mnamerConfigLoading"
        :model="mnamerConfigForm"
        label-width="140px"
      >
        <el-form-item label="启用 mnamer">
          <el-switch v-model="mnamerConfigForm.enabled" />
          <span class="form-tip">开启后远程查询 OMDB/TMDB/TVDB</span>
        </el-form-item>

        <el-divider content-position="left">API Keys(留空不修改)</el-divider>

        <el-form-item label="OMDB API Key">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input
              v-model="mnamerConfigForm.omdb_api_key"
              placeholder="输入新 Key 或留空保持不变"
              show-password
              style="flex: 1"
            />
            <el-button
              v-if="mnamerKeyFlags.has_omdb"
              type="danger"
              plain
              size="small"
              @click="clearMnamerKey('omdb_api_key')"
            >
              清除
            </el-button>
          </div>
          <el-tag v-if="mnamerKeyFlags.has_omdb" type="success" size="small" style="margin-top: 4px">
            已配置
          </el-tag>
        </el-form-item>

        <el-form-item label="TMDB API Key">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input
              v-model="mnamerConfigForm.tmdb_api_key"
              placeholder="输入新 Key 或留空保持不变"
              show-password
              style="flex: 1"
            />
            <el-button
              v-if="mnamerKeyFlags.has_tmdb"
              type="danger"
              plain
              size="small"
              @click="clearMnamerKey('tmdb_api_key')"
            >
              清除
            </el-button>
          </div>
          <el-tag v-if="mnamerKeyFlags.has_tmdb" type="success" size="small" style="margin-top: 4px">
            已配置
          </el-tag>
        </el-form-item>

        <el-form-item label="TVDB API Key">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input
              v-model="mnamerConfigForm.tvdb_api_key"
              placeholder="输入新 Key 或留空保持不变"
              show-password
              style="flex: 1"
            />
            <el-button
              v-if="mnamerKeyFlags.has_tvdb"
              type="danger"
              plain
              size="small"
              @click="clearMnamerKey('tvdb_api_key')"
            >
              清除
            </el-button>
          </div>
          <el-tag v-if="mnamerKeyFlags.has_tvdb" type="success" size="small" style="margin-top: 4px">
            已配置
          </el-tag>
        </el-form-item>

        <el-divider content-position="left">查询参数</el-divider>

        <el-form-item label="默认候选数量">
          <el-input-number v-model="mnamerConfigForm.hits" :min="1" :max="20" />
          <span class="form-tip">每次查询返回的候选数(1-20)</span>
        </el-form-item>

        <el-form-item label="移动而非复制">
          <el-switch v-model="mnamerConfigForm.prefer_move" />
          <span class="form-tip">开启=移动文件,关闭=复制文件</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="mnamerConfigVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMnamerConfig" :loading="mnamerConfigSaving">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpened, Search, Upload, ArrowRight, Document, MagicStick, Check } from '@element-plus/icons-vue'
import {
  scanImportDirectory, runImport, getImportStatus, getImportReport,
  getImportHistory, deleteImportRecord,
  getMnamerHealth, getMnamerCandidates, previewMnamerTarget, executeMnamerRename,
  getMnamerConfig, updateMnamerConfig
} from '@/api'

// ============================================
// Tab 状态
// ============================================
const activeTab = ref('import')

// ============================================
// 普通导入(原有逻辑)
// ============================================
const currentStep = ref(0)
const scanning = ref(false)
const importing = ref(false)
const loadingHistory = ref(false)
const scanResult = ref(null)
const currentJob = ref(null)
const report = ref(null)
const history = ref([])
let pollTimer = null

const scanForm = ref({
  directory: '',
  recursive: true,
  extensions: 'mp4,mkv,avi,wmv,flv,mov'
})

const importForm = ref({
  scrape: true,
  sources: ['javbus', 'javdb', 'avmoo'],
  skip_existing: true
})

// 已识别番号数：统计 directories 中 detected_number 非空的目录
const scanMatched = computed(() => {
  if (!scanResult.value?.directories) return 0
  return scanResult.value.directories.filter(d => d.detected_number).length
})

// 未识别数：统计 directories 中 detected_number 为空的目录
const scanUnmatched = computed(() => {
  if (!scanResult.value?.directories) return 0
  return scanResult.value.directories.filter(d => !d.detected_number).length
})

const jobStatus = computed(() => {
  if (!currentJob.value) return ''
  if (currentJob.value.status === 'success') return 'success'
  if (currentJob.value.status === 'failed') return 'exception'
  return ''
})

// 导入进度百分比：基于 processed/total 计算（后端无 progress 字段）
const jobProgress = computed(() => {
  if (!currentJob.value || !currentJob.value.total) return 0
  return Math.min(100, Math.round((currentJob.value.processed / currentJob.value.total) * 100))
})

const runScan = async () => {
  if (!scanForm.value.directory.trim()) {
    ElMessage.warning('请输入目录路径')
    return
  }
  scanning.value = true
  try {
    const directories = scanForm.value.directory.split('\n').map(s => s.trim()).filter(Boolean)
    const res = await scanImportDirectory({
      directories,
      recursive: scanForm.value.recursive,
      extensions: scanForm.value.extensions.split(',').map(s => s.trim()).filter(Boolean)
    })
    scanResult.value = res
    ElMessage.success(`扫描完成：发现 ${res.total} 个目录，${scanMatched.value} 个已识别番号`)
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '扫描失败'
    ElMessage.error('扫描失败: ' + msg)
    console.error('Scan error:', e)
  }
  finally { scanning.value = false }
}

const goToImport = () => { currentStep.value = 1 }

const runImportAction = async () => {
  importing.value = true
  try {
    // 优先使用扫描结果中的子目录（精确），否则回退到用户输入的目录
    let directories
    if (scanResult.value?.directories?.length) {
      directories = scanResult.value.directories.map(d => d.path)
    } else {
      directories = scanForm.value.directory.split('\n').map(s => s.trim()).filter(Boolean)
    }
    if (!directories.length) {
      ElMessage.warning('没有可导入的目录，请先扫描')
      return
    }
    const res = await runImport({
      directories,
      scrape: importForm.value.scrape,
      sources: importForm.value.sources,
      skip_existing: importForm.value.skip_existing
    })
    currentJob.value = res
    ElMessage.success('导入任务已启动，job_id=' + (res.job_id || res.id))
    pollJob(res.job_id || res.id)
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '导入失败'
    ElMessage.error('导入失败: ' + msg)
    console.error('Import error:', e)
  }
  finally { importing.value = false }
}

const pollJob = (jobId) => {
  if (!jobId) return
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const status = await getImportStatus(jobId)
      currentJob.value = status
      if (['success', 'failed', 'completed'].includes(status.status)) {
        clearInterval(pollTimer)
        pollTimer = null
        const r = await getImportReport(jobId)
        report.value = r
        currentStep.value = 2
        loadHistory()
      }
    } catch (e) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 2000)
}

const loadHistory = async () => {
  loadingHistory.value = true
  try {
    const res = await getImportHistory()
    history.value = res.items || res || []
  } catch (e) { console.error(e) }
  finally { loadingHistory.value = false }
}

const deleteRecord = (row) => {
  ElMessageBox.confirm(`确认删除该记录？`, '提示', { type: 'warning' })
    .then(async () => {
      try {
        await deleteImportRecord(row.id)
        ElMessage.success('已删除')
        loadHistory()
      } catch (e) { console.error(e) }
    }).catch(() => {})
}

const restart = () => {
  currentStep.value = 0
  scanResult.value = null
  currentJob.value = null
  report.value = null
}

// ============================================
// 智能重命名(mnamer)
// ============================================
const mnamerLoading = ref(false)
const previewLoading = ref(false)
const renameLoading = ref(false)
const mnamerHealth = ref({ available: false, version: '' })
const mnamerResult = ref(null)
const mnamerTarget = ref(null)
const renameResult = ref(null)

const mnamerForm = ref({
  filePath: '',
  hits: 5,
  selectedIndex: null
})

const loadMnamerHealth = async () => {
  try {
    const res = await getMnamerHealth()
    mnamerHealth.value = res
  } catch (e) {
    console.error('mnamer health check failed', e)
  }
}

const queryCandidates = async () => {
  if (!mnamerForm.value.filePath.trim()) {
    ElMessage.warning('请输入文件路径')
    return
  }
  mnamerLoading.value = true
  mnamerResult.value = null
  mnamerTarget.value = null
  renameResult.value = null
  mnamerForm.value.selectedIndex = null
  try {
    const res = await getMnamerCandidates({
      file_path: mnamerForm.value.filePath,
      hits: mnamerForm.value.hits
    })
    mnamerResult.value = res
    if (res.candidates?.length) {
      ElMessage.success(`找到 ${res.count} 个候选`)
    } else {
      ElMessage.info('无候选结果（可能缺少 API Key，仅本地解析可用）')
    }
  } catch (e) {
    console.error('mnamer query failed', e)
  } finally {
    mnamerLoading.value = false
  }
}

const selectCandidate = (idx) => {
  mnamerForm.value.selectedIndex = idx
  mnamerTarget.value = null
}

const previewTarget = async () => {
  if (mnamerForm.value.selectedIndex === null) {
    ElMessage.warning('请先选择一个候选')
    return
  }
  previewLoading.value = true
  mnamerTarget.value = null
  try {
    const res = await previewMnamerTarget({
      file_path: mnamerForm.value.filePath,
      match_index: mnamerForm.value.selectedIndex
    })
    mnamerTarget.value = res
  } catch (e) {
    console.error('preview target failed', e)
  } finally {
    previewLoading.value = false
  }
}

const confirmRename = async () => {
  if (mnamerForm.value.selectedIndex === null) {
    ElMessage.warning('请先选择一个候选')
    return
  }
  try {
    await ElMessageBox.confirm(
      '确认执行重命名？此操作会移动文件到新路径。',
      '确认重命名',
      { type: 'warning' }
    )
  } catch {
    return
  }
  renameLoading.value = true
  renameResult.value = null
  try {
    const res = await executeMnamerRename({
      file_path: mnamerForm.value.filePath,
      match_index: mnamerForm.value.selectedIndex
    })
    renameResult.value = res
    ElMessage.success('重命名成功')
  } catch (e) {
    console.error('rename failed', e)
  } finally {
    renameLoading.value = false
  }
}

// ============================================
// mnamer 配置对话框
// ============================================
const mnamerConfigVisible = ref(false)
const mnamerConfigLoading = ref(false)
const mnamerConfigSaving = ref(false)
const mnamerConfigForm = ref({
  enabled: false,
  omdb_api_key: '',
  tmdb_api_key: '',
  tvdb_api_key: '',
  hits: 5,
  prefer_move: true,
})
// 标记 API Key 是否已配置(后端返回掩码 *** 表示已配置)
const mnamerKeyFlags = ref({ has_omdb: false, has_tmdb: false, has_tvdb: false })

const loadMnamerConfig = async () => {
  mnamerConfigVisible.value = true
  mnamerConfigLoading.value = true
  try {
    const res = await getMnamerConfig()
    mnamerConfigForm.value = {
      enabled: !!res.enabled,
      // 后端返回 *** 表示已配置,前端不回显实际 key,留空让用户重新输入
      omdb_api_key: res.omdb_api_key && res.omdb_api_key !== '****' ? res.omdb_api_key : '',
      tmdb_api_key: res.tmdb_api_key && res.tmdb_api_key !== '****' ? res.tmdb_api_key : '',
      tvdb_api_key: res.tvdb_api_key && res.tvdb_api_key !== '****' ? res.tvdb_api_key : '',
      hits: res.hits || 5,
      prefer_move: res.prefer_move !== false,
    }
    mnamerKeyFlags.value = {
      has_omdb: !!res.has_omdb,
      has_tmdb: !!res.has_tmdb,
      has_tvdb: !!res.has_tvdb,
    }
  } catch (e) {
    ElMessage.error('加载 mnamer 配置失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    mnamerConfigLoading.value = false
  }
}

const saveMnamerConfig = async () => {
  mnamerConfigSaving.value = true
  try {
    // 仅在用户输入了新值时才提交 key 字段(避免把空字符串当作清除)
    const payload = {
      enabled: mnamerConfigForm.value.enabled,
      hits: mnamerConfigForm.value.hits,
      prefer_move: mnamerConfigForm.value.prefer_move,
    }
    if (mnamerConfigForm.value.omdb_api_key) payload.omdb_api_key = mnamerConfigForm.value.omdb_api_key
    if (mnamerConfigForm.value.tmdb_api_key) payload.tmdb_api_key = mnamerConfigForm.value.tmdb_api_key
    if (mnamerConfigForm.value.tvdb_api_key) payload.tvdb_api_key = mnamerConfigForm.value.tvdb_api_key
    await updateMnamerConfig(payload)
    ElMessage.success('mnamer 配置已保存')
    mnamerConfigVisible.value = false
    // 重新检查健康状态(启用/禁用可能改变可用性)
    await loadMnamerHealth()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    mnamerConfigSaving.value = false
  }
}

const clearMnamerKey = async (keyName) => {
  try {
    await ElMessageBox.confirm(`确定清除 ${keyName.toUpperCase()} API Key 吗？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    // 提交空字符串清除 key(后端约定空字符串表示清除)
    await updateMnamerConfig({ [keyName]: '' })
    ElMessage.success(`${keyName.toUpperCase()} API Key 已清除`)
    await loadMnamerConfig()
  } catch (e) {
    ElMessage.error('清除失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  loadHistory()
  loadMnamerHealth()
})
</script>

<style scoped>
.import-page { display: flex; flex-direction: column; gap: 16px; }
.import-tabs { border-radius: 10px; }
.step-card, .content-card { border-radius: 10px; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; color: #303133; }
.form-tip { color: #909399; font-size: 12px; margin-left: 8px; }
.scan-result h4, .report h4 { color: #303133; margin: 12px 0; }
.result-stat { text-align: center; padding: 16px; background: #f5f7fa; border-radius: 8px; }
.result-num { font-size: 24px; font-weight: 700; color: #303133; }
.result-num.success { color: #67c23a; }
.result-num.warning { color: #e6a23c; }
.result-num.danger { color: #f56c6c; }
.result-num.info { color: #909399; }
.result-label { color: #909399; font-size: 12px; margin-top: 4px; }
.job-progress { margin-top: 16px; }
.job-info { display: flex; gap: 16px; margin-top: 10px; color: #606266; font-size: 13px; }

/* mnamer 智能重命名样式 */
.parsed-section h4, .candidates-section h4, .target-section h4 { color: #303133; margin: 12px 0; }
.candidate-card { cursor: pointer; transition: border-color 0.2s; }
.candidate-card.selected { border-color: #409eff; background: #ecf5ff; }
.candidate-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.candidate-name { font-weight: 600; color: #303133; font-size: 14px; }
.candidate-meta { display: flex; flex-wrap: wrap; gap: 12px; color: #606266; font-size: 12px; }
</style>
