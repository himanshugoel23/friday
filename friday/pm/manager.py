# ruff: noqa: E501
"""Agent 2: the project manager. A deterministic state machine over a persisted ``TaskRecord``.

Rules (docs/PROJECT_MANAGER.md): it never calls vendors and never writes vendor-facing words;
the LLM (optional) only rewords a user-facing question; every decision goes to the record's log;
the user hears from it ONCE when the request is understood, then only for an outcome or a
question only the user can answer (progress messages exist only when ``updates_on``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .classifier import CHANNELS, Classification, Classifier
from .plans import PlanTemplate, long_slots, message, slot_question, template_for
from .plans import raw as plans_raw
from .slots import (
    SLOT_KEYS,
    QuestionWriter,
    RuleSlotExtractor,
    SlotExtractor,
    TemplateWriter,
    clean_slots,
    detect_language,
    is_cancel,
    parse_answer,
    parse_yes_no,
)
from .state import (
    TERMINAL,
    Decision,
    MemoryTaskStore,
    Pending,
    Status,
    StepState,
    TaskRecord,
    TaskStore,
    utcnow,
)
from .steps import StepAgents, StepContext, StepResult

PARENTS = {"mummy", "mom", "mother", "maa", "papa", "dad", "father", "parents"}
# Slot change -> first step that must run again.
_RESET_FROM = {"where": "locate", "service": "search", "details": "search",
               "when": "calls", "delegation": "calls", "for_whom": "calls", "budget": "collect"}


class PMReply(BaseModel):
    task_id: str
    status: str
    messages: list[str] = Field(default_factory=list)   # in the turn's own channel
    pending_kind: str | None = None
    deliver_via: str = "whatsapp_text"                   # channel of ``messages``
    whatsapp: list[str] = Field(default_factory=list)    # extra texts to send on WhatsApp


class TurnReply(BaseModel):
    """Turn-based result for any channel (the voice layer speaks ``reply_text``)."""

    task_id: str
    reply_text: str
    state: str                       # task status value
    pending_kind: str | None = None  # what the PM waits for (None = nothing / working)
    pending_slot: str | None = None
    background: bool = False         # call: steps run later via run_background()
    whatsapp: list[str] = Field(default_factory=list)
    done: bool = False


class ProjectManager:
    def __init__(self, *, classifier: Classifier, agents: StepAgents,
                 store: TaskStore | None = None, extractor: SlotExtractor | None = None,
                 writer: QuestionWriter | None = None,
                 clock: Callable[[], datetime] = utcnow,
                 id_factory: Callable[[], str] | None = None,
                 min_confidence: float = 0.6, max_rounds: int = 2,
                 max_step_attempts: int = 2) -> None:
        self.classifier = classifier
        self.agents = agents
        self.store = store or MemoryTaskStore()
        self.extractor = extractor or RuleSlotExtractor()
        self.writer = writer or TemplateWriter()
        self.clock = clock
        self.new_id = id_factory or (lambda: uuid.uuid4().hex[:12])
        self.min_confidence = min_confidence
        self.max_rounds = max_rounds
        self.max_step_attempts = max_step_attempts

    # ------------------------------------------------------------------ public API

    async def handle_turn(self, task_id: str | None, text: str,
                          channel: str = "whatsapp_text", *, user_id: str = "user",
                          profile: dict[str, Any] | None = None,
                          updates_on: bool = False) -> TurnReply:
        """One user turn on any channel (whatsapp_text | whatsapp_voice | call | sms)."""
        r = await self.handle_message(text, task_id=task_id, user_id=user_id, profile=profile,
                                      updates_on=updates_on, channel=channel)
        task = self.store.load(r.task_id)
        assert task is not None
        return TurnReply(
            task_id=r.task_id, reply_text=" ".join(r.messages), state=r.status,
            pending_kind=r.pending_kind,
            pending_slot=task.pending.slot if task.pending else None,
            background=task.background, whatsapp=r.whatsapp,
            done=task.status in TERMINAL)

    async def run_background(self, task_id: str) -> PMReply:
        """Run the plan of a task that started on a call. From here everything (questions,
        the outcome) goes to WhatsApp; nothing depends on the caller still being on the line."""
        task = self.store.load(task_id)
        if task is None:
            raise KeyError(f"unknown task {task_id}")
        msgs: list[str] = []
        if task.status not in TERMINAL and not task.pending:
            task.channel, task.background = "whatsapp_text", False
            self._log(task, "background_run_started")
            await self._drive(task, msgs)
        reply = self._reply(task, msgs)
        self.store.save(task)
        return reply

    async def handle_message(self, text: str, *, task_id: str | None = None,
                             user_id: str = "user", profile: dict[str, Any] | None = None,
                             updates_on: bool = False,
                             channel: str = "whatsapp_text") -> PMReply:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        msgs: list[str] = []
        if task_id is None:
            task = TaskRecord(id=self.new_id(), user_id=user_id, profile=profile or {},
                              updates_on=updates_on, channel=channel)
            self._log(task, "task_created", user_id=user_id, updates_on=updates_on)
            self._note_message(task, text)
            await self._start(task, text, msgs)
        else:
            loaded = self.store.load(task_id)
            if loaded is None:
                raise KeyError(f"unknown task {task_id}")
            task = loaded
            task.channel = channel
            if task.status in TERMINAL:
                self._say(task, msgs, self._m(task, "terminal"))
                self.store.save(task)
                return self._reply(task, msgs)
            self._note_message(task, text)
            await self._on_message(task, text, msgs)
        await self._drive(task, msgs)
        reply = self._reply(task, msgs)
        self.store.save(task)
        return reply

    async def resume(self, task_id: str) -> PMReply:
        """Continue after a restart: steps caught mid-run are re-run; a waiting question is re-sent."""
        task = self.store.load(task_id)
        if task is None:
            raise KeyError(f"unknown task {task_id}")
        msgs: list[str] = []
        if task.status not in TERMINAL:
            for s in task.plan:
                if s.status == "running":
                    s.status = "pending"
                    self._log(task, "resumed_step", step=s.name)
            if task.pending:
                self._say(task, msgs, task.pending.prompt)
            else:
                await self._drive(task, msgs)
        reply = self._reply(task, msgs)
        self.store.save(task)
        return reply

    # ------------------------------------------------------------------ helpers

    def _log(self, task: TaskRecord, event: str, /, **detail: Any) -> None:
        task.log.append(Decision(ts=self.clock().isoformat(), kind=event, detail=detail))

    def _say(self, task: TaskRecord, msgs: list[str], text: str) -> None:
        msgs.append(text)
        task.outbox.append(text)

    def _reply(self, task: TaskRecord, msgs: list[str]) -> PMReply:
        wa, task.deferred = [d["text"] for d in task.deferred], []
        return PMReply(task_id=task.id, status=task.status.value, messages=msgs,
                       pending_kind=task.pending.kind if task.pending else None,
                       deliver_via=task.channel, whatsapp=wa)

    def _note_message(self, task: TaskRecord, text: str) -> None:
        task.inbox.append(text)
        lang = detect_language(text)
        if lang != "en" or not task.inbox[:-1]:
            task.language = lang

    def _template(self, task: TaskRecord) -> PlanTemplate:
        assert task.bucket
        t = template_for(task.bucket, task.category)
        if task.archetype and task.archetype != t.archetype:  # e.g. book downgraded to availability
            from .plans import build_template
            t = build_template(task.archetype, task.category)
        return t

    def _m(self, task: TaskRecord, key: str, **kw: Any) -> str:
        """Template text in the user's language and the current channel's style."""
        return message(key, task.language, task.channel, **kw)

    def _stop(self, task: TaskRecord, msgs: list[str], reason: str, key: str, **kw: Any) -> None:
        task.status = Status.STOPPED
        task.stop_reason = reason
        task.pending = None
        self._log(task, "stopped", reason=reason)
        self._say(task, msgs, self._m(task, key, **kw))
        if task.channel == "call":  # the outcome is always also delivered on WhatsApp
            self._whatsapp(task, message(key, task.language, "whatsapp_text", **kw))

    def _whatsapp(self, task: TaskRecord, text: str) -> None:
        task.deferred.append({"channel": "whatsapp_text", "text": text})
        task.outbox.append(text)

    async def _ask(self, task: TaskRecord, msgs: list[str], pending: Pending) -> None:
        if pending.slot:
            pending.prompt = await self.writer.write(pending.slot, pending.prompt, task.language)
        task.pending = pending
        task.status = Status.AWAITING_USER
        self._log(task, "question_asked", kind=pending.kind, slot=pending.slot,
                  round=task.rounds_used)
        self._say(task, msgs, pending.prompt)

    # ------------------------------------------------------------------ first message

    async def _start(self, task: TaskRecord, text: str, msgs: list[str]) -> None:
        c = await self.classifier.classify(text, task.channel)
        self._apply_classification(task, c)
        await self._after_classification(task, text, msgs)

    def _apply_classification(self, task: TaskRecord, c: Classification) -> None:
        task.bucket, task.category, task.confidence = c.bucket, c.category, c.confidence
        from .taxonomy import buckets
        task.archetype = buckets()[c.bucket].archetype
        self._log(task, "classified", bucket=c.bucket, category=c.category,
                  confidence=c.confidence)

    async def _after_classification(self, task: TaskRecord, text: str,
                                    msgs: list[str]) -> None:
        if task.archetype == "handoff" and task.bucket != "other":
            task.status = Status.HANDOFF
            self._log(task, "handoff", bucket=task.bucket, reason="bucket_not_run_by_pm")
            self._say(task, msgs, self._m(task, "handoff"))
            return
        if task.category is None or task.bucket == "other" or task.confidence < self.min_confidence:
            if task.category is None and task.bucket == "other" and task.confidence < 0.3 \
                    and task.rounds_used >= self.max_rounds:
                pass
            if task.rounds_used >= self.max_rounds:
                if task.category is None or task.bucket == "other":
                    self._stop(task, msgs, "classification_unresolved", "stop_category")
                    return
            else:
                task.rounds_used += 1
                if task.category is None:
                    p = Pending(kind="category", prompt=self._m(task, "category_unclear"))
                else:
                    p = Pending(kind="bucket", prompt=self._m(task, "bucket_unclear"))
                await self._ask(task, msgs, p)
                return
        if task.archetype == "handoff":  # bucket "other" with a category but rounds used up
            task.status = Status.HANDOFF
            self._say(task, msgs, self._m(task, "handoff"))
            return
        await self._ingest_first(task, text)

    async def _ingest_first(self, task: TaskRecord, text: str) -> None:
        """Slots from the first message plus saved places from the caller's profile."""
        found = clean_slots(await self.extractor.extract(text, task.category))
        for k, v in found.items():
            task.slots.setdefault(k, v)
        if found:
            self._log(task, "slots_extracted", slots=found)
        if "where" not in task.slots:
            prof = task.profile
            whom = str(task.slots.get("for_whom", "")).lower()
            place = prof.get("parents_place") if whom in PARENTS else prof.get("home_place")
            if place:
                task.slots["where"] = place
                self._log(task, "slot_from_profile", slot="where", for_whom=whom or "self")

    # ------------------------------------------------------------------ later messages

    async def _on_message(self, task: TaskRecord, text: str, msgs: list[str]) -> None:
        if is_cancel(text):
            self._cancel(task, msgs, during=task.pending.kind if task.pending else "running")
            return
        p = task.pending
        if p is not None and p.data.get("via") == "whatsapp" and task.channel == "call":
            self._say(task, msgs, self._m(task, "whatsapp_followup"))  # long input: not by voice
            return
        if p is None:
            await self._apply_changes(task, text, msgs)
            return
        if p.kind in ("category", "bucket"):
            c = await self.classifier.classify(text, task.channel)
            self._log(task, "answer_received", kind=p.kind)
            bucket = c.bucket if c.bucket != "other" else task.bucket
            category = c.category or task.category
            conf = max(c.confidence, 0.7) if (bucket != "other" and category) else c.confidence
            merged = Classification(bucket=bucket or "other", category=category, confidence=conf)
            task.pending = None
            self._apply_classification(task, merged)
            await self._after_classification(task, " ".join(task.inbox), msgs)
            if task.status == Status.AWAITING_USER and task.pending is None:
                task.status = Status.RUNNING
            return
        if p.kind == "slot":
            await self._answer_slot(task, text, msgs)
            return
        if p.kind == "step_question":
            task.outputs.setdefault("_answers", {})[p.step] = text
            self._log(task, "answer_received", kind="step_question", step=p.step)
            task.pending = None
            task.status = Status.RUNNING
            return
        # consent | widen | over_budget : yes / no
        # New slot values in the reply ("nahi, Sector 45 mein") are a change, not a yes/no.
        before = dict(task.slots)
        await self._apply_changes(task, text, msgs, keep_pending=True)
        if task.slots != before:
            return
        yn = parse_yes_no(text)
        if yn is None:
            p.unclear += 1
            self._log(task, "answer_unclear", kind=p.kind, count=p.unclear)
            if p.unclear >= 2:
                self._stop(task, msgs, f"{p.kind}_unanswered", "stop_category")
            else:
                self._say(task, msgs, self._m(task, "yesno_unclear"))
            return
        self._log(task, "answer_received", kind=p.kind, value=yn)
        await self._yes_no(task, p, yn, msgs)

    async def _answer_slot(self, task: TaskRecord, text: str, msgs: list[str]) -> None:
        p = task.pending
        assert p and p.slot
        value = parse_answer(p.slot, text)
        if value is None and p.unclear < 1:
            p.unclear += 1
            self._log(task, "answer_unclear", slot=p.slot)
            self._say(task, msgs, self._m(task, "yesno_unclear")
                      if p.slot == "delegation" else p.prompt)
            return
        task.pending = None
        task.status = Status.RUNNING
        if value is not None:
            task.slots[p.slot] = value
            self._log(task, "answer_received", slot=p.slot, value=value)
        else:
            self._log(task, "answer_unusable", slot=p.slot)
        extra = clean_slots(await self.extractor.extract(text, task.category))
        for k, v in extra.items():
            if k != p.slot:
                task.slots.setdefault(k, v)

    async def _yes_no(self, task: TaskRecord, p: Pending, yes: bool, msgs: list[str]) -> None:
        if p.kind == "consent":
            if yes:
                task.outputs["_consent_user"] = True
                task.pending, task.status = None, Status.RUNNING
            else:
                self._stop(task, msgs, "consent_declined", "consent_declined")
        elif p.kind == "widen":
            if yes:
                to = float(p.data["to_km"])
                self._log(task, "widen_accepted", from_km=task.radius_km, to_km=to)
                task.radius_km = to
                task.pending, task.status = None, Status.RUNNING
                self._reset_from(task, "search", reset_radius=False)
            else:
                self._stop(task, msgs, "widen_declined", "widen_declined")
        elif p.kind == "over_budget":
            if yes:
                task.outputs["_over_budget_ack"] = True
                task.pending, task.status = None, Status.RUNNING
            else:
                self._stop(task, msgs, "over_budget_declined", "over_budget_declined")

    # ------------------------------------------------------------------ interruptions

    def _cancel(self, task: TaskRecord, msgs: list[str], during: str) -> None:
        task.status = Status.CANCELLED
        task.pending = None
        for s in task.plan:
            if s.status in ("pending", "running"):
                s.status = "skipped"
        self._log(task, "interrupt_cancel", during=during)
        self._say(task, msgs, self._m(task, "cancelled"))

    def _reset_from(self, task: TaskRecord, step: str, reset_radius: bool = True) -> None:
        names = [s.name for s in task.plan]
        if step not in names:
            return
        i = names.index(step)
        for s in task.plan[i:]:
            s.status, s.reason = "pending", None
            task.outputs.pop(s.name, None)
        task.outputs.pop("_over_budget_ack", None)
        task.outputs.pop("_over_budget", None)
        if "consent" in names and i <= names.index("consent"):
            task.outputs.pop("_consent_user", None)
        if reset_radius and i <= (names.index("search") if "search" in names else 0):
            tpl = self._template(task)
            task.radius_km = tpl.radius_km
        self._log(task, "replan", from_step=step)

    async def _apply_changes(self, task: TaskRecord, text: str, msgs: list[str],
                             keep_pending: bool = False) -> None:
        found = clean_slots(await self.extractor.extract(text, task.category))
        changes = {k: v for k, v in found.items() if k in SLOT_KEYS and task.slots.get(k) != v}
        if not changes:
            self._log(task, "message_ignored", reason="no_slot_change")
            return
        self._log(task, "interrupt_change", changes=changes)
        task.slots.update(changes)
        if not task.plan:  # still collecting slots: just take the new values
            return
        if changes.get("delegation") is False and task.archetype == "book":
            task.archetype = "availability"
            self._rebuild_plan(task)
            self._log(task, "archetype_switch", to="availability")
        names = [s.name for s in task.plan]
        first = min((_RESET_FROM[k] for k in changes if _RESET_FROM[k] in names),
                    key=names.index, default=None)
        if first:
            self._reset_from(task, first)
        if not keep_pending:
            task.pending = None
        else:
            task.pending = None
        task.status = Status.RUNNING
        summary = ", ".join(f"{k}={v}" for k, v in changes.items())
        self._say(task, msgs, self._m(task, "replanned", changes=summary))

    def _rebuild_plan(self, task: TaskRecord) -> None:
        old = {s.name: s for s in task.plan}
        task.plan = [old.get(n, StepState(name=n)) for n in self._template(task).steps]

    # ------------------------------------------------------------------ slot checking and plan

    async def _check_slots(self, task: TaskRecord, msgs: list[str]) -> None:
        if task.archetype == "book" and task.slots.get("delegation") is False:
            task.archetype = "availability"   # the user said: do not book, only check
            self._log(task, "archetype_switch", to="availability", reason="delegation_declined")
            self._say(task, msgs, self._m(task, "switched_to_check"))
        tpl = self._template(task)
        order = plans_raw()["ask_order"]
        missing = [s for s in order if s in tpl.required and s not in task.slots]
        if missing and task.rounds_used < self.max_rounds:
            slot = missing[0]
            task.rounds_used += 1
            if task.channel == "call" and slot in long_slots():
                # Long input (details, address, many numbers) is requested on WhatsApp.
                q = slot_question(slot, task.language, tpl, "whatsapp_text")
                task.pending = Pending(kind="slot", slot=slot, prompt=q, data={"via": "whatsapp"})
                task.status = Status.AWAITING_USER
                self._log(task, "question_deferred_to_whatsapp", slot=slot)
                self._whatsapp(task, message("whatsapp_followup", task.language, question=q))
                self._say(task, msgs, self._m(task, "whatsapp_followup"))
                return
            await self._ask(task, msgs, Pending(kind="slot", slot=slot,
                                                prompt=slot_question(slot, task.language, tpl, task.channel)))
            return
        unresolved: list[str] = []
        for slot in missing:
            if slot in tpl.defaults:
                task.slots[slot] = tpl.defaults[slot]
                task.assumed[slot] = tpl.defaults[slot]
                self._log(task, "default_applied", slot=slot, value=tpl.defaults[slot])
            else:
                unresolved.append(slot)
        if "delegation" in unresolved and task.archetype == "book":
            # No explicit instruction to book: never book. Check prices/availability only.
            task.archetype = "availability"
            self._log(task, "archetype_switch", to="availability", reason="no_delegation")
            self._say(task, msgs, self._m(task, "switched_to_check"))
            tpl = self._template(task)
            unresolved = [s for s in tpl.required if s not in task.slots and s not in tpl.defaults]
            for s in tpl.required:
                if s not in task.slots and s in tpl.defaults:
                    task.slots[s] = tpl.defaults[s]
                    task.assumed[s] = tpl.defaults[s]
        if unresolved:
            self._stop(task, msgs, "missing_slots:" + ",".join(unresolved), "stop_missing",
                       missing=", ".join(unresolved))
            return
        for k, v in tpl.defaults.items():  # optional slots: silent defaults
            if k not in task.slots:
                task.slots[k] = v
                self._log(task, "default_applied", slot=k, value=v, silent=True)
        task.radius_km = tpl.radius_km
        task.plan = [StepState(name=n) for n in tpl.steps]
        task.status = Status.RUNNING
        self._log(task, "plan_created", archetype=tpl.archetype, steps=tpl.steps,
                  radius_km=tpl.radius_km, hard_max_km=tpl.hard_max_km,
                  assumed=task.assumed)
        self._ack(task, msgs, tpl)

    def _ack(self, task: TaskRecord, msgs: list[str], tpl: PlanTemplate) -> None:
        if task.acked:
            return
        task.acked = True
        from .taxonomy import buckets, categories
        summary = f"{buckets()[task.bucket].label.lower()}: {categories()[task.category].label}"
        shown = {k: v for k, v in task.assumed.items() if k != "for_whom"}
        if shown:
            assumed = ", ".join(f"{k}: {v}" for k, v in shown.items())
            self._say(task, msgs, self._m(task, "ack_assumed", summary=summary,
                                          assumed=assumed))
        else:
            self._say(task, msgs, self._m(task, "ack", summary=summary))

    # ------------------------------------------------------------------ driving the plan

    async def _drive(self, task: TaskRecord, msgs: list[str]) -> None:
        for _ in range(200):
            if task.status in TERMINAL or task.pending:
                return
            if task.bucket is None:
                return
            if not task.plan:
                await self._check_slots(task, msgs)
                if not task.plan:
                    return
                continue
            step = next((s for s in task.plan if s.status in ("pending", "running")), None)
            if step is None:
                task.status = Status.DONE
                self._log(task, "done")
                return
            if task.channel == "call":  # keep the call turn short: steps run via run_background
                task.background = True
                self._log(task, "background_scheduled")
                return
            await self._run_step(task, step, msgs)
            self.store.save(task)

    def _ctx(self, task: TaskRecord, step: str, vendor: dict | None = None) -> StepContext:
        tpl = self._template(task)
        return StepContext(
            task_id=task.id, user_id=task.user_id, step=step, bucket=task.bucket or "", category=task.category or "",
            slots=dict(task.slots), radius_km=task.radius_km or tpl.radius_km,
            hard_max_km=tpl.hard_max_km, n_vendors=tpl.n_vendors,
            outputs={k: v for k, v in task.outputs.items() if not k.startswith("_")}
            | {k: v for k, v in task.outputs.items() if k == "_over_budget"},
            vendor=vendor, user_answer=task.outputs.get("_answers", {}).get(step),
            language=task.language)

    async def _agent(self, step: str, ctx: StepContext) -> StepResult:
        try:
            return await self.agents.run(step, ctx)
        except Exception as e:  # noqa: BLE001 - agent crashes are failures, not PM crashes
            return StepResult(status="failed", reason=f"exception:{type(e).__name__}",
                              retryable=True)

    async def _run_step(self, task: TaskRecord, step: StepState, msgs: list[str]) -> None:
        if step.name == "consent":
            await self._consent(task, step, msgs)
            return
        if step.name == "calls":
            await self._calls(task, step, msgs)
            return
        step.status = "running"
        step.attempts += 1
        self._log(task, "step_started", step=step.name, attempt=step.attempts)
        res = await self._agent(step.name, self._ctx(task, step.name))
        await self._handle_result(task, step, res, msgs)

    async def _handle_result(self, task: TaskRecord, step: StepState, res: StepResult,
                             msgs: list[str]) -> None:
        if res.status == "ok":
            data = res.data
            if step.name == "shortlist":
                data = self._validate_shortlist(task, data)
                if not data["vendors"]:
                    await self._on_empty(task, step, "no_vendors_in_range", msgs)
                    return
            step.status = "done"
            task.outputs[step.name] = data
            self._log(task, "step_done", step=step.name)
            if task.updates_on and step.name != "report":
                self._say(task, msgs, self._m(task, "progress", step=step.name))
            if step.name == "collect" and await self._over_budget(task, data, msgs):
                return
            if step.name == "report" and isinstance(data.get("message"), str):
                self._say(task, msgs, data["message"])
        elif res.status == "empty":
            await self._on_empty(task, step, res.reason or "empty", msgs)
        elif res.status == "needs_user":
            step.status = "pending"
            step.attempts -= 1
            await self._ask(task, msgs, Pending(
                kind="step_question", step=step.name,
                prompt=res.question or slot_question("where", task.language)))
        else:  # failed
            self._log(task, "step_failed", step=step.name, reason=res.reason,
                      retryable=res.retryable, attempt=step.attempts)
            if res.retryable and step.attempts < self.max_step_attempts:
                step.status = "pending"
                return
            step.status, step.reason = "failed", res.reason
            self._stop(task, msgs, f"step_failed:{step.name}:{res.reason}",
                       "blocked" if res.reason == "blocked_by_policy" else "step_failed")

    def _validate_shortlist(self, task: TaskRecord, data: dict) -> dict:
        """Distance is a HARD filter: drop anything beyond the radius or the category hard max."""
        tpl = self._template(task)
        limit = min(task.radius_km or tpl.radius_km, tpl.hard_max_km)
        kept = []
        for v in data.get("vendors", []):
            d = v.get("distance_km")
            if isinstance(d, int | float) and not isinstance(d, bool) and d <= limit:
                kept.append(v)
            else:
                self._log(task, "distance_violation", vendor=v.get("id"), distance_km=d,
                          limit_km=limit)
        return {**data, "vendors": kept}

    async def _on_empty(self, task: TaskRecord, step: StepState, reason: str,
                        msgs: list[str]) -> None:
        tpl = self._template(task)
        cur = task.radius_km or tpl.radius_km
        bigger = [r for r in tpl.radius_steps if r > cur]
        step.status = "pending"
        self._log(task, "no_vendors", step=step.name, radius_km=cur, reason=reason)
        if not bigger:
            self._stop(task, msgs, "no_vendors_within_hard_max", "widen_stop",
                       hard_max_km=int(tpl.hard_max_km))
            return
        to = bigger[0]
        self._log(task, "widen_offered", from_km=cur, to_km=to)
        await self._ask(task, msgs, Pending(
            kind="widen", data={"to_km": to},
            prompt=self._m(task, "widen", current_km=_km(cur), to_km=_km(to))))

    async def _consent(self, task: TaskRecord, step: StepState, msgs: list[str]) -> None:
        tpl = self._template(task)
        if not task.outputs.get("_consent_user"):
            vendors = task.outputs.get("shortlist", {}).get("vendors", [])
            lines = []
            for v in vendors[: tpl.n_vendors]:
                extra = f", {v['rating']}*" if v.get("rating") else ""
                lines.append(f"- {v.get('name', v.get('id'))}, {_km(v['distance_km'])} km{extra}")
            await self._ask(task, msgs, Pending(
                kind="consent", data={"vendors": [v.get("id") for v in vendors]},
                prompt=self._m(task, "consent", count=len(lines),
                               list="\n".join(lines))))
            return
        step.status = "running"
        step.attempts += 1
        res = await self._agent("consent", self._ctx(task, "consent"))
        if res.status == "ok" and res.data.get("approved", True):
            step.status = "done"
            task.outputs["consent"] = res.data
            self._log(task, "step_done", step="consent")
        else:
            res = StepResult(status="failed", reason=res.reason or "blocked_by_policy")
            await self._handle_result(task, step, res, msgs)

    async def _calls(self, task: TaskRecord, step: StepState, msgs: list[str]) -> None:
        tpl = self._template(task)
        step.status = "running"
        step.attempts += 1
        results: list[dict] = task.outputs.setdefault("calls", [])
        tried = {r["vendor_id"] for r in results}
        vendors = task.outputs.get("shortlist", {}).get("vendors", [])
        want = 1 if tpl.call_mode == "first_success" else tpl.n_vendors
        ok = sum(r["outcome"] == "ok" for r in results)
        for v in vendors:
            if ok >= want:
                break
            if v["id"] in tried:
                continue
            res = await self._agent("calls", self._ctx(task, "calls", vendor=v))
            entry = {**res.data, "vendor_id": v["id"], "vendor_name": v.get("name"),
                     "reason": res.reason}
            if res.status == "ok" and res.data.get("ambiguous"):
                entry["outcome"] = "ambiguous"
                self._log(task, "flagged_ambiguous", vendor=v["id"])
            elif res.status == "ok":
                entry["outcome"] = "ok"
                ok += 1
            else:
                entry["outcome"] = res.reason or "failed"
                self._log(task, "vendor_skipped", vendor=v["id"], reason=res.reason,
                          next="next vendor in shortlist")
            results.append(entry)
            self.store.save(task)
        if ok == 0 and not any(r["outcome"] == "ambiguous" for r in results):
            step.status = "failed"
            self._stop(task, msgs, "all_vendors_failed", "all_no_pickup")
            return
        step.status = "done"
        self._log(task, "step_done", step="calls", ok=ok, tried=len(results))

    async def _over_budget(self, task: TaskRecord, data: dict, msgs: list[str]) -> bool:
        budget = task.slots.get("budget")
        prices = [q["price_inr"] for q in data.get("quotes", [])
                  if isinstance(q.get("price_inr"), int | float)]
        if not budget or not prices or min(prices) <= budget:
            return False
        self._log(task, "over_budget", budget=budget, lowest=min(prices))
        task.outputs["_over_budget"] = True
        if task.outputs.get("_over_budget_ack"):
            return False
        await self._ask(task, msgs, Pending(
            kind="over_budget",
            prompt=self._m(task, "over_budget", budget=budget, lowest=int(min(prices)))))
        return True


def _km(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"
