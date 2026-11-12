<template>
  <el-dialog
    v-model="visible"
    title="批量下载字幕"
    width="760px"
    :close-on-click-modal="false"
    @closed="onClosed"
  >
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
      title="字幕来自第三方公开站点（SubtitleCat / 爱译网），仅供个人备份与学习，请勿传播或商用。站点有限速，任务耗时较长，请勿重复点击。"
    />

    <!-- 启动参数 -->
    <el-form v-if="!isRunning" label-width="96px" style="margin-bottom: 8px">
      <el-form-item label="下载范围">
        <el-radio-group v-model="form.onlyMissing">
          <el-radio :value="true">仅缺字幕（推荐）</el-radio>
          <el-radio :value="false">全部（已有字幕跳过）</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="数量上限">
        <el-input-number v-model="form.limit" :min="1" :max="200" :step="10" />
        <span class="hint">按「最新入库」顺序处理前 {{ form.limit }} 部（上限 200）</span>
      </el-form-item>
      <el-form-item label="并发">
        <el-select v-model="form.concurrency" style="width: 120px">
          <el-option v-for="n in [1, 2, 3, 4]" :key="n" :label="`${n}`" :value="n" />
        </el-select>
        <span class="hint">站点限速，建议 1~2</span>
      </el-form-item>
      <el-form-item label="关键词过滤">
        <el-input v-model="form.keyword" clearable placeholder="可选：标题/番号关键字，留空为全部" style="width: 320px" />
      </el-form-item>
    </el-form>

    <!-- 运行进度 -->
    <div v-if="job" class="progress-box">
      <div class="progress-head">
        <span class="progress-text">
          {{ statusText }}　已完成 {{ job.done }}/{{ job.total }}
        </span>
        <span class="progress-nums">
          <b class="ok">{{ job.ok }}</b> 成功 ·
          <b class="skip">{{ job.skipped }}</b> 跳过 ·
          <b class="fail">{{ job.failed }}</b> 失败
        </span>
        <el-button
          v-if="isRunning"
          size="small"
          type="danger"
          plain
          :loading="cancelling"
          @click="cancel"
        >取消任务</el-button>
      </div>
      <el-progress
        :percentage="percent"
        :status="job.status === 'failed' ? 'exception' : (job.status === 'done' ? 'success' : '')"
        :stroke-width="14"
      />
      <div class="current" v-if="isRunning && job.current">
        当前：{{ job.current.code }} {{ job.current.stage || '' }}
        <span v-if="job.eta_seconds">（预计还需 {{ formatEta(job.eta_seconds) }}）</span>
      </div>
    </div>

    <!-- 明细 -->
    <div v-if="items.length" class="result-box">
      <div class="result-head">
        <span>明细（{{ items.length }} 条）</span>
        <el-checkbox v-model="onlyFailed" size="small">只看失败</el-checkbox>
      </div>
      <el-table :data="visibleItems" size="small" height="240" style="width: 100%">
        <el-table-column prop="code" label="番号" width="120" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <span v-if="row.source === 'subtitlecat'">SubtitleCat</span>
            <span v-else-if="row.source === 'aiyi1'">爱译网</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">{{ ((row.elapsed_ms || 0) / 1000).toFixed(1) }}s</template>
        </el-table-column>
        <el-table-column label="说明" min-width="220">
          <template #default="{ row }">{{ row.status === 'failed' ? subtitleReasonText(row) : row.message }}</template>
        </el-table-column>
      </el-table>
    </div>

    <template #footer>
      <el-button @click="visible = false">{{ isRunning ? '后台继续' : '关闭' }}</el-button>
      <el-button v-if="!isRunning" type="primary" :loading="starting" @click="start">开始下载</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  cancelSubtitleBatch,
  getLatestSubtitleBatch,
  getSubtitleBatch,
  startSubtitleBatch,
  subtitleReasonText
} from '@/api/subtitle'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  module: { type: String, required: true },
  presetKeyword: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'finished'])

const POLL_MS = 2000

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const form = ref({ onlyMissing: true, limit: 200, concurrency: 2, keyword: props.presetKeyword || '' })
const starting = ref(false)
const cancelling = ref(false)
const jobId = ref('')
const job = ref(null)
const onlyFailed = ref(false)
let timer = null

const isRunning = computed(() => job.value?.status === 'queued' || job.value?.status === 'running')
const percent = computed(() => {
  if (!job.value || !job.value.total) return 0
  return Math.min(100, Math.round((job.value.done / job.value.total) * 100))
})
const items = computed(() => job.value?.items || [])
const visibleItems = computed(() => (onlyFailed.value ? items.value.filter(i => i.status === 'failed') : items.value))

