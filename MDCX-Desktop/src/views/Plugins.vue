<template>
  <div class="plugins-page">
    <div class="page-header">
      <div class="header-title">
        <h2>插件系统</h2>
        <p class="muted">爬虫 / 翻译引擎 / 整理规则 / 通知器 插件化管理</p>
      </div>
      <div class="header-actions">
        <el-button @click="loadPlugins" :icon="Refresh">刷新</el-button>
        <el-button type="primary" @click="reloadAll" :loading="reloading">
          <el-icon><RefreshRight /></el-icon> 重载全部
        </el-button>
        <el-button type="success" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon> 新建插件
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeType" @tab-change="loadPlugins">
      <el-tab-pane
        v-for="t in pluginTypes" :key="t.value"
        :label="`${t.label} (${countByType(t.value)})`"
        :name="t.value"
      />
    </el-tabs>

    <el-table :data="filteredPlugins" v-loading="loading" border stripe>
      <el-table-column label="名称" min-width="180">
        <template #default="{ row }">
          <div class="plugin-name">
            <span class="name">{{ row.display_name || row.name }}</span>
            <el-tag size="small" type="info">{{ row.name }}</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="90" prop="version" />
      <el-table-column label="作者" width="120" prop="author" />
      <el-table-column label="描述" min-width="220" show-overflow-tooltip prop="description" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="statusTagType(row.status)"
            size="small"
          >{{ statusLabel(row.status) }}</el-tag>
          <el-tooltip v-if="row.error" :content="row.error" placement="top">
            <el-icon class="error-icon"><WarningFilled /></el-icon>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            :type="row.enabled ? 'warning' : 'success'"
            @click="toggleEnabled(row)"
          >{{ row.enabled ? '禁用' : '启用' }}</el-button>
          <el-button size="small" @click="openDetail(row)">
            <el-icon><View /></el-icon> 详情
          </el-button>
          <el-button size="small" @click="onReloadPlugin(row)">
            <el-icon><Refresh /></el-icon> 重载
          </el-button>
          <el-button size="small" type="danger" @click="removePlugin(row)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="detailVisible"
      size="60%"
      :title="`插件详情 - ${currentPlugin?.display_name || currentPlugin?.name || ''}`"
      direction="rtl"
    >
      <div v-loading="detailLoading" class="plugin-detail">
        <el-tabs v-model="detailTab">
          <el-tab-pane label="基本信息" name="info">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="名称">{{ detail.info?.display_name }}</el-descriptions-item>
              <el-descriptions-item label="标识">{{ detail.info?.name }}</el-descriptions-item>
              <el-descriptions-item label="类型">{{ detail.info?.plugin_type }}</el-descriptions-item>
              <el-descriptions-item label="版本">{{ detail.info?.version }}</el-descriptions-item>
              <el-descriptions-item label="作者">{{ detail.info?.author }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ detail.info?.status }}</el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ detail.info?.description }}</el-descriptions-item>
              <el-descriptions-item label="文件路径" :span="2">
                <code>{{ detail.info?.file_path }}</code>
              </el-descriptions-item>
              <el-descriptions-item v-if="detail.info?.error" label="错误" :span="2">
                <span class="error-text">{{ detail.info?.error }}</span>
              </el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>

          <el-tab-pane label="配置" name="config">
            <el-alert
              type="info"
              :closable="false"
              title="JSON 配置，根据 config_schema 编辑"
              style="margin-bottom: 12px"
            />
            <el-input
              v-model="configText"
              type="textarea"
              :rows="14"
              placeholder="输入 JSON 格式配置"
            />
            <div style="margin-top: 12px">
              <el-button type="primary" @click="saveConfig" :loading="savingConfig">
                保存配置
              </el-button>
              <el-button @click="formatConfig">格式化 JSON</el-button>
            </div>
            <el-divider>配置 Schema</el-divider>
            <pre class="schema-block">{{ JSON.stringify(detail.config_schema, null, 2) }}</pre>
          </el-tab-pane>

          <el-tab-pane label="源代码" name="source">
            <pre class="source-block">{{ detail.source_code }}</pre>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <!-- 创建插件对话框 -->
    <el-dialog v-model="showCreateDialog" title="新建插件" width="500px">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="类型" required>
          <el-select v-model="createForm.plugin_type" placeholder="选择类型" style="width: 100%">
            <el-option
              v-for="t in pluginTypes" :key="t.value"
              :label="t.label" :value="t.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input
            v-model="createForm.name"
            placeholder="英文标识，如 my_crawler"
          />
          <small class="muted">仅字母/数字/下划线，将成为文件名</small>
        </el-form-item>
        <el-form-item label="覆盖已存在">
          <el-switch v-model="createForm.force" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createPlugin" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh, RefreshRight, Plus, View, Delete, WarningFilled
} from '@element-plus/icons-vue'
import {
  listPlugins, getPluginDetail, enablePlugin, disablePlugin,
  reloadPlugin, reloadAllPlugins, updatePluginConfig,
  createPluginTemplate, deletePlugin
} from '@/api'

