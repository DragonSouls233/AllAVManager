@echo off
chcp 65001 >nul
echo ============================================
echo  MDCX 服务端更新脚本
echo  从共享路径 \\192.168.10.110\MDCX-Server 同步
echo ============================================
echo.

set SRC=G:\MDCX\MDCX-Server
set DST=E:\MDCX-Server

echo [1/3] 更新后端服务代码...
copy /Y "%SRC%\app\api\routes\actresses.py" "%DST%\app\api\routes\actresses.py"
copy /Y "%SRC%\app\api\routes\read_only.py" "%DST%\app\api\routes\read_only.py"
copy /Y "%SRC%\app\api\routes\stash_api.py" "%DST%\app\api\routes\stash_api.py"
copy /Y "%SRC%\app\api\routes\western_enhanced.py" "%DST%\app\api\routes\western_enhanced.py"
copy /Y "%SRC%\app\api\routes\ws_events.py" "%DST%\app\api\routes\ws_events.py"
copy /Y "%SRC%\app\api\__init__.py" "%DST%\app\api\__init__.py"
copy /Y "%SRC%\app\main.py" "%DST%\app\main.py"
copy /Y "%SRC%\app\middleware\performance.py" "%DST%\app\middleware\performance.py"
xcopy /E /Y "%SRC%\app\services\*.py" "%DST%\app\services\"
xcopy /E /Y "%SRC%\app\crawlers\*.py" "%DST%\app\crawlers\"
echo 后端代码更新完成!
echo.

echo [2/3] 更新前端静态文件...
xcopy /E /Y "%SRC%\static\*" "%DST%\static\"
echo 前端文件更新完成!
echo.

echo [3/3] 修复配置中 JAV 模块...
powershell -Command "(Get-Content '%DST%\data\config\config.yaml') -replace 'jav:\s*\n\s+enabled: false', 'jav:`n  enabled: true' | Set-Content '%DST%\data\config\config.yaml'"
echo 配置修复完成!
echo.

echo ============================================
echo  更新完成！请重启服务：
echo  1. 按 Ctrl+C 停止当前服务
echo  2. 重新运行：python run.py
echo ============================================
pause
