<template>
  <div class="actors">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索演员..."
        clearable
        style="width: 300px"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
        <el-button type="success" @click="openAvatarDialog">
          <el-icon><MagicStick /></el-icon>
          头像刮削
        </el-button>
      </div>

      <!-- 作品数分类：多作品(默认页) / 素人单作品 / 全部，阈值可配 -->
      <div class="filter-bar">
        <el-radio-group v-model="movieCountFilter" @change="onFilterChange">
          <el-radio-button label="multi">多作品（默认页）</el-radio-button>
          <el-radio-button label="single">素人 / 单作品</el-radio-button>
          <el-radio-button label="all">全部</el-radio-button>
        </el-radio-group>
        <div class="threshold">
          <span class="muted">多作品阈值</span>
          <el-input-number
            v-model="minMoviesForFilter"
            :min="1" :max="20" :step="1"
            size="small" controls-position="right"
            @change="onFilterChange"
          />
          <span class="muted">部（≥此值归“多作品”，其余归“素人”）</span>
        </div>
      </div>

      <div class="actors-grid" v-loading="loading">
      <div
        v-for="actor in actors"
        :key="actor.id"
        class="actor-card"
        @click="goActorDetail(actor.id)"
      >
        <div class="actor-avatar">
          <img :src="getActorAvatar(actor)" :alt="actor.name" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-name-jp" v-if="actor.name_jp">{{ actor.name_jp }}</div>
          <div class="actor-movies" v-if="actor.movie_count">{{ actor.movie_count }} 部作品</div>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无数据" />
    </div>

    <div class="pagination" v-if="total > 0">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :page-sizes="[60, 80, 100, 120]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadActors"
        @size-change="handleSizeChange"
      />
    </div>

    <!-- 头像刮削对话框 -->
    <el-dialog v-model="avatarVisible" title="演员头像智能补充刮削" width="640px">
      <el-alert type="info" :closable="false" show-icon class="avatar-tip">
        <template #title>
          {{ avatarStore.library.available
            ? '已检测到本地头像资料库，可优先离线匹配，无需联网抓取'
            : '只处理作品数 ≥ 阈值且无头像的演员，从 JavBus 等站点抓取头像' }}
        </template>
      </el-alert>

      <el-form label-width="100px" class="avatar-form">
        <el-form-item label="最少作品数">
          <el-input-number v-model="minMovies" :min="1" :max="50" />
          <span class="muted" style="margin-left:8px">仅刮削达到该作品数的演员</span>
        </el-form-item>
        <el-form-item label="本地资料库" v-if="avatarStore.library.available">
          <el-switch v-model="avatarStore.useLocalLibrary" />
          <span class="muted" style="margin-left:8px">
            优先从本地资料库匹配（{{ libPathText }}，共 {{ avatarStore.library.count ?? '?' }} 张）
          </span>
        </el-form-item>
      </el-form>

      <div class="avatar-actions">
        <el-button @click="runPreview" :loading="previewing">
          <el-icon><View /></el-icon> 预览待处理
        </el-button>
        <el-button type="primary" @click="startScrape" :loading="starting" :disabled="avatarStore.active">
          <el-icon><VideoPlay /></el-icon> 开始刮削
        </el-button>
        <el-button v-if="avatarStore.active" type="danger" @click="avatarStore.cancel()">
          取消任务
        </el-button>
      </div>

      <!-- 预览列表 -->
      <template v-if="previewList.length">
        <el-divider>待处理演员（前 20 个，共 {{ previewTotal }} 个）</el-divider>
        <div class="preview-list">
          <span v-for="a in previewList" :key="a.id" class="preview-chip">
            {{ a.name }}<small v-if="a.movie_cnt">（{{ a.movie_cnt }}）</small>
          </span>
        </div>
      </template>

      <!-- 任务进度（同时全局浮层也会显示） -->
      <template v-if="avatarStore.active || avatarStore.status.status">
        <el-divider>任务进度</el-divider>
        <div class="job-status">
          <el-tag :type="jobTagType">{{ avatarStore.status.status || '空闲' }}</el-tag>
          <span class="muted job-msg">{{ avatarStore.statusText }}</span>
        </div>
        <el-progress
          v-if="avatarStore.progressPercent > 0"
          :percentage="avatarStore.progressPercent"
          :status="avatarStore.isFinished ? 'success' : undefined"
          class="job-progress"
        />
        <el-descriptions :column="3" border size="small" class="job-desc" v-if="hasJobDetail">
          <el-descriptions-item label="总数">{{ avatarStore.status.total }}</el-descriptions-item>
          <el-descriptions-item label="已处理">{{ avatarStore.status.completed }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ avatarStore.status.success }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ avatarStore.status.failed }}</el-descriptions-item>
          <el-descriptions-item label="跳过">{{ avatarStore.status.skipped }}</el-descriptions-item>
          <el-descriptions-item label="当前演员">{{ avatarStore.status.current_actor || '—' }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, MagicStick, View, VideoPlay } from '@element-plus/icons-vue'
