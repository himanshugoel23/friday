"""DLT-templated SMS (India): no free-form SMS, only registered templates.

* ``FakeSMS``  - records sends (simulator mode / tests).
* ``MSG91SMS`` - MSG91 Flow API (``/api/v5/flow``) with the DLT template id from
  ``Settings.sms_dlt_templates``; template params are sent as ``var1..varN``.

Owner: Backend Engineer A.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import httpx

from friday.core.clock import Clock, SystemClock
from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger, mask_phone
from friday.core.models import SendReceipt, TemplateRef, new_id

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

MSG91_BASE = "https://control.msg91.com"


class SentSMS:
    def __init__(self, to_phone: str, template: TemplateRef, dlt_template_id: str | None) -> None:
        self.to_phone = to_phone
        self.template = template
        self.dlt_template_id = dlt_template_id


class FakeSMS:
    name = "fake"

    def __init__(self, templates: dict[str, str] | None = None, clock: Clock | None = None) -> None:
        self.templates = templates or {}
        self.clock = clock or SystemClock()
        self.sent: list[SentSMS] = []
        self._ids = itertools.count(1)

    async def send_template(self, to_phone: str, template: TemplateRef) -> SendReceipt:
        tpl_id = self.templates.get(template.key)
        if tpl_id is None:
            return SendReceipt(
                message_id=new_id(), ok=False, error=f"no DLT template for {template.key!r}"
            )
        self.sent.append(SentSMS(to_phone, template, tpl_id))
        return SendReceipt(
            message_id=new_id(),
            provider_message_id=f"fake-sms.{next(self._ids)}",
            sent_at=self.clock.now(),
        )


class MSG91SMS:
    name = "msg91"

    def __init__(
        self,
        *,
        auth_key: str,
        sender_id: str,
        templates: dict[str, str],
        dlt_entity_id: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = MSG91_BASE,
        timeout_s: float = 15.0,
    ) -> None:
        self.sender_id = sender_id
        self.templates = templates
        self.dlt_entity_id = dlt_entity_id
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=timeout_s,
            headers={"authkey": auth_key, "accept": "application/json"},
        )

    async def send_template(self, to_phone: str, template: TemplateRef) -> SendReceipt:
        tpl_id = self.templates.get(template.key)
        msg_id = new_id()
        if tpl_id is None:
            return SendReceipt(message_id=msg_id, ok=False, error=f"no DLT template for {template.key!r}")
        recipient: dict[str, str] = {"mobiles": to_phone.lstrip("+")}
        for i, p in enumerate(template.params, start=1):
            recipient[f"var{i}"] = p[:30]  # DLT {#var#} max 30 chars
        body: dict[str, object] = {
            "template_id": tpl_id,
            "sender": self.sender_id,
            "short_url": "0",
            "recipients": [recipient],
        }
        if self.dlt_entity_id:
            body["DLT_TE_ID"] = tpl_id
        try:
            resp = await self._client.post("/api/v5/flow", json=body)
        except httpx.HTTPError as e:
            log.warning("msg91 send to %s failed: %s", mask_phone(to_phone), type(e).__name__)
            return SendReceipt(message_id=msg_id, ok=False, error=f"transport: {type(e).__name__}")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 or data.get("type") == "error":
            err = str(data.get("message") or f"http {resp.status_code}")[:200]
            log.warning("msg91 send to %s rejected: %s", mask_phone(to_phone), err)
            return SendReceipt(message_id=msg_id, ok=False, error=err)
        return SendReceipt(message_id=msg_id, provider_message_id=str(data.get("message") or ""))

    async def aclose(self) -> None:
        await self._client.aclose()


def build_fake_sms(c: Container) -> FakeSMS:
    return FakeSMS(dict(c.settings.sms_dlt_templates), c.clock)


def build_msg91_sms(c: Container) -> MSG91SMS:
    s = c.settings
    if not s.msg91_auth_key:
        raise ProviderError("msg91", "MSG91_AUTH_KEY not set")
    return MSG91SMS(
        auth_key=s.msg91_auth_key.get_secret_value(),
        sender_id=s.sms_sender_id,
        templates=dict(s.sms_dlt_templates),
        dlt_entity_id=s.dlt_entity_id,
    )
