# DeskIT — Config, storage layout, dependencies and packaging surface

Subsystem map for the distribution plan. Read-only survey of
`C:\Users\shimr\Desktop\Organized\Projects\DeskIT` on 2026-09-15 (repo at
commit `1159b16`, branch `main`, remote `https://github.com/DeskIT-app/DeskIT.git`,
132 tracked files). Every claim cites `file:line`. Nothing was run, modified
or created inside the repo; machine-side facts (shortcuts, scheduled tasks,
caches, PATH) were read with query-only commands.

---

## Purpose

This subsystem is everything that decides *where the app lives and what it
touches*: how it is started, which file is its configuration and how that
file is written, every file and folder it reads or writes at runtime, every
pip wheel and external binary it needs, the kernel-object and port names it
claims, and the machine-side hooks (Startup shortcut, scheduled tasks, the
Claude Code hook) that make it work for one owner on one PC. A distribution
plan has to replace all of it with an installer, a per-user data layout and
a real settings store, so the inventory below is deliberately exhaustive.

The headline finding: **the code folder is simultaneously the install
directory, the user's data directory, the log directory, the secrets store,
the model-cache trigger, the git working tree the owner pushes from, and the
scheduled-task working directory.** `config.toml` alone mixes shipped
defaults, documentation, the user's preferences, this machine's device name
and monitor coordinates, and owner-only project names — and it is *tracked in
git*, so a fresh clone boots with the owner's state.

---

## Files and what each does

### Launchers and process plumbing

| File | Role | Evidence |
|---|---|---|
| `DeskIT.vbs` | The launcher. `wscript` runs `<folder>\.venv\Scripts\pythonw.exe <folder>\main.py` hidden (window style 0), cwd = the folder. | `DeskIT.vbs:5-8` |
| `Dashboard.vbs` | Same shape, runs `dashboard.py`. | `Dashboard.vbs:3-7` |
| `Stop DeskIT.vbs` | Same shape, runs `main.py --stop`. | `Stop DeskIT.vbs` |
| `launch.py` | Cross-launch helper: picks `.venv\Scripts\pythonw.exe` first, then `pythonw.exe` beside `sys.executable`, then `sys.executable` (`launch.py:39-47`); spawns detached with `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP` (`launch.py:28-31,51-60`); `open_path` = `os.startfile` (`launch.py:78`). |
| `singleton.py` | Named mutex `Local\DeskIT.instance`, quit event `Local\DeskIT.quit`, dashboard mutex `Local\DeskIT.dashboard`, show event `Local\DeskIT.dashboard.show` (`singleton.py:25-31`). `Local\` = per logon session, on purpose (`singleton.py:24`). |
| `control.py` | Request/response named pipe `\\.\pipe\DeskIT.control` between dashboard and app (`control.py:43`); chosen over a TCP port to avoid port collisions (`control.py:20-23`); default pipe DACL gives Everyone read-only (`control.py:25-28`). Needs pywin32 `win32pipe`/`win32file` (`control.py:56-62`). |
| `versions.py` | Only reports the git branch via `git rev-parse --abbrev-ref HEAD` (`versions.py:57-61`), cached, `"(unknown)"` without git (`versions.py:62-65`). The branch switcher was removed 2026-09-08 (`versions.py:1-33`). |
| `main.py` | App entry. `APP_DIR = Path(__file__).resolve().parent` (`main.py:34`); config path default `APP_DIR/config.toml` (`main.py:324,5859`); CLI flags `--config --fake --check --list-devices --stop --test-sound --translate --punctuate --lookup --setup --benchmark --study --review --vocab --drain --dashboard` (`main.py:5859-5913`); first-run wizard when `firstrun.needed(cfg)` (`main.py:5966-5967`); logging to `app.log` (500 KB × 2 backups) and `transcripts.log` (1 MB × 3 backups) (`main.py:5652-5665`). |
| `firstrun.py` | Wizard; marker `.setup-done` (`firstrun.py:65`); `needed()` = not `[setup] done` and no marker (`firstrun.py:676-677`); writes `audio.device` through `config.set_values` (`firstrun.py:639`); opens `ms-settings:privacy-microphone` (`firstrun.py:197`). |

### Configuration

| File | Role | Evidence |
|---|---|---|
| `config.toml` | 1794 lines, 120 KB, ~185 assignments, 23 sections; "two thirds comments" (`config.py:4`). Tracked in git (`git ls-files`), currently *modified* (uncommitted: `punctuate_hotkey` and two card positions). |
| `config.py` | 2433 lines. Frozen dataclasses with defaults; `load()` reads with stdlib `tomllib` (`config.py:1482-1487`) and validates ~100 rules (`config.py:1932-2280`). `set_values()` is a regex **line editor** (`config.py:2285,2340-2432`) — see "set_values and why a TOML round-trip is forbidden" below. |
| `settings.py` | Generates the dashboard's Settings page from `config.toml` itself: every assignment becomes a row, the surrounding comments become help text, an `a \| b \| c` at the front of the comment becomes a menu (`settings.py:1-19`). Two parsers on purpose — tomllib for values, a line scan for comments (`settings.py:21-28`). Writing goes through `config.set_values` (`settings.py:53-56`). |
| `.env` | Secrets: `GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `GROQ_API_KEY` (key names read from the file; values redacted). Read by `apikey.py` (`apikey.py:18-19,25-27,38-52`), environment variable first (`apikey.py:30-35`). Gitignored (`.gitignore:1`). |
| `server_token.txt` | Phone/notify bearer token, generated `secrets.token_urlsafe(24)` on first server start (`server.py:97-113`); read by `notify_hook.py` (`notify_hook.py:54`). Gitignored (`.gitignore:41`). |
| `.setup-done` | Per-installation marker (`firstrun.py:65,683-688`); gitignored (`.gitignore:50`). `[setup] done` in config.toml is only a hand override, and its docstring explains why the marker cannot live in the tracked file (`config.py:242-256`). |

### Machine-side installers (owner runs by hand)

