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
  **Finish** with "Start DeskIT now" ticked. The app itself is English
  chrome with Hebrew text.
- Downloads nothing itself: the big files DeskIT needs come down by themselves on the first
  start, in the background — the same on every copy, from here, winget or the Microsoft Store.
  What each one is, its exact size and its licence: [below](#downloads).
- Puts the program in `%LOCALAPPDATA%\Programs\DeskIT`, the downloads in
  `%LOCALAPPDATA%\DeskIT\models` and `\packs`, and a shortcut in the Start menu and on the
  desktop. The shortcut opens the desk, with DeskIT starting behind it (the dot, the model);
  when DeskIT is already running it only brings the desk up.
- Starts DeskIT at the end; the first run opens the wizard ([chapter 2](02-first-run)), which
  downloads whatever is still missing in the background.
- Never bundles a speech model or NVIDIA's libraries: DeskIT downloads them in the background
  from the first start.

## Downloads {#downloads}

What DeskIT downloads by itself on the first start, in full — the bar at the top of the
first-run wizard, **Downloading app parts**, opens this table. Every file is checked against
the SHA-256 DeskIT ships with; nothing is packed inside the installer.

| Part | What it is | Size | Licence |
|---|---|---|---|
| Hebrew speech | The Hebrew speech model, [ivrit-ai/whisper-large-v3-turbo-ct2](https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2) — without it there is no dictation | 1.62 GB | Apache-2.0 |
| English detection | A second, general model, [deepdml/faster-whisper-large-v3-turbo-ct2](https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2), that notices when you spoke English and transcribes it as English. Offered on an NVIDIA card with 6 GB of video memory | 1.62 GB | MIT |
| Faster with your NVIDIA card | NVIDIA's own CUDA libraries (cuBLAS, cuDNN, NVRTC) from PyPI. Offered on an NVIDIA card with 4 GB and a driver from 545.84; without them the card runs like a CPU | 1.37 GB | [NVIDIA CUDA EULA](https://docs.nvidia.com/cuda/eula/index.html), [cuDNN SLA](https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html) |
| Screen recording | PyAV with FFmpeg, for the record key, the photo key and the phone's audio | 28 MB | [PyAV (BSD-3)](https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt), [FFmpeg — this build is GPL: x264, x265](https://ffmpeg.org/legal.html) |

Anything already on the PC is not downloaded again. A download that fails is tried again by
itself; one that keeps failing is left for the next start. The files land in
`%LOCALAPPDATA%\DeskIT\models` and `\packs`. A part you removed by hand (Settings > Dictation,
Settings > Screen) is not downloaded again.

## Updating

DeskIT looks for a newer version once a week (one request to github.com, no identifier; the
switch is under **Settings > Privacy**). When there is one, **Settings > General** shows it with
a **Download and install** button; the download is checked against its SHA-256 before the
installer runs. winget users can also run `winget upgrade YoavShimron.DeskIT`.

## Uninstalling

**Settings > Apps** like any program. The uninstaller asks whether to remove your data too
(`%LOCALAPPDATA%\DeskIT`: the model, your learned words, history and recordings — and the
key you pasted, from Windows Credential Manager). Keep is the default; Delete leaves nothing of
DeskIT on the PC.
