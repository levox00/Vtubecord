@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Live2D Shizuku

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"

echo ========================================
echo   Live2D Shizuku Sample Setup
echo ========================================
echo.
echo Official free sample:
echo   https://www.live2d.com/en/learn/sample/shizuku/
echo.
echo This project does NOT redistribute Live2D assets.
echo Download from the official site and extract into:
echo.
echo   !ROOT!\assets\live2d\shizuku\
echo.
echo Opening the official page...
start https://www.live2d.com/en/learn/sample/shizuku/
echo.
echo Read and obey the Live2D Sample License.
pause
exit /b 0
