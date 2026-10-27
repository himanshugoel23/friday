# Trip concierge reference: Crew and similar (for Friday)

Written 2026-10-27 by the product-manager agent. Public repo: no personal data. Labels: **[V]** verified in a fetched or searched source (date given), **[C]** claimed by the company or a blog, **[U]** unverified or not found.

## 0. Which "Crew"
The closest match is **Swiggy CREW**, relaunched 2026-09-03 as a travel concierge (earlier a lifestyle concierge from June 2025). A different app, NomadCrew, is a group trip planner, not a concierge. If the founder meant another Crew, send a link.

## 1. Comparison table
| Player | What | Channel | Price / who pays | Human in loop |
|---|---|---|---|---|
| Swiggy CREW (India) | Plans and books flights, hotels, cabs, visas, forex, reservations, experiences; 24/7 | iOS/Android app [V Inc42]; WhatsApp in a user story [C Curly Tales] | Subscription, invite-only; sources conflict (see 2) | Yes, human concierges with AI tools [C] |
| Navan (global, business) | Booking, in-trip changes, disruption rebooking, assistant "Ava" | App, web, chat | Employer pays (B2B) [C] | Yes, for hard cases [C] |
| TripIt (global) | Itinerary from forwarded confirmation emails | App, email | Free; Pro (alerts) about $49/year [C blogs] | No |
| Google AI Mode / Gemini | Trip planning (Canvas), Flight Deals, agentic restaurant booking (US) | Search, app | Free | No |
| Pilot (pilotplans.com) | Self-serve trip booking; managed group concierge | Web, apps, chat | Free app, pay-what-you-want; concierge price [U] | Yes, for support/group |
| Mezi (older US) | Text-to-human concierge | SMS | [U] | Yes; still operating [U] |
| Mondee (Abhi) | AI itinerary inside a travel marketplace (2023) | Web | [U] | [U]; current status [U] |
| Card concierge (Amex Platinum, HDFC Infinia, Diners Black) | 24x7 phone/lifestyle/travel requests; lounge access | Phone, app | Annual card fee; invite/spend-linked | Yes, humans |
| IndiGo 6Eskai, Air India AI.g | Airline bot: book, check-in, boarding pass, status | WhatsApp | Free | No |

