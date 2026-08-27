@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Start llama.cpp Server

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "GGUF_DIR=!ROOT!\assets\models\gguf"
set "TOOLS=!ROOT!\tools\llama.cpp"

echo ========================================
echo   Start llama.cpp Server
echo ========================================
echo.

set "MODEL="
for %%F in ("!GGUF_DIR!\*.gguf") do (
    set "MODEL=%%~fF"
    goto FOUND_MODEL
)
:FOUND_MODEL

if "!MODEL!"=="" (
    echo [ERROR] No .gguf file found in assets\models\gguf\
    echo Run 02_download_llm_model.bat first.
    pause
    exit /b 1
)

echo Found model directory: !GGUF_DIR!
echo.

set "LLAMA_SERVER="
where llama-server >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%i in ('where llama-server') do set "LLAMA_SERVER=%%i"
)

if "!LLAMA_SERVER!"=="" (
    if exist "!TOOLS!\llama-server.exe" set "LLAMA_SERVER=!TOOLS!\llama-server.exe"
)
if "!LLAMA_SERVER!"=="" (
    if exist "!ROOT!\tools\llama-server.exe" set "LLAMA_SERVER=!ROOT!\tools\llama-server.exe"
)

if "!LLAMA_SERVER!"=="" (
    echo llama-server.exe not found.
    echo Download from https://github.com/ggml-org/llama.cpp/releases
    echo Put llama-server.exe into tools\llama.cpp\
    start https://github.com/ggml-org/llama.cpp/releases
    pause
    exit /b 1
)

echo Using: !LLAMA_SERVER!

REM --- Auto-extract CUDA DLLs if missing ---
set "HAS_CUDART=0"
where cudart64_*.dll >nul 2>&1
if not errorlevel 1 set "HAS_CUDART=1"

if "!HAS_CUDART!"=="0" (
    dir "!TOOLS!\cudart64_*.dll" >nul 2>&1
    if not errorlevel 1 set "HAS_CUDART=1"
)

if "!HAS_CUDART!"=="0" (
    echo CUDA runtime DLLs not found. Extracting from cudart-llama-bin-win-cuda-13.3-x64.zip ...
    if exist "!TOOLS!\cudart-llama-bin-win-cuda-13.3-x64.zip" (
        powershell -Command "Expand-Archive -Path '!TOOLS!\cudart-llama-bin-win-cuda-13.3-x64.zip' -DestinationPath '!TOOLS!' -Force"
        echo CUDA DLLs extracted to !TOOLS!\
    ) else (
        echo [WARNING] cudart-llama-bin-win-cuda-13.3-x64.zip not found in !TOOLS!\
        echo CUDA DLLs may be missing. If llama-server fails to start, extract the zip manually.
    )
)

echo Server: http://127.0.0.1:8081 (router mode, one model in VRAM)
set "PERF_ARGS="
set "PROFILE_PYTHON=python"
if exist "!ROOT!\backend\.venv\Scripts\python.exe" set "PROFILE_PYTHON=!ROOT!\backend\.venv\Scripts\python.exe"
set "PROFILE_PYTHON_OK=0"
if exist "!PROFILE_PYTHON!" set "PROFILE_PYTHON_OK=1"
if "!PROFILE_PYTHON!"=="python" (
    where python >nul 2>&1
    if not errorlevel 1 set "PROFILE_PYTHON_OK=1"
)
if "!PROFILE_PYTHON_OK!"=="1" (
    for /f "delims=" %%A in ('"!PROFILE_PYTHON!" "!ROOT!\scripts\performance_profile.py" --root "!ROOT!" --server "!LLAMA_SERVER!" --llama-args --platform windows') do set "PERF_ARGS=%%A"
)
if "!PERF_ARGS!"=="" echo [WARNING] Performance profile resolver unavailable; using llama.cpp defaults.
if not "!PERF_ARGS!"=="" echo Performance: !PERF_ARGS!
echo Press Ctrl+C to stop.
echo.

REM Router mode lets the backend load/unload GGUF files on demand.  Keeping
REM the maximum at one model prevents two selected models from sharing VRAM.
"!LLAMA_SERVER!" --models-dir "!GGUF_DIR!" --models-max 1 --models-autoload --jinja --host 127.0.0.1 --port 8081 -c 16384 -ngl 99 !PERF_ARGS!

pause
exit /b 0
