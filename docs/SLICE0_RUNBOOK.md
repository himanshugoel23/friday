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
- [ ] database at the latest migration (0010_chatbot)
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

## Registering the new SIM on Meta (WhatsApp Cloud API) - founder has the SIM (19 Oct)
Steps and screens are from general knowledge; Meta changes them often, so follow what the screen says if it differs. You type every code on Meta's own page; nothing goes through Friday or this chat.
1. Make sure the SIM is active and can receive SMS or a voice call (keep it in a phone for now). The number must NOT be registered on the normal WhatsApp or WhatsApp Business app. If it is, delete that WhatsApp account first (Settings > Account > Delete account), then wait a few minutes.
2. business.facebook.com: create a Business portfolio (Meta Business Suite) if you do not have one. Use your real name or company name.
3. developers.facebook.com: your app (type Business) > WhatsApp > API Setup > "Add phone number". Fill the display name, category, then choose SMS or voice verification, and type the 6-digit code you receive on the SIM.
   - The display name is reviewed by Meta and must match the brand (a generic or misleading name is rejected). The business name is not final; you can start with a working name and change it later, or use the free test number meanwhile.
4. Set a 6-digit two-step verification PIN for the number when asked and keep it in your password manager (not in chat).
5. Permanent token: business.facebook.com > Business settings > Users > System users > Add (admin) > Assign assets (your app and the WhatsApp account, full control) > Generate token with `whatsapp_business_messaging` and `whatsapp_business_management`. Copy it once into the server prompt (hidden). The temporary 24-hour token on the API Setup page also works for a first test.
6. Copy: Phone number ID, App secret (App settings > Basic), your chosen verify token. Enter them when the installer asks (or re-run it and press Enter to keep the others).
7. Webhook: WhatsApp > Configuration > Callback URL `https://<server>.sslip.io/webhooks/whatsapp`, your verify token, subscribe to `messages`.
8. Limits to expect: a number without Meta business verification can message only a small number of new people a day and has restrictions on display name changes; messages Friday starts outside 24 hours after the user's last message need approved templates (docs/LAUNCH_CHECKLIST.md section 4). For slice 0 you only message yourself first, so none of this blocks.
9. Keep the free Meta test number as a backup while the new number is being approved.

## From zero: no Facebook or Meta account yet (founder, 20 Oct). Do A to F now (about 45 minutes), G later
Meta changes screens often; follow what the screen says if it differs. Use your own real name and your own email and phone everywhere (fake details get accounts blocked). Keep passwords in a password manager, never in chat.
A. Facebook account: facebook.com > Create new account, real name, your email, birthday. Confirm the email. Turn on two-factor login (Settings > Accounts Centre > Password and security > Two-factor authentication, use an authenticator app). A brand-new account can be asked for an ID or a selfie check; do it, it is normal.
B. Business portfolio: business.facebook.com > Create account. Business name: a working name is fine (for example "Friday"), your name, your email. This is the home of your WhatsApp account. Business verification (documents) is NOT needed for slice 0.
C. Developer account: developers.facebook.com > Get started > log in with the same Facebook account > verify your phone or email > accept the terms > choose "Developer".
D. Create the app: My Apps > Create App > use case "Other" > app type "Business" > name "Friday" > connect the Business portfolio from step B.
E. Add WhatsApp: in the app, Add products > WhatsApp > Set up. Meta creates a WhatsApp Business Account and a free TEST number automatically.
F. First test with the free test number: WhatsApp > API Setup. Note down (do not paste in chat): the Phone number ID, the temporary access token (24 hours), and add YOUR phone under "To" (Meta sends a code to your WhatsApp to confirm). Then App settings > Basic > App secret. Choose a random verify word.
   Enter these three values plus the verify word when the server installer asks (hidden typing). Set the webhook (callback URL from the installer, verify word, subscribe to `messages`). Send "hi" from your phone.
G. Later, once the business name is decided: add the new SIM as the real number (section above), create a System User permanent token, and start business verification if Meta asks for it for higher limits.
