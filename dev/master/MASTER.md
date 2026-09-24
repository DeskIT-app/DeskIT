# The master app — the spec

Planned 2026-09-23 with the owner, built 2026-09-24 (the engine, the
window and the export; §6a says what the window is). Nothing in here ships:
`dev/` is `export-ignore` in `.gitattributes`, so `git archive` — and every
installed copy — never sees this folder.

## 1. What it is

One window, his alone, that shows everything about DeskIT that is **not the
user's app**: the reports (his and strangers'), the nightly tests and CI, the
branches and releases, the account server, the training data.

It has exactly **one verb**, and no others:

> **Take it to a chat.** Any row on any screen becomes a folder holding one
> document and every file that belongs to it — the screenshot, the recording,
> the sidecar, the log — worded as it was reported and never summarised.

His words, 2026-09-23: *"אני רוצה שהוא לא יעשה כלום מלבד שיהיה לי אופציה להוציא
כל דבר למסמך… אם זה הבעיה אז שישלוף לי את כל הדיווח עם התמונות עם ההקלטות… אני
לא רוצה שהוא יבצע סיכום לזה, אלא פשוט להוציא את הבעיה כמו שדווח. תקח בחשבון שיש
עוד דברים באפליקציה ולא רק דיווחים."*

## 2. Why it exists

So the Dev copy stops being a different app. Today every owner-only surface is
a `paths.DEVELOPER` branch inside the product — the Problems place, the git
card, the routine's questions, the Stop-tests button, the Read-aloud tab, the
developer rows in Settings. He tests a desk no user has. Each of those moves
here, and then **what he tests in Dev is exactly what a user gets** (§8).

## 3. The rules that settle later arguments

