# Parents' security and care: Phase 1 spec (2026-11-04)

Founder's Phase 1 feature list (2026-11-04), turned into a spec with an honest feasibility check. Companion to docs/PARENT_CARE_RESEARCH.md (market, scams, consent rules, sources). Evidence tags: **[S]** seen in a search/doc this session, **[U]** unverified (needs a test on a real phone or a policy check), **[A]** my assessment. Every spoken or chat line here is PENDING founder approval; nothing in this document is built yet except what section 1 says exists.

## 0. The three founder features, in one line each
1. **Friday answers missed calls** (for the parent or the child), tells the other person on the app/WhatsApp if urgent, and keeps trying on its own judgment.
2. **Friday notices unusual activity on the parent's phone** by combining signals (unknown call, then video call, then a payment app, then a screen share) and then updates the child, nudges the parent, or reassures.
3. **Emergency button, medicine refill checks, daily check-ins, and later CCTV.**

## 1. Feature 1: family call answering (largely exists)
**Already in the codebase [S, docs]:** `friday/receptionist` (Friday answers only calls the user did not pick up, via carrier conditional forwarding to Friday's number; takes a message in at most 90 s; classifies URGENT/NORMAL/SPAM; WhatsApp summary with buttons; digest for non-urgent) and `friday/urgent` (URGENT alert, then if not acknowledged within N minutes Friday rings the user's own number, at most 2 calls, daily cap). Both default OFF; lines PENDING approval. Docs: docs/RECEPTIONIST.md, docs/URGENT_ESCALATION.md.

**Adaptation for the family niche (new work):**
- **Two phones in the family graph.** The parent's phone forwards missed calls to Friday; the child's phone can too. A call from the child that the parent misses: Friday answers the child ("Papa abhi phone nahi utha rahe. Main unhe batati hoon aur dobara try karti hoon.") and starts a **reach-the-parent loop**. A call from the parent that the child misses: Friday answers the parent warmly, takes the message, tells the child on WhatsApp, and if the parent says it is urgent, escalates.
- **"Keeps calling on its own judgment" becomes bounded autonomy** (section 5): Friday decides urgency (rules first, LLM second), and the family sets the ceiling (how many tries, which hours, who is next).
- **Parent-friendly voice**: slower, simpler Hindi/Hinglish, repeats the key line, never asks for OTP/PIN, always says it is an AI assistant, offers "press 1 / say 'beta ko bulao' to ring your son now".
- **Setup friction [A]**: conditional forwarding has to be set once on each SIM. Sources disagree on exact codes and **a DoT item says USSD-based forwarding was suspended (2024, current status not confirmed) [S, U]**; Airtel/Vi/BSNL allow it in phone Settings, Jio via the MyJio app **[S]**. The Android app can walk the parent through the phone's own call-settings screen, and the child can do it at a family visit. **Whether Friday receives the original caller's number on forwarded calls ("redirecting number") is unverified with Vobiz [U]**; the receptionist doc already marks this as unverified.
- **Android can't answer calls on the parent's behalf**; forwarding is the only reliable way **[A]**.

## 2. Feature 2: unusual-activity detection (signal reality check)
What Android lets a Play-compliant app see **[S]/[U]**:

| Signal | How we get it | Permission / policy | Confidence |
|---|---|---|---|
| Unknown caller (incoming) + number + time | Call-screening role (`CallScreeningService`, Android 10+; non-contact calls are passed to the screener; carrier verdict data from Android 11) **[S]** | User grants the role in Default apps; no SMS/Call Log permission | Good |
| Call is ongoing and how long | Telephony call-state callback (ringing / off-hook / idle) | `READ_PHONE_STATE`; number itself NOT available without Call Log permission (restricted **[S]**), so pair with the screener's number | Good for duration |
| Outgoing call to a new number | Not reliably visible without Call Log; possibly via screening direction **[U]** | restricted | Low |
| **Video call likely** | Camera becomes unavailable because "some application or service starts using it" (`CameraManager.AvailabilityCallback`) **[S]**; whether a permission is needed is **unconfirmed [U]**; this says "camera in use", not which app or whether it is WhatsApp | none confirmed | Medium: a proxy only |
| Microphone/recording in use by another app | Audio recording callbacks exist but details for other apps are limited **[U]** | unknown | Low |
| **Screen share in progress** | No public API to detect another app capturing the screen **[A, not found in my search]**. Proxy: a known remote-access or screen-sharing app opened; plus Google's own call-time protections and screen-share warnings in Google Pay/Paytm/Navi **[S]** | none for package-name checks | Low for generic screen share, Good for named remote-access apps |
| Remote-access app installed/opened | Query specific package names with `<queries>`; foreground check via usage access **[A/U]** (Play policy for usage access **not verified [U]**) | package visibility / usage access | Good for a fixed list |
| Payment/banking app opened | Foreground app via usage access **[U]** | special "usage access" | Medium; policy check needed |
| **A transaction happened** | **No API to see UPI/bank transactions on the phone.** Proxies: (a) parent's bank alert emails delivered to the child's mailbox, read by Friday with the child's Google consent **[A]**; (b) RBI Account Aggregator read-only feed with the parent's consent **[U]**; (c) payment app opened during a suspicious call; (d) if RBI adopts "trusted contact approval" for 70+ above about Rs 50,000 **[S, proposal]**, the child approves in the bank app and Friday just explains | varies | (a) Medium, (b) Later |
| New app installed from outside Play | Installer-package check requires package visibility **[U]**; Play Protect's own India pilot blocks risky sideloads **[S]** | - | Low; lean on Play Protect |
| Phone idle all day | App heartbeat plus daily tap; screen-unlock broadcast needs a battery-costly service **[A]** | - | Use the check-in call instead |

**Reality in one sentence [A]:** we can see "unknown call + how long + camera in use + a payment or remote-access app opened + a bank alert later", not message content, not the screen, not the exact transaction in real time. That is enough for good risk scoring if we are honest in the wording ("looks like", not "is").

## 3. Scenario table: key scenarios, signals, actions
Scores are per parent per rolling 30 minutes. Start in **shadow mode** (log, do not alert) for the first week of a pilot with the family's consent, to measure false positives before turning alerts on **[A]**.

| # | Scenario | Signals (all within window) | Parent nudge | Child message | Reassure path |
|---|---|---|---|---|---|
| S1 | **Digital-arrest pattern** | unknown/international caller, call over 10 min, camera in use at any time, call still going at 20 min | Banner + vibration at 10 min: "Koi 'arrest' ya 'jaanch' ki baat kare to ye scam hai. Phone kaat do." At 20 min: Friday rings after the call ends or pops a full-screen "Call my son" | WATCH at 10 min, HIGH at 20 min with buttons [Call Papa] [Friday jumps on his line] [Mark safe] | Parent taps "Ye mera rishtedar hai" -> number trusted; child gets "false alarm, trusted" |
| S2 | **Remote-access takeover** | AnyDesk/TeamViewer/QuickSupport... opened (any time) | Full-screen: "Isse koi aapka phone control kar sakta hai. Band kar dijiye." | HIGH at once | "Maine khud lagaya" for a child-initiated support session (child pre-approves a support window) |
| S3 | **KYC / OTP call** | unknown caller, then banking or UPI app opened within 15 min of the call starting, call still active or ended less than 5 min ago | "Kya call pe kisi ne bank app kholne ko kaha? Bank kabhi call pe app nahi khulwata." | WATCH; HIGH if the call is over 5 min | Parent: "Maine khud kholi" -> logged, no escalation |
| S4 | **Voice-clone panic** | call from a number that is not in contacts or a contact whose call is short, then within 10 min the parent calls the child (or opens a payment app) | "Rukiye. Kya unhone paise maange? Unse family safe word poochiye." | Heads-up: "Papa ko abhi koi 'rishtedar' bankar call aaya lagta hai" | Safe word matched (parent says it) -> resolved |
| S5 | **Large payment to new payee** | bank alert (via email to child) above family threshold, new beneficiary | Friday rings the parent: "Aapne abhi Rs X bheje? Agar nahi, turant bank ko 1930/ bank helpline par call kijiye." | HIGH with the exact alert text (no more) | Parent confirms "haan mera hi tha" -> logged |
| S6 | **Night video call** | unknown video-like activity (camera in use) at night | Gentle nudge next morning, not at night | WATCH in the digest | - |
| S7 | **Unreachable** | daily check-in unanswered, two retries failed, no phone heartbeat | - | Escalation ladder: WhatsApp, then call child, then second family contact | Parent answers later -> "Papa is fine" message |
| S8 | **Pension/KYC season** | calendar windows (Oct-Nov pensioners) | Pre-emptive call: "Jeevan Pramaan ke liye koi call/link aaye to OTP mat dena." | Digest note | - |

