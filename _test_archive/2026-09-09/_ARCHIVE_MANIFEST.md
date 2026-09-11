# 测试文件归档清单

- **归档时间**：2026-09-09 17:40
- **来源**：`G:\MDCX\` 根目录散落文件
- **归档位置**：`G:\MDCX\_test_archive\2026-09-09\`
- **操作方式**：移动（mv），**未删除任何文件**
- **数量**：69 项，合计 1.1 MB

## 归档内容分类

| 类别 | 示例 | 数量 |
|---|---|---|
| 一次性 Python 测试脚本 | `_test*.py`、`test_*.py`、`tmp_*.py` | 约 55 |
| JS 崩溃复现脚本 | `test_compare_crash*.js`、`test_compare_ui.js` | 5 |
| 测试截图/产物 | `jav_list.png`、`login_test.png`、`test_web_fixed.png`、`test_web_home.png` | 4 |
| 临时数据库残留 | `_tmp_anime_test.db-shm` / `-wal` | 2 |
| 辅助诊断脚本 | `check_covers.py`、`fix_series.py`、`inspect_actors.py`、`list_tables.py`、`source_dist.py`、`fc2_scrape_test.py` | 6 |
| 测试文档 | `TEST_FIX_4_MODULES.md` | 1 |
| 缓存 | `__pycache__`（根目录，由上述脚本产生） | 1 |

## 保留未动（用户确认）

- `ms-playwright/` (702 MB)、`_verify_data/` (188 MB)、`node_modules/` (32 MB)、`backups/` (19 MB)
- 已成体系的测试目录：`scripts/`、`QA-Tests/`、`Tools/`、`query_tmp/`、`screenshots/`、`reports/`、`tmp_scancheck/`、`tmp_nfo_smoke/`、`tmp_sakuramedia/`
- 根目录保留：`.gitattributes`、`.gitignore`、`README.md`

## 遗留项

`G:\MDCX\nul` — 0 字节 Windows 保留设备名垃圾文件（历史上 `> nul` 误用产生）。
Windows 不允许对保留名做 rename/move，脚本返回 EPERM。如需清除，在**管理员 CMD** 执行：

```
del "\\?\G:\MDCX\nul"
```

## 注意

- 上述文件**均未被 git 跟踪**（已 `git ls-files` 验证），移动不影响版本库。
- `scripts/` 下 `mdcx_smoke_ctx.cjs`、`mdcx_anime_detail.cjs` 是仍在使用的 e2e 冒烟脚本，**未移动**。
