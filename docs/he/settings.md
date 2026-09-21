---
title: הגדרות
---

# הגדרות

כל הגדרה, במילים שדף ההגדרות משתמש בהן, בסדר שבו הדף מציג אותן. הדף
נוצר מהקובץ `defaults.toml` על ידי `dev/gen_settings_doc.py` — לא נערך
ביד, ולכן לא יכול לסטות מהקובץ. מה שתשנה נשמר ב־`settings.toml` בתוך
תיקיית דסק-איט שלך; הקובץ שליד האפליקציה שומר את ברירות המחדל ואת
ההסבר לכל מפתח.


## General

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `backend` — Where your speech is turned into words | On this computer is faster and better at Hebrew, and nothing leaves the machine. | `local` | On this computer / In Google's cloud |
| `auto_language` — Also understand English | The app decides for each recording; off, everything you say is taken as Hebrew. | on | on / off |
| `punctuate.auto` — Punctuate every dictation | Commas, full stops and question marks go in on the way to the cursor, which costs about a second each time. | off | on / off |
| `punctuate.nikud` — Add vowel points as well | The Hebrew vowel marks go in along with the punctuation. | off | on / off |
| `polish.when` — Fix misheard words with a model | With a cloud key the fix goes in before the text is pasted (a third of a second); without one the model on this PC takes 5-7 s, so the text is pasted at once and its fix arrives as a card you can accept. Or always before the paste, only for words you have corrected before, or never. (per tier — cpu: `never`) | `cloud` | Before the paste with a key, as a card without one / Always before the paste / Only taught words / Never |
| `vocab.enabled` — Use the words it has learned | Corrections you taught it with the correction key are applied to new dictations. | on | on / off |
| `local.cleanup` — Take out the ums and the false starts | The sounds you make while thinking, and a phrase you began again, are dropped. | on | on / off |
| `review.enabled` — Suggest a better word after a dictation | A small card offers the word it thinks you meant; yes teaches it, no is remembered. Off, it learns quietly instead. (per tier — cpu: off) | on | on / off |
| `study.enabled` — Keep learning while the computer is idle | After a few quiet minutes it listens again to what you dictated and learns from what it got wrong. Nothing leaves this PC. (per tier — cpu: off) | on | on / off |
| `translate.target` — Translate into | The language the translate key writes in. | `English` | text |

### On The Screen

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `indicator` — Show the dot in the corner | Blue means it is listening, red means it is recording, amber means it is writing your words down. Click it and the panel opens beside it. | on | on / off |
| `dot.corner` — Which corner the dot sits in | A corner of the main screen above the taskbar — or press Move the dot (here, or on the panel the dot opens), drag it anywhere you like, and press Enter. The panel and the key card open beside it wherever it ends up. | `top-right` | Bottom right / Top right |
| `feedback.enabled` — Mark the cursor with … while it listens | The marker turns into your words when they arrive. | on | on / off |
| `hint.enabled` — Show the key card while a key is held | A card that says what the other keys do, once the key has been held for a moment. | on | on / off |
| `auto_pause_fullscreen` — Pause by itself while a game fills the screen | While a game or a presentation owns the whole screen, the dictation key is left to it, and comes back when it lets go. | off | on / off |

### Messages From Other Programs

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `notify.enabled` — Show messages from other programs | Off, nothing is shown, stored or played. | on | on / off |
| `notify.cue` — Play a sound when one arrives | Off, the card appears in silence. | on | on / off |
| `notify.interrupt` — Which messages pop up | Every one, only what is waiting on you, or none; the rest wait quietly on the panel beside the dot. | `input` | Every message / Only what needs you / None |
| `notify.summarize` — Say a finished message in one line | When Claude finishes, the card carries one plain sentence about its message instead of the first lines — written by Groq, with the cloud-text switch on and a Groq key. Off, or without either, the card shows the message's first lines. | on | on / off |

## Screen

### Ask About The Screen

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `visual_qa.enabled` — Ask about the screen | Hold the key, drag a box, ask; the answer comes back on a card. | on | on / off |
| `visual_qa.speak` — Read the answer aloud | Whether the card offers to say the answer, says every answer as it lands, or never speaks. | `button` | Never / With a button / Always |
| `visual_qa.echo_to_field` — Type what you asked into the field you were in | Once the card closes, so the question becomes part of what you were writing. | on | on / off |

### Screenshots And Recordings

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `capture.enabled` — Screenshots and screen recording | Off, both keys stop working and nothing is taken. | on | on / off |
| `capture.after_shot` — After a screenshot | What happens the moment you let go: a small card, the editor, or nothing at all. | `toast` | Show a small card / Open the editor / Nothing |
| `capture.always_save` — Always save the file as well | Off, the picture is on the clipboard and nowhere else until you press Save. | off | on / off |
| `capture.folder` — Where pictures are saved | Screenshots and webcam photos both land here. A plain name means a folder beside the app. | `captures` | text |
| `capture.clip_folder` — Where recordings are saved | Empty means the same folder as the pictures. | (empty) | text |
| `capture.quality` — Recording quality | How much detail a recording keeps, against how large the file is. | `balanced` | Small file / Balanced / Sharp |
| `capture.audio` — Record the microphone too | Off to start with: a recorder that quietly opens the microphone is a surprise. | `off` | No / Yes |

