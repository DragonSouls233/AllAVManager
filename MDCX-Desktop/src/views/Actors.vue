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
        <el-button type="warning" @click="openProfileDialog">
          <el-icon><Refresh /></el-icon>
          资料刮削
        </el-button>
        <el-button type="info" plain @click="syncActors" :loading="syncing">
          <el-icon><RefreshLeft /></el-icon>
          同步演员
        </el-button>
        <el-button type="danger" plain @click="openMergeDialog">
          <el-icon><Switch /></el-icon>
          JavDB 自动合并
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
          <!-- 合并标记：显示该演员合并进来的旧名 -->
          <el-tooltip
            v-if="mergedOf(actor).length"
            :content="'已合并：' + mergedOf(actor).join('、')"
            placement="top"
          >
            <el-tag size="small" type="warning" effect="plain">已合并 {{ mergedOf(actor).length }} 名</el-tag>
          </el-tooltip>
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
    <!-- 资料刮削对话框 -->
    <el-dialog v-model="profileVisible" title="演员资料补充刮削" width="560px">
      <el-alert type="info" :closable="false" show-icon class="avatar-tip">
        <template #title>
          从 AV联盟 → DMM → JavWiki → 维基百科等源补充演员资料（生日/身高/三围/罩杯/出道/社交等），仅补空缺字段，自动跳过资料已完整的演员
        </template>
      </el-alert>
      <el-form label-width="100px" class="avatar-form">
        <el-form-item label="最少作品数">
          <el-input-number v-model="profileMinMovies" :min="1" :max="100" />
          <span class="muted" style="margin-left:8px">仅刮削达到该作品数的演员</span>
        </el-form-item>
        <el-form-item label="刮削数量">
          <el-input-number v-model="profileLimit" :min="1" :max="500" />
          <span class="muted" style="margin-left:8px">最多刮削人数（优先资料缺失的演员）</span>
        </el-form-item>
        <el-form-item label="同时补头像">
          <el-switch v-model="profileIncludeAvatar" />
          <span class="muted" style="margin-left:8px">资料源有头像时一并补充（缺头像的演员）</span>
        </el-form-item>
      </el-form>
      <div class="avatar-actions">
        <el-button type="primary" @click="startProfileScrape" :loading="profileScraping">
          <el-icon><Refresh /></el-icon> 开始刮削
        </el-button>
      </div>
    </el-dialog>
    <!-- JavDB 改名自动合并对话框 -->
    <el-dialog v-model="mergeVisible" title="JavDB 改名演员自动合并" width="760px">
      <el-alert type="info" :closable="false" show-icon class="avatar-tip">
        <template #title>
          读取 JavDB 演员库（含全部历史艺名），匹配本地演员表中的同名演员。建议先执行「同步演员」补齐改名后的新艺名，再扫描合并。
        </template>
      </el-alert>
      <div class="avatar-actions" style="margin: 12px 0">
        <el-button type="primary" @click="scanJavdbMergeCandidates" :loading="mergeScanning">
          <el-icon><Search /></el-icon> 扫描合并候选
        </el-button>
        <el-button type="success" @click="applySelectedMerges" :loading="mergeApplying" :disabled="!mergeSelected.length">
          <el-icon><Switch /></el-icon> 合并选中（{{ mergeSelected.length }} 组）
        </el-button>
        <span class="muted" style="margin-left: auto">共 {{ mergeCandidates.length }} 组候选</span>
      </div>
      <el-table
        :data="mergeCandidates"
        v-loading="mergeScanning"
        max-height="440"
        size="small"
        @selection-change="onMergeSelectionChange"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column label="JavDB 全部艺名" min-width="200">
          <template #default="{ row }">
            <el-tag size="small" type="info" style="margin-right:4px">{{ row.javdb_names[0] }}</el-tag>
            <span class="muted" style="font-size:12px">{{ row.javdb_names.slice(1).join(' / ') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="保留（主名）" min-width="120">
          <template #default="{ row }">
            <b>{{ row.canonical.name }}</b>
            <div class="muted" style="font-size:12px">{{ row.canonical.movie_count }} 部</div>
          </template>
        </el-table-column>
        <el-table-column label="并入" min-width="160">
          <template #default="{ row }">
            <el-tag size="small" type="warning" style="margin:2px 4px 2px 0"
              v-for="s in row.sources" :key="s.id">
              {{ s.name }}（{{ s.movie_count }}）
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, MagicStick, Refresh, RefreshLeft, View, VideoPlay, Switch } from '@element-plus/icons-vue'
import { getActors, previewAvatarScrape, scrapeActorProfiles, syncModuleActors, scanJavdbMerge, applyJavdbMerge } from '@/api'
import { useAvatarScrapeStore } from '@/stores/avatarScrape'
import { defaultAvatar, getActorAvatarUrl, getFileProxyUrl } from '@/utils/media'

// 合并来源：后端 merged_from 优先，旧版只有 alias 时本地解析（剔除主名自身）
function mergedOf(actor) {
  if (!actor) return []
  if (Array.isArray(actor.merged_from)) return actor.merged_from
  if (!actor.alias) return []
  const self = String(actor.name || '').trim().toLowerCase()
  return String(actor.alias)
    .split(/[,，、;；|/／]+/)
    .map(s => s.trim())
    .filter(s => s && s.toLowerCase() !== self)
}

const router = useRouter()
const route = useRoute()
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

// 路由模块检测：演员列表端点(_build_actor_response)不返回 module_type，
// 必须从路由推断模块，才能拼出正确的模块隔离头像端点(与后端 avatars/{module}/ 对齐)
const MODULE_MAP = {
  'jav': 'jav', 'fc2': 'fc2', 'uncensored': 'uncensored',
  'western': 'western', 'pornhub': 'pornhub', 'chinese': 'chinese'
}
const moduleType = computed(() => MODULE_MAP[route.path.split('/')[1]] || 'jav')

// 演员头像获取：有 avatar_url 直接加载/代理，无则走模块隔离端点
function getActorAvatar(actor) {
  if (actor?.avatar_url) {
    if (/^https?:\/\//i.test(actor.avatar_url)) return actor.avatar_url
    return getFileProxyUrl(actor.avatar_url)
  }
  return getActorAvatarUrl(actor, moduleType.value)
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
    // 解码 HTML 实体（修复数据中含 < > & 等特殊字符导致渲染异常）
    const items = (res.items || []).map(a => ({
      ...a,
      name: new DOMParser().parseFromString(a.name || '', 'text/html').body.textContent || a.name,
      name_jp: a.name_jp ? new DOMParser().parseFromString(a.name_jp, 'text/html').body.textContent || a.name_jp : a.name_jp
    }))
    actors.value = items
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

// ===== 资料刮削（批量补充演员信息）=====
const profileVisible = ref(false)
const profileMinMovies = ref(2)
const profileLimit = ref(100)
const profileIncludeAvatar = ref(false)
const profileScraping = ref(false)

function openProfileDialog() {
  profileVisible.value = true
}

// ===== 同步演员（从影片 actor 字段反查补齐演员表）=====
const syncing = ref(false)
async function syncActors() {
  try {
    await ElMessageBox.confirm(
      `从「${moduleType.value}」模块所有影片的 actor 字段提取演员名，补齐缺失的演员记录（含改名后的新艺名）。继续吗？`,
      '同步演员',
      { confirmButtonText: '开始同步', cancelButtonText: '取消', type: 'info' }
    )
  } catch (e) {
    return
  }
  syncing.value = true
  try {
    const res = await syncModuleActors(moduleType.value)
    ElMessage.success(`同步完成：发现 ${res.actors_found} 人，新增 ${res.actors_added}，更新计数 ${res.actors_updated}`)
    loadActors()
  } catch (e) {
    ElMessage.error('同步演员失败: ' + (e.message || '未知错误'))
  } finally {
    syncing.value = false
  }
}

async function startProfileScrape() {
  try {
    await ElMessageBox.confirm(
      `确认对「${moduleType.value}」模块 ≥ ${profileMinMovies.value} 部作品的前 ${profileLimit.value} 名资料缺失演员启动资料刮削吗？` +
      (profileIncludeAvatar.value ? '（将同时补充缺失的头像）' : ''),
      '资料刮削',
      { confirmButtonText: '开始刮削', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) {
    return // 用户取消
  }
  profileScraping.value = true
  try {
    const res = await scrapeActorProfiles({
      module: moduleType.value,
      min_movies: profileMinMovies.value,
      limit: profileLimit.value,
      include_avatar: profileIncludeAvatar.value
    })
    profileVisible.value = false
    ElMessage.success(res.message || `资料刮削已启动（共 ${res.total} 人，后台执行中）`)
    setTimeout(() => loadActors(), 5000)
  } catch (e) {
    ElMessage.error('资料刮削启动失败: ' + (e.message || '未知错误'))
  } finally {
    profileScraping.value = false
  }
}

// ===== JavDB 改名演员自动合并 =====
const mergeVisible = ref(false)
const mergeScanning = ref(false)
const mergeApplying = ref(false)
const mergeCandidates = ref([])
const mergeSelected = ref([])

function openMergeDialog() {
  mergeVisible.value = true
}

async function scanJavdbMergeCandidates() {
  mergeScanning.value = true
  try {
    const res = await scanJavdbMerge({ module: moduleType.value, max_pages: 30 })
    mergeCandidates.value = res.candidates || []
    ElMessage.success(`扫描完成：本地 ${res.scanned} 位演员，发现 ${res.total} 组改名合并候选`)
    if (!mergeCandidates.value.length) {
      ElMessage.info('未发现改名合并候选。若本库刚导入改名演员，请先执行「同步演员」补齐新艺名。')
    }
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.message || '未知错误'))
  } finally {
    mergeScanning.value = false
  }
}

function onMergeSelectionChange(rows) {
  mergeSelected.value = rows
}

async function applySelectedMerges() {
  const selections = mergeSelected.value.map(r => ({
    canonical_id: r.canonical.id,
    source_ids: r.sources.map(s => s.id)
  }))
  try {
    await ElMessageBox.confirm(
      `确认合并选中的 ${selections.length} 组演员吗？\n被合并演员的作品将归入保留演员名下，其姓名自动成为别名。此操作不可撤销。`,
      'JavDB 自动合并',
      { confirmButtonText: '确认合并', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) {
    return
  }
  mergeApplying.value = true
  try {
    const res = await applyJavdbMerge({ module: moduleType.value, selections })
    ElMessage.success(`已合并 ${res.applied} 组演员`)
    // 刷新已合并的候选（被合并的 source 已删除，canonical 计数已更新）
    const mergedIds = new Set()
    res.results?.forEach(r => {
      mergedIds.add(r.canonical_id)
      ;(r.merged_names || []).forEach(n => { /* 无 id，留给重新扫描 */ })
    })
    mergeCandidates.value = mergeCandidates.value.filter(c => !mergedIds.has(c.canonical.id))
    loadActors()
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || '未知错误'))
  } finally {
    mergeApplying.value = false
  }
}

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
