// Electron preload - 暴露受控的 API 给渲染进程
// 使用 contextBridge.exposeInMainWorld 注册到 window.electronAPI
import { contextBridge, ipcRenderer } from 'electron'

// 桌面端 API：托盘、全局快捷键、自动更新、窗口控制等
contextBridge.exposeInMainWorld('electronAPI', {
  // 平台信息
  platform: process.platform,
  isElectron: true,

  // ===== 窗口控制 =====
  windowMinimize: () => ipcRenderer.send('window-minimize'),
  windowMaximize: () => ipcRenderer.send('window-maximize'),
  windowClose: () => ipcRenderer.send('window-close'),
  windowToggleMaximize: () => ipcRenderer.send('window-toggle-maximize'),
  onWindowStateChange: (callback) => {
    const handler = (_event, state) => callback(state)
    ipcRenderer.on('window-state-changed', handler)
    return () => ipcRenderer.removeListener('window-state-changed', handler)
  },

  // ===== 系统托盘 =====
  trayToggle: () => ipcRenderer.send('tray-toggle'),
  trayShow: () => ipcRenderer.send('tray-show'),

  // ===== 全局快捷键 =====
  // 注册渲染进程请求的快捷键
  registerGlobalShortcut: (accelerator) => ipcRenderer.invoke('global-shortcut-register', accelerator),
  unregisterGlobalShortcut: (accelerator) => ipcRenderer.invoke('global-shortcut-unregister', accelerator),
  // 监听主进程触发的全局快捷键事件
  onGlobalShortcut: (callback) => {
    const handler = (_event, accelerator) => callback(accelerator)
    ipcRenderer.on('global-shortcut-triggered', handler)
    return () => ipcRenderer.removeListener('global-shortcut-triggered', handler)
  },

  // ===== 自动更新 =====
  updaterCheck: () => ipcRenderer.invoke('updater-check'),
  updaterDownload: () => ipcRenderer.invoke('updater-download'),
  updaterInstall: () => ipcRenderer.send('updater-install'),
  onUpdaterEvent: (callback) => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('updater-event', handler)
    return () => ipcRenderer.removeListener('updater-event', handler)
  },

  // ===== 桌面偏好持久化 =====
  getDesktopPrefs: () => ipcRenderer.invoke('prefs-get'),
  setDesktopPrefs: (prefs) => ipcRenderer.invoke('prefs-set', prefs),

  // ===== 外链打开 =====
  openExternal: (url) => ipcRenderer.send('open-external', url),

  // ===== 应用信息 =====
  getAppInfo: () => ipcRenderer.invoke('app-info'),

  // ===== 桌面原生通知（任务 3）=====
  // 渲染进程调用：electronAPI.showNotification('刮削完成', '已处理 100 部影片')
  showNotification: (title, body, opts) => ipcRenderer.invoke('show-notification', title, body, opts),

  // ===== 开机自启（任务 5）=====
  setAutoLaunch: (enabled) => ipcRenderer.invoke('set-auto-launch', enabled),
  getAutoLaunch: () => ipcRenderer.invoke('get-auto-launch'),

  // ===== mdcx:// 协议唤起回调（任务 4）=====
  // 渲染进程注册：electronAPI.onOpenUrl(({ type, id, route, raw }) => { ... })
  onOpenUrl: (callback) => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('open-url', handler)
    return () => ipcRenderer.removeListener('open-url', handler)
  },

  // ===== 路由跳转回调（任务 6 配套，由全局快捷键 / mdcx:// 触发）=====
  onNavigateRoute: (callback) => {
    const handler = (_event, route) => callback(route)
    ipcRenderer.on('navigate-route', handler)
    return () => ipcRenderer.removeListener('navigate-route', handler)
  },

  // ===== 任务控制回调（任务 2 配套，由托盘菜单触发）=====
  onTaskControl: (callback) => {
    const handler = (_event, action) => callback(action)
    ipcRenderer.on('task-control', handler)
    return () => ipcRenderer.removeListener('task-control', handler)
  },

  // ===== 后端自动探测 =====
  detectBackend: () => ipcRenderer.invoke('backend-detect'),
})

// 兼容旧版调用（部分老组件可能直接用 window.electronAPI.openExternal）
