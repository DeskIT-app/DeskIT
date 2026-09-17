# DeskIT distribution map — Core dictation pipeline

Read-only survey of `C:/Users/shimr/Desktop/Organized/Projects/DeskIT`, 2026-09-15.
Line numbers refer to the files as they are on disk today (git `main` at 1159b16).

## Purpose

The core pipeline is: a global low-level keyboard hook (`hotkey.py`) drives a push-to-talk state machine; a persistent PortAudio/WASAPI input stream (`recorder.py`) buffers int16 mono audio while the key is held; a rolling thread (`rolling.py`) decodes settled 25 s stretches on the GPU while the user is still talking; on release the tail is decoded, the text is cleaned (`cleanup.py`), and the result is pasted at the cursor by clipboard + `ctrl+v` (`injector.py`). Backends live behind one interface (`transcribers/`): `local` (faster-whisper + the ivrit-ai Hebrew CT2 fine-tune, plus a second general model used as the English detector), `gemini` (Google, audio leaves the machine), `fake` (canned text for tests). Around that: a single-instance mutex and quit event (`singleton.py`), a named-pipe control channel for the dashboard (`control.py`), windowless launchers (`*.vbs`, `launch.py`), audible cues rendered to WAV files (`cues.py`), a durable spool for audio that could not be transcribed (`spool.py`), and the first-run wizard hook (`firstrun.py`, called from `main.py`).

Every byte of state — settings, logs, audio, vocabulary, tokens, keys — is written **next to the code**, because `APP_DIR = Path(__file__).resolve().parent` (`main.py:34`) is the root of everything, repeated independently in `launch.py:16`, `firstrun.py:51`, `server.py:68`, `apikey.py:17`, `cues.py:21`, `versions.py:36`, `install_fonts.py:30`.

## Files and what each does

