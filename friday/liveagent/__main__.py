"""python -m friday.liveagent lines [--lang hinglish|hi|en]   list every PENDING line with its id
python -m friday.liveagent simulate                          run all personas (pass/fail table)
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "lines"
    if cmd == "simulate":
        from friday.liveagent.simulation.runner import main as sim

        return sim()
    from friday.liveagent import lines as L

    lang = argv[argv.index("--lang") + 1] if "--lang" in argv else None
    for pl in L.all_lines():
        if lang and pl.language != lang:
            continue
        print(f"{pl.id}\t{pl.status}\t{pl.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
