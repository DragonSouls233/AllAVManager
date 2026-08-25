<template>
  <div class="page cover-problems-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><WarningFilled /></el-icon>
          封面问题修复
        </h2>
        <span class="page-subtitle">扫描本地存在但损坏/乱码的封面，批量就地解密或重下</span>
      </div>
      <div class="page-header-right">
        <el-button :icon="Refresh" :loading="loading" @click="loadProblems">重新扫描</el-button>
      </div>
    </div>

    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num primary">{{ problems.length }}</span>
            <span class="stat-label">问题影片</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num warning">{{ typeCounts.xor_garbled || 0 }}</span>
            <span class="stat-label">CDN 乱码</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num danger">{{ typeCounts.decoded_broken || 0 }}</span>
            <span class="stat-label">解码失败</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-inner">
            <span class="stat-num info">{{ typeCounts.too_small || 0 }}</span>
            <span class="stat-label">文件过小</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-radio-group v-model="typeFilter" size="default" @change="loadProblems">
        <el-radio-button :value="''">全部</el-radio-button>
        <el-radio-button value="xor_garbled">CDN 乱码</el-radio-button>
        <el-radio-button value="decoded_broken">解码失败</el-radio-button>
        <el-radio-button value="too_small">文件过小</el-radio-button>
      </el-radio-group>

      <div class="toolbar-actions">
        <el-checkbox v-model="selectAll" :disabled="!problems.length" @change="toggleAll">
          全选
        </el-checkbox>
        <el-button type="warning" plain :disabled="!targetCodes.length" :loading="fixing" @click="startFix('decrypt')">
          <el-icon><Unlock /></el-icon>
          就地解密
        </el-button>
        <el-button type="primary" :disabled="!targetCodes.length" :loading="fixing" @click="startFix('full')">
          <el-icon><MagicStick /></el-icon>
          解密并重下
        </el-button>
        <el-button type="danger" plain :disabled="!targetCodes.length" :loading="fixing" @click="startFix('redownload')">
          <el-icon><RefreshRight /></el-icon>
          仅重下
        </el-button>
      </div>
    </div>

    <!-- 修复进度提示 -->
    <el-alert
      v-if="fixing"
      type="info"
      :closable="false"
      show-icon
      class="fixing-alert"
    >
      <template #title>
        正在后台批量修复 {{ fixingCount }} 部影片（{{ fixingIndex }}/{{ fixingCount }}）… 请稍候，页面会自动刷新结果
      </template>
    </el-alert>

    <!-- 问题卡片网格 -->
    <div v-loading="loading" class="problem-grid">
      <el-empty v-if="!loading && !problems.length" description="没有发现封面问题 🎉" />
      <div
        v-for="item in problems"
        :key="item.code"
        class="problem-card"
        :class="{ 'is-selected': checked.has(item.code) }"
      >
        <!-- 封面预览：乱码文件用 decrypt=1 预览解密效果 -->
        <div class="cover-box" @click="toggleCheck(item.code)">
          <el-checkbox
            v-if="problems.length"
            class="cover-check"
            :model-value="checked.has(item.code)"
            @click.stop="toggleCheck(item.code)"
          />
          <img
            v-if="!item.imgError && item.movie_id"
            :src="coverImg(item)"
            :alt="item.code"
            loading="lazy"
            @error="item.imgError = true"
          />
          <div v-else class="cover-placeholder">
            <el-icon><Picture /></el-icon>
            <span>封面不可预览</span>
          </div>
          <div class="cover-badge">{{ item.code }}</div>
        </div>

        <div class="card-body">
          <div class="card-title" :title="item.title">{{ item.title }}</div>
          <div class="file-badges">
            <el-tag
              v-for="f in item.files"
              :key="f.name"
              size="small"
              :type="tagType(f.type)"
              effect="light"
            >
              {{ f.name }} · {{ problemLabel(f.type) }}
            </el-tag>
          </div>
          <div class="card-actions">
            <el-button size="small" type="primary" plain @click="startFix('full', [item.code])">
              修复此部
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Refresh, RefreshRight, Unlock, MagicStick,
  WarningFilled, Picture
} from '@element-plus/icons-vue'
import { getCoverProblems, fixCoverProblems } from '@/api/jav'
import { getServerUrl } from '@/api/index'

// ===== 状态 =====
const loading = ref(false)
const problems = ref([])
const typeCounts = ref({})
const typeFilter = ref('')
const checked = ref(new Set())
const selectAll = ref(false)

// ===== 修复进度 =====
const fixing = ref(false)
const fixingCount = ref(0)
const fixingIndex = ref(0)
let fixTimer = null
let fixPolling = 0

