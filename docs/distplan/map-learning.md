# DeskIT distribution map — Learning and personal history

Subsystem: everything that "learns the person" or records what he said.
Files read (all under `C:/Users/shimr/Desktop/Organized/Projects/DeskIT`): `vocab.py`, `polish.py`, `study.py`, `review.py`, `review_card.py`, `history.py`, `summary.py`, `reading.py`, `spool.py`, the relevant regions of `main.py`, `dashboard.py`, `config.py`, `translate.py`, `apikey.py`, `transcribers/__init__.py`, `transcribers/local_whisper.py`, `versions.py`, `firstrun.py`, `problems.py`, `.gitignore`, `.claude/commands/weekly-reports.md`, `config.toml` sections `[vocab] [study] [polish] [review] [local]`. Directories `corpus/`, `corpus/read/`, `recent/`, `pending/` were listed only. `transcripts.log`, `vocab.json`, `review.json` and the sidecars were inspected for **structure only** (ASCII key names), never for content. Nothing was run and nothing was modified.

---

## Purpose

This subsystem is the app's memory of one person. It has four learning channels and three history records, all keyed to a single owner and all stored **inside the code folder** (`APP_DIR = Path(__file__).resolve().parent`, `main.py:34`):

| Channel | Module | What it learns | Where it lands |
|---|---|---|---|
| Correction key (human) | `vocab.py`, `main.py:4440-4560` | (heard -> meant) word pairs from an edit the user made on screen | `vocab.json`, `transcripts.log` (`CORRECTED`), `recent/*.json` (`corrected`) |
| Context pass (polish) | `polish.py` | learns nothing; *uses* the vocabulary glossary and sends transcript text to an LLM | `transcripts.log` (`POLISHED`), `app.log` |
| Study pass (silent, machine) | `study.py` | pairs from 3 extra local decodes + LLM adjudication, while idle | `vocab.json` (`auto_hits`), `corpus/`, `recent/*.json` (`study`), `transcripts.log` (`STUDIED`) |
| Second reading (card, human-approved) | `review.py`, `review_card.py` | pairs the user accepts on a card / in the dashboard / from the phone | `review.json`, `vocab.json`, `corpus/`, `recent/*.json` (`review`), `transcripts.log` (`REVIEW`) |
| Read aloud (data collection) | `reading.py` | nothing about words — collects (audio, known-text) pairs of the user's voice | `corpus/read/`, `corpus/read/texts/`, `corpus/read/skipped.json` |
| History reader | `history.py` | reads `transcripts.log` back for the dashboard's Said page | read-only |
| Summary | `summary.py` | pure text truncation for cards; no I/O | none |

The long-term reason most of this exists is written in the code: a **future LoRA fine-tune of the local Whisper model on the owner's own voice** (`study.py:59-64, 479-487`; `reading.py:3-9`; `config.toml` `[study] corpus_keep` comment; `README.md:4011-4012`). No fine-tuning code exists in the repo; the corpus is a research asset.

While `[review] enabled = true` the review engine **replaces** the study engine (`main.py:2073-2107`: `_study` is only built when `_review is None`). The live `vocab.json` confirms this: its 63 entries carry only `heard/meant/hits/last` and no `auto_hits`/`auto_srcs`/`glossary_only` keys, so nothing machine-learned has been written by the study path in the current file.

---

## Files and what each does

### `vocab.py` (540 lines) — the learned vocabulary
- Store: `vocab.json` next to the app, JSON `{"version": 1, "corrections": [...]}`; loaded at `vocab.py:275-289`, saved at `vocab.py:291-301` (plain `write_text`, no temp file / rename).
- Entry shape (`vocab.py:311-316`, `362-380`): `heard`, `meant`, `hits` (human corrections), `last`; machine entries add `auto_hits`, `auto_srcs` (last 8 recording stems), `glossary_only`.
- Two mechanisms: **hotwords** fed to faster-whisper per 30 s window (`hotwords()` `vocab.py:451-461`; capped by `max_terms`, ranked by `_ranked()` `vocab.py:385-449`) and **replacement** after `replace_after_hits` human hits (`apply()` `vocab.py:490-528`, whole-token regex with Hebrew prefix handling `_PREFIX = "[ובהלכמש]"` `vocab.py:85`).
- **Seeds first and unconditionally** (`vocab.py:396-401`): `seed_terms` come from `config.toml [vocab] terms` and always occupy the front of the hotword list.
- `glossary(limit=60)` (`vocab.py:463-481`) hands (heard, meant) pairs to `polish.py`'s system prompt — i.e. learned words are part of every cloud request.
- `learn_from_edit` / `heard_by_decoder` (`vocab.py:318-336`, `210-235`): the backward-learning guard.
- No delete/forget API for a learned entry exists anywhere (the dashboard never writes `vocab.json`: grep of `dashboard.py` for vocab writers returned nothing).

### `polish.py` (464 lines) — the context pass (LLM repair)
- Backends in order of `[polish] prefer`: `groq` -> `cerebras` (opt-in only, never a fallback) -> `ollama` (`polish.py:285-324`). Groq needs `GROQ_API_KEY` in `.env`; a missing key is one log line (`polish.py:326-345`).
- `_prompt(glossary)` (`polish.py:144-178`) embeds up to 60 learned pairs in the system prompt; rebuilt per request (`polish.py:279-283`).
- Safety enforced in code: `_is_safe` (`polish.py:234-266`) — >=0.75 word similarity, <=15 % growth, non-empty; a rejected reply is never retried (`polish.py:421-463`).
- Sends **transcript text** off the machine when Groq/Cerebras is used; never audio (`polish.py:96-100`).
- `warm()` (`polish.py:364-388`) sends a throwaway "שלום" request to every backend at startup when `warm_up = true`.

