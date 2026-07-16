<template>
  <div class="settings">
    <el-tabs v-model="activeTab" class="settings-tabs" type="border-card">
      <!-- 服务器配置 -->
      <el-tab-pane label="服务器" name="server">
        <el-card shadow="never" class="setting-card">
          <template #header>
            <div class="card-title"><el-icon><Monitor /></el-icon> 服务器连接</div>
          </template>
          <el-form label-width="140px" :model="serverConfig">
            <el-form-item label="服务器地址">
              <el-input v-model="serverConfig.url" placeholder="http://localhost:8420">
                <template #append>
                  <el-button @click="saveServerUrl" type="primary">保存</el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item label="连接状态">
              <el-tag :type="serverConfig.connected ? 'success' : 'danger'">
                {{ serverConfig.connected ? '已连接' : '未连接' }}
              </el-tag>
              <el-button text @click="checkConnection" style="margin-left: 12px">
                <el-icon><Refresh /></el-icon> 检查
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 后端配置 -->
      <el-tab-pane label="后端配置" name="backend" lazy>
        <el-card shadow="never" class="setting-card" v-loading="configLoading">
          <template #header>
            <div class="card-title">
              <el-icon><Setting /></el-icon> 后端配置
              <div class="header-actions">
                <el-button size="small" @click="loadConfig">重新加载</el-button>
                <el-button size="small" type="warning" @click="confirmReset">重置默认</el-button>
                <el-button size="small" type="primary" @click="saveBackendConfig" :loading="saving">保存</el-button>
              </div>
            </div>
          </template>

          <el-collapse v-model="activeCollapse">
            <el-collapse-item title="代理设置" name="proxy">
              <el-form label-width="160px" :model="backendConfig.proxy">
                <el-form-item label="启用代理">
                  <el-switch v-model="backendConfig.proxy.enabled" />
                </el-form-item>
                <el-form-item label="代理类型">
                  <el-radio-group v-model="backendConfig.proxy.protocol">
                    <el-radio value="http">HTTP</el-radio>
                    <el-radio value="socks5">SOCKS5</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item label="HTTP 代理">
                  <el-input v-model="backendConfig.proxy.http" placeholder="http://127.0.0.1:10809" />
                </el-form-item>
                <el-form-item label="SOCKS5 代理">
                  <el-input v-model="backendConfig.proxy.socks5" placeholder="socks5://127.0.0.1:10808" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" plain @click="testProxyAction" :loading="proxyTesting">
                    <el-icon><Connection /></el-icon> 测试代理连通性
                  </el-button>
                </el-form-item>
              </el-form>
            </el-collapse-item>

            <el-collapse-item title="刮削配置" name="scraper">
              <el-form label-width="160px" :model="backendConfig.scraper">
                <el-form-item label="并发数">
                  <el-input-number v-model="backendConfig.scraper.concurrent_limit" :min="1" :max="20" />
                </el-form-item>
                <el-form-item label="超时(秒)">
                  <el-input-number v-model="backendConfig.scraper.timeout" :min="10" :max="300" />
                </el-form-item>
                <el-form-item label="重试次数">
                  <el-input-number v-model="backendConfig.scraper.retry_count" :min="0" :max="10" />
                </el-form-item>
                <el-form-item label="各模块媒体目录">
                  <div style="width:100%">
                    <div v-for="mod in moduleDirs" :key="mod.name" style="margin-bottom:12px;padding:12px;border:1px solid #ebeef5;border-radius:6px;">
                      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                        <el-text size="small" tag="b">{{ mod.label }}</el-text>
                        <el-tag v-if="mod.dir" size="small" type="info" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ mod.dir }}</el-tag>
                        <el-tag v-else size="small" type="warning">未配置</el-tag>
                      </div>
                      <div style="display:flex;gap:8px;">
                        <el-input
                          :model-value="mod.dir"
                          @input="(v) => onModuleDirInput(mod.name, v)"
                          placeholder="输入模块媒体目录路径"
                          size="small"
                          clearable
                        />
                        <el-button size="small" type="primary" @click="saveModuleDir(mod.name)" :loading="savingModuleDir === mod.name">保存</el-button>
                      </div>
                    </div>
                  </div>
                </el-form-item>
              </el-form>
            </el-collapse-item>

            <el-collapse-item title="JavDB Cookie" name="javdb">
              <el-form label-width="160px">
                <el-form-item label="Cookie 字符串">
                  <el-input
                    v-model="cookies.javdb"
                    type="textarea"
                    :rows="3"
                    placeholder="复制浏览器中的 Cookie 字符串"
                  />
                </el-form-item>
                <el-form-item>
                  <el-button @click="checkCookieAction('javdb')" :loading="cookieChecking.javdb">
                    检查 Cookie
                  </el-button>
                  <el-button type="primary" plain @click="cookieLoginAction('javdb')" :loading="cookieLoginLoading.javdb">
                    <el-icon><User /></el-icon> 浏览器登录获取
                  </el-button>
                </el-form-item>
                <el-form-item v-if="cookieLoginStatus.javdb" label="登录状态">
                  <el-tag :type="cookieLoginStatus.javdb === 'success' ? 'success' : 'warning'">
                    {{ cookieLoginStatus.javdb }}
                  </el-tag>
                </el-form-item>
              </el-form>
            </el-collapse-item>

            <el-collapse-item title="JavBus Cookie" name="javbus">
              <el-form label-width="160px">
                <el-form-item label="Cookie 字符串">
                  <el-input
                    v-model="cookies.javbus"
                    type="textarea"
                    :rows="3"
                    placeholder="复制浏览器中的 Cookie 字符串"
                  />
                </el-form-item>
                <el-form-item>
                  <el-button @click="checkCookieAction('javbus')" :loading="cookieChecking.javbus">
                    检查 Cookie
                  </el-button>
                  <el-button type="primary" plain @click="cookieLoginAction('javbus')" :loading="cookieLoginLoading.javbus">
                    <el-icon><User /></el-icon> 浏览器登录获取
                  </el-button>
                </el-form-item>
              </el-form>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </el-tab-pane>

      <!-- 认证配置 -->
      <el-tab-pane label="认证" name="auth" lazy>
        <el-card shadow="never" class="setting-card" v-loading="authLoading">
          <template #header>
            <div class="card-title">
              <el-icon><Key /></el-icon> 局域网可信 IP 自动登录
              <div class="header-actions">
                <el-button size="small" type="primary" @click="saveAuthConfig" :loading="authSaving">保存</el-button>
              </div>
            </div>
          </template>

          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 16px"
          >
            启用后，列表中的 IP / IP 段访问 API 无需登录 token。<br>
            前端登录页会显示"可信网络直接进入"按钮，自动跳转首页。
          </el-alert>

          <el-form label-width="160px">
            <el-form-item label="启用可信 IP">
              <el-switch v-model="authConfig.enable_trusted_ip" />
              <el-text type="info" size="small" style="margin-left: 12px">
                {{ authConfig.enable_trusted_ip ? '已启用' : '已禁用' }}
              </el-text>
            </el-form-item>
            <el-form-item label="可信 IP 列表">
              <el-input
                v-model="trustedIPsText"
                type="textarea"
                :rows="8"
                placeholder="每行一条，支持单 IP 或 CIDR 段&#10;例如：&#10;127.0.0.1&#10;192.168.1.0/24&#10;10.0.0.0/8"
              />
              <div class="form-tip">
                <el-text type="info" size="small">
                  支持 IPv4 / IPv6，CIDR 段（如 192.168.0.0/16 覆盖整个 192.168.x.x）
                </el-text>
              </div>
            </el-form-item>
            <el-form-item label="快捷模板">
              <el-button size="small" @click="applyTemplate('lan')">局域网常用段</el-button>
              <el-button size="small" @click="applyTemplate('localhost')">仅本机</el-button>
              <el-button size="small" @click="applyTemplate('clear')">清空</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 关于 -->
      <el-tab-pane label="关于" name="about">
        <el-card shadow="never" class="setting-card">
          <div class="about-content">
            <h2>龙魂视频管理系统</h2>
            <div class="about-grid">
              <div class="about-item">
                <div class="about-label">版本</div>
                <div class="about-value">{{ aboutVersion }}</div>
              </div>
              <div class="about-item">
                <div class="about-label">前端技术</div>
                <div class="about-value">Vue 3 + Element Plus + Electron</div>
              </div>
              <div class="about-item">
                <div class="about-label">后端技术</div>
                <div class="about-value">FastAPI + SQLAlchemy + curl_cffi</div>
              </div>
              <div class="about-item">
                <div class="about-label">爬虫源</div>
                <div class="about-value">54+ 站点 · 多源聚合</div>
              </div>
              <div class="about-item">
                <div class="about-label">特色功能</div>
                <div class="about-value">本地对比 · 视频指纹 · mpv播放 · 工作流</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Monitor, Setting, Refresh, Connection, User, Key } from '@element-plus/icons-vue'
