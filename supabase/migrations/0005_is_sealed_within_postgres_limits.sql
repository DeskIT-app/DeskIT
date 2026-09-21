-- DeskIT — is_sealed() as Postgres can run it (2026-09-21, an hour after 0004).
--
-- Measured live right after 0004 ran: the first call of is_sealed()
-- answered
--   ERROR 2201B: invalid regular expression: invalid repetition count(s)
-- Postgres' regex engine caps a bound in `{m,n}` at 255, and 0004 wrote
-- `{16,7600}` — the length cap of a sealed value in the same bound as
-- its shape. Every CHECK that calls the function would have refused
-- every row (no row had been written yet). The cap moves out of the
-- regex into char_length; the shape is the same, and vault.is_sealed in
-- the app is the same expression again (test_migration_has_no_key_column
-- holds the two equal).
--
-- Applied once through the Supabase connector after 0004, 2026-09-21.

create or replace function public.is_sealed(t text)
returns boolean
language sql
immutable
strict
parallel safe
as $$
  select char_length(t) <= 7603
     and t ~ '^[a-z][0-9]\.[A-Za-z0-9+/]{16,}={0,2}$'
$$;
