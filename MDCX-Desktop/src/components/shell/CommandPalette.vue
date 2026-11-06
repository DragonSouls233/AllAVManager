<template>
  <teleport to="body">
    <transition name="cp-fade">
      <div
        v-if="modelValue"
        class="cp-mask"
        @mousedown.self="close"
        @keydown.tab.prevent
      >
        <div
          ref="panelRef"
          class="cp-panel"
          role="dialog"
          aria-modal="true"
          aria-label="命令面板"
        >
          <!-- 输入区 -->
          <div class="cp-input-row">
            <el-icon class="cp-icon" :size="16"><Search /></el-icon>
            <input
              ref="inputRef"
              v-model="keyword"
              class="cp-input"
              type="text"
              placeholder="搜索页面、影片、演员…（↑↓ 选择，Enter 打开，Esc 关闭）"
              role="combobox"
              aria-expanded="true"
              aria-controls="cp-listbox"
              :aria-activedescendant="activeId"
              @keydown="onKeydown"
            />
            <kbd class="cp-esc">Esc</kbd>
          </div>

          <!-- 结果 -->
          <div id="cp-listbox" class="cp-body" role="listbox">
            <div v-if="loadingContent" class="cp-loading">
              <el-icon class="cp-spin" :size="13"><Loading /></el-icon> 搜索中…
            </div>

            <template v-for="group in groups" :key="group.key">
              <div class="cp-group-title">{{ group.title }}</div>
              <button
                v-for="item in group.items"
                :id="`cp-opt-${item.uid}`"
                :key="item.uid"
                type="button"
                role="option"
                class="cp-item"
                :class="{ 'is-active': flatItems[activeIndex]?.uid === item.uid }"
                :aria-selected="flatItems[activeIndex]?.uid === item.uid"
                @mouseenter="activeIndex = indexOfUid(item.uid)"
                @click="run(item)"
              >
                <el-icon v-if="item.icon" class="cp-item-icon" :size="15">
                  <component :is="item.icon" />
                </el-icon>
                <el-icon v-else class="cp-item-icon" :size="15"><Document /></el-icon>
                <span class="cp-item-label">{{ item.label }}</span>
                <span v-if="item.hint" class="cp-item-hint">{{ item.hint }}</span>
              </button>
            </template>

            <div v-if="!groups.length && !loadingContent" class="cp-empty">
              <template v-if="keyword.trim().length >= 2">没有匹配结果</template>
              <template v-else>输入关键词开始搜索</template>
            </div>
          </div>

          <div class="cp-footer">
            <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
            <span><kbd>Enter</kbd> 打开</span>
            <span><kbd>Esc</kbd> 关闭</span>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup>
/**
 * CommandPalette —— ⌘K / Ctrl+K 命令面板
 *
 * 能力（ARCH-phase1 §7.5）：
 * 1. 页面组：`flattenNav()` 模糊匹配（≤6）
 * 2. 内容组：`unifiedSearch()`（≥2 字、350ms 防抖、≤8）
 * 3. 空关键词：「最近访问 5 条」+「常用工具 6 条」
 *
 * 纪律：
 * - `unifiedSearch` 抛错 → 静默，只渲染页面组（不弹 ElMessage）；
 * - 关闭后焦点还原到打开前的元素；
 * - hash 路由：一律 `router.push({ path, query })`，不用裸 href。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Loading, Document } from '@element-plus/icons-vue'
import { flattenNav, TOOL_GROUPS } from '@/config/nav'
import { unifiedSearch } from '@/api/modules'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const RECENT_KEY = 'mdcx_cmd_recent'
const MAX_PAGE = 6
const MAX_CONTENT = 8

const router = useRouter()
const keyword = ref('')
const inputRef = ref(null)
const panelRef = ref(null)
const activeIndex = ref(0)
const pageResults = ref([])
const contentResults = ref([])
const recent = ref([])
const loadingContent = ref(false)

let debounceTimer = null
let requestSeq = 0
let restoreFocusEl = null

// ---------- 扁平页面表（只算一次） ----------
const FLAT_NAV = flattenNav()

/** 常用工具 6 条：跨组分取前 6 个工具（每工具一个直达路径） */
const COMMON_TOOLS = (() => {
  const out = []
  for (const g of TOOL_GROUPS) {
    if (g.tools.length === 0) continue
    const t = g.tools[0]
    out.push({
      uid: `common-${g.key}`,
      key: t.key,
      label: t.label,
      hint: g.label,
      icon: g.icon,
      to: `${g.to}?tool=${t.key}&module=jav`,
    })
    if (out.length >= 6) break
  }
  return out
})()

// ---------- 最近访问 ----------
function readRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const list = JSON.parse(raw)
    if (!Array.isArray(list)) return []
    return list
      .filter((x) => x && typeof x.to === 'string')
      .slice(0, 5)
      .map((x, i) => ({ uid: `recent-${i}`, label: x.label, hint: x.hint || '', icon: x.icon || 'Clock', to: x.to }))
  } catch {
    return []
  }
}

