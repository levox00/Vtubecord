[CmdletBinding()]
param([string]$Root = "")

if ([string]::IsNullOrWhiteSpace($Root)) {
    $scriptRoot = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
        $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    $Root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
}

$ErrorActionPreference = "Stop"
$target = Join-Path $Root "tools\nemo-speech"
$installerUrl = "https://raw.githubusercontent.com/NVIDIA/NeMo-Speech.cpp/main/scripts/install.ps1"
$tempInstaller = Join-Path ([IO.Path]::GetTempPath()) ("nemo-speech-install-" + [guid]::NewGuid().ToString("N") + ".ps1")

New-Item -ItemType Directory -Force -Path $target | Out-Null
Write-Host "Installing NVIDIA NeMo-Speech.cpp (server profile, automatic GPU backend)..." -ForegroundColor Cyan
Write-Host "The official installer verifies release archives and falls back to a source build when needed." -ForegroundColor DarkGray

try {
    Invoke-WebRequest -UseBasicParsing -Uri $installerUrl -OutFile $tempInstaller
    & $tempInstaller -Prefix $target -Backend auto -Profile server -NoModifyPath
    if ($LASTEXITCODE -ne 0) {
        throw "The NeMo-Speech.cpp installer exited with code $LASTEXITCODE."
    }

    $executable = Join-Path $target "bin\nemo-speech.exe"
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Installation completed without $executable."
    }
    Write-Host "NeMo-Speech.cpp is ready at $executable" -ForegroundColor Green
    Write-Host "Restart START.bat so the backend can detect the new executable." -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $tempInstaller -Force -ErrorAction SilentlyContinue
}
