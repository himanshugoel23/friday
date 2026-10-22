# Inbound ID: which user or task is this call or message for?

Status: PM proposal. All wording is a draft, pending founder approval.

## Problem

One shared number. A salon calls back and may be serving several of our users. Staff are busy and forget names. Today we match only by caller number (docs/FRONT_DOOR.md), which fails when they call from another phone or have two open tasks.

Rule: **never guess, never say another user's data.** A wrong match is worse than "we will message you".

## Candidates (feel / failure / privacy / cost)

1. **Open tasks for this vendor number.** Invisible. Fails if they call from another phone or have 2+ tasks. Low risk. Free.
2. **One open task per vendor, queue the second.** Invisible. Costs the queued user some delay. Removes most ambiguity. Free.
3. **Reference code** (spoken at end of call, sent on WhatsApp, asked on callback). One small ask. Fails if forgotten. Code holds no data. Free.
4. **Ask "kis kaam ke liye?"**, match to this vendor's tasks only. Feels like a receptionist. Fails on vague answers ("wohi booking"). Safe if we repeat only what they already know. One short LLM call.
5. **WhatsApp buttons and quoted replies carrying the task id.** Zero effort, exact. Fails on a fresh unquoted message and outside the 24 h window. Low risk. Template fees.
6. **Tell them up front** we will call or WhatsApp, so no need to call. Reassuring, no risk, free. Some still call.
7. **Message to ops, never guess.** Slightly slow. No risk. Ops time.
8. New: **"Call me" button** on WhatsApp (Truecaller Business, Uber callback style). The vendor taps, Friday dials, task already known. Needs WhatsApp on their phone. One outbound call.
9. New: **recency hint** (we called this number in the last 2 hours). Free, but a hint only, never decisive.
10. New: keypad code. Clunky, skip. Masked number per user and vendor (Uber, Zomato): needs many numbers, out of scope.
11. New: **stranger path.** Unknown caller gets the identity line and a message-taking flow with zero task data.

Contact centres and doctors' lines do the same: caller ID, one cheap question, a reference number, then a human. Web search was not used; this is product knowledge, unverified.

## Recommendation: minimum set, ranked

1. **Say it up front (6).** Last line of every vendor call: "Main WhatsApp pe bhej dungi." Cuts inbound calls before they start.
2. **One open task per vendor (2).** Cap the queue wait at about 24 h. The candidate set (1) is then nearly always one task.
3. **Reference code (3).** Short, easy in Hindi, like "F-42". A shortcut, never a requirement.
4. **WhatsApp payload and quoted reply (5) plus "Call me" button (8).** Exact match, no effort.
5. **Ask what it is about (4)** when there is no code. Use number (1) and recency (9) as hints only. Never read a name; confirm only the service and day the vendor already knows.
6. **Ops fallback (7, 11).** Two or more matches, or none: take a message, tell them "WhatsApp pe batate hain", alert ops.

Items 1 to 3 should make ambiguity rare; 6 catches the rest.

## Vendor callback flow (5 lines, Hinglish, DRAFT pending approval)

1. "Namaste, main Friday hoon, ek AI assistant. WhatsApp wali reference code bata dijiye, jaise F-42."
2. No code: "Koi baat nahi. Aap kis kaam ke liye call kar rahe hain, booking ya rate?"
3. "Achha, kya aaj haircut ki booking ke baare mein baat hui thi?"
4. After a clear yes: "Ji, bataiye, main note kar leti hoon."
5. "Theek hai, main customer se confirm karke WhatsApp pe bhej dungi. Call nahi karna padega. Thank you."

If line 3 stays unclear after one try: "Main aapka message team ko de deti hoon, woh WhatsApp pe jawab denge. Thank you."

## Open questions for the founder

1. Code style: letter plus two digits, or two words?
2. Is a 24 h queue cap fine, or should urgent tasks jump the queue? Are users fine waiting?
3. Say the service and day first, or only after the vendor says it? (I recommend the stricter second.)
4. Who in ops gets the "message taken" alert, and how fast must they answer?
5. Approve a "Call me" button template (needs Meta approval)?
6. Staff often call from personal phones: accept that number match is only a hint?
