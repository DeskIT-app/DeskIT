-- DeskIT — a signed-out session is out at once, not at its token's hour
-- (2026-10-03).
--
-- Measured on this project the day it was found: "Sign out of every PC"
-- (POST /auth/v1/logout?scope=global) deleted every session of the
-- account at 12:38:23 UTC, and the owner's other copy went on for 58
-- minutes on the access token it already held — 90 requests, every one
-- answered: 16 history rows written, a vault row written, and two
-- requests to join the account APPROVED, the second handing the
-- account's key to a new copy 58 minutes after the sign-out. Its live
-- socket even joined again, 51 minutes after, with the same token. It
-- locked only at 13:38:02, when its refresh was refused. That is the
-- platform as documented: an access token is a signed JWT (ES256 here),
-- checked by its signature alone, and "Access Tokens of revoked sessions
-- remain valid until their expiry time" — 3600 s on this project. So
-- the changed lock's "It wasn't me", whose whole point is to throw a
-- stranger out, left the stranger in for up to an hour.
--
-- The fix is the session the token names: `auth.sessions` holds a row
-- per live session, a sign-out deletes it, and every access token
-- carries its id in the `session_id` claim. One look at that row —
-- a primary-key lookup through the function below, measured 19
-- microseconds a call (10,000 calls as the authenticated role) against
-- PostgREST's own 6-9 ms a request here — decides every request at the
-- door:
--
--   * the Data API (every table, delete_me): `pgrst.db_pre_request`
--     runs private.check_request() once per request, before the query,
--     and a session that is gone is HTTP 401. The app answers a 401
--     with one refresh, the refresh is refused ("Refresh Token Not
--     Found"), and the copy locks — the path 8.8 always had;
--   * Realtime and Storage do not run the pre-request (Supabase's own
--     caution), so their policies — the two of 0003, the three of 0001 —
--     carry the same check. Realtime reads them at a join and at every
--     new token, so a revoked session cannot join or broadcast; a socket
--     already joined keeps hearing "something changed" until its token's
--     hour is over, and can do nothing with it.
--
-- The token stays at 3600 s: a shorter one would close the same window
-- by refreshing twelve times as often (288 a day per running copy at 5
-- minutes, all of it Auth egress out of the Free plan's 5 GB, and each
-- refresh one more chance of a false sign-out on a bad network — which
-- here is a locked dictation). The app also tells its other copies on
-- the live channel right after it ends their sessions (sb.sign_out), so
-- an honest copy locks within the second; this file is what holds when
-- the copy is not listening, or is not ours.
--
-- A token with no session (the publishable key's anon role, the secret
-- key's service role) has nothing to check and passes. Nothing here
-- reads or writes a row of anyone's data.
--
-- Applied once through the Supabase connector after 0005, 2026-10-03.

create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to anon, authenticated, service_role;

-- plpgsql and not one SQL CASE: probed before this was applied, the
-- planner evaluates an index key at executor start whatever branch the
-- CASE takes, so a session_id that is not a uuid failed the whole call
-- (22P02) instead of answering false.
create or replace function private.session_ok()
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  sid text := auth.jwt() ->> 'session_id';
begin
  if coalesce(sid, '') = '' then
    return true;
  end if;
  if sid !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' then
    return false;
  end if;
  return exists (select 1 from auth.sessions s
                  where s.id = sid::uuid
                    and (s.not_after is null or s.not_after > now()));
end
$$;

create or replace function private.check_request()
returns void
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if not private.session_ok() then
    raise sqlstate 'PT401' using message = 'this session was signed out';
  end if;
end
$$;

revoke all on function private.session_ok()    from public;
revoke all on function private.check_request() from public;
grant execute on function private.session_ok()    to anon, authenticated, service_role;
grant execute on function private.check_request() to anon, authenticated, service_role;

alter role authenticator set pgrst.db_pre_request = 'private.check_request';
notify pgrst, 'reload config';

alter policy live_topic_read on realtime.messages
  using (realtime.topic() = 'user:' || (select auth.uid())::text
         and extension = 'broadcast'
         and (select private.session_ok()));

alter policy live_topic_write on realtime.messages
  with check (realtime.topic() = 'user:' || (select auth.uid())::text
              and extension = 'broadcast'
              and (select private.session_ok()));

alter policy reports_objects_insert on storage.objects
  with check (bucket_id = 'reports'
              and (storage.foldername(name))[1] = (select auth.uid())::text
              and (select private.session_ok()));

alter policy reports_objects_select on storage.objects
  using (bucket_id = 'reports'
         and (storage.foldername(name))[1] = (select auth.uid())::text
         and (select private.session_ok()));

alter policy reports_objects_delete on storage.objects
  using (bucket_id = 'reports'
         and (storage.foldername(name))[1] = (select auth.uid())::text
         and (select private.session_ok()));
