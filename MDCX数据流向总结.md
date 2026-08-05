# MDCX 数据流向完整总结

> 文档版本: 2026-08-05
> 适用代码: `MDCX-Server` (已修复版)

---

## 1. 数据库结构

### 1.1 模块数据库（JAV 主库）
**文件**: `E:\MDCX-Server\data\database\jav.db`（开发机 `L:\data\database\jav.db`）

| 表 | 关键字段 | 特点 |
|----|---------|------|
| `jav_movies` | `id, code, title, cover_url, poster_url, actor(逗号分隔), studio, file_path` | **无外键**，演员名存为字符串 |
| `jav_actors` | `id, name, avatar_url, movie_count` | 演员基础信息 |

**数据量**: 8195 影片, 561 演员

### 1.2 中心数据库（旧库）
**文件**: `E:\MDCX-Server\data\database\scraper.db`（开发机 `L:\data\database\scraper.db`）

| 表 | 关键字段 | 特点 |
|----|---------|------|
| `movies` | `id, code, title, cover_url, output_dir, fingerprint, studio_id(FK)` | 有外键关联 |
| `actors` | `id, name, avatar_url, birth_date, height, cup...` | 完整演员信息 |
| `movie_actors` | `movie_id, actor_id` | 多对多关联 |
| `studios` | `id, name` | 厂商表 |
| `favorite_items` | `id, group_id, entity_id, module(新加)` | 收藏夹 |

**数据量**: 11 影片, 6 演员（基本废弃）

> **结论**: JAV 所有数据在 `jav.db`，**中心数据库已基本废弃**。当前代码已修改为优先查模块数据库。

---

## 2. 封面读取流程

**端点**: `GET /api/v1/jav/movies/{id}/cover/file`

```
┌─────────────────────────────────────────────────────────┐
│  第1步: 规范目录查找                                      │
│  L:\data\movies\jav\{code}\poster.jpg                    │
│  L:\data\movies\jav\{code}\fanart.jpg                    │
│  L:\data\movies\jav\{code}\thumb.jpg                     │
│  找到 → 直接返回 ✅                                       │
├─────────────────────────────────────────────────────────┤
│  第2步: DB中 cover_url 本地路径                            │
│  如果 cover_url 不是 http/https 开头 → 当作本地文件路径    │
├─────────────────────────────────────────────────────────┤
│  第2.5步: DB中 cover_url 远程URL → 下载到规范目录          │
│  ✅ 本次修复新增                                          │
│  当 cover_url 是远程 URL（如 javbus CDN）                 │
│  → 自动下载到 L:\data\movies\jav\{code}\poster.jpg       │
│  → 带 Referer 防盗链头                                    │
│  → 同时尝试下载 fanart.jpg                                │
├─────────────────────────────────────────────────────────┤
│  第3步: 视频同目录查找                                     │
│  查视频文件 parent 目录下的 poster.jpg/cover.jpg 等        │
├─────────────────────────────────────────────────────────┤
│  兜底: 返回 SVG 灰色占位图 "暂无封面"                      │
└─────────────────────────────────────────────────────────┘
```

>


- get_movie_cover_path("jav", code) →
  `{data_dir}/movies/jav/{code}/poster.jpg`
- data_dir 在服务器上 = `E:\MDCX-Server\data`
- 所以完整路径 = `E:\MDCX-Server\data\movies\jav\{code}\poster.jpg`
- 在开发机通过共享访问 = `L:\data\movies\jav\{code}\poster.jpg`
- 开发机上 L 盘 是 E 盘的共享映射，两者是同一物理文件

---

## 3. 补丁刮削流程

### 3.1 output_dir 确定（修复后）

```
┌──────────────────────────────────────────────────────┐
│  优先级1: DB 中 output_dir 字段值                      │
│  有值且有效 → 直接使用                                 │
├──────────────────────────────────────────────────────┤
│  优先级2: 规范目录（本次修复新增）                       │
│  {data_dir}/movies/{module}/{code}/                   │
│  示例: L:\data\movies\jav\AIAV-036\                   │
│  ✅ 现在 NFO/封面/预览图全部写入这里                    │
├──────────────────────────────────────────────────────┤
│  优先级3: 视频文件父目录（旧行为，仅做最终兜底）          │
│  示例: H:\AI\[2025-11-20][AIAV-036]...\               │
│  ⚠️ 已不是默认回退，只在以上都不可用时才用               │
└──────────────────────────────────────────────────────┘
```

### 3.2 source → module 映射

`detector.py` 中的 `_source_to_module` 函数：

| source 值 | 映射到模块目录 |
|-----------|--------------|
| `javdb, javbus, dmm, javlibrary, ...` | `jav` |
| `folder, freejavbt, javdatabase, xcity` | `jav`（本次修复） |
| `madou, guochan` | `chinese` |
| `fc2, fc2club, fc2ppvdb` | `fc2` |
| `pornhub` | `pornhub` |
| `western, adulttime, theporndb, aylo` | `western` |
| 其他未知 source | 直接作目录名（应极少出现了） |

### 3.3 数据库写入（修复后）

- **`_update_database` 新增 `module` 参数**
- `module=None` → 写中心数据库（旧行为，保留兼容）
- `module="jav"` → 写 `jav_movies` 表（本次修复）
- 写模块数据库时用**原生 SQL**（字段映射表）

### 3.4 补丁刮削写入的内容

| 文件 | 写入位置 | 说明 |
|------|---------|------|
| `movie.nfo` | `{output_dir}/movie.nfo` | Emby/Kodi 元数据 |
| `poster.jpg` | `{output_dir}/poster.jpg` | 封面（大图） |
| `fanart.jpg` | `{output_dir}/fanart.jpg` | 背景图 |
| `thumb.jpg` | `{output_dir}/thumb.jpg` | 缩略图 |
| `extrafanart/*.jpg` | `{output_dir}/extrafanart/` | 预览图/截图 |

