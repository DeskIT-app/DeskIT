# The 02:55 nightly test run, as the scheduled task invokes it.
#
# Runs `nightly.py` in this repo: it asks on screen whether to run, waits five
# minutes, and runs the WHOLE suite -- including the sixteen tests that need
# the real screen and the real mouse and are therefore skipped every time the
# owner is at his desk, which is every day. Everything it did is appended to
# problems\nightly\run.log. A clean night files nothing at all; a night with
# real failures leaves ONE report on the Problems place for the Saturday
# routine to rule on. See nightly.py for the whole contract.
#
# WHY THIS FILE EXISTS AT ALL -- why the alarm clock is Task Scheduler and not
# a timer inside DeskIT. On the night DeskIT had crashed there would be no test
# run, and that is exactly the night you would want one. So the trigger lives
# outside the thing it is testing.
#
# Windows PowerShell 5.1: no &&, no ternary, no ??. Nothing here may prompt --
# there is no console and the owner is asleep.
#
# It exits 0 whatever happened, weekly_review.ps1's reason: Task Scheduler's
# history stays clean and he learns about a bad night from the Problems place
# rather than from a red icon in a window he never opens. A missing interpreter
# or a moved repo is still logged loudly, because those are the two failures
# that make every future run a no-op.

# -Now: SKIP THE QUESTION AND RUN THE SUITE. For running the thing by hand to
# see that it works, which is the only way anybody will ever see it work
# without staying up. The scheduled task never passes it.
param([switch]$Now)

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

# --- the paths, because a task's working directory is not ours
# The repo is wherever THIS FILE lives, not a typed path -- weekly_review.ps1
# paid for that lesson on 2026-09-05, when a concurrent rename left a typed
# path pointing at a folder that no longer existed and the next run would have
# exited 0 in silence. $PSScriptRoot follows the folder through a rename; the
# typed path stays only as a fallback for a host that runs this by content
# rather than by file.
$Repo   = if ($PSScriptRoot) { $PSScriptRoot } else { 'C:\Users\shimr\Desktop\Organized\Projects\DeskIT' }
$LogDir = Join-Path $Repo 'problems\nightly'
$Log    = Join-Path $LogDir 'run.log'
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$Script = Join-Path $Repo 'nightly.py'

# Where a message goes when the repo itself is missing. Without this the
# "repo is gone" line would be written UNDER the gone repo: New-Item -Force
# happily creates the whole missing tree and buries the warning in it.
$Fallback = Join-Path $env:LOCALAPPDATA 'DeskIT\nightly-run.log'
$script:Target = $Fallback

# run.log is capped rather than rotated forever: one previous generation, the
# way app.log / app.log.1 already do it. nightly.py caps the same file at the
# same size from the Python side; whichever writes first does the rotation.
$LogMaxBytes = 524288

function Write-Log {
    param([string]$Text)
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    try {
        $dir = Split-Path -Parent $script:Target
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
        }
        Add-Content -Path $script:Target -Value "[$stamp] $Text" -Encoding utf8
    } catch {
        # Nothing to do and nowhere to say it. A log we cannot write must not
        # take the run down.
    }
}

function Rotate-Log {
    try {
        if (-not (Test-Path $Log)) { return }
        if ((Get-Item $Log).Length -lt $LogMaxBytes) { return }
        $old = "$Log.1"
        if (Test-Path $old) { Remove-Item -Path $old -Force -Confirm:$false }
        Move-Item -Path $Log -Destination $old -Force
    } catch {
        # A log that will not rotate is still a log worth appending to.
    }
}

# --- the failures worth shouting about
if (-not (Test-Path -PathType Container $Repo)) {
    Write-Log "FATAL: repo path is gone -- $Repo. The nightly test run cannot run and will not run again until this path is corrected in nightly_tests.ps1. (Logged here because the repo's own problems\nightly is gone with it.)"
    exit 0
}

$script:Target = $Log
Rotate-Log

if (-not (Test-Path -PathType Leaf $Python)) {
    Write-Log "FATAL: no interpreter at $Python. Every nightly run is a no-op until the virtual environment is back. (The repo's own python, never a system one -- the suite imports the app.)"
    exit 0
}
if (-not (Test-Path -PathType Leaf $Script)) {
    Write-Log "FATAL: nightly.py is not beside this script ($Script). Nothing ran."
    exit 0
}

