# The Ken, "Two by Two" newsletter/episode on personal AI assistants in India (founder's 12 screenshots, 2026-10-27)

Source: screenshots of a The Ken newsletter + podcast transcript (guests: the co-founder of a "social layer for AI" company and the founder of a consumer-research lab). Quotes below are short paraphrases; survey respondents are anonymous. Not verified beyond what the screenshots show. A blurred bank-SMS notification in one screenshot was ignored (no personal data recorded).

## 1. The survey: what subscribers want an assistant to take away (16 clusters, share of answers)
Where did my money go? 10.5% | Managing the family's health 9.6% | Planning the trip 9.4% | What to cook today 9.2% | Madam, OTP? 7.1% | Sticking to the goal 6.7% | Getting your money back 6.6% | Finding the exact right thing 5.9% | Running your wedding 5.5% | Keeping the machines running 5.2% | Renting a home 5.1% | Looking after the pet 4.3% | Keeping up with the school 4.3% | Buying insurance 3.9% | Getting the slot 3.5% | Getting the visa 3.3%.
Sample asks: vehicle ownership transfer when Aadhaar address is in another state (RTO "agent"); triaging a 300-message group chat for what needs my reply; coordinating who walks/feeds the dog.
Context stated: Instinct valued at ~$2.5B within weeks (Aug), Meta followed with "Muse"; 6,000+ student teams building agents for these 16 problems.

## 2. What the guests argued
- **Culture of delegation:** India already offloads (cooks, drivers, RTO agents, CAs). Adoption is not blocked by culture.
- **But adoption is low because of trust and value:** most people are value-driven ("if it can earn me money, get me a loan, build my credit score"); everyday automation is the "1% problem". Marketplaces are big in India because they enforce trust; "I don't see how AI agents enforce trust."
- **Trust ladder:** start with low-trust tasks, build trust, then hand over high-trust decisions (like ChatGPT as a bridge).
- **Side effects of agents in the real world:** an agent got quotes by typing the user's phone number into 14 insurance sites, so the user then got 14 sales calls.
- **Disintermediation:** an agent could call 10 cabs and save the ~20% commission; trust is the blocker.
- **Agents are a harness around the model:** evals make them more predictable than the raw model; power law favours well-funded teams with talent for eval harnesses.
- **Churn risk:** a general assistant (~Rs 1,000/month) can do 80% of a single-purpose service at Rs 350; vertical agents survive where there is social status or real specialisation.
- **WhatsApp:** some people find it "too personal" for an agent (prefer Telegram/Slack), yet would hand over GST payments and CA OTP chasing.
- **Instinct usage example:** "every 20 minutes check every show near me and tell me which is filling" (monitoring/polling as a feature).
- **Small-business view:** a hardware-store owner gets ~10 calls an hour (stock, price, negotiation, unsettled bills); things move only when he personally shows up.

## 3. What this means for Friday (my reading, to decide)
1. **Top asks map to our scope:** money tracking ("where did my money go": savings/bills/life state), trip planning (items D/E/F), cooking, OTP/forms, refunds (item C), health (assist-only), wedding (not now).
2. **Trust is the product:** our approval-first rule, proof on every "done" (B), kill switch and never storing OTP/PIN are the right answer to "how do agents enforce trust". Make them visible in the pitch.
3. **Protect the user's phone number:** vendor quote flows must not spray the user's number. Friday should use Friday's own number/callback and an anonymised contact for vendor forms and calls (we already call vendors from Friday's number; browser forms must never type the user's number without approval; add a "lead-spray guard" rule: max N vendors per request, one at a time).
4. **Monitoring is a feature:** "watch X every 20 minutes and tell me" (seats, price, reply, refund status): candidate item after the beta list (needs a polling task type with a cap).
5. **WhatsApp reluctance:** keep the option of voice calls and a web/Telegram-free path off the beta; note as a risk, not a change.
6. **Do not be a generic assistant:** differentiate on India-specific verticals done end to end with calls (vendor calling, receptionist, hold-fighting), as the guests suggest vertical agents survive.
7. **Value-driven users:** lead with money outcomes (savings found, refunds recovered, bills tracked) over convenience.
8. **Vendor side is real:** shop owners drown in calls: receptionist-for-businesses (later "vendor-side", already in the settled list) has evidence of need.