> **修复后位置**: `L:\data\movies\jav\PYU-424\poster.jpg` ✅
> **修复前位置**: `H:\...\PYU-424\poster.jpg` ❌

---

## 4. 演员头像流程

### 4.1 Gfriends 批量导入

```
┌──────────────────────────────────────────────────────┐
│  1. 预览 (GET /api/v1/gfriends/preview)               │
│     → 扫描所有模块数据库 (jav_actors/fc2_actors/...) │
│     → 找到 avatar_url 为空的演员                      │
│     → 与 Gfriends 本地头像库文件名做匹配              │
│     → 返回 matched 列表                               │
├──────────────────────────────────────────────────────┤
│  2. 导入 (POST /api/v1/gfriends/import)              │
│     → 复制头像文件到 data/avatars/actor_{id}.jpg     │
│     → 更新模块数据库:                                 │
│       UPDATE jav_actors SET avatar_url = ? WHERE id=? │
│     → 更新中心数据库:                                 │
│       UPDATE actors SET avatar_url = ? WHERE id=?     │
│     → avatar_url 值: "/api/v1/actors/{id}/avatar/file"│
├──────────────────────────────────────────────────────┤
│  3. 头像展示 (GET /api/v1/jav/actors/{id}/avatar/file)│
│     → 查 jav_actors 表                                │
│     → avatar_url 指向 API 路由 → 返回头像文件         │
│     → 无头像则 404                                    │
└──────────────────────────────────────────────────────┘
```

### 4.2 本地头像库探测

```
L:\gfriends-master\Content\   ← 实际位置
  ├── あ行\
  ├── か行\
  ├── ...
  └── わ行\

服务器配置: config.yaml → gfriends.local_library_path
当前值: E:\MDCX-Server\gfriends-master（服务器上不存在）
自动探测兜底: data_dir.parent / "gfriends-master"
            = E:\MDCX-Server\gfriends-master
```

> ⚠️ 头像库实际在 `L:\gfriends-master` 根，服务器路径需配置为 `E:\MDCX-Server\gfriends-master`

---

## 5. 演员详情页

### 5.1 演员作品列表

**端点**: `GET /api/v1/jav/actors/{id}/movies?page=1&page_size=24`

| 项目 | 值 |
|------|-----|
| 查询数据库 | `jav.db` |
| 查询表 | `jav_movies` |
| 匹配方式 | `actor LIKE '%演员名%'` （文本模糊匹配） |
| 排序 | `release_date DESC NULLS LAST` |
| 返回字段 | id, code, title, cover_url, release_date, duration, studio |

### 5.2 演员时间线

**端点**: `GET /api/v1/jav/actors/{id}/timeline`
- 同表文本匹配
- 按年分组统计影片数

### 5.3 演员头像文件

**端点**: `GET /api/v1/jav/actors/{id}/avatar/file`
- 查 `jav_actors` 表（非中心库 `Actor` 表）
- 优先返回本地文件 → 远程 URL 提示通过 Gfriends 导入

---

## 6. 收藏夹（修复后）

| 端点 | 数据库 | 说明 |
|------|--------|------|
| `POST /groups/{id}/items?module=jav` | 中心库 `favorite_items` | module 字段标识模块 |
| `GET /check?entity_id=X&module=jav` | 中心库 `favorite_items` | 跨模块查询收藏状态 |
| `DELETE /groups/{id}/items/{eid}?module=jav` | 中心库 `favorite_items` | 跨模块删除 |

> `favorite_items` 表新增 `module` 列（默认 `""`=中心库），需要先跑迁移脚本。

---

## 7. 当前已知问题

| 问题 | 状态 | 修复方式 |
|------|------|---------|
| 封面远程 URL 不下载 | ✅ 已修复 | jav_routes.py 第2.5步 |
| 播放 401 未授权 | ✅ 已修复 | auth_middleware.py 放行 play/file |
| Gfriends 查不到演员 | ✅ 已修复 | gfriends.py 查模块数据库 |
| 补丁刮削写到视频目录 | ✅ 已修复 | engine.py output_dir 回退规范目录 |
| 数据库更新写入中心库 | ✅ 已修复 | strategy.py 支持 module 参数 |
| source 映射生成多余目录 | ✅ 已修复 | detector.py 回退到 jav |
| 演员详情 500 maker 字段 | ✅ 已修复 | jav_routes.py getattr 安全取值 |
| favorites.module 列不存在 | ⏳ 待迁移 | 需在服务器跑 migrate_db.py |
| 爬虫 403 | ⏳ 待配 | 需配 CookieCloud 或手动填 Cookie |

---

## 8. 部署清单

每次修改后复制到服务器的核心文件：

```powershell
# ===== 路由 =====
jav_routes.py          # JAV 封面/详情/演员作品
gfriends.py            # Gfriends 预览/导入
favorites.py           # 收藏夹跨模块
actors.py              # 演员列表+module
fingerprint.py         # 指纹跨模块
emby_compat.py         # Emby 兼容跨模块

# ===== 服务 =====
gfriends_importer.py   # 头像导入
fingerprint.py         # 指纹计算
metrics.py             # 跨模块统计

# ===== 补丁刮削 =====
engine.py              # output_dir 回退修复
strategy.py            # 数据库更新 module 支持
detector.py            # source 映射

# ===== 其他 =====
auth_middleware.py     # 播放/头像放行
module_helper.py       # 公用工具
workflow.py            # 刮削工作流写模块库
models.py              # FavoriteItem module 字段
```
