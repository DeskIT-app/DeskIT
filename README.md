# HebrewDictation

Hold **Right Ctrl**, speak Hebrew, release — the cleaned transcript (no
fillers, punctuated, self-corrections resolved) is pasted at your cursor in
whatever window has focus. Injection is clipboard + Ctrl+V, never
per-character typing, because per-character breaks RTL in terminals.

For anything longer than a sentence, don't keep holding: tap **←** while
still holding Right Ctrl and the recording **locks on** — let go and talk
for as long as you want. Tap **←** again to transcribe, or **Esc** to throw
it away. See [Long dictation](#long-dictation-lock-the-key-with-).

## Setup

Everything below assumes this folder. The venv already exists with all
dependencies installed (`sounddevice`, `numpy`, `pywin32`, `google-genai`).
To rebuild from scratch: `py -3.11 -m venv .venv` then
`.venv\Scripts\pip install -r requirements.txt`.

### 1. API key — read the privacy note before pasting the key

The key lives in a **`.env` file in this folder** (already created), one line:

```
GEMINI_API_KEY=your-key-here
```

The app reads that file directly, so it works in every shell immediately —
no environment variables, no restarts. **Rotating your key? Edit that one
line and save; nothing else changes.**

An environment variable (`GEMINI_API_KEY`) still takes priority if one is
set. Beware the trap it caused during setup: `setx` writes the key to the
registry, but Windows Terminal shares a single process across all its tabs
and windows, so new tabs keep inheriting the *old* environment until you
quit Windows Terminal completely. The `.env` file exists to make that
irrelevant.

> **PRIVACY — this is the deal you are accepting on the free tier:**
> Google may use free-tier API inputs — your prompts **and your audio** —
> to improve its products. Every word you dictate through the Gemini
> backend, including everything you say to Claude Code, goes to Google
> under those terms. The paid tier does not have this clause, and the
> local backend (Backend B below) never leaves this machine. If that
> trade ever stops being acceptable, Backend B is the answer.

### 2. Pick your microphone

```
.venv\Scripts\python.exe main.py --list-devices
```

Put the device **index** (more reliable than names — the MME host API
truncates them) into `config.toml` → `[audio] device`. Empty string means
the system default. On this machine the default is the **Arctis 7 headset
mic**; the eMeet C960 webcam mic and the SteelSeries Sonar virtual mic are
the alternatives.

### 3. Validate the key

```
.venv\Scripts\python.exe main.py --check
```

One tiny text-only request; prints where the key came from, then the API
reply or the exact problem.

## Run

**Normal use: double-click `Hebrew Dictation` on the Desktop** (or
`Hebrew Dictation.vbs` in this folder). It runs in the background with no
console window and no taskbar entry. **Two rising beeps = it is listening.**
To quit: double-click `Stop Hebrew Dictation` — two falling beeps confirm.

Because there is no window, the app enforces one instance at a time
(launching twice would paste every transcript twice) and writes its status
to **`app.log`** in this folder — that is where errors go when nothing is
visible on screen. A startup failure also pops a message box, so a
double-click never fails silently.

**It also starts automatically at login** — a shortcut lives in
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`. To stop that,
delete that one shortcut (`Win+R` → `shell:startup`); the Desktop icon
keeps working either way.

From a terminal, for debugging:

```
.venv\Scripts\python.exe main.py
```

Same app with a live console; Ctrl+C quits. Add `--fake` to run the whole
pipeline with a canned Hebrew string instead of the API — good for testing
paste behavior in a new target app. `--stop` from anywhere asks a running
background instance to quit.

## Behavior you should expect

- **Beeps:** two rising = app ready; high = recording started; high +
  higher = locked on, you can let go; mid = captured, transcribing; single
  mid-high = translating; rising pair = translation landed; two low =
  error; two falling = app stopped. No beep on aborts (by design). Hear
  them all with `--test-sound`.
- **Two `pythonw.exe` processes in Task Manager is normal** — a venv's
  `python.exe` is a launcher stub that runs the real interpreter as a
  child. It is one app; the single-instance guard is what proves it.
- **Combo abort:** pressing any other key while holding the hotkey aborts
  silently — holding Right Ctrl and pressing C does a normal copy and
  records nothing. The latch key (←) is the one exception, and the rule is
  off entirely once locked (see below).
- **Taps** under 0.3 s are discarded; recordings hitting 400 s are
  discarded with an error beep (`max_seconds` — the runaway guard for when
  a key-release gets swallowed, e.g. by an elevated window). A *locked*
  recording has no cap at all.
- **transcripts.log** (this folder, rotates at ~1 MB × 3): every attempt —
  timestamp, duration, backend, latency, and the raw backend text. It is
  the recovery path when a paste lands nowhere, and the evidence when a
  transcription looks wrong. **Privacy:** it is a plaintext record of
  everything you dictate, on this disk. Delete it whenever you like.
- **Windows Terminal shows Hebrew oddly.** WT has no real bidi rendering,
  so pasted Hebrew can *look* re-ordered. The app under the terminal
  (Claude Code) receives the correct string. Display-only — don't debug it.
  Chrome renders properly.
- **WT multi-line paste warning:** WT pops a dialog when a paste contains
  a newline. The Gemini prompt asks for a single paragraph unless you
  clearly dictate structure; if the dialog still annoys you, disable
  `multiLinePasteWarning` in WT settings.
- **Clipboard restore is text-only.** Text that was on the clipboard is
  restored after the paste. An image or copied files can't be restored in
  v0 — the console says so and the transcript stays on the clipboard.
- **Mouse isn't hooked:** Ctrl+Click while holding the hotkey reaches the
  focused app as Ctrl+Click (and recording continues). Don't click while
  dictating.
- The mic stream stays open the whole time the app runs (this is what
  keeps the first word from being clipped), so Windows shows the
  mic-in-use indicator, and a Bluetooth headset may sit in its
  lower-quality headset profile while the app is up.

## Long dictation: lock the key with ←

Push-to-talk is right for a sentence and wrong for a paragraph — your hand
is doing nothing but holding a key down. So the hold can be handed off:

1. Hold **Right Ctrl** and start talking as usual.
2. Still holding it, **tap ←** (the left-arrow, right next to Right Ctrl —
   reachable with the same hand, no need to let go). Two rising beeps.
3. Let go of Right Ctrl. The recording keeps running, **with no time
   limit**, hands free.
4. **Tap ← again** to finish and paste, or **Esc** to discard.

Details worth knowing:

- **← is swallowed, but only while it is doing this job.** It has to be:
  the arrow would otherwise move the caret, which is exactly where the
  transcript is about to be pasted. Idle, it is an ordinary arrow key — the
  app doesn't touch it. This is the only key the hook ever suppresses.
- **Tapping Right Ctrl again also finishes** a locked recording, if that's
  what your hand reaches for first.
- **Stray keys don't abort a locked recording.** While *holding*, another
  key means "you're typing a combo, not dictating" and cancels. Locked,
  your hands are free on purpose, so that rule is off — otherwise one
  keystroke would destroy several minutes of speech. Esc is the way out.
- **The 400 s cap is lifted while locked.** `max_seconds` exists to catch a
  key-release the OS swallowed; a locked recording has no key-release to
  lose, so there is nothing for it to guard. Set `latch_max_seconds` if you
  want one anyway.
- **It is still one utterance.** The whole thing is transcribed in one go
  when you stop, not streamed — a five-minute recording means a longer wait
  at the end (~0.4 s per 10 s of audio on the local GPU backend) and one
  paste of the entire text.
- Pick a different key with `latch_hotkey`. Avoid `right shift`: **Ctrl+Shift
  switches keyboard layout** in Windows, so it would flip you between Hebrew
  and English mid-dictation.

## Translating to English (tap F9)

Dictation always writes what you said, in the language you said it. When
you want the same message in English, **tap** (don't hold) `F9`:

- **Something selected?** Only the selection is translated.
- **Nothing selected?** The whole field is (the key sends Ctrl+A itself).

The English replaces the Hebrew in place, and your clipboard is put back
the way you left it. One mid beep when it starts, a rising pair when the
text lands.

This is a *different* backend from dictation, because Whisper only
transcribes — it cannot translate. Gemini goes first (it keeps `commit`,
`deploy` and friends in Latin script and holds your register); when its
daily cap is spent, or it errors, a local **Ollama** model answers instead,
so the key never dies at 20 requests. Ollama needs the model pulled:

```bash
ollama pull llama3.1:8b
```

Measured 2026-08-12: Gemini ~1–3 s. Ollama ~2.5 s warm, but **~76 s on the
first request after it goes idle** while ~5 GB loads into VRAM — which is
why `ollama_timeout_s` is 150 and not 30.

Guards worth knowing:

- **It refuses over `max_chars` (5000).** With nothing selected the key
  presses Ctrl+A, and in a document editor that means the entire document.
  Above the cap it beeps and changes nothing — select the part you want.
- **The original is written to `transcripts.log` before the paste**
  (`TRANSLATE-IN`), so nothing is lost if the replace goes wrong.
- **Text with no Hebrew in it is skipped** rather than spending a request.
- **Moved to another window while it worked?** It refuses to paste and
  leaves the English on your clipboard instead.
- **Editors that copy the current line when nothing is selected** (VS Code)
  read as "you selected something", so the result is inserted rather than
  replacing — one Ctrl+Z. Chat-style inputs, the actual use case, are
  unaffected.

Check it without touching the keyboard:

```bash
.venv\Scripts\python.exe main.py --translate "אני רוצה לעשות deploy מחר"
```

## Nothing is ever lost

The failure this design exists to prevent: you speak for 20 seconds, the
backend refuses the request, and the speech is gone with only an error
beep. That cannot happen now.

- **A placeholder reserves your spot.** The moment you release the hotkey,
  `...` (configurable, `[feedback] placeholder`) is pasted at the cursor.
  When the transcript arrives it replaces exactly that text, in exactly
  that window. However long the request takes, the words land where you
  were speaking.
- **Failed audio goes to disk, not the bin.** Any backend error writes the
  WAV plus a small JSON sidecar into `pending\` *before* deciding whether
  to retry, so even a crash mid-retry cannot lose it. The file is deleted
  only once its text has actually been produced.
- **It retries by itself** for `[feedback] retry_seconds` (default 45),
  waiting exactly as long as the API's own `retryDelay` asks.
- **`python main.py --drain`** turns anything still in `pending\` into
  text — run it after the daily quota resets. The app also warns at
  startup when recordings are waiting.
- **It never pastes into the wrong window.** If you moved to another
  window, the app refuses to erase the placeholder or blind-paste; the
  transcript goes to your clipboard and the log tells you to press
  <kbd>Ctrl</kbd>+<kbd>V</kbd>.

## Troubleshooting

- **Hotkey or paste dead in a specific window** → that window is probably
  elevated (run-as-admin). Windows (UIPI) blocks both the hook and the
  injection from a non-elevated process. Run this app elevated too, or
  dictate into non-elevated windows.
- **Recordings are pure silence** → Windows Settings → Privacy & security
  → Microphone → allow desktop apps. Also check the startup line that
  names the device being used.
- **No beeps** → `python main.py --test-sound` plays every cue. They go
  through the normal audio mixer to the **default playback device**, so if
  they are inaudible, that app's slider is probably down: run
  `python audio_check.py` to see every app's volume (it flags anything at
  0% or muted) and `python audio_check.py --fix python` to restore it.
  Note: `winsound.Beep` is *not* used — on this machine it returns success
  and produces no sound at all.
- **One app suddenly has no sound while others are fine** → same tool:
  `python audio_check.py`. This already happened once with Chrome sitting
  at 0%. Voice/dictation tools that duck other audio while recording
  (e.g. Wispr Flow) can leave an app turned down if they exit badly.
- **429 errors** → the free tier allows **20 requests per day per model**
  (measured 2026-08-12; the raw body says
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20`).
  Waiting does not help — the bucket only trickles. The app now handles
  this itself: it rests the spent model, rotates to the next in
  `[gemini] models`, and falls back to the local backend when all are
  spent. Nothing you dictate is lost either way (see *Nothing is ever
  lost* below).
