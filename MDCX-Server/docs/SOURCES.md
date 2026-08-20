# 上游协议/逆向来源追踪

> 本文档集中记录**所有依赖上游项目逆向或非公开协议**的模块。**版本失效时**按本文档定位文件 → 找到 `*_META` 字典 → 同步更新常量 + 复现步骤。

---

## JavDB 匿名 App API

| 字段 | 值 |
|---|---|
| **状态** | ✅ 工作中 |
| **客户端** | `app/services/javdb_app_client.py` |
| **元数据常量** | `JAVDB_APP_API_META`（同文件，顶部） |
| **权威参考** | [github.com/FlanChanXwO/javdb-cli](https://github.com/FlanChanXwO/javdb-cli) (Go, **v0.7.2**) |
| **本地副本** | [G:\MDCX\.references\MDCX-Project-Reference\ref15-javdb-cli](file:///G:/MDCX/.references/MDCX-Project-Reference/ref15-javdb-cli)（git submodule，可 `git submodule update` 批量更新） |
| **关键参考文件** | `internal/javdb/appapi/endpoint/route/{decrypt,selector}.go`（自动选线）+ `sdk/reversesearch.go`（以图搜番）+ `internal/javdb/appapi/endpoint/magnets/magnets.go`（磁力排序）+ `internal/javdb/appapi/`（App API 客户端） |
| **App 镜像** | `https://jdforrepam.com`（自动选线时由 `/api/v1/startup` 解密出动态域名，如 `apidd.*`） |
| **逆向目标** | `JavDB.apk 1.9.28` (`app_version=1.9.28`, `app_version_number=10928`) |
| **签名算法** | `jdsignature = "{ts}.{SUFFIX}.{md5(str(ts)+PREFIX)}"` |
| **已同步功能** | 自动选线（`javdb_autohost.py`）· 以图搜番（`javdb_reverse_search.py`）· 磁力排序/筛选（`rank_magnets`/`filter_magnets`）· 统一投影（`project_movie`/`project_magnet`）· 严格番号解析（`search_movie_exact`）· 演员别名补全（`fetch_actor_aliases`，移植自 mdcx-diy，2026-08-20） |
| **被本项目使用** | `app/scraper/comparator.py` (`JavDBListCrawler` API 模式: 列表/磁力/演员探测) |
| **失效信号** | 持续返回 `ParameterInvalid` / `success:false` / `_request` 全空 |
| **更新步骤** | 见 `JAVDB_APP_API_META["update_steps"]` 列表（6 步） |
| **替代方案** | `javdb_api_client.py`（需登录）→ `JavDBCrawler`（HTML 爬虫，Cookie 兜底） |
| **健康检查** | `create_app_client_from_config()` 后台异步跑一次 `ABP-123` 搜索，失败打 WARNING 日志 |
| **失效日期** | 待定（填入 `JAVDB_APP_API_META["deprecated_after"]`） |
| **BATCH 报告** | [.references/batch_reports/BATCH1_分析报告.md](file:///G:/MDCX/.references/batch_reports/BATCH1_分析报告.md) 第 15 项（javdb-cli）+ 第 12 项（javapi）— P0 高价值参考 |

### ⚠️ 容易混淆的项目

| 仓库 | 协议 | 关系 |
|---|---|---|
| [github.com/FlanChanXwO/javdb-cli](https://github.com/FlanChanXwO/javdb-cli) | **JavDB App 协议** (jdforrepam.com jdsignature) | ✅ **我们的真实参考源** |
| [github.com/javinfo/cli](https://github.com/javinfo/cli) | **javinfo 商业 API** (api.javinfo.dev) | ❌ 不是 App 协议；v0.1.0→v0.1.4 是商业 API 侧功能更新，**与我们无关** |
| [github.com/javinfo/mcp](https://github.com/javinfo/mcp) | javinfo 商业 API 的 MCP 包装 | ❌ 商业 API，不是 App 协议 |

### 衍生项目参考

研究 jdsignature 方案时建议参考的开源项目（不需要引用，但要更新常量时可以对照校验）：

| 仓库 | 语言 | 用途 | 状态 | 备注 |
|---|---|---|---|---|
| [FlanChanXwO/javdb-cli](https://github.com/FlanChanXwO/javdb-cli) | Go | **JavDB App 协议完整实现**（CLI + SDK） | ✅ v0.7.2 | **当前主用参考源** |
| [.references\MDCX-Project-Reference\ref15-javdb-cli](file:///G:/MDCX/.references/MDCX-Project-Reference/ref15-javdb-cli) | Go | 上述仓库的本地参考副本（git submodule） | ✅ v0.7.2 | 含完整 `internal/javdb/appapi/` 客户端 |
| [javinfo/cli](https://github.com/javinfo/cli) | Go | javinfo 商业 API CLI | ✅ v0.1.4 2026-08 | ❌ **与 App 协议无关**，不要误用 |
| [javinfo/mcp](https://github.com/javinfo/mcp) | Node.js | javinfo MCP 包装 | ✅ v0.6.2 2026-08 | ❌ 商业 API |
| [bdvajstudio/javdb](https://github.com/bdvajstudio/javdb) | Repo only | JavDB 官方 iOS App AltStore 源 | ✅ v1.9.35 2026-03-11 | **更新 PREFIX/SUFFIX 的次选源**（拉最新 AltStore IPA 提取） |
| [.references\MDCX-Project-Reference\ref12-javapi](file:///G:/MDCX/.references/MDCX-Project-Reference/ref12-javapi) | Go | 聚合搜索 API，**也走 JavDB App 协议 + jdsignature 认证** | ✅ | 次要参考源；可对照签名常量 |
| [TongWu/JAVDB_AutoSpider](https://github.com/TongWu/JAVDB_AutoSpider) | Python + Rust | 综合爬虫：HTML 翻页 + 代理池 + qBittorrent 集成 | ✅ 2026-08，455 stars | 仅用 HTML，可作降级方案参考；不依赖 App 协议 |
| [SiVeci/JavDB_magnet_Spider](https://github.com/SiVeci/JavDB_magnet_Spider) | Python | curl_cffi 绕 CF + WebUI + SQLite | ✅ 2026-08 | 同样用 HTML + 权重筛选磁力 |
| [Ian-Lin8239/javdb_magnet](https://github.com/Ian-Lin8239/javdb_magnet) | Python | 月榜磁力爬取 | ✅ 2026-02 | 简单工具，仅参考 |
| [akynazh/jvav](https://github.com/akynazh/jvav) | Python | JAV 工具集 | ✅ 2026-08 | 跨数据源（DMM/JavBus/JavDB），可作元数据合并参考 |
| [phoenixthrush/javdb-python](https://github.com/phoenixthrush/javdb-python) | Python | **javdatabase.com 爬虫**（非 javdb.com） | ❌ 2025 停更 | 与 javdb.com 是不同网站，名字冲突 |
| [peiyu7921/javdb-scraper](https://github.com/peiyu7921/javdb-scraper) | Python | DrissionPage 浏览器自动化 | ❌ 2025 停更 | 维护停滞 |

### .references 目录同步规范

`G:\MDCX\.references\MDCX-Project-Reference\` 是**全部真实引用项目**的集中管理目录（git submodule 方式，共 41 个参考仓库）。javdb-cli 对应 `ref15-javdb-cli`。批量更新流程：

1. **更新全部子模块**（在 `MDCX-Project-Reference` 目录下）：
   ```powershell
   git submodule update --remote --merge
   ```
2. 只更新单个参考仓库（如 javdb-cli）：
   ```powershell
   git -C ref15-javdb-cli fetch origin
   git -C ref15-javdb-cli checkout origin/main
   ```
3. 对比本地 `sign.go` 与 `internal/javdb/appapi/` 看是否改了常量
4. 按 `JAVDB_APP_API_META["update_steps"]` 同步到 `javdb_app_client.py`（配套文件：`javdb_autohost.py` 自动选线、`javdb_reverse_search.py` 以图搜番）
5. 跑 `check_command_hint` 确认签名仍有效

> 新增参考仓库时，在 `MDCX-Project-Reference` 下执行 `git submodule add <url> refNN-<name>` 登记，并同步更新 `docs/SOURCES.md` 对应段落。

---

## JavDB HMAC API (官方)

| 字段 | 值 |
|---|---|
| **状态** | ✅ 工作中 |
| **客户端** | `app/services/javdb_api_client.py` |
| **元数据常量** | `JAVDB_API_META`（同文件，顶部） |
| **上游项目** | JavDB 官方 App 协议（闭源） |
| **API 域名** | `https://api.javdb.com` |
| **认证方式** | `jdsignature = HMAC-SHA256(session_token, METHOD+PATH+BODY)` → `JV1.{mid}.{sig}.{suffix}` |
| **Token 端点** | `POST /api/v1/login/sessions` |
| **被本项目使用** | `app/services/mcp_service.py` (`tool_search_movie` 兜底) |
| **失效信号** | 持续 401 / signature 不被服务端接受 |
| **更新步骤** | 闭源协议无源码可逆向；失效时优先走匿名 App API 或 HTML 爬虫 |
| **替代方案** | `javdb_app_client.py`（匿名）→ `JavDBCrawler`（HTML） |
| **失效日期** | 待定（填入 `JAVDB_API_META["deprecated_after"]`） |

---

## JavDB HTML 爬虫 (Cloudflare 受限)

| 字段 | 值 |
|---|---|
| **状态** | ✅ 工作中（最稳定但需 Cookie） |
| **爬虫** | `app/crawlers/javdb.py` (`JavDBCrawler`) |
| **依赖** | 有效 JavDB Cookie（`config.crawler.javdb_cookie`） |
| **域名切换** | `javdb.com` / `javdb36.com` / `javdb.org` (走 `site_switchers.py`) |
| **失效信号** | 持续 Cloudflare 5秒盾 / Turnstile |
| **替代方案** | `javdb_app_client.py`（匿名 App API，推荐） |

---

## JavBus 公开站点

| 字段 | 值 |
|---|---|
| **状态** | ✅ 工作中 |
| **爬虫** | `app/scraper/comparator.py` (`JavBusListCrawler`) |
| **依赖** | 无（无需 Cookie） |
| **有码域名** | `https://www.javbus.com` |
| **无码分区** | `https://www.javbus.com/uncensored/` |
| **失效信号** | HTML 结构变化 → 列表卡片选择器为空 |
| **更新步骤** | 检查 `JavBusListCrawler._parse_list_html` / `_parse_movie_links` 选择器 |

---

## ThePornDB / Aylo API

| 字段 | 值 |
|---|---|
| **状态** | ✅ 工作中 |
| **API** | `https://site-api.project1service.com/v2/...` |
| **客户端** | `app/crawlers/western/aylo_api.py` |
| **失效信号** | API 端点迁移 / 鉴权失败 |

---

## MissAV / 其他在线源

见 `app/services/streaming_aggregator.py`（在线播放聚合）。

---

## 维护约定

1. **新增依赖上游逆向/协议**的模块 → 必须：
   - 在该模块顶部声明 `*_META` 字典（含 `source_repo` / 失效信号 / 更新步骤）
   - 在本文件 `## 表格` 中新增一段
2. **失效日期**确认后填入对应 `*_META["deprecated_after"]`
3. **健康检查**失败时不要静默——必须打 WARNING/ERROR 级别日志
