import { app as l, nativeTheme as _, BrowserWindow as T, ipcMain as i, shell as te, globalShortcut as k, Menu as j, nativeImage as V, Tray as ne, Notification as q, dialog as oe } from "electron";
import { spawn as se } from "child_process";
import re from "net";
import ae, { mkdirSync as ie, appendFileSync as le, existsSync as Q, readFileSync as ce, writeFileSync as de } from "fs";
import E, { dirname as ue, join as b } from "path";
import { fileURLToPath as fe } from "url";
import { createRequire as pe } from "module";
let m = null, y = null, z = null, O = [];
const he = ["time-pos", "pause", "duration", "volume", "mute", "path", "speed", "hwdec-current"], u = {
  running: !1,
  loaded: !1,
  pause: !0,
  timePos: 0,
  duration: 0,
  volume: 100,
  mute: !1,
  speed: 1,
  path: "",
  hwdec: "",
  error: ""
};
function me(t) {
  const e = [];
  t && e.push(t);
  try {
    e.push(E.join(process.resourcesPath || "", "vendor", "mpv", "mpv.exe"));
  } catch {
  }
  e.push(E.join(l.getAppPath(), "vendor", "mpv", "mpv.exe")), e.push(
    "C:\\Program Files\\mpv\\mpv.exe",
    "C:\\Program Files (x86)\\mpv\\mpv.exe",
    E.join(l.getPath("home"), "scoop", "apps", "mpv", "current", "mpv.exe")
  );
  for (const o of e)
    try {
      if (o && ae.existsSync(o)) return o;
    } catch {
    }
  return null;
}
function J(t) {
  const e = String(t).trim();
  e && (O.push(e), O.length > 200 && O.shift());
}
function $() {
  if (!(!z || z.isDestroyed()) && (z.webContents.send("mpv-state", { ...u }), global.__mpvOsdWindows))
    for (const t of global.__mpvOsdWindows)
      t && !t.isDestroyed() && t.webContents.send("mpv-state", { ...u });
}
function B(t) {
  if (!y || y.destroyed) return !1;
  try {
    return y.write(JSON.stringify({ command: t }) + `
`), !0;
  } catch {
    return !1;
  }
}
function ge(t) {
  try {
    const e = JSON.parse(t);
    if (e.event === "property-change" && e.name) {
      switch (e.name) {
        case "time-pos":
          u.timePos = e.data || 0;
          break;
        case "pause":
          u.pause = !!e.data;
          break;
        case "duration":
          u.duration = e.data || 0;
          break;
        case "volume":
          u.volume = e.data ?? 100;
          break;
        case "mute":
          u.mute = !!e.data;
          break;
        case "speed":
          u.speed = e.data || 1;
          break;
        case "path":
          u.path = e.data || "";
          break;
        case "hwdec-current":
          u.hwdec = e.data && e.data !== "no" ? e.data : "";
          break;
        default:
          break;
      }
      $();
    } else e.event === "file-loaded" ? (u.loaded = !0, $()) : e.event === "end-file" && (u.loaded = !1, $());
  } catch {
  }
}
function H(t, e = 0) {
  const o = re.connect(t);
  y = o;
  let s = "";
  o.on("connect", () => {
    he.forEach((c, a) => {
      B(["observe_property", a + 1, c]);
    });
  }), o.on("data", (c) => {
    s += c.toString("utf8");
    let a;
    for (; (a = s.indexOf(`
`)) >= 0; )
      ge(s.slice(0, a)), s = s.slice(a + 1);
  }), o.on("error", () => {
  }), o.on("close", () => {
    y = null, e < 12 && m && !m.killed && setTimeout(() => H(t, e + 1), 400);
  });
}
function we(t, e = {}) {
  var x, S;
  M(), z = t;
  const o = me(e.mpvPath);
  if (!o)
    return u.error = "未找到 mpv.exe：请安装 mpv，或在设置里指定 mpv 路径", u.running = !1, $(), { ok: !1, error: u.error };
  const s = t.getNativeWindowHandle();
  let c = 0;
  try {
    c = s.length >= 8 ? s.readBigUInt64LE(0) : BigInt(s.readUInt32LE(0));
  } catch {
    c = 0;
  }
  const a = `\\\\.\\pipe\\mdcx-mpv-${process.pid}`;
  u.error = "", u.hwdec = "", O = [];
  const A = [
    e.url,
    `--wid=${c}`,
    "--no-border",
    "--osc=no",
    "--window-dragging=no",
    "--force-window=yes",
    "--idle=yes",
    "--keep-open=always",
    "--no-focus-on-open",
    `--input-ipc-server=${a}`,
    "--hwdec=auto-safe",
    "--vo=gpu",
    "--gpu-api=d3d11",
    "--sub-auto=all",
    "--audio-file-auto=all",
    "--osd-level=0",
    "--no-config"
  ];
  return e.start && e.start > 0 && A.push(`--start=${e.start}`), e.subFile && A.push(`--sub-file=${e.subFile}`), m = se(o, A, { windowsHide: !0 }), (x = m.stdout) == null || x.on("data", (v) => J(v.toString())), (S = m.stderr) == null || S.on("data", (v) => J(v.toString())), m.on("error", (v) => {
    u.error = `mpv 启动失败: ${v.message}`, u.running = !1, $();
  }), m.on("exit", () => {
    u.running = !1, u.loaded = !1, m = null, $();
  }), setTimeout(() => H(a), 600), u.running = !0, $(), { ok: !0, mpvPath: o, wid: String(c) };
}
function ye(t) {
  return B(t);
}
function ve(t, e) {
  return B(["set_property", t, e]);
}
function M() {
  try {
    y && !y.destroyed && (y.write(JSON.stringify({ command: ["quit"] }) + `
`), y.end());
  } catch {
  }
  if (y = null, m && !m.killed)
    try {
      m.kill();
    } catch {
    }
  m = null, u.running = !1, u.loaded = !1;
}
function be() {
  return { ...u };
}
function ke() {
  return O.slice(-60);
}
const N = pe(import.meta.url), Ae = fe(import.meta.url), P = ue(Ae);
let n = null, h = null, D = !1;
const Y = process.env.NODE_ENV === "development";
l.disableHardwareAcceleration();
l.commandLine.appendSwitch("no-sandbox");
l.commandLine.appendSwitch("disable-gpu");
l.commandLine.appendSwitch("disable-gpu-sandbox");
l.commandLine.appendSwitch("disable-gpu-compositing");
l.commandLine.appendSwitch("disable-gpu-rasterization");
l.commandLine.appendSwitch("in-process-gpu");
l.commandLine.appendSwitch("disable-features", "VizDisplayCompositor");
function r(t) {
  try {
    const e = b(l.getPath("userData"), "logs");
    ie(e, { recursive: !0 }), le(b(e, "desktop.log"), `[${(/* @__PURE__ */ new Date()).toISOString()}] ${t}
`, "utf8");
  } catch (e) {
    console.error(e);
  }
}
function F(t, e) {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${t}</title><style>body{margin:0;background:#111827;color:#e5e7eb;font-family:Arial,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;height:100vh}.box{max-width:760px;padding:32px;background:#1f2937;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.35)}h1{margin:0 0 16px;color:#60a5fa}pre{white-space:pre-wrap;color:#fca5a5;background:#111827;padding:16px;border-radius:8px}</style></head><body><div class="box"><h1>${t}</h1><p>MDCX Desktop start failed.</p><pre>${e}</pre></div></body></html>`;
}
const L = () => b(l.getPath("userData"), "desktop-prefs.json"), I = {
  // 系统托盘
  enable_tray: !0,
  minimize_to_tray: !0,
  // 关闭窗口时最小化到托盘
  close_to_tray: !0,
  // 点击关闭按钮时最小化到托盘（vs 直接退出）
  // 全局快捷键（空字符串表示禁用）
  shortcut_show_hide: "CommandOrControl+Shift+M",
  // 显示/隐藏主窗口
  shortcut_play_pause: "CommandOrControl+Shift+P",
  // 播放/暂停 mpv
  shortcut_screenshot: "CommandOrControl+Shift+S",
  // mpv 截图
  // 自动更新
  auto_update: !0,
  // 启动行为
  start_minimized: !1,
  // 主题（与前端 localStorage mdcx_theme 同步）
  theme: "system"
  // light / dark / system
};
function $e() {
  try {
    if (!Q(L())) return { ...I };
    const t = JSON.parse(ce(L(), "utf8"));
    return { ...I, ...t };
  } catch (t) {
    return r(`loadPrefs failed: ${t.message}`), { ...I };
  }
}
function _e(t) {
  try {
    de(L(), JSON.stringify(t, null, 2), "utf8");
  } catch (e) {
    r(`savePrefs failed: ${e.message}`);
  }
}
let f = { ...I };
function C() {
  r("createWindow start"), j.setApplicationMenu(null), n = new T({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    // 隐藏原生标题栏，使用自定义 TitleBar.vue
    // macOS 上仍保留原生 traffic lights，Windows/Linux 完全自定义
    titleBarStyle: "hidden",
    webPreferences: {
      nodeIntegration: !1,
      contextIsolation: !0,
      // preload 为 ESM(.mjs)：Electron 要求 sandbox:false 才能加载（沙箱只支持 CJS preload）
      sandbox: !1,
      preload: b(P, "preload.mjs")
    },
    title: "龙魂 - 视频管理系统",
    show: !f.start_minimized,
    backgroundColor: "#111827"
  });
  const t = () => {
    if (!n) return;
    const e = n.isMaximized() ? "maximized" : "normal";
    n.webContents.send("window-state-changed", e);
  };
  if (n.on("maximize", t), n.on("unmaximize", t), n.on("close", (e) => {
    r(`window close event, isQuiting=${D}, closeToTray=${f.close_to_tray}`), !D && f.close_to_tray && h && (e.preventDefault(), n.hide());
  }), n.on("closed", () => {
    r("window closed"), n = null;
  }), n.webContents.on("did-fail-load", (e, o, s, c) => {
    const a = `errorCode=${o}
errorDescription=${s}
url=${c}`;
    r(`did-fail-load ${a}`), n.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(F("页面加载失败", a))}`);
  }), n.webContents.on("render-process-gone", (e, o) => {
    r(`render-process-gone ${JSON.stringify(o)}`);
  }), n.webContents.on("console-message", (e, o, s, c, a) => {
    r(`console level=${o} ${s} ${a}:${c}`);
  }), Y)
    r("load dev url http://localhost:5173"), n.loadURL("http://localhost:5173").catch((e) => {
      r(`load dev failed ${e.stack || e.message}`), n.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(F("开发模式加载失败", e.stack || e.message))}`);
    }), n.webContents.openDevTools();
  else {
    const e = b(P, "../dist/index.html");
    r(`load file ${e}`), n.loadFile(e).catch((o) => {
      r(`load file failed ${o.stack || o.message}`), n.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(F("文件加载失败", `${e}

${o.stack || o.message}`))}`);
    });
  }
}
function X() {
  if (!f.enable_tray) {
    h && (h.destroy(), h = null);
    return;
  }
  if (h) return;
  let t;
  const e = b(P, "../resources/icon.png");
  if (Q(e) && (t = V.createFromPath(e), t.isEmpty() && (r(`tray icon empty at ${e}, fallback to default`), t = null)), !t) {
    const s = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAOklEQVR4nO3OQQ0AIBADwYJ/yzcCJBkSY4h+fn3/PwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7q2gkAAWcG5mEAAAAASUVORK5CYII=",
      "base64"
    );
    t = V.createFromBuffer(s);
  }
  h = new ne(t), h.setToolTip("龙魂视频管理系统");
  const o = j.buildFromTemplate([
    { label: "显示主窗口", click: () => w() },
    {
      label: "迷你模式",
      click: () => {
        n && (n.isMinimized() && n.restore(), n.isVisible() || n.show(), n.isAlwaysOnTop() ? (n.setAlwaysOnTop(!1), n.setSize(1400, 900), n.center()) : (n.setSize(480, 320), n.setAlwaysOnTop(!0)), n.focus());
      }
    },
    { type: "separator" },
    {
      label: "暂停任务",
      click: () => {
        n == null || n.webContents.send("task-control", "pause"), R("MDCX 任务", "已暂停所有任务");
      }
    },
    {
      label: "继续任务",
      click: () => {
        n == null || n.webContents.send("task-control", "resume"), R("MDCX 任务", "已继续所有任务");
      }
    },
    { type: "separator" },
    { label: "退出", click: () => K() }
  ]);
  h.setContextMenu(o), h.on("click", () => w()), h.on("double-click", () => {
    if (!n) {
      C();
      return;
    }
    n.isVisible() && !n.isMinimized() ? n.hide() : w();
  });
}
function w() {
  if (!n) {
    C();
    return;
  }
  n.isMinimized() && n.restore(), n.isVisible() || n.show(), n.focus();
}
function K() {
  D = !0, h && (h.destroy(), h = null), l.quit();
}
function R(t, e, o = {}) {
  if (!q.isSupported())
    return r(`notification not supported, skip: ${t} - ${e}`), null;
  const s = new q({
    title: t || "MDCX",
    body: e || "",
    silent: !!o.silent,
    urgency: o.urgency || "normal"
  });
  return s.on("click", () => {
    n && (n.isMinimized() && n.restore(), n.isVisible() || n.show(), n.focus());
  }), s.show(), s;
}
function Ce(t) {
  try {
    return l.setLoginItemSettings({
      openAtLogin: !!t,
      // Windows 上通过 args 标识自启项，便于后续区分启动来源
      args: ["--hidden"]
    }), r(`setAutoLaunch(${t}) ok`), !0;
  } catch (e) {
    return r(`setAutoLaunch failed: ${e.message}`), !1;
  }
}
function xe() {
  try {
    return !!l.getLoginItemSettings().openAtLogin;
  } catch {
    return !1;
  }
}
const g = /* @__PURE__ */ new Map();
function W() {
  G();
  const { shortcut_show_hide: t, shortcut_play_pause: e, shortcut_screenshot: o } = f;
  if (t)
    try {
      k.register(t, () => {
        n ? n.isVisible() && !n.isMinimized() ? n.hide() : w() : C(), n && n.webContents.send("global-shortcut-triggered", t);
      }) ? g.set(t, "show_hide") : r(`failed to register shortcut: ${t}`);
    } catch (s) {
      r(`register shortcut_show_hide failed: ${s.message}`);
    }
  if (e)
    try {
      k.register(e, () => {
        n && n.webContents.send("global-shortcut-triggered", e);
      }) && g.set(e, "play_pause");
    } catch (s) {
      r(`register shortcut_play_pause failed: ${s.message}`);
    }
  if (o)
    try {
      k.register(o, () => {
        n && n.webContents.send("global-shortcut-triggered", o);
      }) && g.set(o, "screenshot");
    } catch (s) {
      r(`register shortcut_screenshot failed: ${s.message}`);
    }
  try {
    k.register("CommandOrControl+Alt+R", () => {
      n ? n.isVisible() && !n.isMinimized() ? n.hide() : w() : C(), n && n.webContents.send("global-shortcut-triggered", "CommandOrControl+Alt+R");
    }) ? g.set("CommandOrControl+Alt+R", "toggle_window") : r("failed to register shortcut: CommandOrControl+Alt+R");
  } catch (s) {
    r(`register toggle_window failed: ${s.message}`);
  }
  try {
    k.register("CommandOrControl+Alt+E", () => {
      w(), n == null || n.webContents.send("navigate-route", "/movies"), n == null || n.webContents.send("global-shortcut-triggered", "CommandOrControl+Alt+E");
    }) ? g.set("CommandOrControl+Alt+E", "open_explore") : r("failed to register shortcut: CommandOrControl+Alt+E");
  } catch (s) {
    r(`register open_explore failed: ${s.message}`);
  }
}
function G() {
  for (const t of g.keys())
    try {
      k.unregister(t);
    } catch (e) {
      r(`unregister ${t} failed: ${e.message}`);
    }
  g.clear();
}
let p = null;
try {
  p = N("electron-updater").autoUpdater;
} catch {
  r("electron-updater not installed, auto-update disabled");
}
function Se() {
  if (!p || !f.auto_update) return;
  p.autoDownload = !1, p.autoInstallOnAppQuit = !0;
  const t = (e, o = {}) => {
    n && n.webContents.send("updater-event", { type: e, ...o });
  };
  p.on("checking-for-update", () => t("checking")), p.on("update-available", (e) => t("available", { version: e.version, releaseNotes: e.releaseNotes })), p.on("update-not-available", () => t("not-available")), p.on("download-progress", (e) => t("progress", { percent: e.percent, transferred: e.transferred, total: e.total })), p.on("update-downloaded", (e) => t("downloaded", { version: e.version })), p.on("error", (e) => t("error", { message: (e == null ? void 0 : e.message) || String(e) })), setTimeout(() => {
    p.checkForUpdates().catch((e) => r(`autoUpdater.checkForUpdates failed: ${e.message}`));
  }, 3e4);
}
const Oe = l.requestSingleInstanceLock();
Oe ? l.on("second-instance", (t, e) => {
  var s;
  r("second-instance triggered, showing main window"), w();
  const o = ((s = e == null ? void 0 : e.slice(-1)) == null ? void 0 : s[0]) || "";
  typeof o == "string" && o.startsWith("mdcx://") && Z(o);
}) : (r("another instance is running, quitting"), l.quit());
function Z(t) {
  if (!(!t || !t.startsWith("mdcx://"))) {
    r(`handleOpenUrl: ${t}`);
    try {
      const o = new URL(t).pathname.split("/").filter(Boolean);
      if (o.length < 2) {
        r(`invalid mdcx url: ${t}`);
        return;
      }
      const [s, c] = o;
      let a = null;
      if (s === "movie") a = "/movies";
      else if (s === "actor") a = `/actors/${c}`;
      else if (s === "play") a = `/play/${c}`;
      else {
        r(`unknown mdcx url type: ${s}`);
        return;
      }
      w(), n && (n.webContents.send("open-url", { type: s, id: c, route: a, raw: t }), a && n.webContents.send("navigate-route", a));
    } catch (e) {
      r(`handleOpenUrl failed: ${e.message}`);
    }
  }
}
l.on("open-url", (t, e) => {
  t.preventDefault(), Z(e);
});
l.whenReady().then(() => {
  r("app ready"), f = $e(), f.theme === "dark" ? _.themeSource = "dark" : f.theme === "light" ? _.themeSource = "light" : _.themeSource = "system";
  try {
    const t = l.setAsDefaultProtocolClient("mdcx");
    r(`setAsDefaultProtocolClient('mdcx') -> ${t}`);
  } catch (t) {
    r(`setAsDefaultProtocolClient failed: ${t.message}`);
  }
  C(), X(), W(), Se();
}).catch((t) => {
  r(`app ready failed ${t.stack || t.message}`);
});
l.on("window-all-closed", () => {
  r("window-all-closed"), process.platform !== "darwin" && (f.minimize_to_tray && h || K());
});
l.on("activate", () => {
  r("activate"), T.getAllWindows().length === 0 ? C() : w();
});
l.on("before-quit", () => {
  D = !0;
});
l.on("will-quit", () => {
  if (G(), h) {
    try {
      h.destroy();
    } catch {
    }
    h = null;
  }
});
i.on("open-external", (t, e) => {
  te.openExternal(e);
});
i.on("window-minimize", () => n == null ? void 0 : n.minimize());
i.on("window-maximize", () => n == null ? void 0 : n.maximize());
i.on("window-close", () => n == null ? void 0 : n.close());
i.on("window-toggle-maximize", () => {
  n && (n.isMaximized() ? n.unmaximize() : n.maximize());
});
i.on("tray-toggle", () => {
  n != null && n.isVisible() ? n.hide() : w();
});
i.on("tray-show", () => w());
let d = null, U = null;
function Pe() {
  Y ? d.loadURL("http://localhost:5173/#/mpv-osd").catch(() => {
  }) : d.loadFile(b(P, "../dist/index.html"), { hash: "/mpv-osd" }).catch(() => {
  });
}
function De() {
  if (d && !d.isDestroyed()) return d;
  if (!n) return null;
  const t = n.getContentBounds();
  d = new T({
    x: t.x,
    y: t.y,
    width: t.width,
    height: t.height,
    transparent: !0,
    frame: !1,
    resizable: !1,
    movable: !1,
    hasShadow: !1,
    skipTaskbar: !0,
    backgroundColor: "#00000000",
    webPreferences: {
      nodeIntegration: !1,
      contextIsolation: !0,
      sandbox: !1,
      preload: b(P, "preload.mjs")
    }
  }), d.setAlwaysOnTop(!0, "screen-saver"), d.setIgnoreMouseEvents(!0, { forward: !0 }), global.__mpvOsdWindows = [d], Pe();
  const e = () => {
    !d || d.isDestroyed() || !n || d.setBounds(n.getContentBounds());
  };
  return n.on("move", e), n.on("resize", e), n.on("maximize", e), n.on("unmaximize", e), d.on("closed", () => {
    d = null, global.__mpvOsdWindows = [], M();
  }), d;
}
function ee() {
  d && !d.isDestroyed() && d.close(), d = null, global.__mpvOsdWindows = [];
}
i.handle("mpv-start", async (t, e = {}) => {
  if (!n) return { ok: !1, error: "主窗口不存在" };
  U = {
    module: String(e.module || ""),
    id: Number(e.id) || 0,
    url: String(e.url || "")
  }, De();
  const o = we(n, e);
  return r(`mpv-start url=${e.url} result=${JSON.stringify(o)}`), o;
});
i.handle("mpv-context", () => U || null);
i.on("mpv-command", (t, e) => ye(e));
i.on("mpv-set-prop", (t, e, o) => ve(e, o));
i.on("mpv-stop", () => {
  r("mpv-stop"), M(), ee(), U = null;
});
i.on("mpv-exit", () => {
  r("mpv-exit"), M(), ee(), U = null, n && !n.isDestroyed() && (n.isFullScreen() && n.setFullScreen(!1), n.webContents.send("mpv-exit"));
});
i.on("mpv-fullscreen", () => {
  !n || n.isDestroyed() || (n.setFullScreen(!n.isFullScreen()), setTimeout(() => {
    d && !d.isDestroyed() && n && d.setBounds(n.getContentBounds());
  }, 300));
});
i.handle("mpv-state", () => be());
i.handle("mpv-log", () => ke());
i.on("mpv-osd-interactive", (t, e) => {
  d && !d.isDestroyed() && d.setIgnoreMouseEvents(!e, { forward: !0 });
});
i.handle("global-shortcut-register", (t, e) => {
  try {
    if (g.has(e)) return !0;
    const o = k.register(e, () => {
      n == null || n.webContents.send("global-shortcut-triggered", e);
    });
    return o && g.set(e, "dynamic"), o;
  } catch (o) {
    return r(`dynamic register ${e} failed: ${o.message}`), !1;
  }
});
i.handle("global-shortcut-unregister", (t, e) => {
  try {
    return g.has(e) && g.get(e) === "dynamic" && (k.unregister(e), g.delete(e)), !0;
  } catch {
    return !1;
  }
});
i.handle("updater-check", async () => {
  var t;
  if (!p) return { ok: !1, error: "electron-updater not installed" };
  try {
    const e = await p.checkForUpdates();
    return { ok: !0, version: ((t = e == null ? void 0 : e.updateInfo) == null ? void 0 : t.version) || null };
  } catch (e) {
    return { ok: !1, error: e.message };
  }
});
i.handle("updater-download", async () => {
  if (!p) return { ok: !1, error: "electron-updater not installed" };
  try {
    return await p.downloadUpdate(), { ok: !0 };
  } catch (t) {
    return { ok: !1, error: t.message };
  }
});
i.on("updater-install", () => {
  p && (D = !0, p.quitAndInstall());
});
i.handle("prefs-get", () => f);
i.handle("prefs-set", (t, e) => {
  const o = { ...f };
  return f = { ...f, ...e }, _e(f), o.enable_tray !== f.enable_tray && X(), (o.shortcut_show_hide !== f.shortcut_show_hide || o.shortcut_play_pause !== f.shortcut_play_pause || o.shortcut_screenshot !== f.shortcut_screenshot) && W(), o.theme !== f.theme && (f.theme === "dark" ? _.themeSource = "dark" : f.theme === "light" ? _.themeSource = "light" : _.themeSource = "system"), { ok: !0, prefs: f };
});
i.handle("app-info", () => ({
  version: l.getVersion(),
  name: l.getName(),
  platform: process.platform,
  arch: process.arch,
  electron: process.versions.electron,
  chrome: process.versions.chrome,
  node: process.versions.node,
  userData: l.getPath("userData"),
  logsPath: b(l.getPath("userData"), "logs"),
  prefsPath: L()
}));
i.handle("show-notification", (t, e, o, s) => {
  try {
    return { ok: !!R(e, o, s || {}) };
  } catch (c) {
    return r(`show-notification IPC failed: ${c.message}`), { ok: !1, error: c.message };
  }
});
i.handle("set-auto-launch", (t, e) => ({ ok: Ce(e), enabled: !!e }));
i.handle("get-auto-launch", () => ({ enabled: xe() }));
const ze = 8420;
function Ie(t, e, o = 2e3) {
  return new Promise((s) => {
    const c = N("http"), a = `http://${t}:${e}/api/v1/health/version`, A = c.get(a, { timeout: o }, (x) => {
      let S = "";
      x.on("data", (v) => {
        S += v;
      }), x.on("end", () => {
        try {
          const v = JSON.parse(S);
          s({ ok: !0, url: `http://${t}:${e}`, version: v.version || "" });
        } catch {
          s({ ok: !0, url: `http://${t}:${e}`, version: "" });
        }
      });
    });
    A.on("error", () => s({ ok: !1, url: `http://${t}:${e}` })), A.on("timeout", () => {
      A.destroy(), s({ ok: !1, url: `http://${t}:${e}` });
    });
  });
}
function Le() {
  const t = [];
  t.push("127.0.0.1"), t.push("localhost");
  try {
    const o = N("os").networkInterfaces();
    for (const s of Object.keys(o))
      for (const c of o[s])
        if (c.family === "IPv4" && !c.internal) {
          t.push(c.address);
          const a = c.address.split(".");
          a.length === 4 && (t.push(`${a[0]}.${a[1]}.${a[2]}.1`), t.push(`${a[0]}.${a[1]}.${a[2]}.100`), t.push(`${a[0]}.${a[1]}.${a[2]}.200`));
        }
  } catch (e) {
    r(`get network interfaces failed: ${e.message}`);
  }
  return [...new Set(t)];
}
async function Me() {
  const t = Le();
  r(`backend detection candidates: ${JSON.stringify(t)}`);
  for (const e of t)
    try {
      const o = await Ie(e, ze);
      if (o.ok)
        return r(`backend detected at ${o.url}`), o;
    } catch {
    }
  return r("backend detection: none found"), { ok: !1, url: "", version: "" };
}
i.handle("select-folder", async () => {
  if (!n) return { canceled: !0, path: null };
  const t = await oe.showOpenDialog(n, {
    properties: ["openDirectory"],
    title: "选择媒体目录"
  });
  return t.canceled || t.filePaths.length === 0 ? { canceled: !0, path: null } : { canceled: !1, path: t.filePaths[0] };
});
i.handle("backend-detect", async () => await Me());
