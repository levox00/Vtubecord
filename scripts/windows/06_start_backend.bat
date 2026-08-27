@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Backend

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "BACKEND=!ROOT!\backend"
set "VPY=!BACKEND!\.venv\Scripts\python.exe"

echo ========================================
echo   Starting Backend FastAPI
echo ========================================
echo.

if not exist "!VPY!" (
    echo [ERROR] Virtual environment not found.
    echo Run scripts\windows\01_install_dependencies.bat first.
    pause
    exit /b 1
)

if not exist "!BACKEND!\data" mkdir "!BACKEND!\data"

pushd "!BACKEND!"
set "PYTHONPATH=!BACKEND!"
echo Backend:  http://127.0.0.1:8000
echo API docs: http://127.0.0.1:8000/docs
echo.
"!VPY!" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
popd

pause
exit /b 0
