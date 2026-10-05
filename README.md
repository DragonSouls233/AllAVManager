# <a id="zh-cn"></a>MDCX — 视频元数据管理系统

<p align="center">
  <a href="#zh-cn">📖 简体中文</a> ·
  <a href="#zh-tw">🇭🇰 繁體中文</a> ·
  <a href="#en">🌐 English</a>
</p>

<br>

---

# 简体中文

## 简介

MDCX 是一款**自托管**的本地视频库管理系统，面向成人视频内容设计。它把「文件扫描 → 封面抓取 → 演员信息 → 去重比对 → 下载管理 → 多端播放 → 媒体服务器分发」串成一条完整工作流。

系统采用**模块化架构**：每种内容类型独立数据库（SQLite），互不干扰，便于横向扩展。

### 支持的内容模块

| 模块 | 数据库 | 说明 |
|------|--------|------|
| JAV（审查） | `jav.db` | 日本成人影片（含审查片） |
| JAV（无码） | `uncensored.db` | 无码影片 |
| FC2-PPV | `fc2.db` | FC2 付费影片 |
| 国产 | `chinese.db` | 国产影片，支持 LLM 智能刮削 |
| 欧美 | `western.db` | Western 影片 |
| Pornhub | `pornhub.db` | Pornhub 内容 |
| 动漫 | `anime.db` | 动漫影片（Getchu 等源） |
| 系统 | `system.db` | 用户、会话、设置、缓存、任务、工作流 |

共 **8 个独立 SQLite 数据库**，业务模块共享同一套规范化表结构（21 张共享基表），通过外键级联保证数据完整性。

### 核心特性

- **137 个爬虫源**：JavBus、JavDB、DMM、FC2-PPVDB、ThePornDB、Madou、Haijiao、Getchu 等
- **LLM 智能刮削**：基于 OpenAI 兼容 API（Ollama / Gemini / DeepSeek），无番号影片也能抓取元数据
- **YAML 声明式爬虫插件**：新增网站无需修改核心代码
- **智能去重**：文件哈希 + 感知哈希（pHash）+ 音频指纹三重去重
- **封面管理**：多源采集、人脸裁剪、自动降级、海报增强
- **批量刮削与修复**：自动检测缺失字段、智能跳过、分级报告
- **下载管理**：qBittorrent / Transmission / Aria2 / yt-dlp 直下
- **视频播放**：内嵌 ArtPlayer + HLS + 本地 mpv / ffplay，支持代理播放
- **媒体服务器兼容**：Emby / Jellyfin / Metatube / TVBox / MacCMS / Stash API / WebDAV
- **自动组织**：目录监听 + 定时整理 + NFO 生成（可自定义命名模板）
- **自动备份**：定时任务、订阅监控、下载后自动处理
- **系统监控**：WebSocket 事件总线 + Prometheus 指标
- **6 套主题**：cinema / default / forest / midnight / rose / sunset
- **桌面客户端**：Electron 33 + Vue 3 + Element Plus
- **AI 集成**：MCP 协议接口 + Telegram Bot 远程控制
- **本地代理**：内置 Xray，配置热重载

### 统计

| 指标 | 数量 |
|------|------|
| 后端路由文件 | 94 |
| 爬虫模块 | 137 |
| 服务模块 | 117 |
| 数据库模型文件 | 21 |
| 前端页面 | 125 |
| 前端 API 客户端 | 13 |
| Pinia Store | 16 |
| 通用组件 | 29 |
| 主题 | 6 |
| 文档 | 21 |

---

## 技术架构

### 后端 — `MDCX-Server/`

| 组件 | 技术选型 |
|------|----------|
| Web 框架 | FastAPI 0.135+ / Uvicorn |
| 数据库 | SQLite (aiosqlite) + SQLAlchemy 2.x |
| 数据校验 | Pydantic v2 |
| HTTP 客户端 | curl-cffi（TLS 指纹，绕过 Cloudflare） |
| 反爬 / 解析 | lxml, BeautifulSoup, Playwright, cloudscraper |
| 图片处理 | Pillow + OpenCV + MediaPipe + ONNX Runtime |
| 去重 | ImageHash (pHash) |
| 定时任务 | APScheduler |
| 文件监控 | Watchdog |
| 认证 | python-jose (JWT) + passlib |
| 监控 | Prometheus Client |
| LLM | OpenAI SDK（兼容 Ollama / Gemini / DeepSeek） |

**启动流程**：日志初始化 → 数据库连接 → Schema 迁移 → 任务调度器 → 目录监听 → 自动扫描 → 封面补全 → 插件系统 → 爬虫配置 → CookieCloud 同步 → 网盘客户端（CloudDrive2/115）→ 下载管理器 → 备份服务 → 订阅自动下载 → 自动整理（每小时）→ Xray 代理 → 配置监听

### 前端 — `MDCX-Desktop/`

| 组件 | 技术选型 |
|------|----------|
| 框架 | Vue 3.5 + Vue Router 4.5 |
| UI 库 | Element Plus 2.9 + @element-plus/icons-vue |
| 状态管理 | Pinia 2.3 + @vueuse/core |
| 播放器 | ArtPlayer 5.2 + hls.js 1.6 |
| 桌面壳 | Electron 33.2 + electron-builder 25.1 |
| 构建工具 | Vite 6.0 + vite-plugin-electron |
| HTTP 客户端 | Axios |