- **Over RDP** the combo-abort rule is inert (RDP input arrives flagged
  as injected). Everything else works.
- Keyboard layout (Hebrew/English) does not matter: the paste chord is
  sent as virtual keys, which real apps handle layout-independently.

## Backends

`config.toml` → `backend`:

**Default is `local`.** Measured 2026-08-12 on 8 real Hebrew clips with
ground-truth transcripts (`imvladikon/hebrew_speech_kan`):

| backend | mean WER | mean latency | daily limit |
|---|---|---|---|
| **local** (ivrit-ai on GPU) | **10.8%** | **0.38 s** | none |
| gemini | 15.9% | 2.71 s | 20 requests/model |

The local model is a Hebrew-specific fine-tune; Gemini is a general model,
and it showed it — `להבין` for `להביא`, `בחישוב` for `בחישוק`, `מבזבזים`
for `מבשרים`, all of which the local model got right.

- `gemini`: Google `google-genai` SDK. Transcription **and**
  cleanup in one call (fillers removed, self-corrections resolved, digits,
  English technical terms kept in Latin script) — this is what the local
  backend does not do.
  `[gemini] models` is a **list**, tried in order, because free-tier quota
  is counted per model. A model that reports its cap is rested (30 min for
  a daily cap) and the next one takes over.
  Thinking is disabled for latency, but the two families need *opposite*
  knobs and reject each other's with a 400 — `gemini-2.5*` takes
  `thinking_budget=0`, the newer `-latest` aliases take
  `thinking_level="low"`. Measured on `gemini-flash-latest`: 5.6 s → 2.5 s.
