<template>
  <div class="view-status-page">
    <h2>三态视频标记</h2>
    <p class="page-desc">浏览过 / 已观看 / 想看 三态视频状态管理，支持批量标记和按状态筛选。</p>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card stat-browsed">
          <div class="stat-content">
            <div class="stat-icon"><el-icon><View /></el-icon></div>
            <div>
              <div class="stat-label">浏览过</div>
              <div class="stat-value">{{ stats.browsed }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card stat-watched">
          <div class="stat-content">
            <div class="stat-icon"><CircleCheck /></div>
            <div>
              <div class="stat-label">已观看</div>
              <div class="stat-value">{{ stats.watched }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card stat-wanted">
          <div class="stat-content">
            <div class="stat-icon"><StarFilled /></div>
            <div>
              <div class="stat-label">想看</div>
              <div class="stat-value">{{ stats.wanted }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card stat-unmarked">
          <div class="stat-content">
            <div class="stat-icon"><Hide /></div>
            <div>
              <div class="stat-label">未标记</div>
              <div class="stat-value">{{ stats.unmarked }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 状态筛选 -->
    <el-card shadow="never" class="filter-card">
      <el-radio-group v-model="currentStatus" @change="loadMovies">
        <el-radio-button label="browsed">浏览过 ({{ stats.browsed }})</el-radio-button>
        <el-radio-button label="watched">已观看 ({{ stats.watched }})</el-radio-button>
        <el-radio-button label="wanted">想看 ({{ stats.wanted }})</el-radio-button>
      </el-radio-group>
      <el-button type="primary" :icon="Refresh" @click="loadAll" style="margin-left: 12px">刷新</el-button>
    </el-card>

    <!-- 影片列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="movies" v-loading="loading" stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column label="封面" width="80">
          <template #default="{ row }">
            <el-image
              v-if="row.cover_url"
              :src="row.cover_url"
              :preview-src="row.cover_url"
              fit="cover"
              style="width: 50px; height: 70px; border-radius: 4px"
              preview-teleported
            />
            <div v-else class="no-cover">无封面</div>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="番号" width="140" />
        <el-table-column prop="title" label="标题" min-width="280" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.view_status)" effect="dark">
              {{ statusLabel(row.view_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最后播放" width="170">
          <template #default="{ row }">
            {{ row.last_played_at ? formatTime(row.last_played_at) : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="setStatus(row.id, 'browsed')">浏览</el-button>
            <el-button size="small" type="success" @click="setStatus(row.id, 'watched')">已看</el-button>
            <el-button size="small" type="warning" @click="setStatus(row.id, 'wanted')">想看</el-button>
            <el-button size="small" type="info" @click="setStatus(row.id, null)">清除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 批量操作 -->
      <div class="batch-bar" v-if="selected.length > 0">
        <span>已选 {{ selected.length }} 部</span>
        <el-button size="small" @click="batchSet('browsed')">批量设为浏览</el-button>
        <el-button size="small" type="success" @click="batchSet('watched')">批量设为已看</el-button>
        <el-button size="small" type="warning" @click="batchSet('wanted')">批量设为想看</el-button>
        <el-button size="small" type="info" @click="batchSet(null)">批量清除</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { View, Hide, StarFilled, CircleCheck, Refresh } from '@element-plus/icons-vue'
import {
  getViewStatusStats, listMoviesByViewStatus, setMovieViewStatus, batchSetViewStatus
} from '@/api'

const stats = reactive({ browsed: 0, watched: 0, wanted: 0, unmarked: 0 })
const currentStatus = ref('wanted')
const movies = ref([])
const loading = ref(false)
const selected = ref([])

const statusLabel = (s) => ({
  browsed: '浏览过', watched: '已观看', wanted: '想看'
}[s] || '未标记')

const statusTagType = (s) => ({
  browsed: 'info', watched: 'success', wanted: 'warning'
}[s] || '')

const formatTime = (iso) => new Date(iso).toLocaleString('zh-CN')

const loadStats = async () => {
  try {
    const data = await getViewStatusStats()
    Object.assign(stats, data)
  } catch (e) { /* 拦截器已报错 */ }
}

const loadMovies = async () => {
  loading.value = true
  try {
    const data = await listMoviesByViewStatus(currentStatus.value, 200, 0)
    movies.value = data.items || []
  } catch (e) { /* */ } finally {
    loading.value = false
  }
}

const loadAll = async () => {
  await Promise.all([loadStats(), loadMovies()])
}

const setStatus = async (movieId, status) => {
  try {
    await setMovieViewStatus(movieId, status)
    ElMessage.success(`已${status ? '设置为 ' + statusLabel(status) : '清除标记'}`)
    await loadAll()
  } catch (e) { /* */ }
}

const onSelectionChange = (rows) => { selected.value = rows }

const batchSet = async (status) => {
  if (selected.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确认将选中的 ${selected.value.length} 部影片${status ? '设置为 ' + statusLabel(status) : '清除标记'}？`,
      '批量操作确认', { type: 'warning' }
    )
    const ids = selected.value.map(m => m.id)
    const res = await batchSetViewStatus(ids, status)
    ElMessage.success(`已更新 ${res.updated} 部`)
    await loadAll()
  } catch (e) { /* */ }
}

onMounted(loadAll)
</script>

<style scoped>
.view-status-page { padding: 16px; }
.page-desc { color: var(--el-text-color-secondary); margin-bottom: 16px; }
.stats-row { margin-bottom: 16px; }
.stat-card { border-radius: 8px; }
.stat-content { display: flex; align-items: center; gap: 16px; }
.stat-icon {
  width: 48px; height: 48px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; color: white;
}
.stat-browsed .stat-icon { background: linear-gradient(135deg, #909399, #c0c4cc); }
.stat-watched .stat-icon { background: linear-gradient(135deg, #67c23a, #95d475); }
.stat-wanted .stat-icon { background: linear-gradient(135deg, #e6a23c, #f3d19e); }
.stat-unmarked .stat-icon { background: linear-gradient(135deg, #dcdfe6, #e4e7ed); color: #909399; }
.stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-value { font-size: 28px; font-weight: 600; }
.filter-card { margin-bottom: 16px; }
.list-card { border-radius: 8px; }
.no-cover {
  width: 50px; height: 70px;
  display: flex; align-items: center; justify-content: center;
  background: #f5f7fa; color: #c0c4cc; font-size: 11px;
  border-radius: 4px;
}
.batch-bar {
  margin-top: 12px; padding: 12px; background: #f5f7fa;
  border-radius: 6px; display: flex; gap: 8px; align-items: center;
}
</style>
