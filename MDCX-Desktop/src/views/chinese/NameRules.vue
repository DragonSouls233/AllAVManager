<template>
  <div class="chinese-name-rules">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>📛 国产命名规范管理</span>
          <div class="header-actions">
            <el-button type="primary" @click="saveRules" :loading="saving">
              <el-icon><Check /></el-icon> 保存规则
            </el-button>
          </div>
        </div>
      </template>

      <el-alert title="国产视频文件名常含广告/平台标记，此处可管理和自动去除。保存后每次去广告操作会优先使用内置规则，新发现的广告词会自动记录。" type="info" show-icon :closable="false" style="margin-bottom:16px" />

      <el-form label-width="120px">
        <el-form-item label="内置广告词">
          <el-switch v-model="builtinEnabled" active-text="启用内置规则" />
        </el-form-item>
        <el-form-item label="自动记录">
          <el-switch v-model="autoRecord" active-text="自动记录新广告词" />
        </el-form-item>
      </el-form>

      <el-tabs v-model="activeTab">
        <el-tab-pane label="内置规则（不可编辑）" name="builtin">
          <el-table :data="builtinRules" size="small" max-height="400" stripe>
            <el-table-column type="index" width="50" />
            <el-table-column prop="pattern" label="广告词" />
            <el-table-column label="状态" width="100">
              <template #default>
                <el-tag size="small" type="success">系统内置</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="用户规则" name="user">
          <div style="margin-bottom:12px">
            <el-input v-model="newRule" placeholder="输入广告词，如 PsychoPorn.com" style="width:300px">
              <template #append>
                <el-button @click="addRule" :disabled="!newRule.trim()">
                  <el-icon><Plus /></el-icon> 添加
                </el-button>
              </template>
            </el-input>
          </div>
          <el-table :data="userRules" size="small" max-height="400" stripe>
            <el-table-column type="index" width="50" />
            <el-table-column prop="pattern" label="广告词" />
            <el-table-column label="操作" width="100">
              <template #default="{ row, index }">
                <el-button type="danger" size="small" text @click="removeRule(index)">
                  <el-icon><Delete /></el-icon> 删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!userRules.length" style="text-align:center;padding:20px;color:#999">
            暂无用户自定义规则。每次去广告时新发现的广告词会自动添加到这里。
          </div>
        </el-tab-pane>

        <el-tab-pane label="自动记录日志" name="history">
          <el-table :data="autoRecorded" size="small" max-height="400" stripe>
            <el-table-column prop="pattern" label="广告词" />
            <el-table-column prop="first_seen" label="首次发现" width="160" />
            <el-table-column prop="file" label="来源文件" min-width="300">
              <template #default="{ row }">
                <span style="font-size:12px;color:#999">{{ row.file }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!autoRecorded.length" style="text-align:center;padding:20px;color:#999">
            暂无自动记录。
          </div>
        </el-tab-pane>
      </el-tabs>

      <el-divider />

      <el-form label-width="120px">
        <el-form-item label="命名模板">
          <el-input v-model="namingTemplate" placeholder="{code}.{actor}.{title}" style="width:400px" />
          <div style="margin-left:12px;font-size:12px;color:#999">
            支持变量：{code} 番号, {actor} 演员, {title} 标题, {studio} 工作室
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 一键去广告 -->
    <el-card shadow="never" style="margin-top:16px">
      <template #header>
        <span>🔄 一键去广告重命名</span>
      </template>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-input v-model="testFilename" placeholder="输入文件名测试去广告效果" style="width:100%">
            <template #append>
              <el-button @click="testClean">测试</el-button>
            </template>
          </el-input>
        </el-col>
        <el-col :span="12">
          <div v-if="cleanResult" class="clean-result">
            <div>原始：<span class="old-text">{{ testFilename }}</span></div>
            <div>清除：<span class="new-text">{{ cleanResult }}</span></div>
          </div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getChineseNameRules, updateChineseNameRules } from '@/api/chinese'

const saving = ref(false)
const activeTab = ref('builtin')
const builtinEnabled = ref(true)
const autoRecord = ref(true)
const namingTemplate = ref('{code}.{actor}.{title}')
const newRule = ref('')
const builtinRules = ref([])
const userRules = ref([])
const autoRecorded = ref([])

const testFilename = ref('TM0165.王小妮.妈妈的性奴之路.天美传媒.9Porn.asia')
const cleanResult = ref('')

async function loadRules() {
  try {
    const data = await getChineseNameRules()
    builtinRules.value = data.builtin?.map(p => ({ pattern: p })) || []
    userRules.value = data.user_defined?.map(p => ({ pattern: p })) || []
    autoRecorded.value = data.auto_recorded || []
    builtinEnabled.value = data.builtin_enabled !== false
    autoRecord.value = data.auto_record !== false
    namingTemplate.value = data.naming_template || '{code}.{actor}.{title}'
  } catch (e) {
    // 默认内置规则
    builtinRules.value = [
      '!DVDEmpire', '!CHDVDEmpire', '!9Porn', '9Porn.asia',
      'CHT!BT', '!BT', '!DD', '!HD', '!SD',
      'PsychoPorn.com', 'PsychoPorn', 'PornHub.com',
      'xvideos.com', 'xhamster.com', '91Porn', 'Pornhub.com'
    ].map(p => ({ pattern: p }))
  }
}

function addRule() {
  const r = newRule.value.trim()
  if (!r) return
  if (userRules.value.some(u => u.pattern === r)) {
    ElMessage.warning('该规则已存在')
    return
  }
  userRules.value.push({ pattern: r })
  newRule.value = ''
}

function removeRule(index) {
  userRules.value.splice(index, 1)
}

async function saveRules() {
  saving.value = true
  try {
    await updateChineseNameRules({
      builtin_enabled: builtinEnabled.value,
      auto_record: autoRecord.value,
      user_defined: userRules.value.map(r => r.pattern),
      naming_template: namingTemplate.value
    })
    ElMessage.success('规则已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

function testClean() {
  let title = testFilename.value
  const rules = [...builtinRules.value.map(r => r.pattern), ...userRules.value.map(r => r.pattern)]
  for (const rule of rules) {
    title = title.replace(rule, '')
  }
  title = title.replace(/[-_.\s]{2,}/g, '.').replace(/\.+$/, '').replace(/^\.+/, '')
  cleanResult.value = title
}

onMounted(loadRules)
</script>

<style scoped>
.chinese-name-rules {
  max-width: 1000px;
  margin: 0 auto;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.clean-result {
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
  line-height: 1.8;
}
.old-text { color: #f56c6c; }
.new-text { color: #67c23a; font-weight: bold; }
</style>
