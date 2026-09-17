# updates

**Question:** Auto-update for a Python desktop app on Windows in 2026: tufup, PyUpdater (dead?), Velopack (Python support?), Squirrel.Windows, WinSparkle, a hand-rolled updater reading a GitHub Releases latest.json, winget upgrade, MSIX App Installer updates, Inno Setup re-run. Cover replacing files while running, verifying update signatures/hashes, stable/beta channels, semver for desktop apps, keeping user data outside the install dir, rollback, and GitHub Releases limits (asset size, bandwidth) — why the ML model must not be a release asset. Recommend one approach.

Researched 2026-09-16.

## Findings (appended as sources are read)

### Search-round 1 (unverified leads, to confirm on primary pages)
- Velopack: claims first-class Python support; PyPI package `velopack` (last release 2026-06-03 per search); works with PyInstaller --onedir; `vpk pack` builds installer. https://docs.velopack.io/getting-started/python
- tufup: built on python-tuf; patches (bsdiff) with fallback to full archive; pre-releases filtered by default (channel-like); issues active through late 2025. https://github.com/dennisvang/tufup
- GitHub Releases (docs): "Each file included in a release must be under 2 GiB", "no limit on the total size of a release, nor bandwidth usage" (to quote from primary). https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- PyUpdater: last release 4.0 (Aug 2021 on PyPI per memory) - verify on PyPI.
- winget: Inno Setup installer type supported; each release needs a new manifest, `wingetcreate update` can run in CI. Publisher/PackageName should match Add/Remove Programs entry.
- Code signing: Azure Trusted/Artifact Signing ~$9.99/mo, but individuals only in USA/Canada (Israeli solo dev = not eligible, per search); OV cert $150-300/yr. MSIX .appinstaller requires CA-trusted cert.

