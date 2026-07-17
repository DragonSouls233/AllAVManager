import { contextBridge as a, ipcRenderer as e } from "electron";
a.exposeInMainWorld("electronAPI", {
  // 平台信息
  platform: process.platform,
  isElectron: !0,
  // ===== 窗口控制 =====
  windowMinimize: () => e.send("window-minimize"),
  windowMaximize: () => e.send("window-maximize"),
  windowClose: () => e.send("window-close"),
  windowToggleMaximize: () => e.send("window-toggle-maximize"),
  onWindowStateChange: (n) => {
    const t = (r, o) => n(o);
    return e.on("window-state-changed", t), () => e.removeListener("window-state-changed", t);
  },
  // ===== 系统托盘 =====
  trayToggle: () => e.send("tray-toggle"),
  trayShow: () => e.send("tray-show"),
  // ===== 全局快捷键 =====
  // 注册渲染进程请求的快捷键
  registerGlobalShortcut: (n) => e.invoke("global-shortcut-register", n),
  unregisterGlobalShortcut: (n) => e.invoke("global-shortcut-unregister", n),
  // 监听主进程触发的全局快捷键事件
  onGlobalShortcut: (n) => {
    const t = (r, o) => n(o);
    return e.on("global-shortcut-triggered", t), () => e.removeListener("global-shortcut-triggered", t);
  },
  // ===== 自动更新 =====
  updaterCheck: () => e.invoke("updater-check"),
  updaterDownload: () => e.invoke("updater-download"),
  updaterInstall: () => e.send("updater-install"),
  onUpdaterEvent: (n) => {
    const t = (r, o) => n(o);
    return e.on("updater-event", t), () => e.removeListener("updater-event", t);
  },
  // ===== 桌面偏好持久化 =====
  getDesktopPrefs: () => e.invoke("prefs-get"),
  setDesktopPrefs: (n) => e.invoke("prefs-set", n),
  // ===== 外链打开 =====
  openExternal: (n) => e.send("open-external", n),
  // ===== 应用信息 =====
  getAppInfo: () => e.invoke("app-info"),
  // ===== 桌面原生通知（任务 3）=====
  // 渲染进程调用：electronAPI.showNotification('刮削完成', '已处理 100 部影片')
  showNotification: (n, t, r) => e.invoke("show-notification", n, t, r),
  // ===== 开机自启（任务 5）=====
  setAutoLaunch: (n) => e.invoke("set-auto-launch", n),
  getAutoLaunch: () => e.invoke("get-auto-launch"),
  // ===== mdcx:// 协议唤起回调（任务 4）=====
  // 渲染进程注册：electronAPI.onOpenUrl(({ type, id, route, raw }) => { ... })
  onOpenUrl: (n) => {
    const t = (r, o) => n(o);
    return e.on("open-url", t), () => e.removeListener("open-url", t);
  },
  // ===== 路由跳转回调（任务 6 配套，由全局快捷键 / mdcx:// 触发）=====
  onNavigateRoute: (n) => {
    const t = (r, o) => n(o);
    return e.on("navigate-route", t), () => e.removeListener("navigate-route", t);
  },
  // ===== 任务控制回调（任务 2 配套，由托盘菜单触发）=====
  onTaskControl: (n) => {
    const t = (r, o) => n(o);
    return e.on("task-control", t), () => e.removeListener("task-control", t);
  },
  // ===== 文件夹选择器 =====
  selectFolder: () => e.invoke("select-folder"),
  // ===== 后端自动探测 =====
  detectBackend: () => e.invoke("backend-detect")
});
