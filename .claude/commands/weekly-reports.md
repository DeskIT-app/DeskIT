---
description: Give every open report its turn — build every one whose answer is already on disk, set aside a tagged multiple-choice question for every one that is blocked, then ask them all at once with AskUserQuestion, write the summary, the plan and the archive, and never answer your own question.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

# Weekly review of the problem reports

It is Saturday at four in the morning and nobody is at the keyboard. But this
is not a batch job printing into a void: it runs as a **Claude Code scheduled
task**, so it is a **real session with a live composer**. The session stays
there after the run ends. He wakes up, reads it, and can type into it.

Two consequences, and they shape the whole file:

- **You can ask a real question** — `AskUserQuestion` puts clickable options in
  front of him (§2). You are not restricted to prose he has to answer somewhere
  else.
- **He is asleep while you work.** So nothing may *wait* on him mid-run. Every
  build, every document, every close happens first; the asking is the last
  thing the run does (§8b), and by then there is nothing left undone that his
  silence could hold up.

Everything else you need is below or on disk. Working directory is the repo
root; every path below is relative to it.

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
- **He has not answered it → investigate it, then write the question aside and
  go on to the next report.** One question, as many real options as the
  question actually has, and no code. It stays open.

Everything else here — the evidence work, the verdicts, the three documents,
the archive — is unchanged, because the reason the routine could be trusted to
write documents is the same reason it can now be trusted to write code: it
never claims more than the evidence shows.

## The shape of the run: every report gets its turn

The obvious way to write this routine is to take the reports in order, and
stop at the first one you cannot settle so you can ask about it. That is the
shape he rejected, in these words:

> "If she stops at the first report, asks me a question and waits for me to
> finish, she wastes a huge amount of time — and if all the other reports
> could have been done without asking me anything, then it is just a nightmare
> to wait and it takes forever."

He is right, and the arithmetic is why: he is asleep at 04:04. A run that
blocks on report one has not asked a question early, it has **thrown the whole
Saturday away** — four reports that needed nothing from him sit untouched
until next week because the first one had a gap in its evidence. The waiting
buys nothing either, because a question asked at 04:04 and a question asked at
04:40 are both answered at the same moment: when he wakes up.

So the run is a **loop over every open report**, and each report is carried to
its own dead end before the next one starts:

1. **Gather its evidence and rule on it** (§1).
2. Then exactly one of three ends:
   - **His answer to it is already on disk → build it** (§3), test it, commit
     it, and move on.
   - **It is settled and needs nothing from him and nothing built** — the cause
     is established and an existing commit already covers it, or it is
     `understood, cause not yet established` with the measurement written into
     the plan → **close it** (§7b) and move on.
   - **It is blocked on something only he can decide → write the question into
     the store, set it aside, and move on** (§2). No code for this report, and
     **no waiting.**
3. Only when every report has had its turn: the documents, the closes, the
   card, and then **all the collected questions asked together** (§8b).

Three rules fall out of that, and they are not negotiable:

- **A blocked report never ends the run.** It ends its own turn. If you find
  yourself about to write the summary because report two had no answer, you
  have made exactly the mistake this section exists to prevent.
- **Start each report fresh.** The next report is not a continuation of the
  one you just failed to settle. Read its own evidence; a theory carried over
  from the report before it is the commonest way two unrelated reports get the
  same wrong cause.
- **Build everything that can be built, not one thing.** Each build is its own
  commit on the same `weekly/<DATE>` branch, with the tests gate run *before*
  each commit (§3d), so one report's failure cannot discard another report's
  work.

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

