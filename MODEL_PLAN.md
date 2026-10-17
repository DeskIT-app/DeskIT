# DeskIT — the road to the best Hebrew speech model ("the model plan")

Written 2026-10-13 on the owner's brief: *"think of every corner … find the
best way. It doesn't have to be efficient — take as long and as many tests
as you need, but in the end reach the best result. No compromises."* Rules
that stand (his, 2026-10-12): only free things or the keys he already has
(Claude, Groq); before EVERY spend of the Claude key, the plan and the
estimated cost, and his yes; never fit the model to his own voice — the app
is for everyone. Training lives in `DeskIT-training\` (outside the repo, never
shipped); this file is the map. Earlier numbers: `API_POOL_PLAN.md` §13.4-13.9.

---

## 1. Where we stand (2026-10-13)

Every row is the night tests' own two sets, the app's own decoding mode.

| model | FLEURS Hebrew, words wrong | Reversim (Hebrew + English), words wrong | English words right | decode, 123 min of FLEURS |
|---|---|---|---|---|
| today's (ivrit.ai turbo) | **19.61%** (2,679) | 16.03% | 40% | ~295 s |
| ivrit.ai **large-v3** (not turbo) | 19.82% (2,707) | 16.56% | 40% | **1,035 s** |
| night3 (+ ivrit crowd 51 h) | 20.06% | 11.80% | 74% | ~295 s |
| night4 (+ teacher labels) | 19.76% | **10.97%** | 73% | ~296 s |
| night5 (night4 again) | 19.94% | 11.42% | 73% | ~293 s |
| today's + Sonnet 5.5 fix after it | **17.22%** | 15.69% | 43% | +1.55 s a dictation |
| night2 + Sonnet 5.5 fix | 20.07% | 11.76% | 79% | |

### The Stage 0 sets (measured the night of 2026-10-13 → 14)

Words wrong, as counts (lower is better). FLEURS dev = Google's own dev split
(328 clips, 49 min); Reversim dev = 379 stretches of 8 older episodes nobody
trained on (56 min, 234 English words); WhatsApp = ivrit.ai's eval-whatsapp
(54 voice messages, 71 min, verbatim expert text); d1 = ivrit.ai's eval-d1
(17 podcast recordings, 86 min, long-form). "pen 1.0" = the app's decode with
`repetition_penalty` 1.0 instead of the app's 1.15 (finding 7). Everything in
`DeskIT-training\runs\stage0\report.txt`.

| model | FLEURS dev | Reversim dev | WhatsApp | d1 | FLEURS test | Reversim test |
|---|---|---|---|---|---|---|
| today's (the app's decode) | 1,210 | 1,292 | **875** | **600** | 2,679 | 1,265 |
| night2 (Reversim only) | 1,313 | 993 | 1,558 | 1,408 | 3,042 | 951 |
| night3 (+ ivrit crowd) | 1,228 | 1,009 | 1,363 | 1,040 | 2,740 | 931 |
| night4 (+ teacher labels) | 1,241 | 822 | 1,131 | 881 | 2,699 | 866 |
| night5 (night4 again) | 1,233 | 817 | 1,177 | 838 | 2,724 | 901 |
| **today's, pen 1.0** | **1,109** | 1,309 | **665** | **499** | **2,638** | 1,228 |
| **night4, pen 1.0** | 1,122 | **792** | 833 | 592 | 2,668 | **757** |
| today's, pen 1.05 | 1,130 | 1,284 | 700 | 518 | | |
| night6 (all data, Reversim twice) | 1,217 | 832 | 1,127 | 731 | 2,691 | 885 |

**The decode on branch `no-repetition-penalty`** (pen 1.0, a looping clip
decoded again with 1.15 — computed from the decodes above, which are
deterministic; the loops coming back are why the FLEURS test, night4's
Reversim test and night6's d1 are lower than in the pen 1.0 rows):

| model | FLEURS dev | Reversim dev | WhatsApp | d1 | FLEURS test | Reversim test |
|---|---|---|---|---|---|---|
| today's | 1,109 | 1,309 | **665** | **499** | 2,536 | 1,228 |
| night4 | 1,122 | 792 | 833 | 592 | 2,565 | **738** |
| night6 | 1,096 | **783** | 818 | 574 | **2,530** | 776 |
| night7 (night6 + verbatim labels) | **1,093** | 824 | 788 | 547 | 2,542 | 741 |
| night8 (night7, clips still missing 2+ heard words left out) | 1,100 | 851 | 767 | 539 | 2,541 | 741 |

**night6 (2026-10-14)**: all 251 h of crowd-transcribe + Reversim twice,
5.7 h. Against night4 it is level — a little better on plain Hebrew (FLEURS
dev −26, FLEURS test −35), a little worse on the Reversim test (+38), the
rest inside the spread. It is the first trained model that is not worse
than today's on plain Hebrew (−13 and −6), and it is ~40% better on Hebrew
with English; but it is still 23% worse on WhatsApp and 15% on d1, and the
reason is still the dropped words (WhatsApp: 128 dropped vs today's 82).
More data did not cure finding 8 — the labels have to.

**night7 (2026-10-15)**: night6 with the verbatim labels, scored by its own
runner in the branch's decode (night6's row above was re-measured by the same
runner and came back to the word, so the computed rows hold). The cure works
and is half done: words DROPPED against today's model on WhatsApp 128 -> 105
(today 82), on d1 182 -> 148 (today 122) — the excess halved on both. The
totals moved the same way (WhatsApp −30, d1 −27, Reversim test −35) but each
inside its spread; Reversim dev +41 is the one cost, and its references are
the same edited text, so putting spoken words back is partly scored as
insertions there. Still +123 / +48 against today's on WhatsApp / d1.
The restoration only put words back mid-clip where nothing else changed;
30% of the clips still lack 2+ heard words.

**night8 (2026-10-16) — finding 8 closed.** Words dropped on WhatsApp 79
(today's 82; night6 128, night7 105), on d1 136 (today's 122). The English
held (Reversim test 247 of 330 English words right, today's 118). What is left
on WhatsApp is mostly the style the app wants: 121 of night8's 767 are an
English term in Latin letters where the reference spells it in Hebrew
("google" for "גוגל", "token" for "טוקנים"); without those, night8 646 against
today's 662 there, and on d1 523 against 487 (inside the ~45 spread). It is
the first trained model level with today's on plain Hebrew and on everyday
speech and ~40% better on Hebrew with English. **His call, 2026-10-17: into
his Dev copy for days of real dictation** (`local.model` in settings.toml =
`DeskIT-training\runs\night8\ct2`; one line back to
`ivrit-ai/whisper-large-v3-turbo-ct2` undoes it), **and night9 = night8
repeated** (`night_teacher9.ps1`, 2026-10-18 03:15) — the plan's two runs.

The decode is deterministic (temperature pinned), so a variant of ONE model
differs by its setting alone; two TRAINED runs (night4/night5) differ by 5-8
words on the two dev sets that look like the tests and by ~45 on WhatsApp/d1.

## 2. What the measurements already settled

1. **Two identical runs differ by ~25 words on FLEURS and ~35 on Reversim**
   (night4 vs night5). Any difference smaller than that is noise.
2. **The Claude-corrected training text helps** — both runs with it beat
   night3 on both tests — by roughly 1% (FLEURS) and 5% (Reversim) of the
   errors. Modest, real, already paid for.
3. **Our base model already learned from crowd-transcribe-v5, crowd-recital
   and the Knesset plenums** (its model card). Adding those again is
   *rehearsal*: it stops the model forgetting Hebrew, it cannot teach it new
   Hebrew. This is why plain Hebrew barely moves.
4. **ivrit.ai's large-v3 is not a better teacher and not a better base**: no
   better on either test, 3.5× slower (measured today). That road is closed.
5. **The strongest teacher we have is Claude reading our model's output.**
   Sonnet 5.5's fix took FLEURS from 19.61% to 17.22% (−12% of the errors) —
   better than any model we have trained. Text in, text out; the audio stays
   on this PC.
6. **The FLEURS gap left is mostly style**: of night4's 20 extra words, 9 are
   foreign names written in Latin where FLEURS writes Hebrew letters.
7. **The app's own `repetition_penalty=1.15` costs words — more than any
   training night gained** (Stage 0 sweep, 2026-10-14). At 1.0, today's model
   makes 8% fewer errors on FLEURS dev, 24% on WhatsApp, 17% on d1, 1.5% on the
   FLEURS test and 3% on the Reversim test; 1% more on Reversim dev. 1.05 sits
   between. Night4 gains the same way (WhatsApp 1,131 → 833). It penalises every
   token already written, and Hebrew repeats its small words and prefixes
   legitimately: "את זה" → "לזה", "רעיון" → "חיאיון". It went in on 2026-08-13
   against one 222-ה loop and was "measured byte-identical on clean audio"
   (short clips). Without it the decoder looped on 2 of 1,912 clips with
   today's model and 3 with each trained one, always one word over and over
   ("ושבע" x68 and "של" x22 on the FLEURS test, "זהו" x14 on Reversim, "רבה"
   x44 on d1). **His go, 2026-10-14 morning: branch `no-repetition-penalty`**
   — the first decode at 1.0, and a loop (a letter run OR a word loop) retried
   first with 1.15, then greedy, then the ladder. On the two looping clips
   the 1.15 decode is the one that comes back, so the app's expected numbers
   are the pen 1.0 rows with those two clips at their old values. The night
   scripts import the app's guards from the checkout, so from the day the
   branch is in the checkout every eval measures 1.0 — the rows above taken
   at 1.15 are then comparable only to each other.
8. **Every trained night is WORSE than today's model on the two sets that look
   like dictation** — WhatsApp and d1 — and the two night tests could not show
   it. Cause, measured (`label_length_check.py`): Reversim's transcripts are
   edited, and over the 18,739 training clips today's model hears ~20,000 words
   (4%) the text does not have — כן, אז, זה, אני, כאילו, זאת אומרת, גם; 35% of
   clips miss 2+. Claude's teacher labels kept them out (20,333). The nights
   learned to leave them out: words dropped on WhatsApp 100 (today) vs 221
   (night4); on d1 148 vs 262, plus one 58-word Knesset tail. The Reversim test
   itself is edited text, so it REWARDS the drop. More plain Hebrew (night3)
   and the teacher (night4) narrowed it; it did not close it. With the
   penalty off night4 still drops more (WhatsApp 137 vs 82) but matches or
   beats the app's CURRENT decode on all six sets (d1 and the FLEURS test by
   8 and 11 words only). Part of the rest is the style he wants
   (English in Latin: "אינץ" → "inch", "טוקנים" → "tokens"), counted as errors there.
9. **The tightened guard thresholds drop nothing on public speech**: stock
   no_speech 0.6 / log_prob -1.0 / compression 2.4 gave byte-identical text on
   all 778 items (262 min); the silence cut off changed 2 of 54 WhatsApp
   messages by one word. Beam 1 and beam 8 are within ±2% of beam 5 — beam 5
   stays.
10. **The dev sets agree with the tests where they overlap**: FLEURS dev and
   the FLEURS test both put today's model first and night2 last, the rest
   within noise; the teacher labels' gain shows on Reversim dev too (night3
   1,009 → night4 822, far above the 5-word spread).

## 3. The plan, in stages

### Stage 0 — measure so we cannot fool ourselves (free) — DONE 2026-10-14

Built and run the night of 10-13 → 14 (§1, findings 7-10). The sets live in
`DeskIT-training\data\public\stage0\` (one `test.json` each, the two tests
too); one scorer, `scripts\eval_set.py <model> <set> <out>` (the night
scripts' formulas, checked to reproduce night4's counts exactly);
`scripts\stage0_run.ps1` runs models × sets into `runs\stage0\` and writes
`report.txt`; `-Tag/-Guards/-Beam` run a decode variant; `stage0_compare.py`
says which words two models differ on. night6 is scored on all of it by
itself once its own report lands (two runners wait for it: the app's decode,
then pen 1.0 with both tests).

- **A decision set separate from the tests.** Until now every choice was made
  on the two tests themselves, so the tests slowly stop being tests. From now
  on: choose on **FLEURS dev** (Google's own dev split, free download) and a
  **Reversim dev** (3-4 of the 29 older episodes with transcripts we never
  downloaded); open the tests only to confirm a winner.
- **Two more tests that look like dictation**: ivrit.ai's **eval-whatsapp**
  (spontaneous voice messages, consumer phones, expert-transcribed) and
  **eval-d1**. Both gated — he accepts their terms on Hugging Face.
- **Two runs of any recipe** whose gain is under ~40 words; decide on the mean.
- **Speed is a test too**: every candidate decoded in the app's own mode;
  anything slower than today's model needs his word.

### Stage 1 — squeeze the recipe (free, ~6-8 nights, one change a night)

Each night changes ONE thing against the best recipe so far, judged on dev:
- **night6 (done 2026-10-14)**: all 251 h of crowd-transcribe (rehearsal at
  scale) + Reversim twice — level with night4, see §1.
- **night9 (armed for 2026-10-18 03:15)**: night8 again, to measure its spread.
- **night8 (done 2026-10-16, `night_teacher8.ps1`; §1)**: night7 with
  ONE change — the Reversim clips whose verbatim label still lacks 2+ heard
  words left out, both copies (`build_night8_data.py`,
  `train_lora_night8.py`): 13,124 of 18,739 clips kept, 34.9 h, 62% of the
  English words. If WhatsApp and d1 reach today's model while Reversim holds,
  finding 8 is closed; if the English drops, the middle road is "at most two
  missing" (81% of clips, 74% of the English).
- **night7 (done 2026-10-15) — the labels made verbatim**:
  night4's recipe with `runs\teacher\labels_verbatim.jsonl`
  (`build_verbatim_labels.py`): the Hebrew words today's model heard and the
  label lacks, put back where nothing else changes there — 6,357 words in 22%
  of the labels (כן 540, אז 386, זה 309, כאילו 217, זאת אומרת 176…), never at a
  clip's edge, never a lone letter or a hesitation noise, never touching the
  label's English. Judged on WhatsApp and d1 at pen 1.0. The other road,
  keeping only clips that miss at most one heard word, keeps 61% of the clips
  but only 55% of the English words.
- the add-on also on the **encoder** (the part that hears) — the only place a
  plain-Hebrew *hearing* error can be fixed;
- a bigger add-on (rank 64), or the whole 4-layer decoder trained outright;
- learning rate ×0.5 and ×2;
- Reversim's share of the mix (17% / 33% / 50%);
- the share of labels with timestamps.
Free decoding-side sweep (no training): beam size and the guards, on dev —
a gain there applies to every model. **Run 2026-10-14** (`stage0_sweep.ps1`,
`stage0_sweep2.ps1`): finding 7 (the penalty) and finding 9 (nothing else).

### Stage 2 — new knowledge (his clicks; Claude only with his yes)

The base has not seen these:
- **knesset-committees** (May 2026): human protocols of committee sessions —
  new plain Hebrew, many speakers, formal register. Free.
- **audio-v2**: 20,000+ hours of Hebrew podcasts with machine transcripts
  (made by our very base model). Taken alone, those transcripts teach the
  model its own mistakes. With **Claude as the teacher** — the same pipeline
  as the Reversim labels, Sonnet correcting each clip against our model's
  hearing, English terms in Latin — they become better than the model that
  wrote them (finding 5). Start with the tech and startup shows (Geekonomy,
  MDLI, AnotherPodcastForStartups, TheOptimizer…): mixed Hebrew-English,
  exactly his use. **Estimate before asking him**: Sonnet through the Batch
  API ~$0.85 per 1,000 clips (measured), so 30,000 clips (~80 h) ~$26,
  60,000 ~$51 — asked as a separate yes, with the cap enforced in code as
  on 2026-10-10.
- a **name-style pass** on all training text (foreign place and person names
  in Hebrew letters, tech terms in Latin) — aimed at the FLEURS style gap;
  cheap, only clips with names; estimated before asking.

### Stage 3 — combine (free)

- **Model soup**: average the add-ons of the best 2-4 runs into one model —
  usually steadier than any single run.
- **Iterate the teacher**: the improved model hears the clips again, Claude
  corrects again, train again (each round better text → better model).

### Stage 4 — choose and ship

The winner confirmed on all four tests (FLEURS, Reversim, whatsapp, d1) and
on speed; then his Dev copy for a few days of real dictation; then the
product decision (house rule 9). Separately, the Claude fix **behind** the
paste (the second reading) stays a product option: it measured −12% errors
on FLEURS at ~1.5 s that nobody waits for.

## 4. What he needs to do

1. On Hugging Face (signed in as yoav53), accept the terms of:
   `ivrit-ai/eval-whatsapp`, `ivrit-ai/eval-d1`, `ivrit-ai/knesset-committees`,
   `ivrit-ai/audio-v2-opus`, `ivrit-ai/audio-v2-transcripts` (checked today:
   all five closed to his token; crowd-transcribe-v5 is open). Done the same
   evening: all five open.
2. Say yes or no to each Claude spend when it is asked, with its estimate.
3. Keep DeskIT running at night (it is what keeps the PC awake).
4. (2026-10-14) The repetition penalty (finding 7): decided — off on the first
   decode, kept for loops; branch `no-repetition-penalty`, his Dev copy next.
5. (2026-10-14) Decide night7 (verbatim labels, Stage 1) after night6's numbers.

## 5. Ruled out, and why

- ivrit.ai large-v3 as base or teacher — measured, no better, 3.5× slower.
- Training on his own dictations — his rule: the app is for everyone.
- Paid speech APIs — house rules 1 and 2.
