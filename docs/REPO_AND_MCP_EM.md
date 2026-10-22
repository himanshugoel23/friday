# Friday: architecture, MCP and repo plan (EM review, 2026-10-22)

Read-only audit. Facts come from the tree: 29 packages in `friday/`, ~140k lines, 251 test files with 3,162 test functions, 11 Alembic migrations (`friday/db/migrations/versions/0001..0011`), 80 distinct `FRIDAY_*` names in `friday/core/config.py`, 109 across the code, 77 docs files (not 300; the pain is quality, not count), `docs/HANDOFF.md` at 930 lines, **no `.github/` at all: no CI, no CODEOWNERS, no PR template**. `deploy/supabase/schema.sql` is a second schema next to Alembic (drift risk).

## 1. Target architecture

Flow: `channel in -> classifier -> project manager -> agent -> tool -> outcome out`.

| Layer | Today | Rule |
|---|---|---|
| L0 core | `core`, `db` | No imports from above. Config, clock, events, models, repos. |
| L1 domain | `tasks`, `lifestate`, `savings`, `quotes`(models), `calls`(models, gate, dnc, approval) | Pure rules and state machines. No network. |
| L2 tools | `connectors`, `google`, `scouting`, `discovery`, `vendors`, telephony | Each tool = one port + real + fake. |
| L3 agents | `pm`, `brain`, `playbooks`, `receptionist`, `liveagent`, `chatbot` | Decide and call tools through the tool bus only. |
| L4 channels/voice | `channels`, `voice`, `api`, `chatbot_media` | Translate wire format to events. No business logic. |
| L5 wiring | `integration`, `ops`, `cli` | The only place that imports everything. |

Dependency rule: a layer imports only downward. Agents never import `voice` or `channels`; they emit events and call ports. Today `receptionist` imports `voice` and `liveagent` (9 imports), and `quotes` imports `api` and `brain`: both break the rule.

**Service boundaries (3, no more before pilot):**
1. `api` (webhooks: WhatsApp, SMS, telephony). Fast, stateless, only enqueues.
2. `worker` (PM, agents, connectors, scouting). Pulls jobs from the queue (Postgres `tasks/outbox.py` first; Redis only when needed).
3. `voice` (live call media, WebSocket, latency-critical, own process, own scaling).

Everything else is a module inside these. **Sync only** for: webhook ack, live-call turn (voice), cheap classifier. **Async** for everything with a vendor, a browser, a wait or a retry. State lives in the DB only (matches the founder rule: the phone is never needed). Idempotency key on every inbound message and every tool call. Outbox pattern for sends (already in `tasks/outbox.py`).

## 2. MCP, defined properly

**Principle:** one tool contract for everything. Internal capabilities are in-process by default, exposed as MCP only when a boundary needs it. `connectors/registry.py` already ranks backends `official_mcp > deep_link > scripted_browser > llm_browser` with status and kill switch: keep it, it is the right idea. Today there is no MCP client or server in code (only that registry mentions it).

**Remote vs in-process:**
- In-process (a Python `ToolBus` using the same JSON schemas): calls, whatsapp send, memory/life state, savings, calendar. Reason: same DB transaction, no network hop, simple tests, no extra auth surface.
- Remote MCP server: browser connectors (heavy, needs Chromium, crash isolation, own scaling), Swiggy/Zomato official MCP, Personal Agent Protocol later. Reason: isolation, different release speed, vendor owns them.
- Rule: every tool has a JSON schema, so moving one in-process tool to a remote MCP server is a config change, not a rewrite.

**Capability map (tool name, level):**
`calls.place` (irreversible), `calls.status` (read), `places.search` (read), `quotes.collect` (reversible), `whatsapp.send` (irreversible), `calendar.list` (read), `calendar.create` (reversible), `browser.<site>.search` (read), `browser.<site>.cart` (reversible), `browser.<site>.pay` (irreversible, always user OTP), `memory.get/put` (read/reversible), `savings.check` (read). External: `swiggy.*`, `zomato.*`.

**Approval levels:** L0 read: auto. L1 reversible: auto inside user limits, logged. L2 irreversible (money, call to a third party, message to a third party, booking): needs a stored consent or a fresh yes from the user; this extends the existing `calls/approval.py` and `calls/gate.py` into one policy engine. Allow-list for real numbers stays hard-coded in the gate.

