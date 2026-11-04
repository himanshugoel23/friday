# ruff: noqa: E501, SIM905
"""Care detection: rules only, no language model, no network. NOT a clinical tool.

``assess(text)`` returns a tier:

* ``HIGH``      thoughts of suicide or self-harm (explicit or indirect).
* ``ELEVATED``  serious distress without ideation (hopelessness, or a cluster such as job loss +
                "failure" + sleeplessness).
* ``NONE``      anything else.

Handled: Roman Hinglish, Devanagari Hindi and English; negation ("I don't want to die"), plain
information or product talk ("suicide prevention app idea"), jokes and hyperbole ("I will die
laughing"), a third person ("my friend says he wants to die"), and the evasions the guardrails
normaliser folds (case, look-alikes, spaced letters, repeats, light leet-speak).

The rules are a first draft written by engineers. They WILL miss real messages and WILL fire on some
harmless ones. Review by a mental-health professional is recommended before a wide launch
(docs/CARE_PROTOCOL.md). When unsure the rules lean towards caring (a false alarm costs one gentle
message; a miss can cost much more).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from friday.guardrails.normalize import squash, variants

_I = re.IGNORECASE


class Tier(StrEnum):
    NONE = "none"
    ELEVATED = "elevated"
    HIGH = "high"


@dataclass(frozen=True)
class Assessment:
    tier: Tier
    reasons: tuple[str, ...] = ()
    lang: str = "hinglish"  # en | hinglish | hi  (the language to answer in)
    third_party: bool = False  # the distress is about someone else


NONE = Assessment(Tier.NONE)


def _c(pattern: str) -> re.Pattern[str]:
    # NFKC the pattern too: the folded text has nukta letters decomposed (ज़ -> ज + ़)
    return re.compile(unicodedata.normalize("NFKC", pattern), _I)


@dataclass(frozen=True)
class _Rule:
    id: str
    pat: re.Pattern[str]
    negatable: bool = False  # a negator next to the phrase cancels it ("I don't want to die")
    topic: bool = False  # bare topic word: information talk ("prevention app") cancels it
    hyperbole: bool = False  # "die laughing" style talk cancels it
    exempt: re.Pattern[str] | None = None


def _r(id_: str, pattern: str, *, neg: bool = False, topic: bool = False, hyp: bool = False, exempt: str | None = None) -> _Rule:
    return _Rule(id_, _c(pattern), neg, topic, hyp, _c(exempt) if exempt else None)


# ----------------------------------------------------------------------------- HIGH (ideation)
_NOT_ORDINARY_END = r"(?:meeting|call|session|chat|conversation|discussion|contract|subscription|lease|relationship|exam|test|video|class|lecture|shift|order)"

HIGH: list[_Rule] = [
    # English
    _r("en.kill_self", r"\b(?:kill(?:ing)?|killed)\s+my\s*self\b", neg=True, hyp=True),
    _r("en.want_die", r"\b(?:want(?:ed|s)?|wanna|wan+t+|wish(?:ing)?|need|ready|feel\s+like|feeling\s+like)\s+(?:to\s+)?(?:just\s+)?(?:di+e+|be\s+dead|dying|not\s+exist|not\s+be\s+(?:here|alive)|not\s+wake\s+up|disappear\s+forever|sleep\s+forever)\b", neg=True, hyp=True),
    _r("en.wish_dead", r"\bwish\s+(?:i|that\s+i)\s+(?:was|were|am|could\s+be|had\s+been)\s+(?:dead|gone|not\s+alive|never\s+born)\b|\bwish\s+i\s+(?:would|could|will)\s+(?:just\s+)?(?:die|not\s+wake\s+up|disappear)\b|\bwish\s+i\s+(?:had\s+)?never\s+been\s+born\b|\bwish\s+i\s+(?:was|were|had)\s*(?:n'?t|not|never)\s+(?:born|alive)\b", neg=True),
    _r("en.going_to_end", r"\b(?:going|gonna|about)\s+to\s+(?:kill|end|hurt|harm)\s+my\s*self\b|\b(?:i(?:'ll|\s+will)|i\s*am\s+going\s+to)\s+(?:just\s+)?(?:die|end\s+(?:my\s+life|it\s+all))\b(?!\s+(?:laugh|of|from|for|if|when|without|waiting|here|hungry|cold|hot|bored|embarrass))", neg=True, hyp=True),
    _r("en.end_life", r"\bend(?:ing)?\s+my\s+(?:own\s+)?life\b|\btake\s+my\s+(?:own\s+)?life\b|\btaking\s+my\s+(?:own\s+)?life\b|\bend\s+it\s+all\b|\bend\s+everything\b", neg=True),
    _r("en.end_it", r"\b(?:want|wanna|going|gonna|plan\w*|thinking\s+(?:of|about)|ready|time|decid\w*|have|need|should|let'?s|just|will|i'?ll)\s+(?:to\s+)?end\s+it\b(?!\s+(?:with|between|here|there|for\s+today|now\s+with))|^\W*(?:just\s+|i\s+)?(?:want\s+to\s+)?end\s+it\W*$", neg=True, exempt=rf"\b{_NOT_ORDINARY_END}\b"),
    _r("en.dont_want_live", r"\b(?:do\s*n'?t|dont|do\s+not|no\s+longer|never)\s+want\s+to\s+(?:live|be\s+alive|be\s+here|exist|go\s+on|wake\s+up)\b|\bnot\s+want\s+to\s+(?:live|be\s+alive)\b"),
    _r("en.no_point_living", r"\bno\s+(?:point|reason|use|purpose)\s+(?:in\s+|of\s+|to\s+)?(?:living|live|life|going\s+on|being\s+alive|continuing)\b|\b(?:life|living)\s+(?:is\s+)?(?:not|no\s+longer)\s+worth\s+(?:living|it)\b|\bnot\s+worth\s+living\b|\bwhy\s+(?:am\s+i|should\s+i\s+keep)\s+(?:still\s+)?(?:alive|living)\b|\bwhat'?s\s+the\s+point\s+of\s+living\b"),
    _r("en.better_not_born", r"\bbetter\s+(?:off\s+)?(?:if|when|without)\s+(?:i\s+(?:was|were|had)\s*(?:n'?t|not|never)\s+(?:born|here|alive|around|exist\w*)|i\s+(?:didn'?t|did\s+not)\s+exist|i\s+was\s+gone|i\s+died|i\s+(?:was|were)\s+dead|me\b)|\beveryone\s+(?:would\s+be|is|will\s+be)\s+better\s+(?:off\s+)?without\s+me\b|\bbetter\s+off\s+dead\b|\bworld\s+(?:would\s+be|is)\s+better\s+without\s+me\b|\bshould(?:n'?t|\s+not)\s+have\s+been\s+born\b"),
    _r("en.self_injury", r"\b(?:hurt|harm|cut|cutting|hurting|harming)\s+my\s*self\b|\b(?:slit|slash|cut)\w*\s+my\s+wrists?\b|\bhang\s+my\s*self\b|\bhanging\s+my\s*self\b", neg=True, exempt=r"\b(?:shav\w*|cooking|kitchen|accident\w*|paper|chopp\w*|knife\s+slipped|by\s+mistake|nail|hair\s?cut|haircut)\b"),
    _r("en.method", r"\b(?:i(?:\s*am|'m|'ll|\s+will|\s+might|\s+may)|going\s+to|gonna|want\s+to|wanna|thinking\s+(?:of|about)|should)\s+(?:just\s+)?(?:jump(?:ing)?\s+(?:off|from)|take\s+an?\s+overdose|overdose|swallow\w*\s+(?:all\s+)?(?:my\s+|the\s+)?(?:pills|tablets|sleeping\s+pills))\b|\b(?:wrote|writing|leaving|left)\s+(?:a\s+)?(?:suicide|goodbye|final)\s+(?:note|letter)\b|\btake\s+all\s+(?:my|the)\s+(?:pills|sleeping\s+pills)\b|\b(?:took|swallowed|ate)\s+(?:all\s+(?:of\s+)?(?:my|the)|too\s+many|a\s+lot\s+of)\s+(?:pills|tablets|sleeping\s+pills|medicines?)\b"),
    _r("en.tired_of_life", r"\b(?:tired|sick|done|exhausted)\s+(?:of|with)\s+(?:living|life|being\s+alive)\b(?!\s+(?:with|in|here|at|on|alone|under|away|far))"),
    _r("en.suicidal_self", r"\b(?:i\s*(?:am|'m|feel|felt|was|have\s+been|been)\s+(?:so\s+|really\s+|feeling\s+|actually\s+)?suicidal|(?:feeling|feel)\s+suicidal|suicidal\s+(?:thoughts?|ideation|feelings?)\s+(?:again|tonight|today|now|are|have)|(?:have|having|got)\s+suicidal\s+(?:thoughts?|ideation|feelings?)|my\s+suicidal)\b", neg=True),
    _r("en.suicide_topic", r"\b(?:thinking|thoughts?|think|considering|contemplating|planning|plan|attempt(?:ed|ing)?|try(?:ing)?|tried|commit(?:ting|ted)?|about)\s+(?:of\s+|about\s+|to\s+)?(?:\w+\s+){0,2}(?:suicide)\b|\bsuicid\w*\b", topic=True, neg=True),
    _r("en.self_harm_word", r"\bself[\s\-]?harm\w*\b", topic=True, neg=True),
    # Hinglish (Roman)
    _r("hg.mar_jana", r"\bmar\s*ja(?:na|ana|ane)\s+(?:chah|hi\s+(?:behtar|achha|accha)|behtar|achha|accha)\w*|\bmar\s*ja(?:un|aun|oon)(?:ga|gi)?\b|\bmarna\s+chah\w*|\bmar\s*jaana\b", neg=True, hyp=True, exempt=r"\b(?:bhookh|bhook|hasi|hans\w*|sharm\w*|garmi|thand|pyaas|boredom|bore|laugh\w*|hungry)\b"),
    _r("hg.jeene_ka_mann", r"\bjee?(?:ne|na)\s+(?:ka|ki)\s+(?:mann?|mood|dil|iccha|ichha|icha|himmat|wajah|vajah|maksad)\s+(?:hi\s+)?(?:nahi|nhi|nai|nahin|na)\b|\bjee?na\s+(?:hi\s+)?(?:nahi|nhi|nahin)\s+chah\w*|\bjee?ne\s+ki\s+(?:koi\s+)?(?:wajah|vajah|umeed|ummeed|ichha|iccha)\s+(?:hi\s+)?(?:nahi|nhi|nahin)\b|\bab\s+(?:aur\s+)?(?:nahi|nhi)\s+jee?\s*(?:sakta|sakti|paunga|paungi|paaunga)\b|\bjee?ne\s+se\s+(?:thak|tang|dar)\w*|\bzindagi\s+se\s+(?:thak|tang)\w*|\bzindagi\s+(?:khatam|khtm)\b|\bjeevan\s+(?:khatam|samapt)\b"),
    _r("hg.khud_ko", r"\bkhud\s*ko\s+(?:khatam|maar|nuksan|chot|hurt|jala|kaat)\w*|\bkhud\s*kushi\b|\bkhudkushi\b|\baatmahatya\b|\batmahatya\b|\bapni\s+jaan\s+(?:de|le|lun|du)\w*|\bjaan\s+(?:de\s+du|de\s+dun|dedunga|de\s+dunga|de\s+dungi|dene)\w*|\bsuicide\s+(?:kar|karna|karunga|karungi|karne|ka\s+(?:khayal|vichar|mann|man))\w*", neg=True),
    _r("hg.suicide_word", r"\bsuicid\w*\b", topic=True, neg=True),
    _r("hg.na_hota", r"\b(?:main|mai|mein)\s+na\s+hota\s+(?:to|toh)\s+(?:behtar|achha|accha|sab)|\bmera\s+na\s+hona\s+(?:hi\s+)?(?:behtar|achha|accha)|\bpaida\s+(?:hi\s+)?(?:nahi|nhi)\s+(?:hona|hota|hua|hota)\b|\bmere\s+bina\s+(?:sab|sabki?|sabka|sab\s+log)\s+(?:behtar|achha|accha|khush)|\bmere\s+(?:jaane|marne)\s+se\s+(?:kisi\s+ko\s+)?(?:fark|farq)\s+(?:nahi|nhi)|\bkisi\s+ko\s+(?:fark|farq)\s+(?:nahi|nhi)\s+(?:padega|padta)\s+(?:agar|jo|ki)\s*(?:main|mai|mein)"),
    _r("hg.sab_khatam_kar", r"\bsab\s+(?:kuch\s+)?khatam\s+(?:kar|krna|krdu|kardu)\w*|\b(?:ye|yeh)\s+sab\s+(?:khatam|end)\s+kar\w*|\bend\s+kar\s+(?:du|dun|dunga|dungi)\s+(?:sab|zindagi|life|ye\s+sab|yeh\s+sab)|\bsab\s+(?:kuch\s+)?end\s+kar\w*", neg=True),
    _r("hg.sab_khatam_bare", r"^\W*(?:ab\s+|bas\s+|mera\s+|ye\s+|yeh\s+|ho\s+gaya\s+)*(?:sab|sabkuch|sab\s+kuch)\s+khatam(?:\s+(?:ho\s+gaya|ho\s+gya|hogaya|hai|ho\s+gayi))?\W*$"),
    _r("hg.method", r"\bzeh?a?r\s+kha\w*|\bzeher\s+kha\w*|\bneend\s+ki\s+goli\w*\s+kha\w*|\bpankhe\s+se\s+latak\w*|\bph?aansi\s+laga\w*|\bphansi\s+laga\w*|\bchhat\s+se\s+(?:kood|kud)\w*|\bnas\s+kaat\w*|\bhath\s+kaat\w*|\bsubah\s+(?:na|nahi|nhi)\s+uth\w*|\bsote\s+sote\s+mar\w*|\bneend\s+(?:me|mein)\s+hi\s+mar\w*", neg=True),
    # Devanagari Hindi
    _r("hi.mar_jana", r"मर\s*जाना\s+चाह|मरना\s+चाह|मर\s*जा(?:ऊ|उ)[ंँ]?(?:गा|गी)?(?![ा-ौ])", neg=True, exempt=r"भूख|हँस|हंस|हास|शर्म|गर्मी|ठंड|प्यास|बोर"),
    _r("hi.jeene_ka_man", r"जीने\s+का\s+(?:मन|मूड|दिल|इच्छा)\s+(?:ही\s+)?(?:नहीं|नही|नहि)|जीना\s+(?:ही\s+)?(?:नहीं|नही)\s+चाह|जीने\s+की\s+(?:इच्छा|वजह|उम्मीद|कोई\s+वजह)\s+(?:ही\s+)?(?:नहीं|नही)|ज\u093c?ि(?:ं|न्)दगी\s+(?:खत्म|ख़त्म|से\s+(?:थक|तंग))|और\s+नहीं\s+जी\s+(?:सकता|सकती)|जीने\s+से\s+(?:थक|तंग)|जीवन\s+(?:खत्म|समाप्त)"),
    _r("hi.khud_ko", r"खुद\s*को\s+(?:खत्म|मार|नुकसान|चोट|ख़त्म|काट)|आत्महत्या|आत्मघात|खुदकुशी|खुदखुशी|अपनी\s+जान\s+(?:दे|ले)|जान\s+दे\s+(?:दूँ|दूं|दूंगा|दूँगा|दूंगी|दूँगी|दिया)", neg=True, topic=True),
    _r("hi.sab_khatam", r"सब\s+(?:कुछ\s+)?(?:खत्म|ख़त्म)\s+कर|^\W*(?:अब\s+|बस\s+|मेरा\s+)*सब\s+(?:कुछ\s+)?(?:खत्म|ख़त्म)(?:\s+(?:हो\s+गया|है|हो\s+गई))?\W*$"),
    _r("hi.na_hota", r"मैं\s+न\s+होता\s+तो|मैं\s+न\s+होती\s+तो|मेरे\s+बिना\s+सब|पैदा\s+(?:ही\s+)?नहीं\s+(?:होना|हुआ|हुई)|मेरे\s+(?:जाने|मरने)\s+से\s+किसी\s+को\s+फर्क|किसी\s+को\s+फर्क\s+नहीं\s+पड़ेगा"),
    _r("hi.method", r"जहर\s+खा|ज़हर\s+खा|फांसी\s+लगा|फाँसी\s+लगा|छत\s+से\s+कूद|नींद\s+की\s+गोलियां?\s+खा|नस\s+काट|सुबह\s+(?:न|नहीं)\s+उठ", neg=True),
]

# ----------------------------------------------------------------------------- ELEVATED (distress)
# (category, weight, pattern). Two points make ELEVATED: one strong signal, or two different categories.
_E = [
    ("hopeless", 2, r"\bhopeless\b(?!\s+(?:at|with|romantic|case|in\s+(?:maths|cooking|math)))|\bno\s+hope\b|\bhopeless\s+about\s+(?:my\s+)?(?:life|future)\b|\bcan'?t\s+see\s+(?:a\s+)?(?:future|way\s+out)\b|\bdon'?t\s+see\s+(?:a\s+)?(?:way\s+out|future|point)\b|\bno\s+(?:way\s+out|future)\b|\blife\s+is\s+(?:pointless|meaningless|over|ruined|hell)\b|\bno\s+point\s+(?:in\s+)?(?:anything|trying|it\s+all)\b|\bnothing\s+(?:matters|is\s+left|left\s+for\s+me)\b|\bi\s+have\s+nothing\s+left\b|\bnothing\s+to\s+live\b"),
    ("hopeless", 2, r"\bkoi\s+(?:umeed|ummeed)\s+(?:nahi|nhi|nahin)|\b(?:umeed|ummeed)\s+(?:khatam|nahi|nhi)|\bkuch\s+(?:nahi\s+bacha|bacha\s+nahi)|\bab\s+(?:aur\s+)?(?:nahi|nhi)\s+(?:ho\s+sakta|seh\s+sakta|sah\s+sakta|jhel\s+sakta|sehna)|\bhar\s+gaya\s+hu|\bhar\s+gayi\s+hu|\bsab\s+(?:kuch\s+)?(?:barbaad|bekaar|bekar)\b|कोई\s+उम्मीद\s+नहीं|अब\s+और\s+नहीं\s+(?:सह|सहा|झेल)|हार\s+(?:गया|गई)|सब\s+(?:कुछ\s+)?(?:बर्बाद|बेकार)"),
    ("worthless", 2, r"\bworthless\b|\bi(?:'m|\s+am)\s+(?:a\s+)?(?:burden|waste\s+of\s+space)\b|\bburden\s+(?:to|on|for)\s+(?:everyone|everybody|my\s+family|all|them)\b|\bno\s+one\s+(?:cares|would\s+(?:miss|notice))\b|\bnobody\s+(?:cares|would\s+(?:miss|notice))\b|\bnobody\s+needs\s+me\b|\bno\s+one\s+needs\s+me\b|\bbojh\s+(?:hoon|hu|hun|ban)\w*|\bsabke\s+liye\s+bojh\b|\bkisi\s+kaam\s+ka\s+nahi\b|\bkoi\s+(?:parwah|parvah|fikr)\s+nahi\s+(?:karta|karti)|बोझ\s+(?:हूँ|हूं|बन)|किसी\s+काम\s+का\s+नहीं|कोई\s+परवाह\s+नहीं"),
    ("cant_take", 2, r"\bcan'?t\s+(?:take|handle|bear|do)\s+(?:this|it|any\s*more|it\s+any\s*more|this\s+any\s*more)\b|\bcan'?t\s+go\s+on\b|\bi\s+(?:give|gave)\s+up\b|\bgive\s+up\s+on\s+(?:life|everything)\b|\bwant\s+to\s+disappear\b|\bwish\s+i\s+could\s+disappear\b|\bi'?m\s+done\s+with\s+everything\b|\bfeel\s+(?:so\s+)?(?:trapped|broken|numb)\b|\bpanic\s+attacks?\b|\bbreaking\s+down\b|\bbreakdown\b|\bi(?:'m|\s+am)\s+(?:so\s+)?depressed\b|\bdepressed\b|\bdepression\b|\bnow\s+i\s+can'?t\s+anymore\b|\bab\s+aur\s+nahi\b"),
    ("cant_take", 2, r"\bsab\s+se\s+thak\s+(?:gaya|gayi)\b|\bthak\s+(?:gaya|gayi)\s+hu\w*\s+(?:sab\s+se|zindagi)|\bbreakdown\b|\bghabrahat\b|सब\s+से\s+थक|बहुत\s+थक\s+(?:गया|गई)\s+हूँ\s+सब|डिप्रेशन|डिप्रेस्ड|घबराहट"),
    ("job_loss", 1, r"\blost\s+(?:my\s+)?job\b|\bgot\s+(?:fired|laid\s+off|terminated)\b|\blaid\s+off\b|\bfired\s+from\b|\bunemployed\b|\bjobless\b|\bnaukri\s+(?:chali|chhut|chut|gayi|nahi|chod)|\bjob\s+(?:chali|chhut|chut|gayi|gai|nahi\s+mil)|\bnikal\s+diya\b|नौकरी\s+(?:चली|छूट|नहीं)|निकाल\s+दिया|बेरोज़गार|बेरोजगार"),
    ("failure", 1, r"\b(?:i(?:'m|\s+am)\s+(?:a\s+)?(?:total\s+|complete\s+|such\s+a\s+)?(?:failure|loser|useless)|failure\s+hu+n?|failure\s+hoon|nalayak|nikamma|nikami|bekaar\s+(?:hu|hoon|insaan)|fail\s+ho\s+gaya|fail\s+ho\s+gayi|feel\s+like\s+a\s+failure|total\s+failure)\b|असफल|नाकाम|बेकार\s+(?:हूँ|हूं|इंसान)|निकम्मा|नालायक|फेल\s+हो\s+गया"),
    ("sleep", 1, r"\bcan'?t\s+sleep\b|\bnot\s+sleeping\b|\bsleepless\b|\bhaven'?t\s+(?:slept|been\s+sleeping)\b|\bno\s+sleep\b|\binsomnia\b|\bneend\s+(?:nahi|nhi|nahin)\s+(?:aati|aa\s+rahi|aa\s+rhi)|\braat\s+bhar\s+jag\w*|नींद\s+(?:नहीं|नही)|रात\s+भर\s+जाग"),
    ("isolation", 1, r"\ball\s+alone\b|\bso\s+alone\b|\bcompletely\s+alone\b|\bno\s+one\s+to\s+talk\b|\bnobody\s+to\s+talk\b|\bakel[ae]\s+(?:hu|hoon|ho\s+gaya|ho\s+gayi|pad\s+gaya)|\bkoi\s+nahi\s+(?:hai\s+mere|samajhta|sunta)|\bbahut\s+(?:akela|akeli)\b|अकेला\s+(?:हूँ|हूं|पड़)|अकेली\s+(?:हूँ|हूं|पड़)|बहुत\s+अकेला|कोई\s+नहीं\s+(?:है|समझता|सुनता)"),
    ("money", 1, r"\bin\s+debt\b|\bdrowning\s+in\s+debt\b|\bkarz\w*\s+(?:mein|me)\b|\bqarz\b|कर्ज़|कर्ज"),
    ("crying", 1, r"\bcrying\s+(?:all\s+day|non\s*stop|since|every)|\bcan'?t\s+stop\s+crying\b|\bro\s+(?:raha|rahi)\s+hu|\brona\s+(?:aa|ruk)|रो\s+(?:रहा|रही)\s+हूँ|रोना\s+(?:आ|बंद)"),
    ("exhausted", 1, r"\btired\s+of\s+everything\b|\bexhausted\s+with\s+(?:everything|it\s+all)\b|\bdone\s+with\s+everything\b|\bsab\s+kuch\s+bahut\s+bhaari\b"),
]
ELEVATED_RULES: list[tuple[str, int, re.Pattern[str]]] = [(c, w, _c(p)) for c, w, p in _E]
_ELEVATED_NEEDS = 2

# ----------------------------------------------------------------------------- context filters
_HYPERBOLE = _c(
    r"\b(?:laugh\w*|giggl\w*|lol|lmao|rofl|haha+|hehe+)\b|\bhasi\b|\bhans\s*hans\b|\bhans\s*ke\b|हंस|हँस|हँसी|हास्य|😂|🤣"
    r"|\b(?:die|dying|dead|died|kill(?:ing|ed)?)\s+(?:of|from|for|to\s+(?:see|know|meet|try|get|go|hear))\s+(?:embarrassment|shame|hunger|boredom|cringe|laughter|cold|heat|excitement|curiosity|food|pizza|chai|this|that|it)\b"
    r"|\bto\s+die\s+for\b|\bdying\s+to\b|\bdie[\s-]?hard\b|\bkill(?:ing)?\s+it\b|\bkill\s+(?:time|the\s+(?:process|app|task|bug|noise)|this\s+(?:bug|process))\b"
)
# plain information or product talk: "suicide prevention app idea", "article on self harm"
_TOPIC_WORDS = r"(?:suicid\w*|self[\s\-]?harm\w*|आत्महत्या|खुदकुशी)"
_INFO = _c(
    rf"{_TOPIC_WORDS}\s+(?:prevention|awareness|helpline|hotline|statistics|stats|rates?|research|app|apps|website|article|movie|film|song|book|novel|documentary|essay|project|thesis|news|policy|policies|law|laws|squad|bridge|note\s+in\s+(?:the\s+)?(?:movie|book|film))\b"
    rf"|\b(?:prevention|awareness|article|essay|documentary|movie|film|novel|book|song|statistics|research|news|study|report|app|hotline|helpline)\s+(?:of|on|about|for|against|around)\s+(?:\w+\s+){{0,2}}{_TOPIC_WORDS}"
    rf"|\b(?:signs|symptoms|causes|reasons|history|meaning|definition|facts|laws?|rate|rates)\s+(?:of|about|on)\s+{_TOPIC_WORDS}"
    rf"|\bhow\s+to\s+(?:help|support|talk\s+to|prevent|spot|stop)\s+(?:\w+\s+){{0,4}}{_TOPIC_WORDS}"
    rf"|\bwhat\s+is\s+{_TOPIC_WORDS}|{_TOPIC_WORDS}\s+(?:kya\s+hai|ke\s+baare\s+mein|ki\s+roktham|ko\s+rokne)"
    rf"|(?:आत्महत्या|खुदकुशी)\s+(?:रोकथाम|जागरूकता|हेल्पलाइन|पर\s+(?:लेख|निबंध|फिल्म|खबर|रिपोर्ट))"
)
_PRE_NEG_EN = re.compile(r"(?:\b(?:do\s*n'?t|dont|do\s+not|never|not|won'?t|wont|will\s+not|no\s+way|am\s+not|aren'?t|isn'?t|didn'?t|wouldn'?t|would\s+not|can'?t\s+imagine|nahi|nhi|kabhi\s+nahi|mat)\s+(?:(?!(?:i|me|my|main|mai|mein)\b)[\w']+\s+){0,2})$", _I)
_POST_NEG = re.compile(r"^\s*(?:(?:[\w']+\s+){0,1})(?:nahi|nhi|nai|nahin|mat|नहीं|नही|मत|never|not)\b", _I)
_FIRST_PERSON_SELF = re.compile(r"\b(?:i|i'm|i'll|i've|me|my|myself)\b", _I)


def _clause(view: str, m: re.Match[str]) -> str:
    """The stretch of the message around a match, up to the nearest punctuation on both sides."""
    start = max(view.rfind(ch, 0, m.start()) for ch in ".,;!?\n") + 1
    ends = [i for ch in ".,;!?\n" if (i := view.find(ch, m.end())) != -1]
    return view[start : min(ends) if ends else len(view)]


def _negated(view: str, m: re.Match[str]) -> bool:
    before = re.split(r"[.,;!?\n]", view[: m.start()])[-1]
    if _PRE_NEG_EN.search(before.lower()):
        return True
    after = re.split(r"[.,;!?\n]", view[m.end():])[0]
    return bool(_POST_NEG.match(after))


# ----------------------------------------------------------------------------- third person
_THIRD = _c(
    r"\b(?:my|his|her|their|our)\s+(?:close\s+)?(?:friend|brother|sister|mother|mom|mum|father|dad|husband|wife|son|daughter|colleague|cousin|partner|boyfriend|girlfriend|roommate|classmate|student|neighbou?r|uncle|aunt|maid|driver|boss)\s+(?:\w+\s+){0,3}?(?:says|said|is|was|wants?|talks?|keeps?|told|threatened|tried|has|thinks?|mentioned|texted|feels?|felt|wanted)\b[^.!?\n]{0,60}"
    r"|\b(?:he|she|they)\s+(?:wants?|wanted|said\s+(?:he|she|they)\s+(?:wants?|will)|is\s+(?:suicidal|talking\s+about)|keeps\s+talking\s+about)\s+[^.!?\n]{0,50}"
    r"|\b(?:mera|meri|uska|uski|mere)\s+(?:dost|bhai|bhaiya|behen|bahan|didi|maa|mummy|papa|pati|patni|beta|beti|friend|colleague|padosi|cousin)\s+(?:\w+\s+){0,6}?(?:mar\s*jaa?na|marna|mar\s*jaun|suicide|khudkushi|jaan\s+de|khud\s*ko|jeene|zindagi)[^.!?\n]{0,40}"
    r"|(?:मेरा|मेरी|उसका|उसकी|मेरे)\s+(?:दोस्त|भाई|बहन|माँ|मां|पापा|पति|पत्नी|बेटा|बेटी|सहेली)\s+(?:\S+\s+){0,6}?(?:मरना|मर\s*जाना|आत्महत्या|खुदकुशी|जान\s+दे|खुद\s*को|जीने|ज़िंदगी|जिंदगी)[^.!?\n]{0,40}"
)

# ----------------------------------------------------------------------------- language
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HINGLISH = frozenset(
    "hai hain hu hun hoon ho nahi nhi nai nahin mujhe mera meri mere main mai mein kya kyun kyu aap tum "
    "ka ki ke ko se par pe bahut bohot bhi toh to abhi ab kuch sab koi kisi raha rahi rha rhi tha thi "
    "karna kar karo kiya gaya gayi chahta chahti chahiye jaana jana jaun jeene jeena zindagi khatam "
    "akela akeli thak bhai behen dost maa papa haan ji theek thik bas mat kal aaj raat neend naukri".split()
)


def detect_language(text: str) -> str:
    """``hi`` when mostly Devanagari, ``hinglish`` for Roman Hindi, else ``en``."""
    letters = [ch for ch in text if ch.isalpha()]
    if letters and sum(1 for ch in letters if _DEVANAGARI.match(ch)) * 2 >= len(letters):
        return "hi"
    words = re.findall(r"[a-z']+", text.lower())
    hits = sum(1 for w in words if w in _HINGLISH)
    return "hinglish" if hits >= 2 or (hits >= 1 and len(words) <= 3) else "en"


# ----------------------------------------------------------------------------- the entry point
def _high_hits(views: list[str], squashed: str) -> list[str]:
    hits: list[str] = []
    for view in views:
        info = bool(_INFO.search(view))
        short = len(view.split()) <= 3
        for rule in HIGH:
            for m in rule.pat.finditer(view):
                if rule.exempt and rule.exempt.search(view):
                    continue
                if rule.negatable and _negated(view, m):
                    continue
                if rule.hyperbole and _HYPERBOLE.search(_clause(view, m)):
                    continue
                if rule.topic and (info or (rule.id in ("en.suicide_topic", "hg.suicide_word", "en.self_harm_word") and not (short or _FIRST_PERSON_SELF.search(view) or re.search(r"thinking|thought|think|about|feel|plan|attempt|tried|commit|chahta|karna|karun|mann|vichar|khayal", view)))):
                    continue
                if rule.id not in hits:
                    hits.append(rule.id)
                break
    if not hits and re.search(r"khudkokhatam|khudkomaar|marnachah|jeenekamannahi|iwanttodie|wanttodie|endmylife|killmyself", squashed):
        # letters typed with stray gaps only: a plain phrase was already judged (negation, jokes) above
        plain = re.compile(r"kill\s*my\s*self|end\s*my\s*life|want\s*to\s*die|khud\s*ko\s*khatam|khud\s*ko\s*maar|marna\s*chah|jeene\s*ka\s*mann", _I)
        if not any(plain.search(v) for v in views):
            hits.append("squashed")
    return hits


def _elevated_score(views: list[str]) -> tuple[int, list[str]]:
    best, cats = 0, []
    for view in views:
        seen: dict[str, int] = {}
        for cat, weight, pat in ELEVATED_RULES:
            if pat.search(view):
                seen[cat] = max(seen.get(cat, 0), weight)
        score = sum(seen.values())
        if score > best:
            best, cats = score, sorted(seen)
    return best, cats


def assess(text: str | None) -> Assessment:
    """Tier of one message. Pure and deterministic."""
    raw = (text or "").strip()
    if not raw:
        return NONE
    raw = raw[:2000]
    lang = detect_language(raw)
    views = variants(raw)
    third = False
    cleaned = []
    for v in views:
        if _THIRD.search(v):
            third = True
            v = _THIRD.sub(" ", v)
        cleaned.append(v)
    squashed = squash(raw) if len(raw) <= 120 else ""
    hits = _high_hits(cleaned, squashed)
    if hits:
        return Assessment(Tier.HIGH, tuple(hits), lang)
    score, cats = _elevated_score(cleaned)
    if score >= _ELEVATED_NEEDS:
        return Assessment(Tier.ELEVATED, tuple(cats), lang)
    if third:
        return Assessment(Tier.ELEVATED, ("third_party",), lang, third_party=True)
    return Assessment(Tier.NONE, (), lang)


# ----------------------------------------------------------------------------- small helpers
_OKAY = _c(
    r"^\W*(?:(?:i\s*(?:am|'m)|im|main|mai|mein)\s+)?(?:(?:ab|now|really|bilkul|sach\s+mein)\s+)*(?:ok(?:ay)?|fine|better|safe|alright|all\s+right|good|theek|thik|ठीक|सुरक्षित)\b[^?]{0,40}$"
    r"|\b(?:i\s*(?:am|'m)|im)\s+(?:ok(?:ay)?|fine|safe|alright|better\s+now|good\s+now)\b|\b(?:main|mai|mein)\s+(?:ab\s+)?(?:theek|thik|safe|thik\s+hu|theek\s+hu)\b|\bab\s+(?:theek|thik)\s+(?:hu|hoon|hun)\b|\bi\s+am\s+ok\b|मैं\s+(?:अब\s+)?(?:ठीक|सुरक्षित)|अब\s+ठीक"
)
_STOP = _c(r"^\W*(?:stop|rukiye|ruko|ruk\s+jao|bas|enough|band\s+karo|mat\s+bhejo|no\s+more|leave\s+me\s+alone|रुकिए|रुको|बस|बंद\s+करो)\W*$")
_YES = _c(r"^\W*(?:yes|yeah|yep|yup|ya|haan|han|haa+|ha|hmm+\s+yes|hanji|haan\s+ji|ji\s+haan|sometimes|kabhi\s+kabhi|thoda|a\s+little|i\s+do|हाँ|हां|जी\s+हाँ|हाँ\s+जी|कभी\s+कभी)(?!\w)")
_NO = _c(r"^\W*(?:no|nope|nah|nahi|nhi|nai|nahin|not\s+really|na|i\s+don'?t|i\s+do\s+not|नहीं|नही|ना)(?!\w)")
_CALL_YES = _c(r"\b(?:call\s+me|ring\s+me|phone\s+me|yes\s+call|call\s+karo|call\s+kar\s+do|mujhe\s+call|phone\s+karo|call\s+kijiye)\b|कॉल\s+(?:करो|कर\s+दो|कीजिए)|फोन\s+करो")
_PERSON = _c(
    r"\b(?:mom|mother|mum|mummy|maa|papa|father|dad|sister|brother|didi|bhai|bhaiya|behen|bahan|friend|dost|partner|wife|husband|cousin|uncle|aunt|teacher|boyfriend|girlfriend|bf|gf|colleague)\b|माँ|मां|मम्मी|पापा|भाई|बहन|दीदी|दोस्त|पति|पत्नी|सहेली"
)


def says_okay(text: str | None) -> bool:
    return any(_OKAY.search(v) for v in variants(text))


def says_stop(text: str | None) -> bool:
    return any(_STOP.search(v) for v in variants(text))


def says_yes(text: str | None) -> bool:
    return any(_YES.search(v) for v in variants(text))


def says_no(text: str | None) -> bool:
    return any(_NO.search(v) for v in variants(text))


def says_call_me(text: str | None) -> bool:
    return any(_CALL_YES.search(v) for v in variants(text))


def names_person(text: str | None) -> str | None:
    """The word the user used for a trusted person ("my sister", "meri behen", "Riya"), or None.
    Only letters are kept and the length is capped; it is used once to write the draft and is not
    stored."""
    t = (text or "").strip()
    m = _PERSON.search(t.lower()) if t else None
    if m:
        return m.group(0)
    words = re.findall(r"[^\W\d_]+", t, flags=re.UNICODE)
    if 1 <= len(words) <= 3 and len(t) <= 30 and not says_yes(t) and not says_no(t):
        return " ".join(w.capitalize() if w.isascii() else w for w in words)[:24]
    return None


def is_distress(text: str | None) -> bool:
    """True when the text shows HIGH or ELEVATED distress. Used by the stores that must never keep
    such words (reply log, evidence ledger text, exports)."""
    return assess(text).tier != Tier.NONE
