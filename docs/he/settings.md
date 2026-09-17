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
| `backend` — Where your speech is turned into words | On this computer is faster and better at Hebrew, and nothing leaves the machine. | `local` | On this computer / In the cloud (Gemini) / Fake, for testing |
| `auto_language` — Notice when a sentence is English | The app decides for each recording; off, everything you say is taken as Hebrew. | on | on / off |
| `punctuate.auto` — Punctuate every dictation | Commas, full stops and question marks go in on the way to the cursor, which costs about a second each time. | off | on / off |
| `polish.when` — Fix misheard words with a model | Always, only when the sentence holds a word you have corrected before, or never. (per tier — cpu: `never`) | `always` | Always / Only taught words / Never |
| `vocab.enabled` — Use the words it has learned | Corrections you taught it with the correction key are applied to new dictations. | on | on / off |
| `feedback.enabled` — Mark the cursor with … while it listens | The marker turns into your words when they arrive. | on | on / off |
| `hint.enabled` — Show the key card while a key is held | A card that says what the other keys do, once the key has been held for a moment. | on | on / off |
| `auto_pause_fullscreen` — Pause by itself while a game fills the screen | While a game or a presentation owns the whole screen, the dictation key is left to it, and comes back when it lets go. | off | on / off |
| `indicator` — The little dot in the corner | Blue means it is listening, red means it is recording, amber means it is writing your words down. Click it and the panel opens beside it. | on | on / off |
| `dot.corner` — Which corner the dot sits in | A corner of the main screen above the taskbar — or press Move the dot and put it anywhere you like. The panel and the key card open beside it wherever it ends up. | `top-right` | Bottom right / Top right |
| `problems.enabled` — Report a problem with one line | The report key opens a box; the app attaches the dictation, the recording and the settings itself. | on | on / off |

## Dictation

### Recording

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `min_seconds` — Shortest hold that counts, in seconds | Anything shorter is treated as an accidental tap and thrown away. | `0.3` | a number |
| `max_seconds` — Longest recording while you hold, in seconds | Past this it stops on its own, drops the recording and beeps. | `400` | a number |
| `latch_max_seconds` — Longest recording once it is locked on, in seconds | Zero means no limit at all. | `0` | a number |

### Pasting

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `feedback.placeholder` — The marker itself | The characters it leaves at the cursor while it works. | `...` | text |
| `paste_chord` — Paste with | The keys the app presses to put your words at the cursor; some terminals want a different pair. | `ctrl+v` | text |
| `restore_delay_ms` — Wait before your old clipboard comes back, in milliseconds | The app borrows the clipboard to paste, then puts back whatever was on it. | `300` | a number |

### When The Cloud Runs Out

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `fallback_to_local` — Use this computer when the cloud has nothing left | A free cloud service only answers so many times a day; when it stops, the model here does the work. | on | on / off |

### Fixing Words

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `polish.max_wait_s` — Longest your paste may be held up, in seconds | Past this the dictation is pasted exactly as it came and the answer is thrown away. (per tier — gpu-small: `6.0`) | `10` | a number |
| `study.enabled` — Keep learning while you are away | After a quiet spell it listens again to what you sent and learns from what it got wrong. Nothing leaves the machine. (per tier — cpu: off) | on | on / off |
| `study.idle_minutes` — Minutes of quiet before it starts | It steps aside the moment you press a key, so a dictation never waits for it. | `3` | a number |

### At Startup

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `splash` — Show a small window while the models load | Without it, clicking the shortcut looks like it did nothing. | on | on / off |

### Updates

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `updates.channel` — Which releases to look at | Stable is the tested one; beta gets each version a little earlier. The weekly check itself is the switch on Privacy. | `stable` | Stable / Beta, a little earlier |
| `updates.skipped` — A version you chose to skip | Empty means none. A newer version than this one is offered again. | (empty) | text |

### The Microphone

Which microphone it listens to, and how finely it records what it hears.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `audio.sample_rate` — How finely the sound is recorded | The speech model was trained for one setting, so this is best left where it is. | `16000` | a number |

