<template>
  <div class="patch">
    <!-- 步骤条 -->
    <el-card shadow="never" class="step-card">
      <el-steps :active="currentStep" finish-status="success" align-center>
        <el-step title="检测缺失" description="扫描缺失字段/图片" />
        <el-step title="执行补刮" description="重新刮削缺失数据" />
        <el-step title="查看报告" description="补刮结果统计" />
      </el-steps>
    </el-card>

    <!-- 步骤 1: 检测 -->
    <el-card v-if="currentStep === 0" shadow="never" class="content-card">
      <template #header>
        <div class="card-title"><el-icon><Search /></el-icon> 检测缺失字段</div>
      </template>
      <el-form label-width="160px" :model="detectForm">
        <el-form-item label="检测范围">
          <el-radio-group v-model="detectForm.scope">
            <el-radio value="all">全部影片</el-radio>
            <el-radio value="incomplete">仅未刮削完整</el-radio>
            <el-radio value="no_cover">缺封面</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="检测字段">
          <div style="margin-bottom:6px">
            <el-checkbox :indeterminate="isAllSelectedIndeterminate" v-model="isAllSelected" @change="handleSelectAll">
              全选/取消
            </el-checkbox>
            <el-tag size="small" type="info" style="margin-left:8px">
              {{ detectForm.fields.length }} / {{ allFieldOptions.length }}
            </el-tag>
          </div>
          <el-checkbox-group v-model="detectForm.fields">
            <el-checkbox v-for="opt in fieldGroups.critical" :key="opt.value" :value="opt.value" border size="small">
              <span style="color:#f56c6c;font-weight:500">{{ opt.label }}</span>
            </el-checkbox>
            <br />
            <el-checkbox v-for="opt in fieldGroups.metadata" :key="opt.value" :value="opt.value" border size="small">
              {{ opt.label }}
            </el-checkbox>
            <br />
            <el-checkbox v-for="opt in fieldGroups.images" :key="opt.value" :value="opt.value" border size="small">
              <span style="color:#409eff">{{ opt.label }}</span>
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="目录范围">
          <el-select
            v-model="detectDirs"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="留空则检测全部影片"
            style="width: 100%"
          >
            <el-option v-for="d in mediaDirOptions" :key="d" :label="d" :value="d" />
          </el-select>
          <span class="hint">可限定到某个演员/番号文件夹，针对性检测缺失</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runDetect" :loading="detecting">
            <el-icon><Search /></el-icon> 开始检测
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="detectResult" class="detect-result">
        <el-divider />
        <h4>检测结果</h4>
        <el-row :gutter="16">
          <el-col :span="8">
            <div class="result-stat">
              <div class="result-num warning">{{ detectResult.items?.length || 0 }}</div>
              <div class="result-label">缺失数据影片</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="result-stat">
              <div class="result-num">{{ detectResult.total || 0 }}</div>
              <div class="result-label">总影片数</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="result-stat">
              <div class="result-num info">{{ detectPercent }}%</div>
              <div class="result-label">缺失比例</div>
            </div>
          </el-col>
        </el-row>
        <el-button type="primary" @click="goToRun" style="margin-top: 16px">
          下一步：执行补刮 <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </el-card>

    <!-- 步骤 2: 执行 -->
    <el-card v-if="currentStep === 1" shadow="never" class="content-card">
      <template #header>
        <div class="card-title"><el-icon><MagicStick /></el-icon> 执行补刮</div>
      </template>
      <el-form label-width="160px" :model="runForm">
        <el-form-item label="补刮模式">
          <el-radio-group v-model="runForm.mode">
            <el-radio value="all">全部影片</el-radio>
            <el-radio value="directory">指定目录</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目标目录" v-if="runForm.mode === 'directory'">
          <el-select
            v-model="runDirs"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="选择要补刮的目录"
            style="width: 100%"
          >
            <el-option v-for="d in mediaDirOptions" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="补刮类型">
          <el-radio-group v-model="runForm.patch_type">
            <el-radio value="smart">智能</el-radio>
            <el-radio value="images_only">仅图片</el-radio>
            <el-radio value="metadata_only">仅元数据</el-radio>
            <el-radio value="full">完整</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="补刮来源">
          <el-checkbox-group v-model="runForm.sources">
            <el-checkbox value="javbus">JavBus</el-checkbox>
            <el-checkbox value="javdb">JavDB</el-checkbox>
            <el-checkbox value="avmoo">Avmoo</el-checkbox>
            <el-checkbox value="dmm">DMM</el-checkbox>
            <el-checkbox value="missav">MissAV</el-checkbox>
            <el-checkbox value="javlibrary">JavLibrary</el-checkbox>
          </el-checkbox-group>
          <span class="hint">指定优先使用的刮削站点（预览图/封面来自这些站点）</span>
        </el-form-item>
        <el-form-item label="仅补刮缺失">
          <el-switch v-model="runForm.only_missing" />
          <span class="hint">开启后跳过字段已完整的影片</span>
        </el-form-item>
        <el-form-item label="跳过近期刮削">
          <el-switch v-model="runForm.skip_recent" />
          <span class="hint">跳过最近 {{ runForm.skip_recent_days }} 天内已刮削的影片</span>
        </el-form-item>
        <el-form-item label="近期天数" v-if="runForm.skip_recent">
          <el-input-number v-model="runForm.skip_recent_days" :min="0" :max="365" />
          <span class="hint">设为 0 表示不跳过</span>
        </el-form-item>
        <el-form-item label="跳过已审核">
          <el-switch v-model="runForm.skip_verified" />
          <span class="hint">跳过状态为"已审核"的影片</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runPatchAction" :loading="running">
            <el-icon><MagicStick /></el-icon> 开始补刮
          </el-button>
          <el-button @click="currentStep = 0">上一步</el-button>
        </el-form-item>
      </el-form>

      <div v-if="currentJob" class="job-progress">
        <el-divider />
        <h4>补刮进度</h4>
        <el-progress :percentage="currentJob.progress || 0" :status="jobStatus" />
        <div class="job-info">
          <span>状态：{{ jobStatusText }}</span>
          <span v-if="currentJob.current_code">当前：{{ currentJob.current_code }}</span>
          <span>待补：{{ currentJob.total_to_patch ?? 0 }}</span>
          <span>已处理：{{ currentJob.total_patched ?? 0 }}</span>
          <span>成功：{{ currentJob.total_success ?? 0 }}</span>
          <span>失败：{{ currentJob.total_failed ?? 0 }}</span>
          <span v-if="currentJob.total_detected">检测：{{ currentJob.total_detected }}</span>
          <span v-if="currentJob.total_skipped">跳过：{{ currentJob.total_skipped }}</span>
        </div>
      </div>
    </el-card>

    <!-- 步骤 3: 报告 -->
    <el-card v-if="currentStep === 2" shadow="never" class="content-card">
      <template #header>
        <div class="card-title"><el-icon><Document /></el-icon> 补刮报告</div>
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
              <div class="result-num success">{{ report.success || 0 }}</div>
              <div class="result-label">成功</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="result-stat">
              <div class="result-num danger">{{ report.failed || 0 }}</div>
              <div class="result-label">失败</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="result-stat">
              <div class="result-num info">{{ report.skipped || 0 }}</div>
              <div class="result-label">跳过</div>
            </div>
          </el-col>
        </el-row>
        <el-divider />
        <h4>历史记录</h4>
        <el-table :data="history" v-loading="loadingHistory" stripe size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="started_at" label="开始时间" width="160" />
          <el-table-column prop="total" label="总数" width="80" />
          <el-table-column prop="success" label="成功" width="80" />
          <el-table-column prop="failed" label="失败" width="80" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'warning'" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-button type="primary" @click="restart" style="margin-top: 16px">
        重新开始
      </el-button>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, MagicStick, ArrowRight, Document } from '@element-plus/icons-vue'
