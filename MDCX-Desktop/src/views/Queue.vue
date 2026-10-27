<template>
  <div class="queue-page">
    <h2>观影队列</h2>
    <p class="page-desc">
      跨模块聚合的「未看 / 稍后看 / 已标记」三类片单。基于各库 movies 表的
      <code>watch_later</code> / <code>flagged</code> 字段，纯本地、可导出 CSV。
    </p>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card stat-unseen">
          <div class="stat-content">
            <div class="stat-icon"><VideoCamera /></div>
            <div>
              <div class="stat-label">未看</div>
              <div class="stat-value">{{ stats.unseen }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card stat-later">
          <div class="stat-content">
            <div class="stat-icon"><Clock /></div>
            <div>
              <div class="stat-label">稍后看</div>
              <div class="stat-value">{{ stats.watch_later }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card stat-flagged">
          <div class="stat-content">
            <div class="stat-icon"><Flag /></div>
            <div>
              <div class="stat-label">已标记</div>
              <div class="stat-value">{{ stats.flagged }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 过滤栏 -->
    <el-card shadow="never" class="filter-card">
      <el-radio-group v-model="currentQueue" @change="loadMovies">
        <el-radio-button label="unseen">未看 ({{ stats.unseen }})</el-radio-button>
        <el-radio-button label="watch_later">稍后看 ({{ stats.watch_later }})</el-radio-button>
        <el-radio-button label="flagged">已标记 ({{ stats.flagged }})</el-radio-button>
      </el-radio-group>

      <el-select v-model="currentModule" style="width: 160px; margin-left: 12px" @change="loadMovies">
        <el-option label="全部模块" value="all" />
        <el-option v-for="m in moduleOptions" :key="m.value" :label="m.label" :value="m.value" />
      </el-select>

      <el-button :icon="Download" @click="exportCsv" style="margin-left: 12px">导出 CSV</el-button>
      <el-button :icon="Refresh" @click="loadAll" style="margin-left: 8px">刷新</el-button>
    </el-card>

    <!-- 卡片墙 -->
    <el-card shadow="never" class="list-card">
      <div v-loading="loading" class="card-grid">
        <div v-for="item in movies" :key="item.module + item.id" class="movie-card-item">
          <div class="cover" @click="goDetail(item)">
            <el-image
              v-if="item.cover_url"
              :src="item.cover_url"
              fit="cover"
              class="cover-img"
              @error="onCoverError(item)"
            >
              <template #error><div class="no-cover">无封面</div></template>
            </el-image>
            <div v-else class="no-cover">无封面</div>
            <el-tag v-if="item.module_label" size="small" class="module-tag" effect="dark">
              {{ item.module_label }}
            </el-tag>
          </div>
          <div class="meta">
            <div class="code" @click="goDetail(item)">{{ item.code }}</div>
            <div class="title" :title="item.title">{{ item.title || '—' }}</div>
            <div class="actions">
              <el-button
                size="small"
                :type="item.watch_later ? 'warning' : 'info'"
                :plain="!item.watch_later"
                @click="toggle(item, 'watch_later')"
              >稍后看</el-button>
              <el-button
                size="small"
                :type="item.flagged ? 'danger' : 'info'"
                :plain="!item.flagged"
                @click="toggle(item, 'flagged')"
              >标记</el-button>
            </div>
          </div>
        </div>
      </div>

      <el-empty v-if="!loading && movies.length === 0" :description="emptyHint" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { VideoCamera, Clock, Flag, Download, Refresh } from '@element-plus/icons-vue'
import {
  getQueueStats, listQueueMovies, toggleQueueFlag, exportQueueCsv
} from '@/api'

const router = useRouter()

const stats = reactive({ unseen: 0, watch_later: 0, flagged: 0 })
const currentQueue = ref('unseen')
const currentModule = ref('all')
const movies = ref([])
const loading = ref(false)
const moduleOptions = [
  { label: 'JAV有码', value: 'jav' },
  { label: 'JAV无码', value: 'uncensored' },
  { label: 'FC2', value: 'fc2' },
  { label: 'PORNHUB', value: 'pornhub' },
  { label: '里番', value: 'anime' },
  { label: '欧美', value: 'western' },
  { label: '国产', value: 'chinese' },
]

const queueLabel = (q) => ({ unseen: '未看', watch_later: '稍后看', flagged: '已标记' }[q])
const emptyHint = () => `「${queueLabel(currentQueue.value)}」队列为空`

const loadStats = async () => {
  try {
    const data = await getQueueStats(currentModule.value)
    stats.unseen = data.totals?.unseen || 0
    stats.watch_later = data.totals?.watch_later || 0
    stats.flagged = data.totals?.flagged || 0
  } catch (e) { /* 拦截器已处理 */ }
}

const loadMovies = async () => {
  loading.value = true
  try {
    const data = await listQueueMovies(currentQueue.value, {
      module: currentModule.value, limit: 60, offset: 0,
    })
    movies.value = data.items || []
  } catch (e) { /* */ } finally {
    loading.value = false
  }
}

const loadAll = async () => { await Promise.all([loadStats(), loadMovies()]) }

const toggle = async (item, field) => {
  try {
    const res = await toggleQueueFlag({
      module: item.module, movie_id: item.id, field, value: !item[field],
    })
    item[field] = res.value
    await loadStats()
    ElMessage.success(res.value ? '已加入' : '已移除')
  } catch (e) { /* */ }
}

const onCoverError = (item) => { item.cover_url = '' }

const goDetail = (item) => {
  router.push(`/${item.module}/movies/${item.id}`)
}

const exportCsv = async () => {
  try {
    const res = await exportQueueCsv(currentQueue.value, currentModule.value)
    const blob = res.data instanceof Blob ? res.data : new Blob([res.data])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `queue-${currentQueue.value}-${currentModule.value}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) { /* */ }
}

onMounted(loadAll)
</script>

<style scoped>
.queue-page { padding: 16px; }
.page-desc { color: var(--el-text-color-secondary); margin-bottom: 16px; }
.page-desc code { background: #f5f7fa; padding: 1px 5px; border-radius: 3px; }
.stats-row { margin-bottom: 16px; }
.stat-content { display: flex; align-items: center; gap: 16px; }
.stat-icon {
  width: 48px; height: 48px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; color: white;
}
.stat-unseen .stat-icon { background: linear-gradient(135deg, #409eff, #79bbff); }
.stat-later .stat-icon { background: linear-gradient(135deg, #e6a23c, #f3d19e); }
.stat-flagged .stat-icon { background: linear-gradient(135deg, #f56c6c, #fab6b6); }
.stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-value { font-size: 28px; font-weight: 600; }
.filter-card { margin-bottom: 16px; }
.list-card { border-radius: 8px; }
.card-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 14px;
  min-height: 120px;
}
.movie-card-item { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; overflow: hidden; }
.cover { position: relative; aspect-ratio: 2 / 3; background: #f5f7fa; cursor: pointer; }
.cover-img { width: 100%; height: 100%; }
.no-cover {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  color: #c0c4cc; font-size: 12px;
}
.module-tag { position: absolute; left: 6px; top: 6px; }
.meta { padding: 8px; }
.meta .code { font-weight: 600; font-size: 13px; cursor: pointer; }
.meta .title {
  font-size: 12px; color: var(--el-text-color-secondary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 2px 0 8px;
}
.meta .actions { display: flex; gap: 6px; }
</style>
