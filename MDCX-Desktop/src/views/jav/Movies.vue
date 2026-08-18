<template>
  <div class="module-movies">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索标题/番号..." clearable style="width: 280px" @keyup.enter="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="sortBy" placeholder="排序" style="width: 160px" @change="onSortChange">
        <el-option label="默认（最新）" value="" />
        <el-option label="番号 ↑ (ABC-001→999)" value="code" />
        <el-option label="番号 ↓ (ABC-999→001)" value="-code" />
        <el-option label="发行日期 ↓" value="-release_date" />
        <el-option label="发行日期 ↑" value="release_date" />
        <el-option label="评分 ↓" value="-rating" />
        <el-option label="时长 ↓" value="-duration" />
      </el-select>
      <el-select v-model="store.statusFilter" placeholder="刮削状态" style="width: 130px" @change="onFilterChange">
        <el-option label="全部" value="" />
        <el-option label="待刮削" value="pending" />
        <el-option label="已刮削" value="scraped" />
      </el-select>
      <el-select v-model="store.pageSize" style="width: 80px" @change="onPageSizeChange">
        <el-option :value="12" label="12" />
        <el-option :value="24" label="24" />
        <el-option :value="48" label="48" />
        <el-option :value="96" label="96" />
        <el-option :value="192" label="192" />
        <el-option :value="240" label="240" />
        <el-option :value="288" label="288" />
      </el-select>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="success" @click="startScan" :loading="scanning">
        <el-icon><FolderOpened /></el-icon> 扫描目录
      </el-button>
      <el-button type="warning" @click="startScrapeAll" :loading="store.scraping" :disabled="store.pendingCount === 0">
        <el-icon><Monitor /></el-icon> 批量刮削
        <el-tag v-if="store.pendingCount" size="small" type="danger" style="margin-left:4px">{{ store.pendingCount }}</el-tag>
      </el-button>
      <el-button type="danger" plain @click="startRefill" :loading="store.scraping">
        <el-icon><Refresh /></el-icon> 批量补图
      </el-button>
      <el-button type="danger" @click="openForceScrape">
        <el-icon><MagicStick /></el-icon> 特殊刮削
      </el-button>
      <el-button type="info" @click="startImportNfo" :loading="store.scraping">
        <el-icon><Document /></el-icon> 导入 NFO
      </el-button>
      <el-tag v-if="store.total">{{ store.total }} 部</el-tag>
      <!-- 详情页跳转筛选状态（系列/片商/类别/番号前缀） -->
      <el-tag v-if="route.query.series" type="success" closable @close="clearRouteFilter('series')">系列：{{ route.query.series }}</el-tag>
      <el-tag v-if="route.query.maker" type="warning" closable @close="clearRouteFilter('maker')">片商：{{ route.query.maker }}</el-tag>
      <el-tag v-if="route.query.genre" type="danger" closable @close="clearRouteFilter('genre')">类别：{{ route.query.genre }}</el-tag>
      <el-tag v-if="route.query.code_prefix" type="info" closable @close="clearRouteFilter('code_prefix')">番号：{{ route.query.code_prefix }}</el-tag>
    </div>

    <!-- 信息筛选 TAB：中文 / 无码 / 信息全 / 信息不全 -->
    <div class="info-tabs">
      <el-radio-group v-model="infoTab" @change="onInfoTabChange">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="chinese">中文</el-radio-button>
        <el-radio-button value="uncensored">无码</el-radio-button>
        <el-radio-button value="complete">信息全</el-radio-button>
        <el-radio-button value="incomplete">信息不全</el-radio-button>
      </el-radio-group>
    </div>

    <div class="movies-grid" v-loading="store.loading">
      <div v-for="m in store.movies" :key="m.id" class="movie-card" @click="goDetail(m.id)">
        <div class="cover">
          <img :src="getCoverSrc(m)" :alt="m.title" @error="onCoverError">
          <div class="cover-badge">{{ m.source_platform || 'JAV' }}</div>
          <div class="cover-badges">
            <el-tag v-for="b in getMovieVersionBadges(m)" :key="b.text" size="small" :type="versionBadgeType(b.type)" effect="dark">{{ b.text }}</el-tag>
          </div>
          <div class="cover-status">
            <el-tag v-if="m.status === 'scraped'" size="small" type="success">已刮削</el-tag>
            <el-tag v-else size="small" type="warning">待刮削</el-tag>
          </div>
        </div>
        <div class="info">
          <div class="title" :title="m.title">{{ m.title || m.code }}</div>
          <div class="meta">
            <span class="code">{{ m.code }}</span>
            <span v-if="m.studio" class="studio">{{ m.studio }}</span>
          </div>
          <div class="tags">
            <el-tag v-if="m.series" size="small" type="info">{{ m.series }}</el-tag>
            <el-tag v-if="m.release_date" size="small">{{ String(m.release_date).slice(0, 10) }}</el-tag>
          </div>
          <div class="actors" v-if="m.actor">
            <el-tag v-for="a in m.actor.split(',').slice(0, 4)" :key="a" size="small" type="success" class="actor-tag">{{ actorName(a) }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!store.loading && !store.movies.length" description="暂无JAV影片" />
    </div>

    <div class="pagination" v-if="store.total > 0">
      <el-pagination
        v-model:current-page="store.page"
        v-model:page-size="store.pageSize"
        :page-sizes="[12, 24, 48, 96, 192, 240, 288]"
        :total="store.total"
        layout="total, sizes, prev, pager, next"
        @current-change="loadMovies"
        @size-change="onPageSizeChange"
      />
    </div>

    <!-- 特殊刮削：按番号 + 指定 JAVDB/JAVBUS 链接强制重刮 -->
    <el-dialog v-model="forceScrapeVisible" title="特殊刮削（指定链接修复）" width="560px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="用于修复同番号自动刮削匹配到错误信息的情况。将先清理该影片文件夹下的旧 NFO/图片，再按指定链接重新刮削。"
        style="margin-bottom: 16px"
      />
      <el-form label-width="90px">
        <el-form-item label="番号" required>
          <el-input v-model="forceScrapeForm.code" placeholder="如 ABC-123" style="width: 260px" />
        </el-form-item>
        <el-form-item label="站点">
          <el-radio-group v-model="forceScrapeForm.site">
            <el-radio value="javdb">JAVDB</el-radio>
            <el-radio value="javbus">JAVBUS</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="详情链接">
          <el-input
            v-model="forceScrapeForm.url"
            type="textarea"
            :rows="2"
            placeholder="粘贴该番号的 JAVDB/JAVBUS 详情页链接（推荐，可精确定位）。留空则按番号+站点搜索刮削。"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="forceScrapeVisible = false">取消</el-button>
        <el-button type="primary" :loading="forceScrapeLoading" @click="submitForceScrape">
          清理并重新刮削
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useJavStore } from '@/stores/jav'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getCoverSrc, getMovieVersionBadges, versionBadgeType } from '@/utils/media'
import { forceScrapeJavMovie } from '@/api/jav'

