-- DeskIT — the live channel (2026-09-20).
--
-- The owner, with two copies of one account open side by side: "I sync,
-- and not two seconds pass and it is already on the other app." Every
-- push the app makes now ends with one broadcast on the account's own
-- Realtime topic, `user:<uid>`, carrying the NAMES of the stores that
-- changed (settings, vocab, history) and the id of the device that
-- changed them — never a word of what was said — and every signed-in
-- copy holds one websocket on that topic (net.websocket, one row on the
-- Network screen while it is open) and pulls the named store the moment
-- a broadcast from another device lands. Measured from the owner's PC
-- on the day: broadcast to arrival 0.15 to 0.30 s.
--
-- Realtime's private channels are authorised by row-level security on
-- `realtime.messages`, the same way every table of 0001 is: a person may
-- join and receive (select) and send (insert — the REST broadcast) on the
-- one topic that carries their own id, on the broadcast extension only.
-- No presence, no postgres_changes: no table is published to Realtime,
-- so nothing anyone said ever travels through it — only the nudge to go
-- and pull. Without these policies the join answers "Unauthorized" and
-- the app falls back to its 15-minute pass; nothing else changes.
--
-- Applied once by hand in the SQL editor after 0002, 2026-09-20.

create policy live_topic_read on realtime.messages
  for select to authenticated
  using (realtime.topic() = 'user:' || (select auth.uid())::text
         and extension = 'broadcast');

create policy live_topic_write on realtime.messages
  for insert to authenticated
  with check (realtime.topic() = 'user:' || (select auth.uid())::text
              and extension = 'broadcast');
