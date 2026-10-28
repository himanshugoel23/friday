"""Read-only update status for the small server: ``GET /ops-status/{token}`` (docs/AUTOUPDATE.md).

The auto-updater (deploy/autoupdate.sh) writes a plain-text report; this serves it so the developer
can read it without a console. Off unless FRIDAY_OPS_STATUS_TOKEN is set (16+ chars). The report
holds no secrets: git commit ids and migration/doctor lines only.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

_DEFAULT_FILE = "/opt/friday/var/autoupdate/status.txt"
_MAX_BYTES = 60_000


def _token() -> str:
    # The server's .env is read by pydantic only, not exported to the process: look in both places.
    env = os.environ.get("FRIDAY_OPS_STATUS_TOKEN")
    return env or str(dotenv_values(".env").get("FRIDAY_OPS_STATUS_TOKEN") or "")


def ops_status_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{token}", response_class=PlainTextResponse)
    def status(token: str) -> PlainTextResponse:
        expected = _token()
        if len(expected) < 16 or not hmac.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(status_code=404, detail="Not Found")
        path = Path(os.environ.get("FRIDAY_OPS_STATUS_FILE", _DEFAULT_FILE))
        try:
            data = path.read_bytes()[-_MAX_BYTES:]
        except OSError:
            return PlainTextResponse("no report yet\n")
        return PlainTextResponse(data.decode("utf-8", "replace"))

    return router
