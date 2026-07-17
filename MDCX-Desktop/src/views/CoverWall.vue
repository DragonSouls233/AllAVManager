<template>
  <div class="cover-wall" style="height: 100vh; overflow-y: auto; background: #0f0f0f;">
    <!-- 顶部导航 -->
    <div class="cover-wall-header">
      <div class="header-left">
        <h1 class="header-title">封面墙</h1>
        <span class="header-count" v-if="totalCount > 0">{{ totalCount }} 部影片</span>
      </div>
      <div class="header-right">
        <el-input
          v-model="keyword"
          placeholder="搜索番号 / 标题..."
          clearable
          style="width: 240px"
          size="small"
          @keyup.enter="search"
          @clear="search"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select v-model="moduleFilter" placeholder="模块" size="small" style="width: 120px" @change="loadData">
          <el-option label="全部" value="" />
          <el-option label="JAV 有码" value="jav" />
          <el-option label="JAV 无码" value="uncensored" />
          <el-option label="FC2" value="fc2" />
          <el-option label="国产" value="chinese" />
          <el-option label="PORNHub" value="pornhub" />
        </el-select>
        <el-select v-model="sortBy" placeholder="排序" size="small" style="width: 140px" @change="loadData">
          <el-option label="最新发布" value="-release_date" />
          <el-option label="评分最高" value="-rating" />
          <el-option label="播放最多" value="-play_count" />
          <el-option label="时长最长" value="-duration" />
        </el-select>
      </div>
    </div>

    <!-- 封面墙网格 -->
    <div
      class="cover-grid"
      ref="gridRef"
      v-infinite-scroll="loadMore"
      :infinite-scroll-distance="200"
      :infinite-scroll-immediate="false"
    >
      <div
        v-for="item in items"
        :key="item.id"
        class="cover-item"
        @click="openMovie(item)"
        @mouseenter="onItemEnter($event, item)"
        @mouseleave="onItemLeave($event, item)"
      >
        <div class="cover-image-wrapper">
          <img
            :src="getCoverUrl(item)"
            :alt="item.code"
            class="cover-image"
            loading="lazy"
            @error="onImageError($event, item)"
          />
          <!-- 模块标签 -->
          <span class="cover-badge" :class="`badge-${item.module || 'jav'}`">
            {{ moduleLabel(item.module) }}
          </span>
          <!-- 时长 -->
          <span class="cover-duration" v-if="item.duration">
            {{ formatDuration(item.duration) }}
          </span>
          <!-- 评分 -->
          <span class="cover-rating" v-if="item.rating != null">
            {{ item.rating.toFixed(1) }}
          </span>
        </div>
        <div class="cover-info">
          <p class="cover-code">{{ item.code }}</p>
          <p class="cover-title" v-if="item.title">{{ item.title }}</p>
          <p class="cover-actors" v-if="item.actors?.length">
            {{ item.actors.map(a => a.name || a).join(' / ') }}
          </p>
        </div>
        <!-- 悬停提示 -->
        <div class="cover-hover-info" v-show="hoveredId === item.id">
          <p class="hover-title">{{ item.title }}</p>
          <p class="hover-actors" v-if="item.actors?.length">
            演员: {{ item.actors.map(a => a.name || a).join(', ') }}
          </p>
          <p class="hover-date" v-if="item.release_date">发行: {{ item.release_date }}</p>
          <p class="hover-studio" v-if="item.studio">制作商: {{ item.studio }}</p>
        </div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="cover-loading">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <span>加载中...</span>
    </div>
    <div v-if="!loading && items.length === 0" class="cover-empty">
      <el-icon :size="48"><PictureFilled /></el-icon>
      <p>{{ keyword ? '未找到匹配的影片' : '暂无影片数据' }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMovieCoverUrl } from '@/utils/media'
import { getMovies } from '@/api'

const router = useRouter()

const items = ref([])
const loading = ref(false)
const keyword = ref('')
const moduleFilter = ref('')
const sortBy = ref('-release_date')
const totalCount = ref(0)
const page = ref(1)
const pageSize = 30
const hoveredId = ref(null)
let hoverTimer = null

function getCoverUrl(item) {
  return getMovieCoverUrl(item)
}

