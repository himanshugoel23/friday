# Private browser: train, shopping, Swiggy (Builder C notes)

Founder decision 2026-10-27: build the private browser for every site first. Everything here is tested
against FAKE sites only (no network, no real accounts). **Every real selector is a guess against a fake**;
real runs need legal status `cleared`, `FRIDAY_BROWSER_SITES_ENABLED` and a founder-supervised session.
All new wording lives in each package's `copy.py` and is **PENDING founder approval** (hear before change).

## Adapters (keys `"<catalog site key>.<use case>"`; each package exports `ADAPTERS` and `FAKE_SITES`, lazily)
| Key | Package | What |
|---|---|---|
| `irctc.train` | `sites/train` | book: password via `CredentialService.autofill`, then the site's own code (one-time page) |
| `ixigo.train` | `sites/train` | book: phone + the site's own code |
| `erail.train_info` | `sites/train` | read-only timetable + seat info, no login, no clicks, no booking |
| `amazon.shopping`, `flipkart.shopping` | `sites/shopping` | buy, track order (read-only), cancel order (irreversible, own approval) |
| `swiggy.food` | `sites/swiggy` | `FoodAdapter` reused; Swiggy allow-list, mandatory address, add-ons unticked |

Shared helpers (no import of `sites/adapters.py`, so no cycle): `sites/train/common.py` (HandOver, AddOnStuck,
`allowed_hosts` from `catalog.policy_hosts`, `build_kit`, `read_payment`, `SimSession`); `sites/train/base.py`
(`ScriptedAdapter`). Fakes: `sites/fakes/{train,shopping,swiggy}_site.py` with knobs for sold out / waitlist,
price rise after approval, login expired, captcha / block page, pre-ticked (and sticky) add-ons, missing variant,
closed booking window, injection text in titles.

## Rules and how they are kept
* Passwords: only `CredentialService.autofill` types them (the sim refuses a password fill otherwise); codes only from `OneTimeOtpChannel`.
  Logs hold selector keys only. Tests assert no password, code or username in calls, traces, proposals or audit.
* Passengers (name, age, gender, berth), variants, train / product pick, class, date and quota are asked, never defaulted.
  Tatkal only when the user says so. Shortlists: at most 5, availability and ratings shown as the site shows them.
* Waitlist and RAC tickets: `details["extra_approval"]` must be answered with the exact phrase `WAITLIST OK`
  (`details["extra_approval_given"]=True`); until then `execute` touches nothing and re-asks.
* Captcha and a closed booking window raise `HandOver` (a `SiteBlocked`): stop, give the link, never solve or retry.
* Add-ons, plans, trials, subscriptions, tips are unticked; if one stays, `reapprove` with the real total and `notes["addon_stuck"]`.
* Price rise, changed availability or a different delivery address after approval: `reapprove` (never silent).
* One irreversible click (`book_confirm`, `order_confirm_button`, `cancel_confirm_button`, Swiggy `checkout_button`), armed only after the gate allowed it.
* Cancel needs its own grant (`ShopGate`, `sites/shopping/gate.py`): a purchase approval never covers it.

## Shared-file changes needed (not made by Builder C)
1. `sites/adapters.py`: at the END of the file: `from friday.connectors.sites import shopping, swiggy, train` then
   `for m in (train, shopping, swiggy): ADAPTERS.update(m.ADAPTERS)` (verified cycle-free).
2. `flow.py` `QUESTION_KEY` / `_missing`: use `adapter.missing(slots)` when present, and render the question from
   `adapter.pending["text_key"]` (keys in each `copy.py`, `QUESTION_KEYS`); `Problem.kind` values `need_choice` /
   `need_detail` mean "ask the user" (options in `adapter.pending["options"]`), `over_budget` / `not_allowed` / `not_supported` are stops.
3. `flow.py` approval and summary text: pick `approve_train` / `approve_shopping` / `approve_cancel_order` by connector
   or `details["mode"]`; when `details["extra_approval"]` show `approve_train_waitlist` and accept only the phrase; skip
   approval when `details["read_only"]` (track order, eRail) and send `ExecResult.reason` (status `info`); status `done` for cancel.
4. `flow.py` `_failure`: for `HandOver` use `e.reason` (`captcha` / `booking_window`) to choose `handover_captcha` / `handover_window`.
5. `RunCtx`: add `credentials: CredentialService | None = None` and have the flow pass it (IRCTC reads `ctx.credentials`).
6. `ExecResult.status`: widen the Literal with `info`, `done`; `Problem.kind` with the kinds above (runtime does not enforce them).
7. `planner.py` / `_quick`: intents and slots for `train`, `shopping`, `food` on Swiggy (`from`, `to`, `date`, `cls`, `quota`, `passengers`, `train`; `query`, `pick`, `variant`, `address`, `intent`).
8. `sim.py`: register `FAKE_SITES` factories (`factory(**state_kwargs) -> FakeSiteKit(state, new_session)`).

## Assumptions to confirm
Fee ceilings (`FEE_CAP_PER_TICKET` ₹150, `FEE_MARGIN` ₹100 for shopping) are guesses; RAC is treated like waitlist (extra approval).
