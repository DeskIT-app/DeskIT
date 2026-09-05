---
description: Read every open problem report, write the weekly summary, the deep plan and the archive, ask about what you did not understand, then close only what you did. Fixes nothing.
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Weekly review of the problem reports

You are running unattended. Nobody is at the keyboard, there is no terminal to
print to and no question you can ask interactively. Everything you need is
below or on disk.

**This run produces documents and stops. It fixes nothing.** No code change, no
config change, no test run, no commit. The owner reads the summary, discusses
it, answers whatever you asked, and only if he approves does the work happen
later in a normal session. If you find yourself editing a `.py` file you have
misread this command.

**The honesty rule, which outranks everything else here.** In his words:

> "if you did not understand the bug or you did not find the bug that I was
> talking about, don't guess — ask me. Leave it as a question, and when I look
> at all the planning I will answer your question and accept or not accept
> your plan."

So: a report you cannot explain from its evidence gets a **question**, not a
theory. It stays open. The repo's standing rule is *measure, don't assume, and
write the measurement down* (see the `diagnose-with-evidence` skill), and a
plan that guesses is worse than a plan that asks, because he will act on it.

Working directory is the repo root. Every path below is relative to it.

---

## 0. Read the store, and the questions you already asked

The reports live in `problems.json`, read through `problems.py`. Use the repo's
own interpreter, never a system python:

```
.venv\Scripts\python.exe -c "import json,pathlib,problems;s=problems.Store(pathlib.Path('problems.json'));print(json.dumps(s.items(problems.OPEN),ensure_ascii=False,indent=2))"
```

`Store.items(status)` returns newest first. The keys on an item are
`id, at, where, kind, text, status, resolved, by, dictation{}, shot, env{}`.
`kind` is one of `wrong`, `broken`, `slow`, `idea`, `other`.

Then read **`problems/weekly/asked.json`**, which is this routine's own memory
of what it has already asked about. It may not exist yet; that is the first
run. Shape:

```json
{"version": 1,
 "asked": {"<report id>": {"date": "2026-09-12", "question": "<the one sentence>"}}}
```

This file exists because you **must not re-ask the same question every week.**
A report already in `asked` is a carry-over: the summary says *still waiting on
your answer from `<date>`* and repeats the question verbatim, and you do not
re-derive it or reword it. It is his question to answer, not yours to rephrase.

*Why a sidecar and not a field on the report: `problems.py` is not this
routine's to change and its schema is asserted by `tests.py`. There is no
public API to edit a report's text — only `Store.resolve`, which sets
`status`/`resolved`/`by` — and stamping `by` on a still-open report would print
routine bookkeeping onto the row the dashboard draws (`dashboard.py` renders
`item["by"]`). So the routine keeps its own state in its own folder.*

Set `DATE` to today's local date as `YYYY-MM-DD`.

### When to write nothing

- **No open reports at all → stop here.** Write no file, create no folder for
  the date, send no notification. A quiet week must leave no trace: a document
  he opens to find nothing in it is worse than no document, and a card for an
  empty review teaches him to ignore the card.
- **Open reports, but every one of them is already in `asked` and nothing has
  changed → write only the summary**, as a short standing-questions note (§2,
  questions block plus the carry-over lines, nothing else). No new plan, no new
  archive — there is nothing new to plan or archive. The card says answers are
  wanted. Do not manufacture a document to look busy.

---

## 1. Gather the evidence, then rule on each report

For each open report, collect what actually exists:

- **The screenshot.** `item["shot"]` is a path relative to the repo root
  (`problems/<id>.jpg`). **Open it with the Read tool and look at it.** It is
  the difference between a report about the Recordings tab and a report about
  whatever was really on the screen. `problems.shot_path(store, item)` resolves
  it if the relative path gives you trouble. Most reports have no screenshot;
  that is ordinary, not a failure.
