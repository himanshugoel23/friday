"""Proactive engine - triggers, scheduler and guardrails.

Owner: Backend Engineer.

  engine.py  build_proactive_engine(c): asyncio tick loop; triggers (task reminders,
             follow-ups, date facts, patterns, recurring due, morning briefing,
             wellbeing alerts, promised-date care follow-ups); guardrails (daily cap 3,
             quiet hours 22-08 IST, autonomy levels, ignore-learning, every nudge offers
             an action, templates outside 24h); brain.judge_nudge for copy.
"""
