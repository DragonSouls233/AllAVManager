<template>
  <div class="gfriends-page">
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-title">
          <el-icon><Setting /></el-icon> 资料库配置
        </div>
      </template>
      <el-form :model="configForm" label-width="160px" style="max-width: 800px">
        <el-form-item label="资料库模式">
          <el-radio-group v-model="configForm.mode">
            <el-radio-button value="online">在线下载 (GitHub)</el-radio-button>
            <el-radio-button value="local">本地资料库</el-radio-button>
          </el-radio-group>
          <span class="form-tip">本地模式读取本地已下载的 Gfriends 副本，无需访问 GitHub</span>
        </el-form-item>
        <el-form-item label="本地资料库路径">
          <el-input
            v-model="configForm.local_library_path"
            placeholder="如 O:\MDCX\GitHub-ZIP\P1-High\gfriends-master\gfriends-master"
            clearable
          >
            <template #append>
              <el-button @click="browseFolder" :loading="browsing">浏览</el-button>
            </template>
          </el-input>
          <span class="form-tip">填写 gfriends-master 根目录（含 Content/ 子目录），或直接填 Content/ 目录</span>
        </el-form-item>
        <el-form-item label="优先使用本地">
          <el-switch v-model="configForm.prefer_local" />
          <span class="form-tip">开启后，「开始批量导入」自动使用本地资料库（无需勾选下方「本地资料库」开关）</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="testLocalLibrary" :loading="testing">测试路径</el-button>
          <span class="form-tip" v-if="libraryStatus">
            资料库状态：<el-tag :type="libraryStatus.available ? 'success' : 'danger'" size="small">
              {{ libraryStatus.available ? `已就绪 (${libraryStatus.count} 张)` : '未找到' }}
            </el-tag>
            <span v-if="libraryStatus.path"> — {{ libraryStatus.path }}</span>
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="preview-card">
      <template #header>
        <div class="card-title">
          <el-icon><Avatar /></el-icon> Gfriends 头像库批量导入
          <el-button type="primary" size="small" style="margin-left: auto" @click="loadPreview" :loading="loadingPreview">
            刷新预览
          </el-button>
        </div>
      </template>

      <el-alert v-if="!preview" type="info" :closable="false" title="点击「刷新预览」查看本地无头像演员的匹配情况" />

      <template v-else>
        <el-row :gutter="16" class="stat-row">
          <el-col :span="6">
            <el-statistic title="无头像演员" :value="preview.total_no_avatar" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="Gfriends 匹配" :value="preview.matched" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="未匹配" :value="preview.unmatched" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="匹配率" :value="preview.match_rate" />
          </el-col>
        </el-row>

        <el-divider />

        <el-table :data="preview.samples" border size="small" style="width: 100%">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="name" label="演员名" min-width="150" />
          <el-table-column prop="name_jp" label="日文名" min-width="150" />
          <el-table-column label="匹配状态" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.matched" type="success" size="small">已匹配</el-tag>
              <el-tag v-else type="info" size="small">未匹配</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div class="form-tip" v-if="preview.total_no_avatar > 20">
          仅显示前 20 条样本，实际共 {{ preview.total_no_avatar }} 个无头像演员
        </div>
      </template>
    </el-card>

    <el-card shadow="never" class="import-card">
      <template #header>
        <div class="card-title">
          <el-icon><Download /></el-icon> 执行批量导入
        </div>
      </template>
      <el-form :model="form" label-width="180px" style="max-width: 600px">
        <el-form-item label="覆盖已有头像">
          <el-switch v-model="form.overwrite" />
          <span class="form-tip">开启后即使演员已有头像也会重新下载覆盖</span>
        </el-form-item>
        <el-form-item label="最低出演影片数">
          <el-input-number v-model="form.min_movies" :min="0" :max="100" :step="1" />
          <span class="form-tip">仅导入出演影片数 ≥ N 的演员（0 = 全部）</span>
        </el-form-item>
        <el-form-item label="本地资料库" v-if="avatarStore.library.available">
          <el-switch v-model="form.use_local" />
          <span class="form-tip">优先从本地离线副本匹配头像（不访问 GitHub）：{{ libPathText }}</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="startImport" :loading="importing" :disabled="!preview">
            开始批量导入
          </el-button>
          <span class="form-tip" v-if="!preview">请先点击上方「刷新预览」</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="jobs-card" v-if="currentJob">
      <template #header>
        <div class="card-title">
          <el-icon v-if="currentJob.status === 'running'"><Loading /></el-icon>
          <el-icon v-else><CircleCheck /></el-icon>
          任务进度
          <el-tag :type="jobStatusType" size="small" style="margin-left: 8px">{{ jobStatusText }}</el-tag>
        </div>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务 ID">{{ currentJob.job_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ jobStatusText }}</el-descriptions-item>
        <el-descriptions-item label="总数">{{ currentJob.progress?.total || 0 }}</el-descriptions-item>
        <el-descriptions-item label="匹配">{{ currentJob.progress?.matched || 0 }}</el-descriptions-item>
        <el-descriptions-item label="已下载">{{ currentJob.progress?.downloaded || 0 }}</el-descriptions-item>
        <el-descriptions-item label="跳过">{{ currentJob.progress?.skipped || 0 }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ currentJob.progress?.failed || 0 }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ formatTime(currentJob.started_at) }}</el-descriptions-item>
      </el-descriptions>

      <el-progress
        v-if="currentJob.status === 'running'"
        :percentage="importProgress"
        :status="'active'"
        style="margin-top: 16px"
      />
    </el-card>

    <el-card shadow="never" class="info-card">
      <template #header>
        <div class="card-title">
          <el-icon><InfoFilled /></el-icon> 关于 Gfriends
        </div>
      </template>
      <el-alert type="info" :closable="false">
        <template #title>
          Gfriends 是 GitHub 上的开源演员头像集合仓库，包含数千张高质量演员头像。
        </template>
        <p style="margin: 8px 0 0">本项目会从 <el-link type="primary" href="https://github.com/gfriends/gfriends" target="_blank">gfriends/gfriends</el-link> 仓库拉取 Filetree.json 索引，匹配本地数据库中的演员名（含日文名），批量下载头像到 data/avatars/ 目录，并自动调用人脸裁剪优化。</p>
        <p style="margin: 8px 0 0">建议配合代理使用（GitHub raw 在国内访问可能不稳定）。</p>
        <p style="margin: 8px 0 0"><strong>本地资料库：</strong>如果已经下载了 Gfriends 仓库的全部头像（如 <code>O:\MDCX\GitHub-ZIP\P1-High\gfriends-master\gfriends-master</code>），可在上方"资料库配置"中填写路径，切换到本地模式，导入时不访问网络，速度极快。</p>
      </el-alert>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Avatar, Download, Loading, CircleCheck, InfoFilled, Setting } from '@element-plus/icons-vue'
