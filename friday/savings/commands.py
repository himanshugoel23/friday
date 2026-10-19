"""WhatsApp-facing command handlers of the savings engine (thin, behind interfaces).

The front door asks ``SavingsCommands.handle(user_id, text)`` for every text message and
``handle_button(user_id, button_id)`` for every button tap; both return a :class:`Reply` or None
("not mine, carry on"). Nothing here sends a message: the caller sends the reply. The lead connects
it in one place (see docs/SAVINGS_ENGINE.md, "Connecting it").

Commands: "kaun sa card Zomato pe 640", "mere paas HDFC Regalia aur SBI Cashback hai",
"SBI Cashback hata do", "mere cards", a forwarded bill, "meri bills", "is mahine kitna bachaya".
Buttons: ``led:<entry>:used|other|skip`` (card outcome) and ``bill:<id>:ok|paid|snooze|notmine``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

from friday.core.clock import Clock, at_ist, ist_date
from friday.core.models import ReplyButton
from friday.savings import copy
from friday.savings.bills import (
    Bill,
    BillKind,
    BillSource,
    BillStatus,
    bill_from_parse,
    parse_bill_button,
    parse_bill_text,
)
from friday.savings.calculator import best_card
from friday.savings.categories import parse_purchase
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig
from friday.savings.rules import CardRule
from friday.savings.savings_ledger import MonthlySummary, Outcome, SavingsLedger
from friday.savings.wallet import (
    SensitiveDataError,
    UserCard,
    ensure_not_sensitive,
    match_cards,
    parse_card_chunk,
    parse_wallet_message,
)


class WalletPort(Protocol):
    async def list(self, user_id: str) -> list[UserCard]: ...
    async def get_by_key(self, user_id: str, card_key: str) -> UserCard | None: ...
    async def upsert(self, card: UserCard) -> UserCard: ...
    async def remove(self, user_id: str, card_key: str) -> bool: ...


class RulesPort(Protocol):
    async def verified_rules(self, today: date) -> list[CardRule]: ...


class BillsPort(Protocol):
    async def save(self, bill: Bill) -> Bill: ...
    async def get(self, user_id: str, bill_id: str) -> Bill | None: ...
    async def active_for_user(self, user_id: str) -> list[Bill]: ...


@dataclass
class Reply:
    text: str
    buttons: list[ReplyButton] = field(default_factory=list)


def _buttons(pairs: list[tuple[str, str]]) -> list[ReplyButton]:
    return [ReplyButton(id=i, title=t) for i, t in pairs[:3]]


_ASK_CARD = re.compile(
    r"\b(kaun\s*sa|kon\s*sa|konsa|kaunsa|which|best)\s+(?:credit\s+|debit\s+)?card\b", re.I
)
_SUMMARY = re.compile(
    r"(kitna|kitne|how\s+much).{0,30}(bachaya|bachae|bacha|saved?|save)|"
    r"(bachat|savings?)\s*(summary|report|dikhao|batao|kitni)?\s*$|mahine\s+ki\s+bachat|"
    r"is\s+mahine.{0,20}(bachat|savings?)",
    re.I,
)
_BILLS_LIST = re.compile(
    r"^\s*(?:meri|my|mere)\s+bills?\b|\bbills?\s+(?:dikhao|dikha|list|show|batao)\b|"
    r"\bkaun\s*si\s+bills?\s+(?:due|baaki)\b",
    re.I,
)
_BILL_HINT = re.compile(r"\b(bill|statement|recharge|due|payable|invoice|dth)\b", re.I)
_USUAL = re.compile(r"\b(usual|default|regular|roz\s+ka|main\s+zyada)\b.{0,20}\bcard\b", re.I)


class SavingsCommands:
    def __init__(
        self,
        *,
        wallet: WalletPort,
        rules: RulesPort,
        bills: BillsPort,
        ledger: SavingsLedger,
        clock: Clock,
        config: SavingsConfig = DEFAULT_CONFIG,
    ) -> None:
        self.wallet, self.rules, self.bills, self.ledger = wallet, rules, bills, ledger
        self.clock, self.config = clock, config

    def _today(self) -> date:
        return ist_date(self.clock.now())

    # ------------------------------------------------------------------ router
    async def handle(self, user_id: str, text: str) -> Reply | None:
        """A reply when the message is a savings command, else None."""
        if not text or not text.strip():
            return None
        if _ASK_CARD.search(text):
            return await self.which_card(user_id, text)
        if _SUMMARY.search(text):
            return await self.summary(user_id)
        if _BILLS_LIST.search(text):
            return await self.list_bills(user_id)
        if self._looks_like_bill(text):
            return await self.add_bill(user_id, text)
        if _USUAL.search(text):
            return await self.set_usual(user_id, text)
        intent = parse_wallet_message(text)
        if intent.sensitive:
            return Reply(copy.SENSITIVE_REFUSAL)
        if intent.kind == "list":
            return await self.list_cards(user_id)
        if intent.kind == "add":
            return await self.add_cards(user_id, intent)
        if intent.kind == "remove":
            return await self.remove_cards(user_id, intent)
        return None

    async def handle_button(self, user_id: str, button_id: str) -> Reply | None:
        if button_id.startswith("led:"):
            return await self._ledger_button(user_id, button_id)
        parsed = parse_bill_button(button_id)
        if parsed:
            return await self._bill_button(user_id, *parsed)
        return None

    # ------------------------------------------------------------------ which card
    async def which_card(self, user_id: str, text: str) -> Reply:
        wallet = await self.wallet.list(user_id)
        if not wallet:
            return Reply(copy.NO_CARDS_FOR_QUESTION)
        p = parse_purchase(text)
        if p.ask == "amount":
            return Reply(copy.ASK_AMOUNT)
        if p.ask == "which_amount":
            return Reply(copy.ASK_WHICH_AMOUNT)
        if p.ask in {"category", "which_category"} or p.category is None or p.amount_paise is None:
            return Reply(copy.ask_category(p.options))
        today = self._today()
        rules = await self.rules.verified_rules(today)
        ranking = best_card(
            p.amount_paise, p.category, wallet, rules, today, p.merchant, config=self.config
        )
        if not ranking.options:
            return Reply(copy.no_rules_answer(ranking))
        entry = await self.ledger.record_recommendation(user_id, ranking, wallet)
        pending = entry is not None and entry.outcome == Outcome.PENDING
        buttons = _buttons(copy.outcome_buttons(entry.id)) if entry and pending else []
        return Reply(copy.recommendation(ranking, self.config.max_options_shown), buttons)

    async def _ledger_button(self, user_id: str, button_id: str) -> Reply | None:
        parts = button_id.split(":")
        if len(parts) != 3 or parts[2] not in {"used", "other", "skip"}:
            return None
        outcome = {
            "used": Outcome.USED_RECOMMENDED, "other": Outcome.USED_OTHER, "skip": Outcome.SKIPPED
        }[parts[2]]
        entry, changed = await self.ledger.report_outcome(user_id, parts[1], outcome)
        if entry is None:
            return Reply(copy.OUTCOME_UNKNOWN)
        if not changed:
            return Reply(copy.OUTCOME_ALREADY)
        if outcome == Outcome.USED_RECOMMENDED:
            await self._book_use(user_id, entry)
        texts = {
            Outcome.USED_RECOMMENDED: copy.OUTCOME_USED,
            Outcome.USED_OTHER: copy.OUTCOME_OTHER,
        }
        return Reply(texts.get(outcome, copy.OUTCOME_SKIP))

    async def _book_use(self, user_id: str, entry) -> None:  # noqa: ANN001
        """The user used the recommended card: count its reward against the monthly cap."""
        card = await self.wallet.get_by_key(user_id, entry.recommended_card_key)
        today = self._today()
        if card is None or entry.on_date.strftime("%Y-%m") != f"{today:%Y-%m}":
            return
        same_month = card.caps_month == f"{today:%Y-%m}"
        spend = card.monthly_spend_so_far_paise if same_month else 0
        card = card.with_cap_used(entry.rule_scope or "all", entry.recommended_reward_paise, today)
        await self.wallet.upsert(
            card.model_copy(update={"monthly_spend_so_far_paise": spend + entry.spend_paise})
        )

    async def summary(self, user_id: str) -> Reply:
        s: MonthlySummary = await self.ledger.monthly_summary(user_id)
        return Reply(copy.monthly_summary(s))

    # ------------------------------------------------------------------ wallet
    async def add_cards(self, user_id: str, intent) -> Reply:  # noqa: ANN001
        have = {c.card_key for c in await self.wallet.list(user_id)}
        rules = await self.rules.verified_rules(self._today())
        ruled = {r.card_key for r in rules}
        new, dup, no_rules = [], [], []
        for pc in intent.cards:
            try:
                ensure_not_sensitive(pc.bank, "bank")
                ensure_not_sensitive(pc.card_name, "card_name")
                card = UserCard(
                    user_id=user_id, bank=pc.bank, card_name=pc.card_name, network=pc.network,
                    added_at=self.clock.now(),
                )
            except SensitiveDataError:
                return Reply(copy.SENSITIVE_REFUSAL)
            except ValueError:
                intent.unclear.append(f"{pc.bank} {pc.card_name}")
                continue
            if card.card_key in have:
                dup.append(card.display)
                continue
            await self.wallet.upsert(card)
            have.add(card.card_key)
            new.append(card.display)
            if card.card_key not in ruled:
                no_rules.append(card.display)
        return Reply(copy.wallet_added(new, dup, intent.unclear, no_rules))

    async def remove_cards(self, user_id: str, intent) -> Reply:  # noqa: ANN001
        queries = [f"{c.bank} {c.card_name}" for c in intent.cards] + list(intent.unclear)
        done: list[str] = []
        notes: list[str] = []
        for q in queries:
            cards = await self.wallet.list(user_id)
            hits = match_cards(cards, q)
            if not hits:
                notes.append(copy.wallet_not_found(q))
            elif len(hits) > 1:
                notes.append(copy.wallet_ambiguous(q, [h.display for h in hits]))
            else:
                await self.wallet.remove(user_id, hits[0].card_key)
                done.append(copy.wallet_removed(hits[0].display))
        return Reply(" ".join([*done, *notes]))

    async def list_cards(self, user_id: str) -> Reply:
        cards = await self.wallet.list(user_id)
        if not cards:
            return Reply(copy.WALLET_EMPTY)
        usual = next((c.display for c in cards if c.usual), None)
        return Reply(copy.wallet_list([c.display for c in cards], usual))

    async def set_usual(self, user_id: str, text: str) -> Reply | None:
        body = _USUAL.sub(" ", text)
        body = re.sub(
            r"\b(hai|he|hain|mera|meri|mere|is|my|set|karo|kar\s*do)\b", " ", body, flags=re.I
        )
        parsed = parse_card_chunk(body)
        query = body if isinstance(parsed, str) else (
            f"{parsed.bank} {parsed.card_name}" if parsed else ""
        )
        hits = match_cards(await self.wallet.list(user_id), query) if query else []
        if len(hits) != 1:
            return Reply(copy.wallet_not_found(query.strip() or text.strip()))
        for c in await self.wallet.list(user_id):
            want = c.card_key == hits[0].card_key
            if c.usual != want:
                await self.wallet.upsert(c.model_copy(update={"usual": want}))
        return Reply(copy.usual_set(hits[0].display))

    # ------------------------------------------------------------------ bills
    def _looks_like_bill(self, text: str) -> bool:
        if not _BILL_HINT.search(text):
            return False
        parse = parse_bill_text(text, self._today())
        # a due date makes it a bill to remember; a known kind plus an amount is a bill missing
        # its date (we then ask for it)
        return parse.due_date is not None or (
            parse.kind != BillKind.OTHER and parse.amount_paise is not None
        )

    async def add_bill(
        self, user_id: str, text: str, source: BillSource = BillSource.FORWARDED
    ) -> Reply:
        parse = parse_bill_text(text, self._today())
        if parse.sensitive:
            return Reply(copy.SENSITIVE_REFUSAL)
        if not parse.usable:
            return Reply(copy.bill_need_due(parse.missing))
        bill = bill_from_parse(user_id, parse, source)
        await self.bills.save(bill)
        msg, pairs = copy.bill_confirm(bill)
        return Reply(msg, _buttons(pairs))

    async def list_bills(self, user_id: str) -> Reply:
        bills = await self.bills.active_for_user(user_id)
        if not bills:
            return Reply(copy.BILLS_NONE)
        return Reply(copy.bills_list(sorted(bills, key=lambda b: b.due_date), self._today()))

    async def _bill_button(self, user_id: str, bill_id: str, action: str) -> Reply:
        bill = await self.bills.get(user_id, bill_id)
        if bill is None:
            return Reply(copy.BILL_UNKNOWN)
        now: datetime = self.clock.now()
        if action == "ok":
            bill.confirmed = True
            await self.bills.save(bill)
            return Reply(copy.bill_confirmed(bill))
        if action == "paid":
            bill.status, bill.paid_at, bill.snoozed_until = BillStatus.PAID, now, None
            await self.bills.save(bill)
            return Reply(copy.bill_paid(bill))
        if action == "snooze":
            hour = self.config.bill_reminder_hour_ist
            bill.status = BillStatus.SNOOZED
            bill.snoozed_until = at_ist(ist_date(now) + timedelta(days=1), hour)
            await self.bills.save(bill)
            return Reply(copy.bill_snoozed(hour))
        bill.status, bill.snoozed_until = BillStatus.DISMISSED, None
        await self.bills.save(bill)
        return Reply(copy.BILL_DISMISSED)
