---
title: 6. The phone keyboard
---

[עברית](../he/06-phone) · English

# 6. The phone keyboard

**The two-sentence version.** The DeskIT keyboard for Android records on the phone and sends
the recording to *your* PC: at home straight over your Wi-Fi, and away from home through your
own account, locked so that only your own devices can read it. Your PC transcribes it with the
same Hebrew model and the same learned words, and the text lands in the field on the phone.

## What you need

- DeskIT running on the PC and signed in, with **Dictate from the phone** on. It is on unless
  you turned it off: **Settings > Phone**.
- An Android phone, signed in to the same account as the PC. The phone signs in with Google,
  so an account made without Google needs a Google sign-in on the PC first; **Settings > Phone**
  says so and has the button. Everything in the account stays.
- The DeskIT keyboard app. **Settings > Phone** on the PC shows where to get it: point the
  phone's camera at the code on its card.

There is nothing to type: no address, no token, no port.

## Setting it up

1. Install the keyboard app and open it.
2. Sign in with Google, with the account your PC uses.
3. The phone asks to join your account, the way a second PC does, and both screens show the
   same code. On the PC the request is on **Home**: press **Approve** only if you are adding
   this phone yourself right now and the code matches. On the phone, press **Same code**.
   Neither side opens anything until both have pressed.
4. Allow the microphone, and turn the DeskIT keyboard on in Android's keyboard settings.
5. In any app: switch to the DeskIT keyboard, hold the microphone key, speak, release.

## At home

On Wi-Fi, the keyboard finds every PC of your account by itself, from what each PC leaves
sealed in your account, and tries all of their addresses at once; the first to answer takes the
dictation. Only a PC your account lists can answer, and only a phone your account lists gets
in: each side checks the other's certificate before a word is sent, over TLS. Once the phone
has read your devices, it needs no internet for this.

## Away from home

When the phone cannot reach your PC on the network it is on (you are out, on mobile data, or on
someone else's Wi-Fi), the keyboard reaches it **through your account** instead: the recording
goes up in pieces on your account's own private channel, each piece locked with your account's
key, and the PC's text comes back the same way. It is your PC's model and your learned words,
as at home. Nothing to set up and nothing to press.

- **You always know.** The keyboard's line says *via your account* when the text came this way:
  *3.7 s · local via your account*.
- **Who can read it.** Only devices of your account: the account's server sees that pieces of
  some size passed, never what is in them. A phone you removed with **Forget** is refused by your
  PCs.
- **The PC must be on**, with DeskIT running and **Dictate from the phone** on. **Settings >
  Phone** on the PC has **Also from outside home**, on by default; off, that PC does not answer
  away from home.
- **When no PC answers** this way either, the keyboard goes on to your cloud key, below, or the
  recording waits on the phone for **Send again**.

## When your PC can't be reached

The keyboard has a backup: when no PC of your account answers within about a second, at home or
through your account, it sends
that recording to **Groq** (or **Gemini**, if that is the only key you have) with **your own
key**, and the text lands in the field as usual. It is on unless you turn it off. The phone
shows it once, with the switch already on; you can turn it off there, or later in the phone's
Settings, under **When your PC can't be reached**.

- **The key.** The same key your PC uses: it lives in your account, locked with your account's
  key. Add, change or remove it in the phone's Settings, under **Your cloud keys**, or on the PC
  — a change on one reaches the other by itself. The phone opens it for one request and keeps
  nothing readable.
- **You always know.** The keyboard's line says *Transcribing in the cloud…* while it works and
  *from the cloud (Groq)* when the text is in. **What you said** on the phone marks it too.
- **The price.** The provider hears that recording, and its words are less accurate than your
  PC's, with none of the words DeskIT learned. That is why it is a backup and never the first
  road.
- **Afterwards.** The recording is deleted from the phone. Only the text goes on to your PCs,
  locked, and appears on their **Said** page marked *From the cloud* — only if your account
  keeps what you said.
- **No key yet?** Away from home, a recording that could not be sent waits, and the button
  beside it reads **Add a key** instead of **Send again** until there is a way to send it.

## When nothing gets through

- **It waits.** A dictation that reached no PC and no cloud waits on the keyboard, for an hour
  at most. Its line says why in a few words — that your phone isn't on Wi-Fi, when that is the
  reason. **Send again** sends what waits, oldest first; the **X** deletes it. Nothing is sent
  behind your back.
- **A recording is never lost when the keyboard closes.** If it closes in the middle of one —
  the screen goes dark, another app takes over — the microphone stops and the recording is kept.
  The next time the keyboard opens, the microphone key says **Continue** with how long you had
  talked: go on where you stopped, send it, or delete it with the **X**. The screen stays on
  while you record.

## What leaves the phone, and where

- The recording goes to your PC. At home it goes straight to it, over TLS. Away from home it
  goes through your account, locked with your account's own key: the account's server carries
  sealed bytes it cannot open. Only the cloud backup above, when no PC answers, sends a recording
  to a provider, with your own key. Nothing goes to the developer.
- The PC does the transcription; the phone shows the result. What you taught DeskIT at the
  desk (learned words, the repair pass if you turned it on) applies to the phone's text too —
  under the same consent switches as at the desk. If the cloud repair is on at the desk, the
  phone's text goes through it as well.
- The keyboard refuses password fields and other private fields.
- **Settings > Account** on the PC lists your phones beside your PCs. **Forget** takes one off
  the list and ends its session at once, and your PCs refuse it from then on. Signing out on
  the phone takes everything of yours off it: the key, the words and the recordings.

## Trouble

- **The phone can't connect at home.** Windows may be blocking it. **Settings > Phone** has
  *The phone can't connect?* with **Let it through**: DeskIT asks Windows to let your phone in,
  and Windows asks you for a yes. Its details show this PC's addresses and port.
- **Is the PC listening?** DeskIT must be running on the PC with **Dictate from the phone** on,
  and your account turned on there. With the account off on that PC, the phone cannot come in;
  turn it on from **Home** or **Settings > Privacy**.
- **Another program holds the port.** DeskIT takes the next free one and tells your phone
  through your account. There is nothing to change on the phone.
- **The phone was removed.** A phone taken off with **Forget** says so, and approving it again
  on the PC brings it back.
