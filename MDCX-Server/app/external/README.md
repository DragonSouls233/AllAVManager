# Third-Party Reference Code

本目录包含从开源参考项目移植到 MDCX-Server 的代码，按来源分目录组织。

> 📋 引入决策与对比报告：`O:\MDCX\.workbuddy\memory\REFERENCE-COMPARISON.md`
> 📋 引入检查清单：每个子目录的 `LICENSE` 文件、`ORIGIN.md` 注明来源

## 目录约定

| 子目录 | 来源 | 许可 | 状态 |
|---|---|---|---|
| `mnamer/` | https://github.com/jkwill87/mnamer (mnamer-main) | MIT | 🔵 已引入 |
| `mdcmaster_crawlers/` | https://github.com/avtopiri/mdcx (mdcx-master) | MIT | 🟡 计划中 |
| `mdcmaster_tools/` | https://github.com/avtopiri/mdcx (mdcx-master) | MIT | 🟡 计划中 |

## 硬性规则

1. **每文件单独引入**（单文件/单包），禁止将多个第三方项目混在同一文件
2. **保留原始 LICENSE 注释**于文件头部（COPYRIGHT + LICENSE 文本）
3. **修改部分必须有 `// MDCX MODIFIED:` 注释**注明修改人与原因
4. **禁止引入 GPL 系**（JavSP GPL-3.0、Jellyfin Plugin GPL-3.0、Medusa GPL-3.0、AVDC GPL-3.0）— 仅算法参考，不 import
5. **每个子目录的 `ORIGIN.md`** 必须记录：来源仓库 / commit hash / 引入日期 / 适配者
6. **升级策略**：上游更新时只 `diff` 受改动的文件，全文件覆盖前必查 `ORIGIN.md` 中"已修改区域"

## 与 MDCX 主代码的边界

- `app/external/<source>/<feature>.py` — 第三方代码原样或轻度适配
- `app/services/<feature>_engine.py` — 我们写的包装层，**严禁 import 内部细节**泄露到上层
- 上层模块（routes / scraper）只允许 `from app.services.<feature>_engine import ...`
