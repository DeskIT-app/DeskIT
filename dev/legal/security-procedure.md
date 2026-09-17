# Basic security procedure

- One Supabase console account, 2FA on, opened only from `<the laptop>`,
  which runs full-disk encryption.
- The publishable key is the only key inside the app; the service-role
  key lives in the owner's password manager and never in the repo, a
  file or a chat.
- Row-level security is the access control on every table (chapter 8).
- Backups: `<where, how often>` (chapter 8).
- `dev/inbox.py` reads only consented columns (chapter 7).
- Incidents go to `incident-log.md` the day they are noticed.
