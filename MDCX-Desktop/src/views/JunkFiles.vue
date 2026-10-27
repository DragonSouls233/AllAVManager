<template>
  <div class="junk-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <h2 class="page-title">
          <el-icon><Delete /></el-icon>
          垃圾文件检测
        </h2>
        <el-button type="primary" :loading="scanning" @click="doScan">
          <el-icon><Search /></el-icon> 扫描
        </el-button>
        <el-button :disabled="!chosen.length" @click="recycleChosen">
          <el-icon><Delete /></el-icon> 移入回收站（{{ chosen.length }}）
        </el-button>
      </div>
      <div class="hint">只读扫描配置的媒体目录，识别样本片 / 预告片 / 广告推广 / 系统垃圾。删除走回收站，可恢复。</div>
    </el-card>

    <div v-loading="scanning">
      <el-card v-if="result" shadow="never" class="summary-card">
        <el-tag type="danger">共 {{ result.total }} 个</el-tag>
        <el-tag>占用 {{ result.total_size_human }}</el-tag>
        <el-tag v-if="result.limited" type="warning">已达扫描上限</el-tag>
        <el-tag v-for="(v, k) in result.by_reason" :key="k" effect="plain">
          {{ reasonLabel(k) }} {{ v.count }}
        </el-tag>
      </el-card>

      <el-card v-for="(v, k) in result?.by_reason || {}" :key="k" shadow="never" class="reason-card">
        <div class="reason-head">
          <span class="reason-name">{{ reasonLabel(k) }}</span>
          <span class="reason-size">{{ humanSize(v.total_size) }}</span>
          <span class="reason-count">{{ v.count }} 个</span>
        </div>
        <el-table :data="v.items" size="small" @selection-change="(rows) => onSel(k, rows)">
          <el-table-column type="selection" width="40" />
          <el-table-column prop="path" label="路径" show-overflow-tooltip />
          <el-table-column prop="size" label="大小" width="110">
            <template #default="{ row }">{{ humanSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click="recycle([row.path])">回收</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-empty v-if="result && !result.total" description="未检测到垃圾文件" />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { scanJunkFiles, trashAdResidue } from '@/api'

const scanning = ref(false)
const result = ref(null)
const selected = ref({})  // reason -> [path]
const chosen = ref([])

async function doScan() {
  scanning.value = true
  selected.value = {}
  chosen.value = []
  try {
    const d = await scanJunkFiles({})
    result.value = d
    ElMessage.success(`扫描完成，命中 ${d.total} 个`)
  } catch (e) {
    ElMessage.error('扫描失败')
  } finally {
    scanning.value = false
  }
}

function onSel(reason, rows) {
  selected.value[reason] = rows.map(r => r.path)
  chosen.value = Object.values(selected.value).flat()
}

function reasonLabel(k) {
  return { sample: '样本片', trailer: '预告片', ad: '广告/推广', system: '系统垃圾' }[k] || k
}
function humanSize(n) {
  if (!n) return '0B'
  let x = n; const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (x >= 1024 && i < u.length - 1) { x /= 1024; i++ }
  return i === 0 ? `${x}B` : `${x.toFixed(1)}${u[i]}`
}

async function recycle(paths) {
  try {
    await trashAdResidue(paths)
    ElMessage.success(`已移入回收站 ${paths.length} 个`)
    doScan()
  } catch (e) {
    ElMessage.error('移入回收站失败')
  }
}
async function recycleChosen() {
  if (!chosen.value.length) return
  await recycle(chosen.value)
}
</script>

<style scoped>
.junk-page { padding: 16px; }
.toolbar { display: flex; align-items: center; gap: 10px; }
.page-title { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 18px; }
.hint { font-size: 12px; opacity: 0.65; margin-top: 8px; }
.summary-card { margin: 12px 0; display: flex; gap: 8px; flex-wrap: wrap; }
.reason-card { margin-bottom: 12px; }
.reason-head { display: flex; gap: 16px; align-items: baseline; margin-bottom: 10px; font-weight: 600; }
.reason-name { font-size: 15px; }
.reason-size { color: #fbbf24; font-size: 13px; }
.reason-count { color: #9aa3b2; font-size: 13px; }
</style>
