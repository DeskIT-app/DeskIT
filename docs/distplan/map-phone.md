# DeskIT distribution map — Phone endpoint and Android app

Read-only survey of `server.py`, `server_token.txt` (existence only), `android/`, `config.toml [server]`,
`config.py ServerConfig`, the phone hooks in `main.py`, the dashboard's Phone block, and README
"Dictating from the phone" (lines 3371-3524). All paths are under
`C:/Users/shimr/Desktop/Organized/Projects/DeskIT` unless stated.

## Purpose

The phone records; the PC transcribes. `server.py` is a loopback-only `ThreadingHTTPServer` that runs as a
daemon thread inside the running desktop app (`main.py:771-781`, started at `main.py:2058-2064`, stopped at
`main.py:2145-2146`) and borrows the already-loaded transcriber, translator, punctuator, notify engine,
review store and lookup engine through callables (`server.py:598-633`). Reachability is delegated entirely
to Tailscale: the socket binds `127.0.0.1:8756` and `tailscale serve --bg 8756` fronts it with a real TLS
certificate at `https://<machine>.<tailnet>.ts.net/` (`server.py:1-30`, `server.py:641-663`). A bearer
token generated on first run (`server.py:97-112`) guards every POST route and `GET /review`.

Two clients exist:

1. A mobile web page served at `/` (`server.py:670-834`, Hebrew UI, hold-to-talk, copies the transcript to the
   clipboard). Needs a secure context for `getUserMedia` and `navigator.clipboard`, which is the stated reason
   for `tailscale serve` rather than bare HTTP (`server.py:20-27`).
2. An Android input-method (keyboard) app, package `com.yoav.dictation`, that commits the transcript straight
   into whatever field has the cursor, plus a Home screen, Settings, a "second reading" notification/review
   screen, and a PROCESS_TEXT "lookup" dialog (`android/app/src/main/AndroidManifest.xml:19-75`). The APK is
   sideloaded from the PC over the same link at `/app.apk` (`server.py:216-240`).

## Files and what each does

### PC side

| File | Role |
|---|---|
| `server.py` (834 lines) | The HTTP door. Constants: `APP_DIR`, `TOKEN_FILE = APP_DIR/"server_token.txt"`, `APK = APP_DIR/android/app/build/outputs/apk/debug/app-debug.apk`, `APK_GRADLE = APP_DIR/android/app/build.gradle.kts` (`server.py:66-70`). `apk_version()` regex-reads `versionName` from the gradle SOURCE file (`server.py:73-85`). `load_token()` reads or generates+writes the token (`server.py:97-112`). `_tailscale_exe()` probes PATH then two Program Files paths (`server.py:115-125`). `run_utf8()` spawns with `CREATE_NO_WINDOW` and UTF-8 decoding (`server.py:128-149`). `tailscale_name()` runs `tailscale status --json` and returns `Self.DNSName` (`server.py:152-163`). `to_wav()` decodes any container via PyAV/faster-whisper to 16 kHz mono WAV (`server.py:166-178`). `_Handler` routes (below). `PhoneServer.start()` binds, logs the URL with the token embedded (`server.py:641-663`). `PAGE` is the inline web client (`server.py:670-834`). |
| `server_token.txt` | Exists (32 bytes, dated Aug 12). Gitignored (`.gitignore` line "server_token.txt"). Shared secret for the phone AND for `notify_hook.py` (`notify_hook.py:54`). Never printed here. |
| `config.py:1112-1125` | `ServerConfig(enabled=False, host="", port=8756)`. Docstring: off by default because it opens a socket; `""` = 127.0.0.1 by design. Range check at `config.py:2149-2150`. Loaded at `config.py:1717-1720`. |
| `config.toml:1297-1308` | `[server] enabled = true, host = "", port = 8756` on the owner's machine. Its comment ("host = "" binds to the Tailscale address when it is up") is STALE relative to `server.py:642` (`host.strip() or "127.0.0.1"`) and to `tests.py:3965-3977`, which asserts loopback only. |
| `main.py:771-781` | Builds `PhoneServer` only when `cfg.server.enabled`, wiring `_transcribe_for_phone`, `_translate_for_phone`, `_punctuate_for_phone`, `_notify_from_outside`, `_review_pending_for_phone`, `_review_decide_for_phone`, `_lookup_for_phone`. |
| `main.py:2347-2404` | `_transcribe_for_phone`: transcribes with `language=None`, writes `OK | PHONE | ...` to `transcripts.log`, runs the same `_improve()` repair/context pass as the desk, saves the WAV + sidecar into `recent/` with `source: "phone"` (`main.py:388-401`; `self.recent = Spool(APP_DIR / "recent", ...)` at `main.py:356`) and submits it to the review engine with `card=False`. |
| `main.py:2406-2432` | Review store access for the phone (`review.json` via `review.Store`), verdicts written `by="phone"` and logged `REVIEW | ... | phone`. |
| `main.py:2433-2497` | Lookup / translate / punctuate for the phone: same engines as the desk keys, all logged IN/OUT to `transcripts.log`. |
| `main.py:1543-1550` | `_notify_from_outside`: forwards `/notify` bodies to the notify engine (Claude Code Stop hook uses this route with the same token, `notify_hook.py:16-19`). |
| `main.py:1760` | Status payload field `"phone": self.phone.url` — the dashboard shows and copies the token-bearing URL (`dashboard.py:7664-7690`, `dashboard.py:8091-8099`). |
| `settings.py:618-626, 655, 1143-1145, 1374-1376` | Generated Settings page: tab "Phone" with `server.enabled` and `server.port` as friendly rows; `server.host` described as "Empty means your own private network" (also stale wording). |
| `notify_hook.py:54` | Second consumer of `server_token.txt` — outside this subsystem but couples the token's location. |
| `tests.py` | ~12 phone tests (`tests.py:2884, 2940, 3023, 3052, 3129, 3187, 3942, 3951, 3965, 4938, 9405`), using `yoav.example.ts.net` fakes (`tests.py:3931`). |
| `AGENTS.md:1043` | One-line description of `server.py`. |
| `README.md:3371-3524` | The user-facing walkthrough (Tailscale on both ends, `tailscale serve --bg 8756`, open the logged URL, `/app.apk`, paste the `#t=` line, three traps). |

