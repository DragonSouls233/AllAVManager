<template>
  <div class="site-priority-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Sort /></el-icon>
          站点优先级
        </h2>
        <div class="page-subtitle">拖拽排序 · 一键测速 · 启用/禁用 · 字段覆盖能力可视化</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadData" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button @click="pingAll" :loading="pinging">
          <el-icon><Connection /></el-icon> 一键测速
        </el-button>
        <el-button type="primary" @click="saveOrder" :loading="saving" :disabled="!orderChanged">
          <el-icon><Check /></el-icon> 保存顺序
        </el-button>
      </div>
    </div>

    <!-- 总览 -->
    <el-card shadow="never" class="summary-card">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="站点总数">{{ items.length }}</el-descriptions-item>
        <el-descriptions-item label="已启用">{{ enabledCount }} / {{ items.length }}</el-descriptions-item>
        <el-descriptions-item label="总刮削数">{{ totalMovies }}</el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="orderChanged"
        type="warning"
        :closable="false"
        show-icon
        title="顺序已变更，请点击“保存顺序”按钮以生效"
        style="margin-top: 10px"
      />
    </el-card>

    <!-- 站点列表（可拖拽） -->
    <el-card shadow="never" class="list-card">
      <template #header>
        <div class="card-title">
          <el-icon><Rank /></el-icon> 站点列表（拖拽排序 · 数值越大越优先）
        </div>
      </template>

      <div v-if="!items.length && !loading" class="empty-state">
        <el-empty description="暂无站点" />
      </div>

      <div
        v-for="(item, idx) in items"
        :key="item.name"
        class="site-row"
        :class="{ 'row-disabled': !item.enabled, 'row-dragging': draggingIdx === idx }"
        :draggable="true"
        @dragstart="onDragStart(idx, $event)"
        @dragover.prevent="onDragOver(idx, $event)"
        @dragenter.prevent="onDragEnter(idx)"
        @dragend="onDragEnd"
        @drop.prevent="onDrop(idx, $event)"
      >
        <div class="row-handle" title="拖拽排序">
          <el-icon><DCaret /></el-icon>
        </div>
        <div class="row-priority">
          <el-tag :type="idx === 0 ? 'danger' : idx < 3 ? 'warning' : 'info'" effect="dark" size="small">
            #{{ idx + 1 }}
          </el-tag>
          <div class="priority-num">{{ 1000 - idx }}</div>
        </div>
        <div class="row-info">
          <div class="row-name">
            <span class="name-text">{{ item.display_name }}</span>
            <el-tag size="small" type="info">{{ item.name }}</el-tag>
            <el-tag v-if="!item.enabled" size="small" type="danger">已禁用</el-tag>
          </div>
          <div class="row-url">
            <el-link :href="item.base_url" target="_blank" type="primary" :underline="false">
              {{ item.base_url || '-' }}
            </el-link>
          </div>
          <div class="row-meta">
            <span class="meta-item">
              <el-icon><Histogram /></el-icon>
              刮削 {{ item.scraped_count }} ({{ item.scraped_percent }}%)
            </span>
            <span class="meta-item">
              <el-icon><DataAnalysis /></el-icon>
              覆盖能力 {{ item.field_coverage_score }}/100
            </span>
            <span class="meta-item" v-if="item.supported_types?.length">
              <el-icon><Files /></el-icon>
              {{ item.supported_types.join(' · ') }}
            </span>
          </div>
        </div>
        <div class="row-ping">
          <template v-if="pingResults[item.name]">
            <div class="ping-row">
              <span class="ping-label">直连</span>
              <el-tag :type="pingTagType(pingResults[item.name].direct)" size="small">
                {{ pingText(pingResults[item.name].direct) }}
              </el-tag>
            </div>
            <div class="ping-row" v-if="pingResults[item.name].proxy">
              <span class="ping-label">代理</span>
              <el-tag :type="pingTagType(pingResults[item.name].proxy)" size="small">
                {{ pingText(pingResults[item.name].proxy) }}
              </el-tag>
            </div>
          </template>
          <span v-else class="ping-empty">未测速</span>
        </div>
        <div class="row-actions">
          <el-tooltip :content="item.enabled ? '禁用' : '启用'" placement="top">
            <el-switch
              :model-value="item.enabled"
              @change="(v) => toggleSite(item.name, v)"
              size="small"
            />
          </el-tooltip>
          <el-tooltip content="单独测速" placement="top">
            <el-button
              size="small"
              link
              type="primary"
              @click="pingSingle(item.name)"
              :loading="singlePinging === item.name"
            >
              <el-icon><Connection /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Sort, Refresh, Connection, Check, Rank, DCaret,
  Histogram, DataAnalysis, Files,
} from '@element-plus/icons-vue'
import {
  getSitePriorityVisualization, pingAllSitesForVisualization,
  updateSitePriorityOrder, toggleSiteEnabled,
} from '@/api'

const loading = ref(false)
const pinging = ref(false)
const saving = ref(false)
const singlePinging = ref('')

const items = ref([])
const totalMovies = ref(0)
const proxyEnabled = ref(false)

