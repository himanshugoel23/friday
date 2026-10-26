"""``friday speech``: try the Speech Understander and score it on the eval set.

    friday speech try "umm kal nahi parso haircut chahiye"      one utterance (uses the real model if keyed)
    friday speech eval                                           the no-model floor cases (offline, free)
    friday speech eval --live                                    ALL cases through the real model (costs a little)

Exit codes: 0 all cases pass, 1 a case failed, 2 cannot run (e.g. --live without a key).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

CASES = Path(__file__).parent / "data" / "eval_cases.json"


def register(sub: Any) -> None:
    sp = sub.add_parser("speech", help="Speech Understander: try an utterance, score the eval set")
    ssub = sp.add_subparsers(dest="speech_cmd")
    t = ssub.add_parser("try", help="clean one utterance")
    t.add_argument("text")
    t.add_argument("--channel", default="voice_note", choices=["voice_note", "call", "text"])
    t.add_argument("--place", action="append", default=[], help="a saved place/shop (memory)")
    t.add_argument("--person", action="append", default=[], help="a saved person (memory)")
    e = ssub.add_parser("eval", help="score the eval set")
    e.add_argument("--live", action="store_true", help="use the real model (needs a key)")
    e.add_argument("--json", action="store_true")


def _memory(people: list[str], places: list[str]) -> Any:
    from friday.speech.memory import MemoryView

    mv = MemoryView(people=list(people), places=list(places))
    mv.vocab = {w.lower() for name in [*people, *places] for w in name.split()}
    return mv


def _understander(live: bool) -> Any:
    from friday.core.config import Settings
    from friday.speech import SpeechUnderstander

    settings = Settings()
    llm = None
    if live:
        if not settings.llm_key_configured() or settings.resolve_llm() == "fake":
            return None
        from friday.core.container import Container

        llm = Container(settings).get("llm")
    return SpeechUnderstander(llm, settings)


def run_command(args: argparse.Namespace) -> int:
    cmd = getattr(args, "speech_cmd", None)
    if cmd == "try":
        und = _understander(live=True) or _understander(live=False)
        res = asyncio.run(
            und.understand(
                args.text, channel=args.channel, memory=_memory(args.person, args.place)
            )
        )
        print(json.dumps({**res.model_dump(), "text": res.text}, indent=2, ensure_ascii=False))
        return 0
    if cmd == "eval":
        return _eval(live=args.live, as_json=args.json)
    print(__doc__)
    return 0


def _eval(*, live: bool, as_json: bool) -> int:
    from friday.speech import ground

    und = _understander(live)
    if und is None:
        print("--live needs an LLM key in the environment (none found). Not running.")
        return 2
    cases = json.loads(CASES.read_text())["cases"]
    if not live:
        cases = [c for c in cases if c.get("floor")]
    rows, failed = [], 0
    for c in cases:
        mem = c.get("memory", {})
        mv = _memory(mem.get("people", []), mem.get("places", []))
        res = asyncio.run(und.understand(c["text"], memory=mv))
        out = f" {res.text.lower()} "
        why = []
        why += [f"missing:{w}" for w in c.get("must_contain", []) if w.lower() not in out]
        why += [f"present:{w}" for w in c.get("must_not_contain", []) if w.lower() in out]
        why += ground.violations(c["text"], res.text, mv.vocab)
        failed += bool(why)
        rows.append({"id": c["id"], "ok": not why, "why": why, "source": res.source,
                     "text": res.text, "ms": round(res.latency_ms)})
    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        for r in rows:
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"{mark} {r['id']:22s} [{r['source']:5s} {r['ms']:5d}ms] {r['text']}"
                  + (f"   <- {', '.join(r['why'])}" if r["why"] else ""))
        print(f"\n{len(rows) - failed}/{len(rows)} passed ({'live model' if live else 'floor only'})")
    return 1 if failed else 0
