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

---

## 2026-10-07 — Stage 3 merge log (EM)
Merged into `friday/core` additively; old import paths keep working. Workarounds above
can now be removed (owners in docs/TASKS.md §Stage 3).

**Backend Engineer A**
| Request | Status |
|---|---|
| `Notifier` Protocol | **Merged** `interfaces.Notifier` (as proposed). |
| `TaskEngine` Protocol | **Merged** `interfaces.TaskEngine`. Return types are `Any` (the engine returns `Task`/plans). `handle_unknown_caller` is documented as an optional extra and is not in the Protocol, so `isinstance` keeps working. |
| `InboundCallReceived` / `MissedCallReceived` events | **Merged** into `core.events`. `friday.voice.events` re-exports them, so it is the same class. |
| `CallResult.from_number`, `OutboundCallRequest.from_number` | **Merged.** |

**Backend Engineer B**
| Request | Status |
|---|---|
| `Task.role` | **Merged** as `str | None` with `TaskRole` constants. Drop the `[friday:role=…]` notes tag. |
| `Business.alt_phones` | **Merged.** Also on `BusinessCandidate` for directory results. |
| `BusinessCandidate.hours` | **Merged.** |
| `CallBrief.from_number` | **Merged.** Also `number_changed` for the "calling from a new number" line. |
| `Settings.friday_numbers` + `tasks_*` policy | **Merged.** Env `FRIDAY_NUMBERS` (CSV or JSON) and `FRIDAY_TASKS_*` (same names as `TaskPolicy`). |
| CallSessionRunner `run_inbound` / `cancel` | **Merged** as separate Protocols `InboundCallRunner` / `CancellableRunner`. The runner doesn't implement `cancel` yet, so adding it to `CallSessionRunner` would break `isinstance`. |
| Repository extras | **Merged** as typing-only methods on the repository Protocols. |
| `WellbeingAlertRaised` | **Merged** into `core.events`. `friday.tasks.events` re-exports it. |

**Voice Engineer**
| Request | Status |
|---|---|
| Telephony routing settings / factories | **Merged.** `TelephonyProviderName` += `routed`, `sarvam`. Live + `auto` → `routed`. Adds `telephony_route` (CSV env `FRIDAY_TELEPHONY_ROUTE`), `exotel_subdomain`, `exotel_voicebot_app_id`, `exotel_caller_ids`, `sarvam_telephony_*`, `sarvam_caller_ids`, `inbound_claim_timeout_s`, `sim_time_scale`. `live_problems()` requires one fully configured route provider. FACTORIES adds `routed` and `sarvam`. |
| `capabilities()` / `take_inbound()` on `TelephonyProvider` | **Merged as a separate Protocol** `InboundTelephony` plus helper `telephony_capabilities(provider)`. The simulator has no `capabilities()`, so putting them on `TelephonyProvider` would break `isinstance`. |
| Events `CallCostReport`, `CallLatencyReport`, `CallLanguageSwitched` | **Merged** into `core.events` (re-exported by voice). |
| `OutboundCallRequest.from_number`, `CallBrief.from_number`/`ivr_map`, `CallTurn.audio_class`, `CallResult` cost fields, `Transcription.duration_s` | **Merged.** `VoiceCallResult` can now drop its duplicate fields. |
| `SimBusiness.alt_phones` | **Rejected for now.** The simworld schema is frozen for this wave. Keep the `sim:alt_phones=` persona directive (QA may propose it in wave 2). |

**AI Engineer**
| Request | Status |
|---|---|
| `CallBrief.direction` / `CallBrief.inbound`; `InboundContext`, `RelatedTask` | **Merged** into `core.models`. `friday.brain.inbound` re-exports them, so it is the same class. |
| `Brain.build_inbound_brief` | **Merged** (sync, signature as implemented). |
| `ConversationContext.identifiers` | **Merged.** |
| Cost / routing settings | **Merged** as `llm_models` (per-purpose defaults: Haiku; `call_turn` → Sonnet), `llm_default_purpose_model`, `llm_escalation_model`, `llm_task_token_budget`, `llm_prompt_caching`, `llm_batch_enabled`, `Settings.model_for(purpose)`. **Not changed:** `llm_model` / `llm_fast_model` defaults stay as before (`tests/brain/test_llm.py` pins them). They are legacy fallbacks; brain routing should use `model_for`. |
| Button helpers `c:` / `r:` | **Merged** as `choice_button_id`, `ref_button_id`, `parse_any_button_id`. `parse_button_id` is deliberately **unchanged** (still None for `c:`/`r:`/`ob:`) so the API keeps routing those to `brain.interpret`. |
| `Intent.FORGET` + `Interpretation.forget_fact_ids` | **Merged.** |
| `NudgeCandidate.nudge_id` | **Merged** (default `new_id()`). Backend: create `Nudge(id=candidate.nudge_id)`. |
| Learned IVR maps | **Merged** via Voice's `CallBrief.ivr_map`. Keep storing the replay line on `Business.ivr_notes`. |

