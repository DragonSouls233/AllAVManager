<template>
  <header class="topbar">
    <!-- 左：折叠 + 面包屑 -->
    <div class="topbar-left">
      <button
        type="button"
        class="icon-btn touch-target"
        :aria-label="collapsed ? '展开侧边栏' : '折叠侧边栏'"
        :aria-expanded="!collapsed"
        aria-controls="main-sidebar"
        @click="$emit('update:collapsed', !collapsed)"
      >
        <el-icon :size="18"><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
      </button>
      <PageBreadcrumb class="topbar-crumb" />
    </div>

    <!-- 右：搜索 / 任务 / NSFW / 主题 / 撤销 / 用户 -->
    <div class="topbar-right">
      <!-- 搜索入口（只做触发器，面板是 CommandPalette） -->
      <button type="button" class="search-trigger" aria-label="搜索（Ctrl+K）" @click="$emit('open-search')">
        <el-icon :size="15"><Search /></el-icon>
        <span class="search-placeholder">搜索页面、影片、演员…</span>
        <kbd class="search-kbd">Ctrl K</kbd>
      </button>

      <!-- 任务胶囊 -->
      <button
        v-if="shell.runningTasks > 0"
        type="button"
        class="task-pill touch-target"
        :aria-label="`任务 ${shell.taskDone}/${shell.taskTotal} 进行中`"
        @click="router.push('/tasks')"
      >
        <el-icon class="task-spin" :size="13"><Loading /></el-icon>
        <span class="task-text">任务 {{ shell.taskDone }}/{{ shell.taskTotal }}</span>
        <span class="task-bar" aria-hidden="true">
          <span class="task-bar-fill" :style="{ width: `${shell.taskPercent}%` }" />
        </span>
      </button>

      <!-- NSFW -->
      <el-popover placement="bottom-end" :width="280" trigger="click" v-model:visible="nsfwPopoverVisible">
        <template #reference>
          <el-tooltip :content="nsfwEnabled ? 'NSFW 模式：已开启' : 'NSFW 模式：已关闭'" placement="bottom">
            <button
              type="button"
              class="icon-btn touch-target nsfw-btn"
              :class="{ 'nsfw-active': nsfwEnabled }"
              :aria-label="nsfwEnabled ? 'NSFW 模式已开启,点击关闭' : 'NSFW 模式已关闭,点击开启'"
              :aria-expanded="nsfwPopoverVisible"
              aria-haspopup="dialog"
              @click="nsfwPopoverVisible = !nsfwPopoverVisible"
            >
              <el-icon :size="18">
                <View v-if="nsfwEnabled" />
                <Hide v-else />
              </el-icon>
            </button>
          </el-tooltip>
        </template>
        <div class="nsfw-panel">
          <div class="nsfw-panel-title">NSFW 模式</div>
          <div class="nsfw-panel-desc">关闭后将隐藏封面、标题、演员头像等敏感内容</div>
          <div class="nsfw-panel-row">
            <span>启用 NSFW 模式</span>
            <el-switch v-model="nsfwEnabled" @change="onNsfwToggle" :loading="nsfwLoading" />
          </div>
          <el-divider />
          <div class="nsfw-panel-row">
            <span>隐藏封面</span>
            <el-switch v-model="nsfwConfig.hide_cover" @change="onNsfwConfigChange" />
          </div>
          <div class="nsfw-panel-row">
            <span>隐藏标题</span>
            <el-switch v-model="nsfwConfig.hide_title" @change="onNsfwConfigChange" />
          </div>
          <div class="nsfw-panel-row">
            <span>隐藏演员头像</span>
            <el-switch v-model="nsfwConfig.hide_actor_avatar" @change="onNsfwConfigChange" />
          </div>
          <div class="nsfw-panel-row">
            <span>模糊缩略图</span>
            <el-switch v-model="nsfwConfig.blur_thumbnails" @change="onNsfwConfigChange" />
          </div>
          <div class="nsfw-panel-row">
            <span>模糊强度</span>
            <el-slider
              v-model="nsfwConfig.blur_intensity"
              :min="1"
              :max="50"
              :disabled="!nsfwConfig.blur_thumbnails"
              style="width: 120px"
              @change="onNsfwConfigChange"
            />
          </div>
        </div>
      </el-popover>

      <!-- 主题 -->
      <el-tooltip :content="isDark ? '切换到亮色模式' : '切换到暗黑模式'" placement="bottom">
        <button
          type="button"
          class="icon-btn touch-target"
          :aria-label="isDark ? '切换到亮色模式' : '切换到暗黑模式'"
          :aria-pressed="isDark"
          @click="toggleDark"
        >
          <el-icon :size="18">
            <Sunny v-if="isDark" />
            <Moon v-else />
          </el-icon>
        </button>
      </el-tooltip>

      <!-- 撤销 / 重做 Chip（Q4：取代状态栏的 undo 文案） -->
      <el-dropdown v-if="undoStore.canUndo || undoStore.canRedo" trigger="click" @command="onUndoCommand">
        <button type="button" class="undo-chip touch-target" aria-label="撤销/重做历史">
          <el-icon :size="13"><RefreshLeft /></el-icon>
          <span>
            <template v-if="undoStore.canUndo">可撤销 {{ undoStore.undoCount }}</template>
            <template v-else>可重做 {{ undoStore.redoCount }}</template>
          </span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="undo" :disabled="!undoStore.canUndo">
              撤销上一步（{{ undoStore.undoCount }}）
            </el-dropdown-item>
            <el-dropdown-item command="redo" :disabled="!undoStore.canRedo">
              重做（{{ undoStore.redoCount }}）
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-divider direction="vertical" class="topbar-divider" />

      <!-- 用户菜单 -->
      <el-dropdown trigger="click" @command="onUserCommand">
        <button type="button" class="user-btn touch-target" :aria-label="`当前登录用户 ${currentUser}`">
          <el-avatar :size="26" class="user-avatar" aria-hidden="true">
            <el-icon :size="14"><User /></el-icon>
          </el-avatar>
          <span class="user-name">{{ currentUser }}</span>
          <span v-if="updateAvailable" class="update-dot" aria-label="有新版本可用" />
          <el-icon :size="12" class="user-caret"><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="changelog">更新日志</el-dropdown-item>
            <el-dropdown-item v-if="isElectron" command="check-update">检查更新</el-dropdown-item>
            <el-dropdown-item v-if="isElectron && updateDownloaded" command="install-update">
              安装更新并重启
            </el-dropdown-item>
            <el-dropdown-item command="refresh" divided>刷新页面</el-dropdown-item>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<script setup>
