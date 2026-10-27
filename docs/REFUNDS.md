# Refund and cancellation tracking (item C)

Status: built, behind `FRIDAY_REFUNDS_ENABLED` (default OFF). Fakes only: nothing here dials, sends or calls a provider. All wording is PENDING founder approval (`friday/refunds/copy.py`, same pattern as the other `copy.py` files). Design: `docs/TRIP_CONCIERGE_DESIGN.md` section C. Migration `0018_refunds`.

Friday never holds or sees the money. Every "received" is the user's word or a document the user supplied, and the reply says so.

## State machine (`friday/refunds/machine.py`, table-tested for every pair)
`suspected -> opened -> requested -> vendor_acknowledged -> promised(date, amount) -> received | rejected | escalated | closed`.
- `suspected` is a PROPOSAL (Friday noticed a cancelled booking, a cancelled order or a disputed bill). Only the user can open it; "no" closes it as declined; a week without an answer lapses it (the only close the system makes, and it was never a real case).
- `opened -> any later state` (a vendor can reject or promise at any point); `promised -> promised` (a new promise); `received -> received` (the rest arrives in instalments); `received -> escalated | closed` (a short refund: chase the rest or accept); `rejected -> escalated | closed`; `escalated -> promised | received | rejected | closed`; `closed` is terminal.
- Guards: a promise needs a date AND an amount; **received needs an amount and a basis (the user's word or proof) and can never come from the system or a timer**; closing needs a reason and **only the user closes a real case**; closing as `received` needs the received amount and the basis.
- Opened from: a cancelled trip leg (hook below), a cancelled order (`propose_from_order`), a bill or charge dispute (`propose_from_bill_dispute`), or the user ("Exampleair ka refund nahi aaya 4500", `open_by_user`). Each proposal is idempotent per origin.

## Reminders (`reminders.py`, `service.run_user/tick`)
Pure schedule, days after the state change (promised: after the promised day): opened 1 (did you ask?), 3 (vendor follow-up), then weekly; requested/acknowledged 3, 7 (vendor follow-up), then weekly; promised +1, +4 (vendor follow-up), then weekly; escalated weekly; rejected once; short refund once; suspected at once and again after 2 days. All offsets are proposals. Rules: reminders go to the USER on WhatsApp only, at 10:00 IST; **quiet hours 22:00-08:00 hold a reminder**; **weekly cap 3 per user per rolling 7 days** across cases (`FRIDAY_REFUND_WEEKLY_CAP`), over cap is held; a reminder held more than 72 h past due is dropped (never sent late); at most 8 per case; a changed state starts a fresh schedule (key `refund:<case>:<epoch>:<n>`, never twice); "refund mute" silences everything. Every proactive line carries a one-clause reason and how to stop. "mera refund kahan hai" is a reply to the user, not a nudge, and is not capped.

## Vendor follow-up (a proposal, never automatic)
At the "followup" stages the user gets a proposal: a call through the existing task engine, and always a message draft the user can send. A call needs `FRIDAY_REFUND_CHASE_CALLS=true` (default OFF), a number from the resolver, and the user's tap. `approve_followup` re-resolves the number (a removed record never gets substituted), then `RefundTaskPort.create_task(spec, approved=False)`: the task engine asks again before it dials and `CallGate` applies. At most 2 approved follow-ups per case. The spec is built by one function (`RefundService.followup_spec`, type `STATUS_CHASE`) so hold-fighting (customer care) can swap it for a `CUSTOMER_CARE` spec later. **The production adapter `EngineRefundTaskPort` refuses to start any call while `copy.CALL_LINE_STATUS` is PENDING** (the questions in `VENDOR_CALL_QUESTIONS` are pending lines; the founder hears audio first). When the follow-up task finishes, `on_followup_finished` links its proof items (levels kept: observed / vendor_stated) and moves an `opened` case to `requested`.

## Who to call (`resolver.py`): a number is never invented
The resolver only returns numbers a `NumberSource` handed it, after `calls.numbers.canonical` (dialable, not an emergency code). Order: the number the user typed, the phone field of a CONFIRMED document of that user (hotel confirmation) matching the vendor, the number on the user's earlier task for that vendor, proof the user supplied, a person-verified vendor record. Names are matched conservatively (`name_match`). For the payment issuer it returns the bank NAME the user gave and a pointer to the card or app; there is no number field for it. With nothing held it says so, asks the user for a number or a photo of the ticket or bill, and offers the message draft. A property test checks the output is always a subset of what the sources supplied.

## Evidence and proof (`evidence.py`)
Same levels and kinds as `friday/evidence` (`observed`, `vendor_stated`, `user_supplied`). Honesty rules: a user can only create `user_supplied` items (a forwarded refund message, a receipt, "aa gaya", a vendor promise they relay); `observed` and `vendor_stated` exist only by linking proof items of a follow-up task Friday ran (`attach_proof_items`: another user's or an expired item is refused). An amount counts as stated only if its digits occur in the forwarded text. No bytes: a receipt keeps its sha-256 and the amount. Summaries and payloads are encrypted. **A case closes as received only on the user's word or on proof that states at least the received amount**; the basis (`user` or `proof`) is stored.

## Expected vs received
`amount_check`: exact (within Rs 1, `FRIDAY_REFUND_AMOUNT_TOLERANCE_PAISE`), over, short, unknown expected. The expected amount is the case amount, else the vendor's promised amount. Exact, over or unknown-expected closes the case; **short stays open** and asks "chase the rest or is this fine" (a later top-up adds to the total).

## Chat (`commands.py`, not yet wired to the router)
"Exampleair ka refund nahi aaya 4500", "mera refund kahan hai" / "where is my refund" (open cases with age), "Exampleair refund aa gaya 4500", "refund maang liya", "Exampleair ne 20 Nov tak 4500 ka kaha" / "Exampleair said 4500 by 20 Nov", "refund rejected / escalate / band karo", "refund number +91...", "refund kisko call karun", "refund mute / unmute". Buttons `refund:<case_id>:<action>` (yes, no, asked, recd, notyet, chase, close, call, nocall); a button of another user's case does nothing.

## Wrapped card
`RefundService.money_recovered(user_id, since)` returns `MoneyRecovered(total_paise, cases, proof_backed)`: ONLY cases closed as `received` with a basis (proof or the user's word). Promised, short-and-open, rejected, dropped and suspected cases count for nothing.

## Trip hook
`TripService(refunds=RefundService)`: when the flight/train status watch reports a cancellation, the trip calls `propose_from_trip_cancellation` (vendor name = the airline part of the label, flight number dropped). It creates a SUSPECTED case only; the next reminder tick asks the user (yes / no). Nothing is requested from anyone. A refund-tracker failure is logged and never breaks the trip message; with refunds OFF no case is made. Orders (`propose_from_order`) and bills (`propose_from_bill_dispute`) have the same entry points but are NOT yet called by the task engine or the bill flow.

## Data (0018_refunds)
`refund_cases`, `refund_events`, `refund_evidence`, `refund_nudges`; `user_id` is the erasure key. Vendor name, user-typed number, bank name, notes, the follow-up proposal, evidence summary and payload, and reminder text are encrypted (field cipher). `DataPurger.purge_user` deletes all four; retention (`expire_refunds`) deletes a CLOSED case 180 days after closing (`FRIDAY_REFUNDS_RETENTION_DAYS`) and never an open one; RLS on with no policy (`deploy/supabase/rls.sql`).

## Switches
`FRIDAY_REFUNDS_ENABLED=false`, `FRIDAY_REFUNDS_ENABLED_USERS` (empty = all), `FRIDAY_REFUND_CHASE_CALLS=false`, `FRIDAY_REFUND_WEEKLY_CAP=3`, `FRIDAY_REFUND_MAX_CHASE_CALLS=2`, `FRIDAY_REFUND_AMOUNT_TOLERANCE_PAISE=100`, `FRIDAY_REFUNDS_RETENTION_DAYS=180`. `ops/doctor` lists the switch and warns when on.

## Not done / needs the founder
- Not wired into the live chat router or the scheduler loop (`RefundCommands`, `RefundService.tick()` are complete and tested); the production `RefundSender` (WhatsApp text + buttons, an approved template for sends outside the 24 h window) is not written; no document/photo handler calls `attach_receipt`/`attach_text` yet.
- No order-cancel or bill-dispute caller; no engine hook that calls `on_followup_finished` when the follow-up task ends.
- The vendor-call questions and every line below are PENDING (hear-before-change); the real follow-up call stays refused until `CALL_LINE_STATUS` is flipped in a reviewed commit after the founder hears audio.
- Reminder offsets, the cap of 3 a week, 10:00 send hour, the 72 h expiry, the 2-follow-up cap, 180-day retention, Rs 1 tolerance: all proposals.
- Hold-fighting is not built; this module only exposes `followup_spec` as the swap point. A founder-entered vendor refund-window table (design `policy_table.py`) is NOT built: no line states a refund window or a legal right.
- Quiet hours and the send hour use IST only. Out-of-window sends need an approved template (same open item as trips and life-state).

## Wording (PENDING_FOUNDER_APPROVAL), copy ids in `friday/refunds/copy.py`
Each id has `hinglish` and `en`. No spoken line exists in this module.
`ack.ok`, `age.days`, `age.today`, `amount.expected`, `amount.part`, `btn.asked`, `btn.call_no`, `btn.call_ok`, `btn.chase`, `btn.close`, `btn.no`, `btn.notyet`, `btn.received`, `btn.yes`, `case.unknown`, `case.which`, `closed.accepted`, `closed.dropped`, `escalated.ok`, `evidence.saved`, `followup.approved`, `followup.call`, `followup.cap`, `followup.declined`, `followup.draft`, `followup.draft_body`, `followup.no_number`, `followup.off`, `illegal`, `level.observed`, `level.user_supplied`, `level.vendor_stated`, `list.footer`, `list.header`, `list.item`, `list.item.promised`, `list.none`, `muted`, `notyet.ok`, `nudge.checkin`, `nudge.received_q`, `nudge.rejected_q`, `nudge.requested_q`, `nudge.short_q`, `number.bad`, `number.saved`, `open.exists`, `open.need_vendor`, `open.ok`, `promised.need`, `promised.ok`, `received.exact`, `received.exact_proof`, `received.need_amount`, `received.over`, `received.short`, `received.unknown`, `rejected.ok`, `requested.ok`, `source.document`, `source.evidence`, `source.task`, `source.user`, `source.vendor_record`, `state.closed`, `state.escalated`, `state.opened`, `state.promised`, `state.received`, `state.rejected`, `state.requested`, `state.suspected`, `state.vendor_acknowledged`, `suspect.again`, `suspect.ask`, `suspect.no`, `suspect.yes`, `unmuted`, `what.bill_dispute`, `what.order`, `what.trip_leg`, `what.user`, `who.header`, `who.issuer`, `who.line`.
Pending call questions (data for a task spec, not a script): `VENDOR_CALL_QUESTIONS` (3 questions x 2 languages).

Tests: `uv run pytest tests/refunds -q`.
