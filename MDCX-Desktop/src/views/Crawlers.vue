<template>
  <div class="crawlers">
    <!-- 模块标识横幅 -->
    <el-alert v-if="moduleTitle" :title="moduleTitle" :description="moduleDesc" :type="moduleAlertType" show-icon :closable="false" class="module-banner" />

    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-num primary">{{ stats.total || 0 }}</div>
            <div class="stat-label">总爬虫数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-num success">{{ stats.enabled || 0 }}</div>
            <div class="stat-label">已启用</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-num" :class="health.circuit_open > 0 ? 'danger' : 'info'">
              {{ health.circuit_open || 0 }}
            </div>
            <div class="stat-label">熔断中</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-num warning">{{ stats.disabled || 0 }}</div>
            <div class="stat-label">已禁用</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-num info">{{ stats.avg_latency ? stats.avg_latency.toFixed(0) + 'ms' : '-' }}</div>
            <div class="stat-label">平均延迟</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 熔断中的源：一眼看清现在谁在跳过 -->
    <el-alert
      v-if="breakerList.length"
      type="warning" show-icon :closable="false" class="breaker-banner"
      :title="`${breakerList.length} 个源当前被熔断跳过`"
    >
      <div class="breaker-list">
        <el-tag v-for="s in breakerList" :key="s.name" type="danger" size="small" class="breaker-tag">
          {{ s.display_name || s.name }} · {{ Math.round(s.breaker.remaining_seconds) }}s
          <span v-if="s.breaker.strike" class="breaker-strike">· 连续 {{ s.breaker.strike }} 次</span>
        </el-tag>
      </div>
    </el-alert>

    <!-- 工具栏 -->
    <el-card class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input v-model="searchKey" placeholder="搜索爬虫名称/网址..." clearable style="width:220px">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="filterStatus" placeholder="状态" style="width:100px">
            <el-option label="全部" value="" />
            <el-option label="已启用" value="enabled" />
            <el-option label="已禁用" value="disabled" />
          </el-select>
          <el-select v-model="filterTier" placeholder="源序层级" style="width:120px">
            <el-option label="全部层级" value="" />
            <el-option label="主力源" value="primary" />
            <el-option label="辅助源" value="aux" />
            <el-option label="日本官方" value="jp" />
            <el-option label="未入源序" value="other" />
          </el-select>
          <el-tooltip content="只显示当前熔断中的源" placement="top">
            <el-checkbox v-model="onlyBreaker">仅熔断</el-checkbox>
          </el-tooltip>
          <span class="filter-hint" v-if="moduleTypes.length">当前模块：<el-tag size="small" :type="moduleAlertType">{{ moduleTypes.join(' · ') }}</el-tag></span>
        </div>
        <div class="toolbar-right">
          <el-button type="primary" :loading="pingingAll" @click="pingAll">
            <el-icon><Connection /></el-icon> 一键测速
          </el-button>
          <el-button @click="loadCrawlers"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
      </div>
    </el-card>

    <!-- 爬虫表格 -->
    <el-card shadow="never" class="table-card">
      <el-empty v-if="!loading && filteredCrawlers.length === 0" description="未找到匹配的爬虫，请检查筛选条件或刷新列表" />
      <el-table v-else :data="filteredCrawlers" v-loading="loading" stripe
        :default-sort="{ prop: 'priority', order: 'ascending' }">
        <el-table-column prop="name" label="标识" width="130" fixed>
          <template #default="{ row }"><span class="crawler-name">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column prop="display_name" label="名称" width="130" />
        <el-table-column prop="base_url" label="网址" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link v-if="row.base_url" :href="row.base_url" target="_blank" type="primary">{{ row.base_url }}</el-link>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="supported_types" label="支持类型" width="180">
          <template #default="{ row }">
            <el-tag v-for="t in (row.supported_types || [])" :key="t" size="small"
              :type="typeTagType(t)" style="margin-right:4px;margin-bottom:2px">{{ typeLabel(t) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="90" sortable>
          <template #default="{ row }">
            <span :class="['priority-badge', `p-${priorityLevel(row.priority)}`]">{{ row.priority }}</span>
          </template>
        </el-table-column>
        <el-table-column label="源序层级" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="healthMap[row.name]" size="small" :type="tierTagType(healthMap[row.name].tier)">
              {{ tierLabel(healthMap[row.name].tier) }}
            </el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="能力" min-width="190">
          <template #default="{ row }">
            <template v-if="healthMap[row.name]">
              <el-tag v-for="c in (healthMap[row.name].capabilities || [])" :key="c" size="small"
                :type="capTagType(c)" class="cap-tag">{{ capLabel(c) }}</el-tag>
            </template>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="熔断" width="120" align="center">
          <template #default="{ row }">
            <template v-if="healthMap[row.name]">
              <el-tag v-if="healthMap[row.name].breaker?.open" type="danger" size="small"
                class="breaker-cell">跳过 {{ Math.round(healthMap[row.name].breaker.remaining_seconds) }}s</el-tag>
              <el-tag v-else-if="healthMap[row.name].breaker?.half_open" type="warning" size="small">半开</el-tag>
              <span v-else class="text-ok">正常</span>
            </template>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80" fixed="right">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(val) => toggleCrawler(row, val)" :loading="row._switching" />
          </template>
        </el-table-column>
        <el-table-column label="延迟" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row._ping !== undefined" :class="['latency', latencyClass(row._ping)]">{{ row._ping === -1 ? '失败' : row._ping + 'ms' }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="testCrawlerDialog(row)" :loading="row._testing">测试</el-button>
            <el-button size="small" type="primary" plain @click="pingSingle(row)" :loading="row._pinging">测速</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 测试对话框 -->
    <el-dialog v-model="testDialog.visible" title="测试爬虫刮削" width="640px">
      <el-form label-width="100px">
        <el-form-item label="爬虫"><el-tag>{{ testDialog.crawlerName }}</el-tag></el-form-item>
        <el-form-item label="测试番号"><el-input v-model="testDialog.number" placeholder="例如：SSIS-001" /></el-form-item>
        <el-form-item v-if="testDialog.result" label="结果"><pre class="test-result">{{ testDialog.result }}</pre></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="testDialog.visible = false">关闭</el-button>
        <el-button type="primary" :loading="testDialog.loading" @click="runTest">执行测试</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Connection } from '@element-plus/icons-vue'
import { getCrawlers, getCrawlerStats, getSourceHealth, enableCrawler, disableCrawler, testCrawler, pingCrawler, pingCrawlers } from '@/api'

const route = useRoute()
const loading = ref(false)
const pingingAll = ref(false)
const crawlers = ref([])
const stats = ref({})
const searchKey = ref('')
const filterStatus = ref('')
const filterTier = ref('')
const onlyBreaker = ref(false)

// ---------- 模块检测 ----------
const MODULE_MAP = {
  jav:     { types: ['jav', 'jav_uncensored', 'fc2'],        title: 'JAV 刮削管理',    desc: '有码 · 无码 · FC2 共用爬虫体系',         alertType: 'primary' },
  fc2:     { types: ['fc2'],                                   title: 'FC2 刮削管理',    desc: 'FC2 独立爬虫',                             alertType: 'warning' },
  uncensored: { types: ['jav_uncensored'],                     title: '无码刮削管理',    desc: '无码 JAV 专用爬虫',                         alertType: 'danger' },
  western: { types: ['western'],                               title: '欧美刮削管理',    desc: '欧美站点爬虫',                             alertType: 'info' },
  pornhub: { types: ['pornhub'],                               title: 'Pornhub 刮削管理', desc: 'Pornhub 专用爬虫',                          alertType: 'warning' },
  chinese: { types: ['chinese'],                               title: '国产刮削管理',    desc: '国产站点爬虫（麻豆/91/海角等）',          alertType: 'success' },
}
const DEFAULT_MODULE = { types: [], title: '全部爬虫', desc: '所有模块的刮削站点', alertType: '' }

const moduleKey = computed(() => {
  const seg = route.path.split('/')
  return MODULE_MAP[seg[1]] ? seg[1] : null
})
const moduleCfg = computed(() => moduleKey.value ? MODULE_MAP[moduleKey.value] : DEFAULT_MODULE)
const moduleTitle = computed(() => moduleCfg.value.title)
const moduleDesc = computed(() => moduleCfg.value.desc)
const moduleAlertType = computed(() => moduleCfg.value.alertType)
const moduleTypes = computed(() => moduleCfg.value.types)

// ---------- 源健康（能力矩阵 / 层级 / 熔断）----------
// 端点 /health/sources 是 2026-10-08 新增；老后端未部署时返回 404，
// 这里整体容错：拿不到就退化成只显示原有列，不报错、不白屏。
const health = ref({})
const healthMap = computed(() => {
  const m = {}
  for (const s of (health.value.sources || [])) m[s.name] = s
  return m
})
const breakerList = computed(() =>
  (health.value.sources || []).filter(s => s.breaker?.open)
)

const TIER_LABEL = { primary: '主力', aux: '辅助', jp: '日本', other: '未入序' }
const TIER_TAG = { primary: 'success', aux: 'warning', jp: 'danger', other: 'info' }
const tierLabel = (t) => TIER_LABEL[t] || t
const tierTagType = (t) => TIER_TAG[t] || 'info'

// 能力轴：与后端 SourceCapability 枚举一致
const CAP_LABEL = {
  movie: '影片', performer: '演员', gallery: '图集',
  plot: '简介', rating: '评分', genres: '标签',
}
const CAP_TAG = {
  movie: 'success', performer: 'primary', gallery: 'warning',
  plot: 'danger', rating: 'info', genres: 'info',
}
const capLabel = (c) => CAP_LABEL[c] || c
const capTagType = (c) => CAP_TAG[c] || 'info'

const loadHealth = async () => {
  try {
    const res = await getSourceHealth()
    health.value = res || {}
  } catch (e) {
    health.value = {}   // 老后端无此端点，静默降级
  }
}

// ---------- 过滤 ----------
const filteredCrawlers = computed(() => {
  return crawlers.value.filter(c => {
    // 按模块类型过滤
    if (moduleTypes.value.length) {
      const cTypes = c.supported_types || []
      if (!cTypes.some(t => moduleTypes.value.includes(t))) return false
    }
    // 搜索关键词
    if (searchKey.value) {
      const key = searchKey.value.toLowerCase()
      if (!c.name.toLowerCase().includes(key) &&
          !(c.display_name || '').toLowerCase().includes(key) &&
          !(c.base_url || '').toLowerCase().includes(key)) return false
    }
    // 状态
    if (filterStatus.value === 'enabled' && !c.enabled) return false
    if (filterStatus.value === 'disabled' && c.enabled) return false
    // 源序层级
    if (filterTier.value) {
      const h = healthMap.value[c.name]
      if (!h || h.tier !== filterTier.value) return false
    }
    // 仅熔断
    if (onlyBreaker.value) {
      const h = healthMap.value[c.name]
      if (!h?.breaker?.open) return false
    }
    return true
  })
})

const typeLabel = (t) => ({
  jav: '有码', jav_uncensored: '无码', fc2: 'FC2',
  western: '欧美', pornhub: 'Pornhub', chinese: '国产',
  anime: '动画', normal: '通用', other: '其他'
}[t] || t)

const typeTagType = (t) => ({
  jav: 'success', jav_uncensored: 'danger', fc2: 'warning',
  western: 'info', pornhub: 'warning', chinese: 'success',
  anime: 'primary', normal: 'info'
}[t] || 'info')

const priorityLevel = (p) => {
  if (p <= 15) return 'high'
  if (p <= 30) return 'mid'
  if (p <= 50) return 'low'
  return 'lowest'
}

const latencyClass = (ms) => {
  if (ms === -1) return 'bad'
  if (ms < 500) return 'good'
  if (ms < 1500) return 'ok'
  return 'slow'
}

const loadCrawlers = async () => {
  loading.value = true
  try {
    const res = await getCrawlers()
    crawlers.value = (res.items || res || []).map(c => ({ ...c, _ping: undefined, _switching: false, _testing: false, _pinging: false }))
    loadStats()
    loadHealth()
  } catch (e) { /* ignore */ }
  finally { loading.value = false }
}

const loadStats = async () => {
  try {
    const res = await getCrawlerStats()
    stats.value = res || {}
  } catch (e) {
    const list = filteredCrawlers.value
    const enabled = list.filter(c => c.enabled).length
    const pinged = list.filter(c => c._ping !== undefined && c._ping > 0)
    const avg = pinged.length ? pinged.reduce((s, c) => s + c._ping, 0) / pinged.length : 0
    stats.value = { total: list.length, enabled, disabled: list.length - enabled, avg_latency: avg }
  }
}

const toggleCrawler = async (row, val) => {
  row._switching = true
  try {
    if (val) await enableCrawler(row.name)
    else await disableCrawler(row.name)
    row.enabled = val
    ElMessage.success(`${row.display_name || row.name} 已${val ? '启用' : '禁用'}`)
    loadStats()
  } catch (e) { /* ignore */ }
  finally { row._switching = false }
}

const pingSingle = async (row) => {
  row._pinging = true
  try {
    const res = await pingCrawler(row.name)
    row._ping = res.latency_ms ?? (res.latency ?? -1)
    if (row._ping > 0) ElMessage.success(`${row.name}: ${row._ping}ms`)
    else ElMessage.warning(`${row.name} 连接失败`)
    loadStats()
  } catch (e) { row._ping = -1 }
  finally { row._pinging = false }
}

const pingAll = async () => {
  pingingAll.value = true
  try {
    const res = await pingCrawlers()
    const results = res.results || res.items || []
    const map = {}
    results.forEach(r => { map[r.name] = r.latency_ms ?? r.latency ?? -1 })
    crawlers.value.forEach(c => { if (c.name in map) c._ping = map[c.name] })
    ElMessage.success(`测速完成：${results.length} 个站点`)
    loadStats()
  } catch (e) { /* ignore */ }
  finally { pingingAll.value = false }
}

const testDialog = ref({ visible: false, crawlerName: '', number: 'SSIS-001', result: '', loading: false })

const testCrawlerDialog = (row) => {
  testDialog.value = { visible: true, crawlerName: row.name, number: 'SSIS-001', result: '', loading: false }
}

const runTest = async () => {
  if (!testDialog.value.number) { ElMessage.warning('请输入测试番号'); return }
  testDialog.value.loading = true
  try {
    const res = await testCrawler(testDialog.value.crawlerName, testDialog.value.number)
    testDialog.value.result = JSON.stringify(res, null, 2)
    ElMessage.success('测试完成')
  } catch (e) { testDialog.value.result = '测试失败' }
  finally { testDialog.value.loading = false }
}

onMounted(() => { loadCrawlers() })
</script>

<style scoped>
.crawlers { display:flex; flex-direction:column; gap:16px; }
.module-banner { margin-bottom:0; }
.stats-row { margin-bottom:0; }
.stat-card { border-radius:10px; border:none; }
.stat-inner { text-align:center; padding:8px 0; }
.stat-num { font-size:28px; font-weight:700; line-height:1.2; }
.stat-num.primary { color:#409eff; }
.stat-num.success { color:#67c23a; }
.stat-num.warning { color:#e6a23c; }
.stat-num.info { color:#909399; }
.stat-num.danger { color:#f56c6c; }
.stat-label { color:#909399; font-size:13px; margin-top:4px; }
.toolbar-card, .table-card { border-radius:10px; }
.toolbar { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }
.toolbar-left, .toolbar-right { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.filter-hint { font-size:12px; color:#909399; }
.crawler-name { font-family:Consolas,Monaco,monospace; font-weight:600; color:#303133; }
.text-muted { color:#c0c4cc; }
.text-ok { color:#67c23a; font-size:12px; }

/* 熔断横幅 */
.breaker-banner { margin-bottom:12px; }
.breaker-list { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.breaker-tag { margin:0; }
.breaker-strike { opacity:.75; margin-left:4px; }

/* 能力标签 */
.cap-tag { margin:0 4px 2px 0; }
.breaker-cell { font-variant-numeric: tabular-nums; }
.priority-badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600; color:#fff; }
.priority-badge.p-high { background:#f56c6c; }
.priority-badge.p-mid { background:#e6a23c; }
.priority-badge.p-low { background:#409eff; }
.priority-badge.p-lowest { background:#909399; }
.latency.good { color:#67c23a; font-weight:600; }
.latency.ok { color:#e6a23c; font-weight:600; }
.latency.slow { color:#f56c6c; font-weight:600; }
.latency.bad { color:#f56c6c; font-weight:600; }
.test-result { background:#1a1a2e; color:#a5d6ff; padding:12px; border-radius:6px; font-size:12px; max-height:320px; overflow:auto; white-space:pre-wrap; word-break:break-all; }
</style>
