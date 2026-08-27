param(
    [string]$ServerExecutable = "",
    [string]$GithubRepository = $env:VTUBECORD_GITHUB_REPOSITORY
)

$ErrorActionPreference = "Stop"
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$projectRoot = (Resolve-Path (Join-Path $desktopRoot "..\")).Path
$resourceDir = Join-Path $desktopRoot "src-tauri\resources"

New-Item -ItemType Directory -Path $resourceDir -Force | Out-Null

$backendPython = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"

if (-not $ServerExecutable) {
    $ServerExecutable = Join-Path $projectRoot "backend\dist\VtubecordServer.exe"
    if (-not (Test-Path -LiteralPath $ServerExecutable)) {
        $ServerExecutable = Join-Path $projectRoot "dist\VtubecordServer\VtubecordServer.exe"
    }
}

if (-not (Test-Path -LiteralPath $ServerExecutable)) {
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw "VtubecordServer.exe is missing and backend/.venv is not available. Run SETUP.bat first or pass -ServerExecutable."
    }
    & $backendPython -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing PyInstaller into the packaging environment..."
        & $backendPython -m pip install "pyinstaller>=6.10.0"
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not be installed." }
    }
    Write-Host "Packaging FastAPI backend..."
    & $backendPython -m PyInstaller --noconfirm --clean --onefile --noconsole `
        --name VtubecordServer --distpath (Join-Path $projectRoot "backend\dist") `
        --workpath (Join-Path $projectRoot "backend\build") --specpath (Join-Path $projectRoot "backend\build") `
        --paths (Join-Path $projectRoot "backend") --collect-submodules app `
        --hidden-import aiosqlite --hidden-import aiosqlite.core --hidden-import aiosqlite.cursor `
        (Join-Path $projectRoot "backend\desktop_server.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
    $ServerExecutable = Join-Path $projectRoot "backend\dist\VtubecordServer.exe"
}

$updaterExecutable = Join-Path $resourceDir "VtubecordUpdater.exe"
if (-not (Test-Path -LiteralPath $updaterExecutable)) {
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw "VtubecordUpdater.exe is missing and backend/.venv is not available. Run SETUP.bat first."
    }
    & $backendPython -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing PyInstaller into the packaging environment..."
        & $backendPython -m pip install "pyinstaller>=6.10.0"
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not be installed." }
    }
    Write-Host "Packaging Vtubecord updater..."
    $updaterDist = Join-Path $projectRoot "desktop\updater\dist"
    $updaterBuild = Join-Path $projectRoot "desktop\updater\build"
    & $backendPython -m PyInstaller --noconfirm --clean --onefile --noconsole `
        --name VtubecordUpdater --distpath $updaterDist --workpath $updaterBuild `
        --specpath $updaterBuild (Join-Path $projectRoot "desktop\updater\VtubecordUpdater.py")
    if ($LASTEXITCODE -ne 0) { throw "Vtubecord updater packaging failed with exit code $LASTEXITCODE." }
    $updaterExecutable = Join-Path $updaterDist "VtubecordUpdater.exe"
}
Copy-Item -LiteralPath $updaterExecutable -Destination (Join-Path $resourceDir "VtubecordUpdater.exe") -Force

$appVersion = "0.1.0"
$tauriConfigPath = Join-Path $desktopRoot "src-tauri\tauri.conf.json"
if (Test-Path -LiteralPath $tauriConfigPath) {
    try {
        $tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
        if ($tauriConfig.version) { $appVersion = [string]$tauriConfig.version }
    } catch {
        Write-Warning "Could not read the Tauri version from $tauriConfigPath; using $appVersion."
    }
}

$repoValue = if ($GithubRepository) { $GithubRepository.Trim() } else { "" }
if (-not $repoValue) {
    try {
        $remote = (& git -C $projectRoot config --get remote.origin.url 2>$null | Select-Object -First 1)
        if ($remote) {
            $repoValue = ([string]$remote).Trim()
                -replace '^https?://github\.com/', ''
                -replace '^git@github\.com:', ''
                -replace '\.git$', ''
                -replace '/$', ''
        }
    } catch {
        # A local source checkout may intentionally have no GitHub remote.
    }
}
$updateConfig = @{
    repository = $repoValue
    current_version = $appVersion
} | ConvertTo-Json
$updateConfig | Set-Content -LiteralPath (Join-Path $resourceDir "update-config.json") -Encoding UTF8

if (Test-Path -LiteralPath $ServerExecutable) {
    Copy-Item -LiteralPath $ServerExecutable -Destination (Join-Path $resourceDir "VtubecordServer.exe") -Force
    Write-Host "Bundling backend: $ServerExecutable"
} else {
    Write-Warning "VtubecordServer.exe was not found. The installer will build, but the installed app will need the server binary in its resources."
}

Push-Location $desktopRoot
try {
    npm run build
} finally {
    Pop-Location
}
