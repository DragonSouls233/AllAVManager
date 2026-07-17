import { app, BrowserWindow, Menu, ipcMain, shell, Tray, nativeImage, globalShortcut, nativeTheme, Notification, dialog } from 'electron'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import { appendFileSync, mkdirSync, readFileSync, writeFileSync, existsSync } from 'fs'
import { createRequire } from 'module'

// ESM 中加载 CommonJS 模块（electron-updater 是 CommonJS）
const require = createRequire(import.meta.url)

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

let mainWindow = null
let tray = null
let isQuiting = false

const isDev = process.env.NODE_ENV === 'development'

// ===== 命令行开关（保留原有 GPU 兼容性修复）=====
app.disableHardwareAcceleration()
app.commandLine.appendSwitch('no-sandbox')
app.commandLine.appendSwitch('disable-gpu')
app.commandLine.appendSwitch('disable-gpu-sandbox')
app.commandLine.appendSwitch('disable-gpu-compositing')
app.commandLine.appendSwitch('disable-gpu-rasterization')
app.commandLine.appendSwitch('in-process-gpu')
app.commandLine.appendSwitch('disable-features', 'VizDisplayCompositor')

// ===== 日志 =====
function writeLog(message) {
  try {
    const logDir = join(app.getPath('userData'), 'logs')
    mkdirSync(logDir, { recursive: true })
    appendFileSync(join(logDir, 'desktop.log'), `[${new Date().toISOString()}] ${message}\n`, 'utf8')
  } catch (error) {
    console.error(error)
  }
}

