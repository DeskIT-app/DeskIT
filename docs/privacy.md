---
title: DeskIT privacy policy
policy_version: "2026-09-17-draft"
---

# DeskIT privacy policy

**DRAFT — English canonical text.** The Hebrew column (first, for the
Israeli reader) is written by the owner (plan chapter 16); the one-hour
lawyer review of D25 looks at this page, the terms and the tier
reasoning of chapter 13.8 in one sitting. Angle-bracket fields are the
owner's to fill. Every sentence here must stay checkable against
`NETWORK.md`, the code, or the account service's schema — no promise
that the code does not keep.

Version `<policy_version>` · `<date>`. Changes are announced in the
release notes; the consent cards inside the app carry a `text_version`
and ask again when the section they quote changes.

## 1. Who

The controller is **Yoav Shimron**, a private individual in Israel.
There is no company and no data protection officer (chapter 13.8:
none is required at this scale). Contact: **shimronyoav@gmail.com** — the
same address as in `TRADEMARK.md` and `SECURITY.md`.

## 2. Local by default

Everything personal lives on your PC, in `%LOCALAPPDATA%\DeskIT`:

- `audio\recent`, `audio\pending`, `corpus\` — recordings the app kept
  (a ring of the last `vocab.keep_audio = 20`; the second reading keeps
  `[review] keep_audio = 3`);
- `logs\transcripts.log` — what you dictated, kept
  `[history] keep_days = 30` days;
- `vocab.json`, `review.json` — the words it learned and the proposals
  it made;
- `problems.json` and its attachments — reports you wrote;
- `lookup_cache.json`, `logs\`, `models\`, `packs\`, `secrets\`;
- pictures and clips go to your Pictures and Videos folders.

Nothing leaves the PC until you switch a cloud feature on through its
consent card. To delete: Settings > Your data, per store, or "Delete
everything on this PC"; the uninstaller asks "Remove my data too?".

## 3. Cloud features with your own key

Off by default. Each kind has its own consent card and its own row in
`consent.json`:

| Kind | What is sent | To |
|---|---|---|
| cloud text | the dictated text, with the learned word pairs present in it | `api.groq.com` or `generativelanguage.googleapis.com` |
| cloud audio | the recording | the same |
| cloud screenshots | the region of the screen you picked | the same |

Always under your own account and key: you are the provider's customer
and DeskIT is your client software. The key is stored in Windows
Credential Manager and is sent to that one provider only.

Provider facts the cards quote verbatim: `<the Gemini unpaid-tier
sentences from D11 — "to provide, improve, and develop Google products
and services", "human reviewers may read, annotate, and process your API
input and output", "Do not submit sensitive, confidential, or personal
information to the Unpaid Services", the EEA/UK/CH restriction — and
Groq's retention statement, each with its source URL and the date it
was read>`.

Both providers require users to be 18 or over for these features.

## 4. The account

DeskIT works with an account: the first-run wizard asks you to sign in
with Google before the keys work, once — this PC remembers you until
you sign out. (An anonymous account, with no e-mail, exists for people
who only want to send problem reports; the app offers it on the
Account block.) Collected on sign-in: a user id; with Google, the e-mail address of the
Google account you chose (held by the sign-in service, never shown to
other users); the name of this PC as Windows reports it (or the name
you typed), the app version, the Windows build, the hardware tier;
timestamps; and the IP address as the processor sees it, in its logs
only (kept one day).

**Two syncs, each behind its own consent card, both off until you turn
them on.** "Settings and words": your changed settings — minus every
key, hotkey, device, folder, port and position, which never leave the
PC — and the words the app learned from your corrections. "What you
said": the text of what you dictated, translated, punctuated and looked
up, one row per event, so the Said page is the same on every PC you
sign into. Never audio, screenshots or clips. **Plain statement: the
rows of the "what you said" sync sit in the developer's database. Its
security rules separate users from each other; they do not stop the
project's administrator from reading a row.** If that is not acceptable,
leave that sync off — dictation and everything else work exactly the
same.

Problem reports you chose to send: the report text you typed, only the
attachments you ticked (a screenshot, a recording, the transcript, a
settings snapshot — each passed through the redactor and previewed
before Send).

Purpose: keeping your words and settings with you across PCs; reading
the reports you send. Voluntary: no law requires any of it; without an
account there are no reports and no sync, and dictation is unaffected.
Recipients: Supabase Inc. as processor (region Frankfurt, EU); Google
LLC for the sign-in itself; **Anthropic PBC when the owner processes
reports with AI tools under his own account**. Retention: reports and
attachments 12 months; synced words, settings and history for as long
as the account exists; idle anonymous accounts 12 months; the owner's
monthly backup 3 months. "Delete my account" in the app deletes
everything at once — rows, files and the account — and "Sign out"
revokes the session everywhere. Rights: access, rectification and
deletion through the app and by e-mail. The whole database schema is
published at `supabase/migrations/` in the repository; no table in it
has a column that could hold an API key.

## 5. The phone companion

Audio travels between your phone and your PC over your own network —
a pairing over a certificate the PC generates, optionally Tailscale —
never through any server of the owner. The phone token is stored under
DPAPI.

## 6. Screenshots, clips, camera

Local files only, in your Pictures and Videos folders. Nothing is
uploaded unless the cloud-screenshots consent is on or you tick an
attachment in a report.

## 7. The update check

Off until asked once. When on: one request a week to `api.github.com`
for the latest release's `latest.json`, with no identifier and no
telemetry.

## 8. Every connection, listed

The full host list is `NETWORK.md`, shipped beside the app. Every
outbound request is shown on the Network screen (Settings > Privacy >
EVERY CONNECTION) and mirrored to
`logs\network.log`. The Offline switch refuses every host but
`127.0.0.1`.

## 9. Security

Keys in Credential Manager; machine secrets under DPAPI; TLS to every
host; the log redactor removes what looks like a key or a token before
anything is attached to a report; `SECURITY.md` says how to report a
problem.

## 10. Age

18 or over for every cloud feature (the providers require it). Local
dictation has no age gate.

## 11. Changes and contact

This page carries a version and a date. Changes are announced in the
release notes; a consent card asks again when the section it quotes
changes. Contact: **shimronyoav@gmail.com**.
