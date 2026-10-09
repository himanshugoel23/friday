# Free trial: first live call from GitHub Codespaces (no server, no laptop)

Decision D13 in `BETA_PLAN.md`. Use this to try Friday for free, from a phone or tablet browser, before paying
for a real server. It uses the existing **pilot profile** (`FRIDAY_PROFILE=pilot`, `friday init-env | doctor |
livecall`, see also `LIVE_TEST_WINDOWS.md` which is the same flow written for Windows).

## What it proves, and what it does not

* Proves: the real call loop (Vobiz telephony + Sarvam speech + the LLM): Friday rings **your own number**, says
  she is an AI first, mirrors Hindi/English/Hinglish, and the call quality and latency are acceptable.
* Does NOT prove: WhatsApp, Postgres/Redis, the production Docker stack, Caddy/HTTPS, backups, multi-user flows.
  Those need the real server (see `DEPLOY_AWS.md`, or any India-region VPS; D12 in `BETA_PLAN.md`).
* Pilot mode needs only: LLM key, Sarvam key, Vobiz credentials + a number you own, the generated secrets, and an
  https public URL. WhatsApp/SMS/hotels fall back to simulators and recordings stay off. It may only dial numbers in
  `FRIDAY_PILOT_ALLOWED_NUMBERS`, and refuses if the estimated spend is above `FRIDAY_PILOT_MAX_SPEND_INR` (25).
* A Codespace sleeps after about 30 minutes idle and the free tunnel address changes on every start, so this is for
  trying only. GitHub's free Codespaces quota (about 120 core-hours a month on a personal account, so about 60 hours
  on a 2-core machine) can change: check github.com/settings/billing.

## Accounts and keys needed (a few rupees per test call)

| What | Where | Env name |
|---|---|---|
| LLM | console.anthropic.com (new key, set a monthly spend limit) **or** an OpenAI key (the repo auto-selects whichever is set; if both, set `FRIDAY_LLM_PROVIDER`) | `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` |
| Speech | Sarvam dashboard | `SARVAM_API_KEY` |
| Telephony | Vobiz console: trial upgraded, balance topped up, one number you own, call queuing OFF | `SARVAM_TELEPHONY_AUTH_ID`, `SARVAM_TELEPHONY_AUTH_TOKEN`, `FRIDAY_NUMBERS` |
| Allowed target | your own mobile, E.164 | `FRIDAY_PILOT_ALLOWED_NUMBERS=+91XXXXXXXXXX` |

Set the caller ID to the founder's own Vobiz number in the Codespace `.env`, e.g. `SARVAM_CALLER_IDS=+918064267861` (nothing is pre-set; `friday doctor` names it as missing).

Put keys only in the Codespace `.env` (or Codespaces secrets: repo Settings -> Secrets and variables -> Codespaces). Never paste keys into chat or commit them. `.env` is git-ignored. Create fresh keys (old ones were shared in chats).

## Steps (all in a browser)

1. github.com -> the repo -> **Code** -> **Codespaces** -> **Create codespace on `claude/friday-phase-1`**
   (2-core machine). The editor and a terminal open in the browser.
2. Terminal:
   ```bash
   pip install uv
   sudo curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && sudo chmod +x /usr/local/bin/cloudflared
   uv sync
   uv run friday init-env        # creates .env with random secrets, lists what is still empty
   ```
3. Open `.env` in the editor. Fill the empty names listed above and set `FRIDAY_MODE=live`, `FRIDAY_PROFILE=pilot`.
4. Second terminal tab: `cloudflared tunnel --url http://localhost:8000` prints `https://<random>.trycloudflare.com`.
   Put that in `.env` as `FRIDAY_PUBLIC_BASE_URL` (https, no trailing slash). It changes on every restart.
5. In the first tab: `uv run friday doctor` (read-only checks; fix what it names), then optionally a free dry run
   `uv run friday livecall --to +910000000000 --simulate`.
6. The real call: `uv run friday livecall --to +91XXXXXXXXXX` (your own number). Your phone rings from the Vobiz number.
   Expect the AI disclosure first, language mirroring, an honest answer to "are you a bot?". Logs go to `var/livecalls/`.

## The front door: YOU call Friday (`--listen`)

Same Codespace, same tunnel, same `.env`, but the call goes the other way: you ring Friday's Vobiz number
from your own phone (a number in `FRIDAY_PILOT_ALLOWED_NUMBERS`) and talk to her. Details, limits and
safety: `FRONT_DOOR.md`.

```bash
bash deploy/codespace_call.sh --listen      # tunnel + .env + `friday listen`
```
It starts Friday, runs the read-only checks against the live address, finds or creates the Vobiz
application `friday-front-door` (answer and hangup URL = the current tunnel address), links
`SARVAM_CALLER_IDS[0]` to it (remembering what the number rang before), prints `Call +91... now`, and serves
calls until you press Ctrl+C. After each call you get a summary (caller masked, outcome, duration,
languages, estimated cost, transcript file under `var/livecalls/`). On exit the previous link is restored.

* Free dry run, no phone, no network, no cost: `bash deploy/codespace_call.sh --listen --simulate`
  (or `uv run friday listen --simulate`).
* If the Codespace died before it could restore the link (the number would ring a dead address): run
  `uv run friday listen --restore` (or put the old application back in the Vobiz console).
* What to try: call, listen for the AI disclosure, say your name (first time), "Hindi", "haan", then
  "Looks Unisex Salon mein haircut book karo kal shaam" (Friday reads it back and waits for your yes).
  Ask "are you a bot?". In the live pilot Friday says honestly that she cannot phone real businesses yet.
* Only numbers in `FRIDAY_PILOT_ALLOWED_NUMBERS` are served; anyone else hears one short polite AI-voice
  message and is hung up (no AI cost). Max 180 s per call, one call at a time, spend cap
  `FRIDAY_PILOT_MAX_SPEND_INR`.
* Do not run `friday listen` and `friday livecall` at the same time (one live call at a time).

## If it fails

* `FRIDAY_PUBLIC_BASE_URL ... https`: paste the current tunnel address. `/health is not reachable`: the tunnel is
  not running or the address in `.env` is stale. Another live call seems to be running: wait, or delete
  `var/livecalls/livecall.lock` if sure.
* Vobiz rejects the call: trial accounts restrict destinations and caller IDs; upgrade the account. Record the
  rejection text in `LIVE_TEST_ISSUES.md`.
* Free alternatives for a real (always-on) server later: Oracle Cloud Always Free (Mumbai; sign-up often fails with
  Indian cards, capacity is scarce) or Google Cloud's $300 trial credit (Mumbai). A paid India VPS is the safest.
