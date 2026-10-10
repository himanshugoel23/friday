# Playbook: salon booking (v6, founder script)

Friday phones a salon for a user. The PRICE comes first. Then, only when the owner delegated the decision, she asks about a slot and may book it. Everything is Roman-script Hinglish; the *names* inside the lines (salon, user) are Devanagari for a better voice. No language switching: if the salon answers in pure Hindi or English she still replies in Hinglish. The model never writes Friday's words, it only classifies what the salon said.

## Inputs

`business_name` / `user_first_name` (Roman, for logs) and the derived `business_name_spoken` / `user_spoken` (Devanagari + approved glossary words, e.g. "श्रेया saloon"); `honorific` (default **sir**, overridable: madam / ji); `services` (a list in the owner's words, spoken as "haircut", "haircut aur beard trim", "haircut, beard trim aur facial"; the older single `service` still works); `playbook_mode` (`book` | `quote_only`); `date_window` ("aaj shaam 5 baje" or "kal shaam"); `fallback_when` (a second specific time, e.g. "kal shaam 5 baje", book mode only); `budget`; `stylist_pref`; `negotiate` and `explore_options` (both off unless the owner says so).

**Mode** comes from the owner's instruction: `playbook_mode: quote_only` (the default, and the only possible mode when no delegation exists) or `book` (only when the task carries a delegation and there is a time to ask for). Outputs: `slot_free`, `offered_slots`, `slot`, `price_inr`, `stylist`, `advance_needed`, `outcome`.

## The script

**Opening (spoken first by the runner, then she waits):**
> Hello, kya meri baat {business_name_spoken} se ho rahi hai?

**After the salon says yes ("haan ji") - one turn, both modes start the same way:**
> Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant. {user_spoken} {honorific} ko {services_spoken} karwana hai, toh unki booking ke regarding call kiya hai. Toh sir, ek baar bata sakte hain inke kya charges rahenge?

(quote_only: "...toh **uske charges** ke regarding call kiya hai.") No duration question, no read-back of the price.

### QUOTE_ONLY mode (the owner only asked for a price check)
After the price, no availability or slot question at all:
> Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.

Outcome `QUOTE_COLLECTED` (call outcome `partial`): `price_inr` is in the collected values and the quote, so the task engine reports it to the owner like any finished call. If the salon will not give a price on the phone, the same line is spoken and the outcome is `UNCLEAR`.

### BOOK mode (a delegation exists)
After the price (a stylist preference, if the user named one, is asked first: "Agar {stylist_pref} available ho to unse hi karwana hai, warna koi bhi chalega."):
> Theek hai sir. Kya {date_window} ka slot mil sakta hai?  (e.g. "aaj shaam 5 baje")

* **Free** ("ho jayega" means that time) and the code-level check passes:
  > Theek hai sir, toh {slot} ka slot book kar lijiye. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.
* **Busy** and the task names a fallback time (same price ceiling):
  > Achha, nahi ho sakta. Toh kya kal ka slot available rahega?
  and if yes:
  > Theek hai sir, phir {slot} ka slot book kar lete hain. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.
* Busy and no fallback (or the fallback is busy too): "Toh kaun sa time free hai?" (two times, "Toh kaun se do time free hain?", only if the owner wants to compare). Anything the salon offers is only OFFERED (`SLOT_OFFERED`), never booked.
* Nothing free: "Koi baat nahi, main {user_spoken} {honorific} ko bata dungi. Shukriya." (`NO_SLOT`).
* She may not book (no delegation, price over the ceiling or budget, price unknown, an advance wanted, a time that is not one of the delegated times): "Theek hai, shukriya. Main {user_spoken} {honorific} se poochh kar aapko batati hoon." (`SLOT_OFFERED`).

The two booking lines are the ONLY lines that book. They are spoken only when the delegation exists AND `check_commit` passes (price within the ceiling, the time is one of the delegated times). The delegation for "today 5 pm OR tomorrow 5 pm" holds both times and ONE price ceiling; times between them are outside it (`Delegation.slot_windows`).

### Asked about being an AI (any step, any phrasing)
She does not volunteer it. If the salon asks ("AI ho?", "robot hai?", "insaan ho?", "real person?", "machine?", "bot?", "computer?", "recorded hai?", English or Hinglish), the very next thing she says is:
> Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.

and the call goes on (the question that was pending is asked again). She never denies it, claims to be human or dodges the question; this is enforced in code (see docs/PLAYBOOKS.md, "The `ai_disclosure: on_request` guarantee"). After a hold, the runner's short re-intro is "Main Friday hoon, {user_spoken} {honorific} ki virtual assistant." **Founder to do: check Sarvam's and Vobiz's terms on AI disclosure.**

### Other branches (unchanged behaviour)
* "Kaun bol raha hai?" / not heard (before the identity answer): "Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?"; later: the short introduction, then the pending question again.
* Wrong name / wrong number: "Maaf kijiye, galat number lag gaya. Shukriya." No purpose is ever said. Busy: "Koi baat nahi, main baad mein call karti hoon. Shukriya." Do not call again: "Theek hai, hum dobara call nahi karenge. Shukriya." (number blocked). Rude: "Maaf kijiye, pareshan karne ke liye. Shukriya."
* Hold: wait silently (max 60 s), then ask again. Did not hear: "Sorry, ek baar phir?" (max 2 per step, then "Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.").
* Off-script: "Yeh main {user_spoken} {honorific} se poochh kar bataungi." Customer's number: "{user_spoken} {honorific} ka number main share nahi kar sakti." OTP/PIN/card: "Yeh jaankari main share nahi kar sakti."
* No advance or cancellation question by her. Only if the SALON raises an advance / booking amount / cancellation fee: "Advance main abhi nahi de sakti, {user_spoken} {honorific} se poochh kar bataungi." (never booked). No negotiation unless the owner said so (book mode only).

## Rules the engine enforces in code, whatever the lines say
Never confirm, pay or give a deposit; never say OTP/PIN/card; max 4 repeats of one question; max 180 s and 30 turns; stop on a do-not-call request; the booking lines only with a delegation and a passing price/slot check; AI answered truthfully on request.

## Outcomes
`QUOTE_COLLECTED` (price check done) | `SLOT_OFFERED` (waiting for the user) | `BOOKED` (only if delegated and committed) | `NO_SLOT` | `CALL_BACK_LATER` | `WRONG_NUMBER` | `UNCLEAR` | `REFUSED` (DNC) | `NO_ANSWER`.

## Hear it, check it, test it
* `friday playbook preview salon_booking --mode book --business "Shreya Salon" --user Himanshu --services "haircut, beard trim" --when "aaj shaam 5 baje" --fallback-when "kal shaam 5 baje" --branch busy_then_fallback --out var/preview/` renders the real lines into one wav (see docs/PLAYBOOKS.md).
* `friday tts-check "Shreya Salon" "Looks Unisex Salon"` flags names that need a human listen.
* `friday livecall --playbook salon_booking ...` can never book unless `--book-now` (with `--when` one specific time and `--budget`); `--fallback-when "kal shaam 5 baje"` adds the second time. `deploy/call-me.sh` wraps it.
