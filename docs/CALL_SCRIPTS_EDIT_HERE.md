# Call scripts: ONE place to write how Friday talks to vendors

Founder: write or change the words here (Hinglish, Roman script; Indian names are filled in automatically). Tell Claude "use my script from CALL_SCRIPTS_EDIT_HERE" and the lines are copied into the playbooks, **then audio is sent to you before anything goes live** (hear-before-change).

How to edit: change only the text between the quotes. Keep `{words in curly brackets}`: they are filled in by the system (`{business_name_spoken}` = vendor name, `{user_spoken}` = your name, `{honorific}` = sir/ma'am, `{services_spoken}` = what you want, `{date_window}` = when, `{slot}` = the booked time, `{budget}` = price limit).

## Way of talk (write your rules here, in plain words)
- Tone: 
- Do say: 
- Never say: 
- Length of a call: 

Files: live salon script = `friday/playbooks/data/salon_booking.yaml`; the 6 new call types = `friday/playbooks/pending/<type>.yaml` (section `lines:`). Below is the current text of every line.


## enquiry: Enquiry (coaching, admissions, courses, photographers, wedding services)
`friday/playbooks/pending/enquiry.yaml`

- `disclosure`: Hello, kya meri baat {business_name_spoken} se ho rahi hai?
- `reintro`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant.
- `s0_who`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?
- `recording_notice`: Yeh call quality ke liye record ho sakta hai.
- `intro`: Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant.
- `ai_yes`: Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.
- `bye_busy`: Koi baat nahi, main baad mein call karti hoon. Shukriya.
- `bye_wrong`: Maaf kijiye, galat number lag gaya. Shukriya.
- `bye_dnc`: Theek hai, hum dobara call nahi karenge. Shukriya.
- `bye_rude`: Maaf kijiye, pareshan karne ke liye. Shukriya.
- `bye_unclear`: Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.
- `wa_decline`: Sir, abhi WhatsApp possible nahi hai, aap yahin bata dijiye please.
- `s5_no_advance`: Advance main abhi nahi de sakti, {user_spoken} {honorific} se poochh kar bataungi.
- `no_number`: {user_spoken} {honorific} ka number main share nahi kar sakti.
- `q_close`: Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.
- `sorry`: Sorry, ek baar phir?
- `offscript`: Yeh main {user_spoken} {honorific} se poochh kar bataungi.
- `no_secrets`: Yeh jaankari main share nahi kar sakti.
- `intro_enq`: {user_spoken} {honorific} ko {services_spoken} ke baare mein jaankari chahiye.
- `s3_ask_first`: Toh sir, fees kitni rahegi?
- `s3_ask`: Sir, fees kitni hogi?
- `s4_ask`: Batch ka timing kya rehta hai?
- `s5_ask`: Demo class mil sakti hai?

## home_service_visit: Home service visit (plumber, electrician, AC repair, painter, pest control, packers, ...)
`friday/playbooks/pending/home_service_visit.yaml`

- `disclosure`: Hello, kya meri baat {business_name_spoken} se ho rahi hai?
- `reintro`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant.
- `s0_who`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?
- `recording_notice`: Yeh call quality ke liye record ho sakta hai.
- `intro`: Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant.
- `ai_yes`: Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.
- `bye_busy`: Koi baat nahi, main baad mein call karti hoon. Shukriya.
- `bye_wrong`: Maaf kijiye, galat number lag gaya. Shukriya.
- `bye_dnc`: Theek hai, hum dobara call nahi karenge. Shukriya.
- `bye_rude`: Maaf kijiye, pareshan karne ke liye. Shukriya.
- `bye_unclear`: Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.
- `wa_decline`: Sir, abhi WhatsApp possible nahi hai, aap yahin bata dijiye please.
- `s5_no_advance`: Advance main abhi nahi de sakti, {user_spoken} {honorific} se poochh kar bataungi.
- `no_number`: {user_spoken} {honorific} ka number main share nahi kar sakti.
- `q_close`: Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.
- `sorry`: Sorry, ek baar phir?
- `offscript`: Yeh main {user_spoken} {honorific} se poochh kar bataungi.
- `no_secrets`: Yeh jaankari main share nahi kar sakti.
- `intro_visit`: {user_spoken} {honorific} ke yahan {services_spoken} ka kaam hai.
- `s3_ask_first`: Toh sir, visit ka charge kitna rahega?
- `s3_ask`: Sir, visit ka charge kitna hoga?
- `s4_ask`: Aur kaam ka rough estimate kitna aa jata hai?
- `s5_ask_date`: Visit {date_window} ho sakta hai?
- `s5_ask_open`: Aaj ya kal visit ho sakta hai?
- `s5b_ask`: Toh kab tak aa sakte hain?
- `s6_ask`: Aane ka time kya rahega?

## quote_and_slot: Quote and slot (clinic, dentist, gym trial, car wash, laundry, tutor demo, ...)
`friday/playbooks/pending/quote_and_slot.yaml`

- `disclosure`: Hello, kya meri baat {business_name_spoken} se ho rahi hai?
- `reintro`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant.
- `s0_who`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?
- `recording_notice`: Yeh call quality ke liye record ho sakta hai.
- `intro`: Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant.
- `intro_book`: {user_spoken} {honorific} ko {services_spoken} chahiye, toh unki booking ke regarding call kiya hai.
- `intro_quote`: {user_spoken} {honorific} ko {services_spoken} chahiye, toh uske charges ke regarding call kiya hai.
- `s3_ask_first`: Toh sir, ek baar bata sakte hain inke kya charges rahenge?
- `s3_ask`: Sir, {services_spoken} ke kya charges rahenge?
- `ai_yes`: Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.
- `bye_busy`: Koi baat nahi, main baad mein call karti hoon. Shukriya.
- `bye_wrong`: Maaf kijiye, galat number lag gaya. Shukriya.
- `bye_dnc`: Theek hai, hum dobara call nahi karenge. Shukriya.
- `bye_rude`: Maaf kijiye, pareshan karne ke liye. Shukriya.
- `bye_unclear`: Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.
- `s3b_ask`: {user_spoken} {honorific} ka budget {budget} rupaye hai. Kuch kam ho sakta hai?
- `wa_decline`: Sir, abhi WhatsApp possible nahi hai, aap yahin bata dijiye please.
- `s2_ask_first`: Theek hai sir. Kya {date_window} ka slot mil sakta hai?
- `s2_ask`: Kya {date_window} ka slot mil sakta hai?
- `s2_appt_only`: Appointment ke liye hi poochh rahi hoon.
- `s2_ask_time`: Kitne baje ka?
- `s2f_ask`: Achha, nahi ho sakta. Toh kya {fallback_day} ka slot available rahega?
- `s2b_ask`: Toh kaun sa time free hai?
- `s2b_ask_two`: Toh kaun se do time free hain?
- `s2b_none`: Koi baat nahi, main {user_spoken} {honorific} ko bata dungi. Shukriya.
- `s5_no_advance`: Advance main abhi nahi de sakti, {user_spoken} {honorific} se poochh kar bataungi.
- `no_number`: {user_spoken} {honorific} ka number main share nahi kar sakti.
- `s7_close`: Theek hai, shukriya. Main {user_spoken} {honorific} se poochh kar aapko batati hoon.
- `s7_commit_free`: Theek hai sir, toh {slot} ka slot book kar lijiye. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.
- `s7_commit_fallback`: Theek hai sir, phir {slot} ka slot book kar lete hain. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.
- `q_close`: Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.
- `sorry`: Sorry, ek baar phir?
- `offscript`: Yeh main {user_spoken} {honorific} se poochh kar bataungi.
- `no_secrets`: Yeh jaankari main share nahi kar sakti.

## rental: Rental (car, cab, bike, equipment)
`friday/playbooks/pending/rental.yaml`

- `disclosure`: Hello, kya meri baat {business_name_spoken} se ho rahi hai?
- `reintro`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant.
- `s0_who`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?
- `recording_notice`: Yeh call quality ke liye record ho sakta hai.
- `intro`: Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant.
- `ai_yes`: Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.
- `bye_busy`: Koi baat nahi, main baad mein call karti hoon. Shukriya.
- `bye_wrong`: Maaf kijiye, galat number lag gaya. Shukriya.
- `bye_dnc`: Theek hai, hum dobara call nahi karenge. Shukriya.
- `bye_rude`: Maaf kijiye, pareshan karne ke liye. Shukriya.
- `bye_unclear`: Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.
- `wa_decline`: Sir, abhi WhatsApp possible nahi hai, aap yahin bata dijiye please.
- `no_number`: {user_spoken} {honorific} ka number main share nahi kar sakti.
- `q_close`: Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.
- `sorry`: Sorry, ek baar phir?
- `offscript`: Yeh main {user_spoken} {honorific} se poochh kar bataungi.
- `no_secrets`: Yeh jaankari main share nahi kar sakti.
- `intro_rent`: {user_spoken} {honorific} ko {services_spoken} kiraye par chahiye.
- `intro_rent_for`: Yeh {duration_text} ke liye chahiye.
- `s3_ask_first`: Toh sir, {unit_phrase} kitna rahega?
- `s3_ask`: Sir, {unit_phrase} kitna hoga?
- `s2_ask_first`: Theek hai sir. Kya {date_window} ke liye available hai?
- `s2_ask`: Kya {date_window} ke liye available hai?
- `s2_ask_open`: Theek hai sir. Kya aaj ya kal ke liye available hai?

## stock_and_price: Stock and price (pharmacy, electronics, hardware, grocery, optician, books, ...)
`friday/playbooks/pending/stock_and_price.yaml`

- `disclosure`: Hello, kya meri baat {business_name_spoken} se ho rahi hai?
- `reintro`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant.
- `s0_who`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?
- `recording_notice`: Yeh call quality ke liye record ho sakta hai.
- `intro`: Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant.
- `ai_yes`: Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.
- `bye_busy`: Koi baat nahi, main baad mein call karti hoon. Shukriya.
- `bye_wrong`: Maaf kijiye, galat number lag gaya. Shukriya.
- `bye_dnc`: Theek hai, hum dobara call nahi karenge. Shukriya.
- `bye_rude`: Maaf kijiye, pareshan karne ke liye. Shukriya.
- `bye_unclear`: Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.
- `wa_decline`: Sir, abhi WhatsApp possible nahi hai, aap yahin bata dijiye please.
- `s5_no_advance`: Advance main abhi nahi de sakti, {user_spoken} {honorific} se poochh kar bataungi.
- `no_number`: {user_spoken} {honorific} ka number main share nahi kar sakti.
- `q_close`: Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.
- `sorry`: Sorry, ek baar phir?
- `offscript`: Yeh main {user_spoken} {honorific} se poochh kar bataungi.
- `no_secrets`: Yeh jaankari main share nahi kar sakti.
- `intro_stock`: {user_spoken} {honorific} ko {services_spoken} chahiye.
- `s2_ask_first`: Aapke yahan hai? Kitne ka rahega?
- `s2_ask`: {services_spoken} hai aapke yahan?
- `s3_ask`: Kitne ka rahega sir?
- `s3_options`: Do-teen options ke rate bata dijiye please.
- `any_brand`: Jo bhi available ho, uska rate bata dijiye.
- `s5_ask`: Delivery ho jayegi, ya aana padega?
- `oos_close`: Achha ji, theek hai. Main {user_spoken} {honorific} ko bata deti hoon. Thank you.

## table_or_venue: Table or venue (restaurant, cafe, banquet, hotel room)
`friday/playbooks/pending/table_or_venue.yaml`

- `disclosure`: Hello, kya meri baat {business_name_spoken} se ho rahi hai?
- `reintro`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant.
- `s0_who`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?
- `recording_notice`: Yeh call quality ke liye record ho sakta hai.
- `intro`: Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant.
- `ai_yes`: Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.
- `bye_busy`: Koi baat nahi, main baad mein call karti hoon. Shukriya.
- `bye_wrong`: Maaf kijiye, galat number lag gaya. Shukriya.
- `bye_dnc`: Theek hai, hum dobara call nahi karenge. Shukriya.
- `bye_rude`: Maaf kijiye, pareshan karne ke liye. Shukriya.
- `bye_unclear`: Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.
- `wa_decline`: Sir, abhi WhatsApp possible nahi hai, aap yahin bata dijiye please.
- `s5_no_advance`: Advance main abhi nahi de sakti, {user_spoken} {honorific} se poochh kar bataungi.
- `no_number`: {user_spoken} {honorific} ka number main share nahi kar sakti.
- `q_close`: Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.
- `sorry`: Sorry, ek baar phir?
- `offscript`: Yeh main {user_spoken} {honorific} se poochh kar bataungi.
- `no_secrets`: Yeh jaankari main share nahi kar sakti.
- `intro_venue`: {user_spoken} {honorific} ko {party_size} logon ke liye {services_spoken} chahiye, {date_window}.
- `s3_ask_first`: Toh sir, {unit_phrase} kitna rahega?
- `s3_ask`: Sir, {unit_phrase} kitna hoga?
- `s2_ask_first`: Theek hai sir. Kya {date_window} ke liye available rahega?
- `s2_ask`: Kya {date_window} ke liye available rahega?
- `s2_ask_time`: Kitne baje ka?
- `s2f_ask`: Achha, nahi ho sakta. Toh kya {fallback_day} ke liye available rahega?
- `s2b_ask`: Toh kaun sa time free hai?
- `s2b_ask_two`: Toh kaun se do time free hain?
- `s2b_none`: Koi baat nahi, main {user_spoken} {honorific} ko bata dungi. Shukriya.
- `s7_close`: Theek hai, shukriya. Main {user_spoken} {honorific} se poochh kar aapko batati hoon.
- `s7_commit_free`: Theek hai sir, toh {slot} ka {services_spoken} {party_size} logon ke liye book kar lijiye. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.
- `s7_commit_fallback`: Theek hai sir, phir {slot} ka {services_spoken} {party_size} logon ke liye book kar lete hain. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.

## salon_booking: Salon booking (haircut etc.)
`friday/playbooks/data/salon_booking.yaml`

- `disclosure`: Hello, kya meri baat {business_name_spoken} se ho rahi hai?
- `reintro`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant.
- `s0_who`: Main Friday hoon, {user_spoken} {honorific} ki virtual assistant. Kya meri baat {business_name_spoken} se ho rahi hai?
- `recording_notice`: Yeh call quality ke liye record ho sakta hai.
- `intro`: Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki virtual assistant.
- `intro_book`: {user_spoken} {honorific} ko {services_spoken} karwana hai, toh unki booking ke regarding call kiya hai.
- `intro_quote`: {user_spoken} {honorific} ko {services_spoken} karwana hai, toh uske charges ke regarding call kiya hai.
- `s3_ask_first`: Toh sir, ek baar bata sakte hain inke kya charges rahenge?
- `s3_ask`: Sir, {services_spoken} ke kya charges rahenge?
- `ai_yes`: Haan ji, main {user_spoken} {honorific} ki personal AI assistant hoon.
- `bye_busy`: Koi baat nahi, main baad mein call karti hoon. Shukriya.
- `bye_wrong`: Maaf kijiye, galat number lag gaya. Shukriya.
- `bye_dnc`: Theek hai, hum dobara call nahi karenge. Shukriya.
- `bye_rude`: Maaf kijiye, pareshan karne ke liye. Shukriya.
- `bye_unclear`: Maaf kijiye, awaaz saaf nahi aa rahi. Main baad mein call karti hoon. Shukriya.
- `s3b_ask`: {user_spoken} {honorific} ka budget {budget} rupaye hai. Kuch kam ho sakta hai?
- `s4_ask`: Agar {stylist_pref} available ho to unse hi karwana hai, warna koi bhi chalega.
- `s2_ask_first`: Theek hai sir. Kya {date_window} ka slot mil sakta hai?
- `s2_ask`: Kya {date_window} ka slot mil sakta hai?
- `s2_appt_only`: Appointment ke liye hi poochh rahi hoon.
- `s2_ask_time`: Kitne baje ka?
- `s2f_ask`: Achha, nahi ho sakta. Toh kya {fallback_day} ka slot available rahega?
- `s2b_ask`: Toh kaun sa time free hai?
- `s2b_ask_two`: Toh kaun se do time free hain?
- `s2b_none`: Koi baat nahi, main {user_spoken} {honorific} ko bata dungi. Shukriya.
- `s5_no_advance`: Advance main abhi nahi de sakti, {user_spoken} {honorific} se poochh kar bataungi.
- `no_number`: {user_spoken} {honorific} ka number main share nahi kar sakti.
- `s7_close`: Theek hai, shukriya. Main {user_spoken} {honorific} se poochh kar aapko batati hoon.
- `s7_commit_free`: Theek hai sir, toh {slot} ka slot book kar lijiye. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.
- `s7_commit_fallback`: Theek hai sir, phir {slot} ka slot book kar lete hain. {user_spoken} {honorific} aane se pehle aapko ek baar call kar lenge. Thank you.
- `q_close`: Theek hai sir, main {user_spoken} {honorific} ko bata deti hoon. Thank you.
- `sorry`: Sorry, ek baar phir?
- `offscript`: Yeh main {user_spoken} {honorific} se poochh kar bataungi.
- `no_secrets`: Yeh jaankari main share nahi kar sakti.

## Founder rules for ALL scripts (13 Oct)
1. Always add natural filler words (Ji, Achha, Toh, actually).
2. Every call starts: (a) confirm the business name, (b) the purpose of the call in ONE short line (the hook), then the details.
3. Sentence endings sound like real Hinglish speech ("... rahega?", "... rahegi", "... kar dun?", "... ho jayega na?"), never stiff or formal; stiff endings make her sound like an AI.
4. Use the everyday English word where people do (say "nearest", not "nazdeek"; "slot", "booking", "available", "confirm").
