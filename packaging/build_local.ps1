# The build's steps 1-7 on this PC, into dist\stage — a throwaway tree for
# the phase-0 VirusTotal probe and for seeing the pipeline work before
# a tag runs it on GitHub (DISTRIBUTION_PLAN.md 10.3, "Local rehearsal").
# It publishes nothing, attests nothing, and its output is not a release.
#
#     powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_local.ps1
#     powershell ... -File packaging\build_local.ps1 -Python "C:\...\Python311\python.exe"
#
# Needs: a full python.org 3.11.9 install (its Tcl/Tk tree and _tkinter.pyd
# are copied, so the patch version must be the embeddable's), network for
# the wheelhouse and the python.org zip (once; both are cached in dist\).
param(
    [string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    [string]$Out = "dist"
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$Version = (Get-Content VERSION -Raw).Trim()
$Embed = "3.11.9"
$EmbedUrl = "https://www.python.org/ftp/python/$Embed/python-$Embed-embed-amd64.zip"
$Stage = Join-Path $Out "stage"
$Wheels = Join-Path $Out "wheels"
$Zip = Join-Path $Out "python-$Embed-embed-amd64.zip"

$got = (& $Python -c "import platform; print(platform.python_version())").Trim()
if ($got -ne $Embed) { throw "$Python is $got; the embeddable is $Embed and the Tk tree must match" }
$PyHome = Split-Path -Parent $Python

Write-Host "DeskIT $Version -> $Stage"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force $Stage, $Wheels | Out-Null

# 1. wheelhouse, by hash, binary only
& $Python -m pip download -r requirements.lock --require-hashes --no-deps --only-binary=:all: `
    --platform win_amd64 --python-version 3.11 --implementation cp --abi cp311 --dest $Wheels
if ($LASTEXITCODE) { throw "pip download failed" }

# 2. the embeddable zip, checked against packaging\python-embed.sha256
if (-not (Test-Path $Zip)) { Invoke-WebRequest -Uri $EmbedUrl -OutFile $Zip }
$want = ((Get-Content packaging\python-embed.sha256 -Raw).Trim() -split "\s+")[0].ToLower()
$hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $want) { throw "$Zip SHA-256 $hash, expected $want" }
Expand-Archive $Zip -DestinationPath (Join-Path $Stage "python")

# 3. Tcl/Tk from the full install
$py = Join-Path $Stage "python"
Copy-Item -Recurse (Join-Path $PyHome "tcl") (Join-Path $py "tcl")
New-Item -ItemType Directory -Force (Join-Path $py "Lib") | Out-Null
Copy-Item -Recurse (Join-Path $PyHome "Lib\tkinter") (Join-Path $py "Lib\tkinter")
foreach ($f in "_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll") {
    $src = Join-Path $PyHome "DLLs\$f"
    if (Test-Path $src) { Copy-Item $src (Join-Path $py $f) }
}

# 4. the committed _pth
Copy-Item packaging\python311._pth (Join-Path $py "python311._pth") -Force

# 5. install from the wheelhouse only
& $Python -m pip install --no-index --find-links $Wheels --require-hashes --no-deps `
    -r requirements.lock --target (Join-Path $py "Lib\site-packages")
if ($LASTEXITCODE) { throw "pip install failed" }
Get-ChildItem -Recurse $py -Include __pycache__ -Directory | Remove-Item -Recurse -Force

# 6. the product tree — the working copy's .gitattributes decide what is in it
$appZip = Join-Path $Out "app.zip"
git archive --worktree-attributes --format=zip --output $appZip HEAD
if ($LASTEXITCODE) { throw "git archive failed" }
Expand-Archive $appZip -DestinationPath (Join-Path $Stage "app")
foreach ($f in "LICENSE", "NOTICE", "OFL.txt", "NETWORK.md", "SECURITY.md") {
    $src = Join-Path $Stage "app\$f"
    if (Test-Path $src) { Copy-Item $src (Join-Path $Stage $f) }
}

# 7. the manifest, and a read-back
& $Python (Join-Path $Stage "app\manifest.py") write $Stage
& $Python (Join-Path $Stage "app\manifest.py") verify $Stage
if ($LASTEXITCODE) { throw "the manifest does not verify" }

# and the tree starts on its own interpreter
& (Join-Path $py "python.exe") -c "import sys, tkinter, numpy, PIL, sounddevice; print('staged python', sys.version.split()[0], 'tk', tkinter.TkVersion, 'numpy', numpy.__version__)"
if ($LASTEXITCODE) { throw "the staged python cannot import the base set" }
$size = (Get-ChildItem -Recurse $Stage -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("stage: {0:N0} MB on disk" -f ($size / 1MB))

# 9-10. the channel word and, when Inno Setup 6 is installed here, the
#       installer itself (steps 8 and 11-15 are the workflow's alone)
Set-Content -Path (Join-Path $Stage "CHANNEL") -Value github -NoNewline -Encoding ascii
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    $core = ($Version -split '-')[0]
    $beta = if ($Version -match '-beta\.(\d+)$') { $Matches[1] } else { '0' }
    & $iscc packaging\DeskIT.iss /DVersion=$Version /DVersionInfo="$core.$beta" /DStage=$Stage /DOutDir=$Out
    if ($LASTEXITCODE) { throw "ISCC failed" }
    Get-ChildItem $Out -Filter "DeskIT-Setup-*.exe" | ForEach-Object { Write-Host ("installer: {0} ({1:N0} MB)" -f $_.Name, ($_.Length / 1MB)) }
} else {
    Write-Host "Inno Setup 6 is not installed here; the stage is built, the installer is not (release.yml makes it)"
}
