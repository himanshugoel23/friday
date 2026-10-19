# State of Friday (19 Oct 2026, after the four consumer workstreams)

Legend: BUILT+TESTED (offline, fakes) / WIRED (callable from WhatsApp) / VERIFIED (real world) / PARKED.
Full suite: 4678 passed. Nothing below has been exercised with a real recipient, real Google, or the live database.

## 1. Calls
- Business calls (VERIFIED earlier on a test phone, Ritu voice on Sarvam): 10 pending playbooks (salon, quote and slot, enquiry, home service visit, PG, cab, stock and price, table, hotel, banquet), 22 categories, WhatsApp quotes flow, retries (+1 h, +3 h, max 3).
- Consumer calls to anyone (BUILT+TESTED): family/friends, providers, customer care, officials, unknown people, groups, call-backs. Request understanding, contact book, brief, approval of the exact brief and opening line, safety gate, global do-not-call, caps and calling windows, group fan-out, retries, plain-language report, recording retention. Live engine with fixed "moves", 297 pending lines, intent detection, guards (no invented numbers, no private facts, no commitments outside the brief, truthful AI disclosure, hard stops), voicemail/IVR/hold, 37 simulated callee personas x 3 languages. WIRED: no (integration builder running).
## 2. Savings (BUILT+TESTED)
Card wallet by name, verified rules table (only example rows), calculator, "which card" answers with reason, bills (parse forwarded text, reminders, pay link only), monthly saved-Rs ledger, neutrality test (no revenue input).
## 3. Your day (BUILT+TESTED)
Life state, Hinglish capture of events and commitments, now-status and context summary, calendar import and clash check, follow-ups ("kaisa gaya?"), morning brief, quiet hours/caps/mute, "what do you remember / forget / export / delete everything".
## 4. Google (BUILT+TESTED against a fake Google)
Per-user OAuth with PKCE, encrypted tokens, Calendar read/write/clash, Gmail read-only narrow search (switch off), disconnect and delete.
## 5. Trust and control
Approval before calls and actions, code-level gates, do-not-call, DataPurger covers all new tables, secrets scrubbing, per-user data only, no payments by Friday.
## 6. Learning and tooling
Style tool, learning loop (label, evaluate, few-shot), simulation personas, problem register with the founder's decisions, competitor research.
## 7. PARKED
Ordering through platforms (browser connector with fake site and Zomato explore run stays in the repo, off by default), payments by Friday, devices, social accounts, Gmail broad access, voice-first phone app, call screening/divert.
## 8. Not done / needs the founder
Real card rules, approval of all wording and audio, Google Cloud project, Supabase password and applying migrations 0006-0009, business name and legal pages, WhatsApp number/templates, a server to run on, the list in docs/CONSUMER_DECISIONS.md.
