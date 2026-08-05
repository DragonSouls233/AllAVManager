# MDCX 新数据库架构设计

> 版本: v2.0 | 日期: 2026-08-05
> 目标: 彻底废除 scraper.db，6 模块完全独立 + 系统库管理全局数据

---

## 1. 架构概述

```
┌─────────────────────────────────────────────────────────────────────┐
│                         system.db (系统库)                          │
│  users │ user_sessions │ settings │ cache │ tasks │ workflows      │
│  migrations │ scan_records │ favorite_groups │ favorite_items      │
│  asset_change_logs                                                  │
└─────────────────────────────────────────────────────────────────────┘
          ▲                                 ▲
          │  user_id (int, 无FK)            │  module + entity_id
          │                                 │
  ┌───────┴────────┬────────────┬───────────┴──────────┬──────────────┐
  │   jav.db       │  fc2.db    │  uncensored.db      │  chinese.db  │
  │ JAV有码        │  FC2       │  JAV无码             │  国产         │
  │                │            │                     │              │
  │ movies ★       │ movies ★   │ movies ★            │ movies ★     │
  │ actors ★       │ actors ★   │ actors ★            │ actors ★     │
  │ movie_actors   │ movie_actors│ movie_actors       │ movie_actors │
  │ studios        │ studios    │ studios             │ studios      │
  │ series ── studios│ series   │ series              │              │
  │ tags           │ tags       │ tags                │ tags         │
  │ movie_tags     │ movie_tags │ movie_tags          │ movie_tags   │
  │ actor_tags     │ actor_tags │ actor_tags          │ actor_tags   │
  │ tier_config    │ tier_config│ tier_config         │ tier_config  │
  │ actor_tiers    │ actor_tiers│ actor_tiers         │ actor_tiers  │
  │ actor_compare  │ actor_compare│ actor_compare     │              │
  │ subscriptions  │ subscriptions│ subscriptions     │              │
  │ play_history   │ play_history│ play_history       │ play_history │
  │ patch_records  │ patch_records│ patch_records     │ patch_records│
  │ import_records │ import_records│ import_records   │ import_records│
  │ file_organize  │ file_organize│ file_organize     │ file_organize│
  │ movie_relations│ movie_relations│ movie_relations │ movie_relations│
  │ recommendations│ recommendations│ recommendations │ recommendations│
  └────────────────┴────────────┴───────────────────┴──────────────┘
           ▲                                 ▲
  ┌────────┴──────────────┐   ┌──────────────┴──────────┐
  │   pornhub.db          │   │   western.db            │
  │   PORNHUB             │   │   欧美                   │
  │                       │   │                         │
  │ movies ★              │   │ movies ★                │
  │ actors ★              │   │ actors ★                │
  │ movie_actors          │   │ movie_actors            │
  │ studios               │   │ studios                 │
  │ tags                  │   │ series ── studios       │
  │ movie_tags            │   │ tags                    │
  │ actor_tags            │   │ movie_tags              │
  │ ... (同上)            │   │ ... (同上)              │
  └───────────────────────┘   └─────────────────────────┘
```

## 2. 核心设计原则

| 原则 | 说明 |
|------|------|
| **1 DB = 1 Module** | 每个模块拥有独立 .db 文件，不共享数据 |
| **完全规范化** | 所有多对多关系使用关联表，不再用逗号分隔字符串 |
| **外键 + CASCADE** | 所有关联表使用 FK + ON DELETE CASCADE |
| **统一定义** | 6 个模块共享相同的核心表结构，仅模块特有字段不同 |
| **系统库独立** | 用户、认证、设置、收藏夹等跨模块数据放 system.db |
| **无跨库外键** | system.db 与模块DB之间仅通过 int ID 关联，无 FK 约束 |

## 3. 废除清单

从 `scraper.db` 删除：
- ~~movies, actors, movie_actors~~ → 各模块自有
- ~~studios, series~~ → 各模块自有
- ~~tags, movie_tags, actor_tags~~ → 各模块自有
- ~~tier_config, actor_tiers~~ → 各模块自有
- ~~actor_compare_urls~~ → 各模块自有
- ~~actor_subscriptions, series_subscriptions~~ → 各模块自有
- ~~play_history~~ → 各模块自有
- ~~patch_records, import_records~~ → 各模块自有
- ~~file_organize_jobs, auto_organize_rules~~ → 各模块自有
- ~~movie_relations, user_recommendations~~ → 各模块自有

保留并移入 `system.db`：
- users, user_sessions
- settings, cache
- tasks, workflows
- migrations, scan_records
- favorite_groups, favorite_items
- asset_change_logs

