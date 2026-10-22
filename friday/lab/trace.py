"""Turn tracing for the lab: what happened inside Friday for one message.

Nothing here changes behaviour. ``Tracer.install`` wraps methods on THIS world's own objects (the
pipeline, the consumer router, the brain, the call gate) and a few module-level functions (copy
modules, slot parsers) with timing/recording shims; ``Tracer.uninstall`` puts everything back. The
shims record into the turn that is current in a ContextVar, so two labs in one process do not mix.

A trace is plain JSON-able data:

    route        which handler answered, in plain words, plus ``path`` (every step that ran)
    intent       intent value, confidence, slots (understood by the brain or by a consumer parser)
    answered_by  "rules" | "language model (fake|real)" | "consumer handler" ...
    guards       gate / throttle / redaction decisions with reason codes
    stages       name, depth, ms (real time), what each returned
    llm_calls    purpose + ms for every model call
    copy_keys    wording used that is still PENDING founder approval
"""

from __future__ import annotations

import contextlib
import contextvars
import inspect
import time
from contextlib import asynccontextmanager
from typing import Any

_CURRENT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "lab_turn", default=None
)

# consumer-router handlers, in the order the router tries them, with plain names
HANDLER_NAMES = {
    "proactive": "proactive engine (clock tick)",
    "consumer._edit_turn": "call plan edit",
    "consumer._call_turn": "call request (friends and family calls)",
    "consumer._google": "Google connect",
    "consumer._memory": "memory controls (what do you remember / forget)",
    "consumer.savings": "savings (cards and bills)",
    "consumer.followup_reply": "reply to a follow-up",
    "consumer._my_day": "your day",
    "consumer._card_question": "which card to use",
    "consumer._capture_turn": "life capture (events and commitments)",
    "consumer._button": "consumer button",
    "quotes_flow": "vendor quotes flow",
    "pm_gateway": "project manager",
    "pipeline._button": "task button (q:/a:/n:)",
    "onboarding": "onboarding",
    "pending_action": "pending PIN / delete confirmation",
}
_CONSUMER_ORDER = (
    "consumer._edit_turn",
    "consumer._call_turn",
    "consumer._google",
    "consumer._memory",
    "consumer.savings",
    "consumer.followup_reply",
    "consumer._my_day",
    "consumer._card_question",
    "consumer._capture_turn",
    "consumer._button",
)

_COPY_SKIP_PREFIXES = ("fmt_", "_", "cli_")
_COPY_SKIP_NAMES = {
    "noun",
    "topic_label",
    "label",
    "merchant_label",
    "when_phrase",
    "date_phrase",
    "reason_clause",
    "spend_phrase",
    "outcome_buttons",
    "spoken",
}
_COPY_MODULES = (
    "friday.integration.copy",
    "friday.lifestate.copy",
    "friday.savings.copy",
    "friday.calls.copy",
    "friday.google.consent_copy",
)


def _short(v: Any, n: int = 80) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[: n - 1] + "…"
    if isinstance(v, dict):
        return {k: _short(x, n) for k, x in list(v.items())[:20]}
    if isinstance(v, (list, tuple)):
        return [_short(x, n) for x in list(v)[:10]]
    return v


def current_turn() -> dict[str, Any] | None:
    return _CURRENT.get()


def new_turn(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "stages": [],
        "guards": [],
        "llm_calls": [],
        "copy_keys": [],
        "slots": {},
        "interpretation": None,
        "_depth": 0,
        "_order": 0,
    }


def _record_stage(
    turn: dict[str, Any], name: str, started: float, order: int, depth: int, info: dict[str, Any]
) -> None:
    turn["stages"].append(
        {
            "name": name,
            "order": order,
            "depth": depth,
            "ms": round((time.perf_counter() - started) * 1000, 2),
            **info,
        }
    )


