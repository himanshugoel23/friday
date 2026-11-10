# Robin concierge desk and support line: design (engineering manager, 2026-11-10)

Status: DESIGN ONLY. Nothing built, no line or script approved (hear-before-change applies to every spoken or sent line; all wording PENDING).
Public repo: no personal data, no keys. Marks: [U] = unverified (number, law, vendor behaviour), [F] = needs founder input.

Founder decisions (2026-11-10, end of docs/HANDOFF.md): (a) a human CONCIERGE does manual errands, hired in proportion to registrations;
(b) one help-and-support WhatsApp number PLUS a phone line, which is also the grievance contact; (c) Robin and the concierge NEVER pay, the user pays
by UPI link/QR; (d) the emergency desk stays AI-only (docs/ROBIN_RESCUE_DESK_PILOT.md is the pilot plan for the emergency path; it is not this desk);
(e) the parent is voice-first (no typing), the child is the admin and owns consent; security paths ignore time of day.

What exists today (read from code): friday/tasks has a task state machine (CREATED, PLANNING, NEEDS_INFO, AWAITING_APPROVAL, CALLING, AWAITING_USER,
COMPLETED, FAILED, CANCELLED ...) built for AI-run errands, with TaskType values such as BOOKING, HEALTHCARE, ORDER, SERVICE_COORDINATION and
STATUS_CHASE; the concierge request is a different object (a human works it), but it can REUSE the task events/outbox and TaskType vocabulary and
may spawn an AI sub-task (for example "call the clinic"). docs/CONCIERGE_REFERENCE.md is trip-concierge market research (Swiggy CREW etc.), not a
design for this desk. docs/ROBIN_PHASE1_BACKLOG.md has T22 (floating mic) and T23 (concierge, "design first": this document).

## 1. What the concierge can and cannot do

Principle: the concierge does the errand; the family keeps the money, the credentials and the medical decisions.

| Request type (elderly care) | What staff do | Cannot do / limits |
|---|---|---|
| Book doctor appointment | Find the clinic/doctor the family names, phone or portal-book a slot, confirm to parent (voice) and child (chat) | Choose a doctor on medical grounds; promise a doctor "from Robin" |
| Book lab test / home sample collection | Book with a named lab, share prep instructions the lab gave (fasting etc.), follow up on report delivery | Read or interpret results; forward reports outside the family thread |
| Medicine order follow-up | Check a pharmacy order the family placed, chase delivery, re-order an EXISTING prescription item on the child's yes, flag stock low | Choose, substitute or change a medicine or dose; order without a valid prescription on file; any dosage advice |
| Groceries / daily needs | Build the basket from the family's usual list, send the UPI link to the payer, track delivery | Pay; store a card; substitute silently |
| Bill reminders | Remind about due dates the child entered or the bill shows; walk the child through paying; send the UPI link | Pay; log in to a utility or bank account; hold standing instructions to pay |
| Cab | Book a cab for a named trip (parent boards, fare paid by the user via the cab app/UPI) | Hold the user's wallet; share driver details outside the family |
| Repair person (plumber, electrician, AC, appliance) | Find 2-3 vetted vendors, get a visit window and a quoted range, confirm the slot, follow up after the visit | Vouch for a vendor as safe; negotiate on a hidden commission; send an unknown person to an empty home without the child's yes |
| Forms and paperwork | Fill a form with details the family supplied, book the visit, remind what to carry (pension life certificate, Aadhaar update appointment, insurance claim intake) | Take or use Aadhaar/PAN numbers beyond the form; sign for anyone; submit anything needing OTP or biometric (the family does that step) |
| Chase and follow-up | Call a vendor, bank branch, hospital desk on the family's behalf to ask status | Argue a claim for the family; commit the family to money |

