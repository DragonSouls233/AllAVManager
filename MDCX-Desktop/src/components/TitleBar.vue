<template>
  <div v-if="isElectron" class="title-bar">
    <!-- 左侧：应用标题 + 当前路由名称 -->
    <div class="title-left">
      <span class="app-name">MDCX</span>
      <span v-if="routeTitle" class="title-separator">·</span>
      <span v-if="routeTitle" class="route-name">{{ routeTitle }}</span>
    </div>

    <!-- 中间占位（可拖拽区域） -->
    <div class="title-center"></div>

    <!-- 右侧：macOS 风格红绿黄窗口控制按钮（Windows 平台样式） -->
    <!-- macOS 上使用原生 traffic lights，不渲染自定义按钮 -->
    <div v-if="!isMac" class="window-controls">
      <button
        class="control-btn minimize"
        title="最小化"
        @click="onMinimize"
      >
        <svg class="ctrl-icon" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 5 H8" />
        </svg>
      </button>
      <button
        class="control-btn maximize"
        :title="isMaximized ? '还原' : '最大化'"
        @click="onToggleMaximize"
      >
        <svg v-if="!isMaximized" class="ctrl-icon" viewBox="0 0 10 10" aria-hidden="true">
          <rect x="2" y="2" width="6" height="6" />
        </svg>
        <svg v-else class="ctrl-icon" viewBox="0 0 10 10" aria-hidden="true">
          <rect x="2.5" y="3.5" width="5" height="5" />
          <rect x="3.5" y="2.5" width="5" height="5" />
        </svg>
      </button>
      <button
        class="control-btn close"
        title="关闭"
        @click="onClose"
      >
        <svg class="ctrl-icon" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 2 L8 8 M8 2 L2 8" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

// 仅在 Electron 环境下渲染
const electronAPI = (typeof window !== 'undefined' && window.electronAPI) || null
const isElectron = computed(() => !!electronAPI?.isElectron)
// macOS 使用原生 traffic lights，其他平台使用自定义按钮
const isMac = computed(() => electronAPI?.platform === 'darwin')

// 窗口最大化状态
const isMaximized = ref(false)
let unbindWindowState = null

// 路由标题映射（与 Layout.vue 保持一致）
const ROUTE_TITLES = {
  '/': '首页概览',
  '/movies': '番号库',
  '/actors': '演员',
  '/crawlers': '爬虫管理',
  '/compare': '本地与在线对比',
  '/favorites': '收藏夹',
  '/fingerprint': '视频指纹去重',
  '/patch': '补丁刮削',
  '/import': '批量导入',
  '/tags': '标签管理',
  '/tiers': '分级治理中心',
  '/log-stream': '实时日志流',
  '/webdav-import': 'WebDAV 导入',
  '/cloud-drive2': 'CloudDrive2 网盘',
  '/pan-115': '115 网盘离线下载',
  '/metatube-plugin': 'Metatube 插件',
  '/network-diag': '网络诊断中心',
  '/face-crop': 'AI 人脸裁剪',
  '/site-priority': '站点优先级',
  '/naming-template': '命名模板',
  '/emby-config': 'Emby 协议兼容',
  '/strm': 'STRM 文件生成',
  '/tvbox': 'TVBox/MacCMS 开放接口',
  '/downloaders': '下载器统一管理',
  '/themes': '皮肤主题',
  '/schema-settings': 'Schema 设置',
  '/deploy': '部署档位',
  '/backup': '自动备份管理',
  '/desktop-settings': '桌面设置',
  '/tasks': '任务中心',
  '/plugins': '插件系统',
  '/webhooks': 'Webhook 通知',
  '/subscriptions': '演员订阅',
  '/viewing-report': 'AI 观影报告',
  '/telegram-bot': 'Telegram Bot',
  '/view-status': '三态视频标记',
  '/file-organize': '文件整理',
  '/users': '用户管理',
  '/logs': '系统日志',
  '/mpv-settings': 'mpv 播放器设置',
  '/settings': '系统设置',
  '/poster-enhance': '海报增强',
  '/series-subscriptions': '系列订阅',
  '/movie-graph': '影片图谱',
  '/recommendations': '智能推荐',
  '/auto-organize': '自动整理',
  '/cookiecloud': 'CookieCloud 同步',
  '/gfriends': 'Gfriends 头像库',
  '/unrecognized-files': '未识别文件处理',
  '/nfo-scrape': 'NFO 免改名刮削',
  '/workflows': '工作流管理',
  '/studios': '制片厂管理',
  '/files': '文件管理',
  '/system-status': '系统状态',
  '/source-merge': '多来源数据精选',
  '/refresh-folders': '文件夹刷新',
  '/cookie-manager': 'Cookie 管理器',
  '/proxy-xray': '内置代理',
  '/auto-organize': '自动整理'
}