/**
 * AppTopbar —— 64px 顶栏
 *
 * 五段布局：折叠 / 面包屑（flex:1） / 搜索 / 任务胶囊 / 工具组 / 用户菜单
 *
 * 搬迁说明（ARCH-phase1 §7.3 / §7.4）：
 * - NSFW 的全部状态与三个处理函数**逐字迁自** AdminLayout.vue（含 `data-nsfw` 反向映射注释）；
 * - 「更新日志 / 检查更新 / 安装更新」只保留入口按钮，对话框与状态机仍在 AdminLayout；
 * - 删除：刷新按钮、退出按钮、更新徽标、`el-divider` 之外的独立图标。
 */
import { computed, reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Fold, Expand, Search, Loading, View, Hide, Sunny, Moon,
  RefreshLeft, User, ArrowDown,
} from '@element-plus/icons-vue'
import { getNsfwConfig, updateNsfwConfig, toggleNsfwMode } from '@/api'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'
import { useUndoStore } from '@/stores/undo'
import { useShellStatsStore } from '@/stores/shellStats'
import PageBreadcrumb from '@/components/shell/PageBreadcrumb.vue'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
  /** 有新版本可用（Electron 更新器推上来） */
  updateAvailable: { type: Boolean, default: false },
  /** 更新已下载完成 */
  updateDownloaded: { type: Boolean, default: false },
})

const emit = defineEmits(['update:collapsed', 'open-search', 'open-changelog', 'open-update', 'install-update'])

const router = useRouter()
const shell = useShellStatsStore()
const undoStore = useUndoStore()

// ===== 主题 =====
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)
const toggleDark = () => themeStore.toggleDark()

// ===== 认证 =====
const authStore = useAuthStore()
const currentUser = computed(() => authStore.username)

// ===== Electron =====
const isElectron = computed(() => !!(window.electronAPI && window.electronAPI.isElectron))

// ===== NSFW 模式（原样迁自 AdminLayout.vue）=====
const nsfwPopoverVisible = ref(false)
const nsfwLoading = ref(false)
const nsfwEnabled = ref(true)
const nsfwConfig = reactive({
  hide_cover: false,
  hide_title: false,
  hide_actor_avatar: false,
  blur_thumbnails: false,
  blur_intensity: 10,
})

