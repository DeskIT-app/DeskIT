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

## 3. The plan, in stages

### Stage 0 — measure so we cannot fool ourselves (free, this week)

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
- **tonight (night6, armed)**: all 251 h of crowd-transcribe (rehearsal at
  scale) + Reversim twice.
- the add-on also on the **encoder** (the part that hears) — the only place a
  plain-Hebrew *hearing* error can be fixed;
- a bigger add-on (rank 64), or the whole 4-layer decoder trained outright;
- learning rate ×0.5 and ×2;
- Reversim's share of the mix (17% / 33% / 50%);
- the share of labels with timestamps.
Free decoding-side sweep in the daytime (no training): beam size and the
three guard thresholds, on dev — a gain there applies to every model.

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
   all five closed to his token; crowd-transcribe-v5 is open).
2. Say yes or no to each Claude spend when it is asked, with its estimate.
3. Keep DeskIT running at night (it is what keeps the PC awake).

## 5. Ruled out, and why

- ivrit.ai large-v3 as base or teacher — measured, no better, 3.5× slower.
- Training on his own dictations — his rule: the app is for everyone.
- Paid speech APIs — house rules 1 and 2.
