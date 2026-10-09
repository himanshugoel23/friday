# Playbooks: scripted calls to businesses, one data file per business type

A **playbook** is a script for one kind of call (salon booking, pharmacy order, ...). It is a data file: the exact words Friday says, and what she does for each thing the other side might say. A new business type is a new file. No code.

Why: a call that follows a script is predictable. Friday's words never change by surprise, a founder can read every sentence she can say, and every call can be rehearsed in simulation before a real phone rings.

What stays the same for every playbook (enforced in code, not in the file):

* The AI disclosure is the first thing said, always.
* Friday never confirms or books unless the user delegated the decision ("any slot 5-7 pm under 800, you decide") AND the offer fits those limits. Otherwise she says she will call back after approval.
* She never says OTP, PIN, card or password words, and never agrees to an advance or a payment.
* If the other side says "don't call again", the call ends politely and the number is blocked for good.
* Hinglish only. If the salon answers in pure Hindi or English, Friday still replies in Hinglish.
* A call has a maximum length, a maximum number of questions, and a maximum number of times one question is repeated.

The one place an AI model is used: **understanding what the salon just said** (a fixed list of "intents" plus a few values such as the price). The model never writes Friday's words. If it is confused, the answer is "Sorry, ek baar phir?".

## The salon playbook

`friday/playbooks/data/salon_booking.yaml` implements the founder draft in `docs/playbooks/salon_booking.md` (S1 to S7, S2b, S3b, confusion handling, outcomes). Two small extras: `S2t` ("Kitne baje ka?" when she says yes without a time) and `S3r` (the read-back "Matlab 400 rupaye... Sahi?").

A task uses it automatically when it is a **booking** at a business whose category is salon / parlour / barber / spa, or whose request mentions haircut / facial / waxing and so on, **and** the task says when ("kal shaam"). Anything else keeps the normal AI-driven call. A confirmation call-back (after the user approved) is never scripted.

To change what Friday says: edit the text under `lines:` in that file, then run `uv run friday playbook validate salon_booking`.

## Writing a playbook for another business type

Copy `salon_booking.yaml` and change it. The parts, top to bottom:

```yaml
version: 1                  # file format version
id: pharmacy_order          # same as the file name
language: hinglish          # the only allowed value

select:                     # which tasks use it
  task_types: [order]
  categories: [pharmacy, chemist]
  keywords: [medicine, dawai]

inputs:                     # what the task must know before dialling
  user_first_name: {required: true}
  service: {required: true}
  date_window: {required: true}

limits: {max_duration_s: 180, max_repeats: 4, max_unclear_per_step: 2, hold_max_s: 60, max_turns: 30}

disclosure: disclosure      # which line is the AI disclosure
confusion: {line: sorry, outcome: UNCLEAR, close: bye_unclear}

lines:                      # EVERY sentence Friday can say. {slots} are filled in.
  disclosure: "Namaste, main Friday hoon, {user_first_name} ji ki AI assistant."
  s1_ask: "Kya main do minute le sakti hoon?"
  ...

routes:                     # shared "where next" decisions
  after_price:
    - {when: [has_stylist_pref], goto: S4}
    - {goto: S5}

defaults:                   # what every step does for these intents unless it says otherwise
  STOP_CALLING: {say: [bye_dnc], outcome: REFUSED, set: {do_not_call: "yes"}}

start: S1
steps:
  S1:
    ask: [s1_ask]           # lines spoken when the step starts
    branches:               # for each thing she might say, what Friday does
      YES: {goto: S2}
      NO: {say: [bye_busy], outcome: CALL_BACK_LATER}
      ASKS_REPEAT: {say: [s1_short], stay: true, max_uses: 1}

outcomes:                   # how the call ends, and how the rest of Friday sees it
  SLOT_OFFERED: {call_outcome: pending_approval, needs_quote: true}
```

What a branch can do (exactly one of): `goto: S3` (or `goto: "@route"`), `outcome: NAME` (end the call), `repeat: true` (say the lines, ask the question again), `stay: true` (say the lines, wait for her answer), `hold_s: 60` (wait silently, then ask again). It may also `say:` lines first, `set:` a fixed fact (`do_not_call`, `advance_needed`...), have a `when:` condition, and a `max_uses:` limit.

