<template>
  <div class="themes-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Brush /></el-icon>
          皮肤主题
        </h2>
        <div class="page-subtitle">
          主题插件化 · 自定义配色 / 圆角 / 字号 · 实时预览 · 导入导出
        </div>
      </div>
      <div class="page-header-actions">
        <el-button @click="handleImportClick">
          <el-icon><Upload /></el-icon> 导入主题
        </el-button>
        <el-button @click="handleExportCurrent">
          <el-icon><Download /></el-icon> 导出当前
        </el-button>
        <el-button
          v-if="themesStore.isPreviewing"
          @click="themesStore.resetTheme()"
        >
          <el-icon><RefreshLeft /></el-icon> 取消预览
        </el-button>
        <el-button
          type="primary"
          :disabled="!themesStore.isPreviewing"
          @click="confirmApply"
        >
          <el-icon><Check /></el-icon> 确认应用
        </el-button>
      </div>
    </div>

    <!-- 预览状态提示 -->
    <el-alert
      v-if="themesStore.isPreviewing"
      :title="`正在预览「${currentDisplay}」主题，点击「确认应用」保存，或「取消预览」回退`"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 0"
    />

    <el-row :gutter="16">
      <!-- 左侧：预设主题画廊 + 自定义主题列表 -->
      <el-col :span="16">
        <!-- 预设主题画廊 -->
        <el-card shadow="never" class="section-card">
          <template #header>
            <div class="card-title">
              <el-icon><Picture /></el-icon> 预设主题
              <span class="card-subtitle">点击卡片即可实时预览</span>
            </div>
          </template>
          <div class="theme-gallery">
            <div
              v-for="theme in themesStore.presetThemes"
              :key="theme.name"
              class="theme-card"
              :class="{
                active: isActive(theme.name),
                previewing: isPreviewing(theme.name),
              }"
              @click="themesStore.previewTheme(theme.name)"
              @dblclick="themesStore.setTheme(theme.name)"
            >
              <!-- 配色色板预览 -->
              <div
                class="theme-swatch"
                :style="swatchStyle(theme)"
              >
                <div class="swatch-bar primary" :style="{ background: theme.colors.primary }" />
                <div class="swatch-bar success" :style="{ background: theme.colors.success }" />
                <div class="swatch-bar warning" :style="{ background: theme.colors.warning }" />
                <div class="swatch-bar danger" :style="{ background: theme.colors.danger }" />
                <div class="swatch-bar info" :style="{ background: theme.colors.info }" />
              </div>
              <!-- 主题信息 -->
              <div class="theme-info">
                <div class="theme-name">
                  {{ theme.display_name }}
                  <el-tag
                    v-if="isActive(theme.name)"
                    size="small"
                    type="success"
                    effect="dark"
                  >
                    当前
                  </el-tag>
                  <el-tag
                    v-else-if="isPreviewing(theme.name)"
                    size="small"
                    type="warning"
                    effect="dark"
                  >
                    预览中
                  </el-tag>
                </div>
                <div class="theme-desc">{{ theme.description }}</div>
                <!-- hover 配色详情 -->
                <div class="theme-colors-detail">
                  <span
                    v-for="key in ['primary', 'success', 'warning', 'danger', 'info', 'background', 'surface', 'text', 'border', 'link']"
                    :key="key"
                    class="color-chip"
                    :title="`${key}: ${theme.colors[key]}`"
                  >
                    <span class="color-dot" :style="{ background: theme.colors[key] }" />
                    <span class="color-label">{{ key }}</span>
                  </span>
                </div>
              </div>
              <!-- 操作按钮 -->
              <div class="theme-actions" v-if="isActive(theme.name) || isPreviewing(theme.name)">
                <el-button
                  v-if="!isActive(theme.name)"
                  size="small"
                  type="primary"
                  @click.stop="themesStore.setTheme(theme.name)"
                >
                  应用
                </el-button>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 自定义主题列表 -->
        <el-card shadow="never" class="section-card">
          <template #header>
            <div class="card-title">
              <el-icon><Custom /></el-icon> 自定义主题
              <span class="card-subtitle">
                共 {{ themesStore.customThemes.length }} 个
              </span>
              <el-button
                size="small"
                type="primary"
                style="margin-left: auto"
                @click="openEditor(null)"
              >
                <el-icon><Plus /></el-icon> 新建主题
              </el-button>
            </div>
          </template>
          <el-empty
            v-if="themesStore.customThemes.length === 0"
            description="暂无自定义主题，点击「新建主题」创建"
            :image-size="80"
          />
          <div v-else class="custom-list">
            <div
              v-for="theme in themesStore.customThemes"
              :key="theme.name"
              class="custom-item"
              :class="{
                active: isActive(theme.name),
                previewing: isPreviewing(theme.name),
              }"
            >
              <div
                class="custom-swatch"
                :style="{ background: theme.colors.primary }"
                @click="themesStore.previewTheme(theme.name)"
              />
              <div class="custom-info" @click="themesStore.previewTheme(theme.name)">
                <div class="custom-name">{{ theme.display_name || theme.name }}</div>
                <div class="custom-desc">{{ theme.description || theme.name }}</div>
              </div>
              <div class="custom-actions">
                <el-button
                  size="small"
                  @click="openEditor(theme)"
                >
                  编辑
                </el-button>
                <el-button
                  size="small"
                  @click="handleExport(theme.name)"
                >
                  导出
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  @click="handleDelete(theme.name)"
                >
                  删除
                </el-button>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：当前主题详情 + 编辑器 -->
      <el-col :span="8">
        <el-card shadow="never" class="section-card sticky-card">
          <template #header>
            <div class="card-title">
              <el-icon><Setting /></el-icon>
              {{ editorMode === 'edit' ? '编辑主题' : '当前主题详情' }}
            </div>
          </template>

          <!-- 当前主题信息（非编辑模式） -->
          <div v-if="editorMode !== 'edit'" class="current-detail">
            <div class="detail-name">
              {{ currentTheme.display_name }}
              <el-tag size="small" :type="themesStore.isCustom ? 'warning' : 'info'">
                {{ themesStore.isCustom ? '自定义' : '预设' }}
              </el-tag>
            </div>
            <div class="detail-desc">{{ currentTheme.description }}</div>

            <el-divider content-position="left">配色</el-divider>
            <div class="color-grid">
              <div
                v-for="key in ['primary', 'success', 'warning', 'danger', 'info', 'background', 'surface', 'text', 'border', 'link']"
                :key="key"
                class="color-item"
              >
                <div class="color-preview" :style="{ background: currentTheme.colors[key] }" />
                <div class="color-meta">
                  <div class="color-key">{{ colorLabels[key] }}</div>
                  <div class="color-val">{{ currentTheme.colors[key] }}</div>
                </div>
              </div>
            </div>

            <el-divider content-position="left">参数</el-divider>
            <div class="param-row">
              <span>圆角</span>
              <span>{{ currentTheme.radius }}px</span>
            </div>
            <div class="param-row">
              <span>字号</span>
              <span>{{ currentTheme.font_size }}px</span>
            </div>

            <el-button
              v-if="themesStore.isCustom"
              type="primary"
              style="width: 100%; margin-top: 16px"
              @click="openEditor(currentTheme)"
            >
              <el-icon><Edit /></el-icon> 编辑此主题
            </el-button>
            <el-button
              type="primary"
              plain
              style="width: 100%; margin-top: 8px"
              @click="openEditor(JSON.parse(JSON.stringify(currentTheme)))"
            >
              <el-icon><CopyDocument /></el-icon> 另存为新主题
            </el-button>
          </div>

          <!-- 编辑器 -->
          <div v-else class="editor-form">
            <el-form :model="editorData" label-width="80px" size="small">
              <el-form-item label="主题名">
                <el-input
                  v-model="editorData.name"
                  placeholder="my-theme（英文标识符）"
                />
              </el-form-item>
              <el-form-item label="显示名">
                <el-input
                  v-model="editorData.display_name"
                  placeholder="我的主题"
                />
              </el-form-item>
              <el-form-item label="描述">
                <el-input
                  v-model="editorData.description"
                  type="textarea"
                  :rows="2"
                  placeholder="主题描述"
                />
              </el-form-item>

              <el-divider content-position="left">颜色</el-divider>
              <div
                v-for="key in ['primary', 'success', 'warning', 'danger', 'info', 'background', 'surface', 'text', 'border', 'link']"
                :key="key"
                class="color-edit-row"
              >
                <span class="color-edit-label">{{ colorLabels[key] }}</span>
                <el-color-picker v-model="editorData.colors[key]" />
                <el-input
                  v-model="editorData.colors[key]"
                  size="small"
                  style="width: 120px"
                />
              </div>

              <el-divider content-position="left">参数</el-divider>
              <el-form-item :label="`圆角: ${editorData.radius}px`">
                <el-slider
                  v-model="editorData.radius"
                  :min="0"
                  :max="24"
                  :step="1"
                />
              </el-form-item>
              <el-form-item :label="`字号: ${editorData.font_size}px`">
                <el-slider
                  v-model="editorData.font_size"
                  :min="12"
                  :max="18"
                  :step="1"
                />
              </el-form-item>

              <div class="editor-actions">
                <el-button @click="previewEditor">实时预览</el-button>
                <el-button @click="editorMode = 'view'">取消</el-button>
                <el-button type="primary" @click="saveEditor">保存</el-button>
              </div>
            </el-form>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 隐藏的文件输入（用于导入） -->
    <input
      ref="fileInput"
      type="file"
      accept=".json,application/json"
      style="display: none"
      @change="handleFileSelected"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useThemesStore } from '../stores/themes'

