<#
.SYNOPSIS
  Starts the AetherGuard dashboard: builds the React app if needed, starts the API on 127.0.0.1:8790 and opens the browser.

.DESCRIPTION
  1. Builds dashboard\dist (npm ci when node_modules is missing, then npm run build) when dist is missing or older than
     the dashboard sources.
  2. If http://127.0.0.1:<Port>/api/mode already answers, something is serving the dashboard: it is left alone and only
     the browser is opened.
  3. Otherwise starts  <project>\.venv\Scripts\python.exe -m aetherguard.serve.api --port <Port>  hidden (it binds
     127.0.0.1 only), records its process id in  data\run\dashboard.pid, waits until /api/mode answers, then opens the
     default browser. API output goes to  logs\dashboard_api.out.log  and  logs\dashboard_api.err.log.

  -Stop stops only the API process this script started (the one in the pid file) and its child processes. It refuses
  to stop a process whose command line is not the dashboard API, so a recycled pid is never touched.

.PARAMETER Stop        Stop the API this script started.
.PARAMETER Port        API port (default 8790).
.PARAMETER NoBrowser   Do not open the browser.
.PARAMETER Serve       Build if needed, then run the API in the foreground (what the scheduled task "AetherGuard dashboard"
                       runs at logon). When that task exists, a plain start starts the task and -Stop stops it.
.PARAMETER TimeoutSeconds  How long to wait for the API to answer (default 90).
#>
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$NoBrowser,
    [switch]$Serve,
    [ValidateRange(1024, 65535)][int]$Port = 8790,
    [ValidateRange(5, 600)][int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$Project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Dashboard = Join-Path $Project 'dashboard'
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$PidFile = Join-Path $Project 'data\run\dashboard.pid'
$LogDir = Join-Path $Project 'logs'
$Url = "http://127.0.0.1:$Port/"
$ApiMarker = 'aetherguard.serve.api'

function Test-Api {
    try {
        $null = Invoke-RestMethod -Uri "${Url}api/mode" -TimeoutSec 3
        return $true
    } catch {
        return $false
    }
}

function Get-ProcessCommandLine([int]$ProcessId) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($info) { return [string]$info.CommandLine }
    return $null
}

function Stop-ProcessTree([int]$RootId) {
    # The venv's python.exe may start the real interpreter as a child, so stop descendants first.
    foreach ($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootId" -ErrorAction SilentlyContinue)) {
        Stop-ProcessTree -RootId ([int]$child.ProcessId)
    }
    Stop-Process -Id $RootId -Force -ErrorAction SilentlyContinue
}

$TaskName = 'AetherGuard dashboard'
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Stop -and $Task) {
    # The scheduled task owns the server (it runs this script with -Serve): stopping the task ends the server.
    if ($Task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Output "Stopped the scheduled task '$TaskName'."
    } else {
        Write-Output "The scheduled task '$TaskName' is not running."
    }
    # The venv's python.exe runs the real interpreter as a child, which outlives the task: stop the process that
    # listens on the port, and its launcher, but only when its command line is the dashboard API.
    foreach ($conn in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        $owner = [int]$conn.OwningProcess
        $line = Get-ProcessCommandLine -ProcessId $owner
        if ($line -like "*$ApiMarker*") {
            $parent = (Get-CimInstance Win32_Process -Filter "ProcessId = $owner" -ErrorAction SilentlyContinue).ParentProcessId
            if ($parent -and ((Get-ProcessCommandLine -ProcessId ([int]$parent)) -like "*$ApiMarker*")) { Stop-ProcessTree -RootId ([int]$parent) }
            Stop-ProcessTree -RootId $owner
            Write-Output "Stopped the dashboard server listening on port $Port (pid $owner)."
        } elseif ($line) {
            Write-Output "Port $Port is held by another program (pid $owner); left alone."
        }
    }
}

if ($Stop) {
    if (-not (Test-Path $PidFile)) {
        Write-Output "No dashboard API was started by this script (no $PidFile)."
        exit 0
    }
    $recorded = [int](Get-Content $PidFile -TotalCount 1)
    $commandLine = Get-ProcessCommandLine -ProcessId $recorded
    if ($null -eq $commandLine) {
        Write-Output "The dashboard API (pid $recorded) is no longer running."
    } elseif ($commandLine -notlike "*$ApiMarker*") {
        Write-Error "Pid $recorded is not the dashboard API (command line: $commandLine); leaving it alone and keeping $PidFile."
        exit 1
    } else {
        Stop-ProcessTree -RootId $recorded
        Write-Output "Stopped the dashboard API (pid $recorded)."
    }
    Remove-Item $PidFile -Force
    exit 0
}

