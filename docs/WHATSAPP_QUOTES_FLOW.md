# WhatsApp quotes flow (beta slice)

A user texts Friday on WhatsApp (English, Hindi or Hinglish), for example
"kal shaam parlour mein haircut karwana hai, quotes chahiye". Friday asks only what is missing, finds
nearby parlours on Google Places, shows 3, asks for approval, phones them one after another with the salon
playbook (price check), sends ONE comparison message with Book buttons, and books the one the user picks.

Code: `friday/quotes/` (flow, parse, finder, calls, messages, store). Tests: `tests/quotes/`.
Simulator: `uv run friday whatsapp-sim` (offline, no keys). All copy lives in `friday/quotes/messages.py`;
a test keeps this document and that file in sync.

## Server-side principle (docs/HANDOFF.md section 2b)

Nothing depends on the user's phone after the approval. The whole job (calls, the single retry, the
comparison) runs from the server and the task queue, with no further user input. The conversation is stored
in the DB table `quote_conversations`; `QuotesFlow.tick()` (every 30 s from the runtime) resumes anything a
restart interrupted. We never ask the user to keep the chat open, share live location or install anything:
a one-time location pin or a typed location is all we need.

### Delivery and fallback rules

1. The comparison (or booking result) is sent on WhatsApp. It is stored on the conversation
   (`delivery.text`, buttons, provider message id, sent time).
2. If the WhatsApp send fails, or Meta later reports the message as `failed`, an SMS summary goes out
   immediately (existing SMS channel, DLT template `user_task_update`; the variable is at most 30
   characters, so only the headline: "Glow Salon Rs 450 +2").
3. If there is no delivery receipt (`delivered` or `read`) within `FRIDAY_QUOTES_DELIVERY_RECEIPT_WAIT_MIN`
   minutes (default 20), the same SMS goes out (once). A switched-off phone still receives the WhatsApp
   message when it comes back online; the SMS is the nudge.
4. A short voice call-back is only requested if `FRIDAY_QUOTES_VOICE_FALLBACK=true` (default false), after
   twice that wait with the SMS sent and still no receipt. Today this records the request (audit
   `quotes.voice_callback_requested`); placing that call is not wired yet.
5. `FRIDAY_QUOTES_SMS_FALLBACK=false` turns the SMS fallback off.
6. The user can type `status` or `result` at any later time and gets the stored result again (with its
   buttons while a booking is still possible), or "still working" while calls run.
7. 24 h window: the user's own messages open it. Free-form text and buttons are only sent inside it. For the
   final result outside the window the notifier switches to the generic `task_update` template (the text is
   the variable, buttons are dropped, so the user replies `book 1` or `status`); that template must be
   approved by Meta, otherwise the send fails and the SMS fallback applies. All other messages of the flow
   are replies to something the user just sent, so they are inside the window.

## State machine

```
  text request
      |
      v
  COLLECTING --(asks one missing slot at a time: service, who, when, location)--+
      | all slots known; Places search (counts as 1 of the user's daily requests)  |
      v                                                                           |
  CONFIRMING  --[Badlo]--> next 3 places (or a new search) -----------------------+
      | [Haan, call karo]  (kill switch off, allow-list ok)
      v
  QUEUED  <-- outside 09:00-19:00 IST, kill switch, or waiting for the retry pass
      | tick()
      v
  CALLING  (1 call at a time by default, 3 at most; first pass over all vendors, then ONE retry
      |     each for no-answer/failed after 10 minutes)
      v
  AWAITING_BOOK  (comparison delivered; buttons: Book <vendor> <time>)
      | [Book X]  (asks "Kitne baje?" if the request had no exact time)
      v
  BOOKING  (delegation: that vendor, that time, the quoted price as the ceiling)
      v
  DONE   (confirmation or the reason it failed)

  any state --"cancel"--> CANCELLED      any state --"stop"--> CANCELLED for ALL open requests
  COLLECTING/CONFIRMING untouched for 24 h --> CANCELLED (silently)
```

