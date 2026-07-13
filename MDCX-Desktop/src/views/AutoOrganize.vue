<template>
  <div class="page">
    <!-- 页面标题区 -->
    <div class="page-header">
      <div class="page-header__text">
        <h2>自动整理规则</h2>
        <p class="desc">根据播放次数 / 评分 / 观看状态等条件，自动将影片移动、复制或链接到指定目录</p>
      </div>
      <div class="page-header__actions">
        <el-button type="primary" :icon="Plus" @click="openCreateDialog">新建规则</el-button>
        <el-button :icon="Promotion" :loading="checking" @click="triggerCheck">手动触发检查</el-button>
      </div>
    </div>

    <!-- 规则列表 -->
    <div class="section-card" v-loading="loading">
      <el-skeleton v-if="firstLoading" :rows="5" animated />
      <template v-else>
        <el-empty v-if="rules.length === 0" description="暂无自动整理规则，点击右上角“新建规则”开始配置" />
        <el-table v-else :data="rules" stripe row-key="id" style="width: 100%">
          <el-table-column prop="name" label="规则名称" min-width="160">
            <template #default="{ row }">
              <span class="rule-name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="条件" min-width="240">
            <template #default="{ row }">
              <span class="condition-text">
                <el-tag size="small" type="info" effect="plain">{{ fieldLabel(row.condition_field) }}</el-tag>
                <span class="op">{{ opLabel(row.condition_op) }}</span>
                <code class="value">{{ row.condition_value }}</code>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="动作" width="140">
            <template #default="{ row }">
              <el-tag :type="actionTagType(row.action)" size="small">
                <el-icon class="action-icon"><component :is="actionIcon(row.action)" /></el-icon>
                {{ actionLabel(row.action) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="target_path" label="目标路径" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="target-path">{{ row.target_path || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="90" align="center">
            <template #default="{ row }">
              <el-switch
                v-model="row.enabled"
                @change="(val) => toggleEnabled(row, val)"
                :loading="row._switching"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" :icon="Edit" @click="openEditDialog(row)">编辑</el-button>
              <el-button text type="danger" :icon="Delete" @click="confirmDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>

    <!-- 新建 / 编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建规则' : '编辑规则'"
      width="640px"
      :close-on-click-modal="false"
      @closed="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="110px"
        label-position="right"
      >
        <el-form-item label="规则名称" prop="name">
          <el-input v-model="form.name" placeholder="如：高分影片归档" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item label="条件字段" prop="condition_field">
          <el-select v-model="form.condition_field" placeholder="选择条件字段" style="width: 100%">
            <el-option v-for="opt in fieldOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="条件操作符" prop="condition_op">
          <el-select v-model="form.condition_op" placeholder="选择操作符" style="width: 100%">
            <el-option v-for="opt in opOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="条件值" prop="condition_value">
          <el-input v-model="form.condition_value" placeholder="如：5 / 已观看 / 8.0" />
        </el-form-item>
        <el-form-item label="执行动作" prop="action">
          <el-select v-model="form.action" placeholder="选择执行动作" style="width: 100%">
            <el-option v-for="opt in actionOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标路径" prop="target_path">
          <el-input v-model="form.target_path" placeholder="如 O:\MDCX\Library\高分">
            <template #append>
              <el-button :icon="FolderOpened" :loading="pickingDir" @click="pickDirectory">选择</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="启用规则">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Edit, Delete, Promotion, FolderOpened,
  Rank, CopyDocument, Switch, Link
} from '@element-plus/icons-vue'
import {
  getAutoOrganizeRules,
  createAutoOrganizeRule,
  updateAutoOrganizeRule,
  deleteAutoOrganizeRule,
  triggerAutoOrganizeCheck
} from '@/api'

// ====== 常量映射 ======
const fieldOptions = [
  { value: 'play_count', label: '播放次数 (play_count)' },
  { value: 'rating', label: '评分 (rating)' },
  { value: 'view_status', label: '观看状态 (view_status)' }
]
const opOptions = [
  { value: 'eq', label: '等于 (=)' },
  { value: 'ne', label: '不等于 (≠)' },
  { value: 'gt', label: '大于 (>)' },
  { value: 'lt', label: '小于 (<)' },
  { value: 'ge', label: '大于等于 (≥)' },
  { value: 'le', label: '小于等于 (≤)' },
  { value: 'contains', label: '包含' },
  { value: 'regex', label: '正则匹配' },
  { value: 'in', label: '属于（逗号分隔）' }
]
const actionOptions = [
  { value: 'move', label: '移动 (move)' },
  { value: 'copy', label: '复制 (copy)' },
  { value: 'hardlink', label: '硬链接 (hardlink)' },
  { value: 'symlink', label: '软链接 (symlink)' }
]

const fieldLabel = (v) => fieldOptions.find(o => o.value === v)?.label || v
const opLabel = (v) => opOptions.find(o => o.value === v)?.label || v
const actionLabel = (v) => actionOptions.find(o => o.value === v)?.label || v
const actionTagType = (a) => ({ move: 'warning', copy: 'info', hardlink: 'primary', symlink: 'success' }[a] || '')
const actionIcon = (a) => ({ move: Rank, copy: CopyDocument, hardlink: Switch, symlink: Link }[a] || Rank)

// ====== 状态 ======
const rules = ref([])
const loading = ref(false)
const firstLoading = ref(true)
const checking = ref(false)
const pickingDir = ref(false)

// 对话框
const dialogVisible = ref(false)
const dialogMode = ref('create') // create | edit
const editingId = ref(null)
const submitting = ref(false)
const formRef = ref(null)

const defaultForm = () => ({
  name: '',
  condition_field: 'play_count',
  condition_op: 'gt',
  condition_value: '',
  action: 'move',
  target_path: '',
  enabled: true
})
const form = reactive(defaultForm())

const formRules = {
  name: [{ required: true, message: '请输入规则名称', trigger: 'blur' }],
  condition_field: [{ required: true, message: '请选择条件字段', trigger: 'change' }],
  condition_op: [{ required: true, message: '请选择条件操作符', trigger: 'change' }],
  condition_value: [{ required: true, message: '请输入条件值', trigger: 'blur' }],
  action: [{ required: true, message: '请选择执行动作', trigger: 'change' }],
  target_path: [{ required: true, message: '请输入或选择目标路径', trigger: 'blur' }]
}

// ====== 数据加载 ======
const loadRules = async () => {
  loading.value = true
  try {
    const data = await getAutoOrganizeRules()
    // 后端可能返回数组或 { items: [...] }
    const list = Array.isArray(data) ? data : (data?.items || data?.rules || [])
    rules.value = list.map(r => ({ ...r, _switching: false }))
  } catch (e) {
    // 错误信息已由 axios 拦截器统一提示
  } finally {
    loading.value = false
    firstLoading.value = false
  }
}

// ====== 切换启用状态 ======
const toggleEnabled = async (row, val) => {
  row._switching = true
  try {
    await updateAutoOrganizeRule(row.id, { enabled: val })
    ElMessage.success(`规则【${row.name}】已${val ? '启用' : '停用'}`)
  } catch (e) {
    // 失败时回滚
    row.enabled = !val
  } finally {
    row._switching = false
  }
}

// ====== 新建 / 编辑 ======
const openCreateDialog = () => {
  dialogMode.value = 'create'
  editingId.value = null
  Object.assign(form, defaultForm())
  dialogVisible.value = true
}

const openEditDialog = (row) => {
  dialogMode.value = 'edit'
  editingId.value = row.id
  Object.assign(form, {
    name: row.name ?? '',
    condition_field: row.condition_field ?? 'play_count',
    condition_op: row.condition_op ?? 'gt',
    condition_value: row.condition_value ?? '',
    action: row.action ?? 'move',
    target_path: row.target_path ?? '',
    enabled: row.enabled ?? true
  })
  dialogVisible.value = true
}

const resetForm = () => {
  formRef.value?.resetFields()
  Object.assign(form, defaultForm())
  editingId.value = null
  dialogMode.value = 'create'
}

const submitForm = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      const payload = {
        name: form.name,
        condition_field: form.condition_field,
        condition_op: form.condition_op,
        condition_value: form.condition_value,
        action: form.action,
        target_path: form.target_path,
        enabled: form.enabled
      }
      if (dialogMode.value === 'create') {
        await createAutoOrganizeRule(payload)
        ElMessage.success('规则创建成功')
      } else {
        await updateAutoOrganizeRule(editingId.value, payload)
        ElMessage.success('规则更新成功')
      }
      dialogVisible.value = false
      await loadRules()
    } catch (e) {
      // 错误已由拦截器统一提示
    } finally {
      submitting.value = false
    }
  })
}