function Test-BuildNeeded {
    $built = Join-Path $Dashboard 'dist\index.html'
    if (-not (Test-Path $built)) { return $true }
    $sources = @(Get-ChildItem (Join-Path $Dashboard 'src'), (Join-Path $Dashboard 'public') -Recurse -File)
    $sources += Get-Item (Join-Path $Dashboard 'index.html'), (Join-Path $Dashboard 'package.json'), (Join-Path $Dashboard 'vite.config.ts')
    $newest = ($sources | Measure-Object -Property LastWriteTime -Maximum).Maximum
    return $newest -gt (Get-Item $built).LastWriteTime
}

if (Test-BuildNeeded) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Error 'The dashboard must be built but npm was not found on PATH. Install Node.js, then run this script again.'
        exit 1
    }
    Push-Location $Dashboard
    try {
        if (-not (Test-Path 'node_modules')) {
            Write-Output 'Installing dashboard packages (npm ci)...'
            npm ci
            if ($LASTEXITCODE -ne 0) { Write-Error "npm ci failed (exit code $LASTEXITCODE)."; exit 1 }
        }
        Write-Output 'Building the dashboard (npm run build)...'
        npm run build
        if ($LASTEXITCODE -ne 0) {
            if ($Serve -and (Test-Path (Join-Path $Dashboard 'dist\index.html'))) {
                Write-Warning "npm run build failed (exit code $LASTEXITCODE); serving the previous build."
            } else {
                Write-Error "npm run build failed (exit code $LASTEXITCODE)."; exit 1
            }
        }
    } finally {
        Pop-Location
    }
}

if ($Serve) {
    # Foreground server for the scheduled task: Task Scheduler supervises this process (no time limit, restarted on
    # failure), so the server lives as long as the task instead of being ended with a launcher.
    if (Test-Api) { Write-Output "Something already answers on $Url; not starting a second server."; exit 0 }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Set-Location $Project
    # cmd does the redirection: Windows PowerShell turns a native program's stderr (uvicorn logs there) into
    # error records, which $ErrorActionPreference = 'Stop' would make fatal.
    $out = Join-Path $LogDir 'dashboard_api.out.log'
    $err = Join-Path $LogDir 'dashboard_api.err.log'
    cmd.exe /c "`"$Python`" -m $ApiMarker --port $Port >> `"$out`" 2>> `"$err`""
    exit $LASTEXITCODE
}

if ((-not (Test-Api)) -and $Task) {
    Start-ScheduledTask -TaskName $TaskName
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (Test-Api)) {
        if ((Get-Date) -gt $deadline) {
            Write-Error "The scheduled task '$TaskName' did not bring the dashboard up within $TimeoutSeconds s; see logs\dashboard_api.err.log."
            exit 1
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Output "Dashboard started by the scheduled task '$TaskName' on $Url ; stop it with: scripts\start_dashboard.ps1 -Stop"
} elseif (Test-Api) {
    Write-Output "Something already answers on $Url; leaving it alone."
} else {
    if (-not (Test-Path $Python)) {
        Write-Error "Project Python not found at $Python. Create the virtual environment first (see README)."
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $LogDir, (Split-Path $PidFile) | Out-Null
    $process = Start-Process -FilePath $Python -ArgumentList '-m', $ApiMarker, '--port', $Port `
        -WorkingDirectory $Project -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir 'dashboard_api.out.log') `
        -RedirectStandardError (Join-Path $LogDir 'dashboard_api.err.log')
    Set-Content -Path $PidFile -Value $process.Id -Encoding ascii
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (Test-Api)) {
        if ($process.HasExited) {
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
            Write-Error "The dashboard API exited with code $($process.ExitCode); see logs\dashboard_api.err.log."
            exit 1
        }
        if ((Get-Date) -gt $deadline) {
            Stop-ProcessTree -RootId $process.Id
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
            Write-Error "The dashboard API did not answer within $TimeoutSeconds s; stopped it. See logs\dashboard_api.err.log."
            exit 1
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Output "Dashboard API started (pid $($process.Id)) on $Url ; stop it with: scripts\start_dashboard.ps1 -Stop"
}

if (-not $NoBrowser) { Start-Process $Url }