function createErrorHtml(title, detail) {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>body{margin:0;background:#111827;color:#e5e7eb;font-family:Arial,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;height:100vh}.box{max-width:760px;padding:32px;background:#1f2937;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.35)}h1{margin:0 0 16px;color:#60a5fa}pre{white-space:pre-wrap;color:#fca5a5;background:#111827;padding:16px;border-radius:8px}</style></head><body><div class="box"><h1>${title}</h1><p>MDCX Desktop start failed.</p><pre>${detail}</pre></div></body></html>`
}

// ===== 桌面偏好持久化 =====
const PREFS_FILE = () => join(app.getPath('userData'), 'desktop-prefs.json')

const DEFAULT_PREFS = {
  // 系统托盘
  enable_tray: true,
  minimize_to_tray: true,        // 关闭窗口时最小化到托盘
  close_to_tray: true,           // 点击关闭按钮时最小化到托盘（vs 直接退出）
  // 全局快捷键（空字符串表示禁用）
  shortcut_show_hide: 'CommandOrControl+Shift+M',  // 显示/隐藏主窗口
  shortcut_play_pause: 'CommandOrControl+Shift+P', // 播放/暂停 mpv
  shortcut_screenshot: 'CommandOrControl+Shift+S', // mpv 截图
  // 自动更新
  auto_update: true,
  // 启动行为
  start_minimized: false,
  // 主题（与前端 localStorage mdcx_theme 同步）
  theme: 'system'                // light / dark / system
}

function loadPrefs() {
  try {
    if (!existsSync(PREFS_FILE())) return { ...DEFAULT_PREFS }
    const data = JSON.parse(readFileSync(PREFS_FILE(), 'utf8'))
    return { ...DEFAULT_PREFS, ...data }
  } catch (e) {
    writeLog(`loadPrefs failed: ${e.message}`)
    return { ...DEFAULT_PREFS }
  }
}

function savePrefs(prefs) {
  try {
    writeFileSync(PREFS_FILE(), JSON.stringify(prefs, null, 2), 'utf8')
  } catch (e) {
    writeLog(`savePrefs failed: ${e.message}`)
  }
}

let currentPrefs = { ...DEFAULT_PREFS }

// ===== 创建主窗口 =====
function createWindow() {
  writeLog('createWindow start')
  Menu.setApplicationMenu(null)

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    // 隐藏原生标题栏，使用自定义 TitleBar.vue
    // macOS 上仍保留原生 traffic lights，Windows/Linux 完全自定义
    titleBarStyle: 'hidden',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: join(__dirname, 'preload.js')
    },
    title: '龙魂 - 视频管理系统',
    show: !currentPrefs.start_minimized,
    backgroundColor: '#111827'
  })

  // 窗口状态广播给渲染进程
  const broadcastWindowState = () => {
    if (!mainWindow) return
    const state = mainWindow.isMaximized() ? 'maximized' : 'normal'
    mainWindow.webContents.send('window-state-changed', state)
  }
  mainWindow.on('maximize', broadcastWindowState)
  mainWindow.on('unmaximize', broadcastWindowState)

  // 关闭按钮：根据偏好决定是隐藏到托盘还是退出
  mainWindow.on('close', (event) => {
    writeLog(`window close event, isQuiting=${isQuiting}, closeToTray=${currentPrefs.close_to_tray}`)
    if (!isQuiting && currentPrefs.close_to_tray && tray) {
      event.preventDefault()
      mainWindow.hide()
    }
  })

  mainWindow.on('closed', () => {
    writeLog('window closed')
    mainWindow = null
  })

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    const detail = `errorCode=${errorCode}\nerrorDescription=${errorDescription}\nurl=${validatedURL}`
    writeLog(`did-fail-load ${detail}`)
    mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(createErrorHtml('页面加载失败', detail))}`)
  })

  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    writeLog(`render-process-gone ${JSON.stringify(details)}`)
  })

  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    writeLog(`console level=${level} ${message} ${sourceId}:${line}`)
  })

  if (isDev) {
    writeLog('load dev url http://localhost:5173')
    mainWindow.loadURL('http://localhost:5173').catch((error) => {
      writeLog(`load dev failed ${error.stack || error.message}`)
      mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(createErrorHtml('开发模式加载失败', error.stack || error.message))}`)
    })
    mainWindow.webContents.openDevTools()
  } else {
    const indexPath = join(__dirname, '../dist/index.html')
    writeLog(`load file ${indexPath}`)
    mainWindow.loadFile(indexPath).catch((error) => {
      writeLog(`load file failed ${error.stack || error.message}`)
      mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(createErrorHtml('文件加载失败', `${indexPath}\n\n${error.stack || error.message}`))}`)
    })
  }
}

// ===== 系统托盘 =====
function createTray() {
  if (!currentPrefs.enable_tray) {
    if (tray) {
      tray.destroy()
      tray = null
    }
    return
  }
  if (tray) return  // 已存在

  // 优先加载 resources/icon.png，不存在则用内嵌 base64 默认图标
  let icon
  const iconPath = join(__dirname, '../resources/icon.png')
  if (existsSync(iconPath)) {
    icon = nativeImage.createFromPath(iconPath)
    if (icon.isEmpty()) {
      writeLog(`tray icon empty at ${iconPath}, fallback to default`)
      icon = null
    }
  }
  if (!icon) {
    // 内嵌 16x16 蓝色方块 PNG 作为兜底
    const iconBuffer = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAOklEQVR4nO3OQQ0AIBADwYJ/yzcCJBkSY4h+fn3/PwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7q2gkAAWcG5mEAAAAASUVORK5CYII=',
      'base64'
    )
    icon = nativeImage.createFromBuffer(iconBuffer)
  }

  tray = new Tray(icon)
  tray.setToolTip('龙魂视频管理系统')

  // 托盘菜单：显示主窗口/迷你模式/暂停任务/继续任务/退出
  const contextMenu = Menu.buildFromTemplate([
    { label: '显示主窗口', click: () => showMainWindow() },
    {
      label: '迷你模式',
      click: () => {
        // 切换主窗口在迷你（小尺寸置顶）与正常之间
        if (!mainWindow) return
        if (mainWindow.isMinimized()) mainWindow.restore()
        if (!mainWindow.isVisible()) mainWindow.show()
        // 简易迷你：缩小窗口并始终置顶
        if (mainWindow.isAlwaysOnTop()) {
          mainWindow.setAlwaysOnTop(false)
          mainWindow.setSize(1400, 900)
          mainWindow.center()
        } else {
          mainWindow.setSize(480, 320)
          mainWindow.setAlwaysOnTop(true)
        }
        mainWindow.focus()
      }
    },
    { type: 'separator' },
    {
      label: '暂停任务',
      click: () => {
        // 通知渲染进程暂停所有刮削/下载任务
        mainWindow?.webContents.send('task-control', 'pause')
        showNotification('MDCX 任务', '已暂停所有任务')
      }
    },
    {
      label: '继续任务',
      click: () => {
        mainWindow?.webContents.send('task-control', 'resume')
        showNotification('MDCX 任务', '已继续所有任务')
      }
    },
    { type: 'separator' },
    { label: '退出', click: () => quitApp() }
  ])

  tray.setContextMenu(contextMenu)
  // 单击显示主窗口
  tray.on('click', () => showMainWindow())
  // 双击切换主窗口显示/隐藏
  tray.on('double-click', () => {
    if (!mainWindow) {
      createWindow()
      return
    }
    if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
      mainWindow.hide()
    } else {
      showMainWindow()
    }
  })
}

function showMainWindow() {
  if (!mainWindow) {
    createWindow()
    return
  }
  if (mainWindow.isMinimized()) mainWindow.restore()
  if (!mainWindow.isVisible()) mainWindow.show()
  mainWindow.focus()
}

function quitApp() {
  isQuiting = true
  if (tray) {
    tray.destroy()
    tray = null
  }
  app.quit()
}

// ===== 桌面原生通知 =====
// 通知类型：刮削完成 / 订阅新片 / 下载完成 / 异常告警
// 通过 ipcMain.on('show-notification', ...) 接收渲染进程请求
function showNotification(title, body, opts = {}) {
  if (!Notification.isSupported()) {
    writeLog(`notification not supported, skip: ${title} - ${body}`)
    return null
  }
  const notification = new Notification({
    title: title || 'MDCX',
    body: body || '',
    silent: !!opts.silent,
    urgency: opts.urgency || 'normal'
  })
  // 点击通知聚焦主窗口
  notification.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      if (!mainWindow.isVisible()) mainWindow.show()
      mainWindow.focus()
    }
  })
  notification.show()
  return notification
}

// ===== 开机自启 =====
function setAutoLaunch(enabled) {
  try {
    app.setLoginItemSettings({
      openAtLogin: !!enabled,
      // Windows 上通过 args 标识自启项，便于后续区分启动来源
      args: ['--hidden']
    })
    writeLog(`setAutoLaunch(${enabled}) ok`)
    return true
  } catch (e) {
    writeLog(`setAutoLaunch failed: ${e.message}`)
    return false
  }
}

function getAutoLaunch() {
  try {
    return !!app.getLoginItemSettings().openAtLogin
  } catch (e) {
    return false
  }
}

// ===== 全局快捷键 =====
const registeredShortcuts = new Map()

function registerAllShortcuts() {
  unregisterAllShortcuts()

  const { shortcut_show_hide, shortcut_play_pause, shortcut_screenshot } = currentPrefs

  if (shortcut_show_hide) {
    try {
      const ok = globalShortcut.register(shortcut_show_hide, () => {
        if (!mainWindow) {
          createWindow()
        } else if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
          mainWindow.hide()
        } else {
          showMainWindow()
        }
        // 通知渲染进程
        if (mainWindow) mainWindow.webContents.send('global-shortcut-triggered', shortcut_show_hide)
      })
      if (ok) registeredShortcuts.set(shortcut_show_hide, 'show_hide')
      else writeLog(`failed to register shortcut: ${shortcut_show_hide}`)
    } catch (e) {
      writeLog(`register shortcut_show_hide failed: ${e.message}`)
    }
  }

  if (shortcut_play_pause) {
    try {
      const ok = globalShortcut.register(shortcut_play_pause, () => {
        if (mainWindow) mainWindow.webContents.send('global-shortcut-triggered', shortcut_play_pause)
      })
      if (ok) registeredShortcuts.set(shortcut_play_pause, 'play_pause')
    } catch (e) {
      writeLog(`register shortcut_play_pause failed: ${e.message}`)
    }
  }

  if (shortcut_screenshot) {
    try {
      const ok = globalShortcut.register(shortcut_screenshot, () => {
        if (mainWindow) mainWindow.webContents.send('global-shortcut-triggered', shortcut_screenshot)
      })
      if (ok) registeredShortcuts.set(shortcut_screenshot, 'screenshot')
    } catch (e) {
      writeLog(`register shortcut_screenshot failed: ${e.message}`)
    }
  }

  // ===== 固定全局快捷键（任务 6 要求）=====
  // Ctrl+Alt+R：显示/隐藏主窗口
  try {
    const ok = globalShortcut.register('CommandOrControl+Alt+R', () => {
      if (!mainWindow) {
        createWindow()
      } else if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
        mainWindow.hide()
      } else {
        showMainWindow()
      }
      if (mainWindow) mainWindow.webContents.send('global-shortcut-triggered', 'CommandOrControl+Alt+R')
    })
    if (ok) registeredShortcuts.set('CommandOrControl+Alt+R', 'toggle_window')
    else writeLog('failed to register shortcut: CommandOrControl+Alt+R')
  } catch (e) {
    writeLog(`register toggle_window failed: ${e.message}`)
  }

  // Ctrl+Alt+E：打开探索页（通知渲染进程跳转 /movies）
  try {
    const ok = globalShortcut.register('CommandOrControl+Alt+E', () => {
      showMainWindow()
      // 通知渲染进程跳转路由
      mainWindow?.webContents.send('navigate-route', '/movies')
      mainWindow?.webContents.send('global-shortcut-triggered', 'CommandOrControl+Alt+E')
    })
    if (ok) registeredShortcuts.set('CommandOrControl+Alt+E', 'open_explore')
    else writeLog('failed to register shortcut: CommandOrControl+Alt+E')
  } catch (e) {
    writeLog(`register open_explore failed: ${e.message}`)
  }
}

function unregisterAllShortcuts() {
  for (const accel of registeredShortcuts.keys()) {
    try {
      globalShortcut.unregister(accel)
    } catch (e) {
      writeLog(`unregister ${accel} failed: ${e.message}`)
    }
  }
  registeredShortcuts.clear()
}

// ===== 自动更新（electron-updater）=====
// 注意：electron-updater 是可选依赖，未安装时优雅降级
let autoUpdater = null
try {
  autoUpdater = require('electron-updater').autoUpdater
} catch (e) {
  writeLog('electron-updater not installed, auto-update disabled')
}

function setupAutoUpdater() {
  if (!autoUpdater || !currentPrefs.auto_update) return

  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true

  const sendUpdaterEvent = (type, payload = {}) => {
    if (mainWindow) mainWindow.webContents.send('updater-event', { type, ...payload })
  }

  autoUpdater.on('checking-for-update', () => sendUpdaterEvent('checking'))
  autoUpdater.on('update-available', (info) => sendUpdaterEvent('available', { version: info.version, releaseNotes: info.releaseNotes }))
  autoUpdater.on('update-not-available', () => sendUpdaterEvent('not-available'))
  autoUpdater.on('download-progress', (progress) => sendUpdaterEvent('progress', { percent: progress.percent, transferred: progress.transferred, total: progress.total }))
  autoUpdater.on('update-downloaded', (info) => sendUpdaterEvent('downloaded', { version: info.version }))
  autoUpdater.on('error', (err) => sendUpdaterEvent('error', { message: err?.message || String(err) }))

  // 启动后 30 秒检查一次更新
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((e) => writeLog(`autoUpdater.checkForUpdates failed: ${e.message}`))
  }, 30_000)
}

// ===== 单例锁 =====
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  writeLog('another instance is running, quitting')
  app.quit()
} else {
  // Windows/Linux 通过 second-instance 接收 mdcx:// 协议唤起
  app.on('second-instance', (_event, commandLine) => {
    writeLog('second-instance triggered, showing main window')
    showMainWindow()
    // 在 Windows 上，协议 URL 出现在 argv 末尾
    const lastArg = commandLine?.slice(-1)?.[0] || ''
    if (typeof lastArg === 'string' && lastArg.startsWith('mdcx://')) {
      handleOpenUrl(lastArg)
    }
  })
}

// ===== mdcx:// 协议注册 =====
// 支持 URL：mdcx://movie/{id} / mdcx://actor/{id} / mdcx://play/{id}
function handleOpenUrl(url) {
  if (!url || !url.startsWith('mdcx://')) return
  writeLog(`handleOpenUrl: ${url}`)
  try {
    const u = new URL(url)
    const segs = u.pathname.split('/').filter(Boolean)
    // mdcx://movie/{id} / mdcx://actor/{id} / mdcx://play/{id}
    if (segs.length < 2) {
      writeLog(`invalid mdcx url: ${url}`)
      return
    }
    const [type, id] = segs
    let route = null
    if (type === 'movie') route = `/movies`
    else if (type === 'actor') route = `/actors/${id}`
    else if (type === 'play') route = `/play/${id}`
    else {
      writeLog(`unknown mdcx url type: ${type}`)
      return
    }
    // 显示主窗口并通知渲染进程跳转
    showMainWindow()
    if (mainWindow) {
      mainWindow.webContents.send('open-url', { type, id, route, raw: url })
      if (route) mainWindow.webContents.send('navigate-route', route)
    }
  } catch (e) {
    writeLog(`handleOpenUrl failed: ${e.message}`)
  }
}

// macOS 上从 Dock/邮件唤起时通过 open-url 事件传入 mdcx://
app.on('open-url', (event, url) => {
  event.preventDefault()
  handleOpenUrl(url)
})

// ===== 应用生命周期 =====
app.whenReady().then(() => {
  writeLog('app ready')
  currentPrefs = loadPrefs()

  // 应用主题
  if (currentPrefs.theme === 'dark') nativeTheme.themeSource = 'dark'
  else if (currentPrefs.theme === 'light') nativeTheme.themeSource = 'light'
  else nativeTheme.themeSource = 'system'

  // 注册 mdcx:// 协议
  try {
    const ok = app.setAsDefaultProtocolClient('mdcx')
    writeLog(`setAsDefaultProtocolClient('mdcx') -> ${ok}`)
  } catch (e) {
    writeLog(`setAsDefaultProtocolClient failed: ${e.message}`)
  }

  createWindow()
  createTray()
  registerAllShortcuts()
  setupAutoUpdater()
}).catch((error) => {
  writeLog(`app ready failed ${error.stack || error.message}`)
})

app.on('window-all-closed', () => {
  writeLog('window-all-closed')
  if (process.platform !== 'darwin') {
    if (currentPrefs.minimize_to_tray && tray) {
      // 已在 close 事件中处理隐藏
    } else {
      quitApp()
    }
  }
})

app.on('activate', () => {
  writeLog('activate')
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  } else {
    showMainWindow()
  }
})

app.on('before-quit', () => {
  isQuiting = true
})

app.on('will-quit', () => {
  // 注销全局快捷键
  unregisterAllShortcuts()
  // 销毁系统托盘
  if (tray) {
    try {
      tray.destroy()
    } catch (e) {}
    tray = null
  }
})

// ===== IPC 处理 =====
ipcMain.on('open-external', (_event, url) => {
  shell.openExternal(url)
})

// 窗口控制
ipcMain.on('window-minimize', () => mainWindow?.minimize())
ipcMain.on('window-maximize', () => mainWindow?.maximize())
ipcMain.on('window-close', () => mainWindow?.close())
ipcMain.on('window-toggle-maximize', () => {
  if (!mainWindow) return
  if (mainWindow.isMaximized()) mainWindow.unmaximize()
  else mainWindow.maximize()
})

// 托盘
ipcMain.on('tray-toggle', () => {
  if (mainWindow?.isVisible()) mainWindow.hide()
  else showMainWindow()
})
ipcMain.on('tray-show', () => showMainWindow())

// 全局快捷键动态注册（让前端可临时注册额外的快捷键）
ipcMain.handle('global-shortcut-register', (event, accelerator) => {
  try {
    if (registeredShortcuts.has(accelerator)) return true
    const ok = globalShortcut.register(accelerator, () => {
      mainWindow?.webContents.send('global-shortcut-triggered', accelerator)
    })
    if (ok) registeredShortcuts.set(accelerator, 'dynamic')
    return ok
  } catch (e) {
    writeLog(`dynamic register ${accelerator} failed: ${e.message}`)
    return false
  }
})
ipcMain.handle('global-shortcut-unregister', (event, accelerator) => {
  try {
    if (registeredShortcuts.has(accelerator) && registeredShortcuts.get(accelerator) === 'dynamic') {
      globalShortcut.unregister(accelerator)
      registeredShortcuts.delete(accelerator)
    }
    return true
  } catch (e) {
    return false
  }
})

// 自动更新 IPC
ipcMain.handle('updater-check', async () => {
  if (!autoUpdater) return { ok: false, error: 'electron-updater not installed' }
  try {
    const result = await autoUpdater.checkForUpdates()
    return { ok: true, version: result?.updateInfo?.version || null }
  } catch (e) {
    return { ok: false, error: e.message }
  }
})
ipcMain.handle('updater-download', async () => {
  if (!autoUpdater) return { ok: false, error: 'electron-updater not installed' }
  try {
    await autoUpdater.downloadUpdate()
    return { ok: true }
  } catch (e) {
    return { ok: false, error: e.message }
  }
})
ipcMain.on('updater-install', () => {
  if (autoUpdater) {
    isQuiting = true
    autoUpdater.quitAndInstall()
  }
})

// 偏好持久化
ipcMain.handle('prefs-get', () => currentPrefs)
ipcMain.handle('prefs-set', (event, prefs) => {
  const oldPrefs = { ...currentPrefs }
  currentPrefs = { ...currentPrefs, ...prefs }
  savePrefs(currentPrefs)

  // 即时应用部分偏好变更
  if (oldPrefs.enable_tray !== currentPrefs.enable_tray) {
    createTray()  // 创建或销毁托盘
  }
  if (oldPrefs.shortcut_show_hide !== currentPrefs.shortcut_show_hide ||
      oldPrefs.shortcut_play_pause !== currentPrefs.shortcut_play_pause ||
      oldPrefs.shortcut_screenshot !== currentPrefs.shortcut_screenshot) {
    registerAllShortcuts()
  }
  if (oldPrefs.theme !== currentPrefs.theme) {
    if (currentPrefs.theme === 'dark') nativeTheme.themeSource = 'dark'
    else if (currentPrefs.theme === 'light') nativeTheme.themeSource = 'light'
    else nativeTheme.themeSource = 'system'
  }

  return { ok: true, prefs: currentPrefs }
})

// 应用信息
ipcMain.handle('app-info', () => ({
  version: app.getVersion(),
  name: app.getName(),
  platform: process.platform,
  arch: process.arch,
  electron: process.versions.electron,
  chrome: process.versions.chrome,
  node: process.versions.node,
  userData: app.getPath('userData'),
  logsPath: join(app.getPath('userData'), 'logs'),
  prefsPath: PREFS_FILE(),
}))

// ===== 桌面原生通知 IPC（任务 3）=====
// 渲染进程通过 ipcRenderer.invoke('show-notification', title, body) 调用
ipcMain.handle('show-notification', (_event, title, body, opts) => {
  try {
    const n = showNotification(title, body, opts || {})
    return { ok: !!n }
  } catch (e) {
    writeLog(`show-notification IPC failed: ${e.message}`)
    return { ok: false, error: e.message }
  }
})

// ===== 开机自启 IPC（任务 5）=====
ipcMain.handle('set-auto-launch', (_event, enabled) => {
  const ok = setAutoLaunch(enabled)
  return { ok, enabled: !!enabled }
})

ipcMain.handle('get-auto-launch', () => {
  return { enabled: getAutoLaunch() }
})

// ===== 路由跳转 IPC（任务 6 配套）=====
// 由主进程发起，渲染进程通过 onNavigateRoute(callback) 监听
// 已通过 mainWindow.webContents.send('navigate-route', route) 推送

// ===== mdcx:// 协议 IPC（任务 4 配套）=====
// 由主进程发起，渲染进程通过 onOpenUrl(callback) 监听
// 已通过 mainWindow.webContents.send('open-url', payload) 推送

// ===== 任务控制 IPC（任务 2 配套）=====
// 由托盘菜单发起，渲染进程通过 onTaskControl(callback) 监听
// 已通过 mainWindow.webContents.send('task-control', 'pause'/'resume') 推送

// ===== 后端自动探测 IPC =====
const BACKEND_PORT = 8420

function tryConnect(host, port, timeout = 2000) {
  return new Promise((resolve) => {
    const http = require('http')
    const url = `http://${host}:${port}/api/v1/health/version`
    const req = http.get(url, { timeout }, (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk })
      res.on('end', () => {
        try {
          const json = JSON.parse(data)
          resolve({ ok: true, url: `http://${host}:${port}`, version: json.version || '' })
        } catch {
          resolve({ ok: true, url: `http://${host}:${port}`, version: '' })
        }
      })
    })
    req.on('error', () => resolve({ ok: false, url: `http://${host}:${port}` }))
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, url: `http://${host}:${port}` }) })
  })
}

