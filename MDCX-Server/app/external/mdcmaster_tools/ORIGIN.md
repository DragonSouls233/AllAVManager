# mdcmaster_tools — 占位

## 状态

🟡 **计划中** — 阶段 4 执行

## 目标

从 `mdcx-master/mdcx/tools/` 移植 6 个工具到本目录，每个工具一个独立 `.py` 文件。

## 来源

- **上游仓库**：https://github.com/avtopiri/mdcx
- **本地副本**：`O:\MDCX\GitHub-ZIP\P0-Core\mdcx\mdcx-master\mdcx\tools`
- **许可**：MIT（同作者）
- **Copyright**：原 MDCX 作者

## 拟移植清单

| 上游文件 | MDCX 目标文件 | 用途 |
|---|---|---|
| `actress_db.py` | `actress_db.py` | 演员库（与现有 `actor_subscription.py` 互补） |
| `emby_actor_image.py` | `emby_actor_image.py` | Emby 演员头像推送 |
| `emby_actor_info.py` | `emby_actor_info.py` | Emby 演员信息推送 |
| `missing.py` | `missing_filler.py` | 缺字段补刮 |
| `subtitle.py` | `subtitle_helper.py` | 字幕匹配辅助（与现有 `subtitle_matcher.py` 互补） |
| `wiki.py` | `wiki_helper.py` | Wiki 增强查询（与现有 `wikipedia_scraper.py` 互补） |
