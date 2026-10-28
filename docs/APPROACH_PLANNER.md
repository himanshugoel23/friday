# Approach planner (PM step 0): decide WHAT a request needs before planning

Status: built, tests green, switch OFF by default. All chat wording below is PENDING the founder's approval. No spoken (voice) line was touched.

## Why
First real web-chat test (2026-10-28): "check the price of 5 kg Aashirwad atta on Zepto" got no answer for a long time and the bot kept saying "before I call...". Every request was forced into the bucket x category plan that ends in vendor CALLS, and there was no price/web lookup. The project manager must think first: is a call needed, or a lookup, an app, an answer, or one question?

## Flow
```
chat text -> InboundPipeline._active (after chatbot/features, before browser/quotes/PM/brain)
   -> PlannerGateway.route
        skip: buttons, voice-less/empty text, a task waiting for this user's answer, an active PM task
        -> ApproachPlanner.plan = decider (LLM or heuristic) + apply_policy (code, last word)
        WEB_LOOKUP  -> WebLookupAgent -> sourced reply (here)
        ASK/DECLINE -> one question / plain refusal (here)
        CALL_VENDORS, APP_OR_CONNECTOR, ANSWER -> the existing chain (calls keep consent, allow-list, kill switch; apps keep the browser rules; answers go to the brain)
```
Package `friday/planner/`: `types.py` (Approach, Reason, ApproachDecision), `signals.py` (offline keyword signals, English + Hinglish), `planner.py` (HeuristicDecider, LLMDecider, apply_policy), `agents/{answer,web_lookup,call,ask}.py`, `web.py` (provider port: Fake, Unavailable, OpenAI), `slow.py`, `wording.py`, `gateway.py`, `wiring.py`. Registered in `docs/AGENT_ROSTER.md` (agents 23-28).

## Approaches and reason codes
ANSWER (knowledge, no tool) / WEB_LOOKUP (public prices, stock, timings, reviews, facts) / APP_OR_CONNECTOR (order or book through an enabled connector) / CALL_VENDORS (only when a human at a local business must be asked) / ASK (one question, only if truly needed) / DECLINE.
Reason = a code (`knowledge`, `live_public_data`, `order_via_app`, `local_human_needed`, `missing_info`, `not_allowed`, `unsure`, or a `guard_*` code when the guard overrode the first choice) plus a short text. Each decision is written to the audit log (`planner.decision`: approach, reason code, source).

## Decider and guard
The LLM (only when `FRIDAY_APPROACH_USE_LLM` and the resolved provider is OpenAI) answers a closed JSON schema (`PlannerLLMOut`, strict). It is asked only when the offline heuristic is not already confident (>= 0.8). Timeout 6 s; any failure or invalid JSON falls back to the heuristic. The guard (pure function) then enforces:
1. a CALL is never kept when a lookup can answer, unless the user said "call them" / "call karke";
2. APP_OR_CONNECTOR needs an enabled connector (today: the private browser): else WEB_LOOKUP if a lookup can answer, otherwise ASK;
3. a CALL or APP below 0.5 confidence becomes ASK; unknown text becomes ANSWER (the brain), never a call;
4. an LLM-chosen CALL below 0.75 with no local-business signal and no explicit request becomes ASK.
Choosing CALL_VENDORS only lets the request continue into the old flow. Every real call still passes the existing consent, allow-list, call-window, redirect and kill-switch guards.
Decision table (tests): Zepto price -> WEB_LOOKUP; "find me a plumber tonight" -> CALL_VENDORS; "what is the capital of France" -> ANSWER; "order pizza" -> APP_OR_CONNECTOR if the browser connector is enabled, else ASK.

## Web lookup agent
Provider port `WebSearchPort`. Real adapter: OpenAI Responses API with the `web_search` tool (`OpenAIWebSearch`, India location hint, low context size, model `FRIDAY_APPROACH_WEB_MODEL` or the default light model). Fake provider for tests; with no OpenAI key the clearly failing `UnavailableWebSearch` is used (the user is told plainly, no retry). Output: status (ok / no_result / timeout / unavailable), summary, items, sources (only URLs the provider actually cited; an item URL that was not cited is dropped), `as_of`, caveat, `ask_pincode`.
No sources means no answer ("no_result"): an unsourced price is never shown. Hard cap 25 s for the whole lookup including its single retry (a retry only starts if >= 8 s remain); successful results are cached 5 minutes per (query, store, pincode). The reply to a pincode ("560001") after a price answer, or "yes" after a timeout, re-runs the last lookup.
Honest note: the OpenAI adapter is covered by fake-client tests only; it has NOT been run against the real API from here. Run one real query on the server first (`FRIDAY_APPROACH_PLANNER_ENABLED=true`, ask a Zepto price) and look at the sources.

## Honest limits: web prices may differ from the app
A price found on public web pages or search is not the live price in the Zepto/Blinkit app. Quick-commerce prices and stock vary by pincode and store, search snippets can be hours or days old, and a page can show a different pack size. The reply therefore always shows sources and an "as of" time, carries a caveat, and (for Zepto/Blinkit/Instamart/BigBasket/JioMart) asks for the pincode. It is a guide, not a quote. Ordering through an app is a separate, unbuilt connector.