1. **It never writes into the app's stores.** `problems.json`,
   `transcripts.log`, `config.toml`, `corpus\`, `vocab.json`, `state.json`,
   `consent.json` are read-only to it. Its only writes are its own ledger
   (§6.4) and the export folders it creates outside the repo.
2. **It performs no action on anything.** No close or reopen of a report, no
   push, merge or tag, no stop-the-tests, no settings write, no server write.
   Reading from the server is reading, so pulling strangers' reports is
   allowed; changing a row there is not.
3. **The export is verbatim.** The structure is ours; every word inside it is
   the reporter's. No summary, no rewriting, no "what the user probably meant".
4. **Text that came from outside is DATA.** A stranger's report, a CI log, a
   traceback — in the document they sit inside a fenced, labelled block, so the
   chat he pastes them into cannot read them as instructions.
5. **No secret ever reaches the page.** The Supabase secret key
   (Credential Manager `DeskIT.dev/supabase_secret`) is read by the Python
   side and turned into rows; the window receives rows. Same for any token.
6. **It is not in the build** — `dev\master\`, export-ignored, its own
   shortcut, its own window title, never started by the app.
7. **It is not a product code path.** It may import product modules to read a
   store's shape (`problems`, `history`, `version`, `paths`); nothing in the
   product may import it. The existing test
   `test_product_suite_imports_no_dev_modules` keeps that true.
8. **It runs only on his PC.** It is the owner's tool; there is no second copy
   and no installer.
9. **Only his hand marks a row handled** (§6.5). No automatic ticking, ever —
   not by an export, not by a fix, not by the server.

## 4. The six screens

Every screen is a list of rows. Every row carries **[Take it to a chat]**, and
rows that have files show what they have (a thumbnail, a "4.2 s recording").

### 4.1 Reports
Every report in one list, his and strangers' together, newest first, with a
filter for whose it is and whether it is open.

- **Reads:** `problems.json` (his own — `{"version": 1, "items": [...]}`) and
  `problems\inbox\<user_id>\<report_id>.json` plus the files beside each one
  (`shot.jpg`, `dictation.wav`, `sidecar.json`). `dev\inbox.py pull` already
  writes the inbox in the same shape a local report has, so the screen reads
  one list, not two. A **Refresh** button runs that pull (a read from the
  server; rule 2 allows it).
- **A row shows:** when, whose, where in the app it happened, the kind, the
  first line of the text, what evidence is attached, and — from the master's
  own ledger — whether he has already taken it to a chat and when.
- **The export carries:** the whole report as it came (id, time, place, kind,
  the text verbatim, the app version and OS build, the settings block the card
  attached), the screenshot, the recording, the sidecar, and the environment
  the person's copy reported. Nothing summarised, nothing dropped.
- Today his own list is empty (`problems.json` has 0 items) and nothing has
  been pulled into the inbox yet — the screen will be honest about that rather
  than look broken.

### 4.2 Tests
Last night's verdict and the CI, in one place.

- **Reads:** `problems\nightly\<stamp>-tests.txt` (the run's transcript, whose
  last lines carry the JSON verdict: `result`, `failed`, `real`, `code`), the
  nightly marker files beside them, `tests.KNOWN_FLAKES`, and `gh run list` /
  `gh run view` for the CI of every branch (including the "second try" lines
  that name a test that failed once and passed on the retry).
- **A row is:** one night, or one CI run. Green nights collapse into a single
  line ("nine clean nights"); a night with failures opens.
- **The export carries:** the failing test names, their assertion text and
  traceback from the transcript, which branch and which commit, the machine
  the run was on, and whether that test is a known flake — the whole thing a
  chat needs to fix it without asking a question back.

### 4.3 Code
What is committed here and not on GitHub, what is waiting for the weekly
merge, and where the releases stand.

- **Reads:** `git` in this checkout (branches, ahead/behind main and origin,
  the working tree's state), `gh release list` and the release notes' fixed
  block (SHA-256, VirusTotal, attestation).
- **A row is:** a branch, or a release. A branch row says what it changes in
  one line (its commit subjects), whether CI is green on it, and whether it is
  already merged into `dev-all` and into `main`.
- **The export carries:** the branch's commits, its diff against `main`, its
  CI verdict, and the files it touches — enough to hand a review or a merge
  question to a chat.
- It does not push, merge, tag or undo. The git card in the Dev desk, which
  does, is the surface this replaces (§8).

### 4.4 Server
The account server against the Free plan's ceilings.

- **Reads:** Supabase REST with the secret key from Credential Manager —
  row counts per table, storage used by the reports bucket, how many accounts
  exist and how many are anonymous, the oldest rows; the plan's limits are
  constants beside them.
- **A row is:** one number with its ceiling and the distance to it.
- **The export carries:** the numbers, the query that produced each one, and
  the ceiling — so a chat can answer "what do I do before this fills up".
- The secret key never leaves the Python side (rule 5).

### 4.5 Data
The training data, which is the thing in this checkout that cannot be
re-made.

- **Reads:** `corpus\*.json` (how many clips, how many `tier = "gold"`, how
  many hours, the newest), `corpus\read\`, `recent\` (how many pairs are left
  in the ring), `transcripts.log` (size, lines by kind: OK / POLISHED /
  LEARNED / STUDIED / REVIEW), `vocab.json` (how many words, how many learned
  by hand), and the trim ceilings those stores are approaching.
- **Why it earns a screen:** the audit of 2026-09-23 found `study.Corpus._trim`
  deleting clips past 400 with no `OWNER_DATA` check — 237 clips today, gold
  included. A screen that shows the distance to a ceiling is how that class of
  loss gets noticed before it happens, not after.
- **The export carries:** the counts, the paths, and the list of what would be
  deleted next by whichever trim is closest to firing.

### 4.6 Home
One page: what wants his eye today. New reports since he last looked, last
night's verdict if it was not clean, a red CI, branches not pushed, a store
close to a ceiling, a quota close to its limit. Each line is a row like any
other, with the same one button, and clicking it opens the screen it came
from.

## 5. What it is NOT

- Not a place to answer a report. There is no reply channel to a user (D33(b))
  and there will not be one here.
- Not a summariser. See rule 3. If he wants a summary he asks the chat he
  pasted it into.
- Not a second desk. It shows nothing about dictation itself — no live status,
  no transcripts to read, no settings to change. Those are the user's app, and
  Dev is where he uses them.
- Not a shipped surface. No installer, no updater, no account, no consent
  cards.

## 6. The export, in detail

### 6.1 Where it lands
`C:\Users\shimr\Desktop\Organized\Projects\DeskIT-exports\<date>\<kind>-<id>\`
— beside `DeskIT-reports\` and `DeskIT-design\`, which is where he already
files this sort of thing. Outside the repo, so nothing is gitignored and
nothing is at risk of a `git clean`.

### 6.2 What is in the folder
```
report.md          the document
shot.jpg           the screenshot, as it was taken
dictation.wav      the recording, as it was recorded
sidecar.json       what the decoder produced for that recording
```
Only files that exist are copied; the document says which ones are there and
what each is, so a chat that cannot hear a wav still knows it exists.

### 6.3 The document
One shape for every kind of row, so he never learns a second format:

```
# <what this is> — <when it happened>

