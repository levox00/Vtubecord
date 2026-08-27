@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Install Dependencies

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "BACKEND=!ROOT!\backend"
set "FRONTEND=!ROOT!\frontend"
set "CONFIG_DIR=!ROOT!\config"

echo ========================================
echo   AI VTuber - Install Dependencies
echo ========================================
echo.
echo Project root: !ROOT!
echo.

echo [1/3] Setting up Python backend...

if not exist "!BACKEND!\app\main.py" (
    echo [ERROR] Cannot find backend\app\main.py
    echo Expected: !BACKEND!\app\main.py
    pause
    exit /b 1
)

if not exist "!BACKEND!\.venv\Scripts\python.exe" (
    echo     Creating virtual environment...
    pushd "!BACKEND!"
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        popd
        pause
        exit /b 1
    )
    popd
)

if not exist "!BACKEND!\.venv\Scripts\python.exe" (
    echo [ERROR] venv missing python.exe after creation.
    echo Try installing Python 3.12 or 3.13 from python.org
    pause
    exit /b 1
)

set "VPY=!BACKEND!\.venv\Scripts\python.exe"
echo     Using: !VPY!
echo     Upgrading pip...
"!VPY!" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip upgrade failed.
    pause
    exit /b 1
)

echo     Installing requirements.txt ...
"!VPY!" -m pip install -r "!BACKEND!\requirements.txt"
if errorlevel 1 (
    echo [ERROR] pip install failed.
    echo.
    echo Tips:
    echo   - Python 3.14 is very new; prefer Python 3.12 or 3.13
    echo   - Delete backend\.venv and try again
    pause
    exit /b 1
)
echo [OK] Backend dependencies installed.

echo.
echo [2/3] Setting up frontend...

if not exist "!FRONTEND!\package.json" (
    echo [ERROR] frontend\package.json not found
    pause
    exit /b 1
)

pushd "!FRONTEND!"
call npm install
if errorlevel 1 (
    echo [ERROR] npm install failed.
    popd
    pause
    exit /b 1
)
popd
echo [OK] Frontend dependencies installed.

echo.
echo [3/3] Preparing config and folders...

if not exist "!CONFIG_DIR!\config.yaml" (
    copy "!CONFIG_DIR!\config.example.yaml" "!CONFIG_DIR!\config.yaml" >nul
    echo [OK] Created config\config.yaml from example.
) else (
    echo [OK] config\config.yaml already exists.
)

if not exist "!BACKEND!\data" mkdir "!BACKEND!\data"
if not exist "!ROOT!\assets\models\gguf" mkdir "!ROOT!\assets\models\gguf"
if not exist "!ROOT!\assets\voices\piper" mkdir "!ROOT!\assets\voices\piper"
if not exist "!ROOT!\assets\live2d\shizuku" mkdir "!ROOT!\assets\live2d\shizuku"
if not exist "!ROOT!\assets\whisper" mkdir "!ROOT!\assets\whisper"
if not exist "!ROOT!\tools\llama.cpp" mkdir "!ROOT!\tools\llama.cpp"

echo.
echo ========================================
echo   Dependencies installed successfully.
echo.
echo   Next steps:
echo     - 02_download_llm_model.bat
echo     - Or START.bat
echo ========================================
pause
exit /b 0
