# competitors

Question: How comparable dictation/voice-typing desktop apps distribute and onboard in 2026, especially open-source local-whisper ones (Handy, Vibe, Buzz, WhisperWriter, Speech Note, SuperWhisper, Wispr Flow, Talon, Win+H Hebrew, ivrit.ai/Dicta/Israeli products). Per app: install, pricing, model download/size, GPU/CPU, API key storage, first-run, updates, bug reporting. Shared patterns, GitHub complaints (antivirus, model download failures, no GPU). Realistic audience and channels for a free Hebrew dictation app for Windows.

Date of research: 2026-09-16

## Findings (appended per source)

### Search round 1 (2026-09-16, search snippets, to verify on primary pages)
- Handy (cjpais): Tauri (Rust+React), Win x64+ARM, normal installer, also `winget install cjpais.Handy`; no model bundled, first run asks which model to download; ships Whisper Small/Medium/Turbo/Large, Parakeet V2/V3, Moonshine, custom GGML; Parakeet = CPU-only (Intel 6th gen+), Whisper benefits from GPU. Site handy.computer + GitHub releases. Sources: github.com/cjpais/handy, spokenly.app/blog/handy-review.
- Vibe (thewh1teagle, Israeli): Windows installer vibe_3.0.5_x64-setup.exe ~24 MB from GitHub releases; in winget (Thewh1teagle.vibe); MIT; free, no registration; Hebrew via ivrit-ai ggml model (discussion #27). Site thewh1teagle.github.io/vibe.
- Win+H Hebrew: NOT supported. Microsoft Q&A "When will windows have dictation for the Hebrew language" (learn.microsoft.com/en-us/answers/questions/3894380); voice typing says "Voice typing isn't available in the current language". Cloud mode ~46 locales; offline packs only en/fr/de/es/zh/ja etc. => a real gap DeskIT fills.
- ivrit.ai: non-profit, datasets + models (whisper-large-v3-turbo Hebrew fine-tune), a "Hebrew Transcription Leaderboard" HF space; no consumer Windows app found in search. Dicta AI "Voice to Text" is a Google Play app (Android), not a Windows product.
- Buzz (chidiwilliams): model-download failures are the dominant complaint: issues #1450 (fail to download model, whisper.cpp), #1615 (2026-09-11, managed network), #1444 (large-v3 download stuck, app stuck on startup after forced close), #1031 (HF models do not work). Docs FAQ at chidiwilliams.github.io/buzz/docs/faq.
- AV false positives elsewhere: UPX-compressed PE binaries trigger Defender ML "Trojan:Win32/Bearfoos.B!ml" (microsoft/apm #487, kunchenguid/no-mistakes #535).

### Primary: github.com/cjpais/handy (README, fetched 2026-09-16)
- Licence: "MIT License - see LICENSE file for details." but "the Handy name, logo, icon, and brand assets are not open-source."
- Install: GitHub releases / handy.computer; "Also available via winget: winget install cjpais.Handy" (third-party maintained); Homebrew cask, .deb.
- Signing: "Handy release artifacts are signed with Tauri's updater signature format. The public key is stored in src-tauri/tauri.conf.json." (minisign; not Authenticode). Auto-update = Tauri updater with signature check.
- Models: none bundled; first run picks a model; Whisper Small/Medium/Turbo/Large + Parakeet V3; "file sizes ranging from 478 MB to 1.6 GB"; stored per user in `C:\Users\{username}\AppData\Roaming\com.pais.handy\models\`.
- GPU/CPU: Whisper "with GPU acceleration when available" (Vulkan); "Parakeet V3 - CPU-optimized model". Windows: "asks the Vulkan loader to skip implicit layers to avoid crashes caused by overlay and capture hooks" (overlay/capture hooks = a real Windows-only crash source).
- Bugs: GitHub issues + contact@handy.computer. No API keys ("Your voice stays on your computer"). Free, sponsors only.
- Known issue: #99 "Handy Crash on Windows 10 (Vulkan.dll)" - user had to fetch vulkan-1.dll manually.

### Primary: github.com/thewh1teagle/vibe (README)
- MIT. "Ultimate privacy: fully offline transcription, no data ever leaves your device". "Automatic updates" (Tauri). "Optimized for Nvidia / AMD / Intel GPUs! (Vulkan/CoreML)". Models: Whisper, Nemotron 3.5, Parakeet TDT v3.
- Bug reporting: "You can open new issue and it's recommend to check DEBUG.md first" + bug report template. Donation link "Support the project".
- Hebrew: discussion #27 "[Hebrew] Transcribe using Ivrit.ai model!" - ivrit-ai ggml model loads as a custom model (Vibe author is Israeli). Installer ~24 MB (vibe_3.0.5_x64-setup.exe), also winget Thewh1teagle.vibe.

### Primary: Microsoft Q&A 3894380 (answer 2025-02-09)
- "As of the time being, Windows 11 does not support Hebrew with regards to the built in voice typing or dictation feature." Suggested alternatives: Dictanote browser extension; Feedback Hub. (Still unsupported per 2026 third-party lists.)

### Primary: chidiwilliams.github.io/buzz/docs/faq
- Models in `%USERPROFILE%\AppData\Local\Buzz\Buzz\Cache`. "On Windows GPU support is included in the installation .exe. CUDA 12 required, computers with older CUDA versions will use CPU."
- "If a model download was incomplete or corrupted, Buzz may crash. Try to delete the downloaded model files in Help -> Preferences -> Models and re-download them."
- Logs: "Help -> About Buzz ... Show logs". Antivirus mentioned only as a mic-access blocker.

### Search snippets (pricing, to verify): Wispr Flow free = 2,000 words/week on Mac+Windows, Pro $15/mo or $12/mo annual, 14-day trial. Superwhisper free tier + Pro $8.49/mo / $84.99/yr / $249.99 lifetime; Windows app "relies more on cloud processing". Speech Note: MPL-2.0, Flathub, Linux only, models downloaded in-app. WhisperWriter (savbell): git clone + venv on Python 3.11, faster-whisper local or OpenAI API; no installer -> developer audience only. Talon: unverified.
- AV false positives: common pattern for unsigned/packed binaries (Bearfoos ML heuristics); hankhank10/false-positive-malware-reporting collects whitelist links; Authenticode signing + VirusTotal submission reduce it.

### Primary: wisprflow.ai/pricing (fetched 2026-09-16)
- Free: "2,000/week on desktop" words, "1,000/week on iPhone"; Pro "$15/user/mo" monthly, "$12/user/mo" annual; "You never need a credit card to start"; dictation on "Mac, Windows, iOS, and Android". Cloud-based (audio leaves the machine) - opposite of DeskIT's promise.
- superwhisper.com/pricing returned 404; snippet pricing (free tier, $8.49/mo, $249.99 lifetime) UNVERIFIED.

### Primary: talonvoice.com
- Free (beta) + optional Patreon ("early feature access", "high priority support"); Windows .exe and portable .zip; no Hebrew mention; changelog-driven updates. Audience = hands-free coding/accessibility, not Hebrew typing.

### Primary: Vibe discussion #27 (Hebrew, Mar-Nov 2024, 8 participants)
- Hebrew users load ivrit-ai ggml model via a link inside the app ("ivrit-ai/whisper-v2-d3-e3", file ivrit-ai-whisper-13-v2-e3.bin). Complaints: accuracy ("errors every 3-4 words" on the older model), Windows install failures (Win7 users), no translation. Shows an existing, small Hebrew audience that already tried a whisper GUI and asked in English/Hebrew on GitHub.

### Primary: Handy issues (search page, fetched 2026-09-16)
- #13 "SmartScreen on Windows thinks Handy may be untrustworthy" (closed Jun 26 2025, opened by the author himself); #1399 "Security Alert by virustotal.com" (May 2026); #1891 "Windows Defender detected Trojan in installer of 0.9.5" (Aug 30 2026). => AV/SmartScreen flags recur with EVERY new unsigned release, even for a popular MIT app.

### Primary: Vibe issues (search page)
- #1552 (Sep 6 2026, open) "All model downloads failed. Last error: Error while writing to file C:\Users\...\AppDa..."; #1479 (Sep 1 2026, open) "All model downloads failed..."; #1485 "sona process died during model loading (exited with code -1066598274)" (GPU/driver crash); #1489 load_model failed. => model download to AppData and GPU-driver crashes are the top two support burdens.

### Code signing reality (search snippets + Tauri docs links)
- Unsigned exe => "Windows protected your PC" SmartScreen block; signing only the installer leaves the inner binary unsigned (murmure #428, blocked by Smart App Control). Since 2024 EV certs get no instant SmartScreen reputation; reputation accrues per binary.
- Azure Trusted Signing (now "Artifact Signing") for individuals: from $9.99/month AND "Individual developers must be located in the United States or Canada for public trust certificates" => NOT available to a solo Israeli dev; and not zero-cost anyway. Alternatives: SignPath.io free OSS signing (unverified), or ship unsigned + document the SmartScreen "More info -> Run anyway" step (what Handy/Vibe effectively do).
- ivrit.ai: no consumer Windows dictation app found; offers models (whisper-large-v3-ct2, whisper-large-v3-turbo-ct2), a leaderboard HF space, "a free transcription tool" (web); 22,000 h dataset (Jul 2025). ShmuelRonen/hebrew_whisper = a Gradio file-transcription tool, not push-to-talk.

### Round 3 primary/secondary
- signpath.org: "Free Code Signing for Open Source software"; "For OSS projects, our services are free of charge"; no personal ID needed, HSM-held key, ties binary to the public repo. (Eligibility details not on the landing page - uncertainty; SignPath Foundation is known to require an OSI licence and a public repo with a CI build.)
- Handy #13: author wrote "I need to do trusted identity validation through Microsoft Azure. This is currently in progress, so eventually, handy will be signed." Yet Defender/VirusTotal flags reappeared in May and Aug 2026 (#1399, #1891) => even a signed Tauri app keeps getting ML false positives on new releases; a FAQ entry is mandatory.
- Microsoft Trusted Signing blog page body not retrievable; the US/Canada individual restriction + $9.99/mo rests on search snippets (learn.microsoft.com Q&A 2113965, 5595324) - treat as likely but unverified.
- ivrit.ai site: "Need to transcribe? Link to the free transcription tool from ivrit.ai" (transcribe.ivrit.ai, web upload). No Windows dictation app. Models: ivrit-ai/whisper-large-v3-turbo-ct2 is Apache 2.0, "fine-tuned on 295 hours of volunteer transcriptions and 93 hours of professionally transcribed Hebrew speech", ~7.7k downloads/month, documented for faster-whisper. => ivrit.ai is the natural distribution partner, not a competitor.
- Superwhisper: official pricing page 404 for us; third-party pages (spokenly, usevoicy, voibe, Jun 2026) agree on free tier + Pro $8.49/mo, $84.99/yr; lifetime either $249.99 or ~$849 (conflict) => unverified. Windows 10/11 app exists as of mid-2026.
- Handy review (spokenly, 2026): rough edges include "Whisper models crash on certain Windows and Linux configurations", "text appears 2 to 5 seconds after you stop speaking", "First words of a transcription occasionally get clipped", "History and LLM post-processing live behind a debug shortcut rather than in settings".
- CPU reality (snailtext/spokenly 2026 guides): CPU inference "stays usable up to small and gets slow beyond it"; Parakeet V3 is the CPU default in Handy (needs Skylake+). No Hebrew Parakeet exists => DeskIT's CPU story must be a smaller Hebrew whisper (turbo-ct2 int8) or opt-in cloud.
- Audience channels: no Reddit/Facebook thread found by search; Hebrew demand shows up as Adobe Premiere feature requests (2023-2026), Microsoft Q&A, Vibe discussion #27. Israeli communities exist off-search (Facebook groups, Telegram, Tapuz, Geektime) - not verified here.

## Options compared

| App | Stack / install | Price | Model at first run | GPU / CPU | Keys | Updates | Bugs | Hebrew |
|---|---|---|---|---|---|---|---|---|
| Handy (cjpais) | Tauri; NSIS exe, winget, ARM build | Free, MIT, sponsors | Picker on first run; 478 MB-1.6 GB; AppData\Roaming\com.pais.handy\models | Vulkan for Whisper; Parakeet V3 = CPU default; Vulkan crashes on overlays | none (offline) | Tauri updater, minisign-signed | GitHub issues + email | Whisper multilingual only, no fine-tune |
| Vibe (thewh1teagle, IL) | Tauri; ~24 MB setup.exe, winget | Free, MIT, donations | Downloaded in-app to AppData\Local; custom ggml link | Vulkan (NV/AMD/Intel) | none | Tauri auto-update | Issue template + DEBUG.md | Yes via ivrit-ai ggml (discussion #27); file transcription, not push-to-talk |
| Buzz | PyQt/PyInstaller exe, MS Store | Free (Store paid tier unverified) | Downloaded in-app, AppData\Local\Buzz cache | CUDA 12 in exe, else CPU | OpenAI key optional (in prefs) | Manual/Store | Help > Show logs | Whisper multilingual, file-based |
| WhisperWriter | git clone + Python 3.11 venv | Free | faster-whisper download | CUDA if torch finds it | OpenAI key in config | git pull | GitHub | multilingual, devs only |
| Speech Note | Flatpak (Linux only) | Free, MPL-2.0 | In-app model list | CPU/GPU options | none | Flathub | GitHub | Whisper Hebrew via model list |
| Superwhisper | Native Win app (mid-2026) | Free tier; Pro $8.49/mo (unverified) | Local small models free; cloud for quality on Windows | Apple-optimised; Windows leans cloud | BYO key possible (unverified) | in-app | email | multilingual cloud |
| Wispr Flow | Native Win app, account required | Free 2,000 words/week; Pro $15/mo ($12 annual) | Cloud only | n/a | n/a | in-app | support | cloud multilingual |
| Talon | exe / portable zip | Free beta + Patreon | bundled | CPU | none | manual | Slack/changelog | not Hebrew |
| Win+H | built in | free | n/a | cloud | n/a | Windows | Feedback Hub | NOT supported ("isn't available in the current language") |
| ivrit.ai | web tool transcribe.ivrit.ai + HF models | free, Apache 2.0 | n/a | n/a | n/a | n/a | n/a | the reference Hebrew models; no dictation app |

Shared patterns: (1) no model in the installer, first-run picker with sizes + a per-user AppData folder; (2) auto-update via a signed feed (Tauri updater); (3) free-tier-plus-Pro for cloud apps, pure-free for local OSS; (4) GitHub Issues + a template that asks for the log file; (5) Windows-specific pain: SmartScreen/Defender flags on every unsigned release, half-written model downloads that then crash the app on startup, GPU driver/overlay crashes, CPU too slow above "small".

## Recommendation for DeskIT
1. Ship as a per-user, no-admin Windows installer (Inno Setup or NSIS, PyInstaller/embedded-Python payload) that installs NO model. First run = Hebrew confirmation, a model picker with sizes and a plain speed estimate for the detected hardware (CUDA GPU found / CPU only), and a resumable download to %LOCALAPPDATA%\DeskIT\models with checksum + "delete and re-download" button. Reason: every competitor's top issue class is model downloads and post-download crashes (Buzz #1444/#1450/#1615, Vibe #1479/#1552).
2. CPU-only default = ivrit-ai whisper-large-v3-turbo-ct2 int8 (Apache 2.0, built for faster-whisper); offer the full large-v3-ct2 only when CUDA is detected. Offer an opt-in cloud path (Groq whisper on the user's own key) as the "no GPU, I accept audio leaving the machine" tier. Reason: no Hebrew Parakeet exists, and Handy's CPU story only works because Parakeet does.
3. Position DeskIT as "the Win+H that Hebrew never got": Microsoft explicitly does not support Hebrew voice typing (Q&A 3894380), Vibe is file-transcription, Wispr/Superwhisper are cloud and paid. Real and unfilled niche; Vibe #27 shows Hebrew users already hunt for whisper GUIs.
4. Signing: apply to SignPath Foundation (free for OSS; needs a public repo + CI build) rather than Azure Trusted Signing (paid, individuals US/CA only per snippets). Until signed, document the SmartScreen "More info > Run anyway" step with a screenshot and publish VirusTotal links per release, as Handy does after #13/#1399/#1891. Expect Defender ML flags anyway; add a FAQ entry and a "report false positive" link.
5. Updates: GitHub Releases as the feed, a tiny version-check on start (JSON in the repo), manual download-and-run; skip self-patching in v1 to stay off AV heuristics. Submit a winget manifest (free, gives winget install and a trust signal; Handy and Vibe are both there).
6. Bug reports: keep the bug-report key but route to Supabase with an explicit preview of what is sent (log tail, config without secrets, hardware) and a checkbox "include last 10 s of audio" default OFF. Mirror a public issue template on GitHub for power users.
7. Keys: store user keys with Windows DPAPI (CryptProtectData) in %LOCALAPPDATA%\DeskIT, never in the config file that gets attached to reports; the proof = a documented redaction list, one readable function that builds the report payload, and a Supabase schema with no key column. No competitor publishes such a proof, so it is a differentiator.
8. Channels (all free): ivrit.ai community (ask to be listed as a tool using their models), Vibe discussion #27, Israeli dev Telegram/Facebook groups, Hebrew tech press (Geektime), r/Israel and r/hebrew, the Adobe/Microsoft threads where Hebrew users asked, winget + AlternativeTo + SourceForge mirrors (Handy/Vibe get auto-mirrored). Audience: Israeli office workers, students, lawyers/doctors writing Hebrew notes, accessibility/RSI users, Hebrew-speaking devs; most on laptops without a discrete GPU.

## What the owner must do by hand
- Create a public GitHub repo with an OSI licence (MIT like Handy/Vibe; Handy reserves name/logo) - prerequisite for SignPath and winget.
- Apply to SignPath Foundation (form on signpath.org) and set up the CI build they sign; or accept unsigned releases for v1.
- Submit the winget manifest PR (microsoft/winget-pkgs) after the first release; needs a stable download URL and version scheme.
- Create the Supabase project (free tier) and a Hugging Face account (free) if a model mirror is needed.
- Decide the name/trademark posture and write the Hebrew + English user guide and the SmartScreen/Defender FAQ with screenshots.
- Optional: GitHub Pages landing page (Vibe uses thewh1teagle.github.io/vibe).

## Sources
- https://github.com/cjpais/handy (README: licence, signing, model paths, Vulkan note)
- https://github.com/cjpais/Handy/issues/13 , #1399, #1891 (SmartScreen/Defender/VirusTotal)
- https://spokenly.app/blog/handy-review (rough edges, 2026)
- https://github.com/thewh1teagle/vibe (README) and https://github.com/thewh1teagle/vibe/discussions/27 (Hebrew, ivrit-ai model)
- Vibe issues #1479, #1552, #1485, #1489 (model download / load failures, Sep 2026)
- https://chidiwilliams.github.io/buzz/docs/faq ; Buzz issues #1444, #1450, #1615, #1031
- https://learn.microsoft.com/en-us/answers/questions/3894380/when-will-windows-have-dictation-for-the-hebrew-la (2025-02-09)
- https://wisprflow.ai/pricing (free 2,000 words/week; Pro $15 / $12)
- https://talonvoice.com/ (free beta + Patreon; Windows exe/zip)
- https://signpath.org/ (free OSS code signing)
- https://www.ivrit.ai/en/ivrit-ai-2/ ; https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2 (Apache 2.0)
- https://github.com/savbell/whisper-writer ; https://github.com/mkiol/dsnote
- Snippets only: superwhisper pricing (spokenly/usevoicy/voibe), Azure Trusted Signing individual terms (learn.microsoft.com Q&A 2113965, 5595324), CPU-speed guides (snailtext, spokenly).

## Uncertainties
- Superwhisper prices and BYO-key support: official pricing page 404; lifetime price conflicts ($249.99 vs ~$849).
- Azure Trusted Signing "$9.99/month" and "individuals must be in US or Canada" not read on a Microsoft page.
- SignPath Foundation eligibility rules (licence, project age, reproducible CI) not on the landing page.
- Buzz Microsoft Store paid tier and Speech Note Hebrew quality not verified.
- Size of ivrit-ai turbo-ct2 files and its int8 CPU speed on a typical laptop not measured; the owner's "~40x slower on CPU" is for the large model.
- Hebrew user communities (Facebook/Telegram) not surfaced by US-only web search; channel list is inferred.
- Whether Handy completed Azure signing after #13 (flags recurred in 2026).
