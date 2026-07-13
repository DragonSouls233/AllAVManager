<template>
  <div class="naming-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><EditPen /></el-icon>
          命名模板
        </h2>
        <div class="page-subtitle">Jinja2 沙箱模板引擎 · 自定义文件名/目录名/海报名</div>
      </div>
      <div class="page-header-actions">
        <el-button @click="loadAll" :loading="loading">
          <el-icon><Refresh /></el-icon> 重载
        </el-button>
        <el-button type="primary" @click="saveAll" :loading="saving">
          <el-icon><Check /></el-icon> 保存配置
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左侧：模板编辑 -->
      <el-col :span="16">
        <el-card shadow="never" class="template-card">
          <template #header>
            <div class="card-title">
              <el-icon><EditPen /></el-icon> 模板配置
              <el-switch
                v-model="config.enabled"
                active-text="启用"
                inactive-text="禁用"
                style="margin-left: auto"
              />
            </div>
          </template>

          <el-form :model="config" label-width="140px">
            <el-form-item label="文件名模板">
              <el-input v-model="config.file_template" placeholder="[{{ code }}] {{ title }}" />
              <div class="tpl-actions">
                <el-button size="small" @click="preview('file_template')">预览</el-button>
                <el-button size="small" @click="validate('file_template')">验证语法</el-button>
                <el-button size="small" link @click="useDefault('file_template', '[{{ code }}] {{ title }}')">恢复默认</el-button>
              </div>
            </el-form-item>

            <el-form-item label="目录名模板">
              <el-input
                v-model="config.dir_template"
                placeholder="{{ studio }}/{{ release_year }}/{{ code }}"
                type="textarea"
                :rows="2"
              />
              <div class="tpl-actions">
                <el-button size="small" @click="preview('dir_template')">预览</el-button>
                <el-button size="small" @click="validate('dir_template')">验证语法</el-button>
                <el-button size="small" link @click="useDefault('dir_template', '{{ studio }}/{{ release_year }}/{{ code }}')">恢复默认</el-button>
              </div>
            </el-form-item>

            <el-form-item label="海报文件名模板">
              <el-input v-model="config.poster_template" placeholder="{{ code }}-poster" />
              <div class="tpl-actions">
                <el-button size="small" @click="preview('poster_template')">预览</el-button>
                <el-button size="small" @click="validate('poster_template')">验证语法</el-button>
                <el-button size="small" link @click="useDefault('poster_template', '{{ code }}-poster')">恢复默认</el-button>
              </div>
            </el-form-item>

            <el-form-item label="缩略图名模板">
              <el-input v-model="config.thumb_template" placeholder="{{ code }}-thumb" />
              <div class="tpl-actions">
                <el-button size="small" @click="preview('thumb_template')">预览</el-button>
                <el-button size="small" @click="validate('thumb_template')">验证语法</el-button>
                <el-button size="small" link @click="useDefault('thumb_template', '{{ code }}-thumb')">恢复默认</el-button>
              </div>
            </el-form-item>

            <el-divider>高级选项</el-divider>

            <el-form-item label="非法字符处理">
              <el-radio-group v-model="config.replace_invalid_to_underscore">
                <el-radio :value="true">替换为下划线</el-radio>
                <el-radio :value="false">直接删除</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="文件名最大长度">
              <el-input-number v-model="config.max_length" :min="20" :max="255" />
              <span class="form-tip">建议 ≤ 120，避免 Windows 路径过长</span>
            </el-form-item>
          </el-form>

          <!-- 预览结果 -->
          <el-card v-if="previewResult" shadow="never" class="preview-result">
            <template #header>
              <div class="card-title">
                <el-icon><View /></el-icon> 预览结果
                <el-tag :type="previewResult.ok ? 'success' : 'danger'" size="small">
                  {{ previewResult.ok ? '成功' : '失败' }}
                </el-tag>
              </div>
            </template>
            <div v-if="previewResult.ok" class="preview-output">{{ previewResult.result }}</div>
            <div v-else class="preview-error">{{ previewResult.error }}</div>
          </el-card>

          <!-- 默认模板示例 -->
          <el-card shadow="never" class="defaults-card">
            <template #header>
              <div class="card-title"><el-icon><Files /></el-icon> 默认模板示例（点击使用）</div>
            </template>
            <div class="defaults-list">
              <div
                v-for="(tpl, key) in defaults"
                :key="key"
                class="default-item"
                @click="applyDefault(tpl)"
              >
                <code class="default-tpl">{{ tpl }}</code>
                <span class="default-key">{{ key }}</span>
              </div>
            </div>
          </el-card>
        </el-card>
      </el-col>

      <!-- 右侧：变量文档 -->
      <el-col :span="8">
        <el-card shadow="never" class="vars-card">
          <template #header>
            <div class="card-title"><el-icon><Document /></el-icon> 可用变量</div>
          </template>
          <el-table :data="variables" size="small" stripe>
            <el-table-column prop="name" label="变量名" width="120">
              <template #default="{ row }">
                <code class="var-name">{{ '{{ ' + row.name + ' }' + '}' }}</code>
              </template>
            </el-table-column>
            <el-table-column prop="type" label="类型" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="typeTag(row.type)">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="desc" label="说明" />
          </el-table>
        </el-card>

        <el-card shadow="never" class="filters-card">
          <template #header>
            <div class="card-title"><el-icon><MagicStick /></el-icon> 可用过滤器</div>
          </template>
          <div class="filters-list">
            <div v-for="f in filters" :key="f.name" class="filter-item">
              <code class="filter-name">| {{ f.name }}</code>
              <span class="filter-desc">{{ f.desc }}</span>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="tip-card">
          <template #header>
            <div class="card-title"><el-icon><InfoFilled /></el-icon> 使用提示</div>
          </template>
          <ul class="tip-list">
            <li>使用 <code>{% if is_uncensored %}[无码]{% endif %}</code> 添加条件标记</li>
            <li>使用 <code>{{ actors[0] }}</code> 取列表首项（演员）</li>
            <li>使用 <code>{{ title|truncate_str(40) }}</code> 截断长标题</li>
            <li>目录模板用 <code>/</code> 作为层级分隔符</li>
            <li>StrictUndefined 模式下，缺失变量会报错；建议用 <code>{% if x %}...{% endif %}</code> 包裹可选字段</li>
            <li>所有模板在沙箱中执行，无法访问文件系统或执行任意代码</li>
          </ul>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  EditPen, Refresh, Check, View, Files, Document, MagicStick, InfoFilled,
} from '@element-plus/icons-vue'
import {
  getNamingConfig, updateNamingConfig,
  previewNamingTemplate, validateNamingTemplate,
  getDefaultTemplates, getTemplateVariables,
} from '@/api'

