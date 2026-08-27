@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Start All

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "PID_FILE=%TEMP%\ai-vtuber-processes.txt"

echo ========================================
echo   AI VTuber - Launch Everything
echo ========================================
echo.
echo Project: !ROOT!
echo.

REM --- Kill old processes with a detailed report ---
echo Stopping old processes...
powershell -NoProfile -ExecutionPolicy Bypass -File "!SCRIPT_DIR!stop_ai_vtuber.ps1" -Root "!ROOT!" -PidFile "!PID_FILE!"
if errorlevel 1 (
    echo [WARNING] One or more cleanup operations failed. Review the report above.
) else (
    echo [OK] Old process cleanup finished.
)
timeout /t 2 /nobreak
echo.

REM --- Start Zonos TTS (port 8091) ---
set "HAS_ZONOS_VENV=0"
if exist "!ROOT!\tools\zonos\.venv\Scripts\python.exe" set "HAS_ZONOS_VENV=1"
if "!HAS_ZONOS_VENV!"=="1" (
    echo Starting Zonos TTS server...
    call :launch_component "!SCRIPT_DIR!08_start_zonos.bat"
    timeout /t 2 /nobreak >nul
) else (
    echo No Zonos venv found - skipping Zonos TTS.
)

REM --- Start Index-TTS (port 8090) ---
set "HAS_ITTS_VENV=0"
if exist "!ROOT!\tools\index-tts\.venv\Scripts\python.exe" set "HAS_ITTS_VENV=1"
if "!HAS_ITTS_VENV!"=="1" (
    echo Starting Index-TTS server...
    call :launch_component "!SCRIPT_DIR!09_start_indextts.bat"
    timeout /t 2 /nobreak >nul
) else (
    echo No Index-TTS venv found - skipping Index-TTS.
)

set "HAS_MODEL=0"
for %%F in ("!ROOT!\assets\models\gguf\*.gguf") do set "HAS_MODEL=1"

if "!HAS_MODEL!"=="1" (
    echo Starting llama.cpp server...
    call :launch_component "!SCRIPT_DIR!05_start_llamacpp.bat"
    timeout /t 3 /nobreak >nul
) else (
    echo No local GGUF found - skipping llama.cpp.
)

REM --- Start NVIDIA NeMo-Speech.cpp streaming ASR (port 8092) when installed ---
set "NEMO_MODEL=!ROOT!\assets\whisper\nemotron\nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
if not exist "!NEMO_MODEL!" set "NEMO_MODEL=!ROOT!\..\assets\whisper\nemotron\nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
set "NEMO_EXE=!ROOT!\tools\nemo-speech\nemo-speech.exe"
if not exist "!NEMO_EXE!" set "NEMO_EXE=!ROOT!\tools\nemo-speech\bin\nemo-speech.exe"
if not exist "!NEMO_EXE!" set "NEMO_EXE=!ROOT!\tools\nemo-speech.cpp\build\bin\nemo-speech.exe"
if not exist "!NEMO_EXE!" set "NEMO_EXE=!LOCALAPPDATA!\Programs\NeMoSpeech\bin\nemo-speech.exe"
if exist "!NEMO_MODEL!" (
    if exist "!NEMO_EXE!" (
        echo Starting NeMo-Speech.cpp streaming ASR...
        call :launch_component "!SCRIPT_DIR!10_start_nemo_speech.bat"
        timeout /t 2 /nobreak >nul
    ) else (
        echo Nemotron model found, but NeMo-Speech.cpp executable is missing - skipping sidecar.
        echo Install it with: powershell -ExecutionPolicy Bypass -File "!SCRIPT_DIR!install_nemo_speech.ps1"
    )
) else (
    echo Nemotron Q8_0 model not downloaded - skipping sidecar. Use STT settings to accept and download it.
)

echo Starting backend...
call :launch_component "!SCRIPT_DIR!06_start_backend.bat"

REM Wait for FastAPI to finish loading before opening the frontend. This avoids
REM an initial bridge WebSocket race while the backend is still starting.
echo Waiting for backend API...
set "BACKEND_READY=0"
for /L %%A in (1,1,30) do (
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/status' -TimeoutSec 1; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        set "BACKEND_READY=1"
        goto :backend_ready
    )
    timeout /t 1 /nobreak >nul
)
:backend_ready
if "!BACKEND_READY!"=="1" (
    echo Backend API is ready.
) else (
    echo Backend is still starting; the frontend will continue launching.
)

echo Starting frontend...
call :launch_component "!SCRIPT_DIR!07_start_frontend.bat"

echo Waiting for the web interface...
for /L %%A in (1,1,30) do (
    powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath 'http://localhost:5173' -ErrorAction Stop; exit 0 } catch { exit 1 }" >nul 2>&1
        if not errorlevel 1 (
            echo Opened AI VTuber in your default browser.
        ) else (
            start "" "http://localhost:5173"
            echo Requested AI VTuber in your default browser.
        )
        goto :frontend_ready
    )
    timeout /t 1 /nobreak >nul
)
echo Frontend is still starting. Opening the browser now; refresh once Vite finishes if needed.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath 'http://localhost:5173' -ErrorAction Stop } catch {}" >nul 2>&1

:frontend_ready
echo.
echo Open http://localhost:5173 in your browser.
echo The launcher is ready. Press any key to close this launcher window.
pause >nul
exit /b 0

:launch_component
set "AI_VTUBER_LAUNCH_TARGET=%~1"
set "AI_VTUBER_LAUNCH_ROOT=!ROOT!"
set "LAUNCH_PID="
echo [start] !AI_VTUBER_LAUNCH_TARGET!
for /f "delims=" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$args = '/k call ' + [char]34 + $env:AI_VTUBER_LAUNCH_TARGET + [char]34; $p = Start-Process -FilePath $env:ComSpec -ArgumentList $args -WorkingDirectory $env:AI_VTUBER_LAUNCH_ROOT -PassThru; $p.Id"') do (
    set "LAUNCH_PID=%%P"
    >>"!PID_FILE!" echo %%P
)
if defined LAUNCH_PID (
    echo [start] PID !LAUNCH_PID! recorded in !PID_FILE!
) else (
    echo [failed] Could not start !AI_VTUBER_LAUNCH_TARGET!
)
exit /b 0