// ====== 删除 ======
const confirmDelete = (row) => {
  ElMessageBox.confirm(
    `确认删除规则【${row.name}】？该操作不可恢复。`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await deleteAutoOrganizeRule(row.id)
      ElMessage.success('规则已删除')
      await loadRules()
    } catch (e) {
      // 错误已由拦截器统一提示
    }
  }).catch(() => { /* 取消 */ })
}

// ====== 手动触发检查 ======
const triggerCheck = async () => {
  checking.value = true
  try {
    const data = await triggerAutoOrganizeCheck()
    // 后端可能返回 { success, failed, skipped, ... }
    const success = data?.success ?? data?.completed ?? 0
    const failed = data?.failed ?? 0
    const skipped = data?.skipped ?? 0
    ElMessage.success(`检查完成：成功 ${success} / 失败 ${failed} / 跳过 ${skipped}`)
    await loadRules()
  } catch (e) {
    // 错误已由拦截器统一提示
  } finally {
    checking.value = false
  }
}

// ====== 目录选择（Electron 环境） ======
const pickDirectory = async () => {
  pickingDir.value = true
  try {
    if (window.electronAPI && window.electronAPI.selectDirectory) {
      const dir = await window.electronAPI.selectDirectory()
      if (dir) form.target_path = dir
    } else {
      ElMessage.info('当前环境不支持目录选择，请手动输入路径')
    }
  } catch (e) {
    ElMessage.error('目录选择失败')
  } finally {
    pickingDir.value = false
  }
}

onMounted(() => {
  loadRules()
})
</script>

<style scoped>
.page {
  padding: var(--space-4, 16px);
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.page-header__text h2 {
  margin: 0 0 6px 0;
  font-size: 20px;
  font-weight: 600;
}
.page-header__text .desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.page-header__actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.section-card {
  background: var(--el-bg-color, #fff);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--el-border-color-light, #ebeef5);
  min-height: 200px;
}
.rule-name {
  font-weight: 500;
  color: var(--el-text-color-primary);
}
.condition-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.condition-text .op {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.condition-text .value {
  background: var(--el-fill-color-light, #f5f7fa);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  font-family: var(--el-font-family-mono, monospace);
}
.action-icon {
  margin-right: 4px;
  vertical-align: middle;
}
.target-path {
  color: var(--el-text-color-regular);
  font-family: var(--el-font-family-mono, monospace);
  font-size: 12px;
  word-break: break-all;
}
</style>
