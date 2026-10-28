# Shopping assistant (2026-10-29)

Status: built, tests green with fakes only, switch `FRIDAY_SHOPPING_ASSISTANT_ENABLED` default OFF (needs the approach planner). **All chat lines below are PENDING the founder's approval.** No spoken (voice) line was touched. Web search quality for prices and images has NEVER been run live.

## Why
First live test: "Aata ka rate check krna zepto pr" then pincode and product gave "Iska pakka result nahi mila" three times (quick-commerce prices are mostly not on the open web). Founder: when the user just says "atta", behave like a personal assistant: show the popular brands with data and images, RECOMMEND one, and ask "home or PG?" (never the office unless asked) from the saved places instead of asking for a pincode.

## Flow
```
"atta" -> PlannerGateway.route -> ShoppingAssistant (before the planner; also for a planner WEB_LOOKUP whose query is a catalog category)
   progress line (message 1)  "Checking Zepto, Blinkit, Swiggy Instamart, BigBasket for atta..."
   ShoppingPM --A2A, in parallel--> zepto | blinkit | instamart | bigbasket   (wave 2, only if < 2 core sites showed prices: amazon, jiomart)
        each = GrocerySiteAgent (skill grocery.search) over a GroceryProvider, driven by its versioned knowledge file
   merge (friday/shopping/compare.py, plain code): same brand + pack size = one product with every site's printed offer
        price per kg/L from the PRINTED pack size, rating, label ingredients (category table), delivery time if shown
   headline with ONE pick + reason -> image cards (web chat only) -> comparison, freshness, sources, unread sites
   + ONE question: "Home or PG?" buttons (saved places) or "Ghar ya PG? Share the area or pincode once..." (none saved)
   tap / answer -> place saved (Place store) -> same agents re-run with the pincode/area -> refined message
```
The recommendation never waits for the place.

## Pieces (all in `friday/shopping`, plus 3 small hooks)
- `categories.yaml`: data table of popular choices and what to compare per category (atta, rice, dal, oil, milk, detergent, shampoo). Names only; every number comes from a cited page.
- `sites.py`: the `GroceryProvider` port, `WebGroceryProvider` (public pages via the web lookup port), `GrocerySiteAgent` (A2A handler), knowledge loader. `knowledge/<site>.v1.json` for zepto, blinkit, instamart, bigbasket (core) and amazon, jiomart (extras): domains, query templates, where each fact sits, quirks, safety flags. Status `unverified` until a live run.
- `pm.py`: the shopping PM (only manages: parallel A2A delegation, one budget, waves). `agent.py`: PM + merge + images. `compare.py`: pack parsing, per-unit price, scoring, ONE pick, reason from facts only. `images.py`, `places.py`, `assistant.py`, `wording.py`, `wiring.py`.
- Hooks: `friday/planner/gateway.py` (shopping goes first; planner WEB_LOOKUP on a catalog query), `friday/planner/wiring.py`, `friday/planner/web.py` (WebItem gained optional pack/ingredients/rating-count/image fields), `friday/core/config.py` (2 settings), `deploy/enable-web-test.sh` (name added), web page (below).

## Grounding rules (enforced in code, tested)
- A site agent keeps an item only if its cited page is on THAT site's own domain (Instamart: under /instamart). A price, rating or ingredient is shown only for such an item. No cited page = no number ("price not visible").
- Price per kg/L is computed by us from the price and the pack size printed on the page; no pack size = no per-unit figure.
- The pick is a small deterministic score (price per unit, rating, ingredient phrases from the category table). The reason lists only facts present on the page (lowest per kg, label phrase, rating).
- Out-of-stock offers never lead. The named store (Zepto/Blinkit) with no visible price: "X does not show its own prices online, so these are other sellers' prices", and the sites not read are named.
- Honest freshness: "Prices as of HH:MM IST from public pages. They may differ in the app." Friday never orders or pays; the user opens the app.

## Images
Only from a cited product page: its `og:image` (fetched server side by `HttpOgImages`: https only, public hosts, no redirects, short timeout, size cap) or an image URL the provider itself cited. Web chat only: the message carries the https URL as `media_url` with the title and price as caption; the page shows it with `referrerpolicy=no-referrer`, hides it if it fails to load, and the caption stays. CSP `img-src` gained `https:` (page only loads images the server sent). WhatsApp/simulator: text only for now; the data (`Product.image_url`, title, price line) is ready for an image message later. Never hotlinks anything uncited.

