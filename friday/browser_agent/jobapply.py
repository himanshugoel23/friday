# ruff: noqa: E501
"""Job-application playbook on top of the browser agent. Behind FRIDAY_JOB_APPLY_ENABLED (default OFF).

* Never applies without the user's STANDING OPT-IN (a stored choice: ``preview`` or ``auto``).
* PREVIEW (default): the run stops at the final submit and shows what will be sent; the user's YES for that application sends it.
* AUTO (explicit opt-in, daily cap): the standing opt-in counts as the yes for the SUBMIT click only. Legal statements (never paid,
  background-check consent, declarations) are still asked verbatim, every time, and an open legal box stops the auto path.
* A daily cap counts applications per user per IST day; the ledger feeds the evening summary (what, where, proof, when).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from friday.browser_agent import rules
from friday.browser_agent.agent import BrowserAgent
from friday.browser_agent.ports import FactSource
from friday.browser_agent.types import AskField, RunOutcome, RunSpec, Status

DATA = Path(__file__).parent / "data" / "job_apply.v1.json"
MODE_KEY = "job_apply_mode"
IST = timedelta(hours=5, minutes=30)
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
CMD_RE = re.compile(r"^\s*(?:job\s*apply|apply\s+to\s+jobs)\s+(auto\s+on|on|off)\s*$", re.I)


def playbook() -> dict[str, Any]:
    return json.loads(DATA.read_text())  # type: ignore[no-any-return]


def required_fields(pb: dict[str, Any] | None = None) -> list[AskField]:
    pb = pb or playbook()
    return [AskField(key=f["key"], label=f["label"], default=f.get("default"), options=f.get("options")) for f in pb["profile_fields"] if f.get("required")]


def build_goal(url: str, pb: dict[str, Any] | None = None) -> str:
    pb = pb or playbook()
    return str(pb["goal_template"]).format(url=url, keys=", ".join(f["key"] for f in pb["profile_fields"]))


def ist_day(now: datetime) -> str:
    return (now.astimezone(UTC) + IST).strftime("%Y-%m-%d")


class JobLedger:
    """One JSON line per application: when, where (host + path), what (title as the agent reported it), proof id. No answers, no values."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, user_id: str, *, now: datetime, host: str, where: str, what: str, proof_id: str, status: str) -> None:
        row = {"user": user_id, "day": ist_day(now), "when": now.isoformat(timespec="seconds"), "host": host, "where": where, "what": what[:160], "proof": proof_id, "status": status}
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def rows(self, user_id: str, day: str | None = None) -> list[dict[str, Any]]:
        out = []
        if not self.path.exists():
            return out
        for ln in self.path.read_text().splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("user") == user_id and (day is None or r.get("day") == day):
                out.append(r)
        return out

    def applied_today(self, user_id: str, now: datetime) -> int:
        return sum(1 for r in self.rows(user_id, ist_day(now)) if r["status"] == "applied")

    def users_for_day(self, day: str) -> list[str]:
        if not self.path.exists():
            return []
        seen: list[str] = []
        for ln in self.path.read_text().splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("day") == day and r["user"] not in seen:
                seen.append(r["user"])
        return seen

    def delete_user(self, user_id: str) -> int:
        if not self.path.exists():
            return 0
        keep, gone = [], 0
        for ln in self.path.read_text().splitlines():
            try:
                if json.loads(ln).get("user") == user_id:
                    gone += 1
                    continue
            except ValueError:
                pass
            keep.append(ln)
        self.path.write_text("\n".join(keep) + ("\n" if keep else ""))
        return gone


LINES = {
    "need_optin": {
        "en": "Job applications are off for you. Write 'job apply on' and I will always show you each application and wait for your YES; write 'job apply auto on' if you want me to send them myself (up to {cap} a day, legal statements are still asked).",
        "hinglish": "Job applications abhi band hain. 'job apply on' likhiye: main har application dikhaungi aur aapke YES ka intezaar karungi; 'job apply auto on' likhiye toh main khud bhejungi (din mein {cap} tak, legal statements phir bhi poochhungi).",
    },
    "optin_on": {
        "en": "Okay. Job applications are on in preview mode: I show each one and wait for your YES.",
        "hinglish": "Theek hai. Job applications preview mode mein on hain: har ek dikhaungi aur aapke YES ka intezaar karungi.",
    },
    "optin_auto": {
        "en": "Okay. Auto-apply is on, up to {cap} applications a day. I still ask you the legal statements, and I send you an evening summary with proof. Write 'job apply off' to stop.",
        "hinglish": "Theek hai. Auto-apply on hai, din mein {cap} tak. Legal statements phir bhi poochhungi, aur shaam ko proof ke saath summary bhejungi. Rokne ke liye 'job apply off' likhiye.",
    },
    "optin_off": {"en": "Okay. Job applications are off.", "hinglish": "Theek hai. Job applications band."},
    "cap_reached": {
        "en": "I have already applied to {n} jobs today, which is your daily limit. I will not apply to more today.",
        "hinglish": "Aaj {n} jobs par apply kar chuki hoon, yeh aapki daily limit hai. Aaj aur nahi karungi.",
    },
    "need_resume": {
        "en": "I need your resume first. Send it here as a PDF or DOCX and I will keep it for applications (write 'forget my resume' to remove it).",
        "hinglish": "Pehle aapka resume chahiye. Yahan PDF ya DOCX bhejiye, main applications ke liye rakh lungi ('forget my resume' likhne par hata dungi).",
    },
    "need_url": {
        "en": "Send me the link of the job you want me to apply to.",
        "hinglish": "Jis job par apply karna hai uska link bhejiye.",
    },
    "summary_head": {"en": "Your applications today:", "hinglish": "Aaj ki aapki applications:"},
    "summary_row": {"en": "{n}. {what} ({where}) at {when}. Proof saved.", "hinglish": "{n}. {what} ({where}) {when} baje. Proof save hai."},
    "summary_none": {"en": "No applications were sent today.", "hinglish": "Aaj koi application nahi bheji."},
}


