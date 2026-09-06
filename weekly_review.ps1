# The Saturday 08:00 weekly review, as the scheduled task invokes it.
#
# Runs `/weekly-reports` headless in this repo and appends everything it said
# to problems\weekly\run.log. It produces documents and stops -- it fixes
# nothing; see .claude\commands\weekly-reports.md for what the run actually
# does and why closing a report is safe.
#
# Windows PowerShell 5.1: no &&, no ternary, no ??. Nothing here may prompt --
# there is no console and nobody is at the keyboard on a Saturday morning.
#
# It exits 0 whatever happened, so Task Scheduler's history stays clean and the
# owner learns about a bad Saturday from the log rather than a red icon. A
# missing claude.exe or a moved repo is still logged loudly, because those are
# the two failures that make every future run a no-op.

# -Answered: HE JUST ANSWERED A QUESTION, SO THERE IS NEW WORK NOW.
#
# The routine asks a multiple-choice question when a report cannot be settled
# from its own evidence, and then it stops. He answers inside the app -- the
# question card in main.py, or the dashboard's answer surface -- and the store
# write is followed immediately by this script with this switch, which is a
# CONTRACT: it is spelled exactly '-Answered', because two other files call it.
#
# All the switch does is ignore today's .done stamp. Everything else about the
# run is identical, because the command is already the right one: it reads the
# questions store, builds what he has answered, and asks about what it still
# cannot decide. What it must NOT do is claim the day -- see the stamp block
# below.
param([switch]$Answered)

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

# --- the three absolute paths, because a task's working directory is not ours
# The repo is wherever THIS FILE lives -- not a typed path. Measured
# 2026-09-05 10:20: a concurrent rename session had already set this to
# ...\Projects\DeskIT while the folder was still ...\Projects\DeskIT,
# which would have made the next Saturday hit "repo path is gone" and exit 0
# in silence. $PSScriptRoot follows the folder through a rename without anyone
# remembering to edit a string; the typed path stays only as a fallback for a
# host that runs the script by content rather than by file.
$Repo   = if ($PSScriptRoot) { $PSScriptRoot } else { 'C:\Users\shimr\Desktop\Organized\Projects\DeskIT' }
$LogDir = Join-Path $Repo 'problems\weekly'
$Log    = Join-Path $LogDir 'run.log'

# Which claude.exe. NOT a fixed path, because there are two clients on this
# machine and picking the wrong one silently costs features: measured
# 2026-09-04, C:\Users\shimr\.local\bin\claude.exe was 2.1.201 while the
# desktop app carried 2.1.258 and 2.1.260 -- fifty-nine versions apart, and
# the older one has zero occurrences of quota_auto_resume in its bundle. A
# weekly run on a stale client is a weekly run against different behaviour
# than the owner sees when he types the command himself.
#
# So: the newest bundle the desktop app has, chosen by real version compare
# ([version] and not a string sort, or 2.1.9 would beat 2.1.260), and the
# standalone binary only as a fallback for a machine without the app. The
# chosen path and its version go in the log, so a run that behaved oddly can
# be traced to the client that produced it instead of being guessed at.
$Claude = $null
# $ClaudeWhy records what the resolver saw, because the first real run
# (2026-09-05 04:00) picked the fallback while the identical code picked
# 2.1.260 by hand -- and a resolver that fails silently under the scheduler is
# indistinguishable from one that chose. Logged at "starting", once Write-Log
# has a target.
$ClaudeWhy = ''
try {
    # Two places to look, and the second is the one that matters under the
    # scheduler. The desktop app is an MSIX package (Claude_pzs8sxrjxfjjc in
    # Program Files\WindowsApps), so its %APPDATA%\Claude is VIRTUALISED: the
    # real files live under %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming,
    # and only a process inside the package sees them at the %APPDATA% path.
    # Measured 2026-09-05 04:04: the scheduler's process got exists=False on
    # the %APPDATA% path while a shell inside the app saw 2.1.258 and 2.1.260
    # there -- same user, same string, different view of the file system.
    $appdata = [string]$env:APPDATA
    if (-not $appdata) { $appdata = Join-Path $env:USERPROFILE 'AppData\Roaming' }
    $roots = @(Join-Path $appdata 'Claude\claude-code')
    $pkgs = Join-Path $env:LOCALAPPDATA 'Packages'
    if (Test-Path $pkgs) {
        Get-ChildItem $pkgs -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue | ForEach-Object {
            $roots += Join-Path $_.FullName 'LocalCache\Roaming\Claude\claude-code'
        }
    }
    $found = @()
    foreach ($root in $roots) {
        $exists = Test-Path $root
        $ClaudeWhy += " [$root exists=$exists]"
        if (-not $exists) { continue }
        foreach ($d in @(Get-ChildItem $root -Directory -ErrorAction SilentlyContinue)) {
            $exe = Join-Path $d.FullName 'claude.exe'
            $v = $null
            if ((Test-Path -PathType Leaf $exe) -and [version]::TryParse($d.Name, [ref]$v)) {
                $found += [pscustomobject]@{ Version = $v; Path = $exe }
            }
        }
    }
    $best = $found | Sort-Object Version -Descending | Select-Object -First 1
    if ($best) { $Claude = $best.Path }
} catch {
    $ClaudeWhy += " resolver threw: $($_.Exception.Message)"
}
if (-not $Claude) {
    $Claude = 'C:\Users\shimr\.local\bin\claude.exe'
    $ClaudeWhy += " -> FELL BACK to .local\bin"
} else {
    $ClaudeWhy += " -> picked $Claude"
}

