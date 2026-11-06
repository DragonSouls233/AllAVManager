<template>
  <div class="layout-root">
    <el-container class="layout-container">
      <!-- 跳到主内容（无障碍快捷导航） -->
      <a href="#main-content" class="skip-link">跳到主内容</a>

      <!-- 侧栏（浅色 · 手风琴 · 折叠 64px） -->
      <AppSidebar v-model="collapsed" @open-changelog="openChangelog" />

      <el-container direction="vertical" class="content-column">
        <!-- 顶栏（64px） -->
        <AppTopbar
          :collapsed="collapsed"
          :update-available="updateAvailable"
          :update-downloaded="updateDownloaded"
          @update:collapsed="collapsed = $event"
          @open-search="paletteOpen = true"
          @open-changelog="openChangelog"
          @open-update="openUpdateDialog"
          @install-update="installUpdate"
        />

        <el-main class="main-content" id="main-content" role="main">
          <router-view v-slot="{ Component }">
            <transition name="fade-slide" mode="out-in">
              <keep-alive :max="20" :exclude="excludeCache">
                <component :is="Component" :key="$route.name" />
              </keep-alive>
            </transition>
          </router-view>
        </el-main>
      </el-container>

      <!-- 全局状态通告区（屏幕阅读器礼貌播报） -->
      <div aria-live="polite" aria-atomic="true" class="sr-only">
        {{ liveStatus }}
      </div>

      <!-- 命令面板（⌘K / Ctrl+K） -->
      <CommandPalette v-model="paletteOpen" />

      <!-- 自动更新对话框（仅 Electron 环境） -->
      <el-dialog v-model="updateDialogVisible" title="应用更新" width="440px" v-if="isElectron">
        <div class="update-dialog-content">
          <!-- 检查中 -->
          <div v-if="updateStatus === 'checking'" class="update-state">
            <el-icon class="is-loading" :size="32"><Refresh /></el-icon>
            <p>正在检查更新...</p>
          </div>

          <!-- 有新版本 -->
          <div v-else-if="updateStatus === 'available'" class="update-state">
            <el-icon :size="40" color="#5468d4"><Download /></el-icon>
            <h3>发现新版本 v{{ updateVersion }}</h3>
            <div v-if="updateReleaseNotes" class="update-notes" v-html="updateReleaseNotes"></div>
            <p class="update-hint">点击下方按钮下载更新</p>
            <el-button type="primary" :loading="updateDownloading" @click="downloadUpdate">
              {{ updateDownloading ? '下载中...' : '下载更新' }}
            </el-button>
          </div>

          <!-- 下载进度 -->
          <div v-else-if="updateStatus === 'downloading'" class="update-state">
            <el-icon :size="32" color="#5468d4"><Download /></el-icon>
            <p>正在下载更新...</p>
            <el-progress :percentage="updateProgress" :stroke-width="8" />
            <p class="update-progress-text">
              {{ formatBytes(updateTransferred) }} / {{ formatBytes(updateTotal) }}
            </p>
          </div>

          <!-- 下载完成 -->
          <div v-else-if="updateStatus === 'downloaded'" class="update-state">
            <el-icon :size="40" color="#67C23A"><CircleCheck /></el-icon>
            <h3>更新已就绪</h3>
            <p>新版本 v{{ updateVersion }} 已下载完成，重启应用以完成安装。</p>
            <el-button type="success" @click="installUpdate">安装并重启</el-button>
          </div>

          <!-- 无更新 -->
          <div v-else-if="updateStatus === 'not-available'" class="update-state">
            <el-icon :size="40" color="#67C23A"><CircleCheck /></el-icon>
            <h3>已是最新版本</h3>
            <p>当前版本 v{{ currentVersion }} 是最新的。</p>
          </div>

          <!-- 错误 -->
          <div v-else-if="updateStatus === 'error'" class="update-state">
            <el-icon :size="40" color="#F56C6C"><WarningFilled /></el-icon>
            <h3>更新失败</h3>
            <p class="update-error">{{ updateError }}</p>
            <el-button @click="checkForUpdates">重试</el-button>
          </div>

          <!-- 初始状态 -->
          <div v-else class="update-state">
            <el-icon :size="32" color="#909399"><Download /></el-icon>
            <p>检查是否有新版本</p>
            <el-button type="primary" @click="checkForUpdates">检查更新</el-button>
          </div>
        </div>
      </el-dialog>

      <!-- 更新日志对话框 -->
      <el-dialog v-model="changelogVisible" title="更新日志" width="560px">
        <div class="changelog-content">
          <div class="changelog-header">
            <span class="changelog-version">v{{ versionInfo.version || '0.01' }}</span>
            <el-tag size="small" type="success">{{ versionInfo.patch_level || 'baseline' }}</el-tag>
            <span class="changelog-date">{{ versionInfo.build_date || '' }}</span>
          </div>
          <el-divider />
          <div class="changelog-list">
            <div v-for="(patch, i) in (versionInfo.patches || []).slice().reverse()" :key="i" class="changelog-item">
              <el-icon class="changelog-icon"><Document /></el-icon>
              <span class="changelog-text">{{ patch }}</span>
            </div>
            <div v-if="!(versionInfo.patches || []).length" class="changelog-empty">
              暂无更新记录
            </div>
          </div>
          <el-divider />
          <div class="changelog-footer">
            <span>爬虫数: {{ versionInfo.scrapers || 55 }}</span>
            <span>内置代理: {{ versionInfo.xray ? '✅' : '❌' }}</span>
            <span>NFO缓存: {{ versionInfo.nfo_cache ? '✅' : '❌' }}</span>
          </div>
        </div>
      </el-dialog>

      <!-- 全局头像刮削进度浮层 -->
      <transition name="fade-slide">
        <div v-if="avatarStore.active" class="avatar-scrape-float" role="status" aria-live="polite">
          <div class="asf-header">
            <el-icon class="is-loading asf-spin"><Loading /></el-icon>
            <span class="asf-title">头像刮削进行中</span>
            <el-button text size="small" class="asf-cancel" @click="avatarStore.cancel()">
              取消
            </el-button>
          </div>
          <div class="asf-body">
            <el-progress :percentage="avatarStore.progressPercent" :stroke-width="8" :show-text="false" />
            <div class="asf-text">{{ avatarStore.statusText }}</div>
            <div v-if="avatarStore.status.current_actor" class="asf-current">
              正在处理：{{ avatarStore.status.current_actor }}
            </div>
          </div>
        </div>
      </transition>
    </el-container>
  </div>
