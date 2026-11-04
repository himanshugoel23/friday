# Friday for parents: product research and Phase 1 proposal (2026-11-04)

Prepared as product head at the founder's request (2026-11-04). Evidence tags: **[S]** = seen in a search result this session (source in section 12), **[U]** = unverified or from a low-quality source, **[A]** = my own assessment/inference, not a fact. My search tool is US-focused and many results are blogs or vendor pages; every number below should be re-checked against the primary source before it goes into marketing.

## 1. Positioning (what changed)
- **From:** a general assistant for everyone (wins nothing against free ChatGPT/Gemini/Perplexity offers and Instinct).
- **To:** **Friday for parents: security and care**. Buyer = the adult child (lives in another city or country). User = the parent (60+). Child interface = WhatsApp. Parent interface = phone calls to and from Friday + a small Android app. No vendor/third-party calling in Phase 1.
- One-line promise **[A]**: "Your parents are never alone with a stranger on the phone. Friday checks on them every day, watches for scams, and tells you the moment something looks wrong."

## 2. What the threat looks like right now (India)
| Scam | What happens | Evidence |
|---|---|---|
| **Digital arrest** | Caller poses as CBI/TRAI/police/court, "arrests" the victim on video call, forces transfers. Seniors lose crores per case. | **Figures conflict: do not quote one number.** ORF/Pioneer attribute Rs 22,495 crore (2025) to digital arrest, but the Rio discovery PDF (2026-11-03) cites Rs 22,931 crore and 28 lakh cases as ALL digital fraud 2021-2025 and Rs 4,057.7 crore across 297,727 complaints for digital arrest 2022-May 2026 (NewsBytes) **[U, I judge the PDF split more plausible]**; I4C: about 46% of operations traced to Cambodia/Myanmar/Laos **[S]**; a report to the Supreme Court: 21,928 digital-arrest complaints, over Rs 647 crore, Jan-Aug 2026 **[S, secondary]**; cases: 82-year-old in Pune Rs 10.74 crore (Jan 2026), 82-year-old in Chandigarh Rs 2.5 crore **[S, news]**; Supreme Court took suo motu notice **[S]**. |
| **Fake KYC / bank block + remote-access app** | "Update KYC or account is blocked", victim installs AnyDesk/TeamViewer/QuickSupport, scammer drives the phone. | Mumbai senior Rs 3.95 lakh after AnyDesk; Goa man Rs 2.10 lakh; several similar **[S, news]**. |
| **UPI collect request as "refund"** | Victim enters PIN to "receive" money; it pays the scammer. | Guidance in several bank/finance blogs **[S]**; "UPI limit" scam cost an Indore pensioner couple nearly Rs 6 lakh **[S]**. |
| **Fake utility/bank helpline call** | Caller ID shows a bank logo/name; or "electricity will be cut tonight". | Andaman man Rs 2.89 lakh; Indore case with bank logo on screen **[S]**. |
| **APK files on WhatsApp** | "Wedding invitation.apk", "parcel tracking.apk" gives the scammer SMS/OTP/phone control. | Police warnings in Himachal and Rajasthan; Bengaluru man Rs 5 lakh **[S]**. |
| **Pension / life-certificate scams** | Fake Jeevan Pramaan links/apps/calls; OTP and bank details stolen. Seasonal: pensioners 80+ from 1 Oct, others in Nov. | Kerala Police warning (Oct 2026), Pune retired officer Rs 4.5 lakh, CPAO: "no agency calls for life certificate or OTP" **[S]**. |
| **AI voice-clone "relative in trouble"** | Cloned voice of a family member asks for urgent money. | Indore Jan 2026 (Rs 97,500), Hyderabad 72-year-old Rs 1.97 lakh (2025) **[S, AI Incident Database + news; several blogs only [U]]**. Advice commonly given: family safe word, call back on a known number. |
| **Investment/Telegram/WhatsApp groups, fake apps** | "Guaranteed returns" groups and fake trading apps. | Quick Heal predicts steep rise in social-media scams in 2026 **[S]**. |
Scale context: cumulative reported losses 2021 to mid-2026 above Rs 55,050 crore across 65.8 lakh complaints (Quick Heal page citing the national portal) **[S, verify]**. Helpline **1930**, portal cybercrime.gov.in **[S]**.
**Caution [S]:** Quick Heal's KYC analysis says seniors are a smaller SHARE of KYC-scam victims by count (older adults 12-15%, seniors 5-8%, middle-aged 20-25%). Seniors lose less often than adults overall but, per the news cases, in much larger amounts per case **[A]**. Pitch the fear honestly: "rare but ruinous".

