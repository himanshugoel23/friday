"""A FAKE Google for tests: OAuth (token, userinfo, revoke), Calendar events, Gmail messages.

A FastAPI app driven through ``httpx.ASGITransport``: no socket, no network at all. It enforces
what the real thing enforces that matters to us: PKCE S256 on the code exchange, a one-time
code, client id/secret and redirect URI checks, refresh-token grants (with an ``invalid_grant``
switch), access tokens that can expire (401), revocation, and Calendar's "same event id twice is
a 409". It records every request so tests can assert what Friday asked for.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

BASE = "http://fake-google"
CLIENT_ID = "test-client-id.apps.example"
CLIENT_SECRET = "test-client-secret-value"
REDIRECT = "https://friday.example/google/callback"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FakeGoogle:
    def __init__(self) -> None:
        self.codes: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, dict[str, Any]] = {}  # token -> {sub, email, scope}
        self.access_tokens: dict[str, dict[str, Any]] = {}  # token -> {sub, scope, expired}
        self.accounts: dict[str, dict[str, str]] = {}
        self.events: dict[str, dict[str, dict[str, Any]]] = {}  # sub -> id -> event
        self.messages: dict[str, list[dict[str, Any]]] = {}  # sub -> messages
        self.requests: list[dict[str, Any]] = []
        self.authorize_params: list[dict[str, str]] = []
        self.revoked: list[str] = []
        self.gmail_queries: list[str] = []
        self.gmail_formats: list[str] = []
        # switches
        self.fail_refresh = False  # refresh grant answers invalid_grant
        self.revoke_status = 200
        self.page_size = 250
        self.grant_override: list[str] | None = None  # scopes the "user" actually ticked
        self.omit_refresh_token = False
        self.app = self._build()

    # ------------------------------------------------------------------ test helpers
    def client_factory(self):
        def make() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url=BASE, timeout=5
            )

        return make

    def add_account(self, key: str, email: str, sub: str | None = None) -> str:
        sub = sub or f"sub-{key}"
        self.accounts[key] = {"sub": sub, "email": email}
        return sub

    def user_clicks_allow(self, consent_url: str, account: str = "alice") -> tuple[str, str]:
        """Play the browser: validate the authorize request like Google, return (code, state)."""
        parts = urlsplit(consent_url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.authorize_params.append(q)
        assert q["client_id"] == CLIENT_ID and q["redirect_uri"] == REDIRECT
        assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        ticked = self.grant_override if self.grant_override is not None else q["scope"].split()
        scope = " ".join(ticked)
        self.codes[code] = {
            "challenge": q["code_challenge"],
            "redirect_uri": q["redirect_uri"],
            "scope": scope,
            "account": account,
        }
        return code, q["state"]

    def expire_access_tokens(self) -> None:
        for t in self.access_tokens.values():
            t["expired"] = True

    def drop_refresh_tokens(self) -> None:
        self.refresh_tokens.clear()

    def add_message(
        self, sub: str, *, kind: str, id: str, sender: str, subject: str, snippet: str,
        date: str = "Mon, 05 Jan 2026 09:00:00 +0530",
    ) -> None:
        self.messages.setdefault(sub, []).append(
            {
                "id": id, "kind": kind, "snippet": snippet,
                "body": "FULL BODY SHOULD NEVER BE REQUESTED " + snippet,
                "headers": [
                    {"name": "From", "value": sender},
                    {"name": "Subject", "value": subject},
                    {"name": "Date", "value": date},
                ],
            }
        )

    def all_tokens_seen(self) -> set[str]:
        out = set(self.refresh_tokens) | set(self.access_tokens)
        return out

    # ------------------------------------------------------------------ app
    def _build(self) -> FastAPI:
        app = FastAPI()
        fake = self

        async def log(request: Request) -> dict[str, Any]:
            body = (await request.body()).decode() if request.method in ("POST", "PUT") else ""
            rec = {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.query_params),
                "body": body,
                "auth": request.headers.get("authorization"),
            }
            fake.requests.append(rec)
            return rec

        def form(rec: dict[str, Any]) -> dict[str, str]:
            return {k: v[0] for k, v in parse_qs(rec["body"]).items()}

        def new_access(sub: str, scope: str) -> str:
            tok = "ya29." + secrets.token_urlsafe(24)
            fake.access_tokens[tok] = {"sub": sub, "scope": scope, "expired": False}
            return tok

        def err(code: str, status: int = 400) -> JSONResponse:
            return JSONResponse({"error": code, "error_description": "fake"}, status_code=status)

        @app.post("/token")
        async def token(request: Request) -> Response:
            f = form(await log(request))
            if f.get("client_id") != CLIENT_ID or f.get("client_secret") != CLIENT_SECRET:
                return err("invalid_client", 401)
            if f.get("grant_type") == "authorization_code":
                info = fake.codes.pop(f.get("code", ""), None)  # one time only
                if info is None or info["redirect_uri"] != f.get("redirect_uri"):
                    return err("invalid_grant")
                verifier = f.get("code_verifier", "")
                if b64(hashlib.sha256(verifier.encode()).digest()) != info["challenge"]:
                    return err("invalid_grant")  # PKCE failed
                acct = fake.accounts[info["account"]]
                out = {
                    "access_token": new_access(acct["sub"], info["scope"]),
                    "expires_in": 3599,
                    "scope": info["scope"],
                    "token_type": "Bearer",
                }
                if not fake.omit_refresh_token:
                    rt = "1//" + secrets.token_urlsafe(30)
                    fake.refresh_tokens[rt] = {**acct, "scope": info["scope"]}
                    out["refresh_token"] = rt
                return JSONResponse(out)
            if f.get("grant_type") == "refresh_token":
                rt = fake.refresh_tokens.get(f.get("refresh_token", ""))
                if fake.fail_refresh or rt is None:
                    return err("invalid_grant")
                return JSONResponse(
                    {
                        "access_token": new_access(rt["sub"], rt["scope"]),
                        "expires_in": 3599,
                        "scope": rt["scope"],
                        "token_type": "Bearer",
                    }
                )
            return err("unsupported_grant_type")

        def who(rec: dict[str, Any]) -> dict[str, Any] | None:
            auth = rec["auth"] or ""
            tok = fake.access_tokens.get(auth[7:]) if auth.startswith("Bearer ") else None
            return None if tok is None or tok["expired"] else tok

        @app.get("/userinfo")
        async def userinfo(request: Request) -> Response:
            tok = who(await log(request))
            if tok is None:
                return err("invalid_token", 401)
            acct = next(a for a in fake.accounts.values() if a["sub"] == tok["sub"])
            return JSONResponse(
                {"sub": acct["sub"], "email": acct["email"], "email_verified": True}
            )

        @app.post("/revoke")
        async def revoke(request: Request) -> Response:
            f = form(await log(request))
            t = f.get("token", "")
            fake.revoked.append(t)
            if fake.revoke_status != 200:
                return JSONResponse({"error": "boom"}, status_code=fake.revoke_status)
            fake.refresh_tokens.pop(t, None)
            fake.access_tokens.pop(t, None)
            return JSONResponse({})

        # -------------------------------------------------------------- calendar
        def cal(tok: dict[str, Any]) -> dict[str, dict[str, Any]]:
            return fake.events.setdefault(tok["sub"], {})

        def calendar_ok(tok: dict[str, Any] | None) -> Response | None:
            if tok is None:
                return err("unauthenticated", 401)
            if "calendar.events" not in tok["scope"]:
                return err("forbidden", 403)
            return None

        @app.get("/calendar/calendars/primary/events")
        async def list_events(request: Request) -> Response:
            tok = who(await log(request))
            if (bad := calendar_ok(tok)) is not None:
                return bad
            q = request.query_params
            lo, hi = _dt(q["timeMin"]), _dt(q["timeMax"])
            items = []
            for ev in cal(tok).values():
                if ev["status"] == "cancelled":
                    continue
                s = _dt(ev["start"].get("dateTime") or ev["start"]["date"] + "T00:00:00+05:30")
                e = _dt(ev["end"].get("dateTime") or ev["end"]["date"] + "T00:00:00+05:30")
                if s < hi and e > lo:
                    items.append((s, ev))
            items.sort(key=lambda p: p[0])
            start = int(q.get("pageToken", "0"))
            page = [ev for _, ev in items[start : start + fake.page_size]]
            out: dict[str, Any] = {"items": page}
            if start + fake.page_size < len(items):
                out["nextPageToken"] = str(start + fake.page_size)
            return JSONResponse(out)

        @app.post("/calendar/calendars/primary/events")
        async def insert_event(request: Request) -> Response:
            tok = who(await log(request))
            if (bad := calendar_ok(tok)) is not None:
                return bad
            body = await request.json()
            if body["id"] in cal(tok):
                return err("duplicate", 409)
            cal(tok)[body["id"]] = {**body, "status": "confirmed"}
            return JSONResponse(cal(tok)[body["id"]])

        @app.get("/calendar/calendars/primary/events/{eid}")
        async def get_event(eid: str, request: Request) -> Response:
            tok = who(await log(request))
            if (bad := calendar_ok(tok)) is not None:
                return bad
            ev = cal(tok).get(eid)
            return JSONResponse(ev) if ev else err("notFound", 404)

        @app.put("/calendar/calendars/primary/events/{eid}")
        async def put_event(eid: str, request: Request) -> Response:
            tok = who(await log(request))
            if (bad := calendar_ok(tok)) is not None:
                return bad
            body = await request.json()
            cal(tok)[eid] = {**body, "id": eid}
            return JSONResponse(cal(tok)[eid])

        @app.delete("/calendar/calendars/primary/events/{eid}")
        async def delete_event(eid: str, request: Request) -> Response:
            tok = who(await log(request))
            if (bad := calendar_ok(tok)) is not None:
                return bad
            ev = cal(tok).get(eid)
            if ev is None:
                return err("notFound", 404)
            if ev["status"] == "cancelled":
                return err("gone", 410)
            ev["status"] = "cancelled"
            return Response(status_code=204)

        # -------------------------------------------------------------- gmail
        def gmail_ok(tok: dict[str, Any] | None) -> Response | None:
            if tok is None:
                return err("unauthenticated", 401)
            if "gmail.readonly" not in tok["scope"]:
                return err("forbidden", 403)
            return None

        @app.get("/gmail/users/me/messages")
        async def gmail_list(request: Request) -> Response:
            tok = who(await log(request))
            if (bad := gmail_ok(tok)) is not None:
                return bad
            q = request.query_params["q"]
            fake.gmail_queries.append(q)
            kind = "bill" if "invoice" in q else "ticket" if "PNR" in q else "appointment"
            msgs = [m for m in fake.messages.get(tok["sub"], []) if m["kind"] == kind]
            return JSONResponse({"messages": [{"id": m["id"], "threadId": m["id"]} for m in msgs]})

        @app.get("/gmail/users/me/messages/{mid}")
        async def gmail_get(mid: str, request: Request) -> Response:
            tok = who(await log(request))
            if (bad := gmail_ok(tok)) is not None:
                return bad
            fmt = request.query_params.get("format", "full")
            fake.gmail_formats.append(fmt)
            m = next((m for m in fake.messages.get(tok["sub"], []) if m["id"] == mid), None)
            if m is None:
                return err("notFound", 404)
            out: dict[str, Any] = {"id": mid, "snippet": m["snippet"],
                                   "payload": {"headers": m["headers"]}}
            if fmt == "full":
                out["payload"]["body"] = {"data": b64(m["body"].encode())}
            return JSONResponse(out)

        return app


def settings_overrides() -> dict[str, Any]:
    """Settings that point the connector at the fake."""
    return {
        "google_oauth_client_id": CLIENT_ID,
        "google_oauth_client_secret": CLIENT_SECRET,
        "google_redirect_uri": REDIRECT,
        "google_auth_url": f"{BASE}/o/oauth2/v2/auth",
        "google_token_url": f"{BASE}/token",
        "google_userinfo_url": f"{BASE}/userinfo",
        "google_revoke_url": f"{BASE}/revoke",
        "google_calendar_base_url": f"{BASE}/calendar",
        "google_gmail_base_url": f"{BASE}/gmail",
    }


__all__ = ["FakeGoogle", "settings_overrides", "BASE", "CLIENT_ID", "REDIRECT"]
