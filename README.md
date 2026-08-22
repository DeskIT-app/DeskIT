# HebrewDictation

Hold **Right Ctrl**, speak Hebrew, release — the cleaned transcript (no
fillers, self-corrections resolved) is pasted at your cursor in whatever
window has focus. Injection is clipboard + Ctrl+V, never per-character
typing, because per-character breaks RTL in terminals.

**Punctuation is a separate key, on purpose.** Whisper transcribes sounds,
not sentences. The language-model pass that repairs misheard *words*
([`[polish]`](#the-other-family-polish)) is deliberately forbidden from
touching anything else — punctuating your text is a rewrite, and this
app does not rewrite what you said without being asked. Tap **F2** on what
landed and it gets its commas, full stops and question marks, with your
words guaranteed untouched. See
[Punctuating what you just dictated](#punctuating-what-you-just-dictated).

For anything longer than a sentence, don't keep holding: tap **←** while
still holding Right Ctrl and the recording **locks on** — let go and talk
for as long as you want. Tap **←** again to transcribe, or **Esc** to throw
it away. See [Long dictation](#long-dictation-lock-the-key-with-).

**Reading rather than writing? Tap F8.** Select a word or a sentence
anywhere — a web page, a PDF, a chat, a field you have no permission to
edit — and a small box appears with the Hebrew, or with the English if
what you selected was already Hebrew. It is the one key that never
changes what is on screen. See
[Looking something up](#looking-something-up-without-changing-it).

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

Run **`install_fonts.py`** once to install Rubik for your user (no
admin) — the dashboard's typeface, designed for Hebrew and Latin
together; without it the window falls back to Segoe UI and stays
correct, just plainer. Then open **`Dashboard.vbs`** and drive all of it
from one window — see
[The dashboard](#the-dashboard) below. Double-clicking `Hebrew Dictation`
while it is *already* running opens the dashboard too, instead of the old
"already running" complaint.

The dashboard can start *and* stop the app, so it can replace both Desktop
shortcuts on its own; autostart is a separate shortcut in the Startup
folder and is unaffected either way. Its icon is `icon.ico` — run
`make_icon.py` (needs Pillow) to regenerate it. There are three cuts of
one drawing in that file, because 16 px cannot hold what 256 px can: the
sound arcs are dropped below 48, and the alef knocked out of the
microphone goes at 16, where it stops being a letter and becomes noise.

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

## Two versions: classic and fast

This folder carries **two whole versions of the app**, kept as git
branches, and you choose between them by double-clicking **`Versions`**
(`Versions.vbs` here):

- **classic** — the app exactly as it was when this system was added:
  local Whisper + the ~5 s `gemma3:12b` repair pass. Frozen.
- **fast** — the same dictation pipeline with the repair pass sent to
  **Groq's free API first** (~sub-second instead of ~5 s), falling back to
  the identical local path classic uses. Also adds knobs:
  `[polish] prefer = "groq" | "cerebras" | "ollama"` and
  `[local] beam_size`.

Switching stops the running instance, flips the branch, restarts the app,
and **carries your `config.toml` across untouched** — both versions commit
byte-identical settings, so your keys, seeds and vocabulary never change
underneath you. `.env`, `vocab.json`, `transcripts.log`, `recent\` are
gitignored and simply shared. A switch refuses if any *other* tracked file
has uncommitted edits, rather than guessing what to keep.

From a terminal instead of the window:

```
.venv\Scripts\python.exe versions.py list
.venv\Scripts\python.exe versions.py switch classic
```

**Or from the dashboard.** The sidebar has a **Version** screen: it names
what is running and offers one *Use this* button per other version.
Switching from there is the same stop–flip–restart, with progress shown in
the window, and the Overview status line leads with the current version's
name so "which one am I on?" never needs a click.

### What fast costs and needs

- **A key.** Put `GROQ_API_KEY=...` in `.env` (console.groq.com — free,
  no credit card, thousands of requests a day). Without a key the fast
  version runs the repair pass locally, exactly like classic — the setting
  costs nothing until the key exists.
- **Why not Cerebras?** It was the first choice here, on published free-
  tier terms. Measured live 2026-08-22 with a fresh account: balance
  $0.00, every model HTTP 402 payment required, subscription tiers
  $1,500+/month and sold out. The free tier is gone; support for it stays
  in the code (`[polish] prefer = "cerebras"`) for whoever holds quota.
- **Privacy, stated plainly:** the repair pass sends the *transcript
  text* to Groq under their free-tier terms. Your audio never leaves
  this machine. If even text-in-the-cloud is unacceptable, set
  `[polish] prefer = "ollama"` — that IS classic's behavior.
- **The safety check is unchanged.** Every repaired reply still goes
  through `_is_safe()` (word-level diff, ±15% growth cap); a model that
  rewrites instead of repairing gets thrown out exactly as before. Replies
  are also length-capped from the input size now, so a runaway generation
  is bounded rather than waited on.
- **Gemini stays out of the repair pass**, as before: its tiny 20/day pool
  belongs to Ctrl+F9 and F2. Groq is its own bucket and cannot starve
  them.

## The dashboard

`Dashboard.vbs` opens one window that answers "is it on?", turns it on and
off, and lets you move the keys. It is a **separate process** — it has to
be, since half its job is starting the app — and it talks to the running
instance over a named pipe (`control.py`). Closing it never stops
dictation; it is a remote control, not the app.

**One window, however many times you click the icon.** A shortcut to a
`.vbs` has no notion of "already open", so a second launch takes its own
named mutex, fails, pokes the window that exists and exits — clicking the
icon behaves like clicking a taskbar button. The window also claims its
own taskbar identity (`SetCurrentProcessExplicitAppUserModelID`) and sets
`icon.ico` on itself with `WM_SETICON`; without both, the taskbar shows
`pythonw.exe`'s generic icon and it reads as "some script is running".
Tk's own `iconbitmap()` is not enough — measured here, it reports success
and leaves `WM_GETICON` returning 0.

**Pinning it works too.** A pin is built from the process *executable*,
so pinning this window used to produce a tile with Python's icon that
said "Python" and relaunched a bare interpreter. The window now carries
relaunch properties on its own HWND (`SHGetPropertyStoreForWindow`:
command, display name, icon), so the pin launches `Dashboard.vbs` with
the right name and face. If you pinned it before this existed, unpin and
pin it again — the shell reads these when the pin is created.

**Five screens down the side, not one long column.** Everything that was
in that column is still here; it stopped being one scroll of unrelated
things. The state and the three buttons that change it are on
**Overview**; everything you have said is on **History**; the keys are on
**Keys**; which whole-app version is running, and the one-click way to
change it, is on **Version**; what it is using and where its files are is
on **Settings**. The status dot stays in the corner of the sidebar on all
of them, because "is it on?" is the question the window exists to answer
and it must never be a click away.

```
┌──────────────────┬──────────────────────────────────────────────────┐
│ ▣ Hebrew Dictation│ Overview                                        │
│   hold Right Ctrl │                                                 │
│                   │  ● RUNNING                                      │
│ ▸ Overview        │    fast · local · Arctis 7 @ 16000 Hz           │
│   History         │    4.2 s spoken -> 96 characters pasted         │
│   Keys            │                       [Start] [Pause] [Stop]    │
│   Version         │                                                 │
│   Settings        │  DICTATIONS  SPOKEN    CHARACTERS  AVERAGE WAIT │
│                   │  18          6.2 min   4,210       0.5 s        │
│                   │                                                 │
│                   │  LAST DICTATION                          21:23  │
│                   │      … the sentence itself, right-aligned …     │
│                   │  23.3 s · local · 3.4 s latency                 │
│                   │  [Copy text] [Show in history]                  │
│ ● RUNNING         │                                                 │
│   up 2h 14m       │  VOCABULARY 98 words   PHONE endpoint is live   │
└──────────────────┴──────────────────────────────────────────────────┘
```

The window is drawn rather than assembled: Tk 8.6 cannot round a corner
or anti-alias one, so every card, pill, switch and key cap in it is a
pre-rendered Pillow bitmap with widgets sitting on the flat middle of it
(`ui.py`). The palette is the one this window has always had.

### Everything you said, in the window

**The History screen is `transcripts.log`, read back.** The last hundred
entries, newest first, one row for each thing *you did* rather than one
for each line the code wrote:

```
  21:23   ▣    … what you said, up to two lines of it …            ⧉
  20 Aug       Dictation · 23.3 s · local · 3.4 s latency · polished

  21:08   ▣    [ heard ← meant ]  [ heard ← meant ]                ⧉
  20 Aug       Learned · 2 words
```

Three places where "one line" and "one thing that happened" are not the
same number, and `history.py` exists to reconcile them:

- **A translation is two lines** (`TRANSLATE-IN`, `TRANSLATE-OUT`) and one
  act. Joined, the row can show what went in as well as what came out —
  and the search box looks at both. Punctuation and lookups are the same
  shape.
- **A polished dictation is two lines** (`OK`, then `POLISHED`). Shown as
  two rows it is the same sentence twice, one of them with the misheard
  words still in it. The polish is folded into the dictation it belongs
  to and the row says `polished`.
- **A correction is a diff written as prose** (`CORRECTED | before ||
  after`): two whole sentences that differ in two words. The row shows the
  two words.

Filter chips across the top, and a search box that matches what you said,
what it answered, and which engine answered. **Click a row to copy it** —
the whole text, not the two lines the row had room for.

Nothing here writes to the log; a malformed line is skipped rather than
repaired. The log is still the record, `Open transcripts.log` is still
there, and everything older than the last hundred is still in it.

**Why the Hebrew is on screen at all.** This window used to show the last
dictation as `4.2 s -> 96 chars` with a Copy button, because Tk was
believed to have no bidi at all. The truth, measured on 2026-08-20 (Tk
8.6.12, Windows 11), has two layers:

- **The font.** "Segoe UI Variable" holds no Hebrew glyphs
  (`GetGlyphIndicesW` says so), and the per-word font fallback that
  papers over it breaks bidi segmentation — every Hebrew word rendered
  **letter-reversed** (בדקתי drawn as יתבדק), which looks exactly like a
  transcription bug. `ui.pick_face()` measures existence *and* Hebrew
  coverage before a face may carry a transcript. The face it prefers is
  **Rubik** (designed for Hebrew+Latin, SIL OFL, vendored in `fonts\`,
  installed per-user by `install_fonts.py`); the floor is Segoe UI.
- **The base direction.** With a Hebrew-capable face, Tk shapes each run
  correctly but lays the *runs* of a mixed line out left-to-right, so the
  two Hebrew halves of a sentence swap around an English word — the exact
  failure the lookup box was built to avoid (see [Why the box is a Win32
  window and not Tk](#why-the-box-is-a-win32-window-and-not-tk)).
  Directional control characters change nothing; Tk strips them. So
  transcripts are not Labels: `ui.draw_text` renders them with
  `DrawTextW`+`DT_RTLREADING` — the same call the lookup box has already
  proven — into bitmaps, wrapping and the trailing … included, and a test
  holds the result against that reference render pixel-for-pixel.

Pure-Hebrew lines are a single run, which is why quick probes look fine
and the second layer stayed hidden until a mixed sentence landed on the
overview. The chrome stays English on purpose: a label is one direction
by construction.

### Pause, and why it is not "stop"

**Stopping unloads two Whisper models; starting again reloads them, which
is the ~25 s you were trying to avoid.** Pausing unloads nothing. The keys
go inert, everything stays in VRAM, and resuming is instant — which is
what you want before a game, where holding Right Ctrl would otherwise
start a recording every time.

- `pause_hotkey` (default **Insert**) toggles it from anywhere,
  including from inside a fullscreen game. It is the one key that still
  works while paused — a key that only worked while the app was listening
  could never turn listening back on — and it never means anything else.
- Two falling notes = paused. Two rising = listening again. The cue is the
  whole confirmation when the status dot is behind a game.
- The dot goes grey.
- A recording in flight when you pause is **discarded**, not transcribed.
  Pausing means stop listening; half a sentence appearing at your cursor a
  moment later is the opposite of that.
- **The phone endpoint keeps working.** This pauses the keyboard.
- `auto_pause_fullscreen` does it by itself while a game or a
  presentation owns the screen (it asks Windows the same question it asks
  before showing its own notifications), and the switch for it is on the
  dashboard's **Settings** screen. **Off by default**: it is the one
  setting that can stop dictation without anyone asking it to, and "my
  hotkey stopped responding" is a much worse half hour than tapping the
  pause key yourself. It only ever un-pauses *its own* pause.

### Changing the keys

Click a key in the dashboard and press the one you want. The running app
is paused while it listens, so the key you press cannot set anything off —
without that, pressing Right Ctrl to bind it would start a recording and
pressing Ctrl+F9 would translate whatever happened to be selected.

**Chords are captured the way you would press them**: hold Ctrl, then hit
F9, and the dialog records `ctrl+f9`. It waits after a modifier rather
than binding it — the first key event of Ctrl+F9 *is* the Ctrl, and a
dialog that took the first thing it saw would set the key to `left ctrl`
and close. A modifier pressed and released on its own still binds itself,
which is how `Right Ctrl` gets set, and the side you pressed is kept.

The change applies **live** (no restart) and is written to `config.toml`
**with every comment kept** — it is edited line by line, not re-serialised,
because most of those comments are measurements. A key that collides with
another one is refused with a sentence before anything is written, and the
new file is fully parsed and validated before it replaces the old one:
clicking in a dashboard must not be able to produce a `config.toml` the
next launch refuses.

Keys can be changed with the app stopped too — the dashboard edits
`config.toml` directly and says it applies at the next start.

> An instance started *before* this window existed holds the lock but
> cannot answer it. The dashboard notices after 45 s and says so — stop and
> start it once to get the controls.

### Which keys are safe

**The tap keys are not swallowed.** They fire the action *and* reach
whatever has focus, which is why the question "which key should this be?"
is really "which key does nothing in Chrome, in Google's apps, in
Microsoft 365 on the web, in WhatsApp Web and in Spotify?" The honest
answer is: almost none of them. Chrome takes F1, F3, F4, F5, F6, F10, F11
and F12 — eight of the twelve, measured on this machine, every one of
them either reloading the page, going full screen or taking the caret out
of it. Edge takes the same eight. Excel for the web is said to take F2,
F4, F6, F9 and F11 and Gmail to bind most of the alphabet; neither was
measured here, and the paragraph after the table says which rows were.

Seven that survive, best first:

| key | free in | taken by | one-handed? |
|---|---|---|---|
| **`f8`** | Chrome, Edge, all seven Google apps, Word / Excel / PowerPoint / Outlook / Teams on the web, WhatsApp Web, Spotify, the NVIDIA overlay | a console (history search), VS Code (next problem) | **yes** — the right edge of the F5–F8 block is a tactile landmark, so it is findable blind |
| **`ctrl+f8`** | all of the above, *plus* the console and VS Code | nothing found | yes, with the **left** ctrl |
| **`ctrl+f9`** | the same list | nothing found | yes, with the **left** ctrl |
| **`f2`** | Chrome and Edge — verified twice, once with the page blocking the key and once letting it through | Drive, Explorer and VS Code (rename), Excel and PowerPoint on the web (edit this cell) | **yes** — the easiest reach on the board |
| **`f13`–`f24`** | Chrome and Edge, measured directly — every one of the twelve reached the page and did nothing | nothing found | only once you make one — no keyboard sends them. Remap a key in SteelSeries GG, a mouse thumb button in G HUB, or use PowerToys Keyboard Manager |
| **`ctrl+f12`** | Chrome and Edge, measured directly. F12's own claimants (DevTools, Steam's screenshot) are bare-only | nothing found | **no** — F12 is at the far right of the row, and that hand is on the mouse |
| **`pause`**, **`scroll lock`** | Chrome and Edge, measured directly | nothing found | **no** — top-right island, beside the OLED and the volume roller. Right for `pause_hotkey`, which you tap twice a day on purpose; wrong for one you tap thirty times |

**How much of this was actually measured, and what was not.** The browser
column comes from a real probe: a local page that logs every `keydown`
and every focus change to a file the test cannot erase, driven twice —
once with the page cancelling the key (does the browser even let it
through?) and once letting it through (does the browser then *do*
something?) — in Chrome and in Edge. It covers `f1`–`f6`, `f10`–`f24`,
`pause`, `scroll lock`, and ctrl / shift / alt over `f1`, `f2`, `f3`,
`f5`, `f6`, `f10`–`f16`.

**It never pressed `f7`, `f8` or `f9`, or any chord on them** — which is
to say the three keys this app now ships on were reasoned about, not
measured. Read those rows as follows:

- `f8` and `ctrl+f8`, `ctrl+f9`: **not measured.** What *was* measured is
  every neighbour — thirteen different `ctrl+F<n>` combinations, `f10`
  through `f24` bare — and not one of them was taken by either browser.
  That is a good reason to expect `f8` and the two chords to be clear,
  and it is not the same as having pressed them. The everything-else
  half of that row (Google apps, Office on the web, WhatsApp Web,
  Spotify, the NVIDIA overlay, a console, VS Code) is **not measured at
  all**: the probe is a web page and can only report what a web page and
  its browser did.
- `f7` and `f9` are named below as taken. **Also not measured** — they
  are the two the probe skipped. Chrome's caret-browsing dialog on `f7`
  and Edge's Immersive Reader on `f9` are both documented behaviour, but
  the file in front of you did not check them.

If a key matters enough to argue about, press it on the page yourself
before believing this table.

**Not these, and one of them is the obvious guess.** `ctrl+f6` — the
chord this feature was built for — is reserved right across Microsoft
365: Word, Excel, PowerPoint *and* Teams on the web all use it to jump
between the ribbon and the content. In the *browser* it is free, and
that is measured: `ctrl+f6` reached the page and did nothing observable
in Chrome and in Edge, five separate runs. It is off the list on the
strength of the Office half alone. Also out: `caps lock` (the best key on the
board if the app swallowed it, and it does not swallow tap keys, so every
press would toggle caps), any bare letter or digit, `f6` (the address bar
— your original complaint, and it is Chrome's doing, not Google's), `f7`
(Chrome's caret-browsing prompt, Docs' spell-check), `f4` (Edge's address
bar, Excel's `$A$1` toggle), `insert` (Outlook flags a message; overtype
everywhere else), and the media keys, which Spotify, Chrome and Teams are
already fighting over.

### Modifier chords, and why only `ctrl`

The four tap keys take `modifier+key`. The modifier may be `ctrl`, `shift`
or `alt`, either side (`ctrl+f8`) or a named side (`left ctrl+f8`), and
the key comes **last**:

```toml
translate_hotkey = "ctrl+f9"      # either ctrl — this is what ships
correct_hotkey   = "left ctrl+f8" # name a side and only that key counts
lookup_hotkey    = "f8"           # bare, exactly as it always was
```

`"f8+ctrl"`, `"ctrl+shift"` (no key to fire on) and `"win+f8"` are refused
with a sentence. `"f8"` and `"ctrl+f8"` are two different bindings and may
both be bound: the chord wins when its modifiers match exactly, the bare
key catches everything else, and only one of them ever fires. The four
other keys — dictate, English, latch, pause — **refuse** a modifier,
because they are held, latched and toggled rather than tapped.

**Use `ctrl`, not `shift` and not `alt`,** and that is a rule about this
app rather than about Windows. A tap key injects `Ctrl+A` / `Ctrl+C` /
`Ctrl+V` about 50 ms after it fires, and it does not release the modifier
your hand is still holding. Ctrl is harmless there because every chord the
app sends already begins with ctrl — ctrl held over `Ctrl+C` is still
`Ctrl+C`. Shift is not: it turns that copy into `Ctrl+Shift+C`, which is
Inspect Element in Chrome, and the select-all into `Ctrl+Shift+A`, which
is Search Tabs and takes the focus the paste was about to land in. Alt is
worse again — the NVIDIA overlay owns `Alt+F1/F2/F3/F9/F10` on this
machine, `Alt+F4` sits one key from `Alt+F5`, left Alt+Shift switches
keyboard layout, and `Ctrl+Alt` *is* AltGr, which on the Hebrew layout is
the niqqud level.

Which is why no shift or alt chord appears in the table above, however
free of the browser it measures. `shift+f12` in particular looks ideal
and is not: the browser ignores it, and then your held shift turns the
app's own `Ctrl+C` into Inspect Element and no text is ever read. The
app will still *bind* a shift or alt chord if you ask it to — that is
your business, not a thing it can check — but nothing here recommends
one.

Press a ctrl chord with the **left** ctrl. The right one is the dictation
key, so it starts a recording and the tap then aborts it: nothing is
transcribed, and nothing else happens either.

### Four defaults changed, and you were living with three of them

`lookup_hotkey` was `j` — every `j` you typed sent a `Ctrl+C` into the
focused app, opened a box and spent GPU time, and Gmail and Calendar bind
bare `j` as well. `punctuate_hotkey` was `f7`, which is Chrome's
caret-browsing key: Chrome answers it with a **modal dialog**, so every
punctuate in the browser asked a question first, and Docs uses it for
spelling. `translate_hotkey` was `f9`, which Edge uses for Immersive
Reader, Excel for the web uses to recalculate, and every IDE uses for
breakpoints. `correct_hotkey` was `f8` and `f8` was the one binding that
was already right — it moved to `ctrl+f8` only so the lookup key, the most
tapped of the four and the only one you press mid-sentence with the other
hand on the mouse, could have it.

## Behavior you should expect

- **Beeps:** two rising = app ready; high = recording started; high +
  higher = locked on, you can let go; mid = captured, transcribing; single
  mid-high = translating; rising pair = translation landed; the same two
  notes a fourth lower = punctuating and punctuated, and the same two
  again on a pitch *between* those two families = looking something up
  and the answer, because three tap keys that feel identical under the
  finger need three sounds you can tell apart; two low =
  error; **two falling from mid = paused; two rising to mid = listening
  again**; one short neutral note = heard you, nothing to do; two falling =
  app stopped. No beep on aborts (by design). Hear them all with
  `--test-sound`.
- **Startup takes ~25 s** (two Whisper models onto the GPU) and a small
  window appears bottom-right while it happens, naming each step as it
  goes. Without it, clicking the shortcut is indistinguishable from
  clicking a shortcut that does nothing — so you click again. It does not
  take focus and does not appear in Alt-Tab; it vanishes once the hotkey is
  live. Turn it off with `splash = false`.
- **A small dot sits in the top-right corner while the app runs** — blue
  when idle, red while recording, red and breathing while a recording is
  *locked on*, amber while transcribing, grey while paused. If you ever saw
  the loading box stay on screen *and* no dot appear, that was one bug, not
  two: `quit()` in Tkinter sets a flag shared by every Tk window in the
  process, so about half the time the splash's "close" closed the dot
  instead and left itself running. Neither overlay calls `quit()` any more
  (`overlay._pump_until`), and a test asserts they never will. It is how you tell a running app
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
- **It gets a word wrong? Tap `Ctrl+F8`, fix it, and it stops getting it
  wrong.** See [Teaching it the words it gets
  wrong](#teaching-it-the-words-it-gets-wrong).
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

## Translating to English

Dictation always writes what you said, in the language you said it. When
you want the same message in English, **tap** (don't hold) `Ctrl+F9`:

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

## Punctuating what you just dictated

**Whisper transcribes sounds, not sentences.** The local Hebrew fine-tune
hands back a run of words with barely a comma in it, and nothing else in
the fast path puts them there: [`[polish]`](#the-other-family-polish) is
forbidden from adding punctuation — it may only fix *mishearings*, and a
reply that added anything else would be thrown out by its safety check. So:
dictate, read it, **tap** `F2`.

- **Something selected?** Only the selection is punctuated.
- **Nothing selected?** The whole field is (the key sends Ctrl+A itself).

```
תוסיף עוד עיר לאפליקציה ואז תריץ את זה מחדש מה דעתך
->
תוסיף עוד עיר לאפליקציה, ואז תריץ את זה מחדש. מה דעתך?
```

A low beep when it starts, a rising pair when the text lands — a fourth
below the translate key's, so a press that went to the wrong one of the
two is obvious by ear.

### Your words cannot change, and that is checked, not hoped for

This key replaces text you are about to send, on a language model's
say-so. So the promise is not in the prompt, it is in `punctuate.py`:
**every non-letter is stripped from the reply and from your text, and the
two must be identical.** Spaces, newlines, every punctuation mark and
Hebrew nikud all fall out of that comparison — so the model may break a
paragraph into lines, but a model that rewrote a word, dropped a
hesitation it thought was noise, translated a term, or *answered* your
text instead of punctuating it fails the check.

A failed reply is never pasted. The other backend is tried, and if that
fails too your text is left exactly as it was, with an error cue and the
reason in `app.log`.

### Which model

Gemini first, Ollama when the daily cap is spent — same order as the
translate key, and the same `ollama pull llama3.1:8b`. Measured on real
dictations 2026-08-15:

| | punctuation | speed |
|---|---|---|
| Gemini | every comma, full stop and question mark, plus the maqaf in `ה-commit` | 0.6–3.2 s |
| llama3.1:8b | never broke a word, but added only a trailing full stop on one of two samples | 17.7 s cold, 3.6 s warm |

Set `[punctuate] prefer = "ollama"` if you end up tapping this after
*every* dictation — the free tier is 20 requests/day/model and the
translate key draws on the same bucket.

`[punctuate] nikud = true` adds Hebrew vowel points as well as
punctuation. The same letter-for-letter check covers it, because nikud are
combining marks and drop out of the comparison exactly like a comma does.

Guards, all shared with the translate key: it refuses over `max_chars`
(5000), writes the original to `transcripts.log` as `PUNCTUATE-IN` before
the paste, restores your clipboard on every exit path, and leaves the text
on the clipboard rather than pasting it if you moved to another window
while it worked. Pressing it on an already-punctuated field is a soft
"nothing to do" note, not an error.

Check it without touching the keyboard:

```bash
.venv\Scripts\python.exe main.py --punctuate "תריץ את זה מחדש מה דעתך"
```

## Looking something up without changing it

The other three tap keys rewrite what is on screen. This one is the exact
opposite, and that is the whole point of it: **select a word or a sentence
anywhere, tap `F8`, and a small box appears beside what you selected with
what it means.** A term in a web page, a line in a PDF, a message in a
chat, a field you have no permission to edit — nothing is typed, nothing is
pasted, nothing on screen moves, and the box stays until you close it.

- **A word or a short term** comes back as a dictionary entry: the single
  best equivalent on its own first line, then up to three senses, each
  labelled with its part of speech from a closed Hebrew list (`שם עצם`,
  `פועל`, `שם תואר`, `תואר הפועל`, `ביטוי`, `קיצור`). `brittle` comes back
  as `שביר`, with one sense for the adjective and one for the noun.
- **Anything longer** comes back translated.
- **Both directions, decided per selection.** English goes to Hebrew,
  Hebrew comes back as English — one key, one habit. `both_ways = false`
  if you only ever want the Hebrew direction.

```
תעשה commit לפני ה-merge
->
Make a commit before the merge
```

**It closes two ways, and nothing else closes it: the `×` in its title
bar, and `Esc`.** Not a timer, not your next keystroke, not a click, and not the
mouse — three of which used to take it away on their own. The mouse was the
bug. The report was "it disappears randomly, maybe because of the wheel",
and the rule underneath it was dismiss-on-mouse-*leave*: the box opens
where you were pointing, which means it opens under the cursor, so the
first twitch of the hand deleted the answer. From the outside that is
indistinguishable from a box vanishing at random, which is exactly what it
looked like.

Esc is swallowed, and only while a box is up, so it closes the box without
also reaching the editor behind it. **Two** keys are taken and no others —
Esc, and the `Ctrl+C` described below, under five conditions that all have
to hold at once. Everything else on the keyboard is passed straight
through untouched: the box has no keyboard of its own, because it never
takes focus, and it used to be dismissed by *any* key, which meant an
answer could not be read with a hand resting on Shift.

**Where it appears:** beside the selection, never on top of it. It sits a
gap below what you pointed at, flips above when the bottom of the screen
is in the way, and hangs its reading edge under the anchor — a Hebrew
answer its right edge, an English one its left — flipping to the other
side rather than being clipped. It stays inside the work area of the
monitor the selection is on, including when the selection is on the second
screen and including when the mouse is over the taskbar. The anchor is the
caret where the app has one, and where it does not — anything built on
Chromium, which is most of what this key gets used in — it is where the
mouse was when the key went down, which after a drag-select is the end of
what you selected.

The key is rebindable from the dashboard like every other one, `""` turns
it off, and every answer goes into `transcripts.log` (`LOOKUP-IN` /
`LOOKUP-OUT`) before it reaches the screen, so a box you dismissed too fast
is read back from there.

### The title bar moves it, and nothing else does

**Drag the box by the strip across its top; everything under that strip is
text you can take.** Like every other window on this machine. It used to be
draggable from *anywhere*, which is exactly why it could not also offer its
text — one press cannot both move a window and take a line out of it, so
the box had to pick one. It picks per press now, and the whole decision
lives in one function: the buttons first, then the bar, then the body.

**The bar names the word you asked about**, which the box otherwise has no
way to know — it is handed an answer, never the question. That matters most
once the box has outlived the selection: drag it away from your text, or
read it after the highlight has gone, and the bar is the only thing on
screen still saying which word this is about. A phrase too long for the bar
is elided rather than allowed to widen the box; the answer decides the
width, not the caption. With nothing passed it says `עברית` or `English`,
which is the box telling you which way the model actually answered.

**Two copy buttons, and `Ctrl+C`:**

- The **first** button, next to the `×`, copies the whole answer — *the
  whole* answer, not what fitted. A long one is trimmed on screen to the
  520 px cap; the button still hands over all of it. Measured on a
  1762-character answer showing 565 of them: the clipboard got 1762.
- **Press a line to take it, drag for a range, double-click for the whole
  sense** however many lines it wrapped to. A **third** button appears in
  the bar while something is lit and copies exactly that and nothing else.
  Its room is reserved from the moment there is an answer, so pressing on a
  sense never shuffles the `×` out from under a finger already on its way
  to it.
- `Ctrl+C` does the same as that third button. It is swallowed only when
  all five of these hold at once: something is selected, the box is up, the
  chord is plain (no Shift, Alt or Win), the window in front is still the
  one you made the selection in front of, and it is not a console — Ctrl+C
  in a terminal is an interrupt, and eating the one that was meant to stop
  somebody's build is worse than making them click the button. Fail any of
  the five and the chord belongs to the app underneath and goes there
  untouched. The button always works; the chord is an accelerator on it,
  never the only way.
- **A copy you take from the box survives.** Every other clipboard path in
  this app saves your clipboard and puts it back afterwards, and the
  translate key holds that pair open for as long as its model takes — with
  the box readable and copyable throughout. So a copy made here *claims*
  the clipboard and those restores stand down. Measured before that guard:
  a copy taken during a translation was destroyed 5 times out of 5. Windows
  Clipboard History will record it, which is the opposite of what the
  capture path takes care to avoid and is right here — this one you asked
  for.

**Selection is by character, and it behaves the way a browser's does.**
Drag through the text and you take exactly what you crossed; double-click
takes the word under it. The interesting half is what happens at a change
of direction. Drag leftwards through `Whisper הוא` and the range stays
*contiguous in the string* while the highlight on screen breaks into two
blocks with the `Wh` dark between them — one selection, two rectangles —
because the English sits inside the Hebrew the other way round. That is
what every browser does with the same text, and it is why the caret
appears to jump to the far side of a word as you cross into it.

This needs a character hit test, which `DrawTextW` does not have, so every
line is drawn by **Uniscribe** (`ScriptStringOut`) instead: it answers the
hit test, and it is given a *logical* range and works out for itself which
rectangles that is on screen. Every line goes through it and not just the
selected one, because two painters on alternate lines of one paragraph is
how a line comes to shift the moment it is selected.

**How much the change of painter moved the text: nothing at all.** The
same line rendered both ways into two identical bitmaps and compared byte
for byte came back *identical* on all 610 samples — ten hand-picked shapes
and 600 real lines out of this machine's own `transcripts.log`
(2026-08-20) — and then the whole window, captured before and after the
change, came back identical pixel for pixel inside the box, against a
control that rendered the same painter twice and differed by nothing.

It is only free if `ScriptStringOut` is called with **no rectangle**.
Handing it the row's rectangle is what a first attempt did, and it cost
two things at once: the highlight was painted across the row's whole
width, reaching out past the last letter of a short line into empty space
as if text were selected that was not there — and 368 pixels of a 265 px
box came back one value in 255 out, because filling the row changes the
ground the glyphs are blended against and ClearType notices. With no
rectangle the fill covers the glyphs' own extents, which is what a
selection is. The row is still clipped, through the DC's clip region.

What lands on the clipboard is the string that was drawn, in its own
order: a Hebrew line with `Whisper` inside it copies as it was written,
not as the glyphs came out left to right.

### Which way round, and when it refuses

Direction is decided by counting **words, not letters**.
`תעשה commit לפני ה-merge` is 9 Hebrew letters against 11 Latin ones, so a
letter count calls that sentence English; Hebrew is written without vowels,
which makes words the only fair unit. At or above `hebrew_share` (0.34) of
Hebrew words the selection goes to English, below it to Hebrew.

It refuses — the soft "nothing to do" note, **no request spent** — on an
empty selection, on more than `max_chars` (5000: a paragraph is what Ctrl+F9 is
for), on digits, punctuation or emoji alone, and on a lone URL, path or
e-mail address. Identifiers are deliberately *not* refused; `commit` is
exactly what this key exists for. Any of them takes the box down first: a
box that waits to be closed would otherwise leave the answer to the *last*
question standing as the answer to this one, with the note playing over it
saying otherwise.

**A second tap asks a new question.** It used to close the box instead,
which was right while the box dismissed itself — the key that opened it
was the obvious key to shut it — and became wrong the moment the box
started waiting to be closed: under that rule, selecting a second word and
tapping did nothing except make the first answer disappear. Closing is
what the `×` is for. What a tap still refuses is a lookup already *in
flight* — one clipboard, one selection, one answer being written — and
that plays the soft note.

### It changes nothing, and it never selects for you

- **No Ctrl+A, ever.** Ctrl+F9 and F2 send it on purpose — with nothing selected
  they take the whole field. A read-only key doing that would leave your
  entire document selected, and your next keystroke would wipe it. Measured
  in the places this key actually gets used, that select-all grabs 188
  characters of a web page, 1781 of an Electron conversation and 11914 of
  terminal scrollback. So an empty selection is an empty answer, not the
  whole page.
- **Your clipboard is borrowed for about 20 ms and put back** — text,
  images and copied files alike, in a `finally`, so an exception between the
  copy and the restore cannot leave your selection sitting on it. Verified
  byte-identical after every end-to-end round on 2026-08-19. Two formats are
  *not* restored, HTML and RTF, so a Chrome copy pasted into Word loses its
  formatting until your next real copy. **The one deliberate exception is a
  copy you made yourself** — either button on the box, or its `Ctrl+C`.
  That one claims the clipboard and no restore in this app will put
  anything back over it.

### Two things worth knowing before you trust the word "read-only"

- **Windows Clipboard History keeps every capture.** The only way to read a
  selection out of another app is to copy it, so `Win+V` holds what you
  looked up — about five entries per capture on this machine, permanently,
  and there is no API to ask that another app's copy be excluded. This is
  already true of Ctrl+F9 and F2; it is said here because "read-only" means *the
  app changes nothing on screen*, not *nothing is recorded*. If that
  matters, turn Clipboard History off in Windows settings.
- **Console windows are refused.** Windows Terminal turns a copy chord with
  nothing selected into a real **Ctrl+C interrupt** for whatever is running
  in it — reproduced 5 times out of 5, and `ctrl+shift+c` interrupts too,
  so there is no safe chord to use instead. The key sends nothing there and
  plays the soft note; `skip_consoles = false` tries anyway. Both the window
  you pressed the key in *and* the one that has focus when the copy actually
  goes out are checked, because those can be different windows: the press is
  remembered on the hook thread and the capture then waits its turn behind
  Ctrl+F9, which can hold the cursor for as long as its model takes. Tap the key
  in a browser, alt-tab to a terminal, and the chord would otherwise land
  there. **VS Code's
  integrated terminal is the hole**: it does not announce itself as a
  console (its window class is `Chrome_WidgetWin_1`), so it is not covered.
  Untested, and not a thing to try while a build is running.

Elevated windows are the same UIPI story as everywhere else here. DPI
scaling other than 100% is untested — both monitors on this machine are
96 dpi and the process is DPI-unaware, so Windows will stretch the box:
correctly sized, slightly soft, on screen.

### Ollama goes first here, and translate and punctuate are the reason

This is deliberately the opposite order to
[translating](#translating-to-english) and
[punctuating](#punctuating-what-you-just-dictated), and the
arithmetic settles it. The free tier is 20 requests per model per day across
four models — about 80 — and `app.log` shows Ctrl+F9 and F2 *alone* spending
34 / 39 / 17 / 18 of them on working days, and running into 429s on seven
separate days. This key costs nothing to press and gets pressed while you
are **reading**, so it would plausibly run 30–60 times a day; sent to the
cloud first it would take the whole pool and break the two keys whose local
fallback is the weak one.

Measured 2026-08-19 over `127.0.0.1`, warm: `gemma3:12b` answers a word in
1.9–3.1 s and a sentence in 1.0–2.0 s, against Gemini's 0.8–1.3 s. About a
second slower, and free. It costs no extra VRAM either —
[`[polish]`](#the-other-family-polish) already keeps that model resident.

A cold model is the exception. The key asks Ollama whether the model is
loaded (1 ms over `127.0.0.1`, 2049 ms over `localhost` — which is why that
config line is a literal IP), and if it is not, *this one* lookup goes to
Gemini while the local model warms up in the background: cold is 24.4 s to
the first token, and nobody watches a box for that long. Bounded at about
one cloud request per 30 idle minutes. `cold_to_gemini = false` turns it off
and you wait instead.

**Answers are cached**, in `lookup_cache.json` next to `vocab.json`.
`brittle` means the same thing tomorrow, and looking the same word up twice
is the whole point of the key. Measured 134 bytes an entry, so the 500-entry
default is about 67 KB, and a repeat is 0.00 s instead of 2.33 s with one
request saved. Only selections under 200 characters are kept. That file is a
record of what you were reading, so it is gitignored like `vocab.json`;
delete it whenever you like.

One honest quality note: single-word answers are right about 7 times in 8 on
`gemma3:12b`. `deadlock` failed three separate ways locally and Gemini got
it first time. Word mode is the one place the cloud is measurably better —
and also the most cacheable, so the cost is bounded by the number of
*distinct* words you look up, not by how often you tap.

### Why the box is a Win32 window and not Tk

Because **Tk 8.6 has no way to set a paragraph's base direction, so a Hebrew
answer comes out with the two halves of the sentence swapped around any
English term in it.** Measured on this machine on 2026-08-19, screenshotted
and compared glyph by glyph: given the logical string `אב גד ABC הו כל.`,
Tk puts the full stop at the far **right** and exchanges the two halves of
the sentence around the `ABC`; `DrawTextW` with `DT_RTLREADING` puts it at
the far **left** and leaves the sentence in the order it was written. There
is no point printing Tk's output here — your browser would reorder it a
second time; `popup.py`'s docstring holds the comparison. That flag hands
Windows' own bidi algorithm the correct base direction, and everything
downstream of it — mirrored brackets, digit and percent runs inside Hebrew,
trailing punctuation, niqqud — comes out right with no extra dependency.

The direction is taken from the language the answer was asked *for*, never
guessed from the text: 1.4% of the Hebrew lines in this machine's own
`transcripts.log` begin with a Latin word, and a guess renders every one of
those backwards.

The box never takes focus, never appears in Alt-Tab, absorbs a click without
activating, is placed beside the selection on the monitor that selection is
on, and is capped at 460 × 520 px with anything longer trimmed. Not one GDI
or USER object leaked over 200 cycles of opening and closing it — re-counted
2026-08-20 now that it has a bar, three buttons and a highlight to paint:
flat at 9 GDI / 4 USER across 200 open-and-close cycles, flat at 10 / 4
across 200 selection changes, and flat across 61 copies (the USER count goes
to 5 while the "copied" flash timer is up and back to 4 when it expires,
which is the timer, not a leak). Driving the box against a text editor in
another process left **one** (foreground, focus) state for the whole run —
show, both drags, six selections, two copies, `Ctrl+C` and close — and what
was typed afterwards still went to the editor.

Placement is swept rather than sampled, and the sweep is a test: every
149 × 137 px of **both monitors' full rectangles** — not their work areas —
in both directions, at three box sizes. Sweeping the full rectangle is the
point. The anchor is not guaranteed to be inside the work area, because it
can be the mouse and the mouse can be over the taskbar; the first run of
that sweep found 376 placements that hung under it, and one of them left
25 px of the box lying across the Start button.

### You see the answer before it is finished

The local model writes a word at a time and the box now shows each one as
it lands, instead of staying empty until the last token. Measured
2026-08-19 on this machine, six selections, warm model, cold cache, timed
to the **first text on screen** — which is the only number you actually
feel:

| | whole answer only | as it is written |
|---|---|---|
| `brittle` | 1.67 s | **0.73 s** |
| `cumbersome` | 1.64 s | **0.61 s** |
| `מסורבל` | 1.19 s | **0.59 s** |
| an English sentence | 1.02 s | **0.64 s** |
| a Hebrew sentence | 0.86 s | **0.58 s** |
| a 250-character paragraph | 2.31 s | **0.58 s** |

Median 2.1× sooner, and the paragraph 4×. The *totals* are unchanged —
1.41 s against 1.43 s median — because nothing about the model got faster.
What changed is that the box stopped being empty while it worked. It
repaints on a completed line or every 80 ms and never per token: tokens
arrive 24 ms apart, and a box resizing forty times a second reads as
jitter rather than as speed.

A repeat of anything you have already looked up is served from
`lookup_cache.json` in 0.000000 s without a single repaint.

Streaming quietly took `ollama_timeout_s` away, and it has been handed
back. That timeout is per socket *operation*: unstreamed, the server says
nothing for the whole generation, so the first read times out and the
request is bounded — by accident, but bounded. Streamed, a token lands
every 24 ms, no read ever waits, and nothing bounds anything. Measured
against a server that streamed for 8.0 s at `ollama_timeout_s = 3`: 394
chunks and no timeout. A model that loops would have answered nothing and
refused every further tap for as long as it kept writing, so the stream
now carries its own deadline and gives up like any other failed request —
the error note, and the next backend.

### Check it by hand

Glyph order, legibility and DPI cannot be unit-tested, so seven checks are
yours — worth redoing after any change to `popup.py`:

1. **A Chrome page** — select an English sentence, tap `F8`. The Hebrew must
   read right-to-left, with the full stop at the far **left** of the last
   line.
2. **VS Code** — select an identifier in the editor (not in the integrated
   terminal); the answer arrives and the editor loses nothing.
3. **A read-only field** — a PDF in the browser, or a greyed-out box. The
   answer appears and the field is untouched.
4. **A Hebrew selection** — the answer comes back in English, left-aligned,
   and the English is not reversed.
5. **A very long unbroken token** — a 200-character URL or hash. The box
   must stay inside its 460 px and break the token; a window running off the
   side of the screen is the failure that cap exists for.
6. **Leave it alone and read it.** Move the mouse over the box, off it,
   back on; turn the wheel on it; type; wait half a minute. It must still
   be there, and then the `×` must close it. This is the one the owner
   reported, and the only check here that is about the box *not* doing
   something.
7. **Move it and take a line out of it.** Drag it by the title bar — it
   follows the cursor; drag it by a sense — it does not move a pixel, and
   the line lights up instead. Press the third button and paste: exactly
   the lines that were lit, in the order they were written. Then keep
   typing into the window underneath: the box never took the focus, so
   what you type still lands where it was going. **The `Ctrl+C` half of
   this can only be checked by a real finger** — every synthesised key
   carries `LLKHF_INJECTED` and the hook deliberately never offers those
   to the box, which is the same gate that keeps the app's own copy chord
   out of it. So no script can press this one for you.

Check the backends without touching the keyboard:

```bash
.venv\Scripts\python.exe main.py --lookup "brittle"
.venv\Scripts\python.exe main.py --lookup "תעשה commit לפני ה-merge"
```

It prints which way round it went, which backend answered and how long it
took, and it refuses exactly what the key refuses. Safe to run while
dictation is running.

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

**Everything you teach it with `Ctrl+F8` on the desktop applies here too**, and
there is nothing on the phone that implements it: the phone only records,
this machine transcribes, and it does so with the same model and the same
[learned vocabulary](#teaching-it-the-words-it-gets-wrong). Correct
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

## Teaching it the words it gets wrong

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
then **tap `Ctrl+F8`**. It reads the corrected text off the screen, diffs it
against what it produced, and learns the difference. If the field holds a
lot of other text, select just the corrected sentence first.

There is deliberately **no edit box**. The first version put the transcript
in a Tk window to be fixed there, and Tk 8.6 is a bad place to *edit*
right-to-left text: the base direction cannot be set, so a line that
begins with a Latin word lays out around it, and the caret jumps as it is
typed into. You are already fixing the text in an app with
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

### What the key sounds like, and when it says nothing

**Most presses of this key legitimately learn nothing** — you already sent
the message, or it got the words right. Those are not failures and no
longer sound like one:

| you hear | it means |
|---|---|
| two rising notes | it learned something (the dashboard names the words) |
| one short neutral note | nothing to learn — see below |
| two falling notes | a real error: the clipboard was locked, or the selection was too big to search |

The single note covers three cases, and the dashboard's **last** line says
which: the text is not on screen any more (usually: you pressed Enter),
there is no text where the cursor is, or the text is unchanged.

**The same cue does not repeat within four seconds.** It used to. Pressing
a key that appears not to have worked is exactly what anyone does, and on
2026-08-14 `app.log` recorded nine presses in five seconds — all failing
for the same reason, all beeping. Nine identical answers to one question is
heard as one long fault, not as an answer.

The translate key (Ctrl+F9) had the same three "nothing to do" cases — an empty
field, no Hebrew in it, a selection too big to send — and now behaves the
same way. The punctuate key (F2) was built with the same rule from the
start: an empty field, a field with no words in it, and a field that came
back already punctuated are all one soft note, once. So was the lookup key
(F8), which has more of them than any other — nothing selected, a selection
too long to send, nothing translatable in it, a console window it refuses
to send a copy to, and a second press while the first is still in flight.
Each is a different sentence in the dashboard and in `app.log`, and all of
them are the same single note.

> Fixed at the same time: pressing the key twice after one edit used to
> learn that edit **twice**. The app went on believing it had produced the
> unfixed text, so the second press diffed the same change again — and two
> hits is the threshold at which a garble starts being repaired
> automatically, so a single correction could confirm itself. Check
> `main.py --vocab` for a `[auto] 2x` entry you only ever corrected once.

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

**This pass is local only — there is no Gemini fallback**, unlike
[translating](#translating-to-english) and
[punctuating](#punctuating-what-you-just-dictated). It used to have
one, back when it ran a few times a day and every run cost you a wait. It
now runs on *every* dictation with nothing to limit it, so a stopped Ollama
would quietly send dozens of requests a day to Gemini and burn the
20/day/model free tier that `Ctrl+F9` and `F2` depend on. Those are keys you
press on purpose; this is a pass you never asked for on any particular
sentence, and it does not get to starve them. No local model means no
repair, and your transcript stays exactly as pasted.

**It runs in front of your paste, and it costs you seconds.** The rule that
makes that bearable is the placeholder:

> **`...` on screen = not finished. Text on screen = finished, and it will
> not change again.**

<details>
<summary>It was tried the other way round, and moved back</summary>

For a while the transcript pasted instantly and the repair rewrote it on
screen a few seconds later — measurably faster to first text, and the
in-place rewrite was built with a keyboard-hook guard so it could never
overwrite anything you typed.

It was moved back for a reason no benchmark shows: **a sentence that might
still rewrite itself in three seconds is a sentence you cannot send.** You
cannot tell whether what you are looking at is the final version, so you
wait anyway — without knowing what you are waiting for, or when it is over.
The seconds saved were not saved at all.

So the pass sits inside the placeholder, where the waiting is visible and
bounded (`max_wait_s`, 10 s), and the text that lands is done.
</details>

#### Which model — measured, not assumed

This pass uses its own model, separate from the translate key's, and it has
to be pulled:

```bash
ollama pull gemma3:12b
```

Nothing breaks if you skip it — the pass logs that the model is unavailable
and the raw transcript stays exactly as pasted — but you get none of the
benefit below.

Run on the 11 recordings in `recent\` that carry a `corrected` field: real
dictations where the intended words are known, because you typed them with
Ctrl+F8.

| model | WER | vs. raw | better / worse | rejected by `_is_safe` |
|---|---|---|---|---|
| *raw transcript* | 14.2% | — | — | — |
| **`gemma3:12b`** | **10.9% / 10.7%** | **−3.4 pt** | **4–5 / 0** | 1 |
| `qwen2.5-coder:14b` | 13.8% | −0.4 pt | 4 / 2 | 1 |
| `llama3.1:8b` | 16.0% | **+1.8 pt** | 3 / 3 | 5 |
| `aya-expanse:8b` | 15.7% | +1.5 pt | 0 / 2 | 9 |
| `dictalm2.0-instruct` (Hebrew) | 14.2% | ±0 | 0 / 0 | **11** |

`gemma3:12b` was run twice (the backends sample at temperature 0.2, so treat
one clip's difference as noise). Two results are worth keeping:

- **`llama3.1:8b` — what this used to default to — makes your transcript
  worse than leaving it alone.** `_is_safe` threw out 5 of its 11 replies,
  and the 6 that got through still split 3 better / 3 worse: a one-word
  substitution is a tiny word-level edit whichever word it was, so the
  safety net cannot tell a repair from a confident mistake.
- **The Hebrew-native model lost outright.** `dictalm2.0-instruct` was the
  obvious bet and it will not hold the output format — one reply came back
  158 words against a 2-word transcript. Every one of its replies was
  thrown away by the safety check. General instruction-following beat
  language specialisation.

`gemma3:12b` averages 4.7-5.5 s and peaks at 6.2 s, so a dictation now takes
roughly **7 s end to end** instead of 2. `max_wait_s` is 10: past it the
unrepaired transcript is pasted and the reply discarded. `warm_up` sends one
throwaway request at startup so the model is in VRAM before a dictation needs
it (76 s cold vs 2.5 s warm) — without it, your first dictation of the
session pays that and loses the repair to the timeout.

**Smaller is not faster enough to be worth it**, measured on the same clips:
`gemma3:4b` came in at 18.9% WER — *worse than no pass at all* — and
`qwen2.5:7b` at 17.6% against a 17.9% baseline, both at 3.0 s. Saving 2.5 s
costs the entire benefit.

> **VRAM.** `gemma3:12b` is ~8.5 GB and the two Whisper models are ~6 GB. On
> a 16 GB card that fits with little to spare — drop to `gemma3:4b` if
> Ollama starts spilling layers to the CPU.

<details>
<summary>An idea that did not survive measurement: gating repairs on Whisper's word confidence</summary>

`_is_safe` can tell a rewrite from a correction but not a *justified*
substitution from an unjustified one. The obvious refinement is to let the
decoder arbitrate: faster-whisper reports a probability per word (this app
already computes them, for `hallucination_silence_threshold`), so a word
decoded at p=0.99 looks like one no model should be allowed to "fix".

Built and measured on the same 11 clips, refusing any substitution on a word
scored above a floor:

| | no veto | floor 0.85 | floor 0.95 |
|---|---|---|---|
| `gemma3:12b` | 10.7% | 12.4% | 12.4% |
| `llama3.1:8b` | 13.9% | 16.2% | 16.2% |

It makes **both** models worse — including the weak one it was designed to
rescue. The premise is simply false on this fine-tune: the repairs it
blocked were the correct ones, so Whisper is confidently wrong often enough
that its confidence cannot gate anything. Removed rather than shipped
switched off; a knob that only harms whoever turns it on is worse than no
knob.
</details>

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
  - **Detection is the mechanism, not a fallback** (`auto_language`, on).
    The hold key does not declare a language, so an utterance that is
    *entirely* English — the one case the Hebrew fine-tune transliterates
    (`Mac mini` → `מקמיני`) — goes to the general model instead. English
    wins only at confidence ≥ `english_threshold` (0.8); everything below
    that, in any language, stays Hebrew.

    The bar is high because short Hebrew clips get mis-read as
    Portuguese/Russian/Dutch at 0.16–0.73, and one *Hebrew* sentence once
    scored `en 0.57` — which is the number that originally argued for a
    dedicated key. Re-measured 2026-08-20 against the 50 real recordings
    in `recent\`, comparing what each model actually **produced** rather
    than trusting the label: 8 crossed the bar, all 8 were genuinely
    English (6 strictly better, 2 identical), and no Hebrew recording
    crossed it. Cost: one extra encoder pass, median 0.18 s per dictation
    (p90 0.26 s); the ~2 s first pass is spent at startup instead.
  - **A dedicated English key still exists** (`english_hotkey`, off).
    Holding it forces the language with no detection at all. Redundant
    once `auto_language` is on, and kept for anyone who would rather
    declare it by hand.
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
| `hotkey` | `right ctrl` | push-to-talk key, Hebrew **or** English (`f9`, `scroll lock`, ... — see names in `hotkey.py`) |
| `auto_language` | `true` | the hold key declares no language and the model decides per utterance, so one key covers both. `false` pins it to Hebrew. Costs one encoder pass, median 0.18 s |
| `english_hotkey` | `""` | off — `auto_language` covers this. Set it to hold for English with no detection involved; avoid `right alt` (releasing Alt alone pops the menu bar and steals focus before the paste) and `right shift` (holding 8 s triggers Windows FilterKeys). Refuses a modifier: it is held, not tapped |
| `translate_hotkey` | `ctrl+f9` | **tap** to turn the selection — or the whole field — into English; `""` disables. Must differ from the two hold keys. Bare `f9` is Edge's Immersive Reader, Excel-for-the-web's recalculate and every IDE's breakpoint — see [Which keys are safe](#which-keys-are-safe) |
| `punctuate_hotkey` | `f2` | **tap** to put the punctuation into the selection — or the whole field. Whisper transcribes sounds, not sentences. `""` disables. Was `f7`, which pops Chrome's caret-browsing dialog. See [Punctuating what you just dictated](#punctuating-what-you-just-dictated) |
| `latch_hotkey` | `left` | **tap while holding** the hotkey to lock the recording on, so a long dictation isn't a long hold; tap again to finish. Swallowed only while it does this. `""` disables. Avoid `right shift` — Ctrl+Shift switches keyboard layout |
| `correct_hotkey` | `ctrl+f8` | fix the transcript where it landed, then **tap** this; it reads the correction off the screen and learns the difference. `""` disables. Shares its trigger with `lookup_hotkey` on purpose — both keys only read. See [Teaching it the words it gets wrong](#teaching-it-the-words-it-gets-wrong) |
| `lookup_hotkey` | `f8` | **tap** to see what the selection means in a small box that changes nothing — the read-only key, for a web page, a PDF or a field you cannot edit. `""` disables. It gets the cleanest bare key on the board because it is the most-tapped. See [Looking something up](#looking-something-up-without-changing-it) |
| `pause_hotkey` | `insert` | **tap** to make every key above inert without unloading anything, and again to resume. The one key that still works while paused. `""` disables. `scroll lock` is cleaner (nothing binds it anywhere) if you can spare the LED. Refuses a modifier. See [Pause](#pause-and-why-it-is-not-stop) |
| `auto_pause_fullscreen` | `false` | pause by itself while a game or presentation owns the screen, and resume when it lets go |
| `[vocab] enabled` | `true` | feed the learned vocabulary to the decoder as hotwords |
| `[vocab] terms` | your stack | hand-written seeds, ranked ahead of anything learned |
| `[vocab] max_terms` | `40` | cap on the hotword list; faster-whisper truncates at 223 tokens and over-prompting makes Whisper emit the words unbidden |
| `[vocab] replace_after_hits` | `2` | corrections of the same garble before it is also repaired after the fact. `1` would let one slip in the box start rewriting a word you really say |
| `[vocab] keep_audio` | `50` | recordings kept in `recent\` so `--benchmark` can replay them. `0` = keep none |
| `[polish] when` | `always` | `never` \| `known` (only when a learned garble is present) \| `always`. Adds ~5 s to every paste; worth it when it fires |
| `[polish] min_chars` | `20` | below this there is no context to reason from |
| `[polish] ollama_model` | `gemma3:12b` | measured best of five on real clips; `""` = reuse `translate.ollama_model` |
| `[polish] max_wait_s` | `10` | longest your paste may be held up; past it the unrepaired transcript is pasted |
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
| `[translate] ollama_url` | `http://127.0.0.1:11434` | where Ollama listens. The literal IP, not `localhost`: that name resolves to `::1` first here and Ollama is IPv4-only, so every call paid ~2.05 s for a refused connection before falling back (measured 2026-08-19) |
| `[translate] timeout_s` | `30` | Gemini request timeout |
| `[translate] ollama_timeout_s` | `150` | much larger on purpose: 76 s cold vs 2.5 s warm while the model loads into VRAM |
| `[translate] settle_ms` | `120` | how long the focused app gets to answer a copy (the punctuate key reads this one too) |
| `[punctuate] max_chars` | `5000` | same guard as `translate.max_chars`: with nothing selected the key takes the **whole** field |
| `[punctuate] prefer` | `gemini` | `gemini` \| `ollama`. Gemini punctuates better; `ollama` if you tap the key after every dictation and don't want it eating the 20/day/model translation also needs |
| `[punctuate] ollama_model` | `""` | `""` = reuse `translate.ollama_model` |
| `[punctuate] nikud` | `false` | also add Hebrew vowel points, not just punctuation. The same letter-for-letter safety check covers it |
| `[lookup] hebrew_share` | `0.34` | share of Hebrew **words** — not letters — at or above which a selection is sent to English rather than to Hebrew |
| `[lookup] both_ways` | `true` | off, a Hebrew selection gets the soft "nothing to do" note instead of coming back as English |
| `[lookup] max_chars` | `5000` | above this it refuses and spends nothing. A 100-word paragraph already costs 7.4 s locally, and by then you wanted Ctrl+F9 |
| `[lookup] prefer` | `ollama` | `ollama` \| `gemini`, and deliberately the **opposite** of the other two keys: this one is tapped while reading and would eat the whole 20/day/model tier that Ctrl+F9 and F2 depend on |
| `[lookup] model` | `gemma3:12b` | the Ollama model. Already resident for `[polish]`, so it costs no extra VRAM. Not `qwen2.5:7b` — measured, it answered `?");` for `brittle` |
| `[lookup] cold_to_gemini` | `true` | when the local model is not loaded, send *that one* lookup to the cloud and warm the local one in the background rather than make you wait 24.4 s |
| `[lookup] keep_alive` | `"30m"` | how long Ollama keeps the model in VRAM after a lookup. The 5-minute default expired mid-reading-session and cost 23.19 s on the next tap. Shared with `[polish]`, Ctrl+F9 and F2 — it belongs to the loaded model, not to this key — so raising it pins 7.6 GB of the card for that long |
| `[lookup] strip_niqqud` | `true` | drop the vowel points the model sometimes decorates its Hebrew with (8 marks in 4 runs out of 4 on one input). Combining marks only: the maqaf is left alone, or `בית־הספר` would come back welded into `ביתהספר` |
| `[lookup] dwell_ms` | `12000` | **dead — nothing reads it.** The box waits to be closed, by its `×` or by `Esc`. A box that took itself away on a timer was the complaint this key's rewrite answered, and a timer you cannot tell from a bug is worse than no timer |
| `[lookup] max_width` | `460` | pixels. 60 words wrapped to 9 lines measured 512 px wide unbounded |
| `[lookup] max_height` | `520` | pixels; a 22-sentence paragraph made an 896 px window, taller than some work areas. Overflow is trimmed with an ellipsis |
| `[lookup] cache_entries` | `500` | answers kept in `lookup_cache.json` (~134 bytes each). A repeat is 0.00 s and one saved request; only selections under 200 chars are stored. `0` = no cache |
| `[lookup] skip_consoles` | `true` | refuse in console windows, where the copy chord becomes a real Ctrl+C for whatever is running there (reproduced 5/5) |
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
