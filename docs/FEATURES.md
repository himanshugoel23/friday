# Friday: the full feature list (13 Oct 2026)

Friday is a **personal assistant that acts for the user** ("Instinct"-style): it calls, messages,
compares, books and follows up. It is **not** a generic ask-anything chatbot (that is what Puch AI
is). A request outside what Friday does gets a polite redirect and goes on the wishlist.

**Privacy principle (founder, 13 Oct):** what Friday learns about a user (preferences, family,
addresses, favourite vendors) is used for THAT user only and is never used for or shown to anyone
else. The only shared learning is about how businesses talk (anonymised sentences, no user facts).

Status tags: **[BUILT]** in the code and tested; **[PENDING]** built but waiting for the founder's
audio approval or for wiring; **[PLANNED]** designed, not built; **[DECIDE]** needs a founder
decision.

## 1. Ways to ask
- WhatsApp text, WhatsApp voice note, a phone call to the Friday number, SMS. [BUILT: WhatsApp
  channel + simulator; real WhatsApp number waits for the business name] [PENDING]
- Hindi, Hinglish and English, in the user's own style. [BUILT]
- "My requests" list and a `status` text for any request. [BUILT]

## 2. Understanding the request
- Classifier into 22 categories (salon, clinic, lab, appliance repair, home repair, packers and
  movers, pest control, car service, restaurant table, hotel stay, banquet hall, coaching, PG,
  electronics, gym/yoga, event services, vet, wedding vendors, driving school, cab, laundry/tailor,
  florist/gift). [BUILT]
- Project manager: asks only the missing facts, one short question at a time: event type/date/
  venue, PG profile, cab trip, old phone for exchange, hotel dates, banquet details, items for
  movers, "at my venue or at the salon". [BUILT]
- Out-of-scope request: polite reply + wishlist. [BUILT: basic]
- Personal context: knows the user's name (and booking name), family members/beneficiaries,
  usual areas. [PARTLY BUILT]

## 3. Finding the vendor
- Google Places live search, "best AND near" with a hard radius per category; no vendor database
  yet. [BUILT]
- Eligibility checks (type match, phone present, open hours). [BUILT]
- Vendor memory per user (called before, outcome). [PARTLY BUILT]

## 4. The calls (Hinglish, Ritu voice on Sarvam)
- Scripts for 10 forms: salon, quote and slot, enquiry (coaching/gym/driving/events/weddings),
  home service visit (+ packers and movers), PG, cab, stock and price (electronics/florist),
  table, hotel, banquet. Founder-approved text in `docs/SCRIPTS_SPEC.md`. [PENDING: built as
  pending playbooks, audio approval needed before they go live]
- Name check, then the purpose hook, then details; fillers and varied acknowledgements; "thank
  you". [BUILT]
- Answers the business's questions ONLY from the user's facts, never invents. [BUILT]
- Interruptions: she stops when the business speaks; answers, then resumes with the first
  unanswered question. [BUILT: barge-in; resume PENDING]
- Never repeats a line again and again; numbers/times she says must come from the facts or the
  vendor's words. [BUILT]
- "Busy hoon": asks when to call back; retries at +1 h and +3 h, max 3 a day; tells the user if
  nobody picks up. [BUILT]
- Retry call keeps context and asks only what is missing. [PENDING]
- Never books a different time than the user asked; offers "around" then "nearest", then asks the
  user. [PENDING]