**New in Stage 3 (EM)**
- `core.safety`: SECURITY-1/2/24, `check_key_sequence`, `KeyBuffer`, `check_commit` (SECURITY-27).
- `core.crypto`: SECURITY-12 primitives (`KeyProvider`, `LocalKeyProvider`, `KmsKeyProvider` skeleton, `FieldCipher`, `EncryptedText` / `EncryptedJSON`, blind index).
- Security config: SECURITY-17/26/30. `AccountIdentifier` value check (SECURITY-31). Log redaction (SECURITY-26).
- Caller-ID pool contracts: `FridayNumber`, `NumberStatus`, `NumberHealth`, `NumberLimits`, `NumberChoice`, `NumberOutcome`, the `NumberPool` Protocol and `number_*` settings.
- Scale-out: `core.scale` (`JobQueue`, `Outbox`, `DistributedLock`, `Cache`, `RateLimiter`, `IdempotencyStore` plus in-memory impls), role settings, `ROLE_COMPONENTS` / `JOB_ROUTES` in the container.

## 2026-10-08 — Voice Engineer, Stage 3 wave 2 (Sarvam-only, security, scale)
All voice work compiles against merged core; these are follow-ups, each with a local workaround.
1. **Telephony default = Sarvam only (founder 2026-10-08).** `Settings.telephony_route` default should
   be `["sarvam"]` and `resolve_telephony()` `auto` -> `"sarvam"` (not `routed`). Until then the routed
   builder (`friday/voice/telephony/routing.py::default_route`) uses Sarvam only unless
   `telephony_provider="routed"` (then `telephony_route` is honoured) or `exotel`/`twilio` is selected.
   Add `sarvam_verified_capabilities: CsvList = []` (e.g. `bridge_transfer`) - read with `getattr` today.
2. **`object_store` component** (`friday.db.objectstore:build_object_store_component`) is not in
   `FACTORIES`. The runner calls `c.get("object_store")` (None if absent -> recordings keep the provider
   URL; simulator `file://` kept). Add it to FACTORIES and to `ROLE_COMPONENTS["voice"]`.
3. **`safety.looks_like_commitment(text)`** (SECURITY-3): voice carries its own copy in
   `friday/voice/commit.py` so it never imports `friday.brain`; please move one detector into core and
   have both import it. Also `CallAction` has no field for the resolved slot start, so the runner reads
   `collected["slot_at"]` (ISO-8601) and `collected["decision"]` ("slot,price") for `check_commit` -
   propose `CallAction.slot_at: datetime | None`.
4. **`TelephonyProvider.delete_recording(url)`** (SECURITY-14) is implemented on every voice provider
   (raises `ProviderError` on failure); add it to `InboundTelephony`/a `RecordingTelephony` Protocol.
5. **Provider signals**: `CallResult.collected["provider_signal"] = "blocked"|"rejected"` and
   `CallResult.error` containing "blocked"/"rejected" (what `engine._number_outcome` reads today). A typed
   `CallResult.carrier_signal: str | None` would remove the string matching.
6. **Job kind `call.inbound`** is routed to the voice role in `JOB_ROUTES` but `TaskEngine.handle_job`
   only knows `call.place`; `VoiceWorker` therefore claims only `call.place` (inbound calls arrive as bus
   events + `take_inbound`).

---

## 2026-10-08 — Wave 2 integration pass (EM)
**Voice Engineer, Stage 3 wave 2**
| # | Request | Status |
|---|---|---|
| 1 | Sarvam-only default: `telephony_route` default `["sarvam"]`, `auto` → `"sarvam"`, `sarvam_verified_capabilities` | **Merged.** `resolve_telephony()` returns `sarvam` for `auto` in live. `routed` is explicit opt-in. `.env.example` sets `FRIDAY_TELEPHONY_PROVIDER=sarvam`. `live_problems()` requires `SARVAM_TELEPHONY_AUTH_ID/TOKEN` and a caller-ID pool (`FRIDAY_NUMBERS` or `SARVAM_CALLER_IDS`). |
| 2 | `object_store` in FACTORIES and voice role | **Merged** (+ proactive role, `Container.object_store`). Live also requires `FRIDAY_OBJECT_STORE_URL`. |
| 3a | `safety.looks_like_commitment` | **Merged** (moved from `friday/voice/commit.py`, which re-exports it). `friday/brain/guards.py` still has its own copy: the AI Engineer should import the core one. |
| 3b | `CallAction.slot_at` | **Merged.** The voice `slot_of` reads it first and falls back to `collected["slot_at"]`. |
| 4 | `RecordingTelephony` Protocol (`delete_recording`) | **Merged** as its own Protocol, not on `InboundTelephony` (not every provider has inbound). |
| 5 | `CallResult.carrier_signal` | **Merged** (`"blocked"` / `"rejected"` / None). Engine's `_number_outcome` can switch from string matching to this field. |
| 6 | Job kind `call.inbound` | **Rejected.** No consumer exists. Inbound calls arrive as `InboundCallReceived` bus events plus `take_inbound` in the process that hosts the webhook (role `api`). `JOB_ROUTES` keeps the name reserved for a cross-process design. |

