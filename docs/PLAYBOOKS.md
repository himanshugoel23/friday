# Playbooks: scripted calls to businesses, one data file per business type

A **playbook** is a script for one kind of call (salon booking, pharmacy order, ...). It is a data file: the exact words Friday says, and what she does for each thing the other side might say. A new business type is a new file. No code.

Why: a call that follows a script is predictable. Friday's words never change by surprise, a founder can read every sentence she can say, and every call can be rehearsed in simulation before a real phone rings.

What stays the same for every playbook (enforced in code, not in the file):

* The AI disclosure is the first thing said, always. It is short and ends in one question; Friday then waits for the answer.
* Friday never confirms or books unless the user delegated the decision ("any slot 5-7 pm under 800, you decide") AND the offer fits those limits. Otherwise she says she will call back after approval.
* She never says OTP, PIN, card or password words, and never agrees to an advance or a payment.
* If the other side says "don't call again", the call ends politely and the number is blocked for good.
* Hinglish only. If the salon answers in pure Hindi or English, Friday still replies in Hinglish.
* A call has a maximum length, a maximum number of questions, and a maximum number of times one question is repeated.

The one place an AI model is used: **understanding what the salon just said** (a fixed list of "intents" plus a few values such as the price). The model never writes Friday's words. If it is confused, the answer is "Sorry, ek baar phir?".

## The salon playbook

`friday/playbooks/data/salon_booking.yaml` implements the founder draft in `docs/playbooks/salon_booking.md` (S0 to S7, S2b, S3b, confusion handling, outcomes). The call opens with a short disclosure that ends in one question ("Hello, main Friday, ek AI assistant, baat kar rahi hoon. Kya meri baat {business_name} se ho rahi hai?"); step `S0` then speaks nothing and just waits for the salon's answer (yes goes to S1 "Main Rahul ji ki assistant hoon, unki appointment ke regarding call kiya hai. Kya abhi do minute baat ho sakti hai?"; wrong name ends the call politely; "kaun bol raha hai?" gets a one-line answer). Two small extras: `S2t` ("Kitne baje ka?" when she says yes without a time) and `S3r` (the read-back "Matlab 400 rupaye... Sahi?").

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
* a disclosure that does not say Friday is an AI; a step with no `ask` (only the `start` step may, it just waits, and the disclosure must then end in a question); a step nobody can reach; an outcome called BOOKED that is not the delegated commit.

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

No phone, no network, no AI key, no cost. The real call runner and the real playbook engine talk to simulated salons defined in `friday/playbooks/data/salon_booking.personas.yaml`: friendly with a free slot, busy, puts her on hold (and never comes back), "kaun bol raha hai?", "robot hai?", pure Hindi, price over budget, asks for an advance, no slot then two alternatives, noisy line, rude and hangs up, asks for the customer's number, wrong number, asks for an OTP, asks not to be called again, delegated booking... To add a persona, add an entry to that file: it lists what she answers to each line (by line id, so it keeps working when you change the wording). The identity question is the line id `disclosure` (also `s0_who`, `s0_repeat`); a persona that does not list it answers "Haan ji, boliye".

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

## Drafting a playbook for a new business type

Writing a playbook by hand is slow. The **script author** drafts one for you, OFFLINE, in a few minutes, so a new business type (clinic, restaurant, garage...) costs a review, not a project. It never runs during a call: on a live call Friday still says only fixed, validated lines, and no model writes her words.

```
uv run friday playbook types                                  # the business types it knows
uv run friday playbook draft clinic_appointment               # free, offline, no key, no network
uv run friday playbook draft clinic_appointment --live        # a real AI model writes it (costs a little)
uv run friday playbook draft clinic_appointment --rounds 2    # fewer improvement rounds
uv run friday playbook promote clinic_appointment             # copy a REVIEWED draft into use
```

### What it does (the loop)

1. **Draft.** It writes the playbook and 20 to 25 simulated businesses ("personas") for the business type, from what we know about how that kind of business answers the phone: who picks up, what they ask, what they quote, what they will not say, and the awkward things (put on hold, "WhatsApp pe bhej do", "doctor busy hai", token system, booking amount, walk-in only). That knowledge is `friday/playbooks/authoring/business_types.yaml`; you can improve it like any text file. Eight types are included: clinic, restaurant table, car service, plumber/electrician, hotel room enquiry, gym membership, dentist, pharmacy/grocery order status.
2. **Validate.** The same checker as for the salon (`friday playbook validate`) reads the draft. Every problem it finds is sent back to the writer to fix.
3. **Dry-run.** The draft is rehearsed against its simulated businesses, exactly like `friday playbook dry-run`.
4. **Patch.** Whatever failed (a reaction the script does not handle, an ending that is not what a sensible script would give, a limit exceeded, a safety problem) is sent back to the writer to patch. Back to step 2, up to `--rounds` times (default 3).

A **safety violation is never waived.** It cannot be marked "accepted"; deleting the simulated business that exposed it does not help either, because every draft must keep the safety tests (a "don't call again", an OTP ask, a wrong number, a rude hang-up, a delegated booking) and the report calls out any that were removed.

Everything goes to a **drafts folder**, never into the real playbooks: `var/playbook_drafts/<business_type>/` (change it with `--out DIR`; pointing it into `friday/playbooks` is refused).