function pushRecent(item) {
  if (!item || !item.to) return
  try {
    const list = readRecentRaw()
    const filtered = list.filter((x) => x.to !== item.to)
    filtered.unshift({ label: item.label, hint: item.hint || '', icon: item.icon || '', to: item.to })
    localStorage.setItem(RECENT_KEY, JSON.stringify(filtered.slice(0, 5)))
  } catch {
    // localStorage 不可用时不记忆
  }
}

function readRecentRaw() {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list.filter((x) => x && typeof x.to === 'string') : []
  } catch {
    return []
  }
}

// ---------- 分组 ----------
const groups = computed(() => {
  const kw = keyword.value.trim()
  if (kw.length === 0) {
    const out = []
    if (recent.value.length) out.push({ key: 'recent', title: '最近访问', items: recent.value })
    if (COMMON_TOOLS.length) out.push({ key: 'common', title: '常用工具', items: COMMON_TOOLS })
    return out
  }
  const out = []
  if (pageResults.value.length) out.push({ key: 'page', title: '页面', items: pageResults.value })
  if (contentResults.value.length) out.push({ key: 'content', title: '内容', items: contentResults.value })
  return out
})

const flatItems = computed(() => groups.value.flatMap((g) => g.items))

const activeId = computed(() => {
  const it = flatItems.value[activeIndex.value]
  return it ? `cp-opt-${it.uid}` : undefined
})

function indexOfUid(uid) {
  const i = flatItems.value.findIndex((x) => x.uid === uid)
  return i < 0 ? 0 : i
}

// ---------- 搜索 ----------
function matchPages(kw) {
  const q = kw.toLowerCase()
  const scored = []
  for (const item of FLAT_NAV) {
    const hay = `${item.groupLabel} ${item.label} ${item.desc} ${(item.legacy || []).join(' ')}`.toLowerCase()
    const label = item.label.toLowerCase()
    if (!hay.includes(q)) continue
    // 前缀命中优先
    let score = 0
    if (label === q) score = 3
    else if (label.startsWith(q)) score = 2
    else if (label.includes(q)) score = 1
    scored.push({ item, score })
  }
  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, MAX_PAGE).map(({ item }, i) => ({
    uid: `page-${item.key}-${i}`,
    key: item.key,
    label: item.label,
    hint: item.groupLabel,
    icon: item.icon,
    to: item.to,
  }))
}

function scheduleSearch() {
  if (debounceTimer) window.clearTimeout(debounceTimer)
  const kw = keyword.value.trim()

  if (kw.length < 2) {
    pageResults.value = kw.length >= 1 ? matchPages(kw) : []
    contentResults.value = []
    loadingContent.value = false
    activeIndex.value = 0
    return
  }

  pageResults.value = matchPages(kw)
  activeIndex.value = 0

  debounceTimer = window.setTimeout(async () => {
    const seq = ++requestSeq
    loadingContent.value = true
    try {
      const res = await unifiedSearch(kw)
      if (seq !== requestSeq) return
      const items = (res && res.items) || []
      contentResults.value = items.slice(0, MAX_CONTENT).map((r, i) => ({
        uid: `content-${r.module_name || 'x'}-${r.id}-${i}`,
        key: `c-${i}`,
        label: r.title || r.code || '未命名',
        hint: r.code || '',
        icon: 'Film',
        to: `/${r.module_name}/movies/${r.id}`,
      }))
    } catch (e) {
      // 静默：只渲染页面组，不弹 ElMessage
      if (seq === requestSeq) contentResults.value = []
    } finally {
      if (seq === requestSeq) loadingContent.value = false
    }
  }, 350)
}

watch(keyword, () => scheduleSearch())

// ---------- 打开 / 关闭 ----------
function open() {
  if (props.modelValue) return
  restoreFocusEl = document.activeElement
  recent.value = readRecent()
  emit('update:modelValue', true)
  nextTick(() => {
    inputRef.value?.focus()
  })
}

function close() {
  if (!props.modelValue) return
  emit('update:modelValue', false)
  keyword.value = ''
  pageResults.value = []
  contentResults.value = []
  activeIndex.value = 0
  if (debounceTimer) window.clearTimeout(debounceTimer)
  const el = restoreFocusEl
  restoreFocusEl = null
  nextTick(() => {
    if (el && typeof el.focus === 'function') el.focus()
  })
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      recent.value = readRecent()
      nextTick(() => inputRef.value?.focus())
    }
  },
)

// ---------- 键盘 ----------
function onKeydown(e) {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (!flatItems.value.length) return
    activeIndex.value = (activeIndex.value + 1) % flatItems.value.length
    scrollActiveIntoView()
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (!flatItems.value.length) return
    activeIndex.value = (activeIndex.value - 1 + flatItems.value.length) % flatItems.value.length
    scrollActiveIntoView()
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    const item = flatItems.value[activeIndex.value]
    if (item) run(item)
  }
}

