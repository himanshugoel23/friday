"""Task engine - the state machine that turns requests into calls and results.

Owner: Backend Engineer.

  engine.py  build_task_engine(c): created -> planning -> (discovering) -> scheduled ->
             calling -> awaiting_user -> completed/failed; parent/child fan-out
             (sequential / parallel / first-match), aggregation & comparison, approval
             -> confirm call, retries with business-hours-aware queue, recurring
             schedules, care follow-ups, hotel reconfirmation. Supplies AskUser /
             NotifyUser callbacks to the voice CallSessionRunner.
"""
