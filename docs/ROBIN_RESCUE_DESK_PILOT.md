# Robin rescue desk: pilot plan (4-20 families), 2026-11-04

Founder decision (2026-11-04): the founder starts the rescue desk himself for a pilot of 4-5 families, growing to about 20. The child's consent counts as the parent's (consent_basis admin_on_behalf); the parent is told and can stop. Status: PLAN ONLY, nothing built. All scripts and lines are PENDING founder approval.

## 1. What the desk is in the pilot
A **human on duty (the founder or a named teammate)** who is paged when Robin raises a HIGH or EMERGENCY alert, takes over the conversation with the parent (by phone, using Robin's number/line), and decides the next step: stay on the line, call the child, call a second contact, call 112 or the bank, or stand down. Robin (AI) always acts first, within a minute: rings the parent, rings the child, pages the desk.

## 2. Honest promise to families (do not promise what you cannot staff)
- Pilot desk hours: set them and say them (for example 8 am to 10 pm). Outside desk hours Robin works alone and tells the child plainly: "desk is off; for an emergency call 112 yourself or ring your parent".
- Never write "24/7", "we will call the police for you" or "guaranteed" in any message until the staffing and legal review exist.
- Covering ONE seat around the clock takes about 5-6 people (168 hours a week divided by about 40 hours, plus leave): arithmetic, not a quote. A pilot of 5-20 families with one founder means business hours plus a defined on-call window.

## 3. Alert tiers and what pages the desk
| Tier | Example | Robin does | Desk |
|---|---|---|---|
| INFO / WATCH | one unknown call, medicine missed once | digest or a parent nudge | not paged |
| HIGH | long unknown call plus a payment app opened, remote-access app, payment alert above limit, parent unreachable after retries | rings parent and child at once | paged (WhatsApp + call to the desk phone) |
| EMERGENCY | SOS press, "I am being threatened" button, danger words, no answer after the ladder | rings child, second contact | paged at once, takes the call |
Desk ack within 3 minutes or Robin keeps the family ladder going and says so in the log.

## 4. Standard procedures (draft, each needs founder approval and a lawyer's read)
1. **Scam in progress** (parent on a suspicious call or video): get the parent off the call ("Aap phone kaat dijiye, main Robin ki taraf se hoon, aapka beta ne mujhe bataya hai"), do NOT ask for OTP or PIN, confirm no money has moved, tell them there is no "digital arrest" in India, stay on the line until the child is on, then log.
2. **Money already sent**: first-hour playbook with the child: call 1930 (cyber fraud helpline) and the bank's helpline now, ask the bank to freeze the transfer, note the transaction ids, file at cybercrime.gov.in, draft the police complaint for the child to submit; be kind and blame-free.
3. **Medical emergency**: ask the parent how they are, call 112 or the local ambulance number with the parent's consent recorded at setup (say clearly who you are and the address), call the child, stay on until help arrives; never give medical advice beyond "ask the doctor".
4. **Parent unreachable**: call, retry, call a neighbour or second contact named in advance, then the child decides; the desk does not send anyone to the home without the child's instruction.
5. **Distress words from parent or child**: switch to the care protocol (docs/CARE_PROTOCOL.md), name 14416 and 112, no pep talk, no diagnosis, hand to a human voice if the person agrees.
6. Close every incident with a log: what happened, signals, actions, times, who was called, result. The child gets a plain summary.

## 5. Authorities and data rules
- Contact authorities only with the family's consent recorded at setup (extra checkbox: "desk may call 112 or my bank on my parent's behalf") and the minimum facts needed. Keep a record of what was shared.
- Authority/bank contacts are by phone; no automated calls to 112/police.
- Incident logs are encrypted, short retention (set by the family), erased on request; recordings of desk calls only with an audible disclosure and a stated retention; no distress content in training data or analytics.
- Legal review before onboarding any real family: consent on behalf of an adult parent, acting for a parent with authorities, call recording rules, DPDP notice, liability wording in the plan terms.

## 6. Tooling to build (after the family and device packages merge)
A simple web **Desk console** (founder-only login): live alert list with tier, parent, child, why-line and timers; one-tap actions (call parent, call child, call second contact, join the parent's call, mark resolved, escalate to 112 script card, first-hour playbook checklist); script cards in the parent's language; incident notes and timeline; paging to the desk phone by WhatsApp and a ringing call; daily summary (alerts, false alarms, response times); a "shadow review" list for week one. Reuse: friday/urgent (escalation), friday/calls (CallGate), friday/robin alerts, evidence ledger, web admin patterns.

## 7. Pilot success measures
Median time from HIGH signal to a human voice on the line, false-alarm rate per family per week, scams stopped or flagged, parents still active after 30 days, children opening the digest, families willing to pay and at what price, desk hours actually needed per family (this decides unit economics).

## 8. Before the first real family
1. Hindi lines and voice approved by the founder (hear-before-change).
2. Meta WhatsApp token working (founder).
3. Legal review done; terms and consent text ready.
4. A trained second person for leave or sickness, even if only on call.
5. A dry run with the founder's own parents or friends' parents, with the scripts above.
