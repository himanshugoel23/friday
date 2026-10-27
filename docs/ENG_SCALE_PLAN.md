# Friday: engineering scale plan (22 Oct 2026)

Status: proposal for the founder. "(A)" marks an assumption, "(?)" marks unknown. Nothing here is verified on a real vendor yet.

## 1. Today and its single points of failure
One VM (DigitalOcean droplet now; AWS Lightsail Mumbai planned) runs one Python process: API, task engine, live calls, Vobiz media WebSocket, mid-call questions. Postgres (Supabase planned) and Redis are optional; SQLite in dev. Live-call state is in memory. The Postgres job queue, locks, idempotency keys and role split (`FRIDAY_ROLES`) exist in code but the split is disabled.

Single points of failure:
1. The one process/VM: a restart or crash cuts every live call and loses pending mid-call questions.
2. One Vobiz account and carrier; one Sarvam account (STT/TTS/call-turn model); one OpenAI/Claude backend key.
3. One WhatsApp number; Meta can restrict it (AI-assistant policy, quality rating).
4. Kill switch is a file on the VM, so it is not fleet-wide.
5. Secrets (field key) live in one file; losing it makes the DB unreadable.
6. Backups are nightly only and the restore has never been drilled.

## 2. What breaks first
| Scale | First break | Then |
|---|---|---|
| 100 users (10 concurrent calls) | Vobiz channel/concurrency limit (?), trial account limits, the number pool, `max_concurrent_calls=5` default | Sarvam STT rate limits (one REST call per utterance plus speculative calls) |
| 1,000 users (100 concurrent) | One process: audio decode/VAD/TTS streaming on 2 vCPU (A: ~10-20 calls per vCPU); event-loop stalls raise reply latency past 1.5 s p95 | Sarvam/LLM 429s; DB connections without PgBouncer; Meta messaging tier (1K then 10K business-initiated conversations per 24h, Meta-controlled) |
| 10,000 users (1,000 concurrent) | Needs multi-worker voice, sticky routing, shared call state; Vobiz and Sarvam need enterprise contracts (?); number pool and per-number reputation | Postgres hot tables (`call_turns`, `messages`) need partitioning; template spend and Meta quality rating |

Rule of thumb (A): 10% of users active per day, 1 call per active user per day, peak = 5x average. At 1,000 users, expect 5-15 simultaneous calls, not 100. The 100/1,000 concurrent-call figures are 10,000-user territory.

## 3. Telephony design
- **Pool.** N Friday outbound numbers (Indian 10-digit, never 140-series) with health, warm-up caps and cooling (already in `NumberPool`). Pilot: 3-5 numbers. Rule of thumb (A): pool size ≈ peak open vendor tasks / 1 per vendor, plus 30% headroom.
- **One number per vendor plus open task.** A vendor never sees the same Friday number for two open tasks. The number is held until the task closes plus 7 days (founder to confirm). If none is free, the call WAITS in the queue; it never shares.
- **Callback key** = (vendor number, Friday number) maps to exactly one open task. If zero or several match: ask the caller for the user's name and topic, never read out private details; still unmatched: take a message to the ops queue, never guess. Vendor messages carry a reference code.
- **Inbound routing for the receptionist.** One shared inbound number; the user is identified by the redirecting number (Vobiz diversion field is UNKNOWN, needs the probe). No match: generic "take a message".
- **Caller ID.** Friday numbers only, never the user's number (spoofing is not allowed). Truecaller for Business/CNAP per number.
- **Per-number registration cost (?).** Vobiz rental, KYC/DLT per number, CNAP fee: ask Vobiz. Do not buy past the pilot pool until quoted.
- **Pool exhausted.** Queue by priority (callback-confirmations > user-waiting > scheduled > proactive), tell the user "will call within X", alert ops above 80% utilisation.

## 4. Workers, queues, state
- Postgres `SKIP LOCKED` job queue is enough to 10,000 users; do not add Kafka/SQS. Add Redis only for rate limits and shared call state.
- Roles: `api` (ack webhooks fast), `task`, `voice` (one call pinned per worker, sticky by call id), `proactive`. Voice autoscale on concurrent calls per worker.
- Move live-call session and pending mid-call questions into Redis/Postgres so any worker can receive the user's WhatsApp answer. This is the gate to more than one VM.
- Task state machine (exists) must be resumable: every transition persisted in the same transaction as its job (outbox); a crashed call becomes "retry or ask user", never silent loss.
- Idempotency: `dedupe_key` per job (`call:<task>:<attempt>`), `wa:<wamid>` on webhooks, per-user lock for one turn at a time. Retries: +1 h, +3 h, max 3 per day (founder rule); provider 429s re-queue with backoff; dead letters alert.

