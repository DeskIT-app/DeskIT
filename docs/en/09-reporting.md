---
title: 9. Reporting a problem
---

[עברית](../he/09-reporting) · English

# 9. Reporting a problem

**The two-sentence version.** Tap **Ctrl+Alt+R**, write one line, press Enter: the report is
kept on this PC with the screen, the last dictation and your settings attached. Sending
reports to the developer is a later version; today a report reaches us through a GitHub
issue, with a diagnostics block that you can read before pasting.

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

Nothing leaves this PC. The **Send to the developer** checkbox with a preview of the exact
data is a later version; until then the folder is yours to attach to an issue if you want to.

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

Today: only what you paste into an issue. When the in-app sending arrives it will be behind a
consent card, with a preview of the exact JSON and each attachment, an anonymous account (no
e-mail), and a **Delete my account** button that removes everything on the developer's side.
