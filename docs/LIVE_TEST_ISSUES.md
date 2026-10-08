# Live test issues (adapter / platform)

Found while building the laptop harness. Nothing here was fixed outside the harness files.

| File | Symptom | Suggested fix |
|---|---|---|
| Vobiz account (not code) | `features.call_queue` is ON: outbound calls may be queued and marked failed | Ask Vobiz to turn call queuing OFF before the live test (`friday doctor` reports it) |
| `friday/voice/telephony/sarvam.py` | Trial account may restrict who can be dialled; a number that is not the founder's own may fail with no clear message | Surface Vobiz's rejection text in `ProviderError` |
| `friday/voice/session.py` | `CallRunner.cancel(task_id)` is a polite wrap-up request; if the media socket never opens (tunnel wrong) the call only ends at the ring/answer timeouts | `livecall` enforces its own hard deadline (max-seconds + ring timeout + 45 s) and cancels the task; a Voice-side hard hang-up on cancel would be cleaner |
| `friday/db/objectstore.py` | `build_object_store` raises in live mode without `FRIDAY_OBJECT_STORE_URL`; the call runner swallows it (`_optional`) so recordings are simply off | None needed for the pilot; keep this behaviour |
| `friday/api/app.py` | `/health` is the only public liveness route, so `friday doctor` can only prove the tunnel works while `friday serve`/`livecall` is running | Fine; documented in the guide |
