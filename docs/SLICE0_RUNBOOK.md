# Slice 0 runbook: Friday running, database applied, WhatsApp replying (for the founder, from an iPad)

Goal of slice 0 (docs/BUILD_BOARD.md): Friday runs on a server, the database changes (migrations 0006 to 0009) are applied, a message you send to the WhatsApp test number gets a reply, and `friday doctor` shows PASS.
No calls are placed and no real person is messaged in this slice. Never paste a key, token, OTP or password in chat or into a file in the repo; the install script asks for them with hidden typing.

## What you need before starting (about 45 minutes)
1. A server: a DigitalOcean droplet in Bangalore, Ubuntu 24.04, 2 GB memory (the old 1 GB one was tight). Roughly Rs 1,000 a month; check the price on the page. Use the droplet's web console (Droplets > your droplet > Console) and run `tmux new -As friday` first, because the console drops when you switch tabs.
2. Keys you already have or can get: Sarvam API key, OpenAI API key, Vobiz Auth ID and token (you may skip these three for slice 0 and add them in slice 1).
3. Meta WhatsApp test number (free, no business verification): developers.facebook.com > create an app (Business) > add WhatsApp > use the test number > add your own phone as an allowed recipient > copy the temporary access token, the phone number ID and the app secret. Choose a random word as the verify token.
4. Your own phone number with +91 (the only number Friday may call later; it is stored only in the server's .env).
5. Supabase (optional for slice 0, recommended): reset the database password in the dashboard (Project > Database > Settings), then follow deploy/supabase/README.md and run deploy/supabase/set-database-url.sh on the server. Without it the server uses a local SQLite file, which is fine for slice 0.

## Steps
1. Create the droplet and open its console. Run: `tmux new -As friday`
2. Run: `curl -fsSL https://raw.githubusercontent.com/himanshugoel23/friday/claude/friday-phase-1/deploy/small-server.sh -o small-server.sh && sudo bash small-server.sh`
   It installs HTTPS, the code (branch claude/friday-phase-1), asks for the keys above with hidden typing, applies the database changes and starts the service. Press Enter to skip anything you do not have yet.
3. Run the health check: `cd /opt/friday && sudo -u friday /home/friday/.local/bin/uv run friday doctor` (docs/DOCTOR.md explains every line). Fix every [FAIL] in order.
4. In the Meta app: WhatsApp > Configuration: callback URL `https://<your-server-name>.sslip.io/webhooks/whatsapp` (the script prints it), your verify token, subscribe to `messages`.
5. From your phone, WhatsApp "hi" to the Meta test number. Friday should reply within a few seconds.
6. Test the off switch: `sudo systemctl stop friday` (Friday stops answering) and `sudo systemctl start friday` (it answers again). Also run `friday pause --status`.

## Slice 0 is 100% when
- [ ] `friday doctor` shows PASS with no FAIL (WARN lines are explained and accepted)
- [ ] database at the latest migration (0009_life_state)
- [ ] "hi" on WhatsApp gets a reply, and a message with a wrong signature is rejected (doctor checks the handshake)
- [ ] the off switch works and you tried it
- [ ] the four consumer switches are still off (FRIDAY_CONSUMER_CALLS_ENABLED, FRIDAY_SAVINGS_ENABLED, FRIDAY_LIFESTATE_ENABLED, FRIDAY_GOOGLE_ENABLED)
- [ ] no secret appears in `journalctl -u friday` (grep for part of your token)
- [ ] you have seen it work, and docs/BUILD_BOARD.md is updated

## If something fails
Send me the last 20 lines of `friday doctor` output (it never prints secrets) or `journalctl -u friday -n 50 --no-pager`. Do not send tokens, the .env file or your number.

## What comes after
Slice 1 (call someone for me): needs the Vobiz keys, an approved opening line, and one real call to your own phone.

## If you already have the DigitalOcean server (founder, 19 Oct): update it instead of creating one
The droplet (Bangalore, Ubuntu 24.04, code in /opt/friday, service `friday`, HTTPS at https://<ip-with-dashes>.sslip.io) already exists, so skip "create the droplet". In its web console, inside tmux:
1. `tmux new -As friday`
2. `curl -fsSL https://raw.githubusercontent.com/himanshugoel23/friday/claude/friday-phase-1/deploy/small-server.sh -o /root/small-server.sh && sudo bash /root/small-server.sh`
   The script is safe to re-run: it switches the server to the current branch, updates the code, asks for each key again (press Enter to KEEP the value already stored), applies the new database changes (0006 to 0009) and restarts Friday.
3. Then continue from step 3 of "Steps" (friday doctor, Meta webhook, "hi" on WhatsApp, off-switch test).
Note: the server only runs the first-generation features until the new switches are turned on; all four stay off in slice 0.
