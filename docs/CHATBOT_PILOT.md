# WhatsApp chatbot pilot: onboarding and chat quality (22 Oct 2026)

Status: BUILT, OFF BY DEFAULT, ALL WORDING PENDING FOUNDER APPROVAL. Nothing here has been seen by a real person.
Architecture and the access catalogue: `docs/CHATBOT_ARCHITECTURE.md`. Plan: `docs/GO_LIVE_5_DAYS.md` (day 1 workstream: pilot onboarding and consent).
Code: `friday/chatbot/`, tests: `tests/chatbot/` (offline, SQLite, invented numbers, no network).

Goal: a tester starts from a first "hi" and is using Friday in two minutes, with a consent record behind it.

## What a tester sees

```
tester:  hi
Friday:  Namaste! Main Friday hoon, ek AI assistant (insaan nahi).        <- intro: who she is,
         Main yeh kar sakti hoon: - call - card se bachat - aapka din       what she does (3 bullets),
         Main kabhi payment, OTP, PIN ya card number nahi maangti.          what she never does,
         Sirf aapka apna data, jab chaho delete. Aage badhein?              own data, delete anytime
         [Haan, theek hai] [Details] [Nahi]
tester:  (taps Haan)   -> consent recorded, user created
Friday:  Shukriya! Aapko kya bulaun?  [Skip]                                 name
tester:  Rahul
Friday:  Namaste Rahul! Aap kis bhasha mein baat karna chahenge?             language (mirrors the first message)
         [Hinglish] [हिंदी] [English]
tester:  (taps Hinglish)
Friday:  Theek hai, ab main Hinglish mein baat karungi.
         Aap kis shehar mein hain? Shehar ka naam likhiye ya location pin bhejiye.     city or a location pin
tester:  Pune
Friday:  Pune, achha! Chaliye pehla kaam karte hain. Kya try karein?
         [Card jodo] [Mera din] [Kisi ko call]                                one first win (only features that are on)
tester:  (taps Card jodo)
Friday:  Bas likhiye: 'mere paas HDFC Regalia card hai'. ...
Friday:  Bas, itna hi! Kabhi bhi 'menu' likhiye. Main AI assistant hoon: ...   closes with the plain statement
```

## How it works

Hooks in `friday/api/inbound.py` (all behind `FRIDAY_CHATBOT_ONBOARDING`; with it off `pipeline.chatbot` is None and the pipeline behaves exactly as before):

| Where | Hook | What |
|---|---|---|
| unknown number, instead of the invite-code onboarding | `chatbot.handle_unknown` | pilot gate, intro, consent. Returns False when the invite-code flow should run (see the gate table) |
| known user, before the consumer router | `chatbot.pre` | `cb:` buttons, menu/help, human, stop/resume, delete everything, answer to a pending question, shared contact card, location pin, answer to the current onboarding step |
| known user, after quotes/PM/buttons, before the brain | `chatbot.post` | a typed phone number becomes a contact; a clear off-topic question gets the redirect |

### States (table `chatbot_sessions`, one row per person, keyed by a hash of the phone)

| step | meaning | next |
|---|---|---|
| `consent` | intro sent, waiting for Haan / Details / Nahi (or typed haan / nahi / details) | Haan -> `name`; Nahi -> `refused` |
| `refused` | said no. Only this row (hash, step, time) is kept. Silent for 1 hour except a greeting, then the intro again on the next message | `consent` |
| `name` | asked what to call them (Skip allowed) | `language` |
| `language` | Hinglish / हिंदी / English buttons; the default is the language of the first message | `city` |
| `city` | typed city, or a location pin (the city comes from reverse geocoding) | `win` |
| `win` | offers ONE first win by button (card, day, call): only features whose switch is on | `done` |
| `done` | finished. The row stays so a pending question (nickname, place) has somewhere to live | - |