function scrollActiveIntoView() {
  nextTick(() => {
    const id = activeId.value
    if (!id) return
    const el = document.getElementById(id)
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest' })
    }
  })
}

// ---------- 执行 ----------
function run(item) {
  if (!item) return
  pushRecent(item)
  close()
  if (item.to) {
    router.push(item.to).catch(() => {})
  }
}

// ---------- 全局快捷键 ----------
function isTypingTarget(el) {
  if (!el || !el.tagName) return false
  const tag = el.tagName.toUpperCase()
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return el.isContentEditable === true
}

function onGlobalKeydown(e) {
  // Ctrl/Cmd + K：任何位置都生效（输入框内也拦截，这是全局命令面板的惯例）
  if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    if (props.modelValue) close()
    else open()
    return
  }
  // 单独 `/`：仅非输入状态下触发
  if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (props.modelValue) return
    if (isTypingTarget(document.activeElement)) return
    e.preventDefault()
    open()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  recent.value = readRecent()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  if (debounceTimer) window.clearTimeout(debounceTimer)
})
</script>

<style scoped>
.cp-mask {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal, 1040);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 12vh;
  background: rgba(15, 18, 26, 0.38);
}

.cp-panel {
  display: flex;
  flex-direction: column;
  width: min(640px, calc(100vw - 32px));
  max-height: min(560px, 70vh);
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg, 16px);
  box-shadow: 0 24px 64px rgba(15, 18, 26, 0.22);
  overflow: hidden;
}

/* ---------- 输入 ---------- */
.cp-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  height: 52px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border-light);
}

/* input 自身 outline:none 是刻意的（避免双框），焦点环由外框承接，
   保证 Ctrl+K 之后键盘用户仍能看见焦点位置（WCAG 2.4.7）。
   ⚠️ 必须用 **inset**：`.cp-panel` 有 overflow:hidden + 16px 圆角，
   而 --focus-ring 是 outset 外发光，会被祖级裁掉（只剩底边一条缝），
   等于白做。inset 画在盒子内部，overflow 管不着。 */
.cp-input-row:focus-within {
  /* 第一行是给不支持 color-mix 的引擎的退路（后者覆盖前者） */
  box-shadow: inset 0 0 0 2px var(--accent);
  box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--accent) 45%, transparent);
  border-radius: var(--radius-lg, 16px) var(--radius-lg, 16px) 0 0;
}

.cp-icon {
  color: var(--text-placeholder);
  flex-shrink: 0;
}

.cp-input {
  flex: 1;
  min-width: 0;
  height: 100%;
  border: 0;
  outline: none;
  background: transparent;
  font-family: inherit;
  font-size: 15px;
  color: var(--text-primary);
}

.cp-input::placeholder {
  color: var(--text-placeholder);
}

.cp-esc {
  flex-shrink: 0;
  padding: 1px 5px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-family: inherit;
  font-size: 11px;
  color: var(--text-placeholder);
}

/* ---------- 结果 ---------- */
.cp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
  scrollbar-width: thin;
}

.cp-group-title {
  padding: 8px 8px 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-placeholder);
}

.cp-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 38px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-ctl, 8px);
  background: transparent;
  font-family: inherit;
  font-size: 14px;
  color: var(--text-regular);
  text-align: left;
  cursor: pointer;
  box-sizing: border-box;
}

.cp-item.is-active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
}

.cp-item-icon {
  flex-shrink: 0;
  color: var(--text-placeholder);
}

.cp-item.is-active .cp-item-icon {
  color: var(--accent);
}

.cp-item-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cp-item-hint {
  flex-shrink: 0;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-placeholder);
  font-variant-numeric: tabular-nums;
}

.cp-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  font-size: 12px;
  color: var(--text-placeholder);
}

.cp-spin {
  animation: cp-rotating 1.2s linear infinite;
}

.cp-empty {
  padding: 32px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--text-placeholder);
}

/* ---------- 底部提示 ---------- */
.cp-footer {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
  height: 34px;
  padding: 0 16px;
  border-top: 1px solid var(--border-light);
  background: var(--bg-page);
  font-size: 11px;
  color: var(--text-placeholder);
}

.cp-footer kbd {
  display: inline-block;
  min-width: 14px;
  padding: 0 3px;
  margin-right: 3px;
  border: 1px solid var(--border-color);
  border-radius: 3px;
  background: var(--bg-card);
  font-family: inherit;
  font-size: 10px;
  text-align: center;
}

/* ---------- 过渡 ---------- */
.cp-fade-enter-active,
.cp-fade-leave-active {
  transition: opacity var(--dur-fast, 120ms);
}

.cp-fade-enter-from,
.cp-fade-leave-to {
  opacity: 0;
}

@keyframes cp-rotating {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}
</style>
