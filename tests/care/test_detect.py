# ruff: noqa: E501
"""Care detection: many positive and negative examples in English, Roman Hinglish and Devanagari."""

from __future__ import annotations

import pytest

from friday.care.detect import (
    Tier,
    assess,
    detect_language,
    names_person,
    says_no,
    says_okay,
    says_stop,
    says_yes,
)

HIGH_EN = [
    "I want to die", "i wanna kill myself", "everyone would be better off without me",
    "it would be better if I was not born", "no point living anymore", "I just want to end it all",
    "I think I should end it", "end it", "I am feeling suicidal", "thinking about suicide", "suicide",
    "I don't want to live anymore", "I wish I was dead", "i'm going to hurt myself tonight",
    "I took all my pills", "I will kill myself if I fail", "s u i c i d e", "wan t to die",
    "I have suicidal thoughts again", "I'm going to cut my wrists", "I can't see a reason to live, no reason to live",
    "I keep thinking about ending my life", "I wish I had never been born", "life is not worth living",
]
HIGH_HINGLISH = [
    "mujhe jeene ka mann nahi karta", "main mar jaana chahta hu", "mar jaunga ab", "khud ko khatam kar lunga",
    "sab khatam", "sab khatam kar dunga", "zindagi khatam", "main na hota toh behtar hota",
    "kisi ko fark nahi padega agar main mar jaun", "suicide kar lunga", "jeena nahi chahta", "zeher kha lunga",
    "ab aur nahi jee sakta", "kh u d ko khatam kar dunga", "main marna chahti hoon", "mera na hona hi behtar hai",
    "jeene ki koi wajah nahi hai", "zindagi se thak gaya hu, jeene se thak gaya", "apni jaan de dunga",
]
HIGH_HINDI = [
    "मुझे जीने का मन नहीं है", "मैं मरना चाहता हूँ", "मर जाना चाहती हूँ", "मैं खुद को खत्म कर लूंगा",
    "आत्महत्या कर लूंगा", "सब खत्म", "मैं न होता तो बेहतर होता", "मेरे जाने से किसी को फर्क नहीं पड़ेगा",
    "जिंदगी खत्म", "ज़िंदगी से थक गया हूँ", "जहर खा लूंगा", "मैं जीना नहीं चाहता", "अब और नहीं जी सकता",
]
NONE_TEXT = [
    "suicide prevention app idea", "I will die laughing", "dying to see the movie",
    "this joke will kill me, I'm laughing so hard", "I don't want to die", "I am not suicidal",
    "I would never kill myself", "how to help someone who is suicidal", "article about self harm statistics",
    "end it with my landlord", "kill the process", "book a table for two", "I'm so hungry I could die",
    "this heat is killing me", "to die for chocolate cake", "I lost my job, find me jobs", "order milk",
    "write an essay on suicide in the novel", "hopeless at cooking", "can you call my sister",
    "I'm dead tired after the gym", "kill time before the meeting", "documentary on suicide awareness",
    "end the meeting now", "I could die of embarrassment", "what is the suicide helpline policy for our app",
    "sabzi sab khatam ho gayi aur main market ja raha hu", "marna nahi chahta main", "bhookh se mar jaunga yaar",
    "hasi se mar jaunga", "mera phone ka battery khatam ho gaya", "paise sab khatam ho gaye is mahine",
    "aaj ka kaam khatam", "doctor ko call karo", "jeene ka tareeka sikhao yoga",
    "मैं मरना नहीं चाहता", "आत्महत्या रोकथाम पर निबंध", "हँसते हँसते मर जाऊंगा", "मुझे चाय चाहिए",
    "मेरा फ़ोन खराब हो गया", "बिजली का बिल कब आएगा", "आज का काम खत्म हो गया है और मैं घर जा रहा हूँ",
    "sleep", "hello", "",
]
ELEVATED_TEXT = [
    "I lost my job, I'm a failure and I can't sleep", "I feel hopeless", "I am worthless",
    "I feel so alone and I can't stop crying", "naukri chali gayi, main failure hu, neend nahi aati",
    "koi umeed nahi hai", "main kisi kaam ka nahi hu", "ab aur nahi ho sakta mujhse",
    "मैं बेकार हूँ और नींद नहीं आती, नौकरी चली गई", "कोई उम्मीद नहीं बची", "मैं बहुत अकेला हूँ और रोना आ रहा है",
    "I can't take this anymore", "nobody cares about me",
]


@pytest.mark.parametrize("text", HIGH_EN + HIGH_HINGLISH + HIGH_HINDI)
def test_high(text):
    assert assess(text).tier == Tier.HIGH, text


@pytest.mark.parametrize("text", NONE_TEXT)
def test_none(text):
    assert assess(text).tier == Tier.NONE, text


@pytest.mark.parametrize("text", ELEVATED_TEXT)
def test_elevated(text):
    assert assess(text).tier == Tier.ELEVATED, text


@pytest.mark.parametrize("text", [
    "my friend says he wants to die", "meri behen kehti hai ki wo mar jaana chahti hai",
    "मेरा दोस्त आत्महत्या की बात कर रहा है",
])
def test_third_person_is_elevated_with_flag(text):
    a = assess(text)
    assert a.tier == Tier.ELEVATED and a.third_party


def test_single_weak_signals_do_not_trigger():
    for t in ["I lost my job", "I can't sleep", "I'm a failure at chess", "naukri chali gayi", "akela hu ghar pe"]:
        assert assess(t).tier == Tier.NONE, t


def test_a_cluster_needs_two_different_kinds():
    assert assess("lost my job and can't sleep").tier == Tier.ELEVATED
    assert assess("can't sleep, can't sleep, insomnia").tier == Tier.NONE


def test_ideation_wins_over_joke_words_elsewhere():
    assert assess("haha no really, I want to die").tier == Tier.HIGH


def test_evasions_are_folded():
    for t in ["I WANT TO DIE", "i want to diiiiie", "ｉ ｗａｎｔ ｔｏ ｄｉｅ", "I w​ant to d​ie"]:
        assert assess(t).tier == Tier.HIGH, t


def test_language_detection():
    assert assess("मैं मरना चाहता हूँ").lang == "hi"
    assert assess("mujhe jeene ka mann nahi karta").lang == "hinglish"
    assert assess("I want to die").lang == "en"
    assert detect_language("ok") == "en"


def test_small_answers():
    assert says_yes("haan") and says_yes("Yes.") and says_yes("हाँ") and not says_yes("nahi")
    assert says_no("nahi") and says_no("No") and says_no("नहीं") and not says_no("yes")
    assert says_okay("I'm okay") and says_okay("main theek hu") and says_okay("ab theek hoon")
    assert not says_okay("order milk")
    assert says_stop("stop") and says_stop("बस") and not says_stop("don't stop talking to me please")


def test_person_words_only_letters():
    assert names_person("my sister") == "sister"
    assert names_person("meri behen ko") == "behen"
    assert names_person("Riya") == "Riya"
    assert names_person("<script>alert(1)</script> x y z w") is None
    assert names_person("yes") is None
