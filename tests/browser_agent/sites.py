# ruff: noqa: E501
"""Fake job site used by the loop tests."""

from __future__ import annotations

from tests.browser_agent.fakes import FakePageSpec

BASE = "https://jobs.example.com"
JOB, APPLY, REVIEW, DONE = f"{BASE}/job", f"{BASE}/apply", f"{BASE}/review", f"{BASE}/done"


def job_site(extra_apply: list[dict] | None = None) -> dict[str, FakePageSpec]:
    return {
        JOB: FakePageSpec("Backend Engineer", "Backend Engineer at Acme Pvt Ltd, Gurugram. Python, 3+ years.",
                          [{"name": "Apply for this job", "role": "link", "goes_to": APPLY}]),
        APPLY: FakePageSpec("Apply", "Your details", [
            {"name": "Full name", "required": True},
            {"name": "Email", "type": "email", "required": True},
            {"name": "Notice period", "role": "select", "options": ["Immediate", "15 days", "30 days", "60 days"], "required": True},
            {"name": "Resume", "role": "file", "type": "file"},
            *(extra_apply or []),
            {"name": "Review", "role": "button", "goes_to": REVIEW},
        ]),
        REVIEW: FakePageSpec("Review", "Review your application before you send it.", [
            {"name": "Submit application", "role": "button", "submit": True, "goes_to": DONE, "submit_marks": True},
        ]),
        DONE: FakePageSpec("Thanks", "Application received. Reference 4471."),
    }