| File | Role | Evidence |
|---|---|---|
| `install_fonts.py` | Copies `fonts\*.ttf` to `%LOCALAPPDATA%\Microsoft\Windows\Fonts`, registers them under `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts`, `AddFontResourceW` + `WM_FONTCHANGE` broadcast (`install_fonts.py:31-33,51-54,73-82`). **No longer required**: `fonts.py` loads `fonts\` per-process with `AddFontResourceExW(FR_PRIVATE)` (`fonts.py:56-57,103-126`; README:118-131). |
| `install_nightly_task.ps1` | Registers scheduled task "DeskIT Nightly Tests", daily 02:55, `powershell.exe … -File <repo>\nightly_tests.ps1`, working dir = repo, as the current user, Interactive logon, WakeToRun on (`install_nightly_task.ps1:60-66,88-118`). Verified present on this machine. |
| `weekly_review.ps1` | The Saturday 08:00 task body: finds the newest `claude.exe` inside the Claude desktop app's package or `C:\Users\shimr\.local\bin\claude.exe` (`weekly_review.ps1:46-103`), runs `/weekly-reports` headless with `--model claude-opus-5` (`weekly_review.ps1:269-279`), logs to `problems\weekly\run.log` (`weekly_review.ps1:43-45`). Task "DeskIT Weekly Report Review" verified present. |
| `nightly_tests.ps1` | Runs `.venv\Scripts\python.exe nightly.py` (`nightly_tests.ps1:43,145`). |
| `notify_hook.py --install-hook` | Writes `Stop` and `Notification` hook entries into `~/.claude/settings.json` with the absolute path of this repo's `pythonw.exe` and `notify_hook.py` (`notify_hook.py:53,395-452`). Verified installed: `~/.claude/settings.json` lines 12 and 24 carry the absolute repo path. |

### How the app is started today (verified on the machine)

1. **Autostart**: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DeskIT.lnk` → `C:\WINDOWS\system32\wscript.exe "…\DeskIT\DeskIT.vbs"`, working dir = repo, icon = `icon.ico` (read via WScript.Shell; README:150-153 documents it). `Ollama.lnk` sits in the same Startup folder — Ollama is assumed running.
2. **Desktop**: `DeskIT.lnk` → `wscript.exe "…\Dashboard.vbs"`.
3. `DeskIT.vbs` → hidden `.venv\Scripts\pythonw.exe main.py`. `main.py` takes the mutex; a second launch opens the dashboard instead (README:105-108; `singleton.py`).
4. The dashboard's Start button uses `launch.start_app` (`launch.py:63-67`); its own taskbar relaunch command is set to `wscript.exe Dashboard.vbs` via `SHGetPropertyStoreForWindow` (`dashboard.py:596-613`).
5. Stop: `Stop DeskIT.vbs` → `main.py --stop` → sets `Local\DeskIT.quit` (`singleton.py:161-170`).
6. Interpreter: `.venv/pyvenv.cfg` pins `home = C:\Users\shimr\AppData\Local\Programs\Python\Python311`, version 3.11.9 — absolute paths, so the venv is not relocatable.

A real installer has to replace: the venv + python.org Python, the `.vbs` launchers, the Startup `.lnk`, the first-run 3 GB model download, the optional Ollama, the optional Claude hook, the two scheduled tasks (drop), `config.toml` seeding, the data/secret/log locations, and add an uninstaller.

---

## Personal data stores

Everything below is written relative to `APP_DIR` unless stated. "Per-user?" = must be separated per Windows user / per installation in a distributed build.

