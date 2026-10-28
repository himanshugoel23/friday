# ruff: noqa: E501
"""CALL agent: a thin adapter to the EXISTING vendor-call flow. One job: mark the plan as
containing a call and let the request continue into quotes / PM / brain unchanged.

It places no call itself. Every real call still goes through the existing consent, allow-list,
call-window, redirect and kill-switch guards (CallGate); nothing here can bypass them.
"""

from __future__ import annotations

from pydantic import BaseModel

from friday.planner.types import Approach, ApproachDecision


class CallPlanInput(BaseModel):
    decision: ApproachDecision


class CallPlanOutput(BaseModel):
    call_in_plan: bool = True
    continue_existing_flow: bool = True  # the gateway returns "not handled" so the old chain runs


class CallAgent:
    def run(self, inp: CallPlanInput) -> CallPlanOutput:
        if inp.decision.approach != Approach.CALL_VENDORS:
            raise ValueError("CallAgent only plans CALL_VENDORS")
        return CallPlanOutput()
