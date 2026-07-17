import { app as a, nativeTheme as y, BrowserWindow as U, ipcMain as c, shell as N, globalShortcut as m, Menu as L, nativeImage as D, Tray as V, Notification as z, dialog as q } from "electron";
import { fileURLToPath as B } from "url";
import { dirname as J, join as g } from "path";
import { mkdirSync as Q, appendFileSync as j, existsSync as M, readFileSync as Y, writeFileSync as H } from "fs";
import { createRequire as X } from "module";
const x = X(import.meta.url), K = B(import.meta.url), v = J(K);
let t = null, f = null, A = !1;
const G = process.env.NODE_ENV === "development";
a.disableHardwareAcceleration();
a.commandLine.appendSwitch("no-sandbox");
a.commandLine.appendSwitch("disable-gpu");
a.commandLine.appendSwitch("disable-gpu-sandbox");
a.commandLine.appendSwitch("disable-gpu-compositing");
a.commandLine.appendSwitch("disable-gpu-rasterization");
a.commandLine.appendSwitch("in-process-gpu");
a.commandLine.appendSwitch("disable-features", "VizDisplayCompositor");
function s(n) {
  try {
    const e = g(a.getPath("userData"), "logs");
    Q(e, { recursive: !0 }), j(g(e, "desktop.log"), `[${(/* @__PURE__ */ new Date()).toISOString()}] ${n}
`, "utf8");
  } catch (e) {
    console.error(e);
  }
}
function C(n, e) {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${n}</title><style>body{margin:0;background:#111827;color:#e5e7eb;font-family:Arial,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;height:100vh}.box{max-width:760px;padding:32px;background:#1f2937;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.35)}h1{margin:0 0 16px;color:#60a5fa}pre{white-space:pre-wrap;color:#fca5a5;background:#111827;padding:16px;border-radius:8px}</style></head><body><div class="box"><h1>${n}</h1><p>MDCX Desktop start failed.</p><pre>${e}</pre></div></body></html>`;
}
const k = () => g(a.getPath("userData"), "desktop-prefs.json"), b = {
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
function Z() {
  try {
    if (!M(k())) return { ...b };
    const n = JSON.parse(Y(k(), "utf8"));
    return { ...b, ...n };
  } catch (n) {
    return s(`loadPrefs failed: ${n.message}`), { ...b };
  }
}
function W(n) {
  try {
    H(k(), JSON.stringify(n, null, 2), "utf8");
  } catch (e) {
    s(`savePrefs failed: ${e.message}`);
  }
}
let l = { ...b };
function w() {
  s("createWindow start"), L.setApplicationMenu(null), t = new U({
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
      preload: g(v, "preload.js")
    },
    title: "龙魂 - 视频管理系统",
    show: !l.start_minimized,
    backgroundColor: "#111827"
  });
  const n = () => {
    if (!t) return;
    const e = t.isMaximized() ? "maximized" : "normal";
    t.webContents.send("window-state-changed", e);
  };
  if (t.on("maximize", n), t.on("unmaximize", n), t.on("close", (e) => {
    s(`window close event, isQuiting=${A}, closeToTray=${l.close_to_tray}`), !A && l.close_to_tray && f && (e.preventDefault(), t.hide());
  }), t.on("closed", () => {
    s("window closed"), t = null;
  }), t.webContents.on("did-fail-load", (e, o, r, d) => {
    const i = `errorCode=${o}
errorDescription=${r}
url=${d}`;
    s(`did-fail-load ${i}`), t.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(C("页面加载失败", i))}`);
  }), t.webContents.on("render-process-gone", (e, o) => {
    s(`render-process-gone ${JSON.stringify(o)}`);
  }), t.webContents.on("console-message", (e, o, r, d, i) => {
    s(`console level=${o} ${r} ${i}:${d}`);
  }), G)
    s("load dev url http://localhost:5173"), t.loadURL("http://localhost:5173").catch((e) => {
      s(`load dev failed ${e.stack || e.message}`), t.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(C("开发模式加载失败", e.stack || e.message))}`);
    }), t.webContents.openDevTools();
  else {
    const e = g(v, "../dist/index.html");
    s(`load file ${e}`), t.loadFile(e).catch((o) => {
      s(`load file failed ${o.stack || o.message}`), t.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(C("文件加载失败", `${e}

${o.stack || o.message}`))}`);
    });
  }
}
function R() {
  if (!l.enable_tray) {
    f && (f.destroy(), f = null);
    return;
  }
  if (f) return;
  let n;
  const e = g(v, "../resources/icon.png");
  if (M(e) && (n = D.createFromPath(e), n.isEmpty() && (s(`tray icon empty at ${e}, fallback to default`), n = null)), !n) {
    const r = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAOklEQVR4nO3OQQ0AIBADwYJ/yzcCJBkSY4h+fn3/PwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7q2gkAAWcG5mEAAAAASUVORK5CYII=",
      "base64"
    );
    n = D.createFromBuffer(r);
  }
  f = new V(n), f.setToolTip("龙魂视频管理系统");
  const o = L.buildFromTemplate([
    { label: "显示主窗口", click: () => p() },
    {
      label: "迷你模式",
      click: () => {
        t && (t.isMinimized() && t.restore(), t.isVisible() || t.show(), t.isAlwaysOnTop() ? (t.setAlwaysOnTop(!1), t.setSize(1400, 900), t.center()) : (t.setSize(480, 320), t.setAlwaysOnTop(!0)), t.focus());
      }
    },
    { type: "separator" },
    {
      label: "暂停任务",
      click: () => {
        t == null || t.webContents.send("task-control", "pause"), S("MDCX 任务", "已暂停所有任务");
      }
    },
    {
      label: "继续任务",
      click: () => {
        t == null || t.webContents.send("task-control", "resume"), S("MDCX 任务", "已继续所有任务");
      }
    },
    { type: "separator" },
    { label: "退出", click: () => I() }
  ]);
  f.setContextMenu(o), f.on("click", () => p()), f.on("double-click", () => {
    if (!t) {
      w();
      return;
    }
    t.isVisible() && !t.isMinimized() ? t.hide() : p();
  });
}
function p() {
  if (!t) {
    w();
    return;
  }
  t.isMinimized() && t.restore(), t.isVisible() || t.show(), t.focus();
}
function I() {
  A = !0, f && (f.destroy(), f = null), a.quit();
}
function S(n, e, o = {}) {
  if (!z.isSupported())
    return s(`notification not supported, skip: ${n} - ${e}`), null;
  const r = new z({
    title: n || "MDCX",
    body: e || "",
    silent: !!o.silent,
    urgency: o.urgency || "normal"
  });
  return r.on("click", () => {
    t && (t.isMinimized() && t.restore(), t.isVisible() || t.show(), t.focus());
  }), r.show(), r;
}
function ee(n) {
  try {
    return a.setLoginItemSettings({
      openAtLogin: !!n,
      // Windows 上通过 args 标识自启项，便于后续区分启动来源
      args: ["--hidden"]
    }), s(`setAutoLaunch(${n}) ok`), !0;
  } catch (e) {
    return s(`setAutoLaunch failed: ${e.message}`), !1;
  }
}
function te() {
  try {
    return !!a.getLoginItemSettings().openAtLogin;
  } catch {
    return !1;
  }
}
const h = /* @__PURE__ */ new Map();
function E() {
  T();
  const { shortcut_show_hide: n, shortcut_play_pause: e, shortcut_screenshot: o } = l;
  if (n)
    try {
      m.register(n, () => {
        t ? t.isVisible() && !t.isMinimized() ? t.hide() : p() : w(), t && t.webContents.send("global-shortcut-triggered", n);
      }) ? h.set(n, "show_hide") : s(`failed to register shortcut: ${n}`);
    } catch (r) {
      s(`register shortcut_show_hide failed: ${r.message}`);
    }
  if (e)
    try {
      m.register(e, () => {
        t && t.webContents.send("global-shortcut-triggered", e);
      }) && h.set(e, "play_pause");
    } catch (r) {
      s(`register shortcut_play_pause failed: ${r.message}`);
    }
  if (o)
    try {
      m.register(o, () => {
        t && t.webContents.send("global-shortcut-triggered", o);
      }) && h.set(o, "screenshot");
    } catch (r) {
      s(`register shortcut_screenshot failed: ${r.message}`);
    }
  try {
    m.register("CommandOrControl+Alt+R", () => {
      t ? t.isVisible() && !t.isMinimized() ? t.hide() : p() : w(), t && t.webContents.send("global-shortcut-triggered", "CommandOrControl+Alt+R");
    }) ? h.set("CommandOrControl+Alt+R", "toggle_window") : s("failed to register shortcut: CommandOrControl+Alt+R");
  } catch (r) {
    s(`register toggle_window failed: ${r.message}`);
  }
  try {
    m.register("CommandOrControl+Alt+E", () => {
      p(), t == null || t.webContents.send("navigate-route", "/movies"), t == null || t.webContents.send("global-shortcut-triggered", "CommandOrControl+Alt+E");
    }) ? h.set("CommandOrControl+Alt+E", "open_explore") : s("failed to register shortcut: CommandOrControl+Alt+E");
  } catch (r) {
    s(`register open_explore failed: ${r.message}`);
  }
}
function T() {
  for (const n of h.keys())
    try {
      m.unregister(n);
    } catch (e) {
      s(`unregister ${n} failed: ${e.message}`);
    }
  h.clear();
}
let u = null;
try {
  u = x("electron-updater").autoUpdater;
} catch {
  s("electron-updater not installed, auto-update disabled");
}
function ne() {
  if (!u || !l.auto_update) return;
  u.autoDownload = !1, u.autoInstallOnAppQuit = !0;
  const n = (e, o = {}) => {
    t && t.webContents.send("updater-event", { type: e, ...o });
  };
  u.on("checking-for-update", () => n("checking")), u.on("update-available", (e) => n("available", { version: e.version, releaseNotes: e.releaseNotes })), u.on("update-not-available", () => n("not-available")), u.on("download-progress", (e) => n("progress", { percent: e.percent, transferred: e.transferred, total: e.total })), u.on("update-downloaded", (e) => n("downloaded", { version: e.version })), u.on("error", (e) => n("error", { message: (e == null ? void 0 : e.message) || String(e) })), setTimeout(() => {
    u.checkForUpdates().catch((e) => s(`autoUpdater.checkForUpdates failed: ${e.message}`));
  }, 3e4);
}
const oe = a.requestSingleInstanceLock();
oe ? a.on("second-instance", (n, e) => {
  var r;
  s("second-instance triggered, showing main window"), p();
  const o = ((r = e == null ? void 0 : e.slice(-1)) == null ? void 0 : r[0]) || "";
  typeof o == "string" && o.startsWith("mdcx://") && F(o);
}) : (s("another instance is running, quitting"), a.quit());
function F(n) {
  if (!(!n || !n.startsWith("mdcx://"))) {
    s(`handleOpenUrl: ${n}`);
    try {
      const o = new URL(n).pathname.split("/").filter(Boolean);
      if (o.length < 2) {
        s(`invalid mdcx url: ${n}`);
        return;
      }
      const [r, d] = o;
      let i = null;
      if (r === "movie") i = "/movies";
      else if (r === "actor") i = `/actors/${d}`;
      else if (r === "play") i = `/play/${d}`;
      else {
        s(`unknown mdcx url type: ${r}`);
        return;
      }
      p(), t && (t.webContents.send("open-url", { type: r, id: d, route: i, raw: n }), i && t.webContents.send("navigate-route", i));
    } catch (e) {
      s(`handleOpenUrl failed: ${e.message}`);
    }
  }
}
a.on("open-url", (n, e) => {
  n.preventDefault(), F(e);
});
a.whenReady().then(() => {
  s("app ready"), l = Z(), l.theme === "dark" ? y.themeSource = "dark" : l.theme === "light" ? y.themeSource = "light" : y.themeSource = "system";
  try {
    const n = a.setAsDefaultProtocolClient("mdcx");
    s(`setAsDefaultProtocolClient('mdcx') -> ${n}`);
  } catch (n) {
    s(`setAsDefaultProtocolClient failed: ${n.message}`);
  }
  w(), R(), E(), ne();
}).catch((n) => {
  s(`app ready failed ${n.stack || n.message}`);
});
a.on("window-all-closed", () => {
  s("window-all-closed"), process.platform !== "darwin" && (l.minimize_to_tray && f || I());
});
a.on("activate", () => {
  s("activate"), U.getAllWindows().length === 0 ? w() : p();
});
a.on("before-quit", () => {
  A = !0;
});
a.on("will-quit", () => {
  if (T(), f) {
    try {
      f.destroy();
    } catch {
    }
    f = null;
  }
});
c.on("open-external", (n, e) => {
  N.openExternal(e);
});
c.on("window-minimize", () => t == null ? void 0 : t.minimize());
c.on("window-maximize", () => t == null ? void 0 : t.maximize());
c.on("window-close", () => t == null ? void 0 : t.close());
c.on("window-toggle-maximize", () => {
  t && (t.isMaximized() ? t.unmaximize() : t.maximize());
});
c.on("tray-toggle", () => {
  t != null && t.isVisible() ? t.hide() : p();
});
c.on("tray-show", () => p());
c.handle("global-shortcut-register", (n, e) => {
  try {
    if (h.has(e)) return !0;
    const o = m.register(e, () => {
      t == null || t.webContents.send("global-shortcut-triggered", e);
    });
    return o && h.set(e, "dynamic"), o;
  } catch (o) {
    return s(`dynamic register ${e} failed: ${o.message}`), !1;
  }
});
c.handle("global-shortcut-unregister", (n, e) => {
  try {
    return h.has(e) && h.get(e) === "dynamic" && (m.unregister(e), h.delete(e)), !0;
  } catch {
    return !1;
  }
});
c.handle("updater-check", async () => {
  var n;
  if (!u) return { ok: !1, error: "electron-updater not installed" };
  try {
    const e = await u.checkForUpdates();
    return { ok: !0, version: ((n = e == null ? void 0 : e.updateInfo) == null ? void 0 : n.version) || null };
  } catch (e) {
    return { ok: !1, error: e.message };
  }
});
c.handle("updater-download", async () => {
  if (!u) return { ok: !1, error: "electron-updater not installed" };
  try {
    return await u.downloadUpdate(), { ok: !0 };
  } catch (n) {
    return { ok: !1, error: n.message };
  }
});
c.on("updater-install", () => {
  u && (A = !0, u.quitAndInstall());
});
c.handle("prefs-get", () => l);
c.handle("prefs-set", (n, e) => {
  const o = { ...l };
  return l = { ...l, ...e }, W(l), o.enable_tray !== l.enable_tray && R(), (o.shortcut_show_hide !== l.shortcut_show_hide || o.shortcut_play_pause !== l.shortcut_play_pause || o.shortcut_screenshot !== l.shortcut_screenshot) && E(), o.theme !== l.theme && (l.theme === "dark" ? y.themeSource = "dark" : l.theme === "light" ? y.themeSource = "light" : y.themeSource = "system"), { ok: !0, prefs: l };
});
c.handle("app-info", () => ({
  version: a.getVersion(),
  name: a.getName(),
  platform: process.platform,
  arch: process.arch,
  electron: process.versions.electron,
  chrome: process.versions.chrome,
  node: process.versions.node,
  userData: a.getPath("userData"),
  logsPath: g(a.getPath("userData"), "logs"),
  prefsPath: k()
}));
c.handle("show-notification", (n, e, o, r) => {
  try {
    return { ok: !!S(e, o, r || {}) };
  } catch (d) {
    return s(`show-notification IPC failed: ${d.message}`), { ok: !1, error: d.message };
  }
});
c.handle("set-auto-launch", (n, e) => ({ ok: ee(e), enabled: !!e }));
c.handle("get-auto-launch", () => ({ enabled: te() }));
const se = 8420;
function re(n, e, o = 2e3) {
  return new Promise((r) => {
    const d = x("http"), i = `http://${n}:${e}/api/v1/health/version`, $ = d.get(i, { timeout: o }, (O) => {
      let P = "";
      O.on("data", (_) => {
        P += _;
      }), O.on("end", () => {
        try {
          const _ = JSON.parse(P);
          r({ ok: !0, url: `http://${n}:${e}`, version: _.version || "" });
        } catch {
          r({ ok: !0, url: `http://${n}:${e}`, version: "" });
        }
      });
    });
    $.on("error", () => r({ ok: !1, url: `http://${n}:${e}` })), $.on("timeout", () => {
      $.destroy(), r({ ok: !1, url: `http://${n}:${e}` });
    });
  });
}
function ae() {
  const n = [];
  n.push("127.0.0.1"), n.push("localhost");
  try {
    const o = x("os").networkInterfaces();
    for (const r of Object.keys(o))
      for (const d of o[r])
        if (d.family === "IPv4" && !d.internal) {
          n.push(d.address);
          const i = d.address.split(".");
          i.length === 4 && (n.push(`${i[0]}.${i[1]}.${i[2]}.1`), n.push(`${i[0]}.${i[1]}.${i[2]}.100`), n.push(`${i[0]}.${i[1]}.${i[2]}.200`));
        }
  } catch (e) {
    s(`get network interfaces failed: ${e.message}`);
  }
  return [...new Set(n)];
}
async function ie() {
  const n = ae();
  s(`backend detection candidates: ${JSON.stringify(n)}`);
  for (const e of n)
    try {
      const o = await re(e, se);
      if (o.ok)
        return s(`backend detected at ${o.url}`), o;
    } catch {
    }
  return s("backend detection: none found"), { ok: !1, url: "", version: "" };
}
c.handle("select-folder", async () => {
  if (!t) return { canceled: !0, path: null };
  const n = await q.showOpenDialog(t, {
    properties: ["openDirectory"],
    title: "选择媒体目录"
  });
  return n.canceled || n.filePaths.length === 0 ? { canceled: !0, path: null } : { canceled: !1, path: n.filePaths[0] };
});
c.handle("backend-detect", async () => await ie());