| What | Where | Format | Sensitivity | Per-user? |
|---|---|---|---|---|
| Every dictation, translation in/out, punctuation, lookup, correction, error | `transcripts.log`, `.1`–`.3` (`main.py:5661-5665`; reader `history.py:32-33`) | pipe-delimited text, 1 MB × 4 | **High** — verbatim speech, including everything said to Claude Code (`.gitignore:5-11`) | yes |
| Status log, includes pasted text | `app.log`, `.1`, `.2` (`main.py:5654-5657`) | text, 500 KB × 3 | High (`.gitignore:6`) | yes |
| Raw recordings ring (last `[vocab] keep_audio` = 50) | `recent\*.wav` + `.json` sidecar with transcript/corrected text (`main.py:356`, `spool.py:77-95`) | WAV + JSON, ~32 MB now | **High** — the user's voice | yes |
| Recordings that failed to transcribe (kept up to 100) | `pending\` (`main.py:351`, `spool.py:66`) | WAV + JSON | High | yes |
| Verified (audio, text) pairs for fine-tuning, up to `[study] corpus_keep` = 400 | `corpus\` (`study.py:556,494-514`) ~199 MB now; read-aloud clips in `corpus\read\` + `texts\` + `skipped.json` (`reading.py:86-90`, `dashboard.py:213`) | WAV + JSON | **High** — voice | yes (and opt-in) |
| Learned vocabulary (heard → meant) | `vocab.json` (`main.py:338`, `vocab.py:293-299`); `vocab.json.bak-*` are hand-made copies (no code writes `.bak`) | JSON | Medium-high | yes |
| Lookup answers keyed by the literal selected text | `lookup_cache.json` (`lookup.py:628-629`) | JSON, ≤500 entries | Medium — a record of what the user *read* (`.gitignore:8-9`) | yes |
| Second-reading proposals (dictated sentences + proposed fixes) | `review.json` + `review.lock` (`review.py:78,664,693`) | JSON, 215 KB now | High | yes |
| Notifications from other programs (titles + bodies, Claude summaries with project paths) | `notify.json`, `notify.log` (`notify.py:103-104`) | JSON/text | High | yes |
| Bug reports: typed line, raw and final dictation text, pinned WAV, **screenshot**, env stamp | `problems.json`, `problems.md`, `problems.lock`, `problems\<id>.wav/.jpg` (`problems.py:97-99,379,409,575`) | JSON/MD/WAV/JPG | **Very high** (`.gitignore:66-81`) | yes |
| Screenshots and screen recordings | `[capture] folder` / `clip_folder` — relative → beside the app (`capture.py:1678-1686`); on this machine absolute `…\Photos\Screenshots\DeskIT capture` and `…\Videos\DeskIT` (`config.toml:788,796`); camera photos same folder (`config.toml:999`) | PNG/MP4/JPG | **Very high** (`.gitignore:30-35`) | yes |
| Saturday-routine questions and the owner's answers | `questions.json`, `questions.lock` (`questions.py:76`) — **untracked and NOT gitignored** (`git status`) | JSON | Medium (Hebrew Q&A about his code) | owner-only |
| Weekly review outputs, push log | `problems\weekly\*.md`, `run.log`, `push.log` (`dashboard.py:887`, `weekly_review.ps1:43-45`) | MD/text | Medium | owner-only |
| Nightly test transcripts (14 kept), lock, marker, stop flag | `problems\nightly\` (`nightly.py:122-139,214`) | text/JSON | Low | owner-only |
| Awake hold marker and vitals log (RAM, commit, GPU, heaviest processes, claude.exe count) | `awake_state.json`, `awake.log` (`awake.py:116-117,841`); legacy `night_state.json`, `night.log` (`.gitignore:56-60`) | JSON/text, 660 KB now | Low-medium | per-machine |
| API keys | `.env` (`apikey.py:19`) | KEY=VALUE text | **Secret** | per-user |
| Phone/notify bearer token | `server_token.txt` (`server.py:69,110-111`) | 32-char text | **Secret** | per-install |
| Settings + card positions + device name + folders + seed terms | `config.toml` | TOML | Low-medium (reveals hardware, paths, projects) | per-user *and* per-machine layers |
| First-run marker | `.setup-done` (`firstrun.py:65`) | text | none | per-install |
| Generated audio cues | `cues\*.wav` (`cues.py:23,313`) | WAV | none | cache (shared OK) |
| Whisper models | `%USERPROFILE%\.cache\huggingface\hub\models--ivrit-ai--whisper-large-v3-turbo-ct2` (1547 MB) and `models--deepdml--faster-whisper-large-v3-turbo-ct2` (1547 MB) (`local_whisper.py:28-29`) | CT2 weights | none | shared cache OK |
| Ollama models | `%USERPROFILE%\.ollama\models` (83 GB on this machine, many models) | GGUF | none | Ollama's own |
| Copy of Windows' notification database (ALL apps' toasts) | `%TEMP%\hd-notify-watch.db` (+ `-wal`, `-shm`) copied from `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db` (`notify_watch.py:144-147,405-422`) | SQLite | High, transient | per-user temp |
| TTS script + spoken answer text/wav | `<tempdir>\speak.ps1`, wav/text files (`visual_qa.py:1165-1173`) | PS1/WAV/TXT | Medium, transient | per-user temp |
| Claude Code hook entries | `~/.claude/settings.json` (`notify_hook.py:53,430-452`) | JSON | Low | per-user, outside app |
| Reads (not writes): Claude Desktop session store | `%APPDATA%\Claude\claude-code-sessions`, `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code-sessions` (`notify.py:436,457-467`; `notify_hook.py:268`) | JSON | — | machine-specific |
| Reads: Windows Update active hours | `HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings` (`awake.py:390-395`) | registry | — | — |
| Parked test web pages | `ch.html`, `cp_play.html`, `pp.html`, `np_passport.html` (2.7 MB; `.gitignore:24-28`) | HTML | Medium (what the owner was reading) | owner-only |
| Dev artifacts | `.agents\` (untracked, not ignored), `android\local.properties` (`sdk.dir=C:/Users/shimr/dev-tools/android-sdk`), `android\app\build\…\app-debug.apk` served at `/app.apk` (`server.py:70-71,218`) | — | Low | owner-only |

Daily LLM quota counters for study/review are **in memory only** (`study.py:561,598-600`; `review.py:917,980-982`) — they reset on restart; nothing persists them.

---

## Machine-specific assumptions (with file:line)

**In the tracked config.toml (the shipped defaults ARE the owner's values):**
- `[audio] device = "Headset Microphone (Arctis 7 Chat), Windows WASAPI"` — `config.toml:293`. Recorder falls back to the default input with a warning when the name is absent (`recorder.py:109-127`).
- `[capture] folder` and `clip_folder` are absolute paths under `C:\Users\shimr\Desktop\Organized\…` — `config.toml:788,796`; `[camera] folder` the same — `config.toml:999`. `capture.py:1683-1685` does `mkdir(parents=True)`, so on another machine the app would *create* that foreign path.
- Dragged card positions for a 2560×1440 primary with a monitor at x = −1920: `[hint] x=-1895 y=823` (`config.toml:265-266`), `[notify] x=2188 y=1373` (`1168-1169`), `[problems] x=1066 y=511` (`1230,1238`), `[review] x=1238 y=795` (`1704-1705`). Positions are deliberately unvalidated (`config.py:879-881`), and the sentinel rationale cites "this machine" (`config.py:97-101`).
- `[visual_qa] voice = "Microsoft Asaf"` — he-IL WinRT voice, present only with the Hebrew language pack (`config.toml:659`; `visual_qa.py:55-56`).
- `[server] enabled = true` (`config.toml:1305`) although the code default is `false` (`config.py:1117`).
- `[vocab] terms` lists the owner's projects "HebrewDictation", "Massif", "TripSync", "Cowork" (`config.toml:1354-1364`).
- `[notify] watch = "cowork"` assumes the Claude desktop app's package identity `Claude_pzs8sxrjxfjjc!Claude` (`config.toml:1144`; `notify_watch.py:154`).
- `[tests]` section exists only for the owner's scheduled task (`config.toml:1755-1794`; `config.py:1128-1150`).
- Hotkey rationale comments enumerate the owner's apps and the NVIDIA overlay (`config.toml:5-63`).

**In code:**
- `\\.\pipe\DeskIT.control` is a machine-global pipe name (`control.py:43`); port `127.0.0.1:8756` fixed by default (`config.py:1125`, `server.py:638-640`, hard-coded again in `notify_hook.py:52` and in skin text `skin/preview.py:99`, `skin/record.py:47`).
- Ollama at `http://127.0.0.1:11434` (`config.py:326`), literal IP not `localhost` on purpose (`lookup.py:38`).
- CUDA DLLs found by scanning `site-packages/nvidia/*/bin` and prepending to `PATH` (`local_whisper.py:51-79`) — assumes a pip-venv layout.
- Tailscale exe looked up on PATH or in `C:\Program Files\Tailscale` (`server.py:116-123`); `tailscale serve --bg 8756` must have been run once (`server.py:656-658`).
- `weekly_review.ps1:43` and `nightly_tests.ps1:41` fall back to the typed path `C:\Users\shimr\Desktop\Organized\Projects\DeskIT`; `weekly_review.ps1:103` types `C:\Users\shimr\.local\bin\claude.exe`.
- `~/.claude/settings.json` hook lines 12 and 24 embed the repo's absolute `pythonw.exe` and script path.
- Startup `.lnk`, Desktop `.lnk`, both scheduled tasks embed the repo path (verified).
- `awake.py` shells out to `powercfg` (`awake.py:283-286`), `powershell` (`338-341`), `tasklist` for `claude.exe` (`421-427`), `nvidia-smi` (`645-648`); reads `HKLM\…\WindowsUpdate\UX\Settings` (`390-395`).
- `keyboard.py` draws a 104-key ANSI board "because that is what is on his desk" (`keyboard.py:10-11`).
- `.venv/pyvenv.cfg` absolute Python home; `DeskIT.vbs:8` assumes `.venv\Scripts\pythonw.exe` beside the script.
- Fonts: per-user font folder probed at `%LOCALAPPDATA%\Microsoft\Windows\Fonts` (`fonts.py:69-72`).
- Windows 11 specifics: the toast DB path and app-package naming (`notify_watch.py:18-24`), Windows Terminal window class notes (`server.py:47-52`), UIPI limits for elevated windows (README:4146-4150).

