# packaging

**Question:** Packaging a Python 3.11 + Tkinter + pywin32/ctypes + faster-whisper (CTranslate2 with CUDA from pip nvidia wheels, ~2 GB native) Windows app for end users in 2026. Compare PyInstaller onedir, Nuitka, cx_Freeze, and "embeddable CPython + wheelhouse installed by the installer". Cover antivirus/SmartScreen false positives per tool, size, startup time, CUDA DLL search-path issues, Tk bundling gotchas, pythonw (no console), installer framework (Inno Setup vs NSIS vs WiX vs MSIX). Check what open-source Whisper desktop apps for Windows actually ship (Buzz, WhisperWriter, Vibe, Handy).

Date of research: 2026-09-16. Findings appended as each source is read.

## Findings log

### S1. PyInstaller AV false positives (search round 1)
- Root cause: bootloader hash is shared with malware built with PyInstaller; --onefile (self-extracts to temp) trips heuristics far more than --onedir. pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/ ; github.com/pyinstaller/pyinstaller/issues/6754
- Mitigations cited: onedir (default), rebuild bootloader locally (different hash), code-sign. Signing "dramatically reduces" Defender/SmartScreen flags but does not eliminate them.
- Status: ongoing problem 2020-2026 (issue tracker still active).

### S2. CTranslate2 CUDA DLL search path on Windows (search round 1)
- pip wheels nvidia-cublas-cu12 / nvidia-cudnn-cu12 put DLLs under site-packages/nvidia/<pkg>/bin; Windows never adds that to DLL search; CTranslate2 loads CUDA lazily so failure ("Library cublas64_12.dll is not found or cannot be loaded") surfaces at FIRST INFERENCE, not at import. github.com/jaredrhod/backtalk/issues/28 ; github.com/OpenNMT/CTranslate2/issues/1630
- Fix pattern: prepend the wheels' bin dirs to os.environ["PATH"] before WhisperModel(); os.add_dll_directory alone is not enough (native loader uses PATH).
- ctranslate2>=4.5 needs cuDNN 9 -> CUDA >= 12.3 driver; pin 4.4.0 if driver unknown. github.com/SYSTRAN/faster-whisper/issues/1401

