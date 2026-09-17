# keys-privacy

**Question:** Bring-your-own-API-key desktop apps: how to store Gemini/Groq keys on Windows (Credential Manager via keyring, DPAPI file, plain file with ACLs), how open-source BYOK apps word the "keys never reach the developer" guarantee, technical evidence a user can verify, Gemini/Groq terms for third-party apps using a user's own key (incl. Gemini free-tier training clause), Israel Privacy Protection Law Amendment 13 duties for a solo developer, and a concrete design + wording for DeskIT's guarantee.

Researched 2026-09-16. Findings appended per source as read.

## Findings

### Search pass 1 (summaries, to be verified on primary pages below)
- Gemini API Additional Terms: Unpaid Services (AI Studio + unpaid API quota) content is used "to provide, improve, and develop Google products and services and machine learning technologies"; human reviewers may read/annotate; "Do not submit sensitive, confidential, or personal information to the Unpaid Services." Paid Services: prompts/responses not used to improve products. (https://ai.google.dev/gemini-api/terms)
- Groq: no default retention, no training on customer inputs/outputs; troubleshooting/abuse logs up to 30 days; self-serve Zero Data Retention in Data Controls. (https://console.groq.com/docs/your-data)
- Israel Amendment 13 in force 14 Aug 2025; personal data now explicitly includes IP addresses / online identifiers; DPO required "in defined cases"; extraterritorial for Israeli residents' data. (loc.gov, natlawreview, pearlcohen)
- keyring WinVault: CRED_MAX_CREDENTIAL_BLOB_SIZE ~2560 bytes, stored as UTF-16 so ~1280 chars; keyring issue #540. API keys (Gemini ~39 chars, Groq ~56 chars) fit easily. DPAPI CryptProtectData: same per-user protection, no size cap, via pywin32 win32crypt.
- Obsidian Developer policies: "network usage must be clearly disclosed", link to privacy policy required, client-side telemetry prohibited. Obsidian has SecretStorage API for plugins (docs.obsidian.md/plugins/guides/secret-storage).
- Jan: AGPLv3, "runs entirely offline". Cline: stores provider keys in VS Code secret storage.

### Primary: Gemini API Additional Terms (https://ai.google.dev/gemini-api/terms, "Last updated 2026-04-28 UTC")
- Unpaid Services / How Google Uses Your Data: "When you use Unpaid Services, including, for example, Google AI Studio and the unpaid quota on Gemini API, Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products and services" ... "To help with quality and improve our products, human reviewers may read, annotate, and process your API input and output." ... "Do not submit sensitive, confidential, or personal information to the Unpaid Services."
- Paid Services: "Google doesn't use your prompts (including associated system instructions, cached content, and files ...) or responses to improve our products".
- No explicit clause found on this page forbidding an end user from pasting their own key into a third-party app (the terms bind the key holder = the user; DeskIT is the user's tool). UNCERTAINTY: the Google APIs ToS (developers.google.com/terms) has general "do not share credentials" language that I could not verify here.
- Consequence for DeskIT: transcript text sent through the user's free-tier Gemini key IS used for training and may be read by humans. Must be disclosed in the settings UI at the moment the key is pasted, not only in the policy.

### Primary: Groq "Your Data in GroqCloud" (https://console.groq.com/docs/your-data, undated)
- "By default, Groq does not retain customer data for inference requests."
- "We may temporarily log inputs and outputs only when: Troubleshooting errors that degrade platform reliability, or Investigating suspected abuse (e.g. rate-limit circumvention). These logs are retained for up to 30 days."
- "All customers may enable Zero Data Retention (ZDR) in Data Controls settings. When ZDR is enabled, Groq will not retain customer data for system reliability and abuse monitoring."
- Training clause is in the Services Agreement (console.groq.com/docs/legal/services-agreement), not on this page - see below.

### Primary: keyring issue #540 (https://github.com/jaraco/keyring/issues/540)
- Windows Credential Manager password limit "1280 max for the password" (CredWrite, UTF-16 => 2560 bytes). Chunking PR #763 linked, issue still open. Irrelevant for 40-60 char API keys; relevant only if DeskIT ever stores a Supabase session JWT (~800-1200 chars) there - store that in a DPAPI file instead.

### Dead links (do not reuse): docs.obsidian.md/Developer+policies (404 on fetch), jan.ai/docs/privacy (403), docs.continue.dev/telemetry (redirect).

### Primary: Groq Services Agreement (https://console.groq.com/docs/legal/services-agreement, "Last Modified: June 22, 2026")
- s4.2: "Groq is not permitted to use Inputs or Outputs for training or fine-tuning any AI Model Services or other models, unless explicitly granted permission or instructed by Customer."
- s3.2: Customer "is responsible for ... the security of its passwords for the Account (including any keys for Groq's APIs)". => the key holder (DeskIT user) is the Customer; DeskIT is their client software. No clause found forbidding use of a personal key inside a third-party desktop app.
- s6.2: Customer "has obtained all necessary consents and provided all required notices" for its use. For BYOK, that is the user's own duty; DeskIT's guide should say so.

### Cline (github.com/cline/cline discussions #2904, agent-safehouse.dev report)
- Keys stored via VS Code SecretStorage (Electron safeStorage -> DPAPI on Windows, SQLite DB). Standalone CLI mode: plain JSON at ~/.cline/data/secrets.json (documented as a known gap). No standalone "keys never reach us" privacy sentence located.
### Msty / AnythingLLM / Open WebUI (secondary sources only)
- Msty: closed source, "zero telemetry, local-first" as policy only. AnythingLLM and Open WebUI: open source, auditable; AnythingLLM has opt-out anonymous telemetry (to verify). Lesson: closed-source claims are "a policy you trust"; the credible version is open source + auditable network behaviour.
### Verifiable egress (pipelab.org/learn/verifiable-egress-control, github.com/glatinone/pipelock)
- Pattern: every outbound call mediated by one chokepoint that logs a signed receipt; reproducible builds (Signal, Tor) let users confirm binary == source. For a solo Python app the practical subset: single HTTP client module with a hard-coded host allowlist, a unit test that fails on any new host, an in-app "Network" tab showing every request (host, bytes, purpose), and GitHub Actions build with SLSA/attestation so the .exe is traceable to a commit.

### Primary: Microsoft CryptProtectData (learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata, updated 2026-05-15)
- "Typically, only a user with the same logon credential as the user who encrypted the data can decrypt the data. In addition, the encryption and decryption usually must be done on the same computer."
- CRYPTPROTECT_LOCAL_MACHINE: "Any user on the computer ... can use CryptUnprotectData to decrypt" - do NOT use it.
- pOptionalEntropy: extra secret mixed in; without it ANY process running as the same user can decrypt (same limitation as Credential Manager - both are "per-user", not "per-app"). MAC included (tamper-evident). Prompt-struct flow deprecated, removal Feb 2027 - pass NULL.
- NOTE: pywin32's win32crypt.CryptProtectData exposes this; keyring's WinVault also rides on DPAPI. So security level of Credential Manager == DPAPI file; difference is discoverability (Credential Manager UI lists entries; a DPAPI file is opaque) and the 1280-char cap.

### Primary: Gemini "Data logging and sharing" (https://ai.google.dev/gemini-api/docs/logs-policy)
- Logging feature is opt-in and only for billing-enabled projects; "prompts and responses within logs are not used for product improvement" unless the dev shares datasets. Retention 55 days default (7/14/28/55). Confirms: free tier has no logging feature the USER can inspect; the training-use rule for unpaid tier stays as per the Terms page.

### Jan (raw README, github.com/menloresearch/jan): "Everything runs locally when you want it to"; licence line reads "Apache 2.0" in README (search summaries said AGPLv3 - UNCERTAIN, licence changed at some point; verify LICENSE file before citing). No telemetry statement in README.
### Israel Amendment 13 (natlawreview.com/article/israels-gdpr-legislation-set-take-effect-2025)
- "Financial penalties are capped at 5% of the businesses' annual turnover"; example "8 ILS per data subject"; small/micro businesses "capped at penalties of 140,000 ILS ($45,000 USD) per year". DPO for entities meeting "certain criteria based on size and industry"; PPA grace period on DPO enforcement until 31 Oct 2025 (pearlcohen). Numeric thresholds still needed - see DLA Piper below.
### Obsidian Developer policies: official page not fetchable (404 on docs and raw). Search snippet wording (obsidianstats / help): "network usage must be clearly disclosed", "a link to a privacy policy that explains how the data is handled must be included", telemetry prohibited. Treat as paraphrase, not quote.

### Israel: DLA Piper "Data protection laws of the world - Israel" (dlapiperdataprotection.com/index.html?t=law&c=IL)
- Registration now only for: databases on >10,000 data subjects whose main purpose is collecting data to transfer to third parties (data brokers), and public bodies. Notification only: especially-sensitive data on >100,000 subjects.
- DPO mandatory: public bodies; banks/insurers/credit raters; data brokers >10,000; "regular and systematic monitoring ... on a Large Scale"; "Especially Sensitive Data on a Large Scale". => a solo dictation-app dev with a small Supabase table of accounts/bug reports is below every threshold: no registration, no DPO.
- Section 11 notice at collection must state: whether providing data is legally required, purpose, recipients, uses, "consequences of refusing", "controller's name and contact information", "data subject's right to access and rectify the data".
- Breach: report to PPA on a "Serious Information Security Incident" (severity depends on database category).
### Israel Data Security Regulations 2017 (gov.il/en/pages/data_security_eng; iapp.org tutorial)
- Lowest tier = "database managed by an individual" (individual or one-person company, <=3 authorized users, <10,000 subjects, no sensitive data as main purpose): only minimal duties (database definition document, basic access control, documentation). DeskIT's Supabase (accounts + problem reports, owner is the sole admin) fits this tier PROVIDED reports contain no "sensitive information" - so bug reports must strip audio/transcripts by default. UNCERTAIN: whether e-mail + IP of >10,000 users would tip it to "basic" tier - plan for that (still no registration).
### Google APIs ToS (developers.google.com/terms) - incorporated by the Gemini terms
- "Developer credentials (such as passwords, keys, and client IDs) are intended to be used by you and identify your API Client. You will keep your credentials confidential and make reasonable efforts to prevent and discourage other API Clients from using your credentials." Also: developer credentials "may not be embedded in open source projects".
- Reading for DeskIT: the owner must NOT ship his own Gemini key (shared key = violation + owner's quota). BYOK is the compliant model: each user is the API Client for their own key.
### Supabase key model (supabase.com/docs/guides/getting-started/api-keys, secure-data)
- Publishable/anon key is safe in the client only with RLS; service_role/secret key bypasses RLS and must never be in the app. Policies must use auth.uid(), INSERT with WITH CHECK. => DeskIT client ships only the publishable key; the problem_reports table gets INSERT-only-own-rows policy; no column for keys exists at all (schema is the proof).
### Obsidian Developer policies (paraphrase from search; page itself 404 on fetch)
- "Network use": clearly explain which remote services are used and why; server-side telemetry requires a linked privacy policy; client-side telemetry prohibited. Good template for DeskIT's README "Network use" section.

## Options compared

### A. Where to store the user's Gemini/Groq keys on Windows
| Option | Protection | Size | User-visible? | Python deps | Pros | Cons |
|---|---|---|---|---|---|---|
| Credential Manager via `keyring` (WinVault) | DPAPI per-user; any process running as the same user can read | 1280 chars/entry (keyring #540) | Yes: Control Panel > Credential Manager > Generic Credentials | `keyring` | User can see and delete the entry in Windows' own UI; same model as VS Code/Cline (safeStorage), git, gh; nothing in the app folder to share by accident | Cap breaks Supabase JWTs; some corporate policies block it; misconfigured keyring may pick a null backend |
| DPAPI file (`win32crypt.CryptProtectData`, `%LOCALAPPDATA%\DeskIT\secrets.bin`) | Same DPAPI per-user; MAC tamper-check; no cap | Unlimited | No (opaque blob) | `pywin32` (already needed for Win32 hooks) | One code path for keys + Supabase session; works for portable install; no prompts | Invisible to users; readable by malware running as the user (same as row 1) |
| Plain file + NTFS ACL (icacls user-only) | ACL only; plaintext on disk | Unlimited | Yes | none | Trivial | Leaks via backups, bug-report zips, screenshots; not credible for a privacy pitch |
| `.env` next to code (today) | none | - | Yes | none | - | Shared folder = every export risks the key; rejected |

Verdict: Credential Manager for the two human-pasted API keys (so a user can inspect and revoke them in Windows' own UI), DPAPI file for machine secrets (Supabase session/refresh token) and as automatic fallback when `keyring` raises. Cryptographically both are the same DPAPI (Microsoft: same logon credential, same machine); the choice is about visibility and size.

### B. How peer apps state the guarantee (wording actually found)
- Jan (README): "Everything runs locally when you want it to"; licence line "Apache 2.0" (verify LICENSE).
- Cline: keys in VS Code SecretStorage (Electron safeStorage -> DPAPI); documented gap: standalone mode keeps `~/.cline/data/secrets.json` plaintext.
- Obsidian directory rule (paraphrase): plugins must "clearly explain which remote services are used and why"; server telemetry needs a linked privacy policy; client telemetry forbidden.
- Msty: "zero telemetry, local-first" but closed source, so reviewers call it "a policy you trust".
- LM Studio / Continue / Open WebUI / AnythingLLM: pages not fetchable this run; no verbatim quotes, do not attribute wording to them.
- Common pattern: (1) "your key is stored on your device and sent only to <provider>"; (2) a list of hosts contacted; (3) open source as the proof.

### C. Evidence a user can verify, cheapest first
1. Open source on GitHub, release tag == shipped version string shown in the About box.
2. `network.py` is the ONLY module allowed to import `httpx`/`requests`/`urllib`; hard-coded `ALLOWED_HOSTS` = generativelanguage.googleapis.com, api.groq.com, `<project>.supabase.co`, huggingface.co + cdn-lfs.huggingface.co (model download), github.com (updates), 127.0.0.1 (Ollama, phone endpoint). Two pytest checks: grep the tree for stray HTTP imports; assert every request passes the allowlist (a request to any other host raises).
3. Dashboard > "Network" tab: append-only log of every outbound request: time, host, purpose, bytes, and which secret was attached (by name only). Mirrored to `%LOCALAPPDATA%\DeskIT\network.log` so the user can diff it against Windows Firewall logs or Wireshark.
4. Supabase schema published as SQL in the repo: `problem_reports(id, user_id, created_at, app_version, os_build, text, log_excerpt)`. No column can hold a key; RLS `INSERT ... WITH CHECK (auth.uid() = user_id)`; the app ships only the publishable key. The schema in the repo is the checkable part; the live project is the owner's word.
5. Bug-report scrubber: before upload, redact `AIza[0-9A-Za-z_-]{35}` (Gemini), `gsk_[0-9A-Za-z]{52}` (Groq) and any string equal to a stored secret, then show the exact payload in a preview window with a "Send" button. Unit-tested with fixture keys.
6. GitHub Actions builds the installer from the tag with `actions/attest-build-provenance` (free for public repos) so `DeskIT-Setup.exe` is traceable to a commit; SHA-256 in the release notes. Full reproducible PyInstaller builds are not realistic for a solo dev; say so.
7. Third-party audit: not affordable at zero cost; substitute a SECURITY.md with a written threat model and an open invitation to review.

## Recommendation for DeskIT
Guarantee design, "three locks and a window":
1. Storage lock: keys in Windows Credential Manager (`keyring`, service `DeskIT`, usernames `gemini`, `groq`), DPAPI-file fallback; never in config, never in the code folder, never in history or any export.
2. Egress lock: single `network.py` chokepoint + host allowlist + tests. Audio goes only to 127.0.0.1 (local whisper / phone endpoint over Tailscale) unless the user opts into a cloud transcription setting. No request to a Supabase host ever carries anything but the Supabase user JWT.
3. Schema lock: the Supabase database has no place for a key (published SQL + RLS); bug reports are scrubbed and previewed before sending.
4. Window: the Network tab + network.log show every host in real time.
Reason: this is the only combination a stranger can check without trusting Yoav: read the code, read the schema, watch the log. Closed-source-style "we promise" wording (Msty) is exactly what the research shows reviewers discount.

Wording next to each key field and in the guide:
> "Your Gemini key is saved in Windows Credential Manager on this PC (Control Panel > Credential Manager > Generic Credentials > DeskIT). DeskIT sends it only to generativelanguage.googleapis.com together with the text you dictated. It never goes to DeskIT's servers: our database has no field for it, and bug reports are scrubbed and shown to you before they are sent. Every connection this app makes is listed under Dashboard > Network."

Gemini free-tier notice (mandatory, shown once when a Gemini key is pasted, with a checkbox):
> "Google's free tier uses what you send 'to provide, improve, and develop Google products' and 'human reviewers may read, annotate, and process your API input and output'. Google's own words: 'Do not submit sensitive, confidential, or personal information to the Unpaid Services.' Turn on billing in your Google project if you need that off. Groq, by contract, 'is not permitted to use Inputs or Outputs for training' and keeps no data by default (30-day abuse logs unless you enable Zero Data Retention in your Groq console)."

Privacy-policy skeleton (Israel PPL s.11 style): controller = Yoav Shimron + contact e-mail; data = account e-mail, app version, OS build, the bug-report text you approve, IP as seen by Supabase; purpose = sign-in, update checks, fixing reported problems; providing it is not legally required; consequence of refusal = no account and no reports (dictation still works offline); recipients = Supabase (hosting), Google/Groq only via your own key; retention = reports 12 months, account until deleted; rights = access/rectify/delete via "Delete my account" in the dashboard; breach = notify the PPA and affected users. State explicitly: "Audio never leaves your PC unless you turn on cloud transcription." Keep the Supabase database in the 2017 Regulations' "managed by an individual" tier: no sensitive-data columns, owner is the sole admin, reports contain no audio.

## What the owner must do by hand
- Supabase: create a free project, enable RLS on every table, keep the service_role key only in his password manager (never in the repo), add the INSERT-own-rows policy, enable e-mail auth. Cost 0.
- Google: rotate/delete his own Gemini key from `.env` before the first public commit (Google APIs ToS: developer credentials "may not be embedded in open source projects"). Users bring their own keys; nothing to register.
- Groq: rotate his personal key; optionally enable ZDR on his own console.
- GitHub: public repo, pick a licence (AGPL-3.0 keeps forks auditable), enable Actions + build attestations, add SECURITY.md and a README "Network use" section listing every host and why.
- Israel PPA: no database registration and no DPO at DeskIT's scale (below the 10,000-subject data-broker and 100,000 sensitive-data thresholds); write the s.11 notice and a one-page database definition document per the 2017 Data Security Regulations; keep a breach e-mail template ready. No fees, no forms.
- Later, not free: code-signing certificate (order of USD 200-400/yr, unverified) so SmartScreen stops warning; until then publish SHA-256 and the "More info > Run anyway" note.

## Sources
- Gemini API Additional Terms, last updated 2026-04-28: https://ai.google.dev/gemini-api/terms
- Gemini data logging and sharing: https://ai.google.dev/gemini-api/docs/logs-policy
- Google APIs Terms of Service (credentials clause): https://developers.google.com/terms
- Groq Services Agreement, last modified 2026-06-22 (s3.2, s4.2, s6.2): https://console.groq.com/docs/legal/services-agreement
- Groq "Your Data in GroqCloud": https://console.groq.com/docs/your-data
- Microsoft CryptProtectData (dpapi.h): https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- keyring Windows 1280-char limit: https://github.com/jaraco/keyring/issues/540
- Cline key storage: https://github.com/cline/cline/discussions/2904 ; https://agent-safehouse.dev/docs/agent-investigations/cline
- Jan README: https://github.com/menloresearch/jan
- Obsidian developer policies (404 on fetch; via https://obsidian.md/help/plugin-security and search snippets): https://docs.obsidian.md/Developer+policies
- Supabase keys / securing data: https://supabase.com/docs/guides/getting-started/api-keys ; https://supabase.com/docs/guides/database/secure-data
- Israel Amendment 13: https://www.dlapiperdataprotection.com/index.html?t=law&c=IL ; https://natlawreview.com/article/israels-gdpr-legislation-set-take-effect-2025 ; https://www.pearlcohen.com/israel-significant-amendment-to-the-privacy-law-takes-effect/
- Israel Data Security Regulations 2017: https://www.gov.il/en/pages/data_security_eng ; https://iapp.org/news/a/the-new-israeli-data-security-regulations-a-tutorial
- Verifiable egress pattern: https://pipelab.org/learn/verifiable-egress-control/

## Uncertainties
- Verbatim guarantee wording from LM Studio, Continue, Open WebUI, AnythingLLM, Msty was NOT obtained (404/403/redirect); only the Jan README and the Cline discussion are first-hand. Obsidian policy text is paraphrased from snippets.
- Jan licence: README says Apache 2.0, search summaries say AGPLv3; check the LICENSE file before citing.
- Google's "keep your credentials confidential" clause: no explicit prohibition on pasting a personal key into third-party desktop software was found; industry practice (Cline, Continue, Obsidian AI plugins) treats BYOK as allowed.
- Gemini free-tier rate limits were not checked here; another research file should own them.
- Israel: the numeric meaning of "Large Scale" for the DPO duty, and which security tier a >10,000-account Supabase table falls into, are lawyer questions; the plan assumes under 10,000 users at launch.
- Any Windows store (Credential Manager or DPAPI) is readable by any process running as the same user; the guarantee must be phrased "never leaves your PC to us", not "unreadable on your PC".
- Code-signing cost is from memory, not verified this run.
