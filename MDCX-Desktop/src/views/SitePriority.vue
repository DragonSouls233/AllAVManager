<template>
  <div class="site-priority-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Sort /></el-icon>
          站点优先级
        </h2>
        <div class="page-subtitle">按模块分组 · 拖拽排序 · 一键测速 · 启用/禁用</div>
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

    <el-card shadow="never" class="summary-card">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="站点总数">{{ items.length }}</el-descriptions-item>
        <el-descriptions-item label="已启用">{{ enabledCount }} / {{ items.length }}</el-descriptions-item>
        <el-descriptions-item label="总刮削数">{{ totalMovies }}</el-descriptions-item>
        <el-descriptions-item label="代理">{{ proxyEnabled ? '已启用' : '未启用' }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="orderChanged" type="warning" :closable="false" show-icon
        title="顺序已变更，请点击「保存顺序」按钮以生效" style="margin-top:10px" />
    </el-card>

    <div v-if="!loading">
      <el-card v-if="javList.length" shadow="never" class="group-card" style="border-left:4px solid #409eff">
        <template #header>
          <div class="group-header">
            <span class="group-title"><el-tag type="primary" effect="dark">JAV</el-tag> 有码 · 无码 · FC2</span>
            <span class="group-desc"><el-tag size="small" type="warning">JavBus 第一序列</el-tag></span>
          </div>
        </template>
        <SiteRowList :items="javList" :ping-results="pingResults" :single-pinging="singlePinging"
          @toggle="toggleSite" @ping-single="pingSingle" />
      </el-card>

      <el-card v-if="chineseList.length" shadow="never" class="group-card" style="border-left:4px solid #67c23a">
        <template #header>
          <div class="group-header">
            <span class="group-title"><el-tag type="success" effect="dark">国产</el-tag> 独立模块</span>
          </div>
        </template>
        <SiteRowList :items="chineseList" :ping-results="pingResults" :single-pinging="singlePinging"
          @toggle="toggleSite" @ping-single="pingSingle" />
      </el-card>

      <el-card v-if="westernList.length" shadow="never" class="group-card" style="border-left:4px solid #e6a23c">
        <template #header>
          <div class="group-header">
            <span class="group-title"><el-tag type="warning" effect="dark">欧美 · Pornhub</el-tag> 共用刮削</span>
          </div>
        </template>
        <SiteRowList :items="westernList" :ping-results="pingResults" :single-pinging="singlePinging"
          @toggle="toggleSite" @ping-single="pingSingle" />
      </el-card>

      <el-card v-if="otherList.length" shadow="never" class="group-card" style="border-left:4px solid #909399">
        <template #header>
          <div class="group-header">
            <span class="group-title"><el-tag type="info" effect="dark">其他</el-tag> 通用站点</span>
          </div>
        </template>
        <SiteRowList :items="otherList" :ping-results="pingResults" :single-pinging="singlePinging"
          @toggle="toggleSite" @ping-single="pingSingle" />
      </el-card>

      <el-empty v-if="!items.length" description="暂无站点" />
    </div>
    <div v-else v-loading="loading" style="padding:80px 0" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Sort, Refresh, Connection, Check } from '@element-plus/icons-vue'
import { getSitePriorityVisualization, pingAllSitesForVisualization, updateSitePriorityOrder, toggleSiteEnabled } from '@/api'
import SiteRowList from '@/components/SiteRowList.vue'

const loading = ref(false)
const pinging = ref(false)
const saving = ref(false)
const singlePinging = ref('')
const items = ref([])
const totalMovies = ref(0)
const proxyEnabled = ref(false)
const originalOrder = ref([])
const pingResults = reactive({})

const enabledCount = computed(() => items.value.filter(i => i.enabled).length)
const orderChanged = computed(() => {
  if (items.value.length !== originalOrder.value.length) return false
  return items.value.some((it, idx) => it.name !== originalOrder.value[idx])
})

function hasType(item, types) {
  return (item.supported_types || []).some(t => types.includes(t))
}

const javList = computed(() => items.value.filter(i => hasType(i, ['jav', 'jav_uncensored', 'fc2'])))
const chineseList = computed(() => items.value.filter(i => hasType(i, ['chinese']) && !hasType(i, ['jav', 'jav_uncensored', 'fc2'])))
const westernList = computed(() => items.value.filter(i => hasType(i, ['western', 'pornhub']) && !hasType(i, ['jav', 'jav_uncensored', 'fc2', 'chinese'])))
const otherList = computed(() => {
  return items.value.filter(i =>
    !hasType(i, ['jav', 'jav_uncensored', 'fc2', 'chinese', 'western', 'pornhub'])
  )
})

const loadData = async () => {
  loading.value = true
  try {
    const data = await getSitePriorityVisualization()
    items.value = data.items || []
    totalMovies.value = data.total_movies || 0
    proxyEnabled.value = data.proxy_enabled || false
    originalOrder.value = items.value.map(i => i.name)
  } catch (e) { /* ignore */ }
  finally { loading.value = false }
}

const pingAll = async () => {
  pinging.value = true
  try {
    const data = await pingAllSitesForVisualization()
    for (const r of data.results || []) pingResults[r.name] = r
    ElMessage.success(`已测速 ${data.results.length} 个站点`)
  } catch (e) { /* ignore */ }
  finally { pinging.value = false }
}

const pingSingle = async (name) => {
  singlePinging.value = name
  try {
    const data = await pingAllSitesForVisualization()
    for (const r of data.results || []) pingResults[r.name] = r
  } catch (e) { /* ignore */ }
  finally { singlePinging.value = '' }
}

const toggleSite = async (name, enabled) => {
  try {
    await toggleSiteEnabled(name, enabled)
    const it = items.value.find(i => i.name === name)
    if (it) it.enabled = enabled
    ElMessage.success(`${name} 已${enabled ? '启用' : '禁用'}`)
  } catch (e) { /* ignore */ }
}

const saveOrder = async () => {
  if (!orderChanged.value) return
  saving.value = true
  try {
    const order = items.value.map(i => i.name)
    await updateSitePriorityOrder(order)
    originalOrder.value = order
    ElMessage.success(`已保存 ${order.length} 个站点的优先级顺序`)
  } catch (e) { /* ignore */ }
  finally { saving.value = false }
}

onMounted(loadData)
</script>

<style scoped>
.site-priority-page { padding: 4px; }
.page-header { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; }
.page-title { margin:0 0 4px 0; font-size:20px; display:flex; align-items:center; gap:8px; }
.page-subtitle { font-size:12px; color:#909399; }
.page-header-actions { display:flex; gap:8px; }
.summary-card, .group-card { margin-bottom:16px; }
.group-header { display:flex; align-items:center; gap:12px; }
.group-title { font-weight:700; font-size:16px; display:flex; align-items:center; gap:8px; }
.group-desc { font-size:12px; color:#909399; }
</style>
