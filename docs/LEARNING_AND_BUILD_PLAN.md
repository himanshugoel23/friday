# Learning loop and build plan (13 Oct 2026)

Founder ask: build every script, and a model that keeps learning from his corrections and from real
customer calls (new questions, new answers, the way people talk).

## What "self-learning" means here (and what it does not)

Friday's spoken words stay SCRIPTED. A model that rewrites what she says on live calls would
hallucinate, repeat and drift (the founder's own top priority is that she must not). So the loop
learns in three places, and everything it proposes passes tests and the founder before it speaks:

1. **Style dictionary** (built: `friday/playbooks/style/`). Word swaps, fillers, call order,
   endings, approved lines. Each correction the founder gives is added (`friday playbook style-learn`).
2. **Listening model.** What the business said -> intent (price, busy, who is this, visit needed,
   asks event details, ...). This is the part that really learns from data:
   - every call logs each vendor utterance, the step, the intent chosen, the confidence, and
     whether the script had no branch for it (`unhandled`);
   - a review queue groups the unhandled / low-confidence utterances; the founder or a reviewer
     labels them in batches;
   - labels become the evaluation set (regression tests) and few-shot examples for the
     understanding prompt; after about 1-2k labelled sentences we fine-tune a small classifier;
   - a new version ships only if it does not lose on the evaluation set.
3. **Answer bank.** Questions businesses ask ("kaun sa phone hai?", "event kya hai?") with answers
   built ONLY from the user's own facts. New questions are proposed automatically; the founder
   approves the wording (audio first), then it joins the bank.

Rules that never change: hear before change; no spoken line changes without approval; no
invented numbers; the same line never repeats; user facts only; the repo is public (no real
call data, names or numbers are ever committed: the review queue lives under `var/`).

## Build order

1. Shared engine pieces (facts as inputs, phone/UPI capture with read-back, negotiation pushes,
   resume with prior answers).
2. Category split (restaurant table / hotel stay / banquet hall) and project-manager questions.
3. Pending playbooks for every approved script: salon, quote_and_slot, enquiry (+events/weddings),
   home_service_visit, pg_rental, cab_booking, stock_and_price, table_booking, hotel_booking,
   banquet_booking.
4. Callback tasks: negotiation call, confirmation call, retry with context.
5. Learning-loop tooling (collector, review queue, labelling, evaluation).
6. Audio review per script, then promote with the founder's approval marker.

## Watch list: Jev (TypeSafe AI decision model), added 13 Oct 2026

Not adopted. Possible later use: offline vendor-reply classification and review-queue triage only,
never in the live call turn and never for spoken words.
Before any trial:
1. Collect a few hundred real labelled Hinglish vendor sentences (masked, from `var/learning`).
2. Read and record the vendor's data terms; send nothing until user-data principle is satisfied.
3. Benchmark against the current listener on those labels; adopt only if it does not lose on the
   evaluation set and latency/cost are verified by us, not the vendor's claims.
Re-check in 4 weeks (Hindi support, consumer product, data terms).
