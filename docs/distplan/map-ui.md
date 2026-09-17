# DeskIT distribution map — Dashboard, settings, first-run and overlays

Repo: `C:/Users/shimr/Desktop/Organized/Projects/DeskIT` (read-only survey, 2026-09-15).
All line numbers are as of that day. Files in scope: dashboard.py (8548 lines), settings.py (1445),
ui.py (1866), widgets.py (683), keyboard.py (623), firstrun.py (711), fonts.py (169),
install_fonts.py (86), shelf.py (586), shelf_card.py (1032), overlay.py (4286), popup.py (4256),
skin/ (17 modules, 6144 lines), make_icon.py (213), icon.ico, fonts/ (4 TTF + OFL.txt),
config.py (2432; SetupConfig and set_values), SKIN.md (431).

## Purpose

This subsystem is everything a person SEES of DeskIT other than the pasted words:

1. **The dashboard** (`dashboard.py`) — a separate pythonw process, one 1160x720 non-resizable Tk
   window with six places along the top: Home / Corrections / Problems / Said / Keys / Settings
   (`NAV`, dashboard.py:286-288). It starts, pauses and stops the app over the named pipe
   `\\.\pipe\DeskIT.control` (control.py:43), and reads config.toml and the JSON stores straight off
   the disk when no app is running (dashboard.py:10-16). One instance is enforced by the mutex
   `Local\DeskIT.dashboard` (singleton.py:30; dashboard.py:8515-8545).
2. **The settings system** (`settings.py` + `config.set_values`) — the Settings place is GENERATED
   from config.toml: every assignment becomes a row, the comments become its help, an `a | b | c` at
   the front of a comment becomes a menu (settings.py:1-56). Nothing is typed by hand except the
   plain-English words (`TABS`, `_MORE`/`WORDS`, `SECTION_WORDS`).
3. **First run** (`firstrun.py`) — a three-step wizard (microphone with live meter, one recorded
   sentence read back, the keys) that runs once per copy, keyed on a gitignored marker file
   `.setup-done` (firstrun.py:65) or the `[setup] done` override (config.py:242-256).
4. **Overlays** (`overlay.py`, `shelf.py`/`shelf_card.py`, `popup.py`, `skin/`) — the splash, the
   status dot, the hint card, the review card, the notify column, the problem/answer cards, the shelf
   panel beside the dot, and the raw-Win32 lookup popup. `skin/` is an optional Skia "glass"
   re-skin (LAMPLIGHT palette) that can be deleted with no migration (skin/__init__.py:1-30; SKIN.md).
5. **Look-and-feel plumbing** — `ui.py` (palette, rounded Pillow faces, the DrawTextW bidi text
   path, font selection), `widgets.py` (tabs, chips, pile rows), `keyboard.py` (a drawn 104-key
   board lit from the bindings), `fonts.py`/`install_fonts.py` (Rubik, OFL), `make_icon.py`/`icon.ico`.

## Files and what each does