import { getActors, previewAvatarScrape } from '@/api'
import { useAvatarScrapeStore } from '@/stores/avatarScrape'
import { defaultAvatar, getActorAvatarUrl, getFileProxyUrl } from '@/utils/media'

const router = useRouter()
const avatarStore = useAvatarScrapeStore()
const loading = ref(false)
const actors = ref([])
const keyword = ref('')
const page = ref(1)
const pageSize = ref(60)
const total = ref(0)
// 作品数分类：默认显示多作品(>=阈值)演员，素人/单作品单独一页，阈值可配
const movieCountFilter = ref('multi')
const minMoviesForFilter = ref(2)

// 演员头像获取：有 avatar_url 直接加载/代理，无则走后端 API
function getActorAvatar(actor) {
  if (actor?.avatar_url) {
    if (/^https?:\/\//i.test(actor.avatar_url)) return actor.avatar_url
    return getFileProxyUrl(actor.avatar_url)
  }
  return getActorAvatarUrl(actor)
}

const handleAvatarError = (event) => {
  event.target.src = defaultAvatar(event.target.alt)
}

const loadActors = async () => {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      search: keyword.value || undefined,
      movie_count_filter: movieCountFilter.value,
      min_movies: minMoviesForFilter.value
    }
    const res = await getActors(params)
    actors.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const search = () => {
  page.value = 1
  loadActors()
}

// 分页大小变化：重置到第 1 页并重新加载
const handleSizeChange = (val) => {
  pageSize.value = val
  page.value = 1
  loadActors()
}

// 作品数分类 / 阈值变化：重置到第 1 页并重新加载
const onFilterChange = () => {
  page.value = 1
  loadActors()
}

const goActorDetail = (id) => {
  router.push(`/actors/${id}`)
}

// ===== 头像刮削（使用全局 store，进度浮层 + 全局通知独立于本页面）=====
const avatarVisible = ref(false)
const minMovies = ref(2)
const previewing = ref(false)
const starting = ref(false)
const previewList = ref([])
const previewTotal = ref(0)

const libPathText = computed(() => {
  const p = avatarStore.library?.path
  if (!p) return ''
  const parts = String(p).split(/[\\/]/)
  return parts.slice(-3).join('/')
})

const hasJobDetail = computed(() =>
  avatarStore.status && (avatarStore.status.total !== undefined || avatarStore.status.completed !== undefined)
)
const jobTagType = computed(() => {
  const s = avatarStore.status?.status
  if (s === 'completed') return 'success'
  if (s === 'failed' || s === 'cancelled') return 'danger'
  if (s === 'running' || s === 'pending') return 'warning'
  return 'info'
})

function openAvatarDialog() {
  avatarVisible.value = true
  // 确保资料库状态是最新的
  avatarStore.initLibrary()
}

async function runPreview() {
  previewing.value = true
  previewList.value = []
  try {
    const res = await previewAvatarScrape({
      minMovies: minMovies.value,
      useLocalLibrary: avatarStore.useLocalLibrary
    })
    const list = res.actors || res.items || []
    previewList.value = list
    previewTotal.value = res.total || list.length
  } catch (e) {
    // 拦截器已提示
  } finally {
    previewing.value = false
  }
}

async function startScrape() {
  starting.value = true
  try {
    const ok = await avatarStore.start({
      minMovies: minMovies.value,
      useLocalLibrary: avatarStore.useLocalLibrary
    })
    if (ok) avatarVisible.value = false
  } catch (e) {
    // 拦截器已提示
  } finally {
    starting.value = false
  }
}

// 任务完成后刷新演员列表（头像缓存已在后端失效）
watch(
  () => avatarStore.isFinished,
  (finished) => {
    if (finished) loadActors()
  }
)

onMounted(() => {
  loadActors()
  avatarStore.initLibrary()
})
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.actors-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 20px;
  min-height: 400px;
}

.actor-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.actor-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
}

.actor-avatar {
  width: 100px;
  height: 100px;
  margin: 0 auto 15px;
  border-radius: 50%;
  overflow: hidden;
  background: #eee;
}

.actor-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.actor-name {
  font-weight: bold;
  color: #333;
}

.actor-name-jp {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.actor-movies {
  font-size: 12px;
  color: #409eff;
  margin-top: 8px;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}

.avatar-tip {
  margin-bottom: 16px;
}

.avatar-form {
  margin-top: 4px;
}

.muted {
  color: #909399;
}

.avatar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.preview-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preview-chip {
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 14px;
  padding: 4px 12px;
  font-size: 13px;
  color: #606266;
}

.preview-chip small {
  color: #909399;
  margin-left: 2px;
}

.job-status {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.job-msg {
  font-size: 13px;
}

.job-progress {
  margin-bottom: 12px;
}

.job-desc {
  margin-top: 4px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.threshold {
  display: flex;
  align-items: center;
  gap: 6px;
}

.threshold .muted {
  font-size: 13px;
}
</style>
