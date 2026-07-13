<template>
  <div class="fingerprint-page">
    <el-card class="status-card">
      <div class="status-row">
        <el-statistic title="有文件影片" :value="status.total_movies" />
        <el-statistic title="已计算指纹" :value="status.with_fingerprint" />
        <el-statistic title="待计算" :value="status.without_fingerprint" />
        <div class="coverage">
          <div class="coverage-label">覆盖率</div>
          <el-progress :percentage="coveragePercent" :color="coverageColor" />
        </div>
      </div>
      <div class="action-row">
        <el-button type="primary" @click="scanAll" :loading="scanning">
          批量计算指纹
        </el-button>
        <el-input-number v-model="scanLimit" :min="1" :max="500" />
        <span style="color: #909399; font-size: 13px">每次最多处理数量</span>
      </div>
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <span>重复影片检测</span>
          <div class="dup-controls">
            <span style="font-size: 13px; color: #909399">汉明距离阈值：</span>
            <el-input-number v-model="threshold" :min="0" :max="20" size="small" style="width: 100px" />
            <el-button size="small" type="primary" @click="loadDuplicates" :loading="loadingDups">查找重复</el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="!duplicates.length" description="暂无重复影片" />
      <el-table v-else :data="duplicates" border>
        <el-table-column label="影片 1" min-width="200">
          <template #default="{ row }">
            <div class="dup-movie">
              <div class="dup-code">{{ row.movie_1.code }}</div>
              <div class="dup-path">{{ row.movie_1.file_path }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="影片 2" min-width="200">
          <template #default="{ row }">
            <div class="dup-movie">
              <div class="dup-code">{{ row.movie_2.code }}</div>
              <div class="dup-path">{{ row.movie_2.file_path }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="汉明距离" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.hamming_distance === 0 ? 'danger' : 'warning'">
              {{ row.hamming_distance }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { fingerprintStatus, scanFingerprints, findDuplicates } from '@/api'

const status = ref({ total_movies: 0, with_fingerprint: 0, without_fingerprint: 0, coverage: '0%' })
const scanning = ref(false)
const scanLimit = ref(50)
const threshold = ref(5)
const duplicates = ref([])
const loadingDups = ref(false)

const coveragePercent = computed(() => {
  if (!status.value.total_movies) return 0
  return Math.round(status.value.with_fingerprint / status.value.total_movies * 100)
})

const coverageColor = computed(() => {
  if (coveragePercent.value >= 80) return '#67c23a'
  if (coveragePercent.value >= 50) return '#e6a23c'
  return '#f56c6c'
})

const loadStatus = async () => {
  try {
    const res = await fingerprintStatus()
    status.value = res.items ? res : (res.data || res)
  } catch (e) {
    ElMessage.error('加载指纹状态失败')
  }
}

const scanAll = async () => {
  scanning.value = true
  try {
    const res = await scanFingerprints(scanLimit.value)
    const data = res.items ? res : (res.data || res)
    ElMessage.success(`已排队 ${data.queued} 个影片进行指纹计算`)
    setTimeout(() => loadStatus(), 3000)
  } catch (e) {
    ElMessage.error('扫描失败')
  } finally {
    scanning.value = false
  }
}

const loadDuplicates = async () => {
  loadingDups.value = true
  try {
    const res = await findDuplicates(threshold.value)
    const data = res.items ? res : (res.data || res)
    duplicates.value = data.duplicates || []
    if (data.duplicate_count > 0) {
      ElMessage.info(`找到 ${data.duplicate_count} 组重复影片`)
    }
  } catch (e) {
    ElMessage.error('查找重复失败')
  } finally {
    loadingDups.value = false
  }
}

onMounted(() => {
  loadStatus()
  loadDuplicates()
})
</script>

<style scoped>
.fingerprint-page {
  max-width: 900px;
  margin: 0 auto;
}
.status-row {
  display: flex;
  gap: 40px;
  align-items: center;
  margin-bottom: 20px;
}
.coverage {
  flex: 1;
  min-width: 200px;
}
.coverage-label {
  font-size: 14px;
  color: #606266;
  margin-bottom: 8px;
}
.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.dup-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dup-movie {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dup-code {
  font-weight: bold;
  color: #409eff;
}
.dup-path {
  font-size: 12px;
  color: #909399;
  word-break: break-all;
}
</style>