**桌面客户端特性**：自定义标题栏、系统托盘、全局快捷键（`Ctrl+Shift+M` 显隐，`Ctrl+Shift+P` 播放暂停）、自动更新、`mdcx://` 协议注册、端口 8420 后端自动检测

### 数据库架构

8 个独立 SQLite 数据库：

| 数据库 | 用途 |
|--------|------|
| `system.db` | 用户、会话、设置、缓存、任务、工作流（12 张表） |
| `jav.db` | JAV（审查） |
| `uncensored.db` | JAV（无码） |
| `fc2.db` | FC2-PPV |
| `chinese.db` | 国产 |
| `pornhub.db` | Pornhub |
| `western.db` | 欧美 |
| `anime.db` | 动漫 |

7 个业务模块共享同一套基表（`movies` / `actors` / `studios` / `series` / `tags` / `play_history` / `import_records` 等），由 `app/db/_module_mixins.py` 统一定义，各模块只需导入基类并声明具体模型，无需重复定义列。

---

## 快速开始

### 环境要求

- **Python ≥ 3.11**
- **Node.js ≥ 22**
- **ffmpeg**（视频处理，项目内置 `bin/` 目录）
- **Chromium**（Playwright 反爬，`playwright install chromium`）

### 后端启动

```bash
cd MDCX-Server
pip install -r requirements.txt
playwright install chromium

# 运行服务器（默认端口 8420）
python run.py --no-tray --no-browser
# 或
uvicorn app.main:app --host 0.0.0.0 --port 8420
```

API 基础地址：`http://localhost:8420/api/v1`

配置目录：`data/config/config.yaml`

### 桌面客户端启动

```bash
cd MDCX-Desktop
npm install
npm run dev
```

开发模式监听 `localhost:5173`，`/api` 请求自动代理至 `localhost:8420`。

### 构建发布

```bash
# 完整构建
npm run build

# Windows 便携版
npm run build:win

# macOS DMG
npm run build:mac
```

### Docker 部署

```bash
cd MDCX-Server/deploy/docker
docker build -t mdcx-server .
docker run -d --name mdcx -p 8420:8420 \
  -v $(pwd)/data:/app/data \
  mdcx-server
```

或使用 docker-compose：

```bash
docker-compose up -d
# 或 advanced 版本（含 CloudDrive2 / 115 网盘挂载）
docker-compose -f docker-compose.advanced.yml up -d
```

---

## 项目结构

```
MDCX/
├── .gitignore
├── README.md            ← 本文件（简体 / 繁體 / English）
├── MDCX-Server/         ← 后端
│   ├── app/
│   │   ├── api/routes/      94 个路由文件
│   │   ├── crawlers/        137 个爬虫（base/ md/src/ western/）
│   │   ├── db/              全模块数据库模型（共享 Mixin + 8 库）
│   │   ├── services/        117 个服务模块
│   │   ├── scraper/         刮削引擎（engine / merger / llm_scraper / comparator / extractor）
│   │   ├── patcher/         批量刮削与修复
│   │   ├── importer/        图片扫描 / NFO 解析
│   │   ├── tasks/           扫描器 / 调度器 / 队列
│   │   ├── config/          YAML 配置 / 站点注册表 / 迁移
│   │   ├── external/        内置第三方爬虫
│   │   ├── utils/           HTTP / 代理 / Cookie / 加密等工具
│   │   └── main.py          FastAPI 入口
│   ├── bin/                 ffmpeg / yt-dlp / xray 等二进制文件
│   ├── deploy/              Docker / K8s / Nginx / systemd
│   ├── requirements.txt
│   └── pyproject.toml
├── MDCX-Desktop/        ← 前端 / 桌面客户端
│   ├── src/
│   │   ├── api/             13 个 API 客户端模块
│   │   ├── components/      29 个通用组件
│   │   ├── stores/          16 个 Pinia Store
│   │   ├── views/           125 个页面（按内容模块组织）
│   │   └── themes/          6 套主题
│   ├── electron/
│   │   ├── main.js          Electron 主进程
│   │   └── preload.js       预加载脚本
│   ├── vite.config.js
│   └── package.json
└── docs/                ← 开发文档（21 篇）
```

---

## 文档索引

| 文档 | 说明 |
|------|------|
| `docs/PLAN.md` | 模块修复计划与阶段路线图 |
| `docs/new-database-architecture.md` | v2.0 数据库设计（8 库，共享基表） |
| `docs/MDCX数据流向总结.md` | 数据流向图（封面 / 批刮 / 演员头像） |
| `docs/开发设计_5模块架构扩展.md` | 架构设计详述（含 130+ 参考项目分析） |
| `docs/DEVELOPMENT_PLAN.md` | 集成开发计划（10 阶段） |
| `docs/DEPLOY_SERVER.md` | 服务器部署清单 |
| `docs/DEPLOY_DEPENDENCIES.md` | 部署依赖说明 |
| `docs/JAV系列参考项目_深度分析与复用评估.md` | 参考项目复用评估 |
| `docs/命名规则规范_MDCX.md` | NFO 命名规则规范 |
| `docs/开发规则.md` | 开发规范 |
| `docs/MDCX桌面端重构方案.md` | 桌面端重构方案 |