import {
  getConfig, updateConfig, resetConfig, testProxy,
  checkJavdbCookie, checkJavbusCookie, startCookieLogin, getCookieLoginPollStatus,
  healthCheck, getTrustedIPs, updateTrustedIPs, getMe,
  setServerUrl, checkServerConnection, getVersion
} from '@/api'
import { getServerBaseUrl } from '@/utils/media'
import { getModules, updateModulesConfig } from '@/api/modules'

const activeTab = ref('server')
const activeCollapse = ref(['proxy', 'scraper'])
const configLoading = ref(false)
const saving = ref(false)
const proxyTesting = ref(false)
const currentRole = ref('user')
const aboutVersion = ref('加载中...')

const serverConfig = ref({
  url: getServerBaseUrl(),
  connected: false
})

const backendConfig = ref({
  proxy: { enabled: false, protocol: 'http', http: '', socks5: '' },
  scraper: { concurrent_limit: 5, timeout: 60, retry_count: 3, media_dirs: [] }
})

// 后端 Cookie 归属 crawler.*_cookie，保留完整 crawler 配置以免保存时丢失其他字段
const crawlerConfig = ref({})

const cookies = ref({
  javdb: '',
  javbus: ''
})

const cookieChecking = ref({ javdb: false, javbus: false })
const cookieLoginLoading = ref({ javdb: false, javbus: false })
const cookieLoginStatus = ref({ javdb: '', javbus: '' })

