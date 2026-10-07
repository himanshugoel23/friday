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

## 2026-10-07 — Backend Engineer B (tasks/proactive/discovery)
What / why / diff (all additive). Until merged, the workarounds named below are live.
```python
# models.py
class Task:            role: str | None = None
#   fanout | booking | instance | reconfirm | care_followup | callback | close_loop | retry.
#   Workaround: "[friday:role=<role>]" tag in TaskSpec.notes (friday/tasks/engine.py:role_of).
class Business:        alt_phones: list[str] = []          # E.36 "other listed numbers"
#   Workaround: Business.whatsapp_phone is tried as the alternate number.
class BusinessCandidate: hours: BusinessHours | None = None  # B19 hours from Places details
#   Workaround: optional `directory.business_hours(place_id)` on the discovery providers.
class CallBrief:       from_number: str | None = None      # sticky caller-ID (also Voice's ask)
#   Workaround: engine passes runner.run(..., from_number=...) when the runner accepts it.

# config.py - E.36/E.37 policy (today: friday/tasks/policy.py TaskPolicy, env FRIDAY_TASKS_*)
friday_numbers: list[str] = []            # Friday caller-ID pool (Voice proposed the same)
tasks_max_attempts: int = 3
tasks_no_answer_delays_min: list[int] = [10, 45]
tasks_final_window_gap_min: int = 120
tasks_busy_delay_min: int = 5
tasks_try_alt_numbers: bool = True
tasks_whatsapp_request_on_no_answer: bool = True
tasks_missed_call_notify_after: int = 3
tasks_better_offer_pct: int = 15

# interfaces.py
# + endorse Backend A's Notifier / TaskEngine Protocols (my engine implements the
#   TaskEngine one: submit, handle_answer, approve(task_id, approve), choose, cancel,
#   update_spec, handle_business_callback, handle_missed_call, handle_business_message,
#   handle_unknown_caller, start, stop).
# + CallSessionRunner: run_inbound(brief, leg, ask_user, notify_user, *, context=None)
#   and cancel(task_id) (Voice already implements both; the engine uses them if present).
# + TaskRepository extras the engines call when present: add_question, get_question,
#   answer_question, save_hotel_booking; NudgeRepository: get, list_for_user,
#   list_scheduled_due, list_sent_unanswered_before, add_feedback; UserRepository.list_active.

# events.py (today local in friday/tasks/events.py, no core change strictly needed)
class WellbeingAlertRaised(Event): task_id; user_id; person_id: str | None; text: str
```

## 2026-10-07 — Voice Engineer (friday/voice)
What / why / diff (all additive). Voice already works without them via local workarounds
(noted per item); merging them removes the workarounds.

1. **Telephony selection: Sarvam > Exotel > Twilio** (founder/coordinator decisions).
   Today: `FRIDAY_TELEPHONY_PROVIDER=exotel` (or `twilio`) + env `FRIDAY_TELEPHONY_ROUTE=sarvam,exotel,twilio`
   makes those factories return `friday.voice.telephony.routing.RoutedTelephony` (per-call capability fallback,
   Twilio for non-+91 numbers).
```python
# config.py
TelephonyProviderName = Literal["auto", "simulator", "routed", "sarvam", "twilio", "exotel", "plivo"]
telephony_route: list[str] = ["sarvam", "exotel", "twilio"]            # FRIDAY_TELEPHONY_ROUTE
friday_numbers: list[str] = []          # FRIDAY_NUMBERS: sticky caller-ID pool (all providers)
exotel_subdomain: str = "api.in.exotel.com"; exotel_voicebot_app_id: str | None = None   # EXOTEL_*
exotel_caller_ids: list[str] = []
sarvam_telephony_auth_id: str | None = None; sarvam_telephony_auth_token: SecretStr | None = None
sarvam_telephony_base_url: str = "https://api.vobiz.ai/api/v1"; sarvam_caller_ids: list[str] = []
sim_time_scale: float | None = None     # simulator legs: virtual-time scale (None = auto)
def resolve_telephony(self):
    if not self.is_live: return "simulator"
    if self.telephony_provider != "auto": return self.telephony_provider
    return "routed"   # RoutedTelephony skips providers without credentials
# live_problems(): exotel -> also EXOTEL_VOICEBOT_APP_ID; sarvam -> SARVAM_TELEPHONY_AUTH_ID/_TOKEN;
#                  routed -> at least one provider in telephony_route fully configured
# container.py FACTORIES["telephony"]
"routed": "friday.voice.telephony.routing:build_routed_telephony",
"sarvam": "friday.voice.telephony.sarvam:build_sarvam_telephony",
```
2. **Capabilities + inbound on the telephony Protocol** (BRIEF E30-37; per-call fallback).
   Today: duck-typed (`capabilities()`, `take_inbound()` exist on every voice provider).
```python
class TelephonyProvider(Protocol):
    def capabilities(self) -> frozenset[str]: ...   # outbound, inbound, missed_call, media_stream,
                                                   # dtmf, recording, amd, bridge_transfer, bridge_conference
    def take_inbound(self, provider_call_id: str) -> CallLeg | None: ...  # claim a parked inbound leg
class CallSessionRunner(Protocol):
    async def run_inbound(self, leg: CallLeg, brief: CallBrief, ask_user: AskUser,
                          notify_user: NotifyUser | None = None, *, context: str | None = None
                          ) -> CallResult: ...       # (also accepts brief-first order)
    def cancel(self, task_id: str) -> None: ...      # FIRST_MATCH sibling found -> CANCELLED politely
```
   Events: voice publishes `InboundCallReceived(from_phone, to_number, provider_call_id, provider,
   business_id)` and `MissedCallReceived(from_phone, to_number, provider_call_id, provider, ring_seconds,
   reason)` from `friday/voice/events.py` — same names/fields as Backend A's proposal above; please move
   them (plus `CallCostReport`, `CallLatencyReport`, `CallLanguageSwitched`) into core events.py.