- Negotiation (push 1 / push 2 inside the user's range; never above the maximum); none for phones,
  banquets or restaurant tables. [PENDING]
- Confirmation call after "book kar do": books under the user's name, hold lines, visit
  confirmation. [PENDING]
- WhatsApp number capture with read-back; WhatsApp message to the business (template). [BUILT:
  capture; template send PLANNED]
- Payment: the user pays the business directly; UPI number read back, QR or bank details via
  WhatsApp; payment screenshot forwarded to the business. [PLANNED]
- Honest about being an assistant: says "virtual assistant" on request and "AI" truthfully the
  moment she is asked. [BUILT] [DECIDE: whether to say it up front]
- Latency: replies in about 1 s (Sarvam call-turn model, streaming voice). [BUILT]
- Recording + full transcript of every call (founder decision: no consent step for now). [DECIDE:
  recording storage bucket; the spoken recording notice line]
- Hold music / IVR handling and customer-care calls. [PARTLY BUILT; customer-care "hold fighting"
  hero feature PLANNED]

## 5. Results and decisions (outcome-based messaging)
- One acknowledgement when the request is understood, then silence until an outcome or a question
  only the user can answer. [BUILT]
- One comparison message with buttons: Book kar do / Negotiate karo / Chhod do. [BUILT: quotes
  flow] [PENDING: negotiate + confirm callbacks]
- 30-minute reminder if the user has not answered the busy-slot question, then the slot is let
  go. [PLANNED]
- Result sent on WhatsApp; SMS fallback if delivery fails. [BUILT]
- Shareable outcome page with transcript summary as proof. [PLANNED]

## 6. Proactive (Jarvis-style)
- Nudges, morning digest, reminders before an appointment; at most 3 messages a day or one morning
  digest; guardrails (quiet hours, caps, opt-out). [BUILT]
- Vendor-related proactiveness: re-confirm the day before, "your open quotes", unanswered
  questions, cadence-based suggestions (haircut every N weeks). [BUILT: triggers; PENDING:
  wiring to the new callbacks]

## 7. Personal memory (per user only)
- Preferences, favourite vendors, family/beneficiary profile, booking name, addresses. [PARTLY
  BUILT]
- "What do you remember?" and one-step delete. [PLANNED] [DECIDE: data stance, competitor lesson]

## 8. Trust, safety, limits
- Calls only to allow-listed numbers in testing; call window 09:00 to 19:00 IST; 3 requests per
  user per day; do-not-call list; kill switch; per-category switch. [BUILT]
- Never asks for or reads OTP / PIN / card details; never promises money; never pays. [BUILT]
- Delegated booking only inside the user's limits, with a code-level check. [BUILT]
- Vendor-side package: info page, call-back number, opt-out list. [DECIDE]

## 9. The learning loop (never changes spoken words on its own)
- Style dictionary that learns every correction: `friday playbook style-check|style-learn`. [BUILT]
- Every business utterance logged (numbers masked) into a review queue; you label, they become the
  test set; `friday learn report|label|eval|fewshot`. [BUILT]
- Fine-tuned small listening model after about 1,000 to 2,000 labelled sentences. [PLANNED]
- Answer bank: new business questions proposed automatically, you approve the wording first.
  [PLANNED]

## 10. Operations
- Deploy scripts, latency probe, health checks, recordings in an object store, cost tracking,
  weekly competitor update by the product-manager agent. [BUILT / PLANNED]

## 11. Phase 2: the chief of staff
- Gmail and calendar access with the user's permission: bills, travel, appointments, reminders.
  [PLANNED]
- Customer-care and hold-fighting calls (cable, ISP, bank), the hero feature competitors target.
  [PLANNED]
- Limited payments through UPI. [PLANNED]
- Integrations (Swiggy, Zomato MCP, vendor WhatsApp business agents). [PLANNED]
- Truecaller / after-call SMS for trust. [PLANNED]
- Legal read: TRAI/DLT, DPDP, WhatsApp Business rules. [DECIDE]

## 12. Ghost-inspired features, software only (founder, 13 Oct: no hardware, keep the features)
Source: docs/COMPETITORS.md "Update 2026-10-13 (c): ghost.ai". Friday never promises "never leaves
your device"; it promises "used only for you".
- **Privacy promise + "what Friday never does"** (5 lines, public, in the first message). [PLANNED:
  copy needs founder approval]
- **"What do you remember?" and one-step delete / export**, per user. [PLANNED]
- **Per-user encrypted memory**: identifiers and phone numbers are already stored encrypted and
  hashed; memory is never shared across users. [PARTLY BUILT]
- **Autonomy dial per category**: ask first / book within Rs X / never pay. [PARTLY BUILT: delegation
  limits and autonomy_settings table exist; the user-facing setting is PLANNED]
- **Every proactive nudge says why in one clause** ("kyunki aap har 5 hafte mein haircut karwate
  ho"). [PLANNED]
- **Credential firewall**: Friday never sees or speaks OTP, PIN, card; account identifiers are
  encrypted and only used inside an approved task. [BUILT]
- **Always-on background agents**: follow-ups, reminders, retries, re-confirm calls run without the
  user asking again. [PARTLY BUILT: task engine, retries, proactive engine]
- **Learns from the user's own email, calendar and files** (bills, trips, appointments), with
  permission, only for that user. [PLANNED, Phase 2]
- **Open and portable**: the user can export everything Friday knows. [PLANNED]
- Out of scope for now: hardware box, smart home, health data, local on-device models.

## 13. Future: devices and family care (founder, 14 Oct 2026; [PLANNED], not for the beta)
The no-hardware decision stands for now. Design choices to make today so this is easy later:
- **Person model:** a user can add family members (parents, children) as separate people. Each has
  their own consent, language, phone and data; the carer sees only what the person allows.
- **Reminder channel abstraction:** a reminder is "message to person X by channel Y" (WhatsApp, SMS,
  call, later a device speaker). Today's proactive engine already sends; add the channel type.
- **Parent care ideas:** medicine and appointment reminders by voice call in the parent's language,
  a daily "kaise ho?" check-in call, unanswered-call alert to the child, doctor and lab bookings by
  Friday, bill help, "emergency contact" flow. Never medical advice.
- **Device path (later):** a simple speaker or the parent's phone app/WhatsApp first; a dedicated
  device only after real demand. Keep an open interface (device sends events, Friday sends
  speech/text), not a locked design.
- **Consent and dignity:** the parent agrees to being called and can say stop; no secret
  monitoring; clear data limits; health data is high-risk (DPDP) so legal review first.

### 13b. On-device model (asked 14 Oct 2026; [PLANNED], after the beta)
- Friday's calls, WhatsApp and price lookups must run in the cloud, so Friday can never promise
  "nothing leaves your device". The promise stays "used only for you".
- Later, a Friday phone app could run a small model on the device for the most sensitive parts only:
  reading bill SMS and screenshots, the card wallet and spend patterns, contacts. Only the result
  ("electricity bill Rs 1,240 due 20 Oct") goes to the cloud, not the raw messages.
- Costs: an app to build and maintain (Android first), weaker small models (Hinglish quality must be
  tested), battery and storage use, slower updates. Not worth it before real users ask for it.
- Do first: ask the user to forward or photograph what we need; keep per-user encryption and delete.

### 13c. Own hardware, own GPU, own model, on-device training (asked 16 Oct 2026; [DECIDE])
Recommendation: not now. Reasons:
- Friday's core value (calling vendors, WhatsApp, Hinglish voice, comparing, booking) runs in the cloud
  whatever the device is; hardware does not make those calls better.
- Hardware startup cost and risk: design, certification, manufacturing minimums, inventory, shipping,
  returns, support, firmware updates. A few hundred units already needs a large budget and months.
- An own GPU box and own model: training or fine-tuning a Hinglish voice-agent model is expensive and our
  data (labelled calls) is still small. Better models arrive from vendors every few months; our edge is data,
  scripts and trust, not model weights.
- On-device training per user is research-heavy and drains battery/heat. Personalisation can be done in the
  cloud with per-user memory and retrieval (and later small per-user adapters), kept per user.
- Indian price sensitivity: most users will not buy a device; a phone app reaches them at zero hardware cost.
Staged path:
1. Software now (WhatsApp, calls, web voice, shared life state).
2. Phone app (voice session, Siri shortcut, Action Button, call forwarding receptionist).
3. Optional thin-client device later (speaker/pendant that streams to our cloud; no GPU) as an accessory
   when users ask.
4. A home "privacy box" with a local model only if a paying privacy-first segment appears.
Triggers to revisit: roughly 1,000+ weekly active users, repeated user demand for a device, a hardware
partner or funding earmarked for it, and a model/cost study showing local inference helps.
Privacy promise stays "used only for you", not "never leaves your device".