| File | Lines | Role in the pipeline | Notes for distribution |
|---|---|---|---|
| `main.py` | 6380 | `App` (wiring, workers, config write-backs, phone callbacks), `main()` CLI, logging setup, `--drain/--benchmark/--vocab` tools | Owns every `APP_DIR / ...` data path (`main.py:324-401, 487, 687, 2084, 3525, 3862, 5654, 5661`). `APP_ID = "Yoav.DeskIT"` (`main.py:67`). |
| `recorder.py` | 440 | One persistent `sd.InputStream` (`recorder.py:150-156`), utterance buffer, dead-microphone alarm (`SILENT_PEAK`, `recorder.py:35-36`), three-rung open ladder (plain → WASAPI auto_convert → device's own rate, `recorder.py:127-160`), fallback to system default if the named device cannot open (`recorder.py:107-125`) | Device is matched by `sounddevice` string `"<raw name>, <host api>"`; index also accepted. |
| `hotkey.py` | 1360 | VK table (`hotkey.py:38-73`), chord parsing, `PTTStateMachine` (pure), `HookThread` = `SetWindowsHookExW(WH_KEYBOARD_LL)` + message pump (`hotkey.py:1269-1277`), `send_chord` via `SendInput` | Windows silently unhooks a callback slower than ~300 ms (`main.py:2046-2049`), so feature imports are pre-warmed on a thread (`main.py:2056-2057`). UIPI: no events from / no paste into elevated windows. |
| `injector.py` | 933 | Clipboard snapshot → put text → paste chord → restore (`injector.py:320-420`), process-wide clipboard RLock (`injector.py:103`), `read_selection` for the text keys | Uses `win32clipboard` (pywin32). Windows clipboard history (Win+V) will record every transcript. |
| `rolling.py` | 378 | Decodes 25 s windows during the hold; cut at pauses; `finish(timeout=10)` (`rolling.py:229-240`) discards the head if the thread is still busy | Tuned on an RTX 5060 Ti "~40x real time" (`rolling.py:16`). On CPU the decode of one window can exceed the window itself. |
| `spool.py` | 120 | `pending\` (failed audio, kept until `--drain`) and `recent\` (last N recordings + JSON sidecar with transcript); `keep` trims oldest (`spool.py:69, 112-118`) | Raw audio on disk. |
| `singleton.py` | 170 | `Local\DeskIT.instance` mutex, `Local\DeskIT.quit` event, dashboard pair (`singleton.py:24-29`) | Per-login-session names — already per-user. |
| `cues.py` | 344 | 20 cue WAVs synthesised deterministically into `cues\` beside the code + `cues\.recipe` stamp (`cues.py:21, 279-303`); played with `winsound.PlaySound` | `main.py:6361` calls `ensure_files()` bare at every start (mkdir + writes). |
| `cleanup.py` | 176 | Filler strip, char-run collapse, repeat collapse, Knesset boilerplate tail strip (`cleanup.py:31-45`) | Pure. "Never rewrite the user's words" is enforced elsewhere (punctuate); this only deletes hesitations/boilerplate. |
| `control.py` | 265 | `\\.\pipe\DeskIT.control` named pipe, 4 listener instances, JSON request/reply (`control.py:43, 91`) | pywin32 `win32pipe/win32file`. Local only. |
| `launch.py` | 81 | Spawns `pythonw.exe` from `APP_DIR/.venv/Scripts` first (`launch.py:36-45`) detached; `os.startfile` for log buttons | Assumes a venv inside the code folder. |
| `DeskIT.vbs` / `Stop DeskIT.vbs` / `Dashboard.vbs` | 8/6/7 | `shell.Run "<folder>\.venv\Scripts\pythonw.exe" "<folder>\main.py" [--stop]` (`DeskIT.vbs:8`, `Stop DeskIT.vbs:6`, `Dashboard.vbs:7`) | Hard dependency on a venv next to the code; a VBScript error box if missing. |
| `transcribers/__init__.py` | 54 | `get_transcriber(cfg)` picks `gemini`/`fake`/`local`; `local_kwargs` builds the local backend from `[local]` | |
| `transcribers/base.py` | 34 | `TranscriptionError`, `RateLimitError(retry_after, per_day)`, `Transcriber` protocol | |
| `transcribers/fake.py` | 19 | Canned Hebrew, no model | Test/demo backend; useful for a "try the keys" mode. |
| `transcribers/gemini.py` | 157 | `google-genai` client; sends the **whole WAV** as `Part.from_bytes(mime_type="audio/wav")` (`gemini.py:106-110`); key from `apikey.find_api_key()` (`gemini.py:66`); per-model 429 rotation | Only backend that ships audio off-machine. |
| `transcribers/local_whisper.py` | 823 | `_register_cuda_dlls()` (`local_whisper.py:50-79`); device ladder `[("cuda","float16"),("cpu","int8")]` with a forced warm-up inference (`local_whisper.py:396-417`); eager English/detector model (`local_whisper.py:420-428`); loop retry ladder; `decode_window`/`transcribe_with_head` for rolling | Model names come from `[local] model` / `english_model`; no `download_root`, so the Hugging Face default cache is used. |
| `config.toml` (sections in scope) | — | `[audio] [feedback] [local] [gemini] [dot] [hint] [setup]` + top-level keys | Tracked in git AND the owner's live file — see Machine-specific. |
| `firstrun.py` (hook only) | 730 | `needed()` = `not cfg.setup.done and not .setup-done exists` (`firstrun.py:668-676`); `run()` shows a Tk wizard (mic meter → one sentence with the model → keys); writes `audio.device` through `config.set_values` (`firstrun.py:636-640`) and the `.setup-done` marker (`firstrun.py:680-691`); opens `ms-settings:privacy-microphone` on silence (`firstrun.py:194`) | Called at `main.py:5963-5969` BEFORE any model loads. |
| `apikey.py` | 100 | Key lookup: env var first, then `.env` next to the code (`apikey.py:18, 24-26, 37-52`); names `GEMINI_API_KEY/GOOGLE_API_KEY`, `CEREBRAS_API_KEY`, `GROQ_API_KEY` | The single place keys are read — the natural anchor for the "keys never reach the owner" proof. |
| `server.py` (borrowing side) | ~900 | `PhoneServer` runs inside the app, binds `127.0.0.1:8756` (`server.py:638-641`), bearer token from `server_token.txt` (`server.py:69, 97-113`), shells out to `tailscale.exe` to print a URL (`server.py:116-165`) | See "What the phone endpoint borrows". |

### How the whisper models are downloaded and cached

- Two models, both ~1.6 GB CT2 float16 checkpoints:
  - `ivrit-ai/whisper-large-v3-turbo-ct2` — Hebrew, `[local] model` (`config.toml:1587`, default `config.py:261`).
  - `deepdml/faster-whisper-large-v3-turbo-ct2` — general model, used as the **language detector for every utterance** and as the English transcriber (`config.toml:1602`, `config.py:272`; loaded eagerly `local_whisper.py:420-428`; detection `local_whisper.py:344-370`).
- Construction is `WhisperModel(model, device=dev, compute_type=compute)` with **no `download_root`/`cache_dir`** (`local_whisper.py:404-405`, `local_whisper.py:339`), so faster-whisper's `download_model` → `huggingface_hub.snapshot_download` (venv `faster_whisper/utils.py:116`) uses the default cache `%USERPROFILE%\.cache\huggingface\hub`. No `HF_HOME`/`HF_HUB_*` variable is set on this machine and nothing in the repo sets one (grep of all `.py` outside `.venv`: no hits).
- On disk today: `models--ivrit-ai--whisper-large-v3-turbo-ct2` 1.6 GB, `models--deepdml--faster-whisper-large-v3-turbo-ct2` 1.6 GB (plus `Systran/faster-whisper-tiny` 75 MB, presumably from tests). First run therefore downloads ~3.2 GB.
- The download happens inside `App(...)` at `main.py:6180`, while the splash shows "loading the transcription model…" (`main.py:6179`). The splash mirrors only the `app` logger and deliberately not huggingface's chatter (`main.py:242-248`), and under `pythonw` there is no stderr for tqdm — so a first-run user sees a static line for the whole download. The wizard's step 2 also loads the model ("costs ~25 s the first time", `firstrun.py:28-30`) — on a fresh machine that step IS the download.
- Offline or a failed download → `TranscriptionError("could not load the local model ...")` (`local_whisper.py:416-417`) → `fail()` → `MessageBoxW` (`main.py:6181-6182`, `main.py:233-239`).

### How CUDA is found; CPU-only; low VRAM

- `requirements.txt:8-13` pins `faster-whisper`, `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` ("harmless to install without an NVIDIA GPU"). In the venv: `nvidia/cublas` 737 MB, `nvidia/cudnn` 1.1 GB, `nvidia/cuda_nvrtc` 179 MB — ~2 GB of the 2.4 GB venv.
- `_register_cuda_dlls()` (`local_whisper.py:50-79`) scans every `sys.path` entry ending in `site-packages` plus `sys.prefix/Lib/site-packages` for `nvidia/*/bin`, calls `os.add_dll_directory` on each and **prepends them to the process `PATH`** (`local_whisper.py:74-78`) because CTranslate2 uses plain `LoadLibrary`. Process-local, no persistent change.
- Device ladder (`local_whisper.py:396-417`): `device="auto"` tries `("cuda","float16")` then `("cpu","int8")`; each candidate is forced through a real inference on 0.4 s of silence so a "cuda" that constructs but cannot run (missing DLL, OOM) fails NOW and falls to CPU. The fallback is logged at INFO (`local_whisper.py:409-410`) — the only place the user could learn they are on CPU.
- CPU-only: int8, both models still loaded into RAM, "~40x slower on this box: 8.2 s vs 0.20 s for a 3 s clip" (`requirements.txt:11-13`, README:4253-4258). Rolling windows and hallucination guards were tuned on the GPU (`rolling.py:16`, `local_whisper.py:213-224`); on CPU `Roller.finish(timeout=10)` (`rolling.py:229-238`) can time out, discard the head and decode the whole recording again.
- Low VRAM: there is no VRAM probe. Both models ≈ 3.2 GB VRAM ("about 3.2 GB of VRAM", `server.py:8-9`; README:4246). If the Hebrew model OOMs → CPU (same ladder). If only the English model fails → warning "English model unavailable … Hebrew only" and detection is off (`local_whisper.py:425-428`).

### Microphone selection by name

- `[audio] device` (`config.toml:293`) holds `"Headset Microphone (Arctis 7 Chat), Windows WASAPI"`; the comment (`config.toml:294-304`) explains that an index shifted on 2026-09-05 and stopped the app. `AudioConfig.device` default is `None` = system default (`config.py:33-36`).
- The wizard writes exactly `"<raw name>, <host API>"` (`firstrun.py:102-118 device_key`) via `config_mod.set_values(path, {"audio.device": ...})` (`firstrun.py:639`).
- `Recorder.__init__` opens the named device; on `PortAudioError/ValueError` it logs a warning and reopens the system default (`recorder.py:107-125`). Sample rate refusal → WASAPI auto_convert → device's own rate (`recorder.py:127-160`), with resampling downstream (`local_whisper.py:88-127`).

### First-run wizard hooks

- `main.py:5963-5969`: `if args.setup or (firstrun.needed(cfg) and not args.fake): firstrun.run(cfg, Path(args.config))` then reload config. Runs before the singleton lock, the splash, the control pipe and the models.
- `needed()` (`firstrun.py:668-676`): `[setup] done` override (`config.toml:277-289`, `config.py:242-257`) or the `.setup-done` marker next to the code (`firstrun.py:65`). Marker content is two sentences (`firstrun.py:685-688`); `.setup-done` exists here dated Aug 31.
- The wizard pre-selects `cfg.audio.device or default_device()` (`firstrun.py:333`) — on a fresh copy of this tracked `config.toml` that is the owner's Arctis string, which matches nothing on another machine (`order_for`, `firstrun.py:158-167`).

### What the phone endpoint borrows from the running app

`App.__init__` builds `server_mod.PhoneServer(cfg, self._transcribe_for_phone, lambda: self.transcriber.name, self._translate_for_phone, self._punctuate_for_phone, self._notify_from_outside, review_pending=..., review_decide=..., lookup=...)` when `cfg.server.enabled` (`main.py:771-780`) and starts it in `App.start()` (`main.py:2058-2064`, a busy port is non-fatal). It borrows:
- the loaded transcriber and the learned vocabulary — `_transcribe_for_phone` → `self._transcribe` under the same `_model_lock` as the desktop worker (`main.py:2350-2367`, `main.py:4306-4345`);
- the repair pass (`self._improve`, `main.py:2372`), `recent\` ring with `"source": "phone"` (`main.py:2391-2398`), the second-reading engine (`main.py:2399-2401`), `transcripts.log` (`main.py:2367`);
- translate/punctuate/lookup engines and the notify engine (`server.py:333-560`).
- Token: `server_token.txt` beside the code, `secrets.token_urlsafe(24)` on first run (`server.py:97-113`), sent as a bearer/`#t=` fragment. The full URL **including the token** is logged to `app.log` (`server.py:653-654`; acknowledged at `main.py:259`), and `app.log:445` on this machine contains it together with the owner's tailnet hostname.
- Binding: `cfg.server.host or "127.0.0.1"` : `cfg.server.port` (`server.py:638-639`); `tailscale.exe` is probed at `C:\Program Files\Tailscale\tailscale.exe` (`server.py:116-125`) purely to print the MagicDNS URL.

## Personal data stores

All paths are relative to the code folder unless stated. "Per-user?" = must be per-user/per-install in a distributed build.

| What | Where | Format | Sensitivity | Per-user? |
|---|---|---|---|---|
| Every transcript ever produced (desktop, phone, translate/punctuate/lookup in+out, corrections, polish, review verdicts) | `transcripts.log` + `.1..3` (`main.py:5660-5665`, 1 MB × 3); record kinds `OK`, `PHONE`, `ERROR`, `DISCARDED`, `CORRECTED`, `TRANSLATE-IN/OUT`, `PUNCTUATE-IN/OUT`, `LOOKUP-IN/OUT`, `POLISHED`, `REVIEW`, `DRAINED` (`main.py:5380, 2367, 5370, 2748, 4498, 4646-4782, 5054-5086, 5202, 1657, 5692`) | plain text, UTF-8 | HIGH — full dictation history incl. everything said to Claude Code | yes |
| Status log with pasted text fragments, device names, phone URL + token, tailnet name | `app.log` + `.1,.2` (`main.py:5653-5656`, 500 KB × 2) | plain text | HIGH (token) / MEDIUM | yes |
| Raw audio of the last 50 dictations + sidecar with `text`, `raw`, `backend`, `language`, `words` (per-word confidence), `source`, later `corrected`, `review` | `recent\*.wav` + `*.json` (`main.py:356, 5568-5573, 2391-2398, 4525`; keep = `[vocab] keep_audio`, `config.toml:1338`) — 32 MB here | 16 kHz int16 WAV + JSON | HIGH — voice + text | yes |
| Raw audio that failed to transcribe, with error notes | `pending\*.wav` + `*.json` (`main.py:351, 5340, 5354`; `spool.py:75-97`, keep 100) | WAV + JSON | HIGH | yes |
| Learned vocabulary: pairs of (what it heard, what you meant), hit counts, dates | `vocab.json` (+ `vocab.json.bak-*` left by hand) (`main.py:338`) | JSON | MEDIUM — names, projects | yes |
| Gold/labelled clips and study/review corpus; "read this to me" recordings | `corpus\` (review.py:914, study.py:556) and `corpus\read\` (`main.py:370`) — 199 MB here | WAV + JSON | HIGH | yes |
| Bug reports with the user's typed line, raw/final transcript, pinned audio, screenshot | `problems.json`, `problems.md`, `problems.lock`, `problems\` (`main.py:364, 3525, 3862`) | JSON/MD/PNG/WAV | HIGH — screenshots | yes |
| Second-reading proposals | `review.json`, `review.lock` (`main.py:2084, 2416`) | JSON | MEDIUM | yes |
| Weekly-routine questions (off by default) | `questions.json` (`main.py:401`) | JSON | LOW | yes (owner-only feature) |
| Notifications received (titles/bodies from other programs) | `notify.json`, `notify.log` (`main.py:687`) | JSON | MEDIUM | yes |
| Wake-hold state and log | `awake_state.json`, `awake.log` (`main.py:487, 6175`) | JSON/text | LOW | yes |
| Phone endpoint shared secret | `server_token.txt` (`server.py:69, 111`) | 32-char text | HIGH (bearer) | yes |
| API keys | `.env` (`apikey.py:18`); read by `apikey.py:37-52`; also env vars | `KEY=VALUE` | CRITICAL | yes |
| All settings incl. mic name, card positions, hotkeys, vocab seed terms, server on/off | `config.toml` (read `main.py:5952`; written by the line editor `config.py:2340-2430` from `main.py:1420,1451,1461,1474,1505,1908,1935,3649,3921`, `firstrun.py:639`; temp `config.toml.<pid>.new`) | TOML with comments | MEDIUM | yes |
| First-run marker | `.setup-done` (`firstrun.py:65, 685-688`) | text | none | yes (per install) |
| Cue sounds + recipe stamp | `cues\*.wav`, `cues\.recipe` (`cues.py:21, 279-303`) | WAV | none | per install (could ship prebuilt) |
| Lookup cache keyed by selected text | `lookup_cache.json` (lookup subsystem; `.gitignore:16`) | JSON | MEDIUM | yes |
| Screenshots/recordings | `captures\` (`[capture] folder`) | PNG/MP4 | HIGH | yes |
| Whisper models | `%USERPROFILE%\.cache\huggingface\hub\models--*` (default HF cache; no override anywhere) | HF snapshot dirs, 2 × 1.6 GB | none (public models) | per machine (shareable cache) |
| Rubik fonts (optional installer) | `%LOCALAPPDATA%\Microsoft\Windows\Fonts` + `HKCU\...\Fonts` (`install_fonts.py:33-40`) | TTF + registry | none | per user (optional; `fonts.py:120` loads privately without it) |

Kernel-object names (not files): `Local\DeskIT.instance`, `Local\DeskIT.quit`, `Local\DeskIT.dashboard`, `Local\DeskIT.dashboard.show` (`singleton.py:24-29`), pipe `\\.\pipe\DeskIT.control` (`control.py:43`), loopback socket `127.0.0.1:8756` (`server.py:638-639`), AppUserModelID `Yoav.DeskIT` (`main.py:67`).

## Machine-specific assumptions

- `config.toml:293` — `[audio] device = "Headset Microphone (Arctis 7 Chat), Windows WASAPI"`: the owner's headset, committed in the tracked settings file.
- `config.toml:262-263` — `[hint] x = -1895, y = 823`: a real drag position on the owner's LEFT monitor (virtual desktop starts at x = -1920, `config.toml:271-275`, `config.py:96-104`). On a single-monitor machine this is off-screen; `HINT_UNSET = -100000` is the "never moved" sentinel (`config.py:114`).
- `config.toml:1349-1362` — `[vocab] terms` lists the owner's projects (`HebrewDictation`, `Massif`, `TripSync`, `Cowork`) and toolchain. Seed terms are prompted into every decode (`local_whisper.py:466-476`).
- `config.toml:1305` — `[server] enabled = true` (code default is `False`, `config.py:1117`), so a fresh copy of this file opens a socket and probes `tailscale.exe` (`server.py:116-125`, `152-165`) at every start.
- `main.py:67` — `APP_ID = "Yoav.DeskIT"` baked into the taskbar identity.
- `DeskIT.vbs:8`, `Stop DeskIT.vbs:6`, `Dashboard.vbs:7`, `launch.py:37` — `<folder>\.venv\Scripts\pythonw.exe`: a source checkout with an in-folder venv is the only supported layout. `.venv/pyvenv.cfg` pins CPython 3.11.9 at `C:\Users\shimr\AppData\Local\Programs\Python\Python311`.
- `local_whisper.py:64-66` — CUDA DLLs are looked for under `site-packages/nvidia/*/bin` of the running interpreter (pip-wheel layout); a frozen build must reproduce that layout or call `add_dll_directory` itself.
- `rolling.py:16`, `local_whisper.py:213-224`, `requirements.txt:11-13` — window size, LAG, timeouts and the "8.2 s vs 0.20 s" numbers were measured on an RTX 5060 Ti 16 GB; `Roller.finish(timeout=10)` (`rolling.py:229`) is a GPU-speed assumption.
- `server.py:122-123` — Tailscale install paths; `app.log:445` shows `https://yoav.example.ts.net/#t=…` (tailnet name + token in a log).
- `main.py:5846-5850`, README:4146-4149 — non-elevated process; elevated target windows never receive the paste (UIPI).
- `cues.py:3-9` — `winsound.Beep` inaudible "on this machine"; the WAV path is used everywhere, fine.
- `config.toml:5-60` and `hotkey.py` docstrings — default keys were chosen against the owner's Chrome/Google-apps/NVIDIA-overlay bindings; still sensible defaults, but `insert` as pause and `left` arrow as latch are opinionated.
- `install_fonts.py:33` — writes `%LOCALAPPDATA%\Microsoft\Windows\Fonts` and `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts` (optional dev tool; the runtime uses `AddFontResourceExW(FR_PRIVATE)` from `fonts\` instead, `fonts.py:103-131`).
- `versions.py:60-66` — shells out to `git rev-parse` to name the branch; "(unknown)" without git.

## External services and what leaves the machine

| Service | Trigger | Data sent | Key/auth | Optional? |
|---|---|---|---|---|
| Hugging Face Hub (`huggingface.co`) | first construction of `WhisperModel` for each of the two repos (`local_whisper.py:404, 339`); `snapshot_download` may re-check the repo on later loads unless `HF_HUB_OFFLINE`/`local_files_only` | repo id, library user-agent; no user data | none (public repos) | needed once; ~3.2 GB |
| Google Gemini API via `google-genai` | only when `backend = "gemini"` (`transcribers/__init__.py:41-43`) or `--check` (`main.py:5972-5983`) | the **entire WAV of the dictation** + system prompt (`gemini.py:106-110`); `--check` sends "Reply with exactly: OK" (`gemini.py:153-156`) | `GEMINI_API_KEY`/`GOOGLE_API_KEY` from env or `.env` (`apikey.py:24, 37-52`) | yes — default backend is `local` (`config.toml:196`) |
| Tailscale (local `tailscale.exe`, the user's own tailnet) | `PhoneServer.start()` when `[server] enabled` (`server.py:652`) | nothing sent by the app itself; the phone's audio travels over the tailnet to `127.0.0.1:8756` | bearer token in `server_token.txt` | yes |
| Groq / Cerebras | keys are read by `apikey.py:25-26, 76-81` for the polish/translate subsystems (not the core decode) | text only (other subsystem) | `GROQ_API_KEY`, `CEREBRAS_API_KEY` in `.env` | yes |
| Ollama `http://127.0.0.1:11434` | translate/polish/lookup (`config.py:307`) | text, local only | none | yes |

Audio leaves the machine only through the Gemini backend; the local pipeline is offline after the model download.

## Owner-only or developer-only features (in this subsystem)

- Console-only CLI modes in `main.py:5859-5905`: `--fake`, `--check`, `--list-devices`, `--test-sound`, `--translate`, `--punctuate`, `--lookup`, `--setup`, `--benchmark`, `--study`, `--review`, `--vocab`, `--drain`, `--dashboard`. All need `python.exe` + a terminal; `--drain` is the ONLY way to recover `pending\` audio (`main.py:5675-5710`).
- `weekly_review.ps1` spawned from the questions card (`main.py:4181-4195`) with `powershell -ExecutionPolicy Bypass`; `[questions]` store (`main.py:401-403`, off by default, comments describe the Saturday Claude Code routine).
- `versions.current_branch()` via git (`versions.py:60-66`); `problems.py` stamps it on reports.
- `APP_ID = "Yoav.DeskIT"` (`main.py:67`).
- Owner data in the tracked `config.toml` (mic, vocab terms, card positions, server on).
- Dev tools in the folder: `audio_check.py` (pycaw, `requirements.txt:5`), `install_fonts.py`, `make_icon.py`, `install_nightly_task.ps1`, `nightly_tests.ps1`, `nightly.py`, `tests.py` (1.3 MB), `tests_quiet.py`, `visual_qa.py` plan docs, `PARALLEL_FEATURES_PLAN.md`, `VISUAL_QA_PLAN.md`, `SKIN.md`, `AGENTS.md` (81 KB), `README.md` (293 KB lab notebook), `.claude/commands/weekly-reports.md`, `.agents/`, gitignored `*.html` test pages (`ch.html`, `cp_play.html`, `np_passport.html`, `pp.html`, 2.7 MB).
- `[tests]` config section (`config.py:1128-1150`) and `[setup] done` override.
- The `fake` backend (`transcribers/fake.py`) — a test hook, but also a candidate "demo without models" mode.

## What breaks on a fresh machine

1. **No venv/Python** → the `.vbs` launchers reference `.venv\Scripts\pythonw.exe` (`DeskIT.vbs:8`); WScript shows "cannot find the file" and nothing else. `launch.py:36-45` has the same first candidate.
2. **Read-only install folder (Program Files)** → `setup_logging()` opens `APP_DIR/app.log` (`main.py:5653`) before anything → PermissionError, uncaught, silent under pythonw. Later writes with the same fate: `cues.ensure_files()` bare at `main.py:6361` (`cues.py:280, 291`), `.setup-done` (logged, wizard returns every launch, `firstrun.py:689-691`), `server_token.txt` (`server.py:111`, non-fatal via `main.py:2059-2064`), `pending\`/`recent\` (`spool.py:75`), `vocab.json`, `config.toml` write-backs (`config.py:2416`).
3. **First run downloads ~3.2 GB** inside `App()` with a static splash line (`main.py:6179-6180`); offline → message box "could not load the local model" (`local_whisper.py:416-417`, `main.py:233-239`). The wizard's step 2 triggers the same download.
4. **No NVIDIA GPU** → CPU int8 for both models (`local_whisper.py:396-417`), ~40× slower (`requirements.txt:11-13`); only `app.log` says so. Rolling decode may not keep up (`rolling.py:229-238`). RAM: two 1.6 GB models resident.
5. **Small GPU (≤4 GB)** → second model OOMs → English detection silently off (`local_whisper.py:425-428`), or first model OOMs → CPU.
6. **Microphone** → `config.toml:293` names a device that does not exist; `recorder.py:107-125` falls back to the default with a warning, and the wizard runs first anyway (`main.py:5963-5969`) with a phantom pre-selection (`firstrun.py:333`). Windows microphone privacy off → pure silence; the wizard catches it after 6 s (`firstrun.py:71-73, 194`).
7. **`[server] enabled = true`** (`config.toml:1305`) → socket on 127.0.0.1:8756 + `tailscale.exe` probe; without Tailscale: warning + loopback URL with token logged (`server.py:659-663`).
8. **No `.env`** → fine for `local`; `gemini` raises `MISSING_KEY_MESSAGE` (`gemini.py:66-67`, `apikey.py:84-89`) which points at a `.env` path inside the code folder.
9. **No git** → version "(unknown)" (`versions.py:60-66`).
10. **Elevated target windows** → hook and paste inert (UIPI; README:4146-4149). Installing/launching as admin would invert the problem.
11. **Unsigned scripts / heuristics** → a global `WH_KEYBOARD_LL` hook (`hotkey.py:1269`) + clipboard writes + microphone is the signature AV heuristics flag; SmartScreen on `.vbs`.
12. **Owner card coordinates** (`config.toml:262-263`) → hint card placed at x = -1895 on a machine with no monitor there.
13. **Startup with Windows** is not implemented (no Run key / Startup shortcut anywhere in the core files; the only `winreg` use is `install_fonts.py`).

## Settings classification (per config.toml key in scope)

**User** (safe to expose in a Settings page):
`hotkey`, `english_hotkey`, `latch_hotkey`, `translate_hotkey`, `punctuate_hotkey`, `correct_hotkey`, `lookup_hotkey`, `pause_hotkey`, `auto_pause_fullscreen`, `auto_language`, `backend` (as "Local / Google Gemini" with consent), `splash`, `indicator`, `[audio] device` (via the wizard's list, never typed), `[feedback] enabled`, `[local] cleanup`, `[local] extra_fillers`, `[dot] corner`, `[hint] enabled`, `[hint] corner`.

**Advanced** (keep, but behind an "advanced" fold with the existing comments as help):
`paste_chord`, `restore_delay_ms`, `min_seconds`, `max_seconds`, `latch_max_seconds`, `fallback_to_local`, `[feedback] placeholder`, `[feedback] retry_seconds`, `[local] device` (auto/cuda/cpu), `[local] initial_prompt`, `[local] extra_boilerplate`, `[local] beam_size`, `[local] rolling`, `[local] rolling_window_s`, `[gemini] models`, `[gemini] timeout_s`, `[hint] after_ms`, `[hint] scale`.

**Developer or machine state** (not user-facing; either fixed in code, chosen by the hardware probe, or written by the app itself):
`[audio] sample_rate`, `[local] model`, `[local] language` (must stay `"he"`, `config.toml:1588`), `[local] english_model`, `[local] english_threshold`, `[local] guard_hallucinations`, `[local] drop_trailing_boilerplate`, `[dot] x`, `[dot] y`, `[hint] x`, `[hint] y`, `[setup] done` (an override; the real state is `.setup-done`, `config.py:242-257`), `[server] host`, `[server] port` (in scope only as machine settings), `[tests] *`.

## Dependencies and binaries

- CPython 3.11 (venv, `.venv/pyvenv.cfg`), run under `pythonw.exe`.
- `requirements.txt`: `sounddevice` (bundles PortAudio DLL), `numpy`, `pywin32` (`win32clipboard`, `win32pipe`, `win32file`), `google-genai` (+ `google_auth`), `pycaw` (dev tool only), `faster-whisper` 1.2.1 → `ctranslate2` 4.8.1, `huggingface_hub`, `tokenizers`, `onnxruntime` (Silero VAD), `av` 18 (PyAV, used by `_decode_pcm` and `server.to_wav`), `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` (+ transitive `cuda_nvrtc`), optional `skia-python` (`requirements.txt:15-34`), `Pillow` (capture/vqa).
- Windows APIs via ctypes: `user32` (hook, SendInput, MessageBox, GetForegroundWindow), `kernel32` (mutex/event), `shell32` (AppUserModelID, IsUserAnAdmin), `winsound`, `gdi32` (fonts.py).
- External executables probed: `tailscale.exe` (`server.py:116-125`), `powershell` (`main.py:4188`), `git` (`versions.py:61`).
- Assets shipped in the folder: `fonts\` (Rubik, OFL), `skin\`, `icon.ico`, `icon.png`.
- Sizes on this machine: venv 2.4 GB (2.0 GB of it CUDA), models 3.2 GB, code+assets ~10 MB.

## Distribution risks

1. **Data-next-to-code** — every store above lives in `APP_DIR`; an installed app in Program Files cannot write there, and a per-machine folder cannot be per-user. Ten modules compute `APP_DIR` independently; several engines take an `app_dir` argument (`main.py:487, 687, 2086, 2103`), which is the seam to exploit.
2. **`config.toml` is template AND live state** — tracked in git with the owner's mic, vocab, card positions and `server.enabled`; the line editor can only change keys that already exist inside a section (`config.py:2394-2398`), so upgrades that add keys need a merge step, and users' edits must survive a reinstall.
3. **3.2 GB first-run download with no progress, no consent, no cache control**; `huggingface_hub` may also touch the network on later starts.
4. **~2 GB of CUDA wheels** in the base requirements whether or not the machine has an NVIDIA GPU; no VRAM probe; silent CPU fallback that makes dictation ~40× slower with no user-visible explanation.
5. **Tokens and dictations in logs** — `app.log` carries the phone bearer token and the tailnet hostname (`server.py:653-654`); `transcripts.log` carries everything ever said. Any "attach logs to a bug report" flow must redact.
6. **Keys in a `.env` inside the code folder** (`apikey.py:18`); a distributed proof that keys never reach the owner needs a single, testable read site (already true: `apikey.py`) plus a data dir outside the program.
7. **Gemini backend uploads raw audio** (`gemini.py:106-110`) under free-tier terms that allow training (README:70-76) — must be an explicit opt-in screen, never a config default.
8. **Launchers and identity** — `.vbs` + in-folder venv + `pythonw` ("Python" in Task Manager, `main.py:87-91`); `APP_ID = "Yoav.DeskIT"`.
9. **`pending\` audio has no user-facing recovery** (`--drain` only).
10. **Model licences** — redistribution/auto-download of `ivrit-ai/whisper-large-v3-turbo-ct2` and `deepdml/faster-whisper-large-v3-turbo-ct2` needs a licence check before an installer points at them (not verifiable offline here).
11. **Version comes from git** (`versions.py`); no update mechanism exists.
12. **Global keyboard hook + clipboard + mic** looks like a keylogger to AV heuristics; unsigned.
13. **Card coordinates and owner monitor layout** shipped in config (`config.toml:262-263`).
14. **The English detector costs 1.6 GB disk + ~1.6 GB VRAM** purely to detect language and handle rare all-English utterances; on small machines it is the first thing to drop, but that is not a user choice today.

## Recommendations for the plan (concrete)

1. **One `paths.py`**: `DATA_DIR = %LOCALAPPDATA%\DeskIT` (logs, audio, cache, tokens) and `CONFIG_DIR = %APPDATA%\DeskIT` (config.toml, vocab.json, .env) with a `DESKIT_PORTABLE=1` escape hatch that keeps today's next-to-code layout for development. Replace `APP_DIR / "<data>"` at `main.py:324, 338, 351, 356, 364, 370, 401, 487, 687, 2084, 2416, 3525, 3862, 5654, 5661, 5675, 5732, 5743, 5807, 5859, 6333`, `firstrun.py:52, 65`, `server.py:69`, `apikey.py:18`, `cues.py:21`; keep `APP_DIR` for `fonts\`, `skin\`, `icon.ico`. Migrate on first start if the old files exist beside the code.
2. **Split the config**: ship `config.default.toml` (comments = the generated Settings page, keep that) and create the user's `config.toml` from it; teach `set_values` to insert a missing key at the end of its section (today `config.py:2394-2398` raises) and add a `config_version` key so upgrades can merge new sections. Scrub the template: `audio.device = ""`, `vocab.terms` = a generic dev list or empty, all `x/y = -100000`, `server.enabled = false`, `[setup] done = false`.
3. **Model download as a wizard step**: before `App()`, in `firstrun` step 2, call `huggingface_hub.snapshot_download(repo, cache_dir=DATA_DIR/models, ...)` per model with a progress bar and an explicit "2 × 1.6 GB, from huggingface.co" consent; pass `download_root=DATA_DIR/models` to `WhisperModel` (`local_whisper.py:404, 339`) and set `local_files_only=True`/`HF_HUB_OFFLINE=1` after the first success so later starts never touch the network. Offer the English detector as optional ("Detect English automatically — needs 1.6 GB more").
4. **Hardware tiering in the wizard**: probe `ctranslate2.get_cuda_device_count()` and `nvidia-smi --query-gpu=memory.total` (CREATE_NO_WINDOW); ≥ 6 GB → both models float16; 4 GB → Hebrew float16, no detector (or `int8_float16`); no GPU → say plainly "transcription will take about as long as you spoke", set `beam_size = 2`, drop the detector, keep `rolling`; write the result into config; show the active device on the dashboard Home instead of only in `app.log` (`local_whisper.py:409-415`).
5. **Package as a windowed exe** (PyInstaller/Nuitka onedir) launched by a Start-menu shortcut; retire the `.vbs` files and the `.venv` assumption in `launch.py:36-45`; constant `APP_ID = "DeskIT.App"`; per-user Inno Setup installer into `%LOCALAPPDATA%\Programs\DeskIT` (no admin, which also keeps the UIPI story simple); make the CUDA runtime an optional "GPU pack" (~2 GB) the installer offers only when an NVIDIA GPU is detected; ship the 20 cue WAVs pre-rendered (they are deterministic, `cues.py:180-184`) so nothing is written at startup.
6. **Secrets**: move `.env` to `CONFIG_DIR` (or Windows Credential Manager via `keyring`); stop logging the phone URL with its token (`server.py:653-654`) — log the file path; add a test asserting the only readers of `GEMINI_API_KEY/GROQ_API_KEY/CEREBRAS_API_KEY` are `apikey.py` and that the values are passed only to the provider SDK constructors (`gemini.py:75-77`). That test plus a data dir outside the program is the credible "keys never reach the owner" proof — the Supabase client must never import `apikey`.
7. **Consent and defaults**: Gemini opt-in screen quoting README:70-76; `backend = "local"` stays the default; record consent in `DATA_DIR\consent.json`, not in config.
8. **Retire or hide developer CLI**: auto-retry `pending\` on the next start and surface a "N recordings waiting" card with a button (replaces `--drain`); keep `--benchmark/--study/--review/--vocab/--check` behind `--dev`.
9. **Version and updates**: `VERSION` file read by `versions.py` and `problems.py`; a free update check against a GitHub Releases JSON with "download installer" (no self-update in v1).
10. **Startup with Windows** toggle (per-user `HKCU\...\Run` or a Startup-folder shortcut) — absent today.
11. **Logs**: keep rotation, move to `DATA_DIR\logs`, add "Clear history" (transcripts.log, recent\, corpus\) in Settings; redact `#t=` and dictation text from anything a bug report attaches.
12. **Licence check** for both model repos before the installer or wizard downloads them; document that the Hebrew model is a third-party fine-tune.
13. **User guide inputs from this subsystem**: what the clipboard restore does and that Win+V history keeps transcripts; elevated windows; the microphone privacy switch; CPU vs GPU expectations; where the data lives and how to delete it.
