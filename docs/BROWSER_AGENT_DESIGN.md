# General browser agent: tasks on ANY website (2026-10-29)

Status: built and tested against FAKE pages and a SCRIPTED model only. **Nothing has run on a real site, with the real OpenAI model, or in a real Chromium from this code.** Switches `FRIDAY_BROWSER_AGENT_ENABLED` and `FRIDAY_JOB_APPLY_ENABLED` default OFF (both listed, names only, in `deploy/enable-web-test.sh`, always written `false`). All chat lines are PENDING founder approval (list at the end). No spoken line was touched.

## Why
Founder (2026-10-29): Instinct has browser agents that work out how to solve each task and ask the user where needed. `friday/sitemcp` covers KNOWN sites with fixed tools. This is the general one: a goal in plain words, a site, and a loop. Examples from a competitor's logs: apply to a job and fill the form from the profile and resume; cancel a subscription; read prices; fill a cart and stop before checkout; download a bill; check a booking.

## The loop (`friday/browser_agent/agent.py`)
```
 user text -> planner (APP_OR_CONNECTOR, "browser_agent" connector) -> gateway.start_task
              domains = what the USER wrote (link, domain, brand word in data/domains.v1.json); none -> "which website?"
                |
   RunSpec{goal, allowed_domains, steps 40, active seconds 300, cost INR 12} -----> RunState saved after every step (JSON, atomic)
                |
   +---> OBSERVE  snapshot: url (no query), title, <=1400 chars of text, <=60 elements "e7 textbox "Email" required"; never HTML;
   |             all page text inside ONE <page_untrusted> block, '<' '>' neutralised; typed values shown only as "filled"
   |       page guards (code): captcha / 401 / 403 / 429 -> BLOCKED;  payment page -> PAYMENT_STOP;  gov/payment host -> stop;
   |             host outside the allow-list (redirect) -> ask the user "open it?" (yes reopens the browser with the new list)
   |       THINK   one strict-JSON Action from the model (13 tools, flat schema, all fields present)
   |       POLICY  plain code on EVERY action (policy.py): domain, element exists, payment control, account creation,
   |             irreversible click needs a permit, legal text needs the user's own yes/no, ID numbers never typed, value source valid
   |       ACT     goto click fill select upload press wait extract screenshot_proof | ask_user request_confirmation | finish give_up
   +------ loop ---- but: ask_user / request_confirmation SAVE the state, release the browser page and END the call.
                     The user's next chat message resumes the run (also after a server restart).
 stops: DONE, BLOCKED, PAYMENT_STOP, BUDGET (steps | active seconds | cost), GAVE_UP, EXPIRED (user did not answer), CANCELLED ('stop'), BUSY (resumable), ERROR
```
Tools: `goto(url) click(target) fill(target, value_source) select(target, option) upload(target, file_ref) press(key) wait(ms) extract(question) screenshot_proof ask_user(question, kind, fields) request_confirmation(summary, target) finish(result) give_up(reason)`. There is NO pay, place-order, sign, create-account or generic-JS tool (tested). Elements are addressed only by snapshot ids (`e7`); the model never writes a selector or a path.

**Values never go through the model.** `fill` takes a `value_source`: `fact:<key>` (the user's profile / resume facts / earlier answers), `attest:<key>` (the user's own yes/no for a legal statement, this run only), `vault:username|password`, `otp`, or `text:<words>` ONLY inside a search box (no digits runs, no @). The code resolves the value inside the worker. The model sees fact KEYS and, for non-sensitive keys, a short value; email, phone, address, salary, ID-like keys show "(stored, hidden)". A free literal in a form field is refused, so the model cannot invent facts about the user.

