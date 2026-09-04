# PARALLEL FEATURES — plan

Goal, in the owner's words: **while a dictation is running, the other feature
keys must still work.** Right now they do not. Hold Right Ctrl (or latch with
Right Ctrl -> Left arrow) and Ctrl+F10, Win+Shift+S, Ctrl+F6 and Ctrl+F12 are
simply not there — "כאילו הכפתור נעלם".

This file is the whole of what has to happen, so that nothing is dropped
halfway. Every claim below is either quoted from the code or marked TODO.

---

## 0. Why the keys vanish (root cause, verified)

`hotkey.py PTTStateMachine.handle()` has three states and taps live in one:

| state | what a feature key does today | where |
|---|---|---|
| `IDLE` | fires | hotkey.py, the `elif vk in self._taps` branch |
| `RECORDING` (hold) | **aborts the recording**, action never runs | the `elif event_type == "down" and not injected` branch |
| `LATCHED` | **silently ignored** | the "Anything else is ignored on purpose" branch |

So it is not a focus problem and not a Windows problem. Taps are gated on
`IDLE` by construction.

---

## 1. The rules this lands on

Stated so they can be argued with before any code moves.

**R1 — a bound key is never "any other key".**
Mid-hold, a key-down that MATCHES a registered tap fires that tap and does not
abort. Only an unbound key still aborts (Ctrl+C must keep aborting).

**R2 — a modifier alone no longer aborts a hold; it defers.**
`win+shift+s` and `ctrl+f10` cannot be pressed at all if Win / Shift / Ctrl
abort on the way down. So a modifier key-down mid-hold is remembered, not
punished. The abort moves to the first NON-modifier key-down that matches no
binding. Ctrl+C still aborts — one key later, same outcome.
*Contract change: `test_left_ctrl_is_not_the_hotkey` asserts the old immediate
abort and must be rewritten.*

**R3 — the key holding the recording open is a hotkey, not a modifier.**
While `RECORDING`, the active hold hotkey's own vk is excluded from the held
set when matching a chord. Consequences, all wanted:
- `ctrl+f10` is reached with the LEFT ctrl (the right one is busy). Works.
- `win+shift+s` matches `{win, shift}` instead of `{ctrl, win, shift}`, which
  the exact-match rule would have rejected. Works.
- a bare F10 while holding Right Ctrl does NOT become `ctrl+f10`, so `f8`
  (correct) cannot silently turn into `ctrl+f8` (lookup). Unchanged from today.
In `LATCHED` there is no active hotkey and no exclusion — `_mods_down` is
simply the truth.

**R4 — hands-free means everything; one hand means the screen keys.**
- `LATCHED` (hands free by design): **every** tap fires — visual_qa, capture,
  record, photo, translate, punctuate, correct, lookup.
- `RECORDING` (a hand is on the key, the utterance is short): the four SCREEN
  keys fire — visual_qa, capture, record, photo. The four that read or write
  TEXT AT THE CURSOR — translate, punctuate, correct, lookup — are refused
  with the existing "busy" cue and a log line, and, unlike today, **do not
  abort the recording**.
Rationale: with one hand pinned to Right Ctrl you cannot have made a selection,
so the text keys have nothing to act on; the screen keys need no hands at all.

**R5 — the destination of a dictation is decided when it STARTS.**
Today `main.py._handle` reads `self.vqa.sink_active` at TRANSCRIPTION time to
divert a transcript into the ask card. Once Ctrl+F10 can fire mid-dictation,
that would hijack a sentence aimed at the user's editor. The rule becomes:
if the card was up when you pressed the hotkey, this dictation is a question;
otherwise it is a paste, even if a card opens while you speak.

**R6 — the paste target is remembered at START too.**
`_on_stop` captures `injector.foreground_window()` at key-release. If one of
our own overlays is in front at that moment, the transcript is aimed at our own
window. Remember the foreground at start and prefer it when the window at stop
belongs to this process.