**`AskUserQuestion` does not open a side door in that wall, and the store makes
sure of it.** `Store.mark_built` refuses any question that is not `ANSWERED`
(read it — the check is explicit, and its comment is *"so nothing can be
recorded as built off a question he never answered"*). So even if he is awake
and clicks an option in the session while the run is still alive, that click
cannot become a build in this run: the only route from a click to `ANSWERED` is
`answer(...)`, and `answer(...)` is his. A live answer is real and it is his, so
**quote it verbatim in your output** — but the question stays `PENDING`, his
DeskIT card still carries it, and next Saturday builds it from the store with
the audit trail whole. That is one week of latency bought for the guarantee
that every line this routine commits traces to a row he wrote. It is a good
trade and it is not yours to renegotiate at 4 AM.

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
**there is no open option and no "something else" slot.** Both places he
answers add the escape hatch themselves: the DeskIT card carries a free-text
box under the buttons, and `AskUserQuestion` appends its own "Other" choice. So
a slot never has to be spent on one, and it must not be. That is also why the
floor is above one: two genuine choices are a choice, and one is not.

`clean()` enforces the range by **refusing**, never by adjusting, and its
docstring says why: *"Refusing, rather than padding the short list or trimming
the long one, is the honest move… inventing a filler or dropping the tail
changes the question he is being asked."* Carry that principle out of the store
and into every place a question is rendered. It is what settles the one seam
between the store and the tool: `AskUserQuestion` takes at most **four**
options per question while `OPTIONS_MAX` is five, and a five-option question is
therefore **not trimmed to fit the tool** — it goes to him on the card, which
has no such ceiling (§8b).

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
with `--kind error` naming the missing module (§8a), print why, and stop. A
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
  not manufacture a document to look busy. **Still put the carry-overs to him
  with `AskUserQuestion` (§8b)** — a chip he can click is the one thing this
  week can add to a question he has been ignoring on a card, and it costs him
  nothing to see it.

**A question that is already `PENDING` is never asked again — into the store.**
Putting a standing question to him again as a chip is not asking it again; it
is the same question reaching him on a surface he is looking at. What must
never happen twice is the *row*. The store's status does the job the old
`asked.json` bookkeeping did: the summary says
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

## 2. The question: a real multiple choice he clicks

# ASK WITH `AskUserQuestion`. IT IS THE PRIMARY WAY THIS RUN ASKS HIM ANYTHING.

Not prose he has to answer elsewhere. Not a line in a document. A real
multiple-choice prompt with buttons he clicks, because that is what he asked
for, in these words:

> "ממש שאלה אמריקאית כזאת שהיא מבחירה"

The tool is available in these runs — the scheduled task's environment sets
`CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL` — and it is listed in this
command's `allowed-tools`. It is the answer to "how do I ask him?" every time
that question comes up in this file.

**One call, at the very end of the run** (§8b), never mid-report. Everything
below is how to *write* the questions; §8b is where you ask them.

### The tool's shape

One call carries **1 to 4 questions**. Each question is:

- **`header`** — the chip label he sees. **Maximum 12 characters.** This is the
  report tag; see below.
- **`question`** — the question text, opening with the three-word tag.
- **`options`** — **2 to 4** of them, each with a `label` (the short pickable
  line) and a `description` (one line saying what picking it means).

Two things the tool does for you, and doing them yourself is a bug:

1. **It appends its own "Other" free-text choice.** So do **not** write an
   escape-hatch option, do not append "או תכתוב לי" to the last one, and do not
   mention a text box anywhere. Every word about it is a word he reads instead
   of the choice, and it is exactly the line he had removed.
2. **It does not want the list padded.** Two real options is a finished
   question. Everything under *The options are the hard part* below applies to
   the tool's `options` exactly as it applies to the store's.

### Every question carries a three-word tag naming its report

He answers four chips in a row with the reports themselves out of sight. His
requirement:

> "תרשום כזה בשלושה מילים על השאלה לאיזה דיווח היא תקפה — נגיד הדיווח על בעיות
> בתמלול, הדיווח על הבעיות בכרטיסיות התראה"

`header` is what the tool has for exactly this, but 12 characters will not hold
a three-word Hebrew phrase. So the tag lives in **two places at once**:

- **`header`** — the **shortest true form** of the tag, within the cap. A chip,
  not a sentence.
- **the first words of `question`** — the **full three-word phrase**, then an
  em-dash, then the question itself. This is where the naming actually happens;
  `header` is only the pointer.

**Worked example — a transcription report:**

```
header:   בעיות תמלול
question: הדיווח על בעיות בתמלול — ההקלטה 2.4 שניות של שקט. הכתבת לחלון אחר, או שהמקש לא נתפס?
options:  [ "הכתבתי לחלון אחר", "המקש לא נתפס" ]
```

`בעיות תמלול` is 11 characters, so it fits as it stands.

**Worked example — a notify-card report:**

```
header:   כרטיסיות
question: הדיווח על הבעיות בכרטיסיות התראה — הכרטיסייה נשארת על המסך אחרי שלחצת עליה. מה לעשות?
options:  [ "לסגור אותה מיד בלחיצה", "להשאיר אותה עד שתיגמר לבד" ]
```

Here the full tag `כרטיסיות התראה` is 14 characters and will not fit, which is
the ordinary case, not the exception.

**When the tag exceeds the cap:** keep the full phrase at the head of
`question` and shrink `header` to **the one noun that identifies the report** —
`כרטיסיות`, `תמלול`, `הדבקה`, `צלילים`. Never an abbreviation he would have to
decode, and never a word that is not actually in the phrase. If even the single
noun is over 12 characters, choose a shorter true synonym; do not cut a word
mid-letter.

**Headers must be distinct within a call.** Two transcription reports in one
call both want `בעיות תמלול`, and then he has two identical chips and no way to
tell which he is answering. Distinguish by the surface or by the second noun
(`תמלול קצר` / `תמלול ארוך`, `תמלול Recordings`), and keep the full phrases in
the `question` text different too.

**The same tag goes on the question in the store and on its line in the
summary,** so the three places he might read it agree.

The tag is spent out of the question's own length budget, `questions.QUESTION_MAX`
— read the constant, do not carry the number — and `_line` **cuts** an
over-long question rather than refusing it, so a bloated tag silently eats the
end of the question. Both examples above land under a quarter of it, which is
where a tagged question should sit. If you are anywhere near the limit, the
question is too long, not the tag too generous.

### Also write every question into the store, and into the documents

Every open report he has not answered gets **exactly one** question in the
store. One question per report; if you have three, you have not finished the
evidence work.

```
.venv\Scripts\python.exe -c "import pathlib,sys,json,questions;s=questions.Store(pathlib.Path(getattr(questions,'STORE_NAME','questions.json')));a=json.load(open(sys.argv[1],encoding='utf-8'));print(s.ask(a['report_id'],a['question'],a['options']))" <a json file you wrote>
```

Pass it through a small JSON file rather than a command line: the questions and
the options are Hebrew, and a console codepage must not be what mangles them.

**The store write is not where the answer is collected — the tool and the card
are. It is there so the question survives.** He can close the session without
answering, and a session he closed is a question that was never asked at all:
no card, no badge, nothing next Saturday can find. A row in `questions.json` is
what makes his silence recoverable instead of final. Same reason it goes into
the summary (§5) and the plan's `## 5` (§4): three durable copies of a question
whose asking may have evaporated.

Write the store row **during the report's turn**, not at the end. The tool call
comes last, and a run that dies before it must still leave the questions
behind.

**Two consequences of `ask()`'s de-duplication, which matches on the question
text word for word** (read it: same `report_id`, same text, still `PENDING`
returns the standing item instead of a second card):

- **A report's tag must be stable.** Reword the tag next Saturday and the store
  sees a new question and gives him a second card for the same report.
- **Never add a tag to a carry-over question already in the store.** §0d says
  repeat it verbatim and that outranks this section. The tag for a carry-over
  goes in `header` and in the summary line only; the stored text stays exactly
  as it is.

### If the tool is genuinely unavailable — second choice, and say so

It happens — it was missing entirely on 2026-09-05, and no environment variable
brought it back. When it is not there, **ask in the run's final message**, one
question per paragraph, each opening with its three-word tag, the options as
ordinary numbered sentences.

**NEVER PUT THE QUESTION OR THE OPTIONS IN A FENCED CODE BLOCK.** He showed the
result on 2026-09-05 and it is unreadable: a fence forces left-to-right, so
Hebrew comes out with the punctuation thrown to the wrong end, wrapped in a
grey box with a copy button, looking like something to run rather than
something to answer. His words: *"נראה לך שאני יכול לקרוא את זה? תרשום לי את
זה בשפה של אנשים, לא בקוד."* Plain sentences, bold for the question, ordinary
numbers for the options. The same rule governs the summary: no fence around
anything he is meant to read as language. Fences are for commands he runs and
for nothing else.

**And the fallback message carries the questions ONLY.** Not the verdicts, not
the branch, not the counts, not what was left alone — all of that is already in
the summary, the plan and `run.log`, which is where §9 puts it and where it
belongs. His words, after a run that printed the lot: *"אני לא צריך לדעת שום
דבר מלבד השאלות."* So the final message is the questions, and one line saying
where the rest is. If there are no questions, it is one line long.

**This is worse than the tool and it is a fallback, not an alternative.** He
gets no buttons and answers by typing. Say in `run.log` that the tool was
missing — but never let the tool being absent become the reason a run ends up
**silently not asking**. Not asking is the one outcome this section exists to
make impossible.

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
out. There is no open option.** Both surfaces supply one already: the DeskIT
card always carries a free-text box under the buttons — it is there whatever
the options are, and it is there when there are no options at all — and
`AskUserQuestion` appends its own "Other". So the run never has to spend a slot
on an escape hatch, and it must not. An option that reads "something else, I'll
write it" spends a line of a small card telling him about a box he is already
looking at.

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

In all four cases the free-text escape — the card's box, the tool's "Other" —
is already under them and no option refers to it.

---

## 3. Build every report he has already answered

An `ANSWERED` question is an approval. **Build all of them** — this section
runs once per answered report, inside the loop of §*The shape of the run*, and
there is no cap on how many.

There used to be a cap of one per run, and it was the wrong instrument for the
right worry. The worry is unreviewed work piling up where he cannot see it, and
the thing that hides work from him is **an unreviewed branch**, not a second
commit on a branch he is already going to read. Three answers he wrote a week
ago, all buildable, all sitting unbuilt because the run stopped after the
first, is the same waste as stopping at the first question — and it is worse,
because those three he had already decided.

So: **one branch per run (§3a, §3b), one commit per report (§3d, §3e), the
tests gate before every commit.** He opens one branch and reads a commit per
report, each with the answer it came from in its message.

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
   you cannot tell which thing he wants — build nothing for this report, ask
   again, and go on to the next one.** One new question in the store, quoting
   both halves of what he said and asking which he meant; it joins the
   collected questions for §8b like any other. That is this report's dead end,
   not the run's. That costs him one line on Sunday. A branch built on the
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
he has not yet dealt with is the signal to stop.

**Do not test that with the upstream ref.** That was the test here until
2026-09-05 and it is wrong on this machine: DeskIT's Push runs
`git push origin <branch>` and `git push origin <branch>:fast` with no `-u`
(`dashboard.py:834`, `dashboard.py:865`, and `problems/weekly/push.log` shows
both), so a branch he HAS pushed keeps an empty `[%(upstream)]` for ever. Read
literally it jammed the gate shut permanently — every future run declining to
build, on a branch already published and already merged. Ask instead whether
the work is still only local:

```
git for-each-ref --format="%(refname:short)" refs/heads/weekly
```

For each branch it names, it is **dealt with** if EITHER of these says so:

```
git rev-parse --verify --quiet refs/remotes/origin/<branch>       # he pushed it
git merge-base --is-ancestor <branch> <the branch this run started on>
```

On `origin`, or already contained in the branch this run started from, is
finished business and stops nothing. Only a branch that is neither is still
waiting on him.

**If today's `weekly/<DATE>` already exists and is dealt with, do not force it
anywhere and do not delete it.** Branch from where you are onto the next free
name — `weekly/<DATE>-2`, then `-3`. A second run in a day is ordinary (the
runner re-fires whenever an answer arrives) and the Push panel globs
`refs/heads/weekly/`, so the new branch appears there beside the old one.

If any branch is still waiting, **build nothing this run** — not one
report, not any of them. Say in the summary and in your output which branch is
waiting and which report it belongs to, then carry on with the rest of the run
exactly as normal: every report still gets its turn, every blocked one still
gets its question, and the questions are still asked at the end. A waiting
branch stops the *building*; it does not stop the run.

**This gate survives the removal of the one-report cap, and it is the reason
the cap was safe to remove.** One unreviewed branch at a time is the real
constraint: two of them is how he loses track of what the routine has done to
his repo, and the whole arrangement rests on him being able to see all of it at
once. Many commits on one branch he is going to read anyway costs him nothing;
a second branch behind one he has not opened costs him the thread.

If nothing is waiting, build the answered reports in order of **oldest answer
date** first, among those whose report is still `OPEN`. First answered, first
built — so a slow week cannot bury an answer he wrote a fortnight ago.

### 3b. The branch, before you touch a file

Once per run, not once per build:

```
git rev-parse --abbrev-ref HEAD
git checkout -b weekly/<DATE>
```

Record the starting branch name — you will return to it when every build is
done. The name matters: `git branch --list 'weekly/*'` finds every branch this
routine has ever made, which is what keeps its work from being confused with
the other unpushed branches in this repo.

**Stay on the branch for the whole build phase.** Do not check out and back
between reports; there is nothing to gain and a checkout is the one git command
here that can touch another session's files.

### 3c. The precondition that makes reverting safe

**Before editing a file, prove it is clean:**

```
git status --porcelain -- <path>
```

Empty means clean. **If a file you need is already dirty, do not touch it.**
The tree in this repo routinely carries other sessions' half-finished work, and
an edit on top of it cannot be reverted without destroying theirs. Leave the
report open, write down which file was dirty and which session's change it
looked like, and let next Saturday have it — **and go on to the next report.**
One dirty file blocks one build, not the run.

**Run this check per build, not once for the run**, and note what it means once
several builds share a branch: your own committed work does not show up here.
A file you edited and committed for report one is clean again when report three
needs it, and that is correct — the precondition is *"no uncommitted work that
is not mine"*, and yours is no longer uncommitted. What it still catches, which
is the whole point, is another session's edits arriving mid-run.

### 3d. Build it — and gate it before you commit it

Write the code this one answer authorises, and only that. Then, **before the
commit for this report**:

```
.venv\Scripts\python.exe tests_quiet.py
```

**No `--no-screen`, and that is deliberate.** House rule 8 in `AGENTS.md` says
every test run happens on a hidden desktop, and `tests_quiet.py` is exactly
that — but its plain form finishes by running the sixteen tests in
`tests_quiet.NEEDS_SCREEN` in the open, because they need the real display and
the real mouse. That costs about fifteen seconds of windows and a stolen
pointer, which is why anyone running the suite at his desk adds `--no-screen`.
Here nobody is at the desk — this is a scheduled task and he is asleep — so
this is the run that gets to prove those sixteen too. Keep the plain form. If
you are ever running this command by hand while he is sitting there, add the
flag.

**The green state is one failure**, the known machine-flaky
`test_the_process_list_sees_the_processes_it_cannot_open` — the suite prints
`1 FAILED` and exits non-zero and that is still green. **Any other failing test
means this build is reverted**, however plausible the failure looks. You cannot
tell a pre-existing break from one you caused at 4 AM with nobody to ask.

**The gate runs before every commit, and that ordering is what makes several
builds per run safe.** Uncommitted work is what a revert can reach; a commit is
what it cannot. So each report's changes are proved green *while they are still
the only uncommitted thing on the branch*, and then sealed. Run the suite once
at the end instead and a single bad build would put every other report's work
in question with no way to tell which one broke it.

### 3e. Commit only your own files, by path

One commit per report:

```
git add -- <exactly the files you edited for this report>
git commit -m "<one line in the repo's voice, then the report id and the answer it came from>"
```

**Never `git add -A`, never `git add .`, never `git commit -a`.** His rule, and
the reason for it is on the branch you are standing on: the tree carries other
sessions' changes, and a sweep would commit their unfinished work under your
message. Stage by path or do not stage. With several builds in a run this rule
does double duty — a sweep on report three's commit would also swallow anything
report four has half-written.

Then go on to the next report. **Only when the whole loop is finished** do you
go back where you came from:

```
git checkout <the starting branch>
```

If that checkout fails, **stop touching git.** Say so in the summary and in
your output, leave the tree exactly as it is, and let him sort it out — a
forced checkout would take another session's work with it.

### 3f. Reverting one build, when the tests say no

**Only the build that failed is reverted. Every commit already on the branch
stands.** This is the case the design is for, so take it concretely: four
answered reports, the third one's build turns the suite red. Reports one and
two are already committed and green and **they stay**; report three's
uncommitted changes go; report four then gets its turn as if nothing happened,
on the same branch, with its own gate and its own commit. He ends the week with
three good commits and one report marked blocked — not with nothing.

The failed build's changes are not committed yet, so:

```
git checkout -- <the files you edited for this report>
```

That is safe precisely because §3c proved those files were clean before you
started this build, so restoring them restores the branch as report two left it
and nothing of anyone else's. **Do not delete the branch and do not check out
the starting branch here** — earlier commits live on that branch and later
reports still need it. `git branch -D weekly/<DATE>` is right only in the one
case where **nothing was committed at all**: every build in the run failed or
was skipped, so the branch holds no work and an empty `weekly/*` branch with no
upstream would trip §3a's gate next Saturday for nothing.

Then leave that report `OPEN`, leave its question `ANSWERED` so next Saturday
tries again, and write down in the plan **what broke, which test, and the exact
failure line.** Report it in the summary and in your output as **blocked, with
what broke** — beside the builds that succeeded, not instead of them. A build
that failed with the reason recorded is a good week's work; a build that failed
silently is worse than none.

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
Built this run: <b> on weekly/<DATE> — <report id>, <report id>, … — or
"nothing, and why". Blocked builds: <report id> — <which test broke>.

## 0. What the evidence says (per problem)
## 1. The rules this lands on
## 2. What was BUILT this run — the diff, the tests, the branch
## 3. The work, file by file (for the rest)
## 4. What the evidence does not establish
## 5. Open questions — no code until answered
## 6. What is deliberately NOT fixed here
## 7. Done means
```

§2 is the accountability section, and it has **one subsection per build, in the
order the commits were made**, so the section reads down the branch. For each
one: the answer you built against, **quoted from the store — the option he
picked and the words he typed, both, even when one of them is empty**; its
commit subject; every file and function you changed; the `tests_quiet.py`
result verbatim for *that* build, including the one known failure by name; and
what a reader should look at first when he opens the diff. The branch is named
once at the top of §2, since every build shares it.

A build you reverted gets its own subsection in the same place, marked
**blocked**, with the failing test and the exact failure line — and it says
plainly that the commits before it stand. Do not move it to the end or fold it
into §4; a reader walking the branch needs to know that the report between
commit two and commit three exists and why it is not there.

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
and each entry has exactly these five parts and no sixth:

- **What he reported** — quoted in full.
- **What was checked, and what it ruled out** — the wav, the sidecar, the
  screenshot, the review join, the greps, each with what it showed. This is the
  part that proves the question is not laziness.
- **The question**, in one sentence, identical to the store's — **including its
  three-word tag at the front** (§2), and the `header` you gave it beside it in
  brackets, so a reader can match the entry to the chip he clicked.
- **The options**, identical to the store's, in order and complete — however
  many the question has. Do not renumber them, do not add a closing line about
  writing a sentence instead, and do not note that a text box exists.
- **How it was asked** — in the `AskUserQuestion` call, or not asked with the
  tool this run (§8b) and why: it was past the fourth chip, it has five
  options, or the tool failed. That line is what tells next Saturday whether
  his silence means he declined or never saw it.

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

- **<id>** · **הדיווח על בעיות בתמלול** · "<what he reported, 6-8 words>" — ההקלטה 2.4 שניות של שקט. הכתבת לחלון אחר, או שהמקש לא נתפס?
  1. הכתבתי לחלון אחר.  2. המקש לא נתפס.  3. דיברתי והמיקרופון לא קלט.
- **<id>** · **הדיווח על הבעיות בכרטיסיות התראה** · "<what he reported>" — <a two-option question, and two lines is a finished entry>
  1. <option>.  2. <option>.
- **<id>** · **<tag>** · (נשאל ב-12 Sep, עוד ממתין) "<the same question and options, verbatim>"
- <a question not asked with the tool this run — say so in half a line: "לא הוצגה כשאלה בסשן (חמישית בתור) — מחכה לך בכרטיסייה">

## 🔨 נבנה השבוע — צריך שתסתכל ותדחוף  (הכל על weekly/<DATE>)

- **<id>** · "<what he reported>" → <n> קבצים · הטסטים עברו (חוץ מהכשל המוכר של process list)
- **<id>** · "<what he reported>" → <n> קבצים · הטסטים עברו (חוץ מהכשל המוכר של process list)
- **<id>** · "<what he reported>" → נחסם: <test name> נכשל, השינוי הוחזר. שאר ה-commits עומדים.
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

**Every question line opens with its three-word tag** (§2), bolded, before his
quoted words — the same tag that was in the `question` text and the same idea
`header` carried on the chip. He reads this document after clicking the chips,
so the tag is how the two line up in his head.

Each question's options go in exactly as the store has them, however many there
are — and **nothing is added to tell him he can type instead.** He answers from
the chip or the card, and both supply their own free-text escape; the summary is
the copy he skims, and a line about a field he cannot see from here is noise.
Two options is a normal entry, not a truncated one.

A carry-over question is marked with the date it was first asked and repeated
**verbatim** from the store, options included, even if its wording predates
this shape. Its tag goes on the summary line only — never edited into the
stored text (§2).

If **all** building was skipped because an earlier branch is still waiting, say
that in one line where the `🔨` block would have been, naming the branch. The
`🔨` block otherwise lists every build, one line each, **including the ones that
were reverted** — a reverted build is a line in the block naming the test that
failed, not a missing line. He must be able to count the reports in this
document and get the same number he filed.

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
  Call it during the report's turn, not at the end (§2).
- **Each one you built** → `mark_built(ident, branch, note)`, where `branch` is
  `weekly/<DATE>` and `note` says in one line what was changed and that the
  tests passed. It moves to `BUILT`. One call per build; a run with three
  builds makes three calls, all naming the same branch.
- A build you reverted → **leave it `ANSWERED`.** `mark_built` would be a lie
  and the store would take it, because it only checks the status, not the
  truth. `ANSWERED` is what makes next Saturday try again.
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

## 8. Tell him — the card first, then the questions

Two things happen here and **the order is not arbitrary.** The card goes out
first, because it is what reaches him when he is nowhere near this machine, and
it must not be held up behind a dialog nobody is awake to answer. The
`AskUserQuestion` call is the last act of the run, because it is the one thing
that may sit there until he wakes up — and by then everything is built, tested,
committed, written and closed, so his silence holds up nothing at all.

### 8a. The card

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

### 8b. Then ask him — all of it, in one call

Every report has had its turn. Every build is committed, every document is on
disk, every close is done, the card is sent. **Now** put the collected
questions to him, with `AskUserQuestion`, in **one call** (§2 has the shape,
the 12-character `header`, and the three-word tag).

**One call, not one per question.** Four separate dialogs is the queue he
objected to, arriving four times over; one call is four chips he answers in a
row.

Order the questions **by how much work is blocked behind each** — most blocked
first. That is the only ordering that matters, because it decides which ones
get asked when there are more than fit.

**When there are more than four questions:** the tool takes at most four per
call, and the answer is **not** a second call stacked behind the first. Ask the
top four. The rest are **already** in the store, in the summary, and covered by
the card — which is exactly where they would have been anyway, and the DeskIT
card gives him the same buttons plus the same text box, with no ceiling of four
and no ceiling of `OPTIONS_MAX` either. Nothing is lost by not chipping them;
something is lost by making him clear one dialog to discover another. Same
answer for a question with five options (§0b): it goes to the card intact
rather than being trimmed to the tool's four, because trimming changes the
question he is being asked.

**One standing rule covers every mismatch between the store's shape and the
tool's: the card wins and nothing is edited.** The other case you will meet is
a migrated carry-over that still ends in an old `משהו אחר` line (§0d). You may
not remove it — verbatim outranks everything for a question already in the
store — and chipping it would put that line next to the tool's own "Other" and
make the run look confused about its own question. So that one goes to the card
too, and your output says why.

Say in the summary and in your output **which questions were asked with the
tool and which were not, and why** — past the fourth chip, five options, or the
tool failed. A question he never saw as a chip and a question he saw and
skipped look identical next Saturday unless this run wrote down which it was.

**If he answers here and then:** his answers are his, so quote them verbatim in
your output — and **build nothing from them.** Rule 2 and `mark_built`'s
`ANSWERED` check say why; the questions stay `PENDING` and his card carries
them.

**If the tool is unavailable**, fall back to the numbered form in the run's
final message (§2, last block). Second choice, and say in your output that it
was used and why. The one unacceptable ending is a run that had questions and
asked none.

---

## 9. What you print

`problems/weekly/` is inside a gitignored folder, on purpose: these reports are
his and they stay on this machine. So `problems/weekly/run.log` is the only
trace of the run, and your final output is what goes into it. It has to answer,
without the documents open, what this routine did to his repo.

**Everything in this section is written FOR `run.log`, not for him.** When the
run is a scheduled one nobody is watching, they are the same text and that is
fine. When he IS at the keyboard, they are not: what he sees is the questions
and one line saying where the rest is (§2's fallback block says why). Never
make him scroll a run report to find the one thing he has to decide.

The log has to carry all of this:

- **Every report's turn and how it ended** — one line each, in the order you
  took them, and **every open report appears**. Built, closed, or blocked on a
  question. This list is the proof the loop actually ran; a report missing from
  it is a report the run silently skipped.
- **What it built** — **one entry per build**, each with the report id, the
  answer it was built against with **both halves quoted, the option he picked
  and the words he typed**, the files it edited, and the one-line commit
  subject. If the typed words changed what the option said, say what you built
  instead of the option. For each build **not** made, which of the reasons: no
  answered question, an earlier `weekly/*` branch still waiting (name it), a
  file already dirty from another session (name it), an answer whose pick and
  typed words could not be reconciled (quote both and name the new question you
  asked), or a revert (name the test).
- **Which branch** — `weekly/<DATE>`, how many commits are on it, that it was
  NOT pushed, and the branch you returned to.
- **Which tests ran** — the `tests_quiet.py` result **per build**, with the
  known `test_the_process_list_sees_the_processes_it_cannot_open` failure named
  explicitly each time, so a reader does not mistake green for red. If a run
  went red, say which build and which test, and say explicitly that the
  earlier commits stand.
- **What it asked** — every id left open with a question; its **three-word tag
  and the `header` you gave it**; the question in one line; its options as
  stored with their count; whether it is new or a carry-over from which date;
  and **whether it went into the `AskUserQuestion` call or not, and why not**
  (past the fourth chip, five options, or the tool failed and you fell back to
  the numbered form). If he answered any of them live, **quote his answers
  verbatim** and say that nothing was built from them.
- **What it deliberately left alone** — the reports it did not build and why,
  and the standing list: no push, no `config.toml`, no deletions, no
  `problems.json` edits beyond `resolve`, no `git add -A`, no `answer(...)`, no
  restart of the running app.
- **Counts and paths** — how many reports, how many groups, how many of each
  verdict, how many built, how many blocked, and the three document paths.
- **Anything it could not gather evidence for**, named. This is the part a
  future reader needs, because it is what next week has to capture.

Then stop. Do not begin any of the work you planned but were not answered
about, do not act on an answer that arrived during §8b, and **do not answer
your own questions.**
