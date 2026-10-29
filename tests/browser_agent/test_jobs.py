# ruff: noqa: E501
"""Job-application playbook: standing opt-in, preview (default) vs auto with a daily cap, grouped profile questions up front,
legal statements always asked, evening summary with proof."""

from __future__ import annotations

from friday.browser_agent.jobapply import (
    ApplyDecision,
    JobApplyService,
    JobLedger,
    playbook,
    required_fields,
)
from friday.browser_agent.types import Status
from tests.browser_agent.fakes import A, make_rig
from tests.browser_agent.sites import BASE, DONE, JOB, REVIEW, job_site

URL = f"{BASE}/job"
FULL = {"full_name": "Asha Verma", "email": "asha@example.com", "phone": "+919800000000", "current_city": "Gurugram",
        "total_experience_years": "4", "expected_ctc": "18 LPA", "notice_period": "30 days"}
SCRIPT = [A("click", target="e1"), A("fill", target="e1", value_source="fact:full_name"), A("fill", target="e2", value_source="fact:email"),
          A("select", target="e3", option="fact:notice_period"), A("upload", target="e4", file_ref="resume"), A("click", target="e5"),
          A("request_confirmation", summary="Apply to Backend Engineer at Acme; sends your name, email, notice period and resume."),
          A("click", target="e1"), A("finish", result="Backend Engineer at Acme")]


def svc(rig, tmp_path, cap=2):  # noqa: ANN001, ANN201
    return JobApplyService(rig.agent, rig.facts, JobLedger(tmp_path / "ledger.jsonl"), rig.files, daily_cap=cap, now=rig.clock.now)


def mk(tmp_path, script=None, facts=None, pages=None, **kw):  # noqa: ANN001, ANN201
    rig = make_rig(pages or job_site(), list(script if script is not None else SCRIPT), facts=dict(FULL if facts is None else facts), start=JOB,
                   files={"resume": "/f/resume.pdf"}, **kw)
    return rig, svc(rig, tmp_path)


def test_playbook_is_data_with_no_user_values():
    pb = playbook()
    assert {f["key"] for f in pb["profile_fields"]} >= {"full_name", "email", "notice_period", "expected_ctc"}
    assert pb["limits"]["mode_default"] == "preview" and pb["resume"]["file_ref"] == "resume"
    assert any("fee" in n for n in pb["never"]) and [f.key for f in required_fields(pb)][0] == "full_name"
    assert "@" not in str(pb)


async def test_never_applies_without_the_standing_opt_in(tmp_path):
    rig, js = mk(tmp_path)
    res = await js.apply("u1", f"apply for this job {URL}", "en")
    assert isinstance(res, ApplyDecision) and not res.ok and "job apply on" in res.message
    assert rig.provider.opens == 0 and rig.llm.prompts == []
    assert "preview mode" in await js.handle_command("u1", "job apply on", "en")
    assert await js.mode("u1") == "preview"
    assert "Auto-apply is on, up to 2" in await js.handle_command("u1", "JOB APPLY AUTO ON", "en")
    assert await js.mode("u1") == "auto"
    assert "off" in (await js.handle_command("u1", "job apply off", "en")).lower()
    res = await js.apply("u1", f"apply for this job {URL}", "en")
    assert isinstance(res, ApplyDecision) and not res.ok


async def test_needs_a_resume_and_a_link(tmp_path):
    rig = make_rig(job_site(), [], facts=dict(FULL), start=JOB, files={})
    js = svc(rig, tmp_path)
    await js.handle_command("u1", "job apply on", "en")
    r = await js.apply("u1", f"apply for this job {URL}", "en")
    assert isinstance(r, ApplyDecision) and "resume" in r.message
    r = await js.apply("u1", "apply for a job", "en")
    assert isinstance(r, ApplyDecision) and "link" in r.message


async def test_missing_profile_fields_are_asked_once_up_front_before_any_browser(tmp_path):
    rig, js = mk(tmp_path, facts={"full_name": "Asha Verma"})
    await js.handle_command("u1", "job apply on", "en")
    out = await js.apply("u1", f"apply for this job {URL}", "en")
    assert out.status == Status.WAITING_USER and rig.provider.opens == 0 and rig.llm.prompts == []
    for label in ("Email address", "Mobile number", "Current city", "Total experience", "Expected salary", "Notice period"):
        assert label in out.message
    assert "Full name" not in out.message  # already known
    reply = "\n".join(["Email address: asha@example.com", "Mobile number: +919800000000", "Current city: Gurugram", "Total experience (years): 4", "Expected salary (CTC): 18 LPA", "Notice period: 30 days"])
    out = await rig.agent.reply(out.run_id, reply)
    assert out.status == Status.WAITING_CONFIRM  # now the browser ran up to the final submit
    assert rig.facts.data["u1"]["expected_ctc"] == "18 LPA"


