<template>
  <div class="login-container">
    <div class="login-box">
      <div class="logo">
        <h1>龙魂</h1>
        <p>视频管理系统</p>
      </div>

      <!-- 可信 IP 提示条 -->
      <el-alert
        v-if="trustedEnabled"
        type="success"
        :closable="false"
        style="margin-bottom: 16px"
      >
        局域网自动登录已启用，可直接点击进入
      </el-alert>

      <!-- 自动登录中 -->
      <div v-if="autoLogging" class="auto-login">
        <el-icon class="is-loading" size="32"><Loading /></el-icon>
        <p>正在自动登录...</p>
      </div>

      <!-- 登录表单 -->
      <el-form v-else :model="form" @submit.prevent="handleLogin">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="用户名"
            :prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="rememberMe">记住密码（保存哈希）</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            @click="handleLogin"
            style="width: 100%"
          >
            登 录
          </el-button>
        </el-form-item>
        <el-form-item v-if="trustedEnabled">
          <el-button
            size="large"
            @click="directEnter"
            style="width: 100%"
          >
            <el-icon><Key /></el-icon>
            可信网络直接进入
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 服务器地址设置 -->
      <div class="server-entry">
        <el-popover
          placement="bottom"
          :width="360"
          trigger="click"
          v-model:visible="serverPopVisible"
        >
          <template #reference>
            <el-button text type="info" size="small">
              <el-icon><Setting /></el-icon>
              服务器连接设置
            </el-button>
          </template>
          <div class="server-pop">
            <div class="server-pop-title">后端服务器地址</div>
            <el-input
              v-model="serverUrl"
              placeholder="http://192.168.1.100:8420"
              size="small"
              clearable
              @keyup.enter="saveAndCheckServer"
            >
              <template #prepend>URL</template>
            </el-input>
            <div class="server-pop-tip">
              留空则使用当前访问地址。修改后即时生效无需刷新。
            </div>
            <div class="server-pop-actions">
              <el-button size="small" @click="saveAndCheckServer" :loading="serverChecking">
                <el-icon><CircleCheck /></el-icon> 保存并检测
              </el-button>
              <el-button size="small" @click="clearServerUrl">
                清除
              </el-button>
            </div>
            <div v-if="serverStatus" class="server-status" :class="serverStatus.ok ? 'ok' : 'fail'">
              <el-icon><component :is="serverStatus.ok ? SuccessFilled : WarningFilled" /></el-icon>
              <span>{{ serverStatus.ok ? `已连接 (v${serverStatus.version || '?'})` : serverStatus.error }}</span>
            </div>
          </div>
        </el-popover>
      </div>

      <div class="login-footer">
        <el-text type="info" size="small">
          凭证仅以 SHA-256 哈希形式存储于本地，不保存明文密码
        </el-text>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Loading, Key, Setting, CircleCheck, SuccessFilled, WarningFilled } from '@element-plus/icons-vue'
import { login, getTrustedIPs, setServerUrl, getServerUrl, checkServerConnection } from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const autoLogging = ref(false)
const rememberMe = ref(false)
const trustedEnabled = ref(false)

const form = ref({
  username: 'admin',
  password: ''
})

