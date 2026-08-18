<template>
  <div class="scan-control">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Search /></el-icon>
          扫描控制
        </h2>
        <div class="page-subtitle">全模块扫描任务管理与冷却状态监控</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <!-- 状态卡片 -->
    <el-row :gutter="16" style="margin-bottom: 16px">
      <!-- 冷却状态 -->
      <el-col :span="8">
        <el-card shadow="never" class="status-card">
          <template #header>
            <div class="card-title">
              <el-icon><Timer /></el-icon> 冷却状态
            </div>
          </template>
          <div v-if="scanStatus" class="status-body">
            <div class="status-row">
              <span class="status-label">冷却中</span>
              <el-tag :type="scanStatus.in_cooldown ? 'warning' : 'success'" size="small">
                {{ scanStatus.in_cooldown ? '是' : '否' }}
              </el-tag>
            </div>
            <div class="status-row" v-if="scanStatus.in_cooldown">
              <span class="status-label">冷却剩余</span>
              <span class="status-value">{{ formatCooldown(scanStatus.cooldown_remaining_seconds) }}</span>
            </div>
            <div class="status-row">
              <span class="status-label">上次扫描</span>
              <span class="status-value">{{ scanStatus.last_scan_time ? formatTime(scanStatus.last_scan_time) : '从未执行' }}</span>
            </div>
            <div class="status-row">
              <span class="status-label">冷却时长</span>
              <span class="status-value">{{ scanStatus.cooldown_hours ?? '-' }} 小时</span>
            </div>
            <div class="status-row">
              <span class="status-label">重置间隔</span>
              <span class="status-value">{{ scanStatus.reset_days ?? '-' }} 天</span>
            </div>
          </div>
          <el-empty v-else-if="!loading" description="暂无状态信息" :image-size="60" />
        </el-card>
      </el-col>

      <!-- 手动扫描 -->
      <el-col :span="8">
        <el-card shadow="never" class="action-card">
          <template #header>
            <div class="card-title">
              <el-icon><CaretRight /></el-icon> 手动扫描
            </div>
          </template>
          <div class="action-body">
            <el-button
              type="primary"
              size="large"
              class="scan-btn"
              @click="handleManualScan"
              :loading="scanning"
              :disabled="scanStatus?.in_cooldown"
            >
              <el-icon><Search /></el-icon>
              立即执行全模块扫描
            </el-button>
            <div class="action-hint" v-if="scanStatus?.in_cooldown">
              <el-icon><WarningFilled /></el-icon> 扫描冷却中，请等待冷却结束后再执行
            </div>
            <div class="action-hint" v-else>
              手动触发所有模块的媒体文件扫描任务
            </div>

            <!-- 单独模块扫描 -->
            <el-divider style="margin: 10px 0">
              <span style="font-size: 12px; color: #909399">单独模块扫描</span>
            </el-divider>
            <div class="module-scan-list" v-loading="modulesLoading">
              <div
                v-for="mod in enabledModules"
                :key="mod.name"
                class="module-scan-row"
              >
                <span class="module-scan-name">
                  {{ moduleLabel(mod.name) }}
                  <el-tag size="small" type="info" effect="plain">
                    {{ mod.media_dirs?.length || 0 }} 目录
                  </el-tag>
                </span>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="scanningModule === mod.name"
                  :disabled="scanStatus?.in_cooldown"
                  @click="handleModuleScan(mod)"
                >
                  扫描
                </el-button>
              </div>
              <div v-if="!enabledModules.length" class="module-scan-empty">无已启用模块</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 统计信息 -->
      <el-col :span="8">
        <el-card shadow="never" class="stats-card">
          <template #header>
            <div class="card-title">
              <el-icon><DataAnalysis /></el-icon> 扫描统计
            </div>
          </template>
          <div class="stats-grid">
            <div class="stat-item">
              <div class="stat-value">{{ stats.total_records }}</div>
              <div class="stat-label">总扫描次数</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">{{ stats.success_count }}</div>
              <div class="stat-label">成功次数</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">{{ stats.failed_count }}</div>
              <div class="stat-label">失败次数</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选工具栏 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-select v-model="filters.type" placeholder="扫描类型" clearable style="width: 140px">
            <el-option label="全部" value="" />
            <el-option label="启动扫描" value="startup" />
            <el-option label="手动扫描" value="manual" />
            <el-option label="定时扫描" value="scheduled" />
          </el-select>
          <el-select v-model="filters.status" placeholder="扫描状态" clearable style="width: 140px">
            <el-option label="全部" value="" />
            <el-option label="运行中" value="running" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
            <el-option label="超时" value="timeout" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button size="small" @click="loadRecords">
            <el-icon><Search /></el-icon> 查询
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 扫描记录列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="records" v-loading="recordsLoading" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTagType(row.type)">
              {{ typeLabel(row.type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="dark">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="module" label="模块" min-width="120" show-overflow-tooltip />
        <el-table-column prop="total_files" label="文件总数" width="90" align="center" />
        <el-table-column prop="new_files" label="新增数" width="80" align="center" />
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">
            {{ row.started_at ? formatTime(row.started_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="完成时间" width="170">
          <template #default="{ row }">
            {{ row.completed_at ? formatTime(row.completed_at) : '-' }}
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination" v-if="total > 0">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadRecords"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Search, Refresh, Timer, CaretRight, WarningFilled, DataAnalysis
} from '@element-plus/icons-vue'
import {
  getScanStatus, triggerManualScan, getScanRecords
} from '@/api'
import { getModules } from '@/api/modules'

const loading = ref(false)
const recordsLoading = ref(false)
const scanning = ref(false)
const scanStatus = ref(null)
const records = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const filters = reactive({ type: '', status: '' })

// 模块列表（单独模块扫描）
const modules = ref([])
const modulesLoading = ref(false)
const scanningModule = ref('')

// 已启用且有媒体目录的模块
const enabledModules = computed(() =>
  (modules.value || []).filter(m => m.enabled && (m.media_dirs?.length || 0) > 0)
)

// 模块显示名映射
const MODULE_LABELS = {
  jav: 'JAV 有码',
  uncensored: 'JAV 无码',
  fc2: 'FC2',
  chinese: '国产',
  pornhub: 'PORNHUB',
  western: '欧美',
  anime: '动漫',
}
const moduleLabel = (name) => MODULE_LABELS[name] || name

// 加载模块列表
const loadModules = async () => {
  modulesLoading.value = true
  try {
    modules.value = await getModules()
  } catch {
    modules.value = []
  } finally {
    modulesLoading.value = false
  }
}

// 自动刷新定时器
let autoRefreshTimer = null

// 统计信息
const stats = computed(() => {
  const list = records.value || []
  return {
    total_records: total.value,
    success_count: list.filter(r => r.status === 'completed').length,
    failed_count: list.filter(r => r.status === 'failed').length
  }
})

// 类型标签映射
const typeTagType = (type) => {
  const map = { startup: '', manual: 'primary', scheduled: 'warning' }
  return map[type] || ''
}

const typeLabel = (type) => {
  const map = { startup: '启动扫描', manual: '手动扫描', scheduled: '定时扫描' }
  return map[type] || type || '未知'
}

// 状态标签映射
const statusTagType = (status) => {
  const map = { running: 'warning', completed: 'success', failed: 'danger', timeout: 'info' }
  return map[status] || ''
}

const statusLabel = (status) => {
  const map = { running: '运行中', completed: '已完成', failed: '失败', timeout: '超时' }
  return map[status] || status || '未知'
}

// 冷却时间格式化
const formatCooldown = (seconds) => {
  if (!seconds && seconds !== 0) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h} 小时 ${m} 分钟`
  if (m > 0) return `${m} 分钟 ${s} 秒`
  return `${s} 秒`
}

// 时间格式化
const formatTime = (t) => {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN')
  } catch {
    return t
  }
}

// 加载状态
const loadStatus = async () => {
  try {
    scanStatus.value = await getScanStatus()
  } catch {
    // 静默失败
  }
}

// 加载记录
const loadRecords = async () => {
  recordsLoading.value = true
  try {
    const params = { page: page.value, page_size: pageSize }
    if (filters.type) params.type = filters.type
    if (filters.status) params.status = filters.status
    const res = await getScanRecords(params)
    records.value = res.records || res.items || []
    total.value = res.total || res.total_count || 0
  } catch {
    records.value = []
    total.value = 0
  } finally {
    recordsLoading.value = false
  }
}

// 加载全部
const loadAll = async () => {
  loading.value = true
  await Promise.all([loadStatus(), loadRecords(), loadModules()])
  loading.value = false
}

// 手动扫描
const handleManualScan = async () => {
  scanning.value = true
  try {
    const res = await triggerManualScan()
    ElMessage.success('扫描任务已触发，请在记录列表中查看进度')
    // 刷新状态和记录
    await loadAll()
  } catch (e) {
    ElMessage.error('触发扫描失败：' + (e?.response?.data?.detail || e.message || '未知错误'))
  } finally {
    scanning.value = false
  }
}

// 单独模块扫描
const handleModuleScan = async (mod) => {
  scanningModule.value = mod.name
  try {
    const res = await triggerManualScan(mod.name)
    ElMessage.success(`模块「${moduleLabel(mod.name)}」扫描任务已触发，请在记录列表中查看进度`)
    await loadAll()
  } catch (e) {
    ElMessage.error(`触发「${moduleLabel(mod.name)}」扫描失败：` + (e?.response?.data?.detail || e.message || '未知错误'))
  } finally {
    scanningModule.value = ''
  }
}

// 检查是否需要自动刷新（当有运行中的扫描时每30秒刷新一次）
const isAnyRunning = computed(() => {
  return (records.value || []).some(r => r.status === 'running')
})

const startAutoRefresh = () => {
  stopAutoRefresh()
  if (isAnyRunning.value) {
    autoRefreshTimer = setInterval(async () => {
      await loadAll()
      // 如果不再有运行中的任务，停止刷新
      if (!isAnyRunning.value) {
        stopAutoRefresh()
      }
    }, 30000)
  }
}

const stopAutoRefresh = () => {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer)
    autoRefreshTimer = null
  }
}

onMounted(async () => {
  await loadAll()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.scan-control {
  display: flex;
  flex-direction: column;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.page-header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title {
  margin: 0;
  font-size: 20px;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-subtitle {
  font-size: 13px;
  color: #909399;
  margin-left: 32px;
}

.page-header-actions {
  display: flex;
  gap: 8px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

/* 状态卡片 */
.status-card,
.action-card,
.stats-card {
  border-radius: 8px;
  border: none;
}

.status-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.status-label {
  color: #909399;
  font-size: 13px;
}

.status-value {
  color: #303133;
  font-size: 13px;
  font-weight: 500;
}

/* 手动扫描按钮 */
.action-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
}

.scan-btn {
  width: 100%;
  height: 48px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
}

.action-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #909399;
  text-align: center;
}

/* 单独模块扫描 */
.module-scan-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}

.module-scan-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  border-radius: 6px;
  background: #f5f7fa;
}

.module-scan-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #303133;
}

.module-scan-empty {
  font-size: 12px;
  color: #909399;
  text-align: center;
  padding: 8px 0;
}

/* 统计 */
.stats-grid {
  display: flex;
  justify-content: space-around;
  text-align: center;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #409eff;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

/* 工具栏 */
.toolbar-card,
.table-card {
  border-radius: 8px;
  border: none;
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar-left {
  display: flex;
  gap: 12px;
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0 0;
}
</style>
