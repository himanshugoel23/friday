# ruff: noqa: E501
"""Plumbing: the ``urgent_escalation`` component (None unless FRIDAY_URGENT_ESCALATION_ENABLED).

    receptionist._push --open/confirm_alert--> UrgentEscalation     (alert + Acknowledge button)
    WhatsApp button urg:<id>:ack / text "urgent call on|off|N min" --Receptionist.handle--> UrgentEscalation
    inbound call from the user's own number --CallbackService--> UrgentEscalation.note_inbound_call
    Runtime --> UrgentEscalation.loop()  (the scheduler; started next to the receptionist loop)

The dial is ``TelephonyOwnNumberCaller`` (refuses while the spoken line is PENDING approval) behind
``OwnNumberGate`` (the real CallGate). Built lazily; a failure here never stops the receptionist.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import ReplyButton
from friday.urgent.models import Policy
from friday.urgent.service import UrgentEscalation
from friday.urgent.store import SqlEscalationStore

log = get_logger(__name__)


def build_urgent(c: Any) -> UrgentEscalation | None:
    s = c.settings
    if not s.urgent_escalation_enabled:
        return None
    from friday.calls.dnc import DncRegistry
    from friday.calls.gate import CallGate
    from friday.calls.numbers import NumberHasher
    from friday.calls.settings import CallsSettings
    from friday.pause import is_paused
    from friday.receptionist.store import SqlReceptionistStore
    from friday.urgent.gate import OwnNumberGate
    from friday.urgent.telephony import TelephonyOwnNumberCaller

    repos = c.get("repos")
    store = SqlEscalationStore(repos.db, c.clock)
    rcp_store = SqlReceptionistStore(repos.db, c.clock)

    async def send(user_id: str, text: str, buttons: Sequence[ReplyButton]) -> None:
        await c.get("notifier").notify_user(user_id, text, buttons=list(buttons))

    def paused() -> bool:
        return is_paused(s)

    hasher = NumberHasher()
    gate = CallGate(
        store=repos.consumer_calls, dnc=DncRegistry(repos.call_dnc, hasher, c.clock), hasher=hasher,
        settings=CallsSettings(), core_settings=s,
    )  # fmt: skip
    caller = TelephonyOwnNumberCaller(lambda: c.telephony, s, paused=paused)
    return UrgentEscalation(
        store, send, caller, c.clock, users=repos.users, gate=OwnNumberGate(gate, hasher, s),
        policy=Policy.from_settings(s), enabled=lambda: bool(s.urgent_escalation_enabled), paused=paused,
        rcp_config=rcp_store.get_config, tick_s=float(s.urgent_escalation_tick_s),
    )  # fmt: skip
