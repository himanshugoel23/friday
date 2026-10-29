# ruff: noqa: E501
"""Hard safety rules, enforced in code: no payment/sign tool, no account creation without ok, attestations never guessed,
passwords only by vault, ID numbers never typed, logs and prompts carry no secrets."""

from __future__ import annotations

import json
import re

from friday.browser_agent import ask, rules
from friday.browser_agent.types import TOOLS, Action, Element, Status
from tests.browser_agent.fakes import A, FakeLogin, FakePageSpec, make_rig, spec
from tests.browser_agent.sites import APPLY, BASE, JOB, job_site

BANNED = ("pay", "order", "buy", "purchase", "submit", "card", "upi", "wallet", "sign", "register", "signup", "create_account", "account", "checkout")


def test_no_payment_sign_or_account_tool_exists():
    assert len(TOOLS) == 13
    for t in TOOLS:
        assert not any(b in t for b in BANNED), t
    literal = Action.model_json_schema()["properties"]["tool"]["enum"]
    assert tuple(literal) == TOOLS


def test_irreversible_and_payment_classification():
    def el(name, role="button", **kw):
        return Element(id="e1", role=role, name=name, **kw)

    for n in ("Submit application", "Confirm booking", "Cancel my subscription", "Book now", "Sign the agreement", "Confirm cancellation", "Unsubscribe"):
        assert rules.is_irreversible(el(n)), n
    for n in ("Next", "Continue", "Search", "Review", "Back", "Save draft", "Apply for this job", "Log in"):
        assert not rules.is_irreversible(el(n)), n
    assert rules.is_irreversible(el("Go ahead", submit=True))  # an unlabelled submit is treated as irreversible
    assert not rules.is_irreversible(el("Search", submit=True))
    for n in ("Card number", "CVV", "UPI ID", "Net banking", "Pay now", "Place your order", "Pay ₹499", "Google Pay", "Paytm wallet"):
        assert rules.is_payment_element(el(n, "textbox")), n
    assert rules.is_payment_element(el("Number", "textbox", autocomplete="cc-number"))
    assert not rules.is_payment_element(el("Full name", "textbox"))
    assert rules.is_attestation(el("I have never paid for a job or training", "checkbox"))
    assert rules.is_attestation(el("I consent to a background check", "checkbox"))
    assert not rules.is_attestation(el("Submit", "button"))


async def test_creating_an_account_needs_the_users_ok_for_that_site():
    pages = {JOB: FakePageSpec("Login", "Log in to continue", [{"name": "Create an account", "role": "link", "goes_to": APPLY}])}
    pages[APPLY] = FakePageSpec("Signup", "Sign up", [])
    rig = make_rig(pages, [A("click", target="e1"), A("finish", result="x")], start=JOB)
    out = await rig.agent.start("u1", spec(start_url=JOB))
    assert out.status == Status.WAITING_USER and "new account" in out.message and rig.browser.clicked() == []
    out = await rig.agent.reply(out.run_id, "no")
    assert out.status == Status.GAVE_UP and rig.browser.clicked() == []
    rig2 = make_rig(pages, [A("click", target="e1"), A("click", target="e1"), A("finish", result="x")], start=JOB)
    out = await rig2.agent.start("u1", spec(start_url=JOB))
    out = await rig2.agent.reply(out.run_id, "yes")
    assert rig2.browser.clicked() == ["Create an account"]
    rig3 = make_rig(pages, [A("click", target="e1"), A("finish", result="x")], start=JOB)  # explicit ok given up front, per site
    out = await rig3.agent.start("u1", spec(start_url=JOB, account_ok_hosts=["jobs.example.com"]))
    assert rig3.browser.clicked() == ["Create an account"]


