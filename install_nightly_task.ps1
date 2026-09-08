# Register the nightly test run with Windows Task Scheduler. RUN THIS ONCE,
# BY HAND, and read it first -- it is the only file in this repo that changes
# the machine rather than the app.
#
#     powershell -ExecutionPolicy Bypass -File .\install_nightly_task.ps1
#     powershell -ExecutionPolicy Bypass -File .\install_nightly_task.ps1 -WhatIf
#     powershell -ExecutionPolicy Bypass -File .\install_nightly_task.ps1 -Remove
#
# WHAT IT WILL DO. It creates one scheduled task, "DeskIT Nightly Tests",
# modelled line for line on the one that is already there ("DeskIT Weekly
# Report Review", read off this machine on 2026-09-08):
#
#   * daily at 02:55, one trigger, no repetition;
#   * powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass
#     -WindowStyle Hidden -File "<repo>\nightly_tests.ps1", with the repo as
#     the working directory -- the same six switches the weekly task uses;
#   * as YOU, at Interactive logon type and Limited run level. Interactive is
#     not a detail: the run puts a question on your desktop and the suite's
#     last sixteen tests photograph the screen and move the real mouse, none of
#     which a session-0 service can do;
#   * MultipleInstances = IgnoreNew, so a second fire while one is going is
#     dropped rather than queued;
#   * a two-hour execution limit, which is a backstop and not a schedule: the
#     whole suite takes about four minutes.
#
# WHAT IT DELIBERATELY DOES NOT DO.
#
#   * StartWhenAvailable is OFF, and this is the important one. The weekly
#     review has it on, because a review that happens at nine in the morning is
#     still a review. A TEST RUN THAT HAPPENS AT NINE IN THE MORNING TAKES YOUR
#     MOUSE. If the machine was off at 02:55 the night is simply skipped, which
#     is the right answer: the whole feature exists because the sixteen screen
#     tests can only run when nobody is here.
#   * -NoWake turns off WakeToRun. It ships ON, matching the weekly task, and
#     because DeskIT holds the machine awake while it runs anyway. Pass -NoWake
#     if you would rather a sleeping computer stay asleep and skip the night.
#   * It does not touch the weekly task, and it does not need an administrator:
#     a task that runs as you, at Interactive logon type, is yours to register.
#
# AFTER IT RUNS, to see the thing work without staying up until three:
#
#     powershell -ExecutionPolicy Bypass -File .\nightly_tests.ps1 -Now
#
# which skips the question and runs the suite -- so do that when you are not
# using the machine, because it will take the mouse for about fifteen seconds.
# The card itself, with its five-minute clock, is
# `.venv\Scripts\python.exe nightly.py`.
#
# Windows PowerShell 5.1: no &&, no ternary, no ??.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Remove,
    [switch]$NoWake,
    [string]$At = '02:55',
    [string]$TaskName = 'DeskIT Nightly Tests'
)

$ErrorActionPreference = 'Stop'

$Repo   = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$Script = Join-Path $Repo 'nightly_tests.ps1'

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "There is no task called '$TaskName'. Nothing to remove."
        exit 0
    }
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister the scheduled task')) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed '$TaskName'. The nightly run will not fire again."
        Write-Host "Nothing else changed: nightly.py, the setting and the log are all still there."
    }
    exit 0
}

if (-not (Test-Path -PathType Leaf $Script)) {
    Write-Error "nightly_tests.ps1 is not beside this file ($Script). Run this from the repo."
    exit 1
}

# The time is parsed rather than pasted into a string, so a typo is refused
# here instead of registering a task that fires at midnight.
try {
    $when = [datetime]::ParseExact($At, 'HH:mm', $null)
} catch {
    Write-Error "-At wants a 24-hour time like 02:55, got '$At'."
    exit 1
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ("-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`"") `
    -WorkingDirectory $Repo

$trigger = New-ScheduledTaskTrigger -Daily -At $when

# StartWhenAvailable is NOT set -- see the header. A missed night is a missed
# night, and that is much better than a suite that takes the mouse at breakfast.
$settingsArgs = @{
    MultipleInstances  = 'IgnoreNew'
    ExecutionTimeLimit = (New-TimeSpan -Hours 2)
    AllowStartIfOnBatteries = $true
    DontStopIfGoingOnBatteries = $true
}
if (-not $NoWake) { $settingsArgs['WakeToRun'] = $true }
$settings = New-ScheduledTaskSettingsSet @settingsArgs
$settings.StartWhenAvailable = $false

$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

$description = "Runs DeskIT's whole test suite at $At, including the sixteen tests that need the real screen and the real mouse and are skipped every time you are at the desk. Asks first, on screen, and runs anyway if nobody answers in five minutes. A clean run files nothing; a failing one leaves one report on the Problems place. Turn it off with [tests] nightly in config.toml; see nightly.py."

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$verb = if ($existing) { 'Replace the scheduled task' } else { 'Register the scheduled task' }
if (-not $PSCmdlet.ShouldProcess("$TaskName (daily at $At, running $Script)", $verb)) {
    Write-Host "Nothing was registered."
    exit 0
}
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description $description | Out-Null

Write-Host "Registered '$TaskName': daily at $At, running $Script as $($principal.UserId)."
Write-Host "Check it with:  Get-ScheduledTask -TaskName '$TaskName' | Format-List *"
Write-Host "Try it now with: powershell -ExecutionPolicy Bypass -File `"$Script`" -Now"
Write-Host "Turn it off without removing it: set [tests] nightly = false in config.toml."
exit 0
