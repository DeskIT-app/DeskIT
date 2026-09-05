---
description: Build the one report he has already answered, ask one multiple-choice question with as many real options as it has about the ones he has not, write the summary, the plan and the archive, and never answer your own question.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Weekly review of the problem reports

You are running unattended. Nobody is at the keyboard, there is no terminal to
print to and no question you can ask interactively. Everything you need is
below or on disk. Working directory is the repo root; every path below is
relative to it.

## What this run is

This routine used to produce documents and stop. It fixed nothing, and the
owner would then open a chat, answer the questions it had asked, and have that
chat write the code. He has decided against that shape, in these words:

> "Next week this routine happens again — it checks the things I reported,
> investigates them, understands what it can fix without me clarifying exactly
> what I wanted. What it can fix, it fixes. What it cannot, it asks me the
> simplest possible question, which I answer when I wake up in the morning, and
> from there it continues and writes the code. I don't want to open a chat every
> time to answer the questions and then have the routine write the code — I want
> the routine to do everything. I want it to be full autonomous."

So the run has **two jobs**, and which one a report gets is decided by exactly
one fact: **whether his answer to it is already on disk.**

- **He has answered it → build it.** His recorded answer *is* the approval.
  There is no second gate, no "confirm before starting", no waiting for a chat.
  A recorded answer that sits unbuilt for a week is the failure this change was
  made to remove.
- **He has not answered it → investigate it, then ask.** One question, as many
  real options as the question actually has, and no code. It stays open.

Everything else here — the evidence work, the verdicts, the three documents,
the archive — is unchanged, because the reason the routine could be trusted to
write documents is the same reason it can now be trusted to write code: it
never claims more than the evidence shows.

---

## The two rules that outrank everything else in this file

### 1. The honesty rule, in his words

> "if you did not understand the bug or you did not find the bug that I was
> talking about, don't guess — ask me. Leave it as a question, and when I look
> at all the planning I will answer your question and accept or not accept
> your plan."

A report you cannot explain from its evidence gets a **question**, not a
theory. It stays open. The repo's standing rule is *measure, don't assume, and
write the measurement down* (see the `diagnose-with-evidence` skill), and this
rule matters MORE now than it did when the routine only wrote prose, not less:
a guess used to cost him a paragraph he could argue with, and now it costs him
a branch full of code written against a misreading.

### 2. Never answer your own question

**You may build only an answer he wrote. You may never write an answer.**

Nothing in this run may call the questions store's `answer(...)` — not to
record what you inferred, not to fill in an obvious blank, not to save him a
keystroke on a question whose answer you are certain of, not "provisionally so
the build can proceed". `PENDING` is a wall, and the only hand that moves a
question past it is his, from inside DeskIT.

If you are ever about to reason *"he would obviously pick option 2"* — stop.
That sentence is the entire failure mode this design exists to prevent. Picking
for him turns a routine he can leave running into a routine that writes code he
never asked for, and one such branch would cost the feature his trust
permanently. An unanswered question costs him thirty seconds on Sunday morning.
Those are not comparable prices.

**A short option list makes this temptation worse, not better.** A two-option
question is one where you have already narrowed the field to two things you
would both build, and it is exactly there that *"there are only two, and one of
them is clearly right"* starts to sound like reasoning instead of the
prohibited move it is. The number of options has no bearing on this rule. Two
options, one option's worth of doubt, a question you are ninety-nine per cent
sure of — `PENDING` is still a wall, and the only hand that moves a question
past it is his.

---

## 0. Read the stores

### 0a. The reports

The reports live in `problems.json`, read through `problems.py`. Use the repo's
own interpreter, never a system python:

```
.venv\Scripts\python.exe -c "import json,pathlib,problems;s=problems.Store(pathlib.Path('problems.json'));print(json.dumps(s.items(problems.OPEN),ensure_ascii=False,indent=2))"
```

`Store.items(status)` returns newest first. The keys on an item are
`id, at, where, kind, text, status, resolved, by, dictation{}, shot, env{}`.
`kind` is one of `wrong`, `broken`, `slow`, `idea`, `other`
(`problems.KINDS`).

### 0b. The questions, which are now a real store

Questions no longer live in prose or in a sidecar of bookkeeping. They live in
`questions.py`, which is shaped like `problems.py`: `Store(path)` with
`items(status)`, `get`, `ask(report_id, question, options)`, `answer(...)`,
`mark_built(ident, branch, note)`, `drop`, `for_report`, `stamp`; statuses
`PENDING`, `ANSWERED`, `BUILT`, `DROPPED`; and the floor and ceiling on the
option count, `OPTIONS_MIN` and `OPTIONS_MAX`.