- `fake`: instant canned Hebrew — pipeline testing (`--fake` flag does the
  same without editing config).
- `local` (**default**): faster-whisper + `ivrit-ai/whisper-large-v3-turbo-ct2`,
  fully offline, no quota, nothing leaves the machine. Adds ~8 s to
  startup while the model loads onto the GPU.
  - **The language must stay pinned to `he`** — the fine-tune broke
    Whisper's autodetect completely: measured 2026-08-12, it answers
    `he` with probability **1.00 for every input, including pure English**.
    Never ask it what language it heard.
  - **Mixed Hebrew + English in one press works on the normal hotkey.**
    `[local] initial_prompt` biases the decoder towards "Hebrew with
    English technical terms", which is how this actually gets used.
    Without it the decoder *drops the English half of a mixed sentence
    outright*; with it both halves survive, and Hebrew-only accuracy
    improves as well (WER 10.8% → 9.6%). Add your own jargon to the
    prompt. It is not sent to the English model, where it would only
    confuse things.
  - **English has its own hotkey** (`english_hotkey`, default `f9`), for
    utterances that are *entirely* English — the Hebrew fine-tune
    transliterates those (`Should it work?` → `שיידי וורק`). Hold it and
    the language is forced, no detection involved. For anything with
    Hebrew in it, use the normal key.
  - **Automatic detection is a fallback, not the mechanism.** When no key
    says otherwise, the general model detects the language and English
    wins only at confidence ≥ `english_threshold` (0.8). That threshold
    was calibrated on clean synthetic audio, where English scored ~1.00 —
    but on a real headset it is far less certain: a *Hebrew* sentence
    scored `en 0.57` in practice. Detection is therefore biased hard to
    Hebrew (short Hebrew clips get mis-read as Portuguese/Russian/Dutch at
    0.16–0.73), and you should press the English key rather than rely on
    it. Measured on clean audio: English 5/5, 15/15 short Hebrew clips
    still Hebrew, Hebrew WER unchanged at 10.8%.
  - Pressing both hotkeys at once aborts the recording rather than
    silently picking a language.
  - Both models are loaded at startup (~3 GB VRAM total), because the
    general one is the detector for *every* utterance, not a backup.
  - It only transcribes, so `cleanup.py` runs afterwards to strip
    hesitations (`אה`, `אמ`) and collapse restarted phrases — including
    the Hebrew-specific case where a dangling one-letter prefix splits the
    repetition (`רק את מה ש רק את מה שאנחנו` → `רק את מה שאנחנו`). It is
    deliberately conservative: it leaves `כאילו` alone because it is a
    real word as often as it is filler (add it to `[local] extra_fillers`
    if you never mean it literally). Verified not to change WER on clean
    speech.
  - Needs `faster-whisper` plus `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`.
    Those CUDA DLLs live in `site-packages/nvidia/*/bin`, which is not on
    the DLL search path, so `local_whisper.py` prepends them to `PATH` at
    import. Without that it silently runs on CPU: measured on this box,
    **0.20 s on the GPU vs 8.2 s on CPU** for a 3 s clip.
  - `[local] device` is `auto` (GPU, falling back to CPU). The GPU is
    validated with a real warm-up inference at load, because constructing
    on `cuda` succeeds even when the CUDA libraries are missing — the
    failure otherwise only appears on your first dictation.

