<template>
  <el-dialog
    :model-value="visible"
    title="修复媒体文件"
    width="680px"
    :close-on-click-modal="false"
    @open="onOpen"
    @close="onClose"
  >
    <div v-loading="analyzing" class="repair-dialog">
      <!-- 文件信息 -->
      <div class="file-info">
        <div class="fi-row">
          <span class="fi-label">影片</span>
          <span class="fi-value">{{ row?.code || '—' }} <template v-if="row?.title">· {{ row.title }}</template></span>
        </div>
        <div class="fi-row">
          <span class="fi-label">路径</span>
          <span class="fi-value path" :title="row?.file_path">{{ row?.file_path }}</span>
        </div>
      </div>

      <!-- 诊断结果 -->
      <el-alert
        v-if="diag"
        :type="alertType"
        :closable="false"
        show-icon
        class="diag-alert"
      >
        <template #title>
          <span class="diag-title">
            {{ categoryLabel }}
            <el-tag v-if="diag.repairable" size="small" type="success" effect="dark" style="margin-left:8px">可修复</el-tag>
            <el-tag v-else size="small" type="info" effect="plain" style="margin-left:8px">不可修复</el-tag>
          </span>
        </template>
        <div class="diag-detail">{{ diag.detail }}</div>
        <div v-if="diag.video_codec" class="diag-meta">
          时长 {{ diag.duration ? diag.duration.toFixed(0) + ' 秒' : '未知' }} ·
          {{ diag.video_codec }}<span v-if="diag.resolution"> · {{ diag.resolution }}</span> ·
          {{ diag.has_audio ? '有音频' : '无音频' }} ·
          {{ (diag.size / 1048576).toFixed(1) }} MB
          <span v-if="diag.decode_errors"> · 解码报错 {{ diag.decode_errors }} 行</span>
        </div>
      </el-alert>

      <!-- 修复选项（诊断可修时） -->
      <div v-if="diag?.repairable && !jobRunning && !jobDone" class="repair-options">
        <div class="opt-title">修复方式</div>
        <el-radio-group v-model="mode">
          <el-radio-button label="remux">
            重新封装（不重编码）
            <div class="radio-sub">保留原画质，重建索引并置顶 moov；秒级~分钟级</div>
          </el-radio-button>
          <el-radio-button label="reencode">
            重编码（兜底）
            <div class="radio-sub">画质有损、耗时最长；仅当重新封装失败时用</div>
          </el-radio-button>
        </el-radio-group>
        <el-checkbox v-model="verifyDecode" class="opt-verify">
          替换前完整解码验证一遍（更稳，多花约一半时间）
        </el-checkbox>
        <el-alert type="warning" :closable="false" show-icon class="safety-alert" title="安全承诺：原文件不会被动过。修复产物通过验证后，原文件改名备份到同目录 .mdcx-broken/，再原子替换；任何一步失败原文件原地不动。" />
      </div>

      <!-- 任务进度 -->
      <div v-if="job" class="job-panel">
        <div class="job-head">
          <span class="job-status">
            <el-tag :type="statusTagType" size="small" effect="dark">{{ statusLabel }}</el-tag>
            <span class="job-stage">{{ job.stage }}</span>
          </span>
          <el-button v-if="jobRunning" size="small" type="danger" plain @click="onCancelJob">取消任务</el-button>
        </div>
        <pre v-if="job.log?.length" class="repair-log">{{ job.log.join('\n') }}</pre>
        <div v-if="job.error" class="job-error">
          <el-alert type="error" :closable="false" show-icon :title="job.error" />
        </div>
      </div>

      <!-- 成功结果 -->
      <div v-if="job?.result?.status === 'ok'" class="result-panel">
        <el-alert type="success" :closable="false" show-icon title="修复成功，原文件已备份，可播放" />
        <div class="result-rows">
          <div class="res-row">
            <span class="fi-label">原文件备份</span>
            <span class="fi-value path" :title="job.result.backup_path">{{ job.result.backup_path }}</span>
          </div>
          <div class="res-row">
            <span class="fi-label">大小</span>
            <span class="fi-value">
              {{ fmtMB(job.result.old_size) }} MB → {{ fmtMB(job.result.new_size) }} MB
            </span>
          </div>
          <div class="res-row" v-if="job.result.duration_after">
            <span class="fi-label">时长</span>
            <span class="fi-value">
              {{ job.result.duration_before ? job.result.duration_before.toFixed(0) + ' 秒 → ' : '' }}{{ job.result.duration_after.toFixed(0) }} 秒
            </span>
          </div>
        </div>
        <div class="result-tip">确认播放没问题后，备份文件可手动删除（位于同目录 .mdcx-broken/）。</div>
      </div>
    </div>

    <template #footer>
      <el-button @click="onClose">关闭</el-button>
      <el-button v-if="!jobRunning" :loading="analyzing" @click="reanalyze">重新诊断</el-button>
      <el-button
        v-if="diag?.repairable && !jobRunning && !jobDone"
        type="primary"
        :loading="starting"
        @click="onStartRepair"
      >开始修复</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import {
  analyzeMediaRepair, startMediaRepairJob, getMediaRepairJob, cancelMediaRepairJob
} from '@/api'

const props = defineProps({
  visible: { type: Boolean, default: false },
  row: { type: Object, default: null },  // { module, code, title, file_path }
})
const emit = defineEmits(['update:visible', 'repaired'])

