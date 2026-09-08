<template>
  <div v-if="isElectron" class="title-bar" @dblclick="onToggleMaximize">
    <!-- 左侧：品牌 + 当前页面名 -->
    <div class="title-left">
      <span class="app-mark">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="1.5" y="3" width="13" height="10" rx="2" />
          <path d="M6.2 6.1 L10.4 8 L6.2 9.9 Z" />
        </svg>
      </span>
      <span class="app-name">MDCX</span>
      <span v-if="routeTitle" class="title-separator">·</span>
      <span v-if="routeTitle" class="route-name">{{ routeTitle }}</span>
    </div>

    <!-- 中间：可拖拽区域（双击最大化） -->
    <div class="title-center"></div>

    <!-- 右侧：Windows 风格窗口控制 -->
    <div v-if="!isMac" class="window-controls">
      <button class="control-btn" title="最小化" aria-label="最小化" @click.stop="onMinimize">
        <svg class="ctrl-icon" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2.5 6 H9.5" />
        </svg>
      </button>
      <button
        class="control-btn"
        :title="isMaximized ? '向下还原' : '最大化'"
        :aria-label="isMaximized ? '向下还原' : '最大化'"
        @click.stop="onToggleMaximize"
      >
        <svg v-if="!isMaximized" class="ctrl-icon" viewBox="0 0 12 12" aria-hidden="true">
          <rect x="2.5" y="2.5" width="7" height="7" />
        </svg>
        <svg v-else class="ctrl-icon" viewBox="0 0 12 12" aria-hidden="true">
          <rect x="2.5" y="4.5" width="5" height="5" />
          <path d="M4.5 4.5 V2.5 H9.5 V7.5 H7.5" />
        </svg>
      </button>
      <button class="control-btn close" title="关闭" aria-label="关闭" @click.stop="onClose">
        <svg class="ctrl-icon" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 3 L9 9 M9 3 L3 9" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const electronAPI = (typeof window !== 'undefined' && window.electronAPI) || null
const isElectron = computed(() => !!electronAPI?.isElectron)
const isMac = computed(() => electronAPI?.platform === 'darwin')

const isMaximized = ref(false)
let unbindWindowState = null

const routeTitle = computed(() => route.meta?.title || route.name || '')

const onMinimize = () => electronAPI?.windowMinimize?.()

const onToggleMaximize = () => {
  // 中间空白区可双击最大化，按钮本身单击即可，这里统一走同一个 IPC
  electronAPI?.windowToggleMaximize?.()
  isMaximized.value = !isMaximized.value
}

const HINT_KEY = 'mdcx_tray_hint_shown'

const onClose = async () => {
  let closeToTray = true
  try {
    const prefs = await electronAPI?.getDesktopPrefs?.()
    if (prefs && prefs.close_to_tray === false) closeToTray = false
  } catch {
    /* 读不到偏好就按默认（最小化到托盘）处理 */
  }

  // 最小化到托盘时给一次明确反馈，避免用户以为「关不掉」
  if (closeToTray && !localStorage.getItem(HINT_KEY)) {
    localStorage.setItem(HINT_KEY, '1')
    try {
      await electronAPI?.showNotification?.(
        'MDCX 已最小化到托盘',
        '单击托盘图标可重新打开；右键托盘 → 退出，可完全关闭程序'
      )
    } catch {
      /* 通知失败不影响关闭 */
    }
  }

  electronAPI?.windowClose?.()
}

onMounted(() => {
  if (!isElectron.value) return
  // 告诉布局层标题栏高度，供 calc() 使用
  document.documentElement.style.setProperty('--titlebar-h', '36px')
  document.documentElement.classList.add('electron')

  if (unbindWindowState) unbindWindowState()
  unbindWindowState = electronAPI?.onWindowStateChange?.((state) => {
    isMaximized.value = state === 'maximized'
  })
})

onUnmounted(() => {
  document.documentElement.style.removeProperty('--titlebar-h')
  if (unbindWindowState) {
    unbindWindowState()
    unbindWindowState = null
  }
})
</script>

<style scoped>
.title-bar {
  -webkit-app-region: drag;
  height: 36px;
  display: flex;
  align-items: center;
  background: #0d1017;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  color: rgba(233, 238, 247, 0.9);
  font-size: 12px;
  user-select: none;
  flex-shrink: 0;
  position: relative;
  z-index: 100;
}

.title-left {
  -webkit-app-region: no-drag;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 14px;
  pointer-events: none;
}

.app-mark {
  display: inline-flex;
  width: 15px;
  height: 15px;
  color: #41b3ff;
}
.app-mark svg {
  width: 100%;
  height: 100%;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.3;
  stroke-linejoin: round;
}
.app-mark svg path {
  fill: currentColor;
  stroke: none;
}

.app-name {
  font-weight: 600;
  letter-spacing: 0.4px;
  color: #e9eef7;
}

.title-separator {
  color: rgba(255, 255, 255, 0.22);
}

.route-name {
  color: rgba(233, 238, 247, 0.55);
  font-weight: 400;
}

.title-center {
  flex: 1;
  height: 100%;
}

.window-controls {
  -webkit-app-region: no-drag;
  display: flex;
  align-items: stretch;
  height: 100%;
}

.control-btn {
  width: 46px;
  height: 36px;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  outline: none;
  padding: 0;
  transition: background 0.12s;
}

.ctrl-icon {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: rgba(233, 238, 247, 0.82);
  stroke-width: 1.1;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.control-btn:hover {
  background: rgba(255, 255, 255, 0.09);
}

.control-btn:active {
  background: rgba(255, 255, 255, 0.14);
}

.control-btn.close:hover {
  background: #e81123;
}
.control-btn.close:hover .ctrl-icon {
  stroke: #fff;
}
.control-btn.close:active {
  background: #c50f1d;
}
</style>