# Where a message goes when the repo itself is missing. Without this the
# "repo is gone" line would be written UNDER the gone repo -- measured
# 2026-09-04: New-Item -Force happily created C:\nope\gonerepo\problems\weekly
# and buried the FATAL there, which is a phantom directory and a lost warning.
# So the target starts outside the repo and only moves in once the repo is
# confirmed to exist.
$Fallback = Join-Path $env:LOCALAPPDATA 'DeskIT\weekly-run.log'
$script:Target = $Fallback

# Permission mode for the unattended run. The command reads problems.json,
# writes three files under problems\weekly and calls the venv python; with
# nobody there to answer, a permission prompt is a failed Saturday. Narrowed
# instead by --strict-mcp-config (no connectors at all, so nothing tries to
# authenticate) and by refusing the two tools that reach the network.
$PermissionMode = 'bypassPermissions'

# run.log is capped rather than rotated forever: one previous generation, the
# way the repo already keeps app.log / app.log.1.
$LogMaxBytes = 524288

function Write-Log {
    param([string]$Text)
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    $line  = "[$stamp] $Text"
    try {
        $dir = Split-Path -Parent $script:Target
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
        }
        Add-Content -Path $script:Target -Value $line -Encoding utf8
    } catch {
        # Nothing to do and nowhere to say it. A log we cannot write must not
        # take the run down -- the documents matter more than the trace.
    }
}

function Rotate-Log {
    try {
        if (-not (Test-Path $Log)) { return }
        $size = (Get-Item $Log).Length
        if ($size -lt $LogMaxBytes) { return }
        $old = "$Log.1"
        if (Test-Path $old) { Remove-Item -Path $old -Force -Confirm:$false }
        Move-Item -Path $Log -Destination $old -Force
    } catch {
        # A log that will not rotate is still a log worth appending to.
    }
}

# --- the two failures worth shouting about
if (-not (Test-Path -PathType Container $Repo)) {
    Write-Log "FATAL: repo path is gone -- $Repo. The weekly review cannot run and will not run again until this path is corrected in weekly_review.ps1. (Logged here because the repo's own problems\weekly is gone with it.)"
    exit 0
}

# The repo is there, so the log belongs in it from here on.
$script:Target = $Log
Rotate-Log

if (-not (Test-Path -PathType Leaf $Claude)) {
    Write-Log "FATAL: claude.exe not found at $Claude. Every weekly run is a no-op until this path is corrected in weekly_review.ps1."
    exit 0
}

