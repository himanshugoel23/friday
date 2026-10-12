# Friday use cases: build the product around these (brainstorm 2026-10-12, for founder review)

Founder: a generic AI will not work. Friday must win on specific, repeated, painful jobs in an Indian user's life, where
a phone call, a memory and a little initiative do what a chatbot cannot. Friday's unfair advantages: **she can phone people**
(India still runs on calls), **she waits for you** (hold, IVR, "call back later"), **she remembers your people and places**,
and **she acts first** on things you told her or connected.

Score = frequency (how often) x pain (how much people hate it) x wow (would they tell a friend) x feasibility now (1-5 each, shown F/P/W/X).
Status: BUILT / PHASE 1 (beta) / PHASE 2 / LATER.

## 1. Get things done by phone (core, India-specific)
| # | Use case | Example | F/P/W/X | Status |
|---|---|---|---|---|
| 1 | Quotes from 3 nearby vendors, compared | "kal haircut, 3 salon ke rates" | 5/3/5/5 | BUILT (salon), PHASE 1 for 20 categories |
| 2 | Book with delegation | "6 baje ka slot book kar do, 500 tak" | 4/3/5/4 | BUILT (salon) / PHASE 1 |
| 3 | Stock + price check ("kiske paas hai?") | "iPhone 16 256GB kis shop pe milega aaj, kitne ka" | 4/4/5/4 | PHASE 1 (stock_and_price) |
| 4 | Home-service visit quotes | plumber/AC/electrician/pest/packers | 4/5/5/4 | PHASE 1 (home_service_visit) |
| 5 | Table / banquet / hotel enquiry | "Sat ko 8 logon ke liye table, veg" | 4/3/4/4 | PHASE 1 |
| 6 | Rentals (cab, PG, equipment) | "kal Innova 2 din, kitna" | 3/3/4/4 | PHASE 1 |
| 7 | **Customer-care warrior:** call a company, sit through IVR and hold, get a human, raise/follow up a complaint or refund, log the ticket no., call again till solved | "Airtel ka bill galat hai, theek karwao" | 5/5/5/2 | PHASE 2 (hero; IVR navigation exists in the vision) |
| 8 | **Wait on hold for me** and ping when a human picks up | any helpline | 5/5/5/3 | PHASE 2 |
| 9 | Cancel / downgrade / negotiate (broadband, gym, subscription, insurance renewal) | "gym cancel karwa do" | 4/5/5/2 | PHASE 2 (needs legal-safe wording) |
| 10 | Relay to vendors in their language (Kannada/Tamil/Marathi/Bengali) | Bangalore autowala, local plumber | 4/4/5/2 | LATER (STT/TTS per language) |
| 11 | Tell someone for me ("plumber ko bol do main 20 min late hoon") | quick call/message on my behalf | 4/2/4/4 | PHASE 2 |
| 12 | Appointments at clinics/labs for me or parents (fees + slot only) | "papa ke liye diabetes checkup, subah ka slot" | 4/4/5/4 | PHASE 1 (quote_and_slot) |

## 2. Family and care (emotional hook, strong retention)
| 13 | **Parents check-in calls** (daily/weekly, warm, Hinglish, summary + red flags to the child) | "mummy ko roz 6 baje call karke haal poochho" | 5/5/5/3 | PHASE 2 (safety product seed) |
| 14 | Medicine / appointment reminders for parents by call | "papa ko dawai yaad dilao" | 5/4/5/3 | PHASE 2 |
| 15 | Occasions: remember birthdays/anniversaries, offer cake/flowers/gift/salon | from what the user said | 4/3/5/4 | PHASE 1-2 |
| 16 | Family logistics: "mummy ko kal doctor le jaana hai", cab + clinic slot together | multi-step | 3/4/5/3 | PHASE 2 |