## 2. What each does, step by step, for a family trip
**Swiggy CREW** (the reference)
- [V] Positioned as a "personal travel concierge" for affluent urban users; travel was 40-50% of requests in the pilot, so Swiggy narrowed to travel ([Skift 2026-09-03](https://skift.com/2026/09/03/swiggy-has-a-new-travel-concierge-can-a-food-del)).
- [V] Covers flights, hotels, cabs, visas, forex, reservations, local experiences, 24/7 across time zones ([Inc42 2026-09-03](https://inc42.com/buzz/swiggy-narrows-crews-focus-to-travel-after-year-long-concierge-pilot/)).
- [C] A parent travelling to Europe with kids said the concierge stayed on WhatsApp through the trip and changed sightseeing reservations on arrival ([Curly Tales 2026-09-03](https://curlytales.com/india/trending/swiggy-goes-beyond-food-swiggy-crew-will-now-plan-your-trips-babysit-your-itinerary/amp/)).
- [V] Price conflict: Skift says INR 999 for six months; Curly Tales FAQ says INR 999 per quarter; Inc42 and Deep Arrival give no price. Treat price as **unverified**.
- [U] Not found in any source: document vault, hotel pre-arrival calls, cab flow, flight-time monitoring, leave-by-time, lounge by card, proactive alert design, refund or spend-cap rules. The founder's list below is therefore Friday's own design, not a verified copy of Crew.
- [C] Deep Arrival (a blog) says Crew cannot change bookings automatically because suppliers control approvals ([source 2026-09-03](https://deeparrival.com/news/swiggy-crew-24-7-travel-concierge-2026/)).
- [V] Financial reality: Toing and CREW together made INR 51 Cr revenue and INR 131 Cr loss in Q1 FY27; Swiggy's annual report says not every experiment will scale (Inc42, same link). Human concierge at scale is expensive.

**The founder's checklist, by who does it (verified evidence only)**
| Step | Who does it, evidence |
|---|---|
| Structured family vault (tickets, passports, hotel confirmations, check-in times) | TripIt builds a master itinerary from forwarded confirmation emails or a linked Gmail/Outlook inbox [C, blogs, [10xtravel](https://10xtravel.com/tripit-everything-you-need-to-know/)]. Crew: [U]. |
| Call hotel before arrival | No competitor found that does this as a documented feature. Card concierges do "hotel referral and reservation assistance" [C, [Paisabazaar](https://www.paisabazaar.com/hdfc-bank/hdfc-diners-club-black-credit-card-review)]. **Open gap.** |
| Cab booking | Listed by Crew as a service [V]; mechanism [U]. |
| Leave-by time and flight monitoring | TripIt Pro: real-time flight alerts, and a "when to leave for the airport" feature, US flights only [C, 10xtravel]. Navan: alerts before disruption and rebooking [C, [Navan](https://navan.com/blog/the-new-rules-of-travel-support)]. IndiGo 6Eskai gives flight status on WhatsApp [C, [Times Aerospace](https://www.timesaerospace.aero/news/technology/indigo-launches-6eskai-on-whatsapp)]. |
| Lounge by credit card | Access is via card authorisation at a terminal run by DreamFolks-type middleware, plus card and same/next-day boarding pass; eligibility needs an active card [V, [IDFC FIRST T&C](https://www.idfcfirstbank.com/content/dam/idfcfirstbank/pdf/credit-card/first-private/Airport-Lounges-Terms-and-Conditions-FIRST-Private-Credit-Card-01.pdf)]. Rules change often: Amex Mumbai Centurion lounge closed 2026-07-01 [C, blogs]. Nobody found that picks the lounge for the user from the card. **Open gap.** |
| Itinerary timeline | TripIt, Google Canvas ([BGR](https://www.bgr.com/2028290/google-flight-deals-ai-mode-canvas-travel/)), Wanderlog-type tools [U]. |
| Proactive alerts | Navan, TripIt Pro [C]. Crew: [U]. |

## 3. How they appear to do it
- **Humans plus AI tools** is what Crew, Navan and card concierges say [C]. Navan claims 50% of support resolves with no human, self-reported [C, [Navan](https://navan.com/blog/the-new-rules-of-travel-support)]. Nobody published the human share for Crew.
- **Email parsing** is how TripIt gets data [C]. Drive/Docs folders: no source found for any competitor [U].
- **Supplier APIs / partner networks:** Crew mentions "negotiated" hotel rates and a partner network, none named [V that it is claimed, partners U]. Mindtrip books flights through Sabre [C, [Fast.io](https://fast.io/resources/best-ai-for-travel-planning-2026.md)]. Google plans hotel and flight booking with Booking.com, Expedia, Marriott and others, not live in the sources read [C, [GSMArena](https://m.gsmarena.com/googles_ai_mode_expands_agentic_restaurant_reservations_flight_deals_canvas-news-70334.php)].
- **Who pays:** consumer subscription (Crew), employer (Navan), card issuer through annual fee (card concierge), commission or free (Google, airlines). Swiggy says subscription is not the only revenue source, not specified [V, Skift].

## 4. Spending caps, proof of completion, refunds
- **Crew / Navan / card concierge:** no public spend-cap, proof or refund policy found [U]. Deep Arrival says Crew has no published cancellation policy or price guarantee [C].
- **Card networks (global, launch-era 2025):** Visa Intelligent Commerce and Mastercard Agent Pay let consumers set spend limits, require authorisation, use tokenised agent credentials, and plan dispute handling for agent purchases [C, [Digital Commerce 360 2025-05-06](https://www.digitalcommerce360.com/2025/05/06/visa-mastercard-ai-agentic-commerce/)]. Current 2026 status [U].
- **India rail for caps:** UPI Circle lets a primary user delegate to up to 5 people; full delegation capped INR 5,000 per transaction and INR 15,000 per month; partial delegation needs the primary user's PIN [C, secondary sites, NPCI circular not read; [Razorpay](https://razorpay.com/blog/what-is-upi-circle/)]. Fits Friday's "user pays by own UPI app" rule (HANDOFF 2026-10-17): the cap is a Friday rule, the PIN is the user's.
- **Proof:** the Ken page also lists proof and held-money ideas; see `docs/KEN_AGENTS_NOTES.md` (case-competition prototypes, not shipped products).
- Practical proof for a phone agent (Friday's own design, not copied): confirmation number said by the vendor on the call, call recording or transcript excerpt, vendor's own message or booking page, receipt.

## 5. Photos and documents into data
- **Google Document AI** has a generally available US passport parser returning key-value fields, an ID-proofing parser that scores tampering, and an optional human-review step [V, [Google Cloud](https://cloud.google.com/solutions/identity-doc-ai?hl=ro) and [overview](https://docs.cloud.google.com/document-ai/docs/pretrained-overview)]. Indian passports, Aadhaar, price, data residency: [U]. DPDP treatment: [U], needs legal check.
- **Email route:** forwarded or linked-inbox confirmations (TripIt) [C]. Friday already has Gmail consent (HANDOFF 2026-10-14/19).
- **Vision LLM route** (Friday's existing media slice 4b): extract fields from a photo, show the user the extracted fields, ask "right?" before saving [Friday design, no competitor source].
- Crew's own method: [U]. Deep Arrival notes visa help may need passport details and tells users to ask about storage and deletion [C].

## 6. What Friday should build first (ordered)
1. **Trip card from what the user already sends** [design]. Forward email, photo of ticket/booking, PDF: extract (airline, flight, time, PNR, hotel, check-in time, address) into one trip record per family; reply with a 5-line summary and ask to confirm. Evidence it works: TripIt model [C]. Fewest new integrations.
2. **Document vault, our own store, encrypted, per family, with delete-all** [design]. Do not use Drive by default (founder earlier said no Drive; no competitor evidence for Drive). Passports and IDs: store only after explicit consent, show what was extracted, DPDP review first [U].
3. **Leave-by time and flight check** [design; competitor evidence C]. Compute from flight time, airport, traffic, check-in rules; one WhatsApp nudge the evening before and on the day; re-check delays. Needs a flight-status data source [U which].
4. **Call the hotel before arrival** [design; open gap, no competitor found]. This is Friday's core skill (phoning businesses): confirm booking, check-in time, early check-in, cab pickup, extra bed. Proof = hotel-said confirmation in the call summary. Best differentiator.
5. **Proof line on every "done"** (summary, confirmation number, recording excerpt) and **named human fallback** after two failures (see KEN notes).
6. **Per-user spend cap shown at consent** (daily and per transaction), Friday never moves money; user pays via own UPI. Refund tracking: log amount, vendor, promised refund date, nudge the vendor by call [design; no competitor model found].
7. **Lounge hint by card** [design]: user tells Friday which cards they hold (never card numbers); Friday states the typical lounge benefit and the rule (card plus boarding pass) and warns that rules change [V rule, C card details]. Defer until 1-6 work.
8. **Cab booking** last: use the private-browser connectors already built (fake sites only), approval before any payment.

Avoid: promising lowest price or automatic rebooking (Crew has no guarantee; suppliers control changes [C]); hidden humans on calls (Muse lesson in COMPETITORS.md); storing card numbers; running a human concierge team (Swiggy's loss, V).

## 7. What I could not verify
- Crew: price (conflicting), vault, hotel calls, flight monitoring, lounge, refunds, caps, human-to-AI ratio, WhatsApp as an official channel (one user story only), partners. No user reviews or app-store text found; Crew is invite-only.
- Navan's performance numbers are self-reported; navan.com/phocuswire pages: Phocuswire returned HTTP 403, so Ava details come from search snippets only.
- HDFC/Amex concierge process, response times, and DreamFolks involvement per card; card-comparison blogs conflict and are affiliate-driven.
- Tripadvisor trip tools, Mondee's current status, Pilot concierge pricing, Mezi status: not found.
- NPCI's UPI Circle circular was not read; limits come from secondary sites.
- Reddit, X and app-store reviews were not searched in this pass.
- No India-specific consumer competitor with a WhatsApp document vault was found in one search; not proof that none exists.

## Addendum (2026-10-27): founder-shared LinkedIn testimonial of a CREW user (screenshot, one person, claimed)
No names recorded here. The post describes, for a family holiday:
1. **~30% discount** on the hotel stay vs online marketplace rates ("exclusive", not available elsewhere): suggests negotiated/direct rates, not just booking.
2. **"Trip Assist" = a WhatsApp group between the CREW concierge team and the family** (humans in the loop, WhatsApp is the main channel).
3. They **checked the family in for flights**, **filled arrival cards and Air Suvidha-type travel forms**, **created a Google Drive with all travel documents**, **planned a day-wise itinerary with bookings and reservations**, **sent reminders at the right time**, and were available for basic help.
Takeaways for Friday: (a) confirms the founder's recollection: a shared Drive folder + WhatsApp group is the product; (b) new items beyond our list: flight web check-in, arrival/health/customs form filling (browser connector, user approval, supervised), negotiated hotel rates (needs supply deals; not buildable by software alone); (c) still unverified: how much is human vs AI, price, scale.
