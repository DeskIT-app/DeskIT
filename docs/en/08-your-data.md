---
title: 8. Your data
---

[עברית](../he/08-your-data) · English

# 8. Your data

**The two-sentence version.** Everything DeskIT keeps about you is in one folder,
`%LOCALAPPDATA%\DeskIT`, and the only things outside it are your cloud keys in Windows
Credential Manager and, if you chose it, the Start-with-Windows entry. Delete the folder and
DeskIT has forgotten you.

## The folder

Paste `%LOCALAPPDATA%\DeskIT` into the File Explorer address bar. **Settings > The app**
opens each of these with a button:

| what | where | notes |
|---|---|---|
| what you changed | `settings.toml` | only the settings that differ from the defaults; the defaults and the help for every key are in `defaults.toml` beside the program |
| facts about this PC | `state.json` | the microphone, the dot's position, the tier, whether the wizard ran |
| your consents | `consent.json` | one row per cloud gate you opened, with the version of the terms you saw |
| learned words | `vocab.json` | the pairs you taught it |
| the second reading's proposals | `review.json` | |
| your reports | `problems.json`, `problems\` | on this PC unless you sent one |
| everything you said | `logs\transcripts.log` | every dictation, translation and lookup, for the days you set |
| the app's log | `logs\app.log` | no transcripts in it — what a support request may include |
| every connection | `logs\network.log` | the Network place reads this |
| the last recordings | `audio\recent`, `audio\pending` | recent: the last N for teaching; pending: a dictation that waits for the model |
| the Hebrew model | `models\` | 1.62 GB; delete it and Home offers the download again |
| NVIDIA's libraries | `packs\` | the GPU pack, if you installed it |
| screenshots and clips | `captures\` | |
| the phone's token | `secrets\` | encrypted with Windows' own DPAPI for your account |

## How long things are kept

> Audio: the last 50 recordings · History: 30 days · Learned words: until you forget one · Reports: on this PC until you delete them · Lookups: the last 500 answers, on this PC · The speech model: until you delete it · Nothing on any server unless you pressed Send.

The numbers are settings: `vocab.keep_audio`, `history.keep_days`, `lookup.cache_entries`
on the Settings page, and `history.keep_days = 0` turns the history off.

## Deleting

- **One thing:** open the folder from **Settings > The app** and delete the file — DeskIT
  makes a new, empty one. The model: delete `models\` while DeskIT is closed, or use
  **Delete the model** on **Settings > Speed**.
- **Everything:** close DeskIT and run, from the install folder
  (`%LOCALAPPDATA%\Programs\DeskIT`):

  ```
  python\python.exe app\main.py --reset-data --yes
  ```

  It removes the learned words, history, recordings, proposals, reports, caches and logs and
  keeps `settings.toml`, `state.json` and your keys.
- **Uninstalling** asks "Remove my data too?" — Yes runs the same reset and removes the
  Start-with-Windows entry; the default is to keep.
- **Keys:** **Settings > Privacy > YOUR CLOUD KEYS > Remove**, or delete `DeskIT/groq` and
  `DeskIT/gemini` yourself in Control Panel > Credential Manager.
- **Claude Code's hook lines:** the switch under **Settings > The app** removes the two lines
  from `~/.claude/settings.json`.

## Moving to another PC

Copy the folder (`%LOCALAPPDATA%\DeskIT`) into the same place on the other PC after installing
DeskIT there. Keys are never in the folder: paste them again. `state.json` names this PC's
microphone and tier; delete it on the other PC and the wizard runs once more.
