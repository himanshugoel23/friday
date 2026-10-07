# Core change requests (append-only)

`friday/core/` is frozen while engineers work in parallel. To request a change, append
an entry below: **who / what / why / exact diff**. Additive only (new optional fields
with defaults, new enum members, new Protocols). Until merged, work around it locally
in your own package.

<!-- template
## YYYY-MM-DD — <name> (<role>)
What:
Why:
Diff:
-->

## 2026-10-07 — Backend Engineer A (db/channels/api)
What: (1) `Notifier` Protocol; (2) `TaskEngine` Protocol (methods the inbound pipeline and
call-back service call); (3) inbound/missed-call events; (4) caller-ID on calls.
Why: Backend B (tasks/proactive), Voice and Backend A integrate today only by duck typing
(`friday/tasks/ports.py`, `friday/api/inbound.py`, `friday/api/callbacks.py`). BRIEF E30-35
needs the Friday caller-ID per call and inbound-call events shared by voice and backend.
Diff (all additive):
```python
# interfaces.py
@runtime_checkable
class Notifier(Protocol):  # impl: friday.channels.notifier.Notifier
    async def send(self, msg: OutboundMessage, *, urgency: Urgency | None = None) -> SendReceipt: ...
    async def notify_user(self, user_id: str, text: str | None = None, *,
        buttons: Sequence[ReplyButton] = (), template: TemplateRef | None = None,
        task_id: str | None = None, nudge_id: str | None = None,
        question_id: str | None = None) -> SendReceipt: ...
    async def ask_user(self, user_id: str, question: MidCallQuestion) -> SendReceipt: ...
    async def message_person(self, person_id: str, text: str | None = None, *,
        template: TemplateRef | None = None) -> SendReceipt: ...       # consent-gated
    async def request_person_opt_in(self, person: Person, *, requester_name: str,
        what: str) -> SendReceipt: ...
    async def business_touch(self, business: Business, template: TemplateRef, *,
        user_id: str | None = None, task_id: str | None = None) -> SendReceipt: ...

@runtime_checkable
class TaskEngine(Protocol):  # impl: friday.tasks.engine (Backend B)
    async def submit(self, task: Task) -> None: ...             # task already persisted (CREATED)
    async def handle_answer(self, answer: UserAnswer) -> None: ...  # also on bus: UserAnswerReceived
    async def approve(self, task_id: str, approve: bool) -> None: ...  # a:<task>:yes|no buttons
    async def choose(self, task_id: str, index: int | None) -> None: ...
    async def cancel(self, task_id: str) -> None: ...
    async def update_spec(self, task_id: str, spec: TaskSpec) -> None: ...
    # BRIEF E31-35; `match`/`contact` = friday.db.repositories.CallbackMatch / InboundContact
    async def handle_business_callback(self, match: Any, contact: Any) -> None: ...
    async def handle_missed_call(self, match: Any, contact: Any) -> None: ...
    async def handle_business_message(self, msg: InboundMessage, match: Any) -> None: ...
    async def handle_unknown_caller(self, match: Any, contact: Any) -> None: ...  # optional
    async def start(self) -> None: ...   # queue workers (called by the API runtime)
    async def stop(self) -> None: ...

# events.py (published by friday/voice on its inbound webhook)
class InboundCallReceived(Event):
    from_phone: str; to_number: str | None = None; provider_call_id: str | None = None
class MissedCallReceived(Event):
    from_phone: str; to_number: str | None = None; provider_call_id: str | None = None

# models.py
class CallResult:          from_number: str | None = None   # Friday caller ID used
class OutboundCallRequest: from_number: str | None = None   # sticky caller ID (repos.calls.choose_number)
```
Until merged: `friday/api/callbacks.py` subscribes to `Event` and filters by the class names
above; `TaskRepo.save_call` reads `getattr(result, "from_number", None)`; engine/voice may call
`c.repos.calls.record_outbound(..., friday_number=...)` and `c.repos.calls.match(phone, friday_number=...)`.
