-- DeskIT — the account lock (2026-09-21).
--
-- The owner, after the two syncs became one account: the cloud keys and
-- the text of what he said must be locked BEFORE they leave the PC, so
-- that the same account opens them on every PC of his and this project
-- — and whoever runs it — cannot. vault.py in the app is the lock; this
-- file is the server's side of it, which is nothing but opaque text:
--
--   profiles.lock_id  the fingerprint of the account's key (sixteen hex
--                     characters of a hash) — tells a device whether it
--                     holds the right key; opens nothing.
--   vault             one row per cloud key NAME (groq, gemini), the
--                     value sealed under the account key. This is the
--                     one place a key travels to this project, and it
--                     travels sealed: D12 lock 3 read "no column can
--                     hold a key" and reads, from this file on, "no
--                     column the server can READ holds a key".
--   history.cipher    what was said, sealed; `text` and `raw` are
--                     DROPPED, not emptied — a column that does not
--                     exist cannot be sent plaintext by a client that
--                     forgot. `ts`, `kind`, `engine` and `seconds` stay
--                     readable: the syncs order and name rows by them.
--   recovery          the account key wrapped under a recovery key the
--                     app generated and the person keeps (scrypt, then
--                     AES-GCM); optional, one row per account.
--   pairings          a new PC's request to join: its public key, the
--                     short code it shows, and — once a PC that holds
--                     the key approved — the account key wrapped to
--                     that public key. Fifteen minutes, one use. The
--                     phone will use the same table when it joins.
--
-- What the big services do, and the app copies (Apple's keychain
-- syncing, Bitwarden's log-in-with-device, WhatsApp's link-with-phone-
-- number, Signal's secure backups; read 2026-09-21): a new device makes
-- a key pair, an old device approves after the person compared a short
-- code on both screens, the key crosses wrapped to the new device's
-- public key; a generated recovery key for the day no old device is at
-- hand. The server carries public keys and sealed values and nothing
-- it can open.
--
-- The plaintext history rows already here (the owner's own, the only
-- account at the time) are DELETED, not converted — the server cannot
-- seal what it should not read; every copy pushes its history again,
-- sealed, from a fresh cursor (sb.py resets the cursors when the lock's
-- fingerprint changes). His decision, 2026-09-21.
--
-- `is_sealed()` is the shape every opaque column carries in place of
-- `looks_like_key()`: a two-character version tag, a dot, standard
-- base64 (never url-safe, so `gsk_`, `sb_` and `sk-` cannot occur),
-- 16 to 7,600 characters. tests.py holds it against vault.py's own
-- check (test_migration_has_no_key_column, amended). The bound written
-- below, `{16,7600}`, is one Postgres refuses at run time (255 is its
-- cap — measured live an hour after this ran); 0005 is the same
-- function with the cap in char_length.
--
-- Applied once through the Supabase connector after 0003, 2026-09-21.

-- ---------------------------------------------------------------- helpers

create or replace function public.is_sealed(t text)
returns boolean
language sql
immutable
strict
parallel safe
as $$
  select t ~ '^[a-z][0-9]\.[A-Za-z0-9+/]{16,7600}={0,2}$'
$$;

-- ---------------------------------------------------------------- profiles

alter table public.profiles
  add column lock_id text not null default ''
    check (lock_id = '' or lock_id ~ '^[0-9a-f]{16}$');

-- ------------------------------------------------------------------- vault

create table public.vault (
  user_id    uuid not null references auth.users (id) on delete cascade,
  name       text not null check (name ~ '^[a-z][a-z_]{0,31}$'),
  cipher     text not null check (public.is_sealed(cipher)),
  updated_at timestamptz not null default now(),
  primary key (user_id, name)
);
create index vault_user_updated on public.vault (user_id, updated_at);

-- ----------------------------------------------------------------- history

delete from public.history;
alter table public.history drop column text;
alter table public.history drop column raw;
alter table public.history
  add column cipher text not null check (public.is_sealed(cipher));

-- ---------------------------------------------------------------- recovery

create table public.recovery (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  wrapped    text not null check (public.is_sealed(wrapped)),
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- pairings

create table public.pairings (
  id          uuid primary key,
  user_id     uuid not null references auth.users (id) on delete cascade,
  device_id   uuid not null,
  device_name text not null default '' check (char_length(device_name) <= 40 and not public.looks_like_key(device_name)),
  code        text not null check (code ~ '^[0-9A-HJKMNP-TV-Z]{8}$'),
  applicant   text not null check (public.is_sealed(applicant)),
  handed      text check (handed is null or public.is_sealed(handed)),
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null default now() + interval '15 minutes',
  approved_at timestamptz
);
create index pairings_user_id on public.pairings (user_id);

-- --------------------------------------------------------------- triggers

create trigger vault_updated_at before update on public.vault
  for each row execute function public.set_updated_at();

-- From the client only `handed` and `approved_at` may change on a
-- request: the applicant's public key and its code are frozen after
-- insert, so an approval always answers the request that was shown.
create or replace function public.pairings_guard()
returns trigger
language plpgsql
as $$
begin
  if new.id <> old.id
     or new.user_id <> old.user_id
     or new.device_id <> old.device_id
     or new.device_name <> old.device_name
     or new.code <> old.code
     or new.applicant <> old.applicant
     or new.created_at <> old.created_at
     or new.expires_at <> old.expires_at then
    raise exception 'pairings: only handed and approved_at may change after insert';
  end if;
  return new;
end
$$;
create trigger pairings_guard before update on public.pairings
  for each row execute function public.pairings_guard();

-- ---------------------------------------------------- row-level security

alter table public.vault    enable row level security;
alter table public.recovery enable row level security;
alter table public.pairings enable row level security;

create policy vault_select on public.vault for select to authenticated
  using ((select auth.uid()) = user_id);
create policy vault_insert on public.vault for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy vault_update on public.vault for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy vault_delete on public.vault for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy recovery_select on public.recovery for select to authenticated
  using ((select auth.uid()) = user_id);
create policy recovery_insert on public.recovery for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy recovery_update on public.recovery for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy recovery_delete on public.recovery for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy pairings_select on public.pairings for select to authenticated
  using ((select auth.uid()) = user_id);
create policy pairings_insert on public.pairings for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy pairings_update on public.pairings for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy pairings_delete on public.pairings for delete to authenticated
  using ((select auth.uid()) = user_id);

-- ------------------------------------------------------------- privileges

grant select, insert, update, delete on public.vault    to authenticated;
grant select, insert, update, delete on public.recovery to authenticated;
grant select, insert, update, delete on public.pairings to authenticated;

-- -------------------------------------------------------------- delete_me
-- The RPC of 0002 with the three new tables in its sweep.

create or replace function public.delete_me()
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    raise exception 'delete_me: no session';
  end if;
  insert into public.deletion_requests (user_id) values (uid);
  -- the storage objects under reports/<uid>/ are removed by the client
  -- through the Storage API before this call (0002)
  delete from public.problem_reports where user_id = uid;
  delete from public.pairings        where user_id = uid;
  delete from public.recovery        where user_id = uid;
  delete from public.vault           where user_id = uid;
  delete from public.history         where user_id = uid;
  delete from public.vocab_sync      where user_id = uid;
  delete from public.settings_sync   where user_id = uid;
  delete from public.devices         where user_id = uid;
  delete from public.profiles        where user_id = uid;
  delete from auth.users             where id = uid;
end
$$;

revoke all on function public.delete_me() from public;
revoke all on function public.delete_me() from anon;
grant execute on function public.delete_me() to authenticated;

-- ----------------------------------------------------------------- footer
-- The columns this file adds, and why the server can read none of them:
--
--   profiles  + lock_id            sixteen hex characters of a hash
--   vault       user_id name cipher updated_at
--   history   - text - raw + cipher
--   recovery    user_id wrapped created_at
--   pairings    id user_id device_id device_name code applicant handed
--               created_at expires_at approved_at
--
-- `cipher`, `wrapped`, `applicant` and `handed` carry `is_sealed()`:
-- a version tag and standard base64, opaque here. `applicant` is a
-- PUBLIC key (the new PC's P-256 point), `handed` the account key
-- wrapped to it, `wrapped` the account key under the person's recovery
-- key, `cipher` a value under the account key. `code` is eight
-- characters the person compares on two screens; it opens nothing.
-- No column is named key, secret, token, password or apikey, and none
-- holds one the server could read.
