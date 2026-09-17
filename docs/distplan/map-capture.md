# DeskIT subsystem map: Screen capture, recording, camera, ask-the-screen

Repo: `C:/Users/shimr/Desktop/Organized/Projects/DeskIT` (read-only survey, 2026-09-15).
All line numbers are from the files as they stood on that date.

## Purpose

Four hotkeys that put pixels somewhere:

| Key (owner's config) | Code default | What it does | Module |
|---|---|---|---|
| `win+shift+s` (config.toml:767) | `ctrl+f11` (config.py:548) | Freeze + dim the screen, drag a box or Shift-lasso; picture goes to the clipboard, optionally to disk, and a corner card offers crop / draw / arrow / blur / Ask | capture.py `Controller.begin_shot` (6177) |
| `ctrl+f12` (config.toml:783) | `ctrl+f12` (config.py:550) | Pick a region or a whole monitor, record to mp4 with optional system sound + mic until the key is tapped again | capture.py `Controller.toggle_clip` (6549) |
| `ctrl+f6` (config.toml:959) | `ctrl+f6` (config.py:680) | Open the webcam in a card, take a still, land it in the same folder / clipboard / editor | capture.py `Controller.begin_photo` (6418) |
| `ctrl+f10` (config.toml:594) | `ctrl+f10` (config.py:481) | Drag a region, ask a vision model about it by voice or keyboard; answer streams in Hebrew, optional TTS | visual_qa.py `Controller` |

capture.py's own summary (capture.py:1-17): "It is Win+Shift+S, plus the editor, plus a recorder, plus a camera ... nothing leaves the machine". visual_qa.py's (visual_qa.py:1-11, 104-122): "the lookup key, but for pixels"; local-first by design, screenshot never written to disk.

## Files and what each does

| File | Lines | Role | Notes |
|---|---|---|---|
| `capture.py` | 6707 | Screenshot selector/editor (`ShotWindow` 2842+), corner-card deck (`ShotCards`/`ShotToast` ~4400-5200), mp4 writer (`Clip` 1735-1832), WASAPI loopback (`SystemSound` 1835-2000), mic + mixer (`ScreenRecorder` 2004-2360), clip bar (`ClipBar` ~3980+), webcam (`Camera` 2471-2610, `CameraWindow` 5340+), and the `Controller` (6000-6707) main.py talks to | No network code at all (grep for urllib/http/requests/socket: zero hits). Imports visual_qa for palette + text renderer (capture.py:212-218). |
| `visual_qa.py` | 4348 | Ask-the-screen: region selector, floating card, backend chain (`OllamaVision` 556, `GroqVision` 783, `GeminiVision` 904, `Chain` 971-1075), TTS (`Speaker` 1131+), `Controller` (~4130+) | Owns `virtual_screen()` (371-381) and `work_area_near()` (384-404) that capture.py re-exports. |
| `hint.py` | 180 | The hold-card rows: reads `capture.hotkey`, `capture.record_hotkey`, `camera.hotkey`, `visual_qa.hotkey` off the live Config (92-141) so a rebound key moves on the card | Pure Python. Hebrew labels hard-coded (30-43, 151-178). Guards for a `classic` branch (95-98). |
| `answer_card.py` | 698 | **Not part of this subsystem.** It is the weekly-review "question" card (imports `problem_card`, 93; docstring 1-90 describes the Saturday routine asking the owner a question). Its only link to capture is that it draws Hebrew through `visual_qa.text_pil` via problem_card's cached wrappers (docstring 70-80). | Belongs with the problems / weekly-review map. |
| `config.toml` `[visual_qa]` 554-721, `[capture]` 722-924, `[camera]` 925-1015 | | Owner's live values with the comments the dashboard's Settings page is generated from | Contains owner-absolute paths (see below). |
| `config.py` `VisualQAConfig` 464-515, `CaptureConfig` 528-653, `CameraConfig` 656-709; parsing 1797-1844 | | Code defaults and validation | Defaults are relative (`captures`). |
| `captures/` | | Empty directory in the repo (0 files, observed). Gitignored (`.gitignore`: `captures/`). | The owner's real captures are outside the repo (see stores). |
| `main.py` | | Builds `visual_qa.Controller` lazily (798-801) and `capture.Controller` lazily with `ask_provider=self._ask_card` and `hush_overlays` (819-824); tap handlers `_tap_capture`/`_tap_record`/`_tap_photo` (2965-3009); `_SCREEN_ACTIONS` (211) lets these four fire mid-dictation; startup log line 6251-6262 states "screenshots are never written to disk, cloud upload OFF/ON". | |
| `hotkey.py` | | `_takes_the_key` (319-329): a Win-modifier chord is the ONE chord the hook swallows; the swallow itself at 809-822. `parse_binding` refuses Win as the trigger key (271-288). | This is the Win+Shift+S mechanism. |
| `apikey.py` | | Key discovery for Groq/Gemini backends: env var first, then `.env` next to the code (10-31, 56, 65) | Shared with other subsystems. |
| `translate.py` | | `GROQ_URL = "https://api.groq.com/openai/v1"` (367), `USER_AGENT = "deskit/1.0"` (373) used by `GroqVision` | |
| `tests.py` | | "THE privacy test" 10804-10836: built chain has no cloud backend when the gate is shut; `capture_dir` relative-to-app test 13595-13605; default folder asserts 13718, 14897 | These pin today's defaults. |

## Personal data stores

| What | Where | Format | Sensitivity | Must be per-user? | Evidence |
|---|---|---|---|---|---|
| Screenshots `shot YYYY-MM-DD HH-MM-SS.png` | `[capture] folder`. Owner: `C:\Users\shimr\Desktop\Organized\Photos\Screenshots\DeskIT capture` (config.toml:789). Code default `captures` **relative to the code folder** (`Path(__file__).resolve().parent / folder`, capture.py:1681-1684). Folder is created on demand (`mkdir(parents=True)`, 1684). | PNG (RGBA if lassoed) | Highest: anything on screen (mail, banking, chats) | Yes | `save_image` capture.py:1700-1711; name scheme 626-647. Written only when `always_save = true` (owner: false, config.toml:844) or the card's Save is pressed (capture.py:6310-6313), or from the editor (3695). |
| Camera photos `photo ....png` | `[camera] folder` (owner: same Photos folder, config.toml:993; default `captures`, config.py:702) | PNG | High: a photo of the room / the person | Yes | `kind="photo"` capture.py:637, 5359, 5379; saved at the shutter before the editor (docstring 5357-5362). |
| Screen recordings `clip ....mp4` | `[capture] clip_folder` or `folder` (owner: `C:\Users\shimr\Desktop\Organized\Videos\DeskIT`, config.toml:795; default "" = same as `folder`, config.py:557) | mp4, h264 yuv420p + optional AAC mono 48 kHz | Highest: screen video plus, when switched on, what the speakers played (WASAPI loopback, capture.py:1835-2000) and/or the microphone (2262-2280) | Yes | `_new_recorder` capture.py:6652-6669; `Clip._open` 1755-1779. Owner has 3 clips there (observed). |
| Clipboard | System clipboard: CF_DIB + registered "PNG" for pictures (capture.py:1273-1315); CF_HDROP path for clips (1318-1357) | | Transient but leaves the app to any clipboard manager, and to Windows cloud clipboard if the user enabled Win+V sync | n/a | `copy_to_clipboard = true` (config.toml:801, 1001); "the clipboard is not negotiable" (capture.py:2898-2903). |
| Ask-the-screen screenshot | RAM only | JPEG bytes / base64, long side capped at `max_side_px` (1344) or 896 for Groq | Highest | n/a | visual_qa.py:118-122 docstring; `encode_jpeg` 359-368 "In-memory only"; 4245-4246 "Nothing is cached, nothing persists". |
| Frozen desktop copies behind corner cards | RAM only, ~18 MB per card, up to `toast_stack` (max 8) | PIL image | High while resident | n/a | capture.py:326-330; config.py:518-524. |
| The spoken/typed question | `transcripts.log` line `VISUAL-QA-Q \| 2.1s \| <question>` | text | Medium (what the user asked about their screen) | Yes | visual_qa.py:3784 (`transcript_log`); docstring 120-121. |
| The model's answer | `app.log` at DEBUG | text | Medium (describes screen contents) | Yes | visual_qa.py:3785. |
| TTS scratch | `%TEMP%\vqa-tts-<rand>\speak.ps1`, `aN.txt` (the answer text, UTF-8), `aN.wav` | text + wav | Medium (answer text on disk briefly) | per-user by construction (%TEMP%) | visual_qa.py:1165-1166, 1195-1206; docstring says deleted after playback (1138-1139). |
| Crossover: problem-report screenshot | `problems.json` / `problems/` pins a JPEG of the whole screen taken at the problems key | JPEG | Highest | Yes | main.py:3719-3760 (`_problem_shot`, `problems.pin_shot`); `.gitignore` comment on `problems/`. Owned by the problems map, but it is the same grab path and must be excluded from any upload. |

Observed on disk: the repo's `captures/` is empty; the owner's Photos folder holds 1 PNG (2026-09-06), the Videos folder 3 clips.

## Machine-specific assumptions

| Assumption | Where | Effect elsewhere |
|---|---|---|
| Owner's absolute folders `C:\Users\shimr\...` | config.toml:789, 795, 993 | Shipping this config.toml would `mkdir -p` those paths on another user's disk (capture.py:1684). Code defaults are `captures` relative to the code folder (config.py:554, 557, 702). |
| Relative `folder` resolves against `Path(__file__)` (the code folder), because the app is launched from a .vbs, a shortcut and a scheduled task with different CWDs | capture.py:1676-1684 | Under an installer into Program Files this is unwritable and not per-user; uninstall would take the pictures with it. |
| Multi-monitor desktop with negative coordinates: "primary 2560x1440, virtual screen (-1920, 0) 4480x1440" | visual_qa.py:26-31, 371-381, 468; capture.py:440-447 (`monitors()` via EnumDisplayMonitors), 328-330 ("3 monitors, 2026-09-03") | Code is generic (GetSystemMetrics / EnumDisplayMonitors / MonitorFromPoint), so 1 monitor works; but only this layout was ever tested. |
| Process is DPI-unaware at 100 % scaling; "There is no correction factor anywhere in this module and adding one would break the machine it works on" | visual_qa.py:24-31 | On a 125-150 % laptop Windows virtualises coordinates for a DPI-unaware process, so grabs come back at the virtualised (lower) resolution and text in captures will be soft. Not measured; must be tested. |
| Pixel positions of the owner's skin dot ("pill x 2392-2542, dot x 2514-2552") baked into `DOT_ROOM_X = 52` | capture.py:333-346 | Constant, not a path; harmless but owner-derived. |
| `preview_fit`: "a 1280x720 camera is 1:1 on this 2560x1440 monitor" | capture.py:805-809 | Adapts (downscales on small screens). |
| Webcam eMeet C960, MJPEG pin, 25 fps | capture.py:2559-2582 (mjpeg then raw fallback), 754-790 (`pick_camera` skips virtual cameras: obs, droidcam, manycam, nvidia broadcast, ...) | `device = ""` picks the first non-virtual device; a machine with ONLY a virtual camera opens it (789-790). |
| Default render endpoint "Arctis 7 Game" at 48 kHz float for loopback | capture.py:1857-1860, 1913-1931 | Any default speaker works; if none, `_listen` logs "the recording has no sound" and keeps the picture (2350-2357). |
| Mic is dictation's `[audio] device`, and WASAPI auto-convert rung borrowed from recorder.py for drivers that refuse 48 kHz | capture.py:2262-2280, 6665-6668 | Same per-machine device string other subsystems already carry. |
| Ollama at `http://127.0.0.1:11434` with `gemma3:12b` resident (needs a ~16 GB GPU; "nvidia-smi read 14710/16311 MiB") | config.toml:326, 614-621; visual_qa.py:987-990 | Most users have no Ollama and no GPU; see "What breaks". |
| Hebrew OneCore voice "Microsoft Asaf" installed; Windows PowerShell 5.1 with WinRT projection | config.toml:659-667; visual_qa.py:1081-1110 (PowerShell script), 1170-1176 (`powershell -NoProfile -ExecutionPolicy Bypass -File ...`) | Script falls back to any `he*` voice (1093-1097); with none it keeps the default (English) voice. |
| `WDA_EXCLUDEFROMCAPTURE` (Windows 10 2004+) | capture.py:906, 975-1007 | Fine on Windows 11. |
| Win chord swallow measured on this machine ("three runs of a bare low-level hook") | AGENTS.md:629-640; hotkey.py:277-280 | Behaviour depends on the hook being installed and alive; see risks. |

## External services and what leaves the machine

capture.py itself: **nothing** (no urllib/http/socket; the only subprocesses are `explorer /select,` at 1722-1725). The one route out is the editor's Ask button -> `Controller._hand_to_ask` -> `visual_qa.Controller.open_with` (capture.py:6388-6406), which then obeys visual_qa's gate.

visual_qa.py backends (`Chain._builders`, 980-1010):

| Service | Endpoint | What is sent | Auth | Condition | Optional |
|---|---|---|---|---|---|
| Ollama (local) | `{translate.ollama_url}/api/chat` = `http://127.0.0.1:11434` (config.toml:326; visual_qa.py:692-699) | system prompt + question + Q/A history + base64 JPEG of the selection (long side <= `max_side_px` 1344, q85). Warm-up sends a 1-px PNG (760-770). | none | always in the chain (1003) | The whole feature is dead without it unless upload is allowed |
| Groq | `https://api.groq.com/openai/v1/chat/completions` (translate.py:367; visual_qa.py:863-873) | same, image as `data:image/jpeg;base64` <= 896 px, q80 (207-208, 1035-1041); `reasoning_effort: none`; model `qwen/qwen3.6-27b` | `GROQ_API_KEY` from env or `.env` (apikey.py:10-31; visual_qa.py:788) as `Authorization: Bearer` (833-836) | only if `allow_screenshot_upload = true` (1003-1007) | yes |
| Gemini | google-genai SDK `models.generate_content` (visual_qa.py:906-962); models from `[gemini] models` (config.toml:1578-1583) | image bytes + question + history + system instruction | `GEMINI_API_KEY` / `GOOGLE_API_KEY` from env or `.env` (apikey.py:24, 65) | only if gate open AND `gemini_fallback = true` (1005-1006) | yes |

Guarantees in code worth quoting in a user-facing proof:
- With the gate shut the cloud constructors are never listed (visual_qa.py:1003-1007, docstring 971-978); tests.py:10804-10836 asserts the built list.
- Warm-up never touches a cloud backend (visual_qa.py:4329-4335).
- A superseded question is not retried on the next backend (1064-1068), so a barge-in never spends a cloud request.
- Keys go straight from `.env`/env to the provider; nothing in this path talks to any DeskIT-owned server.

Other things that leave the process (not the machine): PowerShell TTS subprocess with the answer text in a temp file (1195-1214); `explorer.exe` for "show in folder".

## Owner-only or developer-only features

- Owner values in config.toml that are choices, not defaults: `capture_hotkey = "win+shift+s"` (config.toml:767, code default `ctrl+f11`), `system_sound = true` "the owner's choice on 2026-09-12" (config.py:632-638), `toast_seconds = 10` vs default 5 (config.toml:820, config.py:580), absolute folders (789, 795, 993), `voice = "Microsoft Asaf"`.
- The problem-report screenshot pipeline (main.py:3719-3760) feeds the owner's Saturday Claude Code review; it shares the grab code but is owner tooling.
- `classic`-branch compatibility guards ("this file must stay byte-identical on both branches") in hint.py:95-98 and main.py:6265 are developer machinery.
- Measurement prose (hundreds of lines of "MEASURED ON THIS MACHINE") in capture.py:34-100, visual_qa.py:22-75, config.toml:585-591, 752-765, 949-958 is documentation for the owner, not behaviour; harmless but it is what the Settings page is generated from, so the generated help text quotes the owner's hardware.
- `DOT_ROOM_X` derived from the owner's dot placement (capture.py:333-346).
- Hebrew-only labels in hint.py (30-43, 151-178) and Hebrew answers by design in visual_qa (system prompt) — right for the Hebrew audience, owner-shaped for anyone else.

## What breaks on a fresh machine

1. **Shipping the owner's config.toml** creates `C:\Users\shimr\...` on the new machine (capture.py:1684) and, if that fails, `save_image` raises and the capture is only on the clipboard.
2. **Installed under Program Files with the code default `captures`**: folder is relative to the code (capture.py:1681-1684), so saving fails on a locked-down install and is shared between Windows users on a shared PC.
3. **Ask-the-screen without Ollama**: `QAError("cannot reach Ollama at ... the upload gate is off, so there is no cloud fallback")` (visual_qa.py:732-736); warm-up logs "skipped" (4336-4337). The key is effectively dead for the majority (no 12 GB model, no GPU) until they install Ollama + a vision model or opt into upload and paste a Groq/Gemini key.
4. **`gemma3:12b` on a small GPU / CPU**: even with Ollama, 12b needs ~8 GB VRAM; on CPU a single image answer is minutes (owner measured 22.6 s cold on a 16 GB GPU, visual_qa.py:38-40).
5. **No Hebrew voice**: the TTS script keeps the default English voice (visual_qa.py:1093-1097) and reads Hebrew text with it, or produces nothing; Speak button still shows (`speak = "button"`).
6. **PowerShell policy**: `-ExecutionPolicy Bypass` on a temp `.ps1` (1170-1176) can be blocked by AppLocker/WDAC on managed machines; then Speak silently fails after a 60 s wait (1216-1218).
7. **Win+Shift+S**: if the shipped config keeps it, the Snipping Tool stops answering while DeskIT runs (hotkey.py:809-822); ShareX/Greenshot/Snagit users who bound the same chord lose it too; if the hook dies, both fire (the measured failure mode in hotkey.py:277-278).
8. **DPI scaling**: untested above 100 % (visual_qa.py:24-31); expect soft captures and possibly mis-placed cards on 150 % laptops.
9. **No webcam**: handled (log + error cue, capture.py:6437-6442). Only a virtual camera: opens it and shows black (789-790).
10. **Missing wheels**: `av` is only a transitive dependency of faster-whisper (requirements.txt lists sounddevice, numpy, pywin32, google-genai, pycaw, faster-whisper, nvidia-*, skia-python — no `av`). A build that swaps ASR for a cloud backend silently loses the recorder and the camera (`import av` at capture.py:1757, 2407, 2567 is inside functions, so it fails at the key press, not at startup).
11. **Tests pin today's defaults**: tests.py:13604, 13718, 14897 assert `folder == "captures"`; changing the default breaks them until updated.

## Settings classification

Per config.toml key (owner value in parentheses where it differs from the code default).

### `[capture]` (config.toml:722-924; config.py:528-653)

| Key | Tier | Note |
|---|---|---|
| `enabled` | user | kill switch for both keys |
| `capture_hotkey` (`win+shift+s`, default `ctrl+f11`) | user | needs a dedicated "replace Snipping Tool" toggle, see recommendations |
| `record_hotkey` | user | |
| `folder` (absolute owner path) | user, **value must be per-user** | default should be a known folder, not `captures` |
| `clip_folder` (absolute owner path) | user, **value must be per-user** | same |
| `copy_to_clipboard` | user | |
| `after_shot` (toast / editor / nothing) | user | |
| `toast_corner`, `toast_seconds` | user | |
| `always_save` | user | privacy-relevant, keep false |
| `copy_clip_path` | user | |
| `audio` (off / mic) | user | privacy-relevant, keep off |
| `system_sound` | user | privacy-relevant (records calls' far end); default true is the owner's call |
| `cursor`, `announce`, `timer_corner` | user | |
| `quality` (small / balanced / sharp) | user | |
| `fps` | advanced | measured ceiling is machine-bound |
| `max_minutes` | advanced | |
| `toast_stack` | advanced | memory dial (18 MB/card) |
| `toast_in_shots` | advanced | |

### `[camera]` (config.toml:925-1015; config.py:656-709)

| Key | Tier | Note |
|---|---|---|
| `enabled`, `camera_hotkey` | user | |
| `device` | user | substring match; should be a dropdown from `cameras()` (capture.py:2462) |
| `mirror`, `timer` | user | |
| `folder` (absolute owner path) | user, **value per-user** | should default to the same known folder as `[capture] folder` |
| `copy_to_clipboard`, `edit_after_shot` | user | |
| `size`, `fps` | advanced | device-bound |

### `[visual_qa]` (config.toml:554-721; config.py:464-515)

| Key | Tier | Note |
|---|---|---|
| `enabled`, `visual_qa_hotkey` | user | |
| `allow_screenshot_upload` | user, but only through a consent dialog | the single most important privacy switch in the app |
| `prefer` | user (when upload on) | |
| `speak`, `voice` | user | hide/auto-off when no he-IL voice |
| `auto_send`, `echo_to_field` | user | |
| `gemini_fallback` | advanced | |
| `max_side_px`, `num_predict`, `window_alpha`, `warmup` | advanced | |
| `ollama_model` | developer-or-machine | tied to what is pulled and to VRAM; expose as a pick with size hints |
| `groq_model` | developer-or-machine | catalog drifts (config.toml:622-633) |
| `ollama_timeout_s`, `cloud_timeout_s` | developer-or-machine | |

## Dependencies and binaries

| Dependency | Used for | Evidence | Ships how |
|---|---|---|---|
| Pillow | ImageGrab (whole virtual screen), ImageDraw/ImageFilter (marks, blur), ImageTk | capture.py:1260, 3722, 6192; visual_qa.py:2778 | pip wheel |
| **PyAV 18.0.0** | libx264 mp4 encode (`Clip`, capture.py:1755-1779), AAC audio, DirectShow camera demux + device listing (2407-2433, 2559-2582) | `import av` inside functions | pip wheel; **bundles its own FFmpeg DLLs** in `.venv/Lib/site-packages/av.libs`: avcodec-62, avformat-62, avdevice-62 (dshow), avfilter-11, avutil-60, swresample-6, swscale-9, libx264-165, libx265, libSvtAv1Enc, libdav1d, libvpx, libopus, libmp3lame, libwebp, ... (observed). **No ffmpeg.exe** anywhere (none in `.venv/Scripts`, none in the repo); **imageio-ffmpeg is not used** (grep: no hits). |
| numpy | frame buffers, audio mixing | capture.py:1159, 2037 | pip |
| pywin32 (`win32clipboard`, `win32con`) | clipboard | capture.py:1297-1298 | pip |
| comtypes + pycaw | WASAPI loopback (`IAudioClient`, hand-declared `IAudioCaptureClient`) | capture.py:1894-1917 | pip (pycaw in requirements.txt) |
| sounddevice (+ bundled PortAudio) + `recorder.wasapi_auto_convert` | microphone track | capture.py:2262-2269 | pip |
| ctypes user32/gdi32 | BitBlt + DIB grab, `SetWindowDisplayAffinity`, `EnumDisplayMonitors`, `MonitorFromPoint`, `SetWindowRgn` | capture.py:975-1007, 436-475 | Windows |
| tkinter | every window | capture.py:2867 | Python stdlib (needs Tcl/Tk in the bundled Python) |
| google-genai SDK | Gemini backend only | visual_qa.py:907-908 | pip; import is lazy so missing SDK just skips the backend (1013-1019) |
| Windows PowerShell 5.1 + WinRT `SpeechSynthesizer` + he-IL voice; `winsound` | TTS | visual_qa.py:1081-1110, 1170-1176 | OS |
| `explorer.exe` | show in folder | capture.py:1722-1725 | OS |
| `cues`, `fonts`, `ui`, `injector` (in-repo) | sounds, Rubik font loading, palette, clipboard queue | visual_qa.py:250-266; capture.py:1383 | in repo |
| skia (optional) | skin only | not in this path | optional |
| Ollama + `gemma3:12b` | local vision | config.toml:614-621 | separate install, ~8 GB download, GPU |

Licensing note (to verify, not asserted): the PyAV wheel's `av.libs` contains libx264 and libx265, which are GPL; an installer that redistributes the wheel redistributes that FFmpeg build. Check the wheel's build flags and include the licences, or pick an LGPL-only encoder path (e.g. Media Foundation `h264_mf` or openh264) before shipping.

## Distribution risks

1. **Win+Shift+S takeover** (config.toml:767-782; hotkey.py:319-329, 809-822; AGENTS.md:629-640). Users expect the Snipping Tool; the takeover is silent, global, and lasts as long as the hook lives. It also collides with ShareX/Greenshot/Snagit defaults. The code default (`ctrl+f11`) avoids all of this.
2. **Owner-absolute folders + `mkdir(parents=True)`** (config.toml:789, 795, 993; capture.py:1684).
3. **Captures relative to the code folder** (capture.py:1676-1684): wrong under Program Files, shared between Windows accounts, deleted on uninstall.
4. **Ask-the-screen is unusable out of the box** for anyone without Ollama + a big GPU (visual_qa.py:732-736) — the feature will look broken, and the only fix the user can reach is flipping `allow_screenshot_upload`, which sends screenshots to Groq/Google under their terms with no in-app consent dialog today (it is a config key, config.toml:599-607).
5. **Screenshots inside problem reports** (main.py:3719-3760): the moment problem reports go to Supabase, the pinned JPEG would upload screen contents unless explicitly excluded.
6. **Recordings can carry audio**: `system_sound = true` records the far end of a call; `audio = "mic"` opens the microphone. Defaults are defensible (config.py:625-638) but the guide must say so; the per-clip switches on the picker (capture.py:2870-2877) are the right UI.
7. **Clipboard**: every capture goes to the system clipboard (capture.py:2898-2903); users with Windows cloud clipboard sync enabled will have screenshots synced to Microsoft. Not the app's doing, but the guide should say it.
8. **DPI scaling** untested (visual_qa.py:24-31).
9. **GPL FFmpeg in the PyAV wheel** (observed `libx264-165`, `libx265` in `av.libs`).
10. **`av` not an explicit requirement** (requirements.txt) — recorder/camera die at key press if faster-whisper is dropped from a build.
11. **Hebrew TTS voice** absent on most machines (visual_qa.py:1093-1097); PowerShell `-ExecutionPolicy Bypass` may be blocked on managed PCs (1170-1176).
12. **Hotkey collisions**: `ctrl+f10/f11/f12/f6` were "measured free" only in Chrome and Edge on the owner's machine (config.toml:559-563, 594-598); IDEs (ctrl+F12 in Visual Studio / JetBrains) and games disagree.
13. **Memory**: up to 8 frozen desktops at ~18 MB each (config.py:518-524) plus a 4480x1440 PhotoImage per window; fine on 16 GB, noticeable on 8 GB laptops with 4K screens.
14. **Virtual-camera-only machines** open the virtual camera (capture.py:789-790).
15. **Hebrew-only hold-card labels** (hint.py:30-43) if the audience widens.
16. **Tests pin the `captures` default** (tests.py:13604, 13718, 14897).

## Recommendations for the plan

1. **Ship code defaults, never the owner's config.toml.** Keep `capture_hotkey = "ctrl+f11"` (config.py:548). Offer Win+Shift+S as an explicit Settings toggle labelled "Replace the Windows Snipping Tool shortcut while DeskIT runs", with the one-line consequence, off by default. `hotkey._takes_the_key` already does the right thing once the user opts in.
2. **Per-user known folders for pictures and clips.** `capture_dir` already does `expanduser()` (capture.py:1681), so defaults of `~/Pictures/DeskIT` and `~/Videos/DeskIT` work with no code change; better, resolve `FOLDERID_Pictures` / `FOLDERID_Videos` via `SHGetKnownFolderPath` for localised/redirected profiles. Drop the relative-to-code fallback in installed builds (keep it for dev checkouts). Update tests.py:13604/13718/14897.
3. **Make `allow_screenshot_upload` flippable only through a consent card** that lists exactly what leaves (a JPEG of the selected region, long side <= 1344 px; the question; earlier Q/A in the same card) and to whom (Groq and/or Google, under their terms, with the user's own key). Show the backend used on every answer (the card already writes "answered in 2.1 s via ollama", visual_qa.py:3777).
4. **First-press experience without Ollama**: instead of the raw `QAError`, a card with three buttons: "Install Ollama + a small vision model" (link, size), "Use my own Groq/Gemini key" (opens the consent card), "Turn this key off". Consider a smaller default `ollama_model` for non-owner installs (e.g. `gemma3:4b`) with VRAM hints in the dropdown; keep 12b as the owner's value.
5. **Proof that keys never reach the owner**: the capture/ask path posts directly from the user's machine to `api.groq.com` / Google with keys read from `.env`/env (apikey.py:10-31; visual_qa.py:833-836, 906-919). Put the endpoint table above in the user guide and add a test in the style of tests.py:10804 that the capture/visual_qa modules import nothing from the Supabase client, so the claim is checked by CI rather than asserted.
6. **Problem reports**: when Supabase upload lands, strip the pinned screenshot by default (`[problems] shot`, main.py:3730-3731) and require a per-report checkbox to include it.
7. **Audio in recordings**: keep `audio = "off"`; decide whether `system_sound` stays true for strangers (suggest true, with a one-time notice the first time a clip starts with sound — the picker's switches, capture.py:2870-2877, remain the per-clip control).
8. **TTS**: at startup probe `SpeechSynthesizer.AllVoices` once (or query the registry for `he-IL` OneCore voices); if none, force `speak = "off"` in the UI and link to Settings > Time & Language > Speech. Ship the `.ps1` as a file in the install dir rather than writing it to `%TEMP%` (visual_qa.py:1165-1166) so AppLocker rules can allow-list it.
9. **Dependencies**: list `av`, `Pillow`, `comtypes` explicitly in requirements; pin `av` (the DLL set in `av.libs` is version-bound). Decide on the FFmpeg licence question before building the installer.
10. **DPI**: add a test matrix item for 125 % / 150 % / mixed-DPI monitors; if captures come back soft, either declare the process per-monitor-DPI-aware (a whole-app change, every Tk window) or document the limitation.
11. **Camera device**: replace the free-text `device` with a dropdown fed by `cameras()` (capture.py:2462), and stop `pick_camera` from opening a virtual camera when it is the only one (offer "no real camera found").
12. **Hold card localisation**: move hint.py LABELS (30-43) and the strings in `card_for` (151-178) behind the same string table the rest of the UI will need; Hebrew stays the first language.
13. **Guide sections this subsystem needs**: where files go and how to change it; what the Ask key sends and when; the Snipping Tool toggle; that recordings may include computer sound; clipboard sync caveat; that "the light next to the lens goes off at the shutter" (capture.py:174-179) is a real promise.
14. **Remove/disable developer scaffolding in the shipped build**: the `classic`-branch getattr guards (hint.py:95-98, main.py:6265), and the measurement prose from the generated Settings help (or keep it under an "About these numbers" fold).
