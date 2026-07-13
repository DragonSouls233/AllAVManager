<template>
  <div class="movies-page">
    <!-- 工具栏 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索番号 / 标题..."
          clearable
          style="width: 280px"
          @keyup.enter="search"
          @clear="search"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="search">
          <el-icon><Search /></el-icon> 搜索
        </el-button>
        <el-button @click="resetFilters">重置</el-button>

        <div class="toolbar-right">
          <!-- 视图模式切换：紧凑/标准/详细 -->
          <el-button-group class="view-mode-group">
            <el-button
              v-for="mode in viewModes"
              :key="mode.value"
              :type="uiStore.viewMode === mode.value ? 'primary' : 'default'"
              size="small"
              :title="mode.label"
              @click="uiStore.setViewMode(mode.value)"
            >
              <el-icon><component :is="mode.icon" /></el-icon>
            </el-button>
          </el-button-group>
          <!-- 图片模式切换：封面/缩略图 -->
          <el-button-group class="image-mode-group">
            <el-button
              :type="uiStore.imageMode === 'poster' ? 'primary' : 'default'"
              size="small"
              title="封面图"
              @click="uiStore.setImageMode('poster')"
            >
              <el-icon><Picture /></el-icon>
            </el-button>
            <el-button
              :type="uiStore.imageMode === 'thumbnail' ? 'primary' : 'default'"
              size="small"
              title="缩略图（视频截图）"
              @click="uiStore.setImageMode('thumbnail')"
            >
              <el-icon><VideoCamera /></el-icon>
            </el-button>
          </el-button-group>
          <!-- 海报模式切换：完整/马赛克/仅番号（B2 纯净模式） -->
          <el-radio-group
            v-model="posterModeProxy"
            size="small"
            class="poster-mode-group"
          >
            <el-radio-button value="full" title="完整显示海报">完整</el-radio-button>
            <el-radio-button value="mosaic" title="海报马赛克模糊">马赛克</el-radio-button>
            <el-radio-button value="number_only" title="隐藏海报，仅显示番号">仅番号</el-radio-button>
          </el-radio-group>
          <el-select v-model="sortBy" placeholder="排序" style="width: 160px" @change="onSortChange">
            <el-option label="默认（最新）" value="" />
            <el-option label="发行日期 ↓" value="-release_date" />
            <el-option label="发行日期 ↑" value="release_date" />
            <el-option label="评分 ↓" value="-rating" />
            <el-option label="播放次数 ↓" value="-play_count" />
            <el-option label="最近播放 ↓" value="-last_played_at" />
            <el-option label="时长 ↓" value="-duration" />
            <el-option label="文件大小 ↓" value="-file_size" />
            <el-option label="标题 A-Z" value="title" />
          </el-select>
          <el-button @click="toggleRandom" :type="isRandom ? 'warning' : 'default'">
            <el-icon><Sort /></el-icon>
            {{ isRandom ? '随机中' : '随机' }}
          </el-button>
          <el-button v-if="isRandom" @click="reshuffle" size="small" circle>
            <el-icon><Refresh /></el-icon>
          </el-button>
          <el-button
            :type="onlyFavorite ? 'warning' : 'default'"
            @click="toggleFavoriteFilter"
          >
            <el-icon><Star /></el-icon> {{ onlyFavorite ? '已选藏' : '仅收藏' }}
          </el-button>
          <el-button
            :type="hasAdvancedFilters ? 'primary' : 'default'"
            @click="filterDrawerVisible = true"
          >
            <el-icon><Filter /></el-icon> 筛选
            <el-badge v-if="hasAdvancedFilters" is-dot class="filter-badge" />
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 首字母导航 -->
    <AlphabetNav
      :alphabet="alphabet"
      :selected-letter="selectedLetter"
      @select="selectLetter"
    />

    <!-- 当前筛选条件 -->
    <div class="active-filters" v-if="hasActiveFilters">
      <span class="filters-label">已选筛选:</span>
      <el-tag v-if="selectedLetter" closable size="small" @close="selectedLetter = ''">
        字母: {{ selectedLetter }}
      </el-tag>
      <el-tag v-for="t in selectedTags" :key="t.id" closable size="small" @close="removeTag(t.id)">
        {{ t.name }}
      </el-tag>
      <el-tag v-if="selectedTags.length > 1" type="warning" size="small">
        {{ tagMode === 'AND' ? '全部匹配 (AND)' : '任一匹配 (OR)' }}
        <el-button text size="small" @click="toggleTagMode" style="margin-left: 4px; padding: 0">
          切换
        </el-button>
      </el-tag>
      <el-tag v-if="onlyFavorite" type="warning" size="small" closable @close="onlyFavorite = false">
        仅收藏
      </el-tag>
      <el-tag v-if="seriesFilter" type="success" size="small" closable @close="clearSeriesFilter">
        系列: {{ seriesFilter }}
      </el-tag>
      <el-tag v-if="makerFilter" type="warning" size="small" closable @close="clearMakerFilter">
        片商: {{ makerFilter }}
      </el-tag>
      <el-tag v-if="studioFilter" type="info" size="small" closable @close="clearStudioFilter">
        制作商: {{ studioFilter }}
      </el-tag>
      <el-tag v-if="minRating !== null || maxRating !== null" type="info" size="small" closable @close="clearRatingFilter">
        评分: {{ minRating ?? 0 }} - {{ maxRating ?? 10 }}
      </el-tag>
    </div>

    <!-- 影片瀑布流（虚拟滚动） -->
    <VirtualScroll
      v-if="movies.length > 0"
      :items="movies"
      :item-height="cardSize.height"
      :height="gridHeight"
      key-field="id"
      :grid-class="`movies-grid mode-${uiStore.viewMode} img-${uiStore.imageMode}`"
      :min-item-width="cardSize.minWidth"
      :gap="cardSize.gap"
      :buffer-rows="5"
      @scroll="onVirtualScroll"
    >
      <template #default="{ item }">
        <MovieCard
          :movie="item"
          :view-mode="uiStore.viewMode"
          :image-mode="uiStore.imageMode"
          @click="goDetail"
          @play="playMovie"
          @fav="toggleFavorite"
          @actor-click="goActor"
          @tag-click="addTagFilter"
          @preview-cover="openCoverPreview"
        />
      </template>
    </VirtualScroll>
    <div v-else-if="loading" class="movies-grid" :class="[`mode-${uiStore.viewMode}`, `img-${uiStore.imageMode}`]">
      <!-- 加载态占位 -->
      <el-skeleton
        v-for="n in 8"
        :key="n"
        :rows="4"
        animated
        style="border-radius: 10px; padding: 12px;"
      />
    </div>
    <el-empty v-else description="暂无数据" />

    <!-- 封面预览模态（0.5x-5x 缩放） -->
    <CoverPreview
      v-model="coverPreviewVisible"
      :src="coverPreviewSrc"
      :title="coverPreviewTitle"
    />

    <!-- 无限滚动哨兵 -->
    <div ref="sentinelRef" class="scroll-sentinel" v-if="total > 0" aria-live="polite">
      <div v-if="loadingMore" class="loading-more">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载更多...</span>
      </div>
      <div v-else-if="!hasMore" class="no-more">
        已加载全部 {{ total }} 部影片
      </div>
    </div>

    <!-- 高级筛选抽屉 -->
    <el-drawer v-model="filterDrawerVisible" title="高级筛选" size="480px">
      <TagFilter
        v-model:tag-mode="tagMode"
        v-model:tag-search="tagSearch"
        v-model:min-rating="minRating"
        v-model:max-rating="maxRating"
        v-model:only-favorite="onlyFavorite"
        :tags="allTags"
        :selected-tags="selectedTags"
        :loading="tagsLoading"
        @toggle-tag="toggleTag"
        @clear="clearFilters"
        @apply="applyFilters"
      />
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Search, Sort, Refresh, Star, Filter, Loading,
  Grid, Menu as MenuIcon, List, Picture, VideoCamera
} from '@element-plus/icons-vue'
// 注意：此处图标列表仅为占位，海报模式按钮组使用 el-radio-button 文本，无需额外图标
import {
  getMovies, getAlphabet, getTags,
  getFavoriteGroups, addFavoriteItem, removeFavoriteItem, checkFavorite
} from '@/api'
import AlphabetNav from '@/components/AlphabetNav.vue'
import MovieCard from '@/components/MovieCard.vue'
import TagFilter from '@/components/TagFilter.vue'
import CoverPreview from '@/components/CoverPreview.vue'
import VirtualScroll from '@/components/VirtualScroll.vue'
import { getMovieCoverUrl } from '@/utils/media'
import { useUiStore } from '@/stores/ui'

