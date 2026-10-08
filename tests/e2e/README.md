# End-to-end suites

These tests drive the **real app** (`Runtime` + inbound pipeline + brain on the deterministic
fake LLM + task engine + simulated telephony / directory / hotels / geocoder + simulator
WhatsApp channel) on a throw-away SQLite file and a `FakeClock`. No network, no keys.
The directory runs in about 40 s. `uv run pytest tests/e2e`.

* `harness.py` - `Friday` (app driver) and `Party` (one phone: `say`, `texts`, `tasks`, `calls`).
* `conftest.py` - fixtures. A template DB with Rahul (Bengaluru) and Priya (Pune) onboarded is built
  once and copied per test. `friday` shims `Task.role` persistence (BUG-2) so the fan-out
  journeys can still be verified; `raw_friday` is the unshimmed app (proves BUG-2).
* `test_bugs.py` - strict xfails for bugs found by QA (see `docs/QA_REPORT.md`).

## Journey coverage

| Journey | File / test |
|---|---|
| Onboarding: consent, PIN, language, optional circle/places | `test_onboarding.py` |
| Booking -> PENDING_APPROVAL -> approval -> confirmation call-back | `test_booking_approval.py` |
| Disclosure first on every call | `test_booking_approval.py::test_every_call_opens...` |
| Delegated booking within / outside limits | `test_delegation_midcall_retries.py` (within: BUG-1 xfail) |
| Mid-call clarification question | `test_delegation_midcall_retries.py` |
| No-answer retries (3, one notification, final options) | `test_delegation_midcall_retries.py` |
| Business call-back, missed call, late call-back / close the loop | `test_callbacks.py` |
| Discovery -> shortlist -> parallel quotes -> comparison -> booking | `test_discovery_stock_recurring.py` |
| Stock hunt, first match | `test_discovery_stock_recurring.py` (correct winner: BUG-8 xfail) |
| Recurring booking | `test_discovery_stock_recurring.py` |
| Customer care: IVR, hold, ticket, follow-up | `test_care_hotel.py` (follow-up: BUG-11) |
| Hotel hybrid + day-before reconfirm | `test_care_hotel.py` (reconfirm: BUG-12) |
| Booking for a parent, opt-in, own-language confirmation | `test_family_location.py` |
| Wellbeing check-in with consent + alert | `test_family_location.py` (consent request: BUG-13) |
| Saved places, "near my office", location pin | `test_family_location.py` ("near me": BUG-15) |
| Proactive cap, quiet hours, dismissal | `test_proactive_delete_pool.py` |
| Delete everything (PIN + confirm) | `test_proactive_delete_pool.py` |
| Number pool: sticky number per business, pool-wide DNC | `test_proactive_delete_pool.py` |

## Simworld coverage (QA-2)

`friday/simworld/world.json` has 32 businesses/people; `test_world_coverage.py` asserts each row.

| TaskType | Sim entries |
|---|---|
| booking / reschedule / cancel_booking / reconfirm | Looks Unisex Salon, Urban Trim Salon, Glamour Studio (hostile to AI) |
| healthcare | Dr. Sharma (Marathi->Hindi, asks "are you AI?"), Dr. Rao (voicemail greeting), Dr. Iyer (morning-only, closed hours), Smile Dental (voicemail) |
| enquiry / quote / discovery | CoolCare, Chill Point (Kannada->Hinglish), Frosty (busy), SafeShift Packers (asks advance) |
| order / stock_hunt | Wellness Pharmacy (miss), City Chemist (hit), Lifeline Medicos (insulin, missed-call), Biryani House (mutton sold out) |
| service_coordination / status_chase | Raju Plumber (hangs up after 6 turns), QuickFix (2 no-answers), Perfect Fit Tailors (alt line) |
| complaint / customer_care | Airtel (IVR + 420 s hold + ticket), Kaveri Bank (agent asks OTP), Skyline Broadband (2400 s hold), Fake Airtel (scam number) |
| rental_hunt | Pune and Chennai landlords (Marathi, Tamil) |
| hotel_booking | Lakeview Homestay (24 h hold, negotiation), Misty Woods (6 h hold, Kannada), Old City Haveli (no answer) |
| wellbeing_checkin / running_late | Mummy (Marathi), Papa (health alert), Nani (no answer) |
| recurring_booking | any booking persona with a delegation (Looks) |
| callback_later / late call-back | Spice Route Restaurant, Urban Trim (rings back after 30 min) |