**Backend A**
| Request | Status |
|---|---|
| `build_object_store(settings)` | **Merged** as FACTORIES `object_store` → `build_object_store_component`. |
| Pool settings to `Database` | **Merged.** `Container.db` passes `db_pool_size`, `db_max_overflow`, `db_pool_timeout_s` explicitly. |

**Role wiring (`friday/api/runtime.py`, `friday/tasks/engine.py`, `friday/cli.py`)**
* `Runtime.start` starts loops per `Settings.roles`: `task` → inbound/message-send worker loop + task engine; `voice` → `build_voice_worker(c)`; `proactive` → proactive engine + a daily retention loop (`repos.retention.run`, once per IST day via the idempotency key); `batch` → reserved (logged); `api` → none.
* `TaskEngine.claim_calls` (default `True`) is set to `False` by the runtime when a voice worker owns `call.place`, so the engine no longer claims it. A voice-only process builds the engine only for `handle_job`.
* New `friday worker --roles voice,task`: background roles without the HTTP server (SIGTERM drains).
* `friday check` lists roles and the components each role needs. In live mode it prints every missing or unsafe setting by name and exits 1.

## 2026-10-08 — Voice integration engineer (real Sarvam / Vobiz docs)
Proposals for `friday/core/config.py` (frozen; additive, none needed to run today):
```python
sarvam_tts_model: str = "bulbul:v3"      # "bulbul:v4-flash" is also accepted (female personas per language)
sarvam_tts_speaker: str = "ritu"         # CHANGE the default from the deprecated bulbul:v2 name "anushka"
sarvam_stt_model: str = "saaras:v4"      # saarika:v2.5 is retired
sarvam_stt_keyterms: CsvList = []        # <= 50 domain terms (saaras:v4 only)
```
Workaround in place: the TTS adapter reads `Settings.sarvam_tts_model` if present, else the env var `FRIDAY_SARVAM_TTS_MODEL`, else `bulbul:v3`. A non-female or legacy v2 speaker (the current `anushka` default) is replaced by `ritu`, so nothing breaks before core changes. `friday/cli.py` got a tiny `friday check --live` flag (read-only Vobiz account probe, `friday.voice.telephony.vobiz_probe`).
Also for ops: `.env.example` should say `FRIDAY_SARVAM_CALLER_IDS` must be numbers ON the Vobiz account (trial: `+918065354620`); `friday check --live` flags a mismatch.

## 2026-10-09 — Front door: people calling Friday's number (Voice / Backend)
Additive only; merged by the same change (`friday/core` stayed backwards compatible, no signature changed).

| # | Change | Where |
|---|---|---|
| 1 | `CallMode.FRONT_DOOR = "front_door"`: a person calls Friday's number and talks to Friday (the safety checks in `core.safety` use a `CallBrief` in this mode for what Friday says) | `core/models.py` |
| 2 | `CallerKind` (`user` / `business` / `unknown`): result of the caller classification on every answered inbound call | `core/models.py` |
| 3 | `Settings.pilot_block_business_calls: bool \| None` (None = automatic: pilot profile AND live mode), `Settings.pilot_blocks_business_calls` and `Settings.pilot_dial_blocked(phone)`: in a live pilot the engine refuses to phone any number not in `FRIDAY_PILOT_ALLOWED_NUMBERS` | `core/config.py` |
| 4 | `Settings.frontdoor_*`: `enabled`, `open_signup`, `pilot_max_call_s` (180), `max_call_s` (300), `per_caller_per_hour` (3), `per_caller_per_day` (10), `global_per_hour` (40), `max_silences` (3), `max_concurrent`, `spend_cap_inr`, `result_callbacks` | `core/config.py` |

Not core, but behaviour changes other owners should know about:
* `SarvamTelephony.handle_stream_message` now publishes `InboundCallReceived` in a background task. The event handler runs the WHOLE call (front door or business call-back); awaiting it inside the WebSocket receive loop meant no media frame could be read until the call was over. Test: `test_inbound_event_handler_does_not_block_the_media_receive_loop`.
* `TaskEngine` refuses to dial in `_outbound_guard` and `_call` when `settings.pilot_dial_blocked(phone)`: the task fails with `PILOT_NO_REAL_CALLS` ("In this test mode I cannot phone real businesses yet..."). Before this change the pilot allow-list was only enforced by `friday livecall`.
* `CallbackService.front_door` (set by `Runtime`) classifies answered inbound calls before the business call-back path; "legacy" decisions (business call-memory match, or an unknown caller outside the pilot with `frontdoor_open_signup` off) take the unchanged path.
