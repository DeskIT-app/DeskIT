# Every host DeskIT may talk to

Every HTTP request the app makes leaves through one module, `net.py`.
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
| `127.0.0.1` | `ollama`, `notify` | Ollama on this PC; the app's own phone listener (the Claude Code hook knocks on it) | the phone token, to our own listener only | none — loopback is the one host allowed in Offline mode |
| `generativelanguage.googleapis.com` | `polish`, `punctuate`, `translate`, `lookup`, `review`, `study`, `reading`, `transcribe`, `ask-screen`, `key-test`, `catalog` | Gemini, with your own key | your Gemini key, in the `x-goog-api-key` header, to this host only | cloud text / cloud audio / cloud screenshots consent |
| `api.groq.com` | the same words, and `summary` — the one sentence a "Claude finished" card says instead of the message's first lines (the head and the tail of the message Claude ended with; Groq only, never Gemini) | Groq, with your own key | your Groq key, as a bearer, to this host only | the same consents (`summary` under cloud text) |
| `huggingface.co` | `model-download` | the Hebrew model, once, from its model card's repository at a pinned commit | never — the repositories need no token and the app has none | the download step itself is the consent |
| `cdn-lfs.huggingface.co`, `cas-bridge.xethub.hf.co`, and any host under `.huggingface.co` or `.hf.co` | `model-download` | where huggingface.co redirects a model file to; the CDN hostname changes by region and year (`us.aws.cdn.hf.co` on 2026-09-17) | never | the same |
| `pypi.org` | `pack-install` | the lock tool's metadata look-up (the owner's checkout only) | never | — |
| `files.pythonhosted.org` | `pack-install` | the GPU pack (NVIDIA's cuBLAS, cuDNN, NVRTC) and the skin pack (skia-python), each wheel pinned by hash; pip then installs them with no network | never | the pack step itself is the consent |
| `api.github.com` | `update-check` | the weekly look at GitHub Releases for `latest.json` — no identifier of any kind | never | the update-check switch (asked once) |
| `github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com` | `update-check`, `update-download` | the release page and the installer file it links to, verified by SHA-256 before it is run | never | the same, and your click on Download |
| `eogvmcbwfthxedcltyrs.supabase.co` — the one project named in `sb.py` (`net.SUPABASE_HOST`; Frankfurt) | `account`, `sync`, `history`, `report` | the optional account: sign-in (anonymous, or Google through Supabase's own flow), your learned words and changed settings, what you said, the problem reports you chose to send; and, while you are signed in with a sync on, one open websocket on your account's own topic (`sync`, status 101 on the row that opened it, a `closed` row with the bytes when it went) that carries only "a store changed on another PC — go and pull" | your account's session token as a bearer, to this host only; the project's PUBLISHABLE key in the `apikey` header (public, opens nothing); never a Groq or Google key | the account consent, then one consent per sync; the reports consent |

The Supabase host is a single value, never a suffix rule: a suffix would
admit any project on that domain. The schema of that project is
published in `supabase/migrations/` and has no column that could hold a
key.

## What never goes out

- Anything at all while Offline mode is on, except to `127.0.0.1`.
- A transcript, a recording or a screenshot to any host without the
  consent row for that kind.
- A key to any host but the one provider that issued it.
- A key in a URL: any query parameter named like one (`key`, `token`,
  ...) is refused on every host.
- A request to a host not on this page.

## How to check for yourself

1. Open Settings > Privacy > EVERY CONNECTION > Open the Network
   screen, or read `logs\network.log`.
2. Dictate, translate, look something up. Every row names its host and
   purpose. With no cloud consent granted, the only rows are
   `127.0.0.1`.
3. Put a firewall rule on `deskit` if you like: the list above is the
   whole allowlist.
