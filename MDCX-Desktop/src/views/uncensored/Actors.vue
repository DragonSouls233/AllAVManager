<template>
  <div class="module-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索无码演员..." clearable style="width: 300px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="page = 1; loadActors()">搜索</el-button>
      <!-- 🔴 2026-10-20：补头像入口（与 JAV 有码演员库同款，走同一套后端刮削链）。
           头像按模块隔离：无码演员落到 DATA/avatars/uncensored/actor_{id}.jpg，
           与有码的 DATA/avatars/jav/actor_{id}.jpg 分目录，编号不会互相覆盖。 -->
      <el-button type="success" plain @click="openAvatarDialog">
        <el-icon><Picture /></el-icon> 补头像
      </el-button>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div v-for="actor in actors" :key="actor.id" class="actor-card" @click="goActorDetail(actor.id)">
        <div class="actor-avatar">
          <img :src="getAvatarSrc(actor)" alt="" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-movies">{{ actor.movie_count }} 部作品</div>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无无码演员，请先扫描影片" />
    </div>

    <!-- 🔴 2026-10-13：补分页（对齐 JAV 有码/国产）-->
    <div class="actors-pagination" v-if="store.actorTotal > 0">
      <el-pagination v-model:current-page="store.actorPage" v-model:page-size="store.actorPageSize"
        :total="store.actorTotal" :page-sizes="[24, 48, 96, 192, 480]"
        layout="total, sizes, prev, pager, next"
        @size-change="onActorPageSizeChange" @current-change="onActorPageChange" />
    </div>

    <!-- 头像刮削对话框（本地库 → AV联盟 → JavDB → JavBus，与 JAV 有码同一套） -->
    <el-dialog v-model="avatarVisible" title="无码演员头像补充刮削" width="640px">
      <el-alert type="info" :closable="false" show-icon class="tip">
        <template #title>
          只处理无头像的无码演员，依次从 本地资料库 → AV联盟 → JavDB → JavBus 抓取头像{{ avatarStore.library.available ? '（已检测到本地头像资料库，可优先离线匹配）' : '' }}
        </template>
      </el-alert>

      <el-form label-width="100px" class="dialog-form">
        <el-form-item label="最少作品数">
          <el-input-number v-model="avatarMinMovies" :min="1" :max="50" />
          <span class="muted" style="margin-left:8px">仅刮削达到该作品数的演员</span>
        </el-form-item>
        <el-form-item label="本地资料库" v-if="avatarStore.library.available">
          <el-switch v-model="avatarStore.useLocalLibrary" />
          <span class="muted" style="margin-left:8px">
            优先从本地资料库匹配（{{ libPathText }}，共 {{ avatarStore.library.count ?? '?' }} 张）
          </span>
        </el-form-item>
      </el-form>

      <div class="actions">
        <el-button @click="runAvatarPreview" :loading="avatarPreviewing">
          <el-icon><View /></el-icon> 预览待处理
        </el-button>
        <el-button type="primary" @click="startAvatarScrape" :loading="avatarStarting" :disabled="avatarStore.active">
          <el-icon><VideoPlay /></el-icon> 开始刮削
        </el-button>
        <el-button v-if="avatarStore.active" type="danger" @click="avatarStore.cancel()">
          取消任务
        </el-button>
      </div>

      <!-- 预览列表 -->
      <template v-if="avatarPreviewList.length">
        <el-divider>待处理演员（前 20 个，共 {{ avatarPreviewTotal }} 个）</el-divider>
        <div class="preview-list">
          <span v-for="a in avatarPreviewList" :key="a.id" class="preview-chip">
            {{ a.name }}<small v-if="a.movie_count">（{{ a.movie_count }}）</small>
          </span>
        </div>
      </template>

      <!-- 任务进度（同时全局浮层也会显示） -->
      <template v-if="avatarStore.active || avatarStore.status.status">
        <el-divider>任务进度</el-divider>
        <div class="job-status">
          <el-tag :type="avatarJobTagType">{{ avatarStore.status.status || '空闲' }}</el-tag>
          <span class="muted job-msg">{{ avatarStore.statusText }}</span>
        </div>
        <el-progress
          v-if="avatarStore.progressPercent > 0"
          :percentage="avatarStore.progressPercent"
          :status="avatarStore.isFinished ? 'success' : undefined"
          class="job-progress"
        />
        <el-descriptions :column="3" border size="small" class="job-desc" v-if="avatarHasJobDetail">
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
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUncensoredStore } from '@/stores/uncensored'
import { useAvatarScrapeStore } from '@/stores/avatarScrape'
import { previewAvatarScrape } from '@/api'
import defaultAvatar from '@/assets/default-avatar.png'
import { getAvatarSrc } from '@/utils/media'