### S3. Buzz (chidiwilliams) Windows shipping (search round 1)
- PyInstaller build, unsigned, SmartScreen "More info -> Run anyway" documented as expected; installer + zip on GitHub/SourceForge. Reported PyInstaller unpack failures on Windows (issue #1403, #1127). github.com/chidiwilliams/buzz

### S4. Vibe (thewh1teagle) (search round 1)
- Tauri (Rust) + whisper.cpp; Windows: NSIS setup .exe + portable zip; separate builds for standard/Vulkan and CUDA. Not a Python app -> not a direct packaging template, but proves "separate GPU-flavor downloads" pattern. github.com/thewh1teagle/vibe ; v2.tauri.app/distribute/windows-installer/

### S5. Azure Trusted Signing / Artifact Signing (search round 1, needs primary verification)
- Individuals allowed (public preview since 2024); Basic ~$9.99/month (5,000 signatures). Renamed "Azure Artifact Signing" 2026. Q&A thread: individual signup hit an Entra ID P2 licence requirement for role creation (learn.microsoft.com/en-us/answers/questions/5595324). VERIFY on pricing page.

### S6. Azure Trusted/Artifact Signing pricing page (primary, fetched 2026-09-16)
- azure.microsoft.com/en-us/pricing/details/trusted-signing/ now shows "Base price (monthly): $-" placeholders, quotas "Basic 5,000 signatures/month", "Premium 100,000", and "Request a pricing quote". The $9.99/mo figure comes from secondary sources (devclass 2026-01, gdgsoft) - NOT verifiable on the primary page today. Eligibility for an Israeli individual: not stated on page; individual public preview (2024) listed a country allowlist. UNCERTAINTY.

### S7. Handy (cjpais) primary README
- "Handy is built as a Tauri application ... Backend: Rust for system integration, audio processing, and ML inference." Whisper GGML/GGUF via whisper.cpp + Parakeet V3 (CPU). GPU: "Intel, AMD, and NVIDIA GPUs on Windows and Linux" (Vulkan). winget package exists but "not maintained by the Handy developers". Tauri updater with signature verification. MIT, brand assets excluded. github.com/cjpais/Handy

### S8. WhisperWriter (savbell) primary README
- Not packaged at all: "To set up and run the project" via venv + pip; roadmap: "Creating standalone executable file". Python 3.11, faster-whisper local by default or OpenAI API. GPL. -> the closest analogue to DeskIT ships NO installer. github.com/savbell/whisper-writer

### S9. Nuitka common-issues page (primary)
- "Some Antivirus Vendors may flag compile binaries using Nuitka's default settings on Windows as malware." Recommended remedy = Nuitka Commercial (paid) -> conflicts with zero-cost constraint. No-console: --windows-console-mode=disable; debug via --force-stdout-spec. Tkinter handled by plugin (tk-inter). nuitka.net/user-documentation/common-issue-solutions.html

### S10. PyInstaller operating-mode page (primary)
- Default = one-folder. One-file: "The bootloader uncompresses the support files and writes copies into the temporary folder. This can take a little time." Console: "By default the bootloader creates a command-line console"; --noconsole/--windowed or a .pyw script suppresses it. pyinstaller.org/en/stable/operating-mode.html

### S11. Nuitka vs PyInstaller AV (secondary, dev.to 2025-12)
- Claims Nuitka FP rate "drastically lower" because output is real compiled C, no runtime unpack. No hard 2025 numbers. dev.to/weisshufer/... ; dev.to/il3ven/nuitka-vs-pyinstaller-distributing-a-python-application-3ah7

### S12. Embeddable CPython + wheelhouse (secondary)
- Embeddable zip has no pip/venv; needs get-pip + editing python311._pth to enable site-packages; "almost fully isolated from the user's system" (docs.python.org/3/using/windows.html). Wheelhouse dir enables offline pip install. Tools: win_app_packager (Inno-oriented), py2win. Known gotcha: embeddable zip does NOT include tkinter/tcl (must copy from a full install). VERIFY on python docs.

### S13. Installer frameworks (secondary)
- Inno Setup: free, small, EXE; NSIS: free, EXE (Tauri default); WiX: free, produces MSI, XML-heavy; MSIX: Store/sideload, requires signing cert always. Forum lore against per-user installs is about UAC, but per-user (LocalAppData) is exactly what unsigned indie apps do to avoid UAC. blog.doubleslash.de/... ; advancedinstaller.com/choosing-the-right-windows-packaging-tool-as-developer.html

### S14. Python docs, embeddable package (primary) docs.python.org/3/using/windows.html
- "The embedded distribution is a ZIP file containing a minimal Python environment. It is intended for acting as part of another application, rather than being directly accessed by end-users."
- "Tcl/tk (including all dependents, such as Idle), pip and the Python documentation are not included." -> Tkinter must be copied from a full install (tcl/, tkinter/, _tkinter.pyd, tcl86t.dll, tk86t.dll, zlib1.dll) by hand.
- "Third-party packages should be installed by the application installer alongside the embedded distribution. Using pip to manage dependencies as for a regular Python installation is not supported with this distribution, though with some care it may be possible to include and use pip for automatic updates." -> vendoring/wheelhouse is the officially blessed pattern.
- pythonw.exe is included in the embeddable zip (windowed launcher).

### S15. Buzz releases (primary) github.com/chidiwilliams/buzz/releases
- v1.4.5 (2026-08-23). "download all three Windows files (one *.exe and both *.bin files) and run the *.exe" -> installer split into multi-part because GitHub's 2 GB/asset limit. "App is not signed, you will get a warning when you install it". Asset sizes did not load (GitHub error). UNCERTAINTY on exact sizes.

### S16. cx_Freeze docs (primary) cx-freeze.readthedocs.io/en/stable/setup_script.html
- "On Windows, you can build a simple installer ... by running the setup script as: python setup.py bdist_msi". base = "gui" suppresses console (Win32GUI name removed for 3.13+). No CUDA-specific hooks; include_files copies extra DLLs manually. MSI from bdist_msi is bare (no per-user/auto-update story documented).

### S17. Azure Artifact Signing eligibility (primary, MS Learn MSIX signing page, ms.date 2026-04-14)
- "Eligibility for Public Trust certificates: Available to organizations in the USA, Canada, the European Union, and the United Kingdom, and to individual developers in the USA and Canada. Organizations must have a verifiable tax history of three or more years."
- => An Israeli solo developer with no company is NOT eligible for Artifact Signing today. Cost table on the same page: "Basic: ~$10/month"; "OV code signing certificate from a CA $300-500/year"; "Microsoft Store distribution: Signed by the Store on submission: Free".
- "like all non-Store distribution, new apps will still show SmartScreen warnings until sufficient download history builds - this typically takes several weeks."
- MSIX: "Windows requires MSIX packages to be signed with a valid code signing certificate." -> MSIX outside the Store is impossible without a cert; self-signed only for dev/test.
- learn.microsoft.com/en-us/windows/msix/package/signing-package-overview

### S18. faster-whisper README (primary) github.com/SYSTRAN/faster-whisper
- "GPU execution requires the following NVIDIA libraries to be installed: cuBLAS for CUDA 12, cuDNN 9 for CUDA 12." pip: nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*  "Purfview's whisper-standalone-win provides the required NVIDIA libraries for Windows & Linux in a single archive." ctranslate2 4.4.0 for cuDNN 8; 3.24.0 for CUDA 11.

### S19. Inno Setup (primary) jrsoftware.org/isinfo.php
- "Extensive support for both administrative and non administrative installations." "right-to-left language support", "Unicode installs", x64 + Arm64. Licence: LICENSE.TXT - free incl. commercial use (verify wording below).

### S20. Inno Setup LICENSE.TXT (primary) jrsoftware.org/files/is/license.txt
- "Permission is granted to anyone to use this software for any purpose, including commercial applications" - no fee. (The "commercial license" line on isinfo.php from the earlier fetch was a summariser error; the licence itself is free.)

### S21. Purfview whisper-standalone-win releases (primary, assets failed to load)
- Faster-Whisper-XXL is PyInstaller-based ("Updated: pyinstaller to 6.16.0"), ships as zip archives, unsigned, with a separate "cuBLAS and cuDNN" release holding CUDA 11/12 lib archives. Sizes not retrieved. UNCERTAINTY on sizes. github.com/Purfview/whisper-standalone-win/releases

### S22. SmartScreen reputation (primary, MS Learn, ms.date 2026-05-04) learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
- "When a file is not signed, SmartScreen reputation must build for each new version of your files, starting with zero reputation. Reputation cannot transfer from previous versions unless both were signed using the same publisher identity."
- "No signature: Warning - 'Windows protected your PC'; User must choose 'Run anyway' ... Enterprise policy can prevent continuation entirely." "Self-signed Certificate: Same behavior as no signature."
- "EV certificates no longer bypass SmartScreen."
- "it can take several weeks and hundreds of clean installs from a wide audience." "There is no need (or mechanism) to manually submit a file for SmartScreen reputation review for consumer endpoints."
- "Store-distributed apps are signed by a Microsoft certificate and are never subject to SmartScreen download warnings."
- "On Windows 11 devices, the Smart App Control feature may supersede SmartScreen ... will block execution of unsigned files unless the file has a positive reputation."
- Artifact Signing "Starts at $9.99/month" (this page states it; pricing page shows "$-").

### S23. SignPath Foundation free OSS signing (primary) signpath.org/terms
- "The project must use an OSI-approved Open Source license without commercial dual-licensing for all components." "The project may not contain any proprietary, non open-source component". Cert is issued in SignPath Foundation's name; MFA + manual approval per release; must publish a code signing policy. -> viable zero-cost signing ONLY if DeskIT is fully open-sourced under an OSI licence. Individual maintainers OK as team members.

### S24. PyInstaller usage (primary) pyinstaller.org/en/stable/usage.html
- --windowed/--noconsole: "Windows and macOS: do not provide a console window for standard i/o." --contents-directory names the onedir _internal folder. --collect-all <pkg> pulls submodules+data+binaries (use for ctranslate2, nvidia.*). --uac-admin exists (do NOT use; per-user install). Tk: PyInstaller's built-in tkinter hook copies tcl/tk trees automatically (the usage page only mentions Tcl/Tk for the splash screen).

### S25. Nuitka Commercial - price not indexed (nuitka.net/commercial/purchase.html). Known: "Due to the relatively low price, no trials are available." Exact price UNCERTAIN; any price > 0 breaks the zero-cost rule anyway.

### S26. nvidia wheel sizes - PyPI file lists not returned by search. Owner's own venv says ~2 GB for cublas+cudnn win_amd64. UNCERTAINTY; verify with `pip download` sizes.

### S27. winget community repo (secondary + MS Learn) learn.microsoft.com/en-us/windows/package-manager/package/repository
- Inno Setup, Nullsoft, MSI, portable, zip all accepted installer types; "All tools must support a silent install." Unsigned installers accepted; automated validation + Defender scan on PR. Free. Does NOT remove SmartScreen warning for direct downloads but winget itself does not show SmartScreen.

### S28. GitHub Releases limits (primary) docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- "Each file included in a release must be under 2 GiB." "There is no limit on the total size of a release, nor bandwidth usage." -> CUDA libs (~2 GB) must be a separate asset or split; explains Buzz's 3-file download.

### S29. Nuitka user manual (primary) nuitka.net/user-documentation/user-manual.html
- --windows-console-mode: force (default) / disable / attach / hide. Needs a C compiler: Visual Studio, or "The MinGW64 compiler (used with --mingw64) option, must be the one Nuitka downloads." Open issues: tk-inter plugin arg errors (#2730), "Tkinter program does not run with --windows-console-mode=disable" (#3019). Nuitka OSS is Apache-2.0 (LICENSE.txt on GitHub); compiled output is yours to distribute.

### S30. PyInstaller + pywin32 (primary changelog) pyinstaller.org/en/stable/CHANGES.html
- PyInstaller 6.x depends on pywin32-ctypes (pure Python) and has hooks for pywin32 (win32gui/win32api etc.) and pywintypes DLL; well-trodden. Raw ctypes hooks (DeskIT's keyboard hook) need no packaging hook at all - ctypes loads system DLLs by name.

---

## Options compared

| Criterion | PyInstaller onedir | Nuitka standalone | cx_Freeze | Embeddable CPython + wheelhouse (installer-installed) |
|---|---|---|---|---|
| Cost | Free (GPL w/ exception) | Free (Apache-2.0); AV-fix advice = paid Commercial | Free | Free (PSF licence) |
| AV / SmartScreen | Worst: shared bootloader hash, thousands of prior malware hits; onedir better than onefile (S1) | Better (real compiled C), but Nuitka docs admit "Some Antivirus Vendors may flag" default builds (S9, S11) | Similar to PyInstaller (frozen stub + zip); less malware abuse so fewer hits, anecdotal | Best: python.exe/pythonw.exe are stock python.org binaries with existing reputation; only the installer .exe is "new" and SmartScreen still warns once (unsigned) |
| Size | ~ venv minus unused stdlib; CUDA libs ~2 GB dominate all options | Same, plus compiled .pyd per module | Same | = venv size; model + CUDA fetched at first run so installer can be ~150-300 MB |
| Startup | Fast (no extraction) | Fastest (compiled) | Fast | = normal Python start; whisper model load dominates anyway |
| CUDA DLL path | Must --collect-all nvidia.* and set PATH at runtime (S2); brittle | Copy DLLs via --include-data-dir; same PATH fix | include_files by hand; same PATH fix | Wheels land in site-packages/nvidia/*/bin unchanged; same 6-line PATH fix in main(); pip resolves versions |
| Tk | Auto hook, mature | tk-inter plugin has open bugs (#2730, #3019) | Works; manual TCL_LIBRARY sometimes | NOT in embeddable zip (S14) - copy tcl/, tkinter, _tkinter.pyd, tcl86t/tk86t.dll from a full 3.11 install once |
| No console | --windowed (S24) | --windows-console-mode=disable (S29) | base="gui" (S16) | pythonw.exe already in the zip; shortcut targets pythonw.exe app.pyw |
| Updates | Re-download whole bundle | Same | Same | Ship only changed code/wheels; docs: "with some care it may be possible to include and use pip for automatic updates" (S14) |
| Build complexity | Medium; hidden-import whack-a-mole | High; C compiler, long builds, plugin bugs | Medium | Low: pip download -d wheelhouse, unzip embeddable, one Inno script; no freezing step |
| Field debugging | Poor (frozen tracebacks) | Poor | Poor | Good: real .py files; user can run python.exe -m deskit --diagnose |

Installer frameworks:

| | Inno Setup | NSIS | WiX (MSI) | MSIX |
|---|---|---|---|---|
| Cost/licence | Free incl. commercial (S20) | Free (zlib) | Free (MS-RL) | Free tooling, cert mandatory |
| Per-user, no UAC | Native "non administrative installations" (S19) | Yes (RequestExecutionLevel user) | Possible, fiddly | Yes |
| Unsigned OK | Yes (SmartScreen warn once) | Yes | Yes | NO: "Windows requires MSIX packages to be signed with a valid code signing certificate" (S17) |
| RTL/Hebrew UI | Built-in RTL + Unicode (S19) | Unicode NSIS, RTL patchy | N/A | Store UI |
| Download-at-install (model/CUDA) | Pascal script / Inno Download Plugin, or in-app | Plugins | Custom action, painful | No |
| winget accepted | Yes (S27) | Yes | Yes | Yes |
| Used by | most indie Python apps | Tauri (Vibe, Handy) | enterprise | Store apps |

What the comparable open-source Whisper apps actually ship (S3, S4, S7, S8, S15, S21):
- Buzz (Python/Qt): PyInstaller, unsigned, 3-part download because of the 2 GiB asset cap; "App is not signed, you will get a warning".
- WhisperWriter (Python 3.11 + faster-whisper, the closest twin to DeskIT): no installer at all; venv + pip from source; exe "on the roadmap".
- Purfview Faster-Whisper-XXL: PyInstaller zip, unsigned, CUDA libs as a separate archive.
- Vibe and Handy (Rust/Tauri + whisper.cpp): NSIS setup.exe + portable zip, separate CUDA/Vulkan flavours, Tauri signed updater; Handy on winget via a community manifest.
- Nobody in this class ships a signed single installer with CUDA inside. All push GPU libs and models to a separate download.

## Recommendation for DeskIT

Ship "embeddable CPython 3.11 + vendored wheelhouse" through a per-user Inno Setup installer; do not freeze.

Why, in order of weight:
1. Zero-cost signing is off the table for this owner: Azure Artifact Signing individuals are "USA and Canada" only (S17), SignPath Foundation needs a fully OSI-licensed project (S23), OV certs are "$300-500/year" (S17). So every option ships unsigned and gets the same one-time "Windows protected your PC" prompt. The remaining differentiator is Defender heuristics, and stock pythonw.exe from python.org has the best reputation on the table while PyInstaller's bootloader has the worst (S1, S22).
2. CTranslate2's CUDA loader wants the DLLs on PATH (S2); in the wheelhouse layout the paths are deterministic: app\python\Lib\site-packages\nvidia\{cublas,cudnn,cuda_runtime}\bin. Freezers must re-discover 2 GB of DLLs on every build.
3. Tk is the only thing the embeddable zip lacks (S14); copying the tcl/tk tree from a full 3.11 install once is a scripted step and avoids Nuitka's open tk-inter bugs (S29).
4. Updates become cheap: a new version is a small code zip plus changed wheels. The CUDA wheels and the 1.6 GB ivrit-ai model are downloaded on first run by the app itself into %LOCALAPPDATA%\DeskIT\cache, so the installer stays a few hundred MB and under GitHub's 2 GiB per-file cap (S28). First launch offers CPU (default, small, int8) or "faster on NVIDIA" opt-in that pip-installs the nvidia wheels into the app's own site-packages.
5. Field debugging: users can run python\python.exe -m deskit --diagnose; frozen builds cannot.
6. Inno Setup over NSIS: free for commercial use (S20), first-class non-admin per-user install and RTL Hebrew (S19), one .iss file, accepted by winget (S27). Skip WiX (MSI complexity, no benefit when unsigned) and MSIX (cert mandatory, S17).

Concrete layout: %LOCALAPPDATA%\Programs\DeskIT\python\ (embeddable + tcl/tk) and \app\ (source). No custom launcher .exe (a new unknown hash); the Start-menu shortcut runs python\pythonw.exe app\deskit.pyw. Settings/keys/history in %APPDATA%\DeskIT; model and CUDA cache in %LOCALAPPDATA%\DeskIT\cache. python311._pth lists Lib\site-packages and "import site". Prepend the nvidia bin dirs to os.environ["PATH"] before importing faster_whisper. Pin ctranslate2 (4.4.0 if the driver is unknown; otherwise latest with a CUDA >= 12.3 driver check that falls back to CPU with a visible message, never silently).

Fallback if the per-user Python tree proves fragile: PyInstaller onedir with --windowed --collect-all ctranslate2 --collect-all nvidia and a locally rebuilt bootloader; never onefile; not Nuitka (paid AV remedy, tk bugs, compile times).

Reputation plan while unsigned: publish through winget (community manifest, Inno /VERYSILENT), keep file names stable across versions, tell users in the guide about "More info -> Run anyway", and document that Smart App Control-enabled Windows 11 machines will block it outright (S22).

## What the owner must do by hand
- Nothing in this plan costs money. Accounts: GitHub (releases), a winget-pkgs pull request from that GitHub account (needs a silent-install switch and a fixed download URL per version).
- Decide the licence. If DeskIT becomes fully OSI open source (MIT/GPL, no proprietary component), apply to SignPath Foundation (signpath.org, MFA, publish a signing policy). That is the only zero-cost route to a signed installer for a non-US/CA individual.
- Not available to him today: Azure Artifact Signing (individuals USA/Canada only); Microsoft Store needs a developer account whose fee was not verified here (treat as non-zero).
- Build machine: install full Python 3.11 once (to copy tcl/tk), Inno Setup 6, run pip download for win_amd64 cp311 wheels, test on a clean Windows 11 VM with Defender on and no NVIDIA driver, VirusTotal-scan the first installer.
- Check the ivrit-ai model licence for first-run download / redistribution (separate research question).

## Sources
- pyinstaller.org/en/stable/operating-mode.html ; /usage.html ; /CHANGES.html
- pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/ ; github.com/pyinstaller/pyinstaller/issues/6754
- nuitka.net/user-documentation/common-issue-solutions.html ; /user-manual.html ; github.com/Nuitka/Nuitka/issues/2730 ; /3019
- cx-freeze.readthedocs.io/en/stable/setup_script.html
- docs.python.org/3/using/windows.html (embeddable package)
- github.com/SYSTRAN/faster-whisper ; github.com/OpenNMT/CTranslate2/issues/1630 ; github.com/jaredrhod/backtalk/issues/28
- learn.microsoft.com/en-us/windows/msix/package/signing-package-overview (ms.date 2026-04-14)
- learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation (ms.date 2026-05-04)
- azure.microsoft.com/en-us/pricing/details/trusted-signing/ ; learn.microsoft.com/en-us/azure/artifact-signing/overview
- signpath.org/terms
- jrsoftware.org/isinfo.php ; jrsoftware.org/files/is/license.txt
- learn.microsoft.com/en-us/windows/package-manager/package/repository
- docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- github.com/chidiwilliams/buzz/releases ; github.com/savbell/whisper-writer ; github.com/thewh1teagle/vibe ; github.com/cjpais/Handy ; github.com/Purfview/whisper-standalone-win/releases
- dev.to/weisshufer/from-pyinstaller-to-nuitka-convert-python-to-exe-without-false-positives-19jf (secondary)

## Uncertainties
- Artifact Signing price: the pricing page shows "$-" placeholders today; "$9.99/month" comes from the MS Learn SmartScreen page and press. Moot unless eligibility expands to Israel; re-check yearly.
- Exact win_amd64 sizes of nvidia-cublas-cu12 / nvidia-cudnn-cu12 9.x wheels, and Buzz/Purfview asset sizes (GitHub asset lists failed to load).
- Nuitka Commercial price (page not indexed); moot under the zero-cost rule.
- Whether Smart App Control is on for target users' Windows 11 Home machines (only enabled on clean installs that pass evaluation); it decides how many users cannot run an unsigned app at all.
- Microsoft Store individual developer registration fee (not verified in this run); the Store is the only route to zero SmartScreen warnings.
- cx_Freeze AV false-positive rate has no primary data; grouped with PyInstaller by construction, not measurement.
- The embeddable-Python approach's Defender hit rate is inferred from the reputation mechanism (S22), not measured. Scan the first installer on VirusTotal.