## 3. Changes in the environment that matter to us
- **Google Play Protect India pilot [S]**: blocks installs from browsers, messaging apps and file managers that ask for sensitive permissions (e.g. SMS). **Call-time protection [S, one May 2025 report]**: during a call with an unknown contact, the phone blocks first-time app installs from those sources, blocks granting accessibility permission and blocks turning off Play Protect; Google is testing blocking banking apps while screen-sharing; Google Pay/Paytm/Navi screen-share warnings **[S, Gulf News]**. These help our users but also mean our own app (needs special permissions) must be Play-compliant, not sideloaded.
- **CNAP (caller name display) [S]**: DoT circular dated 13 Oct 2026 requires carriers to show KYC-verified caller names on 4G+ from **1 Nov 2026**; status of actual launch not confirmed in my results. If live, spoofed "bank" names get harder; our unknown-caller warning should lean on it when available **[A]**.
- **RBI discussion paper "Exploring Safeguards in Digital Payments to Curb Frauds" (10 Apr 2026) [S, secondary coverage]**: ideas include a one-hour delay on UPI/IMPS transfers above about Rs 10,000 (not for trusted contacts), approval by a nominated **trusted contact** for 70+ above about Rs 50,000, a kill switch. **Proposal only.** If adopted, the adult child as "trusted contact" is a natural hook for Friday **[A]**.
- **UPI Circle [S]**: existing feature letting a primary user delegate payments to trusted secondary users, with a 24-hour cooling period after linking.
- **DPDP Rules 2025 [S]**: notified 14 Nov 2025; consent rules for guardians apply to persons with disabilities (Rule 11), not to ordinary seniors; an adult senior must give their own informed consent. Timelines are phased, check the gazette. Get legal review before launch **[A]**.
- **Free general AI in India [S]**: ChatGPT Go free for a year for Indian sign-ups (Nov 2025 onwards), Gemini bundled free with Jio, Perplexity via Airtel (status conflicting). Analysts call it a distribution war. A new general assistant cannot win here **[A]**.

## 4. Competitors and gaps
- **Truecaller Family Protection [S, many outlets]: launched in India mid-March 2026, free core feature, family group up to 5, the admin gets alerts during potential scam calls and can end them remotely on Android; Truecaller Scam Checker (free: links, numbers, messages) launched in India 28 Sep 2026 [S, one outlet]. Google also ships on-device scam-call detection in India [S]. So plain call screening is NOT a differentiator.**
- **Khyaal [S, 2021 article]**: children buy plans for parents (Basic/VIP/Premium), medication reminders, weekly report to family; human services. **Emoha [S]**: membership with 24/7 emergency response, health monitoring, community; prices not found. **HealthSarathi, Samarth [S]**: vendor pages, physical care/NRI plans. **Haal Chaal [S, app page]**: free iPhone app, SOS, "I'm OK" check-ins, medicine reminders, QR family link, **no scam protection, no calling mentioned**.
- **AI phone check-in services (US) [S, vendor pages]**: Joy Calls (about USD 30 per month paid tier), Sentinel (under USD 2 per day), ElderDial (consent intro call, alert when calls go unanswered), Meela, Heartbeat. Proves families pay for AI check-in calls; none are India/Hindi/scam-aware.
- **Platform defaults**: Google Play Protect, Truecaller, CNAP, bank apps' own warnings.
- **Gap [A]**: I did not find an India product that combines (1) proactive Hindi/Hinglish voice calls, (2) scam checking at the moment of doubt, (3) child-facing alerts on WhatsApp, (4) a trust-first design that the parent controls. Treat as a hypothesis; do real market scans with product-manager agent and user interviews.
- **Known adoption barrier [S, vendor guide]**: parents resist monitoring ("suspicious of devices that monitor them"). Mitigation = the parent owns the app and sees everything Friday shares.