**Read those two constants; never carry a number for them in your head.** The
store is the authority on how many options a question may have, the print in
the next block hands you both, and the range is there so a question can be the
size it actually is. Every entry in `options` is a real, pickable choice —
**there is no open option and no "something else" slot.** The card he answers
on always carries a free-text box under the buttons, so a slot never has to be
spent on an escape hatch. That is also why the floor is above one: two genuine
choices are a choice, and one is not.

An answered item carries two fields, `choice` and `text`, and it is normal for
both to be filled. §3 says what to do with that; the short version is that the
typed words are the answer and the pick is where it started.

Its file is `questions.STORE_NAME` if the module defines that constant (the way
`problems.py` defines `STORE_NAME = "problems.json"`), and otherwise
`questions.json` beside `problems.json` in the repo root. Resolve it that way
rather than hard-coding a name.

**First, prove the module is there.** It is the spine of both jobs, so a run
that cannot import it must do nothing at all rather than half of something:

```
.venv\Scripts\python.exe -c "import questions;print('ok',questions.PENDING,questions.ANSWERED,questions.BUILT,questions.DROPPED,questions.OPTIONS_MIN,questions.OPTIONS_MAX)"
```

If that fails, **write no file, close nothing, build nothing.** Send one card
with `--kind error` naming the missing module (§8), print why, and stop. A
Saturday that does nothing costs him nothing; a Saturday that asks questions
into a store that does not exist loses them silently.

### 0c. Migrate the old sidecar, once

`problems/weekly/asked.json` was the routine's previous memory. It holds three
real entries, two of them already answered by the owner and waiting to be
built — which is what makes this run productive rather than a re-ask. Bring
them across:

```
.venv\Scripts\python.exe -c "import pathlib,questions;s=questions.Store(pathlib.Path(getattr(questions,'STORE_NAME','questions.json')));print(questions.import_asked(s,pathlib.Path('problems/weekly/asked.json')))"
```

Call it every run. It is a migration and it is idempotent; calling it on an
already-migrated store must be a no-op, and if it is not, that is a bug to
report in your output, not to work around. **Do not delete `asked.json`
afterwards.** This routine deletes nothing, ever. After the migration the store
is the memory and the sidecar is only history.

Then read the store, all four statuses, so you know what is pending, what he
answered, and what has already been built:

```
.venv\Scripts\python.exe -c "import json,pathlib,questions;s=questions.Store(pathlib.Path(getattr(questions,'STORE_NAME','questions.json')));print(json.dumps({k:s.items(k) for k in (questions.PENDING,questions.ANSWERED,questions.BUILT,questions.DROPPED)},ensure_ascii=False,indent=2,default=str))"
```

Set `DATE` to today's local date as `YYYY-MM-DD`.

### 0d. When to write nothing

- **No open reports and no answered questions → stop here.** Write no file,
  create no folder for the date, send no notification. A quiet week must leave
  no trace: a document he opens to find nothing in it is worse than no
  document, and a card for an empty review teaches him to ignore the card.
- **Every open report already has a `PENDING` question and nothing has changed
  → write only the summary**, as a short standing-questions note (§5, questions
  block plus the carry-over lines, nothing else). No new plan, no new archive —
  there is nothing new to plan or archive. The card says answers are wanted. Do
  not manufacture a document to look busy.

**A question that is already `PENDING` is never asked again.** The store's
status does the job the old `asked.json` bookkeeping did: the summary says
*still waiting on your answer from `<date>`* and repeats the question and its
options **verbatim** from the store. Do not re-derive it, do not reword it, do
not "improve" the options. It is his question to answer, not yours to rephrase,
and he may already have half an answer in mind against the old wording.

Verbatim beats every rule in §2 for a question already in the store. A migrated
carry-over may still end in an old "משהו אחר" line; repeat it as it is rather
than editing the store to match today's shape. The rule against writing an open
option governs what you *ask*, not what you *quote*.

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
  code or the data that shows it. This report is ready to be built the moment
  he has chosen which fix he wants.
- **`understood, cause not yet established`** — you know what he means and can
  reproduce or at least locate it, but the evidence does not yet single out a
  cause. The plan says what measurement would settle it. This is a normal,
  respectable verdict; do not upgrade it to make the plan look stronger, and
  above all do not build against it.
