# WhatsApp templates for messages outside the 24-hour window

STATUS: DRAFT, PENDING_FOUNDER_APPROVAL. Nothing here has been submitted to Meta. The words
are not approved; real template approval by Meta is not verified.

This file is GENERATED from `friday/chatbot/templates.yaml` (edit that file, then run
`uv run friday chatbot templates render > docs/WHATSAPP_TEMPLATES.md`). Check it with
`uv run friday chatbot templates check` (placeholders, buttons, the plain statement, names
against `friday/core/templates.py` and `Settings.whatsapp_templates`, and every sender in
the code).

How to register (Meta WhatsApp Manager, Message templates):
1. Each draft below is registered under its `name` twice: language `en` with the Roman
   Hinglish text (the product default) and language `hi` with the Devanagari text. The plain
   English text is a separate name (`..._en_v1`, language `en`). Choose the category shown.
2. Paste the body exactly, with the example values as the sample for {{1}}, {{2}}...
3. Add the quick-reply buttons in the order shown (titles up to 25 characters).
4. The chatbot passes the logical `key` as `TemplateRef.key`; `Settings.whatsapp_templates`
   maps it to the Meta name (`FRIDAY_WHATSAPP_TEMPLATES` can override a name).
5. Until a draft is approved the generic fallback named in each section keeps being used.

| Logical key | Meta name | Category | Variables | Generic fallback |
|---|---|---|---|---|
| `chatbot_morning_brief` | `friday_morning_brief_v1` (+ `friday_morning_brief_en_v1`) | UTILITY | 2 | `nudge` |
| `chatbot_followup` | `friday_followup_v1` (+ `friday_followup_en_v1`) | UTILITY | 2 | `nudge` |
| `chatbot_bill_reminder` | `friday_bill_reminder_v1` (+ `friday_bill_reminder_en_v1`) | UTILITY | 3 | `nudge` |
| `chatbot_call_outcome` | `friday_call_outcome_v1` (+ `friday_call_outcome_en_v1`) | UTILITY | 3 | `task_update` |
| `chatbot_reengage` | `friday_reengage_hello_v1` (+ `friday_reengage_hello_en_v1`) | MARKETING | 2 | `reengage` |
| `chatbot_consent` | `friday_consent_again_v1` (+ `friday_consent_again_en_v1`) | UTILITY | 1 | `reengage` |

## `friday_morning_brief_v1` (UTILITY)

The morning brief, for a user who opted in to it, when the 24-hour window is closed.

Variables: {{1}} = user's first name; {{2}} = the brief text (one line, items joined with a dot)

Examples: {{1}} = 'Rahul'; {{2}} = 'Aaj 11 baje meeting, shaam 6 baje bijli ka bill due'

Why sentence (must be in every body): Yeh isliye aaya ki aapne subah ka brief chuna tha.

### Roman Hinglish: name `friday_morning_brief_v1`, language `en`, key `chatbot_morning_brief`

```text
Namaste {{1}}, Friday (AI assistant) ka subah ka brief: {{2}}
Yeh isliye aaya ki aapne subah ka brief chuna tha. Band karne ke liye 'stop' likhiye.
Main payment, OTP, PIN kabhi nahi maangti; sirf aapka apna data, jab chaho delete.
```

Buttons: "Theek hai" (payload `cb:tpl:ok`, action ok), "Brief band karo" (payload `cb:tpl:stop`, action stop)

### Hindi: name `friday_morning_brief_v1`, language `hi`, key `chatbot_morning_brief`

```text
नमस्ते {{1}}, Friday (AI असिस्टेंट) का सुबह का ब्रीफ़: {{2}}
यह इसलिए आया कि आपने सुबह का ब्रीफ़ चुना था। बंद करने के लिए 'stop' लिखें।
मैं पेमेंट, OTP, PIN कभी नहीं माँगती; सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।
```

Buttons: "ठीक है" (payload `cb:tpl:ok`, action ok), "ब्रीफ़ बंद करो" (payload `cb:tpl:stop`, action stop)

### English: name `friday_morning_brief_en_v1`, language `en`, key `chatbot_morning_brief_en`

