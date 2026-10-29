# Instinct chat 5: capability lessons (2026-10-29)

Source: the founder's own export with Instinct (9-29 Oct 2026). The raw file stays OUTSIDE the repo (it holds personal data and one-time codes). Only general product lessons are kept here: no names, employers, numbers or personal circumstances.

## New capability seen: a general BROWSER AGENT that works on any site
1. **Applying through job portals and company career pages**: logs in (a one-time code that arrives in the user's mail is read by the assistant itself), reads the existing profile, corrects outdated fields after asking, applies to matching roles one by one, sends a screenshot as proof of each, promises a daily run and an evening summary.
2. **Asks the user only for what a form needs**, often in one grouped message: expected pay, notice period, reason for leaving, previous pay, legal yes/no questions, which address to use. It reuses the answers on the next form.
3. **Creates accounts on employer portals** and keeps the password in its vault; at the last step it explains what an e-signature means (background check, data processing, retention) and asks for a plain 'yes' before signing.
4. **Real limits seen**: file upload from its headless browser failed repeatedly on two portals, so it pushed the upload back to the user; a posting deadline was stated wrongly and later corrected; some sign-ins need a phone prompt the user must tap.
5. **Price lookup plus a UPI QR** worked on a second quick-commerce site after the first one failed on location.

## What Friday should copy
- A goal-driven browser agent that works out the steps itself, **asks all the missing questions in one grouped message**, remembers the answers, and shows proof (docs/BROWSER_AGENT_DESIGN.md, being built).
- A daily "what I did for you" summary with proof.
- Reading login codes from the user's mail only when the user connected mail and approved that use.

## Where Friday must be safer (their mistakes)
- **Account creation and e-signature on a single 'ok'**: for legal attestations and consent text, show the exact words and the consequence and get a clear yes for THAT action; never guess legal answers.
- **Passwords**: it created a portal password itself and stored it. Friday: the user sets their own through the vault link, or an existing login is used.
- **Wrong or shifting facts** (a deadline corrected twice, a field it assumed). Friday: say "I am not sure" and show the page evidence.
- **Spam risk**: daily autonomous applications can reach hundreds of employers under the user's name. Friday: preview mode by default; auto-apply only as an explicit opt-in with a daily cap.
- **Upload failures**: design and test the upload path early; when it fails, say so once and give the exact manual step.

## For Friday's guardrails (general, not taken from any one chat)
Friday should have a written, protected protocol for messages that show serious distress or risk of self-harm: short calm replies; ask the direct safe question once; give the free national helpline Tele-MANS 14416 and the emergency number 112; offer to message a trusted person the user names; do not diagnose, argue or promise outcomes; no product or work chatter until the user is steady; check in later the same day; keep this protocol available even when other features are off. Check docs/GUARDRAILS_MODULE.md for what exists and extend it with tests.

## Open questions for the founder
1. Job-search help as a Friday feature? If yes: preview mode default, auto-apply only by explicit opt-in with a daily cap.
2. Reading login codes from the user's mail: only after the user connects mail and says yes to that use.
3. The distress protocol above as a protected guardrail with its own tests.