**Documentation drift** (three sources disagree on key defaults): README config reference says `translate_hotkey=ctrl+f9`, `punctuate=f2`, `lookup=f8`, `correct=ctrl+f8` (README:4267-4274); `config.py` defaults are `""`, `""`, `f6`, `f8` (`config.py:1185,1190,1201,1206`); the live `config.toml` has `f8`, `ctrl+f2`, `ctrl+f8`, `ctrl+f9` (`config.toml:106,126,147,167`). README Setup says put the device *index* in `[audio] device` (README:79-89) while the file and `recorder.py:112-115` say name-only.

---

## External services and what leaves the machine

| Service | Endpoint / SDK | What is sent | Key | Optional? |
|---|---|---|---|---|
| Google Gemini | `google-genai` SDK `generate_content` (`transcribers/gemini.py:16,107`) | **Audio** (WAV bytes, `transcribers/gemini.py:103`) when `backend = "gemini"`; transcript **text** for translate/punctuate/lookup fallbacks; **screenshot** for ask-the-screen only if `[visual_qa] allow_screenshot_upload = true` (`config.py:463-480`). README warns free-tier inputs may be used for training (README:66-74). 20 req/day/model (README:4165-4172). | `GEMINI_API_KEY` / `GOOGLE_API_KEY` in `.env` or env (`apikey.py:25`) | yes — default backend is `local` (`config.toml:196`) |
| Groq | `https://api.groq.com/openai/v1` over urllib (`translate.py:367,472`) | Transcript **text** for the repair pass (`[polish]`), punctuation, study/review adjudication (`llm_per_day`), and vision for ask-the-screen only behind the upload gate. Privacy paragraph: `translate.py:401-407`. | `GROQ_API_KEY` (`apikey.py:27`) | yes — skipped without a key (`config.py:963-966`) |
| Cerebras | `https://api.cerebras.ai/v1` (`translate.py:366`) | Same as Groq; free tier gone, "kept so quota may return" (`translate.py:392-398`) | `CEREBRAS_API_KEY` | yes (dead provider) |
| Ollama | `http://127.0.0.1:11434` (`config.py:326`; `lookup.py:703,746`) | Text and screenshots, **local only** | none | yes, but most local-LLM features need it (`gemma3:12b`, `llama3.1:8b`) |
| Hugging Face Hub | via `faster_whisper`/`huggingface_hub` (`local_whisper.py:28-29,243-244`) | Nothing personal; downloads ~1.5 GB × 2 on first use | none | required for local backend |
| Tailscale | `tailscale.exe status/serve` (`server.py:116-160`) | Nothing leaves; the **phone sends audio in** to `127.0.0.1:8756` fronted by `tailscale serve` with TLS (`server.py:11-21`) | Tailscale account | yes — `[server] enabled` |
| GitHub | `git fetch/push origin main`, `git reset --keep origin/main` (`dashboard.py:1031,1039,1104`; remote `DeskIT-app/DeskIT`) | The **code** (and any untracked-but-not-ignored file such as `questions.json` if ever added) | owner's git credentials | owner-only |
| Anthropic (Claude Code CLI) | `claude.exe … --model claude-opus-5` headless (`weekly_review.ps1:269-279`) | The contents of `problems.json` — the owner's dictated text, report lines, screenshot paths — plus the repo | owner's Claude subscription | owner-only |
| Windows | `ms-settings:privacy-microphone` (`firstrun.py:197`), `explorer /select` (`capture.py:1724`), WinRT `SpeechSynthesizer` via PowerShell (`visual_qa.py:1080,1172`) | local | — | — |

Design rules already in code worth keeping: audio never leaves except with `backend = "gemini"` (`translate.py:403-405`); screenshots are gated by a constructor-level kill switch (`config.py:463-480`); the phone server binds loopback only (`config.py:1118-1123`).

---

## Owner-only or developer-only features