### Android side (`android/`)

| File | Role |
|---|---|
| `app/build.gradle.kts` | `namespace`/`applicationId = "com.yoav.dictation"`, `compileSdk 34`, `minSdk 26`, `targetSdk 34`, `versionCode = 12`, `versionName = "1.1.0"` (lines 7-20). Comment at 16-18 documents the three-number scheme. `release { isMinifyEnabled = false }` with a comment that unsigned release builds cannot be installed and the debug build is the only sideloadable one (23-29). Zero dependencies (`dependencies { }`, line 37). |
| `build.gradle.kts` | AGP 8.5.2, Kotlin 1.9.24. |
| `settings.gradle.kts` | `rootProject.name = "DeskIT"`, `include(":app")`. |
| `gradle.properties` | `android.useAndroidX=false`, 2 GB heap. |
| `local.properties` | `sdk.dir=C:/Users/shimr/dev-tools/android-sdk` — machine-local, gitignored. |
| `app/src/main/AndroidManifest.xml` | Permissions: RECORD_AUDIO, INTERNET, POST_NOTIFICATIONS (4-7). `allowBackup="false"` (14), `networkSecurityConfig` (13). Components: `HomeActivity` (launcher), `SettingsActivity`, `ReviewActivity`, `LookupActivity` (PROCESS_TEXT, text/plain), `ReviewReceiver`, `DictationIme` service with BIND_INPUT_METHOD (19-75). |
| `res/xml/network_security_config.xml` | `cleartextTrafficPermitted="false"` globally; cleartext allowed only to `10.0.2.2` (emulator host alias). HTTPS is therefore mandatory for any real phone. |
| `res/xml/method.xml` | One IME subtype, locale `he_IL`, settings activity = `SettingsActivity`. |
| `res/values/strings.xml` | All UI strings, English. Several mention Tailscale by name: `unreachable` (83), `unreachable_line` (99), `setup_intro` (115). |
| `res/values/styles.xml`, `colors.xml`, `Skin.kt`, `LampView.kt` | LAMPLIGHT theme; palette copied from `skin/palette.py`; Rubik font bundled (SIL OFL, `Skin.kt:29-33`). |
| `res/font/rubik*.ttf`, `mipmap-*` | Bundled font and adaptive icon. |
| `Prefs.kt` | SharedPreferences store (details below). **`DEFAULT_URL = "https://yoav.example.ts.net"` at line 25** — the owner's MagicDNS name baked in as the default server address, with a docstring (8-11) saying the defaults are "this user's own machine". `parsePasted()` splits a pasted `https://host/#t=token` line (130-136). |
| `Transcriber.kt` | All HTTP via `HttpURLConnection`, no third-party libs (10-13). Routes: `/transcribe` (32-33, 120 s read timeout), `/punctuate` (48-53, 180 s), `/translate` (69-74, 180 s), `/health` (84-98, unauthenticated), `/review` GET (142-159), `/review/decide` (162-168), `/lookup` (176-181). Error text on IOException: "can't reach the PC — is Tailscale on?" (219). |
| `Recorder.kt` | `AudioRecord` 16 kHz mono PCM in memory, `MAX_SECONDS = 300` (about 9.6 MB WAV), silence detection. |
| `DictationIme.kt` (1295 lines) | The keyboard: hold/lock/discard gestures, action key from `EditorInfo`, refuses password / `NO_PERSONALIZED_LEARNING` fields (`isPrivate`, 638-655), health preflight throttled to once a minute (`checkHealth`, 725-745, `HEALTH_TTL_MS`, 1293), sends WAV (`send`, 880-890), places text or keeps it pending, `Prefs.addSaid` on success (904), schedules three review polls at 20/60/150 s (916-930), translate/punctuate on the field (1015-1075), `MAX_FIELD = 4000` (1288). No `Log.` calls anywhere in the Kotlin sources (grep returned nothing). |
| `HomeActivity.kt` | Launcher screen: `/health` check + `Notify.poll` (179-208), update pill opens `${Prefs.url}/app.apk` in the browser (108-111), setup steps (mic, keyboard enabled, token present, notifications), pending proposals, "What you said" list with clipboard copy (320-374). |
| `SettingsActivity.kt` | URL + token fields (77-82), "Save and test" posts one second of silence to `/transcribe` (195-214), switch-back toggle, reset key order, system keyboard settings, "Check for an update" compares `/health.apk` against installed `versionName` and opens `$url/app.apk` (222-241). |
| `Notify.kt` | Notification channel `second_reading`, `poll()` rings once per proposal id (`Prefs.markNotified`), Keep/No actions via `ReviewReceiver` posting `/review/decide` (123-151). |
| `ReviewActivity.kt` | One proposal: struck/lit text, Keep / No. |
| `LookupActivity.kt` | PROCESS_TEXT dialog; posts the selection to `/lookup`, shows the answer, Copy/Close; writes nothing (17-27). |
| `tools/emu.py` | Headless emulator driver. Hard-codes `SDK`, `JDK`, `APK` under `C:\Users\shimr\...` (19-24), AVD `deskit`, DNS `100.100.100.100` (75). Developer-only. |
| `tools/fake_pc.py` | Runs the real `PhoneServer` with fake hooks on `127.0.0.1:8790`; `sys.path.insert` and `config.load` use absolute `C:\Users\shimr\...` paths (13, 22). Developer-only. |
| `app/build/outputs/apk/debug/app-debug.apk` | 1.2 MB, built 2026-09-13 15:24, `versionCode 12 / 1.1.0` per `output-metadata.json`. Gitignored; the artifact `/app.apk` serves. |

