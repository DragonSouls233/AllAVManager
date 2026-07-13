<template>
  <div class="tiers-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Trophy /></el-icon>
          分级治理中心
        </h2>
        <div class="page-subtitle">参考 JATLAS 的"空间预算"理念 · 用分级管理收藏膨胀</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadDashboard" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button type="primary" @click="openConfig">
          <el-icon><Setting /></el-icon> 分级配置
        </el-button>
      </div>
    </div>

    <!-- 仪表盘卡片 -->
    <div class="tier-cards" v-loading="loading">
      <div
        v-for="t in dashboard.tiers"
        :key="t.tier"
        class="tier-card"
        :class="['tier-' + t.tier.toLowerCase(), 'risk-' + t.risk_level]"
        :style="{ '--tier-color': t.color }"
      >
        <div class="tier-header">
          <div class="tier-badge" :style="{ background: t.color }">{{ t.tier }}</div>
          <div class="tier-info">
            <div class="tier-name">{{ t.name }}</div>
            <div class="tier-meta">
              <span>{{ t.actor_count }} 位演员</span>
              <span>·</span>
              <span>{{ t.total_movies }} 部影片</span>
            </div>
          </div>
          <div class="tier-risk-tag" v-if="t.risk_level !== 'normal'">
            <el-tag :type="t.risk_level === 'overflow' ? 'danger' : 'warning'" size="small" effect="dark">
              {{ t.risk_level === 'overflow' ? '超量' : '预警' }}
            </el-tag>
          </div>
        </div>
        <div class="tier-progress">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: Math.min(t.risk_percent, 100) + '%' }"></div>
          </div>
          <div class="progress-text">
            <span>{{ t.actor_count }} / {{ t.max_count > 0 ? t.max_count : '∞' }}</span>
            <span v-if="t.max_count > 0">{{ t.risk_percent }}%</span>
          </div>
        </div>
      </div>

      <!-- 未分级卡片 -->
      <div class="tier-card tier-unassigned" v-if="dashboard.unassigned_count > 0">
        <div class="tier-header">
          <div class="tier-badge" style="background: #888">?</div>
          <div class="tier-info">
            <div class="tier-name">未分级</div>
            <div class="tier-meta">
              <span>{{ dashboard.unassigned_count }} 位演员待分级</span>
            </div>
          </div>
        </div>
        <el-button text type="primary" @click="$router.push('/actors')">前往分级</el-button>
      </div>
    </div>

    <!-- 风险预警列表 -->
    <el-card shadow="never" class="risk-card">
      <template #header>
        <div class="card-title">
          <el-icon><Warning /></el-icon>
          风险预警
          <el-tag v-if="riskData.total > 0" type="danger" size="small" effect="dark">
            {{ riskData.total }}
          </el-tag>
          <span v-else class="card-subtitle">暂无风险</span>
        </div>
      </template>

      <el-table :data="riskData.items" v-loading="riskLoading" stripe>
        <el-table-column label="演员" min-width="160">
          <template #default="{ row }">
            <div class="actor-cell">
              <el-avatar :size="32" :src="getActorAvatarUrlById(row.actor_id)">
                {{ row.actor_name?.slice(0, 1) }}
              </el-avatar>
              <span>{{ row.actor_name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="分级" width="100">
          <template #default="{ row }">
            <el-tag :style="{ background: row.color, color: '#fff', border: 'none' }" size="small">
              {{ row.tier }} · {{ row.tier_name }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="影片数" width="100" prop="movie_count" />
        <el-table-column label="上限" width="100">
          <template #default="{ row }">{{ row.max_count > 0 ? row.max_count : '∞' }}</template>
        </el-table-column>
        <el-table-column label="使用率" width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.min(row.risk_percent, 100)"
              :color="row.risk_level === 'overflow' ? '#f56c6c' : row.risk_level === 'warning' ? '#e6a23c' : '#67c23a'"
              :stroke-width="14"
              :text-inside="true"
              :format="() => row.risk_percent + '%'"
            />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.risk_level === 'overflow' ? 'danger' : 'warning'" size="small" effect="dark">
              {{ row.risk_level === 'overflow' ? '超量' : '预警' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button text size="small" @click="$router.push(`/actors/${row.actor_id}`)">查看</el-button>
            <el-button text size="small" type="primary" @click="openChangeTier(row)">调整分级</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 资产变化日志 -->
    <el-card shadow="never" class="logs-card">
      <template #header>
        <div class="card-title">
          <el-icon><Document /></el-icon>
          资产变化日志
          <div class="header-actions">
            <el-select v-model="logFilter.entity_type" placeholder="全部类型" clearable size="small" style="width: 110px">
              <el-option label="影片" value="movie" />
              <el-option label="演员" value="actor" />
              <el-option label="标签" value="tag" />
              <el-option label="厂商" value="studio" />
              <el-option label="系列" value="series" />
            </el-select>
            <el-select v-model="logFilter.change_type" placeholder="全部变化" clearable size="small" style="width: 130px">
              <el-option label="新增" value="added" />
              <el-option label="移除" value="removed" />
              <el-option label="分级变更" value="tier_changed" />
              <el-option label="评分变更" value="rating_changed" />
              <el-option label="刮削" value="scraped" />
            </el-select>
            <el-button size="small" @click="loadLogs">查询</el-button>
            <el-button size="small" type="warning" @click="clearLogs">清除30天前</el-button>
          </div>
        </div>
      </template>

      <el-timeline>
        <el-timeline-item
          v-for="log in logs.items"
          :key="log.id"
          :timestamp="formatTime(log.created_at)"
          :type="getLogType(log.change_type)"
          :hollow="log.change_type === 'removed'"
        >
          <div class="log-item">
            <el-tag size="small" :type="getLogTagType(log.change_type)">{{ getChangeText(log.change_type) }}</el-tag>
            <span class="log-entity">{{ log.entity_name || `#${log.entity_id}` }}</span>
            <span class="log-desc" v-if="log.description">{{ log.description }}</span>
            <span class="log-value" v-if="log.old_value || log.new_value">
              <span v-if="log.old_value" class="old">{{ log.old_value }}</span>
              <span v-if="log.old_value && log.new_value">→</span>
              <span v-if="log.new_value" class="new">{{ log.new_value }}</span>
            </span>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!logs.items.length && !logLoading" description="暂无日志" />
    </el-card>

    <!-- 分级配置对话框 -->
    <el-dialog v-model="configDialogVisible" title="分级档位配置" width="640px">
      <el-alert type="info" :closable="false" style="margin-bottom: 16px">
        每个档位的"上限"表示该档位最多容纳的演员数量。0 表示无上限。接近上限 80% 时预警，达到 100% 时标记超量。
      </el-alert>
      <el-table :data="configEdit" border>
        <el-table-column label="档位" width="80" prop="tier" />
        <el-table-column label="名称" width="120">
          <template #default="{ row }">
            <el-input v-model="row.name" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="上限" width="100">
          <template #default="{ row }">
            <el-input-number v-model="row.max_count" :min="0" :step="10" size="small" controls-position="right" style="width: 90px" />
          </template>
        </el-table-column>
        <el-table-column label="颜色" width="100">
          <template #default="{ row }">
            <el-color-picker v-model="row.color" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="排序" width="80">
          <template #default="{ row }">
            <el-input-number v-model="row.sort_order" :min="1" :max="99" size="small" controls-position="right" style="width: 70px" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="configDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveConfig" :loading="configSaving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 调整分级对话框 -->
    <el-dialog v-model="changeTierDialog.visible" title="调整演员分级" width="420px">
      <div class="change-tier-content" v-if="changeTierDialog.actor">
        <el-avatar :size="60" :src="getActorAvatarUrlById(changeTierDialog.actor.actor_id)">
          {{ changeTierDialog.actor.actor_name?.slice(0, 1) }}
        </el-avatar>
        <div class="actor-info">
          <div class="name">{{ changeTierDialog.actor.actor_name }}</div>
          <div class="meta">当前: {{ changeTierDialog.actor.tier }} · 影片: {{ changeTierDialog.actor.movie_count }}</div>
        </div>
      </div>
      <el-form label-width="80px" style="margin-top: 16px">
        <el-form-item label="新分级">
          <el-radio-group v-model="changeTierDialog.newTier">
            <el-radio-button v-for="t in dashboard.tiers" :key="t.tier" :value="t.tier">
              {{ t.tier }} · {{ t.name }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="changeTierDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="confirmChangeTier" :loading="changeTierDialog.saving">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Trophy, Refresh, Setting, Warning, Document } from '@element-plus/icons-vue'
import {
  getTierDashboard, getTierRisk, getTierConfig, updateTierConfig,
  getChangeLogs, clearChangeLogs, setActorTier
} from '@/api'
import { getActorAvatarUrlById } from '@/utils/media'

const loading = ref(false)
const riskLoading = ref(false)
const logLoading = ref(false)
const configSaving = ref(false)

const dashboard = ref({ tiers: [], unassigned_count: 0 })
const riskData = ref({ items: [], total: 0, warning_count: 0, overflow_count: 0 })
const logs = ref({ items: [], total: 0 })

const logFilter = reactive({
  entity_type: '',
  change_type: '',
})

// 配置编辑
const configDialogVisible = ref(false)
const configEdit = ref([])

// 调整分级
const changeTierDialog = reactive({
  visible: false,
  actor: null,
  newTier: '',
  saving: false,
})

const loadDashboard = async () => {
  loading.value = true
  try {
    const [d, r] = await Promise.all([getTierDashboard(), getTierRisk()])
    dashboard.value = d
    riskData.value = r
  } catch (e) {
    ElMessage.error('加载仪表盘失败')
  } finally {
    loading.value = false
  }
}

const loadLogs = async () => {
  logLoading.value = true
  try {
    const params = {}
    if (logFilter.entity_type) params.entity_type = logFilter.entity_type
    if (logFilter.change_type) params.change_type = logFilter.change_type
    logs.value = await getChangeLogs(params)
  } catch (e) {
    ElMessage.error('加载日志失败')
  } finally {
    logLoading.value = false
  }
}

const openConfig = async () => {
  const res = await getTierConfig()
  configEdit.value = JSON.parse(JSON.stringify(res.items))
  configDialogVisible.value = true
}

const saveConfig = async () => {
  configSaving.value = true
  try {
    await updateTierConfig({ items: configEdit.value })
    ElMessage.success('配置已保存')
    configDialogVisible.value = false
    loadDashboard()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    configSaving.value = false
  }
}

const openChangeTier = (row) => {
  changeTierDialog.actor = row
  changeTierDialog.newTier = row.tier
  changeTierDialog.visible = true
}

const confirmChangeTier = async () => {
  if (!changeTierDialog.actor || !changeTierDialog.newTier) return
  changeTierDialog.saving = true
  try {
    await setActorTier(changeTierDialog.actor.actor_id, {
      tier: changeTierDialog.newTier,
    })
    ElMessage.success('分级已调整')
    changeTierDialog.visible = false
    loadDashboard()
  } catch (e) {
    ElMessage.error('调整失败')
  } finally {
    changeTierDialog.saving = false
  }
}

const clearLogs = async () => {
  try {
    await ElMessageBox.confirm('确认清除 30 天前的日志？', '提示', { type: 'warning' })
    const res = await clearChangeLogs(30)
    ElMessage.success(`已清除 ${res.deleted} 条日志`)
    loadLogs()
  } catch {}
}

const formatTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`
}

const getLogType = (type) => {
  const map = { added: 'success', removed: 'danger', tier_changed: 'warning', rating_changed: 'primary', scraped: 'info' }
  return map[type] || 'info'
}

const getLogTagType = (type) => {
  const map = { added: 'success', removed: 'danger', tier_changed: 'warning', rating_changed: '', scraped: 'info' }
  return map[type] || 'info'
}

const getChangeText = (type) => {
  const map = { added: '新增', removed: '移除', tier_changed: '分级', rating_changed: '评分', scraped: '刮削' }
  return map[type] || type
}

onMounted(() => {
  loadDashboard()
  loadLogs()
})
</script>

<style scoped>
.tiers-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.page-header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
}

.page-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
}

.page-header-actions {
  display: flex;
  gap: 8px;
}

/* Tier 卡片 */
.tier-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.tier-card {
  background: var(--bg-card);
  border-radius: 12px;
  padding: 16px;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border-light);
  border-left: 4px solid var(--tier-color, #888);
  transition: transform 0.2s, box-shadow 0.2s;
}

.tier-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.tier-card.risk-warning {
  border-left-color: #e6a23c;
}

.tier-card.risk-overflow {
  border-left-color: #f56c6c;
  background: rgba(245, 108, 108, 0.05);
}

.tier-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.tier-badge {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 18px;
  flex-shrink: 0;
}

.tier-info {
  flex: 1;
  min-width: 0;
}

.tier-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.tier-meta {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
  display: flex;
  gap: 4px;
}

.tier-progress {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.progress-bar {
  height: 8px;
  background: var(--border-light);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--tier-color, #888);
  transition: width 0.3s;
}

.risk-warning .progress-fill {
  background: #e6a23c;
}

.risk-overflow .progress-fill {
  background: #f56c6c;
}

.progress-text {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-secondary);
}

.tier-unassigned {
  border-left-color: #888;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

/* 卡片通用 */
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.card-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: normal;
}

.header-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

/* 风险表格 */
.actor-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 日志 */
.log-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.log-entity {
  font-weight: 600;
  color: var(--text-primary);
}

.log-desc {
  color: var(--text-secondary);
  font-size: 13px;
}

.log-value {
  display: flex;
  gap: 4px;
  align-items: center;
  font-size: 13px;
}

.log-value .old {
  color: var(--text-secondary);
  text-decoration: line-through;
}

.log-value .new {
  color: var(--primary-color);
  font-weight: 600;
}

/* 调整分级对话框 */
.change-tier-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.actor-info .name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.actor-info .meta {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}
</style>
