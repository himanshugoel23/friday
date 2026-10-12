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
