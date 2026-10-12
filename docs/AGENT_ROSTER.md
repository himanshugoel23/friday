# Agent roster: many small agents, one job each (draft v1)

Principle: each agent has ONE job, a typed input, a typed JSON output, and a validator. Deterministic work (distance, maths, phone checks, dedupe, budget limits) is plain code, not an LLM. An LLM agent is used only where language understanding is needed, with a closed output schema, and its output is checked by code before the next agent sees it. No agent can talk to the user or the vendor except the two that are built for it.

Pipeline for "get me quotes for X":

| # | Agent | Job (only this) | LLM? | Output |
|---|-------|-----------------|------|--------|
| 1 | Intake classifier | WhatsApp text/voice -> bucket + vendor category (closed lists) | yes | {bucket, category, confidence} |
| 2 | Slot extractor | pull when / where / budget / people / service list from the message | yes | typed slots, missing list |
| 3 | Clarifier | write ONE short WhatsApp question for the first missing slot | yes (templates first) | question text |
| 4 | Location resolver | user text/pin/saved place -> lat/lng (Geocoding) | no | GeoPoint |
| 5 | Query builder | category + area -> Places text-search queries (synonyms, Hinglish) | no (table) | queries |
| 6 | Place searcher (Google scout) | run Places search, return raw candidates with phone, rating, count, hours, types | no | candidates |
| 7 | Eligibility filter | drop closed, no phone, wrong type, outside radius, duplicates | no | eligible list + drop reasons |
| 8 | Review fetcher | get up to 5 reviews per candidate (Place Details) | no | reviews (memory only) |
| 9 | Review authenticity judge | per place: do reviews look genuine? (burst dates, copy-paste text, one-line praise, reviewer with 1 review, owner-reply patterns) -> score + reasons | rules first, LLM for text patterns | {genuine_score, flags} |
| 10 | Service-evidence extractor | from reviews: what service they really offer, quality themes, price mentions, complaints | yes | {services_confirmed[], themes+, themes-, price_hints} |
| 11 | Fit scorer | does the place match THIS request (service, budget, gender/unisex, home visit)? | no (rules over agent 10) | fit 0-1 |
| 12 | Ranker | combine rating (Bayesian-smoothed with count), genuineness, fit, distance, openness into a final score; pick top N with reasons | no | ranked shortlist |
| 13 | Shortlist explainer | one-line WhatsApp reason per pick ("4.6, 800 reviews, known for beard trims, 2 km") | yes (checked) | text |
| 14 | Call-task builder | shortlist + request -> one CallTask per vendor (playbook, slots, delegation, number) | no | CallTasks |
| 15 | Safety/consent gate | allow-list, do-not-call, call hours, quota, redirect mode | no | approved / blocked |
| 16 | Voice caller | runs the playbook call (already built) | scripted, LLM only to classify | transcript + outcome |
| 17 | Result extractor | transcript -> price, slot, notes (validated) | yes (checked) | quote record |
| 18 | Comparer | rank quotes by price/quality/time | no | comparison |
| 19 | Reporter | build the WhatsApp reply (templates) | no / checked LLM | message |
| 20 | Follow-up planner | approvals, reminders, retries, SMS fallback | no | scheduled actions |

Hand-off contract: each agent writes its output to the task record in the DB (resumable, auditable); the next agent reads only that. A failed validation stops the pipeline with a clear reason; no agent "fixes" another agent's output.

Anti-hallucination rules:
1. Closed vocabularies and JSON schemas everywhere an LLM is used; reject and retry once, then escalate to "unsure".
2. An LLM never invents a phone number, price or time: those come only from Google fields or the call transcript, and are checked against the source text.
3. Review text is evidence, quoted with the review id; claims without a quote are dropped.
4. Test sets: recorded Google responses and review samples (fake vs genuine) for agents 7-13.

Review / privacy: raw review text is kept in memory only for shortlisting (Google caching terms); only derived scores and short reasons are stored.

Build order: 6, 7, 8, 9, 10, 11, 12 (the scouting package `friday/scouting/`) first; then 1-5, 14-15 wiring into the quotes flow; 16-20 already partly exist.

## Project manager and distance rule (founder, 2026-10-12)

### Agent 1: Classifier (only classifies)
WhatsApp text/voice -> {bucket, category, confidence} from closed lists. Nothing else.

### Agent 2: Project manager (PM)
Owns one request from first message to final reply. It is a small state machine in code; the LLM is used only to word a clarifying question and to read the user's free-text answers into slots (output validated).
1. Receives the classifier output. Low confidence or missing category -> one clarifying question.
2. Looks up the bucket x category plan template (the list of agents/steps, required slots, defaults).
3. Checks required slots (where, when, service, budget, who it is for, delegation yes/no). Missing -> ONE question at a time, max 2 rounds, then proceeds with stated defaults or stops politely.
4. Creates the plan (a task record with steps: locate -> search -> filter -> reviews -> rank -> shortlist -> consent -> calls -> collect -> compare -> report) and dispatches each step to its agent, reading only their typed outputs.
5. Handles failures: no vendors in range -> offer to widen (asks user), vendors do not pick up -> retries/next in the list, over-budget -> tell the user, ambiguous call result -> flag.
6. Never calls vendors and never writes vendor-facing words itself.
Everything it decides is logged on the task record (resumable after restart).

### Distance rule: nearest AND best
- Each category has a default radius and a hard max (table in the scouting category table), e.g. salon/gym/florist 5 km (max 10), clinic/lab/vet 8 km (max 15), restaurant 5 km (max 12), home-service visits (AC, plumber, pest, laundry pickup) 10 km (max 20), movers/events/wedding/cab 20 km (max 40; they travel), coaching/driving schools 8 km (max 15), PG/rental: area-based as the user says.
- Distance is a hard filter, not just a score: nothing beyond the default radius is ranked as "best". If fewer than N good vendors exist inside the default radius, the PM may widen step by step up to the hard max, and the shortlist says plainly how far each one is; beyond the default radius the user is asked first. Beyond the hard max: never shown.
- "Best" is chosen only among vendors inside the allowed radius. The ranker returns the nearest-good and the best-in-range as separate picks when they differ.
- Distance is real travel distance when known (Routes API later), straight-line until then, with a safety factor.

### Brainstorm notes (our view on the framework)
1. Agents 1 and 2 can run as ONE step in practice (the PM calls the classifier as a tool), but we keep them separate in code so the classifier can be tested alone.
2. The PM should be mostly deterministic code (plan templates per bucket x category). An LLM PM that invents plans is the main hallucination risk; templates plus a few LLM calls for language are safer.
3. Start with the 4 call types (quote, availability/booking, service visit, information) and 3-4 live categories; add templates for the rest later, they are mostly configuration.
4. The user can interrupt at any time ("cancel", "change time"); the PM re-plans from the task record.

## Added 2026-10-12 (founder): conversation-based proactiveness
| 21 | Memory extractor | After each conversation/call: extract follow-ups, dates, concerns, preferences the USER said, each with the exact quote + message/call id (code verifies the quote exists); nothing inferred from outside Friday | yes (checked) | {followups[], dates[], concerns[], prefs[]} |
| 22 | Proactive planner | Turn stored follow-ups into scheduled actions (what, when, channel WhatsApp or call), obeying: opt-in, quiet hours, max 2/week, transactional wording only, dedupe, cancel when the user already did it | no (rules) | scheduled actions |
Users can see ("what do you remember?"), delete one/all, or switch proactive off. Agent 20 (follow-up planner) is merged into 22.
