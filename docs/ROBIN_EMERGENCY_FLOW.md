# Robin: missed calls, emergencies and the AI emergency desk (Phase 1), 2026-11-04

Founder decision (2026-11-04), in the founder's words translated: (1) if the parent OR the child misses a call, the missed person gets a message; (2) if it is an emergency, the call's context goes with the message and Robin keeps ringing them to say it is an emergency; (3) safety checks for fraud; (4) a "911-kind" help desk run by Friday/Robin itself: on an emergency it automatically calls the customer's child and the authorities; NO human agent is involved at the start. This replaces the earlier human-desk pilot plan (docs/ROBIN_RESCUE_DESK_PILOT.md stays as a later option). All lines PENDING founder approval. Status: spec; builder instructed; nothing is live.

## 1. Missed call, either direction
```
caller rings the parent (or the child); no pickup
   -> carrier conditional forwarding -> Robin's number (friday/receptionist)
   -> Robin: "X is not available. Who is calling, and is it urgent?"
   -> caller answers (max about 60 s)
   -> NORMAL : WhatsApp message to the missed person: who, when, what they said (parent: text + short voice note in their language)
   -> URGENT : same message with the call CONTEXT first, and Robin starts ringing the missed person ("emergency" announcement), repeat every 3 min up to 6 tries
   -> pickup / acknowledgement / "I am fine" stops everything; the caller also gets a WhatsApp "X has been told"
```
Reuses friday/receptionist (answer, classify, message) and friday/urgent (acknowledge, repeat calls with caps). New: the family graph (who is the other person), the parent-friendly voice note, the "I keep ringing" loop with the emergency announcement.

## 2. What counts as an EMERGENCY (tiers)
| Source | Tier |
|---|---|
| Parent presses and holds SOS (widget), or says "Robin help" on a call/voice note | EMERGENCY |
| "I am being threatened" button / danger words (112, ambulance, "bachao", overdose, chest pain with breathlessness) | EMERGENCY |
| A caller says it is urgent in a missed-call message | URGENT (rings the missed person; EMERGENCY only if the person says so or the context contains danger words) |
| Fraud in progress (call-pattern HIGH, remote-access app, payment alert above limit) | HIGH (child ladder; authority route only via 1930 bridge, section 3) |
| Parent unreachable after the check-in ladder | HIGH (child, second contact) |
| Distress without a physical emergency | Care protocol (docs/CARE_PROTOCOL.md), not the desk |

## 3. The AI emergency desk (no human)
1. **Robin acts first, within a minute:** rings the child, WhatsApps the child and second contact with the context ("Papa pressed SOS at 7:42 pm; last check-in fine; location shared if allowed"), starts the ladder.
2. **Authorities, policy-gated** (module `friday/robin/authority.py`, switch `FRIDAY_ROBIN_AUTHORITY_CALLS` default OFF, **dry-run first**: it only logs the script it would speak):
   - **Physical emergency:** 112 (police/ambulance/fire). Preconditions: the admin recorded the `authority_calls` item at setup; a confirmed EMERGENCY (two independent signals, or the parent says yes); a spoken 60-second "I am fine" cancel window unless the parent is unresponsive; address and name from the profile; a calm fixed script (what, where, who, callback number); one authority call per incident; audit record.
   - **Fraud in progress or money lost:** Robin does NOT speak alone to 1930: it bridges the parent or the child to the cyber-fraud helpline 1930 on a conference line and hands the child the cybercrime.gov.in complaint draft and bank-freeze checklist (first-hour playbook).
   - **Never** auto-call authorities for fraud-only suspicion or distress-only cases.
3. **Why gated:** an AI that calls 112 can waste emergency capacity or cause harm through a false alarm, and the company carries the liability. India's 112 service is run by the state; whether and how an automated voice may call it is **unverified [U]**; ask a lawyer and the 112/ERSS operator before turning it on. We cannot test real 112 calls: tests use fakes and the dry-run log only.
4. **No human at the start means** all false-alarm handling is automatic: the cancel window, the "I am fine" word, the child's "I have it" button, caps on calls, and a daily review of incidents by the founder (read-only log, no live duty).

## 4. Pilot rollout order (my recommendation)
1. Week 1: missed-call messages and the repeat-ring loop only.
2. Week 2: SOS to the child and second contact, authority calls in DRY-RUN (the founder reads the logged script).
3. After legal review and a test with the founder's own family: turn on 112 calls for physical emergencies; 1930 bridging for fraud.

## 5. Open questions
1. Legal and operator check for automated calls to 112 and 1930.
2. Retry timing for EMERGENCY (default 3 minutes, 6 tries): is that right for a parent who may be asleep or in the bathroom?
3. Should Robin tell the caller (the child) when the parent is reached ("Papa picked up")?
4. Language and voice for the parent-facing announcements: founder approval of audio before any real call.
