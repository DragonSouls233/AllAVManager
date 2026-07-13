<template>
  <div class="onboarding-page">
    <el-card shadow="never" class="onboarding-card">
      <el-steps :active="activeStep" finish-status="success" align-center class="onboarding-steps">
        <el-step title="欢迎" :icon="Promotion" />
        <el-step title="路径配置" :icon="FolderOpened" />
        <el-step title="爬虫启用" :icon="Connection" />
        <el-step title="完成" :icon="CircleCheckFilled" />
      </el-steps>

      <div class="step-content">
        <!-- 步骤 1：欢迎 -->
        <div v-if="activeStep === 0" class="step-panel">
          <div class="welcome-block">
            <el-icon :size="64" color="#409eff"><VideoCamera /></el-icon>
            <h2>欢迎使用 龙魂</h2>
            <p>龙魂视频管理系统配置向导将引导你完成首次设置，整个过程约 2 分钟。</p>
            <ul class="welcome-features">
              <li><el-icon><Check /></el-icon> 配置影片库扫描路径</li>
              <li><el-icon><Check /></el-icon> 启用元数据爬虫来源</li>
              <li><el-icon><Check /></el-icon> 一键完成初始化</li>
            </ul>
          </div>
        </div>

        <!-- 步骤 2：路径配置 -->
        <div v-else-if="activeStep === 1" class="step-panel">
          <h3>配置影片库路径</h3>
          <p class="step-hint">指定本地存放影片的目录，系统会自动扫描并建立索引。</p>
          <el-form label-position="top" class="path-form">
            <el-form-item label="影片库目录">
              <el-input
                v-model="form.movieDirectory"
                placeholder="例如：D:\Movies 或 /home/user/movies"
                clearable
              >
                <template #prefix>
                  <el-icon><FolderOpened /></el-icon>
                </template>
                <template #append>
                  <el-button @click="pickDirectory" :loading="pickingDir">
                    <el-icon><FolderAdd /></el-icon> 选择
                  </el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item label="服务器地址（可选）">
              <el-input
                v-model="form.serverUrl"
                placeholder="http://localhost:8420"
                clearable
              >
                <template #prefix>
                  <el-icon><Link /></el-icon>
                </template>
              </el-input>
              <div class="form-tip">MDCX 后端 API 地址，留空则使用默认值。</div>
            </el-form-item>
          </el-form>
        </div>

        <!-- 步骤 3：爬虫启用 -->
        <div v-else-if="activeStep === 2" class="step-panel">
          <h3>启用元数据爬虫</h3>
          <p class="step-hint">选择要从哪些来源抓取影片元数据（标题/封面/演员等）。至少启用一个。</p>
          <div class="crawler-toolbar">
            <el-button size="small" @click="loadCrawlers" :loading="crawlersLoading">
              <el-icon><Refresh /></el-icon> 重新加载
            </el-button>
            <span class="crawler-count">已启用 {{ enabledCrawlerCount }} / {{ crawlerList.length }}</span>
          </div>
          <div v-loading="crawlersLoading" class="crawler-list">
            <el-checkbox
              v-for="c in crawlerList"
              :key="c.name"
              v-model="c._enabled"
              class="crawler-item"
              border
            >
              <div class="crawler-info">
                <span class="crawler-name">{{ c.name }}</span>
                <el-tag v-if="c.enabled" size="small" type="success">已启用</el-tag>
                <el-tag v-else size="small" type="info">未启用</el-tag>
              </div>
            </el-checkbox>
            <EmptyState
              v-if="!crawlersLoading && !crawlerList.length"
              type="no-data"
              description="未获取到爬虫列表，请检查服务器地址或点击重新加载"
              inline
            />
          </div>
        </div>

        <!-- 步骤 4：完成 -->
        <div v-else-if="activeStep === 3" class="step-panel">
          <div class="complete-block">
            <el-icon :size="64" color="#67C23A"><CircleCheckFilled /></el-icon>
            <h2>配置完成</h2>
            <p>你已经完成 MDCX 的首次设置，可以开始使用了。</p>
            <el-descriptions :column="1" border class="summary">
              <el-descriptions-item label="影片库目录">
                {{ form.movieDirectory || '（未设置）' }}
              </el-descriptions-item>
              <el-descriptions-item label="服务器地址">
                {{ form.serverUrl || 'http://localhost:8420（默认）' }}
              </el-descriptions-item>
              <el-descriptions-item label="已启用爬虫">
                {{ enabledCrawlerList.join('、') || '无' }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </div>
      </div>

      <!-- 导航按钮 -->
      <div class="step-actions">
        <el-button v-if="activeStep > 0" @click="prevStep">
          <el-icon><ArrowLeft /></el-icon> 上一步
        </el-button>
        <el-button v-if="activeStep < 3" type="primary" @click="nextStep" :disabled="!canNext">
          下一步 <el-icon><ArrowRight /></el-icon>
        </el-button>
        <el-button v-else type="success" @click="finish">
          <el-icon><Check /></el-icon> 进入系统
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  VideoCamera, Promotion, FolderOpened, Connection, CircleCheckFilled,
  Check, FolderAdd, Link, Refresh, ArrowLeft, ArrowRight
} from '@element-plus/icons-vue'
import { getCrawlers, enableCrawler, disableCrawler } from '@/api'
import EmptyState from '@/components/EmptyState.vue'

