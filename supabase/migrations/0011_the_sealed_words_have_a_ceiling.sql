-- DeskIT — the sealed words have a ceiling too (2026-11-27).
--
-- 0009 gave every table a client writes to a ceiling per account; 0010,
-- written beside it the same evening, added one more such table,
-- `vocab_sealed`, and left its ceiling to this file on purpose (the two
-- lanes could not see each other's work). This is the eighth table under
-- the same mechanism, and nothing else changes: the two functions are
-- written again whole with one more line each, the three triggers are the
-- other tables' three, and the table's count is made from the rows as they
-- stand.
--
--   table          rows (signed in / anonymous)   bytes (signed in / anonymous)
--   vocab_sealed   5000 / 500                      4,000,000 / 400,000
--
-- Sized like vocab_sync in 0009: the busiest account held 202 words on
-- 2026-11-27, and a sealed row is its 32-character id and a cipher of at
-- most 4,096 characters (0010's check), so 5,000 rows are about 25x the
-- busiest list; the byte line, not the row line, is what bounds an account
-- (4 MB against 21.6 MB for 5,000 rows at the cipher's longest). A signed-in
-- account at every ceiling now holds at most about 35 MB of the plan's 500
-- (0009 said 31), an anonymous one about 1.9 MB.

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
    when 'vocab_sealed'    then '200 + octet_length(id) + octet_length(cipher)'
    when 'settings_sync'   then '200 + octet_length(json::text)'
    when 'vault'           then '200 + 2 * octet_length(name) + octet_length(cipher)'
    when 'devices'         then '200 + octet_length(name) + octet_length(platform) + octet_length(app_version) + coalesce(octet_length(link), 0)'
    when 'pairings'        then '200 + octet_length(device_name) + octet_length(code) + octet_length(applicant) + coalesce(octet_length(handed), 0)'
    when 'problem_reports' then '200 + octet_length(app_version) + octet_length(os_build) + octet_length(place) + octet_length(text) + coalesce(octet_length(dictation_raw), 0) + coalesce(octet_length(dictation_final), 0) + octet_length(env::text) + octet_length(attachments::text)'
  end
$$;

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
      ('vocab_sealed',    false, 5000,  4000000),
      ('vocab_sealed',    true,  500,   400000),
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

drop trigger if exists vocab_sealed_usage_insert on public.vocab_sealed;
create trigger vocab_sealed_usage_insert after insert on public.vocab_sealed
  referencing new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists vocab_sealed_usage_update on public.vocab_sealed;
create trigger vocab_sealed_usage_update after update on public.vocab_sealed
  referencing old table as old_rows new table as new_rows
  for each statement execute function private.usage_counted();
drop trigger if exists vocab_sealed_usage_delete on public.vocab_sealed;
create trigger vocab_sealed_usage_delete after delete on public.vocab_sealed
  referencing old table as old_rows
  for each statement execute function private.usage_counted();

-- the count, from the rows as they stand (none, the evening 0010 landed)
delete from private.account_usage where tbl = 'vocab_sealed';
insert into private.account_usage (user_id, tbl, n_rows, n_bytes)
select user_id, 'vocab_sealed', count(*), sum(200 + octet_length(id) + octet_length(cipher))
  from public.vocab_sealed group by user_id;