### The Marker At The Cursor

The few characters it drops where you are typing, so you can see it heard you while it works.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `feedback.retry_seconds` — How long it keeps trying to paste, in seconds | If the window will not take the words it keeps trying this long, then saves them for later instead of losing them. | `45` | a number |

### What You Said, Kept

How long the record of your dictations stays on this PC for the Recent view.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `history.keep_days` — How long what you said is kept, in days | The Recent view and the clipboard-recovery path read it; older lines are dropped. 0 keeps no history at all. | `30` | a number |

### Words It Has Learned

Names and terms the speech model never heard, handed to it before it listens so it gets them right first time.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `vocab.max_terms` — How many learned words it may use at once | A longer list is not a better one: too many and the model starts saying them when you did not. | `40` | a number |
| `vocab.replace_after_hits` — How many corrections before a word is fixed by itself | One correction could be a slip of the hand, so it waits for the same fix to happen again. | `2` | a number |
| `vocab.hebrew_after_hits` — The same, for a correction that is all Hebrew | A real Hebrew word handed to the model makes it say that word unbidden, so Hebrew has to prove itself more. | `3` | a number |
| `vocab.keep_audio` — How many recent recordings to keep | Keeping the sound is what lets a correction be checked against what was really said. Zero keeps none. | `50` | a number |
| `vocab.terms` — The words you seeded by hand | Your own names and terms. Anything you correct with the correction key is added on its own. | (empty) | a list |

### Learning While You Are Away

After a quiet spell it listens again to what you sent and learns from what it got wrong.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `study.max_clip_seconds` — Longest recording it will study, in seconds | Listening again to a very long recording buys little extra evidence for the time it takes. | `120` | a number |
| `study.llm_per_day` — How many recordings a model may judge each day | Past this the rest simply wait for tomorrow. | `60` | a number |
| `study.corpus_keep` — How many checked recordings to keep | Kept here as material for teaching the model your own voice one day. Zero keeps none. | `400` | a number |

### Fixing Misheard Words

A model reads the sentence and puts back a word that was misheard. It may fix words; it may never write new ones.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `polish.min_chars` — Shortest text worth fixing, in letters | Below this there is no sentence to reason from, which is where a model starts inventing. | `20` | a number |
| `polish.prefer` — Which service fixes the words first | The others follow underneath, so a service that is down costs you speed and never the repair. | `groq` | Groq — fast, free tier / Cerebras / On this computer |
| `polish.groq_model` — Which model to ask on Groq | The one the repair pass sends your text to when Groq goes first. | `openai/gpt-oss-120b` | text |
| `polish.groq_timeout_s` — How long to wait for Groq, in seconds | Past this something is wrong and the next service should have the work. | `20` | a number |
| `polish.cerebras_model` — Which model to ask on Cerebras | Only worth setting if you still have turns left there. | `gpt-oss-120b` | text |
| `polish.cerebras_timeout_s` — How long to wait for Cerebras, in seconds | Past this the next service should have the work. | `20` | a number |
| `polish.ollama_model` — Which model on this computer | The one that fixes the words when no cloud service can. Empty means reuse the translate key's model. (per tier — gpu-small: `gemma3:4b`; cpu: `gemma3:4b`) | `gemma3:12b` | text |
| `polish.warm_up` — Wake the model when the app starts | One throwaway request, so the first dictation of the day does not wait for it. It holds graphics memory all the while. | on | on / off |

### The Speech Model On This Computer