| file | role | reads | writes / side effects |
|---|---|---|---|
| dashboard.py | the control window, six places, settings screen, key rebinding, report box, git buttons | config.toml, vocab.json (461, 3626), transcripts.log via history (281, 1902), review.json (3822), problems.json (3879), questions.json (3941), notify.json/notify.log (6479, 6514), recent/*.wav (5519), corpus/read (213-215), icon.ico/.png (88-89), status over the control pipe | config.toml via set_values (7813, 8267) or via the app's `option`/`rebind` pipe commands (7799-7809, 8256); review.json verdicts (3837-3853); problems.json/problems.md/problems/ (4498-4572, 3970-3984, 6195-6229); questions.json answers (5057-5122); problems/weekly/push.log (887-915); corpus/read/texts/written-*.txt + wavs through reading.py (2437-2466); clipboard (8068-8103); per-window relaunch properties (539-622); spawns git (918-948), weekly_review.ps1 (5159-5186), wscript Dashboard.vbs (1158-1181), pythonw main.py via launch (7987-7997) |
| settings.py | config.toml -> `Section`/`Setting` rows; TABS/TAB_SECTIONS/WORDS; fold rule | config.toml (read, 187-269) | nothing ("Writing is not done here", 52-55) |
| config.py (in scope: SetupConfig 242-256, set_values 2340-2432) | dataclasses + validation; the comment-preserving line editor | config.toml | config.toml via atomic `config.toml.<pid>.new` + os.replace (2413-2432) |
| ui.py | palette (+ skin repaint hook 95-118), `_gdi_face`/`pick_face` (120-161), fonts.load at import (171-175), face names (182-189), type scale, Card/Button/Switch/Dropdown/Field/Scroller, `draw_text` DrawTextW+DT_RTLREADING (1635-1715), `icon_bitmap` | icon.ico/icon.png (356-377) | GDI private font load (through fonts.py) |
| widgets.py | Tabs, StateChip, PileRow, rtl_run, ToneButton, button_width | ui.* at call time | none |
| keyboard.py | full-size ANSI board as one PIL image; `bindings()` maps config keys to caps | config.toml when no status (296-300); fonts/Rubik*.ttf via ImageFont.truetype (409-415, 436-440) | none |
| firstrun.py | the wizard: mic meter, sample sentence, keys | config (SetupConfig), sounddevice device list (127-158) | `audio.device` via set_values (639); `.setup-done` marker (685-688); opens `ms-settings:privacy-microphone` (197); loads the real transcriber = model download/load (304-314) |
| fonts.py | `AddFontResourceExW(FR_PRIVATE)` on every file in fonts\ and any Rubik*.ttf in `%LOCALAPPDATA%\Microsoft\Windows\Fonts` (34-63, 90-118) | fonts/ | process-private font registration only |
| install_fonts.py | optional per-user install: copy to `%LOCALAPPDATA%\Microsoft\Windows\Fonts`, register under `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts`, WM_FONTCHANGE broadcast (31-81) | fonts/ | registry + font folder (per user, no admin) |
| shelf.py / shelf_card.py | the panel beside the dot (state, pile of what wants an answer, last thing said, Screens off, Open the desk); card_for/compose/flat | in-memory pile handed by main.py | none (config writes go through main.py on_change) |
| overlay.py | Splash, StatusDot (805), HintCard (1250), WordPrompt/ProblemCard/AnswerCard (1681-3168), ReviewCard (3172), NotifyCard (3587); work-area/virtual-screen probes (585-660) | nothing on disk | nothing on disk; positions/scale/enabled=false reported to main.py via `on_change`/`dismissed()` which writes config.toml (main.py:623-742, 1420-1505) |
| popup.py | the lookup/translate box: a raw CreateWindowExW class `DeskITLookupPopup` (983) drawn with DrawTextW/Uniscribe | nothing | nothing (clipboard copy buttons) |
| skin/ | palette.py (LAMPLIGHT tokens, UI_NAMES 47), gl.py (wgl context), glass.py (UpdateLayeredWindow window), boot.py (splash card), reveal.py/burst.py (release), dot.py, hint.py, notify.py, review.py, shelf.py, wave.py, preview.py, record.py, ease.py, clock.py | fonts/Rubik.ttf (boot.py:129-131) | dot.py writes the dropped position back through overlay/main (dot.py:360-385); preview/record are dev tools writing PNG/MP4 where told |
| make_icon.py | regenerates icon.ico (16..256) and icon.png from the dalet-as-desk mark | — | icon.ico, icon.png in APP_DIR (commit-time tool) |
| icon.ico, icon.png | the mark; window icon (WM_SETICON, dashboard.py:509-537), taskbar pin icon, home badge | — | — |
| fonts/ | Rubik.ttf, RubikBold.ttf, RubikMedium.ttf, RubikSemiBold.ttf (static cuts of the Google Fonts variable font with rewritten name tables, install_fonts.py:3-9) + OFL.txt | — | — |
| SKIN.md | the design document: how to remove the skin, palette ladder with measured contrast, boot timeline, traps | — | — |
| Dashboard.vbs / DeskIT.vbs / Stop DeskIT.vbs | shortcut launchers: `<folder>\.venv\Scripts\pythonw.exe <folder>\dashboard.py|main.py [--stop]` | — | — |

### How a config.toml key becomes a Settings row (exactly)

1. `settings.read(path)` (settings.py:187-269) runs TWO parsers on purpose: `tomllib.loads` for the
   values (the parser the app trusts) and a line scan for what tomllib throws away — the line number
   of each key and the comments around it. They are reconciled by key; a key the scan finds that
   tomllib did not is a `ValueError` (202-207), and tests.py asserts the reverse (settings.py:24-31).
2. Comment rules (settings.py:39-49): the block under `[section]` is the section's help; an
   unindented block directly above a key (no blank line between) introduces the key; the trailing
   comment plus every INDENTED comment line after it is the key's own; a bare `#` is a paragraph
   break; the block at the top of the file belongs to the "" (general) section.
3. For a `str` value, `_choices` (168-181) takes an `a | b | c` at the very front of the trailing
   comment as the menu; the rest of the comment is the help. `kind_of` (99-108) classifies bool /
   int / float / list / str. A `list`, or a `str` whose first strong letter is Hebrew, is not
   `editable` (81-89): Tk has no bidi caret, and the line editor only writes scalars.
4. `words_for(setting)` (1391-1409) picks what the screen SAYS: a `Friendly(path, label, help,
   names)` from `WORDS` (hand-written for every key — tests.py:19325-19338 asserts the table names
   every key and `SECTION_WORDS` every section), falling back to the key with underscores opened
   and the first sentence of the file's comment.
5. Tab placement: a path named in `TABS` (settings.py:398-590) is drawn there, on its hand-written
   group; every other key is drawn on the tab that owns its section per `TAB_SECTIONS` (605-624),
   one group per section in file order, titled with `SECTION_WORDS`. A section no tab owns lands on
   an `Advanced` tab that only appears when needed (`tab_names`, 671-679). The eight top-level
   `*_hotkey` keys plus the eight nested ones are skipped here and drawn on the Keys screen instead
   (`_keys_screen_paths`, dashboard.py:1219-1226; `NESTED_HOTKEYS`, 334-345). `dot.corner` is
   drawn inside the dot card on General (`BLOCK_PATHS`, dashboard.py:7109-7120). A test holds every
   line of the file to being drawn exactly once (dashboard.py:7186-7190).
6. The fold: `common()` (settings.py:717-745) puts a line on the face of its card if a tab names it
   by hand, if it is a bool, or if it has a menu (file choices or `names`); everything else — a
   number, a duration, a model name, a folder, a list — folds behind one line "N more in this
   section" (`fold`, 748-762; `FOLD_MIN = 2`; dashboard.py:7218-7276). A search never folds
   (dashboard.py:7061-7066); `matches()` (settings.py:283-303) searches the plain words AND the
   file's own dotted name and comment.
7. What the user sees per row (dashboard.py:7348-7396): the plain label (10 pt), up to two lines of
   help (8 pt), and on the right ONE control: a `ui.Switch` for bool; a `ui.Dropdown` for a menu
   (with `audio.device` populated live from sounddevice, 7301-7346); a `ui.Field` for a scalar with
   no menu; or an "In the file" button that opens config.toml in the shell for a list or a Hebrew
   string (7361-7369). Cards are canvas items, one per tick, because 140 rows of widgets cost 2.2 s
   (7147-7169, 7025-7035).
8. The write: `_apply_setting` (7799-7809) asks the RUNNING app over the pipe (`option` -> main.
   set_option, main.py:1915-1935, which validates and takes it live where it can) and falls back to
   `config.set_values(CONFIG_PATH, {path: value})` (7811-7822) when nothing runs. `set_values`
   (config.py:2340-2432) rewrites exactly one assignment line inside the named `[section]`
   (`_section_span`), keeps the aligned trailing comment, refuses to invent a nested key that is not
   already in the file (2394-2398; top-level keys ARE inserted), validates the result with `load()`
   and swaps it in with `os.replace` of a per-pid staging file (2413-2432). Hotkeys go through
   `check_hotkeys` first (dashboard.py:8257-8266).

### Screens that exist today (so new ones can be planned against them)

Dashboard window (1160x720, fixed; `W, H` dashboard.py:97):
- **Top bar** (1526-1620): the mark, six place chips, the state chip (Off/Starting/Listening/
  Recording/Locked on/Transcribing/Paused, `LOOKS` 124-132), Pause/Resume/Start, Stop, Screens off,
  and "Stop tests" while a nightly run is going (115-118, 8019-8055).
- **Home** (1746-1860): headline of what wants an answer (pile of up to 3: notifications, second-
  reading proposals, open reports, routine questions, 2760-3020), "Dismiss all" + Ctrl+Alt+M cap,
  "Report a problem", the band of five doors with counts (3213-3345), "the rest of the day" three
  lines, a footer strip with the awake state, the branch and facts (1838-1856, 3406-3464).
- **Corrections** (2079-2745): tab "Waiting" (second-reading proposals with Yes/No, the vocabulary
  panel 3527-3607) and tab "Read aloud" (a sentence card from corpus/read/texts read into the
  dictation key, kept as (wav, text), a model writes the next paragraph — 2197-2648; a voice panel
  with two progress bars `study.read_sentences` / `study.read_goal_hours`).
- **Problems** (3994-4076): "Changes on this computer — try them, then Push" card with Restart /
  Push / Undo (5228-5407), the routine's questions with 2-5 answer bands and a dictation box
  (4574-5122), the reports with evidence thumbnails and Fixed/Closed/Reopen/delete (4093-4572),
  "Open problems.md".
- **Said** (1901-1975): the last 100 lines of transcripts.log with search and six kind chips,
  "Show more", "Open transcripts.log".
- **Keys** (6520-6895): the legend, the drawn 104-key board lit from the bindings, rows three to a
  line, click-a-cap or press-a-key rebinding dialog "Press a key" (8103-8246) which PAUSES the app
  while listening, a listening card, the foot line about safe keys.
- **Settings** (6896-7900): tabs General / Dictation / Text / Screen / Cards / Phone / [Advanced] /
  The app, plus a magnifier that swaps the tab strip for a search field. Blocks above the rows: the
  DOT card on General (corner menu + "Move the dot" + "Back to the corner", 7474-7663), the PHONE
  card on Phone (Tailscale URL + Copy link, 7664-7690), and on The app: AWAKE (three cards, a
  powercfg/PowerShell probe, 6230-6467), THE APP (branch line, Stop the app, Send a test
  notification, the twenty sound cues with a play button each, 7691-7776) and FILES (open
  transcripts.log / app.log / config.toml / the folder, 7401-7438).
- **Toast/notes** at the foot (1694-1745); the **report box** (ProblemCard) opened from Home/
  Problems (5586-6229) with a screenshot thumbnail, the recording and the branch attached.

First-run wizard (firstrun.py, 720x560): step 1 microphone list + live meter + silence warning with
a button to `ms-settings:privacy-microphone`; step 2 "say one sentence" recorded 3 s and transcribed
by the real backend; step 3 the keys (420-530). Labels here are Hebrew (522-566).

Overlays owned by the app process (overlay.py / skin): Splash (113), StatusDot (805, five states,
a button and a drag handle), HintCard (1250, the key card while the key is held, with "don't show
this again"), WordPrompt/ProblemCard/AnswerCard (1681-3168, the report box and the routine's answer
card as Tk windows), ReviewCard (3172, the second reading: v/x/l/e keys), NotifyCard (3587, the
notification column), the shelf (shelf.py: state, pile, last line, Screens off, Open the desk), the
lookup Popup (popup.py:1314, raw Win32, appears at the selection), and the ask-the-screen card
(visual_qa.py — another subsystem, but painted from ui's palette).

## Personal data stores

Everything below lives INSIDE the code folder (`APP_DIR = Path(__file__).resolve().parent`,
dashboard.py:86, firstrun.py:51, fonts.py:29, keyboard.py:65) unless stated. `.gitignore` already
classifies most of it as "a record of what you actually dictated — keep it off any remote".

| what | where | format | sensitivity | must be per-user? | who in this subsystem touches it |
|---|---|---|---|---|---|
| Settings, incl. the microphone's device NAME, absolute capture/camera/clip folders under `C:\Users\shimr\...`, the owner's hand-seeded `vocab.terms` (personal names), card/dot screen coordinates, model names | `config.toml` | TOML with 2/3 comments (tracked in git!) | medium: personal names, machine paths, hardware names | yes — and it must ALSO be split from the shipped defaults (see risks) | settings.py reads; config.set_values writes (dashboard.py:7813, 8267; firstrun.py:639; main.py on_change) |
| "wizard has run on this copy" | `.setup-done` | 2-line text | none | per install | firstrun.py:65, 683-692 |
| Learned corrections (heard -> meant pairs) | `vocab.json` (+ `vocab.json.bak-*`) | JSON | high (words the user said and what they meant) | yes | dashboard.py:456-467 (count), 3608-3640 (pairs shown), 2247/2446 names fed to the Read-aloud writer |
| Every dictation, translation and lookup | `transcripts.log` (+ `.1`) | text log | high | yes | Said screen via history (dashboard.py:281, 1902-1970); opener 7407-7408 |
| The app diary (holds pasted text per .gitignore) | `app.log` (+ .1, .2) | text | high | yes | opener dashboard.py:7410-7411 |
| Second-reading proposals (sentence + proposed word) | `review.json`, `review.lock` | JSON | high | yes | dashboard.py:3817-3853 (reads and writes verdicts) |
| Bug reports: the typed line, raw/final dictation text, a pinned copy of the recording, a screenshot of the whole desktop, the settings and the branch | `problems.json`, `problems.lock`, `problems.md` (digest), `problems/<id>.jpg`, `problems/<stem>.wav`, `problems/weekly/` | JSON + JPEG + WAV + Markdown | VERY high (screenshots can carry mail/banking; audio) | yes | dashboard.py:3855-3895, 3970-3992, 4268-4290, 4498-4572, 5503-5584, 6195-6229 |
| The Saturday routine's questions and the owner's answers | `questions.json`, `questions.lock` | JSON | owner-only content | n/a in distribution | dashboard.py:3896-3968, 4574-5122 |
| Notifications from other programs (titles/bodies of Claude Code turns), reminders, dismissals | `notify.json`, `notify.log` | JSON + text | high (contents of other programs' messages) | yes | dashboard.py:6468-6519 |
| Raw recent recordings (ring) | `recent/*.wav` | WAV | very high (voice) | yes | dashboard.py:5519-5523 picks the newest as report evidence |
| The read-aloud corpus: the user's prose (dropped .txt/.md), model-written paragraphs, and the recordings of the user reading them | `corpus/read/texts/*.txt`, `corpus/read/texts/written-*.txt`, `corpus/read/*.wav` (+ `corpus/` study pairs) | text + WAV | very high (voice + own writing) | yes | dashboard.py:213-215, 2437-2466 (writes through reading.py:489-500, 564-592) |
| Git log of every push/undo/restart the window made | `problems/weekly/push.log` | text | owner-only | n/a | dashboard.py:887-915 |
| Generated cue sounds | `cues/*.wav` | WAV | none | no (regenerable) | dashboard.py:7765-7776 plays them |
| Looked-up text cache | `lookup_cache.json` | JSON | high (what the user was reading) | yes | not this subsystem (named in .gitignore; config.py:453) |
| Phone endpoint secret | `server_token.txt` | text | secret | yes | shown as part of the phone URL on the Phone card (dashboard.py:7673-7677, 8091-8099) |
| API keys | `.env` beside the code | text | secret | yes | not read here (apikey.py); README:53-58 |
| Rubik per-user install | `%LOCALAPPDATA%\Microsoft\Windows\Fonts\Rubik*.ttf` + `HKCU\...\CurrentVersion\Fonts` values | files + REG_SZ | low | per Windows user | install_fonts.py:31-81; fonts.py:34-40 reads the folder back |
| Taskbar pin relaunch metadata (absolute path of Dashboard.vbs, the app ID, icon path) | Windows per-window property store / pinned tile | shell properties | low (leaks install path) | per user | dashboard.py:539-622 |
| Transient: a screenshot as `%TEMP%\report-shot-*.jpg` for the thumbnail, unlinked in the same call; `config.toml.<pid>.new` staging file; clipboard (last dictation, phone link) | %TEMP%, APP_DIR, clipboard | — | high while it exists | — | dashboard.py:5565-5578; config.py:2422-2432; dashboard.py:8068-8103 |

## Machine-specific assumptions (file:line)

- **The code folder is the data folder and the venv folder.** `APP_DIR` is the module's own
  directory everywhere (dashboard.py:86-89, firstrun.py:51-52, 65, keyboard.py:65-66, fonts.py:29-30,
  install_fonts.py:31, make_icon.py:41). Dashboard.vbs:7, DeskIT.vbs:8 and launch.py:41 run
  `<folder>\.venv\Scripts\pythonw.exe`. Every store above is written beside the code; an install
  under Program Files would make `.setup-done`, config.toml and every JSON store unwritable.
- **Owner's name in the AppUserModelID**: `APP_ID = "Yoav.DeskIT.Dashboard"` (dashboard.py:95)
  — this is what Windows groups the taskbar button and the pin by.
- **The shipped config.toml carries the owner's machine**: `audio.device = "Headset Microphone
  (Arctis 7 Chat), Windows WASAPI"` (config.toml:293); `capture.folder` and `camera.folder` =
  `C:\Users\shimr\Desktop\Organized\Photos\Screenshots\DeskIT capture` (788, 999);
  `capture.clip_folder = C:\Users\shimr\Desktop\Organized\Videos\DeskIT` (796);
  `visual_qa.voice = "Microsoft Asaf"` (659, a Windows he-IL SAPI voice that must be installed);
  card positions from a three-monitor desk whose left monitor starts at x = -1920: `hint.x = -1895`
  (265), `notify.x/y = 2188/1373` (1168-1169), `problems.x/y = 1066/511` (1230-1238),
  `review.x/y = 1238/795` (1704-1705); `vocab.terms` (1354) are the owner's own names.
- **Multi-monitor arithmetic** is built around that desk: overlay.py:604-622 (`_virtual_screen`,
  "this machine has a monitor at x = -1920"), popup.py:74-78 (SM_XVIRTUALSCREEN = -1920), the
  `HINT_UNSET = -100000` sentinel (overlay.py:542; config.toml:235-244). Correct in general, but
  every shipped x/y is a coordinate on the owner's desk.
- **DPI 96 and a fixed pixel layout**: "px = pt * 4/3 at this process's DPI, which is 96 here"
  (ui.py:194-195); the window is fixed 1160x720 and non-resizable (dashboard.py:97, 1334-1338);
  everything is `.place(x=, y=)` with hand-measured pixel constants (e.g. 140-235, 372-387). Row
  heights were measured "on the hidden desktop" (7150-7155, 373-381). A 125-150 % laptop is
  untested.
- **Windows 11 fonts**: `ICONS = "Segoe Fluent Icons"` (ui.py:186-189) with a hard-coded codepoint
  table (ui.py:226-240) — Windows 10 ships "Segoe MDL2 Assets" instead; `pick_face` floors at
  "Segoe UI" (ui.py:153-161).
- **GDI Rubik weights**: only 400 and 700 are real through GDI; `MEDIUM` is a family name that draws
  regular (fonts.py:40-52, ui.py:185). keyboard.py:436-440 loads `RubikMedium.ttf` by file path
  (Pillow), which is the same variable font (skin/boot.py:113-126).
- **Full-size ANSI keyboard with a Hebrew layout**: keyboard.py:11-16 ("because that is what is on
  his desk"); Hebrew legends beside Latin caps (dashboard.py:6533-6535).
- **Local Ollama at `http://127.0.0.1:11434`** and `gemma3:12b` (config.toml:326, 472, 610, 1538) —
  settings menus offer "On this computer" whether or not Ollama exists (settings.py:308-317).
- **Git on PATH and a GitHub `origin/main`** for the branch label and the Changes card
  (dashboard.py:918-948, 965-1008, 7900-7916; versions.py). Absent git degrades to `"?"` and an
  empty block (dashboard.py:938, 980-984) — silently.
- **`weekly_review.ps1` and `powershell.exe` under SystemRoot** (dashboard.py:5159-5186);
  `wscript.exe` + `Dashboard.vbs` for relaunch/pin (dashboard.py:601-608, 1168-1181).
- **`ms-settings:privacy-microphone`** URI (firstrun.py:197) — Windows 10/11 only.
- **The nightly test run and the Stop-tests button** assume `nightly.py`'s file contract in APP_DIR
  (dashboard.py:8019-8055).
- **Skia on an RTX 5060 Ti**: all timings in skin/gl.py:11-20 and SKIN.md; the GPU path falls back
  to CPU (`burst.py`) and to Tk when skia is missing — by design, but the CPU rasteriser is 64 ns
  a pixel, so the release is a different animation on a weak machine (SKIN.md "measurements").
- **Fonts side channel**: fonts.py:34-40 also loads any `Rubik*.ttf` from the per-user font folder,
  so a stale user install could shadow the vendored files ("the app's own copies win", 45-52).
- **`HD_SKIN` env var** disables the skin per run (skin/__init__.py:57).
- **Two writers of config.toml** at once (the app and every dashboard instance) is a known race
  handled by per-pid staging (config.py:2413-2421).

## External services and what leaves the machine

This subsystem makes NO network calls of its own: grep for `urllib|requests|http` across
dashboard.py, settings.py, ui.py, widgets.py, keyboard.py, firstrun.py, fonts.py, install_fonts.py,
shelf.py, shelf_card.py, overlay.py, popup.py and skin/ finds only comments and the Ollama URL
default. What leaves the machine leaves through OTHER modules that this one triggers:

| trigger here | goes through | what is sent | consent/gate |
|---|---|---|---|
| First-run step 2 "say one sentence" (firstrun.py:304-314, 578-583) | `transcribers.get_transcriber(cfg)` | 3 s of audio — to Gemini only if `backend = "gemini"`; default is `local` (config.toml:196) | none beyond the backend setting; with `local` it downloads ~1.6 GB from Hugging Face inside the wizard with only a "loading the model" status line |
| Read-aloud tab: "write the next paragraph" (dashboard.py:2437-2446) | `reading.Writer(cfg).write(seed, names=names_of(vocab.json))` | the NAMES learned in vocab.json are handed to a model to write prose; which model depends on the app's LLM pool (Ollama first; Groq/Gemini if configured) | none specific — this is the one place this subsystem hands vocabulary to a possibly-cloud model |
| Settings rows for `backend`, `punctuate.prefer`, `polish.prefer`, `lookup.prefer`, `visual_qa.prefer`, `visual_qa.allow_screenshot_upload`, `gemini.models`, `*.groq_model`, `*.cerebras_model` | the app | they DECIDE what other subsystems send | the row's help sentence is the only consent text (settings.py:288-291, 535-538) |
| Push / Undo (dashboard.py:1010-1115) | `git fetch/push origin main` | the repo (code); problems/, logs and stores are gitignored | owner-only feature |
| Phone card (dashboard.py:7664-7690, 8091-8099) | shows/copies the Tailscale URL incl. the token | nothing sent by the dashboard | — |
| Report a problem (dashboard.py:5586-6229) | problems.record — local only today | typed line + dictation text + wav + JPEG of ALL screens (5526-5548) + settings + branch | the plan's Supabase report path would make this the most sensitive upload in the app |
| Awake probe (dashboard.py:6440-6456) | awake.probe -> powercfg / PowerShell | nothing leaves | — |
| `os.startfile` on files/folders/ms-settings (launch.py:74-79; firstrun.py:197) | the shell | nothing | — |

## Owner-only or developer-only features

- **Problems tab git card**: "Changes on this computer — try them, then Push" with Restart / Push /
  Undo (dashboard.py:5228-5407); `local_changes`, `push_main`, `undo_main`, `restart_app`
  (965-1181); `TRUNK = "main"`, `PUSH_LOG` (867, 887); the 60-line rationale at 831-871 is about
  how the owner and Claude Code work.
- **Branch stamps**: `_warm_branch` via versions.py (1339-1357, 7900-7916); "branch '…' - running
  now" under The app (7743-7745); the home footer strip (3406-3464); problems.py stamps reports with
  it.
- **The weekly routine's questions**: questions.json rows and the answer bands on Home and Problems
  (2991-3020, 4574-5122); `_wake_review` spawns `weekly_review.ps1 -Answered` (5124-5193);
  "Saturday's read is waiting on an answer" (3008); "Open problems.md" digest (3970-3992, 4058-4060).
- **Nightly self-test**: the "Stop tests" bar button (115-118, 2011-2020, 8019-8055) and the
  `[tests]` rows on The app tab (settings.py:1265-1274, 622-623; config.toml:1755-1790).
- **`notify.watch = "cowork"`** — watching the Claude app's own pop-ups (settings.py:1046-1048;
  config.toml:1144).
- **"Send a test notification"** and the twenty cue play buttons (dashboard.py:7737-7762) — the
  latter is arguably user-facing; the former is a developer aid.
- **`backend = "fake"`** exposed on General as "Fake, for testing" (settings.py:271-273; config.py:16).
- **`lookup.dwell_ms`** is documented DEAD (config.toml:522-528; settings.py:927-929) and still
  shown.
- **Read aloud / voice corpus** (Corrections tab, `study.read_sentences`, `study.read_goal_hours`,
  `study.corpus_keep`) — material "for teaching the model your own voice one day" (settings.py:1170-
  1180): the owner's fine-tune project, not a user feature.
- **`awake.vitals_minutes`** health lines, `awake.pin_timeouts` (changes Windows power settings;
  settings.py:1029-1036).
- **Dev tools**: skin/preview.py, skin/record.py (needs PyAV + a real desktop grab), fonts.py's
  `main()` probe, install_fonts.py, make_icon.py (commit-time), `HD_SKIN`.
- **Owner-specific defaults baked into the tracked config** (see machine-specific list) and the
  `APP_ID` (dashboard.py:95).
- **"Report a problem"** is user-facing in shape but its consumer today is the owner's Saturday
  Claude Code routine reading local files (`.gitignore` comment "The weekly review reads these local,
  untracked files by design").

## What breaks on a fresh machine

1. **No venv, no launch**: Dashboard.vbs/DeskIT.vbs expect `.venv\Scripts\pythonw.exe` beside the
   scripts (Dashboard.vbs:7; launch.py:33-49 falls back to `sys.executable`'s pythonw only for
   spawns from Python).
2. **Pillow is a hard runtime dependency that requirements.txt does not list**: `ui.py:34`,
   `keyboard.py:59`, `shelf_card.py:76` import PIL unconditionally (the dashboard, the wizard and
   the shelf cannot start without it); requirements.txt names sounddevice, numpy, pywin32,
   google-genai, pycaw, faster-whisper, nvidia-*, skia-python only; make_icon.py:5-6 even says
   "Needs Pillow, which is not in requirements.txt". The venv happens to hold pillow 12.3.0.
3. **Read-only install location**: `.setup-done` (firstrun.py:65, 685), config.toml's staging file
   (config.py:2422), every JSON store and log are written into APP_DIR. If mark_done fails "the
   wizard would come back" every launch (firstrun.py:683-692).
4. **The wizard starts on the owner's microphone string** (`self.device = cfg.audio.device or
   default_device()`, firstrun.py:334); `order_for` puts the chosen key first only if it exists in
   the listing (161-170); `_save_device` writes nothing if the user does not change the row (633-
   636). A user who presses Next without picking keeps "Headset Microphone (Arctis 7 Chat), Windows
   WASAPI" — config.toml:291-303 records that a stale device once "stopped the app from starting at
   all".
5. **Model download inside the wizard**: step 2 calls the real transcriber (firstrun.py:304-314);
   on a fresh machine that is the 1.6 GB Hugging Face fetch plus a CUDA-or-CPU load behind the
   single Hebrew status "טוען את המודל ומתמלל…" (578-579), with no size warning, no progress and
   no consent; on CPU the sample takes ~40x longer.
6. **Absolute capture folders** under `C:\Users\shimr\...` (config.toml:788, 796, 999) — either a
   stray directory tree gets created on the other user's C: or the save fails; the Settings row
   says "A plain name means a folder beside the app" (settings.py:559-561), so the fix is a plain
   default.
7. **Card/dot coordinates from a three-monitor desk** (config.toml:265-266, 1168-1169, 1230-1246,
   1704-1705) are clamped to the new virtual screen (overlay.py:604-622), so cards land in odd
   places until dragged. Ship `-100000`.
8. **`visual_qa.voice = "Microsoft Asaf"`** absent -> no spoken answers (other subsystem, but the
   row is on Screen tab as a bare field).
9. **Windows 10**: no "Segoe Fluent Icons" (ui.py:189) -> every glyph in `ICON` (ui.py:226-240) is
   a tofu box on the bar, the doors, the files card and the buttons; `_dark_caption` (dashboard.py:
   624-643) is guarded.
10. **High DPI**: the fixed 1160x720 hand-placed layout (ui.py:194-195; dashboard.py:97) has not
    been measured off 96 DPI.
11. **No git**: branch shows `?`, Changes card silently empty (dashboard.py:938, 980-984) — harmless
    but the Problems tab still reserves the block.
12. **No Ollama**: menus still offer "On this computer" for lookup/polish/translate/visual_qa
    (settings.py:308-317, 274-277); the failures surface elsewhere.
13. **skia-python missing or no GPU**: skin reports off; Tk overlays return (SKIN.md "Getting rid
    of it") — a downgrade, not a crash. On a GPU-less machine the release uses burst.py and the CPU
    rasteriser (skin/gl.py:44-47).
14. **comtypes missing**: the taskbar pin metadata is skipped quietly (dashboard.py:614-622); pin
    would show pythonw's icon.
15. **Fonts**: nothing breaks — Rubik loads privately from fonts\ (fonts.py:90-118) and falls back
    to Segoe UI; install_fonts.py is optional. Licensing is clean (OFL 1.1, fonts/OFL.txt; the four
    files are cuts of the Google Fonts variable font with rewritten name tables, install_fonts.py:3-9
    — an OFL "Modified Version", which the licence permits provided the OFL text ships with them and
    the Reserved Font Name rules are respected: Rubik's OFL header declares no RFN).
16. **The shelf/hint/notify cards hand `enabled = false` or x/y back to main.py** which writes
    config.toml (main.py:1420-1505) — fine, but again into APP_DIR.

## Settings classification (per config.toml key)

Legend — **U** user-facing (keep on a normal Settings page), **A** advanced (fold or an Advanced
page), **D/M** developer-or-machine (remove from the user build, or make it per-machine state
outside config.toml). Tab = where settings.py draws it today; "Keys" = drawn on the Keys screen.

**Top of file ("The basics", tab Dictation / General / Keys)**
- hotkey (65) Keys U · english_hotkey (87) Keys U · latch_hotkey (96) Keys U ·
  translate_hotkey (106) Keys U · punctuate_hotkey (126) Keys U · correct_hotkey (147) Keys U ·
  lookup_hotkey (167) Keys U · pause_hotkey (186) Keys U
- auto_language (81) General U · auto_pause_fullscreen (192) General U ·
  backend (196) General U — but drop the `fake` choice (D) · indicator (208) General U ·
  fallback_to_local (204) Dictation U · splash (205) Dictation U
- paste_chord (197) A · restore_delay_ms (198) A · min_seconds (199) A · max_seconds (200) A ·
  latch_max_seconds (201) A

**[dot] (General)** — corner (229) U · x (235) M · y (236) M (screen coordinates written by "Move
the dot"; per-machine state, not a setting)

**[hint] (Cards)** — enabled (253) U · after_ms (255) A · corner (259) U · x (265) M · y (266) M ·
scale (274) U (written by the card's − / +)

**[setup] (Dictation)** — done (289) D/M (an override for a per-install fact; the real record is
`.setup-done`)

**[audio] (Dictation)** — sample_rate (292) D · device (293) U-but-M (a per-machine hardware name;
must never ship a value)

**[feedback] (Dictation)** — enabled (307) U · placeholder (308) A · retry_seconds (309) A

**[translate] (Text)** — target (316) U · max_chars (317) A · ollama_model (319) A ·
ollama_url (326) M · timeout_s (327) A · ollama_timeout_s (328) A · settle_ms (331) A

**[punctuate] (Text)** — auto (344) U · max_wait_s (355) A · max_chars (359) A · prefer (361) U ·
groq_model (377) A · ollama_model (378) A · nikud (379) U

**[lookup] (Text)** — hebrew_share (419) A · both_ways (423) U · max_chars (433) A ·
prefer (445) U · model (472) A · cold_to_gemini (480) A · keep_alive (505) A · strip_niqqud (520)
U · dwell_ms (522) D (dead) · max_width (529) A · max_height (530) A · cache_entries (544) A ·
skip_consoles (552) A

**[visual_qa] (Screen)** — enabled (591) U · visual_qa_hotkey (593) Keys U ·
allow_screenshot_upload (598) U (privacy switch) · prefer (606) U · ollama_model (610) A ·
groq_model (619) A · gemini_fallback (631) A · max_side_px (637) A · num_predict (647) A ·
speak (654) U · voice (659) M (installed SAPI voice) · auto_send (667) U · echo_to_field (677) U ·
window_alpha (697) A · warmup (708) A · ollama_timeout_s (712) A · cloud_timeout_s (717) A

**[capture] (Screen)** — enabled (765) U · capture_hotkey (767) Keys U · record_hotkey (783) Keys
U · folder (788) U-but-M (absolute owner path today) · clip_folder (796) U-but-M ·
copy_to_clipboard (801) U · after_shot (805) U · toast_corner (812) U · toast_seconds (820) A ·
toast_stack (825) A · toast_in_shots (840) A · always_save (854) U · copy_clip_path (869) A ·
fps (873) A · quality (881) U · cursor (886) U · audio (891) U · max_minutes (902) A ·
timer_corner (905) U · announce (919) U

**[camera] (Screen)** — enabled (957) U · camera_hotkey (959) Keys U · device (963) M ·
size (972) A · fps (980) A · mirror (985) U · timer (995) U · folder (999) U-but-M ·
copy_to_clipboard (1006) U · edit_after_shot (1009) U

**[awake] (The app)** — hold (1042) U · enabled (1045) U · screens_hotkey (1048) Keys U ·
screens_off_again_s (1051) A · keep_screens_off_s (1055) A · vitals_minutes (1062) D ·
pin_timeouts (1071) A (writes Windows power settings)

**[notify] (Cards)** — enabled (1094) U · cue (1096) U · card_seconds (1098) A · stack_max (1103)
A · remind_every_s (1107) A · remind_times (1110) A · coalesce_s (1113) A · interrupt (1117) U ·
quiet_s (1128) A · watch (1144) D (Claude/Cowork-specific) · corner (1158) U · anchor (1162) A ·
x (1168) M · y (1169) M · scale (1176) U · dismiss_hotkey (1177) Keys U

**[problems] (Cards)** — enabled (1200) U · report_hotkey (1203) Keys U · shot (1208) U (privacy) ·
keep_audio (1216) U (privacy) · keep_resolved (1224) A · x (1230) M · y (1238) M · card_x (1240)
M · card_y (1246) M

**[shelf] (Cards)** — enabled (1265) U · shelf_hotkey (1268) Keys U · rows (1272) A ·
corner (1275) U · x (1281) M · y (1287) M · scale (1289) U · hush_notifications (1290) A

**[server] (Phone)** — enabled (1305) U · host (1306) A/M · port (1307) U

**[vocab] (Dictation)** — enabled (1321) U · max_terms (1322) A · replace_after_hits (1326) A ·
hebrew_after_hits (1330) A · keep_audio (1339) A (privacy: how many recordings are kept) ·
terms (1354) U (a list: "In the file" today; personal data living in the tracked file)

**[study] (Dictation)** — enabled (1388) U · idle_minutes (1389) U · max_clip_seconds (1393) A ·
llm_per_day (1395) A · corpus_keep (1400) A (privacy) · read_sentences (1415) D ·
read_goal_hours (1418) D

**[polish] (Dictation)** — when (1466) U · min_chars (1473) A · prefer (1476) U ·
groq_model (1513) A · groq_timeout_s (1527) A · cerebras_model (1532) A ·
cerebras_timeout_s (1536) A · ollama_model (1538) A · max_wait_s (1563) U · warm_up (1570) A

**[gemini] (Text)** — models (1578) A (list) · timeout_s (1584) A

**[local] (Dictation)** — model (1587) D · language (1588) D ("MUST stay pinned") · device (1589)
U/M (auto|cuda|cpu) · cleanup (1590) U · extra_fillers (1592) A (list) · initial_prompt (1598) A
(Hebrew string: "In the file") · english_model (1603) D · english_threshold (1604) A ·
guard_hallucinations (1626) A · beam_size (1629) A · drop_trailing_boilerplate (1640) A ·
extra_boilerplate (1643) A (list) · rolling (1663) A · rolling_window_s (1664) A

**[review] (Dictation)** — enabled (1694) U · card_seconds (1696) A · corner (1701) U ·
x (1704) M · y (1705) M · scale (1708) U · max_changes (1709) A · witness (1712) A ·
accept_key (1723) A · reject_key (1725) A · later_key (1726) A · edit_key (1728) A ·
fix_in_field (1734) U · max_clip_seconds (1740) A · llm_per_day (1743) A · local_model (1750) A

**[tests] (The app)** — nightly (1785) D · wait_seconds (1789) D

Totals: 24 sections (the top of the file + 23 named), ~200 keys. Roughly 85 U (16 of them keys on
the Keys screen), ~95 A, ~25 D/M (of which 17 are x/y/card_x/card_y screen coordinates or device
names that are per-machine state rather than settings).

## Dependencies and binaries

- Python 3.11 stdlib: tkinter/Tk 8.6, ctypes, tomllib, winreg (install_fonts.py), queue/threading.
- **Pillow** — hard dependency (ui.py:34, keyboard.py:59, shelf_card.py:76; make_icon.py); NOT in
  requirements.txt.
- **pywin32** — named pipe (control.py, used by dashboard) and events/mutex (singleton.py).
- **comtypes** (arrives with pycaw) — taskbar relaunch properties, guarded (dashboard.py:561-622).
- **sounddevice** — device listing in the wizard and the Settings microphone menu (firstrun.py:
  127-158; dashboard.py:7301-7321).
- **skia-python** (optional; requirements.txt "OPTIONAL, and deliberately so") — every skin
  module; **opengl32.dll** via ctypes for the GPU path (skin/gl.py:51-74).
- **PyAV** (`av`, arrives with faster-whisper) — skin/record.py only (dev).
- Windows DLLs via ctypes: gdi32 (AddFontResourceExW/CreateFontW/GetGlyphIndicesW/DrawTextW),
  user32 (SPI_GETWORKAREA, GetSystemMetrics, MonitorFromPoint, LoadImageW, WM_SETICON, layered
  windows), shell32 (SetCurrentProcessExplicitAppUserModelID, SHGetPropertyStoreForWindow),
  dwmapi (caption colour), Uniscribe/usp10 (popup.py:769-806).
- Fonts: **Rubik** vendored (SIL OFL 1.1, fonts/OFL.txt), loaded privately by fonts.py; **Segoe
  UI** (Windows) as the floor; **Segoe Fluent Icons** (Windows 11) for every glyph.
- Binaries spawned: `git` (owner-only), `wscript.exe` + `Dashboard.vbs`, `powershell.exe` +
  `weekly_review.ps1` (owner-only), `.venv\Scripts\pythonw.exe` (launch.py), `powercfg`/PowerShell
  through awake.probe.
- Assets: icon.ico (7 sizes) and icon.png, committed; regenerated by make_icon.py (Pillow only).

## Distribution risks

1. **Tracked config.toml is both the defaults and the owner's live settings.** It carries personal
   names (`vocab.terms`), hardware names, absolute paths and desk coordinates (see machine-specific
   list). Any user build that ships this file ships the owner's data, and any update that overwrites
   it destroys the user's settings. settings.py's whole design (comments as help, line editor) is
   bound to ONE file with the comments in it (settings.py:52-55; config.py:1-7).
2. **Everything is written beside the code** (APP_DIR): incompatible with Program Files, with
   per-user profiles on a shared PC, and with a clean uninstall. The `.setup-done` marker in
   particular re-runs the wizard forever if the folder is read-only.
3. **The bug report is the most sensitive object in the app** — a JPEG of all screens
   (dashboard.py:5526-5548), the raw recording, the dictation text and the settings — and the plan
   wants to send reports to Supabase. It needs an explicit preview-and-consent step and per-item
   opt-outs (`problems.shot`, `problems.keep_audio` exist as switches, settings.py:1096-1102).
4. **Owner-only machinery is wired into user-facing pages**: Problems (git card, routine questions,
   problems.md), the bar (Stop tests), The app (branch, test notification), Settings ([tests],
   notify.watch, backend=fake, dead dwell_ms), Corrections (Read aloud / fine-tune corpus).
5. **The wizard downloads a 1.6 GB model silently** and assumes a GPU-class machine; the owner's
   constraint "most users will not have a 16 GB GPU" is not reflected in first-run copy.
6. **Pillow missing from requirements.txt** — an installer built from that file yields a dashboard
   that cannot import.
7. **Windows 10 / high-DPI / single-monitor layouts are unmeasured** (Segoe Fluent Icons, 96-DPI
   pixel constants, fixed window size).
8. **Keys ship pre-bound to the owner's measured-free keys** (config.toml:1-64 explains they were
   chosen against Chrome/Docs/Spotify on his machine); `win+shift+s` is taken from Windows
   (config.toml:767) — a surprise for a new user.
9. **Two processes write config.toml** (app + dashboard); a third writer (settings sync) would need
   the same per-pid staging discipline (config.py:2413-2432).
10. **Hebrew chrome in the wizard** (firstrun.py:522-566) contradicts the "chrome is English" rule
    and relies on pure-Hebrew single-run rendering in Tk.
11. **Phone card shows the token-bearing URL** in plain text on a screen the user may screenshot for
    a report (7673-7677 + 5526-5548).
12. **`APP_ID` names the owner**; the pin's relaunch command bakes the absolute install path.
13. **The optional skin adds a ~50 MB+ wheel (skia-python) and an OpenGL path** for decoration;
    acceptable because it is deletable (SKIN.md), but the installer must decide.

## Recommendations for the plan (concrete)

1. **Split config.toml into three layers, keep the comments once.** Ship `config.toml` as the
   DEFAULTS document (comments = help; this is what settings.py parses for words and choices) and
   write a per-user `settings.toml` overlay in `%LOCALAPPDATA%\DeskIT\` (or `%APPDATA%`) holding only
   changed keys. `settings.read` keeps reading the shipped file for rows/help; `config.load` merges
   the overlay; `set_values` writes the overlay (it already handles "insert a missing top-level key",
   config.py:2399-2410; extend it to create sections). Keep the invariants the tests hold (every key
   drawn once, every key has words, tests.py:19325-19338, dashboard.py:7186-7190).
2. **Move per-machine STATE out of settings**: `dot.x/y`, `hint.x/y/scale`, `notify.x/y`,
   `problems.x/y/card_x/card_y`, `shelf.x/y`, `review.x/y`, `audio.device`, `camera.device`,
   `visual_qa.voice`, `local.device`, `setup.done` -> a `state.json` in the user data dir written
   by the cards' `on_change` (main.py:1420-1505) and by "Move the dot". The Settings page then shows
   ~183 real settings and no coordinates.
3. **Move every store to a user data directory**: transcripts.log, app.log, vocab.json, review.json,
   problems.json + problems/, notify.json/.log, recent/, corpus/, cues/, lookup_cache.json,
   server_token.txt, `.setup-done`, `.env` (keys). One `paths.py` with `APP_DIR` (code, read-only)
   vs `DATA_DIR` (per user); every `APP_DIR / "x.json"` in dashboard.py (461, 3626, 3822, 3826,
   3879, 3941, 6479, 6483, 6514, 5519, 213-215, 887) becomes `DATA_DIR`. The FILES card
   (7401-7438) becomes the user's "where my data lives" page.
4. **Ship neutral defaults**: `audio.device = ""`, `capture.folder = "captures"` and
   `camera.folder = "captures"` (plain name = beside the data dir, matching the row's own help),
   `clip_folder = ""`, all x/y = -100000, `vocab.terms = []`, `visual_qa.voice = ""` (pick the first
   he-IL voice at runtime), `notify.watch = "off"`, `tests.nightly = false`, `backend = "local"`
   with `fake` removed from `_ENGINES` (settings.py:271-273) in the user build.
5. **Gate owner-only UI behind one flag** (e.g. a `developer = false` top-level setting, or the
   presence of `.git` + `weekly_review.ps1`): the Changes card and Push/Undo/Restart (5228-5407),
   the routine's questions (4574-5122), Open problems.md, Stop tests, the branch line, Send a test
   notification, the [tests]/[awake.vitals_minutes]/[notify.watch]/[study.read_*] rows, and the
   Read-aloud tab. `_problems_enabled` (793-810) already shows the pattern of hiding a place by a
   config read before `_build`.
6. **Rework first run for a stranger's machine**: (a) start the microphone row on the SYSTEM default
   when the shipped value does not match a listed device (firstrun.py:334, 161-170), and always write
   the chosen row; (b) before step 2, say the model size, where it goes, and whether a GPU was found
   (CPU = slow), with a real progress bar for the Hugging Face download and a "skip for now" (the
   cloud backend needs a key the user does not have yet); (c) add a step for the API keys with the
   "keys never leave this machine" proof text and a link to the verification page; (d) make the
   wizard's chrome English like the rest (522-566); (e) write the marker into DATA_DIR.
7. **Report-a-problem with consent**: keep the box but show the attachments as toggles (screenshot,
   recording, dictation text, settings) before Send, default the screenshot OFF for cloud reports,
   redact the phone token and the `.env` from the "settings" attachment, and keep the local
   problems.json path as the offline fallback. Never upload `recent/*.wav` without the toggle.
8. **Fix the dependency list**: add `pillow` (and pin `comtypes` explicitly if the pin feature
   stays) to requirements.txt; mark `skia-python` as an optional extra; decide whether the installer
   bundles the skin at all (SKIN.md: delete-able by design).
9. **Windows 10 and DPI**: choose the icon font at runtime (`pick_face(["Segoe Fluent Icons",
   "Segoe MDL2 Assets"], hebrew=False)` — same codepoints for the glyphs used, ui.py:226-240) and
   test the 1160x720 layout at 125 % / 150 % scaling, or call `SetProcessDpiAwareness` and scale
   the constants from `_px()` (ui.py:1625-1633). Test a single-monitor, non-negative virtual screen
   once (overlay.py:604-622 is right in principle).
10. **Rename the AppUserModelID** to a vendor-neutral `DeskIT.Dashboard` (dashboard.py:95) and have
    the installer own the shortcuts/pin instead of the VBS files; keep `Dashboard.vbs`'s
    single-instance behaviour (dashboard.py:8515-8545) via the installed launcher.
11. **Fonts**: keep the private-load path (fonts.py) as the only mechanism; drop install_fonts.py
    from the user build (a per-user font install is a side effect an installer should own if at
    all). Ship `fonts/OFL.txt` next to the TTFs and mention Rubik + OFL in the About text; the four
    renamed cuts are an OFL "Modified Version" and need the licence text distributed with them.
12. **Settings sync (if done)**: sync only the overlay from (1), never the state file from (2), and
    never `vocab.terms`/paths; the per-pid staging in `set_values` (config.py:2413-2432) already
    makes a third writer safe if it goes through the same function.
13. **Use the existing generator for the user guide**: `settings.WORDS`/`SECTION_WORDS` already hold
    a plain-English sentence for every setting and section (tests enforce completeness); a script
    that walks `settings.read()` + `groups_for()` per tab yields the Settings chapter of the guide
    automatically and keeps it in step with the file.