// 各模块媒体目录配置
const moduleDirs = ref([])
const savingModuleDir = ref('')
const moduleLabelsMap = { jav: 'JAV 有码', chinese: '国产', uncensored: 'JAV 无码', fc2: 'FC2', pornhub: 'PORNHub', western: '欧美' }

async function loadModuleDirs() {
  try {
    const mods = await getModules()
    moduleDirs.value = (mods || []).map(m => ({
      name: m.name,
      label: moduleLabelsMap[m.name] || m.name,
      dir: (m.media_dirs || [])[0] || ''
    }))
  } catch {
    // 静默失败
  }
}

const editingModuleDir = ref({})

function onModuleDirInput(name, val) {
  editingModuleDir.value[name] = val
}

async function saveModuleDir(name) {
  savingModuleDir.value = name
  try {
    const dir = editingModuleDir.value[name] || ''
    const dirs = dir ? [dir] : []
    await updateModulesConfig({ [name]: { media_dirs: dirs } })
    ElMessage.success(`${moduleLabelsMap[name] || name} 目录已保存`)
    // 刷新
    const mod = moduleDirs.value.find(m => m.name === name)
    if (mod) mod.dir = dir
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail || e.message || '未知错误'))
  } finally {
    savingModuleDir.value = ''
  }
}

