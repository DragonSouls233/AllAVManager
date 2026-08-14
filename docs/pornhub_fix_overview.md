# PORNHub 模块修复总结

读取 `MDCX-Server` 的 pornhub 模块后，定位并修复了 **6 个实质 bug**（均位于写入/刮削路径，读接口本身正常）。

## 修复清单

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| A | `app/api/routes/pornhub_routes.py` | `scrape_all_actor_profiles_enhanced` 使用模块作用域未定义的 `AVATAR_DIR` / `re` → 运行时 `NameError` 崩溃 | 补 `import re` + 函数内导入 `AVATAR_DIR` |
| B | 同上 | 把演员资料写入**已关闭外层会话的游离对象**，提交到新会话 → 写入静默丢失却报 success | 循环内 `select` 重新取出受管实例 `act` 再写 |
| C | `app/crawlers/pornhub.py` + `app/services/pornhub_comparison.py` | `PornhubComparator` 调用不存在的 `crawler.fetch_actress_videos` → 对比功能静默无结果 | 在 `PornhubCrawler` 实现 `fetch_actress_videos`（返回 dict 列表，兼容 compare 的 `.get()` 消费）；fallback 异常兜底扩为 `(ImportError, AttributeError)` |
| D | `app/api/routes/pornhub_routes.py` | 影片刮削写 `movie.tags`（模型只有 `tag` 列）→ 标签全丢 | 改 `movie.tag`（两处：单部 + 批量） |
| E | 同上 | 非增强版演员资料端点 import 不存在的 `ModuleActorProfileScraper` → 端点 500 | 改用已存在的 `app.scraper.pornhub_actor_scraper.scrape_actor_profile` |
| F | 同上 | `generate_all_pornhub_covers_enhanced` 同样把封面/状态写入游离对象 → 不落库 | 循环内重新取出受管实例再写 |

## 验证

- 三个被改文件均通过 `py_compile`（无语法错误）。
- 静态检查确认：无残留 `movie.tags` 写、无残留 `module_actor_profile` 引用；`fetch_actress_videos` 已定义且被调用。
- 运行期 import 未能在沙箱内完整验证：缺 `lxml` 等第三方依赖（项目依赖不在隔离 Python 中），非代码问题。

## 附带说明

- `app/services/pornhub_parser.py` 是**孤儿文件**（爬虫 `pornhub.py` 自带内联解析，从不 import 它），不影响运行，可后续清理或接入。
- `app/services/pornhub_cache.py` 自包含、无调用方，暂未改动。
- 架构提醒：pornhub 各批量端点务必「同一会话取值 + 写入」，否则游离对象写入会静默丢失（已在本轮 B/F 两处踩中并修复）。

## 部署注意

部署需在服务器侧（`L:` 对开发机只读）复制改动文件并重启后端；详见项目协作约定。
