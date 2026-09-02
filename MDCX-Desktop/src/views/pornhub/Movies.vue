<template>
  <div class="module-movies">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索标题/viewkey..." clearable style="width: 280px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="success" @click="startScan" :loading="scanning">
        <el-icon><FolderOpened /></el-icon> 扫描目录(断点续扫)
      </el-button>
      <el-tooltip content="忽略已处理目录记录，从零全量重扫" placement="top">
        <el-button @click="startRescan" :loading="scanning">
          <el-icon><RefreshRight /></el-icon> 全量重扫
        </el-button>
      </el-tooltip>
      <el-tooltip content="将影片 actor 文本字段与演员表匹配，建立关联" placement="top">
        <el-button type="warning" @click="syncActors" :loading="syncing">
          <el-icon><Link /></el-icon> 同步演员关联
        </el-button>
      </el-tooltip>
      <el-tooltip content="SHA1 内容指纹去重，识别重复文件并可选择删除" placement="top">
        <el-button type="danger" @click="openDedup">
          <el-icon><Delete /></el-icon> 内容去重
        </el-button>
      </el-tooltip>
      <el-tag v-if="store.total">共 {{ store.total }} 部</el-tag>
      <el-tag v-if="route.query.series" type="success" closable @close="clearRouteFilter('series')">系列：{{ route.query.series }}</el-tag>
      <el-tag v-if="route.query.maker" type="warning" closable @close="clearRouteFilter('maker')">片商：{{ route.query.maker }}</el-tag>
      <el-tag v-if="route.query.genre" type="danger" closable @close="clearRouteFilter('genre')">类别：{{ route.query.genre }}</el-tag>
      <el-tag v-if="route.query.code_prefix" type="info" closable @close="clearRouteFilter('code_prefix')">番号：{{ route.query.code_prefix }}</el-tag>
    </div>

    <div class="movies-grid" v-loading="store.loading">
      <div v-for="m in store.movies" :key="m.id" class="movie-card" @click="goDetail(m.id)">
        <div class="cover">
          <img :src="getCoverSrc(m)" :alt="m.title" @error="onCoverError">
          <div class="cover-badge">{{ m.uploader || 'PH' }}</div>
          <div v-if="m.duration" class="duration-badge">{{ formatDuration(m.duration) }}</div>
        </div>
        <div class="info">
          <div class="title">{{ m.title || m.code }}</div>
          <div class="meta">
            <span class="code">{{ m.code }}</span>
            <span v-if="m.source_views" class="views">{{ formatNumber(m.source_views) }} 次播放</span>
            <span v-if="m.rating" class="rating">★ {{ m.rating }}</span>
          </div>
          <div class="categories" v-if="m.categories">
            <el-tag size="mini" v-for="c in parseCategories(m.categories)" :key="c" type="info">{{ c }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!store.loading && !store.movies.length" description="暂无 PORNHub 影片，请先扫描目录" />
    </div>

    <div class="pagination" v-if="store.total > 0">
      <el-pagination
        v-model:current-page="store.page"
        :page-size="store.pageSize"
        :total="store.total"
        layout="total, prev, pager, next"
        @current-change="loadMovies"
      />
    </div>

    <el-dialog v-model="showDedupDialog" title="内容去重 (SHA1 指纹)" width="720px" :close-on-click-modal="false">
      <div v-if="dedupScanning" class="dedup-status">
        <el-progress type="circle" :percentage="dedupProgress" :status="dedupProgress >= 100 ? 'success' : ''" />
        <p>正在扫描 {{ dedupFilesScanned }} 个文件...</p>
      </div>

      <div v-else-if="dedupResult" class="dedup-result">
        <el-row :gutter="16">
          <el-col :span="6">
            <el-statistic title="扫描文件" :value="dedupResult.scanned_files" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="重复组数" :value="dedupResult.duplicate_groups" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="可删除文件" :value="dedupResult.removable_files" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="可节省空间" :value="formatBytes(dedupResult.total_bytes_saved)" />
          </el-col>
        </el-row>

        <div class="dedup-groups" v-if="dedupResult.groups && dedupResult.groups.length">
          <h4>重复组详情（展示前 20 组）</h4>
          <el-collapse>
            <el-collapse-item v-for="(group, idx) in dedupResult.groups.slice(0, 20)" :key="idx" :name="idx">
              <template #title>
                <span>组 {{ idx + 1 }} — {{ group.files.length }} 个文件</span>
              </template>
              <el-table :data="group.files" size="mini" stripe>
                <el-table-column prop="path" label="文件路径" />
                <el-table-column prop="size_str" label="大小" width="100" />
                <el-table-column prop="mtime" label="修改时间" width="150" />
                <el-table-column label="保留" width="60" align="center">
                  <template #default="row">
                    <el-tag :type="row.file.is_kept ? 'success' : 'danger'" size="small">
                      {{ row.file.is_kept ? '保留' : '可删' }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </div>

        <el-empty v-else description="未发现重复文件" />

        <div class="dedup-actions">
          <el-alert type="warning" :closable="false" style="margin-bottom: 12px">
            删除操作不可恢复，将物理删除标记为「可删」的文件
          </el-alert>
          <el-button type="danger" @click="applyDedup" :loading="dedupApplying">
            删除 {{ dedupResult.removable_files }} 个重复文件
          </el-button>
          <el-button @click="closeDedup">关闭</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { usePornhubStore } from '@/stores/pornhub'
import { ElMessage } from 'element-plus'
import defaultCover from '@/assets/default-cover.png'
import { getCoverSrc } from '@/utils/media'
import {
  syncPornhubMovieActors,
  pornhubDedupScan,
  pornhubDedupApply,
  pornhubDedupStatus,
} from '@/api/pornhub'
import { Link, Delete } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const store = usePornhubStore()
const keyword = ref('')
const scanning = ref(false)
const syncing = ref(false)
const showDedupDialog = ref(false)
const dedupScanning = ref(false)
const dedupProgress = ref(0)
const dedupFilesScanned = ref(0)
const dedupResult = ref(null)
const dedupApplying = ref(false)

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

function parseCategories(val) {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [val] }
}

function formatNumber(n) {
  if (!n) return '0'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

function formatBytes(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return n.toFixed(1) + ' ' + units[i]
}

function formatDuration(minutes) {
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h}h${m}m` : `${m}m`
}

function search() {
  store.page = 1
  loadMovies()
}

function resetFilters() {
  keyword.value = ''
  store.page = 1
  router.replace({ path: route.path, query: {} })
  loadMovies()
}

async function loadMovies() {
  await store.loadMovies({ keyword: keyword.value || undefined, ...routeFilterParams() })
}

function goDetail(id) {
  router.push(`/pornhub/movies/${id}`)
}

async function startScan() {
  scanning.value = true
  try {
    const res = await store.triggerResumableScan(false)
    ElMessage.success(res?.message || 'PORNHub 断点续扫已后台启动')
  } catch (e) {
    ElMessage.error('扫描启动失败: ' + (e.message || '未知错误'))
  } finally { scanning.value = false }
}

async function startRescan() {
  scanning.value = true
  try {
    const res = await store.triggerResumableScan(true)
    ElMessage.success(res?.message || 'PORNHub 全量重扫已后台启动')
  } catch (e) {
    ElMessage.error('重扫启动失败: ' + (e.message || '未知错误'))
  } finally { scanning.value = false }
}

async function syncActors() {
  syncing.value = true
  try {
    const res = await syncPornhubMovieActors()
    ElMessage.success(`同步完成: 扫描 ${res?.scanned || 0} 部, 更新 ${res?.updated || 0} 部, 关联 ${res?.linked || 0} 位演员`)
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.message || '未知错误'))
  } finally { syncing.value = false }
}

async function openDedup() {
  showDedupDialog.value = true
  dedupResult.value = null
  dedupProgress.value = 0
  dedupFilesScanned.value = 0

  try {
    const st = await pornhubDedupStatus()
    if (st?.scan_in_progress) {
      ElMessage.info('已有扫描任务在运行')
      dedupScanning.value = true
      return
    }
  } catch {}

  dedupScanning.value = true
  const timer = setInterval(() => {
    dedupProgress.value = Math.min(99, dedupProgress.value + 2)
  }, 300)

  try {
    const res = await pornhubDedupScan()
    clearInterval(timer)
    dedupProgress.value = 100
    dedupFilesScanned.value = res?.scanned_files || 0

    setTimeout(() => {
      dedupScanning.value = false
      dedupResult.value = res
      ElMessage.success(`扫描完成: ${res?.duplicate_groups || 0} 组重复, 可删除 ${res?.removable_files || 0} 个文件`)
    }, 500)
  } catch (e) {
    clearInterval(timer)
    dedupScanning.value = false
    ElMessage.error('去重扫描失败: ' + (e.message || '未知错误'))
  }
}

async function applyDedup() {
  dedupApplying.value = true
  try {
    const res = await pornhubDedupApply()
    ElMessage.success(`删除完成: ${res?.deleted || 0} 个文件, 节省 ${formatBytes(res?.bytes_freed || 0)}`)
    dedupResult.value = null
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.message || '未知错误'))
  } finally { dedupApplying.value = false }
}

function closeDedup() {
  showDedupDialog.value = false
  dedupResult.value = null
  dedupScanning.value = false
}

function onCoverError(e) {
  e.target.src = defaultCover
}

onMounted(loadMovies)
watch(() => route.query, () => { store.page = 1; loadMovies() }, { deep: true })
</script>

<style scoped>
.module-movies { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
.movies-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.movie-card { cursor: pointer; border: 1px solid #ebeef5; border-radius: 8px; overflow: hidden; transition: all 0.2s; }
.movie-card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.1); }
.cover { position: relative; aspect-ratio: 3/4; overflow: hidden; }
.cover img { width: 100%; height: 100%; object-fit: cover; }
.cover-badge { position: absolute; top: 6px; left: 6px; background: rgba(0,0,0,0.6); color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.duration-badge { position: absolute; bottom: 6px; right: 6px; background: rgba(0,0,0,0.7); color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
.info { padding: 8px; }
.title { font-size: 13px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { display: flex; gap: 4px; align-items: center; margin-top: 4px; }
.code { font-size: 11px; color: #999; }
.views { font-size: 10px; color: #409eff; }
.rating { font-size: 10px; color: #e6a23c; margin-left: auto; }
.categories { margin-top: 4px; display: flex; gap: 2px; flex-wrap: wrap; }
.pagination { margin-top: 20px; display: flex; justify-content: center; }
.dedup-status { text-align: center; padding: 30px 0; }
.dedup-status p { margin-top: 16px; color: #666; }
.dedup-result h4 { margin: 16px 0 8px; font-size: 14px; }
.dedup-groups { max-height: 400px; overflow-y: auto; margin: 12px 0; }
.dedup-actions { margin-top: 16px; display: flex; gap: 12px; }
</style>
