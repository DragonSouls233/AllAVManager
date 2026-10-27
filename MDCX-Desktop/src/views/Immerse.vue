<template>
  <div class="immerse-root" @keydown="onKey" tabindex="0" ref="rootEl">
    <!-- 顶部条 -->
    <div class="immerse-top">
      <el-select v-model="module" size="small" style="width: 140px" @change="reset">
        <el-option v-for="m in modules" :key="m.key" :label="m.label" :value="m.key" />
      </el-select>
      <div class="counter">{{ index + 1 }} / {{ items.length }}<span v-if="hasMore">+</span></div>
      <el-button size="small" circle @click="close">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <!-- 主图区 -->
    <div class="immerse-stage" @click="onStageClick">
      <el-image
        v-if="current?.cover_url"
        :src="current.cover_url"
        fit="contain"
        class="immerse-cover"
        :preview-src-list="[]"
      >
        <template #error>
          <div class="no-cover">无封面</div>
        </template>
      </el-image>
      <div v-else class="no-cover">无封面</div>

      <!-- 左右导航热区 -->
      <div class="nav-zone left" @click.stop="prev"><el-icon><ArrowLeft /></el-icon></div>
      <div class="nav-zone right" @click.stop="next"><el-icon><ArrowRight /></el-icon></div>
    </div>

    <!-- 信息条 -->
    <div class="immerse-info">
      <div class="title">{{ current?.title || current?.code || '未知' }}</div>
      <div class="meta">
        <span v-if="current?.code" class="code">{{ current.code }}</span>
        <span v-if="current?.actor">{{ current.actor }}</span>
        <span v-if="current?.studio">{{ current.studio }}</span>
        <span v-if="current?.release_date">📅 {{ current.release_date }}</span>
        <span v-if="current?.rating">⭐ {{ current.rating }}</span>
      </div>
    </div>

    <!-- 底部操作 -->
    <div class="immerse-actions">
      <el-button :disabled="!current" @click="goDetail">
        <el-icon><Document /></el-icon> 详情
      </el-button>
      <el-button type="primary" :disabled="!current" @click="goPlay">
        <el-icon><VideoPlay /></el-icon> 播放
      </el-button>
      <el-button :disabled="!current || index === 0" @click="prev">
        <el-icon><ArrowLeft /></el-icon> 上一张
      </el-button>
      <el-button :disabled="!current" @click="next">
        下一张 <el-icon><ArrowRight /></el-icon>
      </el-button>
    </div>

    <div v-if="loadingMore" class="loading-more">加载更多…</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMovies } from '@/api'

const router = useRouter()
const route = useRoute()
const rootEl = ref(null)

const modules = [
  { key: 'jav', label: 'JAV 有码' }, { key: 'fc2', label: 'FC2' },
  { key: 'uncensored', label: 'JAV 无码' }, { key: 'chinese', label: '国产' },
  { key: 'western', label: '欧美' }, { key: 'pornhub', label: 'PORNHUB' },
  { key: 'anime', label: '里番' },
]

const module = ref(route.query.module || 'jav')
const items = ref([])
const index = ref(0)
const page = ref(1)
const page_size = 60
const hasMore = ref(true)
const loading = ref(false)
const loadingMore = ref(false)

const current = computed(() => items.value[index.value] || null)

async function fetchPage(reset = false) {
  if (reset) {
    page.value = 1
    items.value = []
    hasMore.value = true
    index.value = 0
  }
  if (!hasMore.value) return
  loadingMore.value = !reset ? true : false
  try {
    const res = await getMovies({ module: module.value, page: page.value, page_size })
    const list = (res.items || res.movies || [])
    if (list.length < page_size) hasMore.value = false
    items.value.push(...list)
    page.value += 1
  } catch (e) {
    ElMessage.error('加载失败')
  } finally {
    loadingMore.value = false
  }
}

function reset() {
  fetchPage(true)
}

function prev() {
  if (index.value > 0) index.value -= 1
}
function next() {
  if (index.value < items.value.length - 1) {
    index.value += 1
  } else if (hasMore.value) {
    fetchPage(false).then(() => { if (index.value < items.value.length - 1) index.value += 1 })
  }
}
function onStageClick() {
  // 点击主图区域的中线右侧=下一张，左侧=上一张（避免误触详情）
  next()
}
function goDetail() {
  if (!current.value) return
  router.push(`/${module.value}/movies/${current.value.id}`)
}
function goPlay() {
  if (!current.value) return
  router.push(`/play/${current.value.id}`)
}
function close() {
  router.back()
}
function onKey(e) {
  if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
  else if (e.key === 'Escape') close()
}

onMounted(() => {
  fetchPage(true)
  nextTick(() => rootEl.value?.focus())
})
onBeforeUnmount(() => {})
</script>

<style scoped>
.immerse-root {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: #0d0f14;
  display: flex;
  flex-direction: column;
  outline: none;
}
.immerse-top {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: rgba(255,255,255,0.04);
}
.counter { color: #cdd3e0; font-size: 13px; font-variant-numeric: tabular-nums; }
.immerse-stage {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: pointer;
}
.immerse-cover { max-width: 80%; max-height: 100%; }
.no-cover {
  color: #6b7280; font-size: 18px; display: flex; align-items: center; justify-content: center;
  width: 320px; height: 100%;
}
.nav-zone {
  position: absolute; top: 0; bottom: 0; width: 22%;
  display: flex; align-items: center; font-size: 40px; color: rgba(255,255,255,0.35);
}
.nav-zone.left { left: 0; justify-content: flex-start; padding-left: 16px; }
.nav-zone.right { right: 0; justify-content: flex-end; padding-right: 16px; }
.nav-zone:hover { color: rgba(255,255,255,0.85); background: rgba(255,255,255,0.04); }
.immerse-info { text-align: center; padding: 8px 16px; color: #e5e7eb; }
.immerse-info .title { font-size: 18px; font-weight: 600; }
.immerse-info .meta { margin-top: 6px; font-size: 13px; color: #9aa3b2; display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; }
.immerse-info .meta .code { color: #fbbf24; }
.immerse-actions { display: flex; gap: 10px; justify-content: center; padding: 10px 16px 16px; }
.loading-more { position: absolute; bottom: 70px; left: 50%; transform: translateX(-50%); color: #9aa3b2; font-size: 13px; }
</style>
