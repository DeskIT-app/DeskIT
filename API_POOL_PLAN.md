# DeskIT — the API pool ("the API idea")

Written 2026-10-08 with the owner. **No code is written by this plan**; it is
the brief the code will be written from, and the one place a session lands
when he says *"let's move to the API idea"* / *"בוא נעבור לרעיון ה-API"*.

His words, 2026-10-08: give every user Claude Haiku 5.5 through DeskIT so
that nobody needs a subscription or a key of their own — *"Use Haiku 5.5 or
use your own API key"* — with a share per user, per day and per month, in
dollars or in calls, that follows how many users there are; and the master
app able to change those shares **live, without shipping an update**.

---

## 0. In one paragraph

The owner's Claude Max 5x plan includes $100 of Claude API credit every
billing cycle. DeskIT's own account server (the Supabase project that
already holds every user's sign-in) gets one small function that holds the
API key, checks the caller's share, asks Claude Haiku 5.5 to repair the
transcript, writes down what the call cost, and hands the text back. The
app treats it as one more repair backend, in front of Groq and Ollama, and
every reply still goes through the same guards (`_is_safe`,
`_keep_what_was_said`, `_tail_loss`) as today. Every number that decides
who gets how much lives in a table on the server, so the master app (or the
Supabase dashboard) changes it and the next call obeys. Nothing in the app
holds a quota, a price, a model name or a key.

---

## 1. Where the money comes from — checked 2026-10-08

From Anthropic's own pages (sources at the end):

| fact | what it means here |
|---|---|
| Max 5x includes **$100 / billing cycle** of Claude API credit (Max 20x $200; Pro and Free none) | the pool's ceiling; he is on Max 5x |
| credits **expire at the end of each cycle, no rollover** | an unspent dollar is lost, so a pool that runs at 80-95% is the target, not a saving |
| covers the Claude API, Managed Agents, the Agent SDK, the playground; **not Claude Code** | his own Claude Code use is the subscription and never touches the pool |
| every API key and workspace in the linked Console organization draws from **one balance** | his own experiments and the pool share the $100 — the pool gets a budget below 100 (§5.1) |
| a workspace can have its own **spend limit** | the pool gets a workspace of its own with a limit: the hard backstop if the code is wrong |
| **no payment method is required**; with no other credits, requests simply stop ("credit balance too low") until the next cycle; usage is never charged to the Claude plan | **never add a card or auto-reload to that Console organization.** That, and nothing in the code, is what guarantees house rule 1: the worst case is "the pool is empty", never a bill |
| credit terms: credits may not be transferred or sold, and *"may only be used by the holder of the Anthropic account"* | the key never leaves the server; users never get a key. The holder (his server) makes every call. Free-of-charge use on behalf of an app's users is not addressed by the pages — **ask Anthropic support once before launch** (§12) |
| credits arrive shortly after the plan payment, on his billing day, not on the 1st | the pool's cycle is anchored to that day (`cycle_anchor_day`); the Console's spend caps reset on the 1st, so the two calendars differ (§5.5) |

---

## 2. What a user sees

**Settings › Dictation**, the repair line, one menu:

