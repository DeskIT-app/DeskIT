# web/ — the desk's pages

React + TypeScript in the approved B+ look, built into `web/dist` and shown
by `deskweb.py` inside WebView2 (`webdesk.py` is the shell). The desk moves
off Tk one place at a time; `[desk] web` opens it in the checkout only.
Python builds every word; a page only draws what it is answered.

## Build

`node_modules` and `dist` are gitignored. In a new worktree, copy the
modules from the main checkout (offline, no npm install), then build:

```
robocopy <main checkout>\web\node_modules web\node_modules /E /NFL /NDL /NJH /NJS /MT:16
cd web
npm run build        # tsc --noEmit, then vite build into web\dist
```

`npm run typecheck` is the first half alone.

## Photograph a page (hidden, muted)

Every window goes on a hidden desktop (AGENTS.md rule 8):

```
<py> -c "import tests_quiet as q, pathlib; print(q.run_hidden(r'<py> deskweb.py --shot x.png --place said > out.txt 2>&1', pathlib.Path('.'), desktop='DeskITWebShot'))"
```

`run_hidden` returns only the exit code; the shot prints one JSON line into
`out.txt`. Look at the picture before you say it matches. `--place` takes a
sub too (`--place settings/privacy`). `--shot` takes no mutex and a browser
folder of its own: a worktree's mutex is the checkout's, and the owner's
live web desk holds `paths.WEBVIEW_DIR` (a second browser on it fails with
0x800700AA). It asks his running app for `status` and nothing else.

For more than a picture — clicks, timings, a place's answers — write a
probe that calls `deskweb.run_window(api=Api(Model(send=stub)), on_ready=fn)`
and drives the page with `desk.js(...)` and `desk.capture(png)`:

- set `paths.WEBVIEW_DIR` to a temp folder first (the reason above);
- a worktree's control pipe has the SAME name as his live app's: the stub
  answers `status` and nothing else ever reaches the pipe;
- silence `winsound.PlaySound` / `winsound.Beep` before importing the app;
- a worktree's data folder is empty: copy `notify.json`, `review.json`,
  `transcripts.log`, `vocab.json` in from the main checkout for a real
  picture, delete the copies after, never write his files;
- give `run_hidden` a `desktop=` name of your own: other sessions probe
  on this PC too.

## The places, and who owns what

| file | owner |
|---|---|
| `src/places/<place>.tsx`, `src/places/<place>.css` | that place's session |
| `desk_<place>.py` (Corrections, Said, Keys, Settings) | that place's session |
| the `web desk place: <Place>` section of `tests.py` | that place's session — add your tests BELOW the section's first test (`test_web_desk_<place>_is_wired`) |
| Home: `src/places/home.tsx`, `home.css`, and `deskweb.Model` | the Home session |
| `src/kit.tsx`, `src/kit.css`, `src/app.tsx`, `src/desk.css`, `src/bplus.css`, `src/types.ts`, `src/bridge.ts`, `src/main.tsx`, `deskweb.py` outside `Model` | SHARED — frozen while the places are built in parallel |

Need something in a shared file? Keep it in your own file (a glyph, a
type, a small piece), say so in your report, and it moves to the kit at
the merge. No session edits another's files.

**A page** exports `default function <Place>Place({ sub }: { sub: string })`
and draws under one root, `<div className="place-<place>">`. Its route is
`#/<place>` or `#/<place>/<sub>` (`#/settings/privacy` gives Settings the
sub `privacy`). From `../kit`:

- `usePlace<T>("said", args, pollMs)` → `{data, error, reload}`: read on
  mount and every `pollMs` (0: once) while the window is visible; an
  identical answer draws nothing; `reload(fresh)` draws an answer you
  already have (an act that answers with the place, as Home's does — the
  1-8 ms Yes/No), `reload()` reads now.
- `placeCall<T>("said", "act", {do, arg})` → a button; an answer
  `{ok: false, error}` rejects with `error` as the message.
- `useDesk()` → `say(note)` (the toast), `go(place, sub?)`, and `act()`
  for the desk's own buttons (`"old"` opens the Tk desk at a place).
- `IC`, `Caps`, `Segs`, `Away`.

**Its CSS** is one stylesheet with every other place's: every selector in
`<place>.css` starts with `.place-<place>`, and a class a place puts on
`<body>` is named `<place>-…` (Home's is `home-calm`). A test holds both.
Shared pieces (`.title`, the change pills, `.btn`, `.glass`, keycaps) are
in `kit.css` and `bplus.css`.

**Its module** `desk_<place>.py` has `class Place`, built once per window
by `deskweb.Api.place` with the window's pipe function (`send`, as
`control.send`). `read(**args)` answers what the page draws, `act(do, arg)`
does a button; both answer a dict with `"ok"`, `{"ok": False, "error":
words}` to refuse. Calls arrive on threads of their own — hold a lock, as
`deskweb.Model` does. Same sources and same words as the Tk desk's
builder for that place (each stub's docstring names it).
