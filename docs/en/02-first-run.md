---
title: 2. First run
---

[עברית](../he/02-first-run) · English

# 2. First run

**The tour.** When the wizard closes, a small card appears beside the dot in the corner
of the screen, with a beak pointing at it. Four cards, one sentence each: the dot and its
colours, the key (drawn, with the binding you chose), what a click on the dot opens, and
done. **הבא** (next) moves on, **דלג** (skip) closes it — and a skipped tour does not come
back by itself. To see it again: Settings > The app > **Show the tour**. This page is the
long version of those four cards.

**The two-sentence version.** The first start opens a seven-page wizard; only three pages ask
you anything (which microphone, whether to download now, and the optional extras) and every
other page is **Next**. It runs once; `main.py --setup` from the install folder runs it again.

![Welcome](../img/02-welcome.png)

## Welcome

Three sentences about where your voice goes — it stays on this computer, the words are kept in
one folder you can delete, nothing is sent anywhere until you switch it on — and a link,
**How to check this yourself**, to [chapter 4](04-privacy). **Next**.

## Microphone

![Microphone](../img/02-microphone.png)

Every input device Windows knows, the one Windows calls the default already selected, and a
bar under the list. **Speak. The bar should move.** If it moves, everything downstream is a
detail.

If it does not move, the reason is almost always Windows' own microphone privacy switch, not a
fault: Windows lets desktop apps be blocked from the microphone and then hands them perfect
silence, without an error. The wizard reads that switch before the bar is even drawn and, when
it is off, says so and offers **Open the Windows setting** (Settings > Privacy & security >
Microphone > *Let desktop apps access your microphone*). Turn it on, come back, speak again.

Pick another row if you have more than one microphone. **Next** saves the choice.

## This computer

![This computer](../img/02-computer.png)

The top line is what DeskIT found: an NVIDIA card and its memory ("fast transcription"), a
small NVIDIA card ("fast, smaller mode"), or no NVIDIA card ("transcription will take about
as long as you spoke"). Under it, what this PC still needs, each asked before a byte moves:

- **The Hebrew model** — 1.62 GB from huggingface.co into `%LOCALAPPDATA%\DeskIT\models`.
  Press **Download**; the bar shows bytes, percent and speed, **Pause** keeps what came so far
  and the next start continues from there. You can press **Next** while it downloads, or skip
  it and download from **Home** another day — DeskIT starts without it, and a dictation then
  says the model is missing and keeps the recording.
- **Use the NVIDIA card** (only on a PC with one): 1.37 GB of NVIDIA's CUDA libraries from
  PyPI, under NVIDIA's licence (linked). Without them an NVIDIA card runs like a CPU.
- **Detect English automatically** (only on a larger NVIDIA card): a second, general model
  that notices when you spoke English and transcribes it as English. 1.60 GB more on disk and
  in video memory.

The switches queue behind the model: one **Download**, one bar, "1 of 3 · Hebrew model".
This happens only once.

## Say one sentence

![Say one sentence](../img/02-say.png)

**Record 3 seconds**, speak, and read what came back — through the real backend, the same one
every later dictation uses. The line under it says how long the transcription took; on a PC
without an NVIDIA card that number is the speed to expect. The button waits while the model is
still downloading; **Skip** goes on without it.

## Keys

![Keys](../img/02-keys.png)

The keyboard keys DeskIT listens to — hold, latch, punctuate, ask the screen — as they are
now. These are hotkeys, not API keys; the cloud keys come in [chapter 5](05-cloud). Change
them later on the dashboard's **Keys** place.

## Optional extras

![Optional extras](../img/02-extras.png)

Five switches, each one thing that leaves this PC or changes Windows. They are drawn as they
stand and written only if you move them:

| switch | what it does |
|---|---|
| Fix misheard words with a free cloud model (text only) | Off. Turning it on opens the consent card first ([chapter 5](05-cloud)); needs your own free Groq key. |
| Keep this PC awake while DeskIT runs | On. Windows does not sleep while DeskIT runs; Settings > The app turns it off. |
| Check for updates weekly | On. One request to github.com, no identifier. |
| Connect Claude Code | Off. Two hook lines in `~/.claude/settings.json`: when Claude Code finishes or asks, DeskIT shows a card and plays a cue. |
| Take over Win+Shift+S for DeskIT's screenshot key | On. Windows' own Snipping Tool stops answering that shortcut while DeskIT runs; off, the key is Ctrl+F11. |

## Ready

![Ready](../img/02-done.png)

The hotkey to hold, and two more switches asked once: **Start with Windows** (a Run entry for
your user) and **Dictate from your phone** ([chapter 6](06-phone)). **Open the desk** opens
the dashboard; **Finish** just finishes. If you skipped the model, this page says so and Home
has the download button.
