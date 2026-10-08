# Friday - end-to-end workflows

Every journey below is **as it works today and as it is tested** in `tests/e2e/` (offline, on the
simulator). Legend:

* **[SIM]** = exercised only against the simulated world (fake LLM, simulated telephony / WhatsApp /
  SMS / directory / hotels). Nothing here has been verified live yet.
* **[LIVE-UNVERIFIED]** = code exists for the real provider, never run against it.
* **[NOT BUILT]** = designed, not implemented.
* **[BUG-n]** = a defect found by QA, see `docs/QA_REPORT.md`. The journey is described as intended,
  with what actually happens noted.

Friday only speaks WhatsApp / voice / SMS. There is no app, so everything below is a chat message or
a phone call. Example messages are Hinglish because that is what users send; the fake LLM understands
the phrasings used in the tests.

---

## 1. Onboarding (`tests/e2e/test_onboarding.py`)

1. User messages the WhatsApp number: `hi`. (Beta is invite-only: a new number is asked for a code
   `FRI-XXXXXX` and waitlisted if it has none. Admin phones skip this.)
2. Friday asks name, city, language (English / हिंदी / Hinglish buttons) and tone (playful / formal).
3. **Consent gate.** Friday says what she stores (name, city, tasks, call recordings, in India), that
   she announces she is an AI on every call, and that `delete everything` erases it all. She asks
   "18+ and agree?". Only an explicit "I agree" records the DPDP consent. "Not now" stays at this step,
   asks for no PIN, and no task can be created.
4. **PIN.** 4 digits, typed twice. Trivial PINs (1234, 1111) and mismatches are rejected. The PIN is
   never echoed, never sent to the LLM, stored only as a peppered Argon2 hash; Friday asks the user to
   delete the message.
5. Optional: circle (`mere papa Suresh, +91 98111 11111, Hindi, Delhi`) and places
   (`home: Indiranagar, office: Bellandur`). Both can be skipped. Circle members are **not** messaged.
6. Optional first task ("ek call jo taal rahe ho?") - "later" finishes onboarding.

## 2. How Friday gets a vendor's phone number

Friday never invents a number. The engine (`tasks/engine.py::_business_target`) tries, in order:

| # | Source | User says | What happens |
|---|---|---|---|
| 1 | Shared contact | (taps a WhatsApp contact card) `/contact +91...` in the simulator | the number is used as given |
| 2 | Typed in the message | `Urban Trim Salon +918040001013 mein haircut book karo kal shaam` | the number is used, business saved to memory |
| 3 | Memory | `wahi salon jahan pichli baar gaya tha` / a name already used before | `known_for_user` hit, no search |
| 4 | Name lookup via Places | `Looks Unisex Salon mein haircut book karo kal shaam` | directory text search (Google Places in live, simworld in simulator); first hit with a phone is used. **[BUG-5]** there is no name check: "Urban Trim Salon" dials "Looks Unisex Salon" in the simulator. Always give the number for small shops until fixed |
| 5 | Discovery | `Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo` | see section 8 |
| 6 | Ask the user | `Dr. Mehta ko call karo` (unknown) | "What's their number? You can share the contact too." task waits in NEEDS_INFO |

**Number rules** (all tested): E.164 India numbers only; private-looking mobile numbers need a
confirmation ("Is this a business?") and are capped across users (SECURITY-21); DNC numbers are never
called again, pool-wide (section 15); customer-care calls use only the **official** number list (the
user-supplied number is replaced if it is not on it).

**Scam check.** Before the first call to a number, `NumberVerifier` combines the official-numbers list,
listing consistency, call history and the scam list. A scam number (`Airtel Helpline (unofficial)`)
is refused with an explanation; an unknown number is called with the usual disclosure.

## 3. How Friday gets a location (no app)