- **`could not find it — question for you`** — you do not understand the
  report, or you understand it and could not find the thing he describes, or
  the evidence contradicts it. **Write no root cause and no fix.** The plan
  entry says what you looked at and what you ruled out, and then stops.

A report of kind `idea` is the one exception: there is no bug to diagnose, so
it gets the verdict **`an idea — needs your decision`** instead of one of the
three. Confirm the feature does not already exist (grep for it and say so), lay
out what building it would take, and stop there. Do not design it in detail
before he has said yes.

Reach for the third verdict when: the pinned recording does not contain what
the report is about (silence, a different sentence, the wrong length); the text
describes a behaviour no code path you can find produces; `raw` and `final` are
identical and correct while he says the output was wrong; the screenshot shows
a different surface than `where` claims; or you simply cannot tell what he
means. Those are all reasons to ask, not to theorise.

**Anything waiting on him stays `OPEN`** — questions, undecided ideas, and
anything you built and he has not yet reviewed. An idea closed on his behalf is
a feature request you deleted, and the whole point of the Problems tab is that
it holds what still needs him.

---

## 2. The question: as many real choices as it has, over a text box

Every open report he has not answered gets **exactly one** question in the
store. One question per report; if you have three, you have not finished the
evidence work.

```
.venv\Scripts\python.exe -c "import pathlib,sys,json,questions;s=questions.Store(pathlib.Path(getattr(questions,'STORE_NAME','questions.json')));a=json.load(open(sys.argv[1],encoding='utf-8'));print(s.ask(a['report_id'],a['question'],a['options']))" <a json file you wrote>
```

Pass it through a small JSON file rather than a command line: the questions and
the options are Hebrew, and a console codepage must not be what mangles them.

### The question itself

A question names the report, says what is unclear or what could not be
reproduced, and asks **the one specific thing that would unblock it** — the
simplest possible question, in his words. It is one sentence.

- Bad: **"Can you clarify what you meant?"** — that hands him back the whole
  thinking, which is the work he asked the routine to do.
- Good: **"the recording is 2.4 s of silence — were you dictating into a
  different window, or did the key not catch?"** — it names the measurement, it
  shows he was heard, and it can be answered by pointing at one of two things.

That good example is the standard. Hold every question you write against it.

### The options are the hard part

**Every entry in `options` is a real choice he could pick and you would carry
out. There is no open option.** The card he answers on always carries a
free-text box under the buttons — it is there whatever the options are, and it
is there when there are no options at all — so the run never has to spend a
slot on an escape hatch, and it must not. An option that reads "something else,
I'll write it" spends a line of a small card telling him about a box he is
already looking at.

**No option may point at the box either.** Do not append "או תכתוב לי" to the
last one, do not close the question with an invitation to type, and do not
mention the field anywhere. He knows it is there. Every word about it is a word
he reads instead of the choice, and it is exactly the line he had removed.

### How many — write the size the question actually is

The count runs from `OPTIONS_MIN` to `OPTIONS_MAX` as the store defines them
(§0b), and that range exists so the question can be its own size, not so you
can aim at the top of it. In his words:

> "adaptive, however many it needs, so it does not have to invent options just
> to fill three slots"

**Padding is the failure mode, and it is not a harmless extra.** An option
invented to reach a quota is a line he has to read, parse and reject before he
can answer the real question, and it damages the options around it: two clean
alternatives read as *the two ways this can go*, while the same two beside a
filler read as *three guesses, one of which is obviously weak*. So an option
that only exists to make the list longer costs him time and costs the question
its clarity. **Two real options beat three where the third is filler.** If you
cannot name a third thing you would genuinely build, you have a two-option
question, and that is a finished question.

**Bad** — two real options and a third that exists to make three:

> ההדבקה נתקעת אחרי תמלול ארוך. מה לעשות?
>
> 1. להאריך את `injector.SETTLE_SECONDS` כך שהחלון יספיק לקבל את ה-clipboard.
> 2. לשלוח את צירוף ההדבקה פעם שנייה כשהחלון לא קיבל כלום.
> 3. להשאיר את זה ולראות אם זה חוזר עוד פעם.

Option 3 is not a fix; it is the run declining the work, dressed as a decision
he made. He now reads three lines to settle a two-way question, and the two
real fixes look like a shrug's worth of alternatives. The same question at its
real size is better in every way:

> 1. להאריך את `injector.SETTLE_SECONDS` כך שהחלון יספיק לקבל את ה-clipboard.
> 2. לשלוח את צירוף ההדבקה פעם שנייה כשהחלון לא קיבל כלום.

