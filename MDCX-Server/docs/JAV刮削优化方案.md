# JAV 有码刮削体系优化方案

> 基于今日日志排查 + 参考项目调研（`.references/MDCX-Project-Reference`）
> 日期：2026-08-20

---

## 一、现状诊断（为什么"很多源没效果"）

### 1.1 刮削链路

```
API 端点 (jav_routes / patch)
  └─ ScraperEngine.scrape_number(number, sources, module="jav")
        └─ CrawlerProvider.get_crawlers_for_module("jav")
              ├─ 按 supported_types 过滤 → [javdb, javbus, dmm, ...]
              └─ 按优先级排序，并发刮削 + 合并
```

**爬虫只按番号/模块选择**；演员对比 URL（`ActorCompareURL`）**完全不参与刮削**，仅对比模块使用。

### 1.2 实测结论（远程日志 L:\data\logs\app.log）

| 源 | 现状 | 日志证据 |
|---|---|---|
| javdb（HTML） | ❌ 全挂 | `javdb.com/search → HTTP 403/429`，3 次重试全失败 |
| javdb（App API） | ✅ 影片本体可刮 | 匿名通道稳定，但**磁力抓取失败降级 HTML 又 403** |
| javbus 演员搜索 | ❌ 404 | `/searchstar/三上悠亞`、`/search/三上悠亞` 均 404 |
| mgstage/prestige/missav 等 15 源 | ❌ 已禁用 | `DISABLED_CRAWLERS`（站点关闭/CF 封禁） |

**核心瓶颈**：名义 20+ 源，实际稳定产出只有 javdb App API 一家；javdb 磁力链路还断了。

### 1.3 关键代码位置

