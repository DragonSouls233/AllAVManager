<template>
  <div class="cover-wall" style="height: 100vh; overflow-y: auto; background: #0f0f0f;">
    <div class="cover-wall-header">
      <div class="header-left">
        <h1 class="header-title">封面墙</h1>
        <span class="header-count" v-if="totalCount > 0">{{ totalCount }} 部影片</span>
      </div>
      <div class="header-right">
        <el-input v-model="keyword" placeholder="搜索番号 / 标题..." clearable style="width: 240px" size="small" @keyup.enter="search" @clear="search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="moduleFilter" placeholder="模块" size="small" style="width: 120px" @change="loadData">
          <el-option label="全部" value="" />
          <el-option label="JAV 有码" value="jav" />
          <el-option label="无码" value="uncensored" />
          <el-option label="FC2" value="fc2" />
          <el-option label="国产" value="chinese" />
          <el-option label="欧美" value="western" />
        </el-select>
        <el-select v-model="coverPageSize" size="small" style="width: 80px" @change="loadData">
          <el-option :value="48" label="48" />
          <el-option :value="96" label="96" />
          <el-option :value="192" label="192" />
          <el-option :value="384" label="384" />
        </el-select>
      </div>
    </div>

    <div class="cover-grid" v-loading="loading">
      <div v-for="item in items" :key="item.id" class="cover-item" @click="openMovie(item)">
        <div class="cover-image-wrapper">
          <img :src="coverUrl(item)" :alt="item.code" class="cover-image" loading="lazy" @error="onImageError($event, item)" />
          <span class="cover-badge" :class="`badge-${item.module || 'jav'}`">{{ moduleLabel(item.module) }}</span>
          <span class="cover-code-overlay">{{ item.code }}</span>
        </div>
        <div class="cover-info">
          <p class="cover-title-line" v-if="item.title">{{ item.title }}</p>
          <div class="cover-tags">
            <span v-if="item.studio" class="tag-studio">{{ item.studio }}</span>
            <span v-if="item.release_date" class="tag-date">{{ String(item.release_date).slice(0, 10) }}</span>
            <el-tag v-for="b in getMovieVersionBadges(item)" :key="b.text" size="small" :type="versionBadgeType(b.type)" effect="dark">{{ b.text }}</el-tag>
          </div>
          <p class="cover-actors-line" v-if="item.actor">{{ item.actor }}</p>
        </div>
      </div>
      <el-empty v-if="!loading && !items.length" description="暂无影片" />
    </div>

    <div class="pagination-bar" v-if="totalCount > coverPageSize">
      <el-pagination
        v-model:current-page="page"
        :page-size="coverPageSize"
        :total="totalCount"
        layout="total, prev, pager, next"
        @current-change="onPageChange"
        background
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMovies } from '@/api'
import { getServerBaseUrl, getMovieVersionBadges, versionBadgeType } from '@/utils/media'

const router = useRouter()
const items = ref([])
const loading = ref(false)
const keyword = ref('')
const moduleFilter = ref('')
const page = ref(1)
const coverPageSize = ref(48)
const totalCount = ref(0)

// 复用 media.js 的统一逻辑：Web 用页面 origin，Electron 桌面端回退 localStorage serverUrl（file:// 下 origin 不是后端地址）
function getServerBase() {
  return getServerBaseUrl()
}

function coverUrl(item) {
  if (!item) return ''
  const mod = item.module || item.module_type || 'jav'
  // 优先走后端代理端点（解决防盗链/跨域），回退到本地路径代理
  if (item.id) return `${getServerBase()}/api/v1/${mod}/movies/${item.id}/cover/file`
  if (item.cover_url) {
    if (/^https?:\/\//i.test(item.cover_url)) return item.cover_url
    return `${getServerBase()}/api/v1/files/proxy?path=${encodeURIComponent(item.cover_url)}`
  }
  return 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 280"><rect fill="#222" width="200" height="280"/><text fill="#555" font-size="14" text-anchor="middle" x="100" y="140">${item.code || 'N/A'}</text></svg>`)
}

function moduleLabel(mod) {
  const m = { jav: 'JAV', uncensored: '无码', fc2: 'FC2', chinese: '国产', western: '欧美', pornhub: 'PH' }
  return m[mod] || mod || '?'
}

function onImageError(e, item) {
  e.target.src = 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 280"><rect fill="#222" width="200" height="280"/><text fill="#555" font-size="14" text-anchor="middle" x="100" y="140">${item.code || 'N/A'}</text></svg>`)
}

function openMovie(item) {
  router.push({ name: 'MovieDetail', params: { id: item.id }, query: { module: item.module || 'jav' } })
}

async function loadData() {
  loading.value = true
  try {
    const data = await getMovies({
      page: page.value,
      page_size: coverPageSize.value,
      keyword: keyword.value || undefined,
      module: moduleFilter.value || undefined,
    })
    items.value = data.items || []
    totalCount.value = data.total || 0
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

function onPageChange(p) {
  page.value = p
  loadData()
}

function search() {
  page.value = 1
  loadData()
}

onMounted(() => loadData())
</script>

<style scoped>
.cover-wall { padding: 0; margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.cover-wall-header {
  position: sticky; top: 0; z-index: 10; background: rgba(15,15,15,0.95);
  backdrop-filter: blur(10px); padding: 16px 24px; display: flex; align-items: center;
  justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.08);
}
.header-left { display: flex; align-items: center; gap: 12px; }
.header-title { margin: 0; font-size: 22px; font-weight: 700; color: #fff; }
.header-count { color: #888; font-size: 13px; }
.header-right { display: flex; align-items: center; gap: 10px; }
.cover-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 6px; padding: 6px;
}
.cover-item { position: relative; cursor: pointer; border-radius: 4px; overflow: hidden; transition: transform .2s; }
.cover-item:hover { transform: scale(1.03); z-index: 2; }
.cover-image-wrapper { position: relative; aspect-ratio: 2/3; overflow: hidden; background: #1a1a1a; }
.cover-image { width: 100%; height: 100%; object-fit: cover; display: block; }
.cover-badge { position: absolute; top: 4px; left: 4px; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; color: #fff; }
.badge-jav { background: #e74c3c; } .badge-uncensored { background: #9b59b6; } .badge-fc2 { background: #2ecc71; } .badge-chinese { background: #f39c12; } .badge-western { background: #3498db; }
.cover-code-overlay { position: absolute; bottom: 4px; left: 4px; padding: 1px 5px; background: rgba(0,0,0,0.7); color: #ddd; font-size: 10px; font-family: monospace; border-radius: 2px; }
.cover-info { padding: 6px 8px; background: #1a1a1a; }
.cover-title-line { margin: 0 0 3px; font-size: 12px; color: #ccc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cover-tags { display: flex; gap: 3px; flex-wrap: wrap; margin-bottom: 2px; }
.tag-studio { font-size: 10px; color: #888; background: rgba(255,255,255,0.06); padding: 1px 4px; border-radius: 2px; }
.tag-date { font-size: 10px; color: #777; }
.tag-cn { font-size: 10px; color: #e74c3c; font-weight: 600; }
.tag-un { font-size: 10px; color: #e67e22; font-weight: 600; }
.cover-actors-line { margin: 0; font-size: 10px; color: #666; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pagination-bar { display: flex; justify-content: center; padding: 20px; }
</style>
