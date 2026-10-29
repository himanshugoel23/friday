# ruff: noqa: E501
"""TemplateWriter: the always-available writer. Existing style templates (friday/style, shopping and planner
wording) plus a few new lines (greeting, store-scoped ack, plain-words failure). PENDING founder approval.

Deterministic, no network. It is the fallback whenever the LlmWriter is off, fails or is rejected by the
fact check, so every line here must satisfy the style post-check (a test enforces it).
"""

from __future__ import annotations

from friday.replywriter import status_words as sw
from friday.replywriter.schema import Button, Facts, ProductFact, ReplyInput, ReplyOutput
from friday.shopping import wording as shop
from friday.style import builders as sb
from friday.style.check import split_messages

LINES: dict[str, dict[str, str]] = {
    "greet": {
        "en": "Hi {name}! I'm Friday, your assistant.\n- food: find a restaurant or a dish\n- shopping: compare grocery prices\n- calls, trips or reminders\nWhat can I do for you today?",
        "hinglish": "Hi {name}! Main Friday hoon, aapki assistant.\n- khana: restaurant ya dish dhoondhna\n- shopping: grocery ke daam compare karna\n- call, trip ya reminder\nAaj aapke liye kya karun?",
    },
    "greet_anon": {
        "en": "Hi! I'm Friday, your assistant.\n- food: find a restaurant or a dish\n- shopping: compare grocery prices\n- calls, trips or reminders\nWhat can I do for you today?",
        "hinglish": "Hi! Main Friday hoon, aapki assistant.\n- khana: restaurant ya dish dhoondhna\n- shopping: grocery ke daam compare karna\n- call, trip ya reminder\nAaj aapke liye kya karun?",
    },
    "ack_one": {
        "en": "On it. Checking only {store} for {cat}, as you asked.",
        "hinglish": "Ek minute, sirf {store} par {cat} dekh rahi hoon, jaisa aapne kaha.",
    },
    "ack_all": {"en": "On it. Checking {stores} for {cat} now.", "hinglish": "{stores} par {cat} check kar rahi hoon, bas ek minute."},
    "pick_one": {
        "en": "Checked {store} only. Of {n} popular {cat} options I would take {name}: {reason}.",
        "hinglish": "Sirf {store} dekha. {n} popular {cat} options mein se main {name} loongi: {reason}.",
    },
    "ask_compare": {"en": "Want me to compare with {others} too?", "hinglish": "{others} par bhi compare kar dun?"},
    "ask_retry": {"en": "Want me to try again in a minute?", "hinglish": "Ek minute baad dobara try karun?"},
    "ask_missing": {"en": "Could you tell me the {x}?", "hinglish": "Aap {x} bata dein?"},
    "failed_on": {"en": "{what} on {store}.", "hinglish": "{store} par: {what}."},
    "failed_plain": {"en": "{what}.", "hinglish": "{what}."},
    "failed_next": {"en": "{next}.", "hinglish": "{next}."},
    "and": {"en": " and ", "hinglish": " aur "},
}  # fmt: skip


def line(key: str, lang: str | None, **kw: str) -> str:
    row = LINES[key]
    text = row["en"] if lang == "en" else row["hinglish"]
    return text.format(**kw) if kw else text


def join_names(names: list[str], lang: str | None) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + line("and", lang) + names[-1]


def rs(paise: int | None) -> str:
    if paise is None:
        return ""
    rupees = paise / 100
    return f"Rs {rupees:g}"


def greeting_text(name: str | None, lang: str | None = "hinglish") -> list[str]:
    """The warm general opener: name, three example buckets (food, shopping, calls/trips/reminders), ONE question.
    Also used by the brain's small-talk reply, so the first 'Hi' never lands on a service menu."""
    return [line("greet", lang, name=name) if name else line("greet_anon", lang)]


def _product_line(i: int, p: ProductFact, lang: str | None) -> str:
    bits = [rs(p.price_paise) + (f" ({p.store})" if p.store else "")] if p.price_paise is not None else [shop.line("price_hidden", lang)]
    if p.per_unit_paise is not None and p.unit:
        bits.append(f"{rs(p.per_unit_paise)}/{p.unit}")
    if p.rating:
        bits.append(f"{p.rating:g}*")
    if p.delivery_minutes is not None:
        bits.append(f"{p.delivery_minutes} min")
    return f"{i}. {p.name}: {', '.join(bits)}"


def _pack(messages: list[str]) -> list[str]:
    out: list[str] = []
    for m in messages:
        out += [p for p in split_messages(m.strip(), "text") if p.strip()]
    if len(out) > 5:
        out = [*out[:4], "\n".join(out[4:6])] if len(out[4:]) <= 2 else out[:5]
    return out or [""]


