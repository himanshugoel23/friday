# Phase 1 beta: decisions, 3-day plan and progress log

Single place for every decision taken while planning the first live beta, so the next session can
continue without re-deriving anything. Companion docs: `PRODUCTION_CHECKLIST.md` (go/no-go gate),
`LAUNCH_CHECKLIST.md` (provider setup), `DEPLOY_AWS.md` (how to deploy), `QA_REPORT.md`, `SECURITY_FIXES.md`.
Started 2026-10-08 ("day 1"). Update the log at the bottom as work lands.

## 1. Decisions

| # | Decision | Notes |
|---|---|---|
| D1 | **Goal: a friends-only beta live in 3 days** (5-10 consenting invited users), not a public launch. | Public launch additionally needs OPS-3 pen test, OPS-5 DPIA, OPS-6 breach runbook, KMS/WAF (see `PRODUCTION_CHECKLIST.md` s.3). |
| D2 | **Channels in phase 1: voice calls + WhatsApp. SMS is OFF.** | Considered "calls only" first, then reversed: WhatsApp stays. Reason it was not feasible: there is **no user-facing voice conversation** in the code (inbound calls only match *business call-backs*, `friday/api/callbacks.py`; onboarding, PIN, approvals, reports all run over WhatsApp). Calls-only would be new engineering (voice onboarding/consent/PIN by DTMF, voice approvals, call-back reports), not a 3-day job. |
| D3 | SMS off means: no DLT registration, no MSG91, no sender ID, no `FRIDAY_SMS_DLT_TEMPLATES`. | `friday check` shows `sms off DISABLED`; that is expected. A total WhatsApp delivery failure is only logged/audited as `undeliverable`. |
| D4 | **Everything outside the 24 h WhatsApp window needs an approved Meta template.** Submit all in English and Hindi on day 1 (table in `PRODUCTION_CHECKLIST.md` s.4.1): `friday_task_update_v1`, `friday_question_v1`, `friday_nudge_v1`, `friday_reengage_v1`, `friday_biz_request`, `friday_beneficiary_optin`. | Meta approval is the long pole. If not approved by day 3, mark circle opt-in and message-a-business flows "coming soon". |
| D5 | Fallback if Meta business verification slips: use the **Meta free test number** (max 5 allow-listed phones). | Enough for a tiny beta. |
| D6 | Beta scope limited to what is proven live: **bookings and enquiries**. Hotels, customer-care/IVR calls, call transfer ("connect me") and recordings stay **off / "coming soon"** until the Vobiz TODOs (O-2) are confirmed. | Hotels without Expedia keys are disabled in code; recordings forced off without an object store. |
| D7 | Run with `FRIDAY_PROFILE=beta`, `FRIDAY_INVITE_ONLY=true`, roles `api,task,voice` in **one process on one VM** (O-15: live-call state is in memory). Postgres + Redis from the compose file. | Never scale the `api` service; kill switch is `friday pause`. |
| D8 | Telephony is **Vobiz only**; the number rented inside Sarvam (+91 80 7158 2175) cannot be used. Need a dedicated number, upgraded account, call queuing OFF. | See `LAUNCH_CHECKLIST.md` s.1. |
| D9 | **LLM: Anthropic, with the repo's existing cost routing. Do not use the GPT provider for the beta.** Haiku 5.5 (`claude-haiku-5-5`, $0.10 / $0.50 per 1M tokens) for every background purpose (interpret, extract, summarize, compare, translate, nudge judgement...); Sonnet 5.5 (`claude-sonnet-5-5`, $2 / $10) only for live `call_turn`; Opus only on explicit escalation. Already the defaults (`DEFAULT_LLM_MODELS`, `friday/brain/routing.py`: effort `low` everywhere, small `max_tokens`, prompt caching, 60K-token per-task budget that downgrades to the cheaper model). Reasons: Haiku 5.5 is about 7x cheaper than the GPT light model the repo uses (`gpt-5.4-mini`, est. $0.75 / $4.50) for background work; `call_turn` is quality/safety critical (AI disclosure, never commit without approval, Hinglish) so it keeps Sonnet; GPT path has no batch API and is less tested. Prices from the cached Claude model table (2026-10-06) and the repo's own GPT price estimates, which are unverified. Prices to re-check at https://platform.claude.com/docs/en/about-claude/pricing. **Live-call checks (day 1):** read the per-purpose token/cost log lines; confirm `call_turn` is not truncated at `max_tokens=400` (thinking tokens count toward it on Sonnet 5.5/Haiku 5.5; raise to ~800 if `stop=max_tokens` shows up); try Haiku 5.5 for `call_turn` (`FRIDAY_LLM_MODELS='{"call_turn": "claude-haiku-5-5"}'`) if quality holds in the test calls, as it would cut LLM cost per call by about 20x. Telephony minutes will probably dominate cost anyway. Set a monthly spend limit on the Anthropic key. Needs 30-day retention terms check for ZDR (OPS-2). **Trial exception (2026-10-09):** the founder already has Sarvam and OpenAI keys but no Anthropic key, so the free trial (D13) may run on OpenAI (`OPENAI_API_KEY`; `FRIDAY_LLM_PROVIDER=auto` picks it when it is the only LLM key; models `gpt-5.4-mini` / escalation `gpt-5.4` are the repo defaults and unverified: if the API rejects a model name set `FRIDAY_OPENAI_MODELS`). Re-decide before the beta using measured quality and cost from real calls. |
| D10 | All old API keys are treated as leaked (pasted in chats): **rotate and recreate** before the beta; set monthly spend limits. | `PRODUCTION_CHECKLIST.md` 1.3. |
| D11 | Docker image is built from the repo `Dockerfile` **on the server** (`deploy/update.sh`). The cloud sandbox cannot pull `ghcr.io`, so use `deploy/build_sandbox.sh` there (see s.4). | |
| D12 | **Hosting: not AWS.** Both AWS accounts available (066899195555, 405449670622) are managed sandbox accounts inside AWS Organizations with an SCP that explicitly denies Lightsail (`AccessDenied ... lightsail:CreateKeyPair ... service control policy`); not suitable and not ours to override. Use an India-region VPS instead (DigitalOcean Bangalore recommended): Ubuntu 24.04, 4 GB / 2 vCPU, `deploy/lightsail-launch.sh` works as first-boot user data (now creates the `ubuntu` user if missing). Backups: `deploy/backup.sh` accepts `BACKUP_ENDPOINT_URL` for S3-compatible storage (e.g. DO Spaces). A fresh standalone AWS account (root sign-in, no organization) remains a valid alternative using `deploy/aws/cloudshell_provision.sh`. |
| D13 | **Free first live call: GitHub Codespaces + Cloudflare quick tunnel + the `pilot` profile**, no server or laptop needed. Proves the call loop only (not WhatsApp/Postgres/Docker stack). Guide: `docs/TRIAL_CODESPACES.md`. The real beta still needs an India-region server (D12). |

