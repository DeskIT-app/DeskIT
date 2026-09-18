---
title: 9. Reporting a problem
---

[עברית](../he/09-reporting) · English

# 9. Reporting a problem

**The two-sentence version.** Tap **Ctrl+Alt+R**, write one line, press Enter: the report is
kept on this PC with the screen, the last dictation and your settings attached. Turn on
**Send to the developer** and you see, before anything goes, exactly what would leave —
each file with its size and the one row the server gets — and only your press on **Send**
sends it.

## The report key

Wherever you are, **Ctrl+Alt+R** opens a small box over the window: **What is wrong?**, one
line in Hebrew (Shift+Enter for a new line), and five kinds — wrong / broken / slow / idea /
other. The box attaches, for you: a screenshot of the monitor under the mouse, the last
dictation's text and recording, and a snapshot of your settings (keys never; the snapshot
goes through the same redactor as the log). Enter keeps it; Esc cancels.

![The report box](../img/09-report-card.png)

The dashboard's **Problems** place lists your reports, opens each one's folder
(`%LOCALAPPDATA%\DeskIT\problems\<id>\`), and has the same box for a report written at the
desk.

Nothing leaves this PC unless you turn on **Send to the developer** on the box. The first
time, the consent card beside the dot asks (Settings > Privacy withdraws it later). With the
switch on, a strip under it lists what would travel, each piece with its size and its own
switch: **Screenshot** (off unless you turn it on — a picture of the screen may hold someone
else's words), **Recording** (off), **Transcript text** (on for a "wrong"), **Settings
snapshot** (on: model names and switches, never a key). The button then reads **Preview**
instead of **Keep on this PC**: the report is filed here as always, and a window opens with
the files and the exact row — "This is everything that leaves your PC. Nothing else." —
and two buttons, **Send** and **Keep on this PC**. Closing the window is keeping.

From the hotkey box the same Preview opens on the desk's **Problems** place; a report you
did not answer there keeps a **Preview & send** button on its row. A sent report's row says
"waiting to send" until it went (the app sends when it is online; **Send now** hurries it),
then "sent to the developer"; one the server refused says why. Every copy is idempotent:
sending the same report twice cannot make two.

## Telling us

**GitHub Issues** — [the bug template](https://github.com/DeskIT-app/DeskIT/issues/new/choose)
asks what you did, what happened, what you expected, how you installed, and the diagnostics
block. Get the block with **Settings > The app > Copy diagnostics**, or from the install
folder:

```
python\python.exe app\main.py --diagnose
```

It contains the version, the tier, the Windows build, the model's and packs' standing, the
port, and the last 50 lines of `app.log` through the redactor — no transcripts and no keys.
The block starts with a line saying what it contains; read it before you paste it.

**Windows Defender or SmartScreen flagged the installer?** There is a second template for
that (detection name, file name, the VirusTotal link on the release page), and Microsoft's
own false-positive form is linked from the release page.

**A security problem** — something that lets a key, a transcript or a recording leave the PC
without your consent — goes by e-mail, not a public issue: `SECURITY.md` beside the program
has the address and a 90-day disclosure window.

## What the developer sees

What the Preview showed and nothing else: the row (kind, place, your line, version, Windows
build, tier, the settings snapshot if you left it on, the transcript if you left it on) and
the files you ticked, under your account (anonymous or Google — no e-mail is ever in the
report). **Delete my account** on the Home account card removes every report and file on
the developer's side.
