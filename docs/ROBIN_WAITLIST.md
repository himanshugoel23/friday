# Robin waitlist: test demand while the product is built (2026-11-04)

Founder ask: while Robin is built, test whether people sign up, with a page that says "about to launch, we will message you when your spot opens". Status: BUILT and tested with fakes; **switch `FRIDAY_ROBIN_WAITLIST_ENABLED` is OFF** until the founder approves the page copy. Nothing is live.

## What it is
- **Page** `https://<domain>/robin` (mobile-first, light and dark, English plus a Roman Hinglish toggle, no cookies, `noindex`). Copy: promise of daily check-in, medicine reminders, scam help via forwarding, alerts to the child; "Robin is not live yet and is not an emergency service. In an emergency call 112." No testimonials, no fake counts, no payment.
- **Form:** first name, WhatsApp number (India or any country code: NRI children are core), who it is for, parents' city and main language, optional worries (scam calls, medicines, living alone, emergencies, loneliness, bills), required consent tick (message me on WhatsApp about the waitlist and launch; delete on request). After sign-up: a thank-you plus a "Share on WhatsApp" button (`?src=share`) for siblings.
- **Channel tracking:** add `?src=<name>` to any link you share (for example `/robin?src=family-groups`, `?src=clinic`, `?src=linkedin`). The report shows views and sign-ups per source and the join rate.
- **Privacy page** `/robin/privacy`: what is collected, why, where, how long, how to delete. The deletion contact comes from `FRIDAY_ROBIN_WAITLIST_CONTACT` (set it before going live), else "reply DELETE to any WhatsApp message from Robin".
- **Abuse limits:** honeypot field, 8 sign-ups per hour per IP (hashed, in memory only), 3000 per day, strict schema, duplicate numbers are ignored.
- **Storage:** `var/robin_waitlist/signups.jsonl` (directory 0700, file 0600, each line encrypted with the field cipher when available), `views.json` (counts per day per source: no IP, no device). Never committed (var/ is git-ignored).

## How the founder reads it
- In your chat: send **`waitlist`** (founder-only: first allow-listed number or an admin phone) for the summary: total, last 7 days, by source with views and join rate, cities, languages, who it is for, worries, how many outside India, the latest five (masked numbers). **`waitlist delete +91XXXXXXXXXX`** removes one sign-up.
- Or open `/ops-status/<token>/waitlist` (summary) and `/ops-status/<token>/waitlist.csv` (full export with numbers, token-gated).

## Turn it on (after you approve the copy)
1. Optional: `ROBIN_CONTACT="WhatsApp DELETE to <your number>" bash /opt/friday/deploy/enable-robin-waitlist.sh` (or without the variable).
2. Open `https://64-227-183-183.sslip.io/robin` on your phone and read it as a stranger would. Turn off with `bash /opt/friday/deploy/enable-robin-waitlist.sh off`.
3. Share links with `?src=` tags.

## Messages you may send to people on the list
Only after they ticked the consent box, and only about the waitlist and launch. WhatsApp's own rules: the first message to a new number must be an approved template or a reply to their message; Meta's token is still blocked (founder). Until then contact them by normal WhatsApp from your own number, one by one, with a delete option.

## What it tells you (and what it does not)
It measures **interest**, not willingness to pay. Pair it with the concierge pilot and a price question in your first message ("Would Rs 299 to 499 a month for this feel fair?"). Good early signals: join rate above about 10% on warm sources (family and friends groups), and sign-ups from siblings after the share button. Treat numbers from cold traffic with caution.

## Legal and copy notes (PENDING)
All page, privacy and consent wording is PENDING founder approval and a lawyer's read (DPDP notice, consent for WhatsApp messaging). The domain is a sslip.io address; buy a real domain before wide sharing so the link looks trustworthy.
