---
title: 2. First run
---

[עברית](../he/02-first-run) · English

# 2. First run

**The tour.** When the wizard closes, a small card appears beside the dot in the corner
of the screen, with a beak pointing at it. Four cards, one sentence each: the dot and its
colours, the key (drawn, with the binding you chose), what a click on the dot opens, and
done. **הבא** (next) moves on, **דלג** (skip) closes it — and a skipped tour does not come
back by itself. To see it again: Settings > About > **Show the tour**. This page is the
long version of those four cards.

**The two-sentence version.** The first start opens a seven-page wizard; only three pages ask
you anything (which microphone, whether to download now, and the optional extras) and every
other page is **Next**. It runs once; `main.py --setup` from the install folder runs it again.
Since the installer downloads the model and the packs itself ([chapter 1](01-install)), the
"This computer" page is usually skipped — it appears only for what you unticked there or
what did not finish.

![Welcome](../img/02-welcome.png)

## Welcome

Three sentences about where your voice goes — it stays on this computer, the words are kept in
one folder you can delete, nothing is sent anywhere until you switch it on — and a link,
**How to check this yourself**, to [chapter 4](04-privacy). **Next**.

![Your account](../img/02-account.png)

## Your account

Two cards, one question each. There is no way past this page without an account.

**New to DeskIT?** — **Create an account**. A field for your name (what DeskIT calls you —
the account needs one, so **Continue with Google** wakes once you have typed it), what the
account is for (your learned words and settings follow you to any PC you sign in on), what is
stored (the id and e-mail of the Google account you pick, the name you type) and what never is
(your voice, what you said, your keys). **Continue with Google** opens the browser once; this
PC remembers you until you sign out, and the rest of the setup follows.

**Used DeskIT before?** — **I have an account**. **Sign in with Google** with the account you
used on the other PC, and that is all: your learned words, settings and what you said come
down and DeskIT opens by itself — no microphone, sentence, keys or extras pages, only the downloads page if
this PC still lacks something. The microphone and the keys are the usual ones until you
change them in Settings. What you said and your cloud keys are locked with a key only your
own PCs hold, so one more step: the page shows an eight-character code and waits; open the desk
on your other PC — Home there shows the same code — and press **Approve**. Everything
locked then arrives here too. No other PC at hand? Type the recovery key DeskIT made for you
(Settings > Account > The lock, on any PC that is in). Or **Later**: DeskIT works meanwhile
with your words and settings, and the desk's Account card keeps the code.

Picked the wrong card? A link under each one leads to the other, and **Back** goes back to
the two cards, not to Welcome. Signed in as the wrong person? **Not you? Sign out** under the
signed-in card (or **Back**) signs this PC out — your other PCs stay signed in — and shows the
two cards again. Created an account with a Google account that already holds DeskIT settings?
The page says *Welcome back* and the button says **Open DeskIT**. Signed in with one that holds
nothing yet? It says so, and **Continue** runs the ordinary setup.

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

This page exists only while something is left to download — after an install whose
Downloads page you left as it was, it is not shown at all, and the counter says "of 6".

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
- **Screen recording and the camera**: 28 MB from PyPI — PyAV with FFmpeg, for the record
  key, the photo key and the phone's audio. On by default, so nothing has to be installed
  later; the two licences are linked on the card.

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
| Fix misheard words with a free cloud model (text only) | Off. Turning it on is the consent ([chapter 5](05-cloud) says what leaves and to whom) and opens a field under the row for your own free Groq key, checked with Groq the moment you save it. Next waits until a key works — or the switch is off again. |
| Keep this PC awake while DeskIT runs | On. Windows does not sleep while DeskIT runs; Settings > General turns it off. |
| Check for updates weekly | On. One request to github.com, no identifier. |
| Connect Claude Code | Off. Two hook lines in `~/.claude/settings.json`: when Claude Code finishes or asks, DeskIT shows a card and plays a cue. One copy of DeskIT at a time: if another copy on this PC is connected, the row says so and turning it on asks first — answer *Yes, connect this one* and the other is disconnected. |
| Take over Win+Shift+S for DeskIT's screenshot key | On. Windows' own Snipping Tool stops answering that shortcut while DeskIT runs; off, the key is Ctrl+F11. |

## Ready

![Ready](../img/02-done.png)

The hotkey to hold, and three switches asked once:

- **Keep my words, settings and what I said in my account** — on. The words DeskIT
  learned from you, the settings you changed, the text of what you said and your cloud keys
  follow you to any PC you sign in on, so it hears you your way from the first sentence and
  the Said page is the same page there. What you said and the keys leave locked with a key
  only your own PCs hold; the server cannot read them. Never your voice. To turn it off later:
  Settings > Account > **Withdraw** on *Syncing settings and words* and on *Syncing what
  you said* — each has its own row, so the history can go off alone; **Turn on** on the
  same row asks again. The row appears only when you signed in on the account page.
- **Start with Windows** — off. A Run entry for your user; that start opens no window, only
  the dot.
- **Dictate from your phone** — off ([chapter 6](06-phone)).

**Start** starts DeskIT and opens the desk. If you skipped the model, this page says so and
Home has the download button.
