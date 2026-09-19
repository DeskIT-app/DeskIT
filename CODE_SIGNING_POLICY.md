# Code signing policy

> **Status (2026-09-19):** application to SignPath Foundation submitted; releases up to and
> including 1.1.0 are unsigned, and Windows shows "Windows protected your PC" for them
> (More info → Run anyway; see the [FAQ](https://deskit-app.github.io/DeskIT/en/10-faq)).
> This page states the policy that applies from the first signed release.

DeskIT's Windows installer (`DeskIT-Setup-x.y.z.exe`, also published as `DeskIT-Setup.exe`)
is signed under SignPath Foundation's programme for open-source projects:
**Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).**

## What gets signed

Only artifacts built by this repository's own release workflow,
[`.github/workflows/release.yml`](.github/workflows/release.yml), from a tagged commit
(`vX.Y.Z`) on the `main` branch of [DeskIT-app/DeskIT](https://github.com/DeskIT-app/DeskIT).
The build runs entirely on GitHub Actions: every byte of the installed tree traces to the tag, a
hash-pinned wheel or a SHA-verified python.org archive; nothing is built or uploaded from a
developer's machine. The release page of each version carries the installer's SHA-256, its
VirusTotal scan and a GitHub build attestation, and `deskit --verify` recomputes the installed
tree's manifest on the user's PC.

## Roles

| Role | Who |
|---|---|
| Committers and reviewers | [DeskIT-app](https://github.com/DeskIT-app) — Yoav Shimron, the maintainer and the repository's only committer |
| Approvers | [DeskIT-app](https://github.com/DeskIT-app) — Yoav Shimron |

Every release is approved by hand in SignPath before it is signed; an unapproved build is not signed
and not published.

## Privacy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it. Each optional feature that would send
anything (cloud text services with the user's own key, the problem report, the account, the phone
keyboard, the weekly update check) is off until the user turns it on, and every connection the
program can make is listed in [NETWORK.md](NETWORK.md) and shown in the app's Network window.
The full policy: [privacy policy](https://deskit-app.github.io/DeskIT/privacy).

## Licence

DeskIT is free and open-source software under the [Apache License 2.0](LICENSE). The
uninstaller removes the program; the user's data folder is deleted or kept on their choice
(the guide, chapter 8).