const loading = ref(false)
const saving = ref(false)

const config = reactive({
  enabled: false,
  file_template: '[{{ code }}] {{ title }}',
  dir_template: '{{ studio }}/{{ release_year }}/{{ code }}',
  poster_template: '{{ code }}-poster',
  thumb_template: '{{ code }}-thumb',
  replace_invalid_to_underscore: true,
  max_length: 120,
})

const defaults = ref({})
const variables = ref([])
const filters = ref([])
const previewResult = ref(null)

const loadAll = async () => {
  loading.value = true
  try {
    const [cfg, defs, vars] = await Promise.all([
      getNamingConfig(),
      getDefaultTemplates(),
      getTemplateVariables(),
    ])
    Object.assign(config, cfg)
    defaults.value = defs.templates || {}
    variables.value = vars.variables || []
    filters.value = vars.filters || []
    ElMessage.success('数据已加载')
  } catch (e) {
    // ignore
  } finally {
    loading.value = false
  }
}

const saveAll = async () => {
  saving.value = true
  try {
    await updateNamingConfig({
      enabled: config.enabled,
      file_template: config.file_template,
      dir_template: config.dir_template,
      poster_template: config.poster_template,
      thumb_template: config.thumb_template,
      replace_invalid_to_underscore: config.replace_invalid_to_underscore,
      max_length: config.max_length,
    })
    ElMessage.success('配置已保存')
  } catch (e) {
    // ignore
  } finally {
    saving.value = false
  }
}