const uiStore = useUiStore()

// 视图模式选项（紧凑/标准/详细）
const viewModes = [
  { value: 'compact', label: '紧凑视图', icon: Grid },
  { value: 'standard', label: '标准视图', icon: MenuIcon },
  { value: 'detail', label: '详细视图', icon: List },
]

// 虚拟滚动:卡片尺寸估算（依据视图模式 + 图片模式）
// 网格列数由 VirtualScroll 根据 minItemWidth + gap 自动计算
const cardSize = computed(() => {
  const isThumbnail = uiStore.imageMode === 'thumbnail'
  if (uiStore.viewMode === 'compact') {
    return isThumbnail
      ? { minWidth: 200, height: 200, gap: 10 }
      : { minWidth: 150, height: 300, gap: 10 }
  }
  if (uiStore.viewMode === 'detail') {
    return { minWidth: 560, height: 240, gap: 12 }
  }
  // standard
  return isThumbnail
    ? { minWidth: 280, height: 260, gap: 16 }
    : { minWidth: 220, height: 420, gap: 16 }
})

// 虚拟滚动容器高度:窗口高度 - 头部/工具栏/字母导航等估算空间
const gridHeight = computed(() => Math.max(400, window.innerHeight - 320))

// 虚拟滚动事件转发:接近底部时触发加载下一页（保留 800px 提前量）
const onVirtualScroll = ({ scrollTop }) => {
  const virtualScrollEl = document.querySelector('.virtual-scroll')
  if (!virtualScrollEl) return
  const scrollHeight = virtualScrollEl.scrollHeight
  const clientHeight = virtualScrollEl.clientHeight
  if (scrollTop + clientHeight >= scrollHeight - 800) {
    loadNextPage()
  }
}

