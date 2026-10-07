# Friday

A JARVIS-style, proactive AI assistant for Indian consumers — reachable only via
**WhatsApp, voice call and SMS**. Friday *acts* (places real phone calls to businesses,
customer care and hotels for you and your family), *remembers* you, and *nudges* you
before you have to ask. Hindi, English and Hinglish.

- Product brief: [`docs/BRIEF.md`](docs/BRIEF.md)
- Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Phase 1 tasks & file ownership: [`docs/TASKS.md`](docs/TASKS.md)

## Quickstart (no API keys needed)

```bash
uv sync                 # Python >= 3.11
uv run pytest           # tests (no network)
uv run ruff check .     # lint
uv run friday check     # mode, resolved providers, which modules are implemented
```

By default `FRIDAY_MODE=simulator`: phone calls, WhatsApp, SMS, places search and
hotels are simulated against a shared fake world (`friday/simworld/world.json`), and
the LLM/STT/TTS use deterministic fakes unless you set their keys.

### Run the simulator (placeholder — finalised by QA)

```bash
uv run friday initdb    # create tables in ./friday.db
uv run friday chat      # chat with Friday as if on WhatsApp
uv run friday serve     # API on http://127.0.0.1:8000 (/health, /webhooks/whatsapp, /sim/*)
```

### Going live

Copy `.env.example` to `.env`, set `FRIDAY_MODE=live` and the vendor credentials.
`uv run friday check` lists anything missing; the app refuses to start in live mode
with missing credentials. Never commit `.env`.
