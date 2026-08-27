param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [string]$PidFile
)

$ErrorActionPreference = "Continue"
$script:Failures = 0
$script:Stopped = New-Object 'System.Collections.Generic.HashSet[int]'
$script:Protected = New-Object 'System.Collections.Generic.HashSet[int]'

function Write-Status {
    param(
        [string]$Kind,
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )
    Write-Host ("[{0}] {1}" -f $Kind, $Message) -ForegroundColor $Color
}

Write-Host ""
Write-Host "=== AI VTuber process cleanup ===" -ForegroundColor Cyan
Write-Status "info" ("Root: {0}" -f $Root)
Write-Status "info" ("PID file: {0}" -f $PidFile)

# Protect this launcher and its parent cmd.exe so a broad process match cannot
# terminate the cleanup script itself. Parent discovery can be restricted on
# some Windows policies; in that case launcher command lines are skipped too.
[void]$script:Protected.Add([int]$PID)
$parentInspectionAvailable = $false
try {
    $cursor = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $PID) -ErrorAction Stop
    for ($depth = 0; $cursor -and $depth -lt 4; $depth++) {
        $parentId = [int]$cursor.ParentProcessId
        if ($parentId -le 0) { break }
        [void]$script:Protected.Add($parentId)
        $parentInspectionAvailable = $true
        $cursor = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $parentId) -ErrorAction Stop
    }
    Write-Status "info" ("Protected process IDs: {0}" -f (($script:Protected | Sort-Object) -join ", "))
} catch {
    Write-Status "warn" "Could not inspect the launcher parent chain; launcher command lines will be protected by name." Yellow
}

function Stop-Candidate {
    param(
        [int]$Id,
        [string]$Reason
    )

    if ($Id -le 0 -or $script:Protected.Contains($Id)) {
        if ($Id -gt 0) { Write-Status "skip" ("PID {0} is protected ({1})" -f $Id, $Reason) DarkYellow }
        return
    }
    if ($script:Stopped.Contains($Id)) {
        return
    }

    $process = Get-Process -Id $Id -ErrorAction SilentlyContinue
    if (-not $process) {
        Write-Status "skip" ("PID {0} is no longer running ({1})" -f $Id, $Reason) DarkGray
        [void]$script:Stopped.Add($Id)
        return
    }

    $title = if ($process.MainWindowTitle) { $process.MainWindowTitle } else { "(no window title)" }
    Write-Status "found" ("PID {0} | {1} | title: {2} | reason: {3}" -f $Id, $process.ProcessName, $title, $Reason) White
    $stopError = $null
    try {
        Stop-Process -Id $Id -Force -ErrorAction Stop
    } catch {
        $stopError = $_.Exception.Message
    }
    Start-Sleep -Milliseconds 200

    if (Get-Process -Id $Id -ErrorAction SilentlyContinue) {
        # Some native servers (notably llama-server) do not exit when the
        # PowerShell process-stop request reaches only the wrapper. Ask
        # taskkill to terminate the process tree as a second pass.
        Write-Status "retry" ("PID {0} is still running; trying taskkill /T /F" -f $Id) Yellow
        $taskkillOutput = @(& taskkill.exe /PID $Id /T /F 2>&1)
        Start-Sleep -Milliseconds 250
        if (Get-Process -Id $Id -ErrorAction SilentlyContinue) {
            $script:Failures++
            $detail = if ($stopError) { "Stop-Process: $stopError" } else { "Stop-Process did not close it" }
            $taskkillDetail = ($taskkillOutput -join " ").Trim()
            if ($taskkillDetail) { $detail = "$detail; taskkill: $taskkillDetail" }
            Write-Status "failed" ("PID {0} is still running ({1})" -f $Id, $detail) Red
        } else {
            Write-Status "stopped" ("PID {0} closed by taskkill" -f $Id) Green
        }
    } elseif ($stopError) {
        Write-Status "stopped" ("PID {0} closed after Stop-Process reported: {1}" -f $Id, $stopError) Green
    } else {
        Write-Status "stopped" ("PID {0} closed" -f $Id) Green
    }
    [void]$script:Stopped.Add($Id)
}