If waiting-and-seeing really is one of the things you would do, it is not an
option — it is the verdict `understood, cause not yet established` with a
measurement in the plan (§4 `## 4`), and the question then asks which
measurement he wants first.

### The bar every option set must clear

1. **Each option is a short sentence he could pick in two seconds.** One line.
   An option that needs reading twice is a paragraph wearing a radio button.
2. **They are mutually exclusive.** No "both", no "either of the above", no
   option that is a superset of another. If two options could be true at once,
   his pick tells you nothing.
3. **They are not variations of one idea.** Rewordings of the same plan are not
   a choice; they are a leading question with extra steps, and that is the
   specific way this goes wrong. Two options that differ in wording are one
   option, and one option is below `OPTIONS_MIN` — rewrite the question.
4. **Each option is an action or a fact, not a question.** He is answering, not
   being interviewed again.
5. **Every option must be one you would actually carry out.** A decoy option
   you would refuse if he picked it is a lie in a menu, and so is one you added
   to reach a count.
6. **No option mentions the text box, and none of them is an escape hatch.**
   The box is on the card; the options are for choosing.

**Good** — a real one from this repo, three genuinely different amounts of work:

> יש 21 צלילים ב-`cues.CUES`, ו-11 מהם אותה קווינטה בגבהים שונים ושני זוגות
> רחוקים חצי טון בלבד. מה לעשות?
>
> 1. לבנות סט חדש — לכל צליל אופי אחר, לא גובה אחר.
> 2. להשאיר את הסט ולהרחיק רק את שני הזוגות הקרובים.
> 3. להשתיק את הצלילים שאני לא צריך ולהשאיר חמישה.

Three, because there are three things worth doing here — not because three is a
number. And no fourth line, because the box is on the card.

**Bad** — the same idea three times, so his pick decides nothing:

> 1. לבנות צלילים חדשים.
> 2. לבנות צלילים חדשים עם אופי שונה.
> 3. לבנות את הצלילים מחדש כדי שיהיו שונים אחד מהשני.

### What the options are about depends on the verdict

The question is not always "what did you mean". Once the cause is established,
the thing you actually lack is his choice of fix — so the options carry the
design decision, and answering it is what makes the build legitimate:

| verdict | what the options are |
|---|---|
| `cause established` | the candidate fixes, differing in scope or in what they give up |
| `cause not yet established` | the missing fact, or which measurement he wants taken first |
| `could not find it` | the readings of his report you actually considered |
| `an idea` | build it small / build it fully / do not build it |

Each row says *the* options, not *three* options: however many candidate fixes
there really are, however many readings you really considered. The `idea` row
happens to come out at three most of the time because those three are genuinely
distinct amounts of work — but if "build it small" and "build it fully" are the
same build for a one-line feature, ask two.

In all four cases the free-text box is under them and no option refers to it.

---

## 3. Build the one report he has already answered

An `ANSWERED` question is an approval. Build it — **at most one per run.**

### Read the whole answer — the choice AND the text

An answered item carries two fields and both of them are his:

- `choice` — the index into the stored `options` of the one he picked, or
  `null` when he picked none.
- `text` — what he typed into the card's free-text box, or `""` when he typed
  nothing.

The store keeps both because he uses both. It refuses an answer only when
**both** are empty, which means a pick on its own, typed words on their own,
and **a pick together with typed words** are all complete answers — and the
third is what this section exists for.

**A `choice` and a `text` together mean the text modifies or overrides the
option he picked: his words win.** Building the canned option and filing the
sentence as a comment is how this feature breaks, because it throws away the
only part of the answer he wrote himself. His own example of why he wanted the
box at all is picking *"run before the backup"* and then typing *"actually
after the backup, so that it doesn't…"* — the option carried him most of the
way and the sentence corrected it. The thing to build is the corrected one, not
the one on the button.

So, in this order:

1. Resolve `choice` against the item's stored `options` by index and read the
   option's own text. Never guess the option from the question.
2. Read `text`. Empty, and the picked option is the whole answer — build it.
3. Both present: the option is the starting point and the sentence is the
   instruction. Where they agree, build the option. Where the sentence narrows
   it, reverses it, or adds a condition, **build what the sentence says.**
4. **If the two cannot be reconciled — the sentence contradicts the pick and
   you cannot tell which thing he wants — build nothing and ask again.** One
   new question in the store, quoting both halves of what he said and asking
   which he meant. That costs him one line on Sunday. A branch built on the
   wrong reading of a sentence he took the trouble to type costs him the
   feature's credibility, and you cannot tell from here which way he meant it.