The model that turns your voice into words with nothing leaving this computer.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `local.model` — Which speech model | The Hebrew one this app was built around. | `ivrit-ai/whisper-large-v3-turbo-ct2` | text |
| `local.language` — Which language it expects | It has to stay Hebrew: this model cannot work the language out for itself. | `he` | text |
| `local.cleanup` — Take out the ums and the false starts | The sounds you make while thinking, and a phrase you began again, are dropped. | on | on / off |
| `local.extra_fillers` — Your own ums to drop | Only add words you never mean literally, or real speech will go with them. | (empty) | a list |
| `local.initial_prompt` — The sentence that sets the scene | It tells the model to expect Hebrew with English technical words in it, so it stops dropping the English half. | `שיחה בעברית עם מונחים טכניים באנגלית כמו commit, branch, pull request, merge, deploy, terminal, repo, bug, feature.` | text |
| `local.english_model` — The model for English-only speech | The Hebrew one writes short English sentences out in Hebrew letters, so confident English goes here instead. (per tier — gpu-small: (empty); cpu: (empty)) | `deepdml/faster-whisper-large-v3-turbo-ct2` | text |
| `local.english_threshold` — How sure it must be before calling something English | High on purpose: Hebrew sent to the English model is far worse than one English word in Hebrew letters. | `0.8` | a number |
| `local.guard_hallucinations` — Stop it inventing words you never said | The model keeps writing past the end of real speech and fills the gap; this makes it fussier about what it keeps. | on | on / off |
| `local.drop_trailing_boilerplate` — Drop stock phrases stuck to the end | Never in the middle, where they are almost certainly really yours. | on | on / off |
| `local.extra_boilerplate` — Your own stock phrases to drop | Whole phrases only: one common word here would delete real speech. | (empty) | a list |
| `local.rolling` — Transcribe while you are still talking | The recording is decoded in stretches as you speak, so letting go waits only for the last few seconds. Nothing shows early. | on | on / off |
| `local.rolling_window_s` — How many seconds a stretch waits for, before it is decoded | Shorter means more is done by the time you let go; longer means each stretch is read with more of its own context. Below 20 it was measured to cost words. | `25.0` | a number |

### The Second Reading

The moment a dictation lands, the recording is read again and a card offers back any word it doubts.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `review.enabled` — Read every dictation a second time | Off, there are no cards and no proposals, and the quiet learning while you are away goes on instead. (per tier — cpu: off) | on | on / off |
| `review.card_seconds` — How long the card stays, in seconds | The bar under the title is that clock, and it stops while the mouse is on the card. Zero shows no card at all. | `20` | a number |
| `review.corner` — Where the card appears | Before you have dragged it somewhere else. | `right` | Middle of the right edge / Middle of the left edge / Top right / Top left / Bottom right / Bottom left |
| `review.max_changes` — The most words one reading may offer | A reading that wants more than this is a rewrite rather than a repair, and is dropped. | `4` | a number |
| `review.witness` — How many extra readings must agree | The recording is read several more ways; a word is only offered when this many of them heard it. | `2` | a number |
| `review.accept_key` — The key that says yes | It only counts while the mouse is over the card; anywhere else it types as usual. | `v` | text |
| `review.reject_key` — The key that says no | Also only while the mouse is over the card. | `x` | text |
| `review.later_key` — The key that closes the card for now | Nothing is decided: the proposal waits for you in this window. | `l` | text |
| `review.edit_key` — The key that opens the pencil | A small box asks what the word should have been, and Enter accepts the card with that word. | `e` | text |
| `review.fix_in_field` — Also fix the words where they landed | If that window is still in front and still holds exactly what was pasted. Off, saying yes only teaches. | on | on / off |
| `review.max_clip_seconds` — Longest recording it will read again, in seconds | Reading a very long recording several more ways holds the model up for little gain. | `120` | a number |
| `review.llm_per_day` — How many readings a model may judge each day | Past this the reading still runs, and can only offer the invented endings it finds on its own. | `200` | a number |
| `review.local_model` — Ask the model on this computer when the cloud refuses | Off, because the proposals it made on its own were wrong more often than they were right. | off | on / off |

## Speed

