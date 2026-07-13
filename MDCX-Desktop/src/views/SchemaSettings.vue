<template>
  <div class="schema-settings">
    <!-- 顶部工具栏 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">
          <el-icon><Setting /></el-icon>
          Schema 驱动设置
        </h2>
        <div class="page-subtitle">基于 Pydantic 模型自动生成的配置表单 · 零手写表单</div>
      </div>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索配置项（标题/字段名/描述）"
          clearable
          style="width: 280px"
          :prefix-icon="Search"
        />
        <el-button @click="reloadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 重载
        </el-button>
        <el-button type="warning" @click="confirmReset" :disabled="!hasUnsavedChanges">
          <el-icon><RefreshLeft /></el-icon> 重置
        </el-button>
        <el-button type="primary" @click="saveCurrent" :loading="saving" :disabled="!hasUnsavedChanges">
          <el-icon><Check /></el-icon> 保存
        </el-button>
      </div>
    </div>

    <el-row :gutter="16" class="main-row">
      <!-- 左侧：配置段分组导航 -->
      <el-col :span="5">
        <el-card shadow="never" class="nav-card" v-loading="loading">
          <template #header>
            <div class="card-title">
              <el-icon><Menu /></el-icon> 配置段
            </div>
          </template>
          <el-input
            v-model="filterText"
            placeholder="过滤配置段..."
            size="small"
            clearable
            style="margin-bottom: 8px"
          />
          <el-tree
            ref="treeRef"
            :data="treeData"
            :props="treeProps"
            node-key="key"
            highlight-current
            default-expand-all
            :filter-node-method="filterNode"
            @node-click="onNodeClick"
            class="nav-tree"
          >
            <template #default="{ node, data }">
              <span class="tree-node">
                <span class="tree-label">{{ node.label }}</span>
                <el-tag v-if="data.section && dirtySections.has(data.section)" size="small" type="warning" class="dirty-tag">
                  未保存
                </el-tag>
              </span>
            </template>
          </el-tree>
        </el-card>
      </el-col>

      <!-- 右侧：表单区 -->
      <el-col :span="19">
        <el-card shadow="never" class="form-card" v-loading="loading">
          <template #header>
            <div class="card-title">
              <el-icon><Document /></el-icon>
              <span v-if="currentSection">
                {{ currentSectionSchema?.title || currentSection }}
                <el-tag size="small" type="info" style="margin-left: 8px">
                  {{ currentSection }}
                </el-tag>
              </span>
              <span v-else>请选择配置段</span>
              <div class="header-actions" v-if="currentSection">
                <el-button size="small" @click="resetCurrent" :disabled="!dirtySections.has(currentSection)">
                  恢复当前段
                </el-button>
                <el-button size="small" type="primary" @click="saveCurrent" :loading="saving" :disabled="!dirtySections.has(currentSection)">
                  保存当前段
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="!currentSection" class="empty-state">
            <el-empty description="请从左侧选择配置段" />
          </div>

          <div v-else-if="currentSectionSchema" class="form-area">
            <SchemaForm
              :schema="currentSectionSchema"
              :model-value="currentEditingValues"
              :search-keyword="searchKeyword"
              @update:model-value="onFormUpdate"
            />
          </div>

          <div v-else class="empty-state">
            <el-empty description="该配置段无 schema" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 底部未保存提示 -->
    <div v-if="dirtySections.size > 0" class="unsaved-bar">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ dirtySections.size }} 个配置段有未保存的变更：</span>
      <el-tag
        v-for="sec in Array.from(dirtySections)"
        :key="sec"
        size="small"
        type="warning"
        style="margin: 0 4px; cursor: pointer"
        @click="selectSection(sec)"
      >
        {{ sectionTitle(sec) }}
      </el-tag>
      <div style="margin-left: auto; display: flex; gap: 8px">
        <el-button size="small" @click="reloadAll">放弃所有变更</el-button>
        <el-button size="small" type="primary" @click="saveAllDirty" :loading="saving">
          保存全部
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Setting, Refresh, RefreshLeft, Check, Search, Menu, Document, WarningFilled
} from '@element-plus/icons-vue'
import SchemaForm from '@/components/SchemaForm.vue'
import {
  getConfigSchema, getConfigValues, updateConfigSectionValues
} from '@/api'

