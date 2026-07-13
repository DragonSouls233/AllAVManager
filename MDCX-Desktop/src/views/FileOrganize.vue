<template>
  <div class="file-organize-page">
    <h2>文件整理</h2>
    <p class="page-desc">5 种整理模式：硬链接 / 复制 / 移动 / 软链接 / 原地点名。支持 Jinja2 命名模板预览和批量执行。</p>

    <el-tabs v-model="activeTab" class="organize-tabs">
      <!-- 整理任务 -->
      <el-tab-pane label="整理任务" name="organize">
        <el-card shadow="never" class="form-card">
          <el-form :model="form" label-width="120px" label-position="right">
            <el-form-item label="影片筛选">
              <el-input
                v-model="movieIdInput"
                placeholder="输入影片 ID（逗号分隔），如：1,2,3"
                style="width: 400px; margin-right: 8px"
              />
              <el-button @click="loadMovieIds">载入</el-button>
              <span class="hint">已选 {{ form.movie_ids.length }} 部</span>
            </el-form-item>

            <el-form-item label="整理模式">
              <el-radio-group v-model="form.job_type">
                <el-radio-button v-for="m in modes.job_types" :key="m.value" :label="m.value">
                  {{ m.label }}
                </el-radio-button>
              </el-radio-group>
              <div class="mode-desc" v-if="currentModeDesc">{{ currentModeDesc }}</div>
            </el-form-item>

            <el-form-item label="输出目录" v-if="form.job_type !== 'rename'">
              <el-input
                v-model="form.output_dir"
                placeholder="如 O:\MDCX\Library"
                style="width: 500px"
              />
            </el-form-item>

            <el-form-item label="命名模板">
              <el-input
                v-model="form.template"
                placeholder="Jinja2 模板，如 {{ code }}/{{ code }}"
                style="width: 500px"
              />
              <div class="template-vars">
                可用变量：<code>code</code> <code>title</code> <code>actor</code>
                <code>studio</code> <code>series</code> <code>release_date</code>
                <code>rating</code> <code>maker</code> <code>director</code>
              </div>
            </el-form-item>

            <el-form-item label="冲突策略">
              <el-radio-group v-model="form.conflict_strategy">
                <el-radio v-for="s in modes.conflict_strategies" :key="s.value" :label="s.value">
                  {{ s.label }}（{{ s.desc }}）
                </el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="preview" :loading="previewing" :icon="View">
                预览任务
              </el-button>
              <el-button type="success" @click="execute" :loading="executing" :icon="Check">
                执行整理
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 预览结果 -->
        <el-card shadow="never" class="preview-card" v-if="previewTasks.length > 0">
          <template #header>
            <div class="card-header">
              <span>预览结果（{{ previewTasks.length }} 个任务）</span>
              <el-button size="small" type="danger" @click="previewTasks = []">清空</el-button>
            </div>
          </template>
          <el-table :data="previewTasks" max-height="400" stripe>
            <el-table-column type="index" width="50" />
            <el-table-column prop="movie_id" label="影片ID" width="80" />
            <el-table-column prop="job_type" label="模式" width="100">
              <template #default="{ row }">
                <el-tag :type="jobTypeTag(row.job_type)" size="small">{{ jobTypeLabel(row.job_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="source_path" label="源路径" min-width="200" show-overflow-tooltip />
            <el-table-column prop="target_path" label="目标路径" min-width="200" show-overflow-tooltip />
            <el-table-column prop="conflict_strategy" label="冲突" width="100" />
          </el-table>
        </el-card>

        <!-- 执行结果 -->
        <el-card shadow="never" class="result-card" v-if="results.length > 0">
          <template #header>
            <div class="card-header">
              <span>执行结果（完成 {{ completedCount }} / 失败 {{ failedCount }} / 跳过 {{ skippedCount }}）</span>
            </div>
          </template>
          <el-table :data="results" max-height="400">
            <el-table-column type="index" width="50" />
            <el-table-column prop="movie_id" label="影片ID" width="80" />
            <el-table-column prop="job_type" label="模式" width="100" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="source_path" label="源路径" min-width="200" show-overflow-tooltip />
            <el-table-column prop="target_path" label="目标路径" min-width="200" show-overflow-tooltip />
            <el-table-column prop="error_message" label="错误" min-width="200" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 任务历史 -->
      <el-tab-pane label="任务历史" name="history">
        <el-card shadow="never">
          <div class="filter-bar">
            <el-select v-model="historyFilter.status" placeholder="状态" clearable style="width: 120px">
              <el-option label="pending" value="pending" />
              <el-option label="running" value="running" />
              <el-option label="completed" value="completed" />
              <el-option label="failed" value="failed" />
              <el-option label="skipped" value="skipped" />
            </el-select>
            <el-select v-model="historyFilter.job_type" placeholder="模式" clearable style="width: 140px">
              <el-option v-for="m in modes.job_types" :key="m.value" :label="m.label" :value="m.value" />
            </el-select>
            <el-button type="primary" :icon="Refresh" @click="loadHistory">查询</el-button>
            <el-button :icon="Refresh" @click="loadStats">刷新统计</el-button>
          </div>

          <el-table :data="history" v-loading="historyLoading" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="job_type" label="模式" width="100">
              <template #default="{ row }">
                <el-tag :type="jobTypeTag(row.job_type)" size="small">{{ jobTypeLabel(row.job_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="source_path" label="源路径" min-width="200" show-overflow-tooltip />
            <el-table-column prop="target_path" label="目标路径" min-width="200" show-overflow-tooltip />
            <el-table-column prop="file_size" label="大小" width="100">
              <template #default="{ row }">
                {{ row.file_size ? formatSize(row.file_size) : '—' }}
              </template>
            </el-table-column>
            <el-table-column prop="error_message" label="错误" min-width="200" show-overflow-tooltip />
            <el-table-column prop="created_at" label="创建时间" width="170">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 统计 -->
      <el-tab-pane label="统计" name="stats">
        <el-row :gutter="16">
          <el-col :span="4" v-for="(val, key) in jobStats" :key="key">
            <el-card shadow="hover" class="stat-card">
              <div class="stat-label">{{ statusLabel(key) }}</div>
              <div class="stat-value">{{ val }}</div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { View, Check, Refresh } from '@element-plus/icons-vue'
import {
  getOrganizeModes, previewOrganize, executeOrganize,
  listOrganizeJobs, getOrganizeJobStats
} from '@/api'

const activeTab = ref('organize')
const modes = reactive({ job_types: [], conflict_strategies: [] })
const movieIdInput = ref('')
const form = reactive({
  movie_ids: [],
  job_type: 'hardlink',
  output_dir: '',
  template: '{{ code }}/{{ code }}',
  conflict_strategy: 'skip',
})
const previewing = ref(false)
const executing = ref(false)
const previewTasks = ref([])
const results = ref([])

// 历史
const history = ref([])
const historyLoading = ref(false)
const historyFilter = reactive({ status: '', job_type: '' })

// 统计
const jobStats = ref({})

const currentModeDesc = computed(() => {
  const m = modes.job_types.find(t => t.value === form.job_type)
  return m?.desc || ''
})

const completedCount = computed(() => results.value.filter(r => r.status === 'completed').length)
const failedCount = computed(() => results.value.filter(r => r.status === 'failed').length)
const skippedCount = computed(() => results.value.filter(r => r.status === 'skipped').length)

const jobTypeLabel = (t) => ({ hardlink: '硬链接', copy: '复制', move: '移动', symlink: '软链接', rename: '原地点名' }[t] || t)
const jobTypeTag = (t) => ({ hardlink: 'primary', copy: 'info', move: 'warning', symlink: 'success', rename: '' }[t] || '')
const statusLabel = (s) => ({ pending: '等待', running: '运行中', completed: '已完成', failed: '失败', skipped: '已跳过' }[s] || s)
const statusTag = (s) => ({ pending: 'info', running: 'warning', completed: 'success', failed: 'danger', skipped: '' }[s] || '')

const formatSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}
const formatTime = (iso) => iso ? new Date(iso).toLocaleString('zh-CN') : '—'

const loadModes = async () => {
  try {
    const data = await getOrganizeModes()
    modes.job_types = data.job_types || []
    modes.conflict_strategies = data.conflict_strategies || []
  } catch (e) { /* */ }
}

const loadMovieIds = () => {
  const ids = movieIdInput.value
    .split(/[,\s]+/)
    .map(s => parseInt(s.trim()))
    .filter(n => !isNaN(n) && n > 0)
  form.movie_ids = ids
  ElMessage.success(`载入 ${ids.length} 个影片 ID`)
}

const preview = async () => {
  if (form.movie_ids.length === 0) {
    ElMessage.warning('请先载入影片 ID')
    return
  }
  previewing.value = true
  try {
    const data = await previewOrganize({
      movie_ids: form.movie_ids,
      job_type: form.job_type,
      output_dir: form.output_dir,
      template: form.template,
      conflict_strategy: form.conflict_strategy,
    })
    previewTasks.value = data.items || []
    ElMessage.success(`预览完成：${data.total} 个任务`)
  } catch (e) { /* */ } finally {
    previewing.value = false
  }
}

const execute = async () => {
  if (form.movie_ids.length === 0) {
    ElMessage.warning('请先载入影片 ID')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认对 ${form.movie_ids.length} 部影片执行【${jobTypeLabel(form.job_type)}】操作？`,
      '执行确认',
      { type: 'warning' }
    )
  } catch { return }

  executing.value = true
  try {
    const data = await executeOrganize({
      movie_ids: form.movie_ids,
      job_type: form.job_type,
      output_dir: form.output_dir,
      template: form.template,
      conflict_strategy: form.conflict_strategy,
    })
    results.value = data.results || []
    ElMessage.success(`执行完成：成功 ${data.completed} / 失败 ${data.failed} / 跳过 ${data.skipped}`)
    await loadStats()
  } catch (e) { /* */ } finally {
    executing.value = false
  }
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const params = {}
    if (historyFilter.status) params.status = historyFilter.status
    if (historyFilter.job_type) params.job_type = historyFilter.job_type
    const data = await listOrganizeJobs(params)
    history.value = data.items || []
  } catch (e) { /* */ } finally {
    historyLoading.value = false
  }
}

const loadStats = async () => {
  try {
    jobStats.value = await getOrganizeJobStats()
  } catch (e) { /* */ }
}

onMounted(async () => {
  await loadModes()
  await Promise.all([loadHistory(), loadStats()])
})
</script>

<style scoped>
.file-organize-page { padding: 16px; }
.page-desc { color: var(--el-text-color-secondary); margin-bottom: 16px; }
.organize-tabs { margin-top: 8px; }
.form-card { border-radius: 8px; margin-bottom: 16px; }
.mode-desc { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 4px; }
.template-vars { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 4px; }
.template-vars code {
  background: #f5f7fa; padding: 1px 6px; border-radius: 3px;
  margin-right: 4px; font-size: 11px;
}
.preview-card, .result-card { border-radius: 8px; margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.filter-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.stat-card { border-radius: 8px; text-align: center; }
.stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-value { font-size: 28px; font-weight: 600; margin-top: 8px; }
.hint { margin-left: 8px; color: var(--el-text-color-secondary); }
</style>
