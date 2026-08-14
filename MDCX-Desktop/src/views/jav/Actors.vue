<template>
  <div class="module-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索演员..." clearable style="width: 300px"
        @keyup.enter="search" @clear="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-tooltip content="把合并进来的别名作品一起算上，修正列表里过时的作品数" placement="top">
        <el-button :loading="recalcing" @click="recalcCounts">重算作品数</el-button>
      </el-tooltip>
      <el-button type="warning" @click="openProfileDialog">
        <el-icon><Refresh /></el-icon> 资料刮削
      </el-button>
      <el-button type="success" plain @click="openAvatarDialog">
        <el-icon><Picture /></el-icon> 补头像
      </el-button>
      <el-button type="info" plain @click="syncActors" :loading="syncing">
        <el-icon><RefreshLeft /></el-icon> 同步演员
      </el-button>
      <el-button type="danger" plain @click="openMergeDialog">
        <el-icon><Switch /></el-icon> JavDB 自动合并
      </el-button>
    </div>

    <!-- 作品数分类 Tab -->
    <div class="filter-bar">
      <el-radio-group v-model="movieCountFilter" @change="onFilterChange">
        <el-radio-button label="multi">多作品（默认页）</el-radio-button>
        <el-radio-button label="single">素人 / 单作品</el-radio-button>
        <el-radio-button label="all">全部</el-radio-button>
      </el-radio-group>
      <div class="threshold">
        <span class="muted">多作品阈值</span>
        <el-input-number v-model="minMoviesForFilter" :min="1" :max="20" :step="1"
          size="small" controls-position="right" @change="onFilterChange" />
        <span class="muted">部（≥此值归“多作品”，其余归“素人”）</span>
      </div>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div v-for="actor in actors" :key="actor.id" class="actor-card" @click="goActorDetail(actor.id)">
        <div class="actor-avatar">
          <img :src="getAvatarSrc(actor)" :alt="actor.name" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-movies">{{ actor.movie_count }} 部作品</div>
          <!-- 合并标记：显示这个演员合并进来的旧名，鼠标悬停看全部 -->
          <el-tooltip
            v-if="mergedOf(actor).length"
            :content="'已合并：' + mergedOf(actor).join('、')"
            placement="top"
          >
            <el-tag size="small" type="warning" effect="plain" class="merged-tag">
              已合并 {{ mergedOf(actor).length }} 名
            </el-tag>
          </el-tooltip>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无演员，请先扫描影片" />
    </div>

    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" :page-sizes="[60, 120, 240]" layout="total, sizes, prev, pager, next"
        @size-change="handleSizeChange" @current-change="loadActors" />
    </div>

    <!-- 头像刮削对话框（本地库 → AV联盟 → JavDB → JavBus，全局进度浮层） -->
    <el-dialog v-model="avatarVisible" title="演员头像补充刮削" width="640px">
      <el-alert type="info" :closable="false" show-icon class="tip">
        <template #title>
          只处理无头像的演员，依次从 本地资料库 → AV联盟 → JavDB → JavBus 抓取头像{{ avatarStore.library.available ? '（已检测到本地头像资料库，可优先离线匹配）' : '' }}
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
            {{ a.name }}<small v-if="a.movie_cnt">（{{ a.movie_cnt }}）</small>
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

    <!-- 资料刮削对话框 -->
    <el-dialog v-model="profileVisible" title="演员资料补充刮削" width="560px">
      <el-alert type="info" :closable="false" show-icon class="tip">
        <template #title>
          从 AV联盟 → DMM → JavWiki → 维基百科等源补充演员资料（生日/身高/三围/罩杯/出道/社交等），仅补空缺字段，自动跳过资料已完整的演员
        </template>
      </el-alert>
      <el-form label-width="100px" class="dialog-form">
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
      <div class="actions">
        <el-button type="primary" @click="startProfileScrape" :loading="profileScraping">
          <el-icon><Refresh /></el-icon> 开始刮削
        </el-button>
      </div>
    </el-dialog>

    <!-- JavDB 改名演员自动合并对话框 -->
    <el-dialog v-model="mergeVisible" title="JavDB 改名演员自动合并" width="760px">
      <el-alert type="info" :closable="false" show-icon class="tip">
        <template #title>
          读取 JavDB 演员库（含全部历史艺名），匹配本地演员表中的同名演员。建议先执行「同步演员」补齐改名后的新艺名，再扫描合并。
        </template>
      </el-alert>
      <div class="actions" style="margin: 12px 0">
        <el-button type="primary" @click="scanJavdbMergeCandidates" :loading="mergeScanning">
          <el-icon><Search /></el-icon> 扫描合并候选
        </el-button>
        <el-button type="success" @click="applySelectedMerges" :loading="mergeApplying" :disabled="!mergeSelected.length">
          <el-icon><Switch /></el-icon> 合并选中（{{ mergeSelected.length }} 组）
        </el-button>
        <span class="muted" style="margin-left: auto">共 {{ mergeCandidates.length }} 组候选</span>
      </div>
      <el-table :data="mergeCandidates" v-loading="mergeScanning" max-height="440" size="small"
        @selection-change="onMergeSelectionChange">
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
            <el-tag size="small" type="warning" style="margin:2px 4px 2px 0" v-for="s in row.sources" :key="s.id">
              {{ s.name }}（{{ s.movie_count }}）
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, RefreshLeft, Switch, Picture, View, VideoPlay } from '@element-plus/icons-vue'
import defaultAvatar from '@/assets/default-avatar.png'
import { getAvatarSrc } from '@/utils/media'
import { getJavActors } from '@/api/jav'
import { recalcActorMovieCount, scrapeActorProfiles, syncModuleActors, scanJavdbMerge, applyJavdbMerge, previewAvatarScrape } from '@/api'
import { useAvatarScrapeStore } from '@/stores/avatarScrape'