---

## API 接口

| 路由前缀 | 说明 |
|----------|------|
| `/api/v1/*` | 核心业务 API |
| `/emby/*` | Emby 兼容接口 |
| `/tvbox/*` | TVBox 兼容接口 |
| `/maccms/*` | MacCMS 兼容接口 |
| `/webdav/*` | WebDAV 文件访问 |
| `/metatube/*` | Jellyfin 兼容接口 |
| `/ws/*` | WebSocket 事件推送 |
| `/metrics` | Prometheus 监控指标 |

---

## 扫描超时与并发

| 模块 | 单模块扫描超时 |
|------|---------------|
| Pornhub | 7200s（2 小时） |
| JAV（审查） | 3600s（1 小时） |
| 国产 / 欧美 | 1800s（30 分钟） |
| FC2 / 动漫 | 900s（15 分钟） |
| JAV（无码） | 600s（10 分钟） |

并发限制：最多 2 个模块同时扫描（信号量控制）

---

## 常见问题

**Q：数据存储在哪个目录？**

A：`MDCX-Server/data/` 目录下，包含 SQLite 数据库、配置、缓存、封面缩略图等。

**Q：如何添加新的爬虫源？**

A：通过 YAML 声明式插件配置，详见 `app/config/` 下的站点注册表，无需修改核心代码。

**Q：支持哪些媒体服务器？**

A：Emby、Jellyfin（含 Metatube 路径）、TVBox、MacCMS、Stash、WebDAV 均可直接对接。

**Q：国产影片没有番号怎么刮削？**

A：内置 LLM 智能刮削（`llm_scraper.py`），支持 Ollama / Gemini / DeepSeek 等 OpenAI 兼容 API，通过文件名 + 封面反查获取元数据。

**Q：如何对接网盘？**

A：支持 CloudDrive2 和 115 网盘，通过配置项启用，可在高级 docker-compose 中使用。

**Q：Git 操作连不上 GitHub 怎么办？**

A：确认代理可用（Git 读取 `http.proxy` / `https.proxy` 配置）。也可用 `git -c http.proxy= fetch` 临时绕过代理走直连。

---

## 路线图

- [x] 8 模块独立数据库架构
- [x] 137 个爬虫源集成
- [x] LLM 智能刮削
- [x] 桌面客户端（Electron + Vue 3）
- [x] 自动整理与备份
- [x] Docker / K8s 部署
- [x] 多语言 README（简体 / 繁體 / English）
- [ ] 移动端客户端
- [ ] 多语言 UI（i18n）
- [ ] Web 端（无 Electron 依赖）
- [ ] Webhook / 第三方服务集成
- [ ] 图片反查功能

---

## 许可

本项目采用 [AGPL-3.0](LICENSE) 开源协议。

- 个人免费使用
- 非商业内部使用免费
- 商业使用请联系作者获取授权

---

## 贡献

欢迎提交 Issue 和 Pull Request。请先阅读 `docs/DEVELOPMENT_PLAN.md` 与 `docs/开发规则.md` 了解开发规范。

---

## 致谢