import { detectMissing, runPatch, getPatchStatus, getPatchReport, getPatchHistory, getConfig } from '@/api'

const currentStep = ref(0)
const detecting = ref(false)
const running = ref(false)
const detectResult = ref(null)
const currentJob = ref(null)
const report = ref(null)
const history = ref([])
const loadingHistory = ref(false)
let pollTimer = null

// 媒体目录（用于按目录范围检测/补刮）
const mediaDirOptions = ref([])
const detectDirs = ref([])
const runDirs = ref([])

const detectForm = ref({
  scope: 'incomplete',
  fields: [
    'title', 'plot', 'actors', 'genre', 'release_date', 'studio', 'maker',
    'series', 'director', 'tag', 'duration', 'rating', 'title_jp', 'plot_short', 'trailer_url',
    'cover', 'poster', 'fanart', 'thumb', 'extrafanart', 'actors_image'
  ]
})

// fieldGroups：所有可检测字段，分三组
const fieldGroups = {
  critical: [
    { value: 'title', label: '❌标题' },
    { value: 'release_date', label: '❌发行日期' },
    { value: 'poster', label: '❌海报' },
    { value: 'fanart', label: '❌背景图' },
  ],
  metadata: [
    { value: 'plot', label: '简介' },
    { value: 'actors', label: '演员' },
    { value: 'genre', label: '标签' },
    { value: 'studio', label: '厂商' },
    { value: 'maker', label: '制作商' },
    { value: 'series', label: '系列' },
    { value: 'director', label: '导��' },
    { value: 'tag', label: '额外标签' },
    { value: 'duration', label: '时长' },
    { value: 'rating', label: '评分' },
    { value: 'title_jp', label: '日语标题' },
    { value: 'plot_short', label: '短简介' },
    { value: 'trailer_url', label: '预告片' },
  ],
  images: [
    { value: 'cover', label: '封面' },
    { value: 'thumb', label: '缩略图' },
    { value: 'extrafanart', label: '预览图' },
    { value: 'actors_image', label: '演员头像' },
  ],
}