| Situation | User does | Result |
|---|---|---|
| Typed area | `Indiranagar mein AC repair ...` | geocoded by the city/area text (tested) |
| WhatsApp location pin | taps attach > Location (simulator: `/pin 12.97,77.64`) | "Location mil gayi. Yahin aas-paas dhundhungi." The pin is stored. **[BUG-15]** `yahan ke paas ...` afterwards does not use the pin |
| Maps link | pastes `https://maps.app.goo.gl/...` | resolved via the geocoder (`resolve_maps_link`); saved as a place |
| Saved places | `save my office: Indiranagar, Bengaluru` (also during onboarding) | "Office save kar liya" |
| "near my office" | `mere office ke paas AC repair karne wala dhundo` | the saved office is the search origin (tested) |
| "papa ke ghar ke paas" / beneficiary's place | the parent's saved place (`Person` address) is the origin | resolved by `resolve_references`; ask once with up to 3 buttons when ambiguous **[SIM]** |
| Nothing known | - | Friday asks for a pin or area; she never guesses a city |

## 4. Booking with the call-back approval rule (`test_booking_approval.py`)

The founder rule: **no commitment on the first call.**

1. `Looks Unisex Salon mein haircut book karo kal shaam`
2. Friday: "Lag gayi call: Looks Unisex Salon, Tue 6 Jan, 5 PM-8 PM. Aapke haan bole bina kuch book nahi hoga."
3. The call (first words are always the AI disclosure):
   ```
   callee : Hello, Looks salon, boliye
   friday : Hi, main Friday hoon, ek AI assistant, Rahul ki taraf se call kar rahi hoon.
   friday : Rahul ke liye haircut ka slot chahiye tha, Tue 6 Jan, 5 PM-8 PM. Kaunse slots available hain?
   callee : 4pm, 6pm, 7:30pm available hai.
   friday : Shukriya ji. Main Rahul ji se confirm karke 10-15 minute mein call back karti hoon.
            Tab tak 4 PM / 6 PM hold kar sakte hain?
   ```
   Outcome `PENDING_APPROVAL`, task `AWAITING_APPROVAL`.
4. WhatsApp: "Looks Unisex Salon (Rs 400): 4 PM, 6 PM, 7:30 PM. Kaunsa book karun?" with buttons
   `4 PM, Rs 400` / `6 PM, Rs 400` / `None of these`. **[BUG-14]** the sentence appears twice.
5. User taps `2`. Task goes to `CONFIRMATION_CALLBACK`; a second call from the **same Friday number**
   says the approved terms and the business confirms. Task `COMPLETED`; user gets "Ho gaya: ...".
6. `None of these` -> polite cancel; the business gets a registered template message, no call.
7. No reply -> nothing is booked; the task waits (it does not expire or nag: see QA report).
   **[BUG-9]** the confirmation summary can show a booking reference as a price (Rs 1,96,353).

## 5. Delegation (`test_delegation_midcall_retries.py`)

`kal shaam 4-7 ke beech koi bhi slot, Rs 800 tak, aap decide karo` grants a **Delegation** (time window +
price ceiling). Within it Friday may confirm on the first call; outside it (price Rs 400 > a Rs 300
limit) she falls back to the call-back rule. The delegation applies to that task only (or to every
instance of a recurring rule). **[BUG-1]** a one-off delegation with a time window never confirms on the
call in the simulator because the call policy does not supply the slot time to the safety gate; it
always degrades safely to the call-back flow (and repeats the blocked line up to 10 times, BUG-17).
A recurring rule with a price-only delegation does confirm on the call.

## 6. Mid-call clarification

While the business is on hold, Friday may ask the user: WhatsApp "Salon pooch raha hai: beard trim bhi
chahiye?" with `Haan` / `Nahi`. The task is `AWAITING_USER`; the business hears a polite hold line
("Hold karne ke liye dhanyavaad...") - never a filler word. The answer is injected as a system turn and the
call continues. If the user does not answer within `FRIDAY_MID_CALL_QUESTION_TIMEOUT_S` the call wraps up
politely and the task asks again later. The fake policy never raises a clarification by itself, so the
test scripts the LLM turn.