| file | what |
|---|---|
| `playbook.yaml` | the draft script |
| `personas.yaml` | the simulated businesses |
| `report.md` | the plain-language summary for you (read this first) |
| `dryrun.txt` | the dry-run table (same columns as in "Reading the table") |

### Offline or `--live`

| | default (offline) | `--live` |
|---|---|---|
| who writes it | a fixed template filled with the business type's words | a real AI model, once |
| cost / key / network | none / none / none | costs money / needs an AI key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) / yes |
| result | valid, safe, but generic; the same structure as the salon | richer, more specific to the business; may need patch rounds |
| improvement rounds | nothing to fix, so normally 0 | the model fixes its own validator errors and failed rehearsals |

`--live` refuses to start without a key, and prints its **budget before it spends anything**: the maximum number of rounds, the maximum number of model calls, the maximum output size per call, and a worst-case cost estimate in rupees. The report states what was actually used. The model is chosen by the cost-routing rule under the purpose `playbook_author` (a bigger model than the background jobs, allowed because it runs once per business type; never Opus, never on a call). Costs are estimates, not bills. Use `--live` when the offline draft is too generic for the business, and always read the result: a model can write a nice-sounding line that is wrong for the business.

### What to review (this is the job)

Open `report.md`. It says, in plain words:

* **Status**: ready for review / needs work / blocked: safety / failed. Only "ready for review" can be promoted, and even that is only a draft.
* **The steps**: what Friday asks, in order, and how many reactions each step handles.
* **What failed and what was fixed**, round by round, and anything still failing.
* **Safety result**: must be clean.
* **Test changes the model made**: if a patch round changed what a simulated business was expected to do, or removed one, it is listed. Check those: a patch that "fixes" a failure by weakening the test is not a fix.
* **Lines needing human review**: every line, with the important ones flagged (the AI disclosure, the one line that books, anything about money, advance, booking or confirmation, long lines). Every line of a new draft is new; you read all of them. Things to look for: is it natural Hinglish for that business? Is it too long to say in one breath? Would a real receptionist find it rude, pushy or confusing? Does any line promise something Friday cannot do?

Also open `playbook.yaml` and read the questions Friday asks in order: does the call make sense for this business, and does it stop after the questions that matter? Edit the file freely (fix a line, remove a question). After editing, check it: `uv run friday playbook validate var/playbook_drafts/<type>/playbook.yaml`.

### Listening to audio samples

The lines are text until you hear them. For any line:

```
uv run friday say "Hello, main Friday, ek AI assistant, baat kar rahi hoon. Kya meri baat Sharma Clinic se ho rahi hai?" --out var/preview/clinic.wav
```

Fill the `{...}` values yourself (name, business) when you paste a line. Listen to at least the opening, the price question, the read-back and the closing line; use `--pace 0.9` to try a different speed. This uses the real voice and the Sarvam key, so it costs a very small amount per line.

### Promoting a draft

```
uv run friday playbook promote clinic_appointment
```

Promote looks at the draft as it is on disk NOW (including your edits) and refuses unless all of this holds: it validates; it keeps all the safety tests; the dry run has **zero safety violations** and every simulated business passes; no playbook with that name exists yet (it never overwrites). Then it asks you to **type the business type name** to confirm; anything else copies nothing, and there is no `--yes` shortcut. On success it copies the playbook and personas to `friday/playbooks/data/`. Then run `uv run friday playbook dry-run <type> --update-baseline`, read the table, and commit the new files.

Promoting does not start any calls. A promoted playbook is used only for calls whose task matches its `select:` (task type and category or keyword), and your first test call with it should go to your own second phone, like the salon (see "Placing a test call with a playbook").

### What this does not prove

The simulated businesses are written by the same author (a template or a model), so they share its blind spots. A clean draft means: the script is valid, safe, and handles the cases we thought of. It does not mean a real receptionist will answer as expected. The first test calls and the weekly labelling of real calls (docs/QUALITY_LOOP.md) remain the real test; every surprise becomes a new persona, then a fix.

## Placing a test call with a playbook

```
uv run friday livecall --playbook salon_booking --to +91XXXXXXXXXX --on-behalf-of Rahul --when "kal shaam" [--service haircut] [--budget 600] [--stylist Amit]
uv run friday livecall --playbook salon_booking --simulate --yes --to +919000000000 --on-behalf-of Rahul --when "kal shaam"   # no real call
```

Every existing guard applies: the number must be in `FRIDAY_PILOT_ALLOWED_NUMBERS`, the spend cap and the maximum length apply, only one call at a time, you must type YES. A test call has no delegation, so it can never book. `--on-behalf-of` is the first name Friday says ("Rahul ji ki AI assistant"). Your second phone plays the salon: say the awkward things (busy, "robot hai?", a price over budget, "dobara call mat karna") and read the transcript in `var/livecalls/`.

Voice pace: `FRIDAY_TTS_SPEAKING_RATE` (default 1.0, see `.env.example`) sets how fast Friday speaks; pick it by listening to audio samples before changing it.

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
| `friday/playbooks/authoring/business_types.yaml` | what we know about each business type (offline use only) |
| `friday/playbooks/authoring/` | the script author: prompt, offline template, loop, report, promote |
| `var/playbook_drafts/<type>/` | drafts (never in `data/`; not committed) |
| `tests/playbooks/` | loader, every branch, approval rule, DNC, hold, Hinglish, scoring, cost |