const preview = async (field) => {
  const tpl = config[field]
  if (!tpl) {
    ElMessage.warning('模板不能为空')
    return
  }
  try {
    const r = await previewNamingTemplate({ template: tpl })
    previewResult.value = r
  } catch (e) {
    // ignore
  }
}

const validate = async (field) => {
  const tpl = config[field]
  if (!tpl) {
    ElMessage.warning('模板不能为空')
    return
  }
  try {
    const r = await validateNamingTemplate({ template: tpl })
    if (r.ok) {
      ElMessage.success('语法正确')
    } else {
      ElMessage.error(`语法错误: ${r.error}`)
    }
  } catch (e) {
    // ignore
  }
}

const useDefault = (field, defaultValue) => {
  config[field] = defaultValue
  ElMessage.info('已恢复默认模板，请记得保存')
}

const applyDefault = (tpl) => {
  // 让用户选择目标字段
  // 简化：直接放到文件名模板
  config.file_template = tpl
  ElMessage.info('已应用到"文件名模板"字段，可拖动到其他字段')
}

const typeTag = (t) => {
  const m = { string: 'success', list: 'warning', float: 'danger', bool: 'info', int: 'info' }
  return m[t] || 'info'
}

onMounted(loadAll)
</script>

<style scoped>
.naming-page {
  padding: 4px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.page-title {
  margin: 0 0 4px 0;
  font-size: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-subtitle {
  font-size: 12px;
  color: #909399;
}

.page-header-actions {
  display: flex;
  gap: 8px;
}

.template-card,
.vars-card,
.filters-card,
.tip-card,
.preview-result,
.defaults-card {
  margin-bottom: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.tpl-actions {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  align-items: center;
}

.form-tip {
  font-size: 11px;
  color: #909399;
  margin-left: 8px;
}

.preview-output {
  font-family: 'Consolas', monospace;
  background: #f4f4f5;
  padding: 12px;
  border-radius: 4px;
  font-size: 13px;
  word-break: break-all;
  white-space: pre-wrap;
}

.preview-error {
  color: #f56c6c;
  font-family: 'Consolas', monospace;
  font-size: 12px;
}

.defaults-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px;
}

.default-item {
  padding: 8px 12px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.default-item:hover {
  border-color: #409eff;
  background: #ecf5ff;
}

.default-tpl {
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: #409eff;
  word-break: break-all;
}

.default-key {
  font-size: 11px;
  color: #909399;
}

.var-name {
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: #409eff;
}

.filters-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.filter-item {
  display: flex;
  flex-direction: column;
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
}

.filter-item:last-child {
  border-bottom: none;
}

.filter-name {
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: #e6a23c;
  font-weight: 600;
}

.filter-desc {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}

.tip-list {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 12px;
  color: #606266;
}

.tip-list li {
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
  line-height: 1.5;
}

.tip-list li:last-child {
  border-bottom: none;
}

.tip-list code {
  font-family: 'Consolas', monospace;
  background: #f4f4f5;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 11px;
  color: #c7254e;
}

:deep(.dark) .preview-output {
  background: #3a3a3a;
  color: #d0d0d0;
}

:deep(.dark) .default-item {
  border-color: #3a3a3a;
}

:deep(.dark) .default-item:hover {
  background: #2c3e50;
  border-color: #409eff;
}

:deep(.dark) .tip-list code {
  background: #3a3a3a;
  color: #ff8a80;
}

:deep(.dark) .filter-item,
:deep(.dark) .tip-list li {
  border-bottom-color: #3a3a3a;
}
</style>
