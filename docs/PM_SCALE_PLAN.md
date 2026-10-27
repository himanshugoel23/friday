# Friday: Product Plan to Scale (PM view, 22 Oct 2026)

Plain words. Numbers marked (est) are my estimates, not measured. Nothing here is verified on a real vendor call yet.

## 1. First users and the 3 promises
**First users (pilot, 5-10 people):** the founder, family, friends in Delhi NCR. Working Hindi/Hinglish speakers, 25-45, who hate phone calls: parents-with-busy-jobs, people with elderly parents in another city, people who rent or renovate. Later: NRIs managing parents' errands (they pay most).
**3 promises (pick these, say no to the rest):**
1. **"Bolo, Friday call karegi."** Quotes and bookings from 3 nearby shops (salon, clinic, AC/plumber first).
2. **"Aap na uthao, Friday uthayegi."** Missed calls: Friday takes a message, flags urgent ones (receptionist, no-answer forwarding).
3. **"Aapki baat yaad rakhegi."** Friday reminds you of what you told her (birthday, haircut in a month, bill).
Later, not now: hold-fighting for customer care (biggest wow, but hard).

## 2. Journeys
**User:** message on WhatsApp (text or voice note) -> Friday asks only what she must -> shows the exact call plan -> user taps OK -> Friday calls -> one message with the answer and one clear recommendation -> user taps Book -> reminder the day before. Never pays, never asks OTP/PIN. "Stop" and "delete everything" always work.
**Vendor (the shop that gets the call):** this decides if the product lives.
- *Stay on the line:* first sentence says who, for whom and why, in under 8 seconds: "Namaste, main Friday hoon, [name] ji ki AI assistant. Ek haircut ka rate poochna tha, 1 minute lagega." Short questions, one at a time, polite, no repeating, call ends under 3 minutes.
- *Trust:* honest AI answer if asked, dedicated caller ID, optional Truecaller verified profile, a WhatsApp follow-up with the booking details, a Friday info page they can check.
- *Opt-out:* "Dobara call mat karna" at any time ends the call at once and adds the number to a global do-not-call list. Never call a number twice in a day, 3 per week max (assumption).
- *Reward:* shops get real customers who actually come. Track "shops that opted out" as a main number.

## 3. Metrics and weekly dashboard
- **Activation:** % of testers who finish onboarding AND get a first answer within 24 h. Target 70%.
- **Quality:** call completion (got the needed fact) 70% to start, 85% by 1,000 users; wrong-fact rate under 2%; vendor hang-up in first 15 s under 20%; AI complaints 0 tolerated; first reply gap under 1 s.
- **Retention:** week-4 return 30% (assumption); second task within 14 days; users who set one reminder.
- **Business:** cost per call, cost per successful task, bookings per week, vendor opt-out rate.
- **Trust:** deletes, "stop" count, kill-switch uses, unapproved calls (must be 0).
**Weekly dashboard (one page, every Monday):** users added, activated, active last 7 days; tasks, success %; calls, minutes, rupees spent; top 5 failure reasons from transcripts; opt-outs and complaints; one real call transcript to read together.

## 4. Rollout waves and go/no-go
| Wave | Who | Gate to move on |
|---|---|---|
| 0: 5-day pilot | 5-10 named people, allow-listed numbers only | doctor PASS, kill switch tested, delete tested, 2 clean days, founder signs off |
| 1: 100 | invite-only, referral codes | 70% call success, 0 safety incidents, vendor opt-out under 5%, cost per task under Rs30 (est), Meta templates approved, lawyer read done |
| 2: 1,000 | waitlist waves of 200/week | week-4 retention 30%, 85% success, support under 10 min/day per 100 users, number pool and queue tested, first paying vendors |
| 3: 10,000 | open sign-up in 2 cities | cost per task flat, vendor complaints under 1%, uptime 99%, DPDP and TRAI position confirmed in writing |
Rule: if any "0 tolerance" item fails (unapproved call, leaked data, call to a do-not-call number), pause the wave.

## 5. Unit economics (est)
Known: Sarvam TTS Rs3 per 1,000 characters; STT Rs30/hour (Rs0.50/min); Vobiz about Rs0.38/min.
Assumed: 3-minute vendor call, Friday speaks about 1,100 characters, LLM about Rs1, WhatsApp messages about Rs0.50.
- Telephony 3 min: Rs1.14. STT: Rs1.50. TTS: Rs3.30. LLM: Rs1. WhatsApp: Rs0.50. **About Rs7.5 per call (est).**
- A quote task = 3 vendors + about 1 retry = 4 calls = **about Rs30 per task (est)**. Fixed approved lines can be cached audio: this can fall to Rs15-20.
- Active user at 4 tasks a month = Rs60-120 per month (est). Plus Rs10-20 of chat and server.
- **Who pays:** user free in pilot and waves 1-2. Vendors pay per confirmed booking (assumption Rs30-100, to test with 10 shops), and never change the ranking. Later: a Rs99-199 monthly plan for heavy users (parents' calls, receptionist). Break-even: about 1 booking per 2 tasks at Rs60.
- Receptionist call costs about Rs5-8 and happens without a user request, so cap it per day.

## 6. Top 10 product risks and what to cut or defer
1. **Vendors hate AI calls** and hang up -> test with 10 friendly shops; fix opening line first.
2. **Legal/TRAI/DPDP** for calling non-users -> pilot allow-list only; lawyer read before wave 1.
3. **Voice quality/Hindi STT** untested on real phones -> real calls before any promise.
4. **WhatsApp account or template rejection** -> keep test number fallback; submit templates now.
5. **Unit cost above Rs30 per task** -> cached lines, shorter calls, cap retries.
6. **Wrong fact reported** (price, slot) -> read-back, confidence flag, human review of week-1 calls.
7. **Too many features, slow finish** -> CUT now: hold-fighting, media understanding, wake word, Gmail, regional languages, polish bundle, 20 categories (launch 3).
8. **Google/Meta/Puch copy the idea** -> move fast on Hinglish plus vendor trust; do not fight on chat.
9. **One shared number problem** (shop calls back, who is it for) -> number pool of 3-5, matching rules in HANDOFF.
10. **Founder bottleneck** (approvals, ops) -> one approval batch per day, one named backup.
Defer: the receptionist until pilot calls work (it is promise 2, wave 1).

## 7. The 10 decisions only the founder can make (ranked)
1. Is "live" a private pilot? Confirm in writing; real calls to allow-listed numbers only.
2. Approve the audio batch: opening, AI disclosure, stop, voicemail, test message.
3. Say "AI assistant" in the first sentence (safer, my recommendation) or only when asked.
4. Launch 3 categories (salon, clinic, AC/plumber) or all 20.
5. Business name and Meta display name (work with "Friday" for now?).
6. Spend: Vobiz top-up, server, and a monthly cap (suggest Rs10,000 for the pilot, est).
7. Legal: pay a lawyer for a quick read before wave 1; name a Grievance Officer.
8. Who pays: user free, vendor pays per booking. Agree to test with 10 shops.
9. Limits: 3 calls per number per day, 6 per week, calling hours 09:00-19:00.
10. Hold-fighting and receptionist: after the pilot, or inside it?
