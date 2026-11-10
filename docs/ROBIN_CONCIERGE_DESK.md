# Robin human operations desk: concierge lane + emergency/rescue lane (2026-11-10)

Founder decisions (2026-11-10): (1) the concierge is staffed by humans, hired in proportion to registrations; (2) correction the same day: "we will have human as well" for the emergency desk, so the desk is NOT AI-only. This replaces the earlier lead note "the emergency desk stays AI-only". Design only, nothing built. Every script, line, number and hour below is invented, unverified and PENDING founder approval (hear-before-change). Base for lane 2: docs/ROBIN_RESCUE_DESK_PILOT.md (kept as the pilot plan; this file extends it). Related: ROBIN_EMERGENCY_FLOW.md, ROBIN_LINES.md, CARE_PROTOCOL.md, ROBIN_FALL_DETECTION_*.md.

## 1. One team, two lanes
One human operations team, one console, one roster, one audit log. Two lanes with different rules:

| | Lane 1: Concierge (errands) | Lane 2: Emergency/rescue desk |
|---|---|---|
| Work | manual errands asked by voice/WhatsApp: bills, groceries, bookings, calls to a shop or hotel, document help | HIGH/EMERGENCY alerts: scam in progress, SOS, fall unanswered, parent unreachable |
| Clock | asynchronous, service levels in hours | synchronous: AI acts within 1 minute, human joins within 3 minutes |
| Hours | set and stated (draft 8 am to 8 pm) | pilot: stated desk hours plus an on-call window; outside them Robin works alone and says so |
| Money | staff NEVER pay; the user pays by UPI link they tap | never moves money; only guides the family (bank, 1930) |
| Skill | errands, patience, Hinglish | calm voice, scripts, escalation judgement, distress training |
| Who may do it | any trained concierge | only staff who passed emergency training and a dry run; concierge-only staff cannot take lane 2 |

People can be cross-trained; a person on the lane 2 roster is never also the sole concierge cover during that shift.

## 2. Lane 2 in detail: AI first, humans join
**Timeline (draft):** t=0 signal; t<=60 s Robin (AI) rings the parent, rings the child, pages the desk; t<=3 min desk ack, else the family ladder continues and the log says "desk did not answer"; the human is on the line as soon as acked.

**AI -> human handoff.** Robin hands over a one-screen card: parent, language, tier, why-line, signals with times, what Robin already said/did, who was rung and the result, consent items (including "desk may call 112 or my bank"), child and second contact numbers. Robin tells the parent plainly: "A person from Robin is joining." Robin never pretends to be human; the human says who they are. The human can hand back to Robin (stand down) or keep the line.

**Duty roster.** Primary and secondary per shift; the secondary is paged if the primary does not ack in 3 minutes. Weekly rota published to staff; swaps logged. Never write "24/7", "guaranteed" or "we will call the police for you" until staffing and legal review exist.

**Who may phone whom** (by a person; never an automated call to authorities):
| Contact | Allowed | Condition |
|---|---|---|
| Parent | yes | Robin's number/line; scripts in the parent's language |
| Child (admin) | yes | always, on HIGH/EMERGENCY |
| Second contact named at setup | yes | named in advance by the child |
| Neighbour/other | only the second contact the family named | no cold calls |
| 112 / ambulance | yes, human only | consent item recorded at setup; say who you are, the address, the minimum facts; log what was shared. Without the consent item: tell the child and parent to dial 112 themselves |
| Bank / 1930 cyber helpline | yes, human only, guiding or with the child on the line | consent item recorded; never ask for OTP/PIN |
| Police station / sending someone to the home | no, only on the child's instruction | the desk does not dispatch anyone alone |

**Stays AI-gated and dry-run until legal review** (matches the authority dry-run rule): any call to 112/police/bank on the parent's behalf (before review the desk script tells the child and parent to call 112 themselves, and the console records what would have been done); call recording (audible disclosure and stated retention first); auto-promotion to EMERGENCY after unanswered time; anything acting for the parent with a third party. Live without a legal gate: ringing parent/child/second contact, staying on the line, the first-hour playbook as advice, the incident log.

**Scripts.** The six procedures in ROBIN_RESCUE_DESK_PILOT.md section 4 (scam in progress, money already sent, medical, unreachable, distress, closure) are the call scripts, each as a Hindi/Hinglish/English card in the console. Distress words always switch to the care protocol (14416, 112, no diagnosis) and a human voice if the person agrees.