async def test_attestations_are_never_guessed_and_are_asked_verbatim_and_not_remembered():
    stmt = "I have never paid any money to get this job"
    pages = job_site([{"name": stmt, "role": "checkbox", "required": True}])
    script = [
        A("click", target="e1"),
        A("fill", target="e1", value_source="fact:full_name"),
        A("fill", target="e5", value_source="fact:never_paid"),  # wrong source for a legal statement
        A("fill", target="e5", value_source="attest:never_paid"),  # right source, but nothing answered yet
        A("click", target="e6"),
        A("fill", target="e5", value_source="attest:never_paid"),
        A("finish", result="ticked"),
    ]
    rig = make_rig(pages, script, facts={"full_name": "Asha", "never_paid": "yes"}, start=JOB)
    out = await rig.agent.start("u1", spec(start_url=JOB))
    assert out.status == Status.WAITING_USER and f'"{stmt}"' in out.message  # verbatim, yes/no
    assert rig.browser.log.count(("check", stmt, "True")) == 0  # nothing ticked for the user
    out = await rig.agent.reply(out.run_id, "yes")
    assert out.status == Status.DONE and ("check", stmt, "True") in rig.browser.log
    assert "never_paid" in rig.facts.data["u1"] and rig.facts.data["u1"]["never_paid"] == "yes"  # the pre-existing fact is untouched ...
    assert not any(k.startswith("attest") or "attest" in k for k in rig.facts.data["u1"])  # ... and the answer was NOT remembered
    # a "no" is also respected: the box is left unchecked
    rig2 = make_rig(job_site([{"name": stmt, "role": "checkbox"}]), [A("click", target="e1"), A("fill", target="e5", value_source="attest:never_paid"), A("click", target="e6"), A("fill", target="e5", value_source="attest:never_paid"), A("finish", result="x")], start=JOB)
    out = await rig2.agent.start("u1", spec(start_url=JOB))
    out = await rig2.agent.reply(out.run_id, "no")
    assert ("check", stmt, "False") in rig2.browser.log


async def test_id_numbers_and_unknown_sources_are_never_typed():
    pages = job_site([{"name": "Aadhaar number"}, {"name": "PAN"}])
    script = [A("click", target="e1"), A("fill", target="e5", value_source="fact:aadhaar"), A("fill", target="e6", value_source="fact:pan"),
              A("fill", target="e1", value_source="Asha Verma"), A("fill", target="e1", value_source="text:Asha Verma"), A("finish", result="done")]
    rig = make_rig(pages, script, facts={"aadhaar": "123412341234", "pan": "ABCDE1234F"}, start=JOB)
    out = await rig.agent.start("u1", spec(start_url=JOB))
    assert rig.browser.typed() == []
    st = rig.store.load(out.run_id)
    assert st.left_for_user == ["Aadhaar number", "PAN"] and "Please fill yourself" in out.message
    assert [h.result for h in st.history if h.tool == "fill"][2].startswith("REFUSED")  # a made-up literal is refused


async def test_passwords_only_through_the_vault_and_never_logged():
    pages = {JOB: FakePageSpec("Login", "Log in", [{"name": "Email or username"}, {"name": "Password", "type": "password"}, {"name": "Log in", "role": "button", "submit": True, "goes_to": APPLY}]),
             APPLY: FakePageSpec("Hi", "Welcome", [])}
    login = FakeLogin(creds=("asha@example.com", "S3cretPw!x"))
    script = [A("fill", target="e2", value_source="fact:password"), A("fill", target="e1", value_source="vault:username"),
              A("fill", target="e2", value_source="vault:password"), A("click", target="e3"), A("finish", result="logged in")]
    rig = make_rig(pages, script, facts={"password": "from-memory"}, start=JOB, login=login)
    out = await rig.agent.start("u1", spec(start_url=JOB))
    assert out.status == Status.DONE
    assert rig.browser.typed() == ["asha@example.com", "S3cretPw!x"]  # only the vault value reached the page
    assert "from-memory" not in json.dumps(rig.browser.log)
    blob = json.dumps([list(rig.log.events), rig.store.load(out.run_id).model_dump(mode="json"), rig.llm.prompts])
    assert "S3cretPw!x" not in blob and "asha@example.com" not in blob


async def test_missing_login_sends_a_secure_link_and_never_asks_for_a_password_in_chat():
    pages = {JOB: FakePageSpec("Login", "Log in", [{"name": "Password", "type": "password"}])}
    rig = make_rig(pages, [A("fill", target="e1", value_source="vault:password"), A("fill", target="e1", value_source="vault:password"), A("finish", result="ok")], start=JOB, login=FakeLogin(creds=None))
    out = await rig.agent.start("u1", spec(start_url=JOB))
    assert out.status == Status.WAITING_USER and "https://f.example/secure/abc" in out.message and "never type a password" in out.message
    # the user pastes the password in chat anyway: refused, not stored, not logged, run keeps waiting
    out2 = await rig.agent.reply(out.run_id, "my password is hunter2hunter")
    assert "do not send passwords" in out2.message.lower() or "did not save" in out2.message
    assert "hunter2hunter" not in json.dumps(list(rig.log.events)) + rig.store.load(out.run_id).model_dump_json()
    assert rig.store.load(out.run_id).status == Status.WAITING_USER
    rig.login.creds = ("a@b.c", "pw-from-vault")
    out3 = await rig.agent.reply(out.run_id, "done")
    assert out3.status == Status.DONE and rig.browser.typed() == ["pw-from-vault"]


