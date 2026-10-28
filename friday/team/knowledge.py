# ruff: noqa: E501
"""Versioned site knowledge: DATA, not code. One JSON document per site and version.

* Seeds ship in ``friday/team/knowledge/<site>.v1.json``; runtime versions live under
  ``<root>/<site>/v<N>.json`` with a ``CURRENT`` pointer, a ``changelog.jsonl`` and a ``review/`` queue.
* A change is a PROPOSAL (new document, version = current + 1). ``validate`` checks schema and safety;
  ``classify`` says whether it may be auto-applied (only low-risk paths) or must go to founder review.
* Safety rules, domains and the schema itself can NEVER be changed by a proposal. Nothing here touches code
  or prompts. Every version is kept; ``rollback`` moves the pointer back (and logs it).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from friday.core.logging import get_logger

log = get_logger(__name__)
SEED_DIR = Path(__file__).parent / "knowledge"
SCHEMA = 1
MAX_BYTES = 64_000
REQUIRED: dict[str, type] = {
    "schema": int, "site": str, "version": int, "updated": str, "status": str, "domains": list, "safety": dict,
    "search_flow": list, "url_patterns": dict, "locations": dict, "login_checkout": dict, "quirks": list,
    "anti_bot": dict, "search_query_templates": list, "probes": list, "observed": dict,
}
IGNORED_PATHS = ("version", "updated", "status", "status_note")  # bookkeeping, never a reviewable change
# Paths a proposal may change WITHOUT review (still validated, and new URLs must be verified by the caller).
AUTO_PREFIXES = ("url_patterns.", "observed.", "pattern_confidence.")
AUTO_REGEX = (re.compile(r"^probes\.\d+\.url$"),)
STATUSES = ("unverified", "verified", "stale")


@dataclass
class Change:
    path: str
    old: Any
    new: Any

    def line(self) -> str:
        def short(v: Any, n: int = 160) -> str:
            s = json.dumps(v, ensure_ascii=False)
            return s if len(s) <= n else s[: n - 1] + "…"
        if isinstance(self.old, list) and isinstance(self.new, list):
            added = [x for x in self.new if x not in self.old]
            removed = [x for x in self.old if x not in self.new]
            return f"{self.path}: +{short(added)} -{short(removed)}"
        return f"{self.path}: {short(self.old)} -> {short(self.new)}"


@dataclass
class Proposal:
    site: str
    base_version: int
    doc: dict[str, Any]
    changes: list[Change]
    reason: str
    problems: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)  # paths that block auto-apply

    @property
    def valid(self) -> bool:
        return not self.problems

    @property
    def auto_ok(self) -> bool:
        return self.valid and not self.needs_review and bool(self.changes)

    def diff_text(self) -> str:
        return "\n".join(c.line() for c in self.changes) or "(no content change)"


def flatten(doc: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(doc, dict):
        for k, v in doc.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(doc, list) and any(isinstance(x, (dict, list)) for x in doc):
        for i, v in enumerate(doc):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = doc
    return out


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    a, b = flatten(old), flatten(new)
    return [Change(p, a.get(p), b.get(p)) for p in sorted(set(a) | set(b)) if a.get(p) != b.get(p)]


def _host_ok(url: str, domains: list[str]) -> bool:
    try:
        u = urlsplit(url.replace("{", "x").replace("}", "x"))
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "") in domains


def validate(old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
    """Schema, sanity and safety checks. Empty list = acceptable."""
    problems: list[str] = []
    if len(json.dumps(new)) > MAX_BYTES:
        problems.append("document too large")
    for key, typ in REQUIRED.items():
        if key not in new:
            problems.append(f"missing key: {key}")
        elif not isinstance(new[key], typ):
            problems.append(f"wrong type: {key}")
    if problems:
        return problems
    if new["schema"] != SCHEMA:
        problems.append("schema version cannot change")
    if new["status"] not in STATUSES:
        problems.append("unknown status")
    domains = [str(d) for d in new["domains"]]
    if not domains:
        problems.append("no domains")
    for name, url in new["url_patterns"].items():
        if not isinstance(url, str) or not _host_ok(url, domains):
            problems.append(f"url pattern {name} must be https on a known domain")
    for i, p in enumerate(new["probes"]):
        if not isinstance(p, dict) or not _host_ok(str(p.get("url", "")), domains) or not p.get("expect_markers"):
            problems.append(f"probe {i} invalid")
    if not new["probes"]:
        problems.append("no probes")
    if old is not None:
        if new["site"] != old["site"]:
            problems.append("site cannot change")
        if new["version"] != old["version"] + 1:
            problems.append("version must be previous + 1")
        for locked in ("safety", "domains", "schema"):
            if new[locked] != old[locked]:
                problems.append(f"{locked} cannot be changed by a proposal")
        if new["anti_bot"].get("our_response") != old["anti_bot"].get("our_response"):
            problems.append("anti_bot.our_response is a safety rule and cannot change")
        if new["login_checkout"].get("stop_rule") != old["login_checkout"].get("stop_rule"):
            problems.append("login_checkout.stop_rule is a safety rule and cannot change")
    return problems


def classify(changes: list[Change]) -> list[str]:
    """Paths that need a human (everything outside the low-risk prefixes)."""
    blocking = []
    for c in changes:
        if c.path in IGNORED_PATHS or c.path.startswith(AUTO_PREFIXES) or any(r.match(c.path) for r in AUTO_REGEX):
            continue
        blocking.append(c.path)
    return blocking


class KnowledgeStore:
    def __init__(self, root: str | Path, *, seed_dir: Path = SEED_DIR, clock: Any = time.time) -> None:
        self.root, self.seed_dir, self._clock = Path(root), seed_dir, clock

    # ------------------------------------------------------------------ read
    def sites(self) -> list[str]:
        return sorted(p.name.split(".v")[0] for p in self.seed_dir.glob("*.v1.json"))

    def _seed(self, site: str) -> dict[str, Any]:
        return json.loads((self.seed_dir / f"{site}.v1.json").read_text(encoding="utf-8"))

    def _dir(self, site: str) -> Path:
        return self.root / site

    def current_version(self, site: str) -> int:
        try:
            return int((self._dir(site) / "CURRENT").read_text().strip())
        except (OSError, ValueError):
            return 1

    def get(self, site: str, version: int | None = None) -> dict[str, Any]:
        v = version or self.current_version(site)
        f = self._dir(site) / f"v{v}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        if v == 1:
            return self._seed(site)
        raise KeyError(f"{site} v{v}")

    def versions(self, site: str) -> list[int]:
        found = {1}
        found |= {int(p.stem[1:]) for p in self._dir(site).glob("v*.json") if p.stem[1:].isdigit()}
        return sorted(found)

    def changelog(self, site: str) -> list[dict[str, Any]]:
        f = self._dir(site) / "changelog.jsonl"
        if not f.exists():
            return []
        return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]

    # ------------------------------------------------------------------ write
    def _log(self, site: str, entry: dict[str, Any]) -> None:
        d = self._dir(site)
        d.mkdir(parents=True, exist_ok=True)
        entry = {"ts": int(self._clock()), **entry}
        with (d / "changelog.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.info("team knowledge %s: %s", site, entry.get("event"))

    def _write(self, site: str, doc: dict[str, Any], *, make_current: bool = True) -> None:
        d = self._dir(site)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"v{doc['version']}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        if make_current:
            (d / "CURRENT").write_text(str(doc["version"]))

    def make_proposal(self, site: str, mutate: dict[str, Any], reason: str) -> Proposal:
        """Build a proposal from the CURRENT document with ``mutate`` (a nested dict of replacements) applied."""
        base = self.get(site)
        doc = json.loads(json.dumps(base))
        _deep_update(doc, mutate)
        doc["version"] = base["version"] + 1
        doc["updated"] = time.strftime("%Y-%m-%d", time.gmtime(self._clock()))
        return self.assess(site, doc, reason)

    def assess(self, site: str, doc: dict[str, Any], reason: str) -> Proposal:
        base = self.get(site)
        changes = diff(base, doc)
        p = Proposal(site, base["version"], doc, changes, reason, validate(base, doc))
        p.needs_review = classify(changes)
        return p

    def apply(self, p: Proposal, *, how: str) -> int:
        if not p.valid:
            raise ValueError("invalid proposal: " + "; ".join(p.problems))
        if p.base_version != self.current_version(p.site):
            raise ValueError("stale proposal: the current version moved on")
        self._write(p.site, p.doc)
        self._log(p.site, {"event": "applied", "how": how, "version": p.doc["version"], "reason": p.reason,
                           "changes": [c.line() for c in p.changes][:30]})
        return int(p.doc["version"])

    def queue(self, p: Proposal, *, evidence: dict[str, Any] | None = None) -> str:
        d = self.root / "review"
        d.mkdir(parents=True, exist_ok=True)
        rid = f"{p.site}-v{p.doc['version']}-{int(self._clock())}"
        (d / f"{rid}.json").write_text(json.dumps({
            "id": rid, "site": p.site, "base_version": p.base_version, "reason": p.reason, "problems": p.problems,
            "needs_review": p.needs_review, "diff": [c.line() for c in p.changes], "evidence": evidence or {},
            "doc": p.doc}, indent=2, ensure_ascii=False), encoding="utf-8")
        self._log(p.site, {"event": "queued_for_review", "id": rid, "reason": p.reason,
                           "paths": p.needs_review or ["(invalid)"]})
        return rid

    def review_queue(self, site: str | None = None) -> list[dict[str, Any]]:
        d = self.root / "review"
        items = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))] if d.exists() else []
        return [i for i in items if site in (None, i["site"])]

    def approve(self, review_id: str) -> int:
        """Founder approval of a queued proposal (still validated; refused if it became stale)."""
        f = self.root / "review" / f"{review_id}.json"
        item = json.loads(f.read_text(encoding="utf-8"))
        p = self.assess(item["site"], item["doc"], item["reason"])
        if p.base_version != item["base_version"]:
            raise ValueError("stale proposal")
        v = self.apply(p, how="founder_review")
        f.unlink()
        return v

    def reject(self, review_id: str) -> None:
        f = self.root / "review" / f"{review_id}.json"
        item = json.loads(f.read_text(encoding="utf-8"))
        self._log(item["site"], {"event": "rejected", "id": review_id})
        f.unlink()

    def rollback(self, site: str, to_version: int, reason: str = "") -> int:
        if to_version not in self.versions(site):
            raise KeyError(f"{site} v{to_version}")
        (self._dir(site) / "CURRENT").parent.mkdir(parents=True, exist_ok=True)
        (self._dir(site) / "CURRENT").write_text(str(to_version))
        self._log(site, {"event": "rollback", "to": to_version, "reason": reason})
        return to_version

    def mark_status(self, site: str, status: str, note: str = "") -> None:
        """Record 'unverified' / 'verified' in the changelog only; the document is never rewritten for it."""
        self._log(site, {"event": "status", "status": status, "note": note[:200]})


def _deep_update(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v