const pluginTypes = [
  { label: '爬虫', value: 'crawler' },
  { label: '翻译引擎', value: 'translator' },
  { label: '整理规则', value: 'organizer' },
  { label: '通知器', value: 'notifier' },
]

const activeType = ref('crawler')
const plugins = ref([])
const loading = ref(false)
const reloading = ref(false)

// 详情
const detailVisible = ref(false)
const detailLoading = ref(false)
const currentPlugin = ref(null)
const detail = ref({ info: null, config: {}, config_schema: {}, source_code: '' })
const detailTab = ref('info')
const configText = ref('')
const savingConfig = ref(false)

// 创建
const showCreateDialog = ref(false)
const createForm = reactive({ plugin_type: 'crawler', name: '', force: false })
const creating = ref(false)

const filteredPlugins = computed(() =>
  plugins.value.filter(p => p.plugin_type === activeType.value)
)

const countByType = (type) => plugins.value.filter(p => p.plugin_type === type).length

const statusTagType = (s) => ({
  enabled: 'success',
  disabled: 'info',
  error: 'danger',
  loaded: '',
}[s] || '')

const statusLabel = (s) => ({
  enabled: '已启用',
  disabled: '已禁用',
  error: '错误',
  loaded: '已加载',
}[s] || s)

const loadPlugins = async () => {
  loading.value = true
  try {
    const res = await listPlugins()
    plugins.value = res.items || []
  } finally {
    loading.value = false
  }
}

const toggleEnabled = async (row) => {
  try {
    if (row.enabled) {
      await disablePlugin(row.plugin_type, row.name)
      ElMessage.success('已禁用')
    } else {
      await enablePlugin(row.plugin_type, row.name)
      ElMessage.success('已启用')
    }
    await loadPlugins()
  } catch (e) { /* API 拦截器已报错 */ }
}

const onReloadPlugin = async (row) => {
  try {
    await reloadPlugin(row.plugin_type, row.name)
    ElMessage.success('已重载')
    await loadPlugins()
  } catch (e) { /* API 拦截器已报错 */ }
}

const removePlugin = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除插件 "${row.name}" 吗？该操作会删除源文件，不可恢复。`,
      '删除确认',
      { type: 'warning' }
    )
    await deletePlugin(row.plugin_type, row.name)
    ElMessage.success('已删除')
    await loadPlugins()
  } catch (e) { /* 取消 */ }
}

const reloadAll = async () => {
  reloading.value = true
  try {
    const res = await reloadAllPlugins()
    ElMessage.success(`已重载 ${res.loaded} 个插件，注册爬虫 ${res.crawler_registered} 个`)
    plugins.value = res.items || []
  } finally {
    reloading.value = false
  }
}

const openDetail = async (row) => {
  currentPlugin.value = row
  detailVisible.value = true
  detailLoading.value = true
  detailTab.value = 'info'
  try {
    const res = await getPluginDetail(row.plugin_type, row.name)
    detail.value = res
    configText.value = JSON.stringify(res.config || {}, null, 2)
  } finally {
    detailLoading.value = false
  }
}

const formatConfig = () => {
  try {
    const obj = JSON.parse(configText.value || '{}')
    configText.value = JSON.stringify(obj, null, 2)
    ElMessage.success('格式化成功')
  } catch (e) {
    ElMessage.error('JSON 格式错误')
  }
}

const saveConfig = async () => {
  let obj
  try {
    obj = JSON.parse(configText.value || '{}')
  } catch (e) {
    ElMessage.error('JSON 格式错误，无法保存')
    return
  }
  savingConfig.value = true
  try {
    await updatePluginConfig(
      currentPlugin.value.plugin_type,
      currentPlugin.value.name,
      obj
    )
    ElMessage.success('配置已保存')
    await loadPlugins()
  } finally {
    savingConfig.value = false
  }
}

const createPlugin = async () => {
  if (!createForm.name.trim()) {
    ElMessage.warning('请输入插件名称')
    return
  }
  creating.value = true
  try {
    const res = await createPluginTemplate({
      plugin_type: createForm.plugin_type,
      name: createForm.name.trim(),
      force: createForm.force,
    })
    if (res.loaded) {
      ElMessage.success(`已创建并加载：${res.file_path}`)
    } else {
      ElMessage.warning(`已创建文件，但加载失败：${res.error}`)
    }
    showCreateDialog.value = false
    createForm.name = ''
    createForm.force = false
    await loadPlugins()
  } finally {
    creating.value = false
  }
}

onMounted(loadPlugins)
</script>

<style scoped>
.plugins-page {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.header-title h2 {
  margin: 0 0 4px 0;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.plugin-name {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.plugin-name .name {
  font-weight: 500;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.error-icon {
  color: var(--el-color-danger);
  margin-left: 4px;
  cursor: help;
}
.plugin-detail {
  padding: 0 8px;
}
.schema-block, .source-block {
  background: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
}
.source-block {
  max-height: 600px;
}
.error-text {
  color: var(--el-color-danger);
}
</style>
