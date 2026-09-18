-- DeskIT — delete_me() without the storage delete.
--
-- Measured live on 2026-09-18, the first "Delete my account" against the
-- project: the RPC of 0001 answered
--   403: Direct deletion from storage tables is not allowed. Use the
--        Storage API instead.
-- Supabase guards storage.objects against SQL deletes (the files behind
-- the rows would be orphaned). Chapter 8's open point 4 foresaw this and
-- named the answer: the client removes its own folder through the
-- Storage API first — it holds the delete policy of 0001 — and the RPC
-- removes the rows and the auth user. sb.delete_account() already did
-- the purge before calling the RPC; only the function changes.
--
-- Applied once by hand in the SQL editor after 0001, 2026-09-18.

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
  -- through the Storage API before this call; a folder left behind by
  -- a client that lost its network mid-way is swept by the owner's
  -- retention script (8.9)
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
