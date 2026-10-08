"""Tasks, calls (+ transcript turns, quotes), mid-call questions, hotel bookings."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import or_, select

from friday.core.models import (
    Beneficiary,
    BusinessCandidate,
    CallResult,
    CallTurn,
    CareOutcome,
    ContactTarget,
    Delegation,
    HotelBooking,
    HotelProperty,
    MidCallQuestion,
    Quote,
    RecurrenceRule,
    ShortlistItem,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    Transcript,
    UserAnswer,
    new_id,
)
from friday.db.repositories._base import (
    Repo,
    copy_simple,
    dump_json,
    dump_json_list,
    phone_index,
    row_dict,
)
from friday.db.tables import (
    CallMemoryRow,
    CallQuestionRow,
    CallRow,
    CallTurnRow,
    CostEntryRow,
    HotelBookingRow,
    QuoteRow,
    TaskRow,
)

OPEN_STATUSES = [s.value for s in TaskStatus if not s.is_terminal]


def _task_values(task: Task) -> dict:
    v = copy_simple(
        task,
        TaskRow,
        skip={"spec", "target", "recurrence", "result", "candidate", "shortlist", "delegation"},
    )
    v["beneficiary_person_id"] = task.beneficiary.person_id
    v["spec"] = task.spec.model_dump(mode="json")
    v["target"] = dump_json(task.target)
    v["recurrence"] = dump_json(task.recurrence)
    v["next_run_at"] = task.recurrence.next_run_at if task.recurrence else None
    v["result"] = dump_json(task.result)
    v["candidate"] = dump_json(task.candidate)
    v["shortlist"] = dump_json_list(list(task.shortlist))
    v["delegation"] = dump_json(task.delegation)
    return v


def _task(row: TaskRow) -> Task:
    d = row_dict(
        row,
        skip={
            "beneficiary_person_id",
            "next_run_at",
            "spec",
            "target",
            "recurrence",
            "result",
            "candidate",
            "shortlist",
            "delegation",
        },
    )
    d["beneficiary"] = Beneficiary(person_id=row.beneficiary_person_id)
    d["spec"] = TaskSpec.model_validate(row.spec)
    d["target"] = ContactTarget.model_validate(row.target) if row.target else None
    d["recurrence"] = RecurrenceRule.model_validate(row.recurrence) if row.recurrence else None
    d["result"] = TaskResult.model_validate(row.result) if row.result else None
    d["candidate"] = BusinessCandidate.model_validate(row.candidate) if row.candidate else None
    d["shortlist"] = [ShortlistItem.model_validate(x) for x in row.shortlist or []]
    d["delegation"] = Delegation.model_validate(row.delegation) if row.delegation else Delegation()
    return Task.model_validate(d)


def _quote(row: QuoteRow) -> Quote:
    return Quote.model_validate(row_dict(row, skip={"id", "created_at"}))


def _question(row: CallQuestionRow) -> MidCallQuestion:
    return MidCallQuestion.model_validate(
        row_dict(
            row,
            skip={"answer_text", "answer_option_index", "answer_approves", "answered_at"},
        )
    )


class TaskRepo(Repo):
    """Implements ``friday.core.interfaces.TaskRepository`` (+ extras for the engine,
    proactive engine and API)."""

    # ------------------------------------------------------------------ tasks
    async def get(self, task_id: str) -> Task | None:
        async with self.db.session() as s:
            row = await s.get(TaskRow, task_id)
            return _task(row) if row else None

    async def add(self, task: Task) -> Task:
        async with self.db.session() as s:
            s.add(TaskRow(**_task_values(task)))
        return task

    async def save(self, task: Task) -> Task:
        task.updated_at = self.now()
        async with self.db.session() as s:
            await s.merge(TaskRow(**_task_values(task)))
        return task

    async def set_status(self, task_id: str, status: TaskStatus) -> Task:
        async with self.db.session() as s:
            row = await s.get(TaskRow, task_id)
            if row is None:
                raise KeyError(f"task {task_id} not found")
            row.status = status.value
            row.updated_at = self.now()
            return _task(row)

    async def list_for_user(self, user_id: str, *, open_only: bool = False) -> list[Task]:
        async with self.db.session() as s:
            q = select(TaskRow).where(TaskRow.requester_user_id == user_id)
            if open_only:
                q = q.where(TaskRow.status.in_(OPEN_STATUSES))
            rows = (await s.execute(q.order_by(TaskRow.created_at))).scalars()
            return [_task(r) for r in rows]

    async def list_children(self, parent_task_id: str) -> list[Task]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TaskRow)
                    .where(TaskRow.parent_task_id == parent_task_id)
                    .order_by(TaskRow.created_at)
                )
            ).scalars()
            return [_task(r) for r in rows]

    async def list_due(self, now: datetime) -> list[Task]:
        """SCHEDULED tasks with next_attempt_at <= now, plus non-terminal recurring
        parents whose recurrence.next_run_at <= now."""
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TaskRow)
                    .where(
                        or_(
                            (TaskRow.status == TaskStatus.SCHEDULED.value)
                            & (TaskRow.next_attempt_at.is_not(None))
                            & (TaskRow.next_attempt_at <= now),
                            (TaskRow.status.in_(OPEN_STATUSES))
                            & (TaskRow.next_run_at.is_not(None))
                            & (TaskRow.next_run_at <= now),
                        )
                    )
                    .order_by(TaskRow.next_attempt_at, TaskRow.created_at)
                )
            ).scalars()
            return [_task(r) for r in rows]

    async def list_by_status(self, *statuses: TaskStatus) -> list[Task]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TaskRow)
                    .where(TaskRow.status.in_([st.value for st in statuses]))
                    .order_by(TaskRow.created_at)
                )
            ).scalars()
            return [_task(r) for r in rows]

    async def list_open(self) -> list[Task]:
        """All non-terminal tasks (engine recovery after restart)."""
        return await self.list_by_status(*(TaskStatus(s) for s in OPEN_STATUSES))

    async def list_created_between(
        self, user_id: str, start: datetime, end: datetime
    ) -> list[Task]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TaskRow)
                    .where(
                        TaskRow.requester_user_id == user_id,
                        TaskRow.created_at >= start,
                        TaskRow.created_at < end,
                    )
                    .order_by(TaskRow.created_at)
                )
            ).scalars()
            return [_task(r) for r in rows]

    # ------------------------------------------------------------------ calls
    async def save_call(self, result: CallResult) -> None:
        """Persist one call attempt: call row, transcript turns, quotes, questions
        with answers, and a ``call`` entry in the internal cost ledger. Does NOT
        modify the task row (the engine owns task.cost_inr_est / attempts)."""
        async with self.db.session() as s:
            task_row = await s.get(TaskRow, result.task_id)
            business_id = None
            mode = "agent"
            if task_row is not None:
                if task_row.target:
                    business_id = task_row.target.get("business_id")
                mode = (task_row.spec or {}).get("call_mode", "agent")
            existing = await s.get(CallRow, result.call_id)
            if existing is not None:  # re-save: replace children
                for child in (
                    await s.execute(
                        select(CallTurnRow).where(CallTurnRow.call_id == result.call_id)
                    )
                ).scalars():
                    await s.delete(child)
                for child in (
                    await s.execute(select(QuoteRow).where(QuoteRow.call_id == result.call_id))
                ).scalars():
                    await s.delete(child)
                await s.flush()
            await s.merge(
                CallRow(
                    id=result.call_id,
                    task_id=result.task_id,
                    provider=result.provider,
                    provider_call_id=result.provider_call_id,
                    direction=result.direction.value,
                    to_phone=result.to_phone,
                    business_id=business_id,
                    dial_status=result.dial_status.value,
                    outcome=result.outcome.value,
                    collected=dict(result.collected),
                    languages_heard=[lang.value for lang in result.languages_heard],
                    care=dump_json(result.care),
                    hold_seconds=result.hold_seconds,
                    cost_inr_est=result.cost_inr_est,
                    mode=mode,
                    recording_url=result.recording_url,
                    started_at=result.started_at,
                    answered_at=result.answered_at,
                    ended_at=result.ended_at,
                    error=result.error,
                    from_number=result.from_number,
                )
            )
            await s.flush()
            for seq, turn in enumerate(result.transcript.turns):
                s.add(
                    CallTurnRow(
                        call_id=result.call_id,
                        seq=seq,
                        speaker=turn.speaker.value,
                        text=turn.text,
                        language=turn.language.value if turn.language else None,
                        confidence=turn.confidence,
                        at=turn.at,
                    )
                )
            for q in result.quotes:
                s.add(self._quote_row(q, result.task_id, result.call_id))
            answers = {a.question_id: a for a in result.answers}
            for question in result.questions:
                await s.merge(
                    self._question_row(question, answers.get(question.id), result.call_id)
                )
            if task_row is not None:
                await self._remember_call(s, task_row, result, business_id)
            if task_row is not None and existing is None and result.cost_inr_est:
                s.add(
                    CostEntryRow(
                        user_id=task_row.requester_user_id,
                        task_id=result.task_id,
                        call_id=result.call_id,
                        kind="call",
                        amount_inr=result.cost_inr_est,
                        at=result.ended_at or result.started_at,
                    )
                )

    async def _remember_call(self, s, task_row: TaskRow, result: CallResult, business_id) -> None:  # noqa: ANN001
        """Call memory (E30): upsert by call_id; keeps an already-recorded caller ID."""
        mem = (
            await s.execute(select(CallMemoryRow).where(CallMemoryRow.call_id == result.call_id))
        ).scalar_one_or_none()
        if mem is None:
            mem = CallMemoryRow(
                id=new_id(),
                call_id=result.call_id,
                task_id=result.task_id,
                user_id=task_row.requester_user_id,
                business_phone=result.to_phone,
                business_phone_hmac=phone_index(result.to_phone),
                direction=result.direction.value,
                at=result.started_at,
            )
            s.add(mem)
        if result.from_number:
            mem.friday_number = result.from_number
        mem.business_id = mem.business_id or business_id
        mem.outcome = result.outcome.value

    @staticmethod
    def _quote_row(q: Quote, task_id: str, call_id: str | None) -> QuoteRow:
        v = copy_simple(q, QuoteRow, skip={"task_id", "call_id"})
        return QuoteRow(task_id=q.task_id or task_id, call_id=q.call_id or call_id, **v)

    @staticmethod
    def _question_row(
        q: MidCallQuestion, answer: UserAnswer | None, call_id: str | None = None
    ) -> CallQuestionRow:
        return CallQuestionRow(
            id=q.id,
            task_id=q.task_id,
            call_id=q.call_id or call_id,
            purpose=q.purpose.value,
            text=q.text,
            options=list(q.options),
            timeout_s=q.timeout_s,
            asked_at=q.asked_at,
            answer_text=answer.text if answer else None,
            answer_option_index=answer.option_index if answer else None,
            answer_approves=answer.approves if answer else None,
            answered_at=answer.answered_at if answer else None,
        )

    async def get_call(self, call_id: str) -> CallResult | None:
        async with self.db.session() as s:
            row = await s.get(CallRow, call_id)
            if row is None:
                return None
            return await self._call_from_row(s, row)

    async def list_calls(self, task_id: str) -> list[CallResult]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(CallRow)
                        .where(CallRow.task_id == task_id)
                        .order_by(CallRow.started_at)
                    )
                )
                .scalars()
                .all()
            )
            return [await self._call_from_row(s, r) for r in rows]

    async def _call_from_row(self, s, row: CallRow) -> CallResult:  # noqa: ANN001
        turns = (
            await s.execute(
                select(CallTurnRow).where(CallTurnRow.call_id == row.id).order_by(CallTurnRow.seq)
            )
        ).scalars()
        quotes = (await s.execute(select(QuoteRow).where(QuoteRow.call_id == row.id))).scalars()
        qrows = (
            (await s.execute(select(CallQuestionRow).where(CallQuestionRow.call_id == row.id)))
            .scalars()
            .all()
        )
        return CallResult(
            call_id=row.id,
            task_id=row.task_id,
            provider=row.provider,
            provider_call_id=row.provider_call_id,
            direction=row.direction,
            to_phone=row.to_phone,
            dial_status=row.dial_status,
            outcome=row.outcome,
            transcript=Transcript(
                turns=[
                    CallTurn(
                        speaker=t.speaker,
                        text=t.text,
                        at=t.at,
                        language=t.language,
                        confidence=t.confidence,
                    )
                    for t in turns
                ]
            ),
            collected=row.collected or {},
            quotes=[_quote(q) for q in quotes],
            questions=[_question(q) for q in qrows],
            answers=[_answer(q) for q in qrows if q.answered_at is not None],
            languages_heard=row.languages_heard or [],
            care=CareOutcome.model_validate(row.care) if row.care else None,
            hold_seconds=row.hold_seconds,
            cost_inr_est=row.cost_inr_est,
            recording_url=row.recording_url,
            started_at=row.started_at,
            answered_at=row.answered_at,
            ended_at=row.ended_at,
            error=row.error,
            from_number=row.from_number,
        )

    # ------------------------------------------------------------------ quotes
    async def add_quotes(self, task_id: str, quotes: Iterable[Quote]) -> None:
        async with self.db.session() as s:
            for q in quotes:
                s.add(self._quote_row(q, task_id, q.call_id))

    async def quotes_for_task(self, task_id: str, *, include_children: bool = False) -> list[Quote]:
        async with self.db.session() as s:
            ids = [task_id]
            if include_children:
                ids += list(
                    (
                        await s.execute(select(TaskRow.id).where(TaskRow.parent_task_id == task_id))
                    ).scalars()
                )
            rows = (
                await s.execute(
                    select(QuoteRow).where(QuoteRow.task_id.in_(ids)).order_by(QuoteRow.created_at)
                )
            ).scalars()
            return [_quote(r) for r in rows]

    # ------------------------------------------------------------------ mid-call questions
    async def add_question(self, question: MidCallQuestion) -> MidCallQuestion:
        async with self.db.session() as s:
            await s.merge(self._question_row(question, None))
        return question

    async def get_question(self, question_id: str) -> MidCallQuestion | None:
        async with self.db.session() as s:
            row = await s.get(CallQuestionRow, question_id)
            return _question(row) if row else None

    async def get_answer(self, question_id: str) -> UserAnswer | None:
        async with self.db.session() as s:
            row = await s.get(CallQuestionRow, question_id)
            return _answer(row) if row and row.answered_at else None

    async def answer_question(self, answer: UserAnswer) -> bool:
        """Record an answer; False if unknown or already answered."""
        async with self.db.session() as s:
            row = await s.get(CallQuestionRow, answer.question_id)
            if row is None or row.answered_at is not None:
                return False
            row.answer_text = answer.text
            row.answer_option_index = answer.option_index
            row.answer_approves = answer.approves
            row.answered_at = answer.answered_at
            return True

    async def open_question_for_user(self, user_id: str) -> MidCallQuestion | None:
        """Newest unanswered, unexpired question on one of the user's open tasks."""
        now = self.now()
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallQuestionRow)
                    .join(TaskRow, TaskRow.id == CallQuestionRow.task_id)
                    .where(
                        TaskRow.requester_user_id == user_id,
                        TaskRow.status.in_(OPEN_STATUSES),
                        CallQuestionRow.answered_at.is_(None),
                    )
                    .order_by(CallQuestionRow.asked_at.desc())
                )
            ).scalars()
            for r in rows:
                if (now - r.asked_at).total_seconds() <= max(r.timeout_s, 0) or r.timeout_s <= 0:
                    return _question(r)
            return None

    # ------------------------------------------------------------------ hotel bookings
    async def save_hotel_booking(self, booking: HotelBooking, *, user_id: str) -> HotelBooking:
        v = copy_simple(booking, HotelBookingRow, skip={"property"})
        v["property"] = booking.property.model_dump(mode="json")
        v["user_id"] = user_id
        v["updated_at"] = self.now()
        async with self.db.session() as s:
            await s.merge(HotelBookingRow(**v))
        return booking

    async def get_hotel_booking(self, booking_id: str) -> HotelBooking | None:
        async with self.db.session() as s:
            row = await s.get(HotelBookingRow, booking_id)
            return _hotel(row) if row else None

    async def hotel_bookings_for_task(self, task_id: str) -> list[HotelBooking]:
        async with self.db.session() as s:
            rows = (
                await s.execute(select(HotelBookingRow).where(HotelBookingRow.task_id == task_id))
            ).scalars()
            return [_hotel(r) for r in rows]

    async def hotel_bookings_checking_in(self, day: date) -> list[HotelBooking]:
        async with self.db.session() as s:
            rows = (
                await s.execute(select(HotelBookingRow).where(HotelBookingRow.check_in == day))
            ).scalars()
            return [_hotel(r) for r in rows]


def _answer(row: CallQuestionRow) -> UserAnswer:
    return UserAnswer(
        question_id=row.id,
        text=row.answer_text or "",
        option_index=row.answer_option_index,
        approves=bool(row.answer_approves),
        answered_at=row.answered_at,
    )


def _hotel(row: HotelBookingRow) -> HotelBooking:
    d = row_dict(row, skip={"user_id", "guest_person_id", "business_id", "updated_at", "property"})
    d["property"] = HotelProperty.model_validate(row.property)
    return HotelBooking.model_validate(d)