async def test_preview_mode_shows_the_application_and_waits_for_a_yes_then_logs_it(tmp_path):
    rig, js = mk(tmp_path)
    await js.handle_command("u1", "job apply on", "en")
    out = await js.apply("u1", f"apply for this job {URL}", "en")
    assert out.status == Status.WAITING_CONFIRM and "Apply to Backend Engineer at Acme" in out.message and rig.browser.submitted is False
    out = await rig.agent.reply(out.run_id, "yes")
    assert out.status == Status.DONE and rig.browser.submitted is True
    js.record_outcome("u1", out, rig.store.load(out.run_id).result)
    assert js.ledger.applied_today("u1", rig.clock.now()) == 1
    text = js.evening_summary("u1", "en")
    assert "Backend Engineer at Acme" in text and "jobs.example.com/done" in text and "Proof saved" in text


async def test_auto_mode_uses_the_standing_opt_in_for_the_submit_only(tmp_path):
    rig, js = mk(tmp_path)
    await js.handle_command("u1", "job apply auto on", "en")
    out = await js.apply("u1", f"apply for this job {URL}", "en")
    assert out.status == Status.DONE and rig.browser.submitted is True  # no per-application yes
    assert len(out.proofs) == 1 and "standing opt-in" in out.proofs[0].what
    assert any(e["event"] == "standing_permit" for e in rig.log.events)


async def test_auto_mode_still_asks_every_legal_statement(tmp_path):
    stmt = "I consent to a background check by Acme"
    pages = job_site([{"name": stmt, "role": "checkbox", "required": True}])
    script = [A("click", target="e1"), A("fill", target="e5", value_source="attest:bg_check"), A("click", target="e6"),
              A("fill", target="e5", value_source="attest:bg_check"), A("click", target="e6"),
              A("request_confirmation", summary="Apply to Acme"), A("click", target="e1"), A("finish", result="Backend Engineer at Acme")]
    rig, js = mk(tmp_path, script=script, pages=pages)
    await js.handle_command("u1", "job apply auto on", "en")
    out = await js.apply("u1", f"apply for this job {URL}", "en")
    assert out.status == Status.WAITING_USER and f'"{stmt}"' in out.message and rig.browser.submitted is False
    out = await rig.agent.reply(out.run_id, "yes")
    assert ("check", stmt, "True") in rig.browser.log
    assert out.status == Status.DONE and rig.browser.submitted is True  # now the standing opt-in covers the submit click


async def test_auto_standing_opt_in_does_not_cover_a_checked_off_legal_box_left_open(tmp_path):
    # an UNCHECKED legal box on the review page: the standing opt-in must not be used; a normal chat yes is required
    pages = job_site()
    pages[REVIEW].elements.insert(0, {"name": "I declare that all the information is true", "role": "checkbox", "checked": False})
    script = [A("goto", url=REVIEW), A("request_confirmation", summary="Apply to Acme"), A("click", target="e2")]
    rig, js = mk(tmp_path, script=script, pages=pages)
    await js.handle_command("u1", "job apply auto on", "en")
    out = await js.apply("u1", f"apply for this job {URL}", "en")
    assert out.status == Status.WAITING_CONFIRM and rig.browser.submitted is False


async def test_auto_standing_opt_in_is_used_once_per_run(tmp_path):
    pages = job_site()
    pages[DONE] = type(pages[JOB])("Second", "Another form", [{"name": "Submit application", "role": "button", "submit": True, "submit_marks": True}])
    script = [A("goto", url=REVIEW), A("request_confirmation", summary="Apply to Acme"), A("click", target="e1"), A("click", target="e1"), A("give_up", reason="stop")]
    rig, js = mk(tmp_path, script=script, pages=pages)
    await js.handle_command("u1", "job apply auto on", "en")
    out = await js.apply("u1", f"apply for this job {URL}", "en")
    assert rig.browser.clicked() == ["Submit application"]  # the second submit was refused
    assert out.status == Status.GAVE_UP


async def test_daily_cap_stops_further_applications(tmp_path):
    rig, js = mk(tmp_path)
    await js.handle_command("u1", "job apply auto on", "en")
    for _ in range(2):
        js.ledger.record("u1", now=rig.clock.now(), host="jobs.example.com", where="x", what="y", proof_id="p", status="applied")
    res = await js.apply("u1", f"apply for this job {URL}", "en")
    assert isinstance(res, ApplyDecision) and "daily limit" in res.message and rig.provider.opens == 0
    rig.clock.advance(hours=24)
    assert js.ledger.applied_today("u1", rig.clock.now()) == 0  # a new IST day


async def test_ledger_holds_no_answers_and_is_erasable(tmp_path):
    rig, js = mk(tmp_path)
    await js.handle_command("u1", "job apply on", "en")
    out = await js.apply("u1", f"apply for this job {URL}", "en")
    out = await rig.agent.reply(out.run_id, "yes")
    js.record_outcome("u1", out, "Backend Engineer at Acme")
    raw = (tmp_path / "ledger.jsonl").read_text()
    for v in FULL.values():
        assert v not in raw
    assert js.ledger.delete_user("u1") == 1 and js.ledger.rows("u1") == []
