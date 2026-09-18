---
title: 10. FAQ
---

[עברית](../he/10-faq) · English

# 10. FAQ

**Windows says "protected your PC", or Defender flags the installer.**
Expected for a program not signed with a paid certificate: press **More info → Run anyway**.
Compare the SHA-256 on the release page with the file (right-click > Properties, or
`certutil -hashfile DeskIT-Setup-x.y.z.exe SHA256` in a terminal), check the VirusTotal link
on the release, and read the build attestation. If Defender quarantines the installer, restore
it from Windows Security > Protection history, then report the false positive on Microsoft's
submission form (linked from the release page) and to us with the false-positive template.
Comparable open-source dictation apps, signed ones included, get re-flagged on new releases.

**Smart App Control blocks it.**
Smart App Control allows only signed or Store apps. Use the Store build when it exists, or
turn Smart App Control off — Windows lets you do that once.

**The model download is stuck or failed.**
Home shows the model's row with its button; a download resumes on the next start from where
it stopped. If it never finishes, **Settings > The app > Delete and re-download** removes the
partial folder — DeskIT never loads a partial model. A managed or filtered network may block
huggingface.co; the **Network** place shows the refused host. This is the top issue of every
comparable app, which is why the download asks first, shows bytes, and resumes.

**I have no NVIDIA card — does it work?**
Yes, on the processor: transcription takes about as long as you spoke. Two ways to make it
faster: a free Groq key with cloud transcription under **Settings > Privacy** (your audio
leaves this PC to Groq under your key, and the consent card says so), or an NVIDIA card. AMD
and Intel GPUs are planned.

**The dot stays amber ("transcribing…") for a long time.**
See the previous answer. A card appears once when a transcription passes 10 seconds and
offers the same two options.

**Do I need Ollama?**
No. Ollama is optional; without it the "On this computer" entries are hidden from the
provider menus and ask-the-screen offers three buttons (install Ollama / use my key / turn
this key off). If you install it, DeskIT finds it on `127.0.0.1:11434` and names a model
that fits your card.

**"Port busy", or the phone cannot connect.**
DeskIT uses port 8756 and falls through to the next free port; **Settings > Phone** shows the
one in use — paste the link again on the phone. Allow DeskIT through Windows Firewall on
Private networks (the prompt appears once).

**Nothing pastes into this one window.**
It is running as administrator; Windows blocks pasting from a normal program. The text is on
your clipboard: press Ctrl+V.

**The bar does not move / recordings are silence.**
Windows Settings > Privacy & security > Microphone > allow desktop apps; then check the
device under **Settings > General**. The wizard (`main.py --setup`) shows the bar again.

**Where are my keys, and can you see them?**
Control Panel > Credential Manager > Windows Credentials > `DeskIT/groq`, `DeskIT/gemini`.
They go only to api.groq.com / generativelanguage.googleapis.com under your account;
[chapter 4](04-privacy) shows how to verify that yourself.

**What leaves my PC when everything is off?**
Nothing — not even the update check, if you turned that switch off. The **Network** place is
empty during plain dictation.

**Does the phone app send my voice through the internet?**
No: phone → your PC over your own Tailscale network, TLS to your PC's certificate; there is
no relay.

**How do I delete everything?**
[Chapter 8](08-your-data): the reset command, or uninstall and answer Yes to "Remove my data
too?", then remove the keys in Credential Manager.

**Can I move DeskIT to another PC?**
Copy `%LOCALAPPDATA%\DeskIT` into the same place on the other PC; keys are never in the
folder, paste them again.

**Is it free? Is there a paid tier?**
Free and open source (Apache-2.0). The only things that can cost money are the providers'
paid tiers if you exceed their free limits under your own account.

**I found a security problem.**
`SECURITY.md`: e-mail the address there; 90-day disclosure window.