// 海报模式双向绑定（B2 纯净模式：full/mosaic/number_only）
const posterModeProxy = computed({
  get: () => uiStore.posterMode,
  set: (val) => uiStore.setPosterMode(val),
})

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const loadingMore = ref(false)
const movies = ref([])
const keyword = ref('')
const page = ref(1)
const pageSize = ref(24)
const total = ref(0)
const sortBy = ref('')
const isRandom = ref(false)
const randomSeed = ref(null)

// 无限滚动
const sentinelRef = ref(null)
let ioObserver = null
const hasMore = computed(() => movies.value.length < total.value)

// 字母导航
const alphabet = ref([])
const selectedLetter = ref('')

// 标签筛选
const allTags = ref([])
const tagsLoading = ref(false)
const selectedTags = ref([])
const tagMode = ref('OR')
const tagSearch = ref('')

// 评分 & 收藏
const minRating = ref(null)
const maxRating = ref(null)
const onlyFavorite = ref(false)
const seriesFilter = ref('')
const makerFilter = ref('')
const studioFilter = ref('')

// 抽屉
const filterDrawerVisible = ref(false)

// 封面预览
const coverPreviewVisible = ref(false)
const coverPreviewSrc = ref('')
const coverPreviewTitle = ref('')

const openCoverPreview = (movie) => {
  coverPreviewSrc.value = getMovieCoverUrl(movie)
  coverPreviewTitle.value = movie.code || ''
  coverPreviewVisible.value = true
}

// ============== 计算属性 ==============
const hasAdvancedFilters = computed(
  () => selectedTags.value.length > 0 || minRating.value !== null || maxRating.value !== null
)