**The closed lists** (the loader refuses anything else):

* *Intents* (what she can say): `YES NO CONTINUE ACK BUSY_LATER WHO_IS_THIS ASKS_REPEAT ARE_YOU_BOT WRONG_NUMBER HOLD_ON SLOT_FREE SLOT_BUSY OFFERS_SLOTS GIVES_TIME NEEDS_APPOINTMENT ASKS_CUSTOMER_PHONE GIVES_PRICE PRICE_RANGE PRICE_DEPENDS REFUSES_PRICE NEEDS_ADVANCE NO_ADVANCE GIVES_STYLIST ASKS_OFFTOPIC ASKS_SECRET STOP_CALLING RUDE UNCLEAR`, plus `ANY` (everything not listed). The list lives in `friday/playbooks/intents.py`. A business type that needs a new intent needs a small code change there plus a rule in `understand.py`.
* *Conditions* (`when:`): `recording over_budget has_budget may_negotiate has_stylist_pref time_known slot_known price_known duration_known is_range has_offered can_commit first_ask`. Put `!` in front to negate (`"!duration_known"`).
* *Slots in lines* (`{...}`): `user_first_name service for_whom date_window budget stylist_pref callback_number slot price_inr duration_min stylist`.

**What the validator rejects** (run `uv run friday playbook validate <name>`; it lists every problem, not just the first):

* an unknown intent, condition, step, route, outcome or slot name; a missing line;
* any line with OTP, PIN, CVV, card, password, Aadhaar or UPI words;
* any line in Devanagari (lines must be Roman-script Hinglish), longer than 240 characters, or that claims to be human;
* any line that claims a booking or confirmation ("confirm ho gaya", "booked", "pakka") outside the one delegated-commit line. "Abhi kuch confirm nahi kiya" and "confirm karke call back karti hoon" are fine because they say the opposite;
* a disclosure that does not say Friday is an AI; a step nobody can reach; an outcome called BOOKED that is not the delegated commit.

**Booking is special.** Only one line can book (`commit: true`), only in the single `final` step named `commit_step`, and only when the user delegated AND the code-level check passes. If the runner's check says no, Friday falls back to "approval ke baad call karti hoon" automatically.

## Dry runs (rehearsal in simulation)

```
uv run friday playbook list
uv run friday playbook validate salon_booking
uv run friday playbook dry-run salon_booking                       # all simulated salons
uv run friday playbook dry-run salon_booking --scenarios hold,rude # only personas whose id contains these
uv run friday playbook dry-run salon_booking --show puts_on_hold   # read one conversation
uv run friday playbook dry-run salon_booking --paths               # which steps each persona visited
uv run friday playbook dry-run salon_booking --brain               # classify through the (fake) AI path
uv run friday playbook dry-run salon_booking --update-baseline     # accept the current scores
uv run friday playbook dry-run salon_booking --save-transcripts var/playbooks
```

No phone, no network, no AI key, no cost. The real call runner and the real playbook engine talk to simulated salons defined in `friday/playbooks/data/salon_booking.personas.yaml`: friendly with a free slot, busy, puts her on hold (and never comes back), "kaun bol raha hai?", "robot hai?", pure Hindi, price over budget, asks for an advance, no slot then two alternatives, noisy line, rude and hangs up, asks for the customer's number, wrong number, asks for an OTP, asks not to be called again, delegated booking... To add a persona, add an entry to that file: it lists what she answers to each line (by line id, so it keeps working when you change the wording).

### Reading the table

```
persona              outcome        exp  steps turns secs rep unh llm safe tts  score  vs base
friendly_free_slot   SLOT_OFFERED   ok       7     8   49   0   0   0   ok  ok   100%  same
```

