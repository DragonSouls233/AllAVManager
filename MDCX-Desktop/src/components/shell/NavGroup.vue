<template>
  <!-- ======================= 折叠态：图标 + 右侧浮出面板 ======================= -->
  <div v-if="collapsed" class="nav-collapsed-wrap">
    <el-popover
      placement="right-start"
      :width="200"
      trigger="click"
      :show-arrow="false"
      :offset="8"
      popper-class="nav-flyout"
    >
      <template #reference>
        <button
          type="button"
          class="nav-item nav-item--icon"
          :class="{ 'is-active': hasActive }"
          :aria-label="item.label"
          :title="item.label"
        >
          <el-icon :size="16"><component :is="item.icon" /></el-icon>
        </button>
      </template>
      <div class="nf-title">{{ item.label }}</div>
      <template v-for="(child, idx) in visibleChildren" :key="child.divider ? `d-${idx}` : child.key">
        <div v-if="child.divider" class="nf-divider" />
        <router-link
          v-else
          :to="child.to"
          class="nf-item"
          :class="{ 'is-active': activeKey === child.key }"
        >
          <span class="nf-label">
            <span v-if="child.emoji" class="nf-emoji">{{ child.emoji }}</span>
            {{ child.label }}
          </span>
          <span v-if="countOf(child)" class="nf-count">{{ formatCount(countOf(child)) }}</span>
        </router-link>
      </template>
    </el-popover>
  </div>

  <!-- ======================= 展开态：可折叠组 ======================= -->
  <div v-else class="nav-group">
    <button
      type="button"
      class="nav-item nav-item--group"
      :class="{ 'is-open': open, 'is-active': hasActive && !open }"
      :aria-expanded="open"
      :aria-controls="childrenId"
      @click="$emit('toggle')"
    >
      <el-icon class="nav-icon" :size="16"><component :is="item.icon" /></el-icon>
      <span class="nav-label">{{ item.label }}</span>
      <el-icon class="nav-arrow" :class="{ 'is-open': open }" :size="12"><ArrowRight /></el-icon>
    </button>

    <el-collapse-transition>
      <div v-show="open" :id="childrenId" class="nav-children" :class="{ 'is-scroll': scrollable }">
        <template v-for="(child, idx) in visibleChildren" :key="child.divider ? `d-${idx}` : child.key">
          <div v-if="child.divider" class="nav-divider" />
          <router-link
            v-else
            :to="child.to"
            class="nav-item nav-item--sub"
            :class="{ 'is-active': activeKey === child.key }"
          >
            <span class="nav-sub-label">
              <span v-if="child.emoji" class="nav-emoji">{{ child.emoji }}</span>
              <el-icon v-else-if="child.icon" class="nav-sub-icon" :size="14">
                <component :is="child.icon" />
              </el-icon>
              {{ child.label }}
            </span>
            <span v-if="countOf(child)" class="nav-count">{{ formatCount(countOf(child)) }}</span>
          </router-link>
        </template>
      </div>
    </el-collapse-transition>
  </div>
</template>

<script setup>
/**
 * NavGroup —— 侧栏一级组 + 二级项
 *
 * 设计要点（ARCH-phase1 §7.2 / §11-1）：
 * - 展开态用 `el-collapse-transition`，只做 height 动画，不 `transition: all`；
 * - 设置组 15 项必然超高 → `is-scroll` 组内滚动（`--nav-scroll-max`）；
 * - 折叠态二级项走 `el-popover placement="right-start"`，不给 64px 硬塞文字；
 * - 选中态与侧栏同一套（10% accent 底 + 2px 竖条），由 `.nav-item.is-active` 统一提供。
 */
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useShellStatsStore } from '@/stores/shellStats'

const props = defineProps({
  /** NAV 里的一级组 */
  item: { type: Object, required: true },
  /** 侧栏折叠态 */
  collapsed: { type: Boolean, default: false },
  /** 是否展开 */
  open: { type: Boolean, default: false },
  /** 当前选中的二级项 key */
  activeKey: { type: String, default: '' },
})

defineEmits(['toggle'])

const shell = useShellStatsStore()
const { moduleMovies } = storeToRefs(shell)

