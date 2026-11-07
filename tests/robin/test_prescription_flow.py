# ruff: noqa: E501
"""T12 prescription photo -> the child confirms -> saved only after yes; refill alert with an 'ordered' button; the weekly count corrects the estimate.
Tested with fakes: FakeVision, simulated chat, fake clock. No real reader, no phone, nothing ordered or paid."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace as NS

from friday.chatbot_media.wiring import build_docs
from friday.core.models import Channel, InboundMessage, MessageKind, ReplyButton, User, UserStatus
from friday.docunderstand import copy as doc_copy
from friday.docunderstand.ports import FakeVision
from friday.robin import lines
from friday.robin.medicine import medicines_from_prescription, parse_times_text
from friday.robin.models import AnswerRaw, CallOutcome, CallResult
from tests.docunderstand import samples as S
from tests.robin.conftest import CHILD_PHONE, at

NAMES = ("zorvex", "lumirel")  # invented medicine names in the fixture


def _msg(text: str | None = None, button: str | None = None) -> InboundMessage:
    if button:
        return InboundMessage(channel=Channel.SIMULATOR, from_phone=CHILD_PHONE, kind=MessageKind.BUTTON_REPLY, button_id=button, text=None)
    return InboundMessage(channel=Channel.SIMULATOR, from_phone=CHILD_PHONE, kind=MessageKind.TEXT, text=text)


async def docs_for(w, container, trips=None):  # noqa: ANN001, ANN201
    """The REAL build_docs wiring (sink composition) with a fake reader; ``pipeline`` carries the Robin hub and an optional trips sink."""
    features = NS(on_document_confirmed=trips) if trips else None
    pipeline = NS(robin=w.hub, features=features, reply=None)
    vision = FakeVision()
    inbound = build_docs(container, pipeline, vision=vision)
    return inbound.service, vision


async def everything_robin_stored(w, fam) -> str:  # noqa: ANN001
    """Every record of the family, as text, for the 'no plaintext name' checks. Keys, statuses and audit texts only (data is encrypted at rest)."""
    out = []
    for kind in ("medicine", "audit", "dose", "digest", "pending", "consent", "incident"):
        for r in await w.store.list(fam.id, kind):
            out.append(f"{r.kind}|{r.key}|{r.status}|{r.data.get('text', '') if r.kind == 'audit' else ''}")
    return "\n".join(out).lower()


# ---------------------------------------------------------------- photo -> confirmation -> yes
async def test_photo_asks_the_child_and_saves_only_after_yes(w, container):
    fam, _ = await w.family()
    svc, vision = await docs_for(w, container)
    out = await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    assert len(vision.calls) == 1
    assert "Zorvex" in out.text and "Lumirel" in out.text and "yes or no" in out.text and "I cannot judge doses" in out.text
    assert [b.title for b in out.buttons] == ["Yes, save", "No"]
    assert not await w.hub.meds.meds(fam)  # nothing saved, nothing to remind about
    assert await w.hub.meds.has_proposal(fam)
    await w.hub.handle(w.child_user, _msg("yes"))
    saved = {m.name: m for _, m in await w.hub.meds.meds(fam)}
    assert set(saved) == {"Zorvex", "Lumirel"}
    assert saved["Zorvex"].times == ["08:00", "20:00"] and saved["Zorvex"].dose_text == "5 mg"
    assert saved["Lumirel"].times == ["08:00", "20:00"]  # 'BD'
    assert "Saved 2 medicine(s)." in w.sender.texts()[-1]
    assert not await w.hub.meds.has_proposal(fam)


async def test_no_saves_nothing(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    await w.hub.handle(w.child_user, _msg("no"))
    assert not await w.hub.meds.meds(fam) and not await w.hub.meds.has_proposal(fam)
    assert "did not save anything" in w.sender.texts()[-1]


async def test_the_buttons_work_like_the_words(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    out = await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    yes, no = out.buttons
    await w.hub.handle(w.child_user, _msg(button=no.id))
    assert not await w.hub.meds.meds(fam)
    await w.hub.handle(w.child_user, _msg(button=yes.id))
    assert "no prescription waiting" in w.sender.texts()[-1].lower()  # nothing open any more
    await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    await w.hub.handle(w.child_user, _msg(button=yes.id))
    assert len(await w.hub.meds.meds(fam)) == 2


async def test_a_second_photo_replaces_the_open_proposal(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    await w.hub.handle(w.child_user, _msg("yes"))
    assert len(await w.hub.meds.meds(fam)) == 2


async def test_an_old_proposal_is_dropped_not_saved_by_a_late_yes(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    w.go(hours=49)
    assert not await w.hub.meds.has_proposal(fam)
    await w.hub.handle(w.child_user, _msg("yes"))
    assert not await w.hub.meds.meds(fam)


async def test_times_that_cannot_be_read_are_said_and_left_out(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    p = {**S.PRESCRIPTION, "fields": {**S.PRESCRIPTION["fields"], "times": ["08:00", "as needed"]}}
    out = await svc.handle_media(w.child_user.id, "en", S.sample(p), "image/jpeg")
    assert "could not read the times for: Lumirel" in out.text
    await w.hub.handle(w.child_user, _msg("yes"))
    assert [m.name for _, m in await w.hub.meds.meds(fam)] == ["Zorvex"]


async def test_nothing_readable_saves_nothing_and_says_so(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    p = {**S.PRESCRIPTION, "fields": {**S.PRESCRIPTION["fields"], "times": ["whenever", "later"]}}
    out = await svc.handle_media(w.child_user.id, "en", S.sample(p), "image/jpeg")
    assert "saved nothing" in out.text and not out.buttons
    assert not await w.hub.meds.has_proposal(fam)


# ---------------------------------------------------------------- who may use it
async def test_a_sender_who_is_not_a_robin_admin_is_refused_and_nothing_is_stored(w, container):
    stranger = await container.repos.users.add(User(phone="+919800000199", status=UserStatus.ACTIVE))
    svc, vision = await docs_for(w, container)
    out = await svc.handle_media(stranger.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    assert out.text == doc_copy.t("refuse.prescription", "en") and not out.buttons
    assert await container.repos.documents.latest_open(stranger.id) is None
    assert await container.repos.documents.list_confirmed(stranger.id) == []
    assert not w.sender.sent


async def test_without_robin_at_all_the_prescription_is_refused(container):
    pipeline = NS(robin=None, features=None, reply=None)
    svc = build_docs(container, pipeline, vision=FakeVision()).service
    out = await svc.handle_media("u-x", "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    assert out.text == doc_copy.t("refuse.prescription", "en")


async def test_the_trips_sink_still_works_beside_robin(w, container):
    fam, _ = await w.family()
    calls = []

    async def trips(user_id, doc):  # noqa: ANN001, ANN202
        calls.append(doc.doc_type.value)
        return "Trip created."

    svc, _ = await docs_for(w, container, trips)
    out = await svc.handle_media(w.child_user.id, "en", S.sample(S.FLIGHT), "image/jpeg")
    ok = next(b for b in out.buttons if b.id.startswith("doc:ok:"))
    done = await svc.handle_button(w.child_user.id, "en", ok.id)
    assert calls == ["flight_ticket"] and "Trip created." in done.text
    assert not await w.hub.meds.has_proposal(fam)  # a flight never reaches Robin's medicine list


# ---------------------------------------------------------------- privacy: no medicine name in a column or an audit text
async def test_no_medicine_name_in_a_key_status_audit_or_document_row(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    await svc.handle_media(w.child_user.id, "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    await w.hub.handle(w.child_user, _msg("yes"))
    w.clock.set(at(7, 30, day=30))
    await w.hub.tick()
    await w.hub.meds.mark_ordered(fam, (await w.hub.meds.meds(fam))[0][1].id)
    blob = await everything_robin_stored(w, fam)
    assert "medicine|" in blob and "audit|" in blob  # the scan really saw rows
    assert not any(n in blob for n in NAMES), blob
    assert await container.repos.documents.latest_open(w.child_user.id) is None
    assert await container.repos.documents.list_confirmed(w.child_user.id) == []


# ---------------------------------------------------------------- pure parsing
def test_prescription_fields_to_medicines():
    meds, unread = medicines_from_prescription({"medicine": "Tab Zorvex; Lumirel; Quen", "dose_text": "5 mg; 500 mg", "times": "1-0-1; BD; later", "days": "10"}, date(2026, 1, 5))
    assert [m.name for m in meds] == ["Zorvex", "Lumirel"] and unread == ["Quen"]
    z = meds[0]
    assert z.times == ["08:00", "21:00"] and z.dose_text == "5 mg" and z.strips == 2 and z.last_purchase_date == date(2026, 1, 5)  # 2 doses x 10 days = 20 pills = 2 strips of 10
    assert parse_times_text("8am and 8:30 pm") == ["08:00", "20:30"] and parse_times_text("whenever") == []
    none, _ = medicines_from_prescription({"medicine": "Zorvex", "times": "OD"}, date(2026, 1, 5))
    assert none[0].strips == 0  # no 'days' -> no stock figure


# ---------------------------------------------------------------- refill alert with an 'ordered' button
async def _refill_world(w):  # noqa: ANN001, ANN202
    fam, parent = await w.family()
    med = (await _add(w, fam))
    return fam, parent, med


async def _add(w, fam):  # noqa: ANN001, ANN202
    from friday.robin.medicine import parse_add

    await w.hub.meds.add(fam, parse_add("add medicine Zorvex at 8am strips 1 of 10 bought 2026-01-01", date(2026, 1, 1)))
    return (await w.hub.meds.meds(fam))[0][1]


async def test_refill_alert_has_an_ordered_button_and_comes_once_per_threshold(w):
    fam, _, med = await _refill_world(w)
    w.clock.set(at(7, 30, day=6))  # 5 pills left
    await w.hub.tick()
    sent = [s for s in w.sender.sent if "stock left" in s.text]
    assert len(sent) == 1 and "Zorvex" in sent[0].text
    assert [b.title for b in sent[0].buttons] == ["Ordered"] and sent[0].buttons[0].id == f"rb:{med.id}:ordered"
    await w.hub.tick()
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == 1  # not repeated
    w.clock.set(at(7, 30, day=9))  # 2 left: the second threshold
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == 2


async def test_ordered_tap_is_noted_and_robin_orders_and_pays_nothing(w):
    fam, _, med = await _refill_world(w)
    w.clock.set(at(7, 30, day=6))
    await w.hub.tick()
    await w.hub.handle(w.child_user, _msg(button=f"rb:{med.id}:ordered"))
    reply = w.sender.texts()[-1]
    assert "Zorvex is ordered" in reply and "I do not order or pay" in reply and "pills left" in reply
    _, after = (await w.hub.meds.meds(fam))[0]
    assert after.ordered_at is not None
    assert not w.caller.calls  # no call, no purchase: only a note
    w.clock.set(at(7, 30, day=9))  # the 2-day nudge is quiet after 'ordered'
    n = sum("stock left" in t for t in w.sender.texts())
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == n
    audit = " ".join(r.data["text"] for r in await w.store.list(fam.id, "audit"))
    assert "marked a refill as ordered" in audit and "zorvex" not in audit.lower()


async def test_ordered_for_an_unknown_medicine_is_a_polite_not_found(w):
    fam, _ = await w.family()
    await w.hub.handle(w.child_user, _msg(button="rb:nope:ordered"))
    assert "could not find that medicine" in w.sender.texts()[-1].lower()


async def test_no_refill_alert_when_there_is_no_stock_figure(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    p = {**S.PRESCRIPTION, "fields": {k: v for k, v in S.PRESCRIPTION["fields"].items() if k != "days"}}
    await svc.handle_media(w.child_user.id, "en", S.sample(p), "image/jpeg")
    await w.hub.handle(w.child_user, _msg("yes"))
    w.clock.set(at(7, 30, day=6))
    await w.hub.tick()
    assert not any("stock left" in t for t in w.sender.texts())


async def test_prescription_days_give_a_stock_estimate_that_runs_down(w, container):
    fam, _ = await w.family()
    svc, _ = await docs_for(w, container)
    p = {**S.PRESCRIPTION, "fields": {**S.PRESCRIPTION["fields"], "medicine": ["Tab Zorvex"], "dose_text": ["5 mg"], "times": ["08:00, 20:00"], "days": ["4"]}}
    await svc.handle_media(w.child_user.id, "en", S.sample(p), "image/jpeg")
    await w.hub.handle(w.child_user, _msg("yes"))
    _, med = (await w.hub.meds.meds(fam))[0]
    assert med.strips == 0.8 and med.last_purchase_date == date(2026, 1, 5)  # 2 doses x 4 days = 8 pills, as an ESTIMATE


# ---------------------------------------------------------------- weekly count corrects the estimate
async def test_weekly_count_corrects_the_estimate_and_rearms_the_alert(w):
    fam, parent, med = await _refill_world(w)
    w.clock.set(at(7, 30, day=6))  # estimate: 5 days left -> alert
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == 1
    await w.hub.handle(w.child_user, _msg(button=f"rb:{med.id}:ordered"))
    w.clock.set(at(9, 1, day=11))  # Sunday: the weekly count says 12 pills, far more than the estimate
    w.caller.script(CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="checkin.q.ate", text="haan"), AnswerRaw(line="med.count_ask", text="12 goliyan")]))
    await w.hub.tick()
    _, m = (await w.hub.meds.meds(fam))[0]
    assert m.stock_adjust == 12 and m.stock_counted_at is not None and m.ordered_at is None
    from friday.robin.medicine import days_left

    assert days_left(m, at(9).date().replace(day=11)) == 12  # the estimate was 0; the parent's own count wins
    before = sum("stock left" in t for t in w.sender.texts())
    w.clock.set(at(7, 30, day=18))  # 7 days after the count: 5 left, so the alert fires again from the NEW count
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == before + 1


# ---------------------------------------------------------------- no medical advice, no ordering words
def test_new_lines_give_no_medical_advice_and_stay_pending():
    new = [ln for ln in lines.all_lines() if any(k in ln.id for k in ("med.rx_", "med.ordered_ack", "med.refill", "med.confirm"))]
    assert len(new) >= 10
    bad = ("increase", "decrease", "double", "stop taking", "skip the", "should take", "safe to take", "side effect", "instead of", "recommend", "is used for", "take more", "take less")
    for ln in new:
        assert not any(b in ln.text.lower() for b in bad), ln.id
        assert ln.status == "PENDING_FOUNDER_APPROVAL"
    assert not lines.approved()
    ordered = [ln for ln in lines.all_lines() if "ordered_ack" in ln.id and ln.language == "en"][0]
    assert "I do not order or pay" in ordered.text


def test_the_button_shape():
    assert ReplyButton(id="rb:abc:ordered", title="Ordered")
