# WhatsApp Business API providers: research for Friday (2026-10-28)

Author: PM research agent. Public repo: no keys, no personal data, no phone numbers.
**Method and limits (read first):** every direct page fetch (vendor sites, Meta docs, whatsapp.com legal) FAILED with a DNS
error in this environment on 2026-10-28. All facts below come from web-search result summaries (search date 2026-10-28), mostly
third-party blogs. Nothing here was read from a vendor or Meta page directly. Treat every number as a lead to confirm, not a quote.
"(unverified)" = vendor-page-only, single-source or conflicting. Company-name check: "Heltar" and "AiSensy" are real WhatsApp API
companies in India (see below); I found no other company those names could mean. Confirm with the founder that these are the two he meant.

## 1. Summary (10 lines)
1. Heltar (Delhi, founded 2022, pre-seed) and AiSensy (larger, Meta-listed partner programs) both sell a dashboard on top of Meta's WhatsApp API. Neither is shown to be a Meta-listed BSP by any source I could read; ask for proof (Meta Partner Directory).
2. Neither provider's public material says what happens to a customer with a restricted personal Facebook account. No information found. This is the #1 question to ask.
3. Most providers use "Embedded Signup": the WABA is created inside the customer's OWN Meta business portfolio, and the person doing the signup logs in with their own Facebook account. So the same personal-login block can recur at the provider's popup. Provider-hosted WABAs (provider's own portfolio) exist at some BSPs; ask.
4. Pricing: Meta's per-message charge is passed through plus a provider layer (monthly plan and/or markup). Third-party figures for India: marketing about INR 0.8631, utility/auth/service about INR 0.115 per message before GST (several sources agree; not read from Meta).
5. Meta changed pricing: per-message billing from 2025-07-01; INR billing from 2026-01-01; from 2026-10-01 service-window replies and in-window utility templates become billable (sources disagree on the free allowance). Friday's chat is mostly in-window, so this matters.
6. Meta's AI Providers rule (effective 2026-01-15) bars general-purpose AI assistants as the primary function; business task bots (bookings, support) are described as fine. Friday is a grey area. Lawyer question.
7. Proprietary vs Cloud-API-format: not found for Heltar or AiSensy. 360dialog and Twilio-type providers are the ones known to proxy Meta formats; verify per provider.
8. Calling API: Meta docs (via search summary) say business-initiated calling is available wherever Cloud API is, except USA and Canada, India not excluded; support by Heltar/AiSensy unverified.
9. Do NOT create or borrow another person's or extra Facebook account to evade the restriction (Meta anti-circumvention). Fix the block via Meta appeal/support or a legitimate business owner.
10. Recommendation: first, an appeal to Meta plus a written question to each provider about restricted accounts; in parallel trial a provider whose signup does not need the founder's personal login (provider-hosted WABA), if one is willing in writing.

## 2. Comparison table
| Option | What | Price (INR, mostly unverified) | Restricted-account handling | API format | Notes |
|---|---|---|---|---|---|
| Heltar | Delhi BSP-style SaaS: API, inbox, broadcast, chatbot | Sources conflict: from INR 499/mo; INR 0/2,099/4,999/9,999/mo tiers; USD 50/80/150 tiers with 10/8/5% Meta markup; flat 5% markup; "no premium". All old (400-630 days). | None found | None found | Meta partner status unverified (CB Insights only) |
| AiSensy | Large India WhatsApp marketing + inbox + chatbot platform; runs partner programs (whitelabel, direct API) | Basic INR 1,500, Pro INR 3,200 per month + GST (third-party); own page says no charge to procure the API; markup study +26.3% on marketing (competitor source) | None found | None found | Has "partner" FAQ on embedded signup troubleshooting |
| Gupshup | Large BSP, API-first | Per-message fee on top of Meta (about INR 0.085 claimed) (unverified) | Ask | Proprietary plus Meta-style (unverified) | Docs mention migrating WABAs without OTP |
| Interakt | Shopify/SMB inbox and broadcast | About INR 999-2,499/mo + markup (unverified) | Ask | Proprietary (unverified) | Ownership not checked |
| Wati | Inbox and chatbot SMB | About INR 2,499-7,999/mo + markup + seats (unverified) | Has a public embedded-signup troubleshooting page | Proprietary (unverified) | Per-seat caps |
| Twilio | Global CPaaS | USD, per-message fee on top of Meta; exact fee not verified | Ask | Twilio's own API, not Meta's payloads | No monthly minimum (one source) |
| 360dialog | Hub-style Meta passthrough | Not verified | Docs cover "business account locked" | Documented as Cloud-API-style (unverified) | Documents number migration |
| Meta Cloud API direct | Current setup | No platform fee; Meta per-message only | Blocked at onboarding now | Native | Needs unblocked business owner |
| Telegram / SMS | Fallbacks | Telegram Bot API believed free (unverified, search found nothing); SMS needs DLT | n/a | Own APIs | Not a WhatsApp substitute |

## 3. Per-provider notes
### Heltar (heltar.com; fetch failed)
- What: Delhi-based, founded 2022, pre-seed, last reported raise USD 120K on 2024-09-20, investors Antler and gradCapital. Source: CB Insights search summary, retrieved 2026-10-28 (profile partly unclaimed, so low reliability). https://www.cbinsights.com/company/heltar
- Meta status: CB Insights calls it a Business Solution Provider "affiliated with Meta". No Meta-published listing found. (unverified)
- Products and prices: Heltar's own blog posts (2024-2025) mention starting at INR 499/mo, tiers INR 2,099/4,999/9,999, and a 5% markup; another says no premium. They conflict. https://www.heltar.com/blogs/whatsapp-business-api-pricing-target-1000s-in-1-click-clr618iyz135023mjsms68ght (search result 2026-10-28). Treat all as stale.
- API/webhook/calling/portability/restricted-account: no public information found.
### AiSensy (aisensy.com; fetch failed)
- What: Indian WhatsApp marketing/engagement platform. Advertises a "WhatsApp CTX Growth Champion 2025" Meta recognition (vendor page only, unverified) https://specials.aisensy.com/ . Runs a whitelabel partnership and a "Direct API" partnership where the partner builds its own embedded signup. https://m.aisensy.com/blog/whatsapp-direct-api-partnership/ (search 2026-10-28)
- Pricing: third-party lists Basic INR 1,500 and Pro INR 3,200 per month + GST, 10% off annual https://drenslio.it.com/blog/aisensy-platform-review-2026/ (low-quality source, unverified). AiSensy says it charges nothing to procure the API https://m.aisensy.com/pricing-usd (vendor-only). AiSensy's pricing page also exists for USD and is not a straight conversion. Pricing blog posts: https://m.aisensy.com/blog/whatsapp-pricing-update-october-2026/ (not opened).
- Onboarding: AiSensy partner help has an embedded-signup troubleshooting article https://faq.partner.aisensy.com/articles/9116242-how-to-troubleshoot-embedded-signup (not opened; likely generic). That implies the customer-side Meta login flow.
- API format, calling, portability, restricted-account: no public information found.

## 4. Meta pricing facts (all from search summaries 2026-10-28; Meta pages not opened)
- 2025-07-01: Meta moved from per-conversation to per-delivered-message billing for templates. Source: AiSensy news and a pricing guide (https://news.aisensy.com/95654-pricing-update-effective-july-1-2025 , https://docs.sent.dm/docs/guides/whatsapp-pricing). Vendor/third party.
- 2026-01-01: INR billing localisation for India. Source: https://montymobile.com/blogs/whatsapp-business-api-pricing-in-india-inr-rates-gst-and-the-2026-currency-migration-deadline (third party).
- India rates before 18% GST: marketing INR 0.8631; utility, authentication, service INR 0.1150; authentication-international INR 2.4971. Several blogs agree, others quote 0.7846, 0.871, 0.9494 (conflict). https://dev.to/abhishek_rajpurohit/whatsapp-business-api-pricing-in-india-2026-per-message-rates-gst-and-real-cost-math-1e3a
- 2026-10-01: free-form replies inside the 24-hour window become billable after 1,000 free per business number per month; in-window utility templates stop being free (one source: INR 0.115 from 2026-10-01). Sources disagree on whether the 1,000 allowance covers templates. Customer-initiated messages and the 72-hour click-to-WhatsApp window unchanged. Webhook pricing type changes from free_customer_service to regular (one source). https://www.wati.io/en/blog/whatsapp-service-message-pricing/ , https://www.ycloud.com/blog/whatsapp-api-message-pricing-update-effective-october-1-2026
- Calling: user-initiated calls free (Meta pricing page, per search summary, updated 2026-07); business-initiated charged per minute in 6-second steps; business-initiated per-user limit raised from 10 to 100 per day (2025-12 changelog); new feedback-based restrictions from 2026-01-27. https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing/
- Hidden costs to ask about: 18% GST on provider fees, per-seat charges, minimum commitments, currency conversion, extra fee for template or API access, number-hosting fee.
- Meta's embedded signup v2 deprecated 2026-10-15 (Meta docs via search). Ask each provider that they are on v4.

## 5. Onboarding and the restricted-account question
- Meta-documented pattern: Embedded Signup creates a new WABA linked to the CLIENT's Meta business portfolio and grants the provider's app access. https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/support/migrating-phone-numbers-among-solution-partners-via-embedded-signup (search 2026-10-28). So a provider using it still needs the founder to log in with a Facebook account.
- Documents usually asked (general, not provider-specific, unverified for Heltar/AiSensy): business name, website, business registration/GST/PAN proof for Meta Business Verification, a phone number that can receive OTP and is not already on WhatsApp app (or is migrated), display-name that matches the business. Verification can run after go-live; a policy-failing account can be blocked immediately and appealed by ticket (Sinch docs via search).
- Time to go live: vendor claims range "minutes" to days (Sinch). No independent data. No Heltar or AiSensy figure found.
- Number: must be a number you can receive OTP on; Meta's free 555 test numbers are not portable (360dialog docs). https://docs.360dialog.com/docs/resources/phone-numbers/meta-provided-555-phone-numbers
- Restricted-account behaviour: no provider's public material addresses an old ad-account restriction. Vendor help pages (Chakra, Wati, AiSensy) say generally: wait out temporary restrictions, appeal in Business Manager, or use a different unrestricted account. https://chakrahq.com/article/errors-whatsapp-api-embedded-signup/ , https://support.wati.io/en/articles/11462949-troubleshooting-embedded-signup-process-common-issues-and-how-to-resolve-them
- Important: "use a different Facebook account" in those pages must NOT be used by Friday as a workaround for a restriction on the founder (anti-circumvention). The legitimate routes: (a) Meta appeal / Business Support for the "temporarily blocked" message (the exact phrase was not found in any source; it is a generic rate-limit style message, cause unverified); (b) wait and retry; (c) an actual separate legal entity or co-founder who truly owns and operates the business (not a stand-in). Whether a Dec 2022 advertising restriction on the personal profile triggers the block: unverified.

## 6. API compatibility, reliability, lock-in
- Cloud-API-format (same webhook payloads plus X-Hub-Signature-256 with the app secret): Friday's friday/channels/whatsapp.py expects this. Not found for Heltar or AiSensy. Providers normally re-sign webhooks with their own scheme or call their own endpoints. If proprietary, Friday needs a second adapter and loses interactive-list, template and media parity until tested.
- Friday needs: text, voice note receive and send (ogg/opus), buttons/lists, templates, media download, delivery statuses, and later the Calling API (SDP/WebRTC signalling). Calling needs the provider to forward call webhooks; vendors like Infobip, Bird, Exotel, respond.io advertise it; Heltar/AiSensy: unverified.
- Rate limits and reliability: Meta limits apply (messaging tiers); provider limits unknown. Ask for an SLA, webhook retry policy and idempotency IDs.
- Lock-in: Meta documents moving a number between Solution Partners via embedded signup (migrating-phone-numbers page above). Some providers say moving requires a release step (Typewise docs via search). Template approvals and quality rating may or may not follow. Ask in writing.

## 7. Policy risks
- Meta Business Solution Terms, AI Providers section (effective 2026-01-15; new API users from 2025-10-15 per respond.io): bars AI providers when AI is the "primary (rather than incidental or ancillary)" function and treats Meta's decision as discretionary. Meta told TechCrunch the target is AI model providers distributing general assistants, not businesses using AI for support or bookings. Sources: https://techcrunch.com/2025/10/18/whatssapp-changes-its-terms-to-bar-general-purpose-chatbots-from-its-platform , https://www.whatsapp.com/legal/business-solution-terms , https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers.md (search results 2026-10-28; I could not open the primary text). Pricing policy for AI providers: charging began 2026-02-16, EU/EEA charging stopped 2026-05-13, Brazil continues (search summary).
- Friday: a consumer assistant that books, quotes and phones people AND chats. Narrow task framing helps; open-ended "ask me anything" chat is the risk. It also has no pre-existing "business" relationship with each user. Likely allowed if framed as a service assistant, but Meta's decision is discretionary. LAWYER QUESTION: does Friday count as an AI provider whose primary function is the assistant? Consider a documented use-case scope and a refusal for pure general-knowledge chat on WhatsApp (keep that for voice/other channels).
- Provider angle: providers may add their own AI-use clauses. Ask in writing.
- Opt-in and template rules: marketing templates need opt-in; Friday's reminders are utility/service.
- India: DPDP Act 2023 consent, grievance officer, retention (OTP-in-chat, call transcripts); TRAI/DLT governs SMS and promotional calls, not WhatsApp; WhatsApp Business policy on data. Not researched in depth. LAWYER QUESTION.
- Spillover: a restricted Meta account can also affect WABA creation or quality; clarify with Meta.

## 8. Other options (short)
- Gupshup: big Indian BSP; per-message fee on top of Meta (about INR 0.085, unverified); good for API; heavier sales process. https://codingclave.com/blog/gupshup-whatsapp-pricing-india-2026
- Interakt: SMB, low monthly fee; weaker for custom backends (unverified).
- Wati: SMB inbox, seat caps; public embedded-signup troubleshooting page.
- Twilio: strong developer docs, USD billing, own API format; has a Tech Provider FAQ. https://www.twilio.com/docs/whatsapp/isv/tech-provider-program/faq
- 360dialog: Meta-like passthrough, documents locked-account and number migration. https://docs.360dialog.com/docs/guides/business-account-locked
- Meta direct via a different LEGITIMATE business owner: only a genuinely separate entity or person who actually owns and operates the business; never a borrowed or extra account used to hide the restriction.
- Telegram bot: free to build (unverified), low reach in India for consumers. SMS: DLT registration needed, no rich UI. Both are fallbacks, not replacements.
- Also seen in results (not researched): MSG91, Fast2SMS, Gallabox, Chakra, YCloud, Infobip, Sinch, Bird.

## 9. Recommendation
1. First, in parallel (no cost): (a) use Meta's official appeal/support route for the "temporarily blocked" message and retry after the stated period; (b) email both Heltar and AiSensy the checklist below. Do not pick on price; pick on written answers about restricted accounts and API format.
2. Trial order: a provider with a Cloud-API-compatible API and a written "restricted account" answer. Gupshup/360dialog/Twilio are worth the same checklist since Heltar/AiSensy are proprietary-unknown.
3. Keep the direct Cloud API as the target; use a provider as a bridge only if number portability is confirmed in writing.

### Five-line checklist to send each provider
1. Pricing: all-in INR per month plus markup per marketing/utility/service/auth message, setup fee, GST, minimums, and the effect of the 2026-10-01 service-window change.
2. Restricted accounts: what happens if the owner's personal Facebook has an old (2022) ad restriction or Meta shows "temporarily blocked" at signup; can you host the WABA and run business verification without that login?
3. API format: do you forward Meta Cloud API webhook payloads with X-Hub-Signature-256, or a proprietary format; support for voice notes, buttons, lists, templates, media, Calling API; rate limits and webhook retries.
4. AI assistant policy: is a task assistant that chats and books on behalf of consumers allowed on your platform under Meta's AI Providers terms?
5. Number portability: can we move the number and WABA to our own Meta account or another BSP without downtime, OTP or loss of templates and quality rating? Are you listed in Meta's partner directory (link)?

### Free-trial tests (no credentials in chat)
- Sign up only through the provider's own web form; never paste tokens into chat or git; put tokens only in the server .env.
- Test: webhook payload shape and signature on a throwaway URL; text, voice note in and out, button and list, template approval time, media download, delivery statuses, duplicate/ordering behaviour, a call webhook if offered, and an export of contacts and templates.
- Measure latency over a day and webhook retry behaviour. Use only the allow-listed founder number.

### Stop if
- Provider refuses or evades the restricted-account question, or suggests another person's/extra Facebook account.
- No written portability promise; proprietary-only API with no voice notes, lists or templates.
- Provider says Friday breaks its AI policy, or Meta flags the number.
- Hidden per-message markup above what the founder accepts, or minimum commits.

## 10. Gaps (what I could not verify)
- All direct fetches failed (DNS), so no vendor or Meta page was read. Heltar and AiSensy pricing, partner status, API docs and restricted-account policy are unconfirmed.
- Conflicting India rate figures; Oct-2026 free allowance scope; whether "temporarily blocked" is caused by the 2022 restriction; Meta's primary AI Providers text; Telegram and Twilio exact pricing.
- Re-run this research from an environment with working web fetch; then replace "unverified" items.