- **Claude — free, through DeskIT** (the default for a signed-in Google account)
- **Claude — my own key**
- **Groq — my own key** (today's road)
- **On this computer** (Ollama)
- **Off**

Under the first choice, one plain line and nothing else: *"Today: about 140
dictations left · resets at midnight"* — or, when the share is spent,
*"Today's free share is used — back at midnight. Until then: Groq / on this
computer / no repair"*, naming whatever the person actually has. Never a card,
never a question (`no-floating-cards-for-questions`), never a stop: a
dictation always pastes; at worst it pastes unrepaired, as with the repair
off today.

**The wizard's Optional extras page**: the cloud-repair switch stops needing
a Groq key. On = the pool, with the consent the switch already is (the
owner, 2026-09-19: "whoever turns it on, that is enough"). The key field
moves behind *"Use my own key instead"*. This is the point of the whole idea:
a stranger gets the repair pass with nothing to sign up for beyond the
DeskIT account they already have.

**Settings › Privacy**: a key field for Anthropic beside Groq's and
Gemini's, same masked field, same [Save and test], same vault sync.

The share is counted in **dollars** and shown in **dictations**: the server
enforces micro-dollars (calls differ in size — a 3 s note and a 90 s
paragraph are not one unit), and the line converts with the average cost of
that person's last 20 calls.

---

## 3. One dictation, end to end

```
key released
  -> the decoder (local, unchanged; audio never leaves — house rule 2)
  -> vocab swap (unchanged)
  -> polish.py, provider "deskit":
       net.py  POST https://<ref>.supabase.co/functions/v1/pool
               purpose "pool", secret="supabase_session"  (the host and the
               secret already exist; only the purpose word is new)
               body: { purpose: "repair", text, glossary pairs }
  -> the function `pool` on the server:
       1. the session is real, the account is not anonymous (§8)
       2. pool_config.enabled, the purpose is on, the text is under its cap
       3. the per-minute rate, the person's day and month, the cycle (§5)
       4. Claude Haiku 5.5, thinking off, the server's own instructions for
          that purpose, max_tokens sized from the text
       5. one row in pool_usage: who, when, purpose, model, tokens, cost,
          milliseconds, outcome — never the text
       6. reply { text, left_today_usd, est_dictations_left, resets_at }
          or    { refused: capped | pool_empty | off | rate | too_long |
                            not_google | upstream }
  -> back in polish.py: _tail_loss, _is_safe, _keep_what_was_said — the
     same guards, whoever answered (house rule 3)
  -> paste
```

A refusal or a slow answer is not an error the user meets: `polish` moves to
the next backend the person has, inside the existing `cloud_wait_s` deadline,
and pastes the raw text if none answers in time — exactly today's behaviour
when Groq is slow.

**The instructions live on the server, not in the app.** The app sends the
transcript and the word pairs as data; the server owns the text that tells
the model what to do with them. Two reasons: a client that could send its own
system prompt would turn the pool into free general-purpose Claude for anyone
who reads the source (it is public), and an instruction fix becomes live with
no release. A test holds the server's template and `polish._prompt` to the
same words, so the two roads cannot drift.

---

## 4. The measured numbers — 2026-10-08

Measured on this checkout, read-only (`transcripts.log`, `vocab.json`,
`polish._prompt`):

| what | number |
|---|---|
| his dictations per day (16 days with dictation, 17 Sep – 8 Oct) | median 46.5, mean 52, p90 88, max 144 |
| transcript length | median 95 characters, p90 435 |
| the repair prompt's instructions alone | 1,148 characters |
| the same with his 60 glossary pairs | 2,741 characters |

**Not measured yet — the first job of the build (§11, gate A):** the token
count. `count_tokens` is free and exact; until it has run on 50 real prompts,
the cost below is an estimate. Estimate: ~1,000-1,500 tokens in, ~50-300
out with thinking off → **about $0.0002-0.0003 a repair on Haiku 5.5**
($0.10 / $0.50 per million). A new user's prompt is smaller (few or no
pairs). No prompt caching: the cacheable part is under Haiku's minimum, and
each person's glossary differs.

What $80 a cycle (§5.1) then buys, at $0.0003 a repair:

| kind of user | repairs / month | cost / month | users the pool covers alone |
|---|---|---|---|
| light (20 a day) | 600 | $0.18 | ~440 |
| like him (50 a day) | 1,500 | $0.45 | ~175 |
| heavy (90 a day, his p90) | 2,700 | $0.81 | ~100 |

A real population is mostly light users, so the pool runs out of money
later than the middle row suggests. The other ceiling is Supabase's Free
plan: **500,000 Edge Function invocations a month** (third-party pages agree;
confirm on supabase.com/pricing), against ~265,000 repairs at $80 — fine for
repair alone, worth watching if other purposes join (§9).