// 当前登录用户角色（用于限制媒体目录等仅管理员可改）
const loadCurrentUser = async () => {
  try {
    const res = await getMe()
    currentRole.value = res.role || 'user'
  } catch {
    currentRole.value = 'user'
  }
}

const saveServerUrl = () => {
  setServerUrl(serverConfig.value.url)
  ElMessage.success('服务器地址已保存，即时生效')
}

const checkConnection = async () => {
  try {
    const result = await checkServerConnection()
    serverConfig.value.connected = result.ok
    if (result.ok) {
      ElMessage.success(`服务器连接正常 (v${result.version || '?'})`)
    } else {
      ElMessage.error(`连接失败: ${result.error}`)
    }
  } catch {
    serverConfig.value.connected = false
    ElMessage.error('服务器连接失败')
  }
}

const loadConfig = async () => {
  configLoading.value = true
  try {
    const res = await getConfig()
    backendConfig.value = {
      proxy: {
        enabled: res.proxy?.enabled ?? false,
        protocol: res.proxy?.protocol ?? 'http',
        http: res.proxy?.http ?? res.proxy?.proxy_url ?? '',
        socks5: res.proxy?.socks5 ?? ''
      },
      scraper: {
        concurrent_limit: res.scraper?.concurrent_limit ?? 5,
        timeout: res.scraper?.timeout ?? 60,
        retry_count: res.scraper?.retry_count ?? 3,
        media_dirs: res.scraper?.media_dirs ?? res.media_dirs ?? []
      }
    }
    // 保留完整 crawler 配置（含 fc2ppvdb_cookie 等），保存时再覆盖 javdb/javbus
    crawlerConfig.value = res.crawler ?? {}
    cookies.value.javdb = res.crawler?.javdb_cookie ?? res.javdb_cookie ?? ''
    cookies.value.javbus = res.crawler?.javbus_cookie ?? res.javbus_cookie ?? ''
  } catch (e) {
    console.error('加载配置失败', e)
  } finally {
    configLoading.value = false
  }
}

const saveBackendConfig = async () => {
  saving.value = true
  try {
    await updateConfig({
      proxy: {
        enabled: backendConfig.value.proxy.enabled,
        protocol: backendConfig.value.proxy.protocol,
        http: backendConfig.value.proxy.http,
        socks5: backendConfig.value.proxy.socks5
      },
      scraper: backendConfig.value.scraper,
      // Cookie 归属 crawler.*_cookie，保留其他 crawler 字段避免丢失
      crawler: {
        ...crawlerConfig.value,
        javdb_cookie: cookies.value.javdb,
        javbus_cookie: cookies.value.javbus
      }
    })
    ElMessage.success('配置已保存')
  } catch (e) {
    console.error(e)
  } finally {
    saving.value = false
  }
}

const confirmReset = () => {
  ElMessageBox.confirm('确认重置所有配置为默认值？', '警告', {
    type: 'warning'
  }).then(async () => {
    try {
      await resetConfig()
      ElMessage.success('已重置为默认配置')
      loadConfig()
    } catch (e) {
      console.error(e)
    }
  }).catch(() => {})
}

const testProxyAction = async () => {
  proxyTesting.value = true
  try {
    const res = await testProxy({
      proxy: backendConfig.value.proxy
    })
    if (res.success || res.ok) {
      ElMessage.success(`代理可用，延迟 ${res.latency_ms || '-'}ms`)
    } else {
      ElMessage.warning('代理不可用：' + (res.error || '未知错误'))
    }
  } catch (e) {
    console.error(e)
  } finally {
    proxyTesting.value = false
  }
}

const checkCookieAction = async (site) => {
  cookieChecking.value[site] = true
  try {
    const fn = site === 'javdb' ? checkJavdbCookie : checkJavbusCookie
    const res = await fn(cookies.value[site])
    if (res.valid || res.ok) {
      ElMessage.success(`${site} Cookie 有效`)
    } else {
      ElMessage.warning(`${site} Cookie 无效或已过期`)
    }
  } catch (e) {
    console.error(e)
  } finally {
    cookieChecking.value[site] = false
  }
}

