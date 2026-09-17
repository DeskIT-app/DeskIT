# onboarding

Question: What the first five screens of comparable dictation apps do (Handy, Vibe, Superwhisper, Wispr Flow, Windows voice typing), what DeskIT should copy and avoid, and the page order for the chapter 9 wizard that hosts `models.step()` / `packs.step()` from `steps.py`.

Date of research: 2026-09-17. Read from source where the app is open (Handy `src/components/onboarding/*.tsx` + `en/translation.json`; Vibe `desktop/src/pages/setup/*` + `i18n/desktop/{en-US,he-IL}.json`), from the vendor's docs otherwise. Nothing was installed.

## What each app does in its first five screens

| app | 1 | 2 | 3 | 4 | 5 | notes |
|---|---|---|---|---|---|---|
| **Handy** (Tauri, offline, MIT) | "Permissions Required" — on Windows only Microphone ("Required to hear your voice for transcription."), reads the Windows mic privacy state and polls: Grant Permission → Waiting... → "All set!" | "To get started, choose a transcription model": cards with name, size, accuracy/speed bars, a "Recommended" badge; two picks up front, "Show all N models" folds the rest; % + MB/s + Cancel per card | the settings window (the model is selected the moment it verifies) | — | — | No welcome, no consent, no test, no hotkey page; hotkey lives in settings. Returning users get a "What's new" gate. Download errors surfaced in-place and Cancel were added in 0.9.x after complaints. |
| **Vibe** (Tauri, IL author) | "Setup / Downloading Model..." — starts at once, no ask, no size, no folder; "This happens only once! 🎉"; ghost [Cancel] (tooltip "You can cancel and download the model manually later") | "No Connection" dialog: "Internet connection is required to download the AI model" [Try Again] [I prefer to download manually] | the main window | — | — | Locale ending `-IL` puts the ivrit-ai ggml model first in the URL list (three mirrors). Failures end as "All model downloads failed. Last error: …" — its top open issues (#1479, #1552). Hebrew strings exist (מוריד מודל בינה מלאכותית...). |
| **Superwhisper** (Windows mid-2026) | Welcome | Permissions: Microphone (+ Accessibility on macOS) | Wizard: language → transcription model → microphone; "The defaults work well, and you can change everything later." Cloud default = "nothing to download"; local = "one-time download (75 MB – 3 GB)", first use downloads | The shortcut shown; "Dictate your first text" | — | Cloud vs local table with Setup / Privacy / Offline / Speed rows; sizes per model (Whisper Large v3 Turbo 1.6 GB, Parakeet 494 MB). Files in `%LOCALAPPDATA%\com.superwhisper.app`. |
| **Wispr Flow** (cloud, account) | Sign in via browser (Google/Apple/Microsoft/SSO/e-mail) | Microphone permission; intro screens [Continue] | "Tell us about yourself"; privacy notice | Microphone test (speak aloud); shortcut (press the keys / "Edit shortcut"); languages or auto-detect | "Try It Yourself" hold-speak-release demos; "You control your data": Improve the model for everyone / Don't use my data for training; "Explore Wispr Flow" → Flow Hub | Twelve steps in all. The one page every review praises is the hold-speak-release demo. |
| **Windows voice typing** (Win+H) | No wizard: a floating toolbar, "Listening..." cue, speak | First use needs Settings > Privacy & security > Speech > Online speech recognition ON (a system consent, the audio goes to Azure) | Gear: Voice typing launcher, Automatic punctuation, Filter profanity, Default microphone | — | — | Hebrew: "Voice typing isn't available in the current language" (Q&A 3894380). Copilot+ "Fluid dictation" models download in the background through Windows Update, the option dimmed until they land. |

## What DeskIT copies

1. **Ask, then download in the open** (Handy, Superwhisper): size, source and folder on the screen before a byte moves, %, bytes and rate during, [Pause]/[Cancel] that leaves a resumable part, the error printed on the same page. `steps.py` already does all of this; the wizard hosts it rather than reinventing it.
2. **Read the Windows microphone privacy switch up front** (Handy's `getWindowsMicrophonePermissionStatus`): `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone` (`Value`, plus `NonPackaged\` for desktop apps). Today the wizard learns it from 6 s of silence (`QUIET_S`); a registry read says it before the meter is even drawn, and the meter stays as the proof.
3. **"The defaults work well, and you can change everything later"** (Superwhisper) — one sentence on Welcome and on Done; `[Later]`/`[Skip]` on every page that downloads or measures.
4. **One data page with the switches OFF and the choice explicit** (Wispr's "You control your data") — this is the Optional-extras page; each switch opens its consent card (`consent_card.py`, `privacy.grant`). Weekly update check is the one switch drawn ON, because `privacy.py` ships it on (`update_check = true`, D21), not OFF as 9.2 wrote.
5. **The hotkey named on the last page and a first dictation asked for** (Superwhisper, Wispr): "Hold <key> and speak" with the dot's corner named; the wizard cannot hook the key itself (it does not import `main.py`), so the [Open the desk] button and the sentence do the job.
6. **"This happens only once"** (Vibe) — one line under the model bar.

## What DeskIT avoids

- Vibe's silent auto-download: no ask, no size, a bare AppData path in the failure line — every one of its open download issues starts there. D13 already forbids it.
- Wispr's sign-in, "tell us about yourself" and twelve steps; Superwhisper's language/model/mic pages before anything has proved it works. The meter comes first (`firstrun.py` docstring: "a bar that moves when you talk").
- Handy's and Vibe's blocking on the download: in DeskIT the download keeps running while the wizard moves on, and the sentence page waits for it or is skipped.
- A model picker: there is one Hebrew model (D13); the English detector (+1.6 GB) is a fifth decision nobody can judge on first run — Settings > Speed only, not the wizard (`arch-A §1 P2`: at most four decisions).

## Proposed page order (hosts `steps.py`) — built as `firstrun.py` in PR 20 (2026-09-18); the departures are recorded under D18

| page | chrome | hosts | decision | skippable |
|---|---|---|---|---|
| 0 Welcome | "Welcome" | three Hebrew sentences, "How to check this yourself" (guide ch. 4), privacy link in the footer, the defaults sentence | — | Next |
| 1 Microphone | "Microphone" | today's `_step_mic` + the registry pre-check (copy 2) | device, only when >1 | no |
| 2 This computer | "This computer" | `hardware.summary()` line; `models.step(entry)` as a **pane**; on tier gpu/gpu-small a Switch "Use the NVIDIA card (1.37 GB, NVIDIA licence)" ON that queues `packs.step(gpu)` after the model in the same bar ("1 of 2 · Hebrew model"); [Download] [Later] | model; pack | Later |
| 3 Say one sentence | "Say one sentence" | today's `_step_say`; if the download is still running the same bar sits here ("the model is still coming — 62 %"); writes `last_test_seconds` | — | Skip |
| 4 Keys | "Keys" | today's `_step_done` board (`keycaps.py`) | — | yes |
| 5 Optional extras | "Optional extras" | Switches: cloud repair (OFF → `cloud_text` card, then the Keys block if no key), keep awake (OFF), weekly update check (ON), start with Windows (`setup.autostart`, OFF), phone keyboard (OFF → Settings > Phone) | one | yes |
| 6 Done | "Ready" | "Hold <key> and speak", [Open the desk] [Finish]; deferred model → "download it from Home"; `setup_done` → `state.json` | — | Finish |

**How the pieces fit.** `steps.StepWindow` splits in two: `StepRun` (the thread, the cancel event, the queue — owned by the wizard so it outlives a page) and `StepPane` (a `ui.py` frame that draws one run: title, body through the bitmap path, size line, bar, links, the buttons); `StepWindow` becomes Toplevel + pane and stays for `--download-model` / `--install-pack` from the dashboard (`launch.run_step`). `main.py` shows the two standalone steps only when the wizard is NOT due (`firstrun.needed()` false — a set-up copy whose model was deleted); when it is due, the wizard owns them. `firstrun.needed()` reads `setup_done` from `state.json` (D2/D18) instead of the marker file; `main.py --setup` still reruns it.

## Sources

- Handy: github.com/cjpais/Handy — `src/components/onboarding/{Onboarding,ModelCard,AccessibilityOnboarding}.tsx`, `src/i18n/locales/en/translation.json`, `src/App.tsx` (OnboardingStep "accessibility" | "model" | "done"); deepwiki.com/cjpais/Handy/2.1-installation-and-first-run.
- Vibe: github.com/thewh1teagle/vibe — `desktop/src/pages/setup/{page.tsx,view-model.ts}`, `desktop/src/lib/config.ts` (`modelUrls.hebrew`), `i18n/desktop/{en-US,he-IL}.json`.
- Superwhisper: superwhisper.com/docs/get-started/{quickstart,windows,choose-your-model}.md (fetched 2026-09-17).
- Wispr Flow: docs.wisprflow.ai/articles/3152211871-setup-guide.
- Windows: support.microsoft.com "Use voice typing to talk instead of type on your PC"; learn.microsoft.com Q&A 3894380, 12786706; Insider build 26220.8474 notes (Fluid dictation).

## Uncertainties

- Superwhisper's Windows wizard was read from its docs, not seen; the exact order language → model → microphone is the docs' sentence.
- Wispr's twelve steps are the help-centre order; screens may differ by version.
- The `ConsentStore\microphone` registry read was checked on the owner's PC only (`Value` = Allow at both levels, per-exe rows under `NonPackaged\`); the Deny path was not seen. The meter remains the proof either way.