const hasActiveFilters = computed(
  () => !!selectedLetter.value || selectedTags.value.length > 0 || onlyFavorite.value
    || minRating.value !== null || maxRating.value !== null || !!keyword.value || !!seriesFilter.value
)

// ============== 数据加载 ==============
const loadMovies = async (append = false) => {
  if (append) {
    if (loadingMore.value || !hasMore.value) return
    loadingMore.value = true
  } else {
    loading.value = true
  }
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      search: keyword.value || undefined,
      tag_ids: selectedTags.value.length ? selectedTags.value.map(t => t.id).join(',') : undefined,
      tag_mode: selectedTags.value.length ? tagMode.value : undefined,
      letter: selectedLetter.value || undefined,
      is_favorite: onlyFavorite.value ? true : undefined,
      series: seriesFilter.value || undefined,
      maker: makerFilter.value || undefined,
      studio: studioFilter.value || undefined,
      min_rating: minRating.value ?? undefined,
      max_rating: maxRating.value ?? undefined,
    }
    if (isRandom.value && randomSeed.value !== null) {
      params.seed = randomSeed.value
    } else if (sortBy.value) {
      params.sort = sortBy.value
    }
    const res = await getMovies(params)
    const newItems = (res.items || []).map(m => ({ ...m, _imgIndex: 0, _fav: false, _tags: [], _tagsExpanded: false }))
    if (append) {
      movies.value.push(...newItems)
    } else {
      movies.value = newItems
    }
    total.value = res.total || 0
    loadFavoriteStates(append)
    loadMovieTags()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

// 加载下一页（无限滚动触发）
const loadNextPage = () => {
  if (loadingMore.value || !hasMore.value) return
  page.value += 1
  loadMovies(true)
}

// 批量获取每个影片的标签
// 后端 MovieResponse 已返回结构化 tags 字段（含 id/name/is_user），
// 直接映射到 _tags 供 MovieCard 使用；同时对没有 id 的旧数据按名称回填 id
const loadMovieTags = async () => {
  try {
    const tagMap = new Map()
    for (const t of allTags.value) {
      tagMap.set(t.name.toLowerCase(), t)
    }
    for (const m of movies.value) {
      if (Array.isArray(m.tags) && m.tags.length > 0) {
        // 优先使用后端返回的结构化 tags
        m._tags = m.tags.map(t => ({
          id: t.id || 0,
          name: t.name,
          is_user: !!t.is_user
        }))
      } else if (m.tag) {
        // 兜底：从 movie.tag JSON 字段解析（旧数据兼容）
        let names = []
        try {
          const parsed = JSON.parse(m.tag)
          if (Array.isArray(parsed)) {
            names = parsed
          } else if (typeof parsed === 'string') {
            names = parsed.split(/[,，]/).filter(Boolean).map(s => s.trim())
          }
        } catch {
          names = m.tag.split(/[,，]/).filter(Boolean).map(s => s.trim())
        }
        m._tags = names.map(name => {
          const matched = tagMap.get(name.toLowerCase())
          return matched
            ? { id: matched.id, name, is_user: !!matched.is_user }
            : { id: 0, name, is_user: false }
        })
      }
    }
  } catch (e) {
    // 静默
  }
}

const loadAlphabet = async () => {
  try {
    const res = await getAlphabet()
    alphabet.value = res.groups || []
  } catch (e) {
    console.error(e)
  }
}

const loadAllTags = async () => {
  tagsLoading.value = true
  try {
    const res = await getTags({ page: 1, page_size: 500 })
    allTags.value = res.items || res || []
  } catch (e) {
    console.error(e)
  } finally {
    tagsLoading.value = false
  }
}

// ============== 搜索 & 筛选 ==============
const search = () => {
  page.value = 1
  loadMovies()
}

const resetFilters = () => {
  keyword.value = ''
  selectedLetter.value = ''
  selectedTags.value = []
  minRating.value = null
  maxRating.value = null
  onlyFavorite.value = false
  sortBy.value = ''
  isRandom.value = false
  randomSeed.value = null
  page.value = 1
  loadMovies()
}

