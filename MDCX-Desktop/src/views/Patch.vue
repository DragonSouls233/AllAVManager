<template>
  <div class="patch">
    <!-- 模块标识 -->
    <el-alert v-if="currentModule" :title="'补丁刮削 - ' + moduleLabel" type="info" show-icon :closable="false" class="module-banner" />
    <el-alert v-else title="补丁刮削" description="未指定模块，检测中心数据库（scraper.db）" type="info" show-icon :closable="false" class="module-banner" />

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
          <!-- 精简模式：只列后端 canon 真实源序（主力 + 日本源 / 辅助源） -->
          <div v-if="hasCuratedSources" class="source-pool">
            <div class="source-row">
              <span class="source-tag primary">主力</span>
              <el-checkbox-group v-model="runForm.sources">
                <el-checkbox v-for="o in primaryOptions" :key="o.value" :value="o.value" border size="small">{{ o.label }}</el-checkbox>
              </el-checkbox-group>
            </div>
            <div class="source-row">
              <span class="source-tag">备用</span>
              <el-checkbox-group v-model="runForm.sources">
                <el-checkbox v-for="o in fallbackOptions" :key="o.value" :value="o.value" border size="small">{{ o.label }}</el-checkbox>
              </el-checkbox-group>
            </div>
            <div class="source-actions">
              <el-button link type="primary" size="small" @click="selectSources('auto')">自动序（推荐）</el-button>
              <el-button link size="small" @click="selectSources('all')">全选</el-button>
              <el-button link size="small" @click="selectSources('primary')">仅主力</el-button>
              <span class="hint" v-if="!runForm.sources.length">当前＝自动序，由后端按 canon 裁决</span>
              <span class="hint" v-else>已选 {{ runForm.sources.length }} / {{ sourceOptions.length }} 个源</span>
            </div>
          </div>
          <!-- 兼容模式：其他模块仍按爬虫注册表动态列出 -->
          <el-checkbox-group v-else v-model="runForm.sources">
            <el-checkbox v-for="o in sourceOptions" :key="o.value" :value="o.value" border size="small">{{ o.label }}</el-checkbox>
          </el-checkbox-group>
          <span class="hint" v-if="sourceHint">{{ sourceHint }}</span>
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
          <span class="to-patch-num">待补：{{ currentJob.total_to_patch ?? 0 }} 部</span>
          <span>已处理：{{ currentJob.total_patched ?? 0 }}</span>
          <span>成功：{{ currentJob.total_success ?? 0 }}</span>
          <span>失败：{{ currentJob.total_failed ?? 0 }}</span>
          <span v-if="currentJob.total_skipped" class="muted-num">已跳过：{{ currentJob.total_skipped }} 部</span>
          <span v-if="currentJob.total_detected" class="muted-num">（扫描 {{ currentJob.total_detected }} 部，其中大部分为可选字段缺失/近期已刮，自动跳过）</span>
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
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, MagicStick, ArrowRight, Document } from '@element-plus/icons-vue'
import { detectMissing, runPatch, getPatchStatus, getPatchReport, getPatchHistory, getConfig, getCrawlers } from '@/api'
import { getSourceOrder } from '@/api/jav'

const route = useRoute()

// 支持 prop 传入（chinese/Patch.vue 包装器）或从路由路径自动检测
const props = defineProps({ module: { type: String, default: null } })
const currentModule = computed(() => {
  if (props.module) return props.module
  // 从路由路径自动检测：/jav/patch → jav
  const seg = route.path.split('/')
  const MODULE_NAMES = ['jav', 'fc2', 'uncensored', 'chinese', 'western', 'pornhub']
  return MODULE_NAMES.includes(seg[1]) ? seg[1] : null
})

const MODULE_LABELS = {
  jav: 'JAV 有码/无码/FC2', fc2: 'FC2', uncensored: '无码',
  chinese: '国产', western: '欧美', pornhub: 'Pornhub'
}
const moduleLabel = computed(() => MODULE_LABELS[currentModule.value] || currentModule.value || '中心数据库')

// 各模块对应的爬虫 supported_types（与「刮削管理」保持一致）
const MODULE_TYPES = {
  jav: ['jav', 'jav_uncensored', 'fc2'],
  fc2: ['fc2'],
  uncensored: ['jav_uncensored'],
  western: ['western'],
  pornhub: ['pornhub'],
  chinese: ['chinese'],
}
// ── 补刮来源池（从后端 canon 拉取真实源序）──────────────────────────────
// 🔴 2026-10-05 起不再硬编码源名列表。此前这里写死 engine 的 PRIMARY/FALLBACK
//    池，导致**漏掉 dmm_web**（用户已把 DMM/FANZA 定为主力源），且源序调整后
//    必然漂移。canon.source_order_for() 是唯一真相源，这里只负责渲染。
//    不传 sources 时后端会自己按 canon 序裁决（见 selectSources('auto')）。
const sourceOrder = ref({ mainstream: [], aux: [], jp: [], jp_available: false, labels: {} })

const _label = (name) => sourceOrder.value.labels?.[name] || name