const PROBLEM_LABELS = {
  xor_garbled: 'CDN 混淆乱码',
  decoded_broken: '解码失败/半截文件',
  too_small: '文件过小'
}

function problemLabel(t) {
  return PROBLEM_LABELS[t] || t
}

function tagType(t) {
  if (t === 'xor_garbled') return 'warning'
  if (t === 'decoded_broken') return 'danger'
  return 'info'
}

// 当前筛选下的影片中，实际可操作的目标（选中优先，未选则全部）
const targetCodes = computed(() => {
  if (checked.value.size) {
    return problems.value
      .filter((it) => checked.value.has(it.code))
      .map((it) => it.code)
  }
  return problems.value.map((it) => it.code)
})

function coverImg(item) {
  const base = getServerUrl().replace(/\/$/, '')
  return `${base}/api/v1/jav/movies/${item.movie_id}/cover/file?decrypt=1&t=${Date.now()}`
}

function toggleCheck(code) {
  const next = new Set(checked.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  checked.value = next
  selectAll.value = next.size === problems.value.length && problems.value.length > 0
}

function toggleAll() {
  if (selectAll.value) {
    checked.value = new Set(problems.value.map((it) => it.code))
  } else {
    checked.value = new Set()
  }
}

async function loadProblems() {
  loading.value = true
  try {
    const res = await getCoverProblems({ type_filter: typeFilter.value || undefined, limit: 2000 })
    const data = res.data || {}
    problems.value = (data.problems || []).map((it) => ({ ...it, imgError: false }))
    typeCounts.value = data.type_counts || {}
    // 清理已失效的选中项
    const valid = new Set(problems.value.map((it) => it.code))
    checked.value = new Set([...checked.value].filter((c) => valid.has(c)))
    selectAll.value = checked.value.size === problems.value.length && problems.value.length > 0
  } catch (e) {
    ElMessage.error('扫描封面问题失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function startFix(mode, codes = null) {
  if (fixing.value) return
  const targets = codes || targetCodes.value
  if (!targets.length) {
    ElMessage.warning('没有可修复的影片')
    return
  }
  const payload = { codes: targets }
  if (mode === 'decrypt') {
    payload.decrypt = true
    payload.redownload = false
  } else if (mode === 'redownload') {
    payload.decrypt = false
    payload.redownload = true
  } else {
    payload.decrypt = true
    payload.redownload = true
  }
  fixing.value = true
  fixingCount.value = targets.length
  fixingIndex.value = 0
  fixPolling = 0
  try {
    await fixCoverProblems(payload)
    ElMessage.success(`已启动批量修复 ${targets.length} 部影片（后台执行）`)
    // 轮询刷新结果，直到问题全部解决或达到轮询上限
    fixTimer = setInterval(async () => {
      fixPolling += 1
      fixingIndex.value = Math.min(fixingIndex.value + Math.ceil(fixingCount.value / 20), fixingCount.value)
      try {
        await loadProblems()
        if (!problems.value.length || fixPolling >= 40) {
          clearInterval(fixTimer)
          fixTimer = null
          fixing.value = false
          if (!problems.value.length) {
            ElMessage.success('全部封面问题已修复完成')
          }
        }
      } catch (e) {
        // 单次轮询失败不中断，继续等待后台任务
      }
    }, 3000)
  } catch (e) {
    fixing.value = false
    ElMessage.error('启动批量修复失败：' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  loadProblems()
})

onUnmounted(() => {
  if (fixTimer) clearInterval(fixTimer)
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 20px;
  color: var(--el-text-color-primary);
}
.page-subtitle {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.stats-row {
  margin-bottom: 16px;
}
.stat-inner {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-num {
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
}
.stat-num.primary { color: var(--el-color-primary); }
.stat-num.warning { color: var(--el-color-warning); }
.stat-num.danger { color: var(--el-color-danger); }
.stat-num.info { color: var(--el-color-info); }
.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fixing-alert {
  margin-bottom: 16px;
}

.problem-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
  min-height: 200px;
}
.problem-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.problem-card:hover {
  box-shadow: var(--el-box-shadow-light);
}
.problem-card.is-selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary);
}

.cover-box {
  position: relative;
  width: 100%;
  aspect-ratio: 2 / 3;
  background: var(--el-fill-color-light);
  cursor: pointer;
}
.cover-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cover-check {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 2;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 4px;
  padding: 2px;
}
.cover-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--el-text-color-placeholder);
  font-size: 13px;
}
.cover-placeholder .el-icon {
  font-size: 32px;
}
.cover-badge {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 4px 8px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.72));
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

.card-body {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card-title {
  font-size: 13px;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-badges {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}
.card-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