## 5. Observability
Per-call trace (task_id = trace id): STT/decide/TTS ms per turn, p50/p95, barge-ins, hold seconds, outcome. Cost ledger per call (telephony + STT + TTS + LLM, INR) and per user per month. Metrics: pickup rate per number and per vendor category, task success, queue depth, pool utilisation, 429s, WhatsApp delivery and quality rating, dead letters. Alerts: p95 over 1.5 s, spend over cap, number health drop, dead letters, Vobiz balance low. Kill switch must move from a file to a DB/Redis flag with levels: pause outbound, pause one number, pause all inbound, stop all; plus automatic trip on spam complaints or cost spike.

## 6. Data and privacy
DPDP: consent record per user, notice, grievance officer, India region only. Recordings OFF (founder); transcripts 30 days (A, matches SECURITY.md), summaries kept, messages 12 months, audit 3 years PII-free. Per-user data keys (envelope via KMS) so "delete everything" also shreds the key and honours backups through a tombstone replay. Vendors under zero-retention/DPAs before real users. Callers are third parties: store minimum, no cross-user learning. Retention job exists, KMS path is a skeleton.

## 7. Testing
Keep the simulator world (5,600 tests, 47 receptionist callers, 111 call sims) as the CI gate. Add: (a) replay harness feeding recorded STT transcripts and timing from real pilot calls into the policy; (b) load test with the real audio path (synthetic audio at 20/50/100 concurrent on a staging VM) not just the simulated one; (c) chaos: kill the process mid-call, drop Redis, 429 from Sarvam; (d) canary: 5% of calls on a new version, auto-rollback on latency/outcome regression; (e) weekly restore drill.

## 8. Roadmap
| Phase | Scope | Exit criteria |
|---|---|---|
| P0 Pilot (now) | 5-10 testers, 3-5 numbers, one VM, allow-list | 20 real calls without a safety incident; callback matching 100%; doctor PASS; restore drill done |
| P1 Solid single node (to ~200 users) | Postgres + PgBouncer, shared kill switch, ledger, dashboards | 99% calls complete; p95 reply under 1.5 s; cost per call known |
| P2 Two nodes (to ~1,000) | Call state in Redis, sticky WS routing, voice workers split, hot standby | A killed worker loses no task and no callback; 50 concurrent in a staged test |
| P3 Scale (to 10,000) | Autoscaling voice, partitions, enterprise contracts (Vobiz, Sarvam, Meta tier), regional failover | 200 concurrent for 1 hour at SLO; Meta tier upgrade confirmed |

Build next, in order:
1. Number-pool ledger with open-task holds and (vendor, Friday number) callback lookup.
2. Redirecting-number probe and inbound routing (live test).
3. Per-call cost ledger and trace dashboard.
4. DB-backed multi-level kill switch.
5. Restore drill and PITR on Postgres.
6. Call-queue with priority when the pool is full.
7. Call state and mid-call questions out of memory.
8. Replay-from-real-calls harness.
9. Real-audio load test.
10. Sticky routing and a second voice worker.
11. Per-user key envelope and key shredding on delete.
12. Alerts and on-call rota.

**Do NOT build yet:** Kafka/SQS, Kubernetes, multi-region, per-user numbers, microservices split, a read replica, our own STT/TTS hosting, a feature flag platform, payments, recordings.

## 9. Top 10 technical risks
1. Vobiz limits, spam policy on AI outbound, or an outage (single carrier). Mitigate: second carrier behind `RoutedTelephony`, ask Vobiz early.
2. Redirecting number not provided by Vobiz, so receptionist cannot identify users. Probe first.
3. Caller-ID blocked or labelled spam; pickup collapses.
4. In-memory call state: a restart kills calls and mid-call questions.
5. Sarvam rate limits or latency drift (first-audio 0.5-1.1 s measured, from a different network).
6. Wrong callback match leaks one user's data to a vendor.
7. Meta policy or quality rating cuts WhatsApp; no second channel (SMS off).
8. Cost per call unknown; runaway LLM or telephony spend.
9. DPDP: processors' retention, third-party call data, deletion across backups.
10. Untested restore and a lost field key means unreadable data.