const cookieLoginAction = async (site) => {
  cookieLoginLoading.value[site] = true
  try {
    await startCookieLogin(site)
    ElMessage.info('已启动浏览器，请在弹出的浏览器中完成登录')
    // 轮询状态
    const timer = setInterval(async () => {
      try {
        const status = await getCookieLoginPollStatus(site)
        if (status.completed || status.success) {
          clearInterval(timer)
          cookieLoginLoading.value[site] = false
          cookieLoginStatus.value[site] = 'success'
          if (status.cookie) {
            cookies.value[site] = status.cookie
            ElMessage.success(`${site} Cookie 已自动填入`)
          }
          ElMessage.success(`${site} 登录成功`)
        } else if (status.failed || status.error) {
          clearInterval(timer)
          cookieLoginLoading.value[site] = false
          cookieLoginStatus.value[site] = 'failed'
        }
      } catch {
        clearInterval(timer)
        cookieLoginLoading.value[site] = false
      }
    }, 2000)
    // 60秒超时
    setTimeout(() => {
      if (cookieLoginLoading.value[site]) {
        clearInterval(timer)
        cookieLoginLoading.value[site] = false
        ElMessage.warning('登录超时')
      }
    }, 60000)
  } catch (e) {
    cookieLoginLoading.value[site] = false
    console.error(e)
  }
}

// ===== 认证配置（可信 IP）=====
const authLoading = ref(false)
const authSaving = ref(false)
const authConfig = ref({
  enable_trusted_ip: false,
  trusted_ips: []
})

const trustedIPsText = computed({
  get: () => (authConfig.value.trusted_ips || []).join('\n'),
  set: (val) => {
    authConfig.value.trusted_ips = val.split('\n').map(s => s.trim()).filter(Boolean)
  }
})

const loadAuthConfig = async () => {
  authLoading.value = true
  try {
    const res = await getTrustedIPs()
    authConfig.value = {
      enable_trusted_ip: res.enable_trusted_ip ?? false,
      trusted_ips: res.trusted_ips ?? []
    }
  } catch (e) {
    console.error('加载认证配置失败', e)
  } finally {
    authLoading.value = false
  }
}

const saveAuthConfig = async () => {
  authSaving.value = true
  try {
    await updateTrustedIPs({
      enable_trusted_ip: authConfig.value.enable_trusted_ip,
      trusted_ips: authConfig.value.trusted_ips
    })
    ElMessage.success('认证配置已保存')
  } catch (e) {
    console.error(e)
  } finally {
    authSaving.value = false
  }
}

const applyTemplate = (type) => {
  const templates = {
    lan: ['127.0.0.1', '192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12'],
    localhost: ['127.0.0.1'],
    clear: []
  }
  authConfig.value.trusted_ips = templates[type] || []
}

onMounted(() => {
  checkConnection()
  loadConfig()
  loadModuleDirs()
  loadAuthConfig()
  loadCurrentUser()
  getVersion().then(data => {
    aboutVersion.value = data?.version ? `v${data.version} (${data.patch_level || ''})` : '未知'
  }).catch(() => { aboutVersion.value = '未知' })
})
</script>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
}

.settings-tabs {
  border-radius: 10px;
}

.setting-card {
  border-radius: 8px;
  border: none;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #303133;
}

.header-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.about-content {
  padding: 16px;
}

.about-content h2 {
  color: #409eff;
  margin: 0 0 20px;
}

.form-tip {
  margin-top: 6px;
  line-height: 1.5;
}

.about-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.about-item {
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 8px;
}

.about-label {
  color: #909399;
  font-size: 12px;
  margin-bottom: 4px;
}

.about-value {
  color: #303133;
  font-size: 14px;
  font-weight: 500;
}
</style>
