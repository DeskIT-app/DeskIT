# Ask-the-Screen (Visual Q&A) — implementation prompt

You are implementing a new feature in the DeskIT repo on the
`fast` branch. This document is the complete brief. **Read `AGENTS.md`
first and obey every house rule in it**, then read the module docstrings
of `overlay.py`, `popup.py`, `lookup.py`, `polish.py`, `hotkey.py`, and
the comment blocks of `config.toml` — the architecture you are about to
extend is documented there, with measurements, and the patterns you need
already exist. Do not invent parallel infrastructure.

## The feature, in one paragraph

The owner presses a hotkey, drags a rectangle over any part of the
screen, then asks a question about it with their voice (or keyboard).
The app screenshots the rectangle, transcribes the spoken question with
the local Whisper it already runs, sends image + question to a vision
model, and shows the answer in Hebrew in a small window — with a button
(or config toggle) that also SPEAKS the answer aloud in Hebrew. Think
"lookup key, but for pixels instead of selected text."

## Verified facts — measured live on this machine, 2026-08-25

These were checked on the wire today. Do not re-derive them from docs,
and do not replace them with catalog knowledge from your training data —
when in doubt, re-measure on the machine, never assume.

1. **Nothing needs to be installed. Zero new pip packages, zero system
   installs.** Everything required is already present and verified:
   - `Pillow` 12.3.0 in the venv (`PIL.ImageGrab` for screenshots,
     drawing, downscaling). `sounddevice` + `numpy` present for audio.
   - `gemma3:12b` in Ollama reports `capabilities: ['completion',
     'vision']` — the repair model the app already keeps resident IS a
     vision model. No new model pull, no new VRAM residency.
   - **Microsoft Asaf (he-IL)** is installed as a OneCore/WinRT voice.
     Caution: the legacy SAPI `System.Speech` API does NOT see it (it
     lists only Zira en-US); the WinRT
     `Windows.Media.SpeechSynthesis.SpeechSynthesizer` API DOES list
     "Microsoft Asaf | he-IL". Use WinRT via a PowerShell subprocess,
     not System.Speech, not pyttsx3 (no new deps anyway).
2. **Local vision latency (gemma3:12b via Ollama, 127.0.0.1):** a real
   900×450 screen grab (443 KB PNG) + Hebrew question:
   - cold (vision projector not yet exercised): **40.9 s**, once
   - warm: **2.5 s**, answer was accurate, fluent Hebrew (it correctly
     read a math exercise off the live screen)
   - `ImageGrab.grab(bbox=...)` itself: **0.04 s**
   - GPU after everything loaded: **14,710 / 16,311 MiB** — it fits
     alongside both Whisper models. Nothing was evicted.
3. **Groq's vision model today is `qwen/qwen3.6-27b`** — the llama-4
   scout/maverick vision models are GONE from the catalog (drift, as
   AGENTS.md warns). Verified with a real image call:
   - answered a Hebrew question about an image in **0.51 s**
   - it is a reasoning model, but its knob differs from gpt-oss:
     `reasoning_effort` accepts ONLY `"none"` or `"default"` — sending
     `"low"` is an HTTP 400. Use `"none"`.
   - the chat endpoint sits behind Cloudflare and returns **403 (error
     code 1010) unless a User-Agent header is set** — same trap
     translate.py already documents for Cerebras; reuse that header.
   - **TPM cap is 8,000 tokens/min** on this model tier. One modest
     image ate ~6,500 tokens: real screenshots are 1–2 requests/minute
     before 429. This alone disqualifies Groq as the primary.
   - Hebrew quality is shakier than gemma3's (it hallucinated "three
     similar images" on a single image).
4. **Gemini works as an image fallback on the existing key:**
   `gemini-2.5-flash-lite` answered an image question in Hebrew in
   **2.3 s**. But the free pool is 20 req/day/model shared with
   translate/punctuate — `lookup.py`'s docstring documents why a
   frequently-pressed key must not drain it. Same logic applies here.
5. **Free hotkey:** every `ctrl+F` chord the repo's 2026-08 probe
   pressed (f1, f2, f3, f5, f6, f10–f16) reached the page untouched in
   Chrome and Edge. `ctrl+f10` is measured-free and unbound. Default to
   it; register it through the existing `hotkey.py` machinery so the
   dashboard's capture dialog can rebind it like the other keys.

## Locked decisions — do not re-litigate

- **Local-first, cloud opt-in.** Default backend chain is Ollama
  gemma3:12b ONLY. A screenshot is strictly more sensitive than
  transcript text (it can contain mail, banking, anything), so cloud
  vision sits behind an explicit config gate, default **false**, named
  so nobody can misread it: `allow_screenshot_upload`. When the gate is
  false and Ollama is down, the answer window says exactly that — it
  does not "helpfully" fall through to the cloud. When true, the chain
  is ollama → groq → gemini-pool, built the way `polish.py::Polisher`
  builds its backend chain (study `_builders`/`_backends`; that module
  is your architectural template, including `warm()`).
