# The owner's one-time move onto the three-layer settings (DISTRIBUTION_PLAN
# chapter 3, D2/D4/D30), run from the LIVE checkout while DeskIT is stopped.
#
#   1. keeps the live config.toml as config.legacy.toml (gitignored)
#   2. discards the local edits to the tracked config.toml so the merge can
#      rename it to defaults.toml
#   3. fast-forwards main onto dist/phase1
#   4. --migrate: config.legacy.toml -> settings.toml + state.json
#   5. --reset-data (dry run): prints what "start over" would remove
#
# It never deletes data: step 5 only lists. The real reset is a separate
# command the owner runs by hand, with --yes.
#
# Windows PowerShell 5.1: no &&, no ternary. Stops at the first failure.

$ErrorActionPreference = 'Stop'
$repo = 'C:\Users\shimr\Desktop\Organized\Projects\DeskIT'
$py = Join-Path $repo '.venv\Scripts\python.exe'
Set-Location $repo

Write-Host '== 1. keeping the live config.toml as config.legacy.toml'
if (Test-Path 'config.legacy.toml') {
    Write-Host '   config.legacy.toml already exists - leaving it alone'
} else {
    Copy-Item 'config.toml' 'config.legacy.toml'
}

Write-Host '== 2. discarding the local edits to the tracked config.toml (the copy above has them)'
git checkout -- config.toml
if ($LASTEXITCODE -ne 0) { throw 'git checkout failed' }

Write-Host '== 3. fast-forward main onto dist/phase1'
git merge --ff-only dist/phase1
if ($LASTEXITCODE -ne 0) { throw 'git merge failed' }

Write-Host '== 4. migrate: config.legacy.toml -> settings.toml + state.json'
& $py main.py --migrate
if ($LASTEXITCODE -ne 0) { throw 'migrate failed' }

Write-Host ''
Write-Host '== 5. what --reset-data WOULD remove (nothing removed yet):'
& $py main.py --reset-data
Write-Host ''
Write-Host 'Done. settings.toml and state.json are in place. To start over with only'
Write-Host 'the settings kept, run:   .venv\Scripts\python.exe main.py --reset-data --yes'
