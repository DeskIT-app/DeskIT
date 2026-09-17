# DeskIT subsystem map: Cloud services, API keys and LLM passes

Repo: `C:/Users/shimr/Desktop/Organized/Projects/DeskIT` (read-only survey, 2026-09-15).
Every claim below cites `file:line` in that folder unless marked `.venv`.

## Purpose

This subsystem is everything that can send bytes off the user's machine on the app's own
initiative, plus the local Ollama fallback that stands underneath each cloud leg. It covers:

- **Key discovery** (`apikey.py`): three provider keys read from the process environment or a
  `.env` file beside the code.
- **Gemini plumbing** (`gemini_pool.py`, `transcribers/gemini.py`): 429 parsing, per-model
  daily-quota rotation, "stop thinking" knobs, and the cloud *audio* transcription backend.
- **Text passes that re-use one family of HTTP clients** (`translate.py`): `GeminiTranslator`
  (google-genai SDK), `OllamaTranslator` (urllib to 127.0.0.1:11434), `CerebrasTranslator` and
  its subclass `GroqTranslator` (urllib to OpenAI-compatible `/chat/completions`).
- **The keys built on those clients**: translate (`translate.py::Translator`), punctuate
  (`punctuate.py`), lookup (`lookup.py`), the repair/context pass (`polish.py`), and
  ask-the-screen (`visual_qa.py`).
- **Second-order consumers that borrow the same clients** and therefore the same egress:
  the second reading (`review.py:442-520`), the study pass (`study.py:285-340`), the
  read-aloud sentence writer (`reading.py:397-460`), and the phone endpoint's
  `/translate`, `/punctuate`, `/lookup` routes (`server.py:268-270`, `main.py:2433-2497`).

The owner's stated rules that this subsystem implements: all-free (AGENTS.md:127-131),
audio never leaves the machine except the opt-in Gemini dictation backend (AGENTS.md:132-136),
never rewrite the user's words, enforced in code (AGENTS.md:137-141; `polish.py:234-265`,
`punctuate.py:164-174`).

## Files and what each does

