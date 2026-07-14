<template>
  <div class="western-config">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回欧美列表
    </el-button>

    <h2>欧美模块配置</h2>

    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="基础配置" name="basic">
        <el-form :model="config" label-width="160px" style="max-width: 720px">
          <el-form-item label="启用模块">
            <el-switch v-model="config.enabled" />
          </el-form-item>
          <el-form-item label="媒体目录">
            <el-input
              v-model="dirsText"
              type="textarea"
              :rows="4"
              placeholder="每行一个目录路径"
            />
            <div class="form-tip">支持多个媒体目录，每行一个</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveBasic" :loading="saving">保存基础配置</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="刮削器" name="scraper">
        <el-form :model="config" label-width="160px" style="max-width: 720px">
          <el-form-item label="ThePornDB API Key">
            <el-input
              v-model="config.theporndb_api_key"
              type="password"
              show-password
              placeholder="请输入 ThePornDB API Key"
            />
            <div class="form-tip">在 <a href="https://theporndb.net" target="_blank">theporndb.net</a> 注册账号后获取</div>
          </el-form-item>
          <el-form-item label="启用 IAFD 演员数据">
            <el-switch v-model="config.iafd_enabled" />
            <div class="form-tip">从 IAFD.com 拉取演员详细资料（性别、出生日期、身高体重、社交账号等）</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveScraper" :loading="saving">保存刮削器配置</el-button>
          </el-button>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="品牌映射" name="brand">
        <el-form :model="config" label-width="160px" style="max-width: 720px">
          <el-form-item label="自定义品牌映射">
            <el-input
              v-model="brandMapText"
              type="textarea"
              :rows="6"
              placeholder="key=value 格式，每行一个，例如：&#10;brazzers_extra=BrazzersExxtra"
            />
            <div class="form-tip">JSON 或 key=value 格式。覆盖默认品牌前缀识别（适用于多品牌合集站点）</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveBrandMap" :loading="saving">保存品牌映射</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="代理设置" name="proxy">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          <template #title>内置代理</template>
          <p>所有欧美模块的刮削请求都通过 MDCX 内置代理（SOCKS5/HTTP）发送。</p>
          <p>代理状态: <el-tag :type="proxyOnline ? 'success' : 'danger'">{{ proxyOnline ? '在线' : '离线' }}</el-tag></p>
        </el-alert>
        <el-button @click="checkProxy" :loading="checking">检查代理状态</el-button>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getModulesConfig, updateModulesConfig } from '@/api/modules'
import { getProxyStatus } from '@/api/index'

const router = useRouter()
const activeTab = ref('basic')
const config = ref({
  enabled: false,
  media_dirs: [],
  theporndb_api_key: '',
  iafd_enabled: true,
  site_prefix_mapping: {},
})
const dirsText = ref('')
const brandMapText = ref('')
const saving = ref(false)
const proxyOnline = ref(false)
const checking = ref(false)

function goBack() {
  router.push('/western/movies')
}

async function loadConfig() {
  try {
    const res = await getModulesConfig()
    const westernConfig = res.western || {}
    config.value = {
      enabled: westernConfig.enabled || false,
      media_dirs: westernConfig.media_dirs || [],
      theporndb_api_key: westernConfig.theporndb_api_key || '',
      iafd_enabled: westernConfig.iafd_enabled !== false,
      site_prefix_mapping: westernConfig.site_prefix_mapping || {},
    }
    dirsText.value = (config.value.media_dirs || []).join('\n')
    brandMapText.value = Object.entries(config.value.site_prefix_mapping || {})
      .map(([k, v]) => `${k}=${v}`).join('\n')
  } catch (e) {
    ElMessage.error('加载配置失败: ' + (e.message || '未知错误'))
  }
}

async function saveBasic() {
  saving.value = true
  try {
    config.value.media_dirs = dirsText.value.split('\n').map(s => s.trim()).filter(Boolean)
    await updateModulesConfig({
      western: {
        enabled: config.value.enabled,
        media_dirs: config.value.media_dirs,
      }
    })
    ElMessage.success('基础配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

async function saveScraper() {
  saving.value = true
  try {
    await updateModulesConfig({
      western: {
        theporndb_api_key: config.value.theporndb_api_key,
        iafd_enabled: config.value.iafd_enabled,
      }
    })
    ElMessage.success('刮削器配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

async function saveBrandMap() {
  saving.value = true
  try {
    const map = {}
    brandMapText.value.split('\n').forEach(line => {
      line = line.trim()
      if (!line) return
      const [k, v] = line.split(/[=:]/).map(s => s.trim())
      if (k && v) map[k] = v
    })
    config.value.site_prefix_mapping = map
    await updateModulesConfig({
      western: { site_prefix_mapping: map }
    })
    ElMessage.success('品牌映射已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

async function checkProxy() {
  checking.value = true
  try {
    const res = await getProxyStatus()
    proxyOnline.value = res?.online || res?.status === 'running' || false
  } catch (e) {
    proxyOnline.value = false
  } finally {
    checking.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.western-config { padding: 20px; }
.form-tip { font-size: 12px; color: #999; margin-top: 4px; }
</style>