### On This Computer

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `local.device` — What it runs on | The graphics card is far faster; it falls back to the processor where there is none. (per tier — gpu: `cuda`; gpu-small: `cuda`; cpu: `cpu`) | `auto` | Decide for itself / The graphics card / The processor |
| `local.compute_type` — Number format | Auto is float16 on a card and int8 on the processor; the mixed one fits a card with 4-6 GB. (per tier — gpu: `float16`; gpu-small: `int8_float16`; cpu: `int8`) | `auto` | Auto / float16 — the card / int8 + float16 — a small card / int8 — the processor |
| `local.cpu_threads` — Processor threads for the model | 0 lets the library decide; on a machine without a card the probe writes the core count. (per tier — gpu: `0`; gpu-small: `0`) | `0` | a number |
| `local.beam_size` — Beam width | 5 is the accuracy the app was measured at; 2 or 1 is faster on a processor and a little less accurate. (per tier — gpu: `5`; gpu-small: `5`; cpu: `2`) | `5` | a number |
| `setup.offer_gpu_pack` — Offer GPU speed at start | On a PC with an NVIDIA card, the start asks once to download NVIDIA's libraries (1.37 GB) so dictation runs on the card. Not now turns this off. | on | on / off |

## Text

### Punctuation

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `punctuate.prefer` — Which service punctuates first | The other two are tried underneath when it has nothing left for today. | `groq` | Groq — fast, free tier / Gemini / Ollama, on this computer |
| `punctuate.max_wait_s` — Longest wait for punctuation, in seconds | Past this the dictation is pasted exactly as it came. | `6` | a number |
| `punctuate.nikud` — Add vowel points as well | The Hebrew vowel marks go in along with the punctuation. | off | on / off |

### Translating

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `translate.target` — Translate into | The language the translate key writes in. | `English` | text |

### Looking Up

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `lookup.both_ways` — Answer Hebrew selections too | Off, only an English selection gets an answer. | on | on / off |

### Turning Text Into Another Language

The key that rewrites what is at the cursor in another language, and the services it asks to do it.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `translate.max_chars` — Most letters it will translate at once | Above this the key refuses, on the assumption a select-all caught a whole document. | `5000` | a number |
| `translate.ollama_model` — The model on this computer | The one it falls back to when the cloud has nothing left for today. (per tier — gpu-small: `llama3.2:3b`; cpu: `llama3.2:3b`) | `llama3.1:8b` | text |
| `translate.ollama_url` — Where that model answers | The address the model on this computer is reached at. | `http://127.0.0.1:11434` | text |
| `translate.timeout_s` — How long to wait for the cloud, in seconds | Past this it gives up and tries the next service. | `30` | a number |
| `translate.ollama_timeout_s` — How long to wait for this computer, in seconds | A model that has not been used for a while has to be loaded first, which is slow. | `150` | a number |
| `translate.settle_ms` — How long the other window gets to hand the text over, in milliseconds | The app copies what you selected; this is the pause it allows for the copy to arrive. | `120` | a number |

### Commas And Full Stops

Putting punctuation into text that was dictated without any, without changing a single word of it.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `punctuate.max_chars` — Most letters it will punctuate at once | With nothing selected the key takes the whole field, so this is the ceiling on it. | `5000` | a number |
| `punctuate.groq_model` — Which model to ask on Groq | Empty means use the same one the repair pass uses. | (empty) | text |
| `punctuate.ollama_model` — Which model on this computer to ask | Empty means use the same one the translate key uses. | (empty) | text |

### The Look-Up Box

The small box that says what a selected word means, and never touches anything on screen.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `lookup.hebrew_share` — How much Hebrew makes a selection Hebrew | At or above this share of Hebrew words the answer comes back in English; below it, in Hebrew. | `0.34` | a number |
| `lookup.max_chars` — Most letters it will look up at once | Above this the key refuses rather than spending a long time on it. | `20000` | a number |
| `lookup.prefer` — Which service answers first | The model on this computer goes first here, so a key you tap while reading never spends the cloud's daily turns. | `ollama` | On this computer / Google's model |
| `lookup.model` — Which model writes the meaning | The one on this computer that answers a look-up. (per tier — gpu-small: `gemma3:4b`; cpu: `gemma3:4b`) | `gemma3:12b` | text |
| `lookup.cold_to_gemini` — Ask the cloud while the local model wakes up | A model that has not been used in a while takes a long time to load, so the first look-up goes out instead. | on | on / off |
| `lookup.keep_alive` — How long the model stays ready | Written as a length of time. Longer keeps look-ups instant and holds on to graphics memory. (per tier — gpu-small: `10m`) | `30m` | text |
| `lookup.strip_niqqud` — Take Hebrew vowel marks out of the answer | The model sometimes writes a whole line in vowel points, which is harder to read than plain Hebrew. | on | on / off |
| `lookup.dwell_ms` — How long the box waits before closing | Nothing reads this any more: the box waits for you to close it, and never takes itself away. | `12000` | a number |
| `lookup.max_width` — How wide the box opens, in pixels | You can still drag it wider by either bottom corner. | `460` | a number |
| `lookup.max_height` — How tall the box opens, in pixels | A longer answer shrinks its letters to fit before anything is cut off. | `520` | a number |
| `lookup.cache_entries` — How many answers it remembers | Looking the same word up again is instant and costs nothing. | `500` | a number |
| `lookup.skip_consoles` — Refuse inside terminal windows | The copy this key makes would otherwise interrupt whatever is running there. | on | on / off |