const analyzing = ref(false)
const diag = ref(null)
const mode = ref('remux')
const verifyDecode = ref(true)
const starting = ref(false)
const job = ref(null)
let pollTimer = null

const CATEGORY_LABELS = {
  healthy: ['文件正常', 'success'],
  truncated: ['数据被砍断', 'warning'],
  corrupt: ['中段数据损坏', 'error'],
  moov_at_end: ['非 faststart（索引在文件尾部）', 'warning'],
  no_moov: ['索引（moov）缺失', 'info'],
  zero_byte: ['0 字节文件', 'info'],
  missing: ['文件不存在', 'info'],
  unreadable: ['无法读取', 'info'],
  not_video: ['没有视频流', 'info'],
}

const categoryLabel = computed(() => {
  if (!diag.value) return ''
  return (CATEGORY_LABELS[diag.value.category] || [diag.value.category])[0]
})
const alertType = computed(() => {
  if (!diag.value) return 'info'
  const t = (CATEGORY_LABELS[diag.value.category] || ['', 'info'])[1]
  if (t !== 'success' && diag.value.repairable) return 'warning'
  return t
})
const statusLabel = computed(() => {
  const s = job.value?.status
  return { queued: '排队中', running: '修复中', success: '修复成功', failed: '修复失败', cancelled: '已取消' }[s] || s || ''
})
const statusTagType = computed(() => {
  const s = job.value?.status
  return { queued: 'info', running: 'warning', success: 'success', failed: 'danger', cancelled: 'info' }[s] || 'info'
})
const jobRunning = computed(() => job.value?.status === 'queued' || job.value?.status === 'running')
const jobDone = computed(() => job.value?.status === 'success')

function fmtMB(bytes) {
  if (!bytes && bytes !== 0) return '?'
  return (bytes / 1048576).toFixed(1)
}

async function onOpen() {
  await reanalyze()
}

async function reanalyze() {
  if (!props.row?.file_path) return
  analyzing.value = true
  job.value = null
  try {
    diag.value = await analyzeMediaRepair({
      file_path: props.row.file_path,
      decode_check: true,  // 全解码拿最准结论（ corrupt 只有解码能发现）
    })
  } catch (e) {
    diag.value = null
    ElMessage.error(e?.response?.data?.detail || e?.message || '诊断失败')
  } finally {
    analyzing.value = false
  }
}

async function onStartRepair() {
  if (!props.row?.file_path) return
  starting.value = true
  try {
    const created = await startMediaRepairJob({
      file_path: props.row.file_path,
      mode: mode.value,
      verify_decode: verifyDecode.value,
      // corrupt 只有全解码能发现，内部复查必须带 decode_check 才不会误拒
      decode_check: diag.value?.category === 'corrupt',
    })
    job.value = created
    startPolling(created.id)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '创建修复任务失败')
  } finally {
    starting.value = false
  }
}

function startPolling(jobId) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const j = await getMediaRepairJob(jobId)
      job.value = j
      if (['success', 'failed', 'cancelled'].includes(j.status)) {
        stopPolling()
        if (j.status === 'success') {
          emit('repaired', props.row)
        } else if (j.status === 'failed') {
          ElMessage.error(j.error || '修复失败')
        }
      }
    } catch (e) {
      stopPolling()
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function onCancelJob() {
  if (!job.value?.id) return
  try {
    await cancelMediaRepairJob(job.value.id)
    ElMessage.success('已请求取消')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '取消失败')
  }
}

function onClose() {
  stopPolling()
  emit('update:visible', false)
}

onBeforeUnmount(() => stopPolling())
</script>

<style scoped>
.repair-dialog { min-height: 200px; }
.file-info {
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px; padding: 10px 12px; margin-bottom: 14px;
  font-size: 13px;
}
.fi-row { display: flex; gap: 10px; margin: 2px 0; }
.fi-label { color: var(--el-text-color-secondary, #909399); flex: none; width: 76px; }
.fi-value { word-break: break-all; }
.fi-value.path { font-family: var(--font-mono, monospace); font-size: 12px; color: var(--el-text-color-regular, #606266); }
.diag-alert { margin-bottom: 14px; }
.diag-title { font-weight: 600; }
.diag-detail { font-size: 12px; line-height: 1.6; margin-top: 4px; }
.diag-meta { font-size: 12px; color: var(--el-text-color-secondary, #909399); margin-top: 4px; }
.repair-options { margin-bottom: 14px; }
.opt-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.radio-sub { font-size: 11px; color: var(--el-text-color-secondary, #909399); font-weight: normal; line-height: 1.5; margin-top: 2px; }
.opt-verify { display: block; margin-top: 10px; }
.safety-alert { margin-top: 10px; }
.job-panel { margin-top: 14px; }
.job-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.job-status { display: flex; align-items: center; gap: 8px; }
.job-stage { font-size: 13px; color: var(--el-text-color-regular, #606266); }
.repair-log {
  background: #1e1e2e; color: #a6accd;
  font-family: var(--font-mono, monospace); font-size: 11px; line-height: 1.6;
  padding: 10px 12px; border-radius: 6px;
  max-height: 200px; overflow: auto; white-space: pre-wrap; word-break: break-all;
  margin: 0;
}
.job-error { margin-top: 8px; }
.result-panel { margin-top: 14px; }
.result-rows { margin: 10px 0; font-size: 13px; }
.res-row { display: flex; gap: 10px; margin: 4px 0; }
.result-tip { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
</style>
