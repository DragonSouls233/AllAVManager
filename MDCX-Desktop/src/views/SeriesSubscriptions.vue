<template>
  <div class="page series-subs-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Bell /></el-icon>
          系列订阅
        </h2>
        <span class="page-subtitle">订阅系列后,有新片发布时自动通知或下载</span>
      </div>
      <div class="page-header-actions">
        <el-button :loading="checking" @click="handleCheckAll">
          <el-icon><Refresh /></el-icon> 检查新片
        </el-button>
        <el-button type="primary" @click="openSubscribeDialog">
          <el-icon><Plus /></el-icon> 订阅新系列
        </el-button>
      </div>
    </div>

    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="24" :sm="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num primary">{{ subscriptions.length }}</span>
            <span class="stat-label">订阅总数</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num success">{{ notifyCount }}</span>
            <span class="stat-label">已启用通知</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num warning">{{ newMovieTotal }}</span>
            <span class="stat-label">新片总数</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 订阅列表 -->
    <el-card shadow="never" class="table-card">
      <template #header>
        <div class="card-header-bar">
          <div class="card-header-title">
            <el-icon><List /></el-icon>
            订阅列表
          </div>
          <div class="batch-bar" v-if="selectedRows.length">
            <span class="batch-text">已选 {{ selectedRows.length }} 项</span>
            <el-button size="small" type="success" :loading="batchLoading" @click="handleBatchNotify(true)">
              批量启用通知
            </el-button>
            <el-button size="small" :loading="batchLoading" @click="handleBatchNotify(false)">
              批量禁用通知
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="subscriptions"
        v-loading="loading"
        stripe
        @selection-change="onSelectionChange"
        empty-text="暂无订阅,点击右上角订阅新系列"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column prop="series_name" label="系列名称" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="series-name">{{ row.series_name || `系列 #${row.series_id}` }}</span>
            <span class="series-id">#{{ row.series_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="subscribed_at" label="订阅时间" width="170">
          <template #default="{ row }">{{ formatDate(row.subscribed_at) }}</template>
        </el-table-column>
        <el-table-column label="通知" width="100" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="!!row.notify_new_movie"
              @change="val => toggleNotify(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="自动下载" width="110" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="!!row.auto_download"
              @change="val => toggleAutoDownload(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="preferred_quality" label="偏好质量" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="qualityTagType(row.preferred_quality)">
              {{ row.preferred_quality || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="新片" width="90" align="center">
          <template #default="{ row }">
            <el-badge :value="row.last_movie_count || 0" :max="99" :hidden="!row.last_movie_count">
              <el-button
                text
                size="small"
                :disabled="!row.last_movie_count"
                @click="openNewMoviesDrawer(row)"
              >
                <el-icon><View /></el-icon> 查看
              </el-button>
            </el-badge>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button text size="small" type="danger" @click="handleUnsubscribe(row)">
              <el-icon><Delete /></el-icon> 取消订阅
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑订阅对话框 -->
    <el-dialog
      v-model="showSubscribeDialog"
      :title="dialogMode === 'create' ? '订阅系列' : '编辑订阅'"
      width="520px"
    >
      <el-form :model="subscribeForm" label-width="100px">
        <el-form-item label="系列搜索">
          <el-select
            v-model="subscribeForm.series_id"
            filterable
            remote
            reserve-keyword
            clearable
            placeholder="输入系列名称搜索"
            :remote-method="searchSeries"
            :loading="searching"
            @change="onSeriesPicked"
          >
            <el-option
              v-for="s in seriesOptions"
              :key="s.id"
              :label="s.name"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="通知新片">
          <el-switch v-model="subscribeForm.notify_new_movie" />
        </el-form-item>
        <el-form-item label="自动下载">
          <el-switch v-model="subscribeForm.auto_download" />
        </el-form-item>
        <el-form-item label="偏好质量">
          <el-select v-model="subscribeForm.preferred_quality" style="width: 100%">
            <el-option label="4K" value="4k" />
            <el-option label="1080p" value="1080p" />
            <el-option label="720p" value="720p" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSubscribeDialog = false">取消</el-button>
        <el-button type="primary" :loading="subscribing" @click="handleSubscribe">
          {{ dialogMode === 'create' ? '订阅' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 新片预览抽屉 -->
    <el-drawer
      v-model="showNewMoviesDrawer"
      :title="`${currentSeriesName} - 新片列表`"
      direction="rtl"
      size="480px"
    >
      <div v-loading="loadingNewMovies">
        <div v-if="newMovies.length" class="new-movie-list">
          <div v-for="m in newMovies" :key="m.id" class="new-movie-item" @click="goToMovie(m.id)">
            <div class="new-movie-cover">
              <img v-if="m.cover_url" :src="m.cover_url" :alt="m.code" />
              <div v-else class="cover-fallback">
                <el-icon><Picture /></el-icon>
              </div>
            </div>
            <div class="new-movie-info">
              <div class="new-movie-code">{{ m.code }}</div>
              <div class="new-movie-title">{{ m.title || '未命名' }}</div>
              <div class="new-movie-meta">
                <el-tag size="small" effect="plain">{{ m.release_date || '未知日期' }}</el-tag>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无新片" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Bell, Refresh, Plus, List, View, Delete, Picture
} from '@element-plus/icons-vue'
import {
  getSeriesSubscriptions, subscribeSeries, unsubscribeSeries,
  checkSeriesSubscriptions, getSeriesSubscriptionNewMovies
} from '@/api'
import { getSeries } from '@/api'

const router = useRouter()

const loading = ref(false)
const subscribing = ref(false)
const checking = ref(false)
const batchLoading = ref(false)
const loadingNewMovies = ref(false)
const searching = ref(false)

const subscriptions = ref([])
const selectedRows = ref([])

const showSubscribeDialog = ref(false)
const dialogMode = ref('create')
const subscribeForm = ref({
  series_id: null,
  series_name: '',
  notify_new_movie: true,
  auto_download: false,
  preferred_quality: '1080p'
})

const seriesOptions = ref([])

const showNewMoviesDrawer = ref(false)
const currentSeriesName = ref('')
const newMovies = ref([])

const notifyCount = computed(() => subscriptions.value.filter(s => s.notify_new_movie).length)
const newMovieTotal = computed(() =>
  subscriptions.value.reduce((sum, s) => sum + (s.last_movie_count || 0), 0)
)

function formatDate(d) {
  if (!d) return '-'
  const date = new Date(d)
  if (Number.isNaN(date.getTime())) return d
  return date.toLocaleString('zh-CN', { hour12: false })
}

function qualityTagType(q) {
  if (q === '4k') return 'danger'
  if (q === '1080p') return 'success'
  if (q === '720p') return 'info'
  return ''
}

function onSelectionChange(rows) {
  selectedRows.value = rows
}

async function loadSubscriptions() {
  loading.value = true
  try {
    const res = await getSeriesSubscriptions()
    subscriptions.value = res.items || res || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function searchSeries(query) {
  if (!query) {
    seriesOptions.value = []
    return
  }
  searching.value = true
  try {
    const res = await getSeries({ keyword: query, limit: 20 })
    seriesOptions.value = res.items || res || []
  } catch (e) {
    console.error(e)
  } finally {
    searching.value = false
  }
}

function onSeriesPicked(id) {
  const picked = seriesOptions.value.find(s => s.id === id)
  if (picked) subscribeForm.value.series_name = picked.name
}

function openSubscribeDialog() {
  dialogMode.value = 'create'
  Object.assign(subscribeForm.value, {
    series_id: null,
    series_name: '',
    notify_new_movie: true,
    auto_download: false,
    preferred_quality: '1080p'
  })
  seriesOptions.value = []
  showSubscribeDialog.value = true
}

async function handleSubscribe() {
  if (!subscribeForm.value.series_id) {
    ElMessage.warning('请选择要订阅的系列')
    return
  }
  subscribing.value = true
  try {
    await subscribeSeries({
      ...subscribeForm.value,
      series_id: parseInt(subscribeForm.value.series_id)
    })
    ElMessage.success('订阅成功')
    showSubscribeDialog.value = false
    loadSubscriptions()
  } catch (e) {
    console.error(e)
  } finally {
    subscribing.value = false
  }
}

async function handleUnsubscribe(row) {
  try {
    await ElMessageBox.confirm(
      `确认取消订阅「${row.series_name || row.series_id}」?`,
      '提示',
      { type: 'warning' }
    )
    await unsubscribeSeries(row.series_id)
    ElMessage.success('已取消订阅')
    loadSubscriptions()
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

async function toggleNotify(row, val) {
  row.notify_new_movie = val
  try {
    await subscribeSeries({
      series_id: row.series_id,
      series_name: row.series_name,
      notify_new_movie: val,
      auto_download: row.auto_download,
      preferred_quality: row.preferred_quality
    })
    ElMessage.success(val ? '已启用通知' : '已禁用通知')
  } catch (e) {
    row.notify_new_movie = !val
    console.error(e)
  }
}

async function toggleAutoDownload(row, val) {
  row.auto_download = val
  try {
    await subscribeSeries({
      series_id: row.series_id,
      series_name: row.series_name,
      notify_new_movie: row.notify_new_movie,
      auto_download: val,
      preferred_quality: row.preferred_quality
    })
    ElMessage.success(val ? '已启用自动下载' : '已禁用自动下载')
  } catch (e) {
    row.auto_download = !val
    console.error(e)
  }
}

async function handleBatchNotify(enable) {
  if (!selectedRows.value.length) return
  batchLoading.value = true
  try {
    await Promise.all(selectedRows.value.map(row =>
      subscribeSeries({
        series_id: row.series_id,
        series_name: row.series_name,
        notify_new_movie: enable,
        auto_download: row.auto_download,
        preferred_quality: row.preferred_quality
      })
    ))
    ElMessage.success(`已${enable ? '启用' : '禁用'} ${selectedRows.value.length} 项通知`)
    loadSubscriptions()
  } catch (e) {
    console.error(e)
  } finally {
    batchLoading.value = false
  }
}

async function handleCheckAll() {
  checking.value = true
  try {
    await checkSeriesSubscriptions()
    ElMessage.success('已触发检查,新片数量稍后更新')
    setTimeout(loadSubscriptions, 1500)
  } catch (e) {
    console.error(e)
  } finally {
    checking.value = false
  }
}

async function openNewMoviesDrawer(row) {
  currentSeriesName.value = row.series_name || `系列 #${row.series_id}`
  showNewMoviesDrawer.value = true
  loadingNewMovies.value = true
  newMovies.value = []
  try {
    const res = await getSeriesSubscriptionNewMovies({ series_id: row.series_id })
    newMovies.value = res.items || res || []
  } catch (e) {
    console.error(e)
  } finally {
    loadingNewMovies.value = false
  }
}

function goToMovie(id) {
  router.push(`/movie/${id}`)
}

onMounted(loadSubscriptions)
</script>

<style scoped>
.series-subs-page {
  gap: var(--gap-md);
}

.card-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.card-header-title {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-weight: 600;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.batch-text {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.series-name {
  font-weight: 500;
  color: var(--text-primary);
}

.series-id {
  margin-left: var(--gap-sm);
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

.new-movie-list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap-xs);
}

.new-movie-item {
  display: flex;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  border: 1px solid var(--border-light);
}

.new-movie-item:hover {
  background: var(--bg-page);
  border-color: var(--primary-light);
}

.new-movie-cover {
  width: 64px;
  height: 90px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--bg-page);
  flex-shrink: 0;
}

.new-movie-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder);
}

.new-movie-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.new-movie-code {
  font-weight: 600;
  font-size: var(--font-size-sm);
  color: var(--primary-color);
}

.new-movie-title {
  font-size: var(--font-size-sm);
  color: var(--text-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.new-movie-meta {
  margin-top: auto;
}

@media (max-width: 640px) {
  .batch-bar {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
