<template>
  <div class="cookiecloud-page">
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-title">
          <el-icon><Connection /></el-icon> CookieCloud 配置
          <el-tag v-if="form.enabled" type="success" size="small" style="margin-left: 8px">已启用</el-tag>
          <el-tag v-else type="info" size="small" style="margin-left: 8px">未启用</el-tag>
        </div>
      </template>
      <el-form :model="form" label-width="180px" style="max-width: 720px">
        <el-form-item label="启用 CookieCloud">
          <el-switch v-model="form.enabled" />
          <span class="form-tip">开启后会自动从 CookieCloud 服务器同步浏览器 Cookie</span>
        </el-form-item>
        <el-form-item label="服务器地址">
          <el-input v-model="form.server_url" placeholder="https://cookiecloud.example.com" />
          <span class="form-tip">自建或公共 CookieCloud 服务器地址</span>
        </el-form-item>
        <el-form-item label="用户 ID (UUID)">
          <el-input v-model="form.user_id" placeholder="浏览器扩展生成的 UUID" />
        </el-form-item>
        <el-form-item label="加密密码">
          <el-input v-model="form.password" type="password" show-password placeholder="浏览器扩展设置的密码" />
        </el-form-item>
        <el-form-item label="自动同步间隔 (秒)">
          <el-input-number v-model="form.auto_sync_interval" :min="300" :max="86400" :step="300" />
          <span class="form-tip">范围 300-86400 秒（5 分钟 - 24 小时）</span>
        </el-form-item>
        <el-form-item label="域名映射">
          <el-table :data="domainMappingRows" border size="small" style="width: 100%">
            <el-table-column prop="domain" label="站点域名" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.domain" size="small" />
              </template>
            </el-table-column>
            <el-table-column prop="field" label="对应 Cookie 字段" min-width="160">
              <template #default="{ row }">
                <el-select v-model="row.field" size="small">
                  <el-option label="javdb_cookie" value="javdb_cookie" />
                  <el-option label="javbus_cookie" value="javbus_cookie" />
                  <el-option label="fc2ppvdb_cookie" value="fc2ppvdb_cookie" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ $index }">
                <el-button size="small" type="danger" text @click="removeMapping($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-button size="small" @click="addMapping" style="margin-top: 8px">+ 添加映射</el-button>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="loadConfig">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="status-card">
      <template #header>
        <div class="card-title">
          <el-icon><Refresh /></el-icon> 同步状态
          <el-button type="primary" size="small" style="margin-left: auto" @click="syncNow" :loading="syncing">
            立即同步
          </el-button>
        </div>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="上次同步时间">
          {{ status.last_sync_at ? formatTime(status.last_sync_at) : '从未同步' }}
        </el-descriptions-item>
        <el-descriptions-item label="同步状态">
          <el-tag v-if="status.last_status?.ok" type="success" size="small">{{ status.last_status?.msg }}</el-tag>
          <el-tag v-else-if="status.last_status?.msg" type="danger" size="small">{{ status.last_status?.msg }}</el-tag>
          <el-tag v-else type="info" size="small">未同步</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="已同步站点数">{{ status.last_status?.count || 0 }}</el-descriptions-item>
        <el-descriptions-item label="自动同步间隔">{{ form.auto_sync_interval }} 秒</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never" class="guide-card">
      <template #header>
        <div class="card-title">
          <el-icon><InfoFilled /></el-icon> 使用指南
        </div>
      </template>
      <el-steps direction="vertical" :active="4" process-status="success">
        <el-step title="安装浏览器扩展">
          <template #description>
            在 Chrome/Edge/Firefox 安装 CookieCloud 扩展（开源项目）
          </template>
        </el-step>
        <el-step title="配置扩展">
          <template #description>
            在扩展设置中填写 CookieCloud 服务器地址、设置加密密码，获取用户 ID (UUID)
          </template>
        </el-step>
        <el-step title="登录目标站点">
          <template #description>
            在浏览器中正常登录 JavDB / JavBus / FC2PPVDB 等站点
          </template>
        </el-step>
        <el-step title="在本页配置并同步">
          <template #description>
            填写相同的 服务器地址 / 用户 ID / 密码，点击「立即同步」即可自动覆盖到爬虫配置
          </template>
        </el-step>
        <el-step title="开启自动同步">
          <template #description>
            启用 CookieCloud 后，后端会按设定间隔自动拉取最新 Cookie，无需手动操作
          </template>
        </el-step>
      </el-steps>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, Refresh, InfoFilled } from '@element-plus/icons-vue'
import {
  getCookieCloudConfig, updateCookieCloudConfig, syncCookieCloudNow, getCookieCloudStatus
} from '@/api'

const saving = ref(false)
const syncing = ref(false)

const form = reactive({
  enabled: false,
  server_url: '',
  user_id: '',
  password: '',
  auto_sync_interval: 3600,
})

// 域名映射（表格形式编辑）
const domainMappingRows = ref([])

const status = ref({
  last_sync_at: null,
  last_status: { ok: false, msg: '', count: 0 },
})

const loadConfig = async () => {
  try {
    const [cfg, stat] = await Promise.all([getCookieCloudConfig(), getCookieCloudStatus()])
    form.enabled = cfg.enabled
    form.server_url = cfg.server_url
    form.user_id = cfg.user_id
    form.password = '' // 不回显
    form.auto_sync_interval = cfg.auto_sync_interval

    // 转换 domain_mapping dict → rows
    domainMappingRows.value = Object.entries(cfg.domain_mapping || {}).map(([domain, field]) => ({
      domain,
      field,
    }))

    status.value = stat
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    // 转换 rows → dict
    const domainMapping = {}
    for (const row of domainMappingRows.value) {
      if (row.domain && row.field) {
        domainMapping[row.domain] = row.field
      }
    }
    await updateCookieCloudConfig({
      enabled: form.enabled,
      server_url: form.server_url,
      user_id: form.user_id,
      password: form.password || undefined,
      domain_mapping: domainMapping,
      auto_sync_interval: form.auto_sync_interval,
    })
    ElMessage.success('配置已保存，重启后端后生效')
    loadConfig()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const syncNow = async () => {
  syncing.value = true
  try {
    const res = await syncCookieCloudNow()
    if (res.ok) {
      ElMessage.success(res.msg)
    } else {
      ElMessage.warning(res.msg)
    }
    loadConfig()
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    syncing.value = false
  }
}

const addMapping = () => {
  domainMappingRows.value.push({ domain: '', field: 'javdb_cookie' })
}

const removeMapping = (index) => {
  domainMappingRows.value.splice(index, 1)
}

const formatTime = (iso) => {
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.cookiecloud-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1000px;
  margin: 0 auto;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.form-tip {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.5;
}

.guide-card :deep(.el-step__description) {
  font-size: 13px;
  padding-bottom: 12px;
}
</style>
