@echo off
title MDCX Deploy Tool

echo ========================================
echo   MDCX Deploy Tool
echo ========================================
echo.

set SERVER_PATH=L:\static
set DIST_PATH=G:\MDCX\MDCX-Desktop\dist

REM 1. Check source
if not exist "%DIST_PATH%" (
    echo [ERROR] dist not found: %DIST_PATH%
    echo [INFO] Run "npm run build" first
    pause
    exit /b 1
)
echo [OK] Source: %DIST_PATH%

REM 2. Check target
if not exist "%SERVER_PATH%" (
    echo [INFO] Creating target: %SERVER_PATH%
    mkdir "%SERVER_PATH%"
)
echo [OK] Target: %SERVER_PATH%

REM 3. Clean target
echo.
echo [..] Cleaning %SERVER_PATH% ...
del /f /s /q "%SERVER_PATH%\*.*" >nul 2>&1
for /d %%p in ("%SERVER_PATH%\*") do rmdir /s /q "%%p" 2>nul
echo [OK] Target cleaned

REM 4. Copy files
echo.
echo [..] Copying files ...
xcopy "%DIST_PATH%\*" "%SERVER_PATH%\" /E /I /Y >nul
echo [OK] Files copied

REM 5. Verify
if exist "%SERVER_PATH%\index.html" (
    echo [OK] index.html verified
) else (
    echo [ERROR] Deploy failed - index.html not found
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Deploy Complete!
echo   Open http://192.168.10.110:8420/
echo ========================================
echo.
pause
