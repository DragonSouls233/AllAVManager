# MDCX 服务器端一次性部署清单（方案A）

> 适用：把开发机（G:\MDCX）本轮全部改动，一次性同步到服务器（192.168.10.110，`E:\MDCX-Server`）。
> 约束：SMB 对开发机只读，**只能服务器侧复制**——请 RDP 到 192.168.10.110 本机操作。

## 本次部署覆盖的 6 件事
1. **里番扫描零网络（方案A）**：扫描只做本地 NFO/文件名解析 + 入库 + 复制资源，绝不发起任何网络请求。
2. **里番「指定目录刮削」**：只刮你指定的目录（如 `J:\动漫\2026`），绝不波及 1999–2025 历史全量。
3. **JAV 批量刮削修复**：批量刮削（patcher）因 curl_cffi 在 Py3.14 下原生库损坏而整批失败，已修复为自动降级 httpx。
4. **启动期 `WinError 64` 噪音消除**：`run.py` 原 `set_event_loop(SelectorEventLoop())` 写法被 uvicorn 内部 `asyncio.run` 忽略、仍跑在 Proactor loop 上，客户端握手前断开会抛 `OSError [WinError 64] 指定的网络名不再可用`（asyncio `Task exception was never retrieved` / `Accept failed on a socket`）。已改为 `set_event_loop_policy(WindowsSelectorEventLoopPolicy())` 真正生效。
5. **`#/jav/actor-merge` 白屏修复（纯前端路由 bug）**：菜单项 `index="/jav/actor-merge"` 与路由表 `path: 'actor-merge'`（缺 `jav/` 前缀）不一致 → 从菜单点"合并演员"URL 变 `#/jav/actor-merge`、路由表无此路径 → `router-view` 渲染空 → 整页白屏。已把路由 path 改为 `'jav/actor-merge'`（与菜单、Layout 路由标题映射一致）。**必须重新构建前端**（见下方"前端构建状态"），旧 static 是脏目录（含多个 `index-*.js` 残留），直接复制旧 static 仍可能白屏。
6. **FC2 补丁刮削源动态化（前端 bug 修复）**：补丁刮削页「补刮来源」原被**硬编码为 JAV 三个源**（javbus/javdb/javdatabase），在 FC2 模块（`/#/fc2/patch`）依然显示 JAV 源。已改为按当前模块从**爬虫注册表**（`GET /api/v1/crawlers`）按 `supported_types` 动态过滤生成，与「刮削管理 - FC2」完全一致——FC2 模块下显示所有 `supported_types` 含 `fc2` 的源（fc2/fc2club/fc2ppvdb/fc2_enhanced/fc2fanclub/fc2video/fc2search/fc2hub/javdb/njav）。后端 `ScraperEngine.scrape_number` 本就支持 `sources` 过滤，FC2 番号会正确路由到 FC2 刮削路径，无需后端改动。

## 需要覆盖的文件（开发机 G: → 服务器 E:）

| 源（开发机） | 目标（服务器） | 用途 |
|---|---|---|
| `G:\MDCX\MDCX-Server\app\config\module_models.py` | `E:\MDCX-Server\app\config\module_models.py` | `online_enrich` 默认 `False`（方案A 核心） |
| `G:\MDCX\MDCX-Server\app\tasks\anime_scanner.py` | `E:\MDCX-Server\app\tasks\anime_scanner.py` | 扫描纯本地化，删除自刮削网络调用 |
| `G:\MDCX\MDCX-Server\app\services\anime_scrape_service.py` | `E:\MDCX-Server\app\services\anime_scrape_service.py` | **新建**：目录刮削后台服务（限并发 5、单部失败不中断、带进度 job） |
| `G:\MDCX\MDCX-Server\app\api\routes\anime_routes.py` | `E:\MDCX-Server\app\api\routes\anime_routes.py` | 新增 `POST /api/v1/anime/scrape-dir` + 状态查询端点 |
| `G:\MDCX\MDCX-Server\app\utils\http_client.py` | `E:\MDCX-Server\app\utils\http_client.py` | curl_cffi 降级修复（批量刮削报错根因） |
| `G:\MDCX\MDCX-Server\app\services\scan_control.py` | `E:\MDCX-Server\app\services\scan_control.py` | anime 扫描超时 `600→1800s`（11 万+ 文件目录不超时） |
| `G:\MDCX\MDCX-Server\run.py` | `E:\MDCX-Server\run.py` | **事件循环策略**改为 `WindowsSelectorEventLoopPolicy`（消除启动期 `WinError 64` 噪音） |
| `G:\MDCX\MDCX-Server\data\config\config.server.yaml` | `E:\MDCX-Server\data\config\config.yaml`（**覆盖**） | 带注释完整配置，`anime.online_enrich: false` |
| `G:\MDCX\MDCX-Server\static\`（整目录） | `E:\MDCX-Server\static\`（整目录覆盖） | **重建后的干净前端**：含「指定目录刮削」UI + 路由修复（`#/jav/actor-merge` 白屏已修）+ **FC2 补丁刮削源动态化** |
| `G:\MDCX\MDCX-Desktop\src\router\index.js` | （已构建进 static，溯源用） | 路由 `actor-merge` → `jav/actor-merge`（白屏修复） |

