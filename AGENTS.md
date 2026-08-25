# AGENTS.md — read me before touching anything

A briefing for any AI coder (or human) landing in this folder cold: what
this app is, what the owner wants, what the machine is, and where the
bodies are buried. The README holds the full story; this holds the parts
you must not learn by breaking them.

## What this is

Hebrew push-to-talk dictation for Windows: hold **Right Ctrl**, speak,
release, and a cleaned transcript lands at your cursor via clipboard +
Ctrl+V. Around that core: a repair pass that fixes misheard words, a
translate key, a punctuate key, a lookup key, a correction box that teaches
a vocabulary, a phone endpoint, and a dashboard. Everything is documented,
with measurements, in `README.md` and `config.toml`.

**Two whole versions of the app live here as git branches**, switched with
`Versions.vbs` / `dashboard.py`'s Version screen / `versions.py`:

- `classic` — frozen behavior (local Whisper + local gemma3:12b repair).
- `fast` — current development: repair pass goes to **Groq's free API**
  first (`openai/gpt-oss-120b`, reasoning_effort=low, ~0.3–0.6 s), falling
  back to the identical local path.

Switching carries `config.toml` across untouched because BOTH branches
commit byte-identical settings. **Invariant: never commit a config.toml
that differs between branches.** Tooling files (`versions.py`,
`Versions.vbs`, `dashboard.py`, `ui.py`, `singleton.py`, test fixes) exist
identically on BOTH branches on purpose — additive changes to those get
mirrored to `classic`, or switching would delete the tools needed to come
back.

## House rules — what the owner actually wants

1. **All-free, forever.** No paid APIs, no credit card, no trials. Free
   tiers only if genuinely generous (Groq: yes, no card, ~1,000
   requests/day). Cerebras looked free in docs and wasn't — verified live
   (HTTP 402 on every model) before being demoted. Verify money claims on
   the wire before recommending them.
2. **Audio never leaves the machine.** The one cloud leg sends
   transcript *text* to Groq; the owner accepted that trade knowingly. ASR
   stays local even though cloud Whisper is marginally faster — Hebrew
   quality of the ivrit.ai fine-tune beats generic models, and privacy wins
   ties.
3. **Never rewrite the user's words — enforce it in code, not prompts.**
   The repair pass's `_is_safe()` diffs every reply word-level and throws
   away rewrites (>±15% growth). Punctuation is letter-for-letter checked.
   Any new feature that touches user text gets the same treatment: a
   prompt asking nicely is not a guarantee.