3. **Models** (today: `friday.voice.session.VoiceCallResult(CallResult)` subclass + request metadata).
```python
class OutboundCallRequest:  from_number: str | None = None   # sticky caller ID (runner also sets metadata)
class CallBrief:            from_number: str | None = None   # Backend B's CallMemory choice
                            ivr_map: list[str] = []          # learned menu path, e.g. ["2","3@broadband",
                                                             #  "{Registered mobile}#","9"] (today: ivr_notes
                                                             #  entry "replay: 2 | 3@broadband | ...")
class CallTurn:             audio_class: AudioClass | None = None  # today: "[ivr_prompt] ..." text prefix
class CallResult:           from_number: str | None = None
                            telephony_seconds: float = 0.0; stt_seconds: float = 0.0
                            tts_chars: int = 0; tts_billed_chars: int = 0
                            policy_calls: int = 0; translate_calls: int = 0; ivr_keys_replayed: int = 0
class Transcription:        duration_s: float | None = None  # chunk length (hold accounting)
```
4. **simworld** (today: `persona.notes` directives `sim:alt_phones=...`, `sim:no_answer_attempts=N`,
   `sim:calls_back_after=S`, `sim:missed_call_after=S`, `sim:agent_asks_otp`, `sim:person`, ...; see
   friday/voice/simulator.py docstring). Proposal: `SimBusiness.alt_phones: list[str] = []` so the
   directory/verifier simulators can list alternate numbers too (BRIEF E36).

## 2026-10-07 — AI Engineer (friday/brain)
All additive. Brain works today via local workarounds (noted per item).

1. **Inbound / call-back context on the brief** (BRIEF E-30..37). Today:
   `friday.brain.inbound.InboundCallBrief(CallBrief)` subclass + `inbound_of(brief)`; the brain also
   exposes `brain.build_inbound_brief(ctx, caller_phone=, tasks=|related=, kind="answered"|"missed_call",
   caller_matches_business=)` and `build_call_brief(ctx, task, *, inbound=InboundContext)`.
```python
class CallBrief:  direction: CallDirection = CallDirection.OUTBOUND
                  inbound: InboundContext | None = None   # move friday.brain.inbound.{InboundContext,
                                                          #  RelatedTask} into core models
class Brain(Protocol):
    def build_inbound_brief(self, ctx, *, caller_phone: str, tasks: Sequence[Task] = (),
                            related: Sequence[RelatedTask] = (), kind: str = "answered",
                            friday_number: str | None = None,
                            caller_matches_business: bool = True,
                            business_name: str | None = None) -> CallBrief: ...
```
   Note: `brain.build_call_brief` is deterministic; it returns an *awaitable* brief so both
   `await brain.build_call_brief(...)` (Protocol) and a plain call work.
2. **Approved identifiers in the context** (C24). `ConversationContext` has no identifiers, so the brain
   can't fill `CallBrief.approved_identifiers`. Today it reads `getattr(ctx, "identifiers", [])`;
   otherwise the backend must set `brief.approved_identifiers` after `build_call_brief`.
```python
class ConversationContext:  identifiers: list[AccountIdentifier] = []   # user's saved ids
```
3. **Cost/routing settings** (founder cost rule). Today: env `FRIDAY_LLM_MODEL_<PURPOSE>`,
   `FRIDAY_LLM_ESCALATION_MODEL`, `FRIDAY_LLM_TASK_TOKEN_BUDGET` read by `friday.brain.routing`.
   Defaults: Haiku for everything except `call_turn` (Sonnet); Opus only as escalation.
```python
llm_models: dict[str, str] = {}          # purpose -> model override
llm_call_model: str = "claude-sonnet-5-5"
llm_escalation_model: str = "claude-opus-5-5"
llm_task_token_budget: int = 60000       # per task; over budget -> cheaper model + warning log
# and change llm_model default use: never the default for any purpose (kept for compatibility)
```
4. **Button ids.** Brain emits/accepts `c:<parent_task_id>:<index|none>` (comparison choice) and
   `r:person|place:<id>` (reference disambiguation); onboarding uses `ob:*`. Proposal:
   `choice_button_id(task_id, i)`, `ref_button_id(kind, id)` helpers and `parse_button_id` accepting
   `c`/`r`.
5. **Forget command.** No intent exists; today "forget my rent date" -> `Intent.SETTINGS` with the
   matching facts in `Interpretation.facts` and a confirm reply. Proposal: `Intent.FORGET` +
   `Interpretation.forget_fact_ids: list[str] = []`.
6. **Nudge ids for buttons.** `judge_nudge` runs before the Nudge exists, so buttons use
   `brain.nudge_id_for(candidate)` (sha1 of user+dedupe_key) or `candidate.data["nudge_id"]`. Backend:
   create the `Nudge` with that id. Proposal: `NudgeCandidate.nudge_id: str = Field(default_factory=new_id)`.
7. **Learned IVR maps.** `CallAction.collected["ivr_map"]` / `friday.brain.ivr.learn_ivr_map()` emit the
   voice runner's replay format (`"replay: 2@english | 3@broadband | {Registered mobile}# | 9"`, no
   personal data); store it on `Business.ivr_notes` (shared). +1 to Voice's `CallBrief.ivr_map`.