---

## 5. Dividing the pool

### 5.1 The budget

`cycle_budget_usd` — what the pool may spend per billing cycle. Default
**$80**, leaving $20 of the $100 for the owner's own experiments in the same
organization. The workspace spend limit sits a little above it ($90) as the
backstop that holds even if the function's own count is wrong.

### 5.2 Three modes — `pool_config.mode`, switchable live

**`rolling`** (recommended). Every call recomputes the day's share from
what is left:

```
left        = cycle_budget_usd - spent this cycle
days_left   = days until the cycle ends (at least 1)
active      = people with a pool call in the last 7 days (at least min_active)
daily_share = left / days_left / active * burst
daily_share = clamp(daily_share, min_daily_usd, max_daily_usd)
```

Unspent money flows forward on its own: a quiet first week raises everyone's
share in the third. A crowd arriving lowers it the same day. Nobody is
refused while the pool is full and the crowd is small.

**`even`**: `monthly_share = cycle_budget_usd / active`, `daily_share =
monthly_share / 30 * burst`. Simpler to explain; unspent shares are lost.

**`fixed`**: he types `daily_usd` and `monthly_usd` per person and the
server enforces exactly those. For a beta, or a launch day.

Whatever the mode, three things always hold: `max_monthly_usd_per_user` (no
single account may take more than, say, $3 of the pool), the per-minute rate
(`per_minute_calls`, default 20 — a dictation a few seconds long cannot need
more), and the **cycle guard**: at `spent >= cycle_budget_usd` every call
answers `pool_empty` until the next cycle.

`burst` (default 3) is what lets a person have a heavy day: the share is an
average, and a day three times the average is still served.

### 5.3 What the modes give, worked through (`rolling`, $80, day 1, burst 3)

| active users | daily share | ≈ repairs a day at $0.0003 | feels like |
|---|---|---|---|
| 10 | $0.80 | ~2,600 | unlimited |
| 50 | $0.16 | ~530 | unlimited |
| 200 | $0.04 | ~130 | unlimited for nearly everyone; his max day (144) just fits |
| 500 | $0.016 | ~53 | a heavy user meets the cap in the afternoon |
| 1,000 | $0.008 | ~27 | the free pool is a taste; own key is the real road |

The row where it starts to bite is the row where the master's Home says so
(§7), long before any user writes in.

### 5.4 One person, by hand

`pool_overrides`: a row per account that needs to differ — a higher share (a
tester, a friend who dictates all day), a lower one, or `blocked` with a note.
The master writes it; the function reads it before the mode.

### 5.5 The cycle

`cycle_anchor_day` = his Max billing day, so the pool's month is the
credit's month. The Console workspace limit resets on the calendar 1st; the
budget sits below the limit precisely so the two calendars never matter.

---

## 6. Live, with no update

Every number above is a column in **one row** of `pool_config` on the
server. The function reads it on every call (cached at most 30 s). So all of
this changes the moment he saves it, on every copy, with no release:

- the switch for the whole pool (`enabled`) — the kill switch
- the mode, the budget, the burst, every min and max, the per-minute rate
- the cycle anchor
- which purposes are on (repair first; §9)
- the model and its price per million tokens (so the cost arithmetic follows
  a model change), the effort, thinking on or off
- the instructions per purpose, and the text cap per purpose
- Google-only on or off
- every per-person override

What **does** need a release: the app learning the provider at all (once),
the Settings line's words, the consent card's words, a new purpose the app
has never called. After the first release, tuning the pool never needs
another.

Every change writes a row to `pool_config_log` — when, which field, old
value, new value — so any change can be read back and undone.

---

## 7. The master app — a seventh screen, "Pool"

**It reads** (the Supabase secret key stays on the Python side, MASTER.md
rule 5):