</template>

<script setup>
/**
 * AdminLayout —— Web 外壳骨架
 *
 * 重构后只做 4 件事（ARCH-phase1 §7.1）：
 *   ① 装配：AppSidebar +（AppTopbar + main）
 *   ② 全局对话框：更新 / 更新日志 / 头像刮削浮层
 *   ③ 全局副作用：Electron 事件、更新器、shellStats 轮询、auth 的 刷新/退出
 *   ④ 样式：.layout-root / .main-content / 页面过渡
 *
 * ⚠️ 已移除：el-menu（270 处标记）、el-footer 状态栏、pageTitle 120 行 switch 表、
 *    全局搜索 el-dialog、healthStatus/stats/taskProgress 轮询（全部迁 shellStats）。
 * ⚠️ 逐字保留：Electron 三件套 unbind、更新器状态机、changelog、
 *    avatarStore 浮层、excludeCache（['MovieDetail','Play','ActorDetail']）、liveStatus。
 * ⚠️ 桌面端真实外壳是 CinemaLayout.vue，本文件不参与桌面构建。
 */
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh, Download, CircleCheck, WarningFilled, Document, Loading } from '@element-plus/icons-vue'
import { getVersion } from '@/api'
import { useAvatarScrapeStore } from '@/stores/avatarScrape'
import { useShellStatsStore } from '@/stores/shellStats'
import AppSidebar from '@/layouts/AppSidebar.vue'
import AppTopbar from '@/layouts/AppTopbar.vue'
import CommandPalette from '@/components/shell/CommandPalette.vue'

const route = useRoute()
const router = useRouter()

const avatarStore = useAvatarScrapeStore()
const shell = useShellStatsStore()

const collapsed = ref(false)
const paletteOpen = ref(false)

// ===== keep-alive 排除表（逐字保留）=====
const excludeCache = computed(() => {
  const p = route.path
  if (p.startsWith('/movie/') || p.startsWith('/play/') || p.startsWith('/actors/')) {
    return ['MovieDetail', 'Play', 'ActorDetail']
  }
  return []
})

// ===== 版本 =====
const currentVersion = computed(() => shell.version || '0.1.0')
const versionInfo = ref({ version: '0.01', patches: [], build_date: '', patch_level: '' })

// ===== Electron 桌面端事件监听 =====
// - onNavigateRoute：来自全局快捷键 Ctrl+Alt+E 或 mdcx:// 协议的路由跳转请求
// - onOpenUrl：mdcx:// 协议唤起时携带的载荷（type/id/route）
// - onTaskControl：托盘菜单"暂停/继续任务"触发
let unbindNavigateRoute = null
let unbindOpenUrl = null
let unbindTaskControl = null