## Slow responses
If any plan takes more than 8 s (`FRIDAY_APPROACH_ACK_AFTER_S`) Friday sends ONE short acknowledgement that names the approach, then the result arrives as the normal follow-up. Never more than one. Lookup timeout: the user is told plainly and offered the next best option (check the app, or "try once more"). Calls are mentioned only in the CALL_VENDORS acknowledgement.

## Switches (all default as shown)
`FRIDAY_APPROACH_PLANNER_ENABLED=false` (master; `deploy/enable-web-test.sh` switches it on and prints the name; `off` switches it off), `FRIDAY_APPROACH_USE_LLM=true`, `FRIDAY_APPROACH_DECIDE_TIMEOUT_S=6`, `FRIDAY_APPROACH_ACK_AFTER_S=8`, `FRIDAY_APPROACH_WEB_TIMEOUT_S=25`, `FRIDAY_APPROACH_WEB_CACHE_TTL_S=300`, `FRIDAY_APPROACH_WEB_MODEL` (empty = default light OpenAI model). Needs OPENAI_API_KEY for the web lookup (no new key). Web search is billed by OpenAI per call: cost not measured.

## Wording audit ("before I call" and friends)
Searched `friday/` for "before I call" style phrasing. Only one emitter existed: `friday/tasks/engine.py` `_needs_info` ("Before I call, I need: ..."), used by call tasks. It now goes through `wording.needs_info_line(call_in_plan=True)`: text unchanged for call tasks, and the non-call variant exists for any future non-call task. The PM plan templates (`friday/pm/data/plans.yaml`) mention calls only in the consent / no-pickup / blocked lines, which are call-plan lines already. A test asserts no new planner line mentions calling except the two call-plan lines.

## Changed or new chat lines (founder to approve; en / hinglish; status PENDING)
| key | English | Hinglish |
|---|---|---|
| ack_web | On it, checking {where} now. I'll send the result in a moment. | Ek minute, {where} check kar rahi hoon. Result abhi bhejti hoon. |
| ack_answer | One moment, thinking this through. | Ek minute, soch rahi hoon. |
| ack_app | On it, working on this in {where} now. | {where} par kar rahi hoon, bas ek minute. |
| ack_call (a call IS planned) | On it, lining up the vendors now. This can take a few minutes. | Shuru kar diya, vendors ki taiyari kar rahi hoon. Thoda time lag sakta hai. |
| web_timeout | That took too long and I could not get a reliable answer. You can check {where} directly, or I can try again. Want me to try once more? | Isme bahut der lag gayi aur pakka jawab nahi mil paya. Aap {where} par seedha dekh sakte hain, ya main ek baar aur try karun? |
| web_unavailable | I can't look things up on the web right now. Please check {where} directly, and I'll help once it's back. | Abhi main web par check nahi kar sakti. {where} par seedha dekh lijiye, wapas chalu hote hi madad karungi. |
| web_none | I could not find a reliable result for that. Tell me the exact product and your pincode and I'll try again. | Iska pakka result nahi mila. Exact product aur apna pincode bata dein, main dobara dekhti hoon. |
| web_as_of | As of {time} IST. | {time} IST ke hisaab se. |
| caveat_quick | This is from public web pages, not the {store} app. {store} prices and stock can differ by pincode and store, so treat it as a guide. | Yeh public web pages se hai, {store} app se nahi. {store} ke daam aur stock pincode aur store ke hisaab se alag ho sakte hain, isliye ise andaaza maaniye. |
| caveat_web | This is from public web pages and may differ from the shop's own app or counter price. | Yeh public web pages se hai, dukaan ke app ya counter ke daam se alag ho sakta hai. |
| ask_pincode | Tell me your pincode and I'll narrow it down for your area. | Apna pincode bata dein, main aapke area ke hisaab se dekh lungi. |
| ask_no_connector | I can't place orders inside apps yet. I can look up prices or the menu on the web instead. Want that? | Abhi main apps ke andar order nahi laga sakti. Web par daam ya menu dekh sakti hoon. Chahiye? |
| ask_generic | I want to get this right. Could you tell me a little more about what you need? | Main ise sahi karna chahti hoon. Thoda aur bata dein ki aapko kya chahiye? |
| ask_unsure_call | Just to be sure before I act: what exactly should I find out, and for which place? | Karne se pehle pakka kar lun: exactly kya pata karna hai, aur kis jagah ke liye? |
| decline | Sorry, I can't help with that one. | Maaf kijiye, isme main madad nahi kar sakti. |
| needs_info_call (engine, unchanged text) | Before I call, I need: {missing} | Call karne se pehle mujhe chahiye: {missing} |
| needs_info (new, no call) | To get this done, I need: {missing} | Yeh karne ke liye mujhe chahiye: {missing} |
Result layout (sent as one message): summary, up to 3 items, "As of ..." line, caveat, pincode ask when relevant, "Sources: <urls>".

## Tests
`tests/planner/` (decision table, guard rules, LLM fallback, wording rule, ASK/CALL agents; web lookup with a fake provider: sources, as-of, caveat, timeout, single retry, cache, unavailable, OpenAI response parsing; gateway through the real pipeline: Zepto price, pincode follow-up, plumber falls through with a vendors-only ack, order pizza, one ack, timeout and "yes" retry). No real network, no calls.

## Not done / next
Answer agent uses the brain (no separate direct LLM port yet); no real connector besides the private browser; web results are not yet stored on a task record; planner decisions are audited but not yet shown in `friday` ops views; hindi (Devanagari) lines fall back to Hinglish; cost of web search not measured.
