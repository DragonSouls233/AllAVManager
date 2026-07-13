<template>
  <div class="metatube-page">
    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-header">
              <el-icon><Connection /></el-icon>
              <span>Metatube 插件配置</span>
              <el-tag v-if="config.enabled" type="success" size="small">已启用</el-tag>
              <el-tag v-else type="info" size="small">未启用</el-tag>
            </div>
          </template>

          <el-form :model="config" label-width="120px" size="small">
            <el-form-item label="启用">
              <el-switch v-model="config.enabled" />
              <span class="hint">允许 Jellyfin 调用 MDCX 元数据</span>
            </el-form-item>
            <el-form-item label="路由前缀">
              <el-input v-model="config.base_path" placeholder="/metatube" />
              <span class="hint">Jellyfin 插件配置中的 base url</span>
            </el-form-item>
            <el-form-item label="插件名称">
              <el-input v-model="config.plugin_name" placeholder="MDCX" />
            </el-form-item>
            <el-form-item label="访问令牌">
              <el-input v-model="tokenInput" type="password" show-password placeholder="留空不修改 / 留空则不鉴权" />
              <span class="hint">配置后 Jellyfin 调用时需携带 token</span>
            </el-form-item>
            <el-form-item label="图片质量">
              <el-slider v-model="config.image_quality" :min="1" :max="100" show-input />
            </el-form-item>
            <el-form-item label="图片返回">
              <el-switch v-model="config.image_base64" active-text="Base64" inactive-text="重定向" />
            </el-form-item>
            <el-form-item label="搜索数量">
              <el-input-number v-model="config.search_limit" :min="1" :max="100" />
            </el-form-item>
            <el-form-item label="允许 NSFW">
              <el-switch v-model="config.allow_nsfw" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
              <el-button @click="loadConfig">重载</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-header">
              <el-icon><Document /></el-icon>
              <span>Jellyfin 接入指南</span>
            </div>
          </template>

          <div class="guide">
            <h3>1. 安装 metatube 插件</h3>
            <p>在 Jellyfin 中安装 <a href="https://github.com/metatube-community/jellyfin-plugin-metatube" target="_blank">jellyfin-plugin-metatube</a> 插件。</p>

            <h3>2. 配置插件</h3>
            <p>在 Jellyfin 插件配置页面填写：</p>
            <ul>
              <li><b>服务器地址</b>：<code>{{ serverUrl }}</code></li>
              <li><b>Base URL</b>：<code>{{ config.base_path }}</code></li>
              <li><b>Token</b>：<code v-if="config.token">已配置</code><code v-else>无需填写</code></li>
            </ul>

            <h3>3. 配置媒体库</h3>
            <p>在 Jellyfin 媒体库设置中：</p>
            <ul>
              <li>类型选择「电影」</li>
              <li>元数据下载器选择「Metatube」</li>
              <li>图片下载器选择「Metatube」</li>
            </ul>

            <h3>4. API 端点</h3>
            <el-table :data="endpoints" size="small" stripe>
              <el-table-column prop="method" label="方法" width="70" />
              <el-table-column prop="path" label="路径" min-width="280" />
              <el-table-column prop="desc" label="说明" min-width="180" />
            </el-table>

            <h3>5. 测试连接</h3>
            <p>访问以下 URL 验证插件是否正常工作：</p>
            <el-input :model-value="testUrl" readonly size="small">
              <template #append>
                <el-button @click="openTest">打开</el-button>
                <el-button @click="copyTest">复制</el-button>
              </template>
            </el-input>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getMetatubeConfig, updateMetatubeConfig } from '@/api'

const config = reactive({
  enabled: false,
  base_path: '/metatube',
  plugin_name: 'MDCX',
  image_quality: 85,
  image_base64: false,
  search_limit: 20,
  allow_nsfw: true
})
const tokenInput = ref('')
const saving = ref(false)

const endpoints = [
  { method: 'GET', path: '/metatube/', desc: '插件信息' },
  { method: 'GET', path: '/metatube/search?keyword=ABC', desc: '搜索影片' },
  { method: 'GET', path: '/metatube/movie/mdcx/{id}', desc: '影片详情' },
  { method: 'GET', path: '/metatube/actor/mdcx/{id}', desc: '演员详情' },
  { method: 'GET', path: '/metatube/image/primary/mdcx/{id}', desc: '主图（封面）' },
  { method: 'GET', path: '/metatube/image/backdrop/mdcx/{id}', desc: '背景图' },
  { method: 'GET', path: '/metatube/image/thumb/mdcx/{id}', desc: '缩略图' },
  { method: 'GET', path: '/metatube/image/actor/mdcx/{id}', desc: '演员头像' }
]

const serverUrl = computed(() => {
  const stored = localStorage.getItem('serverUrl')
  return stored ? stored.replace(/\/$/, '') : window.location.origin
})

const testUrl = computed(() => `${serverUrl.value}${config.base_path}/`)

const loadConfig = async () => {
  try {
    const data = await getMetatubeConfig()
    Object.assign(config, data)
  } catch (e) { /* ignore */ }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await updateMetatubeConfig({
      enabled: config.enabled,
      base_path: config.base_path,
      plugin_name: config.plugin_name,
      token: tokenInput.value || undefined,
      image_quality: config.image_quality,
      image_base64: config.image_base64,
      search_limit: config.search_limit,
      allow_nsfw: config.allow_nsfw
    })
    ElMessage.success('配置已保存')
    tokenInput.value = ''
  } finally {
    saving.value = false
  }
}

const openTest = () => {
  window.open(testUrl.value, '_blank')
}

const copyTest = async () => {
  try {
    await navigator.clipboard.writeText(testUrl.value)
    ElMessage.success('已复制')
  } catch (e) {
    ElMessage.warning('复制失败')
  }
}

onMounted(() => { loadConfig() })
</script>

<style scoped>
.metatube-page { padding: 16px; }
.cfg-card { background: var(--el-card-bg-color, #fff); }
.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.card-header .el-tag { margin-left: 8px; }
.hint { margin-left: 8px; color: #999; font-size: 12px; }
.guide h3 { margin: 16px 0 8px; color: #303133; font-size: 15px; }
.guide h3:first-child { margin-top: 0; }
.guide p { margin: 6px 0; color: #606266; line-height: 1.6; }
.guide ul { margin: 6px 0 6px 20px; color: #606266; }
.guide li { margin: 4px 0; }
.guide code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: #c7254e;
  font-size: 13px;
}
.guide a { color: #409EFF; text-decoration: none; }
.guide a:hover { text-decoration: underline; }
</style>
