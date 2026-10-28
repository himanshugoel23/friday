# Friday Web channel (28 Oct 2026)

A WhatsApp-style chat page on the server's own https address, with the REAL Friday behind it: the same inbound pipeline
as the WhatsApp webhook (dedupe, queue, onboarding, consumer router, task engine), the real LLM, real Places search, real
CallGate and real Vobiz/Sarvam calls. It exists because Meta WhatsApp is blocked. It is **not** the Chat Lab (that one is a
simulator); and it is **not** a public launch: named testers only (today: the founder and his wife).

Code: `friday/webchat/` (page = the Chat Lab page with the dev panel never sent). Tests: `tests/webchat/`. Switch:
`FRIDAY_WEB_CHANNEL_ENABLED` (default **off**).

## What it can and cannot do

- **No Meta/WhatsApp send, ever.** While the switch is on, `c.messaging` IS the web channel (no network code in it; a test patches
  httpx to fail and runs a chat) and SMS is the fake. A message to anyone who is not an active tester is refused.
- Replies, reply buttons, list messages, voice notes (as audio players), images/documents arrive in the chat. Approval cards for calls are
  buttons. The "call report" message arrives like any other message. Outbound messages go through the normal Notifier, so they are logged
  in the messages repository exactly like WhatsApp ones: "what do you remember", "delete everything" and purge work on them. The page's
  own copy of the chat is in memory only (a server restart empties the page, not the database).
- Inbound: text, voice note (recorded in the browser, sent as audio, transcribed by the real speech path), photo/PDF (goes through the
  document path when that is switched on), location (browser geolocation), buttons/lists. Contact cards are not offered.
- Replies are fetched by short polling every 3 s and again when the phone wakes up (`visibilitychange`, `online`). A send waits up to
  25 s for Friday's first reply, so the typing dots show while it thinks.

## Who can use it (identity)

- Every tester has a **personal invite link** bound to ONE phone number: `https://<host>/web/<token>/`. The token is random (24 bytes),
  shown **once** when created and stored only as a SHA-256 hash in `var/web/testers.json` (mode 0600, gitignored). It expires
  (default 30 days, `--days` / `FRIDAY_WEB_INVITE_DAYS`) and can be revoked. A wrong, expired or revoked token is a plain 404 on every call
  (page, API, manifest, icons).
- The tester's number must be in `FRIDAY_PILOT_ALLOWED_NUMBERS` or `FRIDAY_CHATBOT_TESTERS`: checked when the invite is made and again
  on every request. `FRIDAY_PROFILE=pilot` is required (otherwise the channel does not start and changes nothing; the reason is printed
  and `friday doctor` shows it). Numbers are shown masked everywhere in the page and the admin view.
- Set `FRIDAY_INVITE_ONLY=false` for the pilot, otherwise a new tester is first asked for an invite code (doctor warns about this).

## Calls go only to the tester's own number

`GuardedTelephony` wraps `c.telephony`, so it sees every dial (vendor/business-search calls, consumer calls, urgent calls, front-door
call-backs). Rule: the call's destination is forced to the requesting tester's own phone when the call can be tied to a tester (the task's
requester), and otherwise must already be an active tester's number. **Any other destination is refused before the provider is touched.**
So a "call this salon" task rings the tester's own phone (the script still uses the real vendor name); a real business is never dialled.
Also: the kill switch (`friday pause`) is checked on every message and every dial; a call is at most `FRIDAY_WEB_MAX_CALL_SECONDS` (180).
Keep `FRIDAY_VENDOR_CALL_REDIRECT_TO` set to an allow-listed number (the founder's) so the existing pilot checks upstream let vendor tasks
reach the dial step; the guard then moves the destination to the requester's own phone. Known limit: consumer calls that cannot be tied to a
task (family calls) are only allowed when the dialled number is itself a tester's number; the existing pilot allow-list still denies the rest.

## Limits (0 = unlimited, the pilot default)

`FRIDAY_WEB_MESSAGES_PER_MIN` (20), `FRIDAY_WEB_MAX_CALLS_PER_DAY` (0), `FRIDAY_WEB_MAX_SPEND_INR` (0, per tester per IST day, estimated from
the call length), `FRIDAY_WEB_GLOBAL_MAX_SPEND_INR` (0, all testers). The Vobiz prepaid balance is the natural ceiling while they are 0;
`friday doctor` prints a note. Calls are counted when dialled in `var/web/ledger.jsonl`.

## Screens

- **Consent** (first open only): one line, "AI assistant, test mode. Calls go only to your own number." + **Continue** (+ a small Privacy
  link). Wording is **PENDING founder approval** (`friday/webchat/copy.py`). Messages are refused until Continue is tapped.
- **Chat**: nothing but the chat. `?dev=1` adds one tiny status line (name, masked number, calls today, link hours left); no dev panel is
  ever sent on the web channel.
- **Feedback**: tap one of Friday's bubbles for thumbs up / down / flag; down and flag ask for an optional note. Stored in
  `var/web/feedback.jsonl`.
- **Privacy** (`/web/privacy`, public, noindex): a placeholder; business name and grievance officer to come from the founder (T5).
- **Add to home screen**: web manifest, icons (192, 512, 180 apple-touch), a minimal service worker, safe areas; light/dark follows the
  device; `noindex` everywhere.

## Set up (server)

1. Env (`/opt/friday/.env`, names only): `FRIDAY_PROFILE=pilot`, `FRIDAY_PILOT_ALLOWED_NUMBERS=` the founder (and `FRIDAY_CHATBOT_TESTERS=` his wife),
   `FRIDAY_INVITE_ONLY=false`, `FRIDAY_VENDOR_CALL_REDIRECT_TO=` the founder's number, `FRIDAY_PUBLIC_BASE_URL=https://...`,
   `FRIDAY_WEB_CHANNEL_ENABLED=true`, optional `FRIDAY_WEB_ADMIN_TOKEN` (16-64 chars). Restart `friday` (it runs inside `friday serve`; no tmux).
2. `sudo bash /opt/friday/deploy/web-https.sh` (pins `/web/*` to port 8000 with a noindex header, keeps /explore, /lab, /qa; `--off` removes it).
   Without it the default Caddy handler already forwards `/web/*`.
3. Invite: `friday web invite --name Himanshu --phone +91...` and `friday web invite --name <wife> --phone +91...` (prints the link once; share it
   privately). Other commands: `friday web testers`, `friday web revoke <id|name>`, `friday web feedback [--tester ...]`.
4. Admin page (only with `FRIDAY_WEB_ADMIN_TOKEN`): `https://<host>/web/admin/<admin token>/` : testers, create links, revoke, feedback, today's
   usage, kill-switch state.
5. `friday doctor` section 11 "web channel".

## iPhone / iPad / Android

Open the link in Safari (iOS) or Chrome (Android) over https. iOS: Share > Add to Home Screen. Android: menu > Install app / Add to Home
screen. Microphone and location prompts need https. The home-screen icon opens the same personal link, so keep the link private: anyone who
has it can chat as that tester until it is revoked.

## Not verified yet / honest limits

Not run against the real server, real Vobiz or a real phone (tests use fakes and run no calls). Voice recording format on iOS (mp4/AAC) depends
on ffmpeg being present for decoding (see `docs/VOICE_NOTES_AND_DEVANAGARI.md`). The consent and privacy wording is pending. Whether a call
is tied to a tester depends on the task requester; untied consumer calls are the limit described above.