## Ask the user (`ask.py`)
Missing fact -> the fill is NOT executed and the field is noted (label, the model's `suggest` as an offered default, the select options). The run keeps filling the rest of the page. Before any navigation, click, Enter, or finish the code sends ONE grouped message with every missing field (numbered, "(suggested: ...)", "(choose: ...)"), and legal statements verbatim with "reply YES or NO". Replies are parsed by rules (numbered lines, "label: value", "ok" = accept suggestions), with one model call as fallback that may only return the asked keys. Answers go to the user's own memory (`Fact` rows, key `ba:<key>`, erasable by "forget" and "delete everything"), so the same question is never asked twice; an explicit `ask_user` for a known key is refused. Legal answers are NOT remembered (asked again each time). Max 4 questions per run. Unanswered questions close the run after 24 h (confirmations after 30 min) with a polite line; a timeout never submits anything. A reply that looks like a password, card, PIN, OTP or Aadhaar is refused, not stored, not logged.

## Safety rules (code, with tests in `tests/browser_agent/test_safety.py` and `test_loop.py`)
1. Page text is data. A page cannot change the goal, allow-list, tools or sources: those live in `RunSpec`/`RunState`, which only the caller and the user's chat can change. A tool call that a fooled model makes anyway is refused by the policy (tested: injection text + model that obeys it).
2. Per-task domain allow-list (subdomains included). `.gov.in`, `.nic.in`, `.gov`, identity (UIDAI, DigiLocker, income tax...) and payment-processor hosts can never be on it. Adding a host needs the user's yes (`allow_domain`).
3. No payment, ever: card, CVV, UPI, VPA, wallet, net banking, "Pay", "Place order" controls are refused and a page that shows them stops the run (PAYMENT_STOP). The QR/link is handed over only if the user asked for it (`handover_payment_link`) and only then is the page address included.
4. No identity/government accounts. No account creation on any site without the user's yes for that site. No Aadhaar/PAN/passport/bank-number typing (left for the user and listed). No captcha solving, no stealth, no proxy rotation (the runtime sets none).
5. Passwords only via the vault link (`ask_user kind=login` sends the secure page; `vault:password` is released to the worker only on the host it was saved for). Login codes only via the secure OTP page / guarded login-OTP-in-chat (a bare 4-8 digit message is left to that guard).
6. Irreversible = submit, confirm booking, cancel subscription, e-sign, unsubscribe, delete account, any unlabelled form submit, Enter in a form that would submit. Needs a PERMIT: the user's explicit YES to a `request_confirmation` that showed the exact text, the host and the button label. A permit is single use, host- and button-bound, expires in 10 min. "maybe" is not a yes. Plain links only count when plainly final ("Confirm...", "Finish").
7. Legal/attestation text (declarations, "I have never paid for a job", background-check consent, terms) is never guessed: `attest:` source only, asked verbatim.
8. Every irreversible action saves a PROOF (JPEG screenshot with password/card/OTP/Aadhaar fields masked, host+path without query, when, what), <= 700 KB, auto-deleted after 14 days, and logs `irreversible_done`.
9. Logs, run state, ledger and prompts carry no typed values (tested with sentinel values). Screenshots do show the page.

## Reuse of the site-MCP runtime
`pwpage.PoolPageProvider` builds a knowledge-shaped dict per task and calls the existing `SessionPool` / `SafeSession`: ONE shared Chromium (shared with the site MCPs when `FRIDAY_SITE_MCP_ENABLED`), one context per user, `FRIDAY_SITE_MCP_MAX_SESSIONS` (2), idle close 240 s, memory guard (250 MB free), robots.txt for `goto`, pacing (3 s per site, 2 s per user, wait > 20 s -> busy), network default-deny to the allow-list, block detection. Pool trouble becomes `BUSY` (resumable); a block becomes `BLOCKED` with the manual steps.

## Failure modes (what the user sees; always plain language + manual steps: where to open, which fields I would have filled, which I left for you)
| Situation | Result |
|---|---|
| captcha / "verify you are human" / 401 / 403 / 429 / robots disallow | BLOCKED, no retry, no bypass |
| payment step reached | PAYMENT_STOP, "you pay yourself" |
| model returns invalid JSON / is down | counts as a refusal; 4 in a row -> GAVE_UP |
| model keeps hitting the policy | 4 consecutive refusals -> GAVE_UP; the same step 3 times -> GAVE_UP ("repeating") |
| selectors drift / element gone | action FAILED, the model re-observes; budget ends it |
| budget (steps, active seconds, estimated INR) | BUDGET, "nothing was submitted" |
| no RAM / browser cap | BUSY, saved, resumed by the housekeeping tick or the user's next message |
| server restart mid-run | state file reloaded; the browser reopens at the last URL; filled fields are filled again from facts (a reload loses typed form state) |
| user silent | EXPIRED, nothing submitted |
| file upload not confirmed by the page (read back `input.files`) | tried twice, then "attach it yourself" |

## Upload path (UNVERIFIED; a competitor's headless upload failed)
The model names a `file_ref` (`resume`); `FileRefs` maps it to a file the user registered in their private folder (pdf/doc/docx/png/jpg, <= 5 MB); the model never supplies a path. `PlaywrightAgentPage.upload` calls `set_input_files` directly on the `<input type=file>` (works for hidden inputs behind drop zones, no OS file dialog), then reads `input.files.length` back and reports success only if it is > 0. Snapshot includes hidden file inputs for that reason. Not covered: pure drag-and-drop widgets with no input element, uploads that need a file chooser click, sites that ignore programmatic files, and virus-scan or size errors shown after attach. How the user's resume gets INTO `FileRefs` is not wired: `FileRefs.store()` exists, but no inbound document hook calls it yet.

## RAM and latency on the 1 GB droplet (ESTIMATES, nothing measured)
Chromium 300-500 MB; the pool allows 2 contexts and ONE page working at a time across ALL users and site MCPs, so a second user's browser task gets `busy` while one runs (the page slot is held through the model's thinking time; it is released while waiting for the user). A 2 GB droplet is the comfortable size (swap helps). Per step: one model call (guess 2-6 s) + page action + pacing for page loads; a 12-step form is guessed at 1-2 minutes of active time. Model cost per step is estimated from token counts at rates in settings (`FRIDAY_BROWSER_AGENT_IN_INR_PER_1K` 0.05, `..._OUT_...` 0.2: GUESSES); a snapshot is ~1-2k input tokens, so a 15-step run is about 20-30k tokens. **Cost per run is unmeasured**; the INR 12 cap is a guess that bounds it.

