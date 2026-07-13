<template>
  <div class="crawlers">
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

    <!-- 工具栏 -->
    <el-card class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input
            v-model="searchKey"
            placeholder="搜索爬虫名称/网址..."
            clearable
            style="width: 260px"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select v-model="filterStatus" placeholder="状态筛选" style="width: 130px">
            <el-option label="全部" value="" />
            <el-option label="已启用" value="enabled" />
            <el-option label="已禁用" value="disabled" />
          </el-select>
          <el-select v-model="filterType" placeholder="类型筛选" style="width: 150px" clearable>
            <el-option v-for="t in allTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button type="primary" :loading="pingingAll" @click="pingAll">
            <el-icon><Connection /></el-icon>
            一键测速
          </el-button>
          <el-button @click="loadCrawlers">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 爬虫表格 -->
    <el-card shadow="never" class="table-card">
      <el-table
        :data="filteredCrawlers"
        v-loading="loading"
        stripe
        style="width: 100%"
        :default-sort="{ prop: 'priority', order: 'ascending' }"
      >
        <el-table-column prop="name" label="标识" width="140" fixed>
          <template #default="{ row }">
            <span class="crawler-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="display_name" label="名称" width="140" />
        <el-table-column prop="base_url" label="网址" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link v-if="row.base_url" :href="row.base_url" target="_blank" type="primary">
              {{ row.base_url }}
            </el-link>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="supported_types" label="支持类型" width="200">
          <template #default="{ row }">
            <el-tag
              v-for="t in (row.supported_types || [])"
              :key="t"
              size="small"
              :type="typeTagType(t)"
              style="margin-right: 4px; margin-bottom: 2px"
            >
              {{ typeLabel(t) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="100" sortable>
          <template #default="{ row }">
            <span :class="['priority-badge', `p-${priorityLevel(row.priority)}`]">
              {{ row.priority }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" fixed="right">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="(val) => toggleCrawler(row, val)"
              :loading="row._switching"
            />
          </template>
        </el-table-column>
        <el-table-column label="延迟" width="100" align="center">
          <template #default="{ row }">
            <span v-if="row._ping !== undefined" :class="['latency', latencyClass(row._ping)]">
              {{ row._ping === -1 ? '失败' : row._ping + 'ms' }}
            </span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="testCrawlerDialog(row)" :loading="row._testing">
              测试
            </el-button>
            <el-button size="small" type="primary" plain @click="pingSingle(row)" :loading="row._pinging">
              测速
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 测试爬虫对话框 -->
    <el-dialog v-model="testDialog.visible" title="测试爬虫刮削" width="640px">
      <el-form label-width="100px">
        <el-form-item label="爬虫">
          <el-tag>{{ testDialog.crawlerName }}</el-tag>
        </el-form-item>
        <el-form-item label="测试番号">
          <el-input v-model="testDialog.number" placeholder="例如：SSIS-001" />
        </el-form-item>
        <el-form-item v-if="testDialog.result" label="结果">
          <pre class="test-result">{{ testDialog.result }}</pre>
        </el-form-item>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Connection } from '@element-plus/icons-vue'
import {
  getCrawlers, getCrawlerStats, enableCrawler, disableCrawler,
  testCrawler, pingCrawler, pingCrawlers
} from '@/api'

const loading = ref(false)
const pingingAll = ref(false)
const crawlers = ref([])
const stats = ref({})
const searchKey = ref('')
const filterStatus = ref('')
const filterType = ref('')

const allTypes = computed(() => {
  const set = new Set()
  crawlers.value.forEach(c => (c.supported_types || []).forEach(t => set.add(t)))
  return Array.from(set).sort()
})

const filteredCrawlers = computed(() => {
  return crawlers.value.filter(c => {
    if (searchKey.value) {
      const key = searchKey.value.toLowerCase()
      if (!c.name.toLowerCase().includes(key) &&
          !(c.display_name || '').toLowerCase().includes(key) &&
          !(c.base_url || '').toLowerCase().includes(key)) return false
    }
    if (filterStatus.value === 'enabled' && !c.enabled) return false
    if (filterStatus.value === 'disabled' && c.enabled) return false
    if (filterType.value && !(c.supported_types || []).includes(filterType.value)) return false
    return true
  })
})

const typeLabel = (t) => ({
  jav: '有码',
  jav_uncensored: '无码',
  fc2: 'FC2',
  western: '欧美',
  anime: '动画',
  other: '其他'
}[t] || t)

const typeTagType = (t) => ({
  jav: 'success',
  jav_uncensored: 'danger',
  fc2: 'warning',
  western: 'info',
  anime: 'primary'
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
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    const res = await getCrawlerStats()
    stats.value = res || {}
  } catch (e) {
    // 兜底：根据列表计算
    const list = crawlers.value
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
  } catch (e) {
    // 错误已由拦截器提示
  } finally {
    row._switching = false
  }
}

const pingSingle = async (row) => {
  row._pinging = true
  try {
    const res = await pingCrawler(row.name)
    row._ping = res.latency_ms ?? (res.latency ?? -1)
    if (row._ping > 0) ElMessage.success(`${row.name}: ${row._ping}ms`)
    else ElMessage.warning(`${row.name} 连接失败`)
    loadStats()
  } catch (e) {
    row._ping = -1
  } finally {
    row._pinging = false
  }
}

const pingAll = async () => {
  pingingAll.value = true
  try {
    const res = await pingCrawlers()
    const results = res.results || res.items || []
    // 按 name 索引
    const map = {}
    results.forEach(r => { map[r.name] = r.latency_ms ?? r.latency ?? -1 })
    crawlers.value.forEach(c => {
      if (c.name in map) c._ping = map[c.name]
    })
    ElMessage.success(`测速完成：${results.length} 个站点`)
    loadStats()
  } catch (e) {
    console.error(e)
  } finally {
    pingingAll.value = false
  }
}

const testDialog = ref({
  visible: false,
  crawlerName: '',
  number: 'SSIS-001',
  result: '',
  loading: false
})

const testCrawlerDialog = (row) => {
  testDialog.value = {
    visible: true,
    crawlerName: row.name,
    number: 'SSIS-001',
    result: '',
    loading: false
  }
}

const runTest = async () => {
  if (!testDialog.value.number) {
    ElMessage.warning('请输入测试番号')
    return
  }
  testDialog.value.loading = true
  try {
    const res = await testCrawler(testDialog.value.crawlerName, testDialog.value.number)
    testDialog.value.result = JSON.stringify(res, null, 2)
    ElMessage.success('测试完成')
  } catch (e) {
    testDialog.value.result = '测试失败'
  } finally {
    testDialog.value.loading = false
  }
}

onMounted(() => {
  loadCrawlers()
})
</script>

<style scoped>
.crawlers {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stats-row {
  margin-bottom: 0;
}

.stat-card {
  border-radius: 10px;
  border: none;
}

.stat-inner {
  text-align: center;
  padding: 8px 0;
}

.stat-num {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-num.primary { color: #409eff; }
.stat-num.success { color: #67c23a; }
.stat-num.warning { color: #e6a23c; }
.stat-num.info { color: #909399; }

.stat-label {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}

.toolbar-card {
  border-radius: 10px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left, .toolbar-right {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.table-card {
  border-radius: 10px;
}

.crawler-name {
  font-family: 'Consolas', 'Monaco', monospace;
  font-weight: 600;
  color: #303133;
}

.text-muted {
  color: #c0c4cc;
}

/* 优先级徽章 */
.priority-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
}
.priority-badge.p-high { background: #f56c6c; }
.priority-badge.p-mid { background: #e6a23c; }
.priority-badge.p-low { background: #409eff; }
.priority-badge.p-lowest { background: #909399; }

/* 延迟颜色 */
.latency.good { color: #67c23a; font-weight: 600; }
.latency.ok { color: #e6a23c; font-weight: 600; }
.latency.slow { color: #f56c6c; font-weight: 600; }
.latency.bad { color: #f56c6c; font-weight: 600; }

.test-result {
  background: #1a1a2e;
  color: #a5d6ff;
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