## Config reference (`config.toml`)

| key | default | meaning |
|---|---|---|
| `hotkey` | `right ctrl` | push-to-talk key for Hebrew (`f9`, `scroll lock`, ... — see names in `hotkey.py`) |
| `english_hotkey` | `f9` | hold for English instead; `""` disables. Avoid `right alt` (releasing Alt alone pops the menu bar and steals focus before the paste) and `right shift` (holding 8 s triggers Windows FilterKeys) |
| `translate_hotkey` | `f9` | **tap** to turn the selection — or the whole field — into English; `""` disables. Must differ from the two hold keys |
| `latch_hotkey` | `left` | **tap while holding** the hotkey to lock the recording on, so a long dictation isn't a long hold; tap again to finish. Swallowed only while it does this. `""` disables. Avoid `right shift` — Ctrl+Shift switches keyboard layout |
| `backend` | `local` | `gemini` \| `local` \| `fake` |
| `paste_chord` | `ctrl+v` | try `shift+insert` for unusual terminals |
| `restore_delay_ms` | `300` | wait after pasting before restoring the old clipboard (too small ⇒ the app pastes the *old* clipboard) |
| `min_seconds` | `0.3` | shorter holds = accidental taps, discarded |
| `max_seconds` | `400` | runaway-recording cap **while held**: stop, discard, error beep |
| `latch_max_seconds` | `0` | the cap once locked; `0` = none. `max_seconds` guards against a swallowed key-up, and a locked recording has no key-up to lose |
| `[audio] sample_rate` | `16000` | falls back to the device default if refused |
| `[audio] device` | `""` | `""` = system default; index from `--list-devices` |
| `fallback_to_local` | `true` | use the local model when every cloud model is out of quota |
| `[feedback] enabled` | `true` | paste a marker at the cursor while transcribing |
| `[feedback] placeholder` | `...` | the marker; replaced by your text (erased by backspaces, so keep it short) |
| `[feedback] retry_seconds` | `45` | how long to keep retrying before leaving the audio in `pending\` |
| `[gemini] models` | 4 flash models | tried in order; per-model daily quota makes a list a longer runway (`model = "..."` still accepted) |
| `[gemini] timeout_s` | `30` | API request timeout |
| `[local] model` | `ivrit-ai/whisper-large-v3-turbo-ct2` | ~1.6 GB, downloaded on first use |
| `[local] language` | `he` | **must stay pinned** — the fine-tune broke autodetect |
| `[local] device` | `auto` | `auto` \| `cuda` \| `cpu` |
| `[local] cleanup` | `true` | strip hesitations and collapse restarted phrases |
| `[local] extra_fillers` | `[]` | words to also strip, e.g. `["כאילו"]` — only add words you never mean literally |
| `[local] initial_prompt` | Hebrew + tech terms | biases the decoder for code-switching; empty disables |
| `[local] english_model` | `deepdml/faster-whisper-large-v3-turbo-ct2` | general model used to detect language and transcribe English; `""` disables both |
| `[local] english_threshold` | `0.8` | confidence needed to treat an utterance as English |
| `[translate] target` | `English` | language the tap key translates into |
| `[translate] max_chars` | `5000` | refuse above this — a Ctrl+A that caught a whole document, not a message |
| `[translate] ollama_model` | `llama3.1:8b` | the fallback; must be pulled in Ollama |
| `[translate] ollama_url` | `http://localhost:11434` | where Ollama listens |
| `[translate] timeout_s` | `30` | Gemini request timeout |
| `[translate] ollama_timeout_s` | `150` | much larger on purpose: 76 s cold vs 2.5 s warm while the model loads into VRAM |
| `[translate] settle_ms` | `120` | how long the focused app gets to answer a copy |

## Design notes

Raw Win32 via ctypes (`WH_KEYBOARD_LL` hook + `SendInput`) — the
`keyboard` library was dropped mid-build after its event delivery proved
unverifiable here, and the raw hook exposes `LLKHF_INJECTED`, which gives
the clean rule: the hotkey works injected or physical, but only *physical*
other-key presses abort a recording, so the app's own synthetic Ctrl+V can
never kill one. Unit tests: `.venv\Scripts\python.exe tests.py`.
