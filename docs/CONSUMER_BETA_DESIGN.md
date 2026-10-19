# Consumer Friday beta: how we build the priority-1 problems (19 Oct 2026)

Source: the problem register (docs/CONSUMER_PROBLEMS.md; artifact with the founder's choices). Priority 1 = 56 problems, plus the
founder's own Musts (A1.1 to A1.8: calls to businesses, service providers, customer care, family and friends, officials, unknown people,
group calls, call-backs). Rules that never change: hear-before-change for every spoken or written line (new lines are PENDING until
the founder approves the audio/text), the model proposes and code decides, no invented numbers, user pays and Friday never pays, no OTP or card
handling, per-user data only, public repo (no secrets, no real numbers).

## The one decision to confirm: how free-form can a personal call be? (A3.1)
Business calls use approved scripts. Personal calls (family, friends, a plumber you know) cannot be fully scripted.
Recommended design, "bounded moves": the conversation is built from a closed set of MOVES (greet, disclose, state purpose, ask, answer from the brief, confirm,
handle objection, close, stop). Each move has approved fixed lines per relationship and language (pending audio approval). A model only picks the move and
fills slots from the user's brief; code checks every slot (numbers, times, names must come from the brief or the other person's words). A fully generated mode
exists behind a switch, OFF in the beta. Disclosure, stop, opt-out and "are you a bot?" lines are always fixed.

## Workstreams (each built in its own git worktree, merged by the lead)
- **W1 Call brief and safety** (before and after the call): A1.1-A1.8, A1.10, A2.*, A4.*, A5.1-A5.6, A5.8, A5.9, A6.1, A6.4, A6.8, D10 (legal map doc).
- **W2 Live call engine** (during the call): A3.*, A5.1 and A5.2 lines, A6.3, A6.5, A6.6, simulation personas.
- **W3 Savings engine v1**: B1, B2, B3, B4, B7, B8, B11, B13 (cards wallet by name, verified rules table, calculator, bills and reminders, forwarded-bill intake).
- **W4 Life state and proactive**: C1-C6, C8, plus the glue to the Google connector (Calendar clash check, morning brief, follow-ups).
- Cross-cutting D1, D2, D5, D6, D11 are done by the lead as small tasks after the four land (onboarding messages, identity, secure code page reuse, WhatsApp rules, labelling).

