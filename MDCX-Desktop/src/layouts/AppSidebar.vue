<template>
  <aside
    class="sidebar"
    :class="{ 'is-collapsed': modelValue }"
    id="main-sidebar"
    role="navigation"
    aria-label="主导航"
  >
    <!-- 品牌区（56px）：32×32 accent 方块 + MDCX + 副标题 -->
    <div class="logo-area">
      <div class="logo-icon" aria-hidden="true">
        <el-icon :size="18"><VideoCamera /></el-icon>
      </div>
      <transition name="fade">
        <div v-show="!modelValue" class="logo-text">
          <h2>MDCX</h2>
          <span>视频管理系统</span>
        </div>
      </transition>
    </div>

    <!-- 菜单（flex:1 + 兜底滚动） -->
    <nav class="sidebar-menu">
      <router-link
        to="/"
        class="nav-item nav-item--home"
        :class="{ 'is-active': activeKey === 'home' }"
        :title="modelValue ? '首页' : undefined"
        :aria-label="modelValue ? '首页' : undefined"
      >
        <el-icon :size="16"><component :is="'HomeFilled'" /></el-icon>
        <span v-if="!modelValue" class="nav-label">首页</span>
      </router-link>

      <NavGroup
        v-for="group in groups"
        :key="group.key"
        :item="group"
        :collapsed="modelValue"
        :open="openKeys.has(group.key)"
        :active-key="activeKey"
        @toggle="toggleGroup(group.key)"
      />
    </nav>

    <SidebarStatus :collapsed="modelValue" @open-changelog="$emit('open-changelog')" />
  </aside>
</template>

<script setup>
/**
 * AppSidebar —— 浅色侧栏（手风琴）
 *
 * 决策（已拍板）：
 * - **手风琴**：同时只展开一组，与旧 `el-menu :unique-opened="true"` 行为一致；
 * - 浅色 `#FBFBFC` + 1px 右边框，无渐变、无阴影；
 * - 展开组持久化在 `localStorage['mdcx_nav_open']`（只存一个 key）；
 * - 折叠 64px 时二级项走 popover（见 NavGroup）。
 *
 * ⚠️ 本组件只被 `AdminLayout.vue` 引用；桌面外壳是 `CinemaLayout.vue`，不受影响。
 */
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NAV, resolveActiveKey } from '@/config/nav'
import NavGroup from '@/components/shell/NavGroup.vue'
import SidebarStatus from '@/components/shell/SidebarStatus.vue'

const props = defineProps({
  /** 折叠态（true = 64px） */
  modelValue: { type: Boolean, default: false },
})

defineEmits(['update:modelValue', 'open-changelog'])

// props 仅用于模板（modelValue）；此处显式引用一次，避免打包/Lint 误判为未使用
void props

const STORAGE_KEY = 'mdcx_nav_open'
const route = useRoute()

/** 4 个可折叠组（首页是独立 link，不参与手风琴） */
const groups = computed(() => NAV.filter((n) => n.kind === 'group'))

const activeKey = computed(() => resolveActiveKey(route.path, route.query))

// ---------- 手风琴状态 ----------
function readStoredKey() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && groups.value.some((g) => g.key === saved)) return saved
  } catch {
    // localStorage 不可用（隐私模式）→ 默认全关
  }
  return ''
}

/** @type {import('vue').Ref<Set<string>>} */
const openKeys = ref(new Set(readStoredKey() ? [readStoredKey()] : []))

function persist() {
  try {
    const first = openKeys.value.values().next()
    localStorage.setItem(STORAGE_KEY, first && !first.done ? first.value : '')
  } catch {
    // 忽略
  }
}

/** 手风琴：开新组必关其它组 */
function toggleGroup(key) {
  const next = new Set()
  if (!openKeys.value.has(key)) next.add(key)
  openKeys.value = next
  persist()
}

function openGroupOf(key) {
  if (!key) return
  for (const g of groups.value) {
    if ((g.children || []).some((c) => c && !c.divider && c.key === key)) {
      if (!openKeys.value.has(g.key)) {
        openKeys.value = new Set([g.key])
        persist()
      }
      return
    }
  }
}

// 首次渲染按当前路由展开所在组
openGroupOf(activeKey.value)

// 路由变化（含命令面板跳转、旧路径进入）→ 展开命中的组
watch(activeKey, (key) => openGroupOf(key))
</script>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-w, 240px);
  flex-shrink: 0;
  height: 100%;
  background: var(--sidebar-bg, #fbfbfc);
  border-right: 1px solid var(--border-color);
  overflow: hidden;
  transition: width var(--dur-base, 200ms) var(--ease-out-nav, ease-out);
}

.sidebar.is-collapsed {
  width: var(--sidebar-w-collapsed, 64px);
}

:global(html.dark) .sidebar {
  background: var(--sidebar-bg);
}

/* ---------- 品牌区 ---------- */
.logo-area {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 56px;
  padding: 0 14px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border-light);
  box-sizing: border-box;
}

.sidebar.is-collapsed .logo-area {
  justify-content: center;
  padding: 0;
}

.logo-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 9px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 82%, #fff), var(--accent));
  color: #fff;
  box-shadow: 0 2px 8px -3px color-mix(in srgb, var(--accent) 70%, transparent);
}

.logo-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  line-height: 1.2;
}

.logo-text h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text-primary);
}

.logo-text span {
  font-size: 11px;
  color: var(--text-placeholder);
  white-space: nowrap;
}

/* ---------- 菜单容器 ---------- */
.sidebar-menu {
  flex: 1;
  min-height: 0;
  padding: 8px 0;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
}

.sidebar-menu::-webkit-scrollbar {
  width: 6px;
}

.sidebar-menu::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

/* ---------- 行（与 NavGroup 同一套视觉） ---------- */
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: calc(100% - 16px);
  margin: 2px 8px;
  padding: 0 10px;
  height: var(--nav-item-h, 36px);
  border: 0;
  border-radius: var(--radius-ctl, 8px);
  background: transparent;
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-regular);
  text-decoration: none;
  cursor: pointer;
  position: relative;
  box-sizing: border-box;
  transition:
    background-color var(--dur-fast, 120ms),
    color var(--dur-fast, 120ms);
}

.nav-item:hover {
  background: var(--hover-layer);
}

.nav-item:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.nav-item.is-active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  font-weight: 600;
}

.nav-item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 2px;
  background: var(--accent);
}

.nav-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar.is-collapsed .nav-item--home {
  width: 40px;
  height: 40px;
  margin: 2px auto;
  padding: 0;
  justify-content: center;
  gap: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--dur-fast, 120ms);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
