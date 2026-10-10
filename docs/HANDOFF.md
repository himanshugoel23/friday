# HANDOFF: read this first (living context for any new chat or agent)

Founder instruction (verbatim intent): keep everything we discuss and decide in the repository, so a new chat can
read it and continue without losing context. **At the START of every task, update this file first** (what was just
asked, any decision, any mistake or lesson), commit and push it, **then** do the task. Never put secrets in it.

Last updated: 2026-10-10 (two chats have worked on this repo; read section 6 first).

---

## 1. What we are building
**Friday**: a JARVIS/F.R.I.D.A.Y.-style, proactive AI personal assistant for Indian consumers. Channels are WhatsApp,
voice calls and SMS only (no app, no web). The core product: Friday makes real phone calls to businesses for the
user (bookings, price quotes, discovery, IVR customer-care, hotels, parents' wellbeing check-ins), AND people can
call Friday's number and talk to her (inbound "front door"). Voice: female, calm, Hinglish. Docs: `docs/BRIEF.md`
(founder decisions, source of truth), `PRD.md`, `VISION.md`, `ARCHITECTURE.md`, `SECURITY.md`.

## 2. Standing rules from the founder (obey always)
1. **Hear before change.** Before ANY code change to spoken lines, voices, pace or pronunciation, generate audio
   (`friday say`, or the Sarvam TTS API from the sandbox) and send it to the founder with `SendUserFile`; change the
   code only after they approve the sound. (Said on 2026-10-10.)
2. **Update this file first** at the start of each task (above).
3. Never read or print `.env`; keys live only in the git-ignored `.env` (sandbox) or typed on the server; never in
   chat or git. Never commit `.env` or `var/`. Keys pasted in chat earlier must be rotated after testing.
4. No real calls except to the allow-listed founder number (+918607549916) and only with the founder's approval.
5. Founder speaks Hindi/Hinglish/English mixed (often dictating); the founder's own wording of the script is the
   authority. Do not assume pronouns for people.
6. Keep AI cost low; keep the user experience good.
7. Show scripts and results plainly; the founder is non-technical about servers/AWS.

## 3. Product decisions made (see BRIEF.md for the older ones)
- Voice agent speaks **Hinglish only** (Roman script; Indian names/business names are written in **Devanagari**
  inside the text for better pronunciation).
- **Approval rule**: Friday books only if the owner (user) gave an explicit instruction to book (delegation, within
  limits); a budget alone is not delegation; otherwise she only collects a quote and reports back.
- **AI disclosure (changed on 2026-10-10 by the founder)**: she introduces herself as "Himanshu sir ki *virtual
  assistant*", does not volunteer "AI", but if the business asks in ANY form (AI/robot/insaan/real person...) she
  answers truthfully next reply: "Haan ji, main <user> sir ki personal AI assistant hoon." She never denies being an
  AI. (Founder should check Sarvam/Vobiz terms; other flows still disclose up front.)
- **Salon call script** (first playbook), founder's design:
  1. "Hello, kya meri baat <salon name> se ho rahi hai?" then WAIT for "haan ji".
  2. "Main Friday baat kar rahi hoon, <user> sir ki virtual assistant. <user> sir ko <services> karwana hai, toh
     unki booking ke regarding call kiya hai."
  3. Price FIRST: "Toh sir, ek baar bata sakte hain inke kya charges rahenge?" (no duration question, no
     read-back, no advance/cancellation question unless the salon raises it, no negotiation unless the owner says).
  4. BOOK mode: "Kya <date/time> ka slot mil sakta hai?" If no: "Achha, nahi ho sakta. Toh kya kal ka slot
     available rahega?" then close: "Theek hai sir, phir kal ka 5 baje ka slot book kar lete hain. <user> sir aane
     se pehle aapko ek baar call kar lenge. Thank you." (If today is free: "...aaj shaam 5 baje ka slot book kar
     lijiye...").
  5. QUOTE-ONLY mode (owner only asked for a price): no slot question; after the price: "Theek hai sir, main <user>
     sir ko bata deti hoon. Thank you."
  - Business name, user name and services are VARIABLES (services joined like "haircut aur beard trim").
  - Wording rejected by the founder: "slot milega" (not how people talk), "kitna time lagega", "arrive hone se
    pehle" (use "aane se pehle"), long openings, repeating things at the close.
- **Pronunciation**: "salon" is spoken as **saloon** (founder picked by ear). Names are converted to Devanagari with
  Sarvam's transliteration API, cached, with an overrides file and a generic-business-word glossary; a
  speak-then-listen check flags names needing review. Sarvam's pronunciation dictionary (bulbul:v3, `dict_id`) is
  wired in (`friday tts-dict sync`, `friday/voice/tts/pronunciations.json`).
- **Voice/speed**: Sarvam bulbul:v3 speaker `ritu`, **pace 0.9** (founder is happy with the speed). Founder said
  the tone still feels robotic: samples of other voices (v4-flash Hinglish customer voices Ishita/Shalini/Simran,
  higher temperature, phrase pauses) were sent; **the founder has not yet chosen a voice**.
- Scale plan: one playbook per business type (8 types drafted offline: clinic, restaurant, car service, home
  services, hotel, gym, dentist, pharmacy); `friday playbook draft/promote`; dry-run simulation before any real
  call; quality loop stores consented, redacted, encrypted transcripts for later review and fine-tuning.

## 4. Where things are (code map)
- `friday/` Python 3.13/uv, FastAPI, SQLAlchemy. LLM: GPT (OpenAI) is the brain for now (`FRIDAY_LLM_PROVIDER=openai`,
  gpt-5.4-mini; call turns with no reasoning because `minimal` is rejected by that model).
- Voice: Vobiz telephony (`friday/voice/telephony/sarvam.py` = Vobiz adapter), Sarvam STT/TTS, front door
  (`friday/voice/frontdoor.py`, `friday/brain/frontdoor.py`), barge-in + early STT + sentence-by-sentence TTS.
- Playbooks: `friday/playbooks/` (data/salon_booking.yaml, engine, validator, dry-run simulator, authoring agent).
  Docs: `docs/PLAYBOOKS.md`, `docs/playbooks/salon_booking.md`. Quality loop: `friday/quality/`, `docs/QUALITY_LOOP.md`.
- Useful commands: `uv run friday playbook validate|dry-run|draft|promote|types`, `friday say "text" --pace 0.9
  --out f.wav`, `friday tts-dict show|sync`, `friday eval`, `friday review`, `friday livecall --playbook
  salon_booking ...`, `friday listen` (front door), `friday doctor`.
- Tests: `uv run pytest -q` (about 1750+ pass), `uv run ruff check .`.

## 5. Infrastructure (no secrets here)
- Server: DigitalOcean droplet, Bangalore, Ubuntu 24.04, 1 GB, IP **64.227.183.183**, HTTPS at
  `https://64-227-183-183.sslip.io`, code in `/opt/friday`, systemd service `friday` (runs `friday listen`),
  installer `deploy/small-server.sh`, one-command salon test call `deploy/call-me.sh`.
- Update the server: `git -C /opt/friday pull --ff-only` then `systemctl restart friday` (restart relinks the
  number in ~1 min). Test call: `bash /opt/friday/deploy/call-me.sh ...` (stops the service, calls, restarts it).
- Numbers: Friday's Vobiz number **+91 80 6426 7861** (inbound + outbound). Allow-listed test number
  +918607549916 (founder). Pilot profile: only allow-listed numbers; real businesses are blocked until the founder
  approves a specific number.
- The AI sandbox cannot SSH to the server; the founder runs commands in the DigitalOcean Web Console (it
  disconnects on tab switch; use `tmux new -As friday`, or the Termius app).
- Open items: Sarvam credits must stay topped up (a 402 "No credits" crashed a call once); ask Vobiz to turn
  **call queue OFF**; rotate all keys that were pasted in chat; decide whether the GitHub repo becomes private;
  check Sarvam/Vobiz terms on AI disclosure; domain/WhatsApp Business/legal pages for beta.

## 6. Lessons and mistakes (so we do not repeat them)
- Do not guess call problems: ask for `journalctl -u friday --since "10 min ago" --no-pager | tail -40`.
- Third-party apt repos can break (Caddy repo returned 402): use Ubuntu's own package.
- `reasoning_effort: minimal` is rejected by gpt-5.4-mini; valid: none/low/medium/high.
- When making audio samples, never put stage directions in the spoken text (it gets spoken).
- Keep agents on disjoint files; do not commit another agent's half-finished work; run the FULL suite before push.
- Sarvam docs are readable with `curl https://docs.sarvam.ai/<path>.md` from the sandbox (WebFetch cannot resolve it).

- **Two chats, one repo = duplicated work.** Before starting ANY task: `git fetch`, read `git log HEAD..origin/<branch>`
  and this file. On 2026-10-09 a second chat redid a "less helpdesk / witty proactive call-back" tone pass
  (`305b40a`) that the main chat had already done (`4eff9d2` front-door lines, `d5e778c` persona cadence). Do not
  repeat tone/copy passes; check git log for the topic first. (Founder asked 2026-10-10: read where we are, then change;
  no repeated similar changes.) Also: that tone pass touched spoken lines BEFORE the "hear before change" rule (2026-10-10);
  from now on, audio sample first.
- **AWS is a dead end for this founder.** Both AWS accounts given were managed sandbox accounts inside AWS
  Organizations with an SCP that denies Lightsail (`lightsail:CreateKeyPair ... explicit deny in a service control
  policy`). Do not retry AWS; hosting is the DigitalOcean droplet (section 5). `docs/DEPLOY_AWS.md`, `deploy/aws/*`,
  `docs/BETA_PLAN.md` (D12/D13) and `docs/TRIAL_CODESPACES.md` are older planning docs written before the droplet
  existed; this file is the source of truth where they differ.
- Founder has no laptop (iPad/phone browser only): give copy-paste steps for the browser console; never ask for
  secrets in chat (use `.env` on the server / environment settings).

## 7. Current state and next steps (update every task)
- DONE and pushed: front door (conversational), quality loop, playbook engine + salon v0.2, script author
  (offline), TTS pronunciation dictionary support, faster turns, droplet deployed and answering calls.
- IN PROGRESS (a builder agent, uncommitted until its tests pass): salon v6 = Devanagari names pipeline,
  services variable, book vs quote-only modes, fallback day, AI-on-request policy, `friday tts-check`,
  `friday playbook preview` (renders the real script to audio for the founder to hear before any call).
- NEXT: send the founder the preview audio from the real code; founder picks the voice (robotic tone issue);
  server update + test call to the founder's phone (`call-me.sh`); then first real salon only with explicit
  approval; then clinic/restaurant playbooks via `friday playbook draft --live`; WhatsApp channel; beta plan.
- 2026-10-10 founder ask (chat B): "read the latest changes made in the other chat first, understand where we are
  and what I asked, then change; do not repeat similar changes." Done: read this file and the 15 new commits; no code
  changed in that step. Answered earlier in chat B (no code): what user/call context is stored (profile, facts, people,
  places, vendor history, encrypted call transcripts, call_memory; front-door call conversations are NOT saved beyond
  name/language/consent and tasks created; consented redacted transcripts now go to the quality loop), and that
  fine-tuning now is premature (no data; playbooks + quality loop are the chosen route, fine-tune later from reviewed data).
- 2026-10-10 founder ask (chat B): "ignore what chat B built earlier; treat chat A's work as the instruction and continue
  it." Action: reverted chat B's tone commit `305b40a` (revert `ca1a714`) so no unapproved spoken-line changes ship to the
  server; chat A's wording stands. Founder then asked to place a Friday call to their own number: done via
  `deploy/call-me.sh` on the droplet (the sandbox has no keys and cannot SSH). The "salon v6" items listed in section 7 are
  NOT in the repo (no `playbook preview`, no `tts-check`, no quote-only mode): confirm with the founder whether chat A
  still has them before rebuilding.

