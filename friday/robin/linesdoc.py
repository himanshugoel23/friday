# ruff: noqa: E501
"""Generates docs/ROBIN_LINES.md from lines.py (+ the festival data file): ``uv run python -m friday.robin.linesdoc``.
A test fails when the checked-in file differs, so the founder always reviews the real text."""

from __future__ import annotations

from pathlib import Path

from friday.robin import lines
from friday.robin.greetings import load_festivals

DOC = Path(__file__).resolve().parents[2] / "docs" / "ROBIN_LINES.md"

HEAD = """# Robin: every spoken and chat line (ALL PENDING_FOUNDER_APPROVAL)

Generated from `friday/robin/lines.py` by `uv run python -m friday.robin.linesdoc` (a test keeps this file in sync). **No audio has been
generated.** The real dial adapter (`friday/robin/telephony.py`) REFUSES to ring while `LINE_STATUS` is not `APPROVED`; a reviewed commit
flips it after the founder has heard the audio (hear-before-change, CLAUDE.md rule 3). `{brand}` is filled from the one brand setting
(`FRIDAY_BRAND_NAME`; the Robin pilot sets `Robin`); the name is never typed into a line. Other slots: `{parent}` (how the family calls the parent,
e.g. Papa), `{child}` (the admin's name), `{medicine}`, `{amount}`, `{why}`, `{time}`.

Parent-facing spoken lines exist in English (`en`), Roman Hinglish (`hinglish`) and Devanagari Hindi (`hi`). Chat lines to the child (admin)
exist in `en` and `hinglish`. Female forms are used in Hindi (the voice is female); the founder to confirm the persona.

Items for the founder to look at first: `intro.*` and `notify.*` (the AI disclosure and the notification of the parent), `nudge.*` (wording on a
possible scam call; never says a call IS a scam), `sos.*`, `screen.*` and `listen.*` (stubs, switches off), `fest.greeting` and the festival names.
"""


def render() -> str:
    out = [HEAD, f"Total lines: **{len(lines.all_lines())}** ({sum(1 for x in lines.all_lines() if x.kind == 'spoken')} spoken, {sum(1 for x in lines.all_lines() if x.kind == 'chat')} chat). Status of each: PENDING_FOUNDER_APPROVAL.\n"]
    for kind, table in (("Spoken to the parent, the child or the second contact (on a call, or as a voice note)", lines.SPOKEN), ("Chat lines to the child (admin)", lines.CHAT)):
        out.append(f"\n## {kind}\n")
        out.append("| Id | Language | Text | Status |\n|---|---|---|---|")
        for key, langs in table.items():
            for lang, text in langs.items():
                out.append(f"| robin.{key}.{lang} | {lang} | {text.replace('|', '/')} | PENDING |")
    out.append("\n## Festival names used by `fest.greeting` (data file `friday/robin/data/festivals.json`; PENDING; a festival is sent only when its date is marked verified)\n")
    out.append("| Id | en | hinglish | hi | Date | Verified |\n|---|---|---|---|---|---|")
    for f in load_festivals():
        n = f["name"]
        out.append(f"| {f['id']} | {n['en']} | {n['hinglish']} | {n['hi']} | {f.get('date') or f.get('month_day')} | {'yes' if f.get('verified') else 'NO'} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    DOC.write_text(render(), encoding="utf-8")
    print(f"wrote {DOC} ({len(lines.all_lines())} lines)")