- **The recording.** `item["dictation"]["wav"]` is a pinned copy under
  `problems/`, and it outlives the `recent\` ring on purpose. **You cannot
  listen to it.** Do not pretend otherwise. What you CAN read is the sidecar
  beside it (`problems/<dictation.id>.json`) and the `dictation` block:
  `seconds`, `backend`, `language`, `attempts`, `last_error`, and `words` — a
  list of `[word, start, end, confidence]`. A low confidence on exactly the
  words he complains about is evidence; a high confidence on an invented tail
  is different evidence and means something else. Say which you found. The
  wav's own size and duration are checkable and sometimes decisive — a report
  about a lost sentence whose recording is 0.2 s is a different bug from one
  whose recording is 30 s.
- **Raw versus final.** `dictation["raw"]` is what the decoder produced,
  `dictation["text"]` / `["final"]` what he got. If they are equal, nothing
  downstream touched it and polish/vocab/punctuate are not suspects. If they
  differ, the difference IS the suspect and you must quote both.
- **The settings that explain it.** `item["env"]`: `backend`, and the real
  model name (`local_model` / `english_model` — write the actual string, never
  "the local model"), `beam_size`, `vocab_enabled`, `vocab_replace_after_hits`,
  `polish_when`, `punctuate_auto`, `review_enabled`, `max_seconds`, `branch`,
  `python`.
- **The second reading.** `dictation["id"]` is the `recent\` wav stem and it is
  **also the `id` in `review.json`**, so a report about a bad transcript can be
  joined to the review record for that same dictation. Look it up whenever the
  report is about a wrong transcription:

  ```
  .venv\Scripts\python.exe -c "import json,sys;d=json.load(open('review.json',encoding='utf-8'));print(json.dumps([r for r in d['items'] if r.get('id')==sys.argv[1]],ensure_ascii=False,indent=2))" <dictation.id>
  ```

  A joined entry gives you `proposed`, `changes[]` (each with
  `before/after/why/family/support`), `agree`, `decodes`, `llm`, and `status` —
  whether the second reading saw the same problem and whether he accepted or
  rejected its fix. A review that already caught the word he complains about
  and was rejected is a different problem from one that never saw it.
- **The code he is describing.** Grep for it. A report about a feature is
  answerable only if you found the code path that implements it. If you cannot
  find any code that matches what he describes, that is itself a finding, and
  it usually means either he is describing something that does not exist yet
  (which makes it an `idea`, whatever he filed it as) or you have misunderstood
  him (which makes it a question).
- **Nothing at all.** A report can be one typed line with an empty `dictation`
  and no shot. That is a legitimate report. Its evidence section says, plainly,
  that there is none.

**Group reports that are obviously the same underlying problem.** Same
`dictation.id`, or the same complaint on the same surface within the week. Say
which ids you merged, and treat them as one entry in the summary and one
section in the plan. Do not merge on a hunch: two reports about "wrong text" on
different dictations with different evidence are two problems.

### The verdict — exactly one per report or group

Every report gets one of these three, named in both documents:

- **`understood, cause established`** — you can name the cause and quote the
  code or the data that shows it. This report can be planned and fixed.
- **`understood, cause not yet established`** — you know what he means and can
  reproduce or at least locate it, but the evidence does not yet single out a
  cause. The plan says what measurement would settle it. This is a normal,
  respectable verdict; do not upgrade it to make the plan look stronger.
- **`could not find it — question for you`** — you do not understand the
  report, or you understand it and could not find the thing he describes, or
  the evidence contradicts it. **Write no root cause and no fix.** The plan
  entry says what you looked at and what you ruled out, and then stops.

A report of kind `idea` is the one exception: there is no bug to diagnose, so
it gets the verdict **`an idea — needs your decision`** instead of one of the
three. Confirm the feature does not already exist (grep for it and say so), lay
out what building it would take, and stop there. Do not design it in detail
before he has said yes.

**Anything waiting on him stays `OPEN`** — questions and undecided ideas alike.
An idea closed on his behalf is a feature request you deleted, and the whole
point of the Problems tab is that it holds what still needs him. Ideas
therefore go into `asked.json` too, with the go/no-go question as their
question, so next week reports *still waiting on your decision from `<date>`*
rather than pitching it again.

Reach for the third verdict when: the pinned recording does not contain what
the report is about (silence, a different sentence, the wrong length); the text
describes a behaviour no code path you can find produces; `raw` and `final` are
identical and correct while he says the output was wrong; the screenshot shows
a different surface than `where` claims; or you simply cannot tell what he
means. Those are all reasons to ask, not to theorise.

### Writing a question he can answer in one sentence

A question must name the report, say what is unclear or what could not be
reproduced, and ask **the one specific thing that would unblock it.**

- Bad: "Can you clarify what you meant?" — that costs him the whole thinking.
- Good: "the recording is 2.4 s of silence — were you dictating into a
  different window, or did the key not catch?"

Offer the two or three alternatives you actually considered, so answering is a
choice and not an essay. One question per report; if you have three, you have
not done the evidence work yet.

---

## 2. Write `problems/weekly/<DATE>-summary.md` — the short one

**This is the only document he actually reads. It must be skimmable in under a
minute.** Write it in **Hebrew**; keep file names, symbol names, model names,
paths and ids in English. (The repo's docs are English; this is his personal
weekly note.)

**The open questions come first, at the top, before the report lines.** They
are the thing that needs him; everything else is only ready to read. Lead with
the count. If there are no questions, say so in one line — that is good news
and he should see it immediately.

Then one line per report or group, each saying two things and no more: **what he
reported, and what is planned about it** — plus its verdict as a short marker.
Not the cause, not the evidence, not the files; those are in the plan. A line
that needs a second line is too long.

Shape:

```
# סיכום שבועי — <DATE>