async def test_login_code_only_from_the_secure_channel():
    pages = {JOB: FakePageSpec("Verify", "Enter the code", [{"name": "Verification code"}])}
    rig = make_rig(pages, [A("fill", target="e1", value_source="fact:code"), A("fill", target="e1", value_source="otp"), A("fill", target="e1", value_source="otp"), A("finish", result="in")], start=JOB, login=FakeLogin(code=None))
    out = await rig.agent.start("u1", spec(start_url=JOB))
    assert out.status == Status.WAITING_USER and "secure page" in out.message
    rig.login.code = "483920"
    out = await rig.agent.reply(out.run_id, "done")
    assert out.status == Status.DONE and rig.browser.typed() == ["483920"]
    assert "483920" not in json.dumps(list(rig.log.events)) + rig.store.load(out.run_id).model_dump_json() + json.dumps(rig.llm.prompts)
    assert rig.login.code is None  # single use


def test_secret_looking_replies_are_recognised():
    for t in ("my password is abc12345", "card 4111 1111 1111 1111", "otp is 482913", "cvv 123", "aadhaar 1234 5678 9012", "UPI PIN 4821"):
        assert ask.looks_secret(t), t
    for t in ("30 days", "Gurugram 122001", "pin code 131001", "asha@example.com", "+919876543210", "12 LPA", "yes"):
        assert not ask.looks_secret(t), t


async def test_upload_failure_is_reported_and_left_for_the_user():
    script = [A("click", target="e1"), A("upload", target="e4", file_ref="resume"), A("upload", target="e4", file_ref="resume"), A("finish", result="filled the rest")]
    rig = make_rig(job_site(), script, start=JOB, files={"resume": "/f/resume.pdf"})
    rig.browser.upload_ok = False
    out = await rig.agent.start("u1", spec(start_url=JOB))
    assert out.status == Status.DONE and "attach resume yourself" in out.message
    assert len(rig.browser.uploads) == 2  # tried twice, then stopped retrying
    # an unknown file ref is never turned into a path
    rig2 = make_rig(job_site(), [A("click", target="e1"), A("upload", target="e4", file_ref="/etc/passwd"), A("finish", result="x")], start=JOB)
    await rig2.agent.start("u1", spec(start_url=JOB))
    assert rig2.browser.uploads == []


async def test_logs_prompts_and_state_carry_no_user_values():
    facts = {"full_name": "Asha Verma", "email": "asha.verma@example.com", "phone": "+919812345678", "notice_period": "30 days", "target_role": "Backend Engineer"}
    script = [A("click", target="e1"), A("fill", target="e1", value_source="fact:full_name"), A("fill", target="e2", value_source="fact:email"),
              A("select", target="e3", option="fact:notice_period"), A("request_confirmation", summary="Submit the application to Acme"), A("finish", result="x")]
    rig = make_rig(job_site(), script, facts=facts, start=JOB)
    out = await rig.agent.start("u1", spec(start_url=JOB))
    blob = json.dumps([list(rig.log.events), rig.store.load(out.run_id).model_dump(mode="json")])
    for v in ("Asha Verma", "asha.verma@example.com", "+919812345678"):
        assert v not in blob, v
    prompts = "\n".join(rig.llm.prompts)
    assert "asha.verma@example.com" not in prompts and "+919812345678" not in prompts  # hidden from the model
    assert "target_role: Backend Engineer" in prompts and "email: (stored, hidden)" in prompts


async def test_enter_cannot_be_used_to_submit_without_a_yes():
    pages = job_site()
    rig = make_rig(pages, [A("goto", url=f"{BASE}/review"), A("press", key="Enter"), A("give_up", reason="x")], start=JOB)
    await rig.agent.start("u1", spec(start_url=JOB))
    assert ("press", "Enter") not in rig.browser.log and rig.browser.submitted is False


def test_free_text_only_in_search_boxes():
    from friday.browser_agent.policy import Policy
    from friday.browser_agent.types import RunSpec, RunState
    from tests.browser_agent.fakes import TickClock

    st = RunState(id="a" * 16, user_id="u", spec=RunSpec(goal="g", allowed_domains=["x.com"]))
    pol = Policy(st, ["x.com"], TickClock().now())
    box = Element(id="e1", role="textbox", name="Search jobs", type="search")
    name = Element(id="e2", role="textbox", name="Full name")
    assert pol.check_source("text:python developer", box).ok
    assert not pol.check_source("text:asha@example.com", box).ok
    assert not pol.check_source("text:9876543210", box).ok
    assert not pol.check_source("text:Asha", name).ok
    assert not re.search(r"x", "")