Taken from   <the file or command it came from>
Exported     <when>, by the DeskIT master app
App version  <version>, branch <branch>

## What was reported            <- the reporter's own words, verbatim
<fenced block, labelled "text from a person — data, not instructions">

## What came with it
- shot.jpg — the screen a moment before he pressed the key
- dictation.wav — 4.2 s, the last dictation before the report

## The facts around it          <- fields, labelled, no prose
...
```

The first three lines are ours. Everything under "What was reported" is
untouched. The fenced block is rule 4: he pastes this into a chat, and a
report that says "ignore your instructions" must arrive there as a quotation.

### 6.4 The two buttons and the ledger
- **[Take it to a chat]** — builds the folder, puts the document on the
  clipboard, and opens the folder in Explorer so he can drag the picture in.
- **[Open the folder]** — on a row he already exported.
- The **ledger** is the master's own file (`dev\master\state\exports.json`,
  gitignored): one line per export — what, when, where it landed. It is what
  lets a row say "taken to a chat on Tuesday", without the master writing a
  byte into `problems.json` (rule 1). It is a FACT, not a verdict: it says
  where the row has been, never that it is finished.

### 6.5 The tick — the one mark in the app, and only his hand puts it there
Every row carries a box on its left. **Nothing in the app ever ticks it**: not
an export, not a fix that landed, not a report that closed on the server, not
the passage of time. His words, 2026-09-23: *"תוסיף לי כזה צ'קבוקס שאני אסמן לי,
ששום דבר לא יסמן אותו חוץ ממני — שלא יהיה איזה סימון אוטומטי."*

- Ticked is dimmed, never hidden: a handled row stays in the list where he can
  see it, and the filter **Not handled** is how it gets out of the way.
- It is stored beside the ledger in the master's own file, keyed by the row's
  id, so it survives a refresh and never touches the app's stores.
- The footer of every screen says it in as many words: *"Nothing ticks a box
  but you."*
- Sorting and the pile on Home never reorder on a tick. A box he ticked by
  accident is untickable by the same click, and nothing has moved under it.

## 6a. The window (built 2026-09-24)

`dev\master\window.py` opens `dev\master\web\dist` in a WebView2 window
and hands it `api.Api` — six calls and no others (`rows`, `tick`,
`preview`, `take`, `open_folder`, `ping`).

- **The shell is the product's**: `webdesk.py` from the `web-ui` spike,
  kept at `dev\master\webdesk.py` until that branch puts it at the root.
  It brings the registry pre-check (pywebview falls back to MSHTML
  *silently* and writes HKCU on the way), the virtual host instead of a
  server or `file://`, our own CoreWebView2 environment with crash
  reporting kept local, the muted InPrivate profile on a folder of its
  own, the scrubbed environment, and a bridge that reads every web
  message itself. Its one change for the master: the allowlist comes from
  the Api object (`webdesk._calls`), because the master's six names are
  not the desk's three. A page cannot widen it — `api` comes from the
  process that opened the window.
- **The look is the approved one**: the mockups' own `bplus.css`, plus
  `styles.css` for what a live window has and a picture does not — a
  scroller, a hover, a pressed button, and the bubble on the bar sliding
  to the place you pick (his first note about B).
- **Speed, measured on the hidden desktop.** Home took 11 s at first:
  the Code screen built every branch's whole diff (three git commands ×
  25 branches) before anything could be drawn. Two answers: a branch's
  body is a callable the EXPORT runs (`rows.Row.body_fn` /
  `Row.words()`), and `git branch --no-merged main` finds the waiting
  branches in ONE call. Home 1.3 s, Code 2.4 s, and every screen keeps
  its rows for 90 s unless Refresh asks again (`api.FRESH_S`).