### Google'S Models

The cloud service several keys fall back on, and how long they are willing to wait for it.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `gemini.models` — Which models to try, in order | Each one has its own small daily allowance, so a list of them lasts longer than any single name. | gemini-2.5-flash, gemini-flash-latest, gemini-2.5-flash-lite, gemini-flash-lite-latest | a list |
| `gemini.timeout_s` — How long to wait, in seconds | Past this it gives up and something else is asked. | `30` | a number |

## Screen

### Ask About The Screen

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `visual_qa.enabled` — Ask about the screen | Hold the key, drag a box, ask; the answer comes back on a card. | on | on / off |
| `visual_qa.speak` — Read the answer aloud | Whether the card offers to say the answer, says every answer as it lands, or never speaks. | `button` | Never / With a button / Always |
| `visual_qa.echo_to_field` — Type what you asked into the field you were in | Once the card closes, so the question becomes part of what you were writing. | on | on / off |
| `visual_qa.auto_send` — Send a spoken question the moment you let go | Otherwise you press Enter, which leaves room to edit what you asked first. | on | on / off |

### Screenshots

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `capture.enabled` — Screenshots and screen recording | Off, both keys stop working and nothing is taken. | on | on / off |
| `capture.after_shot` — After a screenshot | What happens the moment you let go: a small card, the editor, or nothing at all. | `toast` | Show a small card / Open the editor / Nothing |
| `capture.copy_to_clipboard` — Put the picture on the clipboard | It is there the moment you let go of the mouse. | on | on / off |
| `capture.always_save` — Always save the file as well | Off, the picture is on the clipboard and nowhere else until you press Save. | off | on / off |
| `capture.folder` — Where pictures are saved | Screenshots and webcam photos both land here. A plain name means a folder beside the app. | `captures` | text |

### Recording

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `capture.quality` — Quality | How much detail a recording keeps, against how large the file is. | `balanced` | Small file / Balanced / Sharp |
| `capture.fps` — Frames per second | How many pictures a second a recording takes. | `30` | a number |
| `capture.audio` — Record the microphone too | Off to start with: a recorder that quietly opens the microphone is a surprise. | `off` | No / Yes |
| `capture.cursor` — Show the pointer | The mouse pointer is painted in, so it is clear what is being pointed at. | on | on / off |
| `capture.max_minutes` — Stop recording after, in minutes | A backstop for a key tapped by accident. Zero means never stop by itself. | `30` | a number |

### Camera

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `camera.enabled` — Take a photo with the webcam | Off, the key does nothing and the camera is never opened. | on | on / off |
| `camera.mirror` — Mirror the picture | Off, because writing held up to a webcam reads backwards mirrored. | off | on / off |
| `camera.timer` — Countdown before the shot, in seconds | The letter t changes it while the camera window is open. | `0` | a number |
| `camera.size` — Picture size | How big a picture the camera is asked for. | `1280x720` | text |
| `camera.edit_after_shot` — Open the photo in the editor | Right where the preview was, so you can crop it or draw on it. | on | on / off |

### Ask The Screen

