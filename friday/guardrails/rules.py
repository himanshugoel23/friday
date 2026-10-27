# ruff: noqa: E501
"""Rule tables for the NEW categories (Hinglish, Hindi in Devanagari and English). The rules for the
categories that already existed (emergency, medicine, fake bill, off-topic, quick facts) are in
:mod:`friday.guardrails.legacy` and :mod:`friday.guardrails.scope` and are reused, not copied.

Every pattern is matched against the folded views of the message (:mod:`friday.guardrails.normalize`).
Devanagari patterns avoid ``\\b`` (combining vowel signs are not word characters in ``re``).
Each rule has an id (``category.name``) that goes into the audit log and the eval report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from friday.guardrails.models import Category

_I = re.IGNORECASE


@dataclass(frozen=True)
class Rule:
    id: str
    category: Category
    pattern: re.Pattern[str]
    exempt: re.Pattern[str] | None = None

    def matches(self, view: str) -> bool:
        return bool(self.pattern.search(view)) and not (self.exempt and self.exempt.search(view))


def _r(cat: Category, name: str, pattern: str, exempt: str | None = None) -> Rule:
    return Rule(f"{cat.value}.{name}", cat, re.compile(pattern, _I), re.compile(exempt, _I) if exempt else None)


# words that turn an "advice" sentence into a plain request for Friday to act ("vakil ko call karo")
_ACT = r"\b(?:call\s+(?:karo|kar|kardo|krna|karna|lagao)|phone\s+karo|appointment|book\s+(?:karo|kar)|remind\w*|yaad\s+dila\w*|reminder)\b|कॉल\s+कर"

SELF_HARM = [
    _r(Category.SELF_HARM, "en", r"\b(?:kill(?:ing)?\s+my\s*self|end\s+(?:my\s+life|it\s+all)|want\s+to\s+die|wanna\s+die|(?:do\s*n'?t|dont|do\s+not)\s+want\s+to\s+(?:live|be\s+alive|exist)|no\s+reason\s+to\s+(?:live|go\s+on)|better\s+off\s+(?:dead|without\s+me)|hurt(?:ing)?\s+my\s*self|cut(?:ting)?\s+my\s+(?:wrists?|self)|self[\s\-]?harm|suicid\w*|take\s+my\s+(?:own\s+)?life|(?:end|ending)\s+my\s+life|wan+t+\s+to\s+di+e+|not\s+worth\s+living|hang\s+my\s*self)\b"),
    _r(Category.SELF_HARM, "hinglish", r"\b(?:mar\s*ja(?:na|un|aun|oon|unga|ungi)\b|marna\s+chah\w*|jeene\s+ka\s+(?:mann|man|mood|dil)\s+(?:nahi|nhi|nai)|jeena\s+(?:nahi|nhi)\s+chah\w*|jee\s*ne\s+ki\s+ichha\s+(?:nahi|nhi)|khud\s+ko\s+(?:khatam|maar|hurt|nuksan|chot)\w*|apni\s+jaan\s+(?:de|le)\w*|jaan\s+de\s+du\w*|zindagi\s+(?:khatam|se\s+tang)|sab\s+khatam\s+kar\w*|khudkushi|aatmahatya|suicide|zeher\s+kha\s+(?:lu|loon|lun))"),
    _r(Category.SELF_HARM, "hindi", r"(?:मरना\s+चाह|मर\s+जाना\s+चाह|मर\s+जाऊं|मर\s+जाऊँ|जीने\s+का\s+मन\s+नहीं|जीना\s+नहीं\s+चाह|खुद\s+को\s+(?:खत्म|मार|नुकसान|चोट)|आत्महत्या|खुदकुशी|अपनी\s+जान\s+(?:दे|ले)|ज़िंदगी\s+खत्म|जिंदगी\s+खत्म|जहर\s+खा)"),
]

EMERGENCY_EXTRA = [
    _r(Category.EMERGENCY, "en", r"\b(?:ambulance|on\s+fire|house\s+(?:is\s+)?on\s+fire|fire\s+(?:in|at)\s+(?:my|the)|bleeding\s+(?:a\s+lot|heavily|badly|non\s*stop)|severe\s+bleeding|snake\s*bite|having\s+a\s+seizure|stroke|accident\s+ho\s+gaya|poisoned|swallowed\s+(?:poison|acid))\b"),
    _r(Category.EMERGENCY, "hinglish", r"\b(?:aag\s+lag\w*|ambulance\s+(?:bulao|chahiye|bhejo)|khoon\s+(?:bahut\s+)?beh\s+r\w*|saap\s+ne\s+kaat\w*|daura\s+pad\w*|accident\s+ho\s+g\w*|mirgi\s+ka\s+daura|zeher\s+kha\s+li\w*|bachao)\b"),
    _r(Category.EMERGENCY, "hindi", r"(?:आग\s+लग|एम्बुलेंस|एंबुलेंस|खून\s+बह|साँप\s+ने\s+काट|सांप\s+ने\s+काट|दौरा\s+पड़|बचाओ)"),
]

MINORS = [
    _r(Category.MINORS, "age_en", r"\b(?:i\s*(?:am|'m)|im|my\s+age\s+is|age\s*[:\-])\s*(?:only\s+|just\s+)?(?:[5-9]|1[0-7])(?:\s*(?:years?|yrs?|y/?o|year[\s\-]*old|saal)\b|\s*$|\s*[.!,])"),
    _r(Category.MINORS, "age_hinglish", r"\b(?:main|mai|mein|meri\s+umar|meri\s+age|meri\s+umr)\s*(?:abhi\s+|sirf\s+|bas\s+)?(?:[5-9]|1[0-7])\s*(?:saal|sal|years?|varsh)\b|\bumar\s+(?:[5-9]|1[0-7])\s*(?:saal|sal|hai)\b|\b(?:[5-9]|1[0-7])\s*(?:saal|sal)\s+(?:ka|ki)\s+(?:hoon|hun|hu|hu\.)\b"),
    _r(Category.MINORS, "age_hindi", r"(?:मैं|मेरी\s+उम्र|उम्र)\s*(?:अभी\s+|सिर्फ़\s+|सिर्फ\s+)?(?:[5-9]|1[0-7])\s*(?:साल|वर्ष)"),
    _r(Category.MINORS, "words", r"\b(?:i\s*(?:am|'m)\s+(?:a\s+)?(?:minor|underage|under\s*18|under\s+age)|under\s*18|minor\s+hoon|abhi\s+18\s+(?:ka|ki|ke)\s+(?:nahi|nhi)|18\s+se\s+kam|nabalig|class\s+(?:[5-9]|1[0-2])\s*(?:mein|me|m|ka|ki)?\s+(?:padh\w*|student|hoon|hu)|(?:[5-9]|1[0-2])(?:th|vi[n]?)\s+(?:class|standard)\s+(?:mein|me|m)\s+(?:padh\w*|hoon|hu)|school\s+(?:mein|me)\s+padh\w*|school\s+student|high\s*school\s+student)\b|नाबालिग|18\s+से\s+कम"),
]

MEDICAL = [
    _r(Category.MEDICAL_ADVICE, "dose", r"\bhow\s+(?:many|much)\s+(?:[\w']+\s+){0,2}(?:tablets?|pills?|capsules?|mg|ml|goli|drops?)\b|\b(?:dose|dosage)\s+(?:of|for|kitni|kitna)\b|\bkitni\s+(?:goli|tablet)\b|(?:कौन\s+सी|कौनसी|कौन\s+सा)\s+(?:दवा|दवाई|गोली)|दवा\s+(?:लूँ|लूं|लेनी|बताओ)", exempt=_ACT),
]

PROMPT_INJECTION = [
    _r(Category.PROMPT_INJECTION, "ignore", r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|your\s+|the\s+|every\s+)?(?:previous|prior|above|earlier|system|safety|your|these)\s+(?:instructions?|prompts?|rules?|messages?|guidelines?|restrictions?|filters?)"),
    _r(Category.PROMPT_INJECTION, "reveal", r"\b(?:reveal|show|print|tell|repeat|leak|display|bata\w*|dikha\w*)\s+(?:me\s+|mujhe\s+)?(?:your\s+|apna\s+|apni\s+|tumhara\s+|aapka\s+|tumhari\s+)?(?:system\s+prompt|hidden\s+prompt|initial\s+prompt|secret\s+(?:instructions|prompt)|hidden\s+(?:instructions?|rules)|instructions|configuration|api\s*key|settings)\b"),
    _r(Category.PROMPT_INJECTION, "persona", r"\b(?:you\s+are\s+now\s+(?:dan|in\s+developer|an?\s+(?:unrestricted|unfiltered|different|evil))|developer\s+mode|jailbreak|do\s+anything\s+now|dan\s+mode|sudo\s+mode|admin\s+override|act\s+as\s+(?:an?\s+)?(?:unrestricted|unfiltered|evil|uncensored)|pretend\s+(?:that\s+)?(?:you\s+)?(?:have|has|are\s+with)?\s*(?:no|without)\s+(?:rules|restrictions|limits|filters))"),
    _r(Category.PROMPT_INJECTION, "hinglish", r"\b(?:pichle|pehle\s+ke|purane|saare|sabhi|apne)\s+(?:[\w']+\s+){0,2}(?:instructions?|nirdesh|niyam|rules)\s+(?:ko\s+)?(?:ignore|bhool|bhul|mat\s+maan)\w*|\b(?:instructions?|niyam|rules)\s+(?:ko\s+)?(?:ignore|bhool\s+ja|bhul\s+ja|mat\s+maan)\w*|\bsystem\s+prompt\s+(?:bata|dikha)\w*"),
    _r(Category.PROMPT_INJECTION, "hindi", r"(?:पिछले\s+(?:सभी\s+)?(?:निर्देश|इंस्ट्रक्शन)\s*(?:को\s+)?(?:भूल|इग्नोर)|सिस्टम\s+प्रॉम्प्ट|सारे\s+नियम\s+भूल)"),
    _r(Category.PROMPT_INJECTION, "markup", r"(?:<\s*/?\s*system\s*>|\[\s*/?inst\s*\]|^\s*system\s*:|###\s*(?:new\s+)?instruction|<\|im_start\|>)"),
    _r(Category.PROMPT_INJECTION, "forwarded_command", r"\b(?:dear\s+)?(?:ai\s+)?(?:assistant|friday|chatbot|bot)\s*[,:]\s*(?:please\s+)?(?:send|transfer|call|forward|delete|share|reveal|pay|email)\b|\bwhen\s+you\s+(?:read|see)\s+this[, ]+\s*(?:send|call|transfer|forward|delete|reveal)\b"),
]

FAKE_DOCUMENTS = [
    _r(Category.FAKE_DOCUMENTS, "document", r"\b(?:fake|nakli|naqli|naklee|jaali|jali|forged?|forging|bogus|fabricated?)\s+(?:[\w']+\s+){0,2}(?:aadhaar|aadhar|pan|passport|licen[cs]e|degree|marksheet|mark\s*sheet|certificate|salary\s+slip|payslip|pay\s+slip|bank\s+statement|rent\s+agreement|id\s+card|signature|stamp|visa|report|prescription|experience\s+letter|gst\s+invoice|invoice)\b|(?:नकली|जाली)\s+(?:बिल|सर्टिफिकेट|प्रमाण|आधार|मार्कशीट|दस्तावेज|रसीद|पैन)"),
    _r(Category.FAKE_DOCUMENTS, "edit", r"\b(?:edit|change|badal\w*|photoshop|tamper|alter)\s+(?:[\w']+\s+){0,3}(?:bank\s+statement|salary\s+slip|marksheet|certificate|receipt|invoice|medical\s+report|report)\s+(?:[\w']+\s+){0,5}(?:so\s+that|taaki|to\s+show|dikha\w*|amount|total|date|number)"),
    _r(Category.FAKE_DOCUMENTS, "fraud", r"\b(?:phishing|scam\s+(?:call|message|sms|link)|fraud\s+(?:call|sms|message|link)|chargeback\s+fraud|refund\s+scam|insurance\s+fraud|fake\s+(?:review|reviews|offer|lottery)|(?:thagi|dhokha|fraud)\s+(?:karna|karne|kaise|ka\s+tarika)|loot\w*\s+logon|logon\s+ko\s+thag\w*|thag\w*\s+(?:ka|ke)\s+tarike)\b|make\s+(?:a\s+)?(?:phishing|scam)\w*"),
]

ILLEGAL = [
    _r(Category.ILLEGAL, "drugs", r"\b(?:buy|kharid\w*|lena|lao|dilwa\w*|supply|arrange|order|mangwa\w*|sell|bech\w*)\s+(?:[\w']+\s+){0,3}(?:weed|ganja|charas|cocaine|mdma|lsd|heroin|afeem|opium|brown\s+sugar|smack|drugs?|hashish|meth|cannabis|marijuana|nasha)\b|\b(?:weed|ganja|charas|cocaine|mdma|heroin|drugs?|brown\s+sugar)\s+(?:[\w']+\s+){0,3}(?:chahiye|kharid\w*|dilwa\w*|lao|mangwa\w*|supplier|dealer|buy|order|kahan\s+milega|kahan\s+mil\w*)|(?:ड्रग्स|गांजा|चरस|अफीम)\s+(?:[\w']+\s+){0,2}(?:खरीद|चाहिए|कहाँ|कहां)"),
    _r(Category.ILLEGAL, "weapons", r"\b(?:make|build|bana\w*|banane|banao)\s+(?:[\w']+\s+){0,3}(?:bomb|explosive|grenade|detonator|poison|zeher|silencer|ied)\b|\bbomb\s+kaise\s+ban\w*|\b(?:buy|kharid\w*|dilwa\w*|arrange|chahiye)\s+(?:[\w']+\s+){0,3}(?:gun|pistol|revolver|katta|rifle|ammo|bullets?|ak\s*47)\b|\b(?:gun|pistol|katta)\s+(?:[\w']+\s+){0,3}(?:kharid\w*|dilwa\w*|chahiye)|बम\s+(?:कैसे|बनाना|बनाने)|हथियार\s+(?:खरीद|चाहिए)"),
    _r(Category.ILLEGAL, "hacking", r"\bhack\w*\s+(?:[\w']+\s+){0,3}(?:whatsapp|instagram|facebook|account|phone|wifi|email|gmail|bank|atm|server|id|snapchat)|\b(?:bypass|crack|break)\s+(?:[\w']+\s+){0,2}(?:otp|password|passcode|lock|2fa|captcha)|\bsim\s*swap|\bddos|\bspy\s*app|\bkeylogger|\bspyware|\bstalkerware|(?:हैक|हैकिंग)\s*(?:कर|करना|कैसे)"),
    _r(Category.ILLEGAL, "evade", r"\b(?:evade|avoid|escape|dodge)\s+(?:[\w']+\s+){0,3}(?:police|cops|arrest|tax\s+raid|income\s+tax|challan)|\bpolice\s+se\s+(?:bach\w*|chhup\w*|bhag\w*)|\b(?:black\s+money|kala\s+dhan|kaala\s+paisa)\s+(?:[\w']+\s+){0,3}(?:white|safed|convert|launder)|\bhawala\b|\bmoney\s+launder\w*|\bfake\s+(?:note|notes|currency)|\brishwat\b|\bbribe\s+(?:dena|do|kaise|the)|रिश्वत|\bkidnap\w*|\bapaharan|\bchori\s+kaise|\bhow\s+to\s+(?:steal|shoplift|rob)\b|\bspike\s+(?:[\w']+\s+){0,2}(?:drink|glass)"),
]

HARASSMENT = [
    _r(Category.HARASSMENT_ABUSE, "target", r"\b(?:isko|usko|use|unko|inko|him|her|them|my\s+(?:brother|sister|ex|boss|neighbou?r|wife|husband|friend|teacher)|mere\s+(?:bhai|bhaiya|ex|boss|padosi|dost)|apne\s+(?:ex|boss|padosi))\s+(?:[\w']+\s+){0,4}(?:dara\w*|darao|dhamk\w+|threat\w*|scare|harass\w*|pareshan\w*|tang\s+kar\w*|gaali\w*|abuse|insult|bezzati|blackmail|hoax)|(?:ko|pe|par)\s+(?:phone|call)\s+(?:karke|kar\s+ke)\s+(?:dara\w*|dhamk\w+|gaali\w*|pareshan\w*)"),
    _r(Category.HARASSMENT_ABUSE, "verb_first", r"\b(?:scare|threaten|harass|intimidate|blackmail|dara\w*|darao|dhamka\w*|pareshan\s+kar\w*)\s+(?:[\w']+\s+){0,3}(?:my\s+|mere\s+|apne\s+)?(?:brother|sister|ex|boss|neighbou?r|wife|husband|friend|teacher|him|her|them|bhai|padosi|dost|usko|isko)\b|\bthreatening\s+(?:messages?|calls?|texts?|sms)\b"),
    _r(Category.HARASSMENT_ABUSE, "action", r"\b(?:prank\s+call|spam\s+call|bomb\s+call|call\s+bombing|dhamki\s+(?:do|dena|de\s+do)|dara\s+do|darao|pareshan\s+karo|tang\s+karo|threaten|blackmail|stalk\w*)\b|\b(?:bar\s*bar|baar\s*baar|repeatedly|non\s*stop|roz|daily)\s+(?:[\w']+\s+){0,3}(?:call|phone)\s+(?:karke|kar\s+ke|karo)?\s*(?:[\w']+\s+){0,2}(?:tang|pareshan|harass|dara)\w*|धमकी\s+(?:दो|देना)|डरा\s+दो|परेशान\s+करो"),
    _r(Category.HARASSMENT_ABUSE, "slur", r"\b(?:madarchod|madarchod|m[a@]d[a@]rch[o0]d|maderchod|bhenchod|behenchod|bhosdi\w*|bhosdk|chutiy\w*|chutya|gandu|randi|harami|haramzad\w*|kutti|kamin[ae]|fuck\w*|f\*+k\w*|bitch\w*|asshole|motherfucker|bastard|slut|whore|dick\s*head|piece\s+of\s+shit|teri\s+maa\s+ki|maa\s+ki)\b|(?:मादरचोद|मादर\s*चोद|भेनचोद|बहनचोद|चूतिया|हरामी|गांडू|रंडी|कमीना|कुत्ती|भोसड़ी)"),
]

ADULT = [
    _r(Category.ADULT, "explicit", r"\b(?:porn\w*|nude\w*|nudes|naked|xxx|erotic\w*|horny|boobs?|blowjob|onlyfans|sexting|call\s*girl|escort\s+service|nangi|nanga|chudai|lund|chut|sex(?:y|ting)?\s+(?:chat|video|videos|pics?|photos?|baat|story|stories|kar\w*)|sex\s+(?:karna|karo|chahiye)|dirty\s+talk|hookup|gande\s+(?:videos?|photos?|jokes?)|gandi\s+baat\w*|sexy\s+baat\w*|sexy\s+(?:pics?|photos?|video)|send\s+(?:me\s+)?nudes)\b|(?:सेक्स|पोर्न|नंगी|नंगा|चुदाई|गंदी\s+बात)"),
]

PRIVACY = [
    _r(Category.PRIVACY_OTHERS, "their_data", r"\b(?:uski|uska|unka|unki|iski|iska|uske|uski|his|her|their|someone'?s|kisi\s+ka|kisi\s+ki|kisi\s+aur\s+ka|dusre\s+(?:user|log|bande|insaan)\s+(?:ka|ki|ke)|other\s+users?'?s?|girlfriend\s+(?:ki|ka)|wife\s+(?:ki|ka)|husband\s+(?:ki|ka)|ex\s+(?:ki|ka)|bf\s+ka|gf\s+(?:ki|ka)|padosi\s+(?:ka|ki)|boss\s+(?:ka|ki)|neighbou?r'?s?)\s+(?:[\w']+\s+){0,2}(?:live\s+location|location|whatsapp\s+chats?|chats?|messages?|call\s+(?:history|records?|log|details)|cdr|address|ghar\s+ka\s+pata|photos?|password|phone\s+numbers?|mobile\s+numbers?|numbers?|aadhaar|accounts?|balance|gps|salary|bank\s+details)\b",
       exempt=r"\b(?:save|add|store|jodo|jod\s+do|nickname|contact\s+card|mera|meri|apna|apni|my\s+own)\b"),
    _r(Category.PRIVACY_OTHERS, "track", r"\b(?:track|trace|locate|dhoond\w*|pata\s+(?:karo|lagao|laga)|find\s+out\s+where)\s+(?:[\w']+\s+){0,3}(?:someone|kisi|uski|uska|uske|her|him|his|girlfriend|wife|husband|ex\b|boyfriend|a\s+person|kisiki|kisi\s+ladki|kisi\s+ladke)|\b(?:spy\s+on|jasoosi|monitor)\s+(?:[\w']+\s+){0,3}(?:wife|husband|girlfriend|boyfriend|his|her|uski|uska|ex)|\b(?:read|padh\w*|dekh\w*)\s+(?:[\w']+\s+){0,3}(?:wife|husband|girlfriend|boyfriend|his|her|uske|uski)(?:'s)?\s+(?:[\w']+\s+){0,2}(?:messages?|chats?|whatsapp|phone|calls?)"),
    _r(Category.PRIVACY_OTHERS, "hindi", r"(?:उसकी|उसका|उनकी|उनका|किसी\s+की|किसी\s+का|दूसरे\s+यूज़र\s+का)\s+(?:\S+\s+)?(?:लोकेशन|नंबर|नम्बर|पता|चैट|मैसेज|कॉल\s+हिस्ट्री)", exempt=r"सेव|जोड़"),
    _r(Category.PRIVACY_OTHERS, "owner", r"\b(?:who\s+owns\s+(?:this\s+)?(?:phone\s+)?number|number\s+kiska\s+hai|is\s+number\s+ka\s+(?:malik|owner)|iss?\s+number\s+(?:ka|ki)\s+(?:details|owner|malik|address)|dusre\s+user\s+ka\s+number|other\s+user'?s?\s+number|kisi\s+ka\s+bhi\s+(?:number|address|location))\b"),
]

LEGAL = [
    _r(Category.LEGAL_ADVICE, "sue", r"\b(?:should\s+i|can\s+i|do\s+i\s+need\s+to|kya\s+(?:main|mujhe)|main)\s+(?:[\w']+\s+){0,3}(?:sue|file\s+(?:a\s+)?(?:case|fir|lawsuit|complaint\s+in\s+court)|take\s+(?:him|her|them)\s+to\s+court|take\s+legal\s+action|legal\s+action\s+(?:lun|lu|loon)|go\s+to\s+court|case\s+(?:karu|karun|karoon|kar\s+sakta|kar\s+sakti|karna\s+chahiye|file\s+karu))|\b(?:case|fir|muqadma|mukadma|legal\s+notice|court\s+case|consumer\s+case)\s+(?:karu|karun|karoon|kar\s+sakta|kar\s+sakti|karna\s+chahiye|file\s+karu|file\s+kar)\b|क्या\s+मैं\s+केस|केस\s+कर", exempt=_ACT),
    _r(Category.LEGAL_ADVICE, "advice", r"\b(?:legal|kanooni|kanuni|kanoon)\s+(?:advice|salah|rai|madad)|\blawyer\s+(?:advice|salah)|\bwhat\s+are\s+my\s+(?:legal\s+)?rights\b|\blegal\s+action\s+(?:lun|lu|loon|le\s+sakta|lena)\b|\bmere\s+(?:kya\s+)?(?:legal\s+)?(?:rights|adhikar)\s+(?:hain|hai)\b|\bis\s+(?:it|this)\s+(?:legal|illegal)\b|\bkya\s+(?:yeh|ye|ye\s+sab)\s+(?:legal|illegal|kanooni|gair\s*kanooni)\s+hai\b|\b(?:divorce|talaq|custody|vasiyat|will\s+deed|tenancy\s+law|property\s+dispute|bail|anticipatory\s+bail)\s+(?:[\w']+\s+){0,3}(?:kaise|how|kya|batao|help|process|procedure)|कानूनी\s+सलाह|क्या\s+यह\s+(?:कानूनी|गैरकानूनी)", exempt=_ACT),
    _r(Category.LEGAL_ADVICE, "dispute", r"\b(?:landlord|makan\s*malik|employer|boss|company|bank|builder|neighbou?r)\s+(?:[\w']+\s+){0,6}(?:legal\s+action|court|sue|kanooni|vakil\s+se|lawyer\s+se)|\b(?:deposit|security\s+deposit)\s+(?:wapas\s+)?(?:[\w']+\s+){0,5}(?:nahi\s+(?:de|return|mil)|not\s+return\w*)\s*(?:[\w']+\s+){0,5}(?:legal|case|court|kya\s+karu|what\s+should)", exempt=_ACT),
]

FINANCIAL = [
    _r(Category.FINANCIAL_ADVICE, "invest", r"\b(?:kahan|kaha|kidhar|where)\s+(?:[\w']+\s+){0,3}invest\w*|\binvest\w*\s+(?:kahan|kaha|karun|karu|karoon|kaise|where|in\s+what|karna\s+chahiye)|\b(?:should\s+i|kya\s+(?:main|mujhe))\s+(?:[\w']+\s+){0,3}(?:buy|sell|invest|kharid\w*|bech\w*|lena)\s+(?:[\w']+\s+){0,3}(?:stock|share|shares|crypto|bitcoin|gold|property|nifty|sensex|fd|sip|mutual|etf|ipo)|\bkya\s+(?:main|mujhe|hum)\s+(?:[\w']+\s+){0,3}(?:bitcoin|crypto|shares?|stocks?|gold|nifty|sensex|etf|sip|mutual\s+funds?)\s*(?:[\w']+\s+){0,2}(?:kharid\w*|bech\w*|le\w*|lun|loon|lu)\b|निवेश\s+(?:कहाँ|कहां|कैसे)|कहाँ\s+निवेश|कहां\s+निवेश"),
    _r(Category.FINANCIAL_ADVICE, "pick", r"\b(?:which|kaun\s*si|kaun\s+sa|konsi|kon\s*si|kaunsa|best|top)\s+(?:[\w']+\s+){0,2}(?:stocks?|shares?|mutual\s+funds?|sip|crypto|bitcoin|etf|ipo|insurance\s+policy|fd\s+scheme|ulip|nps)\b\s*(?:[\w']+\s+){0,3}(?:buy|lu|loon|lun|kharid\w*|invest|chahiye|sahi|rahega|hai|lena|karun)|(?:कौन\s+सा|कौनसा)\s+(?:शेयर|म्यूचुअल|म्यूच्यूअल|स्टॉक)"),
    _r(Category.FINANCIAL_ADVICE, "loan_tax", r"\b(?:personal\s+loan|gold\s+loan|home\s+loan|car\s+loan|loan)\s+(?:lena|le\s+lun|le\s+loon|lu|lun|loon)\s*(?:chahiye|sahi|theek|kya)?\b|\btax\s+(?:bachane|save|saving|bachao|kaise\s+bach\w*)|\bhow\s+to\s+(?:save|avoid|evade)\s+(?:paying\s+)?(?:income\s+)?tax|\bavoid\s+paying\s+tax|\bitr\s+(?:kaise|how)\s+(?:bharu|file)|\bwhich\s+(?:loan|credit\s+card|insurance)\s+(?:is\s+)?best", exempt=r"\bemi\b.{0,30}\b(?:kab|due|reminder|date|kitna)\b"),
    _r(Category.FINANCIAL_ADVICE, "returns", r"\b(?:double|2x|5x|10x)\s+(?:my\s+|mera\s+)?(?:money|paisa|paise)|\bpaisa\s+(?:double|dugna|dugan)\w*|\bguaranteed\s+returns?|\bget\s+rich\s+quick|\bjaldi\s+ameer\b|\btrading\s+tips?\b|\bintraday\s+tips?\b|\boption\s+trading\s+(?:tips|strategy)"),
]

PROHIBITED = [
    _r(Category.PROHIBITED_ACTION, "pay", r"\b(?:payment|pay|transfer)\s+(?:kar\s*do|kardo|karo|kar\s+de|krdo|now|this|it|abhi)\b|\b(?:ye|yeh|ise|isko|is)\s+(?:[\w']+\s+){0,2}(?:payment|pay)\s+(?:kar|karo)|\b(?:send|transfer|bhej\w*|de\s+do|dedo)\s+(?:rs\.?|₹|inr)?\s*\d[\d,]*\s*(?:rs\.?|rupees?|₹|rupaye)?\s+(?:to|ko)\b|\b(?:pay|bhej|transfer)\s+(?:the\s+|my\s+)?(?:[\w']+\s+){0,2}(?:bill|amount|fees?|rent|emi)\s+(?:for\s+me|mere\s+liye|abhi|now|kar\s*do)|\b(?:paisa|paise|rupaye|rupees|money|amount)\s+(?:[\w']+\s+){0,2}(?:bhej\s*do|bhejo|bhej\s+de|transfer\s+kar\w*)|पेमेंट\s+कर\s+दो|भुगतान\s+कर\s+दो", exempt=r"\b(?:remind\w*|yaad|reminder|kab|due|status|receipt|link|qr|reminder)\b"),
    _r(Category.PROHIBITED_ACTION, "secret_send", r"\b(?:send|bhej\w*|share|forward|de\s+do|dedo|bata\s+do)\s+(?:[\w']+\s+){0,2}(?:mera\s+|my\s+)?(?:otp|pin|cvv|password|passcode)\b|\b(?:mera|my)\s+(?:otp|pin|cvv|password)\s+(?:bhej|send|share|bata|de)\w*|ओटीपी\s+भेज"),
    _r(Category.PROHIBITED_ACTION, "save_secret", r"\b(?:save|store|yaad\s+rakh\w*|note|remember)\s+(?:[\w']+\s+){0,3}(?:card\s+number|cvv|otp|upi\s+pin|atm\s+pin|password|pin\s+number)\b"),
    _r(Category.PROHIBITED_ACTION, "save_secret_rev", r"\b(?:card\s+number|cvv|upi\s+pin|atm\s+pin|otp|password)\s+(?:[\w']+\s+){0,2}(?:save|store|yaad\s+rakh|note)\w*"),
    _r(Category.PROHIBITED_ACTION, "use_card", r"\b(?:use|laga\w*|daal\w*|enter)\s+(?:[\w']+\s+){0,3}(?:my\s+|mera\s+|meri\s+)?(?:card|upi\s+pin|cvv)\s+(?:[\w']+\s+){0,3}(?:pay|payment|buy|purchase|kharid\w*|order)\b"),
]

POLITICS = [
    _r(Category.OUT_OF_SCOPE, "politics", r"\b(?:kaun\s+si|konsi|which|kis)\s+(?:[\w']+\s+){0,2}(?:party|neta|leader|sarkar|government)\s+(?:[\w']+\s+){0,3}(?:sahi|better|best|achhi|acchi|achha|vote|jeetegi|jeetega|win)|\b(?:modi|rahul\s+gandhi|kejriwal|bjp|congress|aap)\s+(?:vs|versus|ya|or)\s+(?:modi|rahul|kejriwal|bjp|congress|aap)\b|\b(?:vote)\s+(?:kisko|kis\s+ko|whom|for\s+whom)|\bwhich\s+religion\s+is\s+(?:the\s+)?(?:best|better|true)|\bhindu\s+(?:vs|ya)\s+muslim|\bkaun\s+sa\s+dharm\s+(?:sahi|best|achha|accha)|\bbeef\s+ban\b|\bmandir\s+masjid\b|किसे\s+वोट|कौन\s+सी\s+पार्टी|कौन\s+सा\s+धर्म"),
]

IDENTITY = [
    _r(Category.OUT_OF_SCOPE, "identity", r"\b(?:are\s+you\s+(?:a\s+)?(?:real\s+)?(?:human|person|bot|robot|ai|real|insaan)|kya\s+tum\s+(?:insaan|insan|human|bot|robot|asli)\s+ho|tum\s+(?:insaan|insan|human|bot|robot)\s+ho\s*(?:ya|\?)?|aap\s+(?:insaan|human|bot|robot)\s+(?:ho|hain)|is\s+this\s+a\s+(?:bot|human|real\s+person)|real\s+person\s+(?:ho|hai|hain|ya)|kya\s+aap\s+(?:insaan|human|bot|asli)\s+(?:hain|ho)|are\s+u\s+(?:a\s+)?(?:bot|human|real))\b|क्या\s+(?:तुम|आप)\s+(?:इंसान|इंसान|बॉट|रोबोट)"),
]

SMALL_TALK = re.compile(
    r"^\W*(?:hi+|hello+|hey+|heya|hii+|namaste|namaskar|pranam|thanks?(?:\s+a\s+lot)?|thank\s+you(?:\s+so\s+much)?|shukriya|dhanyavaad|dhanyawad|ok(?:ay)?|okk+|good\s+(?:morning|night|evening|afternoon)|gm|gn|kaise\s+ho|kaisi\s+ho|how\s+are\s+you|kya\s+haal(?:\s+hai)?|kya\s+chal\s+raha|what'?s\s+up|sup|bye|alvida|hmm+|acha|achha|accha|theek\s+hai|thik\s+hai|cool|nice|great|wah|shabash|good\s+job|नमस्ते|धन्यवाद|शुक्रिया|कैसे\s+हो|ठीक\s+है|हेलो|हाय)(?:\s+(?:friday|ji|ji\s+shukriya|dost))?\W*$",
    _I,
)

# Order matters: the first matching group wins. (engine.py walks PRIORITY in this order.)
RULES: dict[str, list[Rule]] = {
    "self_harm": SELF_HARM,
    "emergency_extra": EMERGENCY_EXTRA,
    "minors": MINORS,
    "medical": MEDICAL,
    "prompt_injection": PROMPT_INJECTION,
    "fake_documents": FAKE_DOCUMENTS,
    "illegal": ILLEGAL,
    "harassment": HARASSMENT,
    "adult": ADULT,
    "privacy": PRIVACY,
    "legal": LEGAL,
    "financial": FINANCIAL,
    "prohibited": PROHIBITED,
    "politics": POLITICS,
    "identity": IDENTITY,
}

# a sensitive skill a declared minor may not use (calls, payments, bookings, orders, logins)
MINOR_SENSITIVE_SKILL = re.compile(
    r"\b(?:call|calls|phone|pay|payment|book|booking|order|login|log\s*in|bill|card|taxi|cab|ride|hotel|recharge|"
    r"ticket|flight|train|upi|bank|loan)\b|कॉल|पेमेंट|बुक",
    _I,
)