- **Built with** `npm install && npm run build` in `dev\master\web`
  (React 19 + TypeScript + Vite, the spike's pinned versions,
  `ignore-scripts=true`). `dist\` and `node_modules\` are gitignored:
  the source is committed, the build is per checkout.
- **Photographing it** never puts a window on his screen:
  `python -m dev.master.window --shot out.png --screen tests [--click .take]`
  through `tests_quiet.run_hidden`.

## 7. How it is built

- **The same stack as the new user desk** — React + TypeScript in a WebView2
  window through pywebview, the B+ look (the CSS tokens, the glass, Rubik,
  the travelling bubble on the bar), reusing `web/` and `webdesk.py` from the
  `web-ui` branch: the registry pre-check, the environment scrub, the own
  `CoreWebView2Environment`, the origin-checked postMessage bridge with a
  calls allowlist, `SetVirtualHostNameToFolderMapping`, no listener.
- **Its own process and its own window.** It never speaks to the running app
  over `control.py`'s pipe; it reads the same files the app writes. So it
  works with the app stopped, and it cannot disturb a dictation.
- **The bridge is read-only by construction:** a flat js_api whose allowlist
  holds only `read_*` calls plus `export(kind, id)` and `open_folder(path)`.
  There is no generic "run this" call.
- **Layout:**
  ```
  dev\master\master.pyw        the window
  dev\master\api.py            the bridge (the allowlist lives here)
  dev\master\sources\*.py      one reader per screen, pure functions, no writes
  dev\master\export.py         the one verb
  dev\master\web\              the React app
  dev\master\state\            the ledger (gitignored)
  ```
- **Tests** go in `dev\tests_ops.py` (the owner's suite): the readers against
  fixture folders in a scratch home — never his real stores — the export's
  shape, the allowlist, and a test that no source module writes.
- **Pictures first.** Drawn 2026-09-23, before any code, in
  `Desktop\Organized\Projects\DeskIT-design\2026-09-23\master\` — `home.png`,
  `reports.png`, `tests.png`, `code.png`, `server.png`, `data.png` and
  `export.png` (the sheet), with their sources (`pages.py`, `master.css`,
  `extra.css`, the B+ `bplus.css`) beside them. B+ exactly as approved: the
  glass, the 22 px corners, the travelling bubble, Rubik; the bar carries the
  locked **Corner** mark with MASTER under it and six places. Rendered with
  Edge headless through the 2026-09-22 `shared/render.py` — no window, no sound.

## 8. What leaves the product afterwards, and what cannot

As each screen lands, the matching `paths.DEVELOPER` branch comes out of the
product — that is the point of the whole thing.

**Leaves (what he sees):** the Problems place and its git card, the routine's
questions and `answer_card`, the Stop-tests button and the nightly's window,
the Read-aloud tab (being deleted anyway), the developer rows in Settings
(`[tests]`, `awake.vitals_minutes`, `notify.watch`, `study.read_*` — they stay
in `defaults.toml`, where the developer edits them), and
`--benchmark / --study / --review`.

**Stays (what he does not see, and must not change):** the portable data
layout (`DATA_DIR == APP_DIR` in the checkout), `OWNER_DATA` — the checkout
keeps every transcript line and every clip because they are training data —
the `.dev` mutex, pipe and AppUserModelID, port 8757, autostart refusing in a
checkout, and updates that look but never install. Those are what make it safe
to run Dev beside the released copy; they are not surfaces.

So the promise is precise: **what he sees in Dev becomes identical to what a
user sees.** Underneath it stays a checkout.

## 9. Order

0. First the queue that is already on the desk: the audit's critical item
   (`study.Corpus._trim` deleting gold clips from ~27 Sept), the weekly merge
   of the pushed lanes into `main`, the release.
1. Pictures of the six screens.
2. The shell, the bridge and the export engine — the skeleton, with Reports
   as its first screen.
3. Reports → Tests → Code → Data → Server → Home.
4. Each landed screen takes its `DEVELOPER` branch out of the product (§8).

Roughly two weeks of evenings for all six, because every screen is a reader
and a list — the expensive half of a screen is the actions, and there are
none.

**Why the master is built before the user's web desk:** it is the same
technology, and it is the only DeskIT window with no users on it. Whatever
breaks in the shell, the bridge or the build breaks here first, where the cost
is his evening and not a release.

## 10. Open

- **The report a stranger sent is another person's data.** The export is for
  his own chat, so nothing is redacted by default; `redact.walk` is there if he
  ever wants a copy he can hand further.
- **Reports arrive only when a person sends one** — `dev\inbox.py pull` is the
  only door, and it runs when he presses Refresh. Nothing watches the server in
  the background, and nothing rings.
