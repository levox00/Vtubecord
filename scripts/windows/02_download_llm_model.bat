@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Download LLM Model

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "OUTDIR=!ROOT!\assets\models\gguf"
if not exist "!OUTDIR!" mkdir "!OUTDIR!"

echo ========================================
echo   Download Local LLM GGUF
echo ========================================
echo.
echo Save path: !OUTDIR!
echo.
echo   1^) Gemma 3 4B Q4_K_M
echo   2^) Gemma 3 4B Q5_K_M
echo   3^) Gemma 3 12B Q4_K_M
echo   4^) Custom URL
echo   5^) Skip
echo.
set /p "CHOICE=Enter choice [1-5]: "

if "!CHOICE!"=="1" (
    set "REPO=unsloth/gemma-3-4b-it-GGUF"
    set "FILE=gemma-3-4b-it-Q4_K_M.gguf"
    goto DOWNLOAD_HF
)
if "!CHOICE!"=="2" (
    set "REPO=unsloth/gemma-3-4b-it-GGUF"
    set "FILE=gemma-3-4b-it-Q5_K_M.gguf"
    goto DOWNLOAD_HF
)
if "!CHOICE!"=="3" (
    set "REPO=unsloth/gemma-3-12b-it-GGUF"
    set "FILE=gemma-3-12b-it-Q4_K_M.gguf"
    goto DOWNLOAD_HF
)
if "!CHOICE!"=="4" goto CUSTOM
if "!CHOICE!"=="5" (
    echo Skipped.
    goto DONE
)
echo Invalid choice.
pause
exit /b 1

:CUSTOM
set /p "CUSTOM_URL=Paste full URL to .gguf file: "
set /p "CUSTOM_NAME=Save as filename: "
curl -L -o "!OUTDIR!\!CUSTOM_NAME!" "!CUSTOM_URL!"
if errorlevel 1 powershell -NoProfile -Command "Invoke-WebRequest -Uri '!CUSTOM_URL!' -OutFile '!OUTDIR!\!CUSTOM_NAME!'"
goto DONE

:DOWNLOAD_HF
echo Repo: !REPO!  File: !FILE!
set /p "CONFIRM=Proceed? [Y/N]: "
if /i not "!CONFIRM!"=="Y" goto DONE
set "HF_URL=https://huggingface.co/!REPO!/resolve/main/!FILE!"
echo Downloading !HF_URL!
curl -L --fail -o "!OUTDIR!\!FILE!" "!HF_URL!"
if errorlevel 1 (
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '!HF_URL!' -OutFile '!OUTDIR!\!FILE!'"
    if errorlevel 1 (
        echo [ERROR] Download failed. Accept license on HF page and use option 4.
        pause
        exit /b 1
    )
)
echo [OK] !OUTDIR!\!FILE!

:DONE
echo Next: llama.cpp releases + 05_start_llamacpp.bat
pause
exit /b 0
