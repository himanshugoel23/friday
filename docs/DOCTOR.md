# friday doctor: what each line means

Run it on the server, in the Friday folder:

    uv run friday doctor              # everything
    uv run friday doctor --offline    # nothing leaves the machine (skips internet checks)
    uv run friday doctor --json       # same result as data, for scripts
    uv run friday doctor --section database   # one part only

It never places a call, sends a message or spends money, and it never prints a password, key or token (only
the NAME of a setting and whether it is ok, missing or unsafe). The last line is `DOCTOR PASS` (exit code 0)
or `DOCTOR FAIL` (exit code 1). A WARN does not fail the run; a FAIL does. `[SKIP]` means "not checked here".

The older laptop checks (Python, uv, tunnel) are still available as `friday doctor --laptop`.

## Reading a line
`[ OK ]` fine. `[WARN]` works but fix it before launch. `[FAIL]` broken, fix it. `[SKIP]` not applicable or switched off by `--offline`.

## 1. settings
- `FRIDAY_MODE=simulator` (WARN): Friday is in practice mode, nothing real happens. Set `FRIDAY_MODE=live` in the env file when you are ready.
- `missing: NAME` (FAIL): that setting is empty. Add it to the env file and restart (`sudo systemctl restart friday`).
- `unsafe or invalid: ...` (FAIL): the setting exists but is a development default or the wrong shape (for example the secret key was never changed, or the public address is not https). Set a proper value.
- `components needed ... not implemented` (FAIL): the code on the server is older than the settings; update the code.

## 2. database
- `cannot connect` (FAIL): the database address or password in `FRIDAY_DATABASE_URL` is wrong, or this machine is not allowed in. Re-check the Supabase connection string.
- `migrations have never been applied` / `migration mismatch` (FAIL): the database is behind the code. Run `uv run python -m friday.db.migrate up`. The latest step must be `0010_chatbot` (chain 0006, 0007_consumer_calls, 0008_savings_engine, 0009_life_state, 0010_chatbot).
- `this code does not contain migration 0010_chatbot` (WARN): the server has an old copy of Friday. Update it.
- `N expected table(s) missing` (FAIL): the migration did not finish. Run the same `migrate up` command.
- `row level security is OFF on ...` (FAIL, Postgres/Supabase only): the tables are readable through Supabase's public key. Run `uv run python -m friday.db.migrate rls`.
- RLS `[SKIP]` on SQLite is normal for a test machine.

## 3. redis and object store
Only checked if `FRIDAY_REDIS_URL` / `FRIDAY_OBJECT_STORE_URL` are set. `not reachable` (FAIL): wrong address, a firewall, or the service is down.

## 4. public URL and WhatsApp handshake
- `must be an https:// URL` (FAIL in live): `FRIDAY_PUBLIC_BASE_URL` must be your real https address, not localhost.
- `GET /health could not be reached` (FAIL): Friday is not running (`sudo systemctl status friday`) or the domain does not point at this server.
- `HSTS header missing` (WARN): https works but the browser-safety header is not sent; add it to the web server.
- `handshake refused (HTTP 403)` (FAIL): the verify token Friday uses differs from `WHATSAPP_VERIFY_TOKEN` in the env file you are checking (usually the service was not restarted after changing it).
- `development default` (FAIL): `WHATSAPP_VERIFY_TOKEN` was never set. Put the same new value here and in the Meta app's webhook page.

## 5. providers (read-only)
- `ANTHROPIC_API_KEY` / `SARVAM_API_KEY is missing` (WARN): only presence is checked; no paid call is made.
- `Meta refused the token` (FAIL): the WhatsApp access token expired or cannot see this phone number. Create a new permanent system-user token in Meta Business settings and update `WHATSAPP_ACCESS_TOKEN`.
- `Meta could not be reached` (WARN): internet problem; try again.
- `Vobiz account readable: balance ...` (OK) with `Vobiz: ...` warnings: the account is readable; the warnings (call queue on, low balance, trial account) should be fixed with Vobiz before real calls. `could not be read` (FAIL): the Auth ID/token are wrong.

## 6. switches
Shows, never changes: `FRIDAY_MODE`, the four feature switches (`FRIDAY_CONSUMER_CALLS_ENABLED`, `FRIDAY_SAVINGS_ENABLED`, `FRIDAY_LIFESTATE_ENABLED`, `FRIDAY_GOOGLE_ENABLED`; off by default), how MANY numbers are on the test allow-list (never the numbers) and whether the vendor-call redirect is set. WARN: consumer calls are on but the allow-list is empty.

Also lists the human-like voice switches by name, ON or OFF (profile `FRIDAY_VOICE_PROFILE`, silent latency switches, audible `FRIDAY_HUMAN_*` elements, VAD backend with fallback note, streaming STT). WARN if silero is requested but the `vad` extra is missing (energy fallback). Details: docs/HUMAN_VOICE.md; `friday voice selftest` runs the offline checks.

## 7. off switch
Shows whether Friday is paused right now (WARN if paused; resume with `uv run friday pause --resume`). Then it tests the mechanism on a throwaway copy with a fake phone line: calls allowed, switch on, call refused, switch off. FAIL means the off switch cannot be trusted; do not go live and tell an engineer. Your real switch is never touched.

## 8. service (systemd)
Is the `friday` service active and when did it last write a log line (time only). `unit is failed/inactive` (FAIL): run `sudo systemctl status friday` and `sudo journalctl -u friday -n 50`. Skipped on machines without systemd.

## 9. receptionist (missed-call forwarding)
Read-only. Shows whether `FRIDAY_RECEPTIONIST_ENABLED` is on (off by default), how MANY users opted in (a count, never who), and the forwarding probe verdict from `var/receptionist/probe.jsonl` (redirecting number delivered in which key, NOT delivered, or probe not run). WARN when the switch is on but nobody opted in, no inbound number is set, or the probe says the redirecting number does not arrive (every forwarded call then takes the generic message-taker path). Details: docs/RECEPTIONIST.md section 3.