**False alarms.** The human asks "are you OK?" first; if fine, marks `false_alarm` with a reason code (accidental press, test, misheard word, sensor). The child gets a short kind note; the parent is not scolded. The source is counted per family per week and feeds threshold tuning. Repeated false alarms lower sensitivity only by the child's choice. A false alarm never justifies skipping the next alert.

**Review of every incident.** Every lane 2 incident (real or false) is closed with a log (what happened, signals, actions, times, who was called, result) and reviewed by a second person within 24 hours (the founder in the pilot); a weekly review covers response times, misses and script quality. The child gets a plain summary. Logs are encrypted, retention set by the family, erased on request; no distress content in training data or analytics.

## 3. Lane 1 in detail: concierge
Request queue (from voice, WhatsApp or the support line) -> Robin triage (classify, check consent/limits) -> assigned to a concierge -> done with proof (photo, receipt, call note) -> user confirms. Rules: never pay (user pays by UPI link); never ask for passwords, OTP or PIN; no medical or legal advice; every action audited (who, what, when); replies are voice-first. Draft service levels: acknowledge within 15 minutes in hours, finish within 4 hours or say why. Tool design is ticket T23.

## 4. Staffing ratios (arithmetic on invented inputs; tune with pilot data)
One full-time person is about 40 desk hours a week; one seat around the clock is 168 / 40 = 4.2, so 5-6 people with leave (from the pilot plan).

**Lane 1 (concierge), by registrations:** if each family makes 0.4 requests a week at 20 minutes, 150 families need 150 x 0.4 x 20 / 60 = 20 work hours a week, about half a person; with queue headroom and leave, open at 1 concierge per 100 families and never fewer than 2 people once hours exceed 40 a week (leave cover).

**Lane 2 (emergency), by coverage hours, not registrations:** 1 seat in desk hours up to about 100 active families; 2 seats (primary + secondary) at 100-300; one extra person per 150 families beyond that. Load check: if 5% of families raise a HIGH/EMERGENCY alert a week at 30 minutes each, 100 families give 5 alerts, about 2.5 hours a week, so coverage hours drive cost, not volume. Pilot (4-20 families): founder plus one trained backup on call. Around-the-clock lane 2 needs 5-6 people and is a business decision, not a pilot default. Cross-trained concierge staff can fill the lane 2 secondary seat, so total headcount is below the sum.

Review at 20, 100 and 300 families with real numbers: alerts per family per week, minutes per incident, requests per family, median time to a human voice.

## 5. Help-and-support line (WhatsApp + phone) routing
One published pair: a WhatsApp number and a phone line (also the grievance contact). Robin (AI) answers first and routes:

| What is said or done | Route |
|---|---|
| Danger, SOS words, fall, "being threatened", parent unreachable | lane 2 at once (page desk, ring child); never queued behind anything |
| Suspicious call/message in progress, money just sent | lane 2 (scam procedure) |
| An errand ("pay the electricity bill", "book a cab", "call the hotel") | lane 1 request queue |
| How do I / app problem / pairing / consent / billing | Robin answers; unresolved goes to a support person (concierge team, in hours) |
| Complaint or grievance | logged with a reference number, to the grievance officer (founder to name), acknowledged within a stated time |
| Phone line outside hours | Robin answers; emergencies still page lane 2 on-call; says what is and is not staffed |

A paired parent or child is recognised by number; an unknown caller gets a generic safe path (no account data read out). The support number is never given as an emergency number: scripts for life danger say "call 112".

## 6. Founder decisions needed
1. Lane 2 pilot hours and on-call window; primary and backup people.
2. Whether the 1:100 and seat figures are the opening plan.
3. Grievance officer and acknowledgement time; support phone provider (real number vs WhatsApp first).
4. Start of legal review (consent on behalf, acting for a parent with authorities, call recording, DPDP, liability wording); until then authority calls stay dry-run.
5. Hiring and training: emergency training, dry-run certification, wellbeing support for desk staff.
6. Pricing: concierge per request vs bundled; lane 2 cost carried in the family plan.

## 7. Unverified
All ratios, times, hours and rates are invented working numbers. No staffing, legal or telephony vendor checked. Desk console, request queue, roster and paging are not built (see ROBIN_RESCUE_DESK_PILOT.md section 6 and T23).
