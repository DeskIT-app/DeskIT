-- DeskIT — a phone is a device of the account (2026-11-06).
--
-- The owner, on the day he took the phone off Tailscale: everything
-- around the account, not around the device. A phone signs in with
-- Google and joins the account lock through `pairings` and Home's
-- Approve, the way a second PC does (0004 said it would), and from then
-- on the account holds what the devices need of each other, sealed under
-- the account key, which this project cannot open. PHONE_LINK_PLAN.md
-- chapters 4.2 and 12 are the whole of it. This file is its server side:
--
--   devices.link        sealed: this device's certificate (its SHA-256 on
--                       a PC, the DER on a phone), its private addresses,
--                       its port, the protocol it speaks, and one flag
--                       about its sync or its backup. Under is_sealed(),
--                       so opaque here, and the seal's associated data is
--                       `device/<uid>/<device id>`. Each device writes only
--                       its own: that is the app's rule, since the server
--                       knows only the account. A row that does not open
--                       under the account key is ignored by every device,
--                       so this project cannot add one.
--   devices.session_id  the id of the session this device runs on, the
--                       `session_id` claim of its own access token, kept
--                       beside the row so that Forget can end it. It is in
--                       the clear because the server must read it, and it
--                       is the client's word, which is why the function
--                       below looks at the session's owner and not at the
--                       column alone.
--   forget_device()     Forget: the row goes and the session it names, the
--                       one thing no device can do for itself on another
--                       device's behalf through the Data API. 0006 makes
--                       the end of a session effective at the next request.
--                       It answers whether any session of that row is left,
--                       because a copy that never wrote `session_id` loses
--                       its row and stays signed in, and the person has to
--                       be told.
--
-- `platform` stays what it was and gains values: `windows-…` as today,
-- `android-<sdk>` on a phone, later `web`.
--
-- The bound 0005 records does not apply here: both columns are checked by
-- is_sealed() or by their type, and no regex in this file has a bound.
--
-- Forget's list of who was forgotten is one more `vault` row, name
-- `forgotten`, sealed like the rest: 0004's table takes it as it stands,
-- and the sync that reads that table skips a name it does not know. So
-- this file adds no table, and D12 lock 3 reads as it did since 0004.
--
-- `delete_me()` needs no change: it already sweeps `devices`, and with the
-- account gone every session goes with `auth.users`.
--
-- A client older than this file is untouched: the columns are nullable and
-- it names neither. A client of this version needs this file first, or its
-- device row is refused, so this file is applied before the app that
-- writes the columns runs against the project.

alter table public.devices
  add column link text check (link is null or public.is_sealed(link));

alter table public.devices
  add column session_id uuid;

-- `security definer` because only the definer may touch auth.sessions, and
-- an empty search_path, as in 0006, so nothing resolves by accident. The
-- two `uid` comparisons are the function's whole authority: a row of
-- another account is not deleted, and a session of another person, named
-- in a column the caller wrote himself, is not ended. A target that is not
-- there is no error, so a second press changes nothing. Deleting the
-- session takes its refresh tokens with it (their foreign key cascades).
-- A device may name itself: Sign out on a phone is Forget on itself.
-- It answers true when no session of that row is left to end: this call
-- ended it, or it was over already, because a PC that signed out keeps its
-- row and a `session_id` that names nothing any more. False is a target
-- that is not there, a row that named no session (a client older than this
-- file, or one whose account gate was shut when it wrote its row), or a row
-- that named somebody else's, which stays exactly as it was. The row goes
-- all the same, and that device stays signed in until its sessions end some
-- other way, which is what the client then tells the person.
create or replace function public.forget_device(target uuid)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
  sid uuid;
  ended boolean := false;
begin
  if uid is null then
    raise exception 'forget_device: no session';
  end if;
  delete from public.devices d
   where d.id = target
     and d.user_id = uid
  returning d.session_id into sid;
  if sid is not null then
    delete from auth.sessions s
     where s.id = sid
       and s.user_id = uid;
    ended := found or not exists (select 1 from auth.sessions s where s.id = sid);
  end if;
  return ended;
end
$$;

revoke all on function public.forget_device(uuid) from public;
revoke all on function public.forget_device(uuid) from anon;
grant execute on function public.forget_device(uuid) to authenticated;

-- ----------------------------------------------------------------- footer
-- The columns this file adds, and what the server can read of them:
--
--   devices  + link        nothing: a version tag and standard base64
--            + session_id  a uuid, which opens nothing without the session
--                          it names; this project already holds that id in
--                          auth.sessions
