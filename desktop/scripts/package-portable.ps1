param(
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$projectRoot = (Resolve-Path (Join-Path $desktopRoot "..\")).Path
$releaseRoot = Join-Path $desktopRoot "src-tauri\target\release"
$application = Join-Path $releaseRoot "Vtubecord.exe"
$resources = Join-Path $releaseRoot "resources"
$portableRoot = Join-Path $releaseRoot "portable\Vtubecord"
$bundleRoot = Join-Path $releaseRoot "bundle"
$archive = Join-Path $bundleRoot ("Vtubecord_{0}_portable.zip" -f $Version)

if (-not (Test-Path -LiteralPath $application)) {
    throw "Vtubecord.exe was not found at $application. Build the desktop app first."
}
if (-not (Test-Path -LiteralPath $resources)) {
    throw "The packaged resources directory was not found at $resources. Build the desktop app first."
}

if (Test-Path -LiteralPath $portableRoot) {
    Remove-Item -LiteralPath $portableRoot -Recurse -Force
}
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null
New-Item -ItemType Directory -Path $bundleRoot -Force | Out-Null

Copy-Item -LiteralPath $application -Destination (Join-Path $portableRoot "Vtubecord.exe")
Copy-Item -LiteralPath $resources -Destination (Join-Path $portableRoot "resources") -Recurse
Copy-Item -LiteralPath (Join-Path $desktopRoot "PORTABLE_README.txt") -Destination (Join-Path $portableRoot "README.txt")

Compress-Archive -Path (Join-Path $portableRoot "*") -DestinationPath $archive -CompressionLevel Optimal
Write-Host "Portable package created: $archive"
