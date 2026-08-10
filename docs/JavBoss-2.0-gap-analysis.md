# JavBoss 2.0 对照 MDCX-Server 差距分析 与 补充实现

> 分析日期：2026-08-10
> 数据来源：JavBoss `main` 源码树（v2.0.0）+ MDCX 部署副本（L: 可读）+ 工作记忆
> 重要：本会话 G: 开发盘挂载中途降级（Read 不可用，Write 可用），核对基于 L: 部署副本。

## 一、关键修正（初版 gap 分析因 G: 降级而误判）

初版因 G: 挂载异常、grep 返回空，误以为 MDCX 缺失「标签分类 / 演员别名」。经核对 L: 部署副本，这两项**已经实现**：

| 能力 | 状态 | 证据 |
|------|------|------|
| 标签分类（Tag.category） | ✅ 已实现 | `models.py`:`Tag.category`；`tags.py` 支持按分类查询/统计/批量打标；`sync-from-movies` 写入 `category="genre"` |
| 演员别名（Actor.alias） | ✅ 已实现 | `models.py`:`Actor.alias`（逗号分隔）；`actor_merge_service.merge_actors()` 合并别名；`search_similar_actors()` 按别名匹配；`actors.py` 有 `fetch-javdb-aliases` 端点 |
| 演员资料字段 | ✅ 已实现 | `Actor` 含 height/bust/waist/hip/cup/birth_date/intro/birthplace/alias/source_url/zodiac/debut_year/social_links |
| 演员资料刮削器 | ✅ 已实现 | `actor_profile_scrapers.py`（DMM/JavWiki/AVOpen/AVWikiDB/Wikidata/Wikipedia/Gfriends）+ `module_actor_profile.py`（uncensored=HEYZO, western=ThePornDB, fc2/pornhub=JavDB） |
| 手动/批量补演员资料 | ✅ 已实现 | `actors.py`:`POST /actors/{id}/scrape-profile`、`POST /actors/scrape-profiles/batch` |

**真正的差距**：JavBoss 2.0 的 `ScanIdolProfiles` —— 一个**后台定时自动补全**缺失演员资料的扫描器。MDCX 只有手动/批量端点，缺少自动化调度。

## 二、本次补充实现（item 3 自动化）

新增「演员资料自动补全扫描器」，对标 JavBoss `ScanIdolProfiles`：

### 新增文件
1. `app/services/actor_profile_enrich_scanner.py`
   - `run_once(module?)`：扫描各模块中资料缺失（height/bust/waist/hip/cup/birth_date 全空）的演员，按模块选源补全。
   - `ensure_scanner_started()`：幂等启动后台 asyncio 循环（默认 24h 一轮，可由 config 覆盖 `actor_profile_enrich_interval_hours` / `actor_profile_enrich_enabled`）。
   - 字段级 merge：仅补空字段，绝不覆盖已有值（同 JavBoss `mergeActressInfo`）；别名追加合并。
   - 礼貌延迟 0.6s/演员，分批（每模块每轮上限 200）续扫。
2. `app/api/routes/actor_enrich.py`
   - `POST /api/v1/actor-enrich/scan?module=jav` 手动触发一轮
   - `GET  /api/v1/actor-enrich/status` 查看状态与最近结果

### 修改文件
3. `app/api/__init__.py`
   - 注册 `actor_enrich` 路由（`prefix=/actor-enrich`）
   - 启动时 best-effort 调用 `ensure_scanner_started()` 自启后台扫描

> 注：`api/__init__.py` 由 L: 部署快照重建 + 上述 2 处新增。若 G: 开发盘有该文件未部署的改动，请先 merge 后再部署。

## 三、JavBoss 2.0 其余功能对照（MDCX 已覆盖，无需补）

| JavBoss 2.0 | MDCX |
|------|------|
| 多源刮削 javbus/javdb/avmoo/avsox/javdatabase/javmodel/javmenu/theporndb | ✅ 已注册主力源 + theporndb(western) |
| 收藏夹+评分+排序 | ✅ favorites |
| 手动补刮/覆盖 | ✅ patch/nfo_scrape |
| 目录自动扫描 | ✅ scan_control/watcher |
| 多用户认证 | ✅ auth/users |
| 视频指纹/去重 | ✅ fingerprint/dedup |
| 内置播放器截图 | ✅ mpv/previews |
| 无码独立模块 | ✅ uncensored 独立 DB |
| 瘦客户端模式 | N/A（MDCX 为 Web 架构） |

## 四、部署步骤（服务器侧，SMB 只读须手动拷贝）

1. 将以下 3 个文件从 G: 开发盘拷贝到服务器 `E:\MDCX-Server\`（L:）：
   - `MDCX-Server/app/services/actor_profile_enrich_scanner.py`
   - `MDCX-Server/app/api/routes/actor_enrich.py`
   - `MDCX-Server/app/api/__init__.py`（覆盖，先确认无未部署改动）
2. 重启 `run.py`（FastAPI 进程）。
3. 验证：
   - `GET /api/v1/actor-enrich/status` → 应返回 running=true、enabled=true、interval_seconds=86400。
   - `POST /api/v1/actor-enrich/scan` → 触发一轮；稍后查 status 看 updated 计数。
4. （可选）在 config 增加 `actor_profile_enrich_interval_hours` / `actor_profile_enrich_enabled` 调间隔/开关。

## 五、待办 / 风险

- ⚠️ G: 开发盘挂载降级：本会话未能对 G: 源码做二次逐行 review，且无法在本地起服务做 Playwright QA。请部署后在服务器侧用真实浏览器验证 `/actor-enrich/status` 与扫描效果。
- 前端暂未新增「资料补全进度」面板（后端 API 已就绪，前端可后续接入 status 接口）。
- 若 G: 恢复后需补：确认 `api/__init__.py` 无被覆盖的未部署路由；对 scanner 做真实运行回归。
