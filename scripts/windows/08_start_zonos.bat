@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Zonos TTS (Port 8091)

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "ZONOS=!ROOT!\tools\zonos"
set "VPY=!ZONOS!\.venv\Scripts\python.exe"

echo ========================================
echo   Starting Zonos TTS Server (8091)
echo ========================================
echo.

if not exist "!VPY!" (
    echo [ERROR] Zonos venv not found at !VPY!
    echo Run: cd tools\zonos && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

set "PYTHONPATH=!ZONOS!"
set "HF_HOME=!ZONOS!\huggingface"
set "TORCH_HOME=!ZONOS!\torch"
set "XFORMERS_FORCE_DISABLE_TRITON=1"
rem Keep phonemizer's per-process DLL copy in a writable project directory.
rem This avoids restrictive Windows TEMP ACLs seen with some Python installs.
set "ZONOS_TEMP=!ZONOS!\tmp"
if not exist "!ZONOS_TEMP!" mkdir "!ZONOS_TEMP!"
set "TEMP=!ZONOS_TEMP!"
set "TMP=!ZONOS_TEMP!"

echo Checking PyTorch CUDA runtime...
"!VPY!" -c "import torch; print('  torch=' + torch.__version__ + ' cuda_build=' + str(torch.version.cuda or 'none') + ' cuda_available=' + str(torch.cuda.is_available()) + ' device=' + (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'))"
if errorlevel 1 echo [WARNING] Could not inspect the Zonos PyTorch runtime.

rem Prefer an installed eSpeak NG runtime so phonemizer can build Zonos text conditioning.
rem The Python helper in server.py also discovers this automatically when the
rem launcher is started from another shell.
set "ESPEAK_LOADER=!LOCALAPPDATA!\Programs\Python\Python314\Lib\site-packages\espeakng_loader"
if exist "!ESPEAK_LOADER!\espeak-ng.dll" (
    set "PHONEMIZER_ESPEAK_LIBRARY=!ESPEAK_LOADER!\espeak-ng.dll"
    set "ESPEAK_DATA_PATH=!ESPEAK_LOADER!\espeak-ng-data"
) else if exist "C:\Program Files\eSpeak NG\libespeak-ng.dll" (
    set "PHONEMIZER_ESPEAK_LIBRARY=C:\Program Files\eSpeak NG\libespeak-ng.dll"
) else if exist "C:\Program Files\eSpeak NG\espeak-ng.dll" (
    set "PHONEMIZER_ESPEAK_LIBRARY=C:\Program Files\eSpeak NG\espeak-ng.dll"
)

echo Zonos:    http://127.0.0.1:8091
echo.
"!VPY!" "!ZONOS!\server.py"

pause
exit /b 0