const childrenId = computed(() => `navg-${props.item.key}`)

/** 模块被停用时整项不渲染（沿用旧 AdminLayout 的 moduleEnabled 逻辑） */
const visibleChildren = computed(() =>
  (props.item.children || []).filter((c) => {
    if (!c) return false
    if (c.divider) return true
    if (c.moduleFlag && shell.enabled[c.moduleFlag] === false) return false
    return true
  }),
)

const hasActive = computed(() =>
  visibleChildren.value.some((c) => c && !c.divider && c.key === props.activeKey),
)

/** 设置组 15 项需要组内滚动（可用高约 740px，15×32=480 其实够，
 *  但用户可能同时看到媒体库展开后的记忆位置；统一给 8 项以上加滚动上限最稳） */
const scrollable = computed(() => visibleChildren.value.filter((c) => !c.divider).length > 10)

/** 只给「模块」行显示影片数（countKey === 'movies'） */
function countOf(child) {
  if (!child || child.divider) return 0
  if (child.countKey !== 'movies') return 0
  return moduleMovies.value[child.key] || 0
}

function formatCount(n) {
  if (!n) return ''
  if (n >= 10000) return `${(n / 10000).toFixed(1)}w`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}
</script>

<style scoped>
/* ---------- 行（展开态） ---------- */
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
  line-height: 1;
  color: var(--text-regular);
  text-align: left;
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

.nav-arrow {
  flex-shrink: 0;
  color: var(--text-placeholder);
  transition: transform var(--dur-base, 200ms) var(--ease-out-nav, ease-out);
}

.nav-arrow.is-open {
  transform: rotate(90deg);
}

/* ---------- 二级项 ---------- */
.nav-children {
  padding-bottom: 4px;
}

.nav-children.is-scroll {
  max-height: calc(100vh - 360px);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.nav-item--sub {
  height: var(--nav-subitem-h, 32px);
  padding-left: 34px;
  font-size: 13.5px;
  font-weight: 400;
}

.nav-sub-label {
  flex: 1;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-sub-icon {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.nav-emoji {
  flex-shrink: 0;
  font-size: 13px;
  line-height: 1;
}

.nav-count {
  flex-shrink: 0;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--text-placeholder);
}

.nav-item.is-active .nav-count {
  color: var(--accent);
}

.nav-divider {
  height: 1px;
  margin: 6px 16px;
  background: var(--border-light);
}

/* ---------- 折叠态 ---------- */
.nav-collapsed-wrap {
  padding: 2px 0;
}

.nav-item--icon {
  width: 40px;
  height: 40px;
  margin: 2px auto;
  padding: 0;
  justify-content: center;
  gap: 0;
}

.nav-item--icon.is-active::before {
  top: 10px;
  bottom: 10px;
}
</style>

<!--
  ⚠️ 折叠态的浮出面板由 el-popover 渲染，默认 teleport 到 body，
  因此 scoped 样式作用不到它 —— 这段必须是**全局**样式，用 `.nav-flyout` 前缀命名空间隔离。
-->
<style>
.nav-flyout {
  padding: 6px;
  border-radius: var(--radius-card, 10px) !important;
}

.nav-flyout .nf-title {
  padding: 2px 4px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-placeholder);
}

.nav-flyout .nf-item {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 8px;
  border-radius: var(--radius-ctl, 8px);
  font-size: 13px;
  color: var(--text-regular);
  text-decoration: none;
  transition:
    background-color var(--dur-fast, 120ms),
    color var(--dur-fast, 120ms);
}

.nav-flyout .nf-item:hover {
  background: var(--hover-layer);
}

.nav-flyout .nf-item.is-active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  font-weight: 600;
}

.nav-flyout .nf-label {
  flex: 1;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-flyout .nf-emoji {
  flex-shrink: 0;
  font-size: 13px;
  line-height: 1;
}

.nav-flyout .nf-count {
  flex-shrink: 0;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--text-placeholder);
}

.nav-flyout .nf-item.is-active .nf-count {
  color: var(--accent);
}

.nav-flyout .nf-divider {
  height: 1px;
  margin: 6px 4px;
  background: var(--border-light);
}
</style>