**R7 — Escape belongs to whatever is on screen; the recording is last in line.**
`cancel_vk` (Esc) discards a LATCHED recording. It is also how you cancel the
region selector, the capture overlay, the camera and the ask card. Esc must
reach those windows (they are focused, so it must NOT be swallowed) while
leaving the recording alone. `popup.py` already sets the precedent for the
lookup box, via `on_key_down` -> swallow. The overlays need the third answer:
claimed, not swallowed.

**R8 — a screenshot taken mid-dictation must not contain our own HUD.**
`overlay.StatusDot` is a topmost always-on dot that pulses red while recording.
`capture.hide_from_capture()` (WDA_EXCLUDEFROMCAPTURE, measured 2026-08-25)
exists and the dot does not use it. It would land in every screenshot the new
feature makes possible.

> **R8 WAS REVERSED ON 2026-09-04 — do not implement it as written.** The
> owner's ask: the screenshot key should freeze the screen and photograph it
> *as it is*, without anything disappearing. The flag is absolute, so it hid
> our windows from HIS grabs too and the notification card could not be
> photographed at all. The dot, the hint card, the review card and both paths
> of the notification card no longer set it. What keeps them out of the way is
> the ORDER in `capture.Controller._shot_flow` — freeze, then hush, then map
> the selector — not invisibility. The clip bar keeps the flag, because a
> recording has no single instant to freeze. See AGENTS.md, "our own windows
> and the owner's screenshots".

**R9 — the activity state is a scalar and must not be stomped.**
`main.py._set_state` writes one string, read by the dot, the dashboard and the
study engine's `_learning_quiet`. A parallel feature ending must not write
"ready" over a live "recording"/"locked".

---

## 2. The work, file by file

### hotkey.py
1. Factor the IDLE tap branch into a `_try_tap(vk, was_down)` helper returning
   `(fire, swallow)`, so auto-repeat arming (`_tap_held`), chord matching and
   the Win-chord swallow (`_takes_the_key` / `_swallow_tap_up`) are identical
   in all three states. Keep byte-identical behaviour for IDLE.
2. `_match_tap` gains an `exclude` argument (R3): the active hotkey's vk.
3. `RECORDING` branch order becomes: active hotkey -> latch -> **tap** ->
   modifier (defer, R2) -> abort.
4. `LATCHED` branch order becomes: finish -> cancel -> **tap** -> ignore.
5. New constructor callback `tap_allowed: Callable[[str, str], bool]`
   (action, state) -> may this fire now? Default: IDLE only, so every existing
   caller and every existing test keeps today's behaviour. main.py passes the
   real policy (R4). Keeps the state machine free of feature semantics.
6. New constructor callback `cancel_guard: Callable[[], bool]` (R7): asked only
   for Esc in LATCHED. True == somebody on screen owns Esc, leave the recording.
7. Docstring: the class docstring is load-bearing in this repo. Every rule
   above gets written into it in the house voice.

### main.py
8. `_on_tap` consults the policy and refuses text actions mid-recording with
   `_cue_once("noop", ...)` + a log line (R4).
9. `_on_start` records the destination ("card" if the VQA card is up, else
   "paste") and the foreground window at start (R5, R6).
10. `_on_stop` puts the decided destination and the better hwnd on `self.queue`.
    TODO: confirm the queue-item shape is not asserted in tests.py.
11. `_handle` uses the carried destination instead of re-reading `sink_active`.
12. `_set_state` refuses to leave a recording state while the machine is not
    IDLE (R9).
13. `_esc_is_claimed()` -> capture busy / vqa busy / popup visible, wired to
    `cancel_guard`. Must be cheap and non-blocking: it runs on the hook thread.
    Must not build the lazy controllers — read `getattr(self, "_vqa", None)`,
    never the property.
14. The lazy `self.vqa` / `self.capture` properties import a large module on the
    HOOK THREAD on first press. Already true; with more presses reaching them it
    gets more likely. TODO: decide whether to pre-warm.

### overlay.py
15. ~~`StatusDot._build_and_loop` applies WDA_EXCLUDEFROMCAPTURE (R8).~~
    **Undone 2026-09-04** — see the note under R8. The dot is meant to be
    photographable; it stands down for a selection instead.