No `gradlew` wrapper is committed; the build is `gradle assembleDebug` with a machine-local JDK 17, SDK 34 and Gradle 8.9 under `C:\Users\shimr\dev-tools` (per the owner's memory notes; no build script exists in the repo).

### HTTP routes (all in `server.py`)

| Method | Path | Auth | Handler | Notes |
|---|---|---|---|---|
| GET | `/` | none | `do_GET` 214-216 | Serves `PAGE`. Token arrives in `#t=` and is moved to `localStorage['dictationToken']` (686-693). |
| GET | `/app.apk` | none (deliberate, 219-222) | 217-240 | 404 JSON if not built. `Content-Disposition: attachment; filename="DeskIT-<versionName>.apk"`, `Cache-Control: no-store`, ETag = mtime. Reads whole file into memory. |
| GET | `/health` | none | 241-244 | `{ok, backend: <transcriber name>, apk: <versionName or null>}`. |
| GET | `/review` | Bearer | `_do_review_pending` 437-460 | ALL pending proposals (desk and phone), with `review.snippet()` parts. |
| POST | `/transcribe` | Bearer | `_do_transcribe` 306-330 | Any audio container -> WAV -> `transcribe()`; returns `{text, seconds, backend[, warning]}`. |
| POST | `/translate` | Bearer | `_do_translate` 332-364 | JSON `{text}`; refuses > `translate.max_chars` and text with no Hebrew. |
| POST | `/punctuate` | Bearer | `_do_punctuate` 366-419 | JSON `{text}`; 409 `unsafe: true` when the model rewrote words. |
| POST | `/notify` | Bearer | `_do_notify` 421-434 (docstring 383-395) | Notification cards from other programs (Claude Code hook). |
| POST | `/review/decide` | Bearer | `_do_review_decide` 462-527 | `{id, verdict: accepted|rejected}` -> store, `by="phone"`. |
| POST | `/lookup` | Bearer | `_do_lookup` 529-562 | `{text}` -> F8 engine; 400 with classify reason. |
| any other | | | 404 JSON | Unknown POST path is 404 before auth (277-281); auth failure is 401 and logged with the client IP (282-286). |

Body limit `MAX_BODY = 32 MiB` (`server.py:91`). Auth is constant-time compare of a `Bearer` header (`server.py:204-209`). `server_version = "DeskIT"` (`server.py:181`).

## Personal data stores

| What | Where | Format | Sensitivity | Must be per-user? |
|---|---|---|---|---|
| Phone bearer token | PC: `<code dir>/server_token.txt` (`server.py:67`) | plain text, `secrets.token_urlsafe(24)` | High: full access to transcribe/translate/lookup/review/notify on that PC | Yes — generated per install; must move out of the code folder into a per-user data dir |
| Phone bearer token + server URL | Phone: SharedPreferences file `dictation`, keys `url`, `token` (`Prefs.kt:14-16, 55-58, 71-77`) | XML prefs, `MODE_PRIVATE`, `allowBackup=false` (`AndroidManifest.xml:14`) | High (token), Medium (hostname reveals tailnet name) | Yes — already per-phone |
| Phone token (web page) | Phone browser `localStorage['dictationToken']` (`server.py:686-693`) | string | High | Yes |
| Token embedded in a URL | PC `app.log` via `log.info("open this on the phone: %s")` (`server.py:653-654`); dashboard status field `phone` and clipboard on "Copy link" (`main.py:1760`, `dashboard.py:8091-8099`) | log line / clipboard | High: the secret sits in a log file that the problems/notify machinery may quote | Yes |
| Phone dictations, transcript text | PC `transcripts.log` lines `OK | PHONE | ...`, `TRANSLATE-IN/OUT | phone`, `PUNCTUATE-IN/OUT | phone`, `LOOKUP-IN/OUT | phone`, `REVIEW | ... | phone` (`main.py:2367-2368, 2431, 2445-2452, 2474-2477, 2495-2498`) | text log | High: everything dictated, translated, punctuated or looked up from the phone | Yes |
| Phone dictation AUDIO + sidecar | PC `recent/` via `Spool(APP_DIR / "recent")` (`main.py:356`, `main.py:388-397`), sidecar `{text, raw, backend, language, words, source: "phone"}` | WAV + JSON | High: raw voice recordings kept on the PC's disk | Yes |
| Second-reading proposals from phone clips | PC `review.json` / `review.lock` (via `review.Store`, `main.py:2413-2416`) | JSON | High: sentences and proposed corrections | Yes |
| Corrections accepted from the phone | PC `vocab.json` (learned on the review engine's next wake, `main.py:2422-2431`) | JSON | Medium/High | Yes |
| "What you said" — last 30 phone transcripts | Phone SharedPreferences key `said` (`Prefs.kt:19, 23, 85-108`) | JSON array `[[epoch_ms, text], ...]` | High: dictated text on the phone, user can Clear | Yes |
| Rung proposal ids | Phone SharedPreferences key `notified`, max 100 ids (`Prefs.kt:20, 115-123`) | comma list | Low | Yes |
| Key order, switch-back flag | Phone SharedPreferences keys `key_order`, `switch_back` (`Prefs.kt:17-18`) | string / bool | Low | Yes (preference) |
| Notify payloads relayed through `/notify` | PC `notify.json` / `notify.log` (per `config.toml:1092-1094`) | JSON/log | Medium (titles/bodies from other programs) | Yes (other subsystem) |
| Downloaded APK | Phone `Downloads/DeskIT-<version>.apk` (`server.py:233-235`) | binary | Low | n/a |
| Emulator artifacts | `~/.android/avd/deskit.avd`, `android/tools/emu.log`, `fake_pc.log` (`tools/emu.py:61, 70`; `tools/fake_pc.py:18`) | misc | Low | Developer-only |

Note: the phone app itself keeps no audio on disk — recordings live in memory (`Recorder.kt` buffer; `DictationIme.lastWav`) and are discarded after delivery (`DictationIme.kt:903`).

## Machine-specific assumptions

- `android/app/src/main/java/com/yoav/dictation/Prefs.kt:25` — `DEFAULT_URL = "https://yoav.example.ts.net"`: the owner's MagicDNS host is the default server for every install of the APK. Docstring 8-11 explicitly assumes "this user's own machine".
- `android/app/build.gradle.kts:7, 11` — `com.yoav.dictation` as namespace and applicationId (owner's name in the package id); also in `AndroidManifest`-referenced class names, `method.xml:3`, `Notify.kt:34` (`com.yoav.dictation.DECIDE`), `tools/emu.py:30`.
- `android/local.properties:6` — `sdk.dir=C:/Users/shimr/dev-tools/android-sdk` (gitignored, but required to build).
- `android/tools/emu.py:19-24` — absolute `C:\Users\shimr\dev-tools\{android-sdk,jdk}` and the absolute APK path; `tools/fake_pc.py:13, 22` — absolute repo path for `sys.path` and `config.toml`.
- `server.py:66-70` — token, APK and gradle file are all resolved relative to the CODE folder (`APP_DIR = Path(__file__).resolve().parent`); the APK path assumes the Android source tree AND its `build/` output live next to the Python app.
- `server.py:118-124` — Tailscale probed at `C:\Program Files\Tailscale\tailscale.exe` and `(x86)`; Windows-only paths.
- `server.py:135-139` — locale codepage note (cp1255) explains the forced UTF-8 decode; not a bug but a Hebrew-Windows assumption.
- `server.py:641-642, 656-660` — without Tailscale the printed URL is `http://127.0.0.1:8756/#t=...`, which no phone can reach, and the log says "Log in to Tailscale, then restart".
- `config.toml:1297-1308` — `[server] enabled = true` on the owner's copy while the code default is `False` (`config.py:1117`).
- `android/app/src/main/res/xml/network_security_config.xml:8-10` — cleartext only to `10.0.2.2`; a stranger's LAN address over plain HTTP is refused by the OS.
- `android/app/src/main/res/values/strings.xml:83, 99, 115` — user-facing text names Tailscale as the transport.
- `README.md:3471-3490` — setup steps assume the same Tailscale account on PC and phone, and reading the token out of `app.log`.
- `tests.py:3931, 16447` — test fixtures use `yoav.example.ts.net` (harmless, but owner-named).
- Debug signing: the served APK is the `debug` variant (`server.py:68-69`, `build.gradle.kts:25-27`), signed by the owner machine's `~/.android/debug.keystore`. Any APK built elsewhere has a different signature and cannot upgrade an install of this one.

## External services and what leaves the machine

- **Tailscale** (`tailscale.exe`, `tailscale serve`): the app only shells out to `tailscale status --json` to learn its own DNS name (`server.py:152-163`); it does not configure Serve itself (the README tells the user to run `tailscale serve --bg 8756` once, `README.md:3475-3480`). Traffic phone<->PC goes over the user's tailnet, TLS-terminated by Tailscale with a Let's Encrypt certificate (`README.md:3506-3510`). Optional in code (falls back to a loopback URL) but mandatory in practice for a real phone. No key; requires a Tailscale account on both devices. Free tier is enough.
- **Phone -> PC** (over the tailnet): raw WAV audio (`Transcriber.kt:32-33`), field text for translate/punctuate (`DictationIme.kt:1015-1022`), selected text for lookup (`LookupActivity.kt:89`), review verdicts. Nothing goes anywhere else from the phone: no analytics, no third-party SDKs (`build.gradle.kts:37`), no logcat output.
- **PC -> cloud, indirectly**: a phone dictation runs the same `_improve()` chain as a desk one (`main.py:2372`): vocabulary repair (local) then `_context_pass` -> polisher (`main.py:5105-5130`), which may reach Ollama / Groq / Gemini depending on `[polish]` config. `/translate` and `/lookup` reuse the desk's Gemini-then-Ollama engines (`main.py:2454-2477`, `2433-2452`); `/punctuate` the desk Punctuator. So transcript TEXT from the phone can reach Groq/Gemini exactly as desk text does, under the same consent settings — audio never does (local ASR). The web page shows the `backend` string returned by the PC (`server.py:772`), and the keyboard shows it in the status line (`DictationIme.kt:933-935`).
- **Hugging Face / CUDA**: not touched by this subsystem directly; it borrows the loaded model.
- **Let's Encrypt**: through Tailscale's certificate provisioning, no key needed.

## Owner-only or developer-only features

- `android/tools/emu.py` and `android/tools/fake_pc.py`: headless emulator driver and fake PC for screenshot checks; absolute owner paths; belong in a dev-tools folder, not in a shipped package.
- `/notify` route and its coupling to the Claude Code Stop hook (`notify_hook.py:16-19, 54`): the token file location is shared with developer tooling. For end users `/notify` is at most an "other programs can ping you" feature.
- `/app.apk` self-hosting of the APK from the source tree's `build/` directory (`server.py:68-69, 217-240`): a developer convenience that assumes the user builds the APK on the same PC. End users will not have Gradle, a JDK or an SDK.
- `apk_version()` reading `versionName` out of `build.gradle.kts` (`server.py:73-85`): reports the SOURCE version, not the built APK's, so `/health.apk` and the download filename can disagree with the file served (the memory notes record exactly this: strings renamed 09-06, served APK built 08-29).
- The dashboard's Phone block's "Copy link" copies the token-bearing URL (`dashboard.py:8091-8099`) — fine for one owner, but for users the token should be pairable without exposing it in logs.
- `tests.py` phone tests and the `yoav.example.ts.net` fixtures.
- The Hebrew-only web page at `/` (`server.py:670-834`): the owner has since made the phone app English end to end (`strings.xml:6-8, 87-89`); the page is the older client.

## What breaks on a fresh machine

1. **No Tailscale** -> `tailscale_name()` returns None -> URL is `http://127.0.0.1:8756/#t=...` and the log says the phone cannot reach it (`server.py:656-660`). The Android app refuses plain HTTP to anything but `10.0.2.2` (`network_security_config.xml`), so even a LAN IP would fail. Hard stop.
2. **Tailscale installed but Serve not enabled / tray app not running / first cert fetch**: three documented traps (`README.md:3495-3510`), each of which looks like a network error.
3. **`[server] enabled` defaults to false** (`config.py:1117`): the endpoint does not exist until the user flips it (dashboard Phone tab, `settings.py:618-624`), then restarts.
4. **Prefs.DEFAULT_URL** points at the owner's tailnet (`Prefs.kt:25`): a stranger who installs the APK and opens Settings sees the owner's hostname pre-filled (`SettingsActivity.kt:77`), and Home's health check goes to the owner's host until a token is saved (`HomeActivity.kt:180-181`; the check short-circuits on empty token, but the URL field still shows it).
5. **No APK to serve**: `/app.apk` answers 404 "no APK built yet" unless `android/app/build/outputs/apk/debug/app-debug.apk` exists next to the code (`server.py:222-224`). Building it needs JDK 17 + SDK 34 + Gradle 8.9 (no wrapper committed) + `local.properties`.
6. **Signature mismatch**: an APK built on another machine is debug-signed with a different key; Android refuses to install it over an existing one ("app not installed" / signature conflict) and Play Protect flags unknown debug APKs.
7. **`server_token.txt` written into the code folder** (`server.py:67, 111`): fails under a read-only Program Files install; a per-user data directory is needed.
8. **Port 8756 busy**: `PhoneServer.start()` raises, main.py logs a warning and disables the phone (`main.py:2058-2064`); no UI tells the user beyond the dashboard's "not running" text.
9. **PyAV / faster-whisper import** inside `to_wav` (`server.py:170-172`): a build without faster-whisper (e.g. cloud-only ASR) breaks every `/transcribe` with a 400 "could not decode".
10. **`tailscale.exe` location**: only PATH and two fixed Program Files paths are probed (`server.py:118-124`); a per-user install elsewhere reads as "Tailscale not up".
11. **`cp1255` assumption** is handled (forced UTF-8), no break.

## Settings classification

`[server]` has three keys (`config.toml:1297-1308`, `config.py:1112-1125`):

| Key | Class | Reasoning |
|---|---|---|
| `server.enabled` | **user** | "Dictate from the phone" on/off; already a friendly row on the Phone tab (`settings.py:620-622`). |
| `server.port` | **advanced** | Only matters on a port collision; shown as friendly (`settings.py:623-624`) but should move to advanced with a "restart needed" note. |
| `server.host` | **developer-or-machine** | Must stay `""`/loopback for `tailscale serve` (`tests.py:3965-3977`); exposing it invites binding the LAN. If a LAN pairing path is added, this becomes a user-facing "Reach it over: Tailscale / home Wi-Fi" choice rather than a raw address. |

Not in config.toml today but effectively settings: the token (file), the Tailscale hostname (derived), and on the phone: `url`, `token`, `switch_back`, `key_order` (all per-phone SharedPreferences, `Prefs.kt`). Recommend adding user-level `server.transport = "tailscale" | "lan" | "off"` and keeping the token out of TOML.

## Dependencies and binaries

PC:
- Python stdlib `http.server.ThreadingHTTPServer`, `secrets`, `subprocess` (`server.py:34-43`).
- `faster_whisper.audio.decode_audio` (PyAV bundled) and `numpy` for `to_wav` (`server.py:170-172`); `recorder.frames_to_wav` (`server.py:174`).
- `review.snippet`, `review.is_rtl` for `/review` payloads (`server.py:568-583`); `translate.needs_translation`, `punctuate.needs_punctuation`/`UnsafeReply` (`server.py:352-354, 397-399, 409`).
- `tailscale.exe` (external, optional-in-code), `tailscale serve` (user-run once).
- Windows-only `creationflags=0x08000000` guarded by `sys.platform` (`server.py:63`).

Android:
- Kotlin 1.9.24, AGP 8.5.2, compile/target SDK 34, min SDK 26, no AndroidX, no libraries (`build.gradle.kts`, `gradle.properties`).
- Build toolchain not in repo: JDK 17, Android SDK 34 (build-tools 34.0.0), Gradle 8.9; `local.properties` per machine.
- Bundled Rubik font (SIL OFL, `Skin.kt:29`).
- Runtime permissions: RECORD_AUDIO, POST_NOTIFICATIONS (API 33+), IME enablement in system settings.

## Distribution risks

1. **Owner hostname in every APK** (`Prefs.kt:25`): leaks the owner's tailnet name and, if a stranger ever shared a tailnet with the owner, would point their keyboard at the owner's PC. Must be removed before any public build.
2. **Package id `com.yoav.dictation`**: renaming later forces every user to uninstall/reinstall (new app identity, lost prefs). Decide the final applicationId before the first public build.
3. **Debug-signed sideload**: no keystore, no release build (`build.gradle.kts:23-29`). Users get Play Protect warnings, and updates from a different build machine will not install over the old one. Needs a real release keystore (free) kept by the owner, and ideally a store or a signed GitHub Release.
4. **Token in logs and clipboard**: the URL with `#t=<token>` is written to `app.log` at every start (`server.py:653-654`), surfaced in the dashboard, and copied to the clipboard on request. The problems/report machinery quotes logs. For users, a leaked token = anyone on their tailnet can transcribe on their PC and read pending review sentences.
5. **Unauthenticated `/health` and `/app.apk`** (`server.py:217-244`): leaks the transcriber backend name and version, and serves the APK to anyone on the tailnet. Acceptable on a personal tailnet; on a shared tailnet (family/company) it is a small info leak and an unsigned binary drop.
6. **`GET /review` returns ALL pending proposals** (`server.py:437-448`): any device holding the token sees desk sentences too. Fine for one person; matters if a household shares a PC account.
7. **Mandatory Tailscale**: a free account, an app install on both devices and one console command (`tailscale serve`) with the three traps in `README.md:3495-3510`. That is the single biggest onboarding cliff for non-technical users. The plan must either script it (`tailscale serve --bg` from the app with the user's yes), or offer a LAN path.
8. **APK hosted from the source tree** (`server.py:68`): end users will not have `android/app/build/...`; the PC installer must ship the APK as a data file, or the phone must fetch it from a public release URL.
9. **Version truth**: `/health.apk` and the download name come from the gradle file, not the artifact (`server.py:73-85`); with a shipped APK file the version should be read from the APK (or a sidecar `version.json`) so update prompts are honest.
10. **Phone audio lands on the PC disk** (`recent/`, `main.py:388-397`) and phone text in `transcripts.log`; the privacy story ("audio never leaves your machine") has to be phrased as "never leaves YOUR devices", and the retention (`vocab.keep_audio`) exposed as a user setting.
11. **Web page (`/`) is Hebrew-only and unauthenticated for the page itself**; its token lives in browser localStorage. If it stays, it needs the English chrome rule and a "forget this phone" action.
12. **Tests assume loopback binding** (`tests.py:3965-3977`); a LAN option changes a tested invariant.
13. **`config.toml` comment drift** on `host` (`config.toml:1302-1304`, `settings.py:1143-1145`) will confuse a Settings page that is generated from those comments.

## Recommendations for the plan

1. **Pairing without the owner's identity.** Delete `DEFAULT_URL` (`Prefs.kt:25`) — default to empty, Home shows "Not set up yet" (already handled at `HomeActivity.kt:182-185`). Replace "paste the log line" with a **QR code** on the dashboard's Phone block encoding `https://<host>/#t=<token>`; the app gets a "Scan" button (camera permission + a tiny inline QR decoder, or `ZXing` via intent — check the no-dependency constraint). Keep `parsePasted()` as the fallback.
2. **Transport choice, documented as two paths.**
   - *Tailscale (recommended, encrypted, works away from home)*: the PC app detects `tailscale.exe`, and on the user's click runs `tailscale serve --bg <port>` itself (with the "Serve not enabled -> click the link" flow surfaced in the UI). The three README traps become three status lines on the Phone tab.
   - *Home Wi-Fi (no account)*: bind `0.0.0.0`/LAN only when `server.transport = "lan"`, generate a self-signed cert on first run and **pin its fingerprint in the QR payload**; the Android app installs it as a per-connection `TrustManager` (the IME does not need a browser-grade secure context, only the web page does). Cleartext stays forbidden (`network_security_config.xml`). Windows Firewall prompt appears once; document it. The web page `/` would not work on this path (getUserMedia) — say so, or drop the page.
3. **Token lifecycle.** Move `server_token.txt` to the per-user data dir (with `config.toml` and history); add "Rotate phone token" and "Forget phones" buttons; stop logging the full URL at INFO (`server.py:653-654`) — log the host only, and show the token only inside the QR / a click-to-reveal field. Give the phone a "Forget this PC" action that clears `url`/`token`/`said`.
4. **APK delivery for users.** Ship a **release-signed** APK (owner keeps one keystore; free) as a data file inside the Windows installer, e.g. `<install>/phone/DeskIT-<ver>.apk`, and serve it from there (`server.py:68`); also publish the same file as a GitHub Release asset so a phone can fetch it without the PC. Read the version from the APK's `AndroidManifest` (or a `version.json` written by the build) rather than `build.gradle.kts` (`server.py:73-85`). Keep `versionCode` monotonic; keep `versionName` three numbers as decided (`build.gradle.kts:16-20`).
5. **Package id.** Pick a neutral final id now (e.g. `app.deskit.keyboard`) and change `namespace`/`applicationId`, `Notify.kt:34`, `method.xml:3`, `tools/emu.py:30`. Do it before the first outside install; it cannot be changed afterwards without an uninstall.
6. **Route hygiene for shared tailnets.** Make `/app.apk` and `/health`'s `backend` field token-gated or reduce `/health` to `{ok, apk}`; scope `GET /review` to `source == "phone"` unless a "show desk proposals too" preference is on.
7. **Privacy copy + settings.** A "Phone" section in the user guide stating: audio goes phone -> your PC only; the PC keeps clips in `recent/` for N days (expose `vocab.keep_audio` as "Keep phone recordings for"), text in `transcripts.log`; cloud passes (Groq/Gemini/Ollama) apply to phone text exactly as to desk text under the same consent toggles. Add the same password-field refusal note the app already implements (`DictationIme.kt:628-655`).
8. **Settings page.** Keep `server.enabled` user-level; move `server.port` to advanced; replace `server.host` with `server.transport` and fix the stale comments in `config.toml:1302-1304` and `settings.py:1143-1145` so the generated page tells the truth (loopback + Tailscale, or LAN).
9. **Cut from the shipped tree.** `android/tools/`, the phone tests' owner fixtures, and the `/notify`-for-Claude coupling belong to the developer repo, not the installer. `notify_hook.py` can keep using the token if it reads it from the new per-user location.
10. **Web page decision.** Either retire `/` (the keyboard is "the way to use this", `README.md:3385-3389`) or translate its chrome to English per the UI rule and give it a "forget token" button. Retiring it simplifies the LAN path (no secure-context requirement).
11. **Fresh-machine checklist for the installer**: firewall rule only for LAN mode; Tailscale detection; "Phone: not set up" state on the dashboard with the QR; APK present; token file created in the data dir; first `/health` self-test from the PC itself.
