<template>
  <div class="telegram-bot-page">
    <!-- 顶部状态 -->
    <el-card shadow="never" class="status-card" :class="{ 'running': status.is_running }">
      <div class="status-header">
        <div class="status-left">
          <div class="bot-avatar" :class="{ 'online': status.is_running }">
            <el-icon size="28"><ChatLineRound /></el-icon>
          </div>
          <div class="status-info">
            <h2 class="page-title">Telegram Bot</h2>
            <div class="status-badges">
              <el-tag :type="status.is_running ? 'success' : 'info'" effect="dark" size="small">
                {{ status.is_running ? '运行中' : '已停止' }}
              </el-tag>
              <el-tag v-if="status.mode" type="warning" effect="plain" size="small">
                {{ status.mode === 'polling' ? '长轮询' : 'Webhook' }}
              </el-tag>
              <el-tag v-if="status.bot_username" type="primary" effect="plain" size="small">
                @{{ status.bot_username }}
              </el-tag>
            </div>
          </div>
        </div>
        <div class="status-actions">
          <el-button
            :type="status.is_running ? 'danger' : 'success'"
            :loading="actionLoading"
            @click="status.is_running ? stopBot() : startBot()"
          >
            <el-icon><VideoPause v-if="status.is_running" /><VideoPlay v-else /></el-icon>
            {{ status.is_running ? '停止' : '启动' }}
          </el-button>
          <el-button :loading="actionLoading" @click="restartBot" :disabled="!status.is_running">
            <el-icon><Refresh /></el-icon> 重启
          </el-button>
          <el-button @click="loadData">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 配置 -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <span class="card-title">
          <el-icon><Setting /></el-icon> Bot 配置
        </span>
      </template>
      <el-form :model="form" label-width="160px" v-loading="loading">
        <el-form-item label="Bot Token">
          <el-input
            v-model="form.bot_token"
            type="password"
            show-password
            placeholder="从 @BotFather 获取的 Bot Token"
          />
          <div class="form-tip">
            访问 <a href="https://t.me/BotFather" target="_blank">@BotFather</a> 创建 Bot 获取 Token
          </div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="运行模式">
          <el-radio-group v-model="form.mode">
            <el-radio value="polling">长轮询（推荐，无需公网）</el-radio>
            <el-radio value="webhook">Webhook（需公网 HTTPS）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Webhook URL" v-if="form.mode === 'webhook'">
          <el-input v-model="form.webhook_url" placeholder="https://your-domain/api/v1/telegram-bot/webhook" />
        </el-form-item>
        <el-form-item label="Webhook Secret" v-if="form.mode === 'webhook'">
          <el-input v-model="form.webhook_secret" placeholder="可选，提高安全性" />
        </el-form-item>
        <el-form-item label="允许的 Chat IDs">
          <el-input
            v-model="allowedChatIdsStr"
            placeholder="逗号分隔，如 123456789,987654321"
          />
          <div class="form-tip">留空则允许所有人（不推荐）。从 <a href="https://t.me/userinfobot" target="_blank">@userinfobot</a> 获取你的 Chat ID</div>
        </el-form-item>
        <el-form-item label="允许的用户名">
          <el-input
            v-model="allowedUsernamesStr"
            placeholder="逗号分隔，如 username1,username2（不带@）"
          />
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="form.language" style="width: 200px">
            <el-option label="中文" value="zh" />
            <el-option label="English" value="en" />
          </el-select>
        </el-form-item>
        <el-form-item label="内联搜索">
          <el-switch v-model="form.enable_inline_search" />
          <div class="form-tip">允许在聊天框直接 @bot 搜索影片</div>
        </el-form-item>
        <el-form-item label="通知事件">
          <el-checkbox-group v-model="form.notification_events">
            <el-checkbox value="movie_added">影片入库</el-checkbox>
            <el-checkbox value="scrape_completed">刮削完成</el-checkbox>
            <el-checkbox value="new_movie_subscribed">订阅新片</el-checkbox>
            <el-checkbox value="play_completed">观看完成</el-checkbox>
            <el-checkbox value="import_completed">导入完成</el-checkbox>
            <el-checkbox value="system_alert">系统告警</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
          <el-button @click="testToken" :loading="testing">
            <el-icon><Connection /></el-icon> 测试 Token
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 测试结果 -->
    <el-card shadow="never" class="test-card" v-if="testResult">
      <template #header>
        <span class="card-title">
          <el-icon><InfoFilled /></el-icon> Token 验证结果
        </span>
      </template>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="Bot ID">{{ testResult.id }}</el-descriptions-item>
        <el-descriptions-item label="用户名">@{{ testResult.username }}</el-descriptions-item>
        <el-descriptions-item label="名称">{{ testResult.first_name }}</el-descriptions-item>
        <el-descriptions-item label="可加入群组">{{ testResult.can_join_groups ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="可读所有消息">{{ testResult.can_read_all_group_messages ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="支持内联">{{ testResult.supports_inline_queries ? '是' : '否' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 命令列表 -->
    <el-card shadow="never" class="commands-card">
      <template #header>
        <span class="card-title">
          <el-icon><List /></el-icon> 支持的命令
        </span>
      </template>
      <el-table :data="commands" stripe size="small">
        <el-table-column prop="cmd" label="命令" width="160" />
        <el-table-column prop="desc" label="说明" />
      </el-table>
    </el-card>

    <!-- 发送消息 -->
    <el-card shadow="never" class="send-card">
      <template #header>
        <span class="card-title">
          <el-icon><Promotion /></el-icon> 发送消息
        </span>
      </template>
      <el-form label-width="100px">
        <el-form-item label="Chat ID">
          <el-input v-model="sendForm.chat_id" placeholder="目标 Chat ID" />
        </el-form-item>
        <el-form-item label="消息内容">
          <el-input
            v-model="sendForm.text"
            type="textarea"
            :rows="4"
            placeholder="支持 Markdown 格式"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="sending" @click="sendMessage">发送</el-button>
          <el-button :loading="broadcasting" @click="broadcastMessage">
            <el-icon><Bell /></el-icon> 广播到所有允许的 Chat
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ChatLineRound, Setting, Refresh, VideoPlay, VideoPause, Connection,
  InfoFilled, List, Promotion, Bell
} from '@element-plus/icons-vue'
import {
  getTelegramBotConfig, updateTelegramBotConfig,
  getTelegramBotStatus, startTelegramBot, stopTelegramBot, restartTelegramBot,
  sendTelegramMessage, broadcastTelegram, testTelegramToken
} from '@/api'

const loading = ref(false)
const saving = ref(false)
const actionLoading = ref(false)
const testing = ref(false)
const sending = ref(false)
const broadcasting = ref(false)

const status = ref({ is_running: false, mode: 'polling' })
const form = ref({
  bot_token: '',
  enabled: false,
  mode: 'polling',
  webhook_url: '',
  webhook_secret: '',
  allowed_chat_ids: [],
  allowed_usernames: [],
  language: 'zh',
  enable_inline_search: false,
  notification_events: []
})
const allowedChatIdsStr = ref('')
const allowedUsernamesStr = ref('')
const testResult = ref(null)

const sendForm = ref({
  chat_id: '',
  text: ''
})

const commands = [
  { cmd: '/start', desc: '开始使用 Bot' },
  { cmd: '/help', desc: '查看帮助' },
  { cmd: '/status', desc: '查看系统状态' },
  { cmd: '/ping', desc: '测试连通性' },
  { cmd: '/subscribe', desc: '查看订阅列表' },
  { cmd: '/subscriptions', desc: '管理订阅' },
  { cmd: '/search <关键词>', desc: '搜索影片' },
  { cmd: '/report', desc: '查看观影报告' }
]

const loadData = async () => {
  loading.value = true
  try {
    const [cfg, st] = await Promise.all([
      getTelegramBotConfig(),
      getTelegramBotStatus()
    ])
    form.value = {
      bot_token: '',  // 后端返回的是脱敏的，不回填
      enabled: cfg.enabled ?? false,
      mode: cfg.mode || 'polling',
      webhook_url: cfg.webhook_url || '',
      webhook_secret: '',
      allowed_chat_ids: cfg.allowed_chat_ids || [],
      allowed_usernames: cfg.allowed_usernames || [],
      language: cfg.language || 'zh',
      enable_inline_search: cfg.enable_inline_search ?? false,
      notification_events: cfg.notification_events || []
    }
    allowedChatIdsStr.value = (cfg.allowed_chat_ids || []).join(',')
    allowedUsernamesStr.value = (cfg.allowed_usernames || []).join(',')
    status.value = st
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const data = {
      enabled: form.value.enabled,
      mode: form.value.mode,
      webhook_url: form.value.webhook_url || null,
      language: form.value.language,
      enable_inline_search: form.value.enable_inline_search,
      notification_events: form.value.notification_events,
      allowed_chat_ids: allowedChatIdsStr.value
        .split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)),
      allowed_usernames: allowedUsernamesStr.value
        .split(',').map(s => s.trim()).filter(Boolean)
    }
    if (form.value.bot_token) data.bot_token = form.value.bot_token
    if (form.value.webhook_secret) data.webhook_secret = form.value.webhook_secret
    await updateTelegramBotConfig(data)
    ElMessage.success('配置已保存')
    loadData()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const testToken = async () => {
  testing.value = true
  try {
    const res = await testTelegramToken()
    testResult.value = res
    ElMessage.success('Token 验证成功')
  } catch (e) {
    ElMessage.error('Token 验证失败，请检查 Token 是否正确')
  } finally {
    testing.value = false
  }
}

const startBot = async () => {
  actionLoading.value = true
  try {
    const res = await startTelegramBot()
    status.value = res.status || status.value
    ElMessage.success('Bot 已启动')
  } catch (e) {
    ElMessage.error('启动失败')
  } finally {
    actionLoading.value = false
  }
}

const stopBot = async () => {
  actionLoading.value = true
  try {
    const res = await stopTelegramBot()
    status.value = res.status || status.value
    ElMessage.success('Bot 已停止')
  } catch (e) {
    ElMessage.error('停止失败')
  } finally {
    actionLoading.value = false
  }
}

const restartBot = async () => {
  actionLoading.value = true
  try {
    const res = await restartTelegramBot()
    status.value = res.status || status.value
    ElMessage.success('Bot 已重启')
  } catch (e) {
    ElMessage.error('重启失败')
  } finally {
    actionLoading.value = false
  }
}

const sendMessage = async () => {
  if (!sendForm.value.chat_id || !sendForm.value.text) {
    ElMessage.warning('请填写 Chat ID 和消息内容')
    return
  }
  sending.value = true
  try {
    await sendTelegramMessage({
      chat_id: sendForm.value.chat_id,
      text: sendForm.value.text
    })
    ElMessage.success('消息已发送')
    sendForm.value.text = ''
  } catch (e) {
    ElMessage.error('发送失败')
  } finally {
    sending.value = false
  }
}

const broadcastMessage = async () => {
  if (!sendForm.value.text) {
    ElMessage.warning('请填写消息内容')
    return
  }
  broadcasting.value = true
  try {
    const res = await broadcastTelegram({ text: sendForm.value.text })
    ElMessage.success(`已广播到 ${res.sent || 0} 个 Chat`)
  } catch (e) {
    ElMessage.error('广播失败')
  } finally {
    broadcasting.value = false
  }
}

onMounted(() => loadData())
</script>

<style scoped>
.telegram-bot-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.status-card,
.config-card,
.test-card,
.commands-card,
.send-card {
  border-radius: 8px !important;
}

.status-card {
  transition: all 0.3s;
}

.status-card.running {
  border-color: #67c23a;
  box-shadow: 0 0 0 1px rgba(103, 194, 58, 0.2);
}

.status-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.bot-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #909399;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.bot-avatar.online {
  background: #67c23a;
  box-shadow: 0 0 0 4px rgba(103, 194, 58, 0.2);
}

.status-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.page-title {
  margin: 0;
  font-size: 18px;
}

.status-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.status-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.form-tip {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.5;
}

.form-tip a {
  color: var(--primary-color);
  text-decoration: none;
}

.form-tip a:hover {
  text-decoration: underline;
}
</style>