Drag a box over anything on screen, ask a question about it, and the answer comes back on a card.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `visual_qa.prefer` — Which model answers first | The others are tried underneath it, when sending pictures out is allowed at all. | `ollama` | On this computer / Groq — fast, free tier / Google's model |
| `visual_qa.ollama_model` — Which model on this computer answers | It has to be one that can look at pictures as well as read. (per tier — gpu-small: `gemma3:4b`; cpu: `gemma3:4b`) | `gemma3:12b` | text |
| `visual_qa.groq_model` — Which model to ask on Groq | Used only when sending pictures out is allowed. | `qwen/qwen3.6-27b` | text |
| `visual_qa.gemini_fallback` — Try Google's model as well | Only when sending pictures out is allowed, and only after the others. | on | on / off |
| `visual_qa.max_side_px` — Biggest the picture is sent at, in pixels | The long side is shrunk to this before it goes; larger buys no more detail, only waiting. | `1344` | a number |
| `visual_qa.num_predict` — Longest answer it may write | Counted in pieces of words. It is what stops a rambling model filling the card. | `400` | a number |
| `visual_qa.window_alpha` — How solid the card looks | Lower lets more of the screen behind it show through; the writing stays sharp either way. | `0.93` | a number |
| `visual_qa.warmup` — Wake the model when the app starts | One throwaway question at startup, so the first real one does not keep you waiting. | on | on / off |
| `visual_qa.ollama_timeout_s` — How long to wait for this computer, in seconds | Generous on purpose, because a model that has to load itself first is slow. (per tier — gpu-small: `60`; cpu: `60`) | `120` | a number |
| `visual_qa.cloud_timeout_s` — How long to wait for a cloud answer, in seconds | Past this the next service should have the work instead. | `30` | a number |

### Screenshots And Screen Recordings

Drag a box to copy a picture of the screen, or record it to a film. None of it leaves this computer.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `capture.clip_folder` — Where recordings are saved | Empty means the same folder as the pictures. | (empty) | text |
| `capture.toast_corner` — Which corner the card after a screenshot appears in | The small card holding what you just took, with the editor one click away on it. | `bottom-right` | Top right / Top left / Bottom right / Bottom left |
| `capture.toast_seconds` — How long that card waits for you, in seconds | The clock stops while the pointer is on the card. | `10` | a number |
| `capture.toast_stack` — How many such cards may be up at once | Take another picture while one is up and a second card joins it, each with its own clock. | `4` | a number |
| `capture.toast_in_shots` — Let a screenshot see those cards | So you can take a picture of one and show it to somebody. Off hides them from every picture and recording. | on | on / off |
| `capture.copy_clip_path` — Put a finished recording on the clipboard as a file | So it pastes into a chat or a folder the way a copied file does. | on | on / off |
| `capture.timer_corner` — Which corner the recording clock sits in | The little red dot and clock while a recording runs. It is hidden from the recording itself. | `bottom-right` | Top right / Top left / Bottom right / Bottom left / Do not show it at all |
| `capture.announce` — Say when a recording has started | A short banner before it shrinks to the clock, because not knowing whether it is running is the usual worry. | on | on / off |

### The Webcam Photo

A picture from the webcam, into the same folder and the same editor as a screenshot.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `camera.fps` — Frames per second asked of the camera | A camera that cannot manage it simply sends fewer. | `30` | a number |
| `camera.folder` — Where photos are saved | The same folder the screenshots go to, so all the pictures are in one place. | `captures` | text |
| `camera.copy_to_clipboard` — Put the photo on the clipboard | It is there the moment the shutter fires. | on | on / off |

## Cards

### The Key Card

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `hint.after_ms` — Show it after holding for, in milliseconds | A quick dictation is over before the card appears. | `400` | a number |
| `hint.corner` — Which corner it starts in | Where the card appears before you have dragged it somewhere else; beside the dot means the dot's own corner, next to it. | `dot` | Beside the dot / Top right / Top left / Bottom right / Bottom left |

### Messages From Other Programs

