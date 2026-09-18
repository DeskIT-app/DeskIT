---
title: 1. Install
---

[עברית](../he/01-install) · English

# 1. Install

**The two-sentence version.** DeskIT installs for your user only, asks for no administrator
password, and lands in `%LOCALAPPDATA%\Programs\DeskIT`. Windows may warn you once because the
installer is not signed with a paid certificate; the code is open and every build is attested.

## Three ways in, in the order to try them

1. **The Microsoft Store** — coming in a later version. It is the door with no warning at all.
2. **winget**, if you have it (Windows 11 has it built in). Open a terminal and run:

   ```
   winget install YoavShimron.DeskIT
   ```

   winget downloads the same installer and skips the SmartScreen download dialog.
3. **GitHub Releases.** Download `DeskIT-Setup-x.y.z.exe` from the
   [latest release](https://github.com/DeskIT-app/DeskIT/releases/latest). Beside it on the
   release page: the file's SHA-256, a VirusTotal link and the build attestation.

## "Windows protected your PC"

When you start the installer from the GitHub route, Windows SmartScreen shows a blue box that
says **Windows protected your PC**. Press **More info**, then **Run anyway**.

Why: the installer is not signed with a paid code-signing certificate. Signing costs money and
identity paperwork that a free, open-source program by one person does not have yet. What you
have instead: the source code, a build made on GitHub's own machines from the tagged source
(the attestation on the release page proves that), the SHA-256 of the file, and a VirusTotal
scan of every release. Comparable open-source dictation apps get the same warning on every new
release, even signed ones.

**Smart App Control.** On a PC where Smart App Control is on, Windows blocks the GitHub
installer outright rather than warning. Smart App Control allows only signed or Store apps; the
Store build (later) is the way, or Windows lets you turn Smart App Control off once.

## What the installer does

- Installs for your user only: no UAC prompt, no administrator password.
- Speaks Hebrew or English by your Windows display language, with no question; only a
  Windows in a third language is asked which of the two to use. Two pages: **Install**, then
  **Finish** with "Start DeskIT now" ticked. The app itself is English chrome with Hebrew text.
- Puts the program in `%LOCALAPPDATA%\Programs\DeskIT` and a shortcut in the Start menu.
- Starts DeskIT at the end; the first run opens the wizard ([chapter 2](02-first-run)).
- Never installs a speech model: that is 1.62 GB, downloaded on the first run with your
  consent, into `%LOCALAPPDATA%\DeskIT\models`.

## Updating

DeskIT looks for a newer version once a week (one request to github.com, no identifier; the
switch is under **Settings > Privacy**). When there is one, **Settings > The app** shows it with
a **Download and install** button; the download is checked against its SHA-256 before the
installer runs. winget users can also run `winget upgrade YoavShimron.DeskIT`.

## Uninstalling

**Settings > Apps** like any program. The uninstaller asks whether to remove your data too
(`%LOCALAPPDATA%\DeskIT`: the model, your learned words, history and recordings). Keep is the
default.