# ---------------------------------------------------------------------------- module-level patches
_GLOBAL_PATCHES: list[tuple[Any, str, Any]] = []  # (owner, attr, original)
_GLOBAL_REFS = 0


def _wrap_module_callable(owner: Any, attr: str, make: Any) -> None:
    orig = getattr(owner, attr)
    if getattr(orig, "_lab_wrapped", False):
        return
    wrapped = make(orig)
    wrapped._lab_wrapped = True  # type: ignore[attr-defined]
    setattr(owner, attr, wrapped)
    _GLOBAL_PATCHES.append((owner, attr, orig))


def _copy_wrapper(modname: str, attr: str, orig: Any) -> Any:
    def wrapper(*a: Any, **k: Any) -> Any:
        turn = _CURRENT.get()
        if turn is not None:
            key = f"{modname}:{a[0]}" if attr in ("line", "spoken") and a else f"{modname}.{attr}"
            if key not in turn["copy_keys"]:
                turn["copy_keys"].append(key)
        return orig(*a, **k)

    wrapper.__name__ = attr
    return wrapper


def install_global_probes() -> None:
    """Copy-module recorders and slot parsers. Reference counted; restored by the last uninstall."""
    global _GLOBAL_REFS
    _GLOBAL_REFS += 1
    if _GLOBAL_REFS > 1:
        return
    import importlib

    for modname in _COPY_MODULES:
        try:
            mod = importlib.import_module(modname)
        except ImportError:  # pragma: no cover
            continue
        if not getattr(mod, "PENDING_FOUNDER_APPROVAL", False):
            continue
        short = modname.removeprefix("friday.")
        for attr, fn in list(vars(mod).items()):
            if (
                not inspect.isfunction(fn)
                or fn.__module__ != modname
                or attr.startswith(_COPY_SKIP_PREFIXES)
                or attr in _COPY_SKIP_NAMES - {"spoken"}
            ):
                continue
            _wrap_module_callable(mod, attr, lambda o, m=short, a=attr: _copy_wrapper(m, a, o))
    from friday.integration import router as router_mod

    def purchase_probe(orig: Any) -> Any:
        def w(text: str) -> Any:
            res = orig(text)
            turn = _CURRENT.get()
            if turn is not None:
                with contextlib.suppress(Exception):  # a probe never breaks the product
                    turn["slots"]["purchase"] = {
                        "amount_rupees": res.amount_paise / 100 if res.amount_paise else None,
                        "category": res.category,
                        "merchant": res.merchant,
                        "ask": res.ask,
                    }
            return res

        return w

    def capture_probe(orig: Any) -> Any:
        async def w(*a: Any, **k: Any) -> Any:
            res = await orig(*a, **k)
            turn = _CURRENT.get()
            if turn is not None and res.status != "none":
                with contextlib.suppress(Exception):  # a probe never breaks the product
                    turn["slots"]["life_capture"] = {
                        "status": res.status,
                        "events": [
                            {
                                "kind": getattr(e.kind, "value", str(e.kind)),
                                "title": e.title,
                                "start": str(e.start),
                            }
                            for e in res.events
                        ],
                        "commitments": len(res.commitments),
                        "via_llm": res.via_llm,
                    }
            return res

        return w

    if hasattr(router_mod, "parse_purchase"):
        _wrap_module_callable(router_mod, "parse_purchase", purchase_probe)
    if hasattr(router_mod, "capture_message"):
        _wrap_module_callable(router_mod, "capture_message", capture_probe)


def uninstall_global_probes() -> None:
    global _GLOBAL_REFS
    _GLOBAL_REFS = max(0, _GLOBAL_REFS - 1)
    if _GLOBAL_REFS:
        return
    for owner, attr, orig in reversed(_GLOBAL_PATCHES):
        setattr(owner, attr, orig)
    _GLOBAL_PATCHES.clear()