**Per-user auth/consent:** table `tool_grants(user_id, tool, level, limits_json, expires_at)`; Google already has OAuth in `friday/google`. Tokens stored encrypted (`core/crypto.py`), never in tool args.

**Audit:** table `tool_audit(id, ts, user_id, task_id, tool, version, args_hash, level, decision, cost_paise, result_status)`. Append-only. Args are scrubbed (reuse `connectors/scrub.py`).

**Limits:** per user per day and per tool count and rupee cost, enforced in the bus before dispatch; a global kill switch per tool (reuse `FRIDAY_CONNECTORS_KILL` idea for all tools).

**Versioning:** `name@major` in the schema; additive changes only inside a major; old major kept 1 release.

**Discovery:** agents never hard-code tools. At start, the bus gives each agent a filtered catalogue (`tools/list`) by agent role, user grants and live status. Agent prompt sees only that list.

**Fakes:** every tool package has `real.py`, `fake.py` and one shared contract test that runs against both (`tests/contracts/` exists, extend it). Fakes are deterministic, can inject failure, and are the default in tests and sim (`simworld`, `calls/fakes.py`, `brain/fake_llm.py` are the seeds). Real tests are marked `live`.

**Example definitions (shortened):**
```json
{"name":"calls.place@1","level":"irreversible","input":{"type":"object",
 "required":["task_id","to_e164","playbook"],"properties":{"task_id":{"type":"string"},
 "to_e164":{"type":"string","pattern":"^\\+91[0-9]{10}$"},"playbook":{"type":"string"},
 "mode":{"enum":["quote_only","book"]}}},"output":{"required":["call_id","status"]}}
{"name":"places.search@1","level":"read","input":{"type":"object","required":["query","lat","lng"],
 "properties":{"query":{"type":"string"},"lat":{"type":"number"},"lng":{"type":"number"},
 "limit":{"type":"integer","maximum":20}}},"output":{"required":["places"]}}
{"name":"whatsapp.send@1","level":"irreversible","input":{"type":"object",
 "required":["to_e164","template","vars","idempotency_key"]},"output":{"required":["message_id"]}}
```

## 3. Repository

**Audit findings:**
- **Overlap:** `calls` (4.2k lines) = call lifecycle, gate, DNC, approval. `quotes` (3k) = quote flow, with its own `calls.py`, `flow.py`, `sim.py`, `dbmodel.py`. `liveagent` (6.6k) = in-call brain; `receptionist` (3.4k) sits on top of liveagent and imports `voice`. `pm` (2.3k) plans, but `quotes/flow.py` and `tasks/engine.py` also orchestrate. Three orchestrators = one too many. `brain` (14.9k, largest) mixes front door, LLM clients, handlers, reports. `voice` is 13.5k and has 109 imports of `core`, fine, but leaks into `brain`/`playbooks`. `chatbot` vs `chatbot_media`, `lang_dev` vs `brain/lang.py`, `learning` vs `quality`: unclear owners.
- **Config sprawl:** 109 `FRIDAY_*` names read directly in modules (`os.environ` in `connectors/registry.py` etc.), not only via `core/config.py`. No registry of flags, no owner, no expiry.
- **Tests/lint:** layout mirrors packages (good); ruff only, no mypy, no import rules. Stray: root `friday.db`, `deploy/*probe*.py`.
- **Migrations:** numbered 0001-0011, linear, good. Risk: two builders adding 0012 at once; `deploy/supabase/schema.sql` duplicates.
- 
**Target layout:** `friday/{core,db,domain/{tasks,lifestate,savings,calls,quotes},tools/{calls,places,whatsapp,calendar,browser,memory,savings,fakes},agents/{pm,receptionist,liveagent,brain},channels/{whatsapp,sms,voice},app/{api,worker,cli}}`. Move by `git mv` in small steps; leave a re-export shim for one release.

**Conventions:** snake_case modules, one public port per `ports.py`, dataclasses/pydantic at boundaries, full typing on `domain` and `tools` first (mypy strict there, lenient elsewhere), add ruff `S` (bandit) and `PTH`. **import-linter** contracts in `pyproject.toml`: layers (L0..L5) and "agents must not import channels/voice". Start in report-only mode with today's violations as an allow-list that can only shrink.