## 5. What an Android app can and cannot do (Play-compliant)
| Wish | Reality | Verdict |
|---|---|---|
| Read parent's SMS | SMS/Call Log permissions only for the default SMS/Phone handler **[S, Play policy text]** | **No** (do not ask). |
| Read WhatsApp messages | No API; notification listener or accessibility would be needed; Accessibility API restricted by Play policy **[S]** | **No** by default. Notification access is a possible later opt-in; Play review risk **[U]**. |
| Record calls | Not allowed by Play policy; legal consent issues **[S]** | **No.** |
| Screen unknown callers | `CallScreeningService` via the call-screening role (Android 10+), carrier verdict data from Android 11 **[S, developer docs]**; only calls not in contacts are passed for screening in AOSP comments **[S]** | **Yes**: warn before answering, show a plain-language banner, optional auto-reject of flagged numbers; log "unknown call, duration". |
| "Check this for me" | Android share sheet: parent shares a link, screenshot, forwarded message, APK name or phone number to Friday | **Yes** (core feature, zero special permission). |
| Detect remote-access apps | Query specific package names (AnyDesk, TeamViewer, QuickSupport, RustDesk...) via `<queries>`; broad app listing (QUERY_ALL_PACKAGES) is restricted **[A, policy not re-verified]** | **Yes**, narrow list. |
| Know the parent is in a banking app during an unknown call with screen share | Needs usage-access and overlay-type permissions, Play review needed **[U]**; Android's own call-time protections already cover part | **Later**, partly redundant. |
| Fall detection | Google's is a Pixel Watch feature; phone-only fall detection not found; crash detection needs a SIM **[S]** | **Not Phase 1** (false alarms, hardware). |
| Location sharing | Standard location permissions, consent screen | **Optional**, opt-in per parent. |
| Daily "phone alive" signal | Foreground-service heartbeat is battery-hostile on cheap phones; use "last seen" from app usage/charging and a simple daily tap | **Yes**, light. |
| Monitoring-app rules **[S]** | Play requires clear notice/consent, a persistent notification and a distinct icon; apps may not conceal monitoring; family-monitoring apps must be marketed as such | **Design rule:** the parent installs it, sees "Friday is protecting you", can pause, sees the list of what the child receives. |

## 6. Phase 1 feature set (proposed)
### Parent side: calls (Friday to parent AND parent to Friday)
1. **Daily check-in call** in Hindi/Hinglish at the parent's chosen time: how are you, did you eat, any pain, any unknown calls today, medicines taken. Voice, short, warm (existing voice stack; Sarvam voices). No answer: retry twice, then WhatsApp the child (existing urgent-escalation pattern).
2. **Medicine schedule and reminders**: child sets drug names/times (or sends a photo of the prescription, existing document vision); reminder by call or app notification; "taken/not yet" tap or voice; missed doses reported to child; refill reminder date set by child. Friday gives no medical advice beyond "ask the doctor".
3. **"Pehle Friday ko dikhao"** one-tap scam check: share link/screenshot/forwarded message/phone number to Friday (share sheet or WhatsApp to the Friday number); answer in 2 lines in the parent's language: **Scam / Looks safe / Not sure, ask your son** with the reason; high-risk ones also alert the child. Stops: CBI/TRAI/police on call, "digital arrest", "KYC blocked", electricity cut-off, "refund" collect request, APK files, remote-access app requests, OTP/PIN requests, "relative in trouble".
4. **Unknown-caller guard** (call-screening role): flags international/spoofed/unknown numbers, shows a banner "Unknown caller. Never share OTP or PIN. Nobody gets arrested on a call.", logs call length; if an unknown call lasts longer than N minutes, Friday calls the parent afterwards: "Who called? Did they ask for money?"
5. **Remote-access guard**: warns when a known remote-access app is installed or opened and alerts the child with one tap to call.
6. **Safe-word flow for voice clones**: the family sets a safe word with the child; Friday reminds the parent "ask them for the safe word before sending money"; one-tap "Call my son" connects them on a known number.
7. **Big SOS button** and "Friday help" voice trigger via a call to Friday: calls the child and tells them, optional location.
8. **Seasonal alerts**: pension/life-certificate window (Oct-Nov), festival-season courier and wedding-card scams, tax/KYC deadlines: short pre-emptive warning calls.

### Child side (WhatsApp; web chat as fallback while Meta's token is blocked)
1. **Real-time alerts** with buttons: Call parent, Call parent with Friday on the line, Mark safe, Show details. Tiers: INFO (digest), WATCH (unknown long call), HIGH (remote-access app + banking, digital-arrest keywords, parent says money was asked).
2. **Daily/weekly digest**: calls answered, medicines taken, scams checked/blocked, mood word from the check-in, unusual silence.
3. **Setup by chat**: parent profile, medicine schedule, check-in time, quiet hours, trusted contacts, safe word, language.
4. **Consent view**: the child sees exactly what Friday can see; the parent can pause at any time; both receive the same list.
5. **Escalation ladder**: parent unreachable, child unreachable, second family contact, then "call 112 / local contact" only with prior consent.

### Explicitly NOT in Phase 1
Vendor/third-party calls, shopping and browser agent tasks, job hunt, call recording, reading SMS/WhatsApp, fall detection, bill payment, doctor booking. These return as Phase 2 "do things for your parents" (below).