A door other programs knock on: a card appears at the edge of the screen and reminds you until you answer.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `notify.enabled` — Take messages from other programs | Off, the door is shut: nothing is shown, stored or played. | on | on / off |
| `notify.cue` — Play a sound when one arrives | Off, the card appears in silence. | on | on / off |
| `notify.card_seconds` — How long a card stays, in seconds | Zero means it waits until you dismiss it, however long that takes. | `0` | a number |
| `notify.stack_max` — How many cards may be on screen at once | The rest wait in this window, counted on the bottom card. | `5` | a number |
| `notify.remind_every_s` — Show an unread card again after, in seconds | Zero never reminds you: the card waits quietly instead. | `120` | a number |
| `notify.remind_times` — How many reminders each message gets | After that it stops asking and waits for you in this window. | `2` | a number |
| `notify.coalesce_s` — Treat a quick second message as the same one, in seconds | A repeat from the same program updates the card instead of ringing all over again. | `5` | a number |
| `notify.interrupt` — Which messages may pull you away | Everything, only what is actually waiting on you, or nothing at all. | `input` | Every message / Only what needs you / Never interrupt |
| `notify.quiet_s` — Hold a finish until that program goes quiet, in seconds | Zero shows it the moment it lands. Anything waiting on you is never held back either way. | `0` | a number |
| `notify.corner` — Where a card appears | Before you have dragged it somewhere else. | `right` | Middle of the right edge / Middle of the left edge / Top right / Top left / Bottom right / Bottom left |
| `notify.anchor` — Which edge of the pile stays put | A longer message can grow upward from the bottom or downward from the top. | `bottom` | Grow upward / Grow downward |
| `notify.scale` — How big the cards are drawn | The same size for every card in the pile. | `1.0` | a number |

### Telling It Something Went Wrong

One typed line, and the app attaches the rest itself: the dictation, the recording and the settings.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `problems.shot` — Attach a picture of the screen | The screen as it looked when you pressed the key. It stays on this computer. | on | on / off |
| `problems.keep_audio` — Keep the recording it is about | So the sound outlives the short list of recent recordings and can still settle what was really said. | on | on / off |
| `problems.keep_resolved` — How many answered reports to keep | Ones nobody has answered yet are never thrown away, whatever this says. | `200` | a number |

### The Panel Beside The Dot

One key opens a small panel next to the dot with everything waiting for you; the same key closes it.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `shelf.enabled` — The panel beside the dot works | Off, the key does nothing. Every card, every sound and this window go on as before. | on | on / off |
| `shelf.rows` — How many waiting things it lists | The rest become one line that opens this window instead. | `5` | a number |
| `shelf.corner` — Which corner it opens in | Before you have dragged it somewhere else. Beside the dot means the dot's own corner, where it opens above the dot rather than covering it. | `dot` | Beside the dot / Top right / Top left / Bottom right / Bottom left |
| `shelf.hush_notifications` — Hide the message cards while the panel is open | The same messages are already listed on the panel. Nothing is marked as seen and no reminder is lost. | on | on / off |

## Privacy

### What May Leave This Pc

Six gates that open only through their consent cards, and two switches: the weekly update check and offline mode.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `privacy.cloud_text` — Text to the cloud | What you dictated or selected may go to Groq or Google under your own key, for the repair pass, punctuation, translation, lookup and the second reading. Opens only through its card, the first time a feature needs it. | off | on / off |
| `privacy.cloud_audio` — Recordings to the cloud | What you said, as audio, may go to Google or Groq for transcription. Opens only through its card. | off | on / off |
| `privacy.cloud_screenshots` — Screen pictures to the cloud | The part of the screen you asked about may go to Groq or Google. Opens only through its card. | off | on / off |
| `privacy.account` — An anonymous account | For problem reports you choose to send. Opens only through its card. | off | on / off |
| `privacy.report_upload` — Sending problem reports | Only what the preview showed. Opens only through its card. | off | on / off |
| `privacy.settings_sync` — Syncing settings | Not built yet. | off | on / off |