Mode: calls are `quote_only` unless the first message explicitly says to book AND names an exact time AND
a budget ("book kar do haircut kal 6 baje 600 tak"); then calls use `book` mode with a delegation for that
time and ceiling, and the first vendor who books ends the run.

## Notification policy (founder rule)

Friday does not message at each stage. The user gets: one short acknowledgement when the request is
understood ("dhoondh rahi hoon"), questions only the user can answer (missing slots, the shortlist
approval), and then NOTHING until an outcome: the quotes, a booking result, a real problem (no places,
Google down, kill switch, test mode), or a question. "Calling now", "calls start tomorrow", per-vendor
results and "booking call started" are NOT sent. Silence is not a dead end: `status` returns progress
("kaam chal raha hai" / "calls kal subah 9 baje shuru hongi") or the stored result.
Optional per-request switch: the user types `updates on` (or `updates band` to stop) and then the
"Progress messages" below are sent for that request only. Default off.

## Rules in code

- One question at a time; location is required (pin, or text like "Sector 56 Gurgaon"). A bare city is
  too wide, so Friday asks for the area. Only Gurgaon and Bangalore; other cities get the polite refusal.
- Vendors: Places text search around the point (5 km), phone required, operational, rating at least 3.8 when a
  rating exists, deduplicated (place id, phone, name at the same spot), numbers on the DNC list never shown or
  called, ranked by `rating * ln(1 + reviews) / (1 + km / 5)` with a boost for "open at the requested time".
  Results are cached per 1 km cell for 6 h. Hard cap of 8 directory calls per request
  (`FRIDAY_QUOTES_MAX_PLACES_CALLS_PER_REQUEST`) and 3 requests per user per day
  (`FRIDAY_QUOTES_MAX_REQUESTS_PER_DAY`).
- Vendor calls only 09:00-19:00 IST (`FRIDAY_QUOTES_CALL_WINDOW_START/END`); outside it the request is queued
  silently (`status` says when the calls start). The kill switch (`friday pause`) holds queued calls.
- Idempotency: Meta retries are dropped by provider message id (runtime idempotency store, the message log,
  and the ids stored on the conversation); a repeated button tap changes nothing; a button of another user is
  ignored.
- AI-honest: the approval message says "Main Friday hoon, AI assistant". On the call the playbook answers
  truthfully if asked. No emoji.
- Voice notes: Friday replies asking for text for now.
- `stop` stops everything (all open requests, in-flight calls are cancelled).

## Test redirect mode (important)