- **The screenshot never touches disk.** It lives as bytes in memory,
  goes out base64-encoded, and is never logged, never cached, never
  written to scratchpad. No answer cache either — the screen changes
  between presses (unlike `lookup_cache.json`, where caching pays).
  The question TEXT is a dictation like any other and goes to
  `transcripts.log` per the app's normal logging; the answer goes to
  `app.log` at debug level with backend + latency numbers.
- **No new dependencies.** stdlib `urllib` for both cloud calls
  (per house style), PIL for pixels, PowerShell WinRT for TTS,
  `winsound`/stdlib for playback. If you believe you need a pip
  package, you have designed it wrong — stop and reread this file.
- **Questions skip the repair pass.** Raw Whisper + vocabulary swap is
  enough: a vision model is robust to a misheard word, and skipping
  Groq repair keeps the question path free, fast, and quota-neutral.
- **Answers are generated text, not the user's words** — `_is_safe()`
  word-diff does NOT apply here. What does apply: a hard `num_predict`
  cap (~400 tokens) so a rambling model cannot hang the window.
- **Hebrew goes through `ui.draw_text`.** The answer window renders
  Hebrew/mixed text via the DrawTextW path like every other window
  here. No Tk Labels for Hebrew, no exceptions — AGENTS.md explains
  why the broken path looks fine until it doesn't.
- **TTS default is a button, not auto.** Config `speak = "off" |
  "button" | "auto"`, default `"button"`: the answer window shows a
  speak control; `"auto"` reads every answer aloud. Synthesis =
  PowerShell subprocess (WinRT SpeechSynthesizer, voice Asaf) writing a
  WAV to a temp file that is deleted after playback, played with
  stdlib `winsound` (async flag so the UI never blocks; a second press
  or Esc stops playback). EVERY subprocess gets
  `creationflags=CREATE_NO_WINDOW` — the repo already froze once
  without it.

## UX flow to build

1. `ctrl+f10` (config key `visual_qa_hotkey`, dashboard-rebindable,
   `enabled = false` unregisters it entirely — that's the kill switch).
2. Full-screen selection overlay: dimmed topmost window, crosshair
   cursor, drag a rectangle (any drag direction — normalize the bbox),
   live rectangle outline while dragging. Esc or click-without-drag
   cancels with nothing shown. Multi-monitor: use the virtual-screen
   bbox (`ImageGrab.grab(bbox=..., all_screens=True)` coordinates) if a
   second monitor is attached; verify coordinates match by comparing a
   captured corner against the on-screen selector during development.
   Also verify DPI scaling: Tk's coordinates and `ImageGrab`'s pixels
   must agree on this machine (Windows 11 — check the process DPI
   awareness the app already sets; if the thumbnail you capture is
   offset or scaled from what was selected, fix awareness FIRST, do not
   fudge coordinates with a correction factor).
   **Threading:** this overlay is interactive, unlike Splash/StatusDot,
   but it still lives under the same Tk constraints documented in
   `overlay.py` — never let two mainloops coexist, never call
   `quit()` (the module docstring documents the module-global
   `quitMainLoop` coin-toss bug that was measured here). Follow the
   existing pattern for how `popup.py` windows run and die.
3. On mouse-up: grab the bbox (in memory), close the selector, open a
   small "ask" window near the selection showing a thumbnail of what
   was captured (this doubles as the user's confirmation of WHAT will
   be asked about) plus a text entry.
4. Question input, two ways, both must work:
   - **Voice:** while the ask window is open, holding Right Ctrl runs
     the normal record→Whisper path but the transcript is routed into
     the ask window's entry INSTEAD of being pasted at the cursor.
     Nothing may leak a paste into the underlying app while the window
     is open. Study how `main.py` routes dictations and how the
     correction box swallows its key before wiring this.
   - **Typed:** just type in the entry. Enter sends either way.
5. Send → the entry disables, a small busy indicator runs, the backend
   chain answers → answer replaces the indicator, rendered RTL, with
   Copy and Speak controls. Keep the window: a follow-up question in
   the same window reuses the SAME screenshot plus prior Q/A as chat
   history (cheap on the local model). Esc closes; closing stops TTS.
6. First-use latency: if `enabled = true`, piggyback a warm-up of the
   vision path onto the app's existing model warm-up (`polish.py::warm`
   precedent): one tiny dummy-image call with `num_predict = 1` in the
   background after startup, so the first real question costs ~2.5 s,
   not ~41 s. Config `warmup = true` to allow opting out.
