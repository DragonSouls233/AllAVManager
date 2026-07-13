<template>
  <div class="schema-form">
    <!-- 顶层 description -->
    <el-alert
      v-if="schema.description && !nested"
      :title="schema.description"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    />

    <el-form
      ref="formRef"
      :model="modelValue"
      :label-width="labelWidth"
      :label-position="labelPosition"
      :disabled="disabled"
      class="schema-form-inner"
    >
      <template v-for="(field, key) in fields" :key="key">
        <!-- 搜索过滤：高亮匹配字段 -->
        <el-form-item
          v-if="isFieldVisible(key, field)"
          :label="field.title || key"
          :prop="String(key)"
          :required="isRequired(key)"
          class="schema-form-item"
          :class="{ 'field-matched': isFieldMatched(key, field) }"
        >
          <!-- 字段描述（hint） -->
          <div class="field-control">
            <!-- 1. switch 开关 -->
            <el-switch
              v-if="field.widget === 'switch'"
              :model-value="!!modelValue[key]"
              @update:model-value="(v) => emitUpdate(key, v)"
            />

            <!-- 2. password 密码输入 -->
            <el-input
              v-else-if="field.widget === 'password'"
              :model-value="modelValue[key] ?? ''"
              type="password"
              show-password
              :placeholder="placeholderFor(field, key)"
              @update:model-value="(v) => emitUpdate(key, v)"
            />

            <!-- 3. textarea 多行文本 -->
            <el-input
              v-else-if="field.widget === 'textarea'"
              :model-value="modelValue[key] ?? ''"
              type="textarea"
              :rows="field.rows || 4"
              :placeholder="placeholderFor(field, key)"
              @update:model-value="(v) => emitUpdate(key, v)"
            />

            <!-- 4. input_number 数字输入 -->
            <el-input-number
              v-else-if="field.widget === 'input_number'"
              :model-value="modelValue[key] ?? field.default ?? 0"
              :min="toNumber(field.minimum)"
              :max="toNumber(field.maximum)"
              :step="field.step || 1"
              controls-position="right"
              @update:model-value="(v) => emitUpdate(key, v)"
            />

            <!-- 5. slider 滑块 -->
            <div v-else-if="field.widget === 'slider'" class="slider-row">
              <el-slider
                :model-value="toNumber(modelValue[key] ?? field.default ?? 0)"
                :min="toNumber(field.minimum)"
                :max="toNumber(field.maximum)"
                :step="field.step || 1"
                show-input
                @update:model-value="(v) => emitUpdate(key, v)"
              />
            </div>

            <!-- 6. select 下拉选择 -->
            <el-select
              v-else-if="field.widget === 'select'"
              :model-value="modelValue[key]"
              :placeholder="`选择${field.title || key}`"
              :multiple="false"
              style="width: 100%; max-width: 320px"
              @update:model-value="(v) => emitUpdate(key, v)"
            >
              <el-option
                v-for="opt in selectOptions(field, key)"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>

            <!-- 7. date_picker 日期选择 -->
            <el-date-picker
              v-else-if="field.widget === 'date_picker'"
              :model-value="modelValue[key]"
              type="date"
              value-format="YYYY-MM-DD"
              :placeholder="`选择${field.title || key}`"
              @update:model-value="(v) => emitUpdate(key, v)"
            />

            <!-- 8. color_picker 颜色选择 -->
            <div v-else-if="field.widget === 'color_picker'" class="color-row">
              <el-color-picker
                :model-value="modelValue[key] || field.default || '#409EFF'"
                @update:model-value="(v) => emitUpdate(key, v)"
              />
              <el-input
                :model-value="modelValue[key] || ''"
                size="small"
                style="width: 140px; margin-left: 8px"
                @update:model-value="(v) => emitUpdate(key, v)"
              />
            </div>

            <!-- 9. tags_input 标签输入（字符串数组）-->
            <div v-else-if="field.widget === 'tags_input'" class="tags-input">
              <el-tag
                v-for="(tag, idx) in (modelValue[key] || [])"
                :key="`${tag}-${idx}`"
                closable
                :disable-transitions="false"
                @close="removeTag(key, idx)"
                style="margin-right: 6px; margin-bottom: 4px"
              >
                {{ tag }}
              </el-tag>
              <el-input
                v-model="tagInput[key]"
                size="small"
                style="width: 180px"
                placeholder="输入后回车添加"
                @keyup.enter="addTag(key)"
                @blur="addTag(key)"
              />
            </div>

            <!-- 10. directory_picker 目录选择器 -->
            <el-input
              v-else-if="field.widget === 'directory_picker'"
              :model-value="modelValue[key] ?? ''"
              :placeholder="placeholderFor(field, key)"
                @update:model-value="(v) => emitUpdate(key, v)"
            >
              <template #append>
                <el-button @click="pickDirectory(key)">
                  <el-icon><FolderOpened /></el-icon>
                </el-button>
              </template>
            </el-input>

            <!-- 11. json_editor JSON 编辑器 -->
            <el-input
              v-else-if="field.widget === 'json_editor'"
              :model-value="jsonText[key] ?? JSON.stringify(modelValue[key] ?? field.default ?? {}, null, 2)"
              type="textarea"
              :rows="6"
              :class="{ 'json-invalid': jsonErrors[key] }"
              @update:model-value="(v) => updateJson(key, v)"
            />
            <div v-if="jsonErrors[key] && field.widget === 'json_editor'" class="json-error">
              {{ jsonErrors[key] }}
            </div>

            <!-- 12. object 嵌套对象 → 递归渲染子表单 -->
            <div v-else-if="field.widget === 'object' && field.properties" class="nested-form">
              <el-divider content-position="left">
                {{ field.title || key }}
              </el-divider>
              <SchemaForm
                :schema="field"
                :model-value="modelValue[key] || {}"
                :nested="true"
                :disabled="disabled"
                :search-keyword="searchKeyword"
                @update:model-value="(v) => emitUpdate(key, v)"
              />
            </div>

            <!-- 0. 默认 input -->
            <el-input
              v-else
              :model-value="modelValue[key] ?? ''"
              :placeholder="placeholderFor(field, key)"
              @update:model-value="(v) => emitUpdate(key, v)"
            />

            <!-- 默认值提示 -->
            <div v-if="field.default !== undefined && field.default !== null && !nested" class="field-default">
              <el-text type="info" size="small">
                默认值：{{ formatDefault(field.default) }}
              </el-text>
            </div>

            <!-- 字段描述（hint）-->
            <div v-if="field.description" class="field-hint">
              {{ field.description }}
            </div>
          </div>
        </el-form-item>
      </template>
    </el-form>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { FolderOpened } from '@element-plus/icons-vue'