## 3. Paperwork, money, renewals (people forget; deadlines hurt)
| 17 | **Renewal radar:** insurance, PUC, car/bike service due, licence, rent agreement, warranty; finds quotes by calling | "car insurance 12 din mein expire: 3 quotes nikaalun?" | 4/5/5/3 | PHASE 2 (from mail/docs/what user said) |
| 18 | Bills due + subscriptions seen in mail ("Netflix + 2 aur, Rs 1,400/mahina") | digest | 5/3/4/3 | PHASE 2-3 |
| 19 | Government/office slots (RTO, passport, bank branch visit timing: phone enquiry) | | 3/4/4/2 | LATER |
| 20 | Documents: user forwards a bill/PDF/photo; Friday explains, files, reminds | | 4/3/4/4 | PHASE 2 |

## 4. Inbox and calendar chief-of-staff (Phase 2 vision)
| 21 | **Unanswered important mail + escalations highlighted**, draft reply on approval | the founder's example | 5/5/5/3 | PHASE 2 |
| 22 | Morning brief: today's meetings, bills, pending replies, weather for plans | one message, user's time | 5/3/5/4 | PHASE 2 |
| 23 | Calendar conflicts and prep ("2 meetings 5 baje, ek shift karun?") | | 4/3/4/4 | PHASE 2 |
| 24 | Travel: flight/hotel from mail -> reminders, cab to airport, hotel call for early check-in | | 3/3/5/3 | PHASE 2-3 |

## 5. Home and daily life
| 25 | Recurring services: maid/cook/water can/gas/cleaning/AC service before summer/pest cycle | "har 3 mahine pest control" | 4/3/4/4 | PHASE 2 |
| 26 | Quick local help: nearest open pharmacy/vet/car mechanic NOW + call to confirm stock | "raat ko dawai kahan milegi, abhi" | 4/5/5/4 | PHASE 1 (stock_and_price) |
| 27 | Move-house pack: packers + PG/flat + internet + cleaners, one project | | 2/5/5/3 | PHASE 2 |
| 28 | Event helper: decorator, catering, photographer, DJ quotes compared | "party Sat ko 30 log" | 2/4/5/4 | PHASE 1 (enquiry) |

## 6. Safety (later; builds on the parent calls)
| 29 | Check-in on a schedule; alert contacts if no answer; share-location request link | | 4/5/5/2 | LATER |

## Cross-cutting "magic" (makes every use case feel like Jarvis)
- **Memory:** people (mummy, wife), places (home, office, parents), preferences (veg, budget, favourite salon), what happened last time.
- **One recommendation with reason**, never a menu; ready next action with a button.
- **Proof of the call:** what the vendor said in one line, optional recording summary.
- **Zero chatter:** outcomes only. **Honest:** "yeh mujhse nahi hoga, yeh kar sakti hoon".
- **Always on our servers:** works when the phone is off; answer is waiting on WhatsApp.

## Hero picks (my recommendation: build the product around THREE promises)
1. **"Ask, and she calls for you."** (1-6, 12, 26, 28): quotes/availability/booking across the 20 categories. Shipping in the beta.
2. **"She waits on hold and fights for you."** (7-9, 11): customer care, refunds, cancellations. Painful, universal, nobody does it well, perfect for a voice agent. **Biggest wow after the beta; start building IVR/hold now.**
3. **"She looks after your people and deadlines."** (13-17, 21-22): parents' calls, reminders, renewals, mail escalations. This is the habit and the moat.

Everything else is a smaller feature on these three. Starting point for new users stays narrow (promise 1), then Friday earns the right to see mail and call parents.

## What we must build (blocks shared by all use cases)
Task engine + project manager (BUILT) -> vendor/archetype playbooks (BUILT, pending audio) -> **IVR/hold navigation + complaint ticket tracker (NEW, promise 2)** -> user memory store + extractor (promise 3) -> proactive planner + scheduler -> connected-source attention engine (Gmail/Calendar) -> parent check-in playbook -> multi-language voice.

## Decisions for the founder
1. Agree with the three promises? Anything missing from your own life or your users' (add use cases here)?
2. Beta launches with promise 1 only; promise 2 (customer-care warrior) as the first big follow-up. OK, or move promise 2 into the beta?
3. Promise 3 order: parents' check-in calls first (emotional, simple), or mail/calendar first (needs Google review lead time)?
4. Which 5 use cases would YOU show to a stranger in 30 seconds to make them say "wow"? (that becomes the landing-page demo)