Set-Location -LiteralPath $Repo
if (-not $?) {
    Write-Log "FATAL: could not Set-Location to $Repo."
    exit 0
}

# --- one review at a time, and the lock is a FILE HANDLE
# The scheduled task is registered MultipleInstances=IgnoreNew, and that was
# protection enough while the task was the only caller. It is not any more:
# -Answered is invoked directly by the app the moment he answers a question,
# and a direct invocation is not the task, so nothing in the scheduler stops it
# landing on top of a running Saturday scan -- two clients writing the same
# three documents under problems\weekly and both closing reports off the same
# problems.json.
#
# An EXCLUSIVE FILE HANDLE (FileShare::None), which is the honest PowerShell
# 5.1 equivalent of the msvcrt.locking that problems.py and review.py use. NOT
# a pid file: that has to be written, read back and checked against a live
# process, and Windows reuses pids, so the check is a guess. The handle needs
# none of it -- and, the reason it was chosen, IT CANNOT WEDGE THE FEATURE.
# Windows closes a handle when the process ends however it ended: cleanly, on
# an exception, on a kill, on a power cut. There is no such thing as a stale
# lock here, so no timeout and no override are needed. The file is left behind
# on purpose; the lock is the handle, never the file's existence.
$LockPath = Join-Path $LogDir 'review.lock'
$Lock = $null
try {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    }
    $Lock = [System.IO.File]::Open($LockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None)
} catch {
    $waiting = 'nothing to do; the next hourly fire will try again'
    if ($Answered) { $waiting = 'the review already running will read his answer, and next Saturday will build it if it did not' }
    Write-Log ("another review holds the lock ($LockPath) -- {0}" -f $waiting)
    exit 0
}

# One review per Saturday, however many times the trigger fires. The task
# repeats hourly until mid-afternoon so a spent usage window does not cost him
# the week -- and the retry is the trigger's own repetition, not
# restart-on-failure, because that was measured NOT to work (2026-09-04: a
# probe task that exited 3 with RestartCount=1 ran once and stayed run;
# Task Scheduler restarts a process that failed to launch, not one that
# launched and returned non-zero). What stops the repetition is this stamp,
# written only after a clean finish. A rate-limited or crashed run leaves no
# stamp, and the next hour tries again.
#
# -Answered is the one thing allowed past it, and only past the CHECK. A new
# answer is new work even though today's scan already finished, which is the
# whole reason the switch exists -- he answers at nine on a Saturday morning
# and the code is written at nine, not next week. The stamp itself is not
# touched here or below: see the finish.
$Stamp = Join-Path $LogDir ((Get-Date).ToString('yyyy-MM-dd') + '.done')
$reviewed = Test-Path -PathType Leaf $Stamp
if ($reviewed -and (-not $Answered)) {
    Write-Log "already reviewed today ($Stamp) -- nothing to do"
    exit 0
}
if ($reviewed) {
    Write-Log "today is already reviewed ($Stamp), but an answer arrived since -- running anyway; the stamp stays as it is"
}

$Reason = 'the Saturday scan'
if ($Answered) { $Reason = 'he answered a question (-Answered)' }
Write-Log ("---- weekly review starting: {0} (repo {1}) ----" -f $Reason, $Repo)
Write-Log "client: $ClaudeWhy"

# stdout and stderr go to their own temp files and are appended afterwards.
# Redirecting a native exe's stderr inline (2>&1) in PowerShell 5.1 wraps every
# line in a NativeCommandError and lies about $?, so Start-Process is used
# instead: real exit code, real separation, and -NoNewWindow means no console
# flashes on the owner's screen if he happens to be logged in.
#
# stdin is redirected from an empty file so the child sees EOF immediately and
# can never sit waiting on input that will not come.
$tmp    = [System.IO.Path]::GetTempPath()
$tag    = [guid]::NewGuid().ToString('N')
$outFile = Join-Path $tmp "weekly-review-$tag.out"
$errFile = Join-Path $tmp "weekly-review-$tag.err"
$inFile  = Join-Path $tmp "weekly-review-$tag.in"

