<template>
  <div class="qg-page">
    <h2>高清版目标</h2>
    <p class="page-desc">
      给某部片子设定「想要更高清版本」，替换文件后检测是否达成。基于 ffprobe 现场读取分辨率。
    </p>

    <!-- 新增表单 -->
    <el-card shadow="never" class="add-card">
      <el-form :inline="true" :model="form">
        <el-form-item label="模块">
          <el-select v-model="form.module" style="width: 140px">
            <el-option v-for="m in moduleOptions" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标清晰度">
          <el-select v-model="form.target_height" style="width: 140px">
            <el-option v-for="p in presets" :key="p.height" :label="p.label" :value="p.height" />
          </el-select>
        </el-form-item>
        <el-form-item label="番号（每行一个）">
          <el-input
            v-model="form.codes" type="textarea" :rows="1"
            style="width: 320px" placeholder="ABC-123&#10;DEF-456"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Plus" :loading="adding" @click="addGoal">添加目标</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 操作栏 -->
    <el-card shadow="never" class="toolbar-card">
      <el-radio-group v-model="filterStatus" @change="loadGoals">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="open">待达成</el-radio-button>
        <el-radio-button label="fulfilled">已达成</el-radio-button>
        <el-radio-button label="dropped">已放弃</el-radio-button>
      </el-radio-group>
      <el-button :icon="Refresh" :loading="checking" @click="checkAll" style="margin-left: 12px">
        全部检测（ffprobe）
      </el-button>
    </el-card>

    <!-- 列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="goals" v-loading="loading" stripe>
        <el-table-column prop="code" label="番号" width="150" />
        <el-table-column prop="module" label="模块" width="90" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column label="目标" width="110">
          <template #default="{ row }">
            <el-tag type="warning" effect="dark">{{ row.target_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前" width="110">
          <template #default="{ row }">
            <span v-if="row.current_label">{{ row.current_label }}</span>
            <span v-else class="muted">未检测</span>
          </template>
        </el-table-column>
        <el-table-column label="达成" width="90">
          <template #default="{ row }">
            <el-tag :type="row.reached ? 'success' : 'info'" effect="dark">
              {{ row.reached ? '已达成' : '未达成' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="checkOne(row)">检测</el-button>
            <el-button size="small" type="success" plain @click="markFulfilled(row)" v-if="row.status !== 'fulfilled'">标记达成</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && goals.length === 0" description="还没有高清版目标，先在上方添加" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  listQualityPresets, listQualityGoals, createQualityGoals,
  checkQualityGoal, checkAllQualityGoals, updateQualityGoal, deleteQualityGoal,
} from '@/api'

const presets = ref([])
const goals = ref([])
const loading = ref(false)
const adding = ref(false)
const checking = ref(false)
const filterStatus = ref('')
const form = reactive({ module: 'jav', target_height: 2160, codes: '' })
const moduleOptions = [
  { label: 'JAV有码', value: 'jav' },
  { label: 'JAV无码', value: 'uncensored' },
  { label: 'FC2', value: 'fc2' },
  { label: 'PORNHUB', value: 'pornhub' },
  { label: '里番', value: 'anime' },
  { label: '欧美', value: 'western' },
  { label: '国产', value: 'chinese' },
]

const loadPresets = async () => {
  try { const d = await listQualityPresets(); presets.value = d.presets || [] } catch (e) {}
}
const loadGoals = async () => {
  loading.value = true
  try {
    const d = await listQualityGoals({ status: filterStatus.value || undefined, limit: 200 })
    goals.value = d.items || []
  } catch (e) { /* */ } finally { loading.value = false }
}
const addGoal = async () => {
  const codes = form.codes.split('\n').map(s => s.trim()).filter(Boolean)
  if (!codes.length) { ElMessage.warning('请填写番号'); return }
  adding.value = true
  try {
    const res = await createQualityGoals({
      module: form.module, codes, target_height: form.target_height, note: '',
    })
    ElMessage.success(`已添加 ${res.created_count} 个${res.skipped_count ? `，跳过 ${res.skipped_count} 个已存在` : ''}`)
    form.codes = ''
    await loadGoals()
  } catch (e) { /* */ } finally { adding.value = false }
}
const checkOne = async (row) => {
  try {
    const res = await checkQualityGoal(row.id)
    Object.assign(row, res)
    ElMessage.success(res.reached ? '已达成目标' : `当前 ${res.current_label || '未探测到'}`)
  } catch (e) {}
}
const checkAll = async () => {
  checking.value = true
  try {
    const res = await checkAllQualityGoals(100)
    ElMessage.success(`检测 ${res.checked} 个，本次新达成 ${res.fulfilled_now} 个`)
    await loadGoals()
  } catch (e) { /* */ } finally { checking.value = false }
}
const markFulfilled = async (row) => {
  try {
    await updateQualityGoal(row.id, { status: 'fulfilled' })
    row.status = 'fulfilled'; ElMessage.success('已标记达成')
  } catch (e) {}
}
const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除目标 ${row.code}？`, '删除', { type: 'warning' })
    await deleteQualityGoal(row.id)
    goals.value = goals.value.filter(g => g.id !== row.id)
    ElMessage.success('已删除')
  } catch (e) {}
}

onMounted(() => { loadPresets(); loadGoals() })
</script>

<style scoped>
.qg-page { padding: 16px; }
.page-desc { color: var(--el-text-color-secondary); margin-bottom: 16px; }
.add-card { margin-bottom: 16px; }
.toolbar-card { margin-bottom: 16px; }
.list-card { border-radius: 8px; }
.muted { color: var(--el-text-color-secondary); }
</style>
