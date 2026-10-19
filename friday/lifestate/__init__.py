"""Life state (W4): one per-user picture of the user's day, read by every channel.

  models.py     LifeEvent, LifeCommitment, PersonRef, NowStatus, UserContext, Followup, TopicPref
  store.py      LifeStore protocol, in-memory store, export / erase helpers
  capture.py    Hinglish messages -> events / commitments (deterministic first, optional LLM hook)
  sync.py       read-only calendar import, booking events, clash check
  now.py        now_status, context_summary (no private text)
  followups.py  event-aware proactive scheduler, morning brief, replies, mute parsing
  memory.py     "what do you remember", "forget X", export, delete everything
  conversation.py  context provider the front door and the live call engine call
  copy.py       ALL user-facing text (PENDING_FOUNDER_APPROVAL)

Imports are kept light on purpose: the database repository imports ``models`` and ``dbmodel`` only.
"""