Set-Location -LiteralPath $Repo
if (-not $?) {
    Write-Log "FATAL: could not Set-Location to $Repo."
    exit 0
}

# ONE RUN AT A TIME IS NOT THIS FILE'S JOB, and that is deliberate. The task is
# registered MultipleInstances=IgnoreNew, and nightly.py itself holds an
# exclusive byte lock on problems\nightly\run.lock for the whole of one
# invocation -- the five minutes of asking and the suite together. That lock is
# a HANDLE, so Windows drops it however the process ended, which means it can
# never wedge a future night. A second guard here would only be a second thing
# that could be left behind.

$reason = 'the 02:55 trigger'
if ($Now) { $reason = 'by hand, with -Now (no question asked)' }
Write-Log ("---- nightly tests starting: {0} (repo {1}) ----" -f $reason, $Repo)

# stdout and stderr go to their own temp files and are appended afterwards.
# Redirecting a native exe's stderr inline (2>&1) in PowerShell 5.1 wraps every
# line in a NativeCommandError and lies about $?, so Start-Process is used
# instead: real exit code, real separation, and -NoNewWindow means no console
# flashes on his screen if he happens to be awake and logged in.
#
# stdin is redirected from an empty file so the child sees EOF immediately and
# can never sit waiting on input that will not come.
#
# NOT pythonw.exe, and not -WindowStyle Hidden on the child: nightly.py has to
# be able to open a real window on his desktop -- the question is the whole
# feature -- and that needs the interactive session the task's Interactive
# logon type gives it.
$tmp     = [System.IO.Path]::GetTempPath()
$tag     = [guid]::NewGuid().ToString('N')
$outFile = Join-Path $tmp "nightly-tests-$tag.out"
$errFile = Join-Path $tmp "nightly-tests-$tag.err"
$inFile  = Join-Path $tmp "nightly-tests-$tag.in"

$exitCode = -1
try {
    New-Item -ItemType File -Path $inFile -Force | Out-Null
    $pyArgs = @($Script)
    if ($Now) { $pyArgs += '--now' }
    Write-Log ("invoking: {0} {1}" -f $Python, ($pyArgs -join ' '))
    $proc = Start-Process -FilePath $Python -ArgumentList $pyArgs `
        -WorkingDirectory $Repo -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $outFile `
        -RedirectStandardError  $errFile `
        -RedirectStandardInput  $inFile
    $exitCode = $proc.ExitCode
} catch {
    Write-Log ("FAILED to start the run: " + $_.Exception.Message)
    $exitCode = -1
}

foreach ($pair in @(@($outFile, 'out'), @($errFile, 'err'))) {
    try {
        if (Test-Path $pair[0]) {
            $text = Get-Content -Path $pair[0] -Raw -Encoding UTF8
            if ($text -and $text.Trim().Length -gt 0) {
                foreach ($line in ($text -split "`r?`n")) {
                    if ($line.Trim().Length -gt 0) {
                        Write-Log ("[{0}] {1}" -f $pair[1], $line)
                    }
                }
            }
        }
    } catch {
        Write-Log ("[{0}] (could not be read back from {1})" -f $pair[1], $pair[0])
    }
}

foreach ($path in @($outFile, $errFile, $inFile)) {
    try {
        if (Test-Path $path) { Remove-Item -Path $path -Force -Confirm:$false }
    } catch { }
}

if ($exitCode -eq 0) {
    Write-Log "---- nightly tests finished ----"
} else {
    # NO CARD, and that is his rule rather than an omission: "a clean run files
    # nothing... he should not wake up to a receipt". A run that could not
    # start is in this log; a run that found something wrong left a report on
    # the Problems place, which is the surface he actually opens. A card at
    # three in the morning would be a notification he cannot act on until
    # daylight, which is the definition of noise.
    Write-Log ("---- nightly tests ended badly (exit {0}) -- see the lines above ----" -f $exitCode)
}

# 0 for everything. There is no failure here worth retrying an hour later: the
# hour is the point, and an hour later he is asleep for one hour less.
exit 0
