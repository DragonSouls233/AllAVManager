# MDCX 项目长期笔记

## 环境拓扑（重要，排查前必读）

| 位置 | 含义 | 可写性 |
|------|------|--------|
| `G:\MDCX\MDCX-Server` | **开发机**本地源码（在这里改代码） | 可读写 |
| `G:\MDCX\MDCX-Desktop` | 前端源码（Vue） | 可读写 |
| `L:\` | 网络映射 = `\\192.168.10.110\MDCX-Server` = **服务器上的 `E:\MDCX-Server`** | **只读**（SMB 权限） |
| `L:\data\database\` | 服务器真实数据库目录（system.db / jav.db / fc2.db / ...） | **只读** |
| `L:\data\logs\app.log` | 服务器日志，**每次启动被清空**，崩溃早期的日志抓不到 | 只读 |

关键结论：
- 服务器进程跑在 **192.168.10.110** 上，开发机 `tasklist` / `taskkill` **看不到也杀不掉**它。
  在开发机杀 python 进程是无效操作（那些是本机自己的进程）。
- 向 `L:` 写文件或改数据库会报 `Permission denied` / `attempt to write a readonly database`，
  **这是 SMB 只读共享导致的，不是进程占用**。部署必须由用户在服务器侧手动复制。
- 可以从 `L:` **读**服务器代码和数据库来做诊断（复制到本地再跑测试是可行的）。

## 架构陷阱：两个都会打开 system.db 的类

- `app/db/database.py` → `class Database` / `get_database()`
  **启动流程 (`main.py` → `init_database`) 实际使用的就是它**，服务代码里 `get_database()` 拿到的也是它。
- `app/db/system_db.py` → `class SystemDatabase`
  另一套封装，**启动时并不会被调用**。

历史事故：`scan_records` 加 `removed_files` 列时，迁移只写进了 `SystemDatabase.init()`，
而启动跑的是 `Database.init()`（只有 `create_all`，不改已存在的旧表），
于是"迁移代码明明存在却完全没生效"，直到 INSERT 时才报
`table scan_records has no column named removed_files`。

**现已修复**：迁移逻辑统一收敛到 `app/db/schema_migrations.py`，
`Database.init()` 与 `SystemDatabase._migrate_schema()` 都调用 `apply_required_columns()`。
以后新增历史列**只改 `SYSTEM_REQUIRED_COLUMNS` 一处**，不要在别处再写 ALTER。

另注意 `ScanRecord` 有两处定义：`db/models.py:565`(旧 Base) 与 `db/system_models.py:120`(SystemBase)，
`scan_control.py` 用的是后者。

## 数据模型约定

- `JavMovie.actor` 是**逗号分隔的演员名文本**，扫描器只写这个字段。
- `MovieActor` 关联表存在但**扫描器从不填充**（恒为空）——
  任何按演员查作品的逻辑都必须用 `movie.actor LIKE '%名字%'`，不能 join 关联表。
- 演员头像真相源：`DATA/avatars/actor_{id}.jpg`（按 actor 主键 id，不是名字）。
  `avatar_url` 字段应存**真实本地绝对路径**，不能存路由字符串
  （详情页会把它当文件路径经 `files/proxy` 加载）。

## 协作约定

- 用户要求：直接修改 G 盘源码并给出部署命令，**不要让用户手动改代码或自己贴代码片段**。
- 服务器部署因共享只读，只能由用户在服务器侧执行复制 + 重启。
- 回复语言：简体中文。