Hard no's (these are rules in the console, not just training): (1) never pay or hold money; payment is a UPI link/QR sent to the user, and the
desk marks "paid" only when the user or the vendor confirms; (2) never ask for, receive or relay OTPs, PINs, passwords, card numbers, UPI PINs;
(3) never open or ask for bank/UPI app access, screen share or remote-access tools; (4) never give medical advice, triage or diagnosis (say "please
ask your doctor" and offer to book the visit); (5) never act on a stranger's instruction, only from the parent or the child admin; (6) never enter
the home or send a person there unless the child has approved; (7) distress words or danger: stop the errand, hand to the emergency path
(Robin AI desk plus the child, docs/CARE_PROTOCOL.md), do not improvise.

Who may ask: the parent (voice/WhatsApp voice note) or the child admin (chat). The child sees every request and can cancel, set a spend ceiling, or
turn the concierge off for the parent. A request that involves money above the family's ceiling [F: default Rs 2,000 [U]] or any health item
needs the child's yes before staff act.

## 2. Request lifecycle, SLAs, priority

Flow: ask -> AI triage -> queue -> staff picks -> work -> proof -> done message -> feedback.
1. INTAKE. Parent speaks (widget mic, WhatsApp voice note, later the support line) or the child types. STT in the parent's language; Robin
   confirms back in one sentence ("Kal subah ka sugar test book karna hai, theek hai?"). Nothing is queued before the parent or child confirms.
2. AI TRIAGE (rules first, LLM may only RAISE priority): classify type (table above), extract slots (who, what, when, where, vendor), detect
   safety/health words, scam signs and out-of-scope asks (payment, OTP, medical advice) and answer those itself with the refusal text. Missing
   slots -> Robin asks the parent by voice (one question at a time) before the ticket reaches staff, so staff get a complete request.
3. QUEUE. Priority P0 safety > P1 health > P2 convenience; inside a class, oldest first, then by due time.
4. PICK. A staff member claims one request (lock with timeout so two people never work it). Claim is audited.
5. WORK. Staff use the one-screen view and contact vendors through Robin lines (section 3). Status moves: NEW, TRIAGED, QUEUED, CLAIMED,
   WAITING_FAMILY, WAITING_VENDOR, PROOF_PENDING, DONE, CANCELLED, FAILED, ESCALATED.
6. PROOF. Done requires proof stored on the request: booking confirmation text/screenshot, order id, vendor's slot message, call note with the
   vendor's name and time. No proof, no DONE (system refuses).
7. DONE MESSAGE. Parent: a short voice note in her language ("Doctor Sharma, Thursday 10 baje, beta ne bhi dekh liya"). Child: text with proof and
   a "Was this right?" button. A "Not right" feeds quality sampling (section 3).
8. PAYMENT STEP (when money is involved). Staff send the child (or the payer the child named) a UPI link/QR for the vendor or order; vendor is
   paid directly; the desk never touches the money and never sees the UPI PIN.

SLAs (targets to publish only after two pilot months of data) [F]:
| Class | Example | First human touch | Resolve |
|---|---|---|---|
| P0 safety | parent says fell, scam in progress, "send someone" | NOT the concierge: Robin AI emergency path starts at once, any hour; the ticket is opened and the concierge only follows up afterwards | n/a |
| P1 health | lab test tomorrow, medicine ran out today | within 30 min in desk hours | same day |
| P2 convenience | groceries, bill reminder, repair quote | within 2 hours in desk hours | 24 to 48 hours (repair visit dates are the vendor's) |
Outside desk hours: Robin tells the parent/child the real time ("Subah 8 baje se dekhenge"), queues it, and anything health-urgent is told to
call the doctor or 112; it never promises a human at night. A request breaching its SLA turns red, pings the shift lead, and the child gets a
"still working on it" message (never silence). Security paths (scam, SOS, unreachable parent) never wait for desk hours.

## 3. Staff tooling (web console)

- Queue: filter by priority, status, language, age; SLA timers; "mine / unclaimed / waiting"; no search by phone number, only by request id or
  first name.
- One-screen request view showing ONLY: request text and confirmed slots, parent first name, language, city/area and PIN code if needed for the
  vendor, relevant instructions (for example "diabetic, fasting test"), the thread with the family, vendor notes, proof, spend ceiling and state.
  Hidden by default: full address (revealed per request when a vendor visit needs it, logged), phone numbers, Aadhaar/PAN/policy numbers
  (the family fills those in the form directly or staff see the last 4 characters), medicine list beyond the item in this request, other
  requests of the family, medical history, health alerts, location history, call transcripts.
- Masked numbers and click-to-contact: staff never see raw phone numbers of the parent, child or second contact. "Call parent / message child /
  call vendor" are buttons that place the call through Robin's own lines (Vobiz [U]): bridge A (staff headset) to B (the person) with the
  Robin number as caller id on both legs. Vendor numbers the staff member finds (clinic, plumber) are typed into the console once and are
  then also stored masked per family vendor book. Recording of bridged calls: off by default; if ever on, audible disclosure and short retention
  [U legal]. Vobiz must be confirmed to support bridged outbound with caller id of the Robin number [U].
- Audit log (append-only, tamper-evident hash chain): who opened which request, every field revealed, every call/message placed (time,
  duration, outcome, not content), status changes, exports attempted, logins, failed logins. Retained [U legal, suggest 1 year]; the
  family can ask for their own slice.
- Shift handover: a handover note per open request ("waiting for lab call-back at 4"), a shift summary page (open, breaching, waiting on family),
  both staff acknowledge; nothing is handed over by chat or personal WhatsApp.
- Escalation: button "escalate to shift lead" and "escalate to founder" (pings by WhatsApp and call to the founder number, allow-listed numbers
  only); automatic escalation on SLA breach, on distress words, on a suspected scam in the request, on a vendor complaint, or on any request
  the staff member thinks is outside the table in section 1.
- Quality sampling: shift lead reviews 10 percent of DONE requests (all in the first month of a new hire) against a rubric: right vendor, proof
  attached, message kind and in the right language, no data over-reveal, no refused-rule breach; the child's "Not right" button always lands in review;
  monthly calibration with the founder. Staff score is never shown to families.
- Child's view (the family-facing side): requests list, status, proof, spend ceiling, pause concierge, "who touched my parent's data".

## 4. Staffing model

All numbers are planning arithmetic, not quotes; replace with pilot data [U].
- Workload assumption [U]: an elderly-care family sends about 3 to 6 requests a month at launch, rising with trust; handling time 15 to 30
  minutes per request including follow-up. So about 1 to 3 staff-hours per family per month. One full-time person gives about 120 productive
  hours a month, so roughly 40 to 100 families per concierge at steady state. Start conservative at 1 concierge per 40 families.
- Hiring triggers: (1) hire the next person when registered families / staff passes 40 (or 50 percent of that when requests per family are above 5
  a month); (2) or when median first-touch time in desk hours is above 60 minutes on 5 of 7 days; (3) or when the SLA-breach rate is above
  10 percent for a week. Always keep a trained second person for leave (backup) before family 20.
- Pilot: founder plus one part-time concierge for the first 4 to 20 families (matches ROBIN_RESCUE_DESK_PILOT.md). 100 families: 2-3 concierges and
  a part-time shift lead; 500 families: 8-12 plus a lead and a quality person [U].
- Cost per family: staff cost per month divided by families. With a fully loaded cost of about Rs 25,000 to 35,000 a month per concierge in a
  metro [U] at 40 to 100 families, that is about Rs 250 to 900 per family per month, plus telephony and vendor-tool cost. The Phase 1 price
  hypothesis in docs/PARENT_CARE_PHASE1_SPEC.md is Rs 299 to 599 a month [U], so the concierge is either a paid add-on tier, a limited number of
  requests a month in the base plan, or priced per request. [F] This is the biggest commercial decision here.
- Hours: start with extended hours, 8 am to 8 pm, 7 days (a single seat is 84 hours a week, about 2.5 to 3 people with leave). Later: add
  a night on-call for P1 health only before 24x7. True 24x7 for one seat needs about 5 to 6 people (same arithmetic as the rescue desk plan) and
  should not be promised or advertised until staffed.
- Language: Hindi/Hinglish first; English; add regional languages by the pilot cities [F].
- Training script (3 days, then 2 weeks of shadowed work; a written test must be passed before access): day 1 who our families are, how to
  speak to an older person (slow, respectful, one question at a time, no jargon), the hard no's and why; day 2 the console, masked calling,
  proof rules, handover, and an exercise with fake families only; day 3 scams and pressure (a caller posing as the child, a vendor asking for an
  advance, a parent asking "just pay it for me"), distress words and the emergency handoff, privacy and DPDP basics. Script cards in the console
  for refusals ("Main paise nahi bhej sakta, aapko UPI link bhejta hoon") and for the emergency handoff. Refusal and spoken lines need founder approval.

## 5. Help and support line

Two entry points, one ticket system (decision b). Grievance contact is the same pair, plus the named officer.
- WhatsApp business number (support, separate from the family-facing Robin number and from the parent's thread): text and voice notes; the bot
  answers FAQs, takes the problem, makes a ticket, tells the user the ticket id and the expected reply time. WhatsApp number must not be the
  founder's personal Facebook-linked one (see docs/META_UNBLOCK_PLAN.md; blocked until the Meta token/WABA works).
- Phone line (Vobiz [U]): an inbound number with an IVR in Hindi/English (menu in the founder's approved voice): 1 "My parent needs help right now"
  -> says call 112 and rings the family ladder through Robin; this branch is AI-only and works at any hour; 2 an existing request or the
  concierge; 3 billing or my account; 4 privacy, grievance or erase my data; 5 speak to someone. Pressing 0 or saying nothing for 8 seconds goes to 5.
- Hours: extended hours matching the desk (start 9 am to 8 pm, 7 days, publish the real hours); outside hours the line plays the hours and takes
  a voicemail and a "call me back" request. Missed-call callback: every missed or abandoned call creates a ticket and the staff returns the call
  from the Robin line within the next desk hour (first business hour at the latest next morning); the caller gets a WhatsApp "we will call you at
  ..." only if the caller number is a known family number.
- Ticketing: id, channel, category (request, billing, privacy, bug, grievance, feedback), priority, owner, SLA timers, status, linked family and
  request (by internal id), canned replies, satisfaction tap. Start with the same Postgres tables and the staff console; do not buy a SaaS
  helpdesk until volume justifies it (a SaaS would receive family data: DPDP processor terms needed [U legal]).
- Grievance officer for privacy law (DPDP Act 2023) [U legal]: name, address and contact of the officer/Data Protection contact must be published on
  the site and in the app, with a reply promise (the Act and Rules lead to a published timeline; the exact days are [U], ask counsel; suggest
  acknowledgement within 48 hours, resolution within 15 days as a working target [U]). The phone line option 4 and a dedicated e-mail go to
  this officer; the officer role is a named person, not the shared inbox. Rights to serve: access, correction, erasure, withdraw consent,
  nominate someone (nominee provisions apply for a person who cannot act [U]). The existing "erase" path in the family core is the technical
  route; the child admin can exercise rights for the parent, the parent can too by voice.
- What the line may reveal: after identity check, only to the child admin (or the parent) of that family, and only what that person can already
  see in the app. Identity check: call-back on the registered number or a code sent to the registered WhatsApp, never "tell me your OTP/PIN".
  The line never reveals: another family member's data without the admin's consent, a parent's health alerts to anyone but the admin, whether a
  person is registered (to an unknown caller it says "I cannot share that"), vendor or staff names, call contents. Unknown callers get general
  help and a request to message from the registered number. No caller is ever asked for OTP, card number or password.

## 6. Privacy and security

- Role-based access (deny by default): PARENT/CHILD (family app), CONCIERGE (only requests assigned to them, minimum view), SHIFT_LEAD (queue,
  sampling, reassign, unmask a number with a reason), SUPPORT (tickets, no request details), GRIEVANCE_OFFICER (their tickets and the data-rights
  tools), ADMIN/FOUNDER (staff accounts, audit, config). Nobody has database access in daily work; emergency access is logged and reviewed.
- Auth: staff web console behind SSO or e-mail + TOTP, device-bound sessions, allow-listed IP/VPN for the office/home network [F], idle timeout
  10 minutes, absolute timeout 8 hours, one active session per person, instant disable on exit.
- No screenshots/export: no export, CSV, print or bulk copy in the console; a watermark of the staff id and time over the screen; clipboard
  copy only for vendor-facing slots (name, date); browser-side rules cannot stop a phone camera, so the policy, NDA and audit cover that [U].
  Staff work on managed or approved devices only; personal phones with no family data on them; no staff WhatsApp for family business.
- People: police-verification/background check [U legal, depends on state and on what the law allows], identity proof, NDA and a code of conduct
  with the hard no's, a clear consequence (dismissal plus reporting), reference checks, probation of 3 months, access removed on the last day.
- Data staff may NEVER see: bank, UPI, card details and any OTP/PIN/password; the parent's phone activity signals, health alerts, location,
  fall events and call-pattern results (the safety package); SMS or WhatsApp content; recordings and transcripts of the parent's calls;
  Aadhaar/PAN in full; medical reports unless the lab-report errand needs a file name; other families' data.
- Data handling: encrypted at rest (existing AES-GCM pattern in friday/robin/dbmodel.py), request data retention set by family, erasable; the
  concierge ticket store is separate from the safety signal store; logs carry ids not content; no request text or proof used for model training.
- Consent: the child consents at setup for the concierge and for each data class it needs (new consent item "concierge"); the parent is told
  in her language and can stop; consent text needs counsel [U legal].

## 7. Technical build plan (tickets)

Order: C1 data model first; C2-C4 can follow in parallel by different agents in separate worktrees; each ticket tested with fakes only,
switches default OFF (new `FRIDAY_ROBIN_CONCIERGE_ENABLED`), no real call or send. Sizes: S under 1 day, M 1-3 days, L 3-6 days.
| Id | Ticket | Size | Depends on | Founder input |
|---|---|---|---|---|
| C1 | Request model + queue: tables (request, event, proof, vendor book), state machine, priority, SLA timers, claim lock, link to AI sub-task (friday/tasks); migration | L | none | [F] ceilings, SLA numbers |
| C2 | AI triage: type/slots/priority, refusals (pay, OTP, medical advice), voice confirm-back, rules first | M | C1 | refusal wording approved by hearing |
| C3 | Staff web console behind auth: queue, one-screen view with field masking, claim, proof upload, handover, escalation buttons | L | C1, C5 | [F] IP allow-list, who gets accounts |
| C4 | Family side: child "requests" view/chat commands (ask, status, cancel, ceiling), parent voice intake and done message via ParentChannel | M | C1, T07 | wording |
| C5 | Audit log: append-only hash chain, field-reveal events, family export of own slice | M | C1 | retention [U legal] |
| C6 | Roles, session timeouts, TOTP, watermark, no-export, disable-on-exit | M | C3 | staff-device policy |
| C7 | Masked click-to-contact: bridge staff <-> person through Robin number, per-family vendor book, call log without content | L | C3, Vobiz capability check | Vobiz confirmation in writing [U], number |
| C8 | UPI payment-link step: link/QR generated for the user to pay the vendor; status "paid" by confirmation; no money held | M | C1 | UPI provider choice/legal [U]; no pay-by-Robin |
| C9 | Support ticketing: tables, console view, canned replies, SLA, satisfaction tap | M | C1, C3 | categories |
| C10 | WhatsApp support number routing: separate WABA number, bot FAQ, ticket creation, handoff to staff, templates | M | C9, Meta token | Meta/WABA unblock, template approval |
| C11 | Phone-line IVR via Vobiz [U]: menu, hours, voicemail, missed-call callback ticket, "parent needs help now" branch to emergency ladder | L | C9, Vobiz number | menu wording and voice approved by hearing, hours |
| C12 | Grievance flow: officer role, data-rights tickets, erase/access wiring to existing family erase, public page text | M | C9 | officer name, legal text [U legal] |
| C13 | Metrics and ops: counts in opsstatus/doctor, daily report (volume by type, first-touch, resolve time, SLA breach, reopen, cost per request, per-family load), staffing-trigger alert | M | C1, C9 | targets |
| C14 | Training sandbox: fake families and a replay set for the training script and quality sampling | S | C3 | training script review |
Critical path to a staffed pilot: C1, C5, C3, C6, C7 (about 4 weeks for one agent at a time [U]); support line C9-C11 can start after C1.

## 8. Risks and what we must NOT claim

Never claim: "24/7" or "round the clock" (until staffed), "doctor", "nurse", "medical advice", "emergency service" or "we call the police/ambulance
for you" (the AI desk helps the family; 112 is the number), "guaranteed", "we pay for you", "safe vendors/verified" (say "vendors we have used"),
"your data never leaves", "bank-grade" security, "Robin is always listening". Say instead: "Robin helps your family get things done; a real person
from our team handles errands 8 am to 8 pm; paying is always done by you."
Risks: (1) insider misuse of family data (mitigation: sections 3 and 6); (2) a staff member commits money or shares an OTP (rules, no payment
tools, audit); (3) vendor harm or fraud at the home (child approval, vendor book, no unattended visit); (4) health harm from a wrong errand (medicine
only from an existing prescription, no substitutions); (5) cost per family above price (staff triggers, per-request limits, add-on tier); (6) SLA
promises beyond staffing (publish only measured SLAs); (7) staff burnout from distress calls (handoff rule, support); (8) DPDP consent for acting
for an adult parent and for processors [U legal]; (9) the voice-first parent can mis-speak a request, so confirm back every time; (10) Meta/Vobiz
dependencies (bridge, caller id, WABA) are unverified [U]; (11) the concierge reverses "no human at the start": make it visible to families
that humans can see the request (not their safety data); (12) a concierge worker tricked by a scammer posing as the child (admin-only
authority, call-back on registered number for any change in payer, address or spend).

## 9. Questions for the founder

1. Pricing: concierge included in the base plan with a monthly request cap, a paid add-on tier, or pay per request? What cap/ceiling per month?
2. Staffing start: founder + one part-time concierge in the pilot, or hire two people before the first family? Which city and languages first?
3. Desk hours to publish: 8 am to 8 pm, 7 days? Night on-call for health only later, yes or no?
4. Spend ceiling that needs the child's yes (suggested Rs 2,000) and whether health items always need it.
5. UPI link: whose handle collects it (vendor's own UPI, or a payment partner)? Any case where Robin should take a commission or deposit (suggest no).
6. Are lab and pharmacy tie-ups allowed (commission, preferred vendors) or are we vendor-neutral? (Suggest neutral and no commission at start.)
7. Who is the grievance officer (name, address, e-mail, phone) and which Vobiz/WhatsApp numbers are bought for support?
8. Do we record staff bridged calls (suggest no) and how long do we keep request data?
9. Staff devices and place of work: office only, or home with VPN? Background-check provider and budget; counsel for DPDP and employment terms.
10. Approve the hard no's in section 1 as final, and approve or change the IVR menu (voice and wording by hearing before build).
11. Does the child get the parent's concierge requests by default, or can the parent keep a private errand (suggest child sees all; tell the parent so)?
12. Order of release: pilot with the founder as the only concierge for 4 to 20 families first (recommended), then hire by the triggers in section 4?
