<template>
  <div class="tool-page">
    <!-- 页头：组名 + 说明 + 模块切换器 -->
    <header class="tp-head">
      <div class="tp-heading">
        <h1 class="tp-title">{{ group.label }}</h1>
        <p class="tp-desc">{{ group.desc }}</p>
      </div>
      <label class="tp-module">
        <span class="tp-module-label">当前模块</span>
        <el-select
          v-model="moduleSel"
          size="small"
          class="tp-module-select"
          placeholder="选择模块"
          aria-label="切换模块"
        >
          <el-option
            v-for="m in moduleOptions"
            :key="m.key"
            :label="`${m.emoji} ${m.label}`"
            :value="m.key"
          />
        </el-select>
      </label>
    </header>

    <div class="tp-body">
      <!-- 左：工具列表 -->
      <nav class="tp-list" aria-label="工具列表">
        <template v-for="(t, idx) in tools" :key="t.key">
          <div v-if="showSection(idx)" class="tp-section">{{ t.section }}</div>
          <button
            type="button"
            class="tp-item"
            :class="{ 'is-active': t.key === activeTool.key }"
            :aria-current="t.key === activeTool.key ? 'page' : undefined"
            @click="setTool(t.key)"
          >
            <span class="tp-item-label">{{ t.label }}</span>
            <span v-if="t.onlyModule" class="tp-item-badge">{{ labelOf(t.onlyModule) }} 专属</span>
          </button>
        </template>
      </nav>

      <!-- 右：动态工具内容 -->
      <section class="tp-content">
        <EmptyState
          v-if="!activeComponent"
          type="error"
          title="该工具暂不可用"
          description="组件映射缺失，请检查 src/config/toolComponents.js"
        />

        <EmptyState
          v-else-if="blocked"
          type="no-data"
          :title="`该工具仅适用于 ${labelOf(activeTool.onlyModule)}`"
          description="切换模块后即可使用"
        >
          <el-button size="small" type="primary" @click="setModule(activeTool.onlyModule)">
            切换过去
          </el-button>
        </EmptyState>

        <!--
          ⚠️ 刻意**不包** <Suspense>：
          异步组件用 `suspensible: false` + loadingComponent（ToolLoading）自管占位，
          Suspense 在这里既不会触发 fallback，还会因部分工具页是多根节点而报错。
          ⚠️ `:key="activeTool.key"` 强制重建，避免组内切换时筛选状态串味（坑 4）。
        -->
        <component
          :is="activeComponent"
          v-else
          :key="activeTool.key"
          v-bind="moduleProps"
        />
      </section>
    </div>
  </div>
</template>

<script setup>
/**
 * ToolPageShell —— 6 个工具组页共用的唯一实现
 *
 * 「URL 即状态」：`?module=` 选模块、`?tool=` 选工具，切换只 `router.replace`（不 push），
 * 刷新 / 分享 / 书签都能复原（ARCH-phase1 §8.2 / §10.2）。
 *
 * 契约：
 * - `groupKey` → 从 `TOOL_GROUPS` 取组（找不到回落第一组，不报错）；
 * - `activeTool`：非法 `?tool=` 回落 `tools[0]` 并归一化 URL；
 * - `currentModule`：非法 `?module=` → `localStorage['mdcx_tool_module']` → `'jav'`；
 * - `moduleProps`：**只有** `moduleAware === true` 才 `v-bind="{module}"`，
 *   否则会给不声明 props 的组件塞一个 `module="jav"` 的脏 DOM 属性（坑 13）。
 */
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { TOOL_GROUPS, MODULES } from '@/config/nav'
import { getComponent } from '@/config/toolComponents'
import { useShellStatsStore } from '@/stores/shellStats'
import EmptyState from '@/components/EmptyState.vue'

const props = defineProps({
  groupKey: { type: String, required: true },
})

const MODULE_STORAGE_KEY = 'mdcx_tool_module'

const route = useRoute()
const router = useRouter()
const shell = useShellStatsStore()

const group = computed(() => TOOL_GROUPS.find((g) => g.key === props.groupKey) || TOOL_GROUPS[0])
const tools = computed(() => group.value.tools || [])

const activeTool = computed(
  () => tools.value.find((t) => t.key === route.query.tool) || tools.value[0],
)

const moduleOptions = computed(() =>
  MODULES.filter((m) => m.toolEnabled && shell.enabled[m.flag] !== false),
)