```text
Hello {{1}}, your morning brief from Friday (AI assistant): {{2}}
You're getting this because you chose a morning brief. Write 'stop' to turn it off.
I never ask for payment, OTP or PIN; only your own data, and you can delete it anytime.
```

Buttons: "Okay" (payload `cb:tpl:ok`, action ok), "Stop the brief" (payload `cb:tpl:stop`, action stop)

## `friday_followup_v1` (UTILITY)

One follow-up question after something the user asked to be reminded about.

Variables: {{1}} = user's first name; {{2}} = the follow-up question

Examples: {{1}} = 'Rahul'; {{2}} = 'Kal ka interview kaisa raha?'

Why sentence (must be in every body): Yeh isliye pooch rahi hoon ki aapne is baare mein yaad dilane ko kaha tha.

### Roman Hinglish: name `friday_followup_v1`, language `en`, key `chatbot_followup`

```text
Namaste {{1}}, Friday (AI assistant) ki taraf se ek chhota sawaal: {{2}}
Yeh isliye pooch rahi hoon ki aapne is baare mein yaad dilane ko kaha tha. 'stop' likhiye toh band.
Main payment, OTP, PIN kabhi nahi maangti; sirf aapka apna data, jab chaho delete.
```

Buttons: "Abhi nahi" (payload `cb:tpl:ok`, action ok), "Mat poocho" (payload `cb:tpl:stop`, action stop)

### Hindi: name `friday_followup_v1`, language `hi`, key `chatbot_followup`

```text
नमस्ते {{1}}, Friday (AI असिस्टेंट) की तरफ़ से एक छोटा सवाल: {{2}}
यह इसलिए पूछ रही हूँ कि आपने इस बारे में याद दिलाने को कहा था। 'stop' लिखें तो बंद।
मैं पेमेंट, OTP, PIN कभी नहीं माँगती; सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।
```

Buttons: "अभी नहीं" (payload `cb:tpl:ok`, action ok), "मत पूछो" (payload `cb:tpl:stop`, action stop)

### English: name `friday_followup_en_v1`, language `en`, key `chatbot_followup_en`

```text
Hello {{1}}, a quick question from Friday (AI assistant): {{2}}
I'm asking because you asked me to follow up on this. Write 'stop' and I'll stop asking.
I never ask for payment, OTP or PIN; only your own data, and you can delete it anytime.
```

Buttons: "Not now" (payload `cb:tpl:ok`, action ok), "Stop asking" (payload `cb:tpl:stop`, action stop)

## `friday_bill_reminder_v1` (UTILITY)

A bill the user told Friday about is due soon. Friday never pays it.

Variables: {{1}} = user's first name; {{2}} = which bill (name only); {{3}} = when it is due

Examples: {{1}} = 'Rahul'; {{2}} = 'bijli'; {{3}} = '25 January'

Why sentence (must be in every body): Yeh isliye aaya ki aapne bill ke reminders chune the.

### Roman Hinglish: name `friday_bill_reminder_v1`, language `en`, key `chatbot_bill_reminder`

```text
Namaste {{1}}, Friday (AI assistant) yaad dila rahi hai: {{2}} ka bill {{3}} tak due hai.
Yeh isliye aaya ki aapne bill ke reminders chune the. 'stop' likhiye toh band.
Main payment kabhi nahi karti aur OTP, PIN nahi maangti; sirf aapka apna data, jab chaho delete.
```

Buttons: "Theek hai" (payload `cb:tpl:ok`, action ok), "Reminder band karo" (payload `cb:tpl:stop`, action stop)

### Hindi: name `friday_bill_reminder_v1`, language `hi`, key `chatbot_bill_reminder`

```text
नमस्ते {{1}}, Friday (AI असिस्टेंट) याद दिला रही है: {{2}} का बिल {{3}} तक देय है।
यह इसलिए आया कि आपने बिल के रिमाइंडर चुने थे। 'stop' लिखें तो बंद।
मैं पेमेंट कभी नहीं करती और OTP, PIN नहीं माँगती; सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।
```

Buttons: "ठीक है" (payload `cb:tpl:ok`, action ok), "रिमाइंडर बंद करो" (payload `cb:tpl:stop`, action stop)

### English: name `friday_bill_reminder_en_v1`, language `en`, key `chatbot_bill_reminder_en`