### Camera

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `camera.enabled` — Take a photo with the webcam | Off, the key does nothing and the camera is never opened. | on | on / off |
| `camera.mirror` — Mirror the picture | Off, because writing held up to a webcam reads backwards mirrored. | off | on / off |

## Phone

### Dictating From The Phone

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `server.enabled` — Dictate from the phone | The phone keyboard sends its recordings here, over your own private network. | off | on / off |

## Privacy

### What May Leave This Pc

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `privacy.cloud_text` — Text to the cloud | What you dictated or selected may go to Groq or Google under your own key, for the repair pass, punctuation, translation, lookup and the second reading. Opens only through its card, the first time a feature needs it. | off | on / off |
| `privacy.cloud_audio` — Recordings to the cloud | What you said, as audio, may go to Google or Groq for transcription. Opens only through its card. | off | on / off |
| `privacy.cloud_screenshots` — Screen pictures to the cloud | The part of the screen you asked about may go to Groq or Google. Opens only through its card. | off | on / off |
| `privacy.account` — An account | Anonymous, or your Google sign-in: for problem reports you choose to send and for the two syncs. Opens only through its card. | off | on / off |
| `privacy.report_upload` — Sending problem reports | Only what the preview showed. Opens only through its card. | off | on / off |
| `privacy.settings_sync` — Syncing settings and words | Your changed settings and learned words follow you to every PC you sign into; never keys, hotkeys, devices, folders or positions. Comes with the sign-in and the wizard's one sync switch; Withdraw turns it off, Turn on here asks again. | off | on / off |
| `privacy.history_sync` — Syncing what you said | The Said page is the same on every PC you sign into. Stored in your account on the developer's server, where he could technically read it. Comes with the sign-in and the wizard's one sync switch, like the settings; Withdraw turns it off on its own, Turn on here asks again. | off | on / off |

### Switches

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `privacy.update_check` — Look for a newer version weekly | One request to GitHub, carrying no identifier. | on | on / off |
| `privacy.offline` — Offline mode | Nothing leaves this computer. Dictation keeps working; cloud fixes, translation and updates pause. | off | on / off |

### Kept On This Pc

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `history.keep_days` — How long what you said is kept, in days | The Said page reads it; older lines are dropped. 0 keeps no history at all. | `30` | a number |

## The app

### This Computer

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `local.load_at_start` — Load the speech model when DeskIT starts | Off, DeskIT starts without it — every key that needs no model works at once, and Start on the desk loads it when you want to dictate. | on | on / off |
| `awake.hold` — Hold the computer awake | While the app is running the machine will not fall asleep on its own timer. The screens may still go dark. | on | on / off |

## Keys — המקשים

אלה המקשים שדסק-איט מאזין להם; מקום Keys מציג אותם על מקלדת מצוירת ומאפשר לשנות אותם.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `awake.screens_hotkey` — Screens hotkey | tap: the screens go off and stay off. | `ctrl+alt+n` | text |
| `camera.camera_hotkey` — Camera hotkey | measured-free like the other ctrl+F keys: the 2026-08 probe found f1-f6 and f10-f16 under ctrl reaching the page untouched in Chrome and Edge. | `ctrl+f6` | text |
| `capture.capture_hotkey` — Capture hotkey | THE SAME KEY WINDOWS USES, taken from it. | `win+shift+s` | text |
| `capture.record_hotkey` — Record hotkey | tap to start, tap again to stop. | `ctrl+f12` | text |
| `correct_hotkey` — Correct hotkey | Fix the words it got wrong RIGHT WHERE THEY LANDED — in Chrome, in Claude Code, wherever you pasted — then TAP this key. | `ctrl+f9` | text |
| `english_hotkey` — English hotkey | A dedicated English key, from before `auto_language` existed. | (empty) | text |
| `hotkey` — Hotkey | hold = dictate Hebrew | `right ctrl` | text |
| `latch_hotkey` — Latch hotkey | Holding a key is fine for a sentence and miserable for a paragraph. | `left` | text |
| `lookup_hotkey` — Lookup hotkey | The key that looks something up without touching it. | `ctrl+f8` | text |
| `notify.dismiss_hotkey` — Dismiss hotkey | tap: the card goes away and everything is marked seen, wherever the mouse is. | `ctrl+alt+m` | text |
| `pause_hotkey` — Pause hotkey | TAP to make every key above inert — without unloading anything. | `insert` | text |
| `problems.report_hotkey` — Report hotkey | tap: the report box opens over whatever is in front, wherever the mouse is. | `ctrl+alt+r` | text |
| `punctuate_hotkey` — Punctuate hotkey | TAP to put the PUNCTUATION into what is already at the cursor: whatever is selected, or the whole field when nothing is selected. | `ctrl+f2` | text |
| `shelf.shelf_hotkey` — Shelf hotkey | tap: the panel opens beside the dot. | `ctrl+alt+d` | text |
| `translate_hotkey` — Translate hotkey | TAP (don't hold) to turn what is already at the cursor into English: whatever is selected, or the whole field when nothing is selected. | `f8` | text |
| `visual_qa.visual_qa_hotkey` — Visual qa hotkey | measured-free like the other ctrl+F keys: everything the 2026-08 probe pressed (f1-f6, f10-f16 under ctrl) reached the page untouched in Chrome and Edge. | `ctrl+f10` | text |