// ===== 数据状态 =====
const loading = ref(false)
const saving = ref(false)
const searchKeyword = ref('')
const filterText = ref('')

// 所有 schema 数据（按分组组织）
const schemaGroups = ref([])
// 所有当前值（section -> values）
const allValues = ref({})
// 编辑中的值（section -> values） - 与 allValues 不同表示有未保存变更
const editingValues = ref({})

const treeRef = ref()
const currentSection = ref('')

// ===== 树形数据 =====
const treeProps = {
  label: 'label',
  children: 'children'
}

const treeData = computed(() => {
  return schemaGroups.value.map((g) => ({
    key: `group::${g.group}`,
    label: g.group,
    children: g.sections.map((s) => ({
      key: `section::${s.section}`,
      label: s.title || s.section,
      section: s.section,
      isLeaf: true
    }))
  }))
})

// ===== 计算属性 =====
const currentSectionSchema = computed(() => {
  if (!currentSection.value) return null
  for (const g of schemaGroups.value) {
    for (const s of g.sections) {
      if (s.section === currentSection.value) return s
    }
  }
  return null
})

const currentEditingValues = computed(() => {
  if (!currentSection.value) return {}
  return editingValues.value[currentSection.value] || {}
})

// 有未保存变更的段
const dirtySections = computed(() => {
  const dirty = new Set()
  for (const sec of Object.keys(editingValues.value)) {
    const editing = editingValues.value[sec]
    const original = allValues.value[sec]
    if (!original || !editing) continue
    if (JSON.stringify(editing) !== JSON.stringify(original)) {
      dirty.add(sec)
    }
  }
  return dirty
})

const hasUnsavedChanges = computed(() => dirtySections.value.size > 0)

// ===== 节点点击 =====
const onNodeClick = (data) => {
  if (data.section) {
    currentSection.value = data.section
  }
}

const selectSection = (sec) => {
  currentSection.value = sec
  // 在树中高亮
  if (treeRef.value) {
    treeRef.value.setCurrentKey(`section::${sec}`)
  }
}

// ===== 表单更新 =====
const onFormUpdate = (newValues) => {
  if (!currentSection.value) return
  editingValues.value = {
    ...editingValues.value,
    [currentSection.value]: newValues
  }
}

// ===== 加载数据 =====
const loadSchema = async () => {
  const data = await getConfigSchema()
  schemaGroups.value = data.groups || []
}

const loadValues = async () => {
  const data = await getConfigValues()
  allValues.value = data || {}
  // 深拷贝到 editingValues
  editingValues.value = JSON.parse(JSON.stringify(allValues.value))
}

const reloadAll = async () => {
  if (hasUnsavedChanges.value) {
    try {
      await ElMessageBox.confirm('有未保存的变更，确认放弃并重新加载？', '警告', {
        type: 'warning'
      })
    } catch {
      return
    }
  }
  loading.value = true
  try {
    await Promise.all([loadSchema(), loadValues()])
    ElMessage.success('已重载配置')
    // 默认选第一个段
    if (!currentSection.value && schemaGroups.value.length > 0) {
      const firstGroup = schemaGroups.value[0]
      if (firstGroup.sections.length > 0) {
        selectSection(firstGroup.sections[0].section)
      }
    }
  } catch (e) {
    console.error('加载失败', e)
  } finally {
    loading.value = false
  }
}

// ===== 保存 =====
const saveCurrent = async () => {
  if (!currentSection.value || !dirtySections.value.has(currentSection.value)) {
    ElMessage.info('当前段无未保存变更')
    return
  }
  await saveSection(currentSection.value)
}

