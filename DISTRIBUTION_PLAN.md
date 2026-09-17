# DeskIT — Distribution plan

Written 2026-09-15 → 2026-09-17, overnight, on the owner's ask: make DeskIT distributable —
per-user data, simple problem reporting, local models and API keys handled, an installer,
versions and updates, a user guide, the screens that need adding, a Supabase backend, and a
proof that a pasted API key never reaches the developer's database. **No code is written by
this plan**; it is the brief the code will be written from.

How it was produced: eight read-only subsystem maps of the repo (every personal store, machine
assumption, outbound host and owner-only feature, cited to file and line), nine web-research
reports (packaging, signing, updates, models, Supabase, key privacy, competitors, legal,
Android), three competing architectures judged and synthesised into 29 numbered decisions
(`decisions.md`, reproduced as chapter 0 below), then one chapter per subject written from
those decisions. The evidence files are in `docs/distplan/` (`decisions.md`, `map-<name>.md`, `research-<name>.md`); the
three competing designs and the judges' notes stayed in the session scratchpad.

Conventions: English; Markdown; no code; `file:line` cites today's repo; `map/<name>` cites a
subsystem map; `research/<name>` cites a research report; `(Dn)` cites a decision; every
chapter ends with Acceptance, Tests to add and, where needed, Open points. `decisions.md`
outranks any chapter.

## Contents

- 0. The decisions (D1–D33)
- 1. Executive summary and principles
- 2. Where the app stands: everything personal, machine-bound or owner-only
- 3. Target layout: directories, config layers, state, secrets, portable mode, migration
- 4. Per-user data, privacy defaults, retention and deletion
- 5. Cloud passes, keys, consent cards and the key-privacy proof
- 6. Hardware tiers, model download, packs, Ollama, TTS
- 7. What the owner-only machinery becomes
- 8. Supabase backend
- 9. Screens: new and changed, with contents and copy
- 10. Packaging, installer, signing and channels
- 11. Versions, updates, rollback
- 12. Android companion: pairing, identity, delivery
- 13. Licence, notices, privacy policy, terms, Israeli law
- 14. User guide, FAQ and support
- 15. Roadmap, effort, acceptance, test plan
- 16. What the owner must do by hand, and open decisions
- A. Appendix: file-by-file change inventory

---

# 0. The decisions (D1–D33)

Synthesised 2026-09-16 from: eight subsystem maps (`distplan/map/*.md`, cited `map/<name>`), nine
research reports (`distplan/research/*.md`, cited `research/<name>`), the complete trust-first design
(`distplan/design/arch-B.md`, cited `arch-B §n`) and the partial user-first design (`arch-A.md`, cited
`arch-A §n`). Where A and B disagreed, the user-first reading won when the owner's constraints allowed it,
because the owner asked for "the most convenient and simple path for the user". No code is written by
this plan; it is the brief the code will be written from.

The one-sentence design: **DeskIT becomes a per-user Windows app whose every personal byte lives in one
folder the user can delete, whose every outbound byte passes one chokepoint the user can watch, whose
API keys live in Windows' own credential store and provably never reach the developer, and whose
first run gets a stranger from download to a Hebrew sentence on screen in one sitting with at most
four decisions.**

## PART 1 — DECISIONS

Format: **Dn — decision.** Reason. Evidence. Rules out. Revisit when.

### A. Runtime layout, config, secrets

**D1 — Three roots, one `paths.py`.** `APP_DIR` (install, read-only: `python\`, `app\`, `app\defaults.toml`, fonts, skin, icon, pre-rendered cues, LICENSE/NOTICES/NETWORK.md/SECURITY.md, `VERSION`, `MANIFEST.sha256`); `DATA_DIR = %LOCALAPPDATA%\DeskIT\` (everything personal: `settings.toml`, `state.json`, `consent.json`, `vocab.json`, `review.json`, `problems.json` + `problems\`, `lookup_cache.json`, `notify.json`, `logs\`, `audio\recent\`, `audio\pending\`, `corpus\`, `models\`, `packs\` (GPU / Recording / Skin wheels installed by pip `--target`), `phone\`, `secrets\`, `cache\`, `tmp\`); pictures and clips in `FOLDERID_Pictures\DeskIT` and `FOLDERID_Videos\DeskIT`. Reason: one folder to find, one to delete, non-roaming (a domain profile must never roam voice data). Evidence: `map/core` rec 1 (call-site list), `map/learning` rec 1, `map/ui` rec 3, `map/owner` rec 2, `map/packaging` rec 1, `arch-B §2`; `arch-A §2` proposed `%APPDATA%` for config — rejected for roaming and for "two folders to explain". Rules out: any `APP_DIR / "<store>"` write; Program Files. Revisit: never.

**D2 — Config in three layers, comments kept once.** `config.load()` = dataclass defaults ← `app\defaults.toml` (today's `config.toml`, scrubbed of the owner's values, comments intact — it still generates the Settings page through `settings.py`) ← `DATA_DIR\settings.toml` (user overrides only, `section.key = value`, scalars and string lists) ← `DATA_DIR\state.json` (per-machine state: every card/dot/hint/shelf/review/notify/problems x/y/scale, `audio.device`, `camera.device`, `visual_qa.voice`, chosen port, `setup_done`, `config_version`). `config.set_values` becomes "write the override file" and learns to create a missing section; the section-only limitation (`config.py:2394-2398`) disappears. Reason: keeps the generated Settings page and its tests; makes updates unable to destroy user settings; removes coordinates from the Settings page. Evidence: `map/ui` recs 1-2, `map/packaging` rec 2, `map/learning` rec 2, `arch-B §2`. Rules out: TOML round-trip serialisers; app writes into `defaults.toml`. Revisit: never.

**D3 — Secrets never in the data folder's plain files.** Groq and Gemini keys → Windows Credential Manager (`win32cred.CredWrite`, targets `DeskIT/groq`, `DeskIT/gemini`; pywin32 already a dependency); Supabase session, phone TLS private key, phone tokens → DPAPI files under `DATA_DIR\secrets\*.bin` (`CryptProtectData`, user scope, `CRYPTPROTECT_UI_FORBIDDEN`) because Credential Manager caps values at ~1280 chars. Key lookup order: Credential Manager → env vars only under a `DESKIT_` prefix (`DESKIT_GROQ_API_KEY`, `DESKIT_GEMINI_API_KEY`; the `GOOGLE_API_KEY` alias that silently borrows a gcloud key is dropped) → developer `.env` only in DEVELOPER/portable mode. Reason: the user can see and delete the keys in Control Panel > Credential Manager, which is part of the proof (D12); no plaintext key beside code ever again. Evidence: `map/cloud` recs 1-2, `research/keys-privacy` §A, `arch-B §2`. Rules out: `.env` in the product; keys in `settings.toml`/`state.json`/logs/reports/exports (tested, D12). Revisit: if a future feature needs a >1280-char secret in Credential Manager (it goes to DPAPI files instead). *Implemented 2026-09-17 as `secretstore.py`: a module named `secrets.py` beside `main.py` would shadow the standard library's `secrets` (`token_urlsafe` in `server.py`, eleven venv files); every later mention of `secrets.py` in this plan means `secretstore.py`. The phone bearer lives in `secrets\phone_token.bin` (name `phone_token`), carried over from `server_token.txt` on the first start and the file deleted. In a portable/developer copy the bare `GROQ_API_KEY` / `GEMINI_API_KEY` environment names are honoured after the `DESKIT_` ones, like the `.env`; an installed copy reads only `DESKIT_*`. `main.py --keys / --set-key / --delete-key` are the terminal surface until the Keys page (chapter 5).*

**D4 — Portable/dev mode keeps the owner's machine unchanged.** `paths.py` decides once: `portable.txt` beside `main.py`, or `DESKIT_PORTABLE=1`, or `.git` beside `main.py` ⇒ today's layout (all roots = the code folder) and the `.env` reader stays. `DEVELOPER = .git present` gates every owner-only UI (git card, Push/Undo, Stop tests, branch line, `[tests]` rows, Read-aloud tab, `--study/--review/--benchmark`). A one-time explicit `deskit --migrate` (never automatic) moves the legacy stores into `DATA_DIR` together (the cross-store ids — `recent\` stem = `review.json` id = report id — must move as a unit), imports `.env` into Credential Manager, and diffs the legacy `config.toml` against `defaults.toml` into `settings.toml` + `state.json`. Reason: owner constraint "his machine keeps working". Evidence: `map/learning` risk 9 and rec 12, `map/ui` rec 5, `arch-B §2`. Rules out: forced migration; two layouts diverging in behaviour. Revisit: never.

**D5 — Collision-proof kernel names and identity.** Pipe `\\.\pipe\DeskIT.control.<session-id>`, mutex `Local\DeskIT.*` (already per-session), port 8756 with fall-through to the next free port written to `state.json` (the hook reads it from there), `notify_watch` temp names per process, AppUserModelID `DeskIT.App` (not `Yoav.DeskIT`), Task Manager shows "DeskIT" via the shortcut/launcher description. Evidence: `map/packaging` risk 7 and rec 9, `map/ui` rec 10. Revisit: never.

**D30 — Two copies on the owner's machine: `DeskIT` (the released build, exactly what everyone gets) and `DeskIT Dev` (the checkout, where changes are made and tested).** Added 2026-09-17 on the owner's word. The checkout keeps today's layout through portable mode (D4) and is the only place code changes happen; the released build is installed from the same installer friends download, into `%LOCALAPPDATA%\Programs\DeskIT` with its data in `%LOCALAPPDATA%\DeskIT` (D1), and updates itself through the same Update card as every user (D21) — the owner dogfoods the real install and update path. Identity: everything global carries a `dev` mark when DEVELOPER/portable mode is on — mutex `Local\DeskIT.dev.*`, pipe `\\.\pipe\DeskIT.dev.control.<session-id>`, default port 8757 (release keeps 8756, both fall through per D5), AppUserModelID `DeskIT.Dev`, Start-menu/desktop shortcut "DeskIT Dev", and a visible DEV tag on the dot tooltip, the shelf and the dashboard bar plus the branch name on Home, so the owner always knows which copy he is looking at. Data: the two copies never share a file; on the owner's machine `--migrate` COPIES the checkout's stores into the released copy's data folder (it deletes nothing unless `--move` is given), so `DeskIT Dev` keeps his vocabulary and history and the released copy starts from a copy of them. Keys: both copies read Credential Manager (`DeskIT/groq`, `DeskIT/gemini`); the dev copy may also read the checkout's `.env` (D3). Running both at once: two hooks on Right Ctrl would record twice, so the copy that starts second sends `pause` over the other copy's pipe (the existing control.py verb), shows one line "DeskIT is paused while DeskIT Dev runs", and sends `resume` on exit; if the second copy dies, the first watches the second's mutex and resumes itself within a few seconds. The phone stays paired to the released copy (its port); the dev copy is exercised with the emulator and `fake_pc.py`. The Claude Code notify hook posts to the dev port first and falls back to the release port, so cards land on whichever copy is up. Tests run only against the checkout, on the hidden desktop, with per-pid names (house rule 8). Reason: the owner asked for a place to keep changing and testing while a stable copy is what he and everyone else use day to day. Evidence: `map/packaging` risk 7 and rec 9 (collisions), `map/core` (singleton.py, control.py), D4, D5. Rules out: a shared data folder between the two copies; running both hooks live at once. Revisit: if the mutual pause proves annoying, the alternative is a distinct hotkey set for the dev copy (`[hotkeys]` overrides in its own `settings.toml`).

### B. Privacy defaults, data, consent

**D6 — Privacy-first defaults for strangers (what ships ON / OFF).** ON: `backend = "local"` (dataclass default fixed from `"gemini"`, `config.py:1219`); learned vocabulary; `vocab.keep_audio = 20` (was 50); `transcripts.log` with a new `[history] keep_days = 30` (0 = off); second reading only when a CUDA device exists and with its own tiny ring (`[review] keep_audio = 3`) so `keep_audio = 0` no longer kills learning; hint/dot/shelf; capture with `capture_hotkey = "ctrl+f11"`, `always_save = false`, `audio = "off"`, `system_sound = false`; weekly update check (asked once, GET only, no identifier). OFF until a consent card: every cloud text pass (`polish.prefer = "ollama"`, `punctuate.prefer = "ollama"`, `lookup.cold_to_gemini = false`, `review.llm_per_day = 0`, `study.llm_per_day = 0`), cloud audio, screenshot upload, `study.enabled`, `study.corpus_keep = 0` (Read-aloud tab hidden), `notify.enabled = false` + `watch = "off"`, `server.enabled = false`, `awake.hold = false`, `vitals_minutes = 0`, `pin_timeouts` under Advanced, account, report upload, sync, lookup cache (`cache_entries = 0`). Removed: Cerebras path, `lookup.dwell_ms`, `backend = "fake"` from the user build, `[tests]`, `vocab.terms` seeds (ship `[]`), owner coordinates, absolute folders, mic name. Evidence: `map/cloud` rec 4, `map/learning` recs 3-6, `map/capture` rec 1, `map/owner` recs 8-9, `map/ui` rec 4, `arch-A §3`, `arch-B §3`. Revisit: `keep_days`/`keep_audio` numbers after the first users' feedback.

**D7 — Consent gates enforced in code, lazy, recorded.** A `[privacy]` section: `cloud_text`, `cloud_audio`, `cloud_screenshots`, `account`, `report_upload`, `settings_sync`, `update_check`, `offline`. One function `privacy.allowed(kind)`; every cloud constructor (`GeminiTranscriber`, `GeminiTranslator`, `GroqTranslator`, `GroqVision`, `GeminiVision`, Supabase client) calls it and refuses to build when the gate is shut — the pattern `visual_qa.Chain._builders` already uses and `tests.py:10804-10836` already asserts. A gate flips only through its consent card; `consent.json` records `{kind, text_version, when, app_version}`; withdrawing tears the clients down. Consent is lazy: the first key press that needs a cloud pass opens the card for that kind. The cloud-text card states that rolling sends stretches before the key is released and that learned word pairs travel in the request (the polish glossary gets filtered to pairs present in the text, like `review.py:643-645` already does). Evidence: `map/cloud` rec 3, `map/capture` "Guarantees in code", `map/learning` rec 4, `arch-B §4`. Rules out: prompts as guarantees; config-only switches for egress. Revisit: never. *Gates implemented 2026-09-17 as `privacy.py` (PR 5): `KINDS` = cloud_text / cloud_audio / cloud_screenshots / account / report_upload / settings_sync, `SWITCHES` = update_check / offline; `allowed(kind)` = row in `consent.json` with the current `TEXT_VERSIONS[kind]` AND `[privacy] <kind>` true AND not offline; `grant`/`withdraw` write the row atomically and mirror the key through `config.save(allow_consent=True)`, the one door — `config.save`/`set_values` refuse `config.CONSENT_KEYS` from anyone else, and the Settings page draws the six gates read-only (`Setting.consent`) with the grant date and a Withdraw button on a Privacy tab. Every cloud constructor's first statement is `privacy.require(kind)` raising a `ConsentRequired` that is also the module's own error class (translate, visual_qa, transcribers.gemini); `visual_qa.Chain._builders` lists cloud legs only while the gate is open (`allow_screenshot_upload` is gone — `--migrate` drops it); `net.py` asks again per request by purpose (`PURPOSE_KINDS`) and writes the consent tag into the row, so a withdrawal from the dashboard — another process — stops the next request without a restart; `privacy.on_change` resets the cached cloud legs of the punctuator, the lookup engine and the translator on grant AND withdraw (a leg cached as unavailable before the card must not outlive it). A shut cloud_audio gate with `backend = "gemini"` falls to the local transcriber with a warning, never a crash. The card (5b, same day): `consent_card.py` holds the words per kind — title, the five blocks, the footer, two buttons, Hebrew with the providers' sentences quoted in English — and `overlay.ConsentCard` shows it mid-right on the flat Tk face (no skin presenter yet), one kind at a time, the next waiting behind; `privacy.pressed()` marks a key press the person made and `privacy.set_asker` is the card's `show`, so a refusal INSIDE a press asks once per kind per process and a warm-up never does; main wraps the two text keys, the lookup key and the repair pass, `visual_qa.Chain.ask` asks when `prefer` names a cloud, and a `backend = "gemini"` start with the gate shut asks once the overlay is up; [Turn on] = `privacy.grant`, [Not now] = `privacy.not_now` (down until the next start). Terminal door as well: `main.py --consents / --consent KIND / --withdraw KIND`. Tests: `test_privacy_gate_refuses_every_cloud_constructor`, `test_screenshot_chain_follows_privacy_gate`, `test_settings_page_cannot_write_privacy_keys`, `test_consent_round_trip_and_withdraw_teardown`, `test_warmups_never_open_a_card`, `test_net_offline_refuses_all_but_loopback`.*

**D8 — Support-safe logs and a redactor.** `app.log` never quotes dictated text, learned pairs, the phone URL/token (`server.py:653-654` logs the host only); quoted text lives only in `transcripts.log`. A redactor for `#t=`, `AIza[0-9A-Za-z_-]{30,}`, `gsk_[0-9A-Za-z]{20,}`, `sk-…`, and any string equal to a stored secret runs on everything a report or `--diagnose` attaches. Evidence: `map/learning` rec 8, `map/core` risk 5, `map/phone` rec 3, `research/keys-privacy` §C.5. Revisit: never. *Implemented 2026-09-17 (PR 6): the five quoting sites keep the count only (`LEARNED` joins `transcripts.log`), `server.py` logs the phone host without the token (the link is on the dashboard's Phone page), `redact.py` holds the patterns (`[redacted:<kind>]` placeholders; `secretstore.scrub` does the stored-value comparison inside the store) and `problems.Store.add` walks every report through it; `[history] keep_days = 30` (`HistoryConfig`; `history.apply` prunes the log and its rotated siblings at start, 0 detaches the handler and the Recent view says so) with size rotation kept — a rewrite of the one file rather than the daily suffix, so `history.py` reads one file as before. **The checkout's own data is exempt** (`paths.OWNER_DATA` = DEVELOPER and FLAT): neither `history.apply` nor `--reset-data` (`migrate.TRAINING_DATA`) touches `transcripts.log`, `recent\` or `corpus\` there — a reset on 2026-09-17 removed 72 read-aloud clips nobody can re-record, and the owner's rule since is that his history is training data. `--diagnose` and the `[review] keep_audio` floor wait for their chapters.*

**D9 — "Your data" page and delete-means-delete.** Settings > Your data: one row per store (size, oldest item) with Forget a word (`Vocab.forget` + atomic save), Clear history, Delete recordings (recent/pending/corpus), Delete reports (purges wav/jpg, `remove(purge=True)`), Delete lookups, Delete the model, Export everything (zip), Delete everything on this PC (folder + Credential Manager entries + `HKCU\Run` value + hook entries), Delete my account (D17). Uninstaller asks "Remove my data too?" (default unticked) and names the folder. Evidence: `map/learning` rec 7, `map/owner` rec 5, `arch-A §3`, `arch-B §3`. Revisit: never.

### C. Cloud, keys and the proof

**D10 — Bring-your-own-key only; the owner's keys never ship.** Google's API ToS forbids embedding developer credentials; Groq limits are per organisation, so a shared key would pool every user into one bucket; "all-free" forbids a paid proxy. Each user is the API customer for their own key. The Keys page walks them to console.groq.com and aistudio.google.com; the guide recommends Groq first (one key unlocks repair, punctuation, lookup and the CPU user's cloud transcription) and Gemini only for translate/ask-the-screen. Evidence: `map/cloud` risk 5, `research/keys-privacy` (Google APIs ToS), `research/models` S7, `arch-B §4`. Rules out: any owner-run proxy or shared key. Revisit: only if the owner ever wants a paid hosted tier (out of scope).

**D11 — Provider notices quoted verbatim at paste time, with a checkbox.** Gemini: free-tier inputs are used "to provide, improve, and develop Google products", "human reviewers may read, annotate, and process your API input and output", "Do not submit sensitive, confidential, or personal information to the Unpaid Services", free tier not allowed for API clients in the EEA/UK/Switzerland, 18+. Groq: "not permitted to use Inputs or Outputs for training", no retention by default, 30-day abuse logs unless Zero Data Retention is on, 18+. Evidence: `research/keys-privacy`, `research/legal`. Revisit: on every provider terms change (the card carries a `text_version`).

**D12 — The key-privacy proof: five locks and a window.** (1) Storage lock — keys only in Credential Manager/DPAPI; a test runs every feature with fixture keys and greps the whole `DATA_DIR`, `settings.toml`, `state.json`, `problems.json`, `network.log`, `app.log` for key-shaped strings. (2) Egress lock — `net.py` is the only module allowed to import `urllib.request`/`http.client`/`httpx`/`requests`/`socket`/`ssl` (a static grep test enforces it, the repo already keeps grep-style tests at `visual_qa.py:173-175`); it holds a frozen `ALLOWED_HOSTS` (`generativelanguage.googleapis.com`, `api.groq.com`, `huggingface.co` + its CDN hosts, `pypi.org` + `files.pythonhosted.org`, `api.github.com` + `github.com` + `objects.githubusercontent.com`, `<ref>.supabase.co`, `127.0.0.1`); each call declares `purpose` and the secret's *name*; any other host raises before connecting; a second test drives every feature through a mock transport and asserts the Supabase host never receives a header or body containing the fixture keys, and that the Supabase module imports neither `apikey`/`secrets` nor `translate`. (3) Schema lock — the Supabase migration is published in the repo; no table has a column that could hold a key; free-text columns carry a CHECK rejecting key-shaped strings; RLS everywhere; only the publishable key ships. (4) Report lock — the report payload is built from the `problems.env()` whitelist, redacted (D8), and shown in a preview before Send; a test serialises a report with a populated fixture key and asserts none of it reaches the payload. (5) Build lock — GitHub Actions builds from the tag with `--require-hashes`, the python.org zip verified by SHA, `git archive`, `MANIFEST.sha256` attested with `actions/attest-build-provenance`; `deskit --verify` recomputes the manifest on disk. The window: Dashboard > Network, an append-only table of every outbound request (time, host, purpose, bytes, secret name, consent that authorised it) mirrored to `logs\network.log`; plus an Offline switch that refuses every host but loopback. The google-genai SDK is replaced by direct REST through `net.py` (it reads env keys on its own, hides its transport, and drags ~50 MB of deps); until then `base_url` is pinned and env pickup disabled. Evidence: `map/cloud` rec 5, `map/owner` rec 13, `map/capture` rec 5, `research/keys-privacy` recommendation, `research/supabase` PROOF, `arch-B §4`. Rules out: closed-source "we promise" wording. Revisit: never; the wording next to every key field is fixed in `arch-B §4` and the guide repeats it. *Lock 2 implemented 2026-09-17 as `net.py`: `open()`/`request()`/`post_json()` over `urllib` with redirects never followed, `ALLOWED_HOSTS` frozen (5.5 minus `api.cerebras.ai`; `SUPABASE_HOST` is `None` until phase 3 sets the ref, so no suffix rule), `PURPOSES` frozen (5.4's list plus `reading` for the read-aloud writer and `notify` for the Claude Code hook's knock on our own listener), `SECRET_HOSTS` binding each secret name to the one host and header it may travel in, any query parameter named `key`/`token`/... refused on every host, a caller's own bearer admitted for `127.0.0.1` only, and `offline` as a module flag PR 5 wires to the switch. One row per call — answered, failed or refused — in `net.rows()` and `paths.NETWORK_LOG` (eight fields, 1 MB × 3). The google-genai clients ride `net.genai_http_options()` — the SDK's httpx client on an httpx transport built in `net.py` with `base_url` pinned and `vertexai=False` — so their rows appear too; the SDK still holds the Gemini key value until the REST port. The Groq clients hold no key value any more (`del key` after the presence check; `net.py` attaches it by name). Tests live in `tests.py` until PR 8 splits the suite: `test_only_net_imports_transport`, `test_net_refuses_unlisted_host`, `test_net_never_puts_key_in_url`, `test_network_log_row_shape`, `test_plain_dictation_touches_only_loopback`. Not yet: the process-wide 429 cooldown table of 5.4, `net.download()`, `session_for_huggingface()`, the Network window itself.* *The REST port of 5.6 landed 2026-09-17 (PR 12): `gemini_pool.Client` — `generate(model, parts, system=, temperature=, thinking=)` as one `POST v1beta/models/<model>:generateContent` through `net.post_json(secret="gemini")`, `list_models()` as `GET v1beta/models`, `APIError` carrying Google's `error.message` and the parsed body (the shape `parse_429` already read), the thinking knob as JSON (`thinkingBudget: 0` / `thinkingLevel: "low"`) with the 400 rescue inside `generate`; `GeminiTranscriber`, `GeminiTranslator` and `GeminiVision` use it and `del` the key value after the presence check; `TooLongForCloud` is raised before the wire for a WAV whose base64 would pass the 20 MB inline cap and `main.py` decodes it locally with a card line; the SDK, its httpx bridge in `net.py` and `google-genai` in `requirements.txt` are gone (the lock drops from 50 to 34 pins; `httpx` stays only as huggingface-hub's dependency). Verified live with the owner's key from the worktree: one `generateContent` answered `OK`, the catalog listed 58 models, both as rows with the secret name and the consent tag. Tests: `test_gemini_rest_request_shape`, `test_gemini_inline_limit_refused_before_send`, `test_gemini_429_parsed_from_json_body`; the older pool tests now build `APIError` instead of the SDK's exception.*

### D. Hardware tiers and models

**D13 — One Hebrew model, downloaded at first run, never bundled.** `ivrit-ai/whisper-large-v3-turbo-ct2` (Apache-2.0, ungated, no token, 1.62 GB) via `snapshot_download(local_dir=DATA_DIR\models\…, revision=<pinned commit>, tqdm_class=<Tk bar>)`, `dry_run` first for the size line, resumable, size/hash-verified, never loads a partial snapshot, then `HF_HUB_OFFLINE=1` for the rest of the process life; "Delete and re-download" in Settings > Speed. The English detector (`deepdml/faster-whisper-large-v3-turbo-ct2`, +1.6 GB disk, +1.6 GB VRAM) becomes optional and is offered only on the GPU tier. Optional owner win: an int8 re-conversion (~0.8 GB) under the owner's Hugging Face account, Apache-2.0 with attribution, halves the CPU user's download. The model is never a GitHub Release asset (2 GiB cap, acceptable-use). Evidence: `research/models` S1/S6/S16, `map/core` rec 3 and risk 14, `research/competitors` (half-downloaded models are every competitor's top issue), `research/updates`. Revisit: if ivrit.ai publishes a smaller CPU-oriented Hebrew model. *PR 15 (2026-09-17): `models.py` + `models.lock` — the lock beside the code names both repos (`ivrit-ai/whisper-large-v3-turbo-ct2` @ `72ad623a`, Apache-2.0, 1.62 GB; the deepdml detector @ `4df90f75`, MIT) with every file's size and SHA-256, written by `python models.py --lock` from the Hub's metadata (LFS SHA-256 as the Hub records it, the small files hashed) and cross-checked against the owner's cached snapshot — all five files match. One departure from the text above, measured: `snapshot_download` is NOT used — huggingface_hub 1.27 writes each file to a per-process temp name and deletes it on any failure (`_download_to_tmp_and_move`, its PR #4228), so the resumable download the decision leans on no longer exists in the library; `models.download()` is the app's own, through `net.py`: `/resolve/` followed by hand (the Hub answers a 302 to `us.aws.cdn.hf.co` for the weights and a 307 with a RELATIVE Location for the small files; `net.ALLOWED_SUFFIXES` = Hugging Face's two domains, since the CDN hostname moves), `<name>.part` resumed with a Range (`206 Partial Content` checked live, a server that ignores it starts the file over), every file hashed, then `.complete` with the revision. `HF_HUB_OFFLINE=1` is therefore set for the WHOLE process on an installed copy, not only after `.complete`: the loader is given the folder and the library never needs the network. `source(repo)` hands WhisperModel the verified folder (installed) or the hub name (checkout, portable — D4 unchanged); a folder without `.complete` is `ModelMissing` (a TranscriptionError with `retry_after = inf`) and `get_transcriber` returns `transcribers/missing.py`'s stand-in so the app starts, keeps a dictation's recording in `pending\` and says why. The step is `models.offer()` — one window on ui.py, Hebrew paragraph through the bitmap path, [Download] / [Not now] / [Pause], the size line before any byte — shown by main before the wizard while the model is not ready, and by `--download-model`; the chapter 9 wizard hosts it later, and the Home / Speed cards of 6.9 are still to come. Live probe on the installed path: the three small files of the ivrit-ai repo (2.7 MB) paused after 256 kB, resumed with `bytes=262144-` → 206 with exactly the rest, verified, `.complete`; ten rows under `model-download`, all `huggingface.co`. The 1.6 GB weights were not downloaded in this session. Tests: `test_models_lock_is_the_shipped_list`, `test_models_state_and_source_on_an_installed_copy`, `test_models_portable_mode_untouched`, `test_models_env_is_set_on_an_installed_copy`, `test_models_download_resumes_verifies_and_marks_complete`, `test_models_verify_hashes`, `test_models_partial_never_loads`, `test_models_window_offers_downloads_and_closes`, `test_net_admits_the_hub_by_domain`.*

**D14 — Hardware tiers chosen at first run, re-checked at every start, shown on Home.** Probe: `ctranslate2.get_cuda_device_count()` + `nvidia-smi --query-gpu=memory.total,driver_version` (CREATE_NO_WINDOW; wrapper exists at `awake.py:642-646`). Tier 1 NVIDIA ≥ 6 GB with CUDA ≥ 12.3 driver: offer the **GPU pack** (`pip install --target DATA_DIR\packs\gpu nvidia-cublas-cu12 nvidia-cudnn-cu12`, ~1.3 GB from PyPI, versions pinned to the owner's venv; DLL dirs prepended to PATH before importing faster_whisper), float16, detector optional, second reading on. Tier 1b NVIDIA 4-6 GB: GPU pack, `int8_float16`, no detector. Tier 2 no NVIDIA / old driver / pack failed: CPU `int8`, `cpu_threads = cores`, `beam_size = 2`, rolling kept, detector off, second reading and study off, a live "transcribing…" state on the dot, honest copy ("about as long as you spoke — we measured N s for your test sentence"), and **Groq cloud transcription offered as an opt-in** under the audio consent card (user's own key; `whisper-large-v3-turbo`, 20 RPM / 2,000 req/day / 8 h audio/day). Tier 3 AMD/Intel via whisper.cpp Vulkan: phase 5, after a Hebrew WER check. CUDA failure falls to CPU **with a visible card**, never silently. Ollama: detect-and-prompt only (`GET 127.0.0.1:11434`), never bundled; tier-appropriate model suggestions (`gemma3:4b` on 8 GB cards, none on CPU) replace the owner's `gemma3:12b` defaults and 10 s deadlines; without Ollama the local-LLM menu entries are hidden and ask-the-screen shows the three-button card (install Ollama / use my key / turn this key off). Hebrew TTS probed once; forced off with a link to Windows speech settings when no `he-IL` voice exists. Evidence: `map/core` rec 4, `map/cloud` rec 8, `map/capture` recs 4 and 8, `research/models` S7/S8/S13/S14/S18, `arch-A §5`, `arch-B §5`. Revisit: after phase-0 measurement of CPU latency on a real laptop (decides whether tier 2 copy says "usable" or "cloud recommended"). *PR 14 (2026-09-17): `hardware.py` — `probe()` (ctranslate2's CUDA count, `nvidia-smi` for VRAM and driver with the 545.84 floor, cores, `GlobalMemoryStatusEx`, the GPU pack's standing — `venv` in the checkout, `missing` until packs.py) decides the tier in ~0.3 s before any model loads; `probe_slow()` (Ollama + its models through net.py, the he-IL voice through one hidden PowerShell) on a thread; both land under `hardware.*` in state.json (`config.STATE_PREFIXES`). `apply(tier)` writes 6.3's derived defaults through `config.save(derived=True)` into the machine layer — only keys settings.toml does not set, and a key the person later writes to settings leaves state in the same save, so the top layer never hides theirs; a changed tier clears the old tier's keys first. `[local] compute_type` (auto | float16 | int8_float16 | int8) and `cpu_threads` are new keys the ladder honours. Two departures from the table: the cpu tier switches the repair pass off with `polish.when = "never"` (config refuses `max_wait_s = 0`) and keeps the small Ollama model names rather than blanking them (config refuses an empty one). The checkout records the facts and applies nothing (D34). `problems.env()` carries `gpu` and `tier`. Measured on the owner's machine: RTX 16 GB, driver 596.49, 12 cores, tier gpu, probe 0.30 s, the slow half 0.44 s with 12 Ollama models and Microsoft Asaf. Still to come from chapter 6: `models.py` (the download with `models.lock`, `.complete`, `HF_HUB_OFFLINE`), `packs.py` (gpu / recording / skin), the wizard's hardware and download steps, Settings > Speed, the Ollama three-button card, the 6.9 cards. Tests: `test_hardware_probe_no_nvidia`, `test_hardware_probe_small_card`, `test_hardware_probe_old_driver`, `test_the_probe_writes_the_machine_layer_and_a_choice_beats_it`, `test_the_ladder_honours_the_number_format`.* *PR 16 (2026-09-17): `packs.py` + `packs.lock` + `steps.py`. Two packs, not three: `gpu` = cuBLAS 12.9.2.10 + cuDNN 9.24.0.43 + NVRTC 12.9.86 (1.37 GB; NVRTC is cuDNN 9's own dependency in the owner's venv, so it ships with the pack rather than being left to chance), `skin` = skia-python 144.0.post2 (11 MB); `recording` does not exist because PyAV arrives with faster-whisper in the base lock. The lock is written by `python packs.py --lock` from `importlib.metadata` (the versions this venv runs, D34) and PyPI's JSON through net.py, and carries the licence links (NVIDIA CUDA EULA, cuDNN SLA, skia-python BSD-3) the card shows. Open point 1 of chapter 6 is closed the strict way: the wheels come down through `net.download()` (a row per file under `pack-install`, resumed from a part, hashed) and pip runs `--no-index --find-links <wheels> --target <site> --require-hashes --no-deps` — every outbound byte passes the chokepoint, pip included; `NETWORK.md` need not list pip as a second transport. The failure of 6.5 step 4 is recorded as `hardware.gpu_pack_failed` in state.json by the ladder (only when the pack is there) and shows in `standing()` as `failed:<first line>`, which `tier_for` reads as cpu; a `stale` pack still runs and is offered as an update. The step is offered at start right after the model's, on a card with a driver above the floor, until `[setup] offer_gpu_pack = false` ([Not now]); installed, the probe runs again in the same start so the tier is the card's before any model loads. `steps.StepWindow` is the one window both steps use (the model's `Offer` is now a thin subclass); `net.download()` is the one resumable fetch (moved out of models.py). Live: the skin pack on the installed path — 11 MB through net.py (one row), pip offline into the pack in 3.4 s, `import skia` from the pack in a fresh `-S` interpreter. The GPU pack was not downloaded. Tests: `test_packs_lock_is_the_shipped_list`, `test_packs_pip_command`, `test_packs_install_downloads_through_net_then_pip_offline`, `test_packs_lock_mismatch_is_stale`, `test_packs_wanted_and_decline`, `test_packs_failed_falls_to_cpu_with_card`, `test_the_step_window_says_declined_before_it_starts`.*

### E. Owner-only machinery

**D15 — What each owner feature becomes.** Notify door → optional "Connect Claude Code" in Settings, off by default, installs the hook with the installed `pythonw` path, shows the two entries it wrote, uninstaller removes them (`--uninstall-hook`); `notify_watch` ships `watch = "off"` and never copies the OS toast DB unless a `Claude_*` package exists; `notify.log` rotates at 512 KB; `notify.json` bodies never attach to reports. Problems → "Report a problem" v2 (D16). Questions + Saturday routine → do not ship; the routine stays owner-side and reads `problems\inbox\<user_id>\` filled by `dev/inbox.py` from consented columns only; replies flow back as `report_replies` rows and appear on the user's report as the existing "fixed?" mark. Nightly tests, `install_nightly_task.ps1`, `[tests]`, Stop-tests button → do not ship; `tests.py` split into product tests and `dev/` ops tests (`tests.py:25281`, `28490-28510`). Awake → `hold = false` asked once at first run, `vitals_minutes = 0`, `pin_timeouts` under Advanced with "changes the Windows power plan; restored on exit", the `claude.exe` probe removed. Git card (Push/Undo/branch/`push.log`) → removed from the product; Restart stays. `versions.py` → `version.py` reading `VERSION` (branch only when `.git` exists); `problems.env()` stamps `version`, `os_build`, `gpu`, `tier`, drops `branch` and `python`. Dev-only files excluded from the build via a manifest: `weekly_review.ps1`, `.claude/`, `questions.py`, `nightly*.py/.ps1`, `install_nightly_task.ps1`, `tests*.py`, `make_icon.py`, `audio_check.py`, `install_fonts.py`, `android/` (source), `AGENTS.md`, `*_PLAN.md`, `SKIN.md`, `*.html`, `.agents/`, `vocab.json.bak-*`. Evidence: `map/owner` recs 1-12, `map/ui` "Owner-only", `map/packaging` rec 8, `arch-B §6`. Revisit: never. *Amended by D33: door and Snipping key also asked in the wizard; no replies back to the user.* *PR 7 (2026-09-17): the owner-only surface is behind `paths.DEVELOPER` — the Corrections screen's Read-aloud tab (`dashboard.corr_tabs`), the Saturday routine's questions (`_pending_questions` answers `[]`), `problems.md` and its button, the git changes block, the nightly run's Stop button (`_nightly_running` answers False); `settings.read` drops the `[tests]` section and the `awake.vitals_minutes`, `notify.watch`, `study.read_*` rows on a stranger's copy (`settings.developer_only`); `main.py --benchmark/--study/--review` refuse outside the checkout. The files and sections stay in `defaults.toml` so the checkout keeps working; the branch line on the dashboard waits for PR 9. Test: `test_a_strangers_copy_shows_no_owner_surface`.* *PR 8 (2026-09-17): the suite is split — `tests.py` stays the product suite and `dev/tests_ops.py` holds the twenty tests that import `nightly`, drive the Push/Undo card or read AGENTS.md / the nightly scripts (moved verbatim; they import `tests.py`'s fixtures and run only where `paths.DEVELOPER`). `NEEDS_SCREEN` lives in `tests.py` now, with `tests.py --no-screen`; `tests_quiet.py` reads it with `ast` and runs both files on the hidden desktop. `dashboard.py` and `main.py` no longer import `nightly`/`questions` at the top (`_nightly()`, `_questions_mod()`, called only on the owner's paths). `.github/workflows/ci.yml` runs `tests.py --no-screen` on `windows-latest`, `DESKIT_PORTABLE=1`, no `DESKIT_HOME` (the checkout is the data folder, as the suite assumes; a runner has no profile to protect); its first run is not yet observed. Not done here, deliberately: `tests_quiet.py` stays in the root — his daily command, `nightly.py`'s spawn and AGENTS.md all name it, so it moves to `dev/` with the nightly scripts in D28's hand-work batch; the `tests_privacy.py`/`tests_layout.py`/`tests_build.py` modules of chapter 15 are not created (one product file is his habit); five product tests whose last lines assert AGENTS.md documents a rule stay in `tests.py` until CI runs from the archive tree (PR 10). Tests: `test_product_suite_imports_no_dev_modules` (static top-level imports of every product module, every import of `tests.py`, plus a fresh interpreter importing all 74 with `tests.DEV_MODULES` blocked), `test_needs_screen_list_is_complete` (every name is a test; every ask-card window script is listed — the two that fit no pattern are the runner's own finding).*

**D16 — "Report a problem" v2.** One line + kind chips (same card, `problem_card.py` is headless-testable); attachment toggles with byte sizes — Screenshot (monitor under the mouse, not all screens; default ON for the local copy, OFF for upload), Recording (OFF), Transcript text (ON when kind = wrong), Settings snapshot (whitelist, redacted); one checkbox "Send to the developer" (OFF = stays on this PC); a Preview window with the exact JSON and each attachment; [Send] [Keep on this PC]. Sent reports queue in `problems\outbox\` and upload through the user's Supabase session (D17); `developer_status`/replies sync back; Fixed/Reopen writes back. `problems.md` digest and "Open problems.md" removed. Evidence: `map/owner` recs 4-6, `map/ui` rec 7, `map/capture` rec 6, `research/competitors` rec 6, `arch-B §6, §8`. Revisit: never. *Amended by D33: `developer_status`/replies dropped.*

### F. Supabase

**D17 — Supabase, narrow scope, anonymous by default, zero cost.** Purpose: an account row so reports and replies have an owner (anonymous sign-in, no e-mail); problem reports the user chose to send + a reply channel; opt-in sync (phase 5) of `settings.toml` overrides and `vocab.json` only — never `recent\`, `corpus\`, `review.json`, `transcripts.log`. No telemetry table; the update check goes to GitHub, so a user without an account never contacts the project host. Tables (all RLS `to authenticated`, `(select auth.uid()) = user_id`, anon grants revoked): `profiles`, `devices`, `settings_sync`, `vocab_sync`, `problem_reports` (`text` ≤ 600 chars, `dictation_raw/final` nullable, `env` whitelisted jsonb, `attachments`, `status`), `report_replies` (written only by the owner's script with the secret key), `deletion_requests` via a `security definer` RPC `delete_me()` that removes storage objects, rows and the auth user. Storage: private bucket `reports`, path `<user_id>/<report_id>/<file>`, 5 MB/file, MIME allowlist (`image/jpeg`, `application/json`, `text/plain`, `audio/wav` only when ticked). Auth: anonymous sign-in on first Send/Sync (Cloudflare Turnstile on); link an e-mail later with email + 6-digit OTP (needs custom SMTP — Resend free + a domain, phase 5); Google PKCE with a localhost listener is a phase-5 nicety; session in a DPAPI file, one process holds it. Keys: only `sb_publishable_` ships (legacy `anon`/`service_role` retire end-2026); `sb_secret_` lives only in the owner's password manager. Pause: Free projects pause after 7 idle days → a weekly GitHub Actions cron pings one REST endpoint; a paused project means "reports queued in outbox, will retry", never a user-facing error. Backups: none on Free → monthly `pg_dump` by the owner. Retention: reports and attachments 12 months, idle anonymous accounts 12 months (owner script). Region `eu-central-1` (Frankfurt), disclosed. Owner reads reports in Studio (MFA on) or via `dev/inbox.py`. Evidence: `research/supabase` (pricing, api-keys, sessions, storage, pausing), `map/learning` rec 9, `map/owner` recs 4/7/13, `arch-B §7`. Rules out: Realtime as a phone relay (D22); any column for keys; auto-upload. Revisit: anonymous sign-in + Turnstile availability on Free must be verified in phase 0 (fallback: e-mail OTP from day one, which needs the domain earlier). *Amended by D33: no `report_replies` table.*

**D31 — Account-backed sync: a signed-in user sees the same vocabulary, settings and history on every PC.** Added 2026-09-17 on the owner's ask; amends D17's sync scope and schedule. Clarification recorded with it: the ASR model is universal and learns nothing per person; what is personal is the vocabulary (names/terms and the learned corrections, fed to the decoder as hotwords and to the repair pass as a glossary), the settings overrides, and the history (the text of what was dictated). Architecture: local-first with sync — the files in `DATA_DIR` stay the working copy so dictation never waits on the network; a signed-in app pushes its changes and pulls the others' on start, on a timer and after each dictation, through `net.py` (D12) to the Supabase host only. What syncs (text, small): `vocab.json` entries (table `vocab_sync` becomes per-entry rows keyed by `heard`, merged as a union with the higher `hits`), `settings.toml` overrides (last-writer-wins by `updated_at`; keys flagged machine-bound in the settings schema — devices, folders, ports, positions — never leave the PC), `transcripts.log` events as append-only rows in a new `history` table (`user_id`, `device_id`, `ts`, `kind`, `text`, `raw`; unique on `(device_id, ts)`; the Said page reads the merged set), and `review.json` verdicts (accept/reject only, so a second PC does not re-ask). What never syncs: audio (`audio\recent\`, `audio\pending\`, `corpus\`), screenshots and clips, keys (D3, D12 — the schema still has no column for one), `state.json`, `lookup_cache.json`, notify bodies. Identity: **Sign in with Google** (Supabase PKCE with a localhost listener) becomes the primary account method — free, needs only a Google Cloud OAuth client, no domain and no SMTP; anonymous sign-in stays for report-only users and can be linked to a Google identity later; e-mail OTP stays in phase 5 (needs the domain). Consent: two gates, `[privacy] settings_sync` (vocabulary + settings) and a new `[privacy] history_sync`, each with its own consent card, both default off; the history card says plainly that everything dictated will be stored in the user's account on the developer's Supabase project, readable on any PC they sign into, and that the developer can technically read it too (RLS protects users from each other, not from the project admin) — see the policy. "Delete my account" removes it all through the D17 RPC; a "Delete synced history older than N days" control mirrors the local `[history] keep_days`. Size: ~200 bytes per dictation × 100 dictations/day ≈ 7 MB per heavy user per year, so the 500 MB Free database holds dozens of heavy users for years; monitored monthly (D17). Privacy tier: the database now holds dictated text for consenting users — the policy (D25) names `history`, and the PPL database-definition document lists it; anonymous users still hold nothing sensitive. Deferred: end-to-end encryption with a client-side key (so the developer cannot read history) — it would make sign-in on a new PC need a passphrase or a device-to-device handoff; revisit after launch if users ask. Schedule: sync and Google sign-in move from phase 5 into phase 3, together with the account (D27). Reason: the owner wants a person to sign in from any PC that has the app and find their own words and history. Evidence: `research/supabase` (Google PKCE with a localhost redirect, RLS patterns, Free limits), `map/learning` rec 9 (what is worth syncing and what is not), D17. Rules out: cloud-first (dictation blocked by the network); syncing audio; any key column. Revisit: E2E encryption; per-entry conflict rules if two PCs learn different corrections for the same word.

**D32 — Two amendments from the first implementation day (2026-09-17).** (a) *The Settings page keeps every line reachable, coordinates included, behind the fold.* D2/chapter 3.4 wanted the page to show no coordinates; the owner's earlier rules — "show all of them" (2026-09-01) and "I do not need to know all of this" (2026-09-07), held by `test_the_general_page_holds_the_two_corners_and_the_button_together` and `test_the_two_screens_cover_the_whole_file_between_them` — say every line of the file is reachable exactly once, folded. The state keys therefore stay on the page (folded) and are ROUTED to `state.json` by `config.save` (`STATE_KEYS`), which is the part that matters for sync (D31) and for updates. Revisit with chapter 9's screens. (b) *The owner's own cutover keeps only his settings.* His words: keep the settings, delete the history, start like a new user. So `--migrate` writes `settings.toml` + `state.json` from his `config.toml` (6 overrides, 10 state values, 3 retired keys, measured on his live file) and `--reset-data --yes` removes vocabulary, history, recordings, proposals, reports, caches and logs while keeping the two files, the marker and the keys. Both commands refuse while the app runs. Also recorded: `--migrate <folder>` COPIES an old checkout's stores into `DATA_DIR` (never moves; D30), and `defaults.toml` is the tracked name of the old `config.toml` from this day on — the app never writes it, `settings.toml` holds only what differs from it, and the line editor survives solely for `--config <one file>` runs (tests, a one-file portable copy). (c) *Read-aloud and trolls.* Readings are local to the reader's PC and change nothing for anyone else; each reading already carries a match score against the sentence and a non-match is refused, so a troll harms only his own corpus. If a shared corpus is ever collected (phase 5+, opt-in), the match score is the first filter, then a daily cap per user and spot checks. Evidence: reading.py:596-604 (`heard`, `match`), D6 (corpus off by default).

**D33 — The owner's verdicts of 2026-09-17 evening: the feature table, three first-run switches, no reply channel, the routine's mandate, the reset's edge.** (a) *The feature table (D15) is approved with three moves into the first-run wizard.* Saturday routine, nightly tests and the git card do not ship; Report v2 ships. The notify door ("Connect Claude Code"), keep-awake and the Snipping-Tool key (Win+Shift+S) are each asked ONCE in the wizard's "Optional extras" step (D18-1), off unless the person turns them on, and each stays a switch in Settings afterwards (Claude Code / Advanced / Screen): the wizard is where they first decide, Settings is where they change their mind. Keep-awake was already there; the door and the key join it, so the step has five switches. (b) *No reply channel.* The `report_replies` table and RPC (D17), `developer_status` on the user's report (D16), the "Fixed?" mark on a stranger's report and the "Report replies row on Problems" screen (D18-8) are dropped. A person who sent a report learns whether it was fixed only by using the app after an update. `dev/inbox.py` still pulls consented reports into `problems\inbox\<user_id>\`. (c) *The routine's mandate.* Reports → Supabase → the owner's inbox → the Saturday routine goes over every report: what it can check, it checks against the current tree (fixed / still broken / false alarm), and a still-broken one it tries to fix itself; what it cannot check, it summarises. Its written output to the owner holds ONLY what is still open: (1) a bug verified still present that it could not fix, or whose fix needs his approval; (2) a report it could not check. Fixed ones and false alarms do not appear at all. For every fix it did make: one short line saying what it did and one saying how to check it by hand ("fixed the mic during screen recording — record the screen with the mic unmuted and listen to the file"). The routine runs in DeskIT Dev (the checkout, its own branch), never in the released DeskIT copy (D30). (d) *The reset spares the owner's tool journals.* `--reset-data` empties `problems\` around `weekly\` (the routine's journal) and `nightly\` (the test logs) — `migrate.OWNER_PROBLEM_DIRS` — and removes `vocab.json.bak-*` together with the vocabulary. Evidence: the owner's words in the 2026-09-17 session; `migrate.reset_targets`; `test_migrate_writes_the_two_files_and_retires_the_old_one`. Rules out: any write from the owner's side into a user's account. Revisit: (b) if users ask how their report went — a read-only status column would be the smallest answer.

**D34 — The owner's verdicts of 2026-09-17 night: the defaults are what he runs, and both copies are reset only once the separation is finished.** (a) *Defaults.* The shipped `defaults.toml` should be the settings he actually runs. After PR 2's scrub that is already true except for what is personal: his three capture folders, his `vocab.terms`, `server.enabled` (the phone switch — the wizard's phone step asks it) and `privacy.cloud_text` (a consent, never a default). The one override a stranger can use, `punctuate_hotkey = "ctrl+f2"`, is the default now. (b) *The reset.* Both copies on his machine — the checkout ("DeskIT Dev") and the released "DeskIT" — are reset to a fresh state only after the whole separation is done and phase 2's wizard exists, so that he goes through the wizard as a stranger would, re-enters his personal values there and in Settings, and judges the first run. The reset keeps the training data on his checkout (`paths.OWNER_DATA`, the 2026-09-17 rule): `transcripts.log`, `recent\`, `corpus\` are never part of it. (c) *Keys.* New keys are created and entered in the wizard at that reset; the old Gemini and Groq keys are revoked at the providers the same day, and in any case before the repository is made public (they are in its history, D28). (d) *The wizard's shape* is to be informed by what comparable apps do on first run (his ask: look at how other apps of this kind onboard), within D18's screens. Evidence: his message of 2026-09-17 night after the PR 8 merge. Rules out: folding a personal path or a consent into `defaults.toml`. Revisit: (a) if the punctuate key collides on other machines.

### G. Screens

**D18 — Screens to add or change (chrome English; Hebrew body text through the existing bitmap path; installer and guide Hebrew-first).** (1) First-run wizard rewritten: Welcome (three privacy sentences + "how to check this yourself") → Microphone (system default pre-selected, live meter, privacy-switch hint) → Hardware and model (probe result, 1.62 GB download consent with source/destination/progress, optional GPU pack, optional English detector) → Say one sentence (reports the measured time) → Keys (hotkeys) → Optional extras (three switches: cloud repair, keep awake, weekly update check) → Done; at most four real decisions; writes `setup_done` to `state.json`. (2) Consent cards, one layout per gate: what leaves, to whom, under whose account, the provider sentence (D11), how to turn it off, [Turn on] [Not now]. (3) Keys page: Groq/Gemini masked paste, Test, Remove, the storage sentence, the notice, the daily quota meter; no Cerebras. (4) Settings > Privacy: the gates with consent date/text version, Offline mode, retention pickers, clipboard caveat. (5) Settings > Your data (D9). (6) Dashboard > Network (D12 window). (7) Report a problem v2 + Preview (D16). (8) Report replies row on Problems. (9) Settings > Phone: transport Off / Home Wi-Fi / Tailscale, pairing QR, APK link QR, paired phones with Forget/Rotate, firewall note, token hidden unless Reveal. (10) Hardware card on Home (active tier). (11) Update available card (version, size, SHA-256, Download and install / Release notes / Skip). (12) Ask-the-screen first press without Ollama (three buttons). (13) Snipping Tool toggle in Settings > Screen + `ms-screenclip` handler route. (14) About: version, tier, licence, third-party notices, Verify this install, links, "Built with Llama" while a Llama is the default repair model, ivrit.ai attribution. (15) CPU-slowness card the first time a decode exceeds 10 s. (16) Account (inside Privacy or Your data): anonymous id, Link an e-mail (phase 5), Delete my account. Evidence: `arch-A §1 P2`, `arch-B §8`, `map/ui` rec 6, `map/capture` recs 3-4. Revisit: after the first usability session with a non-technical tester. *Amended by D33: (1) gains the Connect-Claude-Code and Snipping-key switches; (8) dropped.*

### H. Packaging, channels, signing, updates, versions

**D19 — Embeddable CPython 3.11 + vendored wheelhouse; never freeze.** `python\` = python.org embeddable zip (SHA-verified) + tcl/tk tree copied from a full 3.11 install + `python311._pth` enabling `Lib\site-packages`; `app\` = the real `.py` tree from `git archive`; shortcut target `python\pythonw.exe app\deskit.pyw`; no custom exe in the GitHub build (the Store MSIX gets a 30-line open-source launcher stub because a manifest needs an executable). Reason: stock python.org binaries carry Defender reputation while PyInstaller's shared bootloader hash is the worst false-positive magnet; CUDA DLL paths become deterministic; the tree is reproducible file-by-file (part of D12 lock 5); field diagnosis with real source. Base wheelhouse ≈ 350-410 MB (CPU set: `pillow` and `comtypes` added, `keyboard` package dropped and the local `keyboard.py` renamed `keycaps.py`, `google-genai` gone after D12, `av` and `nvidia-*` moved to packs, `skia-python` an optional Skin pack). Evidence: `research/packaging` S1/S2/S14/S22 and recommendation, `map/packaging` pip table and recs 6/11, `arch-A §1`, `arch-B §1`. Rules out: PyInstaller/Nuitka/cx_Freeze in v1; MSIX outside the Store (needs a cert). Revisit: only if phase-0 VirusTotal scan of the embeddable build is worse than expected. *PR 10 (2026-09-17): the build's inputs are in the repo — `requirements.txt` as the base set (pillow, comtypes and pip named; the CUDA runtimes, skia and the keyboard package gone; google-genai and httpx stay until the REST port), `requirements.lock` from `pip-compile --generate-hashes --allow-unsafe` constrained to the owner's tested venv versions (50 pins, every one hashed), `packaging/python311._pth` (five lines — `Lib` too, because tkinter is copied there; the plan's four forgot it), `packaging/python-embed.sha256` for 3.11.9 (the digest taken from python.org's own Sigstore bundle, not from a download here), `.gitattributes` with `export-ignore` as the ONE exclusion list (7.4's `build/exclude.txt` is not a second file), `manifest.py` at the root (writer + reader of `MANIFEST.sha256`, stdlib only, ships in `app\` so `--verify` can read it later), `.github/workflows/release.yml` with steps 0-7 of 10.3 plus a dry-run dispatch that keeps `app\` and the manifest as an artifact, and `packaging/build_local.ps1` for the same seven steps on the owner's PC into `dist\`. `keyboard.py` is `keycaps.py`. Neither the workflow nor the rehearsal has been run yet: the rehearsal downloads the wheelhouse (~300 MB) and the python.org zip, which is the owner's phase-0 VirusTotal probe to start. Tests: `test_requirements_base_set`, `test_lock_has_hashes`, `test_pth_lines`, `test_embed_sha_pinned`, `test_manifest_roundtrip` (tests.py); `test_export_ignore_covers_forbidden` (dev/tests_ops.py, archives the working copy).*

**D20 — Two channels from one tree; the Store is the door for non-technical users, GitHub + winget is day-1 and for power users.** Phase 2 ships `DeskIT-Setup-x.y.z.exe` (Inno Setup 6, `PrivilegesRequired=lowest`, per-user into `%LOCALAPPDATA%\Programs\DeskIT`, no admin, `CloseApplications=yes`, Hebrew + English installer pages) on GitHub Releases with SHA-256, build attestation and a VirusTotal link, plus a winget manifest (`wingetcreate`, silent `/VERYSILENT`; winget installs skip the SmartScreen download dialog). Phase 3 submits the same tree as an MSIX to the Microsoft Store under a free individual account (ID + selfie; runFullTrust justification: global push-to-talk hook, screen capture keys, local listener for the phone), because the Store is the only zero-cost route with no SmartScreen warning at all and the only one that survives Smart App Control; once live, the Store link becomes the public "Get DeskIT" button and GitHub stays as fallback. Signing: no free path exists for an Israeli individual (Azure Artifact Signing individuals are US/Canada only; OV certs USD 150-500/yr); with Apache-2.0 apply to SignPath Foundation (free OV signing for OSS, CI-built) in phase 5; fallback Certum OSS EUR 49. Until signed: the guide's SmartScreen screenshot ("More info → Run anyway"), stable file names, the FAQ, the false-positive submission link. Evidence: `research/signing` sources 2/4/6/7/8, `research/packaging` S19-S20, `research/competitors` (Handy/Vibe patterns), `arch-A §1 P1/T2`, `arch-B §1 T2, §9`. Rules out: paid certificates before user numbers justify them; Velopack. Revisit: if the Store rejects a full-trust MSIX with a global hook (then GitHub + winget stays primary and the SignPath application moves up). *PR 11 (2026-09-17): `packaging/DeskIT.iss` written to 10.4 — per-user, `x64compatible`, `MinVersion=10.0.17763`, Restart Manager, `lzma2/ultra64`, English + Hebrew with `ShowLanguageDialog=auto`, one `[Icons]` entry with `AppUserModelID: "DeskIT.App"`, no `[Registry]`, `[Code]` for `/CHANNEL=` (written to `{app}\CHANNEL`), `/NOLAUNCH`, a downgrade refused by name from the uninstall key's `DisplayVersion`, and the uninstall question (Keep the default, `--reset-data --yes` on Delete, the Run value removed either way). `deskit.pyw` is the entry; `paths.CHANNEL` reads the word beside `app\`; `launch.pythonw()` prefers `python\` beside `app\` and `launch.dashboard_command()` gives the pin and Restart one command per layout; `autostart.py` + `setup.autostart` (a state key, a row under "AT STARTUP") is "Start with Windows", re-asserted by `main.py` at start and inert in the checkout. `release.yml` gains steps 9-12 (CHANNEL, ISCC from the runner image, `.sha256` + `latest.json`, a silent install → `manifest.py verify` → silent uninstall on the runner). The script has not been compiled yet — Inno Setup is not on the owner's PC and the stage is not built; the workflow's first tag run is where it is proven. The `.vbs` launchers stay in the repo for the checkout (export-ignored). Tests: `test_iss_settings`, `test_channel_values`, `test_autostart_run_value` (a scratch registry key), `test_deskit_pyw_is_the_entry_and_the_window_is_relaunched_by_layout`.*

**D21 — Updates: verified one-click, no self-patching binary.** GitHub build: weekly `GET api.github.com/repos/<org>/DeskIT/releases/latest` (consent-gated, no identifier); the release carries `latest.json` `{version, url, sha256, size, min_config_version, notes_url}`; the Update card downloads on click, verifies SHA-256, runs `Setup.exe /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`; `DATA_DIR` untouched; `settings.toml.bak` kept; rollback = the previous installer linked in the release notes. winget users `winget upgrade`; Store users get Store auto-update. Beta = GitHub pre-releases behind a `[updates] channel = "stable" | "beta"` setting. Versions: SemVer `MAJOR.MINOR.PATCH[-beta.N]` in one `VERSION` file shared with the Android build (`versionCode = MAJOR*10000 + MINOR*100 + PATCH`, three numbers as the owner already decided), Windows 4-part file version, `config_version` for migrations, `/api/version` on the PC returns `{pc, imeMin, imeLatest, apkUrl, playUrl}`. Evidence: `research/updates` (Inno CloseApplications, GitHub Releases limits), `research/competitors` rec 5, `research/android` source 8, `arch-A §1 T3`, `arch-B §9`. Rules out: Velopack/Squirrel/`Update.exe` in v1 (an unsigned self-updater is the highest-privilege path in the app). Revisit: Velopack if GitHub-channel users turn out to be the majority and signing exists. *PR 9 (2026-09-17): `VERSION` = `1.1.0` (the phone's number, carried over) and `version.py` (`VERSION`, `PARTS`, `IS_BETA`, `BRANCH` — git only when `paths.DEVELOPER`, "" elsewhere, `parse`/`key` with beta-before-release precedence, `label()`), read from `paths.VERSION_FILE`; `versions.py` deleted. `problems.env()` = `version`, `os_build`, `consents` (open gates with their text version) always, `branch` only in the checkout, no `python`; `gpu`/`tier`/`config_version` join with chapter 6 and 11.10. The dashboard's foot says `DeskIT 1.1.0` (plus `running <branch>` in the checkout) and About says `version 1.1.0`; the branch warm-up thread is gone. `server.apk_version()` is `version.VERSION`; `consent.json` rows carry the real `app_version`. `android/app/build.gradle.kts` reads `../VERSION` and derives `versionCode` (10100 for 1.1.0, above the hand-typed 12). Tests: `test_version_file_is_single_source`, `test_version_no_git_on_user_machine`, `test_problems_env_fields`.* *PR 13 (2026-09-17): `updates.py` — `check()` (GET `api.github.com/repos/massifapp/DeskIT/releases/latest`, or the newest pre-release on `[updates] channel = "beta"`, then the release's `latest.json` behind its redirect, each hop admitted by `net.py` in turn; the GitHub Accept header, no query string, no identifier; `Release.parse` refuses a wrong field; a version at or below the running one is stamped in `updates.latest_seen` and hidden; `updates.skipped` hides one and a higher version un-skips; every failure one debug line), `due()` (7 days from `updates.last_check`), `mode()` (store → no check, switch off, Offline, winget → the `winget upgrade YoavShimron.DeskIT` one-liner instead of a download), `download()` (into `tmp\...part`, hashed as it streams through the redirect, renamed only on a match; a mismatch is deleted, both digests logged, the card told), `install()` (`settings.toml.bak`, exactly `/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /NORESTART /LOG="<logs>\setup-<v>.log"`, detached, then the app's own quit; the checkout refuses), `after_update()` (one toast on the first start after), `start_worker()` (10 min after start, then weekly; not in the checkout). `main.py` registers with `RegisterApplicationRestart` when installed. The dashboard's The app card has the row: the status line, Check now, and with a newer version Download and install / Release notes / Skip this version (Copy the winget command on winget). The overlay card of D18 screen 11 and the `config_version` migrations of 11.10 are still to come. Verified live: the check against the repository answers 404 (no release yet) and is recorded as a check, one row in network.log. Tests: `test_latest_json_schema`, `test_update_check_cadence`, `test_update_check_respects_gate`, `test_update_check_request_shape`, `test_update_download_sha_match_runs_inno`, `test_update_download_sha_mismatch_discards`, `test_inno_script_never_names_data_dir`, `test_the_app_tab_carries_the_updates_row`.*

### I. Android

**D22 — Phone pairing on the user's own Wi-Fi; Tailscale optional; no relay.** The PC generates a self-signed cert on first phone setup (`phone\cert.pem`, key DPAPI-wrapped); its SHA-256 fingerprint is the PC's identity; the pairing QR carries `deskit://pair?host=…&port=…&fp=<sha256>&token=<one-time>`; the IME pins the fingerprint with a custom trust manager (network-security-config XML cannot pin a per-user cert), exchanges the one-time token for a per-phone bearer in `EncryptedSharedPreferences`, then speaks HTTPS to the pinned cert; discovery via `NsdManager` with `FLAG_SHOW_PICKER` (survives the Android 17 local-network permission), QR as fallback; Windows Firewall prompt once, documented. Tailscale stays the documented "away from home" path (same pairing over the tailnet IP). Route hygiene: `/health` → `{ok, version}`; `/app.apk` removed from the PC (APK is a GitHub Release asset, later Play); `GET /review` scoped to `source == "phone"`; the Hebrew web page `/` retired; per-phone tokens; "Forget this PC" on the phone. Identity: `applicationId` → `io.github.massifapp.deskit` decided before the first outside install (cannot change later); `DEFAULT_URL` (`Prefs.kt:25`, the owner's tailnet) deleted; release keystore generated once and backed up. Delivery: v1 = release-signed universal APK on GitHub Releases (targetSdk 36, `debuggable=false`), QR from the PC's Phone page; phase 4 = Google Play personal account (US$25 once, ID + card in legal name, 12 testers × 14 days closed test; the registration also satisfies Android developer verification for sideloading before the 2027 enforcement); Data safety: audio "collected, optional, ephemeral, encrypted in transit, not shared" + privacy policy URL; IzzyOnDroid once Apache-2.0 + Fastlane metadata. Evidence: `map/phone` recs 1-11 and risks 1-8, `research/android` sources 1/2/4/6/9/10/12, `arch-B §10`. Rules out: Supabase Realtime / Cloudflare tunnel relays (audio would transit owner infrastructure; Free caps). Revisit: Play reviewers' reading of "audio to your own PC".

### J. Legal

**D23 — Apache-2.0 + trademark notice (owner decision, recommended).** `LICENSE` Apache-2.0, copyright "Yoav Shimron"; `TRADEMARK.md` reserves the DeskIT name, the dalet-as-desk mark and the icon. Reason: the proof (D12) leans on "read the code"; the three free trust amplifiers (SignPath, IzzyOnDroid, Certum OSS) require an OSI licence; "open source" is a phrase a non-technical user recognises. FSL-1.1-Apache-2.0 is the runner-up if the owner wants to block competing products (cost: those three amplifiers, i.e. unsigned forever or EUR 49-400/yr). AGPL rejected (NVIDIA-wheel friction, workplace fear). Evidence: `research/legal` options table, `research/signing` source 2, `research/android` source 9, `arch-A §1 T4`, `arch-B §1 T4`. Revisit: owner's call in phase 0.

**D24 — Third-party compliance.** `THIRD-PARTY-NOTICES.txt` generated at build (`pip-licenses --with-license-file`) plus hand entries: Python (PSF), Tcl/Tk (BSD), Rubik (OFL 1.1, ship `OFL.txt`; the four renamed cuts are an OFL Modified Version), skia-python/Skia (BSD-3), pywin32, PortAudio, ivrit-ai model (Apache-2.0 + attribution), faster-whisper/CTranslate2/Whisper (MIT), Ollama (MIT), NVIDIA EULA URL for the on-demand GPU pack, Llama 3.1 Community License + "Built with Llama" while a Llama is the default Groq repair model, Gemma notice only if Gemma 3 is recommended (prefer Gemma 4, Apache-2.0). PyAV: the core installer ships no GPL FFmpeg — phase 0 checks whether an LGPL cp311 `av` wheel exists (`JScheumann/pyav-ffmpeg-lgpl`); faster-whisper imports `av` at module level, so either the LGPL wheel goes in the base or faster-whisper is vendored (MIT) with a lazy `av` import; screen recording + camera become an opt-in **Recording pack** installed by pip with its licence shown. CUDA wheels never inside the installer (NVIDIA EULA: redistribution only as object code with material functionality; user-triggered pip download with the EULA link is clean). Evidence: `research/legal` component table and PyAV/NVIDIA sections, `map/packaging` risk 15, `map/capture` risk 9, `arch-B §1 T6, §11`. Revisit: when an LGPL `av` wheel for cp311 is confirmed.

**D25 — Privacy policy, terms, Israeli law.** Privacy policy (Hebrew + English, GitHub Pages, linked from wizard/Store/Play/sign-up) structured for Israel PPL s.11: controller Yoav Shimron + contact e-mail (no company); local by default — folder, contents, retention, deletion; BYOK cloud — exactly what goes to Groq/Google under the user's own account, the Gemini training + EEA clauses, 18+; optional account — anonymous by default, data collected (uid, app version, OS build, tier, report text, ticked attachments, timestamps, IP as seen by Supabase), purpose, voluntariness, consequence of refusal (no reports/sync; dictation unaffected), recipients (Supabase Inc., region Frankfurt; **Anthropic PBC when the developer processes reports with AI tools under his own account**), retention 12 months, rights via the app, breach handling; phone = your own network; update check = one anonymous GET. Terms of service: one page shown at first account use only; no EULA (Apache-2.0 carries the disclaimer). Amendment 13 (in force 2025-08-14): no registration/notification/DPO at this scale; still owed: the s.11 notice, a one-page database definition document, a written basic security procedure, access list, incident log, breach template (2017 Data Security Regulations, individual-managed tier — kept there by anonymous accounts and no audio/transcript columns unless ticked). Win+Shift+S: never a default; opt-in toggle + `ms-screenclip` handler route. Evidence: `research/legal`, `research/keys-privacy` §E, `arch-B §11`. Revisit: one-hour lawyer review (the only likely paid legal item).

### K. Guide, support, roadmap

**D26 — User guide and support.** Guide on GitHub Pages, Hebrew first with an English mirror, ten chapters: Install (SmartScreen screenshot, winget one-liner, Store link, Smart App Control note); First run; Dictating (hold, latch, English, correct; elevated windows; Win+V history); **Privacy and how to check it yourself** (the four ten-minute checks: Credential Manager entry; Network tab shows only loopback during plain dictation; Offline mode makes cloud features refuse; the published migration has no key column; optional `--verify` and a firewall-log recipe); Cloud features (getting free keys, quoted terms, what each feature sends); Phone keyboard; Screenshots/recordings/camera; Your data; Reporting a problem; FAQ (Defender flags, stuck download, no NVIDIA, Ollama optional, port busy). The Settings chapter is generated from `settings.read(defaults.toml)` + `WORDS`. Support: GitHub Issues template asking for `--diagnose` output (version, tier, OS build, last 50 support-safe log lines, never transcripts); in-app reports for non-technical users; `SECURITY.md` with a 90-day disclosure window. First-user channels: ivrit.ai community (ask to be listed), Vibe discussion #27, Israeli dev Telegram/Facebook groups, Geektime, r/Israel, r/hebrew; positioning "the Win+H that Hebrew never got" (Windows voice typing does not support Hebrew). Evidence: `research/competitors`, `map/ui` rec 13, `arch-B §12`. Revisit: after launch feedback.

**D27 — Roadmap: six phases, each shippable; v1 = phases 0-2.** Phase 0 Ground truth (3 days): measure CPU int8 latency on a no-GPU laptop; VirusTotal-scan a throwaway embeddable-Python installer; verify Supabase anonymous sign-in + Turnstile on Free; check the LGPL `av` cp311 wheel; owner decides licence and package id; owner rotates his keys. Phase 1 Separation (15-20 days): `paths.py` + portable mode + `--migrate`; `defaults.toml`/`settings.toml`/`state.json`; secrets in Credential Manager/DPAPI; `net.py` + allowlist + the lock tests; `[privacy]` gates + consent cards + `consent.json`; support-safe logs + redactor; neutral defaults; `VERSION`/`version.py`; DEVELOPER flag hides owner UI; test split; acceptance: owner's machine unchanged in portable mode, product CI green, key-string and egress tests green, `network.log` shows only loopback during a plain dictation. Phase 2 Installable (15 days): wheelhouse build + embeddable Python + tcl/tk; Inno per-user installer; wizard with tiers and packs; PyAV out of core; google-genai → REST; update check + verified download; `MANIFEST.sha256` + attestation + `--verify`; NOTICES, privacy policy, terms, SECURITY.md, NETWORK.md; winget manifest; acceptance: clean Windows 11 VM (Defender on, no NVIDIA) install → wizard → dictate in 10 minutes, VirusTotal ≤ 2 hits, `--verify` clean, winget PR merged. Phase 3 Reports, account, Store (12-15 days): Supabase project + published migration + RLS + bucket; anonymous auth + DPAPI session; report v2 + preview + outbox; replies; Your data + delete-account RPC; `dev/inbox.py` + routine reading consented fields; keep-alive cron; Microsoft Store submission; acceptance: a report from a second machine appears in Studio with no e-mail and no key-shaped string; delete-account removes everything; Store certification passed. Phase 4 Phone (12 days): package rename, release keystore, LAN pairing, per-phone tokens, GitHub APK, Play closed test, Data safety; acceptance: dictation over home Wi-Fi with no Tailscale, TLS to the PC only. Phase 5 Trust and reach (10+ days): SignPath application, IzzyOnDroid, e-mail linking (Resend + domain), settings/vocab sync, whisper.cpp Vulkan tier after a WER check, Google PKCE. v1 scope cuts (not in the first public build): read-aloud/corpus, Cerebras, the Hebrew web page, the Saturday routine, nightly tests, git card, sync, e-mail accounts, Store, Play, AMD/Intel GPUs, screen recording unless the Recording pack is installed. Evidence: `arch-B §13`, `arch-A` P2/P3. Revisit: after phase 0 numbers.

**D28 — The owner's hand-work list** (the plan's own chapter; nothing here can be done by code): decide licence + trademark posture; rotate and delete his Gemini/Groq/Cerebras keys before the first public commit; clean the tree (`.gitignore` additions for `questions.json`, `questions.lock`, `.agents/`; move owner scripts to `dev/`; scrub `config.toml` into `defaults.toml`; check git history for the tailnet name/token); GitHub public repo + Actions + Pages + `SECURITY.md` contact; Supabase project (`deskit`, `eu-central-1`, DB password in password manager, copy Project URL + publishable key, paste the migration, enable anonymous sign-in + Turnstile, OTP template, private bucket, MFA on Studio, keep-alive cron, monthly `pg_dump`); Microsoft Store individual account (phase 3: ID + selfie, confirm Israel, reserve "DeskIT", runFullTrust text); Google Play (phase 4: US$25, ID + card, keystore backup, 12 testers, Data safety); SignPath Foundation (phase 5, Apache only); legal papers (policy + terms Hebrew/English, database definition document, security procedure, breach template, optional one-hour lawyer review); a domain (~USD 10/yr, the one likely non-free item, phase 5 for e-mail linking); ivrit.ai courtesy note + optional int8 mirror; measurements (CPU laptop, 125/150 % DPI laptop, single-monitor desk); keep his own machine honest (`portable.txt`, `DESKIT_SUPABASE_SECRET` only in his environment, the routine's command file updated). Evidence: `arch-B §14`, every research report's "what the owner must do". 

**D29 — Open decisions only the owner can settle (each with the recommendation).** (1) Licence: Apache-2.0 (recommended) vs FSL. (2) Public name/identity: keep "DeskIT" and reserve the trademark; package id `io.github.massifapp.deskit`. (3) Store timing: submit in phase 3 (recommended) vs skip the Store entirely. (4) Anonymous-first accounts (recommended) vs e-mail from day one (needs a domain earlier). (5) Whether the Saturday routine keeps processing strangers' reports with Claude under his account (recommended yes, disclosed in the policy) or he reads them by hand. (6) Spend USD 25 on Google Play in phase 4 (recommended) vs GitHub APK only. (7) Buy a domain for e-mail linking (phase 5). (8) Whether the English detector stays a feature at all (recommended: optional on GPU tier only).

---

# 1. Executive summary and principles

This plan turns DeskIT — today a single-owner Windows Hebrew push-to-talk dictation app (Python 3.11 +
Tk + Win32, local faster-whisper, one checkout that is also the running install) — into software a
stranger can download, install and use without ever talking to the developer. It is written for two
readers: the owner (Yoav, a solo Israeli developer who asked for "the most convenient and simple path
for the user" and "my machine keeps working") and the AI coders who will implement it chapter by
chapter. The plan contains no code. The numbered decisions it implements live in `decisions.md`
(D1-D29); every chapter cites the decisions it carries out, and where a chapter finds a gap it says so
in its "Open points" rather than deciding on its own.

## The one-sentence design

**DeskIT becomes a per-user Windows app whose every personal byte lives in one folder the user can
delete, whose every outbound byte passes one chokepoint the user can watch, whose API keys live in
Windows' own credential store and provably never reach the developer, and whose first run gets a
stranger from download to a Hebrew sentence on screen in one sitting with at most four decisions**
(`decisions.md` preamble). The two source designs reach the same sentence from opposite angles:
`arch-B §1` asks that "a sceptic must be able to verify every privacy claim without trusting Yoav",
`arch-A §1` asks "what does a person who has never opened a terminal see".

Where the two designs disagreed, the user-first reading won whenever the owner's constraints allowed
it (`decisions.md` preamble). The one place the trust-first reading won outright is the channel order:
GitHub + winget ship on day 1 and the Store follows in phase 3 (D20), because the GitHub build is the
one whose bytes can be matched to a commit (`arch-B §1` tension 2).

## The owner's ask, restated as nine deliverables

The owner asked for nine things. Each row names the chapter that delivers it and the decisions behind
it; this chapter does not restate their details.

| # | Deliverable | What "done" looks like | Decisions | Chapter |
|---|---|---|---|---|
| 1 | Per-user data | Everything personal in `%LOCALAPPDATA%\DeskIT\`; the install tree read-only; the owner's checkout unchanged in portable mode; a "Your data" page where delete means delete | D1-D5, D6, D8, D9 | 3 (layout), 4 (data) |
| 2 | Simple problem reporting | One line, kind chips, attachment toggles with sizes, a preview of the exact payload, one "Send to the developer" checkbox, replies that come back to the same card | D15, D16 | 7 (owner machinery), 8 (backend) |
| 3 | Models | One Hebrew model downloaded at first run, resumable and verified, never bundled; hardware tiers probed and shown on Home; GPU pack on demand | D13, D14 | 6 (hardware) |
| 4 | Keys and the proof | Bring-your-own-key only; keys in Credential Manager; five locks and a Network window a sceptic can check from inside the app | D7, D10, D11, D12 | 5 (cloud and proof) |
| 5 | Install | Embeddable CPython + vendored wheelhouse in a per-user Inno installer, no admin; winget manifest; Store MSIX from the same tree in phase 3 | D19, D20 | 10 (packaging) |
| 6 | Versions and updates | One `VERSION` file shared with Android; weekly consent-gated check; verified one-click download that re-runs the installer; no self-patching binary | D21 | 11 (updates) |
| 7 | Guide | GitHub Pages, Hebrew first with an English mirror, ten chapters including "Privacy and how to check it yourself"; issue template; `SECURITY.md` | D26 | 14 (guide) |
| 8 | Screens | Sixteen new or changed screens: rewritten wizard, consent cards, Keys, Privacy, Your data, Network, Report v2, Phone, About, Update card and the rest | D18 | 9 (screens) |
| 9 | Supabase | Narrow, anonymous by default, zero cost: accounts for reports and replies, opt-in sync later; published migration with no column that could hold a key | D17 | 8 (supabase) |

Three deliverables the ask implies but did not name get their own chapters because they gate the
nine: the Android companion's pairing and identity (D22, chapter 12), licence and legal papers
(D23-D25, chapter 13), and the roadmap that orders the work (D27, chapter 15). What only the owner
can do — accounts, payments, decisions — is chapter 16 (D28, D29). Chapter 2 is the "before" picture
every other chapter changes; appendix A is the file-by-file inventory.

## Six principles

In priority order. Each later chapter's defaults derive from these; when two collide, the lower number
wins.

1. **Local by default, cloud by consent, never by config.** Every byte that leaves the PC passes one
   chokepoint (`net.py`) and one consent gate whose text and version are recorded; a config switch can
   never open a cloud path on its own (D7, D12; `arch-B §1` principle 1). Today the "transcript text to
   Groq" trade was accepted by the owner personally, not by a downloader (`map/cloud` risk 3).
2. **The proof is structural, not a promise.** Reviewers discount closed-source "zero telemetry"
   wording (`research/keys-privacy` §B). DeskIT's claim rests on five locks a stranger can check — the
   source on disk, the published schema, the Network window, the reproducible build, the redacted
   report preview (D12; `arch-B §1` principle 2).
3. **One sitting, at most four decisions, nothing installed besides DeskIT.** No Python, CUDA, Ollama,
   Tailscale or account is a prerequisite; the app fetches what it needs into its own folders and says
   what it is fetching and how big it is (D13, D14, D18; `arch-A §1` P2, P3). Every other choice has a
   safe default and a lazy consent card the first time a key needs it.
4. **One folder, one account, one key holder; delete means delete.** All personal data in one per-user
   folder; the account optional and anonymous; the API keys the user's own, in Windows' credential
   store; every store has a delete button that removes the files, not just the index (D1, D3, D9, D17;
   `arch-B §1` principles 3-4; `map/owner` risk 2).
5. **The owner's machine keeps working, and the owner's machinery obeys the same rules.** Portable
   mode leaves the checkout untouched; migration is explicit and never automatic; the Saturday
   routine reads only consented fields (D4, D15; `arch-B §1` principle 5; `arch-A §1` P7).
6. **Measure, don't assume; honest speed.** Every hardware-dependent default carries a phase-0
   measurement; the CPU tier prints "about as long as you spoke — we measured N s" instead of hiding
   a 40x slowdown (D14, D27; `arch-B §1` principle 6; `arch-A §1` P4; `map/core` risk 4).

One convention sits beside the principles rather than among them: **Hebrew where the user reads,
English where Tk draws chrome** — installer pages, guide, Store and Play listings and in-app body
paragraphs in Hebrew through the existing bitmap path; buttons, tabs and files in English (D18;
`arch-A §1` P8).

## Six resolved tensions

The two source designs were asked the same six questions. The table records what was decided and
why in one line each; the chapter named holds the mechanics.

| # | Tension | Decision | Why, in one line | Chapter |
|---|---|---|---|---|
| 1 | Embeddable CPython + wheelhouse vs PyInstaller onedir | Embeddable CPython 3.11 + vendored wheelhouse; never freeze; the Store MSIX wraps the same folder with a 30-line open-source launcher stub (D19) | Stock python.org binaries carry Defender reputation, PyInstaller's bootloader is the worst false-positive magnet, CUDA DLL paths become deterministic, and the tree is reproducible file-by-file (`research/packaging` S1/S2/S22; `arch-A §1` T1; `arch-B §1` T1) | 10 |
| 2 | Microsoft Store primary vs GitHub Releases + Inno + winget | Two channels from one tree: GitHub + winget on day 1 and for power users; the Store in phase 3 becomes the public "Get DeskIT" button for non-technical users (D20) | The Store is the only zero-cost route with no SmartScreen warning at all; the GitHub build is the only one whose bytes match a commit and an attestation (`research/signing` sources 5/7; `arch-A §1` T2; `arch-B §1` T2) | 10 |
| 3 | Velopack vs plain version check + manual download | Weekly consent-gated check, `latest.json`, user-initiated SHA-256-verified download, Inno re-run; no self-patching binary in v1 (D21) | An unsigned self-updater is the highest-privilege network path in the app, and Velopack assumes PyInstaller (`research/updates`; `arch-A §1` T3; `arch-B §1` T3) | 11 |
| 4 | FSL-1.1-Apache-2.0 vs Apache-2.0 | Apache-2.0 + `TRADEMARK.md` reserving the name and mark; FSL is the runner-up and the owner may overrule (D23, D29) | "Open source" is a phrase a stranger recognises, the proof leans on "read the code", and the three free trust amplifiers (SignPath, IzzyOnDroid, Certum OSS) require OSI (`research/legal`; `research/signing` source 2; `arch-A §1` T4; `arch-B §1` T4) | 13, 16 |
| 5 | Supabase Realtime as a phone relay | Rejected; pairing on the user's own Wi-Fi with a per-PC self-signed cert pinned by fingerprint, Tailscale as the documented "away from home" path (D22) | Audio must never transit owner infrastructure; Realtime caps at 200 sockets and 256 KB frames and pauses when idle (`research/android` source 10; `arch-A §1` T5; `arch-B §1` T5) | 12 |
| 6 | PyAV's GPL FFmpeg build | The core installer ships no GPL FFmpeg; phase 0 checks for an LGPL cp311 `av` wheel, else faster-whisper is vendored with a lazy `av` import; screen recording and camera become an opt-in Recording pack (D24) | Shipping x264/x265 inside an Apache installer is a compliance defect; the "user's pip fetches it with the licence shown" pattern already serves the NVIDIA wheels (`research/legal` §PyAV; `arch-A §1` T6; `arch-B §1` T6) | 6, 13 |

## v1 definition and what is cut

**v1 = phases 0-2 of the roadmap** (D27): ground truth measured, the code separated into install tree
and data folder with the locks and consent gates in place, and an installable build a stranger can
run on a clean Windows 11 VM with Defender on and no NVIDIA card — install, wizard, dictate in ten
minutes; VirusTotal at most two hits; `deskit --verify` clean; winget manifest merged. Phases 3-5
(reports and account on Supabase plus the Store; the phone; trust and reach) follow, each shippable on
its own. Chapter 15 holds the phase tables, effort and acceptance.

Not in the first public build (D27 "v1 scope cuts"): read-aloud and the corpus, the Cerebras path,
the Hebrew web page served by the PC, the Saturday routine, nightly tests, the git card, settings and
vocabulary sync, e-mail accounts, the Store, Google Play, AMD and Intel GPUs, and screen recording
unless the user installs the Recording pack. Each cut is either owner-only machinery (chapter 7) or a
feature whose consent, licence or delivery story is not ready before phase 3 (chapters 8, 12, 13).

Neutral defaults ship ON only for what runs locally: local backend, learned vocabulary, a small audio
ring, thirty days of history, hint and dot, capture to local files, and a once-asked weekly update
check. Every cloud pass, the account, report upload, sync, the phone listener, keep-awake and the lookup
cache ship OFF until a consent card (D6; chapter 4 has the full table with the owner's current value
each default replaces).

## Reading guide

The plan is sixteen chapters and one appendix. Read 1-2 for orientation, 3-5 before touching any
code (they define the layout, the data rules and the network chokepoint that every other chapter
assumes), then the chapter for the phase being implemented.

| Chapter | Title | Read it when |
|---|---|---|
| 1 | Executive summary and principles | First |
| 2 | Where the app stands | Before estimating anything; it is the inventory of what must change, cited to file and line |
| 3 | Target layout | Before the first pull request; `paths.py`, config layers, secrets, portable mode, `--migrate` |
| 4 | Per-user data, privacy defaults, retention and deletion | With chapter 3; the defaults table and the Your data page |
| 5 | Cloud passes, keys, consent cards and the key-privacy proof | Before any cloud code is touched; `net.py`, `privacy.allowed()`, the five locks and their tests |
| 6 | Hardware tiers, model download, packs, Ollama, TTS | Phase 2; the wizard's hardware step and the pack mechanics |
| 7 | What the owner-only machinery becomes | Phase 1; what leaves the product and what Report v2 is |
| 8 | Supabase backend | Phase 3; tables, RLS, bucket, RPC, outbox, the owner's console steps |
| 9 | Screens | Phases 2-3; every screen's elements, copy and what it writes |
| 10 | Packaging, installer, signing and channels | Phase 2; the build pipeline and the clean-VM matrix |
| 11 | Versions, updates, rollback | Phase 2; `VERSION`, `latest.json`, the Update card, the release checklist |
| 12 | Android companion | Phase 4; pairing protocol, package rename, delivery |
| 13 | Licence, notices, privacy policy, terms, Israeli law | Phase 0 (licence) and phase 2 (papers) |
| 14 | User guide, FAQ and support | Phase 2; written alongside the screens it documents |
| 15 | Roadmap, effort, acceptance, test plan | To sequence the work; the first ten pull requests |
| 16 | What the owner must do by hand, and open decisions | The owner reads this one; also the seed of the Hebrew summary |
| A | File-by-file change inventory | While implementing; keep / change / move / delete per file |

Conventions every chapter follows: English text, Markdown, no code; every claim about today's code
carries a `file:line` or a `map/<name>` citation; every external fact carries a `research/<name>`
citation; decisions are cited as `(Dn)`; each chapter ends with "Acceptance" and "Tests to add" and,
where needed, "Open points". `decisions.md` outranks any chapter: an AI coder who finds a chapter and
a decision in conflict implements the decision and files the conflict as an open point, never a new
decision. The repo is read-only for the plan writers; the owner's live app runs from that checkout,
so GUI checks during implementation run on a hidden desktop (chapter 15 states the rule).

## Acceptance

- Every one of the nine deliverables in the table above resolves to a chapter that exists in
  `DISTRIBUTION_PLAN.md` and whose heading number matches.
- Every decision D1-D29 is cited by at least one chapter other than this one (this chapter cites them
  only through the tables; the mechanics live elsewhere).
- The six principles and the six tensions in this chapter match `arch-B §1` and `arch-A §1` as
  resolved by `decisions.md`; no chapter states a principle or a tension outcome that differs.
- A reader who has read only this chapter can say, for any of the nine asks, which chapter to open and
  which phase delivers it.
- Nothing in this chapter restates a mechanism (a file, a key, a screen element) that a later chapter
  owns; it points instead.

## Tests to add

This chapter adds no product tests; its checks are documentary and run in the `dev/` tree, never in
the user build (D15 test split).

| Test | Asserts |
|---|---|
| `dev/test_plan_index.py::test_every_decision_cited` | Each token `D1` … `D29` appears in at least one chapter file other than `01-summary.md`. |
| `dev/test_plan_index.py::test_deliverable_chapters_exist` | Every chapter number named in the nine-deliverables table and the reading-guide table has a matching `# <n>.` heading in the assembled plan. |
| `dev/test_plan_index.py::test_chapter_sections` | Every chapter file ends with "## Acceptance" and "## Tests to add" (and "## Open points" only after those two). |
| `dev/test_plan_index.py::test_no_code_blocks` | No chapter contains a fenced code block whose info string names a programming language (the house rule "no code"). |

## Open points

- The ask counted nine deliverables; the plan has sixteen chapters because Android, legal and the
  roadmap could not be folded into the nine without repeating them. No decision is affected; the
  owner may prefer a different chapter order for the Hebrew summary (chapter 16).


---

# 2. Where the app stands: everything personal, machine-bound or owner-only

This chapter is the "before" picture. It condenses the eight subsystem maps (`map/core`, `map/cloud`, `map/learning`, `map/capture`, `map/owner`, `map/ui`, `map/phone`, `map/packaging`, measured on the owner's machine on 2026-09-15) into six inventories that the rest of the plan changes. It proposes nothing; every later chapter cites a row here as the thing it fixes (chapter 3 for the stores and layout, chapter 4 for defaults and retention, chapter 5 for the outbound table, chapter 6 for hardware, chapter 7 for the owner machinery, chapter 9 for the screens, chapter 12 for the phone). Line numbers are those the maps recorded; the repo was consulted read-only to confirm names.

Three facts frame everything below:

1. **The code folder is the data folder, the venv folder and the config folder.** `APP_DIR = Path(__file__).resolve().parent` is the root for every store (`main.py:34`, `dashboard.py:86`, `firstrun.py:51`, `apikey.py:18-19`, `lookup.py:627-629`, `history.py:27-28`, `versions.py:36`, `problems.py:316`, `server.py:66-70`, `notify.py:104`, `awake.py:116-117`); the launchers run `<folder>\.venv\Scripts\pythonw.exe` (`DeskIT.vbs:8`, `Dashboard.vbs:7`, `launch.py:37-41`). Sources: `map/core`, `map/learning`, `map/ui`, `map/packaging`.
2. **The tracked `config.toml` carries the owner's values as the shipped defaults** (his microphone, his monitors, his projects, his absolute folders, his voice pack, `[server] enabled = true`) and it is the only place user preferences, per-machine state and documentation can be written (`config.py:2340-2432`). Sources: `map/packaging` "set_values", `map/ui` "Machine-specific assumptions".
3. **`.gitignore` is the only thing keeping personal data off GitHub**, and that protection disappears in any installed copy that is not a git checkout (`map/owner` "Personal data stores"; `.gitignore:5-11, 30-35, 66-81`).

## 2.1 Personal data stores

Every store, its location today, what it holds, how sensitive it is, and whether it must be per-user in a distributed build. Paths are relative to the code folder unless stated. Sizes are the owner's on 2026-09-15.

### 2.1.1 Dictation, learning and history (`map/core`, `map/learning`, `map/packaging`)

| Store | Where (evidence) | Format | Holds | Sensitivity | Per-user? |
|---|---|---|---|---|---|
| Transcript history | `transcripts.log` + `.1..3`, 1 MB x 4 (`main.py:5660-5665`; reader `history.py:32-33`) | pipe-delimited text | every dictation raw and polished (`OK`, `POLISHED`, `main.py:5380, 5202`), every correction before/after (`CORRECTED`, `main.py:4498`), translate/punctuate/lookup in and out (`main.py:4646-4782, 5054-5086`), phone dictations (`OK`/`PHONE`, `main.py:2367`), review/study verdicts (`review.py:1097, 1115`; `study.py:646`), ask-the-screen questions (`visual_qa.py:3784`), errors with kept text (`main.py:5370`) | HIGHEST: includes everything said to Claude Code and what the user selected and read | yes |
| Status log | `app.log` + `.1, .2`, 500 KB x 3 (`main.py:5653-5658`, INFO level) | text | quotes learned pairs (`main.py:4551`, `study.py:649`, `review.py:1053, 1141`), polished text (`main.py:5205`), rejected polish candidates (`polish.py:457-459`), changed words from punctuate (`punctuate.py:358-359`), refused lookup selections (`lookup.py:803`), device names, and **the phone URL with its bearer token and the tailnet name** (`server.py:653-654`; `app.log:445` observed) | HIGH (token) | yes |
| Recent recordings ring | `recent\*.wav` + `*.json`, 50 + 50 files, 32 MB (`main.py:356, 5568-5573, 2391-2398, 4525`; `spool.py:79-98`; cap `[vocab] keep_audio`, `config.toml:1338`) | 16 kHz int16 WAV + sidecar with `seconds, saved, attempts, last_error, text, raw, backend, language, words[[word,start,end,conf]], source, corrected, study{...}, review{engine, when, agree, llm, decodes, variants[3 full decodes], changes}` | the user's voice plus four text readings of each clip | HIGHEST | yes |
| Refused recordings | `pending\*.wav` + `*.json`, keep 100 (`main.py:351, 5340, 5354, 5732`; `spool.py:66-97`) | same spool format | audio that failed to transcribe, kept indefinitely; `--drain` is the only recovery path (`main.py:5675-5710`) | HIGHEST | yes |
| Learned vocabulary | `vocab.json`, 8.5 KB, 63 entries (`main.py:338`; `vocab.py:295-299, 311-316, 362-380`) | JSON: version + `corrections[{heard, meant, hits, last, auto_hits, auto_srcs, glossary_only}]` | names of projects, tools and people and how the user mis-says them; sent to Groq inside every polish/review prompt | HIGH | yes |
| Hand-made vocabulary backups | `vocab.json.bak-20260828`, `-20260828-2151`, `-20260902-2156`, `-20260902-2205-resaved` in the repo root (no code writes `.bak`) | JSON copies | same content, older | HIGH | owner artefacts; must not ship |
| Verified corpus | `corpus\`, 324 wav + 324 json, **199 MB**, cap `corpus_keep = 400` (`study.py:494-510, 556`) | wav copied from `recent\` + `{text, tier gold/silver, seconds, kept}` | labelled voice data, explicitly "training data for a future LoRA" | HIGHEST, the biggest store | yes |
| Read-aloud recordings and deck | `corpus\read\` (59 wav + json, ~11 MB, **uncapped**), `corpus\read\texts\*.txt` (`01-deskit.txt`, `02-git.txt`, `03-phone.txt`, `written-*.txt`), `corpus\read\skipped.json`, transient `pending-<id>.wav` (`reading.py:490-503, 596-604, 650-664`; `main.py:370`; `dashboard.py:213-215`) | WAV + JSON + text | audio of the user reading known sentences; the user's own prose and model paragraphs seeded with learned names | HIGHEST | yes |
| Second-reading proposals | `review.json` (215 KB, 115 items) + `review.lock` (`main.py:2084, 2416`; `review.py:78, 664, 693, 865-890`) | JSON, 300 decided kept | full sentence of each dictation (`text`, `raw`, `proposed`), the three variant readings, accept/reject history, a live `hwnd` (`review.py:880`) | HIGHEST | yes |
| Lookup cache | `lookup_cache.json` (`lookup.py:627-629`, written `lookup.py:498, 522-529`; `.gitignore:8-9`) | JSON, entries keyed `version/target/mode/<selected text>`, up to 500, selections up to 200 chars | keyed by the literal text the user selected while reading (mail, chats, documents): "a record of what you were reading" | HIGH | yes |
| Settings, all layers in one file | `config.toml` (read `main.py:5952`; written by the line editor `config.py:2340-2430` from `main.py:1420, 1451, 1461, 1474, 1505, 1908, 1935, 3649, 3921`, `firstrun.py:639`, `dashboard.py:7813, 8267`; staging file `config.toml.<pid>.new`) | TOML, two-thirds comments, **tracked in git** | microphone name, absolute folders, hand-seeded `vocab.terms`, card/dot coordinates, hotkeys, model names, `server.enabled` | MEDIUM (personal names, machine paths, hardware) | yes, and must be split from shipped defaults |
| First-run marker | `.setup-done`, 104 bytes (`firstrun.py:65, 683-692`) | text | wizard has run on this copy | none | per install |
| Cue sounds + recipe stamp | `cues\*.wav`, `cues\.recipe` (`cues.py:21-23, 279-313`) | WAV | generated | none | regenerable cache |
| Whisper models | `%USERPROFILE%\.cache\huggingface\hub\models--ivrit-ai--whisper-large-v3-turbo-ct2` and `models--deepdml--faster-whisper-large-v3-turbo-ct2`, 1547 MB each (`local_whisper.py:28-29`; no cache override anywhere) | CT2 snapshot dirs | public weights | none | shared cache acceptable |
| Ollama models | `%USERPROFILE%\.ollama\models` (83 GB on the owner's machine) | GGUF | public weights | none | Ollama's own |

### 2.1.2 Keys and secrets (`map/cloud`, `map/phone`, `map/owner`)

| Store | Where (evidence) | Format | Holds | Sensitivity | Per-user? |
|---|---|---|---|---|---|
| API keys | `.env` beside the code (`apikey.py:18-19`; read `apikey.py:37-52`) or process env `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY` (`apikey.py:24-34`) | plaintext `KEY=VALUE` | the owner's Gemini, Groq and dead-tier Cerebras keys | CRITICAL: readable by any process running as the user and by any Windows account that can read the folder | yes; quotas are per key |
| Phone/notify bearer token | `server_token.txt`, 32 chars from `secrets.token_urlsafe(24)` (`server.py:67-69, 110-111`; `notify_hook.py:54`) | text | full access to transcribe/translate/lookup/review/notify on that PC | SECRET | per install |
| The same token in the open | `app.log` (`server.py:653-654`), the dashboard `phone` status field and clipboard on "Copy link" (`main.py:1760`; `dashboard.py:7673-7677, 8091-8099`), the phone page's `localStorage['dictationToken']` (`server.py:686-693`), the Android `SharedPreferences` file `dictation`, keys `url` and `token` (`Prefs.kt:14-16, 55-58, 71-77`; `allowBackup=false`, `AndroidManifest.xml:14`) | log line / clipboard / prefs | the secret, plus the hostname that reveals the tailnet name | HIGH | yes |
| Claude Code hook entries | `~/.claude/settings.json`, outside the repo, with absolute `<HERE>\.venv\Scripts\pythonw.exe` paths (`notify_hook.py:53, 420-451`; verified at lines 12 and 24) | JSON | integration wiring | LOW | per machine; dev |

Where a key value flows today, and nowhere else (`map/cloud` "Every place a key value flows"): `apikey.find_key()` (`apikey.py:56-62`) feeds `genai.Client(api_key=...)` in `transcribers/gemini.py:61-73`, `translate.py:121-138` and `visual_qa.py:912-919`, and the `Authorization: Bearer` header in `translate.py:431-434, 469` and `visual_qa.py:788-794, 836`; `tests.py:302-319` writes a throwaway `.env.selftest`. No key reaches `config.toml`, the dashboard, `problems.json`, `app.log`, `transcripts.log`, `lookup_cache.json`, `notify_hook` or `server.py`; only the human-readable key *source* is logged (`main.py:6334-6336, 5976`). Separately, the google-genai SDK reads `GOOGLE_API_KEY`/`GEMINI_API_KEY` from the environment on its own (`google/genai/_api_client.py:103-117`).

### 2.1.3 Screen, camera, reports and notifications (`map/capture`, `map/owner`, `map/ui`)

| Store | Where (evidence) | Format | Holds | Sensitivity | Per-user? |
|---|---|---|---|---|---|
| Screenshots | `[capture] folder`; owner `C:\Users\shimr\Desktop\Organized\Photos\Screenshots\DeskIT capture` (`config.toml:788`); code default `captures` relative to the code folder, `mkdir(parents=True)` on demand (`capture.py:1681-1684, 1700-1711`); written when `always_save = true` or on Save (`capture.py:6310-6313, 3695`) | PNG | anything on screen | HIGHEST | yes |
| Camera photos | `[camera] folder`; owner: same Photos folder (`config.toml:999`); default `captures` (`config.py:702`); saved at the shutter, before the editor (`capture.py:637, 5357-5379`) | PNG | the room, the person | HIGH | yes |
| Screen recordings | `[capture] clip_folder`; owner `C:\Users\shimr\Desktop\Organized\Videos\DeskIT` (`config.toml:796`); default = `folder` (`config.py:557`); `capture.py:1755-1779, 6652-6669` | mp4 h264 + optional AAC | screen video plus, when on, what the speakers played (WASAPI loopback, `capture.py:1835-2000`) and/or the microphone (`2262-2280`) | HIGHEST | yes |
| Clipboard | CF_DIB + "PNG" for pictures, CF_HDROP for clips (`capture.py:1273-1357`); `copy_to_clipboard = true` (`config.toml:801, 1001`) | system clipboard | leaves the app to any clipboard manager, and to Windows cloud clipboard if Win+V sync is on | transient | n/a |
| Ask-the-screen image | RAM only, JPEG long side up to 1344 (896 for Groq) (`visual_qa.py:118-122, 359-368, 4245-4246`); frozen desktop copies behind corner cards, ~18 MB each, up to 8 (`capture.py:326-330`) | bytes | screen contents while resident | HIGH while resident | n/a |
| TTS scratch | `%TEMP%\vqa-tts-<rand>\speak.ps1`, `aN.txt` (answer text), `aN.wav` (`visual_qa.py:1165-1178, 1195-1208`); deleted after playback, lingers if the process dies | text + WAV | the answer about a screenshot | MEDIUM, transient | per-user temp |
| Problem reports | `problems.json` (+ `problems.lock`, `problems.json.<pid>.tmp`) (`problems.py:97, 151-152, 286-299, 597, 723-740`) | JSON | typed complaint (up to 600 chars), `where`, `kind`, status, `dictation{raw, final, when, id, wav, seconds, backend, language, words, attempts, last_error}`, `shot` path, `env{branch, python, backend, local_model, english_model, beam_size, gemini_models, vocab_enabled, vocab_replace_after_hits, polish_when, punctuate_auto, review_enabled, max_seconds}`, `maybe{by, at, note}` | HIGH | yes |
| Pinned report evidence | `problems\<stem>.wav` + `.json` (3 files, 0.5-1.6 MB each) and `problems\<report-id>.jpg` (5 files; JPEG q85 of the **entire virtual desktop, all monitors**, `main.py:3719-3772`; `problems.py:375-414`); wavs survive `remove()` (`problems.py:869-874`) | WAV/JSON/JPEG | voice + everything on every screen | HIGHEST | yes |
| Report digest | `problems.md` (`problems.py:99, 1013-1071`), rewritten on every Problems-tab open (`dashboard.py:4067-4068`) and by nightly | Markdown | every open report's raw and final text, wav/shot paths, env | HIGH | yes |
| Notifications | `notify.json` (last 100: `title` up to 80, `body` up to 400 chars, which for Claude Code is the last assistant message, `project`, `session`, `app`, `hwnd`, `claude://` link, `seen`; 72 KB) and `notify.log` (125 KB, **uncapped**) (`notify.py:103-108, 289-314, 1425-1430`) | JSON + text | excerpts of the user's AI conversations and project names | HIGH | yes |
| Copy of the Windows notification database | `%TEMP%\hd-notify-watch.db` + `-wal` + `-shm`, refreshed on every toast from any app (`notify_watch.py:144-147, 405-424`) | SQLite | **every app's** toast text | HIGH, transient | must not exist unless the feature is on |
| Awake state and log | `awake_state.json` (`since, since_text, pid, by, saved timers`) and `awake.log` (664 KB, **uncapped**: hold/release, adapter names, active hours, whether `claude.exe` runs, vitals every 10 min with heaviest process names) (`awake.py:116-117, 1222-1245`); legacy `night_state.json`, `night.log` | JSON/text | which programs run and when the user is away | MEDIUM | per machine |
| Transient report thumbnail | `%TEMP%\report-shot-*.jpg`, unlinked in the same call (`dashboard.py:5548-5583`) | JPEG | screenshot bytes briefly | HIGH while present | n/a |
| Taskbar pin metadata | Windows per-window property store: absolute path of `Dashboard.vbs`, app id, icon path (`dashboard.py:539-622`) | shell properties | leaks the install path | LOW | per user |
| Rubik per-user font install | `%LOCALAPPDATA%\Microsoft\Windows\Fonts\Rubik*.ttf` + `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts` (`install_fonts.py:31-81`); the runtime loads privately from `fonts\` instead (`fonts.py:103-131`) | TTF + registry | optional dev tool output | none | per user |

### 2.1.4 Owner-only stores that exist in the tree today (`map/owner`, `map/packaging`)

| Store | Where (evidence) | Holds | Note |
|---|---|---|---|
| Weekly routine documents | `problems\weekly\`: plan/summary/archive per run, a 78 KB `-session.md`, `asked.json`, `run.log` (claude's stdout, 38 KB), `push.log` (every git call, 186 KB), `.done`/`.failed`, `review.lock` (`weekly_review.ps1:43-44, 197, 229, 385`; `dashboard.py:887-890`) | quotes reports and evidence; git output | owner only; must not exist in a user build |
| Nightly transcripts | `problems\nightly\`: 8-14 files of ~60 KB, `run.log`, `run.lock`, `running.json` (pid), `stop` (`nightly.py:122-139, 214, 789`) | test output, local paths | developer only |
| Routine questions | `questions.json` + `questions.lock` (`questions.py:76, 387-400`), **untracked and NOT gitignored** | the owner's typed answers about his code | owner only |
| Fallback logs | `%LOCALAPPDATA%\DeskIT\weekly-run.log`, `nightly-run.log` (`weekly_review.ps1:115`; `nightly_tests.ps1:49`) | task output | owner only |
| Scheduled tasks | "DeskIT Nightly Tests" (02:55, `WakeToRun`, `install_nightly_task.ps1:55, 106, 124`) and "DeskIT Weekly Report Review" (registered by hand, 04:00 with repetition) | embed the repo path | outside the repo |
| Parked test pages | `ch.html`, `cp_play.html`, `pp.html`, `np_passport.html`, 2.7 MB (`.gitignore:24-28`) | what the owner was reading | owner only |
| Dev artefacts | `.agents\` (untracked, not ignored), `android\local.properties` (`sdk.dir=C:/Users/shimr/dev-tools/android-sdk`), `android\app\build\...\app-debug.apk` served at `/app.apk` (`server.py:70-71, 218`), `~/.android/avd/deskit.avd`, `android/tools/emu.log`, `fake_pc.log` | build state | owner only |

Cross-store joins that any move must preserve (`map/learning`): the `recent\` wav stem is the `id` in `review.json` (`review.py:867`) and the `dictation.id` in problem reports (`weekly-reports.md:378-380`); `corpus\` keeps the file name of the `recent\` clip it was copied from (`study.py:499`). Daily LLM quota counters for study/review live in memory only (`study.py:561, 598-600`; `review.py:917, 980-982`) and reset on restart.

Kernel-object names that are identity rather than files (`map/core`, `map/packaging`): mutexes `Local\DeskIT.instance`, `.quit`, `.dashboard`, `.dashboard.show` (`singleton.py:24-29`, per session); pipe `\\.\pipe\DeskIT.control` (`control.py:43`, machine-global); loopback socket `127.0.0.1:8756` (`server.py:638-639`; hard-coded again in `notify_hook.py:52`, `skin/preview.py:99`, `skin/record.py:47`); AppUserModelIDs `Yoav.DeskIT` (`main.py:67`) and `Yoav.DeskIT.Dashboard` (`dashboard.py:95`).

## 2.2 Machine-specific assumptions

Grouped by where the assumption lives. "Effect" is what happens when the assumption is false, as the maps observed it.

### 2.2.1 In the tracked `config.toml` (the shipped defaults are the owner's values)

| Key | Owner value | Evidence | Effect elsewhere |
|---|---|---|---|
| `[audio] device` | `"Headset Microphone (Arctis 7 Chat), Windows WASAPI"` | `config.toml:293` | `recorder.py:107-127` falls back to the default input with a warning; the wizard pre-selects the phantom name (`firstrun.py:333-334`) and writes nothing if the user does not touch the row (`firstrun.py:633-636`); `config.toml:291-303` records that a stale device once "stopped the app from starting at all" |
| `[capture] folder`, `[camera] folder` | `C:\Users\shimr\Desktop\Organized\Photos\Screenshots\DeskIT capture` | `config.toml:788, 999` (confirmed) | `capture.py:1683-1685` does `mkdir(parents=True)`: the app **creates** that foreign path on another user's disk; relative values resolve against the code folder (`capture.py:1676-1684`) |
| `[capture] clip_folder` | `C:\Users\shimr\Desktop\Organized\Videos\DeskIT` | `config.toml:796` (confirmed) | same |
| `[hint] x, y` | `-1895, 823` | `config.toml:265-266` (confirmed) | a drag position on the owner's LEFT monitor (virtual screen starts at x = -1920, `config.toml:271-275`, `config.py:96-104`); `HINT_UNSET = -100000` is the never-moved sentinel (`config.py:114`, `overlay.py:542`) |
| `[notify] x, y` | `2188, 1373` | `config.toml:1168-1169` | off-screen on a 1080p single monitor; positions deliberately unvalidated (`config.py:879-893`) |
| `[problems] x, y, card_x, card_y` | `1066, 511, ...` | `config.toml:1230-1246` | same |
| `[review] x, y, scale` | `1238, 795, 1.0` | `config.toml:1704-1708` | same; `config.py:871-876` explains they are unvalidated on purpose |
| `[dot] x, y`, `[shelf] x, y` | app-written | `config.toml:235-236, 1281-1287` | same |
| `[vocab] terms` | `HebrewDictation`, `Massif`, `TripSync`, `Cowork` and the owner's toolchain | `config.toml:1343-1364` | prompted into every decode (`local_whisper.py:466-476`; `vocab.py:396-401`); over-prompting makes Whisper emit prompted words unbidden (`vocab.py:52-58`) |
| `[local] initial_prompt` | owner-tuned Hebrew dev jargon | `config.toml:1597`; default `config.py:271-273` | the second place the owner's register lives |
| `[server] enabled` | `true` (code default `False`, `config.py:1117`) | `config.toml:1305` | a fresh copy opens `127.0.0.1:8756` and probes `tailscale.exe` at every start (`server.py:116-125, 152-165`) |
| `[visual_qa] voice` | `"Microsoft Asaf"` (he-IL WinRT voice) | `config.toml:659-665`; `visual_qa.py:55-58, 1163-1166` | absent without the Hebrew speech pack; the script falls back to any `he*` voice, else the default English voice reads Hebrew (`visual_qa.py:1093-1097`) |
| `[notify] watch` | `"cowork"` | `config.toml:1144`; `notify_watch.py:154` | assumes the Claude desktop package identity `Claude_pzs8sxrjxfjjc!Claude`; stats the toast DB four times a second and copies ~2 MB to `%TEMP%` on every toast from any app (`notify_watch.py:395-424`) |
| `[capture] capture_hotkey` | `"win+shift+s"` (code default `ctrl+f11`) | `config.toml:767` | the Snipping Tool stops answering while DeskIT runs (`hotkey.py:809-822`); if the hook dies both fire (`hotkey.py:277-278`) |
| `[capture] system_sound`, `toast_seconds` | `true` ("the owner's choice on 2026-09-12"), `10` | `config.toml:820, 844`; `config.py:580, 632-638` | records the far end of calls by default |
| `[tests]` section | `nightly`, `wait_seconds` | `config.toml:1755-1794`; `config.py:1128-1150` | exists only for the owner's scheduled task |
| `[setup] done` | override | `config.toml:289`; `config.py:242-257` | an override for a per-install fact whose real record is `.setup-done` |
| Hotkey rationale comments | enumerate the owner's Chrome/Google-apps/NVIDIA-overlay bindings | `config.toml:5-63`; `hotkey.py` docstrings | the generated Settings help quotes them (`settings.py:1-19`); `insert` as pause and `left` as latch are opinionated |
| Measurement prose | hundreds of "MEASURED ON THIS MACHINE" lines | `config.toml:585-591, 752-765, 949-958, 1030-1039, 1560-1569` | documentation that becomes the Settings page help text, so the help quotes the owner's hardware |
| Ollama model choices and timeouts | `llama3.1:8b` (`:319`), `gemma3:12b` for polish/lookup/visual_qa (`:472, :610, :1538`), `keep_alive = "30m"` (`:505`), `translate.ollama_timeout_s = 150` (`:328`), `polish.max_wait_s = 10` (`:1563-1569`), `visual_qa.ollama_timeout_s = 120` (`:712`) | `config.toml` as cited; `map/cloud` | sized for a 16 GB RTX 5060 Ti sharing VRAM with Whisper ("nvidia-smi read 14710/16311 MiB"); on CPU the repair pass times out on every dictation and silently does nothing (`polish.py:436-446`) |
| Provider model ids | Groq `openai/gpt-oss-120b` (`:1513-1518`), Groq vision `qwen/qwen3.6-27b` (`:619-630`), Gemini list `gemini-2.5-flash, gemini-flash-latest, gemini-2.5-flash-lite, gemini-flash-lite-latest` (`:1578-1583`) | `config.toml`; `gemini_pool.py:64-77` keys the thinking knob on the name prefix | catalog drift yields 404 and a silent fall-through (`translate.py:489-493`; `gemini_pool.py:114-119`); users cannot fix it without editing `config.toml` |
| Free-tier numbers | Gemini 20 req/model/day, 30/60 min cooldowns; Groq ~1,000 req/day, vision 8000 TPM | `gemini_pool.py:1-6, 25-26`; `config.toml:1575`; `polish.py:79-81`; `visual_qa.py:43-46, 204-209` | constants of the 2026-08 catalog |

### 2.2.2 In code

| Assumption | Evidence | Effect |
|---|---|---|
| Source checkout with an in-folder venv is the only supported layout; `.venv/pyvenv.cfg` pins CPython 3.11.9 at `C:\Users\shimr\AppData\Local\Programs\Python\Python311` | `DeskIT.vbs:8`, `Stop DeskIT.vbs:6`, `Dashboard.vbs:7`, `launch.py:36-45` | no venv, no launch (2.5) |
| CUDA DLLs are found by scanning `site-packages/nvidia/*/bin` of the running interpreter and prepending to `PATH` | `local_whisper.py:51-79` | a different layout must reproduce it |
| Rolling window, LAG, timeouts and the "8.2 s vs 0.20 s" numbers were measured on an RTX 5060 Ti 16 GB; `Roller.finish(timeout=10)` is a GPU-speed assumption; three extra decodes per dictation are sized for ~40x real time | `rolling.py:6, 16, 229`; `local_whisper.py:213-224`; `requirements.txt:11-13`; `config.toml:1620-1632` | on CPU the rolling decode may not keep up (`rolling.py:229-238`) |
| Two Whisper models resident (Hebrew fine-tune + `english_model`) for the study `general` plan and English detection | `study.py:342-346`; `local_whisper.py:459-464` | +1.6 GB download and VRAM for a stranger |
| Study and review only exist when `keep_audio > 0` and the transcriber has `study_decode` | `main.py:356-357, 2078-2079, 2095-2097` | `keep_audio = 0` for privacy silently removes both learning engines |
| Keys live beside the code because of the owner's Windows Terminal `setx` problem | `apikey.py:1-8, 18-19`; `README.md:52-69` | see 2.1.2 |
| `GOOGLE_API_KEY` is accepted as a Gemini key | `apikey.py:24` | a user's unrelated gcloud key is silently used |
| `Config.backend` dataclass default is `"gemini"` while the file says `"local"` | `config.py:1219`; `config.toml:196` | a config missing that key defaults to the cloud audio path |
| Ollama at `http://127.0.0.1:11434`, IPv4 literal because this machine's `localhost` resolves to `::1` first | `config.py:326`; `config.toml:320-326`; `lookup.py:38-41` | settings menus offer "On this computer" whether or not Ollama exists (`settings.py:308-317`) |
| `User-Agent: deskit/1.0` required by Cloudflare in front of Groq and Cerebras | `translate.py:369-374`; `visual_qa.py:48-50` | any change gives 403 |
| Tailscale probed on PATH and at `C:\Program Files\Tailscale\tailscale.exe` (+ `x86`); `tailscale serve --bg 8756` must have been run once by hand | `server.py:116-124, 152-163, 656-658`; `README.md:3475-3480` | a per-user Tailscale install reads as "not up"; without Tailscale the URL is unreachable loopback (`server.py:641-642, 656-660`) |
| `Prefs.DEFAULT_URL = "https://yoav.example.ts.net"` is the default server of every APK install; package id `com.yoav.dictation` | `Prefs.kt:8-11, 25`; `build.gradle.kts:7, 11`; `method.xml:3`; `Notify.kt:34`; `tools/emu.py:30` | a stranger sees the owner's hostname pre-filled (`SettingsActivity.kt:77`; `HomeActivity.kt:180-181`) |
| Android cleartext only to `10.0.2.2`; strings name Tailscale as the transport; the served APK is the debug variant signed with the owner's `~/.android/debug.keystore` | `network_security_config.xml:8-10`; `strings.xml:83, 99, 115`; `server.py:68-69`; `build.gradle.kts:25-27` | a LAN IP over plain HTTP is refused by the OS; an APK built elsewhere cannot upgrade an installed one |
| `server.py` resolves token, APK and gradle file relative to the code folder and reads `versionName` out of `build.gradle.kts` (the source version, not the built APK's) | `server.py:66-85, 217-240` | `/health.apk` and the file served can disagree |
| Multi-monitor arithmetic around "primary 2560x1440, virtual screen (-1920, 0) 4480x1440"; only this layout was ever tested | `visual_qa.py:26-31, 371-381, 468`; `capture.py:328-330, 440-447`; `overlay.py:604-622`; `popup.py:74-78`; `main.py:3770` (`all_screens=True`) | generic APIs, so one monitor works, but untested |
| Process is DPI-unaware at 100 %; "adding a correction factor would break the machine it works on"; the dashboard is a fixed 1160x720 `.place(x=, y=)` layout with hand-measured pixel constants at 96 DPI | `visual_qa.py:24-31`; `ui.py:194-195`; `dashboard.py:97, 140-235, 372-387, 1334-1338, 7150-7155` | 125-150 % laptops are untested: soft captures, possibly mis-placed cards |
| Windows 11 fonts: `ICONS = "Segoe Fluent Icons"` with a hard-coded codepoint table | `ui.py:186-189, 226-240` | Windows 10 ships "Segoe MDL2 Assets": tofu boxes on every glyph |
| A full-size ANSI keyboard with a Hebrew layout "because that is what is on his desk" | `keyboard.py:10-16`; `dashboard.py:6533-6535` | cosmetic |
| Pixel positions of the owner's skin dot baked into `DOT_ROOM_X = 52`; "a 1280x720 camera is 1:1 on this 2560x1440 monitor"; webcam eMeet C960 MJPEG 25 fps; render endpoint "Arctis 7 Game" | `capture.py:333-346, 805-809, 2559-2582, 1857-1860, 1913-1931` | adapts; a machine with only a virtual camera opens it and shows black (`capture.py:789-790`) |
| Skia timings on the RTX 5060 Ti; CPU rasteriser 64 ns/pixel | `skin/gl.py:11-20, 44-47`; `SKIN.md` | a different animation on a weak machine; falls back to Tk without skia |
| Git on PATH and a GitHub `origin/main`; `versions.py` shells out to `git rev-parse` | `versions.py:53-66`; `dashboard.py:870, 918-948, 965-1008, 1031-1039, 1104` | "(unknown)" branch; Push/Undo say "GitHub could not be reached" |
| `weekly_review.ps1` typed fallback repo path `C:\Users\shimr\Desktop\Organized\Projects\DeskIT` and `C:\Users\shimr\.local\bin\claude.exe`; resolves `claude.exe` from the MSIX folder `Claude_pzs8sxrjxfjjc`; `bypassPermissions`; `--model claude-opus-5` | `weekly_review.ps1:42, 67-98, 103, 123, 270, 394-401`; `nightly_tests.ps1:40-43` | owner-only |
| `notify_hook.py` reads `~/.claude/settings.json`, `%APPDATA%\Claude\claude-code-sessions`, `config.toml` beside the script, and bakes the absolute `pythonw.exe` into the hook (a moved folder breaks it silently, exit 0 by design) | `notify_hook.py:53-54, 268, 370, 426-427, 537-544` | Startup `.lnk`, Desktop `.lnk`, both scheduled tasks and the hook all embed the repo path; `weekly_review.ps1:36-42` records exactly such an incident |
| `awake.py` reads `HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings`, runs `tasklist` for `claude.exe`, `powershell`, `powercfg` (and `powercfg /change` rewrites the power plan when `pin_timeouts`), `nvidia-smi`; docstring describes this machine's S3/hibernate state | `awake.py:1-12, 280-289, 320-341, 388-397, 421-432, 452, 645-648` | verdicts mention Claude on a stranger's PC |
| Windows-only primitives: `msvcrt.locking`, `GetAncestor`, DrawTextW, `WDA_EXCLUDEFROMCAPTURE` (Windows 10 2004+), `ms-settings:privacy-microphone` | `review.py:707-725`; `reading.py:126-133`; `review_card.py:20-23`; `capture.py:906, 975-1007`; `firstrun.py:197` | fine on Windows 10/11 |
| PowerShell TTS via `-ExecutionPolicy Bypass` on a temp `.ps1` under Windows PowerShell 5.1 | `visual_qa.py:1081-1110, 1170-1176` | blocked by AppLocker/WDAC on managed machines; Speak fails silently after 60 s (`visual_qa.py:1216-1218`) |
| `review.json` items carry a live window handle | `review.py:880` | meaningless after the session |
| The read-aloud `SUBJECTS` and Writer rules describe the owner's life ("his Windows dictation app") | `reading.py:108-121, 373-395` | owner-shaped prose for anyone else |
| Hebrew heuristics (prefix letters, sof pasuq, RTL) are not configurable | `vocab.py:85`; `study.py:91`; `summary.py:56-64`; `review.py:170-180` | right for a Hebrew product |
| `cp1255` locale codepage forced to UTF-8 | `server.py:135-139` | handled |
| Documentation drift on hotkey defaults: README says `translate_hotkey=ctrl+f9`, `punctuate=f2`, `lookup=f8`, `correct=ctrl+f8`; `config.py` defaults are `""`, `""`, `f6`, `f8`; the live file has `f8`, `ctrl+f2`, `ctrl+f8`, `ctrl+f9`; README says put the device *index* in `[audio] device`, the code wants a name | `README:4267-4274, 79-89`; `config.py:1185-1206`; `config.toml:106-167`; `recorder.py:112-115` | three sources disagree |

## 2.3 Outbound destinations

The cloud map's table, completed with the destinations other subsystems own. Grep of every `https?://` literal in the Python sources finds only the two provider URLs in `translate.py:366-367` plus loopback; there is no telemetry, crash reporter or update check anywhere (`map/cloud`). Audio leaves the machine only through the Gemini backend; every other body carries text or a screenshot (`map/learning`, verified against `translate.py:310-335, 450-470`).

| # | Host | Client | Key / auth | Data in the request | Triggered by | Free-tier assumption | Local fallback |
|---|---|---|---|---|---|---|---|
| 1 | `generativelanguage.googleapis.com` (SDK default base URL, `google/genai/_api_client.py:799`; key as `x-goog-api-key`) | google-genai 2.17.0 | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | **the entire WAV of the dictation** + system prompt (`transcribers/gemini.py:102-110`); `--check` sends "Reply with exactly: OK" (`gemini.py:153-156`) | `backend = "gemini"` (`transcribers/__init__.py:41-47`); `--drain` of `pending\`; `--check` (`main.py:5972-5983`) | 20 req/model/day, 4 models rotated | local faster-whisper only if `fallback_to_local` and only on `RateLimitError` (`main.py:4234-4254, 4338-4346`) |
| 1b | same | same | same | **text at the cursor** (selection or whole field, up to 5000 chars) for translate (`translate.py:148-149, 593-596`); phone `/translate` (`server.py:333-368`; `main.py:2454-2475`) | F8 / phone | same bucket | Ollama `llama3.1:8b` (`translate.py:582-607`) |
| 1c | same | same | same | **text** for punctuate, second in chain (`punctuate.py:268-284`); auto-punctuate every dictation if `punctuate.auto` (`main.py:2511-2555`); phone `/punctuate` | ctrl+F2 / auto / phone | same | Groq first, Ollama last (`punctuate.py:184`) |
| 1d | same | same | same | **selected text from any app** for lookup, whole selection in one request (`lookup.py:239-241, 675-686, 897-913`) | ctrl+F8 when the Ollama model is cold and `cold_to_gemini = true` (`lookup.py:827-840`), or `prefer = "gemini"`, or Ollama failed; phone `/lookup` | same | Ollama `gemma3:12b` (`lookup.py:651-672`) |
| 1e | same | same | same | **screenshot JPEG** (long side up to 1344) + question + chat history (`visual_qa.py:905-960`) | ctrl+F10 only if `allow_screenshot_upload = true` **and** `gemini_fallback = true` (`visual_qa.py:986-1006`) | same | Ollama vision (`visual_qa.py:546-712`) |
| 2 | `api.groq.com/openai/v1/chat/completions` (`translate.py:367, 466`) | urllib, `Authorization: Bearer`, UA `deskit/1.0` (`translate.py:466-471`) | `GROQ_API_KEY` | **transcript text of every dictation** of 20+ chars **plus up to 60 learned (heard, meant) pairs** in the system prompt (`polish.py:144-179, 283-294`); with `[local] rolling` each 25 s stretch goes **while the key is still held** (`config.toml:1450-1456`) | polish `when = "always"`, `prefer = "groq"` (`config.toml:1466, 1476`) | ~1,000 req/day; `reasoning_effort = low` (`translate.py:549-556`) | Ollama `gemma3:12b` (`polish.py:302-311`) |
| 2b | same | same | same | **text** for punctuate, first in chain (`punctuate.py:244-266`) | ctrl+F2 / auto / phone | same | Gemini, then Ollama |
| 2c | same | same | same | **screenshot** as `data:image/jpeg;base64` (long side up to 896, q80) + question + history (`visual_qa.py:822-836, 863-880`); model `qwen/qwen3.6-27b` | ctrl+F10 only if `allow_screenshot_upload = true` | 8000 TPM, ~830 tokens per image | Ollama vision |
| 2d | same | same | same | final transcript + alternative decodes + up to 30 learned pairs + **previous dictations as context** (`review.py:483-500, 635-650`) | second reading, every dictation, up to 200/day (`config.py:1109`) | same | Ollama only if `review.local_model = true` (`review.py:449-453`) |
| 2e | same | same | same | primary + 3 candidate decodes of a sent dictation (`study.py:323-340`) | study pass after 3 idle minutes, up to 60/day (`config.py:1029`) | same | Ollama (`study.py:308-313`) |
| 2f | same | same | same | a writing prompt with a subject and up to 3 of the user's learned names (`reading.py:433-452`) | read-aloud tab when the sentence folder runs dry (`dashboard.py:2437-2446`) | same | Ollama |
| 3 | `api.cerebras.ai/v1/chat/completions` (`translate.py:366`) | same class as Groq | `CEREBRAS_API_KEY` | transcript text (polish only) | only if `polish.prefer = "cerebras"` (`polish.py:313-324`) | **none: free tier gone, HTTP 402** (`translate.py:391-396`; `config.toml:1497-1509`) | Groq, Ollama |
| 4 | `127.0.0.1:11434` Ollama (`config.toml:326`) | urllib | none | `/api/chat` text or text + base64 image (`translate.py:311-336`; `visual_qa.py:686-698`); `/api/ps` probe (`lookup.py:703-704`); `/api/generate` warm (`lookup.py:742-750`); warm-up sends a 1-px PNG (`visual_qa.py:760-770`) | every key's fallback; first choice for lookup, visual_qa, polish when `prefer = "ollama"` | n/a | is the fallback |
| 5 | `huggingface.co` (Hub + CDN) | `huggingface_hub` via `faster_whisper.WhisperModel` (`local_whisper.py:28-29, 243, 339, 362, 404`) | none (public repos) | repo id, library user-agent; no user data; ~1.5 GB x 2 on first construction; may re-check the repo on later loads unless `HF_HUB_OFFLINE`/`local_files_only` | first `WhisperModel` for each repo; the wizard's step 2 (`firstrun.py:304-314`) | n/a | none: offline gives "could not load the local model" (`local_whisper.py:416-417`; `main.py:233-239`) |
| 6 | Tailscale (`tailscale.exe status --json`, `tailscale serve`) | subprocess (`server.py:152-163`) | Tailscale account on both devices | nothing sent by the app; the phone's audio travels **in** over the user's tailnet to `127.0.0.1:8756`, TLS by Tailscale with a Let's Encrypt cert (`README.md:3506-3510`) | `PhoneServer.start()` when `[server] enabled` (`server.py:652`) | free tier is enough | loopback URL no phone can reach |
| 7 | Phone to PC (over the tailnet) | Android app / web page | `server_token.txt` bearer | raw WAV (`Transcriber.kt:32-33`), field text for translate/punctuate (`DictationIme.kt:1015-1022`), selected text for lookup (`LookupActivity.kt:89`), review verdicts; a phone dictation then runs the same `_improve()` chain as a desk one (`main.py:2372, 5105-5130`), so phone **text** can reach Groq/Gemini under the same settings; audio never does | phone keys | n/a | n/a |
| 8 | `127.0.0.1:<port>/notify` | `notify_hook.py:364-397` | same bearer | title, body (up to 300 chars of the last assistant message), project name, session id, hwnd, link | Claude Code Stop hook | n/a | the route is also reachable from the tailnet through `tailscale serve` with the same token (`server.py:11-27, 652-662`) |
| 9 | Anthropic, via the local `claude.exe -p` | `weekly_review.ps1:269-284`; `weekly-reports.md:352-384` | the owner's Claude login (OAuth) | every open report: typed text, raw/final transcripts, sidecars with per-word confidence, matching `review.json` entries, **the screenshots** (read as images), plus source files it edits; not the audio | the owner's scheduled task | owner subscription | owner-only |
| 10 | GitHub `origin` (`massifapp/DeskIT`) | `git fetch/push origin main`, `git reset --keep origin/main` (`dashboard.py:1031-1039, 1085-1104`) | owner's git credential helper | the code, and any untracked-but-not-ignored file (`questions.json` today) | Push/Undo buttons | owner-only | n/a |
| 11 | PyPI (`nvidia-*` wheels) | pip by hand (`requirements.txt:13-14`) | none | nothing | install time | n/a | n/a |
| 12 | Claude desktop app (local IPC) | `os.startfile("claude://resume?session=...")` (`notify.py:627-648`) | none | a session id handed to the shell | Open-the-session | n/a | n/a |

What the user is told today (`map/cloud`): `README.md:52-77` documents the `.env` line and Google's free-tier data-use clause; `README.md:224-227` documents that the repair pass sends transcript text to Groq. There is no in-app consent screen: the wizard has no backend or key step (`firstrun.py:31, 303-315, 513-528`), the generated Settings page has no key field, and the only consent text is a settings row's help sentence for `prefer`, `groq_model`, `cold_to_gemini`, `gemini_fallback`, `gemini.models` (`settings.py:288-291, 349-391, 535-538, 895-952, 1189-1212`). The privacy trade "transcript text to Groq" was accepted by the owner personally (`polish.py:98-100`; `AGENTS.md:132-136`), never by a downloaded user.

Guarantees already in code that a proof can cite (`map/capture` "Guarantees in code", `map/learning`, `map/packaging`): with the upload gate shut the cloud constructors are never listed (`visual_qa.py:971-978, 1003-1007`; asserted by `tests.py:10804-10836`); warm-up never touches a cloud backend (`visual_qa.py:4329-4335`); a superseded question is not retried on the next backend (`visual_qa.py:1064-1068`); `apikey.py` is the only reader of `.env`; the phone server binds loopback only (`config.py:1118-1123`); every cloud builder skips with one INFO line when its key is missing (`polish.py:337-343`; `punctuate.py:262-266`; `lookup.py:683-685`; `visual_qa.py:1010-1016`); the polish glossary is filtered to pairs present in the text in `review.py:643-645`.

## 2.4 Owner-only features

Everything that exists for the owner's development loop, his hardware or his personal fine-tune project. "Could a user want it?" is the maps' verdict; what each becomes is chapter 7's job (D15, D16), not this chapter's.

| Feature | Where (evidence) | Why it is owner machinery | Could a user want it? |
|---|---|---|---|
| Saturday Claude routine | `weekly_review.ps1`; `.claude/commands/weekly-reports.md` (99 KB); `questions.py`/`questions.json`; the dashboard's answer bands and `-Answered` wake (`dashboard.py:2991-3020, 4574-5122, 5124-5193`; `main.py:4181-4195`); scheduled task "DeskIT Weekly Report Review" | runs the owner's `claude.exe` with `bypassPermissions`, commits to `main`, asks him in Hebrew; **writes code into the install folder**; reads `problems.json`, `review.json` and `recent\` sidecars by design (`weekly-reports.md:359-384, 1154`) | no |
| Push / Undo / branch card / `push.log` | `dashboard.py:831-1114` (`TRUNK = "main"` at 870, `PUSH_LOG` at 887-890, `local_changes`, `push_main`, `undo_main`); branch stamps `_warm_branch` (`1339-1357, 7900-7916`), "branch ... running now" (`7743-7745`), home footer (`3406-3464`); `versions.py:52-66` | git workflow of one developer; `restart_app` (`1117-1150`) is the only part without git in it | no (Restart yes) |
| Nightly test run | `nightly.py`; `nightly_tests.ps1`; `install_nightly_task.ps1`; `tests_quiet.py`; `[tests]` rows on The app tab (`settings.py:622-623, 1265-1274`); "Stop tests" bar button (`dashboard.py:115-118, 2011-2020, 8019-8055`); `problems\nightly\` | takes the real mouse at 02:55, `WakeToRun`, files reports "not by Yoav" (`nightly.py:487`); `KNOWN_FLAKES` "on this machine" (`nightly.py:168-172`) | no |
| Claude Code hook + `--install-hook` | `notify_hook.py` (writes `~/.claude/settings.json`, `notify_hook.py:420-451`); `/notify` route (`server.py:271, 639`) | depends on Claude Code being installed and on `[server] enabled` + `server_token.txt` (`notify_hook.py:531-533`) | power users, as an opt-in |
| Cowork toast watcher | `notify_watch.py`; `[notify] watch = "cowork"` (`config.toml:1144`; `settings.py:1046-1048`) | reads the Windows toast DB for the Claude desktop AUMID; copies the DB to `%TEMP%` | almost nobody |
| Dismiss-on-arrival / open-the-session | `notify.py:435-620, 627-648`; `dismiss_on_arrival` exists in code only (`config.py:809`) | reads the Claude desktop session store; warns "no Claude session store found" once per column on any machine without the app (`notify.py:1355-1358`) | only with the hook |
| Keep-awake vitals, `claude.exe` probe, `pin_timeouts` | `awake.py:283-286, 320-333, 421-432, 645-648, 841`; `[awake] vitals_minutes`, `pin_timeouts` (`config.toml:1062-1071`; `settings.py:1029-1036`) | built for phone remote control; counts Claude processes; rewrites the machine's power plan | hold / screens-off yes; probe and vitals no |
| Report a problem, as consumed today | `problems.py`; `problem_card.py`; `dashboard.py:5586-6229`; "Open problems.md" (`dashboard.py:3970-3992, 4058-4060`); digest `problems.py:1013-1071`; the all-screens grab (`main.py:3719-3760`) | user-facing in shape, but its only consumer is the routine reading local files (`.gitignore` comment "The weekly review reads these local, untracked files by design") | yes: the one thing here every user wants |
| Fine-tune corpus machinery | `study.py:479-529` (`corpus_keep`); `reading.py` whole (Read this to me + the Writer, `reading.py:1-9`); dashboard Corrections > Read tab (`dashboard.py:2092-2140, 2236-2460`); `[study] read_sentences`, `read_goal_hours`, `corpus_keep` (`config.py:1032-1042`; `settings.py:1170-1180`) | 199 MB of labelled voice for a LoRA that does not exist; subjects describe the owner's life; "five minutes a day" is his ceiling (`config.py:1036-1041`) | no |
| `STUDIED` / `REVIEW` telemetry lines in `transcripts.log` | `study.py:646-647`; `review.py:1097-1099, 1115-1117`; `main.py:1657, 2429` | written for the routine and the owner's measurements | no |
| Cerebras backend | `translate.py:377-526`; `polish.py:296-300, 313-324`; `[polish] cerebras_model`, `cerebras_timeout_s` (`config.toml:1519-1536`); `settings.py:387` | dead free tier "kept for whoever holds quota"; the owner's `.env` still carries the key | no |
| Console-only CLI modes | `main.py:5859-5913`: `--fake`, `--check`, `--list-devices`, `--test-sound`, `--translate`, `--punctuate`, `--lookup`, `--setup`, `--benchmark`, `--study`, `--review`, `--vocab`, `--drain`, `--dashboard`; `python lookup.py "text"` (`lookup.py:923-955`) | need `python.exe` + a terminal; `--study`/`--review`/`--benchmark` load the models a second time and hit Groq in a loop; `--drain` is the only recovery of `pending\` | `--drain` and `--list-devices` have user-facing equivalents nowhere |
| Test hooks in product code | `backend = "fake"` exposed on General as "Fake, for testing" (`settings.py:271-273`; `config.py:16`; `transcribers/fake.py`); `GroqVision.request_body()` (`visual_qa.py:822-836`); `.env.selftest` writer (`tests.py:302-319`); `[setup] done` override; `HD_SKIN` env var (`skin/__init__.py:57`) | test scaffolding | no |
| `ENGINE` version constants that force re-study/re-read; `[review] witness`, `max_changes`, `local_model`; `[vocab] hebrew_after_hits` | `study.py:87`; `review.py:76`; `config.toml:1326-1334, 1697-1713, 1743-1749` | numbers from measurement sessions (2026-09-02) | no |
| `lookup.dwell_ms` | `config.toml:522-528` (marked DEAD); `settings.py:927-929` still shows it; `config.py:441-445` | dead knob | no |
| "Send a test notification"; the twenty cue play buttons | `dashboard.py:7737-7762` | developer aids (the cue buttons are arguably user-facing) | partly |
| `classic`-branch compatibility guards | `hint.py:95-98`; `main.py:6265` ("this file must stay byte-identical on both branches") | developer machinery | no |
| Phone dev tooling | `/app.apk` self-hosting from the source tree's `build/` (`server.py:68-69, 217-240`); `apk_version()` from `build.gradle.kts` (`server.py:73-85`); `android/tools/emu.py`, `fake_pc.py` (absolute owner paths, `emu.py:19-24`, `fake_pc.py:13, 22`); the Hebrew web page at `/` (`server.py:670-834`), older than the English app; "Copy link" copying the token URL (`dashboard.py:8091-8099`); `yoav.example.ts.net` test fixtures (`tests.py:3931, 16447`) | assumes the user builds the APK on the same PC with JDK 17 + SDK 34 + Gradle 8.9 | no |
| Dev tools and docs in the tree | `tests.py` (1.3 MB), `tests_quiet.py`, `make_icon.py`, `audio_check.py` (pycaw, `requirements.txt:5`), `install_fonts.py`, `skin/preview.py`, `skin/record.py`, `fonts.py` `main()` probe, `AGENTS.md` (81 KB), `README.md` (293 KB lab notebook), `PARALLEL_FEATURES_PLAN.md`, `VISUAL_QA_PLAN.md`, `SKIN.md`, `.claude/`, `.agents\`, `*.html` test pages, `vocab.json.bak-*` | briefs and tools for the owner and his AI coders | no |
| Owner values living in the tracked config and in identity strings | the 2.2.1 table; `APP_ID = "Yoav.DeskIT"` / `"Yoav.DeskIT.Dashboard"` (`main.py:67`; `dashboard.py:95`); `com.yoav.dictation`; `Prefs.DEFAULT_URL` | the owner's name, desk and network baked in | no |

Docs disagree about the routine (`map/owner`): `README.md:3251-3265` says it "fixes nothing" and runs "Saturday 08:00"; `weekly-reports.md` (post 2026-09-12) builds and commits; the registered task fires at 04:00. `tests.py` asserts on developer files and README strings (`tests.py:25281` for `--install-hook` in the README; `tests.py:28490-28510` for the contents of `nightly_tests.ps1` and `install_nightly_task.ps1`), so removing the dev files breaks the suite unless it is split.

## 2.5 What breaks on a fresh machine

Ordered by when a stranger would hit it. Each row is observed behaviour, not a guess.

| # | Situation | What happens today | Evidence |
|---|---|---|---|
| 1 | No `.venv` / no Python 3.11 | the `.vbs` launchers point at a missing `pythonw.exe`; WScript says "cannot find the file" and nothing else; `tomllib` needs 3.11; the `skia.cp311` wheel pins 3.11 | `DeskIT.vbs:8`; `launch.py:36-49`; `map/packaging` |
| 2 | Clean `pip install -r requirements.txt` | **Pillow is not listed** yet `ui.py:34`, `keyboard.py:59`, `shelf_card.py:76`, `answer_card.py`, `notify_card.py`, `problem_card.py`, `review_card.py` import PIL unconditionally: the dashboard, the wizard and the shelf cannot start (`make_icon.py:5-6` says so); `pywin32` is required by `control.py` and `injector.py`; `av` is only a transitive dependency of faster-whisper, imported inside functions at `capture.py:1757, 2407, 2567` and `server.py:170-172` | `requirements.txt`; `map/ui`, `map/packaging`, `map/capture` |
| 3 | Install folder read-only (Program Files) | `setup_logging()` opens `APP_DIR/app.log` and `transcripts.log` before anything else: PermissionError, uncaught, silent under pythonw. Later writes with the same fate: `cues.ensure_files()` bare at `main.py:6361` (`cues.py:280, 291`), `.setup-done` (the wizard returns every launch, `firstrun.py:683-692`), `server_token.txt` (`server.py:111`, non-fatal via `main.py:2059-2064`), `pending\`/`recent\` (`spool.py:75`), `vocab.json` (`vocab.py:300-301`, learning lost), `review.Store._save` raising inside the engine thread on every job (`review.py:691-696`, no try/except), `config.toml` write-backs (`config.py:2416-2422`), `problems.py:596`, `notify.py:281`, `awake.py:1228`, `dashboard.py:890`; captures relative to the code folder; uninstall would take the pictures with it | `main.py:5653-5665`; `map/core`, `map/learning`, `map/owner`, `map/capture` |
| 4 | Second Windows user on the same PC, or dev copy + installed copy in one session | everything is in one folder, so two accounts share vocabulary, history and audio; the mutexes are `Local\` (fine) but the pipe `\\.\pipe\DeskIT.control` and port 8756 are machine-global: user B's pipe creation or bind fails and B's dashboard may talk to A's app (pipe DACL read-only to Everyone, so writes fail confusingly); the mutex refuses two instances by design | `control.py:43`; `server.py:638-640`; `singleton.py:132-137` |
| 5 | First run, online | ~3.1 GB downloaded from Hugging Face inside `App()` behind a static splash line, or inside the wizard's step 2 behind the single Hebrew status "loading the model and transcribing", with no size warning, no progress, no consent; on CPU the 3 s sample takes ~40x longer | `main.py:6179-6180`; `firstrun.py:304-314, 578-583`; `local_whisper.py:28-29` |
| 6 | First run, offline or proxied | message box "could not load the local model" | `local_whisper.py:416-417`; `main.py:233-239` |
| 7 | No NVIDIA GPU | CPU int8 for **both** models, ~40x slower (8.2 s vs 0.20 s for a 3 s clip); only `app.log` says so; rolling decode may not keep up; the review engine then runs three extra decodes per dictation on CPU holding the model lock, so the next dictation waits and the machine is busy for minutes after every sentence (`main.py:2077-2080` builds the engine whenever `review.enabled` and `keep_audio > 0`, no hardware gate); two 1.6 GB models resident in RAM | `local_whisper.py:396-417`; `requirements.txt:10-13`; `rolling.py:229-238`; `review.py:1000-1012`; `study.py:400-413` |
| 8 | Small GPU (4 GB or less) | the second model OOMs and English detection is silently off (`local_whisper.py:425-428`), or the first model OOMs and everything drops to CPU; `gemma3:12b` (~8.5 GB) cannot warm | `local_whisper.py:396-428`; `config.py:1006` |
| 9 | The shipped microphone name | `recorder.py:107-127` falls back to the default input with a warning; the wizard pre-selects the phantom name and keeps it if the user presses Next; Windows microphone privacy off gives pure silence, caught by the wizard after 6 s | `config.toml:293`; `firstrun.py:71-73, 161-170, 194, 333-334, 633-636` |
| 10 | The shipped `[server] enabled = true` | socket on `127.0.0.1:8756` + a `tailscale.exe` probe at every start; without Tailscale a warning and a loopback URL **with the token** are logged; port busy: `PhoneServer.start()` raises, the phone is disabled with a log line and only the dashboard's "not running" text | `config.toml:1305`; `server.py:656-664`; `main.py:2058-2064` |
| 11 | Absolute capture folders | `C:\Users\shimr\...` is created on the stranger's disk; if that fails `save_image` raises and the capture is only on the clipboard | `capture.py:1684`; `config.toml:788, 796, 999` |
| 12 | Card coordinates from a three-monitor desk | hint at x = -1895 on a machine with no monitor there; notify/problems/review clamped to odd places by `overlay.py:604-622` until dragged | `config.toml:265-266, 1168-1169, 1230-1246, 1704-1705` |
| 13 | No `.env` | `backend = "local"`: fine. `backend = "gemini"` (the dataclass default if the key is missing from the file): `get_transcriber` raises at startup ("fail fast: no key") and the app does not start; the message points at a `.env` path inside the code folder. A stray `GOOGLE_API_KEY` in the environment is silently used | `main.py:343`; `transcribers/gemini.py:61-67`; `apikey.py:24-34, 84-89`; `config.py:1219` |
| 14 | No key, Ollama installed | every LLM feature runs on Ollama, slower and VRAM-hungry; each cloud builder skipped with one INFO line; no UI surfaces this | `polish.py:337-343`; `punctuate.py:262-266`; `lookup.py:683-685`; `visual_qa.py:1010-1016` |
| 15 | No key and no Ollama (the common stranger) | translate: "cannot reach Ollama at http://127.0.0.1:11434" (`translate.py:353-357`); punctuate: "no punctuation backend answered" (`punctuate.py:365-366`); lookup: "no backend could look that up ... start Ollama" (`lookup.py:892-895`); polish silently pastes the raw transcript (`polish.py:433-464`); ask-the-screen: "the upload gate is off, so there is no cloud fallback" (`visual_qa.py:732-738`); review falls to structural proposals (`review.py:442-446`); study to the consensus vote; the Writer returns None; startup warm-ups all log failures (`polish.py:364-388`; `lookup.py:753-755`; `visual_qa.py:4335-4337`); `app.log` fills with warnings; menus still offer "On this computer" (`settings.py:274-277, 308-317`) | `map/cloud`, `map/ui` |
| 16 | Ollama present, models not pulled, or a small GPU / CPU | HTTP 404: "run 'ollama pull ...' or change <setting> in config.toml" (`translate.py:346-351`; `visual_qa.py:723-731`); with a small GPU `polish.max_wait_s = 10` expires every time, lookups hit 150 s, ask-the-screen 120 s; one image answer on CPU takes minutes (22.6 s cold even on the 16 GB card, `visual_qa.py:38-40`) | `polish.py:436-446`; `config.toml:328, 712` |
| 17 | Provider catalog drift | a retired Groq/Gemini model id yields 404, `TranslationError`, next backend; users cannot fix it without editing `config.toml`; any change to the `deskit/1.0` User-Agent gives 403 | `translate.py:369-374, 489-493`; `gemini_pool.py:114-119` |
| 18 | No "Microsoft Asaf" voice | Speak fails silently or reads Hebrew with the English voice; the Speak button still shows; AppLocker/WDAC blocks the temp `.ps1`, Speak fails after 60 s | `visual_qa.py:1093-1097, 1213-1219`; `config.toml:659-665` |
| 19 | `win+shift+s` shipped as the capture key | the Snipping Tool stops answering while DeskIT runs; ShareX/Greenshot/Snagit users lose the chord; if the hook dies both fire | `hotkey.py:277-278, 809-822` |
| 20 | DPI above 100 % | soft captures and possibly mis-placed cards; the fixed 1160x720 dashboard untested off 96 DPI | `visual_qa.py:24-31`; `ui.py:194-195`; `dashboard.py:97` |
| 21 | Windows 10 | every glyph in `ICON` is a tofu box (no "Segoe Fluent Icons") | `ui.py:186-240` |
| 22 | No git | version "(unknown)"; branch `?`; Changes card silently empty; Push says "git is not on PATH"; `env["branch"]` on reports meaningless | `versions.py:60-66`; `dashboard.py:938-939, 980-987` |
| 23 | No Claude Desktop / Claude Code | the notify door stays idle; `notify_watch` still stats the toast DB and copies it on every toast from any app; arrival watch warns on every column; the awake verdict mentions Claude and shells out to PowerShell/WMI on every screens-off | `notify_watch.py:395-424`; `notify.py:1355-1358`; `awake.py:338-380, 421-432` |
| 24 | No scheduled tasks, no `claude.exe` | the routine does nothing, silently ("FATAL" in `run.log`, exit 0); `[tests]` and "Stop tests" are dead weight; if a user ran `install_nightly_task.ps1` it would wake the PC at 02:55 and take the mouse | `weekly_review.ps1:168-171, 393-395`; `install_nightly_task.ps1` |
| 25 | The hook after a folder move | dies silently (absolute paths in `settings.json`, exit 0 by design); Startup `.lnk`, Desktop `.lnk` and both tasks break the same way | `notify_hook.py:426-427, 537-544`; `weekly_review.ps1:36-42` |
| 26 | Phone without Tailscale | hard stop: the URL is loopback, the Android app refuses plain HTTP to anything but `10.0.2.2`; with Tailscale, three documented traps (Serve not enabled, tray app not running, first cert fetch) each look like a network error; `/app.apk` answers 404 unless a debug APK was built next to the code; an APK built elsewhere cannot upgrade an installed one (debug keystore mismatch) and Play Protect flags it | `server.py:222-224, 656-660`; `network_security_config.xml`; `README.md:3495-3510`; `map/phone` |
| 27 | `[vocab] keep_audio = 0` chosen for privacy | `self.recent = None`: neither study nor review is built; corrections can no longer be tied to audio; `--benchmark` has nothing to measure. The privacy switch silently turns off half the product | `main.py:356-357, 2078, 2096, 5738-5741` |
| 28 | Elevated target windows | hook and paste inert (UIPI); installing or launching as admin would invert the problem | `main.py:5846-5850`; `README:4146-4149` |
| 29 | Unsigned scripts and AV heuristics | a global `WH_KEYBOARD_LL` hook + clipboard writes + microphone is the signature heuristics flag; SmartScreen on `.vbs` | `hotkey.py:1269` |
| 30 | Startup with Windows | not implemented (no Run key or Startup shortcut in the core files; the only `winreg` use is `install_fonts.py`) | `map/core` |
| 31 | Config regenerated from code defaults | behaviour changes: `ServerConfig.enabled` False in code vs true in the file; `dismiss_on_arrival` in code but not in the file; `backend` "gemini" in code vs "local" in the file; an old user file cannot receive a new key inside a section (`config.py:2397-2400`; `firstrun.py:61`), so an update that ships a new `config.toml` overwrites user choices | `config.py:809, 1117, 1219`; `map/packaging` "set_values" |
| 32 | `tests.py` pins today's defaults | `tests.py:13604, 13718, 14897` assert `folder == "captures"`; `tests.py:3965-3977` that `server.host` stays loopback; `tests.py:25281, 28490-28510` on dev files | `map/capture`, `map/phone`, `map/owner` |

Things that already degrade correctly and are worth keeping (`map/learning`, `map/ui`): a missing Groq key is skipped with one log line in polish/study/review/writer; fresh `vocab.json` and `review.json` are handled (`vocab.py:275-278`; `review.py:679-681`); no webcam is handled (`capture.py:6437-6442`); fonts load privately from `fonts\` and fall back to Segoe UI (`fonts.py:90-118`; OFL 1.1 clean, `fonts/OFL.txt`); the skin falls back to Tk without skia (`skin/__init__.py:53-66`); a missing `comtypes` only skips the taskbar pin metadata (`dashboard.py:614-622`).

## 2.6 config.toml key classification

Per section, as the maps classified the ~200 keys in 24 sections (`map/ui` totals: roughly 85 user, ~95 advanced, ~25 developer-or-machine, of which 17 are screen coordinates or device names that are per-machine state rather than settings). Legend: **U** = belongs on a normal Settings page; **A** = keep behind an Advanced fold with the existing comment as help; **D/M** = developer-only, a dead knob, or per-machine state written by the app. "Privacy" marks a key that decides what leaves the machine. Where the maps disagreed the stricter reading is given and the disagreement is listed under Open points.

| Section (`config.toml` lines) | U | A | D/M |
|---|---|---|---|
| top-level (5-208) | `hotkey`, `english_hotkey`, `latch_hotkey`, `translate_hotkey`, `punctuate_hotkey`, `correct_hotkey`, `lookup_hotkey`, `pause_hotkey`, `auto_language`, `auto_pause_fullscreen`, `backend` (privacy: audio to Google), `fallback_to_local`, `splash`, `indicator` | `paste_chord`, `restore_delay_ms`, `min_seconds`, `max_seconds`, `latch_max_seconds` | the `fake` choice of `backend` |
| `[dot]` (229-236) | `corner` | | `x`, `y` (written by "Move the dot") |
| `[hint]` (253-274) | `enabled`, `corner`, `scale` | `after_ms` | `x`, `y` |
| `[setup]` (289) | | | `done` (override of `.setup-done`) |
| `[audio]` (292-293) | `device` (only via a list, never typed) | `sample_rate` | the shipped *value* of `device` |
| `[feedback]` (307-309) | `enabled` | `placeholder`, `retry_seconds` | |
| `[translate]` (311-333) | `target` | `max_chars`, `ollama_model`, `timeout_s`, `copy_chord`, `select_all_chord` | `ollama_url`, `ollama_timeout_s`, `settle_ms` (hardware-derived) |
| `[punctuate]` (334-384) | `auto`, `prefer` (privacy), `nikud` | `max_wait_s`, `max_chars`, `groq_model`, `ollama_model` | |
| `[lookup]` (385-552) | `both_ways`, `prefer` (privacy), `cold_to_gemini` (privacy: on a machine without Ollama that is every lookup to Google), `strip_niqqud`, `max_width`, `max_height` | `hebrew_share`, `max_chars`, `model`, `cache_entries`, `skip_consoles` | `keep_alive`, `dwell_ms` (dead) |
| `[visual_qa]` (554-721) | `enabled`, `visual_qa_hotkey`, `allow_screenshot_upload` (privacy: "the single most important privacy switch in the app"), `prefer`, `speak`, `auto_send`, `echo_to_field` | `gemini_fallback`, `max_side_px`, `num_predict`, `window_alpha`, `cloud_timeout_s` | `voice` (installed voices), `ollama_model` (VRAM), `groq_model` (catalog), `warmup`, `ollama_timeout_s` |
| `[capture]` (722-924) | `enabled`, `capture_hotkey`, `record_hotkey`, `folder`, `clip_folder`, `copy_to_clipboard`, `after_shot`, `toast_corner`, `always_save` (privacy), `cursor`, `audio` (privacy), `system_sound` (privacy), `timer_corner`, `announce`, `quality` | `toast_seconds`, `toast_stack`, `toast_in_shots`, `copy_clip_path`, `fps`, `max_minutes` | the shipped *values* of `folder`/`clip_folder` |
| `[camera]` (925-1015) | `enabled`, `camera_hotkey`, `mirror`, `timer`, `folder`, `copy_to_clipboard`, `edit_after_shot` | `size`, `fps` | `device` |
| `[awake]` (1016-1078) | `hold`, `enabled`, `screens_hotkey` | `screens_off_again_s`, `keep_screens_off_s`, `pin_timeouts` (rewrites the Windows power plan) | `vitals_minutes` |
| `[notify]` (1079-1180) | `enabled`, `cue`, `interrupt`, `corner`, `dismiss_hotkey`, `remind_every_s`, `remind_times`, `scale` | `card_seconds`, `stack_max`, `coalesce_s`, `quiet_s`, `anchor` | `watch` (Claude-Desktop-specific), `dismiss_on_arrival` (code only), `x`, `y` |
| `[problems]` (1181-1249) | `enabled`, `report_hotkey`, `shot` (privacy), `keep_audio` (privacy) | `keep_resolved` | `x`, `y`, `card_x`, `card_y` |
| `[shelf]` (1265-1290) | `enabled`, `shelf_hotkey`, `corner`, `scale` | `rows`, `hush_notifications` | `x`, `y` |
| `[server]` (1297-1308) | `enabled` (opens a socket) | `port` | `host` (must stay loopback, `tests.py:3965-3977`) |
| `[vocab]` (1309-1358) | `enabled`, `keep_audio` (privacy: the real "keep my recordings" switch, coupled to study/review), `terms` (personal: must ship empty) | `max_terms`, `replace_after_hits` | `hebrew_after_hits` (2026-09-02 measurement) |
| `[study]` (1366-1418) | `enabled`, `idle_minutes` | `max_clip_seconds` | `llm_per_day` (Groq bucket), `corpus_keep` (fine-tune material), `read_sentences`, `read_goal_hours` |
| `[polish]` (1420-1573) | `when`, `prefer` (privacy: the switch that sends every dictation's text to Groq) | `min_chars`, `groq_model`, `groq_timeout_s`, `max_wait_s` | `cerebras_model`, `cerebras_timeout_s` (dead provider), `ollama_model` (VRAM), `warm_up` |
| `[gemini]` (1574-1584) | | `models` (catalog drift), `timeout_s` | |
| `[local]` (1586-1668) | `cleanup`, `extra_fillers`, `device` (auto/cuda/cpu, hardware-probed) | `initial_prompt`, `english_threshold`, `guard_hallucinations`, `beam_size`, `drop_trailing_boilerplate`, `extra_boilerplate`, `rolling`, `rolling_window_s` | `model`, `language` ("MUST stay pinned", `config.py:2275-2277`), `english_model` |
| `[review]` (1670-1753) | `enabled`, `card_seconds`, `corner`, `scale`, `fix_in_field` | `max_changes`, `witness`, `accept_key`, `reject_key`, `later_key`, `edit_key`, `max_clip_seconds` | `x`, `y`, `llm_per_day`, `local_model` |
| `[tests]` (1755-1794) | | | `nightly`, `wait_seconds` |
| `[questions]` | | | referenced by `main.py:371-401` and `dashboard.py:3911-3943` but absent from `config.py`: dead until added |

How a key becomes a Settings row today (`map/ui`, `settings.py:1-19`): the generated page reads the help text and menu choices out of the TOML comments, so the classification above is also a classification of *which comments* a stranger will read as help. The eight "privacy" keys (`backend`, `punctuate.prefer`, `lookup.prefer`, `lookup.cold_to_gemini`, `visual_qa.allow_screenshot_upload`, `capture.always_save`, `capture.audio`/`system_sound`, `polish.prefer`, plus `vocab.keep_audio`, `problems.shot`, `problems.keep_audio`, `study.corpus_keep`) are today ordinary rows whose only consent text is a help sentence.

## Acceptance

The audit is done when:

1. Every store in 2.1 has a path, a format, a sensitivity and a per-user verdict, each with at least one `file:line` from a map; no store named in any map's "Personal data stores" section is missing (cross-checked against the eight maps' tables: 27 rows in `map/core`, 15 in `map/learning`, 10 in `map/capture`, 19 in `map/owner`, 19 in `map/ui`, 13 in `map/phone`, 28 in `map/packaging`, 7 in `map/cloud`).
2. Every outbound host in 2.3 carries the data sent, the key used, the trigger and the fallback; the union of hosts equals the union of the maps' "External services" tables (Gemini, Groq, Cerebras, Ollama, Hugging Face, Tailscale, phone-to-PC, loopback `/notify`, Anthropic via `claude.exe`, GitHub, PyPI, Claude desktop IPC).
3. Every owner-only feature in 2.4 names its files and its dashboard or settings surface, so chapter 7 can build its "today / product / dev checkout" table without re-reading the maps.
4. Every row in 2.5 is observed behaviour with a citation; none is speculation.
5. Every `config.toml` key appears exactly once in 2.6; chapters 3 and 4 take their U/A/D/M splits and the privacy list from this table without redefining them.
6. Chapters 3-7, 9 and 12 cite rows of this chapter as the "before" of each change; nothing in this chapter proposes a "after".

## Tests to add

These tests pin the inventory so that later chapters can measure their changes against it. They pass against today's tree (or fail in the exact way this chapter documents) and are the baseline chapters 3-7 flip.

| Test | Asserts |
|---|---|
| `test_audit_app_dir_write_sites_are_inventoried` | a static scan of the product `.py` files for every `APP_DIR / "<name>"` (and `Path(__file__).resolve().parent / "<name>"`) expression yields exactly the set of store names in 2.1.1-2.1.4 (`transcripts.log`, `app.log`, `recent`, `pending`, `vocab.json`, `corpus`, `review.json`, `review.lock`, `lookup_cache.json`, `config.toml`, `.setup-done`, `cues`, `.env`, `server_token.txt`, `problems.json`, `problems.md`, `problems.lock`, `problems`, `notify.json`, `notify.log`, `awake_state.json`, `awake.log`, `questions.json`, `questions.lock`, `captures`); a new name fails the test until it is added to the audit |
| `test_audit_outbound_hosts_are_inventoried` | the set of `https?://` literals in the product sources equals `{api.groq.com, api.cerebras.ai, 127.0.0.1}` plus the SDK/Hub hosts reachable through `google.genai` and `huggingface_hub` imports; any new literal fails until 2.3 lists it |
| `test_audit_key_readers_are_only_apikey` | `os.environ` lookups for `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY` and reads of `.env` occur only in `apikey.py` (and the `.env.selftest` fixture in `tests.py`) |
| `test_audit_key_never_written_to_stores` | with fixture keys loaded, running one polish, one punctuate, one lookup, one ask-the-screen and one report leaves no key-shaped string in `config.toml`, `problems.json`, `problems.md`, `app.log`, `transcripts.log`, `lookup_cache.json`, `notify.json` (today's documented state; chapter 5 widens it to the whole data folder) |
| `test_audit_token_is_logged_today` | `PhoneServer.start()` without Tailscale logs the loopback URL containing `#t=<token>` (`server.py:653-654`); this test is expected to be inverted by chapter 4's log split and exists so the inversion is visible |
| `test_audit_owner_values_in_tracked_config` | the tracked `config.toml` contains the strings `Arctis 7`, `C:\Users\shimr`, `HebrewDictation`, `Microsoft Asaf`, `x = -1895`, `enabled = true` under `[server]`, `watch = "cowork"`, `capture_hotkey = "win+shift+s"` and a `[tests]` section; chapter 3's `defaults.toml` scrub inverts every assertion |
| `test_audit_dataclass_defaults_disagree_with_file` | `Config().backend == "gemini"` while the file says `"local"`; `ServerConfig().enabled is False` while the file says `true`; `dismiss_on_arrival` exists in code and not in the file; chapter 4 inverts the first |
| `test_audit_set_values_cannot_add_section_key` | `config.set_values` refuses to add a key that is absent inside a named section (`config.py:2397-2400`); chapter 3 inverts it |
| `test_audit_keep_audio_zero_disables_learning` | with `[vocab] keep_audio = 0` neither the study nor the review engine is constructed (`main.py:356-357, 2078, 2096`); chapter 4's `[review] keep_audio` inverts it |
| `test_audit_pillow_missing_from_requirements` | `requirements.txt` does not name `pillow` while `ui.py`, `keyboard.py`, `shelf_card.py` import PIL at module level; chapter 10's wheelhouse inverts it |
| `test_audit_settings_keys_classified` | every key that `settings.read(config.toml)` yields appears exactly once in the U/A/D-M table of 2.6 (kept as a data file beside the tests), and every privacy-marked key is one of the twelve listed |
| `test_audit_dev_file_assertions_in_tests` | `tests.py` references `nightly_tests.ps1`, `install_nightly_task.ps1` and the README's `--install-hook` line (`tests.py:25281, 28490-28510`); chapter 7's test split moves these to `dev/` |
| `test_audit_questions_section_is_dead` | `config.py` defines no `[questions]` section while `main.py:371-401` and `dashboard.py:3911-3943` reference one |

## Open points

Resolved while writing (checked read-only against the repo on 2026-09-16, so later chapters can rely on them): the maps disagreed on a few `config.toml` lines and log counts. The file has `[notify] x = 2188, y = 1373` at `1168-1169`, `[review] x = 1238, y = 795` at `1704-1705` (so `map/learning`'s "`[review] x = 2188, y = 1373` at 1168-1176" was the notify card), `[hint] x/y` at `265-266`, `[problems] x/y/card_x/card_y` at `1230/1238/1240/1246`, `[dot]` and `[shelf]` coordinates at the never-moved sentinel `-100000` (`235-236`, `1281-1287`), `capture.folder` at `788`, `clip_folder` at `796`, `camera.folder` at `999`; `app.log` rotates at 500 KB with 2 backups (3 files) and `transcripts.log` at 1 MB with 3 backups (4 files) (`main.py:5653-5665`); `config.py` contains no `questions` section at all, so every `[questions]` reference in `main.py:371-401` and `dashboard.py:3911-3943` is dead code today. Other `config.toml` line citations in this chapter may drift by a few lines between readings of the maps and should be treated as approximate to within five lines.

Still open:

1. **Pillow**: `map/packaging` could not find a listed package that declares Pillow as a dependency and asks that a fresh venv be built to confirm; chapter 10 (D19) already adds `pillow` to the CPU set, so this is a phase-0 check, not a decision.
2. **Weekly task time**: the registered task fires at 04:00 with repetition; README says Saturday 08:00. Owner-side only; noted so the guide (chapter 14) inherits neither text.
3. **`dismiss_on_arrival`** exists in `config.py:809` but not in the file (`map/owner`); D6 does not mention it. Chapter 4 should decide whether it ships as a hidden default or is dropped with `watch`.
4. **`[translate] copy_chord`, `select_all_chord`** appear only in `map/packaging`'s classification (advanced). Checked: they are dataclass defaults in `config.py:333-334` (`"ctrl+c"`, `"ctrl+a"`, read at `config.py:1627`) with no line in `config.toml`, so like `dismiss_on_arrival` they are code-only keys today; chapter 3's `defaults.toml` must decide whether to surface them (they would then appear on the generated Settings page for the first time).


---

# 3. Target layout: directories, config layers, state, secrets, portable mode, migration

This chapter implements D1 (three roots), D2 (config layers), D3 (secrets), D4 (portable/developer mode and `--migrate`) and D5 (collision-proof names). Chapter 2 is the "before" picture; chapter 4 says what goes into each store by default and how it is deleted; chapter 5 owns the key-privacy proof that this layout makes possible; chapter 10 builds the install tree described here.

## 3.1 The two trees

**Install tree, `APP_DIR`** — read-only for the app after install. Per-user under `%LOCALAPPDATA%\Programs\DeskIT` for the Inno build, under `WindowsApps` for the Store build; identical inside (D1, D19, D20; `arch-B §2`).

| Path under `APP_DIR` | Contents | Who writes it |
|---|---|---|
| `python\` | python.org embeddable CPython 3.11, `tcl\`, `tkinter`, `_tkinter.pyd`, `tcl86t.dll`, `tk86t.dll`, `python311._pth`, `Lib\site-packages\` (the wheelhouse) | the build only (chapter 10) |
| `app\` | the product `.py` tree from `git archive`: `deskit.pyw`, `main.py`, `paths.py`, `net.py`, `secrets.py`, `privacy.py`, `version.py`, … | the build only |
| `app\defaults.toml` | today's `config.toml`, scrubbed (chapter 4), comments intact — the Settings-page generator input | the build only; never the app |
| `app\fonts\`, `app\skin\`, `app\icon.ico` | assets already read from `APP_DIR` today (`map/core` rec 1 keeps these) | the build only |
| `app\cues\` | the 20 cue WAVs pre-rendered at build (deterministic, `cues.py:180-184`) — nothing is written at start, which removes the bare `cues.ensure_files()` call at `main.py:6361` from the fresh-machine failure list (`map/core` "What breaks" item 2) | the build only |
| `LICENSE`, `THIRD-PARTY-NOTICES.txt`, `NETWORK.md`, `SECURITY.md`, `TRADEMARK.md`, `VERSION`, `MANIFEST.sha256` | legal and provenance files (chapters 5, 11, 13) | the build only |
| `unins000.exe` | Inno uninstaller (chapter 10) | the installer |

**Data tree, `DATA_DIR = %LOCALAPPDATA%\DeskIT\`** — everything personal, one folder to find and one to delete (D1). `%LOCALAPPDATA%` and not `%APPDATA%` because `%APPDATA%` roams under a domain profile and voice data must never roam to a company server; `arch-A §2` proposed a `%APPDATA%` config split and it was rejected for roaming and for "two folders to explain" (D1).

| Path under `DATA_DIR` | Contents | Today's location (map citation) |
|---|---|---|
| `settings.toml` | user overrides only (3.4) | `config.toml` beside the code, `main.py:324, 5859` (`map/core` "Personal data stores") |
| `state.json` | per-machine state (3.4) | the same `config.toml`, written by cards (`main.py:1420-1505`, `map/ui` rec 2) |
| `consent.json` | every consent given (chapter 5) | did not exist |
| `vocab.json` | learned vocabulary | `main.py:338` |
| `review.json` (+ `review.lock`) | second-reading proposals | `main.py:2084, 2416` |
| `problems.json`, `problems\`, `problems\outbox\` | reports, pinned evidence, queued uploads (chapter 7) | `main.py:364, 3525, 3862` |
| `lookup_cache.json` | lookup cache | beside the code (`.gitignore:16`) |
| `notify.json`, `logs\notify.log` | notify door store and log | `main.py:687` |
| `logs\app.log*`, `logs\transcripts.log*`, `logs\network.log`, `logs\awake.log` | logs (chapter 4 splits them; `network.log` is chapter 5's window) | `main.py:5653-5665`, `main.py:6175` |
| `audio\recent\`, `audio\pending\` | the recent ring and the refused spool | `main.py:356, 351`; `spool.py:75` |
| `corpus\`, `corpus\read\` | opt-in voice corpus (off by default, chapter 4) | `review.py:914`, `study.py:556`, `main.py:370` |
| `models\<org>--<repo>\` | the Hebrew model snapshot (chapter 6) | `%USERPROFILE%\.cache\huggingface\hub` (`map/core` "Personal data stores") |
| `packs\gpu\`, `packs\recording\`, `packs\skin\` | pip `--target` installs (chapter 6) | did not exist (`.venv`) |
| `phone\` | `cert.pem`, `peers.json` (chapter 12) | `server_token.txt` beside the code, `server.py:69, 111` |
| `secrets\*.bin` | DPAPI files (3.6) | `.env` beside the code, `apikey.py:18` |
| `cache\`, `tmp\` | HF metadata, per-process temp copies (the `notify_watch` copy goes here, `map/owner` rec 8) | `%TEMP%` and beside the code |
| `awake_state.json` | wake-hold state | `main.py:487` |

Pictures and clips: `FOLDERID_Pictures\DeskIT` and `FOLDERID_Videos\DeskIT` via `SHGetKnownFolderPath` (D1), replacing the owner's absolute `capture.folder`, `camera.folder` and `clip_folder` (`config.toml:788, 796, 999`).

Gone from both trees: `.setup-done` (becomes `state.json: setup_done`, `firstrun.py:65, 683-688`), `.env`, `server_token.txt`, `problems.md`, `questions.json`, `cues\.recipe`, the `.vbs` launchers and `.venv` (chapter 10).

## 3.2 `paths.py`: one module, three roots

A new module `paths.py`, imported first by `main.py`, `dashboard.py` and `notify_hook.py`, resolves once at import and exposes constants only — no function takes a "where" argument any more:

| Name | Meaning |
|---|---|
| `APP_DIR` | folder containing `main.py` (`Path(__file__).resolve().parent`, as `main.py:34` does today) |
| `DATA_DIR` | `%LOCALAPPDATA%\DeskIT` — or `APP_DIR` in portable mode (3.7) |
| `PICTURES_DIR`, `VIDEOS_DIR` | the known folders + `\DeskIT` |
| `PORTABLE`, `DEVELOPER` | the two booleans of 3.7 |
| named sub-paths | `SETTINGS_FILE`, `STATE_FILE`, `CONSENT_FILE`, `LOGS_DIR`, `RECENT_DIR`, `PENDING_DIR`, `CORPUS_DIR`, `MODELS_DIR`, `PACKS_DIR`, `PHONE_DIR`, `SECRETS_DIR`, `CACHE_DIR`, `TMP_DIR`, `PROBLEMS_DIR`, `OUTBOX_DIR` |

`paths.ensure()` creates the data sub-folders on first use (called once from `main.py` before `setup_logging()`, so the `app.log` open at `main.py:5653` never hits a read-only folder — fresh-machine failure item 2 in `map/core`). An environment override `DESKIT_HOME` (`map/owner` rec 2) redirects `DATA_DIR` for tests, so the product test-suite never touches the tester's real data folder (the hidden-desktop rule of chapter 15 applies to the GUI tests).

## 3.3 Call sites to rewrite

Every `APP_DIR / "<store>"` write becomes the matching `paths.*` constant. The list is the union of the five maps (D1 evidence); an implementer greps for `APP_DIR /` afterwards and must find only `fonts`, `skin`, `icon`, `cues`, `defaults.toml`.

| File | Lines (map citation) | What lives there |
|---|---|---|
| `main.py` | `324, 338, 351, 356, 364, 370, 401, 487, 687, 2084, 2416, 3525, 3862, 5654, 5661, 5675, 5732, 5743, 5807, 5859, 6333` (`map/core` rec 1); `34` (`map/learning` rec 1) | config path, vocab, pending, recent, problems, corpus\read, questions, awake, notify, review, logs, temp copies |
| `dashboard.py` | `213-215, 461, 887, 3626, 3822, 3826, 3879, 3941, 5519, 6479, 6483, 6514` (`map/ui` rec 3; `map/learning` rec 1) | its own reads of the stores; the FILES card (`7401-7438`) becomes the "where my data lives" row of Your data (chapter 4) |
| `firstrun.py` | `52-53, 65` (`map/core` rec 1, `map/learning` rec 1) | config path, `.setup-done` |
| `server.py` | `69, 111` (`map/core` rec 1) | `server_token.txt` → `phone\` (chapter 12) |
| `apikey.py` | `18-19` | `.env` → `secrets.py` (3.6) |
| `cues.py` | `21` | cue folder → `APP_DIR\app\cues` (read-only, pre-rendered) |
| `history.py` | `27-28` (`map/learning` rec 1) | `transcripts.log` read-back |
| `study.py` | `556, 690, 698, 709` | corpus |
| `review.py` | `914, 1189, 1201, 1214` | corpus, review store |
| `problems.py` | `316` | evidence folder |
| `notify_hook.py` | `54, 370` (`map/owner` rec 2) | token and port (3.9) |
| `versions.py` | `36` | dropped with the file (chapter 7, `version.py`) |

The engines already accept a path at construction (`notify.Engine` `832-852`, `awake.Engine` `960-971`, `problems.record(app_dir…)` `899`, `map/owner` rec 2) — for those the change is only at the `main.py` call sites `364, 487, 687`.

Two writes change shape, not only place: `vocab.py:295-299` writes `vocab.json` non-atomically (`map/learning` risk 10) and adopts the tmp-file-plus-`os.replace` pattern that `review.py:691-696` already uses; `config.py:2412-2432` keeps its per-PID temp file but targets `settings.toml` (3.5).

## 3.4 Config layers: `defaults.toml`, `settings.toml`, `state.json`

`config.load()` merges four layers in this order, later winning (D2): dataclass defaults ← `app\defaults.toml` ← `DATA_DIR\settings.toml` ← `DATA_DIR\state.json`. The result is the same frozen dataclass tree as today, so the ~100 validation rules at `config.py:1932-2280` run unchanged on the merged values.

**`defaults.toml`** is today's `config.toml` (1794 lines, 23 sections, two-thirds comments, `map/packaging` "Configuration") with the owner's values replaced by chapter 4's defaults and the `[tests]` section deleted. It stays the *documentation*: `settings.py` keeps parsing it for rows, help text and `a | b | c` menus (`settings.py:1-28`). The app never writes it; a test asserts its hash is unchanged after a full settings round (see Tests).

**`settings.toml`** holds user overrides only — keys whose value differs from `defaults.toml`. Format, deliberately minimal so a 20-line writer suffices and no TOML round-trip library is ever needed (`map/packaging` "set_values and why a TOML round-trip is forbidden"):

- one assignment per line, dotted `section.key = value`, sorted by section then key;
- value kinds: string (TOML basic string, escaped), integer, float, boolean, list of strings (one line, TOML array) — the only kinds `config.toml` uses today;
- no comments, no tables, no nested tables; a single leading comment line "DeskIT settings overrides — edit with the Settings page; help lives in app\defaults.toml" is the only text;
- read with stdlib `tomllib` (a dotted key parses as a nested table, which is exactly the shape `load()` wants);
- written via per-PID temp file + `os.replace`; `settings.toml.bak` kept from the previous write so an update can never destroy user settings (D21 relies on it);
- an entry whose key no longer exists in `defaults.toml` after an update is kept in the file but ignored with one `app.log` line, never an error (`config_version` migrations in chapter 11 delete or rename them).

**`state.json`** holds per-machine state and is written by the cards' `on_change` handlers (`main.py:1420-1505`), "Move the dot" (`config.py:137-145`), the wizard and the server. Every key that leaves the settings file, with its today's line in `config.toml`:

| `state.json` key | Today | Notes |
|---|---|---|
| `dot.x`, `dot.y` | `config.toml:235-236` | clamped to the current virtual screen at load (`map/owner` rec 10; `config.py:884-893` explains why they were unvalidated) |
| `hint.x`, `hint.y`, `hint.scale` | `265-266, 274` | same clamp |
| `notify.x`, `notify.y` | `[notify]` section (`map/owner` rec 10) | |
| `problems.x`, `problems.y`, `problems.card_x`, `problems.card_y` | `1230-1246` | |
| `shelf.x`, `shelf.y`, `shelf.scale` | `1281-1289` | |
| `review.x`, `review.y`, `review.scale` | `1704-1708` | |
| `audio.device` | `293` (the owner's "Headset Microphone (Arctis 7 Chat), Windows WASAPI") | chosen in the wizard's Microphone step; empty = system default |
| `camera.device` | `963` | |
| `visual_qa.voice` | `659` ("Microsoft Asaf") | empty = first `he-IL` voice at runtime (`map/ui` rec 4) |
| `server.port` | did not exist | the port actually bound (3.9) |
| `setup_done` | `.setup-done` marker + `[setup] done` (`289`) | replaces both; `firstrun.needed()` (`firstrun.py:676-677`) reads it |
| `config_version` | did not exist | integer, drives migrations (chapter 11) |
| `tier`, `tier_checked_at` | did not exist | last probe result shown on Home (chapter 6) |

`state.json` is a flat JSON object with dotted keys, written atomically; a missing or corrupt file means "defaults" and one log line, never a start failure. `hwnd` values never go in (they are session state, `map/learning` risk 13).

The Settings page therefore shows ~183 real settings and no coordinates or device names (`map/ui` rec 2); the `[setup]` section (`config.toml:277-289`) leaves `defaults.toml` entirely.

## 3.5 `config.set_values` and the Settings-page invariants

`config.set_values(updates)` no longer takes a file path. It loads the current override dict, applies `updates`, drops any entry now equal to the default, builds the merged config, runs `load()`'s validation on the merged result (as `config.py:2412-2432` does today on the rewritten file), and only then writes `settings.toml`. Consequences:

- the "no key under `[section]` to write" error at `config.py:2397-2400` and the section-span scanner at `config.py:2318-2337` are deleted — inserting a key into a section is now trivial (D2; `map/ui` rec 1);
- the top-level-append path at `config.py:2405-2410` is deleted with it;
- callers keep their signature minus the path: `main.py:1420, 1451, 1461, 1474, 1505, 1908, 1935, 3649, 3921` and `firstrun.py:639` (`map/core` "Personal data stores"); the ones that write positions or the device call a new `state.set_values` instead (the split follows the table in 3.4);
- `settings.py:53-56` (the page's write path) calls the new `set_values` unchanged in spirit.

Invariants the existing tests hold and must keep holding against `defaults.toml`: every key is drawn once and every key and section has words (`tests.py:19325-19338`, `dashboard.py:7186-7190`, `map/ui` rec 1). `settings.read()` is pointed at `APP_DIR\app\defaults.toml`; the tests' `Path(__file__).parent / "config.toml"` becomes `defaults.toml`. The `[tests]` section and its `WORDS` entries go (chapter 7), so the set equality in `test_every_line_and_every_section_has_plain_words` still holds.

The default drift `map/owner` rec 11 found (`ServerConfig.enabled` disagreeing with the file, `dismiss_on_arrival` in code but not in the file) is fixed while scrubbing: `defaults.toml` is the source of truth for the generated page, and a new test asserts every dataclass default equals the `defaults.toml` value or is listed in a short, justified exception table.

## 3.6 Secrets API (`secrets.py`)

A new module `secrets.py` (the only module besides `net.py` that ever holds a secret value in a variable; chapter 5's static import test enforces the reader set) with three operations per *name*: get, set, delete. Names are fixed strings; the backend is chosen by name (D3):

| Name | Backend | Windows target / file | Why |
|---|---|---|---|
| `groq` | Credential Manager, `win32cred.CredWrite/CredRead/CredDelete`, generic credential, user persistence | `DeskIT/groq` | visible and deletable in Control Panel > Credential Manager — part of the proof (D12) |
| `gemini` | Credential Manager | `DeskIT/gemini` | same |
| `supabase_session` | DPAPI file, `CryptProtectData` user scope, `CRYPTPROTECT_UI_FORBIDDEN` | `DATA_DIR\secrets\supabase_session.bin` | a session JSON exceeds the ~1280-char Credential Manager cap (`research/keys-privacy` §A) |
| `phone_key` | DPAPI file | `secrets\phone_key.bin` (the TLS private key, chapter 12) | size |
| `phone_tokens` | DPAPI file | `secrets\phone_tokens.bin` (per-phone bearers, chapter 12) | size, one blob |

Rules: `secrets.get(name)` returns a string or nothing; the value is never logged, never cached beyond the process, never written to any other file (chapter 4's redactor also matches "any string equal to a stored secret" — it asks `secrets` for the current values at report time and nothing else). `secrets.delete_all()` exists for "Delete everything on this PC" (chapter 4) and the uninstaller.

Key lookup order for `groq`/`gemini` (replaces `apikey.py:30-52`): Credential Manager → environment variable `DESKIT_GROQ_API_KEY` / `DESKIT_GEMINI_API_KEY` → `.env` beside `main.py` only when `DEVELOPER` or `PORTABLE` is true. The `GOOGLE_API_KEY` alias that silently borrowed a gcloud key is dropped, and so is `CEREBRAS_API_KEY` (`apikey.py:25, 86-92`, `map/learning` rec 10). The Keys page (chapter 5) is the only writer of `groq`/`gemini`; the wizard never asks for a key.

A `--migrate` run imports `.env` values into Credential Manager and deletes `.env` only after the user confirms (3.8). pywin32 is already a dependency (`control.py:56-62`), so no new package is needed.

## 3.7 Portable / DEVELOPER detection

`paths.py` evaluates, in this order, once at import (D4; `arch-B §2`, `arch-A §2`):

1. `DESKIT_PORTABLE=1` in the environment, or
2. a file `portable.txt` beside `main.py`, or
3. a `.git` folder beside `main.py`

⇒ `PORTABLE = True`: `DATA_DIR = APP_DIR`, every store stays exactly where it is today (`recent\`, `vocab.json`, `config.toml` …), the `.env` reader stays, and `settings.toml`/`state.json`/`defaults.toml` are **not** used — the legacy single `config.toml` keeps working through the old line editor kept alive as `config.set_values_legacy` for portable mode only. This is the owner's constraint "his machine keeps working": he drops one empty file and nothing moves.

`DEVELOPER = (APP_DIR / ".git").exists()` gates every owner-only surface: git card, Push/Undo, Stop tests, branch line, `[tests]` rows, Read-aloud tab, `--study/--review/--benchmark` (chapter 7 lists the dashboard line ranges). `DEVELOPER` implies `PORTABLE`; the reverse is not true (a user may run a portable copy from a USB stick without owner UI).

Open point 1 records the one divergence this creates and how it is bounded.

## 3.8 `deskit --migrate`

An explicit command, never automatic (D4), offered as a sentence on the dashboard Home when the installed build is told where the legacy folder is (`deskit --migrate <legacy folder>`), and runnable from the checkout itself. Steps, each logged to `app.log` as a count, none quoting content:

1. **Refuse if the app is running** — the mutex (`singleton.py:132-137`) is checked first; the cross-store ids below must not move under a live process.
2. **Move the joined stores as a unit** (`map/learning` risk 9 and "Personal data stores" last paragraph): `recent\` → `audio\recent\`, `review.json` + `review.lock`, `problems.json` + `problems\`, `corpus\` (+ `corpus\read\`), `pending\` → `audio\pending\`. The `recent\` wav stem is the `review.json` item id (`review.py:867`) and the report's `dictation.id`, and `corpus\` files keep the `recent\` name they were copied from (`study.py:499`) — file names are never rewritten, so the joins survive by construction. A move is copy-then-verify-then-delete per store, and the whole step is all-or-nothing: if any store fails to copy, everything copied so far is removed from `DATA_DIR` and the legacy folder is untouched.
3. **Move the singletons**: `vocab.json`, `lookup_cache.json`, `notify.json`, `awake_state.json`, `transcripts.log*`, `app.log*`, `notify.log`, `awake.log` (into `logs\`). `vocab.json.bak-*` copies are left behind and reported (owner artefacts, `map/learning` "Personal data stores").
4. **Import secrets**: each of `GROQ_API_KEY`, `GEMINI_API_KEY` from `.env` → `secrets.set`; `CEREBRAS_API_KEY` is reported as "no longer used"; `server_token.txt` is reported as retired (chapter 12 issues per-phone tokens). `.env` is deleted only after a y/n confirmation on the console.
5. **Diff config**: load legacy `config.toml` with `tomllib`, compare every key to `defaults.toml`; state keys (3.4 table) go to `state.json`, everything else that differs goes to `settings.toml`; keys the new build no longer has (`[tests]`, `cerebras_*`, `lookup.dwell_ms`, `backend = "fake"`) are listed on the console and dropped; absolute capture folders are kept as overrides only if the folder exists. `setup_done = true` is written, so the wizard does not run.
6. **Bump store versions**: `vocab.json` and `review.json` gain/keep a `"version"` field with a migration hook (`map/learning` rec 12), so a later engine change can re-decode once.
7. **Print the summary** (counts per store, the new folder path) and exit; a second run finds nothing to move and says so.

The routine never touches the Whisper snapshots in `%USERPROFILE%\.cache\huggingface`; chapter 6's first start downloads into `models\` (an owner-only shortcut for reusing the old cache is open point 4).

## 3.9 Collision-proof names

Two copies of DeskIT on one PC (installed build + dev checkout, or two Windows users on a per-machine install) must not fight (D5; `map/packaging` rec 9 and risk 7; `map/ui` rec 10):

| Object | Today | Target |
|---|---|---|
| Control pipe | `\\.\pipe\DeskIT.control` (`control.py:43`) | `\\.\pipe\DeskIT.control.<session-id>`; the session id from `ProcessIdToSessionId` |
| Mutex and events | `Local\DeskIT.instance`, `.quit`, `.dashboard`, `.dashboard.show` (`singleton.py:24-31`) | unchanged — `Local\` is already per logon session |
| Loopback port | fixed `127.0.0.1:8756` (`server.py:638-639`) | try 8756, then the next free port; the bound port is written to `state.json: server.port`; `notify_hook.py:365-374` reads it from there instead of `config.toml` |
| `notify_watch` temp copy | one fixed name in `%TEMP%` | `DATA_DIR\tmp\notify-<pid>.db` (`map/owner` rec 8) |
| AppUserModelID | `Yoav.DeskIT` (`main.py:67`) | `DeskIT.App`, also set on the shortcut so Task Manager and the taskbar say "DeskIT" |
| Task Manager name | `pythonw.exe` | the shortcut/launcher description "DeskIT" (chapter 10) |

The hook and the phone (chapter 12) are the only consumers of the port; both learn it from `state.json` or the pairing QR, never from a constant.

## 3.10 Build-from-`git archive` forbidden-files check

The installer is built from `git archive` of the tag, never from a working folder (`map/learning` rec 11; `map/packaging` risk 2). Chapter 10's workflow adds a step that fails the build if the archive or the assembled tree contains any of:

`.env`, `vocab.json`, `vocab.json.bak-*`, `review.json`, `review.lock`, `transcripts.log*`, `app.log*`, `notify.log`, `awake.log`, `recent\`, `pending\`, `corpus\`, `problems\`, `problems.json`, `problems.md`, `problems.lock`, `questions.json`, `questions.lock`, `.setup-done`, `server_token.txt`, `lookup_cache.json`, `notify.json`, `awake_state.json`, `config.toml` (only `app\defaults.toml` may exist), `portable.txt`, `.git`, `.agents\`, `.claude\`, and every file on chapter 7's dev-only manifest.

The same list is the `.gitignore` audit the owner runs once by hand (chapter 16 adds `questions.json`, `questions.lock`, `.agents/`).

## Acceptance

- On a clean Windows 11 VM the installed build starts, creates `%LOCALAPPDATA%\DeskIT\` with the sub-folders of 3.1, and writes nothing under `APP_DIR` (verified by comparing `MANIFEST.sha256` before and after an hour of use).
- On the owner's checkout with `portable.txt` present, `git status` shows no new or moved files after a full session; `.env` still supplies keys; the dashboard shows the git card.
- `deskit --migrate` on a copy of the owner's folder produces a `DATA_DIR` in which every `review.json` id and every report `dictation.id` still resolves to a file in `audio\recent\` or `problems\`.
- The Settings page shows no `x`, `y`, `scale`, `device` or `voice` rows; changing a hotkey writes one line to `settings.toml` and leaves `defaults.toml` byte-identical.
- The Groq and Gemini keys appear as `DeskIT/groq` and `DeskIT/gemini` in Control Panel > Credential Manager and nowhere on disk.
- Two DeskIT processes in one session (installed + portable) both start; the second binds a different port and its own pipe.

## Tests to add

| Test | Asserts |
|---|---|
| `test_paths_portable_when_marker_present` | with `portable.txt` beside `main.py`, `DATA_DIR == APP_DIR` and `PORTABLE` is true; without it and with `DESKIT_HOME` set, `DATA_DIR` is that folder |
| `test_paths_developer_requires_git` | `DEVELOPER` is true only when `.git` exists; `DEVELOPER` implies `PORTABLE` |
| `test_no_app_dir_store_writes` | static grep over the product tree: every `APP_DIR /` occurrence names one of `fonts`, `skin`, `icon`, `cues`, `defaults.toml` |
| `test_config_layers_merge_order` | a key set in all four layers resolves to the `state.json` value; one set only in `settings.toml` beats `defaults.toml`; one absent everywhere equals the dataclass default |
| `test_settings_toml_holds_only_overrides` | after `set_values` with a value equal to the default, the key is absent from `settings.toml`; after a different value, exactly one dotted line exists |
| `test_settings_toml_roundtrip_all_kinds` | strings with quotes and Hebrew, ints, floats, booleans and string lists survive write → `tomllib` read |
| `test_defaults_toml_never_written` | hash of `defaults.toml` unchanged after every settings write the dashboard can make |
| `test_set_values_creates_missing_section` | writing `newsection.key` on a fresh `settings.toml` succeeds and reads back |
| `test_set_values_validates_before_write` | an invalid value leaves `settings.toml` untouched and raises `ConfigError` |
| `test_unknown_override_key_is_ignored` | a stale key in `settings.toml` yields one log line and a normal config |
| `test_state_keys_never_in_settings` | every key of the 3.4 state table is rejected by `config.set_values` and accepted by `state.set_values` |
| `test_state_positions_clamped_to_screen` | an off-screen `x/y` in `state.json` is replaced by an on-screen position at load |
| `test_settings_page_no_coordinates` | `settings.read(defaults.toml)` contains no key named `x`, `y`, `scale`, `device`, `voice`, `done` |
| `test_dataclass_defaults_match_defaults_toml` | every dataclass default equals `defaults.toml` or sits in the justified exception table |
| `test_secrets_backend_by_name` | `groq`/`gemini` go through the Credential Manager shim (mocked), `supabase_session`/`phone_*` through DPAPI files under `secrets\` |
| `test_secrets_lookup_order` | Credential Manager beats `DESKIT_*` env, env beats `.env`, `.env` is read only when `PORTABLE`; `GOOGLE_API_KEY` and `CEREBRAS_API_KEY` are never read |
| `test_secrets_never_on_disk_in_data_dir` | after set/get of fixture keys, a grep of `DATA_DIR` (excluding `secrets\*.bin`, which are verified to be DPAPI blobs) finds no key-shaped string (shared with chapter 5 lock 1) |
| `test_migrate_moves_joined_stores_as_unit` | a fixture legacy folder with a `recent\` clip, its `review.json` item and a report referencing it migrates with all three ids still resolving; a forced copy failure leaves `DATA_DIR` empty and the legacy folder intact |
| `test_migrate_config_diff` | a legacy `config.toml` differing in three keys and two positions yields exactly three `settings.toml` lines and two `state.json` keys, with `setup_done` true and `[tests]` dropped |
| `test_migrate_refuses_while_running` | with the instance mutex held, `--migrate` exits non-zero without touching files |
| `test_migrate_is_idempotent` | a second run reports nothing to move |
| `test_vocab_save_is_atomic` | a write interrupted after the temp file leaves the previous `vocab.json` intact |
| `test_pipe_name_has_session_id` | the control pipe name ends with the current session id |
| `test_port_fallthrough_written_to_state` | with 8756 occupied, the server binds the next free port and `state.json: server.port` equals it; `notify_hook` reads the same value |
| `test_app_id_is_neutral` | the AppUserModelID constant equals `DeskIT.App` |
| `test_build_tree_has_no_forbidden_files` | the assembled build tree (or a `git archive` of HEAD) contains none of the 3.10 names |

## Open points

1. **Portable mode keeps two config code paths** (legacy line editor on `config.toml` vs. the new override writer). D4 rules out "two layouts diverging in behaviour"; the divergence here is only *where* settings are written, not what they mean, and it is bounded by running the product test-suite in both modes in CI. If the owner would rather retire the line editor, portable mode could also use `settings.toml` + `state.json` beside the code — that would move his positions and device out of his `config.toml` once, which D4 currently avoids. Owner's call in phase 1.
2. `map/ui` rec 2 and `map/packaging` rec 2 also list `local.device` and `translate.ollama_url` for `state.json`; D2's list does not. This chapter follows D2 (`local.device` is derived from the tier probe each start per D14; `ollama_url` stays a setting). Noted so nobody adds them silently.
3. `DESKIT_HOME` as a test/override hatch is from `map/owner` rec 2 and is not in D1-D5; it is proposed here because product tests need a data folder that is not the tester's own. If rejected, the tests must monkeypatch `paths` instead.
4. Whether `--migrate` should copy the owner's existing Hugging Face snapshot into `models\` (saves him a 1.6 GB download; D13 pins a revision, so the copy must be that revision) — not covered by D4; chapter 6's call.

- **Resolved by D30 (2026-09-17):** the owner runs two copies side by side — the checkout as `DeskIT Dev` (portable mode, `dev` suffix on mutex/pipe/port/AppID, DEV tag on the dot and the bar) and the released installer as `DeskIT` with its own data folder. On his machine `--migrate` copies instead of moving. The second copy to start pauses the first over its pipe and resumes it on exit.

---


# 4. Per-user data, privacy defaults, retention and deletion

This chapter implements D6 (what ships ON and OFF), D8 (support-safe logs and the redactor) and D9 (the "Your data" page and delete-means-delete). It assumes chapter 3's layout (every store under `DATA_DIR`, keys in Credential Manager) and hands the consent cards that turn the OFF features on to chapter 5, the hardware-dependent defaults to chapter 6, the report v2 card to chapter 7 and the page's visual spec to chapter 9. The numbers here are what `app\defaults.toml` ships; the owner keeps his own values as overrides in portable mode (chapter 3, 3.7).

## 4.1 What ships ON and OFF: the default table

Every row names the `defaults.toml` key, the value it ships, and the owner's current value in `config.toml` (line cited) that it replaces. "Consent card" means the key cannot be flipped on by the Settings page alone — the card of chapter 5 flips it and records `consent.json` (D7).

**Ships ON — local, no egress (D6):**

| Key | Ships | Owner today | Why / note |
|---|---|---|---|
| `audio.backend` | `"local"` | file `"local"` (`config.toml:196`); dataclass `"gemini"` (`config.py:1219`) | the dataclass default is fixed to `"local"` so a missing file can never route audio to Google (`map/cloud` rec 4) |
| `vocab.enabled` | `true` | `true` (`1321`) | learned vocabulary stays; it never leaves the PC unless a cloud-text gate is open |
| `vocab.keep_audio` | `20` | `50` (`1339`) | the recent ring; `arch-B §3` argued 10, `arch-A §3` 20 — D6 settles on 20; revisit after first users |
| `[history] keep_days` (new) | `30` | no such key; `RotatingFileHandler(1 MB × 3)` at `main.py:5660-5665` | 4.2 |
| `review.enabled` | `true` (effective only when the tier probe says CUDA, chapter 6) | `true` (`1694`) | `map/learning` rec 5: the guard at `main.py:2077-2080` gains `transcriber.device == "cuda"` |
| `[review] keep_audio` (new) | `3` | no such key | 4.2 — decouples the second reading from the history switch (`map/learning` risk 5) |
| `hint.enabled`, `dot`, `shelf` | `true` | `true` (`253`, `1265`) | the cards; their positions leave the file (chapter 3, 3.4) |
| `capture.enabled` | `true` | `true` (`765`) | |
| `capture.capture_hotkey` | `"ctrl+f11"` | `"win+shift+s"` (`767`) | never the Windows key by default (`map/capture` rec 1; D25); a Snipping Tool toggle is chapter 9 screen 13 |
| `capture.always_save` | `false` | `false` (`854`) | |
| `capture.audio` | `"off"` | `"off"` (`891`) | screen recordings silent by default; the key's own help already says "OFF BY DEFAULT ON PURPOSE" |
| `camera.enabled` | `true` | `true` (`957`) | |
| `capture.folder`, `camera.folder`, `capture.clip_folder` | `""` = `Pictures\DeskIT`, `Videos\DeskIT` | absolute owner paths (`788, 796, 999`) | chapter 3, 3.1 |
| `[updates] check` (new, chapter 11) | `true` after the wizard asks once | no such key | GET only, no identifier; consent kind `update_check` (D7) |
| `problems.enabled` | `true` | `true` (`1200`) | reports are local by default; "Send to the developer" is per report (chapter 7) |
| `problems.keep_audio` | `true` | `true` (`1216`) | the pinned copy stays on this PC; upload of it is a per-report tick (D16) |

**Ships OFF until a consent card (D6, D7):**

| Key | Ships | Owner today | Consent kind |
|---|---|---|---|
| `polish.prefer` | `"ollama"` | `"groq"` (`1476`) | `cloud_text` — with `polish.when` kept at `"always"` (`1466`) the pass simply finds no backend until Ollama is detected or the gate opens |
| `punctuate.prefer` | `"ollama"` | `"ollama"` (`445`) | `cloud_text` |
| `translate.prefer` | `"ollama"` | `"groq"` (`361`) | `cloud_text` |
| `lookup.cold_to_gemini` | `false` | `true` (`480`) | `cloud_text` |
| `lookup.cache_entries` | `0` | `500` (`544`) | none — it is local, but a cache of "what you selected and read" is a store the user should choose; when on, 7-day expiry (`arch-B §3`) |
| `review.llm_per_day` | `0` | `200` (`1743`) | `cloud_text` |
| `study.llm_per_day` | `0` | `60` (`1395`) | `cloud_text` |
| `study.enabled` | `false` | `true` (`1388`) | local switch in Settings > Privacy, no card; needs the GPU tier (chapter 6) |
| `study.corpus_keep` | `0` | `400` (`1400`) | local switch with a disk + privacy sentence; the Read-aloud tab stays hidden while 0 (`map/learning` rec 5); read-aloud is a v1 cut (D27) |
| `visual_qa.allow_screenshot_upload` | `false` | `false` (`598`) | `cloud_screenshots` |
| `visual_qa.prefer` | `"ollama"` | `"ollama"` (`606`) | `cloud_text` for the key route; without Ollama the three-button card (chapter 6) |
| `notify.enabled` | `false` | `true` (`1094`) | none — "Connect Claude Code" in Settings (chapter 7) |
| `notify.watch` | `"off"` | `"cowork"` (`1144`) | none; the OS toast DB is never copied unless a `Claude_*` package exists (D15) |
| `server.enabled` | `false` | `true` (`1305`) | none — turned on by pairing a phone (chapter 12) |
| `awake.hold` | `false` | `true` (`1042`) | asked once in the wizard's Optional extras step |
| `awake.vitals_minutes` | `0` | `10` (`1062`) | |
| `awake.pin_timeouts` | `false`, under Advanced | `false` (`1071`) | help gains "changes the Windows power plan; restored on exit" (`map/owner` rec 9) |
| `[privacy] account`, `report_upload`, `settings_sync` (new, chapter 5) | `false` | did not exist | `account`, `report_upload`, `settings_sync` |
| `[privacy] offline` (new) | `false` | did not exist | the Offline switch of D12 |

Hardware-dependent keys (`local.compute_type`, `local.beam_size`, `local.cpu_threads`, the English detector, tier-appropriate Ollama models) are chapter 6's table, not this one.

## 4.2 New keys: `[history]` and `[review] keep_audio`

**`[history]`** — a new section in `defaults.toml` with one key, `keep_days = 30` (0 = off), and help text that says in plain words what `transcripts.log` is: every sentence you dictated, corrected, translated, punctuated or looked up, kept so the Recent view (`history.py`) and the clipboard-recovery path work. Behaviour:

- `transcripts.log` switches from size rotation (`main.py:5660-5665`) to daily rotation with a date suffix; at start and once a day, files older than `keep_days` are deleted; `keep_days = 0` means the handler is not installed at all and `history.py:27-28` shows an empty Recent view with the sentence "History is off (Settings > Privacy)";
- the recovery message at `main.py:5378-5381` ("Raw backend return goes to the log BEFORE any guard decides not to paste it — this file is the recovery path") is reworded when history is off: the clipboard fallback hint no longer promises the log (`map/learning` rec 8);
- `keep_days` is a retention picker on Settings > Privacy (chapter 9 screen 4): Off / 7 / 30 / 90 / 365.

**`[review] keep_audio = 3`** — the second reading keeps its own tiny ring of the last three clips inside `audio\recent\` (same spool, a floor rather than a second folder): the `Spool` at `main.py:356-357` is built with `keep = max(vocab.keep_audio, review.keep_audio if review is on)`, so `vocab.keep_audio = 0` no longer removes the engines (`main.py:356-357, 2078, 2096`; `map/learning` risk 5, rec 6). The Your data row for recordings says "3 kept for the second reading" when the user has set history to 0 and the second reading is on. The `--drain` console note at `main.py:5738-5739` reads the same effective number.

## 4.3 What is removed from the shipped defaults

While `config.toml` becomes `app\defaults.toml` (chapter 3, 3.4), the scrub removes (D6):

| Removed | Where today | Replacement |
|---|---|---|
| the Cerebras path | `config.toml:1519-1532`; `translate.py:376-525`; `apikey.py:25, 86-92` | none (`map/learning` rec 10) |
| `lookup.dwell_ms` | `522` ("DEAD. Nothing reads this any more") | deleted |
| `backend = "fake"` | `196` comment; `settings.py:271-273` `_ENGINES` | `fake` stays a test double reachable only when `DEVELOPER` (`map/ui` rec 4) |
| `[tests]` section | `1755-1794` | deleted; `WORDS` entries go with it (chapter 7) |
| `vocab.terms` seeds | `1354` (`HebrewDictation`, `Massif`, `TripSync`, `Cowork`; `map/learning` risk 4) | `[]`; the wizard's "names and terms you use" step is **not** added in v1 — the vocabulary learns from corrections (`map/learning` rec 3 proposed the step; D18's wizard has no such step, so it is an open point) |
| owner coordinates | `[dot]`, `[hint]`, `[notify]`, `[problems]`, `[shelf]`, `[review]` x/y/scale | `state.json` (chapter 3, 3.4) |
| absolute folders | `788, 796, 999` | known folders |
| microphone and voice names | `293`, `659` | `state.json`, empty by default |
| `[setup] done` | `289` | `state.json: setup_done` |
| the "this machine's projects" comment block | `config.toml:1343-1358` | neutral help |

The generic dev-jargon `local.initial_prompt` default (`config.py:271-273`) is kept as shipped (`map/learning` rec 3).

## 4.4 Log split: support-safe `app.log`

Rule (D8): `app.log` never quotes dictated text, learned pairs, phone URL or token; quoted text lives only in `transcripts.log`. The four call sites that quote today (`map/learning` rec 8; `arch-B §3`), verified in the repo on 2026-09-16:

| Site | What it logs today | Change |
|---|---|---|
| `main.py:4551-4552` | "learned N correction(s): heard -> meant …" | `app.log` keeps the count only; the pairs move to `transcripts.log` as a `LEARNED` record |
| `main.py:5205-5206` | "context pass (by, s) changed: <polished text>" | `app.log` keeps backend and seconds; the text is already in `transcripts.log` as `POLISHED` (`main.py:5202`) — drop it here |
| `study.py:649-650` | "study of <wav> learned N pair(s): …" | count only; the pairs already go to `transcripts.log` as `STUDIED` at `study.py:647` |
| `review.py:1053-1054` | "second reading of <wav> proposes N change(s): <changes>" | count only; `review.py:1141` (the accepted reading) likewise — the proposal is in `review.json` and `transcripts.log` `REVIEW` |

Also: `server.py:653-654` logs "open this on the phone: https://<host>/#t=<token>" — becomes the host only (`map/phone` rec 3; the token route itself is replaced in chapter 12). The wav file *name* (a timestamp stem) may stay in `app.log`; it is not content. Device names (`map/core` "Personal data stores": `app.log` carries device names and the tailnet name) are allowed — they are what support needs — except the tailnet host, which is logged only in `DEVELOPER` mode.

`transcripts.log` keeps every record kind it has (`OK`, `PHONE`, `ERROR`, `DISCARDED`, `CORRECTED`, `TRANSLATE-IN/OUT`, `PUNCTUATE-IN/OUT`, `LOOKUP-IN/OUT`, `POLISHED`, `REVIEW`, `DRAINED`, `STUDIED`; `map/core` "Personal data stores") plus `LEARNED`, and gains the retention of 4.2. `notify.log` rotates at 512 KB (D15) and `notify.json` bodies never attach to reports.

A guard test (Tests) runs a scripted dictation with a marker sentence through every path (paste, correct, polish, review, study, lookup, phone) and asserts the marker never appears in `app.log`.

## 4.5 The redactor

`redact.py`, one function applied to every string a problem report (chapter 7), `--diagnose` (chapter 14) or an export note attaches, and to the settings snapshot (D8; `research/keys-privacy` §C.5). Patterns, each replaced by a fixed placeholder that names the kind (`[redacted:gemini-key]` etc.) so the owner can still see *that* a key was present:

| Pattern | What it catches |
|---|---|
| `#t=[0-9A-Za-z_-]+` | the legacy phone URL fragment |
| `AIza[0-9A-Za-z_-]{30,}` | Google API keys (D8 uses a permissive length on purpose; `arch-B §3` gave the exact 35) |
| `gsk_[0-9A-Za-z]{20,}` | Groq keys |
| `sk-[0-9A-Za-z_-]{20,}` | OpenAI-style keys pasted by mistake |
| `sb_publishable_…`, `sb_secret_…`, `eyJ[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+` | Supabase keys and any JWT (the session) |
| `Bearer [^\s]+` | any bearer header |
| any string equal to a value `secrets.get` returns for a known name | belt and braces: even a key that matches no pattern |
| (not a pattern) file paths containing the Windows user name | deliberately left alone — whether a path is attached at all is `problems.env()`'s whitelist decision (chapter 7), not the redactor's |

The redactor never sees dictated text unless the user ticked "Transcript text" on the report card; when it does, it still runs (a key can be dictated). It is pure, deterministic, and the same module the lock-4 report test of chapter 5 exercises.

## 4.6 Settings > Your data

A dashboard tab (chapter 9 screen 5 gives the layout) that replaces the FILES card (`dashboard.py:7401-7438`, `map/ui` rec 3) with one row per store: name in plain words, path, size on disk, oldest item's date, and one button. The rows and exactly what each button deletes (D9; `map/learning` rec 7; `map/owner` rec 5):

| Row | Files | Button | What it does |
|---|---|---|---|
| Learned words | `vocab.json` | Forget a word… | opens the list of (heard → meant) pairs with hits and last date; Forget calls a new `Vocab.forget(heard)` and the now-atomic save (chapter 3, 3.3); today no forget exists and the dashboard never writes `vocab.json` (`map/learning` risk 2) |
| History | `logs\transcripts.log*` | Clear history | deletes all rotated files, re-opens an empty one; the Recent view empties |
| Recordings | `audio\recent\`, `audio\pending\`, `corpus\`, `corpus\read\` | Delete recordings | removes wav + json; `review.json` items whose clip is gone are dropped in the same step (their id is the wav stem, `review.py:867`); pinned copies under `problems\` are *not* touched here — that is the reports row |
| Second-reading proposals | `review.json` | Delete proposals | empties the store (`review.Store` keeps 300 decided today, `map/learning` "Personal data stores") |
| Reports | `problems.json`, `problems\`, `problems\outbox\` | Delete reports | `remove(purge=True)` for every row: unlinks the pinned wav/json/jpg when no other report references them (today `problems.py:866-875` deliberately leaves the evidence on disk); queued outbox items are deleted unsent; a report already sent is only removed locally — the copy on the developer's side is covered by "Delete my account" |
| Lookups | `lookup_cache.json` | Delete lookups | deletes the file |
| Notifications | `notify.json`, `logs\notify.log` | Delete notifications | deletes both |
| Speech model | `models\` | Delete the model | removes the snapshot; the next start offers the download again (chapter 6) |
| Optional packs | `packs\` | Remove packs | removes the pip `--target` folders; the tier re-probe falls to CPU with the visible card (chapter 6) |
| Screenshots and clips | `Pictures\DeskIT`, `Videos\DeskIT` | Open folder | never deleted by the app — they are the user's files in the user's folders |
| Logs | `logs\app.log*`, `logs\network.log`, `logs\awake.log` | Clear logs | deletes; `network.log` is append-only while the app runs, so this is the only way it shrinks |
| Everything | the folder | Delete everything on this PC | 1) `secrets.delete_all()` — the two Credential Manager entries and `secrets\*.bin`; 2) the `HKCU\…\Run` value if Start with Windows is on (chapter 10); 3) the two Claude Code hook entries via `notify_hook --uninstall-hook` if installed (D15); 4) the whole `DATA_DIR`; 5) the app exits and the next start is a first run. Two-press confirmation like the report row today (`dashboard.py:4545-4575`) |
| Account | (server side) | Delete my account | the `delete_me()` RPC of chapter 8, then the local session file; disabled with "no account" when `[privacy] account` is false |
| Where my data lives | — | Open folder | `os.startfile(DATA_DIR)` (`launch.py:78`) |

Sizes are computed on tab open in a worker and cached for the session; a store that does not exist shows "empty". Every delete is logged to `app.log` as a count, never as content. Each button's help repeats the retention rule of its store, so this page is also the in-app retention notice the privacy policy points at (chapter 13).

## 4.7 Export format

"Export everything" (D9) writes `DeskIT-export-<YYYY-MM-DD>.zip` to a folder the user picks. Contents: the `DATA_DIR` tree **except** `models\`, `packs\`, `cache\`, `tmp\` and `secrets\`, plus an `export.json` at the root with `{app_version, exported_at, tier, stores: {name: {files, bytes, oldest}}}` and a `README.txt` (Hebrew and English, from the guide) explaining each folder. Keys are never exported — the zip is meant to be moved to another PC or handed to nobody; a test greps it for key-shaped strings. The export is not an import: on the other PC the user copies the folders into the new `DATA_DIR` by hand (documented in the guide's Your data chapter); an in-app import is not in v1.

## 4.8 Uninstall behaviour

The Inno uninstaller (chapter 10) asks one question, default unticked: "Remove my data too? (settings, learned words, history, recordings, reports, the speech model — the folder %LOCALAPPDATA%\DeskIT)". Ticked = the same five steps as "Delete everything on this PC"; unticked = the folder stays and the guide says where it is. Either way the uninstaller removes the `HKCU\…\Run` value and the hook entries, because those point at files it is deleting. The Store build's uninstall cannot ask; the guide names the folder (`arch-A §3`).

## 4.9 The retention sentence the guide prints

Chapter 14's Your data chapter prints, verbatim and kept in sync with `defaults.toml` by a test:

> Audio: the last 20 recordings (or off, then 3 for the second reading) · History: 30 days (or off) · Learned words: until you forget one · Reports: on this PC until you delete them; on the developer's side 12 months after you pressed Send · Lookups: off (7 days when on) · The speech model: until you delete it · Nothing on any server unless you pressed Send or turned on sync.

## Acceptance

- A fresh install dictates a marker sentence through every feature that is on by default; `logs\network.log` shows only loopback (chapter 5's window) and `app.log` does not contain the marker.
- `defaults.toml` contains no owner value: no absolute path, no device or voice name, no coordinate, no `vocab.terms` entry, no `[tests]`, no `cerebras`, no `dwell_ms`.
- Settings > Your data shows every store of 4.6 with a size; every button empties exactly the files in its row and nothing else; "Delete everything on this PC" leaves no `DeskIT/*` credential, no `DeskIT` `Run` value, no hook entry, and no `%LOCALAPPDATA%\DeskIT` folder.
- With history set to Off and the second reading on, the recent ring holds exactly 3 clips and the second reading still proposes.
- The redactor turns every fixture key in a report preview into a placeholder.
- The guide's retention sentence equals the one generated from `defaults.toml`.

## Tests to add

| Test | Asserts |
|---|---|
| `test_defaults_toml_ships_privacy_values` | every key of the 4.1 tables reads back from `defaults.toml` with the shipped value |
| `test_dataclass_backend_default_is_local` | `AudioConfig.backend` default is `"local"` (`config.py:1219`) |
| `test_defaults_toml_has_no_owner_values` | no absolute `C:\` path, no `Arctis`, no `Asaf`, no `x`/`y`/`scale` assignment, empty `vocab.terms`, no `[tests]`/`[setup]` section, no `cerebras`, no `dwell_ms` |
| `test_history_keep_days_prunes` | with `keep_days = 7` and fixture files dated 8 and 6 days ago, the older one is deleted at start and the younger kept |
| `test_history_off_installs_no_handler` | `keep_days = 0` → no `transcripts.log` created after a dictation; Recent view shows the "History is off" sentence |
| `test_review_ring_floor` | `vocab.keep_audio = 0` + review on → the spool keeps 3; `vocab.keep_audio = 20` → 20; review off + 0 → no spool |
| `test_app_log_never_quotes_text` | a marker sentence dictated, corrected, polished, reviewed, studied and looked up never appears in `app.log`; the seven sites log counts |
| `test_transcripts_log_has_learned_record` | after a correction, a `LEARNED` line exists in `transcripts.log` with the pair |
| `test_server_logs_host_only` | the phone-URL log line contains the host and no `#t=` |
| `test_redactor_patterns` | each pattern of 4.5 with a fixture string → placeholder; a plain Hebrew sentence and a wav stem pass through unchanged |
| `test_redactor_matches_stored_secret` | a value returned by `secrets.get` (mocked) that matches no pattern is still replaced |
| `test_your_data_rows_cover_every_store` | the set of paths the page lists equals the set `paths.py` defines minus `models`/`packs`/`cache`/`tmp` exclusions the page names explicitly |
| `test_vocab_forget_removes_pair_atomically` | `Vocab.forget("heard")` drops the entry, saves via temp + replace, and the pair is gone after reload |
| `test_delete_recordings_drops_orphan_reviews` | deleting the ring removes `review.json` items whose id has no clip; pinned copies under `problems\` remain |
| `test_delete_reports_purges_evidence` | `remove(purge=True)` unlinks wav/json/jpg referenced by one report only and keeps files two reports share |
| `test_delete_everything_sequence` | with mocked Credential Manager, registry and hook writer: the two credentials, the `Run` value and both hook entries are removed before the folder, and the folder is gone |
| `test_export_zip_contents` | the zip contains `export.json`, `README.txt`, `settings.toml`, `vocab.json`, `logs\` and `audio\`, and none of `models`, `packs`, `secrets`, `cache`, `tmp`; a grep of every member finds no key-shaped string |
| `test_retention_sentence_matches_defaults` | the sentence generated from `defaults.toml` equals the guide's text file |
| `test_uninstall_question_default_unticked` | the Inno script's task entry for data removal is not `checked` by default (chapter 10 runs it as a script-text assertion) |

## Open points

1. **`capture.system_sound = false`** appears in D6, but `config.toml` has no such key — the recorder's audio key is `capture.audio = "off" | "mic"` (`config.toml:891`). Either D6 means `audio = "off"` (this chapter's reading) or a system-loopback option is planned; chapter 9's Screen tab should not invent a switch for a key that does not exist.
2. **"Names and terms you use" wizard step**: `map/learning` rec 3 proposed it to make `vocab.terms = []` less of a loss; D18's wizard has no such step and D6 ships `[]`. Recommendation: no step in v1, a "Learned words > Add" button on Your data instead (one more button, no consent).
3. **`lookup.cache_entries = 0` disables a purely local cache**; D6 lists it under OFF. If the owner prefers it on (it has no egress), the row still needs its 7-day expiry, which `lookup.py:629` does not implement today.
4. **Report copies already sent**: "Delete reports" removes the local row; the server-side copy goes only with "Delete my account" (D17's `delete_me()`). A per-report "delete on the developer's side too" would need a delete policy on `problem_reports` — chapter 8's call; the guide must say which one applies.
5. **`keep_days` vs. a size cap**: daily rotation with no size cap means a very heavy dictator could grow `transcripts.log` beyond today's 4 MB total; a secondary 50 MB cap is suggested but not in D6.


---

# 5. Cloud passes, keys, consent cards and the key-privacy proof

Implements D7, D10, D11 and D12. It leans on chapter 3 for `secrets.py` and `DATA_DIR`, on chapter 4 for the redactor and the log split, on chapter 6 for the hardware tiers (where the CPU user is offered Groq cloud transcription), on chapter 7 for the report payload, on chapter 8 for the Supabase client, on chapter 9 for the screen layouts and on chapter 14 for the guide chapter that repeats section 5.10. Today's cloud subsystem is inventoried in chapter 2; this chapter only says what changes.

The shape of the change in one paragraph: today keys are read from `.env` beside the code by `apikey.find_key` (`apikey.py:56-62`), five constructors build a network client the moment a feature is configured (`map/cloud` "Every place a key value flows"), and text leaves the machine by default because the owner personally accepted that trade (`polish.py:98-100`, `map/cloud` risk 3). After this chapter, every cloud constructor asks `privacy.allowed(kind)` before it builds, every outbound byte passes `net.py`, the keys live in Windows Credential Manager under the user's own account (D3), and the user can watch the traffic in Dashboard > Network.

## 5.1 The `[privacy]` section and `privacy.allowed()`

A new section in `app\defaults.toml` (chapter 3, D2) and a new module `privacy.py` (appendix A). The keys, all booleans:

| Key | Default | Meaning | Flipped by |
|---|---|---|---|
| `privacy.cloud_text` | `false` | Dictated or selected text may go to Groq / Google under the user's own key | Cloud-text consent card |
| `privacy.cloud_audio` | `false` | Recorded audio may go to Google (`backend = "gemini"`) or Groq (tier-2 offer, chapter 6) | Cloud-audio consent card |
| `privacy.cloud_screenshots` | `false` | A JPEG of the screen region may go to Groq / Google for ask-the-screen | Cloud-screenshots consent card; replaces `visual_qa.allow_screenshot_upload` (`config.toml:599-607`), which `--migrate` (chapter 3) maps onto it |
| `privacy.account` | `false` | The app may create and hold an anonymous Supabase account | Account consent card (chapter 8) |
| `privacy.report_upload` | `false` | Queued problem reports may upload | Report-upload consent card (chapter 7) |
| `privacy.settings_sync` | `false` | `settings.toml` overrides and `vocab.json` may sync (phase 5) | Sync consent card |
| `privacy.update_check` | `true` | One weekly GET to GitHub, no identifier (chapter 11) | The wizard's "Optional extras" switch (D18-1); the first check never runs before `state.json` has `setup_done`, so a user who switches it off in the wizard is never contacted |
| `privacy.offline` | `false` | Refuse every host except loopback (section 5.9) | Settings > Privacy switch, no card |

`update_check` is the only gate that ships on (D6 lists it under ON, "asked once"); every other gate is off until its card (D7). `offline` is not a consent gate but a veto: it overrides all of them.

`privacy.allowed(kind)` is one function with one contract: it returns true only when the `[privacy]` key for `kind` is true, `privacy.offline` is false, and `DATA_DIR\consent.json` holds a row for `kind` whose `text_version` equals the version compiled into the card for that kind. A stale `text_version` (the provider changed its terms, D11) makes the gate read as shut and re-opens the card on the next use. `update_check` and `offline` need no consent row.

`consent.json` is a JSON list of rows `{kind, text_version, when (ISO-8601 local), app_version}`; it is written atomically by `privacy.grant(kind, text_version)` and a row is removed by `privacy.withdraw(kind)`, which also calls every registered tear-down (section 5.3). It is one of the stores chapter 4's "Your data" page lists and "Delete everything on this PC" removes (D9). No other module writes `[privacy]` keys or `consent.json`; the Settings page shows them read-only with the consent date and text version (D18-4) and offers "Withdraw", which calls `privacy.withdraw`. `config.set_values` refuses `privacy.*` keys from the generated Settings page so a config write can never open a gate (this is what "a gate flips only through its consent card" means in code, D7).

Which feature maps to which kind (this table is also the "what each feature sends" list the guide prints, D26):

| Kind | Features and their call sites today |
|---|---|
| `cloud_text` | repair pass `polish.py:285-324` (Groq); punctuation `punctuate.py:230-297` (Groq, Gemini); translate `translate.py:559-607` (Gemini); lookup when `cold_to_gemini` or `prefer = "gemini"` or Ollama failed `lookup.py:827-840`; second reading `review.py:442-520`; study `study.py:285-340`; read-aloud writer `reading.py:397-460` (owner-only after D15); phone `/translate`, `/punctuate`, `/lookup` `server.py:333-411`, `main.py:2433-2497` |
| `cloud_audio` | `GeminiTranscriber` chosen by `backend = "gemini"` `transcribers/__init__.py:45-47`; `--drain` of `pending\` and `--check` `main.py:5972-5983`; the new Groq `whisper-large-v3-turbo` transcriber for tier 2 (chapter 6) |
| `cloud_screenshots` | `GroqVision` and `GeminiVision` in `visual_qa.Chain._builders` `visual_qa.py:986-1004`; the screenshot editor's Ask button `capture.py:6388-6406` inherits it |
| `account`, `report_upload`, `settings_sync` | the Supabase client (chapter 8) and the outbox uploader (chapter 7) |
| `update_check` | the weekly release check (chapter 11) |

## 5.2 Every constructor that must call the gate

The pattern is the one `visual_qa.Chain._builders` already uses and `tests.py:10804-10836` already asserts: the privacy test checks the *built list*, "never against the flag, because a runtime `if` is exactly the kind of guard a refactor silently deletes" (`tests.py:10805-10808`). The constructors below each gain, as their first statement, a call to `privacy.allowed(kind)`; when it is false they raise a new `ConsentRequired(kind)` (a subclass of the module's existing error class, so `polish.py:421-464` "never raises; failure = raw transcript" keeps holding). They also stop calling `apikey.find_key` and ask `secrets.get(name)` (chapter 3) for `(value, source)` so `main.py:6334-6336` keeps logging the source and nothing else.

| Constructor | Where | Kind | Notes |
|---|---|---|---|
| `GeminiTranscriber.__init__` | `transcribers/gemini.py:61-73` | `cloud_audio` | Today raises `TranscriptionError(MISSING_KEY_MESSAGE)` on a missing key and the app fails to start (`main.py:343`); after the change a shut gate or missing key makes `get_transcriber` fall to local with a visible card, never a crash |
| `GeminiTranslator.__init__` | `translate.py:112-138` | `cloud_text` | |
| `GroqTranslator.__init__` (and the base it inherits from) | `translate.py:528-556`, base `translate.py:377-525` | `cloud_text` | `CerebrasTranslator` disappears with the provider (D6); the base class is renamed for what it is, an OpenAI-compatible chat client, and keeps the `deskit/1.0` User-Agent that Cloudflare requires (`translate.py:369-374`) |
| `GroqVision.__init__` | `visual_qa.py:714-900`, key read at `:786-794` | `cloud_screenshots` | |
| `GeminiVision.__init__` | `visual_qa.py:905-960` | `cloud_screenshots` | |
| Groq cloud transcriber (new, chapter 6) | `transcribers/groq.py` | `cloud_audio` | |
| Supabase client (new, chapter 8) | `cloud/supabase_client.py` | `account`; upload and sync calls additionally check `report_upload` / `settings_sync` | |

The lazy chains inherit the guarantee without per-module edits (`map/cloud` rec 3): `punctuate.py:230-297` builds each backend on first press, `polish.py:285-324` on first use, `lookup.py:569-913` on first cold lookup, `translate.Translator` `translate.py:559-607` on first F8. Two call sites need a real edit:

- Start-up warm-ups (`polish.py:364-388`, `lookup.py:753-755`, `visual_qa.py:4329-4335`) must never open a card: they warm only backends whose gate is already open and skip the rest with one INFO line, as the "no key" path does today (`polish.py:337-343`).
- The consent card is opened by the feature's *controller*, not by the constructor: the controller catches `ConsentRequired`, opens the card for that kind once (D7 "the first key press that needs a cloud pass opens the card"), and on [Turn on] retries the same press; on [Not now] it continues with the local fallback and does not ask again until the next process start.

The phone routes (`server.py:333-411`) cannot show a card on the phone; they return the existing error strings and the PC shows the card on its own screen the next time the user presses the key locally (open point 3).

## 5.3 Consent cards per kind

One layout (D18-2), rendered through the existing overlay card path with Hebrew body text via the bitmap renderer (chapter 9): a title, five short blocks (*What leaves*, *To whom*, *Under whose account*, the provider's own sentence per D11, *How to turn it off*) and two buttons [Turn on] [Not now]. Each card carries a `text_version` string (`gemini-2026-04-28`, `groq-2026-06-22`, from the terms' "last updated" dates in `research/legal`) that is written into `consent.json`. The wizard never shows these cards (D18-1 limits the wizard to four decisions); they appear lazily.

| Kind | What leaves | To whom / under whose account | Provider sentence shown | How to turn it off |
|---|---|---|---|---|
| `cloud_text` | The text you dictated or selected, up to 5,000 characters per request; the repair pass sends **rolling stretches while the key is still held** (`config.toml:1452-1456`); the learned word pairs that appear in that text travel in the request (the polish glossary at `polish.py:279-283` is filtered to pairs present in the text, the way `review.glossary_for` already does at `review.py:641-648`); the second reading also sends the sentences dictated just before as context (`review.py:486-500`) | Groq and/or Google, using the key **you** pasted; you are their customer, DeskIT is your tool | Groq: "not permitted to use Inputs or Outputs for training" (Services Agreement s4.2), no retention by default, 30-day abuse logs unless you enable Zero Data Retention in your Groq console. Gemini: the Gemini notice in 5.7 | Settings > Privacy > Withdraw, or remove the key |
| `cloud_audio` | The recording of what you just said, as a WAV file, plus a fixed instruction (`transcribers/gemini.py:102-108`) | Google (Gemini) or Groq, under your key | Gemini notice (free tier trains on inputs; humans may read; not for EEA/UK/CH free quota; 18+) or the Groq sentence | Same; `backend` returns to `local` |
| `cloud_screenshots` | A JPEG of the region you selected (long side at most 1,344 px for Google, 896 px for Groq, `visual_qa.py:207-208`, `:1035-1041`), your question, and the earlier questions and answers in the same card | Groq and/or Google, under your key | as above | Same |
| `account` | An anonymous account id; app version, OS build, hardware tier | Supabase (project host in Frankfurt), under DeskIT's project, the only DeskIT-owned server (chapter 8) | The one-page terms (D25) | Your data > Delete my account |
| `report_upload` | Only what the report preview shows (chapter 7) | Same | none | Keep on this PC instead |
| `settings_sync` | `settings.toml` overrides and `vocab.json`, never audio, history or reports | Same | none | Settings > Privacy |

Every card ends with the same last line, in Hebrew and English: "Every connection this app makes is listed under Dashboard > Network."

Withdrawing a consent (`privacy.withdraw`) runs the registered tear-downs: `Polisher` and `Punctuator` drop their cloud backends (`polish.py:285-324`, `punctuate.py:230-297`), the lookup `Engine` and `Translator` drop their Gemini leg, `visual_qa.Chain` is rebuilt, and a running `GeminiTranscriber` is swapped for the local one through the existing fallback path (`main.py:4234-4254`). Nothing in flight is cancelled; the next request refuses.

## 5.4 `net.py`: the one chokepoint

`net.py` (appendix A) is the only module in `app\` that imports `urllib.request`, `http.client`, `socket` or `ssl` (D12 lock 2). Today Groq, Cerebras and Ollama go through `urllib` in `translate.py:24-25`, `visual_qa.py:682-698`, `:860-874`, `lookup.py:49`, `:703`, `:742`, and Gemini through the google-genai SDK (`map/cloud` "Dependencies"); all of those become calls into `net.py`.

The API, described as a contract:

- `net.request(method, url, purpose, secret=None, headers=None, body=None, timeout_s=...)` returns `(status, headers, body_bytes)`. `purpose` is a short fixed string from a closed vocabulary (`polish`, `punctuate`, `translate`, `lookup`, `review`, `study`, `ask-screen`, `transcribe`, `key-test`, `catalog`, `ollama`, `model-download`, `pack-install`, `update-check`, `update-download`, `account`, `report`, `sync`). `secret` is a **name** (`groq`, `gemini`, `supabase_session`), never a value: `net.py` resolves it through `secrets.get` (chapter 3) and attaches it in the header the provider expects (`Authorization: Bearer` for Groq, `x-goog-api-key` for Google, the session bearer for Supabase). Callers therefore never hold a key value at all, which shrinks lock 1 to two modules.
- `net.download(url, dest, purpose, expected_size, expected_sha256, progress)` streams to a temp file and renames on a verified hash (the installer download in chapter 11).
- `net.session_for_huggingface()` returns the session factory that `huggingface_hub.configure_http_backend` accepts, so the model download in chapter 6 is mediated by the same allowlist and logged (open point 1).
- Before connecting, `net.py` checks the URL's host against `ALLOWED_HOSTS` and the gate for the purpose; an unlisted host raises `EgressRefused(host)` and writes a refused row; `privacy.offline` refuses everything but `127.0.0.1`.
- After every call it appends one row to the in-memory Network table and to `DATA_DIR\logs\network.log`: time, host, purpose, bytes up, bytes down, HTTP status or error class, secret name or `-`, and the consent that authorised it as `kind@text_version` or `-`. Never a body, never a header, never a URL query string. The log rotates at 1 MB x 3 and is one of the "Your data" rows (chapter 4).
- One process-wide cooldown table for provider 429s replaces the per-feature dicts (`translate.py:133-135`, `transcribers/gemini.py:68-70`, `visual_qa.py:948-950`; `map/cloud` risk 11), so a spent Gemini model is spent once per process, not five times.

Egress that is *not* Python HTTP is listed rather than mediated, honestly, in `NETWORK.md`: the `pip install --target` subprocess for packs (chapter 6) talks to PyPI on its own; `net.py` writes a single row "pack-install: pypi.org, files.pythonhosted.org" before it starts and the byte count after it ends. The phone server is inbound only (chapter 12). Windows itself (clipboard cloud sync, Defender) is outside the app and the guide says so (chapter 4).

## 5.5 `ALLOWED_HOSTS` (this table becomes `NETWORK.md`)

Frozen in `net.py`; a test fails when the constant and `NETWORK.md` disagree.

| Host | Why DeskIT talks to it | Gate | Secret attached |
|---|---|---|---|
| `127.0.0.1` (Ollama on port 11434, the phone listener, the Claude Code hook) | Local models, the phone, the notify hook | none; the only host allowed in Offline mode | none |
| `generativelanguage.googleapis.com` | Gemini: transcription, translate, punctuation, lookup, ask-the-screen, key test, model catalog | `cloud_text` / `cloud_audio` / `cloud_screenshots` by purpose | `gemini` |
| `api.groq.com` | Groq: repair, punctuation, lookup, second reading, study, ask-the-screen, tier-2 transcription, key test, model catalog | same | `groq` |
| `huggingface.co`, `cdn-lfs.huggingface.co`, `cas-bridge.xethub.hf.co` | The one-time Hebrew model download (D13) | the wizard's download consent | none (ungated model) |
| `pypi.org`, `files.pythonhosted.org` | GPU / Recording / Skin packs the user asks for (chapter 6) | the pack's install button | none |
| `api.github.com`, `github.com`, `objects.githubusercontent.com` | Weekly update check and the installer download the user clicks (chapter 11) | `update_check` | none |
| `<ref>.supabase.co` | Anonymous account, reports the user sends, replies, opt-in sync (chapter 8) | `account`, `report_upload`, `settings_sync` | `supabase_session` only, never `groq` or `gemini` |

Removed from today's set: `api.cerebras.ai` (`translate.py:366`, dead free tier, D6). Anthropic is contacted only by the owner's Saturday routine on the owner's machine (D15), never by the product, and `NETWORK.md` says so because the privacy policy names Anthropic as a recipient of report text (D25).

`NETWORK.md` is the allowlist table above plus the "outside the chokepoint" paragraph from 5.4 and the disclosure pattern the research recommends: which remote services are used and why, with a link to the privacy policy (`research/keys-privacy`, Obsidian developer policies paraphrase).

## 5.6 Replacing google-genai with direct REST

Why (D12, `arch-B §4`): the SDK reads `GOOGLE_API_KEY`/`GEMINI_API_KEY` from the environment on its own (`.venv/.../google/genai/_api_client.py:103-117`, `map/cloud` risk 2), hides its transport from the chokepoint, and drags roughly 50 MB of dependencies into the wheelhouse (`map/packaging` pip table; D19 drops it). Three classes use it: `GeminiTranscriber` (`transcribers/gemini.py:71-73`, `:105-107`), `GeminiTranslator` (`translate.py:116-138`) and `GeminiVision` (`visual_qa.py:905-960`); `gemini_pool.py` parses the SDK's error object (`gemini_pool.py:29-61`) and sets the thinking knobs through SDK types (`:64-89`).

What replaces it, all through `net.request` with `secret="gemini"`:

| Need | Endpoint | Request shape | Where the old code is |
|---|---|---|---|
| Transcribe, translate, punctuate, lookup, ask-the-screen | `POST /v1beta/models/<model>:generateContent` | JSON with `systemInstruction`, `contents` whose parts are text and, for audio and images, `inlineData {mimeType, data (base64)}`; `generationConfig.thinkingConfig` carrying `thinkingBudget: 0` for 2.5 models or `thinkingLevel: "low"` for `-latest` aliases, the same rule `gemini_pool.thinking_style` applies today | `transcribers/gemini.py:95-108`, `translate.py:140-179`, `visual_qa.py:920-960` |
| Key test and catalog | `GET /v1beta/models` | none; the list is also the drift oracle (5.7) | `GeminiTranscriber.check()` `transcribers/gemini.py:153-157`, `main.py --check` `main.py:5972-5983` |
| 429 handling | the JSON error body's `error.details` (`RetryInfo.retryDelay`, `QuotaFailure` violations) | `gemini_pool.parse_429` reads the body instead of the SDK exception; `rotate()` and its 30/60-minute rests (`gemini_pool.py:92-149`) stay as they are | `gemini_pool.py:29-61` |

The key travels in the `x-goog-api-key` header, which is what the SDK sends today (`map/cloud` destination 1), never in the URL: `net.py` refuses a Google URL whose query string contains `key=`, and a test asserts it.

The inline limit: Google documents a total request size cap of 20 MB for inline parts (phase 0 confirms the figure against the current docs, open point 2). The app records 16 kHz mono 16-bit (`config.py:34`), about 32 KB per second, and base64 adds a third, so a single dictation stays under the cap up to roughly seven minutes. `GeminiTranscriber` measures the WAV before sending; a longer recording is not sent, it is decoded locally with a one-line card ("too long for the cloud pass, decoded on this PC"), and never spooled into `pending\` for a later cloud attempt. The Files API (a second upload endpoint, a second host path) is deliberately not adopted; it would only serve recordings nobody dictates in one breath.

Until the REST port lands (phase 2, D27), the interim in phase 1 is: keep passing `api_key` explicitly (already done at `transcribers/gemini.py:71`, `translate.py:136`), pin `http_options.base_url` to the allowlisted host, and route the SDK's client through `net.py`'s transport so its rows still appear in the window. `google-genai` leaves `requirements.txt:4` with the port.

## 5.7 Keys page, quota meters, model-id drift

The Keys page (D18-3; layout in chapter 9) lives in Settings and replaces the three "edit `.env`" messages (`apikey.py:77-99`) and the README's `.env` instructions. Elements per provider, Groq listed first because the guide recommends it first (D10):

| Element | Behaviour |
|---|---|
| Masked paste field | Accepts a pasted key, trims whitespace and quotes (the `.env` parser's failure mode, `map/cloud` risk 12), shows only the last four characters after save, never re-displays the value |
| [Test] | Groq: `GET api.groq.com/openai/v1/models` (`map/cloud` rec 2); Gemini: `GET /v1beta/models`. One request, purpose `key-test`, result "works" / the provider's status code |
| [Save] | Writes to Credential Manager as `DeskIT/groq` or `DeskIT/gemini` through `secrets.set` (D3); enabled only after the notice checkbox is ticked; saving does not open any consent gate |
| [Remove] | `secrets.delete`, then the tear-downs of 5.3; consents stay recorded but every cloud constructor now fails on "no key" and the features fall back locally with one INFO line |
| Storage sentence | "Your Groq key is saved in Windows Credential Manager on this PC (Control Panel > Credential Manager > Generic Credentials > DeskIT/groq). DeskIT sends it only to api.groq.com together with the text you dictated. It never goes to DeskIT's servers: our database has no field for it, and problem reports are scrubbed and shown to you before they are sent. Every connection this app makes is listed under Dashboard > Network." (wording fixed in `research/keys-privacy` and `arch-B §4`; Gemini gets the same sentence with `DeskIT/gemini` and `generativelanguage.googleapis.com`) |
| Provider notice with checkbox (D11) | Gemini, verbatim: Google's free tier uses what you send "to provide, improve, and develop Google products" and "human reviewers may read, annotate, and process your API input and output"; Google's own words: "Do not submit sensitive, confidential, or personal information to the Unpaid Services"; the free quota is not allowed for API clients in the EEA, the UK or Switzerland; you must be 18 or older; turn on billing in your Google project if you need that off (`research/keys-privacy`, Gemini terms 2026-04-28; `research/legal`). Groq: Groq "is not permitted to use Inputs or Outputs for training" and keeps no data by default, 30-day abuse logs unless you enable Zero Data Retention in your Groq console; 18+ (Services Agreement 2026-06-22 s4.2, `research/legal`). The checkbox's `text_version` is stored with the key's consent rows |
| Get-a-key link | console.groq.com / aistudio.google.com, with the guide's two screenshots (chapter 14) |
| Quota meter | "Groq 240 / 1,000 today", "Gemini 12 / 80 today": per-provider daily counters kept in memory only, never written and never reported (`map/cloud` rec 11); the denominators are labelled "measured Aug 2026, not a contract" because they are observations (`map/cloud` risk 13) |
| Model line | "Repair model: openai/gpt-oss-120b (checked 2026-09-01)"; from the drift record below |

No Cerebras field (D6): `translate.py:377-396`, `polish.py:296-300`, `config.toml:1532-1536`, `settings.py:387` and `apikey.find_cerebras_key` (`apikey.py:69`) go.

Key lookup order after the change (D3): Credential Manager, then environment variables only under the `DESKIT_` prefix (`DESKIT_GROQ_API_KEY`, `DESKIT_GEMINI_API_KEY`), then the developer `.env` only in portable/DEVELOPER mode (chapter 3). The `GOOGLE_API_KEY` alias (`apikey.py:24`) is dropped so a gcloud key is never borrowed silently (`map/cloud` risk 2).

Model-id drift (`map/cloud` risk 6, rec 7): the pinned ids (`config.toml:1513-1518`, `:619-630`, `:1578-1583`, `visual_qa.py:177-179`) become *preferences*, ranked lists in `defaults.toml`. On a 404 for a configured model, the client asks the provider's catalog endpoint (purpose `catalog`), picks the first id from the ranked list that the catalog contains, records it in `state.json` under `catalog.groq_text`, `catalog.groq_vision`, `catalog.gemini` with a `checked` date, and the Keys page shows the line. A catalog with no match leaves the feature on its local fallback with a card, never an edit to a TOML file by the user.

## 5.8 The five locks and the window

Each lock names the test that holds it (full list under "Tests to add").

| # | Lock | What holds it | Test |
|---|---|---|---|
| 1 | Storage | Keys exist only in Credential Manager (D3), read only by `secrets.py` and attached only by `net.py` (5.4). No other module holds a value | `test_no_key_shaped_string_in_data_dir`, `test_only_secrets_and_net_touch_key_values` |
| 2 | Egress | `net.py` is the only transport importer; `ALLOWED_HOSTS` is frozen; every call declares purpose and secret name; the Supabase module never imports `secrets`, `apikey`, `translate` or any provider client | `test_only_net_imports_transport`, `test_net_refuses_unlisted_host`, `test_supabase_never_sees_provider_keys`, `test_supabase_module_imports_nothing_secret`, `test_allowed_hosts_match_network_md` |
| 3 | Schema | `supabase/migrations/0001_init.sql` is in the repo; no column can hold a key; free-text columns carry the CHECK against `gsk_`, `AIza`, `sk-` shapes; RLS on every table; only `sb_publishable_` ships (chapter 8; `research/supabase` PROOF) | `test_migration_has_no_key_column_and_has_checks` (chapter 8) |
| 4 | Report | Payload from the `problems.env()` whitelist (`problems.py:274-302`), redacted (chapter 4), previewed before Send (chapter 7) | `test_report_payload_has_no_key` (chapter 7) |
| 5 | Build | Tagged build, `--require-hashes`, SHA-verified python.org zip, `git archive`, `MANIFEST.sha256`, provenance attestation, `deskit --verify` (chapter 10) | `test_verify_manifest_detects_a_changed_file` (chapter 10) |

The window is **Dashboard > Network** (D18-6): a table with the columns of the `network.log` row (5.4), newest last, append-only for the process life, with a filter by host and a "Open network.log" button; a lock icon in the dashboard header while `privacy.offline` is on; a counter "outbound today: N requests, M KB" on Home beside the hardware card. During a plain dictation on the local backend the table shows only `127.0.0.1` rows (and none if Ollama is absent), which is the demonstration the guide asks the user to perform (5.10).

## 5.9 The Offline switch

`privacy.offline = true`, flipped from Settings > Privacy (no card, it only removes capability). Effects: `net.py` refuses every host but `127.0.0.1` with `EgressRefused`, writes refused rows so the user sees what *tried* to leave; `privacy.allowed` returns false for every kind; the dashboard header shows the lock; the update check, the outbox uploader, the sync job and the catalog probe all stay idle; the model download button is disabled with "offline mode is on". Dictation, learning, history, hint/dot/shelf, Ollama-backed passes and the phone keep working. The switch is per machine and lives in `settings.toml`, not `state.json`, because it is a choice, not a measurement.

## 5.10 How a sceptic verifies each lock

This section is the guide's chapter "Privacy and how to check it yourself" (D26; chapter 14 reuses it verbatim). Four ten-minute checks and two longer ones, in the order a stranger would try them.

1. **Storage (2 minutes).** Paste a key on the Keys page. Open Control Panel > Credential Manager > Windows Credentials > Generic Credentials and find `DeskIT/groq`. Delete it there; the Keys page now shows "no key". Search the folder `%LOCALAPPDATA%\DeskIT` for the first eight characters of the key: no hit. What this proves: the key is in Windows' store, not in any DeskIT file. What it does not prove: that another program running as you cannot read it (Credential Manager and DPAPI are per-user, not per-app, `research/keys-privacy` CryptProtectData), which is why the wording is "never leaves your PC to us", not "unreadable on your PC".
2. **Egress during plain dictation (3 minutes).** Open Dashboard > Network, dictate three sentences with every cloud switch off. The table shows nothing, or only `127.0.0.1` rows if Ollama is installed. Then turn on Offline mode and press the repair or translate key: the feature says it is offline, and a refused row appears naming the host it would have used.
3. **Offline refuses (2 minutes).** With a key saved and cloud text consented, switch Offline on: every cloud feature refuses; switch it off: they work. The gate is code, not a prompt.
4. **The schema (3 minutes).** Open `supabase/migrations/0001_init.sql` in the repository. Read the column list of every table: no column named or shaped for a key, and the CHECK constraints that reject key-shaped strings are in the same file. RLS is enabled on every table in the same file.
5. **The tree (10 minutes, optional).** Run `deskit --verify`: it recomputes `MANIFEST.sha256` over `python\` and `app\` and prints any difference; compare the manifest's hash with the one in the GitHub release and the attestation. Read `net.py`: the allowlist is one constant near the top, and the test `test_only_net_imports_transport` in the product test file is the grep.
6. **Independent packet check (30 minutes, optional).** Enable Windows Firewall logging for allowed connections (the guide gives the two `netsh` lines as text, chapter 14) or run Wireshark filtered to `pythonw.exe`, then diff the destinations against `network.log`: the sets match. The sceptic who does this has verified the window is honest without trusting the developer.

What cannot be verified and is said plainly (`research/keys-privacy` uncertainties): the live Supabase project is the owner's word, only the published migration is checkable; the installer is not byte-reproducible, only the tree is (Inno timestamps); and any store readable by the user's own account is readable by malware running as that account.

## Acceptance

- `defaults.toml` has the `[privacy]` section with the defaults of 5.1; `privacy.allowed` exists; the generated Settings page shows the gates read-only with date and text version and refuses to write them.
- The seven constructors of 5.2 refuse to build when their gate is shut; the first press of each cloud feature on a fresh install opens its card and [Not now] leaves the feature on its local path.
- `consent.json` records `{kind, text_version, when, app_version}`; a bumped `text_version` re-opens the card; Withdraw tears the clients down.
- `net.py` is the only transport importer in `app\`; `ALLOWED_HOSTS` equals the `NETWORK.md` table; a request to any other host raises before connecting; every request writes one `network.log` row with no body, header or query string.
- `google-genai` is out of `requirements.txt`; the three Gemini clients speak REST through `net.py`; a recording over the inline cap is decoded locally with a card.
- The Keys page stores to `DeskIT/groq` and `DeskIT/gemini`, tests with one GET, never re-displays a value, and shows the D11 notice with a checkbox; Cerebras is gone from config, settings and code.
- `network.log` shows only loopback rows during a plain dictation on a machine with no consents (D27 phase 1 acceptance).
- Offline mode makes every cloud feature refuse and leaves dictation working.
- The five lock tests are green in CI and the README shows their badge (`arch-B §4` trust amplifiers).

## Tests to add

All in the product test file (chapter 7's split), runnable on the hidden desktop rule (chapter 15); fixture keys are `gsk_` and `AIza` shaped strings that match the redactor patterns but are not real.

| Test | Asserts |
|---|---|
| `test_privacy_gate_refuses_every_cloud_constructor` | With all gates false, each constructor in 5.2 raises `ConsentRequired`; with the gate true and a consent row of the current `text_version`, it builds against a mock transport; with a stale `text_version`, it refuses |
| `test_screenshot_chain_follows_privacy_gate` | Rewrite of `tests.py:10804-10836`: `Chain._builders` lists only `ollama` while `cloud_screenshots` is shut, even when `prefer = "groq"`; `["ollama", "groq", "gemini"]` when open |
| `test_settings_page_cannot_write_privacy_keys` | `config.set_values` refuses any `privacy.*` key and the generated page has no editable widget for the section |
| `test_consent_round_trip_and_withdraw_teardown` | `grant` writes the row atomically; `withdraw` removes it and every registered tear-down ran; a second `withdraw` is a no-op |
| `test_warmups_never_open_a_card` | Start-up warm-ups with every gate shut make zero `net.request` calls and open zero cards |
| `test_no_key_shaped_string_in_data_dir` | After driving every feature with fixture keys through a mock transport, no file under a temp `DATA_DIR` (including `settings.toml`, `state.json`, `problems.json`, `network.log`, `app.log`, `consent.json`, `lookup_cache.json`) contains a fixture key or a key-shaped string |
| `test_only_secrets_and_net_touch_key_values` | Static: no module in `app\` other than `secrets.py` and `net.py` calls `secrets.get` or mentions the Credential Manager targets |
| `test_only_net_imports_transport` | Static grep of `app\`: `urllib.request`, `http.client`, `httpx`, `requests`, `socket`, `ssl` are imported only by `net.py` (style of `visual_qa.py:173-175`) |
| `test_net_refuses_unlisted_host` | A request to `example.com` raises `EgressRefused` before any socket is opened (transport mock counts zero connects) and a refused row is logged |
| `test_net_offline_refuses_all_but_loopback` | With `privacy.offline`, every allowlisted host is refused and `127.0.0.1` still passes |
| `test_net_never_puts_key_in_url` | A Google URL containing `key=` is refused; the fixture key appears only in the `x-goog-api-key` or `Authorization` header captured by the mock |
| `test_network_log_row_shape` | Each row has exactly the fields of 5.4, the secret column holds a name, and no row contains a body fragment, a header value or a query string |
| `test_supabase_never_sees_provider_keys` | Drives account creation, report upload and sync through the mock transport with fixture keys present: no request to the Supabase host carries a header or body containing them |
| `test_supabase_module_imports_nothing_secret` | Static: the Supabase client module imports neither `secrets`, `apikey`, `translate`, nor any provider module |
| `test_allowed_hosts_match_network_md` | The host set in `net.ALLOWED_HOSTS` equals the hosts listed in `NETWORK.md` |
| `test_plain_dictation_touches_only_loopback` | A local-backend dictation with no consents produces no `network.log` row for a non-loopback host |
| `test_gemini_rest_request_shape` | The transcribe request is a `generateContent` POST with an `inlineData` part of `audio/wav`, a text part, and a `thinkingConfig` matching `gemini_pool.thinking_style` for the model |
| `test_gemini_inline_limit_refused_before_send` | A WAV over the cap makes zero requests and yields the local decode with the card |
| `test_gemini_429_parsed_from_json_body` | `parse_429` extracts retry delay and per-day exhaustion from a JSON error body and `rotate()` rests the model as before |
| `test_catalog_drift_picks_next_model` | A 404 followed by a catalog listing selects the first ranked id present and writes `catalog.*` to `state.json` |
| `test_keys_page_never_redisplays_value` | After Save the field shows only the last four characters and the widget's text never equals the key |
| `test_env_alias_google_api_key_ignored` | `GOOGLE_API_KEY` and unprefixed `GEMINI_API_KEY`/`GROQ_API_KEY` in the environment are not picked up; `DESKIT_*` are |
| `test_polish_glossary_filtered_to_text` | The glossary in the polish system prompt contains only pairs whose heard side occurs in the text (mirrors `review.glossary_for`) |
| `test_cooldown_table_is_process_wide` | One 429 on a Gemini model rests it for the transcriber, translator and vision client alike |
| `test_cerebras_is_gone` | No `cerebras` string in `app\` sources, `defaults.toml` or the generated Settings page |

## Open points

1. **Egress outside the chokepoint.** `huggingface_hub` uses `requests` internally; the plan routes it through `net.session_for_huggingface()` via `configure_http_backend`, which keeps the allowlist but means `requests` ships in the wheelhouse and the static import test must scope to `app\` only. The pip subprocess for packs (chapter 6) is not mediated at all, only announced in the log and in `NETWORK.md`. If the owner wants the stricter reading of D12 ("every outbound byte passes one chokepoint"), packs would have to be downloaded by `net.download` and installed with `pip install --no-index --find-links`; chapter 6 should decide.
2. **The 20 MB inline figure** is quoted from memory of Google's docs; phase 0 confirms it and the resulting dictation cap (about seven minutes at `config.py:34`'s 16 kHz).
3. **Consent from the phone.** D7's lazy card cannot appear on the phone; until the user presses the key on the PC, phone `/translate`, `/punctuate`, `/lookup` run local-only or return an error. Chapter 12 should say which.
4. **`update_check` default.** D6 puts the weekly check under ON "asked once" while `arch-B §4` lists it as the only gate defaulting to true; this chapter reconciles them (default true in `defaults.toml`, shown as a switch in the wizard, first check only after `setup_done`). Chapter 9 and 11 should match.
5. **EEA/UK/CH.** The Gemini notice states the free-tier restriction but the app does not geolocate (that would itself be a request); the guide must make the same statement (chapter 14).
6. **`visual_qa.allow_screenshot_upload`** is retired in favour of `privacy.cloud_screenshots`; `--migrate` (chapter 3) must map a legacy `true` to an *unconsented* gate (the card still has to be shown once, because the owner's acceptance is not the user's).


---

# 6. Hardware tiers, model download, packs, Ollama, TTS

This chapter implements D13 and D14. It turns the two things the current app assumes about the
owner's desk — an RTX 5060 Ti with 16 GB and two 1.6 GB models already sitting in
`%USERPROFILE%\.cache\huggingface\hub` (`map/core` "How the whisper models are downloaded and
cached") — into a first-run probe, one deliberate model download, three optional packs, and copy that
tells a stranger what their machine will do before it does it. Chapter 3 owns `DATA_DIR` and
`state.json`; chapter 5 owns the consent cards and `net.py`; chapter 9 owns the pixel-level screen
specs; chapter 10 owns the base wheelhouse. Here: what the probe decides, what each tier changes,
how bytes get onto the disk, and what the user sees when any of it fails.

## 6.1 Where the app stands (the facts this chapter changes)

| Today | Where | Consequence for a stranger |
|---|---|---|
| `WhisperModel(model, device=dev, compute_type=compute)` is built with no `download_root`; both repos land in the global HF cache; the download happens inside `App()` behind a static splash line "loading the transcription model…", and under `pythonw` there is no tqdm | `transcribers/local_whisper.py:362-363`, `:243`; `main.py:6179-6180`; `map/core` "How the whisper models are downloaded" | A 3.2 GB silent download on first start; offline → `TranscriptionError` → `MessageBoxW` (`local_whisper.py:380-381`, `main.py:233-239`); a half-written snapshot is every competitor's top issue (`research/competitors`, cited by D13) |
| The device ladder tries `("cuda","float16")` then `("cpu","int8")`, forces a silent inference so missing CUDA DLLs fail now, and logs the fallback at INFO — the only place the user could learn they are on CPU | `local_whisper.py:356-378` (the map cited `:396-417`; the file has moved since) | No NVIDIA card → 40× slower dictation with no explanation (`requirements.txt:11-13`) |
| `_register_cuda_dlls()` scans `sys.path` for `site-packages/nvidia/*/bin`, calls `add_dll_directory` and prepends the dirs to `PATH` because CTranslate2 uses plain `LoadLibrary` | `local_whisper.py:50-79`; `research/packaging` S2 | Works only when the wheels sit in the interpreter's `site-packages`; the pack layout (6.5) must be found the same way |
| The English detector is loaded eagerly for every utterance and costs another 1.6 GB disk + ~1.6 GB VRAM; an OOM silently drops detection | `local_whisper.py:386-392`; `map/core` risk 14 | A 4 GB card loses English silently; a CPU user pays a second cold load for nothing |
| Ollama models and deadlines are the owner's: `gemma3:12b` in `[polish]`, `[lookup]`, `[visual_qa]`; `llama3.1:8b` in `[translate]`; `ollama_timeout_s = 120/150`, `max_wait_s = 10` | `config.py:959, 426, 489, 325, 514, 332, 1004` | Without Ollama every "on this computer" pass times out; on a small card a 12b model does not fit (`map/cloud` rec 8) |
| Hebrew TTS assumes the `Microsoft Asaf` he-IL WinRT voice | `config.py:496`; `visual_qa.py:55-56, 1094-1099` | Machines without the voice say nothing and show no reason (`map/capture` rec 8) |
| `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` are unpinned lines in the base requirements | `requirements.txt:13-14` | ~1.3 GB of NVIDIA wheels in every install, CPU machines included; the installer would carry NVIDIA binaries (D24 forbids) |

## 6.2 The probe (D14)

`hardware.py` (new) runs once in wizard step 3 and again at every start before any model loads
(`main.py:5963-5969` is where `firstrun.needed()` is consulted today; the probe goes right after it).
It never raises and finishes in under two seconds or gives up on the slow item.

| Step | How | Field in `state.json` `[hardware]` |
|---|---|---|
| CUDA devices | `ctranslate2.get_cuda_device_count()` — cheap, no subprocess | `cuda_devices` (int) |
| VRAM and driver | `nvidia-smi --query-gpu=memory.total,driver_version --format=csv,noheader,nounits` with `CREATE_NO_WINDOW`, 5 s timeout — generalising the wrapper at `awake.py:642-648` (today it queries `memory.used,memory.total`) | `vram_mb`, `driver` |
| Driver floor | CTranslate2 ≥ 4.5 needs cuDNN 9, which needs a CUDA ≥ 12.3 driver (`research/packaging` S2); the venv today runs `ctranslate2 4.8.1` + `nvidia_cudnn_cu12 9.24.0.43`, so the floor is a real gate | `driver_ok` (bool) |
| Cores and RAM | `os.cpu_count()`, `GlobalMemoryStatusEx` through ctypes | `cores`, `ram_mb` |
| GPU pack present | `DATA_DIR\packs\gpu\packs.lock` exists and its recorded versions equal the ones pinned in `app\packs\gpu.lock` | `gpu_pack` (`ok` / `missing` / `stale` / `failed:<reason>`) |
| Ollama | `GET http://127.0.0.1:11434/` through `net.py` (loopback is always allowed, D12), 1 s timeout, body "Ollama is running" (`research/models` S18); then `GET /api/tags` for the installed models | `ollama` (bool), `ollama_models` (list) |
| Hebrew voice | one PowerShell `AllVoices` query with `CREATE_NO_WINDOW`, the literal-path pattern `visual_qa.py:1094-1099` already uses, filtered to `Language == "he-IL"` | `he_voice` (name or `""`) |
| Decision | the tier table in 6.3 | `tier` (`gpu` / `gpu-small` / `cpu`), `probed_at`, `probe_version` |

`tier` is derived at every start and compared with the stored one. If it changes (a laptop docked to an
eGPU, a driver update, a pack that stopped loading) the app rewrites the derived keys listed in 6.3,
shows the "Your hardware changed" variant of the Home hardware card (chapter 9, screen 10) and never
repeats the wizard. The user's own explicit choices — `english_detector`, `gpu_pack_declined`,
`cloud_transcription` — live in `settings.toml` and are never overwritten by the probe (D2).

## 6.3 Tiers and the defaults that change per tier

Every key below already exists in a dataclass unless marked *new*. Tier defaults are written by
`hardware.apply(tier)` into `state.json` (machine-derived, D2), never into `settings.toml`, so a user
override always wins and an update never fights the probe.

| Key | Today (owner) | Tier 1 GPU ≥ 6 GB | Tier 1b GPU 4-6 GB | Tier 2 CPU | Source |
|---|---|---|---|---|---|
| `[local] device` (`config.py:263`) | `auto` | `cuda` | `cuda` | `cpu` | ladder at `local_whisper.py:356-358` keeps working; `auto` stays for portable mode |
| `[local] compute_type` *new* | hard-coded per device | `float16` | `int8_float16` | `int8` | `research/models` S10 (turbo int8 ≈ 1.5 GB VRAM) |
| `[local] cpu_threads` *new* | absent | 0 | 0 | `cores` | `research/models` rec 2 |
| `[local] beam_size` (`config.py:289`) | 5 | 5 | 5 | 2 | `map/core` rec 4 |
| `[local] english_model` (`config.py:276`) | deepdml turbo | user choice, default `""` (off) | `""` | `""` | D13: detector optional, GPU tier only |
| `[local] rolling` (`config.py:303`) | true | true | true | true (kept; 6.9 covers the finish timeout) | `map/core` "CPU-only" |
| `[review] enabled` (`config.py:1050`) | true | true | true | false | D6, D14 |
| `[review] llm_per_day` (`config.py:1081`) | 200 | 0 until cloud-text consent | 0 | 0 | D6 |
| `[study] enabled` (`config.py:1016`) | true | false, tab hidden | false | false | D6, D14 |
| `[polish] prefer` (`config.py:975`) | `groq` | `ollama` | `ollama` | `ollama` — with no Ollama the pass is skipped, not timed out | D6 |
| `[polish] ollama_model` (`config.py:959`) | `gemma3:12b` | `gemma3:12b` if VRAM ≥ 12 GB else `gemma3:4b` | `gemma3:4b` | `""` (local passes off) | `map/cloud` rec 8 |
| `[polish] max_wait_s` (`config.py:1004`) | 10 | 10 | 6 | 0 (skip) | derived, `map/cloud` rec 8 |
| `[lookup] prefer` / `model` (`config.py:422, 426`) | `ollama` / `gemma3:12b` | same rule as polish | `gemma3:4b` | `groq` once a key exists, else the entry is hidden | `map/cloud` rec 8 |
| `[lookup] cold_to_gemini` (`config.py:430`) | true | false | false | false | D6 |
| `[lookup] keep_alive` (`config.py:436`) | `30m` | `30m` | `10m` | — | derived |
| `[visual_qa] prefer` / `ollama_model` (`config.py:485, 489`) | `ollama` / `gemma3:12b` | `ollama` / by VRAM as polish | `gemma3:4b` | no local entry; first press → three-button card (6.7) | `map/capture` rec 4 |
| `[visual_qa] ollama_timeout_s` (`config.py:514`) | 120 | 120 | 60 | — | derived |
| `[visual_qa] speak` / `voice` (`config.py:495-496`) | `button` / `Microsoft Asaf` | probed (6.8) | probed | probed | `map/capture` rec 8 |
| `[translate] ollama_model` (`config.py:325`) | `llama3.1:8b` | `llama3.1:8b` if VRAM ≥ 8 GB else `llama3.2:3b` | `llama3.2:3b` | `""` | `map/cloud` rec 8 |

Cloud transcription (Groq `whisper-large-v3-turbo`, `research/models` S7/S15) is an *offer* on tier 2
only: the hardware step ends with "For instant results you can use a free Groq account — your audio
would then leave this PC" and a button that opens the cloud-audio consent card (chapter 5). Accepting
flips `[privacy] cloud_audio` through the card and writes `backend = "groq"` to `settings.toml`;
`fallback_to_local` stays on so a spent quota (20 RPM, 2,000 requests and 8 h of audio per day, 25 MB
per file) never blocks dictation. The Gemini audio backend remains the second cloud choice with its
training warning (D11). Neither is ever the default (D6).

## 6.4 The model download (D13)

The download is a wizard step and a Settings action, never a side effect of constructing
`WhisperModel`. `models.py` (new) owns it; the two construction sites `local_whisper.py:243` and
`:362` gain `download_root=DATA_DIR\models` and `local_files_only=True`, so the transcriber can only
load, never fetch.

| Stage | Behaviour | Evidence |
|---|---|---|
| Source | `ivrit-ai/whisper-large-v3-turbo-ct2`, Apache-2.0, ungated, no token; pinned `revision=<commit hash>` recorded in `app\models.lock` (repo id, revision, file list with sizes and sha256) | `research/models` S1/S6 |
| Size line | `snapshot_download(..., dry_run=True)` returns per-file sizes; the step prints "1.62 GB from huggingface.co into `%LOCALAPPDATA%\DeskIT\models`" before anything is fetched | `research/models` S16 |
| Consent | the step is the consent: [Download] / [Not now]. "Not now" leaves a "no model yet" state with a Home card, not a broken app; no local dictation until the model exists | D18 wizard step 3 |
| Transfer | `snapshot_download(repo, revision, local_dir=DATA_DIR\models\ivrit-ai--whisper-large-v3-turbo-ct2, tqdm_class=<Tk-driving tqdm>)`; concurrent, resumable — an interrupted file keeps its `.incomplete` part and continues on the next call; only `huggingface.co` and its CDN hosts are in `ALLOWED_HOSTS` (D12) and every request carries `purpose = "model download"` | `research/models` S16 |
| Progress | Tk bar with bytes, percent, rate and [Pause]; closing the wizard mid-download is allowed and resumes at the next start | D13 "resumable" |
| Verification | after the call returns, every file in `models.lock` must exist with the recorded size and sha256; only then is `DATA_DIR\models\<repo>\.complete` written with the revision inside. `local_whisper` refuses a folder without a matching `.complete` and raises a typed `ModelMissing` that the UI turns into the "Model not ready" card — never `MessageBoxW` | D13 "never loads a partial snapshot" |
| Offline afterwards | once `.complete` exists the process sets `HF_HUB_OFFLINE=1` and `HF_HOME=DATA_DIR\cache\hf` in its own environment before importing `faster_whisper`, so no later start touches the network or the user's global HF cache | `research/models` S16, rec 1 |
| Re-download | Settings > Speed (new tab beside the five at `settings.py:450`) > "Delete and re-download the model" removes the folder and re-runs the step; plain "Delete the model" lives on Your data (chapter 4) | D13 |
| Detector | same machinery with `deepdml/faster-whisper-large-v3-turbo-ct2`, pinned in the same lock file, offered only when `tier == "gpu"` as "Detect English automatically — 1.6 GB more, uses 1.6 GB of your card"; declining stores `english_detector = false` in `settings.toml` | D13, `map/core` rec 3 |
| Owner's optional mirror | an int8 re-conversion (~0.8 GB) under the owner's HF account, Apache-2.0 with ivrit.ai attribution; if it exists, `models.lock` lists it as the tier-2 source and the float16 repo stays the tier-1 source | `research/models` S6 |
| Never a Release asset | GitHub caps assets at 2 GiB and its AUP names "significantly excessive" bandwidth; Hugging Face serves the file over CloudFront with resume at no cost to the owner | `research/updates` (GitHub Docs, AUP, HF storage limits) |

Portable/DEVELOPER mode (D4) keeps today's behaviour: no `download_root`, the global cache, no
`.complete` requirement — the owner's machine re-downloads nothing.

## 6.5 Packs: `DATA_DIR\packs\` (D14, D19, D24)

A pack is a set of wheels the base installer does not carry, fetched by pip from PyPI into a folder the
user can delete. Three packs exist; the mechanics are one module, `packs.py` (new).

| Pack | Wheels (pinned in `app\packs\<name>.lock` with hashes) | Size | Who is offered it | Licence shown |
|---|---|---|---|---|
| `gpu` | `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` — the versions in the owner's venv today (`12.9.2.10`, `9.24.0.43`); `ctranslate2` itself stays in the base | ~1.3 GB download (cuBLAS 553 MB + cuDNN 747 MB), more on disk | tier 1 / 1b in the wizard and on Settings > Speed | NVIDIA EULA and cuDNN SLA URLs on the card; no clickwrap needed because the user downloads NVIDIA's own package (`research/models` S8/S14/S20) |
| `recording` | `av` (PyAV) and whatever chapter 13 decides about its FFmpeg build | tens of MB | anyone who turns on screen recording or the camera in Settings > Screen | PyAV/FFmpeg licence text (D24) |
| `skin` | `skia-python` | ~25 MB | anyone who opens the Skin page | BSD-3 (D24) |

Mechanics, in order:

1. **Install** — `python\python.exe -m pip install --target DATA_DIR\packs\<name> --require-hashes --no-deps -r app\packs\<name>.lock`, run with `CREATE_NO_WINDOW`, stdout piped into the pack card's progress area; the pack card shows the size line first (from the lock file) and [Install] / [Not now]. The pip process talks only to `pypi.org` and `files.pythonhosted.org` (both in `ALLOWED_HOSTS`; the pip subprocess is the one sanctioned non-`net.py` transport, listed in `NETWORK.md`, chapter 5).
2. **Record** — on success `packs.py` writes `DATA_DIR\packs\<name>\packs.lock` (copied from the app lock plus `installed_at`, `app_version`). The probe compares this with the app's lock at every start; a mismatch means "stale" and the Speed page offers "Update the GPU pack (1.3 GB)" — it is never re-downloaded silently.
3. **Load order** — before `faster_whisper` is imported, `packs.activate("gpu")` prepends `DATA_DIR\packs\gpu\nvidia\cublas\bin` and `...\nvidia\cudnn\bin` to `PATH` *and* calls `add_dll_directory` on each, exactly the dual treatment `_register_cuda_dlls()` (`local_whisper.py:50-79`) applies today, because `add_dll_directory` alone is not enough for CTranslate2's plain `LoadLibrary` (`research/packaging` S2). The scan of `sys.path` is replaced by the explicit pack path; `sys.path` gets the pack root appended for `recording` and `skin` so their Python packages import normally.
4. **Verify** — `packs.activate("gpu")` then forces the same 0.4 s silent inference the ladder already forces (`local_whisper.py:368-370`). Failure sets `gpu_pack = "failed:<first line>"` in `state.json`, drops the tier to `cpu` for this session and shows the fallback card (6.9). Nothing is deleted; the user can retry from Speed.
5. **Remove** — Speed > "Remove the GPU pack" deletes the folder and resets `gpu_pack`; Your data (chapter 4) lists `packs\` as one row with its size.

Declining a pack in the wizard writes `gpu_pack_declined = true` to `settings.toml`; the Speed page and
the Home hardware card keep offering it in one line ("Turn on GPU speed — 1.3 GB") without nagging.
The base wheelhouse (chapter 10) therefore never contains `nvidia-*`, `av` or `skia-python`.

## 6.6 The English detector as an option (D13, D29 item 8)

- Offered only in tier 1, in wizard step 3 after the Hebrew model, and later on Speed. Copy: "Detect
  English automatically. Downloads 1.6 GB more and uses 1.6 GB of your graphics card. Without it, short
  English phrases may come out transliterated." Default off.
- `LocalConfig.english_model` (`config.py:276`) defaults to `""` in `defaults.toml`; the wizard writes
  the deepdml id into `settings.toml` only when the user ticks it. `local_whisper.py:386-392` already
  treats an empty name as "Hebrew only"; the warning branch there becomes a one-time card instead of a
  log line.
- Tier 1b and tier 2 never see the option; if a user override names a detector on those tiers the
  probe leaves the value but the loader skips it and the Home card says "English detection is off on
  this hardware".

## 6.7 Ollama: detect-and-prompt (D14)

- Never bundled. The probe's `ollama` flag and `ollama_models` list drive three things:
  the "On this computer" entries in every provider menu (`settings.py` menus for `[polish]`,
  `[lookup]`, `[visual_qa]`, `[translate]`) are hidden when Ollama is absent; the tier table's
  `ollama_model` suggestions are shown with a "not installed — pull it" hint when the model is not in
  `ollama_models`; and the ask-the-screen first press without Ollama shows the three-button card
  (`map/capture` rec 4; chapter 9, screen 12): "Install Ollama + a small vision model" (link to
  ollama.com, the suggested model and its size), "Use my own Groq/Gemini key" (opens the cloud-text or
  screenshot consent card), "Turn this key off".
- Timeouts are derived from the tier (6.3) instead of shipping the owner's 120/150 s; a missing Ollama
  costs one 1 s probe per start, never a 10 s wait per dictation.
- `[polish] ollama_url` (`config.py:326`) stays a setting so a user who runs Ollama on another port can
  point at it; only loopback is allowed by `net.py` unless the user edits the allowlist knowingly
  (chapter 5 decides whether a non-loopback Ollama is permitted at all).

## 6.8 Hebrew TTS probe (D14)

Once per start the probe lists WinRT voices and looks for `he-IL`. With none: `[visual_qa] speak` is
forced to `off` for the session, the Settings row is disabled with the sentence "No Hebrew voice is
installed. Add one under Windows Settings > Time & Language > Speech, then restart DeskIT", and a
button opens `ms-settings:speech`. With one: `voice` in `state.json` records the found name (the owner's
`Microsoft Asaf` moves out of `defaults.toml`). The `.ps1` helper that `visual_qa.py:1165-1166` writes to
`%TEMP%` ships as a file under `APP_DIR\app\` instead (`map/capture` rec 8).

## 6.9 Failure and slowness, always visible (D14)

| Situation | Today | Product |
|---|---|---|
| CUDA present, pack missing or broken | INFO line, silent CPU (`local_whisper.py:372-374`) | Home hardware card in its red variant: "Your NVIDIA card was found but GPU speed could not start (<first line of the error>). Dictation works on the processor meanwhile. [Retry] [Remove and reinstall the pack] [Report a problem]" |
| First decode over 10 s on tier 2 | nothing | the CPU-slowness card (chapter 9, screen 15), once: "This took N s. On this computer dictation takes about as long as you spoke. Speak in shorter bursts, or turn on cloud transcription with your own free Groq key." |
| Rolling on CPU | `Roller.finish(timeout=10)` can discard the head and decode the whole clip again (`rolling.py:229-240`) | on tier 2 the finish timeout scales with the measured real-time factor from the wizard's sentence (`rtf` in `state.json`, minimum 10 s), and the dot shows the live "transcribing…" state until text lands |
| Model folder without `.complete` | would load a partial model | "Model not ready" card with [Resume download] |
| Offline at first run | `MessageBoxW` | the download step says "No internet connection. DeskIT needs to download the model once; it will resume when you are back online" and the app stays usable for everything that needs no model |

## 6.10 What phase 0 must measure and where the numbers land

The research has no primary 2025-26 CPU benchmark for turbo int8 on a laptop; estimates range RTF 0.5-2
(`research/models` S12/S13/S19, "must be measured"). Phase 0 (D27) records, on one no-GPU laptop with 8
cores and on one 4-core machine: cold load time for 1.62 GB; wall time for a 7 s Hebrew clip at
`beam_size` 2 and 5; the same with `cpu_threads` = cores and cores/2; peak RAM. The numbers go to:

- the tier-2 copy in wizard step 4 ("we measured N s for your test sentence" uses the live value; the
  guide's expectation sentence uses the phase-0 median);
- the decision whether tier-2 copy says "usable" or "cloud recommended" (D14 "revisit");
- `defaults.toml` comments for `beam_size` and `cpu_threads`;
- the `rtf` floor used by 6.9's rolling timeout.

Owner's machine numbers that must not ship: "8.2 s vs 0.20 s for a 3 s clip" (`requirements.txt:11-13`,
README) and the ~40× line in `rolling.py:16`.

## Acceptance

- A clean Windows 11 VM with no NVIDIA card, Defender on: wizard step 3 reports "No NVIDIA card",
  shows "1.62 GB from huggingface.co", downloads with a moving bar, survives a forced network drop and
  resumes, writes `.complete`, and `state.json` holds `tier = "cpu"`, `compute_type = "int8"`,
  `cpu_threads = <cores>`, `beam_size = 2`, `review.enabled = false`. `network.log` shows only
  `huggingface.co`/CDN rows with `purpose = "model download"` and, afterwards, only loopback.
- The same VM with `DATA_DIR\models\...` truncated by hand: the app shows "Model not ready", never a
  message box, and the transcriber is never constructed.
- A machine with an NVIDIA card ≥ 6 GB: the GPU pack installs into `DATA_DIR\packs\gpu` from PyPI only,
  `packs.lock` matches `app\packs\gpu.lock`, the silent inference passes, Home shows "GPU — float16";
  renaming `cudnn` inside the pack makes the next start show the red hardware card and dictate on CPU.
- With Ollama stopped, no menu shows an "On this computer" entry and the ask-the-screen key shows the
  three-button card; with Ollama running and `gemma3:4b` absent, the menu shows the pull hint.
- On a machine without a he-IL voice the Speak row is disabled with the settings link; the owner's
  machine (portable mode) still speaks with Asaf.
- The base wheelhouse (chapter 10) contains no `nvidia-*`, `av` or `skia-python` wheel.
- Phase-0 numbers exist in `docs/measurements.md` and the tier-2 copy quotes them.

## Tests to add

| Test | Asserts |
|---|---|
| `test_hardware_probe_no_nvidia` | with `get_cuda_device_count` patched to 0 and `nvidia-smi` absent, `probe()` returns `tier == "cpu"`, never raises, and `apply()` writes exactly the tier-2 keys of 6.3 into `state.json` and nothing into `settings.toml` |
| `test_hardware_probe_small_card` | VRAM 4096 MB, driver ≥ 12.3 → `tier == "gpu-small"`, `compute_type == "int8_float16"`, `english_model == ""` |
| `test_hardware_probe_old_driver` | VRAM 16 GB but driver below the floor → `tier == "cpu"` and the reason string names the driver |
| `test_hardware_user_override_wins` | `settings.toml` sets `beam_size = 5` on tier 2; after `apply()` the effective config keeps 5 |
| `test_hardware_tier_change_card` | stored tier `gpu`, probe returns `cpu` → the "hardware changed" event is emitted once and the wizard is not re-armed |
| `test_models_dry_run_size_line` | with `snapshot_download` mocked, the step text contains "1.62 GB" and the destination path before any non-dry-run call |
| `test_models_partial_never_loads` | a model folder missing `.complete` makes the loader raise `ModelMissing`; `WhisperModel` is never called |
| `test_models_verify_hashes` | a file whose sha256 differs from `models.lock` prevents `.complete` and reports the file name |
| `test_models_offline_env_after_complete` | after a completed download the environment seen by the transcriber import has `HF_HUB_OFFLINE == "1"` and `HF_HOME` under `DATA_DIR\cache` |
| `test_models_hosts_allowlisted` | the download goes only to `huggingface.co` and its listed CDN hosts through `net.py` with `purpose == "model download"` (mock transport, chapter 5 harness) |
| `test_models_portable_mode_untouched` | with `DESKIT_PORTABLE=1` the loader passes no `download_root` and requires no `.complete` |
| `test_packs_pip_command` | the pip argument list for `gpu` contains `--target`, `--require-hashes`, `--no-deps` and the lock path, and the subprocess flags include `CREATE_NO_WINDOW` |
| `test_packs_lock_mismatch_is_stale` | a `packs.lock` with a different cudnn version yields `gpu_pack == "stale"` and no automatic install |
| `test_packs_activate_path_order` | after `activate("gpu")` the two `bin` dirs are the first entries of `PATH` and `add_dll_directory` was called for each |
| `test_packs_failed_falls_to_cpu_with_card` | a forced inference error during activation yields `gpu_pack.startswith("failed:")`, effective device `cpu`, and the red card event |
| `test_base_wheelhouse_has_no_pack_wheels` | the base lock file names no `nvidia-`, `av` or `skia-python` distribution (static, chapter 10 lock as input) |
| `test_detector_offered_only_on_gpu_tier` | wizard step 3's option list contains the detector on `gpu` and not on `gpu-small`/`cpu`; `defaults.toml` has `english_model = ""` |
| `test_ollama_absent_hides_local_entries` | with the loopback probe failing, provider menus contain no `ollama` choice and the ask-the-screen first press yields the three-button card |
| `test_ollama_tiered_suggestions` | VRAM 8 GB → suggested `gemma3:4b`; 16 GB → `gemma3:12b`; cpu → `""` |
| `test_tts_probe_no_hebrew_voice` | an `AllVoices` result without `he-IL` forces `speak == "off"` for the session and the settings row carries the `ms-settings:speech` link |
| `test_cpu_slow_card_once` | two decodes over 10 s on tier 2 emit the slowness card exactly once, with the measured seconds in the text |
| `test_no_owner_numbers_in_copy` | static grep: "8.2 s", "0.20 s", "RTX 5060" and "40x" appear in no shipped string table or `defaults.toml` comment |

## Open points

1. `net.py` declares that pip is the one sanctioned subprocess transport for packs; D12 lists
   `pypi.org` + `files.pythonhosted.org` but says every call passes through `net.py`. Chapter 5 must state
   how a pip subprocess is logged in the Network window (proposal: one synthetic row per pack install with
   the byte count from pip's output) — otherwise packs contradict "every outbound byte passes one chokepoint".
2. D14 lists the driver floor as "CUDA ≥ 12.3"; `research/packaging` S2 offers pinning `ctranslate2
   4.4.0` (cuDNN 8) for unknown drivers. The plan takes the floor, not the downgrade; if phase-0 finds many
   laptops below 12.3, a second GPU pack variant would be needed — not decided.
3. `[polish] prefer = "ollama"` (D6) on a tier-2 machine without Ollama means the pass is skipped; the
   decision does not say whether the Text tab should show "repair is off — install Ollama or add a key"
   permanently or only once. Chapter 9 should pick.
4. The int8 mirror (D13 optional) changes the tier-2 source repo; if the owner never publishes it, the
   `models.lock` simply has one entry. No decision needed, but chapter 16 should list it as optional work.


---

# 7. What the owner-only machinery becomes

Implements D15 and D16. Evidence: `map/owner` (all sections), `map/ui` "Owner-only or developer-only features", `arch-B §6`. The layout rules this chapter leans on (`DATA_DIR`, `state.json`, the `DEVELOPER` flag) are chapter 3's; the Supabase side of reports is chapter 8's; the screens' pixel-level copy is chapter 9's; the file-by-file inventory is appendix A's.

## 7.1 Why this chapter exists

The owner develops DeskIT on the machine he dictates on, with Claude Code, and five families of machinery grew around that fact (`map/owner` "Purpose"): problem reports, the Saturday Claude routine, Push/Undo/Restart, the nightly test run, and the notify door plus keep-awake. Families 2-4 are owner-only by construction; family 1 is the one feature every user wants; family 5 splits into a plausible user feature (keep awake, a generic notification door) and Claude-desktop plumbing (`map/owner` "Purpose", last paragraph). Today all of it ships as live buttons and scripts in the same folder as the app: Push/Undo act on whatever `origin` a folder has (`dashboard.py:1010-1114`), `weekly_review.ps1` runs `claude.exe` with `bypassPermissions` and commits to `main` (`weekly_review.ps1:123, 269-276`), `install_nightly_task.ps1` registers a task that wakes the PC at 02:55 and takes the mouse (`install_nightly_task.ps1:55, 106`), and `notify_watch.py` copies the entire Windows notification database to `%TEMP%` four times a second with the shipped `watch = "cowork"` (`notify_watch.py:147, 395-424`; `config.toml:1130`). `map/owner` risks 5-7 name this as the reason a stranger must never receive the tree as it is.

The rule of this chapter (D15): every owner feature is either removed from the product build, gated behind `DEVELOPER` (chapter 3: `.git` beside `main.py`), or reduced to a neutral opt-in. The owner's own checkout keeps working unchanged because `DEVELOPER` is true there and portable mode keeps his layout (D4).

## 7.2 Feature-by-feature: today, in the product, in the dev checkout

| Feature | Today (file:line) | In the product | In the owner's dev checkout |
|---|---|---|---|
| Notify door: `POST /notify`, Claude Code hook, `--install-hook` | `notify_hook.py:364-397` posts to `127.0.0.1:<[server] port>/notify` with the `server_token.txt` bearer; `--install-hook` writes two entries into `~/.claude/settings.json` with the absolute `<HERE>\.venv\Scripts\pythonw.exe` (`notify_hook.py:400-451, 426-427`) | Optional integration "Connect Claude Code" in Settings > Notifications, off by default (`[notify] enabled = false`). The button runs the existing `install_hook()` with the **installed** `pythonw` path from `APP_DIR\python\` and the installed `notify_hook.py`, then shows the two entries it wrote in a plain list. A "Disconnect" button and the uninstaller both run `--uninstall-hook`, a new switch that removes exactly those two entries and nothing else. The hook reads the port from `state.json` (D5), not from `config.toml` beside the script (`notify_hook.py:370`). | Unchanged; the venv path keeps working because portable mode resolves `APP_DIR` to the checkout. |
| Toast watcher `notify_watch.py`, `[notify] watch` | Copies `wpndatabase.db` + `-wal` + `-shm` to `%TEMP%\hd-notify-watch.db` on every toast from any app (`notify_watch.py:144-147, 405-424`); shipped `watch = "cowork"` (`config.toml:1130`) | Ships `watch = "off"` in `defaults.toml`; `Store._copy` is a no-op unless a `%LOCALAPPDATA%\Packages\Claude_*` folder exists; the copy, when it happens, lives under `DATA_DIR\cache\` not `%TEMP%`; `notify.log` rotates at 512 KB the way `nightly.py:232-237` already rotates its `run.log`. The "cowork" value stays in the enum so the owner can select it. | Owner sets `watch = "cowork"` in his `settings.toml`. |
| Arrival watch, dismiss-on-arrival, `claude://` open | `notify.py:435-620, 627-648`; warns "no Claude session store found" once per column on any machine without the app (`notify.py:1355-1358`) | Kept, silent: the warning drops to debug level; nothing runs unless the hook is connected. `notify.json` bodies (excerpts of the user's AI conversations, `notify_hook.py:351-352`) stay local and are never attached to a report (7.6). `dismiss_on_arrival`, which exists in code but not in the file (`config.py:809`), is added to `defaults.toml` so the generated Settings page and the code agree (`map/owner` rec 11). | Unchanged. |
| Problems: report key, `problems.json`, digest, `remove()` keeping evidence | `problems.py:899-928` (record), `1013-1071` (digest), `859-892` (remove leaves wav/jpg, 869-874); `dashboard.py:4025-4079` (Problems place), `4058-4060` (Open problems.md) | "Report a problem" v2 (7.6): same card, attachment toggles, one "Send to the developer" checkbox, a Preview window, an outbox under `DATA_DIR\problems\outbox\`, upload through the user's own Supabase session (chapter 8), replies shown as the existing "fixed?" mark, `remove(purge=True)`. `problems.md` and "Open problems.md" removed; the digest function moves to `dev/`. | The routine still reads the local store on the owner's machine, and additionally the inbox (7.7). |
| Questions + Saturday routine | `questions.py` (store, `ask()` 370-427, `answer()` 429-488); `weekly_review.ps1`; `.claude/commands/weekly-reports.md`; `_wake_review` spawns `powershell -File weekly_review.ps1 -Answered` (`dashboard.py:5126-5190`); answer bands on Home and Problems (`dashboard.py:2991-3020, 4574-5122`) | Does not ship. `questions.py` is excluded by the manifest (7.4); `_wake_review`, `_questions_store` (`dashboard.py:3911-3943`, dead today because no `[questions]` section exists, `map/owner` "Settings classification") and the answer bands are deleted from `dashboard.py`; `main.py:371-401` no longer builds a questions store. Replies to strangers are `report_replies` rows (text + `fixed_in`) that the app shows on the report row (7.6); there is no multiple-choice surface for strangers in v1. | Stays owner-side, fed by `dev/inbox.py` (7.7). The owner's own in-app question surface is dead code today and is not resurrected. |
| Nightly tests, `install_nightly_task.ps1`, `[tests]`, Stop-tests button | `nightly.py`, `nightly_tests.ps1`, `install_nightly_task.ps1`, `tests_quiet.py`; "Stop tests" bar button (`dashboard.py:115-118, 2011-2020, 8019-8055`); `[tests]` rows on The app tab (`settings.py:1265-1274, 622-623`; `config.toml:1755-1790`; `config.py:1129-1160`) | Do not ship. `[tests]` is removed from `defaults.toml` and from `config.py`'s dataclasses; `_nightly_running`/`_stop_tests` and the bar button are deleted; the suite is split (7.5). | Unchanged; the owner keeps `dev/nightly.py` and his scheduled task. |
| Awake: hold, screens off, vitals, `pin_timeouts`, `claude.exe` probe | `awake.py:178-233` (hold), `280-333` (`powercfg` read/write when `pin_timeouts`), `421-432` (`tasklist claude.exe`), `1240-1245` (`awake.log`, uncapped, 664 KB on the owner's disk); `config.toml:1042` ships `hold = true` | `hold = false`, asked once by the first-run wizard's "Optional extras" step (chapter 9, D18 step 6); `vitals_minutes = 0`; `pin_timeouts` under Advanced with the sentence "Changes the Windows power plan; restored when DeskIT exits"; the `claude.exe` probe removed from the verdict; `awake.log` rotates at 512 KB and lives in `DATA_DIR\logs\`. Screens-off hotkey stays a user feature. | Owner sets `hold = true`, `vitals_minutes = 10` in his `settings.toml`. |
| Git card: Push / Undo / branch line / `push.log` | `dashboard.py:838-946` (git block, `TRUNK` 870, `PUSH_LOG` 890), `965-1114` (`local_changes`, `push_main`, `undo_main`), `5228-5407` (the card), branch stamps `1339-1357, 7900-7916, 7743-7745, 3406-3464` | Removed from the product. Only **Restart** stays: `restart_app()` (`dashboard.py:1117-1150`) has no git in it. The 60-line rationale at `dashboard.py:831-871` moves to `dev/README.md`. | Shown when `DEVELOPER`; the block is wrapped, not deleted, so the owner's Push/Undo loop survives. |
| `versions.py` (git branch) | `versions.py:52-66` shells out to `git rev-parse` in `APP_DIR`, "(unknown)" without git | Replaced by `version.py` reading `APP_DIR\VERSION` (7.8). | Branch shown in addition, only when `.git` exists. |
| Dev tools: `skin/preview.py`, `skin/record.py`, `fonts.py` `main()`, `install_fonts.py`, `make_icon.py`, `HD_SKIN` | `map/ui` "Owner-only" | Excluded from the build (7.4); `fonts.py` keeps its runtime part, its `main()` probe stays harmless. | Unchanged. |
| Developer CLIs `--study`, `--review`, `--benchmark`; `backend = "fake"` | `settings.py:271-273`, `config.py:16`; `map/learning` rec 10 | Hidden unless `DEVELOPER`: the argparse entries stay but refuse with one line in the product; "Fake, for testing" is dropped from the General page's backend choices in `defaults.toml`. | Unchanged. |

Two settings drifts must be fixed before `defaults.toml` is generated from the file (chapter 3), because the generated Settings page and the guide would otherwise inherit them (`map/owner` risk 11, rec 11): `ServerConfig.enabled` defaults to false in code (`config.py:1117`) while the file says true (`config.toml:1304`) — the product ships `false` in both (D6); `dismiss_on_arrival` exists only in code (`config.py:809`) — add it to the file.

## 7.3 Dashboard regions removed or gated

All line ranges are `dashboard.py` as cited by `map/ui` "Owner-only" and `map/owner` "Files".

| Region | Lines | Action |
|---|---|---|
| Git block: `TRUNK`, `PUSH_LOG`, `_git()`, `local_changes`, `push_main`, `undo_main` | 838-1114 | Move into a `dev_git.py` module imported only when `DEVELOPER`; the product never imports it. |
| `restart_app()` | 1117-1150 | Keep in the product. |
| `_relaunch_dashboard()` (spawns `wscript.exe Dashboard.vbs`) | 1153-1178 | Keep, but relaunch via the installed `pythonw` and `deskit.pyw` (chapter 10); the `.vbs` files do not ship. |
| Branch stamps: `_warm_branch`, "branch '…' - running now", home footer strip | 1339-1357, 7900-7916, 7743-7745, 3406-3464 | Replace the branch string with `version.VERSION`; the branch is appended only when `DEVELOPER`. |
| Questions: `_questions_store`, answer bands on Home and Problems, "Saturday's read is waiting on an answer" | 3911-3943, 2991-3020, 4574-5122, 3008 | Delete from the product; the owner's copy stays behind `DEVELOPER` only if he wants the dead surface kept (recommended: delete outright, since `[questions]` has no config and the store never builds). |
| `_wake_review` (spawns `weekly_review.ps1 -Answered`) | 5126-5190 | Delete. |
| Problems place: Report button, "Open problems.md", digest regenerated on open, `_scan_changes()` git off-thread | 4025-4079 (4058-4060, 4067-4068, 4070-4074) | Keep the Report button; delete "Open problems.md" and the digest call; `_scan_changes` moves with the git block. Add the replies row (7.6). |
| "Changes on this computer — try them, then Push" card | 5228-5407 | `DEVELOPER` only. |
| `_problem_delete()` two-press confirmation | 4545-4575 | Keep the two presses; the note "its picture and its recording are still in the problems folder" (4568-4570) becomes "its picture and recording are deleted too" because `remove(purge=True)` is the product path. |
| `_report_shot()` `ImageGrab.grab(all_screens=True)` | 5526-5545 (and `main.py:3770`) | Change to the monitor under the mouse (7.6). |
| "Stop tests" bar button, `_nightly_running`/`_stop_tests` | 115-118, 2011-2020, 8019-8055 | Delete from the product. |
| "Send a test notification" | 7737-7762 | Keep only when `DEVELOPER`; the twenty cue play buttons stay (they are user-facing, `map/ui`). |
| `APP_ID` | 95 | `DeskIT.App` (D5). |
| The app tab `[tests]` rows | `settings.py:1265-1274, 622-623` | Removed with the section. |

The Settings page rows for `[notify] watch` "cowork" (`settings.py:1046-1048`), `lookup.dwell_ms` (dead, `settings.py:927-929`), and the Read-aloud tab (`settings.py:1170-1180`, hidden by `study.corpus_keep = 0`, D6) follow chapter 4's defaults; they are listed here only because they are owner-only in origin.

## 7.4 The build manifest: files that never ship

The build (chapter 10) packs `app\` from `git archive` and then applies an exclusion list kept in the repo as `build/exclude.txt`, one pattern per line, read by the build workflow and asserted by a test (7.5). The list, from D15 and `map/owner` rec 1:

| Pattern | Why |
|---|---|
| `weekly_review.ps1`, `.claude/`, `questions.py` | The Saturday routine and its store (`map/owner` "Files") |
| `nightly.py`, `nightly_tests.ps1`, `install_nightly_task.ps1`, `nightly*.py`, `nightly*.ps1` | The nightly run; the only script that "changes the machine rather than the app" (`install_nightly_task.ps1:2-3`) |
| `tests.py`, `tests_quiet.py`, `tests*.py` | Product tests run in CI, not on the user's PC; the ops tests live in `dev/` (7.5) |
| `make_icon.py`, `audio_check.py`, `install_fonts.py`, `skin/preview.py`, `skin/record.py` | Commit-time and desk-time tools (`map/ui` "Dev tools") |
| `android/` (source), `.agents/`, `AGENTS.md`, `*_PLAN.md` (`VISUAL_QA_PLAN.md`, `PARALLEL_FEATURES_PLAN.md`), `SKIN.md`, `*.html` | Developer briefs and the phone app's source (the APK is a Release asset, chapter 12) |
| `vocab.json.bak-*`, `.env`, `vocab.json*`, `review.json`, `transcripts.log*`, `app.log*`, `recent/`, `pending/`, `corpus/`, `problems/`, `.setup-done`, `notify.*`, `awake*`, `server_token.txt`, `questions.json`, `questions.lock`, `config.toml` | Personal stores that `.gitignore` keeps out of the repo today (`map/owner` "Personal data stores") — listed again because `git archive` of a tag is clean, but the manifest is also asserted against the working tree in a dev build |
| `Dashboard.vbs`, `DeskIT.vbs`, `launch.py`'s venv branch | Replaced by the installed launcher (chapter 10) |
| `versions.py` | Replaced by `version.py` (7.8) |

`dev/` as a whole is excluded; after the split it holds `dev/nightly.py`, `dev/nightly_tests.ps1`, `dev/install_nightly_task.ps1`, `dev/weekly_review.ps1`, `dev/questions.py`, `dev/inbox.py`, `dev/digest.py` (the old `problems.digest`), `dev/dev_git.py`'s helpers if not kept beside `dashboard.py`, `dev/tests_ops.py`, and `dev/README.md` (the moved rationale from `dashboard.py:831-871` and the corrected description of the routine — README `3251-3265` and `weekly-reports.md` disagree today, `map/owner` "What breaks"). Moving these is hand-work on the owner's list (D28, chapter 16) because the scheduled tasks and `~/.claude/settings.json` point at the old paths (`map/owner` "Machine-specific assumptions").

## 7.5 The test split

`tests.py` (28,500+ lines) asserts on developer files: `--install-hook` in the README (`tests.py:25281`), the contents of `nightly_tests.ps1` and `install_nightly_task.ps1` (`tests.py:28493-28527`), and everything that imports `nightly` or `questions` (`map/owner` risk 12, rec 12). The product build cannot drop those files without the suite going red.

The split:

- `tests.py` stays the product suite and loses every test that reads a file in the manifest (7.4) or imports `nightly`, `questions`, `versions`, `dev_git`. Those tests move verbatim to `dev/tests_ops.py`, which imports `tests.py`'s fixtures and runs only in the owner's checkout (`DEVELOPER` true).
- `tests_quiet.py`'s `NEEDS_SCREEN` list (`tests_quiet.py:46-64`, sixteen tests that grab the display or move the mouse) keeps its second-desktop runner, and the runner itself moves to `dev/`; the product CI on GitHub runs `tests.py` with `--no-screen` semantics because a hosted runner has no interactive desktop. The rule "run GUI checks on a hidden desktop while the owner is at the desk" stays the owner's (chapter 15).
- CI for the product job runs from the `git archive` tree with `build/exclude.txt` applied **before** the tests, so a product test that reaches for a dev file fails in CI, not on a user's machine.
- `KNOWN_FLAKES` (`nightly.py:168-172`, "on this machine") stays a dev concern.

## 7.6 "Report a problem" v2

Same key, same card. `problem_card.py` is a pure-Pillow painter with the copy duplicated from the dashboard's card (`problem_card.py:98-110`) and is already headless-testable (`map/owner` rec 4); the dashboard's `_report` flow gets the same fields. The card is a product screen, so its layout and copy are specified in chapter 9 (screen 7); this section is the behaviour contract.

**Fields and defaults**

| Element | Default | Behaviour |
|---|---|---|
| One text line (Hebrew, ≤ 600 chars as today, `problems.py` cleaning in `record()`) | empty | Required. |
| Kind chips: `wrong`, `broken`, `slow`, `idea`, `other` (`problems.py:122`) | none | Required; `wrong`/`slow` attach the last dictation as today (`dashboard.py:5504-5524`, `main.py:3784-3802`, only under `PROBLEM_LAST_MAX_S = 300` s, `main.py:220`). |
| Toggle **Screenshot** with byte size | ON for the local copy, OFF for upload | Captures the **monitor under the mouse**, not `all_screens=True` (`main.py:3770`, `dashboard.py:5526-5545`); still grabbed before the card opens (`main.py:3719-3755`) so the card is not in it; JPEG long side 1344, q85 (`visual_qa.py:209, 359-368`). The thumbnail keeps its caption. |
| Toggle **Recording** with byte size (0.5-1.6 MB, `map/owner` rec 4) | OFF | Copies wav + sidecar into `problems\` as today (`problems.py:375-397`); the sidecar's per-word confidences count as transcript data (next row). |
| Toggle **Transcript text** | ON when kind = `wrong`, else OFF | `dictation.raw` / `dictation.final` (`problems.py:331-353`). |
| Toggle **Settings snapshot** | ON | `problems.env()` whitelist (7.8), passed through the redactor (D8). |
| Checkbox **Send to the developer** | OFF | OFF = the report stays on this PC exactly as today. ON = the ticked parts are queued for upload. The first ON press opens the account consent card (`privacy.report_upload`, D7; chapter 5) and, if accepted, the anonymous sign-in (chapter 8). |
| Buttons | — | **Preview** (only when Send is ticked), **Send** / **Keep on this PC** (the label follows the checkbox), **Cancel**. |

**Preview window.** Opens the exact JSON that will be posted, pretty-printed, plus each ticked attachment (the screenshot as an image, the transcript as text, the recording as a name + size + a Play button). The header line reads "This is everything that leaves your PC. Nothing else." Nothing in the preview is editable except by going back to the card; the redactor (D8) has already run, and any key-shaped string it caught is shown as `[redacted]` so the user sees that the filter exists.

**Storage and outbox.** `record()` writes `problems.json` and `problems\` under `DATA_DIR` as today (`main.py:364, 487, 657-697` call sites, chapter 3). A report with Send ticked additionally writes `DATA_DIR\problems\outbox\<report-id>.json` (the payload) next to hard links or copies of the ticked attachments, and sets `sent = "queued"` on the local row. The uploader (chapter 8, `sb.py`) drains the outbox in the background, sets `sent = "sent"` with the server `id`, and deletes the outbox files. Statuses on the local row: `sent ∈ {none, queued, sent, failed}`; a paused project or no network leaves `queued` and the Problems row shows "waiting to send" — never an error dialog (D17).

**Replies.** `report_replies` rows (chapter 8) are pulled when the Problems place opens and at most once an hour while the app runs; a reply becomes the existing `maybe` mark (`problems.MAYBE`, `problems.py:111`; `suggest()` `806-857`) with `by = "developer"` and the reply text as `note` (`MAYBE_MAX = 200`, `problems.py:136`, raised to 600 to fit a reply). The row already draws the mark in its own colour (`map/owner` rec 6). The user's **Fixed** press (`resolve()`, `problems.py:771-804`) writes `status = "fixed"` back to the server row; **Reopen** writes `status = "open"`. `fixed_in` is shown as "fixed in 1.9 — did it help?".

**Delete.** `remove()` gains `purge=True` (`map/owner` rec 5): it unlinks the pinned wav, sidecar and jpg when no other report references the same stem (`problems.py:869-874` keeps them today). The product always calls `purge=True`; the dev checkout may pass `purge=False` for the routine. Deleting a sent report also enqueues a server delete of the row and its storage folder (chapter 8), best-effort.

**What never attaches.** `notify.json` bodies, `transcripts.log`, `review.json`, `vocab.json`, the phone token, `network.log` (D8, D16). `problems.env()` never copies `os.environ` (`map/owner` "External services", last paragraph) and this stays a tested invariant (7.8, "Tests to add").

**Removed.** `problems.digest()` and `problems.md` (`problems.py:1013-1071`; rewritten on every Problems-tab open, `dashboard.py:4067-4068`) move to `dev/digest.py`; "Open problems.md" (`dashboard.py:4058-4060`) is deleted. "Export my reports" is covered by chapter 4's "Export everything".

## 7.7 The Saturday routine, re-pointed: `dev/inbox.py`

The routine (`weekly_review.ps1` → `claude -p /weekly-reports`, `.claude/commands/weekly-reports.md`) keeps running on the owner's machine only. Today it reads `problems.json` (`weekly-reports.md:232`) and opens `item["shot"]` with the Read tool, which uploads the screenshot to Anthropic under the owner's account (`weekly-reports.md:352-355`; `map/owner` risk 1). With strangers' reports that fact must be (a) limited to what each user ticked, and (b) disclosed in the privacy policy (D25, chapter 13; open decision D29 (5)).

**`dev/inbox.py` contract** (runs only on the owner's machine, with `DESKIT_SUPABASE_SECRET` from his environment; never in the repo, never in the product build):

| Step | Behaviour |
|---|---|
| Fetch | Selects `problem_reports` rows with `status = "open"` (and rows changed since the last run) using the secret key. Reads **only consented columns**: `id`, `user_id`, `created_at`, `app_version`, `os_build`, `tier`, `kind`, `where`, `text`, `env`, `status`, and `dictation_raw`/`dictation_final` only where non-null (they are non-null only when the user ticked Transcript, chapter 8). Never any e-mail (anonymous accounts have none; linked e-mails live in `auth.users`, which the script never selects). |
| Attachments | Downloads a storage object only if it is listed in the row's `attachments` (i.e. the user ticked it). Audio is downloaded only when the row lists a `.wav`. |
| Layout | Writes `DATA_DIR\problems\inbox\<user_id>\<report_id>.json` plus the attachments beside it, in the same shape `problems.json` rows have (so the routine's readers, `weekly-reports.md:232-384`, need only a second glob). A `fetch.log` in `problems\inbox\` records every row and object fetched, so the owner's own egress is auditable (`arch-B §7`). |
| Tombstones | A row that disappeared server-side (the user deleted the report or ran `delete_me()`) deletes the local `<user_id>\<report_id>` files on the next run; an absent `<user_id>` folder server-side deletes the local folder. The routine's archive documents (`problems\weekly\*-reports.md`) must not quote deleted reports after that run; `dev/inbox.py` rewrites the archive index. |
| Reply push-back | The routine writes replies through `dev/inbox.py reply <report_id> "<text>" [--fixed-in <version>]`, which inserts a `report_replies` row (`by = "developer"`) with the secret key and, when `--fixed-in` is given, sets `status = "replied"` on the report. It never edits `text` or attachments. |
| Never | Never touches `settings_sync`, `vocab_sync`, `devices`, `profiles` beyond `user_id`; never prints a row to stdout (Claude's stdout is captured in `run.log`, `weekly_review.ps1:252-256`). |

**The command file** (`.claude/commands/weekly-reports.md`) must be told, in its own words: which fields are consented and that a missing field means "not consented, do not infer it"; that opening a screenshot with the Read tool uploads it to Anthropic under the owner's account and that this is disclosed to users; that replies are written only through `dev/inbox.py reply`, in English or Hebrew as the report's language, ≤ 600 characters, no questions the user cannot answer in-app (there is no question surface for strangers, D15); that `questions.ask` remains for the owner's own reports only; that the branch stamp is gone and reports carry `version` instead (7.8). The `-Answered` wake path (`dashboard.py:5126-5190`) is deleted with the dashboard region, so the routine is triggered only by the scheduled task.

The owner's local reports keep flowing exactly as before: `dev/inbox.py` does not touch `problems.json`, and the routine reads both.

## 7.8 `version.py` and `problems.env()`

`versions.py` (`current_branch()`, `versions.py:52-66`, git on PATH, "(unknown)" without git) is replaced by `version.py`:

- `VERSION` (the single file the build writes, D21, chapter 11) is read once from `APP_DIR\VERSION`; `version.VERSION` is a string like `1.9.0`; `version.BRANCH` is the git branch only when `.git` exists beside `main.py` (the same probe as today, `CREATE_NO_WINDOW`), else `None`.
- Every consumer of `versions.current_branch()` switches: `problems.env()` (`problems.py:277`), the dashboard stamps (7.3), `notify_hook.py` if it reports a version, `/health` and `/api/version` on the phone server (chapter 12).

`problems.env()` (`problems.py:274-302`) stays a whitelist (`map/owner` rec 13) and changes its fields:

| Field | Today | Product |
|---|---|---|
| `branch` | `_branch()` (`problems.py:277`) | dropped; `BRANCH` appended only when `DEVELOPER` |
| `python` | `platform.python_version()` (`problems.py:280`) | dropped (the build pins it) |
| `version` | — | `version.VERSION` |
| `os_build` | — | Windows build number (e.g. `10.0.26200`) |
| `gpu` | — | `true`/`false` (CUDA device seen at start, chapter 6) |
| `tier` | — | `gpu`, `gpu_small`, `cpu`, `cloud` (chapter 6) |
| `backend`, `local_model`, `english_model`, `beam_size`, `gemini_models`, `vocab_enabled`, `vocab_replace_after_hits`, `polish_when`, `punctuate_auto`, `review_enabled`, `max_seconds` | kept (`problems.py:286-299`) | kept; model **names** only (`problems.py:291`), never a key |
| `consents` | — | the list of `[privacy]` gates that were on at report time with their `text_version` (D7), so the owner can tell why a transcript is present |

The `env` dict is exactly the `env` jsonb column of `problem_reports` (chapter 8), so the server-side whitelist and this function are the same list; a test keeps them equal.

## 7.9 Notify door and keep-awake in the product

What survives as a user feature, with its defaults (chapter 4 holds the full default table; these are the owner-machinery rows of it):

| Key | Product default | Owner's value today |
|---|---|---|
| `[notify] enabled` | `false` | `true` |
| `[notify] watch` | `"off"` | `"cowork"` (`config.toml:1130`) |
| `[notify] dismiss_on_arrival` | added to the file, `true` | code-only (`config.py:809`) |
| `[notify] x`, `y` | move to `state.json`, clamped to the virtual screen at load (`config.py:884-893` explains why they were unvalidated) | `2188, 1373` (`config.toml:1160-1161`) |
| `[problems] x`, `y`, `card_x`, `card_y` | `state.json` | `1066, 511, …` (`config.toml:1233-1241`) |
| `[problems] shot` | `true` (local copy) | `true` |
| `[problems] keep_audio` | user-visible privacy row | — |
| `[problems] keep_resolved` | Advanced | — |
| `[awake] hold` | `false`, wizard question | `true` (`config.toml:1042`) |
| `[awake] vitals_minutes` | `0` | `10` |
| `[awake] pin_timeouts` | `false`, Advanced, with the power-plan sentence | — |
| `[server] enabled` | `false` | `true` (`config.toml:1304`) |
| `[tests] *` | section removed | present (`config.toml:1755-1790`) |

The `server_token.txt` bearer shared by the phone page and the hook (`server.py:69, 653`; `notify_hook.py:54`) becomes a DPAPI secret (D3) and the hook gets its own per-integration token (chapter 12 owns the phone tokens); `notify_hook.py` reads the port and its token from `state.json` and `secrets\` rather than from files beside the script.

## Acceptance

- The product build (from `git archive` + `build/exclude.txt`) contains no file from the 7.4 table; a fresh clean-VM install (chapter 10) shows no Push/Undo/branch/Stop-tests/"Open problems.md"/questions UI anywhere on the dashboard, and `grep -r "weekly_review\|nightly\|questions" app\` finds nothing.
- On the owner's checkout (`.git` present, portable mode) the git card, Push/Undo, branch stamps and the routine keep working; his scheduled tasks point at the moved `dev\` scripts and run green once.
- Pressing the report key on a two-monitor machine captures only the monitor under the mouse; the preview shows exactly the payload; with "Send to the developer" unticked, `network.log` (D12) shows no request during the whole report flow.
- With Send ticked and no network, the report row reads "waiting to send" and the outbox holds one JSON; when the network returns it uploads and the outbox empties.
- A reply inserted by `dev/inbox.py reply` appears on the user's row as the "fixed?" mark within an hour of the app running; the user's Fixed press changes the server row's status.
- Deleting a report removes its wav, sidecar and jpg from `DATA_DIR\problems\`.
- `problems.env()` output contains none of `branch`, `python`, and none of the fixture key strings.
- `notify_watch` does nothing on a machine without a `Claude_*` package; `%TEMP%` gains no `hd-notify-watch.db`.
- Product CI passes on a hosted runner without `dev/`.

## Tests to add

| Test | Asserts |
|---|---|
| `test_build_manifest_excludes_dev_files` | For every pattern in `build/exclude.txt`, no matching path exists in the built `app\` tree; and every file listed in 7.4 is matched by at least one pattern. |
| `test_product_suite_imports_no_dev_modules` | Static grep: `tests.py` and the product modules import none of `nightly`, `questions`, `versions`, `dev_git`, `weekly_review`. |
| `test_dashboard_has_no_git_without_developer` | With `DEVELOPER` false, `dashboard` builds the Problems place with no widget whose text contains "Push", "Undo", "branch", "Stop tests", "problems.md", and never spawns `git` or `powershell` (subprocess mocked, call list empty). |
| `test_dashboard_git_card_when_developer` | With `DEVELOPER` true, the same place shows Push/Undo (the owner's loop is not broken). |
| `test_report_shot_is_single_monitor` | With a mocked two-monitor virtual screen, the captured bbox equals the monitor under the mouse, not the union. |
| `test_report_defaults_per_kind` | `wrong` → transcript toggle on; `idea` → off; screenshot local on, upload off; recording off; send off. |
| `test_report_preview_equals_payload` | The bytes shown in the Preview window are byte-identical to the JSON written to `outbox\`. |
| `test_report_unsent_makes_no_network_call` | Send unticked → the mock transport (chapter 5) receives zero requests during record + Problems-tab open. |
| `test_report_outbox_survives_offline` | Transport raises; the row stays `queued`, no dialog is raised, the outbox file persists; a later drain sends it once and deletes the file. |
| `test_report_env_whitelist_has_no_secrets` | With fixture Groq/Gemini keys in Credential Manager and `DESKIT_*` env vars set, `problems.env()` and the outbox payload contain no key-shaped string and no `os.environ` value (`map/owner` rec 13). |
| `test_report_env_fields` | `env` has `version`, `os_build`, `gpu`, `tier`, `consents`; has neither `branch` nor `python` when `DEVELOPER` is false. |
| `test_env_matches_server_whitelist` | The key set of `problems.env()` equals the whitelist documented for the `env` column in `supabase/migrations/0001_init.sql` (parsed from a comment block, chapter 8). |
| `test_reply_becomes_maybe_mark` | A fetched `report_replies` row sets `maybe = {by: "developer", note, fixed_in}` on the matching local row; a second fetch does not duplicate it. |
| `test_fixed_press_writes_status_back` | `resolve(FIXED)` on a sent report enqueues one `status = "fixed"` update for the server id. |
| `test_remove_purge_deletes_evidence` | `remove(purge=True)` unlinks wav, sidecar and jpg; `purge=False` keeps them; a stem shared by two reports survives until the second removal. |
| `test_notify_bodies_never_in_report` | A report recorded while `notify.json` holds bodies contains none of those strings. |
| `test_notify_watch_noop_without_claude_package` | With no `Claude_*` folder, `Store._copy` copies nothing and the poll loop stats nothing. |
| `test_notify_log_rotates` | Appending past 512 KB rotates `notify.log` once, keeping the tail. |
| `test_awake_verdict_has_no_claude_probe` | The probe list contains no `tasklist claude.exe` step; `hold` default is false; `vitals_minutes` default is 0. |
| `test_install_hook_uses_installed_pythonw` | `install_hook()` writes entries pointing at `APP_DIR\python\pythonw.exe` and `APP_DIR\app\notify_hook.py`; `--uninstall-hook` removes exactly those two entries and leaves unrelated hooks intact. |
| `test_version_reads_VERSION_file` | `version.VERSION` equals the file's content; `version.BRANCH` is `None` without `.git`. |
| `test_inbox_reads_consented_columns_only` (in `dev/tests_ops.py`) | The select list `dev/inbox.py` issues equals the consented column list; it never names `email` or any `auth.*` table; a row with null `dictation_raw` produces a local row without that key. |
| `test_inbox_tombstones` (dev) | A report present locally and absent server-side is deleted on the next run, including attachments. |
| `test_inbox_reply_row_shape` (dev) | `reply` inserts `by = "developer"`, `text`, optional `fixed_in`, and updates only `status`. |

## Open points

1. `MAYBE_MAX = 200` (`problems.py:136`) is smaller than a 600-character reply; the chapter raises it to 600. If chapter 9 prefers a separate replies row instead of reusing the "fixed?" mark, the `maybe` mapping in 7.6 changes to a new `reply` field; D15/D16 say "the existing fixed? mark", so this chapter follows that.
2. D15 lists `tests.py:25281, 28490-28510` as the split points; the repo today shows the nightly-file assertions at `tests.py:28484-28527`. Same tests, slightly shifted lines.
3. Whether the owner's dead in-app question surface (`dashboard.py:2991-3020, 4574-5122`) is kept behind `DEVELOPER` or deleted outright is the owner's call; the chapter recommends deletion because `[questions]` has no config section and the store never builds (`map/owner` "Settings classification").
4. The hook's own bearer token: chapter 12 owns phone tokens; this chapter assumes the hook gets a separate DPAPI-stored token so that "Forget this phone" never breaks the Claude Code integration. If chapter 12 keeps one token, the "Connect Claude Code" button must re-install the hook after every rotation.


---

# 8. Supabase backend

Implements D17, together with the Supabase parts of D12 (schema lock, egress lock), D15 (`dev/inbox.py`) and D16 (report upload). Evidence: `research/supabase` (all), `arch-B §7`, `map/learning` rec 9, `map/owner` recs 4/6/7/13. The report card and outbox behaviour on the client are chapter 7's (7.6); the consent card and `privacy.allowed()` are chapter 5's; `net.py` and the Network window are chapter 5's; the "Account" screen is chapter 9's (screen 16); the owner's dashboard clicks are repeated in chapter 16's hand-work list from this chapter's 8.11.

## 8.1 Purpose and non-goals

Three purposes, deliberately narrow (D17, `arch-B §7`):

1. An **account row** so that reports and replies have an owner. Anonymous by default: no e-mail, no name, the `auth.uid()` is the only identifier.
2. **Problem reports the user chose to send** (chapter 7, "Send to the developer" ticked) and a **reply channel** from the owner back to that report.
3. **Opt-in sync** (phase 5, D27) of two small things for people with two PCs: the `settings.toml` overrides and `vocab.json`'s corrections list (`map/learning` rec 9: 8 KB, "the one thing worth carrying between machines").

Non-goals, each a rule the tests hold:

- **No telemetry table.** Nothing is written unless the user pressed Send or turned on Sync. The weekly update check goes to GitHub (D21), so a user who never sends a report never contacts the project host at all.
- **Never** `recent\`, `corpus\`, `review.json`, `transcripts.log`, `notify.json` (`map/learning` rec 9, D17).
- **No column can hold an API key** (D12 lock 3): no `apikey`, `secret`, `token` column anywhere; the free-text columns carry a CHECK that rejects key-shaped strings; the client module never imports the modules that can read a key (8.7).
- **No relay.** Realtime, Edge Functions and the storage bucket are never used to carry audio between phone and PC (D22); the phone never receives the Supabase session (`research/supabase` "Session storage on Windows").
- **No owner-run server.** Only the publishable key ships; the secret key exists only in the owner's password manager and in his shell for `dev/inbox.py` (D17, `research/supabase` api-keys: a secret key "bypasses every Row Level Security policy … Never put one in … a shipped application").
- **Zero cost** (8.12).

## 8.2 Tables

All tables live in schema `public`, RLS enabled, every policy `to authenticated` with the `(select auth.uid()) = user_id` shape, an index on `user_id`, and every grant to `anon` revoked so that a client holding only the publishable key and no session sees nothing (`research/supabase` RLS and secure-data sources; `arch-B §7`).

| Table | Columns (type, constraint) | Purpose |
|---|---|---|
| `profiles` | `user_id` (uuid, primary key, references `auth.users` with cascade delete); `created_at` (timestamptz, default now); `app_version_last_seen` (text ≤ 32); `is_anonymous` (boolean, default true) | One row per account, created by the client right after the first sign-in. No display name in v1 (`arch-B §7` has none; `research/supabase` suggested one — not needed while accounts are anonymous). |
| `devices` | `id` (uuid pk, client-generated, stored in `state.json`); `user_id`; `name` (text ≤ 40, user-typed, e.g. "laptop"; CHECK key-shaped); `platform` (text ≤ 32, e.g. `windows-10.0.26200`); `app_version` (text ≤ 32); `tier` (text in `gpu`, `gpu_small`, `cpu`, `cloud`); `last_seen` (timestamptz) | Lets a two-PC user tell the sync apart; updated at most once a day by a signed-in client. |
| `settings_sync` | `user_id` (pk); `json` (jsonb; CHECK key-shaped on its text form; CHECK size ≤ 64 KB); `updated_at` | The `settings.toml` override set only (D2), after the sync serializer drops every key whose schema entry carries `sync: false` — paths, device names, hotkeys, ports, coordinates, and every key the Keys page owns (`research/supabase` PROOF item 1). Phase 5. |
| `vocab_sync` | `user_id` (pk); `json` (jsonb, the `corrections` list of `vocab.json` only; CHECK key-shaped; CHECK size ≤ 256 KB); `updated_at` | Phase 5. |
| `problem_reports` | `id` (uuid pk, client-generated = the local report id, so the outbox is idempotent); `user_id`; `created_at`; `app_version` (text ≤ 32); `os_build` (text ≤ 32); `tier` (text, same enum); `kind` (text in `wrong`, `broken`, `slow`, `idea`, `other` — `problems.py:122`); `where` (text ≤ 120); `text` (text ≤ 600, CHECK key-shaped); `dictation_raw`, `dictation_final` (text ≤ 4000 each, **nullable**, CHECK key-shaped; non-null only when the Transcript toggle was on); `env` (jsonb, CHECK that its top-level keys are a subset of the whitelist in 7.8 and that its text form is not key-shaped); `attachments` (text array of storage paths, each CHECK-ed to start with the row's own `user_id/` + `id/` prefix); `status` (text in `open`, `replied`, `fixed`, `closed`, default `open`); `updated_at` | One row per sent report. |
| `report_replies` | `id` (uuid pk); `report_id` (references `problem_reports` cascade); `user_id` (denormalised for the RLS predicate); `created_at`; `by` (text, always `developer`); `text` (text ≤ 600, CHECK key-shaped); `fixed_in` (text ≤ 32, nullable) | Written only by `dev/inbox.py` with the secret key; read by the app. |
| `deletion_requests` | `user_id`; `requested_at` | Written by the `delete_me()` RPC as an audit line before the account disappears; readable only with the secret key. |

**The key-shaped CHECK.** One SQL domain-style expression, defined once in the migration and reused by every free-text and jsonb column above: the column's text form must not match the Groq pattern (`gsk_` followed by 20 or more alphanumerics), the Google pattern (`AIza` followed by 30 or more of letters, digits, underscore, hyphen), the OpenAI-style pattern (`sk-` followed by 20 or more alphanumerics), or a Supabase secret (`sb_secret_` prefix). These are the same patterns the client redactor uses (D8) and the same the schema-lock test greps for (D12), so the three layers cannot drift: the migration file carries them in a comment block that `test_redactor_patterns_match_migration` (chapter 5) parses.

**Timestamps and sizes.** `created_at`/`updated_at` are set by database defaults and a trigger, never by the client, so the app cannot backdate a row. Every text column has a length CHECK so a buggy client cannot fill the 500 MB database with one row.

## 8.3 Row-level security, per table

In prose, one line per policy. "Own row" always means the predicate `(select auth.uid()) = user_id`, wrapped in a sub-select for performance as the Supabase RLS guide recommends (`research/supabase` RLS source).

| Table | select | insert | update | delete |
|---|---|---|---|---|
| `profiles` | own row | own row (`user_id` must equal the caller's uid in the with-check) | own row, only `app_version_last_seen` changes (a trigger rejects a change of `user_id`, `created_at`, `is_anonymous` from the client; `is_anonymous` flips only through Supabase's own e-mail linking) | none (cascade from `auth.users`, i.e. only through `delete_me()`) |
| `devices` | own rows | own rows | own rows | own rows |
| `settings_sync` | own row | own row | own row | own row |
| `vocab_sync` | own row | own row | own row | own row |
| `problem_reports` | own rows | own rows (with-check also asserts `status = 'open'` and that every `attachments` path starts with the caller's uid) | own rows, and a trigger allows only `status` to change from the client (Fixed/Reopen write-back, chapter 7); `text`, transcripts, `env`, `attachments` are frozen after insert | own rows (the user deleted the report locally; the storage folder is removed by the client before the row, 8.4) |
| `report_replies` | own rows (`user_id` = caller) | none | none | none |
| `deletion_requests` | none | none | none | none |

The secret key bypasses RLS (`research/supabase` secure-data); it is used only by `dev/inbox.py` (8.10) and the retention script (8.9). No policy anywhere is `to anon`; the migration ends by revoking every privilege on the schema's tables, sequences and functions from `anon`, and a test issues a request with the publishable key and no session against each table and expects an empty result or a permission error (8, "Tests to add").

## 8.4 Storage bucket `reports`

One bucket, `reports`, **private** (public buckets bypass RLS for reads, `research/supabase` storage source), created by the migration through the storage schema so the setting is versioned and not a dashboard click.

- **Path convention:** `<user_id>/<report_id>/<file>`, where `<file>` is one of `shot.jpg`, `dictation.wav`, `sidecar.json`, `transcript.txt`, `settings.json`. The row's `attachments` array lists exactly these paths.
- **Policies on `storage.objects`** (prose): insert for authenticated users where the bucket is `reports` and the first folder of the object name equals the caller's uid as text; select with the same predicate; delete with the same predicate (so the client can remove its own folder before deleting the row and so `delete_me()` can purge). No update policy: an attachment is never replaced, a new report is filed instead.
- **Limits, set on the bucket:** 5 MB per file; MIME allowlist `image/jpeg`, `application/json`, `text/plain`, and `audio/wav` (the recording only ever uploads when the Recording toggle was ticked, chapter 7; the allowlist cannot express "only when ticked", so the client contract plus the row's `attachments` CHECK are the guard). Typical sizes: a screenshot about 100 KB, a recording 0.5-1.6 MB (`map/owner` rec 4).
- **Order of operations on the client:** upload objects first, then insert the row listing them; on failure the row is never inserted and the outbox retries the whole report; orphaned objects from a half-failed upload are swept by the retention script (8.9).
- **Order on delete:** remove the objects, then the row. A row delete with objects still present is tolerated by the retention sweep.

## 8.5 The `delete_me()` RPC

"Delete my account" (chapter 4's Your data page; chapter 9 screen 16) calls one `security definer` function, `delete_me()`, callable by `authenticated` only and taking no arguments (it acts on `auth.uid()`; a function that took a `user_id` argument would be a foot-gun). Behaviour, in order:

1. Insert a `deletion_requests` line (uid, now) — the only trace that survives, with no personal content.
2. Delete every object under `reports/<uid>/` (storage deletes are done through the storage schema inside the function).
3. Delete the caller's rows in `report_replies`, `problem_reports`, `vocab_sync`, `settings_sync`, `devices`, `profiles` (cascades would do most of this; the function does it explicitly so a missing cascade cannot leave a row).
4. Delete the `auth.users` row, which invalidates every refresh token for that account.
5. Return nothing; the client wipes `secrets\supabase.bin`, the device id in `state.json`, and marks every local report `sent = "none"`.

Free has no backups (`research/supabase` pricing), so deletion is real the moment the function returns; the owner's monthly `pg_dump` (8.9) is the only place a deleted account could linger, which the privacy policy states with the retention period of that dump (chapter 13). `dev/inbox.py` mirrors deletions locally on its next run (7.7 tombstones).

## 8.6 Auth flows and session storage

**v1 (phase 3): anonymous sign-in.** On the first "Send to the developer" press with the checkbox ticked (or, in phase 5, the first Sync switch), after the `report_upload` consent card (chapter 5) is accepted, the client performs Supabase's anonymous sign-up: no e-mail, no password, no PII; the returned user has `is_anonymous = true`; the client then inserts its `profiles` row and a `devices` row. Cloudflare Turnstile is enabled for anonymous sign-ins in the project's Auth settings to blunt abuse (`arch-B §7`); rate limits stay default (sign-in/sign-up 30 requests per 5 minutes per IP, token endpoint 150 per 5 minutes, `research/supabase` rate-limits). A machine without an account never sends a request to the project host; the wizard never creates one.

**Phase 5: link an e-mail.** For a second PC (sync) or for a reply by e-mail. E-mail + 6-digit code, no browser and no redirect: the client calls the OTP sign-in with the e-mail, the user types the code into a Tk dialog, the client verifies it; the anonymous account is upgraded in place (same uid, `is_anonymous` becomes false), so reports stay attached. Requires the magic-link template changed to emit the token instead of the confirmation URL (`research/supabase` signinwithotp source), and **custom SMTP**, because the built-in mailer sends 2 messages per hour to project team addresses only (`research/supabase` auth-smtp source: "All other addresses will fail"). Free SMTP candidate: Resend (secondary sources: 3,000/month, 100/day, one verified domain) — the domain is the one likely non-free item (D28). A magic link that must be clicked is not desktop-friendly (the verifier lives in the Python process, `research/supabase` "Design notes"); the 6-digit code is the path.

**Phase 5 nicety: Google via PKCE.** The client starts a one-shot listener on `127.0.0.1:<random port>/cb`, asks Supabase for the provider URL with that redirect, opens the system browser, receives the code, exchanges it in the same process (the code is valid 5 minutes, once; one flow at a time, `research/supabase` PKCE source). Needs `http://127.0.0.1:*/**` in the project's redirect allow-list and a Google Cloud OAuth "Web application" client pointing at `https://<ref>.supabase.co/auth/v1/callback` (`research/supabase` google source). Not built before a user asks for it.

**Session storage.** The session (access token, refresh token, expiry, the user object) is one JSON string, DPAPI-protected (`CryptProtectData`, user scope, `CRYPTPROTECT_UI_FORBIDDEN`) in `DATA_DIR\secrets\supabase.bin` through `secrets.py` (D3, chapter 3), never in Credential Manager (its value cap is about 1,280 characters and the session JSON is larger, `research/supabase` "Refresh-token safety"). Semantics the client must honour, taken from supabase-py's own client because they are the server's rules (`research/supabase` supabase-py source and sessions source): access tokens live one hour; the client refreshes when 10 seconds or less remain and also on demand before any request when the stored expiry has passed (a `pythonw` process that slept through hibernate must not rely on a timer); refresh tokens rotate on every use with a 10-second reuse window, so **exactly one DeskIT process holds the session** — the singleton (chapter 3) already guarantees one app; the dashboard, if it is a second process, asks the app over the control pipe rather than opening the file. A stolen session file is valid until the user signs out everywhere (time-boxed sessions are Pro-only, `research/supabase` sessions source); DPAPI at rest is the mitigation, and "Delete my account" or "Sign out" on the Account screen revokes it server-side.

## 8.7 The client module `sb.py`: responsibilities and forbidden imports

One module, `sb.py` (name proposed by this chapter; appendix A lists it), is the only code that knows the project URL and the publishable key (both constants in the module, the key being `sb_publishable_…`, D17). It does six things and nothing else:

| Responsibility | Contract |
|---|---|
| Gate | Every public function first calls `privacy.allowed("account")` (D7) and, for uploads, `privacy.allowed("report_upload")`; when a gate is shut the function returns "not allowed" without touching the network, the pattern `visual_qa.Chain._builders` already uses (`tests.py:10804-10836`). |
| Transport | Every request goes through `net.py` (D12 lock 2) with host `<ref>.supabase.co`, a declared `purpose` (`account.signin`, `report.upload`, `report.status`, `replies.fetch`, `sync.push`, `sync.pull`, `account.delete`, `keepalive` is the cron's, not the app's) and the secret **name** `supabase.session` — so every call appears in Dashboard > Network with its purpose, and the Offline switch refuses it. The REST surfaces used are Supabase's auth endpoints (anonymous sign-up, token refresh, OTP send/verify, sign-out), PostgREST on `/rest/v1/<table>` with the `apikey` header carrying the publishable key and the bearer carrying the session, and the storage object endpoint on `/storage/v1/object/reports/<path>`. No SDK: the same reasoning that replaces google-genai with REST (D12) applies — an SDK owns its transport and would bypass the window. |
| Session | Load, refresh, store, sign out (8.6) via `secrets.py`. |
| Reports | Drain `problems\outbox\` (8.8); write `status` changes; fetch replies since the last `updated_at` and hand them to `problems.suggest()` (7.6); delete a report's folder and row. |
| Sync (phase 5) | Push/pull `settings_sync` and `vocab_sync` with last-writer-wins on `updated_at` and a local `.bak` before every pull. |
| Account | Anonymous sign-up, e-mail linking, `delete_me()`, and the "what we hold about you" fetch that the Account screen shows (the profile row, the device rows, the count of reports). |

**What `sb.py` may never import** (D12 lock 2, asserted by a static grep test): `apikey` (or its successor `secrets`' key-reading functions — it imports `secrets` only for the `supabase.session` name and the module exposes a narrowed accessor so that a grep for `groq`/`gemini` in `sb.py` finds nothing), `translate`, `polish`, `punctuate`, `lookup`, `visual_qa`, `gemini_pool`, `os.environ` lookups, and any of the HTTP modules `net.py` reserves. Its payload builders take plain dicts produced by `problems.py` and the sync serializer; they never receive a `Config` object, so a key field cannot be reached by accident.

**What it writes locally:** `state.json` (`account.device_id`, `account.last_replies_at`), `secrets\supabase.bin`, the `sent` field on `problems.json` rows, and `logs\app.log` lines with host and purpose only (D8).

## 8.8 Outbox, retry and the paused project

- The outbox (`DATA_DIR\problems\outbox\<report_id>.json` plus attachments, chapter 7) is drained by a background worker started after the app is up and idle, and again every 15 minutes while reports are queued, and on demand from the Problems place's "Send now" link.
- Each report is one unit: objects first, then the row (8.4). The report id is client-generated, so a retry after a half-success is idempotent (the insert conflicts on `id` and is treated as done; a re-upload of an object at the same path is rejected by the no-update policy and treated as present).
- Backoff: 1, 5, 15, 60 minutes, then hourly, then daily; no dialog, ever. The Problems row says "waiting to send" and the Account screen shows "N reports waiting".
- **Paused project.** Free projects pause after 7 days without requests (`research/supabase` pausing source). A paused project answers with an error page or a connection refusal; the client treats every non-2xx from the host, and every transport error, identically: stay queued, back off. The keep-alive cron (8.9) makes a pause unlikely while the user count is near zero; real users' report sends and reply fetches count as activity later ("a few user requests to the database each day … is enough").
- **Poison reports.** A 4xx that is not auth-related (a CHECK failure, a MIME rejection, a size cap) marks the local row `sent = "failed"` with the server's reason string, stops retrying that report, and offers "Edit and resend" — which is just filing a new report. This is the case where the key-shaped CHECK fired on a user's text that merely looked like a key; the client redactor should have caught it first, so this doubles as a test hook.
- **Auth failure.** A 401 triggers one refresh attempt; a second 401 means the account is gone (deleted from another PC, or the retention script removed an idle anonymous account): the client clears the session, sets every `sent = "sent"` report to "sent (account closed)", and the next Send press starts a fresh anonymous sign-in after re-showing the consent card.

## 8.9 Keep-alive, backups, retention

| Concern | Mechanism | Owner |
|---|---|---|
| Idle pause | A GitHub Actions workflow on a weekly cron issues one GET to `/rest/v1/profiles?select=user_id&limit=1` with the publishable key in the `apikey` header; the response is empty because `anon` is revoked, but the request counts as activity (`arch-B §7`; the pattern `travisvn/supabase-pause-prevention` in `research/supabase`). The workflow lives in the public repo; the publishable key in it is public by design. Delete the workflow once daily traffic exists. | repo |
| Restore after a pause | Studio > Restore, one click, available for a year after the pause (`research/supabase` pausing; secondary sources say the one-click path may close after 90 days — treat 90 days as the real limit). The app needs no change: queued reports resume. | owner, by hand |
| Backups | None on Free. Monthly `pg_dump` over the pooler connection string, encrypted with the owner's own key, kept off GitHub (`arch-B §7`). Retention of the dumps: 3 months, stated in the privacy policy (chapter 13). | owner, by hand or a local scheduled task on his machine |
| Report retention | 12 months: a monthly owner script (`dev/retention.py`, run with the secret key from the owner's shell; `pg_cron` if the project exposes it) deletes `problem_reports` rows and their storage folders older than 12 months, and any storage object whose folder has no row (orphans from half-failed uploads, 8.4). | owner |
| Idle accounts | The same script deletes anonymous accounts (`is_anonymous = true`) with no rows in any table and no `last_seen` within 12 months, through the admin auth endpoint. Linked (e-mail) accounts are never auto-deleted. | owner |
| Logs | Supabase keeps auth audit logs 1 hour and API/DB logs 1 day on Free (`research/supabase` pricing); the IP address Supabase sees is in those logs only, which the privacy policy states (D25). | — |

## 8.10 The owner's console workflow and `dev/inbox.py`

The owner never reads reports through the app. Two paths:

- **Studio** (dashboard login, MFA turned on, D28): Table Editor on `problem_reports` for a look, Storage browser for an attachment. Studio uses the owner's login, not a key.
- **`dev/inbox.py`** for the Saturday routine (7.7 holds the full contract): runs only on the owner's machine with `DESKIT_SUPABASE_SECRET` in his environment (never in the repo, never in the product build, the name reserved in `.gitignore`'s comment and in `build/exclude.txt`'s rationale); pulls consented columns into `DATA_DIR\problems\inbox\<user_id>\`; honours tombstones; pushes replies as `report_replies` rows; logs every fetch to `problems\inbox\fetch.log`. It talks REST with the secret key and never runs inside the app process.

Replies the owner writes are plain text, ≤ 600 characters, with an optional `fixed_in` version; the app shows them as the "fixed?" mark (7.6). There is no chat.

## 8.11 Manual setup steps for the owner

Exact clicks (`research/supabase` "What the owner must do by hand", adjusted to D17's anonymous-first order; chapter 16 repeats them as a checklist with costs):

1. supabase.com → sign up with GitHub (no card expected on Free; the pricing page is silent — `research/supabase` uncertainties). New organisation on the Free plan → New project: name `deskit`, region `eu-central-1` (Frankfurt), generate the database password and save it in the password manager only.
2. Project Settings → API Keys: copy the **Project URL** and the `sb_publishable_…` key into `sb.py`'s two constants (they are public; they go into the repo). Never copy `sb_secret_…` anywhere but the password manager; export it as `DESKIT_SUPABASE_SECRET` in his own shell profile for `dev/inbox.py`.
3. SQL Editor → paste `supabase/migrations/0001_init.sql` (8.13) and run it once. Keep the file in the repo; every later change is `0002_…` and so on, never a dashboard edit.
4. Authentication → Providers: enable **Anonymous sign-ins**; Authentication → Attack protection (or the equivalent panel) → enable **Cloudflare Turnstile** with a Turnstile site key created at dash.cloudflare.com (free) — see Open points 1 for the desktop-widget question. Leave rate limits default.
5. Authentication → URL Configuration: Site URL = the GitHub Pages guide URL. Add nothing else until Google PKCE ships (then `http://127.0.0.1:*/**`).
6. Storage → confirm the `reports` bucket the migration created is **private**, file-size limit 5 MB, allowed MIME types `image/jpeg`, `application/json`, `text/plain`, `audio/wav`. If the migration cannot set the limits on this project version, set them here and note it in the migration's header comment.
7. Account → Security: enable MFA on the Supabase login.
8. Repo: add `.github/workflows/supabase-keepalive.yml` (weekly cron, one GET, publishable key) — phase 3, remove later.
9. Phase 5 only — e-mail linking: buy a domain (~USD 10/year); Resend account (free); verify the domain (SPF/DKIM/DMARC DNS records); Project Settings → Authentication → SMTP: host `smtp.resend.com`, port 465, user `resend`, password = the Resend API key, sender `login@<domain>`; Authentication → Email Templates → Magic Link: replace the confirmation-URL placeholder with the token placeholder; OTP length 6, expiry 10 minutes; raise the e-mail rate limit in Auth → Rate Limits.
10. Phase 5 only — Google: console.cloud.google.com → new project → OAuth consent screen (External; app name; support e-mail; privacy-policy URL on GitHub Pages) → Credentials → OAuth client ID, type Web application, authorised redirect URI = the value Supabase shows under Auth → Providers → Google; paste client id + secret into Supabase. An unverified app shows a Google warning until verified (`research/supabase` uncertainties).
11. Monthly: Studio → Reports → database size vs 500 MB and storage vs 1 GB; run `pg_dump`; run `dev/retention.py`.

## 8.12 Limits and cost arithmetic

Free plan, verbatim limits (`research/supabase` pricing, fetched 2026-09-16): 500 MB database, 1 GB file storage, 50,000 monthly active users, 5 GB egress plus 5 GB cached egress, 2 active projects, pause after 1 week idle, no backups, no branching. Cost: 0.

| Resource | Per unit | Headroom |
|---|---|---|
| Storage 1 GB | a report with audio ≈ 1.7 MB (1.6 MB wav + 100 KB jpg + a few KB json); without audio ≈ 0.1 MB | ≈ 600 reports with audio, or ≈ 10,000 without, per rolling 12 months (retention 8.9). Audio is off by default (chapter 7), so the realistic mix is far under the cap. |
| Database 500 MB | a `problem_reports` row with both transcripts ≈ 4 KB; a reply ≈ 1 KB; a profile + device ≈ 1 KB | > 100,000 reports. Not a constraint. |
| Egress 5 GB/month | the app pulls replies (a few KB) and, in phase 5, sync blobs (≤ 256 KB); the owner's `dev/inbox.py` downloads each report once (≈ 1.7 MB with audio) | 1,000 reports with audio in one month would be 1.7 GB; the owner's own downloads are the only material egress. |
| MAU 50,000 | one anonymous account per PC that ever sent a report | Not a constraint at any plausible scale. |
| Requests | reply fetch ≤ 1/hour per running app; outbox drain on demand | Also the activity that keeps the project un-paused once users exist. |
| Projects 2 | `deskit` uses one; the second stays free for a staging copy of the migration | — |

If the caps are ever approached, the first lever is the 12-month retention (8.9) and the 5 MB file cap, the second is turning the Recording toggle's upload off server-side by dropping `audio/wav` from the MIME allowlist; Pro (from USD 25/month) is out of scope by the owner's "all-free" constraint (D10).

## 8.13 Deliverable: `supabase/migrations/0001_init.sql`

A single file in the public repo, applied once by hand (8.11 step 3) and published as part of the proof (D12 lock 3: "the Supabase migration is published in the repo; no table has a column that could hold a key"). Its contents, in order (no SQL in this plan):

1. A header comment: purpose, the date, the statement that this file is the whole schema and that the dashboard is never edited by hand, the region, and the **key-pattern block** — the four regular expressions written once in a machine-readable comment that the client redactor test and the schema-lock test parse (8.2).
2. The `env` whitelist comment block: the exact list of allowed top-level keys, identical to `problems.env()` (7.8), parsed by `test_env_matches_server_whitelist`.
3. The reusable key-shaped check (as a function returning boolean, marked immutable, so every CHECK reads the same).
4. The tables in dependency order (`profiles`, `devices`, `settings_sync`, `vocab_sync`, `problem_reports`, `report_replies`, `deletion_requests`) with their columns, lengths, enums as CHECKs, foreign keys with cascade, and indexes on `user_id` (and on `problem_reports.updated_at` for the replies/status poll).
5. The `updated_at` trigger and the two "only these columns may change from the client" triggers (`profiles`, `problem_reports`).
6. RLS: enable on every table, then the policies of 8.3, all `to authenticated`.
7. The revoke block: all privileges on all tables, sequences and functions in `public` from `anon`; explicit grants to `authenticated` limited to the verbs each table's policies allow.
8. The `reports` bucket row in the storage schema with private flag, size limit and MIME allowlist, then the three `storage.objects` policies of 8.4.
9. The `delete_me()` function (8.5), `security definer`, owner the schema owner, search path pinned, execute granted to `authenticated` only.
10. A footer comment listing every column and stating that none can hold a key and why — this paragraph is what the guide's "check it yourself" chapter (chapter 14) links to.

A second file, `supabase/README.md`, tells a sceptic how to read the migration and how to confirm the live project matches it (Studio → Database → Schema Visualizer, or the PostgREST OpenAPI description at `/rest/v1/` with the publishable key, which lists the columns without exposing rows).

## Acceptance

- The migration applies to a fresh Free project in one run with no errors, and re-applying it fails loudly (it is not idempotent by design; `0002_…` is the way forward).
- A request with the publishable key and no session against every table and the bucket returns nothing or a permission error; a signed-in user sees only their own rows and objects (verified with two anonymous accounts from two machines).
- A report sent from a second machine appears in Studio with no e-mail and no key-shaped string anywhere in the row or objects (D27 phase 3 acceptance); the transcript columns are null when the toggle was off; the `attachments` list contains only ticked files.
- An insert whose `text` contains a fixture key fails the CHECK; the client marks the report `failed` with the reason and does not retry.
- `delete_me()` from the app leaves no row, object or auth user for that uid; `dev/inbox.py` deletes the local mirror on its next run.
- With the project paused (simulated by pointing `sb.py` at a closed port), a Send press shows "waiting to send", nothing else; unpausing drains the outbox.
- Dashboard > Network lists every Supabase request with its purpose; the Offline switch makes `sb.py` refuse without connecting.
- The keep-alive workflow runs green weekly and the project is not paused after 30 days with zero users.
- The static import test for `sb.py` passes; the mock-transport test shows no header or body to the Supabase host containing the fixture Groq/Gemini keys (D12 lock 2).

## Tests to add

| Test | Asserts |
|---|---|
| `test_sb_imports_are_narrow` | Static grep: `sb.py` imports none of `apikey`, `translate`, `polish`, `punctuate`, `lookup`, `visual_qa`, `gemini_pool`, `urllib.request`, `http.client`, `httpx`, `requests`, `socket`, `ssl`; it references neither `groq` nor `gemini` nor `os.environ`. |
| `test_sb_uses_net_only` | Every outbound call from `sb.py` goes through `net.py` with host `<ref>.supabase.co` and a purpose from the fixed list in 8.7; the Offline switch makes each function return "not allowed" with zero transport calls. |
| `test_no_keys_reach_supabase` | Fixture Groq/Gemini keys stored; run sign-in, report upload (all toggles on), status write, replies fetch, sync push through the mock transport; no request to the Supabase host carries a key-shaped string in headers, query or body (D12 lock 2). |
| `test_sb_refuses_when_gate_shut` | With `privacy.account` or `privacy.report_upload` off, every `sb.py` entry point returns "not allowed" and the transport sees nothing. |
| `test_session_file_is_dpapi` | After sign-in the session exists only in `secrets\supabase.bin`, is not plaintext JSON, and `state.json`/`settings.toml`/`app.log` contain no token. |
| `test_session_refresh_on_demand` | A stored session with a past expiry triggers exactly one refresh before the next request; a second 401 clears the session and marks reports "sent (account closed)". |
| `test_outbox_order_and_idempotence` | Objects are uploaded before the row; a failure after the objects leaves the outbox file; the retry inserts once and treats an `id` conflict as done. |
| `test_outbox_backoff_no_dialog` | Transport errors produce the backoff sequence 1/5/15/60 min and never raise a UI dialog. |
| `test_poison_report_marked_failed` | A 4xx CHECK failure sets `sent = "failed"` with the reason and stops retries; a 5xx keeps `queued`. |
| `test_attachments_only_when_ticked` | The row's `attachments` and the uploaded object set equal exactly the ticked toggles; `dictation_raw/final` are null when Transcript is off; `audio/wav` is never uploaded with Recording off. |
| `test_payload_columns_are_whitelist` | The insert body's keys are a subset of the `problem_reports` column list parsed from the migration; `env`'s keys are a subset of the whitelist comment block. |
| `test_redactor_patterns_match_migration` | The four key patterns parsed from the migration's header comment equal the client redactor's patterns (D8) character for character. |
| `test_migration_has_no_key_column` | Static: the migration defines no column whose name contains `key`, `secret`, `token`, `password`, `apikey`; every text and jsonb column carries the key-shaped CHECK; every table has RLS enabled and at least one policy; every policy is `to authenticated`; the revoke-from-anon block is present; the bucket is private. |
| `test_delete_me_clears_local_state` | Calling the account-delete path wipes `secrets\supabase.bin`, `account.*` in `state.json`, and resets `sent` on local rows. |
| `test_replies_poll_is_hourly` | While the app runs, replies are fetched at most once an hour and only with `since = account.last_replies_at`. |
| `test_keepalive_workflow_shape` | The workflow file exists, runs weekly, performs one GET to `/rest/v1/profiles` with the publishable key and no session, and nothing else. |
| `test_sync_serializer_drops_sync_false` (phase 5) | The `settings_sync` payload contains no key whose schema entry is `sync: false` (paths, devices, hotkeys, ports, coordinates, Keys-page fields) and is under 64 KB. |
| `test_rls_isolation_live` (integration, owner's staging project, manual or nightly-dev) | Two anonymous accounts cannot read each other's rows or objects; the publishable key alone reads nothing from any table. |

## Open points

1. **Turnstile in a Tk app.** D17 and `arch-B §7` turn Cloudflare Turnstile on for anonymous sign-ins, but Turnstile is a browser widget: a `pythonw` process cannot render it. The workable shape is a tiny page on the GitHub Pages site that renders the widget and redirects to `http://127.0.0.1:<port>/cb?token=…` on the app's one-shot listener (the same listener Google PKCE would use), after which the app passes the token in the sign-up call. That adds a browser round-trip to the first Send. Phase 0 must verify (a) anonymous sign-in availability on Free, (b) whether Turnstile can be left off with default rate limits as the abuse guard instead; D17 already names e-mail OTP from day one (which needs the domain earlier) as the fallback.
2. **SDK vs REST.** `research/supabase` designs around supabase-py with a DPAPI storage class; D12 makes `net.py` the only transport and this chapter follows D12 (REST through `net.py`). If an implementer prefers supabase-py, it must be given a transport that routes through `net.py`, or the egress-lock grep and the Network window are both defeated.
3. **Bucket limits in the migration.** Whether file-size and MIME limits can be set from SQL on the current project version, or only in the dashboard, must be checked when the migration is written; 8.11 step 6 covers the fallback.
4. **`delete_me()` and storage.** Deleting storage objects from inside a SQL function requires deleting the `storage.objects` rows; whether the underlying files are then garbage-collected by Supabase or need the storage API is to be confirmed in phase 3; if the API is needed, the client deletes its own folder first (it has the delete policy) and the RPC only removes rows.
5. **Module name.** `sb.py` is this chapter's proposal; decisions.md's file list (appendix A) does not name the client module. Any name works as long as the static-import tests target it.
6. **`report_replies.user_id`.** Denormalised for the RLS predicate; `dev/inbox.py` must copy it from the report row when inserting a reply, and a trigger should enforce that it matches.

7. **Extended by D31 (2026-09-17):** sync moves into phase 3 with the account; Google sign-in (PKCE, localhost listener) becomes the primary identity; `vocab_sync` becomes per-entry rows; a new `history` table holds dictated text for users who turn on `[privacy] history_sync`; machine-bound settings keys are flagged in the schema and never leave the PC. The migration must add `history` with its unique key and RLS, and the policy must name it.

---


# 9. Screens: new and changed, with contents and copy

This chapter implements **D18** (the sixteen screens) and carries the copy that D7 (consent cards), D11 (provider notices) and D16 (report v2) require on screen. It says, for each screen, where it lives, every element with its default, the copy, what it writes and to which file, and which existing module it extends. It does not restate the mechanics behind the screens: the config layers are chapter 3, the defaults and the "Your data" deletions are chapter 4, `privacy.allowed()`, `net.py` and the five locks are chapter 5, tiers and packs are chapter 6, report v2 internals and the outbox are chapter 7, Supabase is chapter 8, the update mechanics are chapter 11, pairing is chapter 12, the licence texts are chapter 13.

## 9.1 Conventions every screen follows

**Language.** Chrome (tabs, buttons, labels, switch names, table headers) is English, as the whole dashboard already is (`map/ui` "Screens that exist today"; house rule, `arch-A §1 P8`). Wherever the user reads a *paragraph* — the welcome sentences, a consent card body, the provider notice, the CPU-slowness explanation — the text is Hebrew and is drawn through the bitmap path, `visual_qa.text_pil` (DrawTextW + `DT_RTLREADING`), which is the one bidi path checked glyph by glyph (`problem_card.py` docstring, "RIGHT-TO-LEFT WHERE IT MATTERS"; `map/ui` "Files": `ui.draw_text` 1635-1715 is the same call for Tk surfaces). The Tk constraint that forces this: Tk has no bidi caret and a `str` whose first strong letter is Hebrew is not `editable` in the Settings page (`settings.py:81-89`, `map/ui` "How a key becomes a row" 3). Consequence for this chapter: no screen asks the user to *type* Hebrew into a Tk `ui.Field`; the only Hebrew input surface stays the report line, which already exists (`problem_card.py`, FIELD_* constants). The English copy in this chapter is the chrome as it will be built; the Hebrew paragraphs are given here in English for the coder and are marked *[HE]* — the owner writes the Hebrew (chapter 16), and the string sits in one string table per module so the guide (chapter 14) can quote it.

**Where screens live.** Three hosts exist today and nothing new is invented: (a) the *wizard*, `firstrun.py` (720x560, built on `ui.py`, does not import `main.py`; three steps today at `firstrun.py:420`, `:492`, `:509`, Hebrew labels at 522-566); (b) the *dashboard* (1160x720, six places named in `NAV`, `dashboard.py:286-288`: Home, Corrections, Problems, Said, Keys, Settings; the Settings place draws tabs from `settings.TABS` and `TAB_SECTIONS`, `settings.py:450-660`); (c) *overlay cards* painted in the app process (`overlay.py`: HintCard 1250, ProblemCard 1681-3168, ReviewCard 3172, NotifyCard 3587; ask-the-screen card in `visual_qa.py`). A "card" in this chapter is a painted overlay unless the text says "dashboard card".

**How a Settings row appears.** A new `[section]` in `defaults.toml` is drawn on the tab that owns it in `TAB_SECTIONS` (`settings.py:637`) or on Advanced; a row named by hand in `TABS` (`settings.py:450`) gets its `Friendly(path, label, help, names)` (`settings.py:323-330`); every key needs a `WORDS` entry (`settings.py:1401`) and every section a `SECTION_WORDS` entry (`settings.py:1324`), enforced by `tests.py:19325-19338`; every line must be drawn exactly once (`dashboard.py:7186-7190`). Screens 4, 5, 6, 9, 13 and 16 add rows and blocks and must keep those three invariants. Blocks that are not rows (a table, a QR, a meter) follow the pattern of the DOT card on General (`dashboard.py:7474-7663`) and the PHONE card (`7664-7690`): a canvas block above the section's rows, registered in `BLOCK_PATHS` (`dashboard.py:7109-7120`) when it consumes a key.

**What a screen writes.** Settings rows write through `_apply_setting` (`dashboard.py:7799-7822`) → the running app's `option` pipe command or `config.set_values`, which after chapter 3 writes `DATA_DIR\settings.toml`. Per-machine facts (`setup_done`, `audio.device`, chosen port, card positions) go to `state.json` (D2). Consent flips never go through a settings row: they go through `privacy.grant(kind)` / `privacy.withdraw(kind)` (chapter 5) which append to `consent.json` (D7). Keys never go through settings: `secrets.set(name)` → Credential Manager (D3).

**Owner-only elements** (git card, Push/Undo, Stop tests, branch line, `[tests]` rows, Read-aloud tab, Send a test notification, routine questions, "Open problems.md") disappear from every screen below unless `DEVELOPER` is true (D4, D15; regions listed in chapter 7). This chapter describes the user build.

## 9.2 Wizard flow (screen 1)

The wizard is rewritten from three steps to seven, keeps its window, its `ui.py` chrome and its rule that it imports nothing from `main.py` (`firstrun.py` docstring: the loading step must not start before the window). The one moment the docstring is built around — "a bar that moves when you talk" — stays step 2. The marker moves from `APP_DIR / ".setup-done"` (`firstrun.py:65`) to `setup_done = true` in `state.json` (D2, D18); `main.py --setup` still reruns it. At most four real decisions (`arch-A §1 P2`): microphone (only when more than one input exists), GPU pack (only when an NVIDIA card is found), the model download, and the three extras (one screen, one decision). Everything else is pre-filled and skippable.

| step | title (chrome) | decision required? | skippable? | writes |
|---|---|---|---|---|
| 0 | Welcome | no | — (Next only) | nothing |
| 1 | Microphone | only if >1 input device; system default pre-selected (`map/ui` rec 6a: `firstrun.py:334`, `161-170` fall back to the shipped value today) | no (the meter is the point) | `audio.device` → `state.json` (today `set_values`, `firstrun.py:639`) |
| 2 | Hardware and model | yes: "Download 1.62 GB now" [Download] / [Later] ; GPU pack switch only on tier 1/1b; English detector switch only on tier 1 | yes ("Later" leaves `backend = "local"` with no model; the dot shows "model missing", Home shows the Hardware card with a Download button) | `tier` probe result → `state.json`; model files → `DATA_DIR\models\`; packs → `DATA_DIR\packs\gpu`; `local.device` stays `auto` unless the user picks |
| 3 | Say one sentence | no | yes ("Skip") | measured decode seconds → `state.json` (`last_test_seconds`, read by the CPU copy in screen 10 and 15) |
| 4 | Keys | no (defaults shown, rebinding optional) | yes | hotkeys through `check_hotkeys` → `settings.toml` (today `dashboard.py:8257-8266` for the same dialog) |
| 5 | Optional extras | one decision (three switches, all OFF) | yes | each ON switch opens its consent card (screen 2); cloud repair → `consent.json` + `polish.prefer = "groq"` only after a key exists (else the switch leads to the Keys page, screen 3); keep awake → `awake.hold` in `settings.toml`; weekly update → `consent.json` `update_check` + `[updates] check = true` |
| 6 | Done | no | — | `setup_done = true`, `app_version`, `config_version` → `state.json` |

Per-step contents:

- **Welcome.** Three Hebrew sentences *[HE]*: "Your voice stays on this computer." / "The words you say are kept in one folder you can delete." / "Nothing is sent anywhere until you switch it on." Under them one link in English: "How to check this yourself" → opens the guide's chapter 4 URL (chapter 14) in the browser. Buttons: [Next]. The privacy policy link (D25) sits in the footer in small type.
- **Microphone.** The device list (`sounddevice`, `firstrun.py:127-158`), the live meter, the silence warning with the button to `ms-settings:privacy-microphone` (`firstrun.py:197`) — unchanged behaviour, English chrome. Hint under the meter *[HE]*: "If the bar does not move, the Windows microphone privacy switch is usually the reason." [Back] [Next].
- **Hardware and model.** Top line = the probe result from chapter 6, one of: "NVIDIA GeForce RTX 3060, 12 GB — fast transcription" / "NVIDIA card with 4-6 GB — fast, smaller mode" / "No NVIDIA card found — transcription will take about as long as you spoke" (the phase-0 number replaces "about as long as you spoke" once measured, D14 revisit). Then the download block: "Hebrew model: ivrit-ai/whisper-large-v3-turbo-ct2 · 1.62 GB · from huggingface.co · to `%LOCALAPPDATA%\DeskIT\models`" (the size comes from the `dry_run`, D13), a progress bar with bytes and a [Pause] that resumes on the next start, [Download] [Later]. Two switches under it, drawn only when the tier allows: "Use the NVIDIA card (downloads 1.3 GB of NVIDIA libraries from PyPI; NVIDIA licence)" with the EULA link (D24), and "Detect English automatically (1.6 GB more, uses 1.6 GB of video memory)" (D13). Copy under the switches on tier 2 *[HE]*: "Without an NVIDIA card DeskIT still works; later you can add a free Groq key for faster cloud transcription (Settings > Privacy)." [Back] [Next] (Next is enabled while the download runs; step 3 waits for it).
- **Say one sentence.** Today's step (`firstrun.py:492`): record 3 s, transcribe with the real backend (`firstrun.py:304-314` loads the model here). New: the result line reads "Heard: <text> — took 1.8 s" and on tier 2 adds *[HE]* "This is the speed to expect on this computer." [Back] [Next] [Skip].
- **Keys.** Today's step (`firstrun.py:509`, the board from `keycaps.py`, renamed from `keyboard.py` per D19). Unchanged apart from English labels and a footer "You can change these later under Keys."
- **Optional extras.** Three `ui.Switch` rows, all OFF: "Fix misheard words with a free cloud model (text only)" — help: "Needs your own free Groq key; the text of what you said leaves this PC."; "Keep this PC awake while DeskIT runs" — help: "Stops Windows from sleeping; you can turn it off under Settings > The app."; "Check for updates weekly" — help: "One request to github.com, no identifier sent." Flipping a switch ON opens the matching consent card (screen 2) and the switch stays OFF if the card is dismissed with [Not now]. [Back] [Next].
- **Done.** "DeskIT is ready. Hold <hotkey> and speak." with the dot's corner named, a [Open the desk] button and [Finish]. If the model download was deferred, the line becomes "DeskIT is installed; download the Hebrew model from Home when you are ready."

## 9.3 The sixteen screens

### Screen 2 — Consent cards (D7, D11; chapter 5 owns the gates)

One painted overlay layout (new module `consent_card.py`, split like `problem_card.py`: words + geometry + picture headless, `overlay.ConsentCard` owns the Tk window), opened by `privacy.request(kind)` from wherever a gated feature is first pressed, from screen 1 step 5, and from the Privacy tab (screen 4). Kinds: `cloud_text`, `cloud_audio`, `cloud_screenshots`, `account`, `report_upload`, `settings_sync`, `update_check`. Elements top to bottom, chrome English, body Hebrew *[HE]*:

| element | content |
|---|---|
| eyebrow | "TURN ON: <feature name>" (e.g. "Fix misheard words in the cloud") |
| What leaves | exact list per kind. `cloud_text`: "the text of what you just said; while you hold the key, stretches of it are sent before you release (rolling); up to 60 learned word pairs that appear in the text" (D7, `review.py:643-645` filtering). `cloud_audio`: "the recording of what you said (16 kHz WAV), up to 20 MB per request" (chapter 5, inline limit). `cloud_screenshots`: "a JPEG of the region you selected, long side ≤ 1344 px; your question; earlier questions and answers in the same card" (`map/capture` rec 3). `report_upload`: "the report line, the kind, the attachments you ticked, app version, Windows build, hardware tier". `update_check`: "nothing about you: one GET to api.github.com". `account`: "an anonymous id created for you; no e-mail". `settings_sync`: "your changed settings and learned words; never recordings or history" (D17). |
| To whom / under whose account | "to Groq (api.groq.com) under **your** Groq key" / "to Google (generativelanguage.googleapis.com) under **your** Gemini key" / "to the developer's Supabase project in Frankfurt under your anonymous account" / "to GitHub". The host names are the same strings as `ALLOWED_HOSTS` (chapter 5) and are drawn from it, not retyped. |
| The provider's own sentence | quoted verbatim, chosen by the key that will be used. Gemini (free tier): inputs are used "to provide, improve, and develop Google products"; "human reviewers may read, annotate, and process your API input and output"; "Do not submit sensitive, confidential, or personal information to the Unpaid Services"; not available in the EEA/UK/Switzerland; 18+. Groq: "not permitted to use Inputs or Outputs for training"; no retention by default, 30-day abuse logs unless Zero Data Retention; 18+ (D11, `research/keys-privacy`, `research/legal`). Each card carries `text_version` (D11). |
| How to turn it off | "Settings > Privacy > <feature> — Off. Switching off tears the connection down immediately." |
| checkbox | "I have read the provider's terms" — required before [Turn on] enables, only for the three provider kinds (D11 "with a checkbox") |
| buttons | [Turn on] [Not now]; Esc = Not now |

Writes: `consent.json` row `{kind, text_version, when, app_version}` (D7). If the kind needs a key that is missing, [Turn on] records consent and then opens screen 3 with the matching row focused. The card never shows a key.

### Screen 3 — Dashboard > Keys (the *API keys* block, D10-D12)

Lives on Settings > Privacy as a block titled "YOUR CLOUD KEYS" (the dashboard's Keys place, `dashboard.py:6520`, remains the *hotkeys* board; the name clash is resolved by never calling this block "Keys" in chrome). Two rows, Groq first (recommended, D10), Gemini second. Each row: provider name + "Get a free key" link (console.groq.com / aistudio.google.com); a masked `ui.Field` (bullets, paste only, no reveal); [Test] (one allowed call through `net.py` with `purpose = "key-test"`, result "Works · 4 models visible" or the provider's error text); [Remove] (`secrets.delete`, tears down the client); a status line "Stored in Windows Credential Manager as DeskIT/groq · added 2026-10-02". The daily quota meter under each row: "Today: 37 of 1,000 requests" (counts kept in `state.json` per key name per day, reset at local midnight; limits from chapter 5's table; the meter is an estimate and says so). The storage sentence, fixed wording from `arch-B §4` and repeated by the guide: "This key is stored in Windows Credential Manager on this PC (Control Panel > Credential Manager > Windows Credentials > DeskIT/groq). DeskIT sends it only to api.groq.com. It is never written to a file, a log or a report, and never sent to the developer — see Dashboard > Network for every request." The provider notice (D11) is shown once under the field on first paste as the same block screen 2 uses, with the checkbox. No Cerebras row (D6). Writes: Credential Manager only (D3); `[polish] prefer` / `[punctuate] prefer` are *not* flipped here — they flip on the consent card.

### Screen 4 — Settings > Privacy (new tab)

Add `"Privacy"` to `TABS` after General and own the new `[privacy]`, `[history]` and `[updates]` sections in `TAB_SECTIONS`. Rows and blocks, in order:

1. Block "WHAT MAY LEAVE THIS PC": one line per gate, seven lines — feature name, state, "on since 2026-10-02 (terms v3)" from `consent.json`, and a [Turn on]/[Turn off] `ui.Button` (not a Switch: turning on must go through screen 2, turning off is immediate and calls `privacy.withdraw`). Sub-line under `cloud_audio` on tier 2: "Cloud transcription with your Groq key (whisper-large-v3-turbo)".
2. Block "YOUR CLOUD KEYS" (screen 3).
3. Row `privacy.offline` — Switch "Offline mode" — help: "Refuses every connection except the phone on your own network. Cloud features say 'offline' instead of working." Default `false`. Written through `set_values`; `net.py` reads it live (chapter 5).
4. Group "HOW LONG THINGS ARE KEPT" (chapter 4 owns the semantics): `history.keep_days` Dropdown names 7 / 30 / 90 / Forever (0 = "Off"; default 30); `vocab.keep_audio` Dropdown 0 ("Keep none") / 10 / 20 (default 20) / 50; `review.keep_audio` 0 / 3 (default 3); `problems.keep_audio` (existing key, `config.toml:1216`).
5. Row: clipboard caveat as a help-only line under `capture.copy_to_clipboard`'s twin here: "Text pasted at the cursor goes through the Windows clipboard; Windows clipboard history (Win+V) and cloud clipboard sync may keep a copy — that is a Windows setting, not DeskIT's." (`map/capture` rec 13).
6. Block "ACCOUNT" (screen 16).

Writes: `settings.toml` for rows; `consent.json` for gate changes.

### Screen 5 — Settings > Your data (D9; chapter 4 owns what each button deletes)

A new tab "Your data" after Privacy, replacing the FILES card on The app (`dashboard.py:7401-7438`, `tk.Label "FILES"` at 7422). One canvas table, one row per store: name, path under `DATA_DIR`, size, oldest item, and one button. Rows: Learned words (Forget a word → a small picker over `vocab.json` terms, since a list is not editable in a Tk field), History (Clear history), Recordings (Delete recordings: recent / pending / corpus), Reports (Delete reports), Lookups (Delete lookups), Hebrew model (Delete the model — the Hardware card then offers re-download), Logs (Open the folder). Under the table: [Export everything] (zip to a folder the user picks), [Delete everything on this PC] (confirm dialog names the folder, Credential Manager entries, the Startup entry and the hook entries, D9), and "Where my data lives: `%LOCALAPPDATA%\DeskIT`" with [Open the folder]. The retention sentence from chapter 4 is printed at the foot. Delete my account (screen 16) is linked from here too.

### Screen 6 — Dashboard > Network (D12 window)

A new place is *not* added to `NAV` (the docstring at `dashboard.py:259` argues for few places); Network is the third tab-like block on Settings > Privacy? No — D18 names it "Dashboard > Network", so it is a seventh entry in `NAV` (`dashboard.py:286-288`), drawn last, with a door on Home's band (`dashboard.py:3213-3345`) counting "requests today". Contents: an append-only table (newest first) of every outbound request from `net.py` (chapter 5): time, host, purpose, bytes out / in, secret name (never the value), consent kind that authorised it, result. A host filter Dropdown (All / each host seen / loopback), a "Show loopback (phone)" toggle default off, [Open network.log], and a status line: "During plain dictation this table stays empty — that is the proof." When Offline mode is on, a banner "Offline mode: every host but 127.0.0.1 is refused." Reads `logs\network.log`; writes nothing.

### Screen 7 — Report a problem v2 + Preview (D16; chapter 7 owns the payload and outbox)

Both surfaces stay: the painted hotkey card (`problem_card.py` + `overlay.ProblemCard`) and the dashboard box (`dashboard.py:5586-6229`), sharing strings from `problem_card.py` (its docstring: "the shared thing between the two surfaces is the LAYOUT AND THE COPY"). Changes to `card_for` (`problem_card.py:156`): the card dict gains `attach` (dict of four booleans with byte sizes), `send` (bool) and `sizes`. Elements top to bottom: eyebrow "ON <where>" (unchanged); title `TITLE = "What is wrong?"` (unchanged, `problem_card.py:103`); the Hebrew line field, 3-8 lines, 600 chars (`problems.TEXT_MAX`, `problems.py:127`); kind chips from `problems.KINDS` = wrong / broken / slow / idea / other (`problems.py:122`); then a new **attachments strip** of four toggles with sizes: "Screenshot (monitor under the mouse) · 214 KB" default ON for the local copy, "Recording · 1.1 MB" default OFF, "Transcript text · 0.4 KB" default ON only when kind = wrong, "Settings snapshot · 6 KB" default ON (whitelist + redactor, D8). The thumbnail and `SHOT_CAPTION` ("The screen as it was a moment before this box opened…", `problem_card.py:107`) are drawn only when the Screenshot toggle is ON (`arch-B §8` item 7: caption becomes conditional). `HINT` (`problem_card.py:104`, "…are attached for you") is replaced by "Tick what goes with it." A checkbox "Send to the developer" default OFF; when OFF the buttons are [Keep on this PC] [Cancel]; when ON they are [Preview…] [Cancel], and `SEND_LABEL` "Send" moves to the Preview window. If `report_upload` consent is missing, ticking the checkbox opens screen 2 first. **Preview** (a `ui.Card` Toplevel in the dashboard; from the hotkey card it opens the dashboard on Problems with the preview): the exact JSON that will be uploaded (read-only, monospace, redacted), then each ticked attachment (the JPEG scaled, the WAV as a duration line with a play button, the transcript text, the settings JSON), then [Send] [Keep on this PC]. Writes: `problems.json` + `problems\<id>\` locally always; a copy into `problems\outbox\` when Send is pressed (chapter 7). `KEYS` line ("Enter sends · Shift+Enter…", `problem_card.py:106`) becomes "Enter continues · Shift+Enter for a new line · Esc cancels" because Enter no longer sends when the checkbox is on.

### Screen 8 — Report replies row on Problems

On the Problems place (`dashboard.py:4025`, reports list 4093-4572), under a sent report: a reply row "Developer replied 2026-10-03: fixed in 1.9.2 — did it help? [Yes] [No]" (`arch-B §8` item 8). [Yes] marks the report fixed (the existing "fixed?" mark, D15), [No] reopens it; both write back through the outbox (chapter 7). A sent report shows a status chip: Queued / Sent / Replied / Fixed. Removed from this place: the "Changes on this computer" card with Push/Undo (5228-5407), the routine's questions (4574-5122) and "Open problems.md" (D15, D16) — chapter 7 lists the line ranges.

### Screen 9 — Settings > Phone (D22; chapter 12 owns the protocol)

The existing Phone tab (`settings.py:618-626`; PHONE card `dashboard.py:7664-7690` with the Tailscale URL + Copy link) is rebuilt as one block above the `[server]` rows: a Dropdown "How the phone reaches this PC" with names Off / Home Wi-Fi / Tailscale (writes `server.transport`, default `"off"`; `server.enabled` follows it); when not Off: a pairing QR (payload `deskit://pair?host=…&port=…&fp=<sha256>&token=<one-time>`; the one-time token expires in 10 minutes and the QR regenerates), a second QR "Install the keyboard" pointing at the GitHub Release APK URL (later Play), a "Paired phones" table (name, last seen, [Forget], [Rotate token]), the firewall note *[HE]* "Windows will ask once whether DeskIT may accept connections on your private network — answer Yes for private networks only.", and the PC's fingerprint in short form so the phone's pairing screen can be compared. The token is never drawn as text unless [Reveal] is pressed, and then for 30 s. On Tailscale: a text line "Use the Tailscale IP of this PC on the phone" instead of the hard-coded tailnet URL (`Prefs.kt:25` DEFAULT_URL is deleted, D22). Writes: `server.transport`, `server.port` → `settings.toml`; per-phone tokens → `secrets\phones.bin` (DPAPI, D3); chosen port → `state.json` (D5).

### Screen 10 — Hardware card on Home (D14)

On Home (`dashboard.py:1746-1860`), a dashboard card in the footer strip area (1838-1856, where the branch line used to be) titled "HARDWARE": the active tier in one line — "NVIDIA RTX 3060 · GPU float16" / "NVIDIA 4 GB · GPU int8_float16" / "CPU int8 — about as long as you spoke (measured 4.2 s for your test sentence)" — replacing the log-only fallback at `local_whisper.py:409-415`. Under it, state-dependent buttons: [Download the model] when `models\` is empty; [Enable the NVIDIA card] on tier 1/1b when the pack is absent; "CUDA failed, using CPU — [Details]" when the pack exists but loading failed (D14: never silently). Reads `state.json` (`tier`, `last_test_seconds`); writes nothing itself.

### Screen 11 — Update available card (D21; chapter 11 owns verification)

A dashboard card on Home above the pile, shown when the weekly check found a newer `latest.json`: "DeskIT 1.10.0 is available · 412 MB · SHA-256 3f9c…" with [Download and install] [Release notes] [Skip this version]. Download progress replaces the buttons; "Verified" appears after the hash check and before Inno runs; a failed hash shows "The download did not match — nothing was installed" and the [Download] button again. [Skip] writes `updates.skipped_version` to `state.json`. Beta channel is the `updates.channel` row on Settings > The app (stable / beta). Store builds never show this card (Store auto-update).

### Screen 12 — Ask-the-screen first press without Ollama (D14, `map/capture` rec 4)

Where today a raw `QAError` surfaces when `127.0.0.1:11434` does not answer, the ask-the-screen card (`visual_qa.py`) paints three buttons: [Install Ollama and a small vision model (about 3 GB)] (opens ollama.com and, on 8 GB cards, names `gemma3:4b`; on CPU the button says "Not recommended on this PC" and is disabled), [Use my own Groq/Gemini key] (opens screen 2 `cloud_screenshots`, then screen 3 if no key), [Turn this key off] (writes `visual_qa.enabled = false`). Body *[HE]*: "Ask-the-screen needs a model that can see. Ollama runs one on this PC; a cloud key sends the screenshot to Groq or Google under your own account." Every answer keeps the existing "answered in 2.1 s via ollama" line (`visual_qa.py:3777`) so the backend is visible.

### Screen 13 — Snipping Tool toggle in Settings > Screen (D25)

A hand-named row on the Screen tab: `capture.take_snip_shortcut` (new bool, default `false`), label "Replace the Windows screen-snip shortcut (Win+Shift+S) while DeskIT runs", help "Windows' own Snipping Tool stops answering that shortcut until DeskIT exits. The screenshot key stays Ctrl+F11 otherwise." (`map/capture` rec 1: `hotkey._takes_the_key` already handles it once on). A second line with a link "Make DeskIT the default screen-snip app instead" → the `ms-screenclip` handler route described in chapter 13. Writes `settings.toml`.

### Screen 14 — About (D23, D24)

On Settings > The app, replacing the THE APP block's branch line (`dashboard.py:7691-7776`): "DeskIT <VERSION> · <tier> · Apache-2.0" (version from `version.py`), then buttons: [Third-party notices] (opens `THIRD-PARTY-NOTICES.txt`), [Verify this install] (runs `--verify`, chapter 10, and shows "All 1,412 files match the manifest" or the first mismatch), [Source code] [Privacy policy] [Report a security issue] (SECURITY.md). Two attribution lines, always: "Hebrew speech model by ivrit.ai (Apache-2.0)" and, while the default Groq repair model is a Llama, "Built with Llama". Fonts: "Rubik, SIL Open Font License" (`map/ui` rec 11). Restart stays here; "Stop the app" stays; "Send a test notification" is DEVELOPER-only.

### Screen 15 — CPU-slowness card (D14)

A painted overlay (NotifyCard style, `overlay.py:3587`) shown once, the first time a tier-2 decode exceeds 10 s, and remembered in `state.json` (`cpu_notice_shown`). Body *[HE]*: "That took 14 s. On a computer without an NVIDIA card DeskIT transcribes at about the speed you spoke. Two ways to make it faster: shorter holds, or cloud transcription with your own free Groq key (the recording leaves this PC)." Buttons: [Use cloud transcription] (opens screen 2 `cloud_audio`), [Fine, keep it local], [Don't show again]. The dot's "transcribing…" state (D14) is the permanent signal; this card is the one-time explanation.

### Screen 16 — Account (D17; chapter 8 owns the flows)

A block on Settings > Privacy (and linked from Your data): "ACCOUNT — none" until the first Send or Sync creates an anonymous account, then "Anonymous id a1b2…f9 · created 2026-10-02 · Frankfurt (Supabase)". Buttons: [Link an e-mail] (phase 5; hidden until the OTP flow ships), [Delete my account] → confirm dialog *[HE]* "This removes your reports, replies and attachments from the developer's server and the account itself. Your data on this PC stays." → `delete_me()` RPC (chapter 8), then the block returns to "none". The terms page (D25) is shown once, in the account consent card, before the first account is created.

## 9.4 Module map: which existing module each screen extends

| screen | module(s) | what changes |
|---|---|---|
| 1 wizard | `firstrun.py` | steps `_step_mic` (420) / `_step_say` (492) / `_step_done` (509) kept; new `_step_welcome`, `_step_hardware`, `_step_extras`; MARKER (65) → `state.json`; labels 522-566 → English + string table; `set_values` (639) → `state.json` writer |
| 2 consent | new `consent_card.py` + `overlay.ConsentCard`; `privacy.py` | pattern copied from `problem_card.py` / `overlay.ProblemCard` (1681-3168) |
| 3, 4, 16 | `settings.py` TABS (450), TAB_SECTIONS (637), WORDS (1401), SECTION_WORDS (1324); `dashboard.py` `_screen_settings` (6896), block pattern (7474-7663) | new tab Privacy; blocks Keys / Gates / Account; `_ENGINES` (`settings.py:348-350`) loses "fake" |
| 5 | `dashboard.py` FILES card (7401-7438) → new tab; `settings.py` TABS | |
| 6 | `dashboard.py` NAV (286-288), `_show` map (1650-1655), band (3213-3345) | seventh place |
| 7, 8 | `problem_card.py` (`card_for` 156, strings 103-110), `overlay.ProblemCard`, `dashboard.py` report box (5586-6229) and Problems place (4093-4572) | attachments strip, Send checkbox, Preview, reply row |
| 9 | `dashboard.py` PHONE card (7664-7690), `settings.py` Phone tab (618-626) | transport, QRs, paired phones |
| 10, 11 | `dashboard.py` Home (1746-1860, footer 1838-1856) | two dashboard cards |
| 12 | `visual_qa.py` card (the ask-the-screen surface) | three-button state |
| 13 | `settings.py` Screen tab (533) + `config.py` `[capture]` dataclass | one bool |
| 14 | `dashboard.py` THE APP block (7691-7776) | About |
| 15 | `overlay.py` NotifyCard-style card (3587) | one-time card |

Layout risks carried from `map/ui` rec 9: every new block must fit the fixed 1160x720 window at 125 % and 150 % DPI, and the wizard's 720x560 at the same; the icon font is picked at runtime (`ui.py:226-240`).

## Acceptance

- A stranger on a clean Windows 11 VM reaches a Hebrew sentence on screen through the wizard with at most four decisions, never types a path, an index or a key, and sees no Hebrew in Tk chrome and no English where a paragraph is read (checked by the phase-2 VM run, chapter 15).
- Every gate in `[privacy]` can be turned on only through its consent card; the Privacy tab shows the consent date and `text_version` for each; turning off is immediate.
- The Keys block never renders a key value; Credential Manager shows `DeskIT/groq` after a paste; [Remove] empties it.
- Dashboard > Network shows only loopback rows (or none) after a session of plain dictation.
- Report v2: with "Send to the developer" unticked nothing reaches `problems\outbox\`; with it ticked, the Preview shows the exact bytes that later appear in the outbox file.
- The Settings invariants still hold: every line of `defaults.toml` drawn once, every key in `WORDS`, every section in `SECTION_WORDS`, no coordinate rows on any tab.
- Every new block renders inside the fixed window at 100 / 125 / 150 % DPI without clipping (screenshot run on the hidden desktop, per the owner's rule).
- No owner-only element is drawn when `DEVELOPER` is false.

## Tests to add

| test | asserts |
|---|---|
| `test_wizard_steps_order_and_writes` | the seven steps appear in order; finishing writes `setup_done`, `app_version`, `config_version` to `state.json` and nothing to `APP_DIR`; "Later" on step 2 finishes with no model and Home's Hardware card offering Download |
| `test_wizard_mic_default_is_system_default` | with a shipped `audio.device = ""` and two fixture devices, the pre-selected row is the system default (`firstrun.py:334` path) |
| `test_wizard_decisions_at_most_four` | with a fixture tier-2 machine and one input device, the wizard requires exactly one decision (model) plus the extras screen; tier-1 adds the GPU switch |
| `test_wizard_extras_off_by_default_and_gated` | the three switches start OFF; flipping one opens a consent card; [Not now] leaves it OFF and `consent.json` untouched |
| `test_consent_card_text_per_kind` | `consent_card.card_for(kind)` yields the "what leaves" list, the host from `ALLOWED_HOSTS`, the provider sentence and a `text_version` for all seven kinds; the Gemini card carries the four D11 sentences verbatim; the Groq card the training sentence |
| `test_consent_card_checkbox_gates_turn_on` | [Turn on] is disabled until the terms checkbox is ticked for `cloud_text/audio/screenshots`; not required for `update_check` |
| `test_consent_card_headless_render` | `consent_card.compose` renders every kind to a PNG with no Tk, Hebrew body right-aligned, chrome left-aligned (same style as the existing problem-card render tests) |
| `test_keys_block_never_shows_value` | after `secrets.set("groq", fixture)`, the rendered block's strings contain no substring of the fixture; the status line names `DeskIT/groq` |
| `test_keys_block_test_button_uses_net` | [Test] issues exactly one call through `net.py` with `purpose="key-test"` to the provider host and no other host |
| `test_privacy_tab_rows` | Settings > Privacy draws seven gate lines with dates from a fixture `consent.json`, the Offline switch, the four retention pickers with the D6 defaults, and no key value |
| `test_privacy_gate_off_is_immediate` | pressing [Turn off] on a granted gate calls `privacy.withdraw` and the next `privacy.allowed(kind)` is False without restart |
| `test_settings_invariants_with_new_tabs` | the existing "every line drawn once" and "every key has words" assertions (`dashboard.py:7186-7190`, `tests.py:19325-19338`) pass with Privacy, Your data and the new sections; no `x`/`y`/`scale`/`device` row is drawn |
| `test_your_data_rows_match_stores` | one row per store in `DATA_DIR`, sizes computed from fixture files, and each button maps to the chapter-4 deletion function |
| `test_network_place_reads_log` | a fixture `network.log` renders rows with host, purpose, bytes and consent kind; the host filter narrows; loopback hidden by default; the Offline banner appears when `privacy.offline` is on |
| `test_report_card_attachments_and_send` | `card_for` defaults: screenshot ON, recording OFF, transcript ON only for kind "wrong", settings ON, send OFF; the caption is absent when screenshot is OFF; buttons read [Keep on this PC]/[Cancel] with send OFF and [Preview…]/[Cancel] with send ON |
| `test_report_preview_equals_outbox` | the JSON shown in Preview is byte-identical to the file written to `problems\outbox\` on Send, and contains no key-shaped string with a fixture key set (ties to D12 lock 4) |
| `test_report_strings_shared_by_both_surfaces` | the dashboard box and the painted card use the same TITLE/HINT/KEYS strings (existing comparison test extended to the new strings) |
| `test_reply_row_yes_no` | a fixture `report_replies` row renders under its report; [Yes] marks fixed, [No] reopens; both enqueue a write-back |
| `test_phone_tab_transport_and_token_hidden` | the transport dropdown writes `server.transport`; the QR payload matches `deskit://pair?host=…&port=…&fp=…&token=…`; the token string never appears in the rendered tab unless Reveal was pressed, and disappears after 30 s |
| `test_home_hardware_card_states` | tier fixtures render the three lines; empty `models\` shows [Download the model]; a CUDA-load failure shows the visible fallback line, never only a log entry |
| `test_update_card_flow` | a newer fixture `latest.json` shows the card with version/size/SHA; a bad hash shows the failure line and no installer launch; Skip writes `updates.skipped_version`; no card in a Store build |
| `test_ask_screen_no_ollama_card` | with 11434 closed and no key, the card shows the three buttons; the Ollama button is disabled on tier 2; [Turn this key off] writes `visual_qa.enabled = false` |
| `test_snip_toggle_default_off` | `capture.take_snip_shortcut` defaults to False, is drawn on Screen, and `hotkey._takes_the_key` only claims Win+Shift+S when it is True |
| `test_about_block` | About shows `VERSION`, the tier, "Apache-2.0", the ivrit.ai line, "Built with Llama" iff the default `polish.groq_model` starts with "llama", and the four links |
| `test_cpu_card_once` | the first decode > 10 s on tier 2 shows the card; `cpu_notice_shown` is set; a second slow decode shows nothing; tier 1 never shows it |
| `test_account_block_states` | "none" without a session; the anonymous id and region with a fixture session; [Delete my account] calls the RPC and returns the block to "none" |
| `test_no_hebrew_in_chrome_no_owner_ui` | every `ui.Button`/Tab/Switch label in the user build is ASCII; with `DEVELOPER=False` none of the owner-only regions (chapter 7 list) is drawn on any place |
| `test_layout_fits_at_dpi` | headless render of each new block at 100/125/150 % stays within 1160x720 (dashboard) and 720x560 (wizard) |

## Open points

1. **Network as a seventh place vs a Privacy block.** D18 (6) and `arch-B §8` item 6 say "Dashboard > Network"; `dashboard.py:259` argues for few places. This chapter follows the decision (seventh `NAV` entry) and notes the alternative (a block on Privacy with the same table) if the Home band gets crowded.
2. **"Keys" name clash.** The hotkeys place is called Keys (`NAV`), and D18 (3) calls the API-key screen "Keys page". This chapter draws the API keys as the block "YOUR CLOUD KEYS" on Privacy and keeps the place name for hotkeys; the guide must use the same two names.
3. **Who writes the Hebrew paragraphs.** Every *[HE]* string is given in English for the coder; the owner's Hebrew is a chapter-16 hand item, and until it exists the string table falls back to the English text so the build never shows an empty card.
4. **Quota meter accuracy.** Provider dashboards, not the app, are the truth; the meter counts requests the app made today and says "estimate". Whether a wrong number is worse than none is a phase-2 usability question (D18 revisit).
5. **Step 2 "Later" and the cloud path.** A tier-2 user who defers the model and has no key has no working backend; the Home Hardware card carries the Download button, but the dot's "model missing" state copy is not specified in any decision and is proposed here as one line.


---

# 10. Packaging, installer, signing and channels

Implements D19 and D20; produces the build lock of D12 (lock 5) and the artefacts chapter 11 consumes
(`DeskIT-Setup-x.y.z.exe`, `latest.json`, the winget manifest, the `CHANNEL` marker). Chapter 3 owns the
installed layout and the forbidden-files list; chapter 6 owns what packs do once installed; chapter 11
owns versions, the update check and the release checklist; chapter 13 owns the licence texts this chapter
copies into the tree. This chapter is the recipe that turns a git tag into the three things a stranger can
install, and the reason each step exists.

## 10.1 What we build and why (D19)

Today there is nothing to build: the app runs from the working folder through a venv whose `pyvenv.cfg`
pins an absolute python.org 3.11.9 path, launched by `DeskIT.vbs` → hidden `.venv\Scripts\pythonw.exe
main.py` (`map/packaging` "How the app is started today" items 3 and 6). `requirements.txt` is unpinned
and incomplete (no `pillow`, an unused `keyboard` package that the local `keyboard.py` shadows,
`map/packaging` risk 14), the NVIDIA wheels are 1,986 MB of a 2,398 MB venv (`map/packaging` pip table),
and `transcribers/local_whisper.py:50-79` finds the CUDA DLLs by scanning `sys.path` for the pip
`site-packages/nvidia` layout (`map/packaging` risk 6).

The decision (D19): **the installed product is the python.org embeddable CPython 3.11 plus a vendored
wheelhouse plus the real `.py` tree. Nothing is frozen.** Four reasons, in the order the evidence weighs
them:

| Reason | Evidence |
|---|---|
| Antivirus reputation. Every option ships unsigned in v1 (10.8), so Defender heuristics are the only differentiator. `python.exe`/`pythonw.exe` are stock python.org binaries with years of reputation; PyInstaller's shared bootloader hash is "the worst false-positive magnet" and its own tracker is still open on it; Nuitka's own docs admit vendors flag default builds and point to the paid Commercial edition. | `research/packaging` S1, S9, S22 and the options table |
| Deterministic CUDA paths. CTranslate2 loads cuBLAS/cuDNN lazily by plain `LoadLibrary`, so the DLL directories must be on `PATH` before the first inference; with a pip-installed pack the path is a known constant, with a freezer it is rediscovered per build. | `research/packaging` S2; chapter 6 §6.5 step 3 |
| Reproducibility file by file. A tree of stock binaries plus hashed wheels plus `git archive` can be listed in `MANIFEST.sha256` and recomputed on the user's disk by `deskit --verify`; a frozen bundle cannot (D12 lock 5). | chapter 5 §5.9 |
| Field diagnosis with real source. A user can run `python\python.exe app\main.py --diagnose`; frozen tracebacks name nothing useful. | `research/packaging` recommendation item 5 |

Python's own documentation blesses this layout: the embeddable distribution "is intended for acting as
part of another application", third-party packages "should be installed by the application installer
alongside the embedded distribution", and Tcl/Tk is not included (`research/packaging` S14). So the one
hand-made step is copying the tcl/tk tree from a full 3.11 install (10.3 step 3).

Ruled out and why: PyInstaller/Nuitka/cx_Freeze in v1 (reputation, CUDA paths, Nuitka's open tk-inter
bugs #2730/#3019, `research/packaging` S29); MSIX outside the Store, because "Windows requires MSIX
packages to be signed with a valid code signing certificate" (`research/signing` S17) and no free
certificate exists for the owner (10.8); a custom launcher `.exe` in the GitHub build, because a new
unknown hash is exactly what SmartScreen and Defender score against (`research/packaging` recommendation).
The only executable this plan adds is the Store launcher stub of 10.7, which the Store signs.

Fallback, recorded so nobody re-researches it: if the phase-0 VirusTotal scan of a throwaway embeddable
build is worse than expected (D19 revisit clause), the alternative is PyInstaller **onedir** with a
locally rebuilt bootloader, `--windowed`, `--collect-all ctranslate2`; never onefile, never Nuitka
(`research/packaging` recommendation, last paragraph).

## 10.2 The installed tree

The two roots are chapter 3's (D1); this section lists only what the build puts into `APP_DIR =
%LOCALAPPDATA%\Programs\DeskIT` and where each piece comes from.

| Path under `APP_DIR` | Contents | Produced by |
|---|---|---|
| `python\python.exe`, `pythonw.exe`, `python311.dll`, `python311.zip`, `*.pyd`, `vcruntime140*.dll` | python.org "Windows embeddable package (64-bit)" 3.11.x, unzipped unchanged | 10.3 step 2 |
| `python\python311._pth` | the four lines the embeddable zip needs to see site-packages: `python311.zip`, `.`, `Lib\site-packages`, `import site` (the stock file lacks the last two, `research/packaging` S12/S14) | 10.3 step 4, a file committed under `packaging\` |
| `python\tcl\tcl8.6`, `python\tcl\tk8.6`, `python\Lib\tkinter\`, `python\DLLs\_tkinter.pyd`, `tcl86t.dll`, `tk86t.dll`, `zlib1.dll` | the Tk tree the embeddable zip lacks | 10.3 step 3 |
| `python\Lib\site-packages\` | the base wheelhouse installed with `--no-index --require-hashes` from `requirements.lock` (10.5 lists it) | 10.3 step 1 and 5 |
| `app\` | `git archive` of the tag: every product `.py`, `defaults.toml`, `fonts\` (four Rubik cuts + `OFL.txt`), `skin\`, `cues\` pre-rendered, `icon.ico`, `packs\*.lock`, `VERSION` | 10.3 step 6 |
| `app\deskit.pyw` | the shortcut target; today's `main.py` entry with the `.vbs` hop removed (D19: `python\pythonw.exe app\deskit.pyw`) | chapter 3 |
| `LICENSE`, `NOTICE`, `THIRD-PARTY-NOTICES.txt`, `OFL.txt`, `NETWORK.md`, `SECURITY.md` | chapter 13 texts, the allowlist page from chapter 5 | copied by 10.3 step 6 from the archive |
| `MANIFEST.sha256` | one line per file under `python\` and `app\`: SHA-256, size, relative path; sorted; itself excluded | 10.3 step 7 |
| `CHANNEL` | one word: `github`, `winget` or `store` (10.4, answers chapter 11 open point 1) | the installer at install time, or the MSIX build |
| `unins000.exe`, `unins000.dat` | Inno's uninstaller | Inno |

Absent on purpose: `.venv`, any `.vbs` (`DeskIT.vbs`, `Dashboard.vbs`, `Stop DeskIT.vbs` are replaced by
the shortcut, the dashboard's own relaunch command in `dashboard.py:596-613` re-pointed at `pythonw.exe`,
and the `--stop` flag), `pip` and `setuptools` (not shipped, `map/packaging` pip table last row; the pack
installer of chapter 6 needs pip, so the base wheelhouse carries the `pip` wheel as a plain package and
runs it as `python -m pip`, which the embeddable docs permit "with some care", `research/packaging` S14),
every file in chapter 3 §3.10's forbidden list, and every model, CUDA or FFmpeg byte (D13, D24).

Startup, Start menu and the shortcut: the installer creates one Start-menu shortcut "DeskIT" whose target
is `python\pythonw.exe`, arguments `"app\deskit.pyw"`, working directory `APP_DIR`, icon `app\icon.ico`,
and the AppUserModelID `DeskIT.App` set on the shortcut so the taskbar and Task Manager show "DeskIT"
instead of "pythonw" (D5; chapter 3 §3.9). Today's Startup-folder `.lnk` that runs `wscript.exe`
(`map/packaging` "How the app is started today" item 1) is not recreated by the installer; **"Start with
Windows" is owned by the app**: a switch on Settings > The app writes or removes the `HKCU\Software\
Microsoft\Windows\CurrentVersion\Run` value `DeskIT` with the same target and arguments, records
`autostart` in `state.json`, and re-asserts the value at every start so a moved or upgraded install never
points at a stale path. The wizard's Done step ticks it on by default (it is a pre-ticked switch, not one
of D18's four decisions). "Delete everything on this PC" and the uninstaller remove the value (chapter 4
§4.8).

## 10.3 The build pipeline (D12 lock 5, D19)

One workflow, `.github/workflows/release.yml`, triggered by a tag `v*` (and by hand with a `dry-run`
input that builds but publishes nothing). It runs on `windows-latest`, never on the owner's PC, so the
build lock holds: every byte in `APP_DIR` traces to the tag, a hashed wheel or a SHA-verified python.org
download (D12 lock 5). Inputs it reads from the repo: `VERSION` (chapter 11), `requirements.lock`
(hash-pinned, generated by `pip-compile --generate-hashes` from `requirements.txt` in phase 1),
`packaging\python311._pth`, `packaging\DeskIT.iss`, `packaging\python-embed.sha256` (the SHA-256 of the
python.org zip, updated by hand when the Python patch version moves), `packs\*.lock` (chapter 6).

| Step | Job / name | What it does | Fails when |
|---|---|---|---|
| 0 | `checkout` | `actions/checkout` at the tag, full history off | tag missing, `VERSION` differs from the tag |
| 1 | `wheelhouse` | `pip download -r requirements.lock --require-hashes --only-binary=:all: --platform win_amd64 --python-version 3.11 -d wheels\` on a full 3.11 runner Python; the `pip` wheel is added as a plain package so chapter 6's pack installer can run `python -m pip` (10.2) | any wheel's hash differs from the lock; a package has no cp311 win_amd64 wheel (sdists are refused, so nothing is compiled on the runner) |
| 2 | `embed` | download `python-3.11.x-embed-amd64.zip` from python.org; compare with `packaging\python-embed.sha256`; unzip into `stage\python\` | SHA mismatch |
| 3 | `tk` | copy `tcl\`, `Lib\tkinter\`, `DLLs\_tkinter.pyd`, `tcl86t.dll`, `tk86t.dll`, `zlib1.dll` from the runner's full 3.11 install of the same patch version into `stage\python\` (`research/packaging` S14) | the runner's Python patch version differs from the embeddable one (checked, because `_tkinter.pyd` is built against one `python311.dll`) |
| 4 | `pth` | overwrite `stage\python\python311._pth` with the committed `packaging\python311._pth` (10.2) | never; a test asserts the four lines |
| 5 | `install` | `python -m pip install --no-index --find-links wheels\ --require-hashes -r requirements.lock --target stage\python\Lib\site-packages`, then delete `__pycache__`, `*.dist-info\RECORD` stays (it is what `pip-licenses` reads for `THIRD-PARTY-NOTICES.txt`, D24) | pip touches the network (`--no-index` makes that an error) |
| 6 | `archive` | `git archive` of the tag into `stage\app\`; the `export-ignore` attributes of `.gitattributes` drop `dev\`, `tests\`, `docs\`, `.github\`, `packaging\`, `android\` (chapter 3 §3.10's forbidden list); copy `LICENSE`, `NOTICE`, `OFL.txt`, `NETWORK.md`, `SECURITY.md` to the stage root; generate `THIRD-PARTY-NOTICES.txt` with `pip-licenses --with-license-file` over step 5's target plus the hand entries of D24 (chapter 13) | `dev/test_public_tree.py::test_no_owner_strings_in_archive` (chapter 16) is run against the stage and fails |
| 7 | `manifest` | write `stage\MANIFEST.sha256` (10.2 format) over `python\` and `app\`; `deskit --verify` (chapter 5 §5.9) reads the same format | never |
| 8 | `attest` | `actions/attest-build-provenance` over `MANIFEST.sha256` and, after step 10, over `DeskIT-Setup-x.y.z.exe`; the attestation is what the FAQ's "read the build attestation" line points to (D12 lock 5) | the workflow lacks `id-token: write` / `attestations: write` |
| 9 | `channel` | write `stage\CHANNEL` = `github`; the winget variant is the same installer, so the installer itself rewrites `CHANNEL` to `winget` when run with `/CHANNEL=winget` (10.4, 10.6); the Store job writes `store` (10.7) | — |
| 10 | `inno` | `ISCC.exe packaging\DeskIT.iss /DVersion=x.y.z /DStage=stage` → `DeskIT-Setup-x.y.z.exe`; Inno Setup 6 is installed on the runner by its official installer (`research/packaging` S19-S20: free for any use) | the script's `AppVersion` is not the `VERSION` value |
| 11 | `sha` | `DeskIT-Setup-x.y.z.exe.sha256` (one line: hash, two spaces, file name — the `certutil`/`Get-FileHash` comparable form the guide prints, chapter 14 §14.5) and `latest.json` with chapter 11's fields | — |
| 12 | `smoke` | on the runner: run the installer `/VERYSILENT /SUPPRESSMSGBOXES /LOG`, then `python\python.exe app\deskit.pyw --verify` and `--diagnose` in the installed tree, then the uninstaller `/VERYSILENT`; asserts exit codes and that `MANIFEST.sha256` verifies | any non-zero exit |
| 13 | `virustotal` | upload the installer with the VirusTotal API (`VT_API_KEY` repository secret, free tier) and store the permalink; the job fails the release on any detection count above the threshold the owner sets in the workflow (`VT_MAX_DETECTIONS`, default 2) so a bad build never reaches users (D19 revisit clause) | detections above threshold; the key is missing (then the step is skipped with a warning, never silently) |
| 14 | `release` | `softprops/action-gh-release` (or `gh release create`) with the installer, `.sha256`, `latest.json`, `MANIFEST.sha256`, `THIRD-PARTY-NOTICES.txt`; the release body is the notes template (chapter 11) with the SHA-256, the VirusTotal permalink, the attestation link and the previous installer's link for rollback (D21); `-beta.N` tags publish as pre-releases | the tag already has a release |
| 15 | `winget` | `wingetcreate update <PackageIdentifier> --urls <installer URL> --version x.y.z --submit` with `WINGET_TOKEN` (a fine-grained PAT that can fork and open a PR on `microsoft/winget-pkgs`); skipped for pre-releases (chapter 11 §11.x: no beta in winget v1) | the PR bot's validation fails (10.6) |
| 16 | `store` | phase 3, separate workflow `store.yml` on the same tag: builds the MSIX of 10.7 and uploads it to Partner Center with the Store submission API (`STORE_TENANT_ID`, `STORE_CLIENT_ID`, `STORE_CLIENT_SECRET`) | certification fails (10.7) |

Sizes and time: the wheelhouse download is the slow step (10.5); the whole run should stay under 25
minutes on the free runner. Caching `wheels\` by the lock file's hash (`actions/cache`) is allowed
because `--require-hashes` re-verifies every wheel at install time, so a poisoned cache cannot pass step 5.

What never happens in the workflow: no `pip install` without `--require-hashes`, no compile step, no
download of a model, a CUDA wheel or FFmpeg (D13, D24), no secret other than the four named above, no
step that runs on the owner's machine. The owner's only hand-work per release is the tag and the notes
(chapter 11's release checklist); the owner's one-time hand-work is listed in 10.11 and chapter 16.

Local rehearsal: `packaging\build_local.ps1` runs steps 1-12 on the owner's PC into `dist\` for a
throwaway build (the phase-0 VirusTotal probe D19 asks for), marks it with `CHANNEL` = `github` and
never publishes; its output is not a release and carries no attestation.

## 10.4 Installer behaviour (D20, Inno Setup 6)

`packaging\DeskIT.iss` is one script, parameterised by `/DVersion` and `/DStage`. Its settings and the
behaviour they buy, in the order a user meets them:

| Setting or section | Value | Why |
|---|---|---|
| `AppId` | one GUID, fixed forever, committed in the script | Inno's upgrade-in-place key: a new version with the same `AppId` replaces the old files in the same folder and keeps the one Apps-list entry (D21) |
| `AppName` / `AppVersion` / `VersionInfoVersion` | `DeskIT` / `x.y.z` / the 4-part Windows form of chapter 11 | Apps list, `latest.json`, winget's version match |
| `AppPublisher`, `AppPublisherURL`, `AppSupportURL` | "Yoav Shimron", the repo URL, the guide URL | shown in Apps & features and the SmartScreen "Publisher: Unknown" line stays until 10.8 |
| `PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed` unset | per-user, no UAC prompt ever | D20; an admin install would put the tree under Program Files where the pack installer of chapter 6 could not write |
| `DefaultDirName={localappdata}\Programs\DeskIT`, `DisableDirPage=yes` | the layout of chapter 3 (D1) | paths inside the app assume it; `UsePreviousAppDir=yes` keeps an existing install where it is |
| `ArchitecturesAllowed=x64compatible`, `ArchitecturesInstallIn64BitMode=x64compatible` | 64-bit only | the wheelhouse is win_amd64; Arm64 Windows runs it through emulation and is out of scope (10.10) |
| `MinVersion=10.0.17763` | Windows 10 1809+ | the oldest build the python.org 3.11 binaries and `SetProcessDpiAwarenessContext` paths in the app support (open point 3) |
| `CloseApplications=yes`, `RestartApplications=yes`, `CloseApplicationsFilter=*.exe,*.dll,*.pyd` | the running `pythonw.exe` is asked to close through Restart Manager and relaunched after | D21; the app must answer `WM_QUERYENDSESSION`/`RM` cleanly (chapter 11 open point 3) |
| `SetupLogging=yes` | the log the `--diagnose` block tails (chapter 14 §14.7) | field diagnosis |
| `Compression=lzma2/ultra64`, `SolidCompression=yes` | smallest installer for a tree of many small files | 10.5 |
| `[Languages]` | `english` (Default.isl) and `hebrew` (`Languages\Hebrew.isl`, shipped with Inno) with `ShowLanguageDialog=auto` | D18 installer Hebrew-first: `auto` picks the language from the user's Windows UI language and shows the dialog only when neither matches; Inno renders RTL pages natively (`research/packaging` S19) |
| `[Files]` | `Source: "{#Stage}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion` | ignoreversion because `.py` files carry no version resource and must always be replaced |
| `[Icons]` | one Start-menu entry "DeskIT" as 10.2 describes, `AppUserModelID: "DeskIT.App"`; no desktop icon, no Startup-folder entry | the app owns autostart (10.2) |
| `[Run]` | `postinstall` launch of the shortcut target, ticked by default, `nowait skipifsilent` when the caller passes `/NOLAUNCH` | first-run wizard starts straight after install; the update path of chapter 11 relies on Restart Manager instead |
| `[Registry]` | nothing except what Inno writes for the uninstaller | the `Run` value is the app's (10.2) |
| `[Code]` `CHANNEL` | the script writes `{app}\CHANNEL` from the `/CHANNEL=` parameter, default `github` | answers chapter 11 open point 1 for the two Inno channels; the winget manifest passes `/CHANNEL=winget` in its `InstallerSwitches.Silent` (10.6) |
| `[UninstallDelete]` | none — `APP_DIR` is removed whole by Inno because every file under it came from `[Files]` except `CHANNEL` and the pack-installed wheels, which are listed as `Type: filesandordirs; Name: "{app}"` | packs live inside `python\Lib\site-packages` (chapter 6) and must go with the app |

Upgrade in place: a newer installer over an existing `AppId` reuses the folder, closes the app, replaces
`python\` and `app\` file by file (files that no longer exist in the new tree are not removed by Inno —
so the script's `[InstallDelete]` lists `{app}\app\*` and `{app}\python\Lib\site-packages\*.dist-info`
minus the pack packages, and `MANIFEST.sha256` is regenerated by the first `--verify` run of the new
version), never touches `DATA_DIR` (chapter 3), and never asks about language again. Downgrades are
refused with a message naming the installed version and the previous-installer link (D21 rollback is
"uninstall, then run the previous installer", chapter 11).

Uninstaller: Windows Settings > Apps > DeskIT > Uninstall runs `unins000.exe` per-user, no UAC. It
asks one question in the user's language: "Also delete your settings, history and downloaded models
(about N GB)?" with "Keep" as the default; "Delete" runs the same routine as Settings > Your data >
"Delete everything on this PC" (chapter 4 §4.8), which removes `DATA_DIR`, the model cache, the
`HKCU\...\Run` value, the Credential Manager entries `DeskIT/groq` and `DeskIT/gemini` and the DPAPI
files. "Keep" removes only `APP_DIR` and the `Run` value (a stale autostart pointing at nothing is a
bug users report). The uninstaller never opens a browser "why did you leave" page (a pattern the
competitors' issue trackers get complaints about; and it would be an unconsented request, D12).

Silent switches the plan relies on: `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` (winget, 10.6),
`/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS` (the Update card, D21), `/LOG="path"`, `/NOLAUNCH`
and `/CHANNEL=` (this chapter's two additions), `/LANG=hebrew|english`.

## 10.5 Sizes

Measured today in the owner's venv (`map/packaging` pip table, total 2,398 MB) and what the base
wheelhouse keeps of it (D19, D24):

| Component | Today | In the base installer | Note |
|---|---|---|---|
| `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-nvrtc-cu12` | 1,986 MB | 0 | GPU pack, pip-downloaded on demand with the NVIDIA EULA link (D24, chapter 6) |
| `faster-whisper` + `ctranslate2` | 62 MB | 62 MB | required |
| `onnxruntime` | 45 MB | 45 MB | Silero VAD; required |
| `av` + `av.libs` (FFmpeg incl. libx264) | 68 MB | 0 or 68 MB | 0 if faster-whisper is vendored with a lazy `av` import and `av` goes to the Recording pack; 68 MB if the LGPL cp311 wheel exists and ships in the base (D24 phase-0 check) |
| `numpy` (+libs) | 58 MB | 58 MB | required |
| `pillow` | 16 MB | 16 MB | required, missing from `requirements.txt` today (`map/packaging` risk 14) |
| `pywin32` | ~20 MB | ~20 MB | required |
| `huggingface_hub` + `hf_xet` + `tokenizers` + `tqdm` + `filelock` + `fsspec` + `requests` + `pyyaml` | ~35 MB | ~35 MB | model download; `requests` stays only as faster-whisper's dependency and may not be imported outside `net.py` (D12 lock 2) |
| `pycaw` + `comtypes` + `psutil` | 4 MB | 4 MB | system-sound capture and taskbar properties |
| `sounddevice` (PortAudio) | small | small | required |
| `google-genai` + `pydantic` + `cryptography` + `httpx` etc. | ~52 MB | 0 | replaced by REST through `net.py` (D12) |
| `skia-python` + `icudtl.dat` | 25 MB | 0 | Skin pack (D19) |
| `keyboard` | small | 0 | dropped; local module renamed `keycaps.py` (D19) |
| `pip` (as a plain package) | ~12 MB | ~12 MB | needed by the pack installer (10.2) |
| Embeddable Python 3.11 + tcl/tk tree | — | ~45 MB | not in the venv table; the zip is ~11 MB compressed, the Tk copy ~25 MB unpacked — a phase-0 measurement replaces these estimates |
| `app\` from `git archive` | — | <10 MB | source, fonts, pre-rendered cues, icon |

Arithmetic: 2,398 − 1,986 (NVIDIA) − 52 (genai) − 25 (skia) ≈ 335 MB of wheels unpacked, ≈ 270 MB
if `av` leaves too, plus ~55 MB of Python, Tk and app: **≈ 325-390 MB on disk**, inside D19's 350-410 MB
envelope. With `lzma2/ultra64` solid compression the installer should land near **120-160 MB** (numpy,
onnxruntime and ctranslate2 DLLs compress to roughly a third; the estimate is the owner's phase-0
measurement to confirm). Both numbers are far under GitHub's 2 GiB per-file cap (`research/packaging`
S28), so nothing is split. After first run the user additionally holds the 1.6 GB model in the cache
(D13) and, if chosen, the ~2 GB GPU pack — the wizard states both sizes before downloading (D18).

The numbers the guide, the Store listing and `latest.json` print (`size` field, chapter 11) come from the
build, never from this table: step 11 writes the real byte count.

## 10.6 The winget manifest (D20)

**PackageIdentifier: `YoavShimron.DeskIT`** — this settles chapter 11 open point 2. Reasons: winget ids
are `<Publisher>.<Package>` where the publisher segment is the publisher's name as it appears in
`AppPublisher` (10.4) and in the Apps list, so the full name matches what the moderator sees in the
installer; and chapter 16's `test_no_owner_strings_in_archive` forbids the string `Yoav.DeskIT` anywhere
in the shipped tree while the Update card's copy command (`winget upgrade YoavShimron.DeskIT`, chapter
11 §11.5) must live in the app source. `arch-B §9`'s `Yoav.DeskIT` is superseded. The id is fixed
forever; a rename in winget-pkgs is a moderated move.

The manifest is the three-file singleton `wingetcreate` writes (`manifests\y\YoavShimron\DeskIT\x.y.z\`):
version, `defaultLocale` and installer manifests. Values that matter:

| Field | Value | Source |
|---|---|---|
| `InstallerType` | `inno` | winget knows Inno's switches (`research/signing` source 4: Inno is an accepted type; `research/packaging` S27) |
| `InstallerUrl` | the GitHub Release asset URL of `DeskIT-Setup-x.y.z.exe` (direct HTTPS, no redirector) | source 4: "comes directly from the publisher's website"; GitHub Releases URLs are accepted in practice |
| `InstallerSha256` | from step 11 | pinned per version |
| `Scope` | `user` | `PrivilegesRequired=lowest` |
| `InstallerSwitches.Silent` / `SilentWithProgress` | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOLAUNCH /CHANNEL=winget` and `/SILENT ...` with the same tail | so a winget install never launches the wizard under the winget console and marks the install as the winget channel (chapter 11 open point 1) |
| `UpgradeBehavior` | `install` | same `AppId`, upgrade in place (10.4) |
| `ProductCode` | Inno's `{AppId}_is1` | lets winget match the Apps-list entry for `winget list` and `winget upgrade` |
| `AppsAndFeaturesEntries.DisplayVersion` | `x.y.z` | winget compares this with the Apps list |
| `PackageLocale` `en-US` + a second locale file `he-IL` | name, publisher, short description (the three positioning phrases of chapter 14 §14.8), license `Apache-2.0`, `LicenseUrl`, `PrivacyUrl` (chapter 13), `ReleaseNotesUrl` | the Hebrew locale is the one hand-maintained file; `wingetcreate update` carries it forward |
| `Tags` | `dictation`, `hebrew`, `speech-to-text`, `whisper`, `push-to-talk` | search |

Flow per release (step 15): `wingetcreate update` with the new URL and version opens a PR against
`microsoft/winget-pkgs` from the owner's fork; the pipeline runs the installer in a VM, uninstalls it,
scans it with several AV engines ("Installers Scan test", `research/signing` source 4) and a moderator
merges, usually within a day or two. No signature is required (source 4: no sentence on the page requires
one; many unsigned OSS packages exist). A PUA/AV hit blocks the PR — the same threshold step 13 checks
first. First submission is by hand (`wingetcreate new`, chapter 16) so the owner reads every field once.

What winget buys: `winget install YoavShimron.DeskIT` downloads through winget, which shows no
SmartScreen download dialog (`research/packaging` S27); the installer still carries no signature, so
Smart App Control machines are still blocked (10.9). Pre-releases are never submitted (chapter 11).

## 10.7 The Store MSIX (D20 phase 3)

Same tree, different wrapper. The `store.yml` workflow reuses steps 1-7 of 10.3 and then:

**Launcher stub.** An MSIX manifest needs an `Executable`, and it cannot be `pythonw.exe` with arguments
(the manifest has no arguments field). So the Store build alone adds `DeskIT.exe`: a ~30-line C program
in `packaging\stub\` (D19), open source in the repo, whose whole job is to resolve its own directory,
build the command line `python\pythonw.exe app\deskit.pyw` with the package root as working directory,
set the process to DPI-aware per monitor v2 (so the Tk windows are not blurred, matching what the app
does for itself today), and `CreateProcess` it, exiting with the child's code. No console, no
arguments parsed, no network. It is compiled on the runner with the MSVC toolchain `windows-latest`
carries, and its hash is listed in `MANIFEST.sha256` like every other file. Because the Store signs the
package with Microsoft's certificate, the stub's unknown hash costs nothing there (`research/signing`
source 7); that same stub never enters the GitHub build (10.1).

**Manifest (`AppxManifest.xml`) essentials.** `Identity Name` and `Publisher` are the values Partner
Center assigns when the app name "DeskIT" is reserved (the Publisher is a CN string, not the owner's
name; the build reads both from repository variables). `TargetDeviceFamily Windows.Desktop`, min
version `10.0.17763.0`. `EntryPoint="Windows.FullTrustApplication"`, `Executable="DeskIT.exe"`.
Capabilities: `runFullTrust` (restricted; needed for the global keyboard hook, `SendInput`, the
loopback server and `CredWrite`), `internetClient` (model download, consented cloud calls),
`privateNetworkClientServer` (the phone's Wi-Fi/Tailscale connection to the PC, chapter 12),
`microphone` (the OS microphone privacy prompt applies to packaged apps; the wizard's mic step
explains it, D18). `AppUserModelID` is set through the manifest's application id rather than the
shortcut. Extensions: a `windows.protocol` for `ms-screenclip` is **not** declared — D18 (13) makes
DeskIT a *caller* of the Snipping Tool, not a handler. `desktop4:FileExplorerContextMenus` and startup
tasks: a `windows.startupTask` extension (`TaskId` `DeskITAutostart`, disabled by default) replaces the
`HKCU\...\Run` value of 10.2, because a packaged app's registry writes are virtualised
(`research/signing` "Python apps on the Microsoft Store"); the Settings > The app switch calls the
`StartupTask` API when `CHANNEL` = `store` and writes the `Run` value otherwise.

**Store-specific runtime differences the app must know** (`CHANNEL` = `store`, written into the package
root by the workflow): `APP_DIR` is read-only under `C:\Program Files\WindowsApps\...`, so the pack
installer of chapter 6 targets a second site-packages under `DATA_DIR\packs\` that `deskit.pyw` appends
to `sys.path` at start (chapter 6 must allow this second location; open point 4); `%LOCALAPPDATA%` and
`%APPDATA%` are redirected into the package's virtual folders unless the paths are accessed through the
package-aware APIs — DeskIT keeps its data under the same `DATA_DIR` names but must test that the model
cache and the Credential Manager entries survive an update (10.10 row 9); the update check is disabled
and About says "Updates come from the Microsoft Store" (chapter 11).

**runFullTrust justification text** (entered once in Partner Center, kept in `packaging\store\
justification.md`): "DeskIT is a push-to-talk dictation tool. It needs full trust for three things a
sandboxed app cannot do: (1) a global low-level keyboard hook so the user's chosen key starts and stops
recording in any application, and simulated key input to paste the text where the cursor is; (2) reading
the pixels of the screen for the optional ask-the-screen feature, only when the user presses the key
for it; (3) a local HTTPS listener on the PC so the optional Android companion can send audio over the
user's own Wi-Fi or Tailscale network. Audio is transcribed on the device by default; nothing leaves the
PC without a consent switch that names the recipient. Privacy policy: <URL>. Source code: <repo URL>."

**Listing assets** (`packaging\store\listing\`): 300×300 logo, 1080×1080 and 2400×1200 hero images,
four to six screenshots of chapter 14's screenshot set (the wizard, the dot on top of a chat window, the
Network window, the Keys page with the storage sentence), the three positioning phrases as the short
description, the privacy-policy URL (mandatory for full-trust, `research/signing` source 9), category
"Productivity", age rating through the IARC questionnaire (no user content shared, no ads), and the
"Made available to: all markets" default with the Hebrew and English listing locales.

**Certification loop.** Account: individual, fee waived, government ID and selfie at
`storedeveloper.microsoft.com` (`research/signing` source 3; Israel in "nearly 200 markets" is to be
confirmed in the dropdown — chapter 16). Each submission: upload the `.msixupload` from the workflow,
answer the same questionnaire, submit; certification takes 1-3 business days per update (`research/
signing`, Python-on-Store notes) and runs the Windows App Certification Kit plus a manual full-trust
review. Failures come back as a report; the ones this plan anticipates and their fixes: "app crashes
on launch" (the stub's working directory or a missing `vcruntime140.dll` in `python\`), "declares a
capability it does not use" (drop `privateNetworkClientServer` only if the phone feature is cut),
"privacy policy missing or does not describe collected data" (chapter 13's policy must name the
consented cloud calls and the problem reports). Before every Store submission the workflow runs the
MSIX through `MakeAppx pack` + a local install with a self-signed test certificate on the runner and
the same smoke test as step 12, so certification never sees a package that does not start.

If the Store rejects the global hook outright (D20 revisit clause), phase 3 ends, GitHub + winget stays
primary and the SignPath application of 10.8 moves up to phase 3.

## 10.8 Signing: the situation and the path (D20)

The GitHub installer ships unsigned in phases 2-4. Why no free route exists for the owner, so nobody
re-researches it:

| Route | Status for an Israeli individual | Source |
|---|---|---|
| Azure Artifact Signing (public trust) | closed: "Individual developers must be located in the United States or Canada"; Israel is on the *organisation* list only (needs a registered entity, business id, domain e-mail) and costs from USD 9.99/month | `research/signing` source 6, source 7 |
| OV / EV certificate | USD 150-500 per year; "EV certificates no longer bypass SmartScreen" — reputation still starts at zero per publisher identity, though it then carries across versions | `research/signing` source 7; D20 |
| Self-signed | "Same behavior as no signature" | `research/signing` source 7 |
| Microsoft Store | free, no warning at all, survives Smart App Control — but only for the Store build | `research/signing` source 3, 7; 10.7 |
| SignPath Foundation | free OV signing for OSS built on a connected CI; conditions below | `research/signing` source 2 |
| Certum "Open Source Code Signing in the Cloud" | EUR 49 gross, individuals only, subject "Open Source Developer, Yoav Shimron", max 459 days validity from 2026-02-27; the cheapest real Authenticode certificate available to the owner | `research/signing` source 8 |

What unsigned costs the user: the "Windows protected your PC" dialog on every new version (reputation
"cannot transfer from previous versions unless both were signed", `research/signing` source 7), no
route to request a reputation review ("no need (or mechanism) to manually submit a file", same source),
a hard block on Smart App Control machines, and possible enterprise policies that forbid "Run anyway".
What we do about it until signed: stable file names (`DeskIT-Setup-x.y.z.exe`, no build hashes in the
name), the guide's screenshot sequence (chapter 14 §14.2 chapter 1), the FAQ of 10.9, the VirusTotal
link and the attestation on every release, winget as the download path that shows no dialog, and the
Store as the door for everyone else (D20).

**Phase 5: SignPath Foundation.** Preconditions DeskIT meets by then: Apache-2.0 with no proprietary
component (D23; the trademark notice is not a licence term), public repo, CI-built artefacts (10.3 is
already a "verifiable" build), an uninstaller (10.4), no system change without warning (the autostart
switch is the user's), problem reports opt-in with disclosure (D16, chapter 13). What the application
adds: MFA on the GitHub account and the SignPath account; a `CODE_SIGNING_POLICY.md` page on the
project's home (repo README section and the guide) stating that releases are signed by SignPath
Foundation, that only artefacts built by `release.yml` from the tagged source are signed, naming the
Authors/Reviewers/Approvers (all the owner), and linking the privacy policy (`research/signing` source
2 lists every obligation). Mechanics: a `signpath/github-action-submit-signing-request` step after 10.3
step 10 submits the installer, the owner approves each release by hand in SignPath's UI (mandatory per
source 2), and the signed installer replaces the unsigned one before step 11 hashes it. The certificate
subject reads "SignPath Foundation", not the owner's name — the guide's SmartScreen paragraph changes
to "Publisher: SignPath Foundation" when this lands. SignPath's approval of the project is a human
decision on their side; the roadmap (chapter 15) counts it as a bet, not a milestone.

**Fallback: Certum OSS at EUR 49.** Cloud-based (SimplySign), no card reader, identity checked once;
signing runs on the owner's PC or through SimplySign's CLI in the workflow with a stored credential —
which is the one exception to "nothing runs on the owner's PC" and is why SignPath is preferred. Bought
only if SignPath declines and user numbers justify it (D20: "paid certificates before user numbers
justify them" are ruled out).

Either way the signature covers `DeskIT-Setup-x.y.z.exe` and, later, `unins000.exe`; the `.py` tree
and the wheels stay unsigned, which is fine: Windows checks the signature of what it executes
(`python.exe`, signed by the PSF; the installer) and `deskit --verify` covers the rest.

## 10.9 SmartScreen and Defender: the FAQ content

Chapter 14 §14.5 prints the two answers; this section fixes the facts behind them so the guide, the
release-notes template, the README and `false-positive.yml` say the same thing. Agreed with §14.5 on
both points it asked about: the false-positive link is Microsoft's Security Intelligence file-submission
portal (`microsoft.com/wdsi/filesubmission`, "Software developer" path, the release page and the issue
template link it; the URL is confirmed once in phase 2 and stored as a repository variable so one edit
fixes every page), and the SHA-256 method is the one-liner `certutil -hashfile DeskIT-Setup-x.y.z.exe
SHA256` (present on Windows 10 and 11, no PowerShell knowledge needed; `Get-FileHash` is the alternative
the guide shows for PowerShell users). Stock Explorer's Properties dialog shows no hash tab; §14.5's
"Explorer: Properties" phrase should be dropped (open point 5).

The facts, each with its source, in the order a worried user asks:

| The user's question | The answer's substance | Source |
|---|---|---|
| Why does Windows say "protected your PC"? | The installer is not signed with a certificate. Windows shows this for every unsigned program it has not seen many times; reputation starts at zero per version and cannot carry over without a signature. It says nothing about what the program does. | `research/signing` source 7 |
| Why not just sign it? | The free signing service is closed to individuals outside the US/Canada; certificates cost USD 150-500 a year; a signed program still shows a warning until it earns reputation. The Store build has no warning at all. | 10.8 |
| How do I check it is the real file? | Compare the SHA-256 on the release page with `certutil -hashfile`; open the VirusTotal link on the release; open the build attestation, which proves GitHub built this exact file from the tagged source. | 10.3 steps 8, 11, 13 |
| Defender quarantined or deleted the installer | Restore it from Windows Security > Protection history, check the SHA-256, then report the false positive to Microsoft on the submission portal and to us with `false-positive.yml` (detection name, file name, VirusTotal link). Comparable signed apps get re-flagged on new releases too (Handy #1399, #1891, `research/competitors`). | chapter 14 §14.7 |
| Smart App Control blocks it | Smart App Control runs only signed or Store apps and has no per-app allow; install from the Store (phase 3) or turn SAC off, which Windows allows once and cannot be undone without a reset. | `research/signing` source 7 |
| My company's PC will not let me press "Run anyway" | Enterprise policy can remove the button; ask IT to allow the hash from the release page or use the Store build. | `research/signing` source 7 |
| Does winget help? | `winget install YoavShimron.DeskIT` fetches it without the download dialog; the program is the same unsigned file, so SAC still blocks it. | 10.6 |
| Will the warning go away? | For a given version, after "several weeks and hundreds of clean installs"; each new version starts over until the installer is signed (phase 5). | `research/signing` source 7 |

Tone rules for every copy of this text: no "our software is safe, trust us"; every sentence points at
something the user can check (D12 wording rule). The Hebrew version is the guide's, not a machine
translation (D18, chapter 14).

## 10.10 Clean-VM test matrix

Every release candidate (and every phase-0/1 throwaway build) is installed on machines that are not
the owner's, because chapter 2 lists what breaks on a fresh machine (`map/packaging` "What breaks on a
fresh machine") and none of it reproduces on a PC that already has the venv, the driver and the model.
The VMs are Hyper-V or VirtualBox images kept under `dev\vm\` as checklists, not images in the repo;
each run fills one row of `dev\vm\RESULTS.md` with the build, the date and pass/fail per check. Never on
the owner's own desktop session (memory rule: run GUI checks where they cannot take over his screen).

| # | Machine | Why it exists | Checks |
|---|---|---|---|
| 1 | Windows 11 24H2 Home, Defender on, no NVIDIA driver, 100 % DPI, single monitor, English UI | the baseline stranger | SmartScreen dialog appears with the exact wording the guide shows; install without UAC; wizard runs; model download; one Hebrew sentence pasted into Notepad on CPU; `--verify` passes; uninstall leaves nothing in Apps list and `Run` |
| 2 | same as 1 with Hebrew Windows UI and Hebrew keyboard as default | the target user | installer opens in Hebrew without the language dialog; RTL pages readable; wizard's Hebrew body text renders through the bitmap path; hotkey works with the Hebrew layout (keycode, not keysym) |
| 3 | Windows 11 with an NVIDIA card (GPU pass-through or a physical second PC), driver present | the GPU pack | wizard offers the pack; pip download with the EULA link; CUDA DLLs found at the deterministic path; a decode on the GPU; driver-too-old fallback message when the driver is forced old |
| 4 | Windows 11 at 150 % DPI, two monitors of different scale | Tk scaling bugs | the dot, cards and dashboard are sharp and positioned on the right monitor; the wizard fits the screen |
| 5 | Windows 11 with Smart App Control on (fresh OEM-style image) | the hard block | the GitHub installer is blocked with the SAC message the FAQ quotes; the Store build installs (phase 3) |
| 6 | Windows 10 22H2, Defender on | the floor `MinVersion` promises (open point 3) | install, wizard, one sentence; Snipping Tool route absent gracefully |
| 7 | Machine 1 with the previous release installed and used (keys saved, model present, autostart on) | upgrade in place | the Update card path (`/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`): app closes, files replace, app relaunches, keys and model and settings intact, `CHANNEL` unchanged, `MANIFEST.sha256` verifies |
| 8 | Machine 1, install via `winget install` | the winget path | no download dialog; `CHANNEL` = `winget`; Apps list shows the version; `winget upgrade` finds the next release; the Update card shows the copy command |
| 9 | Machine 1, install from the Store (phase 3) | the MSIX | launches from the stub; microphone prompt; hook works; `DATA_DIR` at the expected path; `StartupTask` toggle; an update through the Store keeps keys, model and settings; packs land under `DATA_DIR\packs\` |
| 10 | Machine 1 with a restricted network (huggingface.co blocked by hosts file) | download failures | the Network window shows the refused host; the wizard's download step reports it and resumes when unblocked (D13) |
| 11 | Machine 1 as a standard (non-admin) user account | no-admin promise | the whole of row 1 without ever seeing UAC |
| 12 | Windows on Arm64 (only if a VM is available) | to document, not to support | record whether the x64 installer runs under emulation; the guide says "not supported" until it does |

Rows 1, 2, 7 and 11 are mandatory for every release; 3, 4, 8 for every minor; 5, 6, 9, 10, 12 once per
phase. Anything a row finds is a chapter 16 hand-work item or a bug, never a guide caveat by default.

## 10.11 Files to add or change

| File | Add / change | What it holds |
|---|---|---|
| `.github/workflows/release.yml` | add | the 15 steps of 10.3, `workflow_dispatch` with `dry-run` |
| `.github/workflows/store.yml` | add (phase 3) | steps 1-7 + stub compile + `MakeAppx` + Store submission API upload |
| `requirements.txt` | change | the base set of D19 (add `pillow`, `comtypes`; drop `keyboard`, `google-genai`, `av` if the pack route wins, `nvidia-*`, `skia-python`) |
| `requirements.lock` | add | `pip-compile --generate-hashes` output; the only file steps 1 and 5 read |
| `packaging\python311._pth` | add | the four lines of 10.2 |
| `packaging\python-embed.sha256` | add | SHA-256 of the python.org zip for the pinned patch version |
| `packaging\DeskIT.iss` | add | the script of 10.4, with `/CHANNEL` and `/NOLAUNCH` handling in `[Code]` |
| `packaging\build_local.ps1` | add | the local rehearsal of steps 1-12 into `dist\` |
| `packaging\stub\DeskIT.c`, `packaging\stub\build.cmd` | add (phase 3) | the launcher stub of 10.7 |
| `packaging\store\AppxManifest.xml`, `packaging\store\justification.md`, `packaging\store\listing\` | add (phase 3) | manifest, the runFullTrust text, the listing assets |
| `packaging\CODE_SIGNING_POLICY.md` | add (phase 5) | the SignPath policy page; linked from README and the guide |
| `.gitattributes` | add | `export-ignore` for `dev\`, `tests\`, `docs\`, `.github\`, `packaging\`, `android\` and the forbidden files of chapter 3 §3.10 |
| `deskit.pyw` | add | the shortcut target (chapter 3); appends `DATA_DIR\packs\` to `sys.path` when `CHANNEL` = `store` |
| `DeskIT.vbs`, `Dashboard.vbs`, `Stop DeskIT.vbs` | remove | replaced by the shortcut, the dashboard's relaunch command and `--stop` (10.2) |
| `keyboard.py` → `keycaps.py` | rename | D19; every importer updated (`dashboard.py:75` and the others `map/packaging` lists) |
| `dashboard.py:596-613` | change | relaunch command targets `python\pythonw.exe app\deskit.pyw` |
| Settings > The app (chapter 9) | change | the "Start with Windows" switch: `Run` value or `StartupTask` by `CHANNEL` |
| `dev\vm\CHECKLIST.md`, `dev\vm\RESULTS.md` | add | the matrix of 10.10 and its log |
| `.github/ISSUE_TEMPLATE/false-positive.yml` | add | chapter 14 §14.7 owns the fields; this chapter owns the link it embeds |
| `dev\test_packaging.py` | add | the tests below |

## Acceptance

1. A push of tag `vX.Y.Z` to the repository produces, without any step on the owner's PC, a GitHub
   Release holding `DeskIT-Setup-X.Y.Z.exe`, its `.sha256`, `latest.json`, `MANIFEST.sha256`,
   `THIRD-PARTY-NOTICES.txt`, a build attestation and a VirusTotal permalink, and opens a winget PR.
2. On VM row 1 the installer runs per-user with no UAC prompt, creates one Start-menu shortcut targeting
   `python\pythonw.exe app\deskit.pyw` with AppUserModelID `DeskIT.App`, writes `CHANNEL` = `github`,
   and the installed tree passes `deskit --verify` against the release's `MANIFEST.sha256`.
3. On VM row 2 the installer and its uninstaller are in Hebrew without a language dialog.
4. Running the next version's installer over an install (row 7) keeps keys, model, settings and
   autostart, and the app relaunches; running an older installer is refused with the rollback message.
5. The uninstaller's "Keep" leaves `DATA_DIR` intact and removes `APP_DIR` and the `Run` value;
   "Delete" also removes `DATA_DIR`, the cache, both Credential Manager entries and the DPAPI files.
6. `winget install YoavShimron.DeskIT` installs silently, marks `CHANNEL` = `winget`, and
   `winget upgrade` moves to the next version.
7. No release asset is larger than 2 GiB, and the base install is under 400 MB on disk (10.5), without
   any model, CUDA or FFmpeg byte.
8. Every step of 10.3 fails loudly on a hash mismatch (wheel, python.org zip) or a VirusTotal count
   above the threshold; nothing is published in that case.
9. Phase 3: the MSIX passes Store certification, launches through the stub, and `CHANNEL` = `store`
   hides the download button and drives the `StartupTask` switch.

## Tests to add

| Test | Asserts |
|---|---|
| `dev/test_packaging.py::test_lock_has_hashes` | every requirement line in `requirements.lock` carries at least one `--hash=sha256:`; no line lacks a pin |
| `dev/test_packaging.py::test_requirements_base_set` | `requirements.txt` names `pillow` and `comtypes`; names none of `keyboard`, `google-genai`, `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-nvrtc-cu12`, `skia-python` |
| `dev/test_packaging.py::test_pth_lines` | `packaging\python311._pth` is exactly `python311.zip`, `.`, `Lib\site-packages`, `import site` |
| `dev/test_packaging.py::test_embed_sha_pinned` | `packaging\python-embed.sha256` holds a 64-hex value and names the same patch version as `release.yml` |
| `dev/test_packaging.py::test_iss_settings` | `DeskIT.iss` contains `PrivilegesRequired=lowest`, `CloseApplications=yes`, `RestartApplications=yes`, `MinVersion=10.0.17763`, both `[Languages]` entries, one `[Icons]` entry with `AppUserModelID: "DeskIT.App"`, no `[Registry]` `Run` value, and a `[Code]` reference to `/CHANNEL` |
| `dev/test_packaging.py::test_iss_version_matches_VERSION` | the `AppVersion` the workflow passes equals the `VERSION` file and the tag (run in the workflow with the tag name as input) |
| `dev/test_packaging.py::test_export_ignore_covers_forbidden` | for each path in chapter 3 §3.10's forbidden list, `git check-attr export-ignore` reports `set` |
| `dev/test_packaging.py::test_manifest_roundtrip` | over a temporary stage tree, the manifest writer and `deskit --verify`'s reader agree; changing one byte of one file fails `--verify` naming that file |
| `dev/test_packaging.py::test_channel_values` | the app's channel reader accepts exactly `github`, `winget`, `store` and treats a missing or other value as `github` with a logged warning |
| `dev/test_packaging.py::test_no_stub_in_github_build` | the stage tree of the GitHub variant contains no `DeskIT.exe`; the Store stage contains exactly one and its hash is in `MANIFEST.sha256` (phase 3) |
| `dev/test_packaging.py::test_winget_manifest_fields` | the generated installer manifest has `InstallerType: inno`, `Scope: user`, silent switches containing `/VERYSILENT`, `/NOLAUNCH` and `/CHANNEL=winget`, `PackageIdentifier: YoavShimron.DeskIT`, and an `InstallerUrl` under `github.com/<org>/DeskIT/releases/download/` |
| `dev/test_packaging.py::test_faq_link_agreement` | the false-positive URL and the `certutil -hashfile` phrase appear identically in the guide's FAQ source, the release-notes template and `false-positive.yml` (they all read one constants file) |
| workflow step 12 `smoke` | silent install, `--verify` and `--diagnose` exit 0 on the runner, silent uninstall leaves no `APP_DIR` |

## Open points

1. `av` in the base or in the Recording pack (D24's phase-0 check for an LGPL cp311 wheel) moves 68 MB
   between the two columns of 10.5 and decides whether faster-whisper is vendored; 10.5 shows both.
2. The VirusTotal threshold `VT_MAX_DETECTIONS` (default 2 here) is the owner's call after the phase-0
   scan; if the embeddable build itself scores worse than that, D19's revisit clause applies before any
   installer work.
3. `MinVersion=10.0.17763` (Windows 10 1809) is a proposal; the app's DPI and `ms-screenclip` paths and
   the Store's `TargetDeviceFamily` minimum should be checked in phase 1 and the floor raised to 22H2
   if the row-6 VM shows anything the guide would have to caveat.
4. The Store build needs a second site-packages under `DATA_DIR\packs\` because `APP_DIR` is read-only
   under `WindowsApps`; chapter 6's pack installer describes a single target and must gain this second
   location when phase 3 starts.
5. Chapter 14 §14.5 says "Explorer: Properties or the one-liner"; stock Explorer has no hash tab, so the
   FAQ row should keep only the `certutil -hashfile` one-liner (and `Get-FileHash`), as 10.9 fixes.
6. Chapter 11's Update card copy command and `arch-B §9` say `Yoav.DeskIT`; 10.6 fixes the winget id as
   `YoavShimron.DeskIT` and chapter 11 §11.5 should be updated to match.
7. Whether `RestartApplications=yes` relaunches `pythonw.exe app\deskit.pyw` correctly through Restart
   Manager is chapter 11 open point 3; VM row 7 is where it is decided, and 10.4's `[Run] postinstall`
   entry is the fallback.
8. The Store's country dropdown for individual accounts must show Israel (`research/signing` source 3
   says "nearly 200 markets" without a list); chapter 16 lists the check, and 10.7 is void until it passes.


---

# 11. Versions, updates, rollback

This chapter implements D21. It gives the app one version number that every surface reads, a
weekly check that sends nothing about the user, an Update card that downloads a verified installer and
hands the replacement to Inno Setup, and a rollback that is a link rather than a mechanism. Chapter 10
builds the installer and the winget manifest; chapter 5 owns `net.py` and the `[privacy] update_check`
gate; chapter 3 owns `state.json` and the config layers; chapter 12 owns the phone side of
`/api/version`. Here: the file, the feed, the check, the card, the switches, the guarantees, the
release checklist and `config_version`.

## 11.1 Where the app stands

| Today | Where | Why it cannot ship |
|---|---|---|
| The only "version" is the git branch name, obtained by spawning `git rev-parse --abbrev-ref HEAD` under `CREATE_NO_WINDOW` and cached | `versions.py:52-66` (module docstring explains the removed branch switcher) | An installed tree has no `.git`; the answer would be "(unknown)" on every stranger's machine |
| The branch is stamped on every problem report together with the Python version | `problems.py:266-280` (`env()` returns `{"branch", "python", ...}`) | Reports need an app version, OS build, GPU and tier (D15), not a branch |
| The dashboard prints the branch under "The app" and along the foot of Home, on a thread because git blocks | `dashboard.py:7903-7913` | Same: nothing meaningful to print |
| The Android app carries its own `versionCode = 12`, `versionName = "1.1.0"`, bumped by hand | `android/app/build.gradle.kts:18-20` | Two hand-edited numbers drift; the PC cannot tell a phone which IME it needs |
| The PC serves `/health` with `{ok, apk}` and `/app.apk` from disk, naming the file after `versionName` parsed out of the Gradle file | `server.py:75-86, 218-232, 243-246` | `/app.apk` is retired (D22); the phone needs a version contract, not a file |
| No update check, no installer, no notion of "newer" | — | Users would never learn of a fix; the owner would answer the same bug for months |
| `config.toml` is both the shipped file and the user's file; an update would overwrite the user's values | `map/packaging` rec 2, D2 | Updates must be unable to destroy settings |

## 11.2 The `VERSION` file and its consumers (D21)

One file, `VERSION`, at the repo root, one line, SemVer `MAJOR.MINOR.PATCH[-beta.N]`, no `v` prefix.
It is copied unchanged into `APP_DIR\VERSION` by the build (chapter 10) and is the single input for
every number below.

| Consumer | Derives | How |
|---|---|---|
| `version.py` (replaces `versions.py`) | `VERSION` string, `(major, minor, patch, pre)` tuple, `is_beta`, `branch` | reads `APP_DIR\VERSION` once; `branch` is spawned from git only when `.git` exists beside `main.py` (DEVELOPER, D4); otherwise `""` — no subprocess on a user's machine |
| `problems.env()` (`problems.py:274`) | `version`, `os_build`, `gpu`, `tier`, `config_version` | drops `branch` and `python` (D15); `os_build` from `sys.getwindowsversion().build`, `gpu`/`tier` from `state.json` `[hardware]` (chapter 6) |
| Dashboard Home foot and About (`dashboard.py:7913` today) | "DeskIT 1.2.0 · GPU float16" | reads `version.py`; no thread, no git |
| The Update card (11.5) | "You have 1.2.0, 1.3.0 is available" | compares against `latest.json` with SemVer precedence (pre-release < release, `research/updates` semver) |
| Inno Setup script (chapter 10) | `AppVersion=1.2.0`, `VersionInfoVersion=1.2.0.0`, `OutputBaseFilename=DeskIT-Setup-1.2.0` | the build reads `VERSION` and passes it as a define; the Windows file-version resource needs four numeric parts, so `-beta.N` maps to `MAJOR.MINOR.PATCH.N` and a release to `.0` |
| Store MSIX manifest (chapter 10) | `Version="1.2.0.0"` | same four-part mapping; the Store requires the fourth part to be 0 |
| winget manifest (chapter 10) | `PackageVersion: 1.2.0`, installer URL and `InstallerSha256` | `wingetcreate update` in the release workflow |
| Android build (chapter 12) | `versionName = VERSION`, `versionCode = MAJOR*10000 + MINOR*100 + PATCH` | a Gradle task reads `../VERSION`; the three-number scheme is the one the owner already decided (D21, `research/android` source 8); today's `versionCode = 12` becomes 10100 for 1.1.0, so the mapping is monotonic from the first tagged build |
| `/api/version` (11.9) | `pc` | `version.py` |
| `git tag` | `v1.2.0` | the release workflow refuses to run when the tag and `VERSION` disagree |
| `latest.json` `version` | `1.2.0` | written by the release workflow from `VERSION` |

SemVer rules for this project, in the words the owner and the coders will use:

- **PATCH** — fixes, copy changes, dependency bumps that change no setting key and no file format.
- **MINOR** — new features, new settings keys with defaults, new consent kinds, new packs; never a
  change that needs a migration of `settings.toml`/`state.json`.
- **MAJOR** — anything that needs `config_version` to move (11.10), a new `DATA_DIR` layout, a phone
  protocol change that raises `imeMin`, or a removal of a shipped feature.
- **`-beta.N`** — pre-releases on the beta channel (11.8); N restarts at 1 for each new base version.
- The Android `versionCode` formula caps MINOR and PATCH at 99; a release workflow check refuses a tag
  that would overflow.

## 11.3 `latest.json` — the feed (D21)

Each GitHub Release carries one asset named `latest.json` (and pre-releases carry the same file; the
channel decides which release is read, 11.8). It is generated by the release workflow, never by hand.

| Field | Type | Meaning | Source |
|---|---|---|---|
| `version` | string | SemVer of this release | `VERSION` |
| `url` | string | direct HTTPS URL of `DeskIT-Setup-<version>.exe` under `github.com/<org>/DeskIT/releases/download/…` | workflow |
| `sha256` | string | hex digest of that installer | workflow, computed after upload |
| `size` | integer | bytes of the installer, shown on the card | workflow |
| `min_config_version` | integer | the smallest `config_version` this build can migrate from; a user below it is told to install an intermediate version | `version.py` constant |
| `notes_url` | string | the release page | workflow |
| `published` | string | ISO date, shown on the card | workflow |

Hosts: the check hits `api.github.com`, the download `github.com` and `objects.githubusercontent.com`;
all three are already in `ALLOWED_HOSTS` (D12) with `purpose = "update check"` and `purpose = "update
download"`. The model is never a release asset (D13); the feed points only at the installer.

## 11.4 The check (D21)

| Aspect | Behaviour | Evidence |
|---|---|---|
| Gate | `[privacy] update_check` (chapter 5); asked once in wizard step 6 as the third switch "Check for updates weekly"; default off until answered; changeable on Settings > Privacy | D6, D7, D18 |
| Cadence | once per 7 days, measured from `state.json` `[updates] last_check`; the first check runs 10 minutes after the start that follows consent, on a worker thread; a manual "Check now" button on About ignores the cadence | D21 |
| Request | `GET https://api.github.com/repos/<org>/DeskIT/releases/latest` (stable) or `…/releases?per_page=5` filtered to `prerelease == true` (beta); User-Agent is the plain `DeskIT/<version>` GitHub requires for API calls; no query string, no cookie, no installation id; 60 requests/hour/IP unauthenticated is far above one per week | `research/updates` "GitHub Releases as update feed", arch-B §9 |
| Result | the release's asset list is scanned for `latest.json`, which is fetched and parsed; the two rows appear in the Network window (chapter 5) with the byte counts | D12 window |
| Comparison | SemVer precedence; a `latest.json` version equal to or below the running one is silently recorded in `state.json` `[updates] latest_seen` and nothing is shown | — |
| Skip | "Skip this version" writes `[updates] skipped = "1.3.0"` in `settings.toml`; a later version un-skips | D18 screen 11 |
| Failure | any error (offline, 403, malformed JSON, missing asset) is one debug line in `app.log`, nothing in the UI; the next try is a week later or on "Check now" | support-safe logs, D8 |
| Offline mode | the `[privacy] offline` switch refuses the host like every other; the About row says "Updates: off while Offline" | D12 |
| Store and winget users | the installed channel is recorded at install time in `APP_DIR\CHANNEL` (`github`, `winget`, `store`, written by the build variant, chapter 10); for `store` the check is disabled and the About row says "Updates come from the Microsoft Store"; for `winget` the card's button is replaced by the one-liner `winget upgrade <PackageIdentifier>` shown with a Copy button, because winget-installed apps should be upgraded by winget | D21, `research/updates` (winget "does NOT auto-update apps") |

## 11.5 The Update card (D18 screen 11, D21)

Lives as an overlay card in the existing card family and as a row on About; chapter 9 draws it.
Contents: "DeskIT <new> is available (you have <current>)", the `published` date, `size` in MB, the
SHA-256 in a copyable monospace line, three buttons: **[Download and install]**, **[Release notes]**
(opens `notes_url` in the browser), **[Skip this version]**. Nothing downloads before the first button.

On [Download and install]:

1. The installer is fetched through `net.py` (`purpose = "update download"`) into
   `DATA_DIR\tmp\DeskIT-Setup-<version>.exe.part`, with the progress on the card and a [Cancel] that
   deletes the part file. Resume is not attempted; a cancelled or failed download starts over.
2. The SHA-256 of the finished file is computed and compared with `latest.json`. Mismatch: the file is
   deleted, the card says "The download did not match its checksum and was discarded. Try again or
   download from the release page", and the two hashes are written to `app.log`. Nothing is executed.
3. Match: the file is renamed to drop `.part`, the card says "Installing… DeskIT will close and reopen",
   `settings.toml` is copied to `settings.toml.bak` (11.7), and the installer is started detached with
   the switches in 11.6. The app then exits normally through its own quit path (`Local\DeskIT.quit`,
   `map/core` `singleton.py`) so the hook, the pipe and the phone server are released before Inno's
   Restart Manager step needs them.
4. The installer relaunches `pythonw.exe app\deskit.pyw`; the first start after an update compares
   `state.json` `[updates] installed_version` with `version.py`, runs `config_version` migrations
   (11.10), records the new version and shows a one-line toast "Updated to <version>" with a
   [Release notes] link.

The card never appears during a hold-to-dictate, during a download of a model or a pack (chapter 6), or
while a recording is running; it waits for idle.

## 11.6 Inno re-run switches and what they guarantee (D21)

The update is a re-run of the same per-user installer chapter 10 ships (`PrivilegesRequired=lowest`,
`CloseApplications=yes`). The app starts it with exactly:

`/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /NORESTART /LOG="<DATA_DIR>\logs\setup-<version>.log"`

| Switch | Effect | Evidence |
|---|---|---|
| `/SILENT` | progress window only, no wizard pages, no questions; the user already answered on the card | Inno help, `research/updates` |
| `/CLOSEAPPLICATIONS` | Windows Restart Manager closes any process still holding files under `APP_DIR` — normally none, because the app quit itself in 11.5 step 3; if a second instance or the dashboard survived, it is closed instead of failing the install | `research/updates` (CloseApplications: "asking the user if Setup should automatically close the applications and restart them"; silent mode closes without prompting) |
| `/RESTARTAPPLICATIONS` | the closed application is relaunched by Restart Manager after the copy; the app registers with `RegisterApplicationRestart` at start so the relaunch command is the shortcut target and not a stale path | `research/updates` (Restart Manager needs the app to register for a clean relaunch) |
| `/NORESTART` | never reboot Windows; nothing DeskIT installs needs it | Inno help |
| `/LOG` | the setup log lands in the data folder so `--diagnose` (chapter 14) can attach its tail | D8 |

`/VERYSILENT` is reserved for winget (chapter 10), where no progress window is wanted.

Guarantees the update must keep, each with the mechanism that keeps it:

| Guarantee | Mechanism |
|---|---|
| `DATA_DIR` is never touched | the installer's `[Files]` and `[InstallDelete]` sections name only `APP_DIR`; a build-time test greps the Inno script for `localappdata\DeskIT` outside the uninstaller's optional "remove my data" step (chapter 10) |
| `settings.toml` survives byte-for-byte | it lives in `DATA_DIR` (D1, D2); the app additionally keeps `settings.toml.bak` from just before the update |
| Credential Manager entries and DPAPI files survive | never referenced by the installer (D3) |
| Model and packs survive | `DATA_DIR\models`, `DATA_DIR\packs` (chapter 6); an update whose pack lock changed shows the "Update the GPU pack" offer, never a silent re-download |
| No self-modifying binary | the app never writes under `APP_DIR`; it downloads a file, verifies it, starts Inno, and exits — the highest-privilege path is the same installer the user already ran once (D21 "rules out" Velopack/Squirrel) |
| Stale `APP_DIR` files cannot linger | the installer's `[InstallDelete]` removes `app\` before copying, so a renamed module from the previous version cannot shadow a new one; `MANIFEST.sha256` + `deskit --verify` (chapter 5, lock 5) confirm the tree afterwards |
| A killed update leaves a working app | Inno copies to temp names and renames at the end; if the machine dies mid-way the previous `APP_DIR` is intact or Inno's own rollback restores it; the downloaded installer stays in `DATA_DIR\tmp` for a manual retry |
| The hook and the pipe are re-created cleanly | the relaunch is a normal start; the per-session pipe/mutex names (D5) leave no stale kernel objects |

## 11.7 Rollback (D21)

There is no rollback mechanism in the app, on purpose: every version's installer stays on GitHub
Releases, and the previous one is a link.

1. Every release's notes start with a fixed block: "Previous version: DeskIT-Setup-<prev>.exe (link) —
   install it over this one if something broke; your settings and model stay." The release workflow
   inserts the block from the previous tag.
2. Installing an older installer over a newer tree works because `[InstallDelete]` clears `app\` and
   Inno does not compare versions when the user runs the setup by hand (the card only ever offers newer
   versions).
3. `settings.toml.bak` (written in 11.5 step 3) is restored from Settings > Your data > "Restore the
   settings from before the last update" — one button, only visible when the file exists and is newer
   than the last migration.
4. If `config_version` moved between the two versions, the older build reads the newer `state.json` and
   `settings.toml` by ignoring unknown keys (the loader already tolerates unknown keys, chapter 3), and
   the guide's rollback paragraph says which versions can be rolled back freely (same `config_version`)
   and which need the `.bak`.
5. For a broken release the owner's remedy is a new PATCH release, not a deleted one: a deleted release
   breaks the previous-version links of the release after it. A yanked release is marked "known bad — use
   the next one" in its notes and its `latest.json` is left in place so the check finds the fix.

## 11.8 Beta channel (D21)

- `[updates] channel = "stable" | "beta"` in `settings.toml`, default `stable`, a picker on Settings >
  Privacy next to the update switch with the sentence "Beta builds arrive earlier and may break; the
  stable channel gets the same fixes a week or two later."
- Beta builds are GitHub pre-releases (`-beta.N` tags, `prerelease: true`); the release workflow builds
  them with the same jobs and the same `latest.json`. The stable check reads `releases/latest`, which
  GitHub defines as the newest non-pre-release; the beta check reads the release list and takes the
  newest by SemVer, which may be a stable one if it is newer.
- Switching from beta back to stable never downgrades: the card stays silent until a stable version
  above the running beta exists.
- winget has no beta identifier in v1 (`research/updates` names a separate `PackageIdentifier` as the
  way; deferred). The Store has no beta.

## 11.9 Store and winget in parallel (D20, D21)

| Channel | Who updates | What the app does |
|---|---|---|
| GitHub installer | the Update card (11.5) | full behaviour |
| winget | the user, `winget upgrade`, after the owner's manifest PR is merged (moderator review, possibly days) | the check still runs; the card shows the command instead of the button |
| Microsoft Store | the Store, automatically | the check is off; About says so; the phone `/api/version` still reports `pc` |

All three install the same `app\` tree from the same tag (D20), so `config_version` and `imeMin` are
identical across channels for a given version.

`/api/version` (replaces `/health`'s `apk` field at `server.py:243-246`) returns `{pc, imeMin,
imeLatest, apkUrl, playUrl}`: `pc` from `version.py`; `imeMin` the lowest IME version this PC still
speaks to; `imeLatest` and `apkUrl` from the same `latest.json` cache when the check is on (the APK is
a release asset, D22) or the values baked into `app\phone.json` at build time when it is off; `playUrl`
a constant once the Play listing exists (chapter 12). The IME compares its own `versionCode` with
`imeMin` and shows its own update prompt (chapter 12).

## 11.10 `config_version` and migrations (D2, D21)

- `state.json` carries `config_version` (integer, starts at 1). `version.py` holds
  `CONFIG_VERSION` (the version this build writes) and `MIN_CONFIG_VERSION` (the oldest it can
  migrate from; published as `min_config_version` in `latest.json`).
- Migrations live in `migrations.py` (new) as an ordered list of numbered steps, each a function with a
  one-line docstring saying what changed; each runs once, in order, at the first start after an update,
  before the config is loaded by anything else, and writes `config_version` only after all steps
  succeed. A failing step leaves the files untouched, shows the "Settings could not be upgraded" card
  with [Report a problem] and [Continue with defaults], and never loops.
- Steps may rename or split keys in `settings.toml` and `state.json`, move a store inside `DATA_DIR`, or
  add a consent kind; they never touch Credential Manager entries except through `secrets.py`
  (chapter 3), and they never delete personal data.
- Step 1 is the `--migrate` import of chapter 3 for the owner's legacy `config.toml`; it is explicit,
  never automatic (D4), and therefore not in the ordered list — it sets `config_version` to the current
  value when it finishes.
- A user whose `config_version` is below `min_config_version` sees, instead of the Update card, "Install
  DeskIT <intermediate> first" with the intermediate installer's link taken from a `bridges` table the
  workflow keeps in the release notes of the version that raised `MIN_CONFIG_VERSION`.
- The check for "did the version change" is `state.json` `[updates] installed_version`; Store and winget
  updates hit the same path because it is the first start that matters, not the download.

## 11.11 Release checklist for the owner (D21, D28)

Every item that code can do is in the release workflow (chapter 10); this is what remains by hand,
in order.

1. Edit `VERSION` (and only `VERSION`); commit "Release x.y.z"; the Android `versionCode` follows by
   itself (11.2).
2. Write the release notes in `CHANGELOG.md` under the new heading — Hebrew paragraph first, English
   second (the guide's language rule, D26); the fixed "Previous version" block is inserted by the
   workflow, do not write it.
3. `git tag vx.y.z` and push the tag. The workflow refuses a tag that does not equal `VERSION`, a
   `VERSION` that is not greater than the last release, or a `-beta` tag on a non-pre-release.
4. Wait for the workflow: wheelhouse with `--require-hashes`, embeddable Python, `git archive`,
   `MANIFEST.sha256`, attestation, Inno build, `latest.json`, VirusTotal submission, draft release with
   the notes, the SHA-256, the attestation link and the VirusTotal link (chapter 10 lists the jobs).
5. Read the VirusTotal result; more than two engines flag → do not publish; submit the false positive to
   Microsoft (chapter 10 FAQ) and wait for the re-scan before continuing.
6. Install the draft build over the previous version on the owner's second machine (not the portable
   dev checkout): the Update card path, the toast, `--verify` clean, one dictation, one report preview.
7. Publish the draft release (un-tick "pre-release" for stable). From this moment the weekly check
   finds it.
8. winget: the workflow opens the `wingetcreate update` PR with the new URL and hash; the owner answers
   moderator comments within ten days or the PR closes (`research/updates`).
9. Store (from phase 3): upload the MSIX built by the same run in Partner Center, paste the same notes,
   submit; certification takes days and can fail on a screenshot, so the GitHub release is never held
   for it.
10. Phone (from phase 4): the APK is attached by the workflow; if `imeMin` rose, say so in the first
    line of the notes.
11. Watch `problems\inbox` (chapter 7) for reports stamped with the new version for a week; a
    regression means a PATCH release, never an edit of the published assets.

## Acceptance

- `VERSION` is the only place a version is typed; `git grep` for a hard-coded `1.` version string in
  `app\`, the Inno script, the winget manifest, the MSIX manifest and `build.gradle.kts` finds none.
- A fresh install of 1.2.0 with consent on, faced with a release 1.3.0 on a test repository: the About
  row shows "1.3.0 available" within the first hour; the card lists size and SHA-256; [Download and
  install] produces `network.log` rows for exactly `api.github.com`, `github.com`,
  `objects.githubusercontent.com` with the two purposes and no query string; the app closes itself, Inno
  runs silently, the app reopens on 1.3.0 with the toast; `settings.toml` is byte-identical to before,
  `settings.toml.bak` exists, Credential Manager entries, `models\` and `packs\` are untouched; `deskit
  --verify` is clean.
- The same with a tampered `latest.json` `sha256`: the download is discarded, nothing runs, the card
  explains, `app.log` holds both hashes.
- With `channel = "beta"` and a 1.4.0-beta.1 pre-release published: the card offers it; with
  `channel = "stable"` it does not.
- With `[privacy] update_check` off or Offline on: no request to `api.github.com` in a week of uptime
  (mock clock), and the About row says why.
- Installing 1.2.0's installer by hand over 1.3.0 yields a working 1.2.0 with the previous settings
  (same `config_version`), and the "Restore the settings from before the last update" button appears
  only when `.bak` exists.
- A report from the updated build carries `version`, `os_build`, `gpu`, `tier`, `config_version` and no
  `branch`/`python`.
- `/api/version` on the PC returns the five fields; the IME below `imeMin` shows its own prompt.

## Tests to add

| Test | Asserts |
|---|---|
| `test_version_file_is_single_source` | `version.py` reads `VERSION`; the parsed tuple, the four-part Windows string and the Android `versionCode` for `1.2.3`, `1.2.3-beta.4` and `2.0.0` match the table in 11.2 |
| `test_version_no_git_on_user_machine` | without `.git` beside `main.py`, `version.branch` is `""` and no subprocess is spawned (patched `subprocess.run` never called) |
| `test_problems_env_fields` | `problems.env()` has `version`, `os_build`, `gpu`, `tier`, `config_version` and lacks `branch`, `python` |
| `test_latest_json_schema` | a generated feed has exactly the seven fields with the right types; a feed missing `sha256` is rejected by the parser |
| `test_update_check_respects_gate` | with `[privacy] update_check` false or `offline` true, the scheduler makes no call in a simulated week |
| `test_update_check_cadence` | with the gate on, exactly one call in a simulated 13 days, the second at day 14; "Check now" calls immediately |
| `test_update_check_request_shape` | the mock transport sees host `api.github.com`, path `/repos/<org>/DeskIT/releases/latest`, no query string, no cookie, User-Agent `DeskIT/<version>`, `purpose == "update check"` |
| `test_update_check_beta_channel` | with `channel = "beta"` the request lists releases and the newest by SemVer wins, including a stable one newer than the beta |
| `test_update_semver_compare` | `1.3.0` > `1.3.0-beta.2` > `1.3.0-beta.1` > `1.2.9`; equal or lower versions show no card |
| `test_update_skip_version` | after "Skip" for `1.3.0`, `1.3.0` shows no card and `1.3.1` does |
| `test_update_card_hidden_while_busy` | with a hold, a model download or a recording active, the card is queued and appears on idle |
| `test_update_download_sha_mismatch_discards` | a body whose hash differs from `sha256` is deleted, the installer is never started (patched `Popen` not called), both hashes are logged |
| `test_update_download_sha_match_runs_inno` | the `Popen` argument list is the installer path plus exactly `/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /NORESTART /LOG=<path>`, `settings.toml.bak` exists, and the quit event is signalled |
| `test_update_channel_file_store_disables_check` | `APP_DIR\CHANNEL == "store"` → no scheduler, About text names the Store; `"winget"` → the card shows the `winget upgrade` line and no download button |
| `test_update_first_start_toast_and_migrations` | `installed_version` lower than `version.py` → migrations run once, `installed_version` and `config_version` are rewritten, the toast is emitted once |
| `test_migrations_run_in_order_once` | three fake steps run in order; a re-run does nothing; a failing second step leaves `config_version` and both files unchanged and emits the failure card |
| `test_migrations_min_config_version_bridge` | `config_version` below `min_config_version` yields the "install intermediate first" card and never the download button |
| `test_inno_script_never_names_data_dir` | static: the Inno script's `[Files]`/`[InstallDelete]` sections contain no path under `%LOCALAPPDATA%\DeskIT` (the uninstaller's optional data removal is the one allowed reference and lives in `[Code]`) |
| `test_api_version_fields` | `GET /api/version` returns `pc`, `imeMin`, `imeLatest`, `apkUrl`, `playUrl`; `pc` equals `version.VERSION`; `/health` no longer returns `apk` |

## Open points

1. D21 names the Store as auto-updating and winget as `winget upgrade`; the plan adds a build-time
   `APP_DIR\CHANNEL` marker to tell the three apart. D20 does not mention it — chapter 10 must produce it
   in each of its three build variants, or the app cannot know to hide the download button.
2. The winget `PackageIdentifier` is not decided: `arch-B §9` proposes `Yoav.DeskIT`, while D5 renames the
   AppUserModelID away from `Yoav.DeskIT` to `DeskIT.App` for a different reason. The winget id is a
   publisher-qualified name and may stay `Yoav.DeskIT`; chapter 10 should fix it and the card's copy
   command depends on it.
3. `/RESTARTAPPLICATIONS` relies on `RegisterApplicationRestart`; the research notes it as needed for a
   clean relaunch but the interaction with `pythonw.exe app\deskit.pyw` as the registered command is
   untested. If Restart Manager relaunches the wrong path, the fallback is Inno's `[Run]` section with
   `postinstall` launching the shortcut target — decide in phase 2 after one real update on the VM.
4. D21 says "rollback = the previous installer linked in the release notes"; the `settings.toml.bak`
   restore button proposed here is an addition consistent with D9's Your data page but not named there —
   chapter 4 should list the row or the button moves to About.


---

# 12. Android companion: pairing, identity, delivery

This chapter implements **D22** (phone pairing on the user's own Wi-Fi, Tailscale optional, no relay) and the Android
half of **D21** (shared `VERSION`, `versionCode` mapping, `/api/version`). It leans on D1 (the phone's files live under
`DATA_DIR\phone\`), D3 (the TLS private key and per-phone tokens are DPAPI-wrapped), D5 (the port fall-through written to
`state.json`), D8 (the token never reaches `app.log`), D12 (loopback stays the only listener unless the user picks a
transport) and D25 (the privacy policy sentence about "your own network"). Screen contents for Settings > Phone are
summarised here and detailed in chapter 9 (screen 9); the wizard never mentions the phone. Evidence throughout:
`map/phone`, `research/android`, `arch-B §10`.

## 12.1 What the phone does today and what changes

Today the phone records and the PC transcribes: `server.py` is a loopback-only `ThreadingHTTPServer` inside the desktop
process (`main.py:771-781`, started `main.py:2058-2064`), fronted by `tailscale serve --bg 8756` with a Let's Encrypt
certificate (`server.py:1-30`, `641-663`), guarded by one bearer token in `server_token.txt` beside the code
(`server.py:67, 97-112`). The Android IME (`com.yoav.dictation`) talks plain `HttpURLConnection` with no third-party
libraries (`Transcriber.kt:10-13`), refuses cleartext except to the emulator host (`network_security_config.xml:8-10`),
and ships the owner's tailnet name as `DEFAULT_URL` (`Prefs.kt:25`). The APK is the debug build served from the source
tree at `/app.apk` (`server.py:68-69, 217-240`). `map/phone` "What breaks on a fresh machine" lists eleven cliffs;
the first (no Tailscale = hard stop) and the fourth (owner's hostname pre-filled) are the ones a stranger hits in the
first minute.

The product keeps the shape (the phone records, the user's own PC transcribes, nothing else is in the path) and changes
the transport, the identity and the delivery:

| Today | Product (D22) |
|---|---|
| Tailscale mandatory, `tailscale serve` typed by hand | `server.transport = "off" \| "lan" \| "tailscale"`; LAN is the default once the user turns the phone on; Tailscale is a documented option (12.5) |
| Let's Encrypt cert via Tailscale | PC-generated self-signed cert, fingerprint pinned by the phone (12.2) |
| One token in `server_token.txt` beside the code | One-time pairing token in the QR; per-phone bearer tokens in `DATA_DIR\phone\phones.bin` (DPAPI) (12.2, D3) |
| Token in `app.log` and on the clipboard (`server.py:653-654`, `dashboard.py:8091-8099`) | Host only in the log (D8); the token exists in the QR and behind a Reveal button (12.4) |
| `DEFAULT_URL` = owner's tailnet (`Prefs.kt:25`) | Deleted; Home shows "Not set up yet" (`HomeActivity.kt:182-185` already handles the empty case) |
| Package `com.yoav.dictation` | `io.github.massifapp.deskit` (12.6) |
| Debug-signed APK from `/app.apk` | Release-signed universal APK on GitHub Releases, later Play (12.8) |
| `/health` leaks backend and version to anyone | `/health` = `{ok, version}` (12.3) |
| `GET /review` returns every pending proposal (`server.py:437-448`) | Scoped to `source == "phone"` (12.3) |
| Hebrew web page at `/` (`server.py:670-834`) | Retired (12.11) |

## 12.2 Pairing protocol, step by step

The pattern is LocalSend / KDE Connect (`research/android` "LocalSend model"): each PC has a self-signed certificate whose
SHA-256 fingerprint is its identity, the phone learns the fingerprint out of band (QR), and every later connection is TLS
to exactly that certificate plus a bearer token. The IME needs no browser secure context (`research/android` source 4:
"native apps have no browser secure-context problem"), so no public certificate is needed.

**Step 0 — the user turns the phone on.** Settings > Phone, transport switch set to "Home Wi-Fi" (12.4). This is the only
consent the feature needs: the PC now listens on the LAN, and the page says so. `server.enabled` stays the master switch
(`config.py:1112-1125`); the transport is the new key.

**Step 1 — certificate.** On the first switch-on the PC creates one keypair and a self-signed X.509 certificate (CN
`DeskIT`, validity 10 years; no SAN is needed because the phone matches the fingerprint, not the name). Files:
`DATA_DIR\phone\cert.pem` (public, plain) and `DATA_DIR\secrets\phone_key.bin` (private key, DPAPI user scope, D3).
`phone.fingerprint()` returns the SHA-256 of the DER certificate as 64 hex characters; the page shows it in groups of
four so a user can compare it with the phone. Chapter 10 decides which wheel generates it (open point 4); this chapter
only requires "generate once, never regenerate silently". "Rotate" (12.4) regenerates the certificate and invalidates
every paired phone by design.

**Step 2 — pairing token.** Pressing "Pair a phone" creates a one-time token (`secrets.token_urlsafe(24)`, the same size
as today's `server.py:97-112`), valid for 10 minutes, single use, kept only in memory. It is never written to
`settings.toml`, `state.json` or `app.log`.

**Step 3 — QR payload.** The page renders a QR (a pure-Python QR encoder is a small wheel; the dashboard already draws
bitmaps, chapter 9) that encodes
`deskit://pair?host=<LAN IPv4>&port=<port>&fp=<64 hex>&token=<one-time>&name=<PC name>`. `host` is the first
non-loopback IPv4 of the adapter with the default route (Wi-Fi first); when the machine has several, the page lets the
user pick and the QR carries the choice. The QR is never logged; the same payload sits behind a "Show as text" button
for phones without a camera, and the IME keeps a paste field that accepts that text (replacing `Prefs.parsePasted`,
`Prefs.kt:130-136`, which parses the old `https://host/#t=` form).

**Step 4 — discovery (optional, first).** The PC advertises `_deskit._tcp.local.` on the LAN (the `zeroconf` wheel; TXT
record carries `fp` and `name`, never a token) while the transport is "lan". The IME's Settings screen opens the system
picker through `NsdManager` with `DiscoveryRequest.FLAG_SHOW_PICKER`, the path that survives the Android 17
local-network permission (`research/android` source 6: addresses returned by the picker "can now be connected to without
ACCESS_LOCAL_NETWORK permission"). Picking a PC fills `host`/`port`/`fp`; the user still scans (or types) the one-time
token because discovery is unauthenticated. The QR alone is the fallback when mDNS is blocked (guest networks, AP
isolation) and is the path the guide teaches first because it needs no explanation.

**Step 5 — pinning and exchange.** The IME opens `https://<host>:<port>/pair` with a custom `X509TrustManager` that
accepts exactly one leaf certificate: the one whose DER SHA-256 equals `fp`. Hostname verification is replaced by the same
check (the connection is to an IP). Network-security-config XML stays as it is (cleartext forbidden) and is not used for
pinning, because it is static and cannot pin a per-user certificate (`research/android` source 4). The request body is
`{token, phone_name, phone_id, ime_version_code}`; `phone_id` is a random UUID the IME generates once. The PC checks the
token (constant-time, single use), records the phone, and answers `{bearer, pc_name, version, ime_min, protocol}`. The
bearer is `secrets.token_urlsafe(32)`, per phone; the PC stores `{phone_id, name, bearer_hash, paired_at, last_seen}` in
`DATA_DIR\phone\phones.bin` (DPAPI, D3) — the hash, not the bearer, so a copied file is useless. The IME stores
`host, port, fp, bearer, pc_name` in `EncryptedSharedPreferences` (the one AndroidX dependency this adds; the
"no dependencies" stance at `build.gradle.kts:37` gives way for this file only). `allowBackup="false"` stays
(`AndroidManifest.xml:14`).

**Step 6 — every later call.** `Transcriber.kt` keeps its route set (`/transcribe`, `/punctuate`, `/translate`, `/health`,
`/review`, `/review/decide`, `/lookup`, `Transcriber.kt:32-181`) but every connection goes through the pinned trust
manager and sends `Authorization: Bearer <per-phone>`. A 401 means "this PC forgot you"; the IME shows "Pair again" and
clears the bearer only, not the transcript list.

**Forget and rotate.** On the phone, "Forget this PC" clears `host/port/fp/bearer/pc_name` and the "What you said" list
(`Prefs.kt:19, 85-108`) after a confirmation, and tells the PC through `POST /unpair` when reachable. On the PC, each
paired phone row has Forget (deletes the row; the phone's next call gets 401) and the page has Rotate (new certificate,
new fingerprint, every row deleted; the page says "every phone must pair again"). Forget and rotate are the answer to
"my phone was stolen" and go into the guide (chapter 14).

**What never happens.** No relay (Supabase Realtime is capped at 200 concurrent connections and 256 KB frames and pauses
after a week; Cloudflare tunnels need a domain and route audio through third-party infrastructure — `research/android`
source 10 and "Cloudflare quick tunnels"); no owner-run host in the path; no token in a URL fragment; no cleartext.

## 12.3 PC-side changes (server.py and friends)

| Where | Today | Change |
|---|---|---|
| `server.py:66-70` | `APP_DIR`, `TOKEN_FILE`, `APK`, `APK_GRADLE` resolved beside the code | `TOKEN_FILE`, `APK`, `APK_GRADLE` and `apk_version()` (`server.py:73-85`) deleted; paths come from `paths.py` (chapter 3): `phone\cert.pem`, `phone\phones.bin`, `secrets\phone_key.bin` |
| `server.py:97-112` `load_token()` | One shared token, written to the code folder | Replaced by `phone.PairingStore`: `issue_pairing_token()`, `redeem(token, phone) -> bearer`, `check(bearer) -> phone_id or None`, `forget(phone_id)`, `rotate()` |
| `server.py:204-209` auth | Constant-time compare of one token | Constant-time compare of the bearer's hash against every stored row; the matching `phone_id` is attached to the request so `last_seen` updates and the log can say "phone <name>" (never the token) |
| `server.py:213-244` `do_GET` | `/`, `/app.apk`, `/health` (`{ok, backend, apk}`), `/review` | `/` and `/app.apk` removed (404); `/health` → `{ok, version}` where `version` is the PC's `VERSION` (chapter 11); new `GET /api/version` (12.9); `/review` scoped by `source == "phone"` (the sidecar field already written at `main.py:388-401`), with a `[server] review_scope = "phone" \| "all"` advanced key for the household that wants desk proposals on the phone (`map/phone` rec 6) |
| `server.py:272` route table | POST routes | Adds `POST /pair` (no bearer, one-time token) and `POST /unpair` (bearer) |
| `server.py:641-663` `PhoneServer.start()` | Binds loopback, probes Tailscale, logs the token URL | Binds by transport: `off` → not started; `lan` → `0.0.0.0` (IPv4) wrapped in an `ssl.SSLContext` loaded from the cert and the DPAPI-unwrapped key, TLS 1.2+; `tailscale` → loopback plus the existing `tailscale serve` front (unchanged behaviour), pairing over the tailnet IP with the same cert pinning so the phone never depends on the Tailscale certificate. The log line `open this on the phone: <url>` (`server.py:653-654`) becomes `phone listening on <host>:<port> (<transport>)` — D8 |
| `server.py:91` `MAX_BODY` | 32 MiB | Kept; `Recorder.kt` caps clips at 300 s (~9.6 MB) |
| `server.py:166-178` `to_wav()` | Decodes any container through PyAV | The IME sends WAV already; the decoder stays for non-WAV bodies only when the Recording pack (chapter 6) is installed, otherwise the route answers 415 with "send WAV" — removes the `av` import from the base path (`map/phone` break 9, D24) |
| `server.py:670-834` `PAGE` | The Hebrew web client | Deleted (12.11) |
| `config.py:1112-1125` `ServerConfig` | `enabled`, `host`, `port` | `host` removed (it was the loopback-only invariant, `tests.py:3965-3977`); adds `transport = "off"` (user), `review_scope = "phone"` (advanced); `port = 8756` moves to advanced with the "restart needed" note; the chosen port after fall-through lives in `state.json` (D5). `defaults.toml` ships `enabled = false` (the owner's `config.toml:1297-1308` has `true`; D6) and the stale "binds to the Tailscale address" comment (`config.toml:1302-1304`, mirrored at `settings.py:1143-1145`) is rewritten because it feeds the generated Settings page |
| `main.py:771-781` | Builds `PhoneServer` when `cfg.server.enabled` | Also passes the transport and the pairing store; on bind failure (port busy) the Phone page shows the reason and the next free port instead of the silent warning at `main.py:2058-2064` (`map/phone` break 8) |
| `main.py:1760` status `phone` | The token-bearing URL | Becomes `{transport, host, port, fingerprint, phones: [...], pairing_open: bool}`; no token |
| `dashboard.py:7664-7690` `_phone_block`, `dashboard.py:8091-8099` `_copy_phone` | URL label + "Copy link" | Replaced by the Settings > Phone page (12.4); "Copy link" removed |
| `notify_hook.py:54` | Reads `server_token.txt` | Reads a separate local-only token from `DATA_DIR\secrets\hook_token.bin` written when "Connect Claude Code" is switched on (D15); `/notify` accepts either a phone bearer or the hook token and stays loopback-reachable in every transport (open point 5) |
| `settings.py:618-626, 655, 1143-1145, 1374-1376` | Phone tab rows for `enabled`, `port`, `host` | Rows regenerate from `defaults.toml`: `enabled` (user), `transport` (user, three words), `port` (advanced), `review_scope` (advanced); the `WORDS` entries get new plain sentences |
| `tests.py:3931, 16447` | `yoav.example.ts.net` fixtures | Renamed to `pc.example` fixtures when the tests move to the product suite (chapter 7) |
| `README.md:3371-3524` | Tailscale walkthrough | Retired; the guide's Phone chapter replaces it (chapter 14) |

Windows Firewall: the first `lan` bind triggers the Windows Defender Firewall prompt for `pythonw.exe` once, on the
private profile. The installer adds no rule (it runs without admin, D20); the Phone page explains the prompt before the
user flips the switch, and the FAQ covers "I clicked Cancel" (allow it later under Windows Security > Firewall > Allow an
app). No rule on the public profile — the page says "home Wi-Fi", and the OS honours that.

## 12.4 Settings > Phone page

Chapter 9 (screen 9) carries the full layout; the behaviour it must implement:

| Element | Behaviour | Writes |
|---|---|---|
| Transport: Off / Home Wi-Fi / Tailscale | Radio; switching to Home Wi-Fi shows the firewall sentence and starts the listener; Tailscale shows the `tailscale status` result and the three former README traps (`README.md:3495-3510`) as status lines (`map/phone` rec 2) | `settings.toml [server] transport`, `enabled` |
| Status line | "Listening on 192.168.1.20:8756 · fingerprint AB12 CD34 …" or the bind error and the port picked instead | — |
| Pair a phone | Opens the pairing panel: QR, "Show as text", 10-minute countdown, "Waiting for the phone…" that turns into "Paired: <phone name>" | in-memory token; `phones.bin` on success |
| Get the keyboard | Second QR = the GitHub Releases download URL from `latest.json` (chapter 11), later the Play URL; caption "Android 8 or newer" | — |
| Paired phones | Table: name, paired on, last seen, [Forget] | `phones.bin` |
| Rotate | Confirmation "Every phone will need to pair again", then new cert + empty table | `cert.pem`, `phone_key.bin`, `phones.bin` |
| Reveal fingerprint | The 64 hex characters, for a user who wants to compare with the phone's Settings screen | — |
| Advanced: port, review scope | Port with "restart needed"; "Show desk proposals on the phone too" | `settings.toml`, `state.json` for the fall-through port |

The page never shows a bearer. The old dashboard Phone block and its "Copy link" go (12.3).

## 12.5 Firewall and Tailscale

Tailscale stays exactly what `map/phone` calls it: the away-from-home path. With transport = Tailscale the PC keeps
binding loopback and the user keeps running `tailscale serve --bg <port>` once (the app may run it on the user's click,
`map/phone` rec 2, with the "Serve not enabled → click the link" flow shown as a status line); the pairing QR then carries
the tailnet IPv4 (100.x) instead of the LAN address and the same fingerprint, so the phone pins the PC's certificate and
not Tailscale's — one trust model for both transports. `_tailscale_exe()` (`server.py:115-125`) additionally probes
`%LOCALAPPDATA%\Tailscale` for per-user installs (`map/phone` break 10). The guide (chapter 14) presents Tailscale as
optional, three sentences, no screenshots of the owner's tailnet.

## 12.6 Package rename checklist

`applicationId` cannot change after the first outside install without every user uninstalling (`map/phone` risk 2), so the
rename is the first Android commit of phase 4 and precedes any APK given to anyone. Target: `io.github.massifapp.deskit`
(D22; no domain purchase). Every place `map/phone` cites:

| File | Line(s) | Change |
|---|---|---|
| `android/app/build.gradle.kts` | 7, 11 | `namespace` and `applicationId` |
| `android/app/build.gradle.kts` | 8, 15 | `compileSdk`/`targetSdk` 34 → 36 (Play requires API 36 for new apps from 2026-08-31, `research/android` source 3); `minSdk 26` stays |
| `android/app/build.gradle.kts` | 16-20 | `versionCode`/`versionName` read from the shared `VERSION` file (12.9) instead of literals |
| `android/app/build.gradle.kts` | 23-29 | `release` gains `signingConfig` from `keystore.properties` (gitignored), `isMinifyEnabled = false` kept, `debuggable = false`; the comment "unsigned release builds cannot be installed" is rewritten |
| `android/app/src/main/java/com/yoav/dictation/**` | all | Directory moves to `io/github/massifapp/deskit/`; package declarations follow |
| `Notify.kt` | 34 | `ACTION_DECIDE = "io.github.massifapp.deskit.DECIDE"` |
| `res/xml/method.xml` | 3 | `settingsActivity` class name |
| `AndroidManifest.xml` | 19-75 | Component names (relative `.HomeActivity` etc. follow the namespace; fully-qualified ones must be edited) |
| `Prefs.kt` | 25, 8-11 | `DEFAULT_URL` deleted, docstring rewritten; prefs move to `EncryptedSharedPreferences` (12.2) |
| `res/values/strings.xml` | 83, 99, 115 | "is Tailscale on?" → "is the PC on and on the same Wi-Fi?"; setup intro without Tailscale |
| `Transcriber.kt` | 219 | Same error text change |
| `HomeActivity.kt` | 108-111 | Update pill opens the URL from `/api/version` (12.9), not `${url}/app.apk` |
| `SettingsActivity.kt` | 77-82, 195-214, 222-241 | URL + token fields → Scan / Pick a PC / Paste; "Save and test" keeps posting one second of silence; "Check for an update" uses `/api/version` |
| `android/tools/emu.py` | 30 | Package name; the whole `tools/` folder moves to `dev/android/` (12.11) |
| `settings.gradle.kts` | — | `rootProject.name` stays `DeskIT`; a `gradlew` wrapper is committed so CI and a second machine build the same way (`map/phone`: "No `gradlew` wrapper is committed") |
| Fastlane metadata | new `android/fastlane/metadata/android/en-US/` and `he-IL/` | short/full description, icon, screenshots — required by IzzyOnDroid (`research/android` source 9) and reused for the Play listing |

The IME label the user sees in Android's keyboard list stays "DeskIT" (`ime_label`).

## 12.7 Release keystore and signing

The owner generates one release keystore (RSA 2048 or EC P-256, validity 25+ years) and backs it up in two places (password
manager attachment + offline copy) — losing it means a new package identity for every user. `keystore.properties` beside
the Android project holds path and passwords and is gitignored; CI (chapter 10) receives the keystore as a base64 secret
and the passwords as secrets, and signs the release build in the same workflow that builds the Windows installer.

Play App Signing (`research/android` source 11): at enrolment the owner either uploads this same key through PEPK so the
Play build and the GitHub build carry one signature, or accepts Google-generated keys and publishes on GitHub the
Play-signed universal APK downloaded from Play Console. Recommendation: upload the owner's key at enrolment (one-time,
irreversible, listed in chapter 16), because it keeps GitHub and Play builds mutually upgradeable and keeps CI as the
single builder.

Debug builds keep the machine's `~/.android/debug.keystore` and stay for the emulator only; a debug APK is never attached
to a release (`map/phone` risk 3).

## 12.8 Delivery: GitHub APK, Play, IzzyOnDroid

**v1 (phase 4): GitHub Releases.** Each PC release tag also carries `DeskIT-<version>.apk` (release-signed, universal,
targetSdk 36, `debuggable=false`; the debug build is 1.2 MB today, `map/phone`) and the `latest.json` of chapter 11
gains `apk_url`, `apk_sha256`, `ime_version_code`, `ime_min_version_code`, `play_url` (empty until Play is live). The
PC's Phone page shows the download QR from `apk_url`. The phone's browser downloads; Android shows "Install unknown apps"
once for the browser — the guide screenshot covers it. Obtainium users add the repo once and get updates automatically
(`research/android` "Obtainium"); the guide mentions it in one line for power users.

**Android developer verification.** Certified devices will require the package and signing key to be registered by a
verified developer — pilot countries from 2026-09-30, global in 2027 (`research/android` sources 2 and 12). The same
US$25 Play Console registration with government ID covers it ("Your existing verified identity … meets this
requirement"; "use the Play Console to register apps you distribute outside of Google Play"). So the GitHub APK is free to
ship today, and the owner's phase-4 Play registration (chapter 16) is what keeps it installable after 2027; the free
20-device hobbyist tier is useless for strangers.

**Phase 4, in parallel: Google Play personal account.** US$25 once, government ID and a card in the legal name, Play
Console phone-app device check (`research/android` source 5); D-U-N-S/organisation accounts are not available without a
company. The app entry auto-registers the package name. Upload an AAB to a **closed testing** track; the 12-testers ×
14-days rule applies to personal accounts created after 2023-11-13 (`research/android` source 1), so the first twelve
early PC users are the testers and the clock runs while the PC side matures. After production access, the Play link
becomes the page's first QR and GitHub stays as fallback.

**Data safety answers** (`research/android` source 7 definitions): Audio (voice recordings) — collected, optional (the
user chooses to dictate), ephemeral processing on the phone, encrypted in transit, not shared with third parties, user can
request deletion (the clips live on their own PC under chapter 4's retention); Personal info / typed text — not collected
by the developer (the IME commits text to the field; the transcript list lives on the phone); Device or other IDs — the
random `phone_id` reaches the user's PC only, not the developer; no analytics, no crash SDK, no ads. Privacy policy URL =
chapter 13's GitHub Pages page. Whether reviewers accept the E2E/ephemeral exemption for audio sent to the user's own PC is
unverified (`research/android` uncertainties), so the conservative declaration above is the one to file.

**IzzyOnDroid (phase 5).** Once the IME is Apache-2.0 (D23), attach the release APK to GitHub releases, keep it under 30 MB,
add Fastlane metadata, and request inclusion (`research/android` source 9). F-Droid main and Galaxy Store are skipped
(signature mismatch and unverified terms).

## 12.9 Version endpoint and in-IME update prompt

One `VERSION` file (chapter 11) feeds both builds: `versionName = MAJOR.MINOR.PATCH`, `versionCode = MAJOR*10000 +
MINOR*100 + PATCH` (`research/android` source 8; well under the 2,100,000,000 cap, strictly increasing as long as
releases only move forward). The Gradle build reads the file at configure time; a CI check fails the build when the
computed `versionCode` is not greater than the previous tag's.

`GET /api/version` on the PC (bearer required, so it leaks nothing to the LAN) returns
`{pc: "1.9.2", ime_min: 10900, ime_latest: 10902, apk_url, apk_sha256, play_url}`; the PC learns `ime_latest` and the URLs
from the last successful update check (chapter 11) and falls back to its own build-time values offline. On every pairing
and on the first `/health` of a session the IME compares its `versionCode`:

| Condition | IME behaviour |
|---|---|
| `versionCode < ime_min` | Blocking card "Update the keyboard to keep dictating" with one button that opens `play_url` when `installerPackageName == com.android.vending`, else `apk_url` |
| `ime_min ≤ versionCode < ime_latest` | One dismissible pill on Home per version (the pill at `HomeActivity.kt:108-111` re-targeted); remembered in prefs so it shows once |
| IME newer than the PC (`protocol` in the `/pair` reply lower than the IME expects) | The PC shows "Your phone's keyboard is newer than DeskIT on this PC — update DeskIT" on the Phone page; the IME keeps working with the routes both sides share |

The old `/health.apk` comparison in `SettingsActivity.kt:222-241` and `apk_version()`'s reading of the gradle source
(`server.py:73-85`, the cause of the served-file/version mismatch recorded in `map/phone` "Owner-only") both go.

## 12.10 Privacy copy for the phone

The sentences the IME's Settings screen, the Play listing and the guide (chapter 14) all reuse, in this order:

1. "Your voice goes from the phone to your own PC and nowhere else. The connection is encrypted and locked to your PC's
   certificate."
2. "Your PC keeps the last N phone recordings so it can learn your words; change N or delete them under Settings > Your
   data on the PC." (N = `vocab.keep_audio`, chapter 4.)
3. "Text you dictate can reach Groq or Google only if you switched those features on, on the PC, under your own key — the
   phone follows the PC's switches." (`main.py:2372, 2433-2477` run the desk's `_improve`, translate and lookup engines;
   D7 gates them.)
4. "The keyboard never types into password fields." (`DictationIme.kt:638-655` already refuses password and
   `NO_PERSONALIZED_LEARNING` fields.)
5. "The phone keeps your last 30 dictations so you can copy them again; Clear removes them. Nothing on the phone is
   backed up to Google." (`Prefs.kt:85-108`; `allowBackup="false"`.)
6. "The developer never sees your audio, your text or your PC's address. There is no analytics code in this app."

The Android system's own warning when enabling any keyboard ("may be able to collect all the text you type") is quoted in
the guide with the explanation that it is generic and what DeskIT actually does with text.

## 12.11 What is cut

- The Hebrew web page at `/` (`server.py:670-834`), its `localStorage` token and the secure-context requirement that made
  Tailscale mandatory (`map/phone` rec 10). The keyboard is the phone client.
- `/app.apk` and the `APK`/`APK_GRADLE` constants (`server.py:66-70, 217-240`): end users have no Gradle; the APK is a
  release asset (12.8).
- `android/tools/emu.py` and `android/tools/fake_pc.py` (absolute owner paths, `map/phone` "Owner-only") → `dev/android/`,
  excluded from the build manifest (D15); the fake PC keeps working for screenshot checks on the hidden desktop.
- `server_token.txt` and the shared-token model; `Prefs.DEFAULT_URL`; the Tailscale wording in `strings.xml`; the
  README phone chapter.
- `server.host` as a setting (12.3).

## Acceptance

- A clean Windows 11 laptop (no Tailscale) and a phone on the same home Wi-Fi: Settings > Phone → Home Wi-Fi → firewall
  prompt accepted → Pair a phone → scan → "Paired" within one minute; a Hebrew sentence dictated in a WhatsApp field lands
  on the phone; `logs\network.log` (D12) shows nothing but loopback and the phone's LAN address during the whole session.
- The same phone with Tailscale on both ends, transport = Tailscale: pairing over the 100.x address, same fingerprint.
- Wireshark on the LAN shows TLS only; a second PC presenting a different certificate on the same address is refused by the
  IME before any request is sent.
- `app.log`, `settings.toml`, `state.json`, a problem report (chapter 7) and `--diagnose` output contain no bearer, no
  pairing token and no `#t=` fragment.
- Forget on the PC → the phone's next call is 401 and shows "Pair again"; Rotate → every phone shows it; "Forget this PC"
  on the phone → Home says "Not set up yet" and the transcript list is empty.
- `DeskIT-<version>.apk` from GitHub Releases installs over the previous release build without uninstall; no debug build
  exists on the release page.
- Play closed test: 12 testers opted in for 14 days; Data safety form accepted with the answers in 12.8.
- The IME shows the blocking update card when the PC's `ime_min` is above its `versionCode`, and nothing when equal.

## Tests to add

| Test | Asserts |
|---|---|
| `test_phone_pair_redeems_once` | The one-time token pairs one phone and a second redeem with the same token is 401; an expired (10 min) token is 401 |
| `test_phone_bearer_per_phone` | Two paired phones get different bearers; forgetting one leaves the other working; `phones.bin` holds hashes, not bearers |
| `test_phone_rotate_invalidates_all` | After `rotate()` the fingerprint changes and every stored bearer is refused |
| `test_phone_no_secret_in_logs` | With a paired fixture phone, `app.log`, `network.log`, the status payload and `problems.env()` contain neither the bearer nor the pairing token (extends D12 lock 1) |
| `test_phone_transport_off_no_socket` | `transport = "off"` starts no listener; `"lan"` binds `0.0.0.0` with TLS; `"tailscale"` binds loopback only (replaces the loopback invariant at `tests.py:3965-3977`) |
| `test_phone_health_minimal` | `/health` returns only `ok` and `version`; `/` and `/app.apk` are 404 |
| `test_phone_review_scoped` | `GET /review` returns proposals with `source == "phone"` only unless `review_scope = "all"` |
| `test_phone_api_version_fields` | `/api/version` requires a bearer and returns the six fields; `ime_min ≤ ime_latest`; the `versionCode` mapping of `VERSION` equals `MAJOR*10000+MINOR*100+PATCH` |
| `test_phone_transcribe_wav_only_without_pack` | A non-WAV body is 415 when the Recording pack is absent and decoded when present |
| `test_phone_port_fallthrough_written` | Port busy → next free port used and written to `state.json`; status reports it |
| `test_phone_qr_payload_shape` | The pairing payload parses to `host, port, fp (64 hex), token, name` and contains no bearer |
| `test_build_manifest_excludes_android_tools` | `dev/android/` and `android/` sources are absent from the product tree (chapter 7 manifest) |
| Android instrumented: `PinnedTrustManagerTest` | Accepts the certificate whose SHA-256 matches, rejects any other, rejects when `fp` is empty |
| Android instrumented: `PairFlowTest` | Against the fake PC on the hidden desktop: pair → bearer stored in `EncryptedSharedPreferences` → transcribe works → Forget clears prefs and the said-list |
| Android unit: `VersionGateTest` | Blocking card below `ime_min`, one pill between, nothing at latest; Play vs GitHub URL chosen by installer package |
| CI: `versioncode-monotonic` | The tag's computed `versionCode` exceeds the previous tag's |

## Open points

1. D22 names `NsdManager` discovery with `FLAG_SHOW_PICKER`, an API that only recent Android versions expose; on `minSdk
   26` devices the picker is unavailable and the QR is the only path. The chapter treats QR as primary and discovery as
   an enhancement; confirm that is the intended reading rather than a discovery-first UX.
2. The one-time token and the certificate fingerprint both travel in the QR; a phone that discovers the PC by mDNS still
   needs the token typed or scanned. If the owner wants a "tap the PC name and confirm a 6-digit code on both screens"
   flow (KDE Connect style) instead, the PC page needs a code display and `/pair` a challenge step — not in D22, so not
   specified here.
3. `EncryptedSharedPreferences` is deprecated in recent AndroidX security-crypto releases though still functional;
   the fallback is the Android Keystore plus a plain prefs file holding an AES-GCM-wrapped bearer. D22 names
   `EncryptedSharedPreferences`; the implementer should check the library status in phase 4.
4. Which wheel generates the certificate (`cryptography` vs a build-time helper) is a chapter 10 wheelhouse decision;
   `cryptography` adds a Rust-built binary wheel to the base set.
5. `/notify` with a separate hook token (12.3) is a reading of D15 and D22 together; if the hook is meant to keep using a
   phone bearer, the "Connect Claude Code" switch would have to pair a virtual phone instead.


---

# 13. Licence, notices, privacy policy, terms, Israeli law

Implements D23, D24, D25 (and leans on D10-D11 for the provider clauses). Everything here is zero-cost except the optional one-hour lawyer review named in D25. Cross-references: the consent-card wording lives in chapter 5, the packs mechanics in chapter 6, the Supabase schema in chapter 8, the wizard screens in chapter 9, the installer in chapter 10, the guide in chapter 14, the owner's hand-work list in chapter 16.

## 13.1 Licence recommendation and the cost of the alternative (D23)

**Recommendation: Apache-2.0**, file `LICENSE` at the repo root, copyright line "Copyright 2026 Yoav Shimron" (copyright vests in the individual; no company is needed, `research/legal` "What the owner must do by hand" item 1). The research report itself ranked FSL first and Apache second; D23 flips the order for three reasons that the report did not weigh:

1. The key-privacy proof (D12, chapter 5) is "read the code". A stranger's willingness to read the code is highest when the licence is one they already recognise as open source; FSL is "Fair Source", not OSI (`research/legal` options table).
2. Three free trust amplifiers require an OSI licence: SignPath's free code signing for open-source projects (`research/signing` source 2, chapter 10), IzzyOnDroid for the Android APK (`research/android` source 9, chapter 12) and Certum's open-source certificate tier. Under FSL those are gone: the installer stays unsigned forever, or the owner pays EUR 49-400 per year for a certificate (D23).
3. Apache-2.0 carries an explicit patent grant and the warranty disclaimer, so no EULA is needed for the app (13.7).

**Cost of the runner-up (FSL-1.1-Apache-2.0).** What it buys: for two years after each release nobody may ship a competing product built from that release; then the release converts to Apache-2.0 automatically (`research/legal` FSL row, fsl.software). What it costs: the three amplifiers above (unsigned SmartScreen warnings on every download, or a paid certificate), "source-available" instead of "open source" in every listing, and IzzyOnDroid refusing the APK. It changes nothing else in this chapter: NOTICES, policy, terms and Israeli duties are identical (`arch-B §11`).

**Rejected.** AGPL-3.0: NVIDIA's EULA forbids using the SDK "in any manner that would cause it to become subject to an open source software license", so CUDA DLLs could never sit beside AGPL code in one bundle, and workplace users avoid AGPL tools (`research/legal` round 4, options table). PolyForm Noncommercial: forbids dictating at work, which breaks "free for users" (`research/legal` options table). MIT: equivalent to Apache in freedom but without the patent grant; Apache is the norm for the model chain DeskIT rides on (ivrit-ai, Gemma 4).

**Compatibility check of the chosen licence with what ships.** Every runtime dependency is MIT / BSD / PSF / OFL / Apache (`research/legal` component table); the two proprietary or copyleft items (NVIDIA wheels, GPL FFmpeg inside the PyPI `av` wheel) are kept outside the installer by 13.4, so the installer as a whole is distributable under Apache-2.0 with no exception text.

**Owner action (phase 0, chapter 16):** confirm Apache-2.0 or FSL. Until confirmed, the repo carries no LICENSE and the first public tag must not be cut.

## 13.2 TRADEMARK.md

Apache-2.0 §6 already withholds trademark rights, but a one-page `TRADEMARK.md` at the repo root makes the position readable to a forker and to a store reviewer (D23). Contents, in this order:

| Section | What it says |
|---|---|
| What is reserved | The name "DeskIT" (any casing, Hebrew transliteration included), the dalet-as-desk mark and the application icon (`make_icon.py` / `icon.ico`, `map/ui` line 33) are marks of Yoav Shimron and are not covered by the Apache-2.0 licence. |
| What you may do | Fork, build and run the code under Apache-2.0; say "based on DeskIT" or "a fork of DeskIT" in plain text; keep the name in unmodified builds of a tagged release; link to the project. |
| What you may not do | Publish a modified build, a store listing, a domain or an app-store account under the name DeskIT or with the icon; imply the owner endorses a fork; use the mark on merchandise. |
| Renaming a fork | Change the product name in `VERSION`/About (chapter 11), the AppUserModelID `DeskIT.App` (D5), the Inno `AppId` (chapter 10), the Android package id (chapter 12), the icon, and the `%LOCALAPPDATA%\DeskIT` folder name (D1) so the two products never share data. |
| No registration claimed | The mark is unregistered in Israel and elsewhere; the file claims common-law use only, and says so, to stay honest. |
| Contact | The same e-mail as the privacy policy (13.6). |

The file is referenced from `README.md`, the About tab, and the Store/Play listing text (chapters 10 and 12). It ships inside `APP_DIR` next to `LICENSE` (D1).

## 13.3 THIRD-PARTY-NOTICES.txt (D24)

One plain-text file, shipped in `APP_DIR` (D1) and linked from About and the guide. It has two halves: a **generated** half (every wheel in the base wheelhouse, produced at build by `pip-licenses --with-license-file --format=plain-vertical` in the GitHub Actions job of chapter 10, so it never drifts from the pinned requirements) and a **hand-written** half (`dev/notices-extra.txt`, concatenated after it) for everything pip does not know about. Each entry states: component name, version, copyright line, licence name, the full licence text verbatim, any upstream NOTICE file, and a source URL. Packs (chapter 6) carry their own `THIRD-PARTY-NOTICES.txt` inside `DATA_DIR\packs\<name>\`, written by the same generator at pack-build time, because their contents are not in the installer.

| Component | Licence | Ships where | Obligation | Text comes from |
|---|---|---|---|---|
| Python 3.11 (embeddable) | PSF-2.0 | installer | keep notice + `LICENSE.txt` | hand: the `LICENSE.txt` inside the python.org zip (`research/legal` round 4) |
| Tcl/Tk | BSD-style | installer | notice "included verbatim in any distributions" | hand: tcl-lang.org licence page (`research/legal` round 3) |
| faster-whisper (SYSTRAN) | MIT | installer (pip) | notice | generated |
| CTranslate2 (OpenNMT) | MIT | installer (pip) | notice | generated |
| OpenAI Whisper code + weights | MIT | no (weights via Hugging Face) | notice | hand (`research/legal` round 3) |
| ivrit-ai `whisper-large-v3-turbo-ct2` | Apache-2.0 | no (user downloads from HF, chapter 6) | notice + attribution line + link to the model card; courtesy cite of arXiv 2307.08720 | hand: HF model card (`research/legal` round 2) |
| Rubik (4 static cuts + `OFL.txt`) | SIL OFL 1.1 | installer `fonts\` | ship `OFL.txt` beside the fonts; never sell the fonts alone; the four renamed cuts (`install_fonts.py:3-9`, `map/ui` line 54) are an OFL "Modified Version", so the entry says so and keeps the copyright "2015 The Rubik Project Authors"; upstream declares no Reserved Font Name, so the rewritten name tables are allowed | hand: `fonts/OFL.txt` already in the repo (`map/ui` line 7) |
| skia-python + Skia | BSD-3 + BSD-3 | installer (pip) | two notices (Kota Yamaguchi; Google) | generated + hand for the bundled Skia (`research/legal` round 3) |
| pywin32 | BSD-3-style (Mark Hammond) | installer (pip) | retain notice | generated |
| PortAudio (via sounddevice) | MIT-style | installer (pip) | notice | generated (sounddevice) + hand (PortAudio) |
| Pillow, numpy, httpx and every other pinned wheel | as declared | installer (pip) | notice | generated |
| PyAV `av` + bundled FFmpeg | see 13.4 | Recording pack only, LGPL build | LGPL notice + FFmpeg's own licence file + list of bundled libraries | pack generator (13.4) |
| NVIDIA cuBLAS / cuDNN wheels | NVIDIA SDK EULA / cuDNN SLA | never in the installer; GPU pack, user-triggered pip | EULA URL shown before the download; EULA text inside the pack folder | pack generator (13.4) |
| Ollama | MIT | no (user installs) | notice | hand (`research/legal` round 3) |
| Llama 3.1 (Ollama fallback or Groq) | Llama 3.1 Community License | no | licence copy + "Built with Llama" while any Llama is a recommended or default model (13.5) | hand (`research/legal` round 2) |
| Gemma 3 (via Ollama) | Gemma Terms of Use | no | one Notice line + link only while Gemma 3 is recommended (13.5) | hand (`research/legal` round 2) |
| Gemini API, Groq API | provider terms | n/a (BYOK, D10) | not a notice item; the links live in the consent cards (D11) and the policy (13.6) | none |

The whole file is UTF-8, licence bodies unwrapped, and starts with a two-line header: the DeskIT version (from `VERSION`, chapter 11) and the build date, so a reader can match it to a release.

## 13.4 PyAV / FFmpeg and NVIDIA handling

**Today.** `capture.py` imports `av` inside functions for mp4 encode through libx264, AAC audio and DirectShow camera access (`capture.py:1755-1779`, `2407-2433`, `2559-2582`; `map/capture` line 172). The PyPI wheel bundles its own FFmpeg DLLs, and the observed `av.libs` folder holds `libx264-165` and `libx265` (`map/capture` line 172 and risk 9). x264 requires an FFmpeg built with the GPL flag, so that build is GPL and an installer that ships the wheel ships a GPL bundle (`research/legal` round 2, pyav-ffmpeg). A second, quieter problem: faster-whisper imports `av` at module level, so removing the wheel from the base breaks dictation itself, not only recording (D24).

**Rule (D24): the core installer ships no GPL FFmpeg.** Two lines of work, both in phase 0:

| Line | What phase 0 does | Outcome A (LGPL wheel exists) | Outcome B (it does not) |
|---|---|---|---|
| Base dictation | Check whether `JScheumann/pyav-ffmpeg-lgpl` (`research/legal` sources) publishes a cp311 win_amd64 `av` wheel; download it, open its bundled licence file and DLL list, confirm no `libx264`, `libx265` or `libvmaf`, record the SHA-256. | Pin that wheel in the base wheelhouse with `--require-hashes` (chapter 10); its LGPL notice goes into the generated NOTICES. | Vendor faster-whisper (MIT) under `app\vendor\faster_whisper\` with the `av` import made lazy, and feed 16 kHz PCM from PortAudio as numpy arrays so no decoder is needed for dictation (`research/legal` recommendation). The base then has no `av` at all. |
| Recording + camera | Put every `import av` path in `capture.py` behind a `packs.available("recording")` check (chapter 6). | Recording pack = the same LGPL wheel and nothing else. | Recording pack = the LGPL wheel if one appears later, else the standard PyPI wheel **installed by the user's own pip** from PyPI, with the GPL FFmpeg licence shown on the pack card before install; DeskIT never redistributes it. |

Either way the Recording pack card (chapter 6) shows the pack name, its size, the licence of what it pulls and a link to the pack's NOTICES. The `[capture]` defaults (`audio = "off"`, `always_save = false`, D6) do not change; what changes is that the clip encoder and the camera list say "install the Recording pack" instead of failing on `import av`.

**NVIDIA.** The CUDA EULA allows redistribution only "incorporated in object code format into software applications" that have "material additional functionality", and cuDNN has its own SLA with a similar clause (`research/legal` round 4). DeskIT could arguably qualify, but the clean path costs nothing: the wheels never sit inside the installer (D24, chapter 6). The GPU pack card runs pip `--target DATA_DIR\packs\gpu` with pinned `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` versions and hashes (`packs\gpu.lock`, appendix A) and shows, before the download starts, the sentence "These libraries are downloaded from PyPI under NVIDIA's licence" with the EULA URL; the user's click is the acceptance and the download is the user's own, from PyPI, not a redistribution by the owner. The EULA text that the wheel carries in its METADATA is copied into `packs\gpu\THIRD-PARTY-NOTICES.txt` after install. Had the owner chosen AGPL (rejected in 13.1) this separation would be mandatory rather than merely clean, because of the EULA's open-source clause (`research/legal` round 4).

## 13.5 Gemma / Llama attribution rules

DeskIT never distributes model weights: Ollama pulls them on the user's PC and Groq hosts them (`research/legal` round 2 for Gemma, round 3 for Ollama). The obligations are therefore about *recommendation and display*, not redistribution.

**Today's model ids in `config.toml`**, which the `defaults.toml` scrub (D2, D6) must revisit:

| Key | Value today | Licence consequence |
|---|---|---|
| `[translate] ollama_model` | `llama3.1:8b` (`config.toml:319`) | Llama 3.1 Community License applies while this is the shipped fallback |
| `[lookup] model` | `gemma3:12b` (`config.toml:472`) | Gemma Terms of Use apply while Gemma 3 is recommended |
| `[visual_qa] ollama_model` | `gemma3:12b` (`config.toml:610`) | same |
| `[visual_qa] groq_model` | `qwen/qwen3.6-27b` (`config.toml:619`) | Qwen licence to check in phase 0 (not covered by the research) |
| `[polish] groq_model` | `openai/gpt-oss-120b` (`config.toml:1513`) | reported Apache-2.0 on its model card; confirm in phase 0 (not covered by the research) |

**Rules.**

1. **Llama.** The Llama 3.1 licence requires anyone who distributes or makes available "a product or service that contains any of them" to include a copy of the licence and to prominently display "Built with Llama" on the website, UI or docs (`research/legal` round 2). Reached only through Ollama or Groq the reading is a judgement call; D24 takes the conservative one: while any `defaults.toml` value or any tier table (chapter 6) names a Llama model, the About tab shows "Built with Llama" under the version line, the guide's Models chapter repeats it, and NOTICES carries the licence copy. Switching every default off Llama removes all three at once; a test (below) ties them together.
2. **Gemma 3.** The Gemma Terms require distributors to pass on the use restrictions and the Notice line "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms" (`research/legal` round 2). DeskIT is not a distributor, but the guide recommends the model, so the Notice line plus link appears in NOTICES and in the Ollama tier table for as long as a `gemma3:*` id is a default. D24 prefers **Gemma 4 (Apache-2.0)** as the recommended local model so the question disappears; phase 0 measures Gemma 4 against the `gemma3:12b` numbers recorded in `config.toml:442-472` before swapping.
3. **Any other id** (Qwen, gpt-oss, future ones): the phase-0 model measurement (chapter 6) records the licence in the tier table; a model with a non-permissive licence is not made a default without an entry in this section.
4. **Ollama itself** is MIT; the "install Ollama" card (chapter 6) links Ollama's own installer and adds nothing beyond the notice.
5. **ivrit-ai** is Apache-2.0 with attribution: the download step (chapter 6) and About name the model and link its card; the guide's Models chapter cites the ivrit.ai paper as a courtesy (`research/legal` round 2).

## 13.6 Privacy policy outline (D25)

One page, Hebrew and English side by side (Hebrew first for the Israeli audience, English as the canonical text for store reviewers), published on GitHub Pages at `docs/privacy.md` in the repo, versioned (a date and a `policy_version` string at the top). It is linked from the wizard's first screen, the consent cards (chapter 9), the Store and Play listings (chapters 10, 12), the account sign-up card and the guide. It is written to satisfy Israel PPL s.11, which requires the notice at collection to state whether providing the data is legally required, the purpose, the recipients and their uses, the consequences of refusing, the controller's name and contact, and the right to access and rectify (`research/keys-privacy` DLA Piper; `research/legal` round 3). The facts each section must state are fixed here so the text can be drafted and later lawyer-checked without re-deriving them.

| # | Section | Facts it must state |
|---|---|---|
| 1 | Who | Controller: Yoav Shimron, private individual, Israel; one contact e-mail (the same one as `TRADEMARK.md` and `SECURITY.md`); no company, no DPO (13.8). |
| 2 | Local by default | Everything personal lives in `%LOCALAPPDATA%\DeskIT` (D1): audio rings (`audio\recent`, `audio\pending`, `corpus`), `transcripts.log`, `vocab.json`, `review.json`, `problems.json` and attachments, `lookup_cache.json`, `logs\`, `models\`, `secrets\`; pictures and clips in the Pictures and Videos folders. Retention defaults from chapter 4 (`vocab.keep_audio = 20`, `[history] keep_days = 30`, `[review] keep_audio = 3`, D6). Nothing leaves the PC until a feature is switched on through a consent card (D7). How to delete: Settings > Your data, per store and "Delete everything on this PC" (D9); the uninstaller's "Remove my data too?" question. |
| 3 | Bring-your-own-key cloud | Off by default (D6). Which data goes where, per kind (D7): cloud text = the dictated text plus the learned word pairs present in it, to `api.groq.com` or `generativelanguage.googleapis.com`; cloud audio = the recording, to the same hosts; cloud screenshots = the picked region, to the same hosts. Always under the user's own account and key; the user is the provider's customer and DeskIT is their client software (`research/keys-privacy` Groq s3.2; D10). The key is stored in Windows Credential Manager and sent only to that provider (D3, D12). Verbatim provider facts (D11): Gemini unpaid tier: content is used "to provide, improve, and develop Google products and services", "human reviewers may read, annotate, and process your API input and output", "Do not submit sensitive, confidential, or personal information to the Unpaid Services", free tier not permitted for API clients in the EEA, UK or Switzerland, 18+ (`research/keys-privacy` Gemini terms 2026-04-28). Groq: "not permitted to use Inputs or Outputs for training", no retention by default, temporary logs up to 30 days for reliability or abuse unless Zero Data Retention is enabled, 18+ (`research/keys-privacy` Groq your-data page and Services Agreement 2026-06-22). Links to both providers' terms. That the user, as the provider's customer, is the one who must hold any consents for what they dictate (Groq s6.2). |
| 4 | Optional account | Off by default; anonymous by default (D17, chapter 8). Data collected: Supabase user id, app version, OS build, hardware tier, the report text the user typed, only the attachments the user ticked (log excerpt, redacted, previewed before Send; audio or transcript only if ticked), timestamps, and the IP address as Supabase sees it. Purpose: replying to problem reports and, later, syncing settings. Voluntary: no legal duty to provide any of it. Consequence of refusal: no reports and no sync; dictation is unaffected. Recipients: Supabase Inc. as processor, project region Frankfurt (EU); **Anthropic PBC when the developer processes reports with AI tools under his own account** (D25). Retention: 12 months, then deleted; "Delete my account" in the app runs the `delete_me()` RPC immediately (chapter 8). Rights: access, rectification and deletion through the app and by e-mail. Breach: the owner notifies the PPA where the law requires and e-mails affected users who left an e-mail (13.8). Key-shaped strings are rejected by the database schema (D12 lock 3). |
| 5 | Phone companion | Audio travels between the phone and the PC over the user's own network (pairing over a local TLS certificate the PC generates; optionally Tailscale), never through any server of the owner (chapter 12); the phone token is stored under DPAPI (D3). |
| 6 | Screenshots, clips, camera | Local files only, in the Pictures and Videos folders; nothing is uploaded unless the cloud-screenshots consent is on or the user ticks an attachment in a report. |
| 7 | Update check | Off until asked once (D6); when on, one GET per week to `api.github.com` for `latest.json` with no identifier, no user agent beyond the default, no telemetry (chapter 11). |
| 8 | Every connection listed | The full host list is `NETWORK.md` (chapter 5); every outbound request is shown in Dashboard > Network and mirrored to `logs\network.log`; the Offline switch refuses every host but loopback (D12). |
| 9 | Security | Keys in Credential Manager, machine secrets under DPAPI (D3); TLS to every host; row-level security on every table (chapter 8); log redactor (D8); `SECURITY.md` for reporting. |
| 10 | Age | 18+ for every cloud feature, because both providers require it (D11); local dictation has no age gate. |
| 11 | Changes and contact | Version and date of the policy; changes announced in the release notes; the consent cards carry a `text_version` (D7) and re-ask when the relevant section changes; contact e-mail. |

Language rules: plain Hebrew in the Hebrew column (chapter 9's copy rule), no "we" (a single named person), no marketing sentences, and no claim that cannot be checked against `NETWORK.md`, the schema or the code (D12 rules out "we promise" wording).

## 13.7 Terms of service page

A free app under Apache-2.0 needs no EULA: the licence already disclaims warranty and liability, and an installer click-through would only add friction (`research/legal` recommendation; D25). What does need terms is the **account service** (chapter 8), because there the owner operates something for the user. One page, `docs/terms.md` next to the policy, shown once inside the account sign-up card with a single "I agree" checkbox, and recorded in `consent.json` as `{kind: "account", text_version, when, app_version}` (D7). Never shown at install and never shown to a user who stays local.

Contents, in order:

| Section | Must say |
|---|---|
| What the service is | Problem reports and, later, settings sync, run by Yoav Shimron on Supabase; free; may be paused or ended with notice in the release notes, in which case the app keeps working locally. |
| Acceptable use | No abuse of the report channel (spam, other people's data, content that is illegal in Israel); the owner may delete reports and close accounts that break this. |
| Your data | Points to the privacy policy (13.6) as the binding description; account deletion is immediate and self-service (`delete_me()`, chapter 8); the owner does not sell or share data beyond the recipients named in the policy. |
| Cloud features | Bring-your-own-key: the user's contract for Groq or Google is with that provider; DeskIT is not a party; 18+ for those features (D10, D11). |
| No warranty, limitation | The Apache-2.0 disclaimer restated in one sentence for the service; liability limited to what Israeli law allows for a free service. |
| Law and venue | Israeli law; courts of Israel (the owner's district). |
| Changes | New `text_version` re-asks the checkbox on the next account use; continued use after refusal is not possible for the account, but the app itself keeps running. |
| Contact | Same e-mail. |

The Store and Play listings link the same two pages; no separate store-specific terms are written (chapters 10 and 12).

## 13.8 Israeli PPL Amendment 13 checklist and the 2017 regulations documents

Amendment 13 to the Protection of Privacy Law came into force on 2025-08-14 (`research/legal` round 1, LoC). For a solo developer whose only database is the optional Supabase accounts-and-reports store (chapter 8), the thresholds fall as follows (`research/keys-privacy` DLA Piper; `research/legal` round 3):

| Duty | Threshold | DeskIT | Result |
|---|---|---|---|
| Database registration | >10,000 subjects **and** main purpose is providing data to others (data broker), or a public body | neither | not required |
| Notification to the PPA | especially sensitive data on >100,000 subjects | anonymous accounts, no sensitive columns | not required |
| Data protection officer | public bodies, banks/insurers/credit raters, brokers >10,000, large-scale systematic monitoring or large-scale sensitive data | none apply | not required |
| s.11 notice at collection | every collection | the privacy policy of 13.6, linked from the sign-up card before the first upload | **required, delivered by 13.6** |
| Purpose limitation, access and rectification, deletion on request | always | Your data page, `delete_me()`, contact e-mail | required, delivered by chapters 4 and 8 |
| Breach reporting | "Serious Information Security Incident" (severity depends on the database category) | see incident log and template below | required when it happens |
| Administrative fines and statutory damages | PPA may fine; small businesses capped at 140,000 ILS per year (`research/keys-privacy` natlawreview) | the reason the documents below are written now, not later | — |

**The 2017 Data Security Regulations.** Four tiers: "database managed by an individual", basic, intermediate, high (`research/legal` round 4, IAPP). The individual-managed tier fits an individual or one-person company with at most three authorised users, under 10,000 subjects and no sensitive data as the main purpose (`research/keys-privacy` gov.il/IAPP). DeskIT stays in it by design: anonymous accounts by default, one authorised user (the owner), no audio or transcript column unless the user ticks the attachment (D25, chapter 8). Two things could push it to "basic": problem reports that routinely carry transcripts (hence attachments are off by default and previewed), or e-mail plus IP for more than 10,000 users (hence anonymous accounts). Even "basic" adds periodic review and a fuller procedure, never registration (`research/legal` round 4). The gov.il text was not readable during research and the per-tier duty list is an acknowledged uncertainty; the documents below cover the union of what both tiers are described as needing, which costs an afternoon.

Documents the owner keeps in `dev/legal/` (private, excluded from the build manifest, chapter 7 and appendix A):

| Document | One page each; contents |
|---|---|
| `database-definition.md` | Name and purpose of the database (problem reports and settings sync for DeskIT); data types held (the column list of chapter 8, verbatim); categories of subjects (app users who opted in); expected count; sensitive data: none by design, attachments possible only when ticked; access holders: Yoav Shimron only; processor: Supabase Inc., region Frankfurt; secondary processor: Anthropic PBC for AI-assisted report handling; retention: 12 months, tombstones; transfer abroad: EU region, under the processor's terms. |
| `security-procedure.md` | Who may log in to the Supabase console (one account, 2FA on); the publishable key is the only key in the app, the service-role key stays in the owner's password manager and never in the repo; RLS is the access control; backups (chapter 8) and where they live; the laptop that opens the console runs full-disk encryption; the `dev/inbox.py` workflow reads only consented columns (chapter 7). |
| `access-list.md` | A table with one row: Yoav Shimron, owner, full access, date granted. Updated if that ever changes. |
| `incident-log.md` | Empty table with columns: date, what happened, data affected, subjects affected, action taken, reported to PPA (yes/no, date), users notified (yes/no, date). Every entry, however small, goes here. |
| `breach-template.md` | Two e-mail drafts, Hebrew and English: one to the PPA with the fields the regulations ask for (what, when, which data, how many subjects, mitigation), one to affected users (plain, what to do). |
| `policy-changelog.md` | One line per `policy_version` and `text_version` change, with the date and what changed, so the re-ask logic of D7 has a written trail. |

None of these needs a lawyer to exist. The one-hour lawyer review named in D25 should look at the privacy policy, the terms and the tier reasoning above in one sitting; it is the only foreseeable paid legal item and it can wait until after the first release (`research/legal` hand-work item 7).

## 13.9 Win+Shift+S

Today the owner's `config.toml:767` binds `capture_hotkey = "win+shift+s"`, the chord Windows reserves for Screen Snip; `hotkey.py:319-329` and `809-822` make a Win-modifier chord the one chord the hook swallows, so the Snipping Tool, OneNote's clip and ShareX/Greenshot/Snagit defaults go silent while DeskIT runs, and if the hook dies both fire (`map/capture` lines 12, 31, 108, 190). The code default is `ctrl+f11` (`config.py:548`).

The legal position: Windows handles the chord through the `ms-screenclip:` protocol; no Microsoft policy forbids a desktop app from being chosen as that protocol's default handler, which is the route Flameshot documents (`research/legal` round 2). A global hook that swallows the chord is lawful but user-hostile, and it becomes a Store rejection risk under the "must not interfere with other software" rule if DeskIT is ever submitted (`research/legal` recommendation; chapter 10). D25 therefore fixes three things:

1. **Never a default.** `defaults.toml` ships `capture_hotkey = "ctrl+f11"` (D6); the owner's value moves to his `settings.toml` through `--migrate` (D4).
2. **An opt-in toggle** on Settings > Capture (chapter 9): "Replace the Windows screen-snip shortcut while DeskIT runs", off, with the one-line consequence "Windows' own Snipping Tool and other tools bound to Win+Shift+S will not answer while DeskIT is running". Ticking it writes `capture_hotkey = "win+shift+s"`; unticking restores `ctrl+f11`. `hotkey._takes_the_key` already behaves correctly once the value is set (`map/capture` line 209).
3. **The proper route as a second toggle**: "Make DeskIT the handler for Windows screen clips", which registers DeskIT for the `ms-screenclip` protocol under `HKCU` (per-user, no admin, chapter 10) and then opens Settings > Apps > Default apps so Windows itself asks the user to confirm; the hook is not needed on that path, and other tools keep the chord unless the user changes the default. Unregistration is part of "Delete everything on this PC" (D9) and of the uninstaller.

The guide's Capture chapter (chapter 14) explains the difference in three sentences and mentions the registry `DisabledHotkeys` route only as "what power users do", never as something DeskIT does.

## 13.10 Files to add or change

| File | Add / change | What |
|---|---|---|
| `LICENSE` | add | Apache-2.0 text, copyright "Yoav Shimron" (13.1); FSL text instead if the owner decides so. |
| `TRADEMARK.md` | add | 13.2. |
| `THIRD-PARTY-NOTICES.txt` | add, generated at build | 13.3; not committed, produced by the release workflow (chapter 10). |
| `dev/notices-extra.txt` | add | The hand-written half of 13.3 (Python, Tcl/Tk, Whisper, ivrit-ai, Rubik, Skia, PortAudio, Ollama, Llama, Gemma). |
| `fonts/OFL.txt` | keep | Already present (`map/ui` line 7); the NOTICES entry points to it. |
| `docs/privacy.md`, `docs/terms.md` | add | 13.6, 13.7; GitHub Pages source; `policy_version` header. |
| `docs/NETWORK.md` | add (chapter 5) | Referenced by the policy section 8. |
| `SECURITY.md` | add (chapter 14) | Referenced by policy section 9. |
| `dev/legal/*.md` | add | The six documents of 13.8; excluded from `git archive` and the manifest (chapter 3). |
| `app/defaults.toml` | change | Model ids per 13.5 (Gemma 4 preferred, Llama fallback decision), `capture_hotkey = "ctrl+f11"`. |
| `capture.py` | change | `import av` sites behind the Recording pack check (13.4); the two toggles of 13.9 in the Capture settings section. |
| `requirements` / wheelhouse lock | change | LGPL `av` wheel pinned, or `av` removed and faster-whisper vendored (13.4). |
| `packs/gpu.lock`, `packs/recording.lock` | add (chapter 6) | Pinned versions and hashes; licence URL fields read by the pack cards. |
| About tab (`dashboard.py`) | change | Links to LICENSE, NOTICES, privacy, terms; "Built with Llama" line conditional on the defaults (13.5). |
| Sign-up card (chapter 9) | change | Terms checkbox and `consent.json` record (13.7); privacy link. |
| Release workflow (chapter 10) | change | `pip-licenses` step, concatenation with `dev/notices-extra.txt`, NOTICES included in the installer and in the manifest. |

## Acceptance

- The repo root holds `LICENSE` (Apache-2.0 or FSL per the owner's phase-0 call) and `TRADEMARK.md`; About links both.
- The installer contains `THIRD-PARTY-NOTICES.txt` with an entry for every wheel in the wheelhouse plus the hand entries of 13.3, and `fonts\OFL.txt` beside the four Rubik cuts.
- No file named `libx264*`, `libx265*` or `libvmaf*` exists anywhere in the installer or in `APP_DIR` after a clean install; no `nvidia_*` package exists in the base wheelhouse.
- Dictation works on a clean VM with no Recording pack and no GPU pack installed.
- The GPU pack card shows the NVIDIA EULA link before any download; the Recording pack card shows the licence of what it will install.
- `docs/privacy.md` and `docs/terms.md` are published on GitHub Pages, each with a `policy_version`, and the eleven policy sections of 13.6 each state the facts listed for them.
- The account sign-up card cannot proceed without the terms checkbox; `consent.json` records the account consent with `text_version`.
- `dev/legal/` holds the six documents of 13.8 with real content, and is absent from `git archive` output and from `MANIFEST.sha256`.
- `defaults.toml` has `capture_hotkey = "ctrl+f11"`; the two capture toggles of 13.9 exist and are off on a fresh install.
- "Built with Llama" appears in About if and only if a Llama id is present in `defaults.toml` or the tier tables.

## Tests to add

| Test | Asserts |
|---|---|
| `test_legal_license_files_present` | `LICENSE`, `TRADEMARK.md` exist at the repo root and `LICENSE` contains the chosen licence's title line and the owner's name. |
| `test_notices_covers_every_wheel` | Parse the build's `THIRD-PARTY-NOTICES.txt`; every distribution name in the wheelhouse lock appears as an entry; every hand entry named in 13.3 appears. |
| `test_notices_rubik_ofl` | The NOTICES Rubik entry names OFL 1.1 and "Modified Version"; `fonts/OFL.txt` is in the manifest. |
| `test_no_gpl_ffmpeg_in_base` | Walk the built `APP_DIR` and the base wheelhouse: no file matching `libx264*`, `libx265*`, `libvmaf*`; if an `av` wheel is present, its bundled licence file says LGPL. |
| `test_no_nvidia_in_base` | The base wheelhouse lock contains no `nvidia-*` distribution; `packs/gpu.lock` carries the EULA URL field. |
| `test_dictation_without_av` | With `av` made unimportable in a subprocess, the transcriber module imports and transcribes a fixture WAV from a numpy array (Outcome B path) or the LGPL wheel is present (Outcome A). |
| `test_recording_requires_pack` | With the Recording pack absent, `capture` reports "install the Recording pack" for clip encode and camera listing and never raises `ImportError`. |
| `test_built_with_llama_conditional` | Render the About text with a `defaults.toml` fixture containing a `llama*` id: "Built with Llama" present; with none: absent; and NOTICES generation includes or omits the Llama licence in step. |
| `test_gemma_notice_conditional` | Same pattern for `gemma3:*` ids and the Gemma Notice line. |
| `test_policy_pages_have_version` | `docs/privacy.md` and `docs/terms.md` start with a `policy_version` and a date, both columns (Hebrew, English) non-empty, and every section title of 13.6 / 13.7 is present. |
| `test_policy_hosts_match_network_md` | Every host named in `docs/privacy.md` is in `ALLOWED_HOSTS` (chapter 5) and vice versa. |
| `test_terms_gate_on_signup` | The sign-up flow refuses to create a session until the account consent is recorded with the current `text_version`; a bumped `text_version` re-asks. |
| `test_dev_legal_excluded_from_build` | `git archive` output and `MANIFEST.sha256` contain no path under `dev/legal/`. |
| `test_capture_hotkey_default` | `config.load()` with no `settings.toml` yields `capture_hotkey == "ctrl+f11"` and both 13.9 toggles false. |
| `test_screenclip_toggle_roundtrip` | Ticking the hook toggle writes `win+shift+s` to `settings.toml`; unticking restores `ctrl+f11`; the protocol toggle writes and removes the `HKCU` `ms-screenclip` keys (run on the hidden desktop, memory rule). |

## Open points

1. **Licence choice is the owner's** (D23 "Revisit: owner's call in phase 0"). This chapter is written for Apache-2.0; if FSL wins, chapter 10's SignPath path and chapter 12's IzzyOnDroid path are struck and the certificate cost lands in chapter 16.
2. **Today's default Groq repair model is not a Llama.** `config.toml:1513` sets `[polish] groq_model = "openai/gpt-oss-120b"`; the only Llama is the `[translate]` Ollama fallback `llama3.1:8b` (`config.toml:319`). D24's phrase "while a Llama is the default Groq repair model" should read "while any Llama id is a shipped default"; the rule in 13.5 is written that way. The gpt-oss and Qwen licences were not in the research and need a phase-0 check.
3. **LGPL `av` wheel for cp311**: existence, DLL list and hash unverified (D24 "Revisit"); 13.4 carries both outcomes.
4. **Gov.il regulations text** returned 403 during research; the individual-managed versus basic tier duty list is reconstructed from DLA Piper and IAPP. The lawyer hour should confirm it.
5. **Gemini EEA clause and BYOK**: the "Paid Services only" rule targets API Clients; whether it binds a BYOK app whose user holds the account is a judgement call (`research/legal` uncertainties). The policy and the consent card warn regardless (D11).
6. **Anthropic as recipient**: D25 names Anthropic PBC as a recipient when the owner processes reports with AI tools. The policy must also say which fields reach that tool (the consented columns only, chapter 7) and that no attachment is sent there unless the user ticked it; chapter 7's `dev/inbox.py` contract is the place to enforce it, and this chapter only states it.
7. **Hebrew legal terminology** for the policy (controller = "בעל מאגר", processor = "מחזיק") should follow the PPA's own wording; drafting the Hebrew column is owner or lawyer work, not AI-coder work.


---

# 14. User guide, FAQ and support

Implements **D26** (guide, support, first-user channels, positioning). It reuses chapter 5's §5.10 as the guide's privacy chapter, chapter 9's screen names and copy, chapter 4's retention sentence (§4.9) and export format, chapter 6's tier copy, chapter 10's installer facts, chapter 11's update mechanics, chapter 12's pairing steps and phone privacy sentences, chapter 13's policy and licence texts, and chapter 7's report v2 spec. It does not restate any of those; it says what the guide must *teach*, in which order, with which screenshots, and how the guide, the FAQ and the support paths are produced and kept in step with the code. Everything in this chapter is written in English for the coder and the owner; the shipped guide is Hebrew first with an English mirror (D26).

## 14.1 Where the guide lives and how it is built

**Host.** GitHub Pages of the public repository (D26; `arch-B §12`), the same site that carries the privacy policy and the terms (D25, chapter 13), so a single URL prefix appears in the app: the Welcome step's "How to check this yourself" link (chapter 9 §9.2), the About screen's links (chapter 9 screen 14), the Update card's "Release notes" (chapter 11), the Store and Play listings, and the Supabase Site URL (chapter 8 §8.11 step 5). Vibe uses exactly this pattern (`thewh1teagle.github.io/vibe`, `research/competitors` "What the owner must do", optional landing page).

**Source tree.** `docs\` in the repository, excluded from the build manifest (it is not part of `app\`, chapter 3; appendix A lists it under new files):

| path | content |
|---|---|
| `docs\he\` | the ten Hebrew chapters, one Markdown file each, numbered `01-install.md` … `10-faq.md`, plus `settings.md` (generated, §14.6) and `quickstart.md` |
| `docs\en\` | the English mirror, same file names; a chapter missing in `en\` falls back to a one-line "not translated yet" stub with a link to the Hebrew page, never to a 404 |
| `docs\img\` | screenshots, named `<chapter>-<screen>-<he\|en>.png`; every screenshot named in §14.2 is a file that must exist (test, §"Tests to add") |
| `docs\privacy.md`, `docs\terms.md` | chapter 13's texts (Hebrew and English on one page each, as D25 asks) |
| `docs\_config.yml` | the Pages site configuration: the site title, the two language trees, the theme; no build step other than Pages' own Jekyll |
| `docs\strings\` | the string tables exported from the app's modules (chapter 9 §9.1: one string table per module) so the guide quotes consent-card and key-field wording *verbatim* rather than retyping it |

**Language rule.** Hebrew pages are the primary text; the English mirror is written second and may lag by one release (chapter 11 §11.11 already applies the same rule to release notes). Chapter titles, screen names and settings keys stay in English inside the Hebrew text because the app's chrome is English (chapter 9 §9.1) — the guide names what the user actually sees on screen: "Settings > Privacy", "YOUR CLOUD KEYS", "Dashboard > Network", "Home", "Keys" (the *hotkeys* place; chapter 9 open point 2 fixes these two names and this chapter uses them the same way).

**Versioning.** The guide is published from `main` at each release tag; the page footer prints the `VERSION` it documents (chapter 11) and the Settings chapter is regenerated at the same time (§14.6). Screenshots are retaken only when the screen changed (the screenshot list in §14.2 names the chapter that owns each screen, so a change there is the trigger).

**Reading level.** The audience (`research/competitors` recommendation 8) is Israeli office workers, students, lawyers and doctors writing Hebrew notes, RSI/accessibility users and Hebrew-speaking developers, "most on laptops without a discrete GPU". Every chapter therefore opens with the two-sentence version and puts the detail after a heading, and every instruction names a screen, a button and a folder path rather than a concept. The Quick Start (§14.3) is the whole guide for the reader who never scrolls.

## 14.2 Table of contents, one paragraph per chapter

The ten chapters of D26, in order, each with what it must teach and the screenshots it needs.

**1. Install.** Teaches: the three ways in, in the order the reader should try them — the Microsoft Store button once phase 3 is live (no warning at all, D20), the `winget install <publisher>.DeskIT` one-liner for people who have winget (skips the SmartScreen download dialog, D20), and the GitHub Release `DeskIT-Setup-x.y.z.exe` with its SHA-256 line and VirusTotal link (chapter 10). Then the SmartScreen sequence for the GitHub route with the exact wording the user sees ("Windows protected your PC" → "More info" → "Run anyway", D20) and the one-sentence reason (the installer is not signed by a paid certificate yet; the code is open and the build is attested, chapter 10). The Smart App Control note: on a PC where Smart App Control is on, the GitHub installer is blocked outright and the Store is the way (`research/signing`, D20). Per-user install, no admin prompt, where it lands (`%LOCALAPPDATA%\Programs\DeskIT`), Start-menu shortcut, and that uninstall is Settings > Apps like any program. Screenshots: `01-smartscreen-more-info`, `01-smartscreen-run-anyway`, `01-installer-language`, `01-installer-finish`, `01-store-page` (phase 3).

**2. First run.** Teaches: the seven wizard steps in chapter 9 §9.2, one paragraph each, marking which steps carry a real decision (microphone only when more than one; download now or later; GPU pack; the three extras) and that everything else is Next. The microphone privacy switch (`ms-settings:privacy-microphone`, chapter 9 step 1) as the reason a silent meter usually has. The model download: 1.62 GB from huggingface.co into `%LOCALAPPDATA%\DeskIT\models`, resumable, verified, "Later" is allowed (D13, chapter 6 §6.3). GPU vs CPU expectations in the tier copy chapter 6 fixes after phase 0 ("about as long as you spoke — we measured N s" until then, D14 revisit). The keys step is *hotkeys*, not API keys; API keys come in chapter 5. Screenshots: `02-welcome`, `02-microphone`, `02-hardware-gpu`, `02-hardware-cpu`, `02-download-progress`, `02-say-one-sentence`, `02-keys`, `02-extras`, `02-done`.

**3. Dictating.** Teaches: hold to dictate, latch, the English key, the correct key, the dot's states (listening, transcribing…, model missing) as chapter 6 and 9 draw them; the hint and the shelf; that the transcript replaces the clipboard and that Win+V (Windows clipboard history) keeps earlier transcripts — which also means Windows may hold them after DeskIT has forgotten them (`map/core` rec 13). Elevated windows: DeskIT cannot paste into a window running as administrator (UIPI); the transcript is on the clipboard, press Ctrl+V there (`README.md:4146-4150`; `map/packaging` rec 16 — the installer never runs the app elevated, so the guide must say this). Correcting a word and how it becomes a learned pair (the Corrections place). Screenshots: `03-dot-states` (three), `03-hint`, `03-shelf`, `03-corrections`.

**4. Privacy and how to check it yourself.** Chapter 5 §5.10 verbatim, plus the framing in §14.4 below. Screenshots: `04-credential-manager`, `04-network-tab-loopback`, `04-offline-refused-row`, `04-migration-columns`, `04-verify-output`, `04-firewall-log`.

**5. Cloud features.** Teaches: what each feature sends, from chapter 5 §5.1's feature-to-kind table (D26 names this list explicitly); getting a free Groq key at console.groq.com (recommended first: one key unlocks repair, punctuation, lookup and, on the CPU tier, cloud transcription — D10) and a free Gemini key at aistudio.google.com (only for translate and ask-the-screen, D10); the two provider notices quoted verbatim from chapter 9 screen 2 (D11), including the EEA/UK/Switzerland and 18+ sentences, stated the same way the app states them because the app does not geolocate (chapter 5 open point 5); the daily quota meter and what "estimate" means; rolling sends stretches before the key is released (D7); learned word pairs travel filtered to the text (D7). The storage sentence next to the key field, quoted from `docs\strings\` (chapter 9 screen 3). Screenshots: `05-groq-console-create-key`, `05-aistudio-create-key`, `05-your-cloud-keys`, `05-consent-cloud-text`, `05-quota-meter`.

**6. Phone keyboard.** Teaches: install the APK from the GitHub Release (QR on Settings > Phone), later Play; pairing on home Wi-Fi in chapter 12's step order (QR, the one-time token, the fingerprint the phone pins); the Windows Firewall prompt appears once and must be allowed on Private networks; Tailscale as the optional away-from-home path with the same pairing over the tailnet address (D22, chapter 12 §12.5); Forget this PC / Forget this phone / Rotate; the password-field refusal (`DictationIme.kt:628-655`, `map/phone` rec 7); the phone privacy sentences from chapter 12 §12.10 reused in that order; that cloud passes apply to phone text under the same consent switches (`map/phone` rec 7); Obtainium in one line for power users (chapter 12). Screenshots: `06-settings-phone`, `06-pair-qr`, `06-firewall-prompt`, `06-ime-enable`, `06-ime-paired`.

**7. Screenshots, recordings, camera.** Teaches: the capture key and the picker; where files go (`Pictures\DeskIT`, `Videos\DeskIT`, D1) and how to change it; that ask-the-screen sends a JPEG of the selected region and the question to the provider of the key you chose (chapter 9 screen 2 `cloud_screenshots`); the three-button card when Ollama is absent (chapter 9 screen 12); the Recording pack as an opt-in install with its licence shown (D24, chapter 6 §6.5); that recordings may include computer sound when that switch is on and open the microphone when audio is "mic" (`map/capture` rec 6); the clipboard caveat — every capture lands on the clipboard, and Windows cloud clipboard sync would send it to Microsoft, which is Windows' doing, not DeskIT's (`map/capture` rec 7); the Snipping Tool toggle (chapter 9 screen 13, D25); "the light next to the lens goes off at the shutter" is a real promise (`capture.py:174-179`, `map/capture` rec 13). Screenshots: `07-picker`, `07-ask-card`, `07-ollama-three-buttons`, `07-settings-screen`.

**8. Your data.** Teaches: the one folder (`%LOCALAPPDATA%\DeskIT`) and what each subfolder holds (chapter 3's tree, one line each); the retention sentence from chapter 4 §4.9 verbatim; the Settings > Your data rows and buttons (chapter 9 screen 5) and what each deletes (chapter 4 §4.6); Export everything and the by-hand import on another PC (chapter 4 §4.7); Delete everything on this PC; the uninstaller's "Remove my data too?" question and, for the Store build, that the folder must be deleted by hand (chapter 4 §4.8); the Account block and Delete my account, and which deletion removes the server-side copy of a sent report (chapter 4 open point 4 — the guide states whichever rule chapter 8 settles). Screenshots: `08-your-data`, `08-folder-explorer`, `08-uninstall-question`.

**9. Reporting a problem.** Teaches: the key, the one line and the kind chips, the attachment toggles with their defaults and sizes, that "Send to the developer" is off by default and off means the report stays on this PC, the Preview window showing the exact JSON, the outbox ("will retry" is not an error, D17), replies appearing on the Problems place, Fixed/Reopen (chapter 7 §7.6, chapter 9 screens 7-8). Nothing about branches, Push/Undo, nightly tests or a Saturday routine (`map/owner` rec 14; the README's two conflicting descriptions of the routine must not be inherited, `map/owner` "Docs disagree", chapter 2 open point 2). Screenshots: `09-report-card`, `09-preview`, `09-replies-row`.

**10. FAQ.** §14.5 in full.

**Settings (generated).** §14.6; linked from the sidebar after chapter 10, not numbered, because it is regenerated per release.

## 14.3 Quick Start (ten steps)

The one page a reader who never scrolls needs, in English here, translated into Hebrew by the owner (chapter 16) and mirrored. Each step names the screen exactly as chapter 9 draws it.

1. **Get it.** Store: press "Get". winget: run the one-liner from the Install chapter. GitHub: download `DeskIT-Setup-x.y.z.exe` from the latest release; if Windows says "protected your PC", press "More info", then "Run anyway" (why: chapter 1 of the guide).
2. **Install.** No administrator password is asked. Pick Hebrew or English for the installer, press through. DeskIT starts by itself at the end.
3. **Welcome.** Read the three sentences. Press Next.
4. **Microphone.** Speak; the bar should move. If it does not, press the "Windows microphone privacy" button, allow desktop apps, come back. Press Next.
5. **Hardware and model.** The top line says what DeskIT found in your PC. Press Download (1.62 GB, from huggingface.co, into your DeskIT folder; you can press Later and download from Home another day). If the screen offers "Use the NVIDIA card", turn it on for fast transcription (1.3 GB more).
6. **Say one sentence.** Hold the hotkey shown, say one Hebrew sentence, release. The screen shows what it heard and how long it took. On a PC without an NVIDIA card this is the speed to expect.
7. **Keys.** These are the keyboard keys DeskIT listens to. Keep the defaults unless one clashes with a program you use. Next.
8. **Optional extras.** All three switches are off. Leave them off for now; the guide's chapter 5 explains the first one. Next, Finish.
9. **Dictate.** Click into any text field, hold the hotkey, speak, release. The Hebrew text is pasted where the cursor is. Press the correct key on a misheard word to teach DeskIT the right one.
10. **Check it.** Open Dashboard > Network: during plain dictation the table is empty (or shows only `127.0.0.1`). Nothing left your PC. The guide's chapter 4 shows three more checks you can do in ten minutes.

## 14.4 "Privacy and how to check it yourself" in full

The chapter's body is chapter 5 §5.10 — the six checks numbered 1-6 with their minute counts, what each proves and what it does not, and the closing paragraph on what cannot be verified — copied verbatim into `docs\en\04-privacy.md` and translated into `docs\he\04-privacy.md`. A test compares the English page against the plan's section so the two cannot drift (§"Tests to add"). What this chapter adds around it:

**Opening (three sentences, the same three the Welcome step shows, chapter 9 §9.2).** "Your voice stays on this computer." / "The words you say are kept in one folder you can delete." / "Nothing is sent anywhere until you switch it on." Then one sentence of framing: "Every claim below comes with a way to check it that does not require trusting us."

**The four ten-minute checks are the ones D26 names**, in chapter 5's order: (1) the Credential Manager entry `DeskIT/groq` — with screenshot `04-credential-manager` showing Control Panel > Credential Manager > Windows Credentials > Generic Credentials; (2) Dashboard > Network shows only loopback during plain dictation — screenshot `04-network-tab-loopback`; (3) Offline mode makes cloud features refuse and a refused row appears naming the host — screenshot `04-offline-refused-row`; (4) the published migration `supabase/migrations/0001_init.sql` has no key column and the CHECK constraints are in the same file — screenshot `04-migration-columns` of the footer comment chapter 8 §8.13 item 10 puts there, and a direct link to that line in the repository.

**The two optional checks.** (5) `deskit --verify` (chapter 10; run from the install folder as `python\python.exe -m deskit --verify`, `arch-B §12`) with its expected output "All N files match the manifest" and where the manifest hash is published (the release page and the attestation); (6) the firewall-log recipe: the guide prints the two `netsh advfirewall` lines *as text the reader copies* (enable logging of allowed connections; set the log path), tells them where `pfirewall.log` lands, and how to compare its destination column against `logs\network.log` for the same minutes — and the Wireshark alternative filtered to `pythonw.exe`. The plan holds no command text (house rule); the guide does.

**The wording next to every key field** is quoted here once more, from `docs\strings\`, so the reader has seen it before pasting a key: "This key is stored in Windows Credential Manager on this PC … It is never written to a file, a log or a report, and never sent to the developer — see Dashboard > Network for every request." (chapter 9 screen 3; `arch-B §4` fixes it and D12 says the guide repeats it).

**What we do not claim.** The closing paragraph of §5.10 verbatim: the live Supabase project is the owner's word, only the migration is checkable; the installer is not byte-reproducible, the tree is; a store readable by your account is readable by malware running as you. Plus the chapter-5 open point 5 sentence: DeskIT does not geolocate, so the EEA/UK/Switzerland restriction on the Gemini free tier is the reader's responsibility to observe.

**Link out.** `NETWORK.md` (chapter 5 §5.5, the same allowlist table) and `SECURITY.md` (§14.7) at the end.

## 14.5 FAQ entries

Each entry is a question in the reader's words and an answer of at most six sentences that names a screen or a folder. The technical background for the first three lives in chapter 10 §10.9; the guide carries only the user-facing answer.

| question | answer (what it must say) | source |
|---|---|---|
| Windows says "protected your PC" / Defender flags the installer | Expected for a program not signed with a paid certificate; press More info → Run anyway. Compare the SHA-256 on the release page with the file (Explorer: Properties or the one-liner the guide prints), check the VirusTotal link on the release, and read the build attestation. If Defender quarantines the installer, the release page carries a link to Microsoft's false-positive submission form; report it there and to us. Even signed apps in this category get re-flagged on new releases (Handy #1399, #1891, `research/competitors`). | D20, chapter 10 |
| Smart App Control blocks it | Smart App Control allows only signed or Store apps; use the Store build (phase 3) or turn SAC off, which Windows lets you do once. | `research/signing`, D20 |
| The model download is stuck or failed | Home > Hardware card shows the progress; a download resumes on the next start; if it never finishes, Settings > Speed > "Delete and re-download" removes the partial snapshot (DeskIT never loads a partial one, D13). A managed or filtered network may block huggingface.co; the Network tab shows the refused host. This is the top issue of every comparable app (Buzz #1444/#1450/#1615, Vibe #1479/#1552). | D13, chapter 6 |
| I have no NVIDIA card — does it work? | Yes, on the CPU; transcription takes about as long as you spoke (the phase-0 number replaces this). Two ways to make it faster: a free Groq key with the "cloud transcription" switch under Settings > Privacy (your audio leaves your PC to Groq under your key, and the consent card says so), or an NVIDIA card. AMD and Intel GPUs are planned (phase 5). | D14, chapter 6 |
| The dot says "transcribing…" for a long time | See the previous answer; the CPU-slowness card appears once when a decode passes 10 s and offers the same two options. | chapter 9 screen 15 |
| Do I need Ollama? | No. Ollama is optional; without it the local-LLM menu entries are hidden and ask-the-screen offers three buttons (install Ollama / use my key / turn this key off). If you install it, DeskIT finds it on `127.0.0.1:11434` and suggests a model that fits your card. | D14 |
| "Port busy" or the phone cannot connect | DeskIT uses port 8756 and falls through to the next free port; Settings > Phone shows the one in use and the pairing QR carries it. Re-scan the QR after a port change. Allow DeskIT through Windows Firewall on Private networks (the prompt appears once). | D5, chapter 12 |
| Nothing pastes into this one window | It is running as administrator; Windows blocks pasting from a normal program. The text is on your clipboard: press Ctrl+V. | `README.md:4146-4150` |
| The bar does not move / recordings are silence | Windows Settings > Privacy & security > Microphone > allow desktop apps; then check the device under Settings > General. | `README.md` troubleshooting, chapter 9 step 1 |
| Where are my keys, and can you see them? | Control Panel > Credential Manager > Windows Credentials > `DeskIT/groq`, `DeskIT/gemini`. They go only to api.groq.com / generativelanguage.googleapis.com under your account; guide chapter 4 shows how to verify that yourself. | D3, D12 |
| What leaves my PC when everything is off? | Nothing; not even an update check until you switch it on. The Network tab is empty during plain dictation. | D6, D12 |
| Does the phone app send my voice through the internet? | No; phone → your PC over your own Wi-Fi (or your own Tailscale network), TLS pinned to your PC's certificate; there is no relay. | D22 |
| How do I delete everything? | Settings > Your data > "Delete everything on this PC" (folder, Credential Manager entries, startup entry, hook entries), then "Delete my account" if you ever pressed Send. Or uninstall and tick "Remove my data too?". | D9 |
| Can I move DeskIT to another PC? | Export everything (zip), install on the other PC, copy the folders into the new `%LOCALAPPDATA%\DeskIT` by hand; keys are never in the export, paste them again. | chapter 4 §4.7 |
| Is it free? Is there a paid tier? | Free and open source (Apache-2.0); the only things that can cost money are the providers' paid tiers if you exceed their free limits under your own account. | D10, D23 |
| I found a security problem | `SECURITY.md`: e-mail the address there; 90-day disclosure window. | §14.7 |

## 14.6 The Settings chapter generator

`settings.WORDS` and `SECTION_WORDS` already hold a plain-English sentence for every key and section, and tests enforce completeness (`settings.py:1401`, `:1324`; `tests.py:19325-19338`; `map/ui` rec 13). The guide's Settings chapter is *generated*, never hand-written, so it cannot drift from the file (`map/packaging` rec 12):

- **Script:** `dev/gen_settings_doc.py` (dev-side, not shipped; appendix A). It calls `settings.read()` on `app\defaults.toml` (chapter 3) — never on the owner's `config.toml` — and walks `TABS` / `TAB_SECTIONS` / `groups_for()` per tab exactly as the Settings place draws them (`settings.py:450-660`, `dashboard.py:7186-7190`), so the document's order is the screen's order.
- **Output:** `docs\en\settings.md`: one heading per tab, one sub-heading per section with its `SECTION_WORDS` sentence, one table row per key with the label, the `WORDS` sentence, the shipped default, the allowed choices (from `Friendly.names` where present) and the tier note when chapter 6's tier table overrides the default. Keys that live in `state.json` (positions, devices, port, `setup_done`) do not appear, because they are not settings (D2). DEVELOPER-only sections and `[tests]` do not appear because they are not in `defaults.toml` (D6, D15).
- **Hebrew:** the generator emits the English page; the Hebrew page `docs\he\settings.md` is produced by the same script from a `docs\strings\settings.he.json` map of key → Hebrew sentence that the owner fills (chapter 16); a missing Hebrew sentence falls back to the English one and is listed at the end of the generator's output so the gap is visible.
- **Freshness:** the release workflow (chapter 10) runs the generator and fails the release when the committed `docs\en\settings.md` differs from the generated one (test below). The retention sentence (chapter 4 §4.9) is generated by the same script into `docs\strings\retention.md` and quoted by guide chapter 8.

## 14.7 Support: issue template, `--diagnose`, in-app reports, `SECURITY.md`

**Two doors.** Non-technical users use "Report a problem" (chapter 7, guide chapter 9). Power users and anyone without an account use GitHub Issues. Both are named on the About screen (chapter 9 screen 14) and in the FAQ.

**`deskit --diagnose`.** A new CLI flag beside `--setup`, `--migrate` and `--verify` (`main.py:5887-5902` holds today's parser; `--study/--review/--benchmark` become DEVELOPER-only, D4). It prints to stdout and copies to the clipboard one text block: `version` (from `version.py`), `tier`, `os_build`, `gpu`, and the other `problems.env()` whitelist fields (`problems.py:274`; D15 drops `branch` and `python`), the active backend and model name, whether the model snapshot is complete, the port in use, the pack states, the last 50 lines of `app.log` and the tail of the Inno setup log (chapter 11 §11.6 `/LOG`), all passed through the redactor (chapter 4 §4.5). It never includes `transcripts.log`, `vocab.json`, `review.json`, `notify.json` bodies, `network.log` rows' purposes with their bodies, or any file under `secrets\` (D8, D26). The block starts with a line naming what it contains so the user can read it before pasting.

**GitHub issue template** (`.github/ISSUE_TEMPLATE/bug.yml`, appendix A): fields — what you did / what happened / what you expected; the `--diagnose` block (required, with the sentence "this contains no transcripts and no keys; you can read it first"); how you installed (Store / winget / GitHub); a checkbox "I searched the FAQ". A second template `false-positive.yml` for Defender/SmartScreen reports asking for the detection name, the file name and the VirusTotal link. A `config.yml` that points "questions" to Discussions. This mirrors Vibe's template + `DEBUG.md` pattern, the one comparable OSS app whose author is Israeli (`research/competitors` Vibe README).

**`SECURITY.md`** at the repository root and in `APP_DIR` (D1): the contact e-mail (the same as the privacy policy's, chapter 13), what to report (anything that lets a key, a transcript or audio leave the PC without a consent row; anything that breaks a lock in chapter 5 §5.8), a 90-day coordinated disclosure window (D26), the supported versions line ("the latest release only"), and a pointer to `NETWORK.md`. No bug bounty. The About screen's "Report a security issue" button opens it (chapter 9 screen 14).

**Replies.** In-app reports get replies through `report_replies` (chapter 8) shown on the Problems place (chapter 9 screen 8); issues get replies on GitHub. The owner's Saturday routine reads only consented inbox rows (chapter 7 §7.7) and the policy discloses AI processing under the owner's account (D25, D29-5).

## 14.8 Launch channels and positioning

**Positioning line:** "the Win+H that Hebrew never got" — Windows voice typing does not support Hebrew ("Voice typing isn't available in the current language", Microsoft Q&A 3894380, `research/competitors`); Vibe transcribes files rather than typing into the cursor; Wispr Flow and Superwhisper are cloud and paid (`research/competitors` options table). Under it, three phrases used everywhere the app is described (README, Store, Play, guide landing page): local Hebrew dictation; open source, Apache-2.0; bring your own free key for the cloud extras, and see every request.

**Channels for the first users, all free, in this order** (D26, `research/competitors` rec 8):

| channel | what to post | when |
|---|---|---|
| ivrit.ai | a courtesy note that DeskIT uses `ivrit-ai/whisper-large-v3-turbo-ct2`, with attribution, and a request to be listed as a tool using their models (D28) | before the first public release |
| Vibe discussion #27 | one reply: a Hebrew push-to-talk app exists, link, that it uses the same ivrit.ai models the thread loads by hand | release day |
| Israeli dev Telegram/Facebook groups, Tapuz, Geektime | the positioning line, one screenshot of Hebrew appearing at the cursor, the Store/GitHub link | release week |
| r/Israel, r/hebrew | the same, in English | release week |
| the Microsoft Q&A and Adobe threads where Hebrew users asked | a short answer with the link (no marketing copy) | release week |
| winget, AlternativeTo, SourceForge mirrors | the winget manifest PR (chapter 10); the others auto-mirror (Handy and Vibe are both there) | after the first release |

What is *not* claimed anywhere: word-error numbers not measured, "unreadable on your PC" (chapter 5 §5.10 check 1 explains the correct wording), and "no data ever leaves your device" (Vibe's phrase) — DeskIT's honest phrase is "nothing leaves until you switch it on, and you can watch it".

## Acceptance

- `docs\he\` and `docs\en\` each contain the ten chapter files, `quickstart.md` and `settings.md`; GitHub Pages serves them at the URL the app's Welcome step, About screen and Update card open (chapters 9, 11).
- Every screenshot named in §14.2 exists under `docs\img\` for the Hebrew tree; the English mirror may reuse them.
- `docs\en\04-privacy.md` contains chapter 5 §5.10's six checks word for word (the test below) and the wording next to the key field matches `docs\strings\`.
- `docs\en\settings.md` is byte-identical to the generator's output for the tagged `defaults.toml`; the retention line in guide chapter 8 equals `docs\strings\retention.md` (chapter 4 §4.9).
- The FAQ carries every entry in §14.5; none of the answers mentions branches, Push/Undo, nightly tests or the Saturday routine.
- `deskit --diagnose` on a fresh install with fixture keys and a marker transcript prints no key-shaped string and not the marker; the issue template's required field accepts the block.
- `SECURITY.md` exists at the archive root and in `APP_DIR` with an e-mail and the 90-day window (chapter 16's `test_legal_files_present` covers presence; the content test is below).
- A non-technical tester (D18 revisit) installs from the GitHub route using only guide chapters 1-2 and the Quick Start, and reaches a pasted Hebrew sentence without asking a question.

## Tests to add

| test | asserts |
|---|---|
| `dev/test_docs.py::test_guide_tree_complete` | both language trees hold `01-install.md` … `10-faq.md`, `quickstart.md`, `settings.md`; `docs\privacy.md` and `docs\terms.md` exist |
| `dev/test_docs.py::test_screenshots_exist` | every `docs\img\<name>.png` referenced by any guide page exists, and every name listed in §14.2 is referenced by its chapter |
| `dev/test_docs.py::test_privacy_chapter_matches_plan` | the six numbered checks in `docs\en\04-privacy.md` equal chapter 5 §5.10's text after whitespace normalisation |
| `dev/test_docs.py::test_key_field_sentence_quoted` | the storage sentence in `docs\en\05-cloud.md` and `04-privacy.md` equals the string in `docs\strings\` exported from the app module that draws screen 3 |
| `dev/test_docs.py::test_settings_doc_fresh` | running `dev/gen_settings_doc.py` against `app\defaults.toml` reproduces the committed `docs\en\settings.md` exactly; every key in `defaults.toml` appears once; no `state.json` key and no DEVELOPER section appears |
| `dev/test_docs.py::test_settings_doc_hebrew_gaps_listed` | a key missing from `settings.he.json` appears in the generator's gap list and falls back to English on the Hebrew page |
| `dev/test_docs.py::test_retention_sentence_matches_defaults` | (shared with chapter 4) the sentence generated from `defaults.toml` equals `docs\strings\retention.md` and the line quoted in `08-your-data.md` |
| `dev/test_docs.py::test_faq_has_no_owner_words` | no guide page contains "Push", "Undo", "nightly", "Saturday", "branch", `problems.md` or `.env` |
| `dev/test_docs.py::test_guide_uses_screen_names` | every "Settings > X", "Dashboard > X" and place name in the guide is one of the names chapter 9 defines (`NAV`, `TABS`, the block titles), so a renamed screen fails the docs build |
| `test_diagnose_is_support_safe` (product tests) | with fixture keys stored and a marker sentence dictated, `--diagnose` output contains neither a key-shaped string (chapter 4's redactor patterns) nor the marker, and contains `version`, `tier`, `os_build` |
| `test_diagnose_never_reads_secrets` (product tests) | `--diagnose` opens no file under `secrets\`, `transcripts.log`, `vocab.json`, `review.json` or `notify.json` (file-open spy) |
| `dev/test_public_tree.py::test_security_md_content` | `SECURITY.md` names an e-mail, the phrase "90 days", the supported-versions line and links `NETWORK.md` |
| `dev/test_public_tree.py::test_issue_templates_present` | `.github/ISSUE_TEMPLATE/bug.yml`, `false-positive.yml` and `config.yml` exist; `bug.yml` has a required field whose label names `--diagnose` |

## Open points

1. **The winget publisher/package id** (`<publisher>.DeskIT`) is chosen by the owner in chapter 16 with the GitHub organisation name; the Install chapter and the Quick Start step 1 carry a placeholder until then.
2. **Which deletion removes the server-side copy of a sent report** is chapter 4 open point 4 / chapter 8's call; guide chapter 8 states the rule once it is settled, and until then says only "Delete my account removes everything on the developer's side".
3. **Phase-0 CPU number.** Guide chapter 2, the FAQ's "no NVIDIA" answer and the Quick Start step 6 use "about as long as you spoke" until the measurement exists (D14 revisit); the sentence is a single string in `docs\strings\` so one edit fixes all three.
4. **Chapter 10 §10.9** (SmartScreen/Defender FAQ background) was still a heading when this chapter was written; the FAQ answers above are self-contained and cite D20 and `research/competitors` directly, and chapter 10 should be checked for agreement on the false-positive submission link and the SHA-256 verification method.
5. **Hebrew community channels** (Telegram/Facebook/Tapuz) are inferred, not verified by the research (`research/competitors` uncertainties); the owner picks the actual groups.


---

# 15. Roadmap, effort, acceptance, test plan

This chapter turns the fifteen preceding chapters into an order of work: six phases, each of which
leaves the tree shippable, with the effort, the dependency, the acceptance gate and the tests that
prove the gate (D27). The estimates are working days for one developer plus AI coders, and they are
rough; phase 0 exists precisely to replace guesses with numbers before phase 1 starts. Nothing here
introduces a new decision; every row points back at the chapter that owns the design.

Two rules govern the whole roadmap:

- **Each phase ends green.** A phase is not "done" when its code is merged; it is done when its
  acceptance row below passes and the tests listed for it are in the product suite. A phase may be
  cut short, but it may not be left half-merged.
- **The owner's machine keeps working at every commit** (D4). Every pull request below is tested in
  portable mode on his checkout before merge; `portable.txt` beside `main.py` is the first file
  phase 1 creates (chapter 3).

## Phases

| Phase | Contents (chapter) | Depends on | Effort | Acceptance |
|---|---|---|---|---|
| **0 Ground truth** | Measure CPU int8 latency of the Hebrew turbo model on a no-GPU laptop with a 7 s clip (ch. 6); VirusTotal-scan a throwaway installer built from the embeddable python.org zip (ch. 10); verify Supabase anonymous sign-in + Turnstile on the Free plan (ch. 8); check whether an LGPL cp311 `av` wheel exists (ch. 13); owner decides licence and package id (ch. 16, D23/D29); owner rotates and deletes his Gemini/Groq/Cerebras keys (D28). | none | 3 | Numbers written into the guide draft (the tier-2 sentence is "usable" or "cloud recommended"); go/no-go on tier 2 and on the Store; `LICENSE` committed; `.env` on the owner's machine holds fresh test keys only. |
| **1 Separation** | `paths.py` with the three roots, portable/DEVELOPER detection, `--migrate` (ch. 3, D1/D4); `defaults.toml` + `settings.toml` + `state.json` and the new `config.set_values` (ch. 3, D2); `secrets.py` on Credential Manager/DPAPI (ch. 3, D3); `net.py` + `ALLOWED_HOSTS` + the import test and the mock-transport test (ch. 5, D12 locks 1-2); `[privacy]` gates, `privacy.allowed()`, consent cards, `consent.json` (ch. 5, D7); support-safe `app.log` + redactor (ch. 4, D8); neutral defaults (ch. 4, D6); `VERSION` + `version.py` (ch. 11); DEVELOPER flag hides every owner surface (ch. 7, D15); test split into product and `dev/` (ch. 7); collision-proof names (D5).; `DeskIT Dev` identity (`dev` suffix on mutex/pipe/port/AppID, DEV tag) and the mutual pause between the two copies (D30) | 0 | 15-20 | Owner's checkout runs unchanged in portable mode; product CI green without `dev/`; `test_no_key_shaped_string_in_data_dir` and `test_supabase_never_sees_provider_keys` green; `logs\network.log` shows only `127.0.0.1` during a plain dictation (`test_plain_dictation_touches_only_loopback`). |
| **2 Installable** | Wheelhouse with `--require-hashes`, embeddable Python + tcl/tk, `python311._pth` (ch. 10, D19); Inno per-user installer (ch. 10, D20); first-run wizard with the probe, model download, GPU/Recording/Skin packs (ch. 6 and 9, D13/D14/D18); PyAV out of the core (ch. 13, D24); google-genai replaced by REST through `net.py` (ch. 5); update check + verified download + Update card (ch. 11, D21); `MANIFEST.sha256` + attestation + `deskit --verify` (ch. 10, D12 lock 5); `THIRD-PARTY-NOTICES.txt`, privacy policy, terms, `SECURITY.md`, `NETWORK.md` (ch. 13, 14); winget manifest (ch. 10). | 1 | 15 | Clean Windows 11 VM, Defender on, no NVIDIA: install, wizard, one Hebrew sentence pasted, all within 10 minutes and with no console window; VirusTotal at most 2 hits; `deskit --verify` clean; winget PR merged. |
| **3 Reports, account, Store** | Supabase project + published `0001_init.sql` + RLS + bucket (ch. 8, D17); anonymous auth with a DPAPI session (ch. 8); Report a problem v2 with Preview and `problems\outbox\` (ch. 7, D16); `developer_status` and the replies row (ch. 7, 9); Your data page + `delete_me()` RPC (ch. 4, 8, D9); `dev/inbox.py` and the re-pointed Saturday routine (ch. 7); weekly keep-alive cron (ch. 8); Microsoft Store submission with the launcher stub and the runFullTrust text (ch. 10, D20).; Google sign-in and vocabulary/settings/history sync with its two consent gates (ch. 8, D31) | 2 | 12-15 | A report sent from a second machine appears in Studio with no e-mail and no key-shaped string (`test_report_payload_has_no_key` plus the manual Studio check); Delete my account removes every row and storage object; Store certification passed. |
| **4 Phone** | Package rename to `io.github.massifapp.deskit`, release keystore, LAN pairing (cert, fingerprint, QR, NSD picker), per-phone tokens, Settings > Phone, route hygiene, GitHub-Release APK, Play closed test with 12 testers, Data safety form (ch. 12, D22). | 2 (3 only for the policy URL on the Play listing) | 12 | Phone dictates over home Wi-Fi with no Tailscale installed; a packet capture on the router shows TLS to the PC's address only; "Forget this PC" leaves no token on the phone. |
| **5 Trust and reach** | SignPath Foundation application (Apache only), IzzyOnDroid listing, Certum fallback decision (ch. 10, D20); e-mail linking via OTP with Resend + a domain (ch. 8); settings/vocab sync (ch. 8, D17); whisper.cpp Vulkan tier 3 after a Hebrew WER check (ch. 6, D14); Google PKCE sign-in (ch. 8). | 3, 4 | 10+ | Signed installer shows a publisher name in the SmartScreen dialog; sync round-trips `settings.toml` and `vocab.json` between two PCs; tier 3 ships only if its WER passes the threshold chapter 6 sets. |

Effort sums: **v1 (phases 0-2) = 33-38 days**; through phase 4 = 57-65 days; phase 5 is open-ended
because three of its items wait on third parties (SignPath review, IzzyOnDroid, a domain purchase).

Dependencies that the table does not make obvious:

- Phase 2's wizard needs phase 1's `state.json` (`setup_done` lives there, D2) and phase 1's
  `net.py` (the model download is an outbound call and must appear in the Network window, D12).
- Phase 3's Store submission needs phase 2's tree unchanged; the MSIX is "the same tree packaged
  twice" (D19/D20), so the Store work cannot begin before the Inno build is stable.
- Phase 4's Play listing needs the privacy policy URL from phase 2 and nothing from phase 3; the
  phone never talks to Supabase (D22).
- Phase 5's e-mail linking is the only roadmap item that costs money (a domain, D28); it is last on
  purpose.

## The v1 definition

v1 is the first public build and equals phases 0-2 (D27). A stranger can: download the installer
from GitHub Releases or run `winget install`, pass SmartScreen with the guide's screenshot, run the
wizard, download the Hebrew model, dictate locally, paste a Groq key behind a consent card, report a
problem **to a local file**, and update with one click. Everything below is explicitly **not** in v1
and must not leak into the v1 tree behind a half-finished switch:

| Cut from v1 | Returns in | Where the cut is enforced |
|---|---|---|
| Read-aloud tab, `corpus\read\`, the Writer | Opt-in later, if at all (D6, `study.corpus_keep = 0`) | Tab hidden unless `corpus_keep > 0` (ch. 4, 9) |
| Cerebras backend and `CEREBRAS_API_KEY` | Never | Deleted (ch. 5, `test_cerebras_is_gone`) |
| The Hebrew web page `/` and `/app.apk` from the PC | Never | Routes removed (ch. 12) |
| Saturday routine, `questions.py`, nightly tests, `install_nightly_task.ps1`, git card | Never in the product; they live in `dev/` | Build manifest (ch. 7, 10; appendix A) |
| Settings/vocab sync, e-mail accounts, Google sign-in | Phase 5 | No sync client code in v1; the tables exist in the migration so the schema is published once (ch. 8) |
| Problem-report upload, account, Store | Phase 3 | "Send to the developer" checkbox absent from the v1 card; reports stay in `problems.json` (ch. 7) |
| Phone pairing, Play | Phase 4 | Settings > Phone shows "coming in a later version" and the Tailscale recipe only (ch. 12) |
| AMD/Intel GPUs (tier 3) | Phase 5 | Probe reports "no NVIDIA" and takes tier 2 (ch. 6) |
| Screen recording and camera | v1 only if the Recording pack installs on the clean VM | Record and camera keys hidden until `packs\recording` exists (ch. 6, 13) |

## Per-phase test plan

### Where tests live and how they run

Today `tests.py` is one 29,140-line file that mixes product tests with owner-ops tests (`tests.py:25281`,
`28490-28510`, `map/owner` rec 12), and `tests_quiet.py` runs it on a second Windows desktop created
with `CreateDesktop`, with a `NEEDS_SCREEN` list of 16 tests that grab the display or move the real
mouse and a `--no-screen` switch that skips them (`tests_quiet.py:8-13, 46-64`). Phase 1 splits this
as chapter 7 specifies:

| Suite | Path | Runs where | Contents |
|---|---|---|---|
| Product suite | `tests.py` (kept name so the owner's habits survive) plus one new module per new subsystem: `tests_layout.py` (ch. 3), `tests_privacy.py` (ch. 4-5), `tests_hardware.py` (ch. 6), `tests_reports.py` (ch. 7-8), `tests_build.py` (ch. 10-11), `tests_phone.py` (ch. 12) | GitHub Actions on `windows-latest` and on the owner's hidden desktop | Everything the product build must pass; imports nothing from `dev/` |
| Ops suite | `dev/tests_ops.py` | Owner's machine only | Nightly, questions, routine, git card, `weekly_review.ps1` fixtures |
| Runner | `tests_quiet.py` (moves to `dev/`; CI calls the product suite directly) | Owner's machine | Second desktop + `--no-screen` |

**The hidden-desktop rule.** On the owner's machine the suite is never run on his interactive
desktop: `tests_quiet.py` creates a separate desktop for the Tk windows and the overlay, and while
he is at the desk it is run with `--no-screen` so the 16 screen-grabbing tests are skipped (his own
standing instruction; `tests_quiet.py:46-64`). AI coders follow this rule without exception. The
`NEEDS_SCREEN` list must be extended for every new test that opens a card, grabs a monitor or moves
the mouse; `test_needs_screen_list_is_complete` (below) enforces it. On CI there is no desktop
question: `windows-latest` runners have an interactive session and the whole suite runs, with the
overlay tests marked to skip when no display is present.

### Tests per phase

The names below are defined in the chapters cited; this table only assigns them to the phase whose
gate they prove, and adds the few cross-cutting tests that belong to no single chapter.

| Phase | Test module | Tests that must be green at the gate |
|---|---|---|
| 0 | none (measurements, not tests) | Phase 0 produces numbers, not tests. Its outputs are: the CPU latency table (ch. 6), the VirusTotal report (ch. 10), a yes/no on anonymous sign-in (ch. 8), a yes/no on the LGPL wheel (ch. 13). |
| 1 | `tests_layout.py` | `test_paths_portable_when_marker_present`, `test_paths_developer_requires_git`, `test_no_app_dir_store_writes`, `test_config_layers_merge_order`, `test_settings_toml_holds_only_overrides`, `test_set_values_creates_missing_section`, `test_state_keys_never_in_settings`, `test_settings_page_no_coordinates`, `test_secrets_lookup_order`, `test_secrets_never_on_disk_in_data_dir`, `test_migrate_moves_joined_stores_as_unit`, `test_migrate_is_idempotent`, `test_pipe_name_has_session_id`, `test_port_fallthrough_written_to_state`, `test_app_id_is_neutral` (ch. 3) |
| 1 | `tests_privacy.py` | `test_only_net_imports_transport`, `test_net_refuses_unlisted_host`, `test_net_offline_refuses_all_but_loopback`, `test_privacy_gate_refuses_every_cloud_constructor`, `test_consent_round_trip_and_withdraw_teardown`, `test_supabase_module_imports_nothing_secret`, `test_supabase_never_sees_provider_keys`, `test_no_key_shaped_string_in_data_dir`, `test_plain_dictation_touches_only_loopback`, `test_polish_glossary_filtered_to_text`, `test_cerebras_is_gone`, `test_env_alias_google_api_key_ignored` (ch. 5); `test_app_log_never_quotes_text`, `test_server_logs_host_only`, `test_redactor_patterns`, `test_redactor_matches_stored_secret`, `test_defaults_toml_ships_privacy_values`, `test_defaults_toml_has_no_owner_values`, `test_dataclass_backend_default_is_local`, `test_history_keep_days_prunes`, `test_review_ring_floor` (ch. 4) |
| 1 | `tests_build.py` | `test_version_file_is_single_source`, `test_version_no_git_on_user_machine`, `test_problems_env_fields` (ch. 11); `test_build_tree_has_no_forbidden_files` (ch. 3); cross-cutting: `test_product_suite_imports_no_dev_modules`, `test_developer_flag_hides_owner_surfaces`, `test_needs_screen_list_is_complete` (this chapter) |
| 2 | `tests_hardware.py` | `test_hardware_probe_no_nvidia`, `test_hardware_probe_small_card`, `test_hardware_probe_old_driver`, `test_models_dry_run_size_line`, `test_models_partial_never_loads`, `test_models_verify_hashes`, `test_models_offline_env_after_complete`, `test_models_hosts_allowlisted`, `test_packs_pip_command`, `test_packs_activate_path_order`, `test_packs_failed_falls_to_cpu_with_card`, `test_base_wheelhouse_has_no_pack_wheels`, `test_detector_offered_only_on_gpu_tier`, `test_ollama_absent_hides_local_entries`, `test_tts_probe_no_hebrew_voice`, `test_cpu_slow_card_once`, `test_no_owner_numbers_in_copy` (ch. 6) |
| 2 | `tests_privacy.py` | `test_gemini_rest_request_shape`, `test_gemini_inline_limit_refused_before_send`, `test_gemini_429_parsed_from_json_body`, `test_net_never_puts_key_in_url`, `test_keys_page_never_redisplays_value`, `test_allowed_hosts_match_network_md`, `test_verify_manifest_detects_a_changed_file` (ch. 5) |
| 2 | `tests_build.py` | `test_latest_json_schema`, `test_update_check_cadence`, `test_update_check_respects_gate`, `test_update_check_request_shape`, `test_update_download_sha_match_runs_inno`, `test_update_download_sha_mismatch_discards`, `test_update_semver_compare`, `test_inno_script_never_names_data_dir`, `test_migrations_run_in_order_once` (ch. 11); `test_legal_files_present`, `test_no_owner_strings_in_archive`, `test_release_assets_named` (ch. 16); cross-cutting: `test_wheelhouse_hashes_pinned`, `test_manifest_covers_every_shipped_file`, `test_wizard_writes_setup_done_to_state` (this chapter) |
| 3 | `tests_reports.py` | `test_report_payload_has_no_key`, `test_migration_has_no_key_column_and_has_checks` (ch. 5); `test_delete_reports_purges_evidence`, `test_delete_everything_sequence`, `test_your_data_rows_cover_every_store`, `test_export_zip_contents` (ch. 4); `test_only_publishable_key_ships`, `test_schema_equals_migration` (ch. 16); the report-v2, outbox, replies and `delete_me()` tests chapters 7 and 8 define; cross-cutting: `test_outbox_survives_paused_project` (this chapter) |
| 4 | `tests_phone.py` | The pairing, pinning, token and route tests chapter 12 defines; cross-cutting: `test_apk_id_matches_decision`, `test_phone_routes_no_apk_no_web_page` (this chapter) |
| 5 | `tests_reports.py`, `tests_hardware.py` | The sync and OTP tests chapter 8 defines; the tier-3 WER gate chapter 6 defines |

### CI shape

One GitHub Actions workflow `ci.yml` runs the product suite on every pull request on
`windows-latest`, with `DESKIT_PORTABLE=1` and a temporary `DATA_DIR` under the runner's temp
folder so no test touches a real profile. A second workflow `release.yml` (chapter 10) builds the
installer from the tag and runs `tests_build.py` against the built tree. The ops suite has no
workflow; it runs only on the owner's machine through `dev/`.

## Risk register

The top twelve risks, with the phase that carries them, the mitigation the plan already contains,
and who owns the response. "Owner" means a hand action from chapter 16; "code" means an AI coder
implements it from the cited chapter.

| # | Risk | Phase | Likelihood / impact | Mitigation in the plan | Owner |
|---|---|---|---|---|---|
| 1 | CPU int8 latency on a real laptop is far worse than the RTF 0.5-2 estimate, making tier 2 useless and the Groq audio opt-in the real default | 0 | medium / high | Phase 0 measures first; tier-2 copy has two variants ("usable" / "cloud recommended", ch. 6); the wizard's "say one sentence" step reports the measured time (D18) | owner measures; code picks the copy |
| 2 | Defender or SmartScreen flags the unsigned embeddable-Python installer more than expected | 0, 2 | medium / high | Phase-0 VirusTotal scan of a throwaway build (D19 revisit clause); stable file names, the guide's screenshot, false-positive submission link (D20); Store channel in phase 3 as the warning-free door | owner scans; code keeps names stable |
| 3 | Supabase anonymous sign-in or Turnstile is not available on the Free plan | 0, 3 | low / medium | Phase 0 verifies; fallback is e-mail OTP from day one, which pulls the domain purchase forward (D17 revisit, D29 item 4) | owner verifies |
| 4 | Store rejects a full-trust MSIX with a global keyboard hook, screen capture keys and a listening port | 3 | medium / medium | GitHub + winget stays primary; SignPath application moves up from phase 5 (D20 revisit) | owner submits; code unaffected |
| 5 | The `--migrate` step corrupts the owner's cross-store ids (`recent\` stem = `review.json` id = report id) and his own machine stops working | 1 | low / high | Stores move as a unit, refused while the app runs, idempotent (ch. 3, `test_migrate_moves_joined_stores_as_unit`, `test_migrate_refuses_while_running`); portable mode means the owner never has to run it | code |
| 6 | A cloud constructor is added later that bypasses `privacy.allowed()` or `net.py` | 1 onward | medium / high | The static import test and the constructor-enumeration test fail the build (ch. 5, D12 lock 2); `NETWORK.md` must match `ALLOWED_HOSTS` (`test_allowed_hosts_match_network_md`) | code, enforced by CI |
| 7 | No LGPL cp311 `av` wheel exists, and faster-whisper's module-level import drags GPL FFmpeg into the core | 0, 2 | medium / medium | Phase 0 checks; fallback is vendoring faster-whisper (MIT) with a lazy `av` import and moving all of `av` into the Recording pack (D24) | owner checks; code vendors |
| 8 | Half-downloaded model leaves the user with a broken install (every competitor's top issue) | 2 | high / medium | `dry_run` size line, resumable `snapshot_download`, hash verification, never loading a partial snapshot, "Delete and re-download" (D13, `test_models_partial_never_loads`) | code |
| 9 | Google's REST `generateContent` path behaves differently from the SDK for inline audio (size limit, 429 body shape) | 2 | low / medium | `test_gemini_inline_limit_refused_before_send`, `test_gemini_429_parsed_from_json_body` (ch. 5); interim: SDK kept with `base_url` pinned and env pickup disabled (D12) | code |
| 10 | The owner's tailnet name, phone token or a key reaches the public git history | 0 | medium / high | Phase-0 history check and key rotation (D28); `test_no_owner_strings_in_archive` and `test_gitignore_covers_owner_files` (ch. 16) | owner |
| 11 | Play reviewers read "audio to your own PC" as data collection and reject the IME or demand a different Data safety answer | 4 | medium / low | GitHub APK is the v1 delivery; Play is phase 4 and optional (D29 item 6); the Data safety wording is in ch. 12 | owner |
| 12 | The Saturday routine, re-pointed at `problems\inbox\`, loses the `AskUserQuestion` flow it uses today and silently stops processing reports | 3 | medium / low | `dev/inbox.py` contract in ch. 7; the routine's command file is updated by hand (D28); a report with no reply after 14 days is visible in Studio | owner + code |

Two risks that are **not** on the register on purpose: paid certificates (deferred by D20 until user
numbers justify them) and Velopack-style self-update (rejected for v1 by D21).

## The first ten pull requests

The order is chosen so that each PR is small enough to review in one sitting, leaves the owner's
checkout working in portable mode, and unlocks the next. PRs 1-10 cover phase 1 and the first third
of phase 2.

| PR | Title | Files (appendix A has the full list) | Unlocks |
|---|---|---|---|
| 1 | `paths.py` and portable mode | New `paths.py`; `portable.txt` in the owner's checkout; `main.py:34` and the `APP_DIR / "<store>"` sites in `main.py`, `history.py:27-28`, `apikey.py:18-19`, `cues.py:21`, `firstrun.py:52-53, 65`, `server.py:66-70`, `lookup.py:627-629`, `problems.py:316, 909-910`, `study.py:556, 690-709`, `review.py:914, 1189-1214`, `dashboard.py:213-215, 461, 887, 3626, 3822, 3879, 3941, 5519, 6479-6514`, `notify_hook.py:54, 370` | Everything |
| 2 | Three config layers | `defaults.toml` from `config.toml`; `config.py` `load()`/`set_values` (`config.py:1482-1487, 2340-2432`); `settings.py:187-269` reads `defaults.toml`; `state.json` writer for `main.py:623-742, 1420-1505`; owner values scrubbed (ch. 4) | Neutral defaults, wizard |
| 3 | `secrets.py` and the Keys lookup | New `secrets.py`; `apikey.py` rewritten to call it (`apikey.py:24-63`); `.env` reader gated by DEVELOPER; `server.py:97-113` token to DPAPI; `notify_hook.py:54` reads the new location | Keys page, proof lock 1 |
| 4 | `net.py` chokepoint and the two lock tests | New `net.py`; `translate.py:450-470`, `visual_qa.py:833-867, 906-919`, `transcribers/gemini.py:61-73` (interim `base_url` pin), `lookup.py:703-750`, `translate.py:310-335` (Ollama through `net.py` too, loopback purpose); `tests_privacy.py` | Network window, Offline switch |
| 5 | `[privacy]` gates and consent cards | New `privacy.py`; constructors in `translate.py`, `transcribers/gemini.py`, `visual_qa.py:714-960`; `consent.json`; consent card in `overlay.py`; `tests.py:10804-10836` generalised | Cloud features for strangers |
| 6 | Support-safe logs and the redactor | `main.py:4551, 5205`, `study.py:649`, `review.py:1053, 1141` stop quoting text; `server.py:653-654` logs host only; redactor module used by `problems.py` and `--diagnose`; `[history] keep_days` | Reports, `--diagnose` |
| 7 | DEVELOPER flag and the owner-surface hide | `dashboard.py` git block 838-1114, `_wake_review` 5126-5190, `_nightly_running/_stop_tests` 8019-8052, `Open problems.md` 4058-4060, questions 4574-5122, Read-aloud tab; `settings.py` rows for `[tests]`, `awake.vitals_minutes`, `notify.watch`, `study.read_*`; `main.py` CLI flags `--study/--review/--benchmark` | A product-only dashboard |
| 8 | Test split and CI | `tests.py` product part kept; `dev/tests_ops.py`; `tests_quiet.py` to `dev/`; `ci.yml`; `test_product_suite_imports_no_dev_modules` | Every later PR is gated |
| 9 | `VERSION`, `version.py`, `problems.env()` | New `VERSION`, `version.py` replacing `versions.py:52-66`; `problems.py:274-302` env fields; `dashboard.py` branch line behind DEVELOPER; Android `build.gradle.kts:16-20` reads the same file (ch. 11) | Update check, reports |
| 10 | Wheelhouse and embeddable Python build | `requirements.lock` with hashes; `keyboard.py` renamed `keycaps.py`; `pillow`/`comtypes` added, `keyboard` package dropped; `release.yml` first half (wheelhouse, zip + SHA, tcl/tk copy, `_pth`, `git archive`, `MANIFEST.sha256`); `build/manifest.txt` of excluded files | Inno installer (PR 11), `--verify` |

After PR 10 the remaining phase-2 work follows in this order: Inno script and installer behaviour
(ch. 10), hardware probe + model download + packs (ch. 6), the wizard rewrite (ch. 9), google-genai
to REST (ch. 5), update check and card (ch. 11), legal and notices files (ch. 13), winget manifest
(ch. 10). Phase 3 opens with the Supabase migration PR because the schema is a published artefact
that the client code, the RLS tests and the privacy policy all cite.

## Acceptance

The roadmap itself is "done" when:

1. Every phase in the table has an owner-visible checklist in the tracker (GitHub Issues milestones
   named `phase-0` to `phase-5`), each item linking to the chapter section that specifies it.
2. Phase 0 has produced its four numbers/answers and the two owner decisions (licence, package id),
   and they are written into chapters 6, 8, 10, 13 and 16 in place of the placeholders.
3. Phase 1's four acceptance conditions hold on the owner's machine in portable mode and on CI.
4. Phase 2's clean-VM run has been performed on a VM with Defender on and no NVIDIA card, timed,
   and recorded (video or step log) in the release notes of the first public tag.
5. The per-phase test table above matches the test names in chapters 3-14 (a mismatch means one of
   the chapters changed and this table was not updated; `test_plan_index` in chapter 1 covers the
   chapter list, and `test_roadmap_names_existing_tests` below covers the test names).
6. The first ten PRs have merged in the listed order, or a written note in the PR explains the
   deviation.

## Tests to add

These are the cross-cutting tests this chapter introduces; the per-phase table above assigns the
rest to their chapters.

| Test | Asserts |
|---|---|
| `test_product_suite_imports_no_dev_modules` | Importing every product test module and every product `.py` file never imports `nightly`, `questions`, `tests_quiet`, `inbox` or anything under `dev/`; fails with the offending module name. |
| `test_developer_flag_hides_owner_surfaces` | With `paths.DEVELOPER` false, the dashboard builds without the git block, the questions place, the Stop-tests button, the branch line, the Read-aloud tab and the `[tests]`/`awake.vitals_minutes`/`notify.watch`/`study.read_*` rows; with it true, all of them are present. |
| `test_needs_screen_list_is_complete` | Every test whose body calls a screen grab, `ImageGrab`, `SetCursorPos`, `SendInput` or opens an overlay card is named in `NEEDS_SCREEN`; a new test that does so and is missing from the list fails this test. |
| `test_wheelhouse_hashes_pinned` | `requirements.lock` contains a `--hash` for every requirement and pip's `--require-hashes` dry-run accepts it; no requirement is unpinned. |
| `test_manifest_covers_every_shipped_file` | The `MANIFEST.sha256` produced by the build lists every file under `app\` and `python\` and nothing outside them; the excluded-files manifest (ch. 7, appendix A) and the shipped list are disjoint. |
| `test_wizard_writes_setup_done_to_state` | Completing the wizard writes `setup_done` (and `config_version`) into `state.json`, never into `settings.toml` or `defaults.toml`, and `firstrun.needed()` reads only `state.json`. |
| `test_outbox_survives_paused_project` | With the mock transport returning the paused-project response, a queued report stays in `problems\outbox\`, the card shows "will retry", no error dialog appears, and the next successful run uploads it once. |
| `test_apk_id_matches_decision` | `android/app/build.gradle.kts`, `method.xml`, `Notify.kt` and the Play metadata all carry `io.github.massifapp.deskit`; `com.yoav.dictation` appears nowhere in the tree. |
| `test_phone_routes_no_apk_no_web_page` | `server.py` answers 404 for `GET /` and `GET /app.apk`; `/health` returns exactly `{ok, version}`; `GET /review` returns only items with `source == "phone"`. |
| `test_roadmap_names_existing_tests` | Every backticked `test_*` name in this chapter's per-phase table is defined in the chapter it is attributed to (a doc-consistency test that runs over `DISTRIBUTION_PLAN.md`; it lives with chapter 1's `test_plan_index`). |
| `test_ci_runs_in_temp_data_dir` | Under `ci.yml` the product suite's `DATA_DIR` resolves under the runner's temp folder and `%LOCALAPPDATA%\DeskIT` is never created. |

## Open points

1. **Effort numbers are unvalidated.** D27 and `arch-B §13` give the same ranges; neither is based on
   a measured velocity for this codebase. The first three PRs should be timed and the table revised
   before phase 2 is scheduled.
2. **Test-module naming.** D15 only says "tests.py split into product tests and `dev/` ops tests".
   The per-subsystem module names proposed here (`tests_layout.py` etc.) are a suggestion to keep
   the 29k-line file from growing; if chapter 7 (in progress) names them differently, chapter 7 wins
   and this table is renamed.
3. **Chapters 7, 8 and 9 were skeletons when this chapter was written**, so their test names are
   referenced generically ("the report-v2, outbox, replies tests chapter 7 defines"). Once those
   chapters land, the phase-3 and phase-4 rows should list the names explicitly, and
   `test_roadmap_names_existing_tests` will flag any that do not exist.
4. **Screen recording in v1** depends on the phase-0 LGPL-wheel answer (D24 revisit); the v1 cut
   table above carries both outcomes. The decision should be recorded in chapter 13 once known.
5. **CI runner display.** Whether `windows-latest` can run the overlay tests without the hidden
   desktop wrapper is assumed, not verified; if it cannot, `tests_quiet.py` stays in the product
   tree as the CI entry point rather than moving to `dev/`.


---

# 16. What the owner must do by hand, and open decisions

Everything in this chapter is work that code cannot do: accounts that need a person's identity,
payments, decisions about licence and name, measurements on hardware only the owner has, and the
hygiene of a repository that is about to become public. It implements D28 (the hand-work list) and
D29 (the open decisions). Part A is grouped by roadmap phase (chapter 15) so the owner can do each
block when that phase starts; the cost is 0 unless a row says otherwise. Part B lists the decisions
only the owner can settle, each with the recommendation from `decisions.md` and what the alternative
costs. Part C is the seed of the Hebrew summary the owner reads. Every row says what to copy back
into the repo or the app, because that is what unblocks the AI coder.

## A. Hand-work checklist, by phase

Column "Copy back" names the file, settings key or secret store the result lands in; "—" means nothing
enters the repo (the row is a decision, a measurement reported in chat, or an account that stays in
the owner's password manager).

### Phase 0 — Ground truth (before the first public commit)

| # | Task | Where | Cost | Copy back / unblocks |
|---|---|---|---|---|
| 0.1 | Decide the licence and trademark posture (Part B, decision 1). | — | 0 | `LICENSE` (Apache-2.0, copyright "Yoav Shimron") and `TRADEMARK.md` reserving the DeskIT name, the dalet-as-desk mark and the icon (D23; chapter 13). Gates SignPath, IzzyOnDroid and Certum OSS. |
| 0.2 | Decide the public name and the Android package id (Part B, decision 2). | — | 0 | `applicationId` in `android/app/build.gradle.kts:11` (today `com.yoav.dictation`) becomes `io.github.massifapp.deskit` before any outside install; it cannot change afterwards (D22; chapter 12). |
| 0.3 | Rotate and delete his own API keys: the Gemini, Google, Cerebras and Groq keys that `apikey.py:24-26` reads from `.env` today. Delete them in the Google AI Studio and Groq consoles, close the Cerebras key entirely (the path is removed, D6), then create fresh personal keys used only for testing. Optionally enable Zero Data Retention on his Groq console. | aistudio.google.com, console.groq.com, cloud.cerebras.ai | 0 | Nothing enters the repo: from phase 1 the test keys live in Credential Manager under `DeskIT/groq` and `DeskIT/gemini` (D3). Google's API ToS forbids embedded developer credentials (`research/keys-privacy` "What the owner must do"). |
| 0.4 | Clean the tree: add `questions.json`, `questions.lock` and `.agents/` to `.gitignore` (today it covers `.env`, logs, audio, `vocab.json`, `review.json`, captures and cues but not those three); move owner scripts (`weekly_review.ps1`, `install_nightly_task.ps1`, `questions.py`, nightly files) to `dev/`; hand the AI coder the list of values in `config.toml` that are his (mic name, absolute folders, coordinates, `vocab.terms` seeds, `server.enabled`) so `defaults.toml` ships without them (D2, D6, D15; chapter 3). | the checkout | 0 | `.gitignore`, `dev/`, `app/defaults.toml`. |
| 0.5 | Check git history for private strings before publishing. Known today: the tailnet host `yoav.example.ts.net` is a tracked constant at `android/app/src/main/java/com/yoav/dictation/Prefs.kt:25`, so it is in every commit that touched that file; the phone token that once sat in `app.log` is untracked but must be confirmed absent. Decide between publishing from a fresh history and rewriting (Open points). | the checkout | 0 | — (decision reported in chat; the coder deletes `DEFAULT_URL`, D22). |
| 0.6 | Measure on a laptop with no NVIDIA card: CPU int8 latency of the turbo model for a 7 s Hebrew clip, plus the same on a 125 % and a 150 % DPI laptop and a single-monitor desk for the layouts (D14, D27; `research/models` "What the owner must do"). | his hardware | 0 | Numbers reported in chat; they land in the tier-2 copy and the CPU-slowness card (chapter 6) and in the guide's expectations (chapter 14). |
| 0.7 | Run the phase-0 checks the coder prepares: VirusTotal scan of a throwaway embeddable-Python installer (needs Inno Setup 6 and a full Python 3.11 on the build machine, `research/packaging` "What the owner must do"); Supabase anonymous sign-in + Turnstile availability on Free; existence of an LGPL cp311 `av` wheel (D24, D27). | virustotal.com, supabase.com, github.com/JScheumann/pyav-ffmpeg-lgpl | 0 | Results reported in chat; they decide chapter 10's Defender FAQ, chapter 8's auth fallback and chapter 6's Recording pack. |

### Phase 1 — Separation (keeping his own machine honest)

| # | Task | Where | Cost | Copy back / unblocks |
|---|---|---|---|---|
| 1.1 | Put `portable.txt` beside `main.py` in his checkout (or set `DESKIT_PORTABLE=1`); the `.git` folder already triggers DEVELOPER mode (D4). Never run `deskit --migrate` on his machine unless he wants the product layout. | the checkout | 0 | `portable.txt` (git-ignored). |
| 1.2 | Keep `DESKIT_SUPABASE_SECRET` only in his user environment, never in `.env` or the repo (D17, D28). | Windows environment variables | 0 | — |
| 1.3 | Move his test keys from `.env` into Credential Manager once `secrets.py` exists (the `--migrate` import step does this; in portable mode the `.env` reader stays, D3/D4). | Control Panel > Credential Manager | 0 | — |
| 1.4 | Update the Saturday routine's command file to read `problems\inbox\<user_id>\` and to state which fields are consented (D15; chapter 7 gives the `dev/inbox.py` contract). | `dev/` | 0 | the routine's command file under `dev/`. |

### Phase 2 — Installable (public repo, papers, first release)

| # | Task | Where | Cost | Copy back / unblocks |
|---|---|---|---|---|
| 2.1 | Create the public GitHub repository under the chosen name; enable Actions, build attestations (`actions/attest-build-provenance` is free for public repos) and Pages; add the contact e-mail to `SECURITY.md` (90-day disclosure window, D26) and to the privacy policy (D25). Releases can use the workflow's own token; a fine-grained token with `contents: write` is only needed for uploads from his desk (`research/updates` "What the owner must do"). | github.com | 0 | `SECURITY.md`, repo URL in `net.py` `ALLOWED_HOSTS` comments and `latest.json` URL (D12, D21). |
| 2.2 | Prepare the build machine: full Python 3.11 installed once (to copy the tcl/tk tree), Inno Setup 6, a clean Windows 11 VM with Defender on and no NVIDIA driver for the acceptance run (D19, D27; `research/packaging` "What the owner must do"). | his PC | 0 | — |
| 2.3 | Write the legal papers in Hebrew and English: privacy policy and terms (chapter 13 gives the outline), the one-page database definition document, the written basic security procedure, the access list (one person), the incident log and the breach e-mail template required by the 2017 Data Security Regulations at the individual-managed tier (D25). | GitHub Pages | 0; optional one-hour lawyer review is the only likely paid legal item | `docs/privacy.md`, `docs/terms.md` under Pages; the four internal documents stay with the owner. |
| 2.4 | Send ivrit.ai a courtesy note and ask to be listed as a tool using their model; optionally re-convert the model to int8 (~0.8 GB) and upload it under his own Hugging Face account (one-time `hf auth login` for upload only; users never need a token) (D13; `research/models` "What the owner must do"). | huggingface.co | 0 | If the mirror exists: its repo id and pinned commit into the model table (chapter 6). |
| 2.5 | Submit the winget manifest from his GitHub account after the first release (`wingetcreate new` once, then `wingetcreate update` per release); answer moderator labels within 10 days or the PR closes (D20; `research/updates` and `research/packaging` "What the owner must do"). | github.com/microsoft/winget-pkgs | 0 | The package identifier into the release workflow (chapter 10). |
| 2.6 | Publish the first release: tag, notes, `DeskIT-Setup-x.y.z.exe`, SHA-256, VirusTotal link, `latest.json` (chapter 11's release checklist). | github.com | 0 | — |

### Phase 3 — Reports, account, Store

| # | Task | Where | Cost | Copy back / unblocks |
|---|---|---|---|---|
| 3.1 | Supabase: sign up (GitHub or e-mail, no card expected); new organisation on Free; new project named `deskit`, region `eu-central-1` (Frankfurt); generate the database password and save it in his password manager (D17; `research/supabase` "What the owner must do" 1). | supabase.com | 0 | — |
| 3.2 | Project Settings > API Keys: copy the Project URL and the `sb_publishable_` key. Never copy `sb_secret_`; it lives only in his password manager and in `DESKIT_SUPABASE_SECRET` on his machine for `dev/inbox.py` (D17). | Supabase dashboard | 0 | Project URL + publishable key into the app's Supabase config and the `<ref>.supabase.co` entry in `ALLOWED_HOSTS` (D12; chapters 5, 8). |
| 3.3 | SQL Editor: paste `supabase/migrations/0001_init.sql` exactly as published in the repo (tables, RLS, anon grants revoked, CHECK constraints, bucket and storage policies, `delete_me()` RPC) (D12 lock 3, D17; chapter 8). | Supabase dashboard | 0 | The migration is the deliverable; the dashboard must match it byte for byte. |
| 3.4 | Authentication: enable anonymous sign-ins and Cloudflare Turnstile (verified in 0.7); leave the e-mail provider for phase 5; set Site URL to the GitHub Pages guide (D17). | Supabase dashboard | 0 | — |
| 3.5 | Storage: confirm bucket `reports` is private, 5 MB per file, MIME allowlist `image/jpeg`, `application/json`, `text/plain`, and `audio/wav` (D17). | Supabase dashboard | 0 | — |
| 3.6 | Turn on MFA for the Studio login; add the weekly keep-alive GitHub Actions cron (one REST GET with the publishable key) so the Free project does not pause after 7 idle days; schedule a monthly `pg_dump` through the pooler connection string (Free has no backups) and a monthly glance at DB size vs 500 MB and storage vs 1 GB (D17). | Supabase, GitHub | 0 | `.github/workflows/keepalive.yml`. |
| 3.7 | Microsoft Store: storedeveloper.microsoft.com > "Get started for free" > Individual developer; government ID + selfie on the phone; confirm Israel is in the country list; reserve the app name "DeskIT"; note the Package/Publisher identity Partner Center assigns; write the one-paragraph runFullTrust justification (global push-to-talk hook, screen-capture keys, local listener for the phone) and the listing assets (D20; `research/signing` "What the owner must do" 1-3). | partner.microsoft.com | 0 (individual fee waived) | Publisher identity into the MSIX manifest; the justification text into the submission (chapter 10). |
| 3.8 | Do NOT open an Azure pay-as-you-go subscription for Artifact Signing: individual validation is US/Canada only and would fail (`research/signing` "What the owner must do" 6). | — | avoids a wasted charge | — |

### Phase 4 — Phone

| # | Task | Where | Cost | Copy back / unblocks |
|---|---|---|---|---|
| 4.1 | Generate the Android release keystore once and back it up in two places; decide at Play enrolment whether to hand Play his own key via PEPK or accept Google-generated keys (D22; `research/android` "What the owner must do"). | his PC | 0 | Keystore path and alias into the local signing config only, never the repo (chapter 12). |
| 4.2 | Google Play personal account: US$25 registration with a card in his legal name, government ID, Play Console phone-app device verification; create the app entry (this also registers the package for Android developer verification for sideloading before the 2027 enforcement); accept the Play Developer Distribution Agreement (D22, Part B decision 6). | play.google.com/console | US$25 once | Play listing URL into `/api/version` `playUrl` (D21; chapter 12). |
| 4.3 | Closed test: 12 testers for 14 days (the same early adopters who install the PC app), then the production-access questionnaire; fill the Data safety form (audio: collected, optional, ephemeral, encrypted in transit, not shared, user-deletable; typed text not collected by the developer) with the privacy policy URL (D22). | Play Console | 0 | Data safety answers recorded in chapter 12's table. |
| 4.4 | Publish the release-signed universal APK on GitHub Releases (v1 delivery) so the PC's Phone page QR has a target (D22). | github.com | 0 | APK URL into `/api/version` `apkUrl`. |

### Phase 5 — Trust and reach

| # | Task | Where | Cost | Copy back / unblocks |
|---|---|---|---|---|
| 5.1 | Apply to SignPath Foundation (Apache-2.0 only): the application form, MFA on the GitHub account, a published code-signing policy page, the CI build they sign. Fallback: Certum Open Source Code Signing in the Cloud (D20; `research/signing` "What the owner must do" 5). | signpath.org / shop.certum.eu | 0, fallback EUR 49 | Signing step into the release workflow (chapter 10). |
| 5.2 | Buy a domain for e-mail linking and create a Resend account; verify the domain (DKIM/SPF/DMARC records); Supabase > Authentication > SMTP: host `smtp.resend.com`, port 465, user `resend`, password = the Resend API key, sender `login@<domain>`; set the Magic Link template to the 6-digit token, 10-minute expiry; raise the e-mail rate limit (D17; `research/supabase` "What the owner must do" 4, 6). | a registrar, resend.com, Supabase | ~USD 10/yr, the one likely recurring non-free item | — |
| 5.3 | Optional Google sign-in: Google Cloud console > OAuth consent screen (External, app name, support e-mail, privacy policy URL) > OAuth client of type Web application with the redirect URI Supabase shows; paste client id and secret into Supabase; add `http://127.0.0.1:*/**` to the redirect list (D17). | console.cloud.google.com | 0 | — |
| 5.4 | IzzyOnDroid: once Apache-2.0 is in place, add Fastlane metadata and request inclusion (D22; `research/android` "What the owner must do"). | izzyondroid.org | 0 | `android/fastlane/metadata/`. |
| 5.5 | Optional: the one-hour privacy-lawyer review of the policy and the PPL tier reading (D25; `research/legal` "What the owner must do" 7). | — | the only likely paid legal item | Revised policy text. |

### Recurring, after launch

| Cadence | Task | Source |
|---|---|---|
| Per release | Tag, notes, assets, SHA-256, VirusTotal link, `latest.json`; winget PR; Store submission with its 1-3 day certification | D20, D21; chapter 11 |
| Weekly | The keep-alive cron runs on its own; glance that it is green until real users make it redundant | D17 |
| Monthly | `pg_dump`; DB and storage size check; retention script for reports older than 12 months and idle anonymous accounts older than 12 months | D17 |
| Saturday | The routine reads `problems\inbox\` via `dev/inbox.py` and pushes replies back as `report_replies` rows | D15; chapter 7 |
| On provider terms change | Bump the consent card `text_version` for the Gemini or Groq notice | D11 |
| Yearly | Domain renewal; SignPath or Certum certificate validity | D20, D17 |

### Cost summary

| Item | Amount | When |
|---|---|---|
| Everything in phases 0-3 | 0 | — |
| Google Play registration | US$25 once | phase 4 |
| Domain for e-mail linking | ~USD 10 per year | phase 5 |
| Certum OSS certificate (only if SignPath declines) | EUR 49 | phase 5 |
| Privacy-lawyer hour (optional) | one consultation | any time after launch |

## B. Open decisions with recommendation and consequence

These are D29's eight questions. Each row is a decision only the owner can take; the coder proceeds
on the recommendation unless told otherwise, and the phase column says when the choice stops being
reversible.

| # | Decision | Recommendation | If the owner chooses otherwise | Must be settled by |
|---|---|---|---|---|
| 1 | Licence: Apache-2.0 vs FSL-1.1-Apache-2.0 | Apache-2.0 + `TRADEMARK.md` (D23) | FSL keeps the source readable and blocks a competing DeskIT product, but forfeits SignPath, IzzyOnDroid and Certum OSS: the Windows build stays unsigned forever or costs EUR 49-400 per year, and the APK has no F-Droid-style listing (`arch-B §14`; `research/legal`). AGPL is rejected outright for NVIDIA-wheel friction and workplace fear. | Phase 0, before the first public commit |
| 2 | Public name and identity | Keep "DeskIT", reserve the trademark, package id `io.github.massifapp.deskit` (D22, D23) | A different name means new Store and Play reservations and a new package id; the package id is the one string that can never change after the first outside install. | Phase 0 for the id; phase 3 for the Store name |
| 3 | Store timing | Submit in phase 3 (D20) | Skipping the Store leaves non-technical users with the SmartScreen "More info > Run anyway" step and no path on Smart App Control machines; GitHub + winget then stays the only channel and the SignPath application moves up to phase 3. | Phase 3 |
| 4 | Accounts: anonymous-first vs e-mail from day one | Anonymous sign-in with Turnstile, e-mail linking later (D17) | E-mail from day one needs custom SMTP, which needs the domain (~USD 10/yr) and Resend in phase 3 instead of phase 5, and puts e-mail addresses in the database from the first user, which moves the PPL tier reading closer to the lawyer question. This is also the forced fallback if phase-0 check 0.7 finds anonymous sign-in unavailable on Free. | Phase 3 |
| 5 | Whether the Saturday routine keeps processing strangers' reports with Claude under his account | Yes, disclosed in the privacy policy as "Anthropic PBC when the developer processes reports with AI tools under his own account" (D25) | Reading reports by hand removes the disclosure and the recipient from the policy but makes every report a manual task; the routine's `dev/inbox.py` contract is the same either way (chapter 7). | Phase 2 (policy text) |
| 6 | Google Play in phase 4 vs GitHub APK only | Pay the US$25 (D22) | GitHub-only saves US$25 but leaves the phone app without the developer verification that sideloading will require from 2027, and without a Play listing non-technical users can find; the Data safety and closed-test work disappears with it. | Phase 4 |
| 7 | Buy a domain for e-mail linking | Yes, phase 5 (D17) | Without a domain there is no custom SMTP, so accounts stay anonymous only: a user who reinstalls Windows loses the link to their earlier reports and replies, and settings sync (phase 5) has no way to identify the same person on a second PC. Brevo's verified-sender path without a domain is untested (`arch-B §14`). | Phase 5 |
| 8 | Whether the English detector stays a feature | Optional, offered only on the GPU tier (D13) | Keeping it everywhere costs every user +1.6 GB of disk and, on GPU, +1.6 GB of VRAM; dropping it entirely removes the automatic Hebrew/English switch that the owner uses today. | Phase 2 (wizard copy) |

## C. Seed of the Hebrew summary

The owner reads a Hebrew summary; this section is what it must say, in English, for translation.
Ten lines, in the order the owner should act.

1. The app becomes a normal per-user Windows program: one folder for the install, one folder under
   `%LOCALAPPDATA%\DeskIT` for everything personal, deletable from inside the app.
2. Your own machine keeps working exactly as today: a `portable.txt` file in the checkout keeps the
   old layout and all the owner-only tools; nothing migrates unless you run `--migrate` yourself.
3. Before the first public commit: choose the licence (Apache-2.0 recommended), delete and re-create
   your Gemini, Groq and Cerebras keys, and decide whether to publish the repo with a fresh history
   because the tailnet host name sits in a tracked Android source file.
4. Strangers bring their own API keys; the keys go into Windows Credential Manager and the app can
   prove, in five ways a sceptic can check, that they never reach you.
5. The first run downloads the Hebrew model (1.62 GB) with a progress bar, detects the graphics card,
   and gets the user to a dictated sentence with at most four decisions.
6. The install is a per-user Inno Setup installer with embedded Python, on GitHub plus winget first;
   the Microsoft Store comes in phase 3 and needs your free individual account with ID verification.
7. Problem reports become one line plus a preview of exactly what is sent, through a free Supabase
   project you create by clicking through the dashboard once; replies come back to the same card.
8. The phone keyboard pairs over the user's own Wi-Fi with a QR; Google Play costs US$25 once and is
   the only planned payment before phase 5.
9. Phase 5 adds free code signing (SignPath, Apache only), e-mail accounts (needs a ~USD 10/yr
   domain) and settings sync.
10. Eight decisions are yours alone; the plan proceeds on the recommendations in Part B unless you
    say otherwise, and the licence and the package id are the two that cannot be undone.

## Acceptance

- Every item in D28 appears in Part A with a phase, a site or console, a cost and a "copy back"
  cell; every item in D29 appears in Part B with the recommendation from `decisions.md` and the
  consequence of the alternative.
- Every cost row is 0 except the four named in the cost summary; no row in the plan elsewhere
  introduces a cost that this chapter does not list.
- Each phase's block can be handed to the owner on its own when that phase starts (chapter 15) and
  contains nothing the coder could do instead.
- Part C, translated, lets the owner act on phase 0 without reading any other chapter.
- The two irreversible choices (licence before the first public commit, package id before the first
  outside install) are marked as such in Part B.

## Tests to add

The owner's hand-work leaves traces the build can check. These run in CI on the public tree and in
`dev/`, never in the user build (D15).

| Test | Asserts |
|---|---|
| `dev/test_public_tree.py::test_no_owner_strings_in_archive` | The `git archive` tree contains none of: the tailnet host `example`, the old package id `com.yoav.dictation`, `Yoav.DeskIT` as an AppUserModelID, a `.env` file, `questions.json`, `questions.lock`, `.agents/`, `portable.txt`, or any string matching the redactor's key patterns (D8, D22, D28). |
| `dev/test_public_tree.py::test_gitignore_covers_owner_files` | `.gitignore` lists `questions.json`, `questions.lock`, `.agents/` and `portable.txt` in addition to today's entries (D28 item "clean the tree"). |
| `dev/test_public_tree.py::test_legal_files_present` | `LICENSE`, `TRADEMARK.md`, `SECURITY.md`, `NETWORK.md`, `THIRD-PARTY-NOTICES.txt` and `VERSION` exist at the archive root and `LICENSE` names "Yoav Shimron" (D23, D24, D26). |
| `dev/test_public_tree.py::test_defaults_toml_is_neutral` | `app/defaults.toml` holds no absolute path, no microphone name, no x/y/scale key, `vocab.terms` empty, `server.enabled = false`, `backend = "local"` (D2, D6, D28). |
| `dev/test_supabase_config.py::test_only_publishable_key_ships` | The Supabase client configuration in the archive contains a key starting `sb_publishable_` and no string starting `sb_secret_`, `service_role` or `eyJ` (D17). |
| `dev/test_release_prereqs.py::test_release_assets_named` | For a given tag, the release carries `DeskIT-Setup-<version>.exe`, its `.sha256`, `latest.json` and, from phase 4, the universal APK, with `latest.json` version equal to `VERSION` (D21; the owner's per-release checklist). |
| `dev/test_migration_matches_dashboard.py::test_schema_equals_migration` | Run by the owner with `DESKIT_SUPABASE_SECRET` set: the live project's tables, columns, policies and bucket settings equal what `supabase/migrations/0001_init.sql` declares (D12 lock 3, task 3.3). |

## Open points

- **Git history.** D28 says "check git history for the tailnet name/token". The check is already
  answered for the host name: `android/app/src/main/java/com/yoav/dictation/Prefs.kt:25` is a tracked
  file, so `yoav.example.ts.net` is in the history of every commit since it was added. Deleting
  the constant (D22) cleans the tree but not the history. The owner must choose between publishing
  from a fresh single-commit history (simplest; loses public blame and the commit trail) and a
  history rewrite that strips the string; `decisions.md` does not choose, and the tailnet host is not
  a secret in the credential sense (it identifies a machine, not a key), so either is defensible. This
  belongs to phase 0 task 0.5.
- **Owner's own migration.** D4 makes `--migrate` explicit and never automatic and D28 keeps
  `portable.txt` in his checkout. The decisions do not say whether the owner ever moves his own
  machine to the product layout; until he does, the product layout is exercised only by the clean VM
  and by the AI coder's tests, never by daily use. Not a contradiction; a note for the risk register
  (chapter 15).
- **Anonymous sign-in on Free.** D17 and D29(4) both depend on phase-0 check 0.7; if it fails, tasks
  3.4 and 5.2 swap phases and the domain cost moves to phase 3. Recorded here so the owner sees the
  dependency before buying anything.


---

# A. Appendix: file-by-file change inventory

This appendix is the lookup table for the implementer: every file in the DeskIT repo today with a verdict, the call sites the subsystem maps cite for the files that change, and the decision plus chapter that drives the change. It repeats no rationale; the chapters do that. Verdicts: **keep** (ships unchanged or with cosmetic edits), **change** (ships after the listed edits), **dev/** (stays in the repo, moves under `dev/`, excluded from the build), **delete** (removed from the repo or never committed), **excluded** (stays in the tree, kept out of the build by the D15 manifest). Source of the file list: a read-only directory listing of the repo root, `transcribers/`, `skin/` and `android/` on 2026-09-17; line counts from the same listing.

Chapter numbers cited: 3 layout (D1-D5), 4 data (D6, D8, D9), 5 cloud proof (D7, D10-D12), 6 hardware (D13-D14), 7 owner machinery (D15-D16), 8 Supabase (D17), 9 screens (D18), 10 packaging (D19-D20), 11 updates (D21), 12 Android (D22), 13 legal (D23-D25), 14 guide (D26), 15 roadmap (D27), 16 owner to-do (D28-D29).

## Existing product files

### Python modules in the repo root

| File (lines) | Verdict | Call sites the maps cite | Driver |
|---|---|---|---|
| `main.py` (6380) | change | Every store built under `APP_DIR` (`main.py:324-401, 487, 657-697, 2084, 3525, 3862, 5654, 5661`); `APP_ID = "Yoav.DeskIT"` (`main.py:67`); config write-backs of card positions (`main.py:623-742, 1420-1505`); `cues.ensure_files()` bare at start (`main.py:6361`); `PhoneServer` wiring (`main.py:771-781`); phone transcribe writes `recent/` (`main.py:2347-2404`); status payload carries the token URL (`main.py:1760`); `_problem_shot` grabs all screens (`main.py:3757-3782`); CLI flags `--study/--review/--benchmark` (map/packaging) | D1, D2, D4, D5 (ch. 3); D8 (ch. 4); D15, D16 (ch. 7); D22 (ch. 12); `--migrate` and `--verify` flags (ch. 3, 5) |
| `config.py` (2432) | change | `backend` default `"gemini"` (`config.py:1219`); `set_values` regex line editor limited to existing sections (`config.py:2285, 2340-2432`, limit at `2394-2398`); `SetupConfig` marker docstring (`config.py:242-256`); `[review] x/y/scale` written by the card (`config.py:1055-1058`); `ServerConfig` (`config.py:1112-1125`) | D2 three layers, D5 port fall-through (ch. 3); D6 defaults (ch. 4); D7 `[privacy]` section (ch. 5); D14 tier defaults (ch. 6) |
| `settings.py` (1445) | change | Reads `config.toml` for the page (`settings.py:187-269`); never writes (`52-55`); Phone tab rows with stale `server.host` wording (`settings.py:618-626, 655, 1143-1145, 1374-1376`) | D2: read `app\defaults.toml`, hide `state.json` keys (ch. 3); D18 new tabs Keys / Your data / Privacy (ch. 9); D26 generated Settings chapter (ch. 14) |
| `apikey.py` (100) | change, becomes a thin shim over `secrets.py` | Env first then `APP_DIR/.env` (`apikey.py:18-19, 24-26, 29-34, 37-53, 57-63`); `GOOGLE_API_KEY` alias (`apikey.py:24`) | D3 Credential Manager, `DESKIT_` prefix, `.env` only in DEVELOPER mode (ch. 3); D12 lock 1 (ch. 5) |
| `transcribers/__init__.py`, `base.py`, `fake.py` | keep | `get_transcriber(cfg)` (map/core) | `fake` stays as the "try the keys" backend (map/core) |
| `transcribers/gemini.py` | change | `genai.Client` built at construction (`gemini.py:61-73`); key from `apikey.find_api_key()` (`gemini.py:66`); whole WAV sent (`gemini.py:106-110`) | D7 `privacy.allowed("cloud_audio")` in the constructor (ch. 5); D12 egress through `net.py` (ch. 5); D19 `google-genai` dropped, REST through `net.py` (ch. 10) |
| `transcribers/local_whisper.py` | change | `_register_cuda_dlls()` (`local_whisper.py:50-79`); device ladder + warm-up (`396-417`); eager detector (`420-428`) | D13 model from `DATA_DIR\models`, `HF_HUB_OFFLINE` (ch. 6); D14 pack DLL dirs, tier quantisation, detector optional (ch. 6) |
| `recorder.py` (440), `rolling.py` (378), `cleanup.py` (176), `hotkey.py` (1360), `injector.py` (933), `singleton.py` (170), `summary.py` (175), `widgets.py` (683), `hint.py` (180), `popup.py` (4256), `overlay.py` (4286), `shelf.py` (586), `shelf_card.py` (1032), `gemini_pool.py` (149), `punctuate.py` (366), `cues.py` (344) | keep (small edits) | `rolling.py:16` RTX tuning comment and `rolling.py:229-240` timeout become tier-aware (ch. 6); `cues.ensure_files()` targets the pre-rendered `APP_DIR\cues` and never writes at start (`cues.py:21, 279-303`, D1); `hint.py:95-98` `classic` branch guard removed; `punctuate.py:184, 230-297` lazy builders call `privacy.allowed` (D7); `overlay.py` positions go to `state.json` via `main.py` (D2) | D1, D2 (ch. 3); D6, D7 (ch. 4, 5); D14 (ch. 6) |
| `spool.py` (120) | change | `Spool.save/_trim` (`spool.py:69, 79-98, 112-122`) | D1 `audio\recent`, `audio\pending` under `DATA_DIR`; D6 `keep_audio = 20` (ch. 3, 4) |
| `control.py` (265) | change | Pipe name `\\.\pipe\DeskIT.control` (`control.py:43, 91`) | D5 per-session pipe name (ch. 3) |
| `launch.py` (81) | change | Picks `.venv\Scripts\pythonw.exe` first (`launch.py:36-47`) | D19 `python\pythonw.exe` beside `app\` (ch. 10) |
| `firstrun.py` (711) | change (rewrite of the flow, keep the meter and device code) | `needed()` reads the `.setup-done` marker (`firstrun.py:65, 668-677`); writes `audio.device` via `set_values` (`636-640`); opens `ms-settings:privacy-microphone` (`197`); loads the real model inside the wizard (`304-314`) | D18 seven-step wizard, `setup_done` in `state.json` (ch. 9); D13, D14 download and tier steps (ch. 6) |
| `server.py` (834) | change | `TOKEN_FILE`, `APK`, `APK_GRADLE` constants (`server.py:66-70`); token generation (`97-113`); `tailscale.exe` shell-out (`116-165`); bind (`638-641`); logs host only (`653-654`) | D22 TLS cert, fingerprint pairing, `/app.apk` removed, `/health` returns `{ok, version}` (ch. 12); D3 token in DPAPI (ch. 3); D5 port fall-through (ch. 3) |
| `translate.py` (606) | change | `GeminiTranslator` (`translate.py:112-179`), `CerebrasTranslator` (`377-525`), `GroqTranslator` (`528-556`), `GROQ_URL` (`367`), `USER_AGENT` (`373`), request body (`450-470`), Ollama chat (`310-333`) | D7 gate in every cloud constructor; D12 all HTTP via `net.py` (ch. 5); Cerebras backend removed with its key (D10, ch. 5) |
| `polish.py` (464) | change | Backend order (`polish.py:285-324`); glossary in the prompt (`144-179, 279-283`); warms every backend at start (`364-388`) | D6 `prefer = "ollama"` (ch. 4); D7 consent text names the glossary (ch. 5); no warm-up of a gated backend |
| `lookup.py` (954) | change | `Cache` at `APP_DIR/lookup_cache.json` (`lookup.py:440-533, 627-629`); Gemini fallback rules | D1 cache to `DATA_DIR`; D6 `cold_to_gemini = false`; D9 "Delete lookups" (ch. 3, 4) |
| `visual_qa.py` (4348) | change | `GroqVision` key and URL (`visual_qa.py:786-794, 836, 863-867`); `GeminiVision` (`905-960`); `Chain._builders()` gate pattern (`971-1075`); grep-style test precedent (`173-175`) | D7 gate reuses the existing pattern (ch. 5); D12 egress lock (ch. 5); `text_pil`/`encode_jpeg` stay the shared Hebrew painter (map/owner) |
| `vocab.py` (540) | change | Store beside the app (`vocab.py:275-289`); plain `write_text` save (`291-301`); no forget API (map/learning) | D1 path; D9 `Vocab.forget` + atomic save (ch. 3, 4) |
| `history.py` (300) | change | `LOG = APP_DIR / "transcripts.log"` (`history.py:27-28, 99-109`) | D1 `DATA_DIR\logs`; D6 `[history] keep_days` (ch. 3, 4) |
| `review.py` (1307), `review_card.py` (448) | change | `review.json` + `review.lock` beside `vocab.json` (`review.py:661-861`); Groq reader (`441-520`); glossary payload (`635-650`) | D1 path; D6 second reading only on CUDA, `[review] keep_audio = 3`, `llm_per_day = 0` until consent (ch. 4, 6); D7 gate (ch. 5) |
| `study.py` (784) | change | `Corpus` under `corpus/` (`study.py:482-529`); `Adjudicator` to Groq (`284-340`) | D1 path; D6 `study.enabled` off, `corpus_keep = 0` (ch. 4); D7 gate (ch. 5) |
| `reading.py` (721) | change | `corpus/read/` never trimmed (`reading.py:60-63`); reads `vocab.json` by path (`186-204`); `Writer` to Groq (`397-503`) | D1 path; D6 Read-aloud tab hidden unless DEVELOPER or `corpus_keep > 0` (ch. 3, 4) |
| `dashboard.py` (8548) | change | Reads every store by `APP_DIR` path (`dashboard.py:213-215, 281, 457-465, 1902, 3625-3639, 3822, 3879, 3941, 5519, 6479, 6514`); git block (`838-946`), `PUSH_LOG` (`890`); `_problems_enabled()` (`793-807`); token URL shown and copied (`7664-7690, 8091-8099`); `set_values` writes (`7813`) | D1, D2 (ch. 3); D15 git card, Stop-tests, `[tests]` rows, questions removed or DEVELOPER-gated (ch. 7); D16 report v2 (ch. 7); D18 Home tier line, Keys, Your data, Update card (ch. 9); D22 pairing QR replaces the URL (ch. 12) |
| `problems.py` (1071) | change | `record()` (`problems.py:899-928`), `env()` stamps branch + python (`274-302`), `dictation()` reads `recent\` (`331-353`) | D15 `env()` stamps `version, os_build, gpu, tier`; D16 outbox, redactor, `remove(purge=True)` (ch. 7); D8 (ch. 4) |
| `problem_card.py` (654) | change | Headless Pillow painter (map/owner) | D16 attachment toggles with byte sizes, "Send to the developer" checkbox (ch. 7) |
| `notify.py` (1430), `notify_card.py` (692) | change | `Store` writes `notify.json` (`notify.py:250-361`) | D1 path; D15 `notify.json` bodies never attach to reports, `notify.log` rotates at 512 KB (ch. 7) |
| `notify_hook.py` (548) | change | Reads `server_token.txt` (`notify_hook.py:54`); `--install-hook` writes absolute repo paths into `~/.claude/settings.json` (`53, 395-452`) | D15 "Connect Claude Code" switch, installed `pythonw` path, `--uninstall-hook` (ch. 7); D3 token from DPAPI (ch. 3) |
| `notify_watch.py` (605) | change | Copies `wpndatabase.db` to a fixed `%TEMP%\hd-notify-watch.db` (`notify_watch.py:144-147, 405-424`) | D15 `watch = "off"`, only when a `Claude_*` package exists; D5 per-process temp name (ch. 7, 3) |
| `awake.py` (1336) | change | `SetThreadExecutionState` hold (`awake.py:178-233`); power-plan timeouts (map/owner); `nvidia-smi` wrapper (`642-646`) reused by the tier probe | D15 `hold = false` asked once, `vitals_minutes = 0`, `claude.exe` probe removed (ch. 7); D14 probe (ch. 6) |
| `capture.py` (6707) | change | Default folder relative to the app (`tests.py:13595-13605`); defaults pinned (`tests.py:13718, 14897`) | D1 `FOLDERID_Pictures\DeskIT`, `FOLDERID_Videos\DeskIT`; D6 `always_save = false`, `audio = "off"`, `system_sound = false` (ch. 3, 4); D19 `av` in the Recording pack (ch. 10) |
| `keyboard.py` (623) | change, renamed `keycaps.py` | Reads `config.toml` when no status (`keyboard.py:296-300`); fonts via `ImageFont.truetype` (`409-415, 436-440`) | D19 name collision with the dropped PyPI `keyboard` package (ch. 10) |
| `fonts.py` (169), `ui.py` (1866) | keep | Private font registration (map/ui); icon paths (`ui.py:356-377`) | Fonts and icon read from `APP_DIR` (D1), no write |
| `versions.py` (66) | change, replaced by `version.py` | `git rev-parse` in `APP_DIR` (`versions.py:37, 52-66`) | D15, D21 `VERSION` file, branch only with `.git` (ch. 7, 11) |
| `questions.py` (719), `answer_card.py` (698) | dev/ | `questions.json` store (`questions.py:76`); `answer_card` imports `problem_card` (`answer_card.py:93`) | D15 questions do not ship (ch. 7) |
| `nightly.py` (887) | dev/ | Lock/marker under `problems\nightly\` (`nightly.py:125-131`); topmost Tk ask window (`540-622`) | D15 (ch. 7) |
| `tests.py` (29140) | change, split | Privacy test (`tests.py:10804-10836`); phone tests with `yoav.example.ts.net` fakes (`tests.py:3931`); nightly/owner tests (`tests.py:25281, 28490-28510`) | D15 product tests stay in `tests.py`, ops tests to `dev/tests_ops.py` (ch. 7); both excluded from the build (D15 manifest) |
| `tests_quiet.py` (221) | dev/ | Second-desktop runner (`tests_quiet.py:8-13, 46-64`) | D15 (ch. 7) |
| `make_icon.py` (213), `audio_check.py` (55), `install_fonts.py` (86) | dev/ | `make_icon.py` writes `icon.ico/.png` at commit time (map/ui); `install_fonts.py` "no longer required" (map/packaging) | D15 manifest (ch. 7) |

### Non-Python files and folders in the repo root

| File | Verdict | Notes / call sites | Driver |
|---|---|---|---|
| `config.toml` (1794 lines) | change, becomes `app\defaults.toml` | Tracked in git and live at once (map/core, map/packaging); owner values: `[server] enabled = true` (`config.toml:1297-1308`), `[capture]`/`[camera]` absolute paths (`config.toml:722-1015`), `[gemini]` (`1574-1584`) | D2 scrub, comments intact (ch. 3); D6 neutral defaults (ch. 4); D28 owner hand-work (ch. 16) |
| `requirements.txt` | change | Pins for the wheelhouse (map/packaging pip table) | D19 base / GPU / Recording / Skin sets, `packs/*.lock` (ch. 10) |
| `.env` | delete from the owner's tree after `--migrate`; never ships | Read at `apikey.py:37-53`; gitignored (`.gitignore:1`) | D3, D28 rotate keys first (ch. 3, 16) |
| `server_token.txt` | delete (replaced by `DATA_DIR\secrets\phone.bin`) | `server.py:69, 97-113`, `notify_hook.py:54`; gitignored (`.gitignore:41`) | D3, D22 (ch. 3, 12) |
| `.setup-done` | delete (marker becomes `state.json` `setup_done`) | `firstrun.py:65, 683-688`; gitignored (`.gitignore:50`) | D2 (ch. 3) |
| `DeskIT.vbs`, `Dashboard.vbs`, `Stop DeskIT.vbs` | delete | Hard-code `<folder>\.venv\Scripts\pythonw.exe` (`DeskIT.vbs:5-8`, `Dashboard.vbs:3-7`, `Stop DeskIT.vbs:6`) | D19 shortcut target `python\pythonw.exe app\deskit.pyw`; portable mode keeps the owner's launch working without them (ch. 10, 3) |
| `README.md` | change | Phone walkthrough assumes Tailscale + `/app.apk` (`README.md:3371-3524`) | D22, D26: the guide tree takes the user-facing parts; README becomes the contributor front page (ch. 12, 14) |
| `AGENTS.md`, `SKIN.md`, `VISUAL_QA_PLAN.md`, `PARALLEL_FEATURES_PLAN.md` | excluded | Developer briefs (`VISUAL_QA_PLAN.md:3-4, 129-140` still cite retired branches, map/owner) | D15 manifest (ch. 7) |
| `ch.html`, `cp_play.html`, `np_passport.html`, `pp.html` | excluded (owner decides delete) | Untracked scratch pages in the root | D15 manifest `*.html` (ch. 7) |
| `weekly_review.ps1`, `nightly_tests.ps1`, `install_nightly_task.ps1` | dev/ | `weekly_review.ps1:46-103, 269-279`; `nightly_tests.ps1:40, 43, 145`; `install_nightly_task.ps1:55-66, 88-118` | D15 (ch. 7) |
| `.gitignore` | change | Add `questions.json`, `questions.lock`, `.agents/`, `vocab.json.bak-*`, `*.html`, `dist/`, `build/`, `wheelhouse/` | D28 (ch. 16) |
| `.claude/`, `.agents/` | excluded | `.claude/commands/weekly-reports.md` is the Saturday routine (map/owner) | D15 manifest; `.claude/` moves to `dev/claude/` (ch. 7) |
| `.git`, `.venv`, `__pycache__` | keep on the owner's machine; never in the build | `DEVELOPER = .git present` (D4) | D4, D19 |
| `icon.ico`, `icon.png`, `fonts/`, `cues/`, `skin/` (16 modules) | keep (ship read-only in `APP_DIR`) | `ui.py:356-377`, `skin/boot.py:129-131`, `dashboard.py:88-89`; `skin/preview.py` and `skin/record.py` are dev tools that write files (map/ui) | D1; D19 `skia-python` becomes the optional Skin pack, `skin/preview.py` and `skin/record.py` excluded (ch. 3, 10); D24 Rubik OFL notice (ch. 13) |
| `android/` (Gradle project + `tools/`) | change (source excluded from the Windows build) | `Prefs.kt:25` owner MagicDNS default; `app/build.gradle.kts:7-20` id `com.yoav.dictation`, `versionCode 12`; `strings.xml:83, 99, 115` name Tailscale; `local.properties` machine-local; `tools/emu.py:19-24, 75` and `tools/fake_pc.py:13, 22` absolute owner paths | D22 pairing, pinning, package id (D29-2), APK as a Release asset; D21 version from `VERSION` (ch. 12, 11); `android/tools/` moves to `dev/` |
| Live stores in the root: `vocab.json`, `vocab.json.bak-*`, `review.json`, `review.lock`, `problems.json`, `problems.lock`, `problems.md`, `problems/`, `questions.json`, `questions.lock`, `notify.json`, `notify.log`, `lookup_cache.json`, `awake_state.json`, `app.log*`, `transcripts.log*`, `night.log`, `awake.log`, `recent/`, `pending/`, `corpus/`, `captures/` | delete from the tree (moved to `DATA_DIR` by `--migrate` on the owner's machine) | Written by the modules above; `problems.md` digest removed outright (D16) | D1, D4, D9 (ch. 3, 4); `vocab.json.bak-*` and `questions.*` in the manifest (D15) |

## Files that move to dev/

`dev/` is a folder inside the public repo (the owner's checkout keeps working because `DEVELOPER` and portable mode are detected from `.git` and `portable.txt`, D4). Nothing under `dev/` enters the build tree (D15 manifest, section below); everything under it may keep absolute owner paths, but the `git mv` is the moment to replace `C:\Users\shimr\...` with `$PSScriptRoot` / `Path(__file__)` where the maps flag them.

| Today | Under `dev/` | What it does there | Edits on the way | Driver |
|---|---|---|---|---|
| `nightly.py`, `nightly_tests.ps1`, `install_nightly_task.ps1` | `dev/nightly.py`, `dev/nightly_tests.ps1`, `dev/install_nightly_task.ps1` | Owner's nightly test run and its scheduled task | `nightly_tests.ps1:40` typed fallback path becomes `$PSScriptRoot\..`; `nightly.py:125-131` markers under `DATA_DIR\problems\nightly` when not portable | D15 (ch. 7) |
| `weekly_review.ps1`, `.claude/commands/weekly-reports.md` | `dev/weekly_review.ps1`, `dev/claude/commands/weekly-reports.md` | The Saturday routine (owner-side only) | Reads `problems\inbox\<user_id>\` filled by `dev/inbox.py`; `weekly_review.ps1:46-103` `claude.exe` lookup unchanged | D15, D17 (ch. 7, 8); D29-5 |
| `questions.py`, `answer_card.py` | `dev/questions.py`, `dev/answer_card.py` | The routine's question store and the owner's answer card | `answer_card.py:93` keeps importing `problem_card` from the product package | D15 (ch. 7) |
| `tests.py` (ops half), `tests_quiet.py` | `dev/tests_ops.py`, `dev/tests_quiet.py` | Nightly/owner tests (`tests.py:25281, 28490-28510`), the second-desktop runner (`tests_quiet.py:8-13`) | Product `tests.py` stays in the root and is excluded from the build; ops tests import from it | D15 (ch. 7); D27 phase 1 "test split" |
| `make_icon.py` | `dev/make_icon.py` | Commit-time icon generator (map/ui) | none | D15 |
| `audio_check.py` | `dev/audio_check.py` | Device probe script | none | D15 |
| `install_fonts.py` | `dev/install_fonts.py` | Per-user font install, "no longer required" (map/packaging) | none; kept for the owner's other tools | D15 |
| `android/tools/emu.py`, `android/tools/fake_pc.py` | `dev/android/emu.py`, `dev/android/fake_pc.py` | Headless emulator driver and fake PC server | `emu.py:19-24, 75` and `fake_pc.py:13, 22` absolute paths become env-driven (`ANDROID_SDK_ROOT`, repo-relative) | D15, D22 (ch. 12) |
| `skin/preview.py`, `skin/record.py` | `dev/skin/preview.py`, `dev/skin/record.py` | Skin dev tools that write files (map/ui) | import the product `skin` package | D15, D19 (ch. 10) |
| (new) | `dev/inbox.py` | Pulls consented `problem_reports` columns from Supabase with the secret key into `problems\inbox\<user_id>\`; writes `report_replies` | new file, see New files | D15, D17 (ch. 7, 8) |
| (new) | `packaging` (sibling of `dev/`, the name chapter 10 uses) | The Inno script, `manifest.txt`, `python-embed.sha256`, `python311._pth`, `build_local.ps1`, the notices generator | new files, see New files | D19, D24 (ch. 10, 13) |

## Files that are deleted or excluded from the build

Two different mechanisms. **Deleted** means the file leaves the repo (or is never committed): the working tree on the owner's machine drops it after `--migrate` (D4) and `.gitignore` keeps it out. **Excluded** means the file stays in git but the build manifest (`packagingmanifest.txt`, D15) leaves it out of `app\`; the `MANIFEST.sha256` produced by the build (ch. 10) therefore never lists it, and the D12 lock-5 reproducibility test fails if one leaks in.

### Deleted

| File | Why | Where its job goes | Driver |
|---|---|---|---|
| `.env` | plaintext keys beside code | Credential Manager via `secrets.py`; `.env` reader survives only in DEVELOPER/portable mode | D3, D28 |
| `server_token.txt` | plaintext bearer beside code (`server.py:69`) | `DATA_DIR\secrets\phone.bin` (DPAPI) | D3, D22 |
| `.setup-done` | marker beside code (`firstrun.py:65`) | `state.json` `setup_done` | D2 |
| `DeskIT.vbs`, `Dashboard.vbs`, `Stop DeskIT.vbs` | venv-bound launchers | Start-menu shortcuts written by the installer; `deskit.pyw` entry | D19 |
| `versions.py` | git-only version source | `version.py` + `VERSION` | D15, D21 |
| `problems.md` | owner digest, never user-facing | removed with the "Open problems.md" button | D16 |
| Live stores in the root (`vocab.json`, `review.json`, `problems.json`, `notify.json`, `lookup_cache.json`, `awake_state.json`, `*.log*`, `recent/`, `pending/`, `corpus/`, `problems/`, `captures/`, `*.lock`, `vocab.json.bak-*`, `questions.json`, `questions.lock`) | personal data in the code folder | `DATA_DIR` (D1) after `--migrate`; the four `vocab.json.bak-*` copies are the owner's to keep elsewhere | D1, D4, D28 |
| `ch.html`, `cp_play.html`, `np_passport.html`, `pp.html` | untracked scratch | owner's call; the manifest excludes `*.html` regardless | D15 |

### Excluded from the build (the D15 manifest)

The manifest is an allow-list plus deny-list read by the build job (ch. 10). Deny patterns, verbatim from D15 with the additions this appendix needs: `weekly_review.ps1`, `.claude/`, `.agents/`, `questions.py`, `nightly*.py`, `nightly*.ps1`, `install_nightly_task.ps1`, `tests*.py`, `make_icon.py`, `audio_check.py`, `install_fonts.py`, `android/` (source), `AGENTS.md`, `*_PLAN.md`, `SKIN.md`, `*.html`, `vocab.json.bak-*`, plus `dev/`, `packaging/`, `supabase/`, `.github/`, `docs/` (guide sources), `skin/preview.py`, `skin/record.py`, `answer_card.py`, `__pycache__/`, `.git*`, `.venv/`, `portable.txt`, `*.log*`, `*.lock`, `*.json` in the root (stores), `requirements*.txt` (the lock files ship under `packs/` instead).

| Pattern | What it catches today | Driver |
|---|---|---|
| `tests*.py` | `tests.py` (29140 lines), `tests_quiet.py` | D15 |
| `nightly*.py`, `nightly*.ps1`, `install_nightly_task.ps1`, `weekly_review.ps1` | the owner's scheduled tasks | D15 |
| `questions.py`, `answer_card.py` | the Saturday routine's question side | D15 |
| `.claude/`, `.agents/` | `weekly-reports.md`, agent skills | D15, D28 |
| `android/` | Gradle project; the APK is a Release asset, not part of the Windows tree | D22 |
| `AGENTS.md`, `*_PLAN.md`, `SKIN.md`, `README.md`, `*.html` | developer documents; the user guide lives in `docs/` and on Pages | D15, D26 |
| `make_icon.py`, `audio_check.py`, `install_fonts.py` | commit-time and probe scripts | D15 |
| `skin/preview.py`, `skin/record.py` | skin dev tools (map/ui) | D15, D19 |
| `dev/`, `packaging/`, `supabase/`, `.github/`, `docs/` | repo-only trees | D15, D17, D19, D26 |
| root `*.json`, `*.log*`, `*.lock`, `vocab.json.bak-*` | any store the owner forgot to move | D1, D15 |

What the build **does** take: every other `*.py` in the root and `transcribers/`, `skin/` (minus the two tools), `defaults.toml`, `fonts/`, `cues/` (pre-rendered), `icon.ico`, `icon.png`, `LICENSE`, `NOTICE`, `THIRD-PARTY-NOTICES.txt`, `OFL.txt`, `NETWORK.md`, `SECURITY.md`, `TRADEMARK.md`, `VERSION`, `CHANNEL`, `packs/*.lock`, and the generated `MANIFEST.sha256` (D1, D19).

## New files

Grouped by where they live. "Ships" says whether the file is in `APP_DIR` after install (D1) or only in the repo. The owning chapter holds the contract; this table holds only the one-line purpose.

### Product modules (ship in `app\`)

| File | Owner | Purpose |
|---|---|---|
| `paths.py` | ch. 3 (D1, D4) | Decides `APP_DIR`, `DATA_DIR`, `PICTURES_DIR`, `VIDEOS_DIR` once per process; detects portable mode (`portable.txt`, `DESKIT_PORTABLE=1`, `.git`) and exposes `DEVELOPER`; every module imports its paths from here and nothing else builds a store path |
| `net.py` | ch. 5 (D12 lock 2) | The only module that imports `urllib.request`, `http.client`, `socket`, `ssl` (or `httpx`/`requests`); frozen `ALLOWED_HOSTS`; every call declares `purpose` and the secret's name; writes `network.log` (host, purpose, bytes, status, never bodies); refuses any host off the list before connecting |
| `secrets.py` | ch. 3 (D3), ch. 5 (D12 lock 1) | Credential Manager read/write/delete for `DeskIT/groq`, `DeskIT/gemini`; DPAPI files under `DATA_DIR\secrets\*.bin` for the Supabase session, the phone TLS key and phone tokens; the `DESKIT_*` env fallback; the `.env` reader only when `DEVELOPER` |
| `privacy.py` | ch. 5 (D7) | `allowed(kind)` over the `[privacy]` gates; `consent.json` read/write (`kind, text_version, when, app_version`); the withdraw hook that tears cloud clients down; the redactor from D8 (key-shaped strings, `#t=`, stored secrets) used by reports and `--diagnose` |
| `version.py` | ch. 11 (D21), ch. 7 (D15) | Reads `VERSION` (SemVer) and `CHANNEL`; derives the Windows 4-part version and the Android `versionCode`; reports the git branch only when `.git` exists; replaces `versions.py` |
| `sb.py` | ch. 8 (D17) | The single Supabase client: project URL + publishable key, anonymous sign-in, session in DPAPI via `secrets.py`, report upload from `problems\outbox\`, reply sync, `delete_me()` RPC; forbidden from importing anything but `net.py` for HTTP |
| `migrations.py` | ch. 3 (D2, D4) | Ordered numbered steps keyed by `config_version`; `--migrate` moves the legacy stores as a unit, imports `.env`, diffs `config.toml` into `settings.toml` + `state.json` |
| `deskit.pyw` | ch. 10 (D19) | Entry stub the shortcut targets (`python\pythonw.exe app\deskit.pyw`); sets `sys.path`, prepends pack DLL dirs, calls `main.main()` |
| `keycaps.py` | ch. 10 (D19) | Today's `keyboard.py` under a name that cannot shadow the PyPI package |
| `defaults.toml` | ch. 3 (D2), ch. 4 (D6) | Today's `config.toml` scrubbed of owner values and machine state, comments intact; the source of the generated Settings page and the guide's Settings chapter |

### Ship-level documents and data (in `APP_DIR`, read-only)

| File | Owner | Purpose |
|---|---|---|
| `VERSION` | ch. 11 (D21) | One line `MAJOR.MINOR.PATCH[-beta.N]`, shared by the Windows build, `version.py`, the Android Gradle script and the release workflow |
| `CHANNEL` | ch. 11 (D21) | One word, `stable` or `beta`, written by the build; the Update card reads it as the default for `[updates] channel` |
| `MANIFEST.sha256` | ch. 10 (D19), ch. 5 (D12 lock 5) | SHA-256 of every file the installer lays down; `--verify` re-hashes the install against it |
| `NETWORK.md` | ch. 5 (D12) | The human-readable copy of `ALLOWED_HOSTS`: each host, which feature uses it, under whose account, and which gate opens it |
| `SECURITY.md` | ch. 13 (D25), ch. 16 (D28) | How to report a vulnerability (contact e-mail), what is in scope, the disclosure window |
| `TRADEMARK.md` | ch. 13 (D23) | Reserves the DeskIT name, the dalet-as-desk mark and the icon under Apache-2.0 |
| `LICENSE`, `NOTICE` | ch. 13 (D23) | Apache-2.0 text with copyright "Yoav Shimron"; `NOTICE` carries the attribution lines Apache requires downstream |
| `THIRD-PARTY-NOTICES.txt`, `OFL.txt` | ch. 13 (D24) | Generated at build by `pip-licenses --with-license-file` plus the hand entries from D24; the Rubik OFL text beside the renamed cuts |
| `packs\gpu.lock`, `packs\recording.lock`, `packs\skin.lock` | ch. 6 (D14), ch. 10 (D19) | Pinned wheel lists (name, version, sha256) for the three on-demand packs; the pack installer feeds them to `pip install --target DATA_DIR\packs\<name>` with hashes required |
| `cues\*.wav` (pre-rendered) | ch. 3 (D1) | The 20 cue files rendered at build time so `cues.ensure_files()` never writes into `APP_DIR` |

### Repo-only: build, release, backend, guide

| File | Owner | Purpose |
|---|---|---|
| `packaging\DeskIT.iss` | ch. 10 (D20) | Inno Setup 6 script: `PrivilegesRequired=lowest`, per-user into `%LOCALAPPDATA%\Programs\DeskIT`, Hebrew + English pages, `CloseApplications=yes`, the "Remove my data too?" uninstall question (D9) |
| `packaging\manifest.txt` | ch. 10 (D19), ch. 7 (D15) | The allow/deny list from the previous section; the build refuses a tree that matches a deny pattern |
| `packaging\python-embed.sha256`, `packaging\python311._pth` | ch. 10 (D19) | Pinned hash of the python.org embeddable zip; the `_pth` that enables `Lib\site-packages` |
| `packaging\build_local.ps1` | ch. 10 (D19) | The owner's local mirror of the release job for a smoke build |
| `packaging\store\listing\` | ch. 10 (D20) | Store listing text, screenshots, the runFullTrust justification, the MSIX manifest and the 30-line launcher stub source |
| `.github\workflows\release.yml` | ch. 10 (D19-D20), ch. 11 (D21) | Tag-driven: wheelhouse from the lock files, embeddable Python by hash, `git archive` through the manifest, Inno build, `MANIFEST.sha256`, SHA-256 + build attestation, `latest.json`, winget manifest via `wingetcreate`, APK from the same `VERSION` |
| `.github\workflows\false-positive.yml` | ch. 10 (D20) | Scheduled VirusTotal scan of the latest installer and the Defender false-positive submission reminder |
| `.github\workflows\supabase-keepalive.yml` | ch. 8 (D17), ch. 16 (D28) | Cron ping that keeps the Free project from pausing |
| `.github\workflows\ci.yml` | ch. 15 (D27) | Product tests, the key-string test, the egress grep test, the manifest test on every push |
| `.github\ISSUE_TEMPLATE\bug.yml`, `config.yml` | ch. 14 (D26) | Issue form that asks for the redacted `--diagnose` output and the tier line; links to the guide |
| `latest.json` (release asset, generated) | ch. 11 (D21) | `{version, url, sha256, size, min_config_version, notes_url}` the Update card fetches from the latest release |
| `supabase\migrations\0001_init.sql` | ch. 8 (D17) | Tables `profiles`, `devices`, `settings_sync`, `vocab_sync`, `problem_reports`, `report_replies`, `deletion_requests`; RLS `to authenticated`; anon grants revoked; CHECK against key-shaped strings; `delete_me()` RPC |
| `supabase\README.md` | ch. 8 (D17) | How the owner applies the migration and rotates the secret key |
| `dev\inbox.py` | ch. 7 (D15), ch. 8 (D17) | Pulls consented `problem_reports` columns into `problems\inbox\<user_id>\` for the Saturday routine; writes `report_replies` with the secret key |
| `dev\retention.py` | ch. 8 (D17), ch. 13 (D25) | Deletes reports older than 12 months and processes `deletion_requests` |
| `dev\gen_settings_doc.py` | ch. 14 (D26) | Renders `docs\he\settings.md` and `docs\en\settings.md` from `settings.read(defaults.toml)` + `WORDS` |
| `dev\tests_ops.py`, `dev\test_public_tree.py`, `dev\test_docs.py` | ch. 7, 10, 14 | The ops half of today's `tests.py`; archive-cleanliness tests; guide freshness tests |
| `docs\` (guide tree) | ch. 14 (D26) | `_config.yml`; `he\` and `en\` with the ten chapters (`01-install` … `10-faq`) and `settings.md`; `img\`; `strings\` (`retention.md`, `settings.he.json`); `privacy.md`, `terms.md` (D25) served on GitHub Pages |
| `dev\claude\commands\weekly-reports.md` | ch. 7 (D15) | Today's `.claude/commands/weekly-reports.md`, moved |
| `portable.txt` (never committed, owner's checkout only) | ch. 3 (D4) | Marker that keeps the owner's tree in today's layout |

## Acceptance

- Every file in the repo root, `transcribers/`, `skin/` and `android/` at the time of the phase-1 branch appears in exactly one row of this appendix with a verdict; a new file added later must be added here in the same pull request (a test enforces it, below).
- No module other than `paths.py` builds a path from `Path(__file__)` or `APP_DIR` for a store; no module other than `net.py` opens a socket; no module other than `secrets.py` touches Credential Manager, DPAPI or `.env` (D1, D3, D12).
- The built `app\` tree matches the "What the build does take" list exactly: `MANIFEST.sha256` lists no file that a deny pattern matches, and every `keep`/`change` row's file is present (D15, D19).
- `dev/` contains every `dev/` row; running the product from an installed tree with `dev/` absent works (nothing in `app\` imports from `dev/`).
- The owner's checkout with `portable.txt` present runs from today's layout after the moves and deletions, with `.env` and the live stores still honoured until he runs `--migrate` (D4).
- Every "change" row's call sites resolve to the cited lines on the phase-1 base commit; a row whose line numbers drift is corrected in the same commit that moves the code.

## Tests to add

| Test | Asserts |
|---|---|
| `test_inventory_complete` (in `dev/test_public_tree.py`) | Walks the repo (minus `.git`, `.venv`, `__pycache__`, gitignored paths) and checks every file is named, by exact name or by a listed glob, in this appendix's tables; fails with the list of unnamed files |
| `test_manifest_excludes_dev_files` | Builds the tree through `packaging\manifest.txt` into a temp dir and asserts none of the D15 deny patterns match a file in it, and that `tests.py`, `nightly.py`, `questions.py`, `weekly_review.ps1`, `.claude/`, `android/` are absent |
| `test_manifest_includes_ship_files` | The same temp tree contains every file in the "does take" list, `defaults.toml`, `VERSION`, `CHANNEL`, `NETWORK.md`, `SECURITY.md`, `TRADEMARK.md`, `LICENSE`, `THIRD-PARTY-NOTICES.txt`, `OFL.txt`, `packs\*.lock`, and all 20 pre-rendered cue files |
| `test_no_store_paths_outside_paths_py` | Static grep over `app\`: no `APP_DIR /`, `Path(__file__)` store construction, or literal store filename (`vocab.json`, `review.json`, `problems.json`, `transcripts.log`, `lookup_cache.json`, `notify.json`, `server_token.txt`, `.env`, `.setup-done`) outside `paths.py`, `migrations.py` and `secrets.py` |
| `test_app_tree_imports_no_dev` | Imports every module in the built `app\` with `dev/` removed from `sys.path`; no `ImportError` |
| `test_deleted_files_absent_from_archive` | `git archive HEAD` contains none of `.env`, `server_token.txt`, `.setup-done`, `*.vbs`, `versions.py`, `problems.md`, `vocab.json.bak-*`, `questions.json`, `questions.lock`, `*.html` |
| `test_keycaps_rename_complete` | No `import keyboard` or `from keyboard` in `app\`; `keycaps.py` present; the `keyboard` distribution is absent from the base wheelhouse lock |
| `test_new_files_present` | Each file in the "New files" tables that is marked as shipping exists in the built tree; each repo-only file exists in the checkout |
| `test_portable_layout_unchanged` (runs only when `portable.txt` exists) | With portable mode on, `paths.DATA_DIR == paths.APP_DIR` and the `.env` reader is enabled |

## Open points

1. `sb.py` is a name proposed by chapter 8 and listed here; chapter 5 counts it among the modules that may only reach the network through `net.py`. If the implementer prefers `supabase_client.py`, both chapters and this table change together.
2. The four untracked `*.html` scratch pages in the root and the four `vocab.json.bak-*` copies are the owner's to delete or keep outside the repo; the manifest excludes them either way, so nothing blocks on the decision (D28).
3. `README.md` is 3500+ lines and mixes contributor notes with user walkthroughs (`README.md:3371-3524`). This appendix marks it "change" and leaves the split to chapter 14; the owner may prefer to keep it as-is and point users at the guide.
4. `answer_card.py` moves to `dev/` because it belongs to the question routine (map/owner), but it imports `problem_card.py` which ships; the product must never import back from `answer_card.py`. `test_app_tree_imports_no_dev` guards this.
5. Line numbers in this appendix are those the maps recorded on the 2026-09-16 tree; `config.toml` is already modified uncommitted (map/packaging), so the phase-1 branch must re-verify the `config.toml` citations before scrubbing it into `defaults.toml`.
6. `dev/retention.py` and `dev/gen_settings_doc.py` are named by chapters 8 and 14; they were not in the brief's new-file list and are included here so the inventory stays complete. If either chapter drops them, remove the rows.