// 🔴 2026-10-13：补每页条数选择器。换条数必须回第 1 页，
// 否则可能停在一个不存在的页码上（如原本在第 5 页，改成 24 条/页后共 2 页）。

const router = useRouter()
const store = useUncensoredStore()
const keyword = ref('')
const loading = ref(false)
const actors = ref([])

async function loadActors() {
  loading.value = true
  try {
    actors.value = await store.loadActors()
  } catch (e) {
    console.error('无码演员加载失败:', e)
    actors.value = []
  } finally {
    loading.value = false
  }
}

function onActorPageChange() {
  loadActors()
}
function onActorPageSizeChange() {
  store.actorPage = 1
  loadActors()
}

function scrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goActorDetail(id) {
  router.push(`/uncensored/actors/${id}`)
}

function handleAvatarError(e) {
  e.target.src = defaultAvatar
}

// ===== 头像补充刮削（🔴 2026-10-20：与 JAV 有码同一套链路，module=uncensored）=====
// 头像文件按模块隔离：DATA/avatars/uncensored/actor_{id}.jpg，
// 与有码的 DATA/avatars/jav/actor_{id}.jpg 分目录存放，编号不会互相覆盖。
const avatarVisible = ref(false)
const avatarMinMovies = ref(2)
const avatarPreviewing = ref(false)
const avatarStarting = ref(false)
const avatarPreviewList = ref([])
const avatarPreviewTotal = ref(0)
const avatarStore = useAvatarScrapeStore()

const libPathText = computed(() => {
  const p = avatarStore.library?.path
  if (!p) return ''
  const parts = String(p).split(/[\\/]/)
  return parts.slice(-3).join('/')
})

const avatarHasJobDetail = computed(() =>
  avatarStore.status && (avatarStore.status.total !== undefined || avatarStore.status.completed !== undefined)
)
const avatarJobTagType = computed(() => {
  const s = avatarStore.status?.status
  if (s === 'completed') return 'success'
  if (s === 'failed' || s === 'cancelled') return 'danger'
  if (s === 'running' || s === 'pending') return 'warning'
  return 'info'
})

function openAvatarDialog() {
  avatarVisible.value = true
  avatarStore.initLibrary()
}

async function runAvatarPreview() {
  avatarPreviewing.value = true
  avatarPreviewList.value = []
  try {
    const res = await previewAvatarScrape({
      minMovies: avatarMinMovies.value,
      useLocalLibrary: avatarStore.useLocalLibrary,
      module: 'uncensored'
    })
    const list = res.actors || res.items || []
    avatarPreviewList.value = list
    avatarPreviewTotal.value = res.total || list.length
  } catch (e) {
    // 拦截器已提示
  } finally {
    avatarPreviewing.value = false
  }
}

async function startAvatarScrape() {
  avatarStarting.value = true
  try {
    const ok = await avatarStore.start({
      minMovies: avatarMinMovies.value,
      useLocalLibrary: avatarStore.useLocalLibrary,
      module: 'uncensored'
    })
    if (ok) avatarVisible.value = false
  } catch (e) {
    // 拦截器已提示
  } finally {
    avatarStarting.value = false
  }
}

// 刮削完成后刷新演员列表，让新头像立刻显示
watch(() => avatarStore.isFinished, (done) => {
  if (done) loadActors()
})

onMounted(loadActors)
</script>

<style scoped>
.actors-pagination { margin-top: 20px; display: flex; justify-content: center; }
.module-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; }
.actor-movies { font-size: 12px; color: #999; }
.tip { margin-bottom: 16px; }
.dialog-form { margin-bottom: 12px; }
.muted { color: #999; font-size: 12px; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
.preview-list { display: flex; flex-wrap: wrap; gap: 6px; max-height: 160px; overflow-y: auto; }
.preview-chip { padding: 2px 8px; background: #f0f2f5; border-radius: 4px; font-size: 12px; }
.preview-chip small { color: #999; }
.job-status { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.job-progress { margin-bottom: 12px; }
</style>