# ---------------------------------------------------------------------------- instance wrappers
class Tracer:
    """Installs the shims on one lab world's objects."""

    def __init__(self) -> None:
        self._restore: list[tuple[Any, str, Any, bool]] = []
        self.installed = False

    # ---- one turn
    @asynccontextmanager
    async def turn(self, label: str):  # noqa: ANN201
        t = new_turn(label)
        token = _CURRENT.set(t)
        started = time.perf_counter()
        try:
            yield t
        finally:
            t["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
            _CURRENT.reset(token)
            finish_trace(t)

    # ---- wrapping
    def _wrap(self, obj: Any, attr: str, stage: str, describe: Any = None) -> None:
        orig = getattr(obj, attr, None)
        if orig is None or getattr(orig, "_lab_wrapped", False):
            return
        had_own = attr in getattr(obj, "__dict__", {})

        async def wrapper(*a: Any, **k: Any) -> Any:
            turn = _CURRENT.get()
            if turn is None:
                return await orig(*a, **k)
            turn["_order"] += 1
            order, depth = turn["_order"], turn["_depth"]
            turn["_depth"] += 1
            started = time.perf_counter()
            try:
                res = await orig(*a, **k)
            except Exception as e:
                turn["_depth"] -= 1
                _record_stage(turn, stage, started, order, depth, {"error": type(e).__name__})
                raise
            turn["_depth"] -= 1
            info: dict[str, Any] = {}
            if describe is not None:
                try:
                    info = describe(res, turn, a, k) or {}
                except Exception:  # noqa: BLE001 - a probe never breaks the product
                    info = {}
            _record_stage(turn, stage, started, order, depth, info)
            return res

        wrapper._lab_wrapped = True  # type: ignore[attr-defined]
        setattr(obj, attr, wrapper)
        self._restore.append((obj, attr, orig, had_own))

    def uninstall(self) -> None:
        if not self.installed:
            return
        for obj, attr, orig, had_own in reversed(self._restore):
            if had_own:
                setattr(obj, attr, orig)
            else:
                with contextlib.suppress(AttributeError):
                    delattr(obj, attr)
        self._restore.clear()
        uninstall_global_probes()
        self.installed = False

    def install(
        self,
        *,
        pipeline: Any,
        router: Any,
        brain: Any,
        llm_owner: Any,
        proactive: Any = None,
        task_engine: Any = None,
    ) -> None:
        if self.installed:
            return
        install_global_probes()
        self.installed = True
        p = pipeline
        self._wrap(p, "handle", "pipeline.handle")
        self._wrap(
            p, "_continue_pending", "pending_action", lambda r, t, a, k: {"consumed": bool(r)}
        )
        self._wrap(
            p,
            "_transcribe",
            "voice_note_to_text",
            lambda r, t, a, k: {"words": len((r or "").split())},
        )
        self._wrap(p, "_looks_sensitive", "guard.sensitive_check", _sensitive_guard)
        self._wrap(p.throttle, "allow", "guard.inbound_throttle", _throttle_guard)
        self._wrap(p.quotes, "handle", "quotes_flow", lambda r, t, a, k: {"consumed": bool(r)})
        self._wrap(p.pm_gateway, "handle", "pm_gateway", lambda r, t, a, k: {"consumed": bool(r)})
        self._wrap(p, "_button", "pipeline._button", lambda r, t, a, k: {"consumed": bool(r)})
        for meth in ("start", "handle", "waitlisted"):
            self._wrap(p.onboarding, meth, "onboarding", _onboarding_info)
        self._wrap(p, "execute", "execute", _execute_info)
        if brain is not None:
            self._wrap(brain, "interpret", "brain.interpret", _interpret_info)
        if llm_owner is not None:
            self._wrap_llm(llm_owner)
        if proactive is not None:
            self._wrap(
                proactive,
                "tick",
                "proactive_tick",
                lambda r, t, a, k: {"messages_created": len(r or [])},
            )
        if task_engine is not None:
            self._wrap(task_engine, "drain", "job_queue_drain", lambda r, t, a, k: {})
        if router is not None:
            self._wrap(
                router, "handle", "consumer_router", lambda r, t, a, k: {"consumed": bool(r)}
            )
            self._wrap(router, "periodic", "consumer_periodic", lambda r, t, a, k: {})
            for name in _CONSUMER_ORDER:
                attr = name.split(".", 1)[1]
                if attr.startswith("_"):
                    self._wrap(router, attr, name, lambda r, t, a, k: {"consumed": bool(r)})
            if router.savings is not None:
                self._wrap(
                    router.savings,
                    "handle",
                    "consumer.savings",
                    lambda r, t, a, k: {"consumed": r is not None},
                )
            if router.life is not None:
                self._wrap(
                    router.life.scheduler,
                    "handle_reply",
                    "consumer.followup_reply",
                    lambda r, t, a, k: {"consumed": bool(getattr(r, "handled", False))},
                )
            if router.calls is not None:
                self._wrap(router.calls.orchestrator.gate, "decide", "guard.call_gate", _gate_guard)
                self._wrap(
                    router.calls.intake.understander,
                    "understand",
                    "call_understanding",
                    _call_slots,
                )

    def _wrap_llm(self, llm: Any) -> None:
        orig = getattr(llm, "complete", None)
        if orig is None or getattr(orig, "_lab_wrapped", False):
            return
        had_own = "complete" in getattr(llm, "__dict__", {})

        async def complete(*a: Any, **k: Any) -> Any:
            turn = _CURRENT.get()
            started = time.perf_counter()
            try:
                return await orig(*a, **k)
            finally:
                if turn is not None:
                    turn["llm_calls"].append(
                        {
                            "purpose": k.get("purpose")
                            or (a[0] if a and isinstance(a[0], str) else None),
                            "provider": getattr(llm, "provider", "?"),
                            "ms": round((time.perf_counter() - started) * 1000, 2),
                        }
                    )

        complete._lab_wrapped = True  # type: ignore[attr-defined]
        setattr(llm, "complete", complete)  # noqa: B010
        self._restore.append((llm, "complete", orig, had_own))


# ---------------------------------------------------------------------------- describers
def _sensitive_guard(res: Any, turn: dict[str, Any], a: Any, k: Any) -> dict[str, Any]:
    turn["guards"].append(
        {
            "gate": "sensitive_content_check",
            "verdict": "redact" if res else "allow",
            "reasons": ["looks_like_secret_or_card"] if res else ["clean"],
        }
    )
    return {"redacted": bool(res)}


def _throttle_guard(res: Any, turn: dict[str, Any], a: Any, k: Any) -> dict[str, Any]:
    turn["guards"].append(
        {
            "gate": "inbound_throttle",
            "verdict": "allow" if res else "deny",
            "reasons": ["under_rate_limit"] if res else ["too_many_messages"],
        }
    )
    return {}


def _gate_guard(res: Any, turn: dict[str, Any], a: Any, k: Any) -> dict[str, Any]:
    turn["guards"].append(
        {
            "gate": "call_gate",
            "verdict": getattr(res.verdict, "value", str(res.verdict)),
            "reasons": list(res.reasons),
            "refusal_key": res.refusal_key,
            "defer_until": str(res.defer_until) if res.defer_until else None,
            "max_duration_s": res.max_duration_s,
        }
    )
    return {"verdict": getattr(res.verdict, "value", str(res.verdict))}


def _call_slots(res: Any, turn: dict[str, Any], a: Any, k: Any) -> dict[str, Any]:
    d = res.draft
    turn["slots"]["call_request"] = _short(
        {
            "callee_ref": d.callee_ref,
            "callee_kind": getattr(d.callee_kind, "value", None),
            "purpose": d.purpose,
            "purpose_kind": getattr(d.purpose_kind, "value", None),
            "details": d.details,
            "scheduled_for": str(d.scheduled_for) if d.scheduled_for else None,
            "language": d.language,
            "missing": list(res.missing),
            "refusal": res.refusal_key,
        }
    )
    return {"ready": res.ready}


def _onboarding_info(res: Any, turn: dict[str, Any], a: Any, k: Any) -> dict[str, Any]:
    user = a[0] if a else None
    step = getattr(getattr(user, "onboarding_step", None), "value", None)
    if step:
        turn.setdefault("onboarding_step", step)
    return {"consumed": True, "step_before": step}


def _execute_info(res: Any, turn: dict[str, Any], a: Any, k: Any) -> dict[str, Any]:
    interp = a[2] if len(a) > 2 else k.get("interp")
    return {"intent": getattr(getattr(interp, "intent", None), "value", None)}


def _interpret_info(res: Any, turn: dict[str, Any], a: Any, k: Any) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    if res.task_spec is not None:
        slots = _short(
            res.task_spec.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        )
    turn["interpretation"] = {
        "intent": res.intent.value,
        "confidence": res.confidence,
        "requires_pin": res.requires_pin,
        "has_reply": bool(res.reply),
        "buttons": [b.title for b in res.buttons],
        "task_slots": slots,
        "profile_update_fields": sorted(res.profile_updates),
        "choice_index": res.choice_index,
    }
    return {"intent": res.intent.value, "confidence": res.confidence}


def finish_trace(t: dict[str, Any]) -> None:
    """Derive route, answered_by and the latency summary from the recorded stages."""
    stages = sorted(t["stages"], key=lambda s: s["order"])
    t["stages"] = stages
    names_consumed = [s["name"] for s in stages if s.get("consumed") and s["name"] in HANDLER_NAMES]
    path = [
        {
            "step": s["name"],
            "result": ("handled" if s.get("consumed") else "passed")
            if "consumed" in s
            else s.get("intent") or s.get("verdict") or "ran",
        }
        for s in stages
        if s["name"] not in ("pipeline.handle",)
    ]
    t["path"] = path
    handler = None
    for n in _CONSUMER_ORDER:
        if n in names_consumed:
            handler = n
            break
    if handler is None:
        for n in ("quotes_flow", "pm_gateway", "pending_action", "pipeline._button", "onboarding"):
            if n in names_consumed:
                handler = n
                break
    interp = t.get("interpretation")
    llm_interpret = [c for c in t["llm_calls"] if c.get("purpose") == "interpret"]
    if handler is not None:
        t["route"] = {"handler": handler, "label": HANDLER_NAMES[handler]}
        t["answered_by"] = (
            "rules (no model call)"
            if not t["llm_calls"]
            else f"model-assisted ({t['llm_calls'][0]['provider']})"
        )
    elif interp is not None:
        t["route"] = {"handler": "brain", "label": f"brain, intent {interp['intent']}"}
        if llm_interpret:
            t["answered_by"] = f"language model ({llm_interpret[0]['provider']})"
        else:
            t["answered_by"] = "rules (deterministic, no model call)"
    elif any(s["name"] == "proactive_tick" for s in stages):
        t["route"] = {"handler": "proactive", "label": "proactive engine (clock tick)"}
        t["answered_by"] = "proactive rules (no model call)"
    else:
        t["route"] = {"handler": None, "label": "nothing handled it"}
        t["answered_by"] = "-"
    t["classifier"] = "not used on the chat path (voice calls only)"
    stage_ms: dict[str, float] = {}
    for s in stages:
        if s["depth"] <= 2:
            stage_ms[s["name"]] = round(stage_ms.get(s["name"], 0.0) + s["ms"], 2)
    t["latency_ms"] = {
        "total": t.get("total_ms"),
        "stages": stage_ms,
        "llm": round(sum(c["ms"] for c in t["llm_calls"]), 2),
    }
    t.pop("_depth", None)
    t.pop("_order", None)
