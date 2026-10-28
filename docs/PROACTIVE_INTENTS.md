# Proactive intents (chat): honest capability replies, playbooks, fragments

Switch: `FRIDAY_PROACTIVE_INTENTS_ENABLED` (default OFF; `deploy/enable-web-test.sh` turns it on and prints the name only).
Code: `friday/intents/gateway.py`. Data table (all wording): `friday/intents/playbooks.yaml`.
Position: `InboundPipeline._active`, after the chatbot and features, BEFORE the query-understanding team and the approach planner. Switch off: nothing is built, nothing changes.

Trigger: the founder's first web-chat test. 'Mera gmail check krna' got a flat 'Maaf kijiye, isme main madad nahi kar sakti.' (that line is the approach planner's DECLINE, `friday/planner/wording.py`, which this work does not touch); 'Kal' and 'interview hainkal' got generic reactive questions.

## What it does
1. **Honest capability replies** (Gmail, Calendar, Drive, ordering apps). It says what it needs, what happens next, and the nearest thing Friday can do now. A connect link is sent ONLY when the Google connector is configured on this server (client id, secret and redirect URI set, consumer Google switch on); otherwise it says plainly it is not set up yet. Gmail also checks `FRIDAY_GOOGLE_GMAIL_ENABLED`. Reading the inbox from chat does not exist yet, so even a connected Gmail gets the paste-the-email fallback. 'connect/disconnect/status google' stays with the existing Google flow.
2. **Playbooks** (interview, birthday, trip, bill, exam, meeting): one proposal, 2-3 buttons, at most ONE question per message. Reminder = a DATE fact in memory (`Fact`, day level; no exact time is invented or promised). 'Prep / packing / gift / revision' asks one question, then the answer is handed to the normal chain as a plain request. Messages that are questions ('interview mein kya poochte hain?') are not hijacked; messages longer than 300 characters (pasted content) are never touched.
3. **Fragments**: the open intent is kept for 15 minutes in memory. 'Kal / aaj / parso' (or the button) fills the date slot; merged typos ('interview hainkal') are split by a small rule; when `FRIDAY_QUERY_UNDERSTANDING_ENABLED` is on and the rules find nothing, the query-understanding agent's rewritten instruction is tried.

