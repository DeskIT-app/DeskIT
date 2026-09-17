# Reporting a security issue

DeskIT is a dictation app whose whole promise is that what you say
stays on your PC unless you switch a cloud feature on yourself. A
security issue is anything that breaks that promise.

## What to report

- Anything that lets a key, a transcript, a recording or a screenshot
  leave the PC without a consent row in `consent.json` — or to a host
  that is not in `NETWORK.md`.
- Anything that breaks one of the five locks described in the plan's
  chapter on keys: a key value on disk outside Windows Credential
  Manager or DPAPI, a key in a log, a key in a URL, a key sent to the
  wrong provider, a request that bypasses `net.py`.
- Anything that lets another program or user on the same PC read the
  app's data folder through the app, or drive its keys.
- A dependency with a known vulnerability in `requirements.lock`.

Ordinary bugs go to the issue tracker or the in-app "Report a problem".

## How to report

E-mail **<contact e-mail — the same as in the privacy policy>** with
the steps to reproduce, the version (Settings > The app) and, if you
have it, the `--diagnose` block (`deskit --diagnose`; it contains no
transcripts and no keys, and you can read it before sending).

Please do not open a public issue for a security problem before it is
fixed.

## What happens next

- An acknowledgement within 7 days.
- A fix, or a reason there will be none, within **90 days** of the
  report (coordinated disclosure). After 90 days you may publish.
- Credit in the release notes if you want it.

There is no bug bounty.

## Supported versions

The latest release only. Older releases are not patched; the weekly
update check (Settings > Privacy) is how a fix reaches you.

## Where to check for yourself

- `NETWORK.md` — every host the app may talk to, and why.
- Dashboard > Network — every request this copy made, host, purpose,
  bytes, status; mirrored in `logs\network.log`.
- The Offline switch (Settings > Privacy) refuses every host but
  `127.0.0.1`.
