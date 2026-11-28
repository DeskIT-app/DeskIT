-- DeskIT — the learned words travel sealed, like what was said (2026-11-27).
--
-- The 2026-11-09 audit (security-server F1, confirmed by its sceptic):
-- `vocab_sync` (0001) kept every learned pair in the clear — `heard`,
-- `meant`, `hits` — and every PC merged what it pulled with no check. Two
-- harms from one table. Whoever reads the project reads the most personal
-- list the app keeps (names, terms, the way a person spells them). And a
-- stolen session, or whoever holds the project, could write a row such as
-- a common word -> another word at hits 1,000,000, or a tombstone per
-- word, and broadcast "changed: vocab": every PC of the account then
-- pasted the other word, gave it to the decoder as a hotword, or lost its
-- list. 0004 sealed what was said and the cloud keys; this file is the
-- same for the words. On the live project the day it was written: 204
-- rows of vocab_sync for 2 accounts, 202 of them one account's (112 kB).
--
--   vocab_sealed   one row per learned word:
--     id           32 hex characters, an HMAC of the heard form (lower
--                  case, the key the app's merge goes by) under a key
--                  derived from the account key (vault.word_id). The
--                  server can upsert one row per word without knowing the
--                  word; two PCs of one account name a word alike, and two
--                  accounts name it otherwise.
--     cipher       {heard, meant, hits, last_used, deleted} sealed under
--                  the account key (vault.seal_json, AES-256-GCM), with
--                  `vocab/<user_id>/<id>` as the associated data
--                  (vault.AAD_VOCAB). A row the server makes up does not
--                  open, nor one moved to another id or another account,
--                  and the app also refuses a row whose word does not hash
--                  to its id. `char_length <= 4096`: a word and its meaning
--                  are 200 characters each in the app, which seal to 3,367
--                  characters at the very most (a control character that
--                  JSON writes as six bytes, throughout); 200 Hebrew
--                  letters each seal to 1,235 (measured 2026-11-27).
--     updated_at   the pull's cursor, as in every table.
--
-- Why a new table and not new columns on vocab_sync. (1) vocab_sync's
-- primary key is (user_id, heard) — the word itself; a sealed row needs
-- another name, and a hash in `heard` would make one column mean two
-- things. (2) The copies already installed (the owner's own Store copy is
-- on 1.0.6) read and write vocab_sync and nothing else, and must go on
-- working: they never see this table, and nothing they send reaches it.
-- (3) As with history in 0004, a table with no plaintext column cannot be
-- sent a word in the clear by a client that forgot.
--
-- vocab_sync is NOT dropped and its rows are NOT deleted here: the server
-- cannot seal what it should not read (0004's argument), and a copy from
-- before this file still writes it and reads it. Their fate is the app's
-- (sb._sync_vocab, in the build that ships with this file):
--   * a copy on that build never writes vocab_sync;
--   * a copy that synced words there before makes ONE last pass of it,
--     from where its own cursor stood (the pull its old code would have
--     made next), then sends every word it holds here, sealed, and never
--     reads vocab_sync again; a copy that never synced in the clear (a new
--     PC, a sign-out since) never reads it at all. So a row a server or a
--     stolen session writes there reaches no copy on that build;
--   * every copy on that build deletes the account's vocab_sync rows that
--     are more than a day old, at most once a day. The day is for the
--     account's other copies from before, which pull every 15 minutes
--     while they run and can still take a word one of them learned. A copy
--     from before reads a row that went as nothing: only a row with
--     `deleted` takes a word off its list (1.0.6's _sync_vocab, read
--     2026-11-27), so it keeps every word in its own file, and they all
--     come up sealed the day it is updated.
--   None is left a day or two after the last copy from before is updated.
--   Dropping vocab_sync is a later file, once no copy older than that
--   build can be running (the owner's call, with the version he releases).
--
-- Nothing else changes. RLS is the own-uid shape of every table, every
-- policy `to authenticated`; `authenticated` gets exactly the four verbs
-- (0001's rule: Supabase's default would give it every privilege); no new
-- function, so 0008's rules have nothing to apply to; delete_me() sweeps
-- the new table (0004's body with the one line added — the cascade from
-- auth.users would take the rows anyway, the sweep says so in words).
--
-- Apply BEFORE the build that seals is run anywhere: that build finds no
-- table without it and says "vocabulary: ..." on every pass until it is
-- there. It never falls back to vocab_sync, because a server that hid this
-- table could otherwise turn the forgery back on.

-- ------------------------------------------------------------ vocab_sealed

create table public.vocab_sealed (
  user_id    uuid not null references auth.users (id) on delete cascade,
  id         text not null check (id ~ '^[0-9a-f]{32}$'),
  cipher     text not null check (public.is_sealed(cipher) and char_length(cipher) <= 4096),
  updated_at timestamptz not null default now(),
  primary key (user_id, id)
);
create index vocab_sealed_user_updated on public.vocab_sealed (user_id, updated_at);

create trigger vocab_sealed_updated_at before update on public.vocab_sealed
  for each row execute function public.set_updated_at();

alter table public.vocab_sealed enable row level security;

create policy vocab_sealed_select on public.vocab_sealed for select to authenticated
  using ((select auth.uid()) = user_id);
create policy vocab_sealed_insert on public.vocab_sealed for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy vocab_sealed_update on public.vocab_sealed for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy vocab_sealed_delete on public.vocab_sealed for delete to authenticated
  using ((select auth.uid()) = user_id);

revoke all on public.vocab_sealed from anon;
revoke all on public.vocab_sealed from authenticated;
grant select, insert, update, delete on public.vocab_sealed to authenticated;

-- -------------------------------------------------------------- delete_me
-- 0004's RPC with the new table in its sweep.

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
  delete from public.vocab_sealed    where user_id = uid;
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
--   vocab_sealed  user_id id cipher updated_at
--
-- `id` is a keyed hash (the key is the account's, which the server never
-- holds), `cipher` carries `is_sealed()`: a version tag and standard
-- base64, opaque here. No column is named key, secret, token, password or
-- apikey, and none holds one the server could read.
