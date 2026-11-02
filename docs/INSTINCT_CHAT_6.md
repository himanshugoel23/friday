# Instinct chat 6: what it solves, how, and the reply lines (2026-11-02)

Source: the founder's own 3-week export with Instinct (9 Oct to 2 Nov 2026). The raw file, voice notes, resumes and PDFs stay OUTSIDE the repo (personal data, one-time codes, a private conversation). This file keeps only product lessons: no names, employers, numbers, addresses, amounts or private circumstances. Reply lines are PARAPHRASED patterns in Roman Hinglish (the founder's chat language), not copied text.

Founder ask (2026-11-02): "see what it can solve and how it is solving it, what lines it is replying. We need to add all of these things into our product."

## A. The conversation shape (applies to every flow)
1. **Acknowledge in one line, say what it will do AND where it will stop.** "Checking X now. Nothing gets booked or paid until you approve the total."
2. **Honest progress when asked "status?"**: say what step it is on and why it is slow ("their site is slow, 2-3 min"), never silence.
3. **Result = short text + a screenshot proof** (page shows the real address bar/URL where possible), then ONE question.
4. **Approve before anything irreversible**: show restaurant/items/address/total with fee lines, then "reply with the number once you approve".
5. **Payment is the user's**: 3 options (UPI QR / collect request approved in the user's own app / cash on delivery). QR expires in about 4-5 min; when it lapses: "say 'pay' and I make a fresh one". On "cancel" it says plainly: nothing was charged, do not scan the QR.
6. **Limits stated plainly with the next best thing**: cannot read phone SMS, cannot send messages to other people, cannot set a phone alarm, cannot take calls: each answer ends with what it CAN do ("I will write the message, you send it", "I will remind you here at 2:45").
7. **Block = stop and hand over**: "I will try once. If the site blocks me I tell you and give the exact manual steps (about a minute)." Rapido had no web booking: said so, gave the app steps / official deep links.
8. **Memory on request**: "what do you know / remember about me" -> bullet list of facts + "tell me anything wrong or to forget".
9. **Language follows the user**: Hinglish by default; switched to Devanagari Hindi when asked ("Hindi mein jawab do") and stayed there.
10. **Proactive**: morning heads-up of today's calls/clashes, "interview in 15 min" at a set time, a daily evening "what I did" summary, deadline warnings ("this posting closes tonight").

## B. What it solved, and how (capability -> mechanism -> reply pattern)
| # | Solved | How | Reply pattern (paraphrase) |
|---|---|---|---|
| 1 | Inbox triage | Google connect link, then reads mail | "Two leads need replies: ... Gmail is 99% full. Want me to draft replies for you to approve?" Corrects itself when wrong ("you already replied to X"). |
| 2 | Subscriptions list + cancel | Reads receipts in mail; for cancel it needs the user's login (vault link) | Active / ending lists with amounts and renewal dates; "email only shows part, UPI autopay mandates are listed in your bank/UPI app"; cancel: says what cancelling does (access till period end, no refund). |
| 3 | Food order | Cloud browser on Zomato; login by phone + OTP the user types in chat; shows menu, then cart total with fee lines, then UPI QR | "Zomato sent a 6-digit code to your phone. Send it here." Session stays saved so repeat orders skip the OTP. |
| 4 | Cab fare compare | Browser reads Uber/Ola web fares after OTP login; no booking | Fare table per service, "Uber is cheaper by X, want me to book?"; when web booking is impossible it sends official deep links (Uber format verified, Ola "may not prefill", Rapido none) and says payment/fares happen in the app. |
| 5 | Hotel search | Booking provider search + browser read of Booking.com; comparison sheet page | "My pick / cheapest and most flexible / others"; says payment is NOT possible via a US-only wallet and offers INR options; says plainly the sheet is not the hotel's site. |
| 6 | Salon booking | Urban Company via browser, OTP login, saved address and saved UPI id | Offers 3-4 options with price; asks the address (and uses the saved one when the typed one is not found: "I found your saved Home address, send it there?"); shows free-cancellation window; cancel = nothing booked. |
| 7 | Train options | Reads seat availability from a public rail site, tells the source; booking only on IRCTC with the user's own account | Lists trains/classes with price and seats, gives a personal pick for "day arrival" vs "overnight". |
| 8 | Price check on quick-commerce | Browser on Zepto/Blinkit | Zepto location failed for it too ("Location not found" with every pincode); it said so, offered Blinkit/Instamart or the Zepto app; Blinkit worked: price, MRP, ETA, product link, screenshot, then OTP login and a final bill with handling/late-night fee lines and the delivery address to confirm, then QR. |
| 9 | Bill lookup | Opened last paid Zomato order and sent the invoice PDFs | Notes "no paid order after <date>" instead of inventing one. |
| 10 | Card bills due | Reads statements from mail | Per card: amount, minimum due, due date, "email numbers are not live balances"; nudges "late fee and credit score" without scolding. |
| 11 | Car insurance | Web research then advice | Ask the 3 facts needed for a quote (model/year, registration city, old policy expiry + claims), advice "claims support first, price second", compare site named, "do not buy from the dealer". |
| 12 | Documents | Clean PDF from a photo; research reports; comparison sheets | Refuses to make a fake fuel bill (see D). |
| 13 | Job hunt (largest block) | Shortlist, then browser applications on portals and company pages, daily run, evening report, referral messages | See section C. |
| 14 | Idea/market research | Reads screenshots of idea lists, ranks them as businesses, cites the source and says "company claim, not independently verified" | Gives a first pick AND why not to copy a winner. |
| 15 | Care in distress | Warm, long, direct | See section E. |