// 主力段 = canon 主力 + 日本官方源（DMM 已进主力，排在辅助源之前）
const primaryOptions = computed(() => {
  const s = sourceOrder.value
  return [...(s.mainstream || []), ...(s.jp || [])].map(v => ({ value: v, label: _label(v) }))
})
// 辅助段 = canon 的 AUX_SOURCE_ORDER
const fallbackOptions = computed(() =>
  (sourceOrder.value.aux || []).map(v => ({ value: v, label: _label(v) }))
)
// 模块 → 补刮来源提示
const SOURCE_HINTS = {
  fc2: 'FC2 专用刮削源（与「刮削管理 - FC2」完全一致）',
  uncensored: '无码专用刮削源',
  western: '欧美专用刮削源',
  pornhub: 'Pornhub 专用刮削源',
  chinese: '国产专用刮削源',
}

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

// 爬虫注册表（用于按模块动态生成「补刮来源」选项）
const crawlers = ref([])

// 精简模式：jav（及中心数据库）用 canon 真实序，不依赖注册表接口
const hasCuratedSources = computed(() => currentModule.value === 'jav' || !currentModule.value)

// 兼容模式：其他模块仍从爬虫注册表按 supported_types 过滤（与「刮削管理」同源）
const dynamicOptions = computed(() => {
  const m = currentModule.value
  if (!m || !MODULE_TYPES[m]) return []
  const types = MODULE_TYPES[m]
  const seen = new Set()
  const uniq = []
  for (const c of crawlers.value) {
    if (!(c.supported_types || []).some(t => types.includes(t))) continue
    if (seen.has(c.name)) continue
    seen.add(c.name)
    uniq.push({ value: c.name, label: c.display_name || c.name })
  }
  return uniq
})

// 当前模块可用的刮削源
const sourceOptions = computed(() =>
  hasCuratedSources.value ? [...primaryOptions.value, ...fallbackOptions.value] : dynamicOptions.value
)

const sourceHint = computed(() => {
  const m = currentModule.value
  if (!m || m === 'jav') {
    if (!hasCuratedSources.value) return ''
    const jp = sourceOrder.value.jp_available
      ? ''
      : '（日本出口当前不可用，DMM 已自动从源序中跳过）'
    return `留空＝自动序：按番号在 canon 源序内轮换（素人/有码自动分流）${jp}` +
      '；手动勾选则只打勾选的源。'
  }
  return SOURCE_HINTS[m] || ''
})

// 来源快捷选择（自动 / 全选 / 仅主力 / 清空）
// 🔴 「自动」= sources 留空，交给后端 canon 按番号裁决。这是最稳的模式：
//    前端不猜顺序，素人/有码分流与日本源可用性都由后端实时判断。
const selectSources = (which) => {
  if (which === 'auto') runForm.value.sources = []
  else if (which === 'all') runForm.value.sources = sourceOptions.value.map(o => o.value)
  else if (which === 'primary') runForm.value.sources = primaryOptions.value.map(o => o.value)
  else runForm.value.sources = []
}

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
  sources: [],
  only_missing: true,
  skip_recent: true,
  skip_recent_days: 7,
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

// 🔴 不再默认全选。旧实现在进入页面时把整个来源池写进 runForm.sources，
// 那样等于用前端硬编码的列表覆盖后端 canon 序（且漏 dmm_web）。
// 留空＝自动序，由后端按番号裁决，这才是正确默认。
const applyDefaultSources = () => {
  runForm.value.sources = []
}

// 拉取 canon 真实源序（渲染主力/辅助两段 UI）
const loadSourceOrder = async () => {
  try {
    const r = await getSourceOrder('ABC-123')
    sourceOrder.value = r || { mainstream: [], aux: [], jp: [], jp_available: false, labels: {} }
  } catch (e) {
    console.error('加载源序失败', e)
  }
}

// 加载爬虫注册表（仅非 jav 模块动态来源需要它）
const loadCrawlers = async () => {
  try {
    const res = await getCrawlers()
    crawlers.value = (res.items || res || [])
  } catch (e) {
    console.error('加载爬虫列表失败', e)
  }
  applyDefaultSources()
  await loadSourceOrder()
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
    if (currentModule.value) params.module = currentModule.value
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
      module: currentModule.value || undefined,
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

onMounted(async () => {
  loadConfig()
  await loadCrawlers()
  applyDefaultSources()
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
.to-patch-num { font-weight: 600; color: var(--el-color-primary, #409eff); }
.muted-num { color: #909399; }

/* 补刮来源：主力 / 备用 分组 */
.source-pool { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.source-row { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
.source-tag {
  flex: 0 0 auto;
  margin-top: 2px;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 18px;
  color: #909399;
  background: #f4f4f5;
}
.source-tag.primary { color: #409eff; background: rgba(64, 158, 255, 0.12); font-weight: 600; }
.source-row :deep(.el-checkbox-group) { display: flex; flex-wrap: wrap; gap: 6px 8px; }
.source-row :deep(.el-checkbox) { margin-right: 0; }
.source-actions { display: flex; align-items: center; gap: 2px; }
.source-actions .hint { margin-left: 6px; }
</style>