import { importGfriends, previewGfriendsMatches, getGfriendsJobStatus, getGfriendsConfig, updateGfriendsConfig, testGfriendsLocalLibrary } from '@/api'
import { useAvatarScrapeStore } from '@/stores/avatarScrape'

const avatarStore = useAvatarScrapeStore()
const loadingPreview = ref(false)
const importing = ref(false)
const saving = ref(false)
const testing = ref(false)
const browsing = ref(false)
const preview = ref(null)
const currentJob = ref(null)
const libraryStatus = ref(null)
let pollTimer = null

const form = reactive({
  overwrite: false,
  min_movies: 0,
  use_local: false,
})

const configForm = reactive({
  enabled: true,
  mode: 'online',
  local_library_path: '',
  prefer_local: true,
  normalize_names: true,
  concurrent_downloads: 5,
  download_timeout: 30,
})

const libPathText = computed(() => {
  const p = avatarStore.library?.path
  if (!p) return ''
  const parts = String(p).split(/[\\/]/)
  return parts.slice(-3).join('/')
})

const jobStatusType = computed(() => {
  if (!currentJob.value) return 'info'
  const s = currentJob.value.status
  if (s === 'running') return 'warning'
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  return 'info'
})

const jobStatusText = computed(() => {
  if (!currentJob.value) return '-'
  const s = currentJob.value.status
  const map = { running: '运行中', completed: '已完成', failed: '失败', started: '已启动' }
  return map[s] || s
})

