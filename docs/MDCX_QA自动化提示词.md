# MDCX 自动化 QA 测试提示词（交叉验证版）

> 用途：喂给自动化 QA 智能体（每 1 小时运行一轮），定位缺陷、修复开发机代码，并交叉验证服务器是否已同步修复。
> 生成日期：2026-08-14
> 核心原则：**7 个模块各自独立（数据库 / 刮削落盘 / 演员头像 / 刮削源），互不共用、不串库、不串源。**
> 运行频率：**每小时 1 次**（由定时任务驱动，幂等、只读优先、轻量，禁止在测试中触发大规模扫描/整盘刮削）。

---

## 一、双机环境（QA 必须知道）

| 角色 | 位置 | 服务地址 | 说明 |
|------|------|----------|------|
| **开发机**（修复与验证） | `G:\MDCX\` | `http://127.0.0.1:8420` | 代码修复在这里做，**服务端应常驻运行**用于验证。数据目录 `G:\MDCX\MDCX-Server\data\` |
| **服务器**（生产） | `192.168.10.110` | `http://192.168.10.110:8420` | **测试绝不修改服务器**。数据目录 `E:\MDCX-Server\data\` |
| **L: 映射** | 本机 | — | `L:\` = 服务器 `E:\MDCX-Server` **只读**映射。可直查服务器代码与数据，**只读不写** |

- 登录：`admin` + 密码 `ACx36O1i9eHXkGdbaV4uDA`（双机一致，存于各机 `data/.auth_password`；若失效从该文件读取）。
- **交叉验证的本质**：开发机修复的代码不会自动同步到服务器，服务器要靠手动复制。所以每轮 QA 的结论是——
  - 开发机通过 = 修复已落地（但仅限开发机）；
  - 服务器未通过同一测试 = **服务器未同步该修复**，产出「待部署文件清单」。

## 二、测试脚本与报告存放（不放在默认目录）

- 所有 QA 测试脚本、测试数据、运行记录统一放在 **`G:\MDCX\QA-Tests\`**（不要散落进 `MDCX-Server/tests` 或项目根目录）。
- 建议结构：
  - `G:\MDCX\QA-Tests\cross_verify.py` — 交叉验证主脚本（API 直测 + 本地/只读文件检查，Python 标准库，可独立运行）
  - `G:\MDCX\QA-Tests\reports\` — 每轮报告输出（命名含时间戳，如 `report_20260814_16.json/md`）
- 脚本参数建议：`--dev-url http://127.0.0.1:8420 --server-url http://192.168.10.110:8420 --dev-root G:\MDCX\MDCX-Server --server-root L:\ --report reports/report_YYYYMMDD_HH.json`
- 每轮退出码：全部通过 0；任一项 FAIL 返回 1（供定时任务/告警感知）。

## 三、QA 核心红线（发现即算 Bug）

1. **串库**：A 模块数据出现在 B 模块库/列表/详情。
2. **串源**：B 模块影片用了非 B 模块刮削源（如 western 用 JAV 有码爬虫）。
3. **串图**：头像/封面跨模块 id 撞车加载他模块图片。
4. **串文件**：刮削产物写错目录（如 chinese 的 NFO 写到 `data/movies/jav/...`）。
5. **补刮死循环**：空字段分级错误导致无限重扫。

## 四、每轮执行流程（交叉验证）

```
第 1 步 静态基线（只读，仅开发机可做，服务器经 L:\ 只读直查）
第 2 步 动态 API 测试：对 开发机 与 服务器 各跑一遍相同用例
第 3 步 代码同步对比：开发机 G:\MDCX\MDCX-Server\app\ vs 服务器 L:\app\ 逐文件 md5
第 4 步 汇总交叉表：dev PASS / server PASS / 未同步项 → 待部署清单
第 5 步 修复（仅改开发机代码）+ 复测 + 更新报告
```