// 拖拽状态
const draggingIdx = ref(-1)
const dragOverIdx = ref(-1)
const originalOrder = ref([]) // 初始顺序，用于检测变更
const pingResults = reactive({})

const enabledCount = computed(() => items.value.filter(i => i.enabled).length)
const orderChanged = computed(() => {
  if (items.value.length !== originalOrder.value.length) return false
  return items.value.some((it, idx) => it.name !== originalOrder.value[idx])
})

const loadData = async () => {
  loading.value = true
  try {
    const data = await getSitePriorityVisualization()
    items.value = data.items || []
    totalMovies.value = data.total_movies || 0
    proxyEnabled.value = data.proxy_enabled || false
    originalOrder.value = items.value.map(i => i.name)
  } catch (e) {
    // ignore
  } finally {
    loading.value = false
  }
}

const pingAll = async () => {
  pinging.value = true
  try {
    const data = await pingAllSitesForVisualization()
    for (const r of data.results || []) {
      pingResults[r.name] = r
    }
    ElMessage.success(`已测速 ${data.results.length} 个站点`)
  } catch (e) {
    // ignore
  } finally {
    pinging.value = false
  }
}

const pingSingle = async (name) => {
  singlePinging.value = name
  try {
    // 复用 ping-all 但仅显示该站点
    const data = await pingAllSitesForVisualization()
    for (const r of data.results || []) {
      pingResults[r.name] = r
    }
  } catch (e) {
    // ignore
  } finally {
    singlePinging.value = ''
  }
}

const toggleSite = async (name, enabled) => {
  try {
    await toggleSiteEnabled(name, enabled)
    const it = items.value.find(i => i.name === name)
    if (it) it.enabled = enabled
    ElMessage.success(`${name} 已${enabled ? '启用' : '禁用'}`)
  } catch (e) {
    // ignore
  }
}

const saveOrder = async () => {
  if (!orderChanged.value) return
  saving.value = true
  try {
    const order = items.value.map(i => i.name)
    await updateSitePriorityOrder(order)
    originalOrder.value = order
    ElMessage.success(`已保存 ${order.length} 个站点的优先级顺序`)
  } catch (e) {
    // ignore
  } finally {
    saving.value = false
  }
}

// ===== 拖拽事件 =====
const onDragStart = (idx, e) => {
  draggingIdx.value = idx
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(idx))
}

const onDragOver = (idx, e) => {
  e.dataTransfer.dropEffect = 'move'
}

const onDragEnter = (idx) => {
  if (draggingIdx.value === -1 || draggingIdx.value === idx) return
  dragOverIdx.value = idx
  // 实时重排序
  const arr = [...items.value]
  const [moved] = arr.splice(draggingIdx.value, 1)
  arr.splice(idx, 0, moved)
  items.value = arr
  draggingIdx.value = idx
}

const onDrop = (idx, e) => {
  e.dataTransfer.getData('text/plain')
  draggingIdx.value = -1
  dragOverIdx.value = -1
}

const onDragEnd = () => {
  draggingIdx.value = -1
  dragOverIdx.value = -1
}

// ===== 工具 =====
const pingTagType = (r) => {
  if (!r) return 'info'
  if (r.success === false) return 'danger'
  if (r.time_ms && r.time_ms > 3000) return 'warning'
  return 'success'
}

const pingText = (r) => {
  if (!r) return '-'
  if (r.success === false) return `失败 ${r.time_ms || 0}ms`
  return `${r.status_code || 'OK'} · ${r.time_ms}ms`
}

onMounted(loadData)
</script>

<style scoped>
.site-priority-page {
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

.summary-card,
.list-card {
  margin-bottom: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.empty-state {
  padding: 40px 0;
}

.site-row {
  display: grid;
  grid-template-columns: 32px 80px 1fr 200px 100px;
  gap: 12px;
  align-items: center;
  padding: 12px 8px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
  cursor: move;
  transition: background 0.15s, transform 0.15s;
}

.site-row:hover {
  background: #f5f7fa;
}

.site-row.row-dragging {
  opacity: 0.5;
  background: #ecf5ff;
}

.site-row.row-disabled {
  opacity: 0.55;
  background: #fafafa;
}

.row-handle {
  color: #c0c4cc;
  text-align: center;
  font-size: 18px;
  cursor: grab;
}

.row-handle:active {
  cursor: grabbing;
}

.row-priority {
  text-align: center;
}

.priority-num {
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.row-info {
  min-width: 0;
}

.row-name {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.name-text {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.row-url {
  font-size: 12px;
  margin-bottom: 4px;
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 11px;
  color: #909399;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.row-ping {
  font-size: 12px;
}

.ping-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.ping-label {
  color: #909399;
  font-size: 11px;
}

.ping-empty {
  color: #c0c4cc;
  font-size: 11px;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}

:deep(.dark) .site-row {
  background: #2c2c2c;
  border-bottom-color: #3a3a3a;
}

:deep(.dark) .site-row:hover {
  background: #333;
}

:deep(.dark) .site-row.row-disabled {
  background: #252525;
}

:deep(.dark) .name-text {
  color: #e0e0e0;
}
</style>