4. **Measure, don't assume — and write the measurement down.** This repo's
   comments are full of numbers ("76 s cold vs 2.5 s warm", "WER 17.9% ->
   13.9%"). Decisions without measurements got reverted. Use
   `main.py --benchmark`, `recent\` recordings, `transcripts.log`, and
   leave your own numbers behind.
5. **~1 s from key release to text** is the target. The pipeline:
   local Whisper (~0.4 s) -> vocabulary swap (instant) -> Groq repair
   (<0.6 s) -> paste. Latency work must not regress rules 2–4.
6. **`config.toml` comments are load-bearing.** Most lines carry
   measurements. Edit it programmatically ONLY through
   `config.set_values()` (line-wise editor that preserves comments); a
   TOML round-trip would delete hours of work.

## The machine

- Windows 11, Python 3.11 venv at `.venv\` (stdlib-first: cloud APIs go
  through plain `urllib`; avoid new pip dependencies).
- GPU: 16 GB VRAM. Budgeted: two Whisper models (~6 GB) + gemma3:12b
  resident in Ollama (~8.5 GB). Adding model residency means evicting
  something — check `nvidia-smi`.
- Mic: Arctis 7 headset, device index `"1"`, 16 kHz mono WAV everywhere.
- Ollama at `http://127.0.0.1:11434` — **127.0.0.1, never localhost**
  (localhost resolves ::1 first and costs ~2 s of refused connection).
- Keys live in `.env` (gitignored): `GEMINI_API_KEY` (translate/punctuate/
  dictation fallback pool, 20 req/day/model), `GROQ_API_KEY`
  (repair pass, ~1,000 req/day), `CEREBRAS_API_KEY` (present but dead —
  their free tier ended; kept as `[polish] prefer = "cerebras"`).
- The app runs windowless under `pythonw.exe`, single instance enforced by
  a named mutex (`singleton.py`); status in `app.log`, everything ever
  dictated in `transcripts.log`. Both logs are plaintext and private.

## Traps we already paid for — do not re-arm them

- **Tests:** `.venv\Scripts\python.exe tests.py` — plain asserts, 323 of
  them, safe to run while dictation is live (two bugs that used to kill
  the app mid-suite are fixed; see git log). Run them BEFORE claiming done.
- **Subprocesses under pythonw allocate consoles.** Every `subprocess.run`
  needs `creationflags=CREATE_NO_WINDOW` (0x08000000) or each git/python
  spawn freezes the UI thread for hundreds of ms. This froze the dashboard
  once already.
- **Tk has no bidi.** UI chrome stays English; Hebrew transcripts render
  through `ui.draw_text` (DrawTextW + DT_RTLREADING), never plain Labels.
  Pure-Hebrew strings LOOK fine in Labels and mixed strings silently
  scramble — don't "fix" the working path.
- **Groq's model is a reasoning model.** `gpt-oss-120b` spends hidden
  tokens before answering: without `reasoning_effort=low` plus a
  max_tokens floor (256), the answer arrives EMPTY. Handled inside
  `translate.py::GroqTranslator`; don't pass tighter caps around it.
- **Model catalogs drift.** `llama-3.3-70b-versatile` vanished from Groq;
  Cerebras' free tier vanished entirely. Before trusting a model id or a
  pricing page, list `/v1/models` and make one real call.
- **A disabled Tk widget repaints itself in SYSTEM colours.** `bg` is
  only the NORMAL state: disable an Entry and Tk falls back to
  `disabledbackground`, which defaults to the platform grey, so a dark
  field went white the instant a question was in flight. Found in a live
  screenshot, not in a test — nothing asserts colour. Set
  `disabledbackground` / `disabledforeground` / `readonlybackground`
  whenever you set `bg` on something that can be disabled, and prefer not
  disabling it at all (`visual_qa.py`'s entry stays live so that typing
  over an answer supersedes it the way speaking over one does).
- **DWM does not round a borderless window.**
  `DWMWA_WINDOW_CORNER_PREFERENCE` rounds the NON-CLIENT area, and an
  `overrideredirect` window has none. `SetWindowRgn` +
  `CreateRoundRectRgn` is the one that works — popup.py already keeps it
  as its pre-Windows-11 fallback — and the region has to be re-cut after
  every resize, so it lives at the end of `_fit_window`.
- **WinRT TTS from PowerShell has two teeth.** (1)
  `SynthesizeTextToStreamAsync` returns `IAsyncOperation<SpeechSynthesisStream>`
  — awaiting it as `<IRandomAccessStream>` (the folk recipe) dies with
  "System.__ComObject cannot be converted"; AsTask must be made generic
  over `SpeechSynthesisStream`. (2) Build WinRT objects with type
  literals (`[Windows.Media...SpeechSynthesizer]::new()`), never
  `New-Object` — only the literal path projects instance members
  (measured: `AllVoices` full through the static accessor, empty through
  a New-Object'd instance). Both in `visual_qa.py::_TTS_PS`, paid for in
  six probes on 2026-08-25.
- **The lookup box's frame must never wait on its text.** `popup.py`
  resizes the window in the same message the mouse arrives in and reflows
  the answer on a 50 ms throttle behind it. Laying out inline first was
  measured as stick-stick-jump on any long answer. Related: `_trim` keeps
  whole wrapped lines instead of binary-searching word cuts — the old way
  cost 699 ms per auto-fit descent on a 4056-char answer, against 22 ms
  now. Don't "simplify" either back.
- **A Tk window must be COLLECTED by the thread that built it, not just
  destroyed there.** `destroy()` does not delete the interpreter; the
  interpreter dies when the last reference to it does. A Tk widget tree is
  always cyclic, so that never happens by refcount — the generational
  collector does it, on whichever thread happens to trip the allocation
  threshold. That thread runs `Tcl_DeleteInterp`, and Tcl panics if it is
  not the creating thread: an abort, exception `0x80000003` in
  `tcl86t.dll`, no Python traceback and nothing in `app.log`. The app
  vanished twice this way on 2026-08-25, both times on the first long
  dictation after using the ask card — a 73 s and a 127 s clip allocating
  on the transcription worker. So a `gc.collect()` next to `destroy()`
  proves nothing: it can only work once every reference is gone, which is
  strictly later than the window's own `run()` can arrange. See
  `visual_qa.py::Controller._flow`. The card tests could never have caught
  it because they all end in `os._exit(0)`, which skips collection —
  `test_a_closed_card_leaves_no_interpreter_for_another_thread_to_free`
  deliberately does not.
- **Hebrew in console output** shows as garbage unless
  `$env:PYTHONIOENCODING='utf-8'` — display-only, data is fine.
- **Branch switches restart the running instance** (~25 s of model
  loading). That is expected, not a crash.

## Where things live

| file | job |
|---|---|
| `main.py` | app wiring: hotkeys, worker, paste, phone endpoint |
| `config.py` / `config.toml` | settings, validation, comment-preserving writes |
| `recorder.py` | mic stream, WAV frames |
| `hotkey.py` | global hook, state machine, chords |
| `transcribers/` | whisper/gemini/fake backends |
| `polish.py` + `translate.py` | repair pass + all chat backends (Gemini/Ollama/Cerebras/Groq) |
| `cleanup.py` / `vocab.py` | filler removal, learned words |
| `injector.py` | clipboard paste, placeholder, focus checks |
| `punctuate.py` / `lookup.py` | F2 rewrite-in-place / reading box |
| `visual_qa.py` | ask-the-screen: region select, vision chain, answer window, TTS |
| `dashboard.py` + `ui.py` | control window incl. the Version screen |
| `versions.py` | whole-app version switching |
| `tests.py` | the suite; run it |