**Tone rules:** never "this is a scam" with certainty from signals alone; say "looks risky". Never announce "all clear" for anything involving money; at most "I saw nothing risky, but never share OTP or PIN". False alarms cost trust: every alert has a "this was fine" button that teaches the system (per parent) and lowers future noise.

## 4. Feature 3: emergency, refills, check-ins, CCTV
- **Emergency button** (Phase 1): big in-app button, home-screen widget, and "call Friday" speed-dial. Flow: rings the child, WhatsApps the child (and a second contact if set) with location only if the parent consented; asks the parent to say what happened; repeats on the ladder; **Friday does not auto-dial 112 in Phase 1** (the phone can: one-tap "Call 112" on the SOS screen). Fall detection **not** Phase 1 (Pixel Watch only **[S]**, phone-only false alarms **[A]**).
- **Medicine schedule and refill checks** (Phase 1): child sets drug, dose, times, pills per strip and last purchase date (or photographs the prescription, existing document vision, child confirms). Friday reminds the parent (call or notification), records taken/missed, estimates days of stock left, asks the parent weekly "kitni goliyan bachi?" to correct drift, tells the child "BP ki dawa 5 din ki bachi hai". **No medical advice.** Phase 2: order the refill with a payment link the family pays (Friday never pays).
- **Daily check-in** (Phase 1): call at the parent's time; asks eating, sleeping, pain, mood, any strange calls; reads out nothing long; the child gets a one-line result.
- **CCTV** (Phase 3, design notes): events only, never raw video in Friday: "no movement by 10 am", "door opened at 2 am", "someone fell" via camera or hub AI. Integration depends on the camera brand (RTSP/ONVIF or the vendor's cloud API **[U]**); needs consent of everyone in the home and staff, visible notice, edge or on-camera detection, DPDP review, and a clear "Friday does not watch live" promise. Not before the daily-use base exists **[A]**.

## 5. Autonomy policy (how "Friday's own judgment" stays safe)
1. **Tiers:** INFO (digest), WATCH (nudge the parent, note to the child), HIGH (child alert at once, parent nudge, ladder), EMERGENCY (SOS or explicit danger words).
2. **Ceilings set by the family at setup, with defaults:** parent nudges max 2 per hour; Friday calls to the parent max 3 per incident, spaced 5 minutes; quiet hours 10 pm to 7 am except EMERGENCY and HIGH-with-money; daily cap of 3 outbound escalation calls per person; second contact only if named in advance.
3. **Always stop on acknowledgement**, on "I am fine", or on the child saying "I have it".
4. **Always explain:** every alert says why in one line ("unknown caller 22 minutes + camera on").
5. **No surprise actions:** Friday never blocks a number, messages third parties, calls 112 or contacts a bank by itself in Phase 1; it advises and rings family.
6. **Sensitivity setting** for the child: Calm / Balanced / Careful (changes thresholds, not what data is read).
7. **Audit log** visible to both parent and child ("what Friday did today"), erasable on request.

## 6. Android app: what it needs in Phase 1
Permissions and roles: call-screening role, phone-state, notifications, (optional) location, (decide after policy check) usage access, package-visibility `<queries>` for named remote-access apps; **no SMS, no Call Log, no accessibility, no call recording** **[A, per the Play policy text seen in research]**. Parent-owned app: persistent notification, distinct icon, "what my son sees" screen, pause button, monitoring-tool declaration in Play Console **[S]**. Distribution for the pilot: Play closed testing (not sideloaded APKs: Play Protect's India pilot blocks risky sideloads **[S]**). Needs: device API on our server (heartbeat, signals, share intake), per-parent keys, signal events stored as counts/timestamps only.

## 7. Phase split
- **1A (reuse, mostly wiring):** family graph + consent, daily check-in call, medicine schedule/reminders/refill estimate, receptionist for family calls, urgent escalation ladder, child alerts on WhatsApp (web chat as fallback while Meta's token is blocked), SOS call flow, scam-check by share/WhatsApp to Friday, care protocol.
- **1B (Android app):** call-screening role, unknown-caller banner, remote-access-app guard, share-to-check, camera-in-use and call-duration signals in shadow mode, correlation engine and scenarios S1-S4, S7, S8.
- **1C:** bank-alert-email signal for S5, usage-access signal if policy allows, tune thresholds on pilot data, weekly "what Friday did" report.
- **Phase 2:** refill ordering, doctor booking, bill-payment links, vendor calling for parents' errands (the old Friday features, initiated by the child).
- **Phase 3:** CCTV events, Account Aggregator feed, fall detection with a wearable partner, bank/insurer partnerships.

## 8. Risks specific to these features
1. **False alarms** from camera-in-use and long calls (a parent can legitimately video-call a grandchild: that is why contacts and the "family" tap exist).
2. **Missed scams**: unseen channels (WhatsApp calls, messages). Be clear in marketing: "Friday adds protection, it does not guarantee it".
3. **Policy risk**: usage access and call screening reviews; keep a fallback that works with only the call-screening role + share-to-check.
4. **Forwarding setup** is the most fragile step; test on Jio, Airtel and Vi phones before promising.
5. **Alert fatigue** for the child; shadow-mode week and the "this was fine" button.
6. **Cost**: outbound calls and TTS per parent per day; model it before pricing.

## 9. Questions for the founder
1. Which signals do you want in the pilot even if a policy review might delay them (usage access)? My suggestion: pilot with call screening, remote-access guard, share-to-check and camera-in-use, add the rest after review.
2. Should Friday ring the **parent** only, or may it also ring a second family contact on its own after the ladder? (Policy default above: second contact only if named in advance.)
3. For S5, is it acceptable that the child forwards the parent's bank email alerts to Friday's inbox (or connects their Gmail) in the pilot?
4. Are first pilot families on Jio, Airtel or Vi? (forwarding setup differs).
5. Who approves the Hindi wording and the voice (hear-before-change)?

## 10. Inputs from the "Metabolic Care and Rio Elder Safety" discovery PDF (2026-11-03, 21 pages, founder-supplied)
The PDF has two products; only the **Rio elder safety** half (pages 9-20) applies. The metabolic-care half (fertility-ready GLP-1 programme) is a separate product I have not touched. The PDF is AI-assisted desk research (blogs and news; its own sources list says review/blog sites are opinions), so treat its numbers as **[U]** until checked. What it changes:
1. **Call screening is not the headline.** Verified [S]: Truecaller Family Protection (free, India, March 2026) and Google's on-device detection already cover scam-call alerts. Our unknown-caller guard (1B) stays as a bundled convenience, not the pitch.
2. **The wedge it proposes (I agree, and it matches your list):** (a) **money-moment detection** (long/unknown call or WhatsApp video, then a banking/UPI or remote-access app, then a payment alert); (b) **a human or human-like rescue** that calls the parent within minutes; (c) **autonomy-first trust** (parent consents, sees what the child sees, can pause, no call recording, no chat reading); (d) daily care. Features 2, 3 and 10 of the PDF are called the launch core.
3. **Payment alerts through notification access, not SMS** (PDF feature 1): read bank/UPI **debit notifications** for a fixed list of banking/UPI app packages and tell the child only "Rs X to <payee type> at <time>" above a limit. This is a cleaner signal than my email-forward idea (S5), which stays as the fallback. **Caveats [S, secondary]:** Play reviews notification access as a core-function permission; on Android 13+ sideloaded installs get "restricted settings" friction, so pilot through Play closed testing; never store notification text; whitelist packages. Needs a Play Console declaration and a real-phone test **[U]**.
4. **Rescue Desk**: the PDF puts a trained 24/7 human desk (Hindi and regional languages) at the centre. For Phase 1 I propose **AI-first rescue + human on call for pilot families**: Friday rings the parent within a minute of a HIGH signal with a calm script, rings the child, and a named human (you or a teammate) is paged for HIGH alerts during the pilot so we can measure false alarms and willingness to pay (the PDF's own "concierge Rescue Desk for 20 families" experiment). Cost target in the PDF: desk under 25% of revenue **[U]**.
5. **Features to add to the backlog from the PDF (not in my first list):** "I am being threatened" button (calls child + desk, reminds "India mein 'digital arrest' hota hi nahi"); **first-hour recovery playbook** (guided 1930 call, bank freeze/kill switch where available, police complaint draft, done together with the child; strong fit for our chat/call stack); **shame-free follow-up** script after a scam (ties to the care protocol); sibling plan (shared alerts, who-is-on-duty); bills/insurance/document vault with due dates; cancel-window rescue if the RBI one-hour hold goes live; later bank/insurer partnerships and an elder-scam intelligence network.
6. **Metrics the PDF proposes (month 12):** trial-to-paid 30%+, parents still active after 90 days 80%+, referrals 0.3+ per paying family, 1-2 bank/insurer pilots **[A, as targets only]**. **Price hypothesis:** Rs 299-599 a month (same as mine); one small competitor lists Rs 149 a month for a family plan with a "senior UPI guard" **[U]**.
7. **Validation plan (endorsed):** about 50 conversations (metro/NRI children 15, parents 60-80 15, scam victims 5, bank staff 3), a waitlist landing page measured via WhatsApp family groups, and the 20-family concierge month. I can build the landing/WhatsApp onboarding and the concierge tooling; the interviews are yours.
8. **Naming:** the PDF calls the product "Rio". Decide whether the product is Friday or Rio before any parent-facing wording or voice is produced.
9. **Honesty about the pitch:** the PDF also notes "WhatsApp video scams no app can screen" and "Google Play permission limits" as top risks; both match section 2 of this spec.

## 11. Founder decisions of 2026-11-04 (supersede earlier parent-consent text in sections 5, 6 and 8)
1. **Consent is given by the child (admin) on the parent's behalf** (`consent_basis = admin_on_behalf`). The parent is **notified and can always stop**: a WhatsApp voice note (and optional call) in their language on setup, a monthly "what is on" voice reminder, "Robin, band karo" by voice or text, or a widget tap. A parent STOP pauses every sensitive item at once, tells the child, and only the parent can resume. Risk flagged for legal review: DPDP has a guardian route for disability, not for a non-disabled adult parent **[S, research doc]**; Google Play requires notice and a persistent notification for monitoring apps **[S]**.
2. **Roles:** Admin (paying child, co-admin siblings), User (parent), Contact (second contact, alerts only).
3. **Parent channel = WhatsApp, voice-note-first**; calls for escalation, emergencies and when the parent rings Robin. Scam check = forward the message, link or screenshot to Robin. Needs Meta's WhatsApp token (blocked today, founder owns) and approved templates for messages outside the 24-hour window.
4. **Android app = thin widget** (press-to-talk microphone, press-and-hold SOS) plus an **optional protection pack** (call-screening role, notification access for bank/UPI notifications, remote-access-app queries, camera-in-use) installed by the child during an in-person setup, since Android needs the phone's holder to grant them.
5. **Voice-clone defence = call-pattern analysis**, not a safe word (optional per family, default off). Needs a transcript source: calls routed through Robin's line (screen-first or parent-triggered listen-in) with an audible disclosure; no third-party call recording on the parent's phone (Android 10+ blocks it and Play bans the workarounds **[S]**).
6. **Phase 1 additions:** human rescue desk (pilot, small), daily good-morning digest, festival graphics (original templates). **Sequenced later:** bill payment (reminder + approved link first), grocery ordering (official Zepto route), reading SMS (only as default SMS app; notification access is the substitute).