const router = useRouter()

const ONBOARDING_DONE_KEY = 'mdcx_onboarding_done'
const MOVIE_DIR_KEY = 'mdcx_movie_directory'
const SERVER_URL_KEY = 'serverUrl'

const activeStep = ref(0)

const form = reactive({
  movieDirectory: localStorage.getItem(MOVIE_DIR_KEY) || '',
  serverUrl: localStorage.getItem(SERVER_URL_KEY) || '',
})

// 爬虫列表
const crawlerList = ref([])
const crawlersLoading = ref(false)
const pickingDir = ref(false)

const enabledCrawlerCount = computed(
  () => crawlerList.value.filter(c => c._enabled).length
)
const enabledCrawlerList = computed(
  () => crawlerList.value.filter(c => c._enabled).map(c => c.name)
)

// 步骤是否可前进
const canNext = computed(() => {
  if (activeStep.value === 2) {
    return enabledCrawlerCount.value > 0
  }
  return true
})

const loadCrawlers = async () => {
  crawlersLoading.value = true
  try {
    const res = await getCrawlers()
    const list = Array.isArray(res) ? res : (res?.items || [])
    crawlerList.value = list.map(c => ({
      name: c.name || c,
      enabled: !!c.enabled,
      _enabled: !!c.enabled,
    }))
  } catch (e) {
    // 静默失败，EmptyState 会给出提示
    crawlerList.value = []
  } finally {
    crawlersLoading.value = false
  }
}

const pickDirectory = async () => {
  pickingDir.value = true
  try {
    if (window.electronAPI && window.electronAPI.selectDirectory) {
      const dir = await window.electronAPI.selectDirectory()
      if (dir) form.movieDirectory = dir
    } else {
      ElMessage.info('当前环境不支持目录选择，请手动输入路径')
    }
  } finally {
    pickingDir.value = false
  }
}

const nextStep = () => {
  // 进入步骤 3 前加载爬虫列表
  if (activeStep.value === 1 && !crawlerList.value.length) {
    loadCrawlers()
  }
  // 步骤 2 校验路径
  if (activeStep.value === 1 && !form.movieDirectory) {
    ElMessage.warning('请填写影片库目录')
    return
  }
  if (activeStep.value < 3) {
    activeStep.value += 1
  }
}

const prevStep = () => {
  if (activeStep.value > 0) {
    activeStep.value -= 1
  }
}

const finish = async () => {
  // 持久化配置
  if (form.movieDirectory) {
    localStorage.setItem(MOVIE_DIR_KEY, form.movieDirectory)
  }
  if (form.serverUrl) {
    localStorage.setItem(SERVER_URL_KEY, form.serverUrl.replace(/\/$/, ''))
  }
  localStorage.setItem(ONBOARDING_DONE_KEY, '1')

  // 应用爬虫启用状态变更
  try {
    for (const c of crawlerList.value) {
      if (c._enabled && !c.enabled) {
        await enableCrawler(c.name)
      } else if (!c._enabled && c.enabled) {
        await disableCrawler(c.name)
      }
    }
  } catch (e) {
    // 静默：单个爬虫切换失败不应阻塞向导完成
  }

  ElMessage.success('配置已保存')
  router.push('/')
}

onMounted(() => {
  loadCrawlers()
})
</script>

<style scoped>
.onboarding-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 80px);
  padding: 20px;
}

.onboarding-card {
  width: 100%;
  max-width: 680px;
  border-radius: 12px;
}

.onboarding-steps {
  margin-bottom: 32px;
}

.step-content {
  min-height: 280px;
  padding: 8px 4px;
}

.step-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.step-panel h2 {
  margin: 12px 0 4px;
  font-size: 22px;
  color: var(--text-primary, #303133);
}

.step-panel h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary, #303133);
}

.step-panel p {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary, #606266);
  line-height: 1.6;
}

.step-hint {
  color: var(--text-secondary, #909399);
}

/* 欢迎页 */
.welcome-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
  padding: 20px 0;
}

.welcome-features {
  list-style: none;
  padding: 0;
  margin: 16px 0 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.welcome-features li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary, #606266);
}

.welcome-features .el-icon {
  color: var(--el-color-success, #67c23a);
}

/* 路径表单 */
.path-form {
  max-width: 520px;
}

.form-tip {
  font-size: 12px;
  color: var(--text-placeholder, #c0c4cc);
  margin-top: 4px;
}

/* 爬虫列表 */
.crawler-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.crawler-count {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}

.crawler-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
  max-height: 260px;
  overflow-y: auto;
  padding: 4px;
}

.crawler-item {
  margin: 0 !important;
  width: 100%;
}

.crawler-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.crawler-name {
  font-weight: 500;
}

/* 完成页 */
.complete-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
  padding: 16px 0;
}

.summary {
  width: 100%;
  max-width: 520px;
  margin-top: 16px;
  text-align: left;
}

/* 导航按钮 */
.step-actions {
  display: flex;
  justify-content: space-between;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light, #ebeef5);
}

.step-actions .el-button:last-child {
  margin-left: auto;
}
</style>
