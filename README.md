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
- **Startup takes ~25 s** (two Whisper models onto the GPU) and a small
  window appears bottom-right while it happens, naming each step as it
  goes. Without it, clicking the shortcut is indistinguishable from
  clicking a shortcut that does nothing — so you click again. It does not
  take focus and does not appear in Alt-Tab; it vanishes once the hotkey is
  live. Turn it off with `splash = false`.
- **A small dot sits in the top-right corner while the app runs** — blue
  when idle, red while recording, red and breathing while a recording is
  *locked on*, amber while transcribing. It is how you tell a running app
  from one you never started or already closed. It is click-through, so it
  never intercepts the close button it sits on. Turn it off with
  `indicator = false`.
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
- **It gets a word wrong? Tap `F8`, fix it, and it stops getting it
  wrong.** See [Teaching it the words it gets
  wrong](#teaching-it-the-words-it-gets-wrong-tap-f8).
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

## Dictating from the phone

The phone records; **this machine transcribes**. That is the whole point —
a phone keyboard's Hebrew dictation is not the ivrit-ai fine-tune, and the
GPU here is already holding the model. The endpoint runs inside the running
app and borrows that loaded model, so it costs no extra VRAM.

Reachability is **Tailscale's** job. No port forwarding, no public IP, no
dynamic DNS. The socket binds to the Tailscale address when it is up, so
the endpoint exists only on your private mesh and never answers the home
LAN. A bearer token is required on top of that.

### Setting it up

1. Install Tailscale on this PC and on the phone, signed into the same
   account. Confirm with `tailscale ip -4`.
2. In `config.toml`, set `[server] enabled = true`, then restart the app.
3. **Give it HTTPS.** Chrome blocks the microphone *and* the clipboard on
   pages that are not a secure context, so plain `http://100.x.y.z:8756`
   will load and then refuse to record:

   ```bash
   tailscale serve --bg 8756
   ```

   That fronts it with a real certificate at
   `https://<machine>.<tailnet>.ts.net/`.
4. The log prints the URL **including the token** (`.../#t=...`). Open that
   once on the phone; the token moves into localStorage and the address bar
   is cleaned, so the page can be bookmarked or added to the home screen.

Hold the button, talk, release. The text appears and is copied to the
clipboard automatically.

**Everything you teach it with `F8` on the desktop applies here too**, and
there is nothing on the phone that implements it: the phone only records,
this machine transcribes, and it does so with the same model and the same
[learned vocabulary](#teaching-it-the-words-it-gets-wrong-tap-f8). Correct
"xpogo" once at the desk and the phone stops producing it from the next
dictation. The repair pass runs on this path as well, so the two cannot
give different answers for the same audio.

Three things that cost real time the first time round:

- **`tailscale serve` does not fail when Serve is off for your tailnet — it
  BLOCKS.** It prints "Serve is not enabled… To enable, visit <url>" and
  then waits for you to click it. That reads exactly like a fatal error, so
  the temptation is to run it again; don't. A second copy racing the first
  fails with `netMap is nil` and can leave `No serve config` behind. Run it
  once, in the background, and click the link.
- **The tray app has to be running.** `tailscaled` (the service) alone is
  not enough: without `tailscale-ipn.exe` the backend sits in
  `BackendState: NoState`, `tailscale ip -4` reports nothing, and the
  MagicDNS name stops resolving — while the service still shows as Running,
  which makes it look like a network problem. Launch Tailscale from the
  Start menu.
- **The first HTTPS request takes ~30 s** while Tailscale provisions the
  Let's Encrypt certificate, and it usually times out rather than waiting.
  Measured here: 26.7 s for the first request, 0.65 s for the next. The token lives in `server_token.txt`
(gitignored); delete it to roll a new one.

If the PC is asleep the page simply cannot reach it — set Windows to never
sleep if you want this available while you are out.

## Words you never said

Whisper does not only transcribe — when the decoder reaches the end of real
speech it can keep going, producing fluent text drawn from its training
data. This fine-tune was trained on **Knesset protocols**, so what it
invents is parliamentary. Observed live on 2026-08-12: a dictation about
adding cities to an app ended with `אדוני היושב-ראש, חברי הכנסת`.

Two defences, both on by default, neither of which changes a good
transcription (measured: byte-identical output, ~8% slower):

- **Tightened decoder guards** (`[local] guard_hallucinations`) — Whisper's
  own confidence thresholds, plus `hallucination_silence_threshold`. The
  library defaults are permissive enough to let a low-confidence trailing
  segment through.
- **A tail-only boilerplate filter** (`[local] drop_trailing_boilerplate`) —
  drops parliamentary phrases stuck to the **end** of a transcript. Never
  the middle: there, you almost certainly really said them. When it fires
  it logs `dropped hallucinated tail` with exactly what it removed, so you
  can check it in `app.log`.

The filter only holds whole phrases that are unmistakably parliamentary.
Single common words are deliberately excluded — deleting real speech is a
worse bug than the one being fixed. Add your own with `extra_boilerplate`.

What this does **not** touch: `[local] cleanup` (hesitations, restarted
phrases) and `initial_prompt` (which is what keeps English technical terms
in Latin script and is worth 10.8% → 9.6% WER). Those are the parts that
make the output *better*, and they stay.

Note that silence alone does not cause this — that was tested and ruled
out. VAD strips silence and key clicks and the result is empty. It takes
real speech in front of it for the decoder to run on.

## Teaching it the words it gets wrong (tap F8)

Whisper does not mishear randomly. It mishears the words it was never
trained on — your project names, your tools, your jargon. Measured from
this machine's own `transcripts.log`, the failures split into two families
that need opposite handling:

| what you said | what it wrote | family |
|---|---|---|
| Expo Go | `xpogo` | never heard the name |
| `--branch production` | `Brinth Production` | never heard the name |
| Cowork | `בקו-ורק` | never heard the name |
| HebrewDictation | `Hebrew reduction` | never heard the name |
| מקלדת | `מקללת` | real word, wrong word |
| סריקה | `סירקה` | real word, wrong word |

**Fix the wrong words where they landed** — in Chrome, in Claude Code,
wherever the transcript was pasted, which you were going to do anyway —
then **tap `F8`**. It reads the corrected text off the screen, diffs it
against what it produced, and learns the difference. If the field holds a
lot of other text, select just the corrected sentence first.

There is deliberately **no edit box**. The first version put the transcript
in a Tk window to be fixed there, and Tk 8.6 has no bidi support at all:
mixed Hebrew and English rendered visually scrambled and the caret jumped
around as it was typed into. You are already fixing the text in an app with
real bidi — reading it beats asking for it again in a worse editor.

What happens to a correction:

- **The corrected form becomes a hotword**, handed to the decoder *before*
  it runs, so it stops producing the garble at all. This is the half that
  matters; everything else is a safety net.
- **After `replace_after_hits` corrections of the same garble (default 2)**
  it is also repaired after the fact, for the times it slips through
  anyway. Two, not one, because this pass rewrites your own words and one
  correction could be a slip of the finger in the box.
- **The recording is kept** (last 50, in `recent\`) with your correction
  attached, which turns "it got this wrong" into a test case — see
  `--benchmark` below.

`python main.py --vocab` prints everything learned and the exact hotword
list being fed to the decoder.

Two things it refuses to do, both of which would poison the vocabulary:

- **Learn from a field that no longer holds the transcript.** If less than
  half the last dictation is still recognisable in what was grabbed, you
  have moved on and it says so rather than diffing unrelated text.
- **Learn insertions or rewrites.** Only substitutions of up to four words
  are kept. A word the model *missed* has no misheard form to key on, and
  editing the sentence into a different sentence is you rewriting, not
  correcting.

One known limit: a mis-hearing that is both the **last word** of the
dictation *and* expands into more words (`xpogo` → `Expo Go`) has no
matching word after it to anchor its end, so it is learned truncated
(`xpogo` → `Expo`). Mid-sentence — the ordinary case, since these are
paragraphs — it is exact. Widening the search would pull in your next
sentence, which is a much worse thing to learn.

### Why this is not just a longer `initial_prompt`

Because `initial_prompt` stops working after 30 seconds, which is exactly
where the long dictations that garble worst live.

`local_whisper.py` sets `condition_on_previous_text=False`. Under that
setting faster-whisper drops the initial prompt after the first decoder
window: it goes into `all_tokens`, and the end of each segment loop does
`prompt_reset_since = len(all_tokens)`. `hotwords` is re-injected per
window inside `get_prompt()` and never touches that path. Measured
2026-08-14 by spying on `WhisperModel.get_prompt` over 125 s of real
speech:

```
initial_prompt='MARKERWORD'   present in 1/5 decoder windows
hotwords='MARKERWORD'         present in 6/6 decoder windows
```

Both are used — they coexist, and the prompt becomes
`" HOTWORDS INITIAL_PROMPT"`. The initial prompt is what sets the
Hebrew-with-English register and is worth 10.8% → 9.6% WER on short clips;
hotwords are what carry the vocabulary past the 30-second mark.

**Budget:** faster-whisper truncates the hotword string at
`max_length // 2 - 1` = **223 tokens**, mid-token if it has to. Hebrew
costs several tokens a word, so `max_terms` (40) keeps the list well under
it. Over-prompting Whisper makes it emit the prompted words unbidden — a
longer list is not a better list.

### The other family: `[polish]`

`מקללת` is a real Hebrew word. No lookup table can safely rewrite it,
because you might have meant it — only the sentence around it says
otherwise. So a language model reads the sentence and fixes the word.

It is allowed to read context. It is **not** allowed to write. The
instruction not to invent is in the prompt *and enforced in code*: every
reply is diffed against the transcript and thrown away if the model did
more than swap words — more than 15% change in word count, or fewer than
75% of the words surviving. A rejected reply is not retried and not
reported as an error; the raw transcript goes through untouched, exactly as
if the pass were off. Failing closed is the only acceptable failure mode
for something sitting between your speech and your cursor.

Ollama goes first here, the reverse of [translating](#translating-to-english-tap-f9),
because this runs on dictations rather than on a key you tap — Gemini's 20
requests/day/model would be gone before lunch and would take translation
down with it. Default `when = "known"`: the pass only runs when the
transcript contains something you have corrected before, so an idle Ollama
is only ever woken (76 s cold) when there is real evidence a repair is due.

**It never holds up your paste.** `max_wait_s` (6 s) is the longest the
pass may delay the transcript reaching your cursor; past it the raw text is
pasted and the reply is discarded whenever it turns up. `warm_up` sends one
throwaway request at startup so the ~5 GB is already in VRAM. Both exist
because of a measured failure on 2026-08-14: a cold Ollama took **53.7 s**,
the transcript sat unpasted the whole time, it looked like a failure, it
got re-dictated — and then both landed 1.5 s apart.

> **The one thing this pass will get wrong, and it cannot be guarded
> against.** Once you have taught it `להטמע` → `להטמיע`, it applies that
> everywhere — including in a sentence where you said the wrong form *on
> purpose*. Observed live: a dictation of "הוא רשם להטמע בלי יוד" ("it wrote
> להטמע without a yud") came out as "הוא רשם להטמיע בלי יוד", which says
> nothing. `_is_safe` cannot catch it, because a one-word swap is exactly
> what this pass is for.
>
> **Hotwords have no such failure mode** — they bias the decoder *before*
> it writes and never rewrite what you said. If you want the learning
> without any risk of being edited, set `when = "never"` and
> `replace_after_hits` high; the vocabulary still works, it just stops
> correcting after the fact.

### Proving it actually helps

```bash
.venv\Scripts\python.exe main.py --benchmark
```

Replays every recording you have corrected, with the vocabulary on and off,
and reports the word error rate of each. This exists because "it feels
better since I added those words" is not evidence, and a vocabulary is
easy to believe in and hard to notice failing. If the numbers get worse it
says so, and tells you the likely cause (a seeded term you rarely say, or
too many of them).

Known limits, so the numbers are read correctly:

- These are the recordings you chose to correct, so they are the hard ones
  by construction — not a sample of normal dictation.
- The benefit is **unmeasured on real Hebrew speech** as of 2026-08-14. The
  mechanism is proven (the window test above) and the cost is nil (A/B on
  clean synthetic English: 8/8 terms both ways, no latency penalty), but
  clean TTS gets the terms right without any help, so it cannot show the
  gain. Your own corrected recordings are the only honest test set, which
  is why the app now keeps them.

**Privacy:** `recent\` is raw audio of what you dictated, on this disk, and
`vocab.json` pairs words you said with what you meant. Both are gitignored
and `recent\` is capped at `keep_audio` (50), oldest dropped first. Set
`keep_audio = 0` to keep none — everything else still works, you just lose
the ability to measure rather than assume. The seed terms in `config.toml`
*are* committed: those are hand-written, not learned.

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
| `correct_hotkey` | `f8` | fix the transcript where it landed, then **tap** this; it reads the correction off the screen and learns the difference. `""` disables. See [Teaching it the words it gets wrong](#teaching-it-the-words-it-gets-wrong-tap-f8) |
| `[vocab] enabled` | `true` | feed the learned vocabulary to the decoder as hotwords |
| `[vocab] terms` | your stack | hand-written seeds, ranked ahead of anything learned |
| `[vocab] max_terms` | `40` | cap on the hotword list; faster-whisper truncates at 223 tokens and over-prompting makes Whisper emit the words unbidden |
| `[vocab] replace_after_hits` | `2` | corrections of the same garble before it is also repaired after the fact. `1` would let one slip in the box start rewriting a word you really say |
| `[vocab] keep_audio` | `50` | recordings kept in `recent\` so `--benchmark` can replay them. `0` = keep none |
| `[polish] when` | `known` | `never` \| `known` (only when a learned garble is present) \| `always` |
| `[polish] min_chars` | `20` | below this there is no context to reason from |
| `[polish] ollama_model` | `""` | `""` = reuse `translate.ollama_model` |
| `[polish] max_wait_s` | `6` | longest the pass may delay your paste; past it the raw transcript is pasted and the reply discarded |
| `[polish] warm_up` | `true` | one throwaway request at startup so the model is in VRAM before a dictation needs it |
| `backend` | `local` | `gemini` \| `local` \| `fake` |
| `paste_chord` | `ctrl+v` | try `shift+insert` for unusual terminals |
| `restore_delay_ms` | `300` | wait after pasting before restoring the old clipboard (too small ⇒ the app pastes the *old* clipboard) |
| `min_seconds` | `0.3` | shorter holds = accidental taps, discarded |
| `max_seconds` | `400` | runaway-recording cap **while held**: stop, discard, error beep |
| `latch_max_seconds` | `0` | the cap once locked; `0` = none. `max_seconds` guards against a swallowed key-up, and a locked recording has no key-up to lose |
| `[audio] sample_rate` | `16000` | falls back to the device default if refused |
| `[audio] device` | `""` | `""` = system default; index from `--list-devices` |
| `indicator` | `true` | the top-right status dot; click-through and never in Alt-Tab |
| `splash` | `true` | show a small window while the models load; it does not take focus and leaves no taskbar entry |
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
| `[local] guard_hallucinations` | `true` | tighten Whisper's confidence thresholds and enable `hallucination_silence_threshold`; measured free on good audio |
| `[local] drop_trailing_boilerplate` | `true` | drop Knesset boilerplate stuck to the **end** of a transcript (never the middle) |
| `[local] extra_boilerplate` | `[]` | your own phrases to drop the same way. Whole phrases only — a single common word deletes real speech |
| `[translate] target` | `English` | language the tap key translates into |
| `[translate] max_chars` | `5000` | refuse above this — a Ctrl+A that caught a whole document, not a message |
| `[translate] ollama_model` | `llama3.1:8b` | the fallback; must be pulled in Ollama |
| `[translate] ollama_url` | `http://localhost:11434` | where Ollama listens |
| `[translate] timeout_s` | `30` | Gemini request timeout |
| `[translate] ollama_timeout_s` | `150` | much larger on purpose: 76 s cold vs 2.5 s warm while the model loads into VRAM |
| `[translate] settle_ms` | `120` | how long the focused app gets to answer a copy |
| `[server] enabled` | `false` | the phone endpoint (see [Dictating from the phone](#dictating-from-the-phone)) |
| `[server] host` | `""` | `""` = the Tailscale address when up, else `127.0.0.1`. Deliberately never `0.0.0.0` |
| `[server] port` | `8756` | the port `tailscale serve` should front |

## Design notes

Raw Win32 via ctypes (`WH_KEYBOARD_LL` hook + `SendInput`) — the
`keyboard` library was dropped mid-build after its event delivery proved
unverifiable here, and the raw hook exposes `LLKHF_INJECTED`, which gives
the clean rule: the hotkey works injected or physical, but only *physical*
other-key presses abort a recording, so the app's own synthetic Ctrl+V can
never kill one. Unit tests: `.venv\Scripts\python.exe tests.py`.
