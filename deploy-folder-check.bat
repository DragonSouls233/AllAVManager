@echo off
chcp 65001 >nul
echo ============================================
echo  部署：JAV 文件夹归属检测/回填功能
echo ============================================

REM ---------- 后端 ----------
echo [1/3] 同步后端代码到 L:\app ...
if not exist "L:\app" (
  echo [错误] 未找到 L:\app，请确认服务器运行目录已挂载！
  pause
  exit /b 1
)
copy /Y "G:\MDCX\MDCX-Server\app\utils\folder_actor_check.py" "L:\app\utils\folder_actor_check.py"
copy /Y "G:\MDCX\MDCX-Server\app\api\routes\jav_routes.py"  "L:\app\api\routes\jav_routes.py"

REM ---------- 前端 ----------
echo [2/3] 整目录替换 L:\static（清旧产物防残留） ...
if exist "L:\static\assets" rmdir /S /Q "L:\static\assets"
xcopy "G:\MDCX\MDCX-Desktop\dist\*" "L:\static\" /E /Y >nul

echo [3/3] 完成！
echo.
echo 请到服务器上重启后端（如 supervisor / run.py --no-tray --no-browser），
echo 浏览器 Ctrl+Shift+R 硬刷新后，在 JAV 有码菜单 →「文件夹归属」使用。
pause
