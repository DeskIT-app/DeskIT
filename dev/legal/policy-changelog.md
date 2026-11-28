# Policy and consent-text changelog

One line per `policy_version` (docs/privacy.md) and per consent card
`text_version` change, so the re-ask logic of D7 has a written trail.

| Date | What | Old version | New version | What changed |
|---|---|---|---|---|
| 2026-09-17 | privacy policy | — | 2026-09-17-draft | first draft |
| 2026-09-17 | account terms | — | 2026-09-17-draft | first draft |
| 2026-11-06 | account consent card | deskit-terms-0+en-2026-09-23 | deskit-terms-0+en-2026-11-06 | names the id of a device's session and the one connection a signed-in copy keeps, syncs on or off; both are new under this gate, so it asks again and is not carried forward |
| 2026-11-07 | history sync consent card | deskit-terms-0+en-2026-09-21 | deskit-terms-0+en-2026-11-07 | "only your own PCs hold" the key becomes "your own devices", because a phone the person approves holds it too; that is more holders than the old words named, so it asks again, on one row with the account card, and is not carried forward |
