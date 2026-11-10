# Robin safety evaluation set and regression gate (T18)

Tag on everything here: **unverified clinical/linguistic review needed.**

## What this is, said plainly
- The corpus is **small** (about 270 scenarios across six categories), **synthetic** (written by engineers; no real victim messages, numbers or call recordings) and **overfit-prone**: the detectors were tuned on similar wording, so a high score here says little about real-world accuracy. A perfect row is a reason to add harder cases, not to relax.
- It is a **regression gate**, not a safety certificate. It catches a rule change that makes things worse on known cases. It does not measure how Robin performs on real scams, real distress or real emergencies.
- All Hindi and Hinglish lines, and the whole care corpus (suicide / distress wording and idioms), need review by a **native speaker** and a **mental-health professional** before anyone treats the numbers as meaningful. The care rules are engineering drafts (see docs/CARE_PROTOCOL.md).
- Fakes only: no network, no real call, no message sent. Numbers and URLs are invented.

## Layout
| Path | Role |
|---|---|
| `tests/bench/robin/scenarios/scamcheck.yaml` | 94 texts: KYC, OTP/PIN, digital arrest, lottery, relative in trouble, remote-access apps, APK, utilities, pension, investment, safe account, links; benign bank OTP notices, family chat, festivals, news, awareness texts |
| `tests/bench/robin/scenarios/calls.yaml` | 10 new call dialogues; `tests/robindevice/call_dialogues.yaml` (existing, 42) is run too. Through `friday/robindevice/callpattern.py` directly (T16 screening is not merged) |
| `tests/bench/robin/scenarios/care.yaml` | distress vs idiom, English, Hinglish, Devanagari |
| `tests/bench/robin/scenarios/emergency.yaml` | `words` (madad, bachao, threat, help), `ladder` (`plan_for` timings in call spacings), `flow` (real alert on a fake clock: SOS/threat/fall/HIGH at 03:00, paused parent, quiet hours still kept for WATCH) |
| `tests/bench/robin/runner.py`, `__main__.py` | the runner |
| `tests/bench/robin/baseline.json` | committed baseline. **Only the lead updates it.** |
| `tests/robin/test_eval_gate.py` | the gate and the negative controls |

## Running
```
uv run python -m tests.bench.robin             # table + every scenario not met
uv run python -m tests.bench.robin --verbose   # also the passing ones
uv run python -m tests.bench.robin --gate      # exit 1 if the baseline is not met
uv run pytest tests/bench/robin tests/robin/test_eval_gate.py -q
```
Lead only, after reviewing why a number moved: `uv run python -m tests.bench.robin --write-baseline`.

## Metrics (per category)
A scenario is *positive* (must be flagged / acted on), *negative* (must stay quiet), and some positives are *HIGH-risk* (money, OTP, remote access, arrest, suicide ideation, SOS, ladder). Precision = TP/(TP+FP); recall = TP/positives; HIGH recall = over HIGH-risk positives; FP rate = FP/negatives. Scam-check flags at RISKY or above; call patterns use the per-dialogue `min`/`max` tier; care uses HIGH/ELEVATED/NONE; emergency words flag `is_help`/`is_threat`.

The gate fails if, for any category, HIGH recall or overall recall is below the baseline, the FP rate is above it, or the corpus has fewer scenarios than the baseline (deleting cases is not a way to pass). The negative controls in `test_eval_gate.py` weaken a rule (OTP words, score thresholds, HIGH tier, care rules, SOS words, ladder) and assert the gate goes red.

`known_gap: true` scenarios are real misses we know about: listed in the runner output (marked `G`), not counted in the gate. Fix the rule, then drop the flag (the lead then refreshes the baseline).

## Current numbers (2026-11-07)
| Category | n | Precision | Recall | HIGH recall | FP rate |
|---|---|---|---|---|---|
| scamcheck | 94 | 0.98 | 0.98 | 1.00 | 0.03 |
| callpattern | 52 | 1.00 | 1.00 | 1.00 | 0.00 |
| care | 68 | 0.97 | 0.91 | 0.88 | 0.03 |
| emergency_words | 30 (+5 gaps) | 1.00 | 1.00 | 1.00 | 0.00 |
| emergency_ladder | 8 | 1.00 | 1.00 | 1.00 | 0.00 |
| emergency_flow | 15 | 1.00 | 1.00 | 1.00 | 0.00 |

## Findings (real misses, not fixed because the fix is not trivially safe)
Care protocol (friday/care/detect.py), the rule owner should decide with clinical input:
- Missed HIGH: `I don't see why I should keep living`, `Everyone would be happier if I was gone`, `I would rather be dead than live like this` (tier NONE).
- False HIGH: `chai ke bina mar jaunga main` (Hinglish hyperbole; `chai` is not in the `hg.mar_jana` exempt list).
Scam check (friday/robindevice/scamcheck.py):
- `Congratulations you are selected for a job at Amazon, pay Rs 2000 registration fee to confirm.` gives UNSURE (score 2): no job-offer-fee rule.
- `Aaj raat ka khana bahar khayenge, 500 rupaye bhej do mujhe UPI se.` (a child asking for dinner money) gives RISKY: money cue plus "aaj raat" counted as urgency.
Emergency words (friday/robin/answers.py), `known_gap`:
- Fall and chest-pain wording is not an SOS word: `main gir gayi hoon, uth nahi pa rahi`, `मैं गिर गया हूँ, उठ नहीं पा रहा`, `seene mein bahut dard ho raha hai`. Adding bare "gir"/"dard" would fire on "paani gir gaya".
- `_has_phrase` is a substring match: `the bank clerk was very helpful` (contains "help") and `padosi bahut madadgar hain` (contains "madad") raise an SOS. A strict word boundary would fix these but would also stop matching stretched spellings ("helppp"), which lowers recall on a safety word, so it was not changed.

Rule gaps fixed (more sensitive, safe direction, with tests in tests/care/test_detect.py): Devanagari `मर जाना ही बेहतर` (twin of the Hinglish rule) and feminine `akeli` in the isolation signal.

## Not covered
Screening and listen-in (T16 not merged), real STT, real LLM second opinions, WhatsApp forward path (covered by tests/robin/test_scam_forward.py), voice/tone, long conversations, code-mixed spelling variety, any real user data.
