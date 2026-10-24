# web/ — the desk's pages

React + TypeScript in the approved B+ look, built into `web/dist` and shown
by `deskweb.py` inside WebView2 (`webdesk.py` is the shell). All five
places are here (2026-10-24); `[desk] web` opens it in the checkout only
until the launch (`deskweb.LAUNCHED`), and the Tk desk stays the fallback
where WebView2 is missing. Python builds every word; a page only draws
what it is answered.

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

## The places, and what they share

| file | what it is |
|---|---|
| `src/app.tsx` | the frame: the bar, the router, the toast, the lock's line over every place but Home, Home's 800 ms poll |
| `src/kit.tsx` + `src/kit.css` | every piece two places draw: `IC` (the glyphs), `Caps`, `Switch`, `Seg` (a track with one sliding bubble — the bar, Said's filters, Settings' tabs), `Change` / `Segs` (the change figure), `placeCall`, `usePlace`, `useDesk`, `useHome` |
| `src/types.ts` | what Home's answer is (`deskweb.Model.home()`) |
| `src/bridge.ts` | the one road to Python (DeskIT's own channel) |
| `src/places/<place>.tsx`, `.css` | one place: Home, Corrections, Said, Keys, Settings |
| `desk_<place>.py` | that place's Python (Home's is `deskweb.Model`) |

A piece two places would copy goes in the kit; a piece one place draws
stays in that place's file. A new glyph is a name in `IC`.

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
  for the desk's own buttons (Home's verbs and the bar's).
- `IC`, `Caps`, `Switch`, `Seg`, `Change`, `Segs`.

**Its CSS** is one stylesheet with every other place's: every selector in
`<place>.css` starts with `.place-<place>`, and a class a place puts on
`<body>` is named `<place>-…` (Home's is `home-calm`). A test holds both.
Shared pieces (`.title`, the change pills, `.btn`, `.glass`, keycaps) are
in `kit.css` and `bplus.css`.

**Its module** `desk_<place>.py` has `class Place`, built once per window
by `deskweb.Api.place` with the window's pipe function (`send`, as
`control.send`). `read(**args)` answers what the page draws, `act(do, arg)`
does a button; both answer a dict with `"ok"`, `{"ok": False, "error":
words}` to refuse. Everything that comes from the page — `do`,
`arg`, `read`'s args — is untrusted: allowlist `do`, and check every
argument before it reaches a file path, a process, a URL, a pipe verb or
a consent (`deskweb.Model._do`'s `consent.on` and `_notify_id` are the
pattern); a failure answers with the exception's type, never its text. Calls arrive on threads of their own — hold a lock, as
`deskweb.Model` does. Same sources and same words as the Tk desk's
builder for that place (each stub's docstring names it).