### tests.py
16. Rewrite `test_left_ctrl_is_not_the_hotkey` for R2.
17. New tests, house style (a `Spy`, plain asserts, one behaviour each):
    - a chord tap fires mid-hold and does not abort
    - a chord tap fires while latched and does not stop the recording
    - an unbound key still aborts mid-hold
    - Ctrl+C still aborts mid-hold (via the deferred rule)
    - the active hotkey's vk is not a chord modifier (R3), incl. win+shift+s
    - a text action is refused mid-hold and the recording survives
    - Esc with a claimed overlay does not discard a latched recording
    - the destination is decided at start (a card opening mid-dictation does
      not hijack the transcript)
    - `_set_state` cannot leave "locked" while latched

### docs
18. README.md + AGENTS.md: one section on the new arbitration.
19. **config.toml is NOT touched.** No new settings are needed, and the repo
    invariant is that config.toml is byte-identical on `fast` and `classic`;
    editing it here would require mirroring to the other branch.

---

## 3. What the recon pass found that the plan above did not

Eight parallel readers over the real code. The findings that changed the work:

- **Q1 clipboard — the big one.** `App._cursor_lock`'s comment claims every
  clipboard borrower takes it. False: `capture.copy_image` / `copy_file` write
  from `capture-shot`, the lookup box from `lookup-copy`, and neither has ever
  heard of that lock. And a retry loop cannot stand in for one, because
  `OpenClipboard` does not serialise two threads of the same PROCESS — the
  second gets a success it cannot honour, and the next call raises Windows
  1418, which is not `ClipboardBusyError` and escapes every handler in main.py
  (losing the audio as well as the paste, because the spool save happens later).
  **Measured 2026-08-30: with `copy_image` firing 4 ms into each paste, the
  clipboard held the image rather than the transcript in 39 of 40 pastes.**
  Fixed with `injector._board_lock`, a process-wide reentrant clipboard queue
  that capture.py joins through `injector.board_held()` — 0 of 40 after.
- **Q2 focus.** Confirmed and worse than assumed: the ask card, the capture
  overlay, the camera and the clip bar all TAKE the foreground and none gives
  it back. A dictation ending over any of them was aimed at our own window and
  destroyed in silence — pasted nowhere, not even left on the clipboard,
  and logged as a success. `injector.is_our_window` + the start hwnd (R6).
- **Q3 esc.** The overlays read Escape with `GetAsyncKeyState` rather than
  receiving it, so the cancel_guard must NOT swallow — which is what it does.
- **Q4 mic.** No second InputStream. But the ask card's TTS and the cues share
  one `winsound` channel, and — the real hazard — the card would read an answer
  aloud into a live microphone, which on any non-headset output is transcribed
  as if the user had said it. `AskWindow.mic_live` refuses it.
- **Q5 sink.** `self.queue`'s shape is not asserted anywhere; `_handle` is
  called with three positional args in seven tests, so the new parameter is
  keyword-with-default.
- **Q6 state.** `_activity` is one string; the worker's closing
  `_set_state("ready")` lands on top of a live recording. Also
  `_learning_quiet` is blind to capture/vqa, so the study pass could take the
  GPU underneath a screen recording. Both fixed.
- **Q7 cues.** Fire-and-forget, non-blocking on the hook thread.

Also found and fixed: `test_a_capture_press_is_refused_while_one_is_already_up`
did `del type(app).capture` in its finally, which removed `App`'s real property
for the whole rest of the suite. Nothing had needed it since.

## 4. What is deliberately NOT fixed here

All pre-existing, all found by the recon, none of them made worse by this
change — listed so they are not mistaken for oversights:

- No overlay restores the window it displaced (only `ShotToast` does), so the
  "press ctrl+v to paste it" fallback can point at the wrong app.
- `show_placeholder`'s return value is discarded, so a marker that landed
  somewhere unexpected is backspaced out of the wrong window.
- A cue and the card's TTS cut each other off — one `winsound` channel.
- `sink_active` goes True only after `AskWindow.__init__` returns, so the
  card's own construction is a window in which it is not yet the sink.

## 5. Done means

`.venv\Scripts\python.exe tests.py` green (468 functions), and the four screen
keys demonstrably answer while a recording is latched.
