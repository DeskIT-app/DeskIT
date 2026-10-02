# The Store package from a finished tree (DISTRIBUTION_PLAN.md 10.7).
#
#   build_msix.ps1 -Tree <folder holding python\ and app\> -Version X.Y.Z -Out <folder>
#
# What it adds to the tree: the three launchers (launcher.c, compiled with
# the MSVC the machine has), assets\ (assets.py), AppxManifest.xml (the
# template with the version filled in) and CHANNEL = store. Then MakeAppx
# packs it — and validates the manifest against the schema while it does,
# which is the first check the package meets. Unsigned: the Store signs
# what it accepts. .github/workflows/store.yml runs this on the tree of a
# published release's installer; a person can run it on the same tree.
#
# -Python is an interpreter with Pillow (the logos); the default is the
# one on PATH.
param(
    [Parameter(Mandatory = $true)] [string] $Tree,
    [Parameter(Mandatory = $true)] [string] $Version,
    [Parameter(Mandatory = $true)] [string] $Out,
    [string] $Python = "python"
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$repo = (Resolve-Path "$here\..\..").Path
$Tree = (Resolve-Path $Tree).Path

if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    throw "the Store takes a release X.Y.Z, not '$Version' (no beta goes to the Store)"
}
$v1, $v2, $v3 = $Matches[1], $Matches[2], $Matches[3]
$four = "$v1.$v2.$v3.0"
foreach ($need in "python\pythonw.exe", "app\deskit.pyw", "app\notify_hook.py") {
    if (-not (Test-Path (Join-Path $Tree $need))) { throw "$need is not in $Tree" }
}

# --- the tools: MSVC through vswhere, MakeAppx from the newest Windows SDK
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found: no Visual Studio / Build Tools" }
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "no Visual Studio with the C++ tools" }
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" |
    Sort-Object { [version]($_.Directory.Parent.Name) } | Select-Object -Last 1
if (-not $makeappx) { throw "makeappx.exe not found: no Windows SDK" }

# --- 1. the launchers
$build = Join-Path ([IO.Path]::GetTempPath()) ("deskit-launcher-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $build | Out-Null
try {
    $icon = (Join-Path $repo "icon.ico").Replace("\", "\\")
    @(
        "#define DESKIT_V1 $v1",
        "#define DESKIT_V2 $v2",
        "#define DESKIT_V3 $v3",
        "#define DESKIT_VERSION `"$four`"",
        "#define DESKIT_ICON `"$icon`""
    ) | Set-Content -Path (Join-Path $build "launcher_version.h") -Encoding ascii
    Copy-Item (Join-Path $here "launcher.c"), (Join-Path $here "launcher.rc") $build
    $variants = @{ "DeskIT.exe" = 0; "DeskITQuiet.exe" = 1; "DeskITHook.exe" = 2 }
    $steps = @("rc /nologo /fo launcher.res launcher.rc")
    foreach ($name in $variants.Keys) {
        $steps += "cl /nologo /O1 /MT /W4 /WX /DDESKIT_VARIANT=$($variants[$name]) launcher.c launcher.res /Fe:$name /link /SUBSYSTEM:WINDOWS user32.lib"
    }
    # vcvars talks on stderr even when it works (VS 18 looks for vswhere on
    # PATH and says so); Windows PowerShell turns any stderr line from a
    # native command into a terminating error under Stop. So cmd folds
    # stderr into stdout and the exit code is the verdict.
    $cmd = "call `"$vcvars`" >nul 2>&1 && cd /d `"$build`" && (" + ($steps -join " && ") + ") 2>&1"
    & cmd.exe /c $cmd
    if ($LASTEXITCODE) { throw "the launcher did not compile (exit $LASTEXITCODE)" }
    foreach ($name in $variants.Keys) { Copy-Item (Join-Path $build $name) (Join-Path $Tree $name) -Force }
} finally {
    Remove-Item -Recurse -Force $build -ErrorAction SilentlyContinue
}

# --- 2. the logos (-B: when -Python is the tree's own interpreter, a
#     bytecode cache written into its site-packages would ride into the
#     package outside the release's manifest)
& $Python -B (Join-Path $here "assets.py") --out (Join-Path $Tree "assets")
if ($LASTEXITCODE) { throw "assets.py failed" }

# --- 3. the manifest and the channel word
$manifest = (Get-Content (Join-Path $here "AppxManifest.xml") -Raw -Encoding utf8).Replace("{VERSION}", $four)
[IO.File]::WriteAllText((Join-Path $Tree "AppxManifest.xml"), $manifest, (New-Object Text.UTF8Encoding $false))
Set-Content -Path (Join-Path $Tree "CHANNEL") -Value store -NoNewline -Encoding ascii

# --- 4. pack (and validate)
New-Item -ItemType Directory -Force $Out | Out-Null
$msix = Join-Path (Resolve-Path $Out).Path "DeskIT-App-$four.msix"
& $makeappx.FullName pack /d $Tree /p $msix /o
if ($LASTEXITCODE) { throw "MakeAppx refused the package (exit $LASTEXITCODE)" }
$sha = (Get-FileHash $msix -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$msix.sha256" -Value "$sha  DeskIT-App-$four.msix" -Encoding ascii
"$msix  $([math]::Round((Get-Item $msix).Length / 1MB)) MB  sha256 $sha"