### `study.py` (784 lines) — silent second learning channel
- `PLANS` (`study.py:342-346`): three extra local decodes — `wide` (beam 8, no hotwords), `general` (the second resident model `[local] english_model`, language detected), `loose` (temperature 0.3). All local (`transcribers/local_whisper.py:437-500`).
- `Adjudicator` (`study.py:284-340`): sends primary + 3 variants as text to Groq, then Ollama; reply must pass `_safe_choice` (`study.py:216-272`).
- `Corpus` (`study.py:482-529`): copies the wav out of `recent/` into `corpus/` with a sidecar `{"text", "tier", "seconds", "kept"}`; tiers `gold` (user-corrected) and `silver` (every decode agreed); trims to `corpus_keep` oldest-first (`study.py:517-523`); a gold sidecar is never downgraded (`study.py:501-503`).
- `Engine` (`study.py:536-673`): wakes every 5 s, studies one clip after `idle_minutes` of quiet, caps LLM calls at `llm_per_day`, writes `study={...}` into the recent sidecar (`study.py:611, 628`), learns via `vocab.learn_auto` (`study.py:636-641`), logs `STUDIED | family | heard || meant` to `transcripts.log` (`study.py:646-647`).
- `study_all` CLI (`main.py --study`, `study.py:679-784`): the measuring stick; prints every pair and WER.

### `review.py` (1307 lines) — the second reading
- Same three decodes, then `Reader` (`review.py:441-520`): Groq only by default; Ollama only if `[review] local_model = true`. Payload = final text + variants + `glossary_for()` (up to 30 learned pairs, those found in the text first; `review.py:635-650`). The `context` (previous sentences) parameter exists but the engine deliberately passes none (`review.py:990-994`).
- `tail_drop` finds invented endings structurally from per-word confidences kept in the sidecar as `words` (no LLM).
- `Store` (`review.py:661-861`): `review.json` beside `vocab.json`, `review.lock` beside it; cross-process lock via `msvcrt.locking` (`review.py:705-730`), atomic write via `<name>.<pid>.tmp` + `os.replace` (`review.py:691-696`); keeps 300 decided items (`KEEP_DECIDED`, `review.py:86`), pending never trimmed.
- Item shape (`suggestion_from`, `review.py:865-890`): `id` (= recent wav stem), `when`, `seconds`, `text`, `raw`, `proposed`, `changes[]` (`before/after/why/kind/span/family/support`), `agree`, `decodes`, `llm`, `status`, `shown`, `decided`, `by` (`card`/`dashboard`/`phone`), `learned`, `hwnd`, `source` (`desktop`/`phone`).
- `Engine` (`review.py:897-1150`): fed right after each paste (`main.py:1554-1563`), waits for GPU quiet up to 90 s (`review.py:1000-1010`), retries up to 6 times if a dictation interrupts, writes a `review` stamp **including the three full variant decodes** into the recent sidecar (`review.py:1027-1038`), admits gold/silver corpus pairs (`review.py:1039-1045`), stores proposals, shows the card. Accept -> `vocab.learn` (one human hit) + gold corpus admission + optional in-field fix (`review.py:1102-1150`; `main.py:1640-1660` logs `REVIEW | fixed`).
- Decisions from the dashboard (`dashboard.py:3841`) and the phone (`main.py:2418-2427`) are written straight to the store and absorbed by the engine's next wake (`review.py:1090-1097`).
- `review_all` CLI (`main.py --review`, `review.py:1172-1307`): replays corpus gold clips + corrected recent clips, scores proposals, sleeps 4 s between Groq calls.

### `review_card.py` (448 lines) — the card's words and picture
- Pure Pillow rendering; every string goes through `visual_qa.text_pil` (DrawTextW + `DT_RTLREADING`, Win32) (`review_card.py:20-23`). Hebrew UI strings hard-coded (`review_card.py:77-84`). No file I/O. Layout constants and palette duplicated from `skin\palette.py` so it works with the skin folder deleted.

### `history.py` (300 lines) — `transcripts.log` read back
- `LOG = APP_DIR / "transcripts.log"` (`history.py:27-28`); reads the live file plus `.1 .2 .3` (`history.py:99-109`). Parses `OK`, `OK | PHONE`, `DRAINED`, `POLISHED`, `CORRECTED`, `REVIEW | accepted`, `ERROR`, `DISCARDED`, `*-IN`/`*-OUT` (translate, punctuate, lookup) (`history.py:170-256`). Read-only; `stamp()` polled every 800 ms by the dashboard (`history.py:292-299`).

### `summary.py` (175 lines)
- Sentence-boundary truncation for one-line rows. Stdlib only, no I/O, no LLM (`summary.py:24-31`). Nothing to distribute-plan here beyond "keep it".

### `reading.py` (721 lines) — Read this to me
- Folder `corpus/read/` (`main.py:370`; `dashboard.py:213-215`), **never trimmed** (`reading.py:60-63`). Kept reading = `<stamp>.wav` + sidecar `{"text","key","tier":"gold","seconds","kept","source":"read","heard","match"}` (`reading.py:585-606`). Transient `pending-<id>.wav` while a reading awaits keep/drop (`reading.py:564-567`). `skipped.json` = list of sentence hashes (`reading.py:650-664`).
- Deck = sentences cut from `corpus/read/texts/*.txt|*.md` (`reading.py:271-300`), files the owner drops there, plus paragraphs written by `Writer` (Groq then Ollama) into `written-<stamp>.txt` (`reading.py:397-503`). The writer is offered **up to three of the user's learned names** per paragraph (`names_of(vocab.json)`, `reading.py:207-231`, `433-448`).
- `terms_of(vocab.json)` (`reading.py:186-204`) reads `vocab.json` directly by path.
- Win32: `ctypes.windll.user32.GetAncestor` to decide whether a key press over the dashboard is a reading (`reading.py:126-133`, `551-560`).
- `tally()` (`reading.py:687-721`) sums gold seconds across `corpus/` and `corpus/read/` for the "how much of your voice" bars.

