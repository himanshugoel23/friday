# Consumer call test: Friday calls your own phone (runbook for the founder)

This is the first real call of the "call someone for me" feature, pointed at your own allow-listed phone. It walks the real path once: request, approval (you type YES), the safety gate, a real Vobiz call, the live conversation engine, then the report. Nothing else can be called: Friday refuses any number that is not on your allow-list.

Code: `friday/integration/telephony.py` (the production line), `friday/integration/call_test.py` (the command), `deploy/consumer-call-test.sh` (the wrapper). Tests: `tests/integration/test_consumer_telephony.py`, `tests/integration/test_call_test_cli.py` (all offline, fakes only). Every line the command prints is in `friday/integration/copy.py` (`CALL_TEST`) and is PENDING your approval, like all wording.

## 1. Before you start (all must be true)
- [ ] `friday doctor` shows PASS on the server (docs/DOCTOR.md).
- [ ] Vobiz account is topped up and a caller ID number is assigned to it (the number goes in `SARVAM_CALLER_IDS` or `FRIDAY_NUMBERS`; doctor checks it is set).
- [ ] These names are set in the server's `.env` (names only here; you type the values on the server, never in chat):
  - `FRIDAY_MODE=live` and `FRIDAY_PROFILE=pilot`
  - `FRIDAY_PILOT_ALLOWED_NUMBERS` = your own phone, like `+91XXXXXXXXXX` (the only number the test may call)
  - `FRIDAY_CONSUMER_CALLS_ENABLED=true`
  - `FRIDAY_PUBLIC_BASE_URL` = the https address of the server (Vobiz calls back into it during the call)
  - optional, for the first test: `FRIDAY_VENDOR_CALL_REDIRECT_TO` = your own phone (it must also be on the allow-list; the allow-list is checked against the number really dialled)
- [ ] The kill switch is off (`friday pause --status` says RUNNING).
- [ ] It is inside the calling window (Indian time): 08:00 to 21:30 for `--who family|friend`, 09:00 to 19:00 for `--who provider`. Outside it Friday refuses and dials nothing.
- [ ] You have not already used up the per-number limits for your own number (3 calls a day, 6 a week; each test call counts as one).

## 2. Rehearse first (no phone, no cost)
```
bash /opt/friday/deploy/consumer-call-test.sh --dry-run
```
It pulls the code, runs the whole path against a pretend callee and prints the plan, the summary and a transcript path. The front door stays up. If this fails, do not go on; send back the last 20 lines.

## 3. The real call
```
bash /opt/friday/deploy/consumer-call-test.sh
```
Useful options (all optional): `--who family|friend|provider` (default friend), `--goal "your own words"`, `--name "Himanshu"` (how your name is said), `--callee-name "Name"`, `--max-seconds 90`, `--whatsapp-report` (also send the report on WhatsApp). Example:
```
bash /opt/friday/deploy/consumer-call-test.sh --who friend --goal "main das minute mein pahunch raha hoon"
```
What happens, in order:
1. It pulls the latest code and stops the front door (`systemctl stop friday`; the call needs the same port). It starts it again when it ends, even on an error or Ctrl-C.
2. It shows **the plan**: who, the goal, what Friday says and asks, **the exact first thing you will hear**, the caller ID (masked), the maximum length (150 seconds, a hard cap; set `FRIDAY_CALLS_TEST_CALL_SECONDS` to change it, 300 at most) and an upper-bound cost (about Rs 12.5 for 150 seconds).
3. It asks `Type YES to place the call:`. Anything but exactly `YES` cancels, and no call is placed.
4. Your phone rings from the Friday caller ID. Answer and talk. Friday opens with the approved first line (greeting plus the line that says she is a virtual assistant calling for the user). **No recording notice is ever played** (your decision; recording is off in the pilot profile anyway).
5. When the call ends it prints the **CALL SUMMARY** and the report Friday would send on WhatsApp (printed only, unless you used `--whatsapp-report`).

What you will hear first is the line printed under "FIRST THING YOU WILL HEAR". It comes from the same code that speaks it, so the text you see is the text you hear (the wording is still pending your approval; the default test message too).

## 4. How to stop
- **Ctrl-C** in the window: hangs up, closes the request, starts the front door again.
- **Kill switch** from a second window: `friday pause`. It stops new dials, and during this test it also ends the call in progress at Friday's next turn (the result is "partial", never retried). Resume with `friday pause --resume`.
- **`sudo systemctl stop friday`**: stops the front door. If the script is running it cannot restart it for you; start it yourself afterwards (`sudo systemctl start friday`).
- Friday also ends the call by itself at the length cap (plus a 15-second backstop) and when the callee hangs up.
- Or just hang up your phone: the call ends as "failed" and is NOT redialled (the test never retries).

## 5. What to send back
Only the summary lines, nothing else:
```
Dial status / Duration / Turns / Languages / Reply gap (p50, p95) / Safety blocks / Outcome / Estimated cost
```
plus anything you heard that was wrong (a pause, a repeated line, a wrong word). Numbers in the output are masked to the last two digits. **Never send keys, the `.env` file, or a full phone number.** The transcript and a masked JSON call log are written on the server under `/opt/friday/var/consumer_calls/` (not in git); send the transcript text only if you are happy to.

## 6. If it refuses
It prints `REFUSED: ...` and dials nothing. The usual ones: number not on the allow-list; `FRIDAY_MODE` not live; `FRIDAY_PROFILE` not pilot; `FRIDAY_CONSUMER_CALLS_ENABLED` not true; kill switch on; outside the calling window; per-number limit reached; a setup problem from doctor (missing key names are listed, never values); the public address not reachable from the internet.

## 7. NOT verified (nobody has placed this call yet)
- A real Vobiz call from this code path: the answer, the audio stream, hang-up events, and the call being cleared by Friday's hang-up.
- Real latency and the reply gap with your switches (streaming speech to text, early commit, end-of-turn, voice-activity backend) on this path.
- Hindi/Hinglish speech recognition on your voice on a phone line; barge-in on a real line.
- Voicemail and busy detection on a real network (the mapping is tested with fakes; the machine detection setting is the existing one).
- That a caller ID from `FRIDAY_NUMBERS` / the number pool is accepted by Vobiz for this account, and how your phone shows it.
- Recording references: off in the pilot profile, so the store-and-retention path is only tested with fakes.
- The opening line and the default test message have not been heard or approved by you.
- The "kill switch ends a call in progress" and "backstop" behaviours on a real call (tested with a scripted line only).
- Postgres: the test creates a local test user row for your number if none exists; only SQLite was tested.
- The WhatsApp report with `--whatsapp-report` outside the 24-hour window (templates).

## 8. Decisions for you
1. **Pilot profile only.** The real line is built only for `FRIDAY_PROFILE=pilot` in live mode. Beta/default profiles keep the refusing line until you say otherwise.
2. **Kill switch mid-call.** Today `friday pause` also ends a consumer call in progress (the older rule was "calls in progress finish"). Keep, or let them finish?
3. **No automatic retry** for the test call (it would call you again an hour later). Normal consumer calls still retry +1 h, +3 h.
4. **Local test user.** If no Friday user has your number, the command creates one (active, no profile). Alternative: refuse until you have messaged Friday on WhatsApp.
5. **Default test message** (said to you if you give no `--goal`): "Friday abhi test chal raha hai, aap mujhe aaram se sun sakte hain." Pending your approval; change it in `copy.py` after you hear it.
