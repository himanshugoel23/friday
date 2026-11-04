# Robin waitlist: test demand while the product is built (2026-11-04)

Founder ask: while Robin is built, test whether people sign up, with a page that says "about to launch, we will message you when your spot opens". Status: BUILT and tested with fakes; **switch `FRIDAY_ROBIN_WAITLIST_ENABLED` is OFF** until the founder approves the page copy. Nothing is live.

## What it is
- **Page** `https://<domain>/robin`: **the design tells the story, with a few words per screen** (about 350 visible words in total including phone mock-up text and legal lines). Fixed warm light theme with dark story panels (cream, deep teal for trust, marigold, a rose alert colour, night blue). Scroll sequence: (1) hero illustration, a mother at home and her child in a distant city joined by a dotted "800 km" line: "Mom is alone. You are far." (2) a ringing-phone mock-up with an unknown caller and three short bubbles ("I am from the police... do not hang up"), "She is 68. She is scared." (3) three big numbers from REAL news reports (Rs 2.5 cr, Rs 3.95 lakh, Rs 6 lakh) linked to the publishers (The Tribune, Free Press Journal) (4) "At 3 am, who finds out first?" with three icon tiles (missed tablet, a fall, an unanswered phone) (5) "You cannot be there every day. Robin can." with two phone mock-ups: Maa's WhatsApp (voice note, Robin's reply) and your phone (alert: "Maa has been on a call with a stranger for 22 minutes", Call Maa button) (6) four icon tiles: daily check-in, medicine reminders, scam help, alerts to you (7) the form. Reveal-on-scroll animation (off for reduced-motion), sticky join button on phones, English and Roman Hinglish toggle, no cookies, `noindex`. The opening is a scene, not a testimonial; no invented quotes, counts or testimonials. A designer can restyle it freely: keep the news links, the honest footer line, name + number only, and the form's field names.
- **Form: only name and WhatsApp number** (India or any country code: NRI children are core). Consent is a plain notice under the button ("By joining you agree that Robin may message you on WhatsApp about the launch..."), not a checkbox; **a lawyer may require an explicit tick** under DPDP, which is a one-line change. After sign-up the page gives something useful: "call your parents tonight and ask one thing" plus "no officer ever arrests anyone over a phone or video call", and a share-to-a-sibling button (`?src=share`).
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