## 7. No answer and retries

`Frosty Air Solutions ko call karke AC repair ke liye bolo` (always busy): attempt 1 now, then +5 min,
then ~+1 h. The user gets **one** message ("isn't picking up, I'll keep trying") and, after the third
failure, one message with three buttons: **Later today / Tomorrow / Another business**. "Tomorrow"
creates a scheduled task at 10:00 IST next day, inside the call window. (The options were swallowed
before the QA fix to `ANSWERABLE_STATUSES`.)

## 8. Discovery -> shortlist -> parallel quotes -> comparison -> booking

1. `Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo`
2. Shortlist (rated, with one review snippet): "1. CoolCare AC Services: 4.7 (320) ... Call all 3 / Cancel".
   No call is made before the user taps.
3. Three child quote tasks run in parallel; unreachable shops are cancelled once the others answered.
   Quote calls never commit.
4. Comparison: "Chill Point AC Repair: Rs 550 - Sun 10 AM / CoolCare: Rs 699 ... Meri pick: Chill Point".
5. User taps a button -> a booking task (confirmation call with the chosen terms). Parent `COMPLETED`.
   **[BUG-2]** with the real repositories fan-out fails ("I couldn't get any offers") because `Task.role`
   is not stored; the e2e suite shims it to verify the rest.

## 9. Stock hunt

`Kothrud mein kis chemist ke paas Dolo 650 stock hai? sab ko call karo`: calls up to 3 shops at a time and
stops at the first yes ("Mil gaya. ... (Checked 2 places.)"). **[BUG-8]** a shop that did not understand the
question can be reported as having stock.

## 10. Recurring booking

`Looks Unisex Salon mein har mahine ki 5 tareekh ko haircut book karna, Rs 500 tak aap decide karo` ->
"Series set up. Next: Thu 05 Feb, 10:00 AM". On the day an instance booking runs under the standing
delegation (confirms on the call if <= Rs 500) and the series schedules the next cycle.

## 11. Customer care: IVR, hold, ticket, follow-up (`test_care_hotel.py`)

1. `Airtel customer care ko call karo, mera broadband band hai, complaint darj karo`
2. Friday uses the **official** number only and shows a pre-call summary: number, ask, "I'll share:
   nothing", "Never shared: OTPs, PINs, CVV, passwords." Buttons `Go` / `Cancel`.
3. The call walks the IVR (`DTMF: 2`, `3`), types an approved identifier masked in logs (`DTMF: ......3210#`),
   waits on hold with **zero** LLM calls (user gets "On hold, ~7 min" and "Still on hold, 5m 0s"), then
   talks to the human agent (disclosure first) and gets the ticket `SR66919230 ... within 48 hours`.
4. Report with the ticket number, transcript and recording link.
5. Limits found: **[BUG-10]** saved account identifiers are never offered/approved for a call, so IVRs
   asking for the registered number end with "I can't do OTP verification; call +91... then press 2, 3";
   **[BUG-11]** the 48-hour follow-up is never scheduled. A bank line that demands an OTP is never given one.
6. Saving the identifier needs the PIN: `my Airtel registered mobile number is 9876543210` -> PIN -> saved.

## 12. Hotels (hybrid) and reconfirm

`Udaipur mein Lake Pichola ke paas 2 raat ka homestay chahiye, 12 Feb se 14 Feb, 2 log`: shortlist of
stays (online rates from the hotel provider + direct calls to the property) -> comparison
"Lakeview Homestay: Rs 4,200 -> Rs 2,800" -> user picks -> booking recorded -> a `RECONFIRM` task is
scheduled for 10:00 IST the day before check-in. **[BUG-12]** the reconfirm call is blocked by the long-digit
guard and pulls the user into the call. Real booking through Expedia Rapid is a stub (`ProviderError("not enabled")`).

## 13. Family: booking for a parent, wellbeing check-ins (`test_family_location.py`)

