@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Full Setup Wizard

set "SCRIPT_DIR=%~dp0"

echo ========================================
echo   AI VTuber - Full Setup Wizard
echo ========================================
echo.
echo This wizard will guide you through:
echo   0. Prerequisites check
echo   1. Install Python + Node dependencies
echo   2. Download an LLM model optional, large
echo   3. Download Piper voices optional, Phase 2
echo   4. Live2D instructions Phase 2
echo.
echo You can cancel any optional step.
echo.
pause

call "!SCRIPT_DIR!00_check_prerequisites.bat"
if errorlevel 1 exit /b 1

call "!SCRIPT_DIR!01_install_dependencies.bat"
if errorlevel 1 exit /b 1

echo.
set /p "DL_LLM=Download a local GGUF model now? [Y/N]: "
if /i "!DL_LLM!"=="Y" call "!SCRIPT_DIR!02_download_llm_model.bat"

echo.
set /p "DL_VOICE=Download Piper TTS voices now? [Y/N]: "
if /i "!DL_VOICE!"=="Y" call "!SCRIPT_DIR!03_download_voice_models.bat"

echo.
set /p "DL_L2D=Open Live2D Shizuku download page? [Y/N]: "
if /i "!DL_L2D!"=="Y" call "!SCRIPT_DIR!04_download_live2d.bat"

echo.
echo ========================================
echo   Setup complete!
echo.
echo To run the app:
echo   - START.bat
echo.
echo Config: config\config.yaml
echo ========================================
pause
exit /b 0
