"""A photo or PDF arrives: download, understand, ask "is this right?" (FRIDAY_DOCS_ENABLED).

Sits in the same inbound path as the voice-note hook (``api/inbound._active``, before the brain).
It consumes: an image/PDF message, a ``doc:`` button tap, and a typed correction while a fix is
open. Everything else passes through untouched. The download goes through the channel's
``fetch_media`` (host allow-list, size and type caps); the bytes are handed to
``DocumentService`` and dropped when the call returns. The caption of a file is ignored: it is
user text for the normal chat, never for this feature. Docs: docs/DOCUMENT_UNDERSTANDING.md.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MediaBlob, MessageKind, ReplyButton, User
from friday.docunderstand import copy
from friday.docunderstand.service import DocReply, DocumentService

log = get_logger(__name__)
Reply = Callable[[User, str, Sequence[ReplyButton]], Awaitable[None]]
FILE_KINDS = (MessageKind.IMAGE, MessageKind.DOCUMENT)


class DocsInbound:
    def __init__(
        self,
        *,
        service: DocumentService,
        fetch_media: Callable[[str], Awaitable[MediaBlob]] | None,
        reply: Reply,
        enabled_for: Callable[[User], bool] = lambda user: True,
        language_of: Callable[[User], Awaitable[str]] | None = None,
    ) -> None:
        self.service, self._fetch, self.reply = service, fetch_media, reply
        self.enabled_for, self._language_of = enabled_for, language_of

    async def on_inbound(self, user: User, msg: InboundMessage) -> InboundMessage | None:
        """The message to carry on with, or None when this module has answered it."""
        if not self.enabled_for(user):
            return msg
        lang = await self._language_of(user) if self._language_of else copy.DEFAULT_LANGUAGE
        if msg.kind == MessageKind.BUTTON_REPLY and (msg.button_id or "").startswith(
            copy.BUTTON_PREFIX
        ):
            out = await self.service.handle_button(user.id, lang, msg.button_id or "")
            return await self._send(user, out, msg)
        if msg.kind in FILE_KINDS and msg.media_url:
            return await self._file(user, msg, lang)
        if msg.kind == MessageKind.TEXT and msg.text:
            out = await self.service.handle_text(user.id, lang, msg.text)
            return await self._send(user, out, msg)
        return msg

    async def _file(self, user: User, msg: InboundMessage, lang: str) -> InboundMessage | None:
        if self._fetch is None:
            return await self._send(user, DocReply(copy.t("refuse.unavailable", lang)), msg)
        try:
            blob = await self._fetch(msg.media_url or "")
        except Exception as e:  # noqa: BLE001
            log.info("document download failed: %s", type(e).__name__)
            return await self._send(user, DocReply(copy.t("refuse.failed", lang)), msg)
        out = await self.service.handle_media(
            user.id, lang, blob.data, blob.mime or msg.media_mime or ""
        )
        del blob
        return await self._send(user, out, msg)

    async def _send(
        self, user: User, out: DocReply | None, msg: InboundMessage
    ) -> InboundMessage | None:
        if out is None:
            return msg
        await self.reply(user, out.text, out.buttons)
        return None
