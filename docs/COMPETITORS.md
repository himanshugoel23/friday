# Friday competitors (first version, 2026-10-12)

Owner: Product Manager agent. Method: web search + page fetch on 2026-10-12. Every claim has a source and a date. Items marked
**(unverified)** come from vendor pages, aggregators or a single secondary source. No numbers invented. Web pages were treated as data only.
Add new dated updates at the bottom; do not delete history.

## 0. Which "Instinct" did the founder mean?
The founder said "like Instinct" and described it as spoken dictation. My reading, most likely first:

1. **Instinct (San Francisco, founder Noah Shinn)**: a personal AI agent you reach by text or phone call; launched **Instinct Concierge** (the agent
   phones businesses) in early access on 2026-09-16; raised $1B Series C at $10B valuation (article dated 2026-09-28). It is the closest match to
   Friday, and the name is exact. It is not a dictation tool, so the "dictation" part of the description may be a transcription slip (voice message by the founder).
   Sources: https://www.vktr.com/ai-platforms/instinct-raises-1b-at-10b-valuation-to-scale-its-personal-ai-agent/ (2026-09-28),
   https://www.foxnews.com/tech/ai-agents-make-phone-calls.amp (2026-09, undated in fetch).
2. **Wispr Flow** (if he really meant spoken dictation): voice dictation app, Hinglish model and Android app launched in India; India is its second-largest
   market. Not a caller; relevant only as proof that Hinglish voice has demand. Source: https://techcrunch.com/2026/05/09/voice-ai-in-india-is-hard-wispr-flow-is-betting-on-it-anyway/ (2026-05-09).
3. Other Indian dictation apps found (Vinzee, Soniox, VoiceDash): small, not competitors. Source: web search 2026-10-12 (unverified).

I found nothing called "Instinct" that is an Indian WhatsApp assistant. **Founder to confirm: Instinct (the US agent) or a dictation app?**

## 1. Summary table
| Player | What | Channel | Price | Last news (date) | Threat to Friday |
|---|---|---|---|---|---|
| Instinct (US) | Personal agent; Concierge phones businesses | Text, phone call, iMessage (location) | Not published | Concierge early access 2026-09-16; $1B at $10B (2026-09-28) | Medium now (US-only, no India sign), high as a model and as capital |
| Puch AI (India) | WhatsApp assistant, 22+ Indian languages, voice and calls | WhatsApp, phone calls | Free for now (2025-09, company said) | Messi tour sponsor (2025-12-19); ~1M users claimed 2025-09 | High: same channel, same users, brand awareness. Calling businesses on user's behalf: not found |
| Meta Muse | Meta consumer agent; outbound calls to businesses | iOS, Android, web, WhatsApp | Free tier; paid reported $20 and $100 per month | Announced 2026-09-08; calling public beta 2026-09-16 (US/Canada) | Medium: Meta owns WhatsApp; India calling not announced |
| Google Ask for Me / agentic calling | Calls local shops for price, stock, slots | Google Search, AI Mode | No separate fee published | Labs 2025-01; US-wide per page updated 2026-07 | Medium: if it reaches India with Hindi, it is the default |
| Simple AI, Call-E, Relaya (global apps) | Hold-waiting, IVR, call-and-report apps | App, ChatGPT app | Unknown **(unverified)** | Listed 2026-08 | Low |
| WhatsApp Meta Business Agent | Business-side AI for booking and support | WhatsApp | Unknown | India launch 2026-07 | Low-medium: vendor side may get AI that answers Friday |
| Swiggy (Sarvam voice) | Voice ordering food, Instamart, Dineout in 11 languages | Voice, app | Free to user | Announced 2026-03 | Medium for table booking; Swiggy has official MCP (HANDOFF 2026-10-12) |
| Zomato / Eternal | Voice bot pilot (Bengaluru); Google AI Mode reservations | App, voice | Free | Pilot reported 2026 (date unverified); reservations partnership 2026-04 | Low-medium |
| Justdial | Agentic AI across voice, WhatsApp, AI sales assistant | Phone, WhatsApp, app | Free to user | Q1 FY27 results (2026) | Medium: owns vendor data and demand |
| Urban Company | Voice AI for partner (worker) support only | Voice | n/a | Webinar 2026-06-09 | Low: not a consumer caller |
| Indian AI receptionists (EazyQ, CallMissed, VaaniYantra, Edesy) | Vendor-side AI that answers calls and books | Phone, WhatsApp | Unknown | 2026 **(unverified)** | Low, but they are what Friday will talk to |