## Known limits
- Other unsupported requests are still declined by the planner's `decline` line when `FRIDAY_APPROACH_PLANNER_ENABLED` is on; that line lives in `friday/planner` (another builder's area) and should get the same honest 'needs / next / nearest' form.
- Devanagari users get the Roman Hinglish lines (mirrored script is not built).
- The state is in memory (lost on restart, like the planner's).

## New chat lines: ALL PENDING founder approval (hear/read before change)
Placeholders: `{when}` = aaj/kal/parso (Hinglish), today/tomorrow/the day after tomorrow (English).

| Key | English | Hinglish |
|---|---|---|
| ask date | "{Label} - got it. Is it today, tomorrow or the day after?" [Today][Tomorrow][Day after] | "{Label} - samajh gayi. Aaj hai, kal ya parso?" [Aaj][Kal][Parso] |
| interview | "Interview {when}, all the best! Shall I set a reminder for that day, and make prep points if you tell me the company and role?" [Remind me][Prep points][Not now] | "Interview {when} hai, all the best! Us din ka reminder laga dun, aur company aur role bata dein toh prep points bhi bana dungi?" [Reminder lagao][Prep points][Abhi nahi] |
| interview prep | "Sure. Which company and which role?" | "Zaroor. Kaun si company aur kaun sa role?" |
| birthday | "Birthday {when}! Want a wish reminder that day, or gift ideas if you tell me who it is and the budget?" | "Birthday {when} hai! Us din wish ka reminder laga dun, ya kiska hai aur budget bata dein toh gift ideas dun?" |
| own birthday | "Happy birthday! Want me to find a place for dinner {when}?" [Find a place][Not now] | "Happy birthday! {when} dinner ke liye koi jagah dhoondh dun?" [Jagah dhoondho][Abhi nahi] |
| birthday gift | "Sure. Who is it for, and what's the budget?" | "Zaroor. Kiske liye, aur budget kitna hai?" |
| trip | "Trip {when}! Want a reminder for that day, and a packing list if you tell me where to and for how many days?" | "Trip {when} hai! Us din ka reminder laga dun, aur kahan jana hai aur kitne din, bata dein toh packing list bana dun?" |
| trip packing | "Sure. Where to, and for how many days?" | "Zaroor. Kahan jana hai aur kitne din ke liye?" |
| bill (no date) | "Bill due - got it. When is it due, and which bill?" | "Bill due hai - samajh gayi. Kab due hai, aur kaun sa bill?" |
| bill | "Bill due {when}. Shall I remind you that day? You pay in your own app, I never pay." | "Bill {when} due hai. Us din yaad dila dun? Payment aap apne app se karein, main kabhi pay nahi karti." |
| exam | "Exam {when}, all the best! Want a reminder that day, or a quick revision plan if you tell me the subject and hours left?" | "Exam {when} hai, all the best! Us din ka reminder laga dun, ya subject aur bache hue ghante bata dein toh revision plan dun?" |
| exam plan | "Sure. Which subject, and how many hours do you have?" | "Zaroor. Kaun sa subject, aur kitne ghante hain?" |
| meeting | "Meeting {when}. Want a reminder that day, and prep notes if you tell me who it's with and the topic?" | "Meeting {when} hai. Us din ka reminder laga dun, aur kisse hai aur topic kya hai bata dein toh prep notes bana dun?" |
| meeting prep | "Sure. Who is it with, and what's the topic?" | "Zaroor. Kisse meeting hai aur topic kya hai?" |
| reminder done | "Done, I'll remind you {when}." | "Ho gaya, {when} yaad dila dungi." |
| not now | "Okay. I'm here whenever you need me." | "Theek hai. Zarurat ho toh bataiye." |
| expired button | "That option has expired. Tell me again what's coming up." | "Woh option purana ho gaya. Dobara bata dein kya hai." |
| Gmail, no link possible | "I can't read your Gmail yet: the Google connection isn't set up on my side. Until then, paste the email text here and I'll summarise it or draft a reply." | "Abhi main aapka Gmail nahi dekh sakti: Google connection mere yahan set up nahi hua hai. Tab tak email ka text yahan paste kijiye, main summary ya reply draft kar dungi." |
| Gmail, reading off | "I can't read your Gmail yet: reading email isn't switched on on my side. (+ paste line)" | "Abhi main aapka Gmail nahi dekh sakti: email padhna mere yahan chalu nahi hua hai. (+ paste line)" |
| Gmail, link | "I need to connect your Gmail first. Open this link (valid 10 minutes): {link}" + paste line | "Pehle aapka Gmail connect karna hoga. Yeh link kholiye (10 minute valid): {link}" + paste line |
| Gmail, connected | "Your Gmail is connected, but I can't read the inbox from chat yet. (+ paste line)" | "Aapka Gmail juda hua hai, par chat se inbox padhna abhi nahi hota. (+ paste line)" |
| Gmail fragment | "Noted, {when}. I still can't open your Gmail myself: paste the email text here and I'll handle it." | "Theek hai, {when}. Main khud abhi aapka Gmail nahi khol sakti: email ka text yahan paste kijiye, main dekh lungi." |
| Calendar (same four states, link, fragment) | see `playbooks.yaml` capabilities.calendar | same |
| Drive | "I can't open your Google Drive from chat yet. Send the photo or PDF here and I'll read it for you." | "Abhi main chat se aapka Google Drive nahi khol sakti. Photo ya PDF yahan bhej dein, main padh lungi." |
| Ordering app | "I can't place orders inside apps yet. I can check prices or the menu on the web. Which item?" | "Abhi main apps ke andar order nahi laga sakti. Web par daam ya menu dekh sakti hoon. Kaun sa item?" |

Tests: `tests/intents/test_intents.py` (fakes only; the three founder phrases, Google configured / client id missing / Gmail scope off / not wired, one-question rule, fragment resolution, switch off).