const allFieldOptions = computed(() => [
  ...fieldGroups.critical, ...fieldGroups.metadata, ...fieldGroups.images
])

const isAllSelected = computed(() => {
  const allValues = allFieldOptions.value.map(o => o.value)
  return allValues.length > 0 && allValues.every(v => detectForm.value.fields.includes(v))
})
const isAllSelectedIndeterminate = computed(() => {
  const allValues = allFieldOptions.value.map(o => o.value)
  const selected = allValues.filter(v => detectForm.value.fields.includes(v)).length
  return selected > 0 && selected < allValues.length
})
const handleSelectAll = (val) => {
  detectForm.value.fields = val ? allFieldOptions.value.map(o => o.value) : []
}

const runForm = ref({
  mode: 'all',
  patch_type: 'smart',
  sources: ['javbus', 'javdb', 'avmoo'],
  only_missing: true,
  skip_recent: false,
  skip_recent_days: 0,
  skip_verified: false,
  directories: []
})

const loadConfig = async () => {
  try {
    const cfg = await getConfig()
    const scraper = cfg.scraper || cfg.data?.scraper || {}
    mediaDirOptions.value = scraper.media_dirs || []
  } catch (e) {
    console.error('加载配置失败', e)
  }
}

const detectPercent = computed(() => {
  if (!detectResult.value) return 0
  const total = detectResult.value.total || 0
  const missing = detectResult.value.items?.length || 0
  if (total === 0) return 0
  return Math.round(missing / total * 100)
})

const jobStatusText = computed(() => {
  if (!currentJob.value) return ''
  const s = currentJob.value.status
  const map = { running: '运行中', success: '已完成', failed: '失败' }
  return map[s] || s || '运行中'
})

const jobStatus = computed(() => {
  if (!currentJob.value) return ''
  if (currentJob.value.status === 'success') return 'success'
  if (currentJob.value.status === 'failed') return 'exception'
  return ''
})

const runDetect = async () => {
  detecting.value = true
  try {
    // scope 仅影响「检测字段」的展示口径；fields 交给后端做精确过滤
    const params = {
      fields: detectForm.value.fields,
    }
    if (detectDirs.value.length) params.directories = detectDirs.value
    const res = await detectMissing(params)
    detectResult.value = res
    ElMessage.success(`检测完成：共 ${res.total ?? 0} 个影片存在缺失`)
  } catch (e) { console.error(e); ElMessage.error('检测失败：' + (e.response?.data?.detail || e.message)) }
  finally { detecting.value = false }
}

const goToRun = () => { currentStep.value = 1 }

const runPatchAction = async () => {
  running.value = true
  try {
    const payload = {
      mode: runForm.value.mode,
      patch_type: runForm.value.patch_type,
      sources: runForm.value.sources,
      skip_complete: runForm.value.only_missing,
      skip_recent_days: runForm.value.skip_recent ? runForm.value.skip_recent_days : 0,
      skip_verified: runForm.value.skip_verified,
    }
    if (runForm.value.mode === 'directory') {
      payload.directories = runDirs.value.length ? runDirs.value : detectDirs.value
    }
    const res = await runPatch(payload)
    currentJob.value = res
    ElMessage.success('补刮任务已启动')
    pollJob(res.job_id || res.id)
  } catch (e) { console.error(e); ElMessage.error('启动失败：' + (e.response?.data?.detail || e.message)) }
  finally { running.value = false }
}

const pollJob = (jobId) => {
  if (!jobId) return
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const status = await getPatchStatus(jobId)
      currentJob.value = status
      if (['success', 'failed', 'completed'].includes(status.status)) {
        clearInterval(pollTimer)
        pollTimer = null
        const r = await getPatchReport(jobId)
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
    const res = await getPatchHistory()
    history.value = res.items || res || []
  } catch (e) { console.error(e) }
  finally { loadingHistory.value = false }
}

const restart = () => {
  currentStep.value = 0
  detectResult.value = null
  currentJob.value = null
  report.value = null
}

onMounted(() => {
  loadConfig()
  loadHistory()
})
</script>

<style scoped>
.patch { display: flex; flex-direction: column; gap: 16px; }
.step-card, .content-card { border-radius: 10px; }
.hint { margin-left: 8px; color: #909399; font-size: 12px; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; color: #303133; }
.detect-result h4, .report h4 { color: #303133; margin: 12px 0; }
.result-stat { text-align: center; padding: 16px; background: #f5f7fa; border-radius: 8px; }
.result-num { font-size: 24px; font-weight: 700; color: #303133; }
.result-num.success { color: #67c23a; }
.result-num.warning { color: #e6a23c; }
.result-num.danger { color: #f56c6c; }
.result-num.info { color: #909399; }
.result-label { color: #909399; font-size: 12px; margin-top: 4px; }
.job-progress { margin-top: 16px; }
.job-info { display: flex; gap: 16px; margin-top: 10px; color: #606266; font-size: 13px; }
</style>
