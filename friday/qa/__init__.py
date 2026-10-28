# ruff: noqa: E501
"""Manual QA of every built feature with REAL calls to the founder's OWN allow-listed phone only.

Docs: docs/QA_MANUAL.md. Pieces:

  config.py      QA switches (FRIDAY_QA_*), default OFF
  override.py    the QA-only override (pending lines, caps, calling window), scoped to ONE number
  safety.py      QaGuard: start-up checks, allow-list, kill switch, daily call and spend caps
  store.py       var/qa/*.jsonl: notes and verdicts, runs, ledger, pending lines heard
  scenarios.py   the list of scenarios and what is real or simulated in each
  runner.py      approval phrase, ring-now countdown, one run at a time, live status
  live.py        the real call backends (reuse `friday livecall`, `consumer call-test`, the urgent dial)
  app.py         the token-protected page on port 8767 (/qa/<token>/)
  cli.py         `friday qa list | serve | run | report | exec`
"""
