<template>
  <div class="cookie-manager-container">
    <div class="page-header">
      <h2>Cookie 管理器</h2>
      <el-button @click="refreshAll" :loading="loading">
        <el-icon><Refresh /></el-icon> 刷新状态
      </el-button>
    </div>

    <p class="page-desc">
      Cookie 浏览器登录将使用项目内置代理，保证 Cookie IP 与爬虫请求 IP 一致，避免 Cookie 失效。
    </p>

    <div v-for="site in sites" :key="site.key" class="site-card">
      <div class="site-header">
        <span class="site-name">{{ site.name }}
          <el-tag size="small" type="info">{{ site.domain }}</el-tag>
        </span>
        <el-tag :type="site.statusTag">{{ site.statusText }}</el-tag>
      </div>

      <div class="site-body" v-if="site.detail">
        <span class="detail-item" v-if="site.detail.configured">
          长度: {{ site.detail.length }} |
          预览: <code>{{ site.detail.preview || '无' }}</code>
        </span>
      </div>

      <div class="site-actions">
        <el-button type="primary" @click="startLogin(site.key)"
          :disabled="site.loggingIn" :loading="site.loggingIn">
          <el-icon><Key /></el-icon> 浏览器登录
        </el-button>
        <el-button @click="validateCookie(site.key)" :loading="site.validating">
          <el-icon><CircleCheck /></el-icon> 验证
        </el-button>
        <el-button @click="showManualDialog(site)">
          <el-icon><EditPen /></el-icon> 手动填写
        </el-button>
      </div>

      <div class="login-log" v-if="site.loginStatus">
        <span :class="'log-' + (site.loginStatus.status || '')">
          {{ site.loginStatus.message }}
        </span>
      </div>
    </div>

    <el-dialog v-model="manualDialog.visible" :title="'手动填写 ' + manualDialog.site.name + ' Cookie'" width="700px">
      <el-input v-model="manualDialog.cookie" type="textarea" :rows="8"
        placeholder="粘贴 Cookie 字符串，格式: key=value; key2=value2; ..." />
      <template #footer>
        <el-button @click="manualDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveManualCookie">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Key, CircleCheck, EditPen } from '@element-plus/icons-vue'
import { cookieStatus, cookieLogin, cookieLoginStatus, cookieValidate, cookieSet } from '../api'

const loading = ref(false)
const refreshTimer = ref(null)

const sites = reactive([
  { key: 'javdb', name: 'JavDB', domain: 'javdb.com', statusText: '检查中...', statusTag: 'info', detail: null, loggingIn: false, validating: false, loginStatus: null },
  { key: 'javbus', name: 'JavBus', domain: 'javbus.com', statusText: '检查中...', statusTag: 'info', detail: null, loggingIn: false, validating: false, loginStatus: null },
  { key: 'fc2ppvdb', name: 'FC2PPVDB', domain: 'fc2ppvdb.com', statusText: '检查中...', statusTag: 'info', detail: null, loggingIn: false, validating: false, loginStatus: null },
  { key: 'pan115', name: '115网盘', domain: '115.com', statusText: '检查中...', statusTag: 'info', detail: null, loggingIn: false, validating: false, loginStatus: null },
])

const manualDialog = reactive({ visible: false, site: {}, cookie: '' })

async function refreshAll() {
  loading.value = true
  try {
    const data = await cookieStatus()
    for (const site of sites) {
      const info = data[site.key]
      if (info) {
        site.detail = info
        if (info.configured) {
          site.statusText = '已配置 (' + info.length + '字符)'
          site.statusTag = 'success'
        } else {
          site.statusText = '未配置'
          site.statusTag = 'warning'
        }
      } else {
        site.detail = null
        site.statusText = '未知'
        site.statusTag = 'info'
      }
    }
  } catch (e) {
    ElMessage.error('获取 Cookie 状态失败')
  } finally {
    loading.value = false
  }
}

async function startLogin(siteKey) {
  const site = sites.find(s => s.key === siteKey)
  if (!site) return
  site.loggingIn = true
  site.loginStatus = { status: 'starting', message: '正在启动浏览器...' }
  try {
    await cookieLogin(siteKey)
    pollLoginStatus(siteKey, site)
  } catch (e) {
    site.loginStatus = { status: 'failed', message: '启动失败: ' + (e.message || '未知错误') }
    site.loggingIn = false
  }
}

async function pollLoginStatus(siteKey, site) {
  const MAX_POLL = 300
  let count = 0
  while (count < MAX_POLL && site.loggingIn) {
    try {
      const status = await cookieLoginStatus(siteKey)
      site.loginStatus = status
      if (status.status === 'completed' || status.status === 'failed') {
        site.loggingIn = false
        if (status.status === 'completed') {
          ElMessage.success(status.message)
          refreshAll()
        } else {
          ElMessage.error(status.message)
        }
        break
      }
    } catch (e) {
      // ignore
    }
    count++
    await new Promise(r => setTimeout(r, 2000))
  }
  if (count >= MAX_POLL) {
    site.loggingIn = false
    site.loginStatus = { status: 'timeout', message: '登录超时' }
  }
}

async function validateCookie(siteKey) {
  const site = sites.find(s => s.key === siteKey)
  if (!site) return
  site.validating = true
  try {
    const result = await cookieValidate(siteKey)
    if (result.valid) {
      ElMessage.success(result.message)
    } else {
      ElMessage.error(result.message)
    }
  } catch (e) {
    ElMessage.error('验证失败: ' + (e.message || '未知错误'))
  } finally {
    site.validating = false
  }
}

function showManualDialog(site) {
  manualDialog.site = site
  manualDialog.cookie = ''
  manualDialog.visible = true
}

async function saveManualCookie() {
  try {
    await cookieSet(manualDialog.site.key, { cookie: manualDialog.cookie })
    ElMessage.success('Cookie 已保存')
    manualDialog.visible = false
    refreshAll()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || '未知错误'))
  }
}

onMounted(() => {
  refreshAll()
  refreshTimer.value = setInterval(refreshAll, 30000)
})

onUnmounted(() => {
  if (refreshTimer.value) clearInterval(refreshTimer.value)
})
</script>

<style scoped>
.cookie-manager-container {
  padding: 20px;
  max-width: 900px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.page-header h2 { margin: 0; }
.page-desc {
  color: #909399;
  font-size: 13px;
  margin-bottom: 20px;
  padding: 8px 12px;
  background: #f0f9eb;
  border-radius: 6px;
  border-left: 3px solid #67c23a;
}
.site-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}
.site-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.site-name { font-weight: 600; font-size: 15px; }
.site-name .el-tag { margin-left: 8px; }
.site-body { margin-bottom: 10px; font-size: 13px; color: #606266; }
.site-body code { background: #f5f7fa; padding: 1px 5px; border-radius: 3px; }
.site-actions { display: flex; gap: 8px; }
.login-log {
  margin-top: 10px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
}
.log-starting, .log-opening, .log-waiting { color: #409eff; }
.log-saving { color: #e6a23c; }
.log-completed { color: #67c23a; }
.log-failed, .log-timeout { color: #f56c6c; }
</style>
