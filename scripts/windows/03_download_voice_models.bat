@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Download Piper Voices

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "OUTDIR=!ROOT!\assets\voices\piper"
if not exist "!OUTDIR!" mkdir "!OUTDIR!"

echo ========================================
echo   Download Piper TTS Voices
echo ========================================
echo Save path: !OUTDIR!
echo.
echo   1^) en_US-lessac-medium
echo   2^) en_US-amy-medium
echo   3^) Both
echo   4^) Skip
echo.
set /p "CHOICE=Enter choice [1-4]: "

if "!CHOICE!"=="4" goto DONE
if "!CHOICE!"=="1" (
    call :DOWNLOAD_VOICE en_US-lessac-medium en/en_US/lessac/medium
    goto DONE
)
if "!CHOICE!"=="2" (
    call :DOWNLOAD_VOICE en_US-amy-medium en/en_US/amy/medium
    goto DONE
)
if "!CHOICE!"=="3" (
    call :DOWNLOAD_VOICE en_US-lessac-medium en/en_US/lessac/medium
    call :DOWNLOAD_VOICE en_US-amy-medium en/en_US/amy/medium
    goto DONE
)
echo Invalid.
pause
exit /b 1

:DOWNLOAD_VOICE
set "VOICE_NAME=%~1"
set "HF_PATH=%~2"
set "BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/!HF_PATH!"
echo Downloading !VOICE_NAME! ...
curl -L --fail -o "!OUTDIR!\!VOICE_NAME!.onnx" "!BASE!/!VOICE_NAME!.onnx"
if errorlevel 1 powershell -NoProfile -Command "Invoke-WebRequest -Uri '!BASE!/!VOICE_NAME!.onnx' -OutFile '!OUTDIR!\!VOICE_NAME!.onnx'"
curl -L --fail -o "!OUTDIR!\!VOICE_NAME!.onnx.json" "!BASE!/!VOICE_NAME!.onnx.json"
if errorlevel 1 powershell -NoProfile -Command "Invoke-WebRequest -Uri '!BASE!/!VOICE_NAME!.onnx.json' -OutFile '!OUTDIR!\!VOICE_NAME!.onnx.json'"
echo [OK] !VOICE_NAME!
exit /b 0

:DONE
echo Done.
pause
exit /b 0
