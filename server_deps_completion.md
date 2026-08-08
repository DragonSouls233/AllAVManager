# MDCX 服务端依赖补全审计（7 模块）

> 审计日期：2026-08-08
> 方法：对 `MDCX-Server/app/` 全量 `.py` 做 AST 解析，提取第三方 import，与 `requirements.txt` 求差；缺失项在 `C:\Python314`（开发机实际运行环境）逐一核验。

## 7 个模块
`jav` · `fc2` · `uncensored` · `chinese` · `western` · `pornhub` · `anime`

依赖绝大多数不在「单个模块」里，而在**模块共用的 scraper / crawler / service / utils**（如 `llm_scraper`、`face_crop`、`module_actor_avatar`、`cookie_login`、`stealth_fetcher`、`translate`、`dedup`），所以补的是「全模块共享基建」，非某模块独占。

## 已写入 requirements.txt 的缺失依赖（13 个 PyPI 包）

| import 名 | pip 包名 | 锁定版本 | 用途 / 触发位置 | 开发机是否已装 |
|---|---|---|---|---|
| cloudscraper | cloudscraper | 1.2.71 | javdb 反爬绕过（jav 等模块） | ✅ 已装 |
| undetected_chromedriver | undetected-chromedriver | 3.5.5 | javdb 抗检测驱动 | ✅ 已装 |
| scrapling | scrapling | 0.4.9 | stealth_fetcher  stealth 抓取 | ✅ 已装 |
| playwright | playwright | 1.60.0 | cookie_login 浏览器登录 | ✅ 已装 |
| openai | openai | 1.54.4 | llm_scraper  LLM 补元数据（多模块 enrich） | ❌ 缺失→补 |
| aiolimiter | aiolimiter | 1.1.0 | llm_scraper 限流 | ❌ 缺失→补 |
| cv2 | opencv-python | 4.13.0.92 | face_crop / watermark / mosaic 图像处理 | ✅ 已装 |
| mediapipe | mediapipe | 0.10.14 | face_crop 人脸检测 | ❌ 缺失→补（重） |
| onnxruntime | onnxruntime | 1.19.2 | face_crop ONNX 推理 | ❌ 缺失→补（重） |
| googletrans | googletrans | 4.0.0rc1 | translate 标题/字幕翻译 | ❌ 缺失→补 |
| imagehash | ImageHash | 4.3.2 | dedup / video_hash 感知哈希 | ✅ 已装 |
| tenacity | tenacity | 9.0.0 | module_actor_avatar 重试 | ❌ 缺失→补 |
| charset_normalizer | charset-normalizer | 3.4.4 | http_client 编码探测（直接 import） | ✅ 已装 |

## 两类「不能写进 requirements.txt」的特例（需你手动处理）

### ⚠️ 特例 1：`core`（非 PyPI 本地包）—— 影响 `chinese` 模块的 haijiao 爬虫
`app/services/haijiao_adapter.py` 顶部：
```python
from core.extractor import TitleExtractor
from core.title_parser import (...)
```
仓库内**没有** `core` 目录，文件 docstring 注明它引用的是另一个项目（P2）的本地 `core` 包（`.references/特殊项目/提取/core/`）。这是**外部本地代码依赖，不是 pip 包**，无法 `pip install`。
- 后果：在全新服务器上，一旦触发 haijiao 爬虫该 import 会 `ModuleNotFoundError`。
- 处理：把 P2 的 `core/` 包随服务器源码一起拷贝到 `MDCX-Server/` 根目录（成为 `MDCX-Server/core/`），或在服务器侧另行放置该包。不解决则 chinese 的 haijiao 子功能不可用，但**不影响其余 6 个模块**。

### ⚠️ 特例 2：`webview`（pywebview）—— 仅桌面端，服务器不需要
`app/desktop/pywebview_app.py` 用到 `import webview`，但服务器入口 `run.py`/`main.py` **不导入** `app.desktop`，属无头后端无关依赖。已**有意不写入**服务器 requirements（装了也用不到，且 pywebview 依赖系统 GUI 库）。

## 服务器一次性安装命令

```bash
# 1) 进入服务器源码目录
cd E:\MDCX-Server

# 2) 安装全部（含新增 13 个）
pip install -r requirements.txt

# 3) 两个必须的后置步骤
pip install --pre googletrans==4.0.0rc1   # 预发布版，主命令里的 ==4.0.0rc1 需 --pre 才会生效
playwright install chromium                 # 下载浏览器内核，否则 cookie_login 不可用

# 4) 若服务器用 Python 3.14：mediapipe / onnxruntime 需确认有 3.14 wheel，
#    否则 face_crop 功能装上也会 import 失败（不影响其他模块启动）
```

## 风险提示
1. **重量级包**：`mediapipe` + `onnxruntime` + `opencv-python` 体积大（合计数百 MB~1GB+），仅在启用「人脸裁剪/水印/马赛克」时需要；若服务器只是跑刮削+扫描，可暂缓这 3 个。
2. **Python 3.14 轮子**：服务器若为 3.14，部分包（尤其 mediapipe/onnxruntime）可能暂无 3.14 wheel，安装前先 `pip install <包>` 试装确认。
3. **googletrans**：官方只发 `4.0.0rc1` 这一个能用的版本，必须 `--pre`。
4. **openai 版本**：llm_scraper 按 OpenAI 1.x 客户端 API 编写，已锁 `1.54.4`（2.x 主版本 API 大体兼容但建议先锁 1.x）。

## 审计未改动
开发机 `C:\Python314` 上本就缺失的 `openai/aiolimiter/mediapipe/onnxruntime/googletrans/tenacity` 此前从未安装 → 对应功能在开发机亦未启用；本次补齐后服务器可一并具备。
