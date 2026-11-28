-- DeskIT — our functions answer only the signed in, on a fixed search path
-- (2026-11-27).
--
-- Found by the project's own security advisor, run on the LIVE database for
-- the first time that day (the 2026-11-09 audit could read only the files):
--
--   * anon could EXECUTE every helper in public (is_sealed, looks_like_key,
--     env_keys_allowed, attachments_under) and the trigger functions
--     (pairings_guard, problem_reports_guard, profiles_guard,
--     set_updated_at). Supabase grants EXECUTE on new functions to anon and
--     authenticated by default. Nothing here is a hole on its own — the
--     helpers are pure checks and a trigger function called through
--     /rest/v1/rpc only errors — but profiles_guard is SECURITY DEFINER, and
--     a caller who has not signed in has no business calling any of them.
--   * seven functions had a role-mutable search_path. profiles_guard,
--     delete_me and forget_device were already pinned.
--
-- What this changes: EXECUTE goes from PUBLIC and anon; authenticated and
-- service_role keep it explicitly. They must: the helpers are called inside
-- the CHECK constraints of rows a signed-in device inserts, and those are
-- evaluated with the inserting role's privileges. anon has no privilege on
-- any table (0001), so no insert of anon's ever reached those checks.
-- Every pinned search_path is `public, pg_temp`: each body names our own
-- tables unqualified, as the default path resolved them, and pg_temp last
-- is Postgres' own advice for a pinned path.
--
-- Applied to the live project the same day with the Supabase connector;
-- the advisor was read again after it.

revoke execute on function public.attachments_under(text[], uuid, uuid) from public, anon;
revoke execute on function public.env_keys_allowed(jsonb) from public, anon;
revoke execute on function public.is_sealed(text) from public, anon;
revoke execute on function public.looks_like_key(text) from public, anon;
revoke execute on function public.pairings_guard() from public, anon;
revoke execute on function public.problem_reports_guard() from public, anon;
revoke execute on function public.profiles_guard() from public, anon;
revoke execute on function public.set_updated_at() from public, anon;

grant execute on function public.attachments_under(text[], uuid, uuid) to authenticated, service_role;
grant execute on function public.env_keys_allowed(jsonb) to authenticated, service_role;
grant execute on function public.is_sealed(text) to authenticated, service_role;
grant execute on function public.looks_like_key(text) to authenticated, service_role;
grant execute on function public.pairings_guard() to authenticated, service_role;
grant execute on function public.problem_reports_guard() to authenticated, service_role;
grant execute on function public.profiles_guard() to authenticated, service_role;
grant execute on function public.set_updated_at() to authenticated, service_role;

alter function public.attachments_under(text[], uuid, uuid) set search_path = public, pg_temp;
alter function public.env_keys_allowed(jsonb) set search_path = public, pg_temp;
alter function public.is_sealed(text) set search_path = public, pg_temp;
alter function public.looks_like_key(text) set search_path = public, pg_temp;
alter function public.pairings_guard() set search_path = public, pg_temp;
alter function public.problem_reports_guard() set search_path = public, pg_temp;
alter function public.set_updated_at() set search_path = public, pg_temp;
