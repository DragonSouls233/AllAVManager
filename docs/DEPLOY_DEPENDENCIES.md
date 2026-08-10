# MDCX 服务器依赖安装指南（Windows 本机）

> 服务器（192.168.10.110）跑的是 **Windows + Python 本机环境**（非 Docker）。
> 因为开发机到服务器的 SMB 共享是**只读**，以下命令必须在**服务器本机**的终端里执行，
> 不能在我的开发机环境里跑。

## 一、确认服务器 Python

在服务器本机打开 CMD / PowerShell，确认 Python 可用，并定位实际解释器：

```bat
python --version
where python
```

> 服务器当前跑 MDCX 用的就是 `python run.py` 里的 `sys.executable -m uvicorn`，
> 所以**必须用同一个 Python** 装依赖，不要装到别的环境里。

## 二、安装核心依赖（第一步必做）

进入项目根目录（服务器上一般是 `E:\MDCX-Server`），执行：

```bat
cd E:\MDCX-Server
pip install -r requirements.txt
```

如果要**重装/对齐到 requirements 锁定的版本**：

```bat
pip install --upgrade -r requirements.txt
```

## 三、浏览器反爬内核（装完必做）

`requirements.txt` 里的 `playwright` 装完只装了 Python 包，**还必须下载浏览器内核**：

```bat
python -m playwright install chromium
python -m playwright install chromium-headless-shell
```

> 这一步很多人漏掉，漏了会导致 javdb 爬虫、cookie 登录、stealth 抓取全部失效。
> 网络受限时可用镜像：
> ```bat
> set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
> python -m playwright install chromium
> ```

## 四、可选 / 按需安装（不装也能跑，但对应功能不可用）

| 包 | 对应功能 | 装法 |
|---|---|---|
| `opencv-python` `mediapipe` `onnxruntime` | 人脸裁剪 / 水印 / 马赛克 | `pip install opencv-python mediapipe onnxruntime` |
| `googletrans==4.0.0rc1` | 翻译工具 | `pip install --pre googletrans==4.0.0rc1` |
| `patchright` | DMM 爬虫 | 已在 requirements.txt，默认装 |

> ⚠️ 若服务器用 Python 3.14：`mediapipe` / `onnxruntime` 可能没有对应 wheel，
> 装不上时这些功能先跳过，不影响主服务。

## 五、验证依赖装成功

```bat
python -c "import fastapi, uvicorn, sqlalchemy, aiosqlite, lxml, parsel, bs4, curl_cffi, httpx, cloudscraper, openai, tenacity; print('核心依赖 OK')"
```

## 六、装完重启服务

```bat
:: 重启 MDCX 后端
cd E:\MDCX-Server
:: 若服务是后台托盘方式，先关闭托盘图标，再重新运行
python run.py --port 8420
```

---

## ⚠️ 重要提醒

1. **必须在服务器本机跑**这些命令——我这边是开发机，连的是只读 SMB，我执行会失败。
2. 装依赖后**必须重启后端**才生效。
3. 如果 `pip install` 报网络错误/超时，可加国内镜像：
   ```bat
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```
4. 依赖装好、服务重启后，前端我这边已构建好（含类别页 + 筛选修复），
   把 `G:\MDCX\MDCX-Server\static` 整目录覆盖到服务器 `E:\MDCX-Server\static` 再硬刷新即可。