// 简单 SHA-256 哈希（使用 Web Crypto API）
async function sha256(text) {
  const buf = new TextEncoder().encode(text)
  const hash = await crypto.subtle.digest('SHA-256', buf)
  return Array.from(new Uint8Array(hash))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

// 检查后端是否启用了可信 IP 自动登录
async function checkTrustedIP() {
  try {
    const res = await getTrustedIPs()
    trustedEnabled.value = !!res.enable_trusted_ip
  } catch {
    // 接口不可用就静默忽略
  }
}

// 尝试用 localStorage 保存的凭证自动登录
async function tryAutoLogin() {
  const savedUser = localStorage.getItem('mdcx_saved_user')
  const savedPwdHash = localStorage.getItem('mdcx_saved_pwd_hash')
  if (!savedUser || !savedPwdHash) return false

  // 验证保存的哈希格式（64 位十六进制）
  if (!/^[a-f0-9]{64}$/.test(savedPwdHash)) {
    localStorage.removeItem('mdcx_saved_user')
    localStorage.removeItem('mdcx_saved_pwd_hash')
    return false
  }

  autoLogging.value = true
  try {
    // 由于我们只保存了哈希，无法反推密码
    // 方案：保存的哈希本身作为"凭证"发送到后端
    // 但后端目前只接受明文密码，所以这里只能：
    // 1) 如果后端启用了可信 IP，直接进入（无需登录）
    // 2) 否则提示用户重新输入密码
    if (trustedEnabled.value) {
      // 可信网络，直接跳转首页（后端中间件会自动放行）
      authStore.setToken('trusted-ip-mode')
      router.push('/')
      return true
    }
    // 没有启用可信 IP，无法自动登录，提示用户
    autoLogging.value = false
    return false
  } catch (e) {
    autoLogging.value = false
    return false
  }
}

const handleLogin = async () => {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const res = await login(form.value)
    const token = res.access_token || res.data?.token
    if (token) {
      authStore.setToken(token, { username: form.value.username })

      // 记住密码：保存用户名 + 密码哈希（不存明文）
      if (rememberMe.value) {
        try {
          const hash = await sha256(form.value.password)
          localStorage.setItem('mdcx_saved_user', form.value.username)
          localStorage.setItem('mdcx_saved_pwd_hash', hash)
        } catch {
          // crypto.subtle 在非 HTTPS 环境可能不可用，忽略
        }
      } else {
        localStorage.removeItem('mdcx_saved_user')
        localStorage.removeItem('mdcx_saved_pwd_hash')
      }

      ElMessage.success('登录成功')
      router.push('/')
    }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

// 可信网络直接进入
const directEnter = () => {
  authStore.setToken('trusted-ip-mode')
  router.push('/')
}

// 服务器地址设置
const serverPopVisible = ref(false)
const serverUrl = ref(getServerUrl())
const serverChecking = ref(false)
const serverStatus = ref(null)

const saveAndCheckServer = async () => {
  const url = serverUrl.value.trim()
  serverChecking.value = true
  serverStatus.value = null
  try {
    const result = await checkServerConnection(url || undefined)
    if (result.ok) {
      setServerUrl(url)
      serverStatus.value = result
      serverPopVisible.value = false
      ElMessage.success(`已连接 ${result.url}`)
    } else {
      serverStatus.value = result
      if (url) {
        setServerUrl(url)
        ElMessage.warning(`地址已保存但连接失败: ${result.error}`)
      }
    }
  } catch (e) {
    serverStatus.value = { ok: false, error: e.message }
  } finally {
    serverChecking.value = false
  }
}

const clearServerUrl = () => {
  setServerUrl('')
  serverUrl.value = ''
  serverStatus.value = null
  ElMessage.success('已清除服务器地址')
}

onMounted(async () => {
  await checkTrustedIP()

  // 如果有保存的凭证，尝试自动登录
  const hasSaved = localStorage.getItem('mdcx_saved_user')
  if (hasSaved) {
    rememberMe.value = true
    await tryAutoLogin()
  }
})
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
}

.login-box {
  width: 420px;
  padding: 40px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.logo {
  text-align: center;
  margin-bottom: 30px;
}

.logo h1 {
  font-size: 48px;
  color: #409eff;
  margin: 0;
}

.logo p {
  color: #666;
  margin-top: 8px;
}

.auto-login {
  text-align: center;
  padding: 40px 0;
  color: #666;
}

.auto-login p {
  margin-top: 12px;
  font-size: 14px;
}

.login-footer {
  margin-top: 16px;
  text-align: center;
}

.server-entry {
  margin-top: 8px;
  text-align: center;
}

.server-pop {
  padding: 4px 0;
}

.server-pop-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
}

.server-pop-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}

.server-pop-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}

.server-status {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding: 8px 10px;
  border-radius: 6px;
}

.server-status.ok {
  background: #f0f9eb;
  color: #67c23a;
}

.server-status.fail {
  background: #fef0f0;
  color: #f56c6c;
}
</style>