### Source: GitHub Docs, About releases (read 2026-09-16)
URL: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- Quote: "Each file included in a release must be under 2 GiB." "Up to 1000 release assets may be associated with a single release." "There is no limit on the total size of a release, nor bandwidth usage."
- Implication: the ~1.6 GB whisper model technically fits under 2 GiB, and bandwidth is not metered, BUT: (a) a single asset near the cap is fragile (uploads over 2 GiB fail; future fp16/larger variants won't fit), (b) it would be re-uploaded per release or pinned to one old release, (c) the model's licence/attribution belongs to ivrit-ai on Hugging Face, which already serves it with resume/CDN, (d) GitHub ToS bans using releases primarily as a file-hosting/CDN unrelated to the repo (not quoted here - uncertainty). Recommendation: app downloads the model from Hugging Face at first run (hf_hub_download, resumable, sha256-verified by HF's LFS pointer), never from Releases.

### Source: tufup README (github.com/dennisvang/tufup)
- "a simple software updater for stand-alone Python applications", built on python-tuf; signs metadata with TUF role keys (root/targets/snapshot/timestamp), no delegations.
- Patches: "the tufup client will always attempt to update using one or more patches. However, if the total amount of patch data is greater than the desired full archive file, a full update will be performed."
- Windows replace-while-running: "On Windows, this script is started in a new process, after which the currently running process will exit." (a batch/robocopy-style script overwrites the install dir and relaunches)
- Channels: "By default ... it only includes final releases. Pre-releases are filtered out, unless you explicitly specify a 'pre-release' channel." (PEP 440 a/b/rc)
- Hosting: any static HTTP server (GitHub Pages works). MIT. Solo maintainer; issues active through late 2025 (search result). Uncertainty: latest release version/date not captured.

### Source: PyPI PyUpdater
URL: https://pypi.org/project/PyUpdater/
- Latest version 4.0, released 2021-04-19; single maintainer. No newer release in 5+ years => treat as dead. Do not use.

### Source: Microsoft Learn, Code signing options (page dated 2026-08-29)
URL: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
- Azure Artifact Signing (ex Trusted Signing): "Approximately $9.99/month"; "Individual developers are currently limited to the USA and Canada." Organizations: USA, Canada, EU, UK. => an Israeli solo developer with no company is NOT eligible.
- OV cert: "Typically $150-300/year"; HSM/USB token required since June 2023; CA validates "organization's legal identity" (individual OV certs exist but pricey).
- EV: "$400+/year", SmartScreen instant bypass "was removed in 2024".
- Self-signed: "Blocks installation for public users". No signature: "Strong SmartScreen block".
- Microsoft Store MSIX: "code signing is free and handled for you automatically", "Free", "Worldwide", no SmartScreen warnings. Free developer account at storedeveloper.microsoft.com (individual registration historically ~$19 one-time - uncertainty, verify).
- Open source: "SignPath Foundation offers free code signing for qualifying open-source projects" (OV-level, managed pipeline).
- => Zero-cost options for signing: (1) publish open source and apply to SignPath Foundation, (2) Microsoft Store MSIX, (3) ship unsigned and accept SmartScreen "More info > Run anyway" friction with a guide screenshot.

### Source: Microsoft Learn, MSIX App Installer auto-update overview (dated 2026-04-10)
URL: https://learn.microsoft.com/en-us/windows/msix/app-installer/auto-update-and-repair--overview
- .appinstaller settings: HoursBetweenUpdateChecks, UpdateBlocksActivation, ShowPrompt, UpdateURI fallback; needs 2021 schema for ShowPrompt. Windows checks the App Installer URI itself; works on all Windows 11.
- Not on this page but standard: MSIX outside the Store must be signed with a cert Windows trusts => blocked for this owner unless Store or SignPath. MSIX also sandboxes file-system writes (virtualised AppData) and complicates global keyboard hooks / pythonw / venv layouts. Skip MSIX for DeskIT.

### Source: Velopack Python getting started + repo README
URLs: https://docs.velopack.io/getting-started/python ; https://github.com/velopack/velopack
- Quote: "Make sure you use PyInstaller's `--onedir` (folder) output, not `--onefile`."
- API: `UpdateManager(url)` -> `check_for_updates()` -> `download_updates()` -> `apply_updates_and_restart()`; "You can also split up the various methods to allow your users to control when to check for updates."
- Quote: "The URL passed to `UpdateManager` points at wherever you host your updates (a web server, S3 bucket, GitHub releases, etc.)"
- README: MIT; "generates an installer, updates, delta packages, and self-updating portable package in just one command"; written in Rust; 2.3k stars; Windows/macOS/Linux. PyPI `velopack` (search: release 2026-06-03).
- Not captured yet (uncertainty): per-user install dir (Velopack installs to %LocalAppData%\<AppId> by convention, no admin - from prior knowledge, verify), channel flag, signing flag, rollback. Velopack's Setup.exe/Update.exe are unsigned unless the owner signs them => SmartScreen warning.

### Source: GitHub Acceptable Use Policies
URL: https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies
- Quote (bandwidth): "If we determine your bandwidth usage to be significantly excessive in relation to other users" GitHub may suspend or limit. No explicit "no CDN" sentence for Releases on this page. => Releases are fine for installers (tens of MB); shipping a 1.6 GB model to every user per version is exactly the "significantly excessive" pattern.

### Source: WinSparkle
URL: https://winsparkle.org/
- C DLL, "no extra runtime dependencies"; appcast XML; DSA/EdDSA signature; MIT; copyright 2026. It only prompts and launches the downloaded installer (installer does the replacement). Usable from Python only via ctypes; adds a native dependency for little gain over a hand-rolled JSON check. Not recommended.

### Source: Hugging Face Hub storage limits
URL: https://huggingface.co/docs/hub/storage-limits
- Public repos: "Best-effort" free storage; "Files are served to the users using CloudFront"; 500GB hard per-file limit. No download-bandwidth cap stated for public models. => ivrit-ai's model is already on HF; the app should download it from there (hf_hub_download / faster-whisper's own download), which is the model's canonical, licence-attributed home and costs the owner nothing.

### Source: Velopack vpk (Windows) CLI reference + integrating overview
URLs: https://docs.velopack.io/reference/cli/content/vpk-windows ; https://docs.velopack.io/integrating/overview
- `--channel` "The channel to use for this release" (default win) => stable/beta = two channel names (e.g. `win` and `win-beta`), each with its own releases.{channel}.json feed in the same GitHub Releases.
- `--delta` "Disable or set the delta generation mode" (default BestSpeed) => delta packages generated automatically.
- Signing: `--signParams` (signtool), `--signTemplate` (custom command), `--azureTrustedSignFile`. Optional; unsigned works but SmartScreen warns.
- `vpk upload github --repoUrl --token --publish --pre --releaseName`; `vpk download github --pre` "Get latest pre-release instead of stable".
- Install layout: "%LocalAppData%\{packId}\current" + Update.exe + sq.version; per-user, no admin. "During updates, only the `current` folder is replaced." App restarts through Update.exe (old process exits, new files swapped in).
- Rollback: "it deletes old local packages from the packages directory, keeping only the currently installed version and the latest local version" => no built-in rollback; rollback = publish a higher version that is the old code (or keep the previous full .nupkg manually).
- Quote: "Since `current` is replaced with the new version during updates, it's not safe to store settings, logs, etc in the `current` dir." => user data must live in %AppData%\DeskIT (roaming) / %LocalAppData%\DeskIT\data.
- Python app must call VelopackApp.build().run() first thing (hooks for install/update/uninstall args).

### Source: Squirrel.Windows repo
URL: https://github.com/Squirrel/Squirrel.Windows
- Notice: "We are looking for help with maintaining this important project - please read the discussion in #1470". .NET-only, effectively legacy; Velopack is its Rust rewrite by the Clowd.Squirrel author and offers "Automatic migrations" from Squirrel. Not for Python.

### tufup version: PyPI latest 0.10.0 (libraries.io); date not confirmed (uncertainty).
### Inno Setup CloseApplications page + winget AUTHORING_MANIFESTS: fetch failed (frames / 404) - retry other URLs.

### Source: Inno Setup help, CloseApplications
URL: https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm
- Quote: "Setup will pause on the Preparing to Install wizard page if it detects applications using files that need to be updated by the [Files] or [InstallDelete] section, showing the applications and asking the user if Setup should automatically close the applications and restart them after the installation has completed." Uses Windows Restart Manager; default "yes"; `force` "will force close ... may cause the user to lose unsaved work". In silent mode (/SILENT, /VERYSILENT) with yes/force it closes and restarts without prompting. => "Inno re-run" update = app downloads new Setup.exe, verifies sha256, runs it with /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS, exits. Works for a pythonw + Tk app; Restart Manager needs the app to register (RegisterApplicationRestart) for a clean relaunch, otherwise Inno relaunches by exe path.

### Source: Microsoft Learn, Submit your manifest (winget-pkgs), updated 2026-07-14
URL: https://learn.microsoft.com/en-us/windows/package-manager/package/repository
- Expectations: "The installer supports non-interactive modes."; "The installer comes directly from the publisher's website."; "The installer and application are virus free."; "installs and uninstalls correctly for both administrators and non-administrators"; "one manifest file per submission"; automated pipeline + "manually reviewed by a moderator"; InstallerSha256 must match; HTTPS required; Validation-Indirect-URL rejects redirectors. GitHub Releases download URLs are accepted in practice (thousands of packages use github.com/.../releases/download/...). No code-signing requirement stated; unsigned Inno installers are accepted (uncertainty: unsigned installers may trip the reputation/URL test; many OSS unsigned packages exist).
- winget does NOT auto-update apps; the user runs `winget upgrade --all` (or a 3rd-party UI). It is a discovery/install channel, not an in-app updater. Each version needs a PR (wingetcreate update in CI with a fork token).

### Source: PyPI velopack
URL: https://pypi.org/project/velopack/
- Latest 1.2.0, released 2026-06-03; Python >=3.8; MIT; Windows x64/x86/ARM64 wheels (cp37-abi3). => actively maintained, native Rust core, matches DeskIT's Python 3.11.

### Source: semver.org
- MAJOR incompatible changes / MINOR backward-compatible features / PATCH fixes. Pre-release: "appending a hyphen and a series of dot separated identifiers"; precedence "1.0.0-alpha < ... < 1.0.0-rc.1 < 1.0.0". Velopack accepts semver2 pre-release tags (e.g. 1.4.0-beta.2) and `vpk download github --pre`. Windows "File version" resources need 4 numeric parts; map 1.4.2 -> 1.4.2.0.

### tufup PyPI: page failed to load (uncertainty on release date; libraries.io says 0.10.0).

## Cross-cutting design points (apply to whichever tool)
- Replace-while-running: Windows locks loaded .exe/.pyd/.dll files, so every scheme is "download aside, exit, swap, relaunch". Velopack (Update.exe swaps `current`), tufup (batch script in new process), Inno re-run (Restart Manager) all do this; a hand-rolled updater must write the same helper.
- Integrity: always pin a sha256 in the feed and verify before running anything (Velopack's releases.json carries the hash; tufup has TUF signatures; hand-rolled = sha256 in latest.json fetched over HTTPS from the owner's own GitHub repo). Signing the installer needs a certificate the owner cannot get for free (see code-signing source) unless the project is open source + SignPath, or goes through the Microsoft Store.
- Channels: Velopack `--channel win` / `--channel win-beta` (two feeds in the same GitHub Releases) or `--pre` pre-releases; tufup pre-release channel via PEP 440; hand-rolled = latest.json + latest-beta.json; winget = separate PackageIdentifier (e.g. Yoav.DeskIT.Beta).
- Semver: MAJOR.MINOR.PATCH with -beta.N pre-releases; expose as 4-part Windows file version; store `config_version` in the user's settings file so migrations run on first launch after an update.
- User data outside the install dir: settings, .env keys, history and models MUST NOT live in the package folder (Velopack quote above); use %APPDATA%\DeskIT (settings, keys, history) and %LOCALAPPDATA%\DeskIT\models + \cuda (large, per-machine). Uninstall leaves them unless the user ticks "remove my data".
- Rollback: none of the tools keep old versions for the user (Velopack deletes older packages). Practical rollback = (a) owner re-publishes the previous build as a higher patch version, (b) app keeps a backup of the last good settings file, (c) a "previous version" link in the guide. Velopack's `current` swap is atomic enough that a failed update leaves the old `current` usable.
- Big binaries: the installer must exclude the 1.6 GB model AND the ~2 GB nvidia CUDA wheels. Ship a CPU-only base (~150-300 MB with CTranslate2 + Tk), download the model from Hugging Face on first run, and offer "Enable GPU" which downloads the nvidia wheels from PyPI (free, CDN-served) into %LOCALAPPDATA%\DeskIT\cuda. Otherwise every update would be multi-GB and users would re-download the model per version.
- GitHub Releases as update feed: the check hits api.github.com/repos/.../releases/latest (60 req/h per IP unauthenticated) or, with Velopack, the releases.{channel}.json asset via the release download URL. One check per launch + a manual "Check now" is far inside limits.

## Options compared
| Option | Python fit | Replace-while-running | Integrity | Channels | Cost / maintenance | Verdict |
|---|---|---|---|---|---|---|
| Velopack 1.2.0 (PyPI 2026-06-03, MIT) | first-class (PyInstaller --onedir) | yes, Update.exe swaps `current`; per-user %LocalAppData%, no admin | sha in feed; optional signtool | `--channel`, `--pre` | free; GitHub Releases hosting built in (`vpk upload github`); delta packages | RECOMMENDED |
| tufup 0.10.0 (MIT) | native Python | batch script relaunch | TUF-signed metadata (strongest) | pre-release channel | free; static host (GitHub Pages); owner manages TUF keys; ~1 maintainer; no installer, shortcuts or uninstall entry | runner-up; more owner ops |
| PyUpdater | Python | yes | keys | yes | last release 4.0 on 2021-04-19 => dead | NO |
| Squirrel.Windows | .NET only | yes | - | - | "looking for help with maintaining"; superseded by Velopack | NO |
| WinSparkle | C DLL via ctypes | no (launches installer) | DSA/EdDSA appcast | appcast per channel | free but a native dependency that only prompts | NO |
| Hand-rolled latest.json + swap script | trivial | must write own swap helper | sha256 you compute | latest.json / latest-beta.json | free; ~200 lines to own forever incl. edge cases | fallback only |
| Inno Setup re-run | any | Restart Manager (`CloseApplications`, /SILENT /RESTARTAPPLICATIONS) | sha256 checked by app before running Setup | separate download URLs | free; full re-download each update, no deltas; UAC-free if `PrivilegesRequired=lowest` | acceptable but heavier updates |
| winget | any installer | winget closes nothing; user runs `winget upgrade` | InstallerSha256 in manifest | separate package id | free; PR per version, moderator review | ADD later as discovery channel, not the updater |
| MSIX + .appinstaller | poor (pythonw, hooks, virtualised AppData) | Windows does it | trusted cert REQUIRED | UpdateURI | cert not free for an Israeli individual ("Individuals: USA and Canada only"; OV $150-300/yr) | NO (unless Store route later) |

## Recommendation for DeskIT
Use **Velopack** (`pip install velopack`, `vpk pack` over a PyInstaller `--onedir` build, `vpk upload github`). Reasons: it is the only maintained framework with a first-class Python client (1.2.0, June 2026), it installs per-user without admin, swaps files while running via Update.exe, generates delta packages so a typical DeskIT update is a few MB, hosts everything on GitHub Releases (free; "no limit on the total size of a release, nor bandwidth usage"), gives stable/beta via `--channel`, and its own docs enforce the right habit: keep settings/keys/history/models out of `current`. An unsigned Setup.exe shows a SmartScreen "unrecognized app" warning; document the "More info > Run anyway" click in the guide and, if DeskIT becomes open source, apply to SignPath Foundation for free OV signing. Keep the ivrit-ai model on Hugging Face (downloaded by the app, hash-verified) and the CUDA wheels on PyPI (opt-in "Enable GPU"); ship a CPU-only ~200 MB base. Add a winget manifest later (wingetcreate in the release workflow) as a second install path; it does not replace in-app updates. Rollback = re-publish the previous build under a new patch version.

## What the owner must do by hand
- GitHub: create a public repo (or private repo with public releases) and a fine-grained token with `contents: write` for `vpk upload github` / GitHub Actions. Free.
- Signing: nothing is free for an Israeli individual. Either accept SmartScreen warnings, open-source the project and apply to SignPath Foundation (form + review), or register a Microsoft Store developer account (individual fee, verify) and ship MSIX via the Store where Microsoft signs for free.
- Hugging Face: nothing to host; confirm the ivrit-ai model licence permits download-on-install and credit it in the guide.
- winget (later): fork microsoft/winget-pkgs, run `wingetcreate new` once, then `wingetcreate update` per release; answer moderator labels within 10 days or the PR closes.
- Decide the AppId (`DeskIT`), the two channel names (`win`, `win-beta`) and the first public version (1.0.0); versions cannot go backwards in Velopack feeds.

## Sources
- GitHub Docs, About releases: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- GitHub Acceptable Use Policies: https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies
- Velopack Python guide: https://docs.velopack.io/getting-started/python ; vpk Windows CLI: https://docs.velopack.io/reference/cli/content/vpk-windows ; integrating overview: https://docs.velopack.io/integrating/overview ; repo: https://github.com/velopack/velopack ; PyPI: https://pypi.org/project/velopack/
- tufup: https://github.com/dennisvang/tufup ; https://libraries.io/pypi/tufup
- PyUpdater PyPI: https://pypi.org/project/PyUpdater/
- Squirrel.Windows: https://github.com/Squirrel/Squirrel.Windows
- WinSparkle: https://winsparkle.org/
- Microsoft Learn, Code signing options (2026-08-29): https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
- Microsoft Learn, MSIX auto-update overview (2026-04-10): https://learn.microsoft.com/en-us/windows/msix/app-installer/auto-update-and-repair--overview
- Microsoft Learn, Submit manifest to the winget repo: https://learn.microsoft.com/en-us/windows/package-manager/package/repository
- Inno Setup CloseApplications: https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm
- Hugging Face storage limits: https://huggingface.co/docs/hub/storage-limits
- semver: https://semver.org/

## Uncertainties
- tufup 0.10.0 release date and Python 3.11+ support not confirmed (PyPI page failed to load).
- Whether Velopack's Python UpdateManager with a GitHub source calls api.github.com (60 req/h per IP unauthenticated) or the static releases.{channel}.json download URL; either is fine at one check per launch, but verify before shipping.
- Microsoft Store individual developer registration fee (historically ~$19 one-time) not verified on a primary page in this run.
- winget acceptance of unsigned Inno installers: policy pages state no signing requirement, but reputation/Defender checks may flag unsigned binaries; expect possible manual review.
- GitHub has no explicit "no CDN" clause on the AUP page read; only "significantly excessive" bandwidth wording. Treat multi-GB model assets as risky regardless.
- Velopack + pythonw/Tk + global keyboard hook: the app must handle `--veloapp-*` args before creating the Tk root; untested here (plan only).
- Size of a CPU-only PyInstaller onedir build with CTranslate2 (~200 MB estimate) not measured.