- **Saturday weekly review**: `weekly_review.ps1`, `.claude/commands/weekly-reports.md` (99 KB), `questions.py`/`questions.json`, the dashboard's answer surface and its "wake the review" spawn (`dashboard.py:5161-5190`; `main.py:4181-4195`), scheduled task "DeskIT Weekly Report Review". Needs `claude.exe`, an Anthropic account, and a writable git checkout — it *writes code into the install folder*.
- **Nightly test run**: `nightly.py`, `nightly_tests.ps1`, `install_nightly_task.ps1`, `[tests]` section, the dashboard's "Stop tests" button, `problems\nightly\` (README:4458-4590).
- **Dashboard Push / Undo / "what is here and not on GitHub"**: `dashboard.py:869-871,986-1104,5197`, `problems\weekly\push.log`. Pure owner workflow.
- **Branch stamp**: `versions.py` (git).
- **Notify door and its two inputs**: `notify_hook.py` (Claude Code Stop hook), `notify_watch.py` (reads the Windows toast DB for the Claude desktop app), `notify.py`'s session-store scan (`notify.py:436-467`). Useful to other Claude Code users, but it depends on Claude Desktop/Claude Code being installed; must be an optional integration, off by default.
- **Phone endpoint's APK route** (`server.py:70-71,218`) and the whole `android\` tree, `android\tools\emu.py`, `fake_pc.py`, `android\local.properties` (SDK path).
- **Fine-tune data collection**: `corpus\` (`study.py:59`), "Read this to me" deck with `read_sentences`/`read_goal_hours` (`reading.py:3,60-64`; `config.py:1034-1042`).
- **Dev tools and docs**: `tests.py` (1.3 MB), `tests_quiet.py` (second desktop), `make_icon.py`, `audio_check.py`, `install_fonts.py`, `AGENTS.md` (81 KB Claude instructions), `PARALLEL_FEATURES_PLAN.md`, `VISUAL_QA_PLAN.md`, `SKIN.md`, `.claude/settings.local.json` (keys: `permissions` → `allow`), `.agents\`.
- **CLI flags** `--benchmark --study --review --vocab --drain --setup` (`main.py:5887-5913`).
- **Awake vitals** counting `claude.exe` processes and calling `nvidia-smi` (`awake.py:421-427,645-648,841`); `[awake] pin_timeouts` rewrites the machine's sleep timers with `powercfg` (`awake.py:283-286`; `config.py:727-732`).
- **Owner values in config**: `[vocab] terms`, the absolute capture folders, the device name, `[server] enabled = true`.

---

## What breaks on a fresh machine

1. **No `.venv`** → `DeskIT.vbs` points at a missing `pythonw.exe` (`DeskIT.vbs:8`); README's rebuild is `py -3.11 -m venv .venv` + `pip install -r requirements.txt` (README:48-50). **`requirements.txt` does not list `pillow`**, yet `ui.py`, `keyboard.py`, `answer_card.py`, `notify_card.py`, `problem_card.py`, `review_card.py`, `shelf_card.py`, `make_icon.py` import `PIL` (import grep) — I found no listed package that declares Pillow as a dependency, so a clean install from the file would fail at `import ui`. Verify with a fresh venv before trusting the list. `pywin32` is required by `control.py` and `injector.py`.
2. **No NVIDIA GPU** → CTranslate2 falls back to CPU, ~40× slower (`requirements.txt:10-12`: 8.2 s vs 0.20 s for a 3 s clip); both large-v3-turbo models still load (README:4239-4240 says ~3 GB VRAM on GPU). The `[polish] warm_up` of gemma3:12b (~5 GB VRAM, `config.py:1006`; README says `keep_alive` "pins 7.6 GB") is impossible on small cards.
3. **First run downloads ~3.1 GB** from Hugging Face with only the splash as feedback (`local_whisper.py:28-29`; measured cache 1547 MB × 2). Offline or proxied machines fail.
4. **No Ollama** → translate fallback, lookup (`prefer = "ollama"`), ask-the-screen (cloud unconstructable by default) and the local repair path all fail with "cannot reach Ollama" (`translate.py:355-358`); with no Groq key either, `[polish]` and `[punctuate]` have nothing to run on.
5. **No `.env`** → Gemini/Groq skipped (`config.py:963-966`); `--check` reports the missing key (`apikey.py:73-79`).
6. **Microphone name absent** → default input with a warning (`recorder.py:120-127`); the wizard runs (no `.setup-done`) and writes the chosen device (`firstrun.py:639`).
7. **Absolute capture folders** get *created* under `C:\Users\shimr\…` on the new machine (`capture.py:1683-1685`).
8. **Card positions** from the owner's multi-monitor desk put cards off-screen on a single monitor (`config.toml:265-266,1168-1169`; unvalidated by design `config.py:879-881`).
9. **"Microsoft Asaf"** voice absent → speech fails silently (`visual_qa.py:55-56`).
10. **No Tailscale** → server logs a warning and prints a loopback URL (`server.py:659-664`); with `[server] enabled = true` shipped, a socket still opens on 127.0.0.1:8756.
11. **No git** → `versions.py` returns "(unknown)" (`versions.py:62-65`); dashboard Push says "git is not on PATH" (`dashboard.py:939`).
12. **No Claude Desktop / Claude Code** → notify door stays idle; `notify_watch` finds no DB; `session_roots()` is empty. Harmless but confusing UI (Waiting pile, shelf rows).
13. **No scheduled tasks** → nothing nightly/weekly; `[tests]` and the "Stop tests" button are dead weight.
14. **Python other than 3.11** → `tomllib` needs ≥3.11; the installed `skia.cp311-win_amd64.pyd` and other wheels pin 3.11.
15. **Fonts** work without installation (`fonts.py:103-126`); **skin** falls back to Tk without skia (`skin/__init__.py:53-66`).
16. **A second Windows user on the same PC**: the mutex is `Local\` (fine), but `\\.\pipe\DeskIT.control` (`control.py:43`) and port 8756 are machine-global — the second instance's pipe creation or bind fails, and the dashboard of user B may talk to user A's app (pipe DACL is read-only to Everyone, so writes fail confusingly). Same for two installs (dev copy + installed copy) in one session, which the mutex refuses by design (`singleton.py:132-137`).
17. **Moving the folder** breaks the Startup `.lnk`, both scheduled tasks and the Claude hook, which all embed absolute paths (`weekly_review.ps1:36-42` records exactly such an incident).
18. **`[setup] done`, `server.enabled`, seed terms, positions, device** ship as the owner's values because `config.toml` is tracked (`config.py:247-251` admits this for `done` only).

---

## set_values and why a TOML round-trip is forbidden — and what that implies

`config.set_values(path, updates)` (`config.py:2340-2432`) is a comment-preserving **regex line editor**: it finds the one assignment line for a key (top-level block only, or inside the named `[section]` span — `config.py:2318-2337,2374-2377`), rewrites only the value while keeping indentation, the trailing `#` comment and its alignment (`config.py:2383-2394`), refuses to *add* a key inside a section ("the line editor only changes keys that are already there", `config.py:2397-2400`), appends a missing top-level key after the last top-level assignment (`config.py:2405-2410`), writes to a per-PID temp file, re-parses and fully validates it with `load()`, then `os.replace`s it into place (`config.py:2412-2432`). The docstring at `config.py:1-8` gives the reason: the file is two-thirds comments that record hours of measurements, and any TOML serializer would drop them all on the first hotkey change. `settings.py:1-19` makes those comments *the UI*: the generated Settings page reads help text and menus out of them.