### 4.1 静态基线（每轮必跑，只读）
1. 确认双机数据目录存在：开发机 `G:\MDCX\MDCX-Server\data\database\`、服务器 `L:\data\database\`。
2. 逐库检查 7 个 `.db`（jav/fc2/uncensored/chinese/pornhub/western/anime）+ `system.db` 存在且可读；列出各库表名，断言与 `app/db/*_models.py` 对应、无他模块前缀表。
3. `system.db` 断言 `favorite_items` 有 `module` 列。
4. 落盘目录健康检查（双机数据目录各做一遍）：
   - `data/movies/{module}/` 存在性；
   - 每个模块统计：code 目录总数 / 含 `movie.nfo` 数 / 含 `poster.jpg` 数 / 含 `extrafanart` 数，输出"刮削完整度"百分比；
   - 检查是否存在**错误落盘**（如 chinese 内容出现在 jav 目录、模块目录名不符合本模块 code 规则）；
   - 演员头像目录 `data/avatars/{module}/` 是否按模块隔离。
5. 静态断言刮削源映射（读开发机源码即可）：
   - `app/crawlers/provider.py` 的 `MODULE_CRAWLER_TYPES` 与前端 `MDCX-Desktop/src/views/jav/Patch.vue` 等页面的 MODULE_TYPES 一致；
   - `app/patcher/detector.py` 的 `_source_to_module` 覆盖所有已注册爬虫的 source，新源未映射则报缺陷。

### 4.2 动态 API 测试（双机各自执行同一套）
6. `GET /api/v1/health` 200；`GET /api/v1/modules` 返回 7 模块。
7. 逐模块 `GET /api/v1/{mod}/movies?page=1&page_size=1`，断言 200 且 total 为非负整数（空库允许 0）。
8. 逐模块封面/头像抽样：取前 ≤5 部影片 id，`GET /api/v1/{mod}/movies/{id}/cover/file`，断言 200 且 Content-Type 为 image/*（无 token 的裸请求也应放行，验证 auth 白名单）。
9. 逐模块演员：`GET /api/v1/{mod}/actors?page=1&page_size=1` 200。
10. 刮削源验证：`GET /api/v1/crawlers` 返回各爬虫及 supported_types；对照期望绑定（见第五节表），发现模块错配即 FAIL。
11. 跨模块收藏：`POST/GET` favorite 接口带 `module` 参数，断言写入 `system.db.favorite_items.module` 正确。

### 4.3 代码同步对比（直接回答"服务器是否已修复"）
12. 全量对比开发机 `G:\MDCX\MDCX-Server\app\` 与服务器 `L:\app\` 下所有 `.py` 文件 md5，输出**差异文件清单**。
13. 重点盯防的"常被修、常忘同步"文件（差异在此清单中要单独高亮）：
    - `app/crawlers/provider.py`（刮削源绑定）
    - `app/patcher/detector.py`（source→module 落盘映射）
    - `app/scraper/engine.py`（补刮模块隔离）
    - `app/scraper/workflow.py`（工作流落库）
    - `app/db/module_db.py`（模块库初始化/迁移）
    - `app/tasks/*_scanner.py`（各模块扫描器）
    - `app/api/routes/{jav,fc2,uncensored,chinese,pornhub,western,anime}_routes.py` + `movies.py`、`modules.py`
14. 输出结论：对每个差异文件，若开发机侧含近期修复逻辑，标记「**服务器未同步 → 待部署**」；若仅格式/注释差异，标记「低优先」。

## 五、刮削源绑定对照表（QA 断言依据）

| 模块 | 允许的爬虫类型（MODULE_CRAWLER_TYPES） | source→module 落盘（detector._source_to_module） |
|------|----------------------------------------|--------------------------------------------------|
| jav | jav, jav_uncensored, fc2 ⚠️ | javdb/javbus/dmm/javlibrary/mgstage/prestige/faleno/…→jav |
| fc2 | fc2 | fc2/fc2club/fc2ppvdb→fc2 |
| uncensored | jav_uncensored | caribbeancom/heyzo/tokyo_hot 等→uncensored（需在映射中确认） |
| chinese | chinese | madou/guochan/91porn 等→chinese |
| western | western | adulttime/theporndb/aylo→western |
| pornhub | pornhub | pornhub→pornhub |
| anime | **缺失（当前不在 MODULE_CRAWLER_TYPES）** | 走独立通道（getchu / anime_scrape_service），不落通用引擎；需确认其落盘为 `data/movies/anime/` |

QA 必须验证的疑点：
- A. `jav` 含 `fc2` 类型是有意设计还是串源（对照前端 Patch.vue 实际勾选）。
- B. `anime` 不在 `MODULE_CRAWLER_TYPES` 中——确认其刮削入口是否正确调用，**这是里番刮削无效果的高危根因候选**。
- C. `get_for_number()` 在番号前缀无匹配时 fallback 到全部 enabled 爬虫（`provider.py`）——无 module 参数路径存在跨源风险，发现即 FAIL。

## 六、专项 1：里番（anime）刮削无效排查（每轮必查，当前已知低效）

1. `GET /api/v1/anime/movies?page=1&page_size=1` 断言 API 通、有数据；无数据先看扫描是否入库（`L:\data\database\anime.db` 与开发机对照 movies 数量）。
2. 检查 `anime.db` 中已入库影片的元数据完整度：title / release_date / cover 填充比例、`scraped_at` 最近时间——**若大量影片 scraped_at 为空或很早，判定"刮削未生效"**。
3. 检查 `anime` 的刮削配置：`app/config/module_models.py` 中 `AnimeModuleConfig.online_enrich`（默认 False，扫描不得联网；手动刮削才走 getchu）。确认刮削触发链路（`/anime/movies/{id}/scrape`、`/anime/scrape-dir`）是否真正调用 getchu 爬虫。
4. 在**开发机**用 1 部样本触发 `POST /api/v1/anime/movies/{id}/scrape`（或 `scrape-dir` 单目录），抓服务日志断言：getchu 源被选中、请求成功、结果落库落盘。**不要在服务器上触发刮削**。
5. 结论区分：功能缺陷（链路断/无爬虫/落库失败） vs 配置缺失（getchu 被墙/需 Cookie/需代理）——配置缺失不作为代码 Bug，但必须在报告中标注并给出配置指引。

## 七、专项 2：各模块扫描 + 刮削保存目录（每轮必查，当前已知有问题）

1. 扫描入库一致性：对每个模块，对比「API total」与「库表 count」（开发机/服务器分别做），不一致即 FAIL 并定位（重点怀疑：扫描计数乐观 +1 但事务回滚，`module_db._migrate_schema` 缺列导致 INSERT 回滚——见 `module_db.py` 注释）。
2. 落盘目录正确性（复用 4.1-4）：抽查每个模块最近刮削的 1 部影片，断言产物齐全（movie.nfo/poster.jpg/fanart.jpg/thumb.jpg/extrafanart）且路径为 `data/movies/{module}/{code}/`；**发现 NFO 或封面仍写到视频原目录或他模块目录 → P0 缺陷**。
3. `output_dir` 优先级回归：DB 中 output_dir 无效时回退 `data/movies/{module}/{code}/`，不得回退到视频父目录（`app/scraper/engine.py`）。
4. 对每模块抽样封面端点返回 200 的比例（开发机/服务器），低于阈值（如 60%）提示"封面缺失率高"，给出样例 code 便于人工核查。

## 八、缺陷修复与部署同步（修复只在开发机）

1. 定位：最小复现 → 抓开发机日志（`data/logs/app.log` / `error.log`）与浏览器 console。
2. 归类：功能缺陷（改代码） vs 配置缺失（Cookie/代理/依赖，给出指引不硬改）。
3. 修复：只改直接相关代码；模块隔离类缺陷优先改 `provider.py` / `detector.py` / `module_db.py` / 路由层，禁止 if 特判掩盖。
4. 复测：重跑对应用例直到 PASS；回归同模块其他用例。
5. 更新「待部署清单」：把本轮新修改的文件追加到 `G:\MDCX\QA-Tests\pending_deploy.txt`（供用户手动复制到服务器，或由部署脚本处理）。
6. **不修改服务器**：服务器任何文件不可写（L: 只读），需要部署时只输出文件清单与建议操作，由用户执行。

## 九、定时运行约束（每小时 1 轮）

- 只读优先：默认用例不得触发全量扫描/整盘刮削/删除操作；需要写数据的验证（如收藏、样本刮削）限定在**开发机**且用可回滚样本。
- 幂等：同一样本重复跑结果一致；报告按时间戳归档不覆盖。
- 超时：单接口 10s；单模块串行；整轮控制在数分钟内。
- 服务器离线/不可达：跳过服务器侧并标注「服务器不可达」，不判 FAIL；开发机不可达时本轮直接 FAIL 并告警（服务没常驻）。
- 变更感知：本轮报告与上轮报告 diff，仅输出新增/消失的缺陷，避免重复刷屏。

## 十、输出格式（每轮）

```
## 环境
- 开发机: http://127.0.0.1:8420 可达/不可达
- 服务器: http://192.168.10.110:8420 可达/不可达
## 交叉对比表（dev / server）
| 测试项 | 模块 | dev | server | 结论 |
|--------|------|-----|--------|------|
| movies API | jav | PASS | PASS | 已同步 |
| cover 抽样 | chinese | PASS | FAIL | 服务器未同步 |
| ... |
## 代码同步
- 差异文件 N 个；未同步修复文件：...（→ 待部署清单）
## 专项结论
- 里番刮削：生效/未生效（根因 + 证据）
- 扫描/落盘目录：正常/异常（证据 + 样例 code）
## 缺陷清单（仅本轮新增）
| # | 严重度 | 模块 | 现象 | 根因(文件:行) | 修复 | 验证 |
## 待部署清单（pending_deploy.txt）
```

所有红线（串库/串源/串图/串文件）必须给出可复现证据（日志行 / 接口响应 / 目录列表 / md5 对比）。