7. Downscaling: cap the long side before sending (config key with its
   measured reasoning in a comment): ~1344 px for gemma3 is a sane
   start; for Groq downscale harder (~896 px, JPEG) because of the
   8k TPM budget. MEASURE full-screen-sized grabs on this machine and
   write the numbers into the config comments like every other knob.

## Config — and the branch invariant you must not break

New `[visual_qa]` section in `config.toml`: `enabled`,
`visual_qa_hotkey`, `prefer`, `ollama_model` (default gemma3:12b),
`allow_screenshot_upload`, `groq_model = "qwen/qwen3.6-27b"`,
`gemini` fallback toggle, `max_side_px`, `num_predict`, `speak`,
`voice = "Microsoft Asaf"`, `warmup`, timeouts. Every key gets a
comment carrying its measurement or reason, in the file's voice.

**Invariant from AGENTS.md: `config.toml` is committed byte-identical
on BOTH branches.** The precedent already exists — `[polish] prefer` is
a fast-only key that classic parses and ignores. So: finish the section
on `fast`, mirror the *identical* file to `classic` in a commit there,
and PROVE classic still boots with it (switch via the `versions.py`
tooling, run classic's tests, switch back). If you touch any of the
both-branches tooling files (`ui.py`, `dashboard.py`, `versions.py`,
`singleton.py`, test fixes), those changes get mirrored to classic
too — additively. Feature code itself (`visual_qa.py`, wiring in
`main.py`, hotkey registration) stays fast-only.

Config edits from code go through `config.set_values()` only — a TOML
round-trip deletes the file's comments, which are load-bearing.

## New module

One new file, `visual_qa.py`, owning: region selection, capture,
downscale, backend chain, ask/answer window, TTS. Keep hooks in
existing files minimal: hotkey registration, startup warm-up call,
dashboard hotkey row (if the dashboard lists rebindable keys, add this
one the same way). Match the repo's documentation culture: a module
docstring that explains the decisions and carries today's numbers, in
the same voice as `lookup.py`'s.

## Tests and proof — the definition of "done"

- Add plain asserts to `tests.py` in the house style, covering at
  least: bbox normalization from all four drag directions; downscale
  math (aspect preserved, no upscaling small grabs); config defaults
  and parsing of the new section; backend selection honoring
  `allow_screenshot_upload = false` (a screenshot must be UNSENDABLE to
  cloud builders when false — assert the chain contains no cloud
  backend, don't trust a runtime `if`); the Groq request builder (has
  User-Agent, `reasoning_effort = "none"`, image attached, model id);
  TTS voice handling and the off/button/auto switch; and that the
  screenshot pipeline is bytes-in/bytes-out with no file path anywhere
  in its signatures.
- `.venv\Scripts\python.exe tests_quiet.py --no-screen` — the full suite
  (287 existing + yours, at the time this was written) passes. Run it
  BEFORE claiming done, per AGENTS.md — and run it that way, hidden:
  house rule 8 says every test run happens on a hidden desktop, and
  `--no-screen` skips the sixteen in `tests_quiet.NEEDS_SCREEN` that
  need the real display or the real mouse. The ask card's own tests are
  among those sixteen, so the plain `tests_quiet.py` — the one that runs
  them in the open — is what finally proves this feature, and it waits
  until he is away from the desk.
- `main.py --benchmark` before and after your changes: the dictation
  pipeline numbers must not regress — this feature must be inert when
  its window is closed.
- Live proof, not "should work": with the app running, press the
  hotkey, drag over a browser paragraph, ASK BY VOICE, and screenshot
  the Hebrew answer window. Record the measured end-to-end time
  (mouse-up → answer visible) in the module docstring and README. The
  target is ≤4 s warm on the local path.
- Verify no console windows flash during the whole flow (the TTS
  subprocess is where this will bite if you forget CREATE_NO_WINDOW).
- Update `README.md` (feature section in the file's voice) and
  `AGENTS.md` only if a new trap was discovered and paid for.

## Out of scope for v1 — do not build

Streaming token-by-token answers; OCR-only fast path; exposing this on
the phone endpoint (`server.py`); persistent conversation memory across
window closes; auto-detecting question language; any paid API, any
trial, anything needing a credit card — the all-free rule is absolute.

## If something here turns out wrong on the wire

Model catalogs drift (scout vanished between 2026-08 sessions; Cerebras'
free tier died). If `qwen/qwen3.6-27b` is gone or gemma3's vision
misbehaves, do what AGENTS.md rule 4 says: list the live catalog, make
one real call, write the measurement down, and pick accordingly —
a locally-verified fact beats anything printed above.
