<template>
  <div class="webhooks-page">
    <div class="page-header">
      <div class="header-title">
        <h2>Webhook 通知</h2>
        <p class="muted">多渠道通知：Telegram / Discord / Bark / 企业微信 / 自定义</p>
      </div>
      <div class="header-actions">
        <el-button @click="loadData" :icon="Refresh">刷新</el-button>
        <el-button type="success" @click="openCreate">
          <el-icon><Plus /></el-icon> 新建 Webhook
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="16">
        <el-table :data="webhooks" v-loading="loading" border stripe>
          <el-table-column label="名称" min-width="140" prop="name" />
          <el-table-column label="渠道" width="110">
            <template #default="{ row }">
              <el-tag :type="channelTagType(row.channel)" size="small">
                {{ channelLabel(row.channel) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="订阅事件" min-width="200">
            <template #default="{ row }">
              <el-tag
                v-for="ev in row.events" :key="ev"
                size="small" type="info"
                style="margin-right: 4px"
              >{{ ev }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                {{ row.enabled ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="testSingle(row)" :loading="row._testing">
                <el-icon><Promotion /></el-icon> 测试
              </el-button>
              <el-button size="small" @click="openEdit(row)">
                <el-icon><Edit /></el-icon> 编辑
              </el-button>
              <el-button size="small" type="danger" @click="removeItem(row)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-divider />

        <div class="section-title">
          <span>广播测试</span>
          <small class="muted">同时发送到所有订阅了该事件的 Webhook</small>
        </div>
        <el-form inline>
          <el-form-item label="事件">
            <el-select v-model="broadcastForm.event" style="width: 200px">
              <el-option
                v-for="ev in supportedEvents" :key="ev"
                :label="ev" :value="ev"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="级别">
            <el-select v-model="broadcastForm.level" style="width: 110px">
              <el-option label="信息" value="info" />
              <el-option label="成功" value="success" />
              <el-option label="警告" value="warning" />
              <el-option label="错误" value="error" />
            </el-select>
          </el-form-item>
          <el-form-item label="标题">
            <el-input v-model="broadcastForm.title" style="width: 200px" />
          </el-form-item>
          <el-form-item label="内容">
            <el-input v-model="broadcastForm.message" style="width: 320px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="doBroadcast" :loading="broadcasting">
              广播
            </el-button>
          </el-form-item>
        </el-form>
      </el-col>

      <el-col :span="8">
        <div class="section-title">
          <span>发送历史</span>
          <el-button
            text size="small" type="danger"
            @click="clearHistory"
            style="float: right"
          >清空</el-button>
        </div>
        <el-timeline v-loading="historyLoading">
          <el-timeline-item
            v-for="rec in history" :key="rec.id"
            :type="rec.success ? 'success' : 'danger'"
            :timestamp="formatTime(rec.timestamp)"
            placement="top"
          >
            <div class="history-item">
              <div class="history-head">
                <el-tag size="small" :type="rec.success ? 'success' : 'danger'">
                  {{ rec.success ? '成功' : '失败' }}
                </el-tag>
                <span class="webhook-name">{{ rec.webhook_name }}</span>
                <el-tag size="small" type="info">{{ rec.channel }}</el-tag>
              </div>
              <div class="history-title">{{ rec.title }}</div>
              <div class="history-event muted">事件: {{ rec.event }}</div>
              <div v-if="rec.error" class="history-error">{{ rec.error }}</div>
            </div>
          </el-timeline-item>
          <el-empty v-if="!history.length" description="暂无发送记录" :image-size="50" />
        </el-timeline>
      </el-col>
    </el-row>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="editDialog"
      :title="editForm.id ? '编辑 Webhook' : '新建 Webhook'"
      width="640px"
    >
      <el-form :model="editForm" label-width="120px">
        <el-form-item label="名称" required>
          <el-input v-model="editForm.name" placeholder="如 我的 Telegram" />
        </el-form-item>
        <el-form-item label="渠道" required>
          <el-select v-model="editForm.channel" style="width: 100%">
            <el-option
              v-for="c in supportedChannels" :key="c"
              :label="channelLabel(c)" :value="c"
            />
          </el-select>
        </el-form-item>

        <!-- Telegram 配置 -->
        <template v-if="editForm.channel === 'telegram'">
          <el-form-item label="Bot Token" required>
            <el-input v-model="editForm.token" placeholder="123456:ABC-..." />
          </el-form-item>
          <el-form-item label="Chat ID" required>
            <el-input v-model="editForm.chat_id" placeholder="-1001234567890 或 私聊 ID" />
          </el-form-item>
        </template>

        <!-- Bark 配置 -->
        <template v-if="editForm.channel === 'bark'">
          <el-form-item label="设备 Key" required>
            <el-input v-model="editForm.token" placeholder="Bark App 中复制" />
          </el-form-item>
          <el-form-item label="Bark 服务器">
            <el-input
              v-model="editForm.bark_server"
              placeholder="默认 https://api.day.app，自建可填入"
            />
          </el-form-item>
        </template>

        <!-- Discord / WeChat / Custom -->
        <template v-if="['discord', 'wechat', 'custom'].includes(editForm.channel)">
          <el-form-item label="Webhook URL" required>
            <el-input v-model="editForm.url" placeholder="https://..." />
          </el-form-item>
        </template>

        <el-form-item label="订阅事件">
          <el-checkbox-group v-model="editForm.events">
            <el-checkbox
              v-for="ev in supportedEvents" :key="ev"
              :label="ev" :value="ev"
            >{{ ev }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="editForm.timeout" :min="5" :max="120" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editForm.enabled" />
        </el-form-item>
        <el-form-item label="额外参数">
          <el-input
            v-model="extraText"
            type="textarea"
            :rows="4"
            placeholder='JSON 格式，如 Bark: {"icon":"https://...","sound":"bell"}；Custom: {"X-Signature":"xxx"}'
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="saveWebhook" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh, Plus, Edit, Delete, Promotion
} from '@element-plus/icons-vue'
import {
  listWebhooks, createWebhook, updateWebhook, deleteWebhook,
  testWebhook, broadcastWebhook,
  getWebhookHistory, clearWebhookHistory
} from '@/api'

const webhooks = ref([])
const loading = ref(false)
const supportedChannels = ref([])
const supportedEvents = ref([])

const history = ref([])
const historyLoading = ref(false)

// 广播
const broadcastForm = reactive({
  event: 'custom',
  level: 'info',
  title: 'MDCX 测试广播',
  message: '这是一条广播消息',
})
const broadcasting = ref(false)

// 创建/编辑
const editDialog = ref(false)
const editForm = reactive({
  id: '',
  name: '',
  channel: 'telegram',
  url: '',
  token: '',
  chat_id: '',
  bark_server: 'https://api.day.app',
  enabled: true,
  events: ['custom'],
  timeout: 30,
  extra: {},
})
const extraText = ref('{}')
const saving = ref(false)

const channelLabel = (c) => ({
  telegram: 'Telegram',
  discord: 'Discord',
  bark: 'Bark',
  wechat: '企业微信',
  custom: '自定义',
}[c] || c)

const channelTagType = (c) => ({
  telegram: 'primary',
  discord: 'success',
  bark: 'warning',
  wechat: 'info',
  custom: '',
}[c] || '')

const formatTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`
}

const loadData = async () => {
  loading.value = true
  try {
    const res = await listWebhooks()
    webhooks.value = (res.items || []).map(w => ({ ...w, _testing: false }))
    supportedChannels.value = res.supported_channels || []
    supportedEvents.value = res.supported_events || []
  } finally {
    loading.value = false
  }
  await loadHistory()
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const res = await getWebhookHistory({ limit: 50 })
    history.value = res.items || []
  } finally {
    historyLoading.value = false
  }
}

const openCreate = () => {
  Object.assign(editForm, {
    id: '', name: '', channel: 'telegram',
    url: '', token: '', chat_id: '',
    bark_server: 'https://api.day.app',
    enabled: true, events: ['custom'],
    timeout: 30, extra: {},
  })
  extraText.value = '{}'
  editDialog.value = true
}

const openEdit = (row) => {
  Object.assign(editForm, {
    id: row.id,
    name: row.name,
    channel: row.channel,
    url: row.url || '',
    token: row.token || '',
    chat_id: row.chat_id || '',
    bark_server: row.bark_server || 'https://api.day.app',
    enabled: row.enabled,
    events: [...(row.events || [])],
    timeout: row.timeout || 30,
    extra: row.extra || {},
  })
  extraText.value = JSON.stringify(row.extra || {}, null, 2)
  editDialog.value = true
}

const saveWebhook = async () => {
  if (!editForm.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  let extraObj = {}
  try {
    extraObj = JSON.parse(extraText.value || '{}')
  } catch (e) {
    ElMessage.error('额外参数 JSON 格式错误')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: editForm.name,
      channel: editForm.channel,
      url: editForm.url,
      token: editForm.token,
      chat_id: editForm.chat_id,
      bark_server: editForm.bark_server,
      enabled: editForm.enabled,
      events: editForm.events,
      timeout: editForm.timeout,
      extra: extraObj,
    }
    if (editForm.id) {
      await updateWebhook(editForm.id, payload)
      ElMessage.success('已更新')
    } else {
      await createWebhook(payload)
      ElMessage.success('已创建')
    }
    editDialog.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

const removeItem = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除 Webhook "${row.name}"？`, '删除确认', { type: 'warning' })
    await deleteWebhook(row.id)
    ElMessage.success('已删除')
    await loadData()
  } catch (e) { /* 取消 */ }
}

const testSingle = async (row) => {
  row._testing = true
  try {
    const res = await testWebhook(row.id)
    if (res.success) {
      ElMessage.success('发送成功')
    } else {
      ElMessage.error(`发送失败：${res.message}`)
    }
    await loadHistory()
  } finally {
    row._testing = false
  }
}

const doBroadcast = async () => {
  broadcasting.value = true
  try {
    const res = await broadcastWebhook({
      event: broadcastForm.event,
      title: broadcastForm.title,
      message: broadcastForm.message,
      level: broadcastForm.level,
    })
    ElMessage.success(`已成功发送到 ${res.sent} 个 Webhook`)
    await loadHistory()
  } finally {
    broadcasting.value = false
  }
}

const clearHistory = async () => {
  try {
    await ElMessageBox.confirm('确定清空发送历史？', '清空确认', { type: 'warning' })
    await clearWebhookHistory()
    ElMessage.success('已清空')
    await loadHistory()
  } catch (e) { /* 取消 */ }
}

onMounted(loadData)
</script>

<style scoped>
.webhooks-page {
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
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 8px;
}
.section-title {
  font-size: 16px;
  font-weight: 500;
  margin: 12px 0;
  display: flex;
  align-items: baseline;
}
.history-item {
  padding: 4px 0;
}
.history-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.webhook-name {
  font-weight: 500;
}
.history-title {
  font-size: 13px;
  margin-bottom: 2px;
}
.history-event {
  font-size: 11px;
}
.history-error {
  font-size: 11px;
  color: var(--el-color-danger);
  margin-top: 4px;
}
</style>
