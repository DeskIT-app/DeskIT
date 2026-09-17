# supabase

**Question:** Supabase for a Python Windows desktop app (DeskIT) in 2026: auth flows that work from a desktop app (email OTP/magic link, email+password, Google via PKCE with a localhost redirect), how supabase-py stores/refreshes sessions and how to keep the refresh token safe on Windows, free-tier limits and gotchas (pause after idle, DB 500 MB, storage 1 GB, 50k MAU, 2 projects, egress), RLS patterns so the shipped anon key cannot read other users' rows (profiles, settings, devices, problem_reports + storage bucket), whether shipping the anon key in a desktop binary is accepted practice, one sentence each on Firebase / PocketBase / Appwrite / Cloudflare D1, and the exact manual steps the owner must do to create the project.

Researched 2026-09-16. Findings appended per source below.

## Findings (per source)

### Search round 1 (secondary sources, to be verified on primary pages)
- Free plan (third-party summaries, 2026): 500 MB DB, 1 GB file storage, 50k MAU, 5 GB egress, 2 active free projects, paused after 7 days inactivity, 500k edge-function invocations, 200 realtime connections. To verify on supabase.com/pricing.
- PKCE docs: code is valid 5 minutes, exchangeable once; code verifier is stored locally by the client that started the flow, so exchange must happen in the same client. Redirect URLs must be allow-listed in Auth > URL Configuration (http://localhost:<port> allowed).
- Keys: new `sb_publishable_...` replaces anon key, `sb_secret_...` replaces service_role; legacy keys "deprecated by end of 2026" (third-party claim, verify). Publishable/anon key is designed to ship in client code; safety depends entirely on RLS being enabled on every table. Secret key must never ship.
- Storage RLS pattern: `bucket_id = 'x' AND (storage.foldername(name))[1] = auth.uid()::text` on storage.objects, in USING and WITH CHECK.
- Session persistence: JS/Flutter clients persist to storage and refresh ~ when 20% of the 1h lifetime remains; "Invalid Refresh Token: Already Used" is the classic failure when two clients hold the same refresh token. supabase-py specifics not found in search, need the source.

### Primary: https://supabase.com/pricing (fetched 2026-09-16)
- Free plan, verbatim: "500 MB database size (Shared CPU • 500 MB RAM)", "1 GB file storage", "50,000 monthly active users", "5 GB egress" + "5 GB cached egress", "Limit of 2 active projects", "Free projects are paused after 1 week of inactivity", Edge Functions "500,000 included", Realtime "200 included" peak connections / "2 Million included" messages.
- Free: branching "Not included", backups "Not included", auth audit logs kept "1 hour", API & DB logs "1 day". Pro "from $25/month". Card requirement not stated on the page (uncertainty; historically no card for free).

### Primary: https://supabase.com/docs/guides/auth/sessions/pkce-flow
- "For security purposes, the code has a validity of 5 minutes and can only be exchanged for an access token once."
- "The code exchange must be initiated on the same browser and device where the flow was started." (i.e., the verifier lives in the client that called sign_in_with_oauth; for a desktop app the Python process holds it, browser only carries the code back to localhost).
- Starting two PKCE flows before one completes overwrites the verifier.

### Primary: https://supabase.com/docs/guides/api/api-keys
- "Supabase is deprecating the `anon` and `service_role` keys by the end of 2026." New format: `sb_publishable_...` / `sb_secret_...`.
- Publishable key: "Safe to expose online: web page, mobile or desktop app, GitHub actions, CLIs, source code." "Anyone can read it, so it only reaches what Row Level Security allows."
- Secret key: "A secret key bypasses every Row Level Security policy you have. Never put one in a browser, a shipped application, or source control."
=> Shipping the publishable key in the DeskIT binary is the officially documented practice.

### Primary: https://supabase.com/docs/guides/storage/security/access-control
- Insert policy: `on storage.objects for insert to authenticated with check (bucket_id = 'my_bucket_id' and (storage.foldername(name))[1] = (select auth.jwt()->>'sub'))`.
- Select: `using ((select auth.jwt()->>'sub') = owner_id)`. Public buckets bypass RLS for reads, so the reports bucket must be PRIVATE.

### Primary: https://supabase.com/docs/guides/database/postgres/row-level-security
- Per-table pattern: `create policy ... on profiles for select to authenticated using ((select auth.uid()) = user_id);` same shape for insert (with check), update (using + with check), delete.
- "A table in an exposed schema without RLS is readable and writable by any role with a grant on it. Enable RLS on every table in an exposed schema."
- Perf: wrap `(select auth.uid())`, index `user_id`, always `to authenticated`. service_role bypasses RLS, keep server-side.

### Primary: https://supabase.com/docs/guides/auth/redirect-urls
- Redirect allow list supports wildcards (`http://localhost:3000/**`) and custom schemes: "For mobile applications you can use deep linking URIs ... `com.supabase://login-callback/`". "The Site URL in URL Configuration defines the default redirect URL when no `redirectTo` is specified."
- For DeskIT: allow-list `http://127.0.0.1:*/callback` style pattern (or a fixed port range) so the app's temporary local HTTP listener can receive `?code=`.

### Primary: https://supabase.com/docs/reference/python/auth-signinwithotp
- `supabase.auth.sign_in_with_otp({"email": ..., "options": {"email_redirect_to": ...}})`; then `supabase.auth.verify_otp({"email": ..., "token": "123456", "type": "email"})`.
- "To send users a one-time code instead of a magic link, modify the magic link email template to include `{{ .Token }}` instead of `{{ .ConfirmationURL }}`." => 6-digit code is the desktop-friendly path (no browser round trip, no redirect at all).

### Secondary: Cloudflare D1 (changelog 2026-09-01 + summaries)
- Free: 5 GB storage, 5M rows read/day, 100k rows written/day; from 2026-09-01 over-limit queries fail. D1 is a database only: no auth, no storage bucket, no email; would need Workers + own auth => more owner code.

### Secondary: alternatives summaries (weweb, devtoolreviews 2026)
- PocketBase: single Go binary + SQLite, free software but needs a VPS the owner pays for/maintains (no free managed tier) => violates zero-cost unless a free VPS (Oracle free tier) is used.
- Appwrite Cloud: pricing aligned with Supabase; free tier exists; Python SDK is server-side oriented (client auth from Python is awkward).
- Firebase Spark: free, no self-host; official Python SDK is admin-only (firebase-admin) so desktop client auth = raw REST calls to Identity Toolkit.

### Primary: https://supabase.com/docs/guides/platform/free-project-pausing
- "Typically a few user requests to the database each day over the previous week is enough to keep the project from being paused."
- "Once the project is paused, there is a 1-year window to restore the project on the platform from within Supabase Studio." (secondary sources: after 90 days paused the one-click Restore is disabled and the API URL is released; then only backup download.)
- "To prevent future automatic pausing, upgrade to the Pro Plan ... Paid projects cannot be paused." No free-plan opt-out. For DeskIT: real users' app launches count as activity; while user count is ~0 the owner needs a weekly ping (GitHub Actions cron hitting the REST API with the publishable key is the common trick, e.g. travisvn/supabase-pause-prevention).

### Primary: https://supabase.com/docs/guides/auth/auth-smtp
- Built-in email: "Currently this value is set to 2 messages per hour." and only to "pre-authorized addresses" that are project team members: "All other addresses will fail with the error message Email address not authorized."
- "We urge all customers to set up custom SMTP server for all other use cases." => Email OTP/magic link for strangers REQUIRES custom SMTP. Free SMTP candidates: Resend (free 3,000 emails/month, 100/day, needs a domain the owner controls) or Brevo (300/day). Uncertainty: exact current free quotas, verify when choosing.

### Primary: https://supabase.com/docs/guides/auth/social-login/auth-google
- Google Cloud: create OAuth client of type "Web application"; Authorized redirect URI = the project's callback shown on the Dashboard Google provider page (`https://<ref>.supabase.co/auth/v1/callback`). Docs say desktop (Flutter) apps "follow the same configuration guide as if your app was a Web application". Google consent screen: an unverified app shows a warning until Google verifies it; with only `email`/`profile` scopes verification is light but branding requires a homepage + privacy-policy URL (uncertainty: current Google rules).

### Primary: supabase-py source, main branch (src/auth/src/supabase_auth/_sync/gotrue_client.py, storage.py, constants.py; src/supabase/src/supabase/lib/client_options.py)
- Storage interface is 3 methods: `get_item(key) -> Optional[str]`, `set_item(key, value: str)`, `remove_item(key)`. Default is `SyncMemoryStorage` (a dict) -> nothing survives process exit unless the app supplies its own storage object via `ClientOptions(storage=...)`.
- Session is saved as one JSON string (`model_dump_json(session)`: access_token, refresh_token, expires_at, user...) under key `STORAGE_KEY = "supabase.auth.token"`; PKCE verifier under `"<storage_key>-code-verifier"`. Both go through the same storage object.
- Auto refresh (sync client): `_save_session` arms a `Timer` to fire `EXPIRY_MARGIN = 10` seconds before `expires_at` (`value = (expire_in - 10) * 1000`), then `_call_refresh_token`; retries with backoff on `AuthRetryableError` up to MAX_RETRIES. `get_session()` also refreshes on demand if `expires_at <= now + 10`. `_recover_and_refresh` at startup reads storage, refreshes if expired. Timer is a thread; in a long-running pythonw app it just works, but the app must call `sign_out()`/cancel on exit to avoid a dangling thread.
- `client_options.py`: `flow_type: AuthFlowType = "pkce"` is the DEFAULT for the supabase client, `auto_refresh_token=True`, `persist_session=True`.
- `sign_in_with_oauth({"provider":"google","options":{"redirect_to":"http://127.0.0.1:PORT/cb"}})` returns `OAuthResponse(url=...)` only; the app must open it (`webbrowser.open`) and run a one-shot local HTTP server to catch `?code=`, then `exchange_code_for_session({"auth_code": code})` which reads the verifier from storage.
- Refresh-token safety on Windows: implement `SyncSupportedStorage` that encrypts with DPAPI (`CryptProtectData` via ctypes, user scope) and writes to `%LOCALAPPDATA%\DeskIT\session.bin`; alternative `keyring` (Windows Credential Manager, ~2.5 KB value limit per credential - session JSON with user object may exceed it, so DPAPI file is safer). Refresh tokens rotate on every refresh (Supabase "refresh token rotation" with reuse-detection interval, default 10 s) so two processes sharing one file will log each other out: keep exactly one DeskIT process holding the session.

### Primary: https://supabase.com/docs/guides/auth/sessions and /auth/rate-limits
- "A refresh token can be used more than once within a defined reuse interval. By default this is 10 seconds"; "refresh tokens never expire but can only be used once"; access token default 1 hour. Time-boxed / inactivity-timeout sessions: "This feature is only available on Pro Plans and up." => on Free, a stolen refresh-token file is valid until the user signs out everywhere; DPAPI at rest is the mitigation.
- Rate limits: built-in mail "2 emails per hour"; OTP "60 seconds window ... for the same user"; sign-in/sign-up "30 requests per 5 minutes" per IP; token endpoint "150 requests per 5 minutes" per IP (covers refresh + PKCE).

### Primary: https://supabase.com/docs/guides/database/secure-data
- "Your publishable key is safe to expose with RLS enabled, because row access permission is checked against your access policies and the user's JWT." "Unlike your publishable key, your secret and service role keys are never safe to expose because they bypass RLS."

### Secondary: Resend free plan (several 2026 summaries; verify on resend.com/pricing)
- 3,000 emails/month, 100/day, 1 verified custom domain, SMTP relay included. Needs a domain the owner owns (uncertainty: domain cost ~10 USD/yr).

## Design notes for DeskIT

### Auth flows that work from a Tk/pythonw desktop app
1. Email + 6-digit code (recommended default): `sign_in_with_otp({"email": ...})` -> user types the code into a Tk dialog -> `verify_otp({"email", "token", "type": "email"})`. No browser, no redirect, no localhost server. Requires the magic-link template changed to `{{ .Token }}` and custom SMTP.
2. Email + password: `sign_up` / `sign_in_with_password`; only the confirmation email needs SMTP. Adds password-reset UX; keep optional.
3. Google via PKCE: app starts `http.server` on 127.0.0.1:<random port>, calls `sign_in_with_oauth({"provider": "google", "options": {"redirect_to": that URL}})`, opens the returned `url` with `webbrowser.open`, receives `?code=`, calls `exchange_code_for_session({"auth_code": code})`. Requires `http://127.0.0.1:*/**` in Auth > URL Configuration and a Google Cloud OAuth "Web application" client pointing at the Supabase callback. The 5-minute code validity and one-flow-at-a-time rule are fine for a desktop app. v2 feature.
Magic link (click in email) is NOT desktop-friendly: the link lands in the browser, and with PKCE the verifier lives in the Python process, so the browser cannot finish it; use the code template.

### Session storage on Windows
- Implement `DpapiFileStorage(SyncSupportedStorage)`: values encrypted with `CryptProtectData` (CRYPTPROTECT_UI_FORBIDDEN, current-user scope), stored as `%LOCALAPPDATA%\DeskIT\auth\<key>.bin`. Pass via `create_client(url, key, options=SyncClientOptions(storage=DpapiFileStorage(), flow_type="pkce"))`. Call `auth.get_session()` at startup (triggers `_recover_and_refresh`).
- Only one DeskIT process may own the session (token rotation + 10 s reuse window). The phone app never receives the Supabase session; it keeps talking to the PC over Tailscale.

### Schema + RLS (all tables in `public`, RLS ON, policies `to authenticated`, `(select auth.uid()) = user_id`, index on user_id)
- `profiles(user_id pk -> auth.users, display_name, created_at)`: select/insert/update own row; no delete policy (cascade from auth.users).
- `settings(user_id pk, json jsonb, updated_at)`: select/insert/update own row. Contains NO API keys (see proof).
- `devices(id uuid pk, user_id, name, platform, app_version, last_seen)`: full CRUD on own rows.
- `problem_reports(id, user_id, app_version, title, body, log_excerpt, created_at, status)`: insert own + select own; no update/delete policy. Owner reads them in Studio (dashboard login, not through the app).
- Storage bucket `reports` PRIVATE; `storage.objects` policies: insert `with check (bucket_id = 'reports' and (storage.foldername(name))[1] = (select auth.uid())::text)`, select with the same expression in `using`. Bucket file-size limit (e.g. 5 MB) protects the 1 GB quota; audio only if the user ticks "attach audio".
- `revoke all on all tables in schema public from anon` so an unauthenticated client holding the publishable key sees nothing; only `authenticated` has grants, filtered by RLS.
- Never ship `sb_secret_`; DeskIT has no backend, so nothing ever needs it.

### PROOF that pasted API keys (Groq/Gemini) never reach the owner's database
Structural, not a promise:
1. Keys live only in Windows Credential Manager (`keyring`) under `DeskIT/groq`, `DeskIT/gemini`, never in the settings JSON that syncs to `settings`. The settings schema generated from config comments marks key fields `sync: false`; the sync serializer drops every such field.
2. DB-side CHECK constraints on `settings.json` and `problem_reports.body/log_excerpt` reject key-shaped strings: `check (json::text !~ '(gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{20,})')`. The constraint sits in the public migration SQL.
3. The bug-report key redacts the same patterns client-side and shows the exact payload in a preview window with a "Send" button.
4. A public repo test (`tests/test_no_secrets_leave.py`) runs sync + report against an `httpx.MockTransport` and asserts no key-shaped string appears in any outbound body. CI badge in the README.
5. The user guide's "What we store" page lists the exact columns.

## Options compared
| Option | Free tier (verified?) | Auth from Python desktop | Files | Owner effort | Verdict |
|---|---|---|---|---|---|
| Supabase | 500 MB DB, 1 GB files, 50k MAU, 5 GB egress, 2 projects, pauses after 1 week idle (primary) | supabase-py: OTP, password, PKCE, pluggable storage | yes, RLS on storage.objects | low: SQL migration only | Recommended |
| Firebase (Spark) | free, no card; Firestore 1 GiB; new Storage buckets need Blaze (card) since 2024 (unverified) | no official client SDK for Python; raw Identity Toolkit REST | needs Blaze | medium | no |
| PocketBase | software free, no managed free tier; needs a VPS | REST, simple | yes | owner runs a server | breaks zero-cost / solo ops |
| Appwrite Cloud | free tier exists (limits not verified) | Python SDK is server-side; client auth awkward | yes | medium | no |
| Cloudflare D1 | 5 GB, 5M reads/day, 100k writes/day, hard-fail since 2026-09-01 (primary changelog) | none: DB only; auth/email/files must be built in Workers + R2 | via R2 | high | no |

## Recommendation for DeskIT
Use Supabase: one Free project, the `sb_publishable_` key compiled into the app, RLS on every table with `to authenticated` policies keyed on `auth.uid()`, anon grants revoked, private `reports` bucket keyed on the user's folder. Default sign-in = email + 6-digit code via custom SMTP (Resend free); Google PKCE with a localhost listener as an optional second button later. Session persisted through a custom `SyncSupportedStorage` encrypted with DPAPI. API keys stay in Credential Manager and are excluded from sync by schema flag, DB constraint, client redaction and a CI test. Reason: it is the only zero-cost option where auth, per-user rows and file uploads are all reachable from plain Python without an owner-run server, and "safe to expose ... desktop app" is an official statement. Costs of the choice: the project pauses after a week without traffic (weekly ping until real users exist), no backups on Free (owner runs `pg_dump` monthly), legacy anon/service_role keys retire end-2026 (start on the new key format).

## What the owner must do by hand
1. supabase.com -> sign up with GitHub or email (no card expected). New organization on Free -> New project: name `deskit`, region `eu-central-1` (Frankfurt), generate and save the database password in his password manager.
2. Project Settings -> API Keys: copy Project URL and the `sb_publishable_...` key into the app config. Never copy `sb_secret_`.
3. SQL Editor: paste the migration (tables, RLS, policies, revoke anon, check constraints, bucket + storage policies). Keep it in the repo as `supabase/migrations/0001_init.sql`.
4. Authentication -> Providers -> Email: enable. Email Templates -> Magic Link: replace `{{ .ConfirmationURL }}` with `{{ .Token }}`; OTP length 6, expiry 10 min. Enable "Confirm email" only if password login ships.
5. Authentication -> URL Configuration: Site URL = the GitHub Pages guide URL; add `http://127.0.0.1:*/**` only when the Google button ships.
6. Custom SMTP: own a domain (~10 USD/yr, the one likely non-free item), create a Resend account (free), verify the domain (DKIM/SPF/DMARC DNS records), then Project Settings -> Authentication -> SMTP: host smtp.resend.com, port 465, user `resend`, password = Resend API key, sender `login@<domain>`. Raise the email rate limit in Auth -> Rate Limits.
7. Google (optional): console.cloud.google.com -> new project -> OAuth consent screen (External, app name, support email, privacy-policy URL on GitHub Pages) -> Credentials -> OAuth client ID, type Web application, Authorized redirect URI = the value shown in Supabase Auth -> Providers -> Google; paste client ID + secret into Supabase.
8. Storage: confirm `reports` is private, file-size limit 5 MB, allowed MIME types (text/plain, application/json, image/png; audio/wav only for opt-in).
9. GitHub Actions weekly cron: `curl https://<ref>.supabase.co/rest/v1/profiles?select=user_id&limit=1 -H "apikey: <publishable>"` to avoid the 1-week idle pause; delete once there are daily users.
10. Monthly: Studio -> DB size vs 500 MB and storage vs 1 GB; `pg_dump` via the pooler connection string (Free has no backups).

## Sources
- https://supabase.com/pricing (Free limits, pause after 1 week, Pro from $25)
- https://supabase.com/docs/guides/platform/free-project-pausing
- https://supabase.com/docs/guides/api/api-keys (publishable key safe in desktop apps; legacy keys deprecated end-2026)
- https://supabase.com/docs/guides/database/secure-data
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/storage/security/access-control
- https://supabase.com/docs/guides/auth/sessions/pkce-flow
- https://supabase.com/docs/guides/auth/sessions (rotation, reuse interval, Pro-only timeouts)
- https://supabase.com/docs/guides/auth/rate-limits
- https://supabase.com/docs/guides/auth/auth-smtp (2 emails/hour, team addresses only)
- https://supabase.com/docs/guides/auth/redirect-urls
- https://supabase.com/docs/guides/auth/social-login/auth-google
- https://supabase.com/docs/reference/python/auth-signinwithotp
- https://github.com/supabase/supabase-py main branch 2026-09-16: src/auth/src/supabase_auth/_sync/gotrue_client.py, _sync/storage.py, constants.py; src/supabase/src/supabase/lib/client_options.py
- https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/
- Secondary: uibakery.io/blog/supabase-pricing; devtoolreviews.com Supabase vs Firebase vs Appwrite vs PocketBase 2026; wpmailsmtp.com/resend-review; github.com/travisvn/supabase-pause-prevention

## Uncertainties
- Whether Supabase Free asks for a credit card at sign-up (pricing page is silent; historically no).
- Exact behaviour after 90 days paused (secondary: one-click restore disabled, URL released) vs the docs' 1-year window.
- Resend free quotas and domain requirement come from secondary sources; the domain is the one likely non-zero expense.
- Firebase Storage on Spark for new projects (believed Blaze-only since Oct 2024) and Appwrite Cloud free limits were not verified on primary pages.
- Google consent-screen requirements for a solo developer without a company (privacy-policy URL required; an "unverified app" warning may show).
- supabase-py Timer-based auto refresh under pythonw and after sleep/hibernate (timer fires late; `get_session()` on-demand refresh should cover it, untested).
- Windows Credential Manager ~2.5 KB value limit vs session JSON size: the reason for a DPAPI file over `keyring` for the session; not measured.
