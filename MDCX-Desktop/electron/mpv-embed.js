/**
 * mpv 内嵌播放器（Electron 主进程侧）
 *
 * 为什么不用 Web 播放器：Chromium 的 MSE 解不了 HEVC/H.265（尤其 10bit），
 * NAS 片源只能靠 ffmpeg 转码才能播，CPU 打满、拖动要等切片。
 * mpv 用 --wid 把自己嵌进 Electron 窗口的原生 HWND，GPU 硬解直通，
 * 零转码、拖动秒开。前端 OSD 走 JSON IPC 控制。
 *
 * 链路：
 *   Electron 主窗口 HWND ──(--wid)──► mpv 子进程（原生渲染 + 硬解）
 *                    └──(webContents.send)──► OSD overlay 窗口（Vue 控制层）
 *   OSD ──(JSON IPC over \\.\pipe\)──► 主进程 ──► mpv
 */
import { spawn } from 'child_process'
import net from 'net'
import fs from 'fs'
import path from 'path'
import { app } from 'electron'

/** 当前 mpv 子进程 */
let mpvProc = null
/** 与 mpv 的 JSON IPC 命名管道连接 */
let ipcSocket = null
/** 承载视频的宿主窗口 */
let hostWindow = null
/** 状态轮询定时器 */
let pollTimer = null
/** 收到的 mpv 日志尾部（用于诊断硬解是否生效） */
let logTail = []

const OBSERVED = ['time-pos', 'pause', 'duration', 'volume', 'mute', 'path', 'speed', 'hwdec-current']

const state = {
  running: false,
  loaded: false,
  pause: true,
  timePos: 0,
  duration: 0,
  volume: 100,
  mute: false,
  speed: 1,
  path: '',
  hwdec: '',
  error: ''
}

/**
 * 定位 mpv.exe：
 *   1) 打包后 resources/vendor/mpv/mpv.exe
 *   2) 开发期 <project>/vendor/mpv/mpv.exe
 *   3) 用户在设置里指定的路径
 *   4) 系统常见安装位置 / PATH
 */
export function findMpvPath(customPath) {
  const candidates = []

  if (customPath) candidates.push(customPath)

  // 打包后（extraResources 会把 vendor 放到 resources/ 下）
  try {
    candidates.push(path.join(process.resourcesPath || '', 'vendor', 'mpv', 'mpv.exe'))
  } catch {
    /* resourcesPath 在某些场景不可用 */
  }
  // 开发期
  candidates.push(path.join(app.getAppPath(), 'vendor', 'mpv', 'mpv.exe'))
  // Windows 常见安装位置
  candidates.push(
    'C:\\Program Files\\mpv\\mpv.exe',
    'C:\\Program Files (x86)\\mpv\\mpv.exe',
    path.join(app.getPath('home'), 'scoop', 'apps', 'mpv', 'current', 'mpv.exe')
  )

  for (const p of candidates) {
    try {
      if (p && fs.existsSync(p)) return p
    } catch {
      /* 路径非法，跳过 */
    }
  }
  return null
}

function pushLog(line) {
  const text = String(line).trim()
  if (!text) return
  logTail.push(text)
  if (logTail.length > 200) logTail.shift()
}

function broadcast() {
  if (!hostWindow || hostWindow.isDestroyed()) return
  // 同时发给宿主窗口和 OSD overlay（overlay 由 main.js 注册进 osdWindows）
  hostWindow.webContents.send('mpv-state', { ...state })
  if (global.__mpvOsdWindows) {
    for (const w of global.__mpvOsdWindows) {
      if (w && !w.isDestroyed()) w.webContents.send('mpv-state', { ...state })
    }
  }
}

function sendCommand(args) {
  if (!ipcSocket || ipcSocket.destroyed) return false
  try {
    ipcSocket.write(JSON.stringify({ command: args }) + '\n')
    return true
  } catch {
    return false
  }
}

function onIpcLine(line) {
  try {
    const msg = JSON.parse(line)
    if (msg.event === 'property-change' && msg.name) {
      switch (msg.name) {
        case 'time-pos': state.timePos = msg.data || 0; break
        case 'pause': state.pause = !!msg.data; break
        case 'duration': state.duration = msg.data || 0; break
        case 'volume': state.volume = msg.data ?? 100; break
        case 'mute': state.mute = !!msg.data; break
        case 'speed': state.speed = msg.data || 1; break
      case 'path': state.path = msg.data || ''; break
      case 'hwdec-current':
        // 实际生效的硬解方式（'no' 表示退回软件解码）
        state.hwdec = msg.data && msg.data !== 'no' ? msg.data : ''
        break
      default: break
      }
      broadcast()
    } else if (msg.event === 'file-loaded') {
      state.loaded = true
      broadcast()
    } else if (msg.event === 'end-file') {
      state.loaded = false
      broadcast()
    }
  } catch {
    /* 非 JSON 行忽略 */
  }
}

