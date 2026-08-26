# mnamer — 来源与适配记录

## 来源

- **上游仓库**：https://github.com/jkwill87/mnamer
- **本地副本**：`O:\MDCX\GitHub-ZIP\P3-Media\mnamer\mnamer-main`
- **引入日期**：2026-07-06
- **引入者**：MDCX Development Team
- **上游 commit**：HEAD（截至 2026-07-06，未固定 commit hash，因 fork 完整性需要后续用 `git submodule` 替换）

## 许可

- **上游 LICENSE**：MIT License
- **Copyright**：上游作者（详见 `mnamer/LICENSE.txt`）
- **MDCX 许可兼容性**：✅ MIT → MIT，闭源衍生 OK
- **必须保留**：原 LICENSE 文本 + 版权声明（已拷贝到 `mnamer/LICENSE.txt`）

## 用途

智能文件重命名引擎。在 MDCX 中作为：

- `app/services/naming.py` 的智能后备（当用户配置为「自动重命名」时调用）
- `app/services/file_organize.py` 的目标路径计算器
- 独立 CLI：`python -m mnamer` 维持与上游一致的体验

## 适配状态

| 阶段 | 状态 | 备注 |
|---|---|---|
| 1. 整包拷贝 | ✅ 完成 | 2026-07-06 |
| 2. 异步包装层 | ✅ 完成 | `app/services/mnamer_engine.py` |
| 3. 接到 naming.py | ✅ 完成 | 见包装层 |
| 4. 接到 file_organize.py | ✅ 完成 | 见包装层 |
| 5. 单元测试 | ✅ 完成 | `tests/test_mnamer_engine.py` |
| 6. 文档 | ✅ 完成 | `O:\MDCX\MDCX-DESIGN.md` 引用 |

## 升级策略

- 监听 https://github.com/jkwill87/mnamer/releases
- 升级前先 diff 我们的 `mnamer/` 与上游，标注 MDCX 改动
- 重大 API 变更时同步更新 `mnamer_engine.py` 包装层

## 已知差异

| 区域 | MDCX 适配 | 原因 |
|---|---|---|
| `mnamer/__init__.py` | 未改 | 保留原样 |
| `mnamer/__main__.py` | 未改 | 保留原 CLI 体验 |
| 所有内部模块 | 未改 | 整包引用 |
| 异步调用 | 包装层 `mnamer_engine.py` 处理 | mnamer 本身是同步实现 |