def line(key: str, lang: str, **kw: object) -> str:
    row = LINES[key]
    return (row.get(lang) or row["hinglish"]).format(**kw)


@dataclass
class ApplyDecision:
    ok: bool
    message: str = ""
    mode: str = ""


class JobApplyService:
    def __init__(self, agent: BrowserAgent, facts: FactSource, ledger: JobLedger, files: Any, *, daily_cap: int = 5, now: Any = None) -> None:
        self.agent, self.facts, self.ledger, self.files, self.cap = agent, facts, ledger, files, daily_cap
        self._now = now or (lambda: datetime.now(UTC))
        self.pb = playbook()

    # ------------------------------------------------------------------ opt-in (standing, per user, erasable)
    async def mode(self, user_id: str) -> str:
        return (await self.facts.load(user_id)).get(MODE_KEY, "")

    async def handle_command(self, user_id: str, text: str, lang: str) -> str | None:
        m = CMD_RE.match(text or "")
        if not m:
            return None
        what = " ".join(m.group(1).lower().split())
        mode = {"on": "preview", "auto on": "auto", "off": "off"}[what]
        await self.facts.remember(user_id, MODE_KEY, mode)
        return line({"preview": "optin_on", "auto": "optin_auto", "off": "optin_off"}[mode], lang, cap=self.cap)

    # ------------------------------------------------------------------ start one application
    async def apply(self, user_id: str, text: str, lang: str) -> RunOutcome | ApplyDecision:
        mode = await self.mode(user_id)
        if mode not in ("preview", "auto"):
            return ApplyDecision(False, line("need_optin", lang, cap=self.cap))
        urls = URL_RE.findall(text or "")
        if not urls:
            return ApplyDecision(False, line("need_url", lang))
        url = urls[0].rstrip(".,")
        host = rules.host_of(url)
        if not host or rules.domain_denied(host):
            return ApplyDecision(False, line("need_url", lang))
        n = self.ledger.applied_today(user_id, self._now())
        if n >= self.cap:
            return ApplyDecision(False, line("cap_reached", lang, n=n))
        if self.files.resolve(user_id, self.pb["resume"]["file_ref"]) is None:
            return ApplyDecision(False, line("need_resume", lang))
        facts = await self.facts.load(user_id)
        missing = [f for f in required_fields(self.pb) if f.key not in facts]
        spec = RunSpec(goal=build_goal(url, self.pb), allowed_domains=[host], start_url=url, playbook="job_apply", lang=lang,
                       standing_ok=["job_application_submit"] if mode == "auto" else [], max_steps=45)
        out = await self.agent.start(user_id, spec, preask=missing or None)
        return out

    # ------------------------------------------------------------------ ledger + evening summary
    def record_outcome(self, user_id: str, out: RunOutcome, state_result: str = "") -> None:
        """Called by the gateway when a job run ends. Only a run that produced an irreversible-action proof counts as applied."""
        applied = out.status == Status.DONE and any("clicked" in p.what for p in out.proofs)
        host = rules.host_of("https://" + out.proofs[-1].where) if out.proofs else ""
        self.ledger.record(user_id, now=self._now(), host=host, where=out.proofs[-1].where if out.proofs else "", what=state_result or "job application",
                           proof_id=out.proofs[-1].id if out.proofs else "", status="applied" if applied else out.status.value)

    def evening_summary(self, user_id: str, lang: str, day: str | None = None) -> str:
        rows = [r for r in self.ledger.rows(user_id, day or ist_day(self._now())) if r["status"] == "applied"]
        if not rows:
            return line("summary_none", lang)
        out = [line("summary_head", lang)]
        for i, r in enumerate(rows, 1):
            hhmm = (datetime.fromisoformat(r["when"]).astimezone(UTC) + IST).strftime("%H:%M")
            out.append(line("summary_row", lang, n=i, what=r["what"], where=r["where"], when=hhmm))
        return "\n".join(out)