5. `choice` is `null` and `text` is all there is: the sentence is the entire
   answer, and rule 2 at the top of this file applies with full force — if it
   does not authorise a specific change, it is not an approval, and the report
   goes back to being a question rather than a build.

Whatever you build, **quote the whole answer in the plan** — the option's text
and his typed words, both, verbatim from the store — so the diff can be read
against exactly what authorised it.

### 3a. The gate: is an earlier build still waiting on him?

Work lands on a branch named `weekly/<YYYY-MM-DD>`, and it is **never pushed**.
He reviews it and presses Push in the dashboard himself. So a `weekly/*` branch
with no upstream is a build he has not yet dealt with, and that is the signal:

```
git for-each-ref --format="%(refname:short) [%(upstream)]" refs/heads/weekly
```

If any line comes back with an empty `[]`, **build nothing this run.** Say in
the summary and in your output which branch is waiting and which report it
belongs to, ask this week's questions as normal, write the documents, and stop.
One report per run, and no second build until he has seen the first: two
unreviewed branches is how he loses track of what the routine has done to his
repo, and the whole arrangement rests on him being able to see all of it at
once.

If nothing is waiting, take the `ANSWERED` question with the **oldest answer
date** whose report is still `OPEN`. First answered, first built.

### 3b. The branch, before you touch a file

```
git rev-parse --abbrev-ref HEAD
git checkout -b weekly/<DATE>
```

Record the starting branch name — you will return to it. The name matters:
`git branch --list 'weekly/*'` finds every branch this routine has ever made,
which is what keeps its work from being confused with the other unpushed
branches in this repo.

### 3c. The precondition that makes reverting safe

**Before editing a file, prove it is clean:**

```
git status --porcelain -- <path>
```

Empty means clean. **If a file you need is already dirty, do not touch it.**
The tree in this repo routinely carries other sessions' half-finished work, and
an edit on top of it cannot be reverted without destroying theirs. Leave the
report open, write down which file was dirty and which session's change it
looked like, and let next Saturday have it.

### 3d. Build it

Write the code the answer authorises, and only that. Then the gate:

```
.venv\Scripts\python.exe tests_quiet.py
```

**The green state is one failure**, the known machine-flaky
`test_the_process_list_sees_the_processes_it_cannot_open` — the suite prints
`1 FAILED` and exits non-zero and that is still green. **Any other failing test
means the build is reverted**, however plausible the failure looks. You cannot
tell a pre-existing break from one you caused at 4 AM with nobody to ask.

### 3e. Commit only your own files, by path

```
git add -- <exactly the files you edited>
git commit -m "<one line in the repo's voice, then the report id and the answer it came from>"
```

**Never `git add -A`, never `git add .`, never `git commit -a`.** His rule, and
the reason for it is on the branch you are standing on: the tree carries other
sessions' changes, and a sweep would commit their unfinished work under your
message. Stage by path or do not stage.

Then go back where you came from:

```
git checkout <the starting branch>
```

If that checkout fails, **stop touching git.** Say so in the summary and in
your output, leave the tree exactly as it is, and let him sort it out — a
forced checkout would take another session's work with it.

### 3f. Reverting, when the tests say no

The branch is disposable; that is the point of it. Nothing was committed yet,
so:

```
git checkout -- <the files you edited>
git checkout <the starting branch>
git branch -D weekly/<DATE>
```

That is safe precisely because §3c proved those files were clean before you
started, so restoring them restores the branch state and nothing of anyone
else's. Then leave the report `OPEN`, leave its question `ANSWERED` so next
Saturday tries again, and write down in the plan **what broke, which test, and
the exact failure line.** A build that failed with the reason recorded is a
good week's work; a build that failed silently is worse than none.

### 3g. What you never touch

- **`git push`, in any form, ever. No force-push, no `--set-upstream`, no
  pushing a tag.** Pushing is his button, and it is the only thing standing
  between an autonomous routine and a public mistake.
- **No `git stash`, no `git reset --hard`, no `git checkout .`, no
  `git clean`.** Each of those reaches past your own files into other
  sessions' work.
- **`config.toml`.** Never edited by this routine, whatever the answer says. It
  is his live configuration and the app reads it while running.
- **No file deletions.** Not a wav, not a screenshot, not a log, not a backup.
- **`problems.json` as data.** Do not seed it, do not clear it, do not rewrite
  a report's text. The only writes allowed are `Store.resolve` in §7.