const routeTitle = computed(() => ROUTE_TITLES[route.path] || route.meta?.title || route.name || '')

const onMinimize = () => {
  electronAPI?.windowMinimize?.()
}

const onToggleMaximize = () => {
  electronAPI?.windowToggleMaximize?.()
}

const onClose = () => {
  electronAPI?.windowClose?.()
}

onMounted(() => {
  if (!isElectron.value) return
  // 同步初始最大化状态
  // Electron 没有直接暴露 isMaximized，通过窗口状态变化事件维护
  if (unbindWindowState) unbindWindowState()
  unbindWindowState = electronAPI?.onWindowStateChange?.((state) => {
    isMaximized.value = state === 'maximized'
  })
})

onUnmounted(() => {
  if (unbindWindowState) {
    unbindWindowState()
    unbindWindowState = null
  }
})
</script>

<style scoped>
/* 整个标题栏为可拖拽区域 */
.title-bar {
  -webkit-app-region: drag;
  height: 32px;
  display: flex;
  align-items: center;
  background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
  user-select: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.25);
  flex-shrink: 0;
}

.title-left {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.app-name {
  color: #fff;
}

.title-separator {
  color: rgba(255, 255, 255, 0.3);
}

.route-name {
  color: rgba(255, 255, 255, 0.65);
  font-weight: 400;
}

.title-center {
  flex: 1;
  /* 中间空白作为拖拽区域 */
}

/* 窗口控制按钮容器 */
.window-controls {
  -webkit-app-region: no-drag;
  display: flex;
  align-items: center;
  height: 100%;
}

/* macOS 风格红绿黄按钮 */
.control-btn {
  width: 46px;
  height: 32px;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  position: relative;
  outline: none;
  padding: 0;
}

/* 圆形彩色徽章（默认隐藏，hover 时显示） */
.control-btn::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #888;
  opacity: 0;
  transition: opacity 0.12s;
  transform: translate(-50%, -50%);
}

/* 默认显示彩色徽章（macOS 风格） */
.control-btn.minimize::before {
  background: #febc2e; /* 黄色 - 最小化 */
  opacity: 1;
}
.control-btn.maximize::before {
  background: #28c840; /* 绿色 - 最大化 */
  opacity: 1;
}
.control-btn.close::before {
  background: #ff5f57; /* 红色 - 关闭 */
  opacity: 1;
}

/* hover 整组按钮时全部显示彩色 */
.window-controls:hover .control-btn::before {
  opacity: 1;
}

/* 按钮 hover 时显示 SVG 图标 */
.ctrl-icon {
  position: relative;
  z-index: 1;
  width: 10px;
  height: 10px;
  fill: none;
  stroke: rgba(0, 0, 0, 0.55);
  stroke-width: 1.2;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0;
  transition: opacity 0.12s;
}

.control-btn:hover .ctrl-icon {
  opacity: 1;
}

.control-btn.maximize .ctrl-icon rect {
  fill: rgba(0, 0, 0, 0.04);
}

/* 关闭按钮 hover 加深 */
.control-btn.close:hover {
  background: rgba(255, 95, 87, 0.18);
}
.control-btn.minimize:hover {
  background: rgba(254, 188, 46, 0.16);
}
.control-btn.maximize:hover {
  background: rgba(40, 200, 64, 0.16);
}

.control-btn:active {
  filter: brightness(0.92);
}
</style>