$exitCode = -1
try {
    New-Item -ItemType File -Path $inFile -Force | Out-Null

    # The model is pinned, and by full id rather than the 'opus' alias: an
    # alias floats to whatever is newest, so two Saturdays a month apart could
    # be judged by different models and nobody would know which. The review is
    # judgement work -- ruling on a report, refusing to guess, writing a plan
    # against evidence -- so it gets the Opus tier, not the account default
    # (which was unset when this was measured on 2026-09-04, i.e. whatever the
    # CLI felt like).
    $claudeArgs = @(
        '-p', '/weekly-reports',
        '--model', 'claude-opus-5',
        '--output-format', 'text',
        '--permission-mode', $PermissionMode,
        '--strict-mcp-config',
        '--disallowed-tools', 'WebFetch', 'WebSearch'
    )
    Write-Log ("invoking: {0} {1}" -f $Claude, ($claudeArgs -join ' '))

    $proc = Start-Process -FilePath $Claude -ArgumentList $claudeArgs `
        -WorkingDirectory $Repo -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $outFile `
        -RedirectStandardError  $errFile `
        -RedirectStandardInput  $inFile
    $exitCode = $proc.ExitCode
} catch {
    Write-Log ("FAILED to start claude: " + $_.Exception.Message)
    $exitCode = -1
}

# The one failure that is worth retrying: the usage window was empty when the
# task fired. Every other failure -- claude missing, repo gone, a real crash --
# is the same an hour later, but a spent allowance refills on its own, and the
# 4 AM slot exists precisely so a heavy evening does not cost him the review.
# The signature is what the client prints on a 429 (seen 2026-09-04:
# "You've hit your session limit · resets 7:50pm (Asia/Jerusalem)"); the
# reset fragment is kept for the log so the retry cadence can be judged
# against it later.
$rateLimited = $false
$resetNote   = ''
$firstOut    = ''       # the first thing claude said -- usually the reason it stopped

foreach ($pair in @(@($outFile, 'out'), @($errFile, 'err'))) {
    $path  = $pair[0]
    $label = $pair[1]
    try {
        if (Test-Path $path) {
            $text = Get-Content -Path $path -Raw -Encoding UTF8
            if ($text -and $text.Trim().Length -gt 0) {
                foreach ($line in ($text -split "`r?`n")) {
                    if ($line.Trim().Length -gt 0) {
                        Write-Log "[$label] $line"
                        if (-not $firstOut) { $firstOut = $line.Trim() }
                    }
                    if ($line -match "hit your \w+ limit|rate_limit|usage limit") {
                        $rateLimited = $true
                        if ($line -match "resets?\s+[^\r\n]*") { $resetNote = $Matches[0] }
                    }
                }
            }
        }
    } catch {
        Write-Log "[$label] (could not be read back from $path)"
    }
}

foreach ($path in @($outFile, $errFile, $inFile)) {
    try {
        if (Test-Path $path) { Remove-Item -Path $path -Force -Confirm:$false }
    } catch { }
}

if ($rateLimited) {
    # Exit 3, and ONLY here: the scheduled task is registered with
    # restart-on-failure (hourly, up to six times -- one five-hour window plus
    # slack), and a non-zero exit is what Task Scheduler counts as a failure.
    # The command itself is safe to re-run: it writes the documents first and
    # closes reports only after they are verified on disk, so a run that died
    # mid-way left everything open and the retry starts clean.
    $note = if ($resetNote) { " ($resetNote)" } else { '' }
    Write-Log ("---- weekly review hit the usage limit{0} -- exit 3 so the task retries in an hour; the reports were left open ----" -f $note)
    if ($Lock) { $Lock.Dispose() }
    exit 3
}

if ($exitCode -eq 0) {
    Write-Log "---- weekly review finished ok ----"
    if ($Answered) {
        # NOT OURS TO WRITE, and not ours to rewrite either. The stamp means
        # "the day's scan is done", and an -Answered run is one build off one
        # answer, not the day's scan. Writing it on a weekday would tell the
        # next Saturday fire that Saturday was reviewed when it was not; and
        # rewriting one already there would move a timestamp nobody asked to
        # move. The switch bypasses the CHECK and nothing else.
        Write-Log "answer run -- today's .done stamp is left exactly as it was"
    } else {
        try {
            Set-Content -Path $Stamp -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) -Encoding ASCII
        } catch {
            Write-Log "could not write $Stamp -- the next hourly fire will run the review again"
        }
    }
} else {
    Write-Log ("---- weekly review FAILED (exit {0}) -- the reports were left open, nothing was closed ----" -f $exitCode)

    # A failure that will not fix itself gets a card on his screen, through
    # the door the repo already has (notify_hook.py -> POST /notify; exits 0
    # in silence if the app is not up). Measured 2026-09-05: the first three
    # real runs all died on "Not logged in" and the only reason anyone knew
    # was that someone happened to be reading run.log at 4 AM. The log is not
    # a channel he opens; the card stack is. Once per day, not once per hourly
    # repetition -- a marker beside the .done stamp keeps the twelve retries
    # from posting twelve copies. A rate-limited run never reaches here: it
    # exits 3 above, because that failure DOES fix itself and a card he cannot
    # act on is noise.
    #
    # An -Answered run gets its OWN marker, and that is not a detail. The two
    # failures are different news: "the Saturday scan did not run" is a week he
    # can wait for, while "you answered a question twenty minutes ago and
    # nothing was built" is the promise this feature makes being broken. With
    # one shared marker, a scan that failed at 04:00 would swallow the card for
    # every answer he gave that day, in silence. Still once per day per kind,
    # which is what the twelve retries needed.
    $failSuffix = '.failed'
    if ($Answered) { $failSuffix = '.answered-failed' }
    $failMark = Join-Path $LogDir ((Get-Date).ToString('yyyy-MM-dd') + $failSuffix)
    if (-not (Test-Path -PathType Leaf $failMark)) {
        try {
            $why = if ($firstOut) { $firstOut } else { "exit $exitCode, nothing printed" }
            if ($why.Length -gt 200) { $why = $why.Substring(0, 200) }
            # The one failure with a known cure gets the cure on the card, in
            # his language, not the client's English one-liner: he said the
            # bare "Not logged in" would not have told him what to do.
            if ($firstOut -match 'Not logged in') {
                $why = 'ה-CLI לא מחובר. פתח PowerShell, הרץ claude.exe מ-.local\bin, הקלד /login ואשר בדפדפן. הריצה הבאה תמשיך לבד.'
            }
            # And the title says WHICH run failed, for the same reason the
            # marker is separate: he is standing there having just answered,
            # and "the weekly review failed" would not tell him that it was
            # HIS answer that went nowhere.
            $failTitle = 'הסקירה השבועית נכשלה'
            if ($Answered) { $failTitle = 'התשובה נשמרה אבל הבנייה נכשלה' }
            $py = Join-Path $Repo '.venv\Scripts\python.exe'
            & $py (Join-Path $Repo 'notify_hook.py') --source weekly --kind error `
                --title $failTitle `
                --body ("{0} · problems/weekly/run.log" -f $why) | Out-Null
            Set-Content -Path $failMark -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) -Encoding ASCII
            Write-Log "failure card sent: $why"
        } catch {
            Write-Log ("could not send the failure card: " + $_.Exception.Message)
        }
    } else {
        Write-Log "failure card already sent today ($failMark) -- not repeating it"
    }
}

# The lock, let go explicitly. Windows would do it a millisecond later anyway
# -- that is the property the whole choice rests on -- but an -Answered run can
# be followed within seconds by another answer, and a handle released here
# rather than at teardown is one less race to think about.
if ($Lock) { $Lock.Dispose() }

# 0 for everything that is not a spent allowance, including hard failures: the
# log is the channel for those, and a retry would only fail the same way.
exit 0