function connectIpc(pipePath, attempt = 0) {
  const sock = net.connect(pipePath)
  ipcSocket = sock

  let buf = ''
  sock.on('connect', () => {
    // 订阅需要回传的属性，之后 mpv 会主动推 property-change
    OBSERVED.forEach((name, i) => {
      sendCommand(['observe_property', i + 1, name])
    })
  })

  sock.on('data', (chunk) => {
    buf += chunk.toString('utf8')
    let idx
    while ((idx = buf.indexOf('\n')) >= 0) {
      onIpcLine(buf.slice(0, idx))
      buf = buf.slice(idx + 1)
    }
  })

  sock.on('error', () => { /* 管道未就绪，等 close 后重试 */ })
  sock.on('close', () => {
    ipcSocket = null
    // mpv 还在跑但管道尚未就绪 → 退避重试（最多 ~5s）
    if (attempt < 12 && mpvProc && !mpvProc.killed) {
      setTimeout(() => connectIpc(pipePath, attempt + 1), 400)
    }
  })
}

/**
 * 启动 mpv 并嵌入指定窗口。
 * @param {BrowserWindow} win 宿主窗口（视频画面画在它的客户区）
 * @param {object} opts { url, start, mpvPath, subFile, audioTrack }
 */
export function startMpv(win, opts = {}) {
  stopMpv()
  hostWindow = win

  const mpvPath = findMpvPath(opts.mpvPath)
  if (!mpvPath) {
    state.error = '未找到 mpv.exe：请安装 mpv，或在设置里指定 mpv 路径'
    state.running = false
    broadcast()
    return { ok: false, error: state.error }
  }

  const handle = win.getNativeWindowHandle()
  // Windows: HWND（x64 为 8 字节）；其他平台退回 4 字节读法
  let wid = 0
  try {
    wid = handle.length >= 8 ? handle.readBigUInt64LE(0) : BigInt(handle.readUInt32LE(0))
  } catch {
    wid = 0
  }

  const pipePath = `\\\\.\\pipe\\mdcx-mpv-${process.pid}`
  state.error = ''
  state.hwdec = ''
  logTail = []

  const args = [
    opts.url,
    `--wid=${wid}`,
    '--no-border',
    '--osc=no',
    '--window-dragging=no',
    '--force-window=yes',
    '--idle=yes',
    '--keep-open=always',
    '--no-focus-on-open',
    `--input-ipc-server=${pipePath}`,
    '--hwdec=auto-safe',
    '--vo=gpu',
    '--gpu-api=d3d11',
    '--sub-auto=all',
    '--audio-file-auto=all',
    '--osd-level=0',
    '--no-config'
  ]
  if (opts.start && opts.start > 0) args.push(`--start=${opts.start}`)
  if (opts.subFile) args.push(`--sub-file=${opts.subFile}`)

  mpvProc = spawn(mpvPath, args, { windowsHide: true })

  mpvProc.stdout?.on('data', (d) => pushLog(d.toString()))
  mpvProc.stderr?.on('data', (d) => pushLog(d.toString()))
  mpvProc.on('error', (e) => {
    state.error = `mpv 启动失败: ${e.message}`
    state.running = false
    broadcast()
  })
  mpvProc.on('exit', () => {
    state.running = false
    state.loaded = false
    mpvProc = null
    broadcast()
  })

  // mpv 要先起来才会监听管道，稍等再连
  setTimeout(() => connectIpc(pipePath), 600)

  state.running = true
  broadcast()
  return { ok: true, mpvPath, wid: String(wid) }
}

export function commandMpv(args) {
  return sendCommand(args)
}

export function setProperty(name, value) {
  return sendCommand(['set_property', name, value])
}

export function stopMpv() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  try {
    if (ipcSocket && !ipcSocket.destroyed) {
      ipcSocket.write(JSON.stringify({ command: ['quit'] }) + '\n')
      ipcSocket.end()
    }
  } catch {
    /* 忽略 */
  }
  ipcSocket = null

  if (mpvProc && !mpvProc.killed) {
    try { mpvProc.kill() } catch { /* 忽略 */ }
  }
  mpvProc = null
  state.running = false
  state.loaded = false
}

export function getMpvState() {
  return { ...state }
}

export function getMpvLog() {
  return logTail.slice(-60)
}
