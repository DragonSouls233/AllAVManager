<template>
  <div class="cinema-root">

    <!-- ===== 顶栏 ===== -->
    <header class="cinema-topbar">
      <div class="cinema-brand">
        <div class="cinema-brand-mark">
          <el-icon :size="17"><VideoCamera /></el-icon>
        </div>
        <div class="cinema-brand-text">
          <span class="cinema-brand-title">MDCX</span>
          <span class="cinema-brand-sub">Player</span>
        </div>
      </div>

      <!-- 模块切换器 -->
      <el-select
        v-model="moduleKey"
        size="small"
        style="width: 132px"
        @change="onModuleChange"
        aria-label="切换模块"
      >
        <el-option label="全部模块" value="" />
        <el-option v-for="m in availableModules" :key="m.key" :label="m.label" :value="m.key" />
      </el-select>

      <!-- 全局搜索 -->
      <div class="cinema-search">
        <el-input
          v-model="searchInput"
          placeholder="搜索番号 / 标题 / 演员…"
          clearable
          size="small"
          @keyup.enter="onSearch"
          @clear="onSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>

      <div class="cinema-topbar-right">
        <el-tooltip :content="nsfwEnabled ? 'NSFW 已开启' : 'NSFW 已隐藏'" placement="bottom">
          <el-button text class="cinema-icon-btn" @click="toggleNsfw" :aria-pressed="nsfwEnabled">
            <el-icon :size="17"><View v-if="nsfwEnabled" /><Hide v-else /></el-icon>
          </el-button>
        </el-tooltip>
        <el-tooltip content="设置" placement="bottom">
          <el-button text class="cinema-icon-btn" @click="go('/settings')" aria-label="设置">
            <el-icon :size="17"><Setting /></el-icon>
          </el-button>
        </el-tooltip>
        <el-tooltip content="连接状态" placement="bottom">
          <el-button text class="cinema-icon-btn" @click="refresh" aria-label="刷新">
            <el-icon :size="17"><Refresh /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
    </header>

    <!-- ===== 主体 ===== -->
    <div class="cinema-body">
      <nav class="cinema-rail" aria-label="主导航">
        <div
          v-for="item in navItems"
          :key="item.path"
          class="cinema-rail-item"
          :class="{ active: isActive(item) }"
          :title="item.label"
          role="link"
          tabindex="0"
          @click="go(item.path)"
          @keyup.enter="go(item.path)"
        >
          <el-icon :size="19"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </div>
        <div class="cinema-rail-spacer" />
        <ConnectionDot />
      </nav>

      <main class="cinema-stage cinema-main" role="main">
        <router-view v-slot="{ Component }">
          <transition name="cinema-fade" mode="out-in">
            <keep-alive :max="6">
              <component :is="Component" :key="$route.name" />
            </keep-alive>
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  VideoCamera, Film, PriceTag, Collection, User, Star,
  Setting, Refresh, Search, View, Hide
} from '@element-plus/icons-vue'
import ConnectionDot from '@/components/cinema/ConnectionDot.vue'
import { useLibraryStore } from '@/stores/library'

const route = useRoute()
const router = useRouter()
const lib = useLibraryStore()

const availableModules = computed(() => lib.availableModules)
const moduleKey = ref(lib.currentModule)
const searchInput = ref(lib.keyword)

const navItems = [
  { path: '/library', label: '影片库', icon: Film, match: ['Library'] },
  { path: '/categories', label: '类别', icon: PriceTag, match: ['Categories'] },
  { path: '/series', label: '系列', icon: Collection, match: ['Series'] },
  { path: '/actors', label: '演员', icon: User, match: ['Actors', 'ActorWorks'] },
  { path: '/favorites', label: '喜好', icon: Star, match: ['Favorites'] }
]

function isActive(item) {
  return item.match.includes(route.name) || route.path.startsWith(item.path)
}

function go(path) {
  if (route.path !== path) router.push(path)
}

function onModuleChange(val) {
  lib.setModule(val)
  // 切模块后回到影片库，避免停留在已失效的类别/系列上下文
  if (!['Library'].includes(route.name)) router.push('/library')
}

function onSearch() {
  lib.setKeyword(searchInput.value.trim())
  if (route.name !== 'Library') router.push('/library')
}

// NSFW：本地状态 + 全局 data 属性驱动 CSS（与 Web 端同一套机制）
const nsfwEnabled = ref(localStorage.getItem('mdcx_nsfw') !== '0')
function applyNsfw() {
  const root = document.documentElement
  root.setAttribute('data-nsfw', nsfwEnabled.value ? 'off' : 'on')
  root.setAttribute('data-nsfw-hide-cover', nsfwEnabled.value ? '0' : '1')
  root.setAttribute('data-nsfw-blur', nsfwEnabled.value ? '0' : '18')
}
function toggleNsfw() {
  nsfwEnabled.value = !nsfwEnabled.value
  localStorage.setItem('mdcx_nsfw', nsfwEnabled.value ? '1' : '0')
  applyNsfw()
}

function refresh() {
  window.location.reload()
}

onMounted(() => {
  applyNsfw()
  lib.loadModules()
  moduleKey.value = lib.currentModule
  searchInput.value = lib.keyword
  // 与外部（顶栏搜索、模块切换）保持同步
  window.addEventListener('mdcx-library-sync', () => {
    moduleKey.value = lib.currentModule
    searchInput.value = lib.keyword
  })
})
</script>

<style scoped>
.cinema-root {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--titlebar-h, 0px));
  overflow: hidden;
  background: var(--cinema-0);
}

.cinema-fade-enter-active,
.cinema-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.cinema-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.cinema-fade-leave-to {
  opacity: 0;
}

/* 顶栏下拉在暗色下的适配 */
.cinema-topbar :deep(.el-select__wrapper) {
  background: var(--cinema-2) !important;
  box-shadow: 0 0 0 1px var(--cinema-line) inset !important;
  border-radius: 8px;
  min-height: 32px;
}

.cinema-topbar :deep(.el-select__placeholder) {
  color: var(--text-2);
  font-size: 12.5px;
}
</style>
