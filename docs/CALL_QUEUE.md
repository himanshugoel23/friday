# Friday's own outbound call queue

Package `friday/callqueue`. Switch `FRIDAY_CALL_QUEUE_ENABLED` (default **false**: the direct dial path is
unchanged and nothing is wrapped). No database migration: state is a local sqlite file.

## Why
The Vobiz account has `features.call_queue` ON and we cannot turn it off. Calls sent faster than the account
allows are queued at Vobiz and may be marked failed. So Friday paces its own calls and never sends Vobiz more than
it will accept.

## Where it sits
`install_call_queue(container)` (called next to `install_pause_guard` in `friday serve`, `friday worker` and the
pilot live-call path) replaces `telephony.place_call` on the container's telephony provider. Every dial path
(consumer calls, urgent escalation, front door, quotes, session) already goes through that one method, so all are
covered. The returned leg is a proxy (`QueuedLeg`) that behaves like the provider leg and releases the slot.

## Rules
- Limits: `FRIDAY_CALL_QUEUE_MAX_CONCURRENT` / `FRIDAY_CALL_QUEUE_CPS` if set, else the account values cached by the
  Vobiz probe (`friday check --live` writes `concurrent_calls_limit` and `cps_limit` next to the queue DB), else
  3 concurrent and 1 call start per second.
- A call waits until: fewer than max concurrent calls are in flight, the start gap since the last start has passed,
  no other call to the same destination is live, and it is the first eligible waiter (urgent before normal, then
  oldest). A busy destination does not block calls to other numbers.
- Urgent = request metadata `kind=urgent_escalation` or `priority=urgent`. Everything else is normal.
- The slot is released on: hangup, not answered/busy/voicemail, placement failure, the leg ending (caller hung up),
  cancel of the waiting task, or the deadline.
- Unanswered calls: if not answered at ring timeout + `FRIDAY_CALL_QUEUE_GRACE_S` (default 10) the watcher hangs the
  provider call up (`leg.hangup()` = Vobiz `DELETE /Call/{uuid}/`) and frees the slot.
- Max duration: a live call is hung up and freed at ring timeout + max call seconds + grace.
- Restart safe: state is in `FRIDAY_CALL_QUEUE_DB` (default `./var/call_queue.db`, WAL, shared by serve and worker).
  A slot whose deadline passed (a crashed process never released it) is reclaimed by the next grant attempt.
- Idempotent: key is `metadata["idempotency_key"]`, else task id + last 4 digits. A live (waiting or active) entry
  with the same key is never duplicated; a second enqueue is refused (`duplicate_call`).
- A waiting call gives up after `FRIDAY_CALL_QUEUE_MAX_WAIT_S` (default 900) with `queue_wait_timeout`.

## Guards that stay in force
The queue refuses (before enqueueing) any number outside the pilot allow-list (`pilot_dial_blocked`, i.e. real
calls only to the allow-listed founder number while in the pilot), and drops waiting calls when the kill switch
(`friday pause`) is on (the inner pause guard still applies at dial). The vendor-call redirect is applied upstream,
unchanged. The queue never alters the number.

## Privacy
Logs and metrics show only the last two digits (`...03`). The state file stores a truncated SHA-256 of the
destination (for the one-per-destination rule) and its last two digits, never the number.

## Observability
`friday/callqueue/metrics.py` counters: `enqueued, started, duplicate, cancelled, expired, reclaimed_stale,
ring_cancelled, max_duration_cancelled, refused_allowlist, released_<reason>`. `friday doctor` section 12 shows
on/off, limits and their source, waiting/active/stale counts, and warns when only defaults are used.

## Tests
`tests/callqueue/test_callqueue.py` (fake clock, fake telephony; no network, no calls).

## Not done
Counters are in-process (not exported to a metrics backend yet). The Vobiz probe cache is written only by
`friday check --live`. Real-line behaviour (Vobiz DELETE on a ringing call) is exercised only through the existing
Sarvam leg code, not against Vobiz.