- **This file.** `.claude/commands/weekly-reports.md` is your own instructions;
  a routine that edits them is a routine nobody can predict.
- **The running app.** Do not stop, restart or `--stop` DeskIT to try your
  change. A recording may be open at that moment. If the change needs a
  restart to be visible, say so in the summary as a step for him:
  *`Stop DeskIT.vbs` ואז `DeskIT.vbs`*.

---

## 4. Write `problems/weekly/<DATE>-plan.md` — the deep one

For whoever does the work next, which may be a fresh session with zero context,
and now also the record of what this run did itself. Follow the house style:
**`PARALLEL_FEATURES_PLAN.md` in the repo root is the template for exactly this
document — read it before you write.** What to copy:

- The goal at the top **in the owner's own words**, quoted.
- **Numbered rules (`R1`, `R2`, …), stated so they can be argued with.**
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
Built this run: <report id> on weekly/<DATE> — or "nothing, and why".

## 0. What the evidence says (per problem)
## 1. The rules this lands on
## 2. What was BUILT this run — the diff, the tests, the branch
## 3. The work, file by file (for the rest)
## 4. What the evidence does not establish
## 5. Open questions — no code until answered
## 6. What is deliberately NOT fixed here
## 7. Done means
```

§2 is new and it is the accountability section. For the one report you built:
the answer you built against, **quoted from the store — the option he picked
and the words he typed, both, even when one of them is empty**; the branch;
every file and function you changed; the `tests_quiet.py` result verbatim,
including the one known failure by name; and what a reader should look at first
when he opens the diff. If you reverted, say that here too, with the failure
line.

If his typed words changed what the picked option said, **say so in one line
and say what you built instead** — that sentence is the whole audit trail for
why the diff does not match the button.

For each problem with verdict `understood, *` that was not built, four things:

1. **Files and functions to touch** — `module.py`, `Class.method`, named. Grep
   for them and quote the line you mean. A plan that says "somewhere in
   `main.py`" is not a plan.
2. **What could break** — which existing behaviour or test the change contests.
   The repo's tests are one file, `tests.py`; name the test that asserts the
   thing you are about to change, so the contract change is visible up front.
3. **What to measure afterwards** — the number that would show it worked, and
   where it comes from. `recent\` holds a real labelled set; `review.json`
   holds accept/reject history. "It should feel better" is not a measurement.
4. **The verdict**, repeated, so a reader of §3 alone cannot mistake a
   `cause not yet established` entry for a settled one.

**§5 is where the honesty rule lands.** One entry per report waiting on him,
and each entry has exactly these four parts and no fifth:

- **What he reported** — quoted in full.
- **What was checked, and what it ruled out** — the wav, the sidecar, the
  screenshot, the review join, the greps, each with what it showed. This is the
  part that proves the question is not laziness.
- **The question**, in one sentence, identical to the store's.
- **The options**, identical to the store's, in order and complete — however
  many the question has. Do not renumber them, do not add a closing line about
  writing a sentence instead, and do not note that a text box exists.

No root cause. No candidate fix. No "probably". **No option marked as the one
you would choose.** If you have a theory you could not test, it belongs in §4
as a stated unknown with the measurement that would settle it — not in §5
dressed as an answer, and not as option 1 with the rest padded out behind it to
give it something to beat.

**The hard rule: the plan must never claim a cause it has not shown evidence
for.** `## 4` being long is a good plan. `## 4` and `## 5` both being empty on
a week with a bare one-line report is a lie, and he will catch it.

---

## 5. Write `problems/weekly/<DATE>-summary.md` — the short one

**This is the only document he actually reads. It must be skimmable in under a
minute.** Write it in **Hebrew**; keep file names, symbol names, model names,
paths, branch names and ids in English. (The repo's docs are English; this is
his personal weekly note.)

**The open questions come first, at the top.** They are the thing that needs
him; everything else is only ready to read. Lead with the count. If there are
no questions, say so in one line — that is good news and he should see it
immediately. What was built comes second, because it also needs him, but it
needs a look rather than a decision.

Then one line per report or group, each saying two things and no more: **what he
reported, and what is planned about it** — plus its verdict as a short marker.
Not the cause, not the evidence, not the files; those are in the plan. A line
that needs a second line is too long.

Shape:

```
# סיכום שבועי — <DATE>

<N> דיווחים · <k> קבוצות · <q> ממתינים לתשובה שלך · <b> נבנה · פירוט מלא ב-<DATE>-plan.md

## ❓ צריך תשובה ממך (<q>)

- **<id>** · "<what he reported, 6-8 words>" — ההקלטה 2.4 שניות של שקט. הכתבת לחלון אחר, או שהמקש לא נתפס?
  1. הכתבתי לחלון אחר.  2. המקש לא נתפס.  3. דיברתי והמיקרופון לא קלט.
- **<id>** · "<what he reported>" — <a two-option question, and two lines is a finished entry>
  1. <option>.  2. <option>.
- **<id>** · (נשאל ב-12 Sep, עוד ממתין) "<the same question and options, verbatim>"

## 🔨 נבנה השבוע — צריך שתסתכל ותדחוף

- **<id>** · "<what he reported>" → <branch weekly/<DATE>> · <n> קבצים · הטסטים עברו (חוץ מהכשל המוכר של process list)
- להפעלה: `Stop DeskIT.vbs` ואז `DeskIT.vbs`   ← רק אם השינוי דורש הפעלה מחדש

## הדיווחים

- ✅ **wrong** · הסוף של המשפט המציא מילים → מבטלים hotwords מה-prompt של המפענח ומודדים שוב
- 🔍 **slow** · ההדבקה נתקעת → מקור לא אושר; מודדים את זמן ה-clipboard לפני שנוגעים בקוד
- ❓ **other** · <report waiting on an answer, one line, no plan>
- 💡 **idea** · לחיצה אוטומטית על try again → צריך החלטה שלך לפני שמתכננים

## מה צריך ממך
- <the one or two decisions only he can make, beyond the questions above,
  or "רק התשובות למעלה ולחיצה על Push">
```

Markers: `✅` cause established, `🔍` understood but cause open, `❓` waiting on
his answer, `💡` an idea that needs his decision, `🔨` built this run.

Each question's options go in exactly as the store has them, however many there
are — and **nothing is added to tell him he can type instead.** He answers from
the card, which always has the box; the summary is the copy he skims, and a
line about a field he cannot see from here is noise. Two options is a normal
entry, not a truncated one.

A carry-over question is marked with the date it was first asked and repeated
**verbatim** from the store, options included, even if its wording predates
this shape.

If the build was skipped because an earlier branch is still waiting, say that
in one line where the `🔨` block would have been, naming the branch. If a build
was reverted, say that in one line, naming the test that failed.

---

## 6. Write `problems/weekly/<DATE>-reports.md` — the archive

Every report you are about to close, **in full**, so the record survives
independently of `problems.json`. This is the reason closing is safe.

**Reports waiting on an answer, and reports you built, are NOT closed, so they
are not archived here.** They stay in the store, which is where their record
already lives. Note them at the bottom of the archive as carried over, with
their ids and — for a built one — its branch, so a reader of this file knows
the week had more in it than what was archived.

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

## 7. Record, then close only what you understood

### 7a. The questions store

- A new question → `ask(report_id, question, options)`. It lands `PENDING`.
- The one you built → `mark_built(ident, branch, note)`, where `branch` is
  `weekly/<DATE>` and `note` says in one line what was changed and that the
  tests passed. It moves to `BUILT`.
- A question whose report is no longer open, or which the week made
  meaningless → `drop`. Say in your output which and why.
- **`answer(...)` is never called by this run.** See rule 2 at the top of this
  file. If you find yourself reaching for it, you have already gone wrong.

### 7b. Close, in this order, and only these reports

**Order matters and this is the step that can lose him a week.** Write all the
documents first. Then verify they are on disk and non-empty — actually stat
them, do not assume the Write succeeded. Only then close.

If any write failed, **stop and leave every report `OPEN`.** A failed Saturday
that leaves the reports open costs him nothing; one that closes them and then
fails costs him the week, and the reports are the only place some of that
information exists.

**Close only reports whose verdict was `understood, *`, which have no
unanswered question, and which you did not build.** A report with a pending
question is not resolved, and neither is an undecided idea, so both stay `OPEN`
and stay in the dashboard's Problems tab — otherwise he would lose the tab
entry for exactly the reports that still need him. `understood, cause not yet
established` **is** closed: the plan carries the measurement, and nothing is
waiting on him.

**A report you built stays `OPEN` too, and it is not marked `FIXED`.**
`problems.py` has a `FIXED` status and this routine does not use it: "fixed" is
a claim that a change was reviewed and kept, and a routine cannot review its
own work. The branch is unpushed, so nothing has been kept yet. He closes it
when he presses Push, or he tells you next Saturday that it was wrong.

