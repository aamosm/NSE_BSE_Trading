# Register MarketLab tasks for the current Windows user (no administrator rights needed).
# Run once from the project folder:   powershell -ExecutionPolicy Bypass -File deploy\windows\register_tasks.ps1
# Remove later with:                  powershell -File deploy\windows\register_tasks.ps1 -Remove
#
# Tasks (all as you, only while you are logged on; none can place orders):
#   MarketLab Scheduler  - `marketlab run` at logon and daily 07:55 IST; missed starts run as soon as possible.
#   MarketLab App        - the private app on http://127.0.0.1:8765 at logon.
#   MarketLab Research   - `marketlab research-run --loop` at logon (separate process; budget-capped).
# The daily Kite login stays manual: open the app or run `marketlab auth` at about 08:00.
param(
  [string]$Symbols = "NSE:INFY NSE:TCS NSE:HDFCBANK NSE:ITC NSE:ONGC",
  [switch]$NoResearch,
  [switch]$WakeToRun,
  [switch]$Remove
)
$ErrorActionPreference = "Stop"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Project ".venv\Scripts\python.exe"
$Names = @("MarketLab Scheduler", "MarketLab App", "MarketLab Research")

if ($Remove) {
  foreach ($n in $Names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue }
  Write-Output "MarketLab tasks removed."
  return
}
if (-not (Test-Path $Python)) { throw "Virtual environment not found at $Python; create it first (docs/KITE_AND_SERVER_SETUP.md)" }

$User = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if ($WakeToRun) { $Settings.WakeToRun = $true }  # also requires "Allow wake timers" in the power plan

function Register-MarketLabTask([string]$Name, [string]$Arguments, $Triggers) {
  $Action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Project
  Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Triggers -Principal $Principal -Settings $Settings `
    -Description "MarketLab (research only; no order capability). Project: $Project" -Force | Out-Null
  Write-Output "Registered: $Name"
}

$AtLogon = New-ScheduledTaskTrigger -AtLogOn -User $User
# 07:55 India time. Windows triggers use the machine clock; this assumes the laptop clock is set to IST.
$Morning = New-ScheduledTaskTrigger -Daily -At "07:55"
Register-MarketLabTask "MarketLab Scheduler" "-m marketlab run --symbols $Symbols" @($AtLogon, $Morning)
Register-MarketLabTask "MarketLab App" "-m marketlab dashboard" @($AtLogon)
if (-not $NoResearch) {
  Register-MarketLabTask "MarketLab Research" "-m marketlab research-run --loop --interval 30" @($AtLogon)
}
Write-Output "Done. Check with: Get-ScheduledTask -TaskName 'MarketLab*' | Format-Table TaskName, State"
