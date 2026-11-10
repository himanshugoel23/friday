# ruff: noqa: E501
"""``uv run python -m tests.bench.robin [--verbose] [--gate] [--write-baseline]`` (lead only for --write-baseline)."""

from __future__ import annotations

import argparse
import json
import sys

from tests.bench.robin import runner as R


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tests.bench.robin")
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--gate", action="store_true", help="exit 1 when the committed baseline is not met"
    )
    p.add_argument(
        "--write-baseline",
        action="store_true",
        help="LEAD ONLY: overwrite baseline.json with the current numbers",
    )
    a = p.parse_args(argv)
    outcomes = R.evaluate_all()
    m = R.metrics(outcomes)
    print(R.render(outcomes, m, verbose=a.verbose))
    if a.write_baseline:
        R.BASELINE.write_text(
            json.dumps(R.baseline_view(m), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"baseline written: {R.BASELINE}")
    if a.gate:
        bad = R.check_gate(m, R.load_baseline())
        for b in bad:
            print("GATE FAIL:", b)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