const currentModule = computed(() => {
  const q = route.query.module
  if (q && MODULES.some((m) => m.key === q && m.toolEnabled)) return q
  let saved = ''
  try {
    saved = localStorage.getItem(MODULE_STORAGE_KEY) || ''
  } catch {
    saved = ''
  }
  if (saved && MODULES.some((m) => m.key === saved && m.toolEnabled)) return saved
  return 'jav'
})

const moduleProps = computed(() =>
  activeTool.value?.moduleAware ? { module: currentModule.value } : {},
)

const blocked = computed(
  () => !!activeTool.value?.onlyModule && activeTool.value.onlyModule !== currentModule.value,
)

const activeComponent = computed(() => getComponent(activeTool.value?.tool))

/** el-select 不支持 computed 直连，用可写代理 → setModule */
const moduleSel = computed({
  get: () => currentModule.value,
  set: (v) => setModule(v),
})

function labelOf(key) {
  const m = MODULES.find((x) => x.key === key)
  return m ? m.label : key || '未知'
}

function showSection(idx) {
  const t = tools.value[idx]
  if (!t || !t.section) return false
  const prev = tools.value[idx - 1]
  return !prev || prev.section !== t.section
}

/** 只改 ?tool=，不整页跳转（组页被 keep-alive 缓存，滚动位置保留） */
function setTool(key) {
  if (!key || key === route.query.tool) return
  router.replace({ path: route.path, query: { ...route.query, tool: key } }).catch(() => {})
}

/** 改 ?module= + 持久化偏好 */
function setModule(key) {
  if (!key) return
  try {
    localStorage.setItem(MODULE_STORAGE_KEY, key)
  } catch {
    // 隐私模式下不记忆
  }
  router.replace({ path: route.path, query: { ...route.query, module: key } }).catch(() => {})
}

/** 非法 ?tool= / ?module= 归一化（不报错、不白屏） */
function normalizeQuery() {
  const targetTool = activeTool.value?.key
  const targetModule = currentModule.value
  const q = { ...route.query }
  let dirty = false
  if (!q.tool || q.tool !== targetTool) {
    q.tool = targetTool
    dirty = true
  }
  if (!q.module || q.module !== targetModule) {
    q.module = targetModule
    dirty = true
  }
  if (dirty) {
    router.replace({ path: route.path, query: q }).catch(() => {})
  }
}

onMounted(normalizeQuery)
watch(() => route.query.tool, normalizeQuery)
watch(() => route.query.module, normalizeQuery)
</script>

<style scoped>
.tool-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  max-width: var(--content-max, 1440px);
  margin-inline: auto;
  min-width: 0;
}

/* ---------- 页头 ---------- */
.tp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.tp-heading {
  min-width: 0;
}

.tp-title {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.015em;
  line-height: 1.4;
  color: var(--text-primary);
}

.tp-desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.tp-module {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.tp-module-label {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.tp-module-select {
  width: 160px;
}

/* ---------- 主体 ---------- */
.tp-body {
  display: flex;
  align-items: flex-start;
  gap: 0;
  min-width: 0;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

/* ---------- 左栏工具列表 ---------- */
.tp-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 200px;
  flex-shrink: 0;
  padding: 8px;
  border-right: 1px solid var(--hairline, var(--border-color));
  align-self: stretch;
  box-sizing: border-box;
}

.tp-section {
  padding: 10px 8px 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-placeholder);
}

.tp-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  height: 36px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-ctl, 8px);
  background: transparent;
  font-family: inherit;
  font-size: 13.5px;
  color: var(--text-regular);
  text-align: left;
  cursor: pointer;
  position: relative;
  box-sizing: border-box;
  transition:
    background-color var(--dur-fast, 120ms),
    color var(--dur-fast, 120ms);
}

.tp-item:hover {
  background: var(--hover-layer);
}

.tp-item:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.tp-item.is-active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  font-weight: 600;
}

.tp-item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 2px;
  background: var(--accent);
}

.tp-item-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tp-item-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 400;
  color: var(--text-placeholder);
}

/* ---------- 右栏内容 ---------- */
.tp-content {
  flex: 1;
  min-width: 0;
  padding: 16px;
  box-sizing: border-box;
}

@media (max-width: 900px) {
  .tp-body {
    flex-direction: column;
  }
  .tp-list {
    width: 100%;
    border-right: 0;
    border-bottom: 1px solid var(--border-color);
    flex-direction: row;
    flex-wrap: wrap;
  }
  .tp-item {
    width: auto;
  }
  .tp-section {
    width: 100%;
  }
}
</style>
