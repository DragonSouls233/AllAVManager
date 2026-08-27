# MDCX — 视频元数据管理系统

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135+-009688)
![Vue 3](https://img.shields.io/badge/Vue-3.5+-42B883)
![Electron](https://img.shields.io/badge/Electron-33.2+-47848F)
![License](https://img.shields.io/badge/License-AGPL--3.0-red.svg)

---

<div align="center">

## 龙魂 · 视频元数据管理系统

> 基于 FastAPI + Vue 3 + Electron 的自托管视频库管理平台，
> 支持智能刮削、去重、播放、组织与分发。

</div>

---

## 1. 项目简介

MDCX 是一个自托管的本地视频库管理系统，专为 **成人视频内容** 设计。它集成了从文件扫描、封面抓取、演员信息、下载管理到多端播放与分发的完整工作流。

系统采用 **模块化架构**，每种视频类型独立数据库（SQLite），互不干扰，便于扩展。

### 支持的内容模块

| 模块 | 说明 |
|------|------|
| JAV（审查） | 日本成人影片（含审查片） |
| JAV（无码） | 无码影片 |
| FC2-PPV | FC2 付费影片 |
| 国产 | 国产影片（支持 LLM 智能刮削） |
| 欧美 | Western 影片 |
| Pornhub | Pornhub 内容 |
| 动漫 | 动漫影片 |

### 核心特性

- **55+ 爬虫源**：JavBus、JavDB、DMM、FC2-PPVDB、ThePornDB、Madou、Haijiao 等
- **LLM 智能刮削**：基于 OpenAI 兼容 API（支持 Ollama / Gemini / DeepSeek），无番号影片也能抓取元数据
- **YAML 声明式爬虫插件**：新增网站无需修改代码
- **智能去重**：文件哈希 + 感知哈希（pHash）+ 音频指纹三重去重
- **封面管理**：多源采集、人脸裁剪、自动降级
- **批量刮削 & 修复**：自动检测缺失字段、智能跳过、分级报告
- **下载管理**：qBittorrent / Transmission / Aria2 / yt-dlp 直下
- **视频播放**：内嵌 ArtPlayer + HLS 支持 + 代理播放
- **媒体服务器兼容**：Emby / Jellyfin / Metatube / TVBox / Stash API / WebDAV
- **自动组织**：目录监听 + 定时整理 + NFO 生成
- **自动备份**：定时任务、订阅监控、下载后自动处理
- **系统状态监控**：WebSocket 事件总线 + Prometheus 指标
- **6 套主题**：cinema / default / forest / midnight / rose / sunset
- **桌面客户端**：Electron + Vue 3 + Element Plus
- **MCP 协议**：AI 工具调用接口
- **Telegram Bot**：远程控制

---

## 2. 技术架构

### 后端 — `MDCX-Server/`

| 组件 | 技术选型 |
|------|----------|
| Web 框架 | FastAPI 0.135+ / Uvicorn |
| 数据库 | SQLite (aiosqlite) + SQLAlchemy 2.x |
| 数据校验 | Pydantic v2 |
| HTTP 客户端 | curl-cffi（TLS 指纹，绕过 Cloudflare） |
| 反爬 / 解析 | lxml, BeautifulSoup, Playwright, cloudscraper, undetected-chromedriver |
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

7 个独立 SQLite 数据库，共约 132 张表：

| 数据库 | 用途 | 表数 |
|--------|------|------|
| `system.db` | 用户、会话、设置、缓存、任务、工作流 | 12 |
| `jav.db` | JAV（审查） | 20 |
| `uncensored.db` | JAV（无码） | 20 |
| `fc2.db` | FC2-PPV | 20 |
| `chinese.db` | 国产 | 20 |
| `pornhub.db` | Pornhub | 20 |
| `western.db` | 欧美 | 20 |

每个模块数据库共享同一规范化 Schema（movies / actors / studios / series / tags / play_history / import_records 等），通过外键级联保证数据完整性。

---

## 3. 快速开始

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

## 4. 项目结构

```
MDCX/
├── .gitignore
├── README.md
├── README_CN.md         ← 中文版本（独立文件）
├── MDCX-Server/         ← 后端
│   ├── app/
│   │   ├── api/routes/      70+ 路由文件
│   │   ├── crawlers/        55+ 爬虫（base/ md/src/ western/）
│   │   ├── db/              全模块数据库模型
│   │   ├── services/        90+ 服务模块
│   │   ├── scraper/         刮削引擎（engine / merger / llm_scraper / comparator / extractor）
│   │   ├── patcher/         批量刮削与修复
│   │   ├── importer/        图片扫描 / NFO 解析
│   │   ├── tasks/           扫描器 / 调度器 / 队列
│   │   ├── config/          YAML 配置 / 站点注册表 / 迁移
│   │   ├── external/        内置第三方爬虫
│   │   ├── utils/           HTTP / 代理 / Cookie / 加密等工具
│   │   └── main.py          FastAPI 入口（1092 行）
│   ├── bin/                 ffmpeg / yt-dlp / xray 等二进制文件
│   ├── deploy/              Docker / K8s / Nginx / systemd
│   ├── requirements.txt
│   └── pyproject.toml
├── MDCX-Desktop/        ← 前端 / 桌面客户端
│   ├── src/
│   │   ├── api/             16 个 API 客户端模块
│   │   ├── components/      30+ 通用组件
│   │   ├── stores/          14 个 Pinia Store
│   │   ├── views/           80+ 页面（按内容模块组织）
│   │   └── themes/          6 套主题
│   ├── electron/
│   │   ├── main.js          Electron 主进程（800 行）
│   │   └── preload.js       预加载脚本
│   ├── vite.config.js
│   └── package.json
└── docs/                ← 开发文档（中文，20+ 篇）
```

---

## 5. 文档索引

| 文档 | 说明 |
|------|------|
| `docs/PLAN.md` | 6 模块修复计划与阶段路线图 |
| `docs/new-database-architecture.md` | v2.0 数据库设计（7 库 132 表） |
| `docs/MDCX数据流向总结.md` | 数据流向图（封面 / 批刮 / 演员头像） |
| `docs/开发设计_5模块架构扩展.md` | 架构设计详述（含 130+ 参考项目分析） |
| `docs/DEVELOPMENT_PLAN.md` | 集成开发计划（10 阶段） |
| `docs/DEPLOY_SERVER.md` | 服务器部署清单 |

> 更多开发设计文档见 [Wiki](https://tinypinglite.github.io/sakuramedia/)

---

## 6. API 接口

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

## 7. 扫描超时与并发

| 模块 | 单模块扫描超时 |
|------|---------------|
| Pornhub | 7200s（2 小时） |
| JAV（审查） | 3600s（1 小时） |
| 国产 / 欧美 | 1800s（30 分钟） |
| FC2 / 动漫 | 900s（15 分钟） |
| JAV（无码） | 600s（10 分钟） |

并发限制：最多 2 个模块同时扫描（信号量控制）

---

## 8. 常见问题

**Q：数据存储在哪个目录？**

A：`MDCX-Server/data/` 目录下，包含 SQLite 数据库、配置、缓存、封面缩略图等。

**Q：如何添加新的爬虫源？**

A：通过 YAML 声明式插件配置，详见 `app/config/` 下的站点注册表，无需修改核心代码。

**Q：支持哪些媒体服务器？**

A：Emby、Jellyfin（含 Metatube 路径）、TVBox、Stash、WebDAV 均可直接对接。

**Q：国产影片没有番号怎么刮削？**

A：内置 LLM 智能刮削（`llm_scraper.py`），支持 Ollama / Gemini / DeepSeek 等 OpenAI 兼容 API，通过文件名 + 封面反查获取元数据。

**Q：如何对接网盘？**

A：支持 CloudDrive2 和 115 网盘，通过配置项启用，可在高级 docker-compose 中使用。

---

## 9. 路线图

- [x] 7 模块独立数据库架构
- [x] 55+ 爬虫源集成
- [x] LLM 智能刮削
- [x] 桌面客户端（Electron + Vue 3）
- [x] 自动整理与备份
- [x] Docker / K8s 部署
- [ ] 移动端客户端
- [ ] 多语言 UI（i18n）
- [ ] Web 端（无 Electron 依赖）
- [ ] Webhook / 第三方服务集成
- [ ] 图片反查功能

---

## 10. 许可

本项目采用 [AGPL-3.0](LICENSE) 开源协议。

- 个人免费使用
- 非商业内部使用免费
- 商业使用请联系作者获取授权

---

## 11. 贡献

欢迎提交 Issue 和 Pull Request。请先阅读 `docs/DEVELOPMENT_PLAN.md` 了解开发规范。

---

## 12. 致谢

- 感谢 [JavBoss](https://github.com/JavBoss/JavBoss)、[JavLib](https://github.com/ForgQi/ForgQi.github.io)、[JavSP](https://github.com/xinxin999999/JavSP)、[yamdc](https://github.com/taxilian/yamdc)、[Javinizer](https://github.com/Javinizer/Javinizer)、[md-crawler](https://github.com/magnetico-io/md-crawler)、[mnamer](https://github.com/mnamer/mnamer) 等项目的设计灵感与代码参考
- 感谢 Playwright、curl-cffi、ArtPlayer、Element Plus 等开源社区
- 参考项目列表见 `docs/开发设计_5模块架构扩展.md`（130+ 项目分析）

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/tinypinglite">tinypinglite</a>
</p>

---

<div align="center">

***

# MDCX — Video Metadata Management System

<div align="center">

## Dragon Soul · Video Library Management

> A self-hosted video library management platform powered by FastAPI, Vue 3, and Electron.
> Featuring intelligent scraping, deduplication, playback, organization, and distribution.

</div>

</div>

---

## 1. Overview

MDCX is a self-hosted local video library management system designed for **adult video content**. It integrates a complete workflow from file scanning, cover art fetching, actor information, download management, to multi-platform playback and distribution.

The system uses a **modular architecture**, with each content type backed by its own SQLite database, independent and extensible.

### Supported Content Modules

| Module | Description |
|--------|-------------|
| JAV (Censored) | Japanese AV (censored) |
| JAV (Uncensored) | Uncensored Japanese AV |
| FC2-PPV | FC2 Pay-Per-View |
| Chinese | Chinese domestic content (with LLM scraping) |
| Western | Western adult content |
| Pornhub | Pornhub content |
| Anime | Anime content |

### Key Features

- **55+ scraping sources**: JavBus, JavDB, DMM, FC2-PPVDB, ThePornDB, Madou, Haijiao, and more
- **LLM intelligent scraping**: Based on OpenAI-compatible API (Ollama / Gemini / DeepSeek), extracts metadata even without standard codes
- **YAML declarative crawler plugins**: Add new sources without modifying code
- **Smart deduplication**: File hash + perceptual hash (pHash) + audio fingerprint triple dedup
- **Cover management**: Multi-source collection, face cropping, auto fallback
- **Batch scraping & patching**: Auto-detect missing fields, smart skip, graded reports
- **Download management**: qBittorrent / Transmission / Aria2 / yt-dlp direct
- **Video playback**: Embedded ArtPlayer + HLS support + proxy playback
- **Media server compatibility**: Emby / Jellyfin / Metatube / TVBox / Stash API / WebDAV
- **Auto-organization**: Directory monitoring + scheduled sorting + NFO generation
- **Auto-backup**: Scheduled tasks, subscription monitoring, post-download processing
- **System monitoring**: WebSocket event bus + Prometheus metrics
- **6 themes**: cinema / default / forest / midnight / rose / sunset
- **Desktop client**: Electron + Vue 3 + Element Plus
- **MCP protocol**: AI tool calling interface
- **Telegram Bot**: Remote control

---

## 2. Technology Stack

### Backend — `MDCX-Server/`

| Component | Technology |
|-----------|------------|
| Web Framework | FastAPI 0.135+ / Uvicorn |
| Database | SQLite (aiosqlite) + SQLAlchemy 2.x |
| Data Validation | Pydantic v2 |
| HTTP Client | curl-cffi (TLS fingerprinting, bypasses Cloudflare) |
| Anti-bot / Parsing | lxml, BeautifulSoup, Playwright, cloudscraper, undetected-chromedriver |
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
| UI Library | Element Plus 2.9 |
| State Management | Pinia 2.3 + @vueuse/core |
| Video Player | ArtPlayer 5.2 + hls.js 1.6 |
| Desktop Shell | Electron 33.2 + electron-builder 25.1 |
| Build Tool | Vite 6.0 + vite-plugin-electron |
| HTTP Client | Axios |

**Desktop client features**: Custom title bar, system tray, global shortcuts (`Ctrl+Shift+M` show/hide, `Ctrl+Shift+P` play/pause), auto-update, `mdcx://` protocol registration, auto-detect backend on port 8420

### Database Architecture

7 independent SQLite databases, ~132 tables total:

| Database | Purpose | Tables |
|----------|---------|--------|
| `system.db` | Users, sessions, settings, cache, tasks, workflows | 12 |
| `jav.db` | JAV (Censored) | 20 |
| `uncensored.db` | JAV (Uncensored) | 20 |
| `fc2.db` | FC2-PPV | 20 |
| `chinese.db` | Chinese domestic | 20 |
| `pornhub.db` | Pornhub | 20 |
| `western.db` | Western content | 20 |

Each module database shares the same normalized schema (movies / actors / studios / series / tags / play_history / import_records, etc.) with foreign key cascading for referential integrity.

---

## 3. Quick Start

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

Dev mode listens on `localhost:5173`, `/api` requests are proxied to `localhost:8420`.

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
# Or advanced version (with CloudDrive2 / 115 drive mount)
docker-compose -f docker-compose.advanced.yml up -d
```

---

## 4. Project Structure

```
MDCX/
├── .gitignore
├── README.md
├── MDCX-Server/         Backend
│   ├── app/
│   │   ├── api/routes/      70+ route files
│   │   ├── crawlers/        55+ crawlers (base/ md/src/ western/)
│   │   ├── db/              Database models for all modules
│   │   ├── services/        90+ service modules
│   │   ├── scraper/         Scraping engine (engine / merger / llm_scraper / comparator / extractor)
│   │   ├── patcher/         Batch scraping & patching
│   │   ├── importer/        Image scanner / NFO parser
│   │   ├── tasks/           Scanners / scheduler / queue
│   │   ├── config/          YAML config / site registry / migrations
│   │   ├── external/        Bundled third-party crawlers
│   │   ├── utils/           HTTP / proxy / cookie / crypto helpers
│   │   └── main.py          FastAPI entry point (1092 lines)
│   ├── bin/                 ffmpeg / yt-dlp / xray binaries
│   ├── deploy/              Docker / K8s / Nginx / systemd
│   ├── requirements.txt
│   └── pyproject.toml
├── MDCX-Desktop/        Frontend / Desktop Client
│   ├── src/
│   │   ├── api/             16 API client modules
│   │   ├── components/      30+ shared components
│   │   ├── stores/          14 Pinia stores
│   │   ├── views/           80+ view pages (organized by module)
│   │   └── themes/          6 themes
│   ├── electron/
│   │   ├── main.js          Electron main process (800 lines)
│   │   └── preload.js       Preload script
│   ├── vite.config.js
│   └── package.json
└── docs/                Development docs (Chinese, 20+ articles)
```

---

## 5. Documentation

| Document | Description |
|----------|-------------|
| `docs/PLAN.md` | 6-module fix plan and phase roadmap |
| `docs/new-database-architecture.md` | v2.0 database design (7 DBs, 132 tables) |
| `docs/MDCX数据流向总结.md` | Data flow diagram (covers, batch scraping, actor avatars) |
| `docs/开发设计_5模块架构扩展.md` | Comprehensive architecture design (130+ reference projects) |
| `docs/DEVELOPMENT_PLAN.md` | Integration development plan (10 phases) |
| `docs/DEPLOY_SERVER.md` | Server deployment checklist |

> More dev docs at [Wiki](https://tinypinglite.github.io/sakuramedia/)

---

## 6. API Endpoints

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

## 7. Scan Timeouts & Concurrency

| Module | Per-Module Timeout |
|--------|--------------------|
| Pornhub | 7200s (2 hours) |
| JAV (Censored) | 3600s (1 hour) |
| Chinese / Western | 1800s (30 minutes) |
| FC2 / Anime | 900s (15 minutes) |
| JAV (Uncensored) | 600s (10 minutes) |

Concurrency limit: max 2 module scans simultaneously (semaphore-based)

---

## 8. FAQ

**Q: Where is data stored?**

A: Under `MDCX-Server/data/`, containing SQLite databases, config, cache, and cover thumbnails.

**Q: How to add a new scraping source?**

A: Via YAML declarative plugin configuration. See the site registry in `app/config/` — no core code changes needed.

**Q: Which media servers are supported?**

A: Emby, Jellyfin (including Metatube path), TVBox, Stash, and WebDAV — all directly compatible.

**Q: How to scrape Chinese content without standard codes?**

A: Built-in LLM smart scraper (`llm_scraper.py`) supports Ollama / Gemini / DeepSeek and other OpenAI-compatible APIs. Extracts metadata via filename + cover reverse lookup.

**Q: How to connect cloud drives?**

A: CloudDrive2 and 115 cloud drive are supported. Enable via config options, usable in advanced docker-compose.

---

## 9. Roadmap

- [x] 7-module independent database architecture
- [x] 55+ scraping sources integrated
- [x] LLM intelligent scraping
- [x] Desktop client (Electron + Vue 3)
- [x] Auto-organization & backup
- [x] Docker / K8s deployment
- [ ] Mobile client
- [ ] Multi-language UI (i18n)
- [ ] Web-only version (no Electron dependency)
- [ ] Webhook / third-party service integration
- [ ] Reverse image search

---

## 10. License

This project is licensed under the [AGPL-3.0](LICENSE) open source license.

- Free for personal use
- Free for non-commercial internal use
- Commercial use requires authorization, contact the author

---

## 11. Contributing

Issues and Pull Requests are welcome. Please read `docs/DEVELOPMENT_PLAN.md` for development guidelines.

---

## 12. Acknowledgments

- Thanks to [JavBoss](https://github.com/JavBoss/JavBoss), [JavLib](https://github.com/ForgQi/ForgQi.github.io), [JavSP](https://github.com/xinxin999999/JavSP), [yamdc](https://github.com/taxilian/yamdc), [Javinizer](https://github.com/Javinizer/Javinizer), [md-crawler](https://github.com/magnetico-io/md-crawler), [mnamer](https://github.com/mnamer/mnamer), and other projects for design inspiration and code reference
- Thanks to Playwright, curl-cffi, ArtPlayer, Element Plus, and the open-source community
- Reference project list see `docs/开发设计_5模块架构扩展.md` (130+ projects analyzed)

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/tinypinglite">tinypinglite</a>
</p>