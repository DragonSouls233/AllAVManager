import { app as a, nativeTheme as y, BrowserWindow as U, ipcMain as c, shell as N, globalShortcut as m, Menu as L, nativeImage as z, Tray as V, Notification as D } from "electron";
import { fileURLToPath as q } from "url";
import { dirname as B, join as g } from "path";
import { mkdirSync as J, appendFileSync as Q, existsSync as M, readFileSync as j, writeFileSync as Y } from "fs";
import { createRequire as H } from "module";
const x = H(import.meta.url), X = q(import.meta.url), v = B(X);
let t = null, f = null, A = !1;
const K = process.env.NODE_ENV === "development";
a.disableHardwareAcceleration();
a.commandLine.appendSwitch("no-sandbox");
a.commandLine.appendSwitch("disable-gpu");
a.commandLine.appendSwitch("disable-gpu-sandbox");
a.commandLine.appendSwitch("disable-gpu-compositing");
a.commandLine.appendSwitch("disable-gpu-rasterization");
a.commandLine.appendSwitch("in-process-gpu");
a.commandLine.appendSwitch("disable-features", "VizDisplayCompositor");
function s(o) {
  try {
    const e = g(a.getPath("userData"), "logs");
    J(e, { recursive: !0 }), Q(g(e, "desktop.log"), `[${(/* @__PURE__ */ new Date()).toISOString()}] ${o}
`, "utf8");
  } catch (e) {
    console.error(e);
  }
}
function C(o, e) {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${o}</title><style>body{margin:0;background:#111827;color:#e5e7eb;font-family:Arial,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;height:100vh}.box{max-width:760px;padding:32px;background:#1f2937;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.35)}h1{margin:0 0 16px;color:#60a5fa}pre{white-space:pre-wrap;color:#fca5a5;background:#111827;padding:16px;border-radius:8px}</style></head><body><div class="box"><h1>${o}</h1><p>MDCX Desktop start failed.</p><pre>${e}</pre></div></body></html>`;
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
function G() {
  try {
    if (!M(k())) return { ...b };
    const o = JSON.parse(j(k(), "utf8"));
    return { ...b, ...o };
  } catch (o) {
    return s(`loadPrefs failed: ${o.message}`), { ...b };
  }
}
function Z(o) {
  try {
    Y(k(), JSON.stringify(o, null, 2), "utf8");
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
  const o = () => {
    if (!t) return;
    const e = t.isMaximized() ? "maximized" : "normal";
    t.webContents.send("window-state-changed", e);
  };
  if (t.on("maximize", o), t.on("unmaximize", o), t.on("close", (e) => {
    s(`window close event, isQuiting=${A}, closeToTray=${l.close_to_tray}`), !A && l.close_to_tray && f && (e.preventDefault(), t.hide());
  }), t.on("closed", () => {
    s("window closed"), t = null;
  }), t.webContents.on("did-fail-load", (e, n, r, d) => {
    const i = `errorCode=${n}
errorDescription=${r}
url=${d}`;
    s(`did-fail-load ${i}`), t.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(C("页面加载失败", i))}`);
  }), t.webContents.on("render-process-gone", (e, n) => {
    s(`render-process-gone ${JSON.stringify(n)}`);
  }), t.webContents.on("console-message", (e, n, r, d, i) => {
    s(`console level=${n} ${r} ${i}:${d}`);
  }), K)
    s("load dev url http://localhost:5173"), t.loadURL("http://localhost:5173").catch((e) => {
      s(`load dev failed ${e.stack || e.message}`), t.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(C("开发模式加载失败", e.stack || e.message))}`);
    }), t.webContents.openDevTools();
  else {
    const e = g(v, "../dist/index.html");
    s(`load file ${e}`), t.loadFile(e).catch((n) => {
      s(`load file failed ${n.stack || n.message}`), t.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(C("文件加载失败", `${e}

${n.stack || n.message}`))}`);
    });
  }
}
function R() {
  if (!l.enable_tray) {
    f && (f.destroy(), f = null);
    return;
  }
  if (f) return;
  let o;
  const e = g(v, "../resources/icon.png");
  if (M(e) && (o = z.createFromPath(e), o.isEmpty() && (s(`tray icon empty at ${e}, fallback to default`), o = null)), !o) {
    const r = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAOklEQVR4nO3OQQ0AIBADwYJ/yzcCJBkSY4h+fn3/PwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7q2gkAAWcG5mEAAAAASUVORK5CYII=",
      "base64"
    );
    o = z.createFromBuffer(r);
  }
  f = new V(o), f.setToolTip("龙魂视频管理系统");
  const n = L.buildFromTemplate([
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
  f.setContextMenu(n), f.on("click", () => p()), f.on("double-click", () => {
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
function S(o, e, n = {}) {
  if (!D.isSupported())
    return s(`notification not supported, skip: ${o} - ${e}`), null;
  const r = new D({
    title: o || "MDCX",
    body: e || "",
    silent: !!n.silent,
    urgency: n.urgency || "normal"
  });
  return r.on("click", () => {
    t && (t.isMinimized() && t.restore(), t.isVisible() || t.show(), t.focus());
  }), r.show(), r;
}
function W(o) {
  try {
    return a.setLoginItemSettings({
      openAtLogin: !!o,
      // Windows 上通过 args 标识自启项，便于后续区分启动来源
      args: ["--hidden"]
    }), s(`setAutoLaunch(${o}) ok`), !0;
  } catch (e) {
    return s(`setAutoLaunch failed: ${e.message}`), !1;
  }
}
function ee() {
  try {
    return !!a.getLoginItemSettings().openAtLogin;
  } catch {
    return !1;
  }
}
const h = /* @__PURE__ */ new Map();
function E() {
  T();
  const { shortcut_show_hide: o, shortcut_play_pause: e, shortcut_screenshot: n } = l;
  if (o)
    try {
      m.register(o, () => {
        t ? t.isVisible() && !t.isMinimized() ? t.hide() : p() : w(), t && t.webContents.send("global-shortcut-triggered", o);
      }) ? h.set(o, "show_hide") : s(`failed to register shortcut: ${o}`);
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
  if (n)
    try {
      m.register(n, () => {
        t && t.webContents.send("global-shortcut-triggered", n);
      }) && h.set(n, "screenshot");
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
  for (const o of h.keys())
    try {
      m.unregister(o);
    } catch (e) {
      s(`unregister ${o} failed: ${e.message}`);
    }
  h.clear();
}
let u = null;
try {
  u = x("electron-updater").autoUpdater;
} catch {
  s("electron-updater not installed, auto-update disabled");
}
function te() {
  if (!u || !l.auto_update) return;
  u.autoDownload = !1, u.autoInstallOnAppQuit = !0;
  const o = (e, n = {}) => {
    t && t.webContents.send("updater-event", { type: e, ...n });
  };
  u.on("checking-for-update", () => o("checking")), u.on("update-available", (e) => o("available", { version: e.version, releaseNotes: e.releaseNotes })), u.on("update-not-available", () => o("not-available")), u.on("download-progress", (e) => o("progress", { percent: e.percent, transferred: e.transferred, total: e.total })), u.on("update-downloaded", (e) => o("downloaded", { version: e.version })), u.on("error", (e) => o("error", { message: (e == null ? void 0 : e.message) || String(e) })), setTimeout(() => {
    u.checkForUpdates().catch((e) => s(`autoUpdater.checkForUpdates failed: ${e.message}`));
  }, 3e4);
}
const oe = a.requestSingleInstanceLock();
oe ? a.on("second-instance", (o, e) => {
  var r;
  s("second-instance triggered, showing main window"), p();
  const n = ((r = e == null ? void 0 : e.slice(-1)) == null ? void 0 : r[0]) || "";
  typeof n == "string" && n.startsWith("mdcx://") && F(n);
}) : (s("another instance is running, quitting"), a.quit());
function F(o) {
  if (!(!o || !o.startsWith("mdcx://"))) {
    s(`handleOpenUrl: ${o}`);
    try {
      const n = new URL(o).pathname.split("/").filter(Boolean);
      if (n.length < 2) {
        s(`invalid mdcx url: ${o}`);
        return;
      }
      const [r, d] = n;
      let i = null;
      if (r === "movie") i = "/movies";
      else if (r === "actor") i = `/actors/${d}`;
      else if (r === "play") i = `/play/${d}`;
      else {
        s(`unknown mdcx url type: ${r}`);
        return;
      }
      p(), t && (t.webContents.send("open-url", { type: r, id: d, route: i, raw: o }), i && t.webContents.send("navigate-route", i));
    } catch (e) {
      s(`handleOpenUrl failed: ${e.message}`);
    }
  }
}
a.on("open-url", (o, e) => {
  o.preventDefault(), F(e);
});
a.whenReady().then(() => {
  s("app ready"), l = G(), l.theme === "dark" ? y.themeSource = "dark" : l.theme === "light" ? y.themeSource = "light" : y.themeSource = "system";
  try {
    const o = a.setAsDefaultProtocolClient("mdcx");
    s(`setAsDefaultProtocolClient('mdcx') -> ${o}`);
  } catch (o) {
    s(`setAsDefaultProtocolClient failed: ${o.message}`);
  }
  w(), R(), E(), te();
}).catch((o) => {
  s(`app ready failed ${o.stack || o.message}`);
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
c.on("open-external", (o, e) => {
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
c.handle("global-shortcut-register", (o, e) => {
  try {
    if (h.has(e)) return !0;
    const n = m.register(e, () => {
      t == null || t.webContents.send("global-shortcut-triggered", e);
    });
    return n && h.set(e, "dynamic"), n;
  } catch (n) {
    return s(`dynamic register ${e} failed: ${n.message}`), !1;
  }
});
c.handle("global-shortcut-unregister", (o, e) => {
  try {
    return h.has(e) && h.get(e) === "dynamic" && (m.unregister(e), h.delete(e)), !0;
  } catch {
    return !1;
  }
});
c.handle("updater-check", async () => {
  var o;
  if (!u) return { ok: !1, error: "electron-updater not installed" };
  try {
    const e = await u.checkForUpdates();
    return { ok: !0, version: ((o = e == null ? void 0 : e.updateInfo) == null ? void 0 : o.version) || null };
  } catch (e) {
    return { ok: !1, error: e.message };
  }
});
c.handle("updater-download", async () => {
  if (!u) return { ok: !1, error: "electron-updater not installed" };
  try {
    return await u.downloadUpdate(), { ok: !0 };
  } catch (o) {
    return { ok: !1, error: o.message };
  }
});
c.on("updater-install", () => {
  u && (A = !0, u.quitAndInstall());
});
c.handle("prefs-get", () => l);
c.handle("prefs-set", (o, e) => {
  const n = { ...l };
  return l = { ...l, ...e }, Z(l), n.enable_tray !== l.enable_tray && R(), (n.shortcut_show_hide !== l.shortcut_show_hide || n.shortcut_play_pause !== l.shortcut_play_pause || n.shortcut_screenshot !== l.shortcut_screenshot) && E(), n.theme !== l.theme && (l.theme === "dark" ? y.themeSource = "dark" : l.theme === "light" ? y.themeSource = "light" : y.themeSource = "system"), { ok: !0, prefs: l };
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
c.handle("show-notification", (o, e, n, r) => {
  try {
    return { ok: !!S(e, n, r || {}) };
  } catch (d) {
    return s(`show-notification IPC failed: ${d.message}`), { ok: !1, error: d.message };
  }
});
c.handle("set-auto-launch", (o, e) => ({ ok: W(e), enabled: !!e }));
c.handle("get-auto-launch", () => ({ enabled: ee() }));
const ne = 8420;
function se(o, e, n = 2e3) {
  return new Promise((r) => {
    const d = x("http"), i = `http://${o}:${e}/api/v1/health/version`, $ = d.get(i, { timeout: n }, (O) => {
      let P = "";
      O.on("data", (_) => {
        P += _;
      }), O.on("end", () => {
        try {
          const _ = JSON.parse(P);
          r({ ok: !0, url: `http://${o}:${e}`, version: _.version || "" });
        } catch {
          r({ ok: !0, url: `http://${o}:${e}`, version: "" });
        }
      });
    });
    $.on("error", () => r({ ok: !1, url: `http://${o}:${e}` })), $.on("timeout", () => {
      $.destroy(), r({ ok: !1, url: `http://${o}:${e}` });
    });
  });
}
function re() {
  const o = [];
  o.push("127.0.0.1"), o.push("localhost");
  try {
    const n = x("os").networkInterfaces();
    for (const r of Object.keys(n))
      for (const d of n[r])
        if (d.family === "IPv4" && !d.internal) {
          o.push(d.address);
          const i = d.address.split(".");
          i.length === 4 && (o.push(`${i[0]}.${i[1]}.${i[2]}.1`), o.push(`${i[0]}.${i[1]}.${i[2]}.100`), o.push(`${i[0]}.${i[1]}.${i[2]}.200`));
        }
  } catch (e) {
    s(`get network interfaces failed: ${e.message}`);
  }
  return [...new Set(o)];
}
async function ae() {
  const o = re();
  s(`backend detection candidates: ${JSON.stringify(o)}`);
  for (const e of o)
    try {
      const n = await se(e, ne);
      if (n.ok)
        return s(`backend detected at ${n.url}`), n;
    } catch {
    }
  return s("backend detection: none found"), { ok: !1, url: "", version: "" };
}
c.handle("backend-detect", async () => await ae());