const themesStore = useThemesStore()

// 编辑器状态
const editorMode = ref('view') // 'view' | 'edit'
const editorData = ref({
  name: '',
  display_name: '',
  description: '',
  colors: {
    primary: '#409eff',
    success: '#67c23a',
    warning: '#e6a23c',
    danger: '#f56c6c',
    info: '#909399',
    background: '#f0f2f5',
    surface: '#ffffff',
    text: '#303133',
    border: '#ebeef5',
    link: '#409eff',
  },
  radius: 8,
  font_size: 14,
})

const fileInput = ref(null)

// 颜色字段中文标签
const colorLabels = {
  primary: '主色',
  success: '成功',
  warning: '警告',
  danger: '危险',
  info: '信息',
  background: '背景',
  surface: '表面',
  text: '文字',
  border: '边框',
  link: '链接',
}

// 当前主题
const currentTheme = computed(() => themesStore.currentTheme)
const currentDisplay = computed(
  () => currentTheme.value.display_name || currentTheme.value.name
)

// ============== 工具方法 ==============

function isActive(name) {
  return (
    themesStore.activeThemeName === name && !themesStore.isPreviewing
  )
}

function isPreviewing(name) {
  return (
    themesStore.previewingName === name && themesStore.isPreviewing
  )
}

/**
 * 主题色板样式（用于卡片预览背景）
 */