## Delivery place
Saved places are read from the Place store (labels/aliases Home/ghar, PG/hostel, Office only if the user's message mentions office/work). The pincode is read from the saved address. With a saved place there is no pincode question: two buttons. With none: one question, the answer ("PG, Koramangala 560034") is saved as a normal Place, so it shows in "what do you remember" and is erased with "delete everything". A pincode typed in the original message skips the question.

## Zepto official MCP: later, port only (see docs/ZEPTO_MCP_PLAN.md)

## Chat wording (PENDING founder approval; English / Hinglish in `friday/shopping/wording.py`)
- progress: "Checking {sites} for {cat}... one moment." / "{sites} par {cat} check kar rahi hoon... bas ek minute."
- pick: "Here are the {n} popular {cat} choices. I would take {name}: {reason}." / "Yeh rahe {n} popular {cat} options. Main {name} loongi: {reason}."
- no pick: "Here are the popular {cat} choices I found. I could not see enough prices to pick one yet." / "Yeh rahe popular {cat} options. Daam poore nahi dikhe, isliye abhi ek pick nahi kar paayi."
- freshness: "Prices as of {time} IST from public pages. They may differ in the app." / "{time} IST ke daam, public pages se. App mein alag ho sakte hain."
- hidden store: "{store} does not show its own prices online, so these are other sellers' prices." / "{store} apne daam online nahi dikhata, isliye yeh doosre sellers ke daam hain."
- sites read / unread: "I could read prices on {ok} of {n} sites." / "{n} mein se {ok} sites par daam dikhe."; "Could not read: {names} (price not visible online)." / "Yahan nahi padh paayi: {names} (daam online nahi dikhe)."
- place question (saved): "Home or PG? I will check delivery and price for that place." / "Ghar ya PG? Us jagah ke liye delivery aur daam dekh leti hoon."
- place question (none saved): "Ghar ya PG? Share the area or pincode once and I will remember it." / "Ghar ya PG? Area ya pincode ek baar bata dein, main yaad rakhungi."
- place saved: "Saved your {label} ({where}). It shows under 'what do you remember'." / "Aapka {label} ({where}) yaad kar liya. 'what do you remember' mein dikhega."
- refined: "Same pick for {label}: {name}." / "{label} ke liye bhi wahi pick: {name}."; "For {label} I would now take {name}: {reason}." / "{label} ke liye ab main {name} loongi: {reason}."; "Checking again for {label} ({where})." / "{label} ({where}) ke liye dobara dekh rahi hoon."
- area not understood: "I could not read an area from that. Send the area name or a 6 digit pincode." / "Isse area samajh nahi aaya. Area ka naam ya 6 digit pincode bhej dein."
- refine failed: "I could not refresh the prices for that place just now, so the comparison above stands." / "Us jagah ke liye abhi daam refresh nahi ho paaye, upar wali comparison hi sahi maanein."
- soft fail: "I could not read live prices just now. The popular {cat} picks are {names}. Want me to try again in a minute?" / "Abhi live daam nahi padh paayi. Popular {cat} yeh hain: {names}. Ek minute baad dobara try karun?"; down: "I can't look up prices right now. The popular {cat} picks are {names}." / "Abhi daam check nahi kar sakti. Popular {cat} yeh hain: {names}."
- buttons: Home/Ghar, PG, Office; row labels "price not visible" / "daam nahi dikha"; "also" / "aur".

## Honest limits (unverified)
- Never run live: whether the OpenAI web search returns prices, ratings, ingredients and cited pages for these sites, and whether Zepto/Blinkit/Instamart show anything at all. Expect Zepto/Blinkit/Instamart to be "price not visible" often; BigBasket/Amazon/JioMart to carry the comparison. First live check: say "atta" on the web chat and read the log lines `shopping pm: {...}` (statuses only).
- Cost: up to 4 web searches per comparison (6 with extras), another set when a place is chosen (cached 5 min per pincode). Estimated Rs 1 each (`FRIDAY_TEAM_COST_PER_SEARCH_INR`), not measured.
- Merge key is brand + pack size: two variants of one brand at the same size (e.g. Select vs Multigrain 5 kg) would merge. The og:image fetch is not tested against real pages.
- Does not use the team PM (`friday/team`); it has its own small PM over the same A2A package. Joining them is a later step.