### Supporting files that write the same stores
- `spool.py`: `Spool.save` (`spool.py:79-98`) writes `<YYYYmmdd-HHMMSS>-<tenths>.wav` + sidecar `{"seconds","saved","attempts","last_error", **extra}`; `update()` merges fields (`spool.py:100-108`); `_trim()` drops oldest past `keep` (`spool.py:116-122`). Used for `pending/` (`keep=100` default) and `recent/` (`keep=cfg.vocab.keep_audio`).
- `main.py`: `setup_logging` — `app.log` (500 KB x 2 backups, `main.py:5653-5656`) and `transcripts.log` (`RotatingFileHandler(maxBytes=1_000_000, backupCount=3)`, `main.py:5660-5665`, `propagate = False`). Desktop `recent.save(extra={"text","raw","backend","language","words"})` (`main.py:5568-5573`); phone `recent.save(extra={..., "source": "phone"})` (`main.py:2391-2397`) then `engine.submit(..., card=False)` (`main.py:2399-2400`); correction attaches `corrected` to the sidecar (`main.py:4522-4528`); `OK | ... | text` line written **before** any guard (`main.py:5378-5381`).
- `dashboard.py`: reads `vocab.json` for a count (`dashboard.py:457-465`) and for recent pairs (`dashboard.py:3625-3639`); decides review items (`dashboard.py:3841`); builds the reading deck and writer (`dashboard.py:2244-2248`, `2436-2448`); picks the newest `recent/*.wav` to pin to a problem report (`dashboard.py:5519-5522`).
- `config.py`: `VocabConfig` (`config.py:888-920`), `PolishConfig` (`923-1009`), `StudyConfig` (`1011-1043`), `ReviewConfig` (`1045-1084`); parsers at `config.py:1673-1740`. `[review] x/y/scale` are **written by the card into config.toml** (`config.py:1055-1059`).
- `apikey.py`: `.env` **next to the module** (`apikey.py:18-19`); lookup order environment then file (`apikey.py:57-63`); names `GEMINI_API_KEY/GOOGLE_API_KEY`, `CEREBRAS_API_KEY`, `GROQ_API_KEY` (`apikey.py:24-26`).
- `translate.py`: `GroqTranslator` = `CerebrasTranslator` pointed at `https://api.groq.com/openai/v1` (`translate.py:367`, `528-556`); request body and headers at `translate.py:450-470`; `OllamaTranslator` posts to `{ollama_url}/api/chat` (`translate.py:310-335`), default `http://127.0.0.1:11434` (`config.toml:326`).

---

## Personal data stores

All paths are relative to the code folder (`APP_DIR`). Sizes measured 2026-09-15 on the owner's machine.

