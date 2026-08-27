param(
    [string]$ServerExecutable = ""
)

$ErrorActionPreference = "Stop"
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$projectRoot = (Resolve-Path (Join-Path $desktopRoot "..\")).Path
$resourceDir = Join-Path $desktopRoot "src-tauri\resources"

New-Item -ItemType Directory -Path $resourceDir -Force | Out-Null

if (-not $ServerExecutable) {
    $ServerExecutable = Join-Path $projectRoot "backend\dist\VtubecordServer.exe"
    if (-not (Test-Path -LiteralPath $ServerExecutable)) {
        $ServerExecutable = Join-Path $projectRoot "dist\VtubecordServer\VtubecordServer.exe"
    }
}

if (-not (Test-Path -LiteralPath $ServerExecutable)) {
    $backendPython = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
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
