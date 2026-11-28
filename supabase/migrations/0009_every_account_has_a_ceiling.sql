-- DeskIT — every account has a ceiling (2026-11-27).
--
-- The 2026-11-09 audit, item A20, and the owner's go the day this was
-- written: one account must not be able to fill the shared free database
-- and so stop every new person from signing up. Above all a throwaway
-- anonymous one, which anybody can make with the publishable key that ships
-- in the app (anonymous sign-ins are on in this project; Supabase limits
-- them per IP address, 30 an hour by its default). Until this file nothing
-- counted what one account held: `history`, `vocab_sync`, `devices`,
-- `pairings`, `problem_reports` and `vault` took rows without end, each row
-- bounded only by its own CHECKs.
--
-- Read on the live project that day: 15 MB in all of the Free plan's
-- 500 MB. The busiest account held 2,490 history rows (1.9 MB, about 770
-- bytes a row) and 202 learned words; 18 device rows in the whole project,
-- one vault row, no pairings, no problem reports, no stored files.
--
-- What is counted. A small table nobody can read or write but these
-- triggers, `private.account_usage`, keeps one line per account and table:
-- its rows, and its bytes as `private.usage_bytes()` counts them — 200
-- bytes a row for the row's header, its fixed columns and its index
-- entries, plus the octet length of every column the client fills with
-- text it chooses (a column in an index counted twice). `octet_length()`
-- reads a TOASTed value's size from its pointer, so nothing is
-- decompressed or fetched to count it. Checked on a scratch PostgreSQL 17
-- with every migration applied: 2,490 history rows of the live average
-- (a 563-character seal) counted 1,912,320 bytes and took 1,982,464 on
-- disk, table, TOAST and both indexes.
--
-- BEGIN CEILINGS
-- table            rows    bytes       anonymous: rows  bytes     busiest account on 2026-11-27
-- history          50000   25000000    2000             1000000   2,490 rows, 1.9 MB
-- vocab_sync       5000    2000000     500              200000    202 rows
-- settings_sync    1       70000       1                20000     1 row (its key: one per account)
-- vault            32      300000      8                40000     1 row
-- devices          400     1000000     10               50000     18 rows in the whole project
-- pairings         50      500000      5                50000     none
-- problem_reports  500     2000000     20               100000    none
-- END CEILINGS
--
-- The worst case, with the arithmetic. An account at every ceiling at once
-- counts 25,000,000 + 2,000,000 + 70,000 + 300,000 + 1,000,000 + 500,000 +
-- 2,000,000 = 30,870,000 bytes, 6.2% of 500 MB; an anonymous one 1,000,000
-- + 200,000 + 20,000 + 40,000 + 50,000 + 50,000 + 100,000 = 1,460,000
-- bytes, 0.3%. What the disk holds can be somewhat more than what is
-- counted (TOAST chunks, part-filled pages, dead rows until a vacuum: 4%
-- more in the check above). Filling 500 MB therefore takes about
-- sixteen Google accounts each at every ceiling, or about 340 anonymous
-- ones: at 30 sign-ups an hour per address, more than eleven hours from
-- one address.
-- `recovery` and `profiles` are one row an account by their keys and
-- bounded by their CHECKs (a recovery row under 7.7 KB), so they are not
-- counted; `deletion_requests` is written by delete_me() alone.
--
-- What is generous. The rows: at least twenty times the busiest account
-- wherever a table has one (history 20x, words 25x, devices 22x the
-- project's 18). The bytes bind first where a row may be large: at the
-- busiest account's 770 bytes a row, history's 25 MB is about 32,000
-- rows, thirteen times today's, and twenty times would be 38 MB for one
-- account, 7.7% of the plan on its own: that is where the bytes did not
-- allow it. At the owner's rate (2,490 rows since 2026-09-21) that is
-- about two years more; a later migration raises a number in one line.
-- An anonymous account holds about a month of the owner's dictation, and
-- its person is told to sign in with Google for more room (the uid stays,
-- the ceiling becomes the one above at the next token, `is_anonymous`).
--
-- Who is anonymous: the caller's own token says so (`is_anonymous` in
-- auth.jwt(), signed by the auth server), and only for the rows of the
-- account the token is (its `sub`); anything else (the service role, the
-- SQL editor) is held to the ceiling of a signed-in person.
--
-- The refusal: SQLSTATE PT507, message `account full: <table>`, detail
-- `<n> rows of <ceiling>, <n> bytes of <ceiling>` (counts only). PostgREST
-- answers a PTxyz code with HTTP xyz, so this is 507 Insufficient Storage
-- on purpose, a 5xx: every client older than the one that knows the code
-- keeps what a 5xx refused and tries again later (the phone drops a
-- history row the server answers with a 4xx, Backup.flush), so nothing is
-- lost anywhere. The app (sb.py, AccountFull) keeps the rows on the PC,
-- stops sending that table for six hours, logs one line and says so in
-- plain words on Settings > Account. A statement is refused only when it
-- GROWS the account (more rows, or more bytes) past a ceiling: a delete,
-- or an update that shrinks, always goes through, so an account over a
-- ceiling that is lowered later can still make room.
--
-- What it costs. One check per STATEMENT, never per row and never a
-- count(*) over the account: an AFTER ... FOR EACH STATEMENT trigger with
-- the statement's own rows as a transition table. Each push the app makes
-- is one statement (history goes up in batches of up to 500 rows, the
-- words and the keys as one upsert each): one aggregate over that batch's
-- rows, one primary-key update of the account's line in account_usage
-- (an insert the first time), one look at a 14-row VALUES list. An upsert
-- (the client's merge-duplicates) fires both the insert and the update
-- trigger, each with only its own rows. Measured with EXPLAIN ANALYZE on
-- the scratch PostgreSQL 17 above, one session, warm: the two triggers
-- took 0.55 to 0.80 ms a statement together, for one row or for 500, on an
-- account of 3,000 rows or of 49,000; the foreign-key check on the same
-- 500 rows took 1.8 to 1.9 ms and the whole statement 14 to 17 ms. The
-- first statement of a connection pays 2.6 to 2.9 ms a trigger once, to
-- compile it.
--
-- The 0008 rules: every new function has a pinned search_path (empty: each
-- name is qualified), EXECUTE goes from PUBLIC and anon and stays with
-- authenticated and service_role. usage_counted() is SECURITY DEFINER, and
-- must be: the account_usage table grants nothing to anybody, so the
-- client role can never write its own count down; a trigger function
-- cannot be called but as a trigger, and `private` is not a schema the API
-- serves. RLS on the public tables is untouched.
--
-- Idempotent: the table if not exists, the functions created or replaced,
-- every trigger dropped if it exists and made again, and the counts made
-- again from the rows at the end, inside the one transaction the file runs
-- in (creating a trigger holds its table against writes until the commit,
-- so no row is counted twice or missed). 0006 made the `private` schema.

-- ----------------------------------------------------------- the counts

create table if not exists private.account_usage (
  user_id uuid not null references auth.users (id) on delete cascade,
  tbl     text not null,
  n_rows  bigint not null default 0,
  n_bytes bigint not null default 0,
  primary key (user_id, tbl)
);
alter table private.account_usage enable row level security;
-- no policy: only the owner of the table, the triggers below, reads or writes it
revoke all on private.account_usage from public, anon, authenticated;

-- What one row of a table counts, as an expression over its columns: the
-- one place it is written, used by the trigger and by the recount below.
create or replace function private.usage_bytes(tbl text)
returns text
language sql
immutable
parallel safe
set search_path = ''
as $$
  select case tbl
    when 'history'         then '200 + octet_length(cipher) + octet_length(engine)'
    when 'vocab_sync'      then '200 + 2 * octet_length(heard) + octet_length(meant)'
    when 'settings_sync'   then '200 + octet_length(json::text)'
    when 'vault'           then '200 + 2 * octet_length(name) + octet_length(cipher)'
    when 'devices'         then '200 + octet_length(name) + octet_length(platform) + octet_length(app_version) + coalesce(octet_length(link), 0)'
    when 'pairings'        then '200 + octet_length(device_name) + octet_length(code) + octet_length(applicant) + coalesce(octet_length(handed), 0)'
    when 'problem_reports' then '200 + octet_length(app_version) + octet_length(os_build) + octet_length(place) + octet_length(text) + coalesce(octet_length(dictation_raw), 0) + coalesce(octet_length(dictation_final), 0) + octet_length(env::text) + octet_length(attachments::text)'
  end
$$;

-- The CEILINGS block above, as the database reads it.
create or replace function private.account_ceiling(tbl text, anonymous boolean)
returns table (max_rows bigint, max_bytes bigint)
language sql
immutable
parallel safe
set search_path = ''
as $$
  select c.r::bigint, c.b::bigint
    from (values
      ('history',         false, 50000, 25000000),
      ('history',         true,  2000,  1000000),
      ('vocab_sync',      false, 5000,  2000000),
      ('vocab_sync',      true,  500,   200000),
      ('settings_sync',   false, 1,     70000),
      ('settings_sync',   true,  1,     20000),
      ('vault',           false, 32,    300000),
      ('vault',           true,  8,     40000),
      ('devices',         false, 400,   1000000),
      ('devices',         true,  10,    50000),
      ('pairings',        false, 50,    500000),
      ('pairings',        true,  5,     50000),
      ('problem_reports', false, 500,   2000000),
      ('problem_reports', true,  20,    100000)
    ) as c (t, a, r, b)
   where c.t = tbl and c.a = anonymous
$$;

-- The trigger: what the statement added or took away, per account, onto
-- that account's line, and a refusal when it grew past a ceiling. The
-- aggregate is dynamic SQL only so that each table's expression is written
-- once (usage_bytes); it reads the statement's transition table, which a
-- PL/pgSQL trigger makes visible to EXECUTE too.
create or replace function private.usage_counted()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  expr  text := private.usage_bytes(tg_table_name);
  q     text;
  uids  uuid[];
  ns    bigint[];
  bs    bigint[];
  total_rows  bigint;
  total_bytes bigint;
  lim_rows    bigint;
  lim_bytes   bigint;
  claims jsonb := auth.jwt();
  anon  boolean;
begin
  if expr is null then
    return null;
  end if;
  if tg_op = 'INSERT' then
    q := format('select array_agg(user_id), array_agg(n), array_agg(b) from ('
                'select user_id, count(*)::bigint as n, sum(%s)::bigint as b '
                'from new_rows group by user_id) d', expr);
  elsif tg_op = 'UPDATE' then
    q := format('select array_agg(user_id), array_agg(n), array_agg(b) from ('
                'select user_id, sum(n)::bigint as n, sum(b)::bigint as b from ('
                'select user_id, 1 as n, (%1$s)::bigint as b from new_rows '
                'union all select user_id, -1, -((%1$s)::bigint) from old_rows) r '
                'group by user_id) d', expr);
  else
    q := format('select array_agg(user_id), array_agg(n), array_agg(b) from ('
                'select user_id, -count(*)::bigint as n, -sum(%s)::bigint as b '
                'from old_rows group by user_id) d', expr);
  end if;
  execute q into uids, ns, bs;
  for i in 1 .. coalesce(cardinality(uids), 0) loop
    update private.account_usage u
       set n_rows  = greatest(u.n_rows + ns[i], 0),
           n_bytes = greatest(u.n_bytes + bs[i], 0)
     where u.user_id = uids[i] and u.tbl = tg_table_name
     returning u.n_rows, u.n_bytes into total_rows, total_bytes;
    if not found then
      -- a delete of an account that has no line (or whose line went with
      -- its auth.users row first) has nothing to take away
      continue when tg_op = 'DELETE';
      insert into private.account_usage as u (user_id, tbl, n_rows, n_bytes)
      values (uids[i], tg_table_name, greatest(ns[i], 0), greatest(bs[i], 0))
      on conflict (user_id, tbl) do update
         set n_rows  = u.n_rows + excluded.n_rows,
             n_bytes = u.n_bytes + excluded.n_bytes
      returning u.n_rows, u.n_bytes into total_rows, total_bytes;
    end if;
    continue when tg_op = 'DELETE' or (ns[i] <= 0 and bs[i] <= 0);
    anon := coalesce((claims ->> 'is_anonymous')::boolean, false)
            and coalesce(claims ->> 'sub' = uids[i]::text, false);
    select c.max_rows, c.max_bytes into lim_rows, lim_bytes
      from private.account_ceiling(tg_table_name, anon) c;
    if total_rows > lim_rows or total_bytes > lim_bytes then
      raise exception using
        errcode = 'PT507',
        message = 'account full: ' || tg_table_name,
        detail  = format('%s rows of %s, %s bytes of %s', total_rows, lim_rows, total_bytes, lim_bytes),
        hint    = case when anon then 'an anonymous account has less room: sign in with Google for more'
                       else 'nothing was written: remove what is no longer needed to make room' end;
    end if;
  end loop;
  return null;
end
$$;

revoke execute on function private.usage_bytes(text) from public, anon;
revoke execute on function private.account_ceiling(text, boolean) from public, anon;
revoke execute on function private.usage_counted() from public, anon;
grant execute on function private.usage_bytes(text) to authenticated, service_role;
grant execute on function private.account_ceiling(text, boolean) to authenticated, service_role;
grant execute on function private.usage_counted() to authenticated, service_role;

-- --------------------------------------------------------- the triggers
-- Three a table: a trigger with a transition table may name one event only.

drop trigger if exists history_usage_insert on public.history;
create trigger history_usage_insert after insert on public.history
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists history_usage_update on public.history;
create trigger history_usage_update after update on public.history
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists history_usage_delete on public.history;
create trigger history_usage_delete after delete on public.history
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

drop trigger if exists vocab_sync_usage_insert on public.vocab_sync;
create trigger vocab_sync_usage_insert after insert on public.vocab_sync
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists vocab_sync_usage_update on public.vocab_sync;
create trigger vocab_sync_usage_update after update on public.vocab_sync
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists vocab_sync_usage_delete on public.vocab_sync;
create trigger vocab_sync_usage_delete after delete on public.vocab_sync
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

drop trigger if exists settings_sync_usage_insert on public.settings_sync;
create trigger settings_sync_usage_insert after insert on public.settings_sync
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists settings_sync_usage_update on public.settings_sync;
create trigger settings_sync_usage_update after update on public.settings_sync
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists settings_sync_usage_delete on public.settings_sync;
create trigger settings_sync_usage_delete after delete on public.settings_sync
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

drop trigger if exists vault_usage_insert on public.vault;
create trigger vault_usage_insert after insert on public.vault
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists vault_usage_update on public.vault;
create trigger vault_usage_update after update on public.vault
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists vault_usage_delete on public.vault;
create trigger vault_usage_delete after delete on public.vault
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

drop trigger if exists devices_usage_insert on public.devices;
create trigger devices_usage_insert after insert on public.devices
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists devices_usage_update on public.devices;
create trigger devices_usage_update after update on public.devices
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists devices_usage_delete on public.devices;
create trigger devices_usage_delete after delete on public.devices
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

drop trigger if exists pairings_usage_insert on public.pairings;
create trigger pairings_usage_insert after insert on public.pairings
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists pairings_usage_update on public.pairings;
create trigger pairings_usage_update after update on public.pairings
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists pairings_usage_delete on public.pairings;
create trigger pairings_usage_delete after delete on public.pairings
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

drop trigger if exists problem_reports_usage_insert on public.problem_reports;
create trigger problem_reports_usage_insert after insert on public.problem_reports
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists problem_reports_usage_update on public.problem_reports;
create trigger problem_reports_usage_update after update on public.problem_reports
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists problem_reports_usage_delete on public.problem_reports;
create trigger problem_reports_usage_delete after delete on public.problem_reports
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

-- ----------------------------------------------------- the counts, made
-- From the rows as they stand, with the triggers' own expression. An
-- account already past a ceiling keeps everything it has, and can shrink
-- but not grow.

do $$
declare
  t text;
begin
  delete from private.account_usage;
  foreach t in array array['history', 'vocab_sync', 'settings_sync', 'vault',
                           'devices', 'pairings', 'problem_reports'] loop
    execute format('insert into private.account_usage (user_id, tbl, n_rows, n_bytes) '
                   'select user_id, %L, count(*), sum(%s) from public.%I group by user_id',
                   t, private.usage_bytes(t), t);
  end loop;
end
$$;

-- ----------------------------------------------------------------- footer
-- What this file adds, and what any of it can read:
--
--   private.account_usage   user_id tbl n_rows n_bytes — counts, no word of
--                           anybody's; no grant, no policy, not served by the API
--   private.usage_bytes()   the expression each table's rows are counted by
--   private.account_ceiling()  the CEILINGS block
--   private.usage_counted() the trigger, three a table on seven tables
--
-- No column is added to a public table, so D12 lock 3 reads as it did.
