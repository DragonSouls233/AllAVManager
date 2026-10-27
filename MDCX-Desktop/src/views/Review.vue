<template>
  <div class="review-page">
    <h2>刮削复核</h2>
    <p class="page-desc">
      把刮削质量做成可运营的抓手：扫描可疑条目（缺封面 / 缺标题 / 乱码 / 番号异常 / 零元数据），
      逐项核查、忽略或导出 CSV。
    </p>

    <!-- 操作栏 -->
    <el-card shadow="never" class="toolbar-card">
      <el-button type="primary" :icon="Search" :loading="scanning" @click="doScan">
        扫描刮削质量
      </el-button>
      <el-button :icon="Download" :loading="exporting" @click="doExport">导出 CSV</el-button>
      <el-button :icon="Delete" @click="clearIgnore">清空忽略名单</el-button>
      <span class="hint">大库（PORNHUB 9 万+）扫描需数秒</span>
    </el-card>

    <!-- 统计 -->
    <el-row :gutter="16" class="stats-row" v-if="stats">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">问题总数</div>
          <div class="stat-value danger">{{ stats.total_issues }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">待处理</div>
          <div class="stat-value">{{ stats.open_issues }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">已忽略</div>
          <div class="stat-value muted">{{ stats.ignored_count }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">高严重度</div>
          <div class="stat-value danger">{{ stats.by_severity?.high || 0 }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 过滤栏 -->
    <el-card shadow="never" class="filter-card">
      <el-select v-model="filterType" placeholder="问题类型" clearable style="width: 180px" @change="loadIssues">
        <el-option v-for="r in rules" :key="r.code" :label="r.label" :value="r.code" />
      </el-select>
      <el-select v-model="filterSeverity" placeholder="严重度" clearable style="width: 130px; margin-left: 12px" @change="loadIssues">
        <el-option label="高" value="high" />
        <el-option label="中" value="medium" />
        <el-option label="低" value="low" />
      </el-select>
      <el-checkbox v-model="includeIgnored" style="margin-left: 16px" @change="loadIssues">
        包含已忽略
      </el-checkbox>
    </el-card>

    <!-- 列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="issues" v-loading="loading" stripe @selection-change="onSelect">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="module_label" label="模块" width="90" />
        <el-table-column prop="code" label="番号" width="150" />
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip />
        <el-table-column label="问题类型" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="t in row.type_labels" :key="t" size="small" class="type-tag">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="严重度" width="90">
          <template #default="{ row }">
            <el-tag :type="sevType(row.severity)" effect="dark">{{ sevLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="ignoreOne(row)" v-if="!row.ignored">忽略</el-button>
            <el-button size="small" type="info" @click="unignoreOne(row)" v-else>取消忽略</el-button>
            <el-button size="small" type="primary" plain @click="goDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="batch-bar" v-if="selected.length > 0">
        <span>已选 {{ selected.length }} 条</span>
        <el-button size="small" @click="batchIgnore">批量忽略</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Download, Delete } from '@element-plus/icons-vue'
import {
  listReviewRules, scanReview, getReviewStats, listReviewIssues,
  ignoreReviewIssue, ignoreReviewBatch, unignoreReviewIssue,
  clearIgnoreList, exportReviewCsv,
} from '@/api'

const router = useRouter()
const rules = ref([])
const stats = ref(null)
const issues = ref([])
const selected = ref([])
const loading = ref(false)
const scanning = ref(false)
const exporting = ref(false)
const filterType = ref('')
const filterSeverity = ref('')
const includeIgnored = ref(false)

const sevType = (s) => ({ high: 'danger', medium: 'warning', low: 'info' }[s] || '')
const sevLabel = (s) => ({ high: '高', medium: '中', low: '低' }[s] || s)

const loadRules = async () => {
  try { const d = await listReviewRules(); rules.value = d.rules || [] } catch (e) {}
}
const loadStats = async () => {
  try { stats.value = await getReviewStats('all') } catch (e) {}
}
const loadIssues = async () => {
  loading.value = true
  try {
    const d = await listReviewIssues({
      module: 'all', type: filterType.value || undefined,
      severity: filterSeverity.value || undefined,
      include_ignored: includeIgnored.value, limit: 100, offset: 0,
    })
    issues.value = d.items || []
  } catch (e) { /* */ } finally { loading.value = false }
}

const doScan = async () => {
  scanning.value = true
  try {
    await scanReview('all', false)
    await Promise.all([loadStats(), loadIssues()])
    ElMessage.success('扫描完成')
  } catch (e) { /* */ } finally { scanning.value = false }
}

const doExport = async () => {
  exporting.value = true
  try {
    const res = await exportReviewCsv({
      module: 'all', type: filterType.value || undefined,
      include_ignored: includeIgnored.value,
    })
    const blob = res.data instanceof Blob ? res.data : new Blob([res.data])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'review-issues.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { /* */ } finally { exporting.value = false }
}

const ignoreOne = async (row) => {
  try {
    await ignoreReviewIssue({ module: row.module, movie_id: row.id, reason: '' })
    row.ignored = true; await loadStats(); ElMessage.success('已忽略')
  } catch (e) {}
}
const unignoreOne = async (row) => {
  try {
    await unignoreReviewIssue({ module: row.module, movie_id: row.id })
    row.ignored = false; await loadStats()
  } catch (e) {}
}
const onSelect = (rows) => { selected.value = rows }
const batchIgnore = async () => {
  if (!selected.value.length) return
  try {
    await ElMessageBox.confirm(`确认忽略选中的 ${selected.value.length} 条？`, '批量忽略', { type: 'warning' })
    await ignoreReviewBatch(selected.value.map(r => ({ module: r.module, movie_id: r.id, reason: '' })))
    await Promise.all([loadStats(), loadIssues()])
    ElMessage.success('已批量忽略')
  } catch (e) {}
}
const clearIgnore = async () => {
  try {
    await ElMessageBox.confirm('确认清空全部忽略名单？', '清空', { type: 'warning' })
    await clearIgnoreList(); await Promise.all([loadStats(), loadIssues()])
  } catch (e) {}
}
const goDetail = (row) => router.push(`/${row.module}/movies/${row.id}`)

onMounted(() => { loadRules(); loadStats(); loadIssues() })
</script>

<style scoped>
.review-page { padding: 16px; }
.page-desc { color: var(--el-text-color-secondary); margin-bottom: 16px; }
.toolbar-card { margin-bottom: 16px; display: flex; gap: 12px; align-items: center; }
.toolbar-card .hint { color: var(--el-text-color-secondary); font-size: 12px; }
.stats-row { margin-bottom: 16px; }
.stat-card { border-radius: 8px; }
.stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-value { font-size: 28px; font-weight: 600; }
.stat-value.danger { color: var(--el-color-danger); }
.stat-value.muted { color: var(--el-text-color-secondary); }
.filter-card { margin-bottom: 16px; }
.list-card { border-radius: 8px; }
.type-tag { margin-right: 4px; }
.batch-bar {
  margin-top: 12px; padding: 12px; background: #f5f7fa;
  border-radius: 6px; display: flex; gap: 8px; align-items: center;
}
</style>
