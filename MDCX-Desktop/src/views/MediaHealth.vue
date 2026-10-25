<template>
  <div class="mh-page">
    <div class="page-header">
      <h2>媒体健康扫描</h2>
      <p class="desc">检查库里记录的影片文件是否还有效：盘符掉线（NAS 未挂载）、文件被移走/删除/改名、下载中断留下的损坏文件。<b>纯只读扫描，不写、不删、不移动任何文件</b>，结果仅供排查。</p>
    </div>

    <div class="toolbar">
      <div class="toolbar-left">
        <el-checkbox-group v-model="selectedModules" :min="1">
          <el-checkbox-button label="jav">JAV</el-checkbox-button>
          <el-checkbox-button label="uncensored">无码</el-checkbox-button>
          <el-checkbox-button label="chinese">国产</el-checkbox-button>
          <el-checkbox-button label="western">欧美</el-checkbox-button>
          <el-checkbox-button label="fc2">FC2</el-checkbox-button>
          <el-checkbox-button label="pornhub">PORNHUB</el-checkbox-button>
        </el-checkbox-group>
        <el-tooltip
          content="对每个存在的文件运行 ffprobe 验证可解码（发现 0 字节/下载中断/损坏的文件）。每部一次子进程，耗时明显变长；默认最多检测 500 部，超出部分跳过。"
          placement="top"
        >
          <el-checkbox v-model="deepCheck" style="margin-left:12px">深度检测（ffprobe）</el-checkbox>
        </el-tooltip>
      </div>
      <div class="toolbar-right">
        <el-button type="primary" :loading="scanning" :icon="Search" @click="startScan">
          {{ scanning ? '扫描中...' : '开始扫描' }}
        </el-button>
      </div>
    </div>

    <div v-if="errorMsg" class="error-box">
      <el-alert type="error" :title="errorMsg" show-icon closable @close="errorMsg = ''" />
    </div>

    <div v-if="results.length && !scanning" class="summary">
      <el-row :gutter="16">
        <el-col :span="6">
          <el-statistic title="扫描影片数" :value="totalScanned" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="正常" :value="totalOk" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="异常" :value="totalIssues">
            <template #suffix>
              <el-tag v-if="totalIssues > 0" type="danger" size="small" style="margin-left:8px">需排查</el-tag>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="无文件记录" :value="totalNoPath">
            <template #suffix>
              <span style="font-size:12px;color:#909399;margin-left:4px">未下载/整理</span>
            </template>
          </el-statistic>
        </el-col>
      </el-row>
    </div>

    <div v-if="results.length && !scanning" class="breakdown">
      <el-row :gutter="16">
        <el-col :span="8">
          <div class="bd-card bd-drive">
            <div class="bd-num">{{ totalDriveMissing }}</div>
            <div class="bd-label">盘符未就绪</div>
            <div class="bd-hint">NAS 掉线或网络盘未挂载，修复挂载后通常自动恢复</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="bd-card bd-file">
            <div class="bd-num">{{ totalFileMissing }}</div>
            <div class="bd-label">文件不存在</div>
            <div class="bd-hint">文件被移走/删除/改名，或整理规则写错了目录</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="bd-card bd-probe">
            <div class="bd-num">{{ totalProbeFailed }}</div>
            <div class="bd-label">探测失败</div>
            <div class="bd-hint">文件在但无法解码（0 字节/损坏/下载中断）</div>
            <el-button
              v-if="totalProbeFailed > 0"
              class="bd-action"
              size="small"
              type="warning"
              plain
              :loading="batchRepairing"
              @click="batchRepair"
            >批量修复（{{ totalProbeFailed }}）</el-button>
          </div>
        </el-col>
      </el-row>
    </div>

    <div v-if="results.length && !scanning && totalDriveMissing > 0" class="ghost-tip">
      <el-alert type="warning" show-icon :closable="false">
        <template #title>
          有 {{ totalDriveMissing }} 部影片的盘符未就绪。若盘符已确认挂载却仍报错，可能是 NAS 掉线留下的
          <b>幽灵盘符</b>（net use 报错误 85）——到「网络盘管理」页执行修复后重新扫描。
        </template>
      </el-alert>
    </div>

    <div v-if="results.length && !scanning && probeDegraded" class="ghost-tip">
      <el-alert type="warning" show-icon :closable="false" title="ffprobe 不可用，深度检测已降级为存在性快检（服务端未找到 ffprobe 可执行文件）。" />
    </div>

    <div v-if="results.length && !scanning && totalProbeSkipped > 0" class="ghost-tip">
      <el-alert type="info" show-icon :closable="false" :title="`深检数量达到上限，${totalProbeSkipped} 部已存在的文件未做 ffprobe 验证（按正常计）。`" />
    </div>

    <!-- 修复任务面板（批量修复入队后出现） -->
    <div v-if="repairJobs.length" class="repair-jobs">
      <div class="rj-head">
        <span>修复任务（最近 {{ repairJobs.length }} 个，排队执行中每次只修一个）</span>
        <el-button text size="small" @click="stopJobsPolling(); repairJobs = []">隐藏</el-button>
      </div>
      <div class="rj-list">
        <div v-for="j in repairJobs" :key="j.id" class="rj-item">
          <el-tag size="small" :type="repairJobTag(j.status)" effect="dark">{{ repairJobLabel(j.status) }}</el-tag>
          <span class="rj-name" :title="j.file_path">{{ baseName(j.file_path) }}</span>
          <span class="rj-stage">{{ j.stage }}</span>
        </div>
      </div>
    </div>

    <div v-if="results.length && !scanning && totalIssues > 0" class="issues">
      <el-tabs v-model="activeTab" class="issue-tabs">
        <el-tab-pane :label="`盘符未就绪（${totalDriveMissing}）`" name="drive">
          <IssueTable :rows="driveRows" kind="drive" />
        </el-tab-pane>
        <el-tab-pane :label="`文件不存在（${totalFileMissing}）`" name="file">
          <IssueTable :rows="fileRows" kind="file" />
        </el-tab-pane>
        <el-tab-pane :label="`探测失败（${totalProbeFailed}）`" name="probe">
          <IssueTable :rows="probeRows" kind="probe" @repair="openRepair" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <div v-else-if="results.length && !scanning && totalIssues === 0" class="all-ok">
      <el-result icon="success" title="未发现异常" :sub-title="`${totalScanned} 部影片全部可访问${totalNoPath ? `，另有 ${totalNoPath} 部无文件记录（未下载/整理）` : ''}`" />
    </div>

    <div v-if="!results.length && !scanning" class="placeholder">
      <el-empty description="选择模块后点击「开始扫描」，检查库里影片文件是否还有效" />
    </div>

    <!-- 单文件修复对话框 -->
    <RepairDialog v-model:visible="repairVisible" :row="repairRow" @repaired="onRepaired" />
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { scanMediaHealth, startMediaRepairJob, listMediaRepairJobs } from '@/api'
import IssueTable from '@/components/media/IssueTable.vue'
import RepairDialog from '@/components/media/RepairDialog.vue'

