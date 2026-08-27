@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Prerequisites Check

echo ========================================
echo   AI VTuber - Prerequisites Check
echo ========================================
echo.

set "MISSING=0"

where python >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found in PATH
    echo     Install Python 3.12+ from https://www.python.org/downloads/
    echo     IMPORTANT: Check "Add python.exe to PATH" during install
    set "MISSING=1"
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
    echo [OK] Python found: !PYVER!
)

where node >nul 2>&1
if errorlevel 1 (
    echo [X] Node.js not found in PATH
    echo     Install Node.js 20+ LTS from https://nodejs.org/
    set "MISSING=1"
) else (
    for /f "tokens=1" %%v in ('node --version 2^>^&1') do set "NODEVER=%%v"
    echo [OK] Node.js found: !NODEVER!
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [X] npm not found
    set "MISSING=1"
) else (
    for /f "tokens=1" %%v in ('npm --version 2^>^&1') do set "NPMVER=%%v"
    echo [OK] npm found: !NPMVER!
)

where git >nul 2>&1
if errorlevel 1 (
    echo [!] Git not found optional
) else (
    echo [OK] Git found
)

where curl >nul 2>&1
if errorlevel 1 (
    echo [!] curl not found - will use PowerShell for downloads
) else (
    echo [OK] curl found
)

echo.
if "!MISSING!"=="1" (
    echo ========================================
    echo   Some required tools are missing.
    echo ========================================
    pause
    exit /b 1
)

echo ========================================
echo   All basic prerequisites OK.
echo ========================================
pause
exit /b 0
