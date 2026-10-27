"""The "is this right?" message: a short summary of the kept fields and three buttons."""

from __future__ import annotations

from friday.core.models import ReplyButton
from friday.docunderstand import copy
from friday.docunderstand.models import Document
from friday.docunderstand.schemas import SHOW, SPECS, parse_date, parse_dt
from friday.docunderstand.validators import Issue

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _d(d) -> str:  # noqa: ANN001
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def display_value(field: str, value: str, doc: Document, language: str) -> str:
    kind = SPECS[doc.doc_type].get(field, "str")
    if kind == "paise":
        paise = int(value)
        amount = f"{paise // 100:,}" + (f".{paise % 100:02d}" if paise % 100 else "")
        return copy.t("money", language, amount=amount)
    if kind in ("dt", "dt_or_date") and (dt := parse_dt(value)):
        return f"{_d(dt)}, {dt:%H:%M}"
    if kind in ("date", "dt_or_date") and (d := parse_date(value)):
        return _d(d)
    if kind == "bool":
        return copy.t("yes" if value == "true" else "no", language)
    return value


def summary_text(doc: Document, issues: list[Issue], language: str) -> str:
    lines = [copy.t(f"head.{doc.doc_type.value}", language)]
    for name in SHOW[doc.doc_type]:
        f = doc.fields.get(name)
        if f is None:
            continue
        mark = f" ({copy.t('unsure', language)})" if f.needs_confirm else ""
        lines.append(
            f"{copy.label(name, language)}: {display_value(name, f.value, doc, language)}{mark}"
        )
    if doc.doc_type.value == "passport":
        lines.append(copy.t("note.passport", language))
    if doc.injection_flag:
        lines.append(copy.t("note.injection", language))
    for code in dict.fromkeys(i.code for i in issues):
        key = f"note.{code}"
        if key in copy.TEXTS:
            lines.append(copy.t(key, language))
    lines.append(copy.t("ask", language))
    return "\n".join(lines)


def buttons(doc: Document, language: str) -> list[ReplyButton]:
    return [
        ReplyButton(id=copy.button_id("ok", doc.id), title=copy.t("btn.ok", language)),
        ReplyButton(id=copy.button_id("fix", doc.id), title=copy.t("btn.fix", language)),
        ReplyButton(id=copy.button_id("drop", doc.id), title=copy.t("btn.drop", language)),
    ]