const avatarStore = useAvatarScrapeStore()

const router = useRouter()
const keyword = ref('')
const loading = ref(false)
const actors = ref([])
const page = ref(1)
const pageSize = ref(60)
const total = ref(0)

// 作品数分类
const movieCountFilter = ref('multi')
const minMoviesForFilter = ref(2)

// 合并来源：后端 merged_from 优先，旧版只有 alias 时本地解析（需剔除主名自身）
const recalcing = ref(false)
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

async function recalcCounts() {
  recalcing.value = true
  try {
    const res = await recalcActorMovieCount('jav', true)
    ElMessage.success(`已重算 ${res.scanned || 0} 位合并演员，更新 ${res.updated || 0} 条作品数`)
    await loadActors()
  } catch (e) {
    ElMessage.error('重算失败: ' + (e.message || e))
  } finally {
    recalcing.value = false
  }
}

async function loadActors() {
  loading.value = true
  try {
    const res = await getJavActors({
      search: keyword.value || undefined,
      movie_count_filter: movieCountFilter.value,
      min_movies: minMoviesForFilter.value,
      page: page.value,
      page_size: pageSize.value,
    })
    // API 返回 {items, total}；旧版本可能返回数组，向下兼容
    if (Array.isArray(res)) {
      actors.value = res
      total.value = res.length
    } else {
      actors.value = res.items || []
      total.value = res.total || 0
    }
  } catch (e) {
    ElMessage.error('加载演员列表失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  loadActors()
}

function onFilterChange() {
  page.value = 1
  loadActors()
}

function handleSizeChange(val) {
  pageSize.value = val
  page.value = 1
  loadActors()
}

function goActorDetail(id) {
  router.push(`/jav/actors/${id}`)
}

function handleAvatarError(e) {
  e.target.src = defaultAvatar(e.target.alt || '?')
}

// ===== 头像补充刮削（全局 store，本地库 → AV联盟 → JavDB → JavBus）=====
const avatarVisible = ref(false)
const avatarMinMovies = ref(2)
const avatarPreviewing = ref(false)
const avatarStarting = ref(false)
const avatarPreviewList = ref([])
const avatarPreviewTotal = ref(0)

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
      useLocalLibrary: avatarStore.useLocalLibrary
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
      useLocalLibrary: avatarStore.useLocalLibrary
    })
    if (ok) avatarVisible.value = false
  } catch (e) {
    // 拦截器已提示
  } finally {
    avatarStarting.value = false
  }
}

// ===== 资料刮削（批量补充演员信息）=====
const profileVisible = ref(false)
const profileMinMovies = ref(2)
const profileLimit = ref(100)
const profileIncludeAvatar = ref(false)
const profileScraping = ref(false)

function openProfileDialog() {
  profileVisible.value = true
}

async function startProfileScrape() {
  try {
    await ElMessageBox.confirm(
      `确认对「jav」模块 ≥ ${profileMinMovies.value} 部作品的前 ${profileLimit.value} 名资料缺失演员启动资料刮削吗？` +
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
      module: 'jav',
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

// ===== 同步演员（从影片 actor 字段反查补齐演员表）=====
const syncing = ref(false)
async function syncActors() {
  try {
    await ElMessageBox.confirm(
      '从「jav」模块所有影片的 actor 字段提取演员名，补齐缺失的演员记录（含改名后的新艺名）。继续吗？',
      '同步演员',
      { confirmButtonText: '开始同步', cancelButtonText: '取消', type: 'info' }
    )
  } catch (e) {
    return
  }
  syncing.value = true
  try {
    const res = await syncModuleActors('jav')
    ElMessage.success(`同步完成：发现 ${res.actors_found} 人，新增 ${res.actors_added}，更新计数 ${res.actors_updated}`)
    loadActors()
  } catch (e) {
    ElMessage.error('同步演员失败: ' + (e.message || '未知错误'))
  } finally {
    syncing.value = false
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
    const res = await scanJavdbMerge({ module: 'jav', max_pages: 30 })
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
    const res = await applyJavdbMerge({ module: 'jav', selections })
    ElMessage.success(`已合并 ${res.applied} 组演员`)
    const mergedIds = new Set()
    res.results?.forEach(r => mergedIds.add(r.canonical_id))
    mergeCandidates.value = mergeCandidates.value.filter(c => !mergedIds.has(c.canonical.id))
    loadActors()
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || '未知错误'))
  } finally {
    mergeApplying.value = false
  }
}

onMounted(loadActors)
</script>

<style scoped>
.module-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 12px; align-items: center; flex-wrap: wrap; }
.filter-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.threshold { display: flex; align-items: center; gap: 6px; }
.muted { color: #909399; font-size: 12px; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; }
.actor-movies { font-size: 12px; color: #999; }
.pagination-wrap { margin-top: 20px; display: flex; justify-content: center; }
.tip { margin-bottom: 4px; }
.dialog-form { margin-top: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.preview-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.preview-chip { background: #f4f4f5; border-radius: 4px; padding: 2px 8px; font-size: 12px; color: #606266; }
.job-status { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.job-msg { font-size: 13px; }
.job-progress { margin-top: 10px; }
.job-desc { margin-top: 10px; }
</style>