<N> דיווחים · <k> קבוצות · <q> ממתינים לתשובה שלך · פירוט מלא ב-<DATE>-plan.md

## ❓ צריך תשובה ממך (<q>)

- **<id>** · "<what he reported, 6-8 words>" — ההקלטה 2.4 שניות של שקט. הכתבת לחלון אחר, או שהמקש לא נתפס?
- **<id>** · (נשאל ב-12 Sep, עוד ממתין) "<the same question, verbatim, not reworded>"

## הדיווחים

- ✅ **wrong** · הסוף של המשפט המציא מילים → מבטלים hotwords מה-prompt של המפענח ומודדים שוב
- 🔍 **slow** · ההדבקה נתקעת → מקור לא אושר; מודדים את זמן ה-clipboard לפני שנוגעים בקוד
- ❓ **other** · <report that is waiting on an answer, one line, no plan>
- 💡 **idea** · לחיצה אוטומטית על try again → צריך החלטה שלך לפני שמתכננים

## מה צריך ממך
- <the one or two decisions only he can make, beyond the questions above,
  or "רק התשובות למעלה">
```

Markers: `✅` cause established, `🔍` understood but cause open, `❓` waiting on
his answer, `💡` an idea that needs his decision rather than a diagnosis.

A carry-over question is marked with the date it was first asked and repeated
**verbatim** from `asked.json`. Never reword it — he may already have half an
answer in mind against the old wording.

---

## 3. Write `problems/weekly/<DATE>-plan.md` — the deep one

For whoever does the work, which may be a fresh session with zero context.
Follow the house style: **`PARALLEL_FEATURES_PLAN.md` in the repo root is the
template for exactly this document — read it before you write.** What to copy:

- The goal at the top **in the owner's own words**, quoted.
- **Numbered rules (`R1`, `R2`, …), stated so they can be argued with before
  any code moves.** This is the point of the document: he reads the summary and
  discusses, and the rules are what he is discussing.
- A section per problem with the evidence that establishes it — **every claim
  either quoted from the code / the data, or marked `TODO`.**
- The work file by file, with the functions named.
- An explicit list of what is deliberately not being fixed, so a later reader
  does not mistake a decision for an oversight.

Required sections:

```
# WEEKLY <DATE> — plan

Goal, in the owner's words: **"<quote from his report>"**

Verdicts: <n> cause established · <n> cause open · <n> waiting on his answer.
Nothing in §4 gets a fix until he answers.

## 0. What the evidence says (per problem)
## 1. The rules this lands on
## 2. The work, file by file
## 3. What the evidence does not establish
## 4. Open questions — no plan until answered
## 5. What is deliberately NOT fixed here
## 6. Done means
```

For each problem with verdict `understood, *`, four things:

1. **Files and functions to touch** — `module.py`, `Class.method`, named. Grep
   for them and quote the line you mean. A plan that says "somewhere in
   `main.py`" is not a plan.
2. **What could break** — which existing behaviour or test the change contests.
   The repo's tests are one file, `tests.py`; name the test that asserts the
   thing you are about to change, so the contract change is visible up front.
3. **What to measure afterwards** — the number that would show it worked, and
   where it comes from. `recent\` holds a real labelled set; `review.json`
   holds accept/reject history. "It should feel better" is not a measurement.
4. **The verdict**, repeated, so a reader of §2 alone cannot mistake a
   `cause not yet established` entry for a settled one.

**§4 is where the honesty rule lands.** One entry per report with the third
verdict, and each entry has exactly three parts and no fourth:

- **What he reported** — quoted in full.
- **What was checked, and what it ruled out** — the wav, the sidecar, the
  screenshot, the review join, the greps, each with what it showed. This is the
  part that proves the question is not laziness.
- **The question**, in one sentence, identical to the one in the summary.

No root cause. No candidate fix. No "probably". If you have a theory you could
not test, it belongs in §3 as a stated unknown with the measurement that would
settle it — not in §4 dressed as an answer.

**The hard rule: the plan must never claim a cause it has not shown evidence
for.** `## 3` being long is a good plan. `## 3` and `## 4` both being empty on
a week with a bare one-line report is a lie, and he will catch it.

---

## 4. Write `problems/weekly/<DATE>-reports.md` — the archive

Every report you are about to close, **in full**, so the record survives
independently of `problems.json`. This is the reason closing is safe.

**Reports waiting on an answer are NOT closed, so they are not archived here.**
They stay in the store, which is where their record already lives. Note them at
the bottom of the archive as carried over, with their ids, so a reader of this
file knows the week had more in it than what was archived.

