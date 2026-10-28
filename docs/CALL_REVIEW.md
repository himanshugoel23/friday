# Call review (founder test calls)

Lets the developer read how the voice bot talked on the founder's own TEST calls, without a console.

- Route: `GET /ops-status/<token>/calls?n=5` (plain text, n default 5, max 20). Same token and the same
  404 as the other ops-status routes.
- CLI (on the server): `friday calls review --n 5`.
- Switch: `FRIDAY_OPS_CALL_REVIEW_ENABLED` (default false). `deploy/enable-web-test.sh` turns it on
  (`off` turns it off) and prints the NAME only, never a value.

## What it shows
Per call: short call id, start time (UTC), outcome and dial status, answered duration, phone masked to
the last 2 digits, metrics already stored (hold seconds, languages heard, turn count, ASR confidence
average and minimum, per-turn confidence), and the turn-by-turn transcript (`speaker: text`),
decrypted on the server by the normal field cipher. Latency and barge-in counts are NOT stored per
call today, so they are not shown (add them to the call row first if wanted).

## Privacy note
- Founder/tester test calls only: a call is shown only if its destination is in
  `FRIDAY_PILOT_ALLOWED_NUMBERS` or `FRIDAY_CHATBOT_TESTERS`. Any other number is never shown.
- A call whose `collected` data carries `real_vendor` or `third_party` is skipped.
- Redacted before output: e-mails, digit runs of 4-8 digits (OTP-like), long key-like tokens.
- Total output capped at 40 KB (last part cut with a marker).
- Off by default. Kill it by unsetting the switch (or `enable-web-test.sh off`) and restarting the
  service: the route then answers 404 and the CLI refuses.
- Plaintext transcripts leave the server over the token-protected route: keep the token secret.

Code: `friday/ops/callreview.py`, `friday/api/opsstatus.py`. Tests: `tests/ops/test_callreview.py`.
