# Friday

A JARVIS-style, proactive AI assistant for Indian consumers, reachable only through **WhatsApp, voice
calls and SMS** (no app). Friday *acts*: she places real phone calls to businesses, customer care and
hotels for you and your family, *remembers* you, and *nudges* you before you have to ask. She speaks
Hindi, English and Hinglish, always says she is an AI on a call, and never commits you to a booking
without your OK (unless you delegated it, within limits you set).

## Quickstart (offline, no keys, no network)

```bash
uv sync                                   # Python >= 3.11
uv run friday chat                        # talk to Friday as if on WhatsApp (fake LLM + simulated world)
uv run pytest                             # whole suite, no network
uv run ruff check .
uv run friday check                       # mode, resolved providers, which modules exist, live problems
uv run friday loadtest --users 1000 --calls 200   # S-11 load test on the simulator
uv run friday serve                       # API on http://127.0.0.1:8000 (/health, /webhooks/whatsapp, /sim/*)
```

In `friday chat` type as the user. `1`/`2`/`3` tap the buttons, `/pin 12.97,77.64` shares a location,
`/voice <words>` sends a voice note, `/contact +91...` a contact card, `/as <phone>` switches sender,
`/call <phone>` makes a business ring back. Try: `Looks Unisex Salon mein haircut book karo kal shaam`.

## Modes

| | `FRIDAY_MODE=simulator` (default) | `FRIDAY_MODE=live` |
|---|---|---|
| LLM | deterministic fake (`friday/brain/fake_llm.py`) | Anthropic (`ANTHROPIC_API_KEY`) |
| Telephony | simulated calls against `friday/simworld/world.json` | Vobiz via the Sarvam adapter (see below) |
| WhatsApp / SMS | in-memory channel / fake SMS | Meta WhatsApp Cloud API / MSG91 |
| Places, hotels | simworld | Google Places + Geocoding, Expedia Rapid (stub) |
| DB | SQLite | Postgres (`FRIDAY_DATABASE_URL`) |

`uv run friday check` refuses live mode until every required setting exists (names only are printed).
Live calling is **Vobiz-only for now**: the number rented inside Sarvam cannot stream audio to our server.
Live tests need a machine with normal internet access: the cloud sandbox cannot reach the providers.

## Architecture

`docs/ARCHITECTURE.md` is the source of truth. In short: `friday/core` (frozen contracts) -> `brain`
(LLM, policy, prompts) / `voice` (telephony, STT/TTS, call runner) / `tasks` (state machine engine,
number pool) / `channels` / `discovery` / `proactive` / `db` / `api`. All components are built through
the container (`friday/core/container.py`); one codebase, several deployments.

## Roles (`FRIDAY_ROLES`, CSV; `uv run friday worker --roles ...`)

| Role | Runs |
|---|---|
| `api` | webhooks (WhatsApp, voice), `/health`, admin, callbacks. Always wired. |
| `task` | inbound-message and message-send workers + the task engine (steps, timers, retries) |
| `voice` | claims `call.place` jobs and runs the calls (capacity-limited). **A deployment without `voice` never places a call.** |
| `proactive` | nudge engine (sharded) + daily retention job |
| `batch` | reserved |

## Environment variables (names only; secrets go in the environment or an untracked `.env`)

| Group | Names |
|---|---|
| Core | `FRIDAY_MODE`, `FRIDAY_ENV`, `FRIDAY_LOG_LEVEL`, `FRIDAY_PUBLIC_BASE_URL`, `FRIDAY_SECRET_KEY`, `FRIDAY_ROLES`, `FRIDAY_DATABASE_URL`, `FRIDAY_REDIS_URL` |
| Keys / encryption | `FRIDAY_PIN_PEPPER`, `FRIDAY_FIELD_KEY` or `FRIDAY_FIELD_KEY_ID` (KMS), `FRIDAY_INDEX_KEY`, `FRIDAY_OBJECT_STORE_URL`, `FRIDAY_ADMIN_TOKEN` |
| LLM | `ANTHROPIC_API_KEY`, `FRIDAY_LLM_MODEL`, `FRIDAY_LLM_FAST_MODEL` |
| Speech | `SARVAM_API_KEY` (STT/TTS), `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY` |
| Telephony (Vobiz) | `SARVAM_TELEPHONY_AUTH_ID`, `SARVAM_TELEPHONY_AUTH_TOKEN`, `FRIDAY_NUMBERS` or `SARVAM_CALLER_IDS`, `FRIDAY_TELEPHONY_PROVIDER` / `FRIDAY_TELEPHONY_ROUTE` (Twilio, Exotel, Plivo adapters also exist) |
| WhatsApp | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `FRIDAY_WHATSAPP_TEMPLATES` |
| SMS | `MSG91_AUTH_KEY`, `DLT_ENTITY_ID`, `FRIDAY_SMS_SENDER_ID`, `FRIDAY_SMS_DLT_TEMPLATES` |
| Discovery | `GOOGLE_PLACES_API_KEY`, `EXPEDIA_RAPID_API_KEY`, `EXPEDIA_RAPID_SHARED_SECRET` |
| Test only | `FRIDAY_TEST_PG_URL`, `FRIDAY_TEST_REDIS_URL` (contract tests), `FRIDAY_CHAT_LOG_LEVEL` |

`.env.example` lists every setting. Never commit `.env`.

## Documentation map

| Doc | What |
|---|---|
| `docs/BRIEF.md` | product brief and founder decisions (final) |
| `docs/PRD.md`, `docs/VISION.md` | detailed requirements, vision |
| `docs/ARCHITECTURE.md` | components, state machine, scale-out (section 10) |
| `docs/TASKS.md` | work breakdown and file ownership |
| `docs/SECURITY.md`, `docs/SECURITY_FIXES.md` | threat model, fix list, ops blockers |
| `docs/CORE_CHANGES.md` | frozen-core change log |
| `docs/SARVAM_QUESTIONS.md` | open questions for Sarvam / Vobiz |
| `docs/WORKFLOWS.md` | every user journey step by step, with what is simulated vs live |
| `docs/QA_REPORT.md` | test results, load test, bugs, go/no-go |
| `docs/LAUNCH_CHECKLIST.md` | what to do to run the first live pilot |
| `tests/e2e/README.md` | e2e suites and simworld coverage table |
| `tests/contracts/` | contract kit for JobQueue / Lock / Cache / RateLimiter / Idempotency |

## Tests

* `tests/<package>` unit tests per package; `tests/security` red-team and privacy tests.
* `tests/e2e` drives the real app on the simulator (about 1 minute, offline).
* `tests/contracts` runs the same contract against memory and SQL implementations; Postgres / Redis variants
  need `FRIDAY_TEST_PG_URL` / `FRIDAY_TEST_REDIS_URL`.
* Known bugs are strict `xfail`s with a `BUG-n` reason; see `docs/QA_REPORT.md`.