**Governance:** `docs/adr/NNNN-title.md` (ADR template; first ADRs: layers, tool bus, one orchestrator, queue choice). `.github/CODEOWNERS` per package, `.github/pull_request_template.md` (tests, secrets check, flag, migration, docs, hear-before-change audio link).

**CI (GitHub Actions, none today):** ruff + format check; mypy (scoped); pytest not-live with Postgres service; import-linter; **gitleaks + `detect-secrets` on every push (public repo)**; pip-audit + bandit; migration check (single head, `alembic upgrade head` then `downgrade -1` on fresh DB, compare to model metadata); markdown link check; fail if `.env`, `var/`, `*.db` staged.

**Release/branching:** trunk `main` (protected, PR + green CI). Short-lived `feat/<owner>/<topic>` branches. **One branch = one owner**: each Claude session is given its own branch and its own git worktree (`EnterWorktree`); a session never pushes to a branch it did not create. Server-side: branch protection forbids force-push, requires PR. Locally: pre-push hook refuses if `git rev-parse --abbrev-ref @{u}` has commits not by this session's trailer. The 2026-10-22 accident (see `backup/vendor-wip-2026-10-22`; also "WIP: builders in progress" commits on one branch) came from many writers on `claude/friday-phase-1`. Release: tag `v0.x` from main, deploy from tag, rollback = previous tag.

**Flags:** `friday/core/flags.py` + `docs/flags.yaml`: name, owner, default, type (kill/rollout/experiment), created, remove-by date. CI fails if code reads an unregistered `FRIDAY_*` or a flag is past remove-by.

**HANDOFF.md:** cap at 150 lines: product rules, standing rules, current state, next 5 steps. Move history to `docs/handoff/YYYY-MM.md` (append-only log) and decisions to ADRs. CLAUDE.md rule "update HANDOFF at start of every task" becomes "append one line to the monthly log".

## 4. Migration plan (each step: full suite green, own PR)

| # | Step | Risk | Effort |
|---|---|---|---|
| 1 | Add `.github` (CODEOWNERS, PR template), CI with ruff+pytest+gitleaks, branch protection, worktree-per-session rule | Low | 0.5d |
| 2 | Split HANDOFF into short file + monthly log; move sections to ADRs | Low | 0.5d |
| 3 | `flags.py` + `flags.yaml`; route `os.environ` reads through it; CI check | Low | 1d |
| 4 | import-linter report-only with current violations frozen | Low | 0.5d |
| 5 | Migration CI check; drop or generate `deploy/supabase/schema.sql` from Alembic | Med | 1d |
| 6 | Add `ToolBus`, schema + audit table + fakes, wrapping 2 existing tools (`places.search`, `whatsapp.send`) in-process | Med | 3d |
| 7 | Wrap `calls.place` with policy engine (merge `approval`/`gate`); same tests, new path | High | 3d |
| 8 | Fix 3 layer violations (`receptionist -> voice`, `quotes -> api/brain`) via ports | Med | 2d |
| 9 | Pick ONE orchestrator (`pm` + `tasks.engine`); `quotes/flow.py` becomes a PM plan | High | 5d |
| 10 | Move connectors behind the bus; browser connectors as a separate remote MCP process | Med | 3d |
| 11 | mypy on `domain` and `tools`; ruff `S` | Low | 2d |
| 12 | `git mv` packages to target layout with shims | Med | 2d |

**Do NOT before pilot:** steps 9 and 12 beyond the first; no queue swap to Redis/Kafka; no splitting `voice` further; no rewrite of `brain`; no new service beyond the three; no renaming of DB tables; no change to spoken lines (hear-before-change).

## 5. Top 10 risks

1. Parallel sessions writing one branch (repeat of 2026-10-22). No CI is the root.
2. Secret leak in a public repo; only a manual rule today.
3. Irreversible actions (real calls, WhatsApp to third parties, payment) spread over several gates; one missed path = harm.
4. Three orchestrators give inconsistent state and double calls.
5. Layer leaks make every refactor risky (receptionist/voice/liveagent coupling).
6. 109 undocumented env switches: wrong prod config, untestable combinations.
7. Schema drift: Alembic vs `supabase/schema.sql`; two builders on migration 0012.
8. Live-voice latency and vendor (Sarvam, telephony) outage with no fallback tested.
9. Browser connectors break silently when sites change; scraping/ToS and OTP-handling legal risk.
10. Knowledge is in one 930-line file and in chat; a new session misses rules, and cost per user is not capped by tool.
