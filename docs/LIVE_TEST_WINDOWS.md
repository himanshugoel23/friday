# Friday live call test on Windows 11 (PowerShell)

Goal: Friday phones YOUR OWN mobile number from the Vobiz trial number and has a short real chat.
Friday can only call numbers you explicitly allow (see "Safety").

## 1. Install the tools (once)
Open PowerShell and paste each line:

```powershell
winget install Git.Git
winget install astral-sh.uv
winget install Cloudflare.cloudflared
```
Close PowerShell and open a new one so the tools are found.

## 2. Get the code
```powershell
git clone -b claude/friday-phase-1 https://github.com/himanshugoel23/friday friday
cd friday
```
(Git will ask you to sign in to GitHub in a browser window the first time, because the repository is private. No Git? On github.com/himanshugoel23/friday choose the branch `claude/friday-phase-1`, then Code, Download ZIP, unzip it, and `cd` into the folder.)

```powershell
uv sync
uv run friday init-env
```
`init-env` creates a file called `.env`, makes the secret keys for you and lists what is still empty.
It never overwrites an existing `.env`.

## 3. Paste your keys
```powershell
notepad .env
```
Fill in (after the `=`, no spaces or quotes):
- `SARVAM_TELEPHONY_AUTH_ID` and `SARVAM_TELEPHONY_AUTH_TOKEN` (Vobiz Auth ID / Token)
- `SARVAM_API_KEY`
- `ANTHROPIC_API_KEY` (real brain). No Anthropic credits? Add the line `FRIDAY_LLM_PROVIDER=fake`
  to test only the audio path (the replies are scripted).
- `FRIDAY_PILOT_ALLOWED_NUMBERS=+91XXXXXXXXXX` (your own phone)

Use FRESH keys (rotate them first), because the old ones were pasted in a chat. Never share `.env`.
The caller ID is already set to the Vobiz trial number +918065354620.

## 4. Start the tunnel (second PowerShell window)
```powershell
cloudflared tunnel --url http://localhost:8000
```
Leave it open. It prints an address like `https://something-random.trycloudflare.com`.
**This address changes every time you start the tunnel.** Put it in `.env`:
`FRIDAY_PUBLIC_BASE_URL=https://something-random.trycloudflare.com` (no slash at the end), save.

## 5. Check everything
Back in the first window:
```powershell
uv run friday doctor
```
Fix every `[FIX]` line. Also make sure the Vobiz account has **call queuing OFF** (ask Vobiz support if
doctor says it is on) and enough balance (a few rupees per test).
Optional dry run with no phone and no cost: `uv run friday livecall --to +910000000000 --simulate`

## 6. Make the call
```powershell
uv run friday livecall --to +91XXXXXXXXXX
```
Friday prints who it will call, the goal, the maximum length and the cost estimate, then asks you to
type `YES`. Your phone rings; answer and play a business: Friday introduces itself as an AI assistant,
asks two or three simple questions and ends politely. Options: `--max-seconds 120`, `--goal "..."`.

At the end you get a summary (outcome, duration, turns, languages, estimated cost) and the transcript is saved
in `var\livecalls\`.

**Stop early:** press Ctrl+C in that window (Friday hangs up).

## Cost
Roughly Rs 3-5 per minute in total (Vobiz about Rs 0.44/min plus Sarvam and the AI). A 3 minute test is
under Rs 15. Friday refuses calls longer than 5 minutes or above the Rs 25 spend cap
(`FRIDAY_PILOT_MAX_SPEND_INR`).

## What the messages mean
- "is not in your allowed list": add the number to `FRIDAY_PILOT_ALLOWED_NUMBERS` in `.env`.
- "setup problem: missing X": fill X in `.env` (names only are shown, never the values).
- "FRIDAY_PUBLIC_BASE_URL ... https": paste the tunnel address (it must start with https://).
- "/health is not reachable": the tunnel is not running or the address in `.env` is old.
- "could not start Friday on port 8000": close any other Friday window.
- "another live call seems to be running": wait, or delete `var\livecalls\livecall.lock` if sure.
- Phone never rings / call "failed": check Vobiz balance, call queuing OFF, and that a trial account may only
  dial allowed numbers (your own worked before).
- Dial status `no_answer` or `busy`: just try again.

## Safety
Friday can only call numbers you listed in `FRIDAY_PILOT_ALLOWED_NUMBERS` (empty by default), one call at
a time, never longer than 5 minutes. Recordings are off; nothing is saved except the local transcript. WhatsApp,
SMS and hotel features are simulated in this mode.
