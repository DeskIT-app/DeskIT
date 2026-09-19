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
  Windows in a third language is asked which of the two to use. Three pages: **Install**,
  **Downloads**, then **Finish** with "Start DeskIT now" ticked. The app itself is English
  chrome with Hebrew text.
- **Downloads**: what this PC still needs, each a ticked box with its size and its licence
  linked under it — the Hebrew speech model (1.62 GB, Apache-2.0); on a PC with an NVIDIA card
  and a driver from 545.84, NVIDIA's CUDA libraries (1.37 GB, NVIDIA's licence) and, with 6 GB
  of video memory, the English detector (1.62 GB, MIT); and screen recording (28 MB, PyAV with
  a GPL build of FFmpeg). Keeping a box ticked is your acceptance of its licence; untick
  anything and the first-run wizard offers it instead. The files come from the same addresses,
  checked against the same SHA-256s, that DeskIT itself uses — nothing is inside the
  installer — and a download that fails asks to retry or leaves the item to the wizard. It
  never fails the install. A silent install (winget, `/VERYSILENT`) and `/NODOWNLOAD` download
  nothing.
- Puts the program in `%LOCALAPPDATA%\Programs\DeskIT`, the downloads in
  `%LOCALAPPDATA%\DeskIT\models` and `\packs`, and a shortcut in the Start menu and on the
  desktop.
- Starts DeskIT at the end; the first run opens the wizard ([chapter 2](02-first-run)), whose
  computer page is skipped when the downloads all landed.
- Never bundles a speech model or NVIDIA's libraries: they are downloaded, with your tick,
  by the installer — or, if you unticked them, by the wizard on the first run.

## Updating

DeskIT looks for a newer version once a week (one request to github.com, no identifier; the
switch is under **Settings > Privacy**). When there is one, **Settings > The app** shows it with
a **Download and install** button; the download is checked against its SHA-256 before the
installer runs. winget users can also run `winget upgrade YoavShimron.DeskIT`.

## Uninstalling

**Settings > Apps** like any program. The uninstaller asks whether to remove your data too
(`%LOCALAPPDATA%\DeskIT`: the model, your learned words, history and recordings). Keep is the
default.