function initDesktopEvents() {
  const api = (typeof window !== 'undefined' && window.electronAPI) || null
  if (!api || !api.isElectron) return
  if (api.onNavigateRoute) {
    unbindNavigateRoute = api.onNavigateRoute((to) => {
      if (!to) return
      try {
        router.push(to).catch(() => {})
      } catch (e) {
        // 静默
      }
    })
  }
  if (api.onOpenUrl) {
    unbindOpenUrl = api.onOpenUrl(({ route: target } = {}) => {
      if (target) {
        router.push(target).catch(() => {})
      }
    })
  }
  if (api.onTaskControl) {
    unbindTaskControl = api.onTaskControl((action) => {
      // 派发自定义事件，由 Tasks.vue 等组件响应
      window.dispatchEvent(new CustomEvent('mdcx-task-control', { detail: action }))
    })
  }
}

// ===== Electron 自动更新 =====
const isElectron = computed(() => !!(window.electronAPI && window.electronAPI.isElectron))
const updateDialogVisible = ref(false)
const updateStatus = ref('')        // '' / 'checking' / 'available' / 'downloading' / 'downloaded' / 'not-available' / 'error'
const updateVersion = ref('')
const updateReleaseNotes = ref('')
const updateProgress = ref(0)
const updateTransferred = ref(0)
const updateTotal = ref(0)
const updateDownloading = ref(false)
const updateError = ref('')
const updateAvailable = ref(false)
const updateDownloaded = ref(false)

// 全局无障碍状态通告（aria-live 区域内容）：根据更新状态派生文案,供屏幕阅读器礼貌播报
const liveStatus = computed(() => {
  if (updateStatus.value === 'checking') return '正在检查更新'
  if (updateStatus.value === 'available') return `发现新版本 ${updateVersion.value}`
  if (updateStatus.value === 'downloading') return `正在下载更新,进度 ${updateProgress.value}%`
  if (updateStatus.value === 'downloaded') return '更新已就绪,可以安装'
  if (updateStatus.value === 'error') return '更新失败'
  if (updateStatus.value === 'not-available') return '已是最新版本'
  return ''
})

function initUpdater() {
  if (!isElectron.value || !window.electronAPI.onUpdaterEvent) return
  window.electronAPI.onUpdaterEvent((payload) => {
    switch (payload.type) {
      case 'checking':
        updateStatus.value = 'checking'
        break
      case 'available':
        updateStatus.value = 'available'
        updateVersion.value = payload.version || ''
        updateReleaseNotes.value = typeof payload.releaseNotes === 'string'
          ? payload.releaseNotes
          : (payload.releaseNotes?.notes || '')
        updateAvailable.value = true
        updateDialogVisible.value = true
        break
      case 'not-available':
        updateStatus.value = 'not-available'
        break
      case 'progress':
        updateStatus.value = 'downloading'
        updateDownloading.value = true
        updateProgress.value = Math.round(payload.percent || 0)
        updateTransferred.value = payload.transferred || 0
        updateTotal.value = payload.total || 0
        break
      case 'downloaded':
        updateStatus.value = 'downloaded'
        updateDownloading.value = false
        updateDownloaded.value = true
        updateVersion.value = payload.version || updateVersion.value
        break
      case 'error':
        updateStatus.value = 'error'
        updateError.value = payload.message || '未知错误'
        updateDownloading.value = false
        break
    }
  })
}

async function checkForUpdates() {
  if (!isElectron.value || !window.electronAPI.updaterCheck) return
  updateStatus.value = 'checking'
  try {
    const result = await window.electronAPI.updaterCheck()
    if (result && !result.ok) {
      updateStatus.value = 'error'
      updateError.value = result.error || '检查更新失败'
    }
  } catch (e) {
    updateStatus.value = 'error'
    updateError.value = String(e)
  }
}

async function downloadUpdate() {
  if (!isElectron.value || !window.electronAPI.updaterDownload) return
  updateDownloading.value = true
  updateStatus.value = 'downloading'
  try {
    await window.electronAPI.updaterDownload()
  } catch (e) {
    updateStatus.value = 'error'
    updateError.value = String(e)
    updateDownloading.value = false
  }
}

function installUpdate() {
  if (!isElectron.value || !window.electronAPI.updaterInstall) return
  window.electronAPI.updaterInstall()
}

function openUpdateDialog() {
  updateDialogVisible.value = true
  checkForUpdates()
}

// ===== 版本 / 更新日志 =====
const changelogVisible = ref(false)

