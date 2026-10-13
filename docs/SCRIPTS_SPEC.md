# Approved call scripts (founder review, 13 Oct 2026): the source of truth

`{...}` = filled per call. `{ack}` = a varied acknowledgement (engine placeholder; never repeats
within the last two). Hinglish, spoken like a person. All lines pass the style rules
(`friday/playbooks/style/style.yaml`): fillers, purpose hook first, natural endings, everyday
English words, "thank you" (never dhanyavad/shukriya).

## Global rules (every script)
1. Order: confirm the business name -> ONE short purpose line (the hook) -> wait for "haan ji,
   bataiye" -> details. Hook: "Ji sir, actually maine aapko {services} ke regarding call kiya tha."
2. Fillers always; acknowledgements vary (`{ack}`).
3. The business asks something -> Friday answers from the USER's facts only (never invent; else
   "Yeh main {Himanshu sir} se poochh kar bataungi."), then resumes with the first unanswered
   question. A question already answered is never asked again. The same line never repeats.
4. "Busy hoon": she asks "Ji koi baat nahi sir, main kab call kar sakti hoon?" and notes the time.
   Retries are +1 h and +3 h, max 3 attempts; the retry opens "Ji sir, actually maine pehle
   {services} ke regarding call kiya tha, bas ek-do cheezein reh gayi thi." and asks ONLY what is
   missing (engine: `resume`, `prior_*`, `skip_when`).
5. "WhatsApp pe bhej do": "Theek hai sir, ek baar aap please WhatsApp ka number confirm kar sakte
   hain?" -> they say "yahi number hai" (use the number called) or give digits -> she reads them
   back: "{captured_spoken}, yahi number hai na?" (YES -> "Okay sir, main aapko WhatsApp kar deti
   hoon."; NO -> asks once more). Engine: intents GIVES_NUMBER / SAME_NUMBER, `{captured_spoken}`.
   If they have no WhatsApp: the details are said on the call and read back in groups.
6. Advance / booking amount: NEVER asked by Friday on her own; only if the USER's request asks
   for it (`q_ask_advance`): "Achha theek hai sir, ek baar booking amount kitna lenge?". If the
   BUSINESS raises it: "{ack}, ek baar advance ya booking amount kitna hoga?" then "Theek hai sir,
   main ek baar {Himanshu sir} ko bata deti hoon, wo aapko advance payment initiate kar denge.
   Thank you." (The user pays the business directly; Friday never pays. Payment details: UPI
   number/ID spoken + read-back; QR or bank details by WhatsApp; no WhatsApp -> said on the call.)
7. Recording notice line exists ("Yeh call quality ke liye record ho sakta hai.") but is only
   spoken when `recording` is on; the founder has not decided whether to keep it.
8. Friday NEVER books a different time/date than the user asked without the user's OK: busy ->
   "{ack}, toh koi {8 baje} ke around ka slot available ho?" -> "Toh sabse nearest kaun sa slot
   available hoga?" -> no booking -> "{ack}, main {Himanshu sir} se confirm karke aapko thodi der
   mein call back karti hoon." ("thodi der mein" / "paanch minute" is a phrase, not a timer; she
   calls back only after the user answers.) Engine flag `alt_offered`.
9. Booking close (delegated, requested time free): "{ack}, toh aap {slot} ka booking
   {user_full_spoken} ke naam se book kar lijiye. {slot_time} se pehle main ek baar confirmation
   ke liye call kar lungi. Thank you."
10. Callbacks are modes of the same playbook (`playbook_mode`): `negotiate` (push 1 at
    `target_price`, push 2 at `push2_price`, never above `max_price`; if the business price <=
    target finalise; after two pushes record their final price) and `confirm` (finalise what the
    user approved: "{Himanshu sir} ne confirm kar diya hai, toh ..."). Negotiation lines:
    push 1: "Toh sir, {Himanshu sir} se baat ho gayi hai, price thoda humare budget se upar hai.
    Humara budget {target_price} ka hai, toh isme bataiye kuch ho sakta hai kya?"; push 2:
    "Achha sir, thoda aur dekh lijiye na, kya {push2_price} tak ho payega?"; not agreed:
    "Theek hai sir, main ek baar {Himanshu sir} se final confirmation leke aapko call back karti
    hoon." NO negotiation for: phones/electronics, banquets, restaurant tables.
11. The price-check close: "{ack}, main ek baar {Himanshu sir} ko bata deti hoon, aur thodi der
    mein aapko confirm karke batati hoon."