const MODULES = ['jav', 'uncensored', 'chinese', 'western', 'fc2', 'pornhub']
const selectedModules = ref(['jav'])
const deepCheck = ref(false)
const scanning = ref(false)
const results = ref([])
const errorMsg = ref('')
const activeTab = ref('drive')

const totalScanned = computed(() => results.value.reduce((s, r) => s + (r.scanned || 0), 0))
const totalOk = computed(() => results.value.reduce((s, r) => s + (r.ok || 0), 0))
const totalNoPath = computed(() => results.value.reduce((s, r) => s + (r.no_path || 0), 0))
const totalDriveMissing = computed(() => results.value.reduce((s, r) => s + (r.drive_missing_total || 0), 0))
const totalFileMissing = computed(() => results.value.reduce((s, r) => s + (r.file_missing_total || 0), 0))
const totalProbeFailed = computed(() => results.value.reduce((s, r) => s + (r.probe_failed_total || 0), 0))
const totalProbeSkipped = computed(() => results.value.reduce((s, r) => s + (r.probe_skipped || 0), 0))
const totalIssues = computed(() => totalDriveMissing.value + totalFileMissing.value + totalProbeFailed.value)
const probeDegraded = computed(() => results.value.some(r => r.probe_errors === -1))

// ---------- 媒体修复 ----------
const repairVisible = ref(false)
const repairRow = ref(null)
const batchRepairing = ref(false)
const repairJobs = ref([])
let jobsTimer = null

function openRepair(row) {
  repairRow.value = row
  repairVisible.value = true
}

function onRepaired() {
  // 修复成功后提示重新扫描刷新状态
  ElMessage.success('修复完成，重新扫描后可看到该影片恢复正常')
}

function baseName(p) {
  if (!p) return ''
  return String(p).split(/[\\/]/).pop()
}

const REPAIR_JOB_LABELS = { queued: '排队中', running: '修复中', success: '成功', failed: '失败', cancelled: '已取消' }
const REPAIR_JOB_TAGS = { queued: 'info', running: 'warning', success: 'success', failed: 'danger', cancelled: 'info' }
function repairJobLabel(s) { return REPAIR_JOB_LABELS[s] || s }
function repairJobTag(s) { return REPAIR_JOB_TAGS[s] || 'info' }