const onSortChange = () => {
  if (sortBy.value && isRandom.value) {
    isRandom.value = false
    randomSeed.value = null
  }
  page.value = 1
  loadMovies()
}

const toggleRandom = () => {
  isRandom.value = !isRandom.value
  if (isRandom.value) {
    randomSeed.value = Math.floor(Math.random() * 1000000) + 1
    sortBy.value = ''
  } else {
    randomSeed.value = null
  }
  page.value = 1
  loadMovies()
}

const reshuffle = () => {
  randomSeed.value = Math.floor(Math.random() * 1000000) + 1
  page.value = 1
  loadMovies()
}

const selectLetter = (letter) => {
  selectedLetter.value = selectedLetter.value === letter ? '' : letter
  page.value = 1
  loadMovies()
}

const toggleFavoriteFilter = () => {
  onlyFavorite.value = !onlyFavorite.value
  page.value = 1
  loadMovies()
}

const addTagFilter = (tag) => {
  // 卡片上的标签可能没有 id（来自 movie.tag 字段），按名称匹配
  if (!tag.id) {
    const found = allTags.value.find(t => t.name === tag.name)
    if (found) tag = found
    else return ElMessage.info(`标签 "${tag.name}" 未在标签库中找到，无法筛选`)
  }
  if (!selectedTags.value.find(t => t.id === tag.id)) {
    selectedTags.value.push(tag)
    page.value = 1
    loadMovies()
  }
}

const removeTag = (id) => {
  selectedTags.value = selectedTags.value.filter(t => t.id !== id)
  page.value = 1
  loadMovies()
}

const toggleTag = (tag) => {
  if (isTagSelected(tag.id)) {
    selectedTags.value = selectedTags.value.filter(t => t.id !== tag.id)
  } else {
    selectedTags.value.push(tag)
  }
}

const isTagSelected = (id) => selectedTags.value.some(t => t.id === id)

const toggleTagMode = () => {
  tagMode.value = tagMode.value === 'AND' ? 'OR' : 'AND'
  if (selectedTags.value.length > 1) {
    page.value = 1
    loadMovies()
  }
}

const clearRatingFilter = () => {
  minRating.value = null
  maxRating.value = null
  page.value = 1
  loadMovies()
}

const clearSeriesFilter = () => {
  seriesFilter.value = ''
  page.value = 1
  loadMovies()
}

const clearMakerFilter = () => {
  makerFilter.value = ''
  page.value = 1
  loadMovies()
}

const clearStudioFilter = () => {
  studioFilter.value = ''
  page.value = 1
  loadMovies()
}

const clearFilters = () => {
  selectedTags.value = []
  minRating.value = null
  maxRating.value = null
  onlyFavorite.value = false
  seriesFilter.value = ''
  makerFilter.value = ''
  studioFilter.value = ''
  tagSearch.value = ''
}

const applyFilters = () => {
  filterDrawerVisible.value = false
  page.value = 1
  loadMovies()
}

// ============== 路由跳转 ==============
// 点击卡片进入番号详情页（简介/图片/系列），详情页内再点“播放”进入播放页
const goDetail = (id) => router.push(`/movie/${id}`)
const playMovie = (id) => router.push(`/play/${id}`)
const goActor = (id) => router.push(`/actors/${id}`)