## Problem to approach (priority 1)
| Problem | Approach |
|---|---|
| A1.1-A1.8 call types | One `call_request` model with `callee_kind` (business, provider, customer_care, family_friend, official, unknown, group) and `purpose`; each kind has its own move set, disclosure wording and risk level. Group = a parent request that spawns child calls with a collected result. Call-back = a scheduled child call. |
| A1.10 vague request | Request understander returns missing fields; Friday asks one question at a time; never dials until who/what/limits are filled. |
| A2.1 who to call | `resolve_contact`: user's saved contacts (names/nicknames table, per user), ask when ambiguous, confirm the number back before the first call; no contacts-sync yet (user shares a contact card or types the number). |
| A2.2 goal and limits | `CallBrief`: goal, must-say, must-not-say, ask list, limits (budget, time, deadline), tone, relationship, language; stored with the request. |
| A2.3 missing facts | Same one-question-at-a-time flow as the quotes flow; closed question templates. |
| A2.4 approval of the draft | Brief summary + the opening line shown on WhatsApp; buttons Approve / Edit / Cancel; no call without approval (code check). |
| A2.7 refuse unsafe | Deterministic rules + classifier for harassment, threats, scams, pranks, impersonation, emergency numbers, minors; refusal text pending approval. |
| A2.8 cost and limits | Per-user daily call and minute caps, per-call max duration, global cap, kill switch (existing policy module). |
| A3.1 free-form | The "bounded moves" design above. |
| A3.2 first seconds | Fixed first move: name the user, say it is an assistant, state purpose in one sentence, offer "I can have X call you back". |
| A3.3 language and STT noise | Reuse Sarvam STT/TTS; language choice from the brief; repeat-back for numbers and times; ask to repeat when confidence is low. |
| A3.4 turn-taking | Reuse the barge-in stack; per-kind speaking pace; elder preset (slower). |
| A3.6 answering about the user | Answer only from brief facts classified `shareable`; everything else gets a fixed deflection ("main unse puchh kar bataungi"). |
| A3.9 commitments | A commitment guard: any promise (time, money, visit) not in the brief becomes `needs_user_approval`, the call says "I will confirm and call back"; confirmed items logged as outcomes. |
| A3.10 voicemail, IVR, hold, drops | Detect via simple signals (beep, "press 1", silence); voicemail leaves the fixed short message only if the brief allows; hold up to a cap; drop -> retry rules. |
| A3.11 when to stop | Hard stops: "stop calling", "wrong number", distress words, "are you a robot, don't talk to bots" -> polite fixed close and record. |
| A4.1 report | Plain-language outcome + transcript summary on WhatsApp within a minute; buttons for next action. |
| A4.3 retries | Existing policy (+1 h, +3 h, max 3); "do not call again" overrides everything. |
| A4.4 mistakes | Wrong person reached -> apology line and a do-not-call mark; user told immediately. |
| A4.5 recordings | Stored per user, retention default 30 days then deleted, user can delete now; never announced on call (founder decision); legal read pending (A5.5). |
| A5.1 disclosure | Always a fixed line at the start ("main <user> ki assistant hoon"); if asked "AI?" answer truthfully with the fixed line. |
| A5.2 impersonation | No voice cloning; the assistant never claims to be the user; a test asserts no "main <user> bol raha hoon" lines exist. |
| A5.3 do-not-call | Global registry keyed by hashed number across all users; opt-out phrase detection; checked before every dial. |
| A5.4 TRAI/DLT | Legal map doc in D10 + number/caller-ID configuration notes; counsel read before real recipients. |
| A5.5 recording law | Same doc; flag set per country/state; default store, never announce, founder decision recorded. |
| A5.6 caller ID | One caller number per user pool ("Friday" number), consistent, Truecaller business verification later; documented. |
| A5.8 abuse | Per-recipient frequency limits (max calls per number per day/week), pattern detection, user strikes and bans, report path. |
| A5.9 sensitive categories | Closed list of restricted topics (medical advice, legal, minors, emergencies, self-harm) with refuse/route lines. |
| A6.1 telephony | Number pool abstraction per user, provider limits as settings, cost per minute tracked. |
| A6.3 latency | Keep the existing latency budget; moves are pre-rendered audio where possible; measure and log per turn. |
| A6.4 cost control | Per-call token and minute budgets, hard cut-off, loop detector (existing repeat guard). |
| A6.5 reliability | Idempotent call creation, no duplicate dials, provider-error retries with backoff, kill switch. |
| A6.6 testing | Simulated callee personas per kind (suspicious, busy, friendly elder, voicemail, IVR, hostile, "who is this") run offline against the engine; regression set. |
| A6.8 code safety net | One `CallGate` (allow/deny/ask) in front of every dial and every commitment, reusing the connector gate pattern; allow-list in test mode. |
| B1 first spend areas | Food, grocery, fuel, bills, shopping: cards first (data we control), bills second. |
| B2 cards without numbers | Wallet table: bank + card name + optional monthly spend and cap used + billing date; no numbers, per user, encrypted. |
| B3, B4 rules and sources | `card_rules` table: card, category, rate, cap, exclusions, source_url, checked_on, verified_by; unverified rows are never shown; a person verifies. |
| B7 calculator | Pure code `best_card(spend, category, wallet)` with unit tests; the model only phrases the result. |
| B8 bills | `bills` table: biller, due date, amount, source (forwarded/Gmail/manual), status; reminders via the proactive engine; pay link only. |
| B11 neutrality | Ranking function takes no revenue input (tested); every recommendation includes a one-clause reason. |
| B13 data in | Forwarded text/photos/PDF to Friday's WhatsApp, parsed by deterministic parsers first, user confirms the parse. |
| C1-C3 life state | `life_events` and `life_commitments` per user with source (user, calendar, booking, bill), start/end aware datetimes in Asia/Kolkata, derived `now` status. |
| C4-C6 timing | Event-aware follow-up scheduler: after-event nudges, before-event reminders, protected events, quiet hours, daily caps, a one-clause reason on each, per-topic mute. |
| C5 channels | Text first; voice note and call only when the user opted in per topic. |
| C8 memory privacy | View, edit, delete, export commands; per-user encryption; existing DataPurger extended. |
| D1, D2 | First-minute onboarding script in WhatsApp (pending approval); identity by verified WhatsApp number, SIM-change re-verification. |
| D5 | Secure one-time page reused for any login code; never payment OTPs. |
| D6 | WhatsApp templates and 24-hour window handled by the existing channel layer; templates drafted for approval. |
| D10 | `docs/LEGAL_MAP.md` listing each rule, the question for a lawyer, and what blocks launch. |
| D11 | Every new spoken line lands in `pending`, with audio review kit; learning-loop labels extended to consumer call utterances. |

## Order and checkpoints
Four builders in parallel (separate worktrees, distinct migration numbers 0007 W1, 0008 W3, 0009 W4; W2 needs none). The lead merges, runs the full suite and reports to the
founder with: what exists, what is unverified, and the list of PENDING lines needing audio approval. Nothing real is dialled until the founder approves a specific test.