```
.venv\Scripts\python.exe -c "import pathlib,sys,problems;s=problems.Store(pathlib.Path('problems.json'));print([(i,s.resolve(i,problems.CLOSED,by='weekly')) for i in sys.argv[1:]]);problems.digest(s,pathlib.Path('problems.md'))" <id> <id> ...
```

`resolve` returns `False` when nothing changed — no such id, an unknown status,
or the file could not be written. Check every returned value and report any
`False` rather than assuming it worked. `problems.digest` then regenerates
`problems.md` from the store, so the digest and the tab agree.

**Why closing is safe, and say this in your own output so a future reader is
not frightened by it:** `Store._trim` only ever drops JSON rows, and only
resolved ones — open reports are never trimmed (`problems.KEEP_RESOLVED` is
200). It never unlinks anything, so a pinned `.wav` or `.jpg` under `problems/`
survives the close, and survives the row aging out of the store 200
resolutions later. Nothing is deleted by this routine, ever. The archive plus
the pinned files are the permanent record; the store row is only what makes the
Problems tab show it as open.

---

## 8. Tell him it is ready — and what he owes

The repo already has the door. Do not invent a new mechanism, do not write to
`notify.json`, do not start a server. `notify_hook.py` is a stdlib-only CLI that
posts to `POST /notify` and **exits 0 in silence when the app is not running**,
so calling it is always safe.

One card, and it leads with the thing that needs him most. Questions outrank a
branch, because a question blocks next Saturday and a branch only waits.

Questions pending:

```
.venv\Scripts\python.exe notify_hook.py --source weekly --kind input --title "הסקירה השבועית — <q> שאלות מחכות לך" --body "<N> דיווחים · <b> נבנה על weekly/<DATE> · problems/weekly/<DATE>-summary.md"
```

Nothing pending but something was built:

```
.venv\Scripts\python.exe notify_hook.py --source weekly --kind input --title "נבנה משהו — צריך שתסתכל ותדחוף" --body "weekly/<DATE> · problems/weekly/<DATE>-summary.md"
```

Nothing waiting on him at all:

```
.venv\Scripts\python.exe notify_hook.py --source weekly --kind done --title "הסקירה השבועית מוכנה" --body "<N> דיווחים · problems/weekly/<DATE>-summary.md"
```

And the one failure worth a card of its own, from §0b:

```
.venv\Scripts\python.exe notify_hook.py --source weekly --kind error --title "הסקירה השבועית לא רצה" --body "questions.py לא נטען — problems/weekly/run.log"
```

`--kind` must be one of `done`, `input`, `error`, `info` (`notify.KINDS`);
`input` is the one that means the card is waiting for him. Send the card only
after the documents are written and the closes are done — a card that arrives
before the document exists sends him to an empty folder.

---

## 9. What you print

`problems/weekly/` is inside a gitignored folder, on purpose: these reports are
his and they stay on this machine. So `problems/weekly/run.log` is the only
trace of the run, and your final output is what goes into it. It has to answer,
without the documents open, what this routine did to his repo:

- **What it built** — the report id, the answer it was built against with
  **both halves quoted, the option he picked and the words he typed**, the
  files it edited, and the one-line commit subject. If the typed words changed
  what the option said, say what you built instead of the option. Or, if
  nothing was built, which of the reasons: no answered question, an earlier
  `weekly/*` branch still waiting (name it), a file already dirty from another
  session (name it), an answer whose pick and typed words could not be
  reconciled (quote both and name the new question you asked), or a reverted
  build.
- **Which branch** — `weekly/<DATE>`, that it was NOT pushed, and the branch
  you returned to.
- **Which tests ran** — the `tests_quiet.py` result, the count, and the known
  `test_the_process_list_sees_the_processes_it_cannot_open` failure named
  explicitly, so a reader does not mistake green for red.
- **What it asked** — every id left open with a question, the question in one
  line, its options as stored with their count, and whether it is new or a
  carry-over from which date.
- **What it deliberately left alone** — the reports it did not build and why,
  and the standing list: no push, no `config.toml`, no deletions, no
  `problems.json` edits beyond `resolve`, no `git add -A`, no restart of the
  running app.
- **Counts and paths** — how many reports, how many groups, how many of each
  verdict, and the three document paths.
- **Anything it could not gather evidence for**, named. This is the part a
  future reader needs, because it is what next week has to capture.

Then stop. Do not begin any of the work you planned but were not answered
about, do not build a second report, and **do not answer your own questions.**