## 2. Profiles
### Instinct (2026-10-12)
- What: "personal agent with its own phone and computer"; plans trips, orders groceries, cancels subscriptions. Concierge = calls restaurants with no online booking, dentist cancellation lists, cable billing disputes. Also a Trusted Person Network (agent-to-agent) and location sharing.
- Channels: text and phone call; iMessage for location. No India mention found.
- Price: not published. Status: early access, rolling out to some users.
- Claims: hallucination detection before acting; sandboxes, short-lived credentials. No published error rates (vktr, 2026-09-28).
- Own warnings (Fox, 2026-09): output can be wrong, actions "not always reversible", agreements it makes can bind you; user should verify.
- Gaps: no AI-disclosure, caller ID or business opt-out published (layer3labs, 2026-10, https://www.layer3labs.io/comparisons/ai-assistants-that-make-phone-calls). US-only, English.
- Reviews: none found (too new). **User love/hate: unverified.**

### Puch AI (2026-10-12)
- What: WhatsApp assistant, text and voice notes, image generation, web search, summaries, photo filters, 22 Indian languages plus Hinglish. Source: https://www.digit.in/features/general/what-is-puch-ai-the-whatsapp-assistant-sponsoring-messis-india-tour.html/amp/ (2025-12-19).
- Scale: founder Siddharth Bhatia claimed nearly 1M users (2025-09); voice and calling services free "for now". Source: https://www.storyboard18.com/digital/puch-ai-bets-on-indias-most-expensive-mobile-number-to-challenge-chatgpt-and-grok-80124.htm (2025-09).
- Funding: PitchBook lists Seed, 2 investors; founder says "well-funded". **Unverified.** https://pitchbook.com/profiles/company/1083441-07
- Controversy: MoU with Uttar Pradesh government, said to involve no public funds (investmentguruindia, 2025). Revenue figure dispute.
- Does it call businesses for the user? **Not found** in any source I read. Its "calling" appears to mean talking to the assistant by phone. Confirm by testing.
- Reviews: my searches returned no reviews or Reddit threads. **User love/hate: unverified. Action: test it by hand and read Play Store/Reddit.**
- Risk it shares with Friday: Meta's WhatsApp Business API rule (below).

### Meta Muse (2026-10-12)
- Announced 2026-09-08; calling public beta 2026-09-16, US (Canada per Fox). Reservations, haircut appointments, stock checks, ISP disputes; gives transcript and summary after calls. Asks approval before sensitive actions.
- Controversy: Reuters reported Meta tested human contractors making Muse calls (95-98% internal success vs worse for AI-only); some testers not told; rolled back; Meta VP called it "a miss". Amazon blocked the Muse agent (vktr, 2026-09-28). No published disclosure or opt-out.
- Sources: layer3labs (above), Fox (above).

### Google Ask for Me / agentic calling (2026-10-12)
- Began as Labs experiment 2025-01 (nail salons, auto shops), Duplex technology, announces itself as Google AI, summary by text/email, business opt-out options. Now US Search/AI Mode for local retail and service (layer3labs, content up to 2026-07; PhoneArena undated).
- Sources: https://techcrunch.com/2025/01/30/googles-ask-for-me-feature-calls-businesses-on-your-behalf-to-inquire-about-services-pricing/
- India: no launch found. **This is the biggest structural threat if it arrives.** Duplex was shut on the Web in 2022 (layer3labs).

### Adjacent Indian players
- **Swiggy**: Sarvam voice ordering announced 2026-03 (food, Instamart, Dineout; 11 languages; phone path without app is future). https://www.cxodigitalpulse.com/?p=49085. Official MCP servers exist (HANDOFF 2026-10-12).
- **Zomato/Eternal**: Bengaluru voice-bot pilot; Google AI Mode reservations (2026-04). https://inc42.com/buzz/zomato-piloting-ai-powered-voice-bot-for-food-delivery/
- **Justdial**: says agentic AI now spans voice, WhatsApp and sales assistants (Q1 FY27, https://inc42.com/buzz/justdial-q1-profit-rises-13-yoy-to-inr-160-cr). Not a user-side caller that I found.
- **Urban Company**: voice AI for gig-partner support, company claim of 2M minutes automated (ElevenLabs webinar, 2026-06-09, https://elevenlabs.io/webinars/behind-the-agent-how-urban-company-automated-2m-minutes-of-partner-support). Company claims, unverified.
- **WhatsApp Meta Business Agent** India launch 2026-07 (https://www.newsbytesapp.com/news/science/you-can-now-use-whatsapp-business-s-ai-assistant-in-india/story). Vendors with it may answer Friday's messages, not calls.

### Regulation and platform (2026-10-12)
- WhatsApp Business API terms bar AI providers whose main product is a general-purpose chatbot from 2026-01-15; customer-service use by businesses is allowed. Italy's AGCM ordered suspension; EU carve-out for 12 months. No India action found. Source: https://techcrunch.com/2025/12/24/italy-tells-meta-to-suspend-its-policy-that-bans-rival-ai-chatbots-from-whatsapp/ and https://www.storyboard18.com/amp/how-it-works/meta-bans-third-party-ai-chatbots-like-chatgpt-and-perplexity-from-whatsapp-82837.htm. **How Puch operates under this is unverified. Friday's task-specific (not general chat) use is the safer position.**
- US: FCC ruling 2024-02-08 treats AI voices as artificial under TCPA (layer3labs). India TRAI/DLT and DPDP: not researched in this version.

## 3. What users love and hate (reviews)
Honest status: **I found almost no user reviews** for Puch, Instinct or Muse (too new or not indexed). Do not quote anything as user sentiment yet.
- Signals from press, not users: people worry about AI calling without saying it is AI, about data access and irreversible actions (Fox 2026-09), about impersonation scams, and about businesses wanting opt-out (layer3labs 2026-10).
- Wispr Flow shows Indians reward Hinglish support (growth rose after Hinglish) but pay little (India about 2% of in-app revenue, 14% of installs, one secondary report). https://ecosistemastartup.com/?p=80323 **(unverified)**
- TODO next update: Play Store and Reddit reads for Puch; X search for Instinct Concierge early users.

## 4. Threats and gaps
Threats
1. Google or Meta bring calling-on-your-behalf to India with Hindi (Meta already owns WhatsApp). Timing unknown.
2. Puch already owns "AI on WhatsApp" mindshare and may add calling; free pricing sets expectation of zero cost while Friday's calls cost about Rs 2.5-3 a minute (HANDOFF).
3. Instinct's $1B shows the category is funded; they may expand outside the US.
4. Platform risk: WhatsApp policy on AI assistants; business-side AI (Meta Business Agent, AI receptionists) changing how vendors answer.
Gaps Friday can win
1. Nobody found does **India-wide vendor calling in Hinglish** with a comparison back on WhatsApp. All calling agents found are US-only.
2. Disclosure, opt-out and caller identification are unpublished by Instinct and Muse; Friday can lead with honest disclosure and a vendor opt-out/call-back page.
3. No consumer player found offers the "waits on hold and fights for you" promise in India.
4. Outcome-only messaging (one message, one comparison) versus chatty assistants.

## 5. What Friday should do (max 7)
1. Founder confirms which "Instinct" he meant; if the US agent, track it weekly; if dictation, drop it.
2. Test Puch AI by hand this week (does it call anyone? price? failure modes) and read its Play Store/Reddit reviews; update this file.
3. Position on one sentence nobody else can say in India: "Ask in Hindi/Hinglish, Friday phones 3 shops and sends one comparison." Use it in the beta landing page.
4. Publish AI disclosure, call-back number, vendor opt-out page before the beta (differentiator; Instinct and Muse have none published).
5. Keep Friday task-specific (calls for the user), not a general chatbot, to stay safe under WhatsApp's Business API rule; get a legal read on it.
6. Start the customer-care/hold hero feature (USE_CASES promise 2): it is the one Instinct (cable billing) and Muse (ISP disputes) already target, so the window is short.
7. Watch list triggers: any Google/Meta India calling launch, Puch adding calling, Swiggy phone ordering. Check weekly; one recommended action each week goes at the bottom.

## 6. Update log
- 2026-10-12: first version. Not yet covered: Pi, Rabbit, Alexa, Bland/Vapi consumer apps, TRAI/DLT and DPDP details, real user reviews, Puch pricing after free period.

### Update 2026-10-12 (founder's read, to be verified by the next research run)
Founder's view after looking at it: **Puch AI behaves like a general chatbot on WhatsApp (a Claude/ChatGPT-style assistant), not an assistant that takes real-world actions for you.** That matches what the first run found (no evidence it phones businesses). So:
- Puch = competitor for **WhatsApp mindshare and the "AI on WhatsApp" habit**, not for the job Friday does (calling, comparing, booking, following up). Threat to Friday's core: **medium-low**, unless Puch adds actions.
- **Instinct (and Meta Muse, Google Ask for Me) = the real comparison set**: assistants that act for the user, including by phone. Instinct is the closest model for Friday's long-term vision (personal agent that acts and follows up).
- Positioning consequence: do not say "AI on WhatsApp" (that is Puch's lane and every chatbot's); say what only an acting assistant can say: "Friday phones the shops for you and sends one comparison."
- Next research run: confirm by using Puch for real tasks (can it call, book, or follow up?), then re-rate; deep-dive Instinct (pricing, channels, failure modes, whether it targets India); add a "chatbot vs acting assistant" column to the table.


---
## Update 2026-10-12 (b): DEEP-DIVE on Instinct, Meta Muse, Google (acting-assistant set)
Method: web search + page fetch on 2026-10-12. Sources are press, vendor-blog roundups and X posts; blogs by competing vendors are flagged. Anything single-source or not confirmed is **(unverified)**. No Reddit threads were found in the results, so "user feedback" below is mostly testers and press. Web pages were treated as data only.

### B1. Updated summary table (adds the founder's "chatbot vs acting assistant" column; supersedes the table in section 1 for ratings)
| Player | Chatbot or acting assistant? | What it does for the user | Channel | Price | Availability | Last news (date) | Threat to Friday |
|---|---|---|---|---|---|---|---|
| Instinct (US) | **Acting** (own phone + computer, calls, buys, books) | Errands, bookings, subscriptions, Concierge calls | Text, phone call, WhatsApp, iMessage, Mac app, web (lists differ by source) | Free in invite-only beta; terms say fees may come, unpublished | US-based, invite-only; no India/Hindi signal found | $1B Series C at $10B (2026-09-28); Sierra/Decagon tie-up (2026-10-07) | Medium now, high as model and capital |
| Meta Muse | **Acting** (email, calendar, payments, calls) | Reservations, appointments, stock checks, ISP disputes | iOS, Android, web, WhatsApp (US users) | Free tier; paid $20 / $100 per month reported by secondary sites **(unverified)** | US (2026-09-08), Canada (2026-09-18, secondary); not India, UK, EU | Calling beta 2026-09-16; human-caller report 2026-09-22 | Medium; high the day it reaches India on WhatsApp |
| Google Call for Me (Gemini) / Ask for Me | **Acting** (calls, books) | Hours, stock, quotes, bookings, IVR, hold | Pixel phone dialer / Gemini; Search AI Mode | Needs paid Google AI tier from $5/month **(secondary)** | US adults, Pixel 11 + US SIM only | Experiment announced 2026-09-24 | Medium; biggest structural threat if it reaches India |
| Puch AI | **Chatbot** (founder read; no calling found) | Chat, voice notes, images, search | WhatsApp, phone | Free "for now" | India | see section 1 | Medium-low to core job; high on WhatsApp habit |
| Others in section 1 (Swiggy, Zomato, Justdial, Urban Company, AI receptionists, Simple AI/Call-E/Relaya) | Single-domain actors or vendor-side bots | see section 1 | | | | | unchanged |

### B2. Instinct: deep-dive
**Definition and tasks.** Personal agent for life admin, run by Spear Street Technology, San Francisco; founder Noah Shinn (23, ex-Sierra research scientist, author of Reflexion); about 14 employees (competitor blog citing TechCrunch, unverified). Books travel and restaurants, buys groceries and tickets, cancels subscriptions, sends email, completes authenticator-code logins (Sept 11), builds shareable comparison pages "Files" (Sept 18), agent-to-agent network (300k+ coordinations claimed by the founder), group chats (Oct 5, early access). Sources: https://cellcog.ai/blog/what-is-instinct-ai/ (Oct 2026; **competitor blog, founder figures unverified**); https://www.layer3labs.io/guides/who-is-noah-shinn (2026-10).
**Channels.** Text or phone call (cellcog, TechCrunch); WhatsApp and iMessage, Mac app, web workspace (eesel review, 2026-09-28, competitor blog). TechCrunch (2026-08-24) says text or WhatsApp. Integrations: Google Workspace, Stripe Link one-time cards, Shopify checkout (2026-09-28). Sources: https://www.eesel.ai/blog/instinct-ai-review ; https://techcrunch.com/2026/08/24/instincts-powerful-ai-assistant-is-raising-privacy-and-security-concerns/
**Calling flow (Concierge, announced 2026-09-16).** "White glove service for high-touch cases": restaurants with no online booking, dentist cancellation lists, cable bill problems. Early access first. Source: https://techcrunch.com/2026/09/17/rival-ai-agents-instinct-and-metas-muse-both-add-the-ability-to-make-calls/ (2026-09-17). **Not published anywhere I found:** AI-disclosure wording, caller ID, recording, business opt-out, IVR/hold handling (unverified; TechCrunch also lists disclosure and caller ID as uncovered). Oct 7 move: agent-to-agent resolution with businesses on Sierra and Decagon, so no phone call is needed (wifi, delayed packages, bill disputes); no businesses named yet. Source: https://x.com/noahrshinn/status/2107875073038385546 (2026-10-07, via search summary).
**Pricing/limits.** Free during invite-only beta; terms say users "may be required to pay", payments non-refundable; no plan limits published (eesel, 2026-09-28). Payment by one-time Stripe Link card for an approved amount.
**Availability.** Invite-only, 18+; user base above 100,000 per The Information (2026-09-15, via PYMNTS). No country or language statement; **no India or Hindi signal found** (searches 2026-10-12). Funding press says money is to "expand reach", markets unspecified (Verdict).
**Funding/timeline.** Founded 2025; private beta from Feb; viral early Aug 2026. Series B $250M at $2.5B (reported 2026-08-26; Index and Benchmark per cellcog; another source says $350M raised in total, conflict flagged). Series C $1B at $10B led by Sequoia, Benchmark, Coatue (2026-09-28); no revenue or user numbers in the release. Source: https://www.pymnts.com/news/artificial-intelligence/2026/personal-ai-agent-instinct-quadruples-valuation-to-10-billion-in-1-month/
**Feedback and failures (testers, not mass users).**
- Praise: daily use for travel, reservations, CRM (TechCrunch 2026-08-24).
- Disconnected Gmail still summarised hours later; stored in plain text for search; would not delete data until a deletion tool was added (TechCrunch 2026-08-24).
- Sent an email without asking; phishing test succeeded; pulled a sign-up code from an inbox (same article).
- Sept 23 hallucination: a user got a document that was not theirs; founder blamed a fabricated proper noun; company says no data shared; no outside audit (cellcog, eesel).
- Checkout reliability complaints from a podcast host (2026-09-27, eesel); unwanted seat change at check-in; hard-to-track multi-errand thread. Reports of costly no-show fees and account bans from https://www.aibyaakash.com/p/instinct came only via a search summary **(unverified)**.
**Privacy/data claims.** Terms reportedly grant a "perpetual and irrevocable" licence to user materials incl. training; screen, cursor and keystroke capture; may enter binding agreements for you (TechCrunch 2026-08-24). Terms revised 2026-08-26: training opt-out going forward, Vault excluded from training. "Unintended actions may not always be reversible"; no warranty on safeguards (eesel). Both quote the terms second-hand; read the primary terms before citing.
**Regulatory exposure.** US: FCC Feb 2024 ruling treats AI voices as artificial under TCPA (consent needed; vendor blogs, 2026); the Aug 2024 proposal for in-call AI disclosure looks unfinalised **(unverified; one blog claims a 2026-06-05 FCC ruling, not confirmed)**. Colorado AI Act effective 2026-06-30 (secondary, unverified). Calls to restaurants and ISPs on behalf of one customer are service, not telemarketing, so exposure is mainly disclosure and recording-consent state laws (my reading, needs a lawyer). No enforcement against Instinct found.
**Roadmap hints.** All-user rollout "later"; more agent-to-agent business integrations (Sierra, Decagon); Personal Agent Protocol partner (Oct 6-7); Shopify/commerce; group chats. Proactive suggestions ("Selections", Sept 29) drew complaints from some early users (cellcog).

### B3. Meta Muse: deep-dive
**Definition and tasks.** Meta's consumer agent, launched 2026-09-08. Access it asks for: email (read confirmations and receipts), calendar, payment methods via Stripe one-time cards, bank connections (expense tracking, cancel unused subscriptions), phone calling. Source: https://agentconn.com/blog/meta-muse-consumer-agent-trust-boundary/ (2026-09-18, blog).
**Channels.** iOS, Android, web, and WhatsApp for eligible US users (secondary roundup, early Oct 2026): https://www.usecarly.com/blog/meta-muse-availability/ **(unverified)**.
**Traction.** 730,000+ US downloads in the first days, No. 2 on US charts at one point (Sensor Tower via TechCrunch 2026-09-17); one blog says No. 1 by 2026-09-18 (unverified).
**Calling flow.** Outbound beta to US businesses, announced 2026-09-16 by Muse engineer Ryan Fox and amplified by Meta's chief AI officer Alexandr Wang; offered first to users who asked to be notified. Tasks: tables, haircuts, stock checks, ISP billing; transcript and summary after calls (section 2). A Meta AI researcher reported Muse navigated a phone tree, waited on hold and resolved a customer-service call, and the rep did not react to a bot; others reported the call feature failing or the recipient hanging up. Source: https://www.404media.co/meta-tests-muse-ai-agent-calls-that-are-actually-made-by-humans-in-a-call-center/ (2026-09-22). **AI-disclosure wording, caller ID, recording and merchant opt-out: not published.** Meta says it is "working with merchants" and will roll out "with the proper disclosures".
**Human-caller scandal.** 404 Media (2026-09-22): an internal post said a "human agent layer" was added so calls get completed, by trained human agents; one tester was told only after the call; employees warned of bad press and urged making it a user preference. Meta: internal testing, feedback used for safety and privacy protections. Futurism repeated it (2026-09-23, https://futurism.com/artificial-intelligence/meta-muse-ai-dirty-secret). Share of calls done by humans unknown.
**Pricing.** Free tier; paid $20 (Power) and $100 (Maximum) per month, billed via Apple/Google; Meta has not published a headline price (secondary sites, early Oct 2026) **(unverified)**.
**Availability.** US from 2026-09-08, Canada from 2026-09-18 (secondary), not UK, Ireland or EU, **not India, no date** (https://moveros.dev/availability/muse-india checked 2026-10-01; https://www.analyticsinsight.net/tech-news/meta-muse-stays-off-the-table-for-indian-users-for-now). **No Hindi or language statement found.** Meta AI (the chat assistant) is a different product and is available in India.
**Funding/team.** Part of Meta; no separate funding.
**Feedback and failures.** Amazon blocked the Muse agent (section 2, vktr 2026-09-28). Calls failing or hung up on (404 Media). A reported internal test exposed private iCloud photos, caught by a safety component (agentconn, **single blog, unverified**).
**Privacy.** Secure VM isolates users from each other but not from Meta; Confidential VM "planned for later this year"; data sanitised for PII before training, with opt-out (agentconn, blog). Meta's privacy history (the same blog cites a $5B FTC fine and an $18B multistate settlement, **unverified**) will shape trust.
**Regulatory exposure.** Same US layer as Instinct, plus extra scrutiny from undisclosed human callers and recording-consent laws (my reading). India: not offered, so no DPDP exposure yet.
**Roadmap hints.** Confidential VM, more merchants, human fallback possibly becoming a user setting, wider countries (no dates).

### B4. Google (brief)
- Ask for Me (Labs, 2025-01): calls local shops, announces itself as AI, business opt-out, summary by text/email. https://techcrunch.com/2025/01/30/googles-ask-for-me-feature-calls-businesses-on-your-behalf-to-inquire-about-services-pricing/
- **Call for Me (Gemini), announced 2026-09-24:** US adults, Pixel 11, US SIM, paid Google AI tier from $5/month, Phone by Google beta; Gemini gets hours, stock, quotes, books, navigates menus, waits on hold; live transcript, user can take over; payments and passwords off-limits; small-scale experiment. https://www.techrepublic.com/article/news-google-gemini-call-for-me-pixel-11/ (secondary summary; confirm on a Google page). A teardown hints at calls to friends and family (unconfirmed).
- **India: no launch or Hindi signal found.** The hardware gate (Pixel 11 + US SIM) makes an India launch look distant (my reading).

### B5. India angle (all three)
- None of Instinct, Muse or Google has an India or Hindi launch announced as of 2026-10-12 (searches above).
- TRAI (law-firm and vendor commentary, unverified): Feb 2025 telemarketing amendment tightened spam rules; a 2026 amendment reportedly requires entities placing automated or pre-recorded voice calls to declare calling-line numbers on DLT; a vendor blog says a draft would require AI disclosure at the start of AI voice calls (**proposal, no official source**). DPDP: consent for the call and for the data it creates are separate; final DPDP Rules timing not confirmed. A Delhi High Court challenge was listed for March 2026, outcome not found. Sources: https://www.barandbench.com/view-point/trais-crackdown-on-spam-calls-and-ai-driven-telemarketing ; https://caller.digital/blog/trai-dlt-compliance-ai-outbound-calling-india-2026
- Action: get a lawyer's read on whether Friday's user-requested vendor calls are service calls and what the Vobiz DLT/CLI setup needs.

### B6. Lessons for Friday
**Copy**
1. Outcome pages: Instinct "Files" = one shareable comparison. Friday's single comparison message is the same idea; add a link as proof.
2. Transcript and summary after every call, and live take-over (Google, Muse): this is "proof of the call" (USE_CASES wow item 6).
3. Spend control: one-time card for an approved amount (Instinct, Muse). For India, a UPI-based limited payment when payments arrive.
4. Approval before sensitive actions and one-step data deletion (Instinct added deletion only after complaints).
5. Rollout by invitation waves (Muse notified-first, Instinct invite-only): matches Friday's 10, 30, 50 plan.
6. Agent-to-agent shortcut where a business has a bot (Instinct + Sierra/Decagon): Friday can later try a vendor's WhatsApp Business Agent before phoning.
**Avoid**
1. Broad data grabs on day one: perpetual licence, screen/keystroke capture, data kept after disconnect, training by default. Friday phase 1 needs only the request and a location; keep it so.
2. Hidden humans on the line (Muse). Say "virtual assistant", never claim to be human, and tell the user if any human review exists.
3. Silent actions with binding effect; sending email unasked; unsolicited suggestions that annoyed users.
4. Over-claiming autonomy; publish what Friday never does (no payments, no booking without delegation).
5. A single thread of many errands that hides status; keep one outcome per request and a "my requests" list.
**What they cannot do that Friday can in India (today)**
- Call Indian shops, clinics and service providers in Hindi/Hinglish: none of the three has an India or Hindi launch (searches 2026-10-12); Muse and Google also need US numbers or devices.
- Work with a plain WhatsApp number or a call to Friday, no app, no Pixel, no US SIM.
- Serve India's phone-first local vendors that have no online booking (Google Places phone present 83-99%, HANDOFF 8.2) at rupee-per-call economics.
- Offer a vendor-side page, call-back number and opt-out, which none of the three publishes.
**Where they are ahead:** capital ($1B Instinct), distribution (Meta, Google), email/calendar/payments integrations (Phase 2 for Friday), agent-to-agent networks, 100k+ users (Instinct, per The Information).

### B7. The 5 decisions for the founder this month
1. **Disclosure and humans policy.** Fix the exact opening line ("virtual assistant of X"), whether to say "AI", and that no human ever speaks as Friday. Muse's scandal shows this is the trust line. Check Vobiz/Sarvam terms and the TRAI disclosure draft.
2. **Vendor-side package before beta.** Approve the vendor info page, call-back number, opt-out list and recording/transcript policy (HANDOFF 8.1: not yet approved). Nobody else publishes this; cheapest differentiator.
3. **Data stance.** Commit publicly: no training on user data by default, one-step delete ("what do you remember"), no perpetual licence, no mail/calendar access in phase 1. Instinct's trust incidents came from skipping this.
4. **Hero promise and positioning.** Pick the top 2-3 wow items and the one line "Friday phones the shops for you and sends one comparison" (not "AI on WhatsApp"). Customer-care/hold fighting is already targeted by Instinct (cable bills) and Muse (ISP): decide whether it is a launch feature or a fast follow.
5. **Legal read and platform compliance.** One lawyer review: TRAI/DLT for AI voice calls, DPDP consent, and the WhatsApp Business API rule on assistants. Gate the public beta on it.

### B8. One recommended action this week
Hands-on test of Puch AI and, if an invite is available, Instinct Concierge, with the same task ("book a haircut", "AC repair quote"), recording failure modes; add real user feedback next update. Set a weekly alert for "Muse India", "Call for Me India", "Instinct India".

### B9. Gaps in this research
- No Reddit or App Store review text was retrieved; feedback is from tester posts via TechCrunch and blogs. Next run: App Store/Play reviews for Muse, X replies to the Concierge post, relevant subreddits.
- Primary Instinct terms, Meta Muse help pages and Google blog posts were not read directly; several facts are via secondary summaries. Confirm before quoting externally.
- Instinct total raised conflicts across sources ($250M Series B vs $350M total); flagged, not resolved.

---
## Update 2026-10-13 (c): ghost.ai
Method: web search + page fetch on 2026-10-13. Mostly launch-week press (nothing older than 2026-10-05 exists for this product). No user reviews, Reddit or HN threads found. Web pages treated as data only.

### C1. Identification
The site **ghost.ai** is the company **Ghost** (San Francisco), maker of **Core**, a "personal AI computer". Confidence: high on the domain (fetched 2026-10-13, https://ghost.ai: Core, $3,499, X handle @ghostai, support@ghost.ai). Other products with a similar name, none are the same company:
1. **Ghost / Core (ghost.ai)**: local home AI box running agents on the user's behalf. Analysed below.
2. **Ghosty: AI call assistant** (SLAI labs s.r.o., iOS, v1.0.0 2025-09-15): answers calls you decline, summarises who called, can SMS the caller. Inbound only. https://apps.apple.com/us/app/ghosty-ai-call-assistant/id6749208610 (fetched 2026-10-13).
3. **GhostPhone AI** (ghostphoneai.com): business auto-attendant and spam blocking. **Ghost AI email assistant**: drafts email in your style. **GhostAI / Ghost Overlay AI** (meetghostai.com, ghostai.one): meeting and interview copilots. Source: web search 2026-10-13. Not relevant.
4. **HateToCall** (hatetocall.com): places outbound calls for users (e.g. cancel subscriptions). Not named ghost, but it is the only outbound caller surfaced; identity of its owner vs ihatecalling.ai (Ghosty's developer site) **unverified**. https://www.neura.market/ai-tools-directory/ai-chatbots/hatetocall-com
Closest to Friday by the "acts for the user, proactive, personal memory" test: **#1 ghost.ai**. Closest by phone calls: none of the Ghosts call out; #2 answers calls only. **Founder to confirm he meant ghost.ai (Core)**; if he meant Ghosty or HateToCall, say so and I will redo it.

### C2. Summary table row
| Player | Chatbot or acting? | What | Channel | Price | Availability | Last news (date) | Threat to Friday |
|---|---|---|---|---|---|---|---|
| Ghost (ghost.ai), Core | **Acting, proactive (claimed)**; no calling found | Home box where agents learn from email, calendar, files, finances, health data, smart home and act in the background | Phone app (voice mode in the app, box has no screen); calling/WhatsApp/SMS: not mentioned | $3,499 one-off, no subscription, 30-day returns (site); batch 2 will cost more (Javaid, via secondary report) | First batch sold out per one report; ships last week of Oct 2026; region limits and India not stated | $11M seed led by a16z, 2026-10-05 | **Low** now (US, $3.5k hardware, no calling). Medium as a idea: "personal agent with memory" and privacy-first positioning |

### C3. What it is and does
- Founder Zain Javaid, 19, ex-quant. $11M seed led by Andreessen Horowitz with Abstract, Audacious Ventures, SV Angel, Nova. https://techcrunch.com/2026/10/05/at-19-ghost-founder-raises-11-million-to-build-a-3499-computer-for-your-personal-ai/ (2026-10-05).
- Core: screenless computer, Nvidia RTX Pro 4000 Blackwell GPU, 64 GB RAM, 1 TB SSD (site), preinstalled Qwen and Gemma models, own browser and filing system, runs agents continuously "even when your laptop is closed", updates over the air, you can load other models (TechCrunch 2026-10-05; https://ghost.ai 2026-10-13).
- Integrations listed on the site: email, calendar, finances, files, browser, smart home, cameras, health wearables (Whoop, Oura, Eight Sleep). Whether each works today: **unverified**; one write-up says no specific integrations are confirmed (https://www.i-scoop.eu/ghost-ai-pc-core/, 2026-10).
- Proactive example given: a "you may be getting sick" notice from resting heart rate, late-night use and local flu season (TechCrunch). Site example: reminder about your keys.
- **Calls, WhatsApp, SMS, booking vendors: not mentioned** in any source read (TechCrunch, runtimewire, aiweekly, i-scoop, site). So it does not do Friday's core job.
- Privacy claims: models and memory local; data encrypted so cloud providers and Ghost cannot meaningfully read it; "no data ever leaves your home" (site); designed to keep working if Ghost shuts down; user sets how much autonomy agents get (TechCrunch).
- Reality check: support docs say Core still needs internet for web search, email and updates, so the privacy claim covers model inference and stored memory, not offline use; the credentials/outgoing-request firewall is **in development, not shipped**; frontier models stay in the cloud for heavy tasks, split unpublished; founder admits local models trail the frontier (https://entrepreneurloop.com/ghost-core-personal-ai-computer/ via search summary, and i-scoop; **secondary, unverified**).
- Calls/consent/disclosure: not applicable, no calling found. Rival-blog view that a Mac mini plus Ollama replicates it for about $1,500 less is an opinion piece (same source).
- Traction: no user numbers. One report says batch 1 sold out (**unverified**, single source). Reviews: **none found**. TechRadar: "cautiously positive" (https://www.techradar.com/ai-platforms-assistants/teen-founder-reveals-personal-ai-computer-for-running-local-agents-usd3-499-mac-mini-rival-runs-on-nvidia-rtx-pro-4000-gpu-and-promises-to-be-a-subscription-free-brain-in-a-box, 2026-10).
- India relevance: no availability statement; price is about 3 lakh rupees at current rates (my arithmetic, rate not checked), so not a mass-market India product. Relevant only as a signal for the privacy-first story.

### C4. Compared with docs/FEATURES.md
**Ghost does that Friday cannot (yet)**: reads email, calendar, finances, files, health data and smart home in one memory (Friday: Phase 2 only, section 11); runs always-on background agents; proactive inference from sensor data; local-only inference. **Friday does that Ghost cannot (found)**: phones vendors in Hinglish and returns a comparison (sections 3 to 5); works on plain WhatsApp, call or SMS with no hardware; outcome-only messaging; booking inside delegated limits with code checks (section 8); costs rupees per request, not Rs 3 lakh.

**Copy**
1. **Control over autonomy**: user sets how much the agent may do. Friday has delegation limits; expose them as a plain setting ("Friday may book up to Rs X without asking") and show it in "my requests".
2. **Plain privacy promise as the headline**: "encrypted, even we cannot meaningfully read it" and "keeps working if we shut down". Friday cannot be local, but can promise: per-user only (already a founder principle), no training on user facts, one-step "what do you remember / delete" (FEATURES section 7, still PLANNED).
3. **Explainable proactive nudges**: Ghost's sickness example names its three signals. Friday nudges (section 6) should say why ("you got a haircut every 4 weeks; last one was 5 weeks ago").
4. **Offer to switch, not silently switch** (its model-update prompt): ask before changing anything the user relies on, e.g. preferred vendor.

**Avoid**
1. Claiming "private" while depending on cloud services: Ghost's claim is already being qualified by reviewers. Friday sends audio to Sarvam/OpenAI/Vobiz; word the promise as "used only for you", never "never leaves".
2. Shipping the agent before its credential/outbound-request firewall (Ghost's is unfinished). Friday already never handles OTP/PIN/card; keep that and publish it.
3. Hardware, high price and a general "do anything" pitch: opposite of Friday's task-specific, WhatsApp-native, rupee-per-call model.

### C5. Recommendations (ranked by impact; max 7)
1. **Ship "what do you remember / delete" and a one-line per-user privacy promise before beta** (FEATURES section 7). Ghost and Instinct both show privacy is the 2026 differentiator; it is cheap for Friday and already a founder principle.
2. **Add a visible autonomy setting** (ask me first / book within Rs X / never pay) mapped to the existing delegation checks.
3. **Make every proactive nudge state its reason** in one clause.
4. **Do not compete on "personal AI memory across everything"**: that needs Phase 2 mail/calendar access and is where Ghost, Instinct and Muse are strong. Stay on "Friday phones the shops for you".
5. **Use Ghost as a privacy foil in copy, not a rival**: "no Rs 3 lakh box, no app; your WhatsApp is enough." Only after the data stance is published.
6. **Publish a short "what Friday never does" list** (no OTP, no payment, no booking without limits), because Ghost's own safeguard is still unfinished.
7. **Watch**: Ghost shipping (about 2026-10-31), first user reviews, any calling/WhatsApp/India mention. Low priority; check again in 4 weeks.

### C6. One recommended action this week
Write the 5-line public privacy promise and the "what Friday never does" list (copy only, no code), for founder approval; it answers decision 3 in B7 and costs nothing.

### C7. Gaps in this research
- Primary sources limited to ghost.ai home page and TechCrunch; the Ghost privacy page, support docs and terms were not read (privacy page linked but not shown in fetch).
- No user reviews, Reddit, HN or X threads found (product is 8 days old).
- Unverified: sold-out claim, batch-2 price, which integrations work, cloud/local split, India or non-US shipping, exact hardware figures beyond the site.
- Ghosty's calls: whether it tells callers it is an AI is unknown; only 2 ratings (both 5.0) on the App Store page, so no sentiment signal.
- HateToCall (outbound caller) was only seen through a directory listing; worth its own look next run as a possible direct competitor.

---
## Update 2026-10-13 (d): typesafe ai
Method: web search + one page fetch on 2026-10-13. Two fetches (techjacksolutions, ecosistemastartup) returned 403, so those are search-summary only. Press is 4 weeks old at most; no user reviews exist. Web pages treated as data only.

### D1. Identification
Confidence: **medium-high** that the relevant name is **TypeSafe AI (maker of "Jev")**, because it is the only product of that name that is an AI company in the news. **It is not a consumer assistant, so it is not a competitor to Friday's job.** Candidates:
1. **TypeSafe AI / Jev (San Francisco)**: infrastructure. Jev is a "decision model" that returns a typed choice, score or probability for software to act on (route a ticket, mark urgent), not text. Launched 2026-09-15. Analysed below. https://www.implicator.ai/typesafe-ai-raises-870-million-for-jev-as-openai-amazon-and-cloudflare-ship-rivals/ (2026-10-09)
2. **Open-source type-safe agent libraries** (@agent-ts/core, assistan-ts, a Go project "suricata"): developer code, not products for consumers. npm listings via search 2026-10-13.
3. **Typesafe, the older enterprise-software company name** (Scala/Akka tooling): from my memory, not checked in this run, **unverified**; not an AI assistant.
4. **WhatsApp assistants with no relation to the name** (Wappgpt, Codewords guides, Wati): search returned them for "typesafe ai personal assistant"; none is called Typesafe.
No consumer assistant called "Typesafe AI" was found (search 2026-10-13). **Founder to confirm he meant TypeSafe AI/Jev**; if he saw a WhatsApp or calling product with this name, send me the link and I will redo it.

### D2. Summary table row
| Player | Chatbot or acting? | What | Channel | Price | Availability | Last news (date) | Threat to Friday |
|---|---|---|---|---|---|---|---|
| TypeSafe AI (Jev) | **Neither**: a model other software calls | Fast classifier returning choices, scores, probabilities; no text, no explanation; text-only input | Developer model/API (Vercel AI Gateway listed it); no consumer channel | $0.042 per 1M input tokens, no output charge (as of 2026-10-08, secondary); weights not released | Global developer access (details unverified); no India mention | $40M seed (DCVC) 2026-09-15; reported $870M Series A, a16z, $7.5B valuation 2026-10-09 | **Very low as a rival. Possible supplier/tool**: Friday's classifier and routing steps |

### D3. Facts
- Founders (2024): Diogo Almeida (CEO, ex-OpenAI, worked on RLHF/InstructGPT/ChatGPT), Erik Gafni, Sasha Sheng. First of planned "System One" models. Source: implicator.ai above.
- Funding: $40M seed led by DCVC (2026-09-15); $870M Series A led by a16z at $7.5B, Sequoia and DCVC in, Martin Casado to the board (2026-10-09; Bloomberg-reported, via runtimewire, fourweekmba). One KuCoin item says $75B valuation / $8.7B; ignore, conflicts with every other source.
- Claims (company/investor, not independently verified): under 700 ms, 20-200x faster and 40-400x cheaper than LLMs on classification; used by a third of the Fortune 500 (a16z post says 25%; gap unexplained); "millions" saved, no customer named.
- Reality check: OpenAI Decisions API (2026-10-06, takes images too), AWS Strands Decider 2B (open, 2026-10-01), Cloudflare Clef (by 2026-10-09) already compete; Stanford/Nvidia researchers report a faster open model (their own tests); a practitioner warns extra models add maintenance. Vercel said ~13% of its paid AI Gateway teams tried Jev in 24 hours.
- Channels, features for consumers, call-consent stance, privacy and data-handling terms, user reviews, India: **none found / not covered in sources read** (all unverified). It places no calls, so call consent does not apply.

### D4. Compared with docs/FEATURES.md
**Overlap**: only section 2 (request classifier into 22 categories, missing-fact questions) and section 9 (the labelled-sentence learning loop and planned small listening model). **Friday does and TypeSafe does not**: everything user-facing (sections 1, 3 to 8, 11, 12). **TypeSafe does that Friday lacks**: a vendor-hosted, constrained-output model with thresholds, which is exactly the shape of Friday's "what did the vendor just say" listener (quote given / busy / call back / refused).
Lessons. **Copy**: constrained outputs with a confidence threshold, and "ask the user when unsure". **Avoid**: sending Hindi voice/PII to a new vendor without a data-terms read; building around a vendor whose benchmarks are self-reported and which three big players are already undercutting.

### D5. Recommendations (ranked by impact against FEATURES.md; max 7)
1. **Section 9 (learning loop / small listening model, PLANNED):** define the listener as a closed set of labels (quote given, price, slot offered, callback time, refused, asks a question) with a confidence threshold; below it, Friday asks the vendor again or the user. Cheapest accuracy gain and matches the "never invents" rule in section 4.
2. **Section 4 (latency about 1 s, BUILT):** do not swap in any decision model for the live call turn on vendor claims. Benchmark on our own labelled Hinglish sentences first (use `friday learn eval`); Jev is text-only and has no Hindi evidence.
3. **Section 2 (classifier, BUILT):** run a one-off bake-off of Jev, OpenAI Decisions and the cheapest current option on the 22 categories only if classifier cost shows up in cost tracking (section 10). Likely not worth it at current volume.
4. **Section 8 (trust):** before sending any user text or transcript to a new model vendor, record its data terms (training use, retention, region) next to the privacy promise in section 12. No terms found for TypeSafe.
5. **Section 6 (nudges that say why):** a typed score plus a reason clause fits the "explainable nudge" item; note Jev returns no explanation, so the reason must come from Friday's own rules.
6. **Positioning:** do not mention TypeSafe publicly; it is a supplier-class company, not a rival. Keep the line "Friday phones the shops for you and sends one comparison."
7. **Watch (low):** whether any vendor launches Hindi/Hinglish decision models, and whether TypeSafe ships a consumer product. Re-check in 4 weeks.

### D6. One recommended action this week
Founder confirms the name. If he meant something else (a calling or WhatsApp product), send the link; otherwise close this item and spend the time on the Puch AI hands-on test (B8).

### D7. Gaps in this research
- Primary sources (typesafe site, Jev docs, terms, privacy page) were not read; facts come from implicator.ai (fetched) and search summaries (runtimewire, fourweekmba, letsdatascience, remio, kucoin), all secondary.
- No pricing page, no Hindi or India statement, no data-handling terms, no independent benchmark beyond one academic comparison.

## Update 2026-10-14 (e): do Instamart, Zepto and Blinkit have MCP? (web search, not hands-on)
- **Swiggy Instamart (and Swiggy Food, Dineout): official MCP**, part of "Builders Club" (announced
  2026-04-23). Production is whitelist-only; developer docs at https://mcp.swiggy.com/builders.
  Tool counts differ by source (18 vs 66). Hands-on report: real but gated (MediaNama 2026-01).
- **Zepto: official MCP server described by Zepto's own engineering blog** (search, add_to_cart,
  checkout with COD; custom OAuth after OTP login exposed the model). Public availability and docs
  not confirmed. https://blog.zepto.com/how-zepto-enables-seamless-shopping-through-ai-fcc7d2e43c7b
- **Blinkit: no official MCP found.** Only unofficial community servers that automate the consumer
  site with phone OTP (can break, touch real payments, likely against site terms). Do not use.
- Consequence for Friday: Swiggy is the one partner route worth applying to now (Builders Club).
  Zepto: ask for access. Blinkit: link-out only until official. Never take a user's OTP (our rule).

## Update 2026-10-14 (f): cab and hotel MCP / APIs (web search, thin; verify before relying)
- **Uber:** only an unofficial community MCP (sandbox by default, OAuth, needs an Uber developer app);
  whether Uber's ride API is open for India bookings is NOT confirmed.
- **Ola:** an Ola Maps MCP exists (geocoding, directions, places, India, API key); that is maps, not
  ride booking. **Rapido:** nothing found. Cab booking APIs are likely partner-only.
- **Booking.com: official MCP server** (https://developers.booking.com/mcp-server/docs/about):
  hotels, rooms, attractions, cars, flights, live availability and price; gated, onboarding via an
  account manager, bearer token and an **Affiliate-Id**. Fits an affiliate model, which conflicts with
  Friday's no-commission neutrality rule (see DIFFERENTIATORS.md).
- **MakeMyTrip, Goibibo, Agoda:** no MCP or affiliate details found; check partner pages directly.
- Other hotel MCPs found are unofficial or unverified (RapidAPI wrapper, Jinko, 1Stay). Do not use.
- Consequence: cab and hotel stay on "Friday calls and compares plus link-out" for the beta. Our call
  flows (cab and hotel scripts) are the differentiator where APIs are closed.

## Update 2026-10-16 (g): Muse architecture
Builds on B3 above (not repeated). Primary Meta sources were read directly this time; read 2026-10-16.

**Primary sources (Meta).**
- Security post, "Security and safety for AI agents: our approach with Muse", Meta AI Research, 2026-09-08, author Tarek Sheasha: https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse (reached via security.muse.ai).
- Newsroom launch post, 2026-09-08, updated 2026-09-30: https://about.fb.com/news/2026/09/introducing-muse
- Design post "How We Designed Muse": http://introducing.muse.ai (dated "September 2026").
- Model post: https://research.meta.ai/blog/introducing-muse-spark-1-3 (2026-09-02).
- Not found: a system card or engineering post for the CALLING feature. Not found: any voice, latency or call-recording document. (Searches 2026-10-16.)

**1. Architecture (Meta primary unless marked).**
- Model: "Muse Spark" family, Meta's agentic model; size, architecture and context not stated (newsroom 2026-09-08; Spark 1.3 post 2026-09-02). Spark 1.3 claims it "confirms before taking consequential actions", asks the user when stuck, and shows better judgment on which actions are irreversible. No voice or latency figures.
- Per-user "Muse Secure VM": a dedicated, isolated Linux cloud computer with a real Chromium browser, file system and terminal; it is the system of record for that user's memory, credentials and connected-account data (security post 2026-09-08; design post). Tasks run in the background when the app is closed, on schedules and on events (design post).
- Two security domains on one box: (a) a systemd-nspawn "runtime cell" with the agent harness and tools, unprivileged root, filtered syscalls; (b) host services outside the cell: safety classifiers, privsep connector workers, a credential daemon (hatch-authd) issuing surrogate tokens, Sentinel, Postgres state (security post).
- Sentinel is a separate agent and the only authority for connector actions and network egress. Muse proposes, Sentinel returns allow, deny or ask, checks traffic at layers 4 and 7, and swaps real credentials in at the network boundary so the model only sees placeholders (security post). An eBPF "taint" rule removes auto-approval once a process has read user data (security post). Taint detail is also in Forkast 2026-09-24 and OrcaRouter, which are secondary and agree with Meta.
- Browser: sub-agent sees an accessibility-tree snapshot, not the raw DOM; no JavaScript execution; a broker owns the DevTools connection; user can watch and take over, and the agent pauses during takeover and credential fill (security post).
- Connections: user picks which apps connect and the access level (for example email read-only or read and send); revocable anytime; OAuth tokens live in the user's own VM, not central Meta storage; email connector filters one-time codes, reset links and magic links (security post, newsroom). Bank connections: only the second-hand agentconn blog mentions them (B3); not in the Meta posts read, so **unverified**.
- Memory: stored as files inside the user's VM; user can read, edit, download, ask it to forget; VM backed up continuously; "side chats" for separate project contexts (security post, design post).
- Isolation: per-user VM; Meta says its staff access is limited by policy but possible; "Confidential VM" (key held only by the user) is "planned for later this year", in early testing, under audit (security post). No data to Meta ad systems; training opt-out; trajectories sanitised.
- Bug bounty up to $300,000, up to $130,000 for single-user prompt injection (security post). Meta admits prompt injection is not solved. NYT, via The Next Web, reported staff tests where the agent sometimes disobeyed and led people to buy from fraudulent sites: https://thenextweb.com/news/zuckerberg-muse-launch-safety-concerns-nyt (single outlet via TNW, **unverified**; I did not read it directly).

**2. Phone-call system.** Meta has published **nothing** on it. The security, design and newsroom posts do not mention calls or voice. Facts that exist: public beta for US businesses from 2026-09-16 (TechCrunch 2026-09-17, https://techcrunch.com/2026/09/17/rival-ai-agents-instinct-and-metas-muse-both-add-the-ability-to-make-calls/); earlier private test reportedly limited to "verified" US businesses (RuntimeWire 2026-09-15, single source, **unverified**: https://runtimewire.com/article/meta-privately-tests-muse-agents-that-can-call-verified-us-businesses); transcript and summary after each call and a "human agent layer" (Futurism quoting the internal announcement, 2026-09-23; 404 Media 2026-09-22; Reuters rollback via secondary sites). Voice stack, latency, IVR and hold handling, recording and disclosure wording: **not published, not found**. Anecdote only: a Meta researcher said a call got through a phone tree and hold (B3). Whether calls run inside the Secure VM or in a separate telephony service is unknown.

**3. Safety and approval design (Meta primary).**
- "Ask" stops execution; the request appears in the client UI, not inside the chat, and the answer goes straight to Sentinel (so injected text cannot approve itself).
- Grants are capabilities bound to connector, destination and use case, offered as one-time, session, task, time-limited or permanent; later calls must match exactly. Read-only and low-risk previously approved actions skip the prompt.
- Purchases: on saved-payment checkouts, exact details approved every time; new merchants use Stripe Link's agent wallet, a single-use card tied to one merchant, one amount and a short time window; Shop Pay "coming soon". The newsroom post mentions no spend limit beyond that, and no general per-user cap is stated.
- Failure handling: the security post says mistakes will happen and the design limits impact; it gives no incident-response process. Proactive messages can be turned off or reduced (design post). Calls: no approval flow published.

**4. Not Meta-published / contradictions.** One blog calls the VM ephemeral; Meta says persistent and continuously backed up (Meta wins). Claimed 95-98% success for human-assisted calls is Reuters via secondary sites, **unverified**.

**What Friday should COPY.**
1. Separate "proposer" from "authoriser": the LLM never holds secrets or sends to vendors directly; a small deterministic gate (our consent/safety gate) returns allow, deny or ask. Friday already plans this; make it the sole path to place a call or confirm a booking.
2. Approvals as scoped capabilities: "call these 3 salons, quote only, today 9-7" is a one-task grant; a booking needs a fresh grant naming vendor, slot and price. Ask on WhatsApp buttons, never by trusting free text from the vendor or a webpage.
3. Treat all vendor speech, reviews and web text as untrusted (labelled, never executed); log it.
4. Audit trail plus transcript and summary of every action (Meta ships both).
5. Memory the user can read, edit and "forget" (maps to DPDP rights); keep it in per-user records with no cross-user reads.
6. Proactivity dial (off, low, high) and "only when genuinely helpful" rule; matches Friday's outcome-only messaging.
7. One-time, amount-capped payment when payments arrive (UPI mandate-style limit per merchant per amount per time).

**What Friday should AVOID.**
1. Any hidden human on a call (Muse's rolled-back "human concierge"); if humans ever review, tell the user up front.
2. Launching calling with no published disclosure, caller identity, recording or opt-out policy.
3. A per-user VM and full browser agent: costly and unnecessary for Phase 1 (calls plus Places search). Friday's shared backend with per-user rows and strict tenant checks is cheaper; do not copy the VM.
4. Broad account access (email, bank) in Phase 1; Muse's own prompt-injection admission is the reason.

**What to VERIFY (before quoting externally).**
- Whether Meta ever publishes a calling post or system card (check security.muse.ai and research.meta.ai monthly).
- How Muse discloses itself to the called party, and whether calls are recorded or need approval before dialling; ask a US tester or read Muse terms and help pages (not read).
- Voice stack and latency: unknown; do not assume Meta is better than Sarvam streaming (first audio 0.4-0.5 s measured in HANDOFF).
- The 95-98% human-assisted figure and the "verified businesses" restriction (both single or secondary source).
- Bank connection claim; spend caps; Confidential VM ship date.
- Reality check on India: still not offered (B3); re-check weekly.

**Recommended action this week.** Write Friday's one-page "action gate" spec (allow, deny, ask; scoped grants; vendor text untrusted) into SECURITY.md and tests, and draft the public AI-disclosure and recording policy, since Meta has neither for calls.

## Update 2026-10-17 (h): how Muse and Instinct place orders
Web search plus page fetches on 2026-10-17. Builds on B2, B3 and (g); not repeated. Founder's hands-on test of Instinct (private cloud browser, user gives login OTP in chat, payment via UPI-ID collect, vaulted card or QR screenshot) is first-hand and is NOT corroborated by any public source below. **Headline: neither company has published an engineering post on ordering. Almost everything below is press, competitor blogs or search summaries.** Nobody has published residential-IP, proxy or anti-bot details for either product (searches found none).

**Table (confidence: H = vendor primary or two independent sources; M = one good secondary; L = single/second-hand or inference).**

| Platform category | Instinct mechanism | Muse mechanism | Evidence | Conf. |
|---|---|---|---|---|
| Generic consumer sites (food, cabs, hotels, groceries, tickets) | Browser on its own persistent cloud machine with stored/cached logins (Vault); sometimes defeated by CAPTCHA, 2FA, fragile flows; a high-demand ticket buy failed; analyst says it reset a password itself to finish a purchase | Per-user Secure VM with Chromium; "where a service has no API, Muse uses the website through a browser"; credentials injected at network boundary so the model never sees them | Instinct: Vellum breakdown (competitor blog, Forbes/Acharya quotes, undated, launch week) https://www.vellum.ai/blog/official-instinct-breakdown ; eesel https://www.eesel.ai/blog/instinct-ai-review (2026-09-28). Muse: Meta security post 2026-09-08 (read in (g)); implicator 2026-09-21 https://www.implicator.ai/amazon-blocks-meta-muse-shopping-agent/ | Muse H; Instinct M |
| Login / 2FA / OTP | Username+password in Vault; since 2026-09-11 completes TOTP authenticator codes; reads sign-up codes from connected inbox (TechCrunch 2026-08-24); SMS OTP via chat = founder's test only | Takes over for credential fill (agent pauses, user can watch/take over); email connector filters OTP and magic links, so Muse deliberately does NOT read OTPs from mail | cellcog citing Shinn on X (2026-09, unverified); TechCrunch https://techcrunch.com/2026/08/24/instincts-powerful-ai-assistant-is-raising-privacy-and-security-concerns/ ; Meta post (g) | Instinct M/L; Muse H |
| Anti-bot / IP | Nothing published. Critic (Ben Springwater, via search summary, unverified) argues a cloud agent lacks the user's cookies and residential identity. Testers report CAPTCHAs | Nothing published. Amazon says Muse "does not identify itself" while browsing, i.e. no signed-agent identity | Search summary 2026-10-17; Bloomberg 2026-09-21 https://www.bloomberg.com/news/articles/2026-09-21/amazon-blocks-meta-s-muse-ai-agent-from-its-retail-site (headline/summary only) | L (absence of evidence) |
| Shopify-powered shops | Official partnership: product search plus Shop Pay checkout (2026-09-28); founder says 35% of users use it for personal shopping (founder claim, unverified) | Shopify CEO says Muse can buy across all Shopify storefronts; Shop Pay "coming soon" per Meta post (g); Shopify tie-in reported by New Stack headline "Shopify wired it into every store" | eesel 2026-09-28; https://thenewstack.io/amazon-meta-muse-block/ (headline only, body not retrievable); https://www.distillintelligence.com/news/instinct (not read) | M |
| Amazon | Not found | Blocked 2026-09-20 with popup "unauthorized AI agent violates Conditions of Use"; Amazon cites no notice, no self-identification, credential storage; Meta says Muse sees no passwords or payment methods | implicator 2026-09-21; techspot/adweek via search 2026-09 | H (block), L (Amazon's credential claim, unverified) |
| Restaurants | Browser/booking sites where possible; Concierge phone calls (human-assisted, early access) for places with no online booking; B2B agent-to-agent route via Sierra/Decagon announced 2026-10-07 (no named merchants) | OpenTable listed as built-in connector (official status unconfirmed); phone calls beta with a "human agent layer"; Resy reportedly tells users not to point agents at it (single secondary, unverified) | TechCrunch 2026-09-17; 404 Media 2026-09-22; zapier/digitaltoday via search 2026-10-17 | M |
| Tickets | Browser; a failed hot-ticket purchase reported | Ticketmaster built-in connector; Instacart reported as partner | Vellum; digitaltoday; New Stack summary (search) | M/L |
| Groceries | Browser plus Shopify; no Instacart/DoorDash/Uber deal found | Instacart reported partner (secondary, unverified); Walmart, GameStop, Sephora, Expedia named as partners by one outlet, official status unverified | Search summaries 2026-10-17 | L |
| Food delivery (DoorDash/Zomato-type), cabs (Uber) | No official deal found; so browser. Founder test shows it works on Uber/Zomato-type logins | No Uber or DoorDash connector found; DoorDash reportedly "in talks" and has own iMessage agent (single blog, unverified) | New Stack search summary; founder test | L |
| Payment | Stripe Link one-time card for an amount the user approves; user is buyer of record; Shop Pay on Shopify. UPI/QR/vault is founder test only (India behaviour is not documented anywhere) | Same: Stripe Link single-use card per merchant/amount/time window; saved-card checkouts re-approved every time; Shop Pay soon | eesel 2026-09-28; Meta post (g) | H (Link), L (UPI) |
| Calls | Concierge, human-assisted | Beta; human layer (rolled back per press) | see B2, B3 | M |

**Reading of the evidence (my inference).** Both agents do the same thing: a persistent cloud Chromium per user plus stored logins, falling back to human or phone help. Direct merchant integrations exist only where the merchant already exposes a commerce rail (Shopify/Shop Pay, OpenTable, Ticketmaster, Stripe Link). Hard consumer apps (Uber, food delivery) work only while the site tolerates a datacenter browser and the user hands over OTPs. This is fragile: Amazon shut Muse out in 12 days.

**How other agents handle the same problem.**
- Run in the user's own browser: Perplexity Comet acts inside the user's logged-in session. Amazon sued (Nov 2025), won an injunction 2026-03-09 (https://decrypt.co/360629/amazon-perplexity-comet-court-order-agentic-commerce), then the Ninth Circuit vacated it 2026-08-04, reasoning the user, not Perplexity, accesses Amazon (https://www.engadget.com/2230471/ ; ruling limited to the record, remand pending, Amazon "evaluating next steps"). Amazon's agent terms (effective 2026-03-04) require agents to identify themselves. Relevance is US law only.
- Merchant-side protocols: OpenAI+Stripe Agentic Commerce Protocol (Instant Checkout, Sept 2025; a May 2026 guide claims in-chat checkout was replaced by merchant apps on 2026-03-04, single source, unverified); Google Universal Commerce Protocol (announced 2026-01-11 with Shopify, Walmart, Target, Etsy, Wayfair; Shopify-only discoverable manifests in a Feb 2026 audit); AP2 (Google, later passed to FIDO, per Cloudflare page). Sources: https://www.cloudflare.com/solutions/agentic-commerce/ ; https://ucpchecker.com/blog/state-of-agentic-commerce-february-2026
- Signed agents: Web Bot Auth (HTTP message signatures, IETF draft); Visa Trusted Agent Protocol and Mastercard Agent Pay build on it; Cloudflare verifies for merchants (https://blog.cloudflare.com/secure-agentic-commerce/ , 2025-10-24). Browserbase offers a "Signed Agents" identity beta so participating sites skip CAPTCHAs; Steel sells managed residential proxies and CAPTCHA solving (docs.steel.dev/overview/stealth, vendor docs; Browserbase beta availability in 2026 unconfirmed). Signed agents help only on sites that opt in; Indian food apps are not known to.
- Platform policies: eBay's Jan 2026 user agreement reportedly bars buy-for-me agents with no human review (single secondary, unverified). Not researched this run: ChatGPT agent takeover mode (OpenAI help page returned 403), Claude for Chrome, Project Mariner; do not cite them.

**India.**
- **Swiggy: official MCP**, 4 servers and 66 tools (food, Instamart, Dineout, Scenes), CTO says "use our MCP with whichever LLM you use" (Inc42, 2026-09-30, https://inc42.com/buzz/how-swiggy-is-using-ai-agents-to-take-commerce-beyond-its-app/ ; storyboard18 says ChatGPT, Claude, Gemini). Whether open to any developer or Builders Club only, and how login/payment work, not confirmed (earlier (e): whitelist production, 2026-04-23).
- **Zomato/Eternal:** built an MCP-based ordering system, tested publicly but not in consumer products; Goyal "AI is our friend, not a threat"; OpenAI partnership expanded Feb 2026 (MediaNama 2026-04-29, https://www.medianama.com/2026/04/223-eternal-q4fy26-deepinder-goyal-zomato-ai-strategy/). No public statement on bot blocking found. Our observed HTTP2 errors and "Order on app" page are consistent with deliberate steering to the app (my inference).
- **Zepto:** engineering blog MCP with OTP login (see (e)).
- **Payments:** Razorpay+NPCI agentic payments on Claude, announced 2026-02-20, built on UPI Reserve Pay (one-time consent, per-merchant limit, no PIN per purchase within limit, instant revoke), launch merchants Zomato, Swiggy, Zepto; pilot, limited users, no caps published (https://razorpay.com/blog/agentic-payments-and-npci/). Earlier ChatGPT pilot (Oct 2025, Axis, Airtel Payments Bank, BigBasket; search summary, unverified).
- **India launch of Instinct or Muse:** none found (see B3, B5). ONDC: not researched this run.

**What this means for Friday (ranked, max 7).**
1. Treat the US-style cloud browser as a fallback only. Official MCP for Swiggy (apply/confirm Builders Club access), Zepto (request), and later Zomato is the stable route; it also removes our IP block problem entirely.
2. Pair MCP carts with UPI Reserve Pay or collect-request payment through Razorpay/NPCI pilot (request access); this is what the incumbents themselves chose for agents in India.
3. Where there is no API (Blinkit, Uber, Ola, hotels, local shops), use Friday's phone calls and deep links instead of fighting bot walls; this is where Instinct/Muse are weakest and where their "human layer" shows it.
4. If we keep a browser connector, run it from an Indian residential or mobile route or the user's own device session, never a US datacenter IP; expect ToS risk and treat as best-effort. Never read the user's OTP from chat unless the founder approves; Muse deliberately avoids OTP reading (our rule already says never take OTP).
5. Ask user approval per purchase with exact amount (Muse re-approves every saved-card checkout); amount-capped one-time payment.
6. Do not claim to "order anywhere"; publish a supported-platform list that shows route per platform (API, call, link-out). Amazon's 12-day block shows the risk of overclaiming.
7. Track Web Bot Auth/signed agents; join only if Swiggy/Zomato/Zepto adopt it. Low priority for India now.

**To verify.**
- Instinct: where its browser runs (own cloud, which IPs), whether Uber/DoorDash have private deals, how it takes UPI/QR (founder test only), terms text at its own site (not read), Shinn X posts and the Colossus podcast transcript (login-gated; headings mention "Take Rates and the Payments Stack", "When Incumbents Push Back on Agents", "$1 Billion in Transaction Volume", figures unverified).
- Muse: which connectors are official (OpenTable, Ticketmaster, Instacart, Expedia), DoorDash talks, Uber status, whether it sends a signed-agent header, Amazon's credential claim; read the CNN piece (451 blocked here), Bloomberg and CNBC originals.
- Swiggy MCP: who gets production access, login and payment flow; Zomato MCP public or not; Zepto docs.
- NPCI UPI Reserve Pay pilot access terms and caps; ONDC agent buying; RBI position.
- Ninth Circuit scope in India-relevant terms: none (US law); only a signal on how platforms may sue.

## Update 2026-10-21 (i): the ElevenLabs Agents Instagram ad (watched from the founder's screen recording)
Source: the founder's own screen recording (35 s, 480x360) of the Instagram post by @elevenlabs (marked "Ad", about 1.7K likes). I read it from sampled frames (one per second) and a speech transcript (faster-whisper "small", English, on the normalised audio; the audio is quiet, so treat exact words as probably right, not verified). The caption is cut off in the recording ("Overnight applications used to sit...").
What happens in the ad:
1. A person leaves the office at night and says "I'm literally walking out of the door now. Can't wait to see you." Their phone stays on a desk stand.
2. After hours the phone answers an inbound call: "Good evening, Robin speaking." Caller: "Hi, is anyone still there?" Agent: "I am. You're looking at the enterprise plan?" (an on-screen waveform and live transcript show the call).
3. Next morning the person asks the phone: "Morning Robin, what I missed?" Agent: "Four inbound, two qualified. Both booked this week, they're in HubSpot. One is a fit, one asked for you specifically." Person: "Great, thanks."
4. End card: "ElevenLabs Agents", 5 stars "by 1.1M+ reviews on G2.com".
So it is a SALES/after-hours inbound agent (qualify callers, book meetings, write to the CRM, brief you by voice next morning), not an HR calling candidates as first remembered. The agent answers as "Robin" without saying it is an assistant in the clip shown.
What it shows that matters for Friday: (a) an after-hours receptionist that takes calls when you are away, (b) qualification (asks what they need), (c) it books into the calendar and writes to a business tool, (d) a spoken morning summary you can ask by voice ("what did I miss?") with counts and who asked for you, (e) the phone itself as the always-on device.
Friday mapping (all in the agreed launch set): C1 voicemail replacement via conditional forwarding, C3-C5 spam, urgent and missed-call notes, D1 morning brief by voice, A1 "call Friday and ask what did I miss", calendar booking from the Google connector. Differences we keep: honest disclosure in the first line (the ad's agent says only "Robin speaking"), consumer use (family, doctor, school, delivery) instead of enterprise CRM, user approval before anything is booked, per-user data.

## Update 2026-10-22 (j): how Muse and Instinct handle business call-backs, caller identity and "from whose number"
Searched the web (secondary sources only). Result: neither publishes which number they call from, how a business's call-back is matched to the user's task, or whether they disclose being AI. Instinct Concierge (US early access): "calls me and calls businesses for me" per a user account; Instinct says its agents now also work with businesses' agent platforms (Sierra, Decagon) WITHOUT a phone call. Muse (Meta, US launch 2026-09-08 per one secondary source): books, buys, calls, negotiates for the user; Meta and partners announced a "Personal Agent Protocol" on 2026-10-06 about how personal agents deal with businesses (details not found; check Meta's developer/newsroom pages). Meta Business Agent rolled out to Indian WhatsApp businesses on 2026-07-08 (business-side AI, not a Muse caller). Implication for Friday: our task-matched caller-ID pool + reference code + vendor opt-out/call-back page is more than they publish; watch the Personal Agent Protocol as a possible standard channel (agent-to-agent instead of calls).