const router = useRouter()
const route = useRoute()
const store = useJavStore()
const keyword = ref('')
const scanning = ref(false)
const sortBy = ref('')

// 2026-08-08: 详情页跳转筛选（系列/片商/类别/番号前缀）
function routeFilterParams() {
  const q = route.query
  const p = {}
  if (q.series) p.series = String(q.series)
  if (q.maker) p.maker = String(q.maker)
  if (q.genre) p.genre = String(q.genre)
  if (q.code_prefix) p.code_prefix = String(q.code_prefix)
  return p
}

function clearRouteFilter(key) {
  const q = { ...route.query }
  delete q[key]
  router.replace({ path: route.path, query: q })
}

function search() {
  store.page = 1
  loadMovies()
}

function onFilterChange() {
  store.page = 1
  loadMovies()
}

function onPageSizeChange() {
  store.page = 1
  loadMovies()
}

function onSortChange() {
  store.page = 1
  loadMovies()
}

// 兜底剥离历史脏数据格式 {'name': 'xx'}
function actorName(s) {
  const t = String(s || '').trim()
  const m = t.match(/\{'name':\s*'([^']*)'\}/)
  return m ? m[1] : t
}

function resetFilters() {
  keyword.value = ''
  sortBy.value = ''
  store.statusFilter = ''
  store.page = 1
  router.replace({ path: route.path, query: {} })
  loadMovies()
}

// 信息筛选 TAB：''=全部 / chinese=中文 / uncensored=无码 / complete=信息全 / incomplete=信息不全
const infoTab = ref('')

function onInfoTabChange() {
  store.page = 1
  loadMovies()
}

async function loadMovies() {
  const params = { keyword: keyword.value || undefined, ...routeFilterParams() }
  if (sortBy.value) params.sort = sortBy.value
  if (infoTab.value === 'chinese') params.is_chinese = 1
  else if (infoTab.value === 'uncensored') params.is_uncensored = 1
  else if (infoTab.value === 'complete' || infoTab.value === 'incomplete') params.info_state = infoTab.value
  await store.loadMovies(params)
}

function goDetail(id) {
  router.push(`/jav/movies/${id}`)
}

// 路由 query 变化（详情页点系列/片商/类别跳转）时重新加载
watch(() => route.query, () => { store.page = 1; loadMovies() }, { deep: true })

