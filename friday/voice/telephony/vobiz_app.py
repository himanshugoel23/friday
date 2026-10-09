"""Vobiz plumbing for INBOUND calls: an Application with Friday's answer URL, linked to a number.

A Vobiz number rings an *Application* (answer_url / hangup_url). For people to call Friday
the front-door number must be linked to an Application that points at the current public URL,
and the old link must be put back when we stop, so the number never points at a dead tunnel.

    mgr = VobizAppManager(auth_id, auth_token)
    link = await mgr.sync(public_base_url, number, secret)    # find/create app, link the number
    ...serve calls...
    await mgr.restore(link)                                   # put the previous link back

Endpoints (docs: vobiz.ai/docs/applications, /applications/create-application,
/applications/attach-number, /applications/detach-number, /account-phone-number; all verified
against the published docs on 2026-10-09, NOT against the live account):

  GET    /Account/{id}/numbers                      -> {"items": [{"e164", "application_id", ...}]}
  GET    /Account/{id}/Application/?limit=&offset=  -> {"objects": [...], "meta": {"next": ...}}
  POST   /Account/{id}/Application/                 {app_name, answer_url, answer_method,
                                                     hangup_url, hangup_method} -> 201 {app_id}
  POST   /Account/{id}/Application/{app_id}/        partial update -> 200 {"message": "changed"}
  POST   /Account/{id}/numbers/{%2B..}/application  {application_id} -> 200   (attach)
  DELETE /Account/{id}/numbers/{%2B..}/application  -> 200                    (detach)

Properties (tested with mocked HTTP only; this module never talks to a real account in tests):
* idempotent: a second ``sync`` with nothing changed performs no write (GETs only);
* the previous link is persisted to ``state_path`` BEFORE the number is re-linked, so a crash
  (Ctrl+C, Codespace sleeping) can still be undone with ``friday listen --restore``;
* ``restore`` only touches the number if it still points at OUR application (someone else's
  later change is never overwritten), and never raises;
* only the Application named ``friday-front-door`` is ever created or edited; nothing is
  deleted (an unused application is harmless), no other number is touched.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger, mask_phone
from friday.voice._http import VendorHTTP
from friday.voice.telephony.sarvam import sarvam_token

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.vobiz.ai/api/v1"
APP_NAME = "friday-front-door"
ANSWER_PATH = "/voice/sarvam/inbound"  # tel.answer_xml: an unknown CallUUID is an inbound call
HANGUP_PATH = "/voice/sarvam/hangup"
PAGE = 100


def inbound_urls(public_base_url: str, secret: str) -> tuple[str, str]:
    """(answer_url, hangup_url) for ``FRIDAY_PUBLIC_BASE_URL``. The token scope is ``inbound``
    (the same one ``SarvamTelephony.url('inbound')`` signs), so the webhook routes accept it."""
    base = public_base_url.rstrip("/")
    if not base.startswith("https://"):
        raise ProviderError("vobiz", "the public URL must be https (callbacks are HTTPS only)")
    token = sarvam_token(secret, "inbound")
    return f"{base}{ANSWER_PATH}?token={token}", f"{base}{HANGUP_PATH}?token={token}"


@dataclass
class LinkState:
    number: str
    app_id: str
    previous_app_id: str | None  # None = the number had no application (detach on restore)
    previous_known: bool = True  # False = it already pointed at our app and we could not tell
    created_app: bool = False
    updated_app: bool = False
    attached: bool = False  # True = this run changed the link (restore has work to do)
    answer_url: str = ""

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["answer_url"] = self.answer_url.split("?")[0]  # never print the token
        return d


@dataclass
class RestoreResult:
    ok: bool
    action: str  # "reattached" | "detached" | "left as is" | "nothing to restore" | "failed"
    detail: str = ""


class VobizAppManager:
    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        state_path: Path | str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.auth_id = auth_id
        self.state_path = Path(state_path) if state_path else None
        self._http = VendorHTTP(
            "vobiz",
            base_url=base_url.rstrip("/"),
            headers={"X-Auth-ID": auth_id, "X-Auth-Token": auth_token},
            retries=0,  # writes are never retried blindly
            transport=transport,
        )
        self.writes: list[str] = []  # "METHOD path" of every write made (tests / summary)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ reads
    async def _json(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        resp = await self._http.request(method, f"/Account/{self.auth_id}{path}", **kw)
        if method != "GET":
            self.writes.append(f"{method} {path}")
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    async def number_entry(self, number: str) -> dict[str, Any]:
        data = await self._json("GET", "/numbers")
        items = data.get("items") or data.get("objects") or []
        for item in items:
            if (item.get("e164") or item.get("number")) == number:
                return item
        raise ProviderError("vobiz", f"{mask_phone(number)} is not a number on this Vobiz account")

    async def current_link(self, number: str) -> str | None:
        entry = await self.number_entry(number)
        return str(entry["application_id"]) if entry.get("application_id") else None

    async def find_app(self) -> dict[str, Any] | None:
        offset = 0
        while True:
            data = await self._json("GET", f"/Application/?limit={PAGE}&offset={offset}")
            objs = data.get("objects") or []
            for app in objs:
                if app.get("app_name") == APP_NAME:
                    return app
            if len(objs) < PAGE or not (data.get("meta") or {}).get("next"):
                return None
            offset += PAGE

    # ------------------------------------------------------------------ state file
    def _load(self) -> dict[str, Any] | None:
        if self.state_path is None or not self.state_path.is_file():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _save(self, state: LinkState) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(state) | {"answer_url": ""}
        self.state_path.write_text(json.dumps(data), encoding="utf-8")

    def _forget(self) -> None:
        if self.state_path is not None:
            self.state_path.unlink(missing_ok=True)

    def pending_restore(self) -> LinkState | None:
        """A link left behind by a run that did not restore (crash / Ctrl+C twice)."""
        raw = self._load()
        if not raw:
            return None
        try:
            return LinkState(**raw)
        except TypeError:
            return None

    # ------------------------------------------------------------------ sync
    async def sync(
        self, public_base_url: str, number: str, secret: str, *, dry_run: bool = False
    ) -> LinkState:
        answer_url, hangup_url = inbound_urls(public_base_url, secret)
        entry = await self.number_entry(number)
        current = str(entry["application_id"]) if entry.get("application_id") else None

        app = await self.find_app()
        created = updated = False
        if app is None:
            app_id = "(would be created)"
            if not dry_run:
                body = await self._json(
                    "POST",
                    "/Application/",
                    json={
                        "app_name": APP_NAME,
                        "answer_url": answer_url,
                        "answer_method": "POST",
                        "hangup_url": hangup_url,
                        "hangup_method": "POST",
                    },
                )
                app_id = str(body.get("app_id") or "")
                if not app_id:
                    raise ProviderError("vobiz", "no app_id in the create-application response")
            created = True
        else:
            app_id = str(app.get("app_id"))
            if (
                app.get("answer_url") != answer_url
                or app.get("hangup_url") != hangup_url
                or str(app.get("answer_method", "POST")).upper() != "POST"
                or str(app.get("hangup_method", "POST")).upper() != "POST"
                or app.get("enabled") is False
            ):
                if not dry_run:
                    await self._json(
                        "POST",
                        f"/Application/{app_id}/",
                        json={
                            "answer_url": answer_url,
                            "answer_method": "POST",
                            "hangup_url": hangup_url,
                            "hangup_method": "POST",
                            "enabled": True,
                        },
                    )
                updated = True

        # what to put back later: a crashed earlier run remembered it, else what is linked now
        saved = self.pending_restore()
        previous: str | None = current
        known = True
        if current == app_id:  # already ours
            if saved and saved.number == number and saved.app_id == app_id:
                previous, known = saved.previous_app_id, saved.previous_known
            else:
                previous, known = None, False
        state = LinkState(
            number=number,
            app_id=app_id,
            previous_app_id=previous,
            previous_known=known,
            created_app=created,
            updated_app=updated,
            attached=current != app_id,
            answer_url=answer_url,
        )
        if current != app_id and not dry_run:
            self._save(state)  # remember BEFORE touching the link
            path = f"/numbers/{quote(number, safe='')}/application"
            await self._json("POST", path, json={"application_id": app_id})
        elif current == app_id and not dry_run and (saved is None):
            self._save(state)
        log.info(
            "vobiz inbound link for %s: app %s (created=%s updated=%s attached=%s)",
            mask_phone(number), app_id, created, updated, state.attached,
        )
        return state

    # ------------------------------------------------------------------ restore
    async def restore(self, state: LinkState | None = None) -> RestoreResult:
        state = state or self.pending_restore()
        if state is None:
            return RestoreResult(True, "nothing to restore")
        try:
            current = await self.current_link(state.number)
            if current != state.app_id:
                self._forget()
                return RestoreResult(
                    True,
                    "left as is",
                    "the number no longer points at the Friday application "
                    "(changed by someone else)",
                )
            path = f"/numbers/{quote(state.number, safe='')}/application"
            if state.previous_app_id:
                await self._json("POST", path, json={"application_id": state.previous_app_id})
                self._forget()
                return RestoreResult(
                    True, "reattached", f"previous application {state.previous_app_id}"
                )
            await self._json("DELETE", path)
            self._forget()
            why = (
                ""
                if state.previous_known
                else " (the earlier link was not known: re-link it in the Vobiz console)"
            )
            return RestoreResult(True, "detached", "the number had no application before" + why)
        except (ProviderError, httpx.HTTPError) as e:
            return RestoreResult(
                False,
                "failed",
                f"{e}. The number may still point at a dead URL: run `friday listen --restore`.",
            )


# ================================================================================ offline fake


class FakeVobizAccount:
    """An in-memory Vobiz account behind ``httpx.MockTransport`` (tests and ``friday listen
    --simulate``): numbers, applications, attach / detach. Records every request in ``requests``.
    Never opens a socket."""

    def __init__(
        self,
        auth_id: str = "MA_TEST",
        numbers: dict[str, str | None] | None = None,
        applications: list[dict[str, Any]] | None = None,
    ) -> None:
        self.auth_id = auth_id
        self.numbers: dict[str, str | None] = dict(numbers or {})
        self.apps: dict[str, dict[str, Any]] = {a["app_id"]: dict(a) for a in applications or []}
        self.requests: list[tuple[str, str, Any]] = []
        self.fail: dict[tuple[str, str], int] = {}  # (METHOD, path-suffix) -> http status
        self._next = 1000

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    @property
    def writes(self) -> list[tuple[str, str, Any]]:
        return [r for r in self.requests if r[0] != "GET"]

    def _app_view(self, a: dict[str, Any]) -> dict[str, Any]:
        return {**a, "enabled": a.get("enabled", True)}

    def _handle(self, request: httpx.Request) -> httpx.Response:  # noqa: C901
        from urllib.parse import unquote

        method = request.method
        path = unquote(request.url.raw_path.decode().split("?")[0])
        body = json.loads(request.content) if request.content else None
        self.requests.append((method, path, body))
        for (m, suffix), status in self.fail.items():
            if m == method and path.endswith(suffix):
                return httpx.Response(status, json={"error": "injected failure"})
        base = f"/api/v1/Account/{self.auth_id}"
        if request.headers.get("x-auth-id") != self.auth_id:
            return httpx.Response(401, json={"error": "invalid credentials"})
        rest = path.removeprefix(base)
        if method == "GET" and rest == "/numbers":
            items = [
                {"e164": n, "application_id": a, "status": "active", "voice_enabled": True}
                for n, a in self.numbers.items()
            ]
            return httpx.Response(200, json={"items": items})
        if rest.startswith("/Application/"):
            tail = rest.removeprefix("/Application/").strip("/")
            if method == "GET" and not tail:
                q = request.url.params
                limit, offset = int(q.get("limit", 20)), int(q.get("offset", 0))
                objs = [self._app_view(a) for a in self.apps.values()]
                nxt = "more" if offset + limit < len(objs) else None
                return httpx.Response(
                    200, json={"objects": objs[offset : offset + limit], "meta": {"next": nxt}}
                )
            if method == "POST" and not tail:
                self._next += 1
                app_id = str(self._next)
                self.apps[app_id] = {"app_id": app_id, **(body or {})}
                created = {"api_id": "x", "app_id": app_id, "message": "created"}
                return httpx.Response(201, json=created)
            if method == "POST" and tail in self.apps:
                self.apps[tail].update(body or {})
                return httpx.Response(200, json={"api_id": "x", "message": "changed"})
            return httpx.Response(404, json={"error": "Application not found"})
        if rest.startswith("/numbers/") and rest.endswith("/application"):
            number = rest.removeprefix("/numbers/").removesuffix("/application")
            if number not in self.numbers:
                return httpx.Response(404, json={"error": "number not found"})
            if method == "POST":
                app_id = (body or {}).get("application_id")
                if app_id not in self.apps:
                    return httpx.Response(404, json={"error": "Application not found"})
                self.numbers[number] = app_id
                return httpx.Response(200, json={"message": "Number attached to application"})
            if method == "DELETE":
                self.numbers[number] = None
                return httpx.Response(200, json={"message": "Number detached from application"})
        return httpx.Response(404, json={"error": f"unhandled {method} {rest}"})
