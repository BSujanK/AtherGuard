<#
.SYNOPSIS
  Registers (or removes) the Windows scheduled task "AetherGuard daily": the live run at 11:00 local time.

.DESCRIPTION
  The task runs  <project>\.venv\Scripts\python.exe -m aetherguard.live run --date today  with the project as the working
  directory and appends all output to  data\live\logs\<yyyy-MM-dd>.log.
  It starts after a missed time as soon as the laptop is available (StartWhenAvailable) and is restarted up to 3 times,
  30 minutes apart, when a run ends with a non-zero exit code (1 error; 3 = published but the rain of the IMD day could
  not be assembled yet, so a later attempt may fill the gap). The last attempt of a 11:00 start is 12:30.
  The time is the laptop's local time; the live run itself works on the IST date, so the laptop clock must be on IST.

.PARAMETER Remove   Unregister the task.
.PARAMETER DryRun   Print the task definition and change nothing.
.PARAMETER Time     Daily start time, HH:mm local (default 11:00).
.PARAMETER Execute  What the task itself runs: the live run with logging. Not for interactive use.
#>
[CmdletBinding()]
param(
    [switch]$Remove,
    [switch]$DryRun,
    [switch]$Execute,
    [ValidatePattern('^\d{2}:\d{2}$')][string]$Time = '11:00'
)

$ErrorActionPreference = 'Stop'
$TaskName = 'AetherGuard daily'
$Project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$LogDir = Join-Path $Project 'data\live\logs'
$Self = $MyInvocation.MyCommand.Path
$RunArguments = '-m aetherguard.live run --date today'
# A start on wake or logon fires before Wi-Fi reconnects; a run then finds every source unresolvable and publishes an
# unscored day (2026-11-08, 2026-11-09). So the task first waits for the name of the NASA archive to resolve.
$NetworkHost = 'cmr.earthdata.nasa.gov'
$NetworkWaitMinutes = 20

if ($Execute) {
    Set-Location $Project
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $log = Join-Path $LogDir ((Get-Date -Format 'yyyy-MM-dd') + '.log')
    $began = Get-Date
    $deadline = $began.AddMinutes($NetworkWaitMinutes)
    while ($true) {
        try { [System.Net.Dns]::GetHostAddresses($NetworkHost) | Out-Null; break } catch { }
        if ((Get-Date) -ge $deadline) {
            Add-Content -Path $log -Value "$(Get-Date -Format s) network wait: $NetworkHost did not resolve within $NetworkWaitMinutes minutes; running anyway"
            break
        }
        Start-Sleep -Seconds 30
    }
    $waited = [int]((Get-Date) - $began).TotalSeconds
    if ($waited -ge 30) {
        Add-Content -Path $log -Value "$(Get-Date -Format s) network wait: started the run after $waited s"
    }
    cmd.exe /c "`"$Python`" $RunArguments >> `"$log`" 2>&1"
    exit $LASTEXITCODE
}

$ActionArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Self`" -Execute"
$RestartCount = 3
$RestartMinutes = 30

if ($DryRun) {
    Write-Output "Task name:        $TaskName"
    Write-Output "Trigger:          daily at $Time local time, again 30, 60 and 90 minutes later (idempotent retries); catch-up at 18:00 and 10 minutes after logon"
    Write-Output "Action:           powershell.exe $ActionArguments"
    Write-Output "Runs:             `"$Python`" $RunArguments"
    Write-Output "Network wait:     up to $NetworkWaitMinutes minutes for $NetworkHost to resolve before the run"
    Write-Output "Working dir:      $Project"
    Write-Output "Log file:         $LogDir\<yyyy-MM-dd>.log"
    Write-Output "Settings:         StartWhenAvailable, RestartCount $RestartCount, RestartInterval $RestartMinutes minutes, ExecutionTimeLimit 2 hours"
    Write-Output "Remove with:      $Self -Remove"
    exit 0
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed the scheduled task '$TaskName'."
    } else {
        Write-Output "No scheduled task '$TaskName' to remove."
    }
    exit 0
}

if (-not (Test-Path $Python)) {
    throw "Project interpreter not found: $Python (create the virtual environment first)."
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $ActionArguments -WorkingDirectory $Project
# Task Scheduler's RestartOnFailure fires only when the action fails to launch, not on a non-zero exit code, so the
# retries are explicit extra triggers 30, 60 and 90 minutes after the start. The live run is idempotent: a completed
# day is skipped, a day published with exit code 3 (rain of the IMD day not yet assembled) is recomputed.
# Two catch-up starts cover what those retries cannot: an 18:00 run recomputes a day whose inputs were missing all
# morning (a source outage), and a run 10 minutes after logon finishes a day whose run was killed by a shutdown or
# restart (Task Scheduler does not count a killed run as missed, so StartWhenAvailable does not repeat it).
$start = [datetime]::ParseExact($Time, 'HH:mm', $null)
$trigger = @(0..$RestartCount | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $start.AddMinutes($_ * $RestartMinutes) })
$trigger += New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact('18:00', 'HH:mm', $null))
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = 'PT10M'
$trigger += $logon
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount $RestartCount `
    -RestartInterval (New-TimeSpan -Minutes $RestartMinutes) -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description 'AetherGuard live run: python -m aetherguard.live run --date today' | Out-Null
Write-Output "Registered '$TaskName': daily at $Time plus $RestartCount retry starts every $RestartMinutes minutes, catch-up at 18:00 and after logon, log in $LogDir."