| What | Where | Format | Sensitivity | Must be per-user? |
|---|---|---|---|---|
| Learned vocabulary | `vocab.json` (8.5 KB, 63 entries) | JSON `{"version":1,"corrections":[{heard, meant, hits, last[, auto_hits, auto_srcs, glossary_only]}]}` (`vocab.py:295-299`, `311-316`, `362-380`) | HIGH — the names he says (projects, tools, people) and how he mis-says them; sent to Groq inside every polish/review prompt | **Yes** |
| Hand-made vocabulary backups | `vocab.json.bak-20260828`, `-20260828-2151`, `-20260902-2156`, `-20260902-2205-resaved` | JSON copies | HIGH (same content, older) | Owner artefacts — no code writes `.bak` (repo-wide grep found nothing); must not ship |
| Transcript history | `transcripts.log`, `.1`, `.2`, `.3` (16 KB + 1 MB live) | pipe-delimited text, one event per line, `RotatingFileHandler(1 MB x 3)` (`main.py:5660-5665`) | **HIGHEST** — every dictation's raw and polished text (`OK`, `POLISHED`, `main.py:5380, 5202`), every correction before/after (`CORRECTED`, `main.py:4498`), translations in/out, punctuations, **lookups = what he selected and read** (`main.py:5054, 5086`), phone dictations (`OK | PHONE`, `main.py:2367`), review/study verdicts (`review.py:1097, 1115`; `study.py:646`), errors with kept text (`main.py:5370`) | **Yes** |
| Status log | `app.log`, `.1`, `.2` (500 KB x 2, `main.py:5653-5655`) | text | HIGH — quotes learned pairs (`main.py:4551`, `study.py:649`, `review.py:1053, 1141`), polished text (`main.py:5205`), pasted text (per `.gitignore:7`) | **Yes** |
| Recent recordings ring | `recent/` (50 wav + 50 json, 32 MB) | `<stamp>-<tenths>.wav` 16 kHz mono 16-bit + sidecar: `seconds, saved, attempts, last_error, text, raw, backend, language, words[[word,start,end,conf]], source, corrected, study{...}, review{engine, when, agree, llm, decodes, variants[3 full decodes], changes}` (`spool.py:79-98`; `main.py:5568-5573`, `2391-2397`, `4525`; `review.py:1027-1038`) | **HIGHEST** — raw audio of his voice plus four text readings of each clip | **Yes** |
| Refused recordings | `pending/` (empty now) | same spool format (`main.py:351`, `5732`) | HIGHEST (audio) | **Yes** |
| Verified corpus | `corpus/` (324 wav + 324 json, **199 MB**, cap `corpus_keep = 400`) | wav copied from `recent/` + `{"text","tier":"gold"\|"silver","seconds","kept"}` (`study.py:494-510`) | **HIGHEST** — labelled voice data, explicitly "training data for a future LoRA" | **Yes** — and the biggest store |
| Read-aloud recordings | `corpus/read/` (59 wav + json, ~11 MB, **uncapped**) | `{"text","key","tier":"gold","seconds","kept","source":"read","heard","match"}` (`reading.py:596-604`); transient `pending-<id>.wav` | HIGHEST (audio of him reading known sentences) | **Yes** |
| Read-aloud deck | `corpus/read/texts/` (`01-deskit.txt`, `02-git.txt`, `03-phone.txt`, `written-*.txt` x3), `corpus/read/skipped.json` | plain text, one sentence a line; skipped = list of sha1 keys (`reading.py:490-503`, `650-664`) | MEDIUM — his own prose, and model paragraphs seeded with his learned names | **Yes** |
| Second-reading proposals | `review.json` (215 KB, 115 items) + `review.lock` | JSON `{"version":1,"items":[...]}` (shape in `review.py:865-890`); 300 decided kept | **HIGHEST** — full sentence of each dictation (`text`, `raw`, `proposed`), the three variant readings' verdicts, accept/reject history, `hwnd` | **Yes** |
| API keys | `.env` (`GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `GROQ_API_KEY`) | `KEY=VALUE` lines read by `apikey.py:41-55` | SECRET | **Yes** |
| Hand-written seeds | `config.toml [vocab] terms` (`config.toml:1343-1358`) | TOML list, **committed** | MEDIUM — "this machine's projects": `HebrewDictation`, `Massif`, `TripSync`, `Cowork` | Per-user (must ship empty) |
| Decoder prompt | `config.toml [local] initial_prompt` (`config.toml:1597`) and the default in `config.py:271-273` | string | LOW (generic dev jargon) but owner-tuned | Per-user override |
| Card positions | `config.toml [review] x = 2188, y = 1373, scale = 1.0` (`config.toml:1168-1176`) — also `[hint] x = -1895` (`265`), `[problems] x/y` (`1230-1238`) | TOML, **committed**, written by the app (`config.py:1055-1059`) | LOW — but they are the owner's multi-monitor coordinates | Per-machine state, not config |
| Setup marker | `.setup-done` (`firstrun.py:65`) | 104-byte file | LOW | Per-installation |
| Adjacent stores fed from here | `problems/` (pinned copies of `recent/` wav+json + screenshots, `problems.py:376-393`), `lookup_cache.json`, `notify.json/log`, `awake_state.json/log`, `cues/`, `server_token.txt` | — | see other maps | **Yes** |

A per-user, per-installation layout has to move **all of the above** out of the code folder. Cross-store joins that must survive the move: the `recent/` wav stem is the `id` in `review.json` (`review.py:867`) and the `dictation.id` in problem reports (`weekly-reports.md:378-380`), and `corpus/` keeps the same file name as the `recent/` clip it was copied from (`study.py:499`).

---

## Machine-specific assumptions

| Assumption | Evidence |
|---|---|
| Every store is beside the code (`APP_DIR = Path(__file__).resolve().parent`) | `main.py:34, 351, 356, 370, 2084, 2416, 5653, 5660, 5732`; `history.py:27-28`; `apikey.py:18-19`; `dashboard.py:213-215, 461, 3626, 3822, 5519`; `study.py:556, 690, 698, 709`; `review.py:914, 1189, 1201, 1214`; `firstrun.py:52-53, 65`; `versions.py:36`; `problems.py:316` |
| Windows-only primitives | `review.py:707-710, 724-725` (`msvcrt.locking`); `reading.py:126-133` (`ctypes.windll.user32.GetAncestor`); `review_card.py:20-23` (DrawTextW via `visual_qa.text_pil`) |
| `review.json` items carry a live window handle | `review.py:880` (`"hwnd"`) — meaningless after the session |
| Local Ollama at `127.0.0.1:11434` with `gemma3:12b` (~8.5 GB VRAM) | `config.toml:326`, `1538`, `1566-1569`; `polish.py:302-311` |
| Two Whisper models resident (Hebrew fine-tune + `english_model`) for the `general` plan | `study.py:342-346`; `transcribers/local_whisper.py:459-464` ("no general model loaded for a second opinion") |
| CUDA: three extra decodes per dictation are sized for a 5060 Ti (~40x real time) | `rolling.py:6`; `requirements.txt` CUDA note; `config.toml:1620-1632` |
| Study/review only exist when `keep_audio > 0` and the transcriber has `study_decode` | `main.py:356-357, 2078-2079, 2095-2097` — setting `keep_audio = 0` for privacy silently removes both learning engines |
| git present (branch stamp on reports) | `versions.py:53-62` |
| Config file carries screen coordinates of this desk | `config.toml:1168-1169` (`x = 2188, y = 1373`), `config.py:871-876` explains they are deliberately unvalidated |
| The read-aloud `SUBJECTS` and writer rules describe the owner's life | `reading.py:108-121` ("a small thing about the phone app that annoys you", "why the machine has to stay awake while the screens are off"); `reading.py:381-385` ("his Windows dictation app") |
| Hebrew-specific heuristics (prefix letters, sof pasuq, RTL detection) | `vocab.py:85`; `study.py:91`; `summary.py:56-64`; `review.py:170-180` — fine for a Hebrew product, not configurable |

---

## External services and what leaves the machine

**Audio never leaves the machine through this subsystem.** All extra decodes run on the local models (`transcribers/local_whisper.py:437-500`); every network body in `translate.py:310-335` and `450-470` carries text only. Verified against the code, not assumed.

| Service | Endpoint | Auth | Data sent | Caller(s) | Optional? |
|---|---|---|---|---|---|
| Groq (default) | `https://api.groq.com/openai/v1/chat/completions` (`translate.py:367, 465`) | `Authorization: Bearer GROQ_API_KEY` from `.env`/env (`translate.py:431-433, 469`); `User-Agent: deskit/1.0` (`translate.py:373`) | JSON: `model`, `temperature 0.2`, `stream false`, `max_tokens`, `reasoning_effort: low`, `messages = [system prompt, user text]` | **polish**: full transcript of every dictation (`when = "always"`, `min_chars = 20`) **plus up to 60 learned (heard -> meant) pairs in the system prompt** (`polish.py:144-178, 283`); with `[local] rolling` each 25 s stretch goes while the key is still held (`config.toml:1450-1455`). **study**: primary + 3 variants (`study.py:337-340`), <= 60/day. **review**: text + variants + up to 30 learned pairs (`review.py:483-497, 635-650`), <= 200/day. **reading.Writer**: a subject line + up to 3 of the user's learned names (`reading.py:433-448`) | Yes — skipped with one log line when no key; `prefer = "ollama"` declines entirely |
| Cerebras | `https://api.cerebras.ai/v1/chat/completions` (`translate.py:366`) | `CEREBRAS_API_KEY` | same shape | polish only, and only if `prefer = "cerebras"` (`polish.py:317-324`) | Opt-in; free tier is gone (HTTP 402, `polish.py:83-88`) |
| Ollama (local) | `http://127.0.0.1:11434/api/chat` (`translate.py:332`; `config.toml:326`) | none | same messages, `options.temperature 0.2`, `num_predict` | polish fallback, study adjudicator fallback, review only if `local_model = true`, reading writer fallback | Yes — URLError -> logged, degrade |
| Gemini | — | — | **not used** by this subsystem (`polish.py:68-76`; `config.toml:1434-1440`) | — | — |
| Hugging Face | model download by `faster_whisper.WhisperModel` (`transcribers/local_whisper.py:243, 362`) | none | nothing personal | outside this subsystem, but the three-decode engines need both models | — |
| Phone (Tailscale HTTP) | inbound only | — | phone dictations are written into `recent/` with `source: "phone"` and read by the review engine without a card (`main.py:2391-2400`); phone can list/decide proposals (`main.py:2411-2427`) | — | — |

What a privacy proof can cite: `apikey.py` is the only reader of `.env`; the key is only ever placed in the `Authorization` header of requests to `translate.py`'s `base_url` (`translate.py:465-470`); nothing in this subsystem writes the key anywhere else.

---

## Owner-only or developer-only features

| Feature | Where | Why it is owner/developer machinery |
|---|---|---|
| `--study`, `--review`, `--benchmark`, `--vocab`, `--drain` CLIs | `main.py:5893-5912`; `study.py:679-784`; `review.py:1172-1307`; `main.py:5720-5760`; `main.py:5799` | Measuring sticks that print WER tables to a console; they load the models a second time and hit Groq in a loop |
| The corpus for a future LoRA | `study.py:479-529`; `config.toml [study] corpus_keep` comment; `README.md:4011-4012` | 199 MB of labelled voice for a fine-tune that does not exist; no user benefit today |
| Read this to me + the Writer | `reading.py` whole; dashboard Corrections > Read tab (`dashboard.py:2092-2140, 2236-2460`); `[study] read_sentences`, `read_goal_hours` | Data collection for that fine-tune; subjects and rules are about the owner's life (`reading.py:108-121, 373-395`); "five minutes a day" is his ceiling (`config.py:1036-1041`) |
| `STUDIED` / `REVIEW` telemetry lines in `transcripts.log` | `study.py:646-647`; `review.py:1097-1099, 1115-1117`; `main.py:1657, 2429` | Written for the Saturday Claude Code routine and the owner's measurements |
| Saturday weekly review reads `review.json` and `recent/` sidecars | `.claude/commands/weekly-reports.md:359-384, 1154` | A developer routine consuming personal stores by design |
| `versions.current_branch()` stamped on reports | `versions.py:53-62`; `problems.py` | git-branch bookkeeping |
| Cerebras backend + its two config keys | `translate.py:376-525`; `config.toml:1519-1532` (`cerebras_model`, `cerebras_timeout_s`) | Kept "for whoever holds quota" on a dead free tier |
| `ENGINE` version constants that force re-study/re-read | `study.py:87`; `review.py:76` | Developer knob |
| `[review] witness`, `max_changes`, `local_model`; `[vocab] hebrew_after_hits` | `config.toml:1697-1713, 1743-1749, 1326-1334` | Numbers from measurement sessions (`2026-09-02`) |
| Committed seeds and coordinates | `config.toml:1343-1358` (`terms`), `1168-1176` (`[review] x/y`) | The owner's stack and his monitors |
| `vocab.json.bak-*` | repo root | Hand-made backups |
| `app.log` quoting learned pairs and text | `main.py:4551, 5205` | Debug convenience that makes the status log personal |

---

## What breaks on a fresh machine

| Situation | What happens | Evidence |
|---|---|---|
| Installed under Program Files (read-only code dir) | `setup_logging` opens `APP_DIR/transcripts.log` and `app.log` for writing before anything else — the app fails to start; `vocab.save` logs and loses learning (`vocab.py:300-301`); `review.Store._save` raises inside the engine thread on every job (`review.py:691-696`, no try/except); `Corpus.admit` swallows OSError (`study.py:513-515`); `recent.save` OSError is caught (`main.py:5574-5576`) | `main.py:5653-5665` |
| No `.env` / no `GROQ_API_KEY` | Groq constructor raises `TranslationError`, polish/study/review/writer skip it with one log line and fall to Ollama (`translate.py:431-433`; `polish.py:326-345`; `study.py:331-333`; `review.py:475-477`; `reading.py:426-428`) — degrades correctly | |
| No Ollama installed | Every local-LLM call fails with URLError -> logged, transcript pasted unrepaired (`polish.py:421-463`); `warm_up = true` spends `ollama_timeout_s = 150` s at startup on a dead socket? — `warm()` runs on a background thread (`polish.py:364-388`) so the paste is not blocked, but `app.log` fills with warnings | `config.toml:328`, `1571-1573` |
| No NVIDIA GPU | CPU fallback ~40x slower (`requirements.txt`); the review engine then runs **three extra decodes per dictation on CPU**, holding the model lock per decode (`review.py:1000-1012`; `study.py:400-413`) — the next dictation waits behind one CPU decode; the machine is busy for minutes after every sentence | `main.py:2077-2080` builds the engine whenever `review.enabled` and `keep_audio > 0`, with no hardware gate |
| Second model (`english_model`) not downloaded/loaded | `general` plan raises and is skipped; 2 decodes remain (`study.py:335-340`; `local_whisper.py:459-464`); `_silver` still needs >= 2 decodes (`study.py:661-670`) | +1.6 GB download for a stranger |
| `[vocab] keep_audio = 0` chosen for privacy | `self.recent = None` -> neither study nor review engine is built (`main.py:356-357, 2078, 2096`); corrections can no longer be tied to audio; `--benchmark` has nothing to measure (`main.py:5738-5741`) | The privacy switch silently turns off half the product |
| Committed seeds | A stranger's decoder is primed with `HebrewDictation`, `Massif`, `TripSync`, `Cowork` **before** anything he taught it (`vocab.py:396-401`); over-prompting makes Whisper emit prompted words unbidden (`vocab.py:52-58`) | `config.toml:1349-1350` |
| Committed card coordinates | `[review] x = 2188, y = 1373` lands the card off-screen on a single 1080p monitor; config.py deliberately does not validate (`config.py:871-876`) | `config.toml:1168-1169` |
| Empty `corpus/read/texts/` | The Read tab asks the Writer; with no Groq and no Ollama it says "drop a text into corpus\read\texts" (`dashboard.py:2455-2457`) | |
| No git | `current_branch()` returns `"(unknown)"` (`versions.py:61`) — harmless | |
| Fresh `vocab.json`, `review.json` | Both handle absence (`vocab.py:275-278`; `review.py:679-681`) — fine | |
| Another user on the same PC | Everything is in one folder: two Windows accounts would share vocabulary, history and audio | `APP_DIR` everywhere |

---

## Settings classification

Per `config.toml` key. **user** = a normal user should see it on the Settings page; **advanced** = keep, fold behind "more"; **developer-or-machine** = remove from the shipped file, or move to per-machine state.

### `[vocab]` (`config.toml:1309-1358`)
| Key | Class | Note |
|---|---|---|
| `enabled` | user | "Use the words it has learned" (`settings.py:431-434`) |
| `terms` | user | but the shipped value must be **empty**; a first-run wizard should ask for "your projects and tools" |
| `max_terms` | advanced | |
| `replace_after_hits` | advanced | |
| `hebrew_after_hits` | developer-or-machine | a 2026-09-02 measurement knob |
| `keep_audio` | user | this is the real "keep my recordings" privacy switch — but see the coupling to study/review above |

### `[study]` (`config.toml:1366-1418`)
| Key | Class | Note |
|---|---|---|
| `enabled` | user | "Keep learning while you are away" (`settings.py:493-496`); default should follow hardware |
| `idle_minutes` | advanced | |
| `max_clip_seconds` | advanced | |
| `llm_per_day` | developer-or-machine | tied to the Groq free-tier bucket |
| `corpus_keep` | developer-or-machine | fine-tune material; recommend shipping `0` and hiding unless "voice training" is a shipped feature |
| `read_sentences`, `read_goal_hours` | developer-or-machine | bars for the owner's read-aloud routine |

### `[polish]` (`config.toml:1420-1573`)
| Key | Class | Note |
|---|---|---|
| `when` | user | never / known / always |
| `prefer` | user | **this is the consent switch** (cloud text vs local) — needs plainer wording than "which service fixes the words first" (`settings.py:1186-1188`) |
| `min_chars` | advanced | |
| `groq_model`, `groq_timeout_s` | advanced | |
| `cerebras_model`, `cerebras_timeout_s` | developer-or-machine | dead tier; remove |
| `ollama_model` | developer-or-machine | depends on VRAM (8.5 GB) |
| `max_wait_s` | advanced | |
| `warm_up` | developer-or-machine | VRAM trade on this box |

### `[review]` (`config.toml:1670-1753`)
| Key | Class | Note |
|---|---|---|
| `enabled` | user | |
| `card_seconds` | user | |
| `corner` | user | |
| `x`, `y`, `scale` | developer-or-machine | app-written state; move to a per-machine state file |
| `max_changes`, `witness` | advanced | |
| `local_model` | developer-or-machine | measured off on 2026-09-02 |
| `accept_key`, `reject_key`, `later_key`, `edit_key` | advanced | |
| `fix_in_field` | user | |
| `max_clip_seconds` | advanced | |
| `llm_per_day` | developer-or-machine | Groq bucket |

### `[local]` keys this subsystem depends on (`config.toml:1586-1668`)
| Key | Class | Note |
|---|---|---|
| `initial_prompt` | advanced | default in `config.py:271-273` is generic dev jargon; fine to ship, but it is the second place the owner's register lives |
| `english_model` | developer-or-machine | +1.6 GB; needed for the `general` plan and for English detection |

---

## Dependencies and binaries

- Python 3.11 stdlib only for storage and HTTP: `json`, `difflib`, `urllib` (`translate.py:24-25`), `msvcrt` (`review.py:707`), `ctypes` (`reading.py:70`), `hashlib`, `threading`, `queue`, `logging.handlers`.
- `faster-whisper` / CTranslate2 with **two** models: `ivrit-ai/whisper-large-v3-turbo-ct2` and `deepdml/faster-whisper-large-v3-turbo-ct2` (`config.toml:1587, 1602`), downloaded by `WhisperModel(...)` into the Hugging Face cache in the user profile (`transcribers/local_whisper.py:243, 362`). The `general` decode plan needs the second (`study.py:344`).
- `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` (`requirements.txt`) for CUDA; CPU is the ~40x-slower fallback.
- Pillow (`review_card.py:41`) and `visual_qa.text_pil` -> Win32 `DrawTextW` for the card.
- Ollama binary + `gemma3:12b` (~8.5 GB) for the local LLM legs; `llama3.1:8b` is the `[translate]` fallback model reused when `polish.ollama_model` is empty (`config.toml:319`; `polish.py:306-307`).
- A Groq API key (free tier, no card) for the default cloud leg.
- `git` (optional; `versions.py`).
- Cross-module coupling: `polish.py`, `study.py`, `review.py` all import `vocab` for `words()`/`family()`/`MAX_SPAN_WORDS`; `review.py` imports `study` for `PLANS`, `agreement`, `Corpus`; `reading.py` imports `vocab` and reads `vocab.json` by path; `study.py`/`review.py` CLIs import `main.word_error_rate` and `spool.Spool`.

---

## Distribution risks

1. **Every personal store is inside the code folder.** An installer, an updater, an uninstaller and a second Windows account all collide with `vocab.json`, `review.json`, `transcripts.log*`, `app.log*`, `recent/`, `pending/`, `corpus/`, `corpus/read/`, `.env`, `.setup-done` (paths cited under *Machine-specific assumptions*). A zip of the owner's working folder would ship his keys, his voice and his history — `.gitignore` protects git only.
2. **Raw voice is hoarded by default**: `recent/` 50 clips + `corpus/` up to 400 (~200 -> 400 MB) + `corpus/read/` uncapped + `problems/` pins, for a fine-tune that does not exist. There is no "delete my recordings / history / learned words" surface: the dashboard never writes `vocab.json`, `Vocab` has no forget method, only `reading.forget` (`reading.py:625-641`) and `Store.forget` (`review.py:856-860`) exist.
3. **Transcript text and the learned vocabulary go to Groq by default** (`prefer = "groq"`, `when = "always"`): each dictation's text plus up to 60 (heard -> meant) pairs in the system prompt (`polish.py:144-178`); the second reading sends up to 30 pairs (`review.py:635-650`); the Writer sends the user's names (`reading.py:433-448`). With rolling, stretches leave before the key is released, so an aborted dictation may already have gone (`config.toml:1450-1455`). None of this is presented as a consent question today; `settings.py:1186-1188` calls it "Which service fixes the words first".
4. **Owner identity baked into committed files**: `[vocab] terms` seeds (`config.toml:1349-1358`), `[review]/[hint]/[problems]` screen coordinates (`config.toml:265-274, 1168-1176, 1230-1246`), read-aloud `SUBJECTS` (`reading.py:108-121`), Hebrew card strings (`review_card.py:77-84`).
5. **Privacy switch disables learning**: `keep_audio = 0` removes both engines (`main.py:356-357, 2078, 2096`) — a user who declines audio retention loses the second reading without being told.
6. **No hardware gate on the triple decode**: on CPU or a small GPU the review/study engines will make the machine crawl (`main.py:2077-2080`); VRAM budget assumes two Whisper models + gemma3:12b on 16 GB (`config.toml:1566-1569`).
7. **Free-tier quotas are per key**: `llm_per_day` values (60 + 200 + polish) were sized for one owner's Groq bucket; each user needs their own key, and the owner's key must never ship (`.env` beside code).
8. **Logs meant for support are personal**: `app.log` quotes learned pairs and text (`main.py:4551, 5205`); a "send me your log" support flow, or a Supabase problem-report upload, would carry dictated text unless stripped. Problem reports already pin audio + screenshot from `recent/` (`problems.py:376-393`).
9. **Cross-store ids**: `recent/` stems are `review.json` ids and problem-report ids; a relocation must move the three together or accept dangling joins (`review.py:867, 1135`).
10. **Non-atomic `vocab.json` write** (`vocab.py:295-299`) — a crash mid-write loses the vocabulary (the file is 8 KB; `review.Store` already does tmp + `os.replace`, `review.py:691-696`).
11. **Cerebras dead code path** and two settings that a user cannot use (`config.toml:1519-1532`).
12. **Developer CLIs ship with the app** (`--study`, `--review`, `--benchmark`) and re-load models / call Groq in loops — harmless but confusing in a user build.
13. **`hwnd` and screen coordinates inside data files** (`review.py:880`; `config.py:1055-1059`) — session/machine state mixed with durable data.
14. **Model downloads land in the user's HF cache**, not in the install; a per-user install must decide where the ~3.2 GB of models live and whether two are required.

---

## Recommendations for the plan

1. **One `paths.py` with a per-user `DATA_DIR`** (e.g. `%LOCALAPPDATA%\DeskIT\`), resolved once, and every `APP_DIR / "<store>"` call site above rewritten to it. Proposed layout:
   ```
   %LOCALAPPDATA%\DeskIT\
     config.toml            user copy; the shipped default stays read-only beside the code
     keys.env               (or Windows Credential Manager) — the only file apikey.py reads
     state.json             card/dot/hint positions, scale, .setup-done, window handles
     vocab.json
     review.json  review.lock
     logs\transcripts.log*  logs\app.log*
     audio\recent\  audio\pending\
     corpus\  corpus\read\  corpus\read\texts\
     problems\
   ```
   Call sites to change: `main.py:34, 351, 356, 370, 2084, 2416, 5653, 5660, 5732`; `history.py:27-28`; `apikey.py:18-19`; `dashboard.py:213-215, 461, 3626, 3822, 5519`; `study.py:556, 690, 698, 709`; `review.py:914, 1189, 1201, 1214`; `firstrun.py:52-53, 65`; `problems.py:316`; `versions.py:36` (or drop).
2. **Move app-written positions out of `config.toml`** (`[review] x/y/scale`, `[hint]`, `[problems]`, `[dot]`) into `state.json`; validate that a stored position is on a connected monitor before using it. This also fixes the committed-coordinates problem and stops `config.set_values` from rewriting a shared file for state.
3. **Ship neutral defaults**: `[vocab] terms = []`; keep the generic dev-jargon `initial_prompt` (`config.py:271-273`) as the shipped default; first-run wizard asks "names and terms you use" and writes them to the user's `config.toml`. Remove the "this machine's projects" comment block (`config.toml:1343-1358`).
4. **Make consent explicit and separate from tuning**: a first-run/Settings question "Send the text of what you say to Groq to fix misheard words? (your audio never leaves)" that sets `polish.prefer` (`groq` | `ollama` | `never`) and gates study/review LLM use. Consider capping or omitting the glossary in the polish system prompt (`polish.py:144-178`) — it exports the user's whole learned list on every request; the review path already filters to pairs found in the text (`review.py:643-645`), the polish path could do the same. State in the user guide that rolling sends stretches before release.
5. **Privacy defaults for strangers**: `keep_audio` small (e.g. 10–20) with a plain label; `corpus_keep = 0` and the Read-aloud tab hidden unless the user opts into "help train a model on my voice"; `study.enabled = false`; `review.enabled` decided by a CUDA check at startup (`main.py:2077-2080`: add `transcriber.device == "cuda"` to the guard, or a "second reading needs a GPU" note).
6. **Decouple the privacy switch from learning**: let the review engine run with `keep_audio` small but > 0, or key it to a separate `[review] keep_audio`; today `keep_audio = 0` silently kills both engines (`main.py:356-357, 2078, 2096`).
7. **A "Your data" page in the dashboard**: sizes of each store, and buttons — forget a learned word (add `Vocab.forget(heard)` + atomic save), clear history (`transcripts.log*`), delete recordings (`recent/`, `pending/`, `corpus/`, `corpus/read/`), delete proposals. Make `Vocab.save` atomic like `review.Store._save` (`review.py:691-696`).
8. **Split logs**: `app.log` support-safe (no dictated text, no learned pairs — `main.py:4551, 5205`, `study.py:649`, `review.py:1053, 1141`); quoted text only in `transcripts.log`, with a retention setting (days / off). "Off" needs the clipboard fallback message reworded, since `transcripts.log` is currently the recovery path (`main.py:5378-5381`).
9. **Supabase scope**: sync at most `vocab.json` (8 KB, the one thing worth carrying between machines) and the user's `config.toml` diff; **never** `recent/`, `corpus/`, `review.json`, `transcripts.log`. Problem reports upload text + settings only; audio/screenshot only with a per-report checkbox. The key-privacy proof can point at `apikey.py` (single reader) and `translate.py:465-470` (single use, `Authorization` header to `base_url`), plus a test that greps for any other reader.
10. **Remove the Cerebras path** (`translate.py:376-525`, `config.toml:1519-1532`, `apikey.py:25, 86-92`) and hide/strip the developer CLIs (`--study`, `--review`, `--benchmark`) from the user build, or move them to a `tools/` entry point.
11. **Build the installer from `git archive`**, not from the working folder, and add a build check that the artifact contains none of: `.env`, `vocab.json*`, `review.json`, `transcripts.log*`, `app.log*`, `recent/`, `pending/`, `corpus/`, `problems/`, `.setup-done`.
12. **Migration on first launch of a new version**: if the old in-folder stores exist (owner's own machine), move them to `DATA_DIR` once; bump `vocab.json`/`review.json` `"version"` with a migration hook; note that bumping `study.ENGINE`/`review.ENGINE` re-decodes every user's `recent/` once.
13. **Read-aloud, if kept as an opt-in feature**: replace `SUBJECTS` (`reading.py:108-121`) with neutral subjects, stop passing the user's names to the Writer unless the cloud consent is on, and cap `corpus/read/` size.
14. **User guide facts to state plainly**: what is stored where and for how long; that audio never leaves; exactly what text goes to Groq and when; how to delete everything; that the second reading needs a GPU and three extra decodes per sentence.
