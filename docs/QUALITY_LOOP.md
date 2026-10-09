# The quality loop: making Friday's calls better from real calls

No fine-tuning. The loop is: **listen, label, turn what went wrong into a test, fix the prompt/copy, prove nothing got worse.**

## 1. What is kept from a call

After every call Friday answers, a transcript is kept **only if the caller agreed to storage** (the spoken "yes" at onboarding, recorded as a TERMS_PRIVACY consent). No consent, an unknown number, a refused call or a deleted user: nothing is written, not even a stub.

What is kept is cleaned first: PIN/OTP/card digits (also when said in words), phone numbers, long numbers and the caller's name are replaced with `[redacted]`, `+91******1234`, `[number]`, `[name]`. The transcript and your notes are encrypted in the database (same field encryption as the rest of the user data).

Kept for **30 days** (`FRIDAY_QUALITY_TRANSCRIPT_RETENTION_DAYS`), then deleted by the daily retention job (or `friday review purge`). If a user says "delete everything", their transcripts go with the rest.

## 2. Reviewing and labelling (a few minutes a day)

```
uv run friday review                       # recent stored calls
uv run friday review show <call_id>        # read the transcript
uv run friday review label <call_id> robotic too_long --note "reads like a script"
uv run friday review label <call_id> good
uv run friday review rate <call_id> 4      # 1-5, or up / down
```

Labels (fixed set): `robotic`, `interrupted_me` (Friday talked over the caller), `cut_me_off` (hung up / moved on too early), `wrong_answer`, `too_long`, `good`, `helpline_feel` (sounded like a call centre), `slow`, `language_mismatch` (replied in the wrong language). Label the bad ones and a few good ones.

Ratings: `record_rating(call_id, rating)` and `POST /admin/quality/rating` exist. The WhatsApp line asking for a rating is in `friday/quality/labels.py` (`RATING_PROMPT`) but **nothing sends it yet**.

## 3. Eval: the test that protects quality

```
uv run friday eval                    # 12 scripted callers, scored, compared to the saved baseline
uv run friday eval --update-baseline  # accept the current scores as the new baseline
uv run friday eval --from-labelled    # turn your labelled real calls into extra scenarios
uv run friday eval --live             # same, with the real LLM key (costs money; opt in)
```

Each scenario is a short script of what a caller says (`friday/quality/scenarios/*.json`): first call, returning caller, "are you human?", unclear audio, language switch, PIN said aloud, change of mind, a real-business request. Friday answers through the real front door on the fake model, so it is free and repeatable. Checks (no AI involved): AI disclosure first, honest about being an AI, no secret echoed, replies at most 2 short sentences, no helpline phrases ("Is there anything else", "Thank you for calling"...), consent never skipped, caller's language mirrored.

The table shows a score per scenario. If a check that **passed in the baseline fails now**, `friday eval` exits with an error: you made it worse. `--strict` fails on any failing check. Exported real calls land in `var/quality/labelled/` (not in git, they come from real people).

Note: the fake model tests Friday's fixed rules and wording, not how the real model phrases things. Use `--live` (optionally `--judge` for 1-5 rubric scores) before a release.

## 4. The weekly routine

1. Label the week's calls. 2. For each bad pattern, fix the prompt/copy. 3. `friday eval --from-labelled`, then fix until nothing regresses. 4. `friday eval --update-baseline` and commit the new baseline.

Refresh the baseline after any front-door rewrite lands, so it reflects the new behaviour.