## 7. Phase 2 and 3: how the general assistant comes back (answer to "daily ke kaam")
Once parents trust the daily call and the child trusts the alerts, the original capabilities become *reasons to upgrade*: book the doctor and arrange transport, reorder regular medicines, pay electricity/phone bills with a parent-approved UPI link (Friday never pays), grocery reorder, appointment reminders, tracking a pending refund or pension query, form help. Each is initiated by the CHILD on WhatsApp ("papa ki BP ki dawa mangwa do") or by the parent by voice, with the existing approval and stop-at-payment rules. The product would stay "parents' care", not "general assistant".

## 8. Trust, consent and compliance (design rules)
1. **Parent consent first**: onboarding call + app screen in the parent's language explaining what Friday sees; parent can say no to each item; no covert mode; persistent notification; pause button; "what my son can see" screen.
2. **Child sees alerts and summaries, not content** (no message text, no call audio). Call recordings: none.
3. **DPDP**: notice + purpose limitation + minimal data + erase on request; verifiable parental/guardian consent is a different regime (children, disabled) **[S]**; get a lawyer to review before public launch **[A]**.
4. **Telecom**: outbound calls only to the consenting parent's number; disclose "Friday, an AI assistant"; respect quiet hours; check TRAI/DND exemptions for transactional/service calls **[U, research needed]**.
5. **No medical advice**; emergencies go to 112; keep the care protocol (distress) active (docs/INSTINCT_CHAT_6.md section E).
6. **Data**: voice and scam-check content encrypted, short retention, never used for training without opt-in.
7. **False negatives**: Friday must never say "this is safe" for money requests; the best we say is "no scam signs found, still do not share OTP/PIN" **[A]**.

## 9. What we can reuse from the codebase
Voice calling and TTS/STT (friday/voice), call queue and urgent escalation (friday/urgent), scheduler and reminders, WhatsApp/web channel, document vision (prescriptions), guardrails and the care protocol work, evidence/proof cards, vault, style layer, bench harness (add scam-script scenarios), A2A/agent team for later. **New build:** parent and family model with consents, Android app + device API (heartbeat, share intake, call-screening events, remote-access detection), scam-check engine (rules + lists + LLM with strict output, evidence of why), alert tiers and routing, medicine schedule, safe word, digest, onboarding calls.

## 10. Business model (hypotheses to test, not facts)
- **Buyer/payer**: adult child (metro/NRI), pays monthly. Distribution through the child: WhatsApp forwards, referral, bank/insurer partnerships later **[A]**.
- **Reference prices [S]**: US AI check-in services about USD 30 a month; Indian elder-care memberships with human responders priced higher but unpublished. **[A]** Test INR 299-499 a month for "daily call + scam check + alerts", a family annual plan, and a free tier that only does the scam-check (acquisition).
- **Risk to the model**: parents install once and forget; the daily call must feel like a relationship, not a robot. Track: calls answered, scam checks per week, child opens digest.
- **Metric for phase 1**: after 30 days, % of parents answering daily call at least 5 days a week; # of scam checks per parent; child NPS; at least one "saved" story validated.

## 11. Risks and open questions
1. **Two-sided adoption**: parent must install and accept; child must pay. Plan a pilot with 10-20 real families the founder knows.
2. **Meta WhatsApp** is still blocked (token); web chat fills in, but the child interface should be WhatsApp. Founder owns this.
3. **Play review and permissions**: call-screening role and monitoring policy; use a closed testing track for the pilot **[A]**.
4. **Liability** if an alert is missed: terms, clear "assistant, not guarantee" copy, insurance; legal review.
5. **Voice quality in Hindi for elders** (speed, accent, noisy homes, low smartphone literacy): needs real tests; hear-before-change rule applies to every spoken line.
6. **Calling costs and quiet hours** at scale (Vobiz per-minute): daily 2-3 minute calls per parent cost model needed **[A]**.
7. **Elders' privacy and dignity** (monitoring creep): keep consent visible; consider a parent-facing weekly "what Friday did for you".
Questions for the founder: target city/language mix; iPhone parents (Android only for now?); will the child be in India or abroad (call timing, payments, NRI plans)? first 10 pilot families; Phase 1 price test.