const applyNsfwMode = () => {
  // 通过 data-attribute 让全局 CSS 感知 NSFW 状态
  // data-nsfw: on/off（off 表示 NSFW 模式关闭 = 正常显示内容；on 表示隐藏敏感内容）
  // data-nsfw-hide-cover / hide-title / hide-actor-avatar: '1' 或 '0'
  // data-nsfw-blur: 模糊强度（0 表示不模糊）
  //
  // 重要：CSS 规则（index.css:823-834）使用 `html[data-nsfw="off"]` 选择器来模糊内容，
  // 因为原始语义是"data-nsfw=off 表示隐藏模式"（反向了）。为了保持命名一致，
  // 这里翻转映射：nsfwEnabled=true(开启 NSFW) → data-nsfw="off"（隐藏）
  //                nsfwEnabled=false(关闭 NSFW) → data-nsfw="on"（显示）
  const root = document.documentElement
  // 反向映射: 开启 NSFW → data-nsfw=off (CSS 触发模糊/隐藏)
  //           关闭 NSFW → data-nsfw=on  (CSS 不触发)
  root.setAttribute('data-nsfw', nsfwEnabled.value ? 'off' : 'on')
  root.setAttribute('data-nsfw-hide-cover', nsfwConfig.hide_cover ? '1' : '0')
  root.setAttribute('data-nsfw-hide-title', nsfwConfig.hide_title ? '1' : '0')
  root.setAttribute('data-nsfw-hide-avatar', nsfwConfig.hide_actor_avatar ? '1' : '0')
  root.setAttribute('data-nsfw-blur', nsfwConfig.blur_thumbnails ? String(nsfwConfig.blur_intensity) : '0')
  // 派发事件让页面组件感知（如 Play.vue 需要重新计算截图模糊）
  window.dispatchEvent(new CustomEvent('mdcx-nsfw-change', {
    detail: {
      enabled: nsfwEnabled.value,
      config: { ...nsfwConfig },
    },
  }))
  localStorage.setItem('mdcx_nsfw', nsfwEnabled.value ? '1' : '0')
}

const loadNsfwConfig = async () => {
  try {
    const data = await getNsfwConfig()
    nsfwEnabled.value = data.enabled
    nsfwConfig.hide_cover = data.hide_cover
    nsfwConfig.hide_title = data.hide_title
    nsfwConfig.hide_actor_avatar = data.hide_actor_avatar
    nsfwConfig.blur_thumbnails = data.blur_thumbnails
    nsfwConfig.blur_intensity = data.blur_intensity
    applyNsfwMode()
  } catch (e) {
    // 静默失败：未授权或后端不可用
    const cached = localStorage.getItem('mdcx_nsfw')
    if (cached !== null) {
      nsfwEnabled.value = cached === '1'
      applyNsfwMode()
    }
  }
}

const onNsfwToggle = async (val) => {
  nsfwLoading.value = true
  try {
    const data = await toggleNsfwMode()
    nsfwEnabled.value = data.enabled
    applyNsfwMode()
    ElMessage.success(nsfwEnabled.value ? 'NSFW 模式已开启' : 'NSFW 模式已关闭')
  } catch (e) {
    // 失败回滚
    nsfwEnabled.value = !val
  } finally {
    nsfwLoading.value = false
  }
}

const onNsfwConfigChange = async () => {
  try {
    await updateNsfwConfig({
      hide_cover: nsfwConfig.hide_cover,
      hide_title: nsfwConfig.hide_title,
      hide_actor_avatar: nsfwConfig.hide_actor_avatar,
      blur_thumbnails: nsfwConfig.blur_thumbnails,
      blur_intensity: nsfwConfig.blur_intensity,
    })
    applyNsfwMode()
  } catch (e) {
    // 静默
  }
}

// ===== 撤销 / 重做 =====
async function onUndoCommand(command) {
  if (command === 'undo') {
    try {
      await undoStore.undo()
    } catch (e) {
      ElMessage.error('撤销失败')
    }
  } else if (command === 'redo') {
    try {
      await undoStore.redo()
    } catch (e) {
      ElMessage.error('重做失败')
    }
  }
}

// ===== 用户菜单 =====
function onUserCommand(command) {
  if (command === 'changelog') {
    emit('open-changelog')
    return
  }
  if (command === 'check-update') {
    emit('open-update')
    return
  }
  if (command === 'install-update') {
    emit('install-update')
    return
  }
  if (command === 'refresh') {
    window.location.reload()
    return
  }
  if (command === 'logout') {
    // 清除保存的凭证，防止自动登录循环
    localStorage.removeItem('mdcx_saved_user')
    localStorage.removeItem('mdcx_saved_pwd_hash')
    authStore.logout()
    router.push('/login')
  }
}