async function startScan() {
  scanning.value = true
  try {
    await store.triggerScan()
    await loadMovies()
    ElMessage.success('扫描完成')
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.message || '未知错误'))
  } finally {
    scanning.value = false
  }
}

async function startScrapeAll() {
  if (store.pendingCount === 0) {
    ElMessage.info('没有待刮削的影片')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认要对 ${store.pendingCount} 部 JAV 影片启动批量刮削吗？`,
      '批量刮削',
      { confirmButtonText: '开始刮削', cancelButtonText: '取消', type: 'warning' }
    )
    const res = await store.triggerScrapeAll()
    ElMessage.success(res.message || '批量刮削已启动')
  } catch (e) {
    if (e !== 'cancel') {
      console.error('[批量刮削启动失败]', e) // 保留完整堆栈，便于定位 DOMException 来源
      ElMessage.error('启动失败: ' + (e.message || '未知错误'))
    }
  }
}

// 批量补图：对「已刮削但缺封面/预览图」的影片完整重刮（后台执行）
async function startRefill() {
  try {
    const { value } = await ElMessageBox.prompt(
      '将自动筛选「已刮削但缺封面/预览图」的影片并完整重刮（后台执行，可重复调用）。请输入本次处理数量：',
      '批量补图',
      {
        inputValue: '50',
        inputValidator: (v) => (/^\d+$/.test(v) && +v >= 1 && +v <= 200) ? true : '请输入 1-200 的整数',
        confirmButtonText: '开始补图',
        cancelButtonText: '取消',
      }
    )
    const res = await store.triggerMediaRefill(Number(value))
    ElMessage.success(res.message || '补图已启动')
  } catch (e) {
    if (e !== 'cancel') {
      console.error('[批量补图启动失败]', e) // 保留完整堆栈，便于定位 DOMException 来源
      ElMessage.error('启动失败: ' + (e.message || '未知错误'))
    }
  }
}

async function startImportNfo() {
  try {
    await ElMessageBox.confirm('确认要导入 NFO 文件吗？', '导入 NFO', { confirmButtonText: '开始导入', cancelButtonText: '取消', type: 'info' })
    const res = await store.triggerImportNfo()
    ElMessage.success(res.message || 'NFO 导入已启动')
  } catch (e) {
    if (e !== 'cancel') {
      console.error('[NFO导入启动失败]', e) // 保留完整堆栈，便于定位 DOMException 来源
      ElMessage.error('启动失败: ' + (e.message || '未知错误'))
    }
  }
}

// ---------- 特殊刮削（指定链接强制重刮） ----------
const forceScrapeVisible = ref(false)
const forceScrapeLoading = ref(false)
const forceScrapeForm = ref({ code: '', site: 'javdb', url: '' })

function openForceScrape() {
  forceScrapeForm.value = { code: '', site: 'javdb', url: '' }
  forceScrapeVisible.value = true
}

async function submitForceScrape() {
  const f = forceScrapeForm.value
  if (!String(f.code || '').trim()) {
    ElMessage.warning('请输入番号')
    return
  }
  forceScrapeLoading.value = true
  try {
    const res = await forceScrapeJavMovie({
      code: String(f.code).trim(),
      site: f.site,
      url: String(f.url || '').trim() || undefined,
    })
    if (res?.status === 'ok') {
      ElMessage.success(res.message || '刮削成功')
      forceScrapeVisible.value = false
      await loadMovies()
    } else {
      ElMessage.error(res?.message || '刮削失败，请检查链接或站点是否可达')
    }
  } catch (e) {
    ElMessage.error('刮削失败: ' + (e?.response?.data?.detail || e?.message))
  } finally {
    forceScrapeLoading.value = false
  }
}

function onCoverError(e) {
  e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 150"><rect fill="%23333" width="100" height="150"/><text x="50" y="80" text-anchor="middle" fill="%23666" font-size="12">无封面</text></svg>'
}

onMounted(() => loadMovies())
</script>

<style scoped>
.info-tabs {
  margin: 12px 0 16px;
}

.movies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}

.movie-card {
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  transition: transform .2s, box-shadow .2s;
}

.movie-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}

.cover {
  aspect-ratio: 2/3;
  position: relative;
  background: #f0f0f0;
  overflow: hidden;
}

.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-badge {
  position: absolute;
  top: 4px;
  left: 4px;
  background: rgba(0,0,0,0.5);
  color: #fff;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
}

.cover-badges {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 3px;
}

.cover-status {
  position: absolute;
  bottom: 4px;
  right: 4px;
}

.info {
  padding: 10px 12px;
}

.title {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.code {
  font-size: 12px;
  font-family: monospace;
  color: #409eff;
  font-weight: 600;
}

.studio {
  font-size: 11px;
  color: #909399;
}

.tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.actors {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}

.actor-tag {
  font-size: 11px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}
</style>