function Get-ListeningProcessIds {
    param([int]$Port)

    $ids = New-Object System.Collections.Generic.List[int]
    try {
        # An empty Get-NetTCPConnection result is normal; do not use
        # -ErrorAction Stop because Windows reports that case as a CIM error.
        $connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($connection in $connections) {
            $owner = [int]$connection.OwningProcess
            if ($owner -gt 0 -and -not $ids.Contains($owner)) { [void]$ids.Add($owner) }
        }
    } catch {
        # Fall through to netstat below.
    }

    # netstat is a reliable fallback on older Windows builds and when the
    # NetTCPIP CIM provider is unavailable or restricted.
    if ($ids.Count -eq 0) {
        $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
        foreach ($line in @(netstat.exe -ano -p tcp 2>$null | Select-String -Pattern $pattern)) {
            if ($line.Line -match $pattern) {
                $owner = [int]$Matches[1]
                if ($owner -gt 0 -and -not $ids.Contains($owner)) { [void]$ids.Add($owner) }
            }
        }
    }
    return @($ids | Sort-Object -Unique)
}

# First close the exact cmd.exe wrappers recorded by the previous launcher.
if (Test-Path -LiteralPath $PidFile) {
    $pidLines = @(Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\d+$' })
    if ($pidLines.Count -eq 0) {
        Write-Status "info" "PID file exists but contains no process IDs" DarkGray
    } else {
        foreach ($line in $pidLines) {
            Stop-Candidate -Id ([int]$line) -Reason "previous launcher PID file"
        }
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Status "info" "No previous launcher PID file found" DarkGray
}

# Close visible AI VTuber console windows, including old launchers. The
# protected parent chain keeps the current START.bat/START_ALL.bat window safe.
$windowCandidates = @(Get-Process -Name cmd -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -like "AI VTuber -*"
})
$fallbackLauncherId = $null
if (-not $parentInspectionAvailable) {
    $fallbackLauncher = $windowCandidates |
        Where-Object { $_.MainWindowTitle -like "*Start All*" } |
        Sort-Object StartTime -Descending |
        Select-Object -First 1
    if ($fallbackLauncher) {
        $fallbackLauncherId = [int]$fallbackLauncher.Id
        Write-Status "info" ("Parent identity unavailable; treating newest Start All window (PID {0}) as the current launcher" -f $fallbackLauncherId) Yellow
    }
}
if ($windowCandidates.Count -eq 0) {
    Write-Status "info" "No AI VTuber console windows found" DarkGray
} else {
    foreach ($process in $windowCandidates) {
        if ($fallbackLauncherId -and $process.Id -eq $fallbackLauncherId) {
            Write-Status "skip" ("PID {0} title '{1}' is treated as the current launcher" -f $process.Id, $process.MainWindowTitle) DarkYellow
            continue
        }
        Stop-Candidate -Id $process.Id -Reason ("window title '{0}'" -f $process.MainWindowTitle)
    }
}

# Close project-owned server processes that may have lost their console window.
$rootPattern = [regex]::Escape($Root)
$commandPattern = "(?i)($rootPattern.*(05_start_llamacpp|06_start_backend|07_start_frontend|08_start_zonos|09_start_indextts|10_start_nemo_speech|uvicorn|vite|npm|llama|nemo-speech)|tools[\\/]zonos|tools[\\/]index-tts|tools[\\/]nemo-speech|nemo-speech|llama-server)"
try {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $commandCandidates = @($processes | Where-Object {
        $_.ProcessId -notin $script:Protected -and
        $_.CommandLine -and
        $_.CommandLine -match $commandPattern -and
        ($parentInspectionAvailable -or $_.CommandLine -notmatch '(?i)START(?:_ALL)?\.bat')
    })
    if ($commandCandidates.Count -eq 0) {
        Write-Status "info" "No project-owned command-line processes found" DarkGray
    } else {
        foreach ($process in $commandCandidates) {
            Stop-Candidate -Id ([int]$process.ProcessId) -Reason ("command line match: {0}" -f $process.CommandLine)
        }
    }
} catch {
    $script:Failures++
    Write-Status "failed" ("Could not inspect process command lines: {0}" -f $_.Exception.Message) Red
}

# Finally report and stop anything listening on the services' ports.
$ports = @(8000, 8081, 8090, 8091, 8092, 5173)
foreach ($port in $ports) {
    $listenerIds = @(Get-ListeningProcessIds -Port $port)
    if ($listenerIds.Count -eq 0) {
        Write-Status "info" ("Port {0}: no listener found" -f $port) DarkGray
    } else {
        foreach ($listenerId in $listenerIds) {
            Stop-Candidate -Id ([int]$listenerId) -Reason ("listener on port {0}" -f $port)
        }
    }
}

if ($script:Failures -gt 0) {
    Write-Status "summary" ("Cleanup completed with {0} failure(s). See the detailed entries above." -f $script:Failures) Red
    exit 1
}
Write-Status "summary" "Cleanup completed successfully; every discovered target was stopped or already gone." Green
exit 0
