# Inbound ID: which user or task is this call or message for? (PM view)

Status: proposal for the founder. Wording is a draft, pending approval.

## The problem

One shared number. A salon calls back (or replies on WhatsApp) and the salon may be handling several of our users. Staff are busy, not technical, and forget names. Today we match only by caller number (docs/FRONT_DOOR.md). That fails when the salon calls from another phone, or has two open tasks.

Rule for everything below: **never guess, and never say another user's data**. A wrong match is worse than "we will call you back".

## Candidates

| # | Idea | Feels to the business | Fails when | Privacy risk | Cost |
|---|---|---|---|---|---|
| 1 | Candidate set = open tasks for this vendor number | Invisible | Vendor calls from another phone; 2+ open tasks | Low | Free |
| 2 | Max one open task per vendor; queue the second | Invisible | Slows user 2; very urgent tasks wait | Lowest: ambiguity mostly gone | Free, some delay |
| 3 | Short reference code, spoken at end of call, sent on WhatsApp, asked on callback | One small ask | They forget or lose it | Low (code has no data) | Free |
| 4 | Ask "kis kaam ke liye?" and match to that vendor's open tasks, no names read out | Natural, like a receptionist | Vague answer ("wohi booking") | Low if we only repeat what they already know | One short LLM match |
| 5 | WhatsApp buttons and quoted replies carry the task id | Zero effort: they tap or reply | Unquoted new message; 24 h window rules | Low | Template fees |
| 6 | Tell them up front: "I will call back or WhatsApp you, no need to call" | Reassuring | Some still call | None | Free |
| 7 | Take a message, send to ops, no guess | Slightly slow | Ops delay | None | Ops time |
| 8 (new) | **"Call me" button** in WhatsApp (Truecaller Business, Uber style callback request): the vendor taps, Friday calls them, so the task is known | Easier than dialling | Needs WhatsApp on the vendor phone | None | One outbound call |
| 9 (new) | Recency hint: most recent call we made to this number in the last 2 hours | Invisible | Wrong if two calls were close | Low | Free; **hint only, never the final answer** |
| 10 (new) | Keypad code (press digits) | Clunky | Many will not | Low | Free; skip for now |
| 11 (new) | Masked number per user and vendor (Uber, Zomato) | Smooth | Needs many numbers | Low | Out of scope by founder decision |
| 12 (new) | Stranger path: unknown number gets the identity line only, no task data | Polite | None | None | Free |

Contact centres and doctors' lines solve this the same way: caller ID first, then one cheap question, then a reference number, then a human. Urban Company and Zomato avoid the problem by never letting the vendor call the platform at all. Meta's quoted replies and button payloads do the same on chat. I did not search the web for this; it is from product knowledge, so treat it as unverified.

## Recommendation: the minimum set

Rank 1 to 6. Items 1 to 3 do most of the work.

1. **Tell them up front (6).** Last line of every vendor call: "Main WhatsApp pe bhej dungi, aapko call nahi karna padega." This cuts inbound volume before it starts.
2. **One open task per vendor (2), with a queue.** Cap the wait (suggest 24 h, then expire the old task). Then the candidate set (1) is almost always one task. Different users wanting the same salon is the case this fixes.
3. **Reference code (3).** Short, easy to say in Hindi, for example "F-42". Spoken twice at the end of the call, sent on WhatsApp, asked first on callback. A code is a shortcut, never a requirement.
4. **WhatsApp payload and quoted reply (5) plus "Call me" button (8).** Exact match, no effort. An unquoted WhatsApp message follows the call rules.
5. **Ask what it is about (4)** when no code: match only against this vendor's open tasks. Use the number (1) and recency (9) as hints. Never read a user's name out; confirm only what the vendor already knows ("haircut ki booking").
6. **Ops message fallback (7).** If two or more matches remain, or none: take a message, tell the vendor "hum aapko WhatsApp pe wapas batate hain", alert ops. Never guess. Strangers (12) get the same path with no task data.

With 1 to 3 in place, ambiguity should be rare, and 6 catches the rest.

## Vendor-facing callback flow (5 lines, Hinglish, DRAFT pending approval)

When a vendor calls in:

1. "Namaste, main Friday hoon, ek AI assistant. Aap hamari WhatsApp wali reference code bata dijiye, jaise F-42."
2. If no code: "Koi baat nahi. Aap kis kaam ke liye call kar rahe hain, booking ya rate?"
3. "Achha, kya aaj haircut ki booking ke baare mein baat hui thi?" (only the service and day the vendor already knows)
4. After a clear yes: "Ji, bataiye, main note kar leti hoon."
5. "Theek hai, main customer se confirm karke aapko WhatsApp pe bhej dungi, call nahi karna padega. Thank you."

If step 3 is unclear after one try: "Main aapka message team ko de deti hoon, woh WhatsApp pe jawab denge. Thank you."

## Open questions for the founder

1. Code style: letter plus two digits, or two words? Is "F-42" easy for your salon and clinic contacts?
2. Is a 24 h cap on the queued second task fine, or should urgent tasks jump the queue?
3. Is "one open task per vendor" acceptable for users, who may wait longer for quotes?
4. May Friday say the service and day on the callback, or only after the vendor says it first? (I recommend the second, stricter.)
5. Who in ops receives the "message taken" alert, and by what time must they answer?
6. Do you approve a "Call me" button template? It needs Meta approval.
7. Staff often call from a personal phone, not the listed number. Do we accept that number match is only a hint?
