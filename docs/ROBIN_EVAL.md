# Robin safety evaluation set and regression gate (T18)

Tag on everything here: **unverified clinical/linguistic review needed.**

## What this is, said plainly
- The corpus is **small** (about 320 scenarios across six categories), **synthetic** (written by engineers; no real victim messages, numbers or call recordings) and **overfit-prone**: the detectors were tuned on similar wording, so a high score here says little about real-world accuracy. A perfect row is a reason to add harder cases, not to relax.
- It is a **regression gate**, not a safety certificate. It catches a rule change that makes things worse on known cases. It does not measure how Robin performs on real scams, real distress or real emergencies.
- All Hindi and Hinglish lines, and the whole care corpus (suicide / distress wording and idioms), need review by a **native speaker** and a **mental-health professional** before anyone treats the numbers as meaningful. The care rules are engineering drafts (see docs/CARE_PROTOCOL.md).
- Fakes only: no network, no real call, no message sent. Numbers and URLs are invented.

## Layout
| Path | Role |
|---|---|
| `tests/bench/robin/scenarios/scamcheck.yaml` | 103 texts: KYC, OTP/PIN, digital arrest, lottery, relative in trouble, remote-access apps, APK, utilities, pension, investment, safe account, links; benign bank OTP notices, family chat, festivals, news, awareness texts |
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

`known_gap: true` scenarios are real misses we know about: listed in the runner output (marked `G`), not counted in the gate. Fix the rule, then drop the flag (the lead then refreshes the baseline). There are none left at the moment.

## Current numbers (2026-11-10, after the safety-gap pass)
| Category | n | Precision | Recall | HIGH recall | FP rate |
|---|---|---|---|---|---|
| scamcheck | 103 | 1.00 | 1.00 | 1.00 | 0.00 |
| callpattern | 52 | 1.00 | 1.00 | 1.00 | 0.00 |
| care | 78 | 1.00 | 1.00 | 1.00 | 0.00 |
| emergency_words | 66 | 1.00 | 1.00 | 1.00 | 0.00 |
| emergency_ladder | 8 | 1.00 | 1.00 | 1.00 | 0.00 |
| emergency_flow | 15 | 1.00 | 1.00 | 1.00 | 0.00 |

Before this pass (2026-11-07): scamcheck 94 (recall 0.98, FP 0.03), care 68 (recall 0.91, HIGH recall 0.88, FP 0.03), emergency_words 30 (+5 known gaps). A perfect row is a reason to add harder cases, not to relax: every number above is on an engineer-written corpus that the fixes were tuned against.

## Findings closed on 2026-11-10 (all of them NEED REVIEW by a native speaker / clinician before anyone trusts them)
Emergency words (friday/robin/answers.py):
- Fall, chest-pain and breathing wording is now SOS-grade help (`answers.is_help`, so every path: parent_said text and voice note, widget voice, calls, typed commands). Matching is by whole words in a run (never a bare "gir" or "dard"): "main gir gayi hoon", "gir gaya hoon", "uth nahi pa rahi", "chakkar ... gir jaunga", "seene mein ... dard", "chest pain", "saans nahi aa rahi", "I can't breathe", "I've fallen" and Devanagari twins. "paani gir gaya", "chai gir gayi", "sar mein dard", "seene mein dard nahi hai" (negation within two words), "I fell asleep" do not fire.
- "help" and the other help words are now WHOLE words: "helpful", "madadgar", "helpline", "helping" no longer raise an SOS. Repeated letters count once, so "helppp", "madadd", "bachaooo", "bachaaao" still do (recall on a safety word is not lowered; the corpus has the stretched cases as gated positives). Also added: "helpme", "bachaiye", "bacha lo", Devanagari "हेल्प", "बचाइए", "बचा लो".
- Known limits: a help word inside a longer glued token ("bachaoplease") is not matched; "bachao" in "paise bachao" (save money) still fires (old behaviour, safe direction).
Care (friday/care/detect.py), new HIGH rules (**clinical review needed**): `en.see_no_reason_live` ("I don't see why I should keep living", "can't see the point in going on living"), `en.happier_if_gone` ("Everyone would be happier if I was gone", "my family would be so much happier without me"), `en.rather_be_dead` ("I would rather be dead than live like this", exempt when the thing is mundane: "rather die than eat that"). Food/weather/network hyperbole such as "chai ke bina mar jaunga", "wifi ke bina to main mar jaunga", "I will die without my coffee" and the Devanagari twin is NONE; the exemption is clause-local (it is a hyperbole pattern, not a word list on the whole message), so "chai ke bina mar jaunga. sach mein mar jana chahti hoon" is still HIGH. No threshold was lowered. Still open: "mujhe mar jana hai" (no "chahta") is NONE.
Scam check (friday/robindevice/scamcheck.py): new category `job_fee` (job word + fee word such as registration/joining/security deposit + pay verb, weight 3 = RISKY; not inside a warning or a negation; reason text PENDING native review in copy.py). "aaj raat" counts as urgency again only when it is not an ordinary plan ("aaj raat ka khana/party/film"), so a child asking for dinner money is no longer RISKY; "aaj raat tak 20000 rupaye bhej do warna..." and the utility-cut text are unchanged.
Call patterns: gap G1 of T16 closed (S4P HIGH is exempt from the shadow week per tier; WATCH stays log-only), see docs/ROBIN_FAMILY_CORE.md section 9.

## Not covered
Screening and listen-in (T16 not merged), real STT, real LLM second opinions, WhatsApp forward path (covered by tests/robin/test_scam_forward.py), voice/tone, long conversations, code-mixed spelling variety, any real user data.
