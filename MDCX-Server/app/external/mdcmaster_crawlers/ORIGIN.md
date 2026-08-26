# mdcmaster_crawlers — 占位

## 状态

🟡 **计划中** — 阶段 3 执行

## 目标

从 `mdcx-master/crawlers/` 移植 30+ 站点爬虫到本目录，每个站点一个独立 `.py` 文件。

## 来源

- **上游仓库**：https://github.com/avtopiri/mdcx
- **本地副本**：`O:\MDCX\GitHub-ZIP\P0-Core\mdcx\mdcx-master\mdcx\crawlers`
- **许可**：MIT（同作者，MDCX 前作）
- **Copyright**：原 MDCX 作者

## 适配原则

1. 每个站点独立文件 `<site>.py`
2. 头部加 `// MDCX MODIFIED FROM mdcx-master` 注释
3. 继承我们的 `app/crawlers/base.py`（异步化）
4. 适配我们的 data model（`app/scraper/context.py` 的 ScrapeContext）
5. API 路由在 `app/api/routes/crawlers.py` 注册

## 首批候选（5 个）

- `javdb_new.py`（mdcx 新版 javdb 接口）
- `fanza.py`（DMM TV/电影模式）
- `iqqtv.py`（iQQTV 站点）
- `javday.py`（JavDay）
- `prestige.py`（Prestige 厂牌）

## 第二批（20+）

airav / arzon / avwiki / cableav / cnmdb / dahlia / faleno / fantastica / freejavbt / getchu / giga / guochan / hdouban / hscangku / jav321 / javmenu / mgstage / njav 等。