const saveSection = async (section) => {
  saving.value = true
  try {
    const values = editingValues.value[section]
    const res = await updateConfigSectionValues(section, values)
    // 用服务端返回的值更新
    allValues.value = { ...allValues.value, [section]: res.values }
    editingValues.value = {
      ...editingValues.value,
      [section]: JSON.parse(JSON.stringify(res.values))
    }
    ElMessage.success(`配置段「${sectionTitle(section)}」已保存`)
  } catch (e) {
    console.error('保存失败', e)
    ElMessage.error(`保存失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    saving.value = false
  }
}

const saveAllDirty = async () => {
  const sections = Array.from(dirtySections.value)
  if (sections.length === 0) {
    ElMessage.info('无未保存变更')
    return
  }
  saving.value = true
  let success = 0
  let failed = 0
  for (const sec of sections) {
    try {
      const values = editingValues.value[sec]
      const res = await updateConfigSectionValues(sec, values)
      allValues.value = { ...allValues.value, [sec]: res.values }
      editingValues.value = {
        ...editingValues.value,
        [sec]: JSON.parse(JSON.stringify(res.values))
      }
      success++
    } catch (e) {
      console.error(`保存 ${sec} 失败`, e)
      failed++
    }
  }
  saving.value = false
  if (failed === 0) {
    ElMessage.success(`全部保存成功（共 ${success} 段）`)
  } else {
    ElMessage.warning(`保存完成：成功 ${success} / 失败 ${failed}`)
  }
}

// ===== 重置 =====
const resetCurrent = () => {
  if (!currentSection.value) return
  editingValues.value = {
    ...editingValues.value,
    [currentSection.value]: JSON.parse(JSON.stringify(allValues.value[currentSection.value] || {}))
  }
  ElMessage.info('已恢复当前段为最后保存的值')
}

const confirmReset = async () => {
  try {
    await ElMessageBox.confirm(
      '确认放弃所有未保存的变更并重新加载？',
      '警告',
      { type: 'warning' }
    )
    await loadValues()
    ElMessage.success('已恢复所有未保存变更')
  } catch {
    // 用户取消
  }
}

// ===== 树过滤 =====
const filterNode = (value, data) => {
  if (!value) return true
  const kw = value.toLowerCase()
  return (
    (data.label || '').toLowerCase().includes(kw) ||
    (data.section || '').toLowerCase().includes(kw)
  )
}

watch(filterText, (val) => {
  if (treeRef.value) {
    treeRef.value.filter(val)
  }
})

// ===== 工具 =====
const sectionTitle = (sec) => {
  for (const g of schemaGroups.value) {
    for (const s of g.sections) {
      if (s.section === sec) return s.title || sec
    }
  }
  return sec
}

// ===== 初始化 =====
onMounted(async () => {
  await reloadAll()
})
</script>

<style scoped>
.schema-settings {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: calc(100vh - 60px);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 16px 20px;
  background: linear-gradient(135deg, #ffffff 0%, #f5f7fa 100%);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 20px;
  color: #303133;
}

.page-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-left: auto;
}

.main-row {
  flex: 1;
  margin-bottom: 16px;
}

.nav-card,
.form-card {
  border-radius: 8px;
  border: 1px solid #ebeef5;
  height: 100%;
}

.nav-card {
  max-height: calc(100vh - 220px);
  overflow: auto;
}

.form-card {
  max-height: calc(100vh - 220px);
  overflow: auto;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #303133;
}

.nav-tree {
  background: transparent;
}

.tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 8px;
}

.tree-label {
  flex: 1;
}

.dirty-tag {
  margin-left: 8px;
  transform: scale(0.85);
}

.empty-state {
  padding: 60px 20px;
}

.form-area {
  padding: 8px 4px;
}

.unsaved-bar {
  position: sticky;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fffbe6;
  border-top: 1px solid #faecd8;
  border-radius: 8px 8px 0 0;
  color: #e6a23c;
  font-size: 13px;
  box-shadow: 0 -2px 8px rgba(230, 162, 60, 0.1);
  z-index: 10;
}

:deep(.el-tree-node__content) {
  height: 32px;
}

:deep(.el-tree-node.is-current > .el-tree-node__content) {
  background-color: #ecf5ff;
  color: #409eff;
}
</style>