async function openChangelog() {
  changelogVisible.value = true
  // 先展示 store 里已有的版本信息（首屏已由 shellStats 拉过），再补全 patches 明细
  if (shell.versionInfo) versionInfo.value = { ...shell.versionInfo }
  try {
    const data = await getVersion()
    if (data) versionInfo.value = data
  } catch (e) {
    console.error('获取版本信息失败:', e)
  }
}

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(1)} ${units[i]}`
}

// ===== 生命周期 =====
/** 首页「更新日志」按钮通过 window 事件上抛，避免为 1 个按钮做 provide/inject */
function onOpenChangelogEvent() {
  openChangelog()
}

onMounted(() => {
  // ① 模块开关 + 外壳数据轮询（全站唯一入口，子组件永不调 startPolling）
  shell.loadModulesEnabled()
  shell.startPolling()
  // ② Electron 自动更新监听
  initUpdater()
  // ③ Electron 桌面端事件（全局快捷键 / mdcx:// 协议 / 任务控制）
  initDesktopEvents()
  // ④ 探测本地头像资料库状态（供演员/头像库页面使用）
  avatarStore.initLibrary()
  // ⑤ 首页等页面通过 window 事件请求打开「更新日志」
  window.addEventListener('mdcx-open-changelog', onOpenChangelogEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener('mdcx-open-changelog', onOpenChangelogEvent)
  shell.stopPolling()
  if (unbindNavigateRoute) {
    unbindNavigateRoute()
    unbindNavigateRoute = null
  }
  if (unbindOpenUrl) {
    unbindOpenUrl()
    unbindOpenUrl = null
  }
  if (unbindTaskControl) {
    unbindTaskControl()
    unbindTaskControl = null
  }
})
</script>

<style scoped>
.layout-root {
  display: flex;
  flex-direction: column;
  /* ⚠️ 逐字保留：--titlebar-h 由 TitleBar.vue 在 Electron 下运行时写入 36px */
  height: calc(100vh - var(--titlebar-h, 0px));
  overflow: hidden;
}

.layout-container {
  flex: 1;
  height: 0; /* 让 flex 子项正确滚动 */
}

.content-column {
  min-width: 0;
  overflow: hidden;
}

.main-content {
  background: var(--bg-page);
  /* 留白统一由「页面根容器」提供（tokens.redesign.css 的 .main-content > *），
     这里必须为 0，否则会和 PageShell 的 padding 叠成 44px */
  padding: 0;
  overflow-y: auto;
}

:global(html.dark) .main-content {
  background: var(--bg-page);
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition:
    opacity var(--dur-base, 200ms) var(--ease-out-nav, ease-out),
    transform var(--dur-base, 200ms) var(--ease-out-nav, ease-out);
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--dur-fast, 120ms);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ===== 自动更新对话框 ===== */
.update-dialog-content .update-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 20px 0;
  text-align: center;
}

.update-dialog-content h3 {
  margin: 0;
  font-size: 18px;
}

.update-dialog-content .update-hint {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 0;
}

.update-dialog-content .update-error {
  color: var(--danger-color);
  font-size: 13px;
  word-break: break-all;
}

.update-dialog-content .update-notes {
  max-height: 200px;
  overflow-y: auto;
  text-align: left;
  background: var(--bg-page);
  padding: 12px;
  border-radius: var(--radius-ctl, 8px);
  font-size: 13px;
  line-height: 1.6;
  width: 100%;
  box-sizing: border-box;
}

.update-dialog-content .update-progress-text {
  color: var(--text-secondary);
  font-size: 12px;
  margin: 0;
}

/* ===== 更新日志对话框 ===== */
.changelog-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-regular);
}

.changelog-version {
  font-weight: 700;
  font-size: 15px;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.changelog-date {
  margin-left: auto;
  color: var(--text-placeholder);
}

.changelog-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.changelog-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-regular);
}

.changelog-icon {
  flex-shrink: 0;
  margin-top: 4px;
  color: var(--accent);
}

.changelog-empty {
  padding: 12px 0;
  font-size: 13px;
  color: var(--text-placeholder);
}

.changelog-footer {
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: var(--text-secondary);
}

/* ===== 全局头像刮削进度浮层 ===== */
.avatar-scrape-float {
  position: fixed;
  top: calc(var(--topbar-h, 64px) + 8px);
  right: 20px;
  width: 300px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-card, 10px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.18);
  padding: 14px 16px;
  z-index: 2000;
}

.avatar-scrape-float .asf-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.avatar-scrape-float .asf-spin {
  color: var(--accent);
  animation: rotating 1.5s linear infinite;
}

.avatar-scrape-float .asf-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.avatar-scrape-float .asf-cancel {
  padding: 2px 8px !important;
  font-size: 12px;
  color: var(--danger-color);
}

.avatar-scrape-float .asf-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.avatar-scrape-float .asf-text {
  font-size: 12px;
  color: var(--text-secondary);
}

.avatar-scrape-float .asf-current {
  font-size: 12px;
  color: var(--text-placeholder);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@keyframes rotating {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}
</style>