* `add my papa Suresh Verma +911140001016 Hindi, rehte hain Delhi` saves the person. Papa is **not**
  contacted.
* One opt-in template is sent to Papa by `Notifier.request_person_opt_in` (in his language). He replies
  `haan`; Friday tells the owner "Suresh said yes". Only then does he get booking confirmations
  (minimal content: business and time, no price). **[BUG-13]** nothing in the product calls the opt-in
  request, and the separate check-in consent is never recorded.
* `papa ko roz subah call karke haal chaal poocho` -> "Pehle Papa se ek baar permission lungi". With consent a daily
  09:00 IST series runs; the call opens in Hindi with the AI disclosure, and a health concern raises an
  `Alert:` to the user with "Call them now / Call their doctor / Listen to recording" and 112/108 advice.
* Circle members can only opt in/out; anything else they send is ignored (security test).

## 14. Business call-backs, missed calls, late call-backs (`test_callbacks.py`)

* A business that missed Friday's call rings the number it saw. The matcher needs the caller ID to equal
  the number we called **and** the dialled Friday number to be the one used; then the brief carries the
  context ("We called you earlier on behalf of Rahul about ...") and the **approval rule still holds**.
* An unknown caller gets a generic greeting, a message is taken, nothing about any user is revealed.
* A missed call from a known business pulls the next attempt forward - one call, not a flurry.
* A late call-back after the task was cancelled/resolved should "close the loop" (thank, no commitment, retries
  cancelled). Retries are cancelled and nothing is committed, but **[BUG-7]** the call is run as a fresh enquiry.

## 15. Number pool and DNC

Friday owns a pool of caller IDs (`FRIDAY_NUMBERS` / `SARVAM_CALLER_IDS`). A business always sees the
**same** number (sticky per business, verified across users); health scoring cools or retires numbers.
`dnc_request` ("please don't call again") blocks the business **pool-wide** - rotation is never used to get
around it; the e2e test blocks the Looks number and no user can reach it.

## 16. Proactive nudges (`test_proactive_delete_pool.py`)

Appointment reminders, date-based nudges ("rent due tomorrow - Main handle karun?"), stale-task checks.
Guardrails: max 3 unprompted per IST day (urgent reminders and safety alerts exempt), none 22:00-08:00 IST
(they are scheduled for the morning; safety alerts bypass), `Not needed` dismisses and is learned.

## 17. Delete everything

`delete everything` -> PIN -> type `DELETE`. Wrong PIN or no confirmation deletes nothing. Afterwards the
user, tasks, calls, recordings (local and object store) are gone and the number is no longer known.

## 18. Future: public front-door number **[NOT BUILT]**

A public Friday number anyone can call or message (no invite) is designed but not implemented: it would
route an unknown caller to an AI front desk that verifies the person (OTP over WhatsApp to a number they
own), creates a waitlist/invite, and never reveals anything about existing users. Today an unknown caller
only gets the generic message-taking greeting (section 14) and an unknown WhatsApp sender gets the invite
prompt. Requirements before building: DLT-registered voice header, Truecaller-for-Business/CNAP listing,
abuse rate limits (`abuse_rate_limit_enabled`), grievance-officer path.

---

### What is simulated vs verified live

| Area | Status |
|---|---|
| LLM (Claude) | **[LIVE-UNVERIFIED]** - all e2e runs use the deterministic fake |
| STT/TTS (Sarvam) | **[LIVE-UNVERIFIED]** |
| Telephony (Vobiz via the Sarvam adapter) | **[LIVE-UNVERIFIED]**; several `TODO(<doc page>)` markers open |
| WhatsApp Cloud API + templates | **[LIVE-UNVERIFIED]** (signature/payload parsing tested on fixtures) |
| Google Places / Geocoding | **[LIVE-UNVERIFIED]** (recorded payload tests only) |
| Everything in sections 1-17 | **[SIM]** end to end |
