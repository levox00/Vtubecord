@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Index-TTS (Port 8090)

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "INDEX_TTS=!ROOT!\tools\index-tts"
set "VPY=!INDEX_TTS!\.venv\Scripts\python.exe"

echo ========================================
echo   Starting Index-TTS Server (8090)
echo ========================================
echo.

if not exist "!VPY!" (
    echo [ERROR] Index-TTS venv not found at !VPY!
    echo Run: cd tools\index-tts && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

set "PYTHONPATH=!INDEX_TTS!"

echo Index-TTS: http://127.0.0.1:8090
echo.
"!VPY!" "!INDEX_TTS!\server.py"

pause
exit /b 0
