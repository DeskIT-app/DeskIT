# runFullTrust — the text for Partner Center

Entered once in Partner Center, in the submission's "Submission options"
box for restricted capabilities (DISTRIBUTION_PLAN.md 10.7). Kept here so
the words the reviewer read are in the repository beside the manifest
that declares the capability.

---

DeskIT is a push-to-talk dictation tool for Windows. It needs full trust
for things a sandboxed app cannot do:

1. A global low-level keyboard hook, so the key the user chose starts and
   stops recording in any application, and simulated key input (the
   clipboard and Ctrl+V) to put the text where the cursor is.
2. Reading the pixels of the screen for the optional screenshot,
   screen-recording and ask-the-screen keys — only when the user presses
   the key for it.
3. A listener on the PC so the optional Android keyboard can send speech
   over the user's own network, and so Claude Code's hook can post a
   notification to the running app over loopback.
4. Windows Credential Manager, where the user's own API keys are kept.

Speech is transcribed on the device by default; nothing leaves the PC
without a consent switch that names the recipient, and every connection
the app can make is listed in NETWORK.md and shown in the app's Network
window.

Privacy policy: https://deskit-app.github.io/DeskIT/privacy
Source code: https://github.com/DeskIT-app/DeskIT