function moduleLabel(module) {
  const labels = { jav: 'JAV', uncensored: '无码', fc2: 'FC2', chinese: '国产', pornhub: 'PORNHub' }
  return labels[module] || module || '未知'
}

function formatDuration(seconds) {
  if (!seconds) return ''
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

function onImageError(event, item) {
  event.target.src = 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 280"><rect fill="#2c2c2c" width="200" height="280"/><text fill="#666" font-size="14" text-anchor="middle" x="100" y="140">' + (item.code || 'NO IMAGE') + '</text></svg>')
}

function openMovie(item) {
  router.push({ name: 'MovieDetail', params: { id: item.id }, query: { module: item.module || 'jav' } })
}

function onItemEnter(event, item) {
  clearTimeout(hoverTimer)
  hoverTimer = setTimeout(() => {
    hoveredId.value = item.id
  }, 300)
}

function onItemLeave(event, item) {
  clearTimeout(hoverTimer)
  hoveredId.value = null
}

async function loadData() {
  loading.value = true
  page.value = 1
  try {
    const params = {
      page: page.value,
      page_size: pageSize,
      sort_by: sortBy.value,
    }
    if (keyword.value) params.keyword = keyword.value
    if (moduleFilter.value) params.module = moduleFilter.value

    const data = await getMovies(params)
    items.value = data.items || []
    totalCount.value = data.total || 0
  } catch (e) {
    ElMessage.error('加载数据失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (loading.value) return
  loading.value = true
  page.value++
  try {
    const params = {
      page: page.value,
      page_size: pageSize,
      sort_by: sortBy.value,
    }
    if (keyword.value) params.keyword = keyword.value
    if (moduleFilter.value) params.module = moduleFilter.value

    const data = await getMovies(params)
    items.value.push(...(data.items || []))
    totalCount.value = data.total || 0
  } catch (e) {
    page.value--
    ElMessage.error('加载更多失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

function search() {
  loadData()
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.cover-wall {
  padding: 0;
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.cover-wall-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(15, 15, 15, 0.95);
  backdrop-filter: blur(10px);
  padding: 16px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
}

.header-count {
  color: #888;
  font-size: 13px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cover-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 4px;
  padding: 4px;
}

.cover-item {
  position: relative;
  cursor: pointer;
  overflow: hidden;
  border-radius: 4px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.cover-item:hover {
  transform: scale(1.02);
  z-index: 2;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.cover-image-wrapper {
  position: relative;
  width: 100%;
  aspect-ratio: 2/3;
  overflow: hidden;
  background: #1a1a1a;
}

.cover-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.cover-badge {
  position: absolute;
  top: 6px;
  left: 6px;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  pointer-events: none;
}

.badge-jav { background: #e74c3c; }
.badge-uncensored { background: #9b59b6; }
.badge-fc2 { background: #2ecc71; }
.badge-chinese { background: #f39c12; }
.badge-pornhub { background: #3498db; }

.cover-duration {
  position: absolute;
  bottom: 6px;
  right: 6px;
  padding: 1px 6px;
  background: rgba(0, 0, 0, 0.75);
  border-radius: 3px;
  font-size: 11px;
  color: #ccc;
  pointer-events: none;
}

.cover-rating {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.75);
  border-radius: 3px;
  font-size: 11px;
  color: #f1c40f;
  font-weight: 600;
  pointer-events: none;
}

.cover-info {
  padding: 8px;
  background: #1a1a1a;
}

.cover-code {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 600;
  color: #e0e0e0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cover-title {
  margin: 0 0 2px;
  font-size: 11px;
  color: #999;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cover-actors {
  margin: 0;
  font-size: 11px;
  color: #666;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cover-hover-info {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 12px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.9));
  pointer-events: none;
}

.hover-title {
  margin: 0 0 6px;
  font-size: 13px;
  color: #fff;
  font-weight: 600;
  line-height: 1.3;
}

.hover-actors,
.hover-date,
.hover-studio {
  margin: 2px 0;
  font-size: 11px;
  color: #ccc;
}

.cover-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  color: #888;
}

.cover-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 80px 20px;
  color: #666;
}

.cover-empty p {
  margin: 0;
  font-size: 15px;
}
</style>
