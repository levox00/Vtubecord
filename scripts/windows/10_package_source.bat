@echo off
setlocal EnableDelayedExpansion
title AI VTuber - Package Source Code

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"

echo ========================================
echo   AI VTuber - Package Source Code
echo ========================================
echo.

set "DATESTAMP=%DATE:~-4%%DATE:~3,2%%DATE:~0,2%"
set "TIMESTAMP=%TIME:~0,2%%TIME:~3,2%"
set "TIMESTAMP=%TIMESTAMP: =0%"
set "ZIP_NAME=ai-vtuber-src_%DATESTAMP%_%TIMESTAMP%.zip"
set "OUTPUT=!ROOT!\%ZIP_NAME%"

echo Creating: %ZIP_NAME%
echo From:     !ROOT!
echo.

REM Use PowerShell to create the zip (robust, handles long paths)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$src = '!ROOT!';" ^
    "$out = '!OUTPUT!';" ^
    "$excludeDirs = @('.venv','node_modules','.git','__pycache__','dist','build','logs','.comfy','outputs','.next','.turbo','.parcel-cache');" ^
    "$excludeFiles = @('*.gguf','*.bin','*.safetensors','*.ckpt','*.pt','*.pth','*.onnx','*.engine','*.zip','*.tar','*.7z','*.rar');" ^
    "" ^
    "$tempDir = Join-Path $env:TEMP ('ai-vtuber-pkg-' + [guid]::NewGuid().ToString('N').Substring(0,8));" ^
    "New-Item -ItemType Directory -Path $tempDir -Force | Out-Null;" ^
    "" ^
    "function Copy-Source($srcDir, $destDir, $relPath) {" ^
    "    foreach ($item in Get-ChildItem -Path $srcDir -ErrorAction SilentlyContinue) {" ^
    "        $name = $item.Name;" ^
    "        $skip = $false;" ^
    "        if ($item.PSIsContainer) {" ^
    "            if ($excludeDirs -contains $name) { $skip = $true }" ^
    "        } else {" ^
    "            foreach ($pat in $excludeFiles) {" ^
    "                if ($name -like $pat) { $skip = $true; break }" ^
    "            }" ^
    "        }" ^
    "        if ($skip) { continue }" ^
    "        $newRel = if ($relPath) { \"$relPath/$name\" } else { $name }" ^
    "        if ($item.PSIsContainer) {" ^
    "            $newDest = Join-Path $destDir $name;" ^
    "            New-Item -ItemType Directory -Path $newDest -Force | Out-Null;" ^
    "            Copy-Source $item.FullName $newDest $newRel;" ^
    "        } else {" ^
    "            $dest = Join-Path $destDir $name;" ^
    "            Copy-Item $item.FullName $dest -Force;" ^
    "        }" ^
    "    }" ^
    "}" ^
    "" ^
    "Write-Host 'Copying source files (excluding models, node_modules, venvs, .git)...';" ^
    "Copy-Source $src $tempDir '';" ^
    "" ^
    "Write-Host 'Creating zip archive...';" ^
    "Compress-Archive -Path (Join-Path $tempDir '*') -DestinationPath $out -Force;" ^
    "" ^
    "Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue;" ^
    "" ^
    "$size = (Get-Item $out).Length;" ^
    "if ($size -gt 1MB) { $sz = '{0:N1} MB' -f ($size/1MB) }" ^
    "else { $sz = '{0:N0} KB' -f ($size/1KB) }" ^
    "Write-Host ('' + [char]0x2714 + ' Created: ' + $out + ' (' + $sz + ')');"

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to create zip.
    pause
    exit /b 1
)

echo.
echo Output: !OUTPUT!
echo.
pause
exit /b 0
