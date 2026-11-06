<#
.SYNOPSIS
  W3 steps that need the complete Late half-hourly store: edge days, the 2024 live-window (Early) build, the train-serve gap
  and the frozen iint feature tables.

.DESCRIPTION
  Run it only after the Late background builds (aetherguard.ingest.imerg_hh --run late: all months of 2007-2017 and
  June-December 2018-2025; log logs\imerg_hh.log) have finished: it refuses to start while any imerg_hh process is running,
  because the half-hourly downloads share the 4-connection politeness limit. Each step stops the script on failure; every
  step is resumable, so run it again after fixing the cause.

  Steps (durations measured on the Late build's ~24 s per IMD day at 4 workers; the table steps are estimates)
    1. Edge days   Late 22-31 May of 2018-2025 in one process (80 days, ~35 min): the season panels start 7 warm-up days
                   before 1 June (25 May); their three-day maxima need 23-24 May, and a lag-1 build (declared by the gap) 22-24 May. 2007-2017 are complete.
                   Skip with -SkipEdgeDays.
    2. Live window Early 2024-06-01..2024-12-31, first 44 half-hours of each day into data\processed\imerg_intensity\early_live
                   (214 days, ~1.3 h).
    3. Gap         median relative error of max3h, truncated Early vs complete Late, over the wet 2024 cell-days of the
                   season_2024 panel; applies the 20% rule; writes reports\phase7_rain_intensity_gap.json (~2 min).
                   Fails (writes nothing) when any 2024 June-December day is missing in either store.
    4. Tables      the frozen `iint` group (`iint_lag1` when the gap declares lag 1; the lag is read from the gap report) next to the other IMERG groups in data\processed\features\imerg: the nine sample
                   tables and the 2018-2025 season panels (~10 min). Fails, listing the days, when a Late day needed by a
                   development row or a season panel day (window D-2..D) is missing; --allow-missing is deliberately not
                   passed. Nothing already frozen is modified; an existing iint build is verified and reused, -Force rebuilds it.

.PARAMETER SkipEdgeDays   Do not fetch 22-31 May of 2018-2025.
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
    Invoke-Step 'Late edge days 22-31 May 2018-2025' @('-m', 'aetherguard.ingest.imerg_hh', '--run', 'late',
        '--start', '2018-05-22', '--end', '2025-05-31', '--days', '05-22:05-31')
}

Invoke-Step 'Early live-window build 2024' @('-m', 'aetherguard.ingest.imerg_hh', '--run', 'early', '--live-window',
    '--start', '2024-06-01', '--end', '2024-12-31')

Invoke-Step 'Train-serve gap 2024' @('-m', 'aetherguard.features.imerg_intensity', 'gap')

$tables = @('-m', 'aetherguard.features.imerg_intensity', 'tables')
if ($Force) { $tables += '--force' }
Invoke-Step 'iint feature tables' $tables

Write-Host 'W3 Task 2 data steps complete: reports\phase7_rain_intensity_gap.json and data\processed\features\imerg\iint_*'
