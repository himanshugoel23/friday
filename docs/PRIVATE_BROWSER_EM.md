# Private browser for Friday: EM design (22 Oct 2026)

Design only. Builds on `friday/connectors` (BrowserSession port, ActionGate, OTP channel, recorder, watch pages, registry). "(est)" = my estimate; "(unverified)" = secondary source only.

## 1. Architecture
**Decision: our own server first, behind the `BrowserSession` port; a cloud-browser provider as a second backend; the user's device only as an optional helper.**
- Own server: cheap, full data control, already built. Weak on anti-bot: Zomato resets our datacenter connections, Swiggy showed a challenge (HANDOFF 17 Oct).
- Cloud provider: Browserbase has proxies, CAPTCHA solving and persistent contexts ([docs](https://docs.browserbase.com/features/proxies)); Steel has profiles and an embeddable live view ([docs](https://docs.steel.dev/overview/sessions-api/embed-sessions/live-sessions)). Cost: cookies sit with a foreign vendor (DPDP) and lock-in. Use only through our port.
- User's device/extension: best identity, but useless when the phone is off. Login bootstrap only.
- **Isolation:** one container per task, one encrypted profile per (user, site): storage state, per-user data key, 30-day expiry, "Disconnect" deletes it. No shared disk or browser. The model never sees cookies (`scrub.py`).
- **Egress:** default-deny, allow only the site's domains; block private ranges and metadata IPs. Start with Indian datacenter IP and measure blocks; if blocked, one sticky Indian residential IP per user (new-IP logins trigger more checks). Never rotate IPs to dodge a ban.
- **Live view/takeover:** extend `watch.py` (tokened, expiring) with the stubbed `TakeoverHook`, used for login and CAPTCHA only. Provider live-view URLs are unauthenticated, so wrap them in our token ([Steel guide](https://docs.steel.dev/overview/guides/view-and-embed-live-sessions)). OpenAI and Google also hand passwords to the user ([OpenAI](https://help.openai.com/en/articles/11752874-chatgpt-agent), [Mariner](https://www.humansecurity.com/ai-agent/google-mariner/); both unverified).
- **Recorder:** keep `recorder.py` (inputs painted over, trace split around login), 30-day retention, deletable.
- **Kill switch:** per connector (exists), per user, global; closes the container and revokes tokens.

## 2. Agents (single-job)
| Agent | Job | LLM |
|---|---|---|
| Planner | request to typed task and limits | once |
| Page reader | page to structured facts | code first |
| Element locator | new selector when a step fails | small model, repair only |
| Executor | one typed step | no |
| Verifier | cart total equals promise | code |
| Safety gate | allow/deny/ask (`gate.py`) | never |
| Summariser | plain-words result | yes |

**Bound:** scripted connector first (no model on the happy path). Locator: max 3 repairs per task, logged, reviewed before becoming script. **Free browsing** only with user approval per task, allow-listed domains, read-only, 20-step cap, token budget; any state change still needs a Grant. Page text is data, never instructions.

## 3. Login, OTP, CAPTCHA, payment
- **Login OTP:** existing one-time page into the worker; memory only, single use, never in model, logs or trace. Prefer takeover (user types into the site's own screen).
- **CAPTCHA:** user takes over. No solver services (Browserbase solves by default, [docs](https://docs.browserbase.com/fundamentals/create-browser-session); turn off).
- **Payment:** stop at pay screen, send QR or `upi://pay`; user pays in their UPI app. No pay tool. Later maybe UPI Reserve Pay ([Razorpay](https://razorpay.com/blog/agentic-payments-and-npci/), pilot). No card vault.
- **Approval:** Grant with exact items, merchant, cap, expiry, one use, as WhatsApp buttons.

## 4. Sites that block or forbid automation
Order: (1) official API/MCP/PAP; (2) partner deal; (3) scripted browser with user in the loop, only after legal clears that site; (4) never.
- Swiggy: invite-led Builders Club with MCP and APIs ([coverage](https://www.fonearena.com/blog/481152/swiggy-builders-club-features.html); terms unverified). Zomato built an MCP ordering system, not shipped (MediaNama, secondary). PAP spec unpublished.
- IRCTC: automated booking tools are called illegal under IRCTC rules and the Railways Act; Akamai anti-bot ([ETV Bharat](https://www.etvbharat.com/en/!bharat/railways-curbs-unauthorised-automated-bookings-by-unscrupulous-agents-enn25060501221), secondary). **No IRCTC automation; deep link.**
- Amazon: conditions bar robots ([secondary copy of Amazon.com text](https://conductatlas.com/platform/amazon/amazon-conditions-of-use/provision/CA-P-018441/prohibition-on-data-mining-and-scraping-tools/)); it blocked Muse in 12 days (COMPETITORS h). **Skip.**
- Not found: terms for Zomato, Uber, Ola, MakeMyTrip, BookMyShow, Flipkart. Legal reads each.
- On any block: stop, send a deep link. Never evade.

## 5. Reliability
Selectors in one dict per site. Fixtures from recorded real pages; fake site for flow logic. Daily canary on login-free steps flips to `degraded` and sends a deep link. Track success, repairs, block reasons, p95 time per connector; alert under 80% over 20 runs (est). Replay fixtures before every release.

## 6. Security
| Threat | Mitigation |
|---|---|
| Prompt injection | Gate in code, not model; page text untrusted; domain allow-list; no outbound-send tool. Anthropic warns page text can override instructions ([summary](https://www.decryptiondigest.com/blog/governing-claude-computer-use-autonomous-desktop-agents), unverified) |
| Credential theft | Secrets never reach the model; scrub; encrypted profiles |
| Session hijack | Per-user container; expiring tokens; revoke; log takeovers |
| SSRF | Egress allow-list, private ranges blocked |
| Malware | Downloads and extensions off; non-root read-only container (microVM/gVisor); destroy per task |

## 7. Cost (all est)
Server about Rs 3-5k/month for 3-5 parallel tasks. Scripted task: under Rs 2 model plus under Rs 1 compute. Free-browse task: Rs 15-60. Provider: Rs 2-10 per task (vendor prices not read). Residential IP: Rs 200-800 per user per month. Target: under Rs 5 per scripted task, under Rs 100 per active user per month.

## 8. Legal (lawyer must check)
1. Does a user-directed agent in the user's own account breach each site's terms; who bears a ban? (US Ninth Circuit vacated Amazon's Comet injunction, 2026-08-04, US only.)
2. Residential proxy sourcing.
3. DPDP: consent, retention, erasure for cookies, screenshots, traces; foreign browser vendor.
4. RBI/NPCI for QR/UPI handoff.
5. AI disclosure to site and user; liability for a wrong order.
6. Whether sites require agent self-identification.

## 9. Roadmap
- **Phase 0, fake sites:** 100 runs, zero secret leaks, injection pages refused, kill switch tested.
- **Phase 1, one site, founder-supervised on his server:** probe first (Zomato web may push only the app). Exit: 10 runs, 8 reach pay screen, 0 unapproved actions, legal go.
- **Phase 2, five sites (API/MCP plus scripted):** canary 14 days, success 85%, blocks under 10%, cost in target.
- **Phase 3, 20 invited users:** consent, Disconnect, delete tested, lawyer sign-off, 0 incidents in 30 days.

**Build first (8):** (1) encrypted profile vault with expiry/Disconnect; (2) per-task container with default-deny egress; (3) takeover view; (4) Grant plus WhatsApp approval; (5) injection test pages; (6) canary plus deep-link fallback; (7) scrubbed real-page fixture recorder; (8) provider backend spike behind the port.

## 10. Top risks; do NOT build
Risks: account bans; cloud IP blocks; ToS/legal challenge; injection causes a wrong purchase; stolen cookie vault; users learn to share OTPs; silent selector drift; foreign vendor holds data; free-browse cost blowup; overpromising "order anywhere".
**Do NOT build:** card vault; OTP/password in chat; SMS or inbox code reading; CAPTCHA solving or fingerprint spoofing; IP rotation to evade bans; IRCTC or Amazon automation; a pay tool; social accounts; an unrestricted do-anything agent; a shared browser.