## 12. Sources used (search results this session; verify before external use)
- ORF, Digital Arrest Scams and the Limits of Domestic Enforcement: https://www.orfonline.org/expert-speak/digital-arrest-scams-and-the-limits-of-domestic-enforcement
- Inventiva (Supreme Court, 647 crore): https://www.inventiva.co.in/trends/a-%E2%82%B92-10-crore-fraud-a-senior-citizen-and-why-supreme-court-wants-banks-to-pay-digital-arrest-fraud-victims-as-%E2%82%B9647-crore-is-lost-in-8-months/
- Tribune (Chandigarh case): https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud
- Free Press Journal (Mumbai AnyDesk case): https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app
- Free Press Journal (Indore UPI limit scam): https://www.freepressjournal.in/indore/upi-limit-scam-costs-pensioner-couple-nearly-6-lakh-in-indore
- YourStory, age-tech and fraud against seniors (fetch blocked, headline only): https://yourstory.com/2026/01/how-age-tech-can-solve-digital-fraud-targeting-seniors
- Quick Heal fraud trends mid-year 2026: https://www.quickheal.co.in/knowledge-centre/fraud-trends-in-india-mid-year-2026-report/
- Quick Heal elder fraud report: https://www.quickheal.co.in/knowledge-centre/guarding-our-elders-a-comprehensive-report-on-the-elder-fraud-epidemic-in-india/
- Wedding-invitation APK scam (Business Standard): https://business-standard.com/india-news/whatsapp-wedding-invitation-scam-scammers-find-new-tricks-to-steal-money-nc-124111301447_1.html
- Tribune Himachal police warning: https://www.tribuneindia.com/news/himachal/invited-to-wedding-police-say-check-the-link-before-you-click
- Pension/life-certificate: https://theprint.in/india/cyber-fraud-targeting-bank-pensioners-through-fake-life-certificate-links-police/3073179/ and https://www.uniindia.com/south-india/crime-kerala-cyber-pensioners/215224 and https://www.indianpaycalculator.in/govt-news/life-certificate-update-call-otp-fraud-cpao-pensioners-2026
- AI voice clone incidents: https://incidentdatabase.ai/entities/scammers-in-india/ and https://dailypioneer.com/news/when-your-voice-is-no-longer-proof
- Google, enhanced fraud protection pilot in India: https://blog.google/intl/en-in/products/launching-enhanced-fraud-protection-pilot-in-india/ ; call-time protections: https://www.newsbytesapp.com/news/science/google-enhances-android-security-against-phone-scams/story ; Gulf News: https://gulfnews.com/technology/media/google-ramps-up-ai-scam-protection-in-india-1.500355149
- Android call screening docs: https://developer.android.com/develop/connectivity/telecom/dialer-app/screen-calls and https://developer.android.com/develop/connectivity/telecom/dialer-app/prevent-spoofing
- Google Play SMS/Call Log policy: https://support.google.com/googleplay/android-developer/answer/10208820 ; stalkerware policy coverage: https://www.techradar.com/news/google-finally-bans-stalkerware-apps-but-there-may-still-be-a-problem
- CNAP: https://www.nationalheraldindia.com/national/department-of-telecommunications-directs-telecom-operators-to-roll-out-caller-name-display-service-from-1-november and https://www.business-standard.com/industry/news/cnap-service-nationwide-rollout-by-march-2026-dot-trai-telecom-125102901190_1.html
- RBI discussion paper coverage: https://www.businesstoday.in/technology/news/story/rbi-suggests-cooling-off-period-for-upi-bank-transfers-what-it-means-for-you-525178-2026-04-10 and https://moneylife.in/article/rbis-proposed-digital-payment-safeguards-what-do-they-mean-for-you/80218.html
- DPDP Rules 2025: https://www.scconline.com/blog/post/2025/11/14/meity-notified-digital-personal-data-protection-rules-2025/ and https://www.dpdpa.com/dpdparules/rule11.html
- Competitors: Khyaal (YourStory 2021): https://yourstory.com/2021/03/khyaal-agetech-startup-from-india-wants-to-be-synonymous-with-holistic-elderly-care ; Haal Chaal: https://apps.apple.com/app/id6758404795 ; Emoha/HealthSarathi/Samarth via search; AI check-in services: https://www.homecaremag.com/news/joy-calls-launches-ai-phone-companion-seniors and https://www.prweb.com/releases/eve-communications-launches-ai-caregiving-service-to-support-seniors-and-family-caregivers-302327194.html
- Free AI offers in India: https://www.dqindia.com/data-and-ai/free-ai-tools-in-india-are-gemini-chatgpt-perplexity-really-free-in-2026-10965188 and https://bestmediainfo.com/mediainfo/mediainfo-digital/why-perplexity-gemini-chatgpt-free-in-india-distribution-war-10642924
- Pixel Watch fall detection: https://blog.google/products-and-platforms/devices/pixel/fall-detection-on-pixel-watch/ ; 112 India ERSS app: https://apps.apple.com/app/id1441951304