```text
Hello {{1}}, Friday (AI assistant) is reminding you: your {{2}} bill is due by {{3}}.
You're getting this because you chose bill reminders. Write 'stop' to turn them off.
I never make payments and never ask for OTP or PIN; only your own data, and you can delete it anytime.
```

Buttons: "Okay" (payload `cb:tpl:ok`, action ok), "Stop reminders" (payload `cb:tpl:stop`, action stop)

## `friday_call_outcome_v1` (UTILITY)

The result of a call Friday made for the user, after the user approved it.

Variables: {{1}} = user's first name; {{2}} = who was called; {{3}} = what happened (one line)

Examples: {{1}} = 'Rahul'; {{2}} = 'Mummy'; {{3}} = 'Unhone kaha ki wo 8 baje tak aa jayengi'

Why sentence (must be in every body): Yeh isliye aaya ki yeh call aapke kehne par, aapke OK ke baad lagayi gayi thi.

### Roman Hinglish: name `friday_call_outcome_v1`, language `en`, key `chatbot_call_outcome`

```text
Namaste {{1}}, Friday (AI assistant): {{2}} ko ki gayi aapki call ka nateeja: {{3}}
Yeh isliye aaya ki yeh call aapke kehne par, aapke OK ke baad lagayi gayi thi. 'stop' likhiye toh band.
Main payment, OTP, PIN kabhi nahi maangti; sirf aapka apna data, jab chaho delete.
```

Buttons: "Theek hai" (payload `cb:tpl:ok`, action ok), "Kuch galat hai" (payload `cb:tpl:human`, action human)

### Hindi: name `friday_call_outcome_v1`, language `hi`, key `chatbot_call_outcome`

```text
नमस्ते {{1}}, Friday (AI असिस्टेंट): {{2}} को की गई आपकी कॉल का नतीजा: {{3}}
यह इसलिए आया कि यह कॉल आपके कहने पर, आपके OK के बाद लगाई गई थी। 'stop' लिखें तो बंद।
मैं पेमेंट, OTP, PIN कभी नहीं माँगती; सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।
```

Buttons: "ठीक है" (payload `cb:tpl:ok`, action ok), "कुछ गलत है" (payload `cb:tpl:human`, action human)

### English: name `friday_call_outcome_en_v1`, language `en`, key `chatbot_call_outcome_en`

```text
Hello {{1}}, Friday (AI assistant): the result of your call to {{2}}: {{3}}
You're getting this because you asked for this call and approved it. Write 'stop' to turn it off.
I never ask for payment, OTP or PIN; only your own data, and you can delete it anytime.
```

Buttons: "Okay" (payload `cb:tpl:ok`, action ok), "Something is wrong" (payload `cb:tpl:human`, action human)

## `friday_reengage_hello_v1` (MARKETING)

One gentle ping to a user who has gone quiet for days. Sent at most once.

Variables: {{1}} = user's first name; {{2}} = one short line about what Friday can do for them now

Examples: {{1}} = 'Rahul'; {{2}} = 'Kal ke kaam ya bill yaad dilane mein madad chahiye to bataiye.'

Why sentence (must be in every body): Yeh isliye bheja ki aapne kuch din se baat nahi ki; sirf ek baar poochungi.

### Roman Hinglish: name `friday_reengage_hello_v1`, language `en`, key `chatbot_reengage`

```text
Namaste {{1}}, Friday (AI assistant) yahan hai. {{2}}
Yeh isliye bheja ki aapne kuch din se baat nahi ki; sirf ek baar poochungi. 'stop' likhiye toh dobara nahi bhejungi.
Main payment, OTP, PIN kabhi nahi maangti; sirf aapka apna data, jab chaho delete.
```

Buttons: "Haan, batao" (payload `cb:tpl:ok`, action ok), "Abhi nahi" (payload `cb:tpl:ok`, action ok), "Stop" (payload `cb:tpl:stop`, action stop)

### Hindi: name `friday_reengage_hello_v1`, language `hi`, key `chatbot_reengage`

```text
नमस्ते {{1}}, Friday (AI असिस्टेंट) यहाँ है। {{2}}
यह इसलिए भेजा कि आपने कुछ दिन से बात नहीं की; सिर्फ़ एक बार पूछूँगी। 'stop' लिखें तो दोबारा नहीं भेजूँगी।
मैं पेमेंट, OTP, PIN कभी नहीं माँगती; सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।
```

