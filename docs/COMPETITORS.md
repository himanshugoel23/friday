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