// ============== 收藏 ==============
const toggleFavorite = async (movie) => {
  try {
    if (movie._fav) {
      const check = await checkFavorite('movie', movie.id)
      const data = check.items ? check : (check.data || check)
      if (data.groups && data.groups.length > 0) {
        await removeFavoriteItem(data.groups[0].group_id, movie.id)
        movie._fav = false
        ElMessage.success('已取消收藏')
      }
    } else {
      const res = await getFavoriteGroups('movie')
      const groups = res.items ? res : (res.data || res)
      let groupId = groups.length > 0 ? groups[0].id : null
      if (!groupId) {
        const { createFavoriteGroup } = await import('@/api')
        const newGroup = await createFavoriteGroup('默认收藏', 'movie')
        groupId = (newGroup.items ? newGroup : (newGroup.data || newGroup)).id
      }
      await addFavoriteItem(groupId, movie.id)
      movie._fav = true
      ElMessage.success('已收藏')
    }
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const loadFavoriteStates = async (append = false) => {
  const start = append ? movies.value.length - (page.value === 1 ? 0 : pageSize.value) : 0
  for (let i = Math.max(0, start); i < movies.value.length; i++) {
    const movie = movies.value[i]
    if (movie._fav === true) continue
    try {
      const check = await checkFavorite('movie', movie.id)
      const data = check.items ? check : (check.data || check)
      movie._fav = data.in_favorites || false
    } catch {
      movie._fav = false
    }
  }
}

// ============== 无限滚动 IntersectionObserver ==============
const setupObserver = () => {
  if (ioObserver) ioObserver.disconnect()
  ioObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && hasMore.value && !loadingMore.value && !loading.value) {
          loadNextPage()
        }
      }
    },
    { rootMargin: '640px 0px', threshold: 0.01 }
  )
  if (sentinelRef.value) ioObserver.observe(sentinelRef.value)
}

onMounted(async () => {
  // 先加载标签库（loadMovieTags 依赖 allTags 匹配 is_user 字段）
  await loadAllTags()
  // 从详情页跳转带入的筛选参数
  if (route.query.series) {
    seriesFilter.value = String(route.query.series)
  }
  if (route.query.maker) {
    makerFilter.value = String(route.query.maker)
  }
  if (route.query.studio) {
    studioFilter.value = String(route.query.studio)
  }
  if (route.query.search) {
    keyword.value = String(route.query.search)
  }
  if (route.query.tag_ids) {
    const ids = String(route.query.tag_ids).split(',').map(Number).filter(n => n > 0)
    selectedTags.value = ids.map(id => allTags.value.find(t => t.id === id)).filter(Boolean)
  }
  loadMovies()
  loadAlphabet()
})

// 哨兵元素出现后设置 observer
watch([total, sentinelRef], () => {
  nextTick(() => setupObserver())
})

onBeforeUnmount(() => {
  if (ioObserver) {
    ioObserver.disconnect()
    ioObserver = null
  }
})
</script>

<style scoped>
.movies-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.toolbar-card {
  border-radius: 8px !important;
}

.toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.toolbar-right {
  margin-left: auto;
  display: flex;
  gap: 8px;
  align-items: center;
}

.filter-badge {
  margin-left: -4px;
  margin-top: -8px;
}

/* 海报模式切换按钮组 */
.poster-mode-group {
  margin-left: 4px;
}

/* 已选筛选标签 */
.active-filters {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 8px 12px;
  background: var(--brand-gradient-soft);
  border-radius: 6px;
}

.filters-label {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 影片瀑布流：通过 :deep() 让样式穿透到 VirtualScroll 内部 viewport */
:deep(.movies-grid) {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
  min-height: 400px;
}

/* ===== 视图模式 ===== */
/* 紧凑模式：更小的卡片，更多列 */
:deep(.movies-grid.mode-compact) {
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}

/* 标准模式：默认 */
:deep(.movies-grid.mode-standard) {
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

/* 详细模式：横向卡片，单列或双列 */
:deep(.movies-grid.mode-detail) {
  grid-template-columns: repeat(auto-fill, minmax(560px, 1fr));
  gap: 12px;
}

/* 缩略图模式下，紧凑/标准模式调整为 16:9 比例 */
:deep(.movies-grid.img-thumbnail.mode-compact) {
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
}
:deep(.movies-grid.img-thumbnail.mode-standard) {
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}

/* VirtualScroll 容器自身样式 */
:deep(.virtual-scroll) {
  border-radius: 8px;
}

/* 暗黑模式补丁 */
:deep(.el-drawer__body) {
  background: var(--bg-card);
}

/* 无限滚动哨兵 */
.scroll-sentinel {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 24px 0;
  min-height: 60px;
}

.loading-more {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.loading-more .is-loading {
  animation: rotating 1.5s linear infinite;
}

.no-more {
  color: var(--text-placeholder);
  font-size: 12px;
}
</style>
