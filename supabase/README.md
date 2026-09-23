# The account server, for a sceptic

DeskIT runs exactly one server of its own: a Supabase project in
Frankfurt, on the Free plan, and the app talks to it only when you have
an account — anonymous, or your Google sign-in — and only for what you
turned on: sending a problem report, syncing your learned words and
changed settings, syncing what you said. A copy of DeskIT with no account
never contacts it (the weekly update check goes to GitHub).

This folder is the whole of that server's shape. There is nothing else:
no edge function, no dashboard setting the files do not mention, and
one Realtime topic per account that carries nothing but "go and pull".

## What is in here

- `migrations/0001_init.sql` — every table, column, check, trigger,
  policy, grant, the storage bucket and the one RPC (`delete_me()`). It
  was pasted into the project's SQL editor once; every later change is a
  new file beside it, never a click in the dashboard.
- `migrations/0002_delete_me_leaves_storage_to_the_api.sql` — the RPC
  without the SQL delete on `storage.objects`, which Supabase refuses
  (measured on the first live "Delete my account"): the app removes its
  own files through the Storage API first, the RPC removes the rows and
  the account.
- `migrations/0003_live_channel.sql` — two policies on
  `realtime.messages`, so that a signed-in copy may listen and send on
  the one topic named after its own account, `user:<uid>`. What
  travels on it is the names of the stores that just changed and the
  id of the device that changed them; the rows themselves still come
  down through the tables above. No table is published to Realtime.
- `migrations/0004_account_lock.sql` — the account lock. `history`
  loses its `text` and `raw` columns and gains `cipher`: what you said
  arrives sealed under a key only your own PCs hold (AES-256-GCM through
  Windows' own CNG in the app, `vault.py`). `vault` holds your cloud keys
  the same way, one sealed row per key name. `profiles.lock_id` is the
  key's fingerprint (sixteen hex characters of a hash — tells a PC
  whether it holds the right key, opens nothing). `recovery` is the
  account key wrapped under a recovery key the app generated and you
  keep (scrypt, then AES-GCM). `pairings` is a new PC's request to
  join: its public key, the first eight characters of the code it shows
  (a hint for a person reading the table: both PCs work the code out
  from the public key and never read this column), and — once a
  PC that holds the key approved it — the key wrapped to that public
  key; fifteen minutes, one use. Every opaque column carries
  `is_sealed()` (a version tag and standard base64) in place of
  `looks_like_key()`. The plaintext history rows that were there were
  deleted, not converted.
- `migrations/0005_is_sealed_within_postgres_limits.sql` — the same
  `is_sealed()` with its length cap in `char_length` instead of the
  regex bound: Postgres caps a bound at 255, and 0004's `{16,7600}`
  made the function refuse every call (measured live an hour after it
  ran, before any row was written).

## How to read it in ten minutes

1. **No column the server can read holds a key.** Search the files for
   `key`, `secret`, `token`, `password`: they appear only in comments
   and in the name of the check function, `looks_like_key()`. Every
   free-text and jsonb column carries `not public.looks_like_key(...)`,
   so a pasted API key, a bearer or a JWT is refused by the database
   itself. The patterns are the same ones the app's redactor uses
   (`redact.py`) — the block `BEGIN KEY-PATTERNS` at the top of 0001 is
   parsed by a test and compared with the code character for character.
   Since 0004 your cloud keys DO travel — to the `vault` table, sealed
   under your account's key, which the server never sees; that column
   and the other opaque ones (`history.cipher`, `recovery.wrapped`,
   `pairings.applicant` and `handed`) carry `is_sealed()` instead,
   which admits only a version tag and standard base64.
2. **Every table has row-level security on, and every policy is
   `to authenticated` with `(select auth.uid()) = user_id`.** You can
   see only your own rows. The `anon` role — what a client holding the
   publishable key and no session is — has every privilege revoked
   (`revoke all ... from anon`), so the key that ships in the app opens
   nothing.
3. **The bucket is private.** `insert into storage.buckets ... public =
   false`, 5 MB per file, four MIME types, and three policies on
   `storage.objects` that let you touch only the folder named after
   your own user id.
4. **What syncs and what never does.** `settings_sync` is one JSON blob
   of your changed settings minus everything machine-bound (`sync.py`
   drops the keys page's fields, hotkeys, devices, folders, ports,
   positions and the privacy gates before it leaves your PC — a test
   holds the list). `vocab_sync` is one row per learned word.
   `history` holds what you dictated only if you turned the history
   sync on — sealed, since 0004: RLS separates users from each other,
   and the lock keeps the project admin from reading a row (only `ts`,
   `kind`, `engine` and `seconds` are plain, for the ordering). Audio,
   screenshots and clips have no table.
5. **Delete means delete.** The app removes your files from the bucket
   (it holds the delete policy), then `delete_me()` removes your rows
   and your `auth.users` row — which invalidates every refresh token —
   and leaves one line in `deletion_requests` with your id and the
   time. The Free plan has no backups; the owner's monthly dump and
   its retention are stated in the privacy policy.

## How to confirm the live project matches

- Studio → Database → Schema Visualizer shows the tables; Table Editor
  shows the columns; Authentication → Policies lists every policy.
- Without a login: any request with the publishable key alone —
  `GET https://eogvmcbwfthxedcltyrs.supabase.co/rest/v1/profiles?select=user_id`,
  or any other table, or the RPC — answers `401 permission denied`
  (measured 2026-09-18 right after the migration ran: profiles,
  history and `delete_me()` all refused; even the OpenAPI description
  at `/rest/v1/` is refused, because the `anon` role holds nothing).
- In the app: Dashboard → Network lists every request to the project
  with its purpose (`account`, `sync`, `history`, `report`); the Offline
  switch refuses them all.

## What the owner does by hand

The clicks that are not SQL (DISTRIBUTION_PLAN.md 8.11): create the
project, paste the migration, enable anonymous sign-ins and the Google
provider, set the site URL and the `http://127.0.0.1:*/**` redirect for
the desktop sign-in, confirm the bucket's limits, turn on MFA for the
dashboard login, add the two repository variables the keep-alive
workflow reads (`.github/workflows/supabase-keepalive.yml`).