| File | Lines | Role |
|---|---|---|
| `apikey.py` | 100 | `find_key(names)` looks in `os.environ` first (`apikey.py:29-34`), then parses `APP_DIR/.env` as `KEY=VALUE` lines, utf-8-sig, stripping quotes (`apikey.py:37-53`). Name buckets: Gemini = `GEMINI_API_KEY` **or `GOOGLE_API_KEY`**; `CEREBRAS_API_KEY`; `GROQ_API_KEY` (`apikey.py:24-26`). Returns `(key, human_source)`. Three "missing key" messages tell the user to edit `.env` (`apikey.py:77-99`). |
| `gemini_pool.py` | 149 | `parse_429()` reads retry-after / per-day / limit out of the SDK error (`:29-61`). `thinking_style()/apply_thinking()`: `thinking_budget=0` for 2.5 models, `thinking_level="low"` for "-latest" aliases (`:64-89`). `rotate()` tries models in order, rests a 429'd model 30 min (per-day) or exponential backoff up to 60 min, raises `RateLimitError` only when every model is resting (`:92-149`). Rotation state lives in the caller's dicts (`:8-10`). |
| `transcribers/gemini.py` | 157 | `GeminiTranscriber`: builds `genai.Client(api_key=...)` at construction (`:61-73`), sends **WAV bytes** + instruction with a Hebrew system prompt (`:91-108`), rotates via `gemini_pool` (`:143-151`), `check()` makes one text request (`:153-157`). Selected only when `backend = "gemini"` (`transcribers/__init__.py:45-47`). |
| `translate.py` | 606 | The shared client family. `GeminiTranslator` (`:112-179`), `OllamaTranslator` (`:183-363`; streaming, `keep_alive`, `num_predict` opt-ins), `CerebrasTranslator` (`:377-525`; Bearer auth, named User-Agent `deskit/1.0` because Cloudflare 403s Python's default UA `:369-374`), `GroqTranslator` (`:528-556`; same class, `GROQ_URL`, `reasoning_effort=low`, `min_max_tokens=256`). `Translator` = Gemini first then Ollama (`:559-607`); **Groq is not in the translate chain**. Hosts: `CEREBRAS_URL="https://api.cerebras.ai/v1"` (`:366`), `GROQ_URL="https://api.groq.com/openai/v1"` (`:367`). |
| `punctuate.py` | 366 | Letter-for-letter guard `is_safe()` (`:134-174`). Chain `ORDER=("groq","gemini","ollama")` with `prefer` first (`:184`, `:299-309`); each backend built lazily on first press (`:230-297`). Used by the F-key, by `punctuate.auto` on every dictation (`main.py:2511-2555`), and by the phone (`main.py:2480-2497`). |
| `lookup.py` | 954 | Direction/mode classification (`:146-323`), prompts (`:343-434`), **`Cache` persisted to `APP_DIR/lookup_cache.json`** keyed by the literal selected text (`:440-533`, path at `:627-629`), `Engine`: Ollama first; Gemini when the local model is not resident and `cold_to_gemini` is on, or when `prefer="gemini"`, or when Ollama fails (`:569-913`). Probes Ollama with `GET /api/ps` (`:703-704`) and warms with `POST /api/generate` (`:742-750`). |
| `polish.py` | 464 | The repair pass. `_is_safe()` word-diff guard (`:234-265`). Backends: `prefer` first, then the rest in order `groq, ollama`; **Cerebras is opt-in only, never a fallback** (`:285-324`). Warms every backend at startup (`:364-388`). Glossary of learned corrections embedded in the system prompt (`:144-179`, `:279-283`). Never raises; failure = raw transcript (`:421-464`). |
| `visual_qa.py` | 4348 | Ask-the-screen. Backends `OllamaVision` (`:546-712`), `GroqVision` (`:714-900`; key at `:786-794`, Bearer header `:836`, `GROQ_URL/chat/completions` `:863-867`, image as `data:image/jpeg;base64`), `GeminiVision` (`:905-960`). `Chain._builders()` lists cloud builders **only if** `allow_screenshot_upload` is true; `gemini_fallback` adds Gemini after Groq (`:986-1004`). Screenshot stays in RAM (`:118-122`). TTS = PowerShell WinRT subprocess writing `.wav`/`.txt` into a `tempfile.mkdtemp("vqa-tts-")` dir (`:1176-1208`). |
| `.env` | 5 lines | Present on the owner's machine with `GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `GROQ_API_KEY` (names only were read). Gitignored (`.gitignore:1`). |
| `config.toml` sections | | `[gemini]` `:1574-1584`; `[translate]` `:311-333`; `[punctuate]` `:334-384`; `[lookup]` `:385-552`; `[visual_qa]` `:554-720`; `[polish]` `:1420-1573`. Dataclasses in `config.py`: `GeminiConfig :38-49`, `TranslateConfig :315-332`, `PunctuateConfig :340-379`, `LookupConfig :382-455`, `VisualQAConfig :463-515`, `PolishConfig :923-1008`. |

Consumers outside the file list that ride on these clients (all text-only, Groq first):

- `review.py:442-520` `Reader`: sends `[1] final transcript`, alternative decodes, the learned
  glossary, and **the sentences dictated just before as context** (`review.py:486-500`) to
  Groq; Ollama only if `review.local_model = true` (default false, `config.py:1094-1097`).
  Budget `llm_per_day = 200` (`config.py:1109`).
- `study.py:285-340` `Adjudicator`: primary + candidate decodes to Groq, then Ollama.
  `llm_per_day = 60` (`config.py:1029`).
- `reading.py:397-460` `Writer`: asks Groq/Ollama to *write* practice sentences; sends only a
  subject and a few names from the user's vocabulary (`reading.py:437-446`).
- `server.py:333-411` phone `/translate` and `/punctuate` and `main.py:2433-2447` `/lookup`
  reuse the same `Translator`/`Punctuator`/`Engine` instances, so phone text follows the same
  cloud path.
- `capture.py:172-174`: the screenshot editor's Ask button hands pixels to `visual_qa` and
  obeys `allow_screenshot_upload` like every other question. `dashboard.py:5538-5542` imports
  `visual_qa` only for `encode_jpeg` when filing a problem report (no network).

## Personal data stores

| What | Where | Format | Sensitivity | Must be per-user? |
|---|---|---|---|---|
| API keys (Gemini/Google, Groq, Cerebras) | `APP_DIR/.env` (`apikey.py:18-19`); alternatively process env vars `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY` (`apikey.py:24-34`) | plaintext `KEY=VALUE` | **Secret.** Readable by any process running as the user; shared by every Windows account that can read the folder | Yes. Quotas are per key; a shared key would also route users' text through the owner's account |
| Lookup answer cache | `APP_DIR/lookup_cache.json` (`lookup.py:627-629`), written on every new answer (`lookup.py:498`, `:522-529`) | JSON `{version, prompt_version, entries: {"3.2\|target\|mode\|<selected text>": answer}}`, up to 500 entries, selections up to 200 chars | High: keyed by the literal text the user selected while reading (mail, chats, documents). `.gitignore:8-9` calls it "a record of what you were reading" | Yes |
| Spooled recordings awaiting cloud transcription | `APP_DIR/pending/` (`spool.py:1-10`); drained by `main.py --drain` (`main.py:5668+`) | WAV + JSON sidecar | High: raw audio, kept indefinitely until transcribed | Yes |
| Text fragments in the status log | `APP_DIR/app.log` (`main.py:5653-5658`, INFO level `:5659`) | rotating text, 500 KB x 3 | Medium: polish logs the rejected candidate (`polish.py:457-459`, first 300 chars); punctuate logs the changed words (`punctuate.py:358-359`, `_what_changed`); lookup logs the first 40 chars of a refused selection (`lookup.py:803`); visual_qa logs answers at DEBUG only (`visual_qa.py:120-122`) | Yes |
| Questions asked of the screen | `APP_DIR/transcripts.log` (`main.py:5660-5665`; `visual_qa.py:120-121`) | rotating text | High: everything dictated | Yes (owned by the dictation subsystem, written by this one) |
| TTS scratch files | `%TEMP%/vqa-tts-*/aN.txt` + `aN.wav` + `speak.ps1` (`visual_qa.py:1176-1178`, `:1203-1208`) | UTF-8 text of the spoken answer, WAV | Medium: the answer text about a screenshot; deleted after playback, lingers if the process dies mid-speech | Transient |
| Learned glossary sent out | read from `vocab.json` via `self._vocab.glossary()` (`polish.py:284`); also `review.py:489-492` | in the system prompt to Groq | Medium: pairs of what the user says and what they meant | (belongs to the vocab subsystem; flows out through this one) |
| Quota/cooldown state | in memory only: `_cooldown/_strikes` dicts per feature (`translate.py:133-135`, `transcribers/gemini.py:68-70`, `visual_qa.py:948-950`) | dicts | none | n/a (lost on restart, so a restart re-pays one 429 per model) |

Nothing in this subsystem ever writes a key value anywhere except the provider request
header. Only the human-readable **source** ("environment variable GEMINI_API_KEY" / ".env file")
is logged (`main.py:6334-6336`, `main.py:5976`). `problems.env()` stamps model *names*
(`problems.py:291`), never keys.

## Machine-specific assumptions

- Keys live beside the code: `APP_DIR = Path(__file__).resolve().parent; ENV_FILE = APP_DIR/".env"` (`apikey.py:18-19`). The rationale is the owner's Windows Terminal `setx` problem (`apikey.py:1-8`; README.md:52-69).
- `GOOGLE_API_KEY` is accepted as a Gemini key (`apikey.py:24`), and the google-genai SDK independently reads `GOOGLE_API_KEY`/`GEMINI_API_KEY` from the environment (`.venv/Lib/site-packages/google/genai/_api_client.py:103-117`). A user with an unrelated `GOOGLE_API_KEY` set for gcloud would silently have it used.
- Lookup cache beside the code: `Path(__file__).resolve().parent / "lookup_cache.json"` (`lookup.py:627-629`).
- Ollama on the same host at `http://127.0.0.1:11434` (`config.toml:326`, `config.py:326`), IPv4 literal on purpose because this machine's `localhost` resolves to `::1` first (`config.toml:320-325`, `lookup.py:38-41`).
- Ollama models assumed pulled: `llama3.1:8b` (`config.toml:319`), `gemma3:12b` for polish/lookup/visual_qa (`config.toml:472`, `:610`, `:1538`). gemma3:12b is ~8.5 GB and the config reasons about a 16 GB card (`config.toml:1560-1562`, `:499-501`, `:447-449`).
- `lookup.keep_alive = "30m"` sized for a 16 GB card shared with Whisper (`config.toml:499-505`); it is runner-global state shared by four keys (`lookup.py:591-598`, `translate.py:204-211`).
- Timeouts tuned to an RTX 5060 Ti: `translate.ollama_timeout_s = 150` (`config.toml:328`), `polish.max_wait_s = 10` against a measured 4.7-5.5 s gemma3 answer (`config.toml:1563-1569`), `visual_qa.ollama_timeout_s = 120` (`config.toml:712`). On CPU-only hardware the repair pass would time out on every dictation and silently do nothing (`polish.py:436-446`).
- Hebrew TTS voice `Microsoft Asaf` he-IL via a PowerShell WinRT subprocess (`config.toml:659-665`, `visual_qa.py:1163-1166`, `:55-58`); absent on a machine without the he-IL speech pack.
- Provider model ids pinned to a catalog snapshot: Groq `openai/gpt-oss-120b` (`config.toml:1513-1518`), Groq vision `qwen/qwen3.6-27b` (`config.toml:619-630`, `visual_qa.py:177-179`), Gemini list `gemini-2.5-flash, gemini-flash-latest, gemini-2.5-flash-lite, gemini-flash-lite-latest` (`config.toml:1578-1583`). The thinking-knob choice is keyed on the model name prefix (`gemini_pool.py:64-77`).
- Free-tier numbers baked into comments and constants: Gemini 20 req/model/day (`gemini_pool.py:1-6`, `config.toml:1575`), cooldown 30/60 min (`gemini_pool.py:25-26`); Groq ~1,000 req/day (`polish.py:79-81`, AGENTS.md:127-128), Groq vision 8000 TPM (`visual_qa.py:43-46`, `:204-209`).
- User-Agent `deskit/1.0` hardcoded (`translate.py:374`), required by Cloudflare in front of Cerebras and Groq (`translate.py:369-373`, `visual_qa.py:48-50`).
- `Config.backend` dataclass default is `"gemini"` (`config.py:1219`) while the shipped `config.toml:196` says `"local"`. A config file missing that key would default to the cloud audio path.
- The privacy trade ("transcript text to Groq") was accepted by the **owner** personally (`polish.py:98-100`, AGENTS.md:132-136, README.md:224-227), not by a downloaded user.
- Owner's `.env` still carries a `CEREBRAS_API_KEY` for a provider whose free tier is dead (`translate.py:391-396`).

## External services and what leaves the machine

### Destinations

| # | Host | Client | Auth | Data in the request | Triggered by | Free-tier assumption | Local fallback |
|---|---|---|---|---|---|---|---|
| 1 | `https://generativelanguage.googleapis.com` (SDK default base URL, `.venv/.../google/genai/_api_client.py:799`; key sent as an `x-goog-api-key` header by the SDK) | google-genai 2.17.0 | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | **Audio** (WAV bytes) + instruction (`transcribers/gemini.py:102-108`) | `backend = "gemini"` (`transcribers/__init__.py:45-47`); also `--drain` of `pending/` and `--check` (`main.py:5972-5983`) | 20 req/model/day, 4 models rotated | local faster-whisper if `fallback_to_local` and only on `RateLimitError` (`main.py:4234-4254`, `:4338-4346`) |
| 1b | same | same | same | **Text at the cursor** (selection or whole field, up to 5000 chars) for translate (`translate.py:148-149`, `:593-596`); phone `/translate` (`server.py:333-368`, `main.py:2454-2475`) | F8 / phone | same bucket | Ollama `llama3.1:8b` (`translate.py:582-607`) |
| 1c | same | same | same | **Text** for punctuate, second in chain (`punctuate.py:268-284`); auto-punctuate every dictation if `punctuate.auto` (`main.py:2511-2555`); phone `/punctuate` | ctrl+F2 / auto / phone | same bucket | Groq first, Ollama last (`punctuate.py:184`) |
| 1d | same | same | same | **Selected text from any app** for lookup (`lookup.py:675-686`, `:897-913`), whole selection in one request (`lookup.py:239-241`) | ctrl+F8 when Ollama model is not resident and `cold_to_gemini=true` (`lookup.py:827-840`), or `prefer="gemini"`, or Ollama failed; phone `/lookup` | same bucket | Ollama `gemma3:12b` (`lookup.py:651-672`) |
| 1e | same | same | same | **Screenshot JPEG** (long side <= 1344) + question + chat history (`visual_qa.py:905-960`) | ctrl+F10 only if `allow_screenshot_upload = true` **and** `gemini_fallback = true` (`visual_qa.py:986-1004`) | same bucket | Ollama vision (`visual_qa.py:546-712`) |
| 2 | `https://api.groq.com/openai/v1/chat/completions` (`translate.py:367`, `:466`) | urllib, `Authorization: Bearer`, UA `deskit/1.0` (`translate.py:466-471`) | `GROQ_API_KEY` | **Transcript text of every dictation** >= 20 chars plus the **learned glossary** in the system prompt (`polish.py:144-179`, `:290-294`); rolling windows while the key is still held (`config.toml:1452-1456`) | polish `when="always"`, `prefer="groq"` (`config.toml:1466`, `:1476`) | ~1,000 req/day; `reasoning_effort=low`, `max_tokens >= 256` (`translate.py:549-556`) | Ollama `gemma3:12b` (`polish.py:302-311`) |
| 2b | same | same | same | **Text** for punctuate, first in chain (`punctuate.py:244-266`) | ctrl+F2 / auto / phone | same | Gemini, then Ollama |
| 2c | same | same | same | **Screenshot** as `data:image/jpeg;base64` (long side <= 896, q80) + question + history (`visual_qa.py:822-836`, `:863-880`) | ctrl+F10 only if `allow_screenshot_upload = true` | 8000 TPM, ~830 tokens per image (`visual_qa.py:43-46`) | Ollama vision |
| 2d | same | same | same | Final transcript + alternative decodes + glossary + **previous dictations as context** (`review.py:486-500`) | second reading, every dictation, up to 200/day (`config.py:1109`) | same bucket | Ollama only if `review.local_model=true` (`review.py:449-453`) |
| 2e | same | same | same | Primary + candidate decodes of a sent dictation (`study.py:323-332`) | study pass after 3 idle minutes, up to 60/day (`config.py:1029`) | same bucket | Ollama (`study.py:308-313`) |
| 2f | same | same | same | A writing prompt with a subject and up to a few names from the vocabulary (`reading.py:437-452`) | read-aloud tab when the sentence folder runs dry | same bucket | Ollama |
| 3 | `https://api.cerebras.ai/v1/chat/completions` (`translate.py:366`) | same class as Groq | `CEREBRAS_API_KEY` | transcript text (polish only) | only if `polish.prefer = "cerebras"` (`polish.py:313-324`) | **None: free tier gone, HTTP 402** (`translate.py:391-396`, `config.toml:1497-1509`) | Groq, Ollama |
| 4 | `http://127.0.0.1:11434` Ollama (`config.toml:326`) | urllib | none | `/api/chat` text or text+base64 image (`translate.py:311-336`, `visual_qa.py:686-698`); `/api/ps` probe (`lookup.py:703-704`); `/api/generate` warm (`lookup.py:742-750`); `keep_alive` (`translate.py:330-331`) | every key's fallback; first choice for lookup, visual_qa, polish when `prefer="ollama"` | n/a | is the fallback |

Outbound destinations owned by other subsystems, listed so the allowlist is complete:
Hugging Face Hub, ~1.6 GB model download on first `WhisperModel(...)` construction
(`transcribers/local_whisper.py:28`, `:243`, model id `config.py:261`); Anthropic via
`claude.exe` in the Saturday review task (`weekly_review.ps1:271-279`); pip nvidia wheels
(`requirements.txt:13-14`); Tailscale (`server.py:11-21`, inbound path for the phone);
`notify_hook.py:374` posts to `127.0.0.1` only. There is no telemetry, crash reporter, or
update check anywhere in the Python sources (grep of every `https?://` literal: only the two
provider URLs in `translate.py:366-367`, plus loopback).

### Every place a key value flows

1. `apikey.find_key()` returns the string (`apikey.py:56-62`) from `os.environ` (`:31`) or the parsed `.env` line (`:48-52`).
2. `transcribers/gemini.py:61` -> `genai.Client(api_key=api_key)` (`:71-73`). SDK holds it and sends `x-goog-api-key`.
3. `translate.py:121` -> `genai.Client(api_key=api_key)` (`:136-138`).
4. `translate.py:431-434` -> `self._key` -> `Authorization: Bearer` header (`:469`). Groq via the subclass (`:528-541`).
5. `visual_qa.py:788-794` -> `self._key` -> header (`:836`) -> `GROQ_URL/chat/completions` (`:863-867`).
6. `visual_qa.py:912-919` -> `genai.Client(api_key=api_key)`.
7. `tests.py:302-319` writes a throwaway `.env.selftest` beside `.env` with a dummy key and monkeypatches `apikey.ENV_FILE` (developer only).
8. Nowhere else. No key reaches `config.toml`, the dashboard, `problems.json`, `app.log`, `transcripts.log`, `lookup_cache.json`, `notify_hook`, or `server.py`. Error messages include the provider's response body (first 200 chars, `translate.py:476-480`), never the request.

### What the user is told today

README.md:52-77 documents the `.env` line and the Google free-tier data-use clause ("your
prompts and your audio") for the Gemini backend; README.md:224-227 documents that the repair
pass sends transcript text to Groq. There is no in-app consent screen: the first-run wizard
(`firstrun.py`) has no backend or key step (it covers microphone, a test transcription and the
hotkeys, `firstrun.py:31`, `:303-315`, `:513-528`), and the generated Settings page has no key
field (no `.env`/`api key` string in `settings.py` or `dashboard.py`; the cloud knobs it shows
are `prefer`, `groq_model`, `cold_to_gemini`, `gemini_fallback`, `gemini.models`,
`settings.py:349-391`, `:895-952`, `:1189-1212`).

## Owner-only or developer-only features

- **Cerebras backend**: `translate.py:377-526`, `polish.py:296-300`, `config.toml:1532-1536`, `settings.py:387`. Dead provider kept "for whoever holds quota".
- **CLI probes**: `--check` (validates key with one Gemini request, `main.py:5972-5983`), `--translate`, `--punctuate`, `--lookup` (`main.py:5986-6040`), `python lookup.py "text"` (`lookup.py:923-955`).
- **Test hooks**: `GroqVision.request_body()` exposed for tests (`visual_qa.py:822-836`); `.env.selftest` writer (`tests.py:302-319`); the vision-chain assertion test referenced at `visual_qa.py:110-115`.
- **Fine-tune corpus machinery** riding on Groq: `reading.py` Writer (LoRA data for the owner's voice, `reading.py:1-9`), `study.py` `corpus_keep` (`config.py:1032-1035`).
- **Measured constants** specific to the owner's hardware and the 2026-08 provider catalog (see Machine-specific assumptions).
- **The `.env` header comment** and the README's "on this machine the default is the Arctis 7" style prose (README.md:86-89).
- **The `GOOGLE_API_KEY` alias** exists for the owner's convenience (`apikey.py:24`).

## What breaks on a fresh machine

- **No `.env` and `backend = "gemini"`**: `get_transcriber` raises at startup ("fail fast: no key", `main.py:343`; `transcribers/gemini.py:61-63`), the app does not start. With the shipped `backend = "local"` (`config.toml:196`) dictation works.
- **No key at all, Ollama installed**: every feature works on Ollama, slower and VRAM-hungry; each cloud builder is skipped with one INFO line (`polish.py:337-343`, `punctuate.py:262-266`, `lookup.py:683-685`, `visual_qa.py:1010-1016`). No UI surfaces this.
- **No key and no Ollama**: translate raises "cannot reach Ollama at http://127.0.0.1:11434" (`translate.py:353-357`); punctuate raises "no punctuation backend answered" (`punctuate.py:365-366`); lookup raises "no backend could look that up ... start Ollama" (`lookup.py:892-895`); polish silently pastes the raw transcript (`polish.py:433-464`); visual_qa says "the upload gate is off, so there is no cloud fallback" (`visual_qa.py:732-738`); review falls back to structural proposals only (`review.py:442-446`); study to the consensus vote; the read-aloud Writer returns None. Startup warm-ups all log failures (`polish.py:364-388`, `lookup.py:753-755`, `visual_qa.py:4335-4337`).
- **Ollama present, models not pulled**: HTTP 404 -> "run 'ollama pull ...' or change <setting> in config.toml" (`translate.py:346-351`, `visual_qa.py:723-731`).
- **No GPU / small GPU**: gemma3:12b will not fit or runs on CPU for minutes; `polish.max_wait_s = 10` expires every time (`polish.py:436-446`), lookups hit the 150 s timeout, visual_qa the 120 s one.
- **No he-IL voice**: Speak button fails silently (`visual_qa.py:1213-1219`, `config.toml:659-665`).
- **Provider catalog drift**: a retired Groq/Gemini model id yields 404 -> `TranslationError` -> next backend (`translate.py:489-493`, `gemini_pool.py:114-119`). Users cannot fix it without editing `config.toml`.
- **Stray `GOOGLE_API_KEY` in the environment** is silently used as the Gemini key (`apikey.py:24-34`).
- **Installer placing the code under Program Files**: `.env`, `lookup_cache.json`, `pending/`, `app.log`, `transcripts.log` all sit in `APP_DIR` and need write access.
- **Cloudflare**: any change to the User-Agent string breaks Groq and Cerebras with 403 (`translate.py:369-374`).

## Settings classification

Per `config.toml` key. "user" = belongs on the Settings page for everyone; "advanced" = show under an Advanced disclosure; "developer-or-machine" = hide, derive, or drop.

**[gemini]** (`config.toml:1574-1584`)
- `models` - advanced (catalog drift; should become auto-discovered)
- `timeout_s` - advanced

**[translate]** (`config.toml:311-333`)
- `target` - user
- `max_chars` - advanced
- `ollama_model` - advanced (machine-dependent choice)
- `ollama_url` - developer-or-machine
- `timeout_s` - advanced
- `ollama_timeout_s` - developer-or-machine (hardware-derived)
- `settle_ms` - developer-or-machine

**[punctuate]** (`config.toml:334-384`)
- `auto` - user
- `max_wait_s` - advanced
- `max_chars` - advanced
- `prefer` - user, but it is really a **privacy choice** (cloud vs local) and should be driven by a consent setting
- `groq_model` - advanced
- `ollama_model` - advanced
- `nikud` - user

**[lookup]** (`config.toml:385-552`)
- `hebrew_share` - advanced
- `both_ways` - user
- `max_chars` - advanced
- `prefer` - user / privacy
- `model` - advanced (machine)
- `cold_to_gemini` - user / **privacy** (sends whatever is selected on screen to Google whenever the local model is cold; on a machine with no Ollama that is every lookup)
- `keep_alive` - developer-or-machine
- `strip_niqqud` - user
- `dwell_ms` - developer-or-machine (marked DEAD at `config.toml:522-528`; drop)
- `max_width`, `max_height` - user
- `cache_entries` - advanced
- `skip_consoles` - advanced

**[visual_qa]** (`config.toml:554-720`)
- `enabled` - user
- `visual_qa_hotkey` - user
- `allow_screenshot_upload` - user / **privacy** (keep the code-level gate)
- `prefer` - advanced
- `ollama_model` - advanced (machine)
- `groq_model` - advanced
- `gemini_fallback` - advanced
- `max_side_px` - advanced
- `num_predict` - advanced
- `speak` - user
- `voice` - developer-or-machine (derive from installed voices)
- `auto_send` - user
- `echo_to_field` - user
- `window_alpha` - user
- `warmup` - developer-or-machine
- `ollama_timeout_s` - developer-or-machine
- `cloud_timeout_s` - advanced

**[polish]** (`config.toml:1420-1573`)
- `when` - user
- `min_chars` - advanced
- `prefer` - user / **privacy** (this is the switch that sends every dictation's text to Groq)
- `groq_model` - advanced
- `groq_timeout_s` - advanced
- `cerebras_model` - developer-or-machine (dead provider)
- `cerebras_timeout_s` - developer-or-machine (dead provider)
- `ollama_model` - advanced (machine)
- `max_wait_s` - advanced (hardware-derived default)
- `warm_up` - developer-or-machine

Related keys outside the six sections that gate this subsystem: top-level `backend`
(`config.toml:196`, user / privacy: "audio to Google"), `fallback_to_local`
(`config.toml:204`, advanced), `review.local_model` and `review.llm_per_day`
(`config.py:1094-1109`, advanced), `study.llm_per_day` (`config.py:1029`, advanced).

## Dependencies and binaries

- **google-genai 2.17.0** (`requirements.txt:4`; `.venv/Lib/site-packages/google_genai-2.17.0.dist-info`) - the only third-party network SDK; used by `transcribers/gemini.py`, `translate.py::GeminiTranslator`, `visual_qa.py::GeminiVision`. Imported lazily inside constructors, so the app runs without it when no Gemini path is built (`translate.py:116-117`, `visual_qa.py:907-908`).
- **stdlib `urllib`** for Groq, Cerebras and Ollama (`translate.py:24-25`, `:332-339`, `:465-475`; `visual_qa.py:682-698`, `:860-874`; `lookup.py:49`, `:703`, `:742`). No `requests`/`httpx` in the app's own code.
- **Ollama** server binary (not pip) with `llama3.1:8b` and `gemma3:12b` pulled; the vision half of gemma3 (`visual_qa.py:36-42`).
- **PowerShell + WinRT `Windows.Media.SpeechSynthesis`** + the `Microsoft Asaf` he-IL voice, `winsound` (`visual_qa.py:1131-1219`).
- **Pillow** (`ImageGrab`, JPEG encode) for the screenshot path (`visual_qa.py:33-35`, `dashboard.py:5539-5542`).
- Internal: `transcribers.base` exceptions (`transcribers/base.py:8-25`), `vocab.words` (`polish.py:118`, `punctuate.py:65`), `ui`/`fonts` for the card.
- Provider-side requirements: a named User-Agent (`translate.py:374`); Groq `reasoning_effort` values differ per model (`translate.py:549-554`, `visual_qa.py:232-234`).

## Distribution risks

1. **Plaintext keys next to the code** (`apikey.py:18-19`). Any process, any backup, any "zip the folder and send it" leaks them; on a shared PC every account shares one key and one quota.
2. **Silent key pickup from the environment**, including `GOOGLE_API_KEY` (`apikey.py:24-34`) and the SDK's own env read (`.venv/.../_api_client.py:103-117`): a user could unknowingly bill or expose a key meant for something else.
3. **Default-on text egress without consent**: `polish.when="always"` + `prefer="groq"` (`config.toml:1466`, `:1476`) sends every dictation and the learned glossary to Groq; `review` sends previous dictations as context (`review.py:496-499`); `punctuate.prefer="groq"`; `lookup.cold_to_gemini=true` sends on-screen selections to Google. All fine for the owner, none of it consented by a downloader. This directly conflicts with the project constraint "transcript text may go to Groq/Gemini only with consent".
4. **Audio egress path exists and is the dataclass default** (`config.py:1219` `backend="gemini"`), with Google's free-tier data-use clause (README.md:71-77). A malformed or missing `backend` line flips a user to cloud audio.
5. **All-free means per-user keys**: there is no way to ship a shared key under the owner's constraints without routing users' text through the owner's account and burning one 20/day quota for everyone. Every user must obtain Groq and/or Google keys themselves; the onboarding cost is the feature's cost.
6. **Provider catalog drift** breaks pinned model ids (`config.toml:1514-1518`, `:620-623`, `visual_qa.py:177-179`); today's remedy is editing `config.toml`.
7. **Hardware-tuned defaults** (gemma3:12b, 10 s repair deadline, 30 min keep_alive) make the local fallbacks either impossible (no GPU) or useless (timeouts) on typical machines, which quietly pushes users toward the cloud legs.
8. **Dead Cerebras path** still in the Settings menu (`settings.py:387`) and config; a user who picks it gets HTTP 402 on every dictation.
9. **User text in files beside the code**: `lookup_cache.json`, `app.log` fragments, `pending/` audio, TTS temp files. An installer must relocate these to a per-user data directory and the uninstaller must know about them.
10. **No proof surface exists yet**: the code is honest (only three provider hosts plus loopback, keys only in provider headers), but nothing demonstrates it to a user, and a future Supabase client added carelessly could import `apikey` or upload `app.log`.
11. **Quota state is per feature and per process** (`translate.py:129-135`): five Gemini clients each learn a 429 separately, wasting up to 4 requests per spent model per restart.
12. **The `.env` parser is minimal** (no `export`, no `=` in values after the first) (`apikey.py:44-52`); a pasted key with trailing text silently becomes a bad key with only an HTTP 400/401 to show for it.
13. **Free-tier terms can change under users**; the README's numbers (20/day, 1,000/day) are measurements from Aug 2026, not contracts.

## Recommendations for the plan

1. **Move secrets out of the code folder and out of plaintext.** Replace `apikey.find_key` with a three-tier lookup: (a) Windows Credential Manager via `win32cred.CredRead/CredWrite` (pywin32 is already a dependency, `requirements.txt:3`), target names like `DeskIT/GROQ_API_KEY`, DPAPI-protected per Windows user; (b) environment variables **only under a DeskIT-specific prefix** (`DESKIT_GROQ_API_KEY`), dropping the `GOOGLE_API_KEY` alias; (c) a developer `.env` accepted only when a `--dev` flag or a marker file is present. Keep the `(key, source)` return shape so `main.py:6334-6336` and the CLI probes keep working.
2. **Add a Keys page to the generated dashboard** with masked paste fields, a per-provider Test button (reuse `GeminiTranscriber.check()` `transcribers/gemini.py:153-157` and a `GET /v1/models` on Groq), a "where it is stored" line, and a Remove button. Never re-display the value.
3. **One consent gate, enforced in code the way `allow_screenshot_upload` is** (`visual_qa.py:986-1004`, asserted by a test rather than a runtime `if`). Add a `[privacy]` section: `cloud_text = false`, `cloud_audio = false`, `cloud_screenshots = false`. Give `translate.py` a single `cloud_allowed(kind)` check that `GeminiTranslator`, `CerebrasTranslator/GroqTranslator`, `GeminiTranscriber`, `GroqVision`, `GeminiVision` call in their constructors and refuse to build when the gate is shut. Then `polish`, `punctuate`, `lookup`, `review`, `study`, `reading`, `server` all inherit the guarantee without per-module edits.
4. **Ship privacy-first defaults**: `polish.prefer="ollama"`, `punctuate.prefer="ollama"`, `lookup.cold_to_gemini=false`, `review.llm_per_day=0` and `study.llm_per_day=0` until a key is entered and consent given; `Config.backend` dataclass default `"local"` (`config.py:1219`). The first-run wizard gets a "Cloud" step: local only / text to Groq / text to Google / screenshots, each with the provider's data-use sentence (README.md:71-77, :224-227 already have the wording).
5. **Proof that keys never reach the owner's database**, in layers a user can check: (a) a published allowlist of exactly four hosts (`generativelanguage.googleapis.com`, `api.groq.com`, `api.cerebras.ai` if kept, `127.0.0.1:11434`) plus Hugging Face for the model download; (b) a runtime egress gateway module (`net.py`) that every outbound call goes through: wrap `urllib.request.urlopen` and pass `http_options.base_url` to `genai.Client`, refuse any host not on the allowlist, and record host + byte count (never bodies or headers) to a user-visible Network page in the dashboard; (c) a static test that `apikey` is imported only by the provider modules (the repo already uses grep-style tests, `visual_qa.py:173-175`) and that the future Supabase module never imports `apikey`, `translate`, or reads `.env`; (d) an `--audit-network` self-test that monkeypatches the gateway, exercises each feature with a fake key and asserts the destination set and that no request body or header to the Supabase host contains the fake key; (e) a reproducible, signed installer built from tagged source so the audit can be re-run by anyone.
6. **Problem-report upload must scrub.** Reuse `problems.env()` (`problems.py:274-302`, model names only) and add a redactor for key-shaped tokens (`AIza...`, `gsk_...`, `csk-...`) applied to any `app.log` excerpt; upload logs only behind their own opt-in.
7. **Handle catalog drift automatically**: on 404 for a configured model, query Groq `/v1/models` or Gemini `models.list`, choose the first match from a ranked preference list, remember it in the per-user config, and show it on the Keys page. Keep `gemini_pool.rotate` but hold one shared cooldown table per process instead of one per feature (`translate.py:129-135`).
8. **Hardware tiering at first run**: read VRAM (nvidia-smi wrapper already exists at `awake.py:642-646`) and pick Ollama models and timeouts per tier (16 GB: current; 8 GB: `gemma3:4b`/`llama3.2:3b`; CPU-only: local passes off, offer Groq with consent). Derive `polish.max_wait_s`, `*_timeout_s`, `keep_alive` instead of shipping the owner's numbers.
9. **Remove Cerebras from the user-facing surface** (`settings.py:387`, `config.toml:1532-1536`); keep the class behind a developer flag or delete it and the `CEREBRAS_API_KEY` bucket.
10. **Relocate per-user data**: `lookup_cache.json`, `pending/`, `app.log`, `transcripts.log`, the TTS scratch dir under `%LOCALAPPDATA%\DeskIT\`; make `APP_DIR` read-only after install. Keys never enter any of these today; keep a test that asserts the key string never appears in any file under the data dir after a full feature run.
11. **Show quota locally**: count requests per provider per day in memory and print "Gemini 12/80, Groq 240/1000" on the Home page; no server involvement.
12. **Write the user guide's privacy page from the allowlist and the consent flags**, in the same plain terms the config comments already use (`config.toml:566-576`, `:1449-1456`), and state the provider terms the way README.md:71-77 does.
13. **Keep audio egress explicit**: the only path is `backend="gemini"`; make it selectable only from the wizard's Cloud step after the Google data-use sentence, and keep `fallback_to_local` on so a spent quota never blocks dictation.