function swatchStyle(theme) {
  return {
    background: theme.colors.background,
    borderTopColor: theme.colors.primary,
  }
}

// ============== 编辑器 ==============

/**
 * 打开编辑器
 * @param {Object|null} theme 编辑时传入主题，新建时传 null
 */
function openEditor(theme) {
  if (theme) {
    // 编辑/复制：深拷贝避免直接修改
    editorData.value = JSON.parse(JSON.stringify(theme))
  } else {
    // 新建：使用默认主题作为模板
    editorData.value = {
      name: `custom-${Date.now().toString(36)}`,
      display_name: '新主题',
      description: '用户自定义主题',
      colors: {
        primary: '#409eff',
        success: '#67c23a',
        warning: '#e6a23c',
        danger: '#f56c6c',
        info: '#909399',
        background: '#f0f2f5',
        surface: '#ffffff',
        text: '#303133',
        border: '#ebeef5',
        link: '#409eff',
      },
      radius: 8,
      font_size: 14,
    }
  }
  editorMode.value = 'edit'
}

/**
 * 实时预览编辑器中的主题（临时应用）
 */
function previewEditor() {
  // 临时构造主题对象并应用
  themesStore.previewingName = editorData.value.name
  themesStore.applyThemeToDOM(editorData.value)
}

/**
 * 保存编辑器主题
 */
function saveEditor() {
  const data = JSON.parse(JSON.stringify(editorData.value))
  if (!data.name) {
    ElMessage.error('请填写主题名')
    return
  }
  if (!data.display_name) {
    data.display_name = data.name
  }
  themesStore.createCustomTheme(data)
  editorMode.value = 'view'
}

// ============== 确认应用 ==============

function confirmApply() {
  if (themesStore.previewingName) {
    themesStore.setTheme(themesStore.previewingName)
    ElMessage.success('主题已应用并保存')
  }
}

