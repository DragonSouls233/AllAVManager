@echo off
chcp 65001 >nul
echo ============================================
echo  部署：JAV 影片编辑保存（PATCH 端点）
echo ============================================

REM ---------- 后端 ----------
echo [1/2] 同步后端代码到 L:\app ...
if not exist "L:\app" (
  echo [错误] 未找到 L:\app，请确认服务器运行目录已挂载！
  pause
  exit /b 1
)
copy /Y "G:\MDCX\MDCX-Server\app\api\routes\jav_routes.py"  "L:\app\api\routes\jav_routes.py"

echo [2/2] 完成！
echo.
echo 本次仅后端改动（新增 PATCH /jav/movies/{id} 端点），前端无需重新构建。
echo 请到服务器上重启后端（如 supervisor / run.py --no-tray --no-browser），
echo 然后进入任意 JAV 影片详情 →「编辑影片数据」→ 修改保存即可。
pause