## 4. 模块特有字段

| 模块 | Movie 特有 | Actor 特有 |
|------|-----------|-----------|
| JAV | is_chinese, is_uncensored, is_mosaic, label, is_leak, tmdb_id | — |
| 无码 | source_platform | — |
| FC2 | is_mosaic, seller_id | — |
| 国产 | folder_name, folder_based_actors, extracted_actor | studio |
| 欧美 | site, network | gender, birthdate, country, ethnicity, measurements, weight, twitter, instagram |
| Pornhub | source_id, source_views, source_score, source_downloads, uploader, categories | nationality |

## 5. 每个模块数据库的 ER 图

以 JAV 模块为例，其余 5 个模块结构完全一致（仅模块特有字段不同）：

```
┌─────────────────────────────────────────────────────────────────────┐
│  jav.db（每个模块完全独立，使用相同的规范化表结构）                    │
│                                                                     │
│  movies ──1:N── movie_actors ──N:1── actors                         │
│    │                                    │                           │
│    │ FK studio_id                       │ FK actor_id               │
│    ▼                                    ▼                           │
│  studios ◄──────── series              actor_tiers (1:1)            │
│              FK studio_id               actor_tags (1:N)             │
│                                        actor_compare_urls (1:N)     │
│  movies ──1:N── movie_tags ──N:1── tags                             │
│                                                                     │
│  movies ──1:N── play_history                                       │
│  movies ──1:N── patch_records                                      │
│  movies ──1:N── import_records                                     │
│  movies ──1:N── movie_relations ──N:1── movies (自引用)            │
│  movies ──1:N── file_organize_jobs                                 │
│                                                                     │
│  actors ──1:N── actor_subscriptions (user_id→system.db)            │
│  series ──1:N── series_subscriptions (user_id→system.db)           │
│                                                                     │
│  tier_config (独立配置表)                                           │
│  auto_organize_rules (独立规则表)                                   │
│  user_recommendations (user_id→system.db, FK movies)               │
└─────────────────────────────────────────────────────────────────────┘
```

## 6. 文件清单

| 文件 | 说明 |
|------|------|
| `app/db/system_models.py` | system.db ORM 模型（新建） |
| `app/db/system_db.py` | system.db 管理器（新建） |
| `app/db/_module_mixins.py` | 模块共享 Mixin 基类（新建） |
| `app/db/jav_models.py` | JAV 有码模块模型（重写） |
| `app/db/fc2_models.py` | FC2 模块模型（重写） |
| `app/db/uncensored_models.py` | JAV 无码模块模型（重写） |
| `app/db/chinese_models.py` | 国产模块模型（重写） |
| `app/db/western_models.py` | 欧美模块模型（重写） |
| `app/db/pornhub_models.py` | Pornhub 模块模型（重写） |
| `app/db/module_db.py` | 模块数据库管理器（重写，支持 per-module Base） |
| `app/utils/module_helper.py` | 跨模块查询工具（更新） |
| `scripts/init_new_db.py` | 数据库重建脚本（新建） |

## 7. 与旧架构的对比

| | 旧架构 | 新架构 |
|---|---|---|
| 中心库 scraper.db | ✅ 存在且大量使用 | ❌ 彻底废除 |
| 模块表名 | jav_movies / jav_actors（各模块不同） | movies / actors（统一表名，独立DB） |
| 演员关联 | 逗号分隔字符串（LIKE 模糊匹配） | movie_actors 多对多表（FK + CASCADE） |
| 外键 | 仅中心库有，模块库无 | 所有模块库完整 FK |
| 级联删除 | 无 | 全部 ON DELETE CASCADE |
| 跨模块数据 | favorites 在 scraper.db | favorites 在 system.db（module 字段区分来源） |
| 数据库数量 | 1 中心库 + 6 模块库 = 7 | 1 系统库 + 6 模块库 = 7 |

## 8. 表统计

| 数据库 | 表数量 | 表列表 |
|--------|--------|--------|
| system.db | 12 | users, user_sessions, settings, cache, tasks, workflows, migrations, scan_records, favorite_groups, favorite_items, asset_change_logs |
| 每个模块DB | 20 | movies, actors, movie_actors, studios, series, tags, movie_tags, actor_tags, tier_config, actor_tiers, actor_compare_urls, actor_subscriptions, series_subscriptions, play_history, import_records, patch_records, file_organize_jobs, auto_organize_rules, movie_relations, user_recommendations |

> 总计：12 + 6 × 20 = **132 张表**（全部规范化，完整 FK 约束）
