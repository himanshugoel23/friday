# ruff: noqa: E501
"""FACT CHECK and style post-check for every LlmWriter output (docs/REPLY_WRITER.md).

Pure functions. A reply passes only when every number, price, store name, pack size and URL in its text
appears in the input facts (after normalisation), no internal status code is printed, and the style rules
(length, one question, no headers, no flat refusal, script) hold. Any failure => the caller uses the
TemplateWriter. The check is a floor, not a judge of taste.
"""

from __future__ import annotations

import re

from friday.replywriter.schema import Facts, ReplyInput, ReplyOutput
from friday.style import check as style_check

KNOWN_STORES = (
    "zepto", "blinkit", "instamart", "swiggy", "bigbasket", "big basket", "amazon", "jiomart", "jio mart",
    "flipkart", "zomato", "dunzo", "dmart", "d-mart", "reliance fresh", "licious", "milkbasket", "myntra",
    "nykaa", "croma", "meesho", "1mg", "pharmeasy", "netmeds",
)  # fmt: skip
_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_ORDINAL = re.compile(r"^\s*\d{1,2}[.)]\s+", re.M)
_PACK = re.compile(r"(\d+(?:\.\d+)?)\s*(kgs?|gms?|grams?|g|ltr|litres?|liters?|l|ml)\b", re.I)
_URL = re.compile(r"https?://[^\s)>\]]+|\bwww\.[^\s)>\]]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|in|co\.in|net|org|io)\b[^\s)>\]]*", re.I)
_UNIT = {"kg": "kg", "kgs": "kg", "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
         "l": "l", "ltr": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l", "ml": "ml"}  # fmt: skip


def norm_number(tok: str) -> str:
    t = tok.replace(",", "").rstrip(".")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    t = t.lstrip("0")
    return "0" + t if t == "" or t.startswith(".") else t


def fmt_rupees(paise: int) -> str:
    return norm_number(f"{paise / 100:.2f}")


def norm_pack(value: str, unit: str) -> str:
    return f"{norm_number(value)}{_UNIT[unit.lower()]}"


def norm_url(u: str) -> str:
    u = u.strip().rstrip(".,;:!?)'\"").lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _fact_strings(f: Facts) -> list[str]:
    out: list[str] = [s for s in (f.name, f.store, f.product, f.category, f.pick, f.pick_reason, f.as_of, f.place, f.topic, f.when) if s]
    out += [*f.stores, *f.stores_unread, *f.stores_offered, *f.missing, *f.links, *f.proof_refs]
    for p in f.products:
        out += [s for s in (p.name, p.store, p.pack) if s]
    return out


def allowed_numbers(inp: ReplyInput) -> set[str]:
    f = inp.facts
    ok: set[str] = set()
    for s in [*_fact_strings(f), *inp.draft]:
        ok.update(norm_number(m) for m in _NUM.findall(s))
    for p in f.products:
        if p.price_paise is not None:
            ok.add(fmt_rupees(p.price_paise))
        if p.per_unit_paise is not None:
            ok.add(fmt_rupees(p.per_unit_paise))
        if p.delivery_minutes is not None:
            ok.add(str(p.delivery_minutes))
        if p.rating is not None:
            ok.add(norm_number(f"{p.rating}"))
    ok.update({str(len(f.products)), str(len(f.stores)), str(len(f.stores_unread))} - {"0"})
    ok.add(str(len(f.stores) + len(f.stores_unread)))
    return ok


def _allowed_stores(inp: ReplyInput) -> str:
    f = inp.facts
    names = [*f.stores, *f.stores_unread, *f.stores_offered, f.store or "", f.product or "", f.pick or "", *inp.draft]
    names += [p.store or "" for p in f.products] + [p.name for p in f.products]
    return " ".join(names).lower()


def _allowed_packs(inp: ReplyInput) -> set[str]:
    texts = [p.pack or "" for p in inp.facts.products] + [p.name for p in inp.facts.products] + _fact_strings(inp.facts) + list(inp.draft)
    return {norm_pack(m.group(1), m.group(2)) for t in texts for m in _PACK.finditer(t)}


def fact_violations(inp: ReplyInput, text: str) -> list[str]:
    """Codes of facts in ``text`` that are not in the input facts. Empty list = every fact is grounded."""
    bad: list[str] = []
    f = inp.facts
    body = _ORDINAL.sub("", text)
    urls = [norm_url(u) for u in _URL.findall(body)]
    allowed_urls = {norm_url(u) for u in [*f.links, *[m for d in inp.draft for m in _URL.findall(d)]]}
    for u in urls:
        if u not in allowed_urls and not any(u.startswith(a) or a.startswith(u) for a in allowed_urls if a):
            bad.append("unknown_url")
            break
    no_urls = _URL.sub(" ", body)
    packs = {norm_pack(m.group(1), m.group(2)) for m in _PACK.finditer(no_urls)}
    if packs - _allowed_packs(inp):
        bad.append("unknown_pack")
    ok = allowed_numbers(inp)
    nums = {norm_number(m) for m in _NUM.findall(no_urls)}
    if nums - ok:
        bad.append("unknown_number")
    low = no_urls.lower()
    have = _allowed_stores(inp)
    for s in KNOWN_STORES:
        if re.search(rf"(?<![a-z]){re.escape(s)}(?![a-z])", low) and s not in have and s.replace(" ", "") not in have.replace(" ", ""):
            bad.append("unknown_store")
            break
    # an internal code is printed when a snake_case token (no_result, layout_changed) or a 'lookup:x' / 'status: x' pattern is in the text;
    # plain words that are also codes (blocked, timeout) are ordinary English and allowed
    if re.search(r"\b[a-z]+(?:_[a-z]+)+\b|\b(?:lookup|status|code)\s*[:=]\s*\w+", low):
        bad.append("leaked_code")
    return bad


def style_violations(inp: ReplyInput, out: ReplyOutput) -> list[str]:
    """Style post-check: each message 1-5 lines/450 chars, exactly <=1 question overall, no headers, no flat refusal, script."""
    codes: list[str] = []
    joined = "\n".join(out.messages)
    for i, m in enumerate(out.messages):
        for v in style_check.check(m, kind="text", has_buttons=bool(out.buttons)):
            if v.code == "options_before_headline" and i > 0:
                continue
            if v.code == "many_questions":
                continue  # judged on the whole reply below
            codes.append(v.code)
    if style_check.question_groups(joined) > 1 or len(re.findall(r"[?？]", joined)) > 1:  # the writer asks at most ONE question
        codes.append("many_questions")
    if "no_question" in inp.style and "?" in joined:
        codes.append("question_not_wanted")
    if inp.script == "roman" and style_check.script_violation("hello", joined):
        codes.append("script_mismatch")
    if inp.script == "devanagari" and style_check.script_violation("नमस्ते", joined):
        codes.append("script_mismatch")
    allowed = {b.id for b in inp.buttons}
    if any(b.id not in allowed for b in out.buttons):
        codes.append("unknown_button")
    if any(p not in inp.facts.proof_refs for p in out.proofs):
        codes.append("unknown_proof")
    return sorted(set(codes))


def verify(inp: ReplyInput, out: ReplyOutput) -> list[str]:
    """All problems with ``out`` (fact errors and style errors). Empty list = safe to send."""
    text = "\n".join(out.messages)
    return sorted(set(fact_violations(inp, text) + style_violations(inp, out)))
