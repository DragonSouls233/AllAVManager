<template>
  <section>
    <div class="cinema-page-head">
      <h1 class="cinema-page-title">影片库</h1>
      <span class="cinema-page-count">{{ lib.currentLabel }} · 共 {{ total }} 部</span>
    </div>

    <!-- 筛选条：排序 + 当前维度筛选（保留可清除，绝不清空用户输入） -->
    <div class="cinema-filters">
      <el-select v-model="sort" size="small" style="width: 150px" @change="reload">
        <el-option label="发行日期 ↓" value="-release_date" />
        <el-option label="发行日期 ↑" value="release_date" />
        <el-option label="评分 ↓" value="-rating" />
        <el-option label="番号 ↑" value="code" />
        <el-option label="番号 ↓" value="-code" />
        <el-option label="最近加入" value="-created_at" />
      </el-select>

      <el-tag v-if="lib.keyword" type="primary" closable @close="clearKeyword">
        搜索：{{ lib.keyword }}
      </el-tag>
      <el-tag v-if="lib.filter.genre" type="danger" closable @close="clearFilter('genre')">
        类别：{{ lib.filter.genre }}
      </el-tag>
      <el-tag v-if="lib.filter.series" type="success" closable @close="clearFilter('series')">
        系列：{{ lib.filter.series }}
      </el-tag>
      <el-tag v-if="lib.filter.actor" type="warning" closable @close="clearFilter('actor')">
        演员：{{ lib.filter.actor }}
      </el-tag>
    </div>

    <!-- 错误态：保留全部筛选，只提示 + 重试 -->
    <div v-if="error" class="cinema-empty">
      <div class="cinema-empty-icon">⚠️</div>
      <div class="cinema-empty-text">{{ error }}</div>
      <el-button size="small" style="margin-top: 12px" @click="reload">重试</el-button>
    </div>

    <!-- 空态 -->
    <div v-else-if="!loading && !items.length" class="cinema-empty">
      <div class="cinema-empty-icon">🎬</div>
      <div class="cinema-empty-text">没有匹配的影片</div>
    </div>

    <!-- 海报网格 -->
    <div v-else class="cinema-grid">
      <template v-if="loading && !items.length">
        <div v-for="n in 18" :key="`sk-${n}`" class="poster-skeleton" />
      </template>
      <PosterCard
        v-for="m in items"
        :key="`${m.module_name || lib.currentModule}-${m.id}`"
        :movie="m"
        @open="openDetail"
        @play="playMovie"
      />
    </div>

    <!-- 无限滚动哨兵 -->
    <div ref="sentinel" style="height: 1px" />
    <div v-if="loading && items.length" class="cinema-loading-more">加载中…</div>
    <div v-else-if="!hasMore && items.length" class="cinema-loading-more">已到底部</div>
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import PosterCard from '@/components/cinema/PosterCard.vue'
import { enrichStatus } from '@/utils/browse'
import { useLibraryStore } from '@/stores/library'
import { getJavMovies } from '@/api/jav'
import { getFc2Movies } from '@/api/fc2'
import { getMovies as getUncensoredMovies } from '@/api/uncensored'
import { getChineseMovies } from '@/api/chinese'
import { getPornhubMovies } from '@/api/pornhub'
import { getWesternMovies } from '@/api/western'
import { getAnimeMovies } from '@/api/anime'

const PAGE = 48

// 各模块列表接口形状一致（{total, items}），仅参数命名略有差异
const FETCHERS = {
  jav: getJavMovies,
  fc2: getFc2Movies,
  uncensored: getUncensoredMovies,
  chinese: getChineseMovies,
  pornhub: getPornhubMovies,
  western: getWesternMovies,
  anime: getAnimeMovies
}

const router = useRouter()
const lib = useLibraryStore()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const hasMore = ref(true)
const sentinel = ref(null)
const sort = ref(lib.filter.sort || '-release_date')

let observer = null
let requestSeq = 0

const filtersKey = computed(() =>
  `${lib.currentModule}|${lib.keyword}|${lib.filter.genre}|${lib.filter.series}|${lib.filter.actor}|${sort.value}`
)

async function loadMore() {
  if (loading.value || !hasMore.value) return
  const fetcher = FETCHERS[lib.currentModule]
  if (!fetcher) {
    error.value = `模块 ${lib.currentModule} 暂不支持浏览`
    return
  }

  const seq = ++requestSeq
  loading.value = true
  error.value = ''

  const skip = items.value.length
  const params = {
    skip,
    limit: PAGE,
    sort: sort.value,
    // uncensored 等部分模块使用 page/page_size 命名，多余参数后端忽略
    page: Math.floor(skip / PAGE) + 1,
    page_size: PAGE
  }
  if (lib.keyword) params.keyword = lib.keyword
  if (lib.filter.genre) params.genre = lib.filter.genre
  if (lib.filter.series) params.series = lib.filter.series
  if (lib.filter.actor) params.actor = lib.filter.actor

  try {
    const res = await fetcher(params)
    if (seq !== requestSeq) return // 丢弃过期响应，避免竞态串页
    const list = res?.items || []
    items.value = skip === 0 ? list : items.value.concat(list)
    total.value = res?.total ?? items.value.length
    hasMore.value = list.length >= PAGE
    enrichStatus(list, lib.currentModule) // 批量补角标/进度（静默失败）
  } catch (e) {
    if (seq !== requestSeq) return
    // 错误时保留已加载内容与全部筛选条件
    error.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载失败，请检查服务器连接'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function reload() {
  lib.applyFilter({ sort: sort.value })
  items.value = []
  total.value = 0
  hasMore.value = true
  error.value = ''
  loadMore()
}

function clearKeyword() {
  lib.setKeyword('')
  window.dispatchEvent(new CustomEvent('mdcx-library-sync'))
  reload()
}

function clearFilter(key) {
  lib.applyFilter({ [key]: '' })
  reload()
}

function openDetail(movie) {
  const mod = movie.module_name || lib.currentModule
  router.push(`/movie/${mod}/${movie.id}`)
}

function playMovie(movie) {
  const mod = movie.module_name || lib.currentModule
  router.push(`/mpv/${mod}/${movie.id}`)
}

onMounted(() => {
  loadMore()
  nextTick(() => {
    if (!sentinel.value) return
    observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) loadMore()
    }, { rootMargin: '600px' })
    observer.observe(sentinel.value)
  })
})

// keep-alive 缓存：从详情/mpv 返回时重刷角标与续播进度（限最近 600）
onActivated(() => {
  if (items.value.length) enrichStatus(items.value, lib.currentModule, 600)
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})

// 模块 / 关键词 / 维度筛选变化 → 重新加载
watch(filtersKey, () => reload())
</script>

<style scoped>
.cinema-loading-more {
  text-align: center;
  padding: 20px 0 8px;
  font-size: 12px;
  color: var(--text-3);
}
</style>
