# The DeskIT name and mark

The code of DeskIT is free software under the Apache License 2.0
(`LICENSE`). Section 6 of that licence withholds trademark rights; this
page says what that means here, in plain words, for someone who forks
the code or reviews a store listing.

## What is reserved

The name **DeskIT** — in any casing, and its Hebrew transliteration
(דסק-איט) — the dalet-as-desk mark and the application icon
(`icon.ico`, `icon.png`, made by `make_icon.py`) are marks of Yoav
Shimron. They are not covered by the Apache-2.0 licence.

## What you may do

- Fork, build, change and run the code under Apache-2.0.
- Say "based on DeskIT" or "a fork of DeskIT" in plain text.
- Keep the name and the icon in **unmodified** builds of a tagged
  release.
- Link to the project.

## What you may not do

- Publish a modified build, a store listing, a domain or an app-store
  account under the name DeskIT or with the icon.
- Imply that the owner endorses, supports or reviewed a fork.
- Use the name or the mark on merchandise.

## Renaming a fork

So that two products never share a person's data or a Windows identity,
a fork under another name changes all of these:

| Where | What |
|---|---|
| `VERSION` and the About card | the product name and its number |
| `paths.APP_ID` | the AppUserModelID `DeskIT.App` (`DeskIT.Dev` in a checkout) |
| `packaging/DeskIT.iss` | the Inno `AppId`, the names, the shortcut |
| `android/` | the Android package id |
| `icon.ico`, `icon.png`, `make_icon.py` | the icon |
| `paths.py` | the `%LOCALAPPDATA%\DeskIT` data folder name |

## No registration claimed

The mark is not registered in Israel or anywhere else. This page claims
common-law use only, and says so to stay honest.

## Contact

The same e-mail as the privacy policy (`docs/privacy.md`) and
`SECURITY.md`.