`FRIDAY_VENDOR_CALL_REDIRECT_TO=<founder-number>` (empty by default) makes every vendor call dial THAT number
instead of the real vendor. The script still uses the real vendor's name and city, the vendor is never
dialled and never messaged (no end-of-call SMS/WhatsApp to the vendor), and call records stay keyed by the
real vendor number. The pilot allow-list is checked against the number actually dialled: with the allow-list
active and no redirect, real vendor numbers are refused ("Test mode mein asli jagah ko call nahi kar
sakti"); with a redirect to an allow-listed number the calls go to that number; a redirect to a number that
is not on the list is refused too. `friday doctor` shows whether the redirect is set.

## Config names (values only on the server, never in git or chat)

`GOOGLE_PLACES_API_KEY`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
`WHATSAPP_APP_SECRET`. Webhook URL for Meta: `<FRIDAY_PUBLIC_BASE_URL>/webhooks/whatsapp` (for the current server
`https://<server-ip-with-dashes>.sslip.io/webhooks/whatsapp`); `friday doctor` prints it. Subscribe the app to the
`messages` field. Other settings: `FRIDAY_QUOTES_FLOW_ENABLED`, `FRIDAY_QUOTES_RADIUS_KM`,
`FRIDAY_QUOTES_MAX_CONCURRENT_CALLS` (1 to 3), `FRIDAY_QUOTES_RETRY_AFTER_MIN`, `FRIDAY_QUOTES_STALE_HOURS`,
`FRIDAY_QUOTES_PLACES_CACHE_TTL_S`, `FRIDAY_QUOTES_DELIVERY_RECEIPT_WAIT_MIN`, `FRIDAY_QUOTES_SMS_FALLBACK`,
`FRIDAY_QUOTES_VOICE_FALLBACK`, `FRIDAY_VENDOR_CALL_REDIRECT_TO`.

## Edge cases

| Case | What happens |
| --- | --- |
| No results | `no_vendors`: asks for another area |
| Vendor has no phone | skipped silently |
| Google fails | `places_failed` (honest, asks to retry later); the conversation stays open |
| Nobody picked up | each vendor retried once after 10 min; then `none_worked` with `Dobara try karo` / `Doosre dekho` |
| All declined | `none_worked` ("sabne mana kiya") with the same buttons |
| User changes mind | `cancel` or `nahi` (at the approval step) cancels; a new request replaces an open shortlist |
| Wrong city | `wrong_city`, request closed |
| Voice note | `voice_note` (asks for text) |
| Daily cap reached | `daily_cap` |
| Calling hours over | queued silently; calls start next morning at 09:00; `status_queued` on request |
| Kill switch on | `paused` at approval; queued calls wait |
| Allow-list / test mode | `test_mode_blocked`, nobody called |
| WhatsApp send fails | SMS fallback (see Delivery) |
| Vendor says "do not call" | engine DNC list; never called or shown again |

## Every user-facing message

Placeholders in braces are filled at send time. Button titles are at most 20 characters. The three
languages are chosen by how the user writes (Roman English, Roman Hindi, Devanagari).

### Asking for missing information (one question at a time)

**ask_services**

- en:

```
Which service do you need? For example haircut, beard trim, facial, waxing.
```

- hinglish:

```
Kaunsi service chahiye? Jaise haircut, beard trim, facial, waxing.
```

- hi:

```
कौन सी सर्विस चाहिए? जैसे हेयरकट, बीयर्ड ट्रिम, फेशियल, वैक्सिंग।
```

**ask_for_name**

- en:

```
Who is it for? Please tell me their name.
```

- hinglish:

```
Kiske liye hai? Unka naam bata dijiye.
```

- hi:

```
किसके लिए है? उनका नाम बता दीजिए।
```

**ask_when**

- en:

```
When do you want it? For example: tomorrow evening 6pm.
```

- hinglish:

```
Kab chahiye? Jaise: kal shaam 6 baje.
```

- hi:

```
कब चाहिए? जैसे: कल शाम 6 बजे।
```

**ask_location**

- en:

```
Where are you? Send a location pin, or type it like 'Sector 56 Gurgaon'.
```

- hinglish:

```
Aap kahan hain? Location pin bhejiye, ya likhiye jaise 'Sector 56 Gurgaon'.
```

- hi:

```
आप कहाँ हैं? लोकेशन पिन भेजिए, या लिखिए जैसे 'Sector 56 Gurgaon'।
```

**ask_book_time**

- en:

```
What time should I book? For example: 6pm.
```

- hinglish:

```
Kitne baje ka slot book karun? Jaise: 6 baje.
```

- hi:

```
कितने बजे का स्लॉट बुक करूँ? जैसे: 6 बजे।
```

**location_unclear**

- en:

```
I could not find that place. Type the area and city, like 'Indiranagar Bangalore'.
```

- hinglish:

```
Yeh jagah mujhe nahi mili. Area aur city likhiye, jaise 'Indiranagar Bangalore'.
```

- hi:

```
यह जगह मुझे नहीं मिली। एरिया और शहर लिखिए, जैसे 'Indiranagar Bangalore'।
```

**wrong_city**

- en:

```
For now I only work in Gurgaon and Bangalore. More cities soon.
```

- hinglish:

```
Abhi sirf Gurgaon aur Bangalore mein kaam karti hoon. Jaldi aur shehar aayenge.
```

- hi:

```
अभी सिर्फ़ गुड़गाँव और बेंगलुरु में काम करती हूँ। जल्दी और शहर आएँगे।
```

### Acknowledgement, shortlist and approval

**searching**

- en:

```
Okay, looking for places near you.
```

- hinglish:

```
Theek hai, aas-paas ke parlour dhoondh rahi hoon.
```

- hi:

```
ठीक है, आस-पास के पार्लर ढूँढ रही हूँ।
```

**shortlist**

- en:

```
Found {n} places near {where}:
{lines}
I am Friday, an AI assistant. Shall I call them for you and ask the price of {services}?
```

- hinglish:

```
{where} ke paas {n} jagah mili:
{lines}
Main Friday hoon, AI assistant. Kya main inhe aapki taraf se call karke {services} ka rate puchun?
```

- hi:

```
{where} के पास {n} जगह मिलीं:
{lines}
मैं Friday हूँ, एक AI असिस्टेंट। क्या मैं इन्हें आपकी तरफ़ से कॉल करके {services} का रेट पूछूँ?
```

**btn_call**

- en:

```
Yes, call them
```

- hinglish:

```
Haan, call karo
```

- hi:

```
हाँ, कॉल करो
```

**btn_change**

- en:

```
Change
```

- hinglish:

```
Badlo
```

- hi:

```
बदलो
```

**no_vendors**

- en:

```
I could not find a place with a phone number near there. Try another area?
```

- hinglish:

```
Wahan aas-paas koi aisi jagah nahi mili jiska number ho. Doosra area bataiye?
```

- hi:

```
वहाँ आस-पास ऐसी कोई जगह नहीं मिली जिसका नंबर हो। दूसरा एरिया बताइए?
```

**no_more_vendors**

- en:

```
No more places to show in that area. Tell me another area?
```

- hinglish:

```
Is area mein aur options nahi hain. Doosra area bataiye?
```

- hi:

```
इस एरिया में और विकल्प नहीं हैं। दूसरा एरिया बताइए?
```

**tap_choice**

- en:

```
Please tap one of the buttons, or tell me a different area.
```

- hinglish:

```
Button dabaiye, ya doosra area bataiye.
```

- hi:

```
बटन दबाइए, या दूसरा एरिया बताइए।
```

### Real problems at approval

**paused**

- en:

```
I am on a short break and cannot make calls right now. Please try later.
```

- hinglish:

```
Main thodi der ke break par hoon, abhi calls nahi kar sakti. Baad mein try kijiye.
```

- hi:

```
मैं थोड़ी देर के ब्रेक पर हूँ, अभी कॉल नहीं कर सकती। बाद में कोशिश कीजिए।
```

**test_mode_blocked**

- en:

```
In test mode I cannot call real places. Nothing was called.
```

- hinglish:

```
Test mode mein asli jagah ko call nahi kar sakti. Kisi ko call nahi gaya.
```

- hi:

```
टेस्ट मोड में असली जगहों को कॉल नहीं कर सकती। किसी को कॉल नहीं गया।
```

**places_failed**

- en:

```
I cannot search places right now. Please try again in a while.
```

- hinglish:

```
Abhi parlour search nahi ho pa raha. Thodi der baad dobara try kijiye.
```

- hi:

```
अभी पार्लर सर्च नहीं हो पा रहा। थोड़ी देर बाद फिर कोशिश कीजिए।
```

**calls_failed**

- en:

```
I could not place the calls. Please try again in a while.
```

- hinglish:

```
Call lagane mein dikkat aayi. Thodi der baad dobara try kijiye.
```

- hi:

```
कॉल लगाने में दिक्कत आई। थोड़ी देर बाद फिर कोशिश कीजिए।
```

**busy**

- en:

```
Your last request is still running. Type 'cancel' to stop it.
```

- hinglish:

```
Pichli request abhi chal rahi hai. Rokni ho to 'cancel' likhiye.
```

- hi:

```
पिछली रिक्वेस्ट अभी चल रही है। रोकनी हो तो 'cancel' लिखिए।
```

### Progress messages (OFF by default, only after the user types `updates on`)

**calling**

- en:

```
Okay, calling them now. I will send all the quotes together.
```

- hinglish:

```
Theek hai, call kar rahi hoon. Saare quotes ek saath bhejungi.
```

- hi:

```
ठीक है, कॉल कर रही हूँ। सारे कोट्स एक साथ भेजूँगी।
```

**queued**

- en:

```
They are closed for calls now. I will call at {when} and send the quotes.
```

- hinglish:

```
Abhi unhe call karne ka time nahi hai. {when} call karungi, phir quotes bhejungi.
```

- hi:

```
अभी उन्हें कॉल करने का समय नहीं है। {when} कॉल करूँगी, फिर कोट्स भेजूँगी।
```

**book_calling**

- en:

```
Okay, calling {name} to book {when}.
```

- hinglish:

```
Theek hai, {name} ko {when} ke liye book karne call kar rahi hoon.
```

- hi:

```
ठीक है, {name} को {when} के लिए बुक करने कॉल कर रही हूँ।
```

**updates_on**

- en:

```
Okay, I will send progress updates for this request.
```

- hinglish:

```
Theek hai, is request ke progress updates bhejungi.
```

- hi:

```
ठीक है, इस रिक्वेस्ट के प्रोग्रेस अपडेट भेजूँगी।
```

**updates_off**

- en:

```
Okay, no progress updates. I will message you with the result.
```

- hinglish:

```
Theek hai, updates nahi bhejungi. Result aate hi message karungi.
```

- hi:

```
ठीक है, अपडेट नहीं भेजूँगी। रिज़ल्ट आते ही मैसेज करूँगी।
```

### Result

**comparison_head**

- en:

```
Quotes for {services} ({when}):
```

- hinglish:

```
{services} ke quotes ({when}):
```

- hi:

```
{services} के कोट्स ({when}):
```

**quote_line**

- en:

```
{name}: Rs {price}
```

- hinglish:

```
{name}: Rs {price}
```

- hi:

```
{name}: Rs {price}
```

**unpriced_line**

- en:

```
{name}: they did not give a price
```

- hinglish:

```
{name}: unhone price nahi bataya
```

- hi:

```
{name}: उन्होंने कीमत नहीं बताई
```

**no_answer_tail**

- en:

```
{n} did not pick up.
```

- hinglish:

```
{n} ne phone nahi uthaya.
```

- hi:

```
{n} ने फ़ोन नहीं उठाया।
```

**declined_tail**

- en:

```
{n} could not help.
```

- hinglish:

```
{n} ne mana kiya.
```

- hi:

```
{n} ने मना किया।
```

**book_prompt**

- en:

```
Tap to book:
```

- hinglish:

```
Book karna ho to dabaiye:
```

- hi:

```
बुक करना हो तो दबाइए:
```

**book_btn**

- en:

```
Book {name} {time}
```

- hinglish:

```
Book {name} {time}
```

- hi:

```
बुक {name} {time}
```

**none_worked**

- en:

```
No quotes this time: {why}. Try again, or see other places?
```

- hinglish:

```
Is baar koi quote nahi mila: {why}. Dobara try karun ya doosre dekhun?
```

- hi:

```
इस बार कोई कोट नहीं मिला: {why}। फिर कोशिश करूँ या दूसरे देखूँ?
```

**why_no_answer**

- en:

```
nobody picked up
```

- hinglish:

```
kisi ne phone nahi uthaya
```

- hi:

```
किसी ने फ़ोन नहीं उठाया
```

**why_declined**

- en:

```
they could not help
```

- hinglish:

```
sabne mana kiya
```

- hi:

```
सबने मना किया
```

**why_mixed**

- en:

```
no price was given
```

- hinglish:

```
kisi ne price nahi bataya
```

- hi:

```
किसी ने कीमत नहीं बताई
```

**btn_retry**

- en:

```
Try again
```

- hinglish:

```
Dobara try karo
```

- hi:

```
फिर से कोशिश
```

**btn_others**

- en:

```
Other places
```

- hinglish:

```
Doosre dekho
```

- hi:

```
दूसरे देखो
```

### Booking outcome

**booked**

- en:

```
Booked: {name}, {when}, Rs {price}.
```

- hinglish:

```
Booking pakki: {name}, {when}, Rs {price}.
```

- hi:

```
बुकिंग पक्की: {name}, {when}, Rs {price}।
```

**book_failed**

- en:

```
Could not book {name}: {why}.
```

- hinglish:

```
{name} mein booking nahi ho payi: {why}.
```

- hi:

```
{name} में बुकिंग नहीं हो पाई: {why}।
```

**bwhy_no_slot**

- en:

```
that time was not free
```

- hinglish:

```
us time ka slot khali nahi tha
```

- hi:

```
उस समय का स्लॉट खाली नहीं था
```

**bwhy_price**

- en:

```
the price was higher than the quote
```

- hinglish:

```
price quote se zyada tha
```

- hi:

```
कीमत कोट से ज़्यादा थी
```

**bwhy_no_answer**

- en:

```
they did not pick up
```

- hinglish:

```
unhone phone nahi uthaya
```

- hi:

```
उन्होंने फ़ोन नहीं उठाया
```

**bwhy_other**

- en:

```
the call did not finish properly
```

- hinglish:

```
baat poori nahi ho payi
```

- hi:

```
बात पूरी नहीं हो पाई
```

### Control, status and edge cases

**cancelled**

- en:

```
Okay, cancelled. Message me anytime for a new request.
```

- hinglish:

```
Theek hai, cancel kar diya. Nayi request kabhi bhi bhej dijiye.
```

- hi:

```
ठीक है, कैंसल कर दिया। नई रिक्वेस्ट कभी भी भेज दीजिए।
```

**stopped**

- en:

```
Stopped everything. Message me again whenever you want to start.
```

- hinglish:

```
Sab kuch band kar diya. Dobara shuru karna ho to kabhi bhi likhiye.
```

- hi:

```
सब कुछ बंद कर दिया। दोबारा शुरू करना हो तो कभी भी लिखिए।
```

**voice_note**

- en:

```
I cannot listen to voice notes yet. Please type it.
```

- hinglish:

```
Abhi main voice note nahi sun paati. Text mein likh dijiye please.
```

- hi:

```
अभी मैं वॉइस नोट नहीं सुन पाती। कृपया टेक्स्ट में लिखिए।
```

**daily_cap**

- en:

```
You have used {n} requests today. Please ask again tomorrow.
```

- hinglish:

```
Aaj ki {n} requests ho chuki hain. Kal phir bhejiye.
```

- hi:

```
आज की {n} रिक्वेस्ट हो चुकी हैं। कल फिर भेजिए।
```

**stale**

- en:

```
That option is no longer valid. Send a new request.
```

- hinglish:

```
Yeh option ab valid nahi hai. Nayi request bhejiye.
```

- hi:

```
यह विकल्प अब मान्य नहीं है। नई रिक्वेस्ट भेजिए।
```

**status_working**

- en:

```
Still working on it. I will message you when the quotes are ready.
```

- hinglish:

```
Abhi kaam chal raha hai. Quotes aate hi message karungi.
```

- hi:

```
अभी काम चल रहा है। कोट्स आते ही मैसेज करूँगी।
```

**status_queued**

- en:

```
Calls start {when}. I will message you when the quotes are ready.
```

- hinglish:

```
Calls {when} shuru hongi. Quotes aate hi message karungi.
```

- hi:

```
कॉल {when} शुरू होंगी। कोट्स आते ही मैसेज करूँगी।
```

**status_none**

- en:

```
No request yet. Tell me what you need, like 'haircut tomorrow evening'.
```

- hinglish:

```
Abhi koi request nahi hai. Bataiye kya chahiye, jaise 'kal shaam haircut'.
```

- hi:

```
अभी कोई रिक्वेस्ट नहीं है। बताइए क्या चाहिए, जैसे 'कल शाम हेयरकट'।
```

**sms_summary**

- en:

```
Friday: {text}
```

- hinglish:

```
Friday: {text}
```

- hi:

```
Friday: {text}
```
