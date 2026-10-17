# Zomato explore run: runbook for the founder

A supervised, real-site test of the Zomato food connector. You log in with YOUR OWN number and type YOUR
OWN login code. The run stops before any order and never pays. Purpose: record what the real pages look
like so the locators in `friday/connectors/food/zomato_live.py` can be tuned (they are all guesses today).

## Safe and unsafe
- Safe: Friday searches, opens a Domino's page, reads the menu, logs in, and stops. With `--add-item "name"` it
  also adds that one dish, shows the cart and the pay screen (QR / UPI link) and stops there.
- It never clicks anything called pay / place order / confirm order / cash on delivery (hard block in code),
  and no place-order tool exists. No payment code, PIN or card is ever requested.
- The login number is the first entry of `FRIDAY_PILOT_ALLOWED_NUMBERS` on the server. It is never printed
  (only the last two digits), logged, saved, or put in a screenshot or trace.
- Your login code goes only through the one-time page below: memory only, used once, never logged, never
  shown to a model, never in a screenshot or trace.
- Unsafe: typing the code anywhere else, pasting it in chat, running this for someone else's number, or
  leaving the watch link public (screenshots show page content such as addresses; the link is the password).
- Zomato's terms may forbid automation and a login from a cloud server may trigger extra checks or a block.
  Use your own account, once, and expect it might stop. The run never tries to get around a block.

## Before you start (once)
1. On the server, make sure `FRIDAY_PILOT_ALLOWED_NUMBERS` in `/opt/friday/.env` starts with your own +91 number.
   If it is empty the run exits with a clear message and does nothing.
2. Dry run on the fake site (no zomato.com, no real number): `sudo bash /opt/friday/deploy/zomato-explore.sh --fake`.
   It installs Xvfb if missing (prints the apt command), finds Chromium (installs one only if none is found, and
   says so) and lets you practise the code page: the fake test code is shown on screen.

## The real run
1. `sudo bash /opt/friday/deploy/zomato-explore.sh` (add `--add-item "Margherita"` only if you want the cart /
   pay-screen part; add `--hold 600` to keep the watch page up after the end).
2. It prints the **WATCH PAGE** link. Open it on your laptop or phone. Pages are plain http on port 8765 bound to
   127.0.0.1, so open them through an SSH tunnel: `ssh -L 8765:127.0.0.1:8765 you@server`, then use the printed
   link as is. Alternative: `--watch-host 0.0.0.0 --public-url http://SERVER:8765` (needs the port opened to
   you only; plain http, less safe), or `FRIDAY_PUBLIC_URL`.
3. You will see steps appear with screenshots: open site, location, search, first Domino's result, menu, login.
4. When it says "Zomato should now text a login code to the number ending ..XX" it prints the **CODE PAGE**
   link (valid 10 minutes, one use). Open it, wait for Zomato's SMS, type the digits, press the button. You
   see "Done". You have 5 minutes. Friday types the code into the site and confirms the login.
5. The run ends with `RESULT: done` or `RESULT: blocked` plus a plain-English REASON.
6. Stop it any time with Ctrl-C (or `sudo pkill -f zomato-explore`); the browser closes and the links die.

## What can stop the run (all clean, all recorded)
CAPTCHA / bot check, "access denied" or HTTP 403/429/5xx, an empty page, a missing button or field (layout
differs from the guesses), the site refusing the number, no code within 5 minutes, a wrong or expired code.
Each writes `blocked_reason` (code + explanation) to `state.json` with a screenshot. No retry loops.

## What to send back
1. `sudo -u friday uv run --directory /opt/friday friday connectors pack-run /opt/friday/var/connectors/zomato-explore/<timestamp>`
   (the script prints the exact line). It writes `<folder>-pack.zip`: state.json, per-step screenshot, page title,
   sanitised visible text, an outline of buttons/fields (no typed values), the menu if read, and the trace of the
   part BEFORE login. Text is scrubbed again (phone numbers, code-like strings, tokens). The after-login trace
   (session cookies) is left out on purpose.
2. Send the zip to the lead. Look at one screenshot first if you like: inputs appear as pink boxes.
3. Do NOT share: the login code, your phone number, the CODE PAGE link, the WATCH PAGE link, `.env`, anything
   from `storage_state` or the after-login trace.

## Files in a run folder (`var/connectors/zomato-explore/<timestamp>/`, gitignored)
`state.json`, `report.html`, `menu.json` (if read), `steps/NN-name/{screenshot.png,text.txt,elements.json,meta.json}`,
`trace-1-before-login.zip`, `trace-2-after-login.zip`. The traces are two separate sessions; none runs from just
before the phone is typed until the login is confirmed.

## Still unverified
- Every locator (`CANDIDATES` in `food/zomato_live.py`): location box, search, result link, menu rows, login
  button, phone / code fields, verify button, cart, proceed-to-pay, QR / UPI link. The log records which candidate
  matched (names only).
- Whether Zomato blocks a cloud IP or headless/xvfb Chromium, shows a CAPTCHA, or needs a different login screen
  (e.g. split code boxes: the code is typed key by key to cope, untested on the real site).
- That the "logged in" check (login button and code field gone) is right on the real page.
- Menu parsing from visible text (veg flag is a guess), the cart summary and the pay screen.
- Site terms and the legal read; session reuse across runs (nothing is saved: each run logs in fresh).

## From an iPad or phone (no SSH tunnel) - founder approved 2026-10-17
1. Use the DigitalOcean web console inside tmux (it disconnects when you switch tabs; tmux keeps the run alive):
   `tmux new -As explore`
2. Once: `sudo git -C /opt/friday pull --ff-only` then `sudo bash /opt/friday/deploy/explore-https.sh`
   (adds an `/explore/*` route to Caddy; it prints the next command).
3. `sudo bash /opt/friday/deploy/zomato-explore.sh --public-url https://<your-host>/explore`
   Open the printed WATCH PAGE and CODE PAGE links in Safari. Every link carries a secret token; do not share them.
4. When finished: `sudo bash /opt/friday/deploy/explore-https.sh --off` removes the route again.
Reattach after a disconnect with `tmux attach -t explore`.

## Probe mode: "is it even working?" (no number, no code, nothing to watch)
`sudo bash /opt/friday/deploy/zomato-explore.sh --probe` opens zomato.com, tries the location and search, opens a
restaurant and reads the menu, then stops. It never logs in, never needs your phone number, and never asks for a code.
Then run the `pack-run` line it prints and send the zip.
First sandbox probe (16-17 Oct, cloud IP, not your server): the home page loaded (HTTP 200) but it is an app-promo
page ("Order on app", app-store buttons) with NO search box; city and restaurant pages were cut off with
ERR_HTTP2_PROTOCOL_ERROR, and swiggy.com answered with a challenge. So it is not yet known whether Zomato's website
allows ordering at all, or whether a server address is let through. The server probe answers that.

Geography check (17 Oct): this sandbox's address is in the US (Ohio, Google Cloud). A browser set up like an Indian user
(en-IN language, Asia/Kolkata timezone, a Gurgaon location) made no difference: Zomato city and restaurant pages still
reset the connection, so it looks address-based, not settings-based. The Bangalore server is the proper Indian-address test.