## 2. Three-day plan

**Day 1 (2026-10-08): first real end-to-end loop**
- Founder, morning (long-lead items): submit Meta templates (en + hi) and start business verification; upgrade Vobiz
  account, top up, buy dedicated number, call queuing OFF; rotate keys + spend limits; point the domain at the server.
- Engineer: build the Docker image (**done**, s.4); provision Lightsail/AWS box (`deploy/lightsail-launch.sh`,
  `DEPLOY_AWS.md`); run `deploy/update.sh` + `deploy/smoke_test.sh`; `friday check` until "live configuration: OK"
  (SMS unset); LLM decided (D9: Anthropic); start on the Meta test number.
- Evening milestone: WhatsApp the test number, onboard, ask for a call to your own phone, get the call and the
  WhatsApp report (`LAUNCH_CHECKLIST.md` s.7 steps 1-7).
- Send the Vobiz questions (`SARVAM_QUESTIONS.md`) today; replies gate day 2.

**Day 2: harden**
- Resolve what can be verified of the Vobiz `TODO` markers in `friday/voice/telephony/sarvam.py` (hangup causes,
  codec/endianness, DTMF). Anything unconfirmed stays disabled for testers (D6).
- Repeat the live flow twice: onboarding, a booking with approval, a business call-back, an inbound call,
  "delete everything". Grep logs for leaked PINs/numbers.
- Fix what the first live run breaks.
- Founder: publish privacy policy, terms, Grievance Officer page and set `FRIDAY_TERMS_URL`, `FRIDAY_PRIVACY_URL`,
  `FRIDAY_GRIEVANCE_EMAIL`; request vendor ZDR/DPA terms in writing (Anthropic/OpenAI, Sarvam, Vobiz, Meta, Google);
  verify `friday/discovery/data/official_numbers.json`; name the on-call person.
- Medium bugs (O-19): approval questions never expire; "2 AM" window display bug.

**Day 3: go/no-go and invite**
- Morning: dress rehearsal with 2-3 internal users; test kill switch (`friday pause`), `update.sh --rollback`,
  backup, cost view; run `pytest` + `ruff` on the deploy commit (O-14).
- Gate: live flow passes twice, no secrets in logs, legal URLs live, vendor terms requested.
- Afternoon: invite 5-10 friends (invite-only on, caller warm-up caps on); watch live that evening.

## 3. Risks

1. Meta business verification / template approval may not finish (D5 is the fallback). Nudges and late reports outside
   24 h need approved templates.
2. No SMS safety net: a Meta restriction stops all text delivery (O-10); calls still work. Accepted for friends-only.
3. Vobiz trial limits or its AI-voice/spam policy could block outbound calls.
4. First-run live surprises (webhooks, media WebSocket, Hinglish STT latency) usually cost half a day.
5. The compose stack, Postgres/Redis path and `smoke_test.sh` have never been run (O-17).