## Wiring
* Planner (`friday/planner`): signal `browser_task` (cancel subscription, apply for a job, fill a form, download a bill, check a booking, stop at checkout, or a site + read/check/download verb). Only when the agent is on (`connectors` contains `browser_agent`) the heuristic returns APP_OR_CONNECTOR for it and the gateway calls `start_task`; known retailers keep the web lookup / site MCP. With the switch off the planner is unchanged. Side effect when ON: the planner now sees a connector, so other "order ..." requests are no longer turned into the "I can't place orders in apps" question by the no-connector guard and continue into the old chain.
* A2A team (`friday/team`): specialist `browser_agent`, skill `browser.task` (`a2a_agent.py`), registered IN-PROCESS only, NOT in the dict the optional HTTP route serves (a remote caller must not start browsing for a user). Not auto-delegated by the PM: a run takes minutes and the PM budget is 40 s, so the planner owns the user entry.
* Pipeline: `InboundPipeline.browser_agent` (answers, 'stop', job commands, before the team/planner), "delete everything" erases runs, proofs, files, ledger; runtime loop `browser_agent_loop` (every 60 s: expire, resume busy runs, purge proofs, evening summary); `friday doctor` lines.
* Login: `StackLogin` adapts the existing private-browser stack (credential link page, vault, OTP page). Without the browser stack the agent says it cannot take a login safely and the user logs in themselves.

## Job-application playbook (`jobapply.py`, `data/job_apply.v1.json`, switch `FRIDAY_JOB_APPLY_ENABLED`)
Data: profile fields (required/optional, options, default), resume ref rules, typical question -> fact key, the legal statements always asked, "never" list (pay a fee, ID numbers, account without ok), cap and mode defaults. Flow: `job apply on` (preview, standing opt-in) or `job apply auto on` (auto, explicit opt-in) or `job apply off`; no opt-in -> no run. "apply for this job <link>": needs a link and a registered resume; missing profile fields are asked ONCE up front (no browser, no model cost); the allow-list is that link's host only. **Preview (default):** the run stops at the final submit with what will be sent; the user's YES sends it. **Auto:** the standing opt-in replaces the per-application yes for the SUBMIT click only, once per run, never when a legal box is still open, and legal statements are still asked every time; daily cap `FRIDAY_JOB_APPLY_DAILY_CAP` (5, IST day). Ledger (when, host+path, title the agent reported, proof id, no answers) feeds the evening summary at 20:00 IST (once a day, with "proof saved"). **Decision for the founder:** the brief asks for a chat yes before ANY irreversible submit AND an auto-apply opt-in; auto mode resolves that as above (standing opt-in = the yes for the submit click). Say if you want auto mode removed.
Not built: finding jobs by search, applying to several jobs in one request, parsing the resume into facts, ATS-specific tuning.

## Honest caveats / unverified
* No real site, no real Chromium, no real OpenAI call. The snapshot script, label rules, irreversible/payment/attestation patterns (`data/rules.v1.json`) and the upload path are general-knowledge guesses; expect false positives (extra confirmations, e.g. both "Cancel membership" and "Finish cancellation" may each ask) and misses (a JS "Apply" button that submits without being a form submit is NOT treated as irreversible).
* Robots.txt is checked for URLs the agent opens with `goto`; navigations caused by clicks are not re-checked. No cookies are saved between runs (login each time).
* Page content (including a logged-in page) is sent to the model provider for the observation. Founder/legal decision needed before logged-in use.
* A model-written confirmation summary could misdescribe the action; the shown host and the exact button label are code-supplied and the permit is bound to that button.
* Resume registration from chat and a document hook are not wired; PM auto-delegation is not wired.

## Chat lines added (all PENDING approval; en / hinglish in `friday/browser_agent/wording.py` and `jobapply.py`)
ack, grouped question (head/foot/suggested/choose), legal statement head, confirmation ("Reply YES to go ahead, or NO to stop") and re-ask, login link, code link, allow domain, allow account, secret refused, not understood, done, proof saved, blocked, payment stop (+ link), budget, gave up, busy, expired, cancelled, already running, which website, manual steps; job: opt-in prompts, on/auto/off, cap reached, need resume, need link, evening summary.

## Tests (fakes only)
`tests/browser_agent` (76): loop completes a fake multi-step form; grouped ask + resume + defaults; injection ignored; payment stop; confirmation blocks submit (maybe/no/expiry/single use/button-bound); allow-list; blocked/captcha/429; budget (steps, cost, seconds); restart-safe resume; no pay/sign tool; logs and prompts free of secrets; vault/OTP; attestations; ID numbers; upload failure; provider over the real `SessionPool`; planner + chat end to end through the real pipeline; A2A specialist; job playbook (opt-in, preview, auto, cap, summary).