// ============== 导入 / 导出 ==============

function handleImportClick() {
  fileInput.value?.click()
}

function handleFileSelected(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => {
    try {
      const data = JSON.parse(ev.target.result)
      themesStore.importTheme(data)
    } catch (err) {
      ElMessage.error('JSON 解析失败：' + err.message)
    }
  }
  reader.readAsText(file)
  // 清空 input，便于重复选择同一文件
  e.target.value = ''
}

function handleExport(name) {
  const theme = themesStore.exportTheme(name)
  if (!theme) {
    ElMessage.error('导出失败：主题不存在')
    return
  }
  downloadThemeJson(theme)
}

function handleExportCurrent() {
  const theme = themesStore.exportTheme()
  if (!theme) return
  downloadThemeJson(theme)
}

function downloadThemeJson(theme) {
  const blob = new Blob([JSON.stringify(theme, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `theme-${theme.name}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success(`主题「${theme.display_name || theme.name}」已导出`)
}

// ============== 删除 ==============

async function handleDelete(name) {
  try {
    await ElMessageBox.confirm(
      `确定删除自定义主题「${name}」吗？此操作不可恢复。`,
      '删除确认',
      { type: 'warning' }
    )
    themesStore.deleteCustomTheme(name)
  } catch (e) {
    // 用户取消
  }
}

// ============== 初始化 ==============

onMounted(() => {
  themesStore.loadThemes()
})
</script>

<style scoped>
.themes-page {
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}

.section-card {
  border-radius: var(--radius-md) !important;
  border: none !important;
  box-shadow: var(--shadow-sm) !important;
  margin-bottom: var(--gap-lg);
}

.sticky-card {
  position: sticky;
  top: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
}

.card-subtitle {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
}

/* ===== 主题画廊 ===== */
.theme-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--gap-md);
}

.theme-card {
  border: 2px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  transition: all 0.25s ease;
  background: var(--bg-card);
  position: relative;
}

.theme-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-hover);
  border-color: var(--primary-light);
}

.theme-card.active {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px var(--brand-gradient-soft);
}

.theme-card.previewing {
  border-color: var(--warning-color);
  box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.2);
}

.theme-swatch {
  height: 80px;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--border-light);
  position: relative;
  overflow: hidden;
}

.swatch-bar {
  flex: 1;
  width: 100%;
}

.theme-info {
  padding: 12px 14px;
}

.theme-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.theme-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
  margin-bottom: 8px;
}

.theme-colors-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  opacity: 0;
  max-height: 0;
  overflow: hidden;
  transition: all 0.25s ease;
}

.theme-card:hover .theme-colors-detail {
  opacity: 1;
  max-height: 80px;
}

.color-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-secondary);
}

.color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
}

.theme-actions {
  padding: 0 14px 12px;
  display: flex;
  justify-content: flex-end;
}

/* ===== 自定义主题列表 ===== */
.custom-list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.custom-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  transition: all 0.2s ease;
}

.custom-item:hover {
  border-color: var(--primary-light);
  background: var(--brand-gradient-soft);
}

.custom-item.active {
  border-color: var(--primary-color);
  background: var(--brand-gradient-soft);
}

.custom-item.previewing {
  border-color: var(--warning-color);
  background: rgba(230, 162, 60, 0.08);
}

.custom-swatch {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  flex-shrink: 0;
  border: 2px solid var(--bg-card);
  box-shadow: 0 0 0 1px var(--border-color);
}

.custom-info {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.custom-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.custom-desc {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.custom-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

/* ===== 当前主题详情 ===== */
.current-detail {
  padding: 4px 0;
}

.detail-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.detail-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.color-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.color-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.color-preview {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-color);
  flex-shrink: 0;
}

.color-meta {
  min-width: 0;
}

.color-key {
  font-size: 12px;
  color: var(--text-secondary);
}

.color-val {
  font-size: 11px;
  color: var(--text-regular);
  font-family: 'Consolas', 'Monaco', monospace;
}

.param-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
  color: var(--text-regular);
  border-bottom: 1px dashed var(--border-light);
}

/* ===== 编辑器 ===== */
.editor-form {
  padding: 4px 0;
}

.color-edit-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.color-edit-label {
  width: 50px;
  font-size: 13px;
  color: var(--text-regular);
  flex-shrink: 0;
}

.editor-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