Buttons: "हाँ, बताओ" (payload `cb:tpl:ok`, action ok), "अभी नहीं" (payload `cb:tpl:ok`, action ok), "Stop" (payload `cb:tpl:stop`, action stop)

### English: name `friday_reengage_hello_en_v1`, language `en`, key `chatbot_reengage_en`

```text
Hello {{1}}, Friday (AI assistant) here. {{2}}
I'm sending this because we haven't talked for a few days; I'll ask only once. Write 'stop' and I won't send it again.
I never ask for payment, OTP or PIN; only your own data, and you can delete it anytime.
```

Buttons: "Yes, tell me" (payload `cb:tpl:ok`, action ok), "Not now" (payload `cb:tpl:ok`, action ok), "Stop" (payload `cb:tpl:stop`, action stop)

## `friday_consent_again_v1` (UTILITY)

Ask the user to agree again when the wording they agreed to changed or has lapsed.

Variables: {{1}} = user's first name

Examples: {{1}} = 'Rahul'

Why sentence (must be in every body): Yeh isliye pooch rahi hoon ki pehli haan purane shabdon par thi.

### Roman Hinglish: name `friday_consent_again_v1`, language `en`, key `chatbot_consent`

```text
Namaste {{1}}, Friday (AI assistant) ke niyam badle hain, isliye aapki haan dobara chahiye.
Yeh isliye pooch rahi hoon ki pehli haan purane shabdon par thi. 'stop' likhiye ya Nahi dabaiye toh main khud se message nahi bhejungi.
Main payment, OTP, PIN kabhi nahi maangti; sirf aapka apna data, jab chaho delete.
```

Buttons: "Haan, theek hai" (payload `cb:consent:yes`, action consent_yes), "Nahi" (payload `cb:consent:no`, action consent_no), "Details" (payload `cb:tpl:details`, action details)

### Hindi: name `friday_consent_again_v1`, language `hi`, key `chatbot_consent`

```text
नमस्ते {{1}}, Friday (AI असिस्टेंट) के नियम बदले हैं, इसलिए आपकी हाँ दोबारा चाहिए।
यह इसलिए पूछ रही हूँ कि पहली हाँ पुराने शब्दों पर थी। 'stop' लिखें या नहीं दबाएँ तो मैं अपने-आप मैसेज नहीं भेजूँगी।
मैं पेमेंट, OTP, PIN कभी नहीं माँगती; सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।
```

Buttons: "हाँ, ठीक है" (payload `cb:consent:yes`, action consent_yes), "नहीं" (payload `cb:consent:no`, action consent_no), "विवरण" (payload `cb:tpl:details`, action details)

### English: name `friday_consent_again_en_v1`, language `en`, key `chatbot_consent_en`

```text
Hello {{1}}, Friday (AI assistant) has changed its terms, so I need your yes again.
I'm asking because your first yes was given to older wording. Write 'stop' or tap No and I won't message you on my own.
I never ask for payment, OTP or PIN; only your own data, and you can delete it anytime.
```

Buttons: "Yes, okay" (payload `cb:consent:yes`, action consent_yes), "No" (payload `cb:consent:no`, action consent_no), "Details" (payload `cb:tpl:details`, action details)

## Notes and open points

- Meta may re-categorise a UTILITY template as MARKETING (and charge accordingly). The
  re-engage draft is submitted as MARKETING on purpose; the others are UTILITY because they
  carry something the user asked for.
- Roman Hinglish is submitted under language code `en` because Meta has no Hinglish code;
  whether Meta accepts that is NOT verified.
- The WhatsApp channel (`friday/channels/whatsapp.py`) sends body parameters only, not button
  payloads; a tap on a template button arrives with the button title, which the chatbot maps
  with `button_action` (`friday/chatbot/templates.py`). Sending payloads is a later change.
- Nothing sends these templates yet: the notifier still falls back to the generic ones
  (`nudge`, `task_update`, `reengage`). `chatbot_template(key, params, lang)` builds the
  reference once a draft is approved and a sender is switched over.