- 禁用列表：[provider.py L30-L46](file:///g:/MDCX/MDCX-Server/app/crawlers/provider.py#L30-L46)
- 刮削选爬虫：[engine.py L143-L159](file:///g:/MDCX/MDCX-Server/app/scraper/engine.py#L143-L159)
- javdb 只走 App API：[javdb.py L52-L55](file:///g:/MDCX/MDCX-Server/app/crawlers/javdb.py#L52-L55)
- 磁力降级：`comparator.py` / `javdb.py` 中 `get_magnets` → HTML 回退

---

## 二、回答用户两个核心问题

### Q1：新增加的演员 URL 作为刮削源有效果吗？

**当前无效。** 原因：
1. `ActorCompareURL`（javbus `/star/`、javdb `/actors/`、avmoo `/tw/actresses/`、javbooks 搜索页）**只被 compare 模块读取**；
2. 刮削引擎选爬虫时**完全不查这张表**；
3. 演员页 URL 本质是"演员档案页"，当前系统也没有"按演员页抓影片列表"的能力。

→ 要让其生效，需新增"**演员页 → 影片列表 → 入库/补刮**"功能（见方案 P0-1）。

### Q2：为什么很多刮削项目没效果？

见 1.2：站点失效 + CF 封禁 + javdb 磁力链路断裂 + 缺替代源。

---

## 三、优化方案（结合参考项目）

### P0-1 演员 URL 接入刮削：新增「按演员抓影片列表」功能 ⭐ 用户核心诉求

**目标**：让探测出的 javdb/javbus/avmoo 演员页 URL 真正生效——一键把某演员的全部影片抓取入库/补刮。

**参考实现**：
- ref15-javdb-cli：`sdk/browse.go` + `endpoint/browse/browse.go`（App API 分类浏览，含演员筛选）、`entity.go`（`/api/v1/actors/{id}` 详情）
- ref01-AVDC：`Getter/javbus.py`（演员页影片列表抓取）、`Getter/javdb.py`

**落地步骤**：
1. `javdb_app_client.py` 新增 `fetch_actor_movies(actor_id)`：
   - 端点：`/api/v1/actors/{id}` 详情（含影片列表分页）
   - 或 `search?q={name}` 已是既有能力（`_search_raw`）
   - 参考 ref15 `entity.go` 的 `actorWithMovies` 结构
2. 新增 `ActorPageScraper` 服务：
   - 输入：演员名 + 4 源 URL（从 `ActorCompareURL` 读）
   - 输出：该演员影片列表（番号/标题/封面/日期）
3. 新增 API：
   - `POST /api/v1/compare/actors/{id}/scrape-movies`（单演员）
   - `POST /api/v1/compare/actors/scrape-movies-all`（批量，复用探测演员列表）
4. 前端 CompareActors.vue 增加"抓取演员影片"按钮

### P0-2 修复 javdb 磁力链路

**目标**：`get_magnets` 不再失败降级 HTML。

**排查方向**：
- [javdb_app_client.py L480-493](file:///g:/MDCX/MDCX-Server/app/services/javdb_app_client.py#L480-L493)：`/api/v1/movies/{id}/magnets` 返回空/失败
- 参考 ref15 `endpoint/movie/movie.go` 的 `GetMagnets` 实现，比对请求参数（可能缺 `limit`/需要 `movie_id` 前缀校验）
- 检查 `movie_id` 是否来自 `/api/v4/movies/{id}`（App id）而非 HTML `/v/`（网页 id）——**id 体系不一致是常见根因**

**验证**：跑 `debug_javdb_magnets.py` 单测一个已知影片的磁力抓取。

### P0-3 增加替代刮削源（复用 ref01-AVDC）

**目标**：缓解单一 javdb 依赖。

**候选源**（ref01-AVDC Getter 已验证可用的经典源）：
- `avsox`（javbus 兄弟站，API 稳定）
- `jav321`（老牌聚合）
- `cableav`（已有本地实现，检查是否被误禁）

**落地**：
1. 逐个实测 avsox / jav321 连通性（代理 + cloudscraper）
2. 移植 ref01 `Getter/avsox.py`、`Getter/jav321.py` 为 `md/` 爬虫
3. 加入 `MODULE_CRAWLER_TYPES["jav"]`，priority 设为 MEDIUM（作为 javdb 失败兜底）

### P1-4 演员资料补全增强（复用 ref22-mdcx-diy）

**目标**：演员生日/身高/罩杯等资料缺失的批量补全。

**参考**：ref22-mdcx-diy `llm.py`（LLM 智能补全）、`manual.py`；现有 `actor_profile_enrich_scanner.py` 已有多源（AVLeague/DMM/JavWiki/Wikipedia/Gfriends）。
**优化点**：
- 把探测到的 javdb `/actors/{id}` 链接接入 `ModuleActorProfileScraper`（javdb 详情含生日等字段）
- 参考 ref22 `llm.py` 增加 LLM 补全兜底（可选，需 API key）

### P1-5 javbus 演员搜索 404 修复

**现状**：`/searchstar/{name}` 404，可能因中文名 URL 编码或 javbus 改版。
**排查**：比对 ref01 `Getter/javbus.py` 的搜索实现（它用 `searchstar` 页 + 正则提取）；确认新路径（`/search/{name}`）与编码方式（`quote` vs `quote_plus`）。

### P2-6 刮削失败自动降级链（提升整体成功率）

**目标**：单源失败不再直接算"刮削失败"。
**落地**：
- 参考 [engine.py L204-L250](file:///g:/MDCX/MDCX-Server/app/scraper/engine.py#L204-L250) 现有 `_scrape_with_crawler`
- 增加"失败源降级提示"日志（记录每源失败原因，便于定位）
- 可选：多源结果按字段置信度合并（已有 `merger.py`）

---

## 四、优先级汇总

| 优先级 | 方案 | 工作量 | 收益 |
|---|---|---|---|
| P0-1 | 演员 URL 接入刮削（按演员抓影片） | 大 | ⭐ 用户核心诉求 |
| P0-2 | 修复 javdb 磁力链路 | 中 | 刮削一步到位 |
| P0-3 | 增加 avsox/jav321 替代源 | 中 | 缓解单源依赖 |
| P1-4 | 演员资料补全增强 | 中 | 资料完整度 |
| P1-5 | javbus 搜索 404 修复 | 小 | 多一个源 |
| P2-6 | 刮削失败降级链 | 小 | 整体成功率 |

---

## 五、建议实施顺序

1. **先做 P0-2**（磁力修复，小改动，立竿见影）——排查 movie_id 体系
2. **再做 P0-1**（演员 URL 接入刮削，核心价值）——先 javdb，再 javbus/avmoo
3. **P0-3** 替代源实测后接入
4. P1-4 / P1-5 / P2-6 按需迭代
