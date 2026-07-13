<template>
  <div class="merge-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>多来源数据精选</h2>
      <p class="subtitle">从多个刮削源对比字段值 · 手动挑选最佳数据 · 写回影片元数据</p>
    </div>

    <!-- 影片选择 -->
    <el-card shadow="never" class="block-card">
      <div class="movie-picker">
        <el-select
          v-model="selectedMovieId"
          filterable
          remote
          reserve-keyword
          placeholder="搜索番号或标题以选择影片"
          :remote-method="searchMovies"
          :loading="movieLoading"
          style="width: 360px"
          @change="onMovieChange"
        >
          <el-option
            v-for="m in movieOptions"
            :key="m.id"
            :label="`${m.code} · ${m.title || ''}`"
            :value="m.id"
          />
        </el-select>
        <el-button @click="loadMeta" :loading="loading">加载字段</el-button>
        <el-tag v-if="currentCode" type="info" class="code-tag">{{ currentCode }}</el-tag>
      </div>
    </el-card>

    <!-- 字段对比编辑 -->
    <el-card shadow="never" class="block-card" v-if="rows.length">
      <template #header>
        <div class="block-title">
          <span>字段精选（{{ rows.length }} 个可编辑字段）</span>
          <div>
            <el-button type="primary" size="small" @click="applySelected" :loading="applying">
              应用选中字段
            </el-button>
            <el-button size="small" @click="selectAll(true)">全选</el-button>
            <el-button size="small" @click="selectAll(false)">清空</el-button>
          </div>
        </div>
      </template>

      <el-table :data="rows" v-loading="loading" style="width: 100%">
        <el-table-column label="字段" width="150">
          <template #default="{ row }">
            <div class="field-name">{{ row.label }}</div>
            <div class="field-key muted">{{ row.field }}</div>
          </template>
        </el-table-column>
        <el-table-column label="当前值" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'muted': isEmpty(row.current) }">{{ displayVal(row.current) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="选择来源" width="170">
          <template #default="{ row }">
            <el-select v-model="row.source" placeholder="手动/来源" size="small" @change="(s) => onSourceChange(row, s)">
              <el-option label="✎ 手动输入" value="manual" />
              <el-option v-for="s in sources" :key="s" :label="s" :value="s" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="预览/手动值" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-input
              v-if="row.source === 'manual'"
              v-model="row.manualValue"
              size="small"
              placeholder="输入新值"
              @input="onManualInput(row)"
            />
            <span v-else-if="row.source && row.preview !== undefined" :class="{ 'muted': isEmpty(row.preview) }">
              {{ displayVal(row.preview) }}
            </span>
            <span v-else-if="row.source" class="muted">
              <el-icon class="is-loading"><Loading /></el-icon> 获取中…
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="应用" width="80" align="center">
          <template #default="{ row }">
            <el-checkbox v-model="row.apply" />
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-empty v-if="!loading && !rows.length && selectedMovieId" description="该影片无可编辑字段" />
    <el-empty v-if="!selectedMovieId" description="请先选择一部影片" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { getMovies } from '@/api'
import {
  getSourceMergeMeta, getSourceMergeFields,
  previewSourceScrape, applySourceMerge
} from '@/api'

const loading = ref(false)
const applying = ref(false)
const movieLoading = ref(false)

const meta = reactive({ fields: {}, sources: [] })
const movieOptions = ref([])
const selectedMovieId = ref(null)
const currentCode = ref('')
const rows = ref([])
const previewCache = reactive({}) // source -> { field: value }

function isEmpty(v) {
  return v === null || v === undefined || v === ''
}
function displayVal(v) {
  if (isEmpty(v)) return '（空）'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

async function loadMeta() {
  try {
    const res = await getSourceMergeMeta()
    meta.fields = res.fields || {}
    meta.sources = (res.sources || []).filter(s => s !== 'manual')
  } catch (e) {
    // 拦截器已提示
  }
}

function searchMovies(query) {
  if (!query) {
    movieOptions.value = []
    return
  }
  movieLoading.value = true
  getMovies({ search: query, page: 1, page_size: 20 })
    .then(res => {
      movieOptions.value = res.items || []
    })
    .catch(() => {})
    .finally(() => { movieLoading.value = false })
}

async function onMovieChange(id) {
  if (!id) return
  const movie = movieOptions.value.find(m => m.id === id)
  currentCode.value = movie?.code || ''
  await loadFields()
}

async function loadFields() {
  if (!selectedMovieId.value) return
  loading.value = true
  rows.value = []
  try {
    const res = await getSourceMergeFields(selectedMovieId.value)
    currentCode.value = res.code || currentCode.value
    rows.value = (res.fields || []).map(f => ({
      field: f.field,
      label: meta.fields[f.field]?.label || f.field,
      type: meta.fields[f.field]?.type || 'str',
      current: f.value,
      source: '',
      manualValue: isEmpty(f.value) ? '' : String(f.value),
      preview: undefined,
      apply: false
    }))
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function onSourceChange(row, source) {
  row.preview = undefined
  if (!source || source === 'manual') return
  if (previewCache[source] && previewCache[source][row.field] !== undefined) {
    row.preview = previewCache[source][row.field]
    return
  }
  try {
    const res = await previewSourceScrape(selectedMovieId.value, source)
    if (res.success) {
      const map = {}
      ;(res.fields || []).forEach(f => { map[f.field] = f.value })
      previewCache[source] = map
      row.preview = map[row.field]
      if (row.preview !== undefined) row.apply = true
    } else {
      ElMessage.warning(`${source}: ${res.message || '无数据'}`)
    }
  } catch (e) {
    // 拦截器已提示
  }
}

function onManualInput(row) {
  if (row.source === 'manual') row.apply = true
}

function selectAll(v) {
  rows.value.forEach(r => { r.apply = v })
}

async function applySelected() {
  const chosen = rows.value.filter(r => r.apply)
  if (!chosen.length) {
    ElMessage.warning('请先勾选要应用的字段')
    return
  }
  const payload = []
  for (const r of chosen) {
    if (r.source === 'manual') {
      if (isEmpty(r.manualValue)) continue
      payload.push({ field: r.field, value: r.type === 'int' ? Number(r.manualValue) : r.manualValue, source: 'manual' })
    } else if (r.source && r.preview !== undefined) {
      payload.push({ field: r.field, value: r.preview, source: r.source })
    }
  }
  if (!payload.length) {
    ElMessage.warning('没有可写入的字段值')
    return
  }
  applying.value = true
  try {
    const res = await applySourceMerge(selectedMovieId.value, payload)
    ElMessage.success(res.message || `已更新 ${payload.length} 个字段`)
    // 重置来源选择并刷新当前值
    Object.keys(previewCache).forEach(k => delete previewCache[k])
    await loadFields()
  } catch (e) {
    // 拦截器已提示
  } finally {
    applying.value = false
  }
}

onMounted(() => {
  loadMeta()
})
</script>

<style scoped>
.merge-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.subtitle {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.block-card {
  margin-bottom: 16px;
}

.movie-picker {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.code-tag {
  font-family: monospace;
}

.block-title {
  font-weight: 600;
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.field-name {
  font-weight: 600;
  color: #303133;
  font-size: 13px;
}

.field-key {
  font-size: 11px;
  font-family: monospace;
}

.muted {
  color: #c0c4cc;
}
</style>