function generateCandidates() {
  const candidates = []
  // 1. localhost
  candidates.push('127.0.0.1')
  candidates.push('localhost')
  // 2. 本机 IP 探测（通过 os 模块）
  try {
    const os = require('os')
    const interfaces = os.networkInterfaces()
    for (const name of Object.keys(interfaces)) {
      for (const iface of interfaces[name]) {
        if (iface.family === 'IPv4' && !iface.internal) {
          candidates.push(iface.address)
          // 生成同网段的 .1 (通常是网关/服务器)
          const parts = iface.address.split('.')
          if (parts.length === 4) {
            candidates.push(`${parts[0]}.${parts[1]}.${parts[2]}.1`)
            candidates.push(`${parts[0]}.${parts[1]}.${parts[2]}.100`)
            candidates.push(`${parts[0]}.${parts[1]}.${parts[2]}.200`)
          }
        }
      }
    }
  } catch (e) {
    writeLog(`get network interfaces failed: ${e.message}`)
  }
  return [...new Set(candidates)]
}

async function detectBackend() {
  const candidates = generateCandidates()
  writeLog(`backend detection candidates: ${JSON.stringify(candidates)}`)
  for (const host of candidates) {
    try {
      const result = await tryConnect(host, BACKEND_PORT)
      if (result.ok) {
        writeLog(`backend detected at ${result.url}`)
        return result
      }
    } catch (e) {
      // 静默
    }
  }
  writeLog('backend detection: none found')
  return { ok: false, url: '', version: '' }
}

// ===== 文件夹选择器（用于前端选择媒体目录）=====
ipcMain.handle('select-folder', async () => {
  if (!mainWindow) return { canceled: true, path: null }
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: '选择媒体目录'
  })
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true, path: null }
  }
  return { canceled: false, path: result.filePaths[0] }
})

ipcMain.handle('backend-detect', async () => {
  const result = await detectBackend()
  return result
})
