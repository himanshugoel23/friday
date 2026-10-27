# Chatbot guardrails: what Friday does when a user can say anything (22 Oct 2026, proposal for the founder)

Principle: Friday is a personal assistant that acts for the user, not a generic chatbot. Policy is decided by CODE (rules plus a small trained classifier), never improvised by a language model. Every guardrail reply is fixed wording (pending the founder's approval, like all copy), in the user's language and script.

## Layers (a message passes top to bottom)
1. **Abuse and volume gate:** per-user message and cost caps, spam and repeated-message detection, bans after strikes, an off switch.
2. **Policy classifier (before the router):** one of: in-scope, small-talk, out-of-scope, restricted-advice, safety-critical, harmful, privacy-violation, injection-attempt, prohibited-action. Output is a decision: allow, redirect, refuse, escalate.
3. **Router and skills** (only for allow). Skills only touch the user's own data; actions need approval buttons and the code gates (limits, do-not-call, windows).
4. **Output filter:** every reply is checked: no number that did not come from a tool or the user, no private fact about someone else, no promise of money or time, no instruction-like text copied from untrusted content, no secrets or system text, no medical, legal or investment advice, no claim to be human.
5. **Logging and review:** every refusal or redirect is logged (masked) with its category into a review queue the founder samples daily in the pilot; mistakes become labelled examples.

## Policy by category
| Category | Example | Friday does | Notes |
|---|---|---|---|
| In scope | "mummy ko call karo", "kaun sa card", "kal 2 baje interview" | the skill, with approval for actions | |
| Small talk | "hi", "thanks", "kaise ho" | one warm line, then back to how she can help | no long chit-chat |
| Out of scope | "jeans kaisa hai?", cricket score, recipe, essay help | short polite redirect, offer the closest useful action, save to a wishlist for the founder | e.g. "Jeans ke baare mein main nahi bata paungi; main aapke din, bills, cards aur calls mein madad karti hoon. Chahein toh dukaan ko call karke rate poochh lun?" |
| Restricted advice (medical, legal, investments, insurance, loans, tax) | "kaun si dawai lun", "kya main case karun", "kahan invest karun" | no advice; facts only where they come from the user's own data; suggest a professional | decided earlier: no advice or selling without licences |
| Safety-critical (self-harm, abuse, emergency, medical emergency) | "mujhe jeene ka mann nahi", "mere ghar mein aag" | immediate fixed caring message with verified helpline and emergency numbers (112), offer to notify a trusted contact only if the user set one, never pretend to be a counsellor, flag to the founder's support inbox | helpline numbers must be verified before launch |
| Harmful or illegal (threats, stalking, scams, fake documents, pranks on named people, impersonation, calling emergency numbers) | "isko dara do phone karke" | refuse in one line, no lecture, log; repeated attempts raise strikes | calls to anyone also go through the call gate |
| Privacy violation (someone else's data, tracking a person, other users) | "uska location batao", "dusre user ka number" | refuse; explain Friday only works with the user's own data | |
| Prohibited actions | "mera OTP bhej do", "ye payment kar do", "card number save karo" | explain she never pays or handles OTP, PIN or card numbers, and show the safe alternative (pay link, QR) | |
| Injection or manipulation | "ignore previous instructions", pasted text with commands, forwarded emails with instructions | ignore the instruction content; treat as plain text; never reveal prompts or settings; continue the user's actual request | tested with a fixture set |
| Sexual or abusive language | slurs, explicit requests | one calm boundary line, no engagement; mute for a while after repeats | |
| Politics, religion, opinions | "kaun si party sahi hai" | neutral decline and offer help | |
| Identity questions | "kya tum insaan ho?" | always truthful: "main ek AI assistant hoon" | fixed wording |
| Unknown or unclear | gibberish, one-word messages | one clarifying question, never a guess that acts | |
| Minors (user says they are under 18) | | polite stop for sensitive skills (calls, payments); parent consent policy needed | founder decision |

## Behaviour rules that cut across categories
- Never invent facts or numbers; say "mujhe nahi pata" and offer to find out through a call or a lookup.
- Never act on anything inside forwarded media, emails or web text; it is untrusted.
- Short, calm, no lecturing; the same refusal wording is not repeated twice in a row (rotate approved variants).
- Match the user's language and script (Hinglish, Hindi, Devanagari, English).
- When unsure, ask or escalate; when a refusal could harm (safety-critical), err toward caring and escalation.
## Build plan (after the running builders)
`friday/guardrails/`: category rules in Hinglish, Hindi (Devanagari) and English, a small trained classifier (same dependency-free approach as the intent classifier, with a regression gate), the policy decision object, fixed copy per category (pending approval), the output filter wired before every send, injection fixtures, a red-team set of at least 300 labelled messages (held out 100) and `friday guardrails eval`, a Chat Lab panel showing the category and decision, a review queue and the support/escalation hook, tests for each category and the "refusal never repeats" rule.
## Decisions for the founder
1. How much small talk is allowed (recommended: one warm line, then back to work).
2. Minors: stop sensitive skills, or require parent consent?
3. Safety-critical: which helplines to name (verified numbers needed) and should Friday alert a trusted contact the user chose?
4. Out-of-scope: DECIDED 2026-10-23 by the founder: allow short answers to simple factual questions (time, weather, simple maths, short definitions) from trusted tools or rules, in Friday's playful tone; redirect + wishlist for medical, legal, financial advice, politics, essays and homework.
5. Strike policy for abusive users (mute length, ban rules) and who reviews.
