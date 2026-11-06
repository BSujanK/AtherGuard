<#
.SYNOPSIS
  W3 steps that need the complete Late half-hourly store: edge days, the 2024 live-window (Early) build, the train-serve gap
  and the frozen iint feature tables.

.DESCRIPTION
  Run it only after the Late background build (aetherguard.ingest.imerg_hh --run late, June-September 2007-2017, then
  June-December 2018-2025; log logs\imerg_hh.log) has finished: it refuses to start while any imerg_hh process is running,
  because the half-hourly downloads share the 4-connection politeness limit. Each step stops the script on failure; every
  step is resumable, so run it again after fixing the cause.

  Steps (durations measured on the Late build's ~24 s per IMD day at 4 workers; the table steps are estimates)
    1. Edge days   Late 30-31 May of every year 2007-2025 (38 days, ~15 min). The three-day maxima of 1-2 June need them;
                   without them those two days are NaN. Skip with -SkipEdgeDays.
    2. Live window Early 2024-06-01..2024-12-31, first 44 half-hours of each day into data\processed\imerg_intensity\early_live
                   (214 days, ~1.3 h).
    3. Gap         median relative error of max3h, truncated Early vs complete Late, over the wet 2024 cell-days of the
                   season_2024 panel; applies the 20% rule; writes reports\phase7_rain_intensity_gap.json (~2 min).
    4. Tables      the frozen `iint` group next to the other IMERG groups in data\processed\features\imerg: the nine sample
                   tables and the 2018-2025 season panels (~10 min). Nothing already frozen is modified; an existing iint
                   build is verified and reused, -Force rebuilds it.

.PARAMETER SkipEdgeDays   Do not fetch 30-31 May.
.PARAMETER Force          Rebuild an existing frozen iint group.
#>
[CmdletBinding()]
param(
    [switch]$SkipEdgeDays,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$Project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Project '.venv\Scripts\python.exe'
Set-Location $Project

function Invoke-Step([string]$Name, [string[]]$Arguments) {
    Write-Host "== $Name"
    $started = Get-Date
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
    Write-Host ("== {0} done in {1:N1} min" -f $Name, ((Get-Date) - $started).TotalMinutes)
}

$running = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'aetherguard\.ingest\.imerg_hh' -and $_.ProcessId -ne $PID }
if ($running) {
    throw ("The half-hourly download is still running (pid {0}); wait for it to finish (logs\imerg_hh.log)." -f ($running.ProcessId -join ', '))
}

if (-not $SkipEdgeDays) {
    foreach ($year in 2007..2025) {
        Invoke-Step "Late edge days $year" @('-m', 'aetherguard.ingest.imerg_hh', '--run', 'late',
            '--start', "$year-05-30", '--end', "$year-05-31")
    }
}

Invoke-Step 'Early live-window build 2024' @('-m', 'aetherguard.ingest.imerg_hh', '--run', 'early', '--live-window',
    '--start', '2024-06-01', '--end', '2024-12-31')

Invoke-Step 'Train-serve gap 2024' @('-m', 'aetherguard.features.imerg_intensity', 'gap')

$tables = @('-m', 'aetherguard.features.imerg_intensity', 'tables')
if ($Force) { $tables += '--force' }
Invoke-Step 'iint feature tables' $tables

Write-Host 'W3 Task 2 data steps complete: reports\phase7_rain_intensity_gap.json and data\processed\features\imerg\iint_*'
