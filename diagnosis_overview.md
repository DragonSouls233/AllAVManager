# MDCX 后端"空闲假死 / 前端打不开"诊断与修复

## 现象
- 后端进程存活，但前端空闲（不操作）一段时间后进入"假死"，最终连前端页面都打不开（浏览器无法加载 `index.html`）。
- `L:\data\logs\app.log` 在 `2026-08-12 09:47:35` 后**再无任何输出**（沉默数小时）。
- 同日志 `09:47:11` 出现 APScheduler 警告：`_auto_organize_job` 被 **missed by 0:01:08**（事件循环被阻塞超过 1 分钟）。

## 根因
服务端是 **单进程、单事件循环**（`run.py` 默认 `workers=1` + Windows `SelectorEventLoop`）。
任何在事件循环里直接执行的**同步阻塞文件 I/O** 都会把整个 loop 卡死 —— 包括给前端提供静态资源、处理 API 请求。
卡死期间浏览器连 `index.html` 都取不到，于是"前端打不开"。

确认有三处同步阻塞调用（均在 async 函数内，跑在事件循环上）：
1. **`app/services/file_organize.py::auto_organize_watched()`**（每小时定时触发的"自动整理已观看视频"）
   调用 `safe_move_file()` 同步执行：读源文件 SHA256 → `shutil.copy2` 整文件复制 → 读目标 SHA256 → `os.remove`。
   多 GB 视频在网络盘(SMB)上复制/校验时长时间阻塞 loop = **空闲假死主因**（空闲时正好轮到定时任务跑）。
2. **`FileOrganizeService._execute_organize / _do_organize`**：`shutil.copy2 / shutil.move` 同步复制（用户手动整理大文件时卡 loop）。
3. **`app/tasks/base_scanner.py::copy_video_assets_to_data_dir()`** 内 `shutil.copy2` 同步复制（扫描期拖慢 loop，正是 `missed by 1:08` 警告的来源）。

## 已做的修复（改在 G 盘源码，待部署）
把上述阻塞调用全部改为 `await asyncio.to_thread(...)`，丢到线程池执行，事件循环不再被文件 I/O 阻塞：

- `G:\MDCX\MDCX-Server\app\services\file_organize.py`
  - 增加 `import asyncio`
  - `auto_organize_watched` 中 move/copy/hardlink-fallback 的 `safe_move_file(...)` → `await asyncio.to_thread(safe_move_file, ...)`
  - `execute_organize` 中 `self._do_organize(...)` → `await asyncio.to_thread(self._do_organize, ...)`
- `G:\MDCX\MDCX-Server\app\tasks\base_scanner.py`
  - 增加 `import asyncio`
  - `shutil.copy2(src, dst)` → `await asyncio.to_thread(shutil.copy2, src, dst)`

两文件已通过 `py_compile` 语法校验。

## 部署步骤（SMB 只读，须服务器侧手拷 + 重启）
1. 将以下两文件从开发机拷贝到服务器对应位置：
   - `G:\MDCX\MDCX-Server\app\services\file_organize.py` → `E:\MDCX-Server\app\services\file_organize.py`
   - `G:\MDCX\MDCX-Server\app\tasks\base_scanner.py` → `E:\MDCX-Server\app\tasks\base_scanner.py`
2. **先结束当前已挂死的 `run.py` 进程**（托盘图标退出 / 任务管理器结束 python 进程）。
3. 重新启动 `run.py`。

## 验证
- 重启后观察 `L:\data\logs\app.log`：空闲时段前端轮询（`/api/v1/stats/health` 等）应持续有 200 日志，不再整段沉默。
- 不再出现 `apscheduler ... missed by` 警告。
- 若已配置"自动整理已观看视频"规则，下次整点跑该任务时前端应依旧可正常打开/操作。

## 附带发现的独立 bug（不影响假死，可选修）
`app/services/backup.py` 备份任务使用 `subprocess.create_subprocess_exec`（正确应为 `asyncio.create_subprocess_exec`），
导致 `error.log` 在 `03:00` 报 `数据库备份失败: module 'subprocess' has no attribute 'create_subprocess_exec'` —— 备份实际未生效。
需要的话可一并修复。
