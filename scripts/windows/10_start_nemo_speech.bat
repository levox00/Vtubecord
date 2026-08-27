@echo off
setlocal EnableExtensions
title AI VTuber - NeMo Speech.cpp ASR

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "MODEL=%ROOT%\assets\whisper\nemotron\nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
if not exist "%MODEL%" set "MODEL=%ROOT%\..\assets\whisper\nemotron\nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
set "EXE=%ROOT%\tools\nemo-speech\nemo-speech.exe"
if not exist "%EXE%" set "EXE=%ROOT%\tools\nemo-speech.cpp\build\bin\nemo-speech.exe"
if not exist "%EXE%" set "EXE=%LOCALAPPDATA%\Programs\NeMoSpeech\bin\nemo-speech.exe"
if not exist "%EXE%" set "EXE=nemo-speech"

if not exist "%MODEL%" (
  echo [nemo] Default Q8_0 model is not downloaded yet.
  echo [nemo] Accept the license and download it from Settings ^> Speech-to-text.
  exit /b 0
)
where "%EXE%" >nul 2>&1
if errorlevel 1 if not exist "%EXE%" (
  echo [nemo] NeMo-Speech.cpp executable was not found.
  echo [nemo] Run powershell -ExecutionPolicy Bypass -File scripts\windows\install_nemo_speech.ps1, then restart.
  exit /b 0
)

echo [nemo] Model: %MODEL%
echo [nemo] Runtime: NeMo-Speech.cpp | CUDA device: 0 | port: 8092 | chunk: 320 ms
"%EXE%" serve --host 127.0.0.1 --port 8092 --asr-model "%MODEL%" --asr.backend.gpu 0 --asr.streaming.rnnt_right_context 3