const statusText = computed(() => {
  const map = { queued: '排队中', running: '下载中', done: '已完成', cancelled: '已取消', failed: '任务异常' }
  return map[job.value?.status] || ''
})

function statusLabel (status) {
  return { downloaded: '成功', skipped: '跳过', failed: '失败' }[status] || status
}
function statusTagType (status) {
  return { downloaded: 'success', skipped: 'info', failed: 'danger' }[status] || 'info'
}
function formatEta (seconds) {
  if (seconds >= 60) return `${Math.round(seconds / 60)} 分钟`
  return `${seconds} 秒`
}

function stopPolling () {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function tick () {
  if (!jobId.value) return
  try {
    const data = await getSubtitleBatch(props.module, jobId.value)
    job.value = data
    if (['done', 'cancelled', 'failed'].includes(data.status)) {
      stopPolling()
      const summary = `字幕补全完成：成功 ${data.ok}，跳过 ${data.skipped}，失败 ${data.failed}`
      if (data.status === 'done') ElMessage.success(summary)
      else if (data.status === 'cancelled') ElMessage.info(`字幕补全已取消（成功 ${data.ok}，失败 ${data.failed}）`)
      else ElMessage.warning('字幕补全任务异常结束')
      emit('finished', data)
    }
  } catch (e) {
    // 服务重启后任务丢失：停止轮询并提示，不弹空白错误框
    stopPolling()
    if (e?.response?.status === 404) ElMessage.warning('任务已结束或服务已重启')
  }
}

function startPolling () {
  stopPolling()
  timer = setInterval(tick, POLL_MS)
}

async function start () {
  starting.value = true
  try {
    const res = await startSubtitleBatch(props.module, {
      // 批量必须显式声明范围：全库 = scope:'all' + confirm + limit（后端不接受空参数）
      scope: 'all',
      confirm: true,
      only_missing: form.value.onlyMissing,
      limit: form.value.limit,
      concurrency: form.value.concurrency,
      keyword: form.value.keyword || null
    })
    jobId.value = res.job_id
    job.value = {
      job_id: res.job_id,
      status: 'queued',
      total: res.total,
      done: 0,
      ok: 0,
      skipped: 0,
      failed: 0,
      items: []
    }
    onlyFailed.value = false
    ElMessage.info(res.message || '字幕补全已启动')
    startPolling()
    tick()
  } catch (e) {
    // 409 等已由 axios 拦截器提示，这里只兜底非 409 的静默失败
    if (e?.response?.status !== 409) {
      ElMessage.error('启动失败：' + (e?.response?.data?.detail || e?.message || '未知错误'))
    }
  } finally {
    starting.value = false
  }
}

async function cancel () {
  if (!jobId.value) return
  cancelling.value = true
  try {
    await cancelSubtitleBatch(props.module, jobId.value)
    ElMessage.info('已请求取消，正在收尾…')
  } catch (e) {
    ElMessage.error('取消失败：' + (e?.response?.data?.detail || e?.message))
  } finally {
    cancelling.value = false
  }
}

/** 打开弹窗时恢复上一次任务（页面刷新后仍能看到进度/结果） */
async function restoreLatest () {
  try {
    const data = await getLatestSubtitleBatch(props.module)
    if (!data) return
    jobId.value = data.job_id
    job.value = data
    if (['queued', 'running'].includes(data.status)) startPolling()
  } catch {
    /* 没有历史任务：静默忽略 */
  }
}

watch(() => props.modelValue, (open) => {
  if (open) {
    if (!form.value.keyword && props.presetKeyword) form.value.keyword = props.presetKeyword
    if (!job.value) restoreLatest()
    else if (isRunning.value) startPolling()
  } else {
    stopPolling()
  }
})

function onClosed () {
  stopPolling()
}

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.hint { margin-left: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.progress-box { margin: 6px 0 14px; padding: 12px; border: 1px solid var(--hairline, var(--border-color)); border-radius: 10px; }
.progress-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.progress-text { font-size: 13px; font-weight: 600; }
.progress-nums { font-size: 12px; color: var(--el-text-color-secondary); }
.progress-nums .ok { color: var(--el-color-success); }
.progress-nums .skip { color: var(--el-color-info); }
.progress-nums .fail { color: var(--el-color-danger); }
.current { margin-top: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.result-box { margin-top: 8px; }
.result-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; font-size: 13px; }
</style>