async function batchRepair() {
  const rows = probeRows.value
  if (!rows.length) return
  batchRepairing.value = true
  let queued = 0
  const errors = []
  for (const row of rows) {
    try {
      // 不预诊断（批量场景全解码太慢）；任务内部会自己复查，
      // 健康的文件会被安全拒绝，不影响队列里其它文件
      await startMediaRepairJob({ file_path: row.file_path, mode: 'remux', verify_decode: true })
      queued++
    } catch (e) {
      errors.push(baseName(row.file_path))
    }
  }
  batchRepairing.value = false
  if (queued) {
    ElMessage.success(`已入队 ${queued} 个修复任务${errors.length ? `，${errors.length} 个入队失败` : ''}（排队执行，点任意文件的「修复」可看详细进度）`)
    startJobsPolling()
  } else {
    ElMessage.error('入队失败：' + (errors[0] || '未知错误'))
  }
}

async function pollJobsOnce() {
  try {
    const data = await listMediaRepairJobs(20)
    repairJobs.value = data.items || []
    const active = repairJobs.value.some(j => j.status === 'queued' || j.status === 'running')
    if (!active) stopJobsPolling()
  } catch { stopJobsPolling() }
}

function startJobsPolling() {
  stopJobsPolling()
  pollJobsOnce()
  jobsTimer = setInterval(pollJobsOnce, 3000)
}

function stopJobsPolling() {
  if (jobsTimer) {
    clearInterval(jobsTimer)
    jobsTimer = null
  }
}

onBeforeUnmount(() => stopJobsPolling())

const driveRows = computed(() => results.value.flatMap(r => (r.drive_missing || []).map(i => ({ ...i, module: r.module }))))
const fileRows = computed(() => results.value.flatMap(r => (r.file_missing || []).map(i => ({ ...i, module: r.module }))))
const probeRows = computed(() => results.value.flatMap(r => (r.probe_failed || []).map(i => ({ ...i, module: r.module }))))

async function startScan() {
  scanning.value = true
  results.value = []
  errorMsg.value = ''
  activeTab.value = 'drive'
  try {
    const data = await scanMediaHealth(selectedModules.value, deepCheck.value)
    // 后端单模块返回单个对象；统一成数组
    results.value = Array.isArray(data) ? data : [data]
    const errCount = results.value.reduce((s, r) => s + (r.issue_total || 0), 0)
    if (errCount === 0) {
      ElMessage.success(`扫描完成，${totalScanned.value} 部影片未发现异常`)
    } else {
      ElMessage.warning(`扫描完成，发现 ${errCount} 部异常影片`)
    }
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '扫描失败'
    errorMsg.value = msg
    ElMessage.error(msg)
  } finally {
    scanning.value = false
  }
}
</script>

<style scoped>
.mh-page { max-width: 1200px; margin: 0 auto; }
.page-header h2 { font-size: 20px; font-weight: 600; margin-bottom: 6px; }
.page-header .desc { color: #909399; font-size: 13px; margin-bottom: 20px; line-height: 1.6; }
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20px; background: #fff; padding: 16px; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.summary, .breakdown {
  background: #fff; padding: 20px; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04); margin-bottom: 16px;
}
.bd-card { text-align: center; padding: 12px 8px; border-radius: 8px; border: 1px solid #ebeef5; }
.bd-num { font-size: 26px; font-weight: 600; line-height: 1.2; }
.bd-label { font-size: 13px; color: #606266; margin-top: 2px; }
.bd-hint { font-size: 11px; color: #909399; margin-top: 6px; line-height: 1.5; }
.bd-drive .bd-num { color: #e6a23c; }
.bd-file .bd-num { color: #f56c6c; }
.bd-probe .bd-num { color: #f56c6c; }
.bd-action { margin-top: 8px; }
.repair-jobs {
  background: #fff; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.rj-head {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 13px; font-weight: 600; color: #606266; margin-bottom: 8px;
}
.rj-list { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow: auto; }
.rj-item { display: flex; align-items: center; gap: 10px; font-size: 12px; }
.rj-name {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: var(--font-mono, monospace); color: #606266;
}
.rj-stage { color: #909399; flex: none; }
.ghost-tip { margin-bottom: 16px; }
.issues { background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); padding: 0 16px 16px; }
.issue-tabs { margin-top: 8px; }
.placeholder { background: #fff; border-radius: 8px; padding: 40px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
.all-ok { background: #fff; border-radius: 8px; padding: 24px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
</style>