Rules of the flow:
- **Nothing is stored before consent** except the session row (a hash of the number and the step). The user, profile, consent and message log are created only on Haan. Replies before consent go straight to the channel and are not logged. The first message itself ("mummy ko call karo") is not kept.
- **Consent record**: an ordinary `Consent` row (`TERMS_PRIVACY`, granted, `policy_version` = `copy.WORDING_VERSION`, `recorded_at` = the time, `evidence_text` = the button/typed words + `lang=` + `wording=`), plus audit entries `user.created` and `consent.granted`. Bump `WORDING_VERSION` when the approved intro/details wording changes.
- **Resumable**: the step lives in the database. After a restart, or a day later, the person is asked the same question again ("Wapas aaye..." after 6 hours).
- **Skippable**: Skip button, or typed skip / baad mein / later. An answer that is not an answer is asked once more, then the step is skipped (never a trap).
- **Not in the way**: a real request in the middle of onboarding ("mummy ko call karo...") is passed to the normal handlers and the question stays open; at the last step any non-answer finishes onboarding and passes through.
- **Pilot gate** (`FRIDAY_PILOT`):

| `FRIDAY_PILOT` | number | what happens |
|---|---|---|
| on | in the allow-list (`FRIDAY_PILOT_ALLOWED_NUMBERS` + `FRIDAY_CHATBOT_TESTERS` + `FRIDAY_ADMIN_PHONES`) | onboards here |
| on | not in the list | one polite waitlist reply, then silence; a row in `chatbot_waitlist` (hash only) |
| off | `FRIDAY_INVITE_ONLY` on (default) | the invite-code onboarding runs exactly as before |
| off | `FRIDAY_INVITE_ONLY` off | anyone onboards here (open sign-up; do not use for the pilot) |

### Menu, help, human, stop, delete

- `menu`, `help`, `madad`, `kya kar sakti ho`, `what can you do` -> a WhatsApp list message (8 rows). Rows of pilot features say `(pilot)` when their switch is on and `(jaldi)` when off. Tapping a row sends a one-message how-to (it never performs stop or delete by itself).
- `human`, `support`, `insaan`, `agent` (optionally `human: the problem`) -> forwarded to `FRIDAY_SUPPORT_INBOX` (name, masked number, the text with numbers masked) and the user is told a person will reply. If the setting is empty, or WhatsApp refuses a free-form message because the founder's 24-hour window is closed, the request is still stored (`friday chatbot wishlist --support`) and the user is told honestly that support is not set up. Message the Friday number from the founder's phone first so the window is open.
- `stop`, `band karo`, `unsubscribe`, `messages band karo` (the whole message only; `stop calling mummy` is not a stop) -> all autonomy categories off, life-state topic "all" muted, morning brief off, a `PROACTIVE` consent record with `granted=false`. `chalu karo` / `start` / `resume` turns it back on. Urgent safety messages still follow the existing guardrail rules.
- `delete everything`, `sab delete karo`, `mera data delete karo` -> hooks into the existing pending `delete_confirm` flow: the user types `DELETE` and `delete_everything` runs (this also erases the chatbot rows). A user who has set a PIN keeps the PIN-protected path (the message goes on to the brain as before).

### Capture