def _finish(messages: list[str], buttons: list[Button], facts: Facts) -> ReplyOutput:
    msgs = _pack(messages)
    last = [ln for ln in msgs[-1].splitlines() if ln.strip()][-1].strip() if msgs[-1].strip() else ""
    question = last if last.endswith("?") else None
    return ReplyOutput(messages=msgs, question=question, buttons=buttons, proofs=list(facts.proof_refs), writer="template")


def _closing_question(inp: ReplyInput) -> str | None:
    f, lang = inp.facts, inp.lang
    if inp.pending == "compare_more":
        return line("ask_compare", lang, others=join_names(f.stores_offered, lang))
    if inp.pending == "place":
        return shop.line("place_ask_saved" if inp.buttons else "place_ask_new", lang)
    if inp.pending == "retry":
        return line("ask_retry", lang)
    if inp.pending == "answer" and f.missing:
        return line("ask_missing", lang, x=f.missing[0].replace("_", " "))
    return None


class TemplateWriter:
    """Pure function of the input. ``write`` never raises for a well-formed ReplyInput."""

    name = "template"

    def write(self, inp: ReplyInput) -> ReplyOutput:
        fn = getattr(self, f"_{inp.intent}", None)
        msgs = fn(inp) if fn else None
        if msgs is None:
            msgs = list(inp.draft) or [sb.honest_limit("finish that just now", "tell me a bit more and I will find the nearest thing I can do", inp.lang)]
        buttons = [b for b in inp.buttons] if (inp.pending and inp.buttons) else []
        return _finish(msgs, buttons, inp.facts)

    # ------------------------------------------------------------------ intents
    def _greeting(self, inp: ReplyInput) -> list[str]:
        return greeting_text(inp.facts.name, inp.lang)

    def _ack(self, inp: ReplyInput) -> list[str]:
        f, lang = inp.facts, inp.lang
        cat = f.category or f.product or ""
        if f.store and not f.stores and cat:
            return [line("ack_one", lang, store=f.store, cat=cat)]
        if f.stores and cat:
            return [line("ack_all", lang, stores=join_names(f.stores, lang), cat=cat)]
        return [sb.ack(f.store or join_names(f.stores, lang) or ("the web" if lang == "en" else "web"), lang)]

    def _price_compare(self, inp: ReplyInput) -> list[str] | None:
        f, lang = inp.facts, inp.lang
        if not f.products:
            return self._lookup_failed(inp)
        cat = f.category or f.product or ""
        if f.pick and f.store:
            head = line("pick_one", lang, store=f.store, n=str(len(f.products)), cat=cat, name=f.pick, reason=f.pick_reason or "")
        elif f.pick:
            head = shop.line("pick", lang, n=str(len(f.products)), cat=cat, name=f.pick, reason=f.pick_reason or "")
        else:
            head = shop.line("pick_none", lang, cat=cat)
        rows = [_product_line(i, p, lang) for i, p in enumerate(f.products[:4], 1)]
        if f.as_of:
            rows.append(shop.line("fresh", lang, time=f.as_of))
        msgs = [head, "\n".join(rows)]
        if f.stores_unread and not f.store:
            msgs[-1] += "\n" + shop.line("sites_unread", lang, names=join_names(f.stores_unread, lang))
        q = _closing_question(inp)
        if q:
            msgs.append(q)
        return msgs

    def _lookup_failed(self, inp: ReplyInput) -> list[str]:
        f, lang = inp.facts, inp.lang
        what = sw.what_happened(f.status_codes[0] if f.status_codes else None, lang)
        first = line("failed_on", lang, what=what, store=f.store) if f.store else line("failed_plain", lang, what=what)
        asked = {"compare_more": "compare_others", "retry": "retry"}.get(inp.pending or "")
        acts = [a for a in (f.next_actions or list(sw.DEFAULT_NEXT)) if a != asked]
        body = [first]
        if acts:
            nxt = sw.next_step(acts, lang)
            body.append(line("failed_next", lang, next=nxt[:1].upper() + nxt[1:]))
        q = _closing_question(inp)
        if q:
            body.append(q)
        return ["\n".join(body)]

    def _ask_one(self, inp: ReplyInput) -> list[str] | None:
        q = _closing_question(inp.model_copy(update={"pending": "answer"})) if inp.facts.missing else None
        return [q] if q else None

    def _honest_limit(self, inp: ReplyInput) -> list[str] | None:
        f = inp.facts
        if not f.topic:
            return None
        msg = sb.honest_limit(f.topic, sw.next_step(f.next_actions, inp.lang), inp.lang)
        q = _closing_question(inp)
        return [f"{msg}\n{q}" if q else msg]

    def _cancelled(self, inp: ReplyInput) -> list[str]:
        return [sb.cancelled(inp.lang, ordered=inp.facts.topic == "order")]

    def _playbook(self, inp: ReplyInput) -> list[str] | None:
        return list(inp.draft) or None