- 感谢 [JavBoss](https://github.com/JavBoss/JavBoss)、[JavLib](https://github.com/ForgQi/ForgQi.github.io)、[JavSP](https://github.com/xinxin999999/JavSP)、[yamdc](https://github.com/taxilian/yamdc)、[Javinizer](https://github.com/Javinizer/Javinizer)、[md-crawler](https://github.com/magnetico-io/md-crawler)、[mnamer](https://github.com/mnamer/mnamer) 等项目的设计灵感与代码参考
- 感谢 Playwright、curl-cffi、ArtPlayer、Element Plus 等开源社区
- 参考项目列表见 `docs/JAV系列参考项目_深度分析与复用评估.md`（130+ 项目分析）

---

---

<div id="zh-tw"></div>

# 繁體中文

## 簡介

MDCX 是一款**自託管**的本地影片庫管理系統，面向成人影片內容設計。它把「檔案掃描 → 封面抓取 → 演員資訊 → 去重比對 → 下載管理 → 多端播放 → 媒體伺服器分發」串成一條完整工作流。

系統採用**模組化架構**：每種內容類型獨立資料庫（SQLite），互不干擾，便於橫向擴展。

### 支援的內容模組

| 模組 | 資料庫 | 說明 |
|------|--------|------|
| JAV（審查） | `jav.db` | 日本成人影片（含審查片） |
| JAV（無碼） | `uncensored.db` | 無碼影片 |
| FC2-PPV | `fc2.db` | FC2 付費影片 |
| 國產 | `chinese.db` | 國產影片，支援 LLM 智能刮削 |
| 歐美 | `western.db` | Western 影片 |
| Pornhub | `pornhub.db` | Pornhub 內容 |
| 動漫 | `anime.db` | 動漫影片（Getchu 等來源） |
| 系統 | `system.db` | 使用者、會話、設定、快取、任務、工作流 |

共 **8 個獨立 SQLite 資料庫**，業務模組共用同一套正規化表結構（21 張共用基底表），透過外鍵聯結保證資料完整性。

### 核心特性

- **137 個爬蟲來源**：JavBus、JavDB、DMM、FC2-PPVDB、ThePornDB、Madou、Haijiao、Getchu 等
- **LLM 智能刮削**：基於 OpenAI 相容 API（Ollama / Gemini / DeepSeek），無番号影片也能抓取中繼資料
- **YAML 宣告式爬蟲外掛**：新增網站無需修改核心程式碼
- **智慧去重**：檔案雜湊 + 感知雜湊（pHash）+ 音訊指紋三重去重
- **封面管理**：多來源採集、人臉裁剪、自動降級、海報增強
- **批次刮削與修復**：自動偵測缺失欄位、智慧略過、分級報告
- **下載管理**：qBittorrent / Transmission / Aria2 / yt-dlp 直下
- **影片播放**：內嵌 ArtPlayer + HLS + 本地 mpv / ffplay，支援代理播放
- **媒體伺服器相容**：Emby / Jellyfin / Metatube / TVBox / MacCMS / Stash API / WebDAV
- **自動組織**：目錄監聽 + 定時整理 + NFO 產生（可自訂命名範本）
- **自動備份**：定時任務、訂閱監控、下載後自動處理
- **系統監控**：WebSocket 事件匯流排 + Prometheus 指標
- **6 套主題**：cinema / default / forest / midnight / rose / sunset
- **桌面客戶端**：Electron 33 + Vue 3 + Element Plus
- **AI 整合**：MCP 協定介面 + Telegram Bot 遠端控制
- **本地代理**：內建 Xray，設定熱重新載入

### 統計

| 指標 | 數量 |
|------|------|
| 後端路由檔案 | 94 |
| 爬蟲模組 | 137 |
| 服務模組 | 117 |
| 資料庫模型檔案 | 21 |
| 前端頁面 | 125 |
| 前端 API 客戶端 | 13 |
| Pinia Store | 16 |
| 通用元件 | 29 |
| 主題 | 6 |
| 文件 | 21 |

---

## 技術架構

### 後端 — `MDCX-Server/`

| 元件 | 技術選型 |
|------|----------|
| Web 框架 | FastAPI 0.135+ / Uvicorn |
| 資料庫 | SQLite (aiosqlite) + SQLAlchemy 2.x |
| 資料驗證 | Pydantic v2 |
| HTTP 客戶端 | curl-cffi（TLS 指紋，繞過 Cloudflare） |
| 反爬 / 解析 | lxml, BeautifulSoup, Playwright, cloudscraper |
| 圖片處理 | Pillow + OpenCV + MediaPipe + ONNX Runtime |
| 去重 | ImageHash (pHash) |
| 定時任務 | APScheduler |
| 檔案監控 | Watchdog |
| 認證 | python-jose (JWT) + passlib |
| 監控 | Prometheus Client |
| LLM | OpenAI SDK（相容 Ollama / Gemini / DeepSeek） |

**啟動流程**：日誌初始化 → 資料庫連線 → Schema 遷移 → 任務調度器 → 目錄監聽 → 自動掃描 → 封面補全 → 外掛系統 → 爬蟲設定 → CookieCloud 同步 → 網盤客戶端（CloudDrive2/115）→ 下載管理器 → 備份服務 → 訂閱自動下載 → 自動整理（每小時）→ Xray 代理 → 設定監聽

### 前端 — `MDCX-Desktop/`

| 元件 | 技術選型 |
|------|----------|
| 框架 | Vue 3.5 + Vue Router 4.5 |
| UI 庫 | Element Plus 2.9 + @element-plus/icons-vue |
| 狀態管理 | Pinia 2.3 + @vueuse/core |
| 播放器 | ArtPlayer 5.2 + hls.js 1.6 |
| 桌面殼 | Electron 33.2 + electron-builder 25.1 |
| 建置工具 | Vite 6.0 + vite-plugin-electron |
| HTTP 客戶端 | Axios |

**桌面客戶端特性**：自訂標題列、系統托盤、全域快捷鍵（`Ctrl+Shift+M` 顯隱，`Ctrl+Shift+P` 播放暫停）、自動更新、`mdcx://` 協定註冊、埠 8420 後端自動偵測

### 資料庫架構

8 個獨立 SQLite 資料庫：

| 資料庫 | 用途 |
|--------|------|
| 系統 | `system.db` | 使用者、會話、設定、快取、任務、工作流（12 張表） |
| `jav.db` | JAV（審查） |
| `uncensored.db` | JAV（無碼） |
| `fc2.db` | FC2-PPV |
| `chinese.db` | 國產 |
| `pornhub.db` | Pornhub |
| `western.db` | 歐美 |
| `anime.db` | 動漫 |

7 個業務模組共用同一套基底表（`movies` / `actors` / `studios` / `series` / `tags` / `play_history` / `import_records` 等），由 `app/db/_module_mixins.py` 統一定義，各模組只需匯入基底類別並宣告具體模型，無需重複定義欄位。

---

## 快速開始

### 環境要求

- **Python ≥ 3.11**
- **Node.js ≥ 22**
- **ffmpeg**（影片處理，專案內建 `bin/` 目錄）
- **Chromium**（Playwright 反爬，`playwright install chromium`）

### 後端啟動

```bash
cd MDCX-Server
pip install -r requirements.txt
playwright install chromium

# 運行伺服器（預設埠 8420）
python run.py --no-tray --no-browser
# 或
uvicorn app.main:app --host 0.0.0.0 --port 8420
```

API 基礎位址：`http://localhost:8420/api/v1`

設定目錄：`data/config/config.yaml`

### 桌面客戶端啟動

```bash
cd MDCX-Desktop
npm install
npm run dev
```

開發模式監聽 `localhost:5173`，`/api` 請求自動代理至 `localhost:8420`。

### 構建發佈

```bash
# 完整構建
npm run build

# Windows 便攜版
npm run build:win

# macOS DMG
npm run build:mac
```

### Docker 部署

```bash
cd MDCX-Server/deploy/docker
docker build -t mdcx-server .
docker run -d --name mdcx -p 8420:8420 \
  -v $(pwd)/data:/app/data \
  mdcx-server
```

或使用 docker-compose：

```bash
docker-compose up -d
# 或 advanced 版本（含 CloudDrive2 / 115 網盤掛載）
docker-compose -f docker-compose.advanced.yml up -d
```

---

## 專案結構

```
MDCX/
├── .gitignore
├── README.md            ← 本檔（簡體 / 繁體 / English）
├── MDCX-Server/         ← 後端
│   ├── app/
│   │   ├── api/routes/      94 個路由檔案
│   │   ├── crawlers/        137 個爬蟲（base/ md/src/ western/）
│   │   ├── db/              全模組資料庫模型（共用 Mixin + 8 庫）
│   │   ├── services/        117 個服務模組
│   │   ├── scraper/         刮削引擎（engine / merger / llm_scraper / comparator / extractor）
│   │   ├── patcher/         批次刮削與修復
│   │   ├── importer/        圖片掃描 / NFO 解析
│   │   ├── tasks/           掃描器 / 調度器 / 佇列
│   │   ├── config/          YAML 設定 / 站台註冊表 / 遷移
│   │   ├── external/        內建第三方爬蟲
│   │   ├── utils/           HTTP / 代理 / Cookie / 加密等工具
│   │   └── main.py          FastAPI 入口
│   ├── bin/                 ffmpeg / yt-dlp / xray 等二進位檔案
│   ├── deploy/              Docker / K8s / Nginx / systemd
│   ├── requirements.txt
│   └── pyproject.toml
├── MDCX-Desktop/        ← 前端 / 桌面客戶端
│   ├── src/
│   │   ├── api/             13 個 API 客戶端模組
│   │   ├── components/      29 個通用元件
│   │   ├── stores/          16 個 Pinia Store
│   │   ├── views/           125 個頁面（按內容模組組織）
│   │   └── themes/          6 套主題
│   ├── electron/
│   │   ├── main.js          Electron 主程序
│   │   └── preload.js       預載入腳本
│   ├── vite.config.js
│   └── package.json
└── docs/                ← 開發文件（21 篇）
```

---

## 文件索引

| 文件 | 說明 |
|------|------|
| `docs/PLAN.md` | 模組修復計畫與階段路線圖 |
| `docs/new-database-architecture.md` | v2.0 資料庫設計（8 庫，共用基底表） |
| `docs/MDCX資料流向總結.md` | 資料流向圖（封面 / 批刮 / 演員頭像） |
| `docs/開發設計_5模組架構擴展.md` | 架構設計詳述（含 130+ 參考專案分析） |
| `docs/DEVELOPMENT_PLAN.md` | 整合開發計畫（10 階段） |
| `docs/DEPLOY_SERVER.md` | 伺服器部署清單 |
| `docs/DEPLOY_DEPENDENCIES.md` | 部署依賴說明 |
| `docs/JAV系列參考專案_深度分析與複用評估.md` | 參考專案複用評估 |
| `docs/命名規則規範_MDCX.md` | NFO 命名規則規範 |
| `docs/開發規則.md` | 開發規範 |
| `docs/MDCX桌面端重構方案.md` | 桌面端重構方案 |

---

## API 介面

| 路由前綴 | 說明 |
|----------|------|
| `/api/v1/*` | 核心業務 API |
| `/emby/*` | Emby 相容介面 |
| `/tvbox/*` | TVBox 相容介面 |
| `/maccms/*` | MacCMS 相容介面 |
| `/webdav/*` | WebDAV 檔案存取 |
| `/metatube/*` | Jellyfin 相容介面 |
| `/ws/*` | WebSocket 事件推送 |
| `/metrics` | Prometheus 監控指標 |

---

## 掃描逾時與並行

| 模組 | 單模組掃描逾時 |
|------|---------------|
| Pornhub | 7200s（2 小時） |
| JAV（審查） | 3600s（1 小時） |
| 國產 / 歐美 | 1800s（30 分鐘） |
| FC2 / 動漫 | 900s（15 分鐘） |
| JAV（無碼） | 600s（10 分鐘） |

並行限制：最多 2 個模組同時掃描（訊號量控制）

---

## 常見問題

**Q：資料儲存在哪個目錄？**

A：`MDCX-Server/data/` 目錄下，包含 SQLite 資料庫、設定、快取、封面縮圖等。

**Q：如何新增新的爬蟲來源？**

A：透過 YAML 宣告式外掛設定，詳見 `app/config/` 下的站台註冊表，無需修改核心程式碼。

**Q：支援哪些媒體伺服器？**

A：Emby、Jellyfin（含 Metatube 路徑）、TVBox、MacCMS、Stash、WebDAV 均可直接對接。

**Q：國產影片沒有番号怎麼刮削？**

A：內建 LLM 智能刮削（`llm_scraper.py`），支援 Ollama / Gemini / DeepSeek 等 OpenAI 相容 API，透過檔名 + 封面反查取得中繼資料。

**Q：如何對接網盤？**

A：支援 CloudDrive2 和 115 網盤，透過設定項啟用，可在進階 docker-compose 中使用。

**Q：Git 操作連不上 GitHub 怎麼辦？**

A：確認代理可用（Git 讀取 `http.proxy` / `https.proxy` 設定）。也可用 `git -c http.proxy= fetch` 暫時繞過代理走直連。

---

## 路線圖

- [x] 8 模組獨立資料庫架構
- [x] 137 個爬蟲來源整合
- [x] LLM 智能刮削
- [x] 桌面客戶端（Electron + Vue 3）
- [x] 自動整理與備份
- [x] Docker / K8s 部署
- [x] 多語言 README（簡體 / 繁體 / English）
- [ ] 行動端客戶端
- [ ] 多語言 UI（i18n）
- [ ] Web 端（無 Electron 依賴）
- [ ] Webhook / 第三方服務整合
- [ ] 圖片反查功能

---

## 授權

本專案採用 [AGPL-3.0](LICENSE) 開源協定。

- 個人免費使用
- 非商業內部使用免費
- 商業使用請聯繫作者取得授權

---

## 貢獻

歡迎提交 Issue 和 Pull Request。請先閱讀 `docs/DEVELOPMENT_PLAN.md` 與 `docs/開發規則.md` 了解開發規範。

---

## 致謝

- 感謝 [JavBoss](https://github.com/JavBoss/JavBoss)、[JavLib](https://github.com/ForgQi/ForgQi.github.io)、[JavSP](https://github.com/xinxin999999/JavSP)、[yamdc](https://github.com/taxilian/yamdc)、[Javinizer](https://github.com/Javinizer/Javinizer)、[md-crawler](https://github.com/magnetico-io/md-crawler)、[mnamer](https://github.com/mnamer/mnamer) 等專案的設計靈感與程式碼參考
- 感謝 Playwright、curl-cffi、ArtPlayer、Element Plus 等開源社群
- 參考專案列表見 `docs/JAV系列參考專案_深度分析與複用評估.md`（130+ 專案分析）

---

---

<a id="en"></a>
# English

## Overview

MDCX is a **self-hosted** local video library management system designed for **adult video content**. It chains the full workflow: file scanning → cover fetching → actor metadata → deduplication → download management → multi-device playback → media server distribution.

The system uses a **modular architecture**: each content type lives in its own SQLite database, fully isolated and horizontally extensible.

### Supported Content Modules

| Module | Database | Description |
|--------|----------|-------------|
| JAV (Censored) | `jav.db` | Japanese AV (censored) |
| JAV (Uncensored) | `uncensored.db` | Uncensored Japanese AV |
| FC2-PPV | `fc2.db` | FC2 Pay-Per-View |
| Chinese | `chinese.db` | Chinese domestic content (LLM scraping) |
| Western | `western.db` | Western adult content |
| Pornhub | `pornhub.db` | Pornhub content |
| Anime | `anime.db` | Anime content (Getchu and more) |
| System | `system.db` | Users, sessions, settings, cache, tasks, workflows |

**8 independent SQLite databases** in total. Business modules share one normalized schema (21 shared base tables) with foreign-key cascading for referential integrity.

### Key Features

- **137 scraping sources**: JavBus, JavDB, DMM, FC2-PPVDB, ThePornDB, Madou, Haijiao, Getchu, and more
- **LLM intelligent scraping**: Based on OpenAI-compatible API (Ollama / Gemini / DeepSeek), extracts metadata even without standard codes
- **YAML declarative crawler plugins**: Add new sources without touching core code
- **Smart deduplication**: File hash + perceptual hash (pHash) + audio fingerprint triple dedup
- **Cover management**: Multi-source collection, face cropping, auto fallback, poster enhancement
- **Batch scraping & patching**: Auto-detect missing fields, smart skip, graded reports
- **Download management**: qBittorrent / Transmission / Aria2 / yt-dlp direct
- **Video playback**: Embedded ArtPlayer + HLS + local mpv / ffplay, proxy playback supported
- **Media server compatibility**: Emby / Jellyfin / Metatube / TVBox / MacCMS / Stash API / WebDAV
- **Auto-organization**: Directory monitoring + scheduled sorting + NFO generation (custom naming templates)
- **Auto-backup**: Scheduled tasks, subscription monitoring, post-download processing
- **System monitoring**: WebSocket event bus + Prometheus metrics
- **6 themes**: cinema / default / forest / midnight / rose / sunset
- **Desktop client**: Electron 33 + Vue 3 + Element Plus
- **AI integration**: MCP protocol interface + Telegram Bot remote control
- **Local proxy**: Bundled Xray with config hot-reload

### Statistics

| Metric | Count |
|--------|-------|
| Backend route files | 94 |
| Crawler modules | 137 |
| Service modules | 117 |
| DB model files | 21 |
| Frontend pages | 125 |
| Frontend API clients | 13 |
| Pinia stores | 16 |
| Shared components | 29 |
| Themes | 6 |
| Documentation | 21 |

---

## Technology Stack

### Backend — `MDCX-Server/`

| Component | Technology |
|-----------|------------|
| Web Framework | FastAPI 0.135+ / Uvicorn |
| Database | SQLite (aiosqlite) + SQLAlchemy 2.x |
| Data Validation | Pydantic v2 |
| HTTP Client | curl-cffi (TLS fingerprinting, bypasses Cloudflare) |
| Anti-bot / Parsing | lxml, BeautifulSoup, Playwright, cloudscraper |
| Image Processing | Pillow + OpenCV + MediaPipe + ONNX Runtime |
| Deduplication | ImageHash (pHash) |
| Task Scheduling | APScheduler |
| File Monitoring | Watchdog |
| Authentication | python-jose (JWT) + passlib |
| Monitoring | Prometheus Client |
| LLM | OpenAI SDK (compatible with Ollama / Gemini / DeepSeek) |

**Startup sequence**: Logging init → DB connections → Schema migrations → Scheduler → Directory watcher → Auto-scan → Cover backfill → Plugin system → Crawler settings → CookieCloud sync → CloudDrive2/115 clients → Download manager → Backup service → Subscription downloader → Auto-organize (hourly) → Xray proxy → Config watcher

### Frontend — `MDCX-Desktop/`

| Component | Technology |
|-----------|------------|
| Framework | Vue 3.5 + Vue Router 4.5 |
| UI Library | Element Plus 2.9 + @element-plus/icons-vue |
| State Management | Pinia 2.3 + @vueuse/core |
| Video Player | ArtPlayer 5.2 + hls.js 1.6 |
| Desktop Shell | Electron 33.2 + electron-builder 25.1 |
| Build Tool | Vite 6.0 + vite-plugin-electron |
| HTTP Client | Axios |

**Desktop client features**: Custom title bar, system tray, global shortcuts (`Ctrl+Shift+M` show/hide, `Ctrl+Shift+P` play/pause), auto-update, `mdcx://` protocol registration, auto-detect backend on port 8420

### Database Architecture

8 independent SQLite databases:

| Database | Purpose |
|----------|---------|
| `system.db` | Users, sessions, settings, cache, tasks, workflows (12 tables) |
| `jav.db` | JAV (Censored) |
| `uncensored.db` | JAV (Uncensored) |
| `fc2.db` | FC2-PPV |
| `chinese.db` | Chinese domestic |
| `pornhub.db` | Pornhub |
| `western.db` | Western content |
| `anime.db` | Anime |

All 7 business modules share the same base tables (`movies` / `actors` / `studios` / `series` / `tags` / `play_history` / `import_records`, etc.), defined once in `app/db/_module_mixins.py`. Each module only imports the base classes and declares its concrete models — no column duplication.

---

## Quick Start

### Requirements

- **Python ≥ 3.11**
- **Node.js ≥ 22**
- **ffmpeg** (video processing, bundled in `bin/`)
- **Chromium** (Playwright anti-bot, `playwright install chromium`)

### Backend

```bash
cd MDCX-Server
pip install -r requirements.txt
playwright install chromium

# Run server (default port 8420)
python run.py --no-tray --no-browser
# Or
uvicorn app.main:app --host 0.0.0.0 --port 8420
```

API base URL: `http://localhost:8420/api/v1`

Config directory: `data/config/config.yaml`

### Desktop Client

```bash
cd MDCX-Desktop
npm install
npm run dev
```

Dev mode listens on `localhost:5173`; `/api` requests are proxied to `localhost:8420`.

### Build for Production

```bash
# Full build
npm run build

# Windows portable
npm run build:win

# macOS DMG
npm run build:mac
```

### Docker Deployment

```bash
cd MDCX-Server/deploy/docker
docker build -t mdcx-server .
docker run -d --name mdcx -p 8420:8420 \
  -v $(pwd)/data:/app/data \
  mdcx-server
```

Or with docker-compose:

```bash
docker-compose up -d
# Or the advanced version (with CloudDrive2 / 115 drive mounts)
docker-compose -f docker-compose.advanced.yml up -d
```

---

## Project Structure

```
MDCX/
├── .gitignore
├── README.md            ← This file (Simplified / Traditional / English)
├── MDCX-Server/         ← Backend
│   ├── app/
│   │   ├── api/routes/      94 route files
│   │   ├── crawlers/        137 crawlers (base/ md/src/ western/)
│   │   ├── db/              DB models for all modules (shared Mixin + 8 DBs)
│   │   ├── services/        117 service modules
│   │   ├── scraper/         Scraping engine (engine / merger / llm_scraper / comparator / extractor)
│   │   ├── patcher/         Batch scraping & patching
│   │   ├── importer/        Image scanner / NFO parser
│   │   ├── tasks/           Scanners / scheduler / queue
│   │   ├── config/          YAML config / site registry / migrations
│   │   ├── external/        Bundled third-party crawlers
│   │   ├── utils/           HTTP / proxy / cookie / crypto helpers
│   │   └── main.py          FastAPI entry point
│   ├── bin/                 ffmpeg / yt-dlp / xray binaries
│   ├── deploy/              Docker / K8s / Nginx / systemd
│   ├── requirements.txt
│   └── pyproject.toml
├── MDCX-Desktop/        ← Frontend / Desktop Client
│   ├── src/
│   │   ├── api/             13 API client modules
│   │   ├── components/      29 shared components
│   │   ├── stores/          16 Pinia stores
│   │   ├── views/           125 view pages (organized by module)
│   │   └── themes/          6 themes
│   ├── electron/
│   │   ├── main.js          Electron main process
│   │   └── preload.js       Preload script
│   ├── vite.config.js
│   └── package.json
└── docs/                ← Development docs (21 articles)
```

---

## Documentation

| Document | Description |
|----------|-------------|
| `docs/PLAN.md` | Module fix plan and phase roadmap |
| `docs/new-database-architecture.md` | v2.0 database design (8 DBs, shared base tables) |
| `docs/MDCX数据流向总结.md` | Data flow diagram (covers, batch scraping, actor avatars) |
| `docs/开发设计_5模块架构扩展.md` | Comprehensive architecture design (130+ reference projects) |
| `docs/DEVELOPMENT_PLAN.md` | Integration development plan (10 phases) |
| `docs/DEPLOY_SERVER.md` | Server deployment checklist |
| `docs/DEPLOY_DEPENDENCIES.md` | Deployment dependencies |
| `docs/JAV系列参考项目_深度分析与复用评估.md` | Reference project reuse assessment |
| `docs/命名规则规范_MDCX.md` | NFO naming convention spec |
| `docs/开发规则.md` | Development guidelines |
| `docs/MDCX桌面端重构方案.md` | Desktop client refactor plan |

---

## API Endpoints

| Route Prefix | Description |
|-------------|-------------|
| `/api/v1/*` | Core business API |
| `/emby/*` | Emby compatibility |
| `/tvbox/*` | TVBox compatibility |
| `/maccms/*` | MacCMS compatibility |
| `/webdav/*` | WebDAV file access |
| `/metatube/*` | Jellyfin compatibility |
| `/ws/*` | WebSocket event push |
| `/metrics` | Prometheus monitoring metrics |

---

## Scan Timeouts & Concurrency

| Module | Per-Module Timeout |
|--------|--------------------|
| Pornhub | 7200s (2 hours) |
| JAV (Censored) | 3600s (1 hour) |
| Chinese / Western | 1800s (30 minutes) |
| FC2 / Anime | 900s (15 minutes) |
| JAV (Uncensored) | 600s (10 minutes) |

Concurrency limit: max 2 module scans simultaneously (semaphore-based)

---

## FAQ

**Q: Where is data stored?**

A: Under `MDCX-Server/data/`, containing SQLite databases, config, cache, and cover thumbnails.

**Q: How do I add a new scraping source?**

A: Via YAML declarative plugin configuration. See the site registry in `app/config/` — no core code changes needed.

**Q: Which media servers are supported?**

A: Emby, Jellyfin (including Metatube path), TVBox, MacCMS, Stash, and WebDAV — all directly compatible.

**Q: How do I scrape Chinese content without standard codes?**

A: Built-in LLM smart scraper (`llm_scraper.py`) supports Ollama / Gemini / DeepSeek and other OpenAI-compatible APIs. Extracts metadata via filename + cover reverse lookup.

**Q: How do I connect cloud drives?**

A: CloudDrive2 and 115 cloud drives are supported. Enable via config options; usable in the advanced docker-compose.

**Q: What if Git can't reach GitHub?**

A: Check that your proxy is running (Git reads `http.proxy` / `https.proxy` from config). You can also bypass the proxy with `git -c http.proxy= fetch` for a direct connection.

---

## Roadmap

- [x] 8-module independent database architecture
- [x] 137 scraping sources integrated
- [x] LLM intelligent scraping
- [x] Desktop client (Electron + Vue 3)
- [x] Auto-organization & backup
- [x] Docker / K8s deployment
- [x] Multi-language README (Simplified / Traditional / English)
- [ ] Mobile client
- [ ] Multi-language UI (i18n)
- [ ] Web-only version (no Electron dependency)
- [ ] Webhook / third-party service integration
- [ ] Reverse image search

---

## License

This project is licensed under the [AGPL-3.0](LICENSE) open source license.

- Free for personal use
- Free for non-commercial internal use
- Commercial use requires authorization — contact the author

---

## Contributing

Issues and Pull Requests are welcome. Please read `docs/DEVELOPMENT_PLAN.md` and `docs/开发规则.md` for development guidelines.

---

## Acknowledgments

- Thanks to [JavBoss](https://github.com/JavBoss/JavBoss), [JavLib](https://github.com/ForgQi/ForgQi.github.io), [JavSP](https://github.com/xinxin999999/JavSP), [yamdc](https://github.com/taxilian/yamdc), [Javinizer](https://github.com/Javinizer/Javinizer), [md-crawler](https://github.com/magnetico-io/md-crawler), [mnamer](https://github.com/mnamer/mnamer), and other projects for design inspiration and code reference
- Thanks to Playwright, curl-cffi, ArtPlayer, Element Plus, and the open-source community
- Reference project list: `docs/JAV系列参考项目_深度分析与复用评估.md` (130+ projects analyzed)

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/DragonSouls233">DragonSouls233</a>
</p>