## 4. Docker image: what was verified (2026-10-08)

Built `friday:beta` (477 MB, Python 3.12, non-root uid 10001). Checked: `friday --help`, `serve` boots in simulator
mode and `/health` returns `{"status":"ok"}`, no proxy CA in the final image, and with `FRIDAY_MODE=live
FRIDAY_PROFILE=beta` `friday check` refuses to start listing 20 missing items (expected with no secrets).
LLM, telephony, STT/TTS, WhatsApp, directory, geocoder, task engine and number pool components all load; SMS and
hotels show as disabled (expected).
**Not verified:** full pytest suite, production compose stack (Postgres/Redis/Caddy), `smoke_test.sh`, migrations
on Postgres.

**Cloud-sandbox build quirk.** The repo `Dockerfile` copies `uv` from `ghcr.io/astral-sh/uv:0.8.17`; the Claude cloud
sandbox's egress policy blocks that blob host (403), and build containers do not trust the sandbox proxy CA. On a
normal server the repo Dockerfile works as is. In the sandbox use `deploy/build_sandbox.sh`, which builds from a
temporary Dockerfile that installs the same `uv` from PyPI and trusts `/root/.ccr/ca-bundle.crt` in the builder
stage only (it never reaches the runtime image; TLS verification is never disabled). Start the daemon first with
`dockerd &` if needed.

## 5. What `friday check` needs for the beta profile

LLM key; Sarvam API key; Vobiz `SARVAM_TELEPHONY_AUTH_ID`/`_AUTH_TOKEN` + `FRIDAY_NUMBERS`; WhatsApp token, phone
number id, app secret and a non-default verify token; Google Places key; https `FRIDAY_PUBLIC_BASE_URL`; Postgres
`FRIDAY_DATABASE_URL`; `FRIDAY_SECRET_KEY`, `FRIDAY_PIN_PEPPER`, `FRIDAY_FIELD_KEY` (or KMS id), `FRIDAY_INDEX_KEY`,
`FRIDAY_ADMIN_TOKEN`; `FRIDAY_TERMS_URL`, `FRIDAY_PRIVACY_URL`, `FRIDAY_GRIEVANCE_EMAIL`; `FRIDAY_INVITE_ONLY=true`.
Template: `deploy/env.production.example`. Never commit secrets.

## 6. Open items / next steps

Verified in the sandbox (2026-10-08): full pytest 1209 passed / 28 skipped, `ruff check` clean, image builds and boots,
Alembic migrations reach head `0003_task_role` on Postgres 16, contract tests 52/52 on real Postgres + Redis, compose
file validates. Not verifiable from the sandbox: the repo Dockerfile (ghcr.io blocked; works via `deploy/build_sandbox.sh`),
the full compose stack (Docker Hub rate limit), live providers, SSH to a server (outbound port 22 blocked).

- [x] D9 decided (Anthropic); [ ] confirm `call_turn` token budget (`max_tokens=400`) and quality in the first live calls.
- [x] Docker image built and smoke-checked; [x] migrations verified on Postgres; [x] tests and lint green (commit `505d4aa`).
- [x] Hosting: AWS accounts blocked by org SCPs (D12); server provider TBD (DigitalOcean Bangalore recommended).
- [ ] **Free trial call (D13): follow `docs/TRIAL_CODESPACES.md`** - needs Anthropic + Sarvam keys and an upgraded Vobiz account with a number.
- [ ] Provision the real server; first `update.sh` + `smoke_test.sh` run; fix what breaks (O-17).
- [ ] Meta: verification, templates submitted, test number wired to the webhook.
- [ ] Vobiz: upgrade, number, queuing off, answer/hangup URLs, questions sent (`SARVAM_QUESTIONS.md`).
- [ ] First live call to the founder's phone (day 1 milestone) and the day 2 repeat runs.
- [ ] Legal pages, vendor terms, verified care numbers, on-call person.
- [ ] Rotate all keys that were ever pasted in chats; set spend limits.
- [ ] Possible later work: a real user-facing voice channel (voice onboarding/approvals) if a calls-only product is wanted.

## 7. Log

- 2026-10-08: reviewed repo state and docs; decisions D1-D11; Docker image built and smoke-checked in the sandbox.
- 2026-10-09: AWS blocked by organization SCPs on both provided accounts; switched hosting to an India-region VPS (D12).
- 2026-10-09: added the free Codespaces trial guide (D13); next: get Vobiz upgraded + keys, run the first live call.
- 2026-10-09: status refresh of section 6; repo in sync with origin/claude/friday-phase-1.
- 2026-10-09: founder has Sarvam + OpenAI keys; trial will use OpenAI (D9 exception). Keys live only in the Codespace `.env` / Codespaces secrets, never in chat or the repo.
