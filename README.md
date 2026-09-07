# DeskIT

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

**Something on screen worth keeping? Press `Win+Shift+S`.** Yes, Windows'
own key — this app takes it. Drag a box or
Shift-drag a lasso and the picture is on your clipboard before you let go.
Then it gets out of your way: a small card appears in a corner for five
seconds with a thumbnail of what you took, and clicking it opens the editor
— crop, arrow, highlight, blur out anything private, or hand the whole
thing to the ask key. Ignore the card and it goes away. `ctrl+f12` records a region to mp4 instead,
and the controls do not appear in the video. See
[Capturing the screen](#capturing-the-screen-winshifts-and-recording-it-ctrlf12).

**Want a picture of something in the room? Tap `ctrl+f6`.** The webcam
opens in a card with a shutter under it; press space and the photo is on
your clipboard and in `captures\` before the flash is over, then opens in
the same editor. The camera is closed again the instant the shutter
fires. See [A photo from the camera](#a-photo-from-the-camera-ctrlf6).

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

**Normal use: double-click `DeskIT` on the Desktop** (or
`DeskIT.vbs` in this folder). It runs in the background with no
console window and no taskbar entry. **Two rising beeps = it is listening.**
To quit: double-click `Stop DeskIT` — two falling beeps confirm.

Open **`Dashboard.vbs`** and drive all of it from one window — see
[The dashboard](#the-dashboard) below. Double-clicking `DeskIT`
while it is *already* running opens the dashboard too, instead of the old
"already running" complaint.

**The typeface hands itself to Windows now (`fonts.py`).** The app draws
in **Rubik**, which is designed for Hebrew and Latin together and is
vendored in `fonts\`. It was not actually drawing in it: measured
2026-09-06, on this machine, with all four files on disk, registered
under `HKCU\...\CurrentVersion\Fonts` by `install_fonts.py` seventeen
days earlier and a reboot since — a fresh process asking GDI for the
family `Rubik` got **Arial** back, so `ui.pick_face(["Rubik"])` returned
`Segoe UI` and the whole window had been in the fallback face without a
word about it. A registry entry is a promise to the next logon, not an
answer to `CreateFontW` in *this* process. So `fonts.load()` calls
`AddFontResourceExW(path, FR_PRIVATE, 0)` on every file in `fonts\`
(and on any `Rubik*.ttf` already in the per-user font folder) at the
import of `ui.py` and of `visual_qa.py`, before anything asks for a
face. `FR_PRIVATE` means nothing is installed, nothing is written, no
`WM_FONTCHANGE` goes out to every window on the desktop, and the face is
gone when the process ends — four calls, under 3 ms together, idempotent,
and it never raises: a missing folder or a GDI that says no is a log line
and Segoe UI, because a typeface is not worth a dictation.
`install_fonts.py` still works and is still worth running once, but the
app no longer depends on it.

Two consequences of that face, both measured. **Rubik draws Hebrew ~13%
smaller than Segoe UI at the same nominal size** (93% of nominal against
107% at 15 px), so every size in the window went **+2 px** and every row
+20% — swapping the face without that makes the app smaller and harder to
read, which is not what a redesign should feel like. And **GDI gives back
exactly two Rubik weights, 400 and 700**: the four files in `fonts\` are
cuts of one variable font, so `Rubik Medium` and `Rubik SemiBold` are
real family names that draw at regular weight (advance 104 px against
Rubik 700's 108 for `מבנה חדש` at 24 px). Emphasis in this window comes
from size and from the accent, never from a Medium that does not exist.

The dashboard can start *and* stop the app, so it can replace both Desktop
shortcuts on its own; autostart is a separate shortcut in the Startup
folder and is unaffected either way. Its icon is `icon.ico` — run
`make_icon.py` (needs Pillow) to regenerate it. **The mark is a dalet
drawn as a desk**: a tabletop with one leg hanging from its right end,
the top's edge just past the leg, and the lamp — the same gold dot the
status dot is — sitting above the left of the top, with two light arcs to
its right. It is the app in one letter: a desk with a lamp on it, and the
lamp is the part that is lit. There are **two cuts** of that one drawing
in the file, because 16 px cannot hold what 256 px can: at 48 px and up
the lamp keeps its glow and the two arcs; below 48 both go, and what is
left is the desk and the dot. The whole thing is solved on the design's
own 64-unit grid, drawn at 4× and downsampled with LANCZOS, into
`icon.ico` at 16/24/32/48/64/128/256 and `icon.png`. The alef that used
to be knocked out of a microphone is gone with the microphone.

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

**Or from the dashboard.** Settings → **The app** names what is running
and offers one *Use this* button per other version. Switching from there
is the same stop–flip–restart, with progress shown in the window, and the
running version's name is on the foot of **Waiting** so "which one am I
on?" never needs a click. It used to be a screen of its own, one of nine
in a rail; ten days of logs hold **not one line about switching**, so it
is now three rows in the block that also holds Stop and the cue sounds.

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

**Six places along the top, and no rail.** The window had grown a left
rail of nine rows — Overview, History, Review, Awake, Notify, Keys,
Version, Problems, Settings — and the rail was 212 px, 18% of the window,
spent on a menu of screens that saw **2.1 actions a day between them**.
Ten days of logs, counted 2026-09-06: **968 actions at a key, 333 at a
card, 21 in this window**. Nine of those ten days had zero or one. All 21
were: nine review verdicts, four dismiss-alls, five screens/night
toggles and three key rebinds, in four bursts — this window is opened to
*catch up*, not to browse, and then closed. So the nine rows are six
words on a 56 px bar:

- **Home** — a summary, and nothing more: what wants an answer (the
  newest three, whatever kind they are), one line saying what else is
  waiting and where, and one line each for the rest of the day. It
  opens here and it does not need scrolling.
- **Corrections** — every proposal the second reading is waiting on,
  and the words it has already learned, side by side.
- **Problems** — what you reported, the questions the weekly routine
  asked back, and the branches it left to publish.
- **Said** — `transcripts.log` read back, with the search and the six
  filters, twenty-five rows at a time.
- **Keys** — every binding, lit on a picture of a keyboard.
- **Settings** — every line of `config.toml`, plus the three things that
  were really settings all along.

It took four goes to get there and every one of them was his. Nine
rail rows became four places (Waiting, Said, Keys, Settings); he said
Waiting and Said are one desk, so they became one scrolling page and
three places; he read that page and said **"Home should be a summary,
and then maybe add more tabs. Home is a summary of everything, and to
get more information, I don't need everything on my home screen"** —
so the home says what wants him and what happened today, and every
kind of thing has a place of its own to be read in full.

The bar carries the mark at the left (the wordmark went with the extra
places — the title bar says DeskIT one line above it), the six places
in the middle with a 2 px gold underline on the one you are on, and at
the right the state as a sentence — the dot in its live colour, the word
(*Off*, *Starting*, *Listening*, *Recording*, *Locked on*,
*Transcribing*, *Paused*), the uptime — and **three** buttons:
**Screens off** (Screens on while they are dark; only while the app
runs, since the screens are the running app's to put out), **Pause**
(Resume when it is paused, Start when it is off), and **Stop**. Screens
off was a small gold link in the home's footer and he could not find
it; Stop was on Settings → The app and he could not find that either
(*"I don't have a button to shut down the model, I only have a button
to pause it"*). The reason Stop was buried has not gone away — it costs
25 seconds of model loading to undo — so **it arms before it fires**:
the first press says *Stop again*, the second one quits, and anything
else disarms it. "Is it on?" is the question this window exists to
answer, and it is answered on every place rather than on one of them.
The window is 1160×720 (it was 940×648) and still fixed, which is what
lets every bitmap be cached.

**The home is the window's whole job, said in one sentence.** *"Five
things want an answer."* — or *"Nothing is waiting."*, with "Nothing else
on the desk needs you right now." under it. Then ONE card holding the
merged pile: unread notifications (Go there / ×), second-reading
proposals (the sentence with the changed word on a gold-soft pill, the
reason under it, Yes / No), open problems (Fixed / Close), and the weekly
routine's questions (Answer / Later) — newest first, whatever kind they
are, **the newest three and no more**, in a card exactly as tall as its
rows. Under it, one line of counts — *5 corrections · 1 problem* — and
each count is the door to the place that holds them, because a number
with nowhere to go is a number nobody can act on. Under that, one faint
line about finishes being held until their session goes quiet.

The card was a fixed rectangle with a scroller inside it and a "+N
more" that grew it, and his photograph of that on 2026-09-07 was rows
floating in the middle of an empty card — the card grew and the
scroller inside it did not. It is drawn from its rows now.

The merge is the finding, not a layout preference. Those four things used
to be four screens; they are four sources of *one* thing — something is
waiting for an answer — and which of the four it is matters far less than
which is newest. Every one of the 21 window actions in ten days was
somebody catching up on a backlog of them. A store that is absent, off or
unreadable contributes nothing and the other three still draw:
`[questions]` is not in `config.toml` on this branch, so that section
simply is not there.

Under the pile, **the rest of the day, one line each**: **Said** (the
last dictation, drawn RTL, with the time and "N today"), **Took** (the
last capture and the folder it went to), **Looked up** (the last term →
its meaning). A line whose store does not exist is skipped rather than
shown empty, and clicking the Said line opens the **Said** place. A
wheel notch anywhere on the page is 48 px rather than a fifth of the
screen — it used to jump, and he called it "laggy and ugly"; a tick
now costs about 4 ms. Under the page, fixed, a footer under a rule: the
awake state, whether the phone is live, which version is running, how
many words it has learned. Four facts that are true whichever place is
open, so they read as a footer and not as a fifth thing to do.

Two controls sit beside the title because that is where their subject is:
**Report a problem** (which also says its key, `Ctrl+Alt+R` — all five
reports in ten days were filed from the key), and **Dismiss all** with
`Ctrl+Alt+M` on a key cap beside it. The key cap is there because that
key has been pressed **zero times** — two separate counts of the logs,
about ten days each, and zero in both; if the window is going to keep the
button, it can at least teach the key. "The whole list" at the bottom right opens the things that need
more than a line — a question with its two-to-five answers and its box, a
report with its evidence and its screenshot, a weekly branch with the one
button that publishes it.

**Settings is the file, on tabs a person can find things on.** Seven of
them: **General** (the dozen things you actually change — where speech
becomes words, the microphone, whether it notices English, punctuation,
fixing misheard words, the learned words, the marker, the key card, the
game pause, the dot, reporting a problem), then **Dictation**, **Text**,
**Screen**, **Cards**, **Phone**, and **The app**. Every row is the same
row: a plain title, one plain sentence under it, and its control at the
right — a switch for a `true`/`false`, a menu with names on it where a
value names a model or a mode ("Groq — fast, free tier", "Only taught
words"), a field for a number or a word, and an "In the file" button
for the two things a field cannot hold, a list and a Hebrew string (Tk
has no bidi caret). A name wider than its menu is cut with an ellipsis
rather than at the menu's edge.

**Every line of `config.toml` is drawn exactly once.** `settings.TABS`
names by hand the fifty-odd lines worth a sentence and a menu, and
`settings.TAB_SECTIONS` says which tab owns each *section* of the file —
Dictation owns `[audio]`, `[polish]`, `[local]`, `[review]` and so on,
Text owns `[punctuate]`, `[translate]`, `[lookup]`, Cards owns `[hint]`,
`[notify]`, `[problems]`, `[shelf]` — so every remaining line of a
section is drawn on that tab, one group per section, titled and
explained with the plain words in `settings.WORDS` rather than the
file's own `latch_max_seconds` and its measured comment. A section no
tab owns lands on an **Advanced** tab that only appears when it has
something to show, so a section added to the file is on the screen the
moment it is saved. A test holds the tabs and the Keys screen to drawing
every line once and nothing twice.

This replaced two things from the day before, on the owner's word
(2026-09-07): a first tab that said forty settings as *sentences* with
the controls inside the words, and a last tab, **Everything**, that
repeated the whole file in the file's own words. The sentences were
clever and he said "make normal settings, no need to be clever" —
and their controls, parented to the sheet rather than the card, painted
over the tab bar when scrolled. Everything he answered in one line: "if
there is Everything, it is already somewhere else, so I do not need
it." One line, one place. The file's own names and comments stay in the
file — and in the search: the magnifier at the right of the tabs finds a
line by its plain title, its sentence, its section, its dotted name or
the comment beside it, and the cross brings the tabs back.

**The app** holds the three blocks that used to be rail rows, because
none of them is a place you go — each is a thing you check and
occasionally flip: **Awake** (the status rows, Check status, Screens
off/on), **The app** (which version is running and the one-click switch,
Stop, Send a test, and one Play button per cue kind — a filed complaint
answered: *he could not tell the twenty sounds apart*, and the answer to
that is not a louder cue but a Play button beside the name of the thing
the cue is FOR), and **Files** (the four things worth opening, named for
what they are: *Everything you said*, *The app's diary*, *The settings
file*, *The app's folder*), followed by the `[awake]` lines. **Phone**
opens with the endpoint, the link and Copy, then the `[server]` lines.

Worth knowing before touching any of it: **191 settings in 20 sections
produced exactly three writes in ten days**, and the three cancel out —
he rebound one key to `h` and back to `ctrl+f9` six seconds later. A
screen nobody edits is a screen that should be readable, and a wheel
tick on any tab now costs 5–9 ms.

Writes go through `config.set_values`, the line editor that keeps the
comments. While the app runs they go through the app (`set_option`, over
the pipe), so the file has one writer at a time and the app can take the
change without a restart where it knows how — `[punctuate]`,
`[feedback]`, `[vocab]`, `[polish]`, `[translate]`, `[review]`,
`[hint]` and `[shelf]` (those two cards are rebuilt), and the paste chord
and delay. Anything else is written all the same and the reply says so:
"saved — it applies the next time it starts".

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⌐  Home  Corrections  Problems  Said  Keys  Settings                 │
│    ────       ● Listening 4h 40m [☾ Screens off] [ Pause ] [ Stop ]  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Five things want an answer.               ⊗ Report a problem        │
│  Nothing else on the desk needs you right now.  Dismiss all Ctrl+Alt+M│
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ ♪  Claude Code · just now                                      │  │
│  │    Claude needs a permission — allow Bash…   [Go there]  [×]   │  │
│  │ ✓            Second reading · it heard 1 word differently      │  │
│  │              …‹the sentence, right-aligned, one word on a pill› │  │
│  │                                              [ Yes ]  [ No ]   │  │
│  │ ⚠            You reported this on 6 Sep                        │  │
│  │              …‹the line he typed, right-aligned›                │  │
│  │                                            [Fixed]  [Close]    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  5 corrections · 1 problem                                           │
│  2 finishes held until the session that sent them goes quiet.         │
│                                                                      │
│  THE REST OF THE DAY · ONE LINE EACH                                 │
│  Said       23:46   …‹the last dictation, right-aligned›   1 today   │
│  Took       22:27   shot 2026-09-06 22-27-55.png           1 today   │
│  Looked up  23:46   leverage → מָנוֹף                                  │
│                                                                      │
│  ──────────────────────────────────────────────────────────────────  │
│  ☾ The screens are off since 22:46.                                  │
│                    phone live · running fast · 38 words learned      │
└──────────────────────────────────────────────────────────────────────┘
```

The window is drawn rather than assembled: Tk 8.6 cannot round a corner
or anti-alias one, so every card, pill, switch and key cap in it is a
pre-rendered Pillow bitmap with widgets sitting on the flat middle of it
(`ui.py`). The palette is **LAMPLIGHT** — one lamp on a dark desk, the
app being the light rather than the furniture — and it is the same table
the cards, the dot, the boxes and the phone page draw from. `SKIN.md`
holds it, with the contrast ratio behind every colour.

### Everything you said, on its own place

**Said is `transcripts.log`, read back**, on a place of its own,
reached from the bar or by clicking the Said line of the home. It
opens on **twenty-five rows** and grows by twenty-five per press of
*Show more* — a hundred at once was, in his words, "a lot to scroll
and it's a nightmare". It was called History, and
"history" appears **zero times in 11,046 lines of log** — nothing that
screen does is logged and no window action was ever recorded there, so
the name was renamed to the thing it holds. The last hundred entries,
newest first, one row for each thing *you did* rather than one for each
line the code wrote:

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

A search box over the top and six filter chips under it (All, Dictation,
Translated, Punctuated, Looked up, Learned, Failed); the search matches
what you said, what it answered, and which engine answered. **Click a row
to copy it** — the whole text, not the two lines the row had room for.

**The vocabulary is beside the list, not behind a tab.** A panel down the
right says how many words it has learned to hear your way, the key that
teaches it one (`Ctrl+F9`), and the pairs it learned lately as
`heard ← meant` pills — the arrow points left because the pair is Hebrew.
It had no screen of its own before, which is a strange thing for a table
that 389 repair passes read; it is now in the same eyeful as the
sentences it changes. Under it, the line that says where those words go:
the best of them ride into the decoder's prompt before it listens, forty
at a time.

Nothing here writes to the log; a malformed line is skipped rather than
repaired. The log is still the record, `Open transcripts.log` is still
there at the foot of the place, and everything older than the last
hundred is still in it.

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
and the second layer stayed hidden until a mixed sentence landed in the
window. The chrome stays English on purpose: a label is one direction
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
  dashboard's **Settings** place. **Off by default**: it is the one
  setting that can stop dictation without anyone asking it to, and "my
  hotkey stopped responding" is a much worse half hour than tapping the
  pause key yourself. It only ever un-pauses *its own* pause.

### The keys, drawn on a keyboard

**Press a key and the board answers.** While the Keys place is up, a
real press on the keyboard lights the cap under your finger and the
panel says what lives there — *Report a problem · tap · chord* for `R`,
since `ctrl+alt+r` is on it — or that the app never takes it: *"Q is
yours."* The owner's ask, verbatim: "if I press R, for example, it
would tell me what it does." Tk reports the press with the Windows
virtual-key code, `keyboard.cap_for_vk` turns it into the cap, and the
modifiers come back unsided the way the caps are named. Never while
the key dialog is listening for a new binding (that press is the
dialog's), and never on another place, where a key press is typing.
Clicking a cap does the same thing.

**Keys is a picture of a keyboard with your bindings lit on it.** It used
to be a row per binding — "Translate (tap) `[F8]`" — in a scrolling
column, which is a lookup table for a thing that is already spatial. You
do not remember that translate is F8; you remember where your finger
goes. And the question the screen actually has to answer, *which keys has
this app taken from me*, was sixteen separate readings of that column.

Eighty-seven caps, an ANSI tenkeyless board, one Pillow image and one hit
table. Everything is measured from a single unit `u` (one 1× cap), so the
board fits whatever room the screen has: at `u=40` it is 746×278, which
leaves 346 px for the panel beside it and the room under it for the
bindings, three to a line. The whole board is one image — 26–32 ms to
draw at `u=43`, 41 ms at `u=60` — and a click redraws all of it in
~30 ms, under a frame, which is why there is no partial-repaint
machinery in `keyboard.py` at all.

Five ways a cap can look, and the legend says all five: **held** (down the
whole time it works), **tapped** (fires and still reaches the app
underneath), **chord** (the modifier lit softly, the key fully), **only
sometimes** — a broken edge, which today is `Esc` — and **unlit**, which
means the app never sees it. Under the board, every binding with its key
cap and what it does; under those, one quiet line:
anything not lit is untouched, and the keys this app *cannot* take —
the punctuation caps — have no code Windows can bind, which is exactly
why they are the safe ones. **Click a cap** and the panel at the right
tells you what that key does and offers to change it, through the same
capture dialog described below.

Four things this got wrong first, all of them worth writing down because
they are all invisible until you look at the drawing:

- **One cap can carry two bindings.** `translate_hotkey = "f8"` and
  `lookup_hotkey = "ctrl+f8"` are the same physical key. The map has to
  be `{cap: [binding, ...]}`; a dict of one silently lost *look up*.
- **`hotkey.parse_binding` returns UNSIDED modifier VKs** — `0x11` for
  ctrl, not `0xA2`. A cap map that calls the left one "left ctrl" never
  matches it, and nine chords lit their letter with no modifier at all.
- **Pillow has no font fallback.** Rubik holds no `U+2190..2193`, so every
  arrow cap drew as `.notdef` — while the *same* arrow inside a
  `ui.KeyCap` looked fine, because Tk falls back per glyph and PIL does
  not. The four arrows are drawn, not typed.
- **`Esc` is not in `config.toml`.** It cancels a running recording — it
  is watched by the recorder, not registered as a hotkey — so it is named
  on the board by hand and drawn with the broken edge that says "only
  sometimes".

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

Nine that survive, best first:

| key | free in | taken by | one-handed? |
|---|---|---|---|
| **`f8`** | Chrome, Edge, all seven Google apps, Word / Excel / PowerPoint / Outlook / Teams on the web, WhatsApp Web, Spotify, the NVIDIA overlay | a console (history search), VS Code (next problem) | **yes** — the right edge of the F5–F8 block is a tactile landmark, so it is findable blind |
| **`ctrl+f8`** | all of the above, *plus* the console and VS Code | nothing found | yes, with the **left** ctrl |
| **`ctrl+f9`** | the same list | nothing found | yes, with the **left** ctrl |
| **`ctrl+f6`** | Chrome and Edge, measured in the same probe — bare F6 walks the caret into the address bar, and the chord does not | nothing found | yes, with the **left** ctrl |
| **`win+shift+s`** and any Win chord | nothing, because it never gets there — a Win chord is the one kind this app **swallows** (measured: the Snipping Tool does not open, and a bare Win tap still opens Start) | Windows itself, until you take it | **yes** — it is the shortcut your hands already know |
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
- **A small dot sits in the bottom-right corner while the app runs**, just
  above the taskbar — blue when idle, red while recording, red and
  breathing while a recording is *locked on*, amber while transcribing,
  grey while paused. If you ever saw the loading box stay on screen *and*
  no dot appear, that was one bug, not two: `quit()` in Tkinter sets a
  flag shared by every Tk window in the process, so about half the time
  the splash's "close" closed the dot instead and left itself running.
  Neither overlay calls `quit()` any more (`overlay._pump_until`), and a
  test asserts they never will. It is how you tell a running app from one
  you never started or already closed. **The disc is a button**: click it
  and the shelf opens beside it, exactly what `ctrl+alt+d` does; click it
  again and the shelf closes. Only the disc takes the click — the glow
  around it lets the mouse through to whatever is underneath. It lived in
  the top-right until 2026-09-07 and was click-through as a whole there,
  because that corner is the close button of every maximised window;
  `[dot] corner = "top-right"` puts it back, button and all. Turn it off
  with `indicator = false`.
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

## Using the other keys while you are still talking

The feature keys used to disappear the moment you started dictating. Press
`Ctrl+F10` mid-sentence and nothing happened at all — not an error, not a
beep, as if the key did not exist. Hold Right Ctrl and press it and you
lost the recording instead. That is fixed: the keys work **at the same
time** as a dictation, and which ones depends on which hand you have free.

**Locked (← tapped): everything works.** Ask about the screen, take a
screenshot, start a screen recording, open the camera, translate,
punctuate, correct, look something up — all of it, while the recording
keeps running. Locking the key is what frees your hands, so this is the
mode the whole thing is built around.

**Holding Right Ctrl: the four screen keys work.** `Ctrl+F10` (ask about
the screen), `Win+Shift+S` (screenshot), `Ctrl+F12` (screen recording) and
`Ctrl+F6` (camera) all fire without touching the recording. The four that
read or rewrite **the text at your cursor** — translate, punctuate,
correct, lookup — make the "not now" sound instead and say why in the log.
With one hand pinned to Right Ctrl you have no selection for them to work
on, and your cursor is where the transcript is about to land.

Things that follow from it, all of them deliberate:

- **A key the app has bound never cancels a recording any more.** Only an
  unbound key does. `Ctrl+C` mid-hold still throws the dictation away —
  that is the rule it was bought for — but it now happens on the `C`
  rather than on the `Ctrl`, because every chord starts with a modifier
  and cancelling on the way down made `Ctrl+F10` unpressable.
- **Right Ctrl is a hotkey, not a Ctrl, while it is holding a recording
  open.** So use the LEFT Ctrl for `Ctrl+F10` while dictating. This is
  also what makes `Win+Shift+S` reachable at all mid-dictation, and what
  stops a bare `F8` quietly becoming `Ctrl+F8`.
- **Esc goes to whatever is on screen.** With a selector, a capture
  overlay, a camera card, an ask card or a lookup box up, Esc closes that
  and leaves the recording alone. Press it again with nothing on screen
  and it discards the locked recording, as before.
- **Where your words go is decided when you START talking.** Open the ask
  card in the middle of dictating an email and the email still lands in
  the email — the card gets the *next* thing you say. Start talking with
  the card already up and it is a question, as always.
- **Your screenshots have your whole screen in them, ours included.** The
  status dot used to be excluded from every capture on the machine. That
  hid it from *your* grabs too, which is how a card you wanted to send
  somebody became a card that vanished the moment you reached for the
  key — so as of 2026-09-04 nothing of ours hides from a screenshot
  except the recording bar. What our windows do instead is step off the
  screen once the picture has been frozen, so they are in the shot without
  standing in the way of the drag. That last part is finished for the
  **notification card** and not yet for the hint and review cards: those
  two are in your screenshots now, but one that arrives while you are
  mid-drag can still land on top of the selection and take the click. They
  always could — hiding them from captures never changed where they sat —
  so this is a corner left to tidy, not something the change broke.
- **The card will not read an answer out loud while the microphone is
  live** — it would be recorded and transcribed as if you had said it.
  The Speak button is there when you have finished.
- **One clipboard, one queue.** A screenshot taken in the half-second a
  transcript is being pasted used to arrive *as* the paste — the picture
  in your document instead of your sentence (39 times out of 40, measured).
  Everything that touches the clipboard now takes its turn.
- **And the screenshot is still on your clipboard afterwards.** The paste
  used to be able to save and put back text only, so a transcript landing
  a second after a screenshot replaced it. Take the shot mid-sentence and
  both survive.

One collision is left, and it is the documented behaviour of the latch
rather than a bug: **tapping Right Ctrl while locked finishes the
recording.** So reach for the left Ctrl when you want a chord — the right
one will end the dictation and then the rest of the chord fires on its own.

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

### Or on every dictation, with one switch

`[punctuate] auto = true` — or the first row of the dashboard's Settings
screen, **Punctuate every dictation** — runs the same pass on every
transcript on its way to the cursor, after the repair pass and before the
paste, so the key is never needed. Off by default, and there is no
warning next to the switch: what it costs is written here instead.

- **Same guarantee.** The reply goes through the same letter-for-letter
  check; one that changed a word is thrown away and the transcript lands
  as it came. In the measurement below that was 2 dictations of 12, both
  spelling "corrections" (`שהכול` -> `שהכל`) the check caught.
- **About a second.** Groq answered in 0.5–1.5 s (median 0.8) with the
  `...` marker up the whole time. `[punctuate] max_wait_s` (6) bounds it:
  past that the transcript is pasted unpunctuated and the answer, if it
  ever comes, is dropped — the key itself has no deadline, because
  nothing is waiting on it.
- **Short answers are left alone.** Fewer than three words and the pass
  stands down: "כן" and "ארבע" already come out of the decoder with a
  mark on them, and the round trip would cost more than they took to say.

Flip it from the dashboard while the app runs and it takes effect on the
next dictation — no restart, because [`set_option`](#the-dashboard) hands
the running app the new `[punctuate]` block and it rebuilds its
punctuator from that.

### Which model

Groq first, then Gemini, then Ollama — whichever `[punctuate] prefer`
names goes first and the other two follow in that order, so a spent
quota costs one fallback and not the key. Measured on real dictations,
first 2026-08-15 with two backends and again 2026-09-01 with three, the
same prompt over 12 transcripts with their punctuation stripped:

| | punctuation | kept every word | speed |
|---|---|---|---|
| Groq (`openai/gpt-oss-120b`, reasoning low) | every comma, full stop and question mark | 10 of 12 | 0.47–1.47 s, median 0.83 |
| Gemini | every comma, full stop and question mark, plus the maqaf in `ה-commit` | 4 of 5 | 0.61–1.14 s, median 0.89 |
| llama3.1:8b | never broke a word, but added only a trailing full stop on one of two samples | 2 of 2 | 17.7 s cold, 3.6 s warm |

Same quality, and Groq's free tier is ~1,000 requests a day against
Gemini's 20 per model — the bucket the translate key draws on. That is
why Groq moved to the front, for the key and for the switch above. No
`GROQ_API_KEY`? Groq is simply not in the chain, and the order is what it
was: Gemini, then Ollama. `[punctuate] groq_model` is `""` = borrow
`[polish] groq_model`.

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

**An answer too tall for the box shrinks before it is cut.** The box opens
no bigger than `[lookup] max_width` × `max_height` — that cap is the point,
so the answer never covers half your screen — but when an answer needs more
room than the cap leaves, the whole layout is re-measured at smaller faces
first (headline and senses scaling together), in one-pixel steps down to
the ~11 px floor, taking the LARGEST face that fits. Only past that floor
does an ellipsis take the tail, and it trims the floor-sized layout, so
more of the answer shows than the old default-size cut ever did. Measured
2026-08-22 on this machine: three copies of the 60-word sample, which used
to lose their last lines at the default face, now fit complete at 16 px;
the whole search costs 0.7 ms for a dictionary word and 22 ms median for a
4056-character answer — near the key's own guard — against 699 ms under
the old word-hunting trim.

**And if even that is not enough room, drag the box bigger by hand** — see
the resizer below; enlarging can bring back words a cap cut off, because
the resize re-fits the full answer, not just what was showing.

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

### The resizer: grips in both bottom corners, and what they buy

**The exceptions to "the body is only text" are two diagonal grips, one
in EACH bottom corner** — whichever your hand finds, that one works. The
first cut had a single mirrored grip whose live corner depended on the
*answer's* language: bottom-right on Hebrew, bottom-left on English, so
the same grab on the same spot of the screen grew one box and did nothing
at all to the next ("I drag the bottom-right down-down-down and it does
nothing"). Both corners resize now, each growing against its own fixed
top corner, and pulling OUTWARD is growth everywhere.

Drag either grip and **the edge tracks your hand pixel for pixel**: the
window is resized in the very same message the mouse arrives in, before
any other work — a Chrome-style edge. The *text* catches up just behind
it, throttled to about twenty reflows a second and always against your
latest size, then exactly once more when you let go; two earlier cuts
failed here in instructive ways — one let the box hug its content so a
short answer's corner stopped following at all ("it gets stuck … it
doesn't go down with me"), the next re-laid the text out inline before
every move, and whenever that work out-lasted the gaps between moves the
frame fell behind and caught up in bursts ("it jumps ten centimeters …
it takes time to open").

**And inside the frame you drew, the type zooms with it.** A hand-set
size is searched on both sides of the normal face — enlarge the box past
what 19 px needs and the letters themselves grow, continuously in 1 px
steps, until the answer fills what you made or hits a generous ceiling;
shrink it and the face gives way the same gradual way before any word
is cut. The first version of this kept the face capped at 19 px forever,
which is why enlarging looked like nothing happening ("I'm trying to
enlarge it, but it's not growing"): the window obeyed and piled invisible
dark slack under short answers. Growth runs to **the full screen** — the
monitor's whole rect, no margin held back ("can I define it to any size I
want, to the point where it's full screen") — and because the gesture
re-fits the *full* answer rather than what was showing, pulling a corner
outward can also bring back lines an earlier cap cut off. The size
belongs to the answer you resized for; a fresh lookup opens at its
natural size again, exactly as it forgets where you dragged the last box.
As everywhere else in this box, the cursor announces a press before the
press means anything: move arrows on the bar, the diagonal on a grip, an
I-beam over text.

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
  whole* answer, not what fitted. A long one is shown within the 520 px
  cap, its face shrinking before anything is trimmed; whatever still does
  not fit even at the smallest readable face shows an ellipsis, and the
  button still hands over all of it. Measured on a 1762-character answer
  showing 565 of them: the clipboard got 1762.
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
empty selection, on more than `max_chars` (20000: past it even the
chunked local model would run for minutes), on digits, punctuation or
emoji alone, and on a lone URL, path or e-mail address. Identifiers are
deliberately *not* refused; `commit` is exactly what this key exists
for. Any of them takes the box down first: a box that waits to be closed
would otherwise leave the answer to the *last* question standing as the
answer to this one, with the note playing over it saying otherwise.

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

## Asking about the screen (`ctrl+f10`)

Tap `ctrl+f10`. The screen freezes and dims; drag a rectangle over anything
— a paragraph in a browser, an error dialog, a chart — and **the rectangle
lights back up to full brightness** while everything around it stays dark,
with its size in pixels beside it. Let go and **the screen stays frozen**:
what you marked keeps its place and its brightness, ringed in blue, and a
panel of blue glass opens beside it to hold the conversation.

The screen being frozen is the point, twice over. You are talking about a
photograph, so nothing underneath can be disturbed by a stray click — and
because the app owns every pixel of that photograph, the glass is a real
blur of what is actually behind the panel rather than an imitation of one.
Tk has no compositor; a frozen screen is what buys the effect. `Esc` gives
you your screen back.

Now talk to it. Hold **Right Ctrl**, ask your question out loud, and let
go: the question sends itself — no Enter — and the Hebrew answer **streams
in**, first words on screen about a quarter of a second later. Or type it
into the pill at the bottom and press Enter, which behaves identically.

If you do not know what to ask, **three questions are already written** on
chips above the text bar. They are the only Hebrew left in the interface,
and on purpose: a chip is not a label, it is the prompt itself, and a model
answers in the language it was asked in.

**There is a pencil.** It sits in the text bar and it works on the bright
area, so you can circle the thing you mean before you say a word — and the
marks are burned into the pixels that get sent, not drawn on top of a
window. It is the one gesture that survives a bad transcription: when the
words come out wrong, the ring around the thing you meant does not. An
undo appears next to it once there is something to undo.

**It is a conversation, and you may interrupt it.** Start talking again
while it is still writing and it does not queue your words or ignore them:
the answer in flight is abandoned mid-token, what you just said is folded
into what you already asked, and the whole thing is re-asked as one
question — so the reply covers everything you have said so far. Talking
also stops it reading the previous answer at you. Press `ctrl+f10` again
to point the same card at a different part of the screen (that starts a
fresh conversation, because the old pixels are gone). Follow-ups stay in
the card against the same screenshot and cost about a second.

The panel is a pane, not a dialog: no title bar, rounded, and see-through
in the way glass is — the blur, the blue and the bright edge along its top
left are painted into the picture, so the text on top of them stays crisp
however transparent the panel looks. Drag it by its top strip, resize it
from its bottom-right corner, and it grows as the conversation does before
it starts to scroll. The icons at the top right copy the answer, read it
aloud, pin the panel and close it; `Esc` closes it too — and the first
`Esc` stops the speaking rather than closing, so you can shut the voice up
without losing the thread.

It is the lookup key, but for pixels, and you can talk over it.

### The screenshot is the most sensitive thing this app has ever handled

A screenshot can hold mail, banking, anything ever shown on this screen —
strictly more than the transcript text the repair pass may already send
out. So this feature is **local-first where every other key is merely
local-preferred**:

- The default chain is **Ollama `gemma3:12b` only** — the repair model the
  app already keeps resident reports `capabilities: ['completion',
  'vision']`, so asking it for pixels costs no new pull and no new VRAM
  (measured with both Whisper models loaded: 14,710 / 16,311 MiB, nothing
  evicted).
- `allow_screenshot_upload` defaults to **false**, and false does not
  mean "cloud second" — it means the cloud backends are **never built**,
  enforced in the chain builder and asserted by a test against the built
  list, not against the flag. With the gate shut and Ollama down, the
  card says so; it does not helpfully fall through to the cloud on its
  own initiative. Flip it to true and the chain becomes ollama → groq →
  gemini-pool.
- The screenshot is **never written to disk**, never logged, never cached
  — the screen changes between presses, so unlike `lookup_cache.json`
  there is nothing worth keeping — and it dies with its card. Even the
  base64 it is encoded into is held by the open card and nothing longer.
  The question text is a dictation like any other and lands in
  `transcripts.log`; the answer is logged at debug level with backend and
  latency.

### What it costs, measured on this machine (2026-08-25)

| step | time |
|---|---|
| tap → the overlay is up | **125 ms** (freeze the screen 78 ms + dim it 16 ms + one PhotoImage of the whole 4480×1440 virtual screen 31 ms) |
| the bright rectangle, repainted per drag event | under 1 ms at 900×450 — no throttle needed |
| downscale 4480×1440 → long side 1344 + JPEG | ~63 ms, ~105 KB; re-encoded **once** per screenshot, not once per question |
| Right Ctrl released → **first text on screen** | **0.24–0.27 s** |
| Right Ctrl released → answer complete | 2.16–2.36 s (of which the model wrote for 1.39–1.42 s) |
| repaints while streaming | 30–34 per answer out of ~141 tokens |
| a follow-up on the same screenshot | ~1.45 s |
| talking over an answer → the reply to both sentences | **2.86 s** from the interruption; the abandoned request hangs up 0.98 s in rather than finishing |
| gemma3:12b vision, first image after idle | ~23 s **once** — the vision projector loads; `warmup = true` pays it at startup |
| Groq `qwen/qwen3.6-27b` (upload on) | 0.5 s, but ~830 prompt tokens/image against an 8,000 tokens/min cap — 1–2 screenshots a minute before 429, so it is the fallback, never the primary |
| Gemini flash-lite (upload on) | 2.2 s, from the shared 20 req/day/model pool F9/F7 drink from |

Interrupting costs almost nothing because the abandoned answer is
genuinely abandoned: the cancel is checked on every streamed line, and a
watchdog closes the connection outright for the case where the model has
gone quiet between lines. The one place it cannot reach is a request
still waiting for its first byte — Ollama sends no headers at all until
the model is loaded — so an interruption during the one-off ~23 s cold
load waits out that load. It hangs up the instant the headers arrive,
which is what stops the GPU writing a whole second answer nobody wants.

The gap between those two Right-Ctrl rows is the whole argument for
streaming: the wait was never ours to shorten, only to fill. Only the
LOCAL backend streams — Groq answers in half a second and Gemini in two,
so there is no wait there to fill, the same split the lookup key made.
Streaming costs one thing and it is paid by hand: the `urllib` timeout is
per socket operation, so a token every 24 ms means no recv ever waits and
the timeout stops bounding anything. The reader keeps its own deadline.

Small selections are faster than big ones precisely because
`max_side_px = 1344` keeps a full-screen grab bounded. Questions
deliberately **skip the repair pass**: a vision model is robust to one
misheard word, and the question path stays free, fast and quota-neutral.

### Speaking the answer

`speak = "button"` (the default) puts a Speak control on every answer —
press again, or press `Esc`, to stop. `"auto"` reads every answer aloud as
it lands, which with auto-send is the closest this gets to a phone call;
`"off"` hides the control. The voice is **Microsoft Asaf (he-IL)**, spoken
through Windows' own WinRT speech synthesizer — the legacy SAPI API cannot
see the OneCore Hebrew voices at all — synthesized by a PowerShell
subprocess into a temp WAV that is deleted the moment playback finishes.
Synthesis measured 30 ms for a 5.9-second clip. Whatever it is reading
stops the moment you start talking.

### Check it by hand

1. **A browser paragraph** — drag over it, ask "מה כתוב כאן?" by voice, and
   do not touch the keyboard. The answer must arrive on its own, quote the
   paragraph, and read right-to-left with the full stop on the left.
2. **The selection must be the bright part.** Everything else is dimmed,
   the size in pixels rides the corner, and the thumbnail that follows
   shows exactly the rectangle you dragged, on whichever monitor.
3. **Esc mid-drag cancels with nothing on screen**; so does a click
   without a drag.
4. **Talk over it.** Ask something long, and while the answer is still
   writing, hold Right Ctrl and say something else. The half-answer must
   vanish, the two sentences must appear as ONE question, and the reply
   must address both. The abandoned answer must never reappear.
5. **Dictate while it is open** — the transcript lands in the card, **not**
   in the app underneath. Nothing may be pasted behind it.
6. **Press `ctrl+f10` again with the card open** — the selector comes back,
   the card takes the new pixels, and the old conversation is gone.
7. **Drag it by the strip, resize it by the corner**, and ask something
   long enough to need the room. The card must grow, then scroll.
8. **Speak, then Esc, then Esc** — the first stops the voice, the second
   closes the card.
9. **With `allow_screenshot_upload = false`, stop Ollama and ask** — the
   card must say it failed, and no cloud request may appear anywhere.

## Capturing the screen (`Win+Shift+S`) and recording it (`ctrl+f12`)

Win+Shift+S — the actual key, taken from Windows — plus the editor Windows
makes you go and find, plus a recorder, and none of it leaves this machine.

**How it takes the key, and what that costs.** A Windows-key chord is the
one kind of binding this app *swallows*. Every one of them is a shortcut
the shell already answers, so letting it through would open this editor
**and** the Snipping Tool. Measured here on 2026-08-26, three runs of a
bare hook:

| | what came up |
|---|---|
| `Win+Shift+S`, hook watching only | `Snipping Tool Overlay` |
| `Win+Shift+S`, the `s` swallowed | **nothing — the chord is ours** |
| `Win` tapped alone, same hook up | Start, exactly as before |

So **nothing has to be turned off in Windows**, and no registry key is
involved: the `s` never reaches the shell, and the Win key itself is never
touched, so every other Win shortcut still works. If you would rather keep
the system snip, `[capture] capture_hotkey = "ctrl+f11"` puts it back —
that key is still measured-free. Ctrl/Shift/Alt chords are *not* swallowed;
they fire the action and still reach whatever has focus, which is the rule
the rest of this app is built on.

**What does not happen next is the point.** The editor used to open over
the whole screen after every capture, for a picture that nine times out of
ten was going straight into a chat window — a modal dialog in nicer
clothes, making the common case pay for the rare one. Now the drag ends
silently with the picture on the clipboard, and a card appears in the
corner for five seconds — one per capture, stacked, so the key is never
dead while one is up:

- a **thumbnail**, so you can see whether it caught the bit you meant
  without opening anything
- **pencil** opens the editor on the frozen pixels, exactly where you took
  them — the screen is still held in memory while the card is up, so the
  window underneath can scroll and the editor still gets what you captured
- **save**, **copy again**, **✕**
- a line that **drains** along the bottom, and **stops draining while the
  pointer is on the card** — five seconds is not long when what you are
  deciding is "did that catch it", and a card that vanishes mid-reach is
  worse than no card
- it **never takes the keyboard**: a capture taken mid-sentence does not
  eat the next keystroke
- and it is **in the next screenshot, on purpose** — see below. It used to
  carry the same don't-photograph-me flag the recording pill carries, and
  that flag is absolute: it hid the card from *your* grab as much as
  anyone else's, so a card you wanted to show somebody was the one thing
  you could not. Press the key again while one is up and the card is in
  the picture and out of your way, because the screen is frozen first and
  the cards step off it a moment later

**And the key is never dead.** It used to be. For as long as a card sat in
that corner the screenshot key did nothing at all — press it again inside
those five seconds and the app wrote "already up" to the log and ignored
you. The reason was ours rather than yours (a Tcl interpreter the card
owned), and it turned up at exactly the moment you are working fastest:
three things off one page, one after another, quicker than any card can
count to five. **Press it again whenever you like.** A second press is a
second capture and a second card, and the cards stack:

- **oldest at the top, newest at the bottom.** The corner is where the eye
  already goes, so the capture you just took is never the one you have to
  hunt for. What `toast_corner` changes is which end of the column is
  pinned — top corners fill downwards, bottom corners upwards — and not
  the order
- **every card has its own clock.** They arrived at different times, so
  they leave at different times, and resting the pointer on one holds that
  one and not the rest
- **the stack holds still while your hand is on it**, so nothing slides
  out from under the pointer: a card whose time is up waits while you are
  on the stack rather than dropping the one you were reaching for a
  card-height down the screen
- **a card belongs to the monitor its capture came from**, so two screens
  carry two independent stacks, each counted from its own corner — the
  monitor to the *left* of the primary included, whose coordinates are
  negative and have caught this app out before
- past **`toast_stack`** cards (four by default, eight at most) the oldest
  goes early to make room, and it takes nothing with it. Every one of
  those captures reached the clipboard the moment you let go of the mouse,
  before any card existed, so an early card is an offer expiring and never
  a picture lost — and with Windows' clipboard history on, `Win+V` still
  has the lot of them
- **you can take a picture of the cards themselves.** The flag that keeps a
  window out of a screenshot is absolute — it hides that window from *your*
  grab as much as anyone else's, which is why a card wearing it could never
  be shown to anybody. So the cards stay photographable, and what stops the
  stack becoming a hall of mirrors is the order rather than the flag: the
  desktop is frozen first and the cards are taken off the screen a moment
  later, so a card lands in the picture once and is never in the way of the
  drag. `toast_in_shots = false` hides them from every capture again

**And the file is now opt-in.** `[capture] always_save = false` is the
default: the picture goes to the clipboard and nowhere else until you press
Save. This is the one setting that gives something up — copying something
else inside those five seconds loses it — and the trade is a folder holding
the captures you meant to keep instead of every rectangle you ever dragged,
which for the most sensitive folder in this repo is worth something on its
own. `always_save = true` restores the old promise exactly, and
`after_shot = "editor"` restores the old behaviour.

Press `Win+Shift+S`. The screen freezes and dims exactly the way the ask key
freezes it, because it is the same gesture and the same hand: **drag a
box**, or **hold Shift and lasso a shape** around something that is not a
rectangle. Or don't drag at all — under the hint there is **a chip per
monitor**, named and sized (`Screen 1  2560 × 1440`, `Screen 2  1920 ×
1080`, `All screens  4480 × 1440`), and clicking one takes that whole
screen. (`Enter` still means "the screen the pointer is on", for when your
hand is already there.) Let go and two things have already happened — the picture is **on your
clipboard** and it is **saved in `captures\`** — before you have finished
letting go of the mouse. That promise is not negotiable and nothing you do
next can undo it. `Esc` at any point gives you your screen back.

Then the editor opens, and this is the part Windows does not do: **the
picture does not move.** What you selected stays exactly where you
selected it, at 1:1, lit and ringed in blue, and a toolbar of blue glass
arrives underneath it. You are drawing on the thing itself, in the place
you found it — not hunting for a thumbnail that opened somewhere else at
some other size.

On the toolbar, left to right:

| | what it does |
|---|---|
| **pencil** | freehand, in the current ink |
| **arrow** | drag from anywhere to the thing you mean |
| **box** | a rounded rectangle around it |
| **highlighter** | a fat translucent stripe — you can still read what is under it |
| **blur** | a **mosaic**, not a Gaussian, over anything nobody else should read |
| **crop** | drag the part to keep — **or drag back out** into what you already cut; the selection follows on screen |
| **swatch** | cycles red → yellow → blue → white |
| **undo** | one step back, and a crop counts as a step |
| **Copy** | the edited picture, back onto the clipboard |
| **Save** | over the same file — one drag makes one file |
| **Ask** | hands the pixels to the ask card (`ctrl+f10`) with everything you drew on them |
| **×** | closes; the file and the clipboard keep what you already had |

**The crop goes both ways.** It is the one edit that throws pixels away
and the one edit everybody overshoots, so cropping is not a one-way door:
pick the crop tool again and the whole picture you took comes back at about
40% brightness behind the bright rectangle, and you drag a new one anywhere
in it. Cut 1280×720 down to 800×450, decide you wanted the caption after
all, and drag back out to 1280×880 — the pixels were never deleted, only
left out of the render. Neither were the marks: ink is stored in
screen coordinates, so an arrow that was cropped off the edge comes back
with the pixels it was drawn on. The limit is the picture you took and not
the whole desktop — past that edge is not "more of the shot", and for a
camera photo it is the desktop the card happened to be sitting on.

**The ink is drawn big and shrunk.** Pillow antialiases nothing, so the
first version of this editor put a visible staircase down every diagonal
and stuck an arrowhead on a shaft that poked out the far side of the point.
Every mark is now rendered at 4× on its own rectangle and resized down —
the same trick the icons use — with the shaft stopping at the arrowhead's
notch and round caps on every stroke. It is cached per mark, so the cost is
paid once when you draw it and never again while you look at it (0.8 ms to
repaint five marks, against 41 ms to render them).

The blur is a mosaic on purpose. A Gaussian at any radius a person will
accept can be sharpened back, and this is the tool people reach for when
the thing underneath is an address or a token. The block size was picked by
reading the result: at 8 px a 12 pt password was still guessable, so it is
12.

A **lasso keeps its transparency**. The png on disk has a real alpha
channel outside the shape, so a cut-out lands on whatever colour the
document you paste it into already is. (The clipboard also carries a plain
bitmap, flattened onto white, for the applications that cannot read alpha —
Windows' own freeform snip makes the same trade.)

### Recording (`ctrl+f12`)

Tap it, pick a region the same way — including **the whole-screen chips**,
which is what that key is usually for — and it starts. **Tap it again to
stop**: the same key, because the second press is the same thought as the
first, and a recorder you have to hunt for with the mouse records you
hunting for it.

**It tells you it started.** A card appears in the corner —
`● Recording started · 960 × 540 · ctrl+f12 to stop` — and after a couple
of seconds it shrinks, in place, to a small rounded pill that is a blinking
red dot and a clock and nothing else. The failure mode of a screen recorder
is not knowing whether it is running; this is the cheapest possible answer,
and it is the shape NVIDIA's overlay uses because it is the right one.

**Put the pointer on the pill and the controls come back** — discard,
mute, pause, stop — growing out of the anchored corner so nothing moves out
from under your hand. The dot goes amber and steady while paused, so
"is this still capturing?" is answerable from the corner of an eye without
a word to read. Drag it if the corner is wrong for one recording;
`[capture] timer_corner` moves it for good, or `"off"` keeps only the
announcement.

A thin blue frame marks what is being recorded. **None of it appears in the
video** — that is `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`,
measured at 0 of 60000 pixels of a window that was demonstrably there, and
it is what lets the pill sit in a corner that may be *inside* the region
being recorded. The frame is also click-through, so it never eats a click
on the thing you are recording.

When you stop, a card says what was written, how long it ran and how big it
is, with buttons to open the folder or copy the file. The clip goes on the
clipboard **as a file**, so you can paste it into a chat or a folder the
way Explorer's Copy does — a video has no useful bitmap form, and a path as
text is not something you can paste into WhatsApp and have arrive as a
video.

The microphone is **off** by default. A screen recorder that quietly opens
your mic is a surprise, and this app's rule is that audio does not travel.
Set `[capture] audio = "mic"` and clips get a track from the same
microphone dictation uses — two simultaneous streams on one device were
verified working here, so recording does not cost you the hotkey — and the
bar grows a mute switch. It mutes rather than removes: an mp4 declares its
streams when the container opens, so a track cannot be added later, and a
switch that pretended otherwise would be a lie in the shape of a button.

### What it costs, measured

The encoder is **PyAV**, which faster-whisper already installs — no new
package, no `ffmpeg.exe`, nothing to keep up to date. The grab is a reused
DIB section and `BitBlt` rather than PIL's `ImageGrab`, and that one choice
is the difference between 30 fps and 18:

| region | our grab | PIL `ImageGrab` | encode (libx264 veryfast) |
|---|---|---|---|
| 1280×720 | 10.1 ms | 53.7 ms | 5.1 ms |
| 1920×1080 | 11.6 ms | 56.7 ms | 11.6 ms |
| 2560×1440 | 21.7 ms | 56.7 ms | 20.9 ms |

Capture and encode run on separate threads over an eight-frame queue.
Achieved on this machine: **30.0 fps at 720p and 1080p with zero dropped
frames**, and 28.0 fps at 1440p — where the shortfall is the grab, not the
encoder. It does not speed the video up: every frame carries a **wall-clock
stamp** in a 1/1000 timebase rather than a frame number, so a clip that
averaged 28 fps is 28 fps of real seconds. A 4.0 s probe came back as
4.03 s, 119 frames.

Size depends entirely on how much of the screen is moving. A 4 s 960×540
recording of a mostly-static screen was **31 KB** (about 0.5 MB/min); a
synthetic worst case with a large block moving every single frame was
28–60 MB/min. Real screens are much closer to the first.

`h264_nvenc` was tried and rejected: the same speed warm (15.1 ms at
1440p) but a 234 ms spike on its first frame while the encoder session came
up — a dropped frame at the exact moment the user is watching — and the GPU
is already carrying two Whisper models and gemma3.

### Where it all goes, and what never leaves

Pictures land in `[capture] folder` and recordings in `[capture] clip_folder` (empty = the same place; the shipped default was `captures\` beside the app), named
`shot 2026-08-25 22-41-03.png` and `clip 2026-08-25 22-41-03.mp4` — hyphens
where a clock would put colons, so sorting the folder by name is sorting it
by time. Two captures inside one second get ` (2)`; nothing is ever
silently overwritten.

**The folder is gitignored, and it is the most sensitive thing in this
repo.** A screenshot can hold mail, banking, anything ever shown here — so
it gets the same treatment `transcripts.log` gets: it stays on this
machine. There is **no upload path in `capture.py` at all**. The only route
from a capture to a model is the editor's **Ask** button, which hands the
pixels to the ask card and obeys `visual_qa.allow_screenshot_upload` like
every other question — which is `false` by default, and means the cloud
backends are not merely unused but unconstructable.

### Try it in this order

1. **Press `Win+Shift+S` and drag a box over a paragraph.** Before you touch
   anything else, paste into Paint — it must already be there. `captures\`
   must be **empty**, and the corner card must say "not saved".
   Then press Save on the card and look again.
2. **Press it three times in a row without waiting.** Every press must be
   taken: three captures, three cards stacked from the corner, the first
   one you took at the top and the one you just took at the bottom, each
   with its own draining line. Then check the second and third pictures —
   the earlier cards must not be in them.
3. **Shift-drag a lasso around something round.** The png must be
   transparent outside the shape, not black and not white.
4. **Press Enter instead of dragging.** The whole monitor the pointer is
   on, taskbar included.
5. **Draw an arrow, then Undo, then crop, then Undo.** The crop must come
   back with the arrow still on it, in the place it was drawn.
6. **Blur something, save, and reopen the file.** The blocks must be in the
   file, not just on screen.
7. **Press Ask.** The ask card must open on what you drew, not on the
   original.
8. **Tap `ctrl+f12` and click the `Screen 2` chip.** The whole second
   monitor, with no drag involved.
9. **Record ten seconds, tap the key again.** The announcement must appear
   and then shrink to the corner pill; neither it nor the blue frame may be
   in the video. Paste into a chat window — the file itself should arrive.
10. **Hover the pill.** Discard, mute, pause and stop must appear without
    the pill moving away from its corner.
11. **Record, then press pause for five seconds, then resume and stop.**
    The pause must be a cut, not five seconds of still image.
12. **Press `Win+Shift+S` while the app is running.** This editor must
    open and the Snipping Tool must not. Then press `Win` on its own —
    Start must still open, and so must `Win+E`.
13. **Crop something small, then pick crop again.** The whole picture must
    reappear faintly behind the bright rectangle; drag a bigger one and the
    picture must grow back, marks and all.

## A photo from the camera (`ctrl+f6`)

The same folder, the same clipboard, the same editor — a different lens.

Tap `ctrl+f6`. A card opens in the middle of the monitor your pointer is
on, with the **live picture** in it and a shutter under it. Press **space**,
**Enter**, or the button, and the photo is **on your clipboard** and
**saved in `captures\`** before the flash has finished — the same promise
`Win+Shift+S` makes and just as non-negotiable. Then it opens in the
screenshot editor, laid on the screen **exactly where the preview was**, so
you can crop it, arrow at it, blur something out or hand it to the ask key.
`Esc` closes without taking anything.

The card is three keys wide:

| | what it does |
|---|---|
| **shutter** | space, Enter, or click. With a timer set, it arms one — and a second press cancels |
| **mirror** (`m`) | flips the picture. **Both** the preview and the file, or neither |
| **timer** (`t`) | cycles off → 3 s → 10 s. The count fills the middle of the picture; `Esc` cancels the countdown before it closes the window |
| **next camera** (`c`) | only there when there is more than one |
| **×** | closes it |

Drag the card by its face if it is over the thing you wanted to
photograph.

### The three decisions worth knowing about

**The lens closes at the shutter, not at the end.** The camera is released
the instant the picture is taken — before the flash, before the file,
long before you have finished drawing on it. The little light beside the
camera means what it looks like it means, and nothing in this app opens it
but this key. `[camera] enabled = false` unregisters the key entirely.

**What you see is what you get.** One image per frame, made at the size the
window is showing, and that image is the preview *and* the clipboard *and*
the file *and* what the editor opens on. So the preview is 1:1 with the
camera whenever the monitor can show it (1280×720 fits here with room to
spare) and scaled down when it cannot — and the photo is whatever was on
the screen. It is why `mirror` flips both or neither: a preview that
disagreed with the file it produced would be the same bug the screenshot
editor is built to avoid, wearing a lens.

**Mirror is off by default.** The commonest thing anyone holds up to a
webcam has writing on it, and mirrored writing is unreadable. Tap `m` when
you are framing your own face and want a mirror to do it in.

### What it is built on, and what it measured

The camera arrives through **PyAV** — the same library that encodes the
screen recordings, and already installed as faster-whisper's own
dependency. No OpenCV, no `ffmpeg.exe`, nothing new to keep up to date.

Measured on this machine, 2026-08-26, on an eMeet C960 over USB:

| | |
|---|---|
| open → first frame | **654–829 ms** over six opens — which is why the card says *waking …* instead of sitting black |
| delivered | **25 fps** at 1280×720 MJPEG, 40.1 ms apart and steady to a tenth of a millisecond |
| one frame to the window | **5.4 ms** at 800×450, 4.3 ms at 1280×720 |
| listing the devices | **147 ms**, paid once when the window opens |

**Ask for MJPEG or you get a slideshow.** This camera offers 1920×1080 at
30 fps as MJPEG and *the same size at 5 fps* as raw `yuyv422`, and
DirectShow hands over the raw one unless it is told otherwise — read off
the device's own pin list, both pins. A camera with no MJPEG pin is asked
again for whatever it has, and that is written to `app.log` so a slow
preview has a reason.

**A virtual camera loses to a real one.** OBS, Teams, Zoom and NVIDIA
Broadcast each install a video device that is not a camera, and they sort
ahead of the real webcam as often as not — here OBS is second of two. With
`[camera] device` empty, the first *real* device wins. Set it to any part
of the name to pin one (`device = "eMeet"` is enough; nobody retypes
`HD Webcam eMeet C960` without a typo), and if that one is unplugged the
key still takes a picture and tells you whose.

### Where it goes

`captures\`, beside the app, named `photo 2026-08-26 18-49-29.png` — the
same folder and the same clock-shaped name the screenshots use, so sorting
by name still groups the shots, the photos and the clips. The folder is
gitignored and **there is no upload path in `capture.py` at all**; the one
route from a photo to a model is the editor's **Ask** button, which obeys
`visual_qa.allow_screenshot_upload` like every other question.

### Try it in this order

1. **Tap `ctrl+f6`.** The card must appear immediately and say *waking …*
   for under a second, not sit black.
2. **Press space.** Paste into Paint before you touch anything else — it
   must already be there. Then look in `captures\` — one file, named
   `photo ...`, and exactly one.
3. **Draw on it and press Save.** It writes over the same file. Still one.
4. **Tap `m`, then space.** The file must be mirrored the way the preview
   was — hold up something with writing on it and check both.
5. **Tap `t` twice for 10 s, press space, then `Esc`.** The countdown must
   stop and the window must stay open; a second `Esc` closes it.
6. **Watch the camera light.** It must go out the moment the shutter fires,
   while the editor is still open.
7. **Press Ask.** The ask card must open on the photo, with whatever you
   drew on it.

## Awake, and the screens off (`ctrl+alt+n`)

Two separate things, and the separation is the point. **The computer never
sleeps** while this app runs: the hold goes up the moment the app starts
and comes down when it exits, whatever the screens are doing, day or night,
at home or from school. **The screens go off on a key** — tap `ctrl+alt+n`,
press **Screens off** on the shelf, or use the footer of the dashboard's
**Waiting** place (the same button is in Settings → Awake, with the
status rows), and within a second the monitors are dark and *stay* dark;
tap or press again and they come back. Nothing is locked — the session stays open, which is what lets
Claude take a screenshot or open a program from the phone.

**What it does, and what it deliberately does not.** The hold is one API
call, `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`, kept
alive by a thread of its own in the running app: no admin, no fake mouse
wiggling, no registry, and Windows drops it by itself if the app dies.
`ES_DISPLAY_REQUIRED` is left out on purpose — with the key untouched the
screens still go dark on the monitor's own timer; only sleep is prevented.
`[awake] hold = false` turns the hold off. The screens are put out directly
(`SC_MONITORPOWER`, broadcast with a timeout so a hung window cannot hang
the app), twice: at once, and again three seconds later, because the mouse
movement that follows a click lights them straight back up. **Screens off
again** in Settings → Awake does the same on demand. A belt to the braces,
once and without admin, is `powercfg /change standby-timeout-ac 0`: Windows
itself then never sleeps on mains, app or no app.

**Why this machine turned off at night — measured before a line was
written (2026-09-02).** `powercfg /a`: classic S3 sleep, no Modern
Standby. `Sleep after` on AC: 30 minutes; hibernate: off. The System log's
restarts were all the owner's own or Windows Update at ten in the morning.
So the culprit was the idle timer, which is exactly what the hold prevents.
Two things the hold cannot fix are read by **Check status** and named in
the block with what to do: the network card's "Allow the computer to turn
off this device to save power" box (ON here — Device Manager, needs
admin), and Windows Update's active hours (9:00–2:00 here, so an update
may restart the machine between two and nine).

**Check status** is the truth check the spec asks for. `powercfg /requests`
needs an elevated prompt, which this app does not have, so the hold is
read from the kernel instead — `CallNtPowerInformation(SystemExecutionState)`
returns the same ES_* flags without the process names — and the row says
"held" only when this app is holding AND the kernel agrees. It also shows
the sleep timer, the standby type, the network card's power-saving flag,
the update window and whether Claude is running. It runs by itself when
the block is built and again after every switch.

**If the app dies holding.** The hold dies with the process and needs no
cleanup. The optional `[awake] pin_timeouts` (off by default) also sets the
sleep and hibernate timers to never for as long as the app runs; those
outlive the process, so `awake_state.json` is written when the hold goes up
and, if it is still there at the next start, the saved numbers are put back
and the file removed. `awake.log` records every hold and release and every
screens-off and screens-on with a timestamp and what the check found.
`[awake] enabled = false` unregisters the key; the dashboard's button keeps
working.

**Keeping them dark.** Any input lights the screens — a key, the mouse,
the click Claude sends from the phone — and Windows only puts them out
again on the monitor's own timer, five minutes here. So while the screens
are off a thread reads `GetLastInputInfo` and puts them out again
`[awake] keep_screens_off_s` seconds (default 10) after the last touch,
every time, with a line in `awake.log` each time it does. The detector is
the tick that lit them, so an untouched machine gets no broadcast at all —
and the owner at the keyboard is not exempt, on purpose: the key means
the screens are dark, and the same key is how to bring them back. `0`
turns it off.

**The vitals, and the morning that made them.** Two mornings running
(2026-09-02, 09-03) the owner came home to a machine that crawled until
this app was stopped — and stopping it cured the machine in about a
second, which is why the app looked guilty. Nothing helped: `app.log`,
Ollama's log, the System log and the task scheduler all had *no line at
all* between the last phone dictation at 11:09 and the key at 14:54.

What it actually was, diagnosed the same afternoon and confirmed by
intervention:

- The USB webcam (eMeet C960, `USB\VID_328F&PID_2013`) had started
  connecting and disconnecting by itself every ~4 s — 5 arrivals and 5
  removals per 40 s, counted with a `WM_DEVICECHANGE` listener. It began
  2026-09-01 19:34, the same evening the freezes started (`app.log`:
  "the camera ... stopped: I/O error").
- Every flap makes NVIDIA's `nvcontainer.exe` (NVIDIA App 11.0.7.247,
  its UXDriver plugin) re-scan the GPU and leak one Thread + one Event
  handle. After 25 h of uptime it held **823,369 handles of the
  machine's 988,258**, and ~1.5 GB of extra **non-paged kernel pool** —
  memory that by definition cannot be paged out. A known NVIDIA bug.
- The leak ran at ~6 handles/s **whether or not this app was running**
  (measured across a deliberate one-minute stop), so the app never
  caused it.
- Unplugging the camera stopped it dead: 0 device-change messages in
  30 s, 0 handles/s. The 823,369 already leaked stay until a reboot.

So the app was the last straw, not the leak: thrashing is a cliff rather
than a slope, and freeing this app's few GB puts the machine back over
the edge instantly — which is exactly why stopping it "fixes" the
machine in a second while changing nothing about the cause. It also
explains the history: 28- and 50-hour runs had been fine, because
before 09-01 nothing was eating the pool and the app's footprint never
reached the cliff.

**What that bought.** While the screens are off, `awake.py` writes a
`vitals` line to `awake.log` every `[awake] vitals_minutes` (default 10)
and one more the moment they come back — the state the owner walks in
on, recorded *before* the stop that cures it. Each line carries free
RAM, commit against its limit, non-paged pool, GPU memory
(`nvidia-smi`), this process, the five heaviest programs by working set,
and the machine's handle count **with the name of the process holding
most of them**. Win32 through ctypes, ~300 ms a read; the GPU number is
the one subprocess.

That last name is load-bearing, and it is why `awake.processes()` reads
the process list from `NtQuerySystemInformation` instead of the obvious
`EnumProcesses` + `OpenProcess`: this app does not run elevated, a
non-elevated `OpenProcess` is refused for a service running as SYSTEM,
and the first implementation of this therefore reported "msedgewebview2
holds 17,654" on a machine where `nvcontainer.exe` held 823,369. In a
leak, the process that needs naming is precisely the one that cannot be
opened. Verified against `Get-Process`: same handle counts, same working
sets, and 330 processes seen where `Get-Process` sees 325.

## The shelf (`ctrl+alt+d`)

**Tap `ctrl+alt+d` — or click the status dot — and a small panel opens
beside the dot with everything waiting on it. Tap it again, click the
dot again, press `Esc`, or press the X at the top of the panel, and it
is gone.** It is the desk without sitting down at it: the state, the
pile, the last thing you said, the screens, and one door to the window.

**The owner's rule, and it is the whole design: it opens only on the key
press or a click on the dot; the same press, the same click, `Esc` or
the X closes it; never on hover, never on passing the corner.** Nothing
arrives here. The corner of the screen where this panel lives is the
same corner cards arrive in on their own, and a panel that also opened
by itself — or on a pointer wandering past — would make that corner
unpredictable, which is the one thing a corner you glance at cannot be.
You ask for it, you answer what is on it, it goes away. The click on the
dot is a click on the *disc* — the glow around it stays transparent to
the mouse — and a double-click is one click, not an open and a close.

**What it holds**, top to bottom:

- **The state**, in the dot's own colour, with the line under it: `up 4h
  32m · recording 1:42` while the microphone is live, `up 3h 07m · 12
  today` otherwise. The recording clock is there because of the single
  loudest number in ten days of logs — **72% of dictations are locked
  on** (355 of 495), which means the key was released and the machine is
  still listening, and that is the one state where missing feedback costs
  a whole recording.
- **Pause** and **Stop**, beside it, and the **X** at the far right of
  the band, where every window keeps its close button. Stop **arms**
  rather than quits: the first press turns it into a confirmation, and
  it is refused outright while a recording is running or locked on. The
  X closes the panel and nothing else — the same door as the key and
  `Esc` — and it lights on hover like its two neighbours.
- **Waiting for you** — the same merged pile the window's Waiting place
  draws, from the same four stores: unread notifications, second-reading
  proposals, open problems, the weekly routine's questions. Newest first,
  whatever kind, each row with the two answers it needs on the row
  (Dismiss / Open · No / Keep · Close / Open · Later / Answer). Capped at
  `[shelf] rows` (5), and "+N more" opens the window.
- **What you said last**, with **Copy**.
- **Screens off / on**, the same toggle as `ctrl+alt+n`.
- **Open the desk** — the one lit thing on the panel, and the only gold:
  history · keys · settings · everything else.

**What it never holds: settings, the key list, the history.** Those are
things you sit down to, and sitting down is what the control window is
for. A shelf you have to read is a window with no title bar.

**A row answer that resolves something in place does not close the
panel.** The first draft said every answer closes it, which makes
clearing a pile of five cost five key presses — the opposite of what
putting two buttons on every row is for. The rule shipped instead: **an
answer that takes the screen somewhere else closes the panel; an answer
that answers what is on the panel refreshes it where it stands.** Three
things leave (opening a notification, opening a problem, answering a
question), and Copy, the door and "+N more" close it as well; Pause and
Screens off refresh in place.

**One gold thing.** The prototype gave every row's first answer a gold
pill. On the LAMPLIGHT palette that put seven lit things on one panel and
left the door — the one primary action — meaning nothing. The primary
answer on a row is now a lifted plate with prose-weight text, the count
badge is neutral, and the door is the only lamp. The one gold-soft pill
that stayed is on a second-reading row, because that pill is *content* —
the word the model wants to change — and not an action.

**Nothing here is allowed to cost a dictation**, and each of these was
measured:

- **The hook has 300 ms.** The tap reads one flag and starts a thread.
  Building the card reads four JSON stores and that happens on
  `shelf-open`; nothing that touches the disk runs inside the hook.
- **`Esc` is claimed narrowly.** The panel claims exactly one virtual key
  (`0x1B`) and only while it is up; it is offered the key *after* the
  review and notify cards, so their pointer-gated claim comes first, and
  it ends the event before the state machine's `cancel_guard` — so an
  `Esc` aimed at the panel can never also throw away a locked recording.
- **Every pixel that is not a named rectangle answers
  `HTTRANSPARENT`** — the 26 px shadow margin and the panel's own padding
  included — so a click aimed at whatever is underneath still lands on
  it (in the top-right, where the panel lived until 2026-09-07, that was
  the close button of every maximised window). Asserted at three scales
  and four pile sizes.
- **Nothing animates.** Composing a full panel is 41 ms, so the
  one-second tick does not recompose: the picture is cached on
  `(card, hover, scale)` and re-blitted, and a genuinely new picture only
  arrives when something changed. `regions()` is 1.9 ms, `card_for()`
  0.02 ms. The refresh check itself is four `os.stat`-sized stamps —
  when they agree, no JSON is read at all.
- **Importing it costs 47 ms**, once, in `App.__init__`, and only when
  `[shelf] enabled = true`.
- **Delete `skin\` and it still opens**, as a flat Tk card with square
  corners, every button working — the same revert rule the rest of the
  look obeys (see `SKIN.md`).

The panel is **452 px wide** including its shadow margin, and 648 px tall
with a full pile of five (370 empty, 682 at the cap). That is tall for
something that sits beside a 13 px dot, and it is defensible only because
it opens on a deliberate press; the lever if it is too much is
`[shelf] rows`, and `3` brings it to 520. It opens beside the dot and
never under it — it inherits the hint card's `DOT_ROOM`, measured
against the **work area** the dot is measured against. With the dot in
its bottom-right corner (the default since 2026-09-07) the panel sits
**above** the dot, right-aligned to its own 14 px margin: on this
2560x1440 screen with a 48 px taskbar the visible panel's right edge is
at x 2546 and its bottom edge at y 1332, 18 px clear of the dot's window
at y 1350. With `[dot] corner = "top-right"` it keeps the old placement
beside the dot, x 2100, y 14. While it is up the hint card steps aside
and the notification column is hushed (`[shelf] hush_notifications`);
both come straight back when it closes, nothing is marked seen and no
reminder is lost.

**Every answer goes through the same method the card would have
called** — `_notify_opened` / `_notify_dismissed`, `_review_verdict`,
`problems.resolve` and then `problems.digest`, `_question_show` with the
real answer card and its box — and nothing goes over the named pipe: the
shelf lives inside the running app, and a pipe round trip to reach a
method on the same object would be a second failure mode for nothing. A
store that is off, missing or unreadable costs its own rows and nothing
else; `[questions]` is not in `config.toml` on this branch, so those rows
are built and tested and will appear the day the section does.

**One cost, stated.** Newest-first is one rule for all four sources, so a
burst of notifications can push a question that has been waiting since
Saturday past the cap into "+N more". That is three lines to change if it
ever bites.

**Check it by hand.**
1. Tap `ctrl+alt+d`: the panel appears above the dot, not on it. Tap
   again: gone. Tap once more and press `Esc` with the pointer anywhere
   at all — gone. Once more, and press the X at the top-right of the
   panel — gone. Click the dot's disc: open; click it again: gone.
2. Wave the pointer over that corner without pressing anything: nothing
   opens, ever. Click the dot's *glow* rather than its disc: nothing
   opens, and the click lands on whatever is under the glow.
3. With the panel up, click something underneath *through* the panel's
   shadow margin — the click lands on it, because the margin is
   transparent to the mouse.
4. Hold Right Ctrl, tap `←` to lock on, and press `ctrl+alt+d`: the panel
   opens, the head says `recording 0:07` and counts. Press `Esc`: the
   panel closes and **the recording is still running**. Press `Esc`
   again: now the recording is discarded, as it always was.
5. While locked on, press **Stop**: refused, with the no-op cue — and the
   panel stays open.
6. Let a notification and a second reading both be waiting, then open the
   panel and press **Keep** on the proposal: the row goes, the panel
   stays, the count drops by one. Press **Open** on the notification: the
   session comes forward and the panel closes.
7. `[shelf] rows = 3` from the dashboard, no restart: the next open is a
   shorter panel with "+N more" on it.
8. `[shelf] enabled = false`, restart: the key is unregistered, the row
   is off the hint card and off the Keys board, and everything else — the
   cards, the cues, the window — goes on exactly as before.
9. `set HD_SKIN=0` and start it from a terminal: the panel is a square Tk
   card and every button on it still works.

## Notify — when Claude (or anything) finishes (`ctrl+alt+m`)

Claude Code has a "finished" notification of its own, and on this machine
it never reaches the owner (2026-09-03: both notification switches are on
in `~/.claude/settings.json`, and nothing has ever appeared) — so this app
takes the job. Any program on this machine, or the phone over the same
Tailscale link the dictation endpoint uses, POSTs a small JSON body to
`/notify` on the `[server]` port with the bearer token from
`server_token.txt`, and the app plays a three-note cue, puts a card up at
the screen edge and keeps reminding you until the card is answered —
`Esc` with the mouse over it, a tap of `ctrl+alt+m`, or **Dismiss all**
beside the title of the dashboard's **Waiting** place.

**They stack, they grow upward, and they wait (2026-09-04).** Three
things asked for in one breath, all of them about the same corner of the
screen. The owner keeps the card in the **bottom-right**, and a long
message used to grow downward and run off the bottom of the screen — so
the column is anchored by its BOTTOM edge (`[notify] anchor = "bottom"`)
and a taller card grows *upward* from where it sits; `"top"` pins the top
edge and is the old behaviour. Nothing times out any more: `[notify]
card_seconds` is `0` by default and a card stays until it is answered,
because a notice that had gone before he turned round was the whole
problem this feature exists for. And every unread notification is on
screen at once, as a column, **newest at the top** and oldest at the
bottom, each with its own × and its own click target: `[notify]
stack_max` (default `5`) is how many fit, and the bottom card carries a
faint `+3 earlier` for the rest, which wait on the dashboard's Notify
screen. The whole column is drawn into ONE window, not one window per
card — one thread, one hit test, one placement, and gaps that cannot
drift — and the stacking arithmetic is the capture toast's (`TOAST_GAP`,
`stack_fits`, `stack_at`, `stack_layout`), copied rather than imported,
because `overlay.py` is on the startup path and `capture.py` drags in
Pillow, Tk canvases and a video encoder behind it.

**A click on a card takes you there (2026-09-04).** Pressing anywhere
on one except its × raises the window that sent it — for a Claude Code
notification, the Claude window — and marks that one seen in the same
motion, because arriving at the work is having read the notice. The ×
is the other answer and keeps the old meaning for the card it is on:
down, seen, stay where you are. `Esc` over the column, the dismiss key
and the dashboard's **Dismiss all** are still the whole-hearted version
— everything seen, the column down. A press that travels more than
four pixels is none of them — it is still the drag that moves the
column. How
the sender is identified: `notify_hook.py` walks UP ITS OWN PARENT
PROCESSES and takes the first visible titled window an ancestor owns,
because the hook is a child of the process that owns the window, so the
answer is structural rather than a guess at a title. Measured on this
machine that day, from a process spawned inside Claude Code: six
ancestors (`python.exe`, `python.exe`, three `bash.exe`, `claude.exe`)
owning no window at all, and the seventh, `claude.exe`, owning exactly
one — `(43779834, 'Claude')`. It rides in the payload as `hwnd` and
`app`; `raise_window` restores the window if it was minimised, asks for
the foreground, WATCHES `GetForegroundWindow` until it is the window (up
to half a second) and falls back once to the `AttachThreadInput` dance if
it never becomes it. The watching is not belt-and-braces: the handover is
asynchronous, and measured that day from a plain background process the
immediate read after a `SetForegroundWindow` that returned 1 was `0`
(nobody), with the target in front 500 ms later — so the first version of
this reported failure on a raise that had worked. What it does now, both
measured from a background python with Chrome in front: a minimised probe
window, `raise_window -> True` in 15 ms and `GetForegroundWindow` changed
from `1126367970` to `658500`; and the real Claude window, `True` in
16 ms, `1126367970` → `43779834 'Claude'`. A sender that named no window,
one that has since closed, or a raise Windows refuses costs the raise and
nothing else — the card still goes down, and `notify.log` says which.

**And the window is only half of it (2026-09-04).** One Claude window
holds every session — every notification ever sent from this machine
carries the same handle, `43779834` — so raising it arrives at whichever
session the app was last showing, which was the complaint. So a
notification may also name the SESSION, and a click goes there first:
`notify_hook.session_link` puts a `claude://…` URL in the payload and
`open()` hands it to the shell (`os.startfile`, the same "double-click
this" the log buttons use) before it raises the window, because the
link spawns a process and travels while the raise is instant. The URL
is `claude://resume?session=<uuid>`, and both halves of that were
measured that day. The two links the app advertises for this —
`claude://code/<cse_…>` and `claude://code/continue?session=local_…` —
reach it and are refused by a feature flag, in its own log
(`%LOCALAPPDATA%\Claude\logs\main.log`): `claudeURLHandler: code session
deep link gated off`, `claudeURLHandler: code entry deep link gated
off`. `resume` is not gated: it exists to adopt a CLI session the app
has never seen, and it looks the id up as `local_<uuid>` before it
imports anything, so handing it the uuid of a session the app already
owns imports nothing and simply goes there — `CLI session 6abc45c7-…
already imported as local_6abc45c7-…`, `LocalSessions.setFocusedSession:
local_6abc45c7-…`, and the window on screen changed from the chat it was
showing to that session. The uuid in the link is NOT the `session_id` a
hook is handed (that names the current CLI transcript, and a resume
starts a new one); it is the desktop app's own id, joined to ours
through the app's own store —
`%APPDATA%\Claude\claude-code-sessions\<account>\<org>\local_<id>.json`,
which names `sessionId`, `cliSessionId` and every `priorCliSessionIds`,
so a notification from the fourth episode of a session still opens that
session. Nothing is written there and nothing is asked of the app. A
notification that named no session, a store that has moved or will not
parse, and a shell that will not take the link all cost the trip and
nothing else: the window still comes forward, and `notify.log` says `| to
the session` or `| but the session would not open`.

**What happens.** The body is `{"source", "kind", "title", "body",
"project", "session", "hwnd", "app", "link"}`, every field optional —
`hwnd` is the window a click should raise (an integer; anything
unparsable or negative reads as "no window"), `app` is its title, kept
as a label only, and `link` is the session inside that window (a
`claude://…` URL and nothing else: one scheme, one alphabet, 180
characters, no space, no quote, no backslash, no percent escape —
anything else reads as "no session"). `kind` is one of `done`,
`input`, `error`, `info` (anything else reads as `info`) and colours the
card's bar and the row's dot; an empty `title` gets the kind's own words
("Finished", "Needs your input", "Something went wrong", "Notification").
Each card says who sent it, the title, the first four lines of the body,
the project, and how long ago; it stays until it is answered, because
`[notify] card_seconds` is `0` by default. Any other number is the old
countdown, in seconds, paused while the mouse is on the card and with
the reminders bringing the column back. It never
takes the foreground: the window that had the keyboard keeps it — the
same recipe the capture toast uses — so a card arriving mid-sentence
costs no keystroke.

**How Claude Code is wired.** Two hooks in `C:\Users\shimr\.claude\settings.json`:
`Stop` (every finished turn → `done`, "Claude finished", the first 300
characters of the last message as the body) and `Notification` with the
matcher `idle_prompt|permission_prompt` (→ `input`, "Claude is waiting for
you" / "Claude needs a permission"). Both run `notify_hook.py`, which
reads the event from stdin, maps it, and POSTs; `SubagentStop` and a
`stop_hook_active` re-entry are ignored so a chain of agents is one
notification, not five. It is installed once and idempotently:

    .venv\Scripts\python.exe notify_hook.py --install-hook

which adds the two entries under `hooks` (replacing any earlier entry of
its own, leaving every other key and every foreign hook alone) and says
on stderr whether the file changed. The hook is registered with
`pythonw.exe` so no console flashes per turn; it exits `0` whatever
happens and prints nothing on stdout, because a hook that fails would
stop Claude, and a notification is never worth that.

**A finish waits for its session to go quiet, and only what is waiting on
you rings (2026-09-05).** The hook above fires at the end of EVERY turn,
and a turn that ends "now I will do X" looks exactly like a finish from
here — so for a day the door rang once a turn. Counted off `notify.json`
and `notify.log` before the change: 87 of the last 100 stored were
`claude-code` / `done`, one session alone sent 52 of them, only 5 were
the permission prompts that were actually wanted, and 31 `REMINDED` lines
stood against 120 `RECEIVED`; the median gap between two finishes was
170 s, the shortest 3 s. Two keys answer it. `[notify] interrupt`
(default `"input"`) says which kinds may PULL YOU OUT — play the cue and
keep reminding: `input` and `error` do, a `done` lands as a quiet card
that waits at the edge of the screen and never comes back on its own
(`"all"` is the old door; `"none"` never makes a sound). `[notify]
quiet_s` (seconds; it ships at `0` — see the next paragraph) holds a
`done` until the SESSION that sent it has been quiet that long: the item
is stored at once, and counted on the line under the Waiting pile, but it
is not on the screen (`notify.log` says `HELD
#12`); if the same session speaks again inside the window the held one
is retired unseen (`SUPERSEDED #12 by #13 | same session`) and the new
one takes its slot, and when the timer runs out the card finally goes up
(`QUIET #13`). A permission or a question is never held — it lands and
rings at once, and takes the pending finish with it, because the
session is plainly not finished. Two sessions running at once hold their
finishes apart: the slot is the session id, and a sender with no session
gets one slot per source. The held ones are counted apart on their own
faint line under the Waiting pile ("2 finishes held until the session
that sent them goes quiet. They will arrive here, not on your screen."),
the reply carries `"held": true`, **Send a test** always rings and shows
at once, and `quiet_s = 0` puts every finish up the moment it lands, as
before. `idle_prompt` was NOT the answer: it has never once fired on this
machine, so nothing here leans on it. And no door can tell a finish from
a progress note — only the session can, which is why AGENTS.md now asks
every session, cloud ones included, to report once, at the end.

**The hold is off by the afternoon (2026-09-05).** Twelve hours of
`notify.log` under `quiet_s = 60` said what the hold costs: 28 finishes
held, 26 of them `QUIET` exactly 60 s after their `HELD`, the other 2
retired by a newer turn, not one released early — every card came a
minute after Claude stopped, and the owner would rather have it the
moment Claude stops. So `quiet_s` ships at `0`: a `done` is a card the
instant it lands (still silent — `interrupt` is what keeps it quiet),
and the same session's next arrival still retires the older card
unseen, so one session never stacks its turns. What is left of the wait
is the hook itself: measured against the sessions' own transcripts, the
last words of the answer to the `RECEIVED` line is 1.0 to 2.0 s (six
finishes; pythonw starting up, and a log that keeps whole seconds). The
hold, the timer and the `HELD` / `QUIET` lines stay in the code for
whoever sets the key back; only the number changed.

**How Cowork is wired — and why Chat cannot be.** Cowork has nothing to
install: its sessions run in Anthropic's cloud, so there is no hook file
on this machine to write. What the desktop app *does* do is raise a
**Windows toast** ("IDF selection test prep — Claude is waiting for your
input"), which lives four seconds in the corner and after that only in
the Action Center — the exact miss this whole feature exists to fix. So
`notify_watch.py` reads the toasts instead. Windows writes every one of
them into `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db`
(measured 2026-09-04: a toast raised at 17:21:49.356 was in the table at
17:21:49.371 — 15 ms), and the watcher polls a copy of it four times a
second, turns Claude's rows into the same payload a `POST /notify`
carries, and hands them to the same engine: same cue, same column, same
reminders, same `ctrl+alt+m`.

**Why four times a second, and where the rest of the wait goes.** The
card trails the toast by about a tenth of a second. The toast itself
trails the Cowork turn by about **nine**, and those nine are not this
machine's to give back: measured 2026-09-04 across eight idle toasts on
three days the gap from the server's own turn-end event to the toast is
6.3 to 9.4 s, because the claude.ai *web page* — which is what builds
these toasts, tag and all — holds the notification on a deliberate timer
(10,000 ms on the fast path in force here, 35,000 ms if a server-side
flag flips) before it asks the desktop app to raise it. Nothing local is
told sooner: a sweep of 21,827 files under the app's two data folders
found no write at all between the turn ending and the toast, no Claude
process holds a listening port, its VM service pipe refuses callers
outside its own package, and the window's accessibility tree is
*downstream* — on the one turn end caught by three clocks at once, the
toast beat the window by 0.5–1.3 s. The nine seconds are reachable only
by holding claude.ai's private session stream with the app's own OAuth
token, which is the owner's conversations and borrowed credentials for
nine seconds, so this app does not go there. What was left was the poll,
and it costs nothing to run fast: 240 checks over 60 s spend 159 ms of
CPU altogether (0.26% of one core), because a check is three `stat` calls
and only a real write pays the 33 ms copy.

`[notify] watch` says how much of it to take:

| | |
|---|---|
| `cowork` (default) | Cowork's — `cowork-idle-…`, `cowork-awaiting-…`, "done using your computer" — and anything new the app raises. Claude Code's own sessions are skipped: the `Stop` hook above has already carded every one of their turns, and two cards for one turn is worse than none |
| `all` | those too, for a machine with no hook installed |
| `off` | never opens the file |

A Cowork card raises the Claude window and stops there. It cannot land
on the session: a Cowork id is a `cse_…`, and both deep links the app
advertises for one are refused by a flag on Anthropic's side (the log
lines are in `notify_hook.py`). A **Claude Code** card from this route
*can* — the toast's `Group` is `session-local_<uuid>`, which is the very
id `claude://resume?session=` wants and which `notify_hook.session_link`
otherwise has to dig out of the app's own store.

**Claude Chat raises nothing, and no setting changes that.** The desktop
app's notification service knows two products, `ccd` and `cowork`, and
three kinds — idle, permission request, ask-user-question (its own
bundle, read 2026-09-04; four days of that database agree). A chat reply
that finishes is not announced to Windows, to a hook, or to anything else
on this machine, so there is nothing here — or in any other program — to
hear. If that ever changes, it needs no code: an unrecognised Claude
toast is still shown, as `claude` / `info`.

Note also that the app only toasts a session you are **not** looking at,
so these cards arrive exactly when you are elsewhere, which is when you
wanted one.

**Sending one by hand.** From PowerShell, against the running app:

    $t=(gc 'C:\Users\shimr\Desktop\Organized\Projects\DeskIT\server_token.txt' -Raw).Trim(); irm 'http://127.0.0.1:8756/notify' -Method Post -Headers @{Authorization="Bearer $t"} -ContentType 'application/json; charset=utf-8' -Body '{"title":"Claude finished"}'

(`-Raw` matters: without it `gc` returns an array and the header is
wrong; and `irm` on PowerShell 5.1 throws on any non-2xx, which is the
right behaviour for a one-liner.) Or, from any program, the same script
Claude uses:

    notify_hook.py --title "Build done" --body "17 tests, 0 failed" --source myapp --kind done

`--project` and `--session` are optional; `--url` and `--token-file`
override where it posts; `--hwnd` and `--app` name the window a click on
the card should raise, for a program that knows its own handle and would
rather not have the parent walk find its console's. The reply is `{"ok": true, "id": 12, "unread":
3, "coalesced": false, "held": false}` (`held` is `true` for a finish
still waiting for its session to go quiet); `401` for a bad token, `400` for a body that is
not a JSON object (an *empty* body is a 400 too — always send at least
`{}`), `503` when `[notify] enabled = false`. `/notify` is POST-only and
token-gated like every other route, which matters because `tailscale
serve` fronts the whole port.

**What is never interpreted.** Nothing in the body is parsed, formatted or
run. `title` is cut to 80 characters, `body` to 400, `source` to 40,
`project` to 60, `session` to 64 — each with a trailing `…` when cut —
control characters are stripped, unknown keys dropped, and the result is
drawn as text: every string on the card is its own picture through
`DrawTextW`, so a Hebrew title with an English word in it reads the right
way round, and the chrome (who, when, the project) is never concatenated
with the title or body. The dashboard's rows do the same through
`ui.draw_text`. A program on the far side of the token can make the card
say anything; it cannot make the app *do* anything.

**Reminders and coalescing.** While anything that may interrupt (see
`[notify] interrupt`) is unread the cue replays and the column comes
back every `[notify] remind_every_s` (default 120) seconds, at most
`[notify] remind_times` (default 2) times per arrival; then it waits
quietly in the Waiting pile and on the shelf, unread count intact. A quiet finish never
brings the column back on its own, and never keeps the reminders alive
on its account. The dismiss key, `Esc` over the column and **Dismiss
all** mark *everything* seen at once, because "seen" means you looked,
not that you clicked each one; the × on one card, and a click that opens
one card, mark only that one and leave the rest of the column standing.
Claude fires `Stop` and `Notification` a moment apart, so a second
arrival from the SAME source within `[notify] coalesce_s` (default 5)
seconds skips the second cue; the item is still stored, its card still
goes on top of the column, and the reply says `coalesced: true`.
Coalescing is keyed on the SOURCE and holding on the SESSION, on
purpose: the first is about one sender's two hooks landing together, the
second about which of many sessions has actually gone quiet, and every
Claude Code session sends the same source. Reminders are never
coalesced. `[notify] cue = false` keeps the cards and drops the sound.

**Where it goes.** Every arrival, reminder and dismissal is one line in
`notify.log` (`RECEIVED #12 from claude-code (done) | project
DeskIT | title 'Claude finished' | 212 chars | unread 3`,
`REMINDED 1/2`, `DISMISSED by key | 3 marked seen`); the last 100 items
live in `notify.json`, which the dashboard reads straight off the disk:
the **unread** ones are rows in the Waiting pile, newest first, each with
Go there and ×, and it follows the file while the window is open, app
running or not. There is no Notify screen any more, and the reason is the
one this whole window was rebuilt on — an unread notification is a thing
waiting for an answer, so it is a row in the one pile rather than a hero,
a strip and a list of its own. **Dismiss all** kept its place beside the
Waiting title; **Send a test** moved to Settings → The app, next to the
cue sounds it is a test OF. Both go through the running app, because the
cue, the card and the reminders live in the process with the hotkey in
it. `app.log` gets one
`notify: received` line per arrival and a `rejected an unauthorised
/notify` line per bad token. Both files are gitignored; titles and
bodies are other programs' words and stay on this machine. The column's
position is remembered in `[notify] x` / `y` when you drag it (`corner`
says where it starts before you have), and `scale` sizes it. Under
`anchor = "bottom"` that `y` is the column's BOTTOM edge, not its top —
which is the point: the pile grows away from the screen edge you put it
against, however tall it gets.

**Check it by hand.**
1. Dashboard → Settings → **The app** → **Send a test**: the cue, the
   card mid-height on the right ("Test · A test notification", Hebrew and
   English on one card), and on **Waiting** the title says one more thing
   wants an answer, with the row at the top of the pile.
2. Type a letter into whatever window you were in — it lands there, not
   on the card.
3. Leave the card alone: it stays, however long you leave it. At +120 s
   and +240 s the cue replays and the column comes back up; `notify.log`
   shows `REMINDED 1/2`, `2/2`.
4. **Send a test** twice more: three cards in a column, newest at the
   top, the whole pile growing upward from where the first one sat. Press
   the × on the middle one — it goes, the other two stay, and
   `notify.log` says `DISMISSED #2 by card | 1 marked seen`.
5. Tap `ctrl+alt+m`: the whole column goes, Waiting says nothing is
   waiting, `notify.log` says `DISMISSED by key`.
6. The PowerShell one-liner above twice within five seconds: one cue,
   two rows, `coalesced: true` in the second reply.
7. Set `[notify] quiet_s` to `20` for this one (it ships at `0`, where
   a finish is a card the moment it lands) and restart, then
   `notify_hook.py --kind done --session S1` (the command-line form
   above) twice a few seconds apart, and wait the twenty seconds out: no
   cue, the line under the Waiting pile says one finish is held, both
   replies say `"held": true`, and
   `notify.log` runs `HELD #1`, `HELD #2`, `SUPERSEDED #1 by #2 | same
   session`, `QUIET #2` — then ONE card, silent. A `--kind input` with
   the same `--session` inside the window lands and rings at once and
   takes the held one with it. Put the `0` back after.
8. The same one-liner with the wrong token: `401`, and `app.log` gains
   `rejected an unauthorised /notify`.

**Rejected, 2026-09-03.** *The desktop app's own notification*: it does
not fire for the owner, which is the whole reason this exists. *A `type:
http` hook* in `settings.json`, posting straight to `/notify` with no
script: Claude Code's docs do not say how a bearer token would be
interpolated into the hook's headers, and a hook that sends the event
unauthenticated would need the route opened up, which `tailscale serve`
forbids. *A named-pipe door* beside the dashboard's `control.py`: local
only, so the phone could never knock, and the phone is half the point.
What shipped is the same `HintCard` the second reading already uses, on
its own thread, dragged and remembered the same way.

## Report a problem (`ctrl+alt+r`)

The owner's own bug list, and one typed line is all it asks for.

Something is wrong — the list on **Said** shows yesterday's count, a
dictation comes back with a tail nobody said — and by the time it is
worth writing down, everything that would have explained it is gone. So
the report key anywhere, or **Report a problem** beside the title of the
dashboard's **Waiting** place, opens a small card; you type the one line and press Enter, and the app is already
standing there with the rest of the form filled in. That is the whole
design, and it is the argument the correction key already won: a note you
have to assemble by hand is a note you do not write, so the typed line is
the only thing ever asked of you.

**What it attaches, and why each piece.** *Where you were* — the place's
name from the dashboard, `dictation` or `anywhere` from the key — because
the screen you are looking at answers "where" every single time, and
asking would be asking you to type what the window already knows. *The
last dictation*, its raw text and its final text, plus everything in its
`recent\` sidecar: the seconds, the backend, the language and the
per-word confidences the live pass produced. *A copy of the recording*,
pinned into `problems\`, because `recent\` is a ring of `[vocab]
keep_audio` clips (50 by default) and a report nobody has answered yet
outlives it by weeks — the audio is the only thing that can still settle
what was actually said, and `study.py`'s corpus copies for exactly this
reason. *A screenshot* of the screen as it was a moment before the box
opened. And *the settings that explain a bad dictation*: `backend`, the
real `[local] model` name rather than the word "local", `beam_size`, the
English model, `[vocab] enabled` and `replace_after_hits`, `[polish]
when`, `[punctuate] auto`, `[review] enabled`, `max_seconds`, the branch
that was checked out and the Python it ran on. The clip is filed under
the stem of its wav, which is the id `review.json` already files the same
clip under, so a problem and the second reading of one recording can be
laid side by side later without either store knowing the other exists.

**The screen is photographed before the box exists.** Both doors grab
first and open the card second, and that order is the reason the key is
one method rather than two: a report about the thing on the screen wants
the screen, not a photograph of the question being asked about it. It
costs 47–57 ms for the grab and about 60 ms for the JPEG (`visual_qa.py`
measured both, and encodes it down the same 1344-pixel path the
ask-the-screen key uses), which is why all of it runs on its own thread —
nothing that slow may happen inside the keyboard hook's 300 ms, where a
stall does not slow this feature down, it drops every keystroke on the
machine. `[problems] shot = false` turns the picture off and leaves the
line and the settings.

**Five minutes, or the dictation is not blamed for it.** A report filed
within `PROBLEM_LAST_MAX_S` of a dictation is filed *about* that
dictation — which covers "that came out wrong, let me say why", the press
that follows a bad transcript by the time it takes to read one — and past
it the report is about the app instead, with no clip attached and
`anywhere` where the tab name would be. A stale clip is worse than no
clip: this morning's transcript sitting in a report filed at midnight
still reads as evidence a week later, and it would be evidence for the
wrong thing.

**Dictate it, do not type it (2026-09-04).** Two measurements, and
together they are the whole shape of the field. The first: Tk cannot draw
a mixed line, and changing the widget did not change that. Typing
`הכפתור של Settings לא עובד אחרי restart` into the card's field *draws*
as `restart לא עובד אחרי Settings הכפתור של` — measured in a `tk.Entry`
and, when the field grew into a wrapping `tk.Text`, measured again in the
two side by side: **a `Text` scrambles it exactly the way an `Entry`
does.** The bytes round-trip correctly and the report is stored right;
only the drawing lies. So the echo line under the field, drawn through
`DrawTextW`, is mandatory rather than decorative — it is the only place
on either surface where you can read back what you actually said before
you send it. It is driven by a **60 ms poll of the widget**, not by a
write trace: a `tk.Text` has no `textvariable` to trace at all, and the
trace the old one-line box did run caught the keys and nothing else,
while one poll catches the typing, a dictation, a paste and an undo
alike. The better answer is still not to type: hold the dictation key and
say it, in whichever mix of languages the sentence wants. The second
measurement is why saying it needs two different mechanisms. Into the
**dashboard's** card a dictation simply pastes — the dashboard is a
separate process, so `injector` has no reason to refuse it and a Tk grab
does not stop a paste from outside the window either. Into the **key's**
card it cannot: that window is one of `main.py`'s own, and
`injector.is_our_window` (`injector.py:549`) refuses a paste into this
process deliberately — the placeholder marker would go in and the focus
test would then pass, so it could never be taken back out again. So the
transcript is *diverted* instead, handed to the card's `fill()`, which
puts the words in the field and stops there. Filled, never submitted:
`answer()` is what Enter does, and a decoder that mishears one word must
not turn into a bug report that says the wrong thing. The key is refused
mid-hold, like every other text key, but for its own reason — not because
there is no selection to act on but because there is no hand: one of the
two is on the dictation key. Latched it is allowed, and latched is
exactly the state in which typing a report while the microphone runs
makes sense.

**The card is the window.** It was a `Toplevel` with a title bar and a
strip of background around the card until 2026-09-04, when the owner
looked at it and asked for the card and nothing else — so it is
`overrideredirect`, sized to the card exactly, with Windows rounding the
corners, the way the correction box and the dashboard's dropdowns are.
What the frame used to provide comes from somewhere else now: `Enter`
sends, `Escape` cancels, and a click anywhere outside the card is "never
mind", which is the gesture a floating card asks for. That last one works
because of what a Tk grab does with the clicks it stops — measured
2026-09-04, a press on the dashboard under `grab_set()` is neither
discarded nor delivered to the dashboard, it is *reported to the grab
window* with coordinates relative to the card, so a point outside the
card's rectangle is a negative or over-long number and the screen
coordinates are the whole test. Losing the focus to another app is not a
cancel: you may well be going off to reproduce the thing you are
reporting, and coming back to a box you have to retype would be worse
than no box. The card carries five kind chips (`wrong`, `broken`, `slow`,
`idea`, `other` — `wrong` is the default because a wrong transcript is
what he will be reporting, and `other` is last, where a fallback
belongs), the thumbnail of the screenshot that is going with it, and Send
and Cancel. The chip he picks travels with the line: it is the `kind` the
report is filed under, from both doors.

**And the key's card is the same card, painted (2026-09-04).** The
hotkey path was reusing the correction box — a bare utility rectangle
with a one-line field in it — and the owner's verdict on seeing it was
"this is how it's supposed to look? because I don't think so". It has its
own painter now: `problem_card.py` owns the words, the geometry and the
picture, in pure Python plus Pillow with no Tk in it at all, the way
`hint.py` and `review_card.py` already stand behind the hint and
second-reading cards, and `overlay.ProblemCard` owns the thread, the
keyboard and the mouse. A painter you can render to a PNG is a card you
can look at without pressing the hotkey, which is how this one was wrong
for a week without anybody seeing it. Two things were rejected on the way
here. *Growing the correction box into the card* behind a mode flag: its
`_run` would have become a two-hundred-line body with a branch through
the middle of it, and that box IS the review pencil, the thing he uses
daily. `ProblemCard` is a subclass instead — it inherits the four things
that were hard (the foreground recipe, `open`, `answer`, `fill`) and
overrides only `ask` and `_run`, so the pencil's path is untouched and
provably so. It also fixed a live bug: while one object served both, a
report opening could divert a dictation meant for the pencil. *Building
it out of the dashboard's own widgets*: those are Tk widgets in the
dashboard's interpreter, and the hotkey path often runs with the
dashboard never opened — a second Tk interpreter cannot borrow widgets
from the first. What the two surfaces share instead is the copy and the
layout: the dashboard imports the field metrics, the hint and the keys
line out of `problem_card`, so two surfaces of one feature cannot come to
phrase it differently.

**The field, since he asked for it to be designed.** "When I'm where I
need to write, the thing looks very slop and strict" — and it was: one
30-pixel line with the sentence jammed against the border, for a report
whose real limit is 600 characters. So on both surfaces it is now a
wrapping `tk.Text` that starts three lines tall and grows to eight,
clamped at those 600 characters (the field stops taking words where
`problems.clean` would otherwise cut them off silently on the way to
disk), with 12 pixels of interior room and `spacing3` set so a display
line is exactly 22 px — which it must be, because the well behind it is
*painted* from the line count the widget reports, and a well an inch
short of its own text is how the old one came to look strict. The well is
**rounded** and accent-lit only while the field has the caret: a square
box among rounded chips and rounded buttons was half of "strict" on its
own. The caret is the accent colour, `Ctrl+A` selects all, and the three
keys are **printed on the card** — `Enter sends · Shift+Enter for a new
line · Esc cancels` — because Enter changed meaning the moment the field
grew past one line and he must not have to discover that by losing a
sentence to it. The card grows *downward* from a fixed top-left as the
field does, so nothing he is reading moves: measured 2026-09-04, the
hotkey card standing 411, then 445, then 489 px tall as the field took
its second and third line, and the dashboard's going 454 → 510 → 454 as
a line was added and taken away again — the top-left the same pixel in
every one of those.

**Drag it by anything that is not a control (2026-09-04).** "Make it so I
could drag the card — everything beside the buttons and the text box, so
I can move it." So the handle is the eyebrow, the title, both hint lines,
the echo, the thumbnail and its caption, the margins and the background;
the five chips, Send, Cancel and the field are not, and the field keeps
ordinary mouse text selection. On the floating card that rule needed no
code to enforce: the painter's hit test knows only about the chips and
the two buttons, so *`None` is the definition of draggable* — the
thumbnail drags by never having been a region in the first place — and
because controls act on the **press** rather than the release, a drag can
only ever have begun on the background, which makes "a drag that ends
over a chip must not pick it" true without a line about it. The threshold
is four pixels, `CLICK_PX`, the notification stack's own number under its
own name. Two things had to be learned: `<Motion>` and `<B1-Motion>` share
one handler, because Tk sends the second *instead of* the first while a
button is down and a card bound only to `<Motion>` never moves at all;
and the real `tk.Text` sitting over the painted well means its presses
never reach the canvas, which is what keeps selecting a word working and
keeps the field from being a handle.

**The dashboard's box drags on one binding, and three measurements paid
for it.** A Tk grab funnels every press in the application to the grab
window, so there is exactly one `<Button-1>` handler and it decides by
**where the press landed** — outside the card's screen rectangle is the
cancel, inside on a control is a hand-off, inside on chrome arms the drag
(3 px of slop) — never by where the pointer ended up, which is what makes
a drag unable to read as a cancel and a cancel unable to arm a drag.
Measured that day: (1) `event.widget` can be the Toplevel even while the
pointer is over a child, because the grab is what delivered the press —
the same press on the title reported the `Label` once and the `Toplevel`
once, depending on whether the application was already active, so the
widget is asked of the screen through `winfo_containing` instead; (2) a
repaint mid-drag with a stale origin snapped the card back to where the
drag started, because the layout re-applies that origin on every change
and anything can repaint while the button is down — so the origin follows
the drag rather than being read at the end of it; and (3) **a saved
position must be clamped against the whole virtual desktop, not the
primary monitor** — this machine has a monitor at `x = -1920`, so a card
left there has a genuinely negative x and clamping it to the primary
would walk it home every time. That is also why "never dragged" is the
sentinel `-100000` and not `-1`: it has to be a number no desktop can
reach. Where each was left is remembered — `[problems] x`/`y` for the
floating card, `card_x`/`card_y` for the dashboard's box, two pairs and
not one, because the floating card lives on the desktop while the box
opens centred over the dashboard window, and one shared position would
fling the box off the window it belongs to.

**Reading them back: "the whole list".** An open report is one row in the
Waiting pile with **Fixed** and **Close** on it, which is all a report
that needs one word of you should cost. The rest of it — the evidence —
is behind *the whole list* at the foot of Waiting, where it used to be
the ninth of nine rail rows. Open reports come first, newest first, each
with its kind, where it came from, the line you typed, the raw → final of
the dictation drawn as a bitmap (mixed text again), and the screenshot as
a 220-pixel thumbnail in the corner — an attachment you cannot see is one
you cannot check, and the picture is the difference between a report
about the list on Said and a report about whatever was actually on the
screen. **Fixed** and **Close** answer one there too; below the open ones
are the answered ones with who answered them. Two things about that
thumbnail:
the long side is 220 because that is what a row can give a picture
without pushing the typed line off it and it is still enough of the
screen to recognise the place, and the decode is cached under (path,
mtime, side) — **measured 2026-09-04, 35.8 ms cold against 0.170 ms
warm**, a factor of 210 — which matters because the list rebuilds every
row on every scroll, and decoding the same JPEG a hundred times to draw the
same 220 pixels is the one cost that would make the picture not worth
having. The mtime in the key is what makes it safe:
a shot rewritten in place gets a new key rather than a stale picture.

**`problems.md`, for the weekly read.** It is regenerated from scratch
every time — when the list is opened and after every decision — open
items first, grouped by where they came from, newest first, then a short list
of what has been resolved and by whom. From scratch, and never appended
to, because it is read once a week by the owner *and by an agent working
through the list*, and a file that is appended to turns into a log, which
is the thing he already had. **Open reports are never trimmed.**
Answered ones age out at `[problems] keep_resolved` (200); an open one is
a question nobody has answered, and dropping it to save a kilobyte would
make the store lie about what is wrong with the app. That is
`review.json`'s rule for decided proposals, with the same reasoning
behind it.

**And the weekly read is a routine, not a promise to himself.** A
scheduled task runs `weekly_review.ps1` at **Saturday 08:00 local**,
which runs the local `claude.exe` in this repo on the project command
`/weekly-reports` (`.claude\commands\weekly-reports.md` — the same
command he can type by hand any day of the week). It reads every open
report through `problems.py` and writes three files into
`problems\weekly\`: a short Hebrew summary he can read in under a
minute, a deep plan in `PARALLEL_FEATURES_PLAN.md`'s own style, and a
full archive with the evidence paths. Then it closes and archives the
reports it actually understood, regenerates `problems.md`, and posts a
card through `notify_hook.py` so he finds out the way he finds out about
everything else. **It fixes nothing** — no code, no config, no commit. He
reads, discusses, approves, and the work happens in a normal session
afterwards, because a routine that both diagnoses and edits is a routine
that changes the app while he is asleep.

Two rules are the whole design, and both are his. **Archive, never
delete**: he was asked and he chose it, and `Store._trim` only ever drops
JSON rows — it never unlinks a pinned wav or jpg — so closing a report
loses nothing that could still settle an argument. **Never guess**: in
his words, if the run did not understand the bug or did not find the bug
he was talking about, it must not guess but ask. So a report it cannot
explain from its evidence gets a *specific* question at the top of the
summary and is **left open**, which keeps the pile showing
exactly the ones that need him; the routine remembers what it has
already asked and does not ask it again the following week.

**Rejected: a cloud routine (`/schedule`).** It was the obvious first
answer and it cannot work here. A cloud routine gets a fresh git
checkout of this repo and cannot see this machine, and `problems.json` —
with `problems\` and every wav and screenshot in it — is local and
gitignored on purpose, so the run would open an empty bug list. The
session-scoped alternative expires after seven days, which is shorter
than the interval it would be scheduling. A local scheduled task calling
a local `claude.exe` is the only shape that can read the store the
feature is about; anyone tempted to move this off the machine has to
solve that first.

**Where it goes.** `problems.json` is the store, edited by two processes —
the app when you press the key, the dashboard when you answer a row — so
there is a `problems.lock` beside it (`msvcrt.locking`), a per-process
temp name and one rename, exactly the shape `review.py` settled on: a
reader never sees half a file, and an unparseable one reads as empty.
`problems\` holds the pinned wavs, their sidecars and the screenshots;
`problems.md` is the digest. Reports are ids you can quote — a timestamp,
with a `-1` suffix if a second already has a report in it, the way
`spool.py` names recordings. Filing one writes a line to `app.log` and
puts a one-line note on the dashboard (`problem 20260904-201432 noted
— …`); there is no success cue, because the box disappearing is the
confirmation and every sound in `cues.py` already means something else.
Nothing here may take dictation down: every filesystem error in
`problems.py` is logged and swallowed, and the single deliberate
exception is an empty line, which is not a report. The one way this
feature ever did take the app down is worth knowing, because it is silent
— an `ImageTk.PhotoImage` left alive past its own interpreter is finalised
later, from whatever thread the collector is on, and calls into a Tcl that
is gone: `Tcl_AsyncDelete: async handler deleted by the wrong thread`, no
traceback, nothing in `app.log`. Measured 2026-09-04, it aborted the
process on the **second** card opened, never the first. The hint card's
teardown order is the fix, and it is now this card's: the picture goes
before the frame does. **All four of them —
store, lock, digest, folder — are gitignored**, and that is the
deliberate tension in this feature: a
report quotes what you actually said, pins the audio of you saying it and
carries a picture of your screen, so it gets `transcripts.log`'s rule and
stays on this machine — which means the weekly review reads local,
untracked files by design, and a fresh clone of this repo has an empty
bug list rather than his.

**Check it by hand.**
1. Press `ctrl+alt+r` over any window: the card, asking "What is wrong?",
   with `ON DICTATION` or `ON ANYWHERE` in the corner, the chips, the
   thumbnail and `Enter sends · Shift+Enter for a new line · Esc
   cancels` printed under the field.
2. Hold the dictation key and say the line, English words and all. It
   appears **in** the field, unsent, and the echo under the field draws
   it the right way round even though the field itself does not; the
   report is not filed until you press Enter yourself. Fix a word first
   if the decoder missed one, and `Shift+Enter` if it wants two lines.
3. `app.log` gains `problems: 20260904-… filed from the key, with the
   last dictation, with a screenshot`.
4. Dashboard → **Waiting**: the row is in the pile with Fixed and Close
   on it; **the whole list** has it in full, with the kind, the typed
   line, the raw → final of that dictation and a thumbnail of the screen
   as it was before the box opened. `problems\` holds the wav, its
   sidecar `.json` and the `.jpg`.
5. **Report a problem** beside the Waiting title: the same card, saying
   which place you were on in the corner. Type a mixed Hebrew/English line —
   the field draws it scrambled, the echo underneath draws it right — and
   keep typing past the third line: the field grows, the card grows
   downward under it, and its top-left does not move. Click the dashboard
   behind it: gone, nothing filed, no picture left in `problems\`.
6. **Fixed** on the open row: it moves down to the answered half,
   `problems.md` is rewritten with `1 fixed` and the item marked
   `fixed · dashboard`.
7. Drag either card by its title and drop it: it moves, and the next one
   opens where you left it. Press a chip and wander off before letting
   go — nothing moves, because a chip is not a handle. Drag from the
   title and release over a chip — the card moves and the chip is not
   picked.
8. `[problems] enabled = false`, restart: no key, no button beside the
   Waiting title, and `problems.json` left exactly where it was.

**Rejected, 2026-09-04.** *A text file* — open notes, write "the list on
Said shows yesterday's count", close notes: this is what he had, and it is
what this key replaces, because by the time a report is worth reading the
thing that would explain it is gone. *Asking him for the context* — which
tab, which dictation, which backend: every one of those is knowable
without asking, and a form is how a bug list dies. *A field for the
report's kind in the key's box*: five chips are right on the dashboard,
where he is already sitting and reading, and wrong at the moment he is
annoyed — the key asks one question and files under `wrong`. *Pasting
into the key's card* like every other text destination: impossible by
design, see `injector.py:549` above, which is why `fill()` exists. *A
write trace on the field* instead of the 60 ms poll: a `tk.Text` has no
variable to trace, and the trace the one-line box ran saw the keyboard
and nothing else — not a dictation, not a paste, not an undo. *A square
field*, which is what it had, and which the owner called slop. *Trimming open reports to a cap* the way `notify.json` keeps its
last hundred: there is no measurement to offer for that one, only the
argument — a bug list that forgets is not a bug list.

## Dictating from the phone

The phone records; **this machine transcribes**. That is the whole point —
a phone keyboard's Hebrew dictation is not the ivrit-ai fine-tune, and the
GPU here is already holding the model. The endpoint runs inside the running
app and borrows that loaded model, so it costs no extra VRAM.

Reachability is **Tailscale's** job. No port forwarding, no public IP, no
dynamic DNS. The socket binds to **loopback**, and `tailscale serve` fronts
it — which is load-bearing rather than incidental: Serve proxies to
localhost, so a server bound to the 100.x address instead would be
invisible to it. Nothing listens on any interface a stranger could reach,
not even the home LAN. A bearer token is required on top of that.

### There is an Android keyboard, and it is the way to use this

The web page below came first and still works. The **keyboard** is what you
actually want: a page can only leave the transcript on the clipboard, while
a keyboard commits it straight into whatever field has the cursor, in any
app, with nothing pasted.

It installs from this machine over the same private link — open
`https://<machine>.<tailnet>.ts.net/app.apk` on the phone — and it is built
by Gradle from `android/`. The app's one screen takes the URL and the token
(paste the whole `.../#t=...` line and both fields fill), grants the
microphone, opens the keyboard settings, and checks `/health` for a newer
APK than the installed one.

What the keyboard does, and what each part of it is for:

- **Hold the big button and talk.** Slide **up** to lock it on and keep
  talking hands-free — the phone's version of the left-arrow latch — and
  slide **down** to throw the recording away, which is Esc. A clock and a
  level bar run while it records, so a locked recording you walked away
  from reads as still running, and a microphone another app is holding
  stops looking like a quiet room.
- **The action key** does what the field's own blue key does: **Send** in a
  chat, **Search** in a search box, **Go** in an address bar, a newline in
  a note. It reads that off the field rather than guessing. Without it,
  finishing anything you dictated cost a switch back to the other keyboard.
- **`→ EN`** is Ctrl+F9 and **`, . ?`** is F2, with the same selection
  rules — a selection, or the whole field — and the same guarantees: the
  punctuator's reply is compared to your text letter by letter and thrown
  away if a word changed, and the field is left exactly as it was.
- **`⌫`, `␣`, `.` (hold for a comma) and `↶`.** Undo removes exactly what
  the keyboard last inserted, after checking it is still there, and refuses
  otherwise.
- **Password fields are refused outright.** Dictating into one would send
  the audio here and write the plaintext into `transcripts.log`, where it
  would stay. Same for any field flagged `NO_PERSONALIZED_LEARNING`.

**Everything you teach it with F8 on the desktop applies here too**, with
nothing implemented on the Android side at all: the phone only records,
this machine transcribes, with the same model and the same [learned
vocabulary](#teaching-it-the-words-it-gets-wrong). The repair pass runs on
this path as well, so the two cannot give different answers for the same
audio.

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
5. **For the keyboard**, open `/app.apk` from that same page, install it,
   then paste the whole `.../#t=...` line into the app's first field — it
   splits the URL and the token for you — grant the microphone, and turn
   the keyboard on in Android's settings. "Save and test" sends one second
   of silence, which proves DNS, Tailscale, TLS, the token and the model in
   a single round trip without you having to say anything.

On the page: hold the button, talk, release. The text appears and is copied
to the clipboard automatically. In the keyboard it goes straight into the
field instead, which is the entire reason the keyboard exists.

**Everything you teach it with `F8` on the desktop applies here too**, and
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

Two defences, both on by default:

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

### The guards used to cost you words, and that is fixed

This section used to claim the guards were "byte-identical output, ~8%
slower". That was measured on 2026-08-12 against a corpus with no long
clips in it, and both halves were wrong.

Tightening a threshold makes Whisper *reject* more windows, and every
rejected window goes down faster-whisper's temperature fallback ladder —
which **samples**. So the output was not byte-identical between runs, let
alone against the defaults. Measured 2026-08-28: one 25.2 s recording
produced **five different transcripts in five runs** at fixed settings,
ranging from 4 to 33 word errors. When a sampled attempt won, whole
sentences you had spoken were simply absent — 19 consecutive words in one
observed case, with the audio itself intact and loud.

The fix is one decoder argument, `temperature=[0.0]`: no ladder, one
attempt per window. The decode is now reproducible, and because a forced
window was costing up to six decodes instead of one it is also **58.7%
faster** (144.7 s → 59.8 s across the 50 recordings in `recent\`), with
identical text on 42 of those 50 and no decoder loops in either arm.

If you ever unpin it, understand what you are giving back: the ladder is
Whisper's standard escape from a repetition loop. `repetition_penalty`,
`cleanup.collapse_char_runs` and the loop warning in `local_whisper.py`
are the defences that remain.

**A warning for anyone benchmarking this app.** Every accuracy number
written down here before 2026-08-28 was taken from a single run of a
decoder that was not deterministic. The same beam-5 sweep over the same
six clips scored 10.16%, 42.97% and 14.84% WER on three consecutive
passes. Repeat your measurement before believing it.

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
more than swap words — more than 15% change in word count (in **either**
direction), or fewer than 75% of the words surviving. A rejected reply is
not retried and not reported as an error; the raw transcript goes through
untouched, exactly as if the pass were off. Failing closed is the only
acceptable failure mode for something sitting between your speech and your
cursor.

**A percentage alone was not enough, and that cost you words.** 15% of a
long dictation is a lot of words: the band silently accepted a 13-word cut
on a 90-word transcript, 35 words on 234, and 52 on 352. Meanwhile Groq's
reply can hit its token cap and stop mid-sentence — `gpt-oss` spends up to
402 hidden reasoning tokens out of the same budget, unpredictably — and
nothing was reading `finish_reason`. On 2026-08-27 two truncated replies
were pasted, one cut in the middle of a word.

Both halves are now closed:

- `translate.py` treats `finish_reason == "length"` as a failed reply, so a
  truncated answer falls through to the next backend instead of being
  accepted.
- `polish._tail_loss` rejects any reply that reproduces the transcript and
  then simply **stops** — a strict word-prefix — regardless of what
  percentage that is, and catches the mid-word case too. A genuine repair
  swaps words in the middle; only a cut answer ends early.

Checked against the 50 stored `raw`/`text` pairs in `recent\`: 49
legitimate repairs still pass, one is rejected, and it is the known
truncation.

**There is no Gemini fallback here**, unlike
[translating](#translating-to-english) and
[punctuating](#punctuating-what-you-just-dictated). It used to have
one, back when it ran a few times a day and every run cost you a wait. It
now runs on *every* dictation with nothing to limit it, so a stopped backend
falling through to Gemini would quietly send dozens of requests a day into
the 20/day/model free tier that `Ctrl+F9` and `F2` depend on. Those are keys
you press on purpose; this is a pass you never asked for on any particular
sentence, and it does not get to starve them. That rule has never moved.

**What did move is that the pass is no longer local-only** — on the fast
version, `[polish] prefer` chooses which backend repairs first:

| `prefer` | what it is | typical repair |
|---|---|---|
| **`groq`** *(default on fast)* | Groq's free API — no credit card, ~1,000 requests a day, **its own bucket** that nothing else in this app draws on, so it cannot starve `Ctrl+F9` or `F2` the way Gemini would | ~0.3–0.6 s |
| `cerebras` | the *former* first choice. Their free tier is gone — verified live 2026-08-22 on a fresh account: HTTP 402 on every model, cheapest plan $1,500+/month. Kept working rather than deleted, for whoever holds quota there | ~0.5 s |
| `ollama` | local `gemma3:12b`, no cloud ever. **This is exactly what classic runs** | ~4.7–5.5 s |

Whichever you name goes first and **the others follow underneath it**, the
local model always among them — so a missing key, a rate limit or a dead
network costs you *speed* and never repairs. That is also why the local
model is still warmed at startup even when the cloud goes first: the day
you need the fallback is the day the network is down, which is the worst
possible day to also pay 76 s of cold load. With no backend reachable at
all there is no repair, and your transcript stays exactly as pasted.

**The cloud leg sends transcript *text* off this machine.** Your audio never
does — the speech recognition is local whatever this setting says — but the
words go to Groq under their free-tier terms. `prefer = "ollama"` declines
that entirely, and costs you the seconds back.

<details>
<summary>One trap worth knowing before you swap <code>groq_model</code></summary>

`openai/gpt-oss-120b` is a **reasoning model**: it spends hidden tokens
thinking before it writes an answer. Given a token cap tight enough to
cover only the reply, it burns the whole budget reasoning and returns
**empty** — no error, no reply, just nothing. `translate.py`'s Groq backend
sets `reasoning_effort=low` and floors the cap at 256 to stop that, and a
model you name here inherits both. Their catalog also drifts:
`llama-3.3-70b-versatile` was the obvious pick and is no longer offered, so
list `/v1/models` and make one real call before trusting a name.
</details>

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

## Learning while you idle — the study pass (fast)

`Ctrl+F8` learns only when you stop to teach, and most dictations are sent
and forgotten. The study pass learns from the forgotten ones. A few
minutes after you go idle, the app takes a recording it already
transcribed (from `recent\`), decodes it three MORE ways — the Hebrew
model at a wider beam, the *general* model that is already resident for
language detection, and a looser-temperature pass — lets the decodes
vote, and has a language model adjudicate the words they disagree on.
Where that verified reading differs from what was pasted, the live pass
was probably wrong, and the difference becomes machine evidence for the
vocabulary. You never see any of it; nothing on screen ever changes.

The verified text is picked by two considerations, both enforced in code:

- **Acoustic fit** — every candidate word was produced by a decoder that
  listened to the audio. The adjudicator's reply is *rejected in code* if
  it contains a word no decode ever heard (`study.py::_safe_choice`), so
  it can choose between readings but cannot write its own.
- **Hebrew plausibility** — the adjudicator (the polish backends: Groq
  first, local fallback; text only, audio never leaves this machine)
  reads the whole sentence and picks the reading that is real Hebrew.

Machine evidence is deliberately weaker than anything you teach by hand:

| evidence | may become a hotword | may feed the polish glossary | may rewrite text |
|---|---|---|---|
| your `Ctrl+F8` correction | immediately | immediately | after `replace_after_hits` (2) |
| the study pass | after 2 *different* recordings, family A only | after 2 recordings | **never** |

Family A (unknown names — Latin or digits in the pair) can become
hotwords; family B (a real Hebrew word swapped for another) only ever
feeds the polish glossary, where the sentence around it gates the repair
— feeding it to the decoder would make Whisper emit common words
unbidden.

Two rules exist because the first measured run (2026-08-27, 48 clips)
demanded them:

- **The vote proposes, the adjudicator disposes.** Two of the three
  decodes share a model and share its habits, so "2 of 3 agree" alone
  mostly surfaced orthographic wobble (`ותעשה -> תעשה`,
  `שנייה -> שניה`) — and scored *worse* than the live text on the
  human-corrected clips (10.94% vs 8.59% WER). Nothing is learned unless
  the language model, reading the sentence, chose that reading.
- **A divergence must be the decoder's own testimony.** Where the repair
  pass already fixed a word, every fresh decode of the same audio still
  hears the original garble — so an unguarded diff would learn the pair
  *backwards* and teach the app to un-fix itself. Pairs whose heard side
  never appeared in the raw decode are dropped (`study.py`, the
  backward-learning guard).

Measured on this machine's own 48 recordings, second run (2026-08-27,
after both rules): 48 clips studied in 308 s of idle GPU time; 38 came back clean, 12 divergence pairs survived every guard (2 term, 10 context), and none acts yet — each still needs a second recording to agree. On the 6 human-corrected clips the verified text cost 12 word-edits against the live text's 11 (of 128 truth words, 9.38% vs 8.59% WER) — and that one extra edit turned out to be a mishearing the human correction itself had missed: `הבטח לי חשבון חדש` for a spoken `תפתח לי חשבון חדש`, caught by the pass.

Alongside the learning, verified `(audio, text)` pairs accumulate in
`corpus\` — **gold** when you corrected the clip yourself, **silver**
when every decode agreed with what was pasted — capped at
`[study] corpus_keep` (400). That is training data for a future LoRA
fine-tune of the local model on your own voice, which is where these
errors actually get removed at the source.

Costs and controls, `config.toml [study]`: runs only after
`idle_minutes` (3) of quiet, steps aside before every decode the moment
anything happens (a dictation that collides waits out at most ONE decode
of the shared model lock, not three), skips clips over
`max_clip_seconds` (120), and spends at most `llm_per_day` (60)
adjudications from the same free Groq bucket the polish pass uses.
`enabled = false` turns the whole channel off. `main.py --study` runs it
in the foreground over everything unstudied and prints what it found —
including, for clips you corrected, the verified text scored against
your own correction.

## The second reading — a card that asks, and learns only from yes (fast)

The study pass above learned in silence, and its lessons went into the
decoder's word list unseen — which is how nine everyday Hebrew phrases
came to sit at the tail of the prompt and, on 2026-09-02, turned a 2.8 s
dictation of five words into 29 (see `[vocab] hebrew_after_hits`). The
second reading (`review.py`) keeps the decodes and changes what they are
for: the moment a dictation has landed at the cursor, the recording is
decoded three more ways on the local models, a language model reads the
sentence for words that were probably misheard, and what it finds is
**shown** — a small card, mid-height on the right — instead of learned.
While `[review] enabled` is true the study pass stands down; the same
three decodes serve both.

The card is the sentence, not a pair of words. Each proposal is drawn as
the sentence would read after the change: the changed word on a pill, a
few words either side, and a reason beneath (`אוכלים מנטוס, לא מטוס`),
because "is this what you said" can only be answered against the
sentence. Three buttons, three keys that work while the mouse is on the
card (<kbd>V</kbd> yes, <kbd>X</kbd> no, <kbd>L</kbd> later), a pencil at
the end of every row (or <kbd>E</kbd> for the first) that opens a
one-line box for the word you actually meant — Enter accepts the card
with that word, Escape leaves it pending — and a bar under the title
that is the card's clock — 20 seconds, paused while the pointer is on
it. Two kinds of proposal:

- **A replacement**, from the language model (Groq first, the local
  model underneath; text only — audio never leaves the machine). It is
  shown the other decodes and your known confusions, and asked for
  mishearings only. Its answer is JSON, checked in code
  (`review.validate`): every "before" must be found verbatim in the
  text, spans are bounded, nothing may overlap, a reply that would touch
  a quarter of the words is thrown away whole as a rewrite — and every
  replacement needs a **witness**: another decode of the same audio that
  heard the new words, or a pair you taught (`[review] witness`). The
  first live card had flipped a correct `לחיברתי` to `לכיביתי` on the
  strength of the previous sentence; nothing had heard it.
- **A drop**, found without any model (`review.tail_drop`): a tail of
  words that no other decode heard and that the live decoder itself was
  unsure of. The decoder's per-word confidence is kept for this
  (`recent\*.json`, `"words"`) — on the 2026-09-02 clip the five spoken
  words scored 0.89–1.00 and the 24 invented ones 0.04–0.58, all stamped
  into the last 140 ms.

What a verdict does, and what nothing else may:

| you | the vocabulary | the text on screen |
|---|---|---|
| **Yes** | learns the pair as a `Ctrl+F8` correction would (one human hit, the backward-learning guard applies) | fixed in place — only if that window is still in front and still holds the pasted text exactly (the punctuation key's read-and-paste); otherwise taught, not fixed |
| **No** | nothing; the refusal is recorded | untouched |
| **Later**, or the clock runs out | nothing | untouched |

Nothing is learned and nothing is rewritten without a click. What the
card got no answer to waits as a row in the dashboard's **Waiting** pile
and on the shelf, with the same two buttons — Yes is the one gold button
on that screen — and the changed word on a pill inside the sentence. Nine
of the last 72 verdicts were given there and 63 at the card; the window's
job is the backlog, which is exactly what an unanswered proposal is. The
dashboard writes the verdict to `review.json` (gitignored, next to `vocab.json`)
and the running app learns it within seconds — or at its next start.

Measured on this machine with `main.py --review`, 2026-09-02, over the
17-18 clips a human had corrected — the hard ones by construction — one
run per setting of `[review] witness` (Groq's answers differ run to run,
so these are draws, not constants):

| witness | proposals | exactly the correction | right, the correction kept a garble | wrong | WER if all accepted |
|---|---|---|---|---|---|
| 0 (trust the model) | 13 | 4 | 4 | 5 | 10.19% → 9.12% |
| 1 | 11 | 3 | 0 | 8 | 9.97% → 9.97% |
| 2 (default) | 2 | 0 | 1 | 1 | 9.21% → 9.72% |

The model alone is a coin flip: the right ones with no witness included
`אלך על זה -> לך על זה`, `תשאל -> אתה שואל` and `מתגייסים סין ->
מתגייסים` (an invented word gone), and the wrong ones with exactly one
witness were mostly the general model's own mishearing dressed as
evidence (`אירוע -> רע`). The first live card, with no witness rule,
flipped a correct `לחיברתי` to `לכיביתי` on the strength of the previous
sentence. So the default asks for two witnesses, which makes the card
rare, and the reading's steady value is what needs no model at all: the
invented endings it finds from the decodes and the decoder's own
confidence, and the pairs you taught that it asks you to confirm. Set
`witness = 0` for more proposals and two in three of them wrong.

Controls, `config.toml [review]`: `card_seconds` (20; 0 = the list only,
no card), `corner` / `x` / `y` / `scale` (the card remembers where you
drag it, like the hint card), `max_changes` (4), the three keys,
`fix_in_field`, `max_clip_seconds` (120) and `llm_per_day` (200, from
the same free Groq bucket as the repair pass). `main.py --review` runs
the reading over every clip a human has labelled — the corpus's gold
clips and the corrected recordings in `recent\` — and scores its
proposals against the truth.

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
| `[polish] prefer` | `groq` | `groq` \| `cerebras` \| `ollama` — which backend repairs **first**; the others follow underneath it, the local one always among them, so this is a preference and never a commitment. `ollama` IS classic's behavior |
| `[polish] groq_model` | `openai/gpt-oss-120b` | strongest on Groq's free catalog (measured 2026-08-22). A **reasoning model**: without `reasoning_effort=low` and a 256-token floor — both set in `translate.py` — the reply comes back *empty*. Catalogs drift; `llama-3.3-70b-versatile` is gone |
| `[polish] groq_timeout_s` | `20` | a warm Groq answer lands well under 2 s, so past this something is wrong and the fallback should have the work |
| `[polish] cerebras_model` | `gpt-oss-120b` | only relevant while quota exists there — their free tier ended. Kept so returning is a config edit, not a code change |
| `[polish] cerebras_timeout_s` | `20` | same reasoning as `groq_timeout_s` |
| `[polish] ollama_model` | `gemma3:12b` | measured best of five on real clips; `""` = reuse `translate.ollama_model`. This is the fallback under whatever `prefer` names, so it matters even on the cloud path |
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
| `indicator` | `true` | the status dot in the corner (`[dot] corner`); never in Alt-Tab. The disc is a button that opens the shelf; the glow around it is click-through |
| `[dot] corner` | `bottom-right` | `bottom-right` \| `top-right`. Which corner of the primary monitor's **work area** the dot sits in — above the taskbar, never under it. The shelf and the key card open beside it there unless their own `corner` says otherwise. Read once at startup |
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
| `[lookup] max_chars` | `20000` | above this it refuses and spends nothing. WAS 5000, which select-all kept hitting ("it didn't translate") — long selections now reach the local model in ~3800-char parts with the box naming each part, so a page translates in visible stages. Still minutes of local time at the cap; a whole document is Ctrl+F9's job |
| `[lookup] prefer` | `ollama` | `ollama` \| `gemini`, and deliberately the **opposite** of the other two keys: this one is tapped while reading and would eat the whole 20/day/model tier that Ctrl+F9 and F2 depend on |
| `[lookup] model` | `gemma3:12b` | the Ollama model. Already resident for `[polish]`, so it costs no extra VRAM. Not `qwen2.5:7b` — measured, it answered `?");` for `brittle` |
| `[lookup] cold_to_gemini` | `true` | when the local model is not loaded, send *that one* lookup to the cloud and warm the local one in the background rather than make you wait 24.4 s |
| `[lookup] keep_alive` | `"30m"` | how long Ollama keeps the model in VRAM after a lookup. The 5-minute default expired mid-reading-session and cost 23.19 s on the next tap. Shared with `[polish]`, Ctrl+F9 and F2 — it belongs to the loaded model, not to this key — so raising it pins 7.6 GB of the card for that long |
| `[lookup] strip_niqqud` | `true` | drop the vowel points the model sometimes decorates its Hebrew with (8 marks in 4 runs out of 4 on one input). Combining marks only: the maqaf is left alone, or `בית־הספר` would come back welded into `ביתהספר` |
| `[lookup] dwell_ms` | `12000` | **dead — nothing reads it.** The box waits to be closed, by its `×` or by `Esc`. A box that took itself away on a timer was the complaint this key's rewrite answered, and a timer you cannot tell from a bug is worse than no timer |
| `[lookup] max_width` | `460` | pixels. 60 words wrapped to 9 lines measured 512 px wide unbounded |
| `[lookup] max_height` | `520` | pixels; a 22-sentence paragraph made an 896 px window, taller than some work areas. Past the cap the face shrinks (19 px down to an ~11 px floor) before overflow is trimmed with an ellipsis; a hand-dragged grip overrides both for that one answer |
| `[lookup] cache_entries` | `500` | answers kept in `lookup_cache.json` (~134 bytes each). A repeat is 0.00 s and one saved request; only selections under 200 chars are stored. `0` = no cache |
| `[lookup] skip_consoles` | `true` | refuse in console windows, where the copy chord becomes a real Ctrl+C for whatever is running there (reproduced 5/5) |
| `[capture] enabled` | `true` | both screen keys; `false` unregisters them entirely |
| `[capture] capture_hotkey` | `win+shift+s` | **tap** to capture a region: drag a box, Shift-drag a lasso, Enter for this monitor. On the clipboard and in `folder` before you let go. **The Windows key is the one modifier whose chords this app swallows** — measured: with the `s` eaten the Snipping Tool never opens, and a bare Win tap still opens Start, so nothing has to be disabled in Windows. `ctrl+f11` is still free if you want the system snip back |
| `[capture] record_hotkey` | `ctrl+f12` | **tap** to record a region to mp4, tap again to stop |
| `[capture] folder` | `captures` | relative to the **app**, not the working directory (this app launches from a .vbs, a shortcut and a scheduled task, and all three disagree). Gitignored — it is the most sensitive folder in the repo |
| `[capture] copy_to_clipboard` | `true` | CF_DIB + the registered PNG format, so Paint, Word, Chrome and Slack all find one they like and a lasso keeps its alpha |
| `[capture] after_shot` | `toast` | `toast` \| `editor` \| `nothing`. What happens when you let go. `toast` puts a small card in a corner with a thumbnail and the editor one click away; `editor` opens the editor immediately, the way this key used to; `nothing` is a pure grab-and-go |
| `[capture] toast_corner` | `bottom-right` | which corner that card appears in. Its own setting and not `timer_corner`'s, because the recording pill and the capture card can want different corners on the same desk |
| `[capture] toast_seconds` | `10` | how long it waits. The clock **pauses** while the pointer is on the card |
| `[capture] toast_stack` | `4` | how many cards may be up at once. The key is never refused — past this the oldest card goes early to make room, and it takes nothing with it, because every capture was on the clipboard before its card appeared. 1 to 8; a screen too short for that many holds what it can |
| `[capture] toast_in_shots` | `true` | may a screenshot **see** the cards? `true`, so you can photograph one and show it to somebody — the Windows flag that hides a window from a capture hides it from *your* grab too, which is why the camera card refuses it as well. It does not compound: the desktop is frozen before the deck is taken off the screen, so a card lands in a picture once and never eats the drag. `false` hides them from every capture and every recording |
| `[capture] always_save` | `false` | write **every** capture to `folder`, or only the ones you ask to keep. `false` means the picture is on the clipboard and nowhere else until Save is pressed — the one setting here that gives something up, in exchange for a folder that holds what you meant to keep |
| `[capture] copy_clip_path` | `true` | a finished recording goes on the clipboard as a **file** (CF_HDROP), so it pastes into a chat or a folder |
| `[capture] clip_folder` | *(empty)* | where screen **recordings** (`clip *.mp4`) go; empty means the same as `folder`. An absolute path is used as given — this machine sends clips to `Videos\DeskIT` and pictures to `Photos\Screenshots\DeskIT capture` |
| `[capture] fps` | `30` | measured achievable with zero dropped frames at 720p and 1080p; 1440p settles at ~28 and stays real-time because frames carry wall-clock stamps, not frame numbers |
| `[capture] quality` | `balanced` | `small` \| `balanced` \| `sharp` — crf 30/26/20. Screen content is flat colour and sharp edges, so these are softer than the same names mean for camera video |
| `[capture] cursor` | `true` | BitBlt does not include the pointer, so it is painted in. Without it nobody can tell what is being pointed at |
| `[capture] audio` | `off` | `off` \| `mic`. **Off on purpose** — a recorder that quietly opens your mic is a surprise. With `mic` the clip gets a track from the same microphone dictation uses (two streams on one device verified working here) and the bar grows a mute switch |
| `[capture] timer_corner` | `bottom-right` | `top-left` \| `top-right` \| `bottom-left` \| `bottom-right` \| `off`. Where the red-dot-and-clock pill sits. A corner of the **work area** of the monitor the region is on — never under a taskbar, never on the wrong screen. It is hidden from the capture, so a corner inside the recorded area is fine |
| `[capture] announce` | `true` | say "Recording started" for 2.6 s before shrinking to the pill |
| `[capture] max_minutes` | `30` | a backstop, not a budget: a key tapped by accident must not fill the disk overnight. `0` = no cap |
| `[camera] enabled` | `true` | the webcam key; `false` unregisters it entirely and nothing here can open the lens |
| `[camera] camera_hotkey` | `ctrl+f6` | **tap** for a live preview with a shutter. Space, Enter or the button takes the picture |
| `[camera] device` | `""` | which camera, matched as a case-insensitive **substring** (`"eMeet"` is enough). Empty = the first device that is not a *virtual* camera — OBS, Teams and NVIDIA Broadcast all install one and they sort ahead of the real webcam as often as not |
| `[camera] size` | `1280x720` | what the camera is asked for, as MJPEG. **Ask for MJPEG or you get a slideshow**: this camera offers 1080p at 30 fps as MJPEG and the same size at 5 fps as raw yuyv422, and DirectShow takes the raw one unless told otherwise. A camera with no MJPEG pin is asked again for whatever it has |
| `[camera] fps` | `30` | what it is *asked* for; a webcam that cannot manage it simply sends fewer (this one settles at 25 in this room, because the exposure it wants is longer than a thirtieth of a second) |
| `[camera] mirror` | `false` | flips **both** the preview and the file, or neither. Off because the commonest thing held up to a webcam has writing on it. `m` flips it while the window is open |
| `[camera] timer` | `0` | `0` \| `3` \| `10` seconds of self-timer to start on; `t` cycles it, `Esc` cancels a countdown before it closes the window |
| `[camera] folder` | `captures` | the same folder the screen captures use, so there is one place to look. Files are named `photo ...` rather than `shot ...` |
| `[camera] copy_to_clipboard` | `true` | on the clipboard the moment it is taken, exactly like a screenshot |
| `[camera] edit_after_shot` | `true` | open the photo in the screenshot editor, on the pixels where the preview was. `false` makes the key a pure take-and-go |
| `[shelf] enabled` | `true` | the panel beside the dot (see [The shelf](#the-shelf-ctrlaltd)). `false` unregisters the key entirely and nothing else changes: every card, every cue and the window go on working |
| `[shelf] shelf_hotkey` | `ctrl+alt+d` | **tap** to open the panel beside the status dot; tap again, or press `Esc`, and it closes. It never opens on its own and never on hover. Rebind from the dashboard's Keys place; `""` = no key, and then there is no way to open it |
| `[shelf] rows` | `5` | how many waiting things it lists before the rest become one `+N more` line that opens the window instead (`1` to `8`). It is also the height lever: five rows is a 648 px panel, three is 520 |
| `[shelf] corner` | `dot` | `dot` \| `top-right` \| `top-left` \| `bottom-right` \| `bottom-left`. Where it opens before you have dragged it. `dot` is the status dot's own corner (`[dot] corner`), where the panel opens beside the dot — above it at the bottom of the screen, to its left at the top — and never covers it. `[hint] corner` takes the same word for the same reason, so the corner is decided once |
| `[shelf] x` | `-100000` | the left edge of the panel where you last dragged it, in screen pixels. `-100000` = never moved: use `corner`. Same sentinel as `[notify] x`, for the same reason — a negative coordinate is real on a monitor to the left of the primary |
| `[shelf] y` | `-100000` | the top edge of that same panel |
| `[shelf] scale` | `1.0` | how big it is drawn, `0.6` to `1.4` |
| `[shelf] hush_notifications` | `true` | while the panel is open the notification column steps aside — the same cards are already listed on it, and two piles in one corner is one too many. They come straight back when it closes, nothing is marked seen and no reminder is lost |
| `[server] enabled` | `false` | the phone endpoint (see [Dictating from the phone](#dictating-from-the-phone)) |
| `[server] host` | `""` | `""` = the Tailscale address when up, else `127.0.0.1`. Deliberately never `0.0.0.0` |
| `[server] port` | `8756` | the port `tailscale serve` should front |
| `[notify] enabled` | `true` | the notify door (see [Notify](#notify--when-claude-or-anything-finishes-ctrlaltm)). `false` = `/notify` answers 503 and nothing is shown, stored or played |
| `[notify] cue` | `true` | play the three-note `notify` cue when one arrives and on every reminder. `false` = the card only |
| `[notify] card_seconds` | `0` | `0` = a card stays until you dismiss it, which is what a stack of them wants. Any other number is the old countdown, in seconds, **paused** while the mouse is on the card, with the reminders bringing the column back |
| `[notify] stack_max` | `5` | how many unread cards may be on screen at once, newest at the top. The rest wait in the dashboard's Waiting pile and on the shelf, and are counted on the bottom card as `+3 earlier`. `1` to `8` |
| `[notify] remind_every_s` | `120` | while something is unread, play the cue and show the card again this many seconds after the last time. `0` = never remind |
| `[notify] remind_times` | `2` | ...at most this many times per arrival, then it waits quietly in the dashboard's Waiting pile. `0` = never remind |
| `[notify] coalesce_s` | `5` | a second notification from the **same** source within this many seconds updates the card instead of playing a second cue — Claude fires `Stop` and `Notification` a moment apart. The item is still stored |
| `[notify] interrupt` | `input` | `all` \| `input` \| `none`. Which arrivals may **pull you out** — play the cue and keep reminding. `input` is only what is waiting on you (a permission, a question, an idle session) and what went wrong; a plain finish lands as a quiet card and waits there. `all` is the door as it was; `none` never makes a sound. Counted 2026-09-05: 87 of the last 100 cards were per-turn finishes, each rung and reminded twice |
| `[notify] quiet_s` | `0` | `0` = a finish (`done`) is a card the moment it lands — the shipped value since the afternoon of 2026-09-05, when the morning's 60 held 28 finishes and showed 26 of them exactly 60 s late. Any other number holds a finish that many seconds for the **session** that sent it to go quiet first; a second arrival from the same session inside the window retires the first unseen and waits in its place. A permission or a question never waits either way |
| `[notify] watch` | `cowork` | `off` \| `cowork` \| `all`. Which of the **desktop app's own** Windows notifications get a card here too — the only road in for Cowork, which runs in the cloud and has no hook to install. `cowork` leaves the app's Claude Code sessions to the `Stop` hook that already cards them; `all` takes those too; `off` never looks. Claude Chat is in none of them: a finished chat reply is announced to nothing on this machine |
| `[notify] corner` | `right` | `right` \| `left` \| `top-right` \| `top-left` \| `bottom-right` \| `bottom-left`. Where the card appears before you have dragged it; `right` is mid-height on the right edge, like the second reading's card |
| `[notify] anchor` | `bottom` | `bottom` \| `top`. Which edge of the column stays put as it grows. `bottom` grows a long message **upward**, so a column kept in the bottom-right corner never runs off the screen; `top` pins the top edge and grows downward, as it used to |
| `[notify] x` | `-100000` | the top-left of the card where you last dragged it, in screen pixels. `-100000` = never moved: use `corner`. Negative is real on a monitor to the left of the primary |
| `[notify] y` | `-100000` | same, vertically |
| `[notify] scale` | `1.0` | how big the card is drawn, `0.6` to `1.4` |
| `[notify] dismiss_hotkey` | `ctrl+alt+m` | **tap** to take the card down and mark everything seen, wherever the mouse is. Rebind from the dashboard's Keys place; `""` = no key |
| `[problems] enabled` | `true` | the report key and the dashboard's **Report a problem** button — his own bug list (see [Report a problem](#report-a-problem-ctrlaltr)). `false` unregisters the key, takes the button away and writes nothing; `problems.json` is left exactly where it is |
| `[problems] report_hotkey` | `ctrl+alt+r` | **tap** to open the report box over whatever is in front, wherever the mouse is. Rebind from the dashboard's Keys place; `""` = no key, and the button beside the Waiting title is then the only door. Lives in `[problems]` and is read as `Config.report_hotkey` like `[notify] dismiss_hotkey` is |
| `[problems] shot` | `true` | attach a screenshot of the screen as it looked a moment **before** the box opened — the tab, the dialog, the wrong number, all of which are gone by the time the report is read. Written into `problems\` beside the report and never leaves this machine. `false` = the typed line and the settings only |
| `[problems] keep_audio` | `true` | copy the recording the report is about into `problems\`, so it outlives `recent\`'s ring of `[vocab] keep_audio` clips: an unresolved report sits there for weeks and the audio is the only thing that can settle what was actually said. `false` = the report keeps the wav's name and nothing else |
| `[problems] keep_resolved` | `200` | how many **answered** reports to keep, newest first (`0` to `2000`). Open ones are never trimmed at any setting — a question nobody has answered is not a kilobyte worth saving |
| `[problems] x` | `-100000` | the left edge of the floating report card where you last dragged it, in screen pixels. `-100000` = never dragged, so it opens where it always opens. The sentinel is a number no desktop can reach: negative coordinates are real on a monitor to the left of the primary, and this machine's starts at `x = -1920`. Unvalidated, like `[notify] x` |
| `[problems] y` | `-100000` | the top edge of that same card |
| `[problems] card_x` | `-100000` | the left edge of the **dashboard's** report box, which keeps its own pair: it opens centred over the dashboard window, so sharing the floating card's desktop position would fling it off the window it belongs to |
| `[problems] card_y` | `-100000` | the top edge of the dashboard's report box |

## Design notes

Raw Win32 via ctypes (`WH_KEYBOARD_LL` hook + `SendInput`) — the
`keyboard` library was dropped mid-build after its event delivery proved
unverifiable here, and the raw hook exposes `LLKHF_INJECTED`, which gives
the clean rule: the hotkey works injected or physical, but only *physical*
other-key presses abort a recording, so the app's own synthetic Ctrl+V can
never kill one. Unit tests: see [Tests](#tests) — they run where you
cannot see them, on purpose.

## Tests

The suite is one file, `tests.py`, and it is not the file you run. It
stands up real windows — cards, the dashboard, overlays, the correction
box — and every one of them would land on top of whatever you are doing.
So it is run through `tests_quiet.py`, which starts it on a second
Windows desktop: a real desktop with a foreground window and a
clipboard, that nobody is looking at. Type this:

```
.venv\Scripts\python.exe tests_quiet.py --no-screen
```

and nothing appears at all. That is the command while you are at the
desk, and it has been the rule since 2026-09-07.

`--no-screen` is what makes it silent. Sixteen of the tests cannot live
on a hidden desktop — the ask card photographs the display, and the drag
tests move your actual mouse — so they are named in
`tests_quiet.NEEDS_SCREEN`, and without the flag they run in the open at
the end: about fifteen seconds of windows over your work with your
pointer taken away from you. With the flag they are skipped outright.

The price is that the exit code then covers only the tests that ran, so
the plain form

```
.venv\Scripts\python.exe tests_quiet.py
```

is still worth one run before you ship anything — start it as you get up
from the desk, and it will have finished those sixteen by the time you
are back. `.venv\Scripts\python.exe tests.py` is the same suite with
nothing hidden; it is safe to run while dictation is live, but every
window it opens is one you will watch it open.
