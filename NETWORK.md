# Every host DeskIT may talk to

Every HTTP request DeskIT's own code makes leaves through one module,
`net.py` — the one window that is not DeskIT's code, the web desk's
WebView2, has a section of its own below.
Before a socket is opened the host is checked against the list below;
a host that is not on it is refused and the refusal is itself a row in
the Network log. After every request — answered, failed or refused —
one row goes to the Network screen (Settings > Privacy > EVERY
CONNECTION) and to `logs\network.log`: time,
host, purpose, bytes up, bytes down, status, the NAME of the secret
used (never its value) and the consent that allowed it. Never a body,
never a header, never a query string.

This page is checked against `net.py` by the test suite
(`test_network_md_matches_net_py`): a host added to the code without a
line here fails the build.

## Hosts

| Host | Purpose words | Why | Sends a secret? | Gate |
|---|---|---|---|---|
| `127.0.0.1` | `ollama`, `notify`, `room` | Ollama on this PC; the app's own phone listener (the Claude Code hook knocks on it); `room` is the app asking Ollama which models it holds and unloading them while a game needs the graphics card — and while it does, every other request to Ollama is refused before a socket | the phone token, to our own listener only | none — loopback is the one host allowed in Offline mode |
| `generativelanguage.googleapis.com` | `polish`, `punctuate`, `translate`, `lookup`, `review`, `study`, `reading`, `transcribe`, `ask-screen`, `key-test`, `catalog` | Gemini, with your own key | your Gemini key, in the `x-goog-api-key` header, to this host only | cloud text / cloud audio / cloud screenshots consent |
| `api.groq.com` | the same words, and `summary` — the one sentence a "Claude finished" card says instead of the message's first lines (the head and the tail of the message Claude ended with; Groq only, never Gemini) | Groq, with your own key | your Groq key, as a bearer, to this host only | the same consents (`summary` under cloud text) |
| `huggingface.co` | `model-download` | the Hebrew model, once, from its model card's repository at a pinned commit | never — the repositories need no token and the app has none | the download step itself is the consent |
| `cdn-lfs.huggingface.co`, `cas-bridge.xethub.hf.co`, and any host under `.huggingface.co` or `.hf.co` | `model-download` | where huggingface.co redirects a model file to; the CDN hostname changes by region and year (`us.aws.cdn.hf.co` on 2026-09-17) | never | the same |
| `pypi.org` | `pack-install` | the lock tool's metadata look-up (the owner's checkout only) | never | — |
| `files.pythonhosted.org` | `pack-install` | the GPU pack (NVIDIA's cuBLAS, cuDNN, NVRTC) and the skin pack (skia-python), each wheel pinned by hash; pip then installs them with no network | never | the pack step itself is the consent |
| `api.github.com` | `update-check` | the weekly look at GitHub Releases for `latest.json` — no identifier of any kind | never | the update-check switch (asked once) |
| `github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com` | `update-check`, `update-download` | the release page and the installer file it links to, verified by SHA-256 before it is run | never | the same, and your click on Download |
| `eogvmcbwfthxedcltyrs.supabase.co` — the one project named in `sb.py` (`net.SUPABASE_HOST`; Frankfurt) | `account`, `sync`, `history`, `report` | the optional account: sign-in (anonymous, or Google through Supabase's own flow), your learned words and changed settings, what you said and your cloud keys — those two sealed under your account's own key before they leave (`vault.py`; the server carries only sealed text, a public key and a wrapped key, never the key itself), the problem reports you chose to send; and, while you are signed in with a sync on, one open websocket on your account's own topic (`sync`, status 101 on the row that opened it, a `closed` row with the bytes when it went) that carries only "a store changed on another PC — go and pull" | your account's session token as a bearer, to this host only; the project's PUBLISHABLE key in the `apikey` header (public, opens nothing); never a Groq or Google key in a header — they travel only inside the `vault` rows, sealed | the account consent, then one consent per sync; the reports consent |

The Supabase host is a single value, never a suffix rule: a suffix would
admit any project on that domain. The schema of that project is
published in `supabase/migrations/` and has no column that holds a key
the server can read: your cloud keys reach it only inside the `vault`
rows, locked with a key only your own PCs hold, and only while your
settings sync to your account.

## The desk's web window (WebView2) — outside `net.py`

When the desk opens as a web page (`deskweb.py`; today only in the
developer's own copy), the page is drawn by Microsoft Edge WebView2, a
component of Windows that DeskIT does not ship and cannot change.
WebView2 has network code of its own, so `net.py`, the Network screen
and Offline mode do not reach it. It is kept quiet another way, and
measured:

- The page is DeskIT's own files from the app folder (`app\web\dist`),
  mapped onto a name reserved never to exist on the internet
  (deskit.example) — no server, no port. Every request and every
  navigation to anything else is refused before it starts (`webdesk.py`),
  and the page's own security policy forbids it to fetch, load or send
  anything that is not its own.
- The window's own services are switched off when it starts
  (`webdesk.py`): SmartScreen, Edge's experimentation service, the
  component updater, proxy discovery, every name lookup inside its
  network code, and Edge's sign-in with the Windows account
  (`msOneAuthWAM`). Crash reports stay on this PC.
- Measured on 2026-10-23, WebView2 Runtime 155.0.4283.62, with
  `dev\web_census.py`, which asks Windows for every socket of every
  process of the window four times a second: a first start, 60 s — 0
  sockets; the start after it, 180 s — 0; a later start held open for
  15 minutes, and 10 seconds past its close — 0 (3,230 samples, up to
  7 processes).
- What the sign-in switch stopped: without it, a first start held no
  connection, but each of the 6 starts after a first one opened two
  encrypted connections to substrate.office.com (Microsoft 365) 2 to 4
  seconds after the page loaded, and kept them (in two of the six, a
  third that closed at once). Windows' own name
  lookup found that host, not the browser's, which is why a browser
  network log never showed them. They were encrypted, so what they
  carried was not read; the browser's own code names the Windows
  account's profile and photo on that host.
- What no app can switch off: Microsoft documents that WebView2 collects
  some required diagnostic data whatever the Windows diagnostic setting
  says, and that the optional part follows the Windows setting under
  Privacy & security, Diagnostics & feedback. None of it appeared as a
  socket of the window in the runs above. It is Microsoft's data about
  its own component, under Microsoft's privacy statement — nothing
  DeskIT sends or can read.

## What never goes out

- Anything at all while Offline mode is on, except to `127.0.0.1` (the
  web window's switches above are on whether or not Offline mode is).
- A transcript, a recording or a screenshot to any host without the
  consent row for that kind.
- A key, as it is, to any host but the one provider that issued it. Your
  account gets only the locked copy the settings sync carries.
- A key in a URL: any query parameter named like one (`key`, `token`,
  ...) is refused on every host.
- A request from DeskIT's code to a host not on this page.

## How to check for yourself

1. Open Settings > Privacy > EVERY CONNECTION > Open the Network
   screen, or read `logs\network.log`.
2. Dictate, translate, look something up. Every row names its host and
   purpose. With no cloud consent granted, the only rows are
   `127.0.0.1`.
3. Put a firewall rule on `deskit` if you like: the list above is the
   whole allowlist.
4. The web window's processes are `msedgewebview2.exe`, shared with
   every other program on the PC that uses WebView2 (six others on the
   developer's PC that day). `dev\web_census.py` in the repository
   watches the desk's own and nobody else's.