> 前端源码（仅供溯源，已构建进 static，**无需单独部署**）：
> `MDCX-Desktop/src/api/anime.js`、`MDCX-Desktop/src/views/AnimeMovies.vue`、
> `MDCX-Desktop/src/views/AnimeSeries.vue`（播放整系列 + 年份时间线）、
> `MDCX-Desktop/src/views/Patch.vue`（补刮来源按模块动态化）、
> `MDCX-Desktop/src/api/index.js`（`getCrawlers` 已在 `/api` 导出）

## 前端构建状态
- **最新构建（含白屏修复 + AnimeSeries + Patch FC2 源动态化）**：2026-08-10 08:15，`exit 0`，耗时 11.10s（managed Node 22.22.2）。
- 本次构建前**先整体重命名旧 `static` 为 `static_bak_20260810_081457`**，再 `vite build` —— 产出的 `static` 是**单一批次、干净无残留**（仅 1 个主 chunk `index-BRu0qoNQ.js`，不再有脏目录的多个 `index-*.js`）。
- 该构建已包含截至 08-10 的全部前端改动：
  - `#/jav/actor-merge` 白屏修复（路由 path 加 `jav/` 前缀）；
  - 里番系列页「播放整系列」+「年份时间线」（AnimeSeries.vue 重写）；
  - **FC2 补丁刮削源动态化**（Patch.vue：按模块从爬虫注册表动态生成「补刮来源」）。
- 旧 static 备份：`G:\MDCX\MDCX-Server\static_bak_20260810_081457`（仅开发机，供回滚）。

> ⚠️ **脏目录教训**：之前多次 `vite build` 用了 `emptyOutDir:false`，开发机 `static` 累积了多个 `index-*.js`。主 chunk 引用的子 chunk 虽都在，但**直接复制这种脏目录到服务器是隐患**。每次重建都先 `mv static static_bak_<ts>` 再 build，复制整目录即可。若日后自行重新构建，务必遵守此流程。

## 服务器部署步骤（192.168.10.110 本机）
0. **（关键）停 supervisor + 清日志锁**：杀掉独占 `E:\MDCX-Server\data\logs\app.log` / `error.log` 的进程（否则重启会因日志 handler 打开失败而退出——这是环境死锁，非代码问题）。
1. 复制上表 7 个后端 `.py` 到对应位置（含 `run.py`）。
2. 把 `config.server.yaml` **内容覆盖**到 `E:\MDCX-Server\data\config\config.yaml`（注意是覆盖，不是追加）。
3. 整盘覆盖 `static`：先把**服务器**旧 `static` 整个删除或改名（务必清干净，不能只覆盖 `index.html` —— 否则残留的旧 `index-*.js` / 旧 chunk 与新的主 chunk 不匹配仍可能白屏/异常），再把 `G:\...\static` 整个复制过去。
4. 重启后端：`C:\Python314\python.exe run.py --no-tray --no-browser`（或你惯用的启动方式）。
5. 前端 **Ctrl+Shift+R 硬刷新**，清掉旧 `index.html` 缓存。

## 验证
- 后端：启动日志应打印 `scrape_anime_dir: /api/v1/anime/scrape-dir (POST)` 与 `scrape_anime_dir_status: /api/v1/anime/scrape-dir/{job_id}/status (GET)`。
- 里番页：点「指定目录刮削」→ 填 `J:\动漫\2026`、勾「仅刮缺失」→ 开始，进度实时轮询，只补 2026 新番。
- JAV 批量刮削：选「待刮削」→ 批量刮削，`error.log` 不再出现 `initializer for ctype 'void *' must be a cdata pointer`。
- **FC2 补丁刮削源**：进入 `/#/fc2/patch` → 「执行补刮」步骤的「补刮来源」应显示 FC2 专用源（fc2/fc2club/fc2ppvdb/fc2_enhanced/fc2fanclub/fc2video/fc2search/fc2hub/javdb/njav），**不再显示 JAV 的 javbus/javdb/javdatabase**；提示文案为「FC2 专用刮削源（与『刮削管理 - FC2』完全一致）」。

## 可选：一键复制脚本
- `G:\MDCX\deploy_to_server.ps1`（在服务器本机以管理员运行，先把 `$SRC` 改成服务器侧可访问的开发机源码根路径）。脚本只做文件复制 + 提示重启，不杀进程，避免误伤。

## 注意事项
- 即便不部署 `config.server.yaml`，因 `online_enrich` 代码默认已 `False`，运行时也默认不在线补充；部署注释版是为了显式可读、防止旧配置 `true` 干扰。
- 临时强制 httpx（不部署 `http_client.py` 也可）：启动前 `set MDCX_DISABLE_CURL_CFFI=1`。
- 扫描零网络已生效：报错里的 `补刮失败: <番号>: initializer for ctype` 这条是**批量刮削（patcher）**路径，与扫描无关；扫描本身不会再发 getchu 请求。
- `run.py` 改动后：`error.log` 不再出现 `OSError [WinError 64] 指定的网络名不再可用` / `Accept failed on a socket`（该错误是客户端连接中途断开的正常现象，不影响服务运行，仅属噪音；修复后彻底消失）。
- 里番全量扫描若仍报 `手动扫描 [anime] 超时`：说明整套库（如 `Y:\动漫`，可能是映射/网络盘）扫一遍 >30 分钟，属环境性耗时，非配置问题——`scan_control.py` 的 1800s 已是最新且已部署；如需彻底不丢进度，后续可改"增量提交 + 去掉硬超时"，按需再说。