onMounted(() => {
  // 主题已在 main.js 初始化，这里只需加载 NSFW 配置
  loadNsfwConfig()
})

// props 在模板中被使用（collapsed / updateAvailable / updateDownloaded）；
// 显式引用一次避免 Lint 误判
void props
</script>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: var(--topbar-h, 64px);
  flex-shrink: 0;
  padding: 0 var(--space-6, 24px) 0 var(--space-4, 16px);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  box-sizing: border-box;
  z-index: 10;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.topbar-crumb {
  min-width: 0;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

/* ---------- 图标按钮（32×32） ---------- */
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  padding: 0;
  border: 0;
  border-radius: var(--radius-ctl, 8px);
  background: transparent;
  color: var(--text-regular);
  cursor: pointer;
  transition:
    background-color var(--dur-fast, 120ms),
    color var(--dur-fast, 120ms);
}

.icon-btn:hover {
  background: var(--hover-layer);
  color: var(--text-primary);
}

.icon-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* ---------- 搜索入口 ---------- */
.search-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: min(320px, 26vw);
  height: 34px;
  padding: 0 10px;
  margin-right: 6px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-ctl, 8px);
  background: var(--bg-page);
  color: var(--text-placeholder);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  box-sizing: border-box;
  transition:
    border-color var(--dur-fast, 120ms),
    background-color var(--dur-fast, 120ms);
}

.search-trigger:hover {
  border-color: var(--card-border-hover);
  background: var(--bg-card);
}

.search-trigger:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.search-placeholder {
  flex: 1;
  min-width: 0;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-kbd {
  flex-shrink: 0;
  padding: 1px 5px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-card);
  font-family: inherit;
  font-size: 11px;
  color: var(--text-placeholder);
}

/* ---------- 任务胶囊 ---------- */
.task-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 9px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: transparent;
  font-family: inherit;
  font-size: 12px;
  color: var(--text-regular);
  cursor: pointer;
  font-variant-numeric: tabular-nums;
  transition:
    border-color var(--dur-fast, 120ms),
    background-color var(--dur-fast, 120ms);
}

.task-pill:hover {
  border-color: var(--card-border-hover);
  background: var(--hover-layer);
}

.task-pill:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.task-spin {
  color: var(--accent);
  animation: rotating 1.5s linear infinite;
}

.task-bar {
  display: inline-block;
  width: 60px;
  height: 4px;
  border-radius: 2px;
  background: var(--hover-layer);
  overflow: hidden;
}

.task-bar-fill {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width var(--dur-base, 200ms) var(--ease-out-nav, ease-out);
}

/* ---------- 撤销 Chip ---------- */
.undo-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-ctl, 8px);
  background: transparent;
  font-family: inherit;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  font-variant-numeric: tabular-nums;
}

.undo-chip:hover {
  color: var(--accent);
  border-color: var(--card-border-hover);
}

.undo-chip:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.topbar-divider {
  margin: 0 4px;
}

/* ---------- 用户菜单 ---------- */
.user-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--radius-ctl, 8px);
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  color: var(--text-regular);
  cursor: pointer;
  position: relative;
}

.user-btn:hover {
  background: var(--hover-layer);
}

.user-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.user-avatar {
  background: var(--accent);
  color: #fff;
  flex-shrink: 0;
}

.user-name {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-caret {
  color: var(--text-placeholder);
}

.update-dot {
  position: absolute;
  top: 4px;
  right: 2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--danger-color);
}

/* ---------- NSFW ---------- */
.nsfw-btn {
  position: relative;
}

.nsfw-btn.nsfw-active {
  color: var(--danger-color);
}

.nsfw-btn.nsfw-active::after {
  content: '';
  position: absolute;
  top: 4px;
  right: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--danger-color);
}

.nsfw-panel {
  padding: 4px 0;
}

.nsfw-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.nsfw-panel-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  line-height: 1.5;
}

.nsfw-panel-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
  color: var(--text-regular);
}

.nsfw-panel :deep(.el-divider) {
  margin: 8px 0;
}

@keyframes rotating {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}

@media (max-width: 1100px) {
  .search-trigger {
    width: 34px;
    justify-content: center;
    padding: 0;
  }
  .search-placeholder,
  .search-kbd {
    display: none;
  }
}

@media (max-width: 860px) {
  .user-name {
    display: none;
  }
}
</style>
