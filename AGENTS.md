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
a vocabulary, a background study pass that re-examines sent dictations and learns without being asked (fast only, study.py), a second reading that re-reads every pasted dictation and proposes corrections on a card — learning only what is approved (fast only, review.py, review_card.py, overlay.ReviewCard, the dashboard's Review screen; it stands in for the study pass while on), a screenshot/screen-recording pair of keys, a webcam key
that takes a photo into the same editor, a phone endpoint, and a
dashboard. Everything is documented,
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
   TOML round-trip would delete hours of work. Since 2026-09-01 they are
   also USER-FACING: the dashboard's Settings screen is generated from
   the file (`settings.py`), each key's comment is the help under its
   row, and a `gemini | local | fake` at the front of a comment is read
   as that key's menu. Write a new key's comment as a sentence someone
   will read on screen, keep the menu form for enumerations, and never
   add a settings row by hand — the file is the list.

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

- **Tests:** `.venv\Scripts\python.exe tests_quiet.py` runs the suite on a
  hidden Windows desktop so none of its windows flash over the owner's
  work (asked for 2026-09-02; same tests.py, same exit code, output
  printed at the end). `.venv\Scripts\python.exe tests.py` is the
  same suite in the open — plain asserts, **449 test
  functions** carrying 1,691 of them as of 2026-08-28, safe to run while
  dictation is live (two bugs that used to kill the app mid-suite are
  fixed; see git log). Run them BEFORE claiming done. (This line read "367"
  for a long time and had drifted badly; if you change the suite, either
  re-count with `Select-String -Path tests.py -Pattern "^def test_"` or say
  "hundreds" and stop maintaining a number nobody re-derives.)
- **The decoder WAS not deterministic, and every single-run measurement in
  this repo predates knowing that.** `hallucination_guards()` tightens
  three thresholds well past stock, and every window they reject goes down
  faster-whisper's temperature fallback ladder (0.2 … 1.0), which SAMPLES.
  Measured 2026-08-28: one 25.2 s clip produced **5 distinct transcripts in
  5 runs** at fixed settings, scoring 4, 9, 16, 33 and 3 word edits against
  64 true words — 6.3% to 51.6% WER from one file. That is the mechanism
  behind "words I said are missing": a sampled window wins the fallback and
  its words are gone, silently, with nothing logged. Fixed by pinning
  `temperature=[0.0]` in `hallucination_guards()`, which also removed 58.7%
  of decode time (144.7 s → 59.8 s over the 50 clips in `recent\`, RTF
  0.058 → 0.024) because a forced window costs up to 6 decodes instead of
  1. Two consequences for anyone measuring here: **an A/B taken once is a
  draw from a distribution, not a result** — the same beam-5 sweep over the
  same 6 clips scored 10.16%, 42.97% and 14.84% WER on three passes — and
  the ladder is Whisper's standard escape from a repetition loop, so if you
  ever unpin it, `repetition_penalty`, `collapse_char_runs` and the loop
  warning are what is left. The GPU number above was taken while six agents
  shared the card; re-time it on a quiet machine before quoting it.
- **A percentage guard cannot see a truncation.** `polish._is_safe` bounds
  drift at ±15% *symmetrically* — that part is fine and was verified — but
  15% of a long dictation is enormous: it silently accepted a 13-word cut
  on a 90-word transcript, 35 on 234 and 52 on 352. Groq's replies hit
  `max_tokens` on ~12% of calls (gpt-oss spends 70–402 hidden reasoning
  tokens out of the same budget, non-deterministically), nobody read
  `finish_reason`, and two truncated replies were pasted on 2026-08-27 —
  one cut mid-word. Fixed in two places: `translate.py` raises on
  `finish_reason == "length"`, and `polish._tail_loss` rejects any reply
  that is a strict word-prefix of the transcript, whatever its percentage.
  A repair swaps words in the MIDDLE; only a cut answer reproduces the
  transcript and then stops. Verified over the 50 stored `raw`/`text` pairs
  in `recent\`: 49 legitimate repairs still pass, 1 rejected, and it is the
  known truncation.
- **`raw` and `text` in `recent\*.json` are a free before/after of the
  whole text pipeline, and they settle stage arguments outright.** `raw` is
  the decoder's output, `text` is what was pasted. Example: the polite
  words that appear at the end of sentences unbidden ("בבקשה", "טוב") are
  present in `raw` in 2 of 79 pairs and were ADDED by the repair pass in
  **0 of 79** — so that bug is the fine-tune's, not Groq's, and no amount
  of prompt work on `polish.py` will touch it. Check this pair before
  blaming a stage. (`corpus\*.json` does NOT carry `raw` — only
  `{kept, seconds, text, tier}` — so it contributes 0 pairs to such a
  census, and `tier = "gold"` there means the owner corrected it by hand.)
- **Do not fix the invented polite tail with a word list.** It is tempting
  and it is wrong: of 18 dictations ending in a polite word, roughly 10 are
  real speech — he really does end sentences with "בבקשה". The existing
  `PARLIAMENTARY_BOILERPLATE` comment already refuses single common words
  for this reason and should stay refusing them. Any fix has to gate on
  evidence the decoder already produces (`word_timestamps` is on: a silence
  gap before the token, or an outlying `avg_logprob`), not on the word.
- **A human correction went into the decoder prompt with no family
  gate, and the prompt is where the decoder gets its ideas.** The study
  pass always kept pure-Hebrew machine pairs out of the hotword list
  (`glossary_only`); the correction key did not, so nine one-hit Hebrew
  phrases ("יש לי ריפו", "גיטאהאב", "הרצץ מיליון", "באן יאללה דרוס"...)
  accumulated at the tail of the prompt. Measured 2026-09-02: a 2.8 s
  clip of five words ("תעצור זהו כבר יש קובץ") came out as 29, the
  extra 24 stamped into its last 140 ms at zero duration and p
  0.04-0.58; the same clip decoded cleanly with the Latin terms alone,
  and with the list as it stood before the last two Hebrew pairs were
  learned. Nothing downstream could catch it: temperature is pinned, so
  faster-whisper logs "log probability threshold is not met" at DEBUG
  and keeps the window; `hallucination_silence_threshold` needs a
  silence gap and the tail was glued to the last real word; the
  parliamentary filter knows fixed phrases; polish and the study
  adjudicator are forbidden to drop words. Fixed in `vocab._ranked`
  (`[vocab] hebrew_after_hits`, default 3) and turned into the second
  reading's structural drop (`review.tail_drop`). When words the user
  never said appear, ABLATE THE HOTWORDS FIRST — decode the `recent\`
  wav with `hotwords=None` and with `word_timestamps` — before blaming
  the model or the thresholds.
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
- **...and `gc.collect() == 0` does not prove you buried it. A module
  global is not garbage.** The trap above came back on 2026-08-31 through
  the other door: `skin\wave.py` cached the ring sprites in a module-level
  dict and, to know which interpreter they belonged to, kept
  `_owner = canvas.tk` — which is not a handle to the interpreter, it *is*
  the interpreter. So the ask card's Tcl interpreter stayed reachable
  after the card, its thread, and `_flow`'s collect were all gone, and was
  freed later by whoever dropped the last reference: the NEXT card's pump
  thread, or the main thread at exit. Same panic, same silence —
  "Tcl_AsyncDelete: async handler deleted by the wrong thread", exit 3
  (0x80000003), no traceback, nothing in `app.log`.
  The rings are painted only while the microphone is live, so it fired
  only when the owner SPOKE into the card — which is why the crash looked
  like "dictation and ask-the-screen cannot be used together". Measured:
  one card dictated into aborts at exit, two in a row abort mid-run; both
  clean once the cache hangs off the card.
  **So: nothing module-level may hold a Tk object — not a PhotoImage, not
  a widget, and least of all a `tkapp`.** A cache belongs to the window it
  draws, the way `visual_qa._Slabs` already does it. And the assertion
  that catches this is not `gc.collect() == 0` (a global sails past it) but
  "no global holds a Tk object" — see
  `test_no_global_keeps_a_card_interpreter_alive_past_its_thread`.
- **`ImageTk.PhotoImage(img)` with no `master=` does not bind to the
  window you are drawing on — it binds to `tkinter._default_root`, which
  is somebody else's.** `_default_root` is process-wide and is whatever Tk
  was built first and not yet destroyed: after the splash goes, that is
  the STATUS DOT, alive on its own thread for the whole run. So a
  master-less image built on the ask card's thread is created in the
  status dot's interpreter, from the wrong thread, and Tk answers with
  `RuntimeError: main thread is not in main loop`. `skin\wave.py` swallowed
  it in the `except Exception` that keeps decoration from being fatal, so
  there was no crash and no message — the mic wave simply never appeared,
  for months, in the only place it exists. Measured 2026-08-31 with a
  long-lived overlay root standing: every `paint_wave` call declined;
  every one drew once the image took `master=canvas`.
  Every `ImageTk.PhotoImage` in `visual_qa.py` already passes `master=`.
  Keep it that way, and note that a swallowed exception is exactly how a
  feature that never runs looks identical to one that does.
- **A tk.Frame is an opaque rectangle, forever.** No arrangement of them
  will ever look like glass, and `-alpha` is not the answer either: it is
  WHOLE-window, so it makes the text translucent too, which is where
  Hebrew stops being crisp (popup.py measured that trade years ago). The
  ask card gets its glass by PAINTING one PIL image — blur, tint,
  specular rim — and showing it as a single PhotoImage. That only works
  because the screen is frozen and we own the pixels behind the window;
  the dashboard and the lookup popup cannot use this technique.
- **Three ways to round a borderless window, and only one is right here.**
  Measured on this machine, 2026-08-25: `-transparentcolor` is a 1-BIT
  key, so every antialiased corner pixel that is merely NEAR the chroma
  stays opaque and rings the card in a dark fringe (and keyed pixels are
  click-through). `UpdateLayeredWindow` gives true per-pixel alpha and
  ERASES TK — the Entry's pixels were overwritten and never came back, so
  no caret, no live widgets. What ships is the third: paste the glass onto
  a copy of the CRISP backdrop through an antialiased rounded mask, so
  outside the radius the pixels are the desktop's own, bit for bit. No
  transparency of any kind is involved.
- **ImageDraw's `fill` REPLACES pixels, it does not blend them.** Drawing
  a half-transparent rounded rectangle straight onto the glass punches a
  hole in it. Every soft shape in `visual_qa.py` is built as its own RGBA
  layer and composited (`rr_layer`). The bug looks like a solid white
  pill where a translucent one was wanted.
- **Never ImageGrab the screen back to capture your own ink.** It races
  the topmost window and returns black. The pencil keeps its stroke
  POINTS in Python and replays them into the pristine crop with Pillow;
  the canvas line is only there for the live feel.
- **Full-screen effects on the 4480x1440 virtual screen cost real time.**
  Painting the whole scene was 734 ms before every local effect moved
  onto a CROP around the rectangle it touches, and the specular gradient
  and grain moved out of Python loops (`Image.effect_noise`, and a 64x64
  gradient stretched with BILINEAR). 172 ms now. Pillow's Gaussian blur
  is a 3-pass box approximation, so a big radius costs the same as a
  small one — take the pretty one.
- **The card is three layers, and only the middle one moves.** The
  crisp desktop, the glass, the content. A drag changes the position and
  nothing else, so the content layer is cached on a signature of the
  STATE and the glass is built from a copy of the frozen screen that was
  blurred once. Before that split a drag cost 63 ms a frame (16 fps) and
  almost all of it was re-blurring pixels that had not changed. It is
  16 ms now. Do not move work back into the per-frame path -- and do not
  repaint from the motion handler either: Windows delivers motion faster
  than the card composes, so painting per event queues frames the pointer
  has already left behind. Mark it dirty; the pump paints the latest.
- **winsound.PlaySound without SND_ASYNC blocks its thread, and the API
  is process-global.** So SND_PURGE cannot take effect until the blocking
  call returns, and whoever pressed Stop waited out the whole sentence.
  In the ask card that presser was the pump thread, so the window could
  not repaint or close either -- reported as "it crashes and I cannot get
  out". Play ASYNC and wait out the wav's own duration in short
  cancellable hops instead. 10.59 s from Stop to quiet became 0.00.
- **Declaring argtypes on `ctypes.windll.*` changes them FOR EVERY
  MODULE.** `ctypes.windll.user32` is a process-global cached object and
  five files here reach for the same one. capture.py needs
  `GetDC.restype = c_void_p` (a 64-bit HDC does not fit in the c_int
  ctypes assumes), and setting it there broke `visual_qa.text_pil` on a
  line that had worked for months — "OverflowError: int too long to
  convert", because that module still expected the truncated int. The fix
  is a PRIVATE handle: `ctypes.WinDLL("user32")` builds a new wrapper with
  its own function cache. capture.py uses `_user32`/`_gdi32` and a test
  greps it to keep it that way. Anything new that declares argtypes must
  do the same.
- **`SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` really does
  hide a window from BitBlt** — with and without CAPTUREBLT, and from
  PIL's ImageGrab too. Measured 2026-08-25: a magenta window that filled
  60000/60000 pixels of a grab filled 0 with the flag set. That is what
  lets the recording controls sit on top of the region being recorded
  instead of beside it, which is the only option when the region is the
  whole screen.
- **PIL's `ImageGrab` builds its DCs per call; a reused DIB section does
  not.** 10.1 ms vs 53.7 ms for 1280x720, 21.7 vs 56.7 at 1440p, measured
  2026-08-25. Screen RECORDING is only possible on the second number. Do
  not "simplify" capture.Grabber back to ImageGrab.
- **h264 refuses an odd-sided frame, and it refuses it late.** yuv420p
  subsamples chroma 2x2, so libx264 raises at `add_stream` — which is
  after the user has picked a region and thinks they are recording.
  `capture.even_box` shrinks by a pixel before anything is opened.
- **A video encoder is already installed.** PyAV comes with faster-whisper
  and carries its own FFmpeg (libx264 and h264_nvenc both present). No new
  package and no ffmpeg.exe. NVENC was measured and rejected: same speed
  warm, 234 ms spike on its first frame, and the GPU budget is already
  spent (see The machine).
- **A webcam has no "default device" URL.** FFmpeg's dshow demuxer is
  opened as `video=<friendly name>`, so anything that opens a camera has
  to enumerate first — `capture.cameras()`, 147 ms, once per window. And
  the enumeration is not a query: you open the demuxer with
  `list_devices=true`, it prints the list and REFUSES to open, and the
  refusal is the success case.
- **Read PyAV's log through Python logging, and expect fragments.** Three
  things, all measured 2026-08-26 while building `_dshow_report`.
  (1) `av.logging.restore_default_callback()` sends ffmpeg's lines to the
  C runtime's stderr, and a windowless app has nowhere for stderr to go —
  redirecting fd 2 around the call captured zero lines, twice. The default
  callback, which posts to `logging.getLogger("libav.*")`, is the only
  route that works under pythonw. (2) That logger inherits root's WARNING
  unless you `setLevel(DEBUG)` on it, and ffmpeg's lines are INFO — forget
  it and the device list comes back empty with no error anywhere. (3) What
  arrives are FRAGMENTS: one device is four records (the quoted name,
  `(video`, `)`, the newline), and off the main thread the newline is
  dropped as well. Join them and read with a regex; do not split on lines
  that are not dependably there.
- **Ask a webcam for MJPEG or you get a slideshow.** Measured off this
  camera's own `list_options`: 1920x1080 at 30 fps as mjpeg and *the same
  size at 5 fps* as raw yuyv422 — and DirectShow hands over the raw pin
  unless `vcodec=mjpeg` is in the options. The fallback drops the request
  rather than fail (a 5 fps camera is still a camera) and logs that it did.
- **`text_pil` returns a picture of the BOX it was given, not of the
  glyphs.** Centring that box puts a short string against one edge —
  a "3" clipped by the left curve of a 34 px chip, and a countdown numeral
  visibly off-centre in its disc. Crop to `getbbox()` first. Both bugs
  shipped into the first live screenshot, which is the only place they
  could have been seen.
- **`PhotoImage.paste()` exists, and the camera preview needs it.**
  Building a new `ImageTk.PhotoImage` per frame allocates a 1280x720
  bitmap twenty-five times a second and hands the old one to the garbage
  collector — on a thread that owns a Tcl interpreter, which is the
  Tcl_AsyncDelete story above wearing a different hat. One PhotoImage for
  the window's life, pasted into.
- **Do not hide the camera window from capture.** The clip bar uses
  `WDA_EXCLUDEFROMCAPTURE` because its controls float over the region
  being recorded. The camera card floats over nothing it is recording, and
  the flag has a cost that only shows up later: an excluded window cannot
  be screenshotted, shared or recorded BY THE OWNER either — not by this
  app's own `ctrl+f11`, not by Teams, not for a bug report. It withdraws
  and pumps three ticks before grabbing the desktop instead, which costs
  one repaint at the moment the screen is about to be dimmed anyway.
- **Tk takes the foreground the moment it REALISES a window, and
  `WS_EX_NOACTIVATE` does not stop it.** Measured step by step,
  2026-08-26: with the window `withdraw()`n, `overrideredirect`, topmost
  and already carrying the no-activate flag, the foreground was Chrome
  before `update_idletasks()` and `TkTopLevel` immediately after it.
  Showing it with `SetWindowPos(SWP_NOACTIVATE|SWP_SHOWWINDOW)` instead of
  `deiconify()` did not help either — the grab has already happened by
  then. The flag still earns its place (a later CLICK on the window no
  longer activates it); the first grab has to be UNDONE, with
  `SetForegroundWindow` back to whatever had it, which is allowed because
  at that instant this process owns the foreground. Repainting afterwards
  does not take it again (measured over eight repaints). Anything here
  that is a NOTIFICATION rather than a window the user just asked for owes
  this: see `capture.give_focus_back`.
- **A Windows-key chord IS takeable, and the code used to say it was not.**
  `parse_binding` refused Win as a modifier on the reasoning that "a tap of
  it that nothing consumed opens Start". That reasoning is about Win
  ALONE; it does not survive contact with a chord. Measured 2026-08-26,
  three runs of a bare low-level hook: `Win+Shift+S` with the hook merely
  watching brings up `XamlWindow / "Snipping Tool Overlay"`; with the hook
  returning 1 for the `s` key-down while Win is held, NOTHING opens; and a
  bare tap of Win with that same hook installed still opens Start
  (`Windows.UI.Core.CoreWindow / "Search"`). So no registry key, no
  `DisabledHotkeys`, nothing turned off in Windows — swallow the trigger
  and leave Win itself alone. A Win chord is now the ONE exception to "tap
  keys are not swallowed" (`hotkey._takes_the_key`), and the exception is
  narrow on purpose: a Ctrl/Shift/Alt chord is not usually the shell's.
- **Three-and four-key chords always worked; nothing needed adding.**
  `Binding.mods` is a frozenset and the dashboard builds a chord from
  `held_modifier_groups()`, which asks Windows what is down at the moment
  the trigger lands. `ctrl+shift+alt+f6` has parsed since chords existed.
  What was missing was only the Win group in `_SIDES`/`_MOD_ORDER` — and a
  test saying the capability is there, because a capability with no test
  is one that gets optimised away.
- **Pillow antialiases NOTHING, and the editor's ink is on a picture
  people look at closely.** `ImageDraw.line`/`.polygon` write hard pixels:
  every diagonal was a staircase and it was plainly visible at 1x. Marks
  are drawn at 4x on their OWN rectangle and resized down with LANCZOS
  (`_ink_stamp`, the same trick `icon()` and `rr_layer` use), backing off
  to 2x or 1x when the rectangle approaches a screenful — 4x a 2560x1440
  bbox is 59 MB. And it is cached per mark, keyed on the points: a
  committed mark never changes, a crop only moves where it is pasted, and
  without the cache every hover repaint would re-oversample every stroke.
  0.8 ms to repaint five marks against 41 ms to render them.
- **An arrow's shaft must stop at the notch, not at the point.** Drawn to
  the tip, a 3 px stroke pokes out the far side of the head — the little
  nub in the first screenshot of this editor. And the head wants four
  points (tip, two barbs, a notch pulled back along the shaft), not three:
  a plain triangle on a thin shaft reads as a wedge. `arrow_shape` is the
  geometry and `tk_arrowshape` translates it for the live canvas preview,
  so the arrow you drag is the arrow you get.
- **A key that means two things needs a latch, because a poll is not an
  event.** The camera card reads Esc with `GetAsyncKeyState` at 66 Hz (a
  borderless topmost window does not get the keyboard for free — the same
  reason the selector does), and Esc there cancels a countdown first and
  closes the window second. A human tap holds the key for eighty
  milliseconds, so without remembering that it was already down, one press
  did both: measured 2026-08-26 on a scripted 60 ms tap, which cancelled
  the timer and closed the window every time. Latch on the down edge and
  release on the up.
- **The lens is released by the shutter, not by the editor.** `_fire`
  calls `Camera.close()` before the flash and before the file is written,
  and `Controller.stop()` closes it too. A test asserts the ordering,
  because nothing else can see it and the light beside the camera is the
  only thing the owner has to go on.
- **Hebrew in console output** shows as garbage unless
  `$env:PYTHONIOENCODING='utf-8'` — display-only, data is fine.
- **Mirror to `classic` with a git WORKTREE, never by checking it out.** The shared files
  (config.toml, main.py, dashboard.py, cues.py, .gitignore) have to land on both branches in the
  same change or `test_both_versions_commit_the_same_settings_file` and
  `test_the_shared_half_of_the_app_is_one_file_on_both_versions` go red — and both compare
  COMMITTED blobs, so leaving the work uncommitted is also green. Checking `classic` out swaps the
  working tree under the app the owner is using. A worktree does not:
  `git worktree add <tmp> classic`, copy the shared files in, commit there, run that branch's own
  `tests.py` from the worktree, `git worktree remove <tmp>`. Done on 2026-08-26 with the app live
  and never touched. Note `.gitignore` is in that set even though no test checks it: `versions.py`
  refuses a switch when `git status --porcelain` is dirty, and untracked files count — a
  `captures\` folder ignored on one branch only would block the switch.
- **The look lives in `skin/` and is meant to be deletable.** Every hook
  into it is `try: import skin / except: skin = None` in FRONT of code
  that was not otherwise touched, and `ui.py` still carries the ORIGINAL
  hex literals under the repaint hook — so `rmdir /s skin` really is the
  revert, and two tests assert it. Do not "tidy" those literals to match
  the new palette; that would quietly make the revert stop reverting.
  `SKIN.md` has the rest.
- **Tk antialiases NOTHING, and that is measurable.** A 400x400 grab of
  canvas primitives came back with exactly two distinct colours. So a
  chroma key is bit-exact clean for canvas items (there are no partial
  pixels to fringe) and completely unusable for anything Pillow drew. The
  first release animation was Tk canvas items and was rejected on sight as
  pixelated. What draws antialiased light over the live desktop is
  `UpdateLayeredWindow` + Skia — AGENTS rules ULW out for the ask card
  because it "erases Tk", which is not a cost for a window that is only a
  picture. See `skin/glass.py`.
- **skia-python's CPU rasteriser blends at 64 ns a pixel, and the GPU is
  3400x faster.** The CPU number is perfectly linear and unchanged by
  colour type, alpha type or colour space: a full-screen alpha rect at
  2560x1440 is 238 ms, `kSrc` is 1.34, a big radial gradient 160-240. On
  the GPU the same fill is 0.07 ms and a 60 px Gaussian blur is 0.09.
  `skin/gl.py` builds the OpenGL context by hand (skia-python ships
  `GrDirectContext.MakeGL` but no windowing: a hidden 8x8 window, a pixel
  format, `wglCreateContext`, ~270 ms once) and `skin/glass.py` reads the
  finished frame back into the layered window's DIB — 4.33 ms at 1440p,
  which is the whole price. A GL context is THREAD-AFFINE, so the contexts
  live in a threading.local and the status dot never gets one.
  Without a GPU everything still works and looks quieter: `skin/burst.py`
  is written to the CPU budget and `boot.py` picks between them on
  `glass.on_gpu`. Do not draw a large soft fill on the CPU path.
- **The same reveal renders DIFFERENTLY on the two paths.** `skin/reveal.py`
  measured 2.4% of one frame pure white on the GPU and 38% on the CPU
  rasteriser. It is never drawn there, and its tests skip when there is no
  context rather than testing a path the app never takes.
- **A runtime shader needs its WHOLE uniform block, in declared order.**
  Supplying 8 bytes for a `float2 + float` gives every uniform zero,
  silently — no error, no warning, just a black frame.
- **A reveal is rejected for its SHAPE, not its length.** Two attempts
  failed here. The first was 880 ms — "it appears for half a second, you
  can barely see it". The second kept the same shape and stretched it:
  420 ms of wind-up and 2400 ms of aftermath, and the verdict was the
  same. A card 24 degrees off screen centre costs a gaze about 300 ms just
  to ARRIVE at, so a wind-up shorter than that is one nobody sees begin,
  and 880 ms sits entirely inside one attentional-blink window. What works
  is build 45-55%, payoff 5-12%, decay 35-45%, total inside the 2-3 s
  "subjective present" so it is remembered as one gesture. The current
  moment is 2580 ms at 52/5/43, and `test_the_moment_is_mostly_wind_up`
  holds it there. Two details carry more than their weight: the impact
  CUTS to a composition that is already formed rather than growing one
  from a point, and the 110 ms hitstop after it is what lets the eye catch
  up.
- **The four Rubik files in `fonts\` are ONE variable font.** All four
  report weight 300 and identical advance widths — asking for
  `RubikMedium.ttf` and expecting Medium silently gets Light. Pin the
  `wght` axis with `makeClone` (`skin/boot.py::_rubik`).
- **Branch switches restart the running instance** (~25 s of model
  loading). That is expected, not a crash.
- **The feature keys work DURING a dictation, and that is load-bearing.**
  Until 2026-08-30 they did not: `PTTStateMachine` fired taps only in
  `IDLE`, aborted the recording on any other key mid-HOLD, and ignored
  everything while LATCHED. The owner's report was that Ctrl+F10 "had
  simply vanished — there is no such button, because the app is locked
  onto the audio." Five rules replaced that, and none of them is
  cosmetic:
  - a key this app has BOUND is never a stray keystroke, so it fires
    instead of aborting; only an unbound key still kills a hold, and
    Ctrl+C still does (on the C);
  - a modifier alone DEFERS rather than aborting — every chord starts
    with one, so aborting on the way down made `ctrl+f10` and
    `win+shift+s` unpressable by construction;
  - the key HOLDING a recording open is not a chord modifier
    (`_match_tap(exclude=)`). Without this, `win+shift+s` reads as
    ctrl+win+shift+s and never matches; with it, bare F8 cannot quietly
    become `ctrl+f8`;
  - screen keys (ask-the-screen, screenshot, screen recording, camera)
    fire in every state; the four that touch TEXT AT THE CURSOR are
    refused while the hotkey is HELD and allowed while LATCHED, because
    latching is what frees the hands (`App._tap_allowed`);
  - Escape belongs to whatever is on screen, and the recording is last in
    line for it (`App._esc_is_claimed` -> `cancel_guard`).
- **WHERE a dictation goes is decided when it STARTS, not when it
  transcribes.** `_handle` used to re-read `vqa.sink_active` at the far
  end. Once the ask card can be opened mid-sentence, that reading is of a
  different moment than the one the user was in: a paragraph dictated
  into Chrome was swallowed by a card opened 55 seconds later, and the
  `...` marker left behind could not even be cleared, because the card
  had the foreground. The decision rides the queue item. Same for the
  paste target — the window at the key RELEASE is preferred, unless it is
  one of ours (`injector.is_our_window`), and then the window at the
  press is the only honest answer.
- **`injector._board_lock` is the process-wide clipboard queue, and a
  retry loop is not a substitute for it.** `OpenClipboard` does NOT
  serialise two threads of the same process — the second gets a success
  it cannot honour — so `_open_clipboard`'s retry never fires and the
  next call raises Windows 1418. `App._cursor_lock` never covered this:
  capture.py writes from `capture-shot`, the lookup box from
  `lookup-copy`, and neither has heard of it. Measured 2026-08-30 with
  `copy_image` firing 4 ms into each paste: **the clipboard held the
  screenshot rather than the transcript at read time in 39 of 40 pastes
  without the lock, 0 of 40 with it.** Anything new that touches the
  clipboard goes through `injector`, or takes `injector.board_held()`.
  Two rules fell out of it and both are load-bearing. `set_text` takes the
  board BEFORE bumping the claim counter — claim-then-write is only safe
  while the two are microseconds apart, and a queued write leaves the
  claim visible with nothing behind it, at which point `read_selection`
  concludes the user copied something mid-capture and throws away the
  answer to its own chord. And **no UI thread may take the board**: the
  longest holder is a lookup that found nothing selected, at 2.1 s, so
  popup.py's already-threaded copy button has been joined by the ask
  card's, the capture editor's, the toast's, and the dashboard's
  `copy_last`. Separately, `injector.inject` now saves and restores ALL
  formats when the clipboard holds something it cannot describe as text —
  otherwise the transcript pastes over the screenshot just taken, which is
  the headline gesture undoing itself.
- **Our own windows must not appear in the user's screenshots.**
  `capture.hide_from_capture` (WDA_EXCLUDEFROMCAPTURE) is the flag;
  `overlay.StatusDot` now applies it too, because the screenshot key can
  be pressed while the dot is pulsing red. Re-measured on the dot's own
  window: 3600/3600 magenta pixels before, 0/3600 after.

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
| `study.py` | the second learning channel: when idle, re-decodes sent recordings, votes + adjudicates, learns from divergence (fast only) |
| `injector.py` | clipboard paste, placeholder, focus checks |
| `punctuate.py` / `lookup.py` | F2 rewrite-in-place / reading box |
| `visual_qa.py` | ask-the-screen: region select, vision chain, answer window, TTS |
| `capture.py` | screenshots (select, edit, clipboard, save), screen recording (BitBlt + PyAV), and the webcam photo key (dshow through the same PyAV, into the same editor) |
| `dashboard.py` + `ui.py` | control window incl. the Version screen and the generated Settings screen |
| `settings.py` | config.toml as data: every key, its comment as help, `a \| b \| c` as choices — what the Settings screen draws |
| `skin/` | the whole look — delete the folder to revert it (`SKIN.md`) |
| `versions.py` | whole-app version switching |
| `tests.py` | the suite; run it |
