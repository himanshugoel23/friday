import pytest

from friday.core.models import (
    OutboundMessage,
    Person,
    PersonConsent,
    TaskStatus as S,
    TemplateRef,
    User,
)
from friday.tasks import states
from friday.tasks.context import build_context
from friday.tasks.outbox import Outbox
from tests.tasks.fakes import RecordingNotifier, Repos


def test_terminal_states_have_no_exits_and_check():
    for t in (S.COMPLETED, S.FAILED, S.CANCELLED):
        assert states.ALLOWED[t] == frozenset()
    states.check(S.CREATED, S.PLANNING)
    states.check(S.CALLING, S.CALLING)
    with pytest.raises(states.InvalidTransition):
        states.check(S.COMPLETED, S.CALLING)
    with pytest.raises(states.InvalidTransition):
        states.check(S.CREATED, S.CALLING)
    # every non-terminal state can be cancelled
    assert all(S.CANCELLED in v for k, v in states.ALLOWED.items() if not k.is_terminal)
    assert set(states.ALLOWED) == set(S)


async def test_outbox_template_fallback_consent_and_business():
    repos = Repos()
    u = User(phone="+919811111111")
    await repos.users.add(u)
    n = RecordingNotifier()
    out = Outbox(notifier=n, users=repos.users)
    await out.to_user(u.id, "hello " * 300, template_key="question")
    msg = n.last()
    assert msg.to_phone == u.phone and msg.template.key == "question"
    assert len(msg.template.params[0]) <= 900
    p = Person(owner_user_id=u.id, name="Dad", phone="+919822222222")
    assert await out.to_person(p, "hi") is None  # no consent -> nothing sent
    p.contact_consent = PersonConsent.OPTED_IN
    await out.to_person(p, "hi")
    assert n.last().person_id == p.id
    await out.to_business("+918040000001", TemplateRef(key="business_booking_confirmed"))
    assert n.last().channel.value == "sms"


async def test_outbox_fallbacks():
    class Sms:
        def __init__(self):
            self.sent = []

        async def send_template(self, phone, template):
            self.sent.append(phone)

    class OldNotifier:  # no urgency kwarg
        def __init__(self):
            self.got = []

        async def send(self, msg: OutboundMessage):
            self.got.append(msg)

    sms = Sms()
    out = Outbox(notifier=None, users=None, sms=sms)
    assert await out.to_user("u", "x") is None
    await out.to_business("+918040000001", TemplateRef(key="k"))
    assert sms.sent == ["+918040000001"]
    old = OldNotifier()
    await Outbox(notifier=old, users=None).to_user("u", "x")
    assert len(old.got) == 1

    class Broken:
        async def send(self, msg, *, urgency=None):
            raise RuntimeError

    assert await Outbox(notifier=Broken(), users=None).to_user("u", "x") is None


async def test_context_builder_tolerates_missing_repos():
    from datetime import UTC, datetime

    ctx = await build_context(object(), "u1", datetime(2026, 1, 5, tzinfo=UTC))
    assert ctx.user.id == "u1" and ctx.profile.user_id == "u1" and ctx.facts == []
    repos = Repos()
    ctx2 = await build_context(repos, "u1", datetime(2026, 1, 5, tzinfo=UTC))
    assert ctx2.open_tasks == []


def test_factory_builds_engine(settings):
    from friday.core.container import Container
    from friday.tasks.engine import TaskEngine

    assert isinstance(Container(settings).task_engine, TaskEngine)
