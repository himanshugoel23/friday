# Friday memory: one page (design 2026-10-26; steps 1-5 BUILT the same day, see section 8)

**Why it matters.** A memory that gets better the longer someone uses Friday is the one thing a copycat cannot ship on day one. It also makes everything else better: the Speech Understander fixes a misheard "Shriya" because Shreya Salon is in memory; calls know which salon, which card, which address.

## 1. What exists today (reuse, do not rebuild)
Profile (name, city, language); facts (free text the user told us); people (circle, nicknames, "mummy"); places (home, office, saved); vendor history (who quoted what, ratings); account identifiers; life state (appointments, bills, commitments); wallet (card NAMES only); open tasks; last ~20 turns. All per user, encrypted fields, with "what do you remember / forget X / export / delete everything" controls. The `ConversationContext` hands this to the brain; `friday/speech/memory.py` reads a names-only slice for the Speech Understander.

## 2. What is missing
1. **Learning from correction.** "Nahi, Shriya nahi, Shreya" changes the transcript for that message but is not written back as an alias, so the same mishearing returns.
2. **Memory of what happened.** Facts are statements; there is no short "episode" record ("asked for a haircut quote on 23 Oct, chose the cheaper salon, liked it") that lets Friday say "last time you went to X".
3. **Preferences that emerge** (usual order, budget range, language mix, tone) are not collected; the adaptive persona needs them.
4. **Relevance.** The brain gets recent items, not the most relevant ones. Fine at 50 facts, wrong at 500.
5. **Staleness and conflict.** A moved house, a changed number, a sold car: no expiry, no "is this still true?".

## 3. Design (small, in this order)
| Layer | What it holds | How it is written | Read by |
|---|---|---|---|
| Profile and circle (exists) | name, city, language, people, places, cards by name | user says it, or confirms a proposed alias | everything |
| **Aliases (new)** | spoken or misheard form -> canonical name, with count and last seen | proposed by a correction or a repeated clean-up; becomes active after 2 uses or one confirm tap; undoable | Speech Understander, reference resolver |
| **Episodes (new)** | one line per finished task: what, with whom, outcome, rating, date | written by the engine when a task closes (outcome only, no transcripts) | chat ("last time..."), call briefs, proactive follow-ups |
| **Preferences (new)** | usual budget, usual slot, tone dials, favourite vendors | derived from episodes and style signals; each with a source and a count | persona, vendor ranking |
| Facts (exists) | things the user stated | user says it | brain |

Rules for every item: has a source (said / done / inferred), a date, a confidence, and an expiry or review date; inferred items are shown as "I think..." and never used for money, address or calls without confirmation; the user can see all of it in one list ("what do you remember"), correct or forget any item, and one command deletes everything (aliases and episodes included). Nothing is shared across users. Secrets (OTP, PIN, card digits, passwords) are never memory; saved website logins stay in the credential vault (docs/CREDENTIAL_VAULT.md), not here.

## 4. How it is read (relevance)
Pilot: keep today's recent-items context plus the names slice. Next: rank candidate items per message by recency x frequency x match to the words (names first), keep the top 10-15, and write the "why" of each retrieved item to the trace. Vector search only when the rules-based ranking misses in real transcripts; use the database's own vector support, no new vendor.

## 5. Privacy and law (DPDP)
Purpose-limited (only to help the user), consented at onboarding, minimal context in prompts (names, not the whole profile), 30-day retention for transcripts, user-visible and deletable, encrypted at rest with the field key (KMS for live). Inferred preferences are the sensitive part: show them, let the user turn them off.

## 6. Build order (about 5 working days, estimate)
1. Alias table + write-back from corrections + undo (1.5 days). 2. Episode record on task close + "last time" in chat and call briefs (1.5). 3. Single "what do you remember" list showing source and date, forget per item (1). 4. Relevance ranking with trace (1). 5. Tests: isolation between users, delete-everything covers new tables, no secret ever stored, alias poisoning (a wrong alias cannot redirect a call to another person).

## 7. Open questions for the founder
Should inferred preferences be on by default or opt-in? How long should episodes live (suggest 12 months, then summarised)? Is "last time you used X" welcome in chat, or only when asked?

## 8. Status (built 2026-10-26; all offline-tested, not yet run on real users)
Code: `friday/memory/` (`service.py`, `rank.py`, `attach.py`, `chat.py`, `copy.py`). 1. **Aliases:** `MemoryService.note_misheard` (two sightings or one confirm; must sound like the saved name; cannot take another entry's name; max 6; undo with `forget_alias`); the Speech Understander feeds it from its mis-hearing fixes (`InboundPipeline._learn_aliases`) and uses saved aliases even when the model is off (`speech/understander.py::_apply_aliases`). 2. **Episodes:** one line per finished MAIN task via the event bus (`attach_episodes`, wired in `Runtime.start`), 365-day purge, secrets redacted; stored as facts, no migration. 3. **The list:** "what do you remember about me" shows every item with its source (you told me / done together / my guess) and date; "forget <item>" removes one alias, fact or episode; delete-everything already wipes the facts. 4. **Relevance:** `build_context(query=...)` keeps the 15 best facts (word match x recency x confidence, due dates boosted), alias candidates are never shown to the model, the ranking trace is logged at debug. 5. **Tests:** `tests/memory` (11), `tests/speech/test_aliases.py`, `tests/chatbot/test_memory_chat.py`: isolation between users, cannot forget another user's item, alias poisoning, cap, expiry, secrets, child calls do not create episodes.
NOT done: "last time you used X" lines in chat and call briefs (episodes are stored and reach the brain as facts, but no reply wording uses them yet); preferences (budget, usual slot, tone dials); staleness prompts ("is this still true?"); vector search. The list wording in `friday/memory/copy.py` is PENDING founder approval.