| column | meaning |
|---|---|
| outcome | how the call ended (the playbook's outcome, or the runner's, e.g. `hold_timeout`) |
| exp | `ok` if it matches what the persona is expected to lead to |
| steps | number of steps visited (`--paths` shows which) |
| turns | things Friday said |
| secs | call length in (virtual) seconds; the limit is 180 |
| rep | questions asked again |
| unh | **unhandled intents**: she understood the salon but the step had no branch for it. This should be 0; each one is a hole in the script to fill |
| llm | AI model calls (0 offline; with `--brain`, at most one per salon reply) |
| safe | safety violations. **Must be `ok`.** Anything else prints the details and the command exits with code 2 |
| tts | `ok` if every fixed line was pre-rendered, so no speech-generation delay in the call |
| score | share of checks passed: reached an outcome, expected outcome, no safety violation, no unhandled intent, within limits, fixed lines pre-rendered |
| vs base | change since the saved baseline |

Safety violations the dry run looks for (independently of the engine): the AI disclosure not first; a word Friday said that is not from the playbook; Devanagari or a language switch; an OTP/PIN/card word; a booking or confirmation without delegation; an action the call runner had to block; a "don't call again" that was not honoured.

Exit codes: `0` fine, `1` a check failed or got worse than the baseline, `2` a safety violation (or the playbook is invalid). Commit `friday/playbooks/baselines/<name>.json` after a deliberate improvement, like the quality loop's baseline.

### The improve loop

1. Run the dry run. Look at the failing checks and at a few conversations (`--show`).
2. Fix the playbook (a line, a branch) or add a persona for a case you saw on a real call.
3. Run again; the `vs base` column shows what changed. Nothing may get worse.
4. `--update-baseline`, commit.

Dry runs prove the script and the engine, not the real salon's speech. The simulated salons answer with the words you wrote for them; real salons will surprise you. That is what the first live test call and the weekly labelling of real calls (docs/QUALITY_LOOP.md) are for: every surprise becomes a new persona, then a fix.

## Placing a test call with a playbook

```
uv run friday livecall --playbook salon_booking --to +91XXXXXXXXXX --on-behalf-of Rahul --when "kal shaam" [--service haircut] [--budget 600] [--stylist Amit]
uv run friday livecall --playbook salon_booking --simulate --yes --to +919000000000 --on-behalf-of Rahul --when "kal shaam"   # no real call
```

Every existing guard applies: the number must be in `FRIDAY_PILOT_ALLOWED_NUMBERS`, the spend cap and the maximum length apply, only one call at a time, you must type YES. A test call has no delegation, so it can never book. `--on-behalf-of` is the first name Friday says ("Rahul ji ki AI assistant"). Your second phone plays the salon: say the awkward things (busy, "robot hai?", a price over budget, "dobara call mat karna") and read the transcript in `var/livecalls/`.

Cost control: fixed lines are pre-rendered into the speech cache while the phone rings; lines with a price or a time are spoken sentence by sentence. The AI model is asked about a reply only when the offline rules are unsure (`FRIDAY_PLAYBOOKS_LLM_MODE=auto`, the default; `always`, `never`). It is one small request (purpose `call_turn`, a few tokens out).

## How this feeds fine-tuning later

Every call is a clean pair: *what the salon said* and *which intent it was*. A real call's transcript (kept only with consent, redacted, see docs/QUALITY_LOOP.md) can be labelled with the right intent; those labels are exactly the training data for a small classifier that replaces the big model for the "understand the reply" step, which is the only model use. Friday's side needs no training data: her lines are fixed. Failing dry-run personas and mislabelled real replies become the test set that a smaller model must pass before it replaces the current one. Simulated dry-run transcripts (`--save-transcripts`) are redacted the same way and marked `simulated`; they involve no real person, so no consent is needed, but they should not be mixed into training data as if they were real speech.

## Where things are

| file | what |
|---|---|
| `friday/playbooks/data/<name>.yaml` | the script |
| `friday/playbooks/data/<name>.personas.yaml` | simulated salons for dry runs |
| `friday/playbooks/baselines/<name>.json` | saved dry-run scores |
| `friday/playbooks/model.py` | file format, loader, validator |
| `friday/playbooks/engine.py` | the call policy that walks a playbook |
| `friday/playbooks/understand.py` | intent understanding (offline rules + the one model call) |
| `friday/playbooks/slots.py` | numbers, times and prices from Hinglish speech, sanitised |
| `friday/playbooks/dryrun.py`, `cli.py` | dry runs and `friday playbook ...` |
| `tests/playbooks/` | loader, every branch, approval rule, DNC, hold, Hinglish, scoring, cost |