Per archived report:

- `id`, `at`, `where`, `kind`, `status` as they were before closing, and the
  verdict this run gave it.
- His text, complete and unedited. Never trim it.
- The full `dictation` block including `raw`, `text`, `seconds`, `backend`,
  `attempts`, `last_error`, and the `words` list.
- The full `env` block.
- **The evidence file paths**, verbatim: `problems/<id>.jpg`,
  `problems/<dictation.id>.wav`, `problems/<dictation.id>.json`, and the
  `review.json` id when it joined.
- A one-line description of what the screenshot showed, since a later reader
  may have the path but no way to look at it.

The test of this file: **could someone reconstruct the report from it with
`problems.json` deleted?** If not, it is not finished.

---

## 5. Record the questions, then close only what you understood

### 5a. Write `problems/weekly/asked.json`

Merge, never overwrite. Keep every existing entry whose report is still open —
including its **original date and original wording** — and add an entry for
each new question with today's `DATE`. Drop entries for reports that are no
longer open (he answered, or it was closed some other way). Write it the same
way the repo writes json: a temp file beside it and one rename, so a crash
mid-write cannot leave a half file.

### 5b. Close, in this order, and only these reports

**Order matters and this is the step that can lose him a week.** Write all the
documents first. Then verify they are on disk and non-empty — actually stat
them, do not assume the Write succeeded. Only then close.

If any write failed, **stop and leave every report `OPEN`.** A failed Saturday
that leaves the reports open costs him nothing; one that closes them and then
fails costs him the week, and the reports are the only place some of that
information exists.

**Close only reports whose verdict was `understood, *` AND which are not
waiting on him.** A report with an unanswered question is not resolved, and
neither is an undecided idea, so both stay `OPEN` and stay in the dashboard's
Problems tab — otherwise he would lose the tab entry for exactly the reports
that still need him, which is the opposite of asking. `understood, cause not
yet established` **is** closed: the plan carries the measurement, and nothing
is waiting on him.

```
.venv\Scripts\python.exe -c "import pathlib,sys,problems;s=problems.Store(pathlib.Path('problems.json'));print([(i,s.resolve(i,problems.CLOSED,by='weekly')) for i in sys.argv[1:]]);problems.digest(s,pathlib.Path('problems.md'))" <id> <id> ...
```

`resolve` returns `False` when nothing changed — no such id, or the file could
not be written. Check every returned value and report any `False` rather than
assuming it worked. `problems.digest` then regenerates `problems.md` from the
store, so the digest and the tab agree.

**Why closing is safe, and say this in your own output so a future reader is
not frightened by it:** `Store._trim` only ever drops JSON rows, and only
resolved ones — open reports are never trimmed. It never unlinks anything, so a
pinned `.wav` or `.jpg` under `problems/` survives the close, and survives the
row aging out of the store 200 resolutions later. Nothing is deleted by this
routine, ever. The archive plus the pinned files are the permanent record; the
store row is only what makes the Problems tab show it as open.

---

## 6. Tell him it is ready — and whether he is needed

The repo already has the door. Do not invent a new mechanism, do not write to
`notify.json`, do not start a server. `notify_hook.py` is a stdlib-only CLI that
posts to `POST /notify` and **exits 0 in silence when the app is not running**,
so calling it is always safe.

One card. If anything is waiting on him, the card must **lead with that**,
because a question is a thing he has to do and a document is only a thing he
can read:

```
.venv\Scripts\python.exe notify_hook.py --source weekly --kind input --title "הסקירה השבועית — <q> שאלות מחכות לך" --body "<N> דיווחים · problems/weekly/<DATE>-summary.md"
```

With no questions, it is `--kind done` and the title is just that the review is
ready:

```
.venv\Scripts\python.exe notify_hook.py --source weekly --kind done --title "הסקירה השבועית מוכנה" --body "<N> דיווחים · problems/weekly/<DATE>-summary.md"
```

`--kind` must be one of `done`, `input`, `error`, `info` (`notify.KINDS`);
`input` is the one that means the card is waiting for him. Send the card only
after the documents are written and the closes are done — a card that arrives
before the document exists sends him to an empty folder.

---

## 7. What you print

`problems/weekly/` is inside a gitignored folder, on purpose: these reports are
his and they stay on this machine. So the run log is the only trace, and your
final output goes into it. A few lines:

- how many reports, how many groups, how many of each verdict, the file paths;
- every id you closed, and any `resolve` that returned `False`;
- every id left open with a question, and whether the question is new or a
  carry-over;
- anything you could not gather evidence for, named — this is the part a future
  reader needs, because it is what next week has to capture.

Then stop. Do not begin any of the work you just planned, and do not answer
your own questions.
