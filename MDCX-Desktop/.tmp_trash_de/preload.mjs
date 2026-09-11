import { contextBridge as i, ipcRenderer as e } from "electron";
i.exposeInMainWorld("electronAPI", {
  // 平台信息
  platform: process.platform,
  isElectron: !0,
  // ===== 窗口控制 =====
  windowMinimize: () => e.send("window-minimize"),
  windowMaximize: () => e.send("window-maximize"),
  windowClose: () => e.send("window-close"),
  windowToggleMaximize: () => e.send("window-toggle-maximize"),
  onWindowStateChange: (t) => {
    const n = (r, o) => t(o);
    return e.on("window-state-changed", n), () => e.removeListener("window-state-changed", n);
  },
  // ===== 系统托盘 =====
  trayToggle: () => e.send("tray-toggle"),
  trayShow: () => e.send("tray-show"),
  // ===== 全局快捷键 =====
  // 注册渲染进程请求的快捷键
  registerGlobalShortcut: (t) => e.invoke("global-shortcut-register", t),
  unregisterGlobalShortcut: (t) => e.invoke("global-shortcut-unregister", t),
  // 监听主进程触发的全局快捷键事件
  onGlobalShortcut: (t) => {
    const n = (r, o) => t(o);
    return e.on("global-shortcut-triggered", n), () => e.removeListener("global-shortcut-triggered", n);
  },
  // ===== 自动更新 =====
  updaterCheck: () => e.invoke("updater-check"),
  updaterDownload: () => e.invoke("updater-download"),
  updaterInstall: () => e.send("updater-install"),
  onUpdaterEvent: (t) => {
    const n = (r, o) => t(o);
    return e.on("updater-event", n), () => e.removeListener("updater-event", n);
  },
  // ===== 桌面偏好持久化 =====
  getDesktopPrefs: () => e.invoke("prefs-get"),
  setDesktopPrefs: (t) => e.invoke("prefs-set", t),
  // ===== 外链打开 =====
  openExternal: (t) => e.send("open-external", t),
  // ===== 应用信息 =====
  getAppInfo: () => e.invoke("app-info"),
  // ===== 桌面原生通知（任务 3）=====
  // 渲染进程调用：electronAPI.showNotification('刮削完成', '已处理 100 部影片')
  showNotification: (t, n, r) => e.invoke("show-notification", t, n, r),
  // ===== 开机自启（任务 5）=====
  setAutoLaunch: (t) => e.invoke("set-auto-launch", t),
  getAutoLaunch: () => e.invoke("get-auto-launch"),
  // ===== mdcx:// 协议唤起回调（任务 4）=====
  // 渲染进程注册：electronAPI.onOpenUrl(({ type, id, route, raw }) => { ... })
  onOpenUrl: (t) => {
    const n = (r, o) => t(o);
    return e.on("open-url", n), () => e.removeListener("open-url", n);
  },
  // ===== 路由跳转回调（任务 6 配套，由全局快捷键 / mdcx:// 触发）=====
  onNavigateRoute: (t) => {
    const n = (r, o) => t(o);
    return e.on("navigate-route", n), () => e.removeListener("navigate-route", n);
  },
  // ===== 任务控制回调（任务 2 配套，由托盘菜单触发）=====
  onTaskControl: (t) => {
    const n = (r, o) => t(o);
    return e.on("task-control", n), () => e.removeListener("task-control", n);
  },
  // ===== 文件夹选择器 =====
  selectFolder: () => e.invoke("select-folder"),
  // ===== 后端自动探测 =====
  detectBackend: () => e.invoke("backend-detect"),
  // ===== mpv 内嵌播放器 =====
  mpvStart: (t) => e.invoke("mpv-start", t),
  mpvCommand: (t) => e.send("mpv-command", t),
  mpvSetProp: (t, n) => e.send("mpv-set-prop", t, n),
  mpvStop: () => e.send("mpv-stop"),
  mpvExit: () => e.send("mpv-exit"),
  mpvToggleFullscreen: () => e.send("mpv-fullscreen"),
  mpvState: () => e.invoke("mpv-state"),
  mpvLog: () => e.invoke("mpv-log"),
  mpvContext: () => e.invoke("mpv-context"),
  onMpvExit: (t) => {
    const n = () => t();
    return e.on("mpv-exit", n), () => e.removeListener("mpv-exit", n);
  },
  onMpvState: (t) => {
    const n = (r, o) => t(o);
    return e.on("mpv-state", n), () => e.removeListener("mpv-state", n);
  },
  // OSD 显示 / 隐藏时切换鼠标穿透，让事件在 mpv 与控制条之间流转
  mpvOsdInteractive: (t) => e.send("mpv-osd-interactive", !!t)
});