## C. Job-hunt assistant: how it works (the part to copy, carefully)
Flow it ran: ask what is keeping the user busy -> offer interview prep -> connect Google -> read resume from mail/Drive -> shortlist roles that fit -> ask the minimum questions in ONE message (expected pay, notice period, address to use, reason for leaving, previous pay per employer, yes/no legal questions) -> open portals, fill from the saved profile, upload resume, submit -> proof screenshot per application -> daily count + evening summary -> referral outreach drafts per contact -> user approves one by one.
Lines (paraphrased): "Hirist and IIMJobs codes landed in your Gmail, I read them myself, nothing for you to do"; "Profile already has 'immediately available', expected pay X negotiable: keep as is?"; "Two resumes say different numbers (15,000 vs 2,000 calls a day): which is right?"; "The site's own upload is failing in my browser (tried twice): please upload this PDF yourself, 2 steps, then say 'done' and I verify and continue" and, when told "you do it", "trying another way".
Smart bits: it asked before overwriting profile fields, flagged posting deadlines, summarised "today: N applications" with names, drafted referral messages with the role link and a short proof-points list, sent ONE first, waited for approval, then sent the rest; offered an "honest version" of a resume when the user admitted numbers were polished.

### Instinct mistakes Friday must NOT copy (observed)
1. It **created an employer-portal account and a password by itself**, stored it in its vault, and put the login id in chat. Friday: the user sets their own password through the vault link; never print the login id; ask first.
2. It **e-signed** after one "ha krdo" even though it first explained the consequences (good). Friday: show the exact words, require a plain yes FOR THAT ACTION (already designed).
3. It **filled form facts by inference** ("7 years" from dates) and later admitted it should have asked. Friday: never infer a fact the form asks for; ask, or leave it and say so.
4. It **created a government railway account** collecting date of birth and address. Friday: no government/identity accounts (hard rule).
5. It said "I am not a doctor" then gave a dose; it **diagnosed depression** to a person in distress and talked product during it; it argued "feelings vs facts" at length. Friday: no diagnosis, no product chatter, protocol in section E.
6. It **went silent for hours** (WhatsApp delivery fault) and only apologised at 3 a.m. Friday: if a reply is late, the next message starts with the reason and the time.
7. Its **upload from the headless browser failed repeatedly** on two portals. Friday: design the upload path early, tell once, give the manual steps.
8. It **appended "1-" to a resume filename** on a LinkedIn attach and could not remove it, asked the user, who said send anyway. Friday: warn BEFORE sending when a known side effect would change what the recipient sees.
9. It **used Google sign-in on the user's account**, which triggered a phone approval prompt that the user had not expected. Friday: say before, "your phone will ask you to tap yes".
10. It **quoted a posting deadline wrongly then corrected it** in the next message. Friday: "I am not sure, here is the page" instead of asserting.

## D. Refusals it got right (copy the shape: no, why in one line, then what it WILL do)
- Fake fuel bill for the employer (even "just a sample"): refused; "ask the pump for a duplicate bill, send me the photo, I make a clean PDF".
- Cigarettes in a grocery order: "I cannot do that one, order it yourself in the app", continued the rest of the order.
- Calling the user's relative to scare them: "I cannot call anyone; I can write a message you send".
- Chest pain with fever: no dosage talk beyond common advice; "if pain is severe/radiating/short of breath call 112 now", then ONE question about severity.

## E. Distress: what it did, and the Friday protocol
It stayed with the user for hours, named 14416 (Tele-MANAS, free, 24x7, Hindi) and 112, asked the direct safety question once, asked for a promise to call next day, gave 3 tiny steps (water, lie down, call tomorrow, message me tomorrow), checked in the next day.
Friday keeps what worked and drops what did not: short calm replies; ask the direct question ONCE ("do you have thoughts of hurting yourself?"); give 14416 and 112; offer to message a trusted person the user names (draft for the user to send); NO diagnosis ("this looks like depression"), NO pep-talk arguments, NO product or work talk until the user is steady, a gentle check-in later the same day and next morning, protocol stays on even when other features are off, never logged into training data or the reply log. See docs/GUARDRAILS_MODULE.md.

## F. Browser findings from this chat (for the architecture decision)
- Instinct runs a **cloud browser (a Chrome session on a server)**; the phone is only the chat surface; sessions are kept per user so repeat tasks need no new OTP.
- It **also failed Zepto** ("Location not found" for every pincode) and **got Blinkit**, Zomato, Urban Company, Uber, Ola, Booking.com, job portals, company career pages, IRCTC. Rapido has no web booking.
- It explains blocks by IP type, fingerprint and behaviour; advice to the founder: **block = stop, never fight; no stealth from day one; hosted browser until about 100 users; the moat is workflow + trust + memory**; cost about $1-3 per light user per month for hosted browsers (public estimate).
- It never claims it will not be blocked ("I cannot promise").

## G. Friday status against this chat (to be kept current by the builders)
Have: honest limits, vault links, OTP in chat, proof cards, UPI QR/link with user paying, step-by-step web tasks, PM team, shopping comparison, subscription cancel playbooks, refund tracking, receptionist, guardrails.
Gap list for the flow pack (see the builder briefs in HANDOFF 2026-11-02): grouped questions everywhere, "status?" honesty, "pay" regenerates QR, saved-address fallback, deep links for rides, fee-line totals, daily morning heads-up and evening summary, card-bill-due summary, subscription list from mail, memory recap + forget, referral/outreach drafts with approve-one-first, job pipeline in preview mode with daily cap, distress protocol upgrade, late-reply apology line.

Every new customer-facing line is PENDING founder approval (docs list).
