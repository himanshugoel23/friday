# Open questions: Friday answers what the business asks (design, 2026-10-12)

Founder: when the business asks Friday something, she must not reply with one canned line; she must understand the question and answer properly, using what she knows.

## How it works (friday/playbooks/answerer.py, engine hook)
1. The vendor says something outside the script ("kitne log aayenge?", "sir ka number do", "aap kaun?"). The reply-understanding step labels it `ASKS_OFFTOPIC`.
2. A fact sheet of THIS request is built from the task (who Friday calls for, honorific, what is wanted, when, mode quote-only/book, price/slot already heard). Names are shown to the model as `{user}`,
   `{honorific}`, `{business}` placeholders so it can never garble them; code fills the real spoken names (Devanagari for the voice) afterwards.
3. The fast call-lane model (Sarvam `sarvam-105b-conversations`, ~0.4-0.5 s) writes one or two short Hinglish sentences from the facts, with examples of good replies in the prompt.
4. **Code checks it before it is spoken**: at most ~25 words, no phone number or digits that are not in the facts or the vendor's own words, no booking/confirm/payment/OTP words, no claim to be human,
   Roman letters only (names come from the placeholders), in quote-only mode nothing that sounds like a booking, no unfilled placeholder. Any failure (or a model error) -> the old canned line is used.
5. The script then asks its own question again (the existing `repeat`), so the call keeps its shape: answer first, then back to the price/slot.
Unanswerable from the facts (party size, style, parking, advance, extra services, anything about the user's life) -> "Yeh main <user> <honorific> se poochh kar bataungi." (never a guess).
"Are you an AI?" stays on its own rule (always truthful); stop-calling / rude / wrong number stay on their own rules.

## Switch (OFF until the founder has heard the samples and approved)
`FRIDAY_PLAYBOOKS_OPEN_QUESTIONS=true` in the server `.env` (`bash deploy/setenv.sh FRIDAY_PLAYBOOKS_OPEN_QUESTIONS true`).

## Sample answers sent as audio (Zara voice, phone quality), user = Himanshu, wants = haircut aur beard trim, kal shaam, quote-only
| Business asks | Friday answers |
|---|---|
| kitne log aayenge? | Ji, abhi main sirf charges pooch rahi hoon; kitne log aayenge yeh main हिमांशु sir se poochh kar bataungi. |
| kis naam se booking karni hai? | Ji, abhi main sirf charges pooch rahi hoon; booking ke liye हिमांशु sir khud baat karenge. |
| aap kahan se bol rahi ho? | Ji, main Friday hoon, हिमांशु sir ki virtual assistant, unki taraf se call kiya hai. |
| kya sir ka number mil sakta hai? | Ji, sir ka number main share nahi kar sakti, par aapki baat हिमांशु sir tak zaroor pahuncha dungi. |
| aap sir ki kya lagti hain? | Ji, main हिमांशु sir ki virtual assistant hoon, unhi ke liye call kar rahi hoon. |
| kya aap advance de sakti hain? | Ji, advance ke baare mein main हिमांशु sir se poochh kar bataungi. |
| aapko kya chahiye exactly? | Ji, हिमांशु sir ke liye haircut aur beard trim ke charges poochne the. Exact details main unse poochh kar bataungi. |
| kisne bheja aapko hamare yahan? | Ji, main हिमांशु sir ki virtual assistant hoon, unki taraf se call kiya hai. |
Measured on 12 realistic questions (live Sarvam model + the code checks): 11 answered and passed, 1 rejected by the guard (and would use the canned line). Model time ~0.4-0.55 s from a US machine.

## Known limits / next
- The model sometimes repeats "abhi main sirf charges pooch rahi hoon" where a plain deferral would do; tune the examples from real call transcripts.
- Only `ASKS_OFFTOPIC` uses it. Mid-sentence interruptions and pauses are handled by the call leg, not here (see docs/LATENCY.md and the interruption notes in HANDOFF).
- Founder approval needed per hear-before-change: the SAMPLES are the approval material; any change to the prompt examples means new samples.
