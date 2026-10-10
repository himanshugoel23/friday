# Public beta plan: 6 days (Gurgaon + Bangalore, calling businesses)

Founder ask (2026-10-10): public pilot/beta by the end of this week; 6-7 h/day; landing page to collect basic info;
WhatsApp Business (applied, number pending) with a group; first use case = calling businesses; Google API to find
numbers; measure (a) how many users use it, (b) how many businesses pick up; Gurgaon + Bangalore only; save data in
Supabase. No secrets in this repo (public).

## What already exists (do not rebuild)
Voice calls (Vobiz + Sarvam + GPT), salon playbook v6 (book / price-check), front door (inbound), WhatsApp channel code
(`friday/channels/whatsapp.py`), Google Places + geocoder (`friday/discovery/google_places.py`), Postgres support,
quality loop (consented transcripts), number pool + DNC + pause switch, deploy scripts, server on DigitalOcean.
Missing: Supabase wiring, landing page, public onboarding, beta safety policy for real businesses, metrics dashboard.

## Beta scope (keep it small so it ships)
- Invite-only, 30-50 users, two cities, ONE use case: **salon / parlour** price check and booking (Hinglish).
- User flow on WhatsApp: join via landing page -> "Hi" -> consent + name + city -> asks "haircut kal 5 baje near
  Sector 56 Gurgaon" -> Friday finds 3 salons (Google Places) -> user approves -> Friday calls -> reports result.
- Success metrics: signups, activated (sent 1st request), requests, calls placed, **business pickup rate**,
  outcomes (quote/booked/no slot/declined), cost per call, user rating.

## Day-by-day (parallel builders; founder does accounts/decisions)
**Day 1: accounts + foundations.** Founder: Supabase project (Mumbai region), Google Cloud project + Places API (New)
key with billing + budget alert, domain, check WhatsApp number status, ask Vobiz (outbound limits, DLT/KYC for AI calls,
call queue OFF, extra numbers). Build: Supabase Postgres as the production DB (`FRIDAY_DATABASE_URL`), migrations,
events table (signup, request, call_attempt, answered, outcome, rating); server upgrade to 2 GB; finish v6 test call
with feedback.
**Day 2: discovery.** Places text search + details (phone, rating, open now) for Gurgaon + Bangalore, geofence,
shortlist top 3, cache results, cost caps, never call numbers on DNC, store results in Supabase.
**Day 3: WhatsApp onboarding.** Cloud API webhook on the real domain; welcome, consent, name, city, request; approve /
reject buttons; result messages; templates submitted for approval on Day 1-2 (Meta takes time); use Meta's test number
until the business number is live. Group = founder-run announcement/feedback group; Cloud API groups are limited, so
conversations stay 1:1.
**Day 4: landing page + dashboard.** Static page (Cloudflare Pages/Vercel): value line, form (name, WhatsApp number,
city, use-case), consent text, Terms / Privacy / grievance officer / "calls may be recorded" pages, wa.me button;
form writes to Supabase (insert-only, no secret in the page). Metrics dashboard (Supabase SQL views + admin page).
**Day 5: beta safety + scale.** Policy change from pilot allow-list to approved-beta-users calling real businesses
(explicit founder approval), per-user caps (e.g. 3 calls/day), quiet hours 9-7, one retry max, opt-out/DNC, abuse
blocklist, number rotation or 2nd number, monitoring + alerts, backups, load test (3 parallel calls on the droplet),
20 simulated end-to-end runs, real test calls with team phones as "salons".
**Day 6: soft launch.** 5-10 friends first, founder watches logs live; fix; open invites to 30-50; daily review of
every call transcript (consented only); feedback form. Buffer for slips.

## Decisions needed from the founder (answer these first)
1. Beta size and per-user limits (suggest 50 users, 3 calls each)? Budget cap in rupees for the week?
2. Salon only for the beta (recommended), or also clinic / restaurant?
3. Approve real calls to real businesses for approved beta users (replaces the allow-list)? Human review of the first
   20 calls?
4. Domain name; is "Friday" trademark-safe (check before public marketing)?
5. WhatsApp: 1:1 chats + founder-run group (recommended)?
6. Who answers the grievance-officer email, and the business-facing "who is calling" page/number?

## Risks (honest)
- WhatsApp Business verification and template approval can slip; fallback = Meta test number + SMS/voice.
- Spam labels / blocked calls from one number; Vobiz rules on AI/automated calls (ask Vobiz on Day 1).
- Legal: privacy policy + consent (DPDP), recording notice, AI-assistant disclosure policy, TRAI rules; get a lawyer to
  read the two pages before public launch.
- Single process on a small server: cap concurrent calls (2-3) until upgraded and tested.
- Google Places cost and phone coverage for small salons; some will have no number.