import { browseDirectory } from '@/api'

// 递归组件需要显式 name
defineOptions({ name: 'SchemaForm' })

const props = defineProps({
  // schema 对象，含 properties / required 等
  schema: {
    type: Object,
    required: true
  },
  // 当前值（双向绑定）
  modelValue: {
    type: Object,
    default: () => ({})
  },
  // 是否为嵌套（递归调用）
  nested: {
    type: Boolean,
    default: false
  },
  // 是否禁用
  disabled: {
    type: Boolean,
    default: false
  },
  // 标签宽度
  labelWidth: {
    type: String,
    default: '160px'
  },
  labelPosition: {
    type: String,
    default: 'right'
  },
  // 搜索关键字（用于过滤匹配字段）
  searchKeyword: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue'])

const formRef = ref()

// tag 输入的临时值
const tagInput = ref({})
// JSON 编辑器的文本缓存
const jsonText = ref({})
// JSON 解析错误
const jsonErrors = ref({})

// schema 的 properties
const fields = computed(() => props.schema?.properties || {})

// 必填字段集合
const requiredSet = computed(() => new Set(props.schema?.required || []))

const isRequired = (key) => requiredSet.value.has(key)

// 字段是否可见（搜索过滤：无搜索时全部可见）
const isFieldVisible = (key, field) => {
  if (!props.searchKeyword) return true
  return isFieldMatched(key, field) || hasMatchedChild(field)
}

// 字段是否匹配搜索关键字
const isFieldMatched = (key, field) => {
  if (!props.searchKeyword) return false
  const kw = props.searchKeyword.toLowerCase()
  const title = (field.title || '').toLowerCase()
  const desc = (field.description || '').toLowerCase()
  return (
    String(key).toLowerCase().includes(kw) ||
    title.includes(kw) ||
    desc.includes(kw)
  )
}

// 嵌套对象是否有匹配的子字段
const hasMatchedChild = (field) => {
  if (!field.properties) return false
  for (const [k, f] of Object.entries(field.properties)) {
    if (isFieldMatched(k, f) || hasMatchedChild(f)) return true
  }
  return false
}

// placeholder 生成
const placeholderFor = (field, key) => {
  if (field.default !== undefined && field.default !== null && field.default !== '') {
    return `默认: ${field.default}`
  }
  return `输入${field.title || key}`
}

// 下拉选项
const selectOptions = (field, key) => {
  // 优先使用 schema 中的 enum
  if (Array.isArray(field.enum)) {
    return field.enum.map((v) => ({ label: String(v), value: v }))
  }
  // 语言字段补充 zh/en/ja 选项
  if (/language|lang/i.test(key)) {
    return [
      { label: '中文', value: 'zh' },
      { label: 'English', value: 'en' },
      { label: '日本語', value: 'ja' }
    ]
  }
  return []
}

// 触发更新
const emitUpdate = (key, value) => {
  const newValues = { ...props.modelValue, [key]: value }
  emit('update:modelValue', newValues)
}

// ===== tags_input 操作 =====
const addTag = (key) => {
  const val = (tagInput.value[key] || '').trim()
  if (!val) {
    tagInput.value[key] = ''
    return
  }
  const arr = Array.isArray(props.modelValue[key]) ? [...props.modelValue[key]] : []
  if (!arr.includes(val)) {
    arr.push(val)
    emitUpdate(key, arr)
  }
  tagInput.value[key] = ''
}

const removeTag = (key, idx) => {
  const arr = Array.isArray(props.modelValue[key]) ? [...props.modelValue[key]] : []
  arr.splice(idx, 1)
  emitUpdate(key, arr)
}

// ===== json_editor 操作 =====
const updateJson = (key, text) => {
  jsonText.value[key] = text
  try {
    const parsed = text.trim() ? JSON.parse(text) : null
    jsonErrors.value[key] = null
    emitUpdate(key, parsed)
  } catch (e) {
    jsonErrors.value[key] = `JSON 解析错误: ${e.message}`
  }
}

// ===== directory_picker 操作 =====
const pickDirectory = async (key) => {
  try {
    // 复用现有 /files/browse 端点打开目录选择对话框
    const res = await browseDirectory('', false)
    if (res?.path) {
      emitUpdate(key, res.path)
    }
  } catch (e) {
    ElMessage.warning('目录选择不可用，请手动输入路径')
  }
}

// ===== 工具函数 =====
const toNumber = (val) => {
  if (val === undefined || val === null) return undefined
  const n = Number(val)
  return Number.isFinite(n) ? n : undefined
}

const formatDefault = (val) => {
  if (val === null) return 'null'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

// 暴露给父组件校验使用
defineExpose({
  validate: async () => {
    if (formRef.value) {
      return await formRef.value.validate()
    }
    return true
  },
  clearValidate: () => {
    if (formRef.value) {
      formRef.value.clearValidate()
    }
  }
})
</script>

<style scoped>
.schema-form {
  width: 100%;
}

.schema-form-inner {
  width: 100%;
}

.schema-form-item {
  margin-bottom: 18px;
}

.field-control {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.field-control > :first-child {
  width: 100%;
  max-width: 600px;
}

.field-control > .el-switch,
.field-control > .el-input-number,
.field-control > .el-color-picker {
  width: auto;
  max-width: none;
}

.slider-row {
  width: 100%;
  max-width: 600px;
  padding-right: 16px;
}

.color-row {
  display: flex;
  align-items: center;
}

.tags-input {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  width: 100%;
  max-width: 600px;
  padding: 4px 0;
}

.nested-form {
  width: 100%;
  padding: 8px 12px;
  background: #fafbfc;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.nested-form :deep(.el-divider--text) {
  margin-top: 0;
}

.field-default {
  margin-top: 4px;
}

.field-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
}

.json-error {
  color: #f56c6c;
  font-size: 12px;
  margin-top: 4px;
}

:deep(.json-invalid .el-textarea__inner) {
  border-color: #f56c6c;
}

/* 搜索匹配高亮 */
.field-matched {
  background: #fff8e1;
  border-radius: 4px;
  padding: 4px 8px;
  margin-left: -8px;
  margin-right: -8px;
}
</style>
