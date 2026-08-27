@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Frontend

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "FRONTEND=!ROOT!\frontend"

echo ========================================
echo   Starting Frontend Vite
echo ========================================
echo.

if not exist "!FRONTEND!\package.json" (
    echo [ERROR] frontend not found
    pause
    exit /b 1
)

pushd "!FRONTEND!"
if not exist "node_modules" (
    echo node_modules missing - running npm install...
    call npm install
)
echo Frontend: http://localhost:5173
echo.
call npm run dev
popd

pause
exit /b 0