Consequences for a distributable app:
- **One file carries four layers**: shipped defaults, documentation, the user's preferences, and per-machine UI state (positions, device). The dashboard, every draggable card (`config.py:91-95`), the wizard, the "don't show again" box (`config.toml:253-254`) and "Move the dot" (`config.py:137-145`) all write into the same tracked file — so an update that ships a new `config.toml` overwrites user choices, and a user's old file cannot receive a new key inside a section (`config.py:2397-2400`; `firstrun.py:61` notes the same limit). The `_section_span` scan is also fooled by a `[` at the start of a comment line inside a section (`config.py:2331-2335` checks `lstrip().startswith("[")` on raw lines, not on TOML-parsed headers) — a hazard only if help text ever starts a line with `[`.
- Therefore the plan needs a **separate user-settings store**: keep the shipped TOML as a read-only *defaults + help* document (so `settings.py` keeps working and the docs stay with the keys), and put user overrides in a small comment-free file written by a real serializer (only keys that differ from defaults, dotted `section.key = value`), plus a per-machine `state.json` for positions/device/marker. `config.load()` merges defaults ← user ← state; `set_values` becomes "write the override file", never the shipped one. Migration = diff the legacy `config.toml` against defaults once and import the differences.

---

## Settings classification (per config.toml key)

Legend: **user** = ordinary user changes it from Settings; **advanced** = tuning, hidden behind "more"; **dev/machine** = per-installation state, per-machine value, or owner/developer workflow — not a user setting at all.

| Section | user | advanced | developer-or-machine |
|---|---|---|---|
| top-level | `hotkey`, `auto_language`, `english_hotkey`, `latch_hotkey`, `translate_hotkey`, `punctuate_hotkey`, `correct_hotkey`, `lookup_hotkey`, `pause_hotkey`, `auto_pause_fullscreen`, `backend` (privacy), `fallback_to_local`, `splash`, `indicator` | `paste_chord`, `restore_delay_ms`, `min_seconds`, `max_seconds`, `latch_max_seconds` | — |
| `[dot]` | `corner` | — | `x`, `y` (written by the app; machine state) |
| `[hint]` | `enabled`, `corner` | `after_ms` | `x`, `y`, `scale` (written by the card) |
| `[setup]` | — | — | `done` (installation override; marker belongs in state) |
| `[audio]` | — | `sample_rate` | `device` (per-machine; set by wizard/Settings) |
| `[feedback]` | `enabled` | `placeholder`, `retry_seconds` | — |
| `[translate]` | `target` | `max_chars`, `ollama_model`, `timeout_s`, `ollama_timeout_s`, `settle_ms`, `copy_chord`, `select_all_chord` | `ollama_url` (machine) |
| `[punctuate]` | `auto`, `prefer` (privacy), `nikud` | `max_wait_s`, `max_chars`, `groq_model`, `ollama_model` | — |
| `[lookup]` | `both_ways`, `prefer` (privacy), `cold_to_gemini` (privacy), `strip_niqqud` | `hebrew_share`, `max_chars`, `model`, `keep_alive`, `max_width`, `max_height`, `cache_entries`, `skip_consoles` | `dwell_ms` (dead, `config.py:441-445`) |
| `[visual_qa]` | `enabled`, `visual_qa_hotkey`, `allow_screenshot_upload` (privacy), `prefer`, `speak`, `auto_send`, `echo_to_field` | `ollama_model`, `groq_model`, `gemini_fallback`, `max_side_px`, `num_predict`, `window_alpha`, `warmup`, `ollama_timeout_s`, `cloud_timeout_s` | `voice` (machine: installed TTS voices) |
| `[capture]` | `enabled`, `capture_hotkey`, `record_hotkey`, `folder`, `clip_folder`, `copy_to_clipboard`, `after_shot`, `toast_corner`, `always_save`, `cursor`, `audio` (privacy), `system_sound`, `timer_corner`, `announce` | `toast_seconds`, `toast_stack`, `toast_in_shots`, `copy_clip_path`, `fps`, `quality`, `max_minutes` | (current *values* of `folder`/`clip_folder` are machine paths) |
| `[camera]` | `enabled`, `camera_hotkey`, `mirror`, `timer`, `folder`, `copy_to_clipboard`, `edit_after_shot` | `size`, `fps` | `device` (machine) |
| `[awake]` | `hold`, `enabled`, `screens_hotkey` | `screens_off_again_s`, `keep_screens_off_s`, `pin_timeouts` (system-modifying; keep off) | `vitals_minutes` (owner diagnostics) |
| `[notify]` | `enabled`, `cue`, `interrupt`, `corner`, `anchor`, `dismiss_hotkey`, `remind_every_s`, `remind_times` | `card_seconds`, `stack_max`, `coalesce_s`, `quiet_s` | `watch` (Claude-Desktop-specific), `x`, `y`, `scale` (state) |
| `[problems]` | `enabled`, `report_hotkey`, `shot` (privacy), `keep_audio` (privacy) | `keep_resolved` | `x`, `y`, `card_x`, `card_y` (state) |
| `[shelf]` | `enabled`, `shelf_hotkey`, `rows`, `corner` | `hush_notifications` | `x`, `y`, `scale` (state) |
| `[server]` | `enabled` (opens a socket) | `port` | `host` (machine/network) |
| `[vocab]` | `enabled`, `keep_audio` (privacy), `terms` (personal — ship empty) | `max_terms`, `replace_after_hits`, `hebrew_after_hits` | — |
| `[study]` | `enabled`, `corpus_keep` (privacy/disk; ship 0 or opt-in) | `idle_minutes`, `max_clip_seconds`, `llm_per_day` | `read_sentences`, `read_goal_hours` (owner's fine-tune goal) |
| `[polish]` | `when`, `prefer` (privacy) | `min_chars`, `groq_model`, `groq_timeout_s`, `ollama_model`, `max_wait_s`, `warm_up` | `cerebras_model`, `cerebras_timeout_s` (dead provider) |
| `[gemini]` | — | `models`, `timeout_s` | — |
| `[local]` | `cleanup`, `extra_fillers`, `extra_boilerplate` | `model`, `device`, `initial_prompt`, `english_model`, `english_threshold`, `guard_hallucinations`, `beam_size`, `drop_trailing_boilerplate`, `rolling`, `rolling_window_s` | `language` (must stay pinned, `config.py:2275-2277`) |
| `[review]` | `enabled`, `card_seconds`, `corner`, `accept_key`, `reject_key`, `later_key`, `edit_key`, `fix_in_field` | `max_changes`, `witness`, `max_clip_seconds`, `llm_per_day`, `local_model` | `x`, `y`, `scale` (state) |
| `[tests]` | — | — | `nightly`, `wait_seconds` (owner's scheduled task) |

---

## Dependencies and binaries

### pip (measured in `.venv\Lib\site-packages`, total **2398 MB**)

| Package (installed version) | Size | Native? | Needed by | Optional? |
|---|---|---|---|---|
| `nvidia-cublas-cu12` 12.9.2.10, `nvidia-cudnn-cu12` 9.24.0.43, `nvidia-cuda-nvrtc-cu12` 12.9.86 | **1986 MB** combined | DLLs | CTranslate2 GPU inference; found by `local_whisper.py:51-79` | yes — CPU works, 40× slower (`requirements.txt:10-12`) |
| `faster-whisper` 1.2.1 + `ctranslate2` 4.8.1 | 2 + 60 MB | ctranslate2 DLL (CUDA 12 build) | local backend, rolling decode, language detect | required for local ASR |
| `onnxruntime` 1.28.0 | 45 MB | DLL | faster-whisper's Silero VAD (`local_whisper.py:406-416,478-479`) | pulled by faster-whisper |
| `av` 18.0.0 (PyAV) + `av.libs` | 5 + 63 MB | bundled FFmpeg libs incl. libx264 | screen recording encode (`capture.py:51-52,1757-1805`), non-16 kHz mic resample (`local_whisper.py:105-120`), phone audio decode (`server.py:171-172`) | pulled by faster-whisper; **no ffmpeg.exe needed** |
| `numpy` 2.4.6 (+`numpy.libs`) | 37 + 21 MB | yes | recorder, whisper | required |
| `sounddevice` 0.5.5 | small | bundles PortAudio DLL | recorder (`recorder.py:17`) | required |
| `pywin32` 312 (`win32`, `pythonwin`, `win32com*`) | ~20 MB | yes | named pipe (`control.py:56-62`), clipboard (`injector.py`) | required |
| `pillow` 12.3.0 | 16 MB | yes | every card renderer, `ui.py`, `ImageGrab` in `visual_qa.py` | required — **missing from requirements.txt** |
| `google-genai` 2.17.0 + `pydantic`(11 MB) + `cryptography`(11 MB) + `httpx`/`anyio`/`websockets`/`google-auth`/`protobuf` | ~17 MB + ~35 MB deps | cryptography, pydantic_core DLLs | Gemini backend and cloud fallbacks (`transcribers/gemini.py:16`) | cloud-only; imported at module import |
| `pycaw` 20251023 + `comtypes` 1.4.16 + `psutil` 7.2.2 | 4 MB | comtypes generates COM wrappers on first use | WASAPI loopback "computer sound" in recordings (`capture.py:1894-1899`), `audio_check.py`; comtypes also for the taskbar relaunch properties (`dashboard.py:562-563`) | system-sound capture only |
| `skia-python` 144.0.post2 + `icudtl.dat` | 15 + 10 MB | `.pyd` | the "skin" (`skin/*.py`) | **optional by design** (`requirements.txt:16-29`; `skin/__init__.py:53-66`) |
| `huggingface_hub` 1.27 + `hf_xet` 1.6 + `tokenizers` 0.23 + `tqdm` + `filelock` + `fsspec` + `requests` + `pyyaml` | ~35 MB | tokenizers/hf_xet native | model download + faster-whisper | pulled by faster-whisper |
| `keyboard` 0.13.5 | small | no | **unused** — the repo's own `keyboard.py` shadows it (`dashboard.py:75` imports the local module) | remove |
| `pip`/`setuptools` | 24 MB | — | — | not shipped |

Without the NVIDIA wheels the venv is ≈410 MB; without skia ≈385 MB. Plus models: 3.1 GB Whisper (HF cache), and for the owner's default experience Ollama with `gemma3:12b` (~8 GB) and `llama3.1:8b` (~5 GB) (`config.toml:472,610,1538,319`).

### External binaries assumed

| Binary | Where used | Required? | On this machine |
|---|---|---|---|
| `pythonw.exe` / `python.exe` 3.11 in `.venv` | `DeskIT.vbs:8`, `Dashboard.vbs`, `launch.py:41`, `nightly_tests.ps1:43`, hook command | required | python.org 3.11.9 |
| `wscript.exe` | Startup/Desktop `.lnk`, `dashboard.py:601,1170` | required for the current launch path | Windows |
| `git` | `versions.py:57`, `dashboard.py:932` (log/fetch/push/rev-parse/reset) | no (owner feature) | `/mingw64/bin/git` |
| `claude.exe` | `weekly_review.ps1:46-103,269`; counted by `awake.py:421` | no (owner feature) | not on PATH; inside the Claude desktop package |
| `tailscale.exe` | `server.py:116-160` | only for the phone | `C:\Program Files\Tailscale` |
| `ollama` (server on 11434) | HTTP only, never spawned (`config.py:326`) | for local-LLM features | `%LOCALAPPDATA%\Programs\Ollama`, autostarted via Startup `Ollama.lnk` |
| `ffmpeg.exe` | **not used** (PyAV bundles libav, `capture.py:51-52`) | no | not on PATH |
| `powershell.exe` 5.1 | `awake.py:338`, `visual_qa.py:1172` (TTS), `main.py:4187`, `dashboard.py:5176`, both scheduled tasks | for TTS, awake probes, owner scripts | Windows |
| `powercfg`, `tasklist`, `nvidia-smi`, `taskkill`, `explorer` | `awake.py:283,425,645`, `nightly.py:644`, `capture.py:1724` | optional probes | Windows / NVIDIA driver |

---

## Distribution risks

1. **Tracked `config.toml` is the owner's live state** — device name, absolute folders, positions, project names, `server.enabled=true`; every clone/installer copy inherits it, and the app writes back into the same file (`config.py:2340`). Uncommitted drift is constant (`git status`: modified now).
2. **`questions.json`/`questions.lock` and `.agents\` are untracked and not ignored** — one `git add .` publishes the owner's Hebrew Q&A about his codebase to GitHub. `.html` pages are ignored only by the root glob (`.gitignore:28`).
3. **Secrets beside the code**: `.env` (`apikey.py:19`) and `server_token.txt` (`server.py:69`). An installer that copies the folder, a "zip your app folder" support flow, or a shared Program Files install leaks or shares them. No encryption at rest.
4. **Data = code folder**: an updater that replaces the folder deletes history; Program Files is read-only; two Windows users share one history; uninstall removes personal data or leaves it behind unpredictably.
5. **Size and hardware**: 2.4 GB venv + 3.1 GB models + ~13 GB Ollama models; the owner's defaults need ~11 GB VRAM (3 GB whisper + ~8 GB gemma3:12b). Most users will be CPU-only or 6–8 GB cards; no lite tier exists.
6. **Python 3.11 + venv + `.vbs`**: no bundled interpreter; wheels pin 3.11; `pyvenv.cfg` is absolute; `local_whisper.py:51-79` assumes the pip-venv `site-packages/nvidia` layout (breaks under PyInstaller unless re-pointed).
7. **Global names collide across users/installs**: `\\.\pipe\DeskIT.control` (`control.py:43`), port 8756 (`config.py:1125`), the temp DB name `hd-notify-watch.db` (`notify_watch.py:147`), scheduled task names, the Startup `.lnk`.
8. **Owner machinery that can change the machine or the code**: the Saturday task runs an autonomous Claude session that edits the repo; Push/Undo run `git push`/`git reset --keep` (`dashboard.py:1039,1104`); `install_fonts.py` writes HKCU; `[awake] pin_timeouts` runs `powercfg` (`awake.py:283`); `notify_hook.py --install-hook` edits `~/.claude/settings.json`. None of it may ship enabled.
9. **Privacy surfaces that need consent copy**: Gemini free-tier training clause (README:66-74); `notify_watch` copies *all* apps' toasts (`notify_watch.py:405-422`); `problems` pins audio + screenshots; `lookup_cache.json` records what was read; `corpus\`/`recent\` keep voice; `capture` writes screen pixels. All default on except screenshot upload.
10. **First-run 3 GB download with no consent/progress/checksum/resume UI** (`local_whisper.py:28`).
11. **No versioning**: `versions.py` reports a git branch; `problems.env()` stamps `branch` + python (`problems.py:274-282`); there is no version number, changelog or update check.
12. **Docs disagree** (README vs `config.py` vs `config.toml` defaults — see "Documentation drift"); README Setup still describes device *index*.
13. **Windows-11/Claude-Desktop-specific code paths** (`notify_watch.py:154`, `notify.py:436`) silently do nothing elsewhere.
14. **`requirements.txt` is incomplete and unpinned** (no `pillow`; an unused `keyboard` package installed; no lock file), and the local `keyboard.py` shadows a pip package of the same name.
15. **Licensing to verify before redistribution**: ivrit-ai model weights, `deepdml` model, NVIDIA CUDA runtime redistribution terms, Rubik (OFL — fine), skia-python (BSD), PyAV/FFmpeg (LGPL/GPL build flags of the wheel — check for libx264 GPL), pywin32 (PSF), google-genai (Apache-2.0).
16. **Elevated windows** cannot be dictated into from a non-elevated app (README:4146-4150) — an installer must not run the app elevated, but the guide must explain it.

---

## Recommendations for the plan (concrete)

1. **Introduce `paths.py` and split four locations**, then replace the ~40 `Path(__file__).resolve().parent / …` sites (listed under "Files"): `APP_DIR` (install, read-only: code, `defaults.toml`, `fonts\`, `icon.*`), `DATA_DIR = %APPDATA%\DeskIT` (`settings.toml`, `vocab.json`, `review.json`, `notify.json`, `problems\` + `problems.json`, `lookup_cache.json`, `transcripts.log*`), `STATE_DIR = %LOCALAPPDATA%\DeskIT` (`state.json` with positions/dot/device/`setup_done`, `awake_state.json`, `app.log*`, `awake.log`, `notify.log`, `cache\cues`, `recent\`, `pending\`, `corpus\`), pictures default to `%USERPROFILE%\Pictures\DeskIT`. Keep a **portable mode** (a `portable` file beside `main.py` → everything beside the code) so the owner's dev checkout keeps working unchanged.
2. **Settings store**: ship the current `config.toml` as `defaults.toml` (read-only, keeps every measurement comment; `settings.py` keeps generating the page from it). User changes go to `%APPDATA%\DeskIT\settings.toml` containing only overrides, written by a 20-line serializer (`section.key = value`, scalars and string lists only). `config.load()` = dataclass defaults ← `defaults.toml` ← `settings.toml` ← `state.json`. Retire `set_values`'s section-only limitation and the top-level insert path. One-time migration imports a legacy `config.toml` diff. Positions, `audio.device`, `camera.device`, `visual_qa.voice`, `translate.ollama_url` move to `state.json`.
3. **Secrets**: never in `settings.toml`. Store Groq/Gemini keys DPAPI-encrypted (`CryptProtectData`, user scope) in `%APPDATA%\DeskIT\keys.bin` or in Windows Credential Manager (`CredWrite` via ctypes — no new dependency); `server_token.txt` → `STATE_DIR`. Mark secret fields in the settings schema as `sync: never`; any Supabase settings-sync serializer must run through that schema, with a unit test that asserts the payload contains no `*_API_KEY` and a published `NETWORK.md` listing the only outbound hosts (`api.groq.com`, `generativelanguage.googleapis.com`, `api.cerebras.ai`, `huggingface.co`, `127.0.0.1`, the Supabase project). Route all outbound HTTP through one module with a host allow-list so the proof is one file a reviewer can read.
4. **Ship different defaults**: `backend=local`; `[server] enabled=false`; `[vocab] terms=[]`; `[capture]/[camera] folder` = Pictures; all `x/y` = unset; `[notify] watch="off"`; `[awake] hold=false`, `vitals_minutes=0`; `[study] corpus_keep=0` (opt-in with a disk/privacy sentence); `[vocab] keep_audio` smaller (e.g. 20); `[polish] when="never"` until a repair backend is detected; `[visual_qa] enabled` only when Ollama is detected; remove `[tests]`, `cerebras_*`, `lookup.dwell_ms`.
5. **Hardware tiers at first run**: probe NVIDIA + VRAM (nvidia-smi or CTranslate2 device query): ≥6 GB → GPU float16/int8; else CPU int8 with a warning and a measured expectation; detect Ollama at 11434 and list which features light up; offer the free Groq key as the CPU user's repair path with an explicit consent screen quoting `translate.py:401-407`.
6. **Packaging**: Inno Setup (or MSIX later) installer that bundles a private CPython 3.11 (embeddable package) plus a pre-resolved wheelhouse, in two flavours — *CPU* (~450 MB) and *GPU* (+2 GB CUDA wheels) — and downloads the two Whisper models on first run with progress, resume and checksum (or offers an offline model pack). Replace `.vbs` with a tiny launcher (`DeskIT.exe` stub or a shortcut to the private `pythonw.exe main.py`); the installer owns the Startup entry (checkbox), the Start-menu shortcut, and the uninstaller (removes Startup entry, optional hook entries via a new `notify_hook.py --uninstall-hook`, asks before deleting `DATA_DIR`/`STATE_DIR`). If PyInstaller is chosen instead, re-point `local_whisper._register_cuda_dlls` and `skia`/`av` DLL discovery to the bundle dir.
7. **Versioning and updates**: add `VERSION` + `__version__`; `versions.py` returns it (git branch only when `.git` exists); `problems.env()` stamps it. Publish installers as GitHub Releases (free) with a `latest.json`; the app checks weekly, downloads, verifies SHA-256, and runs the installer in upgrade mode — data dirs untouched. Remove Push/Undo/`_scan_changes` from non-developer builds behind a `DEVELOPER` flag (= `.git` present beside the code).
8. **Owner-only machinery out of the shipped tree**: `nightly*.py/.ps1`, `install_nightly_task.ps1`, `weekly_review.ps1`, `questions.py`, `tests*.py`, `make_icon.py`, `audio_check.py`, `install_fonts.py`, `android\`, `.claude\`, `AGENTS.md`, `*_PLAN.md`, `SKIN.md`, `.html`, `.agents\` — keep in the repo under `dev\` or exclude via the installer manifest. Add `questions.json`, `questions.lock`, `.agents/` to `.gitignore` now.
9. **Collision-proof names**: `\\.\pipe\DeskIT.control.<session-or-SID>`; bind 8756 and fall through to the next free port, writing the chosen port into `state.json`, which `notify_hook.py` reads instead of `config.toml` (`notify_hook.py:365-374`); per-process temp names in `notify_watch`.
10. **Problem reports to Supabase**: keep local by default; "Send" is per report, shows exactly what will be uploaded (text fields from `problems.env()` + the typed line + raw/final text), with WAV and screenshot as separate opt-in ticks; store under the user's account row with RLS; never auto-upload.
11. **requirements**: pin (`requirements.lock`), add `pillow`, drop `keyboard`, split extras (`-gpu`, `-skin`, `-cloud`); rename the local `keyboard.py` (e.g. `keycaps.py`) to stop shadowing.
12. **Docs**: generate the user guide's settings chapter from `settings.py`'s parse of `defaults.toml`; fix README Setup (device by name) and the key-default table; add `THIRD_PARTY.md` after verifying the model and CUDA licences.
13. **Multi-user Windows**: with per-user `DATA_DIR`/`STATE_DIR`, `Local\` mutex, per-session pipe and dynamic port, two logged-in users can each run their own copy of a per-machine install.
