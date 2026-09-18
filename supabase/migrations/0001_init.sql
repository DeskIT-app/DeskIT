-- DeskIT — the whole schema of the one server the app may talk to.
--
-- DISTRIBUTION_PLAN.md chapter 8 (8.13 lists this file's order), decisions
-- D17 (narrow scope, anonymous by default, zero cost), D31 (account-backed
-- sync: vocabulary, settings, history), D33(b) (no reply channel: there is
-- no report_replies table), D12 lock 3 (no column anywhere can hold a key).
--
-- Applied ONCE by hand in the SQL editor of the project `deskit`, region
-- eu-central-1 (Frankfurt), on the Free plan. The dashboard is never edited
-- by hand afterwards: every later change is a new file, 0002_..., in this
-- folder, so the repo IS the schema and a sceptic can read it. This file
-- is not idempotent on purpose — running it twice fails loudly.
--
-- Written 2026-09-18. tests.py holds it against the client:
--   test_migration_has_no_key_column       every text/jsonb column carries
--                                           looks_like_key(), RLS on every
--                                           table, every policy to
--                                           authenticated, anon revoked,
--                                           the bucket private
--   test_redactor_patterns_match_migration  the KEY-PATTERNS block below
--                                           equals redact.PATTERNS
--   test_env_matches_server_whitelist       the ENV-KEYS block below equals
--                                           what problems.env() sends
--   test_payload_columns_are_whitelist      the client's insert bodies use
--                                           only columns defined here
--
-- KEY-PATTERNS — the client redactor's patterns (redact.py, D8), one per
-- line as name<TAB>python-regex. The SQL function below carries the same
-- expressions in Postgres syntax (\b becomes \y); the test parses this
-- block, translates, and finds every one in the function's body.
-- BEGIN KEY-PATTERNS
-- phone-link	#t=[0-9A-Za-z_-]+
-- bearer	\bBearer\s+[^\s\"']+
-- gemini-key	\bAIza[0-9A-Za-z_-]{30,}
-- groq-key	\bgsk_[0-9A-Za-z]{20,}
-- openai-key	\bsk-[0-9A-Za-z_-]{20,}
-- supabase-key	\bsb_(?:publishable|secret)_[0-9A-Za-z_-]{10,}
-- jwt	\beyJ[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+
-- END KEY-PATTERNS
--
-- ENV-KEYS — the top-level keys problem_reports.env may carry: exactly the
-- whitelist problems.env() builds (plan 7.8). Model NAMES, never a key.
-- BEGIN ENV-KEYS
-- version os_build consents gpu tier branch backend local_model
-- english_model beam_size gemini_models vocab_enabled
-- vocab_replace_after_hits polish_when punctuate_auto review_enabled
-- max_seconds
-- END ENV-KEYS

-- ---------------------------------------------------------------- helpers

-- The key-shaped check, defined once and used by every free-text and
-- jsonb column: true when the text carries anything the client redactor
-- would have replaced. A row that trips it is a client bug (the redactor
-- runs first), and the client marks that report "failed" and stops.
create or replace function public.looks_like_key(t text)
returns boolean
language sql
immutable
strict
parallel safe
as $$
  select t ~ '#t=[0-9A-Za-z_-]+'
      or t ~ '\yBearer\s+[^\s\"'']+'
      or t ~ '\yAIza[0-9A-Za-z_-]{30,}'
      or t ~ '\ygsk_[0-9A-Za-z]{20,}'
      or t ~ '\ysk-[0-9A-Za-z_-]{20,}'
      or t ~ '\ysb_(?:publishable|secret)_[0-9A-Za-z_-]{10,}'
      or t ~ '\yeyJ[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+'
$$;

-- The env whitelist as a CHECK: every top-level key of the jsonb is one
-- of the ENV-KEYS above (an empty object passes).
create or replace function public.env_keys_allowed(env jsonb)
returns boolean
language sql
immutable
strict
parallel safe
as $$
  select jsonb_typeof(env) = 'object'
     and coalesce((select bool_and(k = any (array[
           'version', 'os_build', 'consents', 'gpu', 'tier', 'branch',
           'backend', 'local_model', 'english_model', 'beam_size',
           'gemini_models', 'vocab_enabled', 'vocab_replace_after_hits',
           'polish_when', 'punctuate_auto', 'review_enabled', 'max_seconds']))
         from jsonb_object_keys(env) as k), true)
$$;

-- Every attachment path of a report starts with <user_id>/<report_id>/,
-- climbs nowhere, and is not itself key-shaped.
create or replace function public.attachments_under(paths text[], uid uuid, rid uuid)
returns boolean
language sql
immutable
strict
parallel safe
as $$
  select coalesce((select bool_and(p like uid::text || '/' || rid::text || '/%'
                                   and p not like '%..%'
                                   and not public.looks_like_key(p))
                     from unnest(paths) as p), true)
$$;

-- updated_at is the server's, never the client's.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end
$$;

-- ----------------------------------------------------------------- tables
-- In dependency order. Every table: RLS on, an index on user_id, every
-- policy `to authenticated` with the (select auth.uid()) = user_id shape.

-- One row per account, written by the client right after its first
-- sign-in. No display name: accounts are anonymous or a Google identity
-- whose e-mail lives in auth.users, never here.
create table public.profiles (
  user_id               uuid primary key references auth.users (id) on delete cascade,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  app_version_last_seen text not null default '' check (char_length(app_version_last_seen) <= 32 and not public.looks_like_key(app_version_last_seen)),
  is_anonymous          boolean not null default true
);

-- The PCs of one account, so a two-PC user can tell the sync apart.
-- `name` is what the person calls the machine; the client sends the
-- computer name unless they typed another.
create table public.devices (
  id          uuid primary key,
  user_id     uuid not null references auth.users (id) on delete cascade,
  name        text not null default '' check (char_length(name) <= 40 and not public.looks_like_key(name)),
  platform    text not null default '' check (char_length(platform) <= 32 and not public.looks_like_key(platform)),
  app_version text not null default '' check (char_length(app_version) <= 32 and not public.looks_like_key(app_version)),
  tier        text not null default '' check (tier in ('', 'gpu', 'gpu_small', 'cpu', 'cloud')),
  created_at  timestamptz not null default now(),
  last_seen   timestamptz not null default now()
);
create index devices_user_id on public.devices (user_id);

-- The settings.toml override set, minus every machine-bound key (sync.py
-- drops paths, devices, hotkeys, ports, positions and the [privacy]
-- gates before it leaves the PC). Last writer wins by updated_at.
create table public.settings_sync (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  json       jsonb not null default '{}'::jsonb
             check (jsonb_typeof(json) = 'object'
                    and octet_length(json::text) <= 65536
                    and not public.looks_like_key(json::text)),
  updated_at timestamptz not null default now()
);

-- One row per learned correction of vocab.json (D31: per entry, not one
-- blob), keyed by what the decoder heard. Merged as a union: the higher
-- hits count wins, a `deleted` row is a tombstone for "Forget a word".
create table public.vocab_sync (
  user_id    uuid not null references auth.users (id) on delete cascade,
  heard      text not null check (char_length(heard) <= 200 and not public.looks_like_key(heard)),
  meant      text not null default '' check (char_length(meant) <= 200 and not public.looks_like_key(meant)),
  hits       integer not null default 1 check (hits >= 0 and hits <= 1000000),
  last_used  timestamptz,
  deleted    boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (user_id, heard)
);
create index vocab_sync_user_updated on public.vocab_sync (user_id, updated_at);

-- What was dictated, translated, punctuated, looked up or learned, one
-- row per transcripts.log event, for people who turned on
-- [privacy] history_sync (D31). Append-only from the client's side; the
-- Said page on every signed-in PC reads the merged set. The developer
-- can technically read these rows — RLS protects users from each other,
-- not from the project admin — and the privacy policy says so.
create table public.history (
  user_id    uuid not null references auth.users (id) on delete cascade,
  device_id  uuid not null,
  ts         timestamptz not null,
  kind       text not null check (kind in ('dictation', 'translate', 'punctuate', 'lookup', 'learned')),
  text       text not null default '' check (char_length(text) <= 4000 and not public.looks_like_key(text)),
  raw        text check (raw is null or (char_length(raw) <= 4000 and not public.looks_like_key(raw))),
  engine     text not null default '' check (char_length(engine) <= 32 and not public.looks_like_key(engine)),
  seconds    real check (seconds is null or (seconds >= 0 and seconds <= 36000)),
  updated_at timestamptz not null default now(),
  primary key (user_id, device_id, ts, kind)
);
create index history_user_updated on public.history (user_id, updated_at);

-- One row per problem report the person chose to send (chapter 7's
-- "Send to the developer"). `id` is the client's own report id, so a
-- retry after a half-success is idempotent. `place` is the plan's
-- `where` — a reserved word in SQL.
create table public.problem_reports (
  id              uuid primary key,
  user_id         uuid not null references auth.users (id) on delete cascade,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  app_version     text not null default '' check (char_length(app_version) <= 32 and not public.looks_like_key(app_version)),
  os_build        text not null default '' check (char_length(os_build) <= 32 and not public.looks_like_key(os_build)),
  tier            text not null default '' check (tier in ('', 'gpu', 'gpu_small', 'cpu', 'cloud')),
  kind            text not null check (kind in ('wrong', 'broken', 'slow', 'idea', 'other')),
  place           text not null default '' check (char_length(place) <= 120 and not public.looks_like_key(place)),
  text            text not null check (char_length(text) between 1 and 600 and not public.looks_like_key(text)),
  dictation_raw   text check (dictation_raw is null or (char_length(dictation_raw) <= 4000 and not public.looks_like_key(dictation_raw))),
  dictation_final text check (dictation_final is null or (char_length(dictation_final) <= 4000 and not public.looks_like_key(dictation_final))),
  env             jsonb not null default '{}'::jsonb
                  check (public.env_keys_allowed(env)
                         and octet_length(env::text) <= 16384
                         and not public.looks_like_key(env::text)),
  attachments     text[] not null default '{}'::text[]
                  check (cardinality(attachments) <= 8
                         and public.attachments_under(attachments, user_id, id)),
  status          text not null default 'open' check (status in ('open', 'fixed', 'closed'))
);
create index problem_reports_user_id on public.problem_reports (user_id);
create index problem_reports_user_updated on public.problem_reports (user_id, updated_at);

-- The audit line delete_me() writes before the account disappears: the
-- one trace that survives, with no personal content. Readable only with
-- the secret key.
create table public.deletion_requests (
  user_id      uuid not null,
  requested_at timestamptz not null default now()
);

-- --------------------------------------------------------------- triggers

create trigger profiles_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();
create trigger settings_sync_updated_at before update on public.settings_sync
  for each row execute function public.set_updated_at();
create trigger vocab_sync_updated_at before update on public.vocab_sync
  for each row execute function public.set_updated_at();
create trigger history_updated_at before update on public.history
  for each row execute function public.set_updated_at();
create trigger problem_reports_updated_at before update on public.problem_reports
  for each row execute function public.set_updated_at();

-- From the client only app_version_last_seen may change on a profile.
-- is_anonymous flips only through Supabase's own identity linking; the
-- client mirrors the flip by re-upserting, and that write is allowed
-- only when it carries the value auth.users already holds. Security
-- definer so the look at auth.users runs as the owner (the client role
-- cannot read that table).
create or replace function public.profiles_guard()
returns trigger
language plpgsql
security definer
set search_path = public, auth
as $$
begin
  if new.user_id <> old.user_id or new.created_at <> old.created_at then
    raise exception 'profiles: user_id and created_at are frozen';
  end if;
  if new.is_anonymous <> old.is_anonymous
     and new.is_anonymous <> coalesce((select u.is_anonymous from auth.users u where u.id = old.user_id), old.is_anonymous) then
    raise exception 'profiles: is_anonymous follows auth.users';
  end if;
  return new;
end
$$;
create trigger profiles_guard before update on public.profiles
  for each row execute function public.profiles_guard();

-- From the client only `status` may change on a report: the text, the
-- transcripts, env and the attachment list are frozen after insert.
create or replace function public.problem_reports_guard()
returns trigger
language plpgsql
as $$
begin
  if new.user_id <> old.user_id
     or new.created_at <> old.created_at
     or new.app_version <> old.app_version
     or new.os_build <> old.os_build
     or new.tier <> old.tier
     or new.kind <> old.kind
     or new.place <> old.place
     or new.text <> old.text
     or new.dictation_raw is distinct from old.dictation_raw
     or new.dictation_final is distinct from old.dictation_final
     or new.env <> old.env
     or new.attachments <> old.attachments then
    raise exception 'problem_reports: only status may change after insert';
  end if;
  return new;
end
$$;
create trigger problem_reports_guard before update on public.problem_reports
  for each row execute function public.problem_reports_guard();

-- ---------------------------------------------------- row-level security
-- "Own row" everywhere: (select auth.uid()) = user_id, the sub-select the
-- Supabase RLS guide recommends so the planner evaluates it once.

alter table public.profiles          enable row level security;
alter table public.devices           enable row level security;
alter table public.settings_sync     enable row level security;
alter table public.vocab_sync        enable row level security;
alter table public.history           enable row level security;
alter table public.problem_reports   enable row level security;
alter table public.deletion_requests enable row level security;

create policy profiles_select on public.profiles for select to authenticated
  using ((select auth.uid()) = user_id);
create policy profiles_insert on public.profiles for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy profiles_update on public.profiles for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
-- no delete policy: a profile goes only with the auth user (delete_me)

create policy devices_select on public.devices for select to authenticated
  using ((select auth.uid()) = user_id);
create policy devices_insert on public.devices for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy devices_update on public.devices for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy devices_delete on public.devices for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy settings_sync_select on public.settings_sync for select to authenticated
  using ((select auth.uid()) = user_id);
create policy settings_sync_insert on public.settings_sync for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy settings_sync_update on public.settings_sync for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy settings_sync_delete on public.settings_sync for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy vocab_sync_select on public.vocab_sync for select to authenticated
  using ((select auth.uid()) = user_id);
create policy vocab_sync_insert on public.vocab_sync for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy vocab_sync_update on public.vocab_sync for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy vocab_sync_delete on public.vocab_sync for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy history_select on public.history for select to authenticated
  using ((select auth.uid()) = user_id);
create policy history_insert on public.history for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy history_update on public.history for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy history_delete on public.history for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy problem_reports_select on public.problem_reports for select to authenticated
  using ((select auth.uid()) = user_id);
create policy problem_reports_insert on public.problem_reports for insert to authenticated
  with check ((select auth.uid()) = user_id and status = 'open');
create policy problem_reports_update on public.problem_reports for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy problem_reports_delete on public.problem_reports for delete to authenticated
  using ((select auth.uid()) = user_id);

-- deletion_requests: no policy at all — nobody but the secret key reads it.

-- ------------------------------------------------------------- privileges
-- A client holding only the publishable key and no session (the `anon`
-- role) sees nothing: every privilege on this schema's tables, sequences
-- and functions is revoked from it. `authenticated` gets exactly the
-- verbs the policies above allow.

revoke all on all tables    in schema public from anon;
revoke all on all sequences in schema public from anon;
revoke all on all functions in schema public from anon;
alter default privileges in schema public revoke all on tables    from anon;
alter default privileges in schema public revoke all on sequences from anon;
alter default privileges in schema public revoke all on functions from anon;

revoke all on all tables in schema public from authenticated;
grant select, insert, update         on public.profiles        to authenticated;
grant select, insert, update, delete on public.devices         to authenticated;
grant select, insert, update, delete on public.settings_sync   to authenticated;
grant select, insert, update, delete on public.vocab_sync      to authenticated;
grant select, insert, update, delete on public.history         to authenticated;
grant select, insert, update, delete on public.problem_reports to authenticated;
-- deletion_requests: nothing to authenticated either

-- ---------------------------------------------------------------- storage
-- One private bucket. A public bucket bypasses RLS for reads, so it is
-- private, and the limits live here rather than in a dashboard click.
-- Path convention: <user_id>/<report_id>/<file>. If this project version
-- refuses the two limit columns, set them in Storage > reports and note
-- it here (8.11 step 6).

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('reports', 'reports', false, 5242880,
        array['image/jpeg', 'application/json', 'text/plain', 'audio/wav']);

create policy reports_objects_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'reports'
              and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy reports_objects_select on storage.objects for select to authenticated
  using (bucket_id = 'reports'
         and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy reports_objects_delete on storage.objects for delete to authenticated
  using (bucket_id = 'reports'
         and (storage.foldername(name))[1] = (select auth.uid())::text);
-- no update policy: an attachment is never replaced, a new report is filed

-- -------------------------------------------------------------- delete_me
-- "Delete my account": one function, no arguments (it acts on the
-- caller's own uid — a user_id argument would be a foot-gun), callable by
-- authenticated only. The client removes its own storage objects first
-- (it holds the delete policy); the rows here are the backstop, the
-- explicit deletes are there so a missing cascade cannot leave one.
create or replace function public.delete_me()
returns void
language plpgsql
security definer
set search_path = public, storage, auth
as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    raise exception 'delete_me: no session';
  end if;
  insert into public.deletion_requests (user_id) values (uid);
  delete from storage.objects
   where bucket_id = 'reports' and (storage.foldername(name))[1] = uid::text;
  delete from public.problem_reports where user_id = uid;
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
-- Every column, and why none can hold a key (D12 lock 3; the guide's
-- "check it yourself" chapter links here):
--
--   profiles         user_id created_at updated_at app_version_last_seen is_anonymous
--   devices          id user_id name platform app_version tier created_at last_seen
--   settings_sync    user_id json updated_at
--   vocab_sync       user_id heard meant hits last_used deleted updated_at
--   history          user_id device_id ts kind text raw engine seconds updated_at
--   problem_reports  id user_id created_at updated_at app_version os_build tier
--                    kind place text dictation_raw dictation_final env attachments status
--   deletion_requests user_id requested_at
--
-- No column is named key, secret, token, password or apikey, and none is
-- meant for one. Every text column that is not an enumeration (name,
-- platform, app_version, os_build, app_version_last_seen, heard, meant,
-- text, raw, engine, place, dictation_raw, dictation_final, each
-- attachment path) and every jsonb column (json, env) carries
-- `not public.looks_like_key(...)`, so a Groq, Google, OpenAI or Supabase
-- key, a bearer or a JWT pasted into any of them is refused by the
-- database itself — after the client's redactor has already replaced it
-- with [redacted:<kind>]. The enumerations (kind, status, tier) admit
-- only their listed words. The client module that
-- talks to this schema (sb.py) cannot import the modules that read a key
-- (test_sb_imports_are_narrow), and net.py attaches a Groq or Google key
-- only to that provider's own host, never to this one (test
-- test_no_keys_reach_supabase). The settings blob never carries the keys
-- page's fields, hotkeys, paths, devices, ports or positions (sync.py,
-- test_sync_serializer_drops_sync_false).
