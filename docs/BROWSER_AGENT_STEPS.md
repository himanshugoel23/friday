# Browser agent: step-by-step web tasks (design note)

Status: built, switch `FRIDAY_BROWSER_STEPS_ENABLED` default OFF (ON in `deploy/enable-web-test.sh` for the tester server).
All chat wording is PENDING founder approval (`friday/steps/wording.py`). Nothing has been run on a real site.

## Founder instruction (2026-10-29, translated from Hinglish)
For any web search or web task, break the task into steps and do them one by one; do not push the whole task into one prompt.
Example, price of atta on a site: (1) open the site from its URL and look at the page; (2) the price depends on the AREA: use the
saved place if there is one, otherwise ask (home or PG); (3) if the site needs LOGIN, say an OTP is coming on this same number, ask
the user to send it in the chat (allowed, guarded), then use it on the site; (4) search; (5) tell the price, the user's variant if
given, otherwise the main variants; (6) suggest other popular atta brands and recommend the best one.

## Shape

```
text -> StepPlanner (data playbooks; LLM fallback in the SAME closed schema) -> validate -> PlanState (persisted)
     -> StepRunner: for each step: announce -> skip if the precondition is met -> run ONE step -> record proof -> next
          loop steps  (open_site, search, read_results, navigate, fill_preview, act_confirmed, read_status)
                       -> the existing BrowserAgent loop with a small goal per step (policy layer on every action)
          code steps  (need_area, need_login, need_info, match_variant, compare_and_suggest, report) -> small handlers
```

* `friday/steps/types.py`: the closed `StepType` vocabulary. There is no pay, checkout, sign or account-creation type.
* `friday/steps/data/playbooks.v1.json`: playbooks as DATA (`price_check`, `cancel_subscription`, `fill_form_preview`,
  `track_order`), the goal template of each loop step, and the forbidden words list.
* `friday/steps/validate.py`: known types only, at most 12 steps, first `open_site`, last `report`, no payment / sign / account
  wording in any title or argument, no government / identity / payment host. Runs on every plan and on every re-plan.
* `friday/steps/planner.py`: `plan(text)` (data first, then optional LLM that must emit the closed schema) and `replan(plan, idx,
  reason)`: with a model a new validated tail, without one a single retry of a retryable step (the goal gets a "second try" hint).
  Domains come from the user's words or the shopping site table, never from a model or a page.
* `friday/steps/runner.py`: the one-step-at-a-time runner. Persisted after every step (`friday/steps/store.py`, JSON per plan,
  atomic), resumes after the user answers and after a restart (`tick` continues a plan that was RUNNING).
* `friday/steps/worker.py`: runs the inside of a step with `BrowserAgent` (own run store `var/steps/runs`, so the general
  browser-agent gateway never sees these runs). The safety rules (payment stop, allow-list, injection safety, no account creation,
  irreversible confirmation) are NOT repeated: they stay in `friday/browser_agent/policy.py` and apply to every action of every step.
* `friday/steps/suggest.py`: `compare_and_suggest` reuses `ShoppingAgent` (popular brands) and `recommend` (ONE pick + reason) as is.
* `friday/steps/gateway.py` + `wiring.py`: planner entry (`PlannerGateway.steps.start`, before the shopping assistant), early reply
  handling in `InboundPipeline._active` (before the browser-agent gateway), `tick` in the browser-agent loop, "delete everything".

## Behaviour per step

| step | what | asks the user? |
|---|---|---|
| open_site | open the start URL, look; result `login_wall=yes/no` | never |
| need_area | skipped when a saved Home/PG place (or a pincode in the request) exists | only if unknown: "Home or PG?", one question |
| need_login | only when the page showed a login wall (or search/read hit one later: back to this step once) | the OTP, see below |
| search | search box; sets the location from the stored area; `location=not_accepted` -> asks another area once | only on a rejected area |
| read_results | products as `title \| pack \| price`; none -> one retry, then a plain stop | never |
| match_variant | variant (pack/brand) given -> exactly that; not seen -> says so and shows the main ones; none given -> top 3 by price per kg | never |
| compare_and_suggest | other popular brands + one recommendation with a reason | never |
| report | headline, rows, suggestions, pick, proof lines | never |

Progress lines: "Step 2 of 5: I need your area for the price. Home or PG?" The count covers the steps that really run (match_variant and
report are silent and not counted; a skipped step is not counted). One question per message; grouped questions only inside a form
(the loop's own grouped ask).

## Login (guarded OTP)
`need_login` arms the existing guarded path (`PendingLoginRegistry.expect(user, site, plan_id)`), tells the user "Zepto needs a login. It will send an OTP to your number ending
XX. Send it here and I will enter it", types the user's own phone from the stored fact and asks the site to send the code. The code the
user sends is taken by the existing interceptor (`BrowserStack.intercept_chat_secret`): redacted in the transcript, never read by the LLM, held
in `OneTimeOtpChannel` (single use, 5 minutes). The runner never sees it: it only asks `ready(plan_id)`, then the loop types it with `value_source: otp`
(`StepLogin` maps the loop's run id to the plan key). It is not in prompts, plan files, audit events or messages. No code after 5 minutes -> ONE resend is offered
(yes/no); a wrong code -> one more try; then a plain stop. Bank / card / UPI codes are refused by the existing guard.

## Stopping
A blocked site, captcha, rejected location, changed layout, payment page or a login that cannot be completed ends the plan with a plain
message: "I stopped at step N (title): why", then the next best option: for `price_check` with a category "compare public web prices
instead? YES/NO" (runs the existing shopping assistant), otherwise the page to open yourself, always "Nothing was submitted or changed."
A payment stop offers no fallback.

## Switch
Off: `PlannerGateway.steps` and `pipeline.browser_steps` are `None`; nothing changes. On needs `FRIDAY_BROWSER_AGENT_ENABLED` (else stays off).
`FRIDAY_BROWSER_STEPS_DIR` (plans, loop runs), `FRIDAY_BROWSER_STEPS_OTP_TTL_S` (default 300).

## Not verified
Nothing ran against a real site, real Chromium, the real model or the real OTP channel. The goal templates (how well the model follows
"finish with login_wall=yes|no", `title | pack | price` lines, `location=not_accepted`) are the part most likely to need tuning on the
first real run. The loop flattens line breaks in its result, so products are separated by `;` and found by their `| pack | price` shape.