const importProgress = computed(() => {
  if (!currentJob.value || !currentJob.value.progress) return 0
  const p = currentJob.value.progress
  if (p.total === 0) return 0
  return Math.round(((p.matched + p.skipped) / p.total) * 100)
})

const loadConfig = async () => {
  try {
    const cfg = await getGfriendsConfig()
    Object.assign(configForm, {
      enabled: cfg.enabled,
      mode: cfg.mode,
      local_library_path: cfg.local_library_path || '',
      prefer_local: cfg.prefer_local,
      normalize_names: cfg.normalize_names,
      concurrent_downloads: cfg.concurrent_downloads,
      download_timeout: cfg.download_timeout,
    })
    libraryStatus.value = cfg.library_status
  } catch (e) {
    ElMessage.error('加载配置失败: ' + (e.response?.data?.detail || e.message))
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const res = await updateGfriendsConfig({
      enabled: configForm.enabled,
      mode: configForm.mode,
      local_library_path: configForm.local_library_path,
      prefer_local: configForm.prefer_local,
      normalize_names: configForm.normalize_names,
      concurrent_downloads: configForm.concurrent_downloads,
      download_timeout: configForm.download_timeout,
    })
    ElMessage.success('配置已保存')
    libraryStatus.value = res.library_status || libraryStatus.value
    avatarStore.initLibrary()  // 刷新本地资料库状态
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

const testLocalLibrary = async () => {
  testing.value = true
  try {
    const res = await testGfriendsLocalLibrary()
    libraryStatus.value = res
    if (res.available) {
      ElMessage.success(`本地资料库可访问，共 ${res.count} 张头像`)
    } else {
      ElMessage.error('本地资料库不可访问: ' + (res.error || '请检查路径'))
    }
    avatarStore.initLibrary()
  } catch (e) {
    ElMessage.error('测试失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    testing.value = false
  }
}

const browseFolder = async () => {
  // 浏览器没有原生文件夹选择 API，使用 prompt 让用户手动输入
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入本地资料库根目录的完整路径（如 O:\\MDCX\\GitHub-ZIP\\P1-High\\gfriends-master\\gfriends-master）',
      '选择本地资料库路径',
      {
        inputValue: configForm.local_library_path,
        inputPlaceholder: '文件夹绝对路径',
        inputValidator: (v) => (v && v.trim().length > 0) || '路径不能为空',
        confirmButtonText: '使用此路径',
        cancelButtonText: '取消',
      }
    )
    configForm.local_library_path = value.trim()
  } catch {
    // 用户取消
  }
}

const loadPreview = async () => {
  loadingPreview.value = true
  try {
    preview.value = await previewGfriendsMatches(form.use_local)
  } catch (e) {
    ElMessage.error('加载预览失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loadingPreview.value = false
  }
}

const startImport = async () => {
  importing.value = true
  try {
    const res = await importGfriends({
      overwrite: form.overwrite,
      min_movies: form.min_movies,
      use_local: form.use_local
    })
    ElMessage.success('批量导入任务已启动')
    currentJob.value = { job_id: res.job_id, status: 'running', progress: { total: 0, matched: 0, downloaded: 0, skipped: 0, failed: 0 }, started_at: new Date().toISOString() }
    startPolling(res.job_id)
  } catch (e) {
    ElMessage.error('启动失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    importing.value = false
  }
}

const startPolling = (jobId) => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const status = await getGfriendsJobStatus(jobId)
      currentJob.value = { job_id: jobId, ...status }
      if (status.status === 'completed' || status.status === 'failed') {
        clearInterval(pollTimer)
        pollTimer = null
        if (status.status === 'completed') {
          ElMessage.success('批量导入完成！')
        } else {
          ElMessage.error('批量导入失败: ' + (status.error || ''))
        }
      }
    } catch (e) {
      // 静默
    }
  }, 3000)
}

const formatTime = (iso) => {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}

onMounted(() => {
  avatarStore.initLibrary()
  loadConfig()
  loadPreview()
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.gfriends-page {
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

.stat-row {
  margin-bottom: 16px;
}

.form-tip {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.5;
}

code {
  background: rgba(127, 127, 127, 0.1);
  padding: 2px 6px;
  border-radius: 3px;
  font-family: monospace;
}
</style>
