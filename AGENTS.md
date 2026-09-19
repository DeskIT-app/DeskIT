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
a vocabulary, a background study pass that re-examines sent dictations and learns without being asked (fast only, study.py), a second reading that re-reads every pasted dictation and proposes corrections on a card — learning only what is approved (fast only, review.py, review_card.py, overlay.ReviewCard, and a row in the dashboard's Waiting pile; it stands in for the study pass while on), a screenshot/screen-recording pair of keys, a webcam key
that takes a photo into the same editor, a phone endpoint, a hold that
keeps the machine awake for as long as the app runs and a key that puts
the screens off and keeps them off so the phone can drive it through
Claude (awake.py, Settings › Awake in the dashboard, `ctrl+alt+n`), a notify
door (notify.py, `POST /notify`, a cue and a STACK of cards that waits —
newest on top, anchored by its bottom edge so a long message grows
upward, nothing times out, a finish HELD until its session has been
quiet for `[notify] quiet_s` when that is set (it ships at 0 since the
afternoon of 2026-09-05: the card the moment Claude stops) and only the
`[notify] interrupt` kinds ringing — with reminders, `ctrl+alt+m` to
dismiss them
all, a × per card and a click on a card to go to whoever sent it — how
Claude Code says it is done, and, through the Windows toasts the desktop
app raises, how Cowork does too: notify_watch.py, `[notify] watch`; the
unread ones are rows in the dashboard's Waiting pile), a report key that files the owner's own
bug list with the evidence already attached — where he was, the last
dictation and a pinned copy of its audio, a screenshot of the screen a
moment before he asked, the settings that explain a bad transcript —
and is read through once a week off `problems.md` (problems.py,
`ctrl+alt+r`, problem_card.py for the card's face, a row in the Waiting
pile with the evidence behind "the whole list", **Reopen** on any
answered row and a **✕** that asks before it deletes, and a Saturday 08:00
scheduled task that reviews the list, writes the plan and asks about what
it did not understand rather than guessing: weekly_review.ps1,
`/weekly-reports`), a **shelf** and a **dashboard**.

**The shelf** (`ctrl+alt+d`; shelf.py, shelf_card.py, `skin\shelf.py`,
`[shelf]`) is a panel beside the status dot holding the state, the pile
of things waiting for an answer, the last dictation with Copy, the
screens and one door to the window. **It opens only on the key press; the
same press or Esc closes it; never on hover, never on passing the
corner** — that is the owner's rule, verbatim, and it is what the corner
being predictable depends on. Settings, the keys and the history are
deliberately not on it: those are things you sit down to. Since
2026-09-07 there is a fifth door out of it: **a press of a mouse button
anywhere outside the panel closes it** — his ask, verbatim, "if I press
outside of it, like on Google or something, the small tab that opens
when I press the dot will disappear, so I will not need to press the dot
again or the X". Two things about how that is done are load-bearing and
both are in shelf.py's docstring: the window is `WS_EX_NOACTIVATE` and
never has the focus to lose, so it is a GetAsyncKeyState poll and not a
focus event; and the STATUS DOT'S OWN SQUARE is spared, because the dot
is already a toggle and letting the watch see that press would close the
panel and let the dot reopen it in the same click.

**The dashboard** (`dashboard.py` + `ui.py` + `widgets.py`) is four
places along a 56 px top bar — no rail, since 2026-09-07:

- **Home** — a summary and nothing else: one title line and a second
  line saying whether what you can see is all of it, one card as tall
  as its rows holding the newest THREE of the merged pile (notify
  unread + review pending + problems open + questions pending), a band
  of five door tiles under it — always all five, whatever is waiting,
  each with what its place is holding and the whole tile the way in —
  one line each for the rest of the day, a fixed footer of facts. It
  fits without scrolling AND without a hole: the band takes whatever
  room the pile is not using and the ground under it lands the day on
  the footer rule, so the page is exactly PAGE_H whether nothing, two
  things or more than fit are waiting (a test holds all three).
- **Corrections** — every pending proposal of the second reading, with
  the vocabulary panel beside it.
- **Problems** — his reports, the routine's questions and what is
  committed on this computer but not on GitHub (Restart / Push / Undo):
  everything that needs more than a line.
- **Said** — `transcripts.log` read back (history.py), search, filters,
  SAID_PAGE rows at a time behind a Show more.
- **Keys** — the bindings lit on a drawn keyboard (keycaps.py); click a
  cap, or press a real key, to see what it does and rebind it.
- **Settings** — General, Screen, Phone, Privacy, The app (settings.py:
  TABS names the forty-odd lines the screen draws, with their plain
  words; every other line of defaults.toml is a measurement the
  developer edits in the file and the screen never shows — the owner,
  2026-09-18: "I am the user; you are the developer". A path is named
  by exactly one tab, a test holds it). The app carries This PC (the
  model, the GPU pack) and the blocks that used to be rail rows: Awake,
  Stop, Send a test, the cue sounds, the files. No sentences, no
  "Everything", no fold, no Dictation/Text/Cards/Speed tabs — each
  removed on the owner's word.
- **The bar's buttons follow the state and nothing else**
  (`_paint_bar_buttons`). Model off: ONE button, Start. Model on or
  paused: Pause (Resume) and Stop, with Screens off between them. His
  rule, 2026-09-07, and he gave it twice. Stop used to ARM — the first
  press only turned the word into "Stop again" — and he read that word,
  could not tell what it was for, and asked for it gone. Do not put a
  confirmation back. The 25 seconds of model loading it was paying for
  are guarded by the LAYOUT now: Pause keeps the right edge of the bar in
  every state so the key he presses all day never moves, Stop sits 168 px
  away at the far end of the group, and Stop is not drawn at all while
  there is nothing to stop. The shelf's Stop still arms — see
  `main.App._shelf_stop`, and the note there for why.
  **Since 2026-09-18 Stop unloads the MODEL, not the process**
  (`main.App.unload_model` over the pipe verb `unload`; Start with the
  process up sends `load`): the speech model, the microphone stream and
  the learning engines go, `transcribers/off.py` stands in, and the
  hook, the dot, the cards and every key that needs no model keep
  working — `hotkey.set_dictation_off` refuses only the hold keys with
  `MODEL_OFF_WORDS`. status()["model"] is on/off/loading/unloading; the
  chip says Model off and the bar reads one button, Start. **Opening
  the desk with nothing running starts the app WITHOUT the model**
  (`dashboard.bring_up_the_keys` → `launch.start_app(model=False)` →
  `main.py --no-model` → `App(cfg, model=False)`: 0.7 s to a live hook,
  grey dot, every tap key working; the model download offer is skipped).
  The whole
  process quits from Settings > The app > Quit DeskIT or the shelf —
  never from the bar's Stop, a start-up included: the first version
  quit there, he pressed Stop at "Starting" to try the unload and the
  app died under him (22:19). His words: "many things don't need the model — screenshot,
  screen recording and a few more — make those work without it."

  It went nine rail rows -> four places -> three -> six, every step on
  his word. Do not re-litigate the count without one.

Everything is documented, with measurements, in `dev/README-dev.md`
(the owner's working notes — the root `README.md` is the public front
page since 2026-09-18 and ships in `app\`) and `config.toml`.

**There is ONE version of the app.** There were two — `classic` (local
gemma3:12b repair, ~5 s) and `fast` (repair sent to Groq's free API first,
~0.3–0.6 s) — switched by a `Versions.vbs` launcher, the dashboard, or `versions.py`.
All of that was removed on 2026-09-08 on the owner's word: "I want only to
be on this version that is already running." `classic` had been absent
from the machine for a fortnight and the trunk sat BEHIND the branch he
ran, so the only trip left was backwards. `versions.py` is now one
function returning the branch name.

The old invariant — both branches committing a byte-identical
`config.toml`, and every shared file mirrored across — is retired with the
switcher. **Do not restore it, and do not mirror anything to `classic`.**
The fast repair pass survives as a setting, not a version:
`[polish] prefer = "groq" | "cerebras" | "ollama"`, where `"ollama"` is
exactly what classic did.

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
   TOML round-trip would delete hours of work. `settings.py` reads the
   file for the Settings place: a `gemini | local` at the front of a
   comment is that key's menu, and the comment is what the search box
   finds a line by. Since 2026-09-18 the place draws ONLY the lines
   `settings.TABS` names, in the plain words written there; a new key
   is the developer's unless a person has a reason to change it, and
   then it gets a `Friendly` row on the tab it belongs to — never a
   section of the file drawn whole.
7. **Do not end a turn mid-task to report progress — every turn end
   rings the owner's desk.** Claude Code fires its Stop hook at the end
   of EVERY assistant turn, and that hook is the notify door
   (notify_hook.py): a "now I will do X" lands as a card, a three-note
   cue and two reminders, exactly like a real finish. Counted
   2026-09-05 off `notify.json` / `notify.log`: 87 of the last 100
   cards were per-turn finishes ("Claude finished"), 52 of them from
   ONE session, and only 5 were the permission prompts he actually
   wanted; the median gap between finishes was 170 s, the shortest 3 s.
   The door can hold a finish until its session has been quiet for
   `[notify] quiet_s` — but that ships at 0 since the afternoon of
   2026-09-05, because the morning's 60 s hold never once released
   early (26 of 28 held finishes were shown exactly 60 s late, 2 were
   retired by a newer turn) and the owner wants the card the moment
   Claude stops — and lets only the `[notify] interrupt` kinds ring.
   No door can tell a finish from a progress note — only the session
   can, and with the hold off every turn you end is a card on his
   screen at once. So finish the job and report ONCE, at the true end.
   When you genuinely need an answer, ask once, at the point you need
   it, and batch the questions into that one message. A permission
   prompt and a question are the only things that should reach him
   mid-task. This binds Cowork and cloud sessions working on this repo
   too: their toasts come in through the same door (notify_watch.py,
   `[notify] watch`) and land on the same desk.
8. **Every test run happens on a hidden desktop — while he is at the
   machine the command is `.venv\Scripts\python.exe tests_quiet.py
   --no-screen`.** His words, 2026-09-07: "מהיום אני רוצה שאת כל הטסטים שאתה עושה לעשות בשולחן נסתר כמו שאתה עושה עכשיו, זה נהדר ולא קופץ לי על המסך" —
   from today, do every test on a hidden desktop the way it is being
   done now; it is excellent and nothing jumps onto his screen.
   `tests_quiet.py` starts `tests.py` — and then `dev\tests_ops.py`, the
   owner's half of the suite since PR 8 — on a SECOND Windows desktop
   object (`CreateDesktopW` + `STARTUPINFO.lpDesktop` + `CreateProcessW`),
   so every window the suite stands up — cards, the dashboard, overlays —
   is born where nobody is looking. Sixteen tests cannot live there and
   are named in `tests.NEEDS_SCREEN`: the ask card grabs the
   display with `ImageGrab`, the drag tests move the REAL mouse. Without
   `--no-screen` those sixteen run in the OPEN at the end, which is
   about fifteen seconds of windows over his work with his pointer taken
   — exactly what he is objecting to. `--no-screen` skips them outright
   and the whole run is invisible. The price is that its exit code then
   covers only what ran, so the plain `tests_quiet.py` still has to
   happen once before shipping: when he is away from the desk, and only
   after saying so. `.venv\Scripts\python.exe tests.py` is the product
   suite in the open — never reach for it while he is sitting there;
   `tests.py --no-screen` is the same minus the sixteen, and is what
   the product CI runs (`.github/workflows/ci.yml`).

   **And the user, simulated — `dev\user_sim.py` (2026-09-18, his ask:
   "you test through the code, not through use; build a tool that
   behaves like a user — Start and then Stop right after is not
   if/else").** A REAL `main.App` (fake speech backend, a second of
   pretend load, the paste and the clipboard stubbed, no singleton, no
   pipe, silent) driven at a person's pace: the desk's buttons through
   the pipe verbs the desk sends, the keys through `machine.handle`,
   eight scenarios in the order a person meets them, one table at the
   end. Its first run caught a `--no-model` start dying in `__init__`
   (a line that read `self.dot` before the dot existed) that no unit
   test saw. Run it hidden after any change to start/stop/load/unload,
   the dot, the hook or the bar: `.venv\Scripts\python.exe -c "import
   tests_quiet as q, pathlib; q.run_hidden(r'.venv\Scripts\python.exe
   dev\user_sim.py', pathlib.Path('.'))"`.

   The rule is not only about the suite: `tests_quiet.run_hidden(command,
   cwd, desktop=...)` is importable, and any probe, screenshot or
   throwaway script that would put a window on his screen goes through
   it. **AND IT MAKES NO SOUND.** He said both halves again on
   2026-09-08, after a screenshot driver put a second dashboard on his
   screen: "when you're testing the app, please do it only in a
   different monitor, like in a hidden monitor, so it will not appear on
   my screen — if you can, also mute it". A hidden desktop hides the
   WINDOW and not the beep, so a driver silences itself at the source,
   before it imports anything of the app's: `winsound.PlaySound` and
   `winsound.Beep` to no-ops (`cues.play` is winsound), and
   `tk.Misc.bell` with them. And moving the window off-screen is not a
   substitute for the hidden desktop — it does not even photograph:
   PrintWindow gave back a dashboard half-painted with the screen it had
   been dragged over (2026-09-08).

   **The sixteen have their own hour now, and you do not have to ask him
   for it.** `--no-screen` was days old before anyone noticed that the
   sixteen it skips had therefore not run at all, so there is a Windows
   scheduled task at 02:55 (`nightly.py`, `nightly_tests.ps1`) that runs
   the WHOLE suite — `tests_quiet.py` with no flag — while nobody is
   here. It asks on screen first and **no answer means RUN**: he
   rejected an idle check because "מישהו יקום באמצע הלילה לשתות והבקבוק
   ייפול לי על המקלדת ואז היא תחשוב שאני כאן", a bottle on the keyboard
   looking exactly like him being present and cancelling the run in
   silence. A clean night files nothing; a failing one leaves one report
   on the Problems place for Saturday. None of that changes what YOU
   type while he is at the desk: that is still `--no-screen`, every
   time.

## The machine

- Windows 11, Python 3.11 venv at `.venv\` (stdlib-first: cloud APIs go
  through plain HTTP in `net.py`; avoid new pip dependencies).
- GPU: 16 GB VRAM. Budgeted: two Whisper models (~6 GB) + gemma3:12b
  resident in Ollama (~8.5 GB). Adding model residency means evicting
  something — check `nvidia-smi`.
- Mic: Arctis 7 headset, device index `"1"`, 16 kHz mono WAV everywhere.
- Ollama at `http://127.0.0.1:11434` — **127.0.0.1, never localhost**
  (localhost resolves ::1 first and costs ~2 s of refused connection).
- Keys: Windows Credential Manager first (`DeskIT/groq`, `DeskIT/gemini`
  — `main.py --set-key groq`, `--keys` lists what is where), then
  `DESKIT_GROQ_API_KEY` / `DESKIT_GEMINI_API_KEY` in the environment, then
  the gitignored `.env` beside `main.py` — read in THIS checkout only
  (portable/developer mode). `secretstore.py` is the one reader; every
  client asks it through `apikey.py`. `CEREBRAS_API_KEY` and
  `GOOGLE_API_KEY` are no longer read at all. Gemini: translate/punctuate/
  dictation fallback pool, 20 req/day/model; Groq: repair pass, ~1,000
  req/day. The phone token is `secrets\phone_token.bin` (DPAPI), moved
  there from `server_token.txt` on the first start after 2026-09-17.
- Network: every outbound request leaves through `net.py` — `request()`
  / `post_json()` / `open()` (streamed), each with a `purpose` from
  `net.PURPOSES` and, for a cloud host, `secret="groq"` / `"gemini"` by
  NAME; `net.py` looks the value up, attaches it in that provider's
  header and never sends it anywhere else (`SECRET_HOSTS`). Hosts are
  the frozen `net.ALLOWED_HOSTS`; anything else is `EgressRefused`
  before a socket opens. One row per call — host, purpose, bytes,
  status, secret name, never a body or a URL — in `net.rows()` and
  `network.log` (gitignored). A test stands in for the wire at
  `net._connect` (tests' `_FakeRaw`). Gemini is `gemini_pool.Client`
  (REST, plan 5.6): `generate(model, parts, system=, temperature=,
  thinking=)`, `list_models()`, `APIError` with Google's message and the
  parsed body; the SDK is gone.
- Consent: nothing personal leaves until the person said so. `privacy.py`
  holds six gates (`cloud_text`, `cloud_audio`, `cloud_screenshots`,
  `account`, `report_upload`, `settings_sync`) that open ONLY through
  their consent card (`privacy.grant`) — never a settings write, never a
  config edit — and two switches (`update_check`, `offline`). A cloud
  constructor's first line is `privacy.require(kind)`; `net.py` asks
  again per request. `consent.json` beside the settings is the record;
  the Settings page's Privacy tab shows it and offers Withdraw. The
  card (`consent_card.py` words + `overlay.ConsentCard`) opens on the
  first key press that needs the cloud — a controller wraps the press
  in `privacy.pressed()`; outside one a refusal is silent. From a
  terminal: `main.py --consents / --consent KIND / --withdraw KIND`.
  Tests open a gate with `_consented("cloud_text")` — in the scratch
  home, never in the owner's file.
- Owner-only surface: the git block, the routine's questions and
  `problems.md`, the nightly tests, the Read-aloud tab, the `[tests]`,
  `awake.vitals_minutes`, `notify.watch` and `study.read_*` rows, and
  `--benchmark/--study/--review` exist only while `paths.DEVELOPER` is
  true (the `.git` beside `main.py`). A new owner tool goes behind the
  same flag (`dashboard.corr_tabs`, `settings.developer_only`).
- Logs: `app.log` never quotes dictated text, a learned pair, the phone
  link or a key — counts and names only (D8); the words live in
  `transcripts.log` (`OK`, `POLISHED`, `LEARNED`, `STUDIED`, `REVIEW`…),
  which `[history] keep_days` prunes on a stranger's copy and NEVER on
  this checkout (`paths.OWNER_DATA`). Anything that leaves in a report
  goes through `redact.redact` / `redact.walk`.
- The app runs windowless under `pythonw.exe`, single instance enforced by
  a named mutex (`singleton.py`); status in `app.log`, everything ever
  dictated in `transcripts.log`. Both logs are plaintext and private.

## Traps we already paid for — do not re-arm them

- **No module but `net.py` imports a transport.** `urllib.request`,
  `urllib.error`, `http.client`, `httpx`, `requests`, `socket`, `ssl` —
  `test_only_net_imports_transport` greps for them, and the grep is the
  proof a stranger runs (plan 5.10). Need a new host? Add it to
  `net.ALLOWED_HOSTS` in its own commit; a new reason? `net.PURPOSES`.
  Never pass an `Authorization` header to a remote host yourself —
  `net.py` refuses it; pass `secret=<name>`. Loopback is the exception
  (the hook's phone token). An HTTP error status is a RETURN, not an
  exception: check `status`, read the body; `net.NetError` is the
  connection failing, `net.EgressRefused` the door staying shut.
- **This checkout's transcripts, recordings and `corpus\` are training
  data, not app data.** Never delete, prune, rotate away or "reset"
  them here: `paths.OWNER_DATA` guards `history.apply` and
  `migrate.reset_targets`, and any new wipe must honour it. A reset
  on 2026-09-17 removed 72 read-aloud clips (29.6 min of the owner's
  voice with vouched text) that cannot be re-recorded. List every
  delete a change performs on this machine BEFORE it lands.
- **A product module never imports an owner module at the top.**
  `nightly`, `questions`, `answer_card`, `tests_quiet`, `inbox`,
  `weekly_review`, `dev_git` (`tests.DEV_MODULES`) are not in the build
  (plan 7.4), so `import nightly` at the top of `dashboard.py` was a
  copy that could not open its window. Reach for one inside the
  function only the owner's surface calls — `dashboard._nightly()`,
  `main._questions_mod()` — and let `paths.DEVELOPER` decide whether
  that function runs. `test_product_suite_imports_no_dev_modules`
  imports every product module with those names blocked.
- **A privacy gate is not a setting.** Never add `privacy.<gate> = true`
  to a config write, a wizard, a migration or a test fixture as a way
  to "turn the cloud on" — `config.save` refuses it, and the honest way
  is the card (`privacy.grant`, or `_consented(...)` in a test). Warm-ups
  at start-up must swallow `ConsentRequired` like a missing key and open
  nothing; only a key press the person made may open a card.
- **`net.py` defines `open()`; inside it, write files with
  `path.open(...)`.** A bare `open(path, "a")` in that module calls the
  request function and fails on "unknown purpose 'a'" — silently, in
  the log writer's `except`, which is how the first version wrote no
  log at all.
- **Never name a module after a standard-library module.** The plan
  called the secret store `secrets.py`; a file of that name beside
  `main.py` shadows stdlib `secrets` (`token_urlsafe` in `server.py` and
  eleven files in the venv) because the app folder is first on
  `sys.path`. It is `secretstore.py`. Check `python -c "import X"` from
  a folder WITHOUT the file before picking a new module name.
- **A secret value goes into a variable in `secretstore.py` and `net.py`
  and nowhere else.** `apikey.py` is a shim over the store; a client
  checks that a key EXISTS (`find_key`, keep the source, `del` the value)
  and hands `net.py` the NAME. Never log one, never put one in a message, a report or
  a settings file, never cache it in a module global. Tests that write a
  key use the `DeskIT.test/` Credential Manager prefix (`DESKIT_HOME`
  selects it) or the DPAPI files under the tests' scratch home — a test
  that touches `DeskIT/groq` is a test that can delete the owner's key.
- **Every personal-store path comes from `paths.py`, never from
  `Path(__file__)`.** Since 2026-09-17 the app has two roots: `APP_DIR`
  (code, read-only once installed) and `DATA_DIR` (everything a person
  produces — `%LOCALAPPDATA%\DeskIT` for an installed copy). THIS checkout
  is portable (the `.git` beside `main.py` decides it): `DATA_DIR` IS
  `APP_DIR`, every file stays where it always was, and the checkout is
  "DeskIT Dev" — its mutex, pipe and AppUserModelID carry a `.dev` mark so
  the released copy can run beside it. A new store gets a row in
  `paths._LAYOUTS` (flat name | installed name) and a constant; a module
  that builds `APP_DIR / "something"` for anything but fonts, skin or
  the icon fails `test_no_store_path_is_built_beside_the_code`. Never
  create a folder in the checkout that the app did not make before —
  `paths.ensure()` is deliberately smaller in the flat layout. The whole
  argument is DISTRIBUTION_PLAN.md chapter 3; the decisions are D1, D4,
  D5 and D30.
- **Tests:** how you run them is **house rule 8 above**, not a
  preference — `.venv\Scripts\python.exe tests_quiet.py --no-screen`
  while he is at the machine, the plain `tests_quiet.py` only when he is
  away and has been told (asked for 2026-09-02, the `--no-screen` half
  on 2026-09-07). Same tests.py, same exit code, output printed at the
  end. The suite is two files since PR 8 (DISTRIBUTION_PLAN.md 7.5):
  `tests.py` is the product's — GitHub runs it on `windows-latest`
  with `--no-screen` (`.github/workflows/ci.yml`) — and
  `dev\tests_ops.py` is the owner's (the nightly run, the git card,
  the routine's docs), importing its fixtures from `tests.py` and
  running only in this checkout. A test that imports `nightly`,
  drives Push/Undo or reads a file the build never ships goes in the
  second; `test_product_suite_imports_no_dev_modules` refuses the
  first one that reaches for an owner module. The trap that is left
  is the LIST: `tests.NEEDS_SCREEN` holds the sixteen names that need
  the real display or the real mouse, and it is data precisely so it
  can be kept in step (`test_needs_screen_list_is_complete` checks
  every name is a test and every ask-card window script is on it).
  Add a test that photographs the screen or moves the pointer and its
  name goes in there — a test that fails hidden and is NOT in the
  tuple gets re-run in the open, so a missing name costs a second run
  rather than a wrong answer, and `--no-screen` will not know to skip
  it.
  `.venv\Scripts\python.exe tests.py` is the same suite in the open —
  plain asserts, **hundreds** of test functions carrying thousands of
  them, safe to run while dictation is live (two bugs that used to kill
  the app mid-suite are fixed; see git log) — but every window it opens
  is one he sees, so it is the thing not to reach for while he is at the
  desk. Run the suite BEFORE claiming done, through `tests_quiet.py`.
  (This line read
  "367" for a long time, then "449", and both had drifted badly by the
  time anybody looked — 613 functions on 2026-09-04 — so it says
  "hundreds" on purpose now. Re-count with `Select-String -Path
  tests.py -Pattern "^def test_"` when you actually need the number,
  and do not write it back in here.)
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
  tokens before answering, out of the same `max_tokens` as the answer:
  without `reasoning_effort=low` the answer arrives EMPTY, and with the
  cap sized for the answer alone it arrives CUT (measured 2026-09-18:
  77-147 hidden tokens a call on the polish prompt; 21 of 21 polishes
  truncated at the 256 floor, each paste then waiting on Ollama). Handled
  inside `translate.py::GroqTranslator` — a 256 floor plus 512 tokens of
  room for the thought (`reasoning_tokens`); don't pass tighter caps
  around it and don't fold the two numbers together.
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
- **A `PhotoImage` that outlives its interpreter aborts the process, and it
  waits for the SECOND card to do it.** The report card keeps its image in a
  dict every closure on the thread holds; leave that dict alive past
  `root.destroy()` and the `ImageTk.PhotoImage` is finalised later, from
  whichever thread the collector is on, calling into a Tcl that is gone —
  the same "Tcl_AsyncDelete: async handler deleted by the wrong thread"
  abort as the two bullets above, with the same silence. Measured 2026-09-04:
  `WordPrompt`'s teardown has no images in it and exits clean, and the
  painted card aborted on the second card it opened until the picture was
  cleared BEFORE the frame. `HintCard`'s teardown order is the pattern —
  clear the state dict and the sprite cache, drop the closures, then
  destroy. A card that opens once and is never opened again will not show
  you this.
- **A dragged window is clamped against the VIRTUAL DESKTOP, and `event.widget`
  is not where the press landed.** Three measurements from the report card,
  2026-09-04, and every one of them applies to the next draggable thing in
  here. (1) This machine has a monitor at `x = -1920`, so a card left on it
  has a genuinely negative x: clamp a saved position to the PRIMARY monitor
  and it walks home on every open, which is also why every "never dragged"
  sentinel in `config.toml` is `-100000` and not `-1` — it has to be a
  number no desktop can reach. (2) A repaint mid-drag with a stale origin
  snapped the dashboard's card back to where the drag started, because the
  layout re-applies that origin on every change and anything may repaint
  while the button is down: the origin has to FOLLOW the drag, not be read
  at the end of it. (3) Under a Tk grab, `event.widget` can be the Toplevel
  even while the pointer is over a child — the same press on the title
  reported the `Label` once and the `Toplevel` once, depending on whether
  the app was already active — so ask the screen with `winfo_containing` and
  decide by where the press LANDED, never by where the pointer ended up.
- **Do not move the weekly review to a cloud routine.** `/schedule` was the
  obvious answer and it cannot see this machine: a cloud run gets a fresh
  git checkout, and `problems.json` and `problems\` are local and
  gitignored on purpose, so it would review an empty bug list. The
  session-scoped alternative expires after seven days, which is shorter than
  the interval it would be scheduling. Hence a local scheduled task calling
  the local `claude.exe` (`weekly_review.ps1`). Anything that moves this off
  the machine has to solve reading the store first.
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
- **There is no `classic` to mirror to any more** (removed 2026-09-08).
  The rule used to be: land shared files on both branches in one change,
  and never by checking `classic` out — a checkout swaps the working tree
  under the app the owner is using. If two versions are ever wanted again,
  that worktree rule is the one to bring back with them.
- **The 2026-09-07 redesign is UNCOMMITTED on purpose.** LAMPLIGHT, the
  four places, the drawn keyboard, the settings sentences and the shelf
  are all in the working tree and none of it is staged or committed: the
  owner asked for it to stay that way until he has seen it, so that one
  git command throws the whole thing away. Do not `git add`, commit,
  stash or checkout it on his behalf, and do not add files to `fonts\` or
  anywhere else that a `git checkout .` would leave behind — an untracked
  file is the one part of this he could not undo.
- **The look lives in `skin/` and is meant to be deletable.** Every hook
  into it is `try: import skin / except: skin = None` in FRONT of code
  that was not otherwise touched, and `ui.py` still carries the ORIGINAL
  hex literals under the repaint hook — so `rmdir /s skin` really is the
  revert, and two tests assert it. Do not "tidy" those literals to match
  the new palette; that would quietly make the revert stop reverting.
  A name added to the skin must ALSO be added to `ui.py`'s pre-`# --- SKIN`
  block at an OLD-palette value, or deleting `skin\` gives back a
  half-repainted window instead of a coherent old one. `SKIN.md` has the
  rest.
- **A colour is decided in exactly one file, and a test now enforces
  it.** `skin\palette.py` is the table; `UI_NAMES` carries 47 of them and
  `repaint(globals())` writes every one into `ui.py`. The defect this
  answers was real and it was invisible: fourteen `#rrggbb` literals were
  spelled out INSIDE `ui.py`'s own widget constructors, below the
  `# --- SKIN` marker, so `repaint` silently skipped them and three
  further names (`LINE_HI`, `FOCUS`, `ACCENT_ON`) existed in the skin and
  not in `ui.py` at all.
  `test_the_window_has_a_name_for_every_shade_its_widgets_draw`
  fails on any `"#rrggbb"` appearing below that marker. Its sibling,
  `test_every_colour_the_palette_promises_is_the_contrast_it_claims`,
  is there because the palette carried its ratios as PROSE — "15.35 : 1"
  in a docstring that no test could contradict — and asserts AA on every
  text colour over three surfaces, `FAINT` bounded from BOTH sides
  (3.0 ≤ x < 4.5: it is the one shade allowed to fail, and a well-meaning
  lift turns it into a second body colour), the label on the accent fill,
  and the five dot states against `#1a1a1a`. Never eyeball a new colour;
  compute it, and put the number in the table.
- **`fonts.py` must run BEFORE anything asks GDI for a face, and a test
  holds the order.** Being installed under `HKCU\...\Fonts` is a promise
  to the next logon, not an answer to `CreateFontW` in this process:
  measured 2026-09-06, past a reboot and seventeen days after
  `install_fonts.py` ran, a fresh process asking for "Rubik" got Arial,
  so `ui.pick_face(["Rubik"])` returned Segoe UI and the whole app had
  been drawing in the fallback face without a word about it.
  `fonts.load()` (`AddFontResourceExW`, `FR_PRIVATE`, idempotent, never
  raises) is called at the import of `ui.py` and of `visual_qa.py`, and
  `test_the_app_hands_gdi_its_own_fonts_before_it_asks_for_one` asserts
  that the `_fonts.load()` call in `ui.py` comes before `pick_face` —
  because a load that runs after the question changes nothing that run.
  Through GDI there are only TWO real Rubik weights, 400 and 700 (the
  Skia path is different — see the variable-font trap below), so a design
  that wants a third step has to get it from size or colour.
- **A glow that does not reach alpha 0 inside its window IS the window.**
  The status dot's halo was a radial gradient of radius 26 px in a 38 px
  layered window: alpha 27 at every edge midpoint, and the owner saw "a
  square" on every wallpaper and title bar it crossed. UpdateLayeredWindow
  composites the whole rectangle, so any non-zero pixel on the border
  draws the rectangle. Every soft thing on a Glass has to end strictly
  inside its box (`skin\dot.HALO_R` = BOX / 2 − 1, and
  `test_the_dot_glows_to_nothing_inside_its_own_window` walks the whole
  border of every state) — and check it by rendering, never by the
  radius alone: `Dither=True` and antialiasing both reach past a number.
  Related, and the trap that is easy to re-arm: **where the dot is has
  ONE answer and three followers.** The answer used to be `[dot] corner`
  alone, read once at startup; since 2026-09-07 it is `[dot] x/y` when
  they are set (`-100000` in both means "never dragged, use the corner")
  and the corner otherwise, and the one function that says so is
  `skin\dot.spot` — which is `overlay.dot_spot`, the same arithmetic
  given a different box, so the glass dot and the Tk fallback cannot
  disagree. `skin\dot.place` is still the corner HALF of it and is what
  a caller with no saved position to consider asks for. The three
  followers: `skin\dot.spot` (the window itself), `skin\boot._landing`
  (where the reveal's light lands — pass it `x, y` or the light arrives
  in a corner the dot has left), and `overlay.HintCard.origin` with
  `dot_corner=` (where the shelf and the key card stop short of it).
  `[hint]` and `[shelf]` say `corner = "dot"` and `config.load` resolves
  the word, so a Config never carries it. Hard-coding "top-right"
  anywhere in that chain puts a card on the dot or lands the light in an
  empty corner.

  **The cards follow the DOT, not only the corner — since 2026-09-08.**
  This paragraph used to say the opposite and called it permanent; the
  owner then asked for it in as many words ("I want it to be able to
  move where the dot is"), so the question it left open — "beside a dot
  that is nowhere near an edge" — has an answer now, and the answer is
  `overlay.beside_dot`: ABOVE the dot when the whole card fits above it,
  BELOW when it does not, centred on the dot and slid back inside the
  WORK AREA OF THE MONITOR THE DOT IS ON (`overlay._monitor_work`, not
  the primary's — the screen on the left starts at x = -1920), clamped
  last against the whole virtual desktop, and never sharing a pixel with
  the dot. A card taller than the room above and below goes beside it,
  on the side with more room.

  The three rules that decide it, in `HintCard.origin` and in this
  order: a position HE dragged this card to wins; then the dot, if this
  card FOLLOWS the dot and the dot has been dragged out of its corner;
  then the corner, exactly as before. "Follows the dot" is `corner =
  "dot"` in the file and it is carried past `corner_for` — which erases
  the word — as `HintConfig/ShelfConfig.follow_dot` (`config.follows_dot`),
  because a card that NAMED the dot's corner must keep it while a
  follower moves. main.py hands a follower `dot_at=self._dot_beside`, a
  callable and not a number: the dot moves and the cards are built once,
  at startup. It answers None while the dot is still in its corner, and
  None means the corner rule — which is why every corner test written
  before this still passes unchanged.

  Changing it still has to answer the placement question for all four
  cards at once; the notification and review cards are NOT followers
  (`[notify]`/`[review] corner` never says "dot") and were left alone.
- **Moving the dot is a LIVE command, and the two gestures on the disc
  live on different Windows messages.** "Move the dot" (Settings ›
  General, beside the corner menu) goes down `control.py` as `dot` /
  `do = move`, the app arms
  `overlay.StatusDot.move()` for `DOT_MOVE_S` seconds, and the dot's
  own painter picks that up on its next frame — nothing restarts, which
  is the whole of the owner's complaint. While it is armed the disc
  answers **HTCAPTION** instead of HTCLIENT, so Windows runs the drag
  and the press arrives as `WM_NCLBUTTONDOWN`; the shelf's toggle is on
  `WM_LBUTTONDOWN`, which Windows never sends for a caption pixel. That
  is why "a drag must not fire the click" needed no travelled-far-enough
  test here, unlike the notify card. The glow answers HTTRANSPARENT in
  BOTH modes — a temporary mode does not get to make the light take
  clicks away from the window underneath. Move mode is a DEADLINE and
  not a flag because the dashboard hides itself for it: something has to
  end the wait when he presses the button and walks away, or he is left
  with a dot that will not open the shelf and a control window he cannot
  see. The dashboard has its own longer backstop (`DOT_WAIT_S`) for an
  app that stops answering mid-drag.

  **NEITHER PAINT PATH'S DRAG CAN BE DRIVEN WITHOUT A REAL MOUSE, and
  the second half of that was measured on 2026-09-08.** The glass path
  is Windows' own modal move loop, which wants real input, and the
  window's position is re-applied by every `UpdateLayeredWindow`, so a
  `SetWindowPos` standing in for a drag is undone before the message
  lands. The Tk fallback looks like the way round it — it tracks the
  drag with its own `<Button-1>` / `<B1-Motion>` bindings — and it is
  not: Tk builds a mouse event's position from `GetMessagePos`, which
  reports the last message taken OFF THE QUEUE, and `SendMessage` never
  goes near the queue. Probed on the hidden desktop, every synthetic
  press arrived at the real pointer's coordinates, outside the disc, and
  `press` returned having done nothing. Everything AROUND the drag is
  covered headlessly — the pipe
  (`test_the_move_button_reaches_the_running_app_down_the_real_pipe`),
  the arming and the HTCAPTION answer
  (`test_the_real_dot_window_moves_while_the_app_keeps_running`), the
  deadline, the clamp and the write — so what is left for a hand on the
  mouse is the drag itself and nothing else. Do not spend an evening on
  it again.
- **A glass hook is named `<thing>_run`.** The shelf's is
  `skin.shelf_run(card)`, registered in `skin\__init__.py` exactly the
  way `notify_run` is; `tests.py:14791` enforces the naming rule, and a
  hook that does not follow it is a hook the fallback path cannot reason
  about.
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
- **Our own windows and the owner's screenshots: keep them out of the
  DRAG, not out of the PICTURE.** This rule used to read "our own windows
  must not appear in the user's screenshots" and it was wrong, which cost
  the owner the one card he most wanted to send somebody. The flag is
  `capture.hide_from_capture` (WDA_EXCLUDEFROMCAPTURE) and it works —
  re-measured on the status dot's own window, 3600/3600 magenta pixels
  before, 0/3600 after — but it is ABSOLUTE: a window carrying it is
  invisible to every grab on the machine, the owner's own included. The
  notification card that says Claude has finished wore it, so pressing
  `Win+Shift+S` appeared to make it vanish; it never did, the compositor
  was simply leaving it out of the freeze the selector paints itself
  with. Removed 2026-09-04 from the dot, the hint card, the review card
  and both paths of the notification card (`overlay.py` and
  `skin\notify.py` — the glass path is the live one).
  **What replaces it is ORDERING.** `capture.Controller._shot_flow`
  freezes the desktop with one `ImageGrab`, hushes the cards on the very
  next line, and only then maps the selector: they are in the picture and
  off the live screen for the drag. `hush()`/`unhush()` on the overlay
  cards only set a `threading.Event` — they are called from the keyboard
  hook, where the budget is 300 ms — and each card's own loop does the Tk.
  A card that ARRIVES mid-drag is the real race, and a hushed card
  refuses to map at all. `capture.py` gets the callable injected by
  `main.py`; it must not import `overlay.py`.
  **THE HUSH IS ONLY HALF WIRED, AND THIS IS THE HONEST STATE OF IT.**
  `main.py::_hush_overlays` calls `hush()` on the notification card, the
  review card and the hint card, but only the NOTIFICATION card obeys on
  the path that actually runs. `skin.on()` is true on this machine, so
  all three take their glass loops, and only `skin\notify.py` reads the
  flag; `skin\hint.py` and `skin\review.py` do not, and the hint card's
  Tk loop does not either. Both of those cards take clicks on glass
  (`HTCLIENT`/`HTCAPTION`), so one arriving mid-drag still maps over the
  selector and eats the drag. That is NOT a regression — the affinity
  flag never touched z-order or hit-testing, so they could always do it —
  but it is an unfinished mitigation, and one artefact is new: those two
  are now in the frozen backdrop AND can still map live, so the owner can
  briefly see the same card twice. Finishing it means reading `_hushed`
  in `skin\hint.py` and `skin\review.py`. Do not write it up as done
  until it is.
  **The one exemption is the clip bar** (`ClipBar._build` and
  `_build_frame`), and the line is STILL versus MOVING, not ours versus
  theirs. A screenshot has an instant to freeze; a recording does not, so
  the bar would be in every frame of the mp4 and cannot be cropped out —
  it sits *inside* the region being recorded, and the recorder's
  `BitBlt ... SRCCOPY | CAPTUREBLT` exists precisely to include layered
  windows. Measured 2026-08-25: 60000/60000 pixels before the flag, 0
  after. Leave those two calls alone.
- **The notify door rings for what is waiting on him, not for every
  turn — and the fix was not `coalesce_s`.** Claude Code's Stop hook
  fires at the end of EVERY turn; counted 2026-09-05, 87 of the last 100
  cards were per-turn finishes, 52 of them from one session, and the
  median gap between them was 170 s. Raising `coalesce_s` would have done
  nothing: it is keyed on SOURCE and every session sends `claude-code`,
  so two sessions at once already shared one key. `idle_prompt` was no
  answer either — it has never fired on this machine (0 in `notify.log`),
  so nothing may lean on it. What holds is keyed on the SESSION
  (`Engine._key`: the session id, or `~source` for a sender without one):
  a `done` is HELD for `[notify] quiet_s` on a `threading.Timer` (the
  key ships at 0 since 2026-09-05 afternoon — no hold, the card as
  Claude stops — and the timer stays for whoever sets it), the same
  session's next arrival SUPERSEDES it unseen, and only `[notify]
  interrupt` kinds cue and arm the reminders (`_may_interrupt`,
  `_loud_unread`). Keep three things true. A held `done` must never delay
  an `input` — only `done` is ever held, so write the rule as `kind ==
  "done"` and never as a negation, or Cowork's `cu-lock` `info` gets held
  too. Never sleep inside `Engine.receive()`: the hook posts with a 3 s
  timeout, `tests.py` asserts the round trip under 2 s, and `receive()`
  runs under the engine lock the dismiss key also takes — the wait is the
  timer's, on its own thread. And a test that wants the old door says so:
  `_notify_cfg()` pins `quiet_s=0, interrupt="all"`, and the quiet door's
  tests name what they want. `Engine.test()` is `urgent` — Send-a-test
  always rings, whatever the two keys say.

## Where things live

| file | job |
|---|---|
| `main.py` | app wiring: hotkeys, worker, paste, phone endpoint, and the report tap — the screen photographed BEFORE the box opens, the five-minute window (`PROBLEM_LAST_MAX_S`) past which a stale dictation is not blamed for a fresh problem, and the diversion that sends a dictation into the box instead of pasting it |
| `config.py` / `config.toml` | settings, validation, comment-preserving writes |
| `recorder.py` | mic stream, WAV frames |
| `hotkey.py` | global hook, state machine, chords |
| `transcribers/` | whisper/gemini/fake backends |
| `polish.py` + `translate.py` | repair pass + all chat backends (Gemini/Ollama/Cerebras/Groq) |
| `cleanup.py` / `vocab.py` | filler removal, learned words |
| `study.py` | the second learning channel: when idle, re-decodes sent recordings, votes + adjudicates, learns from divergence (fast only) |
| `reading.py` | read this to me: the Corrections place's Read aloud tab. One sentence on a card, read into the dictation key with the dashboard in front, and kept under the CARD'S words in corpus\read (beside the corpus, so corpus_keep never trims it) WHEN HE PRESSES THE LEFT ARROW -- the recording stands after the release, the key held again reads the same sentence over and the new take replaces the one standing (his flow, 2026-09-13 late; Left is the latch key, which the hook swallows only mid-recording, so after the release it reaches the dashboard's root binding): the card is the label, what the model made of the reading is filed in the sidecar (`heard`, `match`) and asked one thing only, whether anything came back at all -- the transcript was a verdict for an evening and he asked why he needed one ('I said it, this is the text'). Redo the last one takes a kept reading back (`forget`), Skip retires a sentence. THE DECK IS PROSE, READ IN ORDER: any .txt/.md he drops into corpus\read\texts, and when it runs dry a paragraph the polish backends write on the next of `SUBJECTS` (`Writer`, Groq then Ollama, text only, ~1 s, at most a third of the sentences carrying an English term (`mixed`), round the names in vocab.json (`names_of`), saved as written-<stamp>.txt like any other file); `plausible` keeps a lone letter, glued punctuation or a triple word off the card. His own dictations were the first source and were dropped on 2026-09-13 -- a dictation is not prose. Kept and skipped sentences (skipped.json, the sidecar's `key`) are never offered again. The app owns the mic and the models: `_on_start` decides `_to_read` at the press from the foreground window alone, `_handle` diverts the transcript (vocab applied, no context pass) to `Reading.heard` instead of pasting, the `read` control command is arm / disarm / keep / drop / forget and `status()["read"]` is what the tab draws. Two bars in [study]: read_sentences (a day's bar, in SENTENCES -- a reading is four seconds of audio and fifteen of his time, so his "five minutes a day" is twenty sentences; the panel says N of M and how many to go), read_goal_hours |
| `injector.py` | clipboard paste, placeholder, focus checks |
| `punctuate.py` / `lookup.py` | F2 rewrite-in-place / reading box |
| `visual_qa.py` | ask-the-screen: region select, vision chain, answer window, TTS; no model that can see (Ollama down, no key, gate shut — `OllamaAbsent`) is screen 12's panel on the card: a Hebrew body and three rows — install Ollama (dim on a CPU-only PC, names the tier's model), use my own key (`privacy.request` opens the consent card), turn this key off (`visual_qa.enabled = false`) |
| `capture.py` | screenshots (select, edit, clipboard, save), screen recording (BitBlt + PyAV), and the webcam photo key (dshow through the same PyAV, into the same editor) |
| `notify.py` | the notify door's engine: cleans what arrived (truncate, never interpret), the store (`notify.json`, last 100), the log (`notify.log`), the cue, the reminders, the live column (`live()` — the unread ones, newest first, capped by `[notify] stack_max`) and the dismiss/open of one card or of all of them — `open()` goes to the sender's session (`open_link`, a whitelisted `claude://…` URL, `_link` is the whole of the policy) and then raises its window; and, since 2026-09-05, the quiet door — `_hold` / `_quiet` (a `done` waits for its SESSION to go quiet, `[notify] quiet_s`), `_supersede` (the same session's older finish retired unseen), `_may_interrupt` / `_loud_unread` (`[notify] interrupt`: who may cue and be reminded), `urgent` for Send-a-test |
| `notify_card.py` | the card's words and picture, and the column's arithmetic (`stack_layout` / `stack_measure` / `stack_hit_test`, copied from capture.py's toast stack rather than imported — this module is on the startup path) — a pure painter, one `text_pil` image per string, no Tk |
| `notify_watch.py` | the other road in, for the half of Claude that cannot knock: Cowork runs in the cloud and has no hook to install, so this polls Windows' own notification store (`wpndatabase.db`, the toasts every app raises) and hands the desktop app's to the same engine — `[notify] watch` (`off \| cowork \| all`; "cowork" leaves the app's Claude Code sessions to the Stop hook, which has already carded them). Claude Chat is in none of it: the app raises notifications for `ccd` and `cowork` only, so a finished chat reply is announced to nothing on this machine |
| `notify_hook.py` | the Claude Code hook (Stop + Notification, `--install-hook` writes them into `~/.claude/settings.json`) and the generic CLI (`--title ... --body ...`) — stdlib only, always exits 0; `owner_window()` walks up the parent processes so the payload can name the window a click on the card raises, and `session_link()` reads the desktop app's own session store so it can name the SESSION inside that window (`claude://resume?session=<the app's uuid>` — the two links the app advertises for this are gated off, its log says so, and the long comment there has the measurements) |
| `problems.py` | the owner's own bug list, which is one typed line plus everything the app can attach without being asked: the store (`problems.json`, `problems.lock` beside it so the app and the dashboard cannot write over each other, open reports NEVER trimmed and answered ones aged out at `keep_resolved`; `resolve()` moves a report to fixed/closed and BACK to open, and `remove()` is the only thing that loses one — the surface calling it must ask first, and it never touches the pinned wav or screenshot), the context collection (the last dictation and its `recent\` sidecar, a copy of the wav and the screenshot pinned into `problems\` so they outlive that ring, the settings that explain a bad transcript), the screenshot thumbnails the Problems tab redraws off (cached on path+mtime+size: 35.8 ms cold vs 0.170 ms warm, 2026-09-04) and the weekly digest (`problems.md`, regenerated from scratch on every write, open items first) |
| `problem_card.py` | the report card's words, geometry and picture — pure Python plus Pillow, no Tk, no window, so the whole card can be rendered to a PNG and looked at without pressing the hotkey (it was wrong for a week because it could not be). Third painter-plus-window pair in here, after hint.py / `HintCard` and review_card.py / `ReviewCard`; `dashboard.py` imports its field metrics, its hint and its keys line so the two surfaces of one feature cannot drift apart |
| `weekly_review.ps1` + `.claude/commands/weekly-reports.md` | the Saturday 08:00 review of the bug list: a scheduled task runs the wrapper, the wrapper runs the local `claude.exe` on the project command, and the command reads `problems.json`, writes the summary, the plan and the archive into `problems\weekly\`, closes only what it understood, regenerates `problems.md` and posts a card through notify_hook.py. It FIXES NOTHING by design, and it asks rather than guesses — a report it cannot explain stays open with a question against it. The command is committed (it is the routine); everything it writes is gitignored (it is his) |
| `nightly.py` + `nightly_tests.ps1` + `install_nightly_task.ps1` | the 02:55 run of the WHOLE suite, the sixteen screen tests included — which is the only time they ever run, because `--no-screen` skips them every day he is at the desk. A Windows scheduled task fires the wrapper and the wrapper runs `nightly.py`: a card asks, and **no answer means RUN** (he rejected an idle check — a bottle falling on the keyboard in the night looks exactly like him being there and would cancel the run in silence). The trigger is outside the app on purpose, so that the night DeskIT crashed is still a night the tests run, and the monitors are never woken: measured 2026-09-08, `ImageGrab.grab()` returns a real 2560×1440 picture with the screens off. A clean night files NOTHING; a night with real failures files ONE report into `problems.json` for the Saturday routine to rule on; the machine's one known flake is named in `KNOWN_FLAKES` and files nothing on its own; a run he stopped is recorded as stopped. State lives in `problems
ightly\` — an OS-held byte lock so two runs cannot overlap and a dead one wedges nothing, a marker the dashboard polls for its **Stop tests** button, and a `stop` file that button writes. `install_nightly_task.ps1` is NOT run by anything here; it changes the machine, so he runs it himself |
| `server.py` | the loopback HTTP door on the `[server]` port: phone dictation, translate, punctuate, notify — every POST route bearer-token gated |
| `control.py` | the named pipe between the dashboard and the app: status, commands, replies; handlers must never block |
| `overlay.py` | every window this app paints by hand: the splash, the status dot, the hint card, the correction and report box (`WordPrompt` — `fill()` puts a dictated line IN the box without sending it, which is the only way a transcript reaches one of OUR windows, `injector` refusing by design to paste into this process), `ProblemCard(WordPrompt)` — a SUBCLASS and not a mode flag, so the review pencil's one-line box is provably untouched; it overrides only `ask` and `_run` — and the review and notify cards on top of `HintCard` |
| `hint.py` | what the hint card says while the key is held: one row per bound key, read off the live Config under the same condition `main.App._bindings` registers it under, so a rebind moves the row and a feature switched off takes its row away. Pure Python, no Tk — the tests read every row |
| `dashboard.py` + `ui.py` | the control window: four places along a top bar (Waiting, Said, Keys, Settings), the merged Waiting pile and "the whole list" behind it that answers the bug list and the routine's questions, the generated Settings place with Stop / cue sounds in it, and the frameless **Report a problem** card the button beside the Waiting title opens; YOUR CLOUD KEYS on Settings > Privacy (screen 3): a masked field per provider that takes a paste and never shows it, [Save and test] (secretstore, then one `key-test` GET through net.py by NAME — the value never touches the window), [Remove], `secretstore.storage_sentence` under each; the two D33 switches as blocks — Connect Claude Code on The app (`notify_hook.install_hook`/`uninstall_hook`), the Snipping-Tool key on Screen (`capture_hotkey` = win+shift+s / ctrl+f11 through `_apply_key`) |
| `net.py` (the window) | The Network screen — D12's window, chapter 9 screen 6; the seventh place on the bar until 2026-09-18, now behind the EVERY CONNECTION card on Settings > Privacy (the bar lights Settings while it is up; `dashboard.SCREENS` lists it beside the six of `NAV`): every outbound request newest first, read from `network.log` through `net.read_log()` — the dashboard is its own process, so the file is the record it shares with the app — a chip per host seen, loopback (the phone, the hook) hidden until its button, the Offline banner, [Open network.log], and the sentence when the table is empty: during plain dictation it stays empty, that is the proof. the card on Privacy counts today's requests; Home's band is five doors again. The table is ONE canvas of text items, not a Label per cell — 2,800 Labels rebuilt on every write to network.log froze the window for 5 s at a time (2026-09-18) |
| `widgets.py` | the pieces the window needs that `ui.py` does not have: the tab strip, a hairline, the state chip, an icon-in-a-label, a row whose text stops where its buttons start, `rtl_run()` for a pill inside a Hebrew sentence, and a toned Button. Every colour is read as `ui.NAME` INSIDE the call, so a repainted palette lands on the next screen drawn |
| `keycaps.py` | the Keys place's board (keyboard.py until PR 10 — the PyPI package of that name shadowed it): 87 caps, one Pillow image and one hit table, everything measured from a single cap unit; the bindings are read from `config.HOTKEY_FIELDS` + `hotkey.parse_binding` and lit on it |
| `prose.py` | the settings said as sentences with the controls inside the words — a hand-flowed Canvas at a fixed 34 px line. Every `Bit` names a real path in `config.toml` and a test walks them |
| `settings.py` | defaults.toml as data: every key, its comment as help, `a \| b \| c` as choices — and `TABS`, the short list of lines the Settings place draws, with their plain words (everything else is the developer's, 2026-09-18) |
| `fonts.py` | hands this process its own copy of Rubik (`AddFontResourceExW`, `FR_PRIVATE`) at the import of `ui.py` and `visual_qa.py`, before anything asks for a face |
| `shelf.py` + `shelf_card.py` + `skin\shelf.py` | the panel beside the dot: the window/thread/queue class (modelled on `overlay.HintCard`), the pure painter (words, geometry, hit test, `INK`) and the glass. Every answer it offers calls the same `App` method the matching card does; nothing goes through `control.py` |
| `skin/` | the whole look — delete the folder to revert it (`SKIN.md`) |
| `version.py` | reads `VERSION` (one line, SemVer, the number every screen and report prints; the Android build reads the same file) and, in the checkout only, the git branch |
| `migrations.py` | the per-user files across versions (11.10): `version.CONFIG_VERSION` is what this build writes to `state.json`, `MIN_CONFIG_VERSION` the oldest it brings forward (published in latest.json by release.yml); `STEPS` is the ordered list (empty at 1); `apply()` at start, before anything reads the config, runs every step above the files' version and stamps only after all succeeded — a failing step leaves the files and says so once. The owner's `--migrate` stamps the current version itself |
| `deskit.pyw` | the installed copy's entry — `python\pythonw.exe app\deskit.pyw [--dashboard]`, what the shortcut, the Run value and the pin's relaunch point at; `main.main()` and nothing else. The checkout keeps its `.vbs` launchers |
| `launch.py` | starting the app and the desk from each other, detached, through `pythonw()` (python\ beside app\, then the venv, then this interpreter's). **Every script an installed copy starts BY PATH carries main.py's four-line sys.path guard before its first import of ours** — the installed `python311._pth` isolates sys.path and never adds the script's folder, which is how "Open the desk" on the 1.1.0 install did nothing (dashboard.py dead on `import config`, stderr in DEVNULL); `test_entry_points_put_their_own_folder_on_sys_path` holds the set. `spawn()` hands each child `paths.SPAWN_LOG` (`spawn.log`, `logs\` on an install) as stderr, one dated row per launch, cut to its tail past 200 KB — the next silent death leaves its traceback there. `dev\shot_desk.py` is the proof: the desk by path under an installed tree's python.exe (or `-I -P`), photographed on the hidden desktop |
| `autostart.py` | "Start with Windows": the HKCU `Run` value `DeskIT` (`setup.autostart`, a state key), re-asserted at every start; refuses in the checkout |
| `packaging\DeskIT.iss` | the per-user Inno installer (10.4): no UAC, Hebrew/English by the Windows language, Restart Manager on upgrade, downgrade refused, `/CHANNEL=` and `/NOLAUNCH`, the uninstall question defaulting to Keep |
| `hardware.py` | the probe at every start (CUDA devices, VRAM + driver from nvidia-smi, cores, RAM; Ollama and the Hebrew voice on a thread) → `hardware.*` in state.json and the tier (gpu / gpu-small / cpu); `apply(tier)` writes 6.3's derived defaults into the machine layer only where settings.toml is silent — a choice beats a probe (`config.save(derived=True)`), and the checkout applies nothing |
| `models.py` + `models.lock` | the Hebrew model on an installed copy (plan 6.4, D13): `models.lock` beside the code names each repo the app may download — pinned commit, every file's size and SHA-256, licence (`python models.py --lock` rewrites it from the Hub's metadata; `--verify REPO` hashes a folder against it); `download()` fetches through `net.py` into `DATA_DIR\models\<owner>--<name>` with the Hub's redirects followed by hand (every hop on the allowlist, a row under `model-download`), resumes a `.part` with a Range, hashes every file and only then writes `.complete`; `source(repo)` is what WhisperModel gets — the verified folder on an installed copy, the hub name in the checkout and a portable copy (D4) — and a folder without `.complete` is a typed `ModelMissing` before the library is asked; `env()` sets HF_HOME under `cache\hf`, offline, no token, no telemetry, before faster_whisper is imported (main calls it first); `offer()` is the step window ([Download] / [Not now] / [Pause], the size line first), shown at start before the wizard while the model is not ready, and by `--download-model` |
| `packs.py` + `packs.lock` | the wheels the installer does not carry (plan 6.5, D14, D19, D24): `gpu` = NVIDIA's cuBLAS + cuDNN + NVRTC at the owner's venv's versions (1.37 GB), `skin` = skia-python; no `recording` pack — PyAV is in the base lock. `packs.lock` (`python packs.py --lock`, from `importlib.metadata` + PyPI's JSON through net.py) holds each wheel's version, file, URL, size, SHA-256 and the licence links the card shows. `install()` = the wheels through `net.download()` into `DATA_DIR\packs\<name>\wheels` (rows under `pack-install`, resumed from a part), then `python -m pip install --no-index --find-links … --target …\site --require-hashes --no-deps` with no network at all (chapter 6 open point 1 closed: pip never talks to PyPI), the record `packs.lock` beside `site`, the wheels deleted. `state()` = venv (checkout) / missing / stale / ok; `standing()` adds `failed:<line>` from `hardware.gpu_pack_failed` (state.json), written by the ladder when the pack is there and cuda does not run; `activate("gpu")` = add_dll_directory + PATH prepend for the pack's `nvidia\*\bin` (what `_register_cuda_dlls` does for the venv), `activate("skin")` = sys.path; `wanted()` / `offer()` / `decline()` = the step at start after the model on a card with a good driver, `[setup] offer_gpu_pack = false` on [Not now]; `--install-pack NAME`; `recording` = PyAV 18 (28 MB) — its FFmpeg is a GPL build (x264, x265), so it is never in the installer (13.4, D24): the person's download from PyPI with the licences on the card, `packs.activate("recording")` at start, the block on Settings > Screen |
| `steps.py` | a download that asks first (models.py, packs.py), in three pieces: `StepRun` is the WORK — the thread, the cancel event, the queue and the state a face is drawn from (bytes, stage, rate, the end word: done / paused / offline / failed) — owned by whoever hosts it; `StepPane` is the FACE on a ui.py frame (Hebrew paragraph through the bitmap path, the size line before any byte, licence links, the bar with bytes/percent/rate, [Download\|Install] / [Not now] → [Pause], `attach()` for the next run of a queue, `compact` for a page where the bar is not the subject); `StepWindow` is a Tk root around one pane — the standalone step the start shows when the wizard is NOT due and what `--download-model` / `--install-pack` open from the dashboard; `steps.show(step)` never raises |
| `pcm.py` | WAV bytes → the 16 kHz mono float32 array faster-whisper takes, with the standard library's `wave` and numpy (channels averaged, other rates resampled) — the ONLY decoder on the dictation path since 13.4: `WhisperModel.transcribe` is handed samples, never a BytesIO (that road is faster-whisper's `decode_audio`, which is PyAV). A body that is not WAV goes to PyAV when a real one is there and is `NotWav` with the Recording pack's sentence when it is not |
| `vendor/av/` | the stand-in for PyAV on an installed copy: `paths.py` puts `vendor/` LAST on sys.path, so a real `av` anywhere wins; faster-whisper's `import av` succeeds; any attribute is one ImportError naming the Recording pack — unless a real `av` has since appeared on sys.path (the pack's site, appended by `packs.activate`), in which case the stub loads it in its own place and hands over, no restart. Ships (not export-ignored) |
| `firstrun.py` | the first-run wizard, seven pages in one 720x640 window (chapter 9.2, `docs/distplan/research-onboarding.md`): Welcome (three privacy sentences, the guide's "check it yourself" link) → Microphone (the live meter, Windows' privacy switch read from the registry before the meter is even drawn, the trap named with the fix one click away) → This computer (the probe's line; the Hebrew model as a `StepPane`, the GPU pack and the English detector as switches that queue behind it — one [Download], one bar, "1 of 3 · Hebrew model"; the queue keeps running while the wizard moves on and is drawn again on the next page) → Say one sentence (the record button waits for the model; the measured seconds into `hardware.last_test_seconds`) → Keys → Optional extras (D33's five: cloud repair through its consent card — `consent_card.flat` in a small window over the wizard, one Tk, the same text_version privacy.grant records — keep-awake, weekly update check, Connect Claude Code, the Snipping-Tool key; drawn as they stand, written only when moved) → Ready (the hotkey, Start with Windows and the phone asked once, [Open the desk]). `setup.done` into state.json (`record_done`; the marker file only for `--config` runs); `run()` returns a `Result` (truthy when saved; `open_desk`, `installed_pack` for main). Imports nothing from main.py. Chrome English, every paragraph Hebrew through `ui.draw_text`; the string table is `WORDS` |
| `tour_card.py` + `overlay.TourCard` | the guide itself (D36): four callouts beside the status dot on the first start after the wizard — the dot and its colours, the hold key drawn as a keycap, what a click on the dot opens, done — one Hebrew sentence each, [הבא] / [דלג] / [סיימתי]. Split like consent_card.py: the words (`STOPS`), the geometry and the picture in `tour_card.py` (pure Pillow; `frame` adds the beak's room on the side that faces the dot, `clamp_tail` keeps it off the corners, `flat` paints card + beak on the chroma colour the window keys out); the thread, the queue and `place` (beside_dot, then which edge faces the dot) in `overlay.TourCard`. Once per copy: `setup.tour` in state.json, written by `main.App._tour_ended` on [סיימתי] AND on [דלג] (a skipped tour never comes back by itself); `App.tour_due()` decides at start; the control command `tour` and Settings > The app > Show the tour put it up again. The docs site is the reference, not the guide |
| `LICENSE`, `NOTICE`, `TRADEMARK.md`, `SECURITY.md`, `NETWORK.md` | the papers beside the code, shipped (chapter 13, 14.7, D23-D26): Apache-2.0 verbatim + the NOTICE with the owner's line; the name and the icon reserved (13.2); how to report a security issue, 90 days, latest release only; every host `net.py` allows with its purpose words — `test_network_md_matches_net_py` holds the page to the code. `docs/privacy.md` + `docs/terms.md` are the Pages drafts (English canonical, Hebrew and the contact address are the owner's); `dev/legal/` the six private papers of 13.8; `dev/notices-extra.txt` the hand-written half of `THIRD-PARTY-NOTICES.txt`, which the release build writes from pip-licenses over the staged site-packages + that file + python/LICENSE.txt + Tcl's license.terms, before the manifest; `.github/ISSUE_TEMPLATE/` the two forms and the Discussions pointer |
| About, `--diagnose` | `dashboard._about_card` on The app: the licence line, the model line (Built with Llama while a default names one — `Dashboard.built_with_llama`), a button per paper (files beside the app; privacy/terms local in a checkout, Pages otherwise), Report on GitHub, Copy diagnostics; `problems.diagnose()` = env() + backend/model/pack standing + channel + port + the last 50 lines of app.log through the redactor, never transcripts.log; `main.py --diagnose` prints it and puts it on the clipboard |
| `release.yml` steps 8/13/14, `winget.yml`, `packaging/winget/`, `CHANGELOG.md` | the build's last steps (10.3, 10.6, 11.11): the manifest and the installer attested (`actions/attest-build-provenance`, public repositories only); VirusTotal through the large-file upload URL, polled, the run failing above `VT_MAX_DETECTIONS` (a repository variable, default 2) and saying so without `VT_API_KEY`; the DRAFT release on a real tag with the notes from `CHANGELOG.md`'s `## x.y.z` section + the fixed block (SHA-256, VirusTotal, attestation, the previous version), pre-release for `-beta`, the installer + .sha256 + latest.json + MANIFEST.sha256 + THIRD-PARTY-NOTICES.txt attached — the owner reads the scan and publishes; `winget.yml` on `release: published` runs `wingetcreate update YoavShimron.DeskIT --submit` with `WINGET_TOKEN` (never a pre-release); `packaging/winget/` holds the four manifests for the one hand submission (`wingetcreate new`) with `/CHANNEL=winget` in the silent switches and Inno's ProductCode |
| `transcribers/missing.py` | the stand-in `get_transcriber` returns on an installed copy whose model is not on disk: the app starts, every key that needs no model works, a dictation meets `ModelMissing` (main keeps the recording in `pending\`, gives up at once, says why) — and the first dictation after `.complete` appears builds the real backend through the `build` it was handed and forwards everything to it (no restart) |
| `transcribers/off.py` | the stand-in `main.App.unload_model` puts in the transcriber's place while the model is unloaded (Stop in the desk, 2026-09-18): `name` = "off" so status(), the phone's /health and the log lines keep working; `transcribe` raises a typed `TranscriptionError` with `MODEL_OFF_WORDS` for the one recording that could reach it. `load_model` replaces it with the real backend |
| This PC on Settings > The app, the Home rows | the four `[local]` knobs the probe writes and `setup.offer_gpu_pack` are the file's, not the screen's (the Speed tab went 2026-09-18); `dashboard._speed_block` = `hardware.summary()`, the model's standing and the GPU pack's with the buttons each state earns (download / continue / delete and re-download / delete; turn on / update / retry / reinstall / remove — each step in a process of its own through `launch.run_step`); `dashboard._waiting_hardware` = the Home pile rows for a model not there, a pack that will not run (`failed:`), a tier that changed (`hardware.tier_changed`, cleared by OK); `_voice_block` on Screen when the probe found no he-IL voice (`hardware.no_voice`, `apply_voice` puts `visual_qa.speak = "off"` in the machine layer); provider menus drop "On this computer" when `hardware.ollama_absent()` unless it is the held value |
| `updates.py` | the weekly look at GitHub Releases (`latest.json` behind the latest release, through `net.py`, no identifier), the verified download into `tmp\`, the installer run again with 11.6's switches after `settings.toml.bak`; `[updates] channel/skipped` are settings, `last_check/latest_seen/installed_version` state; the checkout looks but never installs; a newer release is also a row on Home's pile (screen 11) with the same three buttons, or the 'install the intermediate version first' sentence when the release's `min_config_version` is above this copy's files |
| `manifest.py` | `MANIFEST.sha256`: the build writes one line per file under `python\` and `app\` (`write`), `--verify` reads it back (`verify`); stdlib only |
| `packaging\` | the build's inputs that are not code: `python311._pth`, `python-embed.sha256`, `build_local.ps1` (steps 1-7 on this PC into `dist\`); never in the archive |
| `docs\` | the site GitHub Pages serves at `paths.PAGES_URL` (chapter 14, D26; `pages.yml`, Jekyll): the guide Hebrew first (`docs\he\quickstart.md`, `01-install.md` … `10-faq.md`, `settings.md`) with the English mirror (`docs\en\`), the pictures (`docs\img\`, every one referenced), `privacy.md` and `terms.md`, and `docs\strings\` — the app's own words exported for the guide to quote: the wizard's `WORDS`, the consent cards, `secretstore.storage_sentence`, the retention sentence, the owner's Hebrew map for the Settings page. Never shipped (export-ignored) |
| `dev\gen_settings_doc.py` + `dev\test_docs.py` | the generator (the Settings chapter in the Settings place's own order from `defaults.toml`, the retention sentence, the string tables; `--check` fails a release whose pages are stale) and the guide's tests (trees complete, pictures exist, chapter 4 equals plan 5.10 word for word, the key sentence is the app's, no owner words, every `Settings > X` and `Dashboard > X` is a screen the app draws). `ci.yml` runs the tests on every push; `tests_ops.py` at night |
| `.github/workflows/release.yml` | the build on a tag `v*` (10.3 steps 0-7 so far): wheelhouse by hash, python.org zip by SHA-256, Tk copied from the runner's same-patch Python, `git archive`, the manifest |
| `.gitattributes` | `export-ignore` — what `git archive`, and so the product tree, never contains |
| `sb.py` | the account (chapter 8, D17, D31): the one server DeskIT runs, spoken to only through `net.py` by purpose (`account`, `sync`, `history`, `report`). Two public constants — the project ref and the PUBLISHABLE key (`PROJECT_REF` empty until the owner's project exists; every function then answers "not configured"). Google sign-in through Supabase's PKCE flow with a one-shot listener on 127.0.0.1 (`_listen` / `_wait_for_code` / `_exchange`), or an anonymous account, linkable later; the session as one DPAPI blob under the name `supabase_session` (net.py reads the access token out of it by name); one refresh on a 401, a second 401 drops the session. `sync_now` = pull/merge/push for the three stores behind their gates; `drain_outbox` = the queued reports, objects before the row, a 4xx marks `.failed`, a 5xx waits; `start_worker`/`nudge` = the app's thread (30 s after start, every 15 min, 5 s after a dictation). The dashboard never holds the session: it sends `account` over the pipe (`main.App._account_command`) and reads `status()["account"]`. A static test keeps its imports narrow — never a module that reads a cloud key, never a provider's name. **`REQUIRED = True` is the owner's rule of 2026-09-18: no account, no dictation.** `main.App.locked()` = a configured project and no session → `_lock()` holds the state machine paused with the sign-in sentence (no pause cue; the pause key and the dashboard's Resume put it straight back; the phone is refused), `_unlock()` after a sign-in over the pipe, `sb.SIGNED_OUT_HOOKS` locks again when the session goes (Sign out, Delete, a second 401). The wizard's `account` page (firstrun.py, page 1) has no way past without a session. **And the desk (Q1, 2026-09-18 night): `dashboard._locked_now()` — the app's `status()["locked"]` when it answers, sb.py's own session when it does not — puts the window on the LANDING (`_landing`/`_screen_landing`: the places off the bar, one card, [Sign in with Google], every `_show` refused) until a session exists; the button goes over the pipe to a running app, or runs `sb.sign_in_google` in the window's own process when there is none.** tests.py sets `REQUIRED = False` at import; the lock's tests set it back |
| `sync.py` | what leaves the PC for the account and what never does (D31), no network in it: `syncable()` (the [privacy] gates, the phone endpoint, devices, folders, hotkeys, corners, positions, ports, the hardware tier, the local and Ollama models stay home — `test_sync_serializer_drops_sync_false`), the settings blob and its merge (last writer wins, ≤ 64 KB), `vocab.json` as rows (union by what was heard, higher hits wins, a tombstone for a word forgotten since the snapshot; study.py's hits-0 guesses never travel), `transcripts.log` events as rows and the other PCs' rows back as `REMOTE` lines in `sync\history.log` (history.py folds them into the Said page as "from <device>"); the cursors in `sync\cursor.json` |
| `supabase/migrations/0001_init.sql` + `supabase/README.md` | the whole schema of the account server, pasted once into the project's SQL editor, never a dashboard edit (8.13): seven tables, RLS on each, every policy `to authenticated` with `(select auth.uid()) = user_id`, `anon` revoked from everything, the private `reports` bucket with its limits and three object policies, `delete_me()`; no column can hold a key — every text/jsonb column carries `looks_like_key()`, whose patterns are `redact.PATTERNS` verbatim in the header block (`test_redactor_patterns_match_migration`), and `problem_reports.env` is `problems.env()`'s whitelist (`test_env_matches_server_whitelist`). No `report_replies` (D33). The README is the sceptic's ten-minute read. Export-ignored: it is the repo's proof, not the app's file |
| `.github/workflows/supabase-keepalive.yml` | the weekly knock that keeps the Free project from pausing (8.9): one GET to `/rest/v1/profiles` with the publishable key from a repository VARIABLE; green and silent while the variables are not set |
| `tests.py` | the product suite — hundreds of plain-assert test functions, `NEEDS_SCREEN`, `--no-screen`. Not the file you run |
| `dev\tests_ops.py` | the owner's suite: the nightly run, the git card, the routine's docs — imports `tests.py`'s fixtures, runs only in this checkout |
| `tests_quiet.py` | how both are run: on a hidden Windows desktop, `--no-screen` while he is at the machine (house rule 8). `run_hidden()` is importable, for anything else that must not be seen |
| `.github/workflows/ci.yml` | the product suite on `windows-latest`, `tests.py --no-screen`, on every push; installs `requirements.lock` exactly as the build does (`--require-hashes --no-deps`), `av` from `packs.lock`, `requests` for the phone tests, then `pip check` |
