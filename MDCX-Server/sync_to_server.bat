@echo off
chcp 65001 >nul
title MDCX 一键同步脚本
echo ============================================
echo  MDCX 服务端更新脚本
echo  从 \\192.168.10.110\MDCX-Server 同步到 E:\MDCX-Server
echo ============================================
echo.

set SRC=\\192.168.10.110\MDCX-Server
set DST=E:\MDCX-Server

echo [1/3] 同步后端代码...
echo   -> 全量同步 app 目录（增量更新，已有文件只覆盖更旧的）

rem 先确认共享可访问
if not exist "%SRC%\app" (
    echo [错误] 无法访问共享路径 %SRC%
    pause
    exit /b 1
)

xcopy "%SRC%\app" "%DST%\app" /E /Y /D /Q >nul 2>&1
echo   -> app 同步完成

echo.
echo [2/3] 同步前端 dist（构建好的新页面）...
xcopy "%SRC%\static" "%DST%\static" /E /Y /D /Q >nul 2>&1
echo   -> static 同步完成

echo.
echo [3/3] 修复 JAV 模块配置...
powershell -Command ^
"$yaml = Get-Content '%DST%\data\config\config.yaml' -Raw; " ^
"$yaml = $yaml -replace 'jav:\s*\n\s+enabled: false', 'jav:`n  enabled: true'; " ^
"Set-Content '%DST%\data\config\config.yaml' -Value $yaml -Force"
echo   -> 配置修复完成

echo.
echo ============================================
echo  同步完成！
echo.
echo  请重启服务：
echo   按 Ctrl+C 停止当前服务
echo   然后运行： python run.py
echo ============================================
pause