- the cycle: spent of budget as a bar, days left, and the projected
  end-of-cycle spend at the current rate ("on course for $71 of $80")
- people: active in 7 and 30 days, how many met their cap today, the ten who
  spent most this cycle (short account id, never the text)
- health: calls today, refusals by reason, upstream errors, latency p50 / p90
- the mode, and the share it is producing right now
- **Home** gets one line when something wants his eye: the pool on course to
  run dry before the cycle ends, a cap that more than a tenth of today's
  users met, an upstream error rate above normal. MASTER.md §4.6 already
  promises "a quota close to its limit" on Home; this is that line.

**It changes** every field of §6 and every override of §5.4, and nothing
else — one form, a [Save] that writes `pool_config` / `pool_overrides` and a
`pool_config_log` row, and the screen says when the server will have it
("live within 30 s").

**This is an amendment to MASTER.md rule 2** ("It performs no action on
anything … no server write"), and it needs his word before it is built: the
master gains exactly one write, to these three tables, through one call in
the bridge's allowlist. The alternative that keeps rule 2 whole: the master
only shows, and he changes the numbers in the Supabase dashboard's Table
Editor, which works today with nothing built.

---

## 8. Abuse and failure

| what can go wrong | what holds |
|---|---|
| somebody opens a thousand anonymous accounts to multiply the share | the pool serves **Google accounts only** (the JWT says whether an account is anonymous); `google_only` is live in case he ever wants it off |
| the public source is read and the function used as a free Claude | the server owns the instructions (§3); the client can send only text and word pairs, under a length cap; max_tokens is the server's; the model is the server's |
| one account takes the pool | the per-person month ceiling, the per-minute rate, the override's `blocked` |
| two calls in the same instant both pass the check | overshoot is bounded by one call's cost (~$0.0003) per concurrent call; the workspace limit is the backstop |
| the function has a bug and counts wrong | the workspace spend limit; and with no card in the Console the absolute worst is "credit balance too low", never a charge |
| Anthropic is slow or down | the function answers `upstream` at its own deadline; the app falls through inside `cloud_wait_s` and pastes raw if nothing answers |
| the model refuses (a safety stop) | treated as `upstream` for that dictation; counted, so the master shows it if it is ever more than a curiosity |
| the credit program ends or the plan changes | `pool_empty` from the first refused call; he flips `enabled` off; every copy falls back with no release. The idea depends on a promotion — it must never be the only road |
| Supabase Free limits (invocations, database size) | `pool_usage` is pruned to daily totals after 30 days; the master's Server screen already watches the ceilings |

---

## 9. Privacy and the house rules, one by one

- **Rule 1, all-free.** Free to every user, and free to him beyond the Max
  plan he already pays. Guaranteed by the absence of a card, not by code.
- **Rule 2, audio never leaves.** Only text, as with Groq today.
- **New for the privacy page:** the text now passes through **DeskIT's own
  server** on the way to Anthropic. It is held in memory for one call and
  never stored or logged (`pool_usage` has no text column, and a test reads
  the function's source for any logging of the body). The consent card for
  `cloud_text` gets new words naming both, which bumps its `text_version`, so
  every copy that already said yes is asked again on Home's pile — the
  mechanism exists. `NETWORK.md`, `docs/privacy.md`, and Anthropic's
  retention terms for API data (to be read and quoted, not assumed) go with
  it.
- **Rule 3, never rewrite the user's words.** Unchanged: the guards run on
  the reply whoever wrote it.
- **Rule 4, measure.** Gate A (§11) decides before a line of the app is
  written.
- **Rule 5, ~1 s.** Two more hops (the function, then Anthropic). Measured
  in gate A from this PC; the deadline is still `cloud_wait_s`.
- **`net.py`.** The pool needs no new host (it is the Supabase project) —
  only the purpose word `pool`. The own-key road needs `api.anthropic.com` in
  `ALLOWED_HOSTS` in its own commit and `"anthropic": ("api.anthropic.com",
  "x-api-key", "{}")` in `SECRET_HOSTS`.
- **Keys.** The pool's key exists in exactly two places: the Console, and the
  function's secrets on Supabase. Never in the repo, the app, a log or this
  file. A user's own Anthropic key lives where Groq's does (`secretstore`,
  name `anthropic`) and travels in the account lock like the others.

---

## 10. Beyond repair — later, one purpose at a time

Each is a `purpose` with its own instructions, text cap and switch in
`pool_config`, turned on only after its own measurement against what serves
it today: **punctuate** and **translate** (Gemini today, 20 a day per model),
**lookup**, **ask the screen** (Haiku 5.5 sees images; Groq's one vision
model today), the **notify sentence** (qwen on Groq today). Repair is first
because it is the only one every dictation can use.

---

## 11. Order, with the gates

**Gate A — measure (dev only, nothing ships).** With a key from the pool's
workspace, on this PC: `count_tokens` over 50 real prompts (the cost);
Haiku 5.5 against Groq's gpt-oss-120b on the honest labels this machine has
— his 164 second-reading verdicts and the 16 + 16 hand-labelled repairs and
harms of 2026-10-02 — run more than once (a single run is a draw); latency
from this PC p50 / p90. **Decision:** Haiku keeps at least as many good
repairs and lets through no more harms, and p90 fits the deadline → go. If
only Sonnet 5.5 is good enough, the pool covers about a twentieth of the
users in §4, and the idea is re-decided with that number.

**Then, each its own branch, in this order:**

1. **Hand work (his, one step at a time):** confirm the Console organization
   is linked to the plan; a workspace `deskit-pool` with a spend limit; a key
   in it; that key into the Supabase function's secrets; no payment method;
   one message to Anthropic support about serving the app's users (§1).
2. **The server:** migration `0007` — `pool_config`, `pool_overrides`,
   `pool_usage`, `pool_config_log`, their row-level security (a person reads
   only their own usage; only the function writes), the share arithmetic as
   one SQL function — and the Edge Function `pool` (TypeScript, the official
   Anthropic SDK). Tests against a local Supabase.
3. **The app:** the `deskit` and `anthropic` providers in `polish.py`, the
   `pool` purpose, the Settings line, the Privacy key field, the wizard
   switch, the consent words, `NETWORK.md`, the privacy page. Then the
   Stranger walks it (`dev\stranger.py`) before his own Dev copy does.
4. **The master:** the Pool screen, read-only first; the write (§7) only on
   his word about rule 2.
5. **Release**, as house rule 9 says — a beta first, since the wizard
   changes.

---

## 12. Open — his to decide

1. The budget split: $80 pool / $20 his own (§5.1)?
2. The mode to launch with: `rolling` (recommended) or `fixed` for a beta?
3. MASTER.md rule 2: does the master get its one write (§7), or does tuning
   happen in the Supabase dashboard?
4. Google accounts only (recommended)?
5. Is the remaining share shown as dictations (recommended) or as nothing at
   all until it runs out?
6. The message to Anthropic support about serving the app's users with the
   plan's credit — send it before gate A, or only if gate A says go?

---

Sources (read 2026-10-08):
[API credits for Max and Team plans — Claude Platform Docs](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers) ·
[Monthly API credits for Max and Team plans — Help Center](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-and-team-plans) ·
[Supplemental Credit Terms](https://www.anthropic.com/legal/credit-terms) ·
Haiku 5.5 price $0.10 / $0.50 per million tokens (the Claude API reference
bundled with Claude Code, cached 2026-10-06) ·
Supabase Free plan, 500,000 Edge Function invocations a month:
[designrevision.com](https://designrevision.com/blog/supabase-pricing.md),
[automationatlas.io](https://automationatlas.io/answers/supabase-free-tier-limits-2026/) — third-party, confirm on supabase.com/pricing.