- **Contact**: a shared WhatsApp contact card -> "X ko kya bulaun? mummy, bhaiya..." (once; buttons Mummy / Papa / Skip) -> saved in the user's contact book (`consumer_contacts`, encrypted number, keyed hash) with the nickname and the relationship (mother, father, ...), and confirmed back with the last two digits masked (`+91 98111 000XX`). A typed number ("98111 00077", "mummy 98111 00077") is accepted and confirmed the same way. Emergency numbers are refused; strings of 13 or more digits (cards) are never taken. The entry is saved unconfirmed, so the call gate still confirms the number before the first call.
- **Place**: a location pin -> "Yeh jagah kaunsi hai: ghar, office ya kuch aur?" -> saved as a `Place` (`Home` with alias ghar, `Office`, or the user's own words) through the existing `save_place` (reverse geocoding included). Used by vendor search, never shared. Skip saves nothing. During onboarding the pin also sets the city.
- **Off-topic**: a clear general-knowledge or entertainment ask (capital of France, joke, cricket score, horoscope, recipe...) with nothing from Friday's world in it -> "Main aapke kaam ke liye hoon..." and a wishlist entry (numbers, emails, links masked). Everything else, including every doubt, goes on to the brain. `FRIDAY_CHATBOT_OFFTOPIC` = `redirect` (default), `wishlist_only` (store, let the brain answer) or `off`. Read the wishlist with `uv run friday chatbot wishlist`.

### Chat-quality rules (`friday/chatbot/composer.py`, one test each in `tests/chatbot/test_composer.py`)

1. length caps: 3 lines / 300 characters (the intro 7 / 600, the closing message 4 / 360, proactive 4 / 400);
2. one question per message (one `?`);
3. at most 3 reply buttons, titles up to 20 characters, no empty or duplicate titles; list messages up to 10 rows (title 24, description 72, label 20) and never together with buttons;
4. no repeated line inside a message; the same message twice in a row is replaced by a shorter re-prompt, or not sent;
5. language mirroring: `detect_language` / `mirror_language` (Devanagari -> Hindi, Hinglish words -> Hinglish, English -> English, a bare "hi" -> nothing, so Hinglish by default);
6. a "why" clause on every proactive message, and the plain statement (assistant; never payment / OTP / PIN / card numbers; only the user's own data; delete anytime) on the intro, on proactive text and on the closing message.

In tests (`env=test`) a broken rule raises; in production it is logged by rule name and repaired (clipped, never dropped).

## Settings and switches (all default off / empty; names only)

| Env name | Default | What |
|---|---|---|
| `FRIDAY_CHATBOT_ONBOARDING` | false | the whole feature |
| `FRIDAY_PILOT` | false | only allow-listed testers onboard; the rest are waitlisted |
| `FRIDAY_PILOT_ALLOWED_NUMBERS` | empty | existing allow-list (E.164, CSV); also the numbers Friday may dial in the pilot |
| `FRIDAY_CHATBOT_TESTERS` | empty | extra tester numbers that may chat but are not dial targets |
| `FRIDAY_ADMIN_PHONES` | empty | always allowed |
| `FRIDAY_SUPPORT_INBOX` | empty | WhatsApp number (E.164) that receives `human` requests; never in the code |
| `FRIDAY_CHATBOT_OFFTOPIC` | redirect | redirect / wishlist_only / off |
| `FRIDAY_CHATBOT_GUARDS` | true | fixed safety lines (emergency, medicine, fake bill) and "reply in Hindi" |
| `FRIDAY_CHATBOT_QUICK_ANSWERS` | true | sums, percentages, time and date computed in code |
| `FRIDAY_CHATBOT_FIRST_WINS` | card,day,call | order of the first-win buttons (only those whose feature switch is on are offered) |
| `FRIDAY_CHATBOT_DISCLOSURE_EVERY_STEP` | false | true: every onboarding step ends with a one-line "AI assistant, never payment/OTP/PIN" footer |
| `FRIDAY_SAVINGS_ENABLED`, `FRIDAY_LIFESTATE_ENABLED`, `FRIDAY_CONSUMER_CALLS_ENABLED` | false | the features the first wins and the menu point to (`docs/CONSUMER_INTEGRATION.md`) |

Database: migration `0010_chatbot` (tables `chatbot_sessions`, `chatbot_waitlist`, `chatbot_inbox`; RLS lines added; `friday doctor` now expects `0010_chatbot`). Erasure: `delete_everything` removes the sessions and inbox rows of the user.

Commands: `uv run friday chatbot wishlist [--support]`, `uv run friday chatbot status`, `uv run friday chatbot templates check`, `uv run friday chatbot templates render`.

## WhatsApp templates (messages outside the 24-hour window)

Six drafts (morning brief, follow-up nudge, bill reminder, call outcome, re-engage, consent re-request), each in Roman Hinglish, Hindi and English = 18 registrations: `docs/WHATSAPP_TEMPLATES.md` (generated) from `friday/chatbot/templates.yaml`. `uv run friday chatbot templates check` verifies placeholders against params and examples, Meta's body rules, buttons, the plain statement and the why-clause in every body, names against `friday/core/templates.py` and `Settings.whatsapp_templates`, and every `chatbot_template(...)` call in the code. Nothing sends these yet: the notifier still uses the generic `nudge` / `task_update` / `reengage` until a draft is approved and a sender is switched over. A tap on a template button is understood (`stop`, `human`, consent again) by payload or by title.

## PENDING FOUNDER APPROVAL: every copy id

All wording is in `friday/chatbot/copy.py` (marked `PENDING_FOUNDER_APPROVAL`), in Roman Hinglish with `hi` (Devanagari) and `en` variants of every id. The table shows the Hinglish; read the other two in the file. 85 ids (62 lines, 15 buttons, 8 menu rows), plus the 18 template bodies in `docs/WHATSAPP_TEMPLATES.md`. Tests check structure, never the words, so edit freely. After you approve a changed `intro` or `details`, bump `copy.WORDING_VERSION`.

| id | kind | Hinglish |
|---|---|---|
| `chatbot.line.intro` | intro | Namaste! Main Friday hoon, ek AI assistant (insaan nahi). / Main yeh kar sakti hoon: / - aapke liye call karna / - card se bachat batana / - aapka din yaad rakhna / Main kabhi payment, OTP, PIN ya card number nahi maangti. Sirf aapka apna data, jab chaho delete. / Aage badhein? |
| `chatbot.line.details` | intro | Main Friday, ek AI assistant. Aapke messages sirf aapki madad ke liye padhti hoon. Sirf aapka apna data (naam, shehar, jo aap batao) yaad rakhti hoon, kisi ko bechti nahi. / Payment, OTP, PIN, card number main kabhi nahi maangti. 'delete everything' likho toh sab mita dungi. / Theek hai? |
| `chatbot.line.consent_reprompt` | default | Aage badhne se pehle mujhe aapki haan chahiye. Haan, theek hai ya Nahi? |
| `chatbot.line.refused` | default | Theek hai, koi baat nahi. Maine kuch save nahi kiya. Kabhi mann ho toh 'hi' bhej dena. |
| `chatbot.line.waitlist` | intro | Namaste, main Friday, ek AI assistant. Abhi sirf kuch testers ke saath chal rahi hoon. Aapka number waitlist mein hai, jagah khulte hi bataungi. / Main kabhi payment, OTP ya PIN nahi maangti; sirf aapka apna data, jab chaho delete. |
| `chatbot.line.ask_name` | default | Shukriya! Aapko kya bulaun? Apna naam likhiye ya Skip dabaiye. |
| `chatbot.line.reprompt_name` | default | Naam samajh nahi aaya. Sirf naam likhiye, jaise 'Rahul', ya Skip dabaiye. |
| `chatbot.line.ack_name` | default | Namaste {name}! |
| `chatbot.line.ack_name_skip` | default | Theek hai, bina naam ke. |
| `chatbot.line.ask_language` | default | Aap kis bhasha mein baat karna chahenge? Abhi main {current} mein hoon. |
| `chatbot.line.reprompt_language` | default | Bas Hinglish, Hindi ya English chuniye, ya Skip dabaiye. |
| `chatbot.line.ack_language` | default | Theek hai, ab main {language} mein baat karungi. |
| `chatbot.line.ask_city` | default | Aap kis shehar mein hain? Shehar ka naam likhiye ya location pin bhejiye. |
| `chatbot.line.reprompt_city` | default | Shehar ka naam likhiye (jaise Pune), ya location pin bhejiye, ya Skip dabaiye. |
| `chatbot.line.ack_city` | default | {city}, achha! |
| `chatbot.line.ack_city_pin` | default | Location mil gayi. |
| `chatbot.line.ack_city_skip` | default | Theek hai, baad mein bata dena. |
| `chatbot.line.ask_win` | default | Chaliye pehla kaam karte hain. Kya try karein? |
| `chatbot.line.reprompt_win` | default | Upar se ek chuniye, ya 'menu' likhiye. |
| `chatbot.line.win_card` | default | Bas likhiye: 'mere paas HDFC Regalia card hai'. Sirf card ka naam, number kabhi nahi. |
| `chatbot.line.win_day` | default | Bataiye aage kya hai, jaise 'kal 2 baje interview hai'. Main yaad rakhungi. |
| `chatbot.line.win_call` | default | Likhiye 'mummy ko call karo ki main late hoon'. Call se pehle aapse OK lungi. |
| `chatbot.line.win_soon` | default | Yeh abhi pilot mein chalu nahi hai, jaldi aayega. Tab tak 'menu' likhiye. |
| `chatbot.line.done` | disclosure | Bas, itna hi! Kabhi bhi 'menu' likhiye. / Main AI assistant hoon: payment, OTP, PIN kabhi nahi maangti, sirf aapka apna data, jab chaho delete. |
| `chatbot.line.resume_prefix` | default | Wapas aaye, achha laga! Chaliye wahin se. |
| `chatbot.line.footer_short` | default | Friday AI assistant hai; payment, OTP, PIN kabhi nahi maangti. |
| `chatbot.line.menu_header` | default | Main Friday, aapki AI assistant. Yeh sab kar sakti hoon, chuniye: |
| `chatbot.line.mark_pilot` | default | (pilot) |
| `chatbot.line.mark_soon` | default | (jaldi) |
| `chatbot.line.hint_contact` | default | Kisi ka WhatsApp contact card bhejiye (attach, Contact). Main poochungi unhe kya bulaun: mummy, bhaiya... |
| `chatbot.line.hint_place` | default | Location pin bhejiye (attach, Location). Phir bataiye yeh ghar hai ya office. |
| `chatbot.line.hint_stop` | default | 'stop' likhiye, main khud se bheje jaane wale messages band kar dungi. |
| `chatbot.line.hint_human` | default | 'human' likhiye, koi insaan aapko yahin reply karega. |
| `chatbot.line.hint_delete` | default | 'delete everything' likhiye. Do step mein confirm hota hai, tab sab mita dungi. |
| `chatbot.line.stop_done` | default | Theek hai, ab main khud se message nahi bhejungi. Aap likhoge tabhi jawab dungi. Dobara chalu karne ke liye 'chalu karo' likhiye. |
| `chatbot.line.stop_already` | default | Maine pehle se hi khud se messages band kar rakhe hain. 'chalu karo' likhiye toh dobara shuru karungi. |
| `chatbot.line.resume_done` | default | Theek hai, ab main zaroorat par aapko khud se message bhejungi. Kabhi bhi 'stop' likhkar band kar sakte ho. |
| `chatbot.line.human_forwarded` | default | Maine aapki baat team ko bhej di. Koi insaan aapko yahin reply karega. |
| `chatbot.line.human_noted` | default | Maine note kar liya hai, par abhi support ka number set nahi hai. Jawab aane mein der ho sakti hai. |
| `chatbot.line.support_forward` | internal | Friday support: {name} ({phone}) insaan se baat karna chahte hain. Unka message: {text} |
| `chatbot.line.delete_confirm` | default | Yeh aapka sab data hamesha ke liye mita dega: profile, contacts, yaadein. Pakka? Confirm karne ke liye DELETE likhiye. |
| `chatbot.line.consent_renewed` | default | Shukriya, aapki haan note kar li. Kabhi bhi 'stop' ya 'delete everything' likh sakte ho. |
| `chatbot.line.consent_withdrawn` | default | Theek hai, ab main khud se message nahi bhejungi. Sab mitana ho toh 'delete everything' likhiye. |
| `chatbot.line.contact_ask_nick` | default | {name} ko kya bulaun? mummy, bhaiya... ya Skip. |
| `chatbot.line.contact_ask_nick_number` | default | Yeh number kiska hai? mummy, bhaiya ya naam likhiye, ya Skip. |
| `chatbot.line.contact_saved` | default | {who} save ho gaye: {masked}. Galat lage toh batayiye. |
| `chatbot.line.contact_invalid` | default | Yeh number sahi nahi lag raha. Poora 10 digit ka number dobara bhejiye. |
| `chatbot.line.contact_emergency` | default | Emergency number main save ya dial nahi karti. Zaroorat ho toh aap khud 112 par call karein. |
| `chatbot.line.contact_dropped` | default | Theek hai, contact save nahi kiya. |
| `chatbot.line.place_ask` | default | Yeh jagah kaunsi hai: ghar, office ya kuch aur? |
| `chatbot.line.place_reprompt` | default | Bas ek naam likhiye, jaise ghar ya office, ya Skip dabaiye. |
| `chatbot.line.place_saved` | default | {label} save ho gaya. Yeh sirf aapke vendor search mein kaam aayega, kisi ko share nahi hoga. |
| `chatbot.line.place_skipped` | default | Theek hai, jagah save nahi ki. |
| `chatbot.line.offtopic` | default | Main aapke kaam ke liye hoon: calls, bachat aur aapka din. Yeh sawaal alag hai, par maine note kar liya hai. 'menu' likhiye. |
| `chatbot.line.safety_emergency` | default | Yeh serious ho sakta hai. Abhi 112 par call kijiye ya paas ke hospital jaiye, intezaar mat kijiye. Main doctor nahi hoon, par aapke saath hoon. |
| `chatbot.line.safety_medicine` | default | Main dawai ya dose nahi bata sakti, yeh doctor ya pharmacist hi sahi bata sakte hain. Chahein toh main clinic ka pata karke appointment ke liye call kar sakti hoon. |
| `chatbot.line.refuse_forgery` | default | Nakli bill ya receipt main nahi bana sakti, yeh dhokha hota hai aur aap par bhaari pad sakta hai. Asli kharcha hua ho toh duplicate bill maangiye, uski photo bhejiye, main saaf PDF bana dungi. |
| `chatbot.line.lang_set` | default | Theek hai, ab se {language} mein jawab dungi. |
| `chatbot.line.quick_calc` | default | Jawab: {expr} = {result} |
| `chatbot.line.quick_time` | default | Abhi India mein {time} (IST) hue hain. |
| `chatbot.line.quick_date` | default | Aaj {date} hai. |
| `chatbot.line.why_generic` | default | Yeh isliye aaya ki aapne Friday se yeh madad maangi thi. Band karne ke liye 'stop' likhiye. |
| `chatbot.button.consent_yes` | button | Haan, theek hai |
| `chatbot.button.consent_details` | button | Details |
| `chatbot.button.consent_no` | button | Nahi |
| `chatbot.button.skip` | button | Skip |
| `chatbot.button.lang_hinglish` | button | Hinglish |
| `chatbot.button.lang_hi` | button | हिंदी |
| `chatbot.button.lang_en` | button | English |
| `chatbot.button.win_card` | button | Card jodo |
| `chatbot.button.win_day` | button | Mera din |
| `chatbot.button.win_call` | button | Kisi ko call |
| `chatbot.button.nick_mummy` | button | Mummy |
| `chatbot.button.nick_papa` | button | Papa |
| `chatbot.button.place_home` | button | Ghar |
| `chatbot.button.place_office` | button | Office |
| `chatbot.button.menu_open` | button | Menu dekhein |
| `chatbot.row.call` | list row | Kisi ko call karwao - Aapke liye call, aapke OK ke baad |
| `chatbot.row.card` | list row | Card se bachat - Kaun sa card, bills ke reminders |
| `chatbot.row.day` | list row | Mera din - Aaj kya hai, yaad rakhna |
| `chatbot.row.contact` | list row | Contact jodo - Contact card bhejo, nickname do |
| `chatbot.row.place` | list row | Jagah save karo - Ghar ya office ka location pin |
| `chatbot.row.stop` | list row | Messages band karo - Khud se bheje messages band |
| `chatbot.row.human` | list row | Insaan se baat - Team ka koi insaan reply karega |
| `chatbot.row.delete` | list row | Sab delete karo - Aapka sara data mita dungi |

## What is NOT verified

- Real WhatsApp rendering: reply buttons and the list message have only been checked as Graph API payloads and in the simulator; how they look on a phone, the button and list limits in practice, Devanagari and long titles are untested.
- Real template approval: no template has been submitted. Whether Meta accepts Roman Hinglish under language `en`, keeps UTILITY for the brief, nudge, bill, outcome and consent drafts, and how it prices them is unknown. The channel sends body parameters only, not button payloads; template button taps are mapped by title meanwhile.
- Real users' reactions: the two-minute goal, whether the intro is too long, whether the Hinglish, Hindi and English wording reads naturally, whether testers find `menu`, whether the off-topic detector annoys or misses. The Hindi and English lines are drafts by the builder, not reviewed by a native speaker.
- The off-topic detector is a short rule list, not a model. It will miss some questions and is tuned to never catch a real task; tune it from the wishlist.
- Support forwarding on a live number (the 24-hour window of the founder's phone), reverse geocoding with the real geocoder, voice-note answers to the onboarding questions (they are treated as text through the existing transcription).
- Postgres: migration `0010_chatbot` and the new tables ran on SQLite only (the same caveat as migrations 0006 to 0009).
- `friday/chatbot/templates.py` reads the YAML with PyYAML, which is installed with `uvicorn[standard]` but is not listed as its own dependency.

## Steps for the founder to turn it on for testers

1. Read and approve the wording: the table above (or `friday/chatbot/copy.py`) and `docs/WHATSAPP_TEMPLATES.md`. Send corrections; the words can change without touching code.
2. Apply the database change on the server: `uv run python -m friday.db.migrate up` (head is `0010_chatbot`), then `uv run friday doctor` (must PASS).
3. In the server's `.env` (never in git) set: `FRIDAY_CHATBOT_ONBOARDING=true`, `FRIDAY_PILOT=true`, `FRIDAY_CHATBOT_TESTERS=<tester numbers, E.164, comma separated>`, `FRIDAY_SUPPORT_INBOX=<your WhatsApp number>`. Switch on the features you want testers to meet (`FRIDAY_SAVINGS_ENABLED`, `FRIDAY_LIFESTATE_ENABLED`, `FRIDAY_CONSUMER_CALLS_ENABLED`, per `docs/CONSUMER_INTEGRATION.md`; calls stay limited by the existing allow-list and the missing telephony factory). Restart Friday.
4. From your own phone message the Friday number once (this opens your 24-hour window so `human` requests can reach you).
5. Walk through it yourself from a tester number: `hi`, tap Haan, name, language, city, a first win, then `menu`, a contact card, a location pin, `human`, `stop`, `chalu karo`, a joke request, `delete everything` then `DELETE`. Check `uv run friday chatbot status`.
6. From a number that is not on the list, send `hi`: it must get the waitlist reply and nothing else. `uv run friday chatbot status` shows it on the waitlist.
7. Add testers by adding their numbers to `FRIDAY_CHATBOT_TESTERS` and restarting. Look at `uv run friday chatbot wishlist` and `--support` every day during the pilot.
8. Templates: run `uv run friday chatbot templates check`, approve the bodies, submit them in Meta WhatsApp Manager as described in `docs/WHATSAPP_TEMPLATES.md`; until they are approved the generic templates keep working.
9. Off switch: `FRIDAY_CHATBOT_ONBOARDING=false` and restart (people already onboarded keep their accounts and the old flows); `friday pause` still stops proactive messages and calls at once.

## Decisions for the founder (recommended option implemented, alternatives configurable)

1. **Where the "never" statement appears.** Implemented: in full on the intro, the details, the waitlist reply and the closing message, and in every proactive text and template body. Alternative: also as a one-line footer on every onboarding step (`FRIDAY_CHATBOT_DISCLOSURE_EVERY_STEP=true`).
2. **Allow-list.** Implemented: `FRIDAY_PILOT_ALLOWED_NUMBERS` + `FRIDAY_CHATBOT_TESTERS` + admins. Alternative: use only a separate list.
3. **Pilot off + invite-only on** leaves the invite-code onboarding untouched (the chatbot does not bypass invites).
4. **No PIN in the chatbot onboarding.** Chatbot users have no PIN, so `delete everything` is confirmed by typing `DELETE` (no PIN); W4's own `haan, sab mita do` still exists beside it (open decision 25 in `docs/CONSUMER_DECISIONS.md`). Users who set a PIN keep the PIN path.
5. **A request sent before consent is not kept.** The person has to repeat it after saying Haan.
6. **Shared contact cards** go to the user's contact book (nickname, masked confirmation) instead of becoming a circle member as the brain does today, while the chatbot is on.
7. **First wins** are offered only for features whose switch is on; with none on, onboarding ends after the city. The order is configurable.
8. **Off-topic**: redirect + wishlist (the recommended choice 2 of the architecture note); `wishlist_only` and `off` are one setting away.
9. **Templates**: Roman Hinglish registered as Meta language `en`, Hindi as `hi`, plain English under its own `_en_` name; the re-engage draft is MARKETING, the others UTILITY.
10. **Stop** pauses every proactive category (bills, follow-ups, brief) in one word; the per-topic mute remains the life-state `mat poocho`.

## Files

`friday/chatbot/`: `copy.py` (all words), `composer.py` (quality rules, language mirroring), `commands.py` (command and answer parsing), `scope.py` (off-topic test, masking), `service.py` (the flow), `templates.py` + `templates.yaml` (template drafts and checker), `cli.py` (`friday chatbot`), `dbmodel.py`. Also `friday/db/repositories/chatbot.py`, migration `0010_chatbot`, hooks in `friday/api/inbound.py`, settings in `friday/core/config.py`, `ListMenu` in `friday/core/models.py` with list sending in `friday/channels/whatsapp.py` and rendering in `friday/channels/simulator.py`.
Tests: `uv run pytest tests/chatbot -q`.

## PENDING FOUNDER APPROVAL: refund tracking wording (item C)

85 more copy ids (lines, buttons, state names) in `friday/refunds/copy.py`, Roman Hinglish and English, all `PENDING_FOUNDER_APPROVAL`, behind `FRIDAY_REFUNDS_ENABLED` (OFF). The full id list is in `docs/REFUNDS.md`. Plus three pending vendor-call questions (`VENDOR_CALL_QUESTIONS`): no real call can start while `copy.CALL_LINE_STATUS` is pending.