## 1. salon_booking (live script exists; pending v7 built)
Hook "...{services} ki booking ke regarding..."; price "Toh sir, {services} ke estimated kya
charges rahenge?"; slot "{ack}, toh {date_window} ka slot booking ke liye aapke paas available
hoga?"; busy/nearest/close per global rules; confirmation call (mode confirm).

## 2. quote_and_slot (pending v7 built): clinic, diagnostic lab, car service, vet, laundry/tailor
As salon with `price_word` (fees for clinic and vet) and doctors say "appointment" (`q_appointment`).
"Aake dekhna padega": ask a rough range ONCE ("Achha, toh koi estimated range bata sakte
hain?"), then close. WhatsApp / advance / free consult / depends per global rules.

## 3. enquiry: coaching, gym/yoga, driving school, event services, wedding vendors
Coaching, gym, driving (`price_word` fees): hook "...{services} ke baare mein jaankari ke liye
call kiya tha"; "Toh sir, {services} ki estimated kya fees rahegi?"; batch timing ("Toh batch ka
timing kya rehta hai?", their words only noted); demo class ("Achha toh sir, kuch demo class bhi
mil sakti hai?"). Events and weddings (`q_date`, `price_word` charges): the user's event DATE is
fixed: hook, then "Toh sir, {event_date} ko aap available hain?"; available -> "{ack}, toh
{services} ke estimated kya charges rahenge?"; not available -> "{ack}, main ek baar {Himanshu
sir} ko bata deti hoon. Thank you." When they ask "event kya hai, kab hai, kahan hai": answer ONLY
from facts: "Ji sir, {event_type} hai, {event_date} ko, {event_venue}, {event_city} mein." (and
guests). Parlour/makeup at the venue follows this event style (adds people_count and "Achha,
aane-jaane ka alag charge rahega kya?").

## 4. home_service_visit: appliance repair, home repair, packers and movers, pest control
Hook "...{services} ke kaam ke regarding..."; "Toh sir, visit ka estimated charge kitna rahega?";
"Achha theek hai, aur kaam ka rough estimate kitna aa jata hai?"; "Achha toh sir, {date_window}
visit ho sakta hai?" (yes -> "Achha, aur aane ka time kya rahega?"; no -> "Achha okay. Toh kab tak
aa sakte hain?" their words only). Packers/movers: they ask quantity/from/to/floor: answer from
`items_description`, `from_place`, `to_place`, `floor_info`. Negotiation callback allowed (push 1,
push 2). Confirmation call: "Theek hai sir, {Himanshu sir} ne confirm kar diya hai. Main aapko
WhatsApp pe final address aur location share kar deti hoon. Ek baar WhatsApp number confirm
karenge?" (number rule) then "Theek hai sir, main aapko WhatsApp pe final details share kar deti
hoon. Thank you." The address is never spoken.

## 5a. pg_rental
Hook "...PG ke room ki enquiry ke regarding..."; "Toh sir, ek baar bata sakte hain room ka kya
rent rahega?"; they ask single/double/triple -> "Ji sir, {sharing_type} chahiye."; "{ack}, toh
{sharing_type} ke estimated kya charges rahenge?"; then one at a time: furnishing ("aur room
mein kya kya furnishing rahegi?"), "Aur usme khana ya mess include rahega?", "Aur electricity ka
bill kaise rahega?", "Aur security deposit kitna rahega?", "Aur notice period kitna rehta hai?";
who is it for -> from `occupant_*` ("{occupant_name} ke liye hai, {occupant_from} se hain,
{occupant_job} mein, abhi {occupant_location} mein rehte hain"); "{ack}, aur {move_in_date} se
room chahiye hoga, {sharing_type}."; close per rule 11. CALLBACK (mode negotiate, then visit):
push 1 ("Sir, {Himanshu sir} ka budget {target_price} ke around rahega, isme manage ho payega?"),
push 2 (`push2_price`), then visit: "{ack}, room dekhne ke liye kab aa sakte hain?" confirm date and
time: "Theek hai sir, toh {visit} aa jayenge." Close: "Achha theek hai sir, thank you. Main visit se pehle ek
baar call kar lungi."

## 5b. cab_booking
Hook "...cab booking ke regarding..."; then she volunteers: "Ji, hamko {from_place} se {to_place}
jana hai, {pickup_time} ki cab book karani hai, hum {people_count} log hain."; "Toh sir, iska
total estimated kitna charge rahega?"; "Aur kaun si gaadi milegi isme?"; "Toh sir, is charge mein
sab kuch include rahega na? Toll, khana-peena, driver ka khana, charges wagairah?"; if not
included: "Toh sir, estimated kitna toll lagta hai isme, kuch andaza hai?"; "Toh sir, {pickup_time}
ke liye cab available hogi na?"; close rule 11. Callbacks: negotiate (rule 10), confirm: "{Himanshu
sir} ne final confirm kar diya hai, toh hum {vendor_price} pe final karte hain. Toh sir
{pickup_time} ki booking aap {user_full_spoken} ke naam se kar lijiye. Main aapko WhatsApp par
pickup address share kar deti hoon. Ek baar apna WhatsApp number confirm kar dijiye." (number rule)

## 6. stock_and_price: electronics dealer, florist/gift
Hook "...{services} ke regarding..."; "Toh sir, {services} aapke paas available hoga?"; in stock:
"{ack}, toh iska estimated kya price rahega?" (electronics: NO negotiation); not in stock:
"{ack}, kab tak aa jayega?" (their words noted); electronics: "{ack}, aur isme warranty kitni mil
jayegi?"; exchange (only if `q_exchange`): "{ack}, aur hamare paas purana phone hai exchange ke
liye, uska koi offer mil jayega?" -> they ask model/year/works: answer from `old_phone_*` (missing
-> "Yeh main {Himanshu sir} se poochh kar bataungi.") -> "Toh sir, exchange mein uska kitna milega,
aur final price kitna padega?"; florist: "{ack}, aap home delivery provide karte ho kya?" (area
only if asked: "Ji, {delivery_area} mein."); close rule 11. Confirmation (hold): "{Himanshu sir}
ne confirm kar diya hai, toh ek baar aap hamare liye {services} hold kar dijiye {Himanshu} ke naam
se, woh {shaam} tak aake pick kar lenge." If they ask a booking payment: rule 6.

## 7a. table_booking (restaurant, cafe) `q_price` = no
Hook "...table booking ke regarding..."; she states: "Ji, hamko {date_window} ke liye
{people_count} logon ka table book karana hai." (NO separate availability question, no price);
they answer; available + delegation: booking close (rule 9, "{people_count} logon ka table");
available, no delegation: price-check-style close; not available: rule 8. Optional if the user
asked: outdoor/window table, birthday cake. Confirmation call: generic.

## 7b. hotel_booking
Hook "...room booking ke regarding..."; "Ji, hamko {checkin_date} se {checkout_date} tak,
{guests} log ke liye, {room_count} room chahiye."; they say "multiple options": "{ack}, toh ek
baar options bata dijiye, unka estimated price kya hoga?"; NO room: "Theek hai sir, thank you.
Main {Himanshu sir} se alternate days ke liye confirm karke aapko call back karti hoon."; available:
"Toh sir, yeh price tax ke saath hai ya tax alag se lagega?", "Aur isme breakfast include rahega?",
"Aur check-in aur check-out ka time kya rehta hai?", "Aur cancellation ki kya policy hai?"; close
rule 11. Negotiation only if the user asks (rule 10). Confirmation: "{Himanshu sir} ne confirm kar
diya hai, toh aap {checkin_date} se {checkout_date} tak ka room {user_full_spoken} ke naam se book
kar lijiye." (no WhatsApp step). Booking amount: rule 6 (bank details by WhatsApp).

## 7c. banquet_booking
Hook "...banquet booking ke regarding..."; they ask event details: "Ji, {event_type} hai,
{event_date} ko, {guests} log, {veg_nonveg}."; "Toh sir, iska total estimated kitna rahega?"; NOT
available: "Okay sir, thank you. Main {Himanshu sir} se update karke aapko dobara call karti
hoon."; "{ack}, aur isme decoration include rahega ya alag se?" (DJ/sound only if `q_extras`);
rooms (if `rooms_needed`): "{ack}, aur humein {rooms_needed} rooms bhi chahiye honge. Aapke yahan
kitne rooms available honge?"; VISIT: "{ack}, aur visit karne hum kab aa sakte hain?" -> "Theek hai
sir, {Himanshu sir} {visit} visit karne aa jayenge."; close "{ack}, main ek baar {Himanshu sir} ko
bata deti hoon. Thank you." NO negotiation. Confirmation: "{Himanshu sir} ne confirm kar diya hai,
woh {visit} visit karne aa jayenge." Booking amount: rule 6.