### Switches

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `privacy.update_check` — Look for a newer version weekly | One request to GitHub, carrying no identifier. | on | on / off |
| `privacy.offline` — Offline mode | Refuse every connection except this computer's own — Ollama, the phone, the hook — whatever the gates above say. Dictation keeps working. | off | on / off |

## Phone

### Dictating From The Phone

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `server.enabled` — Dictate from the phone | The phone keyboard sends its recordings here, over your own private network. | off | on / off |

### The Phone

Dictate from your phone and let this computer do the listening, so you keep the Hebrew model.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `server.host` — Which address it answers on | Empty means your own private network, so nothing on the house network can reach it. | (empty) | text |

## The app

### Keeping The Computer Awake

The app holds the machine awake while it runs, and one key puts the screens out without locking anything.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `awake.hold` — Hold the computer awake | While the app is running the machine will not fall asleep on its own timer. The screens may still go dark. | on | on / off |
| `awake.enabled` — The screens key works | Off, the key does nothing; the button in this window still turns the screens off. | on | on / off |
| `awake.screens_off_again_s` — Put the screens out again after, in seconds | The mouse moving after you press the key wakes them straight back up, so it does it once more. | `3` | a number |
| `awake.keep_screens_off_s` — Keep putting them out for, in seconds | While the screens are meant to be off, anything that lights them is undone this long after the last touch. | `10` | a number |
| `awake.pin_timeouts` — Also change Windows' own sleep settings | The old settings are put back when the app closes, or at the next start if it did not get the chance. | off | on / off |

## Keys — המקשים

אלה המקשים שדסק-איט מאזין להם; מקום Keys מציג אותם על מקלדת מצוירת ומאפשר לשנות אותם.

| מפתח | מה זה | ברירת מחדל | אפשרויות |
|---|---|---|---|
| `awake.screens_hotkey` — The screens key | Tap it and the screens go dark and stay dark; tap it again and they come back. Nothing is locked. | `ctrl+alt+n` | text |
| `camera.camera_hotkey` — The webcam key | Tap it and a window opens with the live picture and a shutter under it. | `ctrl+f6` | text |
| `capture.capture_hotkey` — The screenshot key | Tap it and the screen freezes so you can drag a box, or hold Shift and lasso a shape. | `win+shift+s` | text |
| `capture.record_hotkey` — The screen recording key | Tap to start recording a part of the screen, tap again to stop. | `ctrl+f12` | text |
| `correct_hotkey` — The teach-a-word key | Fix a word where it landed, tap this, and it learns the correction for next time. | `ctrl+f9` | text |
| `english_hotkey` — The English-only key | A second key that declares the recording English before you speak, instead of letting the app work it out. | (empty) | text |
| `hotkey` — The dictation key | Hold it, speak, and let go: your words land where the cursor is. | `right ctrl` | text |
| `latch_hotkey` — The lock-on key | Tap it while still holding the dictation key and the recording stays on after you let go. | `left` | text |
| `lookup_hotkey` — The look-up key | Select a word, tap this, and a small box says what it means without changing anything on screen. | `ctrl+f8` | text |
| `notify.dismiss_hotkey` — The dismiss-everything key | Tap it and every card goes away and is marked as seen, wherever the mouse happens to be. | `ctrl+alt+m` | text |
| `pause_hotkey` — The pause key | Tap it and every key here goes quiet; tap it again and they all come back. | `insert` | text |
| `problems.report_hotkey` — The report key | Tap it and a box opens over whatever is in front, wherever the mouse is. | `ctrl+alt+r` | text |
| `punctuate_hotkey` — The punctuation key | Tap it to put commas and full stops into the words already at the cursor, without changing any of them. | `ctrl+f2` | text |
| `shelf.shelf_hotkey` — The panel key | Tap it to open the panel beside the dot; tap it again, or press Escape, to close it. | `ctrl+alt+d` | text |
| `translate_hotkey` — The translate key | Tap it to turn the words already at the cursor into another language. | `f8` | text |
| `visual_qa.visual_qa_hotkey` — The ask-the-screen key | Tap it and the screen dims so you can drag a box over what you want to ask about. | `ctrl+f10` | text |
